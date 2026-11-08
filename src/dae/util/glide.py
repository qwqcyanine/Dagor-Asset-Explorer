"""Generate a Glide (gmod-glide, base_glide_tank) addon around a compiled War Thunder tank model."""
import json
import re
from math import pi, sqrt, isfinite
from os import path, makedirs
from statistics import median
import util.log as log
from util.enums import JET_PLUME_V
from util.vromfs import VROMFS

VERTEX_SCALE = 40 # same as parse.realres

# names absent from a skeleton are ignored by GeomNodeTree.getReducedBones
GLIDE_KEEP_BONES = {
	"bone_turret", "bone_gun", "bone_gun_barrel", "emtr_gun_flame", "bone_camera_driver",
	*(f"bone_mg_aa_{a}_{i:02d}" for a in "hv" for i in range(1, 3)), # roof machine gun mount
	*(f"{s}_{i:02d}" for s in "lr" for i in range(1, 21)),
	*(f"bone_wheel_{s}_{i:02d}" for s in "lr" for i in range(1, 21)),
	# the wheel meshes spin on their own bones: the track is skinned to bone_wheel_*, which only follows the suspension
	*(f"wheel_{s}_{i:02d}" for s in "lr" for i in range(1, 21)),
}

TRACK_R_SUFFIX = "_r"
GLIDE_KMH = 0.06858 # Glide's speedometer: km/h per unit/s
GLIDE_WEIGHT = 9.0 # Glide spring force per kg of mass at rest (sv_gravity 600 * 0.015 tick), measured in game
# stiff tank suspension: springs sag only REST_COMPRESSION under the hull's weight (so wheels barely droop and
# the hull rides up onto obstacles) and wheels can rise BUMP_TRAVEL above rest
REST_COMPRESSION = 2.0
# track rolling resistance (fraction of weight) on hard ground at top speed; Glide's is car tyre sized, ~0.1% for a tank
TRACK_ROLLING = 0.05
# Glide applies the front/rear power split twice (share / wheel count * share of torque): with PowerDistribution 0
# the wheels get 0.5 * 0.5 + 0.5 * 0.5 of the engine output, measured in game
GLIDE_POWER_SPLIT = 0.5
BUMP_TRAVEL = 10.0

def defaultOptions(blk:dict):
	"""Export options the user can edit, prefilled from the War Thunder vehicle blk."""
	if isAircraft(blk):
		fm = (blk or {}).get("fm") or {}

		return {
			"aircraft": True,
			"helicopter": isHelicopter(blk),
			"mass": aircraftMass(fm),
			"maxSpeed": 2400.0,
			"engineForce": 350.0,
		}

	blk = blk or {}
	phys = blk.get("VehiclePhys", {})
	mass = phys.get("Mass", {}).get("TakeOff", blk.get("mass", 20000))

	return {
		"singleFlow": phys.get("mechanics", {}).get("steerType", "clutch_braking") == "clutch_braking",
		"mass": min(float(mass), 50000), # GMod clamps physics mass to 50000
		"maxFwdSpeed": float(blk.get("maxFwdSpeed", 60)),
		"maxRevSpeed": float(blk.get("maxRevSpeed", 15)),
		"upgraded": True,
		"wheeled": isWheeled(blk),
	}

def isWheeled(blk:dict):
	"""Wheeled vehicle (armoured car, wheeled tank destroyer) rather than a tracked tank"""
	return (((blk or {}).get("VehiclePhys") or {}).get("mechanics") or {}).get("tracked") is False

def steering(blk:dict):
	"""{wheel mesh node: (bone it steers with, max deflection in degrees)} from the blk's suspension"""
	susp = ((blk or {}).get("VehiclePhys") or {}).get("suspension") or {}
	nodes = susp.get("steeringNodes") or {}

	return {k: (str(nodes.get(k, "")), float(v)) for k, v in (susp.get("steeringDeflection") or {}).items() if k.startswith("wheel_") and float(v)}

def hiddenNodes(blk:dict, upgraded:bool = True):
	"""Model nodes War Thunder hides for this modification state. Both armor kits are in the model on top of each other,
	so exporting all of them z-fights: `effects` hides the stock parts once a mod is researched, `disableModEffects` the mod parts before."""
	hidden = set()

	for mod in (blk or {}).get("modifications", {}).values():
		nodes = ((mod or {}).get("effects" if upgraded else "disableModEffects") or {}).get("hideNodes", {}).get("node", [])
		hidden.update([nodes] if isinstance(nodes, str) else nodes)

	return hidden

def glideCollisionNodes(names:list[str]):
	"""WT's simple cls_* hulls when present (the *_dm damage parts are too many convex pieces, studiomdl merges them into one hull), never the gun."""
	names = [n for n in names if n.startswith("cls_")] or names

	return {n for n in names if "gun" not in n}

def trackScroll(model, objs):
	"""Signed SMD V change per forward unit along the ground run of a track (0 if unknown)."""
	skeleton = model.skeleton
	faces = []

	for obj in objs:
		bone = skeleton.getNodeByName(obj.name) if skeleton is not None and not obj.skinned else None

		for f in obj.faces:
			faces.append([(*model.getVertex(i, True, bone), *model.getUV(i)) for i in f])

	if not faces:
		return 0.0

	# x is forward, y is up, uv at [3], [4]
	low = min(c[1] for f in faces for c in f)
	high = max(c[1] for f in faces for c in f)
	ratios = []

	for f in faces:
		if max(c[1] for c in f) > low + (high - low) * 0.25:
			continue

		for a, b in ((0, 1), (1, 2), (2, 0)):
			dx = f[b][0] - f[a][0]

			if abs(dx) > 0.5 and abs(f[b][3] - f[a][3]) < 1e-3:
				ratios.append((f[b][4] - f[a][4]) / dx)

	return median(ratios) if ratios else 0.0

def splitTrackMaterials(model):
	"""Rename right track materials (+TRACK_R_SUFFIX) so each side gets its own Source material. Returns {"l"|"r": (materials, vPerUnit)}."""
	tracks = {}

	for side in "lr":
		objs = [o for o in model if o.name.startswith(f"track_{side}")]

		if side == "r":
			for o in objs:
				o.materials = {k:v + TRACK_R_SUFFIX for k, v in o.materials.items()}

		tracks[side] = (sorted({v for o in objs for v in o.materials.values()}), trackScroll(model, objs))

	return tracks

def findGameRoot(assetPath:str):
	"""War Thunder install folder above an asset file, or None."""
	d = path.dirname(path.abspath(assetPath))

	while not path.exists(path.join(d, "aces.vromfs.bin")):
		parent = path.dirname(d)

		if parent == d:
			return None

		d = parent

	return d

def cacheHQTextures(gameRoot:str, textures:list[str]):
	"""Cache the full resolution copies War Thunder keeps in content.hq (and starter *-hq packs in content/base); the export picks the largest cached DDSx per name."""
	from glob import glob
	from parse.material import DDSxTexturePack2
	from util.assetcacher import AssetCacher

	want = {t.split("*")[0] for t in textures or ()}
	found = 0
	packs = (
		glob(path.join(gameRoot or "", "content.hq", "hq_tex", "res", "**", "*.dxp.bin"), recursive = True) +
		glob(path.join(gameRoot or "", "content", "base", "res", "**", "*-hq.dxp.bin"), recursive = True)
	) if want else ()

	for f in packs:
		try:
			for tex in DDSxTexturePack2(f).getPackedFiles():
				# re-exports would cache the same copy again
				if tex.name in want and all(c.getPixelCnt() < tex.getPixelCnt() for c in AssetCacher.getCachedAsset(type(tex), tex.name) or ()):
					AssetCacher.cacheAsset(tex)
					found += 1
		except Exception as e: # a broken pack only costs its textures
			log.log(f"Skipping {f}: {e}")

	return found

def findTankBlk(assetPath:str, modelName:str):
	"""Walk up from the asset file to the War Thunder root and read the tank blk whose model matches. Returns None if not found.
	Each weapon also gets "weaponBlk" (its gamedata blk) when readable."""
	d = findGameRoot(assetPath)

	if d is None:
		return None

	vfs = VROMFS(path.join(d, "aces.vromfs.bin"))
	low = modelName.lower()
	# blk files are named <country>_<model>.blk
	for f in vfs.files:
		if f.startswith("gamedata/units/tankmodels/") and f.count("/") == 3 and (f.endswith(f"_{low}.blk") or f.endswith(f"/{low}.blk")):
			blk = vfs.readBlk(f)

			if str(blk.get("model", "")).lower() == low:
				for w in weapons(blk):
					try:
						w["weaponBlk"] = vfs.readBlk(str(w.get("blk", "")).lower())
					except Exception:
						pass

				return blk

	return None

def gamePos(node):
	# WT is Y-up with +z left; Source is Z-up with +y left
	return (node.wtm[0][3] * VERTEX_SCALE, node.wtm[2][3] * VERTEX_SCALE, node.wtm[1][3] * VERTEX_SCALE)

def vec(p):
	return f"Vector( {p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f} )"

def weapons(blk:dict):
	w = (blk or {}).get("commonWeapons", {}).get("Weapon")

	return [x for x in (w if isinstance(w, list) else [w]) if isinstance(x, dict)]

def firstWeapon(blk:dict):
	return next(iter(weapons(blk)), {})

def machineGun(blk:dict, group:str):
	"""First weapon of a trigger group ("coaxial", "machinegun") or {}"""
	return next((w for w in weapons(blk) if w.get("triggerGroup") == group), {})

def weaponEvent(w:dict):
	wb = w.get("weaponBlk", {})

	return f"event:/{wb['sound_pathStudio']}/{wb['sound']}" if "sound_pathStudio" in wb and "sound" in wb else None

SOUND_BANKS = ("tanks_engines", "tanks_weapons", "tanks_effects")
WEAPON_PARAMS = {"on_shot": 1, "guns": 1} # FMOD weapon events only sound while these are set
DEFAULT_RELOAD_SFX = "grd_cannon_reload"
MANUAL_TRAVERSE = 3.0 # deg/s, gameparams.blk difficulty_settings/damageModel/realistic/brokenHorTurretDriveSpeed

def manualTraverseSpeed(gameRoot:str):
	"""Yaw speed (deg/s) of a hand-cranked turret in realistic battles: WT uses it when the turret drive has no power or is broken"""
	try:
		return float(VROMFS(path.join(gameRoot, "aces.vromfs.bin")).readBlk("config/gameparams.blk")["difficulty_settings"]["damageModel"]["realistic"]["brokenHorTurretDriveSpeed"])
	except (OSError, KeyError, TypeError, ValueError):
		return MANUAL_TRAVERSE

def reloadSfx(gameRoot:str, w:dict):
	"""(FMOD event, sound length) of a cannon's reload, from config/sound_studio.blk"""
	from util.vromfs import VROMFS

	reloads = VROMFS(path.join(gameRoot, "aces.vromfs.bin")).readBlk("config/sound_studio.blk").get("reloads", {})
	r = reloads.get(w.get("weaponBlk", {}).get("sfxReloadBullet", DEFAULT_RELOAD_SFX)) or reloads.get(DEFAULT_RELOAD_SFX)

	return (f"event:/{r['path']}/{r['event']}", float(r.get("time", 0))) if r else (None, 0.0)

def cannonReload(w:dict):
	"""Seconds between cannon shots (blk shotFreq is per second, an aced crew / autoloader)"""
	return 1 / max(float(w.get("weaponBlk", {}).get("shotFreq", 0.5)), 0.05)

def soundEvents(blk:dict, soundConfig:dict = None):
	"""{role: FMOD event path} of a tank blk, resolving engine aliases through WT's sound configuration."""
	snd = (blk or {}).get("sound", {})
	engine = str(snd.get("EngineName", ""))
	engine = f"event:/ground/engines/{engine[len('engine_'):] if engine.startswith('engine_') else engine}"
	events = {
		"engine": f"{engine}/engine",
		"start": f"{engine}/engine_start",
		"stop": f"{engine}/engine_stop",
		"tracks": f"event:/{snd.get('TrackSoundPathStudio', 'ground/engines')}/{snd.get('TrackSoundName')}",
		"turret": f"event:/ground/effects/{snd.get('turret_turn')}",
		"cannon": weaponEvent(firstWeapon(blk)),
	}

	cfg = (soundConfig or {}).get(snd.get("EngineName"), {})
	for role, group, keys in (("engine", "outside", ("eventBack", "eventFront")), ("start", "effects", ("eventStart",)), ("stop", "effects", ("eventStop",))):
		mapping = cfg.get(group, {})
		name = next((mapping[k] for k in keys if mapping.get(k)), None)
		if mapping.get("path") and name:
			events[role] = f"event:/{mapping['path']}/{name}"

	for role in ("coaxial", "machinegun"):
		events[role] = weaponEvent(machineGun(blk, role))

	return {k:v for k, v in events.items() if v}

