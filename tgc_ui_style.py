"""TGC Beta 7 shared presentation; no terrain, OSM, or course mutations.

Reads the installed CFS action_button factory, rather than shipping an older
copy of that module. Tk widget instances, commands, state, variables, geometry
managers and original event bindings are retained. Application-owned Tk/ttk
controls are styled when mapped. Native OS file/message dialogs stay native.
"""
from __future__ import annotations
import re
import sys
import tkinter as tk
from tkinter import ttk
import weakref

MARKER = 'TGC_BETA7_SHARED_CFS_UI_V1'
PREFIX = 'TgcShared'
PRIMARY_TEXT = (
    'select course directory', 'import .course', 'export .course',
    'select and import heightmap', 'select lidar', 'select dem',
    'import unity', 'convert + dem', 'apply +', 'apply selected',
    'apply alignment', 'apply moves', 'confirm placement', 'rebuild mask',
    'rebuild aligned mask', 'local tee', 'download', 'discover',
    'create course', 'generate heightmap', 'save', 'accept', 'yes, merge',
)


def _get(widget, key, default=''):
    try:
        return widget.cget(key)
    except (tk.TclError, AttributeError):
        return default


def _neutral(widget, color):
    """Do not overwrite error/status/legend colors that carry meaning."""
    try:
        rgb = widget.winfo_rgb(str(color))
        return max(rgb) - min(rgb) < 3600
    except (tk.TclError, TypeError):
        return True


def _state_color(style, widget, option, state=(), default=''):
    name = str(_get(widget, 'style')) or widget.winfo_class()
    value = style.lookup(name, option, state=state)
    return value or default


def _sample_button(style, widget):
    """Capture both classic Tk and themed ttk CFS button implementations."""
    if widget.winfo_class() == 'Button':
        return {
            'background': str(_get(widget, 'background')),
            'foreground': str(_get(widget, 'foreground')),
            'activebackground': str(_get(widget, 'activebackground')),
            'activeforeground': str(_get(widget, 'activeforeground')),
            'disabledforeground': str(_get(widget, 'disabledforeground')),
            'disabledbackground': str(_get(widget, 'background')),
            'font': _get(widget, 'font', 'TkDefaultFont'),
            'relief': str(_get(widget, 'relief', 'raised')),
            'borderwidth': _get(widget, 'borderwidth', 1),
            'padx': _get(widget, 'padx', 10),
            'pady': _get(widget, 'pady', 5),
            'highlightthickness': _get(widget, 'highlightthickness', 1),
            'highlightbackground': _get(widget, 'highlightbackground'),
            'highlightcolor': _get(widget, 'highlightcolor'),
            'cursor': _get(widget, 'cursor'),
            'source_style': '',
        }
    if widget.winfo_class() != 'TButton':
        raise RuntimeError('Unsupported CFS button class: ' + widget.winfo_class())
    bg = _state_color(style, widget, 'background', default='#f0f0f0')
    fg = _state_color(style, widget, 'foreground', default='#202020')
    return {
        'background': bg, 'foreground': fg,
        'activebackground': _state_color(style, widget, 'background', ('active',), bg),
        'activeforeground': _state_color(style, widget, 'foreground', ('active',), fg),
        'disabledbackground': _state_color(style, widget, 'background', ('disabled',), bg),
        'disabledforeground': _state_color(style, widget, 'foreground', ('disabled',), '#808080'),
        'font': _state_color(style, widget, 'font', default='TkDefaultFont'),
        'relief': _state_color(style, widget, 'relief', default='raised'),
        'borderwidth': _state_color(style, widget, 'borderwidth', default=1),
        'padding': _state_color(style, widget, 'padding', default=(10, 5)),
        'padx': 10, 'pady': 5, 'highlightthickness': 1,
        'highlightbackground': bg, 'highlightcolor': fg,
        'cursor': _get(widget, 'cursor'),
        'source_style': str(_get(widget, 'style')),
    }


