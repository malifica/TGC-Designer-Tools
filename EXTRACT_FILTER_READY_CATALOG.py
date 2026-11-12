#!/usr/bin/env python3
"""Build a nature-only Filter Ready catalog from Designer.course sources.

Reads the source only. The output contains asset identities and normalized local
samples, never the source course's positions, scales, populations or attribution.

Example:
    py EXTRACT_FILTER_READY_CATALOG.py --course "C:\\Inputs\\Source.course" \
        --profile-id my_theme --output "C:\\Outputs\\my_theme.json"

For a profile based on two courses, supply both paths after --course. Their
active individual nature assets are combined once each, without populations.
Trees, shrubs, grass, plants and rocks are included. Props, structures, wildlife,
paths and water generators are omitted.
"""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
import json
import math
from pathlib import Path
import re
import sys
from collections import Counter


ITEM_SAMPLE = {
    "position": {"x": 0.0, "y": "-Infinity", "z": 0.0},
    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
    "scale": {"x": 0.05, "y": 0.05, "z": 0.05},
}
PATH_FIELDS = {"waypoints", "width", "hasCurves", "state", "absoluteY"}
NODE_FIELDS = {"pointOne", "pointTwo", "waypoint", "width"}
PATH_RECORD_FIELDS = {
    "path", "height", "spacingRule", "flexibilityRule", "heightRule", "spacing",
    "disableHeightOffset", "disableSurfaceTexture", "heightOffset",
    "edgeHeightOffset", "water", "isWater",
}
NATURE_CATEGORIES = frozenset({'tree', 'shrub', 'grass', 'plant', 'rock'})


def parse_json_bytes(raw):
    for encoding in ("utf-16", "utf-16-le", "utf-8-sig"):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeError, json.JSONDecodeError):
            continue
    raise ValueError("Could not decode source JSON")


def decode_course(source):
    outer = parse_json_bytes(gzip.decompress(source.read_bytes()))
    if not isinstance(outer, dict):
        raise ValueError("Source archive must contain a JSON object")
    binary = outer.get("binaryData", {})
    if not isinstance(binary, dict):
        raise ValueError("Source archive binaryData must be an object")
    encoded = binary.get("CourseDescription")
    if not isinstance(encoded, str):
        raise ValueError("Source archive has no CourseDescription payload")
    course = parse_json_bytes(gzip.decompress(base64.b64decode(encoded, validate=True)))
    if not isinstance(course, dict):
        raise ValueError("CourseDescription payload must contain a JSON object")
    return course


def category(path, path_only=False):
    if path_only:
        return "path_generator"
    for marker, label in (("/Trees/", "tree"), ("/Bushes/", "shrub"),
                          ("/Grass/", "grass"), ("/Plants/", "plant"),
                          ("/Rocks/", "rock"), ("/Rock/", "rock")):
        if marker in path:
            return label
    return "prop"


def positive_cluster(cluster):
    if not isinstance(cluster, dict):
        raise ValueError("Cluster record must be an object")
    try:
        count = float(cluster.get("count", 0))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Cluster count must be finite numeric data") from exc
    if not math.isfinite(count):
        raise ValueError("Cluster count must be finite numeric data")
    return count > 0


def native_list(value, name):
    result = value.get(name, []) or []
    if not isinstance(result, list):
        raise ValueError("Native placement collection must be an array: " + name)
    return result


def normalize_path_record(record, asset_path):
    """Normalize an observed native objectPaths2 record, without guessing fields."""
    if not isinstance(record, dict) or not isinstance(record.get("path"), dict):
        raise ValueError("Unsupported native objectPaths2 record for " + asset_path)
    if set(record) - PATH_RECORD_FIELDS:
        raise ValueError("Unreviewed native objectPaths2 fields for " + asset_path +
                         ": " + ", ".join(sorted(set(record) - PATH_RECORD_FIELDS)))
    path = record["path"]
    if set(path) - PATH_FIELDS:
        raise ValueError("Unreviewed native path fields for " + asset_path)
    points = path.get("waypoints")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("Native object path needs at least two source waypoints: " + asset_path)
    if not {"width", "hasCurves", "state", "absoluteY"}.issubset(path):
        raise ValueError("Native path schema is missing reviewed fields: " + asset_path)
    if "isWater" not in record:
        raise ValueError("Native object path is missing its water/generator flag: " + asset_path)
    if not isinstance(record["isWater"], bool):
        raise ValueError("Native isWater flag must be boolean: " + asset_path)
    for point in points:
        if not isinstance(point, dict) or set(point) - NODE_FIELDS:
            raise ValueError("Unreviewed native waypoint schema for " + asset_path)
        if not {"pointOne", "pointTwo", "waypoint"}.issubset(point):
            raise ValueError("Missing native waypoint/control fields for " + asset_path)
        for key in ("pointOne", "pointTwo", "waypoint"):
            if not isinstance(point[key], dict) or set(point[key]) != {"x", "y", "z"}:
                raise ValueError("Unreviewed native coordinate schema for " + asset_path)

    sample = copy.deepcopy(record)
    sample_path = sample["path"]
    is_water = record["isWater"]
    if is_water and path["state"] not in (0, 2):
        raise ValueError("Unreviewed native water-path closure state for " + asset_path)
    closed_water = is_water and path["state"] == 2
    coordinates = ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5)) if closed_water else ((0.0, 0.0), (0.5, 0.0))
    nodes = []
    for x, z in coordinates:
        point = copy.deepcopy(points[0])
        for key in ("pointOne", "pointTwo", "waypoint"):
            point[key] = {"x": x, "y": 0.0, "z": z}
        if "width" in point:
            point["width"] = 0.25
        nodes.append(point)
    sample_path["waypoints"] = nodes
    sample_path["width"] = 0.25
    sample_path["hasCurves"] = False
    sample_path["state"] = path["state"] if is_water else 0
    # Retain the native absoluteY and heightRule convention. Zero-height water
    # vertices and wrapper height agree; runtime translates local X/Z only.
    for field in ("height", "heightOffset", "edgeHeightOffset"):
        if field in sample:
            sample[field] = 0.0
    if "spacing" in sample:
        sample["spacing"] = 0.25
    for field in ("disableHeightOffset", "disableSurfaceTexture"):
        if field in sample:
            sample[field] = True
    if "water" in sample:
        if not isinstance(sample["water"], dict) or set(sample["water"]) - {"flowDirection", "flowSpeed"}:
            raise ValueError("Unreviewed native water parameters for " + asset_path)
        if "flowSpeed" in sample["water"]:
            sample["water"]["flowSpeed"] = 0.0
    return sample


