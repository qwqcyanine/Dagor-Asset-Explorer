"""Run with: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "dae"))
from parse.material import MaterialData, TexturePathDict


def material(cls, slots, par = ""):
    m = MaterialData()
    m.cls, m.par = cls, par
    for i, t in slots.items():
        m.addTexSlot(f"t{i}", t)
    return m


class DDSxTest(unittest.TestCase):
    def test_bgra_reversed_mips_export_as_rgba_dds(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import patch
        from PIL import Image
        from parse.material import DDSx

        header = SimpleNamespace(w=4, h=4, d3dformat=b"\x15\0\0\0", flags=0x40000,
                                 cMethod=0, levels=3, memSz=84, packedSz=84)
        tex = DDSx("test.ddsx", size=84, header=header)
        raw = bytes((30, 20, 10, 255)) + bytes((60, 50, 40, 255)) * 4 + bytes((90, 80, 70, 255)) * 16
        with patch.object(tex, "getData", return_value=raw):
            dds = tex.getDDS()
        self.assertEqual(len(dds), 128 + len(raw))
        img = Image.open(BytesIO(dds)).convert("RGBA")
        self.assertEqual(img.size, (4, 4))
        self.assertEqual(img.getpixel((3, 3)), (70, 80, 90, 255))
        self.assertEqual(dds[-4:], bytes((30, 20, 10, 255)))

    def test_l8_a8_rgba_and_ati2_reversed_mips_export_as_dds(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import patch
        from PIL import Image
        from parse.material import DDSx

        for fmt in (b"2\0\0\0", b"\x1c\0\0\0"): # D3DFMT_L8 (50) and D3DFMT_A8 (28)
            header = SimpleNamespace(w=4, h=2, d3dformat=fmt, flags=0x40000,
                                     cMethod=0, levels=3, memSz=11, packedSz=11)
            tex = DDSx("propmask.ddsx", size=11, header=header)
            raw = bytes((11,)) + bytes((22,)) * 2 + bytes((200,)) * 8
            with patch.object(tex, "getData", return_value=raw):
                dds = tex.getDDS()
            img = Image.open(BytesIO(dds))
            self.assertEqual(img.size, (4, 2))
            self.assertEqual(img.getpixel((3, 1)), 200)
            self.assertEqual(dds[-1:], bytes((11,)))

        # D3DFMT_A8B8G8R8 (32)
        header = SimpleNamespace(w=4, h=2, d3dformat=b" \0\0\0", flags=0x40000,
                                 cMethod=0, levels=3, memSz=44, packedSz=44)
        tex = DDSx("rgba.ddsx", size=44, header=header)
        raw = bytes((1, 2, 3, 255)) + bytes((4, 5, 6, 255)) * 2 + bytes((10, 20, 30, 255)) * 8
        with patch.object(tex, "getData", return_value=raw):
            dds = tex.getDDS()
        img = Image.open(BytesIO(dds)).convert("RGBA")
        self.assertEqual(img.size, (4, 2))
        self.assertEqual(img.getpixel((3, 1)), (10, 20, 30, 255))

        # ATI2 (BC5: 16 bytes per 4x4 block)
        header = SimpleNamespace(w=8, h=4, d3dformat=b"ATI2", flags=0x40000,
                                 cMethod=0, levels=2, memSz=48, packedSz=48)
        tex = DDSx("normal.ddsx", size=48, header=header)
        raw = b"\x11" * 16 + b"\x22" * 32
        with patch.object(tex, "getData", return_value=raw):
            dds = tex.getDDS()
        self.assertEqual(dds[128:128 + 32], b"\x22" * 32)
        self.assertEqual(dds[-16:], b"\x11" * 16)

    def test_heat_conversion_uses_rg_not_noise_and_blur_channels(self):
        from PIL import Image
        from util.glide import jetHeatNormal

        img = Image.new("RGBA", (3, 1))
        img.putdata([(127, 127, 0, 0), (255, 0, 255, 0), (127, 127, 255, 255)])
        out = jetHeatNormal(img)
        self.assertEqual(out.getpixel((0, 0)), (128, 128, 255, 255))
        self.assertEqual(out.getpixel((2, 0)), (128, 128, 255, 255))
        r, g, b, a = out.getpixel((1, 0))
        self.assertGreater(r, 128)
        self.assertLess(g, 128)
        self.assertGreater(b, 128)
        self.assertEqual(a, 255)


class VMTTest(unittest.TestCase):
    def test_masked_cutout_preserves_coverage_not_inverted_paint_mask(self):
        from io import BytesIO
        from PIL import Image
        from util.enums import TEXTURE_GENERIC, TEXTURE_MASKED

        src = Image.new('RGBA', (4, 1))
        src.putdata([(100, 110, 120, a) for a in (0, 64, 192, 255)])
        buf = BytesIO()
        src.save(buf, format='DDS')
        for cls, param, cutout in (
            ('dynamic_masked_chrome_bump', 'atest=127', True),
            ('dynamic_masked_chrome_bump_atest', '', True),
            ('dynamic_masked_chrome_bump', '', False),
            ('dynamic_masked_chrome_bump', 'atest=128', False),
        ):
            with self.subTest(cls=cls,param=param):
                mat = material(cls, {0:'pod_a*'}, param)
                paths = TexturePathDict('wt')
                vmt = mat.getVMT(paths)
                key = 'pod_a' if cutout else 'pod_am'
                self.assertEqual(paths.get(key).texType, TEXTURE_GENERIC if cutout else TEXTURE_MASKED)
                out, _ = mat.convertTex('pod_a', buf.getvalue(), paths, texN=key)
                alpha = list(Image.open(BytesIO(out)).convert('RGBA').getchannel('A').get_flattened_data())
                self.assertEqual(alpha, [0,64,192,255] if cutout else [255,191,63,0])
                if cutout:
                    self.assertIn('$alphatest 1', vmt)
                    self.assertIn('$alphatestreference', vmt)
                else:
                    self.assertNotIn('$alphatest', vmt)

    def test_tank_camo_exponent_and_normal_unit_z(self):
        from io import BytesIO
        from PIL import Image

        src = Image.new('RGBA', (2, 1))
        src.putdata([(100, 110, 120, 0), (100, 110, 120, 128)])
        buf = BytesIO()
        src.save(buf, format='DDS')

        tank = material('dynamic_masked_tank', {0: 'hull_c*', 1: 'camo*'}, 'camo_amplitude_tank=4')
        tank_paths = TexturePathDict('wt')
        tank.getVMT(tank_paths)
        tank_out, _ = tank.convertTex('hull_c', buf.getvalue(), tank_paths, texN='hull_cm')
        tank_alpha = list(Image.open(BytesIO(tank_out)).convert('RGBA').getchannel('A').get_flattened_data())
        self.assertEqual(tank_alpha, [255, 40])

        air = material('dynamic_masked_chrome_bump', {0: 'hull_c*'})
        air_paths = TexturePathDict('wt')
        air.getVMT(air_paths)
        air_out, _ = air.convertTex('hull_c', buf.getvalue(), air_paths, texN='hull_cm')
        air_alpha = list(Image.open(BytesIO(air_out)).convert('RGBA').getchannel('A').get_flattened_data())
        self.assertEqual(air_alpha, [255, 127])

        norm_mat = material('dynamic_masked_tank', {0: 'hull_c*', 2: 'hull_n*'})
        norm_paths = TexturePathDict('wt')
        norm_mat.getVMT(norm_paths)

        rgba_n = Image.new('RGBA', (1, 1), (10, 128, 0, 200))
        nbuf = BytesIO()
        rgba_n.save(nbuf, format='DDS')
        nout, _ = norm_mat.convertTex('hull_n', nbuf.getvalue(), norm_paths)
        self.assertEqual(Image.open(BytesIO(nout)).convert('RGBA').getpixel((0, 0)), (200, 128, 232, 10))

        rgb_n = Image.new('RGB', (1, 1), (200, 128, 0))
        rgbbuf = BytesIO()
        rgb_n.save(rgbbuf, format='DDS')
        rgbout, _ = norm_mat.convertTex('hull_n', rgbbuf.getvalue(), norm_paths)
        self.assertEqual(Image.open(BytesIO(rgbout)).convert('RGBA').getpixel((0, 0)), (200, 128, 232, 255))

    def test_alpha_blend_preserves_texture_coverage(self):
        from util.enums import TEXTURE_GENERIC

        paths = TexturePathDict('wt')
        vmt = material('dynamic_alpha_blend', {0: 'glass_dirt*'}).getVMT(paths)
        self.assertIn('$translucent 1', vmt)
        self.assertNotIn('$alphatest', vmt)
        self.assertNotIn('$envmap', vmt)
        self.assertEqual(paths.get('glass_dirt').texType, TEXTURE_GENERIC)

    def test_detail_normal_and_cubemap_are_not_details(self):
        for detailSlot, tex in ((4, "aircraft_normal_detail_n*"), (1, "stalingrad_noon_cubemap_blur*")):
            vmt = material("dynamic_masked_chrome_bump", {0: "skin_c*", 2: "skin_n*", detailSlot: tex}).getVMT(TexturePathDict("x"))
            self.assertNotIn("$detail", vmt)

    def test_vector_params_are_quoted(self):
        vmt = material("dynamic_masked_chrome_bump", {0: "skin_c*", 1: "camo_c*", 2: "skin_n*"}, "mask_gamma_start=0.5").getVMT(TexturePathDict("x"))
        self.assertIn('$detailscale "[1 1]"', vmt)
        self.assertIn('$detailtint "[1.0 1.0 1.0]"', vmt)

    def test_untextured_glass_is_see_through(self):
        vmt = material("dynamic_glass_chrome", {}, "opacity=0.9").getVMT(TexturePathDict("x"))
        self.assertIn("$translucent 1", vmt)
        # models overwrite $alpha each draw, the proxy restores War Thunder's opacity
        self.assertIn("$wtopacity 0.9", vmt)
        self.assertIn('resultVar "$alpha"', vmt)

    def test_textured_glass_keeps_explicit_opacity(self):
        vmt = material('dynamic_masked_glass_chrome', {0: 'empty_glass*'}, 'opacity=0.1').getVMT(TexturePathDict('wt'))
        self.assertIn('$wtopacity 0.1', vmt)
        self.assertIn('resultVar "$alpha"', vmt)
        self.assertNotIn('$color2', vmt)

    def test_glass_variants_get_their_own_vmt(self):
        names = {material("dynamic_glass_chrome", {}, f"opacity={o}").getName() for o in ("0.17", "0.9")}
        self.assertEqual(len(names), 2)

    def test_coating_only_canopy_has_a_material_name(self):
        from parse.material import computeMaterialNames

        mats = [material("dynamic_glass_chrome", {3: "rainbow_light_coating*"}, f"opacity={o}")
                for o in ("0.17", "0.5")]
        computeMaterialNames(mats)
        self.assertEqual([m.getName() for m in mats],
                         ["rainbow_light_coating_017", "rainbow_light_coating_05"])
        vmt = mats[0].getVMT(TexturePathDict("x"))
        self.assertIn("$wtopacity 0.17", vmt)
        self.assertIn("$translucent 1", vmt)
        self.assertNotIn("$basetexture", vmt)

    def test_jet_flame_is_additive(self):
        vmt = material("aces_weapon_fire", {0: "jet_flame_diamonds*"}).getVMT(TexturePathDict("x"))
        self.assertTrue(vmt.startswith('"UnlitGeneric"'))
        self.assertIn("$additive 1", vmt)
        self.assertIn("$translucent 1", vmt)

    def test_static_muzzle_flash_is_not_drawn_as_permanent_fire(self):
        mat = material("aces_weapon_fire", {0: "gunfire*"})
        vmt = mat.getVMT(TexturePathDict("models/wt"))
        self.assertIn('$additive 1', vmt)
        self.assertIn("$no_draw 1", vmt)
        jet = material("aces_weapon_fire", {0: "jet_flame_diamonds*"})
        self.assertNotIn("$no_draw 1", jet.getVMT(TexturePathDict("models/wt")))

    def test_tex_path_prefers_highest_resolution_pack(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from parse.material import DDSx
        low = DDSx("content/base/res/zzz-tq_pack.dxp.bin", "body_c", 64, 0, SimpleNamespace(w=32, h=32, packedSz=64))
        hq = DDSx("content.hq/hq_tex/res/hq_tex_aircrafts/mig_29.dxp.bin", "body_c", 1024, 0, SimpleNamespace(w=2048, h=2048, packedSz=1024))
        with patch("parse.material.AssetCacher.getCachedAsset", return_value=[low, hq]):
            self.assertEqual(TexturePathDict("wt_glide").getTexPath("body_c"), "models/wt_glide/mig_29")

    def test_jet_flame_texture_gets_disc_art_for_the_plume(self):
        from io import BytesIO
        from PIL import Image
        mat = material("aces_weapon_fire", {0: "jet_flame_diamonds*"})
        paths = TexturePathDict("x")
        mat.getVMT(paths)
        src = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
        src.paste((255, 128, 0, 80), (48, 0, 64, 64))
        buf = BytesIO()
        src.save(buf, format = "DDS")
        out = Image.open(BytesIO(mat.convertTex("jet_flame_diamonds", buf.getvalue(), paths)[0])).convert("RGBA")
        self.assertEqual(out.getpixel((40, 10))[3], 0) # shock diamond discs hidden
        self.assertEqual(out.getpixel((56, 8))[3], 255) # nozzle glow disc filled solid
        self.assertEqual(out.getpixel((1, 56))[3], 0) # the mesh's crossed cards are blanked
        self.assertGreater(out.getpixel((1, 32))[3], 80) # billboard plume strongest at the nozzle
        self.assertLess(out.getpixel((30, 32))[3], 10) # and gone at the tail
        self.assertEqual(out.getpixel((10, 20))[3], 0) # nothing painted outside the plume band
