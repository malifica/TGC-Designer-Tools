
import math

import cv2
import numpy as np
from scipy.spatial import cKDTree

import tgc_definitions


DEFAULT_FILTER_DISTANCE_M = 50.0
BUILDING_CLASSIFICATION = 6
MIN_BUILDING_AREA_M2 = 16.0
BUILDING_SIMPLIFY_M = 1.0
FEATURE_SAMPLE_SPACING_M = 5.0


def detect_lidar_building_footprints(
    selected_points,
    pc,
    sample_scale,
    image_shape,
    printf=print,
):
    """
    Extract simple building footprints from LAS classification 6 points.

    selected_points are the existing lidar_map_api CV2-space rows/cols:
      column 0 = raster row
      column 1 = raster column
      column 4 = LAS classification

    Returns projected-coordinate polygons:
      [{"points": [(easting,northing), ...], "area_m2": ...}, ...]
    """
    points = np.asarray(selected_points)

    if points.ndim != 2 or points.shape[1] < 5:
        return []

    class6 = points[
        points[:, 4].astype(np.int32)
        == BUILDING_CLASSIFICATION
    ]

    if len(class6) == 0:
        printf(
            "LiDAR building detection: no LAS classification-6 points found."
        )
        return []

    rows = int(image_shape[0])
    cols = int(image_shape[1])

    occupancy = np.zeros(
        (rows, cols),
        dtype=np.uint8,
    )

    rr = class6[:, 0].astype(np.int64)
    cc = class6[:, 1].astype(np.int64)

    valid = (
        (rr >= 0)
        & (rr < rows)
        & (cc >= 0)
        & (cc < cols)
    )

    rr = rr[valid]
    cc = cc[valid]

    occupancy[
        rr,
        cc,
    ] = 1

    # Roof-classified cells can have tiny gaps. Close only a one-cell gap;
    # do not aggressively expand footprints.
    kernel = np.ones(
        (3, 3),
        dtype=np.uint8,
    )

    occupancy = cv2.morphologyEx(
        occupancy,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=1,
    )

    contours, _hierarchy = cv2.findContours(
        occupancy,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )

    resolution = float(
        sample_scale
    )

    min_pixels = max(
        3.0,
        float(MIN_BUILDING_AREA_M2)
        / max(
            resolution * resolution,
            1.0e-9,
        ),
    )

    epsilon_px = max(
        0.25,
        float(BUILDING_SIMPLIFY_M)
        / max(
            resolution,
            1.0e-9,
        ),
    )

    buildings = []

    for contour in contours:
        pixel_area = float(
            cv2.contourArea(
                contour
            )
        )

        if pixel_area < min_pixels:
            continue

        approx = cv2.approxPolyDP(
            contour,
            epsilon_px,
            True,
        )

        if len(approx) < 3:
            continue

        projected = []

        for col, row in approx.reshape(-1, 2):
            easting, northing = pc.cv2ToProj(
                int(row),
                int(col),
                resolution,
            )

            projected.append(
                (
                    float(easting),
                    float(northing),
                )
            )

        buildings.append({
            "points": projected,
            "area_m2": float(
                pixel_area
                * resolution
                * resolution
            ),
        })

    buildings.sort(
        key=lambda item: item[
            "area_m2"
        ],
        reverse=True,
    )

    printf(
        "LiDAR building detection: "
        + str(len(buildings))
        + " classification-6 footprint(s) retained from "
        + str(len(class6))
        + " classified points."
    )

    return buildings


def _densify_polyline(
    points,
    spacing_m=FEATURE_SAMPLE_SPACING_M,
    closed=False,
):
    if not points:
        return []

    output = []

    n = len(
        points
    )

    segment_count = (
        n
        if closed and n >= 3
        else max(
            0,
            n - 1,
        )
    )

    for i in range(
        segment_count
    ):
        a = points[
            i
        ]

        b = points[
            (i + 1) % n
        ]

        ax = float(
            a[0]
        )

        az = float(
            a[1]
        )

        bx = float(
            b[0]
        )

        bz = float(
            b[1]
        )

        distance = math.hypot(
            bx - ax,
            bz - az,
        )

        count = max(
            1,
            int(
                math.ceil(
                    distance
                    / max(
                        float(
                            spacing_m
                        ),
                        0.5,
                    )
                )
            ),
        )

        for j in range(
            count
        ):
            t = float(
                j
            ) / float(
                count
            )

            output.append(
                (
                    ax
                    + (bx - ax)
                    * t,
                    az
                    + (bz - az)
                    * t,
                )
            )

    if not closed:
        output.append(
            (
                float(points[-1][0]),
                float(points[-1][1]),
            )
        )

    return output