def exportSounds(gameRoot:str, blk:dict, outDir:str):
	"""Render the tank's WT FMOD events into wavs in outDir (<addon>/sound/...) the way the game mixes them.
	Returns {"engine": [(stem, controllers)], "start": stem, ..., "cannon": [stems], "reload": (stem, delay), "coaxial": ([stems], None)}; {} without banks."""
	from util import wtsound

	soundDir = path.join(gameRoot, "sound")

	if not path.exists(path.join(soundDir, "masterbank.strings.bank")):
		return {}

	guids = wtsound.readStrings(path.join(soundDir, "masterbank.strings.bank"))
	try:
		soundConfig = VROMFS(path.join(gameRoot, "aces.vromfs.bin")).readBlk("config/sound_studio.blk")
	except (OSError, KeyError, ValueError) as e:
		log.log(f"Ground engine sound configuration unavailable: {e}", 2)
		soundConfig = {}
	events = soundEvents(blk, soundConfig)
	reloadEvent, reloadLength = reloadSfx(gameRoot, firstWeapon(blk)) if "cannon" in events else (None, 0.0)

	if reloadEvent:
		events["reload"] = reloadEvent

	banks, roles = {}, {}
	makedirs(outDir, exist_ok = True)

	def find(event):
		guid = guids.get(event)

		for name in SOUND_BANKS if guid else ():
			if name not in banks:
				banks[name] = wtsound.SoundBank(soundDir, name)

			if guid in banks[name].events:
				bank = banks[name]
				bank.decode(bank.walk(guid))
				return bank, guid

		return None, None

	def write(stem, pcm, loop = False, maxSeconds = 15):
		if len(pcm) and float(abs(pcm).max()) > 1e-4:
			wtsound.writeWav(path.join(outDir, f"{stem}.wav"), wtsound.finish(pcm, maxSeconds), wtsound.SOURCE_RATE, loop)
			return stem

	def render(role, params = None, length = None, variants = 1):
		bank, guid = find(events.get(role))

		if not bank:
			return []

		return [stem for v in range(variants) if (stem := write(f"{role}_{v}" if variants > 1 else role, wtsound.Renderer(bank, params, seed = v).event(guid, length, v), length is not None))]

	bank, guid = find(events.get("engine"))

	if bank:
		roles["engine"] = []

		for k, (inst, ctrl) in enumerate(wtsound.engineLayers(bank, guid)):
			stem = write(f"engine_{k}", bank.pcm(bank.instruments[inst]), True, None)

			if stem:
				roles["engine"].append((stem, ctrl))

	for role, params, length in (("start", None, None), ("stop", None, None), ("tracks", {"speed": 50}, 6.0), ("turret", {"velH": 25, "velV": 10}, 6.0)):
		roles[role] = next(iter(render(role, params, length)), None)

	# the turret event plays a hand-crank sub-event while the drive has no power (velH 4: past the start/stop one-shots)
	bank, guid = find(events.get("turret"))
	manual = bank and wtsound.subEvent(bank, guid, "no_power")
	roles["turret_manual"] = manual and write("turret_manual", wtsound.Renderer(bank, {"velH": 4}).event(manual, 6.0), True)

	roles["cannon"] = render("cannon", WEAPON_PARAMS, variants = 3)
	reload = next(iter(render("reload")), None)
	# WT starts the reload sound `time` seconds before the gun is ready
	roles["reload"] = reload and (reload, max(cannonReload(firstWeapon(blk)) - reloadLength, 0.0))

	for role in ("coaxial", "machinegun"):
		roles[role] = (render(role, WEAPON_PARAMS, variants = 6), None)

	return roles

def getWheels(skeleton):
	"""Every road wheel, front to rear per side: [(name, pos, index on side, count on side, node)] left side first.
	All of them are physics wheels, so an obstacle under any road wheel lifts the hull."""
	wheels = []

	for side in "lr":
		# wheeled vehicles name trailing-arm wheels bone_wheel_l_back_03
		nodes = sorted((n for n in skeleton.getNodes() if re.fullmatch(f"bone_wheel_{side}_(back_)?\\d+", n.name)), key = lambda n: -n.wtm[0][3])
		wheels.extend((n.name, gamePos(n), i, len(nodes), n) for i, n in enumerate(nodes))

	return wheels

def gearbox(blk:dict, options:dict):
	"""(forward gear ratios first to top, reverse ratio, top gear wheel force at full power in N or None) from the blk.
	War Thunder: speed per gear = max rpm / (ratio * main * side gear) * wheel circumference, so ratios only need scaling by the differential;
	at the redline the engine delivers its rated power, force = power / speed."""
	phys = (blk or {}).get("VehiclePhys", {}) or {}
	ratios = ((phys.get("mechanics") or {}).get("gearRatios") or {}).get("ratio") or []
	gears = sorted((min(r, 20) for r in ratios if r > 0), reverse = True) or [3.0] # Glide.MAX_GEAR_RATIO
	# reverse keeps the user's reverse speed
	revRatio = min(gears[-1] * options["maxFwdSpeed"] / max(options["maxRevSpeed"], 1), 20)
	engine = phys.get("engine") or {}
	hp = engine.get("horsePowers")
	force = float(hp) * 745.7 / (options["maxFwdSpeed"] / 3.6) if hp else None
	# constant power from max rpm down to min rpm: torque rises by their ratio (gas turbines, diesels less so but same model)
	torqueRise = min(max(float(engine.get("maxRPM", 1)) / float(engine.get("minRPM", 1) or 1), 1.0), 3.0)

	return gears, revRatio, force, torqueRise

def spinBone(wheelBone):
	"""Bone to spin for a bone_wheel_*: its wheel mesh node when kept (the track follows bone_wheel_* itself)"""
	mesh = next((c for c in wheelBone.children if re.fullmatch("wheel_[lr]_\\d+", c.name)), None)

	return mesh.name if mesh else wheelBone.name

def suspensionBones(wheels:list):
	"""[(bone_suspension_* name, 1-based index of its road wheel in `wheels`)]"""
	return [(w[4].parent.name, k + 1) for k, w in enumerate(wheels) if w[4].parent is not None and w[4].parent.name.startswith("bone_suspension_")]

def isDescendant(n, ancestor):
	while n is not None:
		if n is ancestor or n.name == ancestor.name:
			return True
		n = n.parent

	return False

def caliber(w:dict):
	"""mm from a weapon blk path like .../12_7mm_NSV...blk (0 if unknown)"""
	m = re.search(r"/(\d+)(?:_(\d+))?mm", str(w.get("blk", "")))

	return float(f"{m[1]}.{m[2] or 0}") if m else 0.0

def engineLayers(engine:list, soundDir:str):
	"""stream:AddLayer lines from exportSounds' engine layers (controllers come from the WT FMOD event)"""
	fmt = lambda c: f'{{ "{c[0]}", {c[1]:.3f}, {c[2]:.3f}, "{c[3]}", {c[4]:.3f}, {c[5]:.3f} }}'

	return [f'        stream:AddLayer( "{stem}", "{soundDir}/{stem}.wav", {{ {", ".join(map(fmt, ctrl))} }} )' for stem, ctrl in engine]

