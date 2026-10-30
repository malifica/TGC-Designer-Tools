# TGC Designer Tools 2K25 — Beta 8

Beta 8 brings Unity terrain/layout import, detailed course-feature alignment, a refreshed interface, Desert Southwest, and selectable custom-theme tree sizing into the main TGC Tool.

## Highlights

- **Unity RAW + Course SVG import.** Terrain size/height, byte-order and orientation controls, SVG feature mapping, preview, and paired DEM/local-OSM output integrated into the existing import workflow.
- **Bunker and tee alignment audit.** Review terrain-based local offset suggestions and confidence indicators before approving corrections.
- **Course-wide micro-alignment.** Select from the map or list; drag, nudge, or enter precise offsets; move selected groups and undo changes. Manual editing includes greens, fairways, rough, water, mulch, paths and other supported features.
- **Linked or independent boundaries.** Move a feature with its matching inner cutout, or adjust them separately. Shared-boundary handling preserves unselected neighbors and validates the resulting geometry.
- **Refreshed interface.** Consistent controls, synchronized map/list feature filters, and a resizable/maximizable alignment workspace.
- **Desert Southwest theme.** A desert tree/cactus palette with regional playing-surface and terrain-material selections.
- **Custom Theme Weighted Planting.** ON restores the earlier custom-theme height/width behavior; OFF retains current LiDAR-derived sizing. Heroic, Epic and Mythic remain separate size choices. The option defaults OFF; it does not add a new tree-count rule or change detection/filtering.
- **Background-terrain registration improvements.** Corrected source-grid sampling keeps background terrain registered to the detailed terrain.
- **Dry-mulch support.** Import mapped mulch separately from water, with corresponding preview and mask handling.

## Scope and use

Run `tgc_gui_2k25_beta8.exe`. This is the main course-creation tool. Adaptive Terrain, Course Finisher, Crazy Bunkers, and More is More! remain separate applications.

Automatic terrain-based alignment suggestions apply to tees and bunkers. Other supported feature types use manual translation. This is not vertex editing, terrain sculpting, or automatic realignment of every course feature. Review proposed changes and keep project backups.

Unity RAW and SVG supply terrain and surface-layout data. The importer does not invent numbered hole routes when the SVG lacks them. Add routing as appropriate before generating a playable course. Synthetic-coordinate OSM is for local use and must not be uploaded to OpenStreetMap.

For existing projects, reuse processed terrain where appropriate, review alignment, rebuild the aligned mask when required, then regenerate and export. Previously exported courses do not update automatically.

## Release files

- `tgc_gui_2k25_beta8.exe`
- `TGC-Designer-Tools-2K25-v0.5.0-2k25-beta8-Windows-x64.zip`
- Matching SHA-256 checksum files.

The Windows ZIP contains the executable, editable regional profiles, default spline configuration when available, license notices, and these user-facing notes. Project courses, private diagnostics, development-history documents, and test reports are excluded. Beta 7 remains available as a separate release.
