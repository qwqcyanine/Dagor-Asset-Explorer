"""Run with: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "dae"))
from parse.realres import Model, SMD, bindNode
from util.glide import TRACK_R_SUFFIX, defaultOptions, gearbox, generateLua, glideCollisionNodes, splitTrackMaterials


def track(mdl:Model, name:str, mat:str, vPerMeter:float):
    # ground run (y=0) and top run (y=1) quads along x, u across the width
    obj = mdl.newObject(name)
    base = mdl.vertCnt
    verts, uvs = [], []
    for y in (0.0, 1.0):
        for x in (0.0, 1.0):
            for z, u in ((0.0, 0.0), (0.2, 1.0)):
                verts.append((x, y, z))
                uvs.append((u, x * vPerMeter * (1 if y == 0 else -1)))
    mdl.appendVerts(verts, uvs, scale = False)
    obj.appendMaterial(mat)
    for q in (0, 4):
        a, b, c, d = (base + q + i for i in range(4))
        obj.appendFace((a, c, b))
        obj.appendFace((b, c, d))


class GlideTest(unittest.TestCase):
    def test_collision_prefers_cls_and_drops_gun(self):
        self.assertEqual(glideCollisionNodes(["cls_body", "cls_gun", "cls_turret", "body_dm", "gun_barrel_dm"]), {"cls_body", "cls_turret"})
        self.assertEqual(glideCollisionNodes(["hull", "gun_barrel"]), {"hull"})

    def test_right_track_gets_own_material_and_scroll_rate(self):
        mdl = Model("tank")
        track(mdl, "track_l", "track_mat", 2.0)
        track(mdl, "track_r", "track_mat", -2.0)
        tracks = splitTrackMaterials(mdl)

        self.assertEqual(tracks["l"][0], ["track_mat"])
        self.assertEqual(tracks["r"][0], ["track_mat" + TRACK_R_SUFFIX])
        # getVertex scales meters to Source units (x40)
        self.assertAlmostEqual(tracks["l"][1], 2.0 / 40)
        self.assertAlmostEqual(tracks["r"][1], -2.0 / 40)

    def test_default_options_from_blk(self):
        blk = {"mass": 50000.0, "maxFwdSpeed": 75.0, "maxRevSpeed": 10.0,
            "VehiclePhys": {"Mass": {"TakeOff": 46000.0}, "mechanics": {"steerType": "differential"}}}
        self.assertEqual(defaultOptions(blk), {"singleFlow": False, "mass": 46000.0, "maxFwdSpeed": 75.0, "maxRevSpeed": 10.0, "upgraded": True})
        self.assertTrue(defaultOptions(None)["singleFlow"])

    def test_wheels_lifted_by_suspension_travel(self):
        class Node:
            def __init__(self, name, x, y, z):
                self.name, self.children = name, []
                self.wtm = [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z]]
        class Skeleton:
            nodes = [Node(f"bone_wheel_{s}_0{i}", x, 0.4, z) for s, z in (("l", 1.4), ("r", -1.4)) for i, x in enumerate((2, 0, -2))]
            def getNodeByName(self, name): return None
            def getNodes(self): return self.nodes
        lua = generateLua("wt_x", "x", "models/wt_glide/x.mdl", Skeleton(), None, options = {"mass": 40000, "singleFlow": False})
        # wheels at 16 units: mounts sit the bump travel (10) higher; springs carry the weight with 2 units of sag
        self.assertIn("CreateWheel( Vector( 80.0, 56.0, 26.0 )", lua)
        self.assertIn("SetSpringStrength( 30000 )", lua) # 40000 kg * 9 / (6 wheels * 2 units)
        self.assertIn("ENT.WTSingleFlow = false", lua)

    def test_lua_lists_track_materials(self):
        class Skeleton:
            def getNodeByName(self, name): return None
            def getNodes(self): return []
        lua = generateLua("wt_x", "x", "models/wt_glide/x.mdl", Skeleton(), None, {"l": (["m"], 0.05), "r": (["m_r"], 0.05)})
        self.assertIn("GetSpawnColor", lua)
        # no wheels in this skeleton, so no track entries can be bound to a wheel
        self.assertNotIn('"models/wt_glide/x/m"', lua)

    def test_gearbox_from_blk(self):
        blk = {"VehiclePhys": {"engine": {"horsePowers": 1250.0, "maxRPM": 3000.0, "minRPM": 1500.0},
            "mechanics": {"gearRatios": {"ratio": [-6.36, 0.0, 4.38, 3.5, 1.0]}}}}
        gears, rev, force, rise = gearbox(blk, {"maxFwdSpeed": 75.0, "maxRevSpeed": 10.0})
        self.assertEqual(gears, [4.38, 3.5, 1.0])
        self.assertAlmostEqual(rev, 7.5)
        self.assertAlmostEqual(force, 1250 * 745.7 / (75 / 3.6)) # rated power at top speed
        self.assertEqual(rise, 2.0) # constant power from 3000 down to 1500 rpm
        self.assertEqual(gearbox(None, {"maxFwdSpeed": 60.0, "maxRevSpeed": 15.0}), ([3.0], 12.0, None, 1.0))

    def test_bind_node_from_inverse_bind_matrix(self):
        class Node:
            def __init__(self, name, pos, parent = None):
                self.name, self.parent = name, parent
                self.wtm = [[1, 0, 0, pos[0]], [0, 1, 0, pos[1]], [0, 0, 1, pos[2]], [0, 0, 0, 1]]
        bone = Node("bone_wheel_l_01", (2.17, 0.4, 1.4))
        nodes = (Node("", (0, 0, 0)), bone, Node("wheel_l_01", (2.17, 0.4, 1.4), bone))
        # War Thunder's Y-up bones are axis-permuted: rows are the bone axes, then the translation
        rows = ((0, 0, 1), (0, 1, 0), (1, 0, 0))
        t = tuple(-sum(rows[k][j] * (2.17, 0.4, 1.4)[k] for k in range(3)) for j in range(3))

        self.assertIs(bindNode(nodes, (*rows, t)), bone) # the coincident child loses to its parent
        self.assertIs(bindNode(nodes, ((1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0))), nodes[0])

    def test_smd_writes_vertex_weights(self):
        smd = SMD("x", "x")
        tri = smd.newTriangle("m", ((0, 0, 0),) * 3, ((0, 0),) * 3)
        tri.links = (((1, 0.25), (3, 0.75)), None, ((2, 1.0),))
        lines = smd.getString().split("\n")

        self.assertTrue(lines[2].endswith(" 2 1 0.250000 3 0.750000"))
        self.assertEqual(len(lines[3].split()), 9)
        self.assertTrue(lines[4].endswith(" 1 2 1.000000"))


class WTSoundTest(unittest.TestCase):
    def test_sound_events_and_reload(self):
        from util.glide import soundEvents, cannonReload, firstWeapon
        blk = {
            "sound": {"EngineName": "engine_t80", "TrackSoundName": "tracks_mbt", "turret_turn": "turret_turn_servo"},
            "commonWeapons": {"Weapon": [
                {"weaponBlk": {"sound_pathStudio": "ground/weapon/cannons", "sound": "125mm_2a46", "shotFreq": 0.16666}},
                {"triggerGroup": "coaxial", "weaponBlk": {"sound_pathStudio": "ground/weapon/mguns", "sound": "8mm_pkt"}},
            ]},
        }
        ev = soundEvents(blk)

        self.assertEqual(ev["engine"], "event:/ground/engines/t80/engine")
        self.assertEqual(ev["tracks"], "event:/ground/engines/tracks_mbt")
        self.assertEqual(ev["cannon"], "event:/ground/weapon/cannons/125mm_2a46")
        self.assertEqual(ev["coaxial"], "event:/ground/weapon/mguns/8mm_pkt")
        self.assertNotIn("machinegun", ev)
        self.assertAlmostEqual(cannonReload(firstWeapon(blk)), 6.0, 2)

    def test_hidden_nodes_pick_one_armor_kit(self):
        from util.glide import hiddenNodes
        blk = {"modifications": {
            "kit": {"effects": {"hideNodes": {"node": ["stock_a", "stock_b"]}}, "disableModEffects": {"hideNodes": {"node": "mod_a"}}},
            "other": {"effects": {}},
        }}

        self.assertEqual(hiddenNodes(blk, True), {"stock_a", "stock_b"})
        self.assertEqual(hiddenNodes(blk, False), {"mod_a"})
        self.assertEqual(hiddenNodes(None), set())

    def test_curve_controllers_follow_curve(self):
        from util.wtsound import segmentControllers, curveAt
        points = [(0, 0.2), (20, 1.0), (60, 0.5), (100, 0.0)]
        ctrl = segmentControllers(points, 0, 100, "volume")

        def glide(x): # engine_stream.lua: clamp, remap, multiply outputs of one type
            v = 1.0
            for a, b, _, lo, hi in ctrl:
                v *= lo + (hi - lo) * (min(max(x, a), b) - a) / (b - a)
            return v

        for x, _ in points:
            self.assertAlmostEqual(glide(x / 100), max(curveAt(points, x), 1e-4), 3)

    def test_auto_pitch(self):
        from util.wtsound import Renderer, Instrument
        bank = type("B", (), {"params": {b"p": ("rpm_result", 0, 100, 0)}})()
        i = Instrument()
        i.autoPitchParam, i.autoPitchRef, i.autoPitchMin = b"p", 80, 0.9
        r = Renderer(bank)

        self.assertAlmostEqual(r.autoPitch(i, 0), 0.9)
        self.assertAlmostEqual(r.autoPitch(i, 80), 1.0)
        self.assertAlmostEqual(r.autoPitch(i, 40), 0.95)

    def test_bus_gain_automation_replaces_static_and_adds_faders(self):
        from util.wtsound import Renderer, db
        p = b"p"
        bank = type("B", (), {
            "params": {p: ("Distance", 0, 100, 0)},
            "buses": {b"auto": 6.0, b"plain": -3.0},
            "busEffects": {b"plain": [b"fader"]},
            "faders": {b"fader": -16.0},
            "controllers": {b"auto": [(b"c", b"curve", 0)]},
            "controllerParam": {b"c": p},
            "curves": {b"curve": [(0.0, 6.0), (100.0, -42.0)]},
        })()
        r = Renderer(bank)

        self.assertAlmostEqual(r.busGain(b"auto"), db(6.0)) # the stored 6 dB is the curve value, not extra gain
        self.assertAlmostEqual(r.busGain(b"auto", skip = {p}), 1.0) # driven by Glide controllers instead
        self.assertAlmostEqual(r.busGain(b"plain"), db(-19.0))

    def test_sub_event_on_parameter(self):
        from util.wtsound import subEvent, Instrument, Event
        manual = Instrument()
        manual.kind, manual.event, manual.conditions = "EVIB", b"manual", [(b"np", 0.05, 1.0)]
        servo = Instrument()
        servo.kind, servo.conditions = "WAIB", [(b"vel", 0.2, 12.0)]
        turret = Event()
        turret.layouts = [b"l"]
        bank = type("B", (), {
            "events": {b"turret": turret, b"manual": Event()},
            "layouts": {b"l": (b"np", [b"servo", b"m"])},
            "instruments": {b"servo": servo, b"m": manual},
            "paramName": lambda self, g: {b"np": "no_power", b"vel": "velH"}.get(g, ""),
        })()

        self.assertEqual(subEvent(bank, b"turret", "no_power"), b"manual")
        self.assertIsNone(subEvent(bank, b"turret", "broken"))

    def test_manual_traverse_falls_back_without_game(self):
        from util.glide import manualTraverseSpeed, MANUAL_TRAVERSE
        self.assertEqual(manualTraverseSpeed("Z:/nowhere"), MANUAL_TRAVERSE)

    def test_build_fsb_rebases_sample_offsets(self):
        import struct
        from util.wtsound import buildFSB, _samples
        head = lambda: struct.pack("<Q", (12345 << 34) | (999 << 7) | 1) + struct.pack("<I", (8 << 1)) + b"x" * 8 # one 8 byte extra chunk
        fsb = buildFSB(b"FSB5" + b"\0" * 56, [("a", head(), b"A" * 40), ("b", head(), b"B" * 7)])
        out = _samples(fsb, 0)

        self.assertEqual([(n, d.rstrip(b"\0")) for n, _, d in out], [("a", b"A" * 40), ("b", b"B" * 7)])
        self.assertEqual(struct.unpack_from("<Q", out[1][1])[0] >> 34, 12345) # sample count kept