def generateLua(className:str, printName:str, modelPath:str, skeleton, blk:dict, tracks:dict = None, options:dict = None, sounds:dict = None, manualYaw:float = MANUAL_TRAVERSE):
	node = skeleton.getNodeByName
	turret = node("bone_turret")
	gun = node("bone_gun")
	muzzle = node("emtr_gun_flame") or node("bone_gun_barrel")
	driver = node("bone_camera_driver")
	weapon = firstWeapon(blk)
	limits = weapon.get("limits", {})
	pitch = limits.get("pitch", [-8.0, 16.0])
	options = {**defaultOptions(blk), **(options or {})}
	mass = min(float(options["mass"]), 50000)
	massScale = mass / 20000 # base_glide_tank is tuned for its 20000 kg default
	wheels = getWheels(skeleton)
	wheeled = isWheeled(blk)
	steer = steering(blk) if wheeled else {}
	maxSteer = max((a for _, a in steer.values()), default = 30.0)
	radius = max(wheels[0][1][2], 5) if wheels else 15
	gears, revRatio, topForce, torqueRise = gearbox(blk, options)
	top = gears[-1]
	# Glide couples engine rpm = wheel rpm * gear * differential * 60 / tau (sic), so the redline (6000) in top gear caps the speed
	maxWheelRPM = options["maxFwdSpeed"] / GLIDE_KMH / radius * 60 / (2 * pi)
	diff = 6000 / (top * maxWheelRPM * 60 / (2 * pi))
	# total wheel force = engine torque * gear * differential (base_glide_tank's efficiency is 1); force units are GLIDE_WEIGHT per kg-weight
	# without engine data: base_glide_tank's single gear wheel force, scaled to the mass
	topForce = topForce * GLIDE_WEIGHT / 9.81 if topForce else 35000 * massScale * 0.75 * 3
	maxTorque = topForce / (top * diff * GLIDE_POWER_SPLIT)
	# Glide's rolling resistance is surface value (0.05 hard .. 0.2 dirt) * speed per wheel, in absolute force units
	resistScale = mass * GLIDE_WEIGHT * TRACK_ROLLING / (max(len(wheels), 1) * 0.05 * options["maxFwdSpeed"] / GLIDE_KMH)
	# per wheel forces were calibrated on 6 physics wheels: keep the totals with any wheel count
	perWheel = 6 / max(len(wheels), 1)
	# put the wheels where the model has them once the springs settle
	springStrength = mass * GLIDE_WEIGHT / (max(len(wheels), 1) * REST_COMPRESSION)
	# keep base_glide_tank's damping ratio: critical damping grows with sqrt(stiffness)
	baseSpring = 6000 * massScale * perWheel
	springDamper = 30000 * massScale * perWheel * sqrt(springStrength / baseSpring)
	lift = BUMP_TRAVEL
	suspension = suspensionBones(wheels)
	turretPos = gamePos(turret) if turret else (0, 0, 50)
	seatPos = gamePos(driver) if driver else (0, 0, turretPos[2] * 0.5)

	wheelLines = []

	firstRight = next((k + 1 for k, w in enumerate(wheels) if w[0].startswith("bone_wheel_r_")), 1)
	wheelBoneLines = []

	for k, (name, p, i, cnt, n) in enumerate(wheels):
		spin = spinBone(n)
		steerBone, angle = steer.get(spin, ("", 0.0))
		# wheeled: War Thunder's per wheel deflection; tracked: Glide's skid steer pushes the end wheels sideways
		mult = round(angle / maxSteer, 3) if wheeled else (1 if i == 0 else (-1 if i == cnt - 1 else 0))
		wheelLines.append(f"        self:CreateWheel( {vec((p[0], p[1], p[2] + lift))}, {{ radius = {max(p[2], 5):.1f}, steerMultiplier = {mult} }} ){':SetSoundsEnabled( false )' if mult == 0 else ''}")
		# a track rolls all its road wheels with its first one
		drive = k + 1 if wheeled else (firstRight if name.startswith("bone_wheel_r_") else 1)
		# steering a bone that also spins would turn the axle off the wheel
		steerBone = steerBone or name
		angle = angle if steerBone != spin else 0.0
		wheelBoneLines.append(f'        {{ spin = "{spin}", steer = "{steerBone}", wheel = {drive}, angle = {angle:.1f} }},')
	cdMaterials = modelPath[:-len(".mdl")]
	trackLines = []

	for side, wheelIdx in (("l", 1), ("r", firstRight)):
		mats, vPerUnit = (tracks or {}).get(side, ((), 0.0))

		if mats and vPerUnit and wheelIdx <= len(wheels):
			# Source flips V (t = 1 - v); wheel spin (degrees) drops as the tank moves forward
			scale = vPerUnit * pi / 180 * max(wheels[wheelIdx - 1][1][2], 5)
			matList = ", ".join(f'"{cdMaterials}/{m}"' for m in mats)
			trackLines.append(f"        {{ wheel = {wheelIdx}, scale = {scale:.6f}, materials = {{ {matList} }} }},")
	sounds = sounds or {}
	soundDir = f"wt/{className}"
	soundShared, soundClient, soundServer = [], [], []

	def soundScript(name, stems, level, volume = 1.0):
		waves = ", ".join(f'"){soundDir}/{s}.wav"' for s in stems) # ")" = spatialized
		soundShared.append(f'sound.Add( {{ name = "{className}.{name}", channel = CHAN_STATIC, volume = {volume}, level = {level}, pitch = {{ 95, 105 }}, sound = {{ {waves} }} }} )')
		return f"{className}.{name}"

	if sounds.get("engine"):
		soundClient += ["    function ENT:OnCreateEngineStream( stream )", *engineLayers(sounds["engine"], soundDir), "    end"]

	for role, field in (("tracks", "TrackSound"), ("turret", "TurrentMoveSound"), ("turret_manual", "WTTurretManualSound"), ("start", "StartSound"), ("stop", "StoppedSound")):
		if sounds.get(role):
			soundClient.append(f'    ENT.{field} = "{")" if role == "tracks" else ""}{soundDir}/{sounds[role]}.wav"')

	if sounds.get("start"):
		soundClient.append('    ENT.StartedSound = ""')

	if sounds.get("cannon"):
		soundServer.append(f'    ENT.TurretFireSound = "{soundScript("Cannon", sounds["cannon"], 140)}"')

	if sounds.get("reload"):
		reloadSound = soundScript("Reload", [sounds["reload"][0]], 75)
		soundServer += [
			"",
			"    function ENT:OnWeaponFire( weapon, slotIndex )",
			"        if slotIndex == 1 and self:WaterLevel() <= 2 and not self.isCannonInsideWall then",
			f'            timer.Simple( {sounds["reload"][1]:.2f}, function() if IsValid( self ) then self:EmitSound( "{reloadSound}" ) end end )',
			"        end",
			"",
			"        return BaseClass.OnWeaponFire( self, weapon, slotIndex )",
			"    end",
		]

	mgSounds = {g: soundScript(g.capitalize(), sounds[g][0], 100, 0.8) if sounds.get(g, ((), None))[0] else "" for g in ("coaxial", "machinegun")}

	# coaxial MG: second driver weapon, fired along the cannon from its spot on the turret
	coax, aa = machineGun(blk, "coaxial"), machineGun(blk, "machinegun")
	coaxNode = (node(coax.get("flash", "")) or node(coax.get("emitter", ""))) if coax else None
	aaYaw = node(aa.get("turret", {}).get("head", "")) if aa else None
	aaPitch = node(aa.get("turret", {}).get("gun", "")) if aa else None
	aaFlash = node(aa.get("flash", "")) if aa else None
	gunPivot = gamePos(gun) if gun else turretPos
	rel = lambda n, base: vec([a - b for a, b in zip(gamePos(n), base)])

	# first person from WT's camera tags: the gunner's turns with the turret, the commander's with the roof MG cupola
	gunnerCam = node("bone_camera_gunner") or driver
	commanderCam = node("bone_commander_sight_v")
	commanderCam = commanderCam if commanderCam and aaYaw and isDescendant(commanderCam, aaYaw) else None
	firstPerson = [
		"-- first person from War Thunder's camera tags (bone_camera_gunner turns with the turret, bone_commander_sight_v with the roof MG cupola)",
		"local fpPos, fpYaw, fpCupola = Vector(), Angle(), Angle()",
		"",
		"function ENT:GetFirstPersonOffset( seatIndex, localEyePos )",
		"    fpYaw[2] = self.currentTurretAng and self.currentTurretAng[2] or self:GetTurretAngle()[2]",
		"",
	]

	if commanderCam:
		firstPerson += [
			"    if seatIndex == 2 then",
			"        local mg = self:GetWTMachineGun()",
			f"        fpPos:Set( {rel(commanderCam, gamePos(aaYaw))} )",
			"",
			"        if IsValid( mg ) then",
			"            fpCupola[2] = mg:GetLastBodyAngle()[2] - fpYaw[2]",
			"            fpPos:Rotate( fpCupola )",
			"        end",
			"",
			f"        fpPos:Add( {rel(aaYaw, turretPos)} )",
			"        fpPos:Rotate( fpYaw )",
			"        fpPos:Add( self.TurretOffset )",
			"",
			"        return fpPos",
			"    end",
			"",
		]

	firstPerson += [
		f"    fpPos:Set( {rel(gunnerCam, turretPos) if gunnerCam else 'Vector( 0, 0, 40 )'} )",
		"    fpPos:Rotate( fpYaw )",
		"    fpPos:Add( self.TurretOffset )",
		"",
		"    return fpPos",
		"end",
	]
	weaponLines = [f"        self.weapons[1].FireDelay = {cannonReload(firstWeapon(blk)):.2f} -- WT reload"]

	def mgStats(w):
		wb = w.get("weaponBlk", {})
		return 1 / max(float(wb.get("shotFreq", 10)), 0.1), int(wb.get("bulletsCartridge", wb.get("bullets", 0)) or 0), float(wb.get("reloadTime", 5)), round(max(caliber(w), 5) * 2.5)

	if coaxNode:
		delay, ammo, reload, damage = mgStats(coax)
		offset = [a - b for a, b in zip(gamePos(coaxNode), gunPivot)] # follows the gun elevation
		weaponLines += [
			f"        self.coaxOffset = {vec(offset)}",
			f'        self:CreateWeapon( "base", {{ FireDelay = {delay:.3f}, MaxAmmo = {ammo}, ReloadDelay = {reload:.1f}, Damage = {damage}, SingleShotSound = "{mgSounds["coaxial"]}", PrimaryAttack = FireCoaxial }} )',
		]

	if aaPitch:
		delay, ammo, reload, damage = mgStats(aa)
		pitchLimits = aa.get("limits", {}).get("pitch", [-10.0, 60.0])
		weaponLines += [
			"",
			"        -- seat 2: commander on the roof machine gun",
			f"        self:CreateSeat( {vec(turretPos)}, Angle( 0, 270, 0 ), Vector( 0, -150, 0 ), true )",
			f"        self.mgOffset = {vec([a - b for a, b in zip(gamePos(aaPitch), turretPos)])}",
			"        local mg = Glide.CreateTurret( self, self.TurretOffset + self.mgOffset, Angle() )",
			f"        mg:SetFireDelay( {delay:.3f} )",
			f"        mg:SetBulletOffset( {vec([a - b for a, b in zip(gamePos(aaFlash), gamePos(aaPitch))] if aaFlash else (30, 0, 0))} )",
			f"        mg:SetMinPitch( {-float(pitchLimits[1]):.1f} )",
			f"        mg:SetMaxPitch( {-float(pitchLimits[0]):.1f} )",
			f'        mg:SetSingleShotSound( "{mgSounds["machinegun"]}" )',
			'        mg:SetShootLoopSound( "" )',
			f"        mg.BulletDamage = {damage}",
			"        Glide.HideEntity( mg, true )",
			"        Glide.HideEntity( mg:GetGunBody(), true )",
			"        self:SetWTMachineGun( mg )",
		]

	rollingLines = [] if wheeled else [
		"",
		"        -- tracks: scale Glide's per surface rolling resistance up (also for surfaces it has no entry for)",
		"        for id, r in pairs( self.surfaceResistance ) do",
		f"            self.surfaceResistance[id] = r * {resistScale:.2f}",
		"        end",
		"",
		f"        setmetatable( self.surfaceResistance, {{ __index = function() return {0.05 * resistScale:.3f} end }} )",
	]
	suspensionLines = [f'        {{ bone = "{name}", wheel = {k} }},' for name, k in suspension]
	nl = "\n"

	return f'''AddCSLuaFile()

-- Generated by Dagor Asset Explorer
ENT.Type = "anim"
ENT.Base = "base_glide_tank"
ENT.PrintName = "{printName}"

ENT.GlideCategory = "War Thunder"
ENT.ChassisModel = "{modelPath}"

ENT.CanSwitchHeadlights = false
ENT.CanSwitchTurnSignals = false

ENT.ChassisMass = {mass:.0f}
ENT.TurretOffset = {vec(turretPos)}
ENT.PitchAngMax = {-float(pitch[1]):.1f}
ENT.PitchAngMin = {-float(pitch[0]):.1f}
ENT.MaxYawSpeed = {float(weapon.get("speedYaw", 50)):.1f}
-- turning in place uses the raw engine torque, which is scaled down for the differential below
ENT.TurnInPlaceTorqueMultiplier = {35000 * massScale * 3 / maxTorque:.2f}

DEFINE_BASECLASS( "base_glide_tank" )

function ENT:GetGears()
    return {{
        [-1] = {revRatio:.2f}, -- Reverse ({options["maxRevSpeed"]:.0f} km/h)
        [0] = 0,
{nl.join(f"        [{k + 1}] = {g:.2f}, -- {options['maxFwdSpeed'] * top / g:.0f} km/h" for k, g in enumerate(gears))}
    }}
end

-- Glide's spawn menu only lists categories registered here
list.Set( "GlideCategories", "War Thunder", {{ name = "War Thunder", icon = "glide/icons/tank.png" }} )

function ENT:SetupDataTables()
    BaseClass.SetupDataTables( self )
    self:NetworkVar( "Entity", "WTMachineGun" )
end

-- original War Thunder sounds
{nl.join(soundShared)}

{nl.join(firstPerson)}

-- War Thunder: without engine power the turret drive is hand-cranked (realistic broken-drive speed)
ENT.WTManualYawSpeed = {manualYaw:.1f}
ENT.WTManualPitchSpeed = {manualYaw * float(weapon.get("speedPitch", 40)) / max(float(weapon.get("speedYaw", 50)), 1):.1f}
local POWERED_YAW_SPEED = ENT.MaxYawSpeed

function ENT:UpdateTurret( driver, dt, currentAng )
    local powered = self:GetEngineState() == 2
    local lastPitch = currentAng[1]

    self.MaxYawSpeed = powered and POWERED_YAW_SPEED or self.WTManualYawSpeed

    local ang, isAimingAtTarget = BaseClass.UpdateTurret( self, driver, dt, currentAng )

    if not powered then
        local step = self.WTManualPitchSpeed * dt
        ang[1] = lastPitch + math.Clamp( math.NormalizeAngle( ang[1] - lastPitch ), -step, step )
    end

    return ang, isAimingAtTarget
end

if CLIENT then
    ENT.CameraOffset = Vector( -450, 0, {turretPos[2] + 120:.1f} )
    ENT.WTHideCrew = true
{nl.join(soundClient)}

    -- no engine power: no servo whine, the hand-crank sound instead (silent if the game has none)
    function ENT:OnUpdateMisc()
        local powered = self:GetEngineState() == 2
        self.WTTurretPoweredSound = self.WTTurretPoweredSound or self.TurrentMoveSound
        local snd = powered and self.WTTurretPoweredSound or self.WTTurretManualSound or self.WTTurretPoweredSound

        if snd ~= self.TurrentMoveSound then
            if self.turretSound then
                self.turretSound:Stop()
                self.turretSound = nil
            end

            self.TurrentMoveSound = snd
        end

        local lastYaw = self.currentTurretAng[2]

        BaseClass.OnUpdateMisc( self )

        -- Glide's volume is for powered speeds (full at 20 deg/s)
        if not powered and self.turretSound then
            local yawSpeed = math.abs( math.NormalizeAngle( self.currentTurretAng[2] - lastYaw ) ) / math.max( FrameTime(), 0.001 )
            local volume = self.WTTurretManualSound and math.Clamp( yawSpeed / self.WTManualYawSpeed, 0, 1 ) or 0

            self.turretSound:ChangeVolume( volume * self.TurrentMoveVolume )
        end
    end

    -- the crew sits inside the tank
    hook.Add( "PrePlayerDraw", "WTGlide.HideCrew", function( ply )
        local vehicle = ply:GlideGetVehicle()

        if IsValid( vehicle ) and vehicle.WTHideCrew then return true end
    end )

    local TRACKS = {{
{nl.join(trackLines)}
    }}

    for _, t in ipairs( TRACKS ) do
        for i, name in ipairs( t.materials ) do
            local mat = Material( name )
            t.materials[i] = not mat:IsError() and mat or nil
        end
    end

    local trackMatrix = Matrix()
    local trackOffset = Vector()

    function ENT:Draw( flags )
        for i, t in ipairs( TRACKS ) do
            trackOffset[2] = self.trackScroll and self.trackScroll[i] or 0
            trackMatrix:SetTranslation( trackOffset )

            for _, mat in pairs( t.materials ) do
                mat:SetMatrix( "$basetexturetransform", trackMatrix )
                mat:SetMatrix( "$bumptransform", trackMatrix )
            end
        end

        BaseClass.Draw( self, flags )
    end

    -- road wheels ride the ground like War Thunder's suspension: the track is skinned to them
    local SUSPENSION = {{
{nl.join(suspensionLines)}
    }}
    local WHEEL_LIFT = {lift:.1f} -- physics wheels are mounted this far above the model's wheel centres
    local suspensionPos = Vector()

    -- each road wheel follows its physics wheel, so the hull carries what the tracks show
    function ENT:UpdateSuspension()
        if not self.suspensionBones then return end

        for i, s in ipairs( SUSPENSION ) do
            local bone = self.suspensionBones[i]

            if bone then
                suspensionPos[2] = self:GetWheelOffset( s.wheel ) + WHEEL_LIFT -- bones are Y-up
                self:ManipulateBonePosition( bone, suspensionPos, false )
            end
        end
    end

    -- spin: rolls with physics wheel `wheel`; steer: turns by `angle` degrees at full steering (War Thunder's deflection)
    local WHEELS = {{
{nl.join(wheelBoneLines)}
    }}

    function ENT:OnActivateMisc()
        self.wheelBones = {{}}

        for i, w in ipairs( WHEELS ) do
            self.wheelBones[i] = {{ spin = self:LookupBone( w.spin ), steer = w.angle ~= 0 and self:LookupBone( w.steer ) or nil }}
        end

        self.suspensionBones = {{}}

        for i, s in ipairs( SUSPENSION ) do
            self.suspensionBones[i] = self:LookupBone( s.bone )
        end

        self.mgYawBone = self:LookupBone( "{aaYaw.name if aaYaw else ""}" )
        self.mgPitchBone = self:LookupBone( "{aaPitch.name if aaPitch else ""}" )
    end

    local spinAng, steerAng = Angle(), Angle()
    local mgAng = Angle()

    function ENT:OnUpdateAnimations()
        if not self.wheelBones then return end

        self.trackScroll = self.trackScroll or {{}}
        self.lastTrackSpin = self.lastTrackSpin or {{}}

        for i, t in ipairs( TRACKS ) do
            local spin = self:GetWheelSpin( t.wheel )
            local delta = ( spin - ( self.lastTrackSpin[i] or spin ) + 180 ) % 360 - 180

            self.trackScroll[i] = ( ( self.trackScroll[i] or 0 ) + delta * t.scale ) % 1
            self.lastTrackSpin[i] = spin
        end

        self:UpdateSuspension()

        -- bones are Y-up (studiomdl $upaxis Y): rolling is around the bone's Z axis, steering around its Y axis (pitch slot)
        local steering = self:GetSteering()

        for i, w in ipairs( WHEELS ) do
            local b = self.wheelBones[i]

            if b.spin then
                spinAng[2] = self:GetWheelSpin( w.wheel )
                self:ManipulateBoneAngles( b.spin, spinAng, false )
            end

            if b.steer then
                steerAng[1] = -steering * w.angle
                self:ManipulateBoneAngles( b.steer, steerAng, false )
            end
        end

        -- roof machine gun: its body angle is relative to the hull, the bones to the turret
        local mg = self:GetWTMachineGun()

        if IsValid( mg ) and self.mgYawBone and self.mgPitchBone and self.currentTurretAng then
            local bodyAng = mg:GetLastBodyAngle()

            mgAng[1] = math.NormalizeAngle( bodyAng[2] - self.currentTurretAng[2] )
            mgAng[2] = 0
            self:ManipulateBoneAngles( self.mgYawBone, mgAng, false )

            mgAng[1] = 0
            mgAng[2] = -math.NormalizeAngle( bodyAng[1] )
            self:ManipulateBoneAngles( self.mgPitchBone, mgAng, false )
        end
    end
end

if SERVER then
    -- Glide's torque only rises with rpm (a Clamp with min > max pins it to max), but War Thunder engines
    -- give constant power: torque grows as rpm falls, up to MinRPMTorque, which is what climbs steep slopes
    function ENT:GetTransmissionTorque( gear, minTorque, maxTorque )
        if minTorque <= maxTorque then
            return BaseClass.GetTransmissionTorque( self, gear, minTorque, maxTorque )
        end

        local torque = math.Clamp( maxTorque * self:GetMaxRPM() / math.max( self:GetFlywheelRPM(), 1 ), maxTorque, minTorque )
        torque = torque * ( 1 - self.clutch ) * self.gearRatios[gear] * self:GetDifferentialRatio() * self:GetTransmissionEfficiency()

        return gear == -1 and -torque or torque
    end

    -- engine rpm (and so gear choice) from ground speed: Glide uses wheel spin, and a few slipping
    -- road wheels made it shift up at walking pace, killing the torque on slopes; tracks barely slip
    function ENT:TransmissionToEngineRPM( gear, selfTbl )
        return selfTbl.forwardSpeed / {radius:.1f} * 60 / ( 2 * math.pi ) * selfTbl.gearRatios[gear] * self:GetDifferentialRatio() * 60 / ( 2 * math.pi )
    end

    ENT.SpawnPositionOffset = Vector( 0, 0, 50 )
{nl.join(soundServer)}

    local mgPos = Vector()
    local yawAng = Angle()

    -- PrimaryAttack of the coaxial MG VSWEP (driver weapon slot 2)
    local function FireCoaxial( weapon )
        weapon:TakePrimaryAmmo( 1 )
        weapon:SetNextPrimaryFire( CurTime() + weapon.FireDelay )
        weapon:ShootEffects()

        local vehicle = weapon.Vehicle

        vehicle:FireBullet( {{
            pos = vehicle:GetGunPoint( vehicle.coaxOffset ),
            ang = vehicle:GetTurretAimDirection():Angle(),
            attacker = vehicle:GetSeatDriver( 1 ),
            damage = weapon.Damage
        }} )
    end

    function ENT:OnUpdateFeatures( dt )
        BaseClass.OnUpdateFeatures( self, dt )

        local mg = self:GetWTMachineGun()
        if not IsValid( mg ) then return end

        mg:UpdateUser( self:GetSeatDriver( 2 ) )

        -- the roof mount turns with the turret
        yawAng[2] = self:GetTurretAngle()[2]
        mgPos:Set( self.mgOffset )
        mgPos:Rotate( yawAng )
        mgPos:Add( self.TurretOffset )
        mg:SetLocalPos( mgPos )
    end

    -- the camo is in the textures, skip Glide's random paint
    function ENT:GetSpawnColor()
        return Color( 255, 255, 255 )
    end

    -- single-differential (clutch-brake) tanks pivot around the braked inner track instead of counter-rotating both
    ENT.WTSingleFlow = {"true" if options["singleFlow"] else "false"}
    -- wheeled vehicles steer their axles like a car
    ENT.CanTurnInPlace = {"false" if wheeled else "true"}
    ENT.WTTracked = {"false" if wheeled else "true"}

    function ENT:WheelThink( dt, selfTbl )
        BaseClass.WheelThink( self, dt, selfTbl )

        if not selfTbl.WTTracked then return end

        -- Glide gives every wheel a fixed share and drops the airborne ones' share; a track carries the
        -- sprocket's pull to whichever road wheels touch the ground, so they get their side's whole share
        local count, grounded = {{ 0, 0 }}, {{ 0, 0 }}

        for _, w in Glide.EntityPairs( selfTbl.wheels ) do
            local side = w.state.isOnRightSide and 2 or 1
            count[side] = count[side] + 1
            grounded[side] = grounded[side] + ( w.state.isOnGround and 1 or 0 )
        end

        for _, w in Glide.EntityPairs( selfTbl.wheels ) do
            local state = w.state
            local side = state.isOnRightSide and 2 or 1

            if state.isOnGround and grounded[side] < count[side] then
                local scale = count[side] / grounded[side]
                state.torque = state.torque * scale
                state.forwardTractionMult = state.forwardTractionMult * scale
            end
        end

        if not selfTbl.WTSingleFlow or not selfTbl.isTurningInPlace then return end

        for _, w in Glide.EntityPairs( selfTbl.wheels ) do
            local state = w.state

            if state.torque < 0 then
                state.torque = 0
                state.brake = 1
            end
        end
    end

    function ENT:CreateFeatures()
        self:SetDifferentialRatio( {diff:.3f} )
        -- War Thunder gearbox: rated power at the redline of every gear, more torque below it (see GetTransmissionTorque)
        self:SetMinRPMTorque( {maxTorque * torqueRise:.0f} )
        self:SetMaxRPMTorque( {maxTorque:.0f} )
        self.engineBrakeTorque = {maxTorque * 40 / 35:.0f}
        self:SetBrakePower( {20000 * massScale * perWheel:.0f} )
        -- base_glide_tank's suspension is tuned for 20000 kg too
        self:SetSuspensionLength( {REST_COMPRESSION + BUMP_TRAVEL:.1f} )
        self:SetSpringStrength( {springStrength:.0f} )
        self:SetSpringDamper( {springDamper:.0f} )
        -- and so is its traction: unscaled, a heavy tank slides sideways for ~1.5 s
        self:SetForwardTractionMax( {50000 * massScale * perWheel:.0f} )
        self:SetSideTractionMultiplier( {800 * massScale * perWheel:.0f} )
        self:SetSideTractionMax( {12000 * massScale * perWheel:.0f} )
        self:SetSideTractionMin( {10000 * massScale * perWheel:.0f} )

        self:SetMaxSteerAngle( {maxSteer:.1f} )
{nl.join(rollingLines)}

        self:CreateSeat( {vec(seatPos)}, Angle( 0, 270, 0 ), Vector( 0, 150, 0 ), true )
{nl.join(weaponLines)}

{nl.join(wheelLines)}

        -- The model already shows wheels and tracks
        for _, w in ipairs( self.wheels ) do
            Glide.HideEntity( w, true )
        end

    end

    -- muzzle from the turret angles: server bone matrices are stale (they read as the hull origin, so the
    -- base "cannon inside a wall" trace hit the ground and blocked firing)
    local gunPivot = {vec([a - b for a, b in zip(gunPivot, turretPos)])}
    local muzzleOffset = {vec([a - b for a, b in zip(gamePos(muzzle), gunPivot)] if muzzle else (100, 0, 0))}
    local gunPos, gunPitch, turretYaw = Vector(), Angle(), Angle()

    --- World position of a point given relative to the gun's elevation pivot
    function ENT:GetGunPoint( offset )
        local turretAng = self:GetTurretAngle()
        gunPitch[1] = turretAng[1]
        turretYaw[2] = turretAng[2]

        gunPos:Set( offset )
        gunPos:Rotate( gunPitch )
        gunPos:Add( gunPivot )
        gunPos:Rotate( turretYaw )
        gunPos:Add( self.TurretOffset )

        return self:LocalToWorld( gunPos )
    end

    function ENT:GetProjectileStartPos()
        return self:GetGunPoint( muzzleOffset )
    end
end

local ang = Angle()

function ENT:ManipulateTurretBones( turretAng )
    if not self.turretBone then
        self.turretBone = self:LookupBone( "{turret.name if turret else "bone_turret"}" )
        self.gunBone = self:LookupBone( "{gun.name if gun else "bone_gun"}" )
    end

    if not self.turretBone then return end

    -- bones are Y-up (studiomdl $upaxis Y): yaw is around bone Y (pitch slot), elevation around bone Z (yaw slot)
    ang[1] = turretAng[2]
    ang[2] = 0
    ang[3] = 0

    self:ManipulateBoneAngles( self.turretBone, ang, false )

    if not self.gunBone then return end

    ang[1] = 0
    ang[2] = -turretAng[1]

    self:ManipulateBoneAngles( self.gunBone, ang, false )
end
'''

