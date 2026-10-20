from pathlib import Path
import importlib.util
import json
import py_compile

ROOT = Path(__file__).resolve().parent

def read(name):
    path = ROOT / name
    if not path.is_file():
        raise SystemExit("ERROR: required Beta 6 file is missing: " + name)
    return path.read_text(encoding="utf-8")

sources = {
    "tgc_gui.py": read("tgc_gui.py"),
    "tgc_tools.py": read("tgc_tools.py"),
    "tree_profile_manager.py": read("tree_profile_manager.py"),
    "tgc_image_terrain.py": read("tgc_image_terrain.py"),
    "OSMTGC.py": read("OSMTGC.py"),
    "auto_red_mask.py": read("auto_red_mask.py"),
    "usgs_ept_downloader.py": read("usgs_ept_downloader.py"),
    "lidar_map_api.py": read("lidar_map_api.py"),
    "osm_alignment_viewer.py": read("osm_alignment_viewer.py"),
    "osm_mask_alignment.py": read("osm_mask_alignment.py"),
    "osm_custom_layout.py": read("osm_custom_layout.py"),
    "VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py": read("VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py"),
    "VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py": read("VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py"),
    "VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py": read("VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py"),
    "VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py": read("VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py"),
    "VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py": read("VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py"),
    "BUILD_TGC_2K25_BETA6.bat": read("BUILD_TGC_2K25_BETA6.bat"),
}

scale_order = '''        tree_profile_manager.LEGACY_SCALE_MODE,
        tree_profile_manager.HEROIC_SCALE_MODE,
        tree_profile_manager.EPIC_SCALE_MODE,
        tree_profile_manager.MYTHIC_SCALE_MODE,
'''

