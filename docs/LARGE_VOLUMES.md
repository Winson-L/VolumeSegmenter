# Large-volume feasibility experiment

This experiment isolates storage and rendering from semantic segmentation. It uses **strict intensity > cutoff**, not SLIC or an anatomical classifier. It retains every selected sample at its original location and original uint8/uint16 precision. It does not downsample the full-resolution export. Visual equivalence is scoped to the same display cutoff and transfer function; discarded data cannot be recovered by changing the display later.

## Representation

- Bounded batches of source chunks, or sequential RAW slabs, are processed on CPU. There is no full input, label, or reconstruction array.
- Occupied grid cells are tightly cropped and their samples concatenated. Holes inside the cropped box remain zero. No additional voxel deletion is performed.
- The GPU stores those concatenated samples in an integer R8UI/R16UI 2D array texture. Layers bypass the capacity of one 2D texture; balanced rows add only final-row padding per layer; a crop does not get padded to a fixed-size 3D slot.
- An RGBA32UI 3D page table stores each cell's payload offset, crop origin, and crop extent. Entries cost 16 bytes per grid cell, including empty cells. This remains a scaling limitation; it is not a sparse tree.
- The shader skips absent cells, fetches present samples by their original coordinates, and uses physical voxel spacing. This experiment uses nearest-neighbor sampling. Trilinear interpolation would require a new boundary strategy and new image checks.
- One selected volume must still fit in the packed texture and the experimental 1 GiB texture budget. Runtime streaming, mixed LOD and cross-chunk SLIC merging are **not implemented** here.

## Sources

