# Beta 6 LiDAR tree-sizing hotfix

## LiDAR tree-sizing hotfix - 2026-10-20

- Regional themes now select tree models without replacing LiDAR-derived tree scales.
- Built-in and regional tree palettes share the same source crown-radius and height calculation.
- Standard (Lidar) and Heroic retain their established LiDAR mapping; Epic is 1.20 x Heroic and Mythic is 1.80 x Heroic on X/Y/Z.
- Profile scale defaults, per-asset scale distributions and uniform-scale settings no longer override generated tree sizing.
- Tree detection, coordinates, final-grid masks, playing-surface exclusions, OSM alignment and material presets are unchanged.
- Pacific Northwest is included in both the bundled and editable profile directories.
- All previous Beta 6 spline-surface and CFS/mask hotfixes remain included.

The existing processed LiDAR heightmap can be reused; this correction does not require repeating LiDAR processing.

This restores the established source-measurement-to-transform-scale mapping, not a new metre-for-metre calibration of every tree model. Different native models can have different unscaled dimensions.

**Approved executable:** the Windows EXE is promoted byte-for-byte from the successfully tested build, without recompilation. The public filename is `tgc_gui_2k25_beta6.exe`; its window title still includes `LiDAR Tree Size TEST 1` as the original build identifier. That label is expected in this hotfix.

## Validation and provenance

All eight retained Beta 6 source/workflow verifiers and the production tree-generation checks passed on Windows. The compiled EXE passed 44 regional-profile/mode combinations, extreme profile-size tests, source-value spacing, preset ratios and single-tree defaults. The maintainer subsequently confirmed the in-game test worked.

The source files and shipped EXE come from the same approved Windows artifact. The former test entry-point name is retained to match the approved binary; normal launch starts the main GUI. Its `--verify-lidar-trees` switch runs the built-in regression check without opening the GUI.

Approved build commit: `82e5791d4978f81b6d4c471a6c8811720c6b9f9f`.

Approved EXE SHA-256: `c3ec0f85206b8f0148a235e415a48e3c63bdcf94cd760c52e92414a196cf349f`.