# ---- aircraft (base_glide_plane / base_glide_heli) ----

# animated (gear) and Lua driven (controls, wheels, rotors) nodes; the rest follows them
AIRCRAFT_BONE_RE = re.compile(r"gear_\d*[lrc]\d*|wheel\d*_\d*[lrc]|(?:aileron|flaperon)\d*_[lr]|elevator\d*|rudder\d*|prop01_\d+|nozzle\d+_\d+|jet_flame\d*")
# jet nozzle petals and intake ramps (animtree ~nozzle_N: p_nozzle_N over the whole a2d timeline)
AIRCRAFT_NOZZLE_RE = re.compile(r"nozzle\d+_\d+")
# (thrust, p_nozzle) knots: p_nozzle 1 is the closed nozzle (MiG-29 exit r 0.29 m), 0 fully open (0.47 m); closed at idle, opening with thrust
NOZZLE_MAP = ((0.0, 1.0), (1.0, 0.0))
NOZZLE_SAMPLES = 5
AIRCRAFT_GEAR_RE = re.compile(r"gear_\d*[lrc]\d*") # the animtree's p_gear_* nodes; the a2d runs retracted -> extended
# Chute-named bodywork can be compartment covers; respect native HideNodes instead of deleting by name.
AIRCRAFT_HIDDEN_RE = re.compile(r"flare\d+|prop0[23]_\d+|.*_dmg")
# the outer skin of the damage model, not the parts inside it or the moving gear
AIRCRAFT_SKIN_RE = re.compile(r"(fuse|wing|tail|fin|elevator|aileron|flap|rudder|stab|keel|nose)\d*(_[lr])?\d*_dm")
# Glide's GTA V jet (gtav_lazer) is tuned for a ~500 unit long airframe; turning torque must grow with inertia (~length^2)
AIRCRAFT_REF_LENGTH = 500.0
CONTROL_ANGLES = {"GetElevator": 20.0, "GetAileron": 20.0, "GetRudder": 25.0}
SEQ_FPS = 30

def isAircraft(blk:dict):
	return "fm" in (blk or {})

def isHelicopter(blk:dict):
	return "helicopter" in (blk or {})

