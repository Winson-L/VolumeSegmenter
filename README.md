# VolumeSegmenter

A proof of concept for **tightly cropped local volume blocks, original-space coordinates, and simultaneous or selective WebGL2 rendering**.

The current experiment asks:

1. Is rendering one block faster than rendering the whole dataset?
2. How do all-block and single-block rendering differ in GPU time and resident texture payload?
3. Does hiding a block save memory, or must its texture be released?

## Current design

The default extractor recursively divides space along axis-aligned planes, discards empty space and tightly crops each resulting block. Blocks have **disjoint bounding boxes**: each stores only its own local W×H×D array, with `origin_xyz` locating it in the original volume. The renderer uploads these local textures directly; it does not expand them to the original dimensions.

At each split, the heuristic tries quarter/midpoint/three-quarter cuts along each axis and prefers the largest decrease in total stored bounding-box voxels. Ties favor balanced child sizes and smaller surface area. This is not a guarantee of the globally smallest possible partition. `--components` is an upper bound, not a requirement to fabricate extra components.

At full resolution, the sum of block payloads cannot exceed the original uint8 volume. Every retained voxel is preserved exactly. This guarantee is relative to the **selected** input (threshold plus optional cleanup); background removal itself changes the original data. Optional decimation remains explicitly lossy.

On the included skull, the default threshold leaves nonzero data extending to block boundaries, so the eight blocks are each 128³ and total **16 MiB**, equal to the original. A single block is **2 MiB**. This corrects the previous K-means implementation's 60.96 MiB of overlapping bounding boxes. It does not claim a new full-volume compression gain where none exists.

## Foreground selection experiment

