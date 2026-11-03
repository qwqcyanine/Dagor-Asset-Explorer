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

    def test_glass_variants_get_their_own_vmt(self):
        names = {material("dynamic_glass_chrome", {}, f"opacity={o}").getName() for o in ("0.17", "0.9")}
        self.assertEqual(len(names), 2)

    def test_jet_flame_is_additive(self):
        vmt = material("aces_weapon_fire", {0: "jet_flame_diamonds*"}).getVMT(TexturePathDict("x"))
        self.assertTrue(vmt.startswith('"UnlitGeneric"'))
        self.assertIn("$additive 1", vmt)
        self.assertIn("$translucent 1", vmt)

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
