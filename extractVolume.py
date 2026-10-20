"""Reproducible uint8 volume extraction. Arrays are ZYX; metadata is XYZ.

The default is tightly cropped, disjoint spatial partitioning, not anatomical segmentation. Every
retained voxel is assigned once before optional, explicitly lossy decimation.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
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


def select_foreground(volume, threshold, cleanup='none', min_region_voxels=512):
    """Explicit intensity/size heuristics, not a semantic definition of importance.

    Connected filtering preserves all voxels of retained six-connected regions,
    including thin branches. Opening removes thin features. Legacy reproduces
    the original three-voxel border removal and background dilation for audit.
    """
    if cleanup not in ('none', 'connected', 'opening', 'legacy'):
        raise ValueError('Unknown cleanup method')
    if not isinstance(min_region_voxels, int) or min_region_voxels < 1:
        raise ValueError('Minimum region size must be a positive integer')
    mask = volume > threshold
    threshold_count = int(mask.sum())
    regions_before = regions_after = None
    if cleanup == 'legacy':
        margin = min(3, min(volume.shape) // 10)
        if margin:
            for axis in range(3):
                edge = [slice(None)] * 3
                edge[axis] = slice(0, margin)
                mask[tuple(edge)] = False
                edge[axis] = slice(-margin, None)
                mask[tuple(edge)] = False
        if min(volume.shape) > 10:
            mask = ndi.binary_erosion(mask, structure=np.ones((3, 3, 3)))
    elif cleanup in ('connected', 'opening'):
        if cleanup == 'opening':
            mask = ndi.binary_opening(mask, structure=np.ones((3, 3, 3)))
        labels, regions_before = ndi.label(mask)  # Six-neighbor connectivity.
        sizes = np.bincount(labels.ravel())
        keep = sizes >= min_region_voxels
        keep[0] = False
        mask = keep[labels]
        regions_after = int(keep.sum())
    metrics = dict(threshold_nonzero=threshold_count, retained_nonzero=int(mask.sum()),
                   cleanup_removed_voxels=threshold_count - int(mask.sum()),
                   regions_before=regions_before, regions_after=regions_after,
                   intensity_survival={})
    for level in (60, 120):
        reference = volume > level
        count = int(reference.sum())
        removed = int(np.count_nonzero(reference & ~mask))
        metrics['intensity_survival'][str(level)] = dict(original_voxels=count,
            removed_voxels=removed, retained_fraction=(count - removed) / count if count else None)
    return mask, metrics


def kmeans_partition(volume, components=8, seed=42, spatial_weight=0.5, batch_size=100000):
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


def spatial_partition(volume, components=8):
    """Greedy axis-aligned splits with tight child crops; boxes never overlap.

    Try quarter/mid/three-quarter planes on each axis. Prefer the greatest
    reduction in stored bounding-box voxels, breaking ties by smaller largest
    child. This is a bounded heuristic, not a globally minimal partition.
    """
    def tight(lo, hi):
        block = volume[tuple(slice(a, b) for a, b in zip(lo, hi))]
        bounds = []
        for axis in range(3):
            occupied = np.flatnonzero(np.any(block, axis=tuple(i for i in range(3) if i != axis)))
            if not occupied.size:
                return None
            bounds.append((occupied[0], occupied[-1] + 1))
        return (lo + np.array([a for a, b in bounds]),
                lo + np.array([b for a, b in bounds]))

    def size(box):
        return int(np.prod(box[1] - box[0]))

    def surface(box):
        z, y, x = box[1] - box[0]
        return int(x * y + y * z + z * x)

    root = tight(np.zeros(3, dtype=int), np.array(volume.shape))
    if root is None:
        return np.zeros(volume.shape, dtype=np.uint8)
    leaves = [root]
    while len(leaves) < components:
        best = None
        for index, box in enumerate(leaves):
            lo, hi = box
            for axis in range(3):
                length = hi[axis] - lo[axis]
                for offset in sorted(set(int(length * f) for f in (0.25, 0.5, 0.75))):
                    if not 0 < offset < length:
                        continue
                    middle = lo[axis] + offset
                    left_hi, right_lo = hi.copy(), lo.copy()
                    left_hi[axis], right_lo[axis] = middle, middle
                    left, right = tight(lo, left_hi), tight(right_lo, hi)
                    if left is None or right is None:
                        continue
                    score = (size(box) - size(left) - size(right),
                             size(box) - max(size(left), size(right)),
                             -surface(left) - surface(right))
                    if best is None or score > best[0]:
                        best = (score, index, left, right)
        if best is None:
            break
        _, index, left, right = best
        leaves[index:index + 1] = [left, right]
    labels = np.zeros(volume.shape, dtype=np.uint8)
    for identifier, (lo, hi) in enumerate(leaves, 1):
        region = tuple(slice(a, b) for a, b in zip(lo, hi))
        labels[region] = np.where(volume[region] > 0, identifier, 0)
    return labels


@threadpool_limits.wrap(limits=1)
def extract(input_path, output_dir, shape_xyz, *, mode='partition', threshold=None,
            components=8, seed=42, spatial_weight=0.5, downsample=1, strategy="spatial",
            cleanup="none", min_region_voxels=512):
    if strategy not in ('spatial', 'kmeans'):
        raise ValueError('Unknown partition strategy')
    if mode == 'original' and cleanup != 'none':
        raise ValueError('Original mode does not accept foreground cleanup')
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
    mask, foreground_metrics = select_foreground(original, cutoff, cleanup, min_region_voxels)
    retained = np.where(mask, original, 0).astype(np.uint8)
    if mode == 'partition':
        labels = (spatial_partition(retained, components) if strategy == 'spatial'
                  else kmeans_partition(retained, components, seed, spatial_weight))
    else:
        labels = (retained > 0).astype(np.uint8)
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
                                    spatial_weight=spatial_weight, downsample=downsample, strategy=strategy,
                                    cleanup=cleanup, min_region_voxels=min_region_voxels),
                    foreground_metrics=foreground_metrics,
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
    parser.add_argument('--strategy', choices=['spatial', 'kmeans'], default='spatial')
    parser.add_argument('--cleanup', choices=['none', 'connected', 'opening', 'legacy'], default='none')
    parser.add_argument('--min-region-voxels', type=int, default=512)
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
