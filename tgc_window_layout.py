"""Screen-relative startup geometry only. No data, projection or theme changes."""


def _work_area(window, parent=None):
    """Return the owner's monitor work area on Windows, or a screen fallback."""
    import sys
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.DWORD),
                            ('rcMonitor', wintypes.RECT),
                            ('rcWork', wintypes.RECT),
                            ('dwFlags', wintypes.DWORD)]

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            monitor_from_window = user32.MonitorFromWindow
            monitor_from_window.argtypes = (wintypes.HWND, wintypes.DWORD)
            monitor_from_window.restype = wintypes.HANDLE
            get_monitor_info = user32.GetMonitorInfoW
            get_monitor_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(MONITORINFO))
            get_monitor_info.restype = wintypes.BOOL
            owner = parent if parent is not None else window
            monitor = monitor_from_window(owner.winfo_id(), 2)  # nearest monitor
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if monitor and get_monitor_info(monitor, ctypes.byref(info)):
                rect = info.rcWork
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass
    # Leave modest room for a taskbar on systems with no monitor work-area API.
    width = max(1, int(window.winfo_screenwidth()))
    height = max(1, int(window.winfo_screenheight()) - 40)
    return 0, 0, width, height


def large_geometry(work_area):
    """95% of available width and 92% of height; no fixed upper-size cap."""
    left, top, right, bottom = (int(v) for v in work_area)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError('Display work area must have positive dimensions')
    target_w = max(1, int(width * 0.95))
    target_h = max(1, int(height * 0.92))
    x = left + (width - target_w) // 2
    # Leave extra bottom margin for title bar/borders (geometry is client size).
    y = top + max(0, (height - target_h) // 3)
    return target_w, target_h, x, y


def open_large_window(window, parent=None, minimum=(820, 640)):
    """Apply an opening size once. Subsequent user resizing is never overridden."""
    width, height, x, y = large_geometry(_work_area(window, parent))
    window.resizable(True, True)
    # Explicit '+' before signed coordinates expresses absolute positions on
    # left/top monitors, instead of Tk's right/bottom-edge negative offsets.
    window.geometry(f'{width}x{height}+{x}+{y}')
    window.minsize(min(int(minimum[0]), width), min(int(minimum[1]), height))
    # Deliberately no wm maxsize, fullscreen, DPI/font scaling or resize handler.
    return width, height
