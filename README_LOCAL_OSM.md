# HiCamino TGC Designer Tools — Local OSM LiDAR Build Patch

Target: `HiCamino/TGC-Designer-Tools` main.

Observed upstream main tree when prepared:
`4adb37fac73ab013da4ac6b86b02bb9579e19170`

## Added behavior

The normal **Select and Import Heightmap and OSM into Course** workflow gets a new field:

**Local OSM File (blank = online)**

Use **Browse...** to select a local `.osm` / JOSM export.

When a local file is selected:
- it is parsed locally;
- the existing LiDAR GeoPointCloud is used for alignment;
- all normal OSM import options still apply;
- missing referenced nodes are NOT fetched from Overpass;
- the local file must therefore be a complete export.

When the field is blank:
- HiCamino's original online Overpass behavior is unchanged.

The existing separate **Make Flat Course From OSM File** feature is unchanged.

## Files changed
- `tgc_gui.py`
- `tgc_image_terrain.py`
- `OSMTGC.py`

The patcher creates `.pre_local_osm.bak` backups.

## Build
1. Download/extract a clean HiCamino source checkout.
2. Copy this package's files into the source root.
3. Run `BUILD_WINDOWS_LOCAL_OSM.bat`.
4. The target output is:
   `dist\tgc_gui_2k25_LOCAL_OSM.exe`

The build script requires 64-bit Python 3.11 and Git. It does not install either automatically.

This is an unofficial modification of the Apache-2.0 licensed upstream project.
