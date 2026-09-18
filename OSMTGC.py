import cv2
import xml.etree.ElementTree as ET
from GeoPointCloud import GeoPointCloud
import json
import math
import numpy as np
import overpy
import time

import tgc_definitions

status_print_duration = 1.0 # Print progress every N seconds

spline_configuration = None

# Returns left, top, right, bottom
def nodeBoundingBox(nds):
    X = [nd[0] for nd in nds]
    #Y = [nd[1] for nd in nds]
    Z = [nd[2] for nd in nds]
    return (min(X), max(Z), max(X), min(Z))

def shapeCenter(nds):
    bb = nodeBoundingBox(nds)
    return ((bb[0] + bb[2])/2.0, (bb[1]+bb[3])/2.0)

def getwaypoint(easting, vertical, northing, course_version):
    dim2 = "y"
    if course_version == 25:
        dim2 = "z"

    output = json.loads('{"pointOne": {"x": 0.0,"'+dim2+'": 0.0},"pointTwo": {"x": 0.0,"'+dim2+'": 0.0},"waypoint": {"x": 0.0,"'+dim2+'": 0.0} }')
    output["waypoint"]["x"] = easting
    output["waypoint"][dim2] = northing
    return output

def getwaypoint3D(x, y, z):
    wp = json.loads('{"x": 0.0,"y": 0.0,"z": 0.0}')
    wp["x"] = x
    wp["y"] = y
    wp["z"] = z
    return wp

def getTangentAngle(previous_point, next_point, course_version):
    dim2 = "y"
    if course_version == 25:
        dim2 = "z"

    return math.atan2(float(next_point[dim2])-float(previous_point[dim2]), float(next_point["x"])-float(previous_point["x"]))

def completeSpline(points, spline_json, handleLength=1.0, is_clockwise=True, tightSplines=True, course_version=-1):
    dim2 = "y"
    if course_version == 25:
        dim2 = "z"
            
    number_points = len(spline_json["waypoints"])
    for i in range(0, number_points):
        prev_index = i - 1 # Works for negative
        next_index = i + 1
        if next_index == number_points:
            next_index = 0

        p = spline_json["waypoints"][prev_index]["waypoint"]
        t = spline_json["waypoints"][i]["waypoint"]
        n = spline_json["waypoints"][next_index]["waypoint"]

        # Just guessing what these points are and if they are important
        # Set point one and point two to be on the line between the previous and next point, but centered on this point
        angle = getTangentAngle(p, n, course_version)
        if tightSplines:
            # Pull the spline handles perpendicular and inside the shape in order to accurately
            # represent the shapes downloaded online.  Don't want a lot of expansion or smoothing
            angle_one = angle - 1.1 * math.pi / 2.0
            angle_two = angle - 0.9 * math.pi / 2.0

            # Clockwise splines appear to point inward by default, this is what we want
            if not is_clockwise:
                # Flip handles inwards
                angle_temp = angle_one
                angle_one = angle_two + math.pi
                angle_two = angle_temp + math.pi
        else:
            # Loose, smooth splines
            angle_one = angle + math.pi
            angle_two = angle

        # TODO Use angle to center to guarantee these point inwards?  I see them pointing out sometimes
        spline_json["waypoints"][i]["pointOne"]["x"] = t["x"] + handleLength * math.cos(angle_one)
        spline_json["waypoints"][i]["pointOne"][dim2] = t[dim2] + handleLength * math.sin(angle_one)
        spline_json["waypoints"][i]["pointTwo"]["x"] = t["x"] + handleLength * math.cos(angle_two)
        spline_json["waypoints"][i]["pointTwo"][dim2] = t[dim2] + handleLength * math.sin(angle_two)

def splineIsClockWise(spline_json, course_version=-1):
    dim2 = "y"
    if course_version == 25:
        dim2 = "z"

    # https://stackoverflow.com/questions/1165647/how-to-determine-if-a-list-of-polygon-points-are-in-clockwise-order
    points = spline_json["waypoints"]
    edge_sum = 0.0
    for i in range(0, len(points)):
        edge_sum += (points[i]["waypoint"]["x"]-points[i-1]["waypoint"]["x"])*(points[i]["waypoint"][dim2]+points[i-1]["waypoint"][dim2])

    return edge_sum >= 0.0

def shrinkSplineNormals(spline_json, shrink_distance=1.0, is_clockwise=True, course_version=-1):
    if not shrink_distance:
        return spline_json

    dim2 = "y"
    if course_version == 25:
        dim2 = "z"

    number_points = len(spline_json["waypoints"])
    for i in range(0, number_points):
        prev_index = i - 1 # Works for negative
        next_index = i + 1
        if next_index == number_points:
            next_index = 0

        p = spline_json["waypoints"][prev_index]["waypoint"]
        t = spline_json["waypoints"][i]["waypoint"]
        n = spline_json["waypoints"][next_index]["waypoint"]
        tangent_angle = getTangentAngle(p, n, course_version)
        # Move the spline points along the normal to the inside of the shape
        # Since the game expands splines by a fixed amount, we need to shrink the shape by a set amount
        normal_angle = tangent_angle - math.pi/2.0
        # Clockwise splines appear to point inward by default, this is what we want
        if not is_clockwise:
            # Flip normal inwards
            normal_angle = normal_angle + math.pi

        # Now shift the spline point by shrink_distance in the direction of normal_angle
        t["x"] += math.cos(normal_angle)*shrink_distance
        t[dim2] += math.sin(normal_angle)*shrink_distance

    return spline_json

