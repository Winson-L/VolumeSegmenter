"""Five controlled extraction experiments; timings exclude reconstruction/metrics."""
import argparse
import json
import platform
import sys
from pathlib import Path
import numpy as np
import sklearn
from extractVolume import extract, read_volume, reconstruct


def run(input_path, shape, output):
    output = Path(output)
    original = read_volume(input_path, shape)
    rows = []
    cutoff = None
    for name, mode, factor in [('original', 'original', 1), ('crop', 'crop', 1),
                                ('partition', 'partition', 1), ('lossy', 'partition', 2),
                                ('decimated', 'crop', 2)]:
        meta = extract(input_path, output / name, shape, mode=mode, downsample=factor, threshold=cutoff)
        if name == 'crop':
            cutoff = meta['parameters']['threshold']
        restored, coverage = reconstruct(output / name)
        reference = original if mode == 'original' else np.where(original > cutoff, original, 0)
        delta = restored.astype(np.float32) - reference.astype(np.float32)
        rows.append(dict(experiment=name, **{k: meta[k] for k in ['output_bytes', 'processing_seconds', 'retained_nonzero']},
                         component_count=len(meta['components']), reduction_percent=100 * (1 - meta['output_bytes'] / original.nbytes),
                         threshold=meta['parameters']['threshold'],
                         mae_vs_retained=float(np.abs(delta).mean()),
                         mae_vs_original=float(np.abs(restored.astype(np.float32) - original).mean()),
                         retained_voxels_missing=int(np.count_nonzero((reference > 0) & (restored == 0))),
                         introduced_nonzero_voxels=int(np.count_nonzero((reference == 0) & (restored > 0))),
                         overlapping_nonzero_voxels=int(np.count_nonzero(coverage > 1))))
    report = dict(input_file=Path(input_path).name, input_sha256=meta['input_sha256'], dimensions_xyz=shape,
                  original_bytes=original.nbytes, environment=dict(python=sys.version, platform=platform.platform(),
                  numpy=np.__version__, scikit_learn=sklearn.__version__),
                  methodology='Single run per variant, sequential. Processing includes file IO, hashing and extraction; excludes reconstruction and metrics. MiB = 1048576 bytes. Not network compression. No peak RAM claim.', results=rows)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default='skull_256x256x256_uint8.raw')
    p.add_argument('--shape', type=int, nargs=3, default=[256, 256, 256])
    p.add_argument('--output', default='experiments/current')
    args = p.parse_args()
    run(args.input, args.shape, args.output)
