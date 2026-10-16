# TGC Designer Tools 2K25 — v0.5.0-2k25-beta6 Hotfix

## Beta 6 spline-surface hotfix

- OSM water polygons and streams now default to the mulch custom surface.
- Automobile roads now default to asphalt and remain independent from golf cart paths.
- Cart paths retain the selected Designer theme's Cart Path material while honoring configured widths and valid surface overrides.
- Water and streams have independent `splines.json` sections, with the legacy `placeholder` section retained as a closed-water geometry fallback.
- Invalid or misnamed `splines.json` files now produce a clear error instead of silently reverting to defaults.
- The processing log reports effective cart-path, road, water, and stream surfaces and widths.
- Aligned-mask road-width tracking now uses the same validated configuration loader as final OSM import.

The hotfix retains the existing Beta 6 tag and established Windows asset filenames.

Beta 6 builds on the Beta 5 hotfix with a safer CFS/mask workflow, detached Local OSM placement, explicit road/path handling, final-grid LiDAR tree masking, Slope-Locked Hulkify, and an expanded regional-tree system.

## Any Local OSM on any LiDAR/DEM terrain

Beta 6 can use a Local OSM course layout even when its real-world coordinates do not match the selected terrain. In this mode the OSM file is treated as a local metric design: its dimensions and orientation are preserved 1:1, the golf layout is centered on the terrain, and the CFS Alignment Viewer supplies the final translation.

- Centering prefers `golf=hole` geometry, then other golf geometry, before falling back to full node extent.
- The same transform is reused by the initial preview, CFS overlay, Auto Red Mask, and final OSM import.
- AWS EPT discovery and Terrain Gap Fill are disabled while unmatched-OSM mode is active because those operations depend on the original OSM geography.

## CFS-first Auto Red Mask workflow

The production mask is no longer treated as final before CFS alignment.

- Local OSM selection appears before LiDAR/DEM processing.
- CFS alignment is finalized before the production Auto Red Mask is accepted.
- Applying an OSM shift rebuilds `mask.png` on the final master grid using that exact shift.
- Stale masks are blocked rather than silently reused.
- CFS terrain/OSM preparation and production-mask rebuilding run off the Tk main thread with progress reporting.

This is especially important with tight preservation buffers, where even a small post-mask alignment shift could otherwise move course geometry into masked terrain.

## Roads, cart paths, and walking paths

Beta 6 separates these feature classes instead of treating generic OSM paths as golf cart paths.

- Cart paths require `golf=cartpath`.
- Walking paths require explicit `golf=path`.
- Generic `highway=footway`, `highway=path`, and `highway=pedestrian` features are not promoted into golf paths unless tagged for golf.
- Supported automobile `highway=*` features use an independent optional road-spline workflow with a 6.0 m default width.
- Automobile roads are excluded from Auto Flatten Cartpaths.

## LiDAR tree master-grid fix

LiDAR tree filtering now uses the final terrain/master-grid mask so tree placement stays registered after CFS or custom-layout transforms. Existing playing-surface exclusions and explicit rough-island behavior are retained.

## Slope-Locked Hulkify

Slope-Locked Hulkify enlarges complete course geometry by 10% per click while applying the same transform to terrain relief, active water levels, and terrain-seated object elevations. Rise and run scale together, preserving slope severity. Repeated clicks compound from the current course state.

## Regional tree profiles and scale labels

- **Pacific Northwest** is added as a calibrated regional tree profile.
- Tree-size choices are now `Standard (Lidar)`, `Heroic`, `Epic`, and `Mythic`.
- **Standard (Lidar)** retains the established LiDAR sizing behavior.
- **Heroic** retains the existing Heroic calibration.
- **Epic** is `1.20 × Heroic`.
- **Mythic** is `1.80 × Heroic`.
- The same Epic/Mythic multipliers apply to regional profile-calibrated scales.

## Retained Beta 5 hotfix corrections

- AWS EPT Web/Pseudo-Mercator data is reprojected into true-ground local metric coordinates before LAZ output.
- AWS EPT chooser actions remain visible and the selected acquisition remains highlighted.
- Local OSM master extents use safe course/export bounds rather than unrelated distant relation nodes.
- Final `mask.png` dimensions are verified against `heightmap.npy`.
- A mask/heightmap mismatch reports a clear error rather than reaching a NumPy broadcasting failure.

## Windows release

Executable:

```text
tgc_gui_2k25_beta6.exe
```

Windows package:

```text
TGC-Designer-Tools-2K25-v0.5.0-2k25-beta6-Windows-x64.zip
```

The prerelease includes SHA-256 files for both the executable and Windows ZIP.

Beta 6 remains the main TGCTool course-creation application. Adaptive Terrain, Course Finisher, and Crazy Bunkers remain separate downstream tools.
