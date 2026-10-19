import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from extractVolume import extract, read_volume, reconstruct


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_volume(self, data, name='out', **kwargs):
        source = self.root / 'input.raw'
        data.tofile(source)
        target = self.root / name
        meta = extract(source, target, list(data.shape[::-1]), **kwargs)
        return meta, *reconstruct(target)

    def test_non_cubic_boundary_exact_and_disjoint(self):
        data = np.zeros((13, 17, 23), dtype=np.uint8)
        data[0:4, 2:8, 19:] = 150
        data[-3:, -4:, :5] = 210
        data[6, 8, 11] = 255
        meta, result, coverage = self.run_volume(data, threshold=0)
        np.testing.assert_array_equal(data, result)
        np.testing.assert_array_equal(coverage, data > 0)
        self.assertEqual(meta['dimensions_xyz'], [23, 17, 13])

    def test_predicts_unsampled_foreground(self):
        data = np.random.default_rng(21).integers(1, 255, (35, 36, 37), dtype=np.uint8)
        _, result, coverage = self.run_volume(data, threshold=0)
        np.testing.assert_array_equal(data, result)
        self.assertTrue(np.all(coverage == 1))

    def test_seed_reproducibility(self):
        data = np.random.default_rng(8).integers(0, 255, (15, 17, 23), dtype=np.uint8)
        first, a, _ = self.run_volume(data, 'a', seed=7)
        second, b, _ = self.run_volume(data, 'b', seed=7)
        self.assertEqual(first['components'], second['components'])
        self.assertEqual(first['parameters'], second['parameters'])
        np.testing.assert_array_equal(a, b)

    def test_empty_and_single_voxel(self):
        empty = np.zeros((3, 5, 7), dtype=np.uint8)
        meta, result, _ = self.run_volume(empty, 'empty')
        self.assertEqual(meta['components'], [])
        np.testing.assert_array_equal(empty, result)
        empty[-1, 0, -1] = 180
        meta, result, _ = self.run_volume(empty, 'single')
        self.assertEqual(len(meta['components']), 1)
        np.testing.assert_array_equal(empty, result)

    def test_decimation_extent_and_origin(self):
        data = np.zeros((9, 11, 13), dtype=np.uint8)
        data[2:9, 3:10, 4:13] = 150
        meta, result, _ = self.run_volume(data, mode='crop', threshold=0, downsample=2)
        comp = meta['components'][0]
        self.assertEqual(comp['origin_xyz'], [4, 3, 2])
        self.assertEqual(comp['extent_xyz'], [9, 7, 7])
        self.assertEqual(comp['dimensions_xyz'], [5, 4, 4])
        self.assertEqual(comp['spacing_xyz'], [2, 2, 2])
        np.testing.assert_array_equal(data, result)

    def test_original_and_threshold(self):
        data = np.arange(120, dtype=np.uint8).reshape(4, 5, 6)
        _, result, _ = self.run_volume(data, 'original', mode='original')
        np.testing.assert_array_equal(data, result)
        _, result, _ = self.run_volume(data, 'crop', mode='crop', threshold=50)
        np.testing.assert_array_equal(np.where(data > 50, data, 0), result)

    def test_weights_affect_partition(self):
        z, y, x = np.indices((12, 13, 14))
        data = np.where(x % 2, 210, 40).astype(np.uint8)
        spatial, _, _ = self.run_volume(data, 'spatial', threshold=0, components=2, spatial_weight=1)
        intensity, _, _ = self.run_volume(data, 'intensity', threshold=0, components=2, spatial_weight=0)
        self.assertNotEqual(spatial['components'], intensity['components'])

    def test_reject_bad_input_and_existing_output(self):
        source = self.root / 'bad.raw'
        source.write_bytes(b'123')
        with self.assertRaises(ValueError):
            read_volume(source, [2, 2, 2])
        with self.assertRaises(ValueError):
            read_volume(source, [0, 1, 3])
        self.run_volume(np.ones((2, 3, 4), dtype=np.uint8))
        with self.assertRaises(ValueError):
            self.run_volume(np.ones((2, 3, 4), dtype=np.uint8))


if __name__ == '__main__':
    unittest.main()
