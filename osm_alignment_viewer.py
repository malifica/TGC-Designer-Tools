import math
import queue
import threading
import traceback
from pathlib import Path

import cv2
import numpy as np
import overpy
import pyproj
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

import cfs_georef
import OSMTGC
import osm_custom_layout
from GeoPointCloud import GeoPointCloud


FEATURE_COLORS = {
    "bunker": "#ffd400",
    "green": "#00ff66",
    "tee": "#00ffff",
    "fairway": "#66ff33",
    "rough": "#ff9900",
    "mulch": "#faa0be",  # TGC_HBCC_DRY_MULCH_V1
    "driving_range": "#99ff33",
    "water_hazard": "#3399ff",
    "lateral_water_hazard": "#3399ff",
    "cartpath": "#ffffff",
    "road": "#ff5a5a",
    "walkingpath": "#dddddd",
    "other": "#ff66ff",
}


def _to_float(entry, default=0.0):
    try:
        return float(entry.get())
    except Exception:
        return float(default)


def _normalize_gray(arr):
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim > 2:
        a = np.squeeze(a)

    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return np.zeros(a.shape, dtype=np.uint8)

    lo = float(np.percentile(finite, 2.0))
    hi = float(np.percentile(finite, 98.0))
    if not math.isfinite(lo):
        lo = float(np.min(finite))
    if not math.isfinite(hi):
        hi = float(np.max(finite))
    if hi <= lo:
        hi = lo + 1.0

    out = np.array(a, copy=True)
    out[~np.isfinite(out)] = lo
    out = np.clip((out - lo) / (hi - lo), 0.0, 1.0)
    return (255.0 * out).astype(np.uint8)


def _terrain_relief(heightmap, resolution):
    h = np.asarray(heightmap, dtype=np.float32)
    if h.ndim > 2:
        h = np.squeeze(h)

    valid = np.isfinite(h)
    if not np.any(valid):
        return np.zeros(h.shape + (3,), dtype=np.uint8)

# TGC_BETA6_OSM_CARTPATH_ROAD_SPLIT_V4
# TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5
    if not np.all(valid):
        from scipy import ndimage
        invalid = ~valid
        _, idx = ndimage.distance_transform_edt(
            invalid,
            return_distances=True,
            return_indices=True,
        )
        h = h.copy()
        h[invalid] = h[tuple(idx[:, invalid])]

    from scipy import ndimage

    sigma = max(0.45, 0.65 / max(float(resolution), 0.05))
    smooth = ndimage.gaussian_filter(h, sigma=sigma, mode="nearest")

    gy, gx = np.gradient(smooth, float(resolution), float(resolution))

    # Alignment-viewer hillshade is intentionally more expressive than a
    # cartographic/default hillshade.  This changes preview shading only;
    # source elevations and generated terrain are untouched.
    relief_exaggeration = 2.0
    gx *= relief_exaggeration
    gy *= relief_exaggeration

    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)

    az = math.radians(315.0)
    alt = math.radians(35.0)

    shaded = (
        np.sin(alt) * np.sin(slope)
        + np.cos(alt) * np.cos(slope) * np.cos(az - aspect)
    )

    # Stretch the useful lighting range instead of mapping the theoretical
    # -1..+1 range directly.  Gentle golf-course relief otherwise occupies
    # only a narrow band of gray and is difficult to align by eye.
    finite_shade = shaded[np.isfinite(shaded)]
    if finite_shade.size:
        lo = float(np.percentile(finite_shade, 2.0))
        hi = float(np.percentile(finite_shade, 98.0))
    else:
        lo, hi = -1.0, 1.0

    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        lo, hi = -1.0, 1.0

    shaded = np.clip((shaded - lo) / (hi - lo), 0.0, 1.0)
    gray = (255.0 * shaded).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)


def _visual_rgb(data, heightmap):
    visual = data.get("visual", None)

    if visual is None:
        gray = _normalize_gray(heightmap)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    arr = np.asarray(visual)

    if arr.ndim == 2:
        gray = _normalize_gray(arr)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    if arr.ndim == 3 and arr.shape[2] == 1:
        gray = _normalize_gray(arr[:, :, 0])
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    if arr.ndim == 3 and arr.shape[2] >= 3:
        rgb = np.asarray(arr[:, :, :3])

        if np.issubdtype(rgb.dtype, np.floating):
            finite = rgb[np.isfinite(rgb)]
            if finite.size and float(np.max(finite)) <= 1.5:
                rgb = np.clip(rgb * 255.0, 0.0, 255.0)
            else:
                rgb = np.clip(rgb, 0.0, 255.0)

        rgb = np.nan_to_num(rgb, nan=0.0, posinf=255.0, neginf=0.0)
        return rgb.astype(np.uint8)

    gray = _normalize_gray(heightmap)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)


