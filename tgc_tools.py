import base64
import cv2
import gzip
import itertools
import json
import math
import numpy as np
import os
from pathlib import Path
import tgc_definitions

def base64GZDecode(data):
    gz_data = base64.b64decode(data)
    return gzip.decompress(gz_data)

def base64GZEncode(data, level):
    gz_data = gzip.compress(data, compresslevel=level)
    return base64.b64encode(gz_data)

def create_directory(course_directory):
    course_dir = Path(course_directory)
    try:
        Path.mkdir(course_dir, mode=0o777)
    except FileExistsError as err:
        pass
    return course_dir

def get_course_file(course_directory):
    # Find the course file
    course_list = list(Path(course_directory).glob('*.course'))
    if not course_list:
        print("No courses found in: " + course_directory)
        return None
    elif len(course_list) > 1:
        print("More than one course found, using " + str(course_list[0]))
    return course_list[0]

def get_course_name(course_directory):
    course_file = get_course_file(course_directory)
    if course_file is None:
        return None
    return course_file.stem

def unpack_course_file(course_directory, course_file=None):
    # Make directory structure
    course_dir = Path(course_directory)
    output_dir = course_dir / 'unpacked'
    description_dir = output_dir / 'course_description'
    metadata_dir = output_dir / 'metadata'
    thumbnail_dir = output_dir / 'thumbnail'

    try:
        Path.mkdir(output_dir, mode=0o777)
        Path.mkdir(description_dir, mode=0o777)
        Path.mkdir(metadata_dir, mode=0o777)
        Path.mkdir(thumbnail_dir, mode=0o777)
    except FileExistsError as err:
        pass

    course_name = ""
    if course_file is None:
        course_file = get_course_file(course_directory)
        course_name = get_course_name(course_directory)

    with gzip.open(str(course_file), 'r') as f:
        file_content = f.read()
        course_json = json.loads(file_content.decode('utf-16'))

        with (output_dir / 'full.json').open('w') as f:
            f.write(file_content.decode('utf-16'))

        course_description64 = course_json["binaryData"]["CourseDescription"]
        thumbnail64 = course_json["binaryData"]["Thumbnail"]
        course_metadata64 = course_json["binaryData"]["CourseMetadata"]

        course_description_json = base64GZDecode(course_description64).decode('utf-16')
        # Remove potential strange unicode characters like u200b
        course_description_json = (course_description_json.encode('ascii', 'ignore')).decode("utf-8")
        with (description_dir / 'course_description.json').open('w') as f:
            f.write(course_description_json)

        thumbnail_json = base64GZDecode(thumbnail64).decode('utf-16')
        # Remove potential strange unicode characters like u200b
        thumbnail_json = (thumbnail_json.encode('ascii', 'ignore')).decode("utf-8")
        t_json = json.loads(thumbnail_json)
        with (thumbnail_dir / 'thumbnail.json').open('w') as f:
            f.write(thumbnail_json)
        thumbnail_jpg = base64.b64decode(t_json["image"])
        with (thumbnail_dir / 'thumbnail.jpg').open('wb') as f:
            f.write(thumbnail_jpg)

        course_metadata_json = base64GZDecode(course_metadata64).decode('utf-16')
        # Remove potential strange unicode characters like u200b
        course_metadata_json = (course_metadata_json.encode('ascii', 'ignore')).decode("utf-8")
        with (metadata_dir / 'course_metadata.json').open('w') as f:
            f.write(course_metadata_json)        

    return course_name

def pack_course_file(course_directory, course_name=None, output_file=None, course_json=None, course_version=-1):
    if course_version not in tgc_definitions.version_tags:
        return

    file_encoding = tgc_definitions.version_tags[course_version]['file_encoding']    
    course_dir = Path(course_directory)

    output_path = None
    if output_file is not None:
        output_path = Path(output_file)
    else:
        if course_name is None:
            course_name = get_course_name(course_directory)
            if course_name is None:
                # Nothing found, just use 'output.course'
                course_name = 'output'
        output_path = course_dir / (course_name + '.course')

    print("Saving course as: " + str(output_path))

    # Write out new course description before packing into course
    if course_json is not None:
        write_course_json(course_directory, course_json)

    with (course_dir / 'unpacked/course_description/course_description.json').open('r') as desc:
        with (course_dir / 'unpacked/metadata/course_metadata.json').open('r') as meta:
            with (course_dir / 'unpacked/thumbnail/thumbnail.json').open('r') as thumb:
                desc_read = desc.read()
                meta_read = meta.read()
                thumb_read = thumb.read()
                desc_encoded = base64GZEncode(desc_read.encode(file_encoding), 1).decode('utf-8')
                meta_encoded = base64GZEncode(meta_read.encode(file_encoding), 1).decode('utf-8')
                thumb_encoded = base64GZEncode(thumb_read.encode(file_encoding), 1).decode('utf-8')

                output_json = json.loads('{"data":{},"binaryData":{}}')
                output_json["binaryData"]["CourseDescription"] = desc_encoded
                output_json["binaryData"]["Thumbnail"] = thumb_encoded
                output_json["binaryData"]["CourseMetadata"] = meta_encoded

                # Special dense encoding used for course files
                output_string = json.dumps(output_json, separators=(',', ':'))
 
                # Write to final gz format
                output_gz = gzip.compress(output_string.encode(file_encoding), 1)

                with (output_path).open('wb') as f:
                    f.write(output_gz)
                
                return str(output_path)

def get_course_json(course_directory):
    course_dir = Path(course_directory)
    course_json = ""
    with (course_dir / 'unpacked/course_description/course_description.json').open('r') as f:
        course_json = json.loads(f.read())  
        
    return course_json

def get_metadata_json(course_directory):
    course_dir = Path(course_directory)
    metadata_json = ""
    with (course_dir / 'unpacked/metadata/course_metadata.json').open('r') as f:
        metadata_json = json.loads(f.read())  
        
    return metadata_json

def get_spline_configuration_json(course_directory):
    try:
        course_dir = Path(course_directory)
        spline_json = None
        with (course_dir / 'splines.json').open('r') as f:
            spline_json = json.loads(f.read())  
            
        return spline_json
    except:
        return None

