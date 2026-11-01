"""Run with: python -m unittest discover -s tests"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "dae"))
from gui import customtreeview as tree


class ReachedModelGeneration(Exception):
    pass


class SourceExportPathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.compiler = Path(self.tmp.name) / "CE compiler.exe"
        self.compiler.touch()
        self.gameinfo = Path(self.tmp.name) / "gameinfo.txt"
        self.gameinfo.touch()
        self.values = {
            tree.SETTINGS_STUDIOMDL_PATH: str(self.compiler),
            tree.SETTINGS_GAMEINFO_PATH: str(self.gameinfo),
            tree.SETTINGS_VTFCMD_PATH: str(self.compiler),
            tree.SETTINGS_EXPORT_SMD: True,
        }

    def export(self, exportClass=tree.ExportToSource):
        def setting(key):
            return exportClass.forcedSettings.get(key, self.values.get(key, False))

        def model_generation(status):
            raise ReachedModelGeneration()

        action = SimpleNamespace(modelPath=exportClass.modelPath,
                                 item=SimpleNamespace(asset=object()),
                                 setting=setting, setTaskStatus=model_generation)
        with patch.object(tree.SETTINGS, "getValue", side_effect=lambda key: self.values.get(key, False)):
            tree.ExportToSource.save(action, self.tmp.name)

    def test_empty_compiler_fails_before_generation_for_source_and_glide(self):
        self.values[tree.SETTINGS_STUDIOMDL_PATH] = ""
        for exporter in (tree.ExportToSource, tree.ExportToGlide):
            with self.subTest(exporter=exporter.__name__), self.assertRaisesRegex(ValueError, "StudioMDL"):
                self.export(exporter)

    def test_missing_compiler(self):
        self.compiler.unlink()
        with self.assertRaisesRegex(ValueError, "StudioMDL"):
            self.export()

    def test_missing_gameinfo(self):
        self.values[tree.SETTINGS_GAMEINFO_PATH] = ""
        with self.assertRaisesRegex(ValueError, "gameinfo.txt"):
            self.export()

    def test_converter_directory_is_not_an_executable(self):
        self.values[tree.SETTINGS_VTFCMD_PATH] = self.tmp.name
        with self.assertRaisesRegex(ValueError, "VTFCmd"):
            self.export()

    def test_custom_compiler_with_spaces_is_accepted(self):
        with self.assertRaises(ReachedModelGeneration):
            self.export()

    def test_source_only_does_not_require_tools(self):
        self.values.update({tree.SETTINGS_NO_MDL: True, tree.SETTINGS_NO_TEX_EXPORT: True,
                            tree.SETTINGS_STUDIOMDL_PATH: "", tree.SETTINGS_GAMEINFO_PATH: ""})
        with self.assertRaises(ReachedModelGeneration):
            self.export()

    def test_bundled_converter_fallback(self):
        self.values[tree.SETTINGS_VTFCMD_PATH] = ""
        with patch.object(tree, "VTFCMD_PATH", str(self.compiler)), self.assertRaises(ReachedModelGeneration):
            self.export()


if __name__ == "__main__":
    unittest.main()
