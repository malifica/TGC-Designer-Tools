"""Headless pre-build checks for Beta 8.5 hillshade defaults. Requires only NumPy and SciPy.

TGC_BETA8_5_HILLSHADE_DEFAULTS_V1
No Tk window, OpenCV, PyProj, project data, Git checkout, or Windows EXE is used.
The original hillshade is not compared against a fixed published source hash:
legitimate local edits to that original renderer are allowed.
"""
import ast
import importlib.util
import math
from pathlib import Path
import queue
import sys
import traceback
import types
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parent
PATCH_ID = "TGC_BETA8_5_HILLSHADE_DEFAULTS_V1"
spec = importlib.util.spec_from_file_location("_hillshade2_verified_renderer", ROOT / "tgc_hillshade2.py")
hs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hs)
VIEWER_SOURCE = (ROOT / "osm_alignment_viewer.py").read_text(encoding="utf-8-sig")
VIEWER_TREE = ast.parse(VIEWER_SOURCE)
VIEWER_CLASS = next(node for node in VIEWER_TREE.body
                    if isinstance(node, ast.ClassDef) and node.name == "AlignmentViewer")


class NumericalTests(unittest.TestCase):
    def test_flat_and_regional_plane_are_neutral(self):
        y, x = np.mgrid[:160, :200]
        for height in (np.full((160, 200), 457.25), 100 + 0.08 * x + 0.13 * y):
            self.assertTrue(np.all(hs.terrain_relief2(height, 1) == hs.NEUTRAL_GRAY))

    def test_depressions_mounds_and_slope_invariance(self):
        y, x = np.mgrid[:201, :201].astype(float)
        pit = -1.5 * np.exp(-((x - 100) ** 2 + (y - 100) ** 2) / (2 * 6 ** 2))
        a = hs.terrain_relief2(pit, 1)
        b = hs.terrain_relief2(-pit, 1)
        self.assertLess(int(a[100, 100, 0]), 120)
        self.assertGreater(int(b[100, 100, 0]), 144)
        tilted = hs.terrain_relief2(pit + 0.12 * x + 0.08 * y + 1200, 1)
        self.assertLessEqual(int(np.max(np.abs(a.astype(int) - tilted.astype(int)))), 1)

    def test_source_preservation_and_nodata(self):
        height = np.arange(99, dtype=np.float64).reshape(9, 11)
        height[1, 2], height[3, 5], height[4, 6] = np.nan, np.inf, -np.inf
        before = height.tobytes()
        result = hs.terrain_relief2(height, 1)
        self.assertEqual(before, height.tobytes())
        self.assertEqual(result.shape, (9, 11, 3))
        self.assertEqual(result.dtype, np.uint8)
        self.assertTrue(np.all(result[~np.isfinite(height)] == hs.NEUTRAL_GRAY))
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 2])

    def test_empty_tiny_and_invalid_inputs(self):
        for shape in ((0, 4), (4, 0), (1, 1), (1, 31), (31, 1)):
            self.assertEqual(hs.terrain_relief2(np.zeros(shape), 2).shape, shape + (3,))
        self.assertTrue(np.all(hs.terrain_relief2(np.full((12, 9), np.nan), 1) == hs.NEUTRAL_GRAY))
        self.assertEqual(hs.terrain_relief2(np.zeros((1, 19, 1)), 1).shape, (1, 19, 3))
        for value in (0, -1, np.nan, np.inf, None, "bad"):
            with self.assertRaises(ValueError):
                hs.terrain_relief2(np.zeros((5, 5)), value)

    def test_tiny_noise_is_not_contrast_stretched(self):
        height = np.random.default_rng(7).normal(0, 0.002, (128, 128))
        result = hs.terrain_relief2(height, 1)[:, :, 0]
        self.assertLess(float(result.std()), 1.0)
        self.assertLess(int(result.max()) - int(result.min()), 5)

    def test_metre_scaling_and_high_absolute_elevation(self):
        y, x = np.mgrid[-60:61, -60:61]
        height = -1.5 * np.exp(-(x * x + y * y) / (2 * 6 ** 2))
        a = hs.terrain_relief2(height, 1)
        y2, x2 = np.mgrid[-60:60.1:.5, -60:60.1:.5]
        h2 = -1.5 * np.exp(-(x2 * x2 + y2 * y2) / (2 * 6 ** 2))
        b = hs.terrain_relief2(h2, .5)[::2, ::2]
        self.assertLess(float(np.mean(np.abs(a.astype(float) - b.astype(float)))), 1.0)
        elevated = hs.terrain_relief2(height + 1e8, 1)
        self.assertLessEqual(int(np.max(np.abs(a.astype(int) - elevated.astype(int)))), 1)


