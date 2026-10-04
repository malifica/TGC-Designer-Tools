# Beta 4.1 hotfix release checklist

Release: **v0.5.0-2k25-beta4.1**

## 1. Use the hotfix branch

```bat
cd /d C:\TGC-Designer-Tools
git fetch origin
git checkout release/v0.5.0-2k25-beta4.1
git pull
```

## 2. Verify source

```bat
python VERIFY_BETA4_1_SOURCE.py
```

All checks should report `PASS`.

## 3. Build

```bat
BUILD_TGC_2K25_BETA4_1.bat
```

Expected outputs:

```text
dist\tgc_gui_2k25_beta4_1.exe
dist\release_beta4_1\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4.1-Windows-x64.zip
dist\release_beta4_1\tgc_gui_2k25_beta4_1.exe.sha256.txt
dist\release_beta4_1\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4.1-Windows-x64.zip.sha256.txt
```

## 4. Regression validation

1. Process a known GeoTIFF DEM course with Auto Red Mask enabled.
2. Confirm the fast bounded boundary preview still opens.
3. Confirm the console reports: `Generating final DEM mask on full DEM extent (Beta 3/3.1 production semantics).`
4. Confirm `mask.png` and `heightmap.npy` use the same selected crop bounds.
5. Import terrain/features and export the course.
6. Open the course in PGA TOUR 2K25 Designer.
7. Spot-check a LiDAR course to confirm no LiDAR regression.
8. Confirm CFS alignment, multipolygon water, tree filtering and hole normalization remain unchanged.

## 5. Publish

```bat
PUBLISH_TGC_2K25_BETA4_1.bat
```

Tag: `v0.5.0-2k25-beta4.1`

Title: `TGC Designer Tools 2K25 - Beta 4.1 Hotfix`

Publish as a prerelease.
