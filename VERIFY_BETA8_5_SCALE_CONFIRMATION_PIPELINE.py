"""Headless behavior checks of the actual GUI source-confirmation routes.

Whole route definitions and their settings helpers are loaded from tgc_gui.py.
Raster/network work is recorded at its real boundary; the route functions,
queues, decision validation, and acquisition-to-local handoffs remain live.
"""
from __future__ import annotations

import ast
from collections import deque
import hashlib
import math
from pathlib import Path
import queue
import sys
import tempfile
import traceback
import types
import unittest
from unittest.mock import patch

import numpy as np

import tgc_source_scale as policy
import tgc_source_scale_ui as scale_ui


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


ROUTES = {
    "runLidar", "runDEM", "runLocalLidarTreesOnly", "runAwsEptLidar",
    "runUkLidarDem", "runLocalLidarTerrainGapFill", "runUnityRawSVG",
    "getAutoRedMaskSettings", "_mask_option_value",
}


def route_code():
    path = Path(__file__).resolve().with_name("tgc_gui.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ROUTES]
    missing = ROUTES - {node.name for node in functions}
    if missing:
        raise AssertionError("GUI route definitions missing: " + ", ".join(sorted(missing)))
    return compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec")


class Harness:
    def __init__(self, *, selection="Auto", cancel=False, acquisition_mode="full",
                 chooser_cancel=False, inspection_error=None):
        self.tmp = tempfile.TemporaryDirectory(prefix="tgc_scale_routes_")
        self.project = Path(self.tmp.name)
        self.osm = self.project / "course.osm"
        self.osm.write_text('<osm version="0.6"/>', encoding="utf-8")
        self.dem_path = self.project / "terrain.tif"
        self.dem_path.write_bytes(b"header inspected by the mocked metadata boundary")
        self.lidar_path = self.project / "lidar"
        self.lidar_path.mkdir()
        self.heightmap = self.project / "heightmap.npy"
        np.save(self.heightmap, {"heightmap": np.ones((4, 4, 1), np.float32),
                                "image_scale": 2.0, "source": "DEM",
                                "master_grid": {"resolution": 2.0}})
        self.original_heightmap = hashlib.sha256(self.heightmap.read_bytes()).hexdigest()
        self.selection = selection
        self.cancel = cancel
        self.acquisition_mode = acquisition_mode
        self.chooser_cancel = chooser_cancel
        self.inspection_error = inspection_error
        self.context = "main"
        self.events = []
        self.logs = []
        self.alerts = []
        self.pending = deque()
        self.decisions = []
        self.prepare_calls = []
        self.generate_calls = []
        self.tree_calls = []
        self.fill_calls = []
        self.inspection_calls = []
        self.confirm_calls = []
        self.pc = object()
        self.assessment = {"source_type": "LiDAR", "recommended_scale": 1.0,
                           "minimum_scale": 0.0, "reason": "Measured synthetic coverage",
                           "summary": "Synthetic source", "confidence": "high", "notes": []}
        self.dem_assessment = dict(self.assessment, source_type="DEM", minimum_scale=1.0)
        self.source = {"pc": self.pc, "scale_assessment": self.assessment}
        self.candidate = {"project": "Synthetic acquisition", "ql": "QL2",
                          "collect_start": "2020-01-01", "collect_end": "2020-12-31"}
        self.root = types.SimpleNamespace(filename=str(self.project), after=self.after)

        harness = self

        class Worker:
            def __init__(self, target, args=(), kwargs=None, **_options):
                self.target, self.args, self.kwargs = target, args, kwargs or {}

            def start(self):
                previous = harness.context
                harness.context = "worker"
                try:
                    self.target(*self.args, **self.kwargs)
                finally:
                    harness.context = previous

        lidar = types.SimpleNamespace(
            inspect_lidar_source=self.inspect_lidar,
            prepare_lidar_previews=self.prepare_lidar,
            show_prepared_lidar_preview=self.crop,
            generate_lidar_heightmap=self.generate_lidar,
            reframe_heightmap_to_osm_master=lambda *a, **k: self.record("reframe", "worker"),
            attach_lidar_trees_to_existing_dem=self.attach_trees,
            fill_missing_terrain_from_lidar=self.fill_terrain,
        )
        dem = types.SimpleNamespace(prepare_dem_previews=self.prepare_dem,
                                   show_prepared_dem_preview=self.crop,
                                   generate_dem_output=self.generate_dem)
        self.env = {
            "__builtins__": __builtins__, "__name__": "gui_scale_route_test",
            "root": self.root, "Path": Path, "math": math, "np": np,
            "queue": queue, "traceback": traceback,
            "threading": types.SimpleNamespace(Thread=Worker),
            "lidar_processing_active": False, "dem_processing_active": False,
            "AUTO_RED_MASK_BUFFER_DEFAULT_M": 5.0, "AUTO_RED_MASK_BUFFER_MIN_M": 5.0,
            "AUTO_RED_MASK_BUFFER_MAX_M": 30.0, "AWS_EPT_OSM_BUFFER_M": 150.0,
            "alert": self.alerts.append,
            "options_entries_dict": {"local_osm_file": Value(str(self.osm)),
                                     "course_name_filter": Value("Fair"),
                                     "custom_unmatched_osm": Value(False),
                                     "use_osm": Value(False), "adjust_ew": Value(2),
                                     "adjust_ns": Value(3)},
            "lidar_map_api": lidar, "dem_map_api": dem,
            "invalidateOSMMaskAlignmentAfterProcessing": lambda *a, **k: self.record("invalidate", "main"),
            "_apply_custom_unmatched_preview_overlay": lambda prepared, *a, **k: prepared,
            "showAwsEptDatasetChooser": self.aws_choose,
            "usgs_ept_downloader": types.SimpleNamespace(
                discover_osm_ept_candidates=self.aws_discover,
                download_candidate_ept_laz=self.aws_download),
            "tk": types.SimpleNamespace(filedialog=types.SimpleNamespace(
                askdirectory=lambda **k: str(self.lidar_path),
                askopenfilenames=lambda **k: (str(self.dem_path),))),
        }
        exec(route_code(), self.env)
        uk = types.ModuleType("uk_lidar_ui")
        uk.Value = Value
        uk.UKDownloadDialog = self.uk_dialog
        unity = types.ModuleType("tgc_unity_import_ui")
        unity.Value = Value
        unity.UnityImportDialog = self.unity_dialog
        self.patches = [
            patch.object(scale_ui, "confirm_source_scale", self.confirm),
            patch.object(scale_ui, "confirm_existing_grid", self.confirm_fixed),
            patch.object(policy, "inspect_dem_sources", self.inspect_dem),
            patch.dict(sys.modules, {"uk_lidar_ui": uk, "tgc_unity_import_ui": unity}),
        ]

    def __enter__(self):
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *_exc):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def record(self, name, expected_context):
        if self.context != expected_context:
            raise AssertionError("%s ran on %s instead of %s" % (name, self.context, expected_context))
        self.events.append(name)

    def after(self, _delay, callback):
        self.pending.append(callback)

    def drain(self):
        iterations = 0
        while self.pending:
            iterations += 1
            if iterations > 50:
                raise AssertionError("GUI worker pump did not terminate: " + repr(self.events))
            self.pending.popleft()()
        if self.alerts:
            raise AssertionError("Unexpected GUI errors: %r\n%s" % (self.alerts, "\n".join(self.logs)))

    def run(self, route, request="Auto"):
        value, epsg = Value(request), Value("2263")
        callback = self.env[route]
        if route == "runDEM":
            callback(value, self.logs.append, dem_files_override=[str(self.dem_path)])
        elif route == "runUnityRawSVG":
            callback(value, self.logs.append)
        elif route == "runLocalLidarTerrainGapFill":
            callback(epsg, self.logs.append, lidar_dir_path_override=str(self.lidar_path))
        else:
            callback(value, epsg, self.logs.append)

    def inspect_lidar(self, directory, **kwargs):
        self.record("inspect_lidar", "worker")
        self.inspection_calls.append((directory, kwargs))
        if self.inspection_error:
            raise ValueError(self.inspection_error)
        return self.source

    def inspect_dem(self, paths, **_kwargs):
        self.record("inspect_dem", "worker")
        if self.inspection_error:
            raise ValueError(self.inspection_error)
        return self.dem_assessment

    def confirm(self, parent, assessment, request="Auto", **kwargs):
        self.record("confirm", "main")
        self.confirm_calls.append((assessment, request, kwargs))
        if self.cancel:
            return None
        decision = policy.make_scale_decision(self.selection, assessment)
        decision["confirmed"] = True
        self.decisions.append(decision)
        return decision

    def confirm_fixed(self, parent, scale, **kwargs):
        self.record("confirm_fixed", "main")
        self.confirm_calls.append((None, scale, kwargs))
        if self.cancel:
            return None
        decision = {"mode": "existing_grid", "selected_scale": float(scale), "confirmed": True}
        self.decisions.append(decision)
        return decision

    def prepare_lidar(self, directory, scale, output_dir, **kwargs):
        self.record("prepare_lidar", "worker")
        self.prepare_calls.append((scale, kwargs))
        if kwargs.get("prepared_source") is not self.source:
            raise AssertionError("LiDAR preflight source was not reused")
        return {"pc": self.pc, "img_points": np.zeros((1, 5)), "sample_scale": scale,
                "output_dir_path": output_dir, "osm_result": None,
                "auto_red_mask_enabled": False, "auto_red_mask_buffer_m": 5.0,
                "scale_decision": kwargs["scale_decision"]}

    def prepare_dem(self, paths, **kwargs):
        self.record("prepare_dem", "worker")
        self.prepare_calls.append((kwargs["sample_scale"], kwargs))
        return {"image_scale": kwargs["sample_scale"],
                "source_scale_decision": kwargs["source_scale_decision"]}

    def crop(self, *_args, **_kwargs):
        self.record("crop", "main")
        return (0, 0, 4, 4)

    def generate_lidar(self, pc, points, scale, *_args, **kwargs):
        self.record("generate_lidar", "worker")
        self.generate_calls.append((scale, kwargs["scale_decision"]))

    def generate_dem(self, prepared, *_args, **_kwargs):
        self.record("generate_dem", "worker")
        self.generate_calls.append((prepared["image_scale"], prepared["source_scale_decision"]))

    def attach_trees(self, directory, heightmap, **kwargs):
        self.record("attach_trees", "worker")
        if kwargs.get("prepared_source") is not self.source:
            raise AssertionError("Tree-only source was read again instead of reused")
        self.tree_calls.append((directory, heightmap, kwargs))
        return 12

    def fill_terrain(self, directory, heightmap, **kwargs):
        self.record("fill_terrain", "worker")
        self.fill_calls.append((directory, heightmap, kwargs))
        return {"filled_cells": 4}

    def aws_discover(self, *_args, **_kwargs):
        self.record("aws_discover", "worker")
        return (-74, 40, -73, 41), [self.candidate]

    def aws_choose(self, candidates):
        self.record("aws_choose", "main")
        return (None, None) if self.chooser_cancel else (candidates[0], self.acquisition_mode)

    def aws_download(self, candidate, *_args, **_kwargs):
        self.record("aws_download", "worker")
        return str(self.lidar_path)

    def uk_dialog(self, parent, project, osm_file, **kwargs):
        self.record("uk_dialog", "main")

        def ready():
            # The actual UK dialog closes/releases the acquisition state before
            # invoking on_ready; follow the same public callback contract.
            kwargs["on_close"]()
            self.record("uk_download_done", "main")
            if self.chooser_cancel:
                return
            result = types.SimpleNamespace(files=[str(self.dem_path)], data_dir=str(self.lidar_path))
            dataset = types.SimpleNamespace(title="Synthetic ex-US", region="Test", source_page="source")
            kwargs["on_ready"](result, self.acquisition_mode, dataset)

        self.after(0, ready)

    def unity_dialog(self, parent, project, **kwargs):
        self.record("unity_dialog", "main")
        self.unity_initial_scale = kwargs["map_scale"]

        def ready():
            kwargs["on_close"]()
            if self.chooser_cancel:
                return
            self.record("unity_conversion_done", "main")
            kwargs["on_ready"]({"outputs": {"dem": str(self.dem_path), "osm": str(self.osm)},
                                "settings": {"output_spacing_m": 1.0}})

        self.after(0, ready)

    def assert_untouched(self, test):
        test.assertEqual(hashlib.sha256(self.heightmap.read_bytes()).hexdigest(), self.original_heightmap)


