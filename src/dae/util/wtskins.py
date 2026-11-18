"""Import WT UserSkins replace_tex ZIPs and built-in WT camouflages as Source $texturegroup families."""
import csv
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from io import BytesIO, StringIO
import hashlib
import json
import re
import subprocess
import zipfile

import numpy as np
from PIL import Image
from parse.material import DDSx, DDSxTexturePack2, MaterialData
from util.assetcacher import AssetCacher
from util.enums import TEXTURE_NORMAL
from util.vromfs import VROMFS, blkList


_TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[{}:=;]', re.S)


def replacements(text):
	"""Strict subset used by downloadable UserSkins; never silently ignore directives."""
	tokens, end = [], 0
	for match in _TOKEN.finditer(text.lstrip('\ufeff')):
		if match.start() != end:
			raise ValueError("Unsupported UserSkin BLK syntax")
		end = match.end()
		token = match[0]
		if not token.isspace() and not token.startswith(('//', '/*')) and token != ';':
			tokens.append(token)
	if end != len(text.lstrip('\ufeff')):
		raise ValueError("Unsupported UserSkin BLK syntax")
	result, i = [], 0
	while i < len(tokens):
		if tokens[i:i + 4] == ['name', ':', 't', '=']:
			if i + 4 >= len(tokens) or not tokens[i + 4].startswith('"'):
				raise ValueError("Invalid UserSkin name")
			i += 5
			continue
		if tokens[i:i + 2] != ['replace_tex', '{']:
			raise ValueError("Only replace_tex UserSkins are supported (not set_tex or includes)")
		i += 2
		fields = {}
		while i < len(tokens) and tokens[i] != '}':
			key = tokens[i]
			if key not in ('from', 'to') or key in fields or tokens[i + 1:i + 4] != [':', 't', '='] or i + 4 >= len(tokens):
				raise ValueError("Invalid replace_tex entry")
			try:
				fields[key] = json.loads(tokens[i + 4])
			except (ValueError, TypeError) as exc:
				raise ValueError("Invalid replace_tex filename") from exc
			if not isinstance(fields[key], str) or not fields[key]:
				raise ValueError("Empty replace_tex filename")
			i += 5
		if i >= len(tokens) or set(fields) != {'from', 'to'}:
			raise ValueError("Incomplete replace_tex entry")
		result.append((fields['from'].lower(), fields['to']))
		i += 1
	if not result:
		raise ValueError("No replace_tex entries in UserSkin")
	return result


def safePath(name):
	name = name.replace('\\', '/')
	p = PurePosixPath(name)
	if p.is_absolute() or '..' in p.parts or ':' in name or '\x00' in name:
		raise ValueError(f"Unsafe UserSkin path: {name!r}")
	return p


class SkinArchive:
	def __init__(self, filename, modelName=None):
		self.path = Path(filename)
		self.name = self.path.stem
		with zipfile.ZipFile(self.path) as archive:
			files = {}
			for info in archive.infolist():
				p = safePath(info.filename)
				if info.is_dir():
					continue
				if info.file_size > 512 * 1024 * 1024 or info.flag_bits & 1:
					raise ValueError("Oversized/encrypted UserSkin file")
				key = str(p).lower()
				if key in files:
					raise ValueError("Duplicate UserSkin file")
				files[key] = info
			manifests = [k for k in files if k.endswith('.blk')]
			if len(manifests) != 1:
				matches = [m for m in manifests if modelName and PurePosixPath(m).stem == modelName.lower()]
				if len(matches) != 1:
					raise ValueError(f"Cannot uniquely select UserSkin BLK for {modelName or '(unknown model)'}; candidates: {', '.join(manifests) or '(none)'}")
				manifest = matches[0]
			else:
				manifest = manifests[0]
			self.manifest = files[manifest].filename
			if files[manifest].file_size > 1024 * 1024:
				raise ValueError("Oversized UserSkin BLK")
			self.rules = []
			for pattern, target in replacements(archive.read(files[manifest]).decode('utf-8-sig')):
				ref = str(PurePosixPath(manifest).parent / safePath(target)).lower()
				if ref not in files or PurePosixPath(ref).suffix not in ('.dds', '.tga', '.png'):
					raise ValueError(f"Missing/unsupported UserSkin texture: {target}")
				self.rules.append((pattern, files[ref].filename))


