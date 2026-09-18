# TGC Designer Tools — PGA TOUR 2K25 Fork

A streamlined 2K25-focused fork of **HiCamino/TGC-Designer-Tools** for building real-world courses from **LiDAR, GeoTIFF DEM, and OpenStreetMap data**.

Current release: **v0.5.0-2k25-beta2**  
Maintainer: **malifica**  
Upstream: https://github.com/HiCamino/TGC-Designer-Tools

This project remains under the upstream **Apache License 2.0**.

---

## What this fork adds

- **PGA TOUR 2K25** course-structure support.
- **Local OSM / JOSM files** in the normal LiDAR and DEM workflow.
- **GeoTIFF DEM support**, including multi-tile mosaics.
- Automatic **CRS / EPSG detection** for DEM and modern LAS/LAZ files.
- Compound LiDAR CRS handling with separate **horizontal and vertical units**.
- Independent conversion of XY and elevation values to meters.
- **Dense / Original** and **Adaptive - Aggressive** terrain-generation modes.
- User-selectable terrain brush and footprint size for Dense mode.
- **Auto Background Landscape (Purple)** generated from source elevation data.
- User-controlled **Purple Background Detail Spacing**.
- Improved 2K25 LiDAR tree placement.
- Improved blue-water mask handling for OSM water features.
- Automatic conversion of OSM bunker multipolygons with rough inner islands into 2K25-compatible bunker holes.
- Larger, screen-aware GUI.
- Windows PyInstaller packaging with Rasterio/GDAL/PROJ support.

---

## Recommended workflow

When using a local OSM file, select it **before processing LiDAR or DEM data**.

1. Open/import the target .course.
2. Select **Local OSM File** if using a JOSM/OSM export.
3. Choose **Map Scale**.
4. Process **LiDAR or GeoTIFF DEM**.
5. Crop/select the course area.
6. Inspect or edit mask.png if needed.
7. Choose terrain-generation settings.
8. Import terrain and OSM features.
9. Export the finished .course.

The selected Local OSM file is used both for preview/mask creation and the later feature import, keeping the two stages aligned.

---

## Terrain generation

Beta 2 intentionally keeps the public terrain-generation choices simple:

~~~text
Dense / Original
Adaptive - Aggressive
~~~

### Dense / Original

Best when maximum source fidelity is the priority.

| Brush | Description |
|---:|---|
| 72 | Raw / minimal smoothing |
| 15 | Light smoothing |
| 9 | Medium smoothing |
| 10 | Heavy / soft smoothing |

Available absolute brush footprints:

~~~text
1 m, 2 m, 3 m, 4 m, 6 m
~~~

Brush sizes smaller than the source/sample spacing are not used.

### Adaptive - Aggressive

Reduces terrain operations by using larger terrain stamps where possible.

This mode is intended for users who want lower **Objects meter** usage and accept a softer terrain representation away from areas requiring maximum local detail.

---

## Auto Background Landscape

**Auto Background Landscape (Purple)** generates coarse surrounding terrainHeight from the same LiDAR/DEM source instead of leaving the outer course flat.

Default:

~~~text
Purple Background Detail Spacing: 48 m
Brush: 10
Brush footprint: 2.0 × spacing
Smoothing: 0.35 × spacing
~~~

Examples:

~~~text
48 m spacing -> 96 m Brush 10
32 m spacing -> 64 m Brush 10
24 m spacing -> 48 m Brush 10
~~~

Lower spacing values use more of the course Objects meter but preserve more surrounding-landscape detail.

---

## LiDAR CRS handling

Beta 2 uses modern LAS/LAZ CRS parsing when available and supports compound coordinate systems.

Example:

~~~text
Horizontal CRS: NAD83(2011) / Texas South Central (ftUS)
Horizontal EPSG: 6588
Horizontal unit: US survey foot

Vertical CRS: NAVD88 height (ftUS)
Vertical EPSG: 6360
Vertical unit: US survey foot
~~~

XY and Z conversions are handled independently.

The GUI retains:

~~~text
Force LiDAR Horizontal EPSG (blank = auto)
~~~

Leave it blank for automatic detection.

---

## GeoTIFF DEM support

The DEM workflow supports:

- one or multiple georeferenced .tif / .tiff files;
- automatic mosaicing;
- CRS/EPSG detection;
- horizontal reprojection when required;
- native DEM spacing detection;
- NoData-safe processing;
- independent vertical-unit conversion;
- Map Scale controlled terrain reduction.

Dense DEM data is reduced with a deterministic **40th-percentile lower-ground-biased reducer** rather than simple image interpolation.

The tool does not upsample terrain beyond the source DEM's native resolution.

---

## Water masks

Recognized water includes:

~~~text
golf=water_hazard
golf=lateral_water_hazard
natural=water
waterway=*
~~~

Water is finalized as pure blue in the mask:

~~~text
RGB 0,0,255
~~~

Open waterway=* features are rendered as polylines instead of being incorrectly closed into polygons.

Beta 2 retains:

- **Fill Holes Under Blue Mask**
- **Remove All Terrain Under Blue Mask**

The experimental automatic **Carve Blue Mask Banks** feature is **not included** in Beta 2.

---

## OSM bunker inner islands

Modern OSM bunker geometry can use a multipolygon such as:

~~~text
relation: golf=bunker
  outer -> bunker boundary
  inner -> golf=rough island
~~~

Beta 2 converts this into a 2K25-compatible bunker polygon with a narrow neck so the inner rough area becomes a physical hole in the bunker fill.

The inner rough member is consumed during conversion and is not written again as a redundant rough spline.

---

## Windows release

Current executable:

~~~text
tgc_gui_2k25_beta2.exe
~~~

Current release package:

~~~text
TGC-Designer-Tools-2K25-v0.5.0-2k25-beta2-Windows-x64.zip
~~~

See **[BUILD_WINDOWS.md](BUILD_WINDOWS.md)** for source-build instructions.

Release notes: **[RELEASE_NOTES_v0.5.0-2k25-beta2.md](RELEASE_NOTES_v0.5.0-2k25-beta2.md)**

Full change history: **[CHANGELOG.md](CHANGELOG.md)**

---

## Credits

This is a derivative fork of the original **TGC Designer Tools** project and **HiCamino/TGC-Designer-Tools**.

Fork-specific 2K25 Local OSM / LiDAR / DEM work is maintained by **malifica**.

The project also relies on the OpenStreetMap, GDAL/PROJ, Rasterio, laspy, NumPy, OpenCV, and Python ecosystems.

---

## License

Apache License 2.0. See **[LICENSE](LICENSE)**.

This software is unofficial and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, OpenStreetMap Foundation, USGS, or other referenced organizations.
