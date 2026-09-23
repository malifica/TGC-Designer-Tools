import cv2
import json
import math
import matplotlib.pyplot as plt
import numpy as np
import overpy
import sys

from GeoPointCloud import GeoPointCloud
import tgc_definitions
import tgc_tools

# TGC_DYNAMIC_COURSE_PREVIEW_V1
# Preview-only sizing. This does not modify course JSON, terrain stamps, CFS
# georeferencing, LiDAR/DEM data, or exported course coordinates.
PREVIEW_MIN_EXTENT_M = 2000.0
PREVIEW_PADDING_M = 50.0
PREVIEW_MAX_RASTER_DIM = 2400


class _PreviewPointCloud:
    """Minimal TGC->preview coordinate mapper for arbitrary preview bounds."""

    def __init__(self, min_x, min_z, width, height):
        self.min_x = float(min_x)
        self.min_z = float(min_z)
        self.width = float(width)
        self.height = float(height)

    def tgcToCV2(self, x, z, image_scale):
        column = int((float(x) - self.min_x) / float(image_scale))
        row = int((float(z) - self.min_z) / float(image_scale))
        return (row, column)


def _preview_bounds(course_json, course_version):
    """Return preview bounds that contain visible course content.

    The old visualizer always rendered -1000..+1000 m in X/Z. Keep a
    2000x2000 m minimum for normal courses, but grow the preview when terrain,
    splines, holes, water, OOB/crowd brushes, or objects extend farther.
    """
    if course_version not in tgc_definitions.version_tags:
        return (-1000.0, -1000.0, 1000.0, 1000.0)

    if course_version == 25:
        layer_json = course_json
        dim2 = "z"
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
        dim2 = "y"
    else:
        layer_json = course_json["userLayers"]
        dim2 = "y"

    hole_tag = tgc_definitions.version_tags[course_version]["holes"]
    tee_tag = tgc_definitions.version_tags[course_version]["tees"]
    crowd_tag = tgc_definitions.version_tags[course_version]["crowd"]
    spline_tag = tgc_definitions.version_tags[course_version]["splines"]
    surface_tag = tgc_definitions.version_tags[course_version]["surfaces"]
    if surface_tag not in course_json:
        surface_tag += "2"
    oob_tag = tgc_definitions.version_tags[course_version]["oob"]
    obj_tag = tgc_definitions.version_tags[course_version]["objects"]

    bounds = [math.inf, math.inf, -math.inf, -math.inf]

    def add_point(x, z, pad_x=0.0, pad_z=0.0):
        try:
            x = float(x)
            z = float(z)
            pad_x = abs(float(pad_x))
            pad_z = abs(float(pad_z))
        except Exception:
            return
        if not (math.isfinite(x) and math.isfinite(z)):
            return
        bounds[0] = min(bounds[0], x - pad_x)
        bounds[1] = min(bounds[1], z - pad_z)
        bounds[2] = max(bounds[2], x + pad_x)
        bounds[3] = max(bounds[3], z + pad_z)

    def add_brushes(brushes):
        for brush in brushes or []:
            if not isinstance(brush, dict):
                continue
            position = brush.get("position", {})
            scale = brush.get("scale", {})
            add_point(
                position.get("x", 0.0),
                position.get("z", 0.0),
                scale.get("x", 0.0),
                scale.get("z", 0.0),
            )

    # Terrain and visible brush layers.
    add_brushes(layer_json.get("terrainHeight", []))
    add_brushes(layer_json.get("height", []))
    add_brushes(layer_json.get("water", []))
    add_brushes(layer_json.get(surface_tag, []))

    oob_json = layer_json.get(oob_tag, [])
    crowd_json = layer_json.get(crowd_tag, [])
    if course_version == 25:
        if isinstance(oob_json, dict):
            oob_json = oob_json.get("brushes", [])
        if isinstance(crowd_json, dict):
            crowd_json = crowd_json.get("brushes", [])
    add_brushes(oob_json)
    add_brushes(crowd_json)

    # Surface splines, including Bezier handles and spline widths.
    for spline in course_json.get(spline_tag, []) or []:
        try:
            spline_pad = abs(float(spline.get("width", 0.0)))
            spline_pad += max(0.0, abs(float(spline.get("secondaryWidth", 0.0))))
        except Exception:
            spline_pad = 0.0

        for wp in spline.get("waypoints", []) or []:
            for key in ("waypoint", "pointOne", "pointTwo"):
                point = wp.get(key, {})
                add_point(
                    point.get("x", 0.0),
                    point.get(dim2, 0.0),
                    spline_pad,
                    spline_pad,
                )

    # Hole routes and tee positions.
    for hole in course_json.get(hole_tag, []) or []:
        for point in hole.get("waypoints", []) or []:
            add_point(point.get("x", 0.0), point.get("z", 0.0), 5.0, 5.0)

        for tee in hole.get(tee_tag, []) or []:
            point = tee.get("position", {}) if course_version == 25 else tee
            if isinstance(point, dict):
                add_point(point.get("x", 0.0), point.get("z", 0.0), 5.0, 5.0)

    # Placed objects and clusters.
    for group in course_json.get(obj_tag, []) or []:
        value = group.get("Value", {}) if isinstance(group, dict) else {}

        for item in value.get("items", []) or []:
            position = item.get("position", {})
            scale = item.get("scale", {})
            # Object scale is not a reliable meter size, so keep a modest
            # visual margin while still accounting for larger scales.
            pad_x = max(5.0, abs(float(scale.get("x", 1.0))) * 5.0)
            pad_z = max(5.0, abs(float(scale.get("z", 1.0))) * 5.0)
            add_point(position.get("x", 0.0), position.get("z", 0.0), pad_x, pad_z)

        for cluster in value.get("clusters", []) or []:
            position = cluster.get("position", {})
            radius = cluster.get("radius", 0.0)
            add_point(position.get("x", 0.0), position.get("z", 0.0), radius, radius)

    if not all(math.isfinite(v) for v in bounds):
        return (-1000.0, -1000.0, 1000.0, 1000.0)

    min_x, min_z, max_x, max_z = bounds
    min_x -= PREVIEW_PADDING_M
    min_z -= PREVIEW_PADDING_M
    max_x += PREVIEW_PADDING_M
    max_z += PREVIEW_PADDING_M

    width = max_x - min_x
    height = max_z - min_z

    # Keep the historical 2000 m minimum, centered on the actual course.
    if width < PREVIEW_MIN_EXTENT_M:
        center_x = 0.5 * (min_x + max_x)
        half = 0.5 * PREVIEW_MIN_EXTENT_M
        min_x = center_x - half
        max_x = center_x + half

    if height < PREVIEW_MIN_EXTENT_M:
        center_z = 0.5 * (min_z + max_z)
        half = 0.5 * PREVIEW_MIN_EXTENT_M
        min_z = center_z - half
        max_z = center_z + half

    return (min_x, min_z, max_x, max_z)