def _openVromfs(gameRoot: Path, name: str):
	for p in sorted((gameRoot / "cache").glob(f"binary.*/{name}"), reverse=True):
		if p.is_file():
			try:
				return VROMFS(str(p))
			except Exception:
				pass
	for p in (gameRoot / name, gameRoot / "ui" / name, gameRoot / "content" / name):
		if p.is_file():
			try:
				return VROMFS(str(p))
			except Exception:
				pass
	return None


def _findUnitBlk(gameRoot: Path, modelName: str):
	vfs = _openVromfs(gameRoot, "aces.vromfs.bin")
	if vfs is None or not modelName:
		return None, None, None
	low = modelName.lower()
	norm = low.replace("-", "_")
	for f in vfs.files:
		if f.startswith("gamedata/units/tankmodels/") and f.count("/") == 3 and (f.endswith(f"_{low}.blk") or f.endswith(f"/{low}.blk")):
			try:
				blk = vfs.readBlk(f)
			except Exception:
				continue
			if Path(f).stem.lower() == low or str(blk.get("model", "")).lower() == low:
				return Path(f).stem.lower(), f, blk
	for f in vfs.files:
		if f.startswith("gamedata/units/tankmodels/") and f.count("/") == 3 and f.endswith(".blk"):
			try:
				blk = vfs.readBlk(f)
			except Exception:
				continue
			if str(blk.get("model", "")).lower() == low:
				return Path(f).stem.lower(), f, blk
	fmFiles = [f for f in vfs.files if f.startswith("gamedata/flightmodels/") and f.count("/") == 2 and f.endswith(".blk")]
	exact = f"gamedata/flightmodels/{low}.blk"
	cand = exact if exact in vfs.files else next((f for f in fmFiles if Path(f).stem.lower().replace("-", "_") == norm), None)
	if cand:
		try:
			return Path(cand).stem.lower(), cand, vfs.readBlk(cand)
		except Exception:
			pass
	for f in fmFiles:
		try:
			blk = vfs.readBlk(f)
		except Exception:
			continue
		if str(blk.get("model", "")).lower().replace("-", "_") == norm:
			return Path(f).stem.lower(), f, blk
	return None, None, None


def _skinLocTable(gameRoot: Path, language: str = "en") -> dict[str, str]:
	out = {}
	wantCol = "<Chinese>" if language == "zh_CN" else "<English>"
	for vname, csvPath in (("lang.vromfs.bin", "lang/unlocks_skins.csv"), ("regional-lang.vromfs.bin", "lang/regional_skins.csv")):
		vfs = _openVromfs(gameRoot, vname)
		if vfs is None or csvPath not in vfs.files:
			continue
		try:
			rows = csv.reader(StringIO(vfs.read(csvPath).decode("utf-8", "replace")), delimiter=";")
			header = next(rows, [])
			col = header.index(wantCol) if wantCol in header else (header.index("<English>") if "<English>" in header else 1)
			for row in rows:
				if len(row) > col and row[0]:
					val = row[col].replace("\u200b", "").replace("\\t", "").replace("\t", " ").strip()
					if val:
						out[row[0].strip().lower()] = val
		except Exception:
			pass
	return out


