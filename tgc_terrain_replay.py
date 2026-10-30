"""Ordered terrain source reconstruction and explicit replay confidence.

The donor lattice routines are a Python adaptation of the established Adaptive
v0.05 ``converter_native.c`` routines ``infer_spacing_phase``,
``detect_group_grid_rotation`` and ``sample_grid_value``.  A donor lattice is a
model of the imported elevation samples, NOT an exact emulation of the game's
brush alpha textures.  The application must describe it as such.

No soft, irregular or hard brush alpha texture is guessed here.  Individual
brush operations require a caller-supplied ValidatedBrushProfile.  Without one,
their possible influence is marked unresolved; retained elevations in those
cells are diagnostic source elevations and must not define a final shoreline.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Callable, Mapping

import numpy as np


SOURCE_MODEL = "adaptive_v005_donor_lattice"
SOURCE_MODEL_REFERENCE = (
    "Adaptive v0.05 converter_native.c: infer_spacing_phase; "
    "detect_group_grid_rotation; sample_grid_value"
)


@dataclass(frozen=True)
class ValidatedBrushProfile:
    """Explicitly supplied brush alpha with its measured extent convention.

    ``extent_x``/``extent_z`` multiply the serialized X/Z scale to give the
    local support half-extents. ``alpha(u,v)`` returns weights in [0,1], where
    u/v are local coordinates divided by those half-extents.  World-to-local
    yaw follows Adaptive's X/Z frame: u=cos(yaw)*dx-sin(yaw)*dz,
    v=sin(yaw)*dx+cos(yaw)*dz.  ``provenance`` must identify the calibration or
    source of the alpha/extent; a brush name alone is insufficient.

    A profile alone does not establish the relative/local tool's operator.
    Existing Finisher code uses tool1/value0 for a level tap, so treating all
    tool1 stamps as additive deltas is not safe. To enable additive tool1 replay,
    explicitly set ``tool1_semantics='additive_delta'`` and its independently
    validated ``tool1_provenance``. Otherwise every tool1 stroke stays audited.
    """

    name: str
    alpha: Callable[[np.ndarray, np.ndarray], np.ndarray]
    extent_x: float
    extent_z: float
    provenance: str
    tool1_semantics: str | None = None
    tool1_provenance: str | None = None

    def __post_init__(self):
        if not callable(self.alpha):
            raise TypeError("ValidatedBrushProfile.alpha must be callable.")
        if not self.name.strip() or not self.provenance.strip():
            raise ValueError("Brush profiles require a name and explicit provenance.")
        if not all(math.isfinite(v) and v > 0 for v in (self.extent_x, self.extent_z)):
            raise ValueError("Brush profile extents must be finite and positive.")
        if self.tool1_semantics not in (None, "additive_delta"):
            raise ValueError("The supplied tool1 operator is not implemented.")
        if self.tool1_semantics and not (self.tool1_provenance or "").strip():
            raise ValueError("Tool1 replay requires separate operator provenance.")


@dataclass(frozen=True, slots=True)
class TerrainOperation:
    order: int
    layer: str
    index: int
    tool: int | None
    brush_type: int | None
    x: float
    z: float
    sx: float
    sz: float
    rotation_y: float
    value: float
    issue: str | None = None

    @property
    def signature(self):
        if self.issue or self.tool != 0:
            return None
        return (self.layer, self.brush_type, round(self.sx, 2), round(self.sz, 2))


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else float("nan")
    except (TypeError, ValueError, OverflowError):
        return float("nan")


def _integer(value):
    number = _number(value)
    return int(number) if math.isfinite(number) and number == int(number) else None


def _normal_angle(value, period=360.0):
    return (value + period * 0.5) % period - period * 0.5


def _c_round(value):
    """C round(), used by Adaptive, rather than Python's ties-to-even round."""
    value = np.asarray(value)
    return np.copysign(np.floor(np.abs(value) + 0.5), value).astype(np.int64)


