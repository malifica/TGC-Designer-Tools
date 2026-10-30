"""Asynchronous, explicit-review local tee/bunker alignment for the CFS viewer."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from tgc_cfs_widgets import action_button


_DISPLAY_TEXT = {
    "review_candidate": "Review suggested move",
    "keep_current": "Keep current position",
    "insufficient_evidence": "Insufficient terrain evidence",
    "unsupported_topology": "Needs geometry review",
    "already_corrected": "Already corrected",
    "manual_only": "Manual only - no detection",
    "terrain_supports_review_not_verified_ground_truth": "Terrain supports this move; review before accepting.",
    "too_few_native_cells": "Too few terrain cells to judge this feature.",
    "incomplete_terrain_support": "Terrain coverage is incomplete around this feature.",
    "weak_or_inconsistent_landform_evidence": "Terrain features do not consistently support a move.",
    "broad_ambiguous_optimum": "The terrain match is broad or ambiguous.",
    "shared_node_requires_joint_review": "Shared nodes require joint review.",
    "relation_member_requires_joint_review": "This feature belongs to a relation and needs joint review.",
    "smoothing_scales_disagree": "Different terrain smoothing levels suggest different moves.",
    "optimum_reaches_search_limit": "The best match reaches the search boundary; review the search radius.",
    "material_prior_sensitivity": "The suggested move changes too much with the fitting settings.",
    "no_material_move_supported": "The terrain does not support a meaningful move.",
    "improvement_not_supported_on_multiple_arcs": "Only part of the boundary supports this move.",
    "closed_unique_ring_required": "A closed outline with distinct boundary nodes is required.",
    "invalid_polygon": "The feature outline is invalid.",
    "unusable_polygon_coordinates": "The feature coordinates cannot be used.",
    "previously_reviewed_local_correction": "A reviewed local correction has already been applied.",
}


def _display_text(value):
    text = str(value)
    if text in _DISPLAY_TEXT:
        return _DISPLAY_TEXT[text]
    text = text.replace("_", " ")
    return text[:1].upper() + text[1:]


class LocalAlignmentDialog:
    """All Tk access stays on the calling thread; workers return through a queue."""

    def __init__(self, viewer, engine=None):
        self.viewer = viewer
        self.engine = engine
        self.source_file = str(viewer.osm_file)
        self.shift = (float(viewer.shift_ew), float(viewer.shift_ns))
        self.data = viewer.data
        self.grid = dict(viewer.grid)
        self.resolution = float(viewer.resolution)
        self.rows, self.cols = int(viewer.rows), int(viewer.cols)
        self.main_state = self._selection_callback(self.source_file)
        self.original_source = getattr(viewer, "_local_original_osm_file", self.source_file)
        self.original_hash = getattr(viewer, "_local_original_osm_sha256", None)
        self.report = None
        self.features = {}
        self.selected_ids = set()
        self.manual_overrides = {}
        self.manual_history = []
        self._pending_entries = {}
        self._syncing_manual_fields = False
        self._last_focus_id = None
        self._selection_row_hint = None
        self._clicked_focused_row = False
        self._drag_state = None
        self._pointer_action = None
        self.operation = None
        self.closed = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self._pump_id = None
        self._redraw_id = None
        self._start_id = None
        self.zoom = 1.0
        self._scroll_region = None
        self.photo = None
        self.image_item = None
        self.background = Image.fromarray(viewer.backgrounds["Hillshade"], "RGB")
        self.brightness = float(viewer.brightness_var.get())
        self.contrast = float(viewer.contrast_var.get())
        self.context_features = list(viewer.features)

        self.window = tk.Toplevel(viewer.window)
        self.window.title("Local Tee/Bunker Alignment — Review")
        self.window_width = min(1380, max(640, self.window.winfo_screenwidth() - 60))
        self.window_height = min(880, max(480, self.window.winfo_screenheight() - 80))
        self.window.geometry(f"{self.window_width}x{self.window_height}+20+20")
        self.window.minsize(min(1040, self.window_width), min(680, self.window_height))
        self.window.transient(viewer.window)
        self.window.protocol("WM_DELETE_WINDOW", self.request_close)
        self.window.bind("<Destroy>", self._destroyed, add="+")
        self._build_ui()
        viewer.local_review = self
        viewer._set_controls_enabled(False)
        try:
            self.window.grab_set()
        except tk.TclError:
            self._finish()
            raise
        self._set_controls()
        self._start_id = self.window.after(100, self._initial_analysis)

    def _selection_callback(self, previous, new_file=None, expected_state=None):
        callback = getattr(self.viewer, "osm_file_changed_callback", None)
        if callback is not None:
            return callback(previous, new_file, expected_state=expected_state)
        return None

    def _build_ui(self):
        outer = ttk.Frame(self.window, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        header = ttk.Frame(outer)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Review and move local course features", font=("TkDefaultFont", 13, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, text=f"CFS shift used: E/W {self.shift[0]:+.6g} m · N/S {self.shift[1]:+.6g} m").pack(side=tk.RIGHT)
        ttk.Label(outer, wraplength=1260, text=(
            "Select a row or click an object; click the outline for rough. Ctrl-click adds objects to move together. "
            "Only tees/bunkers receive automatic suggestions. Other surfaces are manual. Check moves before saving."
        )).pack(fill=tk.X, pady=(3, 8))

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X, pady=(0, 8))
        from tgc_local_feature_filters import FeatureFilters
        self._feature_filters = FeatureFilters(self, outer, before=controls)
        ttk.Label(controls, text="Automatic fit:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(controls, text="Search radius (m):").pack(side=tk.LEFT)
        self.radius_var = tk.StringVar(master=self.window, value="4")
        self.radius_box = ttk.Spinbox(controls, from_=1, to=8, increment=0.5, width=5, textvariable=self.radius_var)
        self.radius_box.pack(side=tk.LEFT, padx=(5, 14))
        self.tees_var = tk.BooleanVar(master=self.window, value=True)
        self.bunkers_var = tk.BooleanVar(master=self.window, value=True)
        self.tees_check = ttk.Checkbutton(controls, text="Tees", variable=self.tees_var)
        self.bunkers_check = ttk.Checkbutton(controls, text="Bunkers", variable=self.bunkers_var)
        self.tees_check.pack(side=tk.LEFT, padx=4)
        self.bunkers_check.pack(side=tk.LEFT, padx=(4, 16))
        self.analyze_button = action_button(controls, "Analyze", self.start_analysis, compact=True)
        self.analyze_button.pack(side=tk.LEFT, padx=3)
        self.cancel_button = action_button(controls, "Cancel analysis", self.cancel_analysis, compact=True)
        self.cancel_button.pack(side=tk.LEFT, padx=3)
        self.restore_button = action_button(controls, "Restore original OSM", self.restore_original, compact=True)
        self.restore_button.pack(side=tk.LEFT, padx=(16, 3))
        action_button(controls, "Close review", self.request_close, compact=True).pack(side=tk.RIGHT)

        self.status_var = tk.StringVar(master=self.window, value="Preparing review…")
        ttk.Label(outer, textvariable=self.status_var, wraplength=1260).pack(fill=tk.X)
        self.progress = ttk.Progressbar(outer, maximum=100, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(5, 8))

        split = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        split.pack(fill=tk.BOTH, expand=True)
        image_frame = ttk.Frame(split)
        list_frame = ttk.Frame(split, width=510)
        split.add(image_frame, weight=3)
        split.add(list_frame, weight=2)
        image_toolbar = ttk.Frame(image_frame)
        image_toolbar.pack(fill=tk.X)
        action_button(image_toolbar, "Zoom +", lambda: self._set_zoom(self.zoom * 1.25), compact=True).pack(side=tk.LEFT)
        action_button(image_toolbar, "Zoom -", lambda: self._set_zoom(self.zoom / 1.25), compact=True).pack(side=tk.LEFT, padx=4)
        action_button(image_toolbar, "Fit course", self.fit_course, compact=True).pack(side=tk.LEFT)
        action_button(image_toolbar, "Zoom to feature", self.zoom_to_feature, compact=True).pack(side=tk.LEFT, padx=4)
        ttk.Label(image_toolbar, text="Wheel: zoom · Right/middle drag: pan").pack(side=tk.LEFT, padx=6)
        canvas_frame = ttk.Frame(image_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.canvas = tk.Canvas(canvas_frame, background="#22252a", highlightthickness=0)
        hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=lambda a, b: self._scrolled(hbar, a, b),
                              yscrollcommand=lambda a, b: self._scrolled(vbar, a, b))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        hbar.grid(row=1, column=0, sticky="ew")
        vbar.grid(row=0, column=1, sticky="ns")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda _event: self._queue_redraw())
        self.canvas.bind("<ButtonPress-1>", self._pointer_down)
        self.canvas.bind("<B1-Motion>", self._pointer_drag)
        self.canvas.bind("<ButtonRelease-1>", self._pointer_up)
        self.canvas.bind("<Escape>", self._cancel_drag)
        for number in (2, 3):
            self.canvas.bind(f"<ButtonPress-{number}>", self._pan_start)
            self.canvas.bind(f"<B{number}-Motion>", self._pan)
            self.canvas.bind(f"<ButtonRelease-{number}>", self._pointer_up)
        for binding in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(binding, self._wheel)
        legend = ttk.Label(image_frame, text="Source: colors by surface; dashed = inner cutout. Orange: preview. Green: checked move.")
        legend.pack(anchor="w", pady=(4, 2), before=canvas_frame)
        self._build_manual_controls(image_frame, before=canvas_frame)

        ttk.Label(list_frame, text="Click [ ] to approve · Ctrl/Shift: group · Double-click row: check/uncheck").pack(anchor="w", padx=6)
        table_frame = ttk.Frame(list_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=(6, 0), pady=(5, 0))
        self.tree = ttk.Treeview(table_frame, columns=("kind", "way", "east", "north", "status"), selectmode="extended")
        self.tree.heading("#0", text="Use")
        self.tree.column("#0", width=46, minwidth=40, stretch=False)
        for name, text, width in (("kind", "Feature", 100), ("way", "Object ID", 105), ("east", "E/W m", 62),
                                  ("north", "N/S m", 62), ("status", "Status", 135)):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width, minwidth=width, stretch=(name == "status"))
        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        table_x = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=table_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        table_x.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("blocked", foreground="#747474")
        self.tree.tag_configure("manual", foreground="#175f9e")
        self.tree.tag_configure("rough", foreground="#725494")
        self.tree.bind("<<TreeviewSelect>>", self._row_selected)
        self.tree.bind("<ButtonPress-1>", self._tree_pressed)
        self.tree.bind("<Double-1>", self._toggle_row)
        self.tree.bind("<space>", self._toggle_row)
        self.tree.bind("<ButtonRelease-1>", self._check_column)
        check_row = ttk.Frame(list_frame)
        check_row.pack(fill=tk.X, padx=6, pady=5)
        self.check_button = action_button(check_row, "Check selected", lambda: self._check_rows(True), compact=True)
        self.uncheck_button = action_button(check_row, "Uncheck selected", lambda: self._check_rows(False), compact=True)
        self.check_button.pack(side=tk.LEFT)
        self.uncheck_button.pack(side=tk.LEFT, padx=4)
        check_all_row = ttk.Frame(list_frame)
        check_all_row.pack(fill=tk.X, padx=6)
        self.all_button = action_button(check_all_row, "Check all eligible", self.select_all, compact=True)
        self.clear_button = action_button(check_all_row, "Clear checks", self.clear_selection, compact=True)
        self.all_button.pack(side=tk.LEFT)
        self.clear_button.pack(side=tk.LEFT, padx=4)
        self.detail_var = tk.StringVar(master=self.window, value="Feature details will appear here.")
        ttk.Label(list_frame, textvariable=self.detail_var, wraplength=460, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=10)

        bottom = ttk.Frame(outer)
        # Reserve the action footer before the expandable pane, including on a
        # 1366x768 desktop where a fixed 880-pixel dialog would hide the save button.
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0), before=split)
        self.count_var = tk.StringVar(master=self.window, value="0 moves checked")
        ttk.Label(bottom, textvariable=self.count_var).pack(side=tk.LEFT)
        ttk.Label(bottom, wraplength=max(260, self.window_width - 510),
                  text="After saving, use CFS Apply + Rebuild Mask before generating the course.").pack(side=tk.LEFT, padx=20)
        self.apply_button = action_button(bottom, "Save checked corrections", self.apply_selected, primary=True, compact=True)
        self.apply_button.pack(side=tk.RIGHT)

    def _build_manual_controls(self, parent, before):
        frame = ttk.LabelFrame(parent, text="Manual adjustment - selected objects", padding=(6, 4))
        frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0), before=before)
        mode_row = ttk.Frame(frame)
        mode_row.pack(fill=tk.X)
        self.move_mode_var = tk.BooleanVar(master=self.window, value=False)
        self.move_mode_button = action_button(mode_row, "Move selected object: OFF", self.toggle_move_mode, compact=True)
        self.move_mode_button.pack(side=tk.LEFT)
        self.manual_hint_var = tk.StringVar(master=self.window, value="Select a row or click an object to adjust it.")
        ttk.Label(mode_row, textvariable=self.manual_hint_var, wraplength=370).pack(side=tk.LEFT, padx=8)

        link_row = ttk.Frame(frame)
        link_row.pack(fill=tk.X, pady=(3, 0))
        self.link_holes_var = tk.BooleanVar(master=self.window, value=True)
        self.link_holes_check = ttk.Checkbutton(
            link_row, text="Keep object and matching cutout together", variable=self.link_holes_var,
            command=self._link_mode_changed)
        self.link_holes_check.pack(side=tk.LEFT)
        self.related_button = action_button(link_row, "Select related boundaries", self.select_related_rough, compact=True)
        self.related_button.pack(side=tk.LEFT, padx=8)
        only_row = ttk.Frame(frame)
        only_row.pack(fill=tk.X, pady=(3, 0))
        self.independent_button = action_button(only_row, "Move only this object", self._v7_move_only_focused, compact=True)
        self.independent_button.pack(side=tk.LEFT)
        ttk.Label(only_row, text="Other checked moves stay checked.").pack(side=tk.LEFT, padx=8)

        offset_row = ttk.Frame(frame)
        offset_row.pack(fill=tk.X, pady=4)
        self.manual_east_var = tk.StringVar(master=self.window, value="0.000")
        self.manual_north_var = tk.StringVar(master=self.window, value="0.000")
        self.manual_entries = []
        for text, variable in (("E/W m", self.manual_east_var), ("N/S m", self.manual_north_var)):
            ttk.Label(offset_row, text=text).pack(side=tk.LEFT, padx=(0, 3))
            entry = ttk.Entry(offset_row, textvariable=variable, width=8)
            entry.pack(side=tk.LEFT, padx=(0, 8))
            entry.bind("<Return>", lambda _event: self.set_manual_offsets())
            self.manual_entries.append(entry)
            variable.trace_add("write", self._manual_entries_changed)
        self.set_offsets_button = action_button(offset_row, "Set offsets", self.set_manual_offsets, compact=True)
        self.set_offsets_button.pack(side=tk.LEFT, padx=(0, 8))
        self.nudge_buttons = []
        for text, east, north in (("W -", -1, 0), ("E +", 1, 0), ("N +", 0, 1), ("S -", 0, -1)):
            button = action_button(offset_row, text, lambda e=east, n=north: self.nudge_manual(e, n), compact=True)
            button.pack(side=tk.LEFT, padx=1)
            self.nudge_buttons.append(button)

        reset_row = ttk.Frame(frame)
        reset_row.pack(fill=tk.X)
        ttk.Label(reset_row, text="Step m:").pack(side=tk.LEFT, padx=(0, 3))
        self.nudge_step_var = tk.StringVar(master=self.window, value="0.25")
        self.step_buttons = {}
        for step in ("0.10", "0.25", "0.5", "1"):
            button = action_button(reset_row, step, lambda s=step: self.set_nudge_step(s), compact=True, padx=4)
            button.pack(side=tk.LEFT, padx=1)
            self.step_buttons[step] = button
        self.undo_button = action_button(reset_row, "Undo last move", self.undo_manual_move, compact=True)
        self.undo_button.pack(side=tk.LEFT, padx=(8, 3))
        self.suggestion_button = action_button(reset_row, "Accept suggestion", self.revert_manual_to_suggested, compact=True)
        self.suggestion_button.pack(side=tk.LEFT, padx=3)
        self.original_position_button = action_button(reset_row, "Original position", self.revert_manual_to_original, compact=True)
        self.original_position_button.pack(side=tk.LEFT, padx=3)

    # TGC_BETA7_ALL_FEATURES_V6_UI
    def _feature_visible(self, feature):
        filters = getattr(self, "_feature_filters", None)
        return filters is None or filters.visible(feature)

    def _initial_analysis(self):
        self._start_id = None
        if not self.closed:
            self.fit_course()
            self.start_analysis()

    def _set_controls(self):
        idle = not self.closed and self.operation is None
        for widget in (self.radius_box, self.tees_check, self.bunkers_check, self.analyze_button):
            widget.configure(state="normal" if idle else "disabled")
        has_report = idle and self.report is not None
        for widget in (self.check_button, self.uncheck_button, self.all_button, self.clear_button):
            widget.configure(state="normal" if has_report else "disabled")
        self.apply_button.configure(state="normal" if has_report and self.selected_ids else "disabled")
        self.cancel_button.configure(state="normal" if self.operation == "analyze" and not self.cancel_event.is_set() else "disabled")
        can_restore = idle and self.original_source and str(self.original_source) != self.source_file and bool(self.original_hash)
        self.restore_button.configure(state="normal" if can_restore else "disabled")
        feature = self.features.get(self.tree.focus(), {})
        manual_allowed = has_report and bool(feature.get("manual_movable"))
        for widget in (self.move_mode_button, self.set_offsets_button, self.suggestion_button, self.independent_button,
                       self.original_position_button, *self.manual_entries, *self.nudge_buttons,
                       *self.step_buttons.values()):
            widget.configure(state="normal" if manual_allowed else "disabled")
        self.undo_button.configure(state="normal" if has_report and self.manual_history else "disabled")
        self.link_holes_check.configure(state="normal" if has_report else "disabled")
        self.related_button.configure(state="normal" if has_report and feature.get("related_ids") else "disabled")
        self.move_mode_button.configure(text="Move selected object: " + ("ON" if self.move_mode_var.get() else "OFF"))
        for step, button in self.step_buttons.items():
            button.configure(text=f"[{step}]" if step == self.nudge_step_var.get() else step)
        self.canvas.configure(cursor="fleur" if manual_allowed and self.move_mode_var.get() else "hand2")
        if not feature:
            hint = "Select a row or click an object to adjust it."
        elif not feature.get("manual_movable"):
            hint = str(feature.get("manual_reason") or "This geometry cannot be moved independently.")
        elif self.move_mode_var.get():
            hint = f"Drag moves {len(self._movement_ids())} selected/linked object(s). Blank drag pans; Escape cancels."
        else:
            hint = f"{len(self._movement_ids())} object(s) will move. Turn ON to drag, or use offsets/nudges."
        self.manual_hint_var.set(hint)
        manual_count = len(self.selected_ids.intersection(self.manual_overrides))
        self.count_var.set(f"{len(self.selected_ids)} move(s) checked · {manual_count} manual")

    def _effective_offset(self, wid, include_drag=True):
        if include_drag and self._drag_state and wid in self._drag_state["offsets"]:
            return self._drag_state["offsets"][wid]
        manual = self.manual_overrides.get(wid)
        if manual is not None:
            return float(manual["east_m"]), float(manual["north_m"])
        feature = self.features.get(wid, {})
        return float(feature.get("proposed_east_m", 0)), float(feature.get("proposed_north_m", 0))

    def _effective_points(self, wid):
        east, north = self._effective_offset(wid)
        return [(float(x) + east, float(y) + north)
                for x, y in (self.features.get(wid, {}).get("fit_coords_m") or [])]

    def _is_checkable(self, wid):
        feature = self.features.get(wid, {})
        if wid in self.manual_overrides:
            east, north = self._effective_offset(wid, include_drag=False)
            return bool(feature.get("manual_movable") and math.hypot(east, north) > 1e-9)
        return bool(feature.get("movable"))

    def _sync_manual_fields(self):
        wid = self.tree.focus()
        east, north = self._effective_offset(wid)
        values = self._pending_entries.get(wid, (f"{east:.3f}", f"{north:.3f}"))
        self._syncing_manual_fields = True
        try:
            self.manual_east_var.set(values[0])
            self.manual_north_var.set(values[1])
        finally:
            self._syncing_manual_fields = False

    def _manual_entries_changed(self, *_args):
        if self._syncing_manual_fields:
            return
        wid = self.tree.focus()
        if wid not in self.features:
            return
        values = (self.manual_east_var.get(), self.manual_north_var.get())
        east, north = self._effective_offset(wid, include_drag=False)
        if values == (f"{east:.3f}", f"{north:.3f}"):
            self._pending_entries.pop(wid, None)
        else:
            self._pending_entries[wid] = values

    def _confirm_discard(self, action):
        moving = self._drag_state and any(abs(a - b) > 1e-9 for a, b in
                                          zip(self._drag_state["start_offset"], self._drag_state["offset"]))
        if not self.manual_overrides and not self._pending_entries and not moving:
            return True
        return messagebox.askyesno(
            "Unsaved manual adjustments", action + " and discard the unsaved manual adjustments?\n\n"
            "Checked and unchecked manual drafts have not been saved to OSM.", parent=self.window)

    def toggle_move_mode(self):
        if self.operation is not None or not self.features.get(self.tree.focus(), {}).get("manual_movable"):
            return
        self._cancel_drag()
        self.move_mode_var.set(not self.move_mode_var.get())
        self._set_controls()

    def _link_mode_changed(self):
        self._cancel_drag()
        self._show_feature_details()
        self._set_controls()
        self._queue_redraw()

    def _movement_ids(self, anchor=None):
        anchor = anchor or self.tree.focus()
        selected = {sid for sid in self.tree.selection()
                    if sid in self.features and self._feature_visible(self.features[sid])}
        if anchor in self.features and not self._feature_visible(self.features[anchor]):
            anchor = ""
        targets = selected if anchor in selected else {anchor}
        targets.intersection_update(self.features)
        if self.link_holes_var.get():
            pending = list(targets)
            while pending:
                for linked in self.features[pending.pop()].get("linked_ids", []):
                    linked = str(linked)
                    if linked in self.features and linked not in targets:
                        targets.add(linked)
                        pending.append(linked)
        return targets

    def select_related_rough(self):
        wid = self.tree.focus()
        if self.operation is not None or wid not in self.features:
            return
        self._cancel_drag()
        targets = set(self.tree.selection()) | {wid}
        targets.update(str(v) for v in self.features[wid].get("related_ids", [])
                       if str(v) in self.features)
        self._feature_filters.reveal(targets)
        self._last_focus_id = wid
        self.tree.selection_set(sorted(targets))
        self._row_selected()
        self.status_var.set(f"Selected {len(targets)} rows, including related boundaries. They move together; no correction was checked.")

    def _label(self, wid):
        feature = self.features.get(wid, {})
        return str(feature.get("display_id", wid))

    def _group_offsets(self, wid, east, north):
        before_east, before_north = self._effective_offset(wid, include_drag=False)
        delta = east - before_east, north - before_north
        return {target: {"east_m": self._effective_offset(target, False)[0] + delta[0],
                         "north_m": self._effective_offset(target, False)[1] + delta[1]}
                for target in self._movement_ids(wid)}

    def _remember_manual_group(self, targets, focus):
        self.manual_history.append({"focus": focus, "selection": tuple(self.tree.selection()), "states": {
            wid: (dict(self.manual_overrides[wid]) if wid in self.manual_overrides else None,
                  wid in self.selected_ids) for wid in targets}})

    def _commit_manual_group(self, offsets, *, focus=None, allow_pending=()):
        if self.operation is not None or self.report is None or not offsets:
            return False
        pending = set(offsets).intersection(self._pending_entries) - set(allow_pending)
        if pending:
            messagebox.showinfo("Unapplied offsets", "Use Set offsets for " +
                                ", ".join(self._label(w) for w in sorted(pending)) +
                                " before moving this group.", parent=self.window)
            return False
        try:
            offsets = self._backend().validate_manual_offsets(self.report, offsets)
        except Exception as exc:
            messagebox.showerror("Manual object move", str(exc), parent=self.window)
            return False
        if any(self.manual_overrides.get(wid) != value for wid, value in offsets.items()):
            self._remember_manual_group(offsets, focus or self.tree.focus())
        for wid, value in offsets.items():
            self.manual_overrides[wid] = dict(value)
            self._pending_entries.pop(wid, None)
            if self._is_checkable(wid):
                self.selected_ids.add(wid)
            else:
                self.selected_ids.discard(wid)
        self._refresh_checks()
        self._sync_manual_fields()
        self._show_feature_details()
        hidden = sum(not self._feature_visible(self.features[sid]) for sid in offsets)
        self.status_var.set(f"Adjusted {len(offsets)} object(s), including {hidden} linked hidden boundary/boundaries. Nonzero moves are checked for saving.")
        return True

    def set_nudge_step(self, step):
        value = str(step)
        if value in self.step_buttons:
            self.nudge_step_var.set(value)
            self._set_controls()

    def _set_manual_offset(self, wid, east, north):
        return self._commit_manual_group(self._group_offsets(wid, east, north), focus=wid, allow_pending=(wid,))

    def set_manual_offsets(self):
        wid = self.tree.focus()
        if self.operation is not None or wid not in self.features:
            return
        self._cancel_drag()
        try:
            east, north = float(self.manual_east_var.get()), float(self.manual_north_var.get())
        except ValueError:
            messagebox.showerror("Manual object move", "Enter numeric E/W and N/S offsets in metres, then press Set offsets.", parent=self.window)
            return
        self._set_manual_offset(wid, east, north)

    def nudge_manual(self, east_steps=0, north_steps=0):
        wid = self.tree.focus()
        if self.operation is not None or not self.features.get(wid, {}).get("manual_movable"):
            return
        if self._movement_ids(wid).intersection(self._pending_entries):
            messagebox.showinfo("Manual object move", "Press Set offsets to apply typed values before nudging this group.", parent=self.window)
            return
        self._cancel_drag()
        east, north = self._effective_offset(wid)
        step = float(self.nudge_step_var.get())
        self._set_manual_offset(wid, east + east_steps * step, north + north_steps * step)

    def undo_manual_move(self):
        if self.operation is not None or not self.manual_history:
            return
        self._cancel_drag()
        history = self.manual_history.pop()
        wid = history["focus"]
        for target, (previous, was_checked) in history["states"].items():
            if previous is None:
                self.manual_overrides.pop(target, None)
            else:
                self.manual_overrides[target] = previous
            self._pending_entries.pop(target, None)
            if was_checked and self._is_checkable(target):
                self.selected_ids.add(target)
            else:
                self.selected_ids.discard(target)
        self._feature_filters.reveal(history["selection"] or (wid,))
        self.tree.selection_set(history["selection"] or (wid,))
        self.tree.focus(wid)
        self.tree.see(wid)
        self._row_selected()
        self._refresh_checks()
        self.status_var.set(f"Undid the last manual move for {len(history['states'])} object(s).")

    def revert_manual_to_suggested(self):
        # Retain the callback name for existing bindings; now explicitly approve.
        return self._v7_set_checked(checked=True, use_suggestion=True)


    def revert_manual_to_original(self):
        self._cancel_drag()
        targets = self._movement_ids()
        self._commit_manual_group({wid: {"east_m": 0., "north_m": 0.} for wid in targets}, allow_pending=targets)

    def _validate_active_context(self):
        if self.viewer.closed or str(self.viewer.osm_file) != self.source_file:
            raise ValueError("The CFS OSM selection changed. Close this review and reopen it for the current file.")
        if (float(self.viewer.shift_ew), float(self.viewer.shift_ns)) != self.shift:
            raise ValueError("The global alignment changed. Analyze again from a new review.")
        self._selection_callback(self.source_file, expected_state=self.main_state)

    def _begin(self, operation, work):
        self.operation = operation
        self.cancel_event = threading.Event()
        self.progress.stop()
        self.progress.configure(mode="determinate" if operation == "analyze" else "indeterminate", value=0)
        if operation != "analyze":
            self.progress.start(30)
        self._set_controls()

        def worker():
            try:
                payload = work()
                if self.cancel_event.is_set() and operation != "apply":
                    self.events.put(("cancelled", operation))
                else:
                    self.events.put(("done", (operation, payload)))
            except Exception as exc:
                if self.cancel_event.is_set() and operation != "apply":
                    self.events.put(("cancelled", operation))
                else:
                    self.events.put(("error", (operation, str(exc))))

        threading.Thread(target=worker, name="TGC-Local-Alignment-" + operation, daemon=True).start()
        self._pump_id = self.window.after(50, self._pump)

    def _backend(self):
        if self.engine is not None:
            return self.engine
        import tgc_local_alignment
        return tgc_local_alignment

    def start_analysis(self):
        if self.closed or self.operation is not None:
            return
        try:
            self._validate_active_context()
            radius = float(self.radius_var.get())
            if not math.isfinite(radius) or not 1 <= radius <= 8:
                raise ValueError("Choose a search radius from 1 to 8 meters.")
            kinds = tuple(kind for kind, enabled in (("tee", self.tees_var.get()), ("bunker", self.bunkers_var.get())) if enabled)
            if not kinds:
                raise ValueError("Select tees, bunkers, or both.")
        except Exception as exc:
            messagebox.showerror("Local alignment", str(exc), parent=self.window)
            return
        if not self._confirm_discard("Analyze again"):
            return
        self._cancel_drag()
        self.report = None
        self.features.clear()
        self.selected_ids.clear()
        self.manual_overrides.clear()
        self.manual_history.clear()
        self._pending_entries.clear()
        self._last_focus_id = None
        self._feature_filters.clear_rows()
        self.status_var.set("Analyzing local terrain. No moves are selected or applied.")
        self.detail_var.set("You can pan and zoom while analysis runs.")
        self._queue_redraw()
        data, source, shift = self.viewer.data, self.source_file, self.shift

        def work():
            return self._backend().analyze(
                data, source, shift_ew=shift[0], shift_ns=shift[1], search_radius_m=radius, kinds=kinds,
                progress_callback=lambda percent, message: self.events.put(("progress", (percent, message))),
                cancel_event=self.cancel_event)

        self._begin("analyze", work)

    def cancel_analysis(self):
        if self.operation == "analyze":
            self.cancel_event.set()
            self.status_var.set("Cancelling analysis…")
            self._set_controls()

    def _prepare_overlay(self, path):
        # Parser/projection work runs in the worker; none of these functions use Tk.
        from osm_alignment_viewer import _parse_osm, _collect_overlay_features
        parsed = _parse_osm(path)
        features = _collect_overlay_features(parsed, self.data["projection"], self.grid, printf=lambda _message: None)
        return parsed, features

    def apply_selected(self):
        if self.closed or self.operation is not None or self.report is None or not self.selected_ids:
            return
        pending = self.selected_ids.intersection(self._pending_entries)
        if pending:
            messagebox.showinfo("Unapplied offsets", "Press Set offsets for " + ", ".join(self._label(w) for w in sorted(pending)) +
                                " before saving. Typed values have not changed its preview yet.", parent=self.window)
            return
        unchecked_drafts = (set(self.manual_overrides) | set(self._pending_entries)) - self.selected_ids
        if unchecked_drafts and not messagebox.askyesno(
                "Unchecked manual adjustments", f"{len(unchecked_drafts)} unchecked manual draft(s) will not be saved. "
                "Saving changes the source file and clears those drafts. Continue?", parent=self.window):
            return
        try:
            self._validate_active_context()
        except Exception as exc:
            messagebox.showerror("Local alignment", str(exc), parent=self.window)
            return
        filename = Path(self.source_file).stem + "_local_aligned_" + time.strftime("%Y%m%d_%H%M%S") + ".osm"
        destination = filedialog.asksaveasfilename(
            parent=self.window, title="Save corrected Local OSM copy", initialdir=str(self.viewer.heightmap_dir),
            initialfile=filename, defaultextension=".osm", filetypes=[("OpenStreetMap file", "*.osm")])
        if not destination:
            return
        try:
            self._validate_active_context()
        except Exception as exc:
            messagebox.showerror("Local alignment", str(exc), parent=self.window)
            return
        accepted = sorted(self.selected_ids)
        manual_overrides = {wid: dict(self.manual_overrides[wid]) for wid in accepted if wid in self.manual_overrides}
        report, source, shift, data = self.report, self.source_file, self.shift, self.viewer.data
        self.status_var.set(f"Saving {len(accepted)} checked move(s) to a separate OSM copy…")

        def work():
            result = self._backend().apply_reviewed(report, accepted, destination, current_data=data,
                                                    current_nudge=shift, current_osm_file=source,
                                                    manual_overrides=manual_overrides)
            try:
                parsed, features = self._prepare_overlay(result["output"])
            except Exception as exc:
                raise ValueError("The corrected file was saved at " + str(result["output"]) +
                                 " (audit: " + str(result.get("manifest", "see the neighboring .local_alignment.json file")) +
                                 "), but its preview could not be loaded. The current OSM selection was preserved: " + str(exc)) from exc
            return result, parsed, features

        self._begin("apply", work)

    def restore_original(self):
        if self.closed or self.operation is not None or not self.original_source or not self.original_hash:
            return
        if str(self.original_source) == self.source_file:
            return
        try:
            self._validate_active_context()
        except Exception as exc:
            messagebox.showerror("Restore original OSM", str(exc), parent=self.window)
            return
        if not self._confirm_discard("Restore the original OSM"):
            return
        self._cancel_drag()
        original, expected_hash = str(self.original_source), self.original_hash
        self.status_var.set("Verifying and loading the original OSM…")

        def work():
            if hashlib.sha256(Path(original).read_bytes()).hexdigest() != expected_hash:
                raise ValueError("The original OSM changed since this review. Select it manually and review its alignment.")
            parsed, features = self._prepare_overlay(original)
            return {"output": original, "restored": True}, parsed, features

        self._begin("restore", work)

    def _remember_original(self, payload):
        source = payload.get("original_source_osm_path") or payload.get("original_source_path")
        digest = payload.get("original_source_osm_sha256") or payload.get("original_source_sha256")
        if not source and payload.get("source_osm_path") == self.original_source:
            source, digest = self.original_source, payload.get("input_osm_sha256")
        if source and digest:
            self.original_source, self.original_hash = str(source), str(digest)
            self.viewer._local_original_osm_file = self.original_source
            self.viewer._local_original_osm_sha256 = self.original_hash

    def _analysis_done(self, report):
        self.report = report
        self.selected_ids.clear()
        self.manual_overrides.clear()
        self.manual_history.clear()
        self._pending_entries.clear()
        self._last_focus_id = None
        self.features = {str(feature.get("selection_id", feature["way_id"])): feature for feature in report.get("features", [])}
        self._remember_original(report)
        for wid, feature in self.features.items():
            self.tree.insert("", "end", iid=wid, text="[ ]")
        eligible = sum(bool(feature.get("movable")) for feature in self.features.values())
        rough_count = sum(f.get("kind") == "rough" for f in self.features.values())
        manual_count = sum(bool(f.get("manual_movable")) for f in self.features.values())
        self.status_var.set(f"Analysis complete: {eligible} suggestion(s); {manual_count} editable boundaries. Nothing is checked.")
        self.detail_var.set("Select a feature to inspect its terrain evidence and manual movement options.")
        candidates = [wid for wid, feature in self.features.items() if feature.get("movable")]
        first = candidates[0] if candidates else next(iter(self.features), None)
        if first is not None:
            self.tree.selection_set(first)
            self.tree.focus(first)
            self.tree.see(first)
            self._row_selected()
        self._refresh_checks()
        self._feature_filters.apply()
        self._queue_redraw()

    def _file_done(self, payload):
        result, parsed, features = payload
        new_file = str(result["output"])
        try:
            self._validate_active_context()
            self._selection_callback(self.source_file, new_file, expected_state=self.main_state)
        except Exception as exc:
            self.report = None
            self.selected_ids.clear()
            raise ValueError("The file is available at " + new_file + ", but the current selection was not replaced: " + str(exc)) from exc
        # A manual CFS nudge may not yet have been copied to the main entries.
        # Keep the exact reviewed placement when adopting this new source; the
        # callback above has already refused concurrent main-window changes.
        self.viewer._copy_alignment_to_main()
        self.viewer.osm_file = new_file
        self.viewer.osm_result = parsed
        self.viewer.features = features
        self.viewer._redraw_overlay()
        self.viewer._set_progress(100, "Local OSM changed. Apply + Rebuild Mask before generating.")
        self.viewer.printf("CFS Local OSM selected: " + new_file + "; Apply + Rebuild Mask is required.")
        self.source_file = new_file
        self.context_features = list(features)
        self.main_state = self._selection_callback(new_file)
        self._remember_original(result)
        self.report = None
        self.features.clear()
        self.selected_ids.clear()
        self.manual_overrides.clear()
        self.manual_history.clear()
        self._pending_entries.clear()
        self._last_focus_id = None
        self._cancel_drag()
        self._feature_filters.clear_rows()
        self.detail_var.set("The review was cleared because the selected OSM changed. Analyze again to review remaining features.")
        if result.get("restored"):
            self.status_var.set("Original OSM selected. The global nudge is unchanged. Close review and use Apply + Rebuild Mask.")
        else:
            self.status_var.set("Checked corrections saved and selected. Close review and use Apply + Rebuild Mask before generating the course.")
        self._queue_redraw()

    def _pump(self):
        self._pump_id = None
        if self.closed:
            return
        for _ in range(100):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.progress.configure(value=max(0, min(100, float(payload[0]))))
                if not self.cancel_event.is_set():
                    self.status_var.set(str(payload[1]))
                continue
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.operation = None
            if kind == "done":
                operation, result = payload
                try:
                    if operation == "analyze":
                        self._analysis_done(result)
                    else:
                        self._file_done(result)
                    self.progress.configure(value=100)
                except Exception as exc:
                    self.status_var.set(str(exc))
                    messagebox.showerror("Local alignment", str(exc), parent=self.window)
            elif kind == "cancelled":
                self.status_var.set("Analysis cancelled. No OSM selection was changed.")
            elif kind == "error":
                self.status_var.set("Local alignment could not finish: " + payload[1])
                messagebox.showerror("Local alignment", payload[1], parent=self.window)
            self._set_controls()
            if self.close_requested:
                self.close_requested = False
                self.request_close()
                return
        if self.operation is not None:
            self._pump_id = self.window.after(50, self._pump)

    def _check_rows(self, checked):
        return self._v7_set_checked(checked=bool(checked))


    def _toggle_row(self, event=None):
        if self.operation is not None or self.report is None:
            return "break"
        mouse = event is not None and getattr(event, "num", None) in (1, "1")
        if mouse:
            self._v7_skip_release = True
            self._v7_press_row = None
            wid = self.tree.identify_row(event.y)
            if not wid or self.tree.identify_region(event.x, event.y) not in {"tree", "cell"}:
                return "break"
            # First checkbox release already performed the single action. A
            # double press must not toggle again or let its second release undo it.
            if self.tree.identify_column(event.x) == "#0":
                return "break"
            self.tree.focus(wid)
            if wid not in self.tree.selection():
                self.tree.selection_set(wid)
            rows = [wid]
        else:
            rows = self._v7_review_rows()
        if rows:
            self._v7_set_checked(rows, not all(wid in self.selected_ids for wid in rows))
        return "break"


    def _check_column(self, event):
        if getattr(self, "_v7_skip_release", False):
            self._v7_skip_release = False
            self._v7_press_row = None
            self._clicked_focused_row = False
            return "break"
        wid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        same_press = (wid and wid == getattr(self, "_v7_press_row", None)
                      and column == getattr(self, "_v7_press_column", None))
        px, py = getattr(self, "_v7_press_xy", (event.x, event.y))
        click = same_press and abs(event.x - px) <= 6 and abs(event.y - py) <= 6
        self._v7_press_row = None
        if (click and column == "#0"
                and self.tree.identify_region(event.x, event.y) in {"tree", "cell"}):
            self.tree.focus(wid)
            self._v7_set_checked([wid], wid not in self.selected_ids)
            self._clicked_focused_row = False
            return "break"
        if click and wid in self.tree.selection():
            self._row_selected()
            if self._clicked_focused_row and self.tree.focus() == wid:
                self.zoom_to_feature()
        self._clicked_focused_row = False


    def select_all(self):
        if self.operation is None and self.report is not None:
            self.selected_ids.update(wid for wid, feature in self.features.items()
                                     if self._feature_visible(feature) and self._is_checkable(wid))
            self._refresh_checks()

    def clear_selection(self):
        if self.operation is None:
            self.selected_ids.clear()
            self._refresh_checks()

    def _refresh_checks(self):
        for wid in self.tree.get_children():
            feature = self.features[wid]
            east, north = self._effective_offset(wid, include_drag=False)
            manual = wid in self.manual_overrides
            status = ("Manual move" if math.hypot(east, north) > 1e-9 else "Manual · original position") if manual else _display_text(feature.get("status", "unknown"))
            if not manual and feature.get("status") == "unsupported_topology" and feature.get("manual_movable"):
                status = "Manual geometry move"
            tags = ("manual",) if manual else (("rough",) if feature.get("kind") == "rough" and feature.get("manual_movable")
                                               else (() if feature.get("manual_movable") else ("blocked",)))
            self.tree.item(wid, text="[x]" if wid in self.selected_ids else "[ ]", tags=tags,
                           values=(feature.get("label", feature.get("kind", "").title()), self._label(wid),
                                   f"{east:+.3f}", f"{north:+.3f}", status))
        self._set_controls()
        self._feature_filters.refresh_note()
        self._queue_redraw()

    def _tree_pressed(self, event):
        self._selection_row_hint = self.tree.identify_row(event.y) or None
        self._clicked_focused_row = self._selection_row_hint == self.tree.focus()
        self._v7_press_row = self._selection_row_hint
        self._v7_press_column = self.tree.identify_column(event.x)
        self._v7_press_xy = (event.x, event.y)
        self._v7_skip_release = False


    def _row_selected(self, _event=None):
        selection = self.tree.selection()
        if self._selection_row_hint in selection:
            self.tree.focus(self._selection_row_hint)
        self._selection_row_hint = None
        if self.tree.focus() not in selection and selection:
            self.tree.focus(selection[-1])
        wid = self.tree.focus()
        if wid != self._last_focus_id:
            self._cancel_drag()
            self._last_focus_id = wid
            self.zoom_to_feature()
        self._sync_manual_fields()
        self._show_feature_details()
        self._set_controls()
        self._queue_redraw()

    def _select_canvas_feature(self, wid, *, additive=False, keep_group=False):
        # A map pick must keep the viewport still, including when Tk delivers
        # the TreeviewSelect event later during the same drag gesture.
        self._selection_row_hint = None
        self._clicked_focused_row = False
        selection = set(self.tree.selection())
        if additive:
            if wid in selection:
                selection.remove(wid)
                if selection:
                    wid = sorted(selection)[-1]
            else:
                selection.add(wid)
        elif not keep_group or wid not in selection:
            selection = {wid}
        self._last_focus_id = wid if selection else ""
        self.tree.focus(wid if selection else "")
        self.tree.selection_set(sorted(selection))
        if selection:
            self.tree.see(wid)
        self._row_selected()

    def _show_feature_details(self):
        wid = self.tree.focus()
        feature = self.features.get(wid)
        if feature is not None:
            reasons = feature.get("reasons", [])
            if isinstance(reasons, str):
                reasons = [reasons]
            east, north = self._effective_offset(wid)
            label = "Manual" if wid in self.manual_overrides else ("Offset" if feature.get("kind") == "rough" else "Suggested")
            manual_reason = feature.get("manual_reason")
            if not feature.get("manual_movable") and manual_reason:
                reasons = [manual_reason] + list(reasons)
            group = self._movement_ids(wid)
            related = feature.get("related_ids", [])
            connection = (f"Moves with {len(group) - 1} other selected/linked boundary(s). " if len(group) > 1 else "Moves independently. ")
            if related:
                connection += f"{len(related)} related boundary(s) available."
            if feature.get("kind") == "rough":
                reasons = ["Manual only; rough is not analyzed against terrain."]
            self.detail_var.set(f"{feature.get('label', feature.get('kind', '').title())} · {self._label(wid)}\n"
                                f"{label} E/W {east:+.3f} m, N/S {north:+.3f} m\n" + connection + "\n" +
                                "\n".join(dict.fromkeys(_display_text(value) for value in reasons)))
        else:
            self.detail_var.set("Select an object or rough boundary to inspect and move it.")

    def _screen(self, x, y):
        return x / self.resolution * self.zoom, (self.rows - y / self.resolution) * self.zoom

    def _scrolled(self, scrollbar, first, last):
        scrollbar.set(first, last)
        self._queue_redraw()

    def _shows_effective_outline(self, wid):
        feature = self.features[wid]
        return bool(feature.get("movable") or wid in self.manual_overrides
                    or (wid in self._movement_ids() and feature.get("manual_movable")))

    def _polygon_hit(self, points, x, y):
        """Rank a visible polygon hit in canvas pixels, independent of zoom."""
        if len(points) < 3:
            return None
        if any(len(p) != 2 or not all(math.isfinite(float(v)) for v in p) for p in points):
            return None
        points = [self._screen(float(px), float(py)) for px, py in points]
        inside, distance2, twice_area = False, math.inf, 0.
        for index, (ax, ay) in enumerate(points):
            bx, by = points[index - 1]
            length2 = (bx - ax) ** 2 + (by - ay) ** 2
            t = max(0., min(1., ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length2)) if length2 else 0.
            distance2 = min(distance2, (x - ax - t * (bx - ax)) ** 2 + (y - ay - t * (by - ay)) ** 2)
            twice_area += ax * by - bx * ay
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
        area = abs(twice_area) / 2.
        if distance2 <= 8 ** 2:
            return 0, distance2, area
        if inside:
            return 1, area, distance2
        return None

    def _hit_feature(self, x, y):
        x, y = self.canvas.canvasx(x), self.canvas.canvasy(y)
        focused, hits = self.tree.focus(), []
        selected = self._movement_ids()
        for wid, feature in self.features.items():
            if not self._feature_visible(feature):
                continue
            rings = [feature.get("fit_coords_m") or []]
            if self._shows_effective_outline(wid):
                rings.append(self._effective_points(wid))
            for points in rings:
                if feature.get("is_closed", True):
                    rank = self._polygon_hit(points, x, y)
                else:
                    from tgc_local_feature_filters import line_hit
                    rank = line_hit(self, points, x, y)
                if rank is not None:
                    if feature.get("kind") == "rough" and rank[0] == 1 and wid not in selected:
                        continue
                    # Choose the nearest visible boundary, then the smallest
                    # containing polygon. Exact ties keep the current focus.
                    hits.append((rank, wid != focused, feature.get("kind") == "rough", str(wid)))
        return min(hits)[3] if hits else None

    def _pointer_down(self, event):
        self.canvas.focus_set()
        self._cancel_drag()
        wid = None
        additive = bool(getattr(event, "state", 0) & 0x0004)
        if self.operation is None and self.report is not None:
            wid = self._hit_feature(event.x, event.y)
            if wid is not None:
                self._select_canvas_feature(wid, additive=additive, keep_group=self.move_mode_var.get())
                if additive:
                    return "break"
        if (wid is not None and self.move_mode_var.get()
                and self.features[wid].get("manual_movable")):
            targets = self._movement_ids(wid)
            if targets.intersection(self._pending_entries):
                self.status_var.set("Press Set offsets to apply typed values before dragging this group.")
                return "break"
            blocked = [target for target in targets if not self.features[target].get("manual_movable")]
            if blocked:
                self.status_var.set("Cannot move this selection: " + ", ".join(self._label(t) for t in blocked) + " needs geometry review.")
                return "break"
            offset = self._effective_offset(wid, include_drag=False)
            offsets = {target: self._effective_offset(target, include_drag=False) for target in targets}
            self._drag_state = {"wid": wid, "start_x": self.canvas.canvasx(event.x),
                                "start_y": self.canvas.canvasy(event.y), "start_offset": offset, "offset": offset,
                                "start_offsets": offsets, "offsets": dict(offsets)}
            self._pointer_action = "manual"
        else:
            self._pan_start(event)
        return "break"

    def _pointer_drag(self, event):
        if self._pointer_action != "manual" or self._drag_state is None:
            if self._pointer_action == "pan":
                self._pan(event)
            return "break"
        drag = self._drag_state
        east = (self.canvas.canvasx(event.x) - drag["start_x"]) * self.resolution / self.zoom
        north = -(self.canvas.canvasy(event.y) - drag["start_y"]) * self.resolution / self.zoom
        low_x, high_x, low_y, high_y = -math.inf, math.inf, -math.inf, math.inf
        for wid, start in drag["start_offsets"].items():
            if self.features[wid].get("kind") in {"rough", "heavyrough", "wood"}:
                continue
            points = self.features[wid]["fit_coords_m"]
            xs = [float(p[0]) + start[0] for p in points]
            ys = [float(p[1]) + start[1] for p in points]
            low_x, high_x = max(low_x, -min(xs)), min(high_x, self.cols * self.resolution - max(xs))
            low_y, high_y = max(low_y, -min(ys)), min(high_y, self.rows * self.resolution - max(ys))
        bounded = max(low_x, min(high_x, east)), max(low_y, min(high_y, north))
        at_edge = bounded != (east, north)
        drag["offsets"] = {wid: (start[0] + bounded[0], start[1] + bounded[1])
                           for wid, start in drag["start_offsets"].items()}
        drag["offset"] = drag["offsets"][drag["wid"]]
        self._sync_manual_fields()
        self._show_feature_details()
        self.status_var.set(("Terrain edge reached. " if at_edge else "") +
                            f"Dragging {len(drag['offsets'])} object(s): additional E/W {bounded[0]:+.3f} m, N/S {bounded[1]:+.3f} m. "
                            "Release to keep this draft; Escape cancels this drag.")
        self._queue_redraw()
        return "break"

    def _pointer_up(self, _event=None):
        drag = self._drag_state
        self._drag_state = None
        self._pointer_action = None
        if drag is not None:
            if any(abs(a - b) > 1e-9 for a, b in zip(drag["start_offset"], drag["offset"])):
                self._commit_manual_group({wid: {"east_m": offset[0], "north_m": offset[1]}
                                           for wid, offset in drag["offsets"].items()}, focus=drag["wid"])
            self._sync_manual_fields()
            self._queue_redraw()
        return "break"

    def _cancel_drag(self, _event=None):
        had_drag = self._drag_state is not None
        self._drag_state = None
        self._pointer_action = None
        if had_drag:
            self._sync_manual_fields()
            self._show_feature_details()
            self.status_var.set("Current drag cancelled. Earlier manual adjustments are unchanged.")
            self._queue_redraw()
        return "break"

    def _pan_start(self, event):
        self._cancel_drag()
        self._pointer_action = "pan"
        self.canvas.scan_mark(event.x, event.y)

    def _pan(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._queue_redraw()

    def _wheel(self, event):
        if self._drag_state is not None:
            return "break"
        delta, number = getattr(event, "delta", 0), getattr(event, "num", None)
        factor = 1.25 if delta > 0 or number == 4 else 1 / 1.25
        self._set_zoom(self.zoom * factor, (event.x, event.y))
        return "break"

    def _set_zoom(self, zoom, anchor=None):
        if self.closed:
            return
        zoom = max(0.1, min(30.0, float(zoom)))
        ax, ay = anchor or (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        x, y = self.canvas.canvasx(ax) / self.zoom, self.canvas.canvasy(ay) / self.zoom
        self.zoom = zoom
        self._scroll_region = (0, 0, self.cols * zoom, self.rows * zoom)
        self.canvas.configure(scrollregion=self._scroll_region)
        self.canvas.xview_moveto(max(0, (x * zoom - ax) / (self.cols * zoom)))
        self.canvas.yview_moveto(max(0, (y * zoom - ay) / (self.rows * zoom)))
        self._queue_redraw()

    def fit_course(self):
        if not self.closed:
            self._set_zoom(min(max(100, self.canvas.winfo_width() - 10) / self.cols,
                               max(100, self.canvas.winfo_height() - 10) / self.rows))
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)

    def zoom_to_feature(self):
        feature = self.features.get(self.tree.focus())
        if not feature:
            return
        points = list(feature.get("fit_coords_m") or []) + self._effective_points(self.tree.focus())
        points = [p for p in points if len(p) == 2 and all(math.isfinite(float(v)) for v in p)]
        if not points:
            return
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        width, height = max(24, max(xs) - min(xs) + 16), max(24, max(ys) - min(ys) + 16)
        self._set_zoom(min(max(100, self.canvas.winfo_width() - 24) * self.resolution / width,
                           max(100, self.canvas.winfo_height() - 24) * self.resolution / height))
        cx, cy = self._screen((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
        self.canvas.xview_moveto(max(0, (cx - self.canvas.winfo_width() / 2) / (self.cols * self.zoom)))
        self.canvas.yview_moveto(max(0, (cy - self.canvas.winfo_height() / 2) / (self.rows * self.zoom)))
        self._queue_redraw()

    def _queue_redraw(self):
        if not self.closed and self._redraw_id is None:
            self._redraw_id = self.window.after(25, self._redraw)

    def _outline(self, points, color, width=1, dash=None, closed=True):
        coords = []
        for x, y in points:
            if not math.isfinite(float(x)) or not math.isfinite(float(y)):
                return
            coords.extend(self._screen(float(x), float(y)))
        if len(coords) >= 4:
            if closed:
                coords.extend(coords[:2])
            options = {"fill": color, "width": width, "tags": ("outlines",)}
            if dash:
                options["dash"] = dash
            self.canvas.create_line(*coords, **options)

    def _redraw(self):
        self._redraw_id = None
        if self.closed:
            return
        from tgc_cfs_display import viewport_tile
        region = (0, 0, self.cols * self.zoom, self.rows * self.zoom)
        if self._scroll_region != region:
            self._scroll_region = region
            self.canvas.configure(scrollregion=region)
        tile, origin = viewport_tile(self.background, self.zoom, self.canvas.canvasx(0), self.canvas.canvasy(0),
                                     max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()),
                                     self.brightness, self.contrast)
        if tile is not None:
            self.photo = ImageTk.PhotoImage(tile, master=self.canvas)
            if self.image_item is None:
                self.image_item = self.canvas.create_image(*origin, image=self.photo, anchor=tk.NW, tags=("background",))
            else:
                self.canvas.coords(self.image_item, *origin)
                self.canvas.itemconfigure(self.image_item, image=self.photo, state="normal")
            self.canvas.tag_lower("background")
        elif self.image_item is not None:
            self.canvas.itemconfigure(self.image_item, state="hidden")
        self.canvas.delete("outlines")
        for feature in self.context_features:
            if not self._feature_visible(feature):
                continue
            points = [(col * self.resolution + self.shift[0], row * self.resolution + self.shift[1])
                      for col, row in feature.get("points", [])]
            self._outline(points, "#89939b", 1, closed=bool(feature.get("closed", False)))
        focused = self.tree.focus()
        selected = self._movement_ids()
        ordered = [(wid, f) for wid, f in self.features.items() if wid != focused]
        if focused in self.features:
            ordered.append((focused, self.features[focused]))
        from tgc_local_feature_filters import COLORS, filter_kind
        for wid, feature in ordered:
            if not self._feature_visible(feature):
                continue
            width = 3 if wid in selected else 1.5
            color = COLORS[filter_kind(feature)]
            self._outline(feature.get("fit_coords_m") or [], color, width + (1.5 if wid == focused else 0),
                          dash=(3, 3) if feature.get("boundary_role") == "inner" else None,
                          closed=feature.get("is_closed", True))
            if self._shows_effective_outline(wid):
                self._outline(self._effective_points(wid), "#59d98e" if wid in self.selected_ids else "#ffb54d", width, (5, 3), closed=feature.get("is_closed", True))

    def request_close(self):
        if self.closed:
            return
        if self.operation == "apply":
            self.close_requested = True
            self.status_var.set("Finishing the saved correction and updating CFS; this review will then close.")
            return
        if not self._confirm_discard("Close review"):
            return
        self._cancel_drag()
        self.cancel_event.set()
        self._finish()

    def _destroyed(self, event):
        if event.widget is self.window and not self.closed:
            self._finish(destroy=False)

    def _finish(self, destroy=True):
        if self.closed:
            return
        self.closed = True
        self.cancel_event.set()
        for attribute in ("_pump_id", "_redraw_id", "_start_id"):
            token = getattr(self, attribute)
            if token is not None:
                try:
                    self.window.after_cancel(token)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        try:
            self.progress.stop()
            if self.window.grab_current() is self.window:
                self.window.grab_release()
        except tk.TclError:
            pass
        if getattr(self.viewer, "local_review", None) is self:
            self.viewer.local_review = None
            if not self.viewer.closed:
                self.viewer._set_controls_enabled(self.viewer.ready and not self.viewer.busy)
        if destroy:
            try:
                self.window.destroy()
            except tk.TclError:
                pass

    # TGC_BETA7_LOCAL_ACCEPT_V7
    def _v7_review_rows(self, rows=None):
        if rows is None:
            rows = self.tree.selection() or (self.tree.focus(),)
        return sorted({str(wid) for wid in rows if str(wid) in self.features
                       and self._feature_visible(self.features[str(wid)])})


    def _v7_linked_rows(self, wid):
        targets = {wid}
        if self.link_holes_var.get():
            pending = [wid]
            while pending:
                for other in self.features[pending.pop()].get("linked_ids", []):
                    other = str(other)
                    if other not in self.features:
                        raise ValueError("A linked boundary is missing from this review. Analyze again before accepting.")
                    if other not in targets:
                        targets.add(other)
                        pending.append(other)
        return targets


    def _v7_feedback(self, message, *, error=False):
        self.status_var.set(message)
        if error:
            messagebox.showerror("Local alignment approval", message, parent=self.window)
        else:
            messagebox.showinfo("Local alignment approval", message, parent=self.window)


    def _v7_plan_approval(self, rows, use_suggestion=False):
        """Read-only plan. Automatic confidence is never changed on the report."""
        offsets, warnings, skipped, anchors = {}, [], [], []
        for wid in rows:
            feature = self.features[wid]
            manual = wid in self.manual_overrides and not use_suggestion
            # Other surfaces can be checked after a manual edit, but have no fit proposal.
            if not manual and (feature.get("kind") not in {"tee", "bunker"}
                               or feature.get("manual_only")
                               or feature.get("status") in {"manual_only", "already_corrected"}):
                skipped.append(self._label(wid) + ": no new automatic suggestion")
                continue
            if manual:
                east, north = self._effective_offset(wid, include_drag=False)
            else:
                if "proposed_east_m" not in feature or "proposed_north_m" not in feature:
                    skipped.append(self._label(wid) + ": no suggested position")
                    continue
                east, north = float(feature["proposed_east_m"]), float(feature["proposed_north_m"])
            if not math.isfinite(east) or not math.isfinite(north):
                raise ValueError(self._label(wid) + ": the displayed offset is not finite. Analyze again.")
            if math.hypot(east, north) <= 1e-9:
                skipped.append(self._label(wid) + ": zero offset / already at the original position")
                continue
            if not feature.get("manual_movable"):
                raise ValueError(self._label(wid) + ": " + str(feature.get("manual_reason")
                                 or "This boundary has invalid or incomplete geometry."))
            group = self._v7_linked_rows(wid)
            # Explicit manual groups retain their individual relative offsets. A fit
            # proposal and its matching cutout instead receive the same source offset.
            if manual:
                old_e, old_n = self._effective_offset(wid, include_drag=False)
                proposed = {target: {"east_m": self._effective_offset(target, False)[0] + east - old_e,
                                     "north_m": self._effective_offset(target, False)[1] + north - old_n}
                            for target in group}
            else:
                proposed = {target: {"east_m": east, "north_m": north} for target in group}
            for target, value in proposed.items():
                if target in offsets and any(abs(offsets[target][key] - value[key]) > 1e-8
                                             for key in ("east_m", "north_m")):
                    raise ValueError("Selected linked boundaries have different proposed positions. "
                                     "Accept one suggestion at a time, or review the linked-cutout setting. "
                                     "No checks or positions were changed.")
                offsets[target] = value
            anchors.append(wid)
            if not manual and not feature.get("movable"):
                reasons = feature.get("reasons", [])
                if isinstance(reasons, str):
                    reasons = [reasons]
                reason = "; ".join(_display_text(str(r)) for r in reasons[:3])
                warnings.append(f"{self._label(wid)}: E/W {east:+.3f} m, N/S {north:+.3f} m\n"
                                + (reason or _display_text(feature.get("status", "insufficient_evidence"))))
        return offsets, warnings, skipped, anchors


    def _v7_set_checked(self, rows=None, checked=True, *, use_suggestion=False):
        if (self.operation is not None or self.report is None
                or getattr(self, "_v7_accepting", False)):
            return False
        rows = self._v7_review_rows(rows)
        if not rows:
            self.status_var.set("Select a visible row first. Click [ ] or use Check selected to approve a move.")
            return False
        self._cancel_drag()
        self._v7_accepting = True
        try:
            if not checked:
                targets = set()
                for wid in rows:
                    targets.update(self._v7_linked_rows(wid))
                changed = targets.intersection(self.selected_ids)
                if changed:
                    self._remember_manual_group(targets, self.tree.focus())
                    self.selected_ids.difference_update(targets)
                self._refresh_checks()
                self._show_feature_details()
                self.status_var.set(f"Unchecked {len(changed)} move(s). Preview positions are retained; no OSM was changed.")
                return True
            offsets, warnings, skipped, anchors = self._v7_plan_approval(rows, use_suggestion)
            if not offsets:
                detail = "\n".join(skipped[:5])
                self._v7_feedback("There is no nonzero move to accept for these rows. "
                                  "Use Move or Set offsets for a manual adjustment." + ("\n\n" + detail if detail else ""))
                return False
            if set(offsets).intersection(self._pending_entries):
                self._v7_feedback("These rows have unapplied typed offsets. Use Set offsets first, "
                                  "or restore the displayed values before accepting a suggestion.")
                return False
            # Use the same signed-report, geometry, finite-value and grid-bounds
            # validator as dragging/nudging. Final export keeps its live-context checks.
            offsets = self._backend().validate_manual_offsets(self.report, offsets)
            reviewed_report = self.report
            if warnings:
                details = "\n\n".join(warnings[:5])
                if len(warnings) > 5:
                    details += f"\n\n...and {len(warnings)-5} more low-confidence suggestion(s)."
                if not messagebox.askyesno(
                    "Accept low-confidence position?",
                    "The automatic fit did not consider these positions reliable enough for automatic checking.\n\n"
                    + details + "\n\nAccept the displayed positions as your manually approved moves? "
                    "This checks them for saving; it does not improve the detector's confidence.",
                    parent=self.window):
                    self.status_var.set("Suggestion not accepted. Existing drafts and checks are unchanged.")
                    return False
            if self.operation is not None or self.report is not reviewed_report or getattr(self, "closed", False):
                self.status_var.set("The review changed while approval was open. Review the current rows again.")
                return False
            # V5 commit already creates undo records for position changes. Supply
            # a record for re-checking identical drafts too, without double snapshots.
            before_history = len(self.manual_history)
            same_offsets = all(self.manual_overrides.get(wid) == value for wid, value in offsets.items())
            changed_check = any((math.hypot(value['east_m'], value['north_m']) > 1e-9) != (wid in self.selected_ids)
                                for wid, value in offsets.items())
            if same_offsets and changed_check:
                self._remember_manual_group(offsets, self.tree.focus())
            if not self._commit_manual_group(offsets, focus=self.tree.focus()):
                if same_offsets and changed_check and len(self.manual_history) > before_history:
                    self.manual_history.pop()
                return False
            hidden = sum(not self._feature_visible(self.features[wid]) for wid in offsets)
            count = sum(wid in self.selected_ids for wid in offsets)
            text = (f"Accepted {len(anchors)} displayed position(s); {count} move(s) checked for saving"
                    f" ({hidden} linked hidden). Use Save checked corrections to write the OSM.")
            if skipped:
                text += f" {len(skipped)} row(s) had no new nonzero suggestion and were left unchanged."
            self.status_var.set(text)
            return True
        except Exception as exc:
            self._v7_feedback(str(exc), error=True)
            return False
        finally:
            self._v7_accepting = False


    def _v7_move_only_focused(self):
        """Isolate the focused owner for future gestures; never discard drafts."""
        if self.operation is not None or self.report is None:
            return False
        wid = self.tree.focus()
        if wid not in self.features or not self._feature_visible(self.features[wid]):
            self.status_var.set("Select the object to move first.")
            return False
        feature = self.features[wid]
        if not feature.get("manual_movable"):
            self._v7_feedback(self._label(wid) + ": " + str(feature.get("manual_reason")
                              or "The selected boundary has invalid or incomplete geometry."), error=True)
            return False
        self._cancel_drag()
        self.tree.selection_set(wid)
        self.tree.focus(wid)
        self.link_holes_var.set(False)
        self.move_mode_var.set(True)
        self._row_selected()
        self._show_feature_details()
        self._set_controls()
        self._queue_redraw()
        others = len(self.selected_ids - {wid})
        note = (f"Independent movement: only {feature.get('label', feature.get('kind', 'object'))} "
                f"{self._label(wid)} will move. Linked cutouts and unselected boundaries will not follow. "
                f"{others} other previously checked move(s) remain checked; uncheck them to exclude them from Save.")
        if feature.get("boundary_role") == "inner":
            note += " This row is a cutout, not the filled object; its parent-containment checks still apply."
        self.status_var.set(note)
        return True




def open_local_alignment(viewer):
    return LocalAlignmentDialog(viewer)
