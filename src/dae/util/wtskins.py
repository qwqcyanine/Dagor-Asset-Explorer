"""Import WT UserSkins replace_tex ZIPs as Source $texturegroup families."""
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from io import BytesIO
import hashlib
import json
import re
import subprocess
import zipfile

from PIL import Image
from parse.material import MaterialData


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


def importSkins(qc, materials, texturePaths, archives, converter, modelName=None):
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
	rows, changed, reports = [], set(), []
	for index, filename in enumerate(archives, 1):
		skin = SkinArchive(filename, modelName or qc.stem)
		with skin.path.open('rb') as stream:
			digest = hashlib.file_digest(stream, 'sha256').hexdigest()[:12]
		namespace = f'skins/{index}_{digest}'
		destination = base / namespace
		destination.mkdir(parents=True, exist_ok=True)
		mapping, used = {}, set()
		with zipfile.ZipFile(skin.path) as archive:
			for key, tex in texturePaths.getDict().items():
				matches = [(pattern, target) for pattern, target in skin.rules if fnmatchcase(tex.tex.lower(), pattern)]
				if not matches:
					continue
				if len(matches) != 1:
					raise ValueError(f"Ambiguous UserSkin replacement for {tex.tex}")
				pattern, target = matches[0]
				data = archive.read(target)
				with Image.open(BytesIO(data)) as image:
					if image.width * image.height > 8192 * 8192:
						raise ValueError("UserSkin texture exceeds 8192x8192 pixel budget")
					if image.format != 'DDS':
						image.load()
						buf = BytesIO()
						image.save(buf, format='DDS')
						data = buf.getvalue()
				data, _ = MaterialData().convertTex(tex.tex, data, texturePaths, texN=key)
				# Texture names from the model must not become paths supplied by the archive.
				outname = hashlib.sha256(key.encode()).hexdigest()[:16]
				dds = destination / (outname + '.dds')
				dds.write_bytes(data)
				subprocess.run([str(converter), '-file', str(dds), '-output', str(destination), '-version', '7.2'], check=True)
				vtf = destination / (outname + '.vtf')
				if not vtf.is_file():
					raise ValueError(f"VTFCmd did not produce {vtf}")
				dds.unlink()
				mapping[f'{tex.texPath}/{key}'] = f'{cd[1]}/{namespace}/{outname}'
				used.add((pattern, target))
		row = {}
		for name, vmt in originals.items():
			new = vmt
			for old, replacement in mapping.items():
				new = new.replace('"' + old + '"', '"' + replacement + '"')
			if new != vmt:
				(base / namespace / (name + '.vmt')).write_text(new)
				row[name] = f'{namespace}/{name}'
				changed.add(name)
		if not row:
			raise ValueError(f"{skin.name}: no replacements match this model's exported materials")
		rows.append(row)
		reports.append({'skin': index, 'name': skin.name, 'blk': skin.manifest, 'materials': sorted(row),
			'unused': [pattern for pattern, target in skin.rules if (pattern, target) not in used]})
	names = sorted(changed)
	families = [names] + [[row.get(n, n) for n in names] for row in rows]
	group = '\n$texturegroup "skinfamilies"\n{\n' + ''.join('\t{ ' + ' '.join('"' + n + '"' for n in row) + ' }\n' for row in families) + '}\n'
	qc.write_text(text + group)
	(qc.parent / 'source_export/skins.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
	return reports
