# TGC Designer Tools 2K25 — Beta 5 Hotfix

This hotfix keeps the existing `v0.5.0-2k25-beta5` application identity and replaces the Windows release artifacts and source tag with corrected source.

## Fixed: AWS EPT horizontal ground scale

Public USGS EPT resources delivered in EPSG:3857/Web Mercator are now reprojected to a local WGS 84 UTM CRS before the retained points are written to LAZ and passed into the normal LiDAR/CFS pipeline. This prevents the latitude-dependent Web Mercator enlargement that made generated courses substantially larger than their source OSM geometry.

Suitable local projected CRSs, such as UTM or State Plane, remain unchanged. Z elevations and point classifications are preserved. The transformer is cached per CRS pair so the correction adds only a vectorized post-crop X/Y transform.

## AWS EPT acquisition chooser

- The action buttons remain visible without manually resizing the window.
- The selected acquisition is persistently highlighted in standard blue with white text.
- The details area is scrollable while the dataset table remains the only expanding section.

## Fixed: unsafe Local OSM master extent

When no explicit `leisure=golf_course` boundary is present, the master extent now uses this order:

1. complete explicit golf-course boundary;
2. declared OSM export `<bounds>`;
3. golf-feature nodes;
4. all OSM nodes only as the final legacy fallback.

This prevents clipped supporting relation nodes from expanding a course-sized OSM export into a many-kilometre terrain grid.

## Fixed: mask and heightmap dimension lock

- `mask.png` is rebuilt after the final OSM master-grid conversion.
- The written mask dimensions are verified against the final heightmap.
- The user is not told to edit the mask until the final matching mask exists.
- Course generation reports a clear mask/heightmap dimension mismatch instead of reaching a NumPy broadcasting error.

## Existing Beta 5 behavior retained

Regional themes, tree profiles, Heroic/Epic/Legacy tree scaling, DEM workflows, Trees Only, Terrain Gap Fill, Auto Red Mask behavior, OSM multipolygon import, and the native LiDAR rasterizer remain otherwise unchanged.
