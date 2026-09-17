# Windows Build Guide

This guide builds the 2K25 Local OSM / LiDAR / DEM fork on Windows.

## Tested development environment

The current working fork was developed with:

```text
Windows 10/11 64-bit
Python 3.11.x 64-bit
PyInstaller 6.x
Rasterio 1.4.4
Git
```

A modern `laspy` 2.x installation is required by the current loader code.

The repository also contains `laszip/laszip-cli.exe`, which is bundled into the packaged application.

## Existing working checkout

The development checkout used for this fork is:

```text
C:\TGC-Designer-Tools
```

If you already have a working checkout and virtual environment, do not reclone it just to build.

Example environment:

```text
C:\TGC-Designer-Tools\.venv_local_osm
```

Activate it:

```bat
cd /d C:\TGC-Designer-Tools
call .venv_local_osm\Scripts\activate.bat
```

## Install / verify DEM dependency

Install the Rasterio version used by this fork:

```bat
python -m pip install --upgrade "rasterio==1.4.4"
```

Verify:

```bat
python -c "import rasterio; print('Rasterio', rasterio.__version__); print('GDAL', rasterio.__gdal_version__)"
```

You should also verify the core application dependencies from the upstream project are installed in the same environment.

## Syntax check before building

Run:

```bat
python -m py_compile dem_map_api.py tgc_gui.py lidar_map_api.py tgc_image_terrain.py OSMTGC.py infill_image.py usgs_lidar_parser.py
```

Do not package a build if this step fails.

## Test from source first

Before building the EXE:

```bat
python tgc_gui.py
```

Recommended quick checks:

- application opens at the larger screen-aware size;
- Local OSM browse control appears;
- DEM GeoTIFF selector appears;
- terrain Brush and Brush Size selectors appear;
- LiDAR processing still opens and runs;
- DEM processing starts and logs CRS/EPSG and vertical-unit information.

## Build the EXE

The repository contains:

```text
BUILD_TGC_2K25_LOCAL_OSM_DEM.bat
```

It installs/verifies Rasterio, runs syntax checks, and executes PyInstaller.

Run:

```bat
BUILD_TGC_2K25_LOCAL_OSM_DEM.bat
```

Or use the equivalent PyInstaller command directly:

```bat
python -m PyInstaller ^
 --noconfirm ^
 --clean ^
 --onefile ^
 --name "tgc_gui_2k25_LOCAL_OSM_DEM" ^
 --add-binary "./laszip/laszip-cli.exe;laszip" ^
 --additional-hooks-dir "./PyInstaller/hooks/" ^
 --runtime-hook "./PyInstaller/rthook_rasterio.py" ^
 tgc_gui.py
```

Expected output:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_LOCAL_OSM_DEM.exe
```

## Why Rasterio has custom PyInstaller files

Rasterio Windows wheels include GDAL/PROJ support and DLLs that may not be discovered by a basic one-file PyInstaller build.

This fork includes:

```text
PyInstaller/hooks/hook-rasterio.py
PyInstaller/rthook_rasterio.py
```

The hook collects Rasterio submodules, package data, dynamic libraries, and Windows wheel libraries.

The runtime hook makes bundled GDAL/PROJ data directories available when the one-file EXE starts.

Do not omit these files from a DEM-enabled release build.

## Release verification

Before publishing a binary:

1. Run the EXE outside the source folder.
2. Process a known LiDAR test.
3. Process a known DEM GeoTIFF.
4. Verify Local OSM works with networking unavailable.
5. Confirm water appears pure blue in `mask.png`.
6. Verify terrain import completes.
7. Open the resulting course in PGA TOUR 2K25 course designer.
8. Confirm trees, terrain, and OSM features are present.

## SHA-256 checksum

Create a checksum for the release EXE:

```bat
powershell -NoProfile -Command "(Get-FileHash 'dist\tgc_gui_2k25_LOCAL_OSM_DEM.exe' -Algorithm SHA256).Hash | Out-File 'dist\tgc_gui_2k25_LOCAL_OSM_DEM.exe.sha256.txt' -Encoding ascii"
```

## Suggested release package

Create:

```text
TGC-Designer-Tools-2K25-v0.5.0-beta1-Windows-x64\
    tgc_gui_2k25_LOCAL_OSM_DEM.exe
    LICENSE
    README.md
    CHANGELOG.md
```

Publish the ZIP and checksum as GitHub Release assets.

## Git remote layout used by the fork

Recommended:

```text
origin   -> https://github.com/malifica/TGC-Designer-Tools.git
upstream -> https://github.com/HiCamino/TGC-Designer-Tools.git
```

Check with:

```bat
git remote -v
```

To inspect future upstream changes without automatically merging them:

```bat
git fetch upstream
git log --oneline main..upstream/main
```

Because this fork modifies several central terrain-processing files, review upstream changes before merging them.
