# TGC Designer Tools 2K25 — v0.5.0-2k25-beta3.1

Beta 3.1 is a focused hotfix for the Beta 3 release. It keeps the full Beta 3 LiDAR / GeoTIFF DEM / Local OSM / CFS workflow and corrects automatic LiDAR projection for foot-based projected coordinate systems.

## Fixed: Auto LiDAR projection

Some LAS/LAZ files correctly exposed a projected horizontal CRS and unit metadata, but the WKT-derived working projection could remain in feet or US survey feet even though TGCTool had already normalized the LiDAR XY coordinates to meters.

That produced an OSM/CFS alignment mismatch unless the user manually forced the horizontal EPSG.

Beta 3.1 changes the modern LAS/LAZ CRS path so that:

- the LAS/LAZ header is still parsed automatically;
- compound CRS metadata is still split into horizontal and vertical components;
- horizontal and vertical unit conversion remains independent;
- when the horizontal CRS resolves to an EPSG code, the working projection is rebuilt from that canonical EPSG definition with meter-normalized projected output;
- when no EPSG is resolvable, the existing direct-CRS fallback remains available.

## Regression validation

The hotfix was validated against a compound Colorado State Plane South dataset where Auto Detect reports:

```text
Horizontal EPSG: 6432
NAD83(2011) / Colorado South (ftUS)
```

Before the hotfix, OSM alignment required manually forcing EPSG 6432 (or the closely related legacy EPSG 2233).

After the hotfix, leaving **Force LiDAR Horizontal EPSG** blank produces the same correct OSM alignment as manually forcing EPSG 6432.

The console now reports:

```text
Working projection rebuilt from canonical EPSG:6432
```

## Windows build

Run:

```bat
BUILD_TGC_2K25_BETA3_1.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta3_1.exe
```

Expected release archive:

```text
TGC-Designer-Tools-2K25-v0.5.0-2k25-beta3.1-Windows-x64.zip
```

The build still attempts to compile and bundle `tgc_lidar_fast_native.dll`. If the required MinGW-w64 compiler is unavailable, the EXE can still be built with the exact Python fallback. The Beta 3.1 build summary explicitly reports which LiDAR rasterizer was packaged.

## Scope

This hotfix does not fold the separate Adaptive Terrain Converter or Course Finisher into the main TGCTool. It does not otherwise change the Beta 3 terrain, masking, OSM optimization, CFS alignment, or LiDAR/DEM performance behavior.

This project remains an unofficial derivative of HiCamino/TGC-Designer-Tools under the upstream Apache License 2.0.
