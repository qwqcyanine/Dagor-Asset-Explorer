from pathlib import Path
import unittest
import sys
import tempfile

from util import sourceparts as splitter


class SukhoiSplitTests(unittest.TestCase):
    def test_shared_ancestors_animate_on_both_models(self):
        from types import SimpleNamespace
        from util.glide import generateAircraftLua
        node = SimpleNamespace(name='root', wtm=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        skeleton = SimpleNamespace(getNodes=lambda: [node], getNodeByName=lambda name: None)
        lua = generateAircraftLua('wt_su_33', 'Su-33', 'models/wt_glide/su_33.mdl', skeleton, {'fm': {}},
                                  nozzleModel='models/wt_glide/su_33_nozzles.mdl')
        self.assertIn('su_33_nozzles.mdl', lua)
        self.assertIn('self.wtNozzleModel:SetupBones()', lua)
        self.assertIn('self.wtNozzleModel:SetSkin( self:GetSkin() )', lua)
        self.assertIn('self.wtNozzleModel:ManipulateBoneAngles( nozzleBone, LerpAngle', lua)
        self.assertIn('self.wtNozzleModel:Remove()', lua)
        self.assertEqual(lua.count('\nif CLIENT then\n'), 1)
        self.assertEqual(lua.count('\nif SERVER then\n'), 1)

    def test_both_components_keep_skin_families_after_collision(self):
        group = '$texturegroup "skinfamilies"\n{\n { "metal" }\n { "skins/custom/metal" }\n}\n'
        with tempfile.TemporaryDirectory() as d:
            qc = Path(d) / 'su.qc'
            qc.write_text('$modelname "su.mdl"\n$collisionmodel "collision.smd"\n{\n}\n' + group)
            from unittest.mock import patch
            with patch.object(splitter, 'prune_smd', return_value=('smd', 1)):
                (Path(d) / 'collision.smd').write_text('smd')
                out = splitter.split(qc)
            for part in ('body', 'nozzles'):
                text = (out / (part + '.qc')).read_text()
                self.assertEqual(text.count('$texturegroup'), 1)
                self.assertIn(group.strip(), text)
            self.assertNotIn('$collisionmodel', (out / 'nozzles.qc').read_text())

    def test_gui_compile_targets_and_addon_use_split_models(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from gui.customtreeview import ExportToGlide
        from util.glide import writeAddon
        # Invoke the unbound hook with the same state held by the export action.
        action = SimpleNamespace(splitNozzles=True, loadout=[], item=SimpleNamespace(asset=SimpleNamespace(name='j_16')))
        with patch.object(splitter, 'split', return_value=Path('split')):
            self.assertEqual(ExportToGlide.compileTargets(action, 'j_16.qc'),
                             [(Path('split/body.qc'), 'j_16'), (Path('split/nozzles.qc'), 'j_16_nozzles')])
        node = SimpleNamespace(name='root', wtm=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        skeleton = SimpleNamespace(getNodes=lambda: [node], getNodeByName=lambda name: None)
        with tempfile.TemporaryDirectory() as d:
            writeAddon(d, 'wt_j_16', 'J16', 'models/wt_glide/j_16.mdl', skeleton, {'fm': {}},
                       nozzleModel='models/wt_glide/j_16_nozzles.mdl')
            text = (Path(d) / 'lua/entities/wt_j_16.lua').read_text()
            self.assertIn('ClientsideModel( "models/wt_glide/j_16_nozzles.mdl"', text)
            self.assertIn('self.wtNozzleModel:SetSkin( self:GetSkin() )', text)

    def test_remaps_vertices_and_animation_without_changing_coordinates(self):
        smd = '''version 1
nodes
0 "root" -1
1 "gear" 0
2 "nozzle1_1" 0
end
skeleton
time 0
0 0 0 0 0 0 0
1 1 0 0 0 0 0
2 2 0 0 0 0 0
time 1
0 0 0 0 0 0 0
1 1 0 0 0 0 0
2 3 0 0 0 0 0
end
triangles
metal
2 1 2 3 0 1 0 0 0
2 2 3 4 0 1 0 1 0
2 3 4 5 0 1 0 1 1
end
'''
        result, count = splitter.prune_smd(smd, lambda n: n.startswith('nozzle'))
        self.assertEqual(count, 2)
        self.assertNotIn('"gear"', result)
        self.assertIn('1 "nozzle1_1" 0', result)
        self.assertIn('time 1\n0 0 0 0 0 0 0\n1 3 0 0 0 0 0', result)
        self.assertIn('metal\n1 1 2 3 0 1 0 0 0', result)
        with self.assertRaises(AssertionError):
            splitter.prune_smd(smd, lambda n: n == 'gear')
        weighted = smd.replace('2 1 2 3 0 1 0 0 0', '1 1 2 3 0 1 0 0 0 2 2 0.75 0 0.25')
        result, _ = splitter.prune_smd(weighted, lambda n: n.startswith('nozzle'))
        self.assertIn('1 1 2 3 0 1 0 0 0 2 1 0.75 0 0.25', result)
        with self.assertRaises(AssertionError):
            splitter.prune_smd(weighted.replace('2 0.75 0 0.25', '1 0.75 0 0.25'), lambda n: n.startswith('nozzle'))


if __name__ == '__main__':
    unittest.main()
