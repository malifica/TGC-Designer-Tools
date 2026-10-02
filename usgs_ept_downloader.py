import io
import json
import math
import re
import shutil
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
            printf(
                "Selected public AWS EPT project: " + project +
                " (" + str(len(resolved)) + " work unit(s))"
            )
            return project, resolved

        # Some EPT resources are published at project level rather than by
        # the work-unit directory name used by Rocky/TNM.
        project_resource = _get_ept_info(session, project)
        if project_resource is not None:
            root_url, ept_info = project_resource
            printf(
                "Selected public AWS EPT project-level resource: " + project
            )
            return project, [(project, root_url, ept_info)]

        if resolved:
            printf(
                "Skipping partially mirrored AWS EPT project " + project +
                "; missing work unit(s): " + ", ".join(missing)
            )
        else:
            printf(
                "AWS EPT mirror does not contain candidate project: " + project
            )

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


def download_osm_ept_laz(
    osm_file,
    output_root,
    buffer_m=DEFAULT_OSM_BUFFER_M,
    printf=print,
):
    """Download public USGS AWS EPT for a buffered local OSM course extent.

    The output is a directory of ordinary LAZ chunks, so the existing Beta 5
    LiDAR parser, tree detection, preview, mask and terrain code remain the
    authoritative downstream path.
    """
    bbox = read_osm_course_bounds(
        osm_file,
        buffer_m=buffer_m,
        printf=printf,
    )

    output_root = Path(output_root)
    target = output_root / "USGS_AWS_EPT_LAZ"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "TGC-Designer-Tools-Beta5/USGS-EPT"
    })

    projects = discover_tnm_projects(
        bbox,
        printf=printf,
        session=session,
    )
    project, resources = choose_public_ept_project(
        projects,
        printf=printf,
        session=session,
    )

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source": "USGS 3DEP public AWS EPT",
        "tnm_project": project,
        "osm_file": str(Path(osm_file).resolve()),
        "buffer_m": float(buffer_m),
        "wgs84_bbox": list(bbox),
        "resources": [],
    }

    total_points = 0
    total_files = 0

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

        for index, key in enumerate(keys, 1):
            filename = resource_name + "__" + key + ".laz"
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
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    printf(
        "AWS EPT download complete: " +
        str(total_files) + " LAZ chunk(s), " +
        f"{total_points:,}" + " points"
    )
    printf("AWS EPT LAZ directory: " + str(target))
    return str(target)
