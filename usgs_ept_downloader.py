import csv
import io
import json
import math
import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import laspy
import numpy as np
import pyproj
import requests

TNM_PRODUCTS_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"
USGS_EPT_BASE_URL = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public"
DEFAULT_OSM_BUFFER_M = 150.0
HTTP_TIMEOUT = (15, 120)
WESM_CSV_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/metadata/WESM.csv"
WESM_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

QL_REFERENCE = {
    "QL 0": "≤0.35 m pulse spacing / ≥8 pulses/m²",
    "QL 1": "≤0.35 m pulse spacing / ≥8 pulses/m²",
    "QL 2": "≤0.71 m pulse spacing / ≥2 pulses/m²",
    "QL 3": "≤1.41 m pulse spacing / ≥0.5 pulses/m²",
}


def _tag_dict(element):
    return {
        str(tag.attrib.get("k", "")): str(tag.attrib.get("v", ""))
        for tag in element.findall("tag")
    }


def _closed_way_coords(way, nodes):
    refs = [nd.attrib.get("ref") for nd in way.findall("nd")]
    coords = [nodes.get(ref) for ref in refs if ref in nodes]
    coords = [value for value in coords if value is not None]
    if len(coords) < 3:
        return []
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def _polygon_area_lonlat(coords):
    if len(coords) < 4:
        return 0.0
    mean_lat = sum(lat for lon, lat in coords) / len(coords)
    sx = 111320.0 * max(0.1, math.cos(math.radians(mean_lat)))
    sy = 110540.0
    area2 = 0.0
    for i in range(len(coords) - 1):
        x1, y1 = coords[i][0] * sx, coords[i][1] * sy
        x2, y2 = coords[i + 1][0] * sx, coords[i + 1][1] * sy
        area2 += x1 * y2 - x2 * y1
    return abs(area2) * 0.5


def _stitch_way_refs(member_refs, ways, nodes):
    fragments = []
    for ref in member_refs:
        way = ways.get(ref)
        if way is None:
            continue
        ids = [nd.attrib.get("ref") for nd in way.findall("nd")]
        ids = [value for value in ids if value in nodes]
        if len(ids) >= 2:
            fragments.append(ids)

    rings = []
    while fragments:
        chain = fragments.pop(0)
        progress = True
        while chain[0] != chain[-1] and progress:
            progress = False
            for i, candidate in enumerate(fragments):
                if chain[-1] == candidate[0]:
                    chain.extend(candidate[1:])
                elif chain[-1] == candidate[-1]:
                    chain.extend(list(reversed(candidate[:-1])))
                elif chain[0] == candidate[-1]:
                    chain = candidate[:-1] + chain
                elif chain[0] == candidate[0]:
                    chain = list(reversed(candidate[1:])) + chain
                else:
                    continue
                fragments.pop(i)
                progress = True
                break
        if len(chain) >= 4 and chain[0] == chain[-1]:
            rings.append([nodes[node_id] for node_id in chain])
    return rings


