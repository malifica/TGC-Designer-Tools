# TGC Designer Tools — PGA TOUR 2K25 Fork

A streamlined 2K25-focused fork of **HiCamino/TGC-Designer-Tools** for building real-world courses from **LiDAR, GeoTIFF DEM, and OpenStreetMap data**.

Current release: **v0.5.0-2k25-beta3**
Maintainer: **malifica**
Upstream: https://github.com/HiCamino/TGC-Designer-Tools

This project remains under the upstream **Apache License 2.0**.

---

## What Beta 3 adds

- **PGA TOUR 2K25** course-structure support.
- **Local OSM / JOSM** in the normal LiDAR and DEM workflow.
- **GeoTIFF DEM** support, including multi-tile mosaics and automatic CRS/EPSG handling.
- **CFS projected-master-grid georeference lock** shared by terrain and OSM so later feature import uses the same projected affine.
- **CFS Alignment Viewer** with drag/keyboard nudging, Visual / Hillshade / Blend views, higher-contrast terrain hillshade, and a thin tracing-style OSM overlay.
- **Auto Red Mask** enabled by default with a user-selectable **5–30 m** golf/cart preservation buffer (**5 m default**).
- Conservative mask cleanup: a **2 px minimum red width** plus removal of **enclosed red islands smaller than 25 raster pixels**.
- Correct **OSM multipolygon outer/inner handling** in the automatic mask.
- Green preview fill for compound fairway/rough relations and pure-blue relation water.
- **DEM Fast** vectorized/chunked terrain reduction and threaded heavy processing.
- **LiDAR Fast** vectorized filtering/reprojection/raster preparation plus an optional exact native-C ground rasterizer and exact Python fallback.
- Modern LAS/LAZ compound-CRS handling with separate horizontal and vertical units.
- Dense terrain generation with selectable brush/footprint and source-derived background terrain.
- Improved 2K25 LiDAR tree placement and OSM bunker inner-island conversion.
- **50 m LiDAR Tree and Building filters**, enabled by default for their corresponding LiDAR feature types.
- **Optimize OSM Spline Points**, enabled by default, with conservative shape-preservation guards.
- **Adaptive terrain removed from the main TGCTool and GUI**; Adaptive conversion is a separate downstream tool.
- **Course Finisher remains a separate downstream tool** and is not folded into the main TGCTool repository release.

---

## Recommended workflow

When using a local OSM file, select it **before processing LiDAR or DEM data**.

1. Open/import the target `.course`.
2. Select **Local OSM File** if using a JOSM/OSM export.
3. Choose **Map Scale**.
4. Process **LiDAR or GeoTIFF DEM**.
5. Open **CFS Alignment Viewer** and verify the OSM overlay against the terrain.
6. Nudge the OSM alignment only when needed, then apply the shift back to the main window.
7. Crop/select the course area.
8. Inspect `mask.png`; Auto Red Mask preserves course features and masks unrelated detailed terrain.
9. Choose terrain-generation settings.
10. Import terrain and OSM features.
11. Export the generated `.course`.

Cart-path finishing and native-water finishing are intentionally downstream operations and are handled by the separate Course Finisher workflow rather than the main TGCTool.

---

## CFS georeference lock and Alignment Viewer

Beta 3 uses a **CFS projected master grid** so terrain previews, mask generation, OSM alignment, and later OSM-to-course conversion share the same projected reference instead of independently reconstructing/recentering the raster.

The **CFS Alignment Viewer** provides three terrain views:

- **Blend** — combined visual/relief view;
- **Visual** — source preview colors;
- **Hillshade** — terrain-relief view for checking subtle grading and contour alignment.

The Hillshade view is intentionally more expressive than a default cartographic hillshade. It uses preview-only relief exaggeration, a lower simulated sun angle, and a robust contrast stretch so gentle golf-course slopes, banks, drainage and shaping are easier to see. These display changes **do not alter the source elevations or generated terrain**.

