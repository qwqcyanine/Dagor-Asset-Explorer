"""Bake one native WT aircraft loadout and retain per-mount weapon metadata."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import csv
import io
import math


def items(value):
	return value if isinstance(value, list) else [value] if value else []


def presets(blk):
	return [(p.get("name") or Path(p["blk"]).stem, p["blk"])
		for p in items((blk.get("weapon_presets") or {}).get("preset")) if p.get("blk")]


def weaponLabels(gameRoot, language, slots=()):
	"""Read WT's display strings, never use translated text as a preset identifier."""
	from util.vromfs import VROMFS
	if not gameRoot:
		return {}
	try:
		vfs = VROMFS(str(Path(gameRoot) / "lang.vromfs.bin"))
	except FileNotFoundError:
		return {}
	labels = {}
	for name in ("lang/units_weaponry.csv", "lang/units_modifications.csv"):
		if name not in vfs.files:
			continue
		rows = csv.DictReader(io.StringIO(vfs.read(name).decode("utf-8-sig")), delimiter=";")
		for row in rows:
			key = row[rows.fieldnames[0]]
			english = (row.get("<English>") or "").strip()
			value = (row.get("<Chinese>") or english) if language == "zh_CN" else english
			value = value.replace("\u200b", "").strip()
			if key and value:
				labels[key] = value
			if english:
				labels[key + "/english"] = english
	containers = {w["blk"].replace("\\", "/") for _, choices in slots for _, preset in choices
		for w in items(preset.get("Weapon")) if "/containers/" in w.get("blk", "").replace("\\", "/").lower()}
	if containers:
		from util.i18n import tr
		definitions = VROMFS(str(Path(gameRoot) / "aces.vromfs.bin"))
		for ref in sorted(containers):
			definition = definitions.readBlk(ref)
			child = "weapons/" + Path(definition.get("blk", "").replace("\\", "/")).stem
			if labels.get(child):
				labels["weapons/" + Path(ref).stem] = tr("Weapon pod ({count} × {weapon})",
					count=definition.get("bullets", 1), weapon=labels[child])
	return labels


def presetLabel(preset, labels):
	from util.i18n import tr
	counts = Counter()
	details = []
	for weapon in items(preset.get("Weapon")):
		if weapon.get("dummy"):
			continue
		ref = weapon.get("blk", "").replace("\\", "/")
		stem = Path(ref).stem
		key = "weapons/" + stem
		label = labels.get(key)
		if label:
			# Keep recognizable model designations alongside WT's localized weapon type.
			short, english = labels.get(key + "/short"), labels.get(key + "/short/english")
			if short and english and short != english:
				label = label.replace(short, english, 1)
		else:
			kind = {"aam": "Air-to-air missile", "agm": "Air-to-ground missile", "bombs": "Bomb",
				"rockets": "Rocket", "additional gun": "Gun pod"}.get(weapon.get("trigger"))
			label = f"{stem} {tr(kind)}" if kind else stem
		isGun = weapon.get("trigger") == "additional gun"
		if isGun:
			pod = labels.get("modification/" + preset.get("reqModification", ""))
			if pod:
				label = f"{pod} ({label})"
		counts[label] += 1 if isGun else weapon.get("bullets", 1)
		details.append(f"{labels.get(key, label)}\n{ref}")
	label = " + ".join(f"{count} × {name}" if count != 1 else name for name, count in counts.items())
	return label or preset.get("name", ""), "\n".join([preset.get("name", ""), *dict.fromkeys(details)])


def slotChoices(blk):
	return [(s["index"], [(p["name"], p) for p in items(s.get("WeaponPreset")) if p.get("name")])
		for s in items((blk.get("WeaponSlots") or {}).get("WeaponSlot")) if s["index"] != 0]


def resolve(blk, presetPath, vfs):
	"""Preset names are slot-local; custom selections use the same native validation."""
	if isinstance(presetPath, dict):
		entries = [{"slot": int(slot), "preset": name} for slot, name in presetPath.items() if name]
	else:
		if presetPath not in [p for _, p in presets(blk)]:
			raise ValueError(f"Unknown aircraft loadout: {presetPath}")
		entries = items(vfs.readBlk(presetPath).get("Weapon"))
	slots = {s["index"]: s for s in items((blk.get("WeaponSlots") or {}).get("WeaponSlot"))}
	selected, seen = [], set()
	for entry in entries:
		index = entry["slot"]
		if index == 0:
			continue
		if index in seen:
			raise ValueError(f"Duplicate loadout slot {index}")
		seen.add(index)
		matches = [p for p in items(slots.get(index, {}).get("WeaponPreset")) if p.get("name") == entry["preset"]]
		if len(matches) != 1:
			raise ValueError(f"Loadout slot {index}: ambiguous or missing preset {entry['preset']}")
		selected.append((index, matches[0]))
	return selected


