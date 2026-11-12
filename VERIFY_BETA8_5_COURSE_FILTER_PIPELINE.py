"""Offline native-import and routing checks for the Beta 8.5 Course Name filter.

TGC_BETA8_5_COURSE_BOUNDARY_FILTER_PIPELINE_V1
Run with the normal TGC build Python environment. No display or network is used.
Optional: python VERIFY_BETA8_5_COURSE_FILTER_PIPELINE.py --osm Fairview.osm
The optional check reads that file without modifying or bundling it.
"""
import argparse
import ast
import copy
from collections import Counter
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import overpy

import OSMTGC as osm
from osm_course_filter import filter_osm_course


ROOT = Path(__file__).resolve().parent
PATCH_ID = "TGC_BETA8_5_COURSE_BOUNDARY_FILTER_PIPELINE_V1"
OPTIONAL_OSM = None
EXEMPT_GOLF = {"water_hazard", "lateral_water_hazard", "cartpath", "path", "clubhouse"}


def quiet(*args, **kwargs):
    pass


def rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def xml_fixture(ways, relations=(), points=()):
    root = ET.Element("osm", version="0.6")
    coords = {}
    def tags(element, values):
        for key, value in values.items():
            ET.SubElement(element, "tag", k=str(key), v=str(value))
    def node(xy):
        if xy not in coords:
            ident = len(coords) + 1
            coords[xy] = ident
            ET.SubElement(root, "node", id=str(ident), lon=str(xy[0]), lat=str(xy[1]))
        return coords[xy]
    for ident, xy, values in ways:
        refs = [node(point) for point in xy]
        way = ET.SubElement(root, "way", id=str(ident))
        for ref in refs:
            ET.SubElement(way, "nd", ref=str(ref))
        tags(way, values)
    for xy, values in points:
        ident = node(xy)
        item = next(n for n in root.findall("node") if n.get("id") == str(ident))
        tags(item, values)
    for ident, members, values in relations:
        relation = ET.SubElement(root, "relation", id=str(ident))
        for kind, ref, role in members:
            ET.SubElement(relation, "member", type=kind, ref=str(ref), role=role)
        tags(relation, values)
    return ET.tostring(root, encoding="unicode")


def fixture_xml():
    return xml_fixture([
        (10, rectangle(0, 0, 40, 40), {"leisure": "golf_course", "name": "Fairview Demo Club"}),
        (20, rectangle(60, 0, 100, 40), {"leisure": "golf_course", "name": "Harris Demo Club"}),
        (101, rectangle(10, 10, 20, 20), {"golf": "green", "name": "Fair green"}),
        (102, [(5, 4), (10, 5), (15, 6)], {"golf": "hole", "par": "4", "ref": "1"}),
        (103, rectangle(0, 24, 5, 29), {"golf": "bunker"}),  # boundary contact is covered
        (201, rectangle(70, 10, 80, 20), {"golf": "green", "name": "Harris green"}),
        (202, [(65, 4), (70, 5), (75, 6)], {"golf": "hole", "par": "4", "ref": "2"}),
        (203, rectangle(30, 20, 44, 25), {"golf": "green", "name": "Crosses Fair boundary"}),
        (301, rectangle(35, 28, 45, 33), {"golf": "water_hazard"}),
        (302, [(61, 42), (90, 42)], {"golf": "cartpath"}),
        (303, rectangle(70, 60, 75, 65), {"building": "yes"}),
        (304, [(1, 80), (90, 80)], {"highway": "service"}),
        (305, [(1, 85), (90, 85)], {"highway": "footway"}),
        (306, rectangle(50, 70, 55, 75), {"natural": "wood"}),
        (307, rectangle(80, 60, 85, 65), {"golf": "clubhouse"}),
        (308, [(61, 46), (90, 46)], {"golf": "path"}),
    ], points=[((90, 90), {"natural": "tree"}),
               ((15, 6), {"golf": "pin"}), ((75, 6), {"golf": "pin"})])


