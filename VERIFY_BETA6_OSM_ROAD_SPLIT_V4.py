from pathlib import Path
import importlib.util
import json
import py_compile
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parent


def fail(message):
    print("FAIL - " + message)
    raise SystemExit(1)


def read(name):
    path = ROOT / name
    if not path.is_file():
        fail(name + " was not found")
    return path.read_text(encoding="utf-8")


def load_osmtgc():
    # The full Beta 6 checkout has these modules.  The tiny standalone source
    # verification snapshot may not, so provide only the definitions required
    # to import OSMTGC and exercise its pure tag classifier.
    if "overpy" not in sys.modules:
        try:
            __import__("overpy")
        except Exception:
            fake_overpy = types.ModuleType("overpy")
            fake_overpy.exception = types.SimpleNamespace(OverPyException=Exception)
            sys.modules["overpy"] = fake_overpy

    if "GeoPointCloud" not in sys.modules:
        try:
            __import__("GeoPointCloud")
        except Exception:
            fake_geo = types.ModuleType("GeoPointCloud")
            fake_geo.GeoPointCloud = type("GeoPointCloud", (), {})
            sys.modules["GeoPointCloud"] = fake_geo

    if "tgc_definitions" not in sys.modules:
        try:
            __import__("tgc_definitions")
        except Exception:
            fake_defs = types.ModuleType("tgc_definitions")
            fake_defs.featuresToSurfaces = {
                "bunker": 0, "green": 1, "fairway": 2, "rough": 3,
                "heavyrough": 4, "surface1": 7, "surface2": 8,
                "surface3": 10, "cartpath": 10,
            }
            fake_defs.version_tags = {
                25: {"holes": "holes3", "splines": "surfaceSplines2"},
                23: {"holes": "holes2", "splines": "surfaceSplines"},
                19: {"holes": "holes", "splines": "surfaceSplines"},
            }
            sys.modules["tgc_definitions"] = fake_defs

    spec = importlib.util.spec_from_file_location("OSMTGC_beta6_v4_verify", ROOT / "OSMTGC.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    osm = read("OSMTGC.py")
    gui = read("tgc_gui.py")
    image_terrain = read("tgc_image_terrain.py")
    mask = read("auto_red_mask.py")
    alignment = read("osm_mask_alignment.py")
    viewer = read("osm_alignment_viewer.py")

    checks = [
        ("OSM V4 marker", "TGC_BETA6_OSM_CARTPATH_ROAD_SPLIT_V4" in osm),
        ("OSM V4.1 golf-path-only marker", "TGC_BETA6_OSM_GOLF_PATH_ONLY_V4_1" in osm),
        ("Automobile Roads checkbox", 'text="Import Automobile Roads"' in gui),
        ("Automobile Roads default OFF", "roadCheck.deselect()" in gui),
        ("Road setting refreshes mask status", 'options_entries_dict["road"].trace_add("write", _scheduleOSMMaskStatusRefresh)' in gui),
        ("CFS workflow centered", "cfsWorkflowFrame.pack(padx=10, pady=(10, 4))" in gui and "cfsWorkflowFrame.pack(padx=10, pady=(10, 4), anchor=W)" not in gui),
        ("Road spline configuration", 'spline_configuration.get("road", None)' in osm),
        ("Road default width", "pathWidth = 6.0" in osm),
        ("Independent road constructor", "def newRoad(" in osm),
        ("Road optimizer category", '"road": 0.50' in osm),
        ("Road import option", "options_dict.get('road', False)" in osm),
        ("Road indices remembered", "last_imported_road_spline_indices.add(road_index)" in osm),
        ("Auto Flatten skips roads", "skip_spline_indices" in image_terrain and "last_imported_road_spline_indices" in image_terrain),
        ("Mask road option", "include_vehicle_roads" in mask),
        ("Mask road width", "vehicle_road_width_m" in mask),
        ("Mask sidecar road setting", '"include_vehicle_roads"' in alignment),
        ("Mask sidecar road width", '"vehicle_road_width_m"' in alignment),
        ("splines.json road width reader", 'get("road")' in alignment and '"pathWidth"' in alignment),
        ("CFS road preview color", '"road": "#ff5a5a"' in viewer),
        ("CFS shared classifier", "OSMTGC.classifyHighwayForTGC(tags)" in viewer),
        ("CFS Road legend", '("Road", FEATURE_COLORS["road"])' in viewer),
    ]
    failed = []
    for label, ok in checks:
        print(("PASS" if ok else "FAIL") + " - " + label)
        if not ok:
            failed.append(label)

    # Import and exercise the single classifier used by import, preview and mask.
    try:
        mod = load_osmtgc()
        cases = [
            ({"golf": "cartpath", "highway": "service", "golf_cart": "designated"}, "cartpath", "golf cartpath + service"),
            ({"golf": "cartpath", "highway": "path", "golf_cart": "yes"}, "cartpath", "golf cartpath + path"),
            ({"highway": "service", "golf_cart": "designated"}, "road", "service road with golf-cart access but no golf=cartpath"),
            ({"highway": "service"}, "road", "service road"),
            ({"highway": "residential"}, "road", "residential road"),
            ({"highway": "primary"}, "road", "primary road"),
            ({"highway": "track", "access": "private"}, "road", "track"),
            ({"highway": "footway"}, None, "generic footway excluded"),
            ({"highway": "path"}, None, "generic path excluded"),
            ({"highway": "pedestrian"}, None, "generic pedestrian way excluded"),
            ({"highway": "footway", "footway": "sidewalk"}, None, "sidewalk excluded"),
            ({"highway": "footway", "footway": "crossing"}, None, "crossing excluded"),
            ({"highway": "footway", "footway": "access_aisle"}, None, "foot access aisle excluded"),
            ({"golf": "path", "highway": "footway"}, "walkingpath", "golf walking path + footway"),
            ({"golf": "path", "highway": "path"}, "walkingpath", "golf walking path + path"),
            ({"golf": "path", "highway": "service"}, "walkingpath", "golf walking path + service"),
            ({"highway": "cycleway", "foot": "yes"}, None, "cycleway excluded without golf=path"),
            ({"highway": "service", "motor_vehicle": "no", "foot": "yes"}, None, "motor-blocked service way excluded without golf=path"),
            ({"highway": "proposed"}, None, "proposed highway"),
        ]
        for tags, expected, label in cases:
            actual = mod.classifyHighwayForTGC(tags)
            ok = actual == expected
            print(("PASS" if ok else "FAIL") + " - classifier " + label + " => " + repr(actual))
            if not ok:
                failed.append("classifier " + label)
    except Exception as exc:
        print("FAIL - classifier self-test -", exc)
        failed.append("classifier self-test")

    # The Cartpaths control is deliberately *only* golf=cartpath.  Generic
    # golf_cart access must not be used as cartpath authority.
    if 'if _osm_access_positive(golf_cart):\n        return "cartpath"' in osm:
        print("FAIL - generic golf_cart access still promotes roads to cartpaths")
        failed.append("generic golf_cart promotion")
    else:
        print("PASS - cartpath authority is restricted to golf=cartpath")

    if 'amenity_type == "parking" and _osm_access_positive(golf_cart_type)' in osm:
        print("FAIL - golf-cart parking is still imported by the Cartpaths control")
        failed.append("golf-cart parking cartpath import")
    else:
        print("PASS - non-golf parking is not imported as a cartpath")

    # Exercise the aligned-mask signature extension with the established V1
    # verifier stubs. Roads must make a mask stale only when Auto Red Mask is
    # active, and road.pathWidth must be recorded from splines.json.
    try:
        v1_spec = importlib.util.spec_from_file_location(
            "beta6_mask_v1_test_helpers",
            ROOT / "VERIFY_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1.py",
        )
        v1 = importlib.util.module_from_spec(v1_spec)
        v1_spec.loader.exec_module(v1)
        align_mod, restore_alignment_stubs = v1._load_with_test_stubs()
        try:
            with tempfile.TemporaryDirectory(prefix="tgc_road_mask_v4_") as temp:
                folder = Path(temp)
                v1._write_initial_project(folder)
                osm_file = folder / "layout.osm"

                align_mod.rebuild_aligned_mask(
                    folder, osm_file, 0.0, 0.0, True, 5.0,
                    printf=lambda _message: None,
                )
                roads_off = align_mod.get_alignment_status(
                    folder, osm_file, 0.0, 0.0, True, 5.0,
                    include_vehicle_roads=False,
                )
                roads_on = align_mod.get_alignment_status(
                    folder, osm_file, 0.0, 0.0, True, 5.0,
                    include_vehicle_roads=True,
                )
                assert roads_off["state"] == "current"
                assert roads_on["state"] == "stale"

                align_mod.rebuild_aligned_mask(
                    folder, osm_file, 0.0, 0.0, False, 5.0,
                    printf=lambda _message: None,
                )
                disabled_off = align_mod.get_alignment_status(
                    folder, osm_file, 0.0, 0.0, False, 5.0,
                    include_vehicle_roads=False,
                )
                disabled_on = align_mod.get_alignment_status(
                    folder, osm_file, 0.0, 0.0, False, 5.0,
                    include_vehicle_roads=True,
                )
                assert disabled_off["state"] == "current"
                assert disabled_on["state"] == "current"

                (folder / "splines.json").write_text(
                    json.dumps({"road": {"pathWidth": 11.5}}),
                    encoding="utf-8",
                )
                _folder, _hp, _mp, data, heightmap, grid = align_mod._load_heightmap(folder)
                signature = align_mod._signature(
                    folder, data, heightmap, grid, osm_file, 0.0, 0.0, True, 5.0,
                    include_vehicle_roads=True,
                )
                assert signature["include_vehicle_roads"] is True
                assert abs(float(signature["vehicle_road_width_m"]) - 11.5) < 1.0e-9
            print("PASS - aligned mask tracks road toggle/width only when Auto Red Mask is active")
        finally:
            restore_alignment_stubs()
    except Exception as exc:
        print("FAIL - aligned-mask road signature self-test -", exc)
        failed.append("aligned-mask road signature self-test")

    for name in (
        "OSMTGC.py", "tgc_gui.py", "tgc_image_terrain.py", "auto_red_mask.py",
        "osm_mask_alignment.py", "osm_alignment_viewer.py",
        "VERIFY_BETA6_WORKFLOW_UI_REORDER_V2.py",
    ):
        try:
            py_compile.compile(str(ROOT / name), doraise=True)
        except Exception as exc:
            print("FAIL - py_compile", name, "-", exc)
            failed.append("py_compile " + name)

    if failed:
        print("\nBETA 6 OSM ROAD SPLIT V4.1 VERIFICATION FAILED:")
        for item in failed:
            print(" -", item)
        return 1

    print("\nBETA 6 OSM ROAD SPLIT V4.1 VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
