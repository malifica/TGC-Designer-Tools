import math
from collections import Counter

import cv2
import numpy as np


ADAPTIVE_SEED = 250914
ADAPTIVE_MIN_BASE_SPACING_M = 2.0


def _stable_u32(row, col, cells, salt=0):
    x = (int(row) * 0x45D9F3B) ^ (int(col) * 0x119DE1F3)
    x ^= int(cells) * 0x27D4EB2D
    x ^= ADAPTIVE_SEED * 0x165667B1
    x ^= int(salt) * 0x9E3779B1
    x &= 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x & 0xFFFFFFFF


def _rand01(row, col, cells, salt=0):
    return _stable_u32(row, col, cells, salt) / 4294967295.0


def _dilate(mask, radius_cells):
    radius_cells = max(0, int(radius_cells))
    if radius_cells <= 0:
        return mask.copy()
    k = radius_cells * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool)


def _semantic_masks(mask_bgr, image_scale):
    b = mask_bgr[:, :, 0].astype(np.int16)
    g = mask_bgr[:, :, 1].astype(np.int16)
    r = mask_bgr[:, :, 2].astype(np.int16)

    water = (b >= 200) & (g <= 110) & (r <= 110)

    bunker = (
        (b >= 130) & (b <= 215) &
        (g >= 180) & (r >= 180) &
        (np.abs(g - r) <= 45)
    )

    green = (g >= 225) & (r <= 95) & (b <= 120)
    tee = (g >= 185) & (g < 225) & (r <= 60) & (b <= 60)
    fairway = (
        (g >= 145) & (g < 225) &
        (r <= 100) & (b <= 130) &
        (~tee)
    )

    critical = green | tee | bunker | water

    critical_radius = int(math.ceil(8.0 / max(float(image_scale), 1e-6)))
    fairway_radius = int(math.ceil(6.0 / max(float(image_scale), 1e-6)))

    critical_buffer = _dilate(critical, critical_radius) & (~critical)
    fairway_buffer = (
        _dilate(fairway, fairway_radius) &
        (~fairway) &
        (~critical) &
        (~critical_buffer)
    )

    return {
        "water": water,
        "bunker": bunker,
        "green": green,
        "tee": tee,
        "fairway": fairway,
        "critical": critical,
        "critical_buffer": critical_buffer,
        "fairway_buffer": fairway_buffer,
    }


def _standard_block_error(block):
    """
    Standard's conservative terrain test.

    The proven Standard profile was built around the old 2 m hard-square
    LiDAR lattice and did NOT use Aggressive's best-fit-plane residual.
    Raw elevation range deliberately makes a legitimate slope harder to
    coarsen, which is why Standard preserves more terrain than Aggressive.
    """
    finite = block[np.isfinite(block)]
    if finite.size <= 1:
        return 0.0
    return float(np.max(finite) - np.min(finite))


def _plane_max_residual(block):
    """
    Aggressive profile only: local best-fit-plane residual.

    This allows a smooth hillside to coarsen without treating the slope itself
    as terrain error.
    """
    rows, cols = block.shape
    if rows <= 1 and cols <= 1:
        return 0.0

    z = block.astype(np.float64, copy=False)
    zmean = float(np.mean(z))

    rr = np.arange(rows, dtype=np.float64) - (rows - 1) * 0.5
    cc = np.arange(cols, dtype=np.float64) - (cols - 1) * 0.5

    if cols > 1:
        denom_x = rows * float(np.sum(cc * cc))
        a = float(np.sum(np.sum(z, axis=0) * cc) / denom_x)
    else:
        a = 0.0

    if rows > 1:
        denom_y = cols * float(np.sum(rr * rr))
        b = float(np.sum(np.sum(z, axis=1) * rr) / denom_y)
    else:
        b = 0.0

    pred = zmean + b * rr[:, None] + a * cc[None, :]
    return float(np.max(np.abs(z - pred)))


