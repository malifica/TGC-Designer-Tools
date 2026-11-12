"""Source inspection for the pre-processing heightmap-scale confirmation.

DEM inspection reads headers only. LiDAR inspection runs on metric, unquantized
coordinates before GeoPointCloud.pointsAsCV2 changes the point matrix. The LiDAR
coverage thresholds below are an application policy, not a survey accuracy or
USGS quality-level certification.
"""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path

import numpy as np


SOURCE_SCALE_VERSION = "TGC_BETA8_5_AUTO_SOURCE_SCALE_V1"
MAX_HEIGHTMAP_SCALE = 6.0
LIDAR_CANDIDATE_SCALES = (0.5, 1.0, 2.0, 4.0)
_LIDAR_BLOCK_M = 20.0
_LIDAR_FINE_M = 0.5
_LIDAR_SAMPLE_LIMIT = 200000
_LIDAR_CHUNK = 500000


def normalize_scale_request(value):
    """Return 'Auto' or a finite supported manual value; never silently clamp."""
    if value is None or (isinstance(value, str) and value.strip().casefold() in ("", "auto")):
        return "Auto"
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("Heightmap scale must be Auto or a number greater than zero.")
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Heightmap scale must be Auto or a number in metres.") from None
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Heightmap scale must be a finite number greater than zero.")
    if scale > MAX_HEIGHTMAP_SCALE:
        raise ValueError("Heightmap scale must be no greater than 6 m for the current terrain exporter.")
    return scale


def resolve_source_scale(request, assessment):
    """Resolve the popup choice against the inspected source without changing it."""
    requested = normalize_scale_request(request)
    scale = assessment.get("recommended_scale") if requested == "Auto" else requested
    scale = normalize_scale_request(scale)
    if scale == "Auto":
        raise ValueError("The source inspection did not establish a recommended heightmap scale.")
    minimum = float(assessment.get("minimum_scale", 0.0))
    if not math.isfinite(minimum) or minimum < 0:
        raise ValueError("The source inspection contains an invalid minimum scale.")
    if scale + max(1e-9, minimum * 1e-9) < minimum:
        raise ValueError(
            "This DEM supports a processing scale of at least %g m. "
            "Choose %g m or coarser; a smaller pixel would add interpolation, not source detail."
            % (minimum, minimum)
        )
    # Avoid a final floating-point difference between a displayed native value
    # and its exact metadata value without adjusting an actual manual choice.
    if scale < minimum:
        scale = minimum
    return float(scale)


def make_scale_decision(request, assessment):
    normalized = normalize_scale_request(request)
    return {
        "version": SOURCE_SCALE_VERSION,
        "mode": "auto" if normalized == "Auto" else "manual",
        "selected_scale": resolve_source_scale(normalized, assessment),
        "assessment": copy.deepcopy(assessment),
    }


def _pixel_spacing_m(dataset):
    """Physical X/Y pixel-vector lengths, before warping or resampling."""
    import pyproj

    crs = pyproj.CRS.from_user_input(dataset.crs).to_2d()
    transform = dataset.transform
    if crs.is_projected:
        axes = crs.axis_info
        if len(axes) < 2:
            raise ValueError("DEM projected coordinate system has no usable axis units.")
        factors = [float(axis.unit_conversion_factor) for axis in axes[:2]]
        if any(not math.isfinite(v) or v <= 0 for v in factors):
            raise ValueError("DEM has invalid horizontal unit conversion factors.")
        sx = math.hypot(transform.a * factors[0], transform.d * factors[1])
        sy = math.hypot(transform.b * factors[0], transform.e * factors[1])
        return float(sx), float(sy)
    if crs.is_geographic:
        geod = crs.get_geod()
        # Geographic CRSs can use angular units other than degrees (for
        # example grads); Geod.inv always expects degrees here.
        angular_factors = [float(axis.unit_conversion_factor) * 180.0 / math.pi
                           for axis in crs.axis_info[:2]]
        if len(angular_factors) < 2 or any(not math.isfinite(value) or value <= 0
                                         for value in angular_factors):
            raise ValueError("DEM has invalid geographic axis units.")
        fx, fy = angular_factors
        left, bottom, right, top = dataset.bounds
        measurements = []
        for x in (left, (left + right) / 2.0, right):
            for y in (bottom, (bottom + top) / 2.0, top):
                measurements.append((
                    abs(geod.inv(x * fx, y * fy, (x + transform.a) * fx, (y + transform.d) * fy)[2]),
                    abs(geod.inv(x * fx, y * fy, (x + transform.b) * fx, (y + transform.e) * fy)[2]),
                ))
        return tuple(float(max(pair[axis] for pair in measurements)) for axis in (0, 1))
    raise ValueError("DEM coordinate system must be projected or geographic.")