To remove unwanted regions before tight cropping, run `python foreground_study.py`, then open [the foreground viewer](http://127.0.0.1:8765/webgl_volume_rendering.html?study=foreground) with the local server running. The viewer supports all blocks and individual blocks for each preset. Use a fresh `--output` directory to repeat; pass its path as `&base=./experiments/run2/` in the viewer URL.

On this skull, threshold 30 plus removal of six-connected regions smaller than 512 voxels yields **14.43 MiB**; threshold 60 with the same region filter yields **11.58 MiB**, without downsampling. These are heuristic selections, not proof that every discarded voxel is noise. See [selection results and losses](experiments/foreground-results/RESULTS.md). The default extractor remains an unfiltered control so comparisons stay explicit.

## Run

Python 3.12+ and a WebGL2 browser:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
python -m unittest discover -s tests -v
python benchmark.py
python -m http.server 8765 --bind 127.0.0.1
```

On Windows use `.venv\Scripts\activate`. Open [the viewer](http://127.0.0.1:8765/webgl_volume_rendering.html).

The benchmark generates five variants under `experiments/spatial/`: original, background/crop, full-resolution spatial blocks, decimated blocks, and a decimated single-volume baseline. Existing outputs are never silently overwritten. To repeat use `python benchmark.py --output experiments/run2` and open `webgl_volume_rendering.html?base=./experiments/run2/`.

### Viewer controls

- **Load all components:** simultaneously render all local block textures.
- **Only N:** show one block at its original position, without changing camera or resolution.
- **Release unchecked textures** (default on): delete unselected GPU textures and unbind them. Selecting a released block fetches and uploads it again. Application CPU copies are not cached after upload; browser HTTP caching is separate.
- With release **off**, unselected textures stay resident. Their rendering is disabled, but their payload remains in the memory counter. Turning release back on evicts unselected textures.
- **Measure 60 frames:** measure the current selection/settings.
- **Compare original / all / each block:** run three shuffled rounds of all cases at fixed settings, including hidden-but-resident and same-ROI monolithic controls.
- **Download comparison JSON:** export per-frame GPU samples, per-round results, settings and texture byte accounting.

The renderer marches only through the ray interval intersecting active blocks. It preserves the original volume's sampling lattice, camera and voxel scale when comparing selections. The active sampler list is compacted: one selected block means one active texture branch, not eight disabled checks per sample.

### What “memory” means here

The panel reports the **resident R8 texture payload**: the sum of stored voxel counts of textures owned by the application. It also records a one-byte dummy texture separately. Hiding seven blocks while retaining their textures still consumes all eight payloads; releasing them leaves one.

This is exact application payload accounting, **not a measurement of total physical GPU memory**. Browser/driver allocation overhead, alignment, framebuffer storage, shader resources and deferred reclamation are excluded. Total GPU allocation is recorded as `null`, not invented from file size. Timing excludes download/upload and reconstruction.

## Results and methodology

See [the current experiment report](experiments/spatial-results/RESULTS.md), [extraction metrics](experiments/spatial-results/extraction.json) and [rendering measurements](experiments/spatial-results/rendering.json).

The comparison uses full-resolution blocks without decimation: fixed 1280×720 drawing buffer, camera X=90°/Y=0°/distance=1.8, step=1 original voxel unit and cutoff=60. Each case has three rounds, five warm-up frames and 20 timed frames per round. Case order is shuffled with a fixed seed. GPU timings use timer queries and reject disjoint results; CPU submission timings are not mislabeled as GPU time or FPS.

A single block shows less content than all blocks. To separate that effect from representation, the suite also compares block 1 with the **same region clipped from the thresholded monolithic volume**, at identical camera and sampling settings. Display cutoff 60 exceeds the extraction threshold, so the original/full-block visual comparison does not establish preservation of discarded low-intensity data.

## Custom extraction

```bash
python extractVolume.py --input input.raw --shape 320 240 128 \
  --output experiments/custom --components 8 --threshold 20
```

Open `webgl_volume_rendering.html?manifest=./experiments/custom/metadata.json`. The predefined dataset selector and multi-dataset comparison are disabled for custom manifests; individual measurement still works.

- Input is uint8 RAW, X varying fastest. CLI dimensions are **X Y Z**; NumPy arrays are **Z Y X**. File length must match exactly.
- Omit `--threshold` for the seeded two-population intensity heuristic. This is not anatomical segmentation.
- `--strategy spatial` is the default. `--strategy kmeans` retains the previous method for controlled comparison; it has no disjoint-box/storage guarantee. Spatial weights only affect K-means.
- `--cleanup connected --min-region-voxels 512` removes small six-connected foreground regions after thresholding. Retained regions keep their thin branches. `opening` additionally applies a 3³ morphological opening; `legacy` audits the old border removal and erosion. Both can destroy thin structures. `none` is the default.
- `--downsample 2` keeps every second voxel on every axis, without anti-aliasing. It can remove thin structures and is not lossless compression.
- `--mode crop` generates a single foreground bounding box; `--mode original` skips thresholding.

### Metadata schema 2

Each component records:

| Field | Meaning |
| --- | --- |
| `dimensions_xyz` | Stored local texture width, height, depth |
| `origin_xyz` | Local box origin in original voxel coordinates |
| `extent_xyz` | Exclusive spatial extent before decimation |
| `spacing_xyz` | Sample spacing in original voxel units; `[1,1,1]` at full resolution |
| `bytes`, `sha256` | Payload size and reproducibility hash |

For a world point `p`, local sample index is `floor((p-origin)/spacing)`. Reconstruction clips the last sample block to `extent_xyz`. The manifest also retains original volume dimensions, input hash, parameters and processing time. No physical millimeter spacing or rotation is claimed.

## Validation and limits

Tests cover non-cubic/boundary coordinates, tight disjoint boxes, storage budgets, exact reconstruction, empty/tiny inputs, deterministic output, explicit decimation and input validation. The spatial algorithm is deterministic; numerical libraries are limited to one thread for background/K-means repeatability. Cross-platform/library bitwise equivalence is not promised.

Only one real dataset plus synthetic fixtures has been tested. The extractor is not out of core and has no proven peak-RAM ceiling. The viewer supports at most 15 components, device texture limits and 8,192 steps per ray. Nearest sampling is used for an explicit CPU/GPU mapping. More blocks, streaming and adaptive resolution need separate experiments.

Historical experiments remain under `experiments/results/` (the earlier K-means implementation) and `experiments/legacy/` (original source/metadata). Their timings use a different renderer/resolution and must not be compared directly with the current report. The original `skull/` RAW files and historical screenshots remain unchanged. No new dataset provenance or license grant is asserted.
