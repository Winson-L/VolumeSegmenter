"""Reproducible uint8 volume extraction. Arrays are ZYX; metadata is XYZ.

This is spatial/intensity partitioning, not anatomical segmentation. Every
retained voxel is assigned once before optional, explicitly lossy decimation.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


def read_volume(path, shape_xyz):
    if len(shape_xyz) != 3 or any(int(n) != n or n <= 0 for n in shape_xyz):
        raise ValueError('Shape must contain three positive integers (X Y Z)')
    expected = int(np.prod(shape_xyz))
    if Path(path).stat().st_size != expected:
        raise ValueError(f'Expected exactly {expected} bytes for uint8 {shape_xyz}')
    return np.fromfile(path, dtype=np.uint8).reshape(tuple(reversed(shape_xyz)))


def background_threshold(volume, seed=42):
    """Fit two intensity populations on a bounded, seeded sample of nonzero data."""
    values = volume[volume > 0]
    if not values.size:
        return 0.0
    rng = np.random.default_rng(seed)
    sample = values[rng.choice(values.size, min(10000, values.size), replace=False)]
    if np.unique(sample).size < 2:
        return 0.0  # Keep constant-valued foreground, including tiny fixtures.
    model = KMeans(n_clusters=2, n_init=3, random_state=seed).fit(sample[:, None])
    return round(float(model.cluster_centers_.min()), 6)


def partition(volume, components=8, seed=42, spatial_weight=0.5, batch_size=100000):
    """Fit on a bounded sample; predict ALL foreground voxels in bounded batches."""
    foreground = np.flatnonzero(volume)
    labels = np.zeros(volume.size, dtype=np.uint8)
    if not foreground.size:
        return labels.reshape(volume.shape)

    def features(indices):
        z, y, x = np.unravel_index(indices, volume.shape)
        return np.column_stack((x, y, z, volume.ravel()[indices])).astype(np.float32)

    rng = np.random.default_rng(seed)
    sample = rng.choice(foreground, min(30000, foreground.size), replace=False)
    scaler = StandardScaler().fit(features(sample))
    weights = np.array([spatial_weight] * 3 + [1 - spatial_weight], dtype=np.float32)
    train = scaler.transform(features(sample)) * weights
    count = min(components, len(np.unique(train, axis=0)))
    model = KMeans(n_clusters=count, n_init=3, random_state=seed, max_iter=100).fit(train)
    for start in range(0, foreground.size, batch_size):
        indices = foreground[start:start + batch_size]
        labels[indices] = model.predict(scaler.transform(features(indices)) * weights) + 1
    return labels.reshape(volume.shape)


@threadpool_limits.wrap(limits=1)
def extract(input_path, output_dir, shape_xyz, *, mode='partition', threshold=None,
            components=8, seed=42, spatial_weight=0.5, downsample=1):
    if mode not in ('original', 'crop', 'partition'):
        raise ValueError('Unknown mode')
    if not 1 <= components <= 15 or not 0 <= spatial_weight <= 1 or downsample < 1 or int(downsample) != downsample:
        raise ValueError('Require 1–15 components, weight in [0,1], integer downsample >= 1')
    if threshold is not None and not 0 <= threshold <= 255:
        raise ValueError('Threshold must be in [0,255]')
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if list(output.glob('component_*.raw')) or (output / 'metadata.json').exists():
        raise ValueError(f'Output already contains results: {output}; choose a new directory')
    start = time.perf_counter()
    original = read_volume(input_path, shape_xyz)
    cutoff = 0.0 if mode == 'original' else (background_threshold(original, seed) if threshold is None else float(threshold))
    retained = original.copy()
    if mode != 'original':
        retained[retained <= cutoff] = 0
    labels = partition(retained, components, seed, spatial_weight) if mode == 'partition' else (retained > 0).astype(np.uint8)
    ids = np.unique(labels[labels > 0]) if mode != 'original' else [1]
    records = []
    for identifier in ids:
        if mode == 'original':
            lo, hi = np.zeros(3, dtype=int), np.array(original.shape)
            data = original.copy()
        else:
            coords = np.where(labels == identifier)
            lo = np.array([c.min() for c in coords])
            hi = np.array([c.max() + 1 for c in coords])
            slices = tuple(slice(a, b) for a, b in zip(lo, hi))
            data = np.where(labels[slices] == identifier, retained[slices], 0).astype(np.uint8)
        data = data[::downsample, ::downsample, ::downsample].copy()
        filename = f'component_{int(identifier)}.raw'
        data.tofile(output / filename)
        records.append(dict(file=filename, dimensions_xyz=list(map(int, data.shape[::-1])),
                            origin_xyz=list(map(int, lo[::-1])), spacing_xyz=[downsample] * 3,
                            extent_xyz=list(map(int, (hi - lo)[::-1])), bytes=data.nbytes,
                            sha256=hashlib.sha256(data.tobytes()).hexdigest()))
    metadata = dict(schema_version=2, dtype='uint8', array_order='ZYX', coordinate_order='XYZ',
                    input_file=Path(input_path).name, input_sha256=hashlib.sha256(original.tobytes()).hexdigest(),
                    dimensions_xyz=list(shape_xyz), original_bytes=original.nbytes,
                    parameters=dict(mode=mode, threshold=cutoff, seed=seed, components=components,
                                    spatial_weight=spatial_weight, downsample=downsample),
                    original_nonzero=int(np.count_nonzero(original)), retained_nonzero=int(np.count_nonzero(retained)),
                    components=records, output_bytes=sum(c['bytes'] for c in records),
                    processing_seconds=time.perf_counter() - start,
                    reconstruction='nearest block expansion, clipped to original component extent')
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


def reconstruct(directory):
    """Reference reconstruction in original voxel coordinates; max merges lossy overlaps."""
    directory = Path(directory)
    meta = json.loads((directory / 'metadata.json').read_text())
    result = np.zeros(meta['dimensions_xyz'][::-1], dtype=np.uint8)
    coverage = np.zeros(result.shape, dtype=np.uint8)
    for comp in meta['components']:
        block = read_volume(directory / comp['file'], comp['dimensions_xyz'])
        for axis, spacing in enumerate(comp['spacing_xyz'][::-1]):
            block = np.repeat(block, spacing, axis=axis)
        extent = comp['extent_xyz'][::-1]
        block = block[tuple(slice(0, n) for n in extent)]
        origin = comp['origin_xyz'][::-1]
        target = tuple(slice(a, a + n) for a, n in zip(origin, extent))
        np.maximum(result[target], block, out=result[target])
        coverage[target] += block > 0
    return result, coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--shape', type=int, nargs=3, required=True, metavar=('X', 'Y', 'Z'))
    parser.add_argument('--mode', choices=['original', 'crop', 'partition'], default='partition')
    parser.add_argument('--threshold', type=float)
    parser.add_argument('--components', type=int, default=8)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--spatial-weight', type=float, default=0.5)
    parser.add_argument('--downsample', type=int, default=1)
    args = vars(parser.parse_args())
    args['input_path'], args['output_dir'], args['shape_xyz'] = args.pop('input'), args.pop('output'), args.pop('shape')
    print(json.dumps(extract(**args), indent=2))


if __name__ == '__main__':
    main()