def parse(text):
    return overpy.Overpass().parse_xml(text)


def fingerprints(result):
    """Semantic inventory includes metadata, complete geometry, and member roles."""
    def base(element):
        return (dict(element.tags), dict(getattr(element, "attributes", {}) or {}))
    return {
        "nodes": {n.id: (str(n.lat), str(n.lon), base(n)) for n in result.nodes},
        "ways": {w.id: (tuple(w._node_ids), base(w)) for w in result.ways},
        "relations": {r.id: (tuple((type(m).__name__, m.ref, m.role,
                                    dict(getattr(m, "attributes", {}) or {})) for m in r.members),
                                  base(r)) for r in result.relations},
    }


class Grid:
    width = height = 100.
    origin = (0., 0.)
    imin, imax = 0., 1.
    def ulENU(self): return (0., self.height)
    def lrENU(self): return (self.width, 0.)
    def enuToTGC(self, x, y, z): return (x, z, y)
    def latlonToTGC(self, lat, lon, x_offset=0., y_offset=0.):
        return (float(lon) + x_offset, 0., float(lat) + y_offset)
    def latlonToCV2(self, lat, lon, scale, x_offset=0., y_offset=0.):
        return ((float(lat) + y_offset) / scale, (float(lon) + x_offset) / scale)
    def enuToLatLon(self, x, y): return (y, x)
    def projToLatLon(self, x, y): return (y, x)
    def pointsAsCV2(self, scale): return np.array([[1, 1, 5, .5, 2]], dtype=float)


def course_fixture():
    return dict(surfaceSplines2=[], holes3=[], surfaces2=[{}, {}, {}],
                placedObjects4={"preserve": 123}, terrainHeight=[{"preserve": 456}])


def native(result, selector="", grid=None, **options):
    course = course_fixture()
    opts = dict(course_name_filter=selector, optimize_osm_spline_points=False,
                water=True, building=True, cartpath=True, path=True, road=True,
                wood=True, tree=True)
    opts.update(options)
    trees = osm.addOSMToTGC(course, grid or Grid(), result, options_dict=opts,
                           course_version=25, resolve_missing_nodes=False, printf=quiet)
    return course, trees


def installed_functions(filename, names, namespace):
    """Run the installed function bodies without launching the full GUI/raster stack."""
    source = (ROOT / filename).read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=filename)
    selected = [item for item in tree.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in names]
    if {item.name for item in selected} != set(names):
        raise AssertionError("Missing installed functions in " + filename)
    env = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 filename, "exec"), env)
    return env