def drawBrushesOnImage(brushes, color, im, pc, image_scale, fill=True):
    for brush in brushes:
        center = pc.tgcToCV2(brush["position"]["x"], brush["position"]["z"], image_scale)
        center = (center[1], center[0]) # In point coordinates, not pixel
        width = brush["scale"]["x"] / image_scale
        height = brush["scale"]["z"] / image_scale
        rotation = - brush["rotation"]["y"] # Inverted degrees, cv2 bounding_box uses degrees

        thickness = 4
        if fill:
            thickness = -1 # Negative thickness is a filled ellipse

        brush_type_name = tgc_definitions.brushes.get(int(brush["type"]), "unknown")

        if 'square' in brush_type_name:
            box_points = cv2.boxPoints((center, (2.0*width, 2.0*height), rotation)) # Squares seem to be larger than circles
            box_points = np.int32([box_points]) # Bug with fillPoly, needs explict cast to 32bit

            if fill:
                cv2.fillPoly(im, box_points, color, lineType=cv2.LINE_AA)
            else:
                cv2.polylines(im, box_points, True, color, thickness, lineType=cv2.LINE_AA)
        else: # Draw as ellipse for now
            '''center – The rectangle mass center.
            size – Width and height of the rectangle.
            angle – The rotation angle in a clockwise direction. When the angle is 0, 90, 180, 270 etc., the rectangle becomes an up-right rectangle.'''
            bounding_box =  (center, (1.414*width, 1.414*height), rotation) # Circles seem to scale according to radius
            cv2.ellipse(im, bounding_box, color, thickness=thickness, lineType=cv2.LINE_AA)  

def drawSplinesOnImage(splines, color, im, pc, image_scale, course_version):
    for s in splines:
        # Get the shape of this spline and draw it on the image
        nds = []
        dim2 = "y"
        if course_version == 25:
            dim2 = "z"

        for wp in s["waypoints"]:
            nds.append(pc.tgcToCV2(wp["waypoint"]["x"], wp["waypoint"][dim2], image_scale))

        # Don't try to draw malformed splines
        if len(nds) == 0:
            continue

        # Uses points and not image pixels, so flip the x and y
        nds = np.array(nds)
        nds[:,[0, 1]] = nds[:,[1, 0]]
        nds = np.int32([nds]) # Bug with fillPoly, needs explict cast to 32bit

        thickness = int(s["width"])
        if(thickness < image_scale):
            thickness = int(image_scale)

        if ("isFilled" in s and s["isFilled"]) or (s["state"] == 3):
            cv2.fillPoly(im, nds, color, lineType=cv2.LINE_AA)
        else:
            isClosed = None

            if "isClosed" in s:
                isClosed = s["isClosed"]
            else:
                isClosed = s["state"]

            cv2.polylines(im, nds, isClosed, color, thickness, lineType=cv2.LINE_AA)

