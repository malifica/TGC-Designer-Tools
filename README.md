# TGC Designer Tools — 2K25 Local OSM / LiDAR / DEM Fork

This repository is an unofficial fork of **HiCamino/TGC-Designer-Tools**, with additional work focused on **PGA TOUR 2K25**, local OpenStreetMap workflows, LiDAR processing, GeoTIFF DEM support, terrain brush control, water-mask handling, and Windows packaging.

Upstream project: https://github.com/HiCamino/TGC-Designer-Tools  
Fork maintainer: **malifica**  
Upstream baseline used for this work: `4adb37fac73ab013da4ac6b86b02bb9579e19170`

This project remains under the upstream **Apache License 2.0**. Existing upstream credits and licensing are preserved.

> **Important:** If you are using a local `.osm` / JOSM export, select the **Local OSM File before processing LiDAR or DEM data**. The selected local OSM is used during mask/preview generation as well as the later course-feature import.

---

## What this fork adds

### Local OSM in the normal LiDAR / DEM workflow

The normal terrain workflow now includes:

**Local OSM File (blank = online)**

When a local OSM file is selected:

- the `.osm` XML is parsed locally;
- the same local data is used for terrain preview / mask generation;
- the same local data is used again when importing OSM course features;
- the existing LiDAR/DEM georeferencing is used for alignment;
- missing referenced nodes are **not** silently fetched online;
- the local OSM export should therefore be complete.

When the Local OSM field is blank, the original online Overpass behavior remains available.

The older separate **Make Flat Course From OSM File** function is left intact.

---

## Correct order of operation

For a local OSM workflow, use this sequence:

1. Select/import the target `.course`.
2. **Select the Local OSM file.**
3. Choose the desired **Map Scale**.
4. Process **LiDAR or DEM**.
5. Crop/select the course boundaries.
6. Inspect or edit `mask.png` if desired.
7. Choose **Terrain Brush** and **Brush Size**.
8. Run **Import Terrain and Features**.
9. Export the finished `.course`.

Selecting Local OSM **before** LiDAR/DEM processing is important because the processing stage now uses that OSM file to create the preview/mask. This keeps water, golf features, and the later OSM import aligned to the same source data.

---

## GeoTIFF DEM support

The fork adds a parallel DEM workflow that feeds the existing terrain/course pipeline.

Supported behavior includes:

- one or multiple georeferenced `.tif` / `.tiff` DEM tiles;
- automatic mosaic creation;
- course-area crop selection;
- automatic CRS / EPSG reading from the GeoTIFF;
- compound CRS / GeoTIFF metadata handling;
- automatic horizontal reprojection when required;
- automatic native DEM pixel-spacing detection;
- Map Scale controlled terrain sampling;
- NoData-safe processing;
- output through the same `heightmap.npy` / `mask.png` path used by LiDAR.

Selected DEM tiles currently need to use compatible source CRS information.

### Automatic EPSG detection

DEM users do not need to type an EPSG code manually.

The program reads the embedded CRS and logs the detected EPSG when one is available. For compound CRS definitions it also attempts to identify the horizontal component.

Example:

```text
DEM source EPSG automatically detected: 6588
```

If an EPSG number is not explicitly available, the embedded CRS definition is still used.

### Vertical units are handled separately

A GeoTIFF's horizontal coordinate units do not necessarily match its elevation units. This fork checks the DEM's vertical unit and normalizes elevation values to meters before terrain generation.

Supported vertical units:

| Source elevation unit | Conversion |
|---|---:|
| meters | `× 1.0` |
| US survey feet | `× (1200 / 3937)` |
| international feet | `× 0.3048` |

This fixes severe vertical exaggeration when a DEM stores NAVD88 heights in US survey feet but those values would otherwise be interpreted as meters.

---

## DEM Map Scale behavior

The **Map Scale** field controls the final terrain sample spacing.

The tool will reduce denser source data to the selected spacing, but it will not invent terrain resolution finer than the source DEM.

Examples:

| Native DEM | Selected Map Scale | Result |
|---:|---:|---|
| 0.5 m | 1 m | 2×2 source cells per terrain sample |
| 0.5 m | 2 m | 4×4 source cells |
| 0.5 m | 3 m | 6×6 source cells |
| 0.5 m | 4 m | 8×8 source cells |
| 0.5 m | 6 m | 12×12 source cells |
| 1 m | 1 m | native resolution |
| 1 m | 2 m | 2×2 source cells |
| 2 m | 4 m | 2×2 source cells |
| 2 m | requested 1 m | remains at 2 m native resolution |

For common integer scale ratios, the reducer uses exact source-cell blocks. Arbitrary larger target scales are also supported.

### LiDAR-style DEM reduction

