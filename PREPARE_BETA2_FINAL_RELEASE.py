#!/usr/bin/env python3
from pathlib import Path
import py_compile
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parent
VERSION = "v0.5.0-2k25-beta2"
EXE = "tgc_gui_2k25_beta2.exe"

GUI = ROOT / "tgc_gui.py"
ENGINE = ROOT / "tgc_image_terrain.py"

def backup_once(path):
    if not path.exists():
        return
    b = path.with_name(path.name + ".pre_beta2_final_release.bak")
    if not b.exists():
        shutil.copy2(path, b)
        print("Backup:", b.name)

def read(path):
    return path.read_text(encoding="utf-8-sig")

print("=== PREPARE FINAL BETA 2 RELEASE ===")
print()

for required in (GUI, ENGINE):
    if not required.exists():
        raise SystemExit("ERROR: missing " + required.name)

gui = read(GUI)
engine = read(ENGINE)

# The final Beta 2 source must NOT contain the removed carve feature.
forbidden = {
    "tgc_gui.py": [
        "carve_blue_banks",
        "carveBlueBanksCheck",
        "Gradual Blue-Mask Water Carve",
        "Water Bank Carve Brush",
        "Water Carve Brush (round)",
    ],
    "tgc_image_terrain.py": [
        "generate_blue_mask_bank_carve",
        "carve_blue_banks",
        "carve_blue_water",
        "shoreline_brush_type",
        "bank_brush_type",
    ],
}

bad = []
for term in forbidden["tgc_gui.py"]:
    if term in gui:
        bad.append("tgc_gui.py: " + term)
for term in forbidden["tgc_image_terrain.py"]:
    if term in engine:
        bad.append("tgc_image_terrain.py: " + term)

if bad:
    print("ERROR: removed water-carve feature is still present:")
    for item in bad:
        print("  " + item)
    print()
    print("Release preparation stopped.")
    sys.exit(1)

# The established legacy blue-mask controls must still exist.
if 'options_entries_dict["purge_water"]' not in gui:
    raise SystemExit("ERROR: Remove All Terrain Under Blue Mask option is missing.")
if 'options_entries_dict["fill_water"]' not in gui:
    raise SystemExit("ERROR: Fill Holes Under Blue Mask option is missing.")
if "purge_water" not in engine:
    raise SystemExit("ERROR: purge_water processing is missing from terrain engine.")

# Update version.
backup_once(GUI)
new_gui, n = re.subn(
    r'TGC_GUI_VERSION\s*=\s*"[^"]+"',
    f'TGC_GUI_VERSION = "{VERSION}"',
    gui,
    count=1,
)
if n != 1:
    raise SystemExit("ERROR: could not update TGC_GUI_VERSION.")
compile(new_gui, str(GUI), "exec")
GUI.write_text(new_gui, encoding="utf-8", newline="\n")
print("Version set:", VERSION)