- [Open SciVis RAW collection](http://klacansky.com/open-scivis-datasets/)
- [OME-Zarr Open SciVis catalog](https://github.com/InsightSoftwareConsortium/OMEZarrOpenSciVisDatasets)
- [Kingsnake original rendering](https://www.digimorph.org/specimens/Lampropeltis_getula/egg/whole/)
- [Woodbranch DVR example](https://kilnrender.com/gallery)

The importer validates decoded chunk sizes. On 2026-10-21, some Kingsnake OME-Zarr chunks had payload sizes inconsistent with their declared chunk shape. The validated experiment therefore uses the original RAW download for Kingsnake. Woodbranch uses the public OME-Zarr source. HTTP 404 chunk keys mean the metadata's fill value under Zarr semantics; other network failures are retried and then fail the export. Missing metadata is always an error. These distinctions matter: do not reinterpret arbitrary fetch failures as empty volume.

## Reproduce

```sh
pip install -r requirements-lock.txt
mkdir -p experiments/large-volumes
curl -L --fail --retry 2 \
  http://klacansky.com/open-scivis-datasets/kingsnake/kingsnake_1024x1024x795_uint8.raw \
  -o experiments/large-volumes/kingsnake-original.raw
python large_volume.py export --name kingsnake --cutoff 40 --save-original \
  --raw experiments/large-volumes/kingsnake-original.raw \
  --output experiments/large-volumes/kingsnake40
python large_volume.py export --name woodbranch --cutoff 7000 \
  --output experiments/large-volumes/woodbranch7000
python verify_large_volume.py experiments/large-volumes/kingsnake40
python verify_large_volume.py experiments/large-volumes/woodbranch7000
python -m http.server 8765 --bind 127.0.0.1
```

Use an empty output directory on each export. A failed run does not produce a completed manifest. The RAW download plus saved Kingsnake reference require two 795 MiB files. Woodbranch reads source chunks without saving a 16 GiB RAW. Three orthogonal reference MIPs are accumulated during input processing.

Open `http://127.0.0.1:8765/large_volume.html` for Kingsnake, or `http://127.0.0.1:8765/large_volume.html?manifest=./experiments/large-volumes/woodbranch7000/metadata.json` for Woodbranch.

## Measurements and interpretation

The exporter records original sample bytes, selected voxel count, tight-crop payload, fixed-cell equivalent bytes, page-table bytes, transfer bytes, elapsed time, peak process RSS, source chunk hash chain and output file hashes. RSS includes preprocessing allocations; it excludes the browser and OS file cache outside the process. Input download time is outside RAW export time.

The independent verifier checks bounds, non-overlapping contiguous payload intervals, hashes, the exact selected intensity histogram and three complete orthogonal MIPs. If a full RAW reference exists, every stored crop is also compared with its corresponding original region. MIP equality is not a DVR framebuffer comparison and neither establishes anatomical significance.

The browser benchmark uses sequential original/compact modes, three fixed views, 640×480, five warmups and 20 GPU queries per view/mode. Original and compact draw from the same voxel lattice with the same threshold, window and physical spacing. Framebuffer differences are recorded where a full reference can be loaded. GPU milliseconds are measured asynchronously; `1000/ms` is only a GPU throughput estimate, not screen FPS. Network, hashing and upload are excluded from GPU timings. Other running apps and background GPU load can affect measurements.

An original texture exceeding the 1 GiB experiment budget or device dimensions is **skipped before allocation**, with the reason recorded. That is not an observed OOM. A 16 GiB original is especially impractical on the tested M4/16 GiB unified-memory machine, but this experiment does not deliberately crash the browser to prove it.

Cutoff 40 (Kingsnake) and 7000 (Woodbranch) are explicit exploratory targets, informed by small previews. They do not establish a universally correct foreground threshold. Woodbranch's high-intensity selection is especially restrictive: distinguish preservation under that display cutoff from preservation of the complete lower-intensity wood structure. A useful follow-up is a threshold/quality/budget sweep and comparison with content-based selection, not simply maximizing the reduction ratio.

## Side-by-side reference viewer

Open `compare_volumes.html?dataset=kingsnake` for full-resolution original versus pipeline, with shared arcball, window, display threshold and step, and per-panel live FPS/GPU time. The dataset selector also keeps the existing Skull comparison available.

Open `compare_volumes.html?dataset=woodbranch` for the [Kiln Gallery](https://kilnrender.com/gallery) Woodbranch DVR image beside the live full-resolution pipeline. Kingsnake also offers the Gallery's MIP image via the reference selector. Images load directly from the credited source; an offline or failed image load shows a source-link fallback. These are **external appearance references**, with different camera and transfer settings, not pixel-equality controls. Only interactive panels rotate; static references have no FPS or GPU-memory measurement.

The attempted Woodbranch source scale-2 reference was rejected because decoded chunk size disagreed with metadata. No invalid low-resolution source is displayed. Lowering the display threshold below the export cutoff cannot restore omitted pipeline voxels.

## Grouped experiments and shared transfer function

The latest grouped comparison and raw measurements are in [grouped-results](../experiments/grouped-results/RESULTS.md). The viewer now offers Bonsai, Foot and Engine as well as Kingsnake and Woodbranch. Both interactive sides share three editable RGB/extinction control points; the static external reference cannot share those settings.

Reproduce the three additional small examples (downloads, SHA-512 verification, threshold extraction, automatic dense/masked storage, grouping and exact reconstruction checks):

```sh
python prepare_examples.py
```

For the existing large sources, use fresh directories:

```sh
python group_large_volume.py experiments/large-volumes/kingsnake40 experiments/large-volumes/kingsnake-groups --edges 90 160
python large_volume.py export --name woodbranch --cutoff 5000 --output experiments/large-volumes/woodbranch5000
python verify_large_volume.py experiments/large-volumes/woodbranch5000
python group_large_volume.py experiments/large-volumes/woodbranch5000 experiments/large-volumes/woodbranch-groups --edges 6000 9000
python verify_large_groups.py experiments/large-volumes/kingsnake-groups experiments/large-volumes/kingsnake40
python verify_large_groups.py experiments/large-volumes/woodbranch-groups experiments/large-volumes/woodbranch5000
```

The grouping operates on the graph of retained 16³ brick cells, with median-intensity bands and six-neighbor edges. It does not run full-volume SLIC or infer tissue identity. Individual groups are the nine largest brick-graph components; the remaining components are explicitly pooled by intensity band. No component is discarded during grouping. Every brick has one owner, so selections are disjoint and totals are additive without duplication. A logical AABB never allocates a parent dense volume.

An automatic storage decision compares dense-crop bytes against packed selected samples plus an eight-byte prefix/occupancy record per 32 crop positions. Each record contains an absolute sample offset and a 32-bit occupancy mask; shader rank calculation restores exact within-crop coordinates. The page table still costs 16 bytes per full grid cell. No values are quantized or removed by mask packing.

A group file contains samples, an optional mask and compact cell entries. The renderer concatenates only selected groups, remaps their offsets, and releases the previous GPU textures. CPU download/hash buffers are temporary, not part of the reported GPU figure. Large groups are fetched again when selected; this is not an LRU streaming cache. Selecting nothing retains the page table. The UI reports both combined file payload and actual allocated texture payload.

The old >7000 Woodbranch run and its results remain historical baselines; the new grouped comparison uses >5000. That preserves more source voxels, but neither threshold has semantic validation. Raising display transparency cannot recover excluded source values.
