# TGC Designer Tools 2K25 — v0.5.0-2k25-beta4

Beta 4 consolidates the post-Beta-3.1 work on the main TGCTool into a new Windows prerelease. It keeps the established LiDAR / GeoTIFF DEM / Local OSM / CFS workflow and adds the course-import, tree-filtering, preview-performance, and 2K25 theme-tree improvements completed after Beta 3.1.

## Highlights

- Dynamic course preview sizing based on actual course bounds.
- Faster GeoTIFF DEM course-boundary selection with bounded preview preparation off the Tk/UI thread.
- Par-aware OSM golf-hole waypoint normalization.
- LiDAR tree exclusion from maintained playing surfaces, while explicit rough islands can preserve intentional fairway trees.
- OSM multipolygon lakes/ponds imported into the actual 2K25 course with stitched relation topology and physical inner islands.
- Full Fjordland (theme 54) tree palette support from the supplied 2K25 reference course.
- Beta 3.1's automatic LiDAR CRS fix for foot/US-survey-foot projected systems remains included.

## Improved: dynamic course preview

The course preview now sizes itself from the actual rendered course bounds instead of forcing every course into the same fixed square presentation.

This makes long, narrow, or unusually oriented courses easier to inspect without changing the course data itself.

## Improved: faster DEM course-boundary selection

Large GeoTIFF DEM workflows now prepare a bounded-resolution DEM/OSM/Auto Red Mask selector preview in the background before the crop window opens.

After the user accepts the course boundary, TGCTool:

- maps the accepted selection back to full DEM coordinates;
- generates the production mask only for the selected course area;
- retains a 100 m processing halo around the accepted crop so multipolygon and cleanup behavior remains stable at the edge;
- performs final mask/heightmap work off the Tk main thread.

The production Auto Red Mask semantics remain unchanged.

## Improved: OSM golf-hole waypoint normalization

OSM golf-hole centerlines are normalized by par when written into the course:

- standard par 3 two-node routes receive a green-side middle waypoint 5 m before the pin/end node;
- standard par 4 three-node routes remain unchanged;
- standard par 5 four-node routes keep tee + first middle waypoint + pin/end node.

The source OSM is never modified, and nonstandard node counts retain the historical compatibility fallback.

## Improved: LiDAR tree playing-surface filtering

LiDAR-generated tree candidates are now checked against imported course surfaces before they are written:

- greens / tee boxes reject LiDAR tree candidates;
- bunkers reject LiDAR tree candidates;
- fairways reject LiDAR tree candidates unless an explicit rough spline overrides that location;
- OSM-mapped trees are unaffected;
- the optional 50 m course-proximity filter remains unchanged.

This keeps unclassified/elevated LiDAR returns from populating maintained playing surfaces while still allowing deliberately mapped rough islands around real fairway trees.

## Improved: OSM multipolygon water import

The OSM importer now writes standard mapped lakes and ponds into the actual 2K25 course using the same relation topology already used by Auto Red Mask.

- closed `natural=water` ways are imported as filled water placeholder splines;
- `type=multipolygon` water relations are reconstructed from outer/inner member ways;
- fragmented relation shorelines are stitched by shared endpoint node IDs;
- inner islands are preserved as physical holes using the established narrow-neck/lollipop representation required by TGC filled splines;
- consumed relation members are not independently fill-closed into false water;
- incomplete Local OSM relations fail closed with a warning.

## Added: Fjordland theme trees

Theme ID **54** is now recognized as **Fjordland**.

The supplied reference course contained 44 actual Fjordland tree prefabs. Beta 4 adds all of them to the 2K25 global tree dictionary without renumbering existing tree IDs:

- 15 broad/wider tree assets in the normal-tree palette;
- 29 narrow/columnar/conifer assets in the skinny-tree palette;
- 33 new global asset paths appended to the existing dictionary;
- 11 existing global assets reused.

Theme shrub/bush assets are intentionally excluded from LiDAR tree placement.

The main TGCTool now has explicit 2K25 tree palettes for Desert, Boreal, Tropical, Countryside, Harvest, Winter, Delta, Rustic, Swiss, Steppe, Autumn, Highlands, Temperate, and Fjordland.

## Retained from Beta 3.1

Beta 4 retains the automatic LiDAR CRS correction introduced in Beta 3.1. When LAS/LAZ horizontal CRS metadata resolves to an EPSG code, the working projection is rebuilt from the canonical EPSG definition so meter-normalized LiDAR coordinates remain aligned with OSM/CFS data even when the source CRS is defined in feet or US survey feet.

## Windows build

Run:

```bat
BUILD_TGC_2K25_BETA4.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta4.exe
```

Expected release archive:

```text
C:\TGC-Designer-Tools\dist\release_beta4\TGC-Designer-Tools-2K25-v0.5.0-2k25-beta4-Windows-x64.zip
```

The build runs `VERIFY_BETA4_SOURCE.py`, performs Python syntax checks, attempts to compile the optional native LiDAR rasterizer, builds the one-file PyInstaller executable, creates the release ZIP, and writes SHA-256 checksum files.

If MinGW-w64 is unavailable, the EXE still builds with the exact Python LiDAR rasterizer fallback and reports that status in the build summary.

## Publishing

After validation, run:

```bat
PUBLISH_TGC_2K25_BETA4.bat
```

The publish helper requires GitHub CLI (`gh`) to be installed and authenticated. It creates the prerelease/tag `v0.5.0-2k25-beta4` from `main`, uses this file as the release body, and uploads the EXE, release ZIP, and both SHA-256 files.

## Scope

Beta 4 remains the **main TGCTool** release. The separate Adaptive Terrain Converter and Course Finisher are not folded into this repository release.

This project remains an unofficial derivative of HiCamino/TGC-Designer-Tools under the upstream Apache License 2.0.
