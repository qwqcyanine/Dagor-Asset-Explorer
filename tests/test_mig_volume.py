import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'res/experimental/mig29_volume'
spec = importlib.util.spec_from_file_location('mig_volume_install', SOURCE / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class MigVolumeInstallTests(unittest.TestCase):
    def test_patch_removes_old_renderer_and_preserves_heat_and_controls(self):
        original = '''prefix
    local volumeMat = CreateMaterial(old)
    local volumeMesh
    local function BuildVolume() end
    -- shortcut: WT's jet distortion
    local HEAT = true
                volumeMesh = volumeMesh or BuildVolume()
                volumeMesh:Draw()
                render.SetBlend( 1 )
        BaseClass.OnActivateMisc( self )
        KEEP_NOZZLE_AND_SOUND_CONTROLS()
'''
        patched = installer.patch_entity(original)
        self.assertNotIn('BuildVolume', patched)
        self.assertNotIn('volumeMesh', patched)
        self.assertIn('drawWTVolume(p0, self:GetAngles(), flame)', patched)
        self.assertIn('local HEAT = true', patched)
        self.assertIn('KEEP_NOZZLE_AND_SOUND_CONTROLS()', patched)
        self.assertIn('AddCSLuaFile', patched)
        self.assertIn('SetRenderBounds', patched)
        self.assertEqual(installer.patch_entity(patched), patched)

    def test_exhaust_upgrade_removes_legacy_glow_and_refraction(self):
        original = '''local drawWTVolume = include("wt_mig29_volume/volume.lua")
    -- shortcut: WT's jet distortion
    local HEAT = CreateMaterial("old", "Refract", {})
    function ENT:DrawTranslucent() OLD_GLOW() end
    -- thrust -> p_nozzle
    KEEP_NOZZLE_AND_SOUND_CONTROLS()
'''
        patched = installer.patch_exhaust(original)
        self.assertNotIn('OLD_GLOW', patched)
        self.assertNotIn('Refract', patched)
        self.assertIn('exhaust.Nozzle', patched)
        self.assertIn('exhaust.Heat', patched)
        self.assertIn('UpdateScreenEffectTexture', patched)
        self.assertIn('KEEP_NOZZLE_AND_SOUND_CONTROLS', patched)
        self.assertEqual(installer.patch_exhaust(patched), patched)
        with self.assertRaises(ValueError):
            installer.patch_exhaust('unknown layout')

    def test_unknown_entity_layout_fails_without_silent_partial_patch(self):
        with self.assertRaises(ValueError):
            installer.patch_entity('unrecognized entity')


if __name__ == '__main__':
    unittest.main()