def read_osm_course_bounds(osm_file, buffer_m=DEFAULT_OSM_BUFFER_M, printf=print):
    """Return a buffered WGS84 bbox derived from the local OSM golf boundary."""
    osm_path = Path(osm_file)
    if not osm_path.is_file():
        raise FileNotFoundError("Local OSM file was not found: " + str(osm_file))

    root = ET.parse(osm_path).getroot()
    nodes = {}
    for node in root.findall("node"):
        node_id = node.attrib.get("id")
        try:
            lon = float(node.attrib["lon"])
            lat = float(node.attrib["lat"])
        except Exception:
            continue
        nodes[node_id] = (lon, lat)

    if not nodes:
        raise ValueError("Local OSM contains no usable latitude/longitude nodes")

    ways = {way.attrib.get("id"): way for way in root.findall("way")}
    boundary_rings = []

    for way in ways.values():
        tags = _tag_dict(way)
        if not (
            tags.get("leisure") == "golf_course" or
            tags.get("golf") == "course"
        ):
            continue
        coords = _closed_way_coords(way, nodes)
        if coords:
            boundary_rings.append(coords)

    for rel in root.findall("relation"):
        tags = _tag_dict(rel)
        if tags.get("type") != "multipolygon":
            continue
        if not (
            tags.get("leisure") == "golf_course" or
            tags.get("golf") == "course"
        ):
            continue
        refs = [
            member.attrib.get("ref")
            for member in rel.findall("member")
            if (
                member.attrib.get("type") == "way" and
                str(member.attrib.get("role", "")).lower() in ("", "outer")
            )
        ]
        boundary_rings.extend(_stitch_way_refs(refs, ways, nodes))

    if boundary_rings:
        boundary = max(boundary_rings, key=_polygon_area_lonlat)
        source = "explicit golf-course boundary"
    else:
        boundary = list(nodes.values())
        source = "all OSM nodes (no explicit golf-course boundary found)"

    min_lon = min(value[0] for value in boundary)
    max_lon = max(value[0] for value in boundary)
    min_lat = min(value[1] for value in boundary)
    max_lat = max(value[1] for value in boundary)

    buffer_m = max(0.0, float(buffer_m))
    center_lat = 0.5 * (min_lat + max_lat)
    lat_pad = buffer_m / 110540.0
    lon_scale = 111320.0 * max(0.1, math.cos(math.radians(center_lat)))
    lon_pad = buffer_m / lon_scale

    bbox = (
        min_lon - lon_pad,
        min_lat - lat_pad,
        max_lon + lon_pad,
        max_lat + lat_pad,
    )

    printf(
        "AWS EPT OSM extent source: " + source +
        "; buffer=" + str(round(buffer_m, 1)) + " m"
    )
    printf(
        "AWS EPT WGS84 bounds: " +
        ", ".join(str(round(value, 7)) for value in bbox)
    )
    return bbox