def _bilinear(heightmap, row, col):
    h, w = heightmap.shape

    row = min(max(float(row), 0.0), h - 1.0)
    col = min(max(float(col), 0.0), w - 1.0)

    r0 = int(math.floor(row))
    c0 = int(math.floor(col))
    r1 = min(r0 + 1, h - 1)
    c1 = min(c0 + 1, w - 1)

    fr = row - r0
    fc = col - c0

    vals = [
        (heightmap[r0, c0], (1.0 - fr) * (1.0 - fc)),
        (heightmap[r0, c1], (1.0 - fr) * fc),
        (heightmap[r1, c0], fr * (1.0 - fc)),
        (heightmap[r1, c1], fr * fc),
    ]

    total = 0.0
    weight = 0.0
    for value, wt in vals:
        if np.isfinite(value):
            total += float(value) * wt
            weight += wt

    if weight <= 1e-12:
        return float("nan")
    return total / weight


def _block_policy(sem, r0, r1, c0, c1, mode, adaptive_base_spacing):
    sl = np.s_[r0:r1, c0:c1]

    # Water/mask protection is handled separately before adaptive acceptance.
    if np.any(sem["critical"][sl]):
        return adaptive_base_spacing, 0.020, "critical"

    if np.any(sem["critical_buffer"][sl]):
        return 4.0, 0.035, "critical_buffer"

    if np.any(sem["fairway"][sl]):
        if mode == "aggressive":
            return 8.0, 0.040, "fairway"
        return 4.0, 0.040, "fairway"

    if np.any(sem["fairway_buffer"][sl]):
        if mode == "aggressive":
            return 16.0, 0.060, "fairway_buffer"
        return 8.0, 0.060, "fairway_buffer"

    if mode == "aggressive":
        return 32.0, 0.100, "general"

    return 16.0, 0.100, "general"


def _footprint_safe(valid, water, center_r, center_c, footprint_m, image_scale):
    radius_cells = 0.5 * float(footprint_m) / float(image_scale)

    r0 = int(math.floor(center_r - radius_cells))
    r1 = int(math.ceil(center_r + radius_cells)) + 1
    c0 = int(math.floor(center_c - radius_cells))
    c1 = int(math.ceil(center_c + radius_cells)) + 1

    if r0 < 0 or c0 < 0 or r1 > valid.shape[0] or c1 > valid.shape[1]:
        return False

    return bool(
        np.all(valid[r0:r1, c0:c1]) and
        not np.any(water[r0:r1, c0:c1])
    )


def _standard_footprint(spacing_m, row, col, cells):
    overlap = 0.15 + 0.06 * _rand01(row, col, cells, 11)
    return float(spacing_m) * (1.0 + overlap)


def _aggressive_footprint(spacing_m):
    spacing_m = float(spacing_m)
    if spacing_m <= 8.000001:
        return 2.0 * spacing_m
    return 1.5 * spacing_m


def _standard_jitter(spacing_m, row, col, cells):
    if spacing_m <= 4.0:
        atten = 1.0
    elif spacing_m <= 8.0:
        atten = 0.65
    else:
        atten = 0.40

    amp = 0.09 * spacing_m * atten

    return (
        (2.0 * _rand01(row, col, cells, 21) - 1.0) * amp,
        (2.0 * _rand01(row, col, cells, 22) - 1.0) * amp,
    )


def _standard_rotation(row, col, cells):
    angle = -45.0 + 90.0 * _rand01(row, col, cells, 31)
    if -6.0 < angle < 6.0:
        angle = 6.0 if angle >= 0.0 else -6.0
    return angle


def _next_power_of_two_at_least(value):
    n = 1
    while n < value:
        n *= 2
    return n


