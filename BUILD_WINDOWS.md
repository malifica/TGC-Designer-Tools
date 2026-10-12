# Windows Build Guide

This guide builds **TGC Designer Tools 2K25 - Beta 6** on Windows.

## Tested development environment

```text
Windows 10/11 64-bit
Python 3.11.x 64-bit
PyInstaller 6.x
Rasterio 1.4.4
Git
```

The normal checkout is `C:\TGC-Designer-Tools` and the tested virtual environment is `C:\TGC-Designer-Tools\.venv_local_osm`.

## Install dependencies

```bat
cd /d C:\TGC-Designer-Tools
call .venv_local_osm\Scripts\activate.bat
python -m pip install -r requirements.txt
python -c "import rasterio; print('Rasterio', rasterio.__version__); print('GDAL', rasterio.__gdal_version__)"
```

Beta 6 uses modern `laspy` 2.x. LAZ support is available through `laspy[lazrs]`; the repository also retains the upstream `laszip` tools.

## Verify the Beta 6 source

Run the complete Beta 6 verification set before packaging:

```bat
python VERIFY_BETA6_SOURCE.py
python VERIFY_BETA6_LIDAR_TREE_MASK_MASTER_GRID_FIX_V1.py
python VERIFY_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1.py
python VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py
python VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py
python VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py
python VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py
python VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py
```

The build helper also syntax-checks the main LiDAR/DEM, OSM, tree-profile, custom-layout, mask-alignment, and CFS modules.

You can run from source with:

```bat
python tgc_gui.py
```

## Build Beta 6

Run:

```bat
BUILD_TGC_2K25_BETA6.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta6.exe
```

Expected release files:

```text
C:\TGC-Designer-Tools\dist\release_beta6\
    TGC-Designer-Tools-2K25-v0.5.0-2k25-beta6-Windows-x64.zip
    tgc_gui_2k25_beta6.exe.sha256.txt
    TGC-Designer-Tools-2K25-v0.5.0-2k25-beta6-Windows-x64.zip.sha256.txt
```

## Native LiDAR helper

`BUILD_TGC_2K25_BETA6.bat` attempts to compile `lidar_fast_native.c` into `tgc_lidar_fast_native.dll`. Compiler lookup order is:

1. `TGC_CC`
2. `D:\llvm-mingw\bin\x86_64-w64-mingw32-clang.exe`
3. `x86_64-w64-mingw32-clang.exe` on `PATH`
4. `x86_64-w64-mingw32-gcc.exe` on `PATH`

If no compiler is available, the application can still use the exact Python rasterizer fallback.

## Rasterio / GDAL / PROJ packaging

Keep these files in the source tree for DEM-enabled PyInstaller builds:

```text
PyInstaller/hooks/hook-rasterio.py
PyInstaller/rthook_rasterio.py
```

The release build also bundles `tree_profiles` and `laszip/laszip-cli.exe`.

## Beta 6 regression checks

Before publishing a newly built binary, verify at minimum:

1. Normal matched Local OSM + LiDAR and Local OSM + DEM workflows.
2. CFS Alignment Viewer opens before final mask acceptance and shifted alignment rebuilds a correctly sized `mask.png`.
3. Custom unmatched OSM preserves design scale/orientation, centers correctly, previews correctly, and imports with the same transform used by the mask.
4. AWS EPT discovery and Terrain Gap Fill remain blocked in unmatched-OSM mode.
5. `golf=cartpath`, explicit `golf=path`, and optional automobile roads are separated correctly.
6. LiDAR trees remain aligned to the final master grid and respect playing-surface filtering.
7. Slope-Locked Hulkify scales horizontal geometry and relief together.
8. Regional tree profiles, including Pacific Northwest, load correctly with Standard/Heroic/Epic/Mythic sizing.
9. Output courses open in PGA TOUR 2K25 Designer with terrain and OSM features aligned.

## Release identity

Beta 6 uses:

```text
Tag:        v0.5.0-2k25-beta6
EXE:        tgc_gui_2k25_beta6.exe
Prerelease: TGC Designer Tools 2K25 - Beta 6
```

Published release artifacts must come from the executable that was actually tested. Do not substitute a later rebuild without testing and updating the release hashes.

## Git remotes

Recommended:

```text
origin   -> https://github.com/malifica/TGC-Designer-Tools.git
upstream -> https://github.com/HiCamino/TGC-Designer-Tools.git
```

This fork modifies central terrain, OSM, masking, and LiDAR/DEM processing files. Review upstream changes before merging them.