class Variable:
    def __init__(self, value):
        self.value = value
        self.reads = 0

    def get(self):
        self.reads += 1
        return self.value

    def set(self, value):
        self.value = value


class Window:
    def __init__(self):
        self.calls = []

    def after(self, *args):
        self.calls.append(args)
        return len(self.calls)


class IntegrationTests(unittest.TestCase):
    """Execute installed viewer methods with lightweight non-Tk objects."""
    def setUp(self):
        self.jobs, self.errors, self.opened = [], [], []
        jobs, errors = self.jobs, self.errors

        class Thread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                jobs.append(self)

        methods = {"_start_hillshade2", "_pump_hillshade2_queue", "_view_changed",
                   "_current_background", "_open_local_alignment", "_can_interact", "_pump_load_queue"}
        body = [node for node in VIEWER_CLASS.body
                if isinstance(node, ast.FunctionDef) and node.name in methods]
        self.assertEqual({node.name for node in body}, methods)
        node = ast.ClassDef(name="TestViewer", bases=[], keywords=[], body=body, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        env = {"np": np, "queue": queue, "traceback": traceback, "math": math,
               "threading": types.SimpleNamespace(Thread=Thread),
               "messagebox": types.SimpleNamespace(
                   showerror=lambda *args, **kwargs: errors.append((args, kwargs)),
                   showinfo=lambda *args, **kwargs: None)}
        exec(compile(module, "installed-viewer-methods", "exec"), env)
        self.Viewer = env["TestViewer"]
        renderer = types.ModuleType("tgc_hillshade2")
        renderer.terrain_relief2 = lambda heightmap, resolution: self.result(heightmap.shape)
        ui = types.ModuleType("tgc_local_alignment_ui")
        ui.open_local_alignment = self.opened.append
        style = types.ModuleType("tgc_ui_style")
        style.wrap_local_alignment = lambda callback: callback
        self.modules = patch.dict(sys.modules, {
            "tgc_hillshade2": renderer, "tgc_local_alignment_ui": ui, "tgc_ui_style": style})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    @staticmethod
    def result(shape=(4, 5)):
        return np.arange(int(np.prod(shape)) * 3, dtype=np.uint8).reshape(shape + (3,))

    def viewer(self):
        viewer = self.Viewer()
        viewer.ready, viewer.busy, viewer.closed = True, False, False
        viewer.local_review = None
        viewer.rows, viewer.cols, viewer.resolution = 4, 5, 2.0
        viewer.heightmap = np.arange(20, dtype=np.float32).reshape(4, 5)
        viewer.relief2_rgb = None
        viewer._hillshade2_queue = queue.Queue()
        viewer._load_queue = queue.Queue()
        viewer.loading = False
        viewer._hillshade2_loading = False
        viewer._hillshade2_open_review_when_ready = False
        viewer.backgrounds = {"Hillshade 2": np.flipud(200 - self.result()),
                              "Visual": np.full((4, 5, 3), 50, dtype=np.uint8)}
        viewer.blend_rgb = np.full((4, 5, 3), 17, dtype=np.uint8)
        viewer.view_var = Variable("Hillshade 1")
        viewer.window = Window()
        viewer.canvas = types.SimpleNamespace(focus_set=lambda: None)
        viewer._cfs_background_cache = {"Hillshade 1": "old-pending", "Visual": "retain"}
        viewer._cfs_last_tile_key = ("old",)
        viewer.progress, viewer.logs, viewer.redraws = [], [], []
        viewer._set_progress = lambda *args: viewer.progress.append(args)
        viewer.printf = viewer.logs.append
        viewer._redraw_background = lambda: viewer.redraws.append(viewer.view_var.value)
        viewer._redraw_overlay = lambda: None
        viewer._redraw_everything = viewer._redraw_background
        viewer._choose_initial_zoom = lambda: None
        viewer._set_controls_enabled = lambda enabled: None
        viewer.custom_unmatched_osm = False
        viewer.ew_var, viewer.ns_var = Variable("0.00"), Variable("0.00")
        viewer.shift_ew, viewer.shift_ns = 0.0, 0.0
        return viewer

    def select_new_mode(self, viewer):
        viewer.view_var.set("Hillshade 1")
        viewer._view_changed()

    def finish(self, viewer):
        self.jobs[-1].target()
        viewer._pump_hillshade2_queue()

    def test_single_worker_and_pending_orientation(self):
        viewer = self.viewer()
        viewer.ready = False
        viewer._start_hillshade2()
        self.assertFalse(self.jobs, "Renderer must wait until terrain is loaded")
        viewer.ready = True
        self.select_new_mode(viewer)
        viewer._view_changed()
        self.assertEqual(len(self.jobs), 1)
        self.assertTrue(viewer._hillshade2_loading)
        self.assertIs(viewer._current_background(), viewer.backgrounds["Hillshade 2"])
        np.testing.assert_array_equal(viewer._current_background(), np.flipud(200 - self.result()))

    def test_ready_startup_generates_default_without_selection_event(self):
        viewer = self.viewer()
        viewer.ready, viewer.loading = False, True
        viewer.backgrounds = {}
        heightmap = viewer.heightmap.copy()
        legacy = 200 - self.result()
        payload = dict(data={"heightmap": heightmap}, heightmap=heightmap,
                       resolution=2.0, projection="test", grid={}, osm_result=None,
                       features=[], visual_rgb=np.full((4, 5, 3), 50, dtype=np.uint8),
                       relief_rgb=legacy, blend_rgb=np.full((4, 5, 3), 70, dtype=np.uint8))
        viewer._load_queue.put(("done", payload))
        viewer._pump_load_queue()
        self.assertTrue(viewer.ready)
        self.assertFalse(viewer.loading)
        self.assertEqual(viewer.view_var.value, "Hillshade 1")
        self.assertEqual(len(self.jobs), 1, "Default must render without a ComboboxSelected event")
        self.assertTrue(viewer._hillshade2_loading)
        self.assertNotIn("Hillshade 1", viewer.backgrounds)
        np.testing.assert_array_equal(viewer.backgrounds["Hillshade 2"], np.flipud(legacy))
        self.assertIn("Generating Hillshade 1", viewer.progress[-1][1])
        self.assertIs(viewer._current_background(), viewer.backgrounds["Hillshade 2"])
        viewer._start_hillshade2()
        viewer._view_changed()
        self.assertEqual(len(self.jobs), 1, "Default startup and selection must share one job")
        self.finish(viewer)
        np.testing.assert_array_equal(viewer.backgrounds["Hillshade 1"], np.flipud(self.result()))
        np.testing.assert_array_equal(viewer.backgrounds["Hillshade 2"], np.flipud(legacy))
        np.testing.assert_array_equal(viewer.heightmap, heightmap)
        self.assertEqual(viewer.view_var.value, "Hillshade 1")

    def test_completed_image_flips_once_and_invalidates_cache(self):
        viewer = self.viewer()
        source, original = viewer.heightmap.copy(), viewer.backgrounds["Hillshade 2"].copy()
        self.select_new_mode(viewer)
        scheduled = len(viewer.window.calls)
        self.jobs[-1].target()
        self.assertEqual(len(viewer.window.calls), scheduled, "Worker must not call Tk")
        viewer._pump_hillshade2_queue()
        np.testing.assert_array_equal(viewer.backgrounds["Hillshade 1"], np.flipud(self.result()))
        np.testing.assert_array_equal(viewer.heightmap, source)
        np.testing.assert_array_equal(viewer.backgrounds["Hillshade 2"], original)
        self.assertNotIn("Hillshade 1", viewer._cfs_background_cache)
        self.assertEqual(viewer._cfs_background_cache["Visual"], "retain")
        self.assertIsNone(viewer._cfs_last_tile_key)
        self.assertFalse(viewer._hillshade2_loading)
        viewer._start_hillshade2()
        self.assertEqual(len(self.jobs), 1, "Cached layer must not be regenerated")

    def test_switching_away_preserves_selected_view(self):
        viewer = self.viewer()
        self.select_new_mode(viewer)
        viewer.view_var.set("Visual")
        viewer._view_changed()
        redraws = len(viewer.redraws)
        self.finish(viewer)
        self.assertEqual(viewer.view_var.value, "Visual")
        self.assertEqual(len(viewer.redraws), redraws)

    def test_invalid_shape_and_dtype_return_to_original(self):
        for payload in (np.zeros((4, 5), np.uint8), np.zeros((4, 5, 3), np.float32), None):
            viewer = self.viewer()
            viewer.view_var.set("Hillshade 1")
            viewer._hillshade2_loading = True
            viewer._hillshade2_queue.put(("done", payload))
            viewer._pump_hillshade2_queue()
            self.assertEqual(viewer.view_var.value, "Hillshade 2")
            self.assertFalse(viewer._hillshade2_loading)
            self.assertNotIn("Hillshade 1", viewer.backgrounds)

    def test_failure_then_retry(self):
        viewer = self.viewer()
        viewer.view_var.set("Hillshade 1")
        viewer._hillshade2_loading = True
        viewer._hillshade2_queue.put(("error", "test failure"))
        viewer._pump_hillshade2_queue()
        self.assertEqual(viewer.view_var.value, "Hillshade 2")
        self.assertFalse(viewer._hillshade2_loading)
        self.assertTrue(self.errors)
        self.select_new_mode(viewer)
        self.finish(viewer)
        self.assertIn("Hillshade 1", viewer.backgrounds)

    def test_close_ignores_worker_result_before_tk_access(self):
        viewer = self.viewer()
        viewer.closed = True
        viewer._hillshade2_queue.put(("done", self.result()))
        viewer._pump_hillshade2_queue()
        self.assertEqual(viewer._hillshade2_queue.qsize(), 1)
        self.assertEqual(viewer.view_var.reads, 0)
        self.assertFalse(viewer.window.calls or viewer.redraws or viewer.progress or self.errors)

    def test_busy_mask_progress_is_preserved(self):
        for kind, payload in (("done", self.result()), ("error", "test busy failure")):
            viewer = self.viewer()
            self.select_new_mode(viewer)
            viewer.busy = True
            progress = list(viewer.progress)
            viewer._hillshade2_queue.put((kind, payload))
            viewer._pump_hillshade2_queue()
            self.assertEqual(viewer.progress, progress)

    def test_local_review_waits_from_every_mode_and_survives_switching(self):
        modes = ("Hillshade 1", "Hillshade 2", "Visual", "Blend")
        for index, mode in enumerate(modes):
            viewer = self.viewer()
            viewer.view_var.set(mode)
            before_jobs, before_open = len(self.jobs), len(self.opened)
            viewer._open_local_alignment()
            self.assertEqual(len(self.opened), before_open)
            self.assertTrue(viewer._hillshade2_open_review_when_ready)
            self.assertEqual(len(self.jobs), before_jobs + 1)
            changed_mode = modes[(index + 1) % len(modes)]
            viewer.view_var.set(changed_mode)
            viewer._view_changed()
            self.assertTrue(viewer._hillshade2_open_review_when_ready,
                            "Changing main view must not cancel requested local review")
            self.assertEqual(len(self.jobs), before_jobs + 1)
            self.finish(viewer)
            self.assertEqual(len(self.opened), before_open + 1)
            self.assertIs(self.opened[-1], viewer)
            self.assertFalse(viewer._hillshade2_open_review_when_ready)
            self.assertEqual(viewer.view_var.value, changed_mode)
            self.assertIn("Hillshade 1", viewer.backgrounds)

    def test_ready_local_review_opens_from_every_main_mode(self):
        for mode in ("Hillshade 1", "Hillshade 2", "Visual", "Blend"):
            viewer = self.viewer()
            viewer.backgrounds["Hillshade 1"] = np.flipud(self.result())
            viewer.view_var.set(mode)
            before_jobs, before_open = len(self.jobs), len(self.opened)
            viewer._open_local_alignment()
            self.assertEqual(len(self.jobs), before_jobs)
            self.assertEqual(len(self.opened), before_open + 1)
            self.assertIs(self.opened[-1], viewer)
            self.assertEqual(viewer.view_var.value, mode)

    def test_local_review_always_uses_hillshade_one(self):
        tree = ast.parse((ROOT / "tgc_local_alignment_ui.py").read_text(encoding="utf-8-sig"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LocalAlignmentDialog")
        init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        selected = [node for node in init.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            and target.value.id == "self" and target.attr == "background" for target in node.targets)]
        self.assertEqual(len(selected), 1)
        body = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
        for mode in ("Hillshade 1", "Hillshade 2", "Visual", "Blend", None):
            viewer = types.SimpleNamespace(backgrounds={"Hillshade 2": self.result(), "Hillshade 1": np.flipud(self.result())})
            if mode is not None:
                viewer.view_var = Variable(mode)
            dialog = types.SimpleNamespace()
            image = types.SimpleNamespace(fromarray=lambda array, mode: array.copy())
            exec(compile(body, "installed-local-background", "exec"), {"self": dialog, "viewer": viewer, "Image": image})
            np.testing.assert_array_equal(dialog.background, viewer.backgrounds["Hillshade 1"])


class WiringTests(unittest.TestCase):
    def test_dropdown_default_and_deferred_startup(self):
        self.assertIn('value="Hillshade 1"', VIEWER_SOURCE)
        self.assertIn('"Hillshade 2"', VIEWER_SOURCE)
        self.assertIn("viewport_tile", VIEWER_SOURCE)
        self.assertIn(PATCH_ID, VIEWER_SOURCE)
        self.assertTrue(any(isinstance(node, ast.FunctionDef) and node.name == "_terrain_relief" for node in VIEWER_TREE.body))
        for name in ("__init__", "_load_worker"):
            node = next(node for node in VIEWER_CLASS.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertFalse(any(isinstance(child, ast.Call) and
                ((isinstance(child.func, ast.Attribute) and child.func.attr == "_start_hillshade2") or
                 (isinstance(child.func, ast.Name) and child.func.id == "terrain_relief2")) for child in ast.walk(node)))
        ready_pump = next(node for node in VIEWER_CLASS.body if isinstance(node, ast.FunctionDef) and node.name == "_pump_load_queue")
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "_start_hillshade2" for node in ast.walk(ready_pump)))

    def test_build_contains_hidden_import_and_frozen_module_check(self):
        source = (ROOT / "BUILD_TGC_2K25_BETA8.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_arguments")
        constants = [node.value for node in ast.walk(build) if isinstance(node, ast.Constant)]
        self.assertIn("--hidden-import", constants)
        self.assertIn("tgc_hillshade2", constants)
        self.assertIn(PATCH_ID, source)
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "required"
            and node.func.attr in {"add", "update"}
            and any(isinstance(child, ast.Constant) and child.value == "tgc_hillshade2" for child in ast.walk(node))
            for node in ast.walk(tree)))


    @staticmethod
    def source_values(name):
        values = {}
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            value = node.value
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, TypeError):
                if (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)
                        and isinstance(value.left, ast.Name) and value.left.id in values
                        and isinstance(value.right, ast.Constant) and isinstance(value.right.value, str)
                        and isinstance(values[value.left.id], str)):
                    parsed = values[value.left.id] + value.right.value
                else:
                    continue
            values[node.targets[0].id] = parsed
        return values

    def test_exact_beta85_gui_and_build_identity(self):
        gui = self.source_values("tgc_gui.py")
        wrapper = self.source_values("BUILD_TGC_2K25_BETA8_5.py")
        self.assertEqual(gui["TGC_GUI_VERSION"], "v0.5.0-2k25-beta8.5")
        self.assertEqual(gui["TGC_APP_TITLE"], "TGC Designer Tools 2K25 - Beta 8.5")
        self.assertEqual(wrapper["VERSION"], gui["TGC_GUI_VERSION"])
        self.assertEqual(wrapper["APP_TITLE"], gui["TGC_APP_TITLE"])
        self.assertEqual(wrapper["EXE_NAME"], "tgc_gui_2k25_beta8_5")
        self.assertEqual(wrapper["RELEASE_MARKER"], PATCH_ID)
        tree = ast.parse((ROOT / "BUILD_TGC_2K25_BETA8_5.py").read_text(encoding="utf-8-sig"))
        call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "build")
        keywords = {item.arg: item.value for item in call.keywords}
        for name in ("parking_release", "open_island_release", "graduated_release", "hillshade_release"):
            self.assertIs(ast.literal_eval(keywords[name]), True, name + " gate must stay enabled")

    def test_beta85_receipt_identity_and_retained_beta84_identity(self):
        current = self.source_values("COLLECT_BETA8_5_FOR_PUBLICATION.py")
        old = self.source_values("COLLECT_BETA8_4_FOR_PUBLICATION.py")
        self.assertEqual(current["VERSION"], "v0.5.0-2k25-beta8.5")
        self.assertEqual(current["EXE"], "dist/tgc_gui_2k25_beta8_5.exe")
        self.assertEqual(current["RECEIPT"], current["EXE"] + ".build.json")
        self.assertEqual(current["CHECKSUM"], current["EXE"] + ".sha256.txt")
        self.assertEqual(old["VERSION"], "v0.5.0-2k25-beta8.4")
        self.assertEqual(old["EXE"], "dist/tgc_gui_2k25_beta8_4.exe")
        self.assertEqual(old["RECEIPT"], old["EXE"] + ".build.json")
        required = {"tgc_hillshade2.py", "osm_alignment_viewer.py", "tgc_local_alignment_ui.py",
                    "VERIFY_BETA8_5_HILLSHADE.py", "BUILD_TGC_2K25_BETA8_5.py", "BUILD_TGC_2K25_BETA8_5.bat",
                    "COLLECT_BETA8_5_FOR_PUBLICATION.py", "RELEASE_NOTES_v0.5.0-2k25-beta8.5.md",
                    "VERIFY_BETA8_4_GRADUATED_BACKGROUND.py", "VERIFY_OPEN_SURFACE_ISLANDS.py",
                    "VERIFY_OPEN_ISLAND_MASK.py", "VERIFY_BETA8_2_PARKING.py", "VERIFY_BETA8_OSM_WOODS_V1.py"}
        self.assertTrue(required.issubset(set(current["REQUIRED"])), required - set(current["REQUIRED"]))


if __name__ == "__main__":
    print("Beta 8.5 hillshade verification (headless; original renderer edits preserved).", flush=True)
    unittest.main(verbosity=2)
