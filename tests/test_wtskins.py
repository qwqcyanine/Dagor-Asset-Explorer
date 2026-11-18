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
from util.wtskins import SkinArchive, builtinSkins, importSkins, replacements


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
            cmds = []
            def convert(args, **kw):
                cmds.append(list(args))
                p = Path(args[args.index('-file') + 1])
                with Image.open(p) as img:
                    converted.append(img.convert('RGBA').getpixel((0, 0)))
                p.with_suffix('.vtf').write_bytes(b'test')
            with patch('util.wtskins.subprocess.run', side_effect=convert):
                report = importSkins(qc, [mat], paths, [archive], 'converter')
            self.assertIn((10, 20, 30, 215), converted)
            self.assertIn((40, 20, 128, 10), converted)
            normal_cmds = [c for c in cmds if '-flag' in c]
            color_cmds = [c for c in cmds if '-flag' not in c]
            self.assertEqual(len(normal_cmds), 1)
            self.assertEqual(len(color_cmds), 1)
            self.assertIn('NORMAL', normal_cmds[0])
            self.assertIn('DXT5', normal_cmds[0])
            self.assertIn('DXT5', color_cmds[0])
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

            rgba_dir = root / 'rgba'
            rgba_dir.mkdir()
            qc_rgba = rgba_dir / 'air.qc'
            qc_rgba.write_text('$cdmaterials "models/test/air"\n')
            rgba_cmds = []
            def convert_rgba(args, **kw):
                rgba_cmds.append(list(args))
                Path(args[args.index('-file') + 1]).with_suffix('.vtf').write_bytes(b'test')
            with patch('util.wtskins.subprocess.run', side_effect=convert_rgba):
                importSkins(qc_rgba, [mat], paths, [archive], 'converter', vtfFormat='RGBA8888')
            self.assertEqual(len(rgba_cmds), 2)
            for c in rgba_cmds:
                self.assertEqual(c[c.index('-format') + 1], 'RGBA8888')
                self.assertEqual(c[c.index('-alphaformat') + 1], 'RGBA8888')

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
        import gui.settingsDialog as sd_mod
        from gui.glideOptionsDialog import GlideOptionsDialog
        from util.enums import SETTINGS_VTF_FORMAT
        app = QApplication.instance() or QApplication([])
        dialog = GlideOptionsDialog(None, {'aircraft': True})
        self.assertEqual([dialog.vtfFormat.itemData(i) for i in range(dialog.vtfFormat.count())], ['DXT5', 'RGBA8888'])
        dialog.vtfFormat.setCurrentIndex(1)
        dialog.skins.files.addItem('example.zip')
        for i in range(3):
            dialog.vehicleType.setCurrentIndex(i)
            self.assertEqual(dialog.options()['skins'], ['example.zip'])
            self.assertEqual(dialog.options()['vtfFormat'], 'RGBA8888')
        dialog.skins.files.setCurrentRow(0)
        dialog.skins.removeSkin()
        self.assertEqual(dialog.options()['skins'], [])
        dialog.close()

        with patch.object(sd_mod.SETTINGS, 'getValue', side_effect=lambda k: 'DXT5' if k == SETTINGS_VTF_FORMAT else sd_mod.SETTINGS.getSettings()[k]), \
             patch.object(sd_mod.SETTINGS, 'setValue') as set_val:
            s_dlg = sd_mod.SettingsDialog(None)
            self.assertEqual([s_dlg.vtfFormatBox.itemData(i) for i in range(s_dlg.vtfFormatBox.count())], ['DXT5', 'RGBA8888'])
            s_dlg.vtfFormatBox.setCurrentIndex(1)
            set_val.assert_called_with(SETTINGS_VTF_FORMAT, 'RGBA8888')
            s_dlg.close()

    def test_builtin_camo_skin_tex_compositing_and_detail_stripping(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            qc = root / 'ztz_99a.qc'
            qc.write_text('$cdmaterials "models/wt_glide/ztz_99a"\n')
            (root / 'textures').mkdir()
            # Base hull texture: unpainted dirt RGB=(80, 70, 60), alpha=0
            base_buf = BytesIO()
            Image.new('RGBA', (4, 4), (80, 70, 60, 0)).save(base_buf, format='DDS')
            (root / 'textures/ztz_99a_body_cm.dds').write_bytes(base_buf.getvalue())

            # Skin 1: digital camo_skin_tex with alpha=255 RGB=(40, 90, 30)
            dig_buf = BytesIO()
            Image.new('RGBA', (4, 4), (40, 90, 30, 255)).save(dig_buf, format='DDS')
            # Skin 2: noskin reset (alpha=0) + tileable camo replacement RGB=(200, 180, 120)
            noskin_buf = BytesIO()
            Image.new('RGBA', (4, 4), (123, 123, 123, 0)).save(noskin_buf, format='DDS')
            desert_buf = BytesIO()
            Image.new('RGBA', (4, 4), (200, 180, 120, 255)).save(desert_buf, format='DDS')

            mat = MaterialData()
            mat.cls, mat.par = 'dynamic_masked_tank', ''
            mat.addTexSlot('t0', 'ztz_99a_body_c*')
            mat.addTexSlot('t1', 'ussr_camo_green*')
            mat.addTexSlot('t2', 'ztz_99a_body_n*')
            paths = TexturePathDict('wt_glide')

            fake_builtins = [
                {
                    'id': 'wt:cn_ztz_99a#digital',
                    'name': 'digital',
                    'label': '数码迷彩 (digital)',
                    'blk': 'dldata/downloadable_skins.blk#cn_ztz_99a#digital',
                    'rules': [('ztz_99a_body_c*', 'dldata:dig_hash', 'camo_skin_tex')],
                },
                {
                    'id': 'wt:cn_ztz_99a#sand_green_black',
                    'name': 'sand_green_black',
                    'label': '三色沙漠迷彩 (sand_green_black)',
                    'blk': 'gamedata/units/tankmodels/cn_ztz_99a.blk#sand_green_black',
                    'rules': [
                        ('ztz_99a_body_c*', 'dxp:noskin_body_c', 'camo_skin_tex'),
                        ('ussr_camo_green*', 'dxp:cn_camo_sand_green_black', ''),
                    ],
                },
            ]
            blobs = {
                'dldata:dig_hash': dig_buf.getvalue(),
                'dxp:noskin_body_c': noskin_buf.getvalue(),
                'dxp:cn_camo_sand_green_black': desert_buf.getvalue(),
            }
            converted = []

            def convert(args, **kw):
                p = Path(args[args.index('-file') + 1])
                with Image.open(p) as img:
                    converted.append(img.convert('RGBA').getpixel((0, 0)))
                p.with_suffix('.vtf').write_bytes(b'vtf')

            with patch('util.wtskins.builtinSkins', return_value=fake_builtins), \
                 patch('util.wtskins._cacheBuiltinSkinTextures'), \
                 patch('util.wtskins._loadBuiltinTarget', side_effect=lambda gr, tgt, k: blobs[tgt]), \
                 patch('util.wtskins.subprocess.run', side_effect=convert):
                report = importSkins(qc, [mat], paths, ['wt:digital', 'wt:cn_ztz_99a#sand_green_black'], 'converter', 'ztz_99a', root)

            self.assertEqual(len(report), 2)
            self.assertEqual(report[0]['name'], 'digital')
            self.assertEqual(report[1]['name'], 'sand_green_black')
            self.assertIn((40, 90, 30, 255), converted)
            self.assertIn((200, 180, 120, 255), converted)
            vmts = sorted((root / 'source_export').rglob('*.vmt'))
            self.assertEqual(len(vmts), 2)
            vmt_digital = vmts[0].read_text()
            vmt_desert = vmts[1].read_text()
            self.assertNotIn('$detail', vmt_digital)
            self.assertIn('$detail ', vmt_desert)

    def test_camo_skin_tex_uses_t1_paint_where_skin_alpha_is_zero(self):
        from parse.material import DDSx
        from util.assetcacher import AssetCacher

        AssetCacher.clearCache()
        self.addCleanup(AssetCacher.clearCache)

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            qc = root / 'ztz_99a.qc'
            qc.write_text('$cdmaterials "models/wt_glide/ztz_99a"\n')
            (root / 'textures').mkdir()

            # Base hull (4x1): cols 0,3=painted metal alpha=160, cols 1,2=unpainted dirt alpha=0
            base_img = Image.new('RGBA', (4, 1))
            base_img.putdata([(80, 70, 60, 160), (80, 70, 60, 0), (80, 70, 60, 0), (80, 70, 60, 160)])
            base_buf = BytesIO()
            base_img.save(base_buf, format='DDS')
            (root / 'textures/ztz_99a_body_cm.dds').write_bytes(base_buf.getvalue())

            # Skin (8x2, forcing resize of base & camo): alpha=0 on cols 0..5, alpha=255 on cols 6..7
            dig_img = Image.new('RGBA', (8, 2))
            row = [(0, 0, 0, 0)] * 6 + [(40, 90, 30, 255)] * 2
            dig_img.putdata(row * 2)
            dig_buf = BytesIO()
            dig_img.save(dig_buf, format='DDS')

            # Tileable base camo t1 (ussr_camo_green, 4x1)
            camo_buf = BytesIO()
            Image.new('RGBA', (4, 1), (60, 80, 40, 255)).save(camo_buf, format='DDS')

            from types import SimpleNamespace
            camo_ddsx = DDSx(
                str(root / 'gm.dxp.bin'),
                name='ussr_camo_green',
                size=4,
                dataOffset=0,
                header=SimpleNamespace(w=4, h=1, d3dformat=b'DXT5', flags=0, cMethod=0, levels=1, memSz=4, packedSz=4),
            )
            camo_ddsx.getDDS = lambda: camo_buf.getvalue()
            AssetCacher.cacheAsset(camo_ddsx)

            mat = MaterialData()
            mat.cls, mat.par = 'dynamic_masked_tank', 'camo_amplitude_tank=4'
            mat.addTexSlot('t0', 'ztz_99a_body_c*')
            mat.addTexSlot('t1', 'ussr_camo_green*')
            paths = TexturePathDict('wt_glide')

            fake_builtins = [{
                'id': 'wt:cn_ztz_99a#digital',
                'name': 'digital',
                'label': '数码迷彩 (digital)',
                'blk': 'dldata/downloadable_skins.blk#cn_ztz_99a#digital',
                'rules': [('ztz_99a_body_c*', 'dldata:dig_hash', 'camo_skin_tex')],
            }]
            out_pixels = []

            def convert(args, **kw):
                p = Path(args[args.index('-file') + 1])
                with Image.open(p) as img:
                    rgba = img.convert('RGBA')
                    out_pixels.extend([rgba.getpixel((x, 0)) for x in range(8)])
                p.with_suffix('.vtf').write_bytes(b'vtf')

            with patch('util.wtskins.builtinSkins', return_value=fake_builtins), \
                 patch('util.wtskins._cacheBuiltinSkinTextures'), \
                 patch('util.wtskins._loadBuiltinTarget', return_value=dig_buf.getvalue()), \
                 patch('util.wtskins.subprocess.run', side_effect=convert):
                importSkins(qc, [mat], paths, ['wt:digital'], 'converter', 'ztz_99a', root)

            self.assertEqual(len(out_pixels), 8)
            # x=0: painted area where digital skin alpha is 0 falls back to ussr_camo_green (greenish), not bare gray
            self.assertGreater(out_pixels[0][1], out_pixels[0][0])
            self.assertGreater(out_pixels[0][1], out_pixels[0][2])
            # x=3,4: upscaled unpainted dirt (base alpha=0) preserves RGB=(80,70,60), never premultiplied to (0,0,0)
            self.assertEqual(out_pixels[3], (80, 70, 60, 255))
            self.assertEqual(out_pixels[4], (80, 70, 60, 255))
            # x=7: opaque digital skin pixel
            self.assertEqual(out_pixels[7], (40, 90, 30, 255))

    def test_gui_builtin_skin_buttons(self):
        from PyQt5.QtWidgets import QApplication
        from gui.glideOptionsDialog import GlideOptionsDialog
        app = QApplication.instance() or QApplication([])
        fake = [
            {'id': 'wt:cn_ztz_99a#digital', 'name': 'digital', 'label': '数码迷彩 (digital)', 'blk': 'dl', 'rules': []},
            {'id': 'wt:cn_ztz_99a#winter', 'name': 'winter', 'label': '冬季迷彩 (winter)', 'blk': 'blk', 'rules': []},
        ]
        with patch('gui.skinImportWidget.builtinSkins', return_value=fake):
            dialog = GlideOptionsDialog(None, {'aircraft': False}, 'ztz_99a', gameRoot='D:/WT')
            self.assertFalse(dialog.skins.builtinRow.isHidden())
            dialog.skins.addBuiltinSkin()
            self.assertEqual(dialog.options()['skins'], ['wt:cn_ztz_99a#digital'])
            dialog.skins.addAllBuiltinSkins()
            self.assertEqual(dialog.options()['skins'], ['wt:cn_ztz_99a#digital', 'wt:cn_ztz_99a#winter'])
            dialog.close()


if __name__ == '__main__':
    unittest.main()