def build_course_feature_index(
    course_json,
    course_version,
    printf=print,
):
    """
    Build the 50 m LiDAR-object proximity index from CORE GOLF GEOMETRY only.

    V2 accidentally indexed every spline, including:
      - OSM/LiDAR building placeholders;
      - walking paths;
      - cart paths;
      - other Surface1 / Surface3 utility splines.

    That made remote trees/buildings self-validate against nearby non-golf
    splines and defeated the 50 m limit.

    V2B accepts only primary playing/course-envelope surfaces:
      0 = bunker
      1 = green / tee
      2 = fairway
      3 = rough

    Hole centreline routes are also included.

    Deliberately EXCLUDED:
      7  = Surface1 placeholders / many walking paths / buildings
      10 = Surface3 / cart-path style utility geometry
    """
    if (
        course_version
        not in tgc_definitions.version_tags
    ):
        return None

    spline_tag = tgc_definitions.version_tags[
        course_version
    ][
        "splines"
    ]

    hole_tag = tgc_definitions.version_tags[
        course_version
    ][
        "holes"
    ]

    dim2 = (
        "z"
        if course_version == 25
        else "y"
    )

    CORE_SURFACES = {
        0,  # bunker
        1,  # green / tee
        2,  # fairway
        3,  # rough
    }

    samples = []
    included_splines = 0
    excluded_splines = 0

    for spline in course_json.get(
        spline_tag,
        [],
    ) or []:
        try:
            surface = int(
                spline.get(
                    "surface",
                    -999,
                )
            )
        except Exception:
            surface = -999

        if surface not in CORE_SURFACES:
            excluded_splines += 1
            continue

        points = []

        for item in spline.get(
            "waypoints",
            [],
        ) or []:
            wp = item.get(
                "waypoint",
                {},
            )

            try:
                points.append(
                    (
                        float(
                            wp["x"]
                        ),
                        float(
                            wp[
                                dim2
                            ]
                        ),
                    )
                )
            except Exception:
                pass

        if len(
            points
        ) >= 2:
            included_splines += 1

            samples.extend(
                _densify_polyline(
                    points,
                    spacing_m=FEATURE_SAMPLE_SPACING_M,
                    closed=bool(
                        spline.get(
                            "isClosed",
                            spline.get(
                                "ClosedPath",
                                False,
                            ),
                        )
                    ),
                )
            )

    included_holes = 0

    for hole in course_json.get(
        hole_tag,
        [],
    ) or []:
        points = []

        for wp in hole.get(
            "waypoints",
            [],
        ) or []:
            try:
                points.append(
                    (
                        float(
                            wp[
                                "x"
                            ]
                        ),
                        float(
                            wp[
                                "z"
                            ]
                        ),
                    )
                )
            except Exception:
                pass

        if len(
            points
        ) >= 2:
            included_holes += 1

            samples.extend(
                _densify_polyline(
                    points,
                    spacing_m=FEATURE_SAMPLE_SPACING_M,
                    closed=False,
                )
            )

    if not samples:
        printf(
            "LiDAR strict 50 m filter: no bunker/green/tee/fairway/rough "
            "or hole-route geometry was available."
        )

        return None

    array = np.asarray(
        samples,
        dtype=np.float64,
    )

    printf(
        "LiDAR strict 50 m course index: "
        + str(included_splines)
        + " core golf spline(s) + "
        + str(included_holes)
        + " hole route(s); "
        + str(excluded_splines)
        + " path/building/utility spline(s) excluded; "
        + str(len(array))
        + " sampled course points."
    )

    return cKDTree(
        array
    )


def candidate_within_distance(
    x,
    z,
    feature_tree,
    max_distance_m=DEFAULT_FILTER_DISTANCE_M,
):
    if feature_tree is None:
        return False

    distance, _index = feature_tree.query(
        [
            float(x),
            float(z),
        ],
        k=1,
    )

    return bool(
        float(distance)
        <= float(
            max_distance_m
        )
    )



# -------------------------------------------------------------------------
# LiDAR TREE PLAYING-SURFACE EXCLUSION
#
# LiDAR tree detection is intentionally kept separate from this geometry
# filter.  The detector may infer trees from unclassified above-ground
# returns, but a candidate should never survive on a maintained playing
# surface simply because it is near the golf course.
#
# Precedence:
#   1. Green/tee or bunker -> reject.
#   2. Explicit rough spline -> allow (rough can intentionally sit inside a
#      fairway around a real tree).
#   3. Fairway -> reject.
#   4. Everything else -> allow.
#
# OSM-mapped trees are added through a different path and are unaffected.
# -------------------------------------------------------------------------


