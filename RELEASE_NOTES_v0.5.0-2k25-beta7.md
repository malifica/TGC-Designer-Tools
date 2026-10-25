# TGC Designer Tools 2K25 — Beta 7

## Highlights

- **Much faster LiDAR and DEM preview/mask processing.** Reworked coordinate-transform handling prepares and reuses the appropriate transformation instead of constructing it for every OSM node. Affected OSM-heavy stages that previously took many minutes can now complete in seconds; gains depend on the project and hardware.
- **Clearer processing progress.** Named phases, phase-based percentages, elapsed time, and file-write activity make long operations easier to follow.
- **CFS alignment improvements.** The viewer and aligned-mask rebuild use the same transformation convention as course import, with corrected raster-to-screen placement.
- **Better CFS display controls.** Hillshade is the default; brightness and contrast sliders, reset controls, and zoom up to 30× improve detailed alignment. High zoom renders only the visible background area.
- **Current-project folder defaults.** CFS and mask rebuilding start from the selected working folder instead of an earlier project's remembered heightmap location.
- **Independent LiDAR tree controls.** OSM/surface filtering defaults OFF, red-mask tree exclusion defaults ON, and the existing 50 m course-feature filter remains ON and independent.
- **Unresolved OSM relations no longer disable every tree.** Problematic items are identified in the status output and skipped. Enabled surface filtering checks valid shapes and retains confirmed rough-island exceptions without inventing exclusion boxes.
- **More focused DEM previews.** Golf features, roads, streams, water, and necessary relation members are retained; unrelated coastline and residential land-use areas are excluded from the render-feature set. Residential roads remain supported.

The speed improvements preserve the selected terrain resolution and coordinate calculations. Raw-point loading, tree detection, and disk throughput still affect total job time; this is not a fixed whole-process speed multiplier or a CUDA update.

## Existing features retained

Regional tree/material profiles, LiDAR-based tree sizing, water locked to mulch, separate asphalt roads and cart paths, multipolygon islands, Custom/Unmatched OSM placement, source-grid masks, AWS EPT acquisition, Trees Only, Terrain Gap Fill, Dense / Original terrain brushes, and Slope-Locked Hulkify remain included. Course Finisher and Course Architect are separate and unchanged.

## Upgrading and using existing projects

Run **`tgc_gui_2k25_beta7.exe`**. The application title is **TGC Designer Tools 2K25 - Beta 7**.

Reuse the processed heightmap. Back up manually edited masks, review alignment in the corrected CFS viewer, use **Apply + Rebuild Mask**, then regenerate the course features. Rebuilding replaces `mask.png`; make manual mask edits afterward. Previously exported courses do not update automatically.

To retain trees in red-masked areas, uncheck **Exclude LiDAR Trees from Red-Masked Areas**. This affects trees only, not terrain masking. The 50 m filter and saved-grid bounds still apply. To enable maintained-surface exclusions and rough-island handling, enable the independent OSM/surface filter.

## Downloads

- `tgc_gui_2k25_beta7.exe`
- `TGC-Designer-Tools-2K25-v0.5.0-2k25-beta7-Windows-x64.zip`
- A SHA-256 checksum file for each download.

The ZIP includes the executable, editable regional profiles, spline configuration, and user documentation. The prior Beta 6 release remains available.
