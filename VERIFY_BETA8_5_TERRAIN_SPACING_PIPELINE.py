"""Real course-generation checks for independently spaced terrain stamps.

TGC_BETA8_5_TERRAIN_SPACING_PIPELINE_V1
Uses small synthetic projected rasters, OSM and LiDAR tree candidates. No user
project, network, Tk display, Windows executable, or external fixture is needed.
Run with the normal TGC build Python environment.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import math
from pathlib import Path
import random
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pyproj

from GeoPointCloud import GeoPointCloud
import tgc_image_terrain as terrain


ROOT = Path(__file__).resolve().parent
PATCH_ID = "TGC_BETA8_5_TERRAIN_SPACING_PIPELINE_V1"
MISSING = object()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quiet(*args, **kwargs):
    pass


def main_stamps(course):
    return [stamp for stamp in course["height"] if stamp["type"] == 72]


def position(stamp):
    return (round(float(stamp["position"]["x"]), 9),
            round(float(stamp["position"]["z"]), 9))


def stamp_map(course):
    return {position(stamp): stamp for stamp in main_stamps(course)}


def target_axis(last, step):
    """Independent mathematical expectation, including an off-phase endpoint."""
    count = int(math.floor(float(last) / float(step) + 1e-10))
    values = [index * float(step) for index in range(count + 1)]
    if not math.isclose(values[-1], float(last), rel_tol=0., abs_tol=1e-9):
        values.append(float(last))
    return values


class Fixture:
    def __init__(self, folder, rows=9, cols=13, source_spacing=1., holes=False,
                 leading=False, plane=True, cartpath=False, graduated=False):
        self.folder = Path(folder)
        self.rows, self.cols, self.scale = rows, cols, float(source_spacing)
        self.projection = pyproj.Proj("epsg:32618")
        self.edge = (600123.25, 4545678.75)
        reference = GeoPointCloud()
        reference.proj, reference.origin = self.projection, (0., 0.)
        self.origin = reference.projToLatLon(*self.edge)
        yy, xx = np.indices((rows, cols), dtype=float)
        z = 100. + .013 * xx * self.scale + .021 * yy * self.scale
        if not plane:
            z += .0007 * xx * yy
        z = z.astype(np.float32)
        self.mask = np.full((rows, cols, 3), 255, np.uint8)  # south-up working order
        self.forbidden = np.zeros((rows, cols), dtype=bool)
        if leading:
            z[:1, :] = np.nan
            z[:, :3] = np.nan
            self.forbidden[:1, :] = True
            self.forbidden[:, :3] = True
        if holes:
            # Red exclusion, blue purge, and an original NoData blue pixel.
            # They intentionally occupy both coarse and off-phase positions.
            for row, col, color in ((4, 5, (0, 0, 255)), (6, 7, (255, 0, 0)),
                                    (3, 9, (255, 0, 0))):
                self.mask[row, col] = color
                self.forbidden[row, col] = True
            z[3, 9] = np.nan
        if graduated:
            detail = ((yy >= rows // 2 - 14) & (yy < rows // 2 + 14)
                      & (xx >= cols // 2 - 15) & (xx < cols // 2 + 15))
            self.mask[~detail] = (0, 0, 255)
            self.mask[30:34, 30:34] = (255, 0, 0)
            self.forbidden[~detail] = True
        self.raw_height = z[:, :, None]
        self.grid = {
            "min_x": self.edge[0], "min_y": self.edge[1],
            "max_x": self.edge[0] + cols * self.scale,
            "max_y": self.edge[1] + rows * self.scale,
            "rows": rows, "cols": cols, "resolution": self.scale,
            "lower_left_latlon": list(self.origin), "row_order": "south_up_internal",
            "origin_semantics": "southwest_cell_edge", "xy_units": "meters",
            "crs_wkt": self.projection.crs.to_wkt(),
        }
        self.data = {
            "heightmap": self.raw_height,
            "visual": np.repeat(np.linspace(0., 1., rows * cols, dtype=np.float32)
                                .reshape(rows, cols, 1), 3, axis=2),
            "projection": self.projection, "image_scale": self.scale,
            "origin": self.origin, "master_grid": self.grid,
            "trees": [(self.edge[0] + 8.5 * self.scale, self.edge[1] + 5.5 * self.scale, 2., 8.),
                      (self.edge[0] + 10.5 * self.scale, self.edge[1] + 7.5 * self.scale, 2.5, 11.)],
            "buildings": [], "pointcloud": [], "source": "Synthetic LiDAR verification",
            "tree_source_sample_scale": self.scale,
        }
        np.save(self.folder / "heightmap.npy", self.data)
        if not cv2.imwrite(str(self.folder / "mask.png"), np.flip(self.mask, 0)):
            raise RuntimeError("Could not write the temporary test mask")
        root = ET.Element("osm", version="0.6")
        coordinates = {}
        def node(xy):
            if xy not in coordinates:
                ident = len(coordinates) + 1
                coordinates[xy] = ident
                lat, lon = reference.projToLatLon(self.edge[0] + xy[0] * self.scale,
                                                 self.edge[1] + xy[1] * self.scale)
                ET.SubElement(root, "node", id=str(ident), lat=str(lat), lon=str(lon))
            return coordinates[xy]
        ways = [
            (101, [(2.5, 2.5), (4.5, 2.5), (4.5, 4.5), (2.5, 4.5), (2.5, 2.5)], {"golf": "green"}),
            (102, [(1.5, 1.5), (4.5, 2.5), (6.5, 3.5)], {"golf": "hole", "par": "4", "ref": "1"}),
        ]
        if cartpath:
            ways.append((103, [(3.5, rows * .5), (cols - 3.5, rows * .5)], {"golf": "cartpath"}))
        for ident, xy, tags in ways:
            refs = [node(point) for point in xy]
            way = ET.SubElement(root, "way", id=str(ident))
            for ident_node in refs:
                ET.SubElement(way, "nd", ref=str(ident_node))
            for key, value in tags.items():
                ET.SubElement(way, "tag", k=key, v=value)
        self.osm_path = self.folder / "fixture.osm"
        self.osm_path.write_bytes(ET.tostring(root, encoding="utf-8"))
        self.source_hashes = {name: sha(self.folder / name)
                              for name in ("heightmap.npy", "mask.png", "fixture.osm")}
        self.options = {
            "brush_scale": 2., "brush_type": 72, "use_osm": True,
            "local_osm_file": str(self.osm_path), "lidar_trees": True,
            "tree": False, "tree_variety": False, "optimize_osm_spline_points": False,
            "filter_lidar_trees_surfaces": False, "filter_lidar_trees_50m": False,
            "exclude_lidar_trees_red_mask": True, "purge_water": bool(holes or graduated),
        }
        self.last_cloud = None
        self.messages = []

    def assert_source_unchanged(self, test):
        test.assertEqual({name: sha(self.folder / name) for name in self.source_hashes}, self.source_hashes)
        saved = np.load(self.folder / "heightmap.npy", allow_pickle=True).item()
        np.testing.assert_array_equal(saved["heightmap"], self.raw_height)
        np.testing.assert_array_equal(saved["visual"], self.data["visual"])
        test.assertEqual(saved["trees"], self.data["trees"])
        test.assertEqual(saved["master_grid"], self.grid)
        test.assertEqual(saved["image_scale"], self.scale)
        test.assertEqual(saved["origin"], self.origin)
        test.assertEqual(saved["tree_source_sample_scale"], self.scale)
        test.assertTrue(saved["projection"].crs.equals(self.projection.crs))
        if self.last_cloud is not None:
            cloud, before, origin, width, height = self.last_cloud
            np.testing.assert_array_equal(cloud.points(), before)
            test.assertEqual((cloud.origin, cloud.width, cloud.height), (origin, width, height))

    def generate(self, test, spacing=MISSING, **options):
        selected = dict(self.options, **options)
        if spacing is not MISSING:
            selected["terrain_stamp_spacing"] = spacing
        course = dict(theme=12, surfaceSplines2=[], holes3=[], placedObjects4=[],
                      surfaces2=[{}, {}, {}], sourceFixture={"must_remain": 42})
        captures = []
        class RecordingCloud(GeoPointCloud):
            def addFromImage(self, *args, **kwargs):
                result = super().addFromImage(*args, **kwargs)
                captures.append((self, self.points().copy(), self.origin, self.width, self.height))
                return result
        self.messages = []
        random.seed(1729)
        with patch.object(terrain, "GeoPointCloud", RecordingCloud):
            output = terrain.generate_course(course, str(self.folder), options_dict=selected,
                                             course_version=25, printf=self.messages.append)
        test.assertIsNotNone(output)
        test.assertTrue(captures, "The actual source pointcloud was not built")
        self.last_cloud = captures[0]  # Later clouds belong to independent backgrounds.
        self.assert_source_unchanged(test)
        return output


class TerrainSpacingPipelineTests(unittest.TestCase):
    def fixture(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Fixture(directory.name, **kwargs)

    def assert_features_unchanged(self, source, sampled):
        for key in ("surfaceSplines2", "holes3", "placedObjects4", "surfaces2", "sourceFixture"):
            self.assertEqual(source[key], sampled[key], key + " changed with stamp spacing")

    def test_missing_source_and_explicit_native_spacing_are_exactly_equal(self):
        fixture = self.fixture(plane=False)
        missing = fixture.generate(self)
        source = fixture.generate(self, "Source")
        native = fixture.generate(self, "1")
        self.assertEqual(missing, source)
        self.assertEqual(source, native)
        self.assertEqual(len(main_stamps(source)), 117)
        self.assertEqual({s["scale"]["x"] for s in main_stamps(source)}, {2.})
        self.assertEqual(len(source["holes3"]), 1)
        self.assertTrue(source["surfaceSplines2"])
        self.assertEqual(sum(len(g["Value"]["items"]) for g in source["placedObjects4"]), 2)

    def test_two_metre_spacing_keeps_exact_native_heights_osm_and_trees(self):
        fixture = self.fixture(plane=False)
        source = fixture.generate(self, "Source")
        sampled = fixture.generate(self, "2")
        self.assertEqual(len(main_stamps(sampled)), 35)
        self.assert_features_unchanged(source, sampled)
        native = stamp_map(source)
        coarse = stamp_map(sampled)
        xs = sorted({x for x, _ in native})
        zs = sorted({z for _, z in native})
        self.assertEqual(set(coarse), {(x, z) for x in xs[::2] for z in zs[::2]})
        self.assertEqual(len(coarse), len(main_stamps(sampled)), "Duplicate stamp center")
        for xy, stamp in coarse.items():
            self.assertEqual(stamp, native[xy])
        self.assertEqual({stamp["scale"]["x"] for stamp in coarse.values()}, {2.})

    def test_off_phase_last_row_and_column_are_preserved(self):
        fixture = self.fixture(rows=8, cols=10)
        source = fixture.generate(self, "Source")
        sampled = fixture.generate(self, 2.)
        native = stamp_map(source)
        xs, zs = sorted({x for x, _ in native}), sorted({z for _, z in native})
        expected_x = xs[::2] + [xs[-1]]
        expected_z = zs[::2] + [zs[-1]]
        self.assertEqual(len(main_stamps(sampled)), 30)
        self.assertEqual(set(stamp_map(sampled)), {(x, z) for x in expected_x for z in expected_z})
        for xy, stamp in stamp_map(sampled).items():
            self.assertEqual(stamp, native[xy])
        self.assert_features_unchanged(source, sampled)

    def test_fractional_spacing_samples_the_same_plane_in_the_same_frame(self):
        fixture = self.fixture()
        source = fixture.generate(self, "Source")
        sampled = fixture.generate(self, 1.5)
        native = stamp_map(source)
        x0, z0 = min(x for x, _ in native), min(z for _, z in native)
        expected = {(round(x0 + x, 9), round(z0 + z, 9))
                    for x in target_axis(12., 1.5) for z in target_axis(8., 1.5)}
        self.assertEqual(len(main_stamps(sampled)), 63)
        self.assertEqual(set(stamp_map(sampled)), expected)
        first = native[(x0, z0)]["value"]
        for stamp in main_stamps(sampled):
            x, z = position(stamp)
            self.assertAlmostEqual(stamp["value"], first + .013 * (x - x0) + .021 * (z - z0), delta=3e-5)
            self.assertEqual((stamp["scale"]["x"], stamp["scale"]["z"]), (2., 2.))
        self.assert_features_unchanged(source, sampled)

    def test_three_metre_spacing_raises_small_footprint_only(self):
        fixture = self.fixture()
        source = fixture.generate(self, "Source", brush_scale=3.)
        sampled = fixture.generate(self, 3., brush_scale=2.)
        native = stamp_map(source)
        xs, zs = sorted({x for x, _ in native}), sorted({z for _, z in native})
        expected_x, expected_z = xs[::3], zs[::3] + [zs[-1]]
        self.assertEqual(len(main_stamps(sampled)), 20)
        self.assertEqual(set(stamp_map(sampled)), {(x, z) for x in expected_x for z in expected_z})
        for xy, stamp in stamp_map(sampled).items():
            self.assertEqual(stamp, native[xy])
            self.assertEqual((stamp["scale"]["x"], stamp["scale"]["z"]), (3., 3.))
        self.assert_features_unchanged(source, sampled)

    def test_fractional_source_resolution_keeps_native_coordinates(self):
        fixture = self.fixture(source_spacing=1.5)
        source = fixture.generate(self, "Source", brush_scale=3.)
        sampled = fixture.generate(self, 3., brush_scale=3.)
        native = stamp_map(source)
        xs, zs = sorted({x for x, _ in native}), sorted({z for _, z in native})
        self.assertEqual(len(main_stamps(sampled)), 35)
        self.assertEqual(set(stamp_map(sampled)), {(x, z) for x in xs[::2] for z in zs[::2]})
        for xy, stamp in stamp_map(sampled).items():
            self.assertEqual(stamp, native[xy])
        self.assert_features_unchanged(source, sampled)

    def test_mask_edges_and_leading_nodata_keep_native_neighbors(self):
        fixture = self.fixture(rows=11, cols=15, holes=True, leading=True, plane=False)
        source = fixture.generate(self, "Source")
        sampled = fixture.generate(self, 2.)
        native, coarse = stamp_map(source), stamp_map(sampled)
        cloud = fixture.last_cloud[0]
        def cell_position(row, col):
            x, _, z = cloud.projToTGC(fixture.edge[0] + (col + .5) * fixture.scale,
                                     fixture.edge[1] + (row + .5) * fixture.scale, 0.)
            return (round(float(x), 9), round(float(z), 9))
        for row, col in np.argwhere(fixture.forbidden):
            self.assertNotIn(cell_position(row, col), coarse)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    rr, cc = int(row) + dy, int(col) + dx
                    if 0 <= rr < fixture.rows and 0 <= cc < fixture.cols and not fixture.forbidden[rr, cc]:
                        xy = cell_position(rr, cc)
                        if xy in native:
                            self.assertIn(xy, coarse, "Missing native 8-neighbor boundary sample")
        self.assertLess(len(coarse), len(native))
        for xy, stamp in coarse.items():
            self.assertIn(xy, native)
            self.assertEqual(stamp, native[xy])
        self.assert_features_unchanged(source, sampled)

    def test_spacing_does_not_change_vertical_normalization(self):
        fixture = self.fixture()
        source = fixture.generate(self, "Source")
        sampled = fixture.generate(self, 2.)
        native = stamp_map(source)
        for xy, stamp in stamp_map(sampled).items():
            self.assertEqual(stamp["value"], native[xy]["value"])
        # This slope deliberately exposed the old normalization hazard: using
        # only the sparse histogram shifted the entire course by another 2.1 cm.
        first = min(native)
        self.assertAlmostEqual(native[first]["value"], 9.979, delta=2e-5)

    def test_background_cartpath_and_landscape_stamps_are_unchanged(self):
        fixture = self.fixture(rows=21, cols=29, cartpath=True, plane=False)
        flags = {"brush_scale": 2., "add_background": True, "background_scale": 4.,
                 "auto_flatten_cartpaths": True, "auto_background_landscape": True,
                 "outside_background_resolution": 64.}
        source = fixture.generate(self, "Source", **flags)
        sampled = fixture.generate(self, 2., **flags)
        self.assert_features_unchanged(source, sampled)
        source_aux = [s for s in source["height"] if s["type"] != 72]
        sampled_aux = [s for s in sampled["height"] if s["type"] != 72]
        self.assertTrue(source_aux)
        self.assertTrue(any(s["scale"]["x"] == 10. for s in source_aux), "Coarse background was not exercised")
        self.assertTrue(any(s["scale"]["x"] != 10. for s in source_aux), "Cartpath flattening was not exercised")
        self.assertEqual(source_aux, sampled_aux)
        self.assertTrue(source["terrainHeight"])
        self.assertEqual(source["terrainHeight"], sampled["terrainHeight"])
        native = stamp_map(source)
        for xy, stamp in stamp_map(sampled).items():
            self.assertEqual(stamp, native[xy])

    def test_invalid_backend_spacing_stops_before_course_or_material_changes(self):
        fixture = self.fixture()
        for value in (.5, float("nan"), float("inf"), 7., "bad spacing"):
            with self.subTest(value=value):
                course = {"theme": 12, "surfaceSplines2": [{"original": "spline"}],
                          "holes3": [{"original": "hole"}], "placedObjects4": [{"original": "tree"}],
                          "surfaces2": [{"original": "material"}],
                          "height": [{"original": "terrain"}], "terrainHeight": []}
                before = copy.deepcopy(course)
                opts = dict(fixture.options, terrain_stamp_spacing=value)
                with patch.object(terrain.tree_profile_manager, "apply_visual_material_preset") as preset:
                    with self.assertRaises(ValueError):
                        terrain.generate_course(course, str(fixture.folder), options_dict=opts,
                                                course_version=25, printf=quiet)
                preset.assert_not_called()
                self.assertEqual(course, before)
                fixture.assert_source_unchanged(self)

    def test_graduated_background_keeps_all_three_tiers_and_heights(self):
        fixture = self.fixture(rows=128, cols=144, graduated=True, plane=False)
        flags = {"brush_scale": 2., "add_background": True, "graduated_background": True}
        source = fixture.generate(self, "Source", **flags)
        sampled = fixture.generate(self, 2., **flags)
        source_aux = [s for s in source["height"] if s["type"] == 10]
        sampled_aux = [s for s in sampled["height"] if s["type"] == 10]
        self.assertEqual({s["scale"]["x"] for s in source_aux}, {64., 32., 8.})
        self.assertEqual(source_aux, sampled_aux)
        self.assert_features_unchanged(source, sampled)
        native = stamp_map(source)
        self.assertLess(len(main_stamps(sampled)), len(native))
        for xy, stamp in stamp_map(sampled).items():
            self.assertEqual(stamp, native[xy])

    def gui_preflight(self, fixture, spacing):
        """Execute the installed import callback with no window or raster rewrite."""
        from tgc_terrain_sampling import resolve_stamp_spacing, resolve_brush_scale
        tree = ast.parse((ROOT / "tgc_gui.py").read_text(encoding="utf-8-sig"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "generateCourseFromLidar")
        class Variable:
            def __init__(self, value): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value
        options = {"terrain_stamp_spacing": Variable(spacing), "brush_scale": Variable("1"),
                   "lidar_trees": Variable(True), "use_osm": Variable(False)}
        alerts, calls, draw = [], [], []
        def generate(course, folder, **kwargs):
            calls.append((course, folder, copy.deepcopy(kwargs)))
            return course
        original = {"original": "loaded course"}
        env = {
            "np": np, "root": types.SimpleNamespace(filename=str(fixture.folder)),
            "tk": types.SimpleNamespace(filedialog=types.SimpleNamespace(askdirectory=lambda **kw: str(fixture.folder))),
            "course_json": original, "course_version": 25, "brush_scale_combo": {},
            "last_alignment_heightmap_dir": None, "alert": alerts.append,
            "refreshOSMMaskAlignmentStatus": quiet, "validateOSMMaskBeforeCourseImport": lambda *a: True,
            "drawPlaceholder": lambda: draw.append("placeholder"), "drawCourse": lambda *a: draw.append("course"),
            "tgc_image_terrain": types.SimpleNamespace(generate_course=generate),
            "resolve_stamp_spacing": resolve_stamp_spacing, "resolve_brush_scale": resolve_brush_scale,
        }
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "installed-GUI-import-callback", "exec"), env)
        env["generateCourseFromLidar"](options, quiet)
        self.assertIs(env["course_json"], original)
        self.assertEqual(original, {"original": "loaded course"})
        fixture.assert_source_unchanged(self)
        return env, options, alerts, calls, draw

    def test_gui_forwards_two_metre_stamps_with_one_metre_source_and_covered_footprint(self):
        fixture = self.fixture()
        env, options, alerts, calls, draw = self.gui_preflight(fixture, "2")
        self.assertEqual(alerts, [])
        self.assertEqual(len(calls), 1)
        sent = calls[0][2]["options_dict"]
        self.assertEqual(sent["terrain_stamp_spacing"], "2")
        self.assertEqual(float(sent["brush_scale"]), 2.)
        self.assertTrue(sent["lidar_trees"])
        self.assertEqual(env["brush_scale_combo"]["values"], ("2", "3", "4", "6"))
        self.assertEqual(draw, ["placeholder", "course"])

    def test_gui_invalid_spacing_never_calls_generation(self):
        fixture = self.fixture()
        for value in (".5", "nan", "7", "bad spacing"):
            with self.subTest(value=value):
                _, _, alerts, calls, draw = self.gui_preflight(fixture, value)
                self.assertTrue(alerts)
                self.assertEqual(calls, [])
                self.assertEqual(draw, [])

    def test_python311_and_build_gate(self):
        ast.parse(Path(__file__).read_text(encoding="utf-8-sig"), feature_version=(3, 11))
        builder = (ROOT / "BUILD_TGC_2K25_BETA8.py").read_text(encoding="utf-8-sig")
        self.assertIn("VERIFY_BETA8_5_TERRAIN_SPACING_PIPELINE.py", builder)
        self.assertIn("tgc_terrain_sampling", builder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
