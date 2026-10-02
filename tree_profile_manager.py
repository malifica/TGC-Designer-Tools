"""Beta 5 real-life tree profile support.

Custom profiles are JSON files stored in ./tree_profiles. They describe a
real-world course style: tree prefab mix/scale plus the donor course's surface
and terrain material selections.
"""

from __future__ import annotations

import copy
import json
import math
import random
import sys
from pathlib import Path

DESIGNER_THEME_LABEL = "Designer Theme (source course)"
HEROIC_SCALE_MODE = "Heroic (Beta 5)"
EPIC_SCALE_MODE = "Epic"
LEGACY_SCALE_MODE = "Legacy LiDAR"
EPIC_SCALE_MULTIPLIER = 1.20

PLANNED_PROFILE_NAMES = (
    "Piney Woods",
    "Monterey Peninsula",
    "Upstate New York",
    "Scotland",
    "Florida",
)

_PROFILE_CACHE = None
_PROFILE_ERRORS = []


def _profile_directories():
    roots = []

    # Load bundled/source profiles first. For a one-file PyInstaller build,
    # append the user-editable directory next to the EXE last so a profile with
    # the same display_name intentionally overrides the bundled copy.
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root) / "tree_profiles")

    roots.append(Path(__file__).resolve().parent / "tree_profiles")

    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent / "tree_profiles")
    output = []
    seen = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen:
            seen.add(key)
            output.append(root)
    return output


def _valid_scale_stats(value):
    if not isinstance(value, dict):
        return False
    for key in ("p10", "p50", "p90"):
        try:
            number = float(value[key])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(number) or number <= 0.0:
            return False
    return True