Rather than relying on generic image interpolation for the final Map Scale reduction, dense DEM cells are combined with a deterministic **lower-ground-biased reducer**.

The current implementation uses the **40th percentile** of valid source elevations within each output terrain cell. This follows the intent of the existing LiDAR ground reduction, which tends toward the lower ground envelope, while avoiding the point-order dependence of the original LiDAR running filter.

---

## Terrain brush controls

The old smoothing choices were replaced with separate **Brush** and **Brush Size** controls.

### Brush IDs

This fork exposes these terrain brush IDs:

| Brush | Practical description in this fork |
|---:|---|
| **72** | Raw / minimal smoothing; preserves the most local detail |
| **15** | Light smoothing |
| **9** | Medium smoothing |
| **10** | Heavy / soft smoothing; broader terrain blending |

These descriptions are practical legacy-equivalent labels for the exposed TGC brush IDs rather than official HB Studios names.

### Brush Size

Available absolute brush footprints:

- 1 m
- 2 m
- 3 m
- 4 m
- 6 m

Brush Size is an **absolute size in meters**, not a multiplier.

Example:

```text
Map Scale: 2 m
Brush: 10
Brush Size: 4 m
```

means terrain sample centers are spaced every **2 meters**, while each terrain operation uses a **4 meter Brush 10** footprint.

Brush sizes smaller than the source/sample spacing are disabled.

---

## Water-mask improvements

OSM preview and mask generation now recognizes:

- `golf=water_hazard`
- `golf=lateral_water_hazard`
- `natural=water`
- `waterway=*`

Water is repainted in a final pass as pure blue:

```text
RGB 0, 0, 255
```

This makes water easy to identify and allows **Remove All Terrain Under Blue Mask** to work with locally supplied OSM data.

Open `waterway=*` features are drawn as **polylines**, not filled polygons. This fixes the large triangular blue wedges that occurred when an open waterway was incorrectly closed and passed through polygon filling.

Area water remains filled normally.

---

## 2K25 LiDAR tree fixes

The LiDAR tree pipeline has been updated for newer 2K25 course structures, including:

- `placedObjects4` compatible output;
- corrected object payload handling;
- theme-specific tree selection when Tree Variety is disabled;
- additional tree bounds checks;
- improved diagnostics.

---

## LiDAR / Python compatibility

The working Windows development environment for this fork uses:

- Python 3.11.x, 64-bit;
- modern `laspy` 2.x API (`laspy.open(...)`);
- PyInstaller 6.x;
- Rasterio 1.4.4 for DEM/GeoTIFF support;
- bundled `laszip-cli.exe` for LAZ support.

The original source had dependency history from older `laspy` versions. This fork uses the modern loader path required by the current code.

---

## 2K25 compatibility

This fork retains HiCamino's newer 2K25 support and adds fixes around the modified workflow, including use of newer course structures such as:

- `surfaceBrushes2`;
- newer surface/hole structures;
- current object groups;
- `placedObjects4` for LiDAR-generated trees.

---

## GUI changes

The application now opens in a larger, screen-aware window rather than the older fixed `800×600` size.

The target is approximately **1400×900** when the display permits, with automatic reduction on smaller screens. This keeps the LiDAR, DEM, OSM, and terrain controls visible without immediately resizing the window.

---

## Windows build

See **[BUILD_WINDOWS.md](BUILD_WINDOWS.md)** for the complete build process.

The current packaged executable name is:

```text
tgc_gui_2k25_beta2.exe
```

---

## Release status

**v0.5.0-2k25-beta2** is the current fork release.

Beta 2 adds Adaptive - Aggressive terrain generation, automatic purple background landscape generation with user-controlled detail spacing, modern compound LiDAR CRS handling, and 2K25-compatible OSM bunker inner-island conversion.

The experimental automatic **Carve Blue Mask Banks** feature is intentionally not part of Beta 2. The established `Fill Holes Under Blue Mask` and `Remove All Terrain Under Blue Mask` controls remain available.

See **[CHANGELOG.md](CHANGELOG.md)** and **[RELEASE_NOTES_v0.5.0-2k25-beta2.md](RELEASE_NOTES_v0.5.0-2k25-beta2.md)** for details.
---

## Credits

This is a derivative fork, not a replacement for the work that came before it.

Primary upstream lineage includes:

- the original **TGC Designer Tools** project and its contributors;
- **HiCamino/TGC-Designer-Tools** and its 2K25 work;
- the OpenStreetMap, GDAL/PROJ, Rasterio, laspy, LAZ, NumPy, OpenCV, and Python ecosystems used by the tool.

Fork-specific 2K25 Local OSM / DEM modifications are maintained by **malifica**.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).

This software is unofficial and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, OpenStreetMap Foundation, USGS, or other referenced organizations.