def build_catalog(course, profile_id):
    """Build from a decoded course dict or a list of decoded source dicts."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", profile_id):
        raise ValueError("profile-id must be a lowercase identifier using letters, digits and underscores")
    courses = course if isinstance(course, (list, tuple)) else [course]
    if not courses:
        raise ValueError("At least one decoded source course is required")
    groups = []
    collections = []
    for source in courses:
        if not isinstance(source, dict):
            raise ValueError("Decoded source course must be an object")
        collection = next((name for name in ("placedObjects4", "placedObjects3", "placedObjects2")
                           if source.get(name)), "placedObjects4")
        source_groups = source.get(collection, []) or []
        if not isinstance(source_groups, list):
            raise ValueError("Source placement collection must be an array")
        collections.append(collection)
        groups.extend(source_groups)
    merged = {}
    inactive_groups = 0
    zero_only_groups = 0
    non_nature_groups = 0
    path_only_groups = 0
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("Value"), dict):
            raise ValueError("Source placement group must contain a native Value object")
        value = group["Value"]
        items = native_list(value, "items")
        clusters = native_list(value, "clusters")
        positive = any([positive_cluster(item) for item in clusters])
        paths = native_list(value, "objectPaths2")
        splines = native_list(value, "splines")
        if not (items or positive or paths or splines):
            inactive_groups += 1
            zero_only_groups += bool(clusters)
            continue
        key = group.get("Key")
        if not isinstance(key, dict) or not isinstance(key.get("path"), str) or not key["path"].strip():
            raise ValueError("Active source asset requires a native path-based Key")
        path = key["path"]
        if category(path) not in NATURE_CATEGORIES:
            non_nature_groups += 1
            continue
        if not (items or positive):
            # A generator observed only as a path/spline is not a reviewed
            # individual nature object and must not be converted into one.
            path_only_groups += 1
            continue
        if path in merged and merged[path]["key"] != key:
            raise ValueError("Different native Keys share an active path: " + path)
        entry = merged.setdefault(path, {"key": copy.deepcopy(key), "item_supported": False,
                                         "paths": [], "splines": []})
        entry["item_supported"] = entry["item_supported"] or bool(items) or positive
        entry["paths"].extend(paths)
        entry["splines"].extend(splines)
    assets = []
    for path, data in sorted(merged.items()):
        assets.append({"key": data["key"], "category": category(path),
                       "placement": "item", "sample": copy.deepcopy(ITEM_SAMPLE)})
    if not assets:
        raise ValueError("Source has no active individual nature assets (trees, shrubs, grass, plants or rocks)")
    counts = {"assets": len(assets), "categories": dict(sorted(Counter(a["category"] for a in assets).items())),
              "placements": dict(sorted(Counter(a["placement"] for a in assets).items()))}
    catalog = {"schema_version": 1, "profile_id": profile_id, "complete": True,
               "asset_scope": "nature_only",
               "counts": counts, "assets": assets}
    # Strict serialization rejects residual non-finite source metadata.
    json.dumps(catalog, allow_nan=False)
    diagnostics = {"source_collection": collections[0] if len(set(collections)) == 1 else collections,
                   "source_count": len(courses), "source_groups": len(groups),
                   "inactive_groups_excluded": inactive_groups,
                   "zero_count_only_groups_excluded": zero_only_groups,
                   "non_nature_groups_excluded": non_nature_groups,
                   "path_only_groups_excluded": path_only_groups,
                   "active_unique_native_paths": len(assets), **counts}
    return catalog, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", type=Path, nargs="+", required=True,
                        help="One or more original Designer.course sources; active assets are unioned by native path")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = [source.resolve() for source in args.course]
    output = args.output.resolve()
    if output in sources:
        parser.error("Output must be different from every source course")
    if output.suffix.lower() != ".json":
        parser.error("Output must be a .json catalog path")
    catalog, diagnostics = build_catalog([decode_course(source) for source in sources], args.profile_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"profile_id": args.profile_id, "output": str(output), **diagnostics}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
