"""Audit foreground selection separately from cropping and downsampling."""
import argparse
import json
import platform
import sys
from pathlib import Path
import numpy as np
import scipy
from pipeline.extractVolume import extract, read_volume, reconstruct, select_foreground


def run(source, shape, output):
    output = Path(output)
    original = read_volume(source, shape)
    # Same eight-block budget; all except the explicit decimated control use spacing=1.
    variants = [
        ('original', dict(mode='original')),
        ('threshold', dict()),
        ('legacy_cleanup', dict(cleanup='legacy')),
        ('opening', dict(cleanup='opening')),
        ('conservative', dict(threshold=30, cleanup='connected')),
        ('focused', dict(threshold=60, cleanup='connected')),
        ('aggressive', dict(threshold=90, cleanup='connected', min_region_voxels=128)),
        ('focused_decimated', dict(threshold=60, cleanup='connected', downsample=2)),
    ]
    rows = []
    for name, options in variants:
        meta = extract(source, output / name, shape, **options)
        if name != 'original' and options.get('downsample', 1) == 1:
            extract(source, output / (name + '_monolith'), shape, **{**options, 'mode': 'crop'})
        restored, coverage = reconstruct(output / name)
        p = meta['parameters']
        mask, _ = select_foreground(original, p['threshold'], p['cleanup'], p['min_region_voxels'])
        selected = np.where(mask, original, 0).astype(np.uint8)
        row = dict(name=name, parameters=p, output_bytes=meta['output_bytes'],
                   reduction_percent=100*(1-meta['output_bytes']/original.nbytes),
                   component_count=len(meta['components']), selection_metrics=meta['foreground_metrics'],
                   reconstruction_matches_selected=bool(np.array_equal(restored, selected)),
                   mae_vs_selected=float(np.abs(restored.astype(np.float32)-selected).mean()),
                   overlapping_nonzero_voxels=int(np.count_nonzero(coverage > 1)),
                   total_processing_seconds=meta['processing_seconds'])
        rows.append(row)
        print(name, round(row['output_bytes']/1048576, 3), 'MiB', flush=True)
    report = dict(input_sha256=meta['input_sha256'], dimensions_xyz=shape, original_bytes=original.nbytes,
                  environment=dict(python=sys.version, platform=platform.platform(), numpy=np.__version__, scipy=scipy.__version__),
                  methodology='Same original voxel grid and at most eight disjoint cropped boxes. Selection losses and reconstruction losses are separate. Intensity survival is a proxy, not anatomical accuracy. Legacy cleanup audits border removal and erosion, not a reconstruction of the historical 5.85 MiB outputs whose per-component spacing was not recorded.',
                  variants=rows)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='data/skull_256x256x256_uint8.raw')
    parser.add_argument('--shape', nargs=3, type=int, default=[256,256,256])
    parser.add_argument('--output', default='experiments/foreground')
    args = parser.parse_args()
    run(args.input, args.shape, args.output)
