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


## Improved: DEM course-boundary selection

Large GeoTIFF DEMs no longer run the production-resolution Auto Red Mask on the Tk/UI thread before the course-boundary window appears.

Beta 3.1 now:

- prepares a bounded-resolution DEM/OSM/Auto Red Mask preview in the background;
- opens the course-boundary selector from that lightweight preview;
- maps the accepted rectangle back to full DEM coordinates;
- generates the final full-resolution mask only for the selected course area;
- includes a 100 m processing halo around the selected crop so multipolygon and cleanup behavior remains stable at the crop edge;
- performs final mask/heightmap generation on a background worker so the main GUI stays responsive;
- reports preview and final-mask timing in the processing console.

The production Auto Red Mask rules themselves are unchanged.


## Improved: OSM golf-hole waypoint normalization

OSM golf-hole centerlines are now normalized by par when they are written into the TGC course:

- par 3 routes with two OSM nodes receive a third waypoint 5 m before the pin/end node so TGC gets a distinct green-side middle waypoint;
- par 4 routes with three OSM nodes are preserved unchanged;
- par 5 routes with four OSM nodes drop the third OSM node, preserving tee + first middle waypoint + pin/end node.

The source OSM is never modified. Nonstandard node counts retain the historical TGC compatibility fallback.


## Improved: LiDAR tree playing-surface filter

LiDAR-generated tree candidates are now checked against the imported course
surface splines before they are written into the course.

- green / tee surfaces reject LiDAR tree candidates;
- bunker surfaces reject LiDAR tree candidates;
- explicit rough surfaces are allowed and override an underlying fairway;
- fairway surfaces reject LiDAR tree candidates when no rough override exists;
- OSM-mapped trees are unaffected;
- the existing optional 50 m course-proximity filter remains unchanged.

This allows intentionally mapped rough islands around real fairway trees while
preventing unclassified/elevated LiDAR returns from populating maintained
greens, tees, bunkers, and fairways.

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

This hotfix does not fold the separate Adaptive Terrain Converter or Course Finisher into the main TGCTool. It does not change Beta 3 terrain semantics, Auto Red Mask rules, OSM feature semantics, CFS alignment, or LiDAR behavior; the DEM boundary-selection path is optimized as described above.

This project remains an unofficial derivative of HiCamino/TGC-Designer-Tools under the upstream Apache License 2.0.
