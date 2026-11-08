import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/dae'))
from util.jetexhaust import PARAMETERS, SHADERS, parameterImage, exportExhaust, rendererLua
from util.glide import aircraftInertia


class JetExhaustTest(unittest.TestCase):
    def test_native_inertia_axes_units_and_mass(self):
        fm = {'MomentOfInertia': [55000, 250000, 210000], 'Mass': {'EmptyMass': 17900}}
        result = aircraftInertia(fm, 27300)
        scale = 27300 / 17900 * (40 * 0.0254) ** 2
        for actual, native in zip(result, (55000, 210000, 250000)):
            self.assertAlmostEqual(actual, native * scale)
        self.assertIsNone(aircraftInertia({}, 27300))
        for values in ([1, 2], [0, 2, 3], [float('nan'), 2, 3]):
            self.assertIsNone(aircraftInertia(dict(fm, MomentOfInertia=values), 27300))

    def test_parameter_texture_round_trip(self):
        values = {key: i * 0.531 for i, key in enumerate(PARAMETERS)}
        image = parameterImage(values)
        for i, key in enumerate(PARAMETERS):
            r, g, b, _ = image.getpixel((i, 0))
            decoded = (r / 255 + g / 255 ** 2 + b / 255 ** 3) * 256
            self.assertAlmostEqual(decoded, values[key], delta=256 / 255 ** 3)
        for bad in (-1, 256, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                parameterImage(dict(values, absorption=bad))

    def test_shaders_ship_and_missing_resources_fail_explicitly(self):
        resources = Path(__file__).resolve().parents[1] / 'res/jet_exhaust'
        for name in SHADERS:
            self.assertGreater((resources / 'shaders/fxc' / (name + '.vcs')).stat().st_size, 100)
        with TemporaryDirectory() as temp, patch('util.jetexhaust.getResPath', return_value=temp):
            with self.assertRaisesRegex(FileNotFoundError, 'Exhaust shader missing'):
                exportExhaust('unused', temp, 'wt_test', {}, 'unused')
            self.assertFalse((Path(temp) / 'lua').exists())

    def test_renderer_is_parameterized_and_has_no_layer_mesh(self):
        lua = rendererLua('wt_other', 'models/other', {'maxHeight': 13})
        self.assertIn('"maxHeight":13', lua)
        self.assertIn('"wt_other"', lua)
        self.assertIn('"models/other"', lua)
        self.assertIn('exhaust.Nozzle(', lua)
        self.assertIn('exhaust.Heat(', lua)
        self.assertNotIn('BuildVolume', lua)
        self.assertNotIn('mig29', lua)


if __name__ == '__main__':
    unittest.main()
