"""Build the comparable size/timing table from saved experiment artifacts."""
import json
from pathlib import Path
from statistics import median

ROOT=Path('experiments/grouped-results')
def build():
    rows=[]
    for name in ['bonsai','foot','engine','kingsnake','woodbranch']:
        m=json.loads((ROOT/(name+'-storage.json')).read_text())
        r=json.loads((ROOT/(name+'-rendering.json')).read_text())
        original=[v['gpu_median_ms'] for v in r['runs'] if v['mode']=='original' and v['gpu_median_ms'] is not None]
        compact=[v['gpu_median_ms'] for v in r['runs'] if v['mode']=='compact' and v['gpu_median_ms'] is not None]
        if not compact:raise ValueError('Missing GPU measurements for '+name)
        total=m['density_bytes']+m.get('mask_bytes',0)+m['group_index_bytes']
        gpu=next(v['texture_bytes'] for v in r['runs'] if v['mode']=='compact')
        checks=r['image_checks'];exact=bool(checks) and all(c['different_channels']==0 for c in checks)
        rows.append(dict(dataset=name,source_bytes=m['source_bytes'],combined_storage_bytes=total,
            gpu_texture_bytes=gpu,reduction_percent=100*(1-total/m['source_bytes']),
            original_gpu_median_ms=median(original) if original else None,
            combined_gpu_median_ms=median(compact),original_ms_by_view=original,combined_ms_by_view=compact,
            framebuffer_exact=exact if checks else None,groups=len(m['groups']),
            cutoff=m['cutoff'],selected_voxels=m['selected_voxels'],source_voxels=m['source_bytes']//m['bytes_per_voxel'],
            encoding=m['storage_encoding'],window_max=r['window_max']))
    (ROOT/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
    table=['| Dataset | Original MiB | Combined files MiB | Reduction | GPU MiB | Original / combined GPU ms | Image checks |',
           '| --- | ---: | ---: | ---: | ---: | --- | --- |']
    for v in rows:
        orig=f"{v['original_gpu_median_ms']:.2f}" if v['original_gpu_median_ms'] is not None else 'not run'
        table.append(f"| {v['dataset']} | {v['source_bytes']/2**20:.2f} | {v['combined_storage_bytes']/2**20:.2f} | {v['reduction_percent']:.1f}% | {v['gpu_texture_bytes']/2**20:.2f} | {orig} / {v['combined_gpu_median_ms']:.2f} | "+('3/3 exact' if v['framebuffer_exact'] else 'MIP only; no full DVR reference')+' |')
    text="""# Grouped-volume comparison

Measured locally on Apple M4 / 16 GiB unified memory. This report supersedes the old threshold-7000 Woodbranch comparison for the new grouped viewer.

All rows use full-resolution uint8/uint16 input, 16³ grid bricks, the same three fixed camera views, 640×480, step 1, nearest-neighbor sampling, and the shared color/opacity transfer function. Each mode/view has five warmups and 20 asynchronous GPU timer queries. The table is the median of the three per-view medians, not a screen-FPS estimate. Raw samples, windows, environment and per-view framebuffer differences are saved in the adjacent JSON files. Modes are sequential, not simultaneous. Upload, download, hashing and preprocessing are excluded from GPU timings.

"""+'\n'.join(table)+"""

## Selection and interpretation

Bonsai (plant CT), Foot (human foot scan), and Engine (industrial CT) add three small, independently sourced examples (16, 16 and 8 MiB). These broaden content coverage; they are not additional large-memory stress tests. Their input SHA-512 hashes match the Open SciVis catalog. Credits and download URLs are in the provenance files.

The three new examples use raw intensity >32, Kingsnake >40, Woodbranch >5000. These are explicit exploratory foreground rules, not anatomical or semantic ground truth. The color transfer function uses blue/orange/cream control points at 0/50/100% of the recorded display window, with extinction coefficients 0.0001/0.003/0.06. Original and combined representations use identical settings within each row.

Exact image checks apply only to that display cutoff and those three cameras. They do not prove the removed data was irrelevant. Unfiltered-versus-thresholded projection differences are reported separately. Woodbranch retains 211,046,399 voxels (2.46%), versus 92,042,622 at the earlier >7000 cutoff. That is 2.29× as many retained samples, but substantial lower-intensity structure is still omitted.

Woodbranch's 16 GiB monolithic texture is skipped before allocation by the 1 GiB experiment budget. There is no observed OOM or measured original GPU time for that row. Three full-resolution thresholded MIPs and every decoded grouped brick are verified instead. The online image in the viewer is only an external appearance reference.

## Logical groups and memory

Each brick is assigned to an intensity band using the median of its selected voxels. Six-neighbor bricks in the same band form components. The nine largest components remain separate; smaller components are explicitly pooled by band. Group names describe brick medians, not the exact range of every voxel within the group. This is a brick graph baseline, **not cross-chunk SLIC or tissue classification**. A connected brick graph does not guarantee voxel-level connectivity.

Every brick belongs to exactly one group. Logical AABBs reference their members; no dense parent volume is allocated. The automatic encoder selects dense crops or 32-voxel occupancy masks according to smaller total value+mask bytes. Occupancy masks remove stored interior zeros without deleting additional selected voxels. Original precision and coordinates are retained.

“Combined files” sums group sample payloads, masks and group indices; it excludes small JSON manifests and the optional retained source/baseline files on disk. GPU payload adds the resident dense page table, row/layer padding and dummy textures, but excludes browser/driver overhead. Thus the storage and GPU columns intentionally differ. All-group totals count each brick once.

The UI displays each group's bytes and supports multiple selections. It releases old textures and rebuilds only selected groups. On Woodbranch, all groups use about 745.94 MiB, the largest connected group about 350.50 MiB, and no selected groups still retain the 32 MiB page table. This is selection-based residency, not demand streaming or a cache. Small groups may remain dominated by page-table overhead.

## Reproduce

See [the guide](../../docs/LARGE_VOLUMES.md). Run the exporter/grouping/verification commands, start the HTTP server, and use the standalone viewer's color preset “内部结构彩色” and benchmark button for each grouped manifest. Save the JSON reports here as `<dataset>-rendering.json`, then run `python summarize_grouped_results.py`.

The comparison page dataset selector exposes all five grouped datasets plus the existing Skull path. The original Skull SLIC experiment remains a separate algorithm baseline.
"""
    text += "\n## Visual checks\n\nThe interactive screenshot uses the surface preset for visibility; benchmark JSON records the internal-structure preset used for timing.\n\n![Reference and grouped viewer](bonsai-comparison.png)\n\n"
    text += " · ".join(f"[{name} projection comparison]({name}-projections.png)" for name in ['bonsai','foot','engine','kingsnake','woodbranch']) + "\n"
    (ROOT/'RESULTS.md').write_text(text)
if __name__=='__main__':build()
