"""View-only filters for the existing V5 local editor; never change OSM/terrain.

Selection (highlight), save checks, manual drafts and visibility are independent.
Hiding a row clears its active highlight but retains its checked/manual draft.
Explicitly linked cutouts can still move with a visible object, as indicated.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from tgc_cfs_widgets import action_button

FILTERS = (("tee", "Tees"), ("bunker", "Bunkers"), ("green", "Greens"),
           ("fairway", "Fairways"), ("rough", "Rough"), ("water", "Water"),
           ("mulch", "Mulch"), ("paths", "Paths / roads"), ("other", "Other"))
COLORS = {"tee": "#40c8ff", "bunker": "#f2d675", "green": "#53f0a0",
          "fairway": "#9be45d", "rough": "#c49cff", "water": "#63aaff",
          "mulch": "#eda788", "paths": "#e3e3e3", "other": "#abb8cc"}


def filter_kind(feature):
    kind = str(feature.get("kind", "")).lower()
    if kind in ("rough", "heavyrough", "heavy_rough"):
        return "rough"
    if kind in ("water", "water_hazard", "lateral_water_hazard", "waterway"):
        return "water"
    if kind in ("path", "cartpath", "road", "walkingpath"):
        return "paths"
    return kind if kind in dict(FILTERS) else "other"


class FeatureFilters:
    def __init__(self, owner, parent, before):
        self.owner, self.known_rows = owner, set()
        self.variables = {key: tk.BooleanVar(master=owner.window, value=True) for key, _ in FILTERS}
        self.frame = ttk.Frame(parent, padding=(0, 3))
        self.frame.pack(fill="x", before=before, pady=(0, 3))
        ttk.Label(self.frame, text="View only:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        for i, (key, label) in enumerate(FILTERS):
            row, column = divmod(i, 5)
            ttk.Checkbutton(self.frame, text=label, variable=self.variables[key],
                            command=self.apply).grid(row=row, column=column+1, sticky="w", padx=5)
        tools = ttk.Frame(self.frame)
        tools.grid(row=0, column=6, rowspan=2, sticky="e", padx=(12, 0))
        action_button(tools, "All", lambda: self.set_all(True), compact=True).pack(side="left")
        action_button(tools, "None", lambda: self.set_all(False), compact=True).pack(side="left", padx=3)
        self.note = tk.StringVar(master=owner.window, value="Filters affect the view, not terrain analysis or saved moves.")
        ttk.Label(parent, textvariable=self.note, wraplength=1100).pack(fill="x", before=before, pady=(0, 3))
        self.frame.columnconfigure(6, weight=1)

    def visible(self, feature):
        return bool(self.variables[filter_kind(feature)].get())

    def set_all(self, value):
        for variable in self.variables.values():
            variable.set(bool(value))
        self.apply()

    def reveal(self, ids):
        for sid in ids:
            feature = self.owner.features.get(str(sid))
            if feature is not None:
                self.variables[filter_kind(feature)].set(True)
        self.apply()

    def clear_rows(self):
        tree = self.owner.tree
        for sid in self.known_rows | set(tree.get_children("")):
            if tree.exists(sid):
                tree.delete(sid)
        self.known_rows.clear()

    def apply(self):
        owner = self.owner
        if not hasattr(owner, "tree") or owner.closed:
            return
        owner._cancel_drag()
        self.known_rows.update(owner.features)
        visible = [sid for sid, f in owner.features.items() if self.visible(f)]
        allowed = set(visible)
        tree = owner.tree
        selected = [sid for sid in tree.selection() if sid in allowed]
        focused = tree.focus()
        if focused not in allowed:
            tree.focus(selected[-1] if selected else "")
            owner._last_focus_id = tree.focus()
        tree.selection_set(selected)
        # Detach, do not delete: hidden drafts and save-check status stay intact.
        for sid in owner.features:
            if not tree.exists(sid):
                continue
            if sid in allowed:
                tree.move(sid, "", "end")
            else:
                tree.detach(sid)
        checked_hidden = len(set(owner.selected_ids) - allowed)
        self.note.set("Showing %d of %d boundaries; %d checked move(s) hidden. "
                      "Linked cutouts can move with visible objects; filters never delete geometry." %
                      (len(visible), len(owner.features), checked_hidden))
        owner._refresh_checks()
        owner._row_selected()

    def refresh_note(self):
        allowed = {sid for sid, f in self.owner.features.items() if self.visible(f)}
        checked_hidden = len(set(self.owner.selected_ids) - allowed)
        self.note.set("Showing %d of %d boundaries; %d checked move(s) hidden. "
                      "Linked cutouts can move with visible objects; filters never delete geometry." %
                      (len(allowed), len(self.owner.features), checked_hidden))


def line_hit(owner, points, x, y):
    """Hit-test actual open segments; no invented endpoint-to-start closing edge."""
    import math
    if len(points) < 2:
        return None
    pts = [owner._screen(float(px), float(py)) for px, py in points]
    best = math.inf
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        length2 = (bx-ax)**2 + (by-ay)**2
        t = max(0., min(1., ((x-ax)*(bx-ax)+(y-ay)*(by-ay))/length2)) if length2 else 0.
        best = min(best, (x-ax-t*(bx-ax))**2+(y-ay-t*(by-ay))**2)
    return (0, best, 0.) if best <= 64 else None