def findAircraftBlk(assetPath:str, modelName:str):
	"""gamedata/flightmodels/<model>.blk with its flight model as "fm" and weapon blks as "weaponBlk", or None"""
	d = findGameRoot(assetPath)

	if d is None:
		return None

	vfs = VROMFS(path.join(d, "aces.vromfs.bin"))
	low = modelName.lower()
	norm = low.replace("-", "_")
	name = f"gamedata/flightmodels/{low}.blk"
	fmFiles = [f for f in vfs.files if f.startswith("gamedata/flightmodels/") and f.count("/") == 2 and f.endswith(".blk")]

	if name not in vfs.files:
		name = next((f for f in fmFiles if path.basename(f)[:-4].replace("-", "_") == norm), None)

	blk = vfs.readBlk(name) if name else None

	if blk is None:
		for f in fmFiles:
			try:
				b = vfs.readBlk(f)
			except Exception:
				continue

			if str(b.get("model", "")).lower().replace("-", "_") == norm:
				name, blk = f, b
				break

	if blk is None:
		return None

	fmFile = str(blk.get("fmFile") or f"fm/{path.basename(name)}").lower()

	try:
		blk["fm"] = vfs.readBlk(f"gamedata/flightmodels/{fmFile}")
	except (KeyError, ValueError):
		blk["fm"] = {}

	from util.wtweapons import reloadTime, ammoCount
	gameplay = vfs.readBlk("config/gameplay.blk")
	for w in aircraftWeapons(blk):
		w["weaponBlk"] = vfs.readBlk(str(w.get("blk", "")).lower())
		if w.get("trigger") in ("cannon", "machinegun", "guns"):
			ammoCount(w)
			w["arcadeReload"] = reloadTime(blk, w, gameplay)

	return blk

def findAircraftCollision(assetPath:str, modelName:str):
	"""Aircraft keep their <model>_collision in a separate *aircraft_logic.grp under res/"""
	from glob import glob
	from parse.gameres import GameResourcePack

	res = path.dirname(path.abspath(assetPath))

	while path.basename(res).lower() != "res":
		if path.dirname(res) == res:
			return None

		res = path.dirname(res)

	for grp in glob(path.join(res, "*aircraft_logic.grp")) + glob(path.join(res, "*", "*aircraft_logic.grp")):
		asset = next((a for a in GameResourcePack(grp).getPackedFiles() if a.name == f"{modelName}_collision"), None)

		if asset is not None:
			return asset

	return None

def builtinPreset(blk:dict):
	"""The first preset of weapon slot 0 (the guns every loadout has)"""
	slots = ((blk or {}).get("WeaponSlots") or {}).get("WeaponSlot") or []
	slot = next((s for s in (slots if isinstance(slots, list) else [slots]) if s.get("index") == 0), {})
	preset = slot.get("WeaponPreset") or {}

	return (preset[0] if isinstance(preset, list) else preset) or {}

def aircraftWeapons(blk:dict):
	w = builtinPreset(blk).get("Weapon") or []

	return [x for x in (w if isinstance(w, list) else [w]) if isinstance(x, dict) and not x.get("dummy")] + (blk or {}).get("loadoutGuns", [])

def aircraftHiddenNodes(names:list[str], blk:dict):
	"""Model nodes to drop: state-only meshes and the pylons/pods of loadouts other than the built-in guns"""
	slots = (blk or {}).get("WeaponSlots") or {}
	asList = lambda v: [v] if isinstance(v, str) else (v or [])
	hidden = set(asList((slots.get("HideNodes") or {}).get("node"))) - set(asList((builtinPreset(blk).get("ShowNodes") or {}).get("node")))

	return hidden | {n for n in names if AIRCRAFT_HIDDEN_RE.fullmatch(n)}

def aircraftCollisionNodes(names:list[str]):
	return {n for n in names if AIRCRAFT_SKIN_RE.fullmatch(n)} or set(names)

def aircraftKeepBones(skeleton):
	return {n.name for n in skeleton.getNodes() if AIRCRAFT_BONE_RE.fullmatch(n.name)} if skeleton else set()

def _mat(tm):
	import numpy as np

	return np.array(tm, dtype = float)