# Release notes.
notes = ROOT / "RELEASE_NOTES_v0.5.0-2k25-beta2.md"
notes.write_text("# TGC Designer Tools 2K25 — v0.5.0-2k25-beta2\n\nSecond public beta of the **malifica** fork of HiCamino's TGC Designer Tools for PGA TOUR 2K25.\n\nBeta 2 keeps the Local OSM / LiDAR / GeoTIFF DEM foundation from beta 1 and adds the terrain, CRS, OSM, and workflow improvements validated during real-course testing.\n\n## Beta 2 highlights\n\n- **Adaptive - Aggressive** terrain generation integrated into the normal terrain workflow.\n- Experimental adaptive profiles removed from the public GUI; the supported terrain-generation choices are **Dense / Original** and **Adaptive - Aggressive**.\n- **Auto Background Landscape (Purple)** generates coarse surrounding `terrainHeight` from the source LiDAR/DEM rather than leaving a flat outer landscape.\n- User-editable **Purple Background Detail Spacing (m)** controls the tradeoff between surrounding-terrain fidelity and the course Objects meter.\n- Purple background defaults to **48 m** detail spacing; lower values such as **24 m** are supported for mountainous sites.\n- Modern LAS/LAZ CRS parsing through `laspy.header.parse_crs()`.\n- Compound LiDAR CRS handling with separate horizontal and vertical components.\n- Independent LiDAR XY and Z unit conversion.\n- Improved reporting for horizontal EPSG, vertical EPSG, and source units.\n- Automatic conversion of OSM bunker multipolygons containing `golf=rough` inner islands into a 2K25-compatible bunker hole/lollipop geometry.\n- Inner rough member ways consumed during bunker conversion so no redundant rough spline is written.\n- Beta 1 Local OSM, DEM, water-mask, tree, brush, and Windows-packaging improvements retained.\n\n## Water behavior in Beta 2\n\nBeta 2 retains the established blue-mask workflow:\n\n- `Fill Holes Under Blue Mask`\n- `Remove All Terrain Under Blue Mask`\n- pure-blue water mask output\n- `natural=water`\n- `waterway=*`\n- open-waterway polyline handling\n- normal OSM/local-OSM water spline import\n\nThe experimental automatic **Carve Blue Mask Banks / deep-floor water-carve feature is intentionally not included in Beta 2**. Testing showed that automatically sculpting the shoreline was too dependent on the interaction between the source terrain, blue-mask edge, brush falloff, and the legacy terrain-removal system.\n\nThis release therefore leaves shoreline shaping to the established terrain/mask workflow instead of shipping an unreliable automatic carve.\n\n## Terrain generation\n\nThe supported Beta 2 terrain-generation choices are:\n\n```text\nDense / Original\nAdaptive - Aggressive\n```\n\nDense / Original is the maximum-fidelity path.\n\nAdaptive - Aggressive is intended for users who need substantial terrain-operation savings and accept a softer terrain representation in exchange for lower Objects-meter use.\n\n## Auto Background Landscape\n\nWhen enabled, the outer purple `terrainHeight` follows broad source relief instead of creating one flat background.\n\nDefault:\n\n```text\nPurple Background Detail Spacing: 48 m\nBrush: 10\nBrush footprint: 2.0 × detail spacing\nSmoothing: 0.35 × detail spacing\n```\n\nExamples:\n\n```text\n48 m spacing -> 96 m Brush 10\n32 m spacing -> 64 m Brush 10\n24 m spacing -> 48 m Brush 10\n```\n\nThe spacing remains user-editable so the designer decides where to spend the Objects meter.\n\n## LiDAR CRS / EPSG improvements\n\nThe LiDAR loader now prefers modern LAS/LAZ CRS parsing and can split compound CRS definitions into horizontal and vertical components.\n\nExample:\n\n```text\nHorizontal CRS: NAD83(2011) / Texas South Central (ftUS)\nHorizontal EPSG: 6588\nHorizontal unit: US survey foot\n\nVertical CRS: NAVD88 height (ftUS)\nVertical EPSG: 6360\nVertical unit: US survey foot\n```\n\nXY and Z conversions are handled independently.\n\nThe manual override remains:\n\n```text\nForce LiDAR Horizontal EPSG (blank = auto)\n```\n\nLeaving the field blank uses automatic detection.\n\n## OSM bunker inner-rough conversion\n\nBeta 2 supports modern OSM multipolygon geometry such as:\n\n```text\nrelation: golf=bunker\n  outer -> bunker boundary\n  inner -> golf=rough island\n```\n\nThe importer converts this into a 2K25-compatible bunker polygon with a very narrow neck so the inner rough area becomes a physical hole in the bunker fill.\n\nThe inner rough way is consumed and is not written again as a separate rough spline.\n\n## Existing beta 1 features retained\n\n- Local `.osm` / JOSM files in the normal LiDAR / DEM workflow.\n- Local OSM reuse during preview/mask creation and final feature import.\n- GeoTIFF DEM support and multi-tile mosaicing.\n- Automatic DEM CRS handling.\n- Independent DEM vertical-unit conversion.\n- Map Scale controlled DEM reduction.\n- 40th-percentile lower-ground-biased DEM reducer.\n- Pure-blue final water mask.\n- `natural=water` and `waterway=*` recognition.\n- Open-waterway polyline rendering.\n- 2K25 LiDAR tree fixes.\n- Terrain Brush / Brush Size controls.\n- Larger screen-aware GUI.\n- Rasterio/GDAL/PROJ PyInstaller support.\n\n## Build target\n\n```text\nWindows 10/11 64-bit\nPython 3.11.x 64-bit\nPyInstaller 6.x\nRasterio 1.4.4\n```\n\nRelease executable:\n\n```text\ntgc_gui_2k25_beta2.exe\n```\n\nRelease archive:\n\n```text\nTGC-Designer-Tools-2K25-v0.5.0-2k25-beta2-Windows-x64.zip\n```\n\n## Upstream\n\nBased on:\n\n```text\nHiCamino/TGC-Designer-Tools\nupstream baseline: 4adb37fac73ab013da4ac6b86b02bb9579e19170\n```\n\n## License\n\nApache License 2.0. Existing upstream credits and licensing are preserved.\n\nThis is an unofficial community modification and is not affiliated with or endorsed by HB Studios, 2K, PGA TOUR, OpenStreetMap Foundation, USGS, or other referenced organizations.\n", encoding="utf-8", newline="\n")
print("Wrote:", notes.name)