def cfs_palette(root):
    """Use the user's installed, approved CFS widget helper as source of truth."""
    from tgc_cfs_widgets import action_button
    style = ttk.Style(root)
    host = ttk.Frame(root)  # Never packed or displayed.
    try:
        standard = action_button(host, text='Style sample', command=lambda: None)
        primary = action_button(host, text='Style sample', command=lambda: None, primary=True)
        normal = _sample_button(style, standard)
        accent = _sample_button(style, primary)
        return {
            'normal': normal, 'primary': accent,
            'panel': '#d4d7db',  # User-requested slightly darker application grey (V6).
            'text': style.lookup('TLabel', 'foreground') or normal['foreground'],
            'field': style.lookup('TEntry', 'fieldbackground') or '#ffffff',
            'selection': accent['background'],
            'selection_text': accent['foreground'],
            'label_font': style.lookup('TLabel', 'font') or 'TkDefaultFont',
            'source': 'installed tgc_cfs_widgets.action_button',
        }
    finally:
        host.destroy()


def _role(widget, palette):
    explicit = getattr(widget, '_tgc_ui_role', None)
    if explicit in ('primary', 'normal'):
        return explicit
    original_style = str(_get(widget, 'style'))
    primary_style = palette['primary'].get('source_style')
    if primary_style and original_style == primary_style:
        return 'primary'
    background = str(_get(widget, 'background'))
    if (background and background == palette['primary']['background']
            and background != palette['normal']['background']):
        return 'primary'
    label = re.sub(r'\s+', ' ', str(_get(widget, 'text')).strip()).lower()
    if any(label.startswith(t) for t in PRIMARY_TEXT):
        return 'primary'
    return 'normal'


def _local_window(window):
    if getattr(window, '_tgc_local_alignment_window', False):
        return True
    title = str(window.title()).lower()
    return ('local' in title and 'align' in title
            and ('tee' in title or 'bunker' in title))


def _set_options(widget, options):
    supported = set(widget.keys())
    values = {k: v for k, v in options.items() if k in supported and v is not None and v != ''}
    if values:
        widget.configure(**values)


