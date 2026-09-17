# TGC Designer Tools 2K25 — v0.5.0-2k25-beta1

First public beta of the **malifica** fork of HiCamino's TGC Designer Tools, focused on PGA TOUR 2K25 course creation.

## Highlights

This build adds a much more complete offline/local terrain workflow:

- Local `.osm` / JOSM files in the normal LiDAR/terrain workflow.
- GeoTIFF DEM processing alongside LiDAR.
- Automatic DEM EPSG/CRS detection.
- Compound GeoTIFF CRS metadata handling.
- Automatic DEM vertical-unit normalization.
- Map Scale aware DEM reduction.
- Expanded water-mask recognition and pure-blue water output.
- 2K25 LiDAR tree fixes.
- Explicit terrain brush IDs and absolute brush sizes.
- Larger screen-aware GUI.
- PyInstaller support for bundled Rasterio/GDAL/PROJ.

## Important Local OSM sequence

If using Local OSM, select it **before** processing LiDAR or DEM:

```text
1. Import/select course
2. Select Local OSM
3. Set Map Scale
4. Process LiDAR or DEM
5. Crop
6. Check mask.png
7. Select Brush / Brush Size
8. Import Terrain and Features
9. Export course
```

The same Local OSM is now used during preview/mask generation and later feature import.

## Terrain brushes

Available brush IDs:

```text
72 = raw / minimal smoothing
15 = light smoothing
 9 = medium smoothing
10 = heavy / soft smoothing
```

Available absolute sizes:

```text
1 m, 2 m, 3 m, 4 m, 6 m
```

Example:

```text
Map Scale 2 m + Brush 10 + Brush Size 4 m
```

means terrain centers every 2 m with 4 m Brush 10 footprints.

## DEM improvements

DEM support accepts georeferenced GeoTIFF files and can mosaic multiple compatible tiles.

The tool automatically reads CRS/EPSG information and converts elevation values to meters when the GeoTIFF declares US survey feet or international feet.

This is particularly important for USGS/NOAA DEM data, where horizontal and vertical units may differ.

Dense DEMs are reduced to the selected Map Scale using a deterministic lower-ground-biased terrain reducer instead of simple bilinear image scaling.

## Water-mask fixes

Recognized water now includes:

```text
golf=water_hazard
golf=lateral_water_hazard
natural=water
waterway=*
```

Water is finalized as:

```text
RGB 0,0,255
```

Open waterways are drawn as lines rather than closed/filled polygons, preventing giant triangular mask artifacts.

## Status

LiDAR + Local OSM is the more mature workflow.

DEM support is new and remains **beta** while additional GeoTIFF sources, coordinate systems, and terrain profiles are tested.

## Upstream

Based on:

```text
HiCamino/TGC-Designer-Tools
upstream baseline: 4adb37fac73ab013da4ac6b86b02bb9579e19170
```

First fork feature commit:

```text
2a337709fe80edc164375862f9c36b041f3f07ab
```

## License

Apache License 2.0. Existing upstream credits and licensing are preserved.

This is an unofficial community modification and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, OpenStreetMap Foundation, USGS, or other referenced organizations.