checks = [
    ("Beta 6 version", "tgc_gui.py", 'TGC_GUI_VERSION = "v0.5.0-2k25-beta6"'),
    ("Beta 6 title", "tgc_gui.py", 'TGC_APP_TITLE = "TGC Designer Tools 2K25 - Beta 6"'),
    ("Slope-locked Hulkify engine", "tgc_tools.py", "TGC_HULKIFY_COURSE_V2_SLOPE_LOCK"),
    ("Slope-locked Hulkify GUI", "tgc_gui.py", "TGC_HULKIFY_GUI_V2_SLOPE_LOCK"),
    ("Standard label", "tree_profile_manager.py", 'STANDARD_SCALE_MODE = "Standard (Lidar)"'),
    ("Legacy alias uses Standard", "tree_profile_manager.py", "LEGACY_SCALE_MODE = STANDARD_SCALE_MODE"),
    ("Heroic basic label", "tree_profile_manager.py", 'HEROIC_SCALE_MODE = "Heroic"'),
    ("Epic basic label", "tree_profile_manager.py", 'EPIC_SCALE_MODE = "Epic"'),
    ("Mythic basic label", "tree_profile_manager.py", 'MYTHIC_SCALE_MODE = "Mythic"'),
    ("Epic multiplier", "tree_profile_manager.py", "EPIC_SCALE_MULTIPLIER = 1.20"),
    ("Mythic multiplier", "tree_profile_manager.py", "MYTHIC_SCALE_MULTIPLIER = 1.80"),
    ("Tree selector basic order", "tgc_gui.py", scale_order),
    ("Regional Mythic branch", "tree_profile_manager.py", "if tree_scale_mode == MYTHIC_SCALE_MODE:"),
    ("Built-in Mythic Heroic radius minimum", "tgc_image_terrain.py", "min_radius_scale = 0.70 * tree_profile_manager.MYTHIC_SCALE_MULTIPLIER"),
    ("Built-in Mythic Heroic radius maximum", "tgc_image_terrain.py", "max_radius_scale = 1.65 * tree_profile_manager.MYTHIC_SCALE_MULTIPLIER"),
    ("Built-in Mythic Heroic height minimum", "tgc_image_terrain.py", "min_height_scale = 0.85 * tree_profile_manager.MYTHIC_SCALE_MULTIPLIER"),
    ("Built-in Mythic Heroic height maximum", "tgc_image_terrain.py", "max_height_scale = 1.55 * tree_profile_manager.MYTHIC_SCALE_MULTIPLIER"),
    ("AWS EPT true-ground hotfix retained", "usgs_ept_downloader.py", "TGC_AWS_EPT_TRUE_GROUND_METRES_V1"),
    ("Safe OSM master extent retained", "usgs_ept_downloader.py", "TGC_OSM_MASTER_SAFE_EXTENT_V1"),
    ("OSM master mask verification retained", "lidar_map_api.py", "TGC_OSM_MASTER_MASK_WRITE_VERIFY_V1"),
    ("LiDAR tree master-grid mask fix retained", "tgc_image_terrain.py", "BETA6_LIDAR_TREE_MASK_MASTER_GRID_FIX_V1"),
    ("Post-CFS aligned mask engine", "osm_mask_alignment.py", "TGC_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1"),
    ("CFS viewer aligned-mask callback", "osm_alignment_viewer.py", "TGC_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1"),
    ("Pre-import stale-mask gate", "tgc_gui.py", "validateOSMMaskBeforeCourseImport"),
    ("Post-processing aligned-mask invalidation", "tgc_gui.py", "invalidateOSMMaskAlignmentAfterProcessing"),
    ("Aligned-mask sidecar invalidation engine", "osm_mask_alignment.py", "invalidate_alignment_record"),
    ("Professional mask-edit reminder", "tgc_gui.py", "Before importing, finalize the CFS alignment, rebuild the aligned mask"),
    ("Workflow UI reorder", "tgc_gui.py", "BETA6_WORKFLOW_UI_REORDER_V2"),
    ("OSM-first tab name", "tgc_gui.py", "Load OSM and Process LiDAR/DEM"),
    ("Local OSM top workflow frame", "tgc_gui.py", "localOSMSourceFrame = Frame(lidar"),
    ("CFS workflow precedes import", "tgc_gui.py", "cfsWorkflowFrame = Frame(courseControlFrame"),
    ("Background removal enabled by default", "tgc_gui.py", "backgroundCheck.select()"),
    ("Workflow UI verifier", "VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py", "Local OSM selection is the topmost item"),
    ("Responsive CFS viewer and mask rebuild", "osm_alignment_viewer.py", "TGC_BETA6_CFS_ASYNC_MASK_REBUILD_V3"),
    ("Background CFS viewer preparation", "osm_alignment_viewer.py", "TGC-CFS-Viewer-Load"),
    ("Background CFS mask rebuild", "osm_alignment_viewer.py", "TGC-CFS-Aligned-Mask-Rebuild"),
    ("Main-window async mask rebuild", "tgc_gui.py", "TGC-Main-Aligned-Mask-Rebuild"),
    ("Mask staged progress engine", "osm_mask_alignment.py", "progress_callback=None"),
    ("Fast cached mask projector", "osm_mask_alignment.py", "class _FastGridProjector"),
    ("Async mask verifier", "VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py", "CFS viewer preparation runs on a background worker"),
    ("OSM cartpath/road split engine", "OSMTGC.py", "TGC_BETA6_OSM_CARTPATH_ROAD_SPLIT_V4"),
    ("OSM walking paths restricted to golf=path", "OSMTGC.py", "TGC_BETA6_OSM_GOLF_PATH_ONLY_V4_1"),
    ("Automobile Roads UI", "tgc_gui.py", "Import Automobile Roads"),
    ("Independent road spline configuration", "OSMTGC.py", 'spline_configuration.get("road", None)'),
    ("Cartpath authority uses golf=cartpath", "OSMTGC.py", 'if golf_type == "cartpath"'),
    ("Auto Red Mask road support", "auto_red_mask.py", "include_vehicle_roads"),
    ("Aligned-mask road-width tracking", "osm_mask_alignment.py", "vehicle_road_width_m"),
    ("CFS road preview", "osm_alignment_viewer.py", '("Road", FEATURE_COLORS["road"])'),
    ("V4.1 road/path verifier", "VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py", "BETA 6 OSM ROAD SPLIT V4.1 VERIFICATION PASSED"),
    ("Custom / Unmatched OSM UI", "tgc_gui.py", "Custom / Unmatched"),
    ("Custom / Unmatched terrain-centered transform", "osm_custom_layout.py", "TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5"),
    ("Custom OSM CFS projection", "osm_alignment_viewer.py", "custom_unmatched_osm"),
    ("Custom OSM aligned-mask tracking", "osm_mask_alignment.py", '"custom_unmatched_osm": bool(custom_unmatched_osm)'),
    ("Custom OSM final course import", "tgc_image_terrain.py", "CustomTGCPointCloud"),
    ("Custom OSM verifier", "VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py", "BETA 6 CUSTOM / UNMATCHED OSM V5 VERIFICATION PASSED"),
    ("Custom OSM V5.1 course-anchor transform", "osm_custom_layout.py", "TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5_1"),
    ("Custom OSM V5.1 LiDAR/DEM preview overlay", "tgc_gui.py", "_apply_custom_unmatched_preview_overlay"),
    ("Custom OSM V5.1 verifier", "VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py", "BETA 6 CUSTOM / UNMATCHED OSM V5.1 VERIFICATION PASSED"),
    ("Beta 6 build compiles aligned-mask module", "BUILD_TGC_2K25_BETA6.bat", "osm_mask_alignment.py"),
    ("Beta 6 build verifies workflow UI", "BUILD_TGC_2K25_BETA6.bat", "VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py"),
    ("Beta 6 build verifies OSM road split", "BUILD_TGC_2K25_BETA6.bat", "python VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py"),
    ("Beta 6 build verifies Custom / Unmatched OSM", "BUILD_TGC_2K25_BETA6.bat", "python VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py"),
    ("Beta 6 build verifies Custom / Unmatched OSM V5.1", "BUILD_TGC_2K25_BETA6.bat", "python VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py"),
]