def _rectangle_polygon_param(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    coords = [
        (min_lon, max_lat),
        (max_lon, max_lat),
        (max_lon, min_lat),
        (min_lon, min_lat),
        (min_lon, max_lat),
    ]
    return ",".join(str(lon) + " " + str(lat) for lon, lat in coords)


def _project_and_workunit_from_laz_url(url):
    try:
        parts = [part for part in urlparse(url).path.split("/") if part]
        upper = [part.upper() for part in parts]
        laz_index = upper.index("LAZ")
        workunit = parts[laz_index - 1] if laz_index >= 1 else ""
        project = parts[laz_index - 2] if laz_index >= 2 else workunit
        return project, workunit
    except Exception:
        return "", ""


def _item_laz_url(item):
    urls = item.get("urls") or {}
    if isinstance(urls, dict):
        for key in ("LAZ", "LAS", "laz", "las"):
            value = urls.get(key)
            if value:
                return str(value)
    for key in ("downloadURL", "url"):
        value = item.get(key)
        if value and str(value).lower().endswith((".laz", ".las")):
            return str(value)
    return ""


def _project_year_score(project_name):
    text = str(project_name or "")
    years = [
        int(value)
        for value in re.findall(r"(?<!\\d)(20\\d{2})(?!\\d)", text)
    ]
    if years:
        return max(years)
    batches = [
        int(value)
        for value in re.findall(
            r"(?:^|[_-])[A-Z](\\d{2})(?:$|[_-])",
            text,
            re.I,
        )
    ]
    if batches:
        return 2000 + max(batches)
    return 0


def discover_tnm_projects(bbox, printf=print, session=None):
    session = session or requests.Session()
    params = {
        "datasets": "Lidar Point Cloud (LPC)",
        "prodFormats": "LAS,LAZ",
        "polygon": _rectangle_polygon_param(bbox),
        "max": 500,
    }
    printf("Querying The National Map for LiDAR projects intersecting the OSM extent...")
    response = session.get(TNM_PRODUCTS_URL, params=params, timeout=HTTP_TIMEOUT)
    if response.status_code >= 400:
        params.pop("polygon", None)
        params["bbox"] = ",".join(str(value) for value in bbox)
        response = session.get(TNM_PRODUCTS_URL, params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    items = list(payload.get("items") or [])
    if not items:
        raise RuntimeError(
            "The National Map returned no LAS/LAZ products for this OSM extent"
        )

    projects = {}
    for item in items:
        laz_url = _item_laz_url(item)
        if not laz_url:
            continue
        project, workunit = _project_and_workunit_from_laz_url(laz_url)
        if not workunit:
            continue
        if not project:
            project = workunit
        entry = projects.setdefault(
            project,
            {
                "workunits": set(),
                "items": [],
                "year": _project_year_score(project),
            },
        )
        entry["workunits"].add(workunit)
        entry["items"].append(item)

    if not projects:
        raise RuntimeError(
            "LiDAR products were found, but their USGS project/work-unit "
            "names could not be resolved"
        )

    ordered = sorted(
        projects.items(),
        key=lambda pair: (
            pair[1]["year"],
            len(pair[1]["items"]),
            pair[0],
        ),
        reverse=True,
    )
    printf(
        "TNM candidate LiDAR projects (newest first): " +
        "; ".join(
            name + " [" + ", ".join(sorted(info["workunits"])) + "]"
            for name, info in ordered[:8]
        )
    )
    return ordered



def _normalize_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _normalize_row(row):
    return {
        str(key or "").strip().lower(): str(value or "").strip()
        for key, value in dict(row or {}).items()
    }


def _download_wesm_csv(cache_dir, session=None, printf=print):
    session = session or requests.Session()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "WESM.csv"

    if cache_path.exists():
        try:
            age = time.time() - cache_path.stat().st_mtime
            if age <= WESM_CACHE_MAX_AGE_SECONDS:
                printf(
                    "Using cached USGS WESM metadata (" +
                    str(round(age / 3600.0, 1)) + " hours old)."
                )
                return cache_path
        except Exception:
            pass

    printf("Downloading current USGS WESM metadata table...")
    response = session.get(WESM_CSV_URL, timeout=(15, 180))
    response.raise_for_status()
    cache_path.write_bytes(response.content)
    printf(
        "WESM metadata cached: " +
        str(round(len(response.content) / (1024.0 * 1024.0), 2)) + " MB"
    )
    return cache_path


def _load_wesm_rows(cache_dir, session=None, printf=print):
    try:
        path = _download_wesm_csv(
            cache_dir,
            session=session,
            printf=printf,
        )
        rows = []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                rows.append(_normalize_row(row))
        printf("WESM work-unit rows loaded: " + str(len(rows)))
        return rows
    except Exception as exc:
        printf(
            "Warning: USGS WESM metadata could not be loaded: " +
            str(exc)
        )
        printf(
            "Dataset choices will still be shown, but some quality/date "
            "fields may be unavailable."
        )
        return []


def _unique_values(rows, key):
    values = []
    seen = set()
    for row in rows:
        value = str(row.get(key, "") or "").strip()
        if not value:
            continue
        folded = value.lower()
        if folded in seen:
            continue
        seen.add(folded)
        values.append(value)
    return values


def _join_values(rows, key, fallback=""):
    values = _unique_values(rows, key)
    return ", ".join(values) if values else fallback


def _min_date(rows, key):
    values = sorted(_unique_values(rows, key))
    return values[0] if values else ""


def _max_date(rows, key):
    values = sorted(_unique_values(rows, key))
    return values[-1] if values else ""


def _format_gsd(rows):
    values = []
    for raw in _unique_values(rows, "dem_gsd_meters"):
        try:
            value = float(raw)
        except Exception:
            continue
        if value <= 0.0 or not math.isfinite(value):
            continue
        values.append(value)
    if not values:
        return ""
    values = sorted(set(round(value, 4) for value in values))
    if len(values) == 1:
        return str(values[0]) + " m"
    return " / ".join(str(value) + " m" for value in values)


def _quality_reference_label(ql_text):
    parts = []
    for value in [piece.strip() for piece in str(ql_text or "").split(",")]:
        detail = QL_REFERENCE.get(value.upper().replace("QL", "QL ").replace("  ", " "))
        if detail:
            parts.append(value + ": " + detail)
    return "; ".join(parts)


def _match_wesm_rows(wesm_rows, project, workunits):
    if not wesm_rows:
        return []

    wanted_workunits = {
        _normalize_name(value)
        for value in workunits
        if str(value or "").strip()
    }
    wanted_project = _normalize_name(project)

    exact_workunit = [
        row for row in wesm_rows
        if _normalize_name(row.get("workunit")) in wanted_workunits
    ]
    if exact_workunit:
        return exact_workunit

    exact_project = [
        row for row in wesm_rows
        if _normalize_name(row.get("project")) == wanted_project
    ]
    return exact_project


def _aggregate_wesm_metadata(rows):
    ql = _join_values(rows, "ql")
    metadata = {
        "collect_start": _min_date(rows, "collect_start"),
        "collect_end": _max_date(rows, "collect_end"),
        "ql": ql,
        "ql_reference": _quality_reference_label(ql),
        "spec": _join_values(rows, "spec"),
        "production_method": _join_values(rows, "p_method"),
        "dem_gsd": _format_gsd(rows),
        "horizontal_crs": _join_values(rows, "horiz_crs"),
        "vertical_crs": _join_values(rows, "vert_crs"),
        "geoid": _join_values(rows, "geoid"),
        "lpc_pub_date": _max_date(rows, "lpc_pub_date"),
        "lpc_category": _join_values(rows, "lpc_category"),
        "lpc_reason": _join_values(rows, "lpc_reason"),
        "metadata_link": _join_values(rows, "metadata_link"),
        "source_dem_link": _join_values(rows, "sourcedem_link"),
        "lpc_link": _join_values(rows, "lpc_link"),
    }
    return metadata


def _fallback_tnm_metadata(project, info):
    dates = []
    for item in info.get("items", []):
        for key in ("dateCreated", "publicationDate", "lastUpdated"):
            value = item.get(key)
            if value:
                dates.append(str(value)[:10])
    dates = sorted(set(dates))
    return {
        "collect_start": "",
        "collect_end": "",
        "ql": "",
        "ql_reference": "",
        "spec": "",
        "production_method": "",
        "dem_gsd": "",
        "horizontal_crs": "",
        "vertical_crs": "",
        "geoid": "",
        "lpc_pub_date": dates[-1] if dates else "",
        "lpc_category": "",
        "lpc_reason": "",
        "metadata_link": "",
        "source_dem_link": "",
        "lpc_link": "",
    }


def _resolve_public_ept_resources(project, info, session=None):
    session = session or requests.Session()
    resolved = []
    missing = []

    for workunit in sorted(info["workunits"]):
        found = _get_ept_info(session, workunit)
        if found is None:
            missing.append(workunit)
        else:
            root_url, ept_info = found
            resolved.append((workunit, root_url, ept_info))

    if resolved and not missing:
        return resolved, ""

    project_resource = _get_ept_info(session, project)
    if project_resource is not None:
        root_url, ept_info = project_resource
        return [(project, root_url, ept_info)], ""

    if resolved:
        return [], (
            "Partial public EPT mirror; missing work unit(s): " +
            ", ".join(missing)
        )

    return [], "Not present in public AWS EPT mirror"


def discover_osm_ept_candidates(
    osm_file,
    output_root,
    buffer_m=DEFAULT_OSM_BUFFER_M,
    printf=print,
):
    """Discover every TNM LiDAR project overlapping the buffered OSM extent.

    Returns the WGS84 bbox plus a list of candidate dictionaries enriched with
    WESM acquisition/quality metadata and public-AWS-EPT availability.
    """
    bbox = read_osm_course_bounds(
        osm_file,
        buffer_m=buffer_m,
        printf=printf,
    )

    session = requests.Session()
    session.headers.update({
        "User-Agent": "TGC-Designer-Tools-Beta5/USGS-EPT"
    })

    projects = discover_tnm_projects(
        bbox,
        printf=printf,
        session=session,
    )

    cache_dir = Path(output_root) / "_TGC_CACHE"
    wesm_rows = _load_wesm_rows(
        cache_dir,
        session=session,
        printf=printf,
    )

    candidates = []
    for project, info in projects:
        workunits = sorted(info["workunits"])
        matched_rows = _match_wesm_rows(
            wesm_rows,
            project,
            workunits,
        )
        metadata = (
            _aggregate_wesm_metadata(matched_rows)
            if matched_rows
            else _fallback_tnm_metadata(project, info)
        )

        resources, ept_note = _resolve_public_ept_resources(
            project,
            info,
            session=session,
        )

        collection_year = 0
        for key in ("collect_end", "collect_start"):
            value = str(metadata.get(key, "") or "")
            match = re.search(r"(20\\d{2}|19\\d{2})", value)
            if match:
                collection_year = int(match.group(1))
                break
        if not collection_year:
            collection_year = int(info.get("year") or 0)

        candidate = {
            "project": project,
            "workunits": workunits,
            "collection_year": collection_year,
            "collect_start": metadata.get("collect_start", ""),
            "collect_end": metadata.get("collect_end", ""),
            "ql": metadata.get("ql", ""),
            "ql_reference": metadata.get("ql_reference", ""),
            "spec": metadata.get("spec", ""),
            "production_method": metadata.get("production_method", ""),
            "dem_gsd": metadata.get("dem_gsd", ""),
            "horizontal_crs": metadata.get("horizontal_crs", ""),
            "vertical_crs": metadata.get("vertical_crs", ""),
            "geoid": metadata.get("geoid", ""),
            "lpc_pub_date": metadata.get("lpc_pub_date", ""),
            "lpc_category": metadata.get("lpc_category", ""),
            "lpc_reason": metadata.get("lpc_reason", ""),
            "metadata_link": metadata.get("metadata_link", ""),
            "source_dem_link": metadata.get("source_dem_link", ""),
            "lpc_link": metadata.get("lpc_link", ""),
            "ept_available": bool(resources),
            "ept_note": (
                "Public AWS EPT available"
                if resources else ept_note
            ),
            "ept_resources": resources,
            "tnm_item_count": len(info.get("items", [])),
        }
        candidates.append(candidate)

    candidates.sort(
        key=lambda value: (
            int(value.get("collection_year") or 0),
            bool(value.get("ept_available")),
            str(value.get("project", "")),
        ),
        reverse=True,
    )

    printf(
        "LiDAR dataset choices discovered: " +
        str(len(candidates))
    )
    return bbox, candidates



def _ept_root_for_resource(resource_name):
    return USGS_EPT_BASE_URL + "/" + str(resource_name).strip("/")


def _get_json(session, url):
    response = session.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _get_ept_info(session, resource_name):
    root_url = _ept_root_for_resource(resource_name)
    try:
        info = _get_json(session, root_url + "/ept.json")
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 404:
            return None
        raise
    return root_url, info


def choose_public_ept_project(projects, printf=print, session=None):
    session = session or requests.Session()
    for project, info in projects:
        resources, note = _resolve_public_ept_resources(
            project,
            info,
            session=session,
        )
        if resources:
            printf(
                "Selected public AWS EPT project: " + project +
                " (" + str(len(resources)) + " resource(s))"
            )
            return project, resources
        printf("Skipping AWS EPT project " + project + ": " + note)

    raise RuntimeError(
        "No complete public AWS EPT mirror was found for the TNM LiDAR "
        "projects covering this OSM extent"
    )

def _ept_crs(info):
    srs = info.get("srs") or {}
    wkt = srs.get("wkt")
    if wkt:
        try:
            return pyproj.CRS.from_user_input(wkt)
        except Exception:
            pass

    authority = srs.get("authority")
    horizontal = srs.get("horizontal")
    if authority and horizontal:
        try:
            return pyproj.CRS.from_user_input(
                str(authority) + ":" + str(horizontal)
            )
        except Exception:
            pass

    raise RuntimeError(
        "EPT metadata does not contain a usable coordinate reference system"
    )


def _transform_bbox_wgs84_to_crs(bbox, crs):
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326",
        crs,
        always_xy=True,
    )
    min_lon, min_lat, max_lon, max_lat = bbox
    samples = []
    for fx in (0.0, 0.5, 1.0):
        for fy in (0.0, 0.5, 1.0):
            lon = min_lon + (max_lon - min_lon) * fx
            lat = min_lat + (max_lat - min_lat) * fy
            samples.append(transformer.transform(lon, lat))
    xs = [point[0] for point in samples]
    ys = [point[1] for point in samples]
    return (min(xs), min(ys), max(xs), max(ys))


def _node_bounds(root_bounds, key):
    d, ix, iy, iz = [int(value) for value in key.split("-")]
    divisions = float(1 << d)
    minx, miny, minz, maxx, maxy, maxz = [
        float(value) for value in root_bounds
    ]
    dx = (maxx - minx) / divisions
    dy = (maxy - miny) / divisions
    dz = (maxz - minz) / divisions
    return (
        minx + ix * dx,
        miny + iy * dy,
        minz + iz * dz,
        minx + (ix + 1) * dx,
        miny + (iy + 1) * dy,
        minz + (iz + 1) * dz,
    )


def _bounds_overlap_xy(node_bounds, query_bbox):
    return not (
        node_bounds[3] < query_bbox[0] or
        node_bounds[0] > query_bbox[2] or
        node_bounds[4] < query_bbox[1] or
        node_bounds[1] > query_bbox[3]
    )


def collect_ept_node_keys(
    root_url,
    info,
    query_bbox,
    session=None,
    printf=print,
):
    session = session or requests.Session()
    root_bounds = info.get("bounds")
    if not isinstance(root_bounds, (list, tuple)) or len(root_bounds) != 6:
        raise RuntimeError("EPT metadata contains invalid root bounds")

    data_type = str(info.get("dataType", "")).lower()
    if data_type not in ("laszip", "laz"):
        raise RuntimeError("Unsupported EPT dataType: " + str(info.get("dataType")))

    pending_hierarchies = ["0-0-0-0"]
    visited_hierarchies = set()
    positive_keys = set()

    while pending_hierarchies:
        hierarchy_key = pending_hierarchies.pop()
        if hierarchy_key in visited_hierarchies:
            continue
        visited_hierarchies.add(hierarchy_key)
        url = (
            root_url + "/ept-hierarchy/" +
            hierarchy_key + ".json"
        )
        hierarchy = _get_json(session, url)

        for key, count in hierarchy.items():
            try:
                count = int(count)
                bounds = _node_bounds(root_bounds, key)
            except Exception:
                continue

            if not _bounds_overlap_xy(bounds, query_bbox):
                continue

            if count == -1:
                pending_hierarchies.append(key)
            elif count > 0:
                positive_keys.add(key)

    ordered = sorted(
        positive_keys,
        key=lambda value: tuple(
            int(part) for part in value.split("-")
        ),
    )
    printf("AWS EPT overlapping LAZ nodes: " + str(len(ordered)))
    return ordered


def _write_filtered_node(
    session,
    root_url,
    key,
    query_bbox,
    crs,
    output_path,
):
    response = session.get(
        root_url + "/ept-data/" + key + ".laz",
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()

    las = laspy.read(io.BytesIO(response.content))
    x = np.asarray(las.x)
    y = np.asarray(las.y)
    mask = (
        (x >= query_bbox[0]) &
        (x <= query_bbox[2]) &
        (y >= query_bbox[1]) &
        (y <= query_bbox[3])
    )

    count = int(np.count_nonzero(mask))
    if count <= 0:
        return 0

    las.points = las.points[mask]

    try:
        existing = las.header.parse_crs()
    except Exception:
        existing = None

    if existing is None:
        las.header.add_crs(crs)

    las.write(output_path)
    return count


def download_candidate_ept_laz(
    candidate,
    bbox,
    output_root,
    osm_file=None,
    buffer_m=DEFAULT_OSM_BUFFER_M,
    printf=print,
):
    """Download one user-selected public-EPT acquisition into normal LAZ."""
    resources = list(candidate.get("ept_resources") or [])
    if not resources:
        raise RuntimeError(
            "Selected LiDAR dataset is not available in the public AWS EPT mirror"
        )

    output_root = Path(output_root)
    target = output_root / "USGS_AWS_EPT_LAZ"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "TGC-Designer-Tools-Beta5/USGS-EPT"
    })

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    project = str(candidate.get("project") or "")
    manifest = {
        "source": "USGS 3DEP public AWS EPT",
        "tnm_project": project,
        "selected_dataset": {
            key: value
            for key, value in candidate.items()
            if key not in ("ept_resources",)
        },
        "osm_file": (
            str(Path(osm_file).resolve())
            if osm_file else ""
        ),
        "buffer_m": float(buffer_m),
        "wgs84_bbox": list(bbox),
        "resources": [],
    }

    total_points = 0
    total_files = 0

    printf("Downloading selected LiDAR dataset: " + project)
    if candidate.get("collect_start") or candidate.get("collect_end"):
        printf(
            "  Collection: " +
            str(candidate.get("collect_start") or "?") + " to " +
            str(candidate.get("collect_end") or "?")
        )
    if candidate.get("ql"):
        printf(
            "  Quality: " + str(candidate.get("ql")) +
            (
                " (" + str(candidate.get("ql_reference")) + ")"
                if candidate.get("ql_reference") else ""
            )
        )
    if candidate.get("dem_gsd"):
        printf("  Source DEM GSD: " + str(candidate.get("dem_gsd")))

    for resource_name, root_url, info in resources:
        crs = _ept_crs(info)
        query_bbox = _transform_bbox_wgs84_to_crs(bbox, crs)

        printf(
            "AWS EPT resource " + resource_name +
            " CRS=" + str(crs.to_string())
        )

        keys = collect_ept_node_keys(
            root_url,
            info,
            query_bbox,
            session=session,
            printf=printf,
        )

        if not keys:
            continue

        resource_manifest = {
            "resource": resource_name,
            "ept": root_url + "/ept.json",
            "crs": crs.to_string(),
            "query_bbox": list(query_bbox),
            "files": [],
        }

        safe_resource = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(resource_name),
        )

        for index, key in enumerate(keys, 1):
            filename = safe_resource + "__" + key + ".laz"
            destination = target / filename

            try:
                count = _write_filtered_node(
                    session,
                    root_url,
                    key,
                    query_bbox,
                    crs,
                    destination,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Failed downloading AWS EPT node " +
                    resource_name + "/" + key + ": " + str(exc)
                ) from exc

            if count <= 0:
                if destination.exists():
                    destination.unlink()
                continue

            total_points += count
            total_files += 1
            resource_manifest["files"].append({
                "key": key,
                "file": filename,
                "points": count,
            })

            if (
                index == 1 or
                index % 10 == 0 or
                index == len(keys)
            ):
                printf(
                    "  " + resource_name + ": " +
                    str(index) + "/" + str(len(keys)) +
                    " EPT nodes checked; retained points=" +
                    f"{total_points:,}"
                )

        manifest["resources"].append(resource_manifest)

    if total_files <= 0 or total_points <= 0:
        raise RuntimeError(
            "AWS EPT query completed but returned no LiDAR points inside "
            "the buffered OSM extent"
        )

    manifest["output_laz_files"] = total_files
    manifest["output_points"] = total_points

    (target / "aws_ept_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    printf(
        "AWS EPT download complete: " +
        str(total_files) + " LAZ chunk(s), " +
        f"{total_points:,}" + " points"
    )
    printf("AWS EPT LAZ directory: " + str(target))
    return str(target)


def download_osm_ept_laz(
    osm_file,
    output_root,
    buffer_m=DEFAULT_OSM_BUFFER_M,
    printf=print,
):
    """Backward-compatible automatic mode: newest complete public EPT."""
    bbox, candidates = discover_osm_ept_candidates(
        osm_file,
        output_root,
        buffer_m=buffer_m,
        printf=printf,
    )
    candidate = next(
        (
            value for value in candidates
            if value.get("ept_available")
        ),
        None,
    )
    if candidate is None:
        raise RuntimeError(
            "No candidate LiDAR acquisition is available in public AWS EPT"
        )
    return download_candidate_ept_laz(
        candidate,
        bbox,
        output_root,
        osm_file=osm_file,
        buffer_m=buffer_m,
        printf=printf,
    )

