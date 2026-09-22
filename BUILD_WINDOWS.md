# Windows Build Guide

This guide builds the PGA TOUR 2K25 Beta 3.1 hotfix fork on Windows.

## Tested development environment

```text
Windows 10/11 64-bit
Python 3.11.x 64-bit
PyInstaller 6.x
Rasterio 1.4.4
Git
```

The current development checkout is:

```text
C:\TGC-Designer-Tools
```

The tested virtual environment is:

```text
C:\TGC-Designer-Tools\.venv_local_osm
```

## Install dependencies

Activate the environment:

```bat
cd /d C:\TGC-Designer-Tools
call .venv_local_osm\Scripts\activate.bat
```

Install or refresh the repository requirements:

```bat
python -m pip install -r requirements.txt
```

Verify the key DEM dependency:

```bat
python -c "import rasterio; print('Rasterio', rasterio.__version__); print('GDAL', rasterio.__gdal_version__)"
```

Beta 3.1 uses modern `laspy` 2.x. LAZ support is available through `laspy[lazrs]`; the repository also retains the upstream `laszip` tools.

## Syntax check

The Beta 3.1 build script checks:

```text
tgc_gui.py
dem_map_api.py
lidar_map_api.py
lidar_fast_native.py
usgs_lidar_parser.py
infill_image.py
tgc_image_terrain.py
OSMTGC.py
auto_red_mask.py
cfs_georef.py
lidar_feature_filter.py
osm_alignment_viewer.py
```

You can also run the application from source before packaging:

```bat
python tgc_gui.py
```

## Build Beta 3.1 hotfix

Run:

```bat
BUILD_TGC_2K25_BETA3_1.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta3_1.exe
```

The script also creates:

```text
C:\TGC-Designer-Tools\dist\release_beta3_1\
    TGC-Designer-Tools-2K25-v0.5.0-2k25-beta3.1-Windows-x64.zip
    tgc_gui_2k25_beta3_1.exe.sha256.txt
    TGC-Designer-Tools-2K25-v0.5.0-2k25-beta3.1-Windows-x64.zip.sha256.txt
```

## Native LiDAR helper

`BUILD_TGC_2K25_BETA3_1.bat` attempts to compile:

```text
lidar_fast_native.c
```

into:

```text
tgc_lidar_fast_native.dll
```

Compiler lookup order:

1. `TGC_CC`
2. `D:\llvm-mingw\bin\x86_64-w64-mingw32-clang.exe`
3. `x86_64-w64-mingw32-clang.exe` on `PATH`
4. `x86_64-w64-mingw32-gcc.exe` on `PATH`

The native helper uses generic x86-64 compiler settings. If no compiler is available, or the DLL build fails, the main EXE is still built and uses the exact Python rasterizer fallback. The Beta 3.1 build summary explicitly reports either `LiDAR rasterizer: NATIVE C` or `LiDAR rasterizer: PYTHON FALLBACK` so source builders can tell which path was packaged.

## Rasterio / GDAL / PROJ packaging

Rasterio Windows wheels include GDAL/PROJ data and DLLs that a minimal PyInstaller build may not discover automatically.

Beta 3.1 retains:

```text
PyInstaller/hooks/hook-rasterio.py
PyInstaller/rthook_rasterio.py
```

Do not remove these from a DEM-enabled release.

## Release verification

Before publishing the Windows package:

1. Run the EXE outside the source folder.
2. Process a known LiDAR course.
3. Process a known GeoTIFF DEM course.
4. Verify Local OSM works with networking unavailable.
5. Confirm the CFS alignment viewer displays OSM against terrain correctly.
6. Confirm Auto Red Mask preserves compound outer/inner OSM geometry.
7. Confirm relation fairways/rough are visibly filled in `mask.png`.
8. Confirm relation water is pure blue.
9. Import terrain/features and open the output course in PGA TOUR 2K25 Designer.
10. Verify the resulting course geometry and terrain are aligned.

## Git remotes

Recommended:

```text
origin   -> https://github.com/malifica/TGC-Designer-Tools.git
upstream -> https://github.com/HiCamino/TGC-Designer-Tools.git
```

This fork modifies central terrain, OSM, masking, and LiDAR/DEM processing files. Review upstream changes before merging them.
