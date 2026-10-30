#!/usr/bin/env python3
"""Publish reviewed residual translations to a separate OSM copy and manifest."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.parsers import expat


from tgc_local_alignment import AlignmentError

CorrectionError = AlignmentError

def _finite(value, label):
    try:
        number = float(value) if not isinstance(value, bool) else math.nan
    except (TypeError, ValueError, OverflowError):
        number = math.nan
    if not math.isfinite(number):
        raise CorrectionError(f"{label} must be a finite number.")
    return number


def _ids(value):
    parts = value.split(",") if isinstance(value, str) else list(value or [])
    result = []
    for part in parts:
        text = str(part).strip()
        if not text:
            continue
        rough_way = re.fullmatch(r"rough-way:(-?[0-9]+)", text)
        rough_ring = re.fullmatch(r"rough-ring:(-?[0-9]+):(outer|inner):([0-9]+)", text)
        surface_way = re.fullmatch(r"surface-way:(-?[0-9]+)", text)
        surface_ring = re.fullmatch(r"surface-ring:(-?[0-9]+):(outer|inner):([0-9]+)", text)
        if re.fullmatch(r"-?[0-9]+", text):
            text = str(int(text))
        elif surface_way:
            text = "surface-way:" + str(int(surface_way.group(1)))
        elif surface_ring:
            text = "surface-ring:%d:%s:%d" % (int(surface_ring.group(1)), surface_ring.group(2), int(surface_ring.group(3)))
        elif rough_way:
            text = "rough-way:" + str(int(rough_way.group(1)))
        elif rough_ring:
            text = "rough-ring:%d:%s:%d" % (int(rough_ring.group(1)), rough_ring.group(2), int(rough_ring.group(3)))
        else:
            raise CorrectionError(f"Invalid explicit way ID: {text!r}.")
        if text in result:
            raise CorrectionError(f"Way {text} was accepted more than once.")
        result.append(text)
    if not result:
        raise CorrectionError("Select at least one eligible proposal; no file was written.")
    return result


def _index(root, kind):
    result = {}
    for element in root.findall(kind):
        key = element.get("id")
        if key is None or key in result:
            raise CorrectionError(f"Source contains a missing or duplicate {kind} ID.")
        result[key] = element
    return result


def _signature(element):
    # Attribute spelling/order, comments and whitespace are additionally protected
    # by replacing only numeric coordinate spans in the original bytes.
    attributes = tuple(sorted((k, v) for k, v in element.attrib.items()
                              if element.tag != "node" or k not in {"lat", "lon"}))
    return (element.tag, attributes, element.text, element.tail,
            tuple(_signature(child) for child in element))


_ATTRIBUTE = re.compile(rb"([A-Za-z_:][A-Za-z0-9_:.-]*)\s*=\s*([\"'])(.*?)\2", re.S)


def _coordinate_spans(raw):
    """Expat locates actual node tags, ignoring node-like text in XML comments."""
    parser = expat.ParserCreate()
    spans, depth = {}, 0

    def start(name, attributes):
        nonlocal depth
        if depth == 1 and name == "node":
            begin = parser.CurrentByteIndex
            end, quote = begin, None
            while end < len(raw):
                byte = raw[end]
                if quote is not None:
                    if byte == quote:
                        quote = None
                elif byte in (34, 39):
                    quote = byte
                elif byte == 62:
                    break
                end += 1
            node_spans = {}
            for match in _ATTRIBUTE.finditer(raw[begin:end + 1]):
                key = match.group(1).decode("ascii")
                if key in {"lat", "lon"}:
                    node_spans[key] = (begin + match.start(3), begin + match.end(3))
            spans[attributes["id"]] = node_spans
        depth += 1

    def finish(_name):
        nonlocal depth
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = finish
    parser.ExternalEntityRefHandler = lambda *_: 0
    parser.Parse(raw, True)
    return spans


def _valid_ring(points, label):
    """Check nonzero area, duplicate coordinates, and crossing/touching edges."""
    x0, y0 = points[0]
    points = [(x - x0, y - y0) for x, y in points]
    count = len(points)
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            if math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-6:
                raise CorrectionError(f"{label} has repeated polygon coordinates.")
    area2 = sum(a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1]))
    if abs(area2) <= 1e-6:
        raise CorrectionError(f"{label} has zero polygon area.")

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def intersects(a, b, c, d):
        eps = 1e-8
        if (max(a[0], b[0]) + eps < min(c[0], d[0]) or
                max(c[0], d[0]) + eps < min(a[0], b[0]) or
                max(a[1], b[1]) + eps < min(c[1], d[1]) or
                max(c[1], d[1]) + eps < min(a[1], b[1])):
            return False
        ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
        return (min(ab_c, ab_d) <= eps and max(ab_c, ab_d) >= -eps and
                min(cd_a, cd_b) <= eps and max(cd_a, cd_b) >= -eps)

    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if intersects(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count]):
                raise CorrectionError(f"{label} has a self-intersecting polygon.")


def _stage(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        # The context manager has closed the handle, including on Windows.
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _publish_no_replace(temporary, destination):
    """Publish complete bytes without a race that could overwrite another file."""
    try:
        os.link(temporary, destination)
    except OSError:
        if os.name == "nt" and not destination.exists() and not destination.is_symlink():
            # Windows rename fails if the destination exists, unlike POSIX rename.
            os.rename(temporary, destination)
        else:
            raise
    stat = destination.stat()
    return (stat.st_dev, stat.st_ino)


def apply_reviewed(report, accepted_ids, output_path, current_data=None,
                   current_nudge=None, current_osm_file=None, *, manual_overrides=None):
    """Publish selected residuals, with separately explicit manual overrides.

    Manual offsets replace automatic proposals and may exceed the search radius.
    Only accepted IDs are written. The unchanged global CFS nudge is retained once.
    """
    from tgc_local_alignment import (FEATURE_VERSION, REPORT_SCHEMA_VERSION, _data_contract,
                                     _digest, _inventory, _lineage, _manual_eligibility, _manual_shift, _report_digest,
                                     manifest_path, terrain_signature)
    from tgc_local_alignment_topology import render_translations

    accepted = _ids(accepted_ids)
    if manual_overrides is not None and not isinstance(manual_overrides, dict):
        raise CorrectionError("Manual overrides must map selected way IDs to east_m and north_m values.")
    manual = {}
    for key, value in (manual_overrides or {}).items():
        wid = _ids([key])[0]
        if wid in manual:
            raise CorrectionError("Way " + wid + " has more than one manual override.")
        if wid not in accepted:
            raise CorrectionError("Every manual override must also be an explicitly selected way.")
        if not isinstance(value, dict) or set(value) != {"east_m", "north_m"}:
            raise CorrectionError("Each manual override must contain east_m and north_m values.")
        manual[wid] = (_finite(value["east_m"], "Manual east movement"),
                       _finite(value["north_m"], "Manual north movement"))
    if current_data is None or current_nudge is None or current_osm_file is None:
        raise CorrectionError("Live terrain, CFS nudge, and selected OSM are required before applying a review.")
    if not isinstance(report, dict) or report.get("feature_version") != FEATURE_VERSION or report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise CorrectionError("This local-alignment report belongs to a different engine version.")
    if report.get("report_sha256") != _report_digest(report):
        raise CorrectionError("The analyzed report changed; analyze the current source again.")
    if not isinstance(current_nudge, (tuple, list)) or len(current_nudge) != 2:
        raise CorrectionError("The current CFS nudge must contain E/W and N/S values.")
    nudge = [_finite(v, "Current CFS nudge") for v in current_nudge]
    if nudge != report.get("global_nudge_m"):
        raise CorrectionError("The CFS nudge changed after analysis; analyze again before applying.")
    source = Path(report.get("source_osm_path", "")).resolve()
    if Path(current_osm_file).resolve() != source:
        raise CorrectionError("The selected OSM changed after analysis; analyze its current geometry.")
    output = Path(output_path).absolute()
    manifest = manifest_path(output)
    if (output.resolve() == source or manifest.resolve() == source
            or (output.exists() and os.path.samefile(source, output))):
        raise CorrectionError("Output must be a separate copy; the source OSM cannot be overwritten.")
    if any(path.exists() or path.is_symlink() for path in (output, manifest)):
        raise CorrectionError("Output or companion manifest already exists; choose a new filename.")
    if not output.parent.is_dir():
        raise CorrectionError("Output folder must already exist.")
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != report.get("input_osm_sha256"):
        raise CorrectionError("Source OSM SHA-256 changed after analysis; no corrected copy was written.")
    live_terrain = terrain_signature(current_data)
    signature = dict(live_terrain, input_osm_sha256=source_hash, global_nudge_m=nudge)
    if signature != report.get("signature"):
        raise CorrectionError("Terrain or master grid changed after analysis; analyze again before applying.")
    lineage = _lineage(source, source_hash)
    if lineage != report.get("lineage"):
        raise CorrectionError("The source correction history changed after analysis.")
    _, grid, projection = _data_contract(current_data)
    root = ET.fromstring(raw)
    nodes, ways, relations = (_index(root, name) for name in ("node", "way", "relation"))
    by_target = {}
    for feature in report.get("features", []):
        sid = str(feature.get("selection_id", feature.get("way_id")))
        if sid in by_target:
            raise CorrectionError("A feature appears more than once in the report.")
        by_target[sid] = feature
    fresh_inventory, _ = _inventory(raw, grid, projection, tuple(report.get("kinds", ("tee", "bunker"))))
    fresh = {feature["selection_id"]: feature for feature in fresh_inventory}
    applied = set(lineage["applied_way_ids"])
    moves, selected = {}, []
    radius = _finite(report.get("config", {}).get("search_radius_m"), "Analyzed search radius")
    if not 1 <= radius <= 8:
        raise CorrectionError("The report has an unsupported search radius.")
    for sid in accepted:
        if sid not in fresh or sid not in by_target:
            raise CorrectionError("Every accepted target must exist in both the source and analyzed report.")
        feature, original = by_target[sid], fresh[sid]
        for key in ("selection_id", "target_type", "kind", "way_id", "coords_m", "node_ids", "member_way_ids",
                    "member_indexes", "owned_way_ids", "relation_id", "boundary_role"):
            if feature.get(key) != original.get(key):
                raise CorrectionError("Reviewed boundary geometry or ownership differs from the active source.")
        allowed, reason = _manual_eligibility(original)
        if not allowed:
            raise CorrectionError(reason)
        method = "manual" if sid in manual else "automatic"
        if method == "manual":
            shift = _manual_shift(feature, grid, nudge, *manual[sid])
            if not math.hypot(*shift) > 0:
                raise CorrectionError("A selected manual movement must be nonzero; no file was written.")
        else:
            if (feature.get("status") != "review_candidate" or feature.get("movable") is not True
                    or feature.get("kind") not in ("tee", "bunker") or original.get("topology_reasons")
                    or feature["way_id"] in applied):
                raise CorrectionError("Way " + sid + " is not an eligible reviewed movement.")
            shift = (_finite(feature.get("proposed_east_m"), "Residual east movement"),
                     _finite(feature.get("proposed_north_m"), "Residual north movement"))
            if not 0 < math.hypot(*shift) <= radius + 1e-8:
                raise CorrectionError("Reviewed movement is zero or exceeds its analyzed radius.")
        moves[sid] = shift
        selected.append({"selection_id": sid, "way_id": feature["way_id"], "kind": feature["kind"],
                         "boundary_role": feature.get("boundary_role"), "status": feature["status"],
                         "correction_method": method,
                         "added_east_m": shift[0], "added_north_m": shift[1]})
    edited, topology = render_translations(raw, fresh_inventory, moves, grid, projection)
    output_hash = hashlib.sha256(edited).hexdigest()
    summary = {
        "output": str(output), "manifest": str(manifest), "source_osm_path": str(source),
        "source_unchanged": True, "feature_version": FEATURE_VERSION,
        "input_osm_sha256": source_hash, "output_osm_sha256": output_hash,
        "global_nudge_m": nudge, "accepted_features": selected, **topology,
        "counts": {name: len(root.findall(name)) for name in ("node", "way", "relation")},
        "original_source_osm_path": lineage["original_source_osm_path"],
        "original_source_path": lineage["original_source_osm_path"],
        "original_input_osm_sha256": lineage["original_input_osm_sha256"],
        "original_source_osm_sha256": lineage["original_input_osm_sha256"],
        "applied_way_ids": sorted(applied | {by_target[sid]["way_id"] for sid in accepted
                                            if by_target[sid]["kind"] in ("tee", "bunker")}),
        "applied_target_ids": sorted(set(lineage.get("applied_target_ids", [])) | set(accepted)),
    }
    provenance = dict(summary, manifest_schema_version=REPORT_SCHEMA_VERSION,
                      report_sha256=report["report_sha256"], signature=signature,
                      residual_only=True, parent_manifest_sha256=lineage.get("parent_manifest_sha256"))
    provenance["manifest_sha256"] = _digest(provenance)
    manifest_bytes = (json.dumps(provenance, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    stages, published = [], []
    try:
        stages.append(_stage(manifest, manifest_bytes))
        stages.append(_stage(output, edited))
        if source.read_bytes() != raw or terrain_signature(current_data) != live_terrain:
            raise CorrectionError("Source or terrain changed during export; no corrected copy was written.")
        for temporary, destination in zip(stages, (manifest, output)):
            identity = _publish_no_replace(temporary, destination)
            published.append((destination, identity))
    except BaseException:
        for destination, identity in reversed(published):
            try:
                stat = destination.stat()
                if (stat.st_dev, stat.st_ino) == identity:
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for temporary in stages:
            temporary.unlink(missing_ok=True)
    return summary

