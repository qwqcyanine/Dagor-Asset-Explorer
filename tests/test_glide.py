"""Run with: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "dae"))
from parse.realres import Model, SMD, SourceModel, bindNode
from util.glide import GLIDE_KEEP_BONES, TRACK_R_SUFFIX, defaultOptions, gearbox, generateLua, glideCollisionNodes, splitTrackMaterials, tankMassCenter, tankSuspension, turretLimits


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
        self.assertEqual(defaultOptions(blk), {
            "singleFlow": False, "mass": 46000.0, "maxFwdSpeed": 75.0, "maxRevSpeed": 10.0,
            "suspensionSag": 12.5, "suspensionDamping": 50.0, "upgraded": True, "wheeled": False,
        })
        self.assertTrue(defaultOptions(None)["singleFlow"])
        self.assertFalse(defaultOptions({"VehiclePhys": {"mechanics": {"steerType": "clutch_braking", "neutralGearRatio": 2.1}}})["singleFlow"])
        self.assertTrue(defaultOptions({"VehiclePhys": {"mechanics": {"steerType": "clutch_braking"}}})["singleFlow"])

    def test_wheels_lifted_by_suspension_travel(self):
        class Node:
            def __init__(self, name, x, y, z):
                self.name, self.children, self.parent = name, [], None
                self.wtm = [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z]]
        class Skeleton:
            nodes = [Node(f"bone_wheel_{s}_0{i}", x, 0.4, z) for s, z in (("l", 1.4), ("r", -1.4)) for i, x in enumerate((2, 0, -2))]
            def getNodeByName(self, name): return None
            def getNodes(self): return self.nodes
        lua = generateLua("wt_x", "x", "models/wt_glide/x.mdl", Skeleton(), None, options = {"mass": 40000, "singleFlow": False})
        # wheels at 16 units: mounts sit the bump travel (9) higher; springs carry the weight with 5 units of sag
        self.assertIn("CreateWheel( Vector( 80.0, 56.0, 25.0 )", lua)
        self.assertIn("SetSuspensionLength( 14.0 )", lua)
        self.assertIn("SetSpringStrength( 12000 )", lua) # 40000 kg * 9 / (6 wheels * 5 units)
        self.assertIn("ENT.WTSingleFlow = false", lua)

    def test_wheeled_vehicle_steers_its_axles(self):
        class Node:
            def __init__(self, name, pos, parent = None):
                self.name, self.children, self.parent = name, [], parent
                self.wtm = [[1, 0, 0, pos[0]], [0, 1, 0, pos[1]], [0, 0, 1, pos[2]]]
                if parent: parent.children.append(self)
        nodes = []
        for s, z in ("l", 1.0), ("r", -1.0):
            for i, x, back in ((1, 2.0, ""), (3, -1.0, "back_")):
                susp = Node(f"bone_suspension_{s}_{back}{i:02d}", (x, 0.5, z * 0.5))
                wheel = Node(f"bone_wheel_{s}_{back}{i:02d}", (x, 0.6, z), susp)
                nodes += [susp, wheel, Node(f"wheel_{s}_{i:02d}", (x, 0.6, z * 1.2), wheel)]
        class Skeleton:
            def getNodeByName(self, name): return None
            def getNodes(self): return nodes
        blk = {"VehiclePhys": {"mechanics": {"tracked": False}, "suspension": {
            "steeringNodes": {"wheel_l_01": "bone_wheel_l_01", "wheel_r_01": "bone_wheel_r_01"},
            "steeringDeflection": {"wheel_l_01": 27.0, "wheel_r_01": 27.0, "steeringTau": 1e6}}}}
        lua = generateLua("wt_x", "x", "models/wt_glide/x.mdl", Skeleton(), blk)

        self.assertEqual(lua.count("steerMultiplier = 1.0 }"), 2)
        self.assertEqual(lua.count("steerMultiplier = 0.0 }"), 2) # the trailing-arm back wheels are found too
        self.assertIn("SetMaxSteerAngle( 27.0 )", lua)
        self.assertIn("ENT.CanTurnInPlace = false", lua)
        self.assertNotIn("surfaceResistance", lua) # tyres keep Glide's rolling resistance
        self.assertIn('{ spin = "wheel_l_01", steer = "bone_wheel_l_01", wheel = 1, angle = 27.0 }', lua)
        self.assertIn('{ spin = "wheel_r_03", steer = "bone_wheel_r_back_03", wheel = 4, angle = 0.0 }', lua)
        self.assertIn('{ bone = "bone_suspension_l_back_03", wheel = 2 }', lua)

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

    def test_skin_uses_native_ids_for_coincident_control_bones(self):
        from unittest.mock import patch
        from types import SimpleNamespace as NS
        from parse.realres import DynModel
        identity = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
        rotated = ((0, -1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
        fixed, moving = NS(idx=46, name='casing', wtm=identity), NS(idx=349, name='stick_ailerons', wtm=rotated)
        skeleton = NS(getNodes=lambda: [fixed, moving],
                      getNodeByName=lambda name: {'casing': fixed, 'stick_ailerons': moving}.get(name))
        dyn = NS(geomNodeTree=skeleton, _DynModel__skinNodes={57: 0, 59: 1},
                 _DynModel__nodeNames=['casing', 'stick_ailerons'])
        model = Model('skin')
        model.newObject('skin', skinned=True).faces = [(0, 1, 2)]
        model.appendVerts([(1, 0, 0)] * 3, [(0, 0)] * 3, scale=False)
        inverse_bind = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0))
        mesh = NS(boneOrgTms=[[inverse_bind, inverse_bind]], boneNodeIds=[[59, 57]])
        vertex_data = [(NS(getSkin=lambda: [((0, .75), (1, .25))] * 3), 0)]
        with patch('parse.realres.bindNode', side_effect=AssertionError('Must use native IDs')):
            DynModel._DynModel__applySkin(dyn, model, mesh, vertex_data)
        self.assertEqual(model.skin[0], ((349, .75), (46, .25)))
        self.assertEqual(len(model.skin), 3)
        for index in range(3):
            self.assertEqual(model.getVertex(index), (.25, .75, 0))

    def test_smd_writes_vertex_weights(self):
        smd = SMD("x", "x")
        tri = smd.newTriangle("m", ((0, 0, 0),) * 3, ((0, 0),) * 3)
        tri.links = (((1, 0.25), (3, 0.75)), None, ((2, 1.0),))
        lines = smd.getString().split("\n")

        self.assertTrue(lines[2].endswith(" 2 1 0.250000 3 0.750000"))
        self.assertEqual(len(lines[3].split()), 9)
        self.assertTrue(lines[4].endswith(" 1 2 1.000000"))

    def test_turret_limits_table_and_tilt_and_yaw_clamp(self):
        from math import sin, cos, radians
        blk = {"commonWeapons": {"Weapon": [{
            "limits": {"yaw": (-180.0, 180.0), "pitch": (-5.0, 13.0)},
            "limitsTable": {
                "lim1": (-180.0, -135.0, -1.5, 13.0),
                "lim2": [(-135.0, -120.0, -2.5, 13.0), (-120.0, 125.0, -5.0, 13.0)],
                "lim3": (125.0, 180.0, -1.5, 13.0),
            },
        }]}}
        _, _, _, _, table = turretLimits(blk["commonWeapons"]["Weapon"][0])
        self.assertEqual(len(table), 4)
        self.assertEqual(table[0], (-180.0, -135.0, -1.5, 13.0))

        rad = radians(1.66)
        class Node:
            def __init__(self, name):
                self.name, self.children, self.parent = name, [], None
                self.wtm = [[cos(rad), sin(rad), 0, 0], [-sin(rad), cos(rad), 0, 1.5], [0, 0, -1, 0]]
        nodes = [Node("bone_turret"), Node("bone_gun")]
        class Skeleton:
            def getNodeByName(self, name): return next((n for n in nodes if n.name == name), None)
            def getNodes(self): return nodes
        lua = generateLua("wt_x", "x", "models/wt_glide/x.mdl", Skeleton(), blk)
        self.assertIn("1.660 * math.cos( math.rad( wtYaw ) )", lua)
        self.assertIn("if wtYaw >= lim[1] and wtYaw <= lim[2] then", lua)
        self.assertIn("gunPitch[1] = turretAng[1] - 1.660 * math.cos( math.rad( turretAng[2] ) )", lua)
        self.assertIn("ang[2] = -( turretAng[1] - 1.660 * math.cos( math.rad( turretAng[2] ) ) )", lua)
        self.assertIn("BoneTurretAngles( turretAng[2] )", lua)
        self.assertIn("TurretAngles( turretAng[2] )", lua)
        self.assertIn("self:SetRenderBounds( mins, maxs )", lua)
        self.assertIn("self:MarkShadowAsDirty()", lua)

        casemate = {"commonWeapons": {"Weapon": [{"limits": {"yaw": (-3.0, 7.0), "pitch": (-3.0, 22.0)}}]}}
        lua_cm = generateLua("wt_cm", "cm", "models/wt_glide/cm.mdl", Skeleton(), casemate)
        self.assertIn("local yawMin, yawMax = -7.0, 3.0", lua_cm)

    def test_tracked_uses_middle_wheel_and_caps_forward_traction(self):
        class Node:
            def __init__(self, name, x, y, z):
                self.name, self.children, self.parent = name, [], None
                self.wtm = [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z]]
        for b in ("wheel_l_drive", "wheel_r_drive", "wheel_l_front", "wheel_r_front", "wheel_l_back", "wheel_l_top_01", "wheel_r_top_04"):
            self.assertIn(b, GLIDE_KEEP_BONES)
        nodes = [Node(f"bone_wheel_{s}_0{i}", x, 0.4, z) for s, z in (("l", 1.4), ("r", -1.4)) for i, x in enumerate((2, 0, -2))]
        nodes += [
            Node("wheel_l_drive", -2.5, 0.6, 1.4),
            Node("wheel_r_drive", -2.5, 0.6, -1.4),
            Node("wheel_l_front", 2.5, 0.6, 1.4),
            Node("wheel_l_top_01", 0.5, 0.8, 1.4),
        ]
        class Skeleton:
            def getNodeByName(self, name): return next((n for n in nodes if n.name == name), None)
            def getNodes(self): return nodes
        lua = generateLua("wt_x", "x", "models/wt_glide/x.mdl", Skeleton(), None,
                          {"l": (["m"], 0.05), "r": (["m_r"], 0.05)}, options = {"mass": 40000})
        # middle unsteered road wheels (2 and 5), not steered corner wheels (1 and 4)
        self.assertEqual(lua.count("self:CreateWheel("), 6)
        self.assertIn('{ wheel = 2, scale =', lua)
        self.assertIn('{ wheel = 5, scale =', lua)
        self.assertIn('{ spin = "bone_wheel_l_01", steer = "bone_wheel_l_01", wheel = 2, angle = 0.0 }', lua)
        self.assertIn('{ spin = "bone_wheel_r_01", steer = "bone_wheel_r_01", wheel = 5, angle = 0.0 }', lua)
        self.assertIn('{ spin = "wheel_l_drive", steer = "", wheel = 2, angle = 0.0 }', lua)
        self.assertIn('{ spin = "wheel_l_front", steer = "", wheel = 2, angle = 0.0 }', lua)
        self.assertIn('{ spin = "wheel_l_top_01", steer = "", wheel = 2, angle = 0.0 }', lua)
        self.assertIn('{ spin = "wheel_r_drive", steer = "", wheel = 5, angle = 0.0 }', lua)
        wheeled_lua = generateLua("wt_w", "w", "models/wt_glide/w.mdl", Skeleton(), {"VehiclePhys": {"mechanics": {"tracked": False}}})
        self.assertNotIn("wheel_l_drive", wheeled_lua)
        # 40000 kg -> massScale 2.0, 6 wheels -> perWheel 1.0 -> 16000 * 2.0 * 1.0 = 32000 (~0.53g)
        self.assertIn("SetForwardTractionMax( 32000 )", lua)
        self.assertIn("if w:GetRPM() < -maxRPM then w:SetRPM( -maxRPM ) end", lua)
        self.assertIn("w.state.traceData.mins = Vector( -s, -s, 0 )", lua)
        self.assertIn("function ENT:EngineThink( dt, selfTbl )", lua)
        self.assertIn("function ENT:UpdateSteering( dt, selfTbl )", lua)

        six = [Node(f"bone_wheel_{s}_{i:02d}", x, 0.4, z) for s, z in (("l", 1.4), ("r", -1.4)) for i, x in enumerate((3, 2, 1, 0, -1, -2), 1)]
        six_lua = generateLua("wt_x6", "x6", "models/wt_glide/x6.mdl",
            type("S", (), {"getNodeByName": lambda self, n: None, "getNodes": lambda self: six})(),
            {"VehiclePhys": {"mechanics": {"neutralGearRatio": 7.5, "gearRatios": {"ratio": [-6.0, 0.0, 7.5, 0.8]}}}})
        self.assertEqual(six_lua.count("steerMultiplier = 0.5 } ):SetSoundsEnabled( false )"), 2)
        self.assertEqual(six_lua.count("steerMultiplier = -0.5 } ):SetSoundsEnabled( false )"), 2)
        # 6-wheel sides pick the unsteered middle wheel (index 3 -> wheels 4 and 10), not i=1 (steerMultiplier=0.5)
        self.assertIn('{ spin = "bone_wheel_l_01", steer = "bone_wheel_l_01", wheel = 4, angle = 0.0 }', six_lua)
        self.assertIn('{ spin = "bone_wheel_r_01", steer = "bone_wheel_r_01", wheel = 10, angle = 0.0 }', six_lua)
        self.assertIn("function ENT:SwitchGear( index, _cooldown )", six_lua)
        self.assertIn("self.switchCD = 0", six_lua)
        self.assertIn("local ratio = selfTbl.isTurningInPlace and 7.50 or selfTbl.gearRatios[gear]", six_lua)
        self.assertIn("if selfTbl.WTTracked and selfTbl.isTurningInPlace then", six_lua)
        self.assertNotIn("if selfTbl.WTTracked and selfTbl.isTurningInPlace and selfTbl.WTSingleFlow then", six_lua)
        self.assertIn("state.sideTractionMult = state.sideTractionMult * 0.15", six_lua)
        self.assertLess(six_lua.index("if w:GetRPM() < -maxRPM then"), six_lua.index("avSum[side] = avSum[side] + w.state.angularVelocity"))

    def test_tank_mass_center_and_qc_emission(self):
        from types import SimpleNamespace as NS
        blk = {"VehiclePhys": {"Mass": {"CenterOfGravity": (0.15, 0.50, 0.00), "CenterOfGravityClampY": (0.0, 0.6)}}}
        self.assertEqual(tankMassCenter(blk), (6.0, 0.0, 20.0))
        clampedBlk = {"VehiclePhys": {"Mass": {"CenterOfGravity": (0.15, 2.0, 0.00), "CenterOfGravityClampY": (0.0, 0.8)}}}
        self.assertEqual(tankMassCenter(clampedBlk), (6.0, 0.0, 32.0))

        nodes = [
            NS(name="bone_wheel_l_01", wtm=[[1, 0, 0, 1.0], [0, 1, 0, 0.4], [0, 0, 1, 1.4]]),
            NS(name="bone_wheel_r_01", wtm=[[1, 0, 0, -0.5], [0, 1, 0, 0.4], [0, 0, 1, -1.4]]),
        ]
        skeleton = NS(getNodes=lambda: nodes, getNodeByName=lambda n: None)
        mc = tankMassCenter(None, skeleton)
        self.assertEqual(mc, (10.0, 0.0, 16.0))

        col = NS(name="tank_col", getSurfaceProp=lambda: "metal")
        smdl = SourceModel("tank", Model("tank"), collision=col)
        smdl.massCenter = (6.0, 0.0, 20.0)
        qc = smdl.getQC("wt_glide", {"hull": ["hull"]})
        self.assertIn("$collisionmodel \"tank_col.smd\"\n{\n\t$automass\n\t$concave\n\t$masscenter 6.00 0.00 20.00\n}", qc)

    def test_wt_suspension_autofill_dialog_and_lua(self):
        from PyQt5.QtWidgets import QApplication
        from gui.glideOptionsDialog import GlideOptionsDialog
        from types import SimpleNamespace as NS

        blk = {
            "maxFwdSpeed": 75.0,
            "maxRevSpeed": 34.0,
            "VehiclePhys": {
                "Mass": {"TakeOff": 55000.0},
                "mechanics": {"neutralGearRatio": 7.5},
                "suspension": {
                    "suspensionOffsets": (-0.12, -0.12, 0.20),
                    "dampeningRelaxationRatio": 0.40,
                    "dampeningCompressionRatio": 0.15,
                },
            },
        }
        self.assertEqual(tankSuspension(blk), (12.0, 20.0, 52.0))
        self.assertEqual(tankSuspension(blk, 14), (12.0, 20.0, 56.1))
        opts = defaultOptions(blk)
        self.assertEqual(opts["suspensionSag"], 12.0)
        self.assertEqual(opts["suspensionDamping"], 52.0)

        app = QApplication.instance() or QApplication([])
        dlg = GlideOptionsDialog(None, opts, "ztz_99a")
        self.assertAlmostEqual(dlg.spins["suspensionSag"].value(), 12.0, places=1)
        self.assertAlmostEqual(dlg.spins["suspensionDamping"].value(), 52.0, places=1)
        self.assertIn("5–9 cm", dlg.suspensionHint.text())
        self.assertIn("70–100%", dlg.suspensionHint.text())
        self.assertIn("5–9 cm", dlg.spins["suspensionSag"].toolTip())
        self.assertIn("70–100%", dlg.spins["suspensionDamping"].toolTip())
        self.assertFalse(dlg.suspensionHint.isHidden())
        dlg.vehicleType.setCurrentIndex(1)
        self.assertTrue(dlg.suspensionHint.isHidden())
        dlg.vehicleType.setCurrentIndex(0)
        out = dlg.options()
        self.assertAlmostEqual(out["suspensionSag"], 12.0, places=1)
        self.assertAlmostEqual(out["suspensionDamping"], 52.0, places=1)

        nodes = [NS(name=f"bone_wheel_{s}_{i:02d}", wtm=[[1, 0, 0, x], [0, 1, 0, 0.45], [0, 0, 1, z]], children=[], parent=None)
                 for s, z in (("l", 1.4), ("r", -1.4)) for i, x in enumerate((2.5, 1.5, 0.5, -0.5, -1.5, -2.5), 1)]
        skeleton = NS(getNodes=lambda: nodes, getNodeByName=lambda n: None)
        lua = generateLua("wt_ztz_99a", "ZTZ-99A", "models/wt_glide/ztz_99a.mdl", skeleton, blk, options=out)
        self.assertIn("local WHEEL_LIFT = 8.0", lua)
        self.assertIn("suspensionPos[2] = self:GetWheelOffset( s.wheel ) + WHEEL_LIFT", lua)
        self.assertIn("self:SetSuspensionLength( 12.8 )", lua)
        self.assertIn("self:SetSpringStrength( 7813 )", lua)
        self.assertIn("self:SetSpringDamper( 48448 )", lua)
        self.assertNotIn("OnSimulatePhysics", lua)
        self.assertNotIn("WHEEL_DROOP", lua)


class WTSoundTest(unittest.TestCase):
    def test_steady_engine_excludes_ignition_but_keeps_nested_loops(self):
        import numpy as np
        from types import SimpleNamespace as NS
        from util.wtsound import Renderer
        loop = NS(kind='WAIB', loop=-1, pitch=0, autoPitchParam=None)
        shot = NS(kind='WAIB', loop=0, pitch=0, autoPitchParam=None)
        nested = NS(kind='EVIB', loop=0, event='child')
        bank = NS(instruments={'loop': loop, 'shot': shot, 'nested': nested},
                  pcm=lambda i: np.ones(32, np.float32), events={'child': object()})
        renderer = Renderer(bank, steadyLoops=True)
        self.assertEqual(len(renderer.instrument('shot')), 0)
        self.assertEqual(len(renderer.instrument('loop')), 32)
        renderer.event = lambda *args: np.ones(17)
        self.assertEqual(len(renderer.instrument('nested')), 17)
        self.assertEqual(len(Renderer(bank).instrument('shot')), 32)

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

    def test_ground_engine_alias_uses_sound_configuration(self):
        from util.glide import soundEvents
        blk = {"sound": {"EngineName": "engine_mctav6", "TrackSoundName": "tracks_wheels"}}
        cfg = {"engine_mctav6": {
            "outside": {"path": "ground/engines/mcta_v6", "eventFront": "", "eventBack": "engine"},
            "effects": {"path": "ground/engines/mcta_v6", "eventStart": "engine_start", "eventStop": "engine_stop"},
        }}
        events = soundEvents(blk, cfg)
        for role, name in (("engine", "engine"), ("start", "engine_start"), ("stop", "engine_stop")):
            self.assertEqual(events[role], f"event:/ground/engines/mcta_v6/{name}")
        self.assertEqual(events["tracks"], "event:/ground/engines/tracks_wheels")
        self.assertEqual(soundEvents(blk, {})["engine"], "event:/ground/engines/mctav6/engine")
        cfg["engine_mctav6"]["outside"] = {"path": "ground/engines/example", "eventFront": "front"}
        self.assertEqual(soundEvents(blk, cfg)["engine"], "event:/ground/engines/example/front")

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

    def test_engine_rpm_variants_keep_layers_and_drive_gain_and_pitch(self):
        from types import SimpleNamespace
        from util.wtsound import engineLayers, Instrument, Event
        instrument, event = Instrument(), Event()
        instrument.kind, instrument.wave = "WAIB", b"wave"
        instrument.conditions = [(b"rpm", 20, 90)]
        instrument.autoPitchParam, instrument.autoPitchRef, instrument.autoPitchMin = b"rpm", 80, 0.5
        event.layouts = [b"layout"]
        bank = SimpleNamespace(events={b"event": event}, layouts={b"layout": (b"rpm", [b"loop"])},
            instruments={b"loop": instrument}, waves={b"wave": b"sample"},
            controllers={b"loop": [(b"ctrl", b"curve", 4)]}, controllerParam={b"ctrl": b"rpm"},
            curves={b"curve": [(0, 0), (100, 1)]}, busEffects={}, faders={})
        expected = None
        for name in ("rpm_result", "rpm_result_2c25", "rpm_result_t80", "rpm"):
            with self.subTest(name=name):
                bank.params = {b"rpm": (name, 0, 100, 0)}
                layers = engineLayers(bank, b"event")
                self.assertEqual(len(layers), 1) # default RPM=0 must not discard a running layer
                controls = layers[0][1]
                self.assertIn(("rpmFraction", 0, 1, "pitch", 0.5, 1.125), controls)
                self.assertIn(("rpmFraction", 0, 1, "volume", 1e-4, 1.0), controls)
                if expected is None:
                    expected = layers
                self.assertEqual(layers, expected)
        for name in ("Distance", "rpm_resultant"):
            bank.params = {b"rpm": (name, 0, 100, 0)}
            self.assertEqual(engineLayers(bank, b"event"), []) # unrelated parameters still use defaults

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


class AircraftTest(unittest.TestCase):
    def test_gear_duration_uses_flightmodel_not_animation_length(self):
        from util.glide import gearDuration
        self.assertAlmostEqual(gearDuration({"GearActuatorSpeed": 0.2}), 5)
        for speed in (0, -1, None, "bad", float("nan"), float("inf"), 1e-12):
            self.assertEqual(gearDuration({"GearActuatorSpeed": speed}, 2), 2)

    def test_native_volume_ramp_rows_and_bounds(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import patch
        from PIL import Image
        from util.glide import jetVolumeRamps
        img = Image.new("RGB", (256, 64))
        for y in range(64):
            for x in range(256):
                img.putpixel((x, y), (x, y, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        pack = SimpleNamespace(getPackedFiles=lambda: [SimpleNamespace(name="afterburneratlastex", getDDS=lambda: buf.getvalue())])
        with patch("parse.material.DDSxTexturePack2", return_value=pack):
            ramps = jetVolumeRamps("unused", {"rampTextureOffset": 4})
            self.assertEqual(ramps[0][0], [0, 16, 0])
            self.assertEqual(ramps[3][-1], [255, 19, 0])
            self.assertEqual(len(ramps[0]), 32)
            with self.assertRaises(ValueError):
                jetVolumeRamps("unused", {"rampTextureOffset": 16})

    def test_volume_and_weapon_audio_follow_vehicle_data(self):
        from types import SimpleNamespace
        from util.glide import generateAircraftLua, aircraftGuns
        node = SimpleNamespace(name="flare1", wtm=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        skeleton = SimpleNamespace(getNodes=lambda: [node], getNodeByName=lambda name: node if name == "flare1" else None)
        weapons = [{"trigger": "cannon", "emitter": "flare1", "blk": ref, "bullets": 150, "arcadeReload": 60,
                    "weaponBlk": {"shotFreq": 30, "bullet": {"caliber": 0.03}}} for ref in ("a.blk", "b.blk")]
        blk = {"fm": {}, "exhaustTexture": "models/test/exhaust", "builtinPreset": {"Weapon": weapons},
               "AfterBurner0": {"volumetricAfterBurner": {"name": "native", "maxHeight": 10, "maxRadius": 0.3}}}
        # builtinPreset is populated by findAircraftBlk.
        from unittest.mock import patch
        with patch("util.glide.aircraftWeapons", return_value=weapons):
            self.assertEqual(len(aircraftGuns(skeleton, blk)), 2)
            lua = generateAircraftLua("wt_test", "test", "test.mdl", skeleton, blk,
                sounds={"guns": {"a.blk": ["gun0_0", "gun0_1"]}, "engine": {"idle": "idle", "full": "full", "wep": "wep"},
                        "gear": {"start": "gear_start", "loop": "gear_loop", "end": "gear_end"}})
        self.assertIn('ENT.WTHideCrew = false', lua)
        self.assertIn('"maxHeight":10', lua)
        self.assertNotIn('mesh.Begin( result, MATERIAL_TRIANGLES', lua)
        self.assertNotIn('volumeMesh:Draw()', lua)
        self.assertIn('include( "wt_jet_exhaust/volume.lua" )', lua)
        self.assertIn('AddCSLuaFile( "wt_jet_exhaust/exhaust.lua" )', lua)
        self.assertIn('drawWTVolume( origin, angles, flame )', lua)
        self.assertNotIn('PLUME_V0', lua)
        self.assertIn('FireDelay = 0.03333', lua)
        self.assertIn('SingleShotSound = "wt_test.Gun0"', lua)
        self.assertNotIn('SingleShotSound = ""', lua)
        self.assertEqual(lua.count('SingleShotSound = '), 1)
        self.assertIn('wt/wt_test/gun0_1.wav', lua)
        self.assertIn('self:CreateLoopingSound( "wt_idle"', lua)
        self.assertIn('90 ):PlayEx( 0, 100 )', lua)
        self.assertIn('wt/wt_test/gear_loop.wav', lua)
        self.assertIn('elseif self.wtGearMoving then', lua) # no lock sound on initial spawn
        self.assertIn('ent.wtGearMotor:Stop()', lua)
        self.assertNotIn('local opacity = 1 - math.exp(', lua)
        self.assertIn('VOLUME.preNominalEasingParams', lua)

    def test_aircraft_sound_uses_gun_event_not_generic_layer(self):
        import tempfile
        import json
        import numpy as np
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from util.glide import exportAircraftSounds
        ref = "gsh.blk"
        weapon = {"blk": ref, "trigger": "cannon", "weaponBlk": {"gunSound": {
            "pathStudio": "aircraft/weapon", "outside": "gsh_30_1_outside"}}}
        names = {b"gun": "gsh_30_1_close-001", b"extra": "20k_close-001", b"tail": "gsh_30_1_last_close-001"}
        bank = SimpleNamespace(instruments={g: SimpleNamespace(wave=g) for g in names},
            waves={g: g for g in names}, sample=lambda g: (names[g],), walk=lambda g: names,
            decode=lambda guids: None)
        renderer = SimpleNamespace(instrument=lambda guid: np.ones(100, np.float32) * 0.1)
        with tempfile.TemporaryDirectory() as temp, patch("util.glide.aircraftWeapons", return_value=[weapon]), \
             patch("util.glide.path.isfile", return_value=True), \
             patch("util.wtsound.readStrings", return_value={"event:/aircraft/weapon/gsh_30_1_outside": b"event"}), \
             patch("util.wtsound.SoundBank", return_value=bank), patch("util.wtsound.Renderer", return_value=renderer):
            sounds = exportAircraftSounds("unused", {}, temp)
            self.assertEqual(sounds["guns"][ref], ["gun0_0"])
            self.assertEqual(json.loads(Path(temp, "sources.json").read_text())[ref]["samples"], ["gsh_30_1_close-001"])
            self.assertTrue(Path(temp, "gun0_0.wav").is_file())

    def test_helicopter_sound_mapping_and_complete_fallback(self):
        import tempfile
        import json
        import numpy as np
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from util.glide import exportAircraftSounds, generateAircraftLua
        config = {"native_heli": {
            "engines": {"outside": {"path": "aircraft/engines", "eventFront": "", "eventBack_1": "turbine"}},
            "propellers": {"outside": {"path": "aircraft/engines", "event_1": "rotor", "event_2": "tail"}}}}
        refs = {"event:/aircraft/engines/" + n: n for n in ("turbine", "rotor", "tail")}
        bank = SimpleNamespace(events={n: SimpleNamespace(layouts=["rpm", "rpm2", "variant"]) for n in refs.values()},
            layouts={n: (n, []) for n in ("rpm", "rpm2", "variant")},
            params={"rpm": ("rpm", 30, 2200, 30), "rpm2": ("rpm2", 0, 2700, 0),
                    "variant": ("rpm_result_custom", 0, 100, 0)},
            walk=lambda g: [], decode=lambda gs: None)
        blk = {"Sound": {"Engine": "native_heli"}, "helicopter": {}, "fm": {}}
        with tempfile.TemporaryDirectory() as temp, patch("util.glide.path.isfile", return_value=True), \
             patch("util.glide.VROMFS", return_value=SimpleNamespace(readBlk=lambda p: config)), \
             patch("util.wtsound.readStrings", return_value=refs), \
             patch("util.wtsound.SoundBank", return_value=bank), \
             patch("util.wtsound.Renderer", return_value=SimpleNamespace(event=lambda *a: np.ones(100) * 0.1)) as render:
            sounds = exportAircraftSounds("unused", blk, temp)
            self.assertEqual(sounds["helicopter"], ["heli_0", "heli_1", "heli_2"])
            self.assertNotIn("engine", sounds)
            params = render.call_args.args[1]
            self.assertEqual((params["rpm"], params["rpm2"], params["broken"]), (2200, 2700, 0))
            self.assertEqual(params["rpm_result_custom"], 100)
            self.assertIn(b"cue ", Path(temp, "heli_0.wav").read_bytes())
            source = json.loads(Path(temp, "sources.json").read_text())["helicopter"]
            self.assertEqual(source[2]["event"], "event:/aircraft/engines/tail")
            # A missing rotor must not leave half a native engine layered over the defaults.
            refs.pop("event:/aircraft/engines/tail")
            self.assertNotIn("helicopter", exportAircraftSounds("unused", blk, temp))
        node = SimpleNamespace(name="root", wtm=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        skeleton = SimpleNamespace(getNodes=lambda: [node], getNodeByName=lambda n: None)
        lua = generateAircraftLua("wt_test", "test", "test.mdl", skeleton, blk, sounds=sounds)
        self.assertIn('ENT.RotorBeatInterval = 0', lua)
        self.assertIn('wt/wt_test/heli_2.wav', lua)
        self.assertIn('self:GetIsEngineDying()', lua)
        self.assertNotIn('"wt_idle"', lua)
        self.assertNotIn('BaseClass.OnUpdateSounds( self )', lua)
        fallback = generateAircraftLua("wt_test", "test", "test.mdl", skeleton, blk)
        self.assertNotIn('ENT.RotorBeatInterval = 0', fallback)
        self.assertNotIn('function ENT:OnUpdateSounds()', fallback)

    def test_aircraft_countermeasures_respect_wt_weapon_slots(self):
        from types import SimpleNamespace
        from util.glide import generateAircraftLua
        node = SimpleNamespace(name="root", wtm=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        skeleton = SimpleNamespace(getNodes=lambda: [node], getNodeByName=lambda n: node if n == "root" else None)
        ww2 = {"fm": {}, "WeaponSlots": {"WeaponSlot": [{"index": 0, "WeaponPreset": {"Weapon": [{"trigger": "bombs"}]}}]}}
        jet = {"fm": {}, "WeaponSlots": {"WeaponSlot": [{"index": 0, "WeaponPreset": {"Weapon": [{"trigger": "countermeasures", "bullets": 48}]}}]}}
        self.assertIn("ENT.CountermeasureCount = 0", generateAircraftLua("wt_p51", "p51", "models/p51.mdl", skeleton, ww2))
        self.assertNotIn("ENT.CountermeasureCount = 0", generateAircraftLua("wt_su33", "su33", "models/su33.mdl", skeleton, jet))

    def test_heli_cannon_prefix_does_not_select_generic_samples(self):
        import tempfile
        import numpy as np
        from types import SimpleNamespace
        from unittest.mock import patch
        from util.glide import exportAircraftSounds
        weapon = {"blk": "cannon.blk", "trigger": "cannon", "weaponBlk": {"gunSound": {
            "pathStudio": "aircraft/weapon", "outside": "cannon_gsh_30_2_outside"}}}
        names = {b"gun": "gsh_30_2_close-001", b"extra": "gsh_30_alt_close-001"}
        bank = SimpleNamespace(instruments={g: SimpleNamespace(wave=g) for g in names}, waves={g:g for g in names},
            sample=lambda g: (names[g],), walk=lambda g: names, decode=lambda gs: None)
        with tempfile.TemporaryDirectory() as temp, patch("util.glide.aircraftWeapons", return_value=[weapon]), \
             patch("util.glide.path.isfile", return_value=True), \
             patch("util.glide.VROMFS", return_value=SimpleNamespace(readBlk=lambda p: {})), \
             patch("util.wtsound.readStrings", return_value={"event:/aircraft/weapon/cannon_gsh_30_2_outside": b"event"}), \
             patch("util.wtsound.SoundBank", return_value=bank), \
             patch("util.wtsound.Renderer", return_value=SimpleNamespace(instrument=lambda g: np.ones(100) * 0.1)):
            sounds = exportAircraftSounds("unused", {}, temp)
            self.assertEqual(sounds["guns"]["cannon.blk"], ["gun0_0"])

    def test_gear_audio_resolves_config_event_and_exports_three_parts(self):
        import tempfile
        import numpy as np
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from util.glide import exportAircraftSounds
        names = {b"s": "chasis_start", b"l": "chasis_loop", b"e": "chasis_end"}
        bank = SimpleNamespace(instruments={g: SimpleNamespace(wave=g) for g in names},
            waves={g: g for g in names}, sample=lambda g: (names[g],), walk=lambda g: names,
            decode=lambda guids: None)
        config = {"misc_effects": {"path": "aircraft/effects", "eventChasis": "chasis"}}
        with tempfile.TemporaryDirectory() as temp, patch("util.glide.path.isfile", return_value=True), \
             patch("util.glide.VROMFS", return_value=SimpleNamespace(readBlk=lambda p: config)), \
             patch("util.wtsound.readStrings", return_value={"event:/aircraft/effects/chasis": b"event"}), \
             patch("util.wtsound.SoundBank", return_value=bank), \
             patch("util.wtsound.Renderer", return_value=SimpleNamespace(instrument=lambda g: np.ones(100) * 0.1)):
            sounds = exportAircraftSounds("unused", {"fm": {"GearActuatorSpeed": 0.2}}, temp)
            self.assertEqual(sounds["gear"], {"start": "gear_start", "loop": "gear_loop", "end": "gear_end"})
            self.assertIn(b"cue ", Path(temp, "gear_loop.wav").read_bytes())
            self.assertNotIn(b"cue ", Path(temp, "gear_start.wav").read_bytes())

    def test_aircraft_sounds_missing_bank_preserves_defaults(self):
        from util.glide import exportAircraftSounds
        self.assertEqual(exportAircraftSounds("Z:/absent", {}, "unused"), {})

    def test_native_heat_is_optional_and_has_no_water_fallback(self):
        from types import SimpleNamespace
        from util.glide import generateAircraftLua
        node = SimpleNamespace(name="root", wtm=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        skeleton = SimpleNamespace(getNodes=lambda: [node], getNodeByName=lambda name: None)
        for texture in ("", "models/wt_glide/wt_test/exhaust"):
            lua = generateAircraftLua("wt_test", "test", "models/test.mdl", skeleton, {"fm": {}, "exhaustTexture": texture})
            self.assertNotIn("dev/water_normal", lua)
            self.assertNotIn('BuildVolume', lua)
            self.assertNotIn('volumeMesh', lua)
            if texture:
                self.assertIn('exhaust.Heat(', lua)
                self.assertIn('AddCSLuaFile( "wt_jet_exhaust/volume.lua" )', lua)
                self.assertIn('drawWTVolume( origin, angles, flame )', lua)
            else:
                self.assertNotIn('include( "wt_jet_exhaust/', lua)

    def test_flaperons_keep_nested_bones_but_drive_only_parent_hinges(self):
        import numpy as np
        from types import SimpleNamespace
        from util.glide import AIRCRAFT_BONE_RE, controlSurfaces
        root = SimpleNamespace(name='root', parent=None, wtm=np.eye(4))
        nodes = {}
        # Local Y hinge runs spanwise, not vertically in aircraft coordinates.
        hinge = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
        for side in ('l', 'r'):
            parent = SimpleNamespace(name='flaperon_' + side, parent=root, wtm=hinge)
            child = SimpleNamespace(name='flaperon1_' + side, parent=parent, wtm=hinge)
            nodes.update({n.name: n for n in (parent, child)})
        class Model(list):
            skeleton = SimpleNamespace(getNodeByName=nodes.get)
            def getVertex(self, index, *args):
                return [(-2, 0, 0), (-1, 0, 1), (-1, 0, -1)][index]
        model = Model(SimpleNamespace(name=name, skinned=False, faces=[(0, 1, 2)]) for name in nodes)
        self.assertTrue(all(AIRCRAFT_BONE_RE.fullmatch(name) for name in nodes))
        controls = controlSurfaces(model)
        self.assertEqual([c[0] for c in controls], ['flaperon_l', 'flaperon_r'])
        self.assertTrue(all(c[1] == 'GetAileron' for c in controls))
        self.assertEqual(controls[0][3], -controls[1][3])
        self.assertEqual(abs(controls[0][3]), 20)

    def test_gear_sequences_preserve_neutral_ailerons(self):
        import numpy as np
        from types import SimpleNamespace
        from util.glide import gearSequences
        root = SimpleNamespace(idx=0, name="root", parent=None, tm=np.eye(4), wtm=np.eye(4))
        wing = SimpleNamespace(idx=1, name="aileron_l", parent=root, tm=np.eye(4), wtm=np.eye(4))
        gear = SimpleNamespace(idx=2, name="gear_l", parent=root, tm=np.eye(4), wtm=np.eye(4))
        nodes = [root, wing, gear]
        skeleton = SimpleNamespace(getNodes=lambda: nodes, getReducedBones=lambda keep: (nodes, {}),
                                   getReducedSMD=lambda kept: "version 1\nnodes\nend\nskeleton\n")
        def sample(t):
            q = lambda x: (0, 0, 0, 1, x, 0, 0, 1, 1, 1)
            return {"aileron_l": q(t), "gear_l": q(t), "root": q(999)}
        sequences = gearSequences(skeleton, set(), SimpleNamespace(duration=2, sample=sample), {"GearActuatorSpeed": 0.2})
        self.assertIn("time 150\n", sequences["move_gear_down"])
        self.assertNotIn("time 151\n", sequences["move_gear_down"])
        for sequence in sequences.values():
            wing_lines = [line for line in sequence.splitlines() if line.startswith("1 ")]
            self.assertTrue(wing_lines)
            self.assertTrue(all(float(line.split()[1]) == 40 for line in wing_lines))
            self.assertNotIn("39960.0000", sequence) # unrelated animation channels must not move the root
        self.assertIn("2 80.0000", sequences["gear_down"])
        self.assertIn("2 0.0000", sequences["gear_up"])
        self.assertIn("2 0.0000", sequences["idle"])

    def test_gear_pose_bakes_into_rotation_free_bones(self):
        import numpy as np
        from math import cos, sin, radians
        from util.glide import poseSMD, poseWorld, AIRCRAFT_GEAR_RE

        class Node:
            def __init__(self, idx, name, parent, tm):
                self.idx, self.name, self.parent, self.tm = idx, name, parent, tm
                self.wtm = (np.array(parent.wtm) @ np.array(tm) if parent else np.array(tm)).tolist()
        def tm(p, deg = 0.0):
            c, s = cos(radians(deg)), sin(radians(deg))
            return [[c, -s, 0, p[0]], [s, c, 0, p[1]], [0, 0, 1, p[2]], [0, 0, 0, 1]]
        root = Node(0, "root", None, tm((0, 0, 0)))
        gear = Node(1, "gear_l", root, tm((1, 0, 2), 30)) # rotated frame, like Dagor nodes
        wheel = Node(2, "wheel_l", gear, tm((0, -1, 0)))
        class Skeleton:
            def getNodes(self): return [root, gear, wheel]
        # the a2d swings the strut 90 degrees about its local z
        q = (0.0, 0.0, sin(radians(45)), cos(radians(45)), 1.0, 0.0, 2.0, 1.0, 1.0, 1.0)
        world = poseWorld(Skeleton(), {"gear_l": q}, AIRCRAFT_GEAR_RE)
        lines = poseSMD(Skeleton(), [root, gear, wheel], world)
        # composing the SMD frames (R = Rz Ry Rx) puts every bone where the animated node is, z mirrored
        def mat(v):
            rx, ry, rz = v[3:]
            Rx = np.array([[1, 0, 0], [0, cos(rx), -sin(rx)], [0, sin(rx), cos(rx)]])
            Ry = np.array([[cos(ry), 0, sin(ry)], [0, 1, 0], [-sin(ry), 0, cos(ry)]])
            Rz = np.array([[cos(rz), -sin(rz), 0], [sin(rz), cos(rz), 0], [0, 0, 1]])
            m = np.eye(4)
            m[:3, :3], m[:3, 3] = Rz @ Ry @ Rx, v[:3]
            return m
        composed = np.eye(4)
        for k, line in enumerate(lines):
            composed = composed @ mat([float(v) for v in line.split()[1:]])
            self.assertTrue(np.allclose(composed[:3, 3], np.array(world[k])[:3, 3] * [40, 40, -40], atol = 1e-3))
        self.assertTrue(np.allclose(np.array(world[1])[:3, 3], [1, 0, 2])) # swing pivots in place

    def test_hidden_and_collision_nodes(self):
        from util.glide import aircraftCollisionNodes, aircraftHiddenNodes
        blk = {"WeaponSlots": {"HideNodes": {"node": ["pylon1", "fuse4"]}, "WeaponSlot": [{"index": 0, "WeaponPreset": [{"ShowNodes": {"node": "fuse4"}}]}]}}
        names = ["fuse", "fuse4", "pylon1", "flare3", "prop01_1", "prop02_1", "prop01_1_dmg", "jet_flame", "chute1", "chute2", "chute3"]
        self.assertEqual(aircraftHiddenNodes(names, blk), {"pylon1", "flare3", "prop02_1", "prop01_1_dmg"}) # jet_flame stays, scaled with thrust
        self.assertEqual(aircraftCollisionNodes(["fuse_dm", "wing1_l_dm", "tank3_dm", "gear_l_dm", "wingcontrol_dm"]), {"fuse_dm", "wing1_l_dm"})
        from util.wtloadout import hiddenNodes
        self.assertFalse(hiddenNodes({}, [], ["chute1", "chute2", "chute3"]))
        self.assertEqual(hiddenNodes({"WeaponSlots": {"HideNodes": {"node": "chute1"}}}, [], ["chute1"]), {"chute1"})

    def test_remove_objects_prunes_unused_materials(self):
        from types import SimpleNamespace
        mdl = Model("plane", materials=(SimpleNamespace(getName=lambda: "body_mat"), SimpleNamespace(getName=lambda: "prop_mat")))
        body = mdl.newObject("fuse")
        body.appendMaterial("body_mat")
        prop = mdl.newObject("prop02_1")
        prop.appendMaterial("prop_mat")
        mdl.removeObjects({"prop02_1"})
        self.assertEqual([m.getName() for m in mdl.materials], ["body_mat"])

    def test_find_aircraft_blk_matches_hyphenated_and_model_field(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from util.glide import findAircraftBlk, defaultOptions
        files = {
            "config/gameplay.blk": {},
            "gamedata/flightmodels/bf-109a_1.blk": {"model": "bf_109a_1"},
            "gamedata/flightmodels/fm/bf-109a_1.blk": {"Mass": {"EmptyMass": 1900.0, "MaxFuelMass0": 177.0}},
            "gamedata/flightmodels/ef_2000a.blk": {"model": "f_2000a", "fmFile": "fm/f_2000a.blk"},
            "gamedata/flightmodels/fm/f_2000a.blk": {"Mass": {"EmptyMass": 11000.0, "MaxFuelMass0": 4000.0}},
        }
        vfs = SimpleNamespace(files=set(files), readBlk=lambda k: dict(files[k]))
        with patch("util.glide.findGameRoot", return_value="root"), patch("util.glide.VROMFS", return_value=vfs):
            bf = findAircraftBlk("root/res/aircrafts/germ_bf_109.grp", "bf_109a_1")
            ef = findAircraftBlk("root/res/aircrafts/air.grp", "f_2000a")
        self.assertEqual(bf["fm"]["Mass"]["EmptyMass"], 1900.0)
        self.assertEqual(ef["fm"]["Mass"]["EmptyMass"], 11000.0)
        self.assertEqual(defaultOptions(bf), {"aircraft": True, "helicopter": False, "mass": 2077.0, "maxSpeed": 2400.0, "engineForce": 350.0})


class TankSmokeTest(unittest.TestCase):
    def test_tank_smoke_weapon_filters_barrels_and_finds_ejection_launchers(self):
        from types import SimpleNamespace
        from util.glide import tankSmokeWeapon, findTankSmoke
        barrel = {
            "triggerGroup": "smoke",
            "emitter": "emtr_smoke_01",
            "weaponBlk": {"mesh": "t55_smoke_barrel", "rocket": {"bulletType": "smoke_grenade_tank", "startSpeed": 1.0}},
        }
        grenade = {
            "triggerGroup": "smoke",
            "emitterGenRange": (1, 2),
            "emitterGenFmt": "emtr_mortar_flame_%02d",
            "salvo": 2,
            "salvoDelay": 0.5,
            "weaponBlk": {
                "mesh": "grenade_cn_76mm",
                "reloadTime": 8.0,
                "rocket": {"bulletType": "smoke_grenade_tank", "startSpeed": 16.0, "endSpeed": 16.0,
                           "smokeActivateTime": 2.0, "smokeTime": 20.0, "smokeShellRad": 9.0},
            },
        }
        blk = {
            "commonWeapons": {"Weapon": [barrel]},
            "modifications": {"tank_smoke_screen_system_mod": {"effects": {"commonWeapons": {"Weapon": [grenade]}}}},
        }
        self.assertIsNone(tankSmokeWeapon(blk, upgraded=False))
        self.assertIs(tankSmokeWeapon(blk, upgraded=True), grenade)

        class Node:
            def __init__(self, idx, name, parent, pos, xAxis=(1.0, 0.0, 0.0)):
                self.idx, self.name, self.parent = idx, name, parent
                self.wtm = [[xAxis[0], 0, 0, pos[0]], [xAxis[1], 1, 0, pos[1]], [xAxis[2], 0, 1, pos[2]], [0, 0, 0, 1]]

        root = Node(0, "", None, (0, 0, 0))
        turret = Node(1, "bone_turret", root, (0.2, 1.5, 0.0))
        mount = Node(2, "bone_grenade", turret, (0.2, 1.5, 0.0))
        e1 = Node(3, "emtr_mortar_flame_01", mount, (0.2, 1.8, -1.5), (0.8, 0.6, 0.0))
        e2 = Node(4, "emtr_mortar_flame_02", mount, (0.2, 1.8, 1.5), (0.8, 0.6, 0.0))
        nodes = [root, turret, mount, e1, e2]
        skeleton = SimpleNamespace(getNodes=lambda: nodes, getNodeByName=lambda n: next((x for x in nodes if x.name == n), None))
        smoke = findTankSmoke(blk, skeleton)
        self.assertEqual(smoke["mesh"], "grenade_cn_76mm")
        self.assertEqual(len(smoke["emitters"]), 2)
        self.assertTrue(all(e["turret"] and e["bone"] == "bone_turret" for e in smoke["emitters"]))
        self.assertAlmostEqual(smoke["emitters"][0]["pos"][2], 12.0)
        self.assertAlmostEqual(smoke["speed"], 640.0)
        self.assertAlmostEqual(smoke["smokeRadius"], 360.0)

    def test_compile_smoke_models_and_generate_lua(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from util.glide import compileSmokeModels, generateLua

        class Node:
            def __init__(self, idx, name, parent, pos):
                self.idx, self.name, self.parent = idx, name, parent
                self.wtm = [[1, 0, 0, pos[0]], [0, 1, 0, pos[1]], [0, 0, 1, pos[2]], [0, 0, 0, 1]]

        root = Node(0, "", None, (0, 0, 0))
        turret = Node(1, "bone_turret", root, (0, 1, 0))
        emtr1 = Node(2, "emtr_mortar_flame_01", turret, (1, 2, 0.5))
        emtr2 = Node(3, "emtr_mortar_flame_02", turret, (1, 2, -0.5))
        nodes = [root, turret, emtr1, emtr2]

        class Skeleton:
            def getNodes(self): return nodes
            def getNodeByName(self, name): return next((n for n in nodes if n.name == name), None)
            def getReducedBones(self, keep):
                kept = [n for n in nodes if n.idx == 0 or n.name in keep]
                bmap = {n.idx: (kept.index(n) if n in kept else 0) for n in nodes}
                return kept, bmap
            def getReducedSMD(self, kept):
                return "nodes\n" + "\n".join(f'{i} "{n.name or "_ROOT"}" {0 if i else -1}' for i, n in enumerate(kept)) + "\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend"

        class Mat:
            def __init__(self, name): self._name = name
            def getName(self): return self._name
            def setName(self, name): self._name = name

        grenade = Model("grenade_cn_76mm", materials=(Mat("grenade_mat"),))
        gObj = grenade.newObject("@root")
        gObj.appendMaterial("grenade_mat")
        grenade.appendVerts([(0, 0, 0), (0.2, 0, 0), (0, 0.1, 0)], [(0, 0), (1, 0), (0, 1)], scale=False)
        gObj.appendFace((0, 1, 2))

        smoke = {
            "mesh": "grenade_cn_76mm",
            "grenadeModel": grenade,
            "matMap": {"grenade_mat": "smoke_grenade_mat"},
            "emitters": [
                {"name": "emtr_mortar_flame_01", "bone": "bone_turret", "turret": True, "pos": [40.0, 20.0, 40.0], "dir": (0.8, 0.0, 0.6)},
                {"name": "emtr_mortar_flame_02", "bone": "bone_turret", "turret": True, "pos": [40.0, -20.0, 40.0], "dir": (0.8, 0.0, 0.6)},
            ],
            "salvo": 2,
            "salvoDelay": 0.5,
            "reloadTime": 8.0,
            "speed": 640.0,
            "activateTime": 2.0,
            "smokeTime": 20.0,
            "smokeRadius": 360.0,
        }

        with tempfile.TemporaryDirectory() as d:
            qc = Path(d) / "ztz_99a.qc"
            qc.write_text('$modelname "wt_glide/ztz_99a.mdl"\n$cdmaterials "models/wt_glide/ztz_99a"\n')
            targets = compileSmokeModels(qc, Skeleton(), smoke)
            self.assertEqual([name for _, name in targets], ["ztz_99a_smoke", "ztz_99a_smoke_rack"])
            self.assertEqual(smoke["projModel"], "models/wt_glide/ztz_99a_smoke.mdl")
            self.assertEqual(smoke["rackModel"], "models/wt_glide/ztz_99a_smoke_rack.mdl")
            self.assertEqual(smoke["bodygroups"], [(0, 1), (1, 2)])
            rackQcText = (Path(d) / "ztz_99a_smoke_rack.qc").read_text()
            self.assertIn('$bodygroup "smoke_00"', rackQcText)
            self.assertIn('$bodygroup "smoke_01"', rackQcText)
            self.assertIn("smoke_grenade_mat", (Path(d) / "ztz_99a_smoke.smd").read_text())
            self.assertIn("smoke_grenade_mat", (Path(d) / "ztz_99a_smoke_rack_00.smd").read_text())

        lua = generateLua("wt_ztz_99a", "ZTZ-99A", "models/wt_glide/ztz_99a.mdl", Skeleton(), None, smoke=smoke)
        self.assertIn('name = "Smoke Grenades"', lua)
        self.assertIn("self.wtSmokeRack = ClientsideModel( SMOKE.rackModel", lua)
        self.assertIn("EF_BONEMERGE", lua)
        self.assertIn("FireSmoke", lua)
        self.assertIn('net.Receive( "WTGlide.SmokeBurst"', lua)
        self.assertIn('self:SetNW2Int( "WTSmokeFired", 0 )', lua)
        self.assertIn("self.wtSmokeRack:Remove()", lua)
        self.assertIn('weapon.CrosshairImage = ""', lua)
        self.assertIn("function ENT:WeaponThink( selfTbl )", lua)
        self.assertIn("if not fullUpdate and IsValid( self.wtSmokeRack ) then", lua)
        self.assertIn("smokeBurstId = smokeBurstId + 1", lua)

        plainLua = generateLua("wt_plain", "Plain", "models/wt_glide/plain.mdl", Skeleton(), None)
        self.assertNotIn("function ENT:OnActivateWeapon", plainLua)
        self.assertNotIn("function ENT:WeaponThink", plainLua)