class StyleController:
    def __init__(self, root):
        self.root = root
        self.palette = cfs_palette(root)
        self.style = ttk.Style(root)
        self.seen = weakref.WeakKeyDictionary()
        self._defining = False
        self._define_styles()
        # App-private class tag: never replace 'all' bindings belonging to other UI.
        self.tag = 'TGCSharedPresentationV1'
        root.bind_class(self.tag, '<Map>', self._mapped, add='+')
        root.bind_class(self.tag, '<<ThemeChanged>>', self._theme_changed, add='+')
        # Toplevel bindings also receive events from descendants in Tk.
        root.bind('<Map>', self._mapped, add='+')
        root.bind_class('Toplevel', '<Map>', self._mapped, add='+')
        self.style_tree(root)

    def _define_styles(self):
        if self._defining:
            return
        self._defining = True
        try:
            s, p = self.style, self.palette
            for role in ('normal', 'primary'):
                data = p[role]
                name = PREFIX + ('.Primary.TButton' if role == 'primary' else '.TButton')
                s.configure(name, background=data['background'], foreground=data['foreground'],
                            font=data['font'], relief=data['relief'], borderwidth=data['borderwidth'],
                            padding=data.get('padding', (data['padx'], data['pady'])), anchor='center')
                s.map(name,
                      background=[('disabled', data['disabledbackground']),
                                  ('pressed', data['activebackground']), ('active', data['activebackground'])],
                      foreground=[('disabled', data['disabledforeground']),
                                  ('pressed', data['activeforeground']), ('active', data['activeforeground'])],
                      relief=[('pressed', 'sunken'), ('!pressed', data['relief'])])
            for role in ('normal', 'primary'):
                source = PREFIX + ('.Primary.TButton' if role == 'primary' else '.TButton')
                target = PREFIX + ('.Primary.TMenubutton' if role == 'primary' else '.TMenubutton')
                s.configure(target, **s.configure(source))
                s.map(target, **s.map(source))
            for suffix in ('TFrame', 'TLabelframe', 'TLabelframe.Label', 'TLabel',
                           'TCheckbutton', 'TRadiobutton', 'TSizegrip'):
                s.configure(PREFIX + '.' + suffix, background=p['panel'], foreground=p['text'])
            for suffix in ('TEntry', 'TCombobox', 'TSpinbox'):
                name = PREFIX + '.' + suffix
                s.configure(name, fieldbackground=p['field'], foreground=p['text'], padding=3,
                            selectbackground=p['selection'], selectforeground=p['selection_text'])
                s.map(name, fieldbackground=[('disabled', p['panel']), ('readonly', p['field'])],
                      foreground=[('disabled', p['normal']['disabledforeground'])])
            for suffix in ('TCheckbutton', 'TRadiobutton'):
                s.map(PREFIX + '.' + suffix,
                      foreground=[('disabled', p['normal']['disabledforeground'])],
                      background=[('active', p['panel'])])
            s.configure(PREFIX + '.TNotebook', background=p['panel'], tabmargins=(4, 6, 4, 0))
            s.configure(PREFIX + '.TNotebook.Tab', padding=(18, 7), background=p['normal']['background'],
                        foreground=p['normal']['foreground'])
            s.map(PREFIX + '.TNotebook.Tab',
                  background=[('selected', p['selection']), ('active', p['normal']['activebackground'])],
                  foreground=[('selected', p['selection_text']), ('disabled', p['normal']['disabledforeground'])])
            s.configure(PREFIX + '.Treeview', background=p['field'], fieldbackground=p['field'],
                        foreground=p['text'], borderwidth=1, relief='sunken')
            s.map(PREFIX + '.Treeview', background=[('selected', p['selection'])],
                  foreground=[('selected', p['selection_text'])])
            s.configure(PREFIX + '.Treeview.Heading', background=p['normal']['background'],
                        foreground=p['normal']['foreground'], padding=(6, 5), relief='raised')
            for axis in ('Horizontal', 'Vertical'):
                s.configure(PREFIX + '.' + axis + '.TProgressbar', background=p['selection'],
                            troughcolor=p['panel'])
                s.configure(PREFIX + '.' + axis + '.TScrollbar', background=p['normal']['background'],
                            troughcolor=p['panel'])
            # Combobox pop-down list is a Tcl-created widget, not a Python object.
            for name, value in [('background', p['field']), ('foreground', p['text']),
                                ('selectBackground', p['selection']), ('selectForeground', p['selection_text'])]:
                self.root.option_add('*TCombobox*Listbox.' + name, value, 60)
        finally:
            self._defining = False

    def _theme_changed(self, event):
        if event.widget is self.root and not self._defining:
            self._define_styles()

    def _mapped(self, event):
        widget = event.widget
        if not isinstance(widget, tk.Misc):
            return
        try:
            self.style_tree(widget)
            top = widget.winfo_toplevel()
            if isinstance(top, tk.Toplevel) and _local_window(top):
                make_local_resizable(top, self)
        except tk.TclError:
            # A queued Map can arrive after a dialog has been closed.
            return

    def _tag(self, widget):
        # Root and each Toplevel get a Map listener for future descendants.
        if isinstance(widget, tk.Toplevel):
            tags = widget.bindtags()
            if self.tag not in tags:
                widget.bindtags(tags + (self.tag,))
            if not getattr(widget, '_tgc_style_bound', False):
                widget.bind('<Map>', self._mapped, add='+')
                widget._tgc_style_bound = True

    def style_tree(self, widget):
        self._tag(widget)
        if widget not in self.seen:
            self._style_widget(widget)
            self.seen[widget] = True
        for child in widget.winfo_children():
            self.style_tree(child)

    def _style_widget(self, widget):
        p = self.palette
        cls = widget.winfo_class()
        if getattr(widget, '_tgc_keep_style', False):
            return
        if getattr(widget, '_tgc_field_display', False):
            _set_options(widget, {'background': p['field'], 'foreground': p['text'],
                                  'relief': 'sunken', 'borderwidth': 1, 'highlightthickness': 1,
                                  'highlightbackground': '#8796a5', 'padx': 6, 'pady': 4, 'anchor': 'w'})
            return
        # Protect semantic scorecard fields of ALL widget classes, not only Labels.
        ancestor = getattr(widget, 'master', None)
        while isinstance(ancestor, tk.Misc):
            if getattr(ancestor, '_tgc_keep_child_colors', False):
                return
            ancestor = getattr(ancestor, 'master', None)
        if cls in ('Button', 'TButton', 'Menubutton', 'TMenubutton'):
            role = _role(widget, p)
            widget._tgc_ui_role = role
            data = p[role]
            if cls in ('TButton', 'TMenubutton'):
                widget.configure(style=PREFIX + ('.Primary.' if role == 'primary' else '.') + cls)
            else:
                _set_options(widget, {k: v for k, v in data.items()
                                      if k not in ('source_style', 'padding', 'disabledbackground')})
            return
        if cls in ('Tk', 'Toplevel', 'Frame', 'Labelframe', 'LabelFrame', 'Panedwindow', 'PanedWindow'):
            _set_options(widget, {'background': p['panel']})
            if cls.lower() == 'labelframe':
                _set_options(widget, {'foreground': p['text']})
            return
        if cls in ('Label', 'Checkbutton', 'Radiobutton'):
            bg = _get(widget, 'background')
            fg = _get(widget, 'foreground')
            # Blank labels with colored backgrounds are legend/swatch widgets.
            if cls == 'Label':
                if not str(_get(widget, 'text')).strip() and str(_get(widget, 'relief')) == 'solid':
                    return  # Preserve white/grey legend swatches too.
                ancestor = widget.master
                while isinstance(ancestor, tk.Misc):
                    if getattr(ancestor, '_tgc_keep_child_colors', False):
                        return
                    ancestor = getattr(ancestor, 'master', None)
                if not _neutral(widget, bg):
                    return
            options = {'background': p['panel'], 'activebackground': p['panel'],
                       'selectcolor': p['field'], 'disabledforeground': p['normal']['disabledforeground']}
            if _neutral(widget, fg):
                options.update(foreground=p['text'], activeforeground=p['text'])
            _set_options(widget, options)
            return
        if cls in ('Entry', 'Spinbox', 'Listbox', 'Text'):
            _set_options(widget, {
                'background': p['field'], 'foreground': p['text'], 'insertbackground': p['text'],
                'selectbackground': p['selection'], 'selectforeground': p['selection_text'],
                'disabledbackground': p['panel'], 'disabledforeground': p['normal']['disabledforeground'],
                'readonlybackground': p['field'],
            })
            return
        if cls in ('Scrollbar', 'Menu'):
            _set_options(widget, {'background': p['normal']['background'], 'foreground': p['text'],
                                  'activebackground': p['normal']['activebackground'],
                                  'activeforeground': p['normal']['activeforeground'],
                                  'troughcolor': p['panel'], 'disabledforeground': p['normal']['disabledforeground']})
            return
        if cls == 'Scale':
            _set_options(widget, {'background': p['panel'], 'foreground': p['text'],
                                  'activebackground': p['normal']['activebackground']})
            return
        if cls in ('TFrame', 'TLabelframe', 'TLabel', 'TCheckbutton', 'TRadiobutton', 'TEntry',
                   'TCombobox', 'TSpinbox', 'TNotebook', 'TSizegrip'):
            if cls == 'TLabel':
                # Keep existing warning/error styles and explicit semantic colors.
                fg = _get(widget, 'foreground')
                old = str(_get(widget, 'style'))
                inherited = self.style.lookup(old or cls, 'foreground')
                bg = _get(widget, 'background')
                inherited_bg = self.style.lookup(old or cls, 'background')
                if ((bg and not _neutral(widget, bg)) or
                        (old and inherited_bg and not _neutral(widget, inherited_bg))):
                    return
                if (fg and not _neutral(widget, fg)) or (old and inherited and not _neutral(widget, inherited)):
                    return
                if fg:
                    widget.configure(foreground=p['text'])
            widget.configure(style=PREFIX + '.' + cls)
            return
        if cls == 'Treeview':
            # Retain report sizing/fonts: only color/heading presentation is shared.
            old = str(_get(widget, 'style')) or 'Treeview'
            name = PREFIX + '.' + re.sub(r'[^a-zA-Z0-9]', '', old) + '.Treeview'
            options = {key: self.style.lookup(old, key) for key in ('font', 'rowheight')}
            self.style.configure(name, **{k: v for k, v in options.items() if v != ''},
                                 background=p['field'], fieldbackground=p['field'], foreground=p['text'])
            self.style.map(name, background=[('selected', p['selection'])], foreground=[('selected', p['selection_text'])])
            self.style.configure(name + '.Heading', background=p['normal']['background'],
                                 foreground=p['normal']['foreground'], padding=(6, 5))
            widget.configure(style=name)
            return
        if cls in ('TProgressbar', 'TScrollbar'):
            axis = str(_get(widget, 'orient', 'horizontal')).capitalize()
            widget.configure(style=PREFIX + '.' + axis + '.' + cls)
        # Canvas content, OSM colors, photos, drawing geometry and bindings untouched.


