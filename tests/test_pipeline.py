import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from extractVolume import extract, read_volume, reconstruct, select_foreground


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
        _, result, coverage = self.run_volume(data, threshold=0, strategy='kmeans')
        np.testing.assert_array_equal(data, result)
        self.assertTrue(np.all(coverage == 1))

    def test_spatial_storage_budget_and_boxes(self):
        for seed in range(3):
            data = np.zeros((19, 23, 31), dtype=np.uint8)
            rng = np.random.default_rng(seed)
            data[2:8, 1:7, 3:10] = rng.integers(1, 255, (6, 6, 7), dtype=np.uint8)
            data[12:18, 17:22, 23:30] = 200
            meta, restored, coverage = self.run_volume(data, f'sparse{seed}', threshold=0)
            self.assertLess(meta['output_bytes'], data.nbytes)
            boxes = np.zeros(data.shape, dtype=np.uint8)
            for c in meta['components']:
                o, e = c['origin_xyz'][::-1], c['extent_xyz'][::-1]
                region = tuple(slice(a, a + n) for a, n in zip(o, e))
                boxes[region] += 1
                self.assertEqual(c['dimensions_xyz'], c['extent_xyz'])
                block = restored[region]
                for axis in range(3):
                    self.assertTrue(np.any(np.take(block, 0, axis=axis)))
                    self.assertTrue(np.any(np.take(block, -1, axis=axis)))
            self.assertLessEqual(int(boxes.max()), 1)
            np.testing.assert_array_equal(restored, data)
            np.testing.assert_array_equal(coverage, data > 0)

    def test_dense_spatial_budget(self):
        data = np.full((13, 15, 17), 190, dtype=np.uint8)
        meta, restored, coverage = self.run_volume(data, threshold=0)
        self.assertEqual(meta['output_bytes'], data.nbytes)
        np.testing.assert_array_equal(restored, data)
        self.assertTrue(np.all(coverage == 1))

    def test_connected_cleanup_preserves_thin_branch_and_boundary(self):
        data = np.zeros((15, 17, 19), dtype=np.uint8)
        data[0:4, 3:7, 2:6] = 180
        data[2, 5, 6:15] = 170  # Thin branch connected to the retained region.
        data[13, 15, 17] = 230  # Bright but isolated: report, do not call it noise.
        meta, result, coverage = self.run_volume(data, threshold=60, cleanup='connected', min_region_voxels=10)
        expected = data.copy(); expected[13, 15, 17] = 0
        np.testing.assert_array_equal(result, expected)
        self.assertEqual(meta['foreground_metrics']['cleanup_removed_voxels'], 1)
        self.assertEqual(meta['foreground_metrics']['intensity_survival']['120']['removed_voxels'], 1)
        self.assertLess(meta['output_bytes'], data.nbytes)

    def test_cleanup_connectivity_and_empty_mask(self):
        data = np.zeros((5, 6, 7), dtype=np.uint8)
        data[1, 1, 1] = data[2, 2, 2] = 200
        mask, metrics = select_foreground(data, 60, 'connected', 2)
        self.assertFalse(mask.any())  # Diagonal contact is not six-connected.
        self.assertEqual(metrics['regions_before'], 2)
        self.assertEqual(metrics['regions_after'], 0)
        with self.assertRaises(ValueError):
            select_foreground(data, 60, 'connected', 0)

    def test_opening_exposes_loss_of_thin_structures(self):
        data = np.zeros((11, 13, 15), dtype=np.uint8)
        data[5, 6, 2:12] = 200
        mask, metrics = select_foreground(data, 60, 'opening', 1)
        self.assertFalse(mask.any())
        self.assertEqual(metrics['intensity_survival']['120']['removed_voxels'], 10)

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
        spatial, _, _ = self.run_volume(data, 'spatial', threshold=0, components=2, spatial_weight=1, strategy="kmeans")
        intensity, _, _ = self.run_volume(data, 'intensity', threshold=0, components=2, spatial_weight=0, strategy="kmeans")
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
