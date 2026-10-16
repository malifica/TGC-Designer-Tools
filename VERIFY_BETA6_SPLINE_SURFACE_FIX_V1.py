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


def load_osmtgc():
    if "overpy" not in sys.modules:
        try:
            __import__("overpy")
        except Exception:
            fake = types.ModuleType("overpy")
            fake.RelationWay = type("RelationWay", (), {})
            fake.Overpass = type("Overpass", (), {})
            fake.exception = types.SimpleNamespace(OverPyException=Exception)
            sys.modules["overpy"] = fake

    spec = importlib.util.spec_from_file_location(
        "OSMTGC_beta6_spline_fix_verify",
        ROOT / "OSMTGC.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_tgc_tools():
    spec = importlib.util.spec_from_file_location(
        "tgc_tools_beta6_spline_fix_verify",
        ROOT / "tgc_tools.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(label, condition, failed):
    print(("PASS" if condition else "FAIL") + " - " + label)
    if not condition:
        failed.append(label)


def main():
    failed = []

    osm_text = (ROOT / "OSMTGC.py").read_text(encoding="utf-8")
    tools_text = (ROOT / "tgc_tools.py").read_text(encoding="utf-8")
    image_text = (ROOT / "tgc_image_terrain.py").read_text(encoding="utf-8")
    alignment_text = (ROOT / "osm_mask_alignment.py").read_text(encoding="utf-8")

    check(
        "spline surface fix marker",
        "TGC_BETA6_SPLINE_SURFACE_FIX_V1" in osm_text
        and "TGC_BETA6_SPLINE_SURFACE_FIX_V1" in tools_text,
        failed,
    )
    check(
        "water has a dedicated configuration section",
        '_spline_section("water")' in osm_text,
        failed,
    )
    check(
        "stream has a dedicated configuration section",
        '_spline_section("stream")' in osm_text,
        failed,
    )
    check(
        "course import reports the loaded spline configuration",
        "get_spline_configuration_json(\n            heightmap_dir_path,\n            printf=printf" in image_text,
        failed,
    )
    check(
        "aligned-mask road width uses strict configuration loader",
        "tgc_tools.get_spline_configuration_json" in alignment_text,
        failed,
    )

    try:
        mod = load_osmtgc()
        points = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (20.0, 0.0, 5.0),
            (30.0, 0.0, 5.0),
        ]

        mod.spline_configuration = None
        cart = mod.newCartPath(
            points,
            area=False,
            course_version=25,
            optimize_points=False,
        )
        road = mod.newRoad(
            points,
            area=False,
            course_version=25,
            optimize_points=False,
        )
        water = mod.newWaterHazard(points, area=True, course_version=25)
        stream = mod.newWaterHazard(points, area=False, course_version=25)

        check("2K25 cart path defaults to semantic cart-path surface 7", cart["surface"] == 7, failed)
        check("2K25 cart path default width remains 2.0 m", abs(float(cart["width"]) - 2.0) < 1.0e-9, failed)
        check("2K25 road defaults to asphalt / surface 3 id 10", road["surface"] == 10, failed)
        check("2K25 road default width remains 6.0 m", abs(float(road["width"]) - 6.0) < 1.0e-9, failed)
        check("2K25 closed water defaults to mulch / surface 2 id 8", water["surface"] == 8, failed)
        check("2K25 open stream defaults to mulch / surface 2 id 8", stream["surface"] == 8, failed)
        check("2K25 stream default width remains 2.0 m", abs(float(stream["width"]) - 2.0) < 1.0e-9, failed)

        mod.spline_configuration = {
            "cartpath": {
                "primarySurface": "cartpath",
                "pathWidth": 3.4,
            },
            "road": {
                "primarySurface": "asphalt",
                "pathWidth": 8.0,
            },
            "water": {
                "primarySurface": "mulch",
                "pathWidth": 0.01,
            },
            "stream": {
                "primarySurface": "mulch",
                "pathWidth": 2.6,
                "handleLength": 0.5,
                "tightSplines": False,
            },
        }

        cart = mod.newCartPath(
            points,
            area=False,
            course_version=25,
            optimize_points=False,
        )
        road = mod.newRoad(
            points,
            area=False,
            course_version=25,
            optimize_points=False,
        )
        water = mod.newWaterHazard(points, area=True, course_version=25)
        stream = mod.newWaterHazard(points, area=False, course_version=25)

        check("valid cartpath.pathWidth 3.4 is honored", abs(float(cart["width"]) - 3.4) < 1.0e-9, failed)
        check("cartpath semantic name stays on surface 7", cart["surface"] == 7, failed)
        check("road.pathWidth 8.0 is honored", abs(float(road["width"]) - 8.0) < 1.0e-9, failed)
        check("asphalt semantic name resolves to surface 10", road["surface"] == 10, failed)
        check("water mulch semantic name resolves to surface 8", water["surface"] == 8, failed)
        check("stream width override is honored", abs(float(stream["width"]) - 2.6) < 1.0e-9, failed)
        check("stream inherits/uses mulch surface 8", stream["surface"] == 8, failed)

        messages = []
        mod._print_spline_configuration_summary(25, printf=messages.append)
        summary = "\n".join(messages)
        check("effective spline summary reports 3.4 m cart path", "cartpath=surface 7 @ 3.4 m" in summary, failed)
        check("effective spline summary reports asphalt road surface 10", "road=surface 10 @ 8.0 m" in summary, failed)
        check("effective spline summary reports mulch water surface 8", "water=surface 8" in summary, failed)
    except Exception as exc:
        print("FAIL - OSM spline construction self-test - " + str(exc))
        failed.append("OSM spline construction self-test")

    try:
        tools = load_tgc_tools()
        with tempfile.TemporaryDirectory(prefix="tgc_spline_fix_") as temp:
            folder = Path(temp)
            valid = {
                "cartpath": {"primarySurface": "cartpath", "pathWidth": 3.4},
                "road": {"primarySurface": "asphalt", "pathWidth": 8.0},
                "water": {"primarySurface": "mulch", "pathWidth": 0.01},
            }
            (folder / "splines.json").write_text(
                json.dumps(valid),
                encoding="utf-8",
            )
            messages = []
            loaded = tools.get_spline_configuration_json(folder, printf=messages.append)
            check("valid splines.json loads", loaded["cartpath"]["pathWidth"] == 3.4, failed)
            check("loader reports exact path", bool(messages) and "splines.json" in messages[0], failed)

            (folder / "splines.json").write_text(
                '{"road": {"primarySurface": "asphalt" "pathWidth": 8.0}}',
                encoding="utf-8",
            )
            try:
                tools.get_spline_configuration_json(folder, printf=None)
                invalid_failed = False
            except ValueError as exc:
                text = str(exc)
                invalid_failed = "line" in text and "column" in text
            check("invalid JSON fails with line and column", invalid_failed, failed)

        with tempfile.TemporaryDirectory(prefix="tgc_spline_name_") as temp:
            folder = Path(temp)
            (folder / "splines(2).json").write_text("{}", encoding="utf-8")
            try:
                tools.get_spline_configuration_json(folder, printf=None)
                name_failed = False
            except ValueError as exc:
                name_failed = "named exactly splines.json" in str(exc)
            check("misnamed splines JSON fails instead of silently defaulting", name_failed, failed)
    except Exception as exc:
        print("FAIL - strict splines.json loader self-test - " + str(exc))
        failed.append("strict splines.json loader self-test")

    for name in (
        "OSMTGC.py",
        "tgc_tools.py",
        "tgc_image_terrain.py",
        "osm_mask_alignment.py",
    ):
        try:
            py_compile.compile(str(ROOT / name), doraise=True)
            print("PASS - py_compile " + name)
        except Exception as exc:
            print("FAIL - py_compile " + name + " - " + str(exc))
            failed.append("py_compile " + name)

    try:
        default_config = json.loads(
            (ROOT / "extras" / "splines.json").read_text(encoding="utf-8")
        )
        check("shipped config cartpath is semantic cartpath", default_config["cartpath"]["primarySurface"] == "cartpath", failed)
        check("shipped config road is asphalt", default_config["road"]["primarySurface"] == "asphalt", failed)
        check("shipped config water is mulch", default_config["water"]["primarySurface"] == "mulch", failed)
    except Exception as exc:
        print("FAIL - shipped extras/splines.json - " + str(exc))
        failed.append("shipped extras/splines.json")

    if failed:
        print("\nBETA 6 SPLINE SURFACE FIX V1 VERIFICATION FAILED:")
        for item in failed:
            print(" - " + item)
        return 1

    print("\nBETA 6 SPLINE SURFACE FIX V1 VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