def install(root):
    """Install once per Tk interpreter; safe for main GUI and standalone dialogs."""
    master = root._root()
    existing = getattr(master, '_tgc_shared_ui', None)
    if existing is None:
        existing = StyleController(master)
        master._tgc_shared_ui = existing
    existing.style_tree(root)
    return existing


def _work_area(window):
    from tgc_window_layout import _work_area as work_area
    return work_area(window, getattr(window, 'master', None))


def _grow_to_window(widget, window):
    """Enable expansion of an existing canvas/table chain, not fixed sidebars."""
    current = widget
    while current is not window and isinstance(current.master, tk.Misc):
        parent = current.master
        manager = current.winfo_manager()
        if manager == 'grid':
            opts = current.grid_info()
            current.grid_configure(sticky='nsew')
            # Do not assign weights to other columns containing fixed controls.
            parent.grid_rowconfigure(int(opts['row']), weight=1)
            parent.grid_columnconfigure(int(opts['column']), weight=1)
        elif manager == 'pack':
            current.pack_configure(fill='both', expand=True)
        elif manager == 'place':
            # Absolute-positioned drawing widgets may need their own renderer;
            # leave their placement alone rather than move overlay coordinates.
            break
        elif manager in ('panedwindow', 'ttk::panedwindow'):
            # Parent Panedwindow already controls its children; grow that parent.
            pass
        else:
            break
        current = parent