def drawObjectsOnImage(objects, color, im, pc, image_scale):
    for ob in objects:
        for item in ob["Value"]["items"]:
            # Assuming all items are ellipses for now
            center = pc.tgcToCV2(item["position"]["x"], item["position"]["z"], image_scale)
            center = (center[1], center[0]) # In point coordinates, not pixel
            width = max(item["scale"]["x"] / image_scale, 8.0)
            height = max(item["scale"]["z"] / image_scale, 8.0)
            rotation = - item["rotation"]["y"] * math.pi / 180.0 # Inverted degrees, cv2 uses clockwise radians

            '''center – The rectangle mass center.
            size – Width and height of the rectangle.
            angle – The rotation angle in a clockwise direction. When the angle is 0, 90, 180, 270 etc., the rectangle becomes an up-right rectangle.'''

            bounding_box_of_ellipse =  (center, (width, height), rotation)

            cv2.ellipse(im, bounding_box_of_ellipse, color, thickness=-1, lineType=cv2.LINE_AA)

        for cluster in ob["Value"]["clusters"]:
            # Assuming all items are ellipses for now
            center = pc.tgcToCV2(cluster["position"]["x"], cluster["position"]["z"], image_scale)
            center = (center[1], center[0]) # In point coordinates, not pixel
            width = cluster["radius"] / image_scale
            height = cluster["radius"] / image_scale
            rotation = - cluster["rotation"]["y"] * math.pi / 180.0 # Inverted degrees, cv2 uses clockwise radians

            '''center – The rectangle mass center.
            size – Width and height of the rectangle.
            angle – The rotation angle in a clockwise direction. When the angle is 0, 90, 180, 270 etc., the rectangle becomes an up-right rectangle.'''

            bounding_box_of_ellipse =  (center, (width, height), rotation)

            cv2.ellipse(im, bounding_box_of_ellipse, color, thickness=-1, lineType=cv2.LINE_AA)

def drawHolesOnImage(holes, color, im, pc, image_scale, course_version):
    if course_version not in tgc_definitions.version_tags:
        return
    
    tee_tag = tgc_definitions.version_tags[course_version]['tees']

    for h in holes:
        # Get the shape of this spline and draw it on the image
        waypoints = []
        for wp in h["waypoints"]:
            waypoints.append(pc.tgcToCV2(wp["x"], wp["z"], image_scale))

        tees = []
        for t in h[tee_tag]:
            tp = t
            if course_version == 25:
                tp = t["position"]
            tees.append(pc.tgcToCV2(tp["x"], tp["z"], image_scale))

        # Going to skip drawing pinPositions due to low resolution

        # Uses points and not image pixels, so flip the x and y
        waypoints = np.array(waypoints)
        waypoints[:,[0, 1]] = waypoints[:,[1, 0]]
        tees = np.array(tees)
        tees[:,[0, 1]] = tees[:,[1, 0]]

        # Draw a line between each waypoint
        thickness = 5
        for i in range(0, len(waypoints)-1):
            first_point = tuple(waypoints[i])
            second_point = tuple(waypoints[i+1])
            cv2.line(im, first_point, second_point, color, thickness=thickness, lineType=cv2.LINE_AA)

        # Draw a line between each tee and the second waypoint
        first_waypoint = tuple(waypoints[1])
        for tee in tees:
            t = tuple(tee)
            cv2.line(im, t, first_waypoint, color, thickness=thickness, lineType=cv2.LINE_AA)

