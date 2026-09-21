import json
from pathlib import Path

import pyproj

from GeoPointCloud import GeoPointCloud

MASTER_GRID_VERSION = 1


def _projection_crs(projection):
    if projection is None:
        return None
    try:
        crs = getattr(projection, "crs", None)
        if crs is not None:
            return pyproj.CRS.from_user_input(crs)
    except Exception:
        pass
    for candidate in (getattr(projection, "srs", None), projection):
        if candidate is None:
            continue
        try:
            return pyproj.CRS.from_user_input(candidate)
        except Exception:
            pass
    return None


def horizontal_epsg(projection):
    crs = _projection_crs(projection)
    if crs is None:
        return None
    try:
        epsg = crs.to_epsg()
        if epsg is not None:
            return int(epsg)
    except Exception:
        pass
    try:
        for sub in list(crs.sub_crs_list or []):
            if getattr(sub, "is_projected", False):
                epsg = sub.to_epsg()
                if epsg is not None:
                    return int(epsg)
    except Exception:
        pass
    return None


def crs_wkt(projection):
    crs = _projection_crs(projection)
    if crs is None:
        return None
    try:
        return crs.to_wkt()
    except Exception:
        return None


def _latlon_to_projected_meters(lat, lon, projection):
    # Use the exact pyproj.Proj object already used by TGC Designer Tools.
    # Modern LiDAR parsing creates this with preserve_units=False, so its XY
    # output matches the terrain's metre-normalized coordinates.
    pc = GeoPointCloud()
    pc.proj = projection
    pc.origin = (0.0, 0.0)
    x, y = pc.latlonToProj(float(lat), float(lon))
    return float(x), float(y)


def _projected_meters_to_latlon(x, y, projection):
    pc = GeoPointCloud()
    pc.proj = projection
    pc.origin = (0.0, 0.0)
    lat, lon = pc.projToLatLon(float(x), float(y))
    return float(lat), float(lon)


def make_master_grid_from_crop(pc, lower_x, lower_y, upper_x, upper_y, resolution, source="LiDAR/DEM"):
    """Create the authoritative projected grid for a cropped terrain raster.

    Current TGC internals store row 0 at the south.  We preserve that storage
    convention, but make the projected cell-edge affine explicit.
    """
    resolution = float(resolution)
    lower_x = int(lower_x)
    lower_y = int(lower_y)
    upper_x = int(upper_x)
    upper_y = int(upper_y)

    cols = max(0, upper_x - lower_x)
    rows = max(0, upper_y - lower_y)

    # IMPORTANT: use the southwest CELL EDGE, not cv2ToLatLon(), which returns
    # the centre of a pixel.
    enu_x = float(lower_x) * resolution
    enu_y = float(lower_y) * resolution
    min_x, min_y = pc.enuToProj(enu_x, enu_y)
    min_x = float(min_x)
    min_y = float(min_y)

    ll_lat, ll_lon = pc.enuToLatLon(enu_x, enu_y)

    return {
        "version": MASTER_GRID_VERSION,
        "logic": "CFS-style projected master affine",
        "source": str(source),
        "resolution": resolution,
        "rows": rows,
        "cols": cols,
        "min_x": min_x,
        "min_y": min_y,
        "max_x": min_x + cols * resolution,
        "max_y": min_y + rows * resolution,
        "row_order": "south_up_internal",
        "origin_semantics": "southwest_cell_edge",
        "lower_left_latlon": [float(ll_lat), float(ll_lon)],
        "horizontal_epsg": horizontal_epsg(pc.proj),
        "crs_wkt": crs_wkt(pc.proj),
        "xy_units": "meters",
    }