def write_course_json(course_directory, course_json):
    course_dir = Path(course_directory)
    with (course_dir / 'unpacked/course_description/course_description.json').open('w') as f:
        # Reduce floating point resolution to save file space.  Round to millimeter
        # Workaround since dumps has no precision
        # https://stackoverflow.com/questions/1447287/format-floats-with-standard-json-module
        f.write(json.dumps(json.loads(json.dumps(course_json), parse_float=lambda x: round(float(x), 3)), separators=(',', ':')))

def write_metadata_json(course_directory, metadata_json):
    course_dir = Path(course_directory)
    with (course_dir / 'unpacked/metadata/course_metadata.json').open('w') as f:
        out = json.dumps(metadata_json, separators=(',', ':'))
        f.write(out)

def set_course_metadata_name(course_directory, new_course_name):
    metadata_json = get_metadata_json(course_directory)
    metadata_json["name"] = new_course_name
    write_metadata_json(course_directory, metadata_json)

def waypoint_dist(p1, p2):
    dx = p1["x"] - p2["x"]
    dz = p1["z"] - p2["z"]
    return math.sqrt(dx**2 + dz**2)

def get_hole_information(course_json, course_version):
    pars = []
    pin_counts = []
    tees = [[],[],[],[],[]]

    if course_version not in tgc_definitions.version_tags:
        return

    hole_tag = tgc_definitions.version_tags[course_version]['holes']
    pin_tag = tgc_definitions.version_tags[course_version]['pins']
    tee_tag = tgc_definitions.version_tags[course_version]['tees']

    for h in course_json[hole_tag]:
        # Par is same for all tees
        par = h["creatorDefinedPar"]
        if par <= 0: # Check if user specified par
            par = h["par"]
        pars.append(par)

        pin_counts.append(len(h[pin_tag]))

        # Get common yardage for all tees
        waypoints = h["waypoints"][1:] # Every point but the first point
        common_distance = 0.0
        for i in range(0, len(waypoints)-1):
            common_distance += waypoint_dist(waypoints[i], waypoints[i+1])

        # Get specific yardage for all tees, record total yardage for every possible tee
        for i in range(0, 5):
            if i < len(h[tee_tag]):
                tp = h[tee_tag][i]
                if course_version == 25:
                    tp = tp["position"]
                # Convert to yards, from meters
                total_dist = common_distance + waypoint_dist(tp, waypoints[0])
                tees[i].append(1.09*total_dist)
            else:
                tees[i].append(None)

    return pars, pin_counts, tees


def strip_terrain(course_json, output_file, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]

    # Copy existing terrain and write to disk

    output_data = {}
    output_data['terrainHeight'] = layer_json["terrainHeight"]
    output_data['height'] = layer_json["height"]

    print("Saving Terrain as " + output_file)
    np.save(output_file, output_data)

    # Clear existing terrain
    layer_json["terrainHeight"] = []
    layer_json["height"] = []

    return course_json

def insert_terrain(course_json, input_file, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]

    print("Loading terrain from: " + input_file)
    read_dictionary = np.load(input_file, allow_pickle=True).item()

    # Copy existing terrain and write to disk
    layer_json["terrainHeight"] = read_dictionary["terrainHeight"]
    layer_json["height"] = read_dictionary["height"]

    return course_json

