"""Analyze finished 2K25 courses to build Beta 5 real-life tree profiles.

Example:
    python tree_profile_analyzer.py --name "Piney Woods" course1.course course2.course

Generated candidates are disabled until reviewed.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import tgc_definitions


def _decode_course(path):
    raw = Path(path).read_bytes()
    outer = json.loads(gzip.decompress(raw).decode("utf-16"))
    payload = base64.b64decode(outer["binaryData"]["CourseDescription"])
    inner = gzip.decompress(payload)
    for encoding in ("utf-16", "utf-16-le", "utf-8"):
        try:
            return json.loads(inner.decode(encoding))
        except Exception:
            pass
    raise ValueError("Could not decode CourseDescription")


def _tree_shape_reference():
    normal = set()
    skinny = set()
    for ids in tgc_definitions.normal_trees_2k.values():
        for tree_id in ids:
            if 0 <= tree_id < len(tgc_definitions.trees_2k):
                normal.add(tgc_definitions.trees_2k[tree_id])
    for ids in tgc_definitions.skinny_trees_2k.values():
        for tree_id in ids:
            if 0 <= tree_id < len(tgc_definitions.trees_2k):
                skinny.add(tgc_definitions.trees_2k[tree_id])
    return normal, skinny


def _shape_for_path(path, normal_paths, skinny_paths):
    in_normal = path in normal_paths
    in_skinny = path in skinny_paths
    if in_skinny and not in_normal:
        return "skinny"
    if in_normal and not in_skinny:
        return "normal"
    return "review"


def _quantiles(values):
    arr = np.asarray(values, dtype=np.float64)
    return {
        "p10": round(float(np.percentile(arr, 10)), 6),
        "p50": round(float(np.percentile(arr, 50)), 6),
        "p90": round(float(np.percentile(arr, 90)), 6),
    }


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "custom_tree_profile"


def analyze(paths, display_name):
    normal_paths, skinny_paths = _tree_shape_reference()
    by_path = defaultdict(lambda: {"x": [], "y": [], "z": []})
    all_scales = {"x": [], "y": [], "z": []}
    references = []

    for filename in paths:
        course = _decode_course(filename)
        references.append(Path(filename).name)
        groups = course.get("placedObjects4", course.get("placedObjects3", course.get("placedObjects2", []))) or []
        for group in groups:
            asset_path = str((group.get("Key", {}) or {}).get("path", ""))
            if "/Foliage/SpeedTree" not in asset_path or "/Trees/" not in asset_path or "/Bushes/" in asset_path:
                continue
            for item in (group.get("Value", {}) or {}).get("items", []) or []:
                scale = item.get("scale", {}) or {}
                try:
                    sx = float(scale.get("x", 1.0))
                    sy = float(scale.get("y", 1.0))
                    sz = float(scale.get("z", 1.0))
                except (TypeError, ValueError):
                    continue
                by_path[asset_path]["x"].append(sx)
                by_path[asset_path]["y"].append(sy)
                by_path[asset_path]["z"].append(sz)
                all_scales["x"].append(sx)
                all_scales["y"].append(sy)
                all_scales["z"].append(sz)

    total = sum(len(v["y"]) for v in by_path.values())
    if total == 0:
        raise ValueError("No placed tree items were found in the supplied course file(s).")

    assets = []
    review_count = 0
    for path, vals in sorted(by_path.items(), key=lambda kv: (-len(kv[1]["y"]), kv[0])):
        shape = _shape_for_path(path, normal_paths, skinny_paths)
        if shape == "review":
            review_count += 1
        asset = {
            "path": path,
            "shape": shape,
            "weight": len(vals["y"]),
            "count": len(vals["y"]),
        }

        # Designer tree instances are frequently scaled uniformly.  Preserve a
        # compact single distribution when X/Y/Z are effectively identical;
        # otherwise retain independent axis statistics.
        uniform = (
            np.allclose(vals["x"], vals["y"], rtol=1e-6, atol=1e-6)
            and np.allclose(vals["x"], vals["z"], rtol=1e-6, atol=1e-6)
        )
        if uniform:
            asset["uniform_scale"] = _quantiles(vals["y"])
        else:
            asset["scale"] = {
                "x": _quantiles(vals["x"]),
                "y": _quantiles(vals["y"]),
                "z": _quantiles(vals["z"]),
            }
        assets.append(asset)

    return {
        "id": _slug(display_name),
        "display_name": display_name,
        "enabled": False,
        "description": "Candidate real-life tree profile generated from finished Designer-planted reference course(s). Review before enabling.",
        "reference_courses": references,
        "sample_tree_count": total,
        "review_asset_count": review_count,
        "scale_defaults": {
            "x": _quantiles(all_scales["x"]),
            "y": _quantiles(all_scales["y"]),
            "z": _quantiles(all_scales["z"]),
        },
        "assets": assets,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("course", nargs="+", help="Finished .course reference file(s)")
    parser.add_argument("--name", required=True, help='Profile display name, e.g. "Piney Woods"')
    parser.add_argument("--output", help="Output JSON path")
    args = parser.parse_args()

    result = analyze(args.course, args.name)
    output = Path(args.output) if args.output else Path("tree_profiles") / (result["id"] + ".candidate.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("Wrote:", output)
    print("Reference courses:", len(result["reference_courses"]))
    print("Placed tree samples:", result["sample_tree_count"])
    print("Unique tree prefabs:", len(result["assets"]))
    print("Assets needing normal/skinny review:", result["review_asset_count"])
    print("Set enabled=true only after the profile has been reviewed.")


if __name__ == "__main__":
    main()