OSM/golf features are shown as a tracing overlay rather than a heavy finished drawing:

- constant **2 screen-pixel** stroke while zooming;
- a denser Tk `gray75` stipple for a partially transparent tracing effect;
- terrain remains visible underneath while the user aligns features.

Alignment controls include mouse dragging, zoom controls, **0.10 m Arrow-key nudges**, and **1.0 m Shift+Arrow nudges**. The final shift can be copied back to the main Import Terrain and Features controls.

---

## Auto Red Mask

Auto Red Mask is **ON by default**. It preserves OSM golf/cart-path features plus a user-selectable **5–30 m buffer** and paints unrelated detailed terrain red. The default remains **5 m**, and the GUI clearly labels **5 m minimum / 30 m maximum**.

After the metric buffer is rasterized, Beta 3 applies two conservative internal cleanup rules:

- **2 px minimum red width** — suppresses one-pixel red hairs/slivers while retaining genuine two-pixel-wide structures;
- **25-pixel enclosed-island minimum** — enclosed red connected regions smaller than 25 raster pixels are removed.

The large border-connected exterior red region is never removed by the 25-pixel island rule. One mask pixel corresponds to the current processing Map Scale, and `mask.png` remains manually editable if the user wants more or less masking than the automatic cleanup provides.

Beta 3 reconstructs OSM `type=multipolygon` relations before rasterization:

- fragmented **outer** member ways are stitched into rings;
- **inner** rings are subtracted from their owning outer area;
- independently tagged inner golf features remain eligible for preservation;
- multipolygon water is kept and painted pure blue;
- open/incomplete relation fragments are not silently fill-closed into false polygons.

The preview also fills compound fairways bright green and compound rough darker green so `mask.png` shows the relation area being retained.

Mask semantics remain simple:

- **red** = remove from detailed terrain;
- **blue** = water/preserve behavior;
- other colors = preview only / non-red terrain.

---

## Optimize OSM Spline Points

**Optimize OSM Spline Points** is enabled by default for imported OSM geometry.

The optimizer runs before normal TGC spline-handle generation and conservatively removes redundant OSM vertices from supported features:

- bunkers;
- greens;
- tee boxes;
- fairways;
- rough / heavy rough;
- cart paths;
- walking paths.

The simplifier is feature-aware. It uses tighter tolerances on greens, bunkers, and tee boxes and larger tolerances on broad fairway/rough geometry. Safety guards preserve open-path endpoints, sharp corners, polygon winding, minimum point counts, and polygon area within a conservative limit.

Special lollipop/neck geometry used for bunker/fairway inner-island handling is protected from optimization after that geometry is created.

The goal is to reduce spline point count and course object usage without visibly changing the imported OSM shape.

---

## 50 m LiDAR Tree / Building Filters

Beta 3 includes two course-proximity filters, both enabled by default when their corresponding LiDAR feature type is used:

- **Filter LiDAR Trees: within 50 m of Course Features**
- **Filter LiDAR Buildings: within 50 m of Course Features**

The 50 m reference index is built only from core course geometry:

- bunkers;
- greens / tee boxes;
- fairways;
- rough;
- hole centerline routes.

Walking paths, cart paths, building placeholders, and other utility splines are deliberately excluded from the reference index so remote LiDAR objects cannot validate themselves against unrelated geometry.

LiDAR tree candidates farther than 50 m from the indexed course geometry are discarded. LiDAR Class-6 building footprints use the same 50 m course-proximity rule before being added to the course.

These filters reduce object count and prevent distant trees/buildings from consuming the PGA TOUR 2K25 course meter.

---

## Terrain generation and background terrain

The main TGCTool now supports **Dense / Original only** for terrain creation. **Adaptive terrain generation has been removed from the main tool and from its GUI.** Terrain brush and absolute brush footprint remain user selectable.

Common brush IDs exposed by this fork:

| Brush | Practical use |
|---:|---|
| 72 | raw / minimal smoothing |
| 15 | light smoothing |
| 9 | medium smoothing |
| 10 | soft / broad smoothing |

### Add Background Terrain / Remove Cliffs

When the low-resolution background fill is enabled, TGCTool samples the same source elevation data at the requested **Background Scale** and writes those coarse **Brush 10** stamps **before** the regular dense terrain stamps.

Because Brush 10 is a very soft circular brush, its footprint is written at **2.5 × the Background Scale** to overlap/fill the coarse lattice smoothly. For example, a 16 m Background Scale uses a 40 m Brush-10 footprint. The normal selected terrain brush is then written afterward at the detailed source lattice, so the high-resolution terrain sits on top of the coarse fill where they overlap.

### Auto Background Landscape (Purple)

The separate purple `terrainHeight` background can create a coarse source-derived surrounding landscape outside the detailed imported area instead of relying on one flat global elevation. Its detail spacing is user editable (48 m default in the current GUI).

Adaptive terrain is intentionally handled by the separate **Adaptive Terrain Converter** after course generation. This keeps the main LiDAR/DEM import path focused on producing the validated Dense / Original source course.

---

## DEM Fast

Beta 3 keeps the deterministic **40th-percentile lower-ground-biased DEM reducer** but accelerates non-integer reduction ratios with a vectorized/chunked implementation.

Heavy DEM work runs off the Tk main thread. Rasterio/GDAL reprojection defaults to up to eight logical CPU threads (`TGC_DEM_THREADS` can override this).

GeoTIFF processing retains:

- multi-tile mosaics;
- CRS/EPSG detection;
- horizontal reprojection when required;
- independent vertical-unit conversion;
- NoData-safe processing;
- Map Scale controlled reduction without inventing finer-than-source resolution.

---

## LiDAR Fast

Beta 3 accelerates the current LiDAR workflow while preserving its output behavior:

- single-pass crop/classification masks;
- one-time multi-tile concatenation;
- vectorized PyProj CRS transforms;
- vectorized tree-max and preview rasters;
- vectorized interpolation-array preparation;
- optional native-C exact-order ground rasterizer;
- worker-thread preparation/heightmap generation.

If the native helper cannot be compiled or bundled, the program automatically uses the exact Python fallback.

---

## Windows build

Use:

```bat
BUILD_TGC_2K25_BETA3.bat
```

Expected output:

```text
C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta3.exe
```

Release package:

```text
TGC-Designer-Tools-2K25-v0.5.0-2k25-beta3-Windows-x64.zip
```

See **[BUILD_WINDOWS.md](BUILD_WINDOWS.md)** for environment details.

Release notes: **[RELEASE_NOTES_v0.5.0-2k25-beta3.md](RELEASE_NOTES_v0.5.0-2k25-beta3.md)**
Full change history: **[CHANGELOG.md](CHANGELOG.md)**

---

## Scope and downstream tools

The main TGCTool repository release is intentionally focused on **course creation**. It does not fold in the separate Course Finisher or Adaptive Terrain Converter workflows.

- **Adaptive Terrain Converter** — optional downstream conversion after Dense / Original course creation.
- **Course Finisher** — separate downstream cart-path/native-water finishing workflow.

Keeping these operations separate makes the core LiDAR/DEM/OSM generation path easier to validate and avoids coupling post-processing experiments to the main importer.

---

## Credits and license

This is a derivative fork of the original **TGC Designer Tools** project and **HiCamino/TGC-Designer-Tools**. Fork-specific 2K25 work is maintained by **malifica**.

The project also relies on OpenStreetMap, GDAL/PROJ, Rasterio, laspy, NumPy, OpenCV, SciPy, and Python ecosystems.

Apache License 2.0. See **[LICENSE](LICENSE)**.

This software is unofficial and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, OpenStreetMap Foundation, USGS, or other referenced organizations.