def _validate_profile(profile, source_name):
    if not isinstance(profile, dict):
        raise ValueError("profile root must be an object")
    if not profile.get("enabled", False):
        return None

    profile_id = str(profile.get("id", "")).strip()
    display_name = str(profile.get("display_name", "")).strip()
    assets = profile.get("assets", [])
    tree_generation = str(profile.get("tree_generation", "profile")).strip().lower()
    if tree_generation not in ("profile", "none"):
        raise ValueError("tree_generation must be 'profile' or 'none'")
    if not profile_id:
        raise ValueError("missing profile id")
    if not display_name:
        raise ValueError("missing display_name")
    if not isinstance(assets, list):
        raise ValueError("assets must be a list")
    if not assets and tree_generation != "none":
        raise ValueError("enabled profile must contain at least one asset")

    clean_assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        path = str(asset.get("path", "")).strip()
        shape = str(asset.get("shape", "normal")).strip().lower()
        try:
            weight = float(asset.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        if not path or shape not in ("normal", "skinny") or weight <= 0.0:
            continue

        scale = asset.get("scale", {})
        clean_scale = {}
        for axis in ("x", "y", "z"):
            stats = scale.get(axis) if isinstance(scale, dict) else None
            if _valid_scale_stats(stats):
                clean_scale[axis] = {
                    "p10": float(stats["p10"]),
                    "p50": float(stats["p50"]),
                    "p90": float(stats["p90"]),
                }

        uniform_scale = asset.get("uniform_scale")
        clean_uniform_scale = None
        if _valid_scale_stats(uniform_scale):
            clean_uniform_scale = {
                "p10": float(uniform_scale["p10"]),
                "p50": float(uniform_scale["p50"]),
                "p90": float(uniform_scale["p90"]),
            }

        clean_assets.append({
            "path": path,
            "shape": shape,
            "weight": weight,
            "scale": clean_scale,
            "uniform_scale": clean_uniform_scale,
        })

    if not clean_assets and tree_generation != "none":
        raise ValueError("enabled profile contains no usable assets")

    defaults = profile.get("scale_defaults", {})
    clean_defaults = {}
    if isinstance(defaults, dict):
        for axis in ("x", "y", "z"):
            if _valid_scale_stats(defaults.get(axis)):
                clean_defaults[axis] = {
                    "p10": float(defaults[axis]["p10"]),
                    "p50": float(defaults[axis]["p50"]),
                    "p90": float(defaults[axis]["p90"]),
                }

    raw_visual_material_preset = profile.get("visual_material_preset", {})
    clean_visual_material_preset = {}
    if isinstance(raw_visual_material_preset, dict):
        source_course = str(raw_visual_material_preset.get("source_course", "")).strip()
        if source_course:
            clean_visual_material_preset["source_course"] = source_course
        if "theme" in raw_visual_material_preset:
            try:
                clean_visual_material_preset["theme"] = int(
                    raw_visual_material_preset["theme"]
                )
            except (TypeError, ValueError):
                raise ValueError("visual_material_preset.theme must be an integer")
        for key in ("surfaces2", "secondarySurfaces"):
            value = raw_visual_material_preset.get(key)
            if isinstance(value, list) and value:
                clean_visual_material_preset[key] = copy.deepcopy(value)
        for key in ("cartPathTexture", "teeTexture"):
            if key in raw_visual_material_preset:
                clean_visual_material_preset[key] = copy.deepcopy(
                    raw_visual_material_preset[key]
                )

    return {
        "id": profile_id,
        "display_name": display_name,
        "description": str(profile.get("description", "")).strip(),
        "reference_courses": list(profile.get("reference_courses", []) or []),
        "tree_generation": tree_generation,
        "assets": clean_assets,
        "scale_defaults": clean_defaults,
        "visual_material_preset": clean_visual_material_preset,
        "_source": source_name,
    }


def load_profiles(force=False):
    global _PROFILE_CACHE, _PROFILE_ERRORS
    if _PROFILE_CACHE is not None and not force:
        return _PROFILE_CACHE
    profiles = {}
    _PROFILE_ERRORS = []
    for root in _profile_directories():
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                profile = _validate_profile(raw, path.name)
                if profile is not None:
                    profiles[profile["display_name"]] = profile
            except Exception as exc:
                _PROFILE_ERRORS.append(f"{path.name}: {exc}")
    _PROFILE_CACHE = profiles
    return profiles


def get_profile_choices():
    return [DESIGNER_THEME_LABEL] + sorted(load_profiles().keys())


def get_profile(choice):
    if not choice or choice == DESIGNER_THEME_LABEL:
        return None
    return load_profiles().get(str(choice))


def profile_load_errors():
    load_profiles()
    return list(_PROFILE_ERRORS)


def apply_visual_material_preset(target_json, choice, printf=print, metadata=False):
    """Apply a selected regional profile's donor Designer theme and materials."""
    profile = get_profile(choice)
    if profile is None:
        return target_json

    preset = profile.get("visual_material_preset", {}) or {}
    if not preset:
        return target_json

    applied = []
    if metadata:
        # CourseMetadata uses a different key name for the root Designer theme.
        if "theme" in preset:
            target_json["courseTheme"] = copy.deepcopy(preset["theme"])
            applied.append("courseTheme")
        if "surfaces2" in preset:
            target_json["surfaces2"] = copy.deepcopy(preset["surfaces2"])
            applied.append("surfaces2")
    else:
        for key in (
            "theme",
            "surfaces2",
            "secondarySurfaces",
            "cartPathTexture",
            "teeTexture",
        ):
            if key in preset:
                target_json[key] = copy.deepcopy(preset[key])
                applied.append(key)

    if applied and not metadata:
        surfaces = preset.get("surfaces2", []) or []
        slot_labels = {
            0: "bunker",
            6: "green",
            7: "fringe",
            8: "fairway",
            9: "rough",
            10: "heavy rough",
            11: "terrain 0",
            12: "terrain 1",
            13: "terrain 2",
            14: "terrain 3",
        }
        names = []
        for index, label in slot_labels.items():
            if index < len(surfaces):
                item = surfaces[index]
                if isinstance(item, dict) and item.get("name"):
                    names.append(label + "=" + str(item["name"]))
        if "theme" in preset:
            names.insert(0, "Designer theme=" + str(preset["theme"]))
        source = preset.get("source_course", profile.get("_source", "profile"))
        printf(
            "Regional theme preset applied from "
            + str(source)
            + (": " + ", ".join(names) if names else "")
        )

    return target_json

def _pool(profile, shape=None, source_kind="lidar"):
    assets = list(profile.get("assets", []))
    if source_kind == "osm":
        return assets
    if shape in ("normal", "skinny"):
        selected = [a for a in assets if a.get("shape") == shape]
        if selected:
            return selected
    normal = [a for a in assets if a.get("shape") == "normal"]
    return normal or assets


def choose_asset(profile, shape="normal", source_kind="lidar", rng=None):
    rng = rng or random
    pool = _pool(profile, shape=shape, source_kind=source_kind)
    if not pool:
        return None
    weights = [max(0.000001, float(a.get("weight", 1.0))) for a in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def _interpolate_stats(stats, percentile, fallback):
    if not _valid_scale_stats(stats):
        stats = fallback
    p10 = float(stats["p10"])
    p50 = float(stats["p50"])
    p90 = float(stats["p90"])
    p = max(0.0, min(1.0, float(percentile)))
    if p <= 0.5:
        return p10 + (p50 - p10) * (p / 0.5)
    return p50 + (p90 - p50) * ((p - 0.5) / 0.5)


_HEROIC_DEFAULTS = {
    "x": {"p10": 0.70, "p50": 1.10, "p90": 1.65},
    "y": {"p10": 0.85, "p50": 1.15, "p90": 1.55},
    "z": {"p10": 0.70, "p50": 1.10, "p90": 1.65},
}


def scale_for_asset(
    profile,
    asset,
    radius_percentile=0.5,
    height_percentile=0.5,
    tree_scale_mode=None,
):
    defaults = dict(_HEROIC_DEFAULTS)
    defaults.update(profile.get("scale_defaults", {}) or {})
    scale = asset.get("scale", {}) or {}
    uniform_scale = asset.get("uniform_scale")
    sx = _interpolate_stats(
        scale.get("x") or uniform_scale,
        radius_percentile,
        defaults["x"],
    )
    sy = _interpolate_stats(
        scale.get("y") or uniform_scale,
        height_percentile,
        defaults["y"],
    )
    sz = _interpolate_stats(
        scale.get("z") or uniform_scale,
        radius_percentile,
        defaults["z"],
    )

    # Epic preserves the donor-calibrated/profile-relative proportions while
    # making the entire tree population one clear step larger than Heroic.
    if tree_scale_mode == EPIC_SCALE_MODE:
        sx *= EPIC_SCALE_MULTIPLIER
        sy *= EPIC_SCALE_MULTIPLIER
        sz *= EPIC_SCALE_MULTIPLIER

    return sx, sy, sz