def inspect_dem_sources(paths, printf=print):
    """Read every selected DEM header and choose a deterministic common scale.

    All files retain the existing common-CRS requirement. Mixed tiles use the
    coarsest X/Y pixel sizes for the mosaic; the confirmed metric square grid
    uses the coarsest measured physical axis. This policy never depends on the
    order in which a file chooser returned the tile names.
    """
    import rasterio
    import pyproj

    if not paths:
        raise ValueError("No DEM files selected.")
    files = []
    reference_crs = None
    merge_x = merge_y = 0.0
    native_max = 0.0
    notes = []
    for path in paths:
        filename = os.fspath(path)
        with rasterio.open(filename) as dataset:
            if dataset.crs is None:
                raise ValueError("DEM has no CRS/georeferencing: " + filename)
            if dataset.count < 1 or dataset.width < 1 or dataset.height < 1:
                raise ValueError("DEM has no usable elevation grid: " + filename)
            if reference_crs is None:
                reference_crs = dataset.crs
            elif dataset.crs != reference_crs:
                raise ValueError("Selected DEM tiles must use the same coordinate system: " + filename)
            transform = dataset.transform
            tolerance = 1e-12 * max(1.0, abs(transform.a), abs(transform.e))
            if (abs(transform.b) > tolerance or abs(transform.d) > tolerance
                    or transform.a <= 0 or transform.e >= 0):
                raise ValueError(
                    "DEM is rotated, sheared or not north-up: " + filename +
                    ". Reproject it to a north-up elevation raster before importing."
                )
            sx, sy = _pixel_spacing_m(dataset)
            if any(not math.isfinite(value) or value <= 0 for value in (sx, sy)):
                raise ValueError("Could not establish DEM pixel spacing: " + filename)
            native_max = max(native_max, sx, sy)
            merge_x = max(merge_x, abs(float(transform.a)))
            merge_y = max(merge_y, abs(float(transform.e)))
            try:
                size = Path(filename).stat().st_size
            except OSError:
                size = None
            files.append({
                "path": str(Path(filename).resolve()),
                "size_bytes": size,
                "width": int(dataset.width),
                "height": int(dataset.height),
                "transform": [float(value) for value in tuple(transform)[:6]],
                "bounds": [float(value) for value in dataset.bounds],
                "spacing_m": [sx, sy],
                "horizontal_units": [str(axis.unit_name) for axis in pyproj.CRS.from_user_input(dataset.crs).to_2d().axis_info[:2]],
                "elevation_unit": str((dataset.units or [None])[0] or "not declared"),
                "dtype": str(dataset.dtypes[0]),
                "crs": dataset.crs.to_string(),
            })
    if native_max > MAX_HEIGHTMAP_SCALE:
        raise ValueError(
            "The selected DEM's source spacing reaches %g m. The current terrain exporter "
            "supports heightmap/stamp spacing up to 6 m. A finer output grid would not add "
            "source detail; select a finer source DEM." % native_max
        )
    first_spacing = files[0]["spacing_m"]
    mixed = any(any(not math.isclose(pair[axis], first_spacing[axis], rel_tol=1e-6, abs_tol=1e-8)
                    for axis in (0, 1)) for pair in (item["spacing_m"] for item in files[1:]))
    nonsquare = any(not math.isclose(*item["spacing_m"], rel_tol=1e-6, abs_tol=1e-8) for item in files)
    if mixed:
        notes.append("Selected DEM tiles have different spacing. Auto uses the coarsest source axis for a consistent mosaic, independent of tile order.")
    if nonsquare:
        notes.append("The source pixels are not square in metres. The chosen square grid uses the coarser axis; conversion does not add source detail.")
    crs = pyproj.CRS.from_user_input(reference_crs).to_2d()
    metric = crs.is_projected and all(abs(float(a.unit_conversion_factor) - 1.0) < 1e-12 for a in crs.axis_info[:2])
    if not metric:
        notes.append("Source coordinates will be converted to a metric projected grid at the confirmed spacing.")
    if any(item["elevation_unit"] == "not declared" for item in files):
        notes.append("At least one DEM does not declare elevation units; the existing importer assumes metres unless a vertical CRS supplies them.")
    reason = (
        "Detected %g m source grid spacing. Preserve the source detail for the heightmap; "
        "terrain stamp spacing is selected separately." % native_max
    )
    if mixed or nonsquare:
        reason = "Detected source grids require a common square grid. %g m preserves the coarsest source spacing without claiming extra detail." % native_max
    result = {
        "version": SOURCE_SCALE_VERSION,
        "source_type": "DEM",
        "source_count": len(files),
        "source_crs": reference_crs.to_string(),
        "recommended_scale": float(native_max),
        "minimum_scale": float(native_max),
        "confidence": "high",
        "summary": "%d DEM file%s; detected spacing %g to %g m" % (
            len(files), "" if len(files) == 1 else "s",
            min(min(item["spacing_m"]) for item in files), native_max),
        "reason": reason,
        "notes": notes,
        "dem_merge_resolution": [float(merge_x), float(merge_y)],
        "statistics": {"mixed_resolution": mixed, "non_square_pixels": nonsquare},
        "files": files,
    }
    printf("Source inspection: " + result["summary"] + ". Auto heightmap scale: %g m." % native_max)
    return result


