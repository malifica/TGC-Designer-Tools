from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parent


def read(name):
    p = ROOT / name
    if not p.exists():
        raise SystemExit(f"ERROR: required Beta 3 file is missing: {name}")
    return p.read_text(encoding="utf-8")


sources = {
    "tgc_gui.py": read("tgc_gui.py"),
    "auto_red_mask.py": read("auto_red_mask.py"),
    "osm_alignment_viewer.py": read("osm_alignment_viewer.py"),
    "tgc_image_terrain.py": read("tgc_image_terrain.py"),
    "lidar_feature_filter.py": read("lidar_feature_filter.py"),
    "OSMTGC.py": read("OSMTGC.py"),
    "README.md": read("README.md"),
    "RELEASE_NOTES_v0.5.0-2k25-beta3.md": read("RELEASE_NOTES_v0.5.0-2k25-beta3.md"),
}

checks = [
    ("GUI version", "tgc_gui.py", 'TGC_GUI_VERSION = "v0.5.0-2k25-beta3"'),
    ("Visible app title", "tgc_gui.py", 'TGC_APP_TITLE = "TGC Designer Tools 2K25 - Beta 3"'),
    ("Title assignment", "tgc_gui.py", 'root.title(TGC_APP_TITLE)'),
    ("Dense-only main tool", "tgc_gui.py", 'Terrain Generation: Dense / Original only'),
    ("Auto-mask minimum 5 m", "tgc_gui.py", 'AUTO_RED_MASK_BUFFER_MIN_M = 5.0'),
    ("Auto-mask maximum 30 m", "tgc_gui.py", 'AUTO_RED_MASK_BUFFER_MAX_M = 30.0'),
    ("Auto-mask default 5 m", "tgc_gui.py", 'AUTO_RED_MASK_BUFFER_DEFAULT_M = 5.0'),
    ("Auto-mask range label", "tgc_gui.py", 'text="Minimum 5 m / Maximum 30 m"'),
    ("Auto-mask 2 px cleanup", "auto_red_mask.py", '_AUTO_RED_MASK_MIN_RED_WIDTH_PX = 2'),
    ("Auto-mask 25 px island cleanup", "auto_red_mask.py", '_AUTO_RED_MASK_MIN_INTERNAL_RED_AREA_PX = 25'),
    ("CFS hillshade relief exaggeration", "osm_alignment_viewer.py", 'relief_exaggeration = 2.0'),
    ("CFS hillshade lower sun", "osm_alignment_viewer.py", 'alt = math.radians(35.0)'),
    ("CFS hillshade low percentile", "osm_alignment_viewer.py", 'np.percentile(finite_shade, 2.0)'),
    ("CFS hillshade high percentile", "osm_alignment_viewer.py", 'np.percentile(finite_shade, 98.0)'),
    ("CFS overlay constant 2 px", "osm_alignment_viewer.py", 'width = 2'),
    ("CFS overlay gray75", "osm_alignment_viewer.py", '"stipple": "gray75"'),
    ("Background Brush 10 footprint 2.5x", "tgc_image_terrain.py", '2.5*background_scale, brush_type=10'),
    ("50 m LiDAR filter distance", "lidar_feature_filter.py", 'DEFAULT_FILTER_DISTANCE_M = 50.0'),
    ("OSM optimizer default enabled", "OSMTGC.py", "options_dict.get('optimize_osm_spline_points', True)"),
    ("README 5-30 m mask", "README.md", '**5–30 m**'),
    ("README 2 px cleanup", "README.md", '**2 px minimum red width**'),
    ("README 25 px cleanup", "README.md", '**25-pixel enclosed-island minimum**'),
    ("README CFS viewer", "README.md", '## CFS georeference lock and Alignment Viewer'),
    ("README 2.5x background", "README.md", '**2.5 × the Background Scale**'),
    ("README adaptive split", "README.md", '**Adaptive terrain removed from the main TGCTool and GUI**'),
    ("README Course Finisher split", "README.md", '**Course Finisher remains a separate downstream tool**'),
]

forbidden = [
    ("Old fixed auto-mask GUI call", "tgc_gui.py", "auto_red_mask_buffer_m=5.0,"),
    ("Old fixed auto-mask label", "tgc_gui.py", "Auto Red Mask (+5 m around golf/cart features)"),
    ("Old adaptive GUI option", "tgc_gui.py", 'values=("Dense / Original", "Adaptive - Aggressive")'),
]

failed = []
print("TGC Designer Tools 2K25 Beta 3 FINAL source verification")
print("Folder:", ROOT)
print()

for label, filename, needle in checks:
    ok = needle in sources[filename]
    print(("PASS" if ok else "FAIL"), "-", label)
    if not ok:
        failed.append(label)

for label, filename, needle in forbidden:
    ok = needle not in sources[filename]
    print(("PASS" if ok else "FAIL"), "-", label)
    if not ok:
        failed.append(label)

compile_files = [
    "tgc_gui.py",
    "auto_red_mask.py",
    "cfs_georef.py",
    "dem_map_api.py",
    "infill_image.py",
    "lidar_fast_native.py",
    "lidar_feature_filter.py",
    "lidar_map_api.py",
    "osm_alignment_viewer.py",
    "OSMTGC.py",
    "tgc_image_terrain.py",
    "usgs_lidar_parser.py",
]

print()
print("Python syntax check:")
for name in compile_files:
    try:
        py_compile.compile(str(ROOT / name), doraise=True)
        print("PASS -", name)
    except Exception as exc:
        print("FAIL -", name, "-", exc)
        failed.append("py_compile " + name)

required_files = [
    "BUILD_TGC_2K25_BETA3.bat",
    "RELEASE_NOTES_v0.5.0-2k25-beta3.md",
    "auto_red_mask.py",
    "cfs_georef.py",
    "lidar_fast_native.c",
    "lidar_fast_native.py",
    "lidar_feature_filter.py",
    "osm_alignment_viewer.py",
]

print()
print("Required Beta 3 release files:")
for name in required_files:
    ok = (ROOT / name).exists()
    print(("PASS" if ok else "FAIL"), "-", name)
    if not ok:
        failed.append("missing " + name)

if failed:
    print()
    print("FINAL VERIFICATION FAILED")
    for item in failed:
        print(" -", item)
    sys.exit(1)

print()
print("FINAL VERIFICATION PASSED")
print("Visible application title: TGC Designer Tools 2K25 - Beta 3")
print(r"Expected executable: C:\TGC-Designer-Tools\dist\tgc_gui_2k25_beta3.exe")
