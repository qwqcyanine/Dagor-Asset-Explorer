import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/dae'))
from util.wtloadout import resolve, mounts, mountedModel, hiddenNodes
from parse.realres import Model
from parse.material import MaterialData


class LoadoutTest(unittest.TestCase):
	def fixture(self):
		preset = {'name': 'same', 'ShowNodes': {'node': 'rack'}, 'Weapon': {'blk': 'weapon', 'emitter': 'mount', 'bullets': 1}}
		blk = {'weapon_presets': {'preset': {'name': 'test', 'blk': 'preset'}},
			'WeaponSlots': {'HideNodes': {'node': ['rack', 'unused']}, 'WeaponSlot': [
				{'index': i, 'WeaponPreset': preset} for i in (1, 12)]}}
		data = {'preset': {'Weapon': [{'slot': i, 'preset': 'same'} for i in (1, 12)]}, 'weapon': {'mesh': 'missile'}}
		return blk, data, SimpleNamespace(readBlk=lambda p: data[p])

	def test_slot_local_presets_visibility_and_failures(self):
		blk, data, vfs = self.fixture()
		selected = resolve(blk, 'preset', vfs)
		self.assertEqual([s for s, _ in selected], [1, 12])
		self.assertEqual(hiddenNodes(blk, selected, ['flare1']), {'unused', 'flare1'})
		selected[0][1]['ShowNodes']['node'] = ['pylon', 'flare1']
		self.assertIn('flare1', hiddenNodes(blk, selected, ['flare1']))
		node = object()
		self.assertEqual(len(mounts(selected, SimpleNamespace(getNodeByName=lambda n: node), vfs)), 2)
		with self.assertRaisesRegex(ValueError, 'missing emitter'):
			mounts(selected, SimpleNamespace(getNodeByName=lambda n: None), vfs)
		data['weapon']['mesh'] = 'empty_mesh'
		self.assertEqual(mounts(selected, None, vfs), [])
		data['preset']['Weapon'].append({'slot': 1, 'preset': 'same'})
		with self.assertRaisesRegex(ValueError, 'Duplicate'):
			resolve(blk, 'preset', vfs)
		with self.assertRaisesRegex(ValueError, 'Unknown'):
			resolve(blk, 'foreign', vfs)

	def test_full_transform_bone_binding_and_material_isolation(self):
		mat = MaterialData(); mat.setName('metal')
		source = Model('missile', materials=(mat,))
		source.appendVerts([(1, 0, 0), (0, 1, 0), (0, 0, 0)], [(0, 0)] * 3, scale=False)
		obj = source.newObject('@root'); obj.appendMaterial('metal'); obj.appendFace((0, 1, 2))
		node = SimpleNamespace(idx=7, wtm=((0,-1,0,10),(1,0,0,20),(0,0,1,30),(0,0,0,1)))
		out = mountedModel(source, node, 'mounted')
		self.assertEqual(tuple(out.getVertex(0)), (10, 21, 30))
		self.assertEqual(out.skin[0], ((7, 1.0),))
		self.assertEqual(out[0].materials[0], 'loadout_missile_metal')
		self.assertEqual(mat.getName(), 'metal')
		self.assertEqual(tuple(source.getVertex(0)), (1, 0, 0))

	def test_baked_reflections_preserve_outward_faces(self):
		import numpy as np
		for emitter_sign, parent_sign in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
			with self.subTest(emitter=emitter_sign, parent=parent_sign):
				parent_matrix = np.diag([1., 1., parent_sign, 1.])
				emitter_matrix = np.array([[0., -1., 0., 10.], [1., 0., 0., 20.],
					[0., 0., emitter_sign, 30.], [0., 0., 0., 1.]])
				parent = SimpleNamespace(wtm=parent_matrix)
				source = Model('missile', skeleton=SimpleNamespace(getNodeByName=lambda name: parent))
				source.appendVerts([(0, 0, 0), (1, 0, 0), (0, 1, 0)],
					[(0, 0), (1, 0), (0, 1)], scale=False)
				obj = source.newObject('@root'); obj.appendFace((0, 1, 2))
				node = SimpleNamespace(idx=7, wtm=emitter_matrix)
				out = mountedModel(source, node, 'mounted')
				face = out[0].faces[0]
				vertices = [np.asarray(out.getVertex(i)) for i in face]
				normal = np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])
				linear = emitter_matrix[:3, :3] @ parent_matrix[:3, :3]
				expected = np.linalg.inv(linear).T @ np.array([0., 0., 1.])
				self.assertGreater(float(normal @ expected), 0)
				self.assertEqual(face, (2, 1, 0) if emitter_sign * parent_sign < 0 else (0, 1, 2))
				self.assertEqual(obj.faces[0], (0, 1, 2))
				for i in face:
					self.assertEqual(out.getUV(i), source.getUV(i))
					self.assertEqual(out.skin[i], ((7, 1.0),))

	def test_missing_weapon_textures_fail_explicitly(self):
		from tempfile import TemporaryDirectory
		from unittest.mock import patch
		from util.wtloadout import cacheTextures
		mat = MaterialData(); mat.addTexSlot('t0', 'missing_missile_c*')
		with TemporaryDirectory() as root, patch('util.assetcacher.AssetCacher.getCachedAsset', return_value=None), patch('util.glide.cacheHQTextures'):
			with self.assertRaisesRegex(ValueError, 'missing_missile_c'):
				cacheTextures(root, [SimpleNamespace(materials=[mat])])

	def test_apply_retains_per_mount_ammo_and_native_reload(self):
		from unittest.mock import patch
		from util.wtloadout import apply
		blk, data, _ = self.fixture()
		blk['type'] = 'typeFighter'
		data['config/gameplay.blk'] = {'typeFighter': {'rocketReloadCooldownTime': 200}}
		data['weapon'].update(shotFreq=1000.25, rocket={'bulletName': 'test', 'timeLife': 20, 'mass': 121, 'force': 37675, 'endSpeed': 2000, 'startSpeed': 0})
		blk['WeaponSlots']['WeaponSlot'][0]['WeaponPreset']['Weapon']['trigger'] = 'aam'
		node = SimpleNamespace(name='mount', idx=0, wtm=[[1,0,0,10],[0,1,0,20],[0,0,1,30],[0,0,0,1]])
		model = Model('plane', skeleton=SimpleNamespace(getNodeByName=lambda n: node))
		keep = set()
		with patch('util.vromfs.VROMFS') as vfs, patch('util.wtloadout.loadModels', return_value={'missile': Model('missile')}):
			vfs.return_value.readBlk.side_effect = lambda p: data[p]
			report = apply(model, blk, 'preset', 'game', keep)
			self.assertEqual(len(report), 2)
			self.assertNotEqual(report[0]['prefix'], report[1]['prefix'])
			self.assertEqual(report[0]['pos'], (400, 1200, 800))
			self.assertEqual(report[0]['weapon']['bullets'], 1)
			self.assertEqual(report[0]['weapon']['arcadeReload'], 200)
			self.assertEqual(keep, {'mount'})
			rocket = data['weapon']['rocket']
			del rocket['timeLife']
			rocket['maxDistance'] = 8000
			with self.assertRaisesRegex(ValueError, 'Unsupported missile flight data'):
				apply(model, blk, 'preset', 'game', keep)
			blk['WeaponSlots']['WeaponSlot'][0]['WeaponPreset']['Weapon']['trigger'] = 'rockets'
			self.assertEqual(len(apply(model, blk, 'preset', 'game', keep)), 2)
			rocket['maxDistance'] = 0
			with self.assertRaisesRegex(ValueError, 'Unsupported missile flight data'):
				apply(model, blk, 'preset', 'game', keep)
			rocket['maxDistance'] = 8000
			data['weapon']['rocket']['startSpeed'] = float('nan')
			with self.assertRaisesRegex(ValueError, 'Unsupported missile flight data'):
				apply(model, blk, 'preset', 'game', keep)

	def test_container_rounds_compose_native_transforms_and_validate(self):
		import numpy as np
		from util.wtloadout import containerRounds
		definition = dict(bullets=2, useEmitter=True, emitterGenRange=[1, 2], emitterGenFmt='tube%02d', blk='rocket')
		nodes = {f'tube{i:02d}': SimpleNamespace(wtm=np.eye(4)) for i in (1, 2)}
		nodes['tube02'].wtm[2, 3] = 2
		pod = SimpleNamespace(skeleton=SimpleNamespace(getNodeByName=nodes.get))
		mount = SimpleNamespace(idx=7, name='mount', wtm=np.diag([1., 1., -1., 1.]))
		vfs = SimpleNamespace(readBlk=lambda _: dict(mesh='round', rocket={'mass': 10}))
		child, rounds = containerRounds(definition, pod, mount, vfs)
		self.assertEqual(len(rounds), 2)
		self.assertEqual(rounds[1][1].wtm[2, 3], -2)
		self.assertEqual(rounds[1][1].idx, 7)
		del nodes['tube02']
		with self.assertRaisesRegex(ValueError, 'Missing container emitter'):
			containerRounds(definition, pod, mount, vfs)
		with self.assertRaisesRegex(ValueError, 'layout'):
			containerRounds(dict(definition, bullets=3), pod, mount, vfs)

	def test_custom_slots_validate_names_and_allow_empty(self):
		blk, data, vfs = self.fixture()
		self.assertEqual([i for i, _ in resolve(blk, {1: 'same', 12: ''}, vfs)], [1])
		with self.assertRaises(ValueError):
			resolve(blk, {99: 'same'}, vfs)
		with self.assertRaises(ValueError):
			resolve(blk, {1: 'not-native'}, vfs)

	def test_bomb_and_gun_pod_metadata(self):
		from unittest.mock import patch
		from util.wtloadout import apply
		blk, data, _ = self.fixture()
		data['config/gameplay.blk'] = {'common': {'bombReloadCooldownTime': 60, 'cannonReloadCooldownTime': 60}}
		node = SimpleNamespace(name='mount', idx=0, wtm=[[1,0,0,10],[0,1,0,20],[0,0,1,30],[0,0,0,1]])
		model = Model('plane', skeleton=SimpleNamespace(getNodeByName=lambda n: node))
		w = blk['WeaponSlots']['WeaponSlot'][0]['WeaponPreset']['Weapon']
		w['trigger'] = 'bombs'
		data['weapon'].update(shotFreq=10, bomb={'mass': 216.5, 'explosiveMass': 100})
		with patch('util.vromfs.VROMFS') as vfs, patch('util.wtloadout.loadModels', return_value={'missile': Model('missile')}):
			vfs.return_value.readBlk.side_effect = lambda p: data[p]
			self.assertEqual(apply(model, blk, {1: 'same'}, 'game', set())[0]['weapon']['arcadeReload'], 60)
			w.update(trigger='additional gun', bullets=260)
			data['weapon'] = {'cannon': True, 'shotFreq': 50}
			keep = set()
			report = apply(model, blk, {1: 'same'}, 'game', keep)
			self.assertEqual(report[0]['gun']['bullets'], 260)
			self.assertEqual(keep, {'mount'})

	def test_gui_preserves_default_and_returns_selected_path(self):
		from PyQt5.QtWidgets import QApplication
		from gui.glideOptionsDialog import GlideOptionsDialog
		app = QApplication.instance() or QApplication([])
		dialog = GlideOptionsDialog(None, {'aircraft': True}, 'test', [('Native', 'preset')])
		self.assertEqual(dialog.options()['loadout'], '')
		dialog.loadout.setCurrentIndex(1)
		self.assertEqual(dialog.options()['loadout'], 'preset')
		dialog.close()
		from util.wtloadout import slotChoices
		blk, _, _ = self.fixture()
		calls = []
		dialog = GlideOptionsDialog(None, {'aircraft': True}, 'test', slots=slotChoices(blk), preview=calls.append)
		dialog.loadout.setCurrentIndex(dialog.loadout.findData('__custom__'))
		dialog.slotCombos[1].setCurrentIndex(1)
		dialog.reloadSpins['missile'].setValue(12.5)
		dialog.previewButton.click()
		self.assertEqual(calls[0]['loadout'], {1: 'same', 12: ''})
		self.assertEqual(calls[0]['reloadTimes'], {'missile': 12.5})
		dialog.close()


if __name__ == '__main__':
	unittest.main()
