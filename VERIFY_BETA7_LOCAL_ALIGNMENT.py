"""Independent local-alignment integration checks.

Default checks use analytical terrain and private temporary OSM copies. --gui
adds real Tk worker/review/save/cancel checks (a display is required). Optional
--bootleg-heightmap/--bootleg-osm/--regression-json compare the supplied course
with the prior reviewed prototype; those personal files are not bundled.

This does not run Windows, PyInstaller, or the PGA Tour 2K25 game. The native
OSM importer and mask renderer are exercised. Main-window route tests execute
the actual named functions from their AST, avoiding application startup; the
final terrain-generation call is captured rather than creating a game course.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import overpy
import pyproj

from GeoPointCloud import GeoPointCloud
import OSMTGC
import osm_alignment_viewer as viewer_module
import osm_mask_alignment as mask_module
import tgc_local_alignment as engine
from tgc_cfs_display import importer_transformer

ROOT = Path(__file__).resolve().parent


def fixture(folder, nudge=(1.5, -1.0)):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    resolution, size = 2.0, 96
    xx, yy = np.meshgrid((np.arange(size) + .5) * resolution,
                         (np.arange(size) + .5) * resolution)
    radial = np.hypot(xx - 80., yy - 80.)
    t = np.clip((12. - radial) / 4., 0., 1.)
    z = 100. - 2. * t * t * (3. - 2. * t) + .25 * np.exp(-.5 * ((radial - 12.) / 1.) ** 2)
    projection = pyproj.Proj("EPSG:32611")
    forward = importer_transformer(projection)
    min_x, min_y = 575641., 5497180.
    lon0, lat0 = forward.transform(min_x, min_y, direction="INVERSE")
    grid = dict(version=1, rows=size, cols=size, resolution=resolution,
                min_x=min_x, min_y=min_y, max_x=min_x + size * resolution,
                max_y=min_y + size * resolution, crs_wkt=projection.crs.to_wkt(),
                horizontal_epsg=32611, origin_semantics="southwest_cell_edge",
                row_order="south_up_internal", xy_units="meters",
                lower_left_latlon=[lat0, lon0])
    data = dict(heightmap=z, image_scale=resolution, master_grid=grid,
                projection=projection, origin=(lat0, lon0))
    angle = np.linspace(0, 2*np.pi, 96, endpoint=False)
    target = np.column_stack([80.+12.*np.cos(angle), 80.+12.*np.sin(angle)])
    original = target + np.array([3., -2.]) - np.asarray(nudge)
    root = ET.Element("osm", version="0.6", generator="Independent local alignment fixture")
    for i, (x, y) in enumerate(original, 1):
        lon, lat = forward.transform(x+min_x, y+min_y, direction="INVERSE")
        ET.SubElement(root, "node", id=str(i), lon=f"{lon:.12f}", lat=f"{lat:.12f}", version="1")
    way = ET.SubElement(root, "way", id="101", version="1")
    for i in list(range(1, 97)) + [1]:
        ET.SubElement(way, "nd", ref=str(i))
    ET.SubElement(way, "tag", k="golf", v="bunker")
    ET.SubElement(way, "tag", k="name", v="Synthetic rim")
    # Unrelated data must survive export without coordinate or tag edits.
    ET.SubElement(root, "node", id="999", lon=f"{lon0:.12f}", lat=f"{lat0:.12f}", version="7")
    source = folder / "source.osm"
    ET.ElementTree(root).write(source, encoding="utf-8", xml_declaration=True)
    np.save(folder / "heightmap.npy", data)
    return data, source, tuple(nudge), target


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value
    def delete(self, first, last=None): self.value = ""
    def insert(self, index, value): self.value = value


def main_harness(folder, source, nudge, root=None):
    """Run actual main-window route functions without importing app startup."""
    folder = Path(folder)
    root = root or types.SimpleNamespace()
    root.filename = str(folder)
    captured, statuses, generated = {}, [], []
    options = {key: Value(value) for key, value in {
        "use_osm": True, "local_osm_file": str(source), "adjust_ew": str(nudge[0]),
        "adjust_ns": str(nudge[1]), "auto_red_mask_enabled": True,
        "auto_red_mask_buffer_m": 5., "road": False,
        "custom_unmatched_osm": False, "brush_scale": "2"}.items()}
    def opener(*args, **kwargs): captured.update(args=args, kwargs=kwargs)
    def generator(course, path, **kwargs):
        generated.append({"heightmap": path, **kwargs})
        return course
    environment = dict(root=root, Path=Path, np=np, math=math,
        AUTO_RED_MASK_BUFFER_DEFAULT_M=5., AUTO_RED_MASK_BUFFER_MIN_M=5.,
        AUTO_RED_MASK_BUFFER_MAX_M=30., last_alignment_heightmap_dir=None,
        tk=types.SimpleNamespace(filedialog=types.SimpleNamespace(askdirectory=lambda **_: str(folder))),
        alert=lambda message: (_ for _ in ()).throw(AssertionError(message)),
        _setOSMMaskStatus=lambda *message: statuses.append(message),
        _markOSMMaskCurrentAfterRebuild=lambda *_, **__: statuses.append(("CURRENT",)),
        osm_alignment_viewer=types.SimpleNamespace(open_alignment_viewer=opener),
        osm_mask_alignment=mask_module, course_json={}, course_version=25, brush_scale_combo=None,
        drawPlaceholder=lambda: None, drawCourse=lambda _: None,
        refreshOSMMaskAlignmentStatus=lambda *_, **__: None,
        tgc_image_terrain=types.SimpleNamespace(generate_course=generator))
    tree = ast.parse((ROOT / "tgc_gui.py").read_text(encoding="utf-8-sig"))
    wanted = {"_mask_option_value", "_currentOSMMaskInputs", "openCFSAlignmentViewer", "generateCourseFromLidar"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if {node.name for node in functions} != wanted:
        raise AssertionError("Main-window routing functions were not all found")
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "tgc_gui.py"), "exec"), environment)
    def gate(opts, path, printf):
        values = environment["_currentOSMMaskInputs"](opts)
        return mask_module.get_alignment_status(path, values["local_osm_file"],
             values["adjust_ew"], values["adjust_ns"], values["auto_red_mask_enabled"],
             values["auto_red_mask_buffer_m"])["ok_for_import"]
    environment["validateOSMMaskBeforeCourseImport"] = gate
    environment["openCFSAlignmentViewer"](options, lambda *_: None)
    if not captured:
        raise AssertionError("Main route failed to open CFS")
    return environment, options, captured, statuses, generated


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tgc-local-integration-")
        cls.folder = Path(cls.temporary.name)
        cls.data, cls.source, cls.nudge, cls.target = fixture(cls.folder)
        cls.source_bytes = cls.source.read_bytes()
        cls.terrain_bytes = cls.data["heightmap"].tobytes()
        cls.report = engine.analyze(cls.data, cls.source, *cls.nudge)
        cls.result = engine.apply_reviewed(cls.report, [101], cls.folder / "corrected.osm",
              current_data=cls.data, current_nudge=cls.nudge, current_osm_file=cls.source)
        cls.corrected = Path(cls.result["output"])

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def test_01_nonzero_global_nudge_is_fitted_once(self):
        f = self.report["features"][0]
        self.assertTrue(f["movable"])
        self.assertLess(np.linalg.norm([f["proposed_east_m"]+3., f["proposed_north_m"]-2.]), .01)
        np.testing.assert_allclose(np.asarray(f["fit_coords_m"])-np.asarray(f["coords_m"]),
                                   np.tile(self.nudge, (len(f["coords_m"]), 1)), atol=1e-9)

    def test_02_original_terrain_and_osm_are_unchanged(self):
        self.assertEqual(self.source_bytes, self.source.read_bytes())
        self.assertEqual(self.terrain_bytes, self.data["heightmap"].tobytes())
        self.assertNotEqual(self.corrected.resolve(), self.source.resolve())
        old = ET.fromstring(self.source_bytes).find("node[@id='999']")
        new = ET.parse(self.corrected).find("node[@id='999']")
        self.assertEqual(old.attrib, new.attrib)

    def test_03_cfs_mask_and_native_importer_consume_corrected_points(self):
        parsed = overpy.Overpass().parse_xml(self.corrected.read_text())
        grid, projection = self.data["master_grid"], self.data["projection"]
        features = viewer_module._collect_overlay_features(parsed, projection, grid, printf=lambda *_: None)
        feature = next(f for f in features if f["label"] == "101")
        cfs_local = np.asarray(feature["points"])*grid["resolution"] + self.nudge
        np.testing.assert_allclose(cfs_local[:-1], self.target, atol=1e-5)
        projector = mask_module._FastGridProjector(projection, (grid["min_x"], grid["min_y"]))
        for node, expected in zip(parsed.ways[0].get_nodes(), cfs_local):
            self.assertEqual(projector.latlonToCV2(node.lat, node.lon, 2., *self.nudge),
                             (int(expected[1]/2.), int(expected[0]/2.)))
        pc = GeoPointCloud(); pc.proj = projection; pc.origin = (grid["min_x"], grid["min_y"])
        pc.xmin=pc.ymin=0.; pc.xmax=pc.ymax=192.; pc.width=pc.height=192.
        captured = []
        original_builder = OSMTGC.newBunker
        def capture(points, *args, **kwargs):
            captured.extend(points)
            return original_builder(points, *args, **kwargs)
        course = {}
        with patch.object(OSMTGC, "newBunker", capture):
            OSMTGC.addOSMToTGC(course, pc, parsed, x_offset=self.nudge[0], y_offset=self.nudge[1],
                 options_dict={"tree": False}, printf=lambda *_: None, course_version=25, resolve_missing_nodes=False)
        imported = np.array([[x+96., z+96.] for x, _, z in captured])
        np.testing.assert_allclose(imported, cfs_local, atol=1e-8)
        self.assertEqual(len(course["surfaceSplines2"]), 1)

    def test_04_real_mask_changes_then_matches_corrected_source(self):
        mask_module.rebuild_aligned_mask(self.folder, self.source, *self.nudge,
            auto_red_mask_enabled=True, auto_red_mask_buffer_m=5., printf=lambda *_: None)
        original_mask = cv2.imread(str(self.folder / "mask.png"))
        stale = mask_module.get_alignment_status(self.folder, self.corrected, *self.nudge, True, 5.)
        self.assertFalse(stale["ok_for_import"])
        self.assertEqual(stale["state"], "stale")
        mask_module.rebuild_aligned_mask(self.folder, self.corrected, *self.nudge,
            auto_red_mask_enabled=True, auto_red_mask_buffer_m=5., printf=lambda *_: None)
        current = mask_module.get_alignment_status(self.folder, self.corrected, *self.nudge, True, 5.)
        self.assertTrue(current["ok_for_import"])
        self.assertFalse(np.array_equal(original_mask, cv2.imread(str(self.folder / "mask.png"))))

    def test_05_main_selection_rebuild_and_generation_handoff(self):
        env, options, captured, statuses, generated = main_harness(self.folder, self.source, self.nudge)
        callback = captured["kwargs"]["osm_file_changed_callback"]
        state = callback(str(self.source))
        callback(str(self.source), str(self.corrected), expected_state=state)
        self.assertEqual(options["local_osm_file"].get(), str(self.corrected))
        self.assertIn("STALE", statuses[-1][0])
        with self.assertRaises(ValueError): callback(str(self.source), expected_state=state)
        finished = captured["kwargs"]["apply_finished_callback"]
        finished({"action": "rebuilt"}, self.folder, *self.nudge)
        self.assertEqual(statuses[-1][0], "CURRENT")
        captured["kwargs"]["apply_callback"](self.folder, self.corrected, *self.nudge, printf=lambda *_: None)
        env["generateCourseFromLidar"](options, lambda *_: None)
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0]["options_dict"]["local_osm_file"], str(self.corrected))
        options["local_osm_file"].set(str(self.source))
        env["generateCourseFromLidar"](options, lambda *_: None)
        self.assertEqual(len(generated), 1, "Stale original geometry must not pass the import gate")

    def test_06_selection_snapshot_blocks_project_setting_changes(self):
        env, options, captured, _, _ = main_harness(self.folder, self.source, self.nudge)
        callback = captured["kwargs"]["osm_file_changed_callback"]
        state = callback(str(self.source))
        options["adjust_ew"].set("8")
        with self.assertRaises(ValueError): callback(str(self.source), str(self.corrected), expected_state=state)
        self.assertEqual(options["local_osm_file"].get(), str(self.source))
        options["adjust_ew"].set(str(self.nudge[0]))
        env["root"].filename = str(self.folder / "different_project")
        with self.assertRaises(ValueError): callback(str(self.source), expected_state=state)

    def test_07_changed_current_nudge_prevents_export(self):
        destination = self.folder / "stale_nudge.osm"
        with self.assertRaises(engine.AlignmentError):
            engine.apply_reviewed(self.report, [101], destination, current_data=self.data,
                current_nudge=(self.nudge[0]+.5, self.nudge[1]), current_osm_file=self.source)
        self.assertFalse(destination.exists())

    def test_08_changed_terrain_prevents_export(self):
        changed = copy.deepcopy(self.data); changed["heightmap"][50, 50] += .01
        destination = self.folder / "stale_terrain.osm"
        with self.assertRaises(engine.AlignmentError):
            engine.apply_reviewed(self.report, [101], destination, current_data=changed,
                current_nudge=self.nudge, current_osm_file=self.source)
        self.assertFalse(destination.exists())

    def test_09_corrected_osm_cannot_adopt_untracked_zero_shift_mask(self):
        with tempfile.TemporaryDirectory(prefix="tgc-local-legacy-mask-") as temporary:
            folder = Path(temporary)
            np.save(folder / "heightmap.npy", self.data)
            cv2.imwrite(str(folder / "mask.png"), np.full((96, 96, 3), 255, np.uint8))
            legacy = mask_module.get_alignment_status(folder, self.source, 0., 0., True, 5.)
            self.assertEqual(legacy["state"], "legacy_zero_shift")
            stale = mask_module.get_alignment_status(folder, self.corrected, 0., 0., True, 5.)
            self.assertEqual(stale["state"], "stale")
            self.assertFalse(stale["ok_for_import"])
            with self.assertRaisesRegex(RuntimeError, "cannot adopt a legacy mask"):
                mask_module.adopt_existing_zero_shift_mask(folder, self.corrected, 0., 0., True, 5.,
                                                          printf=lambda *_: None)
            self.assertFalse((folder / mask_module.SIDECAR_NAME).exists())
            # The pre-existing adoption workflow remains valid for ordinary OSM.
            mask_module.adopt_existing_zero_shift_mask(folder, self.source, 0., 0., True, 5.,
                                                      printf=lambda *_: None)
            self.assertTrue(mask_module.get_alignment_status(folder, self.source, 0., 0., True, 5.)["ok_for_import"])


def bootleg_check(heightmap, osm, baseline, output=None):
    source, raster = Path(osm), Path(heightmap)
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, raster)]
    data = np.load(raster, allow_pickle=True).item()
    old = json.loads(Path(baseline).read_text())
    report = engine.analyze(data, source)
    expected = {int(f["way_id"]): f for f in old["features"]}
    actual = {int(f["way_id"]): f for f in report["features"]}
    assert expected.keys() == actual.keys(), "Feature inventory differs from the original Bootleg test"
    compared, guarded = 0, []
    for wid, item in actual.items():
        if item["topology_reasons"]:
            assert not item["movable"] and item["status"] == "unsupported_topology"
            guarded.append(wid)
            continue
        previous = expected[wid]
        assert item["status"] == previous["status"], (wid, previous["status"], item["status"])
        for key in ("proposed_east_m", "proposed_north_m"):
            assert abs(float(item[key])-float(previous[key])) <= 1e-9, (wid, key)
        compared += 1
    assert hashes == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, raster)]
    result = dict(features=len(actual), identical_independent_features=compared,
                  topology_guarded_way_ids=guarded, counts=dict(Counter(f["status"] for f in actual.values())),
                  original_inputs_unchanged=True)
    if output: Path(output).write_text(json.dumps(result, indent=2)+"\n")
    print("PASS Bootleg regression: " + json.dumps(result), flush=True)
    return result


def gui_check(screenshot=None):
    import tkinter as tk
    import tgc_local_alignment_ui as ui
    root = tk.Tk(); root.withdraw()
    errors, dialogs, worker_threads = [], [], []
    root.report_callback_exception = lambda *args: errors.append(repr(args))
    main_thread = threading.get_ident()
    def pump_until(condition, seconds=15.):
        end = time.monotonic()+seconds
        while not condition() and time.monotonic()<end:
            root.update(); time.sleep(.005)
        root.update()
        assert condition(), "Timed out waiting for actual Tk worker state"
    with tempfile.TemporaryDirectory(prefix="tgc-local-gui-") as temporary:
        folder = Path(temporary)
        data, source, nudge, _ = fixture(folder)
        source_bytes = source.read_bytes()
        # Deliberately retain a pending viewer nudge while main entries are zero.
        # Adopting a corrected file must synchronize this reviewed nudge too.
        env, options, opened, statuses, _ = main_harness(folder, source, (0., 0.), root=root)
        view = viewer_module.AlignmentViewer(*opened["args"], **opened["kwargs"])
        pump_until(lambda: view.ready)
        view._nudge(*nudge)
        assert float(options["adjust_ew"].get()) == 0. and float(options["adjust_ns"].get()) == 0.
        entered, release = threading.Event(), threading.Event()
        def delayed_analysis(*args, **kwargs):
            worker_threads.append(threading.get_ident()); entered.set()
            while not release.wait(.01):
                if kwargs.get("cancel_event") is not None and kwargs["cancel_event"].is_set():
                    raise engine.AlignmentCancelled("Fixture cancelled")
            return engine.analyze(*args, **kwargs)
        backend = types.SimpleNamespace(analyze=delayed_analysis, apply_reviewed=engine.apply_reviewed)
        dialog = ui.LocalAlignmentDialog(view, engine=backend); dialogs.append(dialog)
        pump_until(entered.is_set)
        heartbeat=[]
        root.after(20, lambda: heartbeat.append(True))
        pump_until(lambda: bool(heartbeat))
        assert dialog.operation == "analyze" and not dialog.selected_ids
        assert not view._can_interact(), "Global CFS movement must be locked during local review"
        release.set()
        pump_until(lambda: dialog.report is not None and dialog.operation is None)
        assert worker_threads and all(t != main_thread for t in worker_threads)
        assert not dialog.selected_ids and str(dialog.apply_button["state"]) == "disabled"
        assert dialog.features["101"]["movable"]
        dialog.select_all(); assert dialog.selected_ids == {"101"}
        destination = folder / "gui_corrected.osm"
        messages=[]
        with patch.object(ui.messagebox, "showerror", lambda *a, **k: messages.append(a)), \
             patch.object(ui.filedialog, "asksaveasfilename", lambda **_: str(destination)):
            # A changed parent setting must block the save without replacing it.
            options["adjust_ew"].set("9")
            dialog.apply_selected()
            assert messages and not destination.exists()
            options["adjust_ew"].set("0"); messages.clear()
            dialog.apply_selected()
            pump_until(lambda: dialog.operation is None and view.osm_file == str(destination))
            assert not messages, messages
        assert source.read_bytes() == source_bytes
        assert options["local_osm_file"].get() == str(destination)
        assert float(options["adjust_ew"].get()) == nudge[0]
        assert float(options["adjust_ns"].get()) == nudge[1]
        assert view.osm_file == str(destination) and dialog.report is None and not dialog.selected_ids
        assert view.shift_ew == nudge[0] and view.shift_ns == nudge[1]
        assert any("STALE" in s[0] for s in statuses)
        if screenshot:
            from PIL import ImageGrab
            ImageGrab.grab().save(screenshot)
        dialog.request_close(); pump_until(lambda: dialog.closed)
        assert view.local_review is None and view._can_interact()
        # A second dialog that closes during analysis must not mutate selection
        # or enqueue late Tk calls after its window is gone.
        entered.clear(); release.clear()
        cancelled = ui.LocalAlignmentDialog(view, engine=backend); dialogs.append(cancelled)
        pump_until(entered.is_set)
        cancelled.request_close()
        assert cancelled.closed and cancelled.cancel_event.is_set()
        assert view.local_review is None
        sentinel=[]; root.after(100, lambda: sentinel.append(True)); pump_until(lambda: bool(sentinel))
        assert options["local_osm_file"].get() == str(destination)
        assert source.read_bytes() == source_bytes
        assert not errors, errors
        view._request_close(); root.destroy()
    print("PASS real Tk: responsive worker, zero default checks, frozen global shift, stale selection block, "
          "reviewed save and CFS/main path update, pending-nudge synchronization, unchanged source, close/cancel cleanup.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--screenshot")
    parser.add_argument("--bootleg-heightmap")
    parser.add_argument("--bootleg-osm")
    parser.add_argument("--regression-json")
    parser.add_argument("--regression-output")
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests))
    if not result.wasSuccessful(): raise SystemExit(1)
    supplied = [args.bootleg_heightmap, args.bootleg_osm, args.regression_json]
    if any(supplied):
        if not all(supplied): parser.error("The three Bootleg regression inputs must be supplied together")
        bootleg_check(*supplied, output=args.regression_output)
    if args.gui: gui_check(args.screenshot)