def _blend_rgb(a, b, alpha=0.55):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    if a.shape[:2] != b.shape[:2]:
        b = cv2.resize(
            b,
            (a.shape[1], a.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )

    out = a * float(alpha) + b * (1.0 - float(alpha))
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def _parse_osm(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        xml = f.read()

    parser = overpy.Overpass()
    return parser.parse_xml(xml)


def _feature_style(tags):
    if OSMTGC.classifyDryAreaForTGC(tags):
        return "mulch", FEATURE_COLORS["mulch"]
    if tags.get("golf") == "mulch":
        return None, None
    golf = str(tags.get("golf", "") or "").lower()

    if golf == "cartpath":
        return "cartpath", FEATURE_COLORS["cartpath"]
    if golf == "path":
        return "walkingpath", FEATURE_COLORS["walkingpath"]
    if golf:
        return golf, FEATURE_COLORS.get(golf, FEATURE_COLORS["other"])

    natural = str(tags.get("natural", "") or "").lower()
    waterway = str(tags.get("waterway", "") or "").lower()

    if natural == "water" or waterway:
        return "water", FEATURE_COLORS["water_hazard"]

    highway_class = OSMTGC.classifyHighwayForTGC(tags)
    if highway_class in ("cartpath", "road", "walkingpath"):
        return highway_class, FEATURE_COLORS[highway_class]

    return None, None


def _project_way_points(way, transformer, min_x, min_y, resolution):
    """Project one OSM way with one cached vectorized CRS/custom transformer."""
    try:
        nodes = list(way.get_nodes(resolve_missing=False))
    except Exception:
        return []

    if len(nodes) < 2:
        return []

    lons = np.asarray([float(node.lon) for node in nodes], dtype=np.float64)
    lats = np.asarray([float(node.lat) for node in nodes], dtype=np.float64)

    try:
        if hasattr(transformer, "project_arrays"):
            xs, ys = transformer.project_arrays(lons, lats)
        else:
            xs, ys = transformer.transform(lons, lats)
    except Exception:
        return []

    cols = (np.asarray(xs, dtype=np.float64) - float(min_x)) / float(resolution)
    rows_south = (np.asarray(ys, dtype=np.float64) - float(min_y)) / float(resolution)

    valid = np.isfinite(cols) & np.isfinite(rows_south)
    return [
        (float(col), float(row))
        for col, row, keep in zip(cols, rows_south, valid)
        if bool(keep)
    ]


def _collect_overlay_features(
    osm_result,
    projection,
    grid,
    printf=print,
    progress_callback=None,
    custom_unmatched_osm=False,
):
    """Build CFS overlay geometry without constructing a transformer per node."""
    min_x = float(grid["min_x"])
    min_y = float(grid["min_y"])
    resolution = float(grid["resolution"])

    if bool(custom_unmatched_osm):
        transformer = osm_custom_layout.placement_for_master_grid(
            osm_result,
            grid,
        )
        info = transformer.diagnostics()
        printf(
            "Custom / Unmatched OSM: ignoring absolute OSM geography; "
            "centering %s (%d node(s), %.1f x %.1f m) on the terrain master grid." % (
                info.get("anchor_strategy", "course anchor"),
                int(info.get("anchor_node_count", 0)),
                info["source_width_m"], info["source_height_m"]
            )
        )
    else:
        # Beta 7: exactly the final importer's geographic datum operation.
        from tgc_cfs_display import importer_transformer
        transformer = importer_transformer(projection)

    features = []
    direct_way_ids = set()
    way_lookup = {way.id: way for way in osm_result.ways}
    projected_cache = {}

    def report(percent, message):
        if progress_callback is not None:
            try:
                progress_callback(float(percent), str(message))
            except Exception:
                pass

    def points_for(way):
        key = getattr(way, "id", id(way))
        if key not in projected_cache:
            projected_cache[key] = _project_way_points(
                way,
                transformer,
                min_x,
                min_y,
                resolution,
            )
        return projected_cache[key]

    total_work = max(1, len(osm_result.ways) + len(osm_result.relations))
    completed = 0

    for way in osm_result.ways:
        kind, color = _feature_style(way.tags)
        if kind is not None:
            points = points_for(way)
            if len(points) >= 2:
                direct_way_ids.add(way.id)
                features.append({
                    "kind": kind,
                    "color": color,
                    "points": points,
                    "closed": len(points) >= 3 and (
                        abs(points[0][0] - points[-1][0]) < 0.5
                        and abs(points[0][1] - points[-1][1]) < 0.5
                    ),
                    "dash": None,
                    "label": str(way.id),
                })

        completed += 1
        if completed == total_work or completed % 100 == 0:
            report(
                28.0 + 22.0 * completed / total_work,
                "Projecting OSM feature geometry...",
            )

    for rel in osm_result.relations:
        kind, color = _feature_style(rel.tags)
        if kind is not None:
            for member in rel.members:
                ref = getattr(member, "ref", None)
                way = way_lookup.get(ref)
                if way is None or way.id in direct_way_ids:
                    continue

                points = points_for(way)
                if len(points) < 2:
                    continue

                role = str(getattr(member, "role", "") or "").lower()
                features.append({
                    "kind": kind,
                    "color": color,
                    "points": points,
                    "closed": True,
                    "dash": (4, 3) if role == "inner" else None,
                    "label": str(rel.id) + ":" + str(ref),
                })

        completed += 1
        if completed == total_work or completed % 50 == 0:
            report(
                28.0 + 22.0 * completed / total_work,
                "Projecting OSM relation geometry...",
            )

    printf(
        "CFS Alignment Viewer: loaded "
        + str(len(features))
        + " OSM overlay feature(s)"
    )
    return features


class AlignmentViewer:
    """Responsive CFS viewer with background loading and mask rebuilding."""

    def __init__(
        self,
        parent,
        heightmap_dir,
        osm_file,
        ew_entry,
        ns_entry,
        printf=print,
        apply_callback=None,
        apply_finished_callback=None,
        custom_unmatched_osm=False,
        osm_file_changed_callback=None,
    ):
        # TGC_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1
        # V3 retains the V1 aligned-mask callback contract; only its execution
        # moved to a queue-driven background worker.
        # TGC_BETA6_CFS_ASYNC_MASK_REBUILD_V3
        self.parent = parent
        self.heightmap_dir = Path(heightmap_dir)
        self.osm_file = str(osm_file)
        self.ew_entry = ew_entry
        self.ns_entry = ns_entry
        self.printf = printf
        self.apply_callback = apply_callback
        self.apply_finished_callback = apply_finished_callback
        self.custom_unmatched_osm = bool(custom_unmatched_osm)
        self.osm_file_changed_callback = osm_file_changed_callback
        self.local_review = None
        self._local_original_osm_file = self.osm_file
        self._local_original_osm_sha256 = None

        self.shift_ew = _to_float(ew_entry, 0.0)
        self.shift_ns = _to_float(ns_entry, 0.0)
        self.original_ew = self.shift_ew
        self.original_ns = self.shift_ns

        self.drag_start_canvas = None
        self.drag_start_shift = None
        self.zoom = 1.0
        from tgc_cfs_display import initialize
        initialize(self)
        self.photo = None
        self.image_item = None

        self.data = None
        self.heightmap = None
        self.resolution = 1.0
        self.projection = None
        self.grid = None
        self.rows = 1
        self.cols = 1
        self.osm_result = None
        self.features = []
        self.visual_rgb = None
        self.relief_rgb = None
        self.blend_rgb = None
        self.backgrounds = {}

        self.ready = False
        self.loading = True
        self.busy = False
        self.closed = False
        self.close_after_apply = False
        self._load_queue = queue.Queue()
        self._apply_queue = queue.Queue()
        self._interactive_widgets = []

        self.window = tk.Toplevel(parent)
        self.window.title("CFS OSM / Terrain Alignment Viewer")
        self.window.geometry("1280x900")
        self.window.minsize(900, 650)
        self.window.protocol("WM_DELETE_WINDOW", self._request_close)

        self._build_ui()
        self._bind_keys()
        self._set_controls_enabled(False)
        self._set_progress(2, "Loading heightmap and CFS master grid...")

        threading.Thread(
            target=self._load_worker,
            name="TGC-CFS-Viewer-Load",
            daemon=True,
        ).start()
        self.window.after(60, self._pump_load_queue)

    def _register(self, widget):
        self._interactive_widgets.append(widget)
        return widget

    def _build_ui(self):
        from functools import partial
        from tgc_cfs_widgets import action_button
        import tgc_cfs_display as display
        instruction = ttk.Frame(self.window)
        instruction.pack(fill=tk.X, padx=8, pady=(6, 2))
        top = ttk.Frame(self.window)

        ttk.Label(
            instruction,
            wraplength=1180,
            justify=tk.LEFT,
            text=(
                "Drag the colored OSM overlay over the terrain. "
                "Arrow keys = 0.10 m; Shift+Arrow = 1.0 m. "
                "Applying the alignment rebuilds mask.png; make manual mask edits afterward."
                + (" Custom / Unmatched mode is centered on the terrain; absolute OSM geography is ignored." if self.custom_unmatched_osm else "")
            ),
        ).pack(fill=tk.X)
        top.pack(fill=tk.X, padx=8, pady=(2, 5))

        ttk.Label(top, text="View:").pack(side=tk.LEFT)
        self.view_var = tk.StringVar(master=self.window, value="Hillshade")
        self.view_combo = self._register(ttk.Combobox(
            top,
            width=10,
            state="readonly",
            textvariable=self.view_var,
            values=("Blend", "Visual", "Hillshade"),
        ))
        self.view_combo.pack(side=tk.LEFT, padx=4)
        self.view_combo.bind("<<ComboboxSelected>>", self._view_changed)

        self.zoom_out_button = self._register(action_button(
            top, text="Zoom -", command=lambda: self._change_zoom(1.0 / 1.25)
        ))
        self.zoom_out_button.pack(side=tk.LEFT, padx=(12, 2))
        self.zoom_in_button = self._register(action_button(
            top, text="Zoom +", command=lambda: self._change_zoom(1.25)
        ))
        self.zoom_in_button.pack(side=tk.LEFT, padx=2)
        self.fit_button = self._register(action_button(
            top, text="Fit", command=self._fit_zoom
        ))
        self.fit_button.pack(side=tk.LEFT, padx=2)
        self.zoom_var = tk.StringVar(master=self.window, value="1.00x")
        ttk.Label(top, text="Zoom:").pack(side=tk.LEFT, padx=(12, 3))
        self.zoom_combo = self._register(ttk.Combobox(
            top, width=8, state="readonly", textvariable=self.zoom_var,
            values=("0.25x", "0.50x", "1x", "2x", "4x", "8x", "15x", "20x", "30x")))
        self.zoom_combo.pack(side=tk.LEFT, padx=3)
        self.zoom_combo.bind("<<ComboboxSelected>>", partial(display.zoom_selected, self))
        ttk.Label(top, text="Maximum 30x; pan with scrollbars").pack(side=tk.LEFT, padx=8)
        tones = ttk.Frame(self.window)
        tones.pack(fill=tk.X, padx=8, pady=(0, 6))
        display.add_display_controls(self, tones)

        readout = ttk.Frame(self.window)
        readout.pack(fill=tk.X, padx=8, pady=(0, 6))

        ttk.Label(readout, text="E/W (m):").pack(side=tk.LEFT)
        self.ew_var = tk.StringVar()
        self.ew_box = self._register(ttk.Entry(
            readout, width=9, textvariable=self.ew_var
        ))
        self.ew_box.pack(side=tk.LEFT, padx=(3, 12))

        ttk.Label(readout, text="N/S (m):").pack(side=tk.LEFT)
        self.ns_var = tk.StringVar()
        self.ns_box = self._register(ttk.Entry(
            readout, width=9, textvariable=self.ns_var
        ))
        self.ns_box.pack(side=tk.LEFT, padx=(3, 12))

        self.update_button = self._register(action_button(
            readout, text="Update Overlay", command=self._update_from_entries
        ))
        self.update_button.pack(side=tk.LEFT, padx=3)
        self.zero_button = self._register(action_button(
            readout, text="Zero", command=self._zero_shift
        ))
        self.zero_button.pack(side=tk.LEFT, padx=3)
        self.revert_button = self._register(action_button(
            readout, text="Revert", command=self._revert_shift
        ))
        self.revert_button.pack(side=tk.LEFT, padx=3)

        local_row = ttk.Frame(self.window)
        local_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.apply_button = self._register(action_button(
            local_row,
            text="Apply + Rebuild Mask",
            command=lambda: self._start_apply(False),
            primary=True,
        ))
        self.apply_button.pack(side=tk.LEFT, padx=(0, 6))
        self.apply_close_button = self._register(action_button(
            local_row,
            text="Apply + Rebuild + Close",
            command=lambda: self._start_apply(True),
        ))
        self.apply_close_button.pack(side=tk.LEFT, padx=3)

        self.local_alignment_button = self._register(action_button(
            local_row, text="Local Tee/Bunker Alignment", command=self._open_local_alignment,
            primary=True,
        ))
        self.local_alignment_button.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(local_row, text="Automatic / manual object moves").pack(side=tk.LEFT, padx=10)

        self.info_var = tk.StringVar(value="Preparing CFS viewer...")
        ttk.Label(self.window, textvariable=self.info_var).pack(
            fill=tk.X, padx=8, pady=(0, 4)
        )

        progress_frame = ttk.Frame(self.window)
        progress_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100.0,
            variable=self.progress_var,
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_text_var = tk.StringVar(value="Preparing...")
        ttk.Label(
            progress_frame,
            textvariable=self.progress_text_var,
            width=52,
            anchor="w",
        ).pack(side=tk.LEFT, padx=(10, 0))

        canvas_frame = ttk.Frame(self.window)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.canvas = tk.Canvas(
            canvas_frame,
            background="black",
            highlightthickness=0,
        )
        hbar = ttk.Scrollbar(
            canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview
        )
        vbar = ttk.Scrollbar(
            canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.canvas.configure(
            xscrollcommand=partial(display.scroll_changed, self, hbar),
            yscrollcommand=partial(display.scroll_changed, self, vbar),
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<MouseWheel>", self._mousewheel_zoom)
        self.canvas.bind("<Button-4>", self._mousewheel_zoom)
        self.canvas.bind("<Button-5>", self._mousewheel_zoom)
        self.canvas.bind("<Configure>", partial(display.queue_redraw, self))

        legend = ttk.Frame(self.window)
        legend.pack(fill=tk.X, padx=8, pady=(2, 8))
        entries = [
            ("Bunker", FEATURE_COLORS["bunker"]),
            ("Green", FEATURE_COLORS["green"]),
            ("Tee", FEATURE_COLORS["tee"]),
            ("Fairway", FEATURE_COLORS["fairway"]),
            ("Rough", FEATURE_COLORS["rough"]),
            ("Natural wood", FEATURE_COLORS["mulch"]),
            ("Water", FEATURE_COLORS["water_hazard"]),
            ("Cart Path", FEATURE_COLORS["cartpath"]),
            ("Road", FEATURE_COLORS["road"]),
            ("Walking Path", FEATURE_COLORS["walkingpath"]),
        ]
        ttk.Label(
            legend,
            text=(
                "OSM source outlines (2 px / higher-visibility tracing overlay; "
                "before TGC spline shrink):"
            ),
        ).pack(side=tk.LEFT, padx=(0, 8))
        for label, color in entries:
            tk.Label(
                legend,
                text="  ",
                background=color,
                relief=tk.SOLID,
                borderwidth=1,
            ).pack(side=tk.LEFT, padx=(3, 1))
            ttk.Label(legend, text=label).pack(side=tk.LEFT, padx=(0, 5))

        self._update_readout()

    def _bind_keys(self):
        bindings = [
            ("<Left>", -0.10, 0.0),
            ("<Right>", 0.10, 0.0),
            ("<Up>", 0.0, 0.10),
            ("<Down>", 0.0, -0.10),
            ("<Shift-Left>", -1.0, 0.0),
            ("<Shift-Right>", 1.0, 0.0),
            ("<Shift-Up>", 0.0, 1.0),
            ("<Shift-Down>", 0.0, -1.0),
        ]
        for sequence, dew, dns in bindings:
            self.window.bind(
                sequence,
                lambda event, x=dew, y=dns: self._key_nudge(event, x, y),
            )
            self.view_combo.bind(
                sequence,
                lambda event, x=dew, y=dns: self._key_nudge(event, x, y),
            )

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in self._interactive_widgets:
            try:
                if widget is self.view_combo or widget is self.zoom_combo:
                    widget.configure(state="readonly" if enabled else "disabled")
                else:
                    widget.configure(state=state)
            except Exception:
                pass

    def _set_progress(self, percent, message):
        try:
            self.progress_var.set(max(0.0, min(100.0, float(percent))))
            self.progress_text_var.set(str(message))
        except Exception:
            pass

    def _queue_progress(self, target_queue, percent, message):
        target_queue.put(("progress", (float(percent), str(message))))

    def _queue_log(self, target_queue, message):
        target_queue.put(("log", str(message)))

    def _load_worker(self):
        try:
            progress = lambda pct, msg: self._queue_progress(
                self._load_queue, pct, msg
            )
            log = lambda msg: self._queue_log(self._load_queue, msg)

            progress(5, "Loading heightmap.npy...")
            data = np.load(
                self.heightmap_dir / "heightmap.npy",
                allow_pickle=True,
            ).item()
            heightmap = np.asarray(data["heightmap"])
            if heightmap.ndim > 2:
                heightmap = np.squeeze(heightmap)

            resolution = float(data["image_scale"])
            projection = data["projection"]

            progress(12, "Reading and validating the CFS master grid...")
            grid = cfs_georef.get_master_grid(
                data,
                heightmap,
                printf=log,
            )
            cfs_georef.validate_projection(projection, printf=log)

            progress(20, "Parsing the Local OSM file...")
            osm_result = _parse_osm(self.osm_file)

            progress(28, "Projecting OSM geometry into the terrain grid...")
            features = _collect_overlay_features(
                osm_result,
                projection,
                grid,
                printf=log,
                progress_callback=progress,
                custom_unmatched_osm=self.custom_unmatched_osm,
            )

            progress(55, "Preparing the terrain visual layer...")
            visual_rgb = _visual_rgb(data, heightmap)

            progress(68, "Generating CFS hillshade...")
            relief_rgb = _terrain_relief(heightmap, resolution)

            progress(88, "Combining terrain display layers...")
            blend_rgb = _blend_rgb(visual_rgb, relief_rgb, alpha=0.55)

            self._load_queue.put(("done", {
                "data": data,
                "heightmap": heightmap,
                "resolution": resolution,
                "projection": projection,
                "grid": grid,
                "osm_result": osm_result,
                "features": features,
                "visual_rgb": visual_rgb,
                "relief_rgb": relief_rgb,
                "blend_rgb": blend_rgb,
            }))
        except Exception:
            self._load_queue.put(("error", traceback.format_exc()))

    def _pump_load_queue(self):
        if self.closed:
            return

        finished = False
        while True:
            try:
                kind, payload = self._load_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                self._set_progress(*payload)
            elif kind == "log":
                try:
                    self.printf(payload)
                except Exception:
                    pass
            elif kind == "error":
                self.loading = False
                self._set_progress(0, "CFS viewer preparation failed.")
                try:
                    self.printf("CFS Alignment Viewer failed:\n" + payload)
                except Exception:
                    pass
                messagebox.showerror(
                    "CFS Alignment Viewer",
                    "Could not prepare the alignment viewer.\n\n" + payload,
                    parent=self.window,
                )
                finished = True
            elif kind == "done":
                self.data = payload["data"]
                self.heightmap = payload["heightmap"]
                self.resolution = payload["resolution"]
                self.projection = payload["projection"]
                self.grid = payload["grid"]
                self.osm_result = payload["osm_result"]
                self.features = payload["features"]
                self.visual_rgb = payload["visual_rgb"]
                self.relief_rgb = payload["relief_rgb"]
                self.blend_rgb = payload["blend_rgb"]
                self.rows = int(self.heightmap.shape[0])
                self.cols = int(self.heightmap.shape[1])
                self.backgrounds = {
                    "Visual": np.flipud(self.visual_rgb),
                    "Hillshade": np.flipud(self.relief_rgb),
                    "Blend": np.flipud(self.blend_rgb),
                }
                self.loading = False
                self.ready = True
                self._choose_initial_zoom()
                self._redraw_everything()
                self._set_controls_enabled(True)
                self._set_progress(100, "CFS alignment viewer ready.")
                self.canvas.focus_set()
                finished = True

        if not finished and not self.closed:
            self.window.after(60, self._pump_load_queue)

    def _request_close(self):
        review = getattr(self, "local_review", None)
        if review is not None and not review.closed:
            review.request_close()
            return
        if self.busy:
            messagebox.showwarning(
                "Mask Rebuild In Progress",
                "The aligned mask is still being rebuilt. Please wait for it "
                "to finish before closing the CFS viewer.",
                parent=self.window,
            )
            return
        self.closed = True
        self.window.destroy()

    def _can_interact(self):
        return bool(self.ready and not self.busy and not self.closed and getattr(self, "local_review", None) is None)

    def _open_local_alignment(self):
        if not self._can_interact():
            return
        if self.custom_unmatched_osm:
            messagebox.showinfo(
                "Local Tee/Bunker Alignment",
                "Local terrain matching requires georeferenced OSM. Turn off Custom / Unmatched OSM and reopen CFS for this feature.",
                parent=self.window,
            )
            return
        try:
            ew, ns = float(self.ew_var.get()), float(self.ns_var.get())
            if not math.isfinite(ew) or not math.isfinite(ns):
                raise ValueError("Enter finite E/W and N/S values before reviewing local alignment.")
            # Use the same centimetre precision as the CFS readout and Apply.
            # Otherwise newly typed finer values could be analyzed, then rounded
            # only after review when the mask/import alignment is copied back.
            ew, ns = float(f"{ew:.2f}"), float(f"{ns:.2f}")
            self.shift_ew, self.shift_ns = ew, ns
            self._redraw_overlay()
            from tgc_local_alignment_ui import open_local_alignment
            # TGC_BETA7_SHARED_CFS_UI_V1: preserve installed local alignment code.
            from tgc_ui_style import wrap_local_alignment
            open_local_alignment = wrap_local_alignment(open_local_alignment)
            open_local_alignment(self)
        except Exception as exc:
            messagebox.showerror("Local Tee/Bunker Alignment", str(exc), parent=self.window)

    def _choose_initial_zoom(self):
        max_w = 1120.0
        max_h = 690.0
        self.zoom = min(
            1.0,
            max_w / max(float(self.cols), 1.0),
            max_h / max(float(self.rows), 1.0),
        )
        self.zoom = max(self.zoom, 0.15)


    def _fit_zoom(self):
        if not self._can_interact():
            return
        from tgc_cfs_display import set_zoom
        width = max(float(self.canvas.winfo_width()) - 20.0, 200.0)
        height = max(float(self.canvas.winfo_height()) - 20.0, 200.0)
        set_zoom(self, min(width / max(float(self.cols), 1.0),
                           height / max(float(self.rows), 1.0)))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._redraw_background()


    def _change_zoom(self, factor):
        from tgc_cfs_display import set_zoom
        set_zoom(self, self.zoom * float(factor))


    def _mousewheel_zoom(self, event):
        if not self._can_interact():
            return "break"
        from tgc_cfs_display import set_zoom
        delta = getattr(event, "delta", 0)
        number = getattr(event, "num", None)
        if delta > 0 or number == 4:
            set_zoom(self, self.zoom * 1.25, (event.x, event.y))
        elif delta < 0 or number == 5:
            set_zoom(self, self.zoom / 1.25, (event.x, event.y))
        return "break"

    def _view_changed(self, event=None):
        if self._can_interact():
            self._redraw_background()
            self.canvas.focus_set()
        return "break"


    def _key_nudge(self, event, dew, dns):
        # Editing a display control or entry must not move the OSM overlay.
        if getattr(event, "widget", None) in (
            self.brightness_slider, self.contrast_slider, self.zoom_combo,
            self.ew_box, self.ns_box):
            return None
        if self._can_interact():
            self._nudge(dew, dns)
            self.canvas.focus_set()
        return "break"

    def _current_background(self):
        return self.backgrounds.get(self.view_var.get(), self.blend_rgb)


    def _redraw_background(self):
        if not self.ready or self.closed:
            return
        from tgc_cfs_display import viewport_tile
        arr = self._current_background()
        view = self.view_var.get()
        cached = self._cfs_background_cache.get(view)
        if cached is None or cached[0] is not arr:
            cached = (arr, Image.fromarray(arr, "RGB"))
            self._cfs_background_cache[view] = cached
        size = (self.cols * self.zoom, self.rows * self.zoom)
        region = (0, 0, size[0], size[1])
        if self._cfs_scrollregion != region:
            self._cfs_scrollregion = region
            self.canvas.configure(scrollregion=region)
        x = self.canvas.canvasx(0)
        y = self.canvas.canvasy(0)
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        brightness = self.brightness_var.get()
        contrast = self.contrast_var.get()
        key = (view, id(arr), self.zoom, x, y, w, h, brightness, contrast)
        if self._cfs_last_tile_key == key:
            return
        tile, origin = viewport_tile(cached[1], self.zoom, x, y, w, h, brightness, contrast)
        if tile is None:
            if self.image_item is not None:
                self.canvas.itemconfigure(self.image_item, state="hidden")
            return
        self._cfs_tile_size = tile.size
        self.photo = ImageTk.PhotoImage(tile, master=self.canvas)
        if self.image_item is None:
            self.image_item = self.canvas.create_image(
                *origin, image=self.photo, anchor=tk.NW, tags=("terrain_background",))
        else:
            self.canvas.coords(self.image_item, *origin)
            self.canvas.itemconfigure(self.image_item, image=self.photo, state="normal")
        self.canvas.tag_lower("terrain_background")
        self._cfs_last_tile_key = key


    def _display_xy(self, col, row_south):
        from tgc_cfs_display import screen_point
        return screen_point(col, row_south, self.rows, self.resolution,
                            self.zoom, self.shift_ew, self.shift_ns)

    def _redraw_overlay(self):
        if not self.ready:
            self._update_readout()
            return
        self.canvas.delete("osm_overlay")
        for feature in self.features:
            coords = []
            for col, row_south in feature["points"]:
                coords.extend(self._display_xy(col, row_south))
            if len(coords) < 4:
                continue
            if feature["closed"]:
                coords.extend(coords[:2])
            kwargs = {
                "fill": feature["color"],
                "width": 2,
                "tags": ("osm_overlay",),
                "smooth": False,
                "stipple": "gray75",
            }
            if feature["dash"]:
                kwargs["dash"] = feature["dash"]
            self.canvas.create_line(*coords, **kwargs)
        self.canvas.tag_raise("osm_overlay")
        self._update_readout()

    def _redraw_everything(self):
        self._redraw_background()
        self._redraw_overlay()

    def _update_readout(self):
        self.zoom_var.set(f"{self.zoom:.2f}x")
        self.ew_var.set(f"{self.shift_ew:.2f}")
        self.ns_var.set(f"{self.shift_ns:.2f}")
        if self.ready:
            self.info_var.set(
                f"Zoom: {self.zoom:.2f}x   |   Grid: " + str(self.cols) + " x " + str(self.rows) + " @ "
                + f"{self.resolution:.3f}" + " m/pixel   |   Shift: "
                + f"{self.shift_ew:.2f} m E/W, {self.shift_ns:.2f} m N/S"
                + "   |   Pixel shift: "
                + f"{self.shift_ew / self.resolution:.2f}, "
                + f"{self.shift_ns / self.resolution:.2f}"
            )

    def _update_from_entries(self):
        if not self._can_interact():
            return
        try:
            self.shift_ew = float(self.ew_var.get())
            self.shift_ns = float(self.ns_var.get())
        except Exception:
            messagebox.showerror(
                "Alignment Viewer",
                "Enter valid numeric E/W and N/S values.",
                parent=self.window,
            )
            return
        self._redraw_overlay()

    def _nudge(self, dew, dns):
        if not self._can_interact():
            return
        self.shift_ew += float(dew)
        self.shift_ns += float(dns)
        self._redraw_overlay()

    def _zero_shift(self):
        if not self._can_interact():
            return
        self.shift_ew = 0.0
        self.shift_ns = 0.0
        self._redraw_overlay()

    def _revert_shift(self):
        if not self._can_interact():
            return
        self.shift_ew = self.original_ew
        self.shift_ns = self.original_ns
        self._redraw_overlay()

    def _drag_start(self, event):
        if not self._can_interact():
            return
        self.canvas.focus_set()
        self.drag_start_canvas = (
            self.canvas.canvasx(event.x),
            self.canvas.canvasy(event.y),
        )
        self.drag_start_shift = (self.shift_ew, self.shift_ns)

    def _drag_move(self, event):
        if not self._can_interact() or self.drag_start_canvas is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        dx_canvas = x - self.drag_start_canvas[0]
        dy_canvas = y - self.drag_start_canvas[1]
        self.shift_ew = (
            self.drag_start_shift[0]
            + dx_canvas / max(self.zoom, 1.0e-9) * self.resolution
        )
        self.shift_ns = (
            self.drag_start_shift[1]
            - dy_canvas / max(self.zoom, 1.0e-9) * self.resolution
        )
        self._redraw_overlay()

    def _drag_end(self, event):
        if not self._can_interact():
            return
        self._drag_move(event)
        self.drag_start_canvas = None
        self.drag_start_shift = None

    def _copy_alignment_to_main(self):
        self.ew_entry.delete(0, tk.END)
        self.ew_entry.insert(0, f"{self.shift_ew:.2f}")
        self.ns_entry.delete(0, tk.END)
        self.ns_entry.insert(0, f"{self.shift_ns:.2f}")

    def _start_apply(self, close_after):
        if not self._can_interact():
            return

        # Honor edits typed into the CFS readout before Apply is pressed.
        try:
            self.shift_ew = float(self.ew_var.get())
            self.shift_ns = float(self.ns_var.get())
        except Exception:
            messagebox.showerror(
                "Alignment Viewer",
                "Enter valid numeric E/W and N/S values.",
                parent=self.window,
            )
            return

        self._copy_alignment_to_main()
        self.printf(
            "CFS Alignment Viewer applied manual OSM nudge: "
            + f"E/W {self.shift_ew:.2f} m, N/S {self.shift_ns:.2f} m"
        )

        if self.apply_callback is None:
            messagebox.showinfo(
                "Alignment Viewer",
                "Alignment copied to the main window.\n\n"
                + f"E/W: {self.shift_ew:.2f} m\n"
                + f"N/S: {self.shift_ns:.2f} m",
                parent=self.window,
            )
            if close_after:
                self._request_close()
            return

        self.busy = True
        self.close_after_apply = bool(close_after)
        self._set_controls_enabled(False)
        self._set_progress(1, "Starting aligned-mask rebuild...")

        threading.Thread(
            target=self._apply_worker,
            name="TGC-CFS-Aligned-Mask-Rebuild",
            daemon=True,
        ).start()
        self.window.after(60, self._pump_apply_queue)

    def _apply_worker(self):
        try:
            progress = lambda pct, msg: self._queue_progress(
                self._apply_queue, pct, msg
            )
            log = lambda msg: self._queue_log(self._apply_queue, msg)
            result = self.apply_callback(
                self.heightmap_dir,
                self.osm_file,
                self.shift_ew,
                self.shift_ns,
                progress_callback=progress,
                printf=log,
            )
            self._apply_queue.put(("done", result))
        except Exception:
            self._apply_queue.put(("error", traceback.format_exc()))

    def _pump_apply_queue(self):
        if self.closed:
            return

        finished = False
        while True:
            try:
                kind, payload = self._apply_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                self._set_progress(*payload)
            elif kind == "log":
                try:
                    self.printf(payload)
                except Exception:
                    pass
            elif kind == "error":
                self.busy = False
                self._set_controls_enabled(True)
                self._set_progress(0, "Aligned-mask rebuild failed.")
                try:
                    self.printf("CFS alignment mask rebuild failed:\n" + payload)
                except Exception:
                    pass
                messagebox.showerror(
                    "Alignment Viewer",
                    "The alignment values were copied, but mask.png could not "
                    "be rebuilt from the final CFS alignment.\n\n" + payload,
                    parent=self.window,
                )
                finished = True
            elif kind == "done":
                self.busy = False
                self._set_controls_enabled(True)
                self._set_progress(100, "Aligned mask rebuilt and verified.")
                if self.apply_finished_callback is not None:
                    try:
                        self.apply_finished_callback(
                            payload,
                            self.heightmap_dir,
                            self.shift_ew,
                            self.shift_ns,
                        )
                    except Exception as exc:
                        self.printf(
                            "Warning: post-rebuild UI update failed: " + str(exc)
                        )

                detail = ""
                if isinstance(payload, dict):
                    detail = str(payload.get("message", "") or "").strip()
                message = (
                    "Alignment copied to the main Import Terrain and Features window.\n\n"
                    + f"E/W: {self.shift_ew:.2f} m\n"
                    + f"N/S: {self.shift_ns:.2f} m"
                )
                if detail:
                    message += "\n\n" + detail
                messagebox.showinfo(
                    "Alignment Viewer",
                    message,
                    parent=self.window,
                )
                close_after = self.close_after_apply
                self.close_after_apply = False
                finished = True
                if close_after and not self.closed:
                    self.closed = True
                    self.window.destroy()

        if not finished and self.busy and not self.closed:
            self.window.after(60, self._pump_apply_queue)

def open_alignment_viewer(
    parent,
    heightmap_dir,
    osm_file,
    ew_entry,
    ns_entry,
    printf=print,
    apply_callback=None,
    apply_finished_callback=None,
    custom_unmatched_osm=False,
    osm_file_changed_callback=None,
):
    heightmap_path = Path(heightmap_dir) / "heightmap.npy"

    if not heightmap_path.exists():
        messagebox.showerror(
            "CFS Alignment Viewer",
            "heightmap.npy was not found in:\n" + str(heightmap_dir),
            parent=parent,
        )
        return None

    if not osm_file:
        messagebox.showerror(
            "CFS Alignment Viewer",
            "Select a Local OSM File first.",
            parent=parent,
        )
        return None

    if not Path(osm_file).exists():
        messagebox.showerror(
            "CFS Alignment Viewer",
            "Local OSM file was not found:\n" + str(osm_file),
            parent=parent,
        )
        return None

    try:
        return AlignmentViewer(
            parent,
            heightmap_dir,
            osm_file,
            ew_entry,
            ns_entry,
            printf=printf,
            apply_callback=apply_callback,
            apply_finished_callback=apply_finished_callback,
            custom_unmatched_osm=custom_unmatched_osm,
            osm_file_changed_callback=osm_file_changed_callback,
        )

    except Exception as exc:
        printf(
            "CFS Alignment Viewer failed: "
            + str(exc)
        )

        messagebox.showerror(
            "CFS Alignment Viewer",
            "Could not open alignment viewer:\n\n" + str(exc),
            parent=parent,
        )

        return None
