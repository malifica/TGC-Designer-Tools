"""Developer-only real Tk check of local manual alignment and CFS controls.

Runs against analytical terrain and private temporary OSM files. It never
loads a user course, and it is not a Windows or real-world fitting accuracy
test. A working display is required; the release builder does not run this.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
import traceback
import tkinter as tk
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
from PIL import ImageGrab
import pyproj

from VERIFY_BETA7_LOCAL_ALIGNMENT import main_harness
import osm_alignment_viewer as viewer_module
import tgc_local_alignment as engine
import tgc_local_alignment_ui as ui
from tgc_cfs_display import importer_transformer
from tgc_cfs_widgets import ActionButton


def fixture(folder, nudge=(1.5, -1.0)):
    """Candidate/keep/weak, shared-node rough, and tee/bunker rough-inner cases."""
    folder = Path(folder)
    resolution, size = 2.0, 192
    xx, yy = np.meshgrid((np.arange(size)+.5)*resolution, (np.arange(size)+.5)*resolution)
    z = np.full((size, size), 100.0)
    rings = {}
    for way_id, centre, misalignment in ((101, (80., 80.), (3., -2.)),
                                         (102, (210., 210.), (0., 0.))):
        radius = np.hypot(xx-centre[0], yy-centre[1])
        t = np.clip((12.-radius)/4., 0., 1.)
        z += -2.*t*t*(3.-2.*t) + .25*np.exp(-.5*((radius-12.)/1.)**2)
        angle = np.linspace(0., 2.*np.pi, 96, endpoint=False)
        ring = np.column_stack([centre[0]+12.*np.cos(angle), centre[1]+12.*np.sin(angle)])
        rings[way_id] = ("bunker", ring+misalignment)
    dx = np.maximum(np.maximum(268.-xx, xx-292.), 0.)
    dy = np.maximum(np.maximum(70.-yy, yy-90.), 0.)
    t = np.clip(np.hypot(dx, dy)/5., 0., 1.)
    z += 2.*(1.-t*t*(3.-2.*t))
    rings[103] = ("tee", np.array([[268., 70.], [292., 70.], [292., 90.], [268., 90.]])+[3., -2.])
    rings[104] = ("tee", np.array([[130., 70.], [150., 70.], [150., 90.], [130., 90.]]))
    rings[105] = ("tee", np.array([[200., 70.], [220., 70.], [220., 90.], [200., 90.]]))
    rings[106] = ("bunker", np.array([[70., 285.], [90., 285.], [90., 305.], [70., 305.]]))
    rings[107] = ("tee", np.array([[135., 285.], [155., 285.], [155., 305.], [135., 305.]]))

    projection = pyproj.Proj("EPSG:32611")
    transform = importer_transformer(projection)
    min_x, min_y = 575641., 5497180.
    lon0, lat0 = transform.transform(min_x, min_y, direction="INVERSE")
    grid = dict(version=1, rows=size, cols=size, resolution=resolution,
                min_x=min_x, min_y=min_y, max_x=min_x+size*resolution, max_y=min_y+size*resolution,
                crs_wkt=projection.crs.to_wkt(), horizontal_epsg=32611,
                origin_semantics="southwest_cell_edge", row_order="south_up_internal", xy_units="meters",
                lower_left_latlon=[lat0, lon0])
    data = dict(heightmap=z, image_scale=resolution, master_grid=grid,
                projection=projection, origin=(lat0, lon0))
    document = ET.Element("osm", version="0.6", generator="Independent manual-UI fixture")
    node_id = 1
    for way_id, (kind, ring) in rings.items():
        ids = []
        for x, y in ring-nudge:
            lon, lat = transform.transform(x+min_x, y+min_y, direction="INVERSE")
            ids.append(node_id)
            ET.SubElement(document, "node", id=str(node_id), lon=f"{lon:.12f}", lat=f"{lat:.12f}", version="1")
            node_id += 1
        way = ET.SubElement(document, "way", id=str(way_id), version="1")
        for i in ids+[ids[0]]: ET.SubElement(way, "nd", ref=str(i))
        ET.SubElement(way, "tag", k="golf", v=kind)
        if way_id == 105:
            shared_id = ids[0]
    rough_ids = [shared_id]
    for x, y in np.array([[190., 55.], [230., 55.]])-nudge:
        lon, lat = transform.transform(x+min_x, y+min_y, direction="INVERSE")
        ET.SubElement(document, "node", id=str(node_id), lon=f"{lon:.12f}", lat=f"{lat:.12f}", version="1")
        rough_ids.append(node_id); node_id += 1
    rough = ET.SubElement(document, "way", id="900", version="1")
    for i in rough_ids+[rough_ids[0]]: ET.SubElement(rough, "nd", ref=str(i))
    ET.SubElement(rough, "tag", k="golf", v="rough")
    outer_ids = []
    for x, y in np.array([[40., 250.], [190., 250.], [190., 350.], [40., 350.]])-nudge:
        lon, lat = transform.transform(x+min_x, y+min_y, direction="INVERSE")
        ET.SubElement(document, "node", id=str(node_id), lon=f"{lon:.12f}", lat=f"{lat:.12f}", version="1")
        outer_ids.append(node_id); node_id += 1
    outer = ET.SubElement(document, "way", id="901", version="1")
    for i in outer_ids+[outer_ids[0]]: ET.SubElement(outer, "nd", ref=str(i))
    relation = ET.SubElement(document, "relation", id="700", version="1")
    for wid, role in ((901, "outer"), (106, "inner"), (107, "inner")):
        ET.SubElement(relation, "member", type="way", ref=str(wid), role=role)
    ET.SubElement(relation, "tag", k="type", v="multipolygon")
    ET.SubElement(relation, "tag", k="golf", v="rough")
    source = folder / "source.osm"
    ET.ElementTree(document).write(source, encoding="utf-8", xml_declaration=True)
    np.save(folder / "heightmap.npy", data)
    return data, source, tuple(nudge)


def projected_way(path, way_id, data):
    root = ET.parse(path).getroot()
    nodes = {n.attrib["id"]: n for n in root.findall("node")}
    way = root.find(f"way[@id='{way_id}']")
    ll = [[float(nodes[n.attrib["ref"]].attrib[k]) for k in ("lon", "lat")] for n in way.findall("nd")]
    xy = np.column_stack(importer_transformer(data["projection"]).transform(*np.array(ll).T))
    return xy-np.array([data["master_grid"]["min_x"], data["master_grid"]["min_y"]])


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class TkChecks:
    def __init__(self, output):
        self.output = output
        self.root = tk.Tk(); self.root.withdraw()
        self.errors, self.results = [], []
        self.root.report_callback_exception = lambda *args: self.errors.append(repr(args))
        self.view = self.dialog = None

    def pump_until(self, condition, timeout=20.):
        end = time.monotonic()+timeout
        while not condition() and time.monotonic() < end:
            self.root.update(); time.sleep(.005)
        self.root.update()
        assert condition(), "Timed out waiting for actual Tk state"
        assert not self.errors, self.errors

    def settle(self):
        ready = []
        self.root.after(90, lambda: ready.append(True))
        self.pump_until(lambda: bool(ready))

    def capture(self, window, name):
        self.settle()
        x, y = window.winfo_rootx(), window.winfo_rooty()
        box = (x, y, x+window.winfo_width(), y+window.winfo_height())
        ImageGrab.grab(bbox=box).save(self.output / name)

    def check(self, name, function):
        details = function()
        self.results.append({"name": name, "passed": True, "details": details})
        print("PASS "+name, flush=True)

    def cleanup(self):
        with patch.object(ui.messagebox, "askyesno", return_value=True):
            if self.dialog and not self.dialog.closed: self.dialog.request_close()
            if self.view and not self.view.closed: self.view._request_close()
        self.root.update()
        self.root.destroy()


    def select_row(self, wid):
        dialog = self.dialog
        dialog.tree.focus(wid)
        dialog.tree.selection_set(wid)
        dialog.tree.see(wid)
        self.settle()
        assert dialog.tree.focus() == wid

    def set_offsets(self, east, north):
        dialog = self.dialog
        dialog.manual_east_var.set(str(east)); dialog.manual_north_var.set(str(north))
        dialog.set_offsets_button.invoke()
        self.settle()
        np.testing.assert_allclose(dialog._effective_offset(dialog.tree.focus()), [east, north], atol=1e-10)

    def outline_matches(self, wid, expected_offset):
        dialog = self.dialog
        self.settle()
        points = np.asarray(dialog.features[wid]["fit_coords_m"])+expected_offset
        expected = np.asarray([dialog._screen(*point) for point in points]).ravel()
        outlines = dialog.canvas.find_withtag("outlines")
        assert outlines, "No actual canvas outlines"
        rendered = np.asarray(dialog.canvas.coords(outlines[-1]))
        np.testing.assert_allclose(rendered[:len(expected)], expected, atol=1e-7)

    def pointer_centre(self, wid, source=False):
        dialog = self.dialog
        points = np.asarray(dialog.features[wid]["fit_coords_m"] if source else dialog._effective_points(wid))
        centre = (points.min(axis=0)+points.max(axis=0))/2
        return self.pointer_at(centre)

    def pointer_at(self, point):
        dialog = self.dialog
        centre = np.asarray(point)
        x, y = dialog._screen(*centre)
        x -= dialog.canvas.canvasx(0); y -= dialog.canvas.canvasy(0)
        assert 0 < x < dialog.canvas.winfo_width() and 0 < y < dialog.canvas.winfo_height(), (x, y)
        return int(round(x)), int(round(y))

    def pointer(self, binding, x, y, state=None):
        options = {} if state is None else {"state": state}
        self.dialog.canvas.event_generate(binding, x=x, y=y, **options)
        self.root.update()

    def click_object(self, wid, source=False):
        x, y = self.pointer_centre(wid, source=source)
        self.pointer("<ButtonPress-1>", x, y)
        self.pointer("<ButtonRelease-1>", x, y)
        self.settle()
        assert self.dialog.tree.focus() == wid, self.dialog.tree.focus()
        assert self.dialog.tree.selection() == (wid,), self.dialog.tree.selection()

    def viewport(self):
        dialog = self.dialog
        return dialog.zoom, dialog.canvas.xview(), dialog.canvas.yview()

    def run(self, folder):
        self.data, self.source, self.nudge = fixture(folder)
        source_bytes = self.source.read_bytes()
        terrain_bytes = (folder / "heightmap.npy").read_bytes()
        env, options, opened, statuses, _ = main_harness(folder, self.source, (0., 0.), root=self.root)
        self.options, self.statuses = options, statuses
        self.view = viewer_module.AlignmentViewer(*opened["args"], **opened["kwargs"])
        view = self.view
        view.window.geometry("1320x700+20+20")
        self.pump_until(lambda: view.ready)

        def cfs_buttons():
            buttons = [w for w in descendants(view.window) if w.winfo_class() in ("Button", "TButton")]
            assert len(buttons) >= 8
            assert all(isinstance(w, ActionButton) for w in buttons), "An old flat CFS action button remains"
            assert all(str(w.cget("relief")) == "raised" and int(w.cget("borderwidth")) >= 2 for w in buttons)
            button = view.local_alignment_button
            normal = button.cget("background")
            button.configure(state="disabled"); self.root.update()
            assert button.cget("background") == "#eef1f4"
            button.invoke(); assert view.local_review is None
            button.configure(state="normal"); assert button.cget("background") == normal
            self.capture(view.window, "CFS_Raised_Buttons_1320x700.png")
            return {"action_buttons": len(buttons), "disabled_action_ignored": True,
                    "raised_border": True, "window": [view.window.winfo_width(), view.window.winfo_height()]}
        self.check("raised CFS action buttons and disabled behavior", cfs_buttons)

        # Exercise the real launcher while CFS fields contain a pending shift.
        # No Apply or mask rebuild occurs before local analysis.
        view.ew_var.set(str(self.nudge[0])); view.ns_var.set(str(self.nudge[1]))
        view.local_alignment_button.invoke()
        self.dialog = view.local_review
        dialog = self.dialog
        dialog.window.geometry("1320x700+20+20")
        self.pump_until(lambda: dialog.report is not None and dialog.operation is None)
        assert not dialog.selected_ids and not dialog.manual_overrides
        assert str(dialog.apply_button.cget("state")) == "disabled"
        self.detector_statuses = {wid: f["status"] for wid, f in dialog.features.items()}
        expected = {"101": "review_candidate", "102": "keep_current", "103": "insufficient_evidence",
                    "104": "keep_current", "105": "unsupported_topology",
                    "106": "unsupported_topology", "107": "unsupported_topology"}
        assert {wid: self.detector_statuses[wid] for wid in expected} == expected, self.detector_statuses
        assert all(f["status"] == "manual_only" and not f["movable"]
                   for f in dialog.features.values() if f["kind"] == "rough")

        def pending_global_shift():
            assert float(options["adjust_ew"].get()) == 0. and float(options["adjust_ns"].get()) == 0.
            assert tuple(dialog.report["global_nudge_m"]) == self.nudge == dialog.shift
            for feature in dialog.features.values():
                actual = np.asarray(feature["fit_coords_m"])-np.asarray(feature["coords_m"])
                np.testing.assert_allclose(actual, np.tile(self.nudge, (len(actual), 1)), atol=1e-9)
            np.testing.assert_allclose([dialog.features["101"]["proposed_east_m"], dialog.features["101"]["proposed_north_m"]],
                                       [-3., 2.], atol=.01)
            labels = [str(w.cget("text")) for w in descendants(dialog.window) if w.winfo_class() in ("Label", "TLabel")]
            assert any("CFS shift used:" in text and "+1.5" in text and "-1" in text for text in labels)
            return {"pending_typed_cfs_shift_m": list(self.nudge), "analyzed_before_apply_or_rebuild": True,
                    "applied_once_to_fit": True, "suggested_residual_m": [-3., 2.], "visible_shift_readout": True}
        self.check("pending CFS entry values are fitted once before Apply or Rebuild", pending_global_shift)

        def row_navigation():
            observations = []
            for wid in ("102", "103", "101"):
                # No Zoom-to-feature call: the actual Treeview selection event
                # must update the viewport for candidate, keep and weak rows.
                self.select_row(wid)
                points = np.asarray(dialog.features[wid]["fit_coords_m"] + dialog._effective_points(wid))
                centre = (points.min(axis=0)+points.max(axis=0))/2
                wanted = np.asarray(dialog._screen(*centre))
                actual = np.array([dialog.canvas.canvasx(dialog.canvas.winfo_width()/2),
                                   dialog.canvas.canvasy(dialog.canvas.winfo_height()/2)])
                error = np.abs(actual-wanted)
                assert np.max(error) <= 3., (wid, actual, wanted)
                assert dialog.zoom > 1., dialog.zoom
                observations.append({"way_id": wid, "status": dialog.features[wid]["status"],
                                     "zoom": dialog.zoom, "centre_error_px": error.tolist()})
            dialog.tree.focus_force(); dialog.tree.event_generate("<KeyPress-Down>"); self.settle()
            assert dialog.tree.focus() == "102", "Native keyboard row navigation failed"
            assert dialog._last_focus_id == "102"
            return observations
        self.check("row selection and keyboard navigation automatically frame all statuses", row_navigation)

        def canvas_selection():
            dialog.fit_course(); self.settle()
            view_before = self.viewport()
            for wid in ("105", "104", "101", "102", "103"):
                self.click_object(wid)
                assert self.viewport() == view_before, "Canvas selection moved the view"
                assert not dialog.selected_ids and not dialog.manual_overrides and not dialog.manual_history
            # An object picked on the map must reveal its row even when the
            # list was scrolled elsewhere. Extra rows are UI-only placeholders.
            placeholders = ["scroll_fixture_"+str(i) for i in range(45)]
            for wid in placeholders: dialog.tree.insert("", "end", iid=wid, values=("", "", "", "", ""))
            dialog.tree.move("103", "", "end")
            dialog.tree.yview_moveto(0.); self.settle()
            assert not dialog.tree.bbox("103")
            self.click_object("101"); self.click_object("103")
            assert dialog.tree.bbox("103"), "Canvas selection left the selected row offscreen"
            dialog.tree.delete(*placeholders)
            for wid in ("101", "102", "103", "104", "105"): dialog.tree.move(wid, "", "end")
            # Separate original and effective outlines widely so neither hit
            # can be explained by the other outline's screen tolerance.
            self.select_row("101"); self.set_offsets(0., 80.)
            dialog.fit_course(); self.settle()
            drafts = copy.deepcopy(dialog.manual_overrides)
            checks, history, view_before = set(dialog.selected_ids), len(dialog.manual_history), self.viewport()
            self.click_object("102"); self.click_object("101", source=True)
            self.click_object("102"); self.click_object("101")
            assert self.viewport() == view_before
            assert drafts == dialog.manual_overrides and checks == dialog.selected_ids and history == len(dialog.manual_history)
            dialog.undo_button.invoke(); self.settle()
            assert not dialog.manual_overrides and not dialog.selected_ids
            return {"all_statuses_picked": ["101", "102", "103", "104", "105"],
                    "canvas_click_does_not_zoom_pan_or_accept": True, "offscreen_row_revealed": True,
                    "original_and_manual_outline_pickable": True, "manual_outline_separation_m": 80.}
        self.check("canvas selection follows source and moved objects without changing the view", canvas_selection)

        def canvas_select_and_drag():
            self.select_row("101")
            dialog.move_mode_button.invoke(); assert dialog.move_mode_var.get()
            dialog._set_zoom(5.); dialog.canvas.xview_moveto(.05); dialog.canvas.yview_moveto(.62); self.settle()
            origin = [dialog.canvas.canvasx(0), dialog.canvas.canvasy(0)]
            assert all(v > 0 for v in origin), origin
            x, y = self.pointer_centre("104")
            before = self.viewport()
            count = len(dialog.manual_history)
            self.pointer("<ButtonPress-1>", x, y)
            assert dialog.tree.focus() == "104" and dialog._drag_state is not None
            assert self.viewport() == before, "Queued row event zoomed during a canvas drag"
            assert not dialog.manual_overrides and not dialog.selected_ids
            self.pointer("<B1-Motion>", x+15, y+10)
            self.pointer("<ButtonRelease-1>", x+15, y+10)
            self.settle()
            np.testing.assert_allclose(dialog._effective_offset("104"), [6., -4.], atol=1e-9)
            assert dialog.selected_ids == {"104"} and len(dialog.manual_history) == count+1
            assert self.viewport() == before
            dialog.undo_button.invoke(); self.settle()
            assert not dialog.manual_overrides and not dialog.selected_ids
            # Shared-node tee movement is now manual and detaches its rough neighbour.
            dialog.fit_course(); self.settle()
            x, y = self.pointer_centre("105")
            self.pointer("<ButtonPress-1>", x, y)
            assert dialog.tree.focus() == "105" and dialog._drag_state is not None
            self.pointer("<B1-Motion>", x+15, y+10); self.pointer("<ButtonRelease-1>", x+15, y+10)
            assert dialog.selected_ids == {"105"} and "rough-way:900" not in dialog.manual_overrides
            assert str(dialog.set_offsets_button.cget("state")) == "normal"
            dialog.undo_button.invoke(); self.settle()
            assert not dialog.manual_overrides and not dialog.selected_ids
            # Switch to a valid feature and leave move mode OFF for later checks.
            dialog.fit_course(); self.settle(); self.click_object("103")
            dialog.move_mode_button.invoke(); assert not dialog.move_mode_var.get()
            return {"new_object_selected_and_moved_in_one_gesture": 104, "zoom": 5.,
                    "canvas_origin_px": origin, "screen_drag_px": [15, 10], "residual_m": [6., -4.],
                    "one_undo_item": True, "shared_node_way_manually_movable_without_rough": 105}
        self.check("one canvas gesture selects and moves another object at a scrolled zoom", canvas_select_and_drag)

        def canvas_pending_and_overlap():
            dialog.manual_east_var.set("2.75")
            dialog.fit_course(); self.settle()
            self.click_object("102"); self.click_object("103")
            assert dialog.manual_east_var.get() == "2.75" and "103" in dialog._pending_entries
            dialog.move_mode_button.invoke(); assert dialog.move_mode_var.get()
            x, y = self.pointer_centre("103")
            self.pointer("<ButtonPress-1>", x, y)
            assert dialog._drag_state is None and "Set offsets" in dialog.status_var.get()
            self.pointer("<B1-Motion>", x+12, y+8); self.pointer("<ButtonRelease-1>", x+12, y+8)
            assert not dialog.manual_overrides and not dialog.selected_ids
            dialog.suggestion_button.invoke(); self.settle()
            assert "103" not in dialog._pending_entries
            dialog.move_mode_button.invoke(); assert not dialog.move_mode_var.get()
            # Place the smaller rectangular tee inside the circular bunker.
            # At centre both contain the click; near separate edges nearest
            # visible boundary must win, independently of previous focus.
            self.select_row("104"); self.set_offsets(70., 130.)
            self.select_row("102")
            centre = self.pointer_centre("102")
            self.pointer("<ButtonPress-1>", *centre); self.pointer("<ButtonRelease-1>", *centre); self.settle()
            assert dialog.tree.focus() == "104", "Smallest containing object was not selected"
            for point, wanted in (((222., 210.), "102"), ((220., 210.), "104")):
                x, y = self.pointer_at(point)
                self.pointer("<ButtonPress-1>", x, y); self.pointer("<ButtonRelease-1>", x, y); self.settle()
                assert dialog.tree.focus() == wanted, (point, wanted, dialog.tree.focus())
            dialog.undo_button.invoke(); self.settle()
            assert not dialog.manual_overrides and not dialog.selected_ids
            self.select_row("103")
            # Panning with other mouse buttons works while move mode is on.
            dialog.move_mode_button.invoke(); assert dialog.move_mode_var.get()
            for number in (2, 3):
                x, y = self.pointer_centre("103")
                before = self.viewport()
                self.pointer(f"<ButtonPress-{number}>", x, y)
                self.pointer(f"<B{number}-Motion>", x+10, y+8)
                self.pointer(f"<ButtonRelease-{number}>", x+10, y+8)
                assert self.viewport() != before and not dialog.manual_overrides and not dialog.selected_ids
            dialog.move_mode_button.invoke(); assert not dialog.move_mode_var.get()
            return {"pending_typed_draft_survives_canvas_selection": True, "pending_draft_blocks_drag": True,
                    "overlap_selects_smallest_interior_or_nearest_boundary": True,
                    "middle_and_right_pan_in_move_mode": True}
        self.check("canvas selection preserves pending entries and resolves overlapping outlines", canvas_pending_and_overlap)

        def linked_rough_holes():
            assert dialog.link_holes_var.get()
            observed = []
            for wid in ("106", "107"):
                self.select_row(wid)
                linked = dialog.features[wid]["linked_ids"]
                assert len(linked) == 1, linked
                hole = linked[0]
                assert dialog.features[hole]["label"] == "Rough hole"
                assert wid in dialog.features[hole]["linked_ids"]
                assert dialog._movement_ids() == {wid, hole}
                before = len(dialog.manual_history)
                self.set_offsets(1.5, -.5)
                assert dialog.selected_ids == {wid, hole}
                np.testing.assert_allclose(dialog._effective_offset(hole), [1.5, -.5])
                outer = next(k for k, f in dialog.features.items() if f.get("boundary_role") == "outer")
                assert outer not in dialog.manual_overrides
                assert len(dialog.manual_history) == before+1
                dialog.undo_button.invoke(); self.settle()
                assert not dialog.manual_overrides and not dialog.selected_ids
                assert dialog.tree.selection() == (wid,), "Undo turned implicit links into explicit row selection"
                observed.append({"feature": wid, "matching_hole": hole, "outer_unchanged": outer})
            return {"tee_and_bunker_supported": observed, "one_undo_per_linked_move": True,
                    "rough_never_automatically_detected": True}
        self.check("tee and bunker keep matching rough holes together by default", linked_rough_holes)

        def separate_and_group_geometry():
            wid = "106"
            hole = dialog.features[wid]["linked_ids"][0]
            outer = next(k for k, f in dialog.features.items() if f.get("boundary_role") == "outer")
            history = len(dialog.manual_history)
            dialog.link_holes_check.invoke(); assert not dialog.link_holes_var.get()
            self.select_row(wid); self.set_offsets(1., 0.)
            assert hole not in dialog.manual_overrides
            self.select_row(hole); self.set_offsets(0., 1.)
            np.testing.assert_allclose(dialog._effective_offset(wid), [1., 0.])
            self.select_row(wid)
            dialog.related_button.invoke(); self.settle()
            assert {wid, hole, outer}.issubset(dialog.tree.selection())
            assert len(dialog.manual_history) == history+2
            # Explicitly select exactly these three for the relative group test.
            dialog.tree.selection_set((wid, hole, outer)); dialog.tree.focus(wid); self.settle()
            self.set_offsets(3., 2.)
            np.testing.assert_allclose(dialog._effective_offset(hole), [2., 3.])
            np.testing.assert_allclose(dialog._effective_offset(outer), [2., 2.])
            assert len(dialog.manual_history) == history+3
            dialog.undo_button.invoke(); self.settle()
            np.testing.assert_allclose(dialog._effective_offset(wid), [1., 0.])
            np.testing.assert_allclose(dialog._effective_offset(hole), [0., 1.])
            assert outer not in dialog.manual_overrides
            # Ctrl-click the rough outer line adds it without accepting/moving it.
            self.select_row(wid); dialog.fit_course(); self.settle()
            before = self.viewport()
            x, y = self.pointer_at([40., 320.])
            self.pointer("<ButtonPress-1>", x, y, state=4)
            self.pointer("<ButtonRelease-1>", x, y, state=4); self.settle()
            assert set(dialog.tree.selection()) == {wid, outer}
            assert self.viewport() == before and outer not in dialog.manual_overrides
            assert dialog.tree.focus() == outer
            dialog.move_mode_button.invoke(); assert dialog.move_mode_var.get()
            count = len(dialog.manual_history)
            zoom = dialog.zoom
            self.pointer("<ButtonPress-1>", x, y)
            assert dialog._drag_state is not None and set(dialog._drag_state["offsets"]) == {wid, outer}
            self.pointer("<B1-Motion>", x+8, y-5)
            self.pointer("<ButtonRelease-1>", x+8, y-5); self.settle()
            delta = [8*dialog.resolution/zoom, 5*dialog.resolution/zoom]
            np.testing.assert_allclose(dialog._effective_offset(wid), np.array([1., 0.])+delta, atol=1e-9)
            np.testing.assert_allclose(dialog._effective_offset(outer), delta, atol=1e-9)
            np.testing.assert_allclose(dialog._effective_offset(hole), [0., 1.])
            assert len(dialog.manual_history) == count+1
            assert self.viewport() == before
            # A pending field on any member blocks the entire group atomically.
            self.select_row(wid); dialog.manual_east_var.set("9.0")
            dialog.tree.selection_set((wid, outer)); dialog.tree.focus(outer); self.settle()
            before_drafts = copy.deepcopy(dialog.manual_overrides)
            with patch.object(ui.messagebox, "showinfo") as info:
                dialog.nudge_buttons[1].invoke(); assert info.called
            assert before_drafts == dialog.manual_overrides
            dialog._pending_entries.pop(wid); dialog._sync_manual_fields()
            while len(dialog.manual_history) > history:
                dialog.undo_button.invoke(); self.settle()
            assert not dialog.manual_overrides and not dialog.selected_ids
            dialog.move_mode_button.invoke(); assert not dialog.move_mode_var.get()
            dialog.link_holes_check.invoke(); assert dialog.link_holes_var.get()
            self.select_row("103")
            return {"feature_only_and_hole_only": True, "related_outer_selection": True,
                    "group_preserves_relative_offsets": True, "ctrl_canvas_multiselection": True,
                    "group_drag_delta_m": delta, "one_group_undo": True,
                    "pending_member_blocks_entire_group": True}
        self.check("independent rough edits and grouped view movement preserve relative positions", separate_and_group_geometry)

        def pan_without_edit():
            self.select_row("103")
            assert not dialog.move_mode_var.get()
            draft = copy.deepcopy(dialog.manual_overrides); report = copy.deepcopy(dialog.report)
            before = (dialog.canvas.xview(), dialog.canvas.yview())
            x, y = self.pointer_centre("103")
            self.pointer("<ButtonPress-1>", x, y)
            self.pointer("<B1-Motion>", x+24, y+16)
            self.pointer("<ButtonRelease-1>", x+24, y+16)
            self.settle()
            assert before != (dialog.canvas.xview(), dialog.canvas.yview()), "Default drag did not pan"
            assert draft == dialog.manual_overrides and report == dialog.report
            # Clicking the same row must bring its outline back after panning,
            # even though the selected item itself has not changed.
            bx, by, bw, bh = dialog.tree.bbox("103", "way")
            dialog.tree.event_generate("<ButtonPress-1>", x=bx+bw//2, y=by+bh//2)
            dialog.tree.event_generate("<ButtonRelease-1>", x=bx+bw//2, y=by+bh//2)
            self.settle()
            points = np.asarray(dialog.features["103"]["fit_coords_m"] + dialog._effective_points("103"))
            centre = (points.min(axis=0)+points.max(axis=0))/2
            target = np.asarray(dialog._screen(*centre))
            viewport = np.array([dialog.canvas.canvasx(dialog.canvas.winfo_width()/2),
                                 dialog.canvas.canvasy(dialog.canvas.winfo_height()/2)])
            assert np.max(np.abs(target-viewport)) <= 3., (target, viewport)
            return {"default_drag_pans": True, "geometry_unchanged": True,
                    "clicking_same_row_returns_to_feature": True}
        self.check("default pan leaves feature geometry unchanged", pan_without_edit)

        def numeric_nudge_focus():
            self.set_offsets(2., 1.)
            assert dialog.manual_overrides["103"] == {"east_m": 2., "north_m": 1.}
            self.outline_matches("103", [2., 1.])
            entry = dialog.manual_entries[0]
            entry.focus_force(); self.root.update(); assert dialog.window.focus_get() is entry
            before = copy.deepcopy(dialog.manual_overrides)
            entry.event_generate("<KeyPress-Right>"); self.settle()
            assert before == dialog.manual_overrides and (view.shift_ew, view.shift_ns) == self.nudge
            dialog.step_buttons["0.25"].invoke()
            dialog.nudge_buttons[1].invoke(); self.settle()
            self.outline_matches("103", [2.25, 1.])
            dialog.undo_button.invoke(); self.settle()
            self.outline_matches("103", [2., 1.])
            # Uncommitted values survive row navigation and cannot be exported.
            dialog.manual_east_var.set("2.75")
            self.select_row("102"); self.select_row("103")
            assert dialog.manual_east_var.get() == "2.75"
            with patch.object(ui.messagebox, "showinfo") as info, patch.object(ui.filedialog, "asksaveasfilename") as chooser:
                dialog.apply_selected()
                assert info.called and not chooser.called
            dialog.manual_east_var.set("2.0"); dialog.manual_north_var.set("1.0")
            dialog.set_offsets_button.invoke(); self.settle()
            return {"numeric_preview_updated": True, "entry_arrow_ignored": True,
                    "nudge_m": .25, "undo_restored_previous_offset": True,
                    "pending_text_preserved_and_save_blocked": True}
        self.check("numeric offsets, nudge, focused-entry arrows and pending text", numeric_nudge_focus)

        def drag_conversion():
            dialog.move_mode_button.invoke(); assert dialog.move_mode_var.get()
            dialog._set_zoom(10.); self.settle()
            origin = [dialog.canvas.canvasx(0), dialog.canvas.canvasy(0)]
            assert all(v > 0 for v in origin), origin
            x, y = self.pointer_centre("103")
            count = len(dialog.manual_history)
            self.pointer("<ButtonPress-1>", x, y)
            assert dialog._drag_state is not None
            self.pointer("<B1-Motion>", x+6, y+4)
            self.pointer("<B1-Motion>", x+15, y+10)
            self.outline_matches("103", [5., -1.])
            assert dialog.manual_overrides["103"] == {"east_m": 2., "north_m": 1.}, "Gesture committed before release"
            self.pointer("<ButtonRelease-1>", x+15, y+10)
            self.settle()
            np.testing.assert_allclose(dialog._effective_offset("103"), [5., -1.], atol=1e-9)
            assert len(dialog.manual_history) == count+1, "A drag should create one undo item"
            dialog.undo_button.invoke(); self.settle(); self.outline_matches("103", [2., 1.])
            # Escape cancels a gesture without erasing the earlier numeric edit.
            x, y = self.pointer_centre("103")
            self.pointer("<ButtonPress-1>", x, y); self.pointer("<B1-Motion>", x+10, y-5)
            dialog.canvas.focus_force(); dialog.canvas.event_generate("<KeyPress-Escape>"); self.settle()
            self.pointer("<ButtonRelease-1>", x+10, y-5)
            assert dialog._drag_state is None
            self.outline_matches("103", [2., 1.])
            return {"zoom": 10., "canvas_origin_px": origin, "drag_pixels": [15, 10],
                    "expected_added_east_north_m": [3., -2.], "one_undo_item": True, "escape_cancelled_only_current_gesture": True}
        self.check("manual drag converts screen coordinates at nonzero zoom and pan", drag_conversion)

        def reset_and_layout():
            dialog.suggestion_button.invoke(); self.settle()
            assert "103" not in dialog.manual_overrides and "103" not in dialog.selected_ids
            self.set_offsets(2., 1.)
            dialog.original_position_button.invoke(); self.settle()
            self.outline_matches("103", [0., 0.]); assert "103" not in dialog.selected_ids
            dialog.undo_button.invoke(); self.settle(); self.outline_matches("103", [2., 1.])
            with patch.object(ui.messagebox, "askyesno", return_value=False) as question:
                before = copy.deepcopy(dialog.manual_overrides)
                dialog.start_analysis()
                assert question.called and dialog.operation is None and dialog.manual_overrides == before
                dialog.request_close(); assert not dialog.closed
            buttons = [w for w in descendants(dialog.window) if w.winfo_class() in ("Button", "TButton")]
            assert all(isinstance(w, ActionButton) for w in buttons)
            wx, wy = dialog.window.winfo_rootx(), dialog.window.winfo_rooty()
            right, bottom = wx+dialog.window.winfo_width(), wy+dialog.window.winfo_height()
            clipped = [w.cget("text") for w in buttons if not w.winfo_ismapped()
                       or w.winfo_rootx()<wx or w.winfo_rooty()<wy
                       or w.winfo_rootx()+w.winfo_width()>right
                       or w.winfo_rooty()+w.winfo_height()>bottom]
            assert not clipped, clipped
            assert dialog.canvas.winfo_height() >= 100 and dialog.tree.winfo_height() >= 100
            assert str(dialog.apply_button.cget("state")) == "normal"
            assert dialog.apply_button.cget("background") == "#245f94"
            self.capture(dialog.window, "Local_Manual_Review_1320x700.png")
            return {"suggestion_and_original_resets": True, "cancelled_discard_preserves_drafts": True,
                    "action_buttons": len(buttons), "clipped_buttons": clipped,
                    "canvas_height": dialog.canvas.winfo_height(), "tree_height": dialog.tree.winfo_height(),
                    "window": [dialog.window.winfo_width(), dialog.window.winfo_height()]}
        self.check("reset, discard protection and complete 1320x700 layout", reset_and_layout)

        first = folder / "manual_first.osm"
        second = folder / "manual_refined.osm"

        def save_checked_only():
            self.select_row("101"); self.set_offsets(1.25, .5)
            self.select_row("103"); dialog.uncheck_button.invoke(); self.settle()
            assert dialog.selected_ids == {"101"} and "103" in dialog.manual_overrides
            with patch.object(ui.messagebox, "askyesno", return_value=False) as ask, \
                 patch.object(ui.filedialog, "asksaveasfilename") as chooser:
                dialog.apply_selected(); assert ask.called and not chooser.called
                assert not first.exists() and "103" in dialog.manual_overrides
            real_apply = engine.apply_reviewed
            with patch.object(ui.messagebox, "askyesno", return_value=True), \
                 patch.object(ui.filedialog, "asksaveasfilename", return_value=str(first)), \
                 patch.object(engine, "apply_reviewed", wraps=real_apply) as apply:
                dialog.apply_button.invoke()
                self.pump_until(lambda: dialog.operation is None and view.osm_file == str(first))
                assert set(apply.call_args.kwargs["manual_overrides"]) == {"101"}
            delta = projected_way(first, 101, self.data)-projected_way(self.source, 101, self.data)
            np.testing.assert_allclose(delta, np.tile([1.25, .5], (len(delta), 1)), atol=1e-5)
            for wid in (102, 103):
                np.testing.assert_array_equal(projected_way(first, wid, self.data), projected_way(self.source, wid, self.data))
            assert self.options["local_osm_file"].get() == str(first)
            assert (view.shift_ew, view.shift_ns) == self.nudge
            assert not dialog.manual_history and not dialog.manual_overrides and not dialog.selected_ids
            assert dialog.report is None and any("STALE" in row[0] for row in self.statuses)
            manifest = json.loads(engine.manifest_path(first).read_text())
            assert [f["way_id"] for f in manifest["accepted_features"]] == [101]
            assert manifest["accepted_features"][0]["correction_method"] == "manual"
            return {"checked_saved_way": 101, "unchecked_draft_not_exported": 103,
                    "actual_added_residual_m": [1.25, .5], "saved_copy_selected_in_main_and_cfs": True,
                    "history_cleared_after_adoption": True}
        self.check("save only checked manual edits and adopt corrected source", save_checked_only)

        def refine_prior_correction():
            first_bytes = first.read_bytes()
            dialog.analyze_button.invoke()
            self.pump_until(lambda: dialog.report is not None and dialog.operation is None)
            assert dialog.features["101"]["status"] == "already_corrected"
            assert not dialog.features["101"]["movable"] and dialog.features["101"]["manual_movable"]
            self.select_row("101"); self.set_offsets(-.75, .25)
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(second)):
                dialog.apply_button.invoke()
                self.pump_until(lambda: dialog.operation is None and view.osm_file == str(second))
            delta = projected_way(second, 101, self.data)-projected_way(self.source, 101, self.data)
            np.testing.assert_allclose(delta, np.tile([.5, .75], (len(delta), 1)), atol=2e-5)
            previous = json.loads(engine.manifest_path(first).read_text())
            current = json.loads(engine.manifest_path(second).read_text())
            assert current["original_source_osm_path"] == str(self.source.resolve())
            assert current["original_source_osm_sha256"] == hashlib.sha256(source_bytes).hexdigest()
            assert current["parent_manifest_sha256"] == previous["manifest_sha256"]
            assert first.read_bytes() == first_bytes and self.source.read_bytes() == source_bytes
            assert (folder / "heightmap.npy").read_bytes() == terrain_bytes
            assert (view.shift_ew, view.shift_ns) == self.nudge
            # After a new manual draft, explicitly accepting discard closes.
            dialog.analyze_button.invoke()
            self.pump_until(lambda: dialog.report is not None and dialog.operation is None)
            self.select_row("102"); self.set_offsets(.5, 0.)
            with patch.object(ui.messagebox, "askyesno", return_value=True) as ask:
                dialog.request_close(); assert ask.called and dialog.closed
            assert view.local_review is None and view._can_interact()
            return {"previous_correction_manually_refined": True, "cumulative_residual_m": [.5, .75],
                    "original_and_parent_lineage_retained": True, "global_nudge_applied_only_by_consumer": True,
                    "originals_unchanged": True, "confirmed_close_discard": True}
        self.check("manual refinement retains prior correction lineage and global nudge", refine_prior_correction)

        def related_geometry_save():
            nonlocal dialog
            before_path = Path(view.osm_file)
            before_raw = before_path.read_bytes()
            view.local_alignment_button.invoke()
            self.dialog = view.local_review
            dialog = self.dialog
            dialog.window.geometry("1320x700+20+20")
            self.pump_until(lambda: dialog.report is not None and dialog.operation is None)
            hole = dialog.features["106"]["linked_ids"][0]
            outer = next(k for k, f in dialog.features.items() if f.get("boundary_role") == "outer")
            dialog.link_holes_check.invoke(); assert not dialog.link_holes_var.get()
            self.select_row("106"); self.set_offsets(2., 0.)
            self.select_row(hole); self.set_offsets(0., 1.)
            self.select_row(outer); self.set_offsets(.5, 0.)
            assert dialog.selected_ids == {"106", hole, outer}
            self.capture(dialog.window, "Related_Rough_Review_1320x700.png")
            target = folder / "relation_separate.osm"
            with patch.object(ui.filedialog, "asksaveasfilename", return_value=str(target)):
                dialog.apply_button.invoke()
                self.pump_until(lambda: dialog.operation is None and view.osm_file == str(target))
            root = ET.parse(target).getroot()
            relation = root.find("relation[@id='700']")
            new_outer = relation.find("member[@role='outer']").get("ref")
            new_hole = next(m.get("ref") for m in relation.findall("member")
                            if m.get("role") == "inner" and m.get("ref") != "107")
            assert int(new_hole) < 0 and not root.find(f"way[@id='{new_hole}']").findall("tag")
            for new_id, old_id, offset in ((106, 106, [2., 0.]), (new_hole, 106, [0., 1.]),
                                           (new_outer, 901, [.5, 0.])):
                diff = projected_way(target, new_id, self.data)-projected_way(before_path, old_id, self.data)
                np.testing.assert_allclose(diff, np.tile(offset, (len(diff), 1)), atol=1e-5)
            np.testing.assert_array_equal(projected_way(target, 107, self.data), projected_way(before_path, 107, self.data))
            assert self.options["local_osm_file"].get() == str(target)
            assert (view.shift_ew, view.shift_ns) == self.nudge
            assert before_path.read_bytes() == before_raw and self.source.read_bytes() == source_bytes
            dialog.analyze_button.invoke()
            self.pump_until(lambda: dialog.report is not None and dialog.operation is None)
            assert dialog.features["106"]["manual_movable"] and not dialog.features["106"]["linked_ids"]
            assert any(f.get("boundary_role") == "inner" and int(new_hole) in f.get("member_way_ids", [])
                       for f in dialog.features.values())
            return {"independent_feature_offset_m": [2., 0.], "independent_hole_offset_m": [0., 1.],
                    "independent_outer_offset_m": [.5, 0.], "untagged_cloned_hole_id": new_hole,
                    "other_tee_unchanged": True, "negative_ids_loaded_into_cfs": True,
                    "reanalysis_keeps_detached_hole_editable": True, "source_and_global_shift_preserved": True}
        self.check("separate rough and feature edits save, load and reanalyze with detached geometry", related_geometry_save)
        assert not self.errors, self.errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("manual_ui_validation"))
    args = parser.parse_args()
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    tests = TkChecks(output)
    failed = None
    try:
        with tempfile.TemporaryDirectory(prefix="tgc-manual-ui-") as temporary, \
             patch.object(ui.messagebox, "showerror", side_effect=lambda *a, **k: (_ for _ in ()).throw(AssertionError(a))):
            tests.run(Path(temporary))
    except Exception as exc:
        failed = {"error": repr(exc), "traceback": traceback.format_exc()}
        print(failed["traceback"], flush=True)
        if tests.dialog and not tests.dialog.closed:
            try: tests.capture(tests.dialog.window, "Failure_State.png")
            except Exception: pass
    finally:
        try: tests.cleanup()
        except Exception as exc:
            failed = failed or {"cleanup_error": repr(exc)}
    record = {"checks": tests.results, "passed": len(tests.results), "failed": failed,
              "tk_callback_errors": tests.errors, "tk_version": tk.TkVersion,
              "fixture_statuses": getattr(tests, "detector_statuses", {}),
              "limits": ["Analytical UI fixture, not terrain-edge ground truth", "No Windows native build or game execution"],
              "source_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                 for name in ("tgc_local_alignment_ui.py", "tgc_local_alignment.py", "tgc_local_alignment_export.py",
                              "tgc_local_alignment_topology.py", "osm_alignment_viewer.py", "tgc_cfs_display.py", "tgc_cfs_widgets.py")}}
    (output / "Manual_UI_Verification.json").write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps({"passed": len(tests.results), "failure": failed is not None, "output": str(output)}), flush=True)
    return failed is not None


if __name__ == "__main__":
    raise SystemExit(main())
