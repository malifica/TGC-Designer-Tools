# TGC Designer Tools 2K25 — v0.5.0-2k25-beta6 Hotfix

## Multipolygon preview and mandatory mulch-water hotfix - 2026-10-21

- Relation-owned golf and water multipolygons render in the selection preview and mask whether Auto Red Mask is ON or OFF.
- Complete relation tags, outer boundaries and inner islands are retained in the ordinary LiDAR/DEM overlay and aligned/custom-OSM mask paths.
- Imported 2K25 water polygons and streams use native mulch category 10. Mulch05 is explicitly retained at surfaces2[2] after regional-theme application and immediately before final archive encoding.
- Asphalt roads use native category 8; cart paths remain category 7. Water/stream geometry and width settings remain configurable, but a primary-surface override cannot change imported water away from mulch.
- Red-mask exclusion/buffering/cleanup, CFS placement, terrain reconstruction, LiDAR tree sizing and all regional profiles are unchanged.

Existing projects: use Rebuild Mask from Current OSM Alignment to regenerate mask.png from the saved heightmap and alignment. Refresh the selection preview separately when needed. Reimport the course features for the water correction; old exported files and PNGs are not rewritten automatically.

This release applies the supplied hotfix to current Beta 6, including a correction to its installer anchors so all six preview call-site edits are actually applied. The native-overpy test fixture is corrected without changing application behavior. The LiDAR tree-sizing hotfix and existing entry point are retained. Automated checks validate geometry and serialized material assignments; native Designer appearance still requires a visual check.

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
- Regional and built-in palettes use the same LiDAR-derived sizing; profile size distributions are ignored.

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