def iter_terrain_operations(course):
    """Visit landscape then sculpt arrays, preserving every in-array index.

    This is the layer order used by the existing Python generator/visualizer.
    The source arrays are never sorted or modified.  Unsupported records are
    retained in the audit instead of silently skipped.
    """
    order = 0
    layers = course
    if "height" not in course and "terrainHeight" not in course:
        for key in ("userLayers2", "userLayers"):
            if isinstance(course.get(key), dict):
                layers = course[key]
                break
    for layer in ("terrainHeight", "height"):
        raw = layers.get(layer, [])
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raw = [raw]
        for index, item in enumerate(raw):
            issue = None
            if not isinstance(item, dict):
                item = {}
                issue = "malformed terrain record"
            pos = item.get("position") or {}
            scale = item.get("scale") or {}
            rotation = item.get("rotation") or {}
            if not isinstance(pos, dict):
                pos = {}
            if not isinstance(scale, dict):
                scale = {}
            if not isinstance(rotation, dict):
                rotation = {}
            tool = _integer(item.get("tool", 0))
            brush_type = _integer(item.get("type"))
            x, z = _number(pos.get("x")), _number(pos.get("z"))
            sx, sz = abs(_number(scale.get("x"))), abs(_number(scale.get("z")))
            yaw = _number(rotation.get("y", 0.0))
            value = _number(item.get("value"))
            if not all(math.isfinite(v) for v in (x, z, sx, sz, yaw, value)) or sx <= 0 or sz <= 0:
                issue = issue or "non-finite or missing terrain geometry/value"
            if tool is None or brush_type is None:
                issue = issue or "missing or non-integer tool/brush type"
            tilt = [_number(rotation.get(axis, 0.0)) for axis in ("x", "z")]
            if any(not math.isfinite(v) or abs(v) > 1e-9 for v in tilt):
                issue = issue or "unvalidated terrain tilt"
            if "opacity" in item and _number(item["opacity"]) != 1.0:
                issue = issue or "unvalidated terrain opacity"
            sy = _number(scale.get("y", 1.0))
            if not math.isfinite(sy) or abs(sy - 1.0) > 1e-9:
                issue = issue or "unvalidated vertical brush scale"
            yield TerrainOperation(order, layer, index, tool, brush_type, x, z, sx, sz, yaw, value, issue)
            order += 1


def _infer_spacing_phase(values):
    """Port Adaptive's 2cm clustering and modal centimetre spacing/phase."""
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    if len(ordered) < 4:
        return None
    unique = []
    i = 0
    while i < len(ordered):
        total, count, mean = float(ordered[i]), 1, float(ordered[i])
        j = i + 1
        while j < len(ordered) and abs(float(ordered[j]) - mean) <= 0.020:
            total += float(ordered[j])
            count += 1
            mean = total / count
            j += 1
        unique.append(mean)
        i = j
    unique = np.asarray(unique)
    delta = np.diff(unique)
    delta = delta[(delta >= 0.25) & (delta <= 20.0)]
    if len(delta) == 0:
        return None
    histogram = Counter(int(v) for v in _c_round(delta * 100.0))
    spacing = max(histogram, key=histogram.get) / 100.0
    if spacing <= 0.0:
        return None
    phases = Counter(int(v) for v in _c_round(np.mod(unique, spacing) * 100.0))
    phase = max(phases, key=phases.get) / 100.0
    return spacing, phase


def _donor_rotation(operations):
    angles = _normal_angle(np.asarray([op.rotation_y for op in operations]))
    buckets = _c_round((angles + 180.0) * 10.0)
    counts = np.bincount(buckets, minlength=3601)
    center = -180.0 + int(np.argmax(counts)) / 10.0
    delta = _normal_angle(angles - center)
    accepted = np.abs(delta) <= 0.151
    confidence = float(np.count_nonzero(accepted) / len(angles))
    raw = float(_normal_angle(center + float(np.mean(delta[accepted]))))
    frame = float(_normal_angle(raw, 90.0)) if confidence >= 0.60 else 0.0
    return raw, frame, confidence


