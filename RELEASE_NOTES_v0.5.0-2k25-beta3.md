# TGC Designer Tools 2K25 — v0.5.0-2k25-beta3

Beta 3 is the current **malifica** PGA TOUR 2K25 fork release. It keeps the Beta 2 Local OSM / LiDAR / GeoTIFF DEM workflow and incorporates the CFS alignment work, automatic course mask, OSM simplification, LiDAR proximity filters, and the validated DEM/LiDAR performance pass used in current course builds.

## Beta 3 highlights

- **CFS georeference lock** so OSM, LiDAR/DEM terrain and later course features use one projected master affine instead of independent recentering assumptions.
- **CFS Alignment Viewer** for checking and adjusting projected OSM against source terrain before course generation.
- The Alignment Viewer now uses a **higher-contrast preview-only hillshade** and a **constant 2-screen-pixel gray75 tracing overlay** so the terrain remains visible while manually nudging golf features.
- Alignment supports mouse drag, zoom, **0.10 m Arrow-key nudges**, and **1.0 m Shift+Arrow nudges**, with the final shift copied back to the main import controls.
- **Auto Red Mask** is enabled by default and preserves golf/cart-path terrain using a user-selectable **5–30 m** buffer (**5 m default**) while masking unrelated terrain.
- After buffering, conservative cleanup removes one-pixel red slivers with a **2 px minimum-width rule** and removes **enclosed red islands smaller than 25 raster pixels**; the border-connected exterior red region remains intact.
- Auto Red Mask understands **OSM multipolygon relations**, stitches fragmented outer/inner member ways, subtracts inner holes correctly, and preserves separately tagged inner golf features.
- Compound fairway/rough multipolygons are filled green in `mask.png`; multipolygon water is retained and painted pure blue; open relation fragments are not implicitly closed into fake areas.
- **Optimize OSM Spline Points** is enabled by default with feature-specific tolerances and conservative shape guards.
- **50 m LiDAR Tree and Building filters** use core golf geometry plus hole routes and exclude cart/walking paths and building/utility splines from the proximity index.
- **DEM Fast** moves heavy DEM work off the Tk main thread and accelerates arbitrary-ratio 40th-percentile reduction while preserving established output behavior.
- **LiDAR Fast** replaces several Python hot paths with vectorized NumPy/PyProj operations and an optional native-C exact-order ground rasterizer.
- The native LiDAR helper is built with generic x86-64 MinGW-w64 settings and has an exact Python fallback when a compiler/DLL is unavailable.
- The main TGCTool is **Dense / Original only**; Adaptive conversion and Course Finisher operations remain separate downstream tools.

## CFS Alignment Viewer

The viewer offers **Blend**, **Visual**, and **Hillshade** modes on the same CFS master-grid projection used by terrain and OSM conversion.

The final Hillshade view is deliberately easier to read on gently shaped golf-course terrain. It uses preview-only relief exaggeration, a lower simulated sun angle, and a robust percentile contrast stretch. None of these display changes modify the elevation data used to create the course.

The OSM overlay is a constant **2 screen pixels** wide and uses Tk `gray75` stippling for a partially transparent tracing-paper effect. This avoids the heavy zoom-scaled outlines from earlier viewer builds while remaining more visible than the prior 1 px / `gray50` experiment.

## Auto Red Mask behavior

With Auto Red Mask enabled, the generated mask uses:

- **red** — terrain excluded from the detailed course area;
- **blue** — preserved water behavior;
- **green/other OSM colors** — visual preview only; these pixels are simply non-red terrain for the terrain mask.

The crop-selection rectangle is black while Auto Red Mask is active so it remains visible over the red background.

Multipolygon relations are resolved before the selected **5–30 m** preservation buffer is applied. The GUI labels **5 m minimum / 30 m maximum**. One raster pixel corresponds to the current processing Map Scale.

After buffering, the internal cleanup keeps the automatic result practical without preventing manual editing: one-pixel red hairs/slivers are removed, enclosed red islands below 25 pixels are removed, and the border-connected exterior mask is preserved.

## Terrain generation and background behavior

The main TGCTool exposes **Dense / Original only** for course creation. **Adaptive terrain has been removed from the main tool and its GUI.** Adaptive conversion is a separate downstream utility.

When **Add Background Terrain / Remove Cliffs** is enabled, the source-derived coarse background is written first with **Brush 10**. Its footprint is **2.5 × the requested Background Scale** so the soft circular stamps overlap smoothly. The normal selected dense terrain brush is written afterward on top of that coarse fill.

The separate **Auto Background Landscape (Purple)** system can also generate a coarse source-derived outer landscape; its detail spacing remains user editable.

## Performance

### DEM

Beta 3 retains the 40th-percentile lower-ground reducer but uses a vectorized/chunked path for arbitrary source-to-target ratios. Rasterio/GDAL reprojection defaults to up to eight logical CPU threads and can be overridden with `TGC_DEM_THREADS`.

### LiDAR

Beta 3 accelerates:

- crop/classification filtering;
- multi-tile point concatenation;
- CRS reprojection;
- tree maximum rasters;
- preview raster generation;
- interpolation array preparation;
- the order-sensitive ground rasterizer.

When `tgc_lidar_fast_native.dll` is available, the exact-order ground rasterizer runs in native C. Otherwise the exact Python fallback is used.

## OSM spline optimization

**Optimize OSM Spline Points** is enabled by default. It conservatively removes redundant OSM vertices before normal spline-handle generation for bunkers, greens, tee boxes, fairways, rough, cart paths, and walking paths while preserving endpoints, sharp corners, winding, minimum point counts, and polygon-area guards.

## 50 m LiDAR Tree / Building Filters

LiDAR tree and Class-6 building generation can be constrained to within **50 m of core course geometry**. The index uses bunker, green/tee, fairway, rough, and hole-route geometry and deliberately excludes cart paths, walking paths, building placeholders, and other utility splines.

## Build

Run:

```bat
BUILD_TGC_2K25_BETA3.bat
```

Expected executable:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta3.exe
```

The build script looks for `TGC_CC`, then the project's tested LLVM-MinGW path, then MinGW-w64 clang/gcc on `PATH`. Failure to build the native helper does not prevent the main executable from being built.

Release archive:

```text
TGC-Designer-Tools-2K25-v0.5.0-2k25-beta3-Windows-x64.zip
```

## Scope

Beta 3 does **not** fold the separate Adaptive Terrain Converter or Course Finisher into the main TGCTool. The main repository release remains focused on deterministic LiDAR/DEM/OSM course creation.

This project remains an unofficial derivative of HiCamino/TGC-Designer-Tools under the upstream Apache License 2.0.