class WindowSizer:
    def __init__(self, window, controller):
        self.window = window
        self.controller = controller
        self.restore_geometry = None
        self.fallback_maximized = False
        self.drag_start = None
        self.pending = None
        left, top, right, bottom = _work_area(window)
        ww, hh = max(1, right-left), max(1, bottom-top)
        # A normal resizable toplevel restores the Windows maximize button.
        # Preserve any existing modal grab and WM_DELETE_WINDOW callback.
        window.transient('')
        if window.tk.call('tk', 'windowingsystem') == 'win32':
            window.attributes('-toolwindow', False)
        window.resizable(True, True)
        window.maxsize(32767, 32767)
        window.minsize(min(820, int(ww*.9)), min(560, int(hh*.9)))
        window.update_idletasks()
        width = min(max(window.winfo_width(), min(1100, int(ww*.9))), int(ww*.95))
        height = min(max(window.winfo_height(), min(720, int(hh*.85))), int(hh*.92))
        window.geometry(f'{width}x{height}+{left+(ww-width)//2}+{top+max(0,(hh-height)//3)}')
        self._controls()
        window.bind('<F11>', self.toggle, add='+')
        window.bind('<Control-Shift-M>', self.toggle, add='+')
        window.bind('<Configure>', self._configured, add='+')
        window.bind('<Destroy>', self._destroyed, add='+')
        self.pending = None
        self._expand_content()

    def _controls(self):
        window = self.window
        children = [w for w in window.winfo_children() if w.winfo_manager() in ('pack', 'grid')]
        managers = {w.winfo_manager() for w in children}
        self.bar = ttk.Frame(window, padding=(6, 3))
        if managers == {'grid'}:
            cols, rows = window.grid_size()
            self.bar.grid(row=rows, column=0, columnspan=max(1, cols), sticky='ew')
            window.grid_rowconfigure(rows, weight=0)
        elif not managers or managers == {'pack'}:
            args = {'side': 'bottom', 'fill': 'x'}
            if children:
                args['before'] = children[0]
            self.bar.pack(**args)
        else:
            # Rare absolute-positioned layout: compact controls at lower right.
            self.bar.place(relx=1, rely=1, anchor='se')
        self.label = ttk.Label(self.bar, text='F11: Maximize / Restore  |  Drag a window edge or the resize grip')
        self.label.pack(side='left', padx=(0, 12))
        self.button = ttk.Button(self.bar, text='Maximize', command=self.toggle)
        self.button._tgc_ui_role = 'primary'
        self.button.pack(side='right', padx=(6, 0))
        self.grip = ttk.Sizegrip(self.bar)
        self.grip.pack(side='right', padx=3)
        self.grip.bind('<ButtonPress-1>', self._resize_begin)
        self.grip.bind('<B1-Motion>', self._resize_drag)
        self.grip.bind('<ButtonRelease-1>', self._resize_end)
        self.controller.style_tree(self.bar)

    def _expand_content(self):
        def descendants(w):
            for child in w.winfo_children():
                yield child
                yield from descendants(child)
        candidates = [w for w in descendants(self.window)
                      if w.winfo_class() in ('Canvas', 'Treeview') and w is not self.grip]
        # Prefer the preview drawing surface, then the table if there is no canvas.
        canvases = [w for w in candidates if w.winfo_class() == 'Canvas']
        for w in (canvases or candidates):
            _grow_to_window(w, self.window)

    def _is_maximized(self):
        if self.fallback_maximized or self.window.state() == 'zoomed':
            return True
        try:
            return bool(self.window.attributes('-zoomed'))
        except tk.TclError:
            return False

    def toggle(self, event=None):
        window = self.window
        if self._is_maximized():
            try:
                window.state('normal')
            except tk.TclError:
                pass
            try:
                window.attributes('-zoomed', False)
            except tk.TclError:
                pass
            self.fallback_maximized = False
            if self.restore_geometry:
                window.geometry(self.restore_geometry)
        else:
            self.restore_geometry = window.geometry()
            try:
                window.state('zoomed')
            except tk.TclError:
                # Geometry fallback works under Xvfb/no window manager too.
                left, top, right, bottom = _work_area(window)
                window.geometry(f'{right-left}x{bottom-top}+{left}+{top}')
                self.fallback_maximized = True
        self.button.configure(text='Restore' if self._is_maximized() else 'Maximize')
        return 'break'

    def _configured(self, event):
        if event.widget is not self.window:
            return
        if self.pending is not None:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after_idle(self._refresh_label)

    def _refresh_label(self):
        self.pending = None
        if self.window.winfo_exists():
            self.button.configure(text='Restore' if self._is_maximized() else 'Maximize')

    def _resize_begin(self, event):
        if self._is_maximized():
            self.toggle()
            self.window.update_idletasks()
        self.drag_start = (event.x_root, event.y_root, self.window.winfo_width(), self.window.winfo_height())
        return 'break'

    def _resize_drag(self, event):
        if self.drag_start is None:
            return 'break'
        x, y, w, h = self.drag_start
        minw, minh = self.window.minsize()
        self.window.geometry(f'{max(minw,w+event.x_root-x)}x{max(minh,h+event.y_root-y)}')
        return 'break'

    def _resize_end(self, event):
        self.drag_start = None
        return 'break'

    def _destroyed(self, event):
        if event.widget is self.window and self.pending is not None:
            try:
                self.window.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None


