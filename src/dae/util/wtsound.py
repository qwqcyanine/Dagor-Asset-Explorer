"""Read War Thunder's FMOD Studio banks (<game>/sound) and render their events to wavs the way the game mixes them."""
import struct
import subprocess
import wave
from os import path
from tempfile import TemporaryDirectory

import numpy as np

from util.misc import LIB_FOLDER

SOURCE_RATE = 44100 # Source's wav player only handles 44.1k (and 22k/11k) correctly

def _chunks(d:bytes):
	"""RIFF chunk tree: {"/FEV /PROJ/EVTS/...": [(bodyStart, bodyEnd)]}"""
	out = {}

	def walk(o, end, p):
		while o + 8 <= end:
			cid = d[o:o + 4]
			size = struct.unpack_from("<I", d, o + 4)[0]

			if cid in (b"RIFF", b"LIST"):
				sub = f"{p}/{d[o + 8:o + 12].decode('latin1')}"
				out.setdefault(sub, []).append((o + 12, o + 8 + size))
				walk(o + 12, o + 8 + size, sub)
			else:
				out.setdefault(f"{p}/{cid.decode('latin1')}", []).append((o + 8, o + 8 + size))

			o += 8 + size + (size & 1)

	walk(0, len(d), "")

	return out

def _x16(d:bytes, o:int):
	v = struct.unpack_from("<H", d, o)[0]
	o += 2

	if v & 0x8000:
		v = (v & 0x7FFF) | (struct.unpack_from("<H", d, o)[0] << 15)
		o += 2

	return v, o

def readStrings(stringsBank:str):
	"""{event path: guid bytes} from the 24-bit radix tree in masterbank.strings.bank"""
	with open(stringsBank, "rb") as f:
		d = f.read()

	o = _chunks(d)["/FEV /PROJ/STDT"][0][0] + 4 # skip the table type
	n, o = _x16(d, o)
	n >>= 1
	nodes = struct.unpack_from(f"<{n * 2}I", d, o + 2)[::2]
	o += 2 + n * 8
	g, o = _x16(d, o)
	g >>= 1
	guids = [d[o + 2 + i * 16:o + 18 + i * 16] for i in range(g)]
	o += 2 + g * 16
	size, o = _x16(d, o)
	blob = d[o:o + size]
	o += size

	def arr24(o):
		k, o = _x16(d, o)
		return [int.from_bytes(d[o + i * 3:o + i * 3 + 3], "little") for i in range(k)], o + k * 3

	leaves, o = arr24(o)
	parents, o = arr24(o)
	out = {}

	for guid, node in zip(guids, leaves):
		segs = []

		while node != 0xFFFFFF:
			s = nodes[node] & 0xFFFFFF

			if s != 0xFFFFFF:
				segs.append(blob[s:blob.index(b"\0", s)].decode())

			node = parents[node]

		out["".join(reversed(segs))] = guid

	return out

def _fsbs(d:bytes):
	"""FSB5 blobs embedded in an .assets.bank: [(offset, total size)]"""
	out = []

	for a, _ in _chunks(d).get("/FEV /SND ", []):
		i = d.index(b"FSB5", a)
		shs, nts, ds = struct.unpack_from("<3I", d, i + 12)
		out.append((i, 0x3C + shs + nts + ds))

	return out

def _samples(d:bytes, fsb:int):
	"""Per sample of one FSB5: (name, header bytes, data bytes)"""
	ns, shs, nts, ds = struct.unpack_from("<4I", d, fsb + 8)
	o = fsb + 0x3C
	heads = []

	for _ in range(ns):
		start = o
		mode = struct.unpack_from("<Q", d, o)[0]
		o += 8
		more = mode & 1

		while more:
			c = struct.unpack_from("<I", d, o)[0]
			more = c & 1
			o += 4 + ((c >> 1) & 0xFFFFFF)

		heads.append((start, o, ((mode >> 7) & 0x7FFFFFF) * 32))

	nameBase = fsb + 0x3C + shs
	dataBase = nameBase + nts
	out = []

	for i, (a, b, ofs) in enumerate(heads):
		end = heads[i + 1][2] if i + 1 < ns else ds
		nameOfs = nameBase + struct.unpack_from("<I", d, nameBase + i * 4)[0] if nts else 0
		name = d[nameOfs:d.index(b"\0", nameOfs)].decode("utf-8", "replace") if nts else str(i)
		out.append((name, d[a:b], d[dataBase + ofs:dataBase + end]))

	return out

