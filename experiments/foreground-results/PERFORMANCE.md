# Foreground rendering comparison

125 cases, three seeded shuffled rounds per case, 20 GPU samples after five warmups per round: 7,500 valid GPU timings. Fixed 1280×720, camera 90/0/1.8, step 1 original voxel unit, cutoff 60. Same browser session and shader. GPU timer queries, not inferred FPS. Download/upload and extraction time excluded. This is one device/session/view, not a general performance guarantee.

Memory below is resident R8 texture payload, not total physical VRAM or process RAM. All hidden-resident controls retain every block texture. Full-resolution monolith controls reconstruct voxel-identically to their corresponding selected blocks, verified before measurement. Each ROI control clips the same selected monolith to that block’s original bounds.

## All-content comparison

| Variant | Blocks MiB | Blocks GPU ms | Round median range ms | Selected monolith MiB | Selected monolith GPU ms |
|---|---:|---:|---:|---:|---:|
| threshold | 16.000 | 8.783 | 7.461–9.265 | 16.000 | 8.749 |
| conservative | 14.427 | 8.775 | 6.833–10.695 | 16.000 | 8.723 |
| focused | 11.578 | 7.250 | 6.556–7.806 | 16.000 | 8.690 |
| opening | 15.686 | 8.940 | 8.193–9.659 | 16.000 | 8.480 |
| legacy_cleanup | 14.408 | 8.547 | 8.080–8.893 | 14.546 | 7.919 |
| aggressive | 6.457 | 5.911 | 5.625–6.155 | 14.231 | 7.996 |
| focused_decimated | 1.454 | 8.046 | 7.690–8.216 | — | — |

Original unfiltered monolith: 16 MiB, 8.649 ms. All times are medians of 60 samples. The conservative all-block round medians vary substantially (6.833–10.695 ms), so small differences should not be treated as reliable wins.

Focused all-block rendering used 27.64% less payload than its selected monolith and took 16.57% less GPU time in this run. Aggressive is smaller and faster but deletes 76.81% of original >60 voxels; it is not an equal-quality comparison to the original. Decimation uses the same marching step of 1, so reducing texture dimensions does not reduce ray sample count automatically. It did not improve all-block time here.

## Every block and matched ROI

Block numbering and bounds differ between presets. Rows compare corresponding content only within a preset. Rendering one block shows less content than rendering all eight; individual timings must not be summed to predict simultaneous rendering.

