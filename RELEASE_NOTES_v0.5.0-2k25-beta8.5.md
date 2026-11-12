# TGC Designer Tools 2K25 — Beta 8.5

- **Heightmap Scale defaults to Auto.** DEM inspection reads the source grid metadata; LiDAR inspection measures classified ground coverage before converting points to pixels. The recommendation is shown with its reason and confidence.
- **Confirm the scale before processing.** Local LiDAR, DEM, AWS EPT and ex-US downloads pause for a source-scale review. Keep Auto, enter a manual scale, or cancel. Source loading/downloads may finish before the review; heightmap and mask generation wait for acceptance.
- Trees-only imports use the same review for their LiDAR processing scale while retaining the existing DEM grid. Terrain gap filling confirms the existing grid, since changing its spacing would require rebuilding the project. Unity RAW conversion also reviews its dimension-derived spacing before conversion and the resulting DEM before heightmap processing.
- DEM tiles with mixed spacing use an explicit common grid based on the coarsest source axis. Selected scales, source measurements and the decision mode are saved with the heightmap for later checks. Manual scales are validated before processing, including the exporter's existing 6 m maximum.
- **Terrain Stamp Spacing (m)** separates final course terrain sampling from LiDAR/DEM processing. For example, process a heightmap at 1 m, then use 2 m stamp spacing with a 2 m brush. Trees, buildings, masks, CFS and OSM placement continue to use the original 1 m source grid.
- **Source** is the default stamp-spacing setting and retains the existing dense output. Numeric spacing may be equal to or larger than the saved source spacing, up to the configured 6 m maximum. The brush footprint is raised to the smallest supported size that covers the requested spacing when needed.
- Integer source-grid ratios (such as 1 m to 2 m) use exact native elevations. Other ratios use bilinear interpolation at the requested stamp centers, without interpolating across masked or invalid terrain. Source-aligned outer endpoints and native samples bordering masked areas are retained, so narrow valid terrain is not dropped.
- Output sampling retains the original horizontal coordinate frame and full-resolution elevation-normalization reference. Changing only spacing therefore does not move OSM or LiDAR objects or change the global terrain elevation datum. Coarser stamps still approximate small terrain details; this feature does not create new source detail or correct inaccurate OSM data.
- The 1 m to 2 m setting uses roughly one quarter as many main interior stamps; boundary retention and separate background/cartpath passes add their own stamps. Fine-resolution processing and tree-detection cost stay the same. Existing heightmaps can be reused at different output spacings without reprocessing.
- **Hillshade 1** is the new default CFS terrain view. Its neutral gray lighting and local relief make bunker depressions and small landforms easier to see.
- **Hillshade 2** retains the original hillshade style as a selectable option.
- The **Local Tee/Bunker Alignment** window uses Hillshade 1, including when the main CFS viewer is displaying another view.
- **Match Course Name** selects golf holes and playing features inside matching OSM golf-course boundaries. Matching is case-insensitive and accepts partial names; leaving it blank includes all courses. Water, trees, buildings, roads, cart paths, and walking paths remain available outside or across the selected boundary, subject to the existing import options.
- Course selection is shared by LiDAR/DEM previews, CFS and local alignment, automatic masks, and final import. Changing the selection makes an earlier alignment mask stale so it can be rebuilt for the selected course.
- Both hillshade styles are display controls. Source elevations, OSM geometry, alignment offsets, terrain generation, and masks are unchanged by switching views.
- Retains Beta 8.4's Graduated Background and the earlier parking, natural-wood, and open-island features.

Windows executable: `tgc_gui_2k25_beta8_5.exe`.

Build with `BUILD_TGC_2K25_BETA8_5.bat` in the existing TGC Python environment. The build stages and checks the new executable before installing it in `dist`; earlier-version executables keep their existing names.