def infer_master_grid_from_legacy_heightmap(read_dictionary, heightmap, printf=print):
    """Recover the exact cell-edge grid from an older heightmap.npy.

    Historical TGC Designer Tools saved origin = cv2ToLatLon(first pixel).
    That function returns the FIRST PIXEL CENTRE. Later addFromImage() treated
    it as the grid edge and added another half-cell. Correct by subtracting
    0.5 * image_scale in projected metres.
    """
    if "origin" not in read_dictionary or "projection" not in read_dictionary:
        raise ValueError("Legacy heightmap lacks origin/projection metadata")

    resolution = float(read_dictionary["image_scale"])
    projection = read_dictionary["projection"]
    lat, lon = read_dictionary["origin"][:2]

    center_x, center_y = _latlon_to_projected_meters(lat, lon, projection)
    min_x = center_x - 0.5 * resolution
    min_y = center_y - 0.5 * resolution

    rows = int(heightmap.shape[0])
    cols = int(heightmap.shape[1])
    ll_lat, ll_lon = _projected_meters_to_latlon(min_x, min_y, projection)

    printf(
        "CFS GeoReference Lock: legacy heightmap detected; correcting "
        "historical first-pixel-centre origin by -0.5 cell ("
        + str(round(0.5 * resolution, 4)) + " m E/W and N/S)."
    )

    return {
        "version": MASTER_GRID_VERSION,
        "logic": "CFS-style projected master affine",
        "source": str(read_dictionary.get("source", "legacy heightmap")),
        "resolution": resolution,
        "rows": rows,
        "cols": cols,
        "min_x": float(min_x),
        "min_y": float(min_y),
        "max_x": float(min_x + cols * resolution),
        "max_y": float(min_y + rows * resolution),
        "row_order": "south_up_internal",
        "origin_semantics": "southwest_cell_edge",
        "lower_left_latlon": [float(ll_lat), float(ll_lon)],
        "horizontal_epsg": horizontal_epsg(projection),
        "crs_wkt": crs_wkt(projection),
        "xy_units": "meters",
        "legacy_half_cell_origin_corrected": True,
    }


def get_master_grid(read_dictionary, heightmap, printf=print):
    grid = read_dictionary.get("master_grid")
    if isinstance(grid, dict):
        required = ("resolution", "rows", "cols", "min_x", "min_y", "lower_left_latlon")
        if all(key in grid for key in required):
            printf("CFS GeoReference Lock: using stored projected master grid.")
            return dict(grid)
    return infer_master_grid_from_legacy_heightmap(read_dictionary, heightmap, printf=printf)


def master_grid_origin_latlon(grid):
    value = grid.get("lower_left_latlon")
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("Master grid has no southwest WGS84 coordinate")
    return float(value[0]), float(value[1])


def validate_projection(projection, printf=print):
    crs = _projection_crs(projection)
    if crs is None:
        raise ValueError("Terrain horizontal CRS could not be resolved")
    if not bool(getattr(crs, "is_projected", False)):
        raise ValueError(
            "Terrain CRS is not a projected horizontal CRS. Use the correct "
            "Force LiDAR Horizontal EPSG / DEM horizontal CRS before OSM import."
        )

    epsg = horizontal_epsg(projection)
    if epsg is not None:
        printf(
            "CFS GeoReference Lock: OSM source EPSG:4326 -> terrain horizontal EPSG:"
            + str(epsg)
        )
    else:
        printf(
            "CFS GeoReference Lock: OSM source EPSG:4326 -> terrain embedded "
            "projected horizontal CRS (no simple EPSG code)"
        )
    return True


def describe_master_grid(grid, printf=print):
    printf(
        "CFS master grid: " + str(grid.get("cols")) + " x " + str(grid.get("rows"))
        + " at " + str(grid.get("resolution")) + " m"
    )
    printf(
        "  projected bounds min=(" + str(round(float(grid.get("min_x", 0.0)), 3))
        + ", " + str(round(float(grid.get("min_y", 0.0)), 3)) + ") max=("
        + str(round(float(grid.get("max_x", 0.0)), 3)) + ", "
        + str(round(float(grid.get("max_y", 0.0)), 3)) + ")"
    )
    if grid.get("horizontal_epsg") is not None:
        printf("  horizontal EPSG: " + str(grid.get("horizontal_epsg")))
    printf("  OSM source CRS: EPSG:4326 (WGS84 lon/lat)")


def write_master_grid_json(directory, grid, filename="cfs_master_grid.json"):
    path = Path(directory) / filename
    safe = {}
    for key, value in grid.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[key] = list(value)
        else:
            safe[key] = str(value)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
