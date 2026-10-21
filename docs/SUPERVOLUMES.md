# Content-driven logical volumes

The pipeline separates **candidate regions**, **selection**, and **storage**. A region groups nearby similar scalar values. Selection decides which voxels to export. Spatial packing then preserves that selection exactly. The runtime does not need the original volume or analysis cache.

## Why this implementation

| Method | What it offers | Decision for this PoC |
|---|---|---|
| 3D SLIC / SSLIC | Local intensity + spatial clustering with connectivity | Use scikit-image SLIC as the candidate generator, not a tissue classifier |
| Global XYZ/intensity K-means | Simple grouping; potentially disconnected, broad bounding boxes | Retain historical baseline; not the new storage representation |
| Connected threshold / confidence connected | Seed-based region growth, established ITK implementation | Use fixed target/support constraints on a region graph; optional fixed seed histogram anchor prevents progressive intensity drift |
| Watershed | Boundary-driven partition; marker selection affects results | Alternative for data with strong gradients; not established as superior on this dataset |
| Random walker | Seeded probabilistic segmentation | Useful future comparison; full-volume solver cost and seed requirements are unnecessary for this first experiment |
| VDB / sparse tree | Sparse storage and traversal, not automatic anatomy recognition | Use a simple brick page table and metadata BVH; no dependency on VDB or VTK |