# Changelog.
changelog = ROOT / "CHANGELOG.md"
if changelog.exists():
    backup_once(changelog)
    c = read(changelog)

    # Replace an earlier draft Beta2 section if present, otherwise insert it.
    c = re.sub(
        r'## \[0\.5\.0-2k25-beta2\][\s\S]*?(?=\n## \[0\.5\.0-2k25-beta1\])',
        '',
        c,
        count=1,
    )

    anchor = "## [0.5.0-2k25-beta1]"
    if anchor not in c:
        raise SystemExit("ERROR: beta1 changelog anchor not found.")

    c = c.replace(anchor, '## [0.5.0-2k25-beta2] - Terrain, CRS, OSM, and workflow beta\n\n### Added\n\n- Integrated `Adaptive - Aggressive` terrain generation mode.\n- Automatic purple `terrainHeight` background landscape generated from source LiDAR/DEM relief.\n- User-editable Purple Background Detail Spacing control.\n- Modern LAS/LAZ CRS parsing through `laspy.header.parse_crs()`.\n- Compound LiDAR CRS splitting into horizontal and vertical components.\n- Independent LiDAR XY and Z unit conversion.\n- OSM bunker multipolygon conversion for `golf=bunker` outer + `golf=rough` inner islands.\n- Narrow lollipop/neck generation so inner rough islands become physical holes in the 2K25 bunker fill.\n\n### Changed\n\n- Public Terrain Generation choices simplified to:\n  - Dense / Original\n  - Adaptive - Aggressive\n- Purple background default detail spacing set to 48 m.\n- Purple background Brush-10 footprint uses `2.0 × spacing`.\n- Purple background smoothing uses `0.35 × spacing`.\n- Purple Background spacing remains editable; values such as 24 m are supported for higher-detail mountainous surroundings.\n- LiDAR force-EPSG label changed to `Force LiDAR Horizontal EPSG (blank = auto)`.\n- Bunker inner rough member ways are consumed during lollipop conversion; no redundant rough spline is written.\n\n### Fixed\n\n- Older LiDAR CRS detection could lose a successfully parsed CRS when a later unrelated VLR raised an exception.\n- Compound LAS/LAZ CRS metadata could be reported as one unresolved CRS instead of separate horizontal/vertical components.\n- LiDAR Z values could be forced through the same unit assumptions as XY.\n- A flat global background landscape was unsuitable for courses with large elevation changes.\n- Coarse background stamps could bridge over significant terrain changes on rolling/mountainous sites.\n- 2K25 could not display a rough island over a filled bunker spline.\n\n### Removed / Deferred\n\n- Experimental automatic `Carve Blue Mask Banks` / deep-floor water sculpting is not included in Beta 2.\n- Experimental Adaptive Standard, Hybrid, Brush-72-only, and Auto-Mask terrain profiles are not exposed in the Beta 2 GUI.\n\n### Water\n\nBeta 2 retains:\n\n- Fill Holes Under Blue Mask\n- Remove All Terrain Under Blue Mask\n- pure-blue final water mask\n- OSM/local-OSM water spline import\n- `natural=water`\n- `waterway=*`\n- open-waterway polyline handling\n\n### Build\n\n- Windows target: Python 3.11.x 64-bit.\n- PyInstaller 6.x.\n- Rasterio 1.4.4.\n- `laszip-cli.exe` bundled for LAZ support.\n- Release executable: `dist\\tgc_gui_2k25_beta2.exe`.\n' + "\n\n" + anchor, 1)
    changelog.write_text(c, encoding="utf-8", newline="\n")
    print("Updated:", changelog.name)