def make_local_resizable(window, controller=None):
    """Public hook used by the CFS caller, plus title-based mapping fallback."""
    existing = getattr(window, '_tgc_window_sizer', None)
    if existing is not None:
        return existing
    # Set a sentinel before layout updates to avoid a re-entrant Map event.
    window._tgc_window_sizer = False
    try:
        controller = controller or install(window)
        result = WindowSizer(window, controller)
        window._tgc_window_sizer = result
        return result
    except Exception:
        delattr(window, '_tgc_window_sizer')
        raise


def open_local_alignment(viewer, original_open):
    """Enhance the installed local dialog without copying its alignment code.

    Handles builders that return a window, return a controller, return None,
    or block in wait_window. Only newly-created Toplevels in this viewer tree
    are considered; unrelated windows and Tk's native dialogs are not resized.
    """
    controller = install(viewer.window)
    root = viewer.window._root()
    def windows(w):
        result = []
        for child in w.winfo_children():
            if isinstance(child, tk.Toplevel):
                result.append(child)
            result.extend(windows(child))
        return result
    before = set(windows(root))
    def apply_new():
        for top in windows(root):
            if top not in before:
                title = str(top.title()).lower()
                if _local_window(top) or ('local' in title and 'align' in title):
                    top._tgc_local_alignment_window = True
                    controller.style_tree(top)
                    make_local_resizable(top, controller)
    # Idle runs after construction, even if original_open enters wait_window.
    job = root.after_idle(apply_new)
    try:
        result = original_open(viewer)
        apply_new()
        return result
    finally:
        try:
            root.after_cancel(job)
        except tk.TclError:
            pass


