"""Analyze finished 2K25 courses to build Beta 5 real-life tree profiles.

The analyzer deliberately excludes the common Designer technique of using trees as
off-course scenery massing: large foliage can be translated vertically and buried
under the terrain to create a dense hedge/forest wall.  Those instances are useful
for scenery, but they must not define a regional LiDAR/OSM tree palette.

Example:
    python tree_profile_analyzer.py --name "Texas Hill Country" course1.course

Generated candidates are disabled until reviewed.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

import tgc_definitions

DEFAULT_VERTICAL_TOLERANCE_M = 0.75
_TERRAIN_HARDNESS = 0.85


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


def _finite_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _prepare_stamp_layer(stamps):
    n = len(stamps)
    centers = np.empty((n, 2), dtype=np.float64)
    rx = np.empty(n, dtype=np.float64)
    rz = np.empty(n, dtype=np.float64)
    angle = np.empty(n, dtype=np.float64)
    value = np.empty(n, dtype=np.float64)
    tool = np.empty(n, dtype=np.int8)
    brush_type = np.empty(n, dtype=np.int16)
    radius = np.empty(n, dtype=np.float64)

    for i, stamp in enumerate(stamps):
        centers[i] = (
            float(stamp["position"]["x"]),
            float(stamp["position"]["z"]),
        )
        rx[i] = abs(float(stamp["scale"]["x"])) / 2.0
        rz[i] = abs(float(stamp["scale"]["z"])) / 2.0
        angle[i] = math.radians(float(stamp["rotation"]["y"]))
        value[i] = float(stamp["value"])
        tool[i] = int(stamp["tool"])
        brush_type[i] = int(stamp["type"])
        radius[i] = math.hypot(rx[i], rz[i])

    return {
        "centers": centers,
        "rx": rx,
        "rz": rz,
        "angle": angle,
        "value": value,
        "tool": tool,
        "brush_type": brush_type,
        "radius": radius,
        "cos": np.cos(angle),
        "sin": np.sin(angle),
        "square": (brush_type == 15) | (brush_type == 72),
    }


def _build_query_groups(layer):
    radius = layer["radius"]
    centers = layer["centers"]
    limits = [5, 10, 20, 40, 80, 160, 320, 800]
    groups = []
    low = 0.0
    for high in limits:
        idx = np.where((radius > low) & (radius <= high))[0]
        groups.append((high, idx, cKDTree(centers[idx]) if len(idx) else None))
        low = high

    idx = np.where(radius > limits[-1])[0]
    if len(idx):
        high = float(radius[idx].max()) + 1.0
        groups.append((high, idx, cKDTree(centers[idx])))
    return groups


def _apply_stamp_layer(initial_height, x, z, layer, groups):
    candidates = []
    for query_radius, idx, tree in groups:
        if tree is None:
            continue
        local = tree.query_ball_point([x, z], r=query_radius)
        if local:
            candidates.extend(idx[np.asarray(local, dtype=int)].tolist())

    if not candidates:
        return initial_height

    candidates = np.asarray(sorted(set(candidates)), dtype=int)
    dx = x - layer["centers"][candidates, 0]
    dz = z - layer["centers"][candidates, 1]
    lx = dx * layer["cos"][candidates] + dz * layer["sin"][candidates]
    lz = -dx * layer["sin"][candidates] + dz * layer["cos"][candidates]

    d = np.where(
        layer["square"][candidates],
        np.maximum(
            np.abs(lx) / layer["rx"][candidates],
            np.abs(lz) / layer["rz"][candidates],
        ),
        np.sqrt(
            (lx * lx) / (layer["rx"][candidates] * layer["rx"][candidates])
            + (lz * lz) / (layer["rz"][candidates] * layer["rz"][candidates])
        ),
    )

    keep = d < 1.0
    candidates = candidates[keep]
    d = d[keep]

    height = float(initial_height)
    for stamp_index, distance in zip(candidates, d):
        t = max(
            0.0,
            min(
                1.0,
                (1.0 - float(distance)) / (1.0 - _TERRAIN_HARDNESS),
            ),
        )
        weight = t * t * (3.0 - 2.0 * t)
        if layer["tool"][stamp_index] == 0:
            height += (layer["value"][stamp_index] - height) * weight
        else:
            height += layer["value"][stamp_index] * weight
    return height


class _TerrainPointSampler:
    """Point replay used only to reject manually vertically displaced foliage.

    The exact game post-blur is not needed for this classification.  A generous
    default tolerance absorbs blur/model error, and a finite-Y tree is accepted
    when it matches either detailed height[] terrain or terrainHeight+height[]
    background terrain.
    """

    def __init__(self, course):
        self.detail = _prepare_stamp_layer(course.get("height", []) or [])
        self.detail_groups = _build_query_groups(self.detail)
        self.background = _prepare_stamp_layer(course.get("terrainHeight", []) or [])
        self.background_groups = _build_query_groups(self.background)

    def estimates(self, x, z):
        detail = _apply_stamp_layer(
            0.0, x, z, self.detail, self.detail_groups
        )
        background = _apply_stamp_layer(
            0.0, x, z, self.background, self.background_groups
        )
        combined = _apply_stamp_layer(
            background, x, z, self.detail, self.detail_groups
        )
        return detail, combined


def _item_is_ground_aligned(item, sampler, tolerance_m):
    position = item.get("position", {}) or {}
    y = _finite_float(position.get("y"))

    # Normal Designer terrain snapping.  This is always treated as a real tree.
    if not math.isfinite(y):
        return True, None

    x = _finite_float(position.get("x"))
    z = _finite_float(position.get("z"))
    if not math.isfinite(x) or not math.isfinite(z):
        return False, None

    detail, combined = sampler.estimates(x, z)
    offset = min(abs(y - detail), abs(y - combined))
    return offset <= tolerance_m, offset


def analyze(
    paths,
    display_name,
    vertical_tolerance_m=DEFAULT_VERTICAL_TOLERANCE_M,
    keep_manual_height=False,
):
    normal_paths, skinny_paths = _tree_shape_reference()
    by_path = defaultdict(lambda: {"x": [], "y": [], "z": []})
    all_scales = {"x": [], "y": [], "z": []}
    references = []

    total_speedtree_items = 0
    excluded_vertical = 0
    excluded_vertical_by_asset = Counter()
    retained_ground_aligned = 0

    for filename in paths:
        course = _decode_course(filename)
        references.append(Path(filename).name)
        sampler = None if keep_manual_height else _TerrainPointSampler(course)

        groups = course.get(
            "placedObjects4",
            course.get("placedObjects3", course.get("placedObjects2", [])),
        ) or []

        for group in groups:
            asset_path = str((group.get("Key", {}) or {}).get("path", ""))
            if (
                "/Foliage/SpeedTree" not in asset_path
                or "/Trees/" not in asset_path
                or "/Bushes/" in asset_path
            ):
                continue

            for item in (group.get("Value", {}) or {}).get("items", []) or []:
                total_speedtree_items += 1

                if sampler is not None:
                    aligned, _offset = _item_is_ground_aligned(
                        item, sampler, vertical_tolerance_m
                    )
                    if not aligned:
                        excluded_vertical += 1
                        excluded_vertical_by_asset[asset_path] += 1
                        continue

                scale = item.get("scale", {}) or {}
                try:
                    sx = float(scale.get("x", 1.0))
                    sy = float(scale.get("y", 1.0))
                    sz = float(scale.get("z", 1.0))
                except (TypeError, ValueError):
                    continue

                retained_ground_aligned += 1
                by_path[asset_path]["x"].append(sx)
                by_path[asset_path]["y"].append(sy)
                by_path[asset_path]["z"].append(sz)
                all_scales["x"].append(sx)
                all_scales["y"].append(sy)
                all_scales["z"].append(sz)

    total = sum(len(v["y"]) for v in by_path.values())
    if total == 0:
        raise ValueError("No usable placed tree items were found in the supplied course file(s).")

    assets = []
    review_count = 0
    for path, vals in sorted(
        by_path.items(),
        key=lambda kv: (-len(kv[1]["y"]), kv[0]),
    ):
        shape = _shape_for_path(path, normal_paths, skinny_paths)
        if shape == "review":
            review_count += 1

        asset = {
            "path": path,
            "shape": shape,
            "weight": len(vals["y"]),
            "count": len(vals["y"]),
        }

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

    result = {
        "id": _slug(display_name),
        "display_name": display_name,
        "enabled": False,
        "description": (
            "Candidate real-life tree profile generated from finished "
            "Designer-planted reference course(s). Review before enabling."
        ),
        "reference_courses": references,
        "all_speedtree_tree_count": total_speedtree_items,
        "natural_reference_tree_count": total,
        "excluded_vertical_massing_count": excluded_vertical,
        "terrain_alignment_tolerance_m": (
            None if keep_manual_height else float(vertical_tolerance_m)
        ),
        "review_asset_count": review_count,
        "scale_defaults": {
            "x": _quantiles(all_scales["x"]),
            "y": _quantiles(all_scales["y"]),
            "z": _quantiles(all_scales["z"]),
        },
        "assets": assets,
    }

    if excluded_vertical_by_asset:
        result["excluded_vertical_massing_assets"] = [
            {"path": path, "count": count}
            for path, count in excluded_vertical_by_asset.most_common()
        ]

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("course", nargs="+", help="Finished .course reference file(s)")
    parser.add_argument(
        "--name",
        required=True,
        help='Profile display name, e.g. "Texas Hill Country"',
    )
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument(
        "--vertical-tolerance",
        type=float,
        default=DEFAULT_VERTICAL_TOLERANCE_M,
        help=(
            "Maximum finite-Y distance from reconstructed terrain to treat as a "
            "natural tree placement (default: 0.75 m)."
        ),
    )
    parser.add_argument(
        "--keep-manual-height",
        action="store_true",
        help="Disable the buried/raised foliage filter for special diagnostics.",
    )
    args = parser.parse_args()

    result = analyze(
        args.course,
        args.name,
        vertical_tolerance_m=args.vertical_tolerance,
        keep_manual_height=args.keep_manual_height,
    )
    output = (
        Path(args.output)
        if args.output
        else Path("tree_profiles") / (result["id"] + ".candidate.json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("Wrote:", output)
    print("Reference courses:", len(result["reference_courses"]))
    print("All SpeedTree tree placements:", result["all_speedtree_tree_count"])
    print("Natural/terrain-aligned samples:", result["natural_reference_tree_count"])
    print("Excluded buried/raised scenery samples:", result["excluded_vertical_massing_count"])
    print("Unique retained tree prefabs:", len(result["assets"]))
    print("Assets needing normal/skinny review:", result["review_asset_count"])
    print("Set enabled=true only after the profile has been reviewed.")


if __name__ == "__main__":
    main()
