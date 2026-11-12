"""Display-only local-relief shading for the default CFS Hillshade 1 option.

The neutral gray background and bounded local lighting emphasize bunker
depressions and small landforms without stretching every plot to black/white.
All filter distances are in metres. No elevation or alignment data is changed.
"""
import math

import numpy as np
from scipy import ndimage


HILLSHADE2_VERSION = "TGC_HILLSHADE2_PATCH_V1"
NEUTRAL_GRAY = 132


def _remove_regional_plane(height, valid):
    """Subtract a sampled least-squares plane from our private float32 copy."""
    rows, cols = height.shape
    row_ids = np.unique(np.linspace(0, rows - 1, min(rows, 96)).astype(np.intp))
    col_ids = np.unique(np.linspace(0, cols - 1, min(cols, 96)).astype(np.intp))
    sample = height[np.ix_(row_ids, col_ids)]
    good = valid[np.ix_(row_ids, col_ids)]
    if not np.any(good):
        return
    x = np.linspace(-1.0, 1.0, cols, dtype=np.float32) if cols > 1 else np.zeros(1, np.float32)
    y = np.linspace(-1.0, 1.0, rows, dtype=np.float32) if rows > 1 else np.zeros(1, np.float32)
    xx, yy = np.meshgrid(x[col_ids], y[row_ids])
    design = np.column_stack((xx[good], yy[good], np.ones(int(good.sum()))))
    coefficients, _, _, _ = np.linalg.lstsq(design, sample[good], rcond=None)
    height -= np.float32(coefficients[2])
    height -= (x * np.float32(coefficients[0]))[None, :]
    height -= (y * np.float32(coefficients[1]))[:, None]


def _wide_smooth(height, sigma_pixels):
    """Approximate a broad Gaussian in three constant-cost box-filter passes.

    The repeated box variance is matched to sigma rather than using a kernel
    whose running time grows with source resolution or the requested radius.
    """
    sigma = max(float(sigma_pixels), 0.0)
    if sigma < 0.75:
        return ndimage.gaussian_filter(height, sigma=sigma, mode="nearest")
    ideal = math.sqrt(4.0 * sigma * sigma + 1.0)
    lower = max(1, int(math.floor(ideal)))
    if lower % 2 == 0:
        lower -= 1
    upper = lower + 2
    # Number of lower-width passes in a 3-box Gaussian approximation.
    low_count = int(round((12.0 * sigma * sigma - 3.0 * lower * lower -
                           12.0 * lower - 9.0) / (-4.0 * lower - 4.0)))
    low_count = max(0, min(3, low_count))
    widths = [lower] * low_count + [upper] * (3 - low_count)
    result = np.empty_like(height)
    scratch = np.empty_like(height)
    ndimage.uniform_filter(height, size=widths[0], output=result, mode="nearest")
    ndimage.uniform_filter(result, size=widths[1], output=scratch, mode="nearest")
    ndimage.uniform_filter(scratch, size=widths[2], output=result, mode="nearest")
    return result


def terrain_relief2(heightmap, resolution):
    """Return display-ready uint8 RGB, preserving native shape and orientation.

    ``resolution`` is metres per pixel. Input may be a 2D heightmap or a 2D
    heightmap with a trailing singleton channel. NaN/Inf cells are filled only
    in private working data and remain neutral gray in the returned image.
    Empty, flat, all-NoData and one-cell-wide maps are supported. Invalid
    resolution or non-2D numeric input raises ValueError.
    """
    try:
        spacing = float(resolution)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Hillshade 1 requires a positive finite terrain resolution") from exc
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("Hillshade 1 requires a positive finite terrain resolution")

    source = np.asarray(heightmap)
    if source.ndim == 3 and source.shape[-1] == 1:
        source = source[:, :, 0]
    if source.ndim != 2 or source.dtype.kind not in "biuf":
        raise ValueError("Hillshade 1 requires a two-dimensional numeric heightmap")
    if source.size == 0:
        return np.empty(source.shape + (3,), dtype=np.uint8)

    valid = np.isfinite(source)
    if not np.any(valid):
        return np.full(source.shape + (3,), NEUTRAL_GRAY, dtype=np.uint8)
    first_valid = float(source.flat[int(np.argmax(valid))])
    height = np.empty(source.shape, dtype=np.float32)
    # Subtract before float32 storage so float64 absolute elevations retain
    # their small local differences. The original array is never written.
    with np.errstate(invalid="ignore", over="ignore"):
        np.subtract(source, first_valid, out=height, casting="unsafe")
    valid &= np.isfinite(height)
    if not np.any(valid):
        return np.full(source.shape + (3,), NEUTRAL_GRAY, dtype=np.uint8)
    _remove_regional_plane(height, valid)

    if not np.all(valid):
        nearest = ndimage.distance_transform_edt(~valid, return_distances=False,
                                                return_indices=True)
        missing = ~valid
        height[missing] = height[tuple(nearest[:, missing])]
        del nearest, missing

    # Suppress sub-metre sampling noise while retaining edges of small bunkers.
    sigma = max(0.45, 0.70 / spacing)
    smooth = ndimage.gaussian_filter(height, sigma=sigma, mode="nearest", truncate=3.0)
    del height

    local = _wide_smooth(smooth, 8.0 / spacing)
    np.subtract(smooth, local, out=local)
    broad = _wide_smooth(smooth, 24.0 / spacing)
    np.subtract(smooth, broad, out=broad)

    # Fixed metre-based tone curves avoid amplifying tiny noise on flat maps.
    gray = local / np.float32(0.85)
    np.tanh(gray, out=gray)
    gray *= np.float32(14.0)
    gray += np.float32(NEUTRAL_GRAY)
    broad /= np.float32(2.5)
    np.tanh(broad, out=broad)
    broad *= np.float32(6.0)
    gray += broad
    del broad

    # Keep some wider landform lighting, with emphasis on the local feature.
    local *= np.float32(0.80)
    smooth *= np.float32(0.20)
    local += smooth
    del smooth
    derivative = np.array([-0.5, 0.0, 0.5], dtype=np.float32) / np.float32(spacing)
    light = ndimage.correlate1d(local, derivative, axis=1, mode="nearest")
    north = ndimage.correlate1d(local, derivative, axis=0, mode="nearest")
    del local
    light -= north
    del north
    # NW illumination in world coordinates; the viewer performs its own
    # single north-up image flip after this function returns.
    light *= np.float32(math.sqrt(0.5) / 0.18)
    np.tanh(light, out=light)
    light *= np.float32(30.0)
    gray += light
    del light
    np.nan_to_num(gray, copy=False, nan=NEUTRAL_GRAY, posinf=182.0, neginf=82.0)
    np.clip(gray, 0.0, 255.0, out=gray)
    gray[~valid] = NEUTRAL_GRAY
    gray = np.rint(gray).astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)