def wrap_local_alignment(original_open):
    """Keep the original CFS call form and the installed opener's metadata."""
    from functools import wraps
    @wraps(original_open)
    def wrapped(viewer):
        return open_local_alignment(viewer, original_open)
    return wrapped


def verify():
    """Hidden-window smoke check using the ACTUAL installed CFS helper.

    Used by the Windows build's staged EXE check. No course files, network,
    alignment workers or conversion jobs are opened or modified.
    """
    root = tk.Tk()
    root.withdraw()
    try:
        controller = install(root)
        p = controller.palette
        called = []
        button = tk.Button(root, text='Browse', command=lambda: called.append(1))
        apply = ttk.Button(root, text='Apply alignment', state='disabled')
        entry = ttk.Entry(root, state='readonly')
        controller.style_tree(root)
        assert str(button.cget('background')) == p['normal']['background']
        button.invoke()
        assert called == [1]
        assert apply.instate(['disabled'])
        assert entry.instate(['readonly'])
        assert controller.style.lookup(apply.cget('style'), 'background') == p['primary']['background']
        win = tk.Toplevel(root)
        win.withdraw()
        win.title('Local Tee/Bunker Alignment — UI self-check')
        win.transient(root)
        win.resizable(False, False)
        content = ttk.Frame(win); content.pack()
        canvas = tk.Canvas(content, width=320, height=180); canvas.pack()
        callback = win.protocol('WM_DELETE_WINDOW')
        sizer = make_local_resizable(win, controller)
        assert tuple(map(int, win.resizable())) == (1, 1)
        assert not str(win.transient())
        assert str(canvas.pack_info()['fill']) == 'both'
        assert win.protocol('WM_DELETE_WINDOW') == callback
        win.destroy()
    finally:
        root.destroy()
    print('BETA 7 SHARED CFS UI CHECK PASSED: installed button palette, callbacks, states, local resize controls.')


if __name__ == '__main__':
    verify()