class ConfirmationRouteTests(unittest.TestCase):
    def assert_stopped(self, h):
        self.assertFalse(h.prepare_calls or h.generate_calls or h.tree_calls or h.fill_calls)
        self.assertFalse(h.env["lidar_processing_active"])
        self.assertFalse(h.env["dem_processing_active"])
        h.assert_untouched(self)

    def test_lidar_auto_pauses_after_inspection_before_rasterization(self):
        with Harness() as h:
            h.run("runLidar")
            self.assertEqual(h.events, ["inspect_lidar"])
            self.assertTrue(h.env["lidar_processing_active"])
            h.drain()
            self.assertEqual(h.events[:5], ["inspect_lidar", "confirm", "prepare_lidar", "crop", "generate_lidar"])
            self.assertEqual(h.generate_calls, [(1.0, h.decisions[0])])
            self.assertEqual(h.confirm_calls[0][1], "Auto")
            self.assertFalse(h.env["lidar_processing_active"])

    def test_lidar_cancel_does_not_prepare_or_write(self):
        with Harness(cancel=True) as h:
            h.run("runLidar")
            h.drain()
            self.assertEqual(h.events, ["inspect_lidar", "confirm"])
            self.assert_stopped(h)

    def test_lidar_manual_override_reaches_generation_with_decision(self):
        with Harness(selection="2") as h:
            h.run("runLidar")
            h.drain()
            self.assertEqual(h.prepare_calls[0][0], 2.0)
            self.assertEqual(h.generate_calls, [(2.0, h.decisions[0])])
            self.assertEqual(h.decisions[0]["mode"], "manual")
            self.assertEqual(len(h.inspection_calls), 1)

    def test_dem_auto_inspection_confirmation_and_generation_order(self):
        with Harness() as h:
            h.run("runDEM")
            self.assertEqual(h.events, ["inspect_dem"])
            h.drain()
            self.assertEqual(h.events[:5], ["inspect_dem", "confirm", "prepare_dem", "crop", "generate_dem"])
            self.assertEqual(h.generate_calls, [(1.0, h.decisions[0])])
            self.assertFalse(h.env["dem_processing_active"])

    def test_dem_cancel_does_not_prepare_or_write(self):
        with Harness(cancel=True) as h:
            h.run("runDEM")
            h.drain()
            self.assertEqual(h.events, ["inspect_dem", "confirm"])
            self.assert_stopped(h)

    def test_dem_manual_scale_and_decision_reach_final_output(self):
        with Harness(selection=2.5) as h:
            h.run("runDEM")
            h.drain()
            self.assertEqual(h.prepare_calls[0][0], 2.5)
            self.assertEqual(h.generate_calls, [(2.5, h.decisions[0])])
            self.assertEqual(h.decisions[0]["mode"], "manual")

    def test_source_inspection_failure_never_opens_confirmation(self):
        for route in ("runLidar", "runDEM"):
            with self.subTest(route=route), Harness(inspection_error="unusable source") as h:
                h.run(route)
                while h.pending:
                    h.pending.popleft()()
                self.assertTrue(h.alerts)
                self.assertFalse(h.confirm_calls)
                self.assert_stopped(h)

    def test_tree_only_manual_scale_keeps_existing_dem_grid(self):
        with Harness(selection=0.5) as h:
            h.run("runLocalLidarTreesOnly")
            self.assertEqual(h.events, ["inspect_lidar"])
            h.drain()
            self.assertEqual(h.events, ["inspect_lidar", "confirm", "attach_trees"])
            self.assertEqual(h.tree_calls[0][2]["sample_scale"], 0.5)
            self.assertEqual(h.tree_calls[0][2]["scale_decision"], h.decisions[0])
            self.assertEqual(h.confirm_calls[0][2]["operation"], "trees")
            self.assertFalse(h.generate_calls)
            h.assert_untouched(self)

    def test_tree_only_cancel_leaves_dem_and_trees_untouched(self):
        with Harness(cancel=True) as h:
            h.run("runLocalLidarTreesOnly")
            h.drain()
            self.assert_stopped(h)

    def test_gap_fill_confirms_and_retains_existing_resolution(self):
        with Harness() as h:
            h.run("runLocalLidarTerrainGapFill")
            h.drain()
            self.assertEqual(h.events[:2], ["confirm_fixed", "fill_terrain"])
            self.assertEqual(h.confirm_calls[0][1], 2.0)
            self.assertNotIn("sample_scale", h.fill_calls[0][2])
            self.assertFalse(h.prepare_calls or h.generate_calls)
            h.assert_untouched(self)

    def test_gap_fill_cancel_prevents_fallback_processing(self):
        with Harness(cancel=True) as h:
            h.run("runLocalLidarTerrainGapFill")
            h.drain()
            self.assertEqual(h.events, ["confirm_fixed"])
            self.assert_stopped(h)

    def test_aws_all_modes_use_local_source_confirmation(self):
        for mode, endpoint in (("full", "generate_lidar"), ("trees", "attach_trees"), ("gap_fill", "fill_terrain")):
            for cancel in (False, True):
                with self.subTest(mode=mode, cancel=cancel), Harness(acquisition_mode=mode, cancel=cancel) as h:
                    h.run("runAwsEptLidar")
                    h.drain()
                    confirm = "confirm_fixed" if mode == "gap_fill" else "confirm"
                    self.assertLess(h.events.index("aws_download"), h.events.index(confirm))
                    self.assertEqual(h.events.count(confirm), 1)
                    if cancel:
                        self.assert_stopped(h)
                    else:
                        self.assertLess(h.events.index(confirm), h.events.index(endpoint))
                        if mode != "gap_fill":
                            self.assertIsNone(h.inspection_calls[0][1]["force_epsg"])
                            self.assertEqual(h.inspection_calls[0][1]["source_metadata"], h.candidate)

    def test_exus_all_modes_use_local_source_confirmation(self):
        for mode, endpoint in (("dem", "generate_dem"), ("lidar", "generate_lidar"), ("trees", "attach_trees")):
            for cancel in (False, True):
                with self.subTest(mode=mode, cancel=cancel), Harness(acquisition_mode=mode, cancel=cancel) as h:
                    h.run("runUkLidarDem")
                    h.drain()
                    self.assertLess(h.events.index("uk_download_done"), h.events.index("confirm"))
                    self.assertEqual(h.confirm_calls[0][1], "Auto")
                    if cancel:
                        self.assert_stopped(h)
                    else:
                        self.assertLess(h.events.index("confirm"), h.events.index(endpoint))
                        if mode != "dem":
                            self.assertIsNone(h.inspection_calls[0][1]["force_epsg"])

    def test_acquisition_cancel_does_not_inspect_or_process_data(self):
        for route in ("runAwsEptLidar", "runUkLidarDem", "runUnityRawSVG"):
            with self.subTest(route=route), Harness(chooser_cancel=True) as h:
                h.run(route)
                h.drain()
                self.assertFalse(h.confirm_calls or h.inspection_calls)
                self.assert_stopped(h)

    def test_unity_auto_reaches_dem_confirmation_before_heightmap(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), Harness(selection=2.0, cancel=cancel) as h:
                h.run("runUnityRawSVG")
                h.drain()
                self.assertEqual(h.unity_initial_scale, "Auto")
                self.assertLess(h.events.index("unity_conversion_done"), h.events.index("inspect_dem"))
                self.assertLess(h.events.index("inspect_dem"), h.events.index("confirm"))
                self.assertEqual(h.confirm_calls[0][1], "Auto")
                if cancel:
                    self.assert_stopped(h)
                else:
                    self.assertEqual(h.generate_calls, [(2.0, h.decisions[0])])
                    self.assertEqual(h.env["options_entries_dict"]["adjust_ew"].get(), 0.0)
                    self.assertEqual(h.env["options_entries_dict"]["adjust_ns"].get(), 0.0)

    def test_any_active_terrain_job_blocks_new_import_routes(self):
        routes = sorted(ROUTES - {"getAutoRedMaskSettings", "_mask_option_value"})
        for route in routes:
            for flag in ("lidar_processing_active", "dem_processing_active"):
                with self.subTest(route=route, active=flag), Harness() as h:
                    h.env[flag] = True
                    h.run(route)
                    self.assertTrue(h.alerts, "The busy import was not reported")
                    self.assertFalse(h.events or h.pending or h.confirm_calls)
                    self.assertTrue(h.env[flag], "An unrelated active job was released")
                    h.assert_untouched(self)


if __name__ == "__main__":
    unittest.main(verbosity=2)
