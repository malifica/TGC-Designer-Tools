# Beta 5 release checklist

Release: **v0.5.0-2k25-beta5**

## 1. Update main

```bat
cd /d C:\TGC-Designer-Tools
git fetch origin
git pull origin main
```

## 2. Verify source

```bat
python VERIFY_BETA5_SOURCE.py
```

All checks should report `PASS`.

## 3. Build

```bat
BUILD_TGC_2K25_BETA5.bat
```

Expected outputs:

```text
dist\tgc_gui_2k25_beta5.exe
dist\release_beta5\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta5-Windows-x64.zip
dist\release_beta5\tgc_gui_2k25_beta5.exe.sha256.txt
dist\release_beta5\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta5-Windows-x64.zip.sha256.txt
```

## 4. Regression validation

1. Launch the Beta 5 EXE outside the source folder.
2. Confirm title: `TGC Designer Tools 2K25 - Beta 5`.
3. Open/import a known 2K25 course.
4. Process a known LiDAR course.
5. Process a known GeoTIFF DEM course with Auto Red Mask enabled.
6. Confirm the DEM console reports `Generating final DEM mask on full DEM extent (Beta 3/3.1 production semantics).`
7. Confirm the generated DEM course opens in PGA TOUR 2K25 Designer.
8. Verify Local OSM and CFS Alignment Viewer.
9. Verify at least one Regional Theme and material preset.
10. Verify Heroic/Epic/Legacy tree-scale selection.
11. Spot-check USGS AWS EPT acquisition discovery.
12. Spot-check Trees Only and Terrain Gap Fill only if source data is available.
13. Confirm OSM multipolygon water and par-aware hole normalization remain intact.

## 5. Publish

```bat
PUBLISH_TGC_2K25_BETA5.bat
```

Tag: `v0.5.0-2k25-beta5`

Title: `TGC Designer Tools 2K25 - Beta 5`

Publish as a prerelease.