class NativeImportTests(unittest.TestCase):
    def setUp(self):
        self.xml = fixture_xml()
        self.source = parse(self.xml)
        self.before = fingerprints(self.source)

    def tearDown(self):
        self.assertEqual(fingerprints(self.source), self.before, "Source OSM was mutated")

    def test_native_result_matches_explicitly_selected_course(self):
        root = ET.fromstring(self.xml)
        for way in list(root.findall("way")):
            if int(way.get("id")) in (201, 202, 203):
                root.remove(way)
        expected = native(parse(ET.tostring(root, encoding="unicode")))
        actual = native(self.source, "  fAiR  ")
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual[0]["holes3"]), 1)
        self.assertEqual(len(native(self.source)[0]["holes3"]), 2)
        selected = filter_osm_course(self.source, "Fair", printf=quiet)
        ids = {w.id for w in selected.ways}
        self.assertIn(103, ids, "A feature touching the course boundary must be retained")
        self.assertNotIn(203, ids, "Intersection or an inside centroid is insufficient")

    def test_blank_preserves_legacy_identity_and_native_behavior(self):
        self.assertIs(filter_osm_course(self.source, " \t ", printf=quiet), self.source)
        actual = native(self.source, "")
        with patch("osm_course_filter.filter_osm_course", side_effect=lambda source, *a, **kw: source):
            expected = native(self.source)
        self.assertEqual(actual, expected)

    def test_unknown_name_precedes_destructive_clear(self):
        course = course_fixture()
        course["surfaceSplines2"] = [{"keep": "existing spline"}]
        course["holes3"] = [{"keep": "existing hole"}]
        course["_tgcOsmWaterMulchV1"] = {"keep": "water bookkeeping"}
        course["_tgcOsmDryMulchV1"] = {"keep": "dry bookkeeping"}
        before = copy.deepcopy(course)
        with patch.object(osm, "clearFeatures", wraps=osm.clearFeatures) as clear:
            with self.assertRaises(ValueError):
                osm.addOSMToTGC(course, Grid(), self.source,
                               options_dict={"course_name_filter": "No such club"},
                               course_version=25, printf=quiet, resolve_missing_nodes=False)
        clear.assert_not_called()
        self.assertEqual(course, before)

    def test_environment_native_geometry_and_options_are_unchanged(self):
        flags = dict(green=False, bunker=False, teebox=False, fairway=False,
                     rough=False, range=False, hole=False)
        baseline = native(self.source, **flags)
        self.assertTrue(baseline[0]["surfaceSplines2"])
        self.assertEqual(len(baseline[1]), 1, "Outside tree must still be imported")
        for name in ("Fair", "Harris"):
            with self.subTest(name=name):
                self.assertEqual(native(self.source, name, **flags), baseline)
                selected = fingerprints(filter_osm_course(self.source, name, printf=quiet))
                for ident in range(301, 309):
                    self.assertEqual(selected["ways"][ident], self.before["ways"][ident])

    def test_retained_environment_relation_keeps_shared_geometry_without_golf_leak(self):
        xml = xml_fixture([
            (10, rectangle(0, 0, 40, 40), {"leisure": "golf_course", "name": "Fairview"}),
            (101, rectangle(10, 10, 20, 20), {"golf": "green"}),
            (201, rectangle(65, 10, 80, 25), {"golf": "green", "name": "Shared outer"}),
        ], [(500, [("way", 201, "outer")], {"type": "multipolygon", "natural": "water"})])
        source = parse(xml)
        before = fingerprints(source)
        selected = filter_osm_course(source, "Fair", printf=quiet)
        lookup = {w.id: w for w in selected.ways}
        self.assertIn(201, lookup)
        self.assertNotIn("golf", lookup[201].tags)
        self.assertEqual(tuple(lookup[201]._node_ids), before["ways"][201][0])
        self.assertEqual(fingerprints(selected)["relations"], before["relations"])
        self.assertEqual([n.id for n in lookup[201].get_nodes(resolve_missing=False)],
                         list(before["ways"][201][0]))
        course, _ = native(selected)
        self.assertEqual(sum(s["surface"] == 1 for s in course["surfaceSplines2"]), 1)
        self.assertIn("_tgcOsmWaterMulchV1", course)
        self.assertEqual(fingerprints(source), before)

    def test_local_course_generation_rejects_before_material_or_terrain_changes(self):
        preset = Mock(side_effect=AssertionError("Material changes happened before validation"))
        env = installed_functions("tgc_image_terrain.py", {"generate_course"}, {
            "Path": Path, "OSMTGC": osm,
            "tgc_definitions": types.SimpleNamespace(version_tags={25: {}}),
            "tree_profile_manager": types.SimpleNamespace(apply_visual_material_preset=preset),
        })
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "two_courses.osm"
            source.write_text(self.xml, encoding="utf-8")
            course = course_fixture()
            before = copy.deepcopy(course)
            with self.assertRaises(ValueError):
                env["generate_course"](course, folder, {
                    "local_osm_file": str(source), "course_name_filter": "Missing club",
                    "use_osm": True}, printf=quiet, course_version=25)
            self.assertEqual(course, before)
            self.assertEqual(source.read_text(encoding="utf-8"), self.xml)
        preset.assert_not_called()

    def test_flat_course_rejects_before_material_changes(self):
        preset = Mock(side_effect=AssertionError("Flat-course materials changed before name validation"))
        env = installed_functions("tgc_image_terrain.py", {"generate_flat_course"}, {
            "OSMTGC": osm,
            "tgc_definitions": types.SimpleNamespace(version_tags={25: {}}),
            "tree_profile_manager": types.SimpleNamespace(apply_visual_material_preset=preset),
        })
        course = course_fixture()
        before = copy.deepcopy(course)
        with self.assertRaises(ValueError):
            env["generate_flat_course"](course, self.xml,
                options_dict={"course_name_filter": "Missing club"}, printf=quiet, course_version=25)
        preset.assert_not_called()
        self.assertEqual(course, before)


