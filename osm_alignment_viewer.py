import math
from pathlib import Path

import cv2
import numpy as np
import overpy
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

import cfs_georef
from GeoPointCloud import GeoPointCloud


FEATURE_COLORS = {
    "bunker": "#ffd400",
    "green": "#00ff66",
    "tee": "#00ffff",
    "fairway": "#66ff33",
    "rough": "#ff9900",
    "driving_range": "#99ff33",
    "water_hazard": "#3399ff",
    "lateral_water_hazard": "#3399ff",
    "cartpath": "#ffffff",
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
    golf = str(tags.get("golf", "") or "").lower()

    if golf:
        return golf, FEATURE_COLORS.get(golf, FEATURE_COLORS["other"])

    natural = str(tags.get("natural", "") or "").lower()
    waterway = str(tags.get("waterway", "") or "").lower()
    highway = str(tags.get("highway", "") or "").lower()
    golf_cart = str(tags.get("golf_cart", "") or "").lower()
    foot = str(tags.get("foot", "") or "").lower()

    if natural == "water" or waterway:
        return "water", FEATURE_COLORS["water_hazard"]

    if golf_cart in ("yes", "designated") or highway in (
        "service",
        "track",
        "path",
        "footway",
    ):
        if foot in ("yes", "designated") and golf_cart not in ("yes", "designated"):
            return "walkingpath", FEATURE_COLORS["walkingpath"]
        return "cartpath", FEATURE_COLORS["cartpath"]

    return None, None


def _node_world_pixel(node, projection, min_x, min_y, resolution):
    helper = GeoPointCloud()
    helper.proj = projection
    helper.origin = (0.0, 0.0)

    x, y = helper.latlonToProj(float(node.lat), float(node.lon))

    col = (float(x) - float(min_x)) / float(resolution)
    row_south = (float(y) - float(min_y)) / float(resolution)

    return col, row_south


def _collect_overlay_features(
    osm_result,
    projection,
    grid,
    printf=print,
):
    min_x = float(grid["min_x"])
    min_y = float(grid["min_y"])
    resolution = float(grid["resolution"])

    features = []
    direct_way_ids = set()

    for way in osm_result.ways:
        kind, color = _feature_style(way.tags)
        if kind is None:
            continue

        try:
            nodes = way.get_nodes(resolve_missing=False)
        except Exception:
            continue

        points = []

        for node in nodes:
            try:
                points.append(
                    _node_world_pixel(
                        node,
                        projection,
                        min_x,
                        min_y,
                        resolution,
                    )
                )
            except Exception:
                pass

        if len(points) < 2:
            continue

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

    way_lookup = {way.id: way for way in osm_result.ways}

    for rel in osm_result.relations:
        kind, color = _feature_style(rel.tags)
        if kind is None:
            continue

        for member in rel.members:
            ref = getattr(member, "ref", None)
            way = way_lookup.get(ref)

            if way is None:
                continue

            if way.id in direct_way_ids:
                continue

            try:
                nodes = way.get_nodes(resolve_missing=False)
            except Exception:
                continue

            points = []

            for node in nodes:
                try:
                    points.append(
                        _node_world_pixel(
                            node,
                            projection,
                            min_x,
                            min_y,
                            resolution,
                        )
                    )
                except Exception:
                    pass

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

    printf(
        "CFS Alignment Viewer: loaded "
        + str(len(features))
        + " OSM overlay feature(s)"
    )

    return features


class AlignmentViewer:
    def __init__(
        self,
        parent,
        heightmap_dir,
        osm_file,
        ew_entry,
        ns_entry,
        printf=print,
    ):
        self.parent = parent
        self.heightmap_dir = Path(heightmap_dir)
        self.osm_file = str(osm_file)
        self.ew_entry = ew_entry
        self.ns_entry = ns_entry
        self.printf = printf

        self.shift_ew = _to_float(ew_entry, 0.0)
        self.shift_ns = _to_float(ns_entry, 0.0)

        self.original_ew = self.shift_ew
        self.original_ns = self.shift_ns

        self.drag_start_canvas = None
        self.drag_start_shift = None

        self.zoom = 1.0
        self.photo = None
        self.image_item = None

        self.data = np.load(
            self.heightmap_dir / "heightmap.npy",
            allow_pickle=True,
        ).item()

        self.heightmap = np.asarray(self.data["heightmap"])
        if self.heightmap.ndim > 2:
            self.heightmap = np.squeeze(self.heightmap)

        self.resolution = float(self.data["image_scale"])
        self.projection = self.data["projection"]

        self.grid = cfs_georef.get_master_grid(
            self.data,
            self.heightmap,
            printf=self.printf,
        )

        cfs_georef.validate_projection(
            self.projection,
            printf=self.printf,
        )

        self.rows = int(self.heightmap.shape[0])
        self.cols = int(self.heightmap.shape[1])

        self.osm_result = _parse_osm(self.osm_file)

        self.features = _collect_overlay_features(
            self.osm_result,
            self.projection,
            self.grid,
            printf=self.printf,
        )

        self.visual_rgb = _visual_rgb(
            self.data,
            self.heightmap,
        )

        self.relief_rgb = _terrain_relief(
            self.heightmap,
            self.resolution,
        )

        self.blend_rgb = _blend_rgb(
            self.visual_rgb,
            self.relief_rgb,
            alpha=0.55,
        )

        self.backgrounds = {
            "Visual": np.flipud(self.visual_rgb),
            "Hillshade": np.flipud(self.relief_rgb),
            "Blend": np.flipud(self.blend_rgb),
        }

        self.window = tk.Toplevel(parent)
        self.window.title("CFS OSM / Terrain Alignment Viewer")
        self.window.geometry("1280x900")
        self.window.minsize(900, 650)

        self._build_ui()
        self._choose_initial_zoom()
        self._redraw_everything()

        self.window.bind("<Left>", lambda e: self._key_nudge(e, -0.10, 0.0))
        self.window.bind("<Right>", lambda e: self._key_nudge(e, 0.10, 0.0))
        self.window.bind("<Up>", lambda e: self._key_nudge(e, 0.0, 0.10))
        self.window.bind("<Down>", lambda e: self._key_nudge(e, 0.0, -0.10))

        self.window.bind("<Shift-Left>", lambda e: self._key_nudge(e, -1.0, 0.0))
        self.window.bind("<Shift-Right>", lambda e: self._key_nudge(e, 1.0, 0.0))
        self.window.bind("<Shift-Up>", lambda e: self._key_nudge(e, 0.0, 1.0))
        self.window.bind("<Shift-Down>", lambda e: self._key_nudge(e, 0.0, -1.0))

        self.canvas.focus_set()

    def _build_ui(self):
        top = ttk.Frame(self.window)
        top.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(
            top,
            text="Drag the colored OSM overlay over the terrain. "
                 "Arrow keys = 0.10 m; Shift+Arrow = 1.0 m.",
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(top, text="View:").pack(side=tk.LEFT)

        self.view_var = tk.StringVar(value="Blend")
        view_combo = ttk.Combobox(
            top,
            width=10,
            state="readonly",
            textvariable=self.view_var,
            values=("Blend", "Visual", "Hillshade"),
        )
        view_combo.pack(side=tk.LEFT, padx=4)
        view_combo.bind(
            "<<ComboboxSelected>>",
            self._view_changed,
        )

        # Keep arrow keys dedicated to OSM nudge even if the View combobox
        # still owns keyboard focus.
        view_combo.bind("<Left>", lambda e: self._key_nudge(e, -0.10, 0.0))
        view_combo.bind("<Right>", lambda e: self._key_nudge(e, 0.10, 0.0))
        view_combo.bind("<Up>", lambda e: self._key_nudge(e, 0.0, 0.10))
        view_combo.bind("<Down>", lambda e: self._key_nudge(e, 0.0, -0.10))
        view_combo.bind("<Shift-Left>", lambda e: self._key_nudge(e, -1.0, 0.0))
        view_combo.bind("<Shift-Right>", lambda e: self._key_nudge(e, 1.0, 0.0))
        view_combo.bind("<Shift-Up>", lambda e: self._key_nudge(e, 0.0, 1.0))
        view_combo.bind("<Shift-Down>", lambda e: self._key_nudge(e, 0.0, -1.0))

        ttk.Button(
            top,
            text="Zoom -",
            command=lambda: self._change_zoom(1.0 / 1.25),
        ).pack(side=tk.LEFT, padx=(12, 2))

        ttk.Button(
            top,
            text="Zoom +",
            command=lambda: self._change_zoom(1.25),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            top,
            text="Fit",
            command=self._fit_zoom,
        ).pack(side=tk.LEFT, padx=2)

        readout = ttk.Frame(self.window)
        readout.pack(fill=tk.X, padx=8, pady=(0, 6))

        ttk.Label(readout, text="E/W (m):").pack(side=tk.LEFT)
        self.ew_var = tk.StringVar()
        self.ew_box = ttk.Entry(
            readout,
            width=9,
            textvariable=self.ew_var,
        )
        self.ew_box.pack(side=tk.LEFT, padx=(3, 12))

        ttk.Label(readout, text="N/S (m):").pack(side=tk.LEFT)
        self.ns_var = tk.StringVar()
        self.ns_box = ttk.Entry(
            readout,
            width=9,
            textvariable=self.ns_var,
        )
        self.ns_box.pack(side=tk.LEFT, padx=(3, 12))

        ttk.Button(
            readout,
            text="Update Overlay",
            command=self._update_from_entries,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            readout,
            text="Zero",
            command=self._zero_shift,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            readout,
            text="Revert",
            command=self._revert_shift,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            readout,
            text="Apply Shift to Main Window",
            command=self._apply_to_main,
        ).pack(side=tk.LEFT, padx=(18, 3))

        ttk.Button(
            readout,
            text="Apply + Close",
            command=self._apply_and_close,
        ).pack(side=tk.LEFT, padx=3)

        self.info_var = tk.StringVar()
        ttk.Label(
            self.window,
            textvariable=self.info_var,
        ).pack(fill=tk.X, padx=8, pady=(0, 4))

        canvas_frame = ttk.Frame(self.window)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.canvas = tk.Canvas(
            canvas_frame,
            background="black",
            highlightthickness=0,
        )

        hbar = ttk.Scrollbar(
            canvas_frame,
            orient=tk.HORIZONTAL,
            command=self.canvas.xview,
        )

        vbar = ttk.Scrollbar(
            canvas_frame,
            orient=tk.VERTICAL,
            command=self.canvas.yview,
        )

        self.canvas.configure(
            xscrollcommand=hbar.set,
            yscrollcommand=vbar.set,
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

        legend = ttk.Frame(self.window)
        legend.pack(fill=tk.X, padx=8, pady=(2, 8))

        entries = [
            ("Bunker", FEATURE_COLORS["bunker"]),
            ("Green", FEATURE_COLORS["green"]),
            ("Tee", FEATURE_COLORS["tee"]),
            ("Fairway", FEATURE_COLORS["fairway"]),
            ("Rough", FEATURE_COLORS["rough"]),
            ("Water", FEATURE_COLORS["water_hazard"]),
            ("Path", FEATURE_COLORS["cartpath"]),
        ]

        ttk.Label(
            legend,
            text="OSM source outlines (2 px / higher-visibility tracing overlay; before TGC spline shrink):",
        ).pack(side=tk.LEFT, padx=(0, 8))

        for label, color in entries:
            swatch = tk.Label(
                legend,
                text="  ",
                background=color,
                relief=tk.SOLID,
                borderwidth=1,
            )
            swatch.pack(side=tk.LEFT, padx=(3, 1))

            ttk.Label(
                legend,
                text=label,
            ).pack(side=tk.LEFT, padx=(0, 5))

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
        width = max(float(self.canvas.winfo_width()) - 20.0, 200.0)
        height = max(float(self.canvas.winfo_height()) - 20.0, 200.0)

        self.zoom = min(
            width / max(float(self.cols), 1.0),
            height / max(float(self.rows), 1.0),
        )

        self.zoom = max(0.10, min(self.zoom, 4.0))
        self._redraw_everything()

    def _change_zoom(self, factor):
        self.zoom = max(
            0.10,
            min(
                6.0,
                self.zoom * float(factor),
            ),
        )

        self._redraw_everything()

    def _mousewheel_zoom(self, event):
        if event.delta > 0:
            self._change_zoom(1.25)
        elif event.delta < 0:
            self._change_zoom(1.0 / 1.25)

    def _view_changed(self, event=None):
        self._redraw_background()
        self.canvas.focus_set()
        return "break"

    def _key_nudge(self, event, dew, dns):
        self._nudge(dew, dns)
        self.canvas.focus_set()
        return "break"

    def _current_background(self):
        return self.backgrounds.get(
            self.view_var.get(),
            self.blend_rgb,
        )

    def _redraw_background(self):
        arr = self._current_background()

        pil = Image.fromarray(arr, "RGB")

        size = (
            max(1, int(round(self.cols * self.zoom))),
            max(1, int(round(self.rows * self.zoom))),
        )

        if size != pil.size:
            pil = pil.resize(
                size,
                Image.Resampling.LANCZOS,
            )

        self.photo = ImageTk.PhotoImage(pil)

        if self.image_item is None:
            self.image_item = self.canvas.create_image(
                0,
                0,
                image=self.photo,
                anchor=tk.NW,
                tags=("terrain_background",),
            )
        else:
            self.canvas.itemconfigure(
                self.image_item,
                image=self.photo,
            )

        self.canvas.tag_lower("terrain_background")

        self.canvas.configure(
            scrollregion=(
                0,
                0,
                size[0],
                size[1],
            )
        )

    def _display_xy(self, col, row_south):
        shifted_col = (
            float(col)
            + self.shift_ew / self.resolution
        )

        shifted_row_south = (
            float(row_south)
            + self.shift_ns / self.resolution
        )

        x = shifted_col * self.zoom

        y = (
            (self.rows - 1.0 - shifted_row_south)
            * self.zoom
        )

        return x, y

    def _redraw_overlay(self):
        self.canvas.delete("osm_overlay")

        # Constant screen-space width keeps the alignment trace readable
        # without becoming heavy as the user zooms in.
        width = 2

        for feature in self.features:
            coords = []

            for col, row_south in feature["points"]:
                x, y = self._display_xy(
                    col,
                    row_south,
                )

                coords.extend((x, y))

            if len(coords) < 4:
                continue

            if feature["closed"]:
                coords.extend(
                    coords[:2]
                )

            kwargs = {
                "fill": feature["color"],
                "width": width,
                "tags": ("osm_overlay",),
                "smooth": False,
                # Tk canvas lines do not expose true alpha.  The denser
                # gray75 stipple is one visibility step above gray50 while
                # still allowing terrain detail to show through the trace.
                "stipple": "gray75",
            }

            if feature["dash"]:
                kwargs["dash"] = feature["dash"]

            self.canvas.create_line(
                *coords,
                **kwargs,
            )

        self.canvas.tag_raise("osm_overlay")
        self._update_readout()

    def _redraw_everything(self):
        self._redraw_background()
        self._redraw_overlay()

    def _update_readout(self):
        self.ew_var.set(
            f"{self.shift_ew:.2f}"
        )

        self.ns_var.set(
            f"{self.shift_ns:.2f}"
        )

        self.info_var.set(
            "Grid: "
            + str(self.cols)
            + " x "
            + str(self.rows)
            + " @ "
            + f"{self.resolution:.3f}"
            + " m/pixel   |   Shift: "
            + f"{self.shift_ew:.2f} m E/W, "
            + f"{self.shift_ns:.2f} m N/S   |   Pixel shift: "
            + f"{self.shift_ew / self.resolution:.2f}, "
            + f"{self.shift_ns / self.resolution:.2f}"
        )

    def _update_from_entries(self):
        try:
            self.shift_ew = float(
                self.ew_var.get()
            )

            self.shift_ns = float(
                self.ns_var.get()
            )

        except Exception:
            messagebox.showerror(
                "Alignment Viewer",
                "Enter valid numeric E/W and N/S values.",
                parent=self.window,
            )
            return

        self._redraw_overlay()

    def _nudge(self, dew, dns):
        self.shift_ew += float(dew)
        self.shift_ns += float(dns)
        self._redraw_overlay()

    def _zero_shift(self):
        self.shift_ew = 0.0
        self.shift_ns = 0.0
        self._redraw_overlay()

    def _revert_shift(self):
        self.shift_ew = self.original_ew
        self.shift_ns = self.original_ns
        self._redraw_overlay()

    def _drag_start(self, event):
        self.canvas.focus_set()

        self.drag_start_canvas = (
            self.canvas.canvasx(event.x),
            self.canvas.canvasy(event.y),
        )

        self.drag_start_shift = (
            self.shift_ew,
            self.shift_ns,
        )

    def _drag_move(self, event):
        if self.drag_start_canvas is None:
            return

        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)

        dx_canvas = (
            x
            - self.drag_start_canvas[0]
        )

        dy_canvas = (
            y
            - self.drag_start_canvas[1]
        )

        self.shift_ew = (
            self.drag_start_shift[0]
            + dx_canvas
            / max(self.zoom, 1.0e-9)
            * self.resolution
        )

        self.shift_ns = (
            self.drag_start_shift[1]
            - dy_canvas
            / max(self.zoom, 1.0e-9)
            * self.resolution
        )

        self._redraw_overlay()

    def _drag_end(self, event):
        self._drag_move(event)
        self.drag_start_canvas = None
        self.drag_start_shift = None

    def _apply_to_main(self):
        self.ew_entry.delete(
            0,
            tk.END,
        )

        self.ew_entry.insert(
            0,
            f"{self.shift_ew:.2f}",
        )

        self.ns_entry.delete(
            0,
            tk.END,
        )

        self.ns_entry.insert(
            0,
            f"{self.shift_ns:.2f}",
        )

        self.printf(
            "CFS Alignment Viewer applied manual OSM nudge: "
            + f"E/W {self.shift_ew:.2f} m, "
            + f"N/S {self.shift_ns:.2f} m"
        )

        messagebox.showinfo(
            "Alignment Viewer",
            "Shift copied to the main Import Terrain and Features window.\n\n"
            + f"E/W: {self.shift_ew:.2f} m\n"
            + f"N/S: {self.shift_ns:.2f} m",
            parent=self.window,
        )

    def _apply_and_close(self):
        self._apply_to_main()
        self.window.destroy()


def open_alignment_viewer(
    parent,
    heightmap_dir,
    osm_file,
    ew_entry,
    ns_entry,
    printf=print,
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