def newSpline(points, pathWidth=0.01, shrink_distance=None, handleLength=0.5, tightSplines=True, 
    secondarySurface="", secondaryWidth=0.0, spline_json=None, course_version=-1):
    
    spline = json.loads('{"surface": 1, \
            "secondarySurface": 11, \
            "secondaryWidth": -1.0, \
            "waypoints": [], \
            "width": 0.01, \
            "state": 3, \
            "ClosedPath": false, \
            "isClosed": true, \
            "isFilled": true \
        }')

    try:
        if spline_json is not None:
            pathWidth = spline_json.get("pathWidth", pathWidth)
            handleLength = spline_json.get("handleLength", handleLength)
            tightSplines = spline_json.get("tightSplines", tightSplines)
            secondarySurface = spline_json.get("secondarySurface", secondarySurface)
            secondaryWidth = spline_json.get("secondaryWidth", secondaryWidth)
    except:
        print("Invalid Spline configuration: " + str(spline_json))

    dim2 = "y"
    if course_version == 25:
        dim2 = "z"

    spline["width"] = pathWidth
    spline["secondarySurface"] = tgc_definitions.featuresToSurfaces.get(secondarySurface, 11) 
    spline["secondaryWidth"] = secondaryWidth

    for p in points:
        spline["waypoints"].append(getwaypoint(*p, course_version))

    # Determine direction of spline
    is_clockwise = splineIsClockWise(spline, course_version)

    # Reduce spline normal distance (move points inwards) by half of width
    # This compensates for the game treating all splines like filled cartpaths
    if shrink_distance is None:
        shrink_distance = pathWidth/2.0
    spline = shrinkSplineNormals(spline, shrink_distance=shrink_distance, is_clockwise=is_clockwise, course_version=course_version)

    # Now that spline is shrunk, set the handles according to the properties we want
    completeSpline(points, spline, handleLength=handleLength, is_clockwise=is_clockwise, tightSplines=tightSplines, course_version=course_version)

    return spline

