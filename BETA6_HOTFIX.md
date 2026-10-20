# TGC Designer Tools 2K25 — Beta 6 Hotfix

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

This hotfix applies the verified **Spline Surface Fix V1** to the existing Beta 6 release.

## Fixed

- OSM water polygons now default to the mulch custom surface instead of the cart-path surface.
- OSM streams now default to mulch and have an independent `stream` section in `splines.json`.
- Automobile roads now default to the asphalt custom surface and remain independently configurable from golf cart paths.
- Golf cart paths retain the selected Designer theme's Cart Path material while honoring `cartpath.pathWidth` and valid `primarySurface` settings.
- `water` and `stream` now have independent `splines.json` sections; the legacy `placeholder` section remains a backward-compatible fallback for closed-water geometry.
- Invalid `splines.json` syntax now stops processing with the exact filename, line, and column instead of silently falling back to defaults.
- Misnamed files such as `splines(2).json` are reported when the required `splines.json` is missing.
- The processing log now reports the effective cart-path, road, water, and stream surfaces and widths.
- CFS/aligned-mask road-width tracking now uses the same validated spline configuration loader as final OSM import.

## Default behavior

- Cart path: selected theme's Cart Path material; 2.0 m unless overridden.
- Automobile road: asphalt; 6.0 m unless overridden.
- Closed water polygon: mulch; 0.01 m boundary width unless overridden.
- Stream: mulch; 2.0 m unless overridden.

The release remains `v0.5.0-2k25-beta6`; the EXE and Windows ZIP retain their established Beta 6 filenames.