def buildFSB(template:bytes, samples:list):
	"""A new FSB5 holding `samples` [(name, header, data)], other header fields copied from `template`."""
	heads, names, data = bytearray(), bytearray(), bytearray()
	nameOfs = []

	for name, head, blob in samples:
		mode = struct.unpack_from("<Q", head)[0] & ~(0x7FFFFFF << 7) | ((len(data) // 32) << 7)
		heads += struct.pack("<Q", mode) + head[8:]
		data += blob + b"\0" * (-len(blob) % 32)
		nameOfs.append(len(names))
		names += name.encode() + b"\0"

	table = struct.pack(f"<{len(samples)}I", *(o + 4 * len(samples) for o in nameOfs)) + names
	table += b"\0" * (-len(table) % 16)

	return b"FSB5" + struct.pack("<5I", 1, len(samples), len(heads), len(table), len(data)) + template[24:0x3C] + heads + table + data

class _Reader:
	def __init__(self, d:bytes, o:int):
		self.d, self.o = d, o

	def take(self, fmt:str):
		v = struct.unpack_from(fmt, self.d, self.o)
		self.o += struct.calcsize(fmt)
		return v if len(v) > 1 else v[0]

	def guid(self):
		self.o += 16
		return self.d[self.o - 16:self.o]

	def x16(self):
		v, self.o = _x16(self.d, self.o)
		return v

	def elems(self, read = None):
		"""FMOD element list: x16 count*2, u16 element size, elements"""
		n = self.x16() >> 1

		if not n:
			return []

		size = self.take("<H")

		if read is None: # skip
			self.o += n * size
			return []

		return [read() for _ in range(n)]

	def skipVersionedElems(self):
		for _ in range(self.x16() >> 1):
			self.o += self.take("<H")

class Instrument:
	kind = "" # chunk body id: WAIB, MUIB, SPIB, EVIB, ...
	wave = None # waveform resource guid
	entries = () # playlist instrument guids
	sequential = False
	event = None # nested event guid
	spawnTime = (0.0, 0.0)
	volume = pitch = 0.0
	loop = 0
	autoPitchParam = None
	autoPitchRef = autoPitchMin = 0.0
	conditions = () # [(param guid, lo, hi)]
	bus = None

class Event:
	timeline = master = None
	layouts = tracks = ()

DSP_FADER = 7
FMOD_NO_DEFAULT = 1e30 # parameters without a default (distance, cone angle) report FLT_MAX

class SoundBank:
	"""One `<name>.bank` (event structure, format 0x8C-0x8F as shipped by War Thunder) plus its `<name>.assets.bank` (FSB5 sample data).
	Node layouts follow Masusder/FModBankParser (Apache-2.0)."""
	def __init__(self, soundDir:str, name:str):
		with open(path.join(soundDir, f"{name}.bank"), "rb") as f:
			d = f.read()

		c = _chunks(d)
		version = struct.unpack_from("<I", d, c["/FEV /FMT "][0][0])[0]

		if not 0x8C <= version <= 0x8F:
			raise ValueError(f"Unsupported FMOD bank version {version:#x} in {name}")

		self.events, self.params, self.layouts, self.timelines = {}, {}, {}, {}
		self.instruments, self.buses, self.curves, self.controllers = {}, {}, {}, {}
		self.controllerParam = {} # controller -> parameter guid of the layout owning it
		self.busEffects, self.faders = {}, {} # bus -> effect guids; fader effect -> gain (dB)

		for a, b in c.get("/FEV /PROJ/EVTS/EVNT/EVTB", []):
			r = _Reader(d, a)
			e = Event()
			guid = r.guid()
			r.guid() # snapshot
			e.timeline = r.guid()
			r.guid() # input bus
			e.master = r.guid()
			r.take("<iiBi")
			e.layouts = r.elems(r.guid)
			r.skipVersionedElems()
			r.skipVersionedElems()
			r.take("<fifI")
			e.tracks = r.elems(r.guid)
			self.events[guid] = e

		for a, b in c.get("/FEV /PROJ/PRMS/PARM/PRMB", []):
			r = _Reader(d, a)
			guid = r.guid()
			r.take("<iI") # flags, type
			n = r.x16()
			pname = d[r.o:r.o + n].decode("utf-8", "replace")
			r.o += n
			lo, hi, default = r.take("<fff")
			self.params[guid] = (pname, lo, hi, default if abs(default) < FMOD_NO_DEFAULT else lo)

		for (a, b), (ca, cb) in zip(c.get("/FEV /PROJ/PMLS/PMLO/PMLB", []), c.get("/FEV /PROJ/PMLS/PMLO/CTRO", [])):
			r = _Reader(d, a)
			guid, param = r.guid(), r.guid()
			self.layouts[guid] = (param, r.elems(r.guid))

			ctrls = _Reader(d, ca)

			for ctrl in ctrls.elems(ctrls.guid):
				self.controllerParam[ctrl] = param

		for a, b in c.get("/FEV /PROJ/TLNS/TMLN/TLNB", []):
			r = _Reader(d, a)
			guid = r.guid()
			box = lambda: (r.guid(), *r.take("<II"))
			self.timelines[guid] = r.elems(box) + r.elems(box)

		for a, b in c.get("/FEV /PROJ/CTRS/CTRL", []):
			r = _Reader(d, a)
			guid, owner, curve = r.guid(), r.guid(), r.guid()
			self.controllers.setdefault(owner, []).append((guid, curve, r.take("<i")))

		for a, b in c.get("/FEV /PROJ/CRVS/CURV", []):
			r = _Reader(d, a)
			guid = r.guid()
			r.guid()
			self.curves[guid] = r.elems(lambda: r.take("<fffI")[:2])

		for kind in ("GBS", "IBS", "MBS", "RBS"):
			for (a, _), (ba, _) in zip(c.get(f"/FEV /PROJ/{kind}S/{kind[:2]}US/{kind}B", []), c.get(f"/FEV /PROJ/{kind}S/{kind[:2]}US/BUS ", [])):
				r = _Reader(d, ba)
				r.take("<II")
				effects = r.elems(r.guid) + r.elems(r.guid) # pre and post fader
				r.take("<H")
				self.buses[d[a:a + 16]] = r.take("<f")

				if effects:
					self.busEffects[d[a:a + 16]] = effects

		for (a, _), (pa, _) in zip(c.get("/FEV /PROJ/BEFX/BEFF/BEFB", []), c.get("/FEV /PROJ/BEFX/BEFF/PMEF", [])):
			r = _Reader(d, a)
			guid = r.guid()

			if r.take("<I") == DSP_FADER and struct.unpack_from("<ii", d, pa) [1] in (0, 1): # first parameter is the gain
				self.faders[guid] = struct.unpack_from("<f", d, pa + 8)[0]

		for listId, bodyId in (("WAIS/WAIT", "WAIB"), ("MUIS/MUIT", "MUIB"), ("SPIS/SPIT", "SPIB"), ("EVIS/EVIT", "EVIB")):
			bodies = c.get(f"/FEV /PROJ/{listId}/{bodyId}", [])
			insts = c.get(f"/FEV /PROJ/{listId}/INST", [])
			playlists = c.get(f"/FEV /PROJ/{listId}/PLST", [None] * len(bodies))

			for (a, _), (ia, _), plst in zip(bodies, insts, playlists):
				r = _Reader(d, a)
				i = Instrument()
				i.kind = bodyId
				guid = r.guid()

				if bodyId == "WAIB":
					i.wave = r.guid()
				elif bodyId == "EVIB":
					i.event = r.guid()
				elif bodyId == "SPIB":
					r.take("<ii")
					i.spawnTime = r.take("<ff")

				if plst:
					p = _Reader(d, plst[0])
					i.sequential = p.take("<i") == 0 # PlaylistPlayMode_PlaySequential
					p.take("<i")
					i.entries = [g for g, _ in p.elems(lambda: (p.guid(), p.take("<f")))]

				self.__readBody(_Reader(d, ia), i)
				self.instruments[guid] = i

		with open(path.join(soundDir, f"{name}.assets.bank"), "rb") as f:
			self.assets = f.read()

		self.fsbs = _fsbs(self.assets)
		self.waves = {}

		for a, _ in _chunks(self.assets).get("/FEV /PROJ/WAVS/WAV ", []):
			bank, sub = struct.unpack_from("<ii", self.assets, a + 18)
			self.waves[self.assets[a:a + 16]] = (bank, sub)

		self.__samples = {}
		self.__pcm = {}

	@staticmethod
	def __readBody(r:_Reader, i:Instrument):
		r.guid() # timeline
		i.volume, i.pitch, i.loop = r.take("<ffi")
		r.take("<ifff") # flags, 3d offset, trigger chance, delay min
		r.take("<f") # delay max

		if r.take("<I") <= 2: # quantization unit up to eighth note carries a multiplier
			r.take("<i")

		i.autoPitchParam = r.guid()
		i.autoPitchRef = r.take("<f")
		r.take("<fi") # initial seek, max polyphony
		r.take("<H")
		i.bus = r.guid()
		r.take("<IIiIf") # channel layout/mask, polyphony behaviour, left trim, seek percent
		i.autoPitchMin = r.take("<f")
		end = r.o + 4 + r.take("<i")
		param, conds = None, []

		while r.o < end:
			t = r.take("<I") & 0xFF

			if t == 0x10:
				r.take("<I")
			elif t == 0x11:
				param = r.guid()
			elif t == 0x20:
				conds.append((param, *r.take("<ff")))

		i.conditions = conds

		if i.autoPitchParam == bytes(16):
			i.autoPitchParam = None

	def sample(self, ref):
		bank, sub = ref

		if bank not in self.__samples:
			self.__samples[bank] = _samples(self.assets, self.fsbs[bank][0])

		return self.__samples[bank][sub]

	def paramName(self, guid):
		return self.params.get(guid, ("",))[0]

	def walk(self, guid:bytes, seen = None):
		"""Every instrument reachable from an event or instrument"""
		seen = set() if seen is None else seen

		if guid in seen:
			return seen

		seen.add(guid)
		e = self.events.get(guid)

		if e:
			for l in e.layouts:
				for i in self.layouts.get(l, (None, ()))[1]:
					self.walk(i, seen)

			for box in self.timelines.get(e.timeline, ()):
				self.walk(box[0], seen)

		i = self.instruments.get(guid)

		if i:
			for g in (*i.entries, *([i.event] if i.event else [])):
				self.walk(g, seen)

		return seen

	def decode(self, guids):
		"""Decode the waveforms of these instruments (mono float, SOURCE_RATE) into the cache, one fsb_aud_extr run per FSB."""
		refs = {self.waves[i.wave] for g in guids if (i := self.instruments.get(g)) and i.wave in self.waves} - set(self.__pcm)
		byFsb = {}

		for ref in refs:
			byFsb.setdefault(ref[0], []).append(ref)

		for fsb, items in byFsb.items():
			with TemporaryDirectory() as tmp:
				start = self.fsbs[fsb][0]

				with open(path.join(tmp, "s.fsb"), "wb") as f:
					f.write(buildFSB(self.assets[start:start + 0x3C], [(f"s{k}", *self.sample(ref)[1:]) for k, ref in enumerate(items)]))

				subprocess.run([path.join(LIB_FOLDER, "fsb_aud_extr.exe"), "s.fsb"], cwd = tmp, check = True, capture_output = True, timeout = 300)

				for k, ref in enumerate(items):
					pcm, rate = readWav(path.join(tmp, f"s{k}.wav"))
					self.__pcm[ref] = resample(pcm.mean(axis = 1) / 32768, rate)

	def pcm(self, inst:Instrument):
		return self.__pcm.get(self.waves.get(inst.wave))

def resample(pcm:np.ndarray, rate:float, target:int = SOURCE_RATE):
	"""Mono float resample (also used for pitch: rate = target * pitch)"""
	if abs(rate - target) < 1e-6 or not len(pcm):
		return pcm

	n = max(int(len(pcm) * target / rate), 1)

	return np.interp(np.arange(n) * (rate / target), np.arange(len(pcm)), pcm).astype(np.float32)

def writeWav(file:str, pcm:np.ndarray, rate:int, loop:bool = False):
	"""16-bit wav; `loop` adds the cue point Source needs to loop it."""
	with wave.open(file, "wb") as w:
		w.setnchannels(pcm.shape[1])
		w.setsampwidth(2)
		w.setframerate(rate)
		w.writeframes(pcm.astype("<i2").tobytes())

	if loop:
		cue = b"cue " + struct.pack("<II", 28, 1) + struct.pack("<II4sIII", 0, 0, b"data", 0, 0, 0)

		with open(file, "r+b") as f:
			f.seek(0, 2)
			f.write(cue)
			size = f.tell()
			f.seek(4)
			f.write(struct.pack("<I", size - 8))

def readWav(file:str):
	with wave.open(file, "rb") as w:
		assert w.getsampwidth() == 2, file
		pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels())

		return pcm.astype(np.float32), w.getframerate()

def curveAt(points, x:float):
	xs = [p[0] for p in points]
	return float(np.interp(x, xs, [p[1] for p in points]))

def db(v:float):
	return 10 ** (v / 20)

# War Thunder engine parameters -> Glide engine stream inputs (rpm and speed both follow the wheels with Glide's single gear)
STREAM_INPUTS = {"rpm_result": "rpmFraction", "rpm": "rpmFraction", "speed": "rpmFraction", "load": "throttle"}

class Renderer:
	"""Evaluates War Thunder FMOD events at fixed parameter values. Parameters not given use their default (distance 0)."""
	def __init__(self, bank:SoundBank, params:dict = None, seed:int = 0, steadyLoops:bool = False):
		self.bank = bank
		self.params = params or {}
		self.rng = np.random.default_rng(seed)
		self.steadyLoops = steadyLoops

	def value(self, guid):
		name, lo, hi, default = self.bank.params.get(guid, ("", 0, 0, 0))
		return float(np.clip(self.params.get(name, default), lo, hi))

	def gain(self, owner, skip = ()):
		"""Linear gain of an instrument's volume automation (prop 4, a linear fade) at the current parameter values."""
		g = 1.0

		for ctrl, curve, prop in self.bank.controllers.get(owner, ()):
			param = self.bank.controllerParam.get(ctrl)

			if param not in skip and curve in self.bank.curves and prop == 4:
				g *= curveAt(self.bank.curves[curve], self.value(param))

		return g

	def level(self, owner, static:float, skip = ()):
		"""dB of a bus volume (prop 0) or fader gain (prop 1000). FMOD automation replaces the stored value, several curves add up."""
		auto = [(self.bank.controllerParam.get(c), curve) for c, curve, prop in self.bank.controllers.get(owner, ()) if prop in (0, 1000) and curve in self.bank.curves]

		if not auto:
			return static

		return sum(curveAt(self.bank.curves[curve], self.value(param)) for param, curve in auto if param not in skip)

	def busGain(self, bus, skip = ()):
		"""Linear gain of a bus: its fader plus its fader effects"""
		if bus is None:
			return 1.0

		v = self.level(bus, self.bank.buses.get(bus, 0.0), skip)
		v += sum(self.level(f, self.bank.faders[f], skip) for f in self.bank.busEffects.get(bus, ()) if f in self.bank.faders)

		return db(v)

	def active(self, i:Instrument):
		return all(lo <= self.value(p) <= hi for p, lo, hi in i.conditions if p)

	def autoPitch(self, i:Instrument, x:float = None):
		if not i.autoPitchParam or i.autoPitchParam not in self.bank.params:
			return 1.0

		lo = self.bank.params[i.autoPitchParam][1]
		x = self.value(i.autoPitchParam) if x is None else x

		return i.autoPitchMin + (1 - i.autoPitchMin) * (x - lo) / max(i.autoPitchRef - lo, 1e-6)

	def staticGain(self, i:Instrument, master = None, skip = ()):
		return db(i.volume) * self.busGain(i.bus, skip) * self.busGain(master, skip)

	def instrument(self, guid, length:float = None, variant:int = 0):
		"""Mono audio of one instrument; `length` (s) tiles loops / fills scatterers."""
		i = self.bank.instruments.get(guid)

		if i is None or (self.steadyLoops and i.kind != "EVIB" and i.loop >= 0):
			return np.zeros(0, np.float32)

		if i.kind == "WAIB":
			pcm = self.bank.pcm(i)

			if pcm is None:
				return np.zeros(0, np.float32)

			pcm = resample(pcm, SOURCE_RATE * self.autoPitch(i) * 2 ** (i.pitch / 12))

			if length and i.loop < 0 and len(pcm):
				pcm = np.resize(pcm, int(length * SOURCE_RATE))

			return pcm

		if i.kind == "EVIB":
			return self.event(i.event, length, variant) if i.event in self.bank.events else np.zeros(0, np.float32)

		if not i.entries:
			return np.zeros(0, np.float32)

		if i.kind == "SPIB":
			out = Mix(length or 4.0, loop = bool(length))
			t = float(self.rng.uniform(0, i.spawnTime[0]))

			while t < out.length:
				out.add(self.instrument(i.entries[0], None, int(self.rng.integers(1 << 16))), t)
				t += float(self.rng.uniform(*i.spawnTime)) or out.length

			return out.pcm

		# a sequential playlist starts with a "first shot" and then repeats the rest: use the steady state
		entry = i.entries[-1] if i.sequential else i.entries[variant % len(i.entries)]

		return self.instrument(entry, length if i.loop < 0 else None, variant)

	def event(self, guid, length:float = None, variant:int = 0):
		"""Mix of an event's timeline and of the parameter sheet instruments active at the current values."""
		e = self.bank.events[guid]
		starts = {}

		for inst, start, _ in self.bank.timelines.get(e.timeline, ()):
			starts.setdefault(inst, start / 48000) # timeline positions are 48 kHz samples

		for l in e.layouts:
			for inst in self.bank.layouts.get(l, (None, ()))[1]:
				starts.setdefault(inst, 0.0)

		parts = []

		for inst, start in starts.items():
			i = self.bank.instruments.get(inst)

			if i and self.active(i):
				pcm = self.instrument(inst, length, variant)
				parts.append((pcm * self.staticGain(i, e.master) * self.gain(inst), start))

		out = Mix(length or max((len(p) / SOURCE_RATE + s for p, s in parts), default = 0), loop = bool(length))

		for pcm, start in parts:
			out.add(pcm, start)

		return out.pcm

class Mix:
	def __init__(self, length:float, loop:bool = False):
		self.length = length
		self.loop = loop
		self.pcm = np.zeros(max(int(length * SOURCE_RATE), 1), np.float32)

	def add(self, pcm:np.ndarray, start:float):
		o = int(start * SOURCE_RATE)

		if self.loop: # wrap around so the loop stays seamless
			idx = (o + np.arange(len(pcm))) % len(self.pcm)
			np.add.at(self.pcm, idx, pcm)
		else:
			n = min(len(pcm), len(self.pcm) - o)

			if n > 0:
				self.pcm[o:o + n] += pcm[:n]

def finish(pcm:np.ndarray, maxSeconds:float = None):
	"""Clip-safe int16 with a short fade when cut."""
	if maxSeconds and len(pcm) > maxSeconds * SOURCE_RATE:
		pcm = pcm[:int(maxSeconds * SOURCE_RATE)].copy()
		fade = min(len(pcm), SOURCE_RATE // 2)
		pcm[-fade:] *= np.linspace(1, 0, fade)

	peak = float(np.abs(pcm).max()) if len(pcm) else 0.0

	if peak > 0.98:
		pcm = pcm * (0.98 / peak)

	return (pcm * 32767).astype(np.int16).reshape(-1, 1)

def subEvent(bank:SoundBank, eventGuid:bytes, paramName:str):
	"""Nested event an event plays only while `paramName` is raised (e.g. the hand-crank turret sound on `no_power`), or None"""
	e = bank.events[eventGuid]

	for l in e.layouts:
		for g in bank.layouts.get(l, (None, ()))[1]:
			i = bank.instruments.get(g)

			if i and i.kind == "EVIB" and i.event in bank.events and any(bank.paramName(p) == paramName and lo > 0 for p, lo, _ in i.conditions):
				return i.event

	return None

def segmentControllers(points, inLo:float, inHi:float, output:str, linear = lambda y: y):
	"""Glide multiplies clamped linear controllers: a curve becomes one controller per segment,
	each scaling from the previous point's value to its own (telescoping product)."""
	ys = [max(linear(y), 1e-4) for _, y in points]
	out = []

	for k in range(len(points) - 1):
		x0, x1 = points[k][0], points[k + 1][0]

		if x1 <= x0:
			continue

		a = (x0 - inLo) / (inHi - inLo)
		b = (x1 - inLo) / (inHi - inLo)
		start = ys[k] if k == 0 else 1.0
		out.append((a, b, output, start, ys[k + 1] / (1.0 if k == 0 else ys[k])))

	return out

def engineLayers(bank:SoundBank, eventGuid:bytes):
	"""Glide engine stream layers for a WT engine event: [(instrument guid, [(input, inLo, inHi, output, outLo, outHi)])].
	Instruments on parameters Glide can't drive are evaluated at the parameter default."""
	r = Renderer(bank)
	e = bank.events[eventGuid]
	layers = []

	def mapped(param):
		name, lo, hi, _ = bank.params.get(param, ("", 0, 1, 0))
		inp = "rpmFraction" if name.startswith("rpm_result_") else STREAM_INPUTS.get(name)
		return (inp, lo, hi) if inp else None

	for l in e.layouts:
		for g in bank.layouts.get(l, (None, ()))[1]:
			i = bank.instruments[g]

			while i.kind == "MUIB" and i.entries: # a one-entry multi around a loop
				g, i = i.entries[0], bank.instruments[i.entries[0]]

			if i.kind != "WAIB" or i.wave not in bank.waves:
				continue

			ctrl = []
			drivenParams = set()

			for param, lo, hi in i.conditions:
				m = mapped(param)

				if not m:
					if not lo <= r.value(param) <= hi:
						break
					continue

				inp, plo, phi = m
				drivenParams.add(param)
				eps = (phi - plo) * 0.01

				if lo > plo: # instruments are silent outside their range
					ctrl.append((inp, (lo - eps - plo) / (phi - plo), (lo - plo) / (phi - plo), "volume", 0, 1))

				if hi < phi:
					ctrl.append((inp, (hi - plo) / (phi - plo), (hi + eps - plo) / (phi - plo), "volume", 1, 0))
			else:
				owners = [(g, (4,)), (i.bus, (0,)), (e.master, (0,))]
				owners += [(f, (1000,)) for bus in (i.bus, e.master) for f in bank.busEffects.get(bus, ()) if f in bank.faders]

				for owner, props in owners:
					for c, curve, prop in bank.controllers.get(owner, ()):
						param = bank.controllerParam.get(c)
						m = mapped(param)

						if m and prop in props and curve in bank.curves:
							drivenParams.add(param)
							ctrl += [(m[0], *s[:2], *s[2:]) for s in segmentControllers(bank.curves[curve], m[1], m[2], "volume", (lambda y: y) if prop == 4 else db)]

				gain = r.staticGain(i, e.master, drivenParams) * r.gain(g, drivenParams)
				m = mapped(i.autoPitchParam)
				pitch = 2 ** (i.pitch / 12)

				if m:
					ctrl.append((m[0], 0, 1, "pitch", r.autoPitch(i, m[1]) * pitch, r.autoPitch(i, m[2]) * pitch))
				else:
					pitch *= r.autoPitch(i)

				if not m and abs(pitch - 1) > 1e-3:
					ctrl.append(("throttle", 0, 1, "pitch", pitch, pitch))

				layers.append((g, ctrl, gain))

	top = max((gain for _, _, gain in layers), default = 1.0)

	return [(g, ctrl + [("throttle", 0, 1, "volume", gain / top, gain / top)]) for g, ctrl, gain in layers if gain / top > 0.01]
