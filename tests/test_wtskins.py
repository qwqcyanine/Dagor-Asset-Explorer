import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/dae'))
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
import zipfile
from PIL import Image
from parse.material import MaterialData, TexturePathDict
from util.wtskins import SkinArchive, importSkins, replacements


class SkinTests(unittest.TestCase):
    def archive(self, root, manifest=None):
        p = root / 'custom.zip'
        image = BytesIO()
        Image.new('RGBA', (4, 4), (10, 20, 30, 40)).save(image, format='DDS')
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('Skin/air.blk', manifest or 'name:t="user"\nreplace_tex{from:t="air_c*" to:t="color.dds"}\nreplace_tex{from:t="air_n*" to:t="normal.dds"}')
            z.writestr('Skin/color.dds', image.getvalue())
            z.writestr('Skin/normal.dds', image.getvalue())
        return p

    def test_rejects_unsafe_ambiguous_and_unsupported_archives(self):
        for text in ('set_tex{from:t="x" to:t="y"}', 'replace_tex{from:t="x"}', 'name:t="user"', 'include "a.blk"'):
            with self.assertRaises(ValueError):
                replacements(text)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for target in ('../escape.dds', '/absolute.dds', 'C:/test.dds', 'absent.dds'):
                p = self.archive(root, f'replace_tex{{from:t="air_c*" to:t="{target}"}}')
                with self.assertRaises(ValueError):
                    SkinArchive(p)
            p = self.archive(root)
            with zipfile.ZipFile(p, 'a') as z:
                z.writestr('other.blk', 'name:t="user"')
            with self.assertRaises(ValueError):
                SkinArchive(p)

    def test_multi_model_archive_selects_exact_manifest_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.archive(Path(d))
            with zipfile.ZipFile(p, 'a') as z:
                z.writestr('Skin/other.blk', 'set_tex{from:t="other_c*" to:t="missing.dds"}')
            skin = SkinArchive(p, 'AIR')
            self.assertEqual(skin.manifest, 'Skin/air.blk')
            self.assertEqual(len(skin.rules), 2)
            for model in (None, 'air_other', 'missing'):
                with self.assertRaisesRegex(ValueError, 'Cannot uniquely select'):
                    SkinArchive(p, model)
            with zipfile.ZipFile(p, 'a') as z:
                z.writestr('second/air.blk', 'name:t="user"')
            with self.assertRaisesRegex(ValueError, 'Cannot uniquely select'):
                SkinArchive(p, 'air')

    def test_gui_selects_manifest_and_preserves_archive_path(self):
        from PyQt5.QtWidgets import QApplication
        from gui.glideOptionsDialog import GlideOptionsDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            p = self.archive(Path(d))
            with zipfile.ZipFile(p, 'a') as z:
                z.writestr('other.blk', 'name:t="user"')
            dialog = GlideOptionsDialog(None, {'aircraft': True}, 'air')
            with patch('gui.skinImportWidget.QFileDialog.getOpenFileNames', return_value=([str(p)], '')):
                dialog.skins.addSkins()
                dialog.skins.addSkins()
            self.assertEqual(dialog.options()['skins'], [str(p)])
            self.assertIn('Skin/air.blk', dialog.skins.files.item(0).text())
            dialog.close()

    def test_qc_families_and_native_channel_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = self.archive(root)
            with zipfile.ZipFile(archive, 'a') as z:
                z.writestr('other.blk', 'name:t="user"')
            qc = root / 'air.qc'
            qc.write_text('$cdmaterials "models/test/air"\n')
            mat = MaterialData()
            mat.cls = 'dynamic_masked_chrome_bump'
            mat.par = ''
            mat.addTexSlot('t0', 'air_c*')
            mat.addTexSlot('t2', 'air_n*')
            paths = TexturePathDict('test')
            original = mat.getVMT(paths)
            converted = []
            def convert(args, **kw):
                p = Path(args[args.index('-file') + 1])
                with Image.open(p) as img:
                    converted.append(img.convert('RGBA').getpixel((0, 0)))
                p.with_suffix('.vtf').write_bytes(b'test')
            with patch('util.wtskins.subprocess.run', side_effect=convert):
                report = importSkins(qc, [mat], paths, [archive], 'converter')
            self.assertIn((10, 20, 30, 215), converted)
            self.assertIn((40, 20, 255, 10), converted)
            self.assertEqual(report[0]['skin'], 1)
            self.assertEqual(report[0]['blk'], 'Skin/air.blk')
            self.assertEqual(report[0]['unused'], [])
            self.assertEqual(qc.read_text().count('$texturegroup'), 1)
            self.assertIn('{ "' + mat.getName() + '" }', qc.read_text())
            self.assertEqual(mat.getVMT(paths), original)
            vmt = next((root / 'source_export').rglob('*.vmt')).read_text()
            self.assertIn('/skins/1_', vmt)
            with self.assertRaises(ValueError):
                importSkins(qc, [mat], paths, [archive], 'converter')

    def test_conversion_failure_does_not_write_qc(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = self.archive(root)
            qc = root / 'air.qc'
            original = '$cdmaterials "models/test/air"\n'
            qc.write_text(original)
            m = MaterialData()
            m.cls, m.par = 'dynamic_masked_chrome_bump', ''
            m.addTexSlot('t0', 'air_c*')
            with patch('util.wtskins.subprocess.run', side_effect=OSError('failed')):
                with self.assertRaises(OSError):
                    importSkins(qc, [m], TexturePathDict('test'), [archive], 'converter')
            self.assertEqual(qc.read_text(), original)

    def test_gui_keeps_skin_selection_for_all_vehicle_types(self):
        from PyQt5.QtWidgets import QApplication
        from gui.glideOptionsDialog import GlideOptionsDialog
        app = QApplication.instance() or QApplication([])
        dialog = GlideOptionsDialog(None, {'aircraft': True})
        dialog.skins.files.addItem('example.zip')
        for i in range(3):
            dialog.vehicleType.setCurrentIndex(i)
            self.assertEqual(dialog.options()['skins'], ['example.zip'])
        dialog.skins.files.setCurrentRow(0)
        dialog.skins.removeSkin()
        self.assertEqual(dialog.options()['skins'], [])
        dialog.close()


if __name__ == '__main__':
    unittest.main()