def builtinSkins(gameRoot, modelName, language: str = "en") -> list[dict]:
	"""Discover War Thunder built-in skins (downloadable_skins.blk + unit BLK skin entries) for modelName."""
	if not gameRoot or not modelName:
		return []
	root = Path(gameRoot)
	if not root.is_dir():
		return []
	unitName, unitPath, blk = _findUnitBlk(root, modelName)
	unit = (unitName or modelName).lower()
	loc = _skinLocTable(root, language)
	out, seen = [], set()

	regVfs = _openVromfs(root, "regional.vromfs.bin")
	if regVfs is not None:
		for blkFile in ("dldata/downloadable_skins.blk", "config/skins_ext.blk"):
			if blkFile not in regVfs.files:
				continue
			try:
				dl = regVfs.readBlk(blkFile)
			except Exception:
				continue
			for key, entry in dl.items():
				if not isinstance(entry, dict):
					continue
				u = str(entry.get("modelName") or (key.split("#", 1)[0] if "#" in key else "")).lower()
				if u != unit:
					continue
				sid = str(entry.get("mangledID") or entry.get("name") or (key.split("#", 1)[1] if "#" in key else key))
				if not sid or sid.lower() in seen:
					continue
				ruleMap = {}
				for k, v in entry.items():
					if isinstance(v, dict):
						h = v.get("lod0") or v.get("lod1") or v.get("lod2")
						if h:
							ruleMap[k.lower()] = (k.lower(), f"dldata:{h}", str(v.get("param") or ""))
				if not ruleMap:
					continue
				title = loc.get(f"{unit}/{sid.lower()}") or loc.get(f"skin/{sid.lower()}") or sid
				label = f"{title} ({sid})" if title.lower() != sid.lower() else sid
				seen.add(sid.lower())
				out.append({
					"id": f"wt:{unit}#{sid}",
					"name": sid,
					"label": label,
					"blk": f"{blkFile}#{unit}#{sid}",
					"rules": list(ruleMap.values()),
				})

	if isinstance(blk, dict):
		for s in blkList(blk.get("default_skin")) + blkList(blk.get("skin")):
			if not isinstance(s, dict):
				continue
			sid = str(s.get("name") or "default")
			if not sid or sid.lower() in seen:
				continue
			ruleMap = {}
			for r in blkList(s.get("replace_tex")):
				if isinstance(r, dict) and r.get("from") and r.get("to"):
					pat = str(r["from"]).lower()
					ruleMap[pat] = (pat, f"dxp:{str(r['to']).split('*')[0]}", "")
			for r in blkList(s.get("set_tex")):
				if isinstance(r, dict) and r.get("from") and r.get("to"):
					pat = str(r["from"]).lower()
					ruleMap[pat] = (pat, f"dxp:{str(r['to']).split('*')[0]}", str(r.get("param") or ""))
			if not ruleMap:
				continue
			locId = str(s.get("nameLocId") or "").lower()
			title = loc.get(f"{unit}/{sid.lower()}") or (loc.get(locId) if locId else None) or loc.get(f"skin/{sid.lower()}") or sid
			label = f"{title} ({sid})" if title.lower() != sid.lower() else sid
			seen.add(sid.lower())
			out.append({
				"id": f"wt:{unit}#{sid}",
				"name": sid,
				"label": label,
				"blk": f"{unitPath}#{sid}",
				"rules": list(ruleMap.values()),
			})

	return out


def _cacheBuiltinSkinTextures(gameRoot: Path, want: set[str], modelName: str = ""):
	missing = lambda: {n for n in want if not any(c.getPixelCnt() > 4096 for c in AssetCacher.getCachedAsset(DDSx, n) or ())}
	if not gameRoot or not missing():
		return
	root = Path(gameRoot)
	stem = (modelName or "").lower()
	priority = [
		root / "content/base/res/tanks/gm-hq.dxp.bin",
		root / "content/base/res/tanks/gm.dxp.bin",
		*(sorted((root / "content.hq/hq_tex/res").rglob(f"*{stem}*.dxp.bin")) if stem else ()),
		*sorted((root / "content/base/res/tanks").glob("*.dxp.bin")),
		*sorted((root / "content/base/res/aircrafts").glob("*.dxp.bin")),
	]
	visited = set()
	for p in priority:
		if not missing():
			break
		if not p.is_file() or p.name == "zzz-tq_pack.dxp.bin" or p in visited:
			continue
		visited.add(p)
		try:
			for tex in DDSxTexturePack2(str(p)).getPackedFiles():
				if tex.name in want and all(c.getPixelCnt() < tex.getPixelCnt() for c in AssetCacher.getCachedAsset(DDSx, tex.name) or ()):
					AssetCacher.cacheAsset(tex)
		except Exception:
			pass