def drawCourseAsImage(course_json, course_version):
    # TGC_DYNAMIC_COURSE_PREVIEW_V1
    # Dynamically size the preview to visible course content. This is strictly
    # a visualizer change; no course coordinates or terrain data are modified.
    if course_version not in tgc_definitions.version_tags:
        return

    min_x, min_z, max_x, max_z = _preview_bounds(course_json, course_version)
    world_width = max(1.0, max_x - min_x)
    world_height = max(1.0, max_z - min_z)

    # Keep memory bounded for unusually large courses while preserving the
    # correct world aspect ratio.
    image_scale = max(
        1.0,
        world_width / float(PREVIEW_MAX_RASTER_DIM),
        world_height / float(PREVIEW_MAX_RASTER_DIM),
    )

    image_width_px = max(1, int(math.ceil(world_width / image_scale)) + 1)
    image_height_px = max(1, int(math.ceil(world_height / image_scale)) + 1)

    im = np.zeros((image_height_px, image_width_px, 3), np.float32)
    pc = _PreviewPointCloud(min_x, min_z, world_width, world_height)

    hole_tag = tgc_definitions.version_tags[course_version]['holes']
    crowd_tag = tgc_definitions.version_tags[course_version]['crowd']    
    spline_tag = tgc_definitions.version_tags[course_version]['splines']
    surface_tag = tgc_definitions.version_tags[course_version]['surfaces']
    if surface_tag not in course_json:
        surface_tag += '2'
    
    oob_tag = tgc_definitions.version_tags[course_version]['oob']
    obj_tag = tgc_definitions.version_tags[course_version]['objects']

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]
    
    # Draw terrain first
    drawBrushesOnImage(layer_json["terrainHeight"], (0.35, 0.2, 0.0), im, pc, image_scale)

    drawBrushesOnImage(layer_json["height"], (0.5, 0.2755, 0.106), im, pc, image_scale)

    # Next draw surfaces in correct stacking orders
    uls = layer_json[surface_tag]
    ss = course_json[spline_tag]

    # Draw real water
    water_color = (0.1, 0.2, 0.5)
    drawBrushesOnImage(layer_json["water"], water_color, im, pc, image_scale)

    # Mulch/Water Visualization Surface #2 has low priority, so draw it first
    # Drawing as the black/dark blue, but it will show up different depending on scene
    surface2_color = (0.1, 0.2, 0.25)
    drawSplinesOnImage([s for s in ss if s["surface"] == 8], surface2_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 8], surface2_color, im, pc, image_scale)

    # Then draw heavy rough
    heavy_rough_color = (0, 0.3, 0.1)
    drawSplinesOnImage([s for s in ss if s["surface"] == 4], heavy_rough_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 4], heavy_rough_color, im, pc, image_scale)

    # Then draw rough
    rough_color = (0.1, 0.35, 0.15)
    drawSplinesOnImage([s for s in ss if s["surface"] == 3], rough_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 3], rough_color, im, pc, image_scale)

    # Next draw fairways
    fairway_color = (0, 0.75, 0.2)
    drawSplinesOnImage([s for s in ss if s["surface"] == 2], fairway_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 2], fairway_color, im, pc, image_scale)

    # Next draw greens
    green_color = (0, 1.0, 0.2)
    drawSplinesOnImage([s for s in ss if s["surface"] == 1], green_color, im, pc, image_scale, course_version) 
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 1], green_color, im, pc, image_scale)

    # Next draw bunkers
    bunker_color = (0.85, 0.85, 0.7)
    drawSplinesOnImage([s for s in ss if s["surface"] == 0], bunker_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 0], bunker_color, im, pc, image_scale)

    # Surface #1 - Gravel?
    surface1_color = (0.7, 0.7, 0.7)
    drawSplinesOnImage([s for s in ss if s["surface"] == 7], surface1_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 7], surface1_color, im, pc, image_scale)

    # Surface #3 Cart Path
    cart_path_color = (0.3, 0.3, 0.3)
    drawSplinesOnImage([s for s in ss if s["surface"] == 10], cart_path_color, im, pc, image_scale, course_version)
    drawBrushesOnImage([b for b in uls if b is not None and b["surfaceCategory"] == 10], cart_path_color, im, pc, image_scale)

    # Don't draw brush or surface 5 because this is are clear generated trees
    # Don't draw brush or surface 6 because this is clear generated objects

    # Draw out of bounds as white boundaries
    out_of_bounds_color = (1.0, 1.0, 1.0)
    oob_json = layer_json[oob_tag]
    if course_version == 25:
        oob_json = oob_json["brushes"]
    drawBrushesOnImage(oob_json, out_of_bounds_color, im, pc, image_scale, fill=False)

    # Draw crowds as pink boundaries
    crowd_color = (1.0, 0.4, 0.75)
    crowd_json = layer_json[crowd_tag]
    if course_version == 25:
        crowd_json = crowd_json["brushes"]
    drawBrushesOnImage(crowd_json, crowd_color, im, pc, image_scale, fill=False)

    # Draw objects last in yellow
    object_color = (0.95, 0.9, 0.2)
    drawObjectsOnImage(course_json[obj_tag], object_color, im, pc, image_scale)

    # Last draw holes themselves
    hole_color = (0.9, 0.3, 0.2)
    drawHolesOnImage(course_json[hole_tag], hole_color, im, pc, image_scale, course_version)

    return im

if __name__ == "__main__":
    print("main")

    if len(sys.argv) < 2:
        print("Usage: python program.py COURSE_DIRECTORY")
        sys.exit(0)
    else:
        lidar_dir_path = sys.argv[1]

    print("Loading course file")
    course_json = tgc_tools.get_course_json(lidar_dir_path)

    im = drawCourseAsImage(course_json)

    fig = plt.figure()

    plt.imshow(im, origin='lower')

    plt.show()