def strip_holes(course_json, output_file, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    hole_tag = tgc_definitions.version_tags[course_version]['holes']

    # Copy existing holes and write to disk
    output_data = {}
    output_data['holes'] = course_json[hole_tag]

    print("Saving Holes as " + output_file)
    np.save(output_file, output_data)

    # Clear existing holes
    course_json[hole_tag] = []

    return course_json

def insert_holes(course_json, input_file, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    hole_tag = tgc_definitions.version_tags[course_version]['holes']

    print("Loading holes from: " + input_file)
    read_dictionary = np.load(input_file, allow_pickle=True).item()

    # Replace our holes from those in the file
    course_json[hole_tag] = read_dictionary['holes']

    return course_json

# Shift terrain and features are separate in case they need to be lined up with each other
def shift_terrain(course_json, easting_shift, northing_shift, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]

    for i in layer_json["height"]:
        i['position']['x'] += easting_shift
        i['position']['z'] += northing_shift

    for i in layer_json["terrainHeight"]:
        i['position']['x'] += easting_shift
        i['position']['z'] += northing_shift

    return course_json

def shift_features(course_json, easting_shift, northing_shift, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    dim2 = 'y'
    if course_version == 25:
        layer_json = course_json
        dim2 = 'z'
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]
    
    hole_tag = tgc_definitions.version_tags[course_version]['holes']
    tee_tag = tgc_definitions.version_tags[course_version]['tees']
    crowd_tag = tgc_definitions.version_tags[course_version]['crowd']    
    spline_tag = tgc_definitions.version_tags[course_version]['splines']
    surface_tag = tgc_definitions.version_tags[course_version]['surfaces']
    if course_version == 25 and surface_tag not in course_json:
        surface_tag += '2'

    oob_tag = tgc_definitions.version_tags[course_version]['oob']
    obj_tag = tgc_definitions.version_tags[course_version]['objects']

    # Shift splines
    for i in course_json[spline_tag]:
        for wp in i["waypoints"]:
            wp["pointOne"]["x"] += easting_shift
            wp["pointTwo"]["x"] += easting_shift
            wp["waypoint"]["x"] += easting_shift
            wp["pointOne"][dim2] += northing_shift
            wp["pointTwo"][dim2] += northing_shift
            wp["waypoint"][dim2] += northing_shift

    # Shift Holes
    for h in course_json[hole_tag]:
        for w in h["waypoints"]:
            w["x"] += easting_shift
            w["z"] += northing_shift
        for t in h[tee_tag]:
            tp = t
            if course_version == 25:
                tp = tp["position"]
            tp["x"] += easting_shift
            tp["z"] += northing_shift
        # Pin positions are in relative coordinates and don't need shifted

    # Shift Brushes
    oob_json = layer_json[oob_tag]
    crowd_json = layer_json[crowd_tag]
    if course_version == 25:
        oob_json = oob_json["brushes"]
        crowd_json = crowd_json["brushes"]
    for b in itertools.chain(layer_json[surface_tag],
                             layer_json["water"],
                             oob_json,
                             crowd_json):
        b['position']['x'] += easting_shift
        b['position']['z'] += northing_shift

    # Shift Objects
    for o in course_json[obj_tag]:
        for i in o["Value"]["items"]:
            i['position']['x'] += easting_shift
            i['position']['z'] += northing_shift

        for c in o["Value"]["clusters"]:
            c['position']['x'] += easting_shift
            c['position']['z'] += northing_shift

    return course_json

def shift_course(course_json, easting_shift, northing_shift, course_version):
    course_json = shift_terrain(course_json, easting_shift, northing_shift, course_version)
    return shift_features(course_json, easting_shift, northing_shift, course_version)

# TGC_HULKIFY_COURSE_V2_SLOPE_LOCK
# Enlarge the course horizontally while scaling vertical TERRAIN RELIEF by the
# same factor.  Scaling rise and run together preserves the original slope
# percentages and terrain severity instead of flattening the course.
def _hulkify_is_number(value):
    return (
        isinstance(value, (int, float)) and
        not isinstance(value, bool) and
        math.isfinite(float(value))
    )


def _hulkify_scale_absolute_point(point, center_x, center_z, factor, second_key="z"):
    if not isinstance(point, dict):
        return 0

    changed = 0
    if _hulkify_is_number(point.get("x")):
        point["x"] = center_x + (float(point["x"]) - center_x) * factor
        changed += 1
    if _hulkify_is_number(point.get(second_key)):
        point[second_key] = center_z + (
            float(point[second_key]) - center_z
        ) * factor
        changed += 1
    return changed


def _hulkify_scale_relative_point(point, factor, second_key="z"):
    if not isinstance(point, dict):
        return 0

    changed = 0
    if _hulkify_is_number(point.get("x")):
        point["x"] = float(point["x"]) * factor
        changed += 1
    if _hulkify_is_number(point.get(second_key)):
        point[second_key] = float(point[second_key]) * factor
        changed += 1
    return changed


def _hulkify_scale_sizes(container, factor, keys):
    if not isinstance(container, dict):
        return 0

    changed = 0
    for key in keys:
        if _hulkify_is_number(container.get(key)):
            container[key] = float(container[key]) * factor
            changed += 1
    return changed


def _hulkify_scale_absolute_height(value, datum, factor):
    return datum + (float(value) - datum) * factor


def _hulkify_scale_point_height(point, datum, factor, key="y"):
    if not isinstance(point, dict) or not _hulkify_is_number(point.get(key)):
        return 0
    point[key] = _hulkify_scale_absolute_height(point[key], datum, factor)
    return 1


def _hulkify_scale_brush(brush, center_x, center_z, factor):
    if not isinstance(brush, dict):
        return 0

    changed = _hulkify_scale_absolute_point(
        brush.get("position"),
        center_x,
        center_z,
        factor,
        "z",
    )

    scale = brush.get("scale")
    if isinstance(scale, dict):
        changed += _hulkify_scale_sizes(scale, factor, ("x", "z"))

    # Some older operations use radius rather than an X/Z scale dictionary.
    changed += _hulkify_scale_sizes(brush, factor, ("radius",))
    return changed


def _hulkify_scale_spline(
    spline,
    center_x,
    center_z,
    factor,
    second_key="z",
    elevation_datum=None,
    vertical_factor=1.0,
    vertical_key="y",
):
    if not isinstance(spline, dict):
        return 0

    changed = 0
    absolute_vertical = bool(spline.get("absoluteY"))
    for waypoint in spline.get("waypoints", []) or []:
        if not isinstance(waypoint, dict):
            continue
        for key in ("pointOne", "pointTwo", "waypoint"):
            point = waypoint.get(key)
            changed += _hulkify_scale_absolute_point(
                point,
                center_x,
                center_z,
                factor,
                second_key,
            )
            if (
                absolute_vertical and
                elevation_datum is not None and
                vertical_factor != 1.0 and
                vertical_key not in ("x", second_key)
            ):
                changed += _hulkify_scale_point_height(
                    point,
                    elevation_datum,
                    vertical_factor,
                    vertical_key,
                )
        changed += _hulkify_scale_sizes(
            waypoint,
            factor,
            ("width", "secondaryWidth"),
        )

    changed += _hulkify_scale_sizes(
        spline,
        factor,
        ("width", "secondaryWidth", "spacing"),
    )
    return changed


def _hulkify_scale_map_container(
    container,
    center_x,
    center_z,
    factor,
    second_key="z",
):
    """Scale map-edit containers, old brush lists, or spline lists."""
    if isinstance(container, list):
        changed = 0
        for item in container:
            changed += _hulkify_scale_map_container(
                item,
                center_x,
                center_z,
                factor,
                second_key,
            )
        return changed

    if not isinstance(container, dict):
        return 0

    if isinstance(container.get("position"), dict):
        return _hulkify_scale_brush(
            container,
            center_x,
            center_z,
            factor,
        )
    if isinstance(container.get("waypoints"), list):
        return _hulkify_scale_spline(
            container,
            center_x,
            center_z,
            factor,
            second_key,
        )

    changed = 0
    for brush in container.get("brushes", []) or []:
        changed += _hulkify_scale_brush(
            brush,
            center_x,
            center_z,
            factor,
        )
    for spline in container.get("splines", []) or []:
        changed += _hulkify_scale_spline(
            spline,
            center_x,
            center_z,
            factor,
            second_key,
        )
    return changed


def _hulkify_layer_json(course_json, course_version):
    if course_version == 25:
        return course_json
    if course_version == 23:
        return course_json["userLayers2"]
    return course_json["userLayers"]


def _hulkify_reference_points(course_json, course_version):
    """Return absolute X/Z points used to preserve the current course center."""
    layer_json = _hulkify_layer_json(course_json, course_version)
    points = []

    def add(point, second_key="z"):
        if not isinstance(point, dict):
            return
        if (
            _hulkify_is_number(point.get("x")) and
            _hulkify_is_number(point.get(second_key))
        ):
            points.append((float(point["x"]), float(point[second_key])))

    for key in ("height", "terrainHeight"):
        for brush in layer_json.get(key, []) or []:
            add(brush.get("position"))

    if points:
        return points

    hole_tag = tgc_definitions.version_tags[course_version]["holes"]
    tee_tag = tgc_definitions.version_tags[course_version]["tees"]
    for hole in course_json.get(hole_tag, []) or []:
        for waypoint in hole.get("waypoints", []) or []:
            add(waypoint)
        for tee in hole.get(tee_tag, []) or []:
            tee_position = tee
            if course_version == 25 and isinstance(tee, dict):
                tee_position = tee.get("position")
            add(tee_position)

    spline_tag = tgc_definitions.version_tags[course_version]["splines"]
    spline_second_key = "z" if course_version == 25 else "y"
    for spline in course_json.get(spline_tag, []) or []:
        for waypoint in spline.get("waypoints", []) or []:
            add(waypoint.get("waypoint"), spline_second_key)

    return points


def get_course_horizontal_bounds(course_json, course_version):
    if course_version not in tgc_definitions.version_tags:
        return None

    points = _hulkify_reference_points(course_json, course_version)
    if not points:
        return None

    xs = [point[0] for point in points]
    zs = [point[1] for point in points]
    min_x = min(xs)
    max_x = max(xs)
    min_z = min(zs)
    max_z = max(zs)
    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_z": min_z,
        "max_z": max_z,
        "width": max_x - min_x,
        "height": max_z - min_z,
        "center_x": 0.5 * (min_x + max_x),
        "center_z": 0.5 * (min_z + max_z),
    }


def get_course_vertical_relief_bounds(course_json, course_version):
    """Return absolute terrain-target bounds used for slope-locked scaling."""
    if course_version not in tgc_definitions.version_tags:
        return None

    layer_json = _hulkify_layer_json(course_json, course_version)
    absolute_values = []
    relative_values = []
    unknown_tools = set()

    for key in ("terrainHeight", "height"):
        for operation in layer_json.get(key, []) or []:
            if not isinstance(operation, dict):
                continue
            value = operation.get("value")
            if not _hulkify_is_number(value):
                continue
            tool = operation.get("tool", 0)
            try:
                tool = int(tool)
            except Exception:
                unknown_tools.add(str(tool))
                continue
            if tool == 0:
                absolute_values.append(float(value))
            elif tool == 1:
                relative_values.append(float(value))
            else:
                unknown_tools.add(str(tool))

    if not absolute_values:
        return {
            "datum": 0.0,
            "min": 0.0,
            "max": 0.0,
            "range": 0.0,
            "absolute_count": 0,
            "relative_count": len(relative_values),
            "unknown_tools": sorted(unknown_tools),
        }

    minimum = min(absolute_values)
    maximum = max(absolute_values)
    return {
        "datum": minimum,
        "min": minimum,
        "max": maximum,
        "range": maximum - minimum,
        "absolute_count": len(absolute_values),
        "relative_count": len(relative_values),
        "unknown_tools": sorted(unknown_tools),
    }


def _hulkify_scale_terrain_operation(operation, datum, vertical_factor):
    if not isinstance(operation, dict):
        return 0, None
    value = operation.get("value")
    if not _hulkify_is_number(value):
        return 0, None

    tool = operation.get("tool", 0)
    try:
        tool = int(tool)
    except Exception:
        return 0, str(tool)

    if tool == 0:
        operation["value"] = _hulkify_scale_absolute_height(
            value,
            datum,
            vertical_factor,
        )
        return 1, None
    if tool == 1:
        operation["value"] = float(value) * vertical_factor
        return 1, None
    return 0, str(tool)


def _hulkify_scale_water_height(water_brush, datum, vertical_factor):
    """Scale active native-water planes; retain zero-valued history/no-op rows."""
    if not isinstance(water_brush, dict):
        return 0

    position = water_brush.get("position")
    y_value = position.get("y") if isinstance(position, dict) else None
    brush_value = water_brush.get("value")
    numeric = [
        float(value)
        for value in (brush_value, y_value)
        if _hulkify_is_number(value)
    ]
    if not numeric:
        return 0

    # Finished 2K25 courses commonly retain zero-value water history entries.
    # Changing those zero rows can resurrect deleted/placeholder water planes.
    if all(abs(value) <= 1.0e-9 for value in numeric):
        return 0

    changed = 0
    if _hulkify_is_number(brush_value):
        water_brush["value"] = _hulkify_scale_absolute_height(
            brush_value,
            datum,
            vertical_factor,
        )
        changed += 1
    if isinstance(position, dict) and _hulkify_is_number(y_value):
        position["y"] = _hulkify_scale_absolute_height(
            y_value,
            datum,
            vertical_factor,
        )
        changed += 1
    return changed


# TGC_HULKIFY_10_PERCENT_V3
def scale_course_horizontal(
    course_json,
    factor=1.10,
    course_version=-1,
    printf=print,
    preserve_slopes=True,
):
    """Scale complete course geometry, slope-locking terrain by default.

    X/Z positions and horizontal footprints are multiplied by ``factor``.
    When ``preserve_slopes`` is true, absolute terrain targets are scaled about
    the lowest absolute terrain target and relative terrain edits are multiplied
    by the same factor.  Therefore both rise and run grow together and original
    slope percentages are retained.
    """
    if course_version not in tgc_definitions.version_tags:
        raise ValueError("Unsupported course version: " + str(course_version))

    try:
        factor = float(factor)
    except Exception as exc:
        raise ValueError("Horizontal scale factor must be numeric") from exc
    if not math.isfinite(factor) or factor <= 0.0:
        raise ValueError("Horizontal scale factor must be greater than zero")

    before = get_course_horizontal_bounds(course_json, course_version)
    if before is None:
        raise ValueError("Course contains no horizontal geometry to scale")

    relief_before = get_course_vertical_relief_bounds(
        course_json,
        course_version,
    )
    elevation_datum = float(relief_before["datum"])
    vertical_factor = factor if preserve_slopes else 1.0

    center_x = float(before["center_x"])
    center_z = float(before["center_z"])
    layer_json = _hulkify_layer_json(course_json, course_version)
    second_key = "z" if course_version == 25 else "y"
    changed = 0
    vertical_changed = 0
    unknown_tools = set(relief_before.get("unknown_tools", []))

    # Terrain operations: horizontal positions/footprints plus slope-locked
    # absolute/relative elevation values in their original operation order.
    for key in ("height", "terrainHeight"):
        for brush in layer_json.get(key, []) or []:
            changed += _hulkify_scale_brush(
                brush,
                center_x,
                center_z,
                factor,
            )
            if vertical_factor != 1.0:
                count, unknown = _hulkify_scale_terrain_operation(
                    brush,
                    elevation_datum,
                    vertical_factor,
                )
                vertical_changed += count
                if unknown is not None:
                    unknown_tools.add(unknown)

    surface_tag = tgc_definitions.version_tags[course_version]["surfaces"]
    if course_version == 25 and surface_tag not in course_json:
        surface_tag += "2"
    for brush in layer_json.get(surface_tag, []) or []:
        changed += _hulkify_scale_brush(
            brush,
            center_x,
            center_z,
            factor,
        )

    # Native water shares the same horizontal and vertical transform so the
    # terrain/water relationship and shoreline heights remain coherent.
    for water_brush in layer_json.get("water", []) or []:
        changed += _hulkify_scale_brush(
            water_brush,
            center_x,
            center_z,
            factor,
        )
        if vertical_factor != 1.0:
            vertical_changed += _hulkify_scale_water_height(
                water_brush,
                elevation_datum,
                vertical_factor,
            )

    # Legacy global water level is transformed only when it is non-zero/active;
    # zero is retained because it is normally a default/sentinel in 2K25 files.
    if (
        vertical_factor != 1.0 and
        _hulkify_is_number(course_json.get("waterLevel")) and
        abs(float(course_json.get("waterLevel"))) > 1.0e-9
    ):
        course_json["waterLevel"] = _hulkify_scale_absolute_height(
            course_json["waterLevel"],
            elevation_datum,
            vertical_factor,
        )
        vertical_changed += 1

    spline_tag = tgc_definitions.version_tags[course_version]["splines"]
    for spline in course_json.get(spline_tag, []) or []:
        changed += _hulkify_scale_spline(
            spline,
            center_x,
            center_z,
            factor,
            second_key,
            elevation_datum=(elevation_datum if course_version == 25 else None),
            vertical_factor=vertical_factor,
            vertical_key="y",
        )

    map_keys = (
        tgc_definitions.version_tags[course_version]["oob"],
        tgc_definitions.version_tags[course_version]["crowd"],
        "clearDetail",
        "clearTrees",
        "treeDensityMap",
        "costMap",
        "AllMapEdits",
    )
    processed = set()
    for key in map_keys:
        if key in processed:
            continue
        processed.add(key)
        if key in layer_json:
            changed += _hulkify_scale_map_container(
                layer_json.get(key),
                center_x,
                center_z,
                factor,
                second_key,
            )
        elif key in course_json:
            changed += _hulkify_scale_map_container(
                course_json.get(key),
                center_x,
                center_z,
                factor,
                second_key,
            )

    hole_tag = tgc_definitions.version_tags[course_version]["holes"]
    tee_tag = tgc_definitions.version_tags[course_version]["tees"]
    pin_tag = tgc_definitions.version_tags[course_version]["pins"]
    for hole in course_json.get(hole_tag, []) or []:
        for waypoint in hole.get("waypoints", []) or []:
            changed += _hulkify_scale_absolute_point(
                waypoint,
                center_x,
                center_z,
                factor,
                "z",
            )
        for tee in hole.get(tee_tag, []) or []:
            tee_position = tee
            if course_version == 25 and isinstance(tee, dict):
                tee_position = tee.get("position")
            changed += _hulkify_scale_absolute_point(
                tee_position,
                center_x,
                center_z,
                factor,
                "z",
            )
        for pin in hole.get(pin_tag, []) or []:
            pin_position = pin
            if course_version == 25 and isinstance(pin, dict):
                pin_position = pin.get("position")
            if isinstance(pin_position, dict):
                pin_second_key = "z" if "z" in pin_position else "y"
                changed += _hulkify_scale_relative_point(
                    pin_position,
                    factor,
                    pin_second_key,
                )
        if isinstance(hole.get("flagOffset"), dict):
            changed += _hulkify_scale_relative_point(
                hole["flagOffset"],
                factor,
                "y",
            )

    # Object locations move vertically with the transformed ground; their model
    # scales stay unchanged so trees/buildings do not become 10% taller/wider.
    object_tag = tgc_definitions.version_tags[course_version]["objects"]
    for object_group in course_json.get(object_tag, []) or []:
        if not isinstance(object_group, dict):
            continue
        value = object_group.get("Value", {})
        if not isinstance(value, dict):
            continue

        for key in ("items", "clusters"):
            for item in value.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                position = item.get("position")
                changed += _hulkify_scale_absolute_point(
                    position,
                    center_x,
                    center_z,
                    factor,
                    "z",
                )
                if vertical_factor != 1.0:
                    vertical_changed += _hulkify_scale_point_height(
                        position,
                        elevation_datum,
                        vertical_factor,
                        "y",
                    )

        for spline in value.get("splines", []) or []:
            changed += _hulkify_scale_spline(
                spline,
                center_x,
                center_z,
                factor,
                "z",
                elevation_datum=elevation_datum,
                vertical_factor=vertical_factor,
                vertical_key="y",
            )

        for key, paths in value.items():
            if not str(key).startswith("objectPaths") or not isinstance(paths, list):
                continue
            for path_record in paths:
                if not isinstance(path_record, dict):
                    continue
                path = path_record.get("path", path_record)
                changed += _hulkify_scale_spline(
                    path,
                    center_x,
                    center_z,
                    factor,
                    "z",
                    elevation_datum=elevation_datum,
                    vertical_factor=vertical_factor,
                    vertical_key="y",
                )
                changed += _hulkify_scale_sizes(
                    path_record,
                    factor,
                    ("spacing",),
                )

    for key in ("distanceMarkers", "walkingDestinations"):
        for record in course_json.get(key, []) or []:
            if not isinstance(record, dict):
                continue
            position = record.get("position") if isinstance(record.get("position"), dict) else record
            if isinstance(position, dict) and "x" in position and "z" in position:
                changed += _hulkify_scale_absolute_point(
                    position,
                    center_x,
                    center_z,
                    factor,
                    "z",
                )
                if vertical_factor != 1.0:
                    vertical_changed += _hulkify_scale_point_height(
                        position,
                        elevation_datum,
                        vertical_factor,
                        "y",
                    )

    marker = course_json.get("malificaHulkify")
    if not isinstance(marker, dict):
        marker = {}
        course_json["malificaHulkify"] = marker
    marker["version"] = 2
    marker["applicationCount"] = int(marker.get("applicationCount", 0) or 0) + 1
    marker["lastFactor"] = factor
    marker["combinedFactor"] = (
        float(marker.get("combinedFactor", 1.0) or 1.0) * factor
    )
    marker["center"] = {"x": center_x, "z": center_z}
    marker["verticalScale"] = vertical_factor
    marker["verticalDatum"] = elevation_datum
    marker["slopeLocked"] = bool(preserve_slopes)
    marker["objectModelScaleChanged"] = False
    marker["courseFinisherMetadataPresent"] = bool(
        course_json.get("malificaCourseFinisher")
    )

    after = get_course_horizontal_bounds(course_json, course_version)
    relief_after = get_course_vertical_relief_bounds(
        course_json,
        course_version,
    )
    printf(
        "Hulkify Course: horizontal factor=" + str(round(factor, 6)) +
        "; center=(" + str(round(center_x, 3)) + ", " +
        str(round(center_z, 3)) + ")"
    )
    printf(
        "Hulkify Course: reference span " +
        str(round(before["width"], 3)) + " x " +
        str(round(before["height"], 3)) + " m -> " +
        str(round(after["width"], 3)) + " x " +
        str(round(after["height"], 3)) + " m"
    )
    if preserve_slopes:
        printf(
            "Hulkify Course: slope lock active; terrain relief " +
            str(round(relief_before["range"], 3)) + " m -> " +
            str(round(relief_after["range"], 3)) +
            " m about datum " + str(round(elevation_datum, 3)) + " m."
        )
    if unknown_tools:
        printf(
            "Hulkify Course warning: unsupported terrain tool value(s) were "
            "left vertically unchanged: " + ", ".join(sorted(unknown_tools))
        )
    printf(
        "Hulkify Course: transformed horizontal values=" + str(changed) +
        "; transformed vertical values=" + str(vertical_changed) +
        "; placed-object model scales unchanged."
    )
    return course_json

# Helper function to rotate coordinates on many different element types
def rotateCoord(elem, x_key='x', y_key='y', c=1.0, s=0.0):
    x = elem[x_key]
    y = elem[y_key]
    elem[x_key] = x * c - y * s
    elem[y_key] = x * s + y * c

# Rotation angle is positive around the y-DOWN axis
# Positive values will rotate the course clockwise
def rotate_course(course_json, rotation_angle_radians, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    dim2 = 'y'
    if course_version == 25:
        layer_json = course_json
        dim2 = 'z'
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]
    
    hole_tag = tgc_definitions.version_tags[course_version]['holes']
    tee_tag = tgc_definitions.version_tags[course_version]['tees']
    pin_tag = tgc_definitions.version_tags[course_version]['pins']
    crowd_tag = tgc_definitions.version_tags[course_version]['crowd']    
    spline_tag = tgc_definitions.version_tags[course_version]['splines']
    surface_tag = tgc_definitions.version_tags[course_version]['surfaces']
    if course_version == 25 and surface_tag not in course_json:
        surface_tag += '2'
        
    oob_tag = tgc_definitions.version_tags[course_version]['oob']
    obj_tag = tgc_definitions.version_tags[course_version]['objects']

    # Elements that have rotation values are stored in degrees
    rotation_angle_degrees = 180.0 * rotation_angle_radians / math.pi

    # Pre calculate cosine and sine with what would be the y-up angle
    c = math.cos(-rotation_angle_radians)
    s = math.sin(-rotation_angle_radians)

    # Rotate Brushes
    oob_json = layer_json[oob_tag]
    crowd_json = layer_json[crowd_tag]
    if course_version == 25:
        oob_json = oob_json["brushes"]
        crowd_json = crowd_json["brushes"]
    for b in itertools.chain(layer_json["height"],
                             layer_json["terrainHeight"],
                             layer_json[surface_tag],
                             layer_json["water"],
                             oob_json,
                             crowd_json):
        try:
            rotateCoord(b['position'], 'x', 'z', c, s)
            b['rotation']['y'] += rotation_angle_degrees
        except:
            print(json.dumps(b))

    # Rotate splines
    for i in course_json[spline_tag]:
        for wp in i["waypoints"]:
            rotateCoord(wp["pointOne"], 'x', dim2, c, s)
            rotateCoord(wp["pointTwo"], 'x', dim2, c, s)
            rotateCoord(wp["waypoint"], 'x', dim2, c, s)

    # Rotate Holes
    for h in course_json[hole_tag]:
        for w in h["waypoints"]:
            rotateCoord(w, 'x', 'z', c, s)
        for t in h[tee_tag]:
            tp = t
            if course_version == 25:
                tp = tp["position"]
            rotateCoord(tp, 'x', 'z', c, s)
        for p in h[pin_tag]:
            # Todo not 100% sure that this is correct
            pp = p
            if course_version == 25:
                pp = p["position"]
            rotateCoord(pp, 'x', 'y', c, s)

    # Rotate Objects
    for o in course_json[obj_tag]:
        for i in o["Value"]["items"]:
            rotateCoord(i["position"], 'x', 'z', c, s)
            i['rotation']['y'] += rotation_angle_degrees

        for cl in o["Value"]["clusters"]:
            rotateCoord(cl["position"], 'x', 'z', c, s)
            cl['rotation']['y'] += rotation_angle_degrees

    return course_json

def getCoursePoints(course_json, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]

    cv2_pts = []

    for i in layer_json["height"]:
        cv2_pts.append([i["position"]["x"], i["position"]["z"]])

    for i in layer_json["terrainHeight"]:
        cv2_pts.append([i["position"]["x"], i["position"]["z"]])

    return cv2_pts

def getBoundingBox(course_json, course_version):
    cv2_pts = getCoursePoints(course_json, course_version)
    return cv2.boundingRect(np.array(cv2_pts).astype(np.int32))

def getMinBoundingBox(course_json, course_version):
    cv2_pts = getCoursePoints(course_json, course_version)
    return cv2.minAreaRect(np.array(cv2_pts).astype(np.int32))

def setValues(x, y, ll, ul, ur, lr):
    # r^2 > dist^2, so no need to do square root
    r2 = x**2 + y**2
    if x <= 0.0 and y <= 0.0:
        pdist2 = ll[0]**2 + ll[1]**2
        if r2 > pdist2:
            ll = (x, y, r2)
            return (ll, ul, ur, lr)
    elif x <= 0.0 and y >= 0.0:
        pdist2 = ul[0]**2 + ul[1]**2
        if r2 > pdist2:
            ul = (x, y, r2)
            return (ll, ul, ur, lr)
    elif x >= 0.0 and y >= 0.0:
        pdist2 = ur[0]**2 + ur[1]**2
        if r2 > pdist2:
            ur = (x, y, r2)
            return (ll, ul, ur, lr)
    elif x >= 0.0 and y <= 0.0:
        pdist2 = lr[0]**2 + lr[1]**2
        if r2 > pdist2:
            lr = (x, y, r2)
            return (ll, ul, ur, lr)
    return (ll, ul, ur, lr)

# Assuming terrain always goes further than "other stuff"
# Also assumes course is roughly centered at 0,0
# Returns ll, ul, ur, lr
def get_terrain_extremes(course_json, course_version):
    if course_version not in tgc_definitions.version_tags:
        return

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]

    # Initialize to higher/lower values than possible so the first points
    # X, Z, radius_squared to point
    ll = (0.0, 0.0, 0.0)
    ul = (0.0, 0.0, 0.0)
    ur = (0.0, 0.0, 0.0)
    lr = (0.0, 0.0, 0.0)

    for i in layer_json["height"]:
        ll, ul, ur, lr = setValues(i["position"]["x"], i["position"]["z"], ll, ul, ur, lr)

    for i in layer_json["terrainHeight"]:
        ll, ul, ur, lr = setValues(i["position"]["x"], i["position"]["z"], ll, ul, ur, lr)

    return (ll, ul, ur, lr)

