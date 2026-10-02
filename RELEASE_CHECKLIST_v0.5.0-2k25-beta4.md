# Beta 4 release checklist

Release: **v0.5.0-2k25-beta4**

## 1. Update the local checkout

```bat
cd /d C:\TGC-Designer-Tools
git pull origin main
```

## 2. Verify source identity

```bat
python VERIFY_BETA4_SOURCE.py
```

All checks should report `PASS`.

## 3. Build

```bat
BUILD_TGC_2K25_BETA4.bat
```

Expected outputs:

```text
dist\tgc_gui_2k25_beta4.exe
dist\release_beta4\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4-Windows-x64.zip
dist\release_beta4\tgc_gui_2k25_beta4.exe.sha256.txt
dist\release_beta4\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4-Windows-x64.zip.sha256.txt
```

The build summary should explicitly report either:

```text
LiDAR rasterizer: NATIVE C
```

or:

```text
LiDAR rasterizer: PYTHON FALLBACK
```

## 4. Regression validation

Before publishing:

1. Launch the Beta 4 EXE outside the source folder.
2. Process a known LiDAR course.
3. Process a known GeoTIFF DEM course.
4. Confirm the dynamic course preview fits the actual course bounds.
5. Confirm the DEM course-boundary selector opens from the bounded preview and final crop/mask generation completes.
6. Confirm Local OSM works without network access.
7. Confirm CFS Alignment Viewer alignment remains correct.
8. Confirm Auto Red Mask still preserves compound outer/inner topology.
9. Confirm par-3 / par-4 / par-5 OSM hole waypoint normalization behaves as documented.
10. Confirm LiDAR trees are rejected on green/tee, bunker, and un-overridden fairway surfaces.
11. Confirm an explicit rough island can preserve a real fairway tree.
12. Confirm a mapped multipolygon lake/pond is written into the output course with islands preserved.
13. Confirm a Fjordland (theme 54) source/template course generates trees from the Fjordland palette.
14. Open the resulting course in PGA TOUR 2K25 Designer and confirm terrain/features remain aligned.

## 5. Publish

Install/authenticate GitHub CLI once if necessary:

```bat
gh auth login
```

Then run:

```bat
PUBLISH_TGC_2K25_BETA4.bat
```

That helper creates the prerelease/tag, uses `RELEASE_NOTES_v0.5.0-2k25-beta4.md` as the release body, and uploads the four release assets.

GitHub release title:

```text
TGC Designer Tools 2K25 - Beta 4
```

Tag:

```text
v0.5.0-2k25-beta4
```

Mark it as a **prerelease**.