def _dense_closed_spline_boundary(spline, course_version, samples_per_segment=12):
    """Return a dense X/Z polygon following the spline's Bezier boundary."""
    dim2 = "z" if course_version == 25 else "y"
    waypoints = list(spline.get("waypoints", []) or [])

    if len(waypoints) < 3:
        return None

    points = []
    count = len(waypoints)

    for i in range(count):
        a = waypoints[i]
        b = waypoints[(i + 1) % count]

        try:
            p0 = np.asarray(
                [
                    float(a["waypoint"]["x"]),
                    float(a["waypoint"][dim2]),
                ],
                dtype=np.float64,
            )
            p1 = np.asarray(
                [
                    float(a["pointTwo"]["x"]),
                    float(a["pointTwo"][dim2]),
                ],
                dtype=np.float64,
            )
            p2 = np.asarray(
                [
                    float(b["pointOne"]["x"]),
                    float(b["pointOne"][dim2]),
                ],
                dtype=np.float64,
            )
            p3 = np.asarray(
                [
                    float(b["waypoint"]["x"]),
                    float(b["waypoint"][dim2]),
                ],
                dtype=np.float64,
            )
        except Exception:
            return None

        for j in range(samples_per_segment):
            t = float(j) / float(samples_per_segment)
            u = 1.0 - t
            p = (
                (u ** 3) * p0
                + 3.0 * (u ** 2) * t * p1
                + 3.0 * u * (t ** 2) * p2
                + (t ** 3) * p3
            )
            points.append((float(p[0]), float(p[1])))

    if len(points) < 3:
        return None

    return np.asarray(points, dtype=np.float32).reshape((-1, 1, 2))


def _surface_region_entry(spline, course_version):
    """Build one fast point-in-spline region entry, including spline width."""
    contour = _dense_closed_spline_boundary(
        spline,
        course_version,
    )
    if contour is None:
        return None

    try:
        width = max(0.0, float(spline.get("width", 0.0)))
    except Exception:
        width = 0.0

    # OSM area splines are shrunk inward by half their width before being
    # written.  Expand the hit test by the same half-width so the exclusion
    # follows the rendered primary surface rather than only the spline center.
    edge_margin = 0.5 * width

    pts = contour.reshape((-1, 2))
    xmin = float(np.min(pts[:, 0])) - edge_margin
    xmax = float(np.max(pts[:, 0])) + edge_margin
    zmin = float(np.min(pts[:, 1])) - edge_margin
    zmax = float(np.max(pts[:, 1])) + edge_margin

    return {
        "contour": contour,
        "edge_margin": edge_margin,
        "bbox": (xmin, zmin, xmax, zmax),
    }


def build_lidar_tree_surface_filter(
    course_json,
    course_version,
    printf=print,
):
    """Build primary playing-surface regions used to reject false LiDAR trees."""
    if course_version not in tgc_definitions.version_tags:
        return None

    spline_tag = tgc_definitions.version_tags[course_version]["splines"]

    regions = {
        "bunker": [],
        "green_tee": [],
        "fairway": [],
        "rough": [],
    }

    for spline in course_json.get(spline_tag, []) or []:
        if not bool(
            spline.get(
                "isFilled",
                spline.get("ClosedPath", False),
            )
        ):
            continue

        try:
            surface = int(spline.get("surface", -999))
        except Exception:
            continue

        if surface == 0:
            key = "bunker"
        elif surface == 1:
            key = "green_tee"
        elif surface == 2:
            key = "fairway"
        elif surface == 3:
            key = "rough"
        else:
            continue

        entry = _surface_region_entry(
            spline,
            course_version,
        )
        if entry is not None:
            regions[key].append(entry)

    printf(
        "LiDAR tree playing-surface filter: "
        + str(len(regions["green_tee"]))
        + " green/tee, "
        + str(len(regions["bunker"]))
        + " bunker, "
        + str(len(regions["fairway"]))
        + " fairway, "
        + str(len(regions["rough"]))
        + " rough region(s)."
    )

    return regions


def _point_hits_surface_regions(x, z, regions):
    for region in regions:
        xmin, zmin, xmax, zmax = region["bbox"]
        if x < xmin or x > xmax or z < zmin or z > zmax:
            continue

        signed_distance = cv2.pointPolygonTest(
            region["contour"],
            (float(x), float(z)),
            True,
        )

        if signed_distance >= -float(region["edge_margin"]):
            return True

    return False