class PipelineRoutingTests(unittest.TestCase):
    def setUp(self):
        self.source = parse(fixture_xml())
        self.before = fingerprints(self.source)

    def tearDown(self):
        self.assertEqual(fingerprints(self.source), self.before)

    def assert_fair(self, result):
        golf_ids = {w.id for w in result.ways if w.tags.get("golf") not in EXEMPT_GOLF and w.tags.get("golf")}
        self.assertEqual(golf_ids, {101, 102, 103})
        self.assertTrue(set(range(301, 309)).issubset({w.id for w in result.ways}))

    def test_lidar_preparation_shares_selected_overlay_and_red_mask_source(self):
        calls = []
        def overlay(source, image, *args, **kwargs):
            calls.append(("overlay", source))
            return image
        def red(source, image, *args, **kwargs):
            calls.append(("red", source))
            return image
        env = installed_functions("lidar_map_api.py", {"prepare_lidar_previews"}, {
            "np": np, "cv2": cv2, "math": math, "overpy": overpy,
            "tgc_tools": types.SimpleNamespace(create_directory=quiet),
            "load_usgs_directory": lambda *a, **kw: Grid(),
            "desired_visible_points_per_pixel": 1.,
            "_rasterize_preview_last_write": lambda pts, h, w, *a: np.zeros((h, w), np.float32),
            "normalize_image": lambda image: image,
            "OSMTGC": types.SimpleNamespace(getOSMData=lambda *a, **kw: self.source,
                                              addOSMToImage=overlay),
            "auto_red_mask": types.SimpleNamespace(apply_auto_red_mask=red),
        })
        prepared = env["prepare_lidar_previews"]("unused", 1., "unused",
            course_name_filter="Fair", auto_red_mask_enabled=True, printf=quiet)
        selected = prepared["osm_result"]
        self.assert_fair(selected)
        self.assertEqual([name for name, _ in calls], ["overlay", "red"])
        self.assertTrue(all(source is selected for _, source in calls))
        calls.clear()
        with self.assertRaises(ValueError):
            env["prepare_lidar_previews"]("unused", 1., "unused",
                course_name_filter="Missing", auto_red_mask_enabled=True, printf=quiet)
        self.assertEqual(calls, [])

    def test_dem_preparation_filters_before_boundary_and_mask_rendering(self):
        seen = []
        def boundary(dem, pc, scale, result, **kwargs):
            seen.append(result)
            return np.zeros(dem.shape + (3,), np.float32), 1, scale
        env = installed_functions("dem_map_api.py", {"prepare_dem_previews"}, {
            "rasterio": types.SimpleNamespace(__version__="verification fixture"),
            "_load_dem": lambda *a, **kw: (np.zeros((8, 9), np.float32), 1., Grid()),
            "_get_osm_for_grid": lambda *a, **kw: self.source,
            "_prepare_boundary_preview": boundary,
        })
        prepared = env["prepare_dem_previews"]([], course_name_filter="Fair", printf=quiet)
        self.assert_fair(prepared["osm_result"])
        self.assertIs(seen[-1], prepared["osm_result"])
        with self.assertRaises(ValueError):
            env["prepare_dem_previews"]([], course_name_filter="Missing", printf=quiet)
        self.assertEqual(len(seen), 1)
        blank = env["prepare_dem_previews"]([], course_name_filter="", printf=quiet)
        self.assertIs(blank["osm_result"], self.source)

    def test_custom_preview_filters_before_placement_overlay_and_mask(self):
        seen = []
        info = {"source_width_m": 10., "source_height_m": 20.}
        def placement(pc, source):
            seen.append(("placement", source))
            return pc, types.SimpleNamespace(diagnostics=lambda: info)
        def draw(source, image, *args, **kwargs):
            seen.append(("overlay", source))
            return image
        def red(source, image, *args, **kwargs):
            seen.append(("red", source))
            return image
        env = installed_functions("tgc_gui.py", {"_apply_custom_unmatched_preview_overlay"}, {
            "_load_custom_preview_osm": lambda *a, **kw: self.source,
            "_custom_preview_pointcloud": placement,
            "OSMTGC": types.SimpleNamespace(addOSMToImage=draw),
            "auto_red_mask": types.SimpleNamespace(apply_auto_red_mask=red),
        })
        for kind in ("lidar", "dem"):
            with self.subTest(kind=kind):
                seen.clear()
                prepared = dict(pc=Grid(), course_image=np.zeros((8, 9, 3)), sample_scale=1.,
                                boundary_preview_rgb=np.zeros((8, 9, 3)), boundary_preview_image_scale=1.)
                result = env["_apply_custom_unmatched_preview_overlay"](prepared, "fixture.osm", kind,
                    course_name_filter="Fair", auto_red_mask_enabled=True, printf=quiet)
                selected = result["custom_preview_osm_result"]
                self.assert_fair(selected)
                self.assertEqual([label for label, _ in seen], ["placement", "overlay", "red"])
                self.assertTrue(all(source is selected for _, source in seen))

    def test_gui_settings_include_course_name_in_mask_identity(self):
        env = installed_functions("tgc_gui.py", {"_mask_option_value", "_currentOSMMaskInputs"}, {
            "math": math, "AUTO_RED_MASK_BUFFER_DEFAULT_M": 5.,
            "AUTO_RED_MASK_BUFFER_MIN_M": 5., "AUTO_RED_MASK_BUFFER_MAX_M": 30.,
        })
        entry = lambda value: types.SimpleNamespace(get=lambda: value)
        options = {"course_name_filter": entry("  FaIr  "), "adjust_ew": entry(2.5),
                   "adjust_ns": entry(-3), "auto_red_mask_enabled": entry(True),
                   "auto_red_mask_buffer_m": entry(10.)}
        first = env["_currentOSMMaskInputs"](options)
        self.assertEqual(first["course_name_filter"], "fair")
        options["course_name_filter"] = entry("Harris")
        second = env["_currentOSMMaskInputs"](options)
        self.assertNotEqual(first, second)
        self.assertEqual(first["adjust_ew"], second["adjust_ew"])

    def test_gui_worker_calls_forward_the_selected_filter(self):
        tree = ast.parse((ROOT / "tgc_gui.py").read_text(encoding="utf-8-sig"))
        expected = {"prepare_lidar_previews", "prepare_dem_previews",
                    "_apply_custom_unmatched_preview_overlay", "open_alignment_viewer"}
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in expected:
                found.add(name)
                self.assertIn("course_name_filter", {keyword.arg for keyword in node.keywords}, name)
        self.assertEqual(found, expected)