def hiddenNodes(blk, selected, names=()):
	from util.glide import aircraftHiddenNodes, AIRCRAFT_HIDDEN_RE
	hidden = aircraftHiddenNodes(names, blk)
	show = set()
	for _, preset in selected:
		hidden.update(items((preset.get("HideNodes") or {}).get("node")))
		show.update(items((preset.get("ShowNodes") or {}).get("node")))
	return (hidden - show) | {n for n in names if AIRCRAFT_HIDDEN_RE.fullmatch(n)}


def mounts(selected, skeleton, vfs):
	result = []
	for index, preset in selected:
		for weapon in items(preset.get("Weapon")):
			if weapon.get("dummy"):
				continue
			definition = vfs.readBlk(weapon["blk"])
			if weapon.get("trigger") == "additional gun":
				continue  # Native pod geometry is selected with ShowNodes; the emitter belongs to the aircraft.
			mesh = definition.get("mesh")
			if mesh == "empty_mesh":
				continue  # Pods represented entirely by the aircraft's ShowNodes.
			emitter = weapon.get("emitter")
			if not isinstance(mesh, str) or not mesh or not isinstance(emitter, str):
				raise ValueError(f"Loadout slot {index}: unsupported mesh/emitter in {weapon['blk']}")
			node = skeleton.getNodeByName(emitter)
			if node is None:
				raise ValueError(f"Loadout slot {index}: missing emitter {emitter}")
			if weapon.get("bullets", 1) != 1:
				raise ValueError(f"Loadout slot {index}: multiple rounds need explicit mount transforms ({emitter})")
			result.append((index, mesh, node))
	return result


def loadModels(gameRoot, names):
	from parse.gameres import GameResourcePack, GameResDesc
	from parse.realres import DynModel, GeomNodeTree
	from util.assetcacher import AssetCacher
	res = Path(gameRoot) / "content/base/res"
	# Read descriptor materials before constructing weapon meshes.
	desc = GameResDesc(str(res / "dynModelDesc.bin"))
	desc.loadDataBlock()
	AssetCacher.appendGameResDesc(desc)
	found = {}
	packs = [res / "aces.grp"] + sorted(p for p in res.rglob("*.grp") if p != res / "aces.grp")
	for path in packs:
		if not names - found.keys():
			break
		pack = GameResourcePack(str(path))
		assets = pack.getPackedFiles()
		wanted = [a for a in assets if isinstance(a, DynModel) and a.name in names - found.keys()]
		if not wanted:
			continue
		for asset in assets:
			if isinstance(asset, GeomNodeTree):
				AssetCacher.cacheAsset(asset)
		for asset in wanted:
			found[asset.name] = asset.getModel(0)
	if names - found.keys():
		raise ValueError(f"Missing WT weapon models: {', '.join(sorted(names - found.keys()))}")
	cacheTextures(gameRoot, found.values())
	return found


def cacheTextures(gameRoot, models):
	from parse.material import DDSx, DDSxTexturePack2, MaterialData
	from util.assetcacher import AssetCacher
	from util.glide import cacheHQTextures
	from util import log
	textures = {t for model in models for mat in model.materials or () for t in mat.textures}
	missing = {MaterialData.getTexFileName(t) for t in textures
		if not AssetCacher.getCachedAsset(DDSx, MaterialData.getTexFileName(t))}
	for pack in sorted((Path(gameRoot) / "content/base/res").rglob("*.dxp.bin")):
		if not missing:
			break
		try:
			for tex in DDSxTexturePack2(str(pack)).getPackedFiles():
				if tex.name in missing:
					AssetCacher.cacheAsset(tex)
					missing.remove(tex.name)
		except Exception as error:
			log.log(f"Skipping weapon texture pack {pack}: {error}", 2)
	cacheHQTextures(gameRoot, textures)
	missing = {t for t in missing if not AssetCacher.getCachedAsset(DDSx, t)}
	if missing:
		raise ValueError(f"Missing WT weapon textures: {', '.join(sorted(missing))}")


