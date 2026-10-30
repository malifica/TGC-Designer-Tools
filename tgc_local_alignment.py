"""Reviewable local tee/bunker alignment on the existing CFS master grid.

Terrain is read only. The geographic OSM is the immutable source of each run.
Global CFS shifts enter the fit once; exports contain only residual object moves.
No GUI imports or OSM-server operations are performed by this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np
import pyproj

FEATURE_VERSION = "beta7-local-alignment-v3"
PATCH_ID = FEATURE_VERSION
REPORT_SCHEMA_VERSION = 1
MANIFEST_SUFFIX = ".local_alignment.json"
READABLE_MANIFEST_VERSIONS = ("beta7-local-alignment-v1", "beta7-local-alignment-v2", FEATURE_VERSION)
SUPPORTED_KINDS = ("tee", "bunker")


class AlignmentError(ValueError):
    """Inputs or review state cannot satisfy the local correction contract."""


class AlignmentCancelled(AlignmentError):
    """The caller cancelled analysis before any source file was changed."""


def _finite(value, label):
    try:
        number = float(value) if not isinstance(value, bool) else math.nan
    except (TypeError, ValueError, OverflowError):
        number = math.nan
    if not math.isfinite(number):
        raise AlignmentError(label + " must be a finite number.")
    return number


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise AlignmentCancelled("Local alignment cancelled; no OSM or terrain was changed.")


def _progress(callback, percent, message):
    if callback is not None:
        callback(float(percent), str(message))


def _index(root, name):
    result = {}
    for element in root.findall(name):
        key = element.get("id")
        try:
            numeric = int(key)
        except (ValueError, TypeError):
            raise AlignmentError("Source contains an invalid " + name + " ID.")
        if str(numeric) != key or key in result:
            raise AlignmentError("Source contains a duplicate or noncanonical " + name + " ID.")
        result[key] = element
    return result


def _tags(element):
    return {tag.get("k"): tag.get("v") for tag in element.findall("tag")}


def _data_contract(data):
    if not isinstance(data, dict):
        raise AlignmentError("Local alignment requires the loaded CFS terrain dictionary.")
    if bool(data.get("custom_unmatched_osm", False)):
        raise AlignmentError("Local alignment currently requires georeferenced OSM; Custom / Unmatched is unsupported.")
    try:
        z = np.asarray(data["heightmap"]).squeeze()
    except (KeyError, TypeError, ValueError) as exc:
        raise AlignmentError("The loaded project has no numeric heightmap.") from exc
    if z.ndim != 2 or min(z.shape) < 3 or z.dtype.kind not in "fiu":
        raise AlignmentError("The heightmap must be a two-dimensional numeric grid.")
    projection = data.get("projection")
    if projection is None:
        raise AlignmentError("Terrain projection metadata is required.")
    try:
        projection = projection if isinstance(projection, pyproj.Proj) else pyproj.Proj(projection)
        crs = projection.crs
    except Exception as exc:
        raise AlignmentError("Terrain projection metadata cannot be read.") from exc
    # Use the exact already-normalized Proj object consumed by CFS/import.
    if not crs.is_projected or len(crs.axis_info) < 2 or any(
            abs(axis.unit_conversion_factor - 1.) > 1e-12 for axis in crs.axis_info[:2]):
        raise AlignmentError("Local alignment requires the existing projected terrain CRS in meters.")
    grid = data.get("master_grid")
    if not isinstance(grid, dict):
        from cfs_georef import get_master_grid
        grid = get_master_grid(data, z, printf=lambda *_: None)
    grid = copy.deepcopy(grid)
    if grid.get("row_order") != "south_up_internal" or grid.get("origin_semantics") != "southwest_cell_edge":
        raise AlignmentError("Local alignment requires the CFS southwest-cell-edge / south-up grid.")
    for key in ("resolution", "min_x", "min_y"):
        grid[key] = _finite(grid.get(key), "Grid " + key)
    if grid["resolution"] <= 0:
        raise AlignmentError("Grid resolution must be positive.")
    if (grid.get("rows"), grid.get("cols")) != z.shape:
        raise AlignmentError("Terrain dimensions differ from the CFS master grid.")
    for key, count, origin in (("max_x", z.shape[1], grid["min_x"]), ("max_y", z.shape[0], grid["min_y"])):
        expected = origin + count * grid["resolution"]
        if key in grid and abs(_finite(grid[key], "Grid " + key) - expected) > 1e-6:
            raise AlignmentError("Terrain bounds differ from the CFS master grid.")
        grid[key] = expected
    if "image_scale" in data and abs(_finite(data["image_scale"], "Image scale") - grid["resolution"]) > 1e-9:
        raise AlignmentError("Heightmap image scale differs from the master grid.")
    if grid.get("xy_units", "meters") not in ("meters", "metres", "m"):
        raise AlignmentError("Local alignment requires a grid measured in meters.")
    if grid.get("crs_wkt"):
        try:
            recorded = pyproj.Proj(grid["crs_wkt"]).crs
        except Exception as exc:
            raise AlignmentError("Master-grid CRS metadata cannot be read.") from exc
        if not recorded.equals(crs, ignore_axis_order=True):
            raise AlignmentError("Loaded terrain projection differs from the master-grid CRS.")
    else:
        grid["crs_wkt"] = crs.to_wkt()
    if not np.any(np.isfinite(z)):
        raise AlignmentError("Terrain contains no finite elevation cells.")
    return z, grid, projection


def terrain_signature(data):
    """Content signature of the exact in-memory grid/projection being reviewed."""
    z, grid, projection = _data_contract(data)
    canonical_z = np.ascontiguousarray(z, dtype="<f8")
    # Normalize irrelevant NaN payload bits while retaining actual missing cells.
    if np.any(np.isnan(canonical_z)):
        canonical_z = canonical_z.copy()
        canonical_z[np.isnan(canonical_z)] = np.nan
    height_hash = hashlib.sha256(_canonical(list(z.shape)) + canonical_z.tobytes()).hexdigest()
    return {
        "heightmap_sha256": height_hash,
        "grid_sha256": _digest(grid),
        "projection_sha256": hashlib.sha256(projection.crs.to_wkt().encode("utf-8")).hexdigest(),
        "grid_shape": list(z.shape),
    }


def _report_digest(report):
    return _digest({key: value for key, value in report.items() if key != "report_sha256"})


def manifest_path(osm_path):
    path = Path(osm_path)
    return path.with_name(path.name + MANIFEST_SUFFIX)


def _lineage(source, source_hash):
    path = manifest_path(source)
    if not path.exists():
        return {"applied_way_ids": [], "applied_target_ids": [], "original_source_osm_path": str(source.resolve()),
                "original_input_osm_sha256": source_hash}
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise AlignmentError("The corrected OSM companion manifest cannot be read.") from exc
    if (not isinstance(record, dict) or record.get("feature_version") not in READABLE_MANIFEST_VERSIONS
            or record.get("manifest_schema_version") != REPORT_SCHEMA_VERSION
            or record.get("output_osm_sha256") != source_hash):
        raise AlignmentError("The corrected OSM companion manifest does not match this source; start from its original OSM.")
    recorded_digest = record.get("manifest_sha256")
    if recorded_digest != _digest({k: v for k, v in record.items() if k != "manifest_sha256"}):
        raise AlignmentError("The corrected OSM companion manifest has changed; start from its original OSM.")
    ids = record.get("applied_way_ids")
    if not isinstance(ids, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in ids) or len(ids) != len(set(ids)):
        raise AlignmentError("The corrected OSM manifest has invalid applied feature IDs.")
    targets = record.get("applied_target_ids", [str(wid) for wid in ids])
    if not isinstance(targets, list) or any(not isinstance(sid, str) for sid in targets) or len(targets) != len(set(targets)):
        raise AlignmentError("The corrected OSM manifest has invalid applied target IDs.")
    return {"applied_way_ids": ids, "applied_target_ids": targets,
            "original_source_osm_path": record["original_source_osm_path"],
            "original_input_osm_sha256": record["original_input_osm_sha256"],
            "parent_manifest_sha256": recorded_digest}


def _inventory(raw, grid, projection, kinds, cancel_event=None):
    from shapely.geometry import Polygon, Point, box
    from shapely.validation import explain_validity
    from tgc_cfs_display import importer_transformer

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AlignmentError("The selected OSM XML cannot be parsed.") from exc
    if root.tag != "osm":
        raise AlignmentError("The selected source must be OSM XML.")
    nodes, ways, relations = (_index(root, name) for name in ("node", "way", "relation"))
    users, members, node_members = defaultdict(set), defaultdict(list), defaultdict(list)
    for wid, way in ways.items():
        for nd in way.findall("nd"):
            users[nd.get("ref")].add(wid)
    for rid, relation in relations.items():
        for member in relation.findall("member"):
            entry = {"relation_id": int(rid), "role": member.get("role", ""), "tags": _tags(relation)}
            if member.get("type") == "way":
                members[member.get("ref")].append(entry)
            elif member.get("type") == "node":
                node_members[member.get("ref")].append(entry)
    transform = importer_transformer(projection)
    edge = np.array([grid["min_x"], grid["min_y"]])
    coords = {}

    def coordinates(refs):
        missing = [nid for nid in refs if nid not in nodes]
        if missing:
            raise AlignmentError("missing_osm_nodes")
        unresolved = list(dict.fromkeys(nid for nid in refs if nid not in coords))
        if unresolved:
            ll = np.array([[_finite(nodes[nid].get("lon"), "Longitude"),
                            _finite(nodes[nid].get("lat"), "Latitude")] for nid in unresolved])
            if np.any(np.abs(ll[:, 0]) > 180) or np.any(np.abs(ll[:, 1]) > 90):
                raise AlignmentError("invalid_geographic_coordinates")
            xy = np.column_stack(transform.transform(ll[:, 0], ll[:, 1], errcheck=True)) - edge
            if not np.all(np.isfinite(xy)):
                raise AlignmentError("nonfinite_projected_coordinates")
            coords.update(zip(unresolved, xy.tolist()))
        return [coords[nid] for nid in refs]

    courses = []
    for wid, way in ways.items():
        tags = _tags(way)
        if tags.get("leisure") == "golf_course":
            refs = [nd.get("ref") for nd in way.findall("nd")]
            try:
                poly = Polygon(coordinates(refs))
                if poly.is_valid and not poly.is_empty:
                    courses.append((poly.area, poly, tags.get("name", "")))
            except Exception:
                pass
    courses.sort(key=lambda item: item[0])
    bounds = box(0., 0., grid["cols"] * grid["resolution"], grid["rows"] * grid["resolution"])
    features = []
    for wid, way in ways.items():
        _cancel(cancel_event)
        tags = _tags(way)
        kind = tags.get("golf")
        kind_from_relation = False
        if kind not in kinds:
            related = [m for m in members[wid] if m["tags"].get("golf") in kinds]
            if not related:
                continue
            kind = related[0]["tags"]["golf"]
            kind_from_relation = True
        refs = [nd.get("ref") for nd in way.findall("nd")]
        try:
            if any(str(int(nid)) != nid for nid in refs):
                raise ValueError("Noncanonical node reference")
        except (TypeError, ValueError) as exc:
            raise AlignmentError("OSM way " + wid + " contains a missing or invalid node reference.") from exc
        shared = [{"node_id": int(nid), "other_way_ids": sorted(int(v) for v in users[nid] - {wid})}
                  for nid in dict.fromkeys(refs) if users[nid] - {wid}]
        node_relations = [{"node_id": int(nid), "memberships": node_members[nid]}
                          for nid in dict.fromkeys(refs) if node_members[nid]]
        reasons = []
        if shared:
            reasons.append("shared_node_requires_joint_review")
        if members[wid] or node_relations:
            reasons.append("relation_member_requires_joint_review")
        feature = {"id": "way/" + wid, "way_id": int(wid), "kind": kind,
                   "tags": tags, "node_ids": [int(v) for v in refs], "coords_m": [],
                   "shared_nodes": shared, "relation_memberships": members[wid],
                   "node_relation_memberships": node_relations, "kind_from_relation": kind_from_relation,
                   "topology_reasons": reasons, "course_name": "", "geometry_valid": False}
        if len(refs) < 4 or refs[0] != refs[-1] or len(set(refs[:-1])) != len(refs) - 1:
            reasons.append("closed_unique_ring_required")
        try:
            xy = coordinates(refs)
            poly = Polygon(xy)
            feature.update(coords_m=xy, centroid_m=list(poly.centroid.coords[0]),
                           area_m2=float(poly.area), bounds_m=list(poly.bounds))
            if not poly.is_valid or poly.is_empty or poly.area <= 1e-6:
                reasons.append("invalid_polygon")
                feature["validity"] = explain_validity(poly)
            else:
                feature["geometry_valid"] = True
                feature["inside_grid"] = bool(bounds.covers(poly))
                for _, course_poly, name in courses:
                    if course_poly.covers(poly.centroid):
                        feature["course_name"] = name
                        break
        except Exception as exc:
            reasons.append(str(exc) if isinstance(exc, AlignmentError) else "unusable_polygon_coordinates")
        features.append(feature)
    from tgc_local_alignment_topology import augment_inventory
    features = augment_inventory(raw, grid, projection, features)
    return features, {"nodes": len(nodes), "ways": len(ways), "relations": len(relations)}


def _manual_eligibility(feature):
    # TGC_BETA7_ALL_FEATURES_V6: explicit whole-boundary edits, not auto-fit guesses.
    from tgc_local_alignment_topology import manual_eligibility
    return manual_eligibility(feature)


def _manual_shift(feature, grid, nudge, east_m, north_m):
    """Validate a residual against reviewed geometry; permit a zero preview."""
    allowed, reason = _manual_eligibility(feature)
    if not allowed or feature.get("manual_movable") is not True:
        raise AlignmentError(reason or feature.get("manual_reason") or "This object is not eligible for manual movement.")
    shift = (_finite(east_m, "Manual east movement"), _finite(north_m, "Manual north movement"))
    width = _finite(grid.get("cols"), "Grid columns") * _finite(grid.get("resolution"), "Grid resolution")
    height = _finite(grid.get("rows"), "Grid rows") * _finite(grid.get("resolution"), "Grid resolution")
    if not math.isfinite(width) or not math.isfinite(height) or min(width, height) <= 0:
        raise AlignmentError("The reviewed terrain bounds are invalid; analyze again.")
    if not isinstance(nudge, (tuple, list)) or len(nudge) != 2:
        raise AlignmentError("The reviewed CFS nudge must contain E/W and N/S values.")
    nudge = [_finite(value, "Reviewed CFS nudge") for value in nudge]
    with np.errstate(over="ignore", invalid="ignore"):
        displayed = np.asarray(feature["coords_m"], dtype=float) + nudge + shift
    tolerance = 1e-6
    if not np.all(np.isfinite(displayed)):
        raise AlignmentError("The manual move would create nonfinite coordinates.")
    if feature.get("kind") in {"rough", "heavyrough", "wood"}:
        return shift
    if (np.any(displayed < -tolerance)
            or np.any(displayed[:, 0] > width + tolerance)
            or np.any(displayed[:, 1] > height + tolerance)):
        raise AlignmentError("The manual move would place part of this object outside the terrain bounds, including the current CFS shift.")
    return shift


def validate_manual_offset(report, way_id, east_m, north_m):
    """Return normalized (east, north) meters or raise a readable AlignmentError.

    The offset replaces the detector proposal and starts at the analyzed source
    geometry. Zero is allowed for preview; export requires a nonzero movement.
    This read-only check does not replace export's live-source/terrain checks.
    """
    from tgc_local_alignment_export import _ids

    if (not isinstance(report, dict) or report.get("feature_version") != FEATURE_VERSION
            or report.get("schema_version") != REPORT_SCHEMA_VERSION):
        raise AlignmentError("This local-alignment report belongs to a different engine version.")
    if report.get("report_sha256") != _report_digest(report):
        raise AlignmentError("The analyzed report changed; analyze the current source again.")
    wid = _ids([way_id])[0]
    features = [feature for feature in report.get("features", [])
                if str(feature.get("selection_id", feature.get("way_id"))) == wid]
    if len(features) != 1:
        raise AlignmentError("The selected way must appear exactly once in the analyzed report.")
    return _manual_shift(features[0], report.get("grid", {}), report.get("global_nudge_m"), east_m, north_m)


def validate_manual_offsets(report, overrides):
    """Validate a whole preview group without modifying the report or drafts."""
    from tgc_local_alignment_export import _ids
    if not isinstance(overrides, dict):
        raise AlignmentError("Manual offsets must map target IDs to E/W and N/S values.")
    if (not isinstance(report, dict) or report.get("feature_version") != FEATURE_VERSION
            or report.get("schema_version") != REPORT_SCHEMA_VERSION):
        raise AlignmentError("This local-alignment report belongs to a different engine version.")
    if report.get("report_sha256") != _report_digest(report):
        raise AlignmentError("The analyzed report changed; analyze the current source again.")
    features = {}
    for feature in report.get("features", []):
        sid = str(feature.get("selection_id", feature.get("way_id")))
        if sid in features:
            raise AlignmentError("The selected target must appear exactly once in the analyzed report.")
        features[sid] = feature
    normalized = {}
    for key, value in overrides.items():
        sid = _ids([key])[0]
        if sid in normalized or not isinstance(value, dict) or set(value) != {"east_m", "north_m"}:
            raise AlignmentError("Manual offsets need one E/W and N/S pair for each target.")
        if sid not in features:
            raise AlignmentError("The selected target must appear exactly once in the analyzed report.")
        east, north = _manual_shift(features[sid], report.get("grid", {}), report.get("global_nudge_m"),
                                   value["east_m"], value["north_m"])
        normalized[sid] = {"east_m": east, "north_m": north}
    return normalized


def analyze(data, osm_file, shift_ew=0, shift_ns=0, search_radius_m=4,
            kinds=SUPPORTED_KINDS, progress_callback=None, cancel_event=None,
            *, custom_unmatched_osm=False):
    """Return explicit review proposals; never modify OSM, terrain, or masks."""
    from tgc_local_alignment_detector import CONFIG, Terrain, analyse_feature

    started = time.perf_counter()
    _cancel(cancel_event)
    if custom_unmatched_osm:
        raise AlignmentError("Local alignment currently requires georeferenced OSM; Custom / Unmatched is unsupported.")
    nudge = [_finite(shift_ew, "CFS E/W shift"), _finite(shift_ns, "CFS N/S shift")]
    radius = _finite(search_radius_m, "Search radius")
    if not 1.0 <= radius <= 8.0 or abs(radius * 2 - round(radius * 2)) > 1e-9:
        raise AlignmentError("Search radius must be from 1 to 8 meters in half-meter increments.")
    if isinstance(kinds, str):
        kinds = (kinds,)
    kinds = tuple(kinds)
    if not kinds or len(set(kinds)) != len(kinds) or any(k not in SUPPORTED_KINDS for k in kinds):
        raise AlignmentError("Local alignment supports tees and bunkers only.")
    source = Path(osm_file).resolve()
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    lineage = _lineage(source, source_hash)
    _progress(progress_callback, 2, "Checking terrain grid and source geometry...")
    z, grid, projection = _data_contract(data)
    signature = terrain_signature(data)
    signature.update(input_osm_sha256=source_hash, global_nudge_m=nudge)
    inventory, source_counts = _inventory(raw, grid, projection, kinds, cancel_event)
    _cancel(cancel_event)
    _progress(progress_callback, 10, "Preparing terrain evidence for tees and bunkers...")
    terrain = Terrain(z, grid["resolution"])
    config = copy.deepcopy(CONFIG)
    config["search_radius_m"] = radius
    applied = set(lineage["applied_way_ids"])
    features = []
    for index, original in enumerate(inventory):
        _cancel(cancel_event)
        feature = copy.deepcopy(original)
        if feature["coords_m"]:
            fit = np.asarray(feature["coords_m"]) + nudge
            feature["fit_coords_m"] = fit.tolist()
            fit_feature = copy.deepcopy(feature)
            fit_feature["coords_m"] = fit.tolist()
            fit_feature["centroid_m"] = (np.asarray(feature.get("centroid_m", [0., 0.])) + nudge).tolist()
        else:
            fit = np.empty((0, 2))
            fit_feature = feature
            feature["fit_coords_m"] = []
        blocked = list(feature["topology_reasons"])
        if feature.get("manual_only") or feature["kind"] not in SUPPORTED_KINDS:
            status = "manual_only"
            # General surfaces/routes use their full original geometry in preview.
            # Do not pass them through tee/bunker fitting or a closed-polygon fit.
            fit = np.asarray(original.get("coords_m", []), dtype=float)
            if fit.ndim == 2 and fit.shape[1] == 2 and np.all(np.isfinite(fit)):
                fit = fit + np.asarray(nudge, dtype=float)
            else:
                fit = np.empty((0, 2))
            feature["fit_coords_m"] = fit.tolist()
            blocked = list(feature["topology_reasons"])
        elif feature["way_id"] in applied:
            status = "already_corrected"
            blocked.append("previously_reviewed_local_correction")
        elif blocked:
            status = "unsupported_topology"
        else:
            status = None
        if status:
            result = {"status": status, "reasons": blocked, "proposed_east_m": 0.,
                      "proposed_north_m": 0., "displacement_m": 0., "accepted_by_default": False}
        else:
            result = analyse_feature(terrain, fit_feature, config)
        feature.update(result)
        feature["coords_m"] = original["coords_m"]
        feature["node_ids"] = original["node_ids"]
        feature["shared_nodes"] = original["shared_nodes"]
        feature["global_nudge_m"] = list(nudge)
        feature["movable"] = bool(feature["status"] == "review_candidate" and not blocked)
        feature["manual_movable"], feature["manual_reason"] = _manual_eligibility(original)
        delta = np.array([feature["proposed_east_m"], feature["proposed_north_m"]])
        feature["proposed_coords_m"] = (fit + delta).tolist() if len(fit) else []
        if "centroid_m" in original:
            feature["centroid_m"] = (np.array(original["centroid_m"]) + nudge).tolist()
        features.append(feature)
        _progress(progress_callback, 10 + 85 * (index + 1) / max(1, len(inventory)),
                  "Prepared %d of %d objects and manual rough boundaries" % (index + 1, len(inventory)))
    _cancel(cancel_event)
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise AlignmentError("The selected OSM changed during analysis; analyze it again.")
    if terrain_signature(data) != {k: v for k, v in signature.items() if k not in ("input_osm_sha256", "global_nudge_m")}:
        raise AlignmentError("Terrain changed during analysis; analyze it again.")
    report = {
        "schema_version": REPORT_SCHEMA_VERSION, "feature_version": FEATURE_VERSION,
        "source_osm_path": str(source), "input_osm_sha256": source_hash,
        "original_source_osm_path": lineage["original_source_osm_path"],
        "original_source_path": lineage["original_source_osm_path"],
        "original_input_osm_sha256": lineage["original_input_osm_sha256"],
        "original_source_osm_sha256": lineage["original_input_osm_sha256"],
        "lineage": lineage, "signature": signature, "grid": grid,
        "global_nudge_m": nudge, "config": config, "kinds": list(kinds),
        "inventory": inventory, "features": features,
        "summary": {"counts": dict(Counter(f["status"] for f in features)),
                    "features_evaluated": sum(f["kind"] in SUPPORTED_KINDS for f in features),
                    "rough_boundaries_manual_only": sum(f["kind"] == "rough" for f in features),
                    "movable_features": sum(f["movable"] for f in features),
                    "manual_movable_features": sum(f["manual_movable"] for f in features),
                    "accepted_by_default": 0, "source_counts": source_counts,
                    "input_files_modified": False, "elapsed_seconds": round(time.perf_counter() - started, 3)},
        "limitations": ["Terrain scores rank review proposals; they are not probabilities or survey measurements.",
                        "Half-meter search steps interpolate the source raster; they do not increase its accuracy.",
                        "Manual edits translate whole surface/relation boundaries and routes; they do not deform vertices or fit radial distortion."]}
    report["report_sha256"] = _report_digest(report)
    _progress(progress_callback, 100, "Local alignment proposals ready for review.")
    return report


analyse = analyze


def apply_reviewed(report, accepted_ids, output_path, current_data=None,
                   current_nudge=None, current_osm_file=None, *, manual_overrides=None):
    from tgc_local_alignment_export import apply_reviewed as export
    return export(report, accepted_ids, output_path, current_data=current_data,
                  current_nudge=current_nudge, current_osm_file=current_osm_file,
                  manual_overrides=manual_overrides)


def self_check():
    """Exercise real numerical fitting + reviewed export in a temporary project."""
    import tempfile
    from shapely import geos_version_string
    from tgc_cfs_display import importer_transformer

    resolution, size = 2., 96
    xx, yy = np.meshgrid((np.arange(size) + .5) * resolution, (np.arange(size) + .5) * resolution)
    radial = np.hypot(xx - 80., yy - 80.)
    t = np.clip((12. - radial) / 4., 0., 1.)
    z = 100. - 2. * t * t * (3. - 2. * t) + .25 * np.exp(-.5 * ((radial - 12.) / 1.) ** 2)
    angle = np.linspace(0, 2 * np.pi, 96, endpoint=False)
    ring = np.column_stack([80. + 12. * np.cos(angle), 80. + 12. * np.sin(angle)])
    nudge = [1., -.5]
    source_xy = ring + np.array([3., -2.]) - nudge
    projection = pyproj.Proj("EPSG:32611")
    forward = importer_transformer(projection)
    min_x, min_y = 576000., 5497500.
    lon0, lat0 = forward.transform(min_x, min_y, direction="INVERSE")
    grid = {"version": 1, "resolution": resolution, "rows": size, "cols": size,
            "min_x": min_x, "min_y": min_y, "max_x": min_x + size * resolution,
            "max_y": min_y + size * resolution, "crs_wkt": projection.crs.to_wkt(),
            "row_order": "south_up_internal", "origin_semantics": "southwest_cell_edge",
            "lower_left_latlon": [lat0, lon0], "xy_units": "meters"}
    data = {"heightmap": z, "projection": projection, "master_grid": grid, "image_scale": resolution}
    with tempfile.TemporaryDirectory(prefix="tgc-local-alignment-check-") as temporary:
        folder = Path(temporary)
        source = folder / "source.osm"
        lines = ['<?xml version="1.0"?>', '<osm version="0.6">']
        for index, (x, y) in enumerate(source_xy, 1):
            lon, lat = forward.transform(x + min_x, y + min_y, direction="INVERSE")
            lines.append('<node id="%d" lon="%.12f" lat="%.12f"/>' % (index, lon, lat))
        lines.append('<way id="101">' + ''.join('<nd ref="%d"/>' % i for i in list(range(1, 97)) + [1]) + '<tag k="golf" v="bunker"/></way>')
        lines.append('</osm>')
        source.write_text('\n'.join(lines), encoding="utf-8")
        source_bytes = source.read_bytes()
        report = analyze(data, source, *nudge)
        feature = report["features"][0]
        delta = np.array([feature["proposed_east_m"], feature["proposed_north_m"]])
        if not feature["movable"] or np.linalg.norm(delta - [-3., 2.]) > 1.:
            raise AlignmentError("Numerical local-alignment fixture did not recover its known displacement.")
        result = apply_reviewed(report, [101], folder / "corrected.osm", current_data=data,
                                current_nudge=nudge, current_osm_file=source)
        if source.read_bytes() != source_bytes or result["changed_nodes"] != 96:
            raise AlignmentError("Reviewed export changed its source or node count.")
        old = ET.fromstring(source_bytes).find("node")
        new = ET.fromstring(Path(result["output"]).read_bytes()).find("node")
        p0 = np.array(forward.transform(float(old.get("lon")), float(old.get("lat"))))
        p1 = np.array(forward.transform(float(new.get("lon")), float(new.get("lat"))))
        if np.linalg.norm((p1 - p0) - delta) > 1e-5:
            raise AlignmentError("Local export applied global CFS shift more than once.")
        repeated = analyze(data, result["output"], *nudge)
        if repeated["features"][0]["movable"] or repeated["features"][0]["status"] != "already_corrected":
            raise AlignmentError("Already reviewed feature was offered for stacked automatic correction.")
        manual_delta = validate_manual_offset(repeated, 101, 1.25, -.75)
        refined = apply_reviewed(repeated, [101], folder / "refined.osm", current_data=data,
                                 current_nudge=nudge, current_osm_file=result["output"],
                                 manual_overrides={101: {"east_m": manual_delta[0], "north_m": manual_delta[1]}})
        moved = ET.fromstring(Path(refined["output"]).read_bytes()).find("node")
        p2 = np.array(forward.transform(float(moved.get("lon")), float(moved.get("lat"))))
        if (np.linalg.norm((p2 - p1) - manual_delta) > 1e-5
                or refined["accepted_features"][0]["correction_method"] != "manual"
                or refined["original_source_osm_path"] != str(source.resolve())
                or source.read_bytes() != source_bytes):
            raise AlignmentError("Manual refinement failed its residual-only export or original-source lineage check.")
        refined_manifest = json.loads(Path(refined["manifest"]).read_text(encoding="utf-8"))
        if refined_manifest["parent_manifest_sha256"] != repeated["lineage"]["parent_manifest_sha256"]:
            raise AlignmentError("Manual refinement did not retain its parent correction history.")
    return {"ok": True, "feature_version": FEATURE_VERSION, "geos": geos_version_string,
            "synthetic_residual_m": delta.tolist(), "global_nudge_retained_m": nudge,
            "manual_refinement_checked": True, "manual_residual_m": list(manual_delta)}
