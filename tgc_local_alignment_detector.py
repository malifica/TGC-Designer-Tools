"""Terrain-supported OSM tee/bunker translation proposals; never auto-edits OSM.

The scores are experimental ranking measures, not probabilities or ground truth.
Input terrain is numeric, south-up, with a southwest CELL EDGE origin. Samples
are at cell centres. The default search and its thresholds are explicit below.
"""
from __future__ import annotations


import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates, binary_erosion
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
try:
    from shapely import contains_xy
except ImportError as exc:
    raise ImportError("Local alignment requires Shapely >= 2.0; rerun the Beta 7 build installer.") from exc


CONFIG = {
    "version": "local-tee-bunker-probe-0.3",
    "search_radius_m": 4.0,
    "search_step_m": 0.5,
    "smoothing_sigma_cells": [0.5, 0.8],
    "profile_halfwidth_m": 2.5,
    "movement_prior": 0.25,
    "minimum_move_m": 1.0,
    "minimum_normalized_gain": 0.18,
    "maximum_scale_disagreement_m": 1.5,
    "minimum_independent_interior_cells": 12,
    "minimum_boundary_curvature_per_m": 0.003,
    "minimum_relief_m": 0.15,
    "minimum_supported_arcs": 2,
}


def boundary_samples(poly, spacing=1.5):
    ring = orient(poly, sign=1.0).exterior
    ds = np.linspace(0.0, ring.length, max(16, int(np.ceil(ring.length / spacing))), endpoint=False)
    xy = np.array([[ring.interpolate(d).x, ring.interpolate(d).y] for d in ds])
    before = np.array([[ring.interpolate((d - 0.8) % ring.length).x,
                        ring.interpolate((d - 0.8) % ring.length).y] for d in ds])
    after = np.array([[ring.interpolate((d + 0.8) % ring.length).x,
                       ring.interpolate((d + 0.8) % ring.length).y] for d in ds])
    t = after - before
    t /= np.maximum(np.linalg.norm(t, axis=1)[:, None], 1e-10)
    outward = np.column_stack([t[:, 1], -t[:, 0]])
    return xy, outward


def interior_samples(poly, spacing=1.5, inset=0.7):
    p = poly.buffer(-inset)
    if p.is_empty or p.area < 4:
        p = poly
    x0, y0, x1, y1 = p.bounds
    xs = np.arange(x0 + spacing / 2, x1, spacing)
    ys = np.arange(y0 + spacing / 2, y1, spacing)
    xx, yy = np.meshgrid(xs, ys)
    keep = contains_xy(p, xx, yy)
    result = np.column_stack([xx[keep], yy[keep]])
    if len(result) > 600:
        result = result[np.linspace(0, len(result) - 1, 600).astype(int)]
    return result


class Terrain:
    def __init__(self, heights, resolution, sigmas=None):
        self.z = np.asarray(heights, dtype=np.float64).squeeze()
        if self.z.ndim != 2:
            raise ValueError("Expected one two-dimensional heightmap")
        self.resolution = float(resolution)
        self.finite = np.isfinite(self.z)
        self.fields = []
        for sigma in sigmas or CONFIG["smoothing_sigma_cells"]:
            weights = gaussian_filter(self.finite.astype(float), sigma, mode="constant", cval=0)
            numerator = gaussian_filter(np.where(self.finite, self.z, 0), sigma, mode="constant", cval=0)
            smooth = numerator / np.maximum(weights, 1e-12)
            # Reject samples whose smoothing support touches missing cells/bounds.
            valid = binary_erosion(self.finite, iterations=max(1, int(np.ceil(3 * sigma))), border_value=0)
            gy, gx = np.gradient(smooth, self.resolution)
            self.fields.append({"sigma": sigma, "z": smooth, "slope": np.hypot(gx, gy), "valid": valid})

    def sample(self, field, points):
        p = np.asarray(points)
        # Translate southwest edge-referenced metres to cell-centre indices.
        indices = np.array([p[..., 1] / self.resolution - 0.5,
                            p[..., 0] / self.resolution - 0.5])
        return map_coordinates(field, indices, order=1, mode="constant", cval=np.nan, prefilter=False)