def mountedModel(source, node, name):
	"""Transform in WT coordinates; the existing SMD exporter handles mirror/axis conversion."""
	import numpy as np
	from parse.realres import Model
	from util.misc import vectorTransform
	materials = deepcopy(source.materials or ())
	names = {}
	for material in materials:
		old = material.getName()
		material.setName(f"loadout_{source.name}_{old}")
		names[old] = material.getName()
	out = Model(name, materials=materials)
	for obj in source:
		parent = source.skeleton.getNodeByName(obj.name) if source.skeleton and not obj.skinned else None
		linear = np.asarray(node.wtm)[:3, :3]
		if parent is not None:
			linear = linear @ np.asarray(parent.wtm)[:3, :3]
		# Baking a reflection reverses winding; SMD's later axis conversion cannot undo it.
		mirrored = np.linalg.det(linear) < 0
		part = out.newObject(f"{name}_{obj.name}", skinned=True)
		for start, mat in obj.materials.items():
			part.appendMaterial(names.get(mat, mat), start)
		indices = {}
		for face in obj.faces:
			for vertex in face:
				if vertex not in indices:
					i = out.vertCnt
					indices[vertex] = i
					position = vectorTransform(node.wtm, source.getVertex(vertex, parentBone=parent))
					out.appendVerts([position], [source.getUV(vertex)], scale=False)
					out.skin[i] = ((node.idx, 1.0),)
			part.appendFace(tuple(indices[v] for v in (reversed(face) if mirrored else face)))
	return out


def hardpointMarkers(blk, skeleton, selected=()):
	"""Use native emitter transforms, including a representative mount for empty slots."""
	chosen = dict(selected)
	markers = []
	if skeleton is None:
		return markers
	for index, choices in slotChoices(blk):
		presets = [chosen[index]] if index in chosen else [p for _, p in choices]
		for preset in presets:
			nodes = {w.get("emitter"): skeleton.getNodeByName(w.get("emitter", ""))
				for w in items(preset.get("Weapon")) if not w.get("dummy")}
			nodes = [n for n in nodes.values() if n is not None]
			if nodes:
				pos = tuple(sum(n.wtm[axis][3] for n in nodes) / len(nodes) for axis in range(3))
				markers.append((index, (pos[0], pos[1], -pos[2]), index in chosen))
				break
	return markers


def containerRounds(definition, pod, mount, vfs):
	"""Resolve native tube transforms; never guess a grid or reuse the aircraft emitter."""
	import numpy as np
	from types import SimpleNamespace
	from util.wtweapons import ammoCount
	count = ammoCount(definition)
	bounds, pattern = definition.get("emitterGenRange"), definition.get("emitterGenFmt")
	if not definition.get("useEmitter") or not isinstance(bounds, (tuple, list)) or len(bounds) != 2 or not isinstance(pattern, str) or bounds[1] - bounds[0] + 1 != count:
		raise ValueError("Unsupported container emitter layout")
	child = vfs.readBlk(definition["blk"])
	if not child.get("rocket") or not child.get("mesh") or child.get("container"):
		raise ValueError("Unsupported container projectile")
	result = []
	for index in range(bounds[0], bounds[1] + 1):
		node = pod.skeleton.getNodeByName(pattern % index) if pod.skeleton else None
		if node is None:
			raise ValueError(f"Missing container emitter: {pattern % index}")
		result.append((child["mesh"], SimpleNamespace(idx=mount.idx, name=mount.name,
			wtm=np.asarray(mount.wtm) @ np.asarray(node.wtm))))
	return child, result