class MaskAndReviewTests(unittest.TestCase):
    def test_mask_signature_changes_with_selection_and_keeps_blank_legacy_compatibility(self):
        import osm_mask_alignment as mask
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            source = folder / "courses.osm"
            source.write_text(fixture_xml(), encoding="utf-8")
            with patch.object(mask, "_grid_fingerprint", return_value="fixture-grid"):
                def signature(name):
                    return mask._signature(folder, {}, np.zeros((8, 9)), {}, source,
                                           0., 0., True, 5., course_name_filter=name)
                blank, fair, same, harris = [signature(name) for name in ("", "Fair", " FAIR ", "Harris")]
            self.assertEqual(fair["course_name_filter"], "fair")
            self.assertTrue(fair["course_filter_policy"])
            self.assertTrue(mask._signatures_match(fair, same)[0])
            self.assertFalse(mask._signatures_match(fair, harris)[0])
            self.assertFalse(mask._signatures_match(blank, fair)[0])
            self.assertFalse(mask._signatures_match(fair, blank)[0])
            legacy = dict(blank)
            legacy.pop("course_name_filter")
            legacy.pop("course_filter_policy")
            self.assertTrue(mask._signatures_match(legacy, blank)[0])

    def test_filtered_masks_cannot_adopt_untracked_legacy_pixels(self):
        import osm_mask_alignment as mask
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            source = folder / "courses.osm"
            source.write_text(fixture_xml(), encoding="utf-8")
            loaded = (folder, folder / "heightmap.npy", folder / "mask.png", {}, np.zeros((8, 9)), {})
            with patch.object(mask, "_load_heightmap", return_value=loaded), \
                    patch.object(mask, "_mask_shape", return_value=(8, 9)), \
                    patch.object(mask, "_load_sidecar", return_value=None), \
                    patch.object(mask, "_grid_fingerprint", return_value="fixture-grid"):
                filtered = mask.get_alignment_status(folder, source, 0., 0., True, 5.,
                                                     course_name_filter="Fair")
                blank = mask.get_alignment_status(folder, source, 0., 0., True, 5.,
                                                  course_name_filter="")
            self.assertEqual(filtered["state"], "stale")
            self.assertFalse(filtered["ok_for_import"])
            self.assertEqual(blank["state"], "legacy_zero_shift")
            with patch.object(mask, "_load_heightmap") as load:
                with self.assertRaisesRegex(RuntimeError, "Course Name"):
                    mask.adopt_existing_zero_shift_mask(folder, source, 0., 0.,
                                                        course_name_filter="Fair", printf=quiet)
            load.assert_not_called()
            self.assertEqual([p.name for p in folder.iterdir()], ["courses.osm"])

    def test_local_review_and_export_retain_other_course_and_environment_geometry(self):
        import pyproj
        import tgc_local_alignment as local
        import tgc_local_alignment_export as exporter
        source_xml = xml_fixture([
            (10, rectangle(0, 0, 40, 40), {"leisure": "golf_course", "name": "Fairview"}),
            (20, rectangle(60, 0, 100, 40), {"leisure": "golf_course", "name": "Harris"}),
            (101, rectangle(10, 10, 20, 20), {"golf": "tee"}),
            (201, rectangle(70, 10, 80, 20), {"golf": "bunker"}),
            (203, rectangle(30, 20, 44, 25), {"golf": "green"}),
            (301, rectangle(35, 28, 45, 33), {"golf": "water_hazard"}),
            (401, rectangle(65, 60, 75, 70), {"golf": "green", "natural": "water"}),
        ])
        root = ET.fromstring(source_xml)
        inverse = pyproj.Transformer.from_crs(3857, 4326, always_xy=True)
        for node in root.findall("node"):
            lon, lat = inverse.transform(float(node.get("lon")), float(node.get("lat")))
            node.set("lon", repr(lon))
            node.set("lat", repr(lat))
        raw = ET.tostring(root, encoding="utf-8")
        projection = pyproj.Proj("epsg:3857")
        data = {"heightmap": np.zeros((100, 100), np.float32), "projection": projection,
                "image_scale": 1., "origin": (0., 0.),
                "master_grid": {"resolution": 1., "min_x": 0., "min_y": 0.,
                                "max_x": 100., "max_y": 100., "rows": 100, "cols": 100,
                                "row_order": "south_up_internal", "origin_semantics": "southwest_cell_edge",
                                "xy_units": "meters", "crs_wkt": projection.crs.to_wkt()}}
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            source, output = folder / "courses.osm", folder / "reviewed.osm"
            source.write_bytes(raw)
            report = local.analyze(data, source, course_name_filter="Fair")
            features = {int(f["way_id"]): f for f in report["features"] if "way_id" in f}
            self.assertIn(101, features)
            self.assertNotIn(201, features)
            self.assertNotIn(203, features)
            self.assertIn(301, features)
            self.assertIn(401, features)
            self.assertIn(features[401]["kind"], ("water", "water_hazard"))
            self.assertEqual(report["course_name_filter"], "fair")
            selection = features[101]["selection_id"]
            with self.assertRaisesRegex(exporter.CorrectionError, "Course Name"):
                local.apply_reviewed(report, [selection], output, current_data=data,
                    current_nudge=(0., 0.), current_osm_file=source, current_course_name_filter="Harris",
                    manual_overrides={selection: {"east_m": 1., "north_m": 0.}})
            self.assertFalse(output.exists())
            local.apply_reviewed(report, [selection], output, current_data=data,
                current_nudge=(0., 0.), current_osm_file=source, current_course_name_filter=" FAIR ",
                manual_overrides={selection: {"east_m": 1., "north_m": 0.}})
            self.assertTrue(output.is_file())
            before = fingerprints(parse(raw.decode("utf-8")))
            after = fingerprints(parse(output.read_text(encoding="utf-8")))
            self.assertEqual(after["ways"], before["ways"])
            self.assertEqual(after["relations"], before["relations"])
            moved = set(before["ways"][101][0])
            for ident, node in before["nodes"].items():
                if ident not in moved:
                    self.assertEqual(after["nodes"][ident], node, "Unselected node changed: " + str(ident))
            self.assertTrue(any(after["nodes"][ident] != before["nodes"][ident] for ident in moved))
            self.assertEqual(source.read_bytes(), raw)
            np.testing.assert_array_equal(data["heightmap"], np.zeros((100, 100), np.float32))


class FairviewFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if OPTIONAL_OSM is None:
            raise unittest.SkipTest("Optional Fairview file check: supply --osm PATH")
        cls.path = Path(OPTIONAL_OSM)
        cls.raw = cls.path.read_bytes()
        cls.source = parse(cls.raw.decode("utf-8-sig"))
        cls.before = fingerprints(cls.source)
        cls.selected = filter_osm_course(cls.source, "Fair", printf=quiet)

    @classmethod
    def tearDownClass(cls):
        if cls.path.read_bytes() != cls.raw or fingerprints(cls.source) != cls.before:
            raise AssertionError("The provided OSM source file/result changed")

    def test_expected_named_boundaries_and_course_split(self):
        courses = {w.id: w.tags.get("name") for w in self.source.ways if w.tags.get("leisure") == "golf_course"}
        self.assertEqual(courses.get(43398982), "Fairview Country Club")
        self.assertEqual(courses.get(43398803), "Griffith E. Harris Golf Course")
        core = lambda source: {w.id: w for w in source.ways if w.tags.get("golf") and w.tags["golf"] not in EXEMPT_GOLF}
        before, fair = core(self.source), core(self.selected)
        harris = core(filter_osm_course(self.source, "Harris", printf=quiet))
        self.assertEqual((len(before), len(fair), len(harris)), (216, 161, 55))
        self.assertFalse(set(fair) & set(harris))
        self.assertEqual(set(fair) | set(harris), set(before))
        self.assertEqual(Counter(w.tags["golf"] for w in fair.values()), {
            "hole": 18, "fairway": 19, "green": 20, "bunker": 55, "tee": 48, "driving_range": 1})
        self.assertEqual(sorted(int(w.tags["ref"]) for w in fair.values() if w.tags["golf"] == "hole"), list(range(1, 19)))
        self.assertEqual(sum(n.tags.get("golf") == "pin" for n in self.selected.nodes), 18)
        self.assertEqual(len(self.selected.ways), 656)
        self.assertEqual({w.id for w in self.selected.ways if w.tags.get("leisure") == "golf_course"}, {43398982})

    def test_every_environment_element_and_all_21_relations_are_preserved(self):
        selected = fingerprints(self.selected)
        self.assertEqual(len(self.source.relations), 21)
        self.assertEqual(Counter(r.tags.get("type") for r in self.source.relations), {
            "boundary": 10, "multipolygon": 8, "route": 2, "waterway": 1})
        self.assertEqual(selected["relations"], self.before["relations"])
        protected = [w for w in self.source.ways
                     if (not w.tags.get("golf") or w.tags["golf"] in EXEMPT_GOLF)
                     and (w.tags.get("leisure") != "golf_course" or w.id == 43398982)]
        # 494 environmental/non-core ways plus the selected course outline.
        # The other course outline is deliberately removed as course metadata.
        self.assertEqual(len(protected), 495)
        for way in protected:
            self.assertEqual(selected["ways"][way.id], self.before["ways"][way.id], "way " + str(way.id))
            for ident in way._node_ids:
                self.assertEqual(selected["nodes"][ident], self.before["nodes"][ident])
        for node in self.source.nodes:
            if not node.tags.get("golf"):
                self.assertEqual(selected["nodes"][node.id], self.before["nodes"][node.id])
        self.assertEqual(sum(n.tags.get("natural") == "tree" for n in self.selected.nodes), 20)
        self.assertEqual(sum(w.tags.get("golf") == "cartpath" for w in self.selected.ways), 37)
        self.assertEqual(sum(w.tags.get("golf") == "water_hazard" for w in self.selected.ways), 4)
        self.assertEqual(selected["ways"][43386755], self.before["ways"][43386755], "Crossing water must not be clipped")

    def test_actual_native_import_produces_exact_fairview_18_routes(self):
        lons = [float(n.lon) for n in self.source.nodes]
        lats = [float(n.lat) for n in self.source.nodes]
        class GeographicGrid(Grid):
            min_lon, min_lat = min(lons), min(lats)
            sx = 111319.49079327358 * math.cos(math.radians(sum(lats) / len(lats)))
            sy = 111319.49079327358
            width = (max(lons) - min(lons)) * sx + 1.
            height = (max(lats) - min(lats)) * sy + 1.
            def latlonToTGC(self, lat, lon, x_offset=0., y_offset=0.):
                return ((float(lon) - self.min_lon) * self.sx + x_offset, 0.,
                        (float(lat) - self.min_lat) * self.sy + y_offset)
        grid = GeographicGrid()
        course, _ = native(self.source, "Fair", grid=grid, water=False, building=False,
                           cartpath=False, path=False, road=False, wood=False, tree=False)
        routes = sorted((w for w in self.selected.ways if w.tags.get("golf") == "hole"),
                        key=lambda way: int(way.tags["ref"]))
        expected = []
        for way in routes:
            par = int(way.tags["par"])
            points = [grid.latlonToTGC(n.lat, n.lon) for n in way.get_nodes(resolve_missing=False)]
            points = osm.normalizeHoleWaypointsForTGC(par, points, printf=quiet, hole_num=int(way.tags["ref"]))
            expected.append(osm.newHole(par, points, 25))
        self.assertEqual(len(course["holes3"]), 18)
        self.assertEqual(course["holes3"], expected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--osm", metavar="PATH", help="Optional original Fairview.osm for the real-data checks")
    args, remaining = parser.parse_known_args()
    OPTIONAL_OSM = args.osm
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
