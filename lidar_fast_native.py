import ctypes
import os
from pathlib import Path
import sys

import numpy as np

_LIB = None
_LOAD_ATTEMPTED = False


def _candidate_paths():
    names = ["tgc_lidar_fast_native.dll"] if os.name == "nt" else ["tgc_lidar_fast_native.so", "libtgc_lidar_fast_native.so"]
    roots = []
    try:
        roots.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path.cwd())
    seen = set()
    for root in roots:
        for name in names:
            p = (root / name).resolve()
            if str(p) not in seen:
                seen.add(str(p))
                yield p


def _load_native():
    global _LIB, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _LIB
    _LOAD_ATTEMPTED = True
    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            lib = ctypes.CDLL(str(path))
            f = lib.tgc_lidar_accumulate
            f.argtypes = [
                ctypes.POINTER(ctypes.c_int32),
                ctypes.POINTER(ctypes.c_int32),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.c_size_t,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
            ]
            f.restype = ctypes.c_int
            _LIB = lib
            return _LIB
        except Exception:
            continue
    return None


def native_available():
    return _load_native() is not None


def _python_exact(points, image_height, image_width, visualization_axis):
    elevation = np.full((image_height, image_width), np.nan, dtype=np.float32)
    visual = np.full((image_height, image_width), np.nan, dtype=np.float32)
    for i in points:
        r = int(i[0]); c = int(i[1])
        if r < 0 or c < 0 or r >= image_height or c >= image_width:
            continue
        value = visual[r, c]
        if np.isnan(value):
            value = i[visualization_axis]
        else:
            value = (i[visualization_axis] - value) * 0.3 + value
        visual[r, c] = value

        e = elevation[r, c]
        if np.isnan(e):
            e = i[2]
        else:
            alpha = 0.4 if i[2] < e else 0.1
            e = (i[2] - e) * alpha + e
        elevation[r, c] = e
    return elevation[:, :, None], visual[:, :, None]


def accumulate_height_and_visual(points, image_height, image_width, visualization_axis, printf=print):
    points = np.asarray(points)
    if points.size == 0:
        return (
            np.full((image_height, image_width, 1), np.nan, np.float32),
            np.full((image_height, image_width, 1), np.nan, np.float32),
        )

    lib = _load_native()
    if lib is None:
        printf("LiDAR Fast native rasterizer DLL not found; using exact Python fallback.")
        return _python_exact(points, image_height, image_width, visualization_axis)

    rows = np.ascontiguousarray(points[:, 0], dtype=np.int32)
    cols = np.ascontiguousarray(points[:, 1], dtype=np.int32)
    z = np.ascontiguousarray(points[:, 2], dtype=np.float64)
    vis = np.ascontiguousarray(points[:, visualization_axis], dtype=np.float64)

    elevation = np.full((image_height, image_width), np.nan, dtype=np.float32)
    visual = np.full((image_height, image_width), np.nan, dtype=np.float32)

    func = lib.tgc_lidar_accumulate
    rc = func(
        rows.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        cols.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        z.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        vis.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_size_t(len(points)),
        ctypes.c_int(image_height),
        ctypes.c_int(image_width),
        elevation.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        visual.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
    )
    if rc != 0:
        printf("LiDAR Fast native rasterizer returned error; using exact Python fallback.")
        return _python_exact(points, image_height, image_width, visualization_axis)

    return elevation[:, :, None], visual[:, :, None]
