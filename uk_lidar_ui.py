"""Independent Tk acquisition dialog; all Tk access stays on the main thread."""
from pathlib import Path
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

import uk_lidar_downloader as uk

VERSION = 'TGC_BETA7_UK_UI_V4'
MODES = {
    'Terrain only — bare-earth DTM': ('dtm', 'dem'),
    'LiDAR point cloud — terrain + trees': ('pointcloud', 'lidar'),
    'LiDAR point cloud — trees only (keep terrain)': ('pointcloud', 'trees'),
}


class Value:
    """Snapshot of an entry value; worker functions never read Tk variables."""
    def __init__(self, value): self.value = value
    def get(self): return self.value


class UKDownloadDialog:
    def __init__(self, parent, project_dir, osm_file, printf=print, on_ready=None, on_close=None):
        self.parent=parent;self.project=Path(project_dir).resolve();self.osm=str(Path(osm_file).resolve())
        self.printf=printf;self.on_ready=on_ready;self.on_close=on_close
        self.queue=queue.Queue();self.cancel=threading.Event();self.busy=False;self.closed=False
        self.close_when_done=False;self.datasets=[];self.bbox=None
        self.window=tk.Toplevel(parent);self.window.title('ex-US LiDAR / DEM From Local OSM — Beta 7')
        from tgc_window_layout import open_large_window
        # TGC_BETA7_LARGE_WINDOWS_V1: normal resizable top-level, no transient
        # dialog style that suppresses the native Windows Maximize control.
        open_large_window(self.window, parent=parent, minimum=(820, 640))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self._controls=[]
        self._build();self.window.grab_set();self._pump_after_id=self.window.after(80,self._pump)

    def _register(self,w):self._controls.append(w);return w

    def _build(self):
        # TGC_BETA7_UK_BUTTON_SELECTION_FIX_V1
        # Private styles only: do not change the application's TabStyle theme.
        self._style = ttk.Style(self.window)
        self._button_style = "TgcUkAction.TButton"
        self._table_style = "TgcUkData.Treeview"
        self._style.configure(
            self._button_style, padding=(12, 7), borderwidth=2,
            relief="raised", anchor="center", background="#F0F0F0",
            foreground="#202020", focusthickness=1, focuscolor="#202020",
        )
        self._style.map(
            self._button_style,
            relief=[("pressed", "!disabled", "sunken"), ("!pressed", "raised")],
            background=[("disabled", "#E5E5E5"), ("pressed", "#D5E8F7"),
                        ("active", "#E5F1FB")],
            foreground=[("disabled", "#808080"), ("!disabled", "#202020")],
        )
        # Match the USGS chooser: blue/white, even when focus leaves the table.
        self._style.configure(
            self._table_style, background="#FFFFFF", fieldbackground="#FFFFFF",
            foreground="#202020", rowheight=max(26, int(self.window.tk.call(
                "font", "metrics", "TkDefaultFont", "-linespace")) + 8),
            borderwidth=1, relief="sunken",
        )
        self._style.map(
            self._table_style,
            background=[("selected", "#0078D7")],
            foreground=[("selected", "#FFFFFF")],
        )
        self._style.configure(
            self._table_style + ".Heading", padding=(6, 5), relief="raised",
            borderwidth=1, background="#E5E5E5", foreground="#202020",
        )
        self._wrap_labels = []
        # TGC_BETA7_UK_PINNED_FOOTER_V1
        # The footer is NOT a row of the potentially overflowing body grid.
        # Its requested height is reserved before allocating the body viewport.
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1, minsize=1)
        self._outer_frame = outer
        # TGC_BETA7_UK_RESIZABLE_REPORT_V1
        # Both panes get real screen space. The report is never a fixed-height
        # child of the upper scrolling settings area; the footer stays separate.
        self._report_fraction = 0.50
        self._report_expanded = False
        self._report_dragging = False
        self._report_layout_after_id = None
        self._report_panes = tk.PanedWindow(
            outer, orient="vertical", sashwidth=10, sashpad=2,
            sashrelief="raised", showhandle=True, handlesize=10,
            opaqueresize=True, borderwidth=0, relief="flat",
            background=self._style.lookup("TFrame", "background") or "#D9D9D9",
            sashcursor="sb_v_double_arrow",
        )
        self._report_panes.grid(row=0, column=0, sticky="nsew")
        viewport = ttk.Frame(self._report_panes)
        self._upper_viewport = viewport
        self._report_panes.add(viewport, minsize=140, stretch="always")
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1, minsize=1)
        self._body_canvas = tk.Canvas(viewport, borderwidth=0,
            highlightthickness=0, width=1, height=1, takefocus=False,
            background=self._style.lookup("TFrame", "background") or "#D9D9D9")
        self._body_canvas.grid(row=0, column=0, sticky="nsew")
        self._body_scrollbar = ttk.Scrollbar(viewport, orient="vertical",
                                           command=self._body_canvas.yview)
        self._body_scrollbar.grid(row=0, column=1, sticky="ns")
        self._body_canvas.configure(yscrollcommand=self._body_scrollbar.set,
                                    yscrollincrement=20)
        box = ttk.Frame(self._body_canvas, padding=(0, 0, 8, 0))
        self._body_frame = box
        self._body_item = self._body_canvas.create_window(0, 0, anchor="nw", window=box)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(6, weight=1, minsize=80)
        label = ttk.Label(box, text="ex-US LiDAR / DEM From Local OSM",
                          font=("Segoe UI", 14, "bold"), wraplength=1050)
        label.grid(row=0, column=0, sticky="ew")
        self._wrap_labels.append(label)
        for row, text in ((1, "Current project: " + str(self.project)),
                          (2, "Local OSM: " + self.osm),
                          (3, "Course extent + 150 m download buffer. The 50 m tree filter is not changed.")):
            label = ttk.Label(box, text=text, wraplength=1050, justify="left")
            label.grid(row=row, column=0, sticky="ew", pady=(5 if row == 1 else 0, 0))
            self._wrap_labels.append(label)

        row = ttk.Frame(box)
        row.grid(row=4, column=0, sticky="ew", pady=(8, 6))
        row.columnconfigure(3, weight=1)
        self._search_frame = row
        self._region_label = ttk.Label(row, text="Country / region:")
        self._region_label.grid(row=0, column=0, sticky="w")
        self.region = tk.StringVar(value="Auto")
        c = self._register(ttk.Combobox(row, textvariable=self.region,
            values=("Auto",) + tuple(sorted((name for name in uk.REGIONS if name != "Auto"), key=str.casefold)), state="readonly", width=18))
        self._region_combo = c
        c.grid(row=0, column=1, sticky="ew", padx=(5, 12))
        c.bind("<<ComboboxSelected>>", self._selection_changed)
        self._mode_label = ttk.Label(row, text="Use:")
        self._mode_label.grid(row=0, column=2, sticky="w")
        self.mode = tk.StringVar(value=next(iter(MODES)))
        c = self._register(ttk.Combobox(row, textvariable=self.mode,
            values=tuple(MODES), state="readonly", width=38))
        self._mode_combo = c
        c.grid(row=0, column=3, sticky="ew", padx=5)
        c.bind("<<ComboboxSelected>>", self._selection_changed)
        # Search has its own row to stay readable under Windows DPI scaling.
        self.discover_button = self._register(ttk.Button(
            row, text="Find Available Data", command=self.find,
            style=self._button_style, takefocus=True))
        self.discover_button.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        label = ttk.Label(box,
            text="Automatic terrain: UK, Canada, Finland, France, Germany (NRW/Bavaria), Japan, Netherlands, New Zealand, Poland, Spain and Switzerland. Native DEM limit: 5 m. Australia / Mexico / Northern Ireland: portal only.",
            wraplength=1050, justify="left")
        label.grid(row=5, column=0, sticky="ew", pady=(0, 5))
        self._wrap_labels.append(label)

        pane = ttk.Frame(box)
        pane.grid(row=6, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(pane, style=self._table_style,
            columns=("region", "title", "date", "resolution", "tiles", "size"),
            show="headings", selectmode="browse", height=3, takefocus=True)
        for name, title, width in [
            ("region", "Region", 85), ("title", "Dataset / acquisition", 370),
            ("date", "Date / year", 110), ("resolution", "Resolution", 95),
            ("tiles", "Files", 55), ("size", "Download size", 125),
        ]:
            self.table.heading(name, text=title)
            self.table.column(name, width=width, minwidth=50, stretch=name == "title",
                              anchor="center" if name in ("date", "resolution", "tiles") else "w")
        self.table.tag_configure("uk_selected", background="#0078D7", foreground="#FFFFFF")
        yscroll = ttk.Scrollbar(pane, orient="vertical", command=self.table.yview)
        xscroll = ttk.Scrollbar(pane, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.table.bind("<<TreeviewSelect>>", self._details)
        self.table.bind("<FocusIn>", self._refresh_selection_highlight, add="+")
        self.table.bind("<FocusOut>", self._refresh_selection_highlight, add="+")
        self.table.bind("<Return>", self._download_key)
        self.selected_text = tk.StringVar(value="Selected dataset: none")
        label = ttk.Label(box, textvariable=self.selected_text,
                          font=("Segoe UI", 10, "bold"), wraplength=1050, justify="left")
        label.grid(row=7, column=0, sticky="ew", pady=(6, 2))
        self._wrap_labels.append(label)
        self.detail = tk.StringVar(value="Choose a region and product, then search. No data is downloaded automatically.")
        label = ttk.Label(box, textvariable=self.detail, wraplength=1050, justify="left")
        label.grid(row=8, column=0, sticky="ew", pady=(0, 5))
        self._wrap_labels.append(label)
        self.process = tk.BooleanVar(value=True)
        self._register(ttk.Checkbutton(box, text="Start normal processing after download",
            variable=self.process)).grid(row=9, column=0, sticky="w", pady=4)
        self._build_report_pane()
        footer = ttk.Frame(outer, padding=(0, 8, 0, 0))
        self._footer_frame = footer
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.portal_button = self._register(ttk.Button(footer,
            text="Open Provider Website", command=self.portal,
            style=self._button_style, takefocus=True))
        self.portal_button.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.download_button = self._register(ttk.Button(footer,
            text="Download Selected", command=self.download,
            style=self._button_style, takefocus=True))
        self.download_button.grid(row=0, column=2, sticky="e", padx=8)
        self.download_button.state(["disabled"])
        self.cancel_button = ttk.Button(footer, text="Close", command=self.close,
                                       style=self._button_style, takefocus=True)
        self.cancel_button.grid(row=0, column=3, sticky="e")
        self._body_canvas.bind("<Configure>", self._sync_body_layout, add="+")
        box.bind("<Configure>", self._sync_body_layout, add="+")
        row.bind("<Configure>", self._layout_search_controls, add="+")
        row.bind("<Configure>", self._sync_body_layout, add="+")
        # A fixed-size canvas child does not receive Configure merely because
        # its requested size changes. Watch variable-height content too.
        for label in self._wrap_labels:
            label.bind("<Configure>", self._sync_body_layout, add="+")
        footer.bind("<Configure>", self._layout_footer, add="+")
        self.cancel_button.bind("<Configure>", self._layout_footer, add="+")
        # Local bindings only; never bind_all() or change another window's wheel.
        pending = [self._body_canvas, box]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            widget.bind("<FocusIn>", self._show_body_widget, add="+")
            if not isinstance(widget, (ttk.Treeview, tk.Text, ttk.Scrollbar, ttk.Combobox)):
                for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(event, self._scroll_body, add="+")

    def _build_report_pane(self):
        """Resizable, independent status area, with readable logs while working."""
        report = ttk.Frame(self._report_panes, padding=(0, 4, 0, 0))
        self._report_frame = report
        report.columnconfigure(0, weight=1)
        report.rowconfigure(3, weight=1, minsize=40)
        self._report_panes.add(report, minsize=180, stretch="always")
        tools = ttk.Frame(report)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tools.columnconfigure(0, weight=1)
        ttk.Label(tools, text="Status / report — drag divider above", font=("Segoe UI", 10, "bold"),
                  width=1).grid(row=0, column=0, sticky="ew")
        # Reading/copying the report remains available during search/download.
        # Do not register these with the controls disabled by _busy().
        self.expand_report_button = ttk.Button(
            tools, text="Expand Report", command=self._toggle_report,
            style=self._button_style, takefocus=True)
        self.expand_report_button.grid(row=0, column=1, padx=(4, 4))
        self.copy_report_button = ttk.Button(
            tools, text="Copy Report", command=self._copy_report,
            style=self._button_style, takefocus=True)
        self.copy_report_button.grid(row=0, column=2)
        self.status = tk.StringVar(value="Ready. Drag the divider above to resize the report.")
        # One summary line; every complete message is retained below. A lengthy
        # exception must not consume the entire pane by wrapping this label.
        ttk.Label(report, textvariable=self.status, width=1, anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(0, 3))
        self.progress = ttk.Progressbar(report, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        log_frame = ttk.Frame(report)
        self._log_frame = log_frame
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=12, width=1, wrap="word",
                           state="disabled", font="TkFixedFont", takefocus=True,
                           padx=5, pady=4)
        self.log.grid(row=0, column=0, sticky="nsew")
        self._log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self._log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=self._log_scrollbar.set)
        self.log.bind("<Control-a>", self._select_report)
        self.log.bind("<Control-A>", self._select_report)
        # Re-measure after native toolbar/text geometry has settled (Windows
        # fonts and DPI do not share the Linux test environment's pixel sizes).
        tools.bind("<Configure>", self._schedule_report_layout, add="+")
        self.log.bind("<Configure>", self._schedule_report_layout, add="+")
        report.bind("<<ThemeChanged>>", self._schedule_report_layout, add="+")
        self._report_panes.bind("<Configure>", self._schedule_report_layout, add="+")
        self._report_panes.bind("<ButtonPress-1>", self._report_drag_start, add="+")
        self._report_panes.bind("<ButtonRelease-1>", self._report_drag_end, add="+")
        self._schedule_report_layout()

    def _schedule_report_layout(self, event=None):
        if self.closed or self._report_dragging:
            return
        if self._report_layout_after_id is None:
            self._report_layout_after_id = self.window.after_idle(self._place_report_split)

    def _report_height_budget(self):
        """Return native pixel requirements without changing fonts or geometry."""
        # TGC_BETA7_UK_REPORT_FONT_HEIGHT_V1
        # Text.height is a request in lines, not a guarantee when its parent is
        # split by percentage. Reserve the real text height PLUS all chrome.
        line = max(1, int(self.log.tk.call(
            "font", "metrics", self.log.cget("font"), "-linespace")))
        inset = 2 * sum(self.log.winfo_pixels(self.log.cget(key))
                        for key in ("borderwidth", "highlightthickness", "pady"))
        # Includes the toolbar, summary, progress bar and their frame padding.
        # Use requested sizes, not the already-compressed allocated log height.
        chrome = max(0, self._report_frame.winfo_reqheight()
                        - self.log.winfo_reqheight())
        preferred = chrome + 12 * line + max(10, inset)
        minimum = chrome + max(40, 2 * line) + inset
        sash = (self._report_panes.winfo_pixels(self._report_panes.cget("sashwidth"))
                + 2 * self._report_panes.winfo_pixels(self._report_panes.cget("sashpad")))
        return preferred, minimum, sash

    def _place_report_split(self):
        self._report_layout_after_id = None
        if self.closed or self._report_dragging or self._report_expanded:
            return
        height = self._report_panes.winfo_height()
        if height < 50:
            return
        preferred, report_minimum, sash = self._report_height_budget()
        # A small display still keeps the upper pane and fixed footer reachable.
        # Users remain free to drag the report smaller; only the untouched
        # default reserves twelve native-font lines when that space is available.
        upper_min = min(140, max(40, height // 4))
        lower_min = min(max(180, report_minimum),
                        max(40, height - upper_min - sash))
        for pane, minimum in ((self._upper_viewport, upper_min), (self._report_frame, lower_min)):
            if int(self._report_panes.panecget(pane, "minsize")) != minimum:
                self._report_panes.paneconfigure(pane, minsize=minimum)
        target = int(round(self._report_fraction * height))
        if not getattr(self, "_report_user_split", False):
            # Budget the normal opening size from the measured font. Preserve
            # proportional growth/shrink on a later window resize, rather than
            # pinning the log at a fixed line count at every window size.
            # A neutral allocation reference, NOT a window-size cap. At 820px
            # the pane reserves 12 real text lines; larger windows share extra
            # height with the report. The top-level starts near full-screen.
            opening_height = 820
            resize_share = int(round((1.0 - self._report_fraction)
                                     * (self.window.winfo_height() - opening_height)))
            target = min(target, height - preferred - resize_share - sash - 2)
        target = max(upper_min, min(height - lower_min - sash, target))
        if self._report_panes.sash_coord(0)[1] != target:
            self._report_panes.sash_place(0, 0, target)

    def _report_drag_start(self, event):
        if self._report_expanded:
            return
        part = self._report_panes.identify(event.x, event.y)
        self._report_dragging = bool(part)
        if self._report_dragging and self._report_layout_after_id is not None:
            self.window.after_cancel(self._report_layout_after_id)
            self._report_layout_after_id = None

    def _report_drag_end(self, event=None):
        if self._report_dragging and not self._report_expanded:
            self._report_user_split = True
            self._report_fraction = max(0.1, min(0.9,
                self._report_panes.sash_coord(0)[1] / max(1, self._report_panes.winfo_height())))
        self._report_dragging = False

    def _toggle_report(self):
        self._report_expanded = not self._report_expanded
        self._report_panes.paneconfigure(self._upper_viewport, hide=self._report_expanded)
        self.expand_report_button.configure(
            text="Restore Split" if self._report_expanded else "Expand Report")
        if not self._report_expanded:
            self._schedule_report_layout()
        self.log.focus_set()

    def _copy_report(self):
        # Copy complete text, including off-screen lines; never clear the report.
        self.window.clipboard_clear()
        self.window.clipboard_append(self.log.get("1.0", "end-1c"))

    def _select_report(self, event=None):
        self.log.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _resize_labels(self, event):
        width = max(80, int(event.width) - 16)
        if width == getattr(self, "_last_wrap_width", None):
            return
        self._last_wrap_width = width
        for label in self._wrap_labels:
            label.configure(wraplength=width)

    def _sync_body_layout(self, event=None):
        """Fit the body to the viewport, scrolling rather than clipping controls."""
        if self.closed:
            return
        canvas = self._body_canvas
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        if width != getattr(self, "_body_width", None):
            self._body_width = width
            canvas.itemconfigure(self._body_item, width=width)
        required = max(height, self._body_frame.winfo_reqheight())
        if required != getattr(self, "_body_height", None):
            self._body_height = required
            canvas.itemconfigure(self._body_item, height=required)
        canvas.configure(scrollregion=(0, 0, width, required))
        if event is not None and event.widget == self._body_frame:
            self._resize_labels(event)

    def _layout_search_controls(self, event=None):
        frame = self._search_frame
        width = frame.winfo_width()
        required = sum(w.winfo_reqwidth() for w in (
            self._region_label, self._region_combo, self._mode_label, self._mode_combo)) + 32
        stacked = width < required
        if stacked == getattr(self, "_search_stacked", None):
            return
        self._search_stacked = stacked
        for col in range(4):
            frame.columnconfigure(col, weight=0)
        if stacked:
            frame.columnconfigure(1, weight=1)
            self._region_combo.grid(row=0, column=1, columnspan=3, sticky="w", padx=(5, 0))
            self._mode_label.grid(row=1, column=0, sticky="w", pady=(5, 0))
            self._mode_combo.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(5, 0), pady=(5, 0))
            self.discover_button.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        else:
            frame.columnconfigure(3, weight=1)
            self._region_combo.grid(row=0, column=1, columnspan=1, sticky="ew", padx=(5, 12))
            self._mode_label.grid(row=0, column=2, sticky="w", pady=0)
            self._mode_combo.grid(row=0, column=3, columnspan=1, sticky="ew", padx=5, pady=0)
            self.discover_button.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _layout_footer(self, event=None):
        """Reflow action buttons without ever placing them in the scrollable body."""
        footer = self._footer_frame
        width = max(1, footer.winfo_width())
        buttons = (self.portal_button, self.download_button, self.cancel_button)
        widths = [w.winfo_reqwidth() for w in buttons]
        rows = 1 if sum(widths) + 24 <= width else (2 if sum(widths[1:]) + 8 <= width else 3)
        if rows == getattr(self, "_footer_rows", None):
            return
        self._footer_rows = rows
        for w in buttons:
            w.grid_forget()
        for col in range(4):
            footer.columnconfigure(col, weight=0)
        if rows == 1:
            footer.columnconfigure(1, weight=1)
            self.portal_button.grid(row=0, column=0, sticky="w", padx=(0, 8))
            self.download_button.grid(row=0, column=2, sticky="e", padx=8)
            self.cancel_button.grid(row=0, column=3, sticky="e")
        elif rows == 2:
            footer.columnconfigure(0, weight=1)
            footer.columnconfigure(1, weight=1)
            self.portal_button.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
            self.download_button.grid(row=1, column=0, sticky="w", padx=(0, 8))
            self.cancel_button.grid(row=1, column=1, sticky="e")
        else:
            footer.columnconfigure(0, weight=1)
            for row, w in enumerate(buttons):
                w.grid(row=row, column=0, sticky="ew", pady=(0, 6 if row < 2 else 0))

    def _scroll_body(self, event):
        if self._body_canvas.yview() == (0.0, 1.0):
            return None
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return None
            units = -max(1, int(abs(delta) / 120)) * (1 if delta > 0 else -1)
        self._body_canvas.yview_scroll(units, "units")
        return "break"

    def _show_body_widget(self, event):
        """Tab navigation keeps controls visible in the scrollable body."""
        widget = event.widget
        y = 0
        while widget != self._body_frame:
            if widget == self._body_canvas or widget == self.window:
                return
            y += widget.winfo_y()
            widget = widget.master
            if widget is None:
                return
        canvas = self._body_canvas
        top = canvas.canvasy(0)
        bottom = y + event.widget.winfo_height()
        visible = canvas.winfo_height()
        if y < top or event.widget.winfo_height() > visible:
            new_top = y
        elif bottom > top + visible:
            new_top = bottom - visible
        else:
            return
        canvas.yview_moveto(max(0.0, new_top) / max(1, self._body_frame.winfo_height()))

    def _refresh_selection_highlight(self, event=None):
        selected = set(self.table.selection())
        for iid in self.table.get_children(""):
            tags = tuple(tag for tag in self.table.item(iid, "tags") if tag != "uk_selected")
            if iid in selected:
                tags += ("uk_selected",)
            self.table.item(iid, tags=tags)

    def _download_key(self, event=None):
        # Uses the same confirmation and selected-dataset route as the button.
        if not self.busy and self._selected() is not None:
            self.download()
        return "break"

    def _say(self,text):
        text = str(text)
        self.status.set(text.splitlines()[0] if text else '')
        self.printf(text)
        # Follow new output only when already at the end. Scrolling back to
        # inspect a provider error must not snap back on the next message.
        follow = self.log.yview()[1] >= 0.995
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        if follow:
            self.log.see('end')
        self.log.configure(state='disabled')

    def _worker_log(self,text):self.queue.put(('log',str(text)))

    def _busy(self,value):
        self.busy=value
        for w in self._controls:
            w.state(['disabled'] if value else ['!disabled'])
        if value or self._selected() is None:self.download_button.state(['disabled'])
        self._refresh_selection_highlight()
        self.cancel_button.configure(text='Cancel Download / Search' if value else 'Close')
        if value:self.progress.start(12)
        else:self.progress.stop()

    def _selection_changed(self,event=None):
        if self.busy:return
        self.datasets=[];self.bbox=None;self.table.delete(*self.table.get_children());self.download_button.state(['disabled'])
        self.selected_text.set('Selected dataset: none')
        self.detail.set('Selection changed. Find Available Data again before downloading.')
        notice=uk.support_notice(self.region.get(),MODES[self.mode.get()][0])
        if notice:self.detail.set(notice)

    def _start(self,fn,success):
        self.cancel.clear();self._busy(True)
        def worker():
            try:self.queue.put((success,fn()))
            except uk.Cancelled as exc:self.queue.put(('cancelled',str(exc)))
            except Exception as exc:self.queue.put(('error',(str(exc),traceback.format_exc())))
        threading.Thread(target=worker,name='TGC-UK-Acquisition',daemon=True).start()

    def find(self):
        if self.busy:return
        region=self.region.get();kind,mode=MODES[self.mode.get()]
        if mode=='trees' and not (self.project/'heightmap.npy').is_file():
            messagebox.showwarning('ex-US Trees Only','Create or load the project terrain heightmap first.',parent=self.window);return
        notice=uk.support_notice(region,kind)
        if notice:
            self._say('NOTICE: '+notice)
            self.detail.set(notice)
            return
        self.datasets=[];self.table.delete(*self.table.get_children());self.bbox=None
        self.selected_text.set('Selected dataset: none')
        def work():
            bbox=uk.course_bbox(self.osm,printf=self._worker_log)
            data,errors=uk.discover(bbox,region,kind,self.cancel,self._worker_log)
            return bbox,data,errors
        self._start(work,'found')

    def _selected(self):
        selected=self.table.selection()
        if not selected:
            return None
        try:
            index = int(selected[0])
        except (TypeError, ValueError):
            return None
        return self.datasets[index] if 0 <= index < len(self.datasets) else None

    def _details(self,event=None):
        self._refresh_selection_highlight()
        ds=self._selected()
        if ds:
            self.selected_text.set('Selected: ' + ds.title + ' | ' + str(ds.year or 'Date not supplied') + ' | ' + ds.region)
            self.detail.set('Licence: '+ds.licence+'\n'+ds.notes)
            self.download_button.state(['disabled'] if self.busy else ['!disabled'])
        else:
            self.selected_text.set('Selected dataset: none')
            self.download_button.state(['disabled'])
            if self.datasets:
                self.detail.set('Select a dataset to view its details and enable Download Selected.')

    def download(self):
        ds=self._selected()
        if self.busy or ds is None or self.bbox is None:return
        kind,mode=MODES[self.mode.get()]
        if ds.kind!=kind:return
        process=bool(self.process.get());bbox=tuple(self.bbox)
        size=('%.1f MB'%(ds.known_bytes/1e6)) if ds.known_bytes is not None else 'Not supplied by the provider; full intersecting tiles may be large.'
        if not messagebox.askyesno('Download selected ex-US data',ds.title+'\n\nDownload size: '+size+'\nLicence: '+ds.licence+'\n\nFiles go under '+str(self.project/uk.storage_folder(ds.region))+'.\n\nNo existing heightmap is changed by downloading.\nProceed?',parent=self.window):return
        def work():
            result=uk.download(ds,bbox,self.project,self.osm,self.cancel,self._worker_log)
            return result,mode,process,ds
        self._start(work,'downloaded')

    def portal(self):
        ds=self._selected();region=ds.region if ds else self.region.get()
        if region=='Auto':
            try:
                box=self.bbox or uk.course_bbox(self.osm,printf=self._say)
                choices=uk.provider_regions(box);region=choices[0] if choices else 'England'
            except Exception:region='England'
        webbrowser.open(uk.PROVIDERS[region])

    def _pump(self):
        self._pump_after_id = None
        if self.closed:return
        try:
            while True:
                kind,payload=self.queue.get_nowait()
                if kind=='log':self._say(payload);continue
                self._busy(False)
                if kind=='found':
                    self.bbox,self.datasets,errors=payload
                    for i,ds in enumerate(self.datasets):
                        size='Spatial window' if any(a.transport in ('cog','gsi_png') for a in ds.assets) else ('%.1f MB'%(ds.known_bytes/1e6) if ds.known_bytes is not None else 'Not supplied')
                        self.table.insert('','end',iid=str(i),values=(ds.region,ds.title,ds.year,ds.resolution,len(ds.assets),size))
                    if self.datasets:
                        self.table.selection_set('0');self.table.focus('0');self.table.see('0');self._details()
                        self.table.focus_set()
                    else:
                        self.detail.set('No selectable datasets. '+('Provider errors were reported above; this is not a coverage verdict.' if errors else 'No matching products were returned for this extent.'))
                elif kind=='downloaded':
                    result,mode,process,ds=payload
                    self._say('ex-US download complete: '+result.data_dir)
                    if process and not self.close_when_done:
                        self._finish()
                        if self.on_ready:self.on_ready(result,mode,ds)
                        return
                elif kind=='cancelled':self._say(payload)
                elif kind=='error':
                    message,trace=payload;self._say('ex-US acquisition failed: '+message);self.printf(trace)
                    if not self.close_when_done:messagebox.showerror('ex-US LiDAR / DEM',message+'\n\nExisting project heightmap/mask are unchanged. See Tool status output.',parent=self.window)
                if self.close_when_done:self._finish();return
        except queue.Empty:pass
        if not self.closed:self._pump_after_id=self.window.after(80,self._pump)

    def close(self):
        if self.busy:
            self.close_when_done=True;self.cancel.set();self.cancel_button.state(['disabled'])
            self._say('Cancellation requested. Current network reads have a bounded timeout; partial acquisition files will be removed.')
        else:self._finish()

    def _finish(self):
        if self.closed:return
        self.closed=True
        after_id = getattr(self, "_pump_after_id", None)
        if after_id is not None:
            try:self.window.after_cancel(after_id)
            except tk.TclError:pass
            self._pump_after_id = None
        layout_id = getattr(self, "_report_layout_after_id", None)
        if layout_id is not None:
            try:self.window.after_cancel(layout_id)
            except tk.TclError:pass
            self._report_layout_after_id = None
        self.progress.stop()
        try:self.window.grab_release()
        except tk.TclError:pass
        self.window.destroy()
        if self.on_close:self.on_close()