def newBunker(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("bunker", None)
    # Very tight shaped to make complex curves
    bunker = newSpline(points, pathWidth=0.01, handleLength=1.0, tightSplines=True, secondarySurface="heavyrough", secondaryWidth=2.5, spline_json=spline_json, course_version=course_version)
    bunker["surface"] = tgc_definitions.featuresToSurfaces["bunker"]
    return bunker

def newGreen(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("green", None)
    green = newSpline(points, pathWidth = 1.7, handleLength=0.2, tightSplines=True, secondarySurface="heavyrough", secondaryWidth=2.5, spline_json=spline_json, course_version=course_version)
    green["surface"] = tgc_definitions.featuresToSurfaces["green"]
    return green

def newTeeBox(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("teebox", None)
    teebox = newSpline(points, pathWidth = 1.7, handleLength=0.2, tightSplines=True, secondarySurface="heavyrough", secondaryWidth=2.5, spline_json=spline_json, course_version=course_version)
    teebox["surface"] = tgc_definitions.featuresToSurfaces["green"]
    return teebox

def newFairway(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("fairway", None)
    fw = newSpline(points, pathWidth = 3.0, handleLength=3.0, tightSplines=False, secondarySurface="rough", secondaryWidth=5.0, spline_json=spline_json, course_version=course_version)
    fw["surface"] = tgc_definitions.featuresToSurfaces["fairway"]
    return fw

def newRough(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("rough", None)
    rh = newSpline(points, pathWidth = 1.7, handleLength=3.0, tightSplines=False, secondarySurface="", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version)
    # Game outputs secondary as 1
    # Remove with 0 width
    rh["surface"] = tgc_definitions.featuresToSurfaces["rough"]
    return rh


# -------------------------------------------------------------------------
# 2K25 BUNKER INNER-ROUGH / "LOLLIPOP" SUPPORT
#
# OSM multipolygon:
#   relation golf=bunker, type=multipolygon
#     outer -> bunker boundary
#     inner -> golf=rough island
#
# PGA TOUR 2K25 will not render rough over a filled bunker. Convert the
# bunker polygon into a narrow-neck/lollipop polygon so the rough island is
# a physical hole in the bunker.
# -------------------------------------------------------------------------

def _strip_closed_ring(points):
    points = list(points)
    if len(points) > 1:
        a = points[0]
        b = points[-1]
        try:
            if math.hypot(float(a[0]) - float(b[0]), float(a[2]) - float(b[2])) < 0.0001:
                points = points[:-1]
        except Exception:
            pass
    return points


def _ring_signed_area_xz(points):
    points = _strip_closed_ring(points)
    if len(points) < 3:
        return 0.0

    area2 = 0.0
    for i in range(len(points)):
        p = points[i]
        q = points[(i + 1) % len(points)]
        area2 += float(p[0]) * float(q[2]) - float(q[0]) * float(p[2])
    return 0.5 * area2


def _point_in_ring_xz(point, ring):
    ring = _strip_closed_ring(ring)
    if len(ring) < 3:
        return False

    x = float(point[0])
    z = float(point[2])
    inside = False
    j = len(ring) - 1

    for i in range(len(ring)):
        xi = float(ring[i][0])
        zi = float(ring[i][2])
        xj = float(ring[j][0])
        zj = float(ring[j][2])

        crosses = ((zi > z) != (zj > z))
        if crosses:
            denom = zj - zi
            if abs(denom) < 1.0e-12:
                denom = 1.0e-12
            x_intersect = (xj - xi) * (z - zi) / denom + xi
            if x < x_intersect:
                inside = not inside
        j = i

    return inside


def _ring_centroid_average(points):
    points = _strip_closed_ring(points)
    if not points:
        return (0.0, 0.0, 0.0)

    return (
        sum(float(p[0]) for p in points) / len(points),
        sum(float(p[1]) for p in points) / len(points),
        sum(float(p[2]) for p in points) / len(points),
    )


def _nearest_ring_vertex_pair(outer, inner):
    best_distance2 = None
    best_outer_index = 0
    best_inner_index = 0

    for oi, op in enumerate(outer):
        ox = float(op[0])
        oz = float(op[2])
        for ii, ip in enumerate(inner):
            dx = float(ip[0]) - ox
            dz = float(ip[2]) - oz
            d2 = dx * dx + dz * dz

            if best_distance2 is None or d2 < best_distance2:
                best_distance2 = d2
                best_outer_index = oi
                best_inner_index = ii

    return best_outer_index, best_inner_index, math.sqrt(max(0.0, best_distance2 or 0.0))


def _offset_point_xz(point, px, pz, amount):
    return (
        float(point[0]) + float(px) * float(amount),
        float(point[1]),
        float(point[2]) + float(pz) * float(amount),
    )


def _make_bunker_hole_excursion(outer, inner, bridge_width=0.18):
    outer = _strip_closed_ring(outer)
    inner = _strip_closed_ring(inner)

    if len(outer) < 3 or len(inner) < 3:
        return None

    # Hole must run opposite the bunker outer winding.
    if _ring_signed_area_xz(outer) * _ring_signed_area_xz(inner) > 0.0:
        inner = list(reversed(inner))

    oi, ii, bridge_length = _nearest_ring_vertex_pair(outer, inner)

    op = outer[oi]
    ip = inner[ii]

    dx = float(ip[0]) - float(op[0])
    dz = float(ip[2]) - float(op[2])
    length = math.hypot(dx, dz)

    if length < 0.001:
        prevp = outer[oi - 1]
        nextp = outer[(oi + 1) % len(outer)]
        dx = float(nextp[0]) - float(prevp[0])
        dz = float(nextp[2]) - float(prevp[2])
        length = max(math.hypot(dx, dz), 0.001)

    # Narrow bridge sides perpendicular to the outer->inner direction.
    px = -dz / length
    pz = dx / length
    half = max(0.02, float(bridge_width) * 0.5)

    outer_a = _offset_point_xz(op, px, pz, half)
    outer_b = _offset_point_xz(op, px, pz, -half)
    inner_a = _offset_point_xz(ip, px, pz, half)
    inner_b = _offset_point_xz(ip, px, pz, -half)

    inner_walk = []
    j = (ii + 1) % len(inner)
    while j != ii:
        inner_walk.append(inner[j])
        j = (j + 1) % len(inner)

    path = [outer_a, inner_a] + inner_walk + [inner_b, outer_b]

    return {
        "outer_index": oi,
        "path": path,
        "local_bridge_indices": [0, 1, len(path) - 2, len(path) - 1],
        "bridge_length": bridge_length,
    }


def _build_lollipop_bunker_ring(outer, inner_rings, bridge_width=0.18):
    outer = _strip_closed_ring(outer)
    if len(outer) < 3:
        return outer, []

    excursions_by_outer_index = {}

    for inner in inner_rings:
        excursion = _make_bunker_hole_excursion(
            outer,
            inner,
            bridge_width=bridge_width
        )
        if excursion is None:
            continue
        excursions_by_outer_index.setdefault(
            excursion["outer_index"], []
        ).append(excursion)

    merged = []
    bridge_indices = []

    for oi, point in enumerate(outer):
        excursions = excursions_by_outer_index.get(oi, [])

        if not excursions:
            merged.append(point)
            continue

        for excursion in excursions:
            base_index = len(merged)
            merged.extend(excursion["path"])
            bridge_indices.extend(
                base_index + i
                for i in excursion["local_bridge_indices"]
            )

    return merged, bridge_indices


def _clamp_spline_handles(spline, waypoint_indices, course_version):
    dim2 = "z" if course_version == 25 else "y"
    waypoints = spline.get("waypoints", [])

    for index in waypoint_indices:
        if index < 0 or index >= len(waypoints):
            continue

        wp = waypoints[index]
        x = wp["waypoint"]["x"]
        d2 = wp["waypoint"][dim2]

        wp["pointOne"]["x"] = x
        wp["pointOne"][dim2] = d2
        wp["pointTwo"]["x"] = x
        wp["pointTwo"][dim2] = d2


def _way_to_tgc_points(way, geopointcloud, x_offset, y_offset, resolve_missing_nodes):
    points = []
    for node in way.get_nodes(resolve_missing=resolve_missing_nodes):
        points.append(
            geopointcloud.latlonToTGC(
                node.lat,
                node.lon,
                x_offset,
                y_offset
            )
        )
    return _strip_closed_ring(points)


def _relation_is_bunker_with_rough_inner(rel, way_lookup):
    outer_members = []
    rough_inner_members = []

    for member in rel.members:
        if not isinstance(member, overpy.RelationWay):
            continue

        way = way_lookup.get(member.ref)
        if way is None:
            continue

        role = str(member.role or "").lower()
        golf_type = way.tags.get("golf", None)

        if role == "outer":
            outer_members.append(member)
        elif role == "inner" and golf_type == "rough":
            rough_inner_members.append(member)

    relation_is_bunker = rel.tags.get("golf", None) == "bunker"

    if not relation_is_bunker:
        for member in outer_members:
            way = way_lookup.get(member.ref)
            if way is not None and way.tags.get("golf", None) == "bunker":
                relation_is_bunker = True
                break

    return relation_is_bunker and outer_members and rough_inner_members


def _build_bunker_rough_multipolygon_splines(
    rel,
    way_lookup,
    geopointcloud,
    x_offset,
    y_offset,
    resolve_missing_nodes,
    course_version,
    printf=print,
):
    outer_rings = []
    rough_inner_rings = []

    for member in rel.members:
        if not isinstance(member, overpy.RelationWay):
            continue

        way = way_lookup.get(member.ref)
        if way is None:
            continue

        role = str(member.role or "").lower()

        if role == "outer":
            points = _way_to_tgc_points(
                way, geopointcloud, x_offset, y_offset, resolve_missing_nodes
            )
            if len(points) >= 3:
                outer_rings.append((member.ref, points))

        elif role == "inner" and way.tags.get("golf", None) == "rough":
            points = _way_to_tgc_points(
                way, geopointcloud, x_offset, y_offset, resolve_missing_nodes
            )
            if len(points) >= 3:
                rough_inner_rings.append((member.ref, points))

    if not outer_rings or not rough_inner_rings:
        return [], [], set()

    # Assign rough islands to containing outer bunker ring.
    assigned = {outer_id: [] for outer_id, _ in outer_rings}

    for inner_id, inner_ring in rough_inner_rings:
        center = _ring_centroid_average(inner_ring)
        containing_outer = None

        for outer_id, outer_ring in outer_rings:
            if _point_in_ring_xz(center, outer_ring):
                containing_outer = outer_id
                break

        if containing_outer is None:
            best = None
            for outer_id, outer_ring in outer_rings:
                _, _, distance = _nearest_ring_vertex_pair(outer_ring, inner_ring)
                if best is None or distance < best[0]:
                    best = (distance, outer_id)
            if best is not None:
                containing_outer = best[1]

        if containing_outer is not None:
            assigned[containing_outer].append((inner_id, inner_ring))

    bunker_splines = []
    rough_splines = []
    consumed_way_ids = set()

    for outer_id, outer_ring in outer_rings:
        inner_entries = assigned.get(outer_id, [])
        inner_rings = [ring for _, ring in inner_entries]

        if inner_rings:
            merged_ring, bridge_indices = _build_lollipop_bunker_ring(
                outer_ring,
                inner_rings,
                bridge_width=0.18,
            )

            bunker = newBunker(merged_ring, course_version)

            # Normal bunker handles are ~1 m and would balloon a 0.18 m neck.
            # Clamp the four neck points to zero handles.
            _clamp_spline_handles(bunker, bridge_indices, course_version)
            bunker_splines.append(bunker)

            # Do NOT create a separate rough spline for the inner island.
            # The lollipop excursion physically removes the bunker fill there,
            # so the underlying course surface is exposed naturally in 2K25.
            # We still consume the OSM inner rough way so the normal way pass
            # cannot create a duplicate/leftover rough spline.
            for inner_id, inner_ring in inner_entries:
                consumed_way_ids.add(inner_id)

            printf(
                "2K25 bunker-hole conversion: relation " +
                str(rel.id) + ", outer way " + str(outer_id) +
                ", rough inner islands=" + str(len(inner_entries)) +
                ", bunker waypoints=" + str(len(merged_ring))
            )
        else:
            bunker_splines.append(newBunker(outer_ring, course_version))

        consumed_way_ids.add(outer_id)

    return bunker_splines, rough_splines, consumed_way_ids


def newHeavyRough(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("heavyrough", None)
    hr = newSpline(points, pathWidth = 1.7, handleLength=3.0, tightSplines=False, secondarySurface="", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version)
    # Game outputs secondary as 1
    # Remove with 0 width
    hr["surface"] = tgc_definitions.featuresToSurfaces["heavyrough"]
    return hr

def newCartPath(points, area=False, course_version=-1):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("cartpath", None)
    pathWidth = 2.0
    shrink_distance = 0.0
    if area:
        shrink_distance = None # Automatic shrink_distance
    cp = newSpline(points, pathWidth=pathWidth, shrink_distance=shrink_distance, handleLength=4.0, tightSplines=False, secondarySurface="", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version) # Smooth a lot
    # Cartpath is surface 10 (this is the one with Cartpath logo in Designer)
    # Remove secondary with 0 width
    cp["surface"] = tgc_definitions.featuresToSurfaces["cartpath"] # Cartpath, Surface #3
    if course_version == 25:
        cp["surface"] = tgc_definitions.featuresToSurfaces["surface1"] 
        
    # 0 is 'not closed' and 3 is 'closed and filled' maybe a bitmask?
    if area:
        cp["state"] = 3
        cp["isClosed"] = True
        cp["isFilled"] = True
    else:
        cp["state"] = 0 # Todo figure out what this means
        cp["isClosed"] = False
        cp["isFilled"] = False

    return cp

def newWalkingPath(points, area=False, course_version=-1):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("walkingpath", None)
    # Minimum width that will render in meters
    pathWidth = 1.7
    shrink_distance = 0.0
    if area:
        shrink_distance = None # Automatic shrink_distance
    wp = newSpline(points, pathWidth=pathWidth, shrink_distance=shrink_distance, handleLength=2.0, tightSplines=False, secondarySurface="rough", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version)
    # Make walking paths Surface #1 for visibility
    # User can switch to green/fairway/rough depending on taste
    # Remove secondary with 0 width
    wp["surface"] = tgc_definitions.featuresToSurfaces["surface1"]
    if area:
        wp["state"] = 3
        wp["isClosed"] = True
        wp["isFilled"] = True
    else:
        wp["state"] = 0 # Todo figure out what this means
        wp["isClosed"] = False
        wp["isFilled"] = False
    return wp

def newWaterHazard(points, area=True, course_version=-1):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("placeholder", None)
    # Add placeholder for water hazard.
    # Add spline and fill with black mulch
    if area:
        # No width, only very detailed fill shape
        wh = newSpline(points, pathWidth = 0.01, handleLength=0.2, tightSplines=True, secondarySurface="", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version)
    else:
        # Make smooth creek or waterway
        wh = newSpline(points, pathWidth=2.0, shrink_distance=0.0, tightSplines=False, secondarySurface="", secondaryWidth=0.0, spline_json=None, course_version=course_version)
    # Fill as mulch/surface #2 as a placeholder
    wh["surface"] = tgc_definitions.featuresToSurfaces["surface2"]
    if course_version == 25:
        wh["surface"] = tgc_definitions.featuresToSurfaces["surface3"]
        
    if area:
        wh["state"] = 3
        wh["isClosed"] = True
        wh["isFilled"] = True
    else:
        wh["state"] = 0 # Todo figure out what this means
        wh["isClosed"] = False
        wh["isFilled"] = False
    return wh

def newBuilding(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("placeholder", None)
    # Add placeholder for buildings
    # Add spline and fill with gravel
    # No width, only very detailed fill shape
    b = newSpline(points, pathWidth = 0.01, handleLength=0.2, tightSplines=True, secondarySurface="", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version)
    # Fill as a placeholder
    b["surface"] = tgc_definitions.featuresToSurfaces["surface1"]
    return b

def newForest(points, course_version):
    global spline_configuration
    spline_json = None
    if spline_configuration is not None:
        spline_json = spline_configuration.get("placeholder", None)
    # Add placeholder spline for naturaL:wood in OSM
    # Add spline and fill with gravel
    # No width, only very detailed fill shape
    f = newSpline(points, pathWidth = 0.01, handleLength=0.2, tightSplines=True, secondarySurface="", secondaryWidth=0.0, spline_json=spline_json, course_version=course_version)
    # Fill as a placeholder
    f["surface"] = tgc_definitions.featuresToSurfaces["surface1"]
    return f

def newTree(point):
    # Just set radius and height to be generic values
    return (point[0], point[2], 7.0, 10.0)

def addHalfwayPoint(points):
    first = points[0]
    last = points[-1]
    new_point = ((first[0] + last[0])/2.0, (first[1]+last[1])/2.0, (first[2]+last[2])/2.0)

    return (first, new_point, last)

def newHole(userpar, points, course_version):
    if course_version not in tgc_definitions.version_tags:
        print("invalid version")
        print(course_version)
        return None

    tee_tag = tgc_definitions.version_tags[course_version]['tees']
    pin_tag = tgc_definitions.version_tags[course_version]['pins']

    hole = json.loads('{"waypoints": [], "'+tee_tag+'": [], "'+pin_tag+'": [],"greenRadius": 0.0,"teeRadius": 0.0,"fairwayRadius": 0.0, \
            "fairwayStart": 0.0,"fairwayEnd": 0.0,"fairwayNoiseScale": -1.0,"roughRadius": 0.0,"heavyRoughRadius": 0.0,"hazardGreenCount": 0.0,"hazardFairwayCount": 0.0, \
            "hazardFairwayPeriod": -1.0,"teeHeight": -1.0, "greenSeed": 206208328, "fairwaySeed": 351286870,"teeTexture": -1, \
            "creatorDefinedPar": -1, "name": "","flagOffset": {"x": 0.0,"y": 0.0},"par": 4}')

    hole["creatorDefinedPar"] = userpar

    if len(points) < 2: # Minimum needed points
        return None
    elif len(points) == 2: # Autogenerated courses put the waypoint halfway between teebox and green.
        points = addHalfwayPoint(points)
    elif len(points) > 3: # Game only supports start point, waypoint, and endpoint
        points = [points[0], points[1], points[-1]] 

    for p in points:
        hole["waypoints"].append(getwaypoint3D(p[0], 0.0, p[2]))

    if course_version == 25:
        tee = {}
        tee["position"] = getwaypoint3D(points[0][0], 0.0, points[0][2]) 
        pin = {}
        pin["position"] = getwaypoint3D(0.0, 0.0, 0.0)
    else:
        tee = getwaypoint3D(points[0][0], 0.0, points[0][2])
        pin = getwaypoint3D(0.0, 0.0, 0.0)

    hole[tee_tag].append(tee)
    hole[pin_tag].append(pin)

    return hole

def getOSMData(bottom_lat, left_lon, top_lat, right_lon, printf=print):
    op = overpy.Overpass()
    # Order is South, West, North, East
    coord_string = str(bottom_lat) + "," + str(left_lon) + "," + str(top_lat) + "," + str(right_lon)
    try:
        query = "(node(" + coord_string + ");way(" + coord_string + ");rel(" + coord_string + "););out;"
        printf("OpenStreetMap Overpass query: " + query)
        return op.query(query) # Request both nodes and ways for the region of interest using a union
    except overpy.exception.OverPyException:
        printf("OpenStreetMap servers are too busy right now.  Try running this tool later.")
        return None

def parseOSMData(xml_data, printf=print):
    try:
        op = overpy.Overpass()
        return op.parse_xml(xml_data)
    except Exception as exc:
        printf("Could not parse local OpenStreetMap file: " + str(exc))
        return None

def clearFeatures(course_json, course_version):
    if course_version not in tgc_definitions.version_tags:
        print("invalid version")
        print(course_version)
        return None

    hole_tag = tgc_definitions.version_tags[course_version]['holes']
    spline_tag = tgc_definitions.version_tags[course_version]['splines']

    # Clear splines?  Make this optional
    course_json[spline_tag] = []
    # Game will crash if more than 18 holes found, so always clear holes
    course_json[hole_tag] = []
    return course_json

def addOSMToTGC(course_json, geopointcloud, osm_result, x_offset=0.0, y_offset=0.0, options_dict={}, spline_configuration_json=None, printf=print, course_version=-1, resolve_missing_nodes=True):
    global spline_configuration

    if course_version not in tgc_definitions.version_tags:
        print("invalid version")
        print(course_version)
        return None

    hole_tag = tgc_definitions.version_tags[course_version]['holes']    
    spline_tag = tgc_definitions.version_tags[course_version]['splines']

    # Ways represent features composed of many lat/long points (nodes)
    # We can convert these directly into the game's splines

    spline_configuration = spline_configuration_json

    # Get terrain bounding box
    ul_enu = geopointcloud.ulENU()
    lr_enu = geopointcloud.lrENU()
    ul_tgc = geopointcloud.enuToTGC(*ul_enu, 0.0)
    lr_tgc = geopointcloud.enuToTGC(*lr_enu, 0.0)

    course_json = clearFeatures(course_json, course_version)

    hole_dictionary = dict() # Holes must be ordered by hole_num.  Must keep track of return order just in case data doesn't have hole number
    num_ways = len(osm_result.ways)
    num_rels = len(osm_result.relations)
    last_print_time = time.time()
    way_dict = {}

    # Pre-detect bunker multipolygons with golf=rough inner islands.
    # Their member ways are consumed by the relation converter so the normal
    # way loop does not create duplicate overlapping bunker/rough splines.
    bunker_hole_relation_ids = set()
    bunker_hole_consumed_way_ids = set()
    bunker_hole_way_lookup = {
        way.id: way for way in osm_result.ways
    }

    if (
        options_dict.get('bunker', True) and
        options_dict.get('rough', True)
    ):
        for rel in osm_result.relations:
            if _relation_is_bunker_with_rough_inner(
                rel,
                bunker_hole_way_lookup
            ):
                bunker_hole_relation_ids.add(rel.id)

                for member in rel.members:
                    if not isinstance(member, overpy.RelationWay):
                        continue

                    way = bunker_hole_way_lookup.get(member.ref)
                    if way is None:
                        continue

                    role = str(member.role or "").lower()
                    if role == "outer":
                        bunker_hole_consumed_way_ids.add(member.ref)
                    elif (
                        role == "inner" and
                        way.tags.get("golf", None) == "rough"
                    ):
                        bunker_hole_consumed_way_ids.add(member.ref)

        if bunker_hole_relation_ids:
            printf(
                "Detected " + str(len(bunker_hole_relation_ids)) +
                " bunker multipolygon relation(s) with rough inner islands."
            )

    for n, way in enumerate(osm_result.ways):
        if way.id in bunker_hole_consumed_way_ids:
            continue
        if time.time() > last_print_time + status_print_duration:
            last_print_time = time.time()
            printf(str(round(100.0*float(n) / num_ways, 2)) + "% through OpenStreetMap Ways")

        way_dict[way.id] = way
        golf_type = way.tags.get("golf", None)
        waterway_type = way.tags.get("waterway", None)
        building_type = way.tags.get("building", None)
        natural_type = way.tags.get("natural", None)
        highway_type = way.tags.get("highway", None)
        golf_cart_type = way.tags.get("golf_cart", None)
        foot_type = way.tags.get("foot", None)
        amenity_type = way.tags.get("amenity", None)

        # Double checking types, but things REALLY slow down if we do the necessary bounding box checks without checking if it's a type we even care about
        if all(v is None for v in [golf_type, waterway_type, building_type, natural_type, highway_type, amenity_type]):
            continue

        area = False
        try:
            area = "yes" == way.tags.get("area", None)
        except:
            pass

        # Get the shape of this way
        nds = []
        try:
            for node in way.get_nodes(resolve_missing=resolve_missing_nodes): # Allow automatically resolving missing nodes, but this is VERY slow with the API requests, try to request beforehand
                nds.append(geopointcloud.latlonToTGC(node.lat, node.lon, x_offset, y_offset))
        except overpy.exception.OverPyException:
            printf("OpenStreetMap servers are too busy right now.  Try running this tool later." if resolve_missing_nodes else "Local OSM file is incomplete: a way/relation references nodes that are not present in the file.")
            return []
        # Check this shapes bounding box against the limits of the terrain, don't draw outside this bounds
        # Left, Top, Right, Bottom
        nbb = nodeBoundingBox(nds)
        if nbb[0] < ul_tgc[0] or nbb[1] > ul_tgc[2] or nbb[2] > lr_tgc[0] or nbb[3] < lr_tgc[2]:
            # Off of map, skip
            continue

        if golf_type is not None:
            if golf_type == "green" and options_dict.get('green', True):
                course_json[spline_tag].append(newGreen(nds, course_version))
            elif golf_type == "bunker" and options_dict.get('bunker', True):
                course_json[spline_tag].append(newBunker(nds, course_version))
            elif golf_type == "tee" and options_dict.get('teebox', True):
                course_json[spline_tag].append(newTeeBox(nds, course_version))
            elif golf_type == "fairway" and options_dict.get('fairway', True):
                course_json[spline_tag].append(newFairway(nds, course_version))
            elif golf_type == "driving_range" and options_dict.get('range', True):
                # Add as fairway
                course_json[spline_tag].append(newFairway(nds, course_version))
            elif golf_type == "rough" and options_dict.get('rough', True):
                course_json[spline_tag].append(newRough(nds, course_version))
            elif (golf_type == "water_hazard" or golf_type == "lateral_water_hazard") and options_dict.get('water', True):
                course_json[spline_tag].append(newWaterHazard(nds, area=True, course_version=course_version))
            elif golf_type == "cartpath" and options_dict.get('cartpath', True):
                course_json[spline_tag].append(newCartPath(nds, area=area, course_version=course_version))
            elif golf_type == "path" and options_dict.get('path', True):
                course_json[spline_tag].append(newWalkingPath(nds, area=area, course_version=course_version))
            elif golf_type == "clubhouse" and options_dict.get('building', True):
                course_json[spline_tag].append(newBuilding(nds, course_version))
            elif golf_type == "hole" and options_dict.get('hole', True):
                # Only add holes for the course we're interested in
                name_filter = options_dict.get('hole_name_filter', None)
                hole_name = way.tags.get("name", "")
                if name_filter is not None:
                    if name_filter.lower() not in hole_name.lower():
                        if hole_name:
                            printf("Skipping Hole with Name: " + hole_name)
                        else:
                            printf("Skipping Unnamed Hole")
                        continue
                try:
                    par = int(way.tags.get("par", -1))
                    hole_num = int(way.tags.get("ref", -1))
                except:
                    printf("ERROR: There is an invalid character saved to OpenStreetMap for par or hole number: " + str(way.tags))
                    par = -1
                    hole_num = -1
                hole = newHole(par, nds, course_version)
                if hole is not None:
                    if hole_num == 0:
                        hole_num = len(hole_dictionary) + 1
                    hole_dictionary[hole_num] = hole
            else:
                printf("Skipping: " + golf_type)
        elif waterway_type is not None:
            # Draw these as water hazards no matter what subtype they are
            if options_dict.get('water', True):
                course_json[spline_tag].append(newWaterHazard(nds, area=area, course_version=course_version))
        elif building_type is not None:
            # Draw these as buildings no matter what subtype they are
            if options_dict.get('building', True):
                course_json[spline_tag].append(newBuilding(nds, course_version))
        elif natural_type is not None:
            if natural_type == "wood" and options_dict.get('tree', True):
                course_json[spline_tag].append(newForest(nds, course_version))
        elif highway_type is not None and highway_type not in ["proposed", "construction"]:
            implicit_foot_access = {"motorway": "no",
                                    "motorway_link": "no",
                                    "trunk": "no",
                                    "trunk_link": "no"}

            way_foot_access = foot_type if foot_type is not None else implicit_foot_access.get(highway_type, "yes")

            if golf_cart_type is not None and golf_cart_type != "no" and options_dict.get('cartpath', True):
                course_json[spline_tag].append(newCartPath(nds, area=area, course_version=course_version))
            elif way_foot_access != "no" and options_dict.get('path', True) and options_dict.get('all_osm_paths', True):
                course_json[spline_tag].append(newWalkingPath(nds, area=area, course_version=course_version))
        elif amenity_type == "parking" and golf_cart_type is not None and golf_cart_type != "no" and options_dict.get('cartpath', True):
            course_json[spline_tag].append(newCartPath(nds, area=True, course_version=course_version))

    for n, rel in enumerate(osm_result.relations):
        if time.time() > last_print_time + status_print_duration:
            last_print_time = time.time()
            printf(str(round(100.0*float(n) / num_rels, 2)) + "% through OpenStreetMap Relations")

        golf_type = rel.tags.get("golf", None)

        if rel.id in bunker_hole_relation_ids:
            try:
                bunker_splines, rough_splines, consumed_ids = (
                    _build_bunker_rough_multipolygon_splines(
                        rel,
                        bunker_hole_way_lookup,
                        geopointcloud,
                        x_offset,
                        y_offset,
                        resolve_missing_nodes,
                        course_version,
                        printf=printf,
                    )
                )
            except overpy.exception.OverPyException:
                printf(
                    "OpenStreetMap servers are too busy right now. Try later."
                    if resolve_missing_nodes else
                    "Local OSM file is incomplete: a bunker multipolygon "
                    "references nodes that are not present in the file."
                )
                return []
            except Exception as exc:
                printf(
                    "Warning: bunker rough-inner conversion failed for relation " +
                    str(rel.id) + ": " + str(exc)
                )
                bunker_splines = []
                rough_splines = []

            if bunker_splines:
                for spline in bunker_splines:
                    course_json[spline_tag].append(spline)
                for spline in rough_splines:
                    course_json[spline_tag].append(spline)

                printf(
                    "Imported bunker relation " + str(rel.id) +
                    " as lollipop bunker hole(s) for 2K25."
                )
                continue

        if golf_type == "fairway" and options_dict.get('fairway', True):
            for member in rel.members:
                if isinstance(member, overpy.RelationWay) and member.role == "outer":
                    wayref = way_dict[member.ref]

                    nds = []
                    try:
                        for node in wayref.get_nodes(resolve_missing=resolve_missing_nodes): # Allow automatically resolving missing nodes, but this is VERY slow with the API requests, try to request beforehand
                            nds.append(geopointcloud.latlonToTGC(node.lat, node.lon, x_offset, y_offset))
                    except overpy.exception.OverPyException:
                        printf("OpenStreetMap servers are too busy right now.  Try running this tool later." if resolve_missing_nodes else "Local OSM file is incomplete: a way/relation references nodes that are not present in the file.")
                        return []

                    # Check this shapes bounding box against the limits of the terrain, don't draw outside this bounds
                    # Left, Top, Right, Bottom
                    nbb = nodeBoundingBox(nds)
                    if nbb[0] < ul_tgc[0] or nbb[1] > ul_tgc[2] or nbb[2] > lr_tgc[0] or nbb[3] < lr_tgc[2]:
                        # Off of map, skip
                        continue

                    fw_spline = newFairway(nds, course_version)
                    course_json[spline_tag].append(fw_spline)
        elif golf_type == "rough" and options_dict.get('rough', True):
            for member in rel.members:
                if isinstance(member, overpy.RelationWay) and member.role == "outer":
                    wayref = way_dict[member.ref]

                    nds = []
                    try:
                        for node in wayref.get_nodes(resolve_missing=resolve_missing_nodes): # Allow automatically resolving missing nodes, but this is VERY slow with the API requests, try to request beforehand
                            nds.append(geopointcloud.latlonToTGC(node.lat, node.lon, x_offset, y_offset))
                    except overpy.exception.OverPyException:
                        printf("OpenStreetMap servers are too busy right now.  Try running this tool later." if resolve_missing_nodes else "Local OSM file is incomplete: a way/relation references nodes that are not present in the file.")
                        return []

                    # Check this shapes bounding box against the limits of the terrain, don't draw outside this bounds
                    # Left, Top, Right, Bottom
                    nbb = nodeBoundingBox(nds)
                    if nbb[0] < ul_tgc[0] or nbb[1] > ul_tgc[2] or nbb[2] > lr_tgc[0] or nbb[3] < lr_tgc[2]:
                        # Off of map, skip
                        continue

                    fw_spline = newRough(nds, course_version)
                    course_json[spline_tag].append(fw_spline)

    # Insert all the found holes
    for key in sorted(hole_dictionary):
        course_json[hole_tag].append(hole_dictionary[key])
    
    trees = [] # Trees must be dealt with differently, and are passed up to a higher level.  Tree format is (x, z, radius, height)
    if options_dict.get('tree', False): # Trees are currently the only node right now.  This takes a lot of time to loop through, so skip if possible
        if not options_dict.get('lidar_trees', False):
            num_nodes = len(osm_result.nodes)
            last_print_time = time.time()
            for n, node in enumerate(osm_result.nodes):
                if time.time() > last_print_time + status_print_duration:
                    last_print_time = time.time()
                    printf(str(round(100.0*float(n) / num_nodes, 2)) + "% done looking for OpenStreetMap Trees")

                natural_type = node.tags.get("natural", None)
                if natural_type == "tree":
                    nd = geopointcloud.latlonToTGC(node.lat, node.lon, x_offset, y_offset)
                    # Check this shapes bounding box against the limits of the terrain, don't draw outside this bounds
                    # Left, Top, Right, Bottom
                    nbb = nodeBoundingBox([nd])
                    if nbb[0] < ul_tgc[0] or nbb[1] > ul_tgc[2] or nbb[2] > lr_tgc[0] or nbb[3] < lr_tgc[2]:
                        # Off of map, skip
                        continue
                    trees.append(newTree(nd))
        else:
            printf("Lidar trees requested: not adding trees from OpenStreetMap")

    # Return the tree list for later use
    return trees

def addOSMFromXML(course_json, xml_data, options_dict={}, printf=print, course_version=-1):
    printf("Adding OpenStreetMap from XML")
    op = overpy.Overpass()
    result = op.parse_xml(xml_data)

    printf("Determining the UTM Geo Projection for this area")
    # Find the lat and lon bounding box from the XML directly
    # Can't find the query bounds in overpy
    root = ET.fromstring(xml_data)
    for bounds in root.iter('bounds'):
        latmin = float(bounds.get('minlat'))
        latmax = float(bounds.get('maxlat'))
        lonmin = float(bounds.get('minlon'))
        lonmax = float(bounds.get('maxlon'))
        break
    
    # Create a basic geopointcloud to handle this projection
    pc = GeoPointCloud()
    pc.addFromLatLon((latmin, lonmin), (latmax, lonmax), printf=printf)

    trees = addOSMToTGC(course_json, pc, result, x_offset=float(options_dict.get('adjust_ew', 0.0)), y_offset=float(options_dict.get('adjust_ns', 0.0)), \
                options_dict=options_dict, printf=printf, course_version=course_version)

    return course_json, trees

def drawWayOnImage(way, color, im, pc, image_scale, thickness=-1, x_offset=0.0, y_offset=0.0):
    # Get the shape of this way and draw it as a poly
    nds = []
    for node in way.get_nodes(resolve_missing=True): # Allow automatically resolving missing nodes, but this is VERY slow with the API requests, try to request them above instead
        nds.append(pc.latlonToCV2(node.lat, node.lon, image_scale, x_offset, y_offset))
    # Uses points and not image pixels, so flip the x and y
    nds = np.array(nds)
    nds[:,[0, 1]] = nds[:,[1, 0]]
    nds = np.int32([nds]) # Bug with fillPoly, needs explict cast to 32bit
    cv2.fillPoly(im, nds, color) 

    # Add option to draw shape again, but with thick line
    # Use this to automatically expand some shapes, for example water
    # For better masking
    if thickness > 0:
        # Need to draw again since fillPoly has no line thickness options that I've found
        cv2.polylines(im, nds, True, color, thickness, lineType=cv2.LINE_AA)

def drawWayLineOnImage(way, color, im, pc, image_scale, thickness=1, closed=False, x_offset=0.0, y_offset=0.0):
    # Draw ONLY the outline/polyline of this way, without fill.
    nds = []
    for node in way.get_nodes(resolve_missing=True):
        nds.append(pc.latlonToCV2(node.lat, node.lon, image_scale, x_offset, y_offset))

    if len(nds) < 2:
        return

    nds = np.array(nds)
    nds[:, [0, 1]] = nds[:, [1, 0]]
    nds = np.int32([nds])

    try:
        thickness = max(1, int(thickness))
    except Exception:
        thickness = 1

    cv2.polylines(im, nds, closed, color, thickness, lineType=cv2.LINE_AA)

def addOSMToImage(ways, im, pc, image_scale, x_offset=0.0, y_offset=0.0, printf=print):
    water_feature_count = 0
    waterway_feature_count = 0

    for way in ways:
        golf_type = way.tags.get("golf", None)
        natural_type = way.tags.get("natural", None)
        waterway_type = way.tags.get("waterway", None)
        area_tag = way.tags.get("area", None)

        thickness = -1
        color = None
        render_mode = "fill"

        if golf_type is not None:
            # Default to fairway-like green
            color = (0, 0.75, 0.2)
            if golf_type == "green":
                color = (0, 1.0, 0.2)
            elif golf_type == "tee":
                color = (0, 0.8, 0)
            elif golf_type == "water_hazard" or golf_type == "lateral_water_hazard":
                color = (0, 0, 1.0)
                render_mode = "fill"
                water_feature_count += 1
            elif golf_type == "fairway":
                color = color
            else:
                color = None

        # Also paint standard OSM water features into the same bright-blue mask.
        if color is None:
            if natural_type == "water":
                color = (0, 0, 1.0)
                render_mode = "fill"
                water_feature_count += 1
            elif waterway_type is not None:
                color = (0, 0, 1.0)
                waterway_feature_count += 1
                if area_tag == "yes":
                    render_mode = "fill"
                    thickness = -1
                else:
                    render_mode = "line"
                    # Waterways are often linear ways instead of closed areas.
                    # Give them a modest stroke so they survive rasterization.
                    try:
                        thickness = max(3, int(round(6.0 / max(float(image_scale), 0.001))))
                    except Exception:
                        thickness = 3

        if color is not None:
            if render_mode == "line":
                drawWayLineOnImage(
                    way, color, im, pc, image_scale,
                    thickness=thickness, closed=False,
                    x_offset=x_offset, y_offset=y_offset
                )
            else:
                drawWayOnImage(way, color, im, pc, image_scale, thickness, x_offset, y_offset)

    # Draw bunkers last on top of all other layers as a hack until proper layer order is established here
    # Needed for things like bunkers in greens...  :\
    for way in ways:
        golf_type = way.tags.get("golf", None)
        if golf_type == "bunker":
            color = (0.85, 0.85, 0.7)
            drawWayOnImage(way, color, im, pc, image_scale, x_offset=x_offset, y_offset=y_offset)

    # FINAL PURE-BLUE WATER MASK PASS
    #
    # Repaint water after every other OSM feature (including bunkers) so the
    # saved mask always contains unmistakable pure blue wherever water exists.
    # The image at this stage is RGB float data in the range 0..1, therefore
    # (0, 0, 1.0) becomes RGB (0, 0, 255) in mask.png.
    pure_blue = (0, 0, 1.0)
    final_water_areas = 0
    final_waterways = 0

    for way in ways:
        golf_type = way.tags.get("golf", None)
        natural_type = way.tags.get("natural", None)
        waterway_type = way.tags.get("waterway", None)
        area_tag = way.tags.get("area", None)

        # Closed/area water: fill solid pure blue.
        if (golf_type == "water_hazard" or
            golf_type == "lateral_water_hazard" or
            natural_type == "water"):
            drawWayOnImage(
                way, pure_blue, im, pc, image_scale,
                -1, x_offset, y_offset
            )
            final_water_areas += 1
            continue

        # waterway=* is commonly a line. Draw open waterways as polylines only.
        if waterway_type is not None:
            if area_tag == "yes":
                drawWayOnImage(
                    way, pure_blue, im, pc, image_scale,
                    -1, x_offset, y_offset
                )
            else:
                try:
                    waterway_thickness = max(
                        3,
                        int(round(6.0 / max(float(image_scale), 0.001)))
                    )
                except Exception:
                    waterway_thickness = 3

                try:
                    drawWayLineOnImage(
                        way, pure_blue, im, pc, image_scale,
                        thickness=waterway_thickness, closed=False,
                        x_offset=x_offset, y_offset=y_offset
                    )
                except Exception as exc:
                    printf(
                        "Warning: could not draw waterway " +
                        str(getattr(way, "id", "?")) +
                        " into blue mask: " + str(exc)
                    )

            final_waterways += 1

    if water_feature_count or waterway_feature_count:
        printf("OSM preview/mask water rendering: " +
               str(water_feature_count) + " area/hazard water features, " +
               str(waterway_feature_count) + " waterway features")

    if final_water_areas or final_waterways:
        printf(
            "FINAL PURE-BLUE mask pass: " +
            str(final_water_areas) + " water areas/hazards, " +
            str(final_waterways) + " waterways -> RGB 0,0,255"
        )

    return im
