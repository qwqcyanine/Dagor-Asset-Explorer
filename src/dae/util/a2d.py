"""Dagor a2d animations (AnimV20 0x300: ACL 2.1 compressed qvvf tracks), sampled with lib/acl_sample.dll (src/acl_sample)."""
from ctypes import c_float, byref, create_string_buffer
from struct import unpack_from
from util.misc import loadDLL

CHTYPE_ROTATION = 5 # the position/scale channels share its ACL tracks

_dll = loadDLL("acl_sample.dll")

class A2D:
	"""`data` is the decompressed a2d: 'ANIM' header, the dump (ACL tracks, names), then the DumpData tables pointing into the dump."""
	def __init__(self, data:bytes):
		label, ver, hdrSize, dumpSize = unpack_from("<4sIII", data)

		if label != b"ANIM" or ver not in (0x300, 0x301):
			raise ValueError(f"not an a2d: {label} {hex(ver)}")

		dump = data[hdrSize:hdrSize + dumpSize]
		tables = data[hdrSize + dumpSize:]
		# PatchableTab: offset into the dump, count, 8 reserved bytes; order: point3, quat, real, note channels
		ofs, cnt, _ = unpack_from("<IIQ", tables, 16)
		cstr = lambda o: dump[o:dump.index(b"\0", o)].decode("ascii", "replace")

		for i in range(cnt):
			tracks, nodeTrack, nodeNum, chType, _, nodeName = unpack_from("<QQIIQQ", dump, ofs + 40 * i)

			if chType == CHTYPE_ROTATION:
				break
		else:
			raise ValueError("a2d without a rotation channel")

		self.names = [cstr(unpack_from("<Q", dump, nodeName + 8 * j)[0]) for j in range(nodeNum)]
		self.tracks = unpack_from(f"<{nodeNum}H", dump, nodeTrack)
		self.__acl = create_string_buffer(dump[tracks:], len(dump) - tracks)
		duration = c_float()
		self.trackCount = _dll.acl_info(self.__acl, byref(duration)) if _dll else -1

		if self.trackCount < 0:
			raise ValueError("ACL tracks unreadable (lib/acl_sample.dll missing?)")

		self.duration = duration.value

	@classmethod
	def fromPack(cls, grpPath:str, name:str):
		"""The Anim2Data asset `name` of a grp, or None"""
		from parse.gameres import GameResourcePack
		from util.decompression import CompressedData
		from util.fileread import BinFile

		asset = next((a for a in GameResourcePack(grpPath).getPackedFiles() if a.name == name), None)

		if asset is None:
			return None

		return cls(CompressedData(BinFile(asset.getBin().read(asset.size))).decompress())

	def sample(self, time:float):
		"""{node name: (quat xyzw, translation xyz, scale xyz)} local transforms at `time` seconds (clamped)"""
		out = (c_float * (self.trackCount * 10))()
		_dll.acl_sample(self.__acl, c_float(time), out)

		return {n: tuple(out[t * 10:t * 10 + 10]) for n, t in zip(self.names, self.tracks)}
