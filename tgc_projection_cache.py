"""Reuse unchanged pyproj operations throughout preview, masks and course import.

One bounded cache per thread; exact source/target objects and always_xy=True.
No coordinate results, origins, offsets or pixel rounding are cached. No grid,
CRS, network, datum or accuracy options are changed. Nothing is stored on a
GeoPointCloud or in heightmap.npy.
"""
from collections import OrderedDict
import threading
import pyproj

_STATE = threading.local()
_MAX_PAIRS = 32


def from_proj(source, target):
    """The same Transformer.from_proj(source, target, True), initialized once."""
    pairs = getattr(_STATE, 'pairs', None)
    if pairs is None:
        pairs = _STATE.pairs = OrderedDict()
    # Retain both objects in the entry: Python cannot recycle their ids while
    # the entry exists. Check identity as well; changing either CRS cannot reuse
    # the old operation. Thread-local storage also avoids cross-thread sharing.
    key = (id(source), id(target))
    hit = pairs.get(key)
    if hit is not None and hit[0] is source and hit[1] is target:
        pairs.move_to_end(key)
        return hit[2]
    transformer = pyproj.Transformer.from_proj(source, target, True)
    pairs[key] = (source, target, transformer)
    pairs.move_to_end(key)
    while len(pairs) > _MAX_PAIRS:
        pairs.popitem(last=False)
    return transformer


def clear_thread_cache():
    """Clear only this thread's transient operation cache (also useful in tests)."""
    _STATE.pairs = OrderedDict()
