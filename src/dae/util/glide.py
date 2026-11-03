"""Generate a Glide (gmod-glide, base_glide_tank) addon around a compiled War Thunder tank model."""
import json
import re
from math import pi, sqrt
from os import path, makedirs
from statistics import median
import util.log as log
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
	"""Export options the user can edit, prefilled from the War Thunder tank blk."""
	blk = blk or {}
	phys = blk.get("VehiclePhys", {})
	mass = phys.get("Mass", {}).get("TakeOff", blk.get("mass", 20000))

	return {
		"singleFlow": phys.get("mechanics", {}).get("steerType", "clutch_braking") == "clutch_braking",
		"mass": min(float(mass), 50000), # GMod clamps physics mass to 50000
		"maxFwdSpeed": float(blk.get("maxFwdSpeed", 60)),
		"maxRevSpeed": float(blk.get("maxRevSpeed", 15)),
		"upgraded": True,
	}

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

def soundEvents(blk:dict):
	"""{role: FMOD event path} of a tank blk"""
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
	events = soundEvents(blk)
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
	"""Every road wheel, front to rear per side: [(name, pos, index on side, count on side)] left side first.
	All of them are physics wheels, so an obstacle under any road wheel lifts the hull."""
	wheels = []

	for side in "lr":
		nodes = sorted((n for n in skeleton.getNodes() if re.fullmatch(f"bone_wheel_{side}_\\d+", n.name)), key = lambda n: -n.wtm[0][3])
		wheels.extend((n.name, gamePos(n), i, len(nodes)) for i, n in enumerate(nodes))

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
	mesh = next((c for c in wheelBone.children if c.name == wheelBone.name[len("bone_"):]), None)

	return mesh.name if mesh else wheelBone.name

def suspensionBones(skeleton, wheels:list):
	"""[(bone_suspension_* name, 1-based index of its road wheel in `wheels`)]"""
	index = {w[0]: k + 1 for k, w in enumerate(wheels)}
	result = []

	for n in skeleton.getNodes():
		if re.fullmatch("bone_suspension_[lr]_\\d+", n.name):
			wheel = next((c for c in n.children if c.name in index), None)

			if wheel:
				result.append((n.name, index[wheel.name]))

	return result

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
	allWheelBones = [spinBone(n) for n in skeleton.getNodes() if re.fullmatch("bone_wheel_[lr]_\\d+", n.name)]
	suspension = suspensionBones(skeleton, wheels)
	turretPos = gamePos(turret) if turret else (0, 0, 50)
	seatPos = gamePos(driver) if driver else (0, 0, turretPos[2] * 0.5)

	wheelLines = []

	for name, p, i, cnt in wheels:
		steer = 1 if i == 0 else (-1 if i == cnt - 1 else 0)
		wheelLines.append(f"        self:CreateWheel( {vec((p[0], p[1], p[2] + lift))}, {{ radius = {max(p[2], 5):.1f}, steerMultiplier = {steer} }} ){':SetSoundsEnabled( false )' if steer == 0 else ''}")

	firstRight = next((k + 1 for k, w in enumerate(wheels) if w[0].startswith("bone_wheel_r_")), 1)
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

	leftBones = ", ".join(f'"{b}"' for b in allWheelBones if re.match("(bone_)?wheel_l_", b))
	rightBones = ", ".join(f'"{b}"' for b in allWheelBones if re.match("(bone_)?wheel_r_", b))
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

    local LEFT_WHEELS = {{ {leftBones} }}
    local RIGHT_WHEELS = {{ {rightBones} }}

    function ENT:OnActivateMisc()
        self.leftWheelBones = {{}}
        self.rightWheelBones = {{}}

        for _, name in ipairs( LEFT_WHEELS ) do
            self.leftWheelBones[#self.leftWheelBones + 1] = self:LookupBone( name )
        end

        for _, name in ipairs( RIGHT_WHEELS ) do
            self.rightWheelBones[#self.rightWheelBones + 1] = self:LookupBone( name )
        end

        self.suspensionBones = {{}}

        for i, s in ipairs( SUSPENSION ) do
            self.suspensionBones[i] = self:LookupBone( s.bone )
        end

        self.mgYawBone = self:LookupBone( "{aaYaw.name if aaYaw else ""}" )
        self.mgPitchBone = self:LookupBone( "{aaPitch.name if aaPitch else ""}" )
    end

    local spinAng = Angle()
    local mgAng = Angle()

    function ENT:OnUpdateAnimations()
        if not self.leftWheelBones then return end

        self.trackScroll = self.trackScroll or {{}}
        self.lastTrackSpin = self.lastTrackSpin or {{}}

        for i, t in ipairs( TRACKS ) do
            local spin = self:GetWheelSpin( t.wheel )
            local delta = ( spin - ( self.lastTrackSpin[i] or spin ) + 180 ) % 360 - 180

            self.trackScroll[i] = ( ( self.trackScroll[i] or 0 ) + delta * t.scale ) % 1
            self.lastTrackSpin[i] = spin
        end

        self:UpdateSuspension()

        -- bones are Y-up (studiomdl $upaxis Y): rolling is around the bone's Z axis
        spinAng[2] = self:GetWheelSpin( 1 )

        for _, b in ipairs( self.leftWheelBones ) do
            self:ManipulateBoneAngles( b, spinAng, false )
        end

        spinAng[2] = self:GetWheelSpin( {firstRight} )

        for _, b in ipairs( self.rightWheelBones ) do
            self:ManipulateBoneAngles( b, spinAng, false )
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

    function ENT:WheelThink( dt, selfTbl )
        BaseClass.WheelThink( self, dt, selfTbl )

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

        -- tracks: scale Glide's per surface rolling resistance up (also for surfaces it has no entry for)
        for id, r in pairs( self.surfaceResistance ) do
            self.surfaceResistance[id] = r * {resistScale:.2f}
        end

        setmetatable( self.surfaceResistance, {{ __index = function() return {0.05 * resistScale:.3f} end }} )

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

def writeAddon(addonDir:str, className:str, printName:str, modelPath:str, skeleton, blk:dict, tracks:dict = None, options:dict = None, gameRoot:str = None):
	entDir = path.join(addonDir, "lua", "entities")
	makedirs(entDir, exist_ok = True)
	sounds = {}

	if gameRoot and blk:
		try:
			sounds = exportSounds(gameRoot, blk, path.join(addonDir, "sound", "wt", className))
		except Exception as e: # the addon still works with Glide's default sounds
			log.log(f"War Thunder sound export failed: {e}", 2)

	manualYaw = manualTraverseSpeed(gameRoot) if gameRoot else MANUAL_TRAVERSE

	with open(path.join(entDir, f"{className}.lua"), "w", encoding = "utf-8") as f:
		f.write(generateLua(className, printName, modelPath, skeleton, blk, tracks, options, sounds, manualYaw))

	with open(path.join(addonDir, "addon.json"), "w", encoding = "utf-8") as f:
		json.dump({"title": f"[Glide] {printName}", "type": "entity", "tags": ["fun"], "ignore": []}, f, indent = 4)
