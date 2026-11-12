# TGC Designer Tools 2K25 — Beta 8.5

## Highlights

- **New default Hillshade 1.** A terrain view with clearer small depressions and raised features is now the default in CFS and the bunker/tee alignment workspace. The previous shading remains available as **Hillshade 2**.
- **Match Course Name.** Filter an OSM file containing multiple courses by a partial, case-insensitive course name. Golf holes and playing features must lie within the matching OSM golf-course boundary. Surrounding water, trees, buildings, roads and paths remain eligible under their normal import controls, including features crossing or outside that boundary. Leave the field blank to include all courses.
- **Separate heightmap resolution and terrain stamp spacing.** Keep a fine heightmap for LiDAR tree detection and OSM alignment, then use wider terrain stamp spacing for course creation—for example, a **1 m heightmap with 2 m stamp spacing**. Native and whole-number-ratio samples retain their original elevations; fractional sample positions use bilinear interpolation with valid source data. Source coordinates, boundary samples and NoData edges are preserved. Brush coverage is checked against the selected spacing.
- **AUTO map scale with confirmation.** AUTO is the default. After source selection and inspection, a confirmation window shows the recommended and selected heightmap scale before processing starts. Accept the recommendation or enter a manual value. DEM recommendations use source pixel spacing; LiDAR recommendations use classified ground coverage. The confirmation is integrated with local LiDAR/DEM and AWS EPT workflows.
- **25 regional themes.** Choose coordinated regional tree palettes, playing surfaces and terrain materials using generic geographic theme names.
- **Nature-only Filter Ready.** The toggle beside theme selection prepares the Designer's Planted filter by adding one sample of each missing nature asset in a remote corner. Existing planted assets are reused. Samples include trees, shrubs, grass, plants and rocks; buildings, furniture, equipment and other props are excluded.
- **Portable theme resources.** Regional profiles and their nature catalogs are bundled with the executable so the full theme selection remains available when the EXE is moved to another folder.

Beta 8.5 retains Graduated Background and the earlier rough/water island handling, local OSM alignment, terrain imports and LiDAR tree controls.
