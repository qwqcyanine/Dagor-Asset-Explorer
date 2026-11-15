import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/dae'))
from parse.realres import Model
from util.wtcockpit import prepareInterior, cockpitLua, splitCockpitQC


class CockpitTest(unittest.TestCase):
    def test_gui_cockpit_is_opt_in_and_only_available_for_j16_planes(self):
        from PyQt5.QtWidgets import QApplication
        from gui.glideOptionsDialog import GlideOptionsDialog
        app = QApplication.instance() or QApplication([])
        dialog = GlideOptionsDialog(None, {'aircraft': True}, modelName='j_16')
        self.assertTrue(dialog.cockpit.isEnabled())
        self.assertFalse(dialog.options()['cockpit'])
        dialog.cockpit.setChecked(True)
        self.assertTrue(dialog.options()['cockpit'])
        dialog.vehicleType.setCurrentIndex(2)
        self.assertFalse(dialog.cockpit.isEnabled())
        self.assertFalse(dialog.options()['cockpit'])
        dialog.close()
        other = GlideOptionsDialog(None, {'aircraft': True, 'cockpit': True}, modelName='su_33')
        self.assertFalse(other.cockpit.isEnabled())
        self.assertFalse(other.options()['cockpit'])
        other.close()

    def test_preflight_rejects_unsupported_or_missing_native_data(self):
        from util.wtcockpit import cockpitPack
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'J-16 only'):
                cockpitPack(folder, 'su_33')
            with self.assertRaisesRegex(FileNotFoundError, 'HQ cockpit'):
                cockpitPack(folder, 'j_16')
            root = Path(folder)
            pack = root / 'content.hq/pkg_cockpits/res/pkg_cockpits_aircrafts/j_16.grp'
            for file in (pack, pack.parent.parent / 'dynModelDesc.bin', root / 'ui/atlases.vromfs.bin'):
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            self.assertEqual(cockpitPack(folder, 'j_16'), pack)

    def test_integrated_compile_stages_materials_and_collects_addon(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        from util.wtcockpit import exportCockpit
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            pack = root / 'j_16.grp'
            tools = [root / n for n in ('studiomdl.exe', 'gameinfo.txt', 'vtfcmd.exe')]
            for file in tools:
                file.touch()
            out, addon = root / 'source', root / 'addon'
            qcdir = out / 'j_16_cockpit'
            qcdir.mkdir(parents=True)
            qc = qcdir / 'j_16_cockpit.qc'
            qc.write_text('$opaque\n')
            target = qcdir / 'j_16_cockpit_0.qc'
            target.touch()
            materials = qcdir / 'source_export/materials'
            materials.mkdir(parents=True)
            (materials / 'panel.vmt').write_text('VertexLitGeneric {}')
            (qcdir / 'textures').mkdir()
            (qcdir / 'textures/panel.dds').touch()
            model = SimpleNamespace(materials=[], skeleton=object(), exportTextures=lambda *a, **k: None)
            dyn = SimpleNamespace(name='j_16_cockpit', getModel=lambda _: model)
            stack.enter_context(patch('util.wtcockpit.cockpitPack', return_value=pack))
            stack.enter_context(patch('parse.realres.DynModel', SimpleNamespace))
            stack.enter_context(patch('parse.gameres.GameResDesc'))
            archive = stack.enter_context(patch('parse.gameres.GameResourcePack'))
            archive.return_value.getPackedFiles.return_value = [dyn]
            stack.enter_context(patch('util.assetcacher.AssetCacher.cacheAsset'))
            stack.enter_context(patch('util.assetcacher.AssetCacher.appendGameResDesc'))
            stack.enter_context(patch('util.wtcockpit.prepareInterior', return_value=(set(), {'surfaces': {}})))
            stack.enter_context(patch('util.a2d.A2D.fromPack'))
            stack.enter_context(patch('util.wtcockpit.stickPoses', return_value={}))
            vrom = stack.enter_context(patch('util.vromfs.VROMFS'))
            vrom.return_value.readBlk.return_value = {'cockpit': {'headPos': [7.8, 1, 0]}}
            source = stack.enter_context(patch('parse.realres.SourceModel'))
            source.return_value.export.return_value = (str(qc), SimpleNamespace(
                getDict=lambda: {'panel': SimpleNamespace(texPath='panel')}))
            stack.enter_context(patch('util.wtcockpit.splitCockpitQC', return_value=[target]))
            stack.enter_context(patch('util.wtcockpit.exportDisplayArtwork'))
            lua = stack.enter_context(patch('util.wtcockpit.cockpitLua', return_value='COCKPIT'))
            stages = []
            def run(command):
                if command[0] == str(tools[2]):
                    (Path(command[-1]) / 'panel.vtf').touch()
                    return
                stage = Path(command[command.index('-game') + 1])
                self.assertNotEqual(stage, root)
                self.assertTrue((stage / 'materials/panel.vmt').is_file())
                self.assertTrue((stage / 'materials/panel/panel.vtf').is_file())
                self.assertTrue((stage / 'gameinfo.txt').is_file())
                stages.append(stage)
                dest = stage / 'models/wt_glide/cockpits/j_16'
                dest.mkdir(parents=True)
                for suffix in ('.mdl', '.vvd', '.dx90.vtx'):
                    (dest / (target.stem + suffix)).touch()
            self.assertEqual(exportCockpit(root, 'j_16', out, addon, *tools, run), 'COCKPIT')
            self.assertFalse(stages[0].exists())
            self.assertTrue((addon / 'models/wt_glide/cockpits/j_16/j_16_cockpit_0.mdl').is_file())
            self.assertEqual(lua.call_args.args[1], (312, 0, 40))
            # A converter that returns success without output must not reuse old VTFs.
            with self.assertRaisesRegex(RuntimeError, 'VTFCmd did not create'):
                exportCockpit(root, 'j_16', out, addon, *tools, lambda command: None)

    def test_addon_writer_appends_cockpit_after_airframe_and_weapons(self):
        from unittest.mock import patch
        from util.glide import writeAddon
        with tempfile.TemporaryDirectory() as folder, \
             patch('util.glide.generateAircraftLua', return_value='AIRFRAME\n'), \
             patch('util.glide.aircraftGuns', return_value=[]), \
             patch('util.wtweapons.missileLua', return_value='WEAPONS\n'), \
             patch('util.wtloadout.weaponLabels', return_value={}):
            writeAddon(folder, 'wt_j_16', 'J-16', 'models/wt_glide/j_16.mdl', None,
                       {'fm': {}}, cockpit='COCKPIT\n')
            lua = Path(folder, 'lua/entities/wt_j_16.lua').read_text(encoding='utf8')
            self.assertEqual(lua, 'AIRFRAME\nWEAPONS\nCOCKPIT\n')
            writeAddon(folder, 'wt_j_16', 'J-16', 'models/wt_glide/j_16.mdl', None, {'fm': {}})
            self.assertEqual(Path(folder, 'lua/entities/wt_j_16.lua').read_text(encoding='utf8'),
                             'AIRFRAME\nWEAPONS\n')

    def model(self):
        nodes = [SimpleNamespace(idx=i, name=n) for i, n in enumerate(('root', 'panel', 'collimator', 'fuse', 'weighted'))]
        skeleton = SimpleNamespace(getNodes=lambda: nodes, getNodeByName=lambda n: next((b for b in nodes if b.name == n), None),
                                   getReducedBones=lambda keep: ([b for b in nodes if b.name in keep or b.name == 'root'], {}))
        model = Model('cockpit', skeleton=skeleton)
        model.appendVerts([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0)] * 3)
        for name, material in [('panel', 'j_16_cockpit'), ('collimator', 'dynamic_mfd_trans'), ('fuse', 'j_16_aircraft_normal_detail_lo')]:
            obj = model.newObject(name, skinned=True)
            obj.faces = [(0, 1, 2)]
            obj.materials = {0: material}
        model.skin[0] = ((4, 1),)
        return model

    def test_interior_keeps_weight_dependencies_and_aperture(self):
        model = self.model()
        keep, report = prepareInterior(model)
        self.assertEqual(report['objects'], ['panel', 'collimator'])
        self.assertIn('weighted', keep)
        self.assertEqual(report['bones'], 4)
        self.assertEqual(report['faces'], 2)
        self.assertEqual(report['surfaces']['dynamic_mfd_trans'][0][2], [0, 0, 40])

    def test_displays_preserve_surface_positions_and_native_uvs(self):
        model = self.model()
        for name, material in [('cn_gauge_mfi_j_16', 'dynamic_mfd'), ('blister2', 'dynamic_mirror')]:
            obj = model.newObject(name, skinned=True)
            obj.faces = [(0, 1, 2), (0, 2, 1)]
            obj.materials = {0: 'j_16_cockpit', 1: material}
        _, report = prepareInterior(model)
        displays = report['surfaces']['displays']
        self.assertEqual([d['material'] for d in displays], ['dynamic_mfd', 'dynamic_mirror'])
        self.assertEqual(displays[0]['triangles'][0][1], [0, 0, 40, 0, 0])
        code = cockpitLua('models/test.mdl', (312, 0, 43), report['surfaces'])
        self.assertIn('if display_rendering or RealTime()', code)
        self.assertNotIn('render.RenderView', code)
        self.assertIn('["$envmap"] = "env_cubemap"', code)
        self.assertIn('data.material ~= "dynamic_mirror"', code)
        self.assertIn('mirror_material:GetName()', code)
        self.assertIn('render.PopRenderTarget()', code)
        self.assertIn('RADAR / RWR: NO DATA', code)
        self.assertNotIn('__COCKPIT_', code)

    def test_native_instrument_artwork_preserves_pixels_and_alpha(self):
        from io import BytesIO
        from unittest.mock import patch
        from PIL import Image
        from util.wtcockpit import exportDisplayArtwork
        buffer = BytesIO()
        Image.new('RGBA', (2, 2), (10, 80, 120, 37)).save(buffer, format='PNG')
        with tempfile.TemporaryDirectory() as folder, patch('util.vromfs.VROMFS') as archive:
            archive.return_value.read.return_value = buffer.getvalue()
            exportDisplayArtwork('installed-wt', folder)
            files = list((Path(folder) / 'wt_cockpit/instruments').glob('*.png'))
            self.assertEqual(len(files), 4)
            for path in files:
                with Image.open(path) as image:
                    self.assertEqual(image.getpixel((0, 0)), (10, 80, 120, 37))
            archive.return_value.read.assert_any_call('gameuiskin/mfd_speed.avif')

    def test_missing_aperture_does_not_mutate_model(self):
        model = self.model()
        model['collimator'].materials = {0: 'wrong'}
        with self.assertRaisesRegex(ValueError, 'HUD geometry'):
            prepareInterior(model)
        self.assertIsNotNone(model['fuse'])

    def test_split_preserves_every_mesh_once_and_shared_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('a', 'b', 'c'):
                (root / f'{name}.smd').write_text('triangles\nmaterial\nv\nv\nv' + ('\nend\n' if name == 'a' else ''))
            qc = root / 'cockpit.qc'
            qc.write_text('$upaxis Y\n$origin 0 0 0 -90\n$modelname "test/cockpit.mdl"\n' +
                          ''.join(f'$body studio "{name}.smd"\n' for name in ('a', 'b', 'c')))
            parts = splitCockpitQC(qc, maxFaces=2)
            self.assertEqual(len(parts), 2)
            text = ''.join(p.read_text() for p in parts)
            for name in ('a', 'b', 'c'):
                self.assertEqual(text.count(f'$body studio "{name}.smd"'), 1)
            self.assertIn('$modelname "test/cockpit_1.mdl"', text)
            self.assertEqual(text.count('$origin 0 0 0 -90'), 2)
            with self.assertRaisesRegex(ValueError, 'budget'):
                splitCockpitQC(qc, maxFaces=0)

    def test_runtime_uses_glide_callbacks_and_preserves_external_crew(self):
        code = cockpitLua('models/test.mdl', (312, 0, 43), {'dynamic_mfd_trans': [[[0, 0, 0]] * 3]})
        self.assertIn('function ENT:DrawVehicleHUD', code)
        self.assertIn('self.weapons[self.weaponSlotIndex]', code)
        self.assertIn('self.WeaponInfo[self.weaponSlotIndex]', code)
        self.assertLess(code.index('render.SetStencilEnable(false)'), code.index('weapon:DrawCrosshair()'))
        self.assertIn('self:GetElevator()', code)
        self.assertIn('self:GetAileron()', code)
        self.assertIn('ENT.WTHideCrew = false', code)
        self.assertIn('ply == LocalPlayer()', code)
        self.assertIn('render.SetStencilEnable(false)', code)
        self.assertIn('render.MaterialOverrideByIndex(index, nil)', code)
        self.assertNotIn('__COCKPIT_', code)
        self.assertNotIn('ents.Create(', code)
        with self.assertRaises(ValueError):
            cockpitLua('bad', (0, 0, 0), {})

    def test_stick_poses_use_native_samples_and_reduced_rest(self):
        from unittest.mock import patch
        from util.wtcockpit import stickPoses
        node = SimpleNamespace(name='stick_elevator')
        skeleton = SimpleNamespace(getReducedBones=lambda _: ([node], {}))
        animation = SimpleNamespace(names=['stick_elevator', 'stick_ailerons'], duration=4,
                                    sample=lambda t: t)
        with patch('util.glide.poseWorld', side_effect=lambda s, sample, *args: sample), \
                patch('util.glide.poseSMD', side_effect=lambda s, k, w: [f'0 {w or 0} 0 0 0 0 0']):
            poses = stickPoses(skeleton, animation)
        self.assertEqual(len(poses['stick_elevator']), 9)
        self.assertEqual(poses['stick_elevator'][4][0], [2, 0, 0])
        self.assertEqual(poses['stick_elevator'][-1][0], [4, 0, 0])
        with self.assertRaisesRegex(ValueError, 'Missing native'):
            stickPoses(skeleton, SimpleNamespace(names=[]))

    def test_exterior_materials_are_explicit_and_optional(self):
        surfaces = {'dynamic_mfd_trans': [[[0, 0, 0]] * 3]}
        code = cockpitLua('models/test.mdl', (312, 0, 43), surfaces, ['j_16_interior'])
        self.assertIn('[==[["j_16_interior"]]==]', code)
        self.assertIn('if first_person(self) then', code)
        self.assertIn('pcall(old_body_draw or self.DrawModel, self, ...)', code)
        self.assertNotIn('SetBodygroup', code)
        self.assertIn('[==[[]]==]', cockpitLua('models/test.mdl', (312, 0, 43), surfaces))


if __name__ == '__main__':
    unittest.main()