def apply(model, blk, presetPath, gameRoot, keepBones, *, previewOnly=False):
	from util.vromfs import VROMFS
	vfs = VROMFS(str(Path(gameRoot) / "aces.vromfs.bin"))
	selected = resolve(blk, presetPath, vfs)
	mountList = mounts(selected, model.skeleton, vfs)
	models = loadModels(gameRoot, {mesh for _, mesh, _ in mountList}) if mountList else {}
	from util.wtweapons import reloadTime, ammoCount
	from util.glide import gamePos
	gameplay = vfs.readBlk("config/gameplay.blk") if not previewOnly else {}
	report = []
	weapons = []
	expanded = []
	childModels = set()
	containers = {}
	for slot, mesh, node in mountList:
		preset = next(p for index, p in selected if index == slot)
		weapon = next(w for w in items(preset.get("Weapon")) if w.get("emitter") == node.name)
		definition = vfs.readBlk(weapon["blk"])
		expanded.append((slot, mesh, node))
		weapons.append(weapon)
		if definition.get("container") and weapon.get("trigger") in ("rockets", "agm", "aam"):
			child, rounds = containerRounds(definition, models[mesh], node, vfs)
			parent = f"loadout_{len(expanded) - 1}_{slot}_{mesh}"
			for childMesh, childNode in rounds:
				if weapon.get("trigger") == "rockets":
					containers[len(expanded)] = parent
				expanded.append((slot, childMesh, childNode))
				weapons.append(dict(weapon, blk=definition["blk"], bullets=1))
				childModels.add(childMesh)
	if childModels:
		models.update(loadModels(gameRoot, childModels))
	mountList = expanded
	for i, (slot, mesh, node) in enumerate(mountList):
		weapon = weapons[i]
		entry = {"slot": slot, "mesh": mesh, "emitter": node.name, "prefix": f"loadout_{i}_{slot}_{mesh}", "pos": gamePos(node)}
		if i in containers:
			entry["container"] = containers[i]
		if not previewOnly and weapon.get("trigger") in ("aam", "agm", "bombs", "rockets") and not vfs.readBlk(weapon["blk"]).get("container"):
			weapon = dict(weapon, weaponBlk=vfs.readBlk(weapon["blk"]))
			if ammoCount(weapon) != 1:
				raise ValueError(f"Missile mount requires one round: {weapon['blk']}")
			definition = weapon["weaponBlk"]
			if weapon["trigger"] == "bombs":
				bomb = definition.get("bomb") or {}
				values = [bomb.get(k) for k in ("mass", "explosiveMass")] + [definition.get("shotFreq")]
				if bomb.get("guidance") or bomb.get("guidanceType") or bomb.get("brakeTime"):
					raise ValueError(f"Guided/retarded bombs are not supported yet: {weapon['blk']}")
				if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in values):
					raise ValueError(f"Unsupported bomb data: {weapon['blk']}")
			else:
				rocket = definition.get("rocket") or {}
				lifetimeKey = "maxDistance" if weapon["trigger"] == "rockets" and not rocket.get("guidanceType") and "timeLife" not in rocket else "timeLife"
				values = [rocket.get(k) for k in (lifetimeKey, "endSpeed", "force", "mass")] + [definition.get("shotFreq")]
				startSpeed = rocket.get("startSpeed")
				if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in values) or not isinstance(startSpeed, (int, float)) or not math.isfinite(startSpeed) or startSpeed < 0:
					raise ValueError(f"Unsupported missile flight data: {weapon['blk']}")
			weapon["arcadeReload"] = reloadTime(blk, weapon, gameplay)
			entry["weapon"] = weapon
		report.append(entry)
	for slot, preset in (() if previewOnly else selected):
		for weapon in items(preset.get("Weapon")):
			if weapon.get("trigger") != "additional gun" or weapon.get("dummy"):
				continue
			weapon = dict(weapon, weaponBlk=vfs.readBlk(weapon["blk"]))
			node = model.skeleton.getNodeByName(weapon.get("emitter", ""))
			if node is None:
				raise ValueError(f"Missing gun pod emitter: {weapon.get('emitter')}")
			weapon["bullets"] = ammoCount(weapon)
			weapon["arcadeReload"] = reloadTime(blk, weapon, gameplay)
			frequency = weapon["weaponBlk"].get("shotFreq")
			if not isinstance(frequency, (int, float)) or not math.isfinite(frequency) or frequency <= 0:
				raise ValueError(f"Invalid gun pod fire rate: {weapon['blk']}")
			report.append({"slot": slot, "gun": weapon})
	# Resolve everything before mutating the aircraft, so unsupported presets fail explicitly.
	parts = [mountedModel(models[mesh], node, f"loadout_{i}_{slot}_{mesh}")
		for i, (slot, mesh, node) in enumerate(mountList)]
	model.removeObjects(hiddenNodes(blk, selected, [o.name for o in model]))
	for part in parts:
		model.mergeModel(part)
	keepBones.update(node.name for _, _, node in mountList)
	keepBones.update(m["gun"]["emitter"] for m in report if "gun" in m)
	return report
