# TGC Designer Tools 2K25 — Beta 6 Hotfix

## Tree topology and nonfatal OSM notices hotfix

- Maintained green, fairway and bunker areas reject new LiDAR trees; confirmed fully contained rough islands remain eligible, subject to other exclusions.
- OSM rough uses outer-minus-inner topology. Broad surrounding rough no longer grants a fairway-tree exception.
- Ambiguous mixed golf tags and unusable tree-topology items print terminal NOTICE messages instead of aborting tree filtering. Trees are denied in the affected outer footprints, including inner areas.
- When complete affected bounds cannot be recovered safely, new LiDAR trees are disabled for that import while processing continues. Healthy areas retain their normal filtering when the fault can be localized.
- EXE: `tgc_gui_2k25_beta6.exe`. Main window: `TGC Designer Tools 2K25 - Beta 6`. No TEST or hotfix suffix is displayed.
- Prior multipolygon-preview, mandatory mulch-water, tree-sizing, CFS/mask and regional-profile fixes are retained. Tree detection/sizing, mask coordinates, Hulkify and spline geometry are unchanged. Course Finisher is not updated.

Reuse the processed heightmap and regenerate the TGC course before Course Finisher. This filter affects newly generated LiDAR trees; it does not remove existing trees from saved finished courses or edit the OSM/server. This is a tree-filter correction, not a change to the spline importer's green-relation coverage. Invalid JSON or unrelated processing errors are not suppressed.

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
