# TGC Designer Tools — PGA TOUR 2K25

Build PGA TOUR 2K25 courses from **LiDAR, GeoTIFF DEMs, OpenStreetMap, and Unity RAW/SVG data**. Import real-world terrain and course features, align the layout visually, choose regional vegetation, and export a `.course` file for Designer.

**Current release: v0.5.0-2k25-beta8** · **Windows x64** · Maintained by **malifica**

[Download Beta 8](https://github.com/malifica/TGC-Designer-Tools/releases/tag/v0.5.0-2k25-beta8) · [Release notes](RELEASE_NOTES_v0.5.0-2k25-beta8.md) · [Change history](CHANGELOG.md)

## Beta 8 highlights

- **Unity RAW + Course SVG import.** Terrain size/height, byte-order and orientation controls, SVG feature mapping, preview, and paired DEM/local-OSM output integrated into the existing import workflow.
- **Bunker and tee alignment audit.** Review terrain-based local offset suggestions and confidence indicators before approving corrections.
- **Course-wide micro-alignment.** Select from the map or list; drag, nudge, or enter precise offsets; move selected groups and undo changes. Manual editing includes greens, fairways, rough, water, mulch, paths and other supported features.
- **Linked or independent boundaries.** Move a feature with its matching inner cutout, or adjust them separately. Shared-boundary handling preserves unselected neighbors and validates the resulting geometry.
- **Refreshed interface.** Consistent controls, synchronized map/list feature filters, and a resizable/maximizable alignment workspace.
- **Desert Southwest theme.** A desert tree/cactus palette with regional playing-surface and terrain-material selections.
- **Custom Theme Weighted Planting.** ON restores the earlier custom-theme height/width behavior; OFF retains current LiDAR-derived sizing. Heroic, Epic and Mythic remain separate size choices. The option defaults OFF; it does not add a new tree-count rule or change detection/filtering.
- **Background-terrain registration improvements.** Corrected source-grid sampling keeps background terrain registered to the detailed terrain.
- **Dry-mulch support.** Import mapped mulch separately from water, with corresponding preview and mask handling.

## Faster LiDAR and DEM processing

Beta 7 substantially reworks how coordinate transformations are handled throughout preview and feature preparation. Earlier processing repeatedly constructed the same geographic transformation for individual OSM nodes. Large OSM files and coordinate systems with more expensive datum transformations could therefore spend many minutes preparing a small preview.

The tool now reuses the appropriate transformation for each projection pair, including repeated preview, mask, and import lookups. **Affected preview/mask stages that previously took many minutes can complete in seconds.** The improvement is especially noticeable on OSM-heavy projects and complex coordinate systems. Total processing time still depends on point count, raster size, storage, and hardware; this is not a fixed speed multiplier for every LiDAR operation.

This acceleration does **not** change terrain resolution, coordinate units, datum settings, or the selected terrain brushes. It is not a shortcut that replaces projected meters with map pixels, and it does not require a CUDA-capable GPU.

DEM preview screening keeps golf features, roads, streams, water, and required multipolygon members while excluding unrelated standalone coastline and residential land-use areas from the render-feature set. Residential **roads** remain eligible. The original OSM file is not modified.

The status output distinguishes normalization, OSM drawing, automatic masking, and file writing. Progress percentages are phase-based rather than time-remaining estimates; elapsed time and available activity counters remain visible during longer operations.

## CFS alignment viewer

Use CFS to compare OSM outlines with the saved terrain, then adjust the layout before importing course features.

- **Hillshade, Visual, and Blend** views; Hillshade is the default.
- **Brightness: 25–200%** and **contrast: 25–300%**, both initially 100%.
- **Zoom up to 30×**, mouse-wheel zoom, zoom buttons/selector, Fit, and scrollbars.
- High zoom renders the visible background region instead of enlarging the entire terrain image in memory.
- Drag the OSM overlay or enter east/west and north/south adjustments. Arrow keys move by 0.10 m; Shift+Arrow moves by 1 m.
- **Apply + Rebuild Mask** saves the adjustment and rebuilds the mask using that placement.

Brightness and contrast affect only the viewer background, not elevations, OSM colors, the saved mask, or the exported course. The overlay represents source OSM outlines; native spline optimization, handles, and widths can affect the final rendered edge.

CFS and mask rebuilding start from the **currently selected project folder**. When it contains `heightmap.npy`, that heightmap is used directly; otherwise the folder chooser starts there. The selected Local OSM file remains explicit, including for intentionally unmatched layouts.

### Upgrading an existing project

Keep a backup of the project and any manually edited mask. Reopen CFS, review alignment in the corrected viewer, then use **Apply + Rebuild Mask** and regenerate the course features. Older tracked alignments may require this refresh. Rebuilding replaces `mask.png`, so make manual mask edits afterward.

**The existing processed heightmap can be reused.** These changes do not require downloading or processing the original LiDAR again. Previously exported courses are not automatically updated.

## LiDAR tree controls

Enable **Add Trees From Lidar** to generate trees from the candidates stored in the processed heightmap. The following controls operate independently:

| Control | Default | Effect |
|---|---|---|
| OSM LiDAR Tree Filter: Fairway / Green / Bunker / Rough | **OFF** | When enabled, checks candidates against resolved playing-surface shapes and preserves confirmed rough-island exceptions. |
| Exclude LiDAR Trees from Red-Masked Areas | **ON** | Rejects candidates on red mask pixels. Turn it off to retain those candidates, subject to the other enabled checks. |
| Filter LiDAR Trees: within 50 m of Course Features | **ON** | Limits candidates to the existing 50 m course-feature neighborhood. |

Turning off red-mask **tree** exclusion does not restore terrain removed by the red mask or disable Auto Red Mask. Saved-grid boundary checks still apply.

Unresolved, incomplete, or ambiguously tagged OSM items are reported in the tool's status output and ignored by the surface filter. The filter does not invent an enclosing exclusion area or use an unresolved relation to reject every tree. Other valid shapes continue to apply when surface filtering is enabled. It remains possible for all candidates to fail genuine individual checks; the change removes the global veto caused by malformed relations.

These controls affect **newly generated LiDAR trees**, not trees already in a finished course. They do not change LiDAR tree detection, model-size calculations, or the separate OSM-mapped-tree workflow.

## Terrain and data options

### Local LiDAR and GeoTIFF DEM

Use local LAS/LAZ files or one or more georeferenced GeoTIFF DEMs. The tool supports automatic coordinate-system handling, separate horizontal/vertical units where supplied, DEM mosaics, NoData-aware processing, and source-aware map-scale selection.

Dense / Original terrain generation retains selectable brush types **72, 15, 9, and 10** and brush footprints. Optional coarse background fill and the separate outside background-landscape feature remain available. The experimental detailed-purple-terrain option is not included.

### USGS AWS EPT from Local OSM

Select a Local OSM file and use **USGS AWS EPT From Local OSM** to discover available acquisitions and download a course-sized subset. The acquisition chooser exposes available collection information. Public EPT downloads do not require an AWS account or Requester Pays credentials.

The existing local-metric reprojection, Trees Only workflow, and Terrain Gap Fill using older/fallback acquisitions remain available. AWS discovery and gap-fill operations depend on real-world geography and are not used for detached Custom/Unmatched OSM placement.

### Any Local OSM on any terrain

Custom/Unmatched OSM treats the course layout as a local metric design and places it on the selected terrain without changing its size or orientation. Use CFS for the final translation. The same placement is used for the preview, mask, and imported features.

### Surfaces and water

OSM water polygons and streams use the native **mulch** surface. Automobile roads use **asphalt** and remain separate from **cart paths**. Widths and supported spline settings remain configurable through `splines.json`.

Multipolygon previews and masks retain relation-owned areas and inner islands regardless of the Auto Red Mask switch. Source completeness and correct tagging still matter; notices identify unusable features rather than silently inventing geometry.

### Regional themes and tree size

Regional profiles provide weighted tree palettes and coordinated playing-surface and terrain materials. Built-in Designer palettes remain available. LiDAR-derived dimensions continue to control tree scaling independently of the chosen regional palette, with **Standard (Lidar), Heroic, Epic, and Mythic** modes.

**Slope-Locked Hulkify** retains the established 10% enlargement workflow, scaling horizontal geometry and relief together to preserve slope severity.

## Recommended workflow

1. Select the project folder and import the source `.course`.
2. Select the Local OSM file before processing LiDAR or a GeoTIFF DEM.
3. Choose the map scale, process the terrain, and accept the desired area.
4. Open CFS, review the layout against the terrain, then apply the alignment and rebuild the mask.
5. Inspect `mask.png` and make any manual edits after the automatic rebuild.
6. Choose terrain brushes, regional/theme options, and tree-filter settings.
7. Import terrain and features, export the course, and inspect it in Designer.

## Windows downloads and source build

The Windows release contains `tgc_gui_2k25_beta8.exe`. Its title is **TGC Designer Tools 2K25 - Beta 8**. Download the Windows ZIP for the executable, editable profiles, spline configuration, and documentation. SHA-256 files accompany both the standalone EXE and ZIP.

For an existing source checkout with its dependencies installed, run:

```bat
BUILD_TGC_2K25_BETA8.bat
```

The executable is written to `dist\tgc_gui_2k25_beta8.exe`. Beta 7 remains available separately. Environment details are in [BUILD_WINDOWS.md](BUILD_WINDOWS.md).

## Credits and license

This is a derivative fork of the original **TGC Designer Tools** project and **[HiCamino/TGC-Designer-Tools](https://github.com/HiCamino/TGC-Designer-Tools)**. Fork-specific PGA TOUR 2K25 work is maintained by **malifica**.

The project relies on OpenStreetMap, GDAL/PROJ, Rasterio, laspy, NumPy, OpenCV, SciPy, and the Python ecosystem. **Apache License 2.0**; see [LICENSE](LICENSE).

This software is unofficial and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, the OpenStreetMap Foundation, USGS, or other referenced organizations.