@dataclass(slots=True)
class _DonorRun:
    first: TerrainOperation
    last: TerrainOperation
    count: int
    grid: np.ndarray
    spacing: float
    ox: float
    oz: float
    angle: float
    rotation_confidence: float
    alignment_fraction: float
    unique_cells: int

    def metadata(self):
        return {
            "layer": self.first.layer,
            "first_index": self.first.index,
            "last_index": self.last.index,
            "first_order": self.first.order,
            "last_order": self.last.order,
            "brush_type": self.first.brush_type,
            "scale_x": self.first.sx,
            "scale_z": self.first.sz,
            "operation_count": self.count,
            "unique_donor_cells": self.unique_cells,
            "grid_shape": [int(v) for v in self.grid.shape],
            "spacing_m": self.spacing,
            "frame_degrees": self.angle,
            "rotation_confidence": self.rotation_confidence,
            "alignment_fraction": self.alignment_fraction,
            "model": SOURCE_MODEL,
            "exact_game_replay": False,
        }

    def sample_grid(self, xs, zs, active):
        cs, sn = math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle))
        # Same world-to-grid convention as Adaptive's native source.
        xx, zz = xs[None, :], zs[:, None]
        col = (cs * xx - sn * zz - self.ox) / self.spacing
        row = (sn * xx + cs * zz - self.oz) / self.spacing
        col, row = np.broadcast_arrays(col, row)
        c0, r0 = np.floor(col).astype(np.int64), np.floor(row).astype(np.int64)
        dc, dr = col - c0, row - r0
        total = np.zeros(active.shape, dtype=np.float64)
        weight_sum = np.zeros(active.shape, dtype=np.float64)
        missing_corner = np.zeros(active.shape, dtype=bool)
        gh, gw = self.grid.shape
        for di, dj, weight in ((0, 0, (1-dr)*(1-dc)), (1, 0, (1-dr)*dc),
                               (0, 1, dr*(1-dc)), (1, 1, dr*dc)):
            cc, rr = c0 + di, r0 + dj
            required = active & (weight > 0.0)
            inside = required & (cc >= 0) & (cc < gw) & (rr >= 0) & (rr < gh)
            missing_corner |= required & ~inside
            indices = np.flatnonzero(inside)
            if not len(indices):
                continue
            vals = self.grid[rr.ravel()[indices], cc.ravel()[indices]]
            finite = np.isfinite(vals)
            missing_corner.ravel()[indices[~finite]] = True
            indices, vals = indices[finite], vals[finite]
            ww = weight.ravel()[indices]
            total.ravel()[indices] += vals * ww
            weight_sum.ravel()[indices] += ww
        # Unlike the Adaptive donor estimate, shoreline geometry cannot bridge
        # a missing donor corner by renormalizing the remaining corners.
        complete = active & (weight_sum > 0.0) & ~missing_corner
        partial = active & (weight_sum > 0.0) & ~complete
        values = np.full(active.shape, np.nan, dtype=np.float64)
        values[complete] = total[complete] / weight_sum[complete]
        return values, complete, partial


def _make_donor_run(operations, minimum, max_cells):
    if len(operations) < minimum:
        return None
    _raw, angle, rotation_confidence = _donor_rotation(operations)
    points = np.asarray([(op.x, op.z) for op in operations], dtype=np.float64)
    cs, sn = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    u, v = cs * points[:, 0] - sn * points[:, 1], sn * points[:, 0] + cs * points[:, 1]
    axis_x, axis_z = _infer_spacing_phase(u), _infer_spacing_phase(v)
    if axis_x is None or axis_z is None:
        return None
    sx, px = axis_x
    sz, pz = axis_z
    if abs(sx - sz) > 0.05 * max(sx, sz):
        return None
    spacing = 0.5 * (sx + sz)
    cc, rr = _c_round((u-px)/spacing), _c_round((v-pz)/spacing)
    tolerance = max(0.035, spacing * 0.025)
    aligned = (np.abs(u-(px+cc*spacing)) <= tolerance) & (np.abs(v-(pz+rr*spacing)) <= tolerance)
    fraction = float(np.mean(aligned))
    # A same-brush run alone is insufficient: hand strokes must pass regular
    # two-dimensional grid support, as well as this alignment confidence.
    if fraction < 0.98:
        return None
    # Do not absorb even one non-grid operation into the source model.  A
    # mixed run stays in explicit replay/audit rather than silently dropping it.
    if not np.all(aligned):
        return None
    minc, maxc, minr, maxr = int(cc.min()), int(cc.max()), int(rr.min()), int(rr.max())
    width, height = maxc-minc+1, maxr-minr+1
    if width < 3 or height < 3 or width*height > max_cells:
        return None
    flat = (rr-minr)*width+(cc-minc)
    _unique, reverse_ids = np.unique(flat[::-1], return_index=True)
    chosen = len(flat)-1-reverse_ids  # newest serialized value wins per donor cell
    if len(chosen) < minimum:
        return None
    # Avoid treating a series of repeated/linear strokes as a dense 2D donor.
    rows_used = np.bincount(rr[chosen]-minr, minlength=height)
    cols_used = np.bincount(cc[chosen]-minc, minlength=width)
    if np.count_nonzero(rows_used >= 3) < 3 or np.count_nonzero(cols_used >= 3) < 3:
        return None
    grid = np.full((height, width), np.nan, dtype=np.float64)
    values = np.asarray([op.value for op in operations])
    grid.ravel()[flat[chosen]] = values[chosen]
    return _DonorRun(operations[0], operations[-1], len(operations), grid, spacing,
                     px+minc*spacing, pz+minr*spacing, angle, rotation_confidence,
                     fraction, len(chosen))


