# TGC Designer Tools 2K25 — v0.5.0-2k25-beta4.1

Beta 4.1 is a focused hotfix for the GeoTIFF DEM + Auto Red Mask production path. It is based directly on the published Beta 4 release and does not add Beta 5 development features.

## Fixed: DEM Auto Red Mask production crop

Beta 4 changed the final DEM mask workflow so that, after the user selected course bounds, the program rebuilt OSM + Auto Red Mask only on the selected crop plus a 100 m processing halo and then cropped that local mask again.

A reported DEM course exposed a compatibility problem in that path. Rebuilding the same course with the restored Beta 3/3.1 production-mask semantics opened correctly in PGA TOUR 2K25.

Beta 4.1 therefore restores the proven production sequence:

1. Keep the fast bounded-resolution DEM boundary preview introduced in Beta 4.
2. After the crop is accepted, render the final OSM + Auto Red Mask once on the full-resolution full DEM coordinate frame.
3. Crop the completed mask and DEM together using the exact same accepted bounds.
4. Build the normal CFS master grid from those accepted crop bounds.

The 100 m crop-halo mask regeneration path is removed.

## Unchanged

- Auto Red Mask polygon/multipolygon logic itself is unchanged.
- 5–30 m Auto Red Mask buffer behavior is unchanged.
- 2 px red-sliver cleanup and 25 px enclosed-island cleanup are unchanged.
- LiDAR processing is unchanged.
- DEM mosaicing, reprojection, vertical-unit handling, Map Scale reduction and performance work are unchanged.
- CFS Alignment Viewer and master-grid crop logic are unchanged.
- OSM water multipolygon import, LiDAR tree filters, par-aware hole normalization and Fjordland tree support are unchanged.
- Adaptive Terrain Converter and Course Finisher remain separate downstream tools.

## Validation

The hotfix was validated by rebuilding the reported DEM-sourced Cape Wickham course with Auto Red Mask in the current Beta 5 development tree after applying the same DEM production-mask fix. The rebuilt course opened correctly in PGA TOUR 2K25.

## Windows build

Run:

```bat
BUILD_TGC_2K25_BETA4_1.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta4_1.exe
```

Expected release archive:

```text
C:\TGC-Designer-Tools\dist\release_beta4_1\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4.1-Windows-x64.zip
```

## Publishing

After validation, run:

```bat
PUBLISH_TGC_2K25_BETA4_1.bat
```

Tag:

```text
v0.5.0-2k25-beta4.1
```

Release title:

```text
TGC Designer Tools 2K25 - Beta 4.1 Hotfix
```

Mark it as a prerelease.