def score_candidates(terrain, feature, shifts, field):
    p = Polygon(feature["coords_m"])
    boundary, normal = boundary_samples(p)
    inside = interior_samples(p)
    if len(inside) < 4:
        raise ValueError("Too few interior samples")
    centre = np.asarray(p.centroid.coords[0])
    r = CONFIG["profile_halfwidth_m"]
    points = boundary[None, :, :] + shifts[:, None, :]
    inn = points - r * normal[None, :, :]
    out = points + r * normal[None, :, :]
    zi = terrain.sample(field["z"], inn)
    zb = terrain.sample(field["z"], points)
    zo = terrain.sample(field["z"], out)
    iz = terrain.sample(field["z"], inside[None, :, :] + shifts[:, None, :])
    slope = terrain.sample(field["slope"], inside[None, :, :] + shifts[:, None, :])
    vv = [terrain.sample(field["valid"].astype(float), xx) for xx in (inn, points, out)]
    iv = terrain.sample(field["valid"].astype(float), inside[None, :, :] + shifts[:, None, :])
    valid = np.logical_and.reduce([np.all(v >= 0.999, axis=1) for v in vv + [iv]])
    valid &= np.all(np.isfinite(iz), axis=1)
    # Inner-to-outer slope change: positive at a convex upper bank/rim.
    curvature = (2 * zb - zi - zo) / r**2
    rim = np.mean(np.clip(curvature, -0.08, 0.12), axis=1)
    slope80 = np.quantile(slope, 0.8, axis=1)
    design = np.column_stack([inside - centre, np.ones(len(inside))])
    coeff = (iz - np.mean(iz, axis=1)[:, None]) @ np.linalg.pinv(design).T
    residual = iz - np.mean(iz, axis=1)[:, None] - coeff @ design.T
    flatness = np.sqrt(np.mean(np.minimum(residual**2, 1.0), axis=1))
    plane_slope = np.hypot(coeff[:, 0], coeff[:, 1])
    if feature["kind"] == "tee":
        # Outward drop helps distinguish a plateau from an ordinary hillside.
        signed_drop = np.mean(np.clip((zi - zo) / (2 * r), -0.4, 0.4), axis=1)
        arc_score = 1.4 * np.clip(curvature, -0.08, 0.12) + 0.2 * np.clip((zi - zo) / (2 * r), -0.4, 0.4)
        raw = 1.4 * rim + 0.2 * signed_drop - 0.55 * slope80 - 0.08 * flatness
        relief = np.mean(zi - zo, axis=1)
    else:
        # Compare boundary to inward samples; never minimize bunker floor Z.
        signed_drop = np.mean(np.clip((zo - zi) / (2 * r), -0.4, 0.4), axis=1)
        arc_score = 1.4 * np.clip(curvature, -0.08, 0.12) + 0.3 * np.clip((zo - zi) / (2 * r), -0.4, 0.4)
        raw = 1.4 * rim + 0.3 * signed_drop
        relief = np.mean(zo - zi, axis=1)
    raw[~valid] = -np.inf
    arcs = np.column_stack([np.mean(x, axis=1) for x in np.array_split(arc_score, 4, axis=1)])
    return {"raw": raw, "rim": rim, "relief": relief, "arcs": arcs,
            "slope80": slope80, "plane_slope": plane_slope, "flatness": flatness,
            "valid": valid, "boundary_samples": len(boundary), "interior_samples": len(inside)}