# Determines the four extremes and tries to shift and rotate the course to fit within 2000m
def auto_position_course(course_json, printf=print, course_version=-1):
    # TODO Corners is redundant with the boundingRect
    extremes = get_terrain_extremes(course_json, course_version)
    rect = getBoundingBox(course_json, course_version)

    fits_on_map = False

    if -1000.0 <= rect[0] and \
       -1000.0 <= rect[1] and \
       rect[0] + rect[2] <= 1000.0 and \
       rect[1] + rect[3] <= 1000.0:
        fits_on_map = True

    if fits_on_map:
        printf("Course fits within map")

    # If course would fit within 2000x2000, don't try to rotate it
    rotation = 0.0
    if rect[2] > 2000.0 or rect[3] > 2000.0:
        # TODO try cv2.minarearect
        # It seems cool, but doesn't seem to outperform my algorithm

        # Otherwise, need to try to fit this course on the map
        # Rotate to try to maximize the extremes into the corners of the square
        # Can rotate a maximum of 45 degrees and all rotations are equivalent because bounded by a square
        ideal_angles = [-3.0/4.0*math.pi, 3.0/4.0*math.pi, 1.0/4.0*math.pi, -1.0/4.0*math.pi]
        rotation_sum = 0.0
        for c, a in zip(extremes, ideal_angles):
            angle = math.atan2(c[1], c[0])
            angle_diff = abs(a - angle)
            rotation_sum += abs(angle_diff)

        rotation = rotation_sum/float(len(extremes))
        printf("Rotating course by: " + str(rotation))
        course_json = rotate_course(course_json, rotation, course_version)

        # See if we needed to rotate the opposite direction
        rect = getBoundingBox(course_json, course_version)

        if rect[2] > 2000.0 or rect[3] > 2000.0:
            printf("Trying opposite rotation: " + str(-rotation))
            # Undo our previous rotation and try the other direction
            course_json = rotate_course(course_json, -2.0*rotation, course_version)

    # Now see if a translation can help get the full course on
    rect = getBoundingBox(course_json, course_version)

    eastwest_shift = -rect[2] / 2 - rect[0]
    northsouth_shift = -rect[3] / 2 - rect[1]

    printf("Shift course by: " + str(eastwest_shift) + " x " + str(northsouth_shift))

    return shift_course(course_json, eastwest_shift, northsouth_shift, course_version)