def _ground_mask(points):
    return (np.isfinite(points[:, :3]).all(axis=1)
            & ((points[:, 4] == 2) | (points[:, 4] == 8)))


def _representative_blocks(sample_xy, xmin, ymin, xmax, ymax):
    """Select at most 64 occupied blocks spread over an 8 by 8 extent grid."""
    origin = np.floor(np.array((xmin, ymin)) / _LIDAR_BLOCK_M) * _LIDAR_BLOCK_M
    ny = int(math.floor((ymax - origin[1]) / _LIDAR_BLOCK_M)) + 1
    block_xy = np.floor((sample_xy - origin) / _LIDAR_BLOCK_M).astype(np.int64)
    keys = np.unique(block_xy[:, 0] * ny + block_xy[:, 1])
    bx, by = keys // ny, keys % ny
    centers = origin + (np.column_stack((bx, by)) + 0.5) * _LIDAR_BLOCK_M
    widths = np.maximum(np.array((xmax - xmin, ymax - ymin)), _LIDAR_BLOCK_M)
    strata_xy = np.clip(np.floor((centers - (xmin, ymin)) / widths * 8), 0, 7).astype(int)
    strata = strata_xy[:, 0] * 8 + strata_xy[:, 1]
    selected = []
    for index in np.unique(strata):
        eligible = np.flatnonzero(strata == index)
        target = np.array((xmin, ymin)) + (np.array((index // 8, index % 8)) + 0.5) / 8 * widths
        # Favor complete blocks over boundary fragments when available.
        complete = ((centers[eligible, 0] - 10 >= xmin) & (centers[eligible, 0] + 10 <= xmax)
                    & (centers[eligible, 1] - 10 >= ymin) & (centers[eligible, 1] + 10 <= ymax))
        if np.any(complete):
            eligible = eligible[complete]
        distance = np.sum((centers[eligible] - target) ** 2, axis=1)
        selected.append(keys[eligible[np.argmin(distance)]])
    return np.sort(np.asarray(selected, dtype=np.int64)), origin, ny


def inspect_lidar_points(points_or_pc, source_metadata=None, printf=print):
    """Measure classified ground coverage in representative 20 m blocks.

    Uniform sampling selects only the representative blocks. A second bounded
    chunk pass visits ALL points in those blocks, so thinning does not reduce
    measured occupancy. Duplicate XY returns do not increase coverage. Only
    temporary arrays are created; input point coordinates are never changed.
    """
    points = points_or_pc.points() if callable(getattr(points_or_pc, "points", None)) else points_or_pc
    points = np.asarray(points)
    if points.ndim != 2 or points.shape[1] < 5 or not len(points):
        raise ValueError("LiDAR source inspection requires X/Y/Z, intensity and classification points.")
    bounds = np.array((np.inf, np.inf, -np.inf, -np.inf), dtype=float)
    ground_count = 0
    fallback_samples = []
    for start in range(0, len(points), _LIDAR_CHUNK):
        chunk = points[start:start + _LIDAR_CHUNK]
        ground = chunk[_ground_mask(chunk), :2]
        ground_count += len(ground)
        if len(ground):
            bounds[:2] = np.minimum(bounds[:2], np.min(ground, axis=0))
            bounds[2:] = np.maximum(bounds[2:], np.max(ground, axis=0))
            if sum(len(part) for part in fallback_samples) < _LIDAR_SAMPLE_LIMIT:
                fallback_samples.append(ground[np.linspace(0, len(ground) - 1, min(64, len(ground)), dtype=int)])
    if not ground_count:
        raise ValueError("No finite classified ground points (classes 2 or 8) were found. A heightmap scale cannot be recommended for this source.")
    xmin, ymin, xmax, ymax = (float(value) for value in bounds)
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("Ground points do not cover a two-dimensional area; a terrain grid cannot be established.")
    if max(xmax - xmin, ymax - ymin) > 1e8:
        raise ValueError("LiDAR coordinates have an implausible extent; check the source projection and units before choosing a heightmap scale.")
    indices = np.linspace(0, len(points) - 1, min(_LIDAR_SAMPLE_LIMIT, len(points)), dtype=np.intp)
    sample = points[indices]
    sample_xy = sample[_ground_mask(sample), :2]
    if len(sample_xy) < min(64, ground_count):
        sample_xy = np.concatenate(fallback_samples, axis=0)
    selected_keys, origin, ny = _representative_blocks(sample_xy, xmin, ymin, xmax, ymax)
    block_count = len(selected_keys)
    side = int(_LIDAR_BLOCK_M / _LIDAR_FINE_M)
    occupied = np.zeros((block_count, side, side), dtype=bool)
    occupied_flat = occupied.ravel()
    raw_counts = np.zeros(block_count, dtype=np.int64)
    for start in range(0, len(points), _LIDAR_CHUNK):
        chunk = points[start:start + _LIDAR_CHUNK]
        ground = chunk[_ground_mask(chunk), :2]
        if not len(ground):
            continue
        block_xy = np.floor((ground - origin) / _LIDAR_BLOCK_M).astype(np.int64)
        keys = block_xy[:, 0] * ny + block_xy[:, 1]
        where = np.searchsorted(selected_keys, keys)
        valid = where < block_count
        valid[valid] &= selected_keys[where[valid]] == keys[valid]
        if not np.any(valid):
            continue
        where = where[valid]
        local = (ground[valid] - origin) - block_xy[valid] * _LIDAR_BLOCK_M
        cell_xy = np.clip(np.floor(local / _LIDAR_FINE_M).astype(np.int64), 0, side - 1)
        occupied_flat[where * side * side + cell_xy[:, 1] * side + cell_xy[:, 0]] = True
        raw_counts += np.bincount(where, minlength=block_count)
    block_origins = origin + np.column_stack((selected_keys // ny, selected_keys % ny)) * _LIDAR_BLOCK_M
    coverage = []
    for scale in LIDAR_CANDIDATE_SCALES:
        ratio = int(round(scale / _LIDAR_FINE_M))
        coarse_side = side // ratio
        # All candidates divide the 20 m blocks exactly except 4 m, which also
        # divides 20; reshape therefore preserves original spatial cells.
        coarse = occupied.reshape(block_count, coarse_side, ratio, coarse_side, ratio).any(axis=(2, 4))
        low = np.maximum(np.array((xmin, ymin)) - block_origins, 0.0)
        high = np.minimum(np.array((xmax, ymax)) - block_origins, _LIDAR_BLOCK_M - 1e-9)
        first = np.clip(np.floor(low / scale).astype(int), 0, coarse_side - 1)
        last = np.clip(np.floor(high / scale).astype(int), 0, coarse_side - 1)
        denominators = np.maximum(1, np.prod(last - first + 1, axis=1))
        fractions = np.minimum(1.0, coarse.sum(axis=(1, 2)) / denominators)
        median = float(np.median(fractions))
        lower_quartile = float(np.percentile(fractions, 25))
        coverage.append({"scale_m": scale, "median_ground_coverage": median,
                         "lower_quartile_ground_coverage": lower_quartile})
    chosen = 4.0
    supported = False
    for row in coverage:
        median_required, lower_required = (0.80, 0.60) if row["scale_m"] == 0.5 else (0.55, 0.35)
        if row["median_ground_coverage"] >= median_required and row["lower_quartile_ground_coverage"] >= lower_required:
            chosen = row["scale_m"]
            supported = True
            break
    confidence = "high" if block_count >= 12 and ground_count >= 2000 else ("moderate" if block_count >= 4 and ground_count >= 250 else "low")
    if not supported:
        confidence = "low"
    selected_coverage = next(row for row in coverage if row["scale_m"] == chosen)
    reason = (
        "%g m is recommended from classified ground coverage in %d representative areas "
        "(median %.0f%% of cells contain measured ground at that scale). "
        "Terrain stamp spacing remains separate."
        % (chosen, block_count, 100 * selected_coverage["median_ground_coverage"])
    )
    notes = ["Raw LiDAR has no fixed pixel size. This recommendation is a processing choice, not a survey-accuracy measurement."]
    if chosen == 0.5:
        notes.append("The sampled ground coverage supports a finer 0.5 m working grid. A 1 m manual setting is available for smaller heightmaps.")
    elif chosen > 1:
        notes.append("Ground returns are sparse or uneven at 1 m. The recommended coarser grid reduces empty terrain cells.")
    if confidence == "low":
        notes.append("Confidence is low because coverage is sparse or the inspected area is small. Review the chosen scale before continuing; gaps may still need interpolation.")
    if max(xmax - xmin, ymax - ymin) > 10000:
        notes.append("The input covers a large area. The recommendation samples the supplied source extent and may differ from a small course crop.")
    estimated_w = int(math.ceil((xmax - xmin) / chosen)) + 1
    estimated_h = int(math.ceil((ymax - ymin) / chosen)) + 1
    result = {
        "version": SOURCE_SCALE_VERSION,
        "source_type": "LiDAR",
        "recommended_scale": chosen,
        "minimum_scale": 0.0,
        "confidence": confidence,
        "summary": "%s LiDAR points; %s classified ground points" % (format(len(points), ","), format(ground_count, ",")),
        "reason": reason,
        "notes": notes,
        "statistics": {
            "point_count": int(len(points)), "ground_point_count": int(ground_count),
            "ground_classes": [2, 8], "representative_blocks": block_count,
            "block_size_m": _LIDAR_BLOCK_M, "coverage_by_scale": coverage,
            "coverage_supported": supported,
            "bounds_m": [xmin, ymin, xmax, ymax],
            "estimated_grid_size": [estimated_w, estimated_h],
            "estimated_base_raster_mib": estimated_w * estimated_h * 4.0 / 1048576,
            "sampled_block_ground_points": int(raw_counts.sum()),
        },
    }
    if source_metadata:
        # Metadata can help explain the source; it never overrides measured
        # coverage or turns a nominal pulse-density figure into ground density.
        import json
        result["source_metadata"] = json.loads(json.dumps(source_metadata, default=str))
    printf("Source inspection: " + result["summary"] + ". Auto heightmap scale: %g m (%s confidence)." % (chosen, confidence))
    return result