def analyse_feature(terrain, feature, config=None):
    cfg = CONFIG | (config or {})
    lim, step = cfg["search_radius_m"], cfg["search_step_m"]
    axis = np.arange(-lim, lim + step / 2, step)
    xx, yy = np.meshgrid(axis, axis)
    shifts = np.column_stack([xx.ravel(), yy.ravel()])
    # Circular search radius prevents 5.66 m diagonal moves in a 4 m search.
    radius = np.linalg.norm(shifts, axis=1)
    allowed = radius <= lim + 1e-8
    zi = int(np.argmin(radius))
    record = {
        "way_id": feature["way_id"], "kind": feature["kind"],
        "course_name": feature.get("course_name", ""),
        "centroid_m": feature.get("centroid_m", list(Polygon(feature["coords_m"]).centroid.coords[0])),
        "area_m2": float(Polygon(feature["coords_m"]).area),
        "shared_nodes": bool(feature.get("shared_nodes")),
        "accepted_by_default": False,
        "global_nudge_m": [0.0, 0.0],
        "proposed_east_m": 0.0, "proposed_north_m": 0.0,
        "status": "insufficient_evidence", "reasons": [],
    }
    poly = Polygon(feature["coords_m"])
    if not poly.is_valid or poly.is_empty:
        record["reasons"] = ["invalid_polygon"]
        return record
    try:
        scores = [score_candidates(terrain, feature, shifts, f) for f in terrain.fields]
    except ValueError as exc:
        record["reasons"] = [str(exc)]
        return record
    valid = allowed & np.logical_and.reduce([s["valid"] for s in scores])
    if not valid[zi] or np.count_nonzero(valid) < 20:
        record["reasons"] = ["incomplete_terrain_support"]
        return record
    normalized = []
    spans = []
    prior = cfg["movement_prior"] * (radius / lim)**2
    for s in scores:
        sample = s["raw"][valid]
        span = max(0.015, float(np.quantile(sample, .9) - np.quantile(sample, .1)))
        spans.append(span)
        norm = (s["raw"] - s["raw"][zi]) / span
        norm[~valid] = -np.inf
        normalized.append(norm)
    # Estimate displacement from terrain alone. The preference to stay put is
    # an accept/abstain gate, not a spring that shrinks every fitted correction.
    # In particular the prior must not manufacture a narrow confidence peak.
    terrain_score = np.mean(normalized, axis=0)
    combined = terrain_score - prior
    # Numerically equal terrain scores must favor the existing location.
    tied = np.flatnonzero(valid & np.isclose(terrain_score, np.max(terrain_score),
                                            atol=1e-9, rtol=1e-7))
    best = int(tied[np.argmin(radius[tied])])
    regularized_best = int(np.argmax(combined))
    individual = [int(np.argmax(n)) for n in normalized]
    disagreement = max(float(np.linalg.norm(shifts[i] - shifts[j])) for i in individual for j in individual)
    d = shifts[best]
    normgain = float(np.mean([n[best] for n in normalized]))
    near = valid & (terrain_score >= terrain_score[best] - 0.10)
    peak_width = float(np.max(np.linalg.norm(shifts[near] - d, axis=1)))
    supporting = np.mean([s["arcs"][best] - s["arcs"][zi] for s in scores], axis=0)
    supported_arcs = int(np.count_nonzero(supporting > 0.002))
    mean_rim = float(np.mean([s["rim"][best] for s in scores]))
    relief = float(np.mean([s["relief"][best] for s in scores]))
    # Actual native grid centres inside polygon: interpolation samples are not independent cells.
    res = terrain.resolution
    bx0, by0, bx1, by1 = poly.bounds
    cells_x = np.arange(np.floor(bx0/res), np.ceil(bx1/res)) * res + res/2
    cells_y = np.arange(np.floor(by0/res), np.ceil(by1/res)) * res + res/2
    cx, cy = np.meshgrid(cells_x, cells_y)
    native_cells = int(np.count_nonzero(contains_xy(poly, cx, cy)))
    record.update({
        "proposed_east_m": float(d[0]), "proposed_north_m": float(d[1]),
        "displacement_m": float(np.linalg.norm(d)),
        "terrain_best_east_m": float(d[0]), "terrain_best_north_m": float(d[1]),
        "terrain_best_displacement_m": float(np.linalg.norm(d)),
        "normalized_score_gain": normgain,
        "regularized_score_gain": float(combined[best]),
        "prior_sensitive_distance_m": float(np.linalg.norm(shifts[best]-shifts[regularized_best])),
        "scale_disagreement_m": disagreement, "peak_width_m": peak_width,
        "supported_arcs": supported_arcs, "mean_rim_curvature_per_m": mean_rim,
        "signed_feature_relief_m": relief, "independent_interior_cells": native_cells,
        "candidate_slope80": float(np.mean([s["slope80"][best] for s in scores])),
        "baseline_slope80": float(np.mean([s["slope80"][zi] for s in scores])),
        "baseline_raw_scores": [float(s["raw"][zi]) for s in scores],
        "candidate_raw_scores": [float(s["raw"][best]) for s in scores],
        "baseline_rim_curvature_per_m": float(np.mean([s["rim"][zi] for s in scores])),
        "baseline_signed_feature_relief_m": float(np.mean([s["relief"][zi] for s in scores])),
        "scale_proposals_m": [shifts[i].tolist() for i in individual],
        "boundary_sample_count": scores[0]["boundary_samples"],
        "interpolated_interior_samples": scores[0]["interior_samples"],
    })
    reasons = []
    if native_cells < cfg["minimum_independent_interior_cells"]:
        reasons.append("too_few_native_cells")
    if mean_rim < cfg["minimum_boundary_curvature_per_m"] or relief < cfg["minimum_relief_m"]:
        reasons.append("weak_or_inconsistent_landform_evidence")
    if record["shared_nodes"]:
        reasons.append("shared_node_requires_joint_review")
    if disagreement > cfg["maximum_scale_disagreement_m"]:
        reasons.append("smoothing_scales_disagree")
    if record["displacement_m"] >= lim - step / 2:
        reasons.append("optimum_reaches_search_limit")
    if peak_width > 2.0:
        reasons.append("broad_ambiguous_optimum")
    if record["prior_sensitive_distance_m"] > 1.0:
        reasons.append("material_prior_sensitivity")
    if record["displacement_m"] < cfg["minimum_move_m"] or combined[best] < cfg["minimum_normalized_gain"]:
        record["status"] = "keep_current"
        reasons.append("no_material_move_supported")
    elif reasons:
        record["status"] = "insufficient_evidence"
    elif supported_arcs < cfg["minimum_supported_arcs"]:
        record["status"] = "insufficient_evidence"
        reasons.append("improvement_not_supported_on_multiple_arcs")
    else:
        record["status"] = "review_candidate"
        reasons.append("terrain_supports_review_not_verified_ground_truth")
    record["reasons"] = reasons
    if record["status"] == "keep_current":
        # A keep-current proposal is literally zero. Preserve the optimizer's
        # weak/subpixel preference only in explicitly named diagnostic fields.
        record["proposed_east_m"] = 0.0
        record["proposed_north_m"] = 0.0
        record["displacement_m"] = 0.0
    return record