# README release/build references.
readme = ROOT / "README.md"
if readme.exists():
    backup_once(readme)
    r = read(readme)

    r = r.replace("tgc_gui_2k25_LOCAL_OSM_DEM.exe", EXE)
    r = r.replace("tgc_gui_2k25_beta1.exe", EXE)

    beta2_status = """## Release status

**v0.5.0-2k25-beta2** is the current fork release.

Beta 2 adds Adaptive - Aggressive terrain generation, automatic purple background landscape generation with user-controlled detail spacing, modern compound LiDAR CRS handling, and 2K25-compatible OSM bunker inner-island conversion.

The experimental automatic **Carve Blue Mask Banks** feature is intentionally not part of Beta 2. The established `Fill Holes Under Blue Mask` and `Remove All Terrain Under Blue Mask` controls remain available.

See **[CHANGELOG.md](CHANGELOG.md)** and **[RELEASE_NOTES_v0.5.0-2k25-beta2.md](RELEASE_NOTES_v0.5.0-2k25-beta2.md)** for details."""

    if "## Release status" in r:
        r = re.sub(
            r'## Release status\n[\s\S]*?(?=\n---\n\n## Credits)',
            beta2_status,
            r,
            count=1,
        )

    readme.write_text(r, encoding="utf-8", newline="\n")
    print("Updated:", readme.name)

# Build guide release names.
build_doc = ROOT / "BUILD_WINDOWS.md"
if build_doc.exists():
    backup_once(build_doc)
    b = read(build_doc)
    b = b.replace("tgc_gui_2k25_LOCAL_OSM_DEM.exe", EXE)
    b = b.replace("TGC-Designer-Tools-2K25-v0.5.0-beta1-Windows-x64", 
                  "TGC-Designer-Tools-2K25-v0.5.0-2k25-beta2-Windows-x64")
    b = b.replace("v0.5.0-beta1", "v0.5.0-2k25-beta2")
    build_doc.write_text(b, encoding="utf-8", newline="\n")
    print("Updated:", build_doc.name)

# Final syntax validation.
print()
print("=== Syntax validation ===")
core = [
    "dem_map_api.py",
    "tgc_gui.py",
    "lidar_map_api.py",
    "tgc_image_terrain.py",
    "OSMTGC.py",
    "infill_image.py",
    "usgs_lidar_parser.py",
]
if (ROOT / "adaptive_terrain.py").exists():
    core.append("adaptive_terrain.py")

for name in core:
    p = ROOT / name
    if not p.exists():
        raise SystemExit("ERROR: required source file missing: " + name)
    py_compile.compile(str(p), doraise=True)
    print("Syntax OK:", name)

print()
print("FINAL BETA 2 RELEASE PREPARATION COMPLETE")
