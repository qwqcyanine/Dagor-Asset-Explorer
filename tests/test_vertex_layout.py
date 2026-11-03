"""Run with: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path
from struct import pack
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "dae"))
from parse.mesh import MatVData
from util.fileread import BinFile


class SkinnedVertexLayoutTest(unittest.TestCase):
    def test_format15_mixed_channel_orders(self):
        # bones/weights first (default layout), then a pos-first vertex as used by War Thunder's ammo belts
        boneFirst = bytes((1, 1, 1, 1, 0, 0, 255, 0)) + pack("<4h", 100, 200, 300, 32767) + bytes(4) + pack("<2h", 4096, -4096)
        posFirst = pack("<4h", -400, 500, -600, 32767) + bytes(4) + pack("<2h", 2048, 2048) + bytes((2, 2, 2, 2, 0, 0, 255, 0))

        vd = object.__new__(MatVData.VertexData)
        vd._VertexData__gvData = SimpleNamespace(getStorageFormat=lambda: 15, getVertexStride=lambda: 24, getVertexCnt=lambda: 2)
        vd.__processVertices__(BinFile(boneFirst + posFirst))

        self.assertEqual(vd.getVertices(), [[100 / 32768, 200 / 32768, 300 / 32768], [-400 / 32768, 500 / 32768, -600 / 32768]])
        self.assertEqual(vd.getUVs(), [(1.0, 2.0), (0.5, 0.5)])
        self.assertEqual(vd.getSkin(), [((1, 1.0),), ((2, 1.0),)])

    def test_skin_weights_blend(self):
        vert = bytes((7, 7, 16, 7, 0, 25, 230, 0)) + pack("<4h", 1, 2, 3, 32767) + bytes(4) + pack("<2h", 0, 0)
        vd = object.__new__(MatVData.VertexData)
        vd._VertexData__gvData = SimpleNamespace(getStorageFormat=lambda: 15, getVertexStride=lambda: 24, getVertexCnt=lambda: 1)
        vd.__processVertices__(BinFile(vert))

        self.assertEqual(vd.getSkin(), [((7, 25 / 255), (16, 230 / 255))])


if __name__ == "__main__":
    unittest.main()