# This doesn't work perfectly, but it works for many courses
def auto_merge_courses(course1_json, course2_json):
    # Shift and rotate courses so that they don't overlap
    # Get bounding boxes for each course
    bb1 = getMinBoundingBox(course1_json)
    bb2 = getMinBoundingBox(course2_json)

    # Find which course is larger
    larger_course = course1_json
    smaller_course = course2_json
    if bb2[1][0] + bb2[1][1] > bb1[1][0] + bb1[1][1]:
        larger_course = course2_json
        smaller_course = course1_json

    # Fit the larger course section on any way we can
    larger_course = auto_position_course(larger_course)

    # Find enough space for the smaller course on the map
    bb1 = getMinBoundingBox(larger_course)
    bb2 = getMinBoundingBox(smaller_course)

    # Rotate smaller course to match larger course
    larger_horizontal_aligned = bb1[1][1] > bb1[1][0]
    smaller_horizontal_aligned = bb2[1][1] > bb2[1][0]
    rotation_angle = (bb1[2] - bb2[2])*math.pi/180.0
    if larger_horizontal_aligned == smaller_horizontal_aligned:
        rotation_angle += math.pi/2.0 # Rotate an extra 90 to align major distance
    rotate_course(smaller_course, rotation_angle)

    # Shift courses to not overlap
    bb1 = getMinBoundingBox(larger_course)
    bb2 = getMinBoundingBox(smaller_course)

    # Determine dominant angle for larger course
    # Needed because minAreaRect only reports -90 to 0.0
    rotation = 0.0
    radius = 0.0 # (h0/2 + gap + h1/2)
    orig_angle = math.pi/180.0*bb1[2]
    if bb1[1][0] > bb1[1][1]: # height > width
        radius = (bb1[1][0]/2.0 + 20 + bb2[1][0]/2.0)
        if orig_angle < -75:
            rotation = 0.0 # Shift straight right
        else:
            rotation = math.pi/4.0 # Shift at 45 degrees to upper right
    else:
        radius = (bb1[1][1]/2.0 + 20 + bb2[1][1]/2.0)
        if orig_angle < -75:
            rotation = math.pi/2.0 # Shift up
        else:
            rotation = 3.0*math.pi/4.0 # Shift at 45 degrees to upper left

    # x0 + radius * sin/cos(rotation)
    # Angles are -90 to 0.0, invert so courses shift up or to the right
    new_center_x = bb1[0][0] + radius*math.cos(rotation)
    new_center_y = bb1[0][1] + radius*math.sin(rotation)
    offset_x = new_center_x - bb2[0][0]
    offset_y = new_center_y - bb2[0][1]
    smaller_course = shift_course(smaller_course, offset_x, offset_y)

    # Apply usual merge
    merged_course = merge_courses(course1_json, course2_json)

    # Position this combined course as best as possible
    return auto_position_course(merged_course)

