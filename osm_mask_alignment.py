"""Authoritative post-CFS OSM alignment mask workflow for Beta 6.

The LiDAR/DEM processing stage may create a provisional mask before the user
applies a manual CFS E/W or N/S alignment.  This module rebuilds mask.png on
the saved full-resolution master grid using the exact same alignment offsets
that will later be used for OSM spline export.

Manual mask edits are intentionally allowed *after* a successful rebuild.
Validity checks compare the OSM/grid/alignment/settings sidecar, not the mask
file hash, so subsequent hand painting does not make a current mask stale.
"""

# TGC_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import overpy
import pyproj

import OSMTGC
import auto_red_mask
import tgc_tools
import osm_custom_layout
import cfs_georef
from GeoPointCloud import GeoPointCloud


PATCH_ID = "TGC_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1"
# TGC_BETA6_OSM_CARTPATH_ROAD_SPLIT_V4
# TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5
ASYNC_PATCH_ID = "TGC_BETA6_CFS_ASYNC_MASK_REBUILD_V3"
SIDECAR_NAME = "osm_mask_alignment.json"
SCHEMA_VERSION = 1
ALIGNMENT_TOLERANCE_M = 0.0051



def _report_progress(progress_callback, percent: float, message: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(max(0.0, min(100.0, float(percent))), str(message))
    except Exception:
        pass


class _FastGridProjector:
    """GeoPointCloud-compatible pixel projection with one cached transformer.

    OSM mask rendering calls latlonToCV2 repeatedly, often more than once for
    the same node.  GeoPointCloud historically rebuilt a PyProj transformer on
    every call.  This adapter preserves the exact coordinate semantics while
    caching both the transformer and projected node locations.
    """

    def __init__(self, projection, origin, custom_placement=None):
        self.proj = projection
        self.origin = (float(origin[0]), float(origin[1]))
        self.custom_placement = custom_placement
        self._cache = {}
        self._fallback = None
        try:
            from tgc_cfs_display import importer_transformer
            self._transformer = (None if custom_placement is not None
                                 else importer_transformer(projection))
        except Exception:
            self._transformer = None
            self._fallback = GeoPointCloud()
            self._fallback.proj = projection
            self._fallback.origin = self.origin

    def latlonToCV2(
        self,
        lat,
        lon,
        image_scale,
        offset_x=0.0,
        offset_y=0.0,
    ):
        key = (round(float(lat), 11), round(float(lon), 11))
        projected = self._cache.get(key)
        if projected is None:
            if self.custom_placement is not None:
                x, y = self.custom_placement.project(float(lon), float(lat))
            elif self._transformer is not None:
                x, y = self._transformer.transform(float(lon), float(lat))
            else:
                return self._fallback.latlonToCV2(
                    lat,
                    lon,
                    image_scale,
                    offset_x,
                    offset_y,
                )
            projected = (float(x), float(y))
            self._cache[key] = projected

        scale = float(image_scale)
        x_enu = projected[0] - self.origin[0] + float(offset_x)
        y_enu = projected[1] - self.origin[1] + float(offset_y)
        # Match GeoPointCloud.enuToCV2: int() truncation for the normal
        # positive in-grid coordinate domain.
        return int(y_enu / scale), int(x_enu / scale)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(str(temporary), str(path))


def _heightmap_paths(heightmap_dir: str | Path) -> Tuple[Path, Path, Path]:
    folder = Path(heightmap_dir)
    if folder.is_file() and folder.name.lower() == "heightmap.npy":
        folder = folder.parent
    return folder, folder / "heightmap.npy", folder / "mask.png"


def _load_heightmap(heightmap_dir: str | Path) -> Tuple[Path, Path, Path, Dict[str, Any], np.ndarray, Dict[str, Any]]:
    folder, heightmap_path, mask_path = _heightmap_paths(heightmap_dir)
    if not heightmap_path.is_file():
        raise FileNotFoundError("heightmap.npy was not found: " + str(heightmap_path))

    data = np.load(str(heightmap_path), allow_pickle=True).item()
    heightmap = np.asarray(data.get("heightmap"))
    if heightmap.ndim not in (2, 3) or heightmap.size == 0:
        raise ValueError("Unsupported or empty heightmap array: " + str(heightmap.shape))

    grid = cfs_georef.get_master_grid(
        data,
        heightmap,
        printf=lambda _message: None,
    )
    return folder, heightmap_path, mask_path, data, heightmap, grid


def _grid_fingerprint(data: Dict[str, Any], heightmap: np.ndarray, grid: Dict[str, Any]) -> str:
    projection = data.get("projection")
    payload = {
        "rows": int(heightmap.shape[0]),
        "cols": int(heightmap.shape[1]),
        "resolution": float(grid.get("resolution")),
        "min_x": float(grid.get("min_x")),
        "min_y": float(grid.get("min_y")),
        "max_x": float(grid.get("max_x", float(grid.get("min_x")) + int(heightmap.shape[1]) * float(grid.get("resolution")))),
        "max_y": float(grid.get("max_y", float(grid.get("min_y")) + int(heightmap.shape[0]) * float(grid.get("resolution")))),
        "horizontal_epsg": cfs_georef.horizontal_epsg(projection),
        "crs_wkt": cfs_georef.crs_wkt(projection),
        "row_order": str(grid.get("row_order", "south_up_internal")),
        "origin_semantics": str(grid.get("origin_semantics", "southwest_cell_edge")),
    }
    return _json_hash(payload)


DEFAULT_VEHICLE_ROAD_WIDTH_M = 6.0


def _vehicle_road_width_m(folder: Path) -> float:
    """Read validated splines.json road.pathWidth used by OSM road import."""
    data = tgc_tools.get_spline_configuration_json(
        folder,
        printf=None,
    )
    if not data:
        return DEFAULT_VEHICLE_ROAD_WIDTH_M
    value = float(
        (data.get("road") or {}).get(
            "pathWidth",
            DEFAULT_VEHICLE_ROAD_WIDTH_M,
        )
    )
    if math.isfinite(value) and value > 0.0:
        return value
    return DEFAULT_VEHICLE_ROAD_WIDTH_M


def _normalize_settings(
    adjust_ew_m: float,
    adjust_ns_m: float,
    auto_red_mask_enabled: bool,
    auto_red_mask_buffer_m: float,
) -> Tuple[float, float, bool, float]:
    ew = float(adjust_ew_m)
    ns = float(adjust_ns_m)
    enabled = bool(auto_red_mask_enabled)
    buffer_m = float(auto_red_mask_buffer_m)

    if not math.isfinite(ew) or not math.isfinite(ns):
        raise ValueError("CFS E/W and N/S alignment values must be finite numbers.")
    if not math.isfinite(buffer_m) or buffer_m < 0.0:
        raise ValueError("Auto Red Mask buffer must be a finite non-negative number.")

    return ew, ns, enabled, buffer_m


def _signature(
    folder: Path,
    data: Dict[str, Any],
    heightmap: np.ndarray,
    grid: Dict[str, Any],
    osm_file: str | Path,
    adjust_ew_m: float,
    adjust_ns_m: float,
    auto_red_mask_enabled: bool,
    auto_red_mask_buffer_m: float,
    include_vehicle_roads: bool = False,
    custom_unmatched_osm: bool = False,
) -> Dict[str, Any]:
    osm_path = Path(osm_file)
    if not osm_path.is_file():
        raise FileNotFoundError("Local OSM file was not found: " + str(osm_path))

    ew, ns, enabled, buffer_m = _normalize_settings(
        adjust_ew_m,
        adjust_ns_m,
        auto_red_mask_enabled,
        auto_red_mask_buffer_m,
    )

    # Automobile-road geometry only affects mask pixels when Auto Red Mask is
    # active.  Do not make an otherwise-disabled mask stale just because the
    # road import checkbox changed.
    include_roads_in_mask = bool(include_vehicle_roads) and bool(enabled)
    road_width_m = (
        _vehicle_road_width_m(folder)
        if include_roads_in_mask
        else DEFAULT_VEHICLE_ROAD_WIDTH_M
    )

    from tgc_cfs_display import ALIGNMENT_GEOMETRY_VERSION
    return {
        "alignment_geometry_version": ALIGNMENT_GEOMETRY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "patch_id": PATCH_ID,
        "heightmap_directory": str(folder.resolve()),
        "master_grid_fingerprint": _grid_fingerprint(data, heightmap, grid),
        "osm_file": str(osm_path.resolve()),
        "osm_sha256": _sha256_file(osm_path),
        "adjust_ew_m": ew,
        "adjust_ns_m": ns,
        "auto_red_mask_enabled": enabled,
        "auto_red_mask_buffer_m": buffer_m,
        "include_vehicle_roads": bool(include_roads_in_mask),
        "vehicle_road_width_m": float(road_width_m),
        "custom_unmatched_osm": bool(custom_unmatched_osm),
        "custom_layout_patch_id": (
            osm_custom_layout.PATCH_ID_V5_1 if bool(custom_unmatched_osm) else ""
        ),
    }


def _load_sidecar(folder: Path) -> Optional[Dict[str, Any]]:
    path = folder / SIDECAR_NAME
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_invalid": True}
    return value if isinstance(value, dict) else {"_invalid": True}


def _mask_shape(mask_path: Path) -> Optional[Tuple[int, int]]:
    if not mask_path.is_file():
        return None
    image = cv2.imread(str(mask_path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    return int(image.shape[0]), int(image.shape[1])


def _alignment_close(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= ALIGNMENT_TOLERANCE_M
    except Exception:
        return False


def _signatures_match(recorded: Dict[str, Any], expected: Dict[str, Any]) -> Tuple[bool, str]:
    if recorded.get("_invalid"):
        return False, "The alignment sidecar is unreadable."
    if recorded.get("invalidated"):
        return False, str(
            recorded.get("invalidated_reason")
            or "Terrain processing regenerated mask.png after the final CFS alignment."
        )
    if recorded.get("patch_id") != PATCH_ID:
        return False, "The alignment sidecar was created by an older workflow."
    if int(recorded.get("schema_version", -1)) != SCHEMA_VERSION:
        return False, "The alignment sidecar schema does not match this build."
    if recorded.get("alignment_geometry_version") != expected.get("alignment_geometry_version"):
        return False, "Beta 7 alignment coordinates changed; review CFS and Apply + Rebuild Mask."
    if recorded.get("master_grid_fingerprint") != expected.get("master_grid_fingerprint"):
        return False, "The heightmap/master grid changed after the mask was recorded."
    if recorded.get("osm_sha256") != expected.get("osm_sha256"):
        return False, "The selected Local OSM file changed after the mask was recorded."
    if not _alignment_close(recorded.get("adjust_ew_m"), expected.get("adjust_ew_m")):
        return False, "The CFS E/W alignment changed after the mask was recorded."
    if not _alignment_close(recorded.get("adjust_ns_m"), expected.get("adjust_ns_m")):
        return False, "The CFS N/S alignment changed after the mask was recorded."
    if bool(recorded.get("auto_red_mask_enabled")) != bool(expected.get("auto_red_mask_enabled")):
        return False, "The Auto Red Mask enabled/disabled setting changed."
    if bool(expected.get("auto_red_mask_enabled")):
        if not _alignment_close(
            recorded.get("auto_red_mask_buffer_m"),
            expected.get("auto_red_mask_buffer_m"),
        ):
            return False, "The Auto Red Mask buffer changed after the mask was recorded."
    recorded_roads = bool(recorded.get("include_vehicle_roads", False))
    expected_roads = bool(expected.get("include_vehicle_roads", False))
    if recorded_roads != expected_roads:
        return False, "The Import Automobile Roads setting changed after the mask was recorded."
    if expected_roads:
        if not _alignment_close(
            recorded.get("vehicle_road_width_m", DEFAULT_VEHICLE_ROAD_WIDTH_M),
            expected.get("vehicle_road_width_m", DEFAULT_VEHICLE_ROAD_WIDTH_M),
        ):
            return False, "splines.json road.pathWidth changed after the mask was recorded."
    recorded_custom = bool(recorded.get("custom_unmatched_osm", False))
    expected_custom = bool(expected.get("custom_unmatched_osm", False))
    if recorded_custom != expected_custom:
        return False, "The Custom / Unmatched OSM setting changed after the mask was recorded."
    if expected_custom:
        if recorded.get("custom_layout_patch_id", "") != expected.get("custom_layout_patch_id", ""):
            return False, "The Custom / Unmatched OSM placement logic changed; rebuild the aligned mask."
    return True, "The mask matches the current OSM alignment and settings."


def get_alignment_status(
    heightmap_dir: str | Path,
    osm_file: str | Path,
    adjust_ew_m: float,
    adjust_ns_m: float,
    auto_red_mask_enabled: bool,
    auto_red_mask_buffer_m: float,
    include_vehicle_roads: bool = False,
    custom_unmatched_osm: bool = False,
) -> Dict[str, Any]:
    """Return a non-destructive status for the current alignment/mask pair."""
    try:
        folder, _heightmap_path, mask_path, data, heightmap, grid = _load_heightmap(heightmap_dir)
    except Exception as exc:
        return {
            "state": "missing_heightmap",
            "ok_for_import": False,
            "message": str(exc),
        }

    expected_shape = (int(heightmap.shape[0]), int(heightmap.shape[1]))
    actual_shape = _mask_shape(mask_path)
    if actual_shape is None:
        return {
            "state": "missing_mask",
            "ok_for_import": False,
            "message": "mask.png is missing or unreadable.",
        }
    if actual_shape != expected_shape:
        return {
            "state": "stale",
            "ok_for_import": False,
            "message": (
                "mask.png dimensions " + str(actual_shape[1]) + " x " + str(actual_shape[0]) +
                " do not match the heightmap " + str(expected_shape[1]) + " x " + str(expected_shape[0]) + "."
            ),
        }

    try:
        expected = _signature(
            folder,
            data,
            heightmap,
            grid,
            osm_file,
            adjust_ew_m,
            adjust_ns_m,
            auto_red_mask_enabled,
            auto_red_mask_buffer_m,
            include_vehicle_roads=include_vehicle_roads,
            custom_unmatched_osm=custom_unmatched_osm,
        )
    except Exception as exc:
        return {
            "state": "stale",
            "ok_for_import": False,
            "message": str(exc),
        }

    recorded = _load_sidecar(folder)
    if recorded is None:
        if bool(custom_unmatched_osm):
            return {
                "state": "stale",
                "ok_for_import": False,
                "message": (
                    "Custom / Unmatched OSM requires a mask rebuilt from its "
                    "terrain-centered placement before import."
                ),
                "expected": expected,
            }
        if (
            abs(float(expected["adjust_ew_m"])) <= ALIGNMENT_TOLERANCE_M
            and abs(float(expected["adjust_ns_m"])) <= ALIGNMENT_TOLERANCE_M
        ):
            return {
                "state": "legacy_zero_shift",
                "ok_for_import": False,
                "message": (
                    "This existing zero-shift mask predates alignment tracking. "
                    "It can be rebuilt or adopted without changing its pixels."
                ),
                "expected": expected,
            }
        return {
            "state": "stale",
            "ok_for_import": False,
            "message": (
                "The current mask has no alignment record, but the CFS shift is non-zero. "
                "Rebuild the mask from the current alignment."
            ),
            "expected": expected,
        }

    matched, message = _signatures_match(recorded, expected)
    return {
        "state": "current" if matched else "stale",
        "ok_for_import": bool(matched),
        "message": message,
        "expected": expected,
        "recorded": recorded,
    }


def invalidate_alignment_record(
    heightmap_dir: str | Path,
    reason: str,
    printf=print,
) -> bool:
    """Mark an existing alignment record stale after terrain/mask processing."""
    folder, _heightmap_path, _mask_path = _heightmap_paths(heightmap_dir)
    sidecar_path = folder / SIDECAR_NAME
    if not sidecar_path.is_file():
        return False

    record = _load_sidecar(folder)
    if not isinstance(record, dict) or record.get("_invalid"):
        record = {
            "schema_version": SCHEMA_VERSION,
            "patch_id": PATCH_ID,
        }

    record["invalidated"] = True
    record["invalidated_utc"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    record["invalidated_reason"] = str(reason)
    _atomic_write_text(
        sidecar_path,
        json.dumps(record, indent=2, sort_keys=True) + "\n",
    )
    printf("OSM alignment mask marked STALE: " + str(reason))
    return True


def _terrain_visual_from_heightmap(heightmap: np.ndarray) -> np.ndarray:
    arr = np.asarray(heightmap)
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    arr = np.asarray(arr, dtype=np.float32)

    finite = arr[np.isfinite(arr)]
    gray = np.zeros(arr.shape, dtype=np.float32)
    if finite.size:
        lo = float(np.percentile(finite, 2.0))
        hi = float(np.percentile(finite, 98.0))
        if not math.isfinite(lo):
            lo = float(np.min(finite))
        if not math.isfinite(hi):
            hi = float(np.max(finite))
        if hi <= lo:
            hi = lo + 1.0
        gray = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
        gray[~np.isfinite(gray)] = 0.0

    return np.repeat(gray[:, :, None], 3, axis=2).astype(np.float32)


def _load_complete_osm(osm_file: str | Path):
    osm_path = Path(osm_file)
    with osm_path.open("r", encoding="utf-8-sig") as stream:
        xml_data = stream.read()

    result = OSMTGC.parseOSMData(xml_data, printf=lambda _message: None)
    if result is None:
        raise RuntimeError("Could not parse Local OSM file: " + str(osm_path))

    incomplete = []
    for way in result.ways:
        try:
            way.get_nodes(resolve_missing=False)
        except overpy.exception.DataIncomplete:
            incomplete.append(getattr(way, "id", "?"))

    if incomplete:
        preview = ", ".join(str(value) for value in incomplete[:10])
        if len(incomplete) > 10:
            preview += ", ..."
        raise RuntimeError(
            "Local OSM contains " + str(len(incomplete)) +
            " incomplete way(s) with missing node references: " + preview
        )

    return result


def _next_backup_path(folder: Path) -> Path:
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = folder / ("mask.before_alignment_rebuild_" + timestamp + ".png")
    suffix = 1
    while candidate.exists():
        candidate = folder / (
            "mask.before_alignment_rebuild_" + timestamp + "_" + str(suffix) + ".png"
        )
        suffix += 1
    return candidate


def _write_mask_atomic(mask_path: Path, mask_rgb_south_up: np.ndarray, expected_shape: Tuple[int, int]) -> None:
    mask_disk = np.flip(np.asarray(mask_rgb_south_up), 0)
    if np.issubdtype(mask_disk.dtype, np.floating):
        mask_u8 = (255.0 * np.clip(mask_disk, 0.0, 1.0)).astype(np.uint8)
    else:
        mask_u8 = np.clip(mask_disk, 0, 255).astype(np.uint8)

    temporary = mask_path.with_name("mask.alignment_rebuild.tmp.png")
    ok = cv2.imwrite(
        str(temporary),
        cv2.cvtColor(mask_u8[:, :, :3], cv2.COLOR_RGB2BGR),
    )
    if not ok:
        raise RuntimeError("Could not write temporary aligned mask: " + str(temporary))

    written = cv2.imread(str(temporary), cv2.IMREAD_COLOR)
    actual_shape = None if written is None else (int(written.shape[0]), int(written.shape[1]))
    if actual_shape != expected_shape:
        try:
            temporary.unlink()
        except Exception:
            pass
        raise RuntimeError(
            "Aligned mask verification failed: expected " + str(expected_shape) +
            ", wrote " + str(actual_shape)
        )

    os.replace(str(temporary), str(mask_path))


def rebuild_aligned_mask(
    heightmap_dir: str | Path,
    osm_file: str | Path,
    adjust_ew_m: float,
    adjust_ns_m: float,
    auto_red_mask_enabled: bool = True,
    auto_red_mask_buffer_m: float = 5.0,
    include_vehicle_roads: bool = False,
    custom_unmatched_osm: bool = False,
    backup_existing: bool = True,
    printf=print,
    progress_callback=None,
) -> Dict[str, Any]:
    """Rebuild mask.png from the final CFS alignment on the master grid."""
    _report_progress(progress_callback, 3, "Loading heightmap and master-grid data...")
    folder, _heightmap_path, mask_path, data, heightmap, grid = _load_heightmap(heightmap_dir)
    _report_progress(progress_callback, 10, "Verifying OSM, grid, and alignment settings...")
    expected = _signature(
        folder,
        data,
        heightmap,
        grid,
        osm_file,
        adjust_ew_m,
        adjust_ns_m,
        auto_red_mask_enabled,
        auto_red_mask_buffer_m,
        include_vehicle_roads=include_vehicle_roads,
        custom_unmatched_osm=custom_unmatched_osm,
    )

    _report_progress(progress_callback, 16, "Validating the terrain projection...")
    cfs_georef.validate_projection(data.get("projection"), printf=printf)
    _report_progress(progress_callback, 22, "Parsing and validating the Local OSM file...")
    osm_result = _load_complete_osm(osm_file)

    resolution = float(grid["resolution"])
    custom_placement = None
    if bool(custom_unmatched_osm):
        custom_placement = osm_custom_layout.placement_for_master_grid(
            osm_result,
            grid,
        )
        info = custom_placement.diagnostics()
        printf(
            "Custom / Unmatched OSM: mask rebuild ignores absolute OSM geography; "
            "centered %s (%d node(s), %.1f x %.1f m) on the terrain grid." % (
                info.get("anchor_strategy", "course anchor"),
                int(info.get("anchor_node_count", 0)),
                info["source_width_m"], info["source_height_m"]
            )
        )
    grid_pc = _FastGridProjector(
        data["projection"],
        (float(grid["min_x"]), float(grid["min_y"])),
        custom_placement=custom_placement,
    )

    printf(
        "Rebuilding mask.png from final CFS alignment: E/W " +
        str(round(float(adjust_ew_m), 3)) + " m, N/S " +
        str(round(float(adjust_ns_m), 3)) + " m."
    )

    _report_progress(progress_callback, 34, "Preparing the full-resolution terrain mask base...")
    mask_rgb = _terrain_visual_from_heightmap(heightmap)
    _report_progress(progress_callback, 48, "Rendering aligned OSM features into mask.png...")
    mask_rgb = OSMTGC.addOSMToImage(
        osm_result,
        mask_rgb,
        grid_pc,
        resolution,
        x_offset=float(adjust_ew_m),
        y_offset=float(adjust_ns_m),
        printf=printf,
    )

    if bool(auto_red_mask_enabled):
        _report_progress(progress_callback, 64, "Applying the aligned Auto Red Mask and buffer...")
        auto_mask_kwargs = {
            "buffer_m": float(auto_red_mask_buffer_m),
            "x_offset": float(adjust_ew_m),
            "y_offset": float(adjust_ns_m),
            "printf": printf,
        }
        # Keep old verifier/test call signatures untouched when roads are off.
        if bool(include_vehicle_roads):
            auto_mask_kwargs.update({
                "include_vehicle_roads": True,
                "vehicle_road_width_m": float(
                    expected.get("vehicle_road_width_m", DEFAULT_VEHICLE_ROAD_WIDTH_M)
                ),
            })
        mask_rgb = auto_red_mask.apply_auto_red_mask(
            osm_result,
            mask_rgb,
            grid_pc,
            resolution,
            **auto_mask_kwargs,
        )
    else:
        printf("Auto Red Mask is disabled; writing the aligned OSM/terrain mask without red exclusion.")
        _report_progress(progress_callback, 72, "Auto Red Mask disabled; preserving aligned OSM overlay.")

    _report_progress(progress_callback, 78, "Backing up the existing mask and preparing atomic output...")
    backup_path = None
    if backup_existing and mask_path.is_file():
        backup_path = _next_backup_path(folder)
        shutil.copy2(mask_path, backup_path)
        printf("Backed up existing mask.png to: " + str(backup_path))

    sidecar_path = folder / SIDECAR_NAME
    old_sidecar = sidecar_path.read_bytes() if sidecar_path.is_file() else None

    try:
        _report_progress(progress_callback, 86, "Writing and verifying the aligned mask...")
        _write_mask_atomic(
            mask_path,
            mask_rgb,
            (int(heightmap.shape[0]), int(heightmap.shape[1])),
        )

        _report_progress(progress_callback, 94, "Recording the final alignment sidecar...")
        record = dict(expected)
        record.update({
            "recorded_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "mask_mode": "rebuilt_from_final_cfs_alignment",
            "mask_file": str(mask_path.resolve()),
            "mask_sha256_at_rebuild": _sha256_file(mask_path),
            "manual_mask_edits_permitted_after_rebuild": True,
        })
        _atomic_write_text(
            sidecar_path,
            json.dumps(record, indent=2, sort_keys=True) + "\n",
        )
    except Exception:
        if backup_path is not None and backup_path.is_file():
            shutil.copy2(backup_path, mask_path)
        if old_sidecar is not None:
            sidecar_path.write_bytes(old_sidecar)
        else:
            try:
                sidecar_path.unlink()
            except Exception:
                pass
        raise

    _report_progress(progress_callback, 100, "Aligned mask rebuilt and verified.")
    printf(
        "Aligned mask verified: " + str(int(heightmap.shape[1])) + " x " +
        str(int(heightmap.shape[0])) + " pixels."
    )
    printf(
        "Final mask alignment recorded. Complete any intended manual edits to "
        "mask.png before importing terrain and OSM into the course."
    )

    return {
        "action": "rebuilt",
        "message": (
            "mask.png was rebuilt from the final CFS alignment. "
            "Complete any intended manual mask edits before importing the course."
        ),
        "mask_path": str(mask_path),
        "backup_path": None if backup_path is None else str(backup_path),
        "sidecar_path": str(sidecar_path),
        "record": record,
    }


def adopt_existing_zero_shift_mask(
    heightmap_dir: str | Path,
    osm_file: str | Path,
    adjust_ew_m: float,
    adjust_ns_m: float,
    auto_red_mask_enabled: bool = True,
    auto_red_mask_buffer_m: float = 5.0,
    include_vehicle_roads: bool = False,
    custom_unmatched_osm: bool = False,
    printf=print,
) -> Dict[str, Any]:
    """Record a legacy zero-shift mask without changing any painted pixels."""
    if bool(custom_unmatched_osm):
        raise RuntimeError(
            "Custom / Unmatched OSM masks cannot adopt legacy geographic pixels; rebuild the mask."
        )
    ew, ns, _enabled, _buffer = _normalize_settings(
        adjust_ew_m,
        adjust_ns_m,
        auto_red_mask_enabled,
        auto_red_mask_buffer_m,
    )
    if abs(ew) > ALIGNMENT_TOLERANCE_M or abs(ns) > ALIGNMENT_TOLERANCE_M:
        raise RuntimeError(
            "Only an existing 0.00/0.00 alignment mask can be adopted without rebuilding."
        )

    folder, _heightmap_path, mask_path, data, heightmap, grid = _load_heightmap(heightmap_dir)
    expected_shape = (int(heightmap.shape[0]), int(heightmap.shape[1]))
    if _mask_shape(mask_path) != expected_shape:
        raise RuntimeError("Existing mask.png does not match the heightmap dimensions.")

    expected = _signature(
        folder,
        data,
        heightmap,
        grid,
        osm_file,
        ew,
        ns,
        auto_red_mask_enabled,
        auto_red_mask_buffer_m,
        include_vehicle_roads=include_vehicle_roads,
        custom_unmatched_osm=custom_unmatched_osm,
    )

    original_master_osm = data.get("osm_master_file")
    if original_master_osm:
        original_path = Path(str(original_master_osm))
        if original_path.is_file() and _sha256_file(original_path) != expected["osm_sha256"]:
            raise RuntimeError(
                "The selected OSM differs from the OSM used to create the master terrain grid; "
                "the existing mask cannot be adopted safely."
            )

    record = dict(expected)
    record.update({
        "recorded_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "mask_mode": "adopted_existing_zero_shift_mask",
        "mask_file": str(mask_path.resolve()),
        "mask_sha256_at_adoption": _sha256_file(mask_path),
        "manual_mask_edits_permitted_after_rebuild": True,
    })

    sidecar_path = folder / SIDECAR_NAME
    _atomic_write_text(
        sidecar_path,
        json.dumps(record, indent=2, sort_keys=True) + "\n",
    )

    printf(
        "Adopted existing zero-shift mask without changing mask.png. "
        "Alignment tracking is now current."
    )
    return {
        "action": "adopted",
        "message": "The existing zero-shift mask was adopted without changing its pixels.",
        "mask_path": str(mask_path),
        "backup_path": None,
        "sidecar_path": str(sidecar_path),
        "record": record,
    }