def _qvv(v):
	"""4x4 from an a2d sample (quat xyzw, translation, scale)"""
	import numpy as np

	x, y, z, w = v[:4]
	m = np.eye(4)
	m[:3, :3] = np.array((
		(1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
		(2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
		(2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
	)) * v[7:10]
	m[:3, 3] = v[4:7]

	return m

def poseWorld(skeleton, local:dict, only = None):
	"""{node idx: Dagor world 4x4} with the a2d `local` transforms of nodes matching `only` (bind pose for the rest)"""
	world = {}

	for n in skeleton.getNodes(): # parents come first
		L = _qvv(local[n.name]) if n.name in local and (only is None or only.fullmatch(n.name)) else _mat(n.tm)
		world[n.idx] = world[n.parent.idx] @ L if n.parent is not None else L

	return world

def _euler(R):
	"""SMD rotation (x, y, z radians, R = Rz Ry Rx)"""
	from math import asin, atan2

	return atan2(R[2][1], R[2][2]), asin(max(-1.0, min(1.0, -R[2][0]))), atan2(R[1][0], R[0][0])

def poseSMD(skeleton, kept:list, world:dict):
	"""One SMD skeleton frame of the rotation-free reduced skeleton (GeomNodeTree.getReducedSMD) posed by `world`"""
	import numpy as np

	M = np.diag((1.0, 1.0, -1.0)) # Dagor -> SMD mirror
	bones = {}
	lines = []

	for i, n in enumerate(kept):
		# the bone moves like its node: world delta from the bind pose, applied to the rotation-free rest
		rest = np.eye(4)
		rest[:3, 3] = _mat(n.wtm)[:3, 3]
		bones[n.idx] = world[n.idx] @ np.linalg.inv(_mat(n.wtm)) @ rest
		L = np.linalg.inv(bones[n.parent.idx]) @ bones[n.idx] if n.parent is not None else bones[n.idx]
		R = M @ L[:3, :3] @ M
		p = M @ L[:3, 3] * VERTEX_SCALE
		lines.append(f"{i} {p[0]:.4f} {p[1]:.4f} {p[2]:.4f} " + " ".join(f"{a:.6f}" for a in _euler(R)))

	return lines

def nozzlePoses(skeleton, a2d):
	"""{bone: [(SMD position offset, Source Angle (p, y, r)) per p_nozzle sample]} relative to the rest pose"""
	from math import degrees

	kept = skeleton.getReducedBones(aircraftKeepBones(skeleton))[0]
	parse = lambda line: [float(v) for v in line.split()[1:]]
	rest = [parse(l) for l in poseSMD(skeleton, kept, poseWorld(skeleton, {}))]
	out = {}

	for k in range(NOZZLE_SAMPLES):
		lines = poseSMD(skeleton, kept, poseWorld(skeleton, a2d.sample(a2d.duration * k / (NOZZLE_SAMPLES - 1)), AIRCRAFT_NOZZLE_RE))

		for n, line, r in zip(kept, lines, rest):
			if AIRCRAFT_NOZZLE_RE.fullmatch(n.name):
				v = parse(line)
				# SMD R = Rz Ry Rx is Source's AngleMatrix(pitch = y, yaw = z, roll = x)
				out.setdefault(n.name, []).append((tuple(a - b for a, b in zip(v[:3], r[:3])), (degrees(v[4]), degrees(v[5]), degrees(v[3]))))

	return {k: v for k, v in out.items() if any(abs(x) > 0.01 for p, a in v for x in p + a)}

def exhausts(skeleton):
	"""[(Source centre, radius)] of the nozzles behind the middle of the airframe (nozzle3/4 on the MiG-29 are intakes)"""
	groups = {}

	for n in skeleton.getNodes():
		if AIRCRAFT_NOZZLE_RE.fullmatch(n.name):
			groups.setdefault(n.name.split("_")[0], []).append(gamePos(n))

	out = []

	for pts in groups.values():
		c = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))

		if c[0] < 0 and len(pts) > 4:
			out.append((c, sum(((p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2) ** 0.5 for p in pts) / len(pts)))

	return out

def gearDuration(fm:dict, fallback:float = 3.333333):
	"""Normalized actuator travel / rate; the A2D timeline only describes the poses."""
	from math import isfinite
	try:
		speed = float(fm.get("GearActuatorSpeed", 0))
	except (TypeError, ValueError):
		return fallback
	return 1 / speed if isfinite(speed) and 0.01 <= speed <= 100 else fallback


def gearSequences(skeleton, keepBones:set[str], a2d, fm:dict = None):
	"""Glide's LandingGearAnims sequences from the a2d gear nodes (start = retracted, end = extended)"""
	kept = skeleton.getReducedBones(keepBones)[0]
	nodes = skeleton.getReducedSMD(kept).split("skeleton")[0]
	frames = max(round(gearDuration(fm or {}, a2d.duration) * SEQ_FPS), 1)
	# shortcut: WT's relative aileron tracks are centred at 0.5; other controller families need their animtree mapping.
	neutral = {n: v for n, v in a2d.sample(a2d.duration * 0.5).items() if re.fullmatch(r"aileron\d*_[lr]", n)}
	def pose(t):
		local = dict(neutral)
		local.update({n: v for n, v in a2d.sample(t).items() if AIRCRAFT_GEAR_RE.fullmatch(n)})
		return poseSMD(skeleton, kept, poseWorld(skeleton, local))
	poses = [pose(a2d.duration * f / frames) for f in range(frames + 1)]
	smd = lambda seq: nodes + "skeleton\n" + "\n".join(f"time {k}\n" + "\n".join(p) for k, p in enumerate(seq)) + "\nend\n"

	return {
		"idle": smd([poseSMD(skeleton, kept, poseWorld(skeleton, neutral))]),
		"gear_down": smd([poses[-1]]),
		"move_gear_up": smd(poses[::-1]),
		"gear_up": smd([poses[0]]),
		"move_gear_down": smd(poses),
	}

def smdAxis(node, axis = (0.0, 1.0, 0.0)):
	"""A node-local Dagor axis in the reduced skeleton's bone space (model axes, SMD mirrored)"""
	import numpy as np

	a = _mat(node.wtm)[:3, :3] @ np.array(axis)
	a = a / (np.linalg.norm(a) or 1)

	return (float(a[0]), float(a[1]), float(-a[2]))

def controlSurfaces(model):
	"""[(bone, Glide input getter, SMD hinge axis, degrees at full input)]: War Thunder hinges them on their local Y
	(animtree rotateNode dirAxis); the sign makes positive Glide input push the trailing edge the way it should."""
	import numpy as np

	skeleton = model.skeleton
	out = []

	for obj in model:
		m = re.fullmatch(r"(aileron|flaperon)\d*_([lr])|(elevator)\d*|(rudder)\d*", obj.name)
		node = skeleton.getNodeByName(obj.name) if m and skeleton is not None and not obj.skinned else None
		idx = {i for f in obj.faces for i in f}

		if node is None or not idx:
			continue
		# Nested flaperon pieces inherit the hinge; rotating both doubles their travel.
		if m[1] == "flaperon" and node.parent and re.fullmatch(r"flaperon\d*_[lr]", node.parent.name):
			continue

		M = np.array((1.0, 1.0, -1.0))
		centre = np.mean([model.getVertex(i, True, node) for i in idx], axis = 0) - _mat(node.wtm)[:3, 3] * VERTEX_SCALE
		move = np.cross(smdAxis(node), centre * M) # trailing edge motion for a small positive turn (SMD: y up, z right)

		if m[1]: # roll right: left aileron down, right aileron up
			getter, sign = "GetAileron", -np.sign(move[1]) * (1 if m[2] == "l" else -1)
		elif m[3]: # pitch down: trailing edge down
			getter, sign = "GetElevator", -np.sign(move[1])
		else: # yaw right: trailing edge right
			getter, sign = "GetRudder", np.sign(move[2])

		out.append((obj.name, getter, smdAxis(node), float(sign or 1) * CONTROL_ANGLES[getter]))

	return out

def aircraftWheels(skeleton, a2d, fm:dict):
	"""[(wheel node, Source pos with the gear down, radius, steers)] from the wheel_[lrc] nodes and the FM struts"""
	world = poseWorld(skeleton, a2d.sample(a2d.duration), AIRCRAFT_GEAR_RE) if a2d else None
	gear = (fm or {}).get("Gear") or {}
	wheels = []

	for n in skeleton.getNodes():
		m = re.fullmatch(r"wheel_(\d*)([lrc])", n.name)

		if not m:
			continue

		w = world[n.idx] if world else _mat(n.wtm)
		strut = gear.get(f"Strut{m[2].upper()}{m[1]}") or gear.get(f"Strut{m[2].upper()}") or {}
		radius = float(strut.get("WheelRadus", 0.35)) * VERTEX_SCALE
		wheels.append((n.name, (w[0][3] * VERTEX_SCALE, w[2][3] * VERTEX_SCALE, w[1][3] * VERTEX_SCALE), radius, m[2] == "c"))

	return wheels

def aircraftMass(fm:dict):
	mass = (fm or {}).get("Mass") or {}

	return min(float(mass.get("EmptyMass", 5000)) + float(mass.get("MaxFuelMass0", 0)), 50000)

def aircraftGuns(skeleton, blk:dict):
	"""[(class, [Source muzzle positions], fire delay, damage, weapon)] grouped by trigger and weapon."""
	guns = {}

	for w in aircraftWeapons(blk):
		node = skeleton.getNodeByName(str(w.get("emitter", ""))) or skeleton.getNodeByName(str(w.get("flash", "")))

		if w.get("trigger") in ("cannon", "machinegun", "guns", "additional gun"):
			if node is None:
				raise ValueError(f"Missing aircraft gun emitter: {w.get('emitter')}")
			guns.setdefault((w["trigger"], w.get("blk", ""), w.get("emitter") if w["trigger"] == "additional gun" else None), []).append((w, gamePos(node)))

	out = []

	from util.wtweapons import ammoCount
	for trigger, entries in guns.items():
		w = dict(entries[0][0], bullets=sum(ammoCount(w) for w, _ in entries))
		muzzles = [p for _, p in entries]
		wb = w.get("weaponBlk", {})
		bullet = wb.get("bullet") or {}
		cal = float((bullet[0] if isinstance(bullet, list) else bullet).get("caliber", 0.0127)) * 1000 # m
		out.append(("explosive_cannon" if cal >= 20 else "base", muzzles, 1 / (max(float(wb.get("shotFreq", 10)), 0.1) * len(muzzles)), round(max(cal, 5) * 2.5), w))

	return out

def exportAircraftSounds(gameRoot:str, blk:dict, outDir:str):
	"""Resolve exact unit/weapon event references; missing events keep Glide's defaults."""
	from util.wtsound import SoundBank, Renderer, readStrings, writeWav, finish, SOURCE_RATE
	import numpy as np

	soundDir = path.join(gameRoot, "sound")
	if not path.isfile(path.join(soundDir, "masterbank.strings.bank")):
		return {}
	strings = readStrings(path.join(soundDir, "masterbank.strings.bank"))
	stringsLower = {k.lower(): (k, v) for k, v in strings.items()}
	try:
		studio = VROMFS(path.join(gameRoot, "aces.vromfs.bin")).readBlk("config/sound_studio.blk")
	except Exception:
		studio = {}
	makedirs(outDir, exist_ok = True)
	out, banks, sources = {"guns": {}}, {}, {}

	def resolve(bankName, event):
		canonical, guid = stringsLower.get(event.lower(), (event, None))
		if not guid:
			raise ValueError(f"Missing FMOD event {event}")
		if bankName not in banks:
			banks[bankName] = SoundBank(soundDir, bankName)
		bank = banks[bankName]
		bank.decode(bank.walk(guid))
		return bank, guid, canonical

	def save(stem, pcm, loop = False):
		if not len(pcm) or np.max(np.abs(pcm)) < 1e-6:
			raise ValueError(f"Silent FMOD render: {stem}")
		writeWav(path.join(outDir, stem + ".wav"), finish(pcm), SOURCE_RATE, loop)
		return stem

	norm = lambda s: s.lower().replace("_", "").replace("-", "")
	for w in aircraftWeapons(blk):
		ref = w.get("blk", "")
		if ref in out["guns"] or w.get("trigger") not in ("cannon", "machinegun", "guns", "additional gun"):
			continue
		cfg = w.get("weaponBlk", {}).get("gunSound", {})
		event = f'event:/{cfg.get("pathStudio", "")}/{cfg.get("outside", "")}'
		try:
			bank, guid, event = resolve("aircraft_guns", event)
			# shortcut: per-shot close samples, not FMOD's distance/cone/first-last-shot mixer.
			stem = norm(re.sub(r"^(cannon_|gun_)|(_gun)?_outside$", "", str(cfg.get("outside", ""))))
			pairs = [(bank.sample(bank.waves[i.wave])[0], g) for g in bank.walk(guid)
				if (i := bank.instruments.get(g)) and i.wave in bank.waves]
			groups = (
				[p for p in pairs if re.search(r"(?:^|_)(?<!first_)(?<!last_)close-\d+$", p[0])],
				[p for p in pairs if re.search(r"(?:^|_)(?<!start_)(?<!end_)(?<!last_)(?:shot|singleshot|fast)[-_]\d+$", p[0]) and not p[0].startswith("body_")],
				[p for p in pairs if re.search(r"(?:^|_)(?:first_close|start_shot|first|start)[-_]\d+$", p[0]) and "far" not in p[0]],
			)
			shots = []
			for grp in groups:
				if grp:
					shots = sorted([p for p in grp if norm(p[0]).startswith(stem)] or [p for p in grp if norm(p[0]).startswith(stem[:4])] or grp)
					break
			if not shots:
				raise ValueError(f"No single-shot close samples in {event}")
			renderer = Renderer(bank, {"on_shot": 1})
			prefix = f"gun{len(out['guns'])}"
			out["guns"][ref] = [save(f"{prefix}_{n}", renderer.instrument(g)) for n, (_, g) in enumerate(shots[:4])]
			sources[ref] = {"event": event, "samples": [name for name, _ in shots[:4]], "cockpitEvent": cfg.get("cockpit")}
		except Exception as e:
			log.log(f"Aircraft gun sound unavailable ({ref}): {e}", 2)

	engine = (blk.get("Sound") or {}).get("Engine")
	if engine and isHelicopter(blk):
		try:
			cfg = studio[engine]
			loops, provenance = [], []
			for group in ("engines", "propellers"):
				outside = cfg[group]["outside"]
				events = [(key, value) for key, value in outside.items() if key.startswith("event") and isinstance(value, str) and value]
				if not events:
					raise ValueError(f"Missing {group} events for {engine}")
				for key, name in events:
					event = f'event:/{outside["path"]}/{name}'
					bank, guid, event = resolve("aircraft_engines", event)
					# shortcut: healthy nominal-RPM exterior mix; add live FMOD controllers for cockpit/load/distance fidelity.
					params = {"load": 0.5, "broken": 0, "rotor_broken": 0, "depth": -1000, "Distance": 0}
					for layout in bank.events[guid].layouts:
						param = bank.layouts[layout][0]
						pname, lo, hi, default = bank.params.get(param, ("", 0, 0, 0))
						if pname in ("rpm", "rpm2", "rpm_result") or pname.startswith("rpm_result_"):
							params[pname] = hi
					stem = save(f"heli_{len(loops)}", Renderer(bank, params).event(guid, 8), True)
					loops.append(stem)
					provenance.append({"config": f"{engine}/{group}/outside/{key}", "event": event, "params": params})
			# Replace defaults only after both engine and rotor groups have been rendered successfully.
			out["helicopter"] = loops
			sources["helicopter"] = provenance
		except Exception as e:
			log.log(f"Helicopter sound unavailable ({engine}): {e}", 2)
	if engine and not isHelicopter(blk):
		engCfg = (studio.get(engine) or {}) if isinstance(studio.get(engine), dict) else {}
		outside = engCfg.get("outside") or (engCfg.get("engines") or {}).get("outside") or {}
		evName = outside.get("eventBack") or outside.get("eventLod1") or engine
		evPath = outside.get("path", "aircraft/engines")
		event = f"event:/{evPath}/{evName}"
		try:
			bank, guid, event = resolve("aircraft_engines", event)
			# shortcut: three native FMOD operating points crossfaded by power; not the complete RPM/distance simulation.
			loops = {}
			for key, rpm, wep in (("idle", 1000, 0), ("full", 2500, 0), ("wep", 2500, 1)):
				params = {"rpm": rpm, "wep": wep, "distance": 0, "Distance": 0, "depth": -1000, "load": 0.5}
				for layout in bank.events[guid].layouts:
					pname = bank.params.get(bank.layouts[layout][0], ("",))[0]
					if pname.startswith("rpm"):
						params[pname] = rpm
				loops[key] = save(f"engine_{key}", Renderer(bank, params, steadyLoops = True).event(guid, 8), True)
			out["engine"] = loops
			sources["engine"] = {"event": event, "operatingPoints": [[1000, 0], [2500, 0], [2500, 1]], "steadyLoopsOnly": True}
		except Exception as e:
			log.log(f"Aircraft engine sound unavailable ({engine}): {e}", 2)

	try:
		# WT calls the common aircraft landing-gear event 'chasis' (one s).
		event = "event:/" + studio["misc_effects"]["path"] + "/" + studio["misc_effects"]["eventChasis"]
		bank, guid, event = resolve("aircraft_effects", event)
		renderer = Renderer(bank)
		parts = {}
		for g in bank.walk(guid):
			i = bank.instruments.get(g)
			if i and i.wave in bank.waves:
				name = bank.sample(bank.waves[i.wave])[0]
				if name in ("chasis_start", "chasis_loop", "chasis_end"):
					parts[name.removeprefix("chasis_")] = renderer.instrument(g)
		if len(parts) != 3:
			raise ValueError("Incomplete landing gear event")
		# Keep the motor at its native pitch; stop it at the compiled sequence's endpoint.
		out["gear"] = {k: save("gear_" + k, pcm, k == "loop") for k, pcm in parts.items()}
		sources["gear"] = {"event": event, "samples": ["chasis_" + k for k in parts],
			"actuatorSeconds": gearDuration(blk.get("fm") or {})}
	except Exception as e:
		log.log(f"Aircraft landing gear sound unavailable: {e}", 2)

	with open(path.join(outDir, "sources.json"), "w", encoding = "utf-8") as f:
		json.dump(sources, f, indent = 2)
	return out


def jetVolumeRamps(gameRoot:str, volume:dict):
	"""after_burner PS selects four atlas rows per rampTextureOffset (depth/height/radius/rings)."""
	from io import BytesIO
	from PIL import Image
	from parse.material import DDSxTexturePack2

	pack = DDSxTexturePack2(path.join(gameRoot, "content/base/res/fx.dxp.bin"))
	tex = next(t for t in pack.getPackedFiles() if t.name == "afterburneratlastex")
	img = Image.open(BytesIO(tex.getDDS())).convert("RGB")
	row = int(volume["rampTextureOffset"]) * 4
	if row < 0 or row + 4 > img.height:
		raise ValueError("Afterburner ramp outside atlas")
	return [[list(img.getpixel((round(x * (img.width - 1) / 31), y))) for x in range(32)] for y in range(row, row + 4)]


def jetHeatNormal(img):
	"""Convert Dagor RG displacement (neutral 127) to Source normal-map XY; B/A aren't normal/opacity."""
	import numpy as np
	from PIL import Image

	x = np.asarray(img.convert("RGBA"), dtype = np.float32)
	xy = (x[..., :2] - 127) / 255
	z = np.sqrt(np.maximum(0, 1 - (xy * xy).sum(axis = 2)))
	out = np.empty_like(x)
	out[..., :2] = (xy + 1) * 127.5
	out[..., 2] = (z + 1) * 127.5
	out[..., 3] = 255

	return Image.fromarray(np.rint(out).clip(0, 255).astype(np.uint8))

def exportJetHeat(gameRoot:str, addonDir:str, vtfCmd:str):
	"""fx.grp's haze_jet_fx and haze_jet_smooth_fx both reference this distortion texture."""
	from io import BytesIO
	from tempfile import TemporaryDirectory
	from subprocess import run
	from PIL import Image
	from parse.material import DDSxTexturePack2

	pack = DDSxTexturePack2(path.join(gameRoot, "content/base/res/fx.dxp.bin"))
	tex = next(t for t in pack.getPackedFiles() if t.name == "distortion_hot_air_a_tex")
	outDir = path.join(addonDir, "materials/models/wt_glide/fx")
	makedirs(outDir, exist_ok = True)

	with TemporaryDirectory() as temp:
		imgPath = path.join(temp, "distortion_hot_air_a_normal.tga")
		jetHeatNormal(Image.open(BytesIO(tex.getDDS()))).save(imgPath)
		run([vtfCmd, "-file", imgPath, "-output", temp, "-version", "7.2", "-format", "RGBA8888", "-alphaformat", "RGBA8888", "-flag", "NORMAL"], check = True)
		# VTFCmd can report success without writing an image; never emit a dangling material reference.
		from shutil import copyfile
		copyfile(path.join(temp, "distortion_hot_air_a_normal.vtf"), path.join(outDir, "distortion_hot_air_a_normal.vtf"))

	return "models/wt_glide/fx/distortion_hot_air_a_normal"

def aircraftInertia(fm:dict, mass:float):
	"""WT principal moments -> Source kg*m² (WT Y-up, exported at 40 units/m)."""
	values = fm.get("MomentOfInertia")
	empty = float((fm.get("Mass") or {}).get("EmptyMass", 0))
	if not isinstance(values, (list, tuple)) or len(values) != 3 or empty <= 0:
		return None
	values = [float(v) for v in values]
	if not all(isfinite(v) and v > 0 for v in values) or not isfinite(empty):
		return None
	# shortcut: scale the native empty-airframe tensor uniformly for fuel/payload.
	scale = mass / empty * (VERTEX_SCALE * 0.0254) ** 2
	return tuple(values[i] * scale for i in (0, 2, 1))


def generateAircraftLua(className:str, printName:str, modelPath:str, skeleton, blk:dict, a2d = None, surfaces:list = None, heatTexture:str = "", sounds:dict = None, options:dict = None):
	fm = blk.get("fm") or {}
	options = {**defaultOptions(blk), **(options or {})}
	sounds = sounds or {}
	soundDir = f"wt/{className}"
	heli = isHelicopter(blk)
	base = "base_glide_heli" if heli else "base_glide_plane"
	node = skeleton.getNodeByName
	mass = min(float(options.get("mass", aircraftMass(fm))), 50000)
	inertia = aircraftInertia(fm, mass) if not heli else None
	inertiaLine = f"        self:GetPhysicsObject():SetInertia( {vec(inertia)} )" if inertia else ""
	maxSpeed = float(options.get("maxSpeed", 2400))
	engineForce = float(options.get("engineForce", 350))
	positions = [gamePos(n) for n in skeleton.getNodes()]
	length = max(float(fm.get("Length", 0)) * VERTEX_SCALE, max(p[0] for p in positions) - min(p[0] for p in positions), 100.0)
	rot = (length / AIRCRAFT_REF_LENGTH) ** 2
	pilot = node("pilot1") or node("pilot")
	seats = [gamePos(pilot) if pilot else (length * 0.25, 0, 40)] + [gamePos(n) for n in (node("gunner1"),) if n]
	wheels = aircraftWheels(skeleton, a2d, fm)
	suspension = REST_COMPRESSION + BUMP_TRAVEL
	spring = mass * GLIDE_WEIGHT / (max(len(wheels), 1) * REST_COMPRESSION)
	# gtav_lazer's damping ratio (10000 for 1500 spring on a 1500 kg, 3 wheel jet)
	damper = 10000 / sqrt(1500 * 500) * sqrt(spring * mass / max(len(wheels), 1))
	massScale = mass / 1500 # gtav_lazer's mass
	props = [n for n in skeleton.getNodes() if re.fullmatch(r"prop01_\d+", n.name)]
	nl = "\n"

	wheelLines = [
		f"        self:CreateWheel( {vec((p[0], p[1], p[2] + BUMP_TRAVEL))}, {{ radius = {r:.1f}, steerMultiplier = {1 if steer else 0}, suspensionLength = {suspension:.1f}, "
		f"springStrength = {spring:.0f}, springDamper = {damper:.0f}, brakePower = {2000 * massScale:.0f}, forwardTractionMax = {2600 * massScale:.0f}, sideTractionMultiplier = {250 * massScale:.0f}, "
		f"sideTractionMax = {2400 * massScale:.0f}, sideTractionMin = {800 * massScale:.0f} }} )"
		for _, p, r, steer in wheels
	]
	seatLines = [f"        self:CreateSeat( {vec(p)}, Angle( 0, 270, 10 ), Vector( 0, {length * 0.4:.0f}, 0 ), true )" for p in seats]
	weaponLines, soundLines = [], []
	for index, (cls, muzzles, delay, damage, weapon) in enumerate(aircraftGuns(skeleton, blk)):
		files = sounds.get("guns", {}).get(weapon.get("blk"), [])
		soundName = f"{className}.Gun{index}"
		if files:
			soundLines.append(f'sound.Add( {{ name = "{soundName}", channel = CHAN_WEAPON, volume = 1, level = 95, pitch = 100, sound = {{ ' + ", ".join(json.dumps(f"{soundDir}/{stem}.wav") for stem in files) + ' } } )')
		soundOption = f'SingleShotSound = {json.dumps(soundName)}, ' if files else ""
		weaponLines.append(f'        self:CreateWeapon( "{cls}", {{ MaxAmmo = {weapon["bullets"]}, ReloadDelay = {weapon["arcadeReload"]:.5f}, FireDelay = {delay:.5f}, Damage = {damage}, {soundOption}ProjectileOffsets = {{ {", ".join(vec(p) for p in muzzles)} }} }} )')
	surfaceLines = [f'        {{ bone = "{b}", input = "{g}", axis = Vector( {a[0]:.4f}, {a[1]:.4f}, {a[2]:.4f} ), angle = {ang:.1f} }},' for b, g, a, ang in surfaces or []]
	# Glide's wheels index in creation order
	spinLines = [f'        {{ bone = "{name}", wheel = {k + 1}, axis = Vector( {a[0]:.4f}, {a[1]:.4f}, {a[2]:.4f} ) }},' for k, (name, *_) in enumerate(wheels) for a in [smdAxis(node(name))]]
	# main rotor / propellers spin with power (visual only: Glide's own rotor entities are hidden)
	nozzleLines = [
		f'        {{ bone = "{b}", frames = {{ ' + ", ".join(f"{{ Vector( {p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f} ), Angle( {a[0]:.2f}, {a[1]:.2f}, {a[2]:.2f} ) }}" for p, a in frames) + " } },"
		for b, frames in (nozzlePoses(skeleton, a2d) if a2d else {}).items()
	]
	ex = exhausts(skeleton)
	flameLines = []

	for n in skeleton.getNodes():
		if re.fullmatch(r"jet_flame\d*", n.name):
			c = gamePos(n)
			# Flame-card origins can be inside the fuselage; use the matching physical nozzle.
			c, r = min(ex, key = lambda e: sum((a - b) ** 2 for a, b in zip(e[0], c))) if ex else (c, 20.0)
			flameLines.append(f'        {{ bone = "{n.name}", pos = {vec(c)}, radius = {r:.1f} }},')
	exhaustLines = [f"        {{ pos = {vec((c[0] - 10, c[1], c[2]))}, scale = {r / 12:.2f} }}," for c, r in ex]
	propLines = [f'        {{ bone = "{n.name}", speed = {1500 if n.name == "prop01_1" else 3000}, axis = Vector( {a[0]:.4f}, {a[1]:.4f}, {a[2]:.4f} ) }},' for n in props for a in [smdAxis(n)]]

	if heli:
		props_ = {p.name: p for p in props}
		main, tail = props_.get("prop01_1"), props_.get("prop01_2")
		radius = lambda k, d: float(((fm.get(f"Propeller{k}") or {}).get("Geometry") or {}).get("Radius", d)) * VERTEX_SCALE
		typeLines = [
			f"ENT.MainRotorOffset = {vec(gamePos(main) if main else (0, 0, 120))}",
			f"ENT.TailRotorOffset = {vec(gamePos(tail) if tail else (-length * 0.6, 0, 60))}",
		]
		serverLines = [
			f"    ENT.MainRotorRadius = {radius(0, 6):.0f}",
			f"    ENT.TailRotorRadius = {radius(1, 1):.0f}",
			"    -- the rotor blades are in the chassis model; Glide's rotor entities only do the collisions",
			'    ENT.MainRotorModel = "models/hunter/plates/plate.mdl"',
			'    ENT.MainRotorFastModel = ""',
			'    ENT.TailRotorModel = "models/hunter/plates/plate.mdl"',
			'    ENT.TailRotorFastModel = ""',
			"    ENT.HelicopterParams = {",
			f"        pitchForce = {700 * rot:.0f},",
			f"        yawForce = {700 * rot:.0f},",
			f"        rollForce = {700 * rot:.0f},",
			f"        uprightForce = {1000 * rot:.0f},",
			"    }",
			"",
			"    function ENT:CreateRotors()",
			"        BaseClass.CreateRotors( self )",
			"",
			"        for _, r in ipairs( self.rotors ) do",
			"            if IsValid( r ) then r:SetNoDraw( true ) end",
			"        end",
			"    end",
		]
		clientLines = []
	else:
		typeLines = []
		serverLines = [
			f"    ENT.ReverseTorque = {2000 * massScale:.0f}",
			"    ENT.SteerConeMaxSpeed = 900",
			"    ENT.PlaneParams = {",
			f"        liftAngularDrag = Vector( {-20 * rot:.0f}, {-70 * rot:.0f}, {-100 * rot:.0f} ), -- (Roll, pitch, yaw)",
			f"        maxSpeed = {maxSpeed:.0f},",
			f"        liftSpeed = {maxSpeed * 0.75:.0f},",
			f"        engineForce = {engineForce:.0f},",
			f"        pitchForce = {5500 * rot:.0f},",
			f"        yawForce = {3500 * rot:.0f},",
			f"        rollForce = {3500 * rot:.0f}",
			"    }",
		]
		# jets sound like gtav_lazer, propeller planes keep base_glide_plane's
		clientLines = [] if props else [
			'    ENT.StartSound = "glide/aircraft/start_4.wav"',
			'    ENT.DistantSoundPath = "glide/aircraft/jet_stream.wav"',
			'    ENT.PropSoundPath = "glide/aircraft/thrust_b11.wav"',
			"    ENT.PropSoundVolume = 0.5",
			"    ENT.PropSoundLevel = 90",
			"    ENT.PropSoundMinPitch = 80",
			"    ENT.PropSoundMaxPitch = 120",
			'    ENT.EngineSoundPath = "glide/aircraft/engine_luxor.wav"',
			"    ENT.EngineSoundLevel = 90",
			"    ENT.EngineSoundVolume = 0.4",
			"    ENT.EngineSoundMinPitch = 103",
			"    ENT.EngineSoundMaxPitch = 132",
			'    ENT.ExhaustSoundPath = "glide/aircraft/distant_laser.wav"',
			"    ENT.ExhaustSoundLevel = 90",
			"    ENT.ExhaustSoundVolume = 0.5",
			"    ENT.ExhaustSoundMinPitch = 55",
			"    ENT.ExhaustSoundMaxPitch = 60",
			'    ENT.ThrustSound = "glide/aircraft/thrust.wav"',
			"    ENT.ThrustSoundMinPitch = 90",
			"    ENT.ThrustSoundMaxPitch = 100",
			"    ENT.ThrustSoundLowVolume = 0.1",
			"    ENT.ThrustSoundHighVolume = 0.4",
		]

	if sounds.get("gear"):
		gear = {k: json.dumps(f"{soundDir}/{v}.wav") for k, v in sounds["gear"].items()}
		serverLines += [
			'    ENT.LandingGearSounds = { [0] = { "" }, [1] = { "" }, [2] = { "" }, [3] = { "" } }',
			"    function ENT:OnLandingGearStateChange( state )",
			"        local moving = state == 1 or state == 3",
			"        if moving then",
			f'            self:EmitSound( {gear["start"]}, 80, 100, 0.7 )',
			f'            self.wtGearMotor = self.wtGearMotor or CreateSound( self, {gear["loop"]} )',
			"            self.wtGearMotor:PlayEx( 0.7, 100 )",
			"            self:CallOnRemove( \"WTGearMotor\", function( ent )",
			"                if ent.wtGearMotor then ent.wtGearMotor:Stop() end",
			"            end )",
			"        elseif self.wtGearMoving then",
			"            if self.wtGearMotor then self.wtGearMotor:Stop() end",
			f'            self:EmitSound( {gear["end"]}, 80, 100, 0.7 )',
			"        end",
			"        self.wtGearMoving = moving",
			"    end",
		]

	volume = ((blk.get("AfterBurner0") or {}).get("volumetricAfterBurner") or {})
	volumeLua = json.dumps(volume, separators = (",", ":"))
	from util.jetexhaust import rendererLua
	exhaustTexture = blk.get("exhaustTexture", "")
	exhaustRenderer = rendererLua(className, exhaustTexture, volume)
	exhaustFiles = 'AddCSLuaFile( "wt_jet_exhaust/volume.lua" )\n    AddCSLuaFile( "wt_jet_exhaust/exhaust.lua" )' if exhaustTexture else ''
	if heli and sounds.get("helicopter"):
		clientLines += [
			'    ENT.StartSound = ""', '    ENT.RotorBeatInterval = 0',
			'    function ENT:OnActivateSounds()',
			* [f'        self:CreateLoopingSound( "wt_heli_{n}", "{soundDir}/{stem}.wav", 85 ):PlayEx( 0, 100 )' for n, stem in enumerate(sounds["helicopter"])],
			'    end',
			'    function ENT:OnUpdateSounds()',
			'        local power = math.Clamp( self:GetPower(), 0, 1.2 )',
			'        local vol = Glide.Config.GetVolume( "aircraftVolume" ) * math.Clamp( power, 0, 1 )',
			'        for id, snd in pairs( self.sounds ) do',
			'            if string.StartWith( id, "wt_heli_" ) then',
			'                snd:ChangePitch( math.Clamp( power * 100, 1, 120 ) )',
			'                snd:ChangeVolume( vol )',
			'            end', '        end',
			'        local dying = self:GetIsEngineDying() and LocalPlayer():GlideGetVehicle() == self',
			'        if dying and not self.sounds.engineWarning and self.EngineFailSound ~= "" then',
			'            self:CreateLoopingSound( "engineWarning", self.EngineFailSound, 130 ):PlayEx( self.EngineFailVolume, 130 )',
			'        elseif not dying and self.sounds.engineWarning then',
			'            self.sounds.engineWarning:Stop()', '            self.sounds.engineWarning = nil',
			'        end', '    end', '']
	if sounds.get("engine") and not heli:
		clientLines += [f'    ENT.{key} = ""' for key in ("StartSound", "DistantSoundPath", "PropSoundPath", "EngineSoundPath", "ExhaustSoundPath", "ThrustSound")]
		clientLines += [
			"    function ENT:OnActivateSounds()",
			* [f'        self:CreateLoopingSound( "wt_{k}", "{soundDir}/{v}.wav", 90 ):PlayEx( 0, 100 )' for k, v in sounds["engine"].items()],
			"    end",
			"    function ENT:OnUpdateSounds()",
			"        BaseClass.OnUpdateSounds( self )",
			"        local p = self:GetPower()",
			"        local thrust = math.Clamp( p - 1, 0, 1 )",
			"        local wep = math.Clamp( ( thrust - 0.8 ) / 0.2, 0, 1 )",
			'        local volume = math.Clamp( p, 0, 1 ) * Glide.Config.GetVolume( "aircraftVolume" )',
			"        local weights = { idle = 1 - thrust, full = thrust * ( 1 - wep ), wep = wep }",
			"        for key, weight in pairs( weights ) do",
			'            local snd = self.sounds["wt_" .. key]',
			"            if snd then",
			"                snd:ChangePitch( 100 )",
			"                snd:ChangeVolume( volume * weight )",
			"            end",
			"        end",
			"    end",
		]

	return f'''AddCSLuaFile()

-- Generated by Dagor Asset Explorer
ENT.Type = "anim"
ENT.Base = "{base}"
ENT.PrintName = "{printName}"

ENT.GlideCategory = "War Thunder"
ENT.ChassisModel = "{modelPath}"
{nl.join(typeLines)}
{nl.join(soundLines)}

DEFINE_BASECLASS( "{base}" )

-- Glide's spawn menu only lists categories registered here
list.Set( "GlideCategories", "War Thunder", {{ name = "War Thunder", icon = "glide/icons/tank.png" }} )

if CLIENT then
    ENT.CameraOffset = Vector( {-length * 1.2:.0f}, 0, {length * 0.2:.0f} )
    ENT.WTHideCrew = false
{nl.join(clientLines)}

    -- the crew sits inside the cockpit
    hook.Add( "PrePlayerDraw", "WTGlide.HideCrew", function( ply )
        local vehicle = ply:GlideGetVehicle()

        if IsValid( vehicle ) and vehicle.WTHideCrew then return true end
    end )

    -- bone = turns by `angle` degrees around `axis` at full input (bones are the model's axes, Y up)
    local SURFACES = {{
{nl.join(surfaceLines)}
    }}

    local WHEELS = {{
{nl.join(spinLines)}
    }}

    local PROPS = {{
{nl.join(propLines)}
    }}

    -- bone pose (offset, angles) at evenly spaced War Thunder p_nozzle values 0..1
    local NOZZLES = {{
{nl.join(nozzleLines)}
    }}

    -- Native nozzle positions; the original cards are hidden and the plume is a three-dimensional mesh.
    local FLAMES = {{
{nl.join(flameLines)}
    }}

    -- Glide afterburner effects at the jet nozzles, for jets without flame meshes
    local EXHAUSTS = {{
{nl.join(exhaustLines)}
    }}

    ENT.ExhaustPositions = {{}}
    ENT.EngineFireOffsets = {{}}

    for _, e in ipairs( EXHAUSTS ) do
        ENT.ExhaustPositions[#ENT.ExhaustPositions + 1] = e.pos
        ENT.EngineFireOffsets[#ENT.EngineFireOffsets + 1] = {{ offset = e.pos, angle = Angle( 270, 0, 0 ), scale = e.scale * 0.5 }}
    end

    local Effect = util.Effect

    function ENT:OnUpdateParticles()
        BaseClass.OnUpdateParticles( self )

        local power = self:GetPower()
        if power < 0.5 or #FLAMES > 0 then return end

        local throttle = self:GetThrottle()
        local eff = EffectData()

        for _, e in ipairs( EXHAUSTS ) do
            eff:SetEntity( self )
            eff:SetOrigin( self:LocalToWorld( e.pos ) )
            eff:SetAngles( self:GetAngles() )
            eff:SetScale( e.scale )
            eff:SetMagnitude( power )
            Effect( "glide_afterburner", eff, true )

            if throttle > 0.1 then
                eff:SetMagnitude( throttle * power )
                eff:SetRadius( 15 * e.scale )
                Effect( "glide_afterburner_flame", eff, true )
            end
        end
    end

    local VOLUME = util.JSONToTable( [=[{volumeLua}]=] )
{exhaustRenderer}

    -- thrust -> p_nozzle
    local NOZZLE_MAP = {{ {", ".join(f"{{ {a}, {b} }}" for a, b in NOZZLE_MAP)} }}

    local function NozzleParam( x )
        if x <= NOZZLE_MAP[1][1] then return NOZZLE_MAP[1][2] end

        for i = 2, #NOZZLE_MAP do
            local a, b = NOZZLE_MAP[i - 1], NOZZLE_MAP[i]
            if x <= b[1] then return Lerp( ( x - a[1] ) / ( b[1] - a[1] ), a[2], b[2] ) end
        end

        return NOZZLE_MAP[#NOZZLE_MAP][2]
    end

    function ENT:OnActivateMisc()
        BaseClass.OnActivateMisc( self )

        local mins, maxs = self:GetRenderBounds()
        local reach = ( VOLUME.maxHeight or 0 ) * {VERTEX_SCALE}
        self:SetRenderBounds( mins - Vector( reach, 40, 40 ), maxs + Vector( 0, 40, 40 ) )
        self.wtBones = {{}}

        for _, list in ipairs( {{ SURFACES, WHEELS, PROPS, NOZZLES, FLAMES }} ) do
            for _, b in ipairs( list ) do
                self.wtBones[b.bone] = self:LookupBone( b.bone )
            end
        end

        self.wtPropSpin = 0
    end

    local ang = Angle()

    local function Turn( self, bone, axis, degrees )
        bone = self.wtBones[bone]
        if not bone then return end

        ang:Zero()
        ang:RotateAroundAxis( axis, degrees )
        self:ManipulateBoneAngles( bone, ang, false )
    end

    function ENT:OnUpdateAnimations()
        if not self.wtBones then return end

        for _, s in ipairs( SURFACES ) do
            local getter = self[s.input]
            Turn( self, s.bone, s.axis, getter and getter( self ) * s.angle or 0 )
        end

        for _, w in ipairs( WHEELS ) do
            Turn( self, w.bone, w.axis, self:GetWheelSpin( w.wheel ) or 0 )
        end

        self.wtPropSpin = ( self.wtPropSpin + self:GetPower() * FrameTime() ) % 360

        for _, p in ipairs( PROPS ) do
            Turn( self, p.bone, p.axis, ( self.wtPropSpin * p.speed ) % 360 )
        end

        -- Glide's plane power spools smoothly: 0 off, 1 idle, 2 full throttle (the throttle itself is the raw key input).
        -- The nozzle glows while the engine runs, the plume grows over the last fifth of thrust. Helicopters keep theirs hidden.
        local power = self.GetThrottle and self:GetPower() or 0
        local thrust = math.Clamp( power - 1, 0, 1 )
        self.wtThrust = thrust
        self.wtGlow = math.Clamp( power, 0, 1 ) * ( 0.25 + 0.75 * thrust )
        local targetFlame = math.Clamp( ( thrust - 0.8 ) * 5, 0, 1 )
        local easing = targetFlame > ( self.wtFlameScale or 0 ) and VOLUME.preNominalEasingParams or VOLUME.postNominalEasingParams
        local seconds = math.max( ( easing or {{}} ).animationTime or 0.2, 0.01 )
        self.wtFlameScale = math.Approach( self.wtFlameScale or 0, targetFlame, FrameTime() / seconds )

        for _, f in ipairs( FLAMES ) do -- DrawTranslucent draws them instead
            local bone = self.wtBones[f.bone]
            if bone then self:ManipulateBoneScale( bone, vector_origin ) end
        end

        if #NOZZLES == 0 then return end

        local f = NozzleParam( thrust ) * ( {NOZZLE_SAMPLES} - 1 )
        if f == self.wtNozzle then return end
        self.wtNozzle = f

        local i = math.min( math.floor( f ), {NOZZLE_SAMPLES} - 2 )
        local t = f - i

        for _, n in ipairs( NOZZLES ) do
            local bone = self.wtBones[n.bone]

            if bone then
                local a, b = n.frames[i + 1], n.frames[i + 2]
                self:ManipulateBonePosition( bone, LerpVector( t, a[1], b[1] ), false )
                self:ManipulateBoneAngles( bone, LerpAngle( t, a[2], b[2] ), false )
            end
        end
    end
end

if SERVER then
    {exhaustFiles}
    ENT.ChassisMass = {mass:.0f}
    ENT.SpawnPositionOffset = Vector( 0, 0, 60 )
    ENT.HasLandingGear = {"true" if a2d else "false"} -- gear_up/gear_down sequences baked from the War Thunder animation
{nl.join(serverLines)}

    -- the camo is in the textures, skip Glide's random paint
    function ENT:GetSpawnColor()
        return Color( 255, 255, 255 )
    end

    function ENT:CreateFeatures()
{inertiaLine}
{nl.join(seatLines)}
{nl.join(weaponLines)}

{nl.join(wheelLines)}

        -- the model's own gear shows the wheels
        for _, w in ipairs( self.wheels ) do
            Glide.HideEntity( w, true )
        end

        -- spawn with the gear down (the bind pose has it retracted)
        if self.HasLandingGear then
            self:ResetSequence( "gear_down" )
        end
    end
end
'''

def writeAddon(addonDir:str, className:str, printName:str, modelPath:str, skeleton, blk:dict, tracks:dict = None, options:dict = None, gameRoot:str = None, a2d = None, surfaces:list = None, vtfCmd:str = None, nozzleModel:str = None, loadout:list = None):
	entDir = path.join(addonDir, "lua", "entities")
	makedirs(entDir, exist_ok = True)
	sounds = {}

	if isAircraft(blk):
		blk = dict(blk, loadoutGuns=[m["gun"] for m in loadout or [] if "gun" in m])
		volume = (blk.get("AfterBurner0") or {}).get("volumetricAfterBurner")
		if volume and not isHelicopter(blk):
			if not gameRoot:
				raise ValueError("WT HLSL exhaust requires the War Thunder game directory")
			from util.jetexhaust import exportExhaust
			texture = exportExhaust(gameRoot, addonDir, className, volume, vtfCmd)
			blk = dict(blk, exhaustTexture = texture)
		if gameRoot:
			sounds = exportAircraftSounds(gameRoot, blk, path.join(addonDir, "sound", "wt", className))
		lua = generateAircraftLua(className, printName, modelPath, skeleton, blk, a2d, surfaces, "", sounds, options)
		from util.wtweapons import missileLua
		from util.wtloadout import weaponLabels
		from util.i18n import LANGUAGE
		lua += missileLua(loadout or [], (options or {}).get("reloadTimes"),
			guns=[w for _, _, _, _, w in aircraftGuns(skeleton, blk)], labels=weaponLabels(gameRoot, LANGUAGE))
		if nozzleModel:
			from util.sourceparts import component_patch
			lua = component_patch(lua, nozzleModel)
		with open(path.join(entDir, f"{className}.lua"), "w", encoding = "utf-8") as f:
			f.write(lua)
	elif gameRoot and blk:
		try:
			sounds = exportSounds(gameRoot, blk, path.join(addonDir, "sound", "wt", className))
		except Exception as e: # the addon still works with Glide's default sounds
			log.log(f"War Thunder sound export failed: {e}", 2)

	if not isAircraft(blk):
		manualYaw = manualTraverseSpeed(gameRoot) if gameRoot else MANUAL_TRAVERSE

		with open(path.join(entDir, f"{className}.lua"), "w", encoding = "utf-8") as f:
			f.write(generateLua(className, printName, modelPath, skeleton, blk, tracks, options, sounds, manualYaw))

	with open(path.join(addonDir, "addon.json"), "w", encoding = "utf-8") as f:
		json.dump({"title": f"[Glide] {printName}", "type": "entity", "tags": ["fun"], "ignore": []}, f, indent = 4)