def _loadBuiltinTarget(gameRoot: Path, target: str, key: str) -> bytes:
	if target.startswith("dldata:"):
		h = target[7:]
		if not gameRoot:
			raise ValueError(f"Game root required for downloadable skin texture {h}")
		ddsxPath = Path(gameRoot) / "cache/content" / h[:2] / f"{h[2:]}.ddsx"
		if not ddsxPath.is_file():
			import requests
			url = f"https://dldata-aws.warthunder.com/production/{h}.ddsx"
			resp = requests.get(url, timeout=30)
			resp.raise_for_status()
			ddsxPath.parent.mkdir(parents=True, exist_ok=True)
			ddsxPath.write_bytes(resp.content)
		return DDSx(str(ddsxPath), key).getDDS()
	if target.startswith("dxp:"):
		tname = target[4:]
		cached = AssetCacher.getCachedAsset(DDSx, tname)
		if not cached:
			raise ValueError(f"Missing built-in skin texture: {tname}")
		return max(cached, key=lambda d: d.getPixelCnt()).getDDS()
	raise ValueError(f"Unsupported built-in skin target: {target}")


def _resizeChannels(img: Image.Image, size: tuple[int, int]) -> Image.Image:
	if img.size == size:
		return img
	return Image.merge(img.mode, [ch.resize(size, Image.Resampling.BILINEAR) for ch in img.split()])


def _compositeCamoSkinTex(baseBytes: bytes, skinImg: Image.Image, camoBytes: bytes | None = None, exp: float = 0.25) -> bytes:
	with Image.open(BytesIO(baseBytes)) as baseRaw:
		baseImg = _resizeChannels(baseRaw.convert("RGBA"), skinImg.size)
	baseArr = np.asarray(baseImg, dtype=np.float32) / 255.0
	skinArr = np.asarray(skinImg, dtype=np.float32) / 255.0
	sw = skinArr[..., 3:4]
	bw = baseArr[..., 3:4]
	if camoBytes is not None:
		with Image.open(BytesIO(camoBytes)) as camoRaw:
			camoImg = _resizeChannels(camoRaw.convert("RGBA"), skinImg.size)
		camoArr = np.asarray(camoImg, dtype=np.float32) / 255.0
		camoRgb = camoArr[..., :3] * (1.0 - sw) + skinArr[..., :3] * sw
		combMask = bw + sw * (1.0 - bw)
		det = np.minimum(bw + 0.25, 1.0) ** 4 * 0.5 + 0.5
		det = det + sw * (1.0 - det)
	else:
		camoRgb = skinArr[..., :3]
		combMask = sw
		det = 1.0
	weight = np.power(np.clip(combMask, 0.0, 1.0), exp)
	outArr = np.empty_like(skinArr, dtype=np.uint8)
	outArr[..., :3] = np.rint((baseArr[..., :3] * (1.0 - weight) + camoRgb * det * weight) * 255.0).clip(0, 255).astype(np.uint8)
	outArr[..., 3] = 255
	buf = BytesIO()
	Image.fromarray(outArr, "RGBA").save(buf, format="DDS")
	return buf.getvalue()


