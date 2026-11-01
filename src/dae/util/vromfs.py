"""Read War Thunder *.vromfs.bin archives and binary .blk files (no external tools)."""
from struct import unpack_from

import zstandard

_KEY1 = (0xAA55AA55, 0xF00FF00F, 0xAA55AA55, 0x12481248)
_KEY2 = (0x12481248, 0xAA55AA55, 0xF00FF00F, 0xAA55AA55)


def _xor16(data:bytes, key):
	return b"".join((int.from_bytes(data[i * 4:i * 4 + 4], "little") ^ k).to_bytes(4, "little") for i, k in enumerate(key))


def _deobfuscate(data:bytes):
	size = len(data)

	if size < 16:
		return data

	out = bytearray(data)
	out[:16] = _xor16(data[:16], _KEY1)

	if size >= 32:
		ofs = 16 + (size - 32) // 4 * 4
		out[ofs:ofs + 16] = _xor16(data[ofs:ofs + 16], _KEY2)

	return bytes(out)


def _uleb(data:bytes, ofs:int):
	result = shift = 0

	while True:
		b = data[ofs]
		ofs += 1
		result |= (b & 0x7F) << shift

		if b < 0x80:
			return result, ofs

		shift += 7


class VROMFS:
	def __init__(self, path:str):
		with open(path, "rb") as f:
			raw = f.read()

		magic = raw[:4]

		if magic not in (b"VRFs", b"VRFx"):
			raise ValueError(f"{path}: not a vromfs file")

		origSize, packed = unpack_from("<II", raw, 8)
		packType, packedSize = packed >> 26, packed & 0x3FFFFFF
		ofs = 16

		if magic == b"VRFx":
			ofs += unpack_from("<H", raw, ofs)[0]

		if packedSize == 0:
			body = raw[ofs:ofs + origSize]
		elif packType in (0x10, 0x30):
			body = zstandard.ZstdDecompressor().decompress(_deobfuscate(raw[ofs:ofs + packedSize]), max_output_size = origSize)
		else:
			raise ValueError(f"{path}: unsupported vromfs packing {hex(packType)}")

		namesOfs, count = unpack_from("<II", body, 0)
		dataOfs = unpack_from("<I", body, 0x10)[0]

		self.files:dict[str, tuple[int, int]] = {}

		for i in range(count):
			nOfs = unpack_from("<I", body, namesOfs + i * 8)[0]
			name = body[nOfs:body.index(b"\x00", nOfs)]

			if name.startswith(b"\xff?"):
				name = name[2:]

			fOfs, fSize = unpack_from("<II", body, dataOfs + i * 16)
			self.files[name.decode("utf-8").lower()] = (fOfs, fSize)

		self.body = body
		self.__names = None
		self.__dict = None

	def read(self, name:str) -> bytes:
		ofs, size = self.files[name.lower()]

		return self.body[ofs:ofs + size]

	def __sharedNames(self):
		if self.__names is None:
			nm = self.read("nm")
			dictName = nm[8:40].hex() + ".dict"
			names = self.__decompress(nm[40:], dictName if dictName in self.files else None)
			count, ofs = _uleb(names, 0)
			_, ofs = _uleb(names, ofs)
			self.__names = names[ofs:].decode("utf-8", "replace").split("\x00")[:count]

		return self.__names

	def __decompress(self, data:bytes, dictName:str = None):
		if dictName:
			if self.__dict is None:
				self.__dict = zstandard.ZstdCompressionDict(self.read(dictName))

			dctx = zstandard.ZstdDecompressor(dict_data = self.__dict)
		else:
			dctx = zstandard.ZstdDecompressor()

		return dctx.stream_reader(data).read()

	def readBlk(self, name:str):
		data = self.read(name)
		kind = data[0]

		if kind == 1:
			return parseBlk(data[1:], None)
		elif kind == 2:
			size = int.from_bytes(data[1:4], "little")
			return parseBlk(self.__decompress(data[4:4 + size])[1:], None)
		elif kind == 3:
			return parseBlk(data[1:], self.__sharedNames())
		elif kind in (4, 5):
			dictName = next((n for n in self.files if n.endswith(".dict")), None) if kind == 5 else None
			return parseBlk(self.__decompress(data[1:], dictName), self.__sharedNames())

		raise ValueError(f"{name}: unsupported blk type {kind}")


def parseBlk(data:bytes, sharedNames:list[str] = None) -> dict:
	"""Returns nested dicts; repeated keys become lists."""
	ofs = 0
	namesCount, ofs = _uleb(data, ofs)

	if sharedNames is None:
		namesSize, ofs = _uleb(data, ofs)
		names = data[ofs:ofs + namesSize].decode("utf-8", "replace").split("\x00")[:namesCount]
		ofs += namesSize
	else:
		names = sharedNames

	blocksCount, ofs = _uleb(data, ofs)
	paramsCount, ofs = _uleb(data, ofs)
	dataSize, ofs = _uleb(data, ofs)
	pData = data[ofs:ofs + dataSize]
	ofs += dataSize
	pInfo = data[ofs:ofs + paramsCount * 8]
	ofs += paramsCount * 8

	def cstr(buf:bytes, o:int):
		return buf[o:buf.index(b"\x00", o)].decode("utf-8", "replace")

	def param(i:int):
		flags, raw = unpack_from("<II", pInfo, i * 8)
		name, kind = names[flags & 0xFFFFFF], flags >> 24
		rawB = pInfo[i * 8 + 4:i * 8 + 8]

		if kind == 1:
			val = names[raw & 0x7FFFFFFF] if raw & 0x80000000 else cstr(pData, raw)
		elif kind == 2:
			val = unpack_from("<i", rawB)[0]
		elif kind == 3:
			val = unpack_from("<f", rawB)[0]
		elif kind == 4:
			val = unpack_from("<2f", pData, raw)
		elif kind == 5:
			val = unpack_from("<3f", pData, raw)
		elif kind == 6:
			val = unpack_from("<4f", pData, raw)
		elif kind == 7:
			val = unpack_from("<2i", pData, raw)
		elif kind == 8:
			val = unpack_from("<3i", pData, raw)
		elif kind == 9:
			val = raw != 0
		elif kind == 0xA:
			val = tuple(rawB)
		elif kind == 0xB:
			val = unpack_from("<12f", pData, raw)
		elif kind == 0xC:
			val = unpack_from("<q", pData, raw)[0]
		else:
			val = raw

		return name, val

	blocks = []
	pIdx = 0

	for i in range(blocksCount):
		nameId, ofs = _uleb(data, ofs)
		pCnt, ofs = _uleb(data, ofs)
		bCnt, ofs = _uleb(data, ofs)
		first = 0

		if bCnt:
			first, ofs = _uleb(data, ofs)

		blocks.append((names[nameId - 1] if nameId else None, range(pIdx, pIdx + pCnt), first, bCnt))
		pIdx += pCnt

	def add(d:dict, key, val):
		if key in d:
			if not isinstance(d[key], list) or not getattr(d[key], "_multi", False):
				d[key] = _Multi([d[key]])
			d[key].append(val)
		else:
			d[key] = val

	def build(bi:int):
		_, params, first, bCnt = blocks[bi]
		d = {}

		for p in params:
			add(d, *param(p))

		for c in range(first, first + bCnt):
			add(d, blocks[c][0], build(c))

		return d

	return build(0) if blocks else {}


class _Multi(list):
	_multi = True


def blkList(val) -> list:
	"""Normalize a blk value that may appear once or many times into a list."""
	if val is None:
		return []

	return list(val) if isinstance(val, _Multi) else [val]
