# TGC Designer Tools 2K25 — v0.5.0-2k25-beta2

Second public beta of the **malifica** fork of HiCamino's TGC Designer Tools for PGA TOUR 2K25.

Beta 2 keeps the Local OSM / LiDAR / GeoTIFF DEM foundation from beta 1 and adds the terrain, CRS, OSM, and workflow improvements validated during real-course testing.

## Beta 2 highlights

- **Adaptive - Aggressive** terrain generation integrated into the normal terrain workflow.
- Experimental adaptive profiles removed from the public GUI; the supported terrain-generation choices are **Dense / Original** and **Adaptive - Aggressive**.
- **Auto Background Landscape (Purple)** generates coarse surrounding `terrainHeight` from the source LiDAR/DEM rather than leaving a flat outer landscape.
- User-editable **Purple Background Detail Spacing (m)** controls the tradeoff between surrounding-terrain fidelity and the course Objects meter.
- Purple background defaults to **48 m** detail spacing; lower values such as **24 m** are supported for mountainous sites.
- Modern LAS/LAZ CRS parsing through `laspy.header.parse_crs()`.
- Compound LiDAR CRS handling with separate horizontal and vertical components.
- Independent LiDAR XY and Z unit conversion.
- Improved reporting for horizontal EPSG, vertical EPSG, and source units.
- Automatic conversion of OSM bunker multipolygons containing `golf=rough` inner islands into a 2K25-compatible bunker hole/lollipop geometry.
- Inner rough member ways consumed during bunker conversion so no redundant rough spline is written.
- Beta 1 Local OSM, DEM, water-mask, tree, brush, and Windows-packaging improvements retained.

## Water behavior in Beta 2

Beta 2 retains the established blue-mask workflow:

- `Fill Holes Under Blue Mask`
- `Remove All Terrain Under Blue Mask`
- pure-blue water mask output
- `natural=water`
- `waterway=*`
- open-waterway polyline handling
- normal OSM/local-OSM water spline import

The experimental automatic **Carve Blue Mask Banks / deep-floor water-carve feature is intentionally not included in Beta 2**. Testing showed that automatically sculpting the shoreline was too dependent on the interaction between the source terrain, blue-mask edge, brush falloff, and the legacy terrain-removal system.

This release therefore leaves shoreline shaping to the established terrain/mask workflow instead of shipping an unreliable automatic carve.

## Terrain generation

The supported Beta 2 terrain-generation choices are:

```text
Dense / Original
Adaptive - Aggressive
```

Dense / Original is the maximum-fidelity path.

Adaptive - Aggressive is intended for users who need substantial terrain-operation savings and accept a softer terrain representation in exchange for lower Objects-meter use.

## Auto Background Landscape

When enabled, the outer purple `terrainHeight` follows broad source relief instead of creating one flat background.

Default:

```text
Purple Background Detail Spacing: 48 m
Brush: 10
Brush footprint: 2.0 × detail spacing
Smoothing: 0.35 × detail spacing
```

Examples:

```text
48 m spacing -> 96 m Brush 10
32 m spacing -> 64 m Brush 10
24 m spacing -> 48 m Brush 10
```

The spacing remains user-editable so the designer decides where to spend the Objects meter.

## LiDAR CRS / EPSG improvements

The LiDAR loader now prefers modern LAS/LAZ CRS parsing and can split compound CRS definitions into horizontal and vertical components.

Example:

```text
Horizontal CRS: NAD83(2011) / Texas South Central (ftUS)
Horizontal EPSG: 6588
Horizontal unit: US survey foot

Vertical CRS: NAVD88 height (ftUS)
Vertical EPSG: 6360
Vertical unit: US survey foot
```

XY and Z conversions are handled independently.

The manual override remains:

```text
Force LiDAR Horizontal EPSG (blank = auto)
```

Leaving the field blank uses automatic detection.

## OSM bunker inner-rough conversion

Beta 2 supports modern OSM multipolygon geometry such as:

```text
relation: golf=bunker
  outer -> bunker boundary
  inner -> golf=rough island
```

The importer converts this into a 2K25-compatible bunker polygon with a very narrow neck so the inner rough area becomes a physical hole in the bunker fill.

The inner rough way is consumed and is not written again as a separate rough spline.

## Existing beta 1 features retained

- Local `.osm` / JOSM files in the normal LiDAR / DEM workflow.
- Local OSM reuse during preview/mask creation and final feature import.
- GeoTIFF DEM support and multi-tile mosaicing.
- Automatic DEM CRS handling.
- Independent DEM vertical-unit conversion.
- Map Scale controlled DEM reduction.
- 40th-percentile lower-ground-biased DEM reducer.
- Pure-blue final water mask.
- `natural=water` and `waterway=*` recognition.
- Open-waterway polyline rendering.
- 2K25 LiDAR tree fixes.
- Terrain Brush / Brush Size controls.
- Larger screen-aware GUI.
- Rasterio/GDAL/PROJ PyInstaller support.

## Build target

```text
Windows 10/11 64-bit
Python 3.11.x 64-bit
PyInstaller 6.x
Rasterio 1.4.4
```

Release executable:

```text
tgc_gui_2k25_beta2.exe
```

Release archive:

```text
TGC-Designer-Tools-2K25-v0.5.0-2k25-beta2-Windows-x64.zip
```

## Upstream

Based on:

```text
HiCamino/TGC-Designer-Tools
upstream baseline: 4adb37fac73ab013da4ac6b86b02bb9579e19170
```

## License

Apache License 2.0. Existing upstream credits and licensing are preserved.

This is an unofficial community modification and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, OpenStreetMap Foundation, USGS, or other referenced organizations.
