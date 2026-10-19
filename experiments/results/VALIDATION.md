# Validation record — 2026-10-19

## Automated correctness checks

`python -m unittest discover -s tests -v`: **8 tests passed**.

Checks cover exact reconstruction on non-cubic data with boundary structures; empty and single-voxel inputs; complete prediction beyond the 30,000-point training sample; repeatable component hashes with a fixed seed; the effect of spatial/intensity weights; decimated origins, spacing and clipped extents; original/thresholded baselines; and rejection of incorrect input sizes or existing output results.

A repeated-run test initially exposed last-bit differences in the automatically estimated threshold from parallel numerical reductions. Extraction now limits numerical libraries to one thread and records the threshold rounded to six decimals. The tests pass with the recorded dependency versions. Reproducibility does not include timing fields or promise identical results across all library/platform versions.

The skull benchmark separately confirms zero missing, introduced or overlapping nonzero voxels for full-resolution extraction relative to the thresholded input. See [skull-report.json](skull-report.json). Decimated outputs have explicit quality loss and overlaps, which are reported rather than treated as exact reconstruction.

## Browser checks

Validated in Chrome 154 on macOS, with actual WebGL2 rendering:

- All five generated variants loaded without shader or texture errors.
- Original and full-resolution partitions align at a shared camera and scale.
- All eight components were switched on individually, with the other seven off. At cutoff 0, each changed the canvas-only screenshot from the all-off baseline; [component-checks.json](component-checks.json) records hashes. This is a sampler-coverage smoke test, not a pixel-accurate GPU reconstruction test.
- Component 8 was visually inspected separately; see [component-8.jpg](component-8.jpg).
- Empty 11×9×7 input produced zero components and a blank background without WebGL warnings.
- A 31×23×17 synthetic fixture with boxes at opposite corners and one central marker rendered in the expected relative positions; see [non-cubic.jpg](non-cubic.jpg). Exact spatial mapping is also tested numerically on CPU.
- A nonexistent manifest produced a visible HTTP 404 message instead of an indefinite loading screen.
- Custom manifests display their own mode/decimation label and disable the predefined dataset selector.

The synthetic browser fixture used a ZYX array of shape `(17,23,31)`, initialized to zero, with `[0:5,0:5,0:5]=220`, `[12:17,18:23,26:31]=180`, and `[7:10,10:13,14:17]=255`. It was extracted with threshold 0, three components and no decimation. Temporary browser fixtures are not included as binary assets.

## GPU timing

One session, one 60-frame measurement per variant after ten warm-up frames. GPU duration uses `EXT_disjoint_timer_query_webgl2`; invalid/disjoint samples are discarded and queries deleted. All five runs returned 60 valid samples. Runs are serial and not randomized; these results should not be generalized to other devices or views.

Shared settings: drawing buffer **3420×1812**, camera **90°, 0°, 1.8**, ray step **1 original voxel unit**, density cutoff **60**, all components enabled. Each measurement JSON records browser/renderer information. The renderer exposes the generic `WebKit WebGL` name, so a specific GPU model is not asserted.

| Variant | Median GPU ms | Raw record |
| --- | ---: | --- |
| Original | 15.71 | [JSON](gpu-original.json) |
| Background + crop | 16.11 | [JSON](gpu-crop.json) |
| Full-resolution partitions | 82.73 | [JSON](gpu-partition.json) |
| Partitions + 2× decimation | 83.90 | [JSON](gpu-lossy.json) |
| Whole crop + 2× decimation | 16.29 | [JSON](gpu-decimated.json) |

The naive multi-volume shader is slower when displaying all partitions. These measurements establish no frame-rate improvement. The stored `raf_and_finish_median_ms` is a separate wall-clock scheduling diagnostic; it is not GPU time, sustained FPS, or a measure of network loading. The viewer renders on demand outside the measurement loop.

Screenshots use the same rendering settings, except the isolated-component smoke test uses cutoff 0 and the non-cubic fixture uses the default camera. Image similarity at cutoff 60 does not demonstrate preservation of lower-intensity data. Payload savings do not imply a quality-matched improvement over the original.
