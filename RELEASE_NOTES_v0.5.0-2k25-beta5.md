# TGC Designer Tools 2K25 — v0.5.0-2k25-beta5

Beta 5 publishes the current main-line TGC Designer Tools 2K25 feature set without adding any new feature work beyond the already-tested Beta 5 development tree.

## Highlights

- Regional Theme system with calibrated real-course tree planting profiles.
- Donor Designer theme plus playing-surface and terrain-material presets.
- Heroic, Epic, and Legacy LiDAR tree-scale modes.
- Public USGS 3DEP AWS EPT acquisition discovery/download from Local OSM.
- Acquisition chooser with WESM collection metadata when available.
- Trees Only workflows that keep existing DEM terrain.
- Terrain Gap Fill using older/fallback LiDAR only where the primary terrain is missing.
- OSM-defined terrain master extent for Local OSM LiDAR workflows.
- Existing Beta 4 improvements: dynamic course preview, par-aware hole normalization, LiDAR playing-surface tree filters, OSM multipolygon water import, and Fjordland tree support.

## Regional Themes

Beta 5 can use JSON-backed regional profiles derived from finished reference courses. Enabled profiles in the current release include the calibrated profiles already present in the Beta 5 tree-profile directory, including Texas Hill Country, Niagara Escarpment, Carolina Piedmont (Autumn), Virginia Coastal Plain, Hudson Valley Mixed Forest, Northern Rockies, Monterey Bay Coast, Georgia Piedmont, San Francisco Peninsula, and South Carolina Lowcountry.

Regional profiles may control:

- source Designer theme;
- weighted tree-prefab mix;
- donor-calibrated X/Y/Z tree scale distributions;
- bunker, green, fringe, fairway, rough and heavy-rough textures;
- terrain/splat material slots.

The reviewed Coastal Links profile remains disabled where the donor contains no suitable natural tree population.

## Tree Scale

- **Heroic (Beta 5)** remains the default.
- **Epic** preserves the same population/mix and scales final trees one additional 20% above Heroic.
- **Legacy LiDAR** remains available for comparison.

## USGS AWS EPT

With a Local OSM file selected, Beta 5 can discover overlapping public USGS 3DEP LiDAR acquisitions and show collection/quality metadata before download. The selected acquisition can be used for:

- normal Terrain + Trees;
- Trees Only while preserving DEM terrain;
- Terrain Gap Fill while preserving valid primary terrain.

Public AWS EPT access does not require an AWS account.

## Terrain Gap Fill

Fallback LiDAR is projected onto the existing master grid and only fills cells where primary terrain is missing/NaN. Valid primary terrain is never overwritten.

When enough overlap exists, Beta 5 measures a robust median vertical offset and applies it only within the existing 2 m safety limit.

## OSM-defined terrain master extent

For Local OSM LiDAR workflows, Beta 5 can reframe the terrain to the golf-course OSM extent plus the established safety buffer. The master extent is snapped to the existing terrain cell lattice, preserving valid primary elevations without resampling and allowing later gap-fill acquisitions to populate missing edge/interior cells.

## Fixed: DEM Auto Red Mask production crop

Beta 5 includes the DEM fix validated against the reported Cape Wickham case.

The fast bounded DEM boundary preview remains, but the final production sequence now follows Beta 3/3.1 semantics:

1. Render OSM + Auto Red Mask on the full-resolution full DEM coordinate frame.
2. Crop the completed mask and the DEM with the exact same accepted bounds.
3. Build the normal CFS master grid from those crop bounds.

The Beta 4 100 m crop-halo production-mask regeneration path is no longer used.

Auto Red Mask polygon logic, buffer rules, multipolygon behavior and cleanup rules are otherwise unchanged.

## Windows build

Run:

```bat
BUILD_TGC_2K25_BETA5.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta5.exe
```

Expected release archive:

```text
C:\TGC-Designer-Tools\dist\release_beta5\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta5-Windows-x64.zip
```

The build runs `VERIFY_BETA5_SOURCE.py`, performs Python syntax checks, attempts to compile the native LiDAR rasterizer, builds the one-file PyInstaller executable, packages the regional profile directory, and writes SHA-256 checksum files.

## Publishing

After validation:

```bat
PUBLISH_TGC_2K25_BETA5.bat
```

Tag: `v0.5.0-2k25-beta5`

Release title: `TGC Designer Tools 2K25 - Beta 5`

Publish as a prerelease.

## Scope

Beta 5 is the main TGCTool release. The Adaptive Terrain Converter, Course Finisher, Yardage/Greens/Course Map tools, and Crazy Bunkers remain separate downstream utilities.

This project remains an unofficial derivative of HiCamino/TGC-Designer-Tools under the upstream Apache License 2.0.