class TerrainReplay:
    """Visit authored layers in order; reconstruct donors and audit every edit.

    Every result includes ``unresolved``.  Callers MUST intersect that mask
    with their intended water footprint before accepting shoreline geometry.
    No default height of zero, procedural base, blur sigma, or brush profile
    is invented.  Source-only results remain an imported donor model.
    """

    def __init__(self, course, profiles: Mapping[int, ValidatedBrushProfile] | None = None,
                 *, min_donor_stamps=64, max_grid_cells=16_000_000):
        self.profiles = dict(profiles or {})
        for key, profile in self.profiles.items():
            if not isinstance(key, int) or not isinstance(profile, ValidatedBrushProfile):
                raise TypeError("profiles must map integer brush types to ValidatedBrushProfile instances.")
        self.max_grid_cells = int(max_grid_cells)
        self.min_donor_stamps = max(9, int(min_donor_stamps))
        self.operations = tuple(iter_terrain_operations(course))
        self.blur_height = bool(course.get("blurHeight", False))
        self.events = []
        i = 0
        while i < len(self.operations):
            op = self.operations[i]
            sig = op.signature
            if sig is None or op.brush_type in self.profiles:
                self.events.append(op)
                i += 1
                continue
            end = i + 1
            while end < len(self.operations) and self.operations[end].signature == sig:
                end += 1
            run = _make_donor_run(self.operations[i:end], self.min_donor_stamps, self.max_grid_cells)
            if run is None:
                self.events.extend(self.operations[i:end])
            else:
                self.events.append(run)
            i = end
        self.donor_runs = [event for event in self.events if isinstance(event, _DonorRun)]

    @staticmethod
    def _bounds(op, profile=None):
        if not all(math.isfinite(v) for v in (op.x, op.z, op.sx, op.sz, op.rotation_y)) or op.sx <= 0 or op.sz <= 0:
            return None
        # Full scale as half-extent encloses both existing project conventions:
        # Adaptive's half-scale and the visualizer's larger square footprint.
        # This is ONLY an unresolved-area envelope, never a rendered brush.
        rx = op.sx * (profile.extent_x if profile else 1.0)
        rz = op.sz * (profile.extent_z if profile else 1.0)
        cs, sn = abs(math.cos(math.radians(op.rotation_y))), abs(math.sin(math.radians(op.rotation_y)))
        ex, ez = cs*rx+sn*rz, sn*rx+cs*rz
        return (op.x-ex, op.z-ez, op.x+ex, op.z+ez)

    def sample_grid(self, xs_1d, zs_1d, active_mask=None):
        xs, zs = np.asarray(xs_1d, dtype=np.float64), np.asarray(zs_1d, dtype=np.float64)
        for coords in (xs, zs):
            if coords.ndim != 1 or not len(coords) or not np.all(np.isfinite(coords)) or np.any(np.diff(coords) <= 0):
                raise ValueError("sample_grid requires nonempty, finite, strictly increasing 1D axes.")
        shape = (len(zs), len(xs))
        if shape[0]*shape[1] > self.max_grid_cells:
            raise ValueError("Terrain sampling grid exceeds the bounded cell limit.")
        active = np.ones(shape, dtype=bool) if active_mask is None else np.asarray(active_mask, dtype=bool).copy()
        if active.shape != shape:
            raise ValueError("active_mask must have shape (len(zs), len(xs)).")
        elevations = np.full(shape, np.nan, dtype=np.float64)
        unresolved = active.copy()
        cause = np.full(shape, -1, dtype=np.int64)
        source_cells = np.zeros(shape, dtype=bool)
        audit, applied, donor_stats = [], [], []
        excluded = 0
        hx = 0.5*float(np.max(np.diff(xs))) if len(xs) > 1 else 0.0
        hz = 0.5*float(np.max(np.diff(zs))) if len(zs) > 1 else 0.0

        for event in self.events:
            if isinstance(event, _DonorRun):
                values, known, partial = event.sample_grid(xs, zs, active)
                record = event.metadata()
                record["sampled_source_cells"] = int(np.count_nonzero(known))
                record["incomplete_source_cells"] = int(np.count_nonzero(partial))
                record["prior_uncertainty_absorbed_by_source_model"] = int(np.count_nonzero(known & (cause >= 0)))
                donor_stats.append(record)
                elevations[known] = values[known]
                unresolved[known] = False
                cause[known] = -1
                source_cells[known] = True
                # A later grid with some missing corners is not an absent
                # layer. Its surrounding later stamps can change the surface,
                # so the older donor value remains diagnostic, not resolved.
                if np.any(partial):
                    unresolved[partial] = True
                    cause[partial] = event.last.order
                    audit.append({"kind": "donor_run_partial_support", "layer": event.first.layer,
                                  "index": event.first.index, "last_index": event.last.index,
                                  "order": event.last.order, "type": event.first.brush_type,
                                  "tool": 0, "reason": "later donor interpolation has missing corners",
                                  "bbox_m": None, "sampled_affected_cells": int(np.count_nonzero(partial))})
                continue

            op = event
            profile = self.profiles.get(op.brush_type)
            reason = op.issue
            if reason is None and op.tool not in (0, 1):
                reason = "unsupported terrain tool"
            if reason is None and profile is None:
                reason = "brush alpha/extent profile unavailable"
            if reason is None and op.tool == 1 and profile.tool1_semantics != "additive_delta":
                reason = "relative/local tool1 operator has not been independently validated"
            bounds = self._bounds(op, profile)
            if bounds is None:
                x0, x1, z0, z1 = 0, len(xs), 0, len(zs)
            else:
                pad_x, pad_z = (hx, hz) if reason else (0.0, 0.0)
                x0 = int(np.searchsorted(xs, bounds[0]-pad_x, side="left"))
                x1 = int(np.searchsorted(xs, bounds[2]+pad_x, side="right"))
                z0 = int(np.searchsorted(zs, bounds[1]-pad_z, side="left"))
                z1 = int(np.searchsorted(zs, bounds[3]+pad_z, side="right"))
            if x0 >= x1 or z0 >= z1 or not np.any(active[z0:z1, x0:x1]):
                excluded += 1
                continue
            subactive = active[z0:z1, x0:x1]
            subvalue = elevations[z0:z1, x0:x1]
            subunknown = unresolved[z0:z1, x0:x1]
            subcause = cause[z0:z1, x0:x1]
            subsource = source_cells[z0:z1, x0:x1]

            if reason is None:
                angle = math.radians(op.rotation_y)
                cs, sn = math.cos(angle), math.sin(angle)
                dx, dz = xs[x0:x1][None, :]-op.x, zs[z0:z1][:, None]-op.z
                u = (cs*dx-sn*dz)/(op.sx*profile.extent_x)
                v = (sn*dx+cs*dz)/(op.sz*profile.extent_z)
                u, v = np.broadcast_arrays(u, v)
                try:
                    weights = np.broadcast_to(np.asarray(profile.alpha(u, v), dtype=np.float64), subactive.shape)
                    if not np.all(np.isfinite(weights)) or np.any(weights < 0) or np.any(weights > 1):
                        raise ValueError("alpha returned weights outside [0,1]")
                except Exception as error:
                    reason = "validated profile failed: " + str(error)
                else:
                    affected = subactive & (weights > 0)
                    if op.tool == 0:
                        # Any nonzero remnant of an unknown prior surface is
                        # still unknown. Only an actual alpha of 1 replaces it.
                        overwrite = affected & (weights == 1.0)
                        blend = affected & ~overwrite & np.isfinite(subvalue)
                        subvalue[blend] += (op.value-subvalue[blend])*weights[blend]
                        subvalue[overwrite] = op.value
                        subunknown[overwrite] = False
                        subcause[overwrite] = -1
                        subsource[overwrite] = False
                    else:
                        resolved = affected & np.isfinite(subvalue)
                        subvalue[resolved] += op.value*weights[resolved]
                    applied.append({"layer": op.layer, "index": op.index, "order": op.order,
                                    "type": op.brush_type, "tool": op.tool, "profile": profile.name,
                                    "sampled_affected_cells": int(np.count_nonzero(affected))})
            if reason is not None:
                subunknown[subactive] = True
                subcause[subactive] = op.order
                audit.append({"layer": op.layer, "index": op.index, "order": op.order,
                              "type": op.brush_type, "tool": op.tool, "reason": reason,
                              "bbox_m": list(bounds) if bounds else None,
                              "sampled_affected_cells": int(np.count_nonzero(subactive))})

        if self.blur_height and np.any(active):
            unresolved[active] = True
        unresolved &= active
        final_causes = set(int(v) for v in np.unique(cause[unresolved]) if v >= 0)
        for record in audit:
            record["remaining_as_latest_uncertain_influence"] = record["order"] in final_causes
        count = int(np.count_nonzero(unresolved))
        diagnostic_limit = 4096
        diagnostics = {
            "model": SOURCE_MODEL if self.donor_runs else "explicit_brush_profiles",
            "source_reference": SOURCE_MODEL_REFERENCE,
            "exact_game_replay": bool(not self.donor_runs and not count and not self.blur_height),
            "status": "unresolved" if count else ("source_lattice_model" if self.donor_runs else "validated_profile_replay"),
            "operation_order": "terrainHeight array, then height array; each in serialized order",
            "operation_count": len(self.operations),
            "layer_counts": dict(Counter(op.layer for op in self.operations)),
            "donor_runs": donor_stats,
            "resolved_source_model_cells": int(np.count_nonzero(source_cells & active & ~unresolved)),
            "active_cells": int(np.count_nonzero(active)),
            "unresolved_cells": count,
            "no_elevation_cells": int(np.count_nonzero(active & ~np.isfinite(elevations))),
            "excluded_operations_outside_active_grid": excluded,
            "unresolved_operations": audit[:diagnostic_limit],
            "unresolved_operation_count": len(audit),
            "unresolved_operations_truncated": len(audit) > diagnostic_limit,
            "unresolved_brush_type_counts": dict(Counter(str(record["type"]) for record in audit)),
            "remaining_uncertain_operation_orders": sorted(final_causes),
            "validated_profile_operations": applied[:diagnostic_limit],
            "validated_profile_operation_count": len(applied),
            "validated_profiles": {str(key): {"name": value.name, "provenance": value.provenance,
                                                "extent_x": value.extent_x, "extent_z": value.extent_z,
                                                "tool1_semantics": value.tool1_semantics,
                                                "tool1_provenance": value.tool1_provenance}
                                   for key, value in self.profiles.items()},
            "blur_height": self.blur_height,
            "postprocessing_unresolved": ["blurHeight has no validated postprocessor"] if self.blur_height else [],
            "uncertainty_extent_convention": "full serialized scale as conservative bbox half-extent; sampling-cell padding",
            "limitations": [
                "Donor interpolation reproduces imported source samples, not the game's brush-alpha replay.",
                "Missing donor corners are not bridged or assigned zero elevation.",
                "Elevations in unresolved cells are diagnostic only and must not determine a shoreline.",
                "Actual soft and irregular brush profiles are not present in the course file.",
            ],
        }
        return {"elevations": elevations, "unresolved": unresolved, "diagnostics": diagnostics}