def merge_courses(course1_json, course2_json):
    for i in course2_json["userLayers"]["height"]:
        course1_json["userLayers"]["height"].append(i)

    for i in course2_json["userLayers"]["terrainHeight"]:
        course1_json["userLayers"]["terrainHeight"].append(i)

    for i in course2_json["surfaceSplines"]:
        course1_json["surfaceSplines"].append(i)

    for i in course2_json["userLayers"]["surfaces"]:
        course1_json["userLayers"]["surfaces"].append(i)

    for i in course2_json["userLayers"]["water"]:
        course1_json["userLayers"]["water"].append(i)

    for i in course2_json["userLayers"]["outOfBounds"]:
        course1_json["userLayers"]["outOfBounds"].append(i)

    for i in course2_json["userLayers"]["crowdLocations"]:
        course1_json["userLayers"]["crowdLocations"].append(i)

    for i in course2_json["placedObjects2"]:
        course1_json["placedObjects2"].append(i)

    print("Warning, holes may be out of order")
    for i in course2_json["holes"]:
        # Can only support 18 holes per course
        if len(course1_json["holes"]) < 18:
            course1_json["holes"].append(i)
        else:
            print("Too many holes")

    return course1_json


def elevate_terrain(course_json, elevate_shift, buffer_height=10.0, clip_lowest_value=-2.0, printf=print, course_version=-1):
    if course_version not in tgc_definitions.version_tags:
        print("invalid version")
        print(course_version)
        return None

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]
            
    # Automatic terrain shift
    if elevate_shift == 0.0 or elevate_shift == None:
        elevations = []
        for i in layer_json["height"]:
            elevations.append(i['value'])

        remaining_terrain = json.loads('[]')
        for i in layer_json["terrainHeight"]:
            elevations.append(i['value'])

        elevations = np.array(elevations)

        # Remove lower outliers
        # The idea is to sort the points by elevation
        # Then take the gradient (difference between each point)
        # Valid points will have many neighbors close in height to them
        s = np.sort(elevations)
        g = np.gradient(s)

        # Find the point in the curve where elevation stabilizes
        # Only need to look in the first half of the data.  Keep noisy positive elevation points
        # 0.05 is an approximate threshold.  Most data is less than 0.015 in elevation difference at the valid point
        half_length = round(len(elevations)/2)
        diff_threshold = (np.median(g[0:half_length]) + g[0:half_length].max(axis=0))/2.0
        diff_threshold = min(0.015, diff_threshold) # Don't set too low if course is very consistent
        try:
            split_index = np.where(g[0:half_length] > diff_threshold)[0][-1] # where returns a tuple of arrays?
            split_index += 1 # Move one past the last invalid point
       
            # The lowest valid point will be our new zero
            elevate_shift = -min(s[split_index:]) + buffer_height
        except IndexError:
            printf("Course likely does not need elevation adjustment")
            return course_json

    printf("Shifting elevation by: " + str(elevate_shift))

    remaining_height = json.loads('[]')
    for i in layer_json["height"]:
        value = i['value']
        if value + elevate_shift >= clip_lowest_value:
            i['value'] += elevate_shift
            remaining_height.append(i)
    layer_json["height"] = remaining_height

    remaining_terrain = json.loads('[]')
    for i in layer_json["terrainHeight"]:
        value = i['value']
        if value + elevate_shift >= clip_lowest_value:
            i['value'] += elevate_shift
            remaining_terrain.append(i)
    layer_json["terrainHeight"] = remaining_terrain

    return course_json

