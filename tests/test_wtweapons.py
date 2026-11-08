import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/dae'))
from util.wtweapons import ammoCount, reloadTime, compileMissiles, missileLua


class WeaponTest(unittest.TestCase):
    def test_native_ammo_and_arcade_reload_precedence(self):
        gameplay = {'common': {'cannonReloadCooldownTime': 60, 'rocketReloadCooldownTime': 60},
                    'typeFighter': {'rocketReloadCooldownTime': 200},
                    'reloadCooldownTimeByCaliber': {'time': [[0.02, 40], [0.03, 60]]}}
        gun = {'bullets': 250, 'trigger': 'cannon', 'weaponBlk': {'bullets': 150, 'shotFreq': 30, 'bullet': {'caliber': .02}}}
        self.assertEqual(ammoCount(gun), 250)
        self.assertEqual(reloadTime({}, gun, gameplay), 40)
        missile = {'trigger': 'aam', 'bullets': 1, 'weaponBlk': {'shotFreq': 1000.25}}
        self.assertEqual(reloadTime({'type': 'typeFighter'}, missile, gameplay), 200)
        self.assertEqual(reloadTime({}, missile, gameplay), 60)
        for value in (None, 0, -1, 2.5, float('inf'), 65536):
            with self.assertRaises(ValueError):
                ammoCount({'bullets': value})
        with self.assertRaises(ValueError):
            reloadTime({}, missile, {})

    def test_reload_overrides_validate_and_emit_bombs(self):
        for bad in ({'gun': -1}, {'missile': float('nan')}, {'bomb': 4000}, {'typo': 3}):
            with self.assertRaises(ValueError):
                missileLua([], bad)
        bomb = {'weapon': {'blk': 'bomb', 'weaponBlk': {'bomb': {'mass': 200, 'explosiveMass': 100}}, 'arcadeReload': 60}}
        code = missileLua([bomb], {'bomb': 5, 'gun': 10})
        self.assertIn('"bomb": 5', code)
        self.assertIn('ents.Create("glide_projectile")', code)
        self.assertIn('missile.velocity = vehicle:GetVelocity()', code)
        self.assertIn('if self.WTTriggerHeld then return end', code)
        self.assertIn('weapon.ReloadDelay = reload_times.gun or weapon.ReloadDelay', code)

    def test_external_gun_pods_stay_independently_selectable(self):
        from util.glide import aircraftGuns
        node = SimpleNamespace(wtm=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
        guns = [{'trigger': 'additional gun', 'emitter': str(i), 'blk': 'pod', 'bullets': 260,
                 'arcadeReload': 60, 'weaponBlk': {'shotFreq': 50}} for i in range(2)]
        with patch('util.glide.aircraftWeapons', return_value=guns):
            result = aircraftGuns(SimpleNamespace(getNodeByName=lambda n: node), {})
        self.assertEqual([w[4]['bullets'] for w in result], [260, 260])
        self.assertEqual([w[2] for w in result], [.02, .02])

    def test_grouped_guns_sum_aircraft_ammo_not_weapon_default(self):
        from util.glide import aircraftGuns
        node = SimpleNamespace(wtm=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
        skeleton = SimpleNamespace(getNodeByName=lambda name: node)
        guns = [{'trigger': 'cannon', 'blk': 'gun', 'bullets': count, 'arcadeReload': 60,
                 'weaponBlk': {'bullets': 999, 'shotFreq': 30}} for count in (125, 125)]
        with patch('util.glide.aircraftWeapons', return_value=guns):
            result = aircraftGuns(skeleton, {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][4]['bullets'], 250)
        self.assertEqual(len(result[0][1]), 2)
        self.assertEqual(guns[0]['bullets'], 125)
        self.assertAlmostEqual(result[0][2], 1 / 60)
        with patch('util.glide.aircraftWeapons', return_value=guns):
            with self.assertRaisesRegex(ValueError, 'Missing aircraft gun emitter'):
                aircraftGuns(SimpleNamespace(getNodeByName=lambda name: None), {})

    def test_bodygroups_merge_chunks_and_projectile_preserves_winding(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            header = 'version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\n'
            faces = 'metal\n0 10 30 -20 0 1 0 0 0 1 0 1\n0 11 30 -20 0 1 0 1 0 1 0 1\n0 10 31 -20 0 1 0 0 1 1 0 1\n'
            qc = root / 'body.qc'
            qc.write_text('$modelname "wt_glide/jet.mdl"\n$cdmaterials "models/jet"\n$body studio "fuse.smd"\n' +
                          '\n'.join(f'$body studio "loadout_0_1_test_@root_{i}.smd"' for i in range(2)) +
                          '\n$body studio "pylon.smd"\n$sequence idle "idle.smd"\n')
            for i in range(2):
                (root / f'loadout_0_1_test_@root_{i}.smd').write_text(header + 'triangles\n' + faces + 'end\n')
            mount = {'prefix': 'loadout_0_1_test', 'pos': [10, 20, 30], 'weapon': {}}
            targets = compileMissiles(qc, [mount])
            text = qc.read_text()
            self.assertEqual(text.count('$bodygroup'), 1)
            self.assertIn('$body studio "pylon.smd"', text)
            self.assertEqual((root / 'loadout_0_1_test.smd').read_text().count('metal\n'), 2)
            projectile = targets[0][0].with_suffix('.smd').read_text()
            self.assertEqual(projectile.count('metal\n'), 2)
            self.assertIn('0 0.000000 0.000000 0.000000 0 1 0 0 0', projectile)
            self.assertIn('0 1.000000 0.000000 0.000000 0 1 0 1 0', projectile)
            self.assertEqual(mount['model'], 'models/wt_glide/jet_loadout_0_1_test.mdl')
            with self.assertRaisesRegex(ValueError, 'Missing missile geometry'):
                compileMissiles(qc, [mount])

    def test_pod_rounds_compile_outside_airframe_and_sync_visibility(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            qc = root / 'body.qc'
            qc.write_text('$modelname "test/jet.mdl"\n$cdmaterials "models/test"\n'
                          '$body studio "loadout_rocket_root.smd"\n$body studio "loadout_pod_root.smd"\n$sequence idle "idle.smd"\n')
            (root / 'loadout_rocket_root.smd').write_text(
                'version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n'
                'metal\n0 1 2 3 0 1 0 0 0\n0 2 2 3 0 1 0 1 0\n0 1 3 3 0 1 0 0 1\nend\n')
            mount = {'prefix': 'loadout_rocket', 'pos': [1, 2, 3],
                     'weapon': {'trigger': 'rockets', 'blk': 'rocket', 'weaponBlk': {'rocket': {}}}}
            (root / 'loadout_pod_root.smd').write_text((root / 'loadout_rocket_root.smd').read_text())
            pod = {'prefix': 'loadout_pod', 'pos': [1, 2, 3], 'mesh': 'pod'}
            targets = compileMissiles(qc, [mount, pod])
            self.assertTrue(mount['external'])
            self.assertTrue(pod['external'])
            self.assertNotIn('$body', qc.read_text())
            self.assertEqual(len(targets), 2)
            self.assertIn('metal\n', targets[0][0].with_suffix('.smd').read_text())
            mount['container'] = pod['prefix']
            code = missileLua([mount, pod])
            self.assertIn('round.container == mount.container', code)
            self.assertIn('vehicle:SetNW2Bool(mount.container, true)', code)
            self.assertIn('self.Vehicle:SetNW2Bool(mount.container, false)', code)
            self.assertIn('self.wtDroppedPods', code)
            self.assertIn('pod.Model:Remove()', code)
            with self.assertRaisesRegex(ValueError, 'independent shell'):
                missileLua([mount])
            self.assertIn(pod['model'], code)
            self.assertIn('ClientsideModel(mount.model', code)
            self.assertIn('self:GetNW2Bool(mount.prefix, false)', code)
            self.assertIn('vehicle:SetNW2Bool(mount.prefix, true)', code)
            self.assertIn('self.Vehicle:SetNW2Bool(mount.prefix, false)', code)
            self.assertIn('if IsValid(model) then model:Remove() end', code)

    def test_launcher_aliases_share_projectile_group(self):
        import json
        import re
        mounts = [{'weapon': {'trigger': 'aam', 'blk': name, 'weaponBlk': {'rocket': {'bulletName': 'pl8b'}}}}
                  for name in ('cn_pl8b_default.blk', 'cn_pl8b.blk')]
        lua = missileLua(mounts)
        groups = json.loads(re.search(r'local missile_groups = util.JSONToTable\(\[==\[(.*?)\]==\]\)', lua)[1])
        self.assertEqual([len(g) for g in groups], [2])

    def test_runtime_uses_single_mount_and_restores_only_own_group(self):
        mount = {'weapon': {'blk': 'launcher', 'weaponBlk': {'rocket': {'bulletName': 'test'}}}}
        lua = missileLua([mount, mount])
        self.assertIn('local mount = self.WTMounts[index]', lua)
        self.assertIn('if not IsValid(missile) then return end', lua)
        self.assertIn('vehicle:FindBodygroupByName(mount.prefix), 1', lua)
        self.assertIn('for _, mount in ipairs(self.WTMounts)', lua)
        self.assertIn('self.projectileOffsetIndex = 0', lua)
        self.assertIn('index ~= self.weaponState.index', lua)


if __name__ == '__main__':
    unittest.main()