def filter_lidar_tree_candidates_by_playing_surfaces(
    lidar_trees,
    pc,
    surface_filter,
    printf=print,
):
    """Reject LiDAR-generated trees from maintained playing surfaces.

    Green/tee and bunker are absolute exclusions.  An explicit rough spline
    overrides fairway so deliberately mapped rough islands can retain real
    trees.
    """
    if not surface_filter:
        printf(
            "LiDAR tree playing-surface filter: no course-surface geometry "
            "available; candidates unchanged."
        )
        return list(lidar_trees)

    kept = []
    rejected_green_tee = 0
    rejected_bunker = 0
    rejected_fairway = 0
    rough_overrides = 0

    for tree in lidar_trees:
        try:
            easting, northing, radius, height = tree
            x, _y, z = pc.projToTGC(
                float(easting),
                float(northing),
                0.0,
            )
        except Exception:
            continue

        # Green/tee and bunker are always hard exclusions.
        if _point_hits_surface_regions(
            x,
            z,
            surface_filter["green_tee"],
        ):
            rejected_green_tee += 1
            continue

        if _point_hits_surface_regions(
            x,
            z,
            surface_filter["bunker"],
        ):
            rejected_bunker += 1
            continue

        # Deliberately mapped rough islands override an underlying fairway.
        if _point_hits_surface_regions(
            x,
            z,
            surface_filter["rough"],
        ):
            rough_overrides += 1
            kept.append(tree)
            continue

        if _point_hits_surface_regions(
            x,
            z,
            surface_filter["fairway"],
        ):
            rejected_fairway += 1
            continue

        kept.append(tree)

    rejected = (
        rejected_green_tee
        + rejected_bunker
        + rejected_fairway
    )

    printf(
        "LiDAR tree playing-surface filter: kept "
        + str(len(kept))
        + "/"
        + str(len(lidar_trees))
        + "; rejected "
        + str(rejected_green_tee)
        + " green/tee, "
        + str(rejected_bunker)
        + " bunker, "
        + str(rejected_fairway)
        + " fairway candidate(s); rough overrides="
        + str(rough_overrides)
        + "."
    )

    return kept


def filter_lidar_tree_candidates(
    lidar_trees,
    pc,
    feature_tree,
    max_distance_m=DEFAULT_FILTER_DISTANCE_M,
    printf=print,
):
    if feature_tree is None:
        printf(
            "LiDAR tree 50 m filter requested, but no course-feature index "
            "exists; no LiDAR trees will be added."
        )
        return []

    kept = []

    for tree in lidar_trees:
        try:
            easting, northing, radius, height = tree

            x, _y, z = pc.projToTGC(
                float(
                    easting
                ),
                float(
                    northing
                ),
                0.0,
            )

            if candidate_within_distance(
                x,
                z,
                feature_tree,
                max_distance_m,
            ):
                kept.append(
                    tree
                )

        except Exception:
            pass

    printf(
        "LiDAR tree course-proximity filter: "
        + str(len(kept))
        + "/"
        + str(len(lidar_trees))
        + " candidate(s) within "
        + str(
            float(
                max_distance_m
            )
        )
        + " m of a course feature."
    )

    return kept


def lidar_building_splines(
    building_candidates,
    pc,
    feature_tree,
    max_distance_m,
    apply_filter,
    new_building_func,
    course_version,
    printf=print,
):
    output = []
    considered = 0
    filtered_out = 0

    for building in building_candidates:
        projected_points = building.get(
            "points",
            [],
        )

        if len(
            projected_points
        ) < 3:
            continue

        tgc_points = []

        for easting, northing in projected_points:
            try:
                tgc_points.append(
                    pc.projToTGC(
                        float(
                            easting
                        ),
                        float(
                            northing
                        ),
                        0.0,
                    )
                )
            except Exception:
                pass

        if len(
            tgc_points
        ) < 3:
            continue

        considered += 1

        cx = float(
            np.mean(
                [
                    p[0]
                    for p in tgc_points
                ]
            )
        )

        cz = float(
            np.mean(
                [
                    p[2]
                    for p in tgc_points
                ]
            )
        )

        if apply_filter:
            if not candidate_within_distance(
                cx,
                cz,
                feature_tree,
                max_distance_m,
            ):
                filtered_out += 1
                continue

        try:
            spline = new_building_func(
                tgc_points,
                course_version,
            )

            if spline is not None:
                output.append(
                    spline
                )
        except Exception:
            pass

    if apply_filter:
        printf(
            "LiDAR building course-proximity filter: "
            + str(len(output))
            + "/"
            + str(considered)
            + " footprint(s) within "
            + str(
                float(
                    max_distance_m
                )
            )
            + " m of a course feature."
        )
    else:
        printf(
            "LiDAR building import: "
            + str(len(output))
            + " footprint spline(s) added without proximity filtering."
        )

    return output
