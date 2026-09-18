# Changelog

All notable fork-specific changes to `malifica/TGC-Designer-Tools` are documented here.

The fork is based on work from `HiCamino/TGC-Designer-Tools`.


## [0.5.0-2k25-beta2] - Terrain, CRS, OSM, and workflow beta

### Added

- Integrated `Adaptive - Aggressive` terrain generation mode.
- Automatic purple `terrainHeight` background landscape generated from source LiDAR/DEM relief.
- User-editable Purple Background Detail Spacing control.
- Modern LAS/LAZ CRS parsing through `laspy.header.parse_crs()`.
- Compound LiDAR CRS splitting into horizontal and vertical components.
- Independent LiDAR XY and Z unit conversion.
- OSM bunker multipolygon conversion for `golf=bunker` outer + `golf=rough` inner islands.
- Narrow lollipop/neck generation so inner rough islands become physical holes in the 2K25 bunker fill.

### Changed

- Public Terrain Generation choices simplified to:
  - Dense / Original
  - Adaptive - Aggressive
- Purple background default detail spacing set to 48 m.
- Purple background Brush-10 footprint uses `2.0 × spacing`.
- Purple background smoothing uses `0.35 × spacing`.
- Purple Background spacing remains editable; values such as 24 m are supported for higher-detail mountainous surroundings.
- LiDAR force-EPSG label changed to `Force LiDAR Horizontal EPSG (blank = auto)`.
- Bunker inner rough member ways are consumed during lollipop conversion; no redundant rough spline is written.

### Fixed

- Older LiDAR CRS detection could lose a successfully parsed CRS when a later unrelated VLR raised an exception.
- Compound LAS/LAZ CRS metadata could be reported as one unresolved CRS instead of separate horizontal/vertical components.
- LiDAR Z values could be forced through the same unit assumptions as XY.
- A flat global background landscape was unsuitable for courses with large elevation changes.
- Coarse background stamps could bridge over significant terrain changes on rolling/mountainous sites.
- 2K25 could not display a rough island over a filled bunker spline.

### Removed / Deferred

- Experimental automatic `Carve Blue Mask Banks` / deep-floor water sculpting is not included in Beta 2.
- Experimental Adaptive Standard, Hybrid, Brush-72-only, and Auto-Mask terrain profiles are not exposed in the Beta 2 GUI.

### Water

Beta 2 retains:

- Fill Holes Under Blue Mask
- Remove All Terrain Under Blue Mask
- pure-blue final water mask
- OSM/local-OSM water spline import
- `natural=water`
- `waterway=*`
- open-waterway polyline handling

### Build

- Windows target: Python 3.11.x 64-bit.
- PyInstaller 6.x.
- Rasterio 1.4.4.
- `laszip-cli.exe` bundled for LAZ support.
- Release executable: `dist\tgc_gui_2k25_beta2.exe`.


## [0.5.0-2k25-beta1] - Initial fork release

Upstream baseline:

```text
HiCamino/TGC-Designer-Tools
4adb37fac73ab013da4ac6b86b02bb9579e19170
```

First fork integration commit:

```text
2a337709fe80edc164375862f9c36b041f3f07ab
Add 2K25 Local OSM, LiDAR and GeoTIFF DEM support
```

### Added

- Local OSM selector in the normal terrain/course workflow.
- Local `.osm` / JOSM XML parsing without requiring Overpass.
- Reuse of selected Local OSM during LiDAR/DEM preview and mask generation.
- GeoTIFF DEM terrain-processing path.
- Single- and multi-tile DEM mosaicing.
- Automatic DEM CRS/EPSG detection.
- Compound CRS metadata inspection.
- Automatic DEM reprojection when needed.
- Independent vertical-unit detection/conversion.
- Support for DEM elevations in meters, US survey feet, and international feet.
- Map Scale controlled DEM reduction.
- Deterministic lower-ground-biased DEM reducer using the 40th percentile.
- Rasterio PyInstaller hook and Windows runtime hook.
- Pure-blue final OSM water-mask pass.
- `natural=water` support.
- `waterway=*` support.
- Open-waterway polyline rendering.
- Screen-aware larger application startup window.
- 2K25 LiDAR tree handling for `placedObjects4`.
- Terrain brush ID dropdown.
- Absolute terrain Brush Size dropdown.

### Changed

- Recommended processing order now selects Local OSM before LiDAR/DEM processing.
- Terrain smoothing choices replaced by explicit brush IDs:
  - 72 — raw/minimal smoothing
  - 15 — light
  - 9 — medium
  - 10 — heavy/soft
- Brush Size uses absolute meter footprints: 1, 2, 3, 4, and 6 m.
- DEM Map Scale now controls actual output terrain sample spacing instead of preserving very dense native DEM cells.
- DEM reduction avoids upsampling beyond native source resolution.
- Water features are rendered last in the mask to preserve unmistakable `RGB 0,0,255`.

### Fixed

- Local OSM selected for course import was previously ignored by the LiDAR mask-generation stage.
- `natural=water` features were absent from blue-mask processing.
- Open `waterway=*` features could be closed and filled as giant triangular polygons.
- DEM NoData sentinel could fall outside the valid float32 range during reprojection.
- Very dense DEM data could generate millions of terrain brush stamps.
- US survey foot DEM elevation values could be interpreted as meters, causing roughly 3.28× vertical exaggeration.
- LiDAR tree objects required newer 2K25 object payload/container handling.
- Older GUI dimensions hid newer controls until the window was manually resized.

### Build

- Windows target: Python 3.11.x 64-bit.
- PyInstaller 6.x.
- Rasterio 1.4.4.
- `laszip-cli.exe` bundled for LAZ handling.
- Current executable target: `dist\tgc_gui_2k25_LOCAL_OSM_DEM.exe`.

### Notes

DEM support is considered beta in this release and should be tested against multiple GeoTIFF sources before relying on it for a final published course.

The upstream Apache-2.0 license and attribution are preserved.
