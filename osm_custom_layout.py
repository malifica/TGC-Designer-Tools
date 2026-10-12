"""Custom / unmatched OSM placement for Beta 6.

When a Local OSM comes from a different geographic location than the selected
LiDAR/DEM terrain, its absolute WGS84 position is intentionally ignored. The
course-layout geometry is projected into a local metric AEQD frame, centered
on a golf-course anchor extent, then translated onto the center of the terrain
master grid.

The anchor deliberately ignores unrelated surrounding OSM geography. It
prefers golf=hole ways, then other golf-layout ways/relations, and only falls
back to the full OSM node set if no course semantics are available.

No rotation or scale is applied in this phase. CFS E/W and N/S alignment remain
the only manual transform.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyproj

PATCH_ID = "TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5"
PATCH_ID_V5_1 = "TGC_BETA6_CUSTOM_UNMATCHED_OSM_V5_1"

_GOLF_LAYOUT_VALUES = {
    "hole",
    "green",
    "tee",
    "fairway",
    "bunker",
    "rough",
    "driving_range",
    "practice",
    "cartpath",
    "path",
    "water_hazard",
    "lateral_water_hazard",
}


def _finite_node_rows(nodes) -> list[tuple[float, float]]:
    rows = []
    seen = set()
    for node in nodes or []:
        try:
            lat = float(node.lat)
            lon = float(node.lon)
        except Exception:
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        key = (round(lat, 12), round(lon, 12))
        if key in seen:
            continue
        seen.add(key)
        rows.append((lat, lon))
    return rows


def _nodes_from_ways(ways) -> list[tuple[float, float]]:
    nodes = []
    for way in ways or []:
        try:
            nodes.extend(way.get_nodes(resolve_missing=False))
        except Exception:
            continue
    return _finite_node_rows(nodes)


def _relation_member_ways(osm_result, relation_predicate):
    way_lookup = {
        getattr(way, "id", None): way
        for way in getattr(osm_result, "ways", []) or []
    }
    selected = []
    seen = set()
    for rel in getattr(osm_result, "relations", []) or []:
        tags = getattr(rel, "tags", {}) or {}
        if not relation_predicate(tags):
            continue
        for member in getattr(rel, "members", []) or []:
            ref = getattr(member, "ref", None)
            way = way_lookup.get(ref)
            if way is None:
                continue
            wid = getattr(way, "id", id(way))
            if wid in seen:
                continue
            seen.add(wid)
            selected.append(way)
    return selected


def _course_anchor_nodes(osm_result) -> tuple[list[tuple[float, float]], str]:
    """Return the smallest reliable course-layout node set for centering.

    Large Overpass/JOSM exports commonly contain miles of roads, waterways and
    other unrelated context. Using every node for detached-layout centering can
    place the actual golf course far outside the terrain preview. Prefer the
    actual golf-hole centerlines because they describe the playable layout most
    directly and are normally present in TGC OSM files.
    """
    ways = list(getattr(osm_result, "ways", []) or [])

    hole_ways = [
        way for way in ways
        if str((getattr(way, "tags", {}) or {}).get("golf", "")).lower() == "hole"
    ]
    rows = _nodes_from_ways(hole_ways)
    if rows:
        return rows, "golf=hole ways"

    golf_ways = [
        way for way in ways
        if str((getattr(way, "tags", {}) or {}).get("golf", "")).lower()
        in _GOLF_LAYOUT_VALUES
    ]
    rows = _nodes_from_ways(golf_ways)
    if rows:
        return rows, "golf layout ways"

    relation_ways = _relation_member_ways(
        osm_result,
        lambda tags: (
            str(tags.get("golf", "")).lower() in _GOLF_LAYOUT_VALUES
            or str(tags.get("leisure", "")).lower() == "golf_course"
        ),
    )
    rows = _nodes_from_ways(relation_ways)
    if rows:
        return rows, "golf layout relations"

    # A mapped golf-course boundary is useful when hole ways are absent.
    leisure_ways = [
        way for way in ways
        if str((getattr(way, "tags", {}) or {}).get("leisure", "")).lower()
        == "golf_course"
    ]
    rows = _nodes_from_ways(leisure_ways)
    if rows:
        return rows, "leisure=golf_course ways"

    # Last-resort fallback preserves V5 behavior for unusual custom OSMs that
    # do not contain any recognizable golf semantics.
    rows = _finite_node_rows(getattr(osm_result, "nodes", []) or [])
    if rows:
        return rows, "all OSM nodes fallback"

    rows = _nodes_from_ways(ways)
    if rows:
        return rows, "all OSM ways fallback"

    return [], "none"


@dataclass(frozen=True)
class CustomOSMPlacement:
    """One deterministic translation-only detached-layout transform."""

    lat0: float
    lon0: float
    source_center_x: float
    source_center_y: float
    target_center_x: float
    target_center_y: float
    width_m: float
    height_m: float
    transformer: Any
    anchor_strategy: str
    anchor_node_count: int

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = self.transformer.transform(float(lon), float(lat))
        return (
            float(self.target_center_x) + float(x) - float(self.source_center_x),
            float(self.target_center_y) + float(y) - float(self.source_center_y),
        )

    def project_arrays(self, lons, lats):
        xs, ys = self.transformer.transform(lons, lats)
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        return (
            float(self.target_center_x) + xs - float(self.source_center_x),
            float(self.target_center_y) + ys - float(self.source_center_y),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "source_center_lat": float(self.lat0),
            "source_center_lon": float(self.lon0),
            "source_width_m": float(self.width_m),
            "source_height_m": float(self.height_m),
            "target_center_x": float(self.target_center_x),
            "target_center_y": float(self.target_center_y),
            "anchor_strategy": str(self.anchor_strategy),
            "anchor_node_count": int(self.anchor_node_count),
        }


def build_custom_placement(
    osm_result,
    target_center_x: float,
    target_center_y: float,
) -> CustomOSMPlacement:
    nodes, anchor_strategy = _course_anchor_nodes(osm_result)
    if not nodes:
        raise ValueError("Custom / Unmatched OSM contains no usable latitude/longitude nodes.")

    lats = np.asarray([row[0] for row in nodes], dtype=np.float64)
    lons = np.asarray([row[1] for row in nodes], dtype=np.float64)
    lat0 = float((np.min(lats) + np.max(lats)) * 0.5)
    lon0 = float((np.min(lons) + np.max(lons)) * 0.5)

    local_crs = pyproj.CRS.from_proj4(
        "+proj=aeqd +lat_0=" + repr(lat0) +
        " +lon_0=" + repr(lon0) +
        " +datum=WGS84 +units=m +no_defs"
    )
    transformer = pyproj.Transformer.from_crs(
        pyproj.CRS.from_epsg(4326),
        local_crs,
        always_xy=True,
    )
    xs, ys = transformer.transform(lons, lats)
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    valid = np.isfinite(xs) & np.isfinite(ys)
    if not np.any(valid):
        raise ValueError("Custom / Unmatched OSM could not be projected into a local metric frame.")
    xs = xs[valid]
    ys = ys[valid]
    min_x = float(np.min(xs)); max_x = float(np.max(xs))
    min_y = float(np.min(ys)); max_y = float(np.max(ys))
    return CustomOSMPlacement(
        lat0=lat0,
        lon0=lon0,
        source_center_x=(min_x + max_x) * 0.5,
        source_center_y=(min_y + max_y) * 0.5,
        target_center_x=float(target_center_x),
        target_center_y=float(target_center_y),
        width_m=max_x - min_x,
        height_m=max_y - min_y,
        transformer=transformer,
        anchor_strategy=anchor_strategy,
        anchor_node_count=len(nodes),
    )


def placement_for_master_grid(osm_result, grid) -> CustomOSMPlacement:
    min_x = float(grid["min_x"])
    min_y = float(grid["min_y"])
    max_x = float(grid.get("max_x", min_x))
    max_y = float(grid.get("max_y", min_y))
    if max_x <= min_x:
        max_x = min_x + float(grid["resolution"]) * float(grid.get("cols", 0))
    if max_y <= min_y:
        max_y = min_y + float(grid["resolution"]) * float(grid.get("rows", 0))
    return build_custom_placement(
        osm_result,
        (min_x + max_x) * 0.5,
        (min_y + max_y) * 0.5,
    )


class CustomTGCPointCloud:
    """Delegate terrain bounds to GeoPointCloud, but detach OSM geolocation."""

    def __init__(self, base_pc, placement: CustomOSMPlacement):
        self._base = base_pc
        self._placement = placement

    def ulENU(self):
        return self._base.ulENU()

    def lrENU(self):
        return self._base.lrENU()

    def enuToTGC(self, x, y, z):
        return self._base.enuToTGC(x, y, z)

    def latlonToTGC(self, lat, lon, offset_x=0.0, offset_y=0.0):
        px, py = self._placement.project(float(lon), float(lat))
        return self._base.projToTGC(
            px + float(offset_x),
            py + float(offset_y),
            0.0,
        )

    def latlonToCV2(self, lat, lon, image_scale, offset_x=0.0, offset_y=0.0):
        """Detached OSM projection for LiDAR/DEM preview and mask drawing."""
        px, py = self._placement.project(float(lon), float(lat))
        return self._base.projToCV2(
            px + float(offset_x),
            py + float(offset_y),
            image_scale,
        )

    def __getattr__(self, name):
        return getattr(self._base, name)
