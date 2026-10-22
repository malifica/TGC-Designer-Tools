# Beta 6 - Tree Topology and Nonfatal OSM Notices

## Tree topology and nonfatal OSM notices hotfix

- Maintained green, fairway and bunker areas reject new LiDAR trees; confirmed fully contained rough islands remain eligible, subject to other exclusions.
- OSM rough uses outer-minus-inner topology. Broad surrounding rough no longer grants a fairway-tree exception.
- Ambiguous mixed golf tags and unusable tree-topology items print terminal NOTICE messages instead of aborting tree filtering. Trees are denied in the affected outer footprints, including inner areas.
- When complete affected bounds cannot be recovered safely, new LiDAR trees are disabled for that import while processing continues. Healthy areas retain their normal filtering when the fault can be localized.
- EXE: `tgc_gui_2k25_beta6.exe`. Main window: `TGC Designer Tools 2K25 - Beta 6`. No TEST or hotfix suffix is displayed.
- Prior multipolygon-preview, mandatory mulch-water, tree-sizing, CFS/mask and regional-profile fixes are retained. Tree detection/sizing, mask coordinates, Hulkify and spline geometry are unchanged. Course Finisher is not updated.

Reuse the processed heightmap and regenerate the TGC course before Course Finisher. This filter affects newly generated LiDAR trees; it does not remove existing trees from saved finished courses or edit the OSM/server. This is a tree-filter correction, not a change to the spline importer's green-relation coverage. Invalid JSON or unrelated processing errors are not suppressed.