def generate_adaptive_stamps(
    heightmap,
    mask_bgr,
    pc,
    image_scale,
    mode,
    get_pixel,
    printf=print,
    hard_boundary_brush_type=72,
    hard_boundary_footprint=None,
    coordinate_min_row=None,
    coordinate_min_col=None,
):
    mode = str(mode or "standard").strip().lower()

    if mode not in ("standard", "aggressive"):
        raise ValueError(
            "Adaptive mode must be 'standard' or 'aggressive'."
        )

    image_scale = float(image_scale)
    heightmap = np.asarray(heightmap, dtype=np.float32)

    # Normalize HxWx1 or similar singleton-channel heightmaps.
    original_shape = heightmap.shape
    if heightmap.ndim > 2:
        heightmap = np.squeeze(heightmap)

    if heightmap.ndim != 2:
        raise ValueError(
            "Adaptive terrain expected a 2-D elevation raster; received shape " +
            str(original_shape) + " -> " + str(heightmap.shape)
        )

    if original_shape != heightmap.shape:
        printf(
            "Adaptive heightmap shape normalized: " +
            str(original_shape) + " -> " + str(heightmap.shape)
        )

    if mask_bgr is None or mask_bgr.ndim != 3:
        raise ValueError(
            "Adaptive terrain expected a 3-channel mask image."
        )

    if mask_bgr.shape[:2] != heightmap.shape:
        raise ValueError(
            "Adaptive heightmap/mask size mismatch: " +
            str(heightmap.shape) + " versus " + str(mask_bgr.shape[:2])
        )

    valid = np.isfinite(heightmap)

    if not np.any(valid):
        return [], {
            "input_cells": 0,
            "output_stamps": 0,
            "reduction_percent": 0.0,
        }

    sem = _semantic_masks(mask_bgr, image_scale)

    valid_rows, valid_cols = np.nonzero(valid)
    detected_min_row = int(valid_rows.min())
    detected_min_col = int(valid_cols.min())

    # Hybrid sub-layers must share the full source coordinate frame.
    # Otherwise each masked subset is incorrectly shifted to its own lower-left.
    min_row = detected_min_row if coordinate_min_row is None else int(coordinate_min_row)
    min_col = detected_min_col if coordinate_min_col is None else int(coordinate_min_col)

    h, w = heightmap.shape

    # IMPORTANT:
    # Standard and Aggressive were designed around the old 2 m ChadTool /
    # TGC-Designer-Tools LiDAR lattice. A 1 m DEM must NOT silently turn
    # Standard into a new 1/2/4/8/16 m algorithm.
    #
    # If the source is finer than 2 m, use the source samples to evaluate
    # terrain fidelity but emit no ordinary adaptive tier finer than 2 m.
    raw_cells_per_base = max(
        1,
        int(math.ceil(ADAPTIVE_MIN_BASE_SPACING_M / image_scale - 1e-9)),
    )
    base_cells = _next_power_of_two_at_least(raw_cells_per_base)
    adaptive_base_spacing = base_cells * image_scale

    specs = []
    tier_counts = Counter()
    protected_leaf_count = 0
    boundary_refinements = 0

    max_m = 32.0 if mode == "aggressive" else 16.0

    max_cells = base_cells
    while (max_cells * 2) * image_scale <= max_m + 1e-6:
        max_cells *= 2

    def append_stamp(
        spacing_m,
        key_row,
        key_col,
        center_r,
        center_c,
        elevation,
        footprint,
        brush_type,
        rotation,
    ):
        x_enu = (center_c - min_col + 0.5) * image_scale
        y_enu = (center_r - min_row + 0.5) * image_scale
        x, _, z = pc.enuToTGC(x_enu, y_enu, 0.0)

        specs.append(
            (
                float(spacing_m),
                int(key_row),
                int(key_col),
                float(elevation),
                x,
                z,
                float(footprint),
                int(brush_type),
                float(rotation),
            )
        )
        tier_counts[round(float(spacing_m), 6)] += 1

    def emit_hard_source_leaf(r, c):
        nonlocal protected_leaf_count

        if r < 0 or c < 0 or r >= h or c >= w:
            return
        if not valid[r, c]:
            return

        center_r = float(r)
        center_c = float(c)
        elevation = float(heightmap[r, c])

        x_enu = (center_c - min_col + 0.5) * image_scale
        y_enu = (center_r - min_row + 0.5) * image_scale
        x, _, z = pc.enuToTGC(x_enu, y_enu, 0.0)

        boundary_footprint = hard_boundary_footprint
        if boundary_footprint is None:
            boundary_footprint = image_scale

        specs.append(
            (
                float(image_scale),
                int(r),
                int(c),
                elevation,
                x,
                z,
                float(boundary_footprint),
                int(hard_boundary_brush_type),
                0.0,
            )
        )
        tier_counts[round(float(image_scale), 6)] += 1
        protected_leaf_count += 1

    def emit_adaptive_base(r0, c0, cells):
        r1 = min(r0 + cells, h)
        c1 = min(c0 + cells, w)

        center_r = r0 + (r1 - r0) * 0.5 - 0.5
        center_c = c0 + (c1 - c0) * 0.5 - 0.5

        spacing_m = cells * image_scale

        if mode == "standard":
            jitter_r_m, jitter_c_m = _standard_jitter(
                spacing_m, r0, c0, cells
            )
            jr = center_r + jitter_r_m / image_scale
            jc = center_c + jitter_c_m / image_scale
            elevation = _bilinear(heightmap, jr, jc)
            footprint = _standard_footprint(
                spacing_m, r0, c0, cells
            )
            rotation = _standard_rotation(r0, c0, cells)
            brush_type = 15
            center_r_out = jr
            center_c_out = jc
        else:
            elevation = _bilinear(heightmap, center_r, center_c)
            footprint = _aggressive_footprint(spacing_m)
            rotation = 0.0
            brush_type = 10
            center_r_out = center_r
            center_c_out = center_c

        if not np.isfinite(elevation):
            return False

        append_stamp(
            spacing_m,
            r0,
            c0,
            center_r_out,
            center_c_out,
            elevation,
            footprint,
            brush_type,
            rotation,
        )
        return True

    def recurse(r0, c0, cells):
        nonlocal boundary_refinements

        r1 = min(r0 + cells, h)
        c1 = min(c0 + cells, w)

        if r0 >= h or c0 >= w or r1 <= r0 or c1 <= c0:
            return

        subvalid = valid[r0:r1, c0:c1]

        if not np.any(subvalid):
            return

        # Missing-data edges are hard boundaries. They may refine below the
        # normal 2 m adaptive base so holes/water/mask edges are not bridged.
        if not np.all(subvalid):
            if cells <= 1:
                emit_hard_source_leaf(r0, c0)
                return

            boundary_refinements += 1
            half = max(1, cells // 2)

            for rr in (r0, r0 + half):
                for cc in (c0, c0 + half):
                    recurse(rr, cc, half)
            return

        # Explicit water is also a hard boundary. With purge-water enabled it
        # is already NaN; otherwise retain the raw source cells rather than
        # laying large adaptive brushes across it.
        if np.any(sem["water"][r0:r1, c0:c1]):
            if cells <= 1:
                emit_hard_source_leaf(r0, c0)
                return

            boundary_refinements += 1
            half = max(1, cells // 2)
            for rr in (r0, r0 + half):
                for cc in (c0, c0 + half):
                    recurse(rr, cc, half)
            return

        # Do not allow ordinary adaptive generation below the proven 2 m base.
        if cells <= base_cells:
            if cells < base_cells:
                # This can happen only after hard-boundary refinement.
                if cells <= 1:
                    emit_hard_source_leaf(r0, c0)
                else:
                    half = max(1, cells // 2)
                    for rr in (r0, r0 + half):
                        for cc in (c0, c0 + half):
                            recurse(rr, cc, half)
                return

            emit_adaptive_base(r0, c0, cells)
            return

        spacing_m = cells * image_scale

        max_allowed_m, tolerance_m, zone = _block_policy(
            sem,
            r0,
            r1,
            c0,
            c1,
            mode,
            adaptive_base_spacing,
        )

        accept = spacing_m <= max_allowed_m + 1e-6

        if accept:
            block = heightmap[r0:r1, c0:c1]

            if mode == "standard":
                # Proven Standard behavior is intentionally conservative.
                # Do NOT use Aggressive's plane-residual test here.
                error_m = _standard_block_error(block)
            else:
                error_m = _plane_max_residual(block)

            accept = error_m <= tolerance_m + 1e-12

        center_r = r0 + (r1 - r0) * 0.5 - 0.5
        center_c = c0 + (c1 - c0) * 0.5 - 0.5

        if accept:
            if mode == "aggressive":
                footprint = _aggressive_footprint(spacing_m)
            else:
                footprint = _standard_footprint(
                    spacing_m, r0, c0, cells
                )

            if not _footprint_safe(
                valid,
                sem["water"],
                center_r,
                center_c,
                footprint,
                image_scale,
            ):
                accept = False
                boundary_refinements += 1

        if accept:
            if mode == "standard":
                jitter_r_m, jitter_c_m = _standard_jitter(
                    spacing_m, r0, c0, cells
                )
                jr = center_r + jitter_r_m / image_scale
                jc = center_c + jitter_c_m / image_scale

                elevation = _bilinear(heightmap, jr, jc)

                if np.isfinite(elevation):
                    append_stamp(
                        spacing_m,
                        r0,
                        c0,
                        jr,
                        jc,
                        elevation,
                        _standard_footprint(
                            spacing_m, r0, c0, cells
                        ),
                        15,
                        _standard_rotation(r0, c0, cells),
                    )
                    return

            else:
                elevation = _bilinear(
                    heightmap, center_r, center_c
                )

                if np.isfinite(elevation):
                    append_stamp(
                        spacing_m,
                        r0,
                        c0,
                        center_r,
                        center_c,
                        elevation,
                        _aggressive_footprint(spacing_m),
                        10,
                        0.0,
                    )
                    return

        half = max(1, cells // 2)
        for rr in (r0, r0 + half):
            for cc in (c0, c0 + half):
                recurse(rr, cc, half)

    # Tile the raster with the largest adaptive tier.
    for r0 in range(0, h, max_cells):
        for c0 in range(0, w, max_cells):
            recurse(r0, c0, max_cells)

    # Largest-to-smallest tiers, with deterministic randomized ordering within
    # each tier to de-correlate the original regular grid.
    specs.sort(
        key=lambda s: (
            -float(s[0]),
            _stable_u32(
                int(s[1]),
                int(s[2]),
                max(
                    1,
                    int(round(s[0] / image_scale)),
                ),
                77,
            ),
        )
    )

    stamps = []

    for (
        spacing_m,
        rkey,
        ckey,
        elevation,
        x,
        z,
        footprint,
        brush_type,
        rotation,
    ) in specs:
        stamp = get_pixel(
            x,
            z,
            elevation,
            footprint,
            brush_type=brush_type,
        )
        stamp["rotation"]["y"] = float(rotation)
        stamps.append(stamp)

    input_cells = int(np.count_nonzero(valid))
    output_count = len(stamps)

    reduction = (
        100.0 *
        (1.0 - float(output_count) / float(input_cells))
        if input_cells else 0.0
    )

    printf("Adaptive terrain engine: V2 / 2m-profile corrected")
    printf("Adaptive terrain mode: " + mode.title())
    printf(
        "Raw source spacing: " +
        str(round(image_scale, 4)) + " m"
    )
    printf(
        "Adaptive logical base spacing: " +
        str(round(adaptive_base_spacing, 4)) + " m"
    )

    if image_scale < ADAPTIVE_MIN_BASE_SPACING_M - 1e-6:
        printf(
            "Fine source detected: source elevations remain available for "
            "error testing/resampling, but ordinary adaptive stamping starts "
            "at the proven 2 m profile."
        )

    printf(
        "Adaptive valid source cells: " +
        str(input_cells)
    )

    for tier in sorted(tier_counts):
        printf(
            "  " + str(round(tier, 4)) +
            " m tier: " +
            str(tier_counts[tier]) +
            " stamps"
        )

    printf(
        "Adaptive hard-boundary source stamps: " +
        str(protected_leaf_count)
    )
    printf(
        "Adaptive mask/water boundary refinements: " +
        str(boundary_refinements)
    )
    printf(
        "Adaptive output terrain stamps: " +
        str(output_count)
    )
    printf(
        "Adaptive terrain stamp reduction vs raw source cells: " +
        str(round(reduction, 1)) + "%"
    )

    return stamps, {
        "engine_version": "V2_2m_profile_corrected",
        "mode": mode,
        "raw_source_spacing": image_scale,
        "adaptive_base_spacing": adaptive_base_spacing,
        "input_cells": input_cells,
        "output_stamps": output_count,
        "reduction_percent": reduction,
        "tier_counts": dict(tier_counts),
        "protected_source_stamps": protected_leaf_count,
        "boundary_refinements": boundary_refinements,
    }

def generate_hybrid_playable_aggressive(
    heightmap,
    mask_bgr,
    pc,
    image_scale,
    get_pixel,
    printf=print,
):
    """
    Hybrid profile:
      - Green / tee / bunker / fairway:
        native source spacing, Brush 72, 2 m footprint.
      - Non-playable land:
        Aggressive type-10 adaptive terrain.
      - Blue-mask water:
        Aggressive type-10 adaptive terrain only.
        If purge-water already changed those cells to NaN, no terrain is written.
    """
    image_scale = float(image_scale)
    heightmap = np.asarray(heightmap, dtype=np.float32)

    original_shape = heightmap.shape
    if heightmap.ndim > 2:
        heightmap = np.squeeze(heightmap)

    if heightmap.ndim != 2:
        raise ValueError(
            "Hybrid terrain expected a 2-D elevation raster; received shape " +
            str(original_shape) + " -> " + str(heightmap.shape)
        )

    if mask_bgr is None or mask_bgr.ndim != 3:
        raise ValueError("Hybrid terrain expected a 3-channel mask image.")

    if mask_bgr.shape[:2] != heightmap.shape:
        raise ValueError(
            "Hybrid heightmap/mask size mismatch: " +
            str(heightmap.shape) + " versus " + str(mask_bgr.shape[:2])
        )

    valid = np.isfinite(heightmap)
    if not np.any(valid):
        return [], {
            "mode": "hybrid_playable72_aggressive10",
            "output_stamps": 0,
        }

    sem = _semantic_masks(mask_bgr, image_scale)

    # All hybrid layers use one shared full-heightmap coordinate frame.
    full_rows, full_cols = np.nonzero(valid)
    coordinate_min_row = int(full_rows.min())
    coordinate_min_col = int(full_cols.min())

    printf(
        "Hybrid shared coordinate frame: min row " +
        str(coordinate_min_row) + ", min col " +
        str(coordinate_min_col)
    )

    playable = (
        sem["green"] |
        sem["tee"] |
        sem["bunker"] |
        sem["fairway"]
    ) & valid & (~sem["water"])

    water = sem["water"] & valid
    other_land = valid & (~playable) & (~water)

    printf("Hybrid terrain engine: V2 / shared-coordinate fix")
    printf("Hybrid terrain profile: Playable Brush 72 / Aggressive Brush 10")
    printf(
        "Playable areas: native source spacing, Brush 72, 2 m footprint."
    )
    printf(
        "Non-playable land: Aggressive type-10 adaptive terrain."
    )
    printf(
        "Blue mask: NEVER Brush 72. Uses Aggressive type 10, "
        "or no terrain if purge-water removed those cells."
    )

    # Non-playable land.
    land_height = np.where(
        other_land, heightmap, np.nan
    ).astype(np.float32)

    land_stamps, land_report = generate_adaptive_stamps(
        land_height,
        mask_bgr,
        pc,
        image_scale,
        mode="aggressive",
        get_pixel=get_pixel,
        printf=lambda msg: printf("Hybrid land: " + str(msg)),
        hard_boundary_brush_type=10,
        hard_boundary_footprint=max(2.0, 2.0 * image_scale),
        coordinate_min_row=coordinate_min_row,
        coordinate_min_col=coordinate_min_col,
    )

    # Blue-mask water. Clear blue in the mask copy so the core aggressive
    # routine treats this as ordinary type-10 terrain bounded by NaN outside.
    water_stamps = []
    water_report = {
        "input_cells": int(np.count_nonzero(water)),
        "output_stamps": 0,
    }

    if np.any(water):
        water_height = np.where(
            water, heightmap, np.nan
        ).astype(np.float32)

        water_mask = mask_bgr.copy()
        water_mask[sem["water"]] = (0, 0, 0)

        water_stamps, water_report = generate_adaptive_stamps(
            water_height,
            water_mask,
            pc,
            image_scale,
            mode="aggressive",
            get_pixel=get_pixel,
            printf=lambda msg: printf("Hybrid blue-mask: " + str(msg)),
            hard_boundary_brush_type=10,
            hard_boundary_footprint=max(2.0, 2.0 * image_scale),
            coordinate_min_row=coordinate_min_row,
            coordinate_min_col=coordinate_min_col,
        )
    else:
        printf(
            "Hybrid blue-mask: no finite blue-mask terrain cells remain; "
            "no terrain stamps written under blue water."
        )

    # Exact playable layer LAST so it remains authoritative over any overlap.
    min_row = coordinate_min_row
    min_col = coordinate_min_col

    playable_footprint = max(2.0, image_scale)
    playable_stamps = []

    rows, cols = np.nonzero(playable)
    for r, c in zip(rows, cols):
        x_enu = (float(c - min_col) + 0.5) * image_scale
        y_enu = (float(r - min_row) + 0.5) * image_scale
        x, _, z = pc.enuToTGC(x_enu, y_enu, 0.0)

        playable_stamps.append(
            get_pixel(
                x,
                z,
                float(heightmap[r, c]),
                playable_footprint,
                brush_type=72,
            )
        )

    stamps = land_stamps + water_stamps + playable_stamps

    source_cells = int(np.count_nonzero(valid))
    output_count = len(stamps)
    reduction = (
        100.0 * (1.0 - float(output_count) / float(source_cells))
        if source_cells else 0.0
    )

    printf("Hybrid terrain summary")
    printf("  Source valid cells: " + str(source_cells))
    printf(
        "  Playable Brush-72 stamps: " +
        str(len(playable_stamps))
    )
    printf(
        "  Non-playable Aggressive type-10 stamps: " +
        str(len(land_stamps))
    )
    printf(
        "  Blue-mask Aggressive type-10 stamps: " +
        str(len(water_stamps))
    )
    printf(
        "  Total hybrid terrain stamps: " +
        str(output_count)
    )
    printf(
        "  Terrain-stamp reduction vs fully dense source: " +
        str(round(reduction, 1)) + "%"
    )

    return stamps, {
        "mode": "hybrid_playable72_aggressive10",
        "raw_source_spacing": image_scale,
        "source_cells": source_cells,
        "playable_72_stamps": len(playable_stamps),
        "land_type10_stamps": len(land_stamps),
        "water_type10_stamps": len(water_stamps),
        "output_stamps": output_count,
        "reduction_percent": reduction,
        "land_report": land_report,
        "water_report": water_report,
    }