| Case | Resident MiB | GPU median ms | Round medians ms |
|---|---:|---:|---|
| original | 16.0000 | 8.649 | 8.463, 8.756, 9.198 |
| threshold/all | 16.0000 | 8.783 | 7.461, 9.265, 8.783 |
| threshold/block_1 | 2.0000 | 1.560 | 1.565, 1.556, 1.571 |
| threshold/monolith_roi_1 | 16.0000 | 1.557 | 1.555, 1.568, 1.561 |
| threshold/block_2 | 2.0000 | 1.573 | 1.589, 1.571, 1.572 |
| threshold/monolith_roi_2 | 16.0000 | 1.570 | 1.536, 1.574, 1.573 |
| threshold/block_3 | 2.0000 | 2.176 | 2.249, 2.092, 2.193 |
| threshold/monolith_roi_3 | 16.0000 | 2.160 | 2.126, 2.116, 2.187 |
| threshold/block_4 | 2.0000 | 1.909 | 2.034, 1.899, 1.870 |
| threshold/monolith_roi_4 | 16.0000 | 1.947 | 1.974, 1.898, 1.998 |
| threshold/block_5 | 2.0000 | 1.414 | 1.454, 1.401, 1.417 |
| threshold/monolith_roi_5 | 16.0000 | 1.405 | 1.410, 1.399, 1.418 |
| threshold/block_6 | 2.0000 | 1.618 | 1.740, 1.493, 1.604 |
| threshold/monolith_roi_6 | 16.0000 | 1.473 | 1.458, 1.521, 1.608 |
| threshold/block_7 | 2.0000 | 2.477 | 2.337, 2.463, 2.589 |
| threshold/monolith_roi_7 | 16.0000 | 2.614 | 2.625, 2.646, 2.325 |
| threshold/block_8 | 2.0000 | 3.067 | 3.084, 3.045, 2.985 |
| threshold/monolith_roi_8 | 16.0000 | 3.078 | 3.073, 3.104, 2.808 |
| threshold/hidden_others_resident | 16.0000 | 1.565 | 1.572, 1.559, 1.563 |
| threshold/monolith_all | 16.0000 | 8.749 | 8.725, 8.912, 8.784 |
| conservative/all | 14.4269 | 8.775 | 6.833, 7.340, 10.695 |
| conservative/block_1 | 12.0000 | 5.786 | 5.786, 5.842, 5.796 |
| conservative/monolith_roi_1 | 16.0000 | 6.031 | 6.189, 5.910, 6.154 |
| conservative/block_2 | 0.6282 | 0.937 | 0.911, 0.966, 0.936 |
| conservative/monolith_roi_2 | 16.0000 | 0.993 | 1.026, 0.890, 0.955 |
| conservative/block_3 | 0.2070 | 0.624 | 0.625, 0.622, 0.621 |
| conservative/monolith_roi_3 | 16.0000 | 0.623 | 0.623, 0.624, 0.622 |
| conservative/block_4 | 0.4252 | 0.786 | 0.789, 0.787, 0.780 |
| conservative/monolith_roi_4 | 16.0000 | 0.780 | 0.782, 0.772, 0.781 |
| conservative/block_5 | 0.0032 | 0.363 | 0.361, 0.365, 0.364 |
| conservative/monolith_roi_5 | 16.0000 | 0.364 | 0.363, 0.364, 0.365 |
| conservative/block_6 | 0.0403 | 0.395 | 0.395, 0.395, 0.395 |
| conservative/monolith_roi_6 | 16.0000 | 0.397 | 0.398, 0.397, 0.396 |
| conservative/block_7 | 0.1582 | 0.476 | 0.475, 0.478, 0.474 |
| conservative/monolith_roi_7 | 16.0000 | 0.475 | 0.477, 0.475, 0.477 |
| conservative/block_8 | 0.9648 | 1.431 | 1.420, 1.441, 1.433 |
| conservative/monolith_roi_8 | 16.0000 | 1.514 | 1.517, 1.515, 1.493 |
| conservative/hidden_others_resident | 14.4269 | 5.658 | 5.869, 5.628, 5.603 |
| conservative/monolith_all | 16.0000 | 8.723 | 8.462, 8.845, 8.809 |
| focused/all | 11.5775 | 7.250 | 6.556, 7.806, 7.533 |
| focused/block_1 | 1.4569 | 1.330 | 1.341, 1.370, 1.198 |
| focused/monolith_roi_1 | 16.0000 | 1.397 | 1.404, 1.402, 1.384 |
| focused/block_2 | 0.3743 | 0.877 | 0.874, 0.880, 0.878 |
| focused/monolith_roi_2 | 16.0000 | 0.875 | 0.874, 0.874, 0.875 |
| focused/block_3 | 0.2074 | 0.774 | 0.772, 0.776, 0.775 |
| focused/monolith_roi_3 | 16.0000 | 0.778 | 0.778, 0.777, 0.780 |
| focused/block_4 | 1.1553 | 1.339 | 1.325, 1.349, 1.334 |
| focused/monolith_roi_4 | 16.0000 | 1.335 | 1.332, 1.338, 1.336 |
| focused/block_5 | 0.4138 | 0.491 | 0.487, 0.567, 0.491 |
| focused/monolith_roi_5 | 16.0000 | 0.494 | 0.546, 0.488, 0.521 |
| focused/block_6 | 0.4230 | 0.643 | 0.644, 0.635, 0.643 |
| focused/monolith_roi_6 | 16.0000 | 0.645 | 0.645, 0.650, 0.640 |
| focused/block_7 | 3.5469 | 3.737 | 3.883, 3.777, 3.501 |
| focused/monolith_roi_7 | 16.0000 | 4.068 | 4.171, 4.105, 3.959 |
| focused/block_8 | 4.0000 | 4.537 | 4.495, 4.559, 4.454 |
| focused/monolith_roi_8 | 16.0000 | 4.558 | 4.560, 4.703, 4.416 |
| focused/hidden_others_resident | 11.5775 | 1.214 | 1.200, 1.349, 1.354 |
| focused/monolith_all | 16.0000 | 8.690 | 8.625, 8.819, 8.485 |
| opening/all | 15.6858 | 8.940 | 8.193, 8.697, 9.659 |
| opening/block_1 | 8.0000 | 5.774 | 5.815, 5.616, 5.966 |
| opening/monolith_roi_1 | 16.0000 | 5.819 | 6.187, 5.766, 5.294 |
| opening/block_2 | 1.3828 | 0.817 | 0.811, 0.857, 0.810 |
| opening/monolith_roi_2 | 16.0000 | 0.804 | 0.801, 0.804, 0.844 |
| opening/block_3 | 0.4766 | 0.504 | 0.504, 0.502, 0.506 |
| opening/monolith_roi_3 | 16.0000 | 0.504 | 0.504, 0.504, 0.505 |
| opening/block_4 | 0.6709 | 1.369 | 1.369, 1.544, 1.145 |
| opening/monolith_roi_4 | 16.0000 | 1.546 | 1.539, 1.531, 1.613 |
| opening/block_5 | 0.7236 | 1.439 | 1.449, 1.418, 1.441 |
| opening/monolith_roi_5 | 16.0000 | 1.431 | 1.393, 1.448, 1.436 |
| opening/block_6 | 3.3750 | 3.922 | 3.768, 4.004, 3.871 |
| opening/monolith_roi_6 | 16.0000 | 3.925 | 3.797, 3.953, 3.834 |
| opening/block_7 | 0.7844 | 1.210 | 1.212, 1.221, 1.197 |
| opening/monolith_roi_7 | 16.0000 | 1.239 | 1.191, 1.242, 1.250 |
| opening/block_8 | 0.2725 | 0.571 | 0.579, 0.568, 0.572 |
| opening/monolith_roi_8 | 16.0000 | 0.573 | 0.574, 0.574, 0.572 |
| opening/hidden_others_resident | 15.6858 | 5.460 | 5.213, 5.359, 5.709 |
| opening/monolith_all | 16.0000 | 8.480 | 8.741, 8.286, 8.450 |
| legacy_cleanup/all | 14.4076 | 8.547 | 8.080, 8.680, 8.893 |
| legacy_cleanup/block_1 | 7.2732 | 5.149 | 4.891, 4.788, 5.372 |
| legacy_cleanup/monolith_roi_1 | 14.5464 | 4.962 | 4.936, 5.024, 4.996 |
| legacy_cleanup/block_2 | 0.0834 | 0.383 | 0.383, 0.382, 0.383 |
| legacy_cleanup/monolith_roi_2 | 14.5464 | 0.384 | 0.385, 0.383, 0.383 |
| legacy_cleanup/block_3 | 0.1086 | 0.390 | 0.390, 0.390, 0.389 |
| legacy_cleanup/monolith_roi_3 | 14.5464 | 0.390 | 0.389, 0.391, 0.390 |
| legacy_cleanup/block_4 | 0.3019 | 0.442 | 0.443, 0.440, 0.439 |
| legacy_cleanup/monolith_roi_4 | 14.5464 | 0.441 | 0.440, 0.442, 0.442 |
| legacy_cleanup/block_5 | 0.3406 | 0.460 | 0.461, 0.461, 0.458 |
| legacy_cleanup/monolith_roi_5 | 14.5464 | 0.460 | 0.462, 0.461, 0.460 |
| legacy_cleanup/block_6 | 0.4161 | 0.477 | 0.475, 0.478, 0.480 |
| legacy_cleanup/monolith_roi_6 | 14.5464 | 0.476 | 0.478, 0.474, 0.476 |
| legacy_cleanup/block_7 | 0.4289 | 0.490 | 0.489, 0.492, 0.490 |
| legacy_cleanup/monolith_roi_7 | 14.5464 | 0.487 | 0.488, 0.486, 0.486 |
| legacy_cleanup/block_8 | 5.4549 | 5.543 | 5.580, 5.370, 5.570 |
| legacy_cleanup/monolith_roi_8 | 14.5464 | 5.596 | 5.617, 5.531, 5.582 |
| legacy_cleanup/hidden_others_resident | 14.4076 | 5.504 | 5.438, 5.426, 5.825 |
| legacy_cleanup/monolith_all | 14.5464 | 7.919 | 7.716, 8.021, 8.379 |
| aggressive/all | 6.4566 | 5.911 | 5.625, 5.882, 6.155 |
| aggressive/block_1 | 1.3236 | 1.173 | 1.170, 1.183, 1.173 |
| aggressive/monolith_roi_1 | 14.2314 | 1.167 | 1.169, 1.169, 1.153 |
| aggressive/block_2 | 0.1578 | 0.430 | 0.430, 0.431, 0.428 |
| aggressive/monolith_roi_2 | 14.2314 | 0.429 | 0.429, 0.428, 0.432 |
| aggressive/block_3 | 0.1021 | 0.395 | 0.397, 0.395, 0.394 |
| aggressive/monolith_roi_3 | 14.2314 | 0.396 | 0.397, 0.394, 0.396 |
| aggressive/block_4 | 0.8840 | 0.866 | 0.869, 0.863, 0.865 |
| aggressive/monolith_roi_4 | 14.2314 | 0.869 | 0.868, 0.872, 0.867 |
| aggressive/block_5 | 0.6857 | 0.925 | 0.934, 0.909, 0.939 |
| aggressive/monolith_roi_5 | 14.2314 | 0.902 | 0.913, 0.900, 0.902 |
| aggressive/block_6 | 0.2837 | 0.664 | 0.664, 0.663, 0.664 |
| aggressive/monolith_roi_6 | 14.2314 | 0.667 | 0.662, 0.668, 0.668 |
| aggressive/block_7 | 1.4995 | 1.291 | 1.319, 1.255, 1.316 |
| aggressive/monolith_roi_7 | 14.2314 | 1.323 | 1.327, 1.346, 1.298 |
| aggressive/block_8 | 1.5202 | 1.629 | 1.612, 1.614, 1.660 |
| aggressive/monolith_roi_8 | 14.2314 | 1.619 | 1.599, 1.624, 1.625 |
| aggressive/hidden_others_resident | 6.4566 | 1.171 | 1.168, 1.177, 1.177 |
| aggressive/monolith_all | 14.2314 | 7.996 | 8.094, 7.895, 8.000 |
| focused_decimated/all | 1.4545 | 8.046 | 8.216, 7.690, 8.046 |
| focused_decimated/block_1 | 0.1830 | 1.365 | 1.338, 1.378, 1.428 |
| focused_decimated/block_2 | 0.0488 | 0.886 | 1.041, 0.882, 1.057 |
| focused_decimated/block_3 | 0.0266 | 0.773 | 0.771, 0.774, 0.774 |
| focused_decimated/block_4 | 0.1453 | 1.314 | 1.310, 1.332, 1.311 |
| focused_decimated/block_5 | 0.0522 | 0.486 | 0.569, 0.483, 0.485 |
| focused_decimated/block_6 | 0.0534 | 0.633 | 0.636, 0.634, 0.624 |
| focused_decimated/block_7 | 0.4453 | 3.847 | 3.697, 4.098, 3.888 |
| focused_decimated/block_8 | 0.5000 | 4.912 | 4.947, 4.284, 5.008 |
| focused_decimated/hidden_others_resident | 1.4545 | 1.384 | 1.376, 1.374, 1.413 |

Most individual blocks and their matched monolith ROI controls have similar time. For focused block 1, independent loading uses 1.457 MiB / 1.330 ms; monolith ROI uses 16 MiB / 1.397 ms. Hiding other blocks without releasing them uses 11.578 MiB / 1.214 ms. Timing differences at this scale include run variability; hiding alone does not reduce resident payload.

## Reproduction and scope

Run `python -m pipeline.foreground_study --output experiments/foreground` in a fresh output directory, serve the repository, open `webgl_volume_rendering.html?study=foreground`, and click Compare. Use Download comparison JSON to export. The study generates matching cropped monolith controls alongside each full-resolution preset. [Raw report](rendering.json) includes every sample, per-run parameters, component coordinates, input hashes and browser identity. [Selection losses](RESULTS.md) are separate from rendering speed.

Spatial partitioning preserves all voxels of the selected full-resolution reference, including thin branches retained by connected filtering. It cannot recover a structure deleted by threshold/size filtering. Calling discarded regions unimportant requires a task-specific mask or annotated reference; intensity survival alone does not establish that.