failed = []
print("TGC Designer Tools 2K25 Beta 6 source verification")
for label, filename, needle in checks:
    ok = needle in sources[filename]
    print(("PASS" if ok else "FAIL"), "-", label)
    if not ok:
        failed.append(label)

if "Heroic (Beta 5)" in sources["tree_profile_manager.py"] or "Heroic (Beta 6)" in sources["tree_profile_manager.py"]:
    print("FAIL - obsolete Heroic label remains")
    failed.append("obsolete Heroic label remains")
else:
    print("PASS - no obsolete Heroic version label")

modules = [
    "tgc_gui.py", "tgc_tools.py", "tgc_image_terrain.py",
    "tree_profile_manager.py", "tree_profile_analyzer.py",
    "dem_map_api.py", "lidar_map_api.py", "lidar_fast_native.py",
    "usgs_lidar_parser.py", "usgs_ept_downloader.py", "infill_image.py",
    "tgc_definitions.py", "OSMTGC.py", "auto_red_mask.py",
    "cfs_georef.py", "lidar_feature_filter.py", "osm_mask_alignment.py",
    "osm_alignment_viewer.py", "osm_custom_layout.py",
    "VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py",
    "VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py",
    "VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py",
    "VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py",
    "VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py",
]
for name in modules:
    try:
        py_compile.compile(str(ROOT / name), doraise=True)
        print("PASS - py_compile", name)
    except Exception as exc:
        print("FAIL - py_compile", name, "-", exc)
        failed.append("py_compile " + name)

profile_path = ROOT / "tree_profiles" / "pacific_northwest.json"
try:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["id"] == "pacific_northwest"
    assert profile["display_name"] == "Pacific Northwest"
    assert profile["enabled"] is True
    assert 'course_name' not in profile['reference_context']
    assert profile["reference_context"]["course_theme_id"] == 12
    assert profile["reference_context"]["holes"] == 18
    assert profile["reference_context"]["par"] == 69
    assert profile["all_speedtree_tree_count"] == 66
    assert profile["natural_reference_tree_count"] == 45
    assert profile["excluded_vertical_massing_count"] == 21
    assert len(profile["assets"]) == 7
    assert sum(int(asset["weight"]) for asset in profile["assets"]) == 45
    expected_assets = {
        "Generic_Conifer_Desktop06",
        "Generic_Conifer_Desktop05",
        "ScotsPine_Desktop06",
        "ScotsPine_Desktop21",
        "ScotsPine_Desktop24",
        "AlaskaCedar_Desktop_Bare01",
        "AlaskaCedar_Desktop_Bare02",
    }
    actual_assets = {asset["path"].rsplit("/", 1)[-1] for asset in profile["assets"]}
    assert actual_assets == expected_assets
    preset = profile["visual_material_preset"]
    assert preset["theme"] == 12
    assert preset["surfaces2"][6]["name"] == "Green19_TPC_Boston"
    assert preset["surfaces2"][7]["name"] == "Fringe19_TPC_Boston"
    assert preset["surfaces2"][8]["name"] == "Fairway58_Nordic"
    assert preset["surfaces2"][9]["name"] == "LightRough58_Nordic"
    assert preset["surfaces2"][10]["name"] == "HeavyRough61_ShinnecockHills"
    print("PASS - Pacific Northwest profile")