Sources: [SLIC API (3D scalar, spacing and connectivity)](https://scikit-image.org/docs/stable/api/skimage.segmentation.html#skimage.segmentation.slic), [SSLIC paper](https://arxiv.org/abs/1806.08741), [region adjacency graph example](https://scikit-image.org/docs/stable/auto_examples/segmentation/plot_rag_merge.html), [ITK connected threshold](https://simpleitk.org/doxygen/latest/html/classitk_1_1simple_1_1ConnectedThresholdImageFilter.html), [ITK confidence connected](https://simpleitk.org/doxygen/latest/html/classitk_1_1simple_1_1ConfidenceConnectedImageFilter.html), [ray-guided sparse rendering](https://pmc.ncbi.nlm.nih.gov/articles/PMC4260263/), [NanoVDB](https://www.openvdb.org/documentation/doxygen/NanoVDB_FAQ.html).

This is a scoped engineering choice, not evidence that SLIC is universally best. The demo has no anatomical ground-truth labels. RAW uint8 values are not assumed to be HU. Bone, soft tissue, vessels and artifacts can have overlapping scalar distributions.

## Run

```bash
pip install -r requirements-lock.txt
python supervolume.py analyze --input skull_256x256x256_uint8.raw \
  --shape 256 256 256 --output experiments/supervolume/analysis
python supervolume.py export --input skull_256x256x256_uint8.raw \
  --analysis experiments/supervolume/analysis --config configs/skull-candidates.json \
  --output experiments/supervolume/selected --brick-size 16
python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/sparse_volume.html`. The viewer reads only the selected export. The original is never fetched by this viewer. Full original-sized reconstruction is allocated only when explicitly running the matched monolith benchmark.

For repeat runs, choose empty output folders. Change the viewer manifest using `?manifest=./experiments/supervolume/my-selection/metadata.json`. Extraction is offline/in-memory, not out of core.

## Choose a target

Open `http://127.0.0.1:8765/region_inspector.html`. Move the Z slice, click one or more regions, adjust the fixed intensity interval, minimum support and boundary contrast, and inspect the cyan preview. Yellow indicates seed regions. Download the config and pass it to `supervolume.py export`. The preview is a slice of a 3D graph selection, not a 2D flood fill.

The inspector needs the analysis cache and original to make a selection. These are working inputs and are not bundled into the selected export. Alternate inputs use `?analysis=./path/to/cache/&input=./path/to/input.raw`. Its displayed CLI example is for the included skull; use your own paths for other inputs. The inspector exports one group per config; combine multiple group entries in JSON for multi-target exports.

For CLI inspection:

```bash
python supervolume.py inspect --analysis experiments/supervolume/analysis --xyz 128 128 128
```

A group can be specified as:

```json
{
  "groups": [{
    "name": "My selected structure",
    "mode": "seeded",
    "seeds_xyz": [[128, 128, 128]],
    "intensity_range": [61, 255],
    "min_fraction": 0.1,
    "max_boundary_delta": 40,
    "clip_to_range": true
  }]
}
```

The coordinate is illustrative, not a validated bone seed. `configs/skull-seeded.json` is a reproducible graph-growth demonstration using the region with the most >60 voxels in the saved analysis parameters; it is not an anatomical annotation. Region IDs depend on the SLIC parameters and library version.

## Exact selection rules

1. SLIC considers normalized scalar intensity and spatial proximity. `--region-size` controls approximate supervoxel scale independently of storage brick size; `--compactness` controls spatial regularity. No smoothing or decimation is applied. SLIC's size/connectivity enforcement can merge small features into surrounding regions; it does not guarantee semantic boundary preservation.
2. Each region stores its exact 256-bin histogram, median, p10/p90 and voxel count. The graph uses face adjacency and mean absolute scalar difference across shared voxel faces.
3. A region is eligible when it has at least one in-range voxel and its fraction of in-range voxels is at least `min_fraction`. Bounds are inclusive.
4. `all_candidates` selects every eligible region, including disconnected ones. `seeded` selects only those reachable from explicit seed regions through eligible neighbors and acceptable boundary contrast. This is region connectivity; range clipping can leave disconnected voxel fragments inside those regions.
5. Optional `max_seed_histogram_distance` (0–1) bounds total variation distance to the pooled fixed seed histogram. It requires seeds. It is intentionally fixed, not updated after growth. Full 256-bin distance may be sensitive to noise; it is optional and is not used by the demo presets.
6. `clip_to_range: true` additionally removes out-of-range voxels inside accepted regions. Set false to retain all nonzero voxels of accepted regions. Zero is the sparse background; zero-valued semantic membership is not exported.
7. When group masks overlap, earlier config groups own the shared voxels. Export reports the overlap count. A voxel is stored once; logical AABBs can overlap without double opacity accumulation.

**The support fraction can discard thin or minority structures.** Do not describe such removal as confirmed noise. The saved sensitivity sweep quantifies losses; no shape/density rule has been proven to identify anatomical importance.

## Storage and rendering

The selected field is divided into 8³/16³/32³ grid cells. Each occupied cell is tightly cropped for disk storage. `density.raw` stores retained values and zero padding inside those crops; `owners.raw` stores one byte per stored voxel for logical-group ownership. The latter has a real storage/CPU cost and is included in totals. Metadata contains offsets, local dimensions, original coordinates, group membership and an AABB hierarchy over leaf references. Parents never allocate dense arrays.

The viewer packs selected cells into an R8 3D atlas with fixed-size slots and an R32UI page table. Atlas padding means GPU payload can exceed tightly cropped density file size. Group ownership stays on the CPU; changing selection repacks only chosen voxels and releases the previous textures. CPU export buffers and transient repacking arrays are not counted as GPU payload. This version does not stream leaves from disk or implement a memory-budget cache.

Ray marching skips absent cells and caches page lookup within a cell. Sampling stays aligned to the original voxel lattice. Logical BVH metadata organizes exports; the current shader traverses the grid/page table, not the BVH. Nearest sampling avoids cross-slot interpolation; trilinear/gradient rendering would require border handling. Spacing affects SLIC distances; the current renderer still uses voxel coordinates, not calibrated physical millimeters.

## Validation

`python -m unittest discover -s tests -v` covers graph drift, fixed seed histograms, boundaries, invalid seeds, overlapping groups, empty/dense/non-cubic arrays, thin features, partial edge bricks, exact reconstruction, BVH leaf coverage, SLIC repeatability and input-cache binding.

The Compare button measures all groups and each group against a dense reconstruction of **identical selected voxels**, using three seeded-shuffled rounds, 20 timed frames and five warmups per case. It first compares GPU framebuffers at three camera orientations. Equality here validates representation, not selection against the original. Timings exclude loading/repacking. Small differences and cross-session differences should not be treated as general speedups.