def importSkins(qc, materials, texturePaths, archives, converter, modelName=None, gameRoot=None, vtfFormat="DXT5"):
	"""Write variant VMT/VTFs and QC before StudioMDL runs; skin 0 is unchanged.
	Returns a manifest including unused rules (e.g. pylons omitted from the model).
	"""
	qc = Path(qc)
	if not archives:
		return []
	text = qc.read_text()
	if '$texturegroup' in text.lower():
		raise ValueError("QC already contains skins; regenerate the export before importing")
	cd = re.search(r'\$cdmaterials\s+"([^"]+)"', text, re.I)
	if not cd or not materials or texturePaths is None:
		raise ValueError("UserSkin import requires exported model materials")
	base = qc.parent / 'source_export/materials' / cd[1]
	base.mkdir(parents=True, exist_ok=True)
	originals = {m.getName(): m.getVMT(texturePaths) for m in materials}
	builtinMap = {}
	if any(isinstance(a, dict) or str(a).startswith("wt:") for a in archives):
		for b in builtinSkins(gameRoot, modelName or qc.stem):
			builtinMap[b["id"].lower()] = b
			builtinMap[f"wt:{b['name'].lower()}"] = b
		wantDxp = set()
		for a in archives:
			b = a if isinstance(a, dict) else builtinMap.get(str(a).lower())
			for pattern, target, param in (b or {}).get("rules", ()):
				if target.startswith("dxp:"):
					wantDxp.add(target[4:])
				if param == "camo_skin_tex":
					for tex in texturePaths.getDict().values():
						if fnmatchcase(tex.tex.lower(), pattern):
							wantDxp.add(tex.tex)
					for m in materials:
						if m.diffuse and fnmatchcase(MaterialData.getTexFileName(m.diffuse).lower(), pattern) and m.mask:
							wantDxp.add(MaterialData.getTexFileName(m.mask))
		_cacheBuiltinSkinTextures(gameRoot, wantDxp, modelName or qc.stem)
	rows, changed, reports = [], set(), []
	for index, filename in enumerate(archives, 1):
		builtin = filename if isinstance(filename, dict) else (builtinMap.get(str(filename).lower()) if str(filename).startswith("wt:") else None)
		if builtin is not None:
			skinName = builtin["name"]
			skinManifest = builtin["blk"]
			skinRules = builtin["rules"]
			digest = hashlib.sha256(skinManifest.encode()).hexdigest()[:12]
			archiveCtx = None
		elif str(filename).startswith("wt:"):
			raise ValueError(f"Unknown built-in skin: {filename}")
		else:
			skin = SkinArchive(filename, modelName or qc.stem)
			skinName = skin.name
			skinManifest = skin.manifest
			skinRules = [(p, t, "") for p, t in skin.rules]
			with skin.path.open('rb') as stream:
				digest = hashlib.file_digest(stream, 'sha256').hexdigest()[:12]
			archiveCtx = skin.path
		namespace = f'skins/{index}_{digest}'
		destination = base / namespace
		destination.mkdir(parents=True, exist_ok=True)
		mapping, camoReplaced, used = {}, set(), set()
		with (zipfile.ZipFile(archiveCtx) if archiveCtx is not None else BytesIO()) as archive:
			for key, tex in texturePaths.getDict().items():
				matches = [(pattern, target, param) for pattern, target, param in skinRules if fnmatchcase(tex.tex.lower(), pattern)]
				if not matches:
					continue
				if len(matches) != 1:
					raise ValueError(f"Ambiguous UserSkin replacement for {tex.tex}")
				pattern, target, param = matches[0]
				mat = next(
					(
						m for m in materials
						if (m.diffuse and MaterialData.getTexFileName(m.diffuse) == tex.tex and ("masked" in m.cls or key == tex.tex))
						or (m.normal and MaterialData.getTexFileName(m.normal) == tex.tex)
					),
					MaterialData(),
				)
				data = archive.read(target) if archiveCtx is not None else _loadBuiltinTarget(gameRoot, target, key)
				if param == "camo_skin_tex":
					with Image.open(BytesIO(data)) as image:
						if image.width * image.height > 8192 * 8192:
							raise ValueError("UserSkin texture exceeds 8192x8192 pixel budget")
						skinImg = image.convert("RGBA")
					if skinImg.getchannel("A").getextrema()[1] == 0:
						used.add((pattern, target))
						continue
					cachedBase = AssetCacher.getCachedAsset(DDSx, tex.tex)
					if cachedBase:
						baseBytes = max(cachedBase, key=lambda d: d.getPixelCnt()).getDDS()
					elif (qc.parent / "textures" / f"{key}.dds").is_file():
						baseBytes = (qc.parent / "textures" / f"{key}.dds").read_bytes()
					else:
						raise ValueError(f"Missing base texture {tex.tex} for camo_skin_tex")
					camoBytes = None
					if mat.mask:
						maskName = MaterialData.getTexFileName(mat.mask)
						maskMatch = next(
							((mp, mt) for mp, mt, mparam in skinRules if mparam != "camo_skin_tex" and fnmatchcase(maskName.lower(), mp)),
							None,
						)
						if maskMatch is not None:
							camoBytes = archive.read(maskMatch[1]) if archiveCtx is not None else _loadBuiltinTarget(gameRoot, maskMatch[1], maskName)
						else:
							cachedCamo = AssetCacher.getCachedAsset(DDSx, maskName)
							if cachedCamo:
								camoBytes = max(cachedCamo, key=lambda d: d.getPixelCnt()).getDDS()
					data = _compositeCamoSkinTex(baseBytes, skinImg, camoBytes, mat.tankCamoExponent() or 0.25)
					camoReplaced.add(f'{tex.texPath}/{key}')
				else:
					with Image.open(BytesIO(data)) as image:
						if image.width * image.height > 8192 * 8192:
							raise ValueError("UserSkin texture exceeds 8192x8192 pixel budget")
						if image.format != 'DDS':
							image.load()
							buf = BytesIO()
							image.save(buf, format='DDS')
							data = buf.getvalue()
					data, _ = mat.convertTex(tex.tex, data, texturePaths, texN=key)
				# Texture names from the model must not become paths supplied by the archive.
				outname = hashlib.sha256(key.encode()).hexdigest()[:16]
				dds = destination / (outname + '.dds')
				dds.write_bytes(data)
				fmt = vtfFormat if vtfFormat in ("DXT5", "RGBA8888") else "DXT5"
				vtfArgs = [str(converter), '-file', str(dds), '-output', str(destination), '-version', '7.2', '-format', fmt, '-alphaformat', fmt]
				if tex.texType == TEXTURE_NORMAL:
					vtfArgs += ['-flag', 'NORMAL']
				subprocess.run(vtfArgs, check=True)
				vtf = destination / (outname + '.vtf')
				if not vtf.is_file():
					raise ValueError(f"VTFCmd did not produce {vtf}")
				dds.unlink()
				mapping[f'{tex.texPath}/{key}'] = f'{cd[1]}/{namespace}/{outname}'
				used.add((pattern, target))
		row = {}
		for name, vmt in originals.items():
			new = vmt
			stripDetail = False
			for old, replacement in mapping.items():
				if '"' + old + '"' in new:
					new = new.replace('"' + old + '"', '"' + replacement + '"')
					if old in camoReplaced:
						stripDetail = True
			if stripDetail:
				new = "\n".join(line for line in new.splitlines() if not line.lstrip().lower().startswith("$detail"))
			if new != vmt:
				(base / namespace / (name + '.vmt')).write_text(new)
				row[name] = f'{namespace}/{name}'
				changed.add(name)
		if not row:
			raise ValueError(f"{skinName}: no replacements match this model's exported materials")
		rows.append(row)
		reports.append({'skin': index, 'name': skinName, 'blk': skinManifest, 'materials': sorted(row),
			'unused': [pattern for pattern, target, _ in skinRules if (pattern, target) not in used]})
	names = sorted(changed)
	families = [names] + [[row.get(n, n) for n in names] for row in rows]
	group = '\n$texturegroup "skinfamilies"\n{\n' + ''.join('\t{ ' + ' '.join('"' + n + '"' for n in row) + ' }\n' for row in families) + '}\n'
	qc.write_text(text + group)
	(qc.parent / 'source_export/skins.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
	return reports