except Exception as exc:
    print("FAIL - Pacific Northwest profile -", exc)
    failed.append("Pacific Northwest profile")

try:
    spec = importlib.util.spec_from_file_location(
        "tree_profile_manager_beta6",
        ROOT / "tree_profile_manager.py",
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    assert manager.STANDARD_SCALE_MODE == "Standard (Lidar)"
    assert manager.LEGACY_SCALE_MODE == "Standard (Lidar)"
    assert manager.HEROIC_SCALE_MODE == "Heroic"
    assert manager.EPIC_SCALE_MODE == "Epic"
    assert manager.MYTHIC_SCALE_MODE == "Mythic"

    fake_profile = {
        "scale_defaults": {
            "x": {"p10": 1.0, "p50": 1.0, "p90": 1.0},
            "y": {"p10": 1.0, "p50": 1.0, "p90": 1.0},
            "z": {"p10": 1.0, "p50": 1.0, "p90": 1.0},
        },
    }
    fake_asset = {"scale": {}, "uniform_scale": None}
    standard = manager.scale_for_asset(
        fake_profile, fake_asset,
        tree_scale_mode=manager.STANDARD_SCALE_MODE,
    )
    heroic = manager.scale_for_asset(
        fake_profile, fake_asset,
        tree_scale_mode=manager.HEROIC_SCALE_MODE,
    )
    epic = manager.scale_for_asset(
        fake_profile, fake_asset,
        tree_scale_mode=manager.EPIC_SCALE_MODE,
    )
    mythic = manager.scale_for_asset(
        fake_profile, fake_asset,
        tree_scale_mode=manager.MYTHIC_SCALE_MODE,
    )
    assert all(abs(value - 1.0) < 1.0e-9 for value in standard)
    assert all(abs(value - 1.0) < 1.0e-9 for value in heroic)
    assert all(abs((e / h) - 1.2) < 1.0e-9 for e, h in zip(epic, heroic))
    assert all(abs((m / h) - 1.8) < 1.0e-9 for m, h in zip(mythic, heroic))
    print("PASS - regional Epic = 1.20x Heroic")
    print("PASS - regional Mythic = 1.80x Heroic")
except Exception as exc:
    print("FAIL - regional scale-mode formulas -", exc)
    failed.append("regional scale-mode formulas")

try:
    import tgc_definitions
    spec = importlib.util.spec_from_file_location(
        "tgc_tools_beta6",
        ROOT / "tgc_tools.py",
    )
    tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools)
    course = {
        "height": [
            {"tool": 0, "position": {"x": -10.0, "y": float("-inf"), "z": 0.0},
             "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
             "scale": {"x": 2.0, "y": 1.0, "z": 2.0},
             "type": 72, "value": 100.0, "radius": 0.0},
            {"tool": 0, "position": {"x": 10.0, "y": float("-inf"), "z": 0.0},
             "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
             "scale": {"x": 2.0, "y": 1.0, "z": 2.0},
             "type": 72, "value": 110.0, "radius": 0.0},
        ],
        "terrainHeight": [],
        "surfaceBrushes": [],
        "water": [],
        "surfaceSplines2": [],
        "outOfBounds2": {"brushes": []},
        "crowdMap2": {"brushes": []},
        "holes3": [],
        "placedObjects4": [],
    }
    before_h = tools.get_course_horizontal_bounds(course, 25)
    before_v = tools.get_course_vertical_relief_bounds(course, 25)
    # TGC_HULKIFY_10_PERCENT_V3
    tools.scale_course_horizontal(course, factor=1.10, course_version=25)
    after_h = tools.get_course_horizontal_bounds(course, 25)
    after_v = tools.get_course_vertical_relief_bounds(course, 25)
    assert abs(after_h["width"] / before_h["width"] - 1.10) < 1.0e-9
    assert abs(after_v["range"] / before_v["range"] - 1.10) < 1.0e-9
    print("PASS - Hulkify horizontal and vertical relief both scale 1.10x")
except Exception as exc:
    print("FAIL - Hulkify slope-lock self-test -", exc)
    failed.append("Hulkify slope-lock self-test")

if failed:
    print()
    print("BETA 6 VERIFICATION FAILED:")
    for label in failed:
        print(" -", label)
    raise SystemExit(1)

print()
print("BETA 6 SOURCE VERIFICATION PASSED")
