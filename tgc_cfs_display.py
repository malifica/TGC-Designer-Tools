"""Beta 7 CFS display-only controls and importer-compatible projection.

No elevation, course geometry, source OSM, mask pixels or nudge values are
changed by brightness/contrast/zoom. Each redraw allocates only a viewport tile,
never a 30x raster of the entire project. No origin/project state is global.
"""
import math
from PIL import Image
import pyproj

MAX_ZOOM = 30.0
ALIGNMENT_GEOMETRY_VERSION = 'beta7-importer-datum-cell-edge-v1'


def importer_transformer(projection):
    """Exactly GeoPointCloud's geographic source/target and axis convention.

    Keep the existing Proj-based source rather than substituting EPSG:4326;
    those can select different datum operations (notably NAD83(PA11)).
    """
    from GeoPointCloud import GeoPointCloud
    source = GeoPointCloud()._platlon
    try:
        from tgc_projection_cache import from_proj
    except ImportError:
        return pyproj.Transformer.from_proj(source, projection, True)
    return from_proj(source, projection)


def screen_point(col, row_south, rows, resolution, zoom, east=0., north=0.):
    """Continuous SW cell-edge coordinates -> NW canvas coordinates."""
    return ((float(col) + float(east) / resolution) * zoom,
            (float(rows) - float(row_south) - float(north) / resolution) * zoom)


def tone_lut(brightness=1., contrast=1.):
    """Fixed mid-grey pivot: tone does not vary when the viewport pans."""
    brightness = float(brightness)
    contrast = float(contrast)
    if not (math.isfinite(brightness) and math.isfinite(contrast)):
        raise ValueError('Display brightness/contrast must be finite')
    brightness = max(.25, min(2., brightness))
    contrast = max(.25, min(3., contrast))
    return [max(0, min(255, int(round(((i - 127.5) * contrast + 127.5) * brightness))))
            for i in range(256)]


def viewport_tile(source, zoom, x, y, width, height, brightness=1., contrast=1., pad=24):
    """Return (PIL RGB tile, canvas origin), bounded by viewport + 2*pad.

    Fractional source extents preserve the exact same world-to-canvas scale at
    all zooms. Do not round each crop to source pixels then resize: that drifts.
    """
    zoom = float(zoom)
    if not math.isfinite(zoom) or zoom < .1 or zoom > MAX_ZOOM:
        raise ValueError('Zoom must be between 0.1 and 30')
    sw, sh = source.size
    width, height = max(1, int(math.ceil(width))), max(1, int(math.ceil(height)))
    left = max(0, int(math.floor(float(x))) - pad)
    top = max(0, int(math.floor(float(y))) - pad)
    right = min(int(math.ceil(sw * zoom)), int(math.ceil(float(x))) + width + pad)
    bottom = min(int(math.ceil(sh * zoom)), int(math.ceil(float(y))) + height + pad)
    if right <= left or bottom <= top:
        return None, (left, top)
    tile = source.transform((right-left, bottom-top), Image.Transform.EXTENT,
                            (left/zoom, top/zoom, right/zoom, bottom/zoom),
                            resample=Image.Resampling.BILINEAR)
    if abs(float(brightness)-1.) > 1e-12 or abs(float(contrast)-1.) > 1e-12:
        tile = tile.point(tone_lut(brightness, contrast) * 3)
    return tile, (left, top)


def initialize(viewer):
    viewer._cfs_background_cache = {}
    viewer._cfs_redraw_id = None
    viewer._cfs_last_tile_key = None
    viewer._cfs_tile_size = (0, 0)
    viewer._cfs_scrollregion = None


def queue_redraw(viewer, *_):
    if viewer.closed or not viewer.ready:
        return
    if viewer._cfs_redraw_id is not None:
        return
    def draw():
        viewer._cfs_redraw_id = None
        if not viewer.closed and viewer.ready:
            viewer._redraw_background()
    viewer._cfs_redraw_id = viewer.window.after(20, draw)


def scroll_changed(viewer, scrollbar, first, last):
    scrollbar.set(first, last)
    queue_redraw(viewer)


def tone_changed(viewer, *_):
    viewer.brightness_text.set('%d%%' % round(viewer.brightness_var.get() * 100))
    viewer.contrast_text.set('%d%%' % round(viewer.contrast_var.get() * 100))
    queue_redraw(viewer)


def reset_tone(viewer):
    viewer.brightness_var.set(1.)
    viewer.contrast_var.set(1.)
    tone_changed(viewer)


def add_display_controls(viewer, frame):
    import tkinter as tk
    from tkinter import ttk
    from tgc_cfs_widgets import action_button
    viewer.brightness_var = tk.DoubleVar(master=viewer.window, value=1.)
    viewer.contrast_var = tk.DoubleVar(master=viewer.window, value=1.)
    viewer.brightness_text = tk.StringVar(master=viewer.window, value='100%')
    viewer.contrast_text = tk.StringVar(master=viewer.window, value='100%')
    ttk.Label(frame, text='Brightness:').pack(side=tk.LEFT)
    viewer.brightness_slider = viewer._register(ttk.Scale(
        frame, from_=.25, to=2., length=190, variable=viewer.brightness_var,
        command=lambda *_: tone_changed(viewer)))
    viewer.brightness_slider.pack(side=tk.LEFT, padx=(6,4))
    ttk.Label(frame, textvariable=viewer.brightness_text, width=5).pack(side=tk.LEFT)
    ttk.Label(frame, text='Contrast:').pack(side=tk.LEFT, padx=(15,0))
    viewer.contrast_slider = viewer._register(ttk.Scale(
        frame, from_=.25, to=3., length=190, variable=viewer.contrast_var,
        command=lambda *_: tone_changed(viewer)))
    viewer.contrast_slider.pack(side=tk.LEFT, padx=(6,4))
    ttk.Label(frame, textvariable=viewer.contrast_text, width=5).pack(side=tk.LEFT)
    viewer.reset_tone_button = viewer._register(action_button(
        frame, text='Reset Brightness / Contrast', command=lambda: reset_tone(viewer)))
    viewer.reset_tone_button.pack(side=tk.LEFT, padx=10)
    ttk.Label(frame, text='Display only; source terrain is unchanged').pack(side=tk.LEFT)


def set_zoom(viewer, requested, anchor=None):
    if not viewer._can_interact():
        return
    value = float(requested)
    if not math.isfinite(value):
        return
    new_zoom = max(.1, min(MAX_ZOOM, value))
    old_zoom = max(.1, float(viewer.zoom))
    if anchor is None:
        anchor = (viewer.canvas.winfo_width()/2., viewer.canvas.winfo_height()/2.)
    ax, ay = anchor
    sx = viewer.canvas.canvasx(ax) / old_zoom
    sy = viewer.canvas.canvasy(ay) / old_zoom
    viewer.zoom = new_zoom
    full_w, full_h = viewer.cols * new_zoom, viewer.rows * new_zoom
    region = (0, 0, full_w, full_h)
    viewer._cfs_scrollregion = region
    viewer.canvas.configure(scrollregion=region)
    viewer.canvas.xview_moveto(max(0., (sx*new_zoom-ax)/max(1., full_w)))
    viewer.canvas.yview_moveto(max(0., (sy*new_zoom-ay)/max(1., full_h)))
    viewer._redraw_everything()


def zoom_selected(viewer, *_):
    try:
        set_zoom(viewer, float(viewer.zoom_var.get().replace('x','').strip()))
    except (ValueError, TypeError):
        viewer._update_readout()