# Maximum course size is 2000 meters by 2000 meters.
# This crops if anything is further than max from the origin
# 2000.0 / 2 is 1000.0 meters
def crop_course(course_json, max_easting=1000.0, max_northing=1000.0, course_version=-1):
    if course_version not in tgc_definitions.version_tags:
        print("invalid version")
        print(course_version)
        return None

    if course_version == 25:
        layer_json = course_json
    elif course_version == 23:
        layer_json = course_json["userLayers2"]
    else:
        layer_json = course_json["userLayers"]
         
    spline_tag = tgc_definitions.version_tags[course_version]['splines']
    hole_tag = tgc_definitions.version_tags[course_version]['holes']
    tee_tag = tgc_definitions.version_tags[course_version]['tees']

    # Filter elevation
    remaining_height = json.loads('[]')
    for i in layer_json["height"]:
        if abs(i["position"]["x"]) <= max_easting and \
           abs(i["position"]["z"]) <= max_northing:
            remaining_height.append(i)
    layer_json["height"] = remaining_height

    remaining_terrain = json.loads('[]')
    for i in layer_json["terrainHeight"]:
        if abs(i["position"]["x"]) <= max_easting and \
           abs(i["position"]["z"]) <= max_northing:
            remaining_terrain.append(i)
    layer_json["terrainHeight"] = remaining_terrain

    # Filter splines
    remaining_splines = json.loads('[]')
    for i in course_json[spline_tag]:
        keep_spline = True
        for wp in i["waypoints"]:
            if abs(wp["pointOne"]["x"]) <= max_easting and \
               abs(wp["pointTwo"]["x"]) <= max_easting and \
               abs(wp["waypoint"]["x"]) <= max_easting and \
               abs(wp["pointOne"]["y"]) <= max_northing and \
               abs(wp["pointTwo"]["y"]) <= max_northing and \
               abs(wp["waypoint"]["y"]) <= max_northing:
               continue
            else:
                keep_spline = False
                break

        if keep_spline:
            remaining_splines.append(i)
    course_json[spline_tag] = remaining_splines

    # Filter Holes
    remaining_holes = json.loads('[]')
    for h in course_json[hole_tag]:
        keep_hole = True
        for w in h["waypoints"]:
            if abs(w["x"]) <= max_easting and \
               abs(w["z"]) <= max_northing:
               continue
            else:
                keep_hole = False
                break
 
        if keep_hole:
            for t in h[tee_tag]:
                if abs(t["x"]) <= max_easting and \
                   abs(t["z"]) <= max_northing:
                    continue
                else:
                    keep_hole = False
                    break

        if keep_hole:
            remaining_holes.append(h)
    course_json[hole_tag] = remaining_holes

    return course_json
