import csv
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'dae'))
from util.wtloadout import presetLabel, weaponLabels


class WeaponLabelsTest(unittest.TestCase):
    def labels(self, language='zh_CN'):
        data = io.StringIO()
        writer = csv.writer(data, delimiter=';')
        writer.writerows([
            ['<ID|readonly|noverify>', '<English>', '<Chinese>'],
            ['weapons/cn_pl8b', 'PL-8B air-to-air missiles', '霹\u200b雳-8B 空\u200b对空导弹'],
            ['weapons/cn_pl8b/short', 'PL-8B', '霹\u200b雳-8B'],
            ['weapons/bomb', '250 kg bomb; HE', ''],
            ['weapons/cannon', '23 mm cannon', '23 毫米机炮'],
            ['modification/pod', 'SPPU-22 gun pod', 'SPPU-22 吊舱'],
        ])
        with patch('util.vromfs.VROMFS') as vfs:
            vfs.return_value.files = {'lang/units_weaponry.csv': None}
            vfs.return_value.read.return_value = data.getvalue().encode('utf-8-sig')
            return weaponLabels('game', language)

    def test_native_csv_language_and_fallback(self):
        labels = self.labels()
        self.assertEqual(labels['weapons/cn_pl8b'], '霹雳-8B 空对空导弹')
        self.assertEqual(labels['weapons/bomb'], '250 kg bomb; HE')
        self.assertEqual(self.labels('en')['weapons/cn_pl8b'], 'PL-8B air-to-air missiles')
        with patch('util.vromfs.VROMFS', side_effect=FileNotFoundError):
            self.assertEqual(weaponLabels('game', 'zh_CN'), {})
        self.assertEqual(weaponLabels(None, 'zh_CN'), {})

    def test_container_uses_native_child_name_and_capacity(self):
        csv_data = b'"<ID>";"<English>";"<Chinese>"\n"weapons/rocket";"S-13OF rockets";""\n'
        preset = {'name': 'pod_slot', 'Weapon': {'blk': 'gameData/Weapons/containers/pod.blk'}}
        with patch('util.vromfs.VROMFS') as vfs:
            vfs.return_value.files = {'lang/units_weaponry.csv': None}
            vfs.return_value.read.return_value = csv_data
            vfs.return_value.readBlk.return_value = {'blk': 'rocket.blk', 'bullets': 5}
            labels = weaponLabels('game', 'en', [(3, [('pod_slot', preset)])])
        label = presetLabel(preset, labels)[0]
        self.assertIn('5 × S-13OF rockets', label)
        self.assertNotIn('pod_slot', label)

    def test_labels_counts_and_internal_tooltip(self):
        w = {'blk': 'gameData\\Weapons\\rocketGuns\\cn_pl8b.blk', 'trigger': 'aam', 'bullets': 1}
        preset = {'name': 'pl8b_slot3', 'Weapon': [w, dict(w), {'dummy': True}]}
        label, tooltip = presetLabel(preset, self.labels())
        self.assertEqual(label, '2 × PL-8B 空对空导弹')
        self.assertIn('pl8b_slot3', tooltip)
        self.assertIn('cn_pl8b.blk', tooltip)
        self.assertIn('霹雳-8B 空对空导弹', tooltip)
        self.assertEqual(preset['Weapon'][0]['bullets'], 1)
        self.assertIn('cn_pl8b', presetLabel(preset, {})[0])
        self.assertEqual(presetLabel({'name': 'unknown'}, {})[0], 'unknown')
        preset['Weapon'] = {'blk': 'bomb.blk', 'bullets': 6}
        self.assertEqual(presetLabel(preset, self.labels())[0], '6 × 250 kg bomb; HE')
        preset.update(reqModification='pod', Weapon={'blk': 'cannon.blk', 'trigger': 'additional gun', 'bullets': 260})
        self.assertEqual(presetLabel(preset, self.labels())[0], 'SPPU-22 吊舱 (23 毫米机炮)')

    def test_exported_hud_names_follow_weapon_slots_without_ammo_counts(self):
        import json
        import re
        from copy import deepcopy
        from util.wtweapons import missileLua
        guns = [{'blk': 'cannon.blk', 'bullets': 150},
                {'blk': 'cannon.blk', 'trigger': 'additional gun', 'bullets': 260}]
        mounts = [{'weapon': {'blk': name + '.blk', 'trigger': 'aam', 'bullets': 1,
                             'weaponBlk': {'rocket': {'bulletName': projectile}}}}
                  for name, projectile in [('cn_pl8b', 'pl8b'), ('cn_pl8b_default', 'pl8b'), ('cn_pl12a', 'pl12a')]]
        mounts += [{'weapon': {'blk': 'bomb.blk', 'trigger': 'bombs', 'bullets': 1,
                                'weaponBlk': {'bomb': {'bulletName': 'bomb'}}}}]
        labels = self.labels() | {'weapons/cn_pl12a': 'PL-12A 空对空导弹'}
        original = deepcopy((guns, mounts))
        code = missileLua(mounts, guns=guns, labels=labels)
        info = json.loads(re.search(r'ENT.WeaponInfo = util.JSONToTable\(\[==\[(.*?)\]==\]\)', code)[1])
        self.assertEqual([w['name'] for w in info],
                         ['23 毫米机炮', '23 毫米机炮', 'PL-8B 空对空导弹', 'PL-12A 空对空导弹', '250 kg bomb; HE'])
        self.assertLess(code.index('ENT.WeaponInfo'), code.index('if SERVER then'))
        self.assertEqual((guns, mounts), original)
        unnamed = missileLua(mounts)
        self.assertEqual(code[code.index('if SERVER then'):], unnamed[unnamed.index('if SERVER then'):])

    def test_hud_name_fallback_and_lua_delimiter_are_safe(self):
        import json
        import re
        from util.wtweapons import missileLua
        guns = [{'blk': 'unknown.blk'}, {'blk': 'quoted.blk'}]
        label = '炮 "A" \\ test\n]==]'
        code = missileLua([], guns=guns, labels={'weapons/quoted': label})
        info = json.loads(re.search(r'ENT.WeaponInfo = util.JSONToTable\(\[==\[(.*?)\]==\]\)', code)[1])
        self.assertEqual([w['name'] for w in info], ['unknown', label])

    def test_write_addon_connects_native_labels_to_client_metadata(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from util.glide import writeAddon
        gun = {'blk': 'cannon.blk', 'bullets': 150}
        with TemporaryDirectory() as folder, \
                patch('util.glide.generateAircraftLua', return_value='-- aircraft\n'), \
                patch('util.glide.exportAircraftSounds', return_value={}), \
                patch('util.glide.aircraftGuns', return_value=[('base', [], .1, 10, gun)]), \
                patch('util.wtloadout.weaponLabels', return_value=self.labels()) as native:
            writeAddon(folder, 'wt_test', 'test', 'test.mdl', None, {'fm': {}}, gameRoot='game')
            native.assert_called_once()
            code = (Path(folder) / 'lua/entities/wt_test.lua').read_text(encoding='utf-8')
            self.assertIn('ENT.WeaponInfo = util.JSONToTable', code)
            self.assertIn('23 ', code)

    def test_gui_localizes_without_changing_selection(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication
        from gui.glideOptionsDialog import GlideOptionsDialog
        app = QApplication.instance() or QApplication([])
        preset = {'name': 'pl8b_slot3', 'Weapon': {'blk': 'cn_pl8b.blk', 'trigger': 'aam'}}
        dialog = GlideOptionsDialog(None, {'aircraft': True}, slots=[(3, [('pl8b_slot3', preset)])], weaponLabels=self.labels())
        combo = dialog.slotCombos[3]
        self.assertEqual(combo.itemText(1), 'PL-8B 空对空导弹')
        self.assertIn('pl8b_slot3', combo.itemData(1, Qt.ToolTipRole))
        dialog.loadout.setCurrentIndex(dialog.loadout.findData('__custom__'))
        combo.setCurrentIndex(1)
        self.assertEqual(dialog.options()['loadout'], {3: 'pl8b_slot3'})
        dialog.close()


if __name__ == '__main__':
    unittest.main()
