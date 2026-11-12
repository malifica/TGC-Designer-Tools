"""Choose terrain stamp positions without resizing or changing a heightmap.

Positions are source-grid [row, column, elevation], so callers continue to use
the original source resolution for world coordinates. A 1 m -> 2 m lattice
uses approximately one quarter of the interior samples. Final row/column
endpoints and exact finite pixels bordering internal NoData are also retained;
these deliberately make the final count larger near edges and thin islands.
"""
from __future__ import annotations

import math

import numpy as np


TERRAIN_SAMPLING_VERSION = "TGC_BETA8_5_TERRAIN_SAMPLING_V1"
ALLOWED_BRUSH_SCALES = (1.0, 2.0, 3.0, 4.0, 6.0)
MAX_STAMP_SPACING = 6.0


def _positive_number(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("%s must be a finite positive number." % name)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("%s must be a finite positive number." % name)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("%s must be a finite positive number." % name)
    return number


def resolve_stamp_spacing(value, source_scale):
    """Resolve None/blank/'Source', otherwise require source <= spacing <= 6 m."""
    source = _positive_number(source_scale, "Source terrain resolution")
    if source > MAX_STAMP_SPACING:
        raise ValueError("Source terrain resolution exceeds the supported 6 m maximum stamp spacing.")
    automatic = value is None or (isinstance(value, str) and value.strip().casefold() in ("", "source"))
    spacing = source if automatic else _positive_number(value, "Terrain stamp spacing")
    if spacing < source:
        raise ValueError("Terrain stamp spacing must be at least the source terrain resolution (%g m)." % source)
    if spacing > MAX_STAMP_SPACING:
        raise ValueError("Terrain stamp spacing must be no greater than 6 m.")
    return spacing


def resolve_brush_scale(value, source_scale, stamp_spacing):
    """Keep a valid adequate brush, or choose the first adequate supported brush."""
    source = _positive_number(source_scale, "Source terrain resolution")
    spacing = resolve_stamp_spacing(stamp_spacing, source)
    minimum = max(source, spacing)
    try:
        requested = _positive_number(value, "Terrain brush scale")
    except ValueError:
        requested = None
    if requested in ALLOWED_BRUSH_SCALES and requested >= minimum:
        return requested
    for scale in ALLOWED_BRUSH_SCALES:
        if scale >= minimum:
            return scale
    raise ValueError("No supported terrain brush can cover this source resolution and stamp spacing.")


def _integer_ratio(ratio):
    if not math.isfinite(ratio):
        return None
    nearest = int(round(ratio))
    # Account only for floating-point representation error (for example 0.3 /
    # 0.1). A deliberately fractional spacing remains fractional.
    if nearest >= 1 and abs(ratio - nearest) <= 4.0 * np.finfo(np.float64).eps * max(1.0, abs(ratio)):
        return nearest
    return None


def _axis(length, ratio, integer_ratio):
    if length == 0:
        return np.empty(0, dtype=np.float64)
    if length == 1:
        return np.zeros(1, dtype=np.float64)
    last = length - 1
    if not math.isfinite(ratio) or ratio >= last:
        return np.array((0.0, float(last)), dtype=np.float64)
    if integer_ratio is not None:
        values = np.arange(0, length, integer_ratio, dtype=np.intp).astype(np.float64)
    else:
        count = int(math.floor(last / ratio)) + 1
        values = np.arange(count, dtype=np.float64) * ratio
        rounded = np.rint(values)
        tolerance = 4.0 * np.finfo(np.float64).eps * np.maximum(1.0, np.abs(values))
        snap = np.abs(values - rounded) <= tolerance
        values[snap] = rounded[snap]
        values = values[values <= last]
    if values[-1] != last:
        values = np.append(values, float(last))
    return values


def _valid_mask(source, original):
    valid = np.isfinite(source)
    if np.ma.isMaskedArray(original):
        mask = np.ma.getmaskarray(original)
        if mask.ndim == 3 and mask.shape[-1] == 1:
            mask = mask[:, :, 0]
        valid &= ~mask
    return valid


def _edge_mask(valid):
    """Finite pixels with an invalid neighbour inside the actual array."""
    rows, columns = valid.shape
    invalid = ~valid
    edges = np.zeros(valid.shape, dtype=bool)
    for row_shift in (-1, 0, 1):
        for column_shift in (-1, 0, 1):
            if row_shift == 0 and column_shift == 0:
                continue
            destination_rows = slice(max(0, -row_shift), min(rows, rows - row_shift))
            destination_columns = slice(max(0, -column_shift), min(columns, columns - column_shift))
            source_rows = slice(max(0, row_shift), min(rows, rows + row_shift))
            source_columns = slice(max(0, column_shift), min(columns, columns + column_shift))
            edges[destination_rows, destination_columns] |= invalid[source_rows, source_columns]
    edges &= valid
    return edges


def _bilinear_lattice(source, valid, row_axis, column_axis):
    rows, columns = source.shape
    lower_rows = np.floor(row_axis).astype(np.intp)
    lower_columns = np.floor(column_axis).astype(np.intp)
    upper_rows = np.minimum(lower_rows + 1, rows - 1)
    upper_columns = np.minimum(lower_columns + 1, columns - 1)
    row_fraction = row_axis - lower_rows
    column_fraction = column_axis - lower_columns
    output = np.zeros((len(row_axis), len(column_axis)), dtype=np.float64)
    usable = np.ones(output.shape, dtype=bool)
    for row_indices, row_weight in ((lower_rows, 1.0 - row_fraction), (upper_rows, row_fraction)):
        for column_indices, column_weight in ((lower_columns, 1.0 - column_fraction), (upper_columns, column_fraction)):
            weight = row_weight[:, None] * column_weight[None, :]
            positive = weight > 0.0
            corner_valid = valid[np.ix_(row_indices, column_indices)]
            usable &= ~positive | corner_valid
            contribution = np.zeros(output.shape, dtype=np.float64)
            # A zero-weight NaN/Inf corner never participates in arithmetic or
            # invalidates an exact sample on a native grid line or endpoint.
            with np.errstate(invalid="ignore", over="ignore"):
                np.multiply(source[np.ix_(row_indices, column_indices)], weight,
                            out=contribution, where=positive & corner_valid)
                output += contribution
    usable &= np.isfinite(output)
    row_positions, column_positions = np.nonzero(usable)
    return np.column_stack((row_axis[row_positions], column_axis[column_positions], output[usable]))


def sample_terrain_stamps(heightmap, source_scale, stamp_spacing=None):
    """Return (Nx3 float64 source-grid stamps, JSON-serializable report).

    Native/integer-ratio samples use original elevations exactly. Fractional
    lattice positions use strict bilinear interpolation: every corner with a
    positive weight must be finite/unmasked. No extrapolation, resizing,
    smoothing, or writes to the input occur. Extra NoData-edge samples retain
    exact original elevations. The complete result is ordered by row, column.
    """
    source_resolution = _positive_number(source_scale, "Source terrain resolution")
    spacing = resolve_stamp_spacing(stamp_spacing, source_resolution)
    original = heightmap
    source = np.asarray(heightmap)
    if source.ndim == 3 and source.shape[-1] == 1:
        source = source[:, :, 0]
    if source.ndim != 2 or source.dtype.kind not in "biuf":
        raise ValueError("Terrain stamp sampling requires a numeric 2D heightmap or MxNx1 heightmap.")
    valid = _valid_mask(source, original)
    finite_count = int(np.count_nonzero(valid))
    ratio = spacing / source_resolution
    integer_ratio = _integer_ratio(ratio)
    mode = "native" if integer_ratio == 1 else ("direct" if integer_ratio is not None else "bilinear")
    row_axis = _axis(source.shape[0], ratio, integer_ratio)
    column_axis = _axis(source.shape[1], ratio, integer_ratio)
    candidate_count = int(len(row_axis) * len(column_axis))
    if not candidate_count:
        main = np.empty((0, 3), dtype=np.float64)
    elif integer_ratio is not None:
        row_indices = row_axis.astype(np.intp)
        column_indices = column_axis.astype(np.intp)
        lattice_valid = valid[np.ix_(row_indices, column_indices)]
        row_positions, column_positions = np.nonzero(lattice_valid)
        selected_rows = row_indices[row_positions]
        selected_columns = column_indices[column_positions]
        main = np.column_stack((selected_rows, selected_columns, source[selected_rows, selected_columns])).astype(np.float64, copy=False)
    else:
        main = _bilinear_lattice(source, valid, row_axis, column_axis)
    main_count = int(len(main))
    exact_main = ((main[:, 0] == np.floor(main[:, 0])) & (main[:, 1] == np.floor(main[:, 1])))
    exact_main_count = int(np.count_nonzero(exact_main))
    edge_count = 0
    stamps = main
    if mode != "native" and 0 < finite_count < source.size:
        edges = _edge_mask(valid)
        if exact_main_count:
            edges[main[exact_main, 0].astype(np.intp), main[exact_main, 1].astype(np.intp)] = False
        edge_rows, edge_columns = np.nonzero(edges)
        edge_count = int(len(edge_rows))
        if edge_count:
            extras = np.column_stack((edge_rows, edge_columns, source[edge_rows, edge_columns])).astype(np.float64, copy=False)
            combined = np.vstack((main, extras))
            stamps = combined[np.lexsort((combined[:, 1], combined[:, 0]))]
    report = {
        "version": TERRAIN_SAMPLING_VERSION,
        "source_scale": float(source_resolution),
        "stamp_spacing": float(spacing),
        "source_shape": [int(value) for value in source.shape],
        "source_finite_count": finite_count,
        "main_lattice_candidate_count": candidate_count,
        "main_lattice_count": main_count,
        "edge_retained_count": edge_count,
        "total_count": int(len(stamps)),
        "direct_sample_count": exact_main_count + edge_count,
        "interpolated_sample_count": main_count - exact_main_count,
        "row_axis_count": int(len(row_axis)),
        "column_axis_count": int(len(column_axis)),
        "mode": mode,
    }
    return stamps, report
