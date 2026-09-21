import cv2
import itertools
import json
import math
import numpy as np
from scipy import ndimage
from pathlib import Path
import random
import sys
import time

import lidar_feature_filter

from GeoPointCloud import GeoPointCloud
from infill_image import infill_image_scipy
import OSMTGC
import cfs_georef
import tgc_definitions
import tgc_tools

status_print_duration = 1.0 # Print progress every n seconds

def get_pixel(x_pos, z_pos, height, scale, brush_type=72):
    output = json.loads('{"tool":0,"position":{"x":0.0,"y":"-Infinity","z":0.0},"rotation":{"x":0.0,"y":0.0,"z":0.0},"_orientation":0.0,"scale":{"x":1.0, \
                         "y":1.0,"z":1.0},"type":0,"value":0.0,"holeId":-1,"radius":0.0,"orientation":0.0}')
    output['type'] = brush_type
    output['position']['x'] = x_pos
    output['position']['z'] = z_pos
    output['value'] = height
    output['scale']['x'] = scale
    output['scale']['z'] = scale
    return output

def _normalize_background_heightmap(heightmap):
    arr = np.asarray(heightmap, dtype=np.float32)
    if arr.ndim > 2:
        arr = np.squeeze(arr)
    if arr.ndim != 2:
        raise ValueError(
            "Auto Background Landscape expected a 2-D heightmap; got " +
            str(arr.shape)
        )
    return arr


def _nearest_fill_invalid(arr):
    """Fill NaN/Inf holes with the nearest valid elevation for coarse background use."""
    valid = np.isfinite(arr)
    if not np.any(valid):
        return None

    if np.all(valid):
        return arr.astype(np.float32, copy=True)

    invalid = ~valid
    # For every invalid pixel, return indices of nearest valid pixel.
    _, indices = ndimage.distance_transform_edt(
        invalid,
        return_distances=True,
        return_indices=True,
    )
    filled = arr.copy()
    filled[invalid] = arr[tuple(indices[:, invalid])]
    return filled.astype(np.float32, copy=False)


def _sample_bilinear_2d(arr, row, col):
    h, w = arr.shape
    row = min(max(float(row), 0.0), h - 1.0)
    col = min(max(float(col), 0.0), w - 1.0)

    r0 = int(math.floor(row))
    c0 = int(math.floor(col))
    r1 = min(r0 + 1, h - 1)
    c1 = min(c0 + 1, w - 1)

    fr = row - r0
    fc = col - c0

    return float(
        arr[r0, c0] * (1.0 - fr) * (1.0 - fc) +
        arr[r0, c1] * (1.0 - fr) * fc +
        arr[r1, c0] * fr * (1.0 - fc) +
        arr[r1, c1] * fr * fc
    )


def generate_coarse_outside_landscape(
    heightmap,
    pc,
    image_scale,
    resolution_m=48.0,
    world_half_extent_m=1000.0,
    printf=print,
):
    """
    Build a low-resolution purple terrainHeight layer ONLY outside the
    detailed imported terrain rectangle.

    The coarse surface follows the DEM/LiDAR's large-scale relief.  Outside
    the source rectangle, each sample uses the nearest point on the source
    edge, so a site with 50+ m of relief keeps the correct low/high sides
    instead of being forced to one global elevation.
    """
    arr = _normalize_background_heightmap(heightmap)
    filled = _nearest_fill_invalid(arr)
    if filled is None:
        printf("Auto Background Landscape: no valid source elevations")
        return []

    try:
        resolution_m = float(resolution_m)
    except Exception:
        resolution_m = 48.0

    resolution_m = max(16.0, min(256.0, resolution_m))

    # Smooth at roughly half the requested coarse spacing.  This keeps the
    # purple layer broad and avoids reproducing small DEM bumps underneath.
    # Preserve more medium-scale relief than the original background pass.
    # The old 0.5x smoothing could wash out rolling/hilly terrain before the
    # purple landscape was stamped.
    sigma_px = max(
        0.75,
        (0.35 * resolution_m) / max(float(image_scale), 1e-6),
    )
    smoothed = ndimage.gaussian_filter(
        filled,
        sigma=sigma_px,
        mode="nearest",
    ).astype(np.float32)

    # Use a smaller Brush-10 footprint so the purple background tracks local
    # relief more faithfully and does not bridge across broad terrain changes.
    # 2.0x spacing still gives deliberate overlap with the soft Brush 10.
    brush_scale_m = 2.0 * resolution_m

    half_w = 0.5 * float(pc.width)
    half_h = 0.5 * float(pc.height)

    # Leave centers that are inside the detailed rectangle out of terrainHeight.
    # The soft outside stamps can overlap the edge slightly, and the detailed
    # sculpt layer is written separately above it.
    x_start = -float(world_half_extent_m) + 0.5 * resolution_m
    x_stop = float(world_half_extent_m) - 0.5 * resolution_m
    z_start = -float(world_half_extent_m) + 0.5 * resolution_m
    z_stop = float(world_half_extent_m) - 0.5 * resolution_m

    xs = np.arange(x_start, x_stop + 1e-6, resolution_m, dtype=np.float64)
    zs = np.arange(z_start, z_stop + 1e-6, resolution_m, dtype=np.float64)

    stamps = []
    min_value = float("inf")
    max_value = float("-inf")

    for z in zs:
        for x in xs:
            if (-half_w <= x <= half_w) and (-half_h <= z <= half_h):
                continue

            # Clamp the TGC position to the nearest point on the detailed
            # rectangle, then sample the smoothed source height there.
            edge_x = min(max(float(x), -half_w), half_w)
            edge_z = min(max(float(z), -half_h), half_h)

            enu_x = edge_x + half_w
            enu_y = edge_z + half_h

            col = enu_x / float(image_scale) - 0.5
            row = enu_y / float(image_scale) - 0.5

            value = _sample_bilinear_2d(smoothed, row, col)

            stamp = get_pixel(
                float(x),
                float(z),
                value,
                brush_scale_m,
                brush_type=10,
            )
            stamp["tool"] = 0
            stamp["rotation"]["y"] = 0.0
            stamps.append(stamp)

            min_value = min(min_value, value)
            max_value = max(max_value, value)

    printf(
        "Auto Background Landscape: generated " + str(len(stamps)) +
        " purple terrainHeight stamps; spacing=" +
        str(round(resolution_m, 2)) + " m, Brush10 scale=" +
        str(round(brush_scale_m, 2)) + " m"
    )

    if stamps:
        printf(
            "Auto Background Landscape: coarse elevation range " +
            str(round(min_value, 2)) + " .. " +
            str(round(max_value, 2)) + " m; source rectangle " +
            str(round(pc.width, 1)) + " x " +
            str(round(pc.height, 1)) + " m"
        )

    return stamps





def _cartpath_dim2(course_version):
    return "z" if course_version == 25 else "y"


def _is_linear_cartpath_spline(spline, course_version):
    try:
        width = float(spline.get("width", 0.0))
        surface = int(spline.get("surface", -1))
    except Exception:
        return False

    if width < 1.90:
        return False

    if bool(spline.get("isFilled", False)):
        return False

    if course_version == 25:
        expected_surface = tgc_definitions.featuresToSurfaces.get("surface1", 7)
    else:
        expected_surface = tgc_definitions.featuresToSurfaces.get("cartpath", 10)

    return surface == expected_surface


def _sample_source_height_tgc(heightmap, pc, image_scale, x, z):
    row, col = pc.tgcToCV2(float(x), float(z), float(image_scale))
    return _sample_bilinear_2d(heightmap, row, col)


def _spline_dense_polyline(spline, course_version, samples_per_segment=24):
    dim2 = _cartpath_dim2(course_version)
    waypoints = spline.get("waypoints", [])

    if len(waypoints) < 2:
        return []

    points = []

    for i in range(len(waypoints) - 1):
        a = waypoints[i]
        b = waypoints[i + 1]

        p0x = float(a["waypoint"]["x"])
        p0z = float(a["waypoint"][dim2])
        p1x = float(a["pointTwo"]["x"])
        p1z = float(a["pointTwo"][dim2])
        p2x = float(b["pointOne"]["x"])
        p2z = float(b["pointOne"][dim2])
        p3x = float(b["waypoint"]["x"])
        p3z = float(b["waypoint"][dim2])

        for j in range(samples_per_segment + 1):
            if i > 0 and j == 0:
                continue

            t = float(j) / float(samples_per_segment)
            u = 1.0 - t

            x = (
                (u ** 3) * p0x +
                3.0 * (u ** 2) * t * p1x +
                3.0 * u * (t ** 2) * p2x +
                (t ** 3) * p3x
            )
            z = (
                (u ** 3) * p0z +
                3.0 * (u ** 2) * t * p1z +
                3.0 * u * (t ** 2) * p2z +
                (t ** 3) * p3z
            )

            points.append((x, z))

    return points


def _prepare_polyline_arc(points):
    if len(points) < 2:
        return None, None, 0.0

    arr = np.asarray(points, dtype=np.float64)
    deltas = arr[1:] - arr[:-1]
    seg_lengths = np.sqrt(np.sum(deltas * deltas, axis=1))

    keep = np.concatenate(([True], seg_lengths > 1.0e-8))
    arr = arr[keep]

    if len(arr) < 2:
        return None, None, 0.0

    deltas = arr[1:] - arr[:-1]
    seg_lengths = np.sqrt(np.sum(deltas * deltas, axis=1))
    cumulative = np.concatenate(([0.0], np.cumsum(seg_lengths)))

    return arr, cumulative, float(cumulative[-1])


def _polyline_point_tangent(points, cumulative, distance):
    total = float(cumulative[-1])
    distance = min(max(float(distance), 0.0), total)

    index = int(np.searchsorted(cumulative, distance, side="right") - 1)
    index = min(max(index, 0), len(points) - 2)

    a = points[index]
    b = points[index + 1]

    seg_start = float(cumulative[index])
    seg_end = float(cumulative[index + 1])
    seg_len = max(seg_end - seg_start, 1.0e-9)

    t = (distance - seg_start) / seg_len
    point = a * (1.0 - t) + b * t

    tangent = b - a
    tangent_len = max(float(math.hypot(tangent[0], tangent[1])), 1.0e-9)
    tangent = tangent / tangent_len

    return (
        float(point[0]),
        float(point[1]),
        float(tangent[0]),
        float(tangent[1]),
    )


def generate_cartpath_flatten_stamps(
    course_json,
    heightmap,
    pc,
    image_scale,
    course_version,
    get_pixel_fn=get_pixel,
    printf=print,
):
    """TGC_AUTO_FLATTEN_CARTPATHS_V2: gentle centerline-anchored smoothing."""
    spline_tag = tgc_definitions.version_tags[course_version]["splines"]
    splines = course_json.get(spline_tag, [])
    source = _normalize_background_heightmap(heightmap)

    all_stamps = []
    path_count = 0
    skipped_area_count = 0
    total_length = 0.0
    max_abs_delta_seen = 0.0
    steep_guard_samples = 0

    for spline_index, spline in enumerate(splines):
        try:
            width = float(spline.get("width", 0.0))
            surface = int(spline.get("surface", -1))
        except Exception:
            continue

        if course_version == 25:
            expected_surface = tgc_definitions.featuresToSurfaces.get("surface1", 7)
        else:
            expected_surface = tgc_definitions.featuresToSurfaces.get("cartpath", 10)

        looks_cartpath_width = width >= 1.90 and surface == expected_surface
        if looks_cartpath_width and bool(spline.get("isFilled", False)):
            skipped_area_count += 1
            continue
        if not _is_linear_cartpath_spline(spline, course_version):
            continue

        dense = _spline_dense_polyline(spline, course_version, samples_per_segment=24)
        points, cumulative, path_length = _prepare_polyline_arc(dense)
        if points is None or path_length < 2.0:
            continue

        path_count += 1
        total_length += path_length

        # Mine Shaft manual work was dominated by soft Brush 10 strokes around
        # 3.3-4.0 m.  Keep the V1 width relationship but use a 3.4 m minimum.
        brush_scale = max(3.40, 1.40 * width)
        side_offset = max(1.50, 0.75 * width)
        profile_step = 0.5
        sample_distances = np.arange(0.0, path_length + 1.0e-6, profile_step, dtype=np.float64)
        if len(sample_distances) == 0 or sample_distances[-1] < path_length:
            sample_distances = np.append(sample_distances, path_length)

        center = np.zeros(len(sample_distances), dtype=np.float64)
        left = np.zeros(len(sample_distances), dtype=np.float64)
        right = np.zeros(len(sample_distances), dtype=np.float64)

        for i, distance in enumerate(sample_distances):
            x, z, tx, tz = _polyline_point_tangent(points, cumulative, distance)
            nx = -tz
            nz = tx
            center[i] = _sample_source_height_tgc(source, pc, image_scale, x, z)
            left[i] = _sample_source_height_tgc(source, pc, image_scale,
                                                x + nx * side_offset,
                                                z + nz * side_offset)
            right[i] = _sample_source_height_tgc(source, pc, image_scale,
                                                 x - nx * side_offset,
                                                 z - nz * side_offset)

        # Centerline grade is authoritative.  Only remove short-wavelength
        # chatter; never chase the lower shoulder as V1 did.
        sigma_samples = max(0.5, 1.5 / profile_step)
        smoothed_center = ndimage.gaussian_filter1d(center, sigma=sigma_samples, mode="nearest")

        # Hard invariant: an automatic target can never differ from the source
        # centerline by more than 20 cm.
        correction = np.clip(smoothed_center - center, -0.20, 0.20)
        target = center + correction

        endpoint_blend = 4.0
        for i, distance in enumerate(sample_distances):
            edge_distance = min(float(distance), path_length - float(distance))
            blend = min(1.0, max(0.0, edge_distance / endpoint_blend))
            blend = blend * blend * (3.0 - 2.0 * blend)
            target[i] = center[i] * (1.0 - blend) + target[i] * blend

        # Shoulder data is safety-only.  Steep banks cause a narrower brush,
        # but cannot change the path's target elevation.
        shoulder_delta = np.maximum(np.abs(left - center), np.abs(right - center))
        stamp_spacing = min(1.70, max(1.30, 0.45 * brush_scale))

        distance = 0.5 * stamp_spacing
        stamp_count = 0
        path_max_delta = 0.0
        while distance <= path_length - 0.5 * stamp_spacing + 1.0e-9:
            x, z, _, _ = _polyline_point_tangent(points, cumulative, distance)
            value = float(np.interp(distance, sample_distances, target))
            source_center = float(np.interp(distance, sample_distances, center))
            local_shoulder_delta = float(np.interp(distance, sample_distances, shoulder_delta))
            delta = value - source_center
            path_max_delta = max(path_max_delta, abs(delta))
            max_abs_delta_seen = max(max_abs_delta_seen, abs(delta))

            local_scale = brush_scale
            if local_shoulder_delta > 0.75:
                local_scale = max(2.80, 1.15 * width)
                steep_guard_samples += 1

            stamp = get_pixel_fn(x, z, value, local_scale, brush_type=10)
            stamp["rotation"]["y"] = 0.0
            all_stamps.append(stamp)
            stamp_count += 1
            distance += stamp_spacing

        printf("Auto Flatten Cartpath V2: spline " + str(spline_index) +
               ", width=" + str(round(width, 2)) + " m" +
               ", length=" + str(round(path_length, 1)) + " m" +
               ", Brush10 scale=" + str(round(brush_scale, 2)) + " m" +
               ", spacing=" + str(round(stamp_spacing, 2)) + " m" +
               ", max target delta=" + str(round(path_max_delta, 3)) + " m" +
               ", stamps=" + str(stamp_count))

    printf("Auto Flatten Cartpaths V2: processed " + str(path_count) +
           " linear cartpath spline(s), " + str(round(total_length, 1)) +
           " m total, generated " + str(len(all_stamps)) +
           " gentle Brush 10 terrain stamps; global max target delta=" +
           str(round(max_abs_delta_seen, 3)) +
           " m; steep-bank narrow-footprint samples=" + str(steep_guard_samples) + ".")

    if skipped_area_count:
        printf("Auto Flatten Cartpaths V2: skipped " + str(skipped_area_count) +
               " filled/area cartpath spline(s).")
    return all_stamps

def get_object_item(x_pos, z_pos, rotation_degrees):
    output = json.loads('{"position":{"x":0.0,"y":"-Infinity","z":0.0},"rotation":{"x":0.0,"y":0.0,"z":0.0},"scale":{"x":1.0,"y":1.0,"z":1.0}}')
    output['position']['x'] = x_pos
    output['position']['z'] = z_pos
    output['rotation']['y'] = rotation_degrees
    return output

def get_placed_object(course_version=-1):
    # TGC_LIDAR_TREE_2K25_FIX_V2
    key = '{"category":0,"type":0,"theme":true}'

    if course_version >= 25:
        # Native 2K25 / placedObjects4 structure.
        return json.loads(
            '{"Key":{"path":""},'
            '"Value":{"items":[],"clusters":[],"splines":[],"objectPaths2":[],"IsEmpty":false}}'
        )

    if course_version >= 23:
        key = '{"path":""}'

    return json.loads('{"Key":'+key+',"Value":{"items":[],"clusters":[]}}')


def get_trees(theme, tree_variety, trees, course_version=-1):
    # Get possible trees for this theme.  User can't easily change theme after this
    # But it's easy to rerun the import tool
    # Default to the default tree 0 if empty or not found
    if course_version >= 23:
        normal_tree_ids = tgc_definitions.normal_trees_2k.get(theme, [0])
        if len(normal_tree_ids) == 0:
            normal_tree_ids = [0]

        # 2K tree ids index a GLOBAL asset-path list.
        # With variety off, use the first tree from this theme's palette,
        # not global asset index 0.
        if not tree_variety:
            normal_tree_ids = [normal_tree_ids[0]]
    else:
        normal_tree_ids = tgc_definitions.normal_trees.get(theme, [0])
        # Legacy numeric type 0 remains theme-relative.
        if (not tree_variety) or len(normal_tree_ids) == 0:
            normal_tree_ids = [0]

    # Default to the normal trees if empty or not found
    if course_version >= 23:
        skinny_tree_ids = tgc_definitions.skinny_trees_2k.get(theme, normal_tree_ids)
    else:
        skinny_tree_ids = tgc_definitions.skinny_trees.get(theme, normal_tree_ids)

    if (not tree_variety) or len(skinny_tree_ids) == 0:
        skinny_tree_ids = []

    # Make an group for each type of tree, even if they may not be used
    normal_trees = []
    for tree_id in normal_tree_ids:
        p = get_placed_object(course_version)
        if course_version >= 23:
            p['Key']['path'] = tgc_definitions.trees_2k[tree_id]
        else:
            p['Key']['category'] = 0
            p['Key']['type'] = tree_id
        normal_trees.append(p)
    skinny_trees = []
    for tree_id in skinny_tree_ids:
        p = get_placed_object(course_version)
        if course_version >= 23:
            p['Key']['path'] = tgc_definitions.trees_2k[tree_id]
        else:
            p['Key']['category'] = 0
            p['Key']['type'] = tree_id
        skinny_trees.append(p)

    # Scale trees based on relative sizes
    min_radius_scale = 0.2
    radius_scale_range = 1.5 - min_radius_scale
    min_height_scale = 0.5
    height_scale_range = 1.2 - min_height_scale

    min_tree_radius = min(trees, key=lambda x: x[2])[2]
    max_tree_radius = max(trees, key=lambda x: x[2])[2]
    tree_radius_range = max_tree_radius - min_tree_radius
    if tree_radius_range > 0.01:
        radius_multiplier = radius_scale_range / tree_radius_range
    else:
        # All nearly same radius, scale to 1.0
        min_radius_scale = 1.0
        radius_multiplier = 0.0
    min_tree_height = min(trees, key=lambda x: x[3])[3]
    max_tree_height = max(trees, key=lambda x: x[3])[3]
    tree_height_range = max_tree_height - min_tree_height
    if tree_height_range > 0.01:
        height_multiplier = height_scale_range / tree_height_range
    else:
        # All nearly same height, scale to 1.0
        min_height_scale = 1.0
        height_multiplier = 0.0

    for tree in trees:
        easting, northing, r, h = tree
        t = get_object_item(easting, northing, random.randrange(0, 359))

        t['scale']['y'] = (h-min_tree_height)*height_multiplier + min_height_scale
        t['scale']['x'] = (r-min_tree_radius)*radius_multiplier + min_radius_scale
        t['scale']['z'] = (r-min_tree_radius)*radius_multiplier + min_radius_scale

        if h / r < 2.5 or len(skinny_trees) == 0: # Normal Tree
            group = random.choice(normal_trees)
        else: # Skinny tree
            group = random.choice(skinny_trees)
        group['Value']['items'].append(t)

    # Remove empty groups
    output = []
    for g in itertools.chain(normal_trees, skinny_trees):
        if len(g['Value']['items']) > 0:
            output.append(g)
    return output

def get_lidar_trees(theme, tree_variety, lidar_trees, pc, mask, mask_pc, image_scale, course_version=-1):
    # Convert to TGC coordinates
    trees = []
    for tree in lidar_trees:
        easting, northing, r, h = tree
        # Use mask to only add trees on desired areas
        row, column = mask_pc.projToCV2(easting, northing, image_scale)
        row = int(row)
        column = int(column)

        # Edge rounding can put candidates one pixel outside the cropped mask.
        if row < 0 or column < 0 or row >= mask.shape[0] or column >= mask.shape[1]:
            continue

        mask_color = mask[(row, column)]
        # Color order is BGR, support both MS Paint Red Colors
        if not (mask_color[0] < 40 and mask_color[1] < 40 and mask_color[2] > 130):
            # Use standard pointcloud tp project trees into final TGC coordinates
            x, y, z = pc.projToTGC(easting, northing, 0.0)
            trees.append((x, z, r, h))

    return get_trees(theme, tree_variety, trees, course_version)

# Set various constants that we need
def set_constants(course_json, flatten_fairways=False, flatten_greens=False, course_latitude=None, printf=print):
    # These only work if the terrain is made from scult (red brushes) rather than landscape (blue brushes)
    course_json["flattenFairways"] = flatten_fairways # Needed to not flatten under fairway splines
    course_json["flattenGreens"] = flatten_greens # Needed to not flatten under green splines

    # Slow down and soften greens a bit by default.   A lot of real world courses are not as firm as fast as TGC defaults
    course_json["greenSpeed"] = 0.136312455
    course_json["greenFirmness"] = 0.20308432

    # Set all hole sizes to 0.0 so that you can add holes without the autogenerated features appearing
    # This lets a designer manually specifcy or delete and readd a hole without the teebox, green, bunkers appearing over their OSM.
    course_json["roughRadius"] = 0.0
    course_json["heavyRoughRadius"] = 0.0
    course_json["fairwayRadius"] = 0.0
    course_json["greenRadius"] = 0.0
    course_json["teeRadius"] = 0.0
    course_json["hazardGreenCount"] = 0.0
    course_json["hazardFairwayCount"] = 0.0

    # Set lighting parameters based on the actual position of the course
    course_json["sunOrientation"] = 0.0 # Set so in game North aligns to true North
    course_json["sunInclination"] = 45.0 # Default halfway position
    # Try to set inclination based on latitude, if provided
    # Based on: http://www.physicalgeography.net/fundamentals/6h.html
    if course_latitude is not None:
        earth_declination = 23.5
        if course_latitude >= earth_declination: # Above the Tropic of Cancer, use June Solstice position
            course_json["sunInclination"] = 90.0 - float(course_latitude) + earth_declination
        elif course_latitude >= 0.0: # Equation to the Tropic of Cancer, use Equinox position
            course_json["sunInclination"] = 90.0 - float(course_latitude)
        elif course_latitude >= -1.0*earth_declination: # Equation to the Tropic of Capricorn, use Equinox position
            # You can't set above 90 in game, but we can here.  Do this so that North and Sunrise to the East are still correct.
            course_json["sunInclination"] = 90.0 - float(course_latitude)
        else: # Below the Tropic of Caprion.  Use December Solstice position
            # You can't set above 90 in game, but we can here.  Do this so that North and Sunrise to the East are still correct.
            course_json["sunInclination"] = 90.0 + -1.0*float(course_latitude) - earth_declination
        printf("For latitude " + str(course_latitude) + ": Setting sun angle to: " + str(course_json["sunInclination"]))

    # Add our own JSON element so the courses could be filtered easily
    # Am choosing an organization name so that TGC-Designer-Tools could be forked
    course_json["gis"] = "ChadRockeyDevelopment"

    return course_json

def generate_course(course_json, heightmap_dir_path, options_dict={}, printf=print, course_version=-1):
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

    obj_tag = tgc_definitions.version_tags[course_version]['objects']
    spline_tag = tgc_definitions.version_tags[course_version]['splines']
    printf("Loading data from " + heightmap_dir_path)

    # Infill data to prevent holes and make the data nice and smooth
    hm_file = Path(heightmap_dir_path) / '/heightmap.npy'
    try:
        read_dictionary = np.load(heightmap_dir_path + '/heightmap.npy', allow_pickle=True).item()
        im = read_dictionary['heightmap'].astype('float32')

        mask = cv2.imread(heightmap_dir_path + '/mask.png', cv2.IMREAD_COLOR)
        # Turn mask into matrix order from image order
        mask = np.flip(mask, 0)

        # Process Image
        printf("Filling holes in heightmap")
        image_scale = read_dictionary['image_scale']
        printf("Map scale is: " + str(image_scale) + " meters")
        background_ratio = None
        if options_dict.get('add_background', False):
            background_scale = float(options_dict.get('background_scale', 16.0))
            background_ratio = background_scale/image_scale
            printf("Background requested with scale: " + str(background_scale) + " meters")
            
        heightmap, background, holeMask = infill_image_scipy(im, mask, background_ratio=background_ratio, fill_water=options_dict.get('fill_water', False), purge_water=options_dict.get('purge_water', False), printf=printf)
    except FileNotFoundError:
        printf("Could not find heightmap or mask at: " + heightmap_dir_path)
        return course_json

    # Clear existing terrain
    course_json = set_constants(course_json, options_dict.get('flatten_fairways', False), options_dict.get('flatten_greens', False), read_dictionary['origin'][0], printf=printf)
    layer_json["height"] = []
    layer_json["terrainHeight"] = []
    course_json[obj_tag] = []

    # Construct high resolution model from the authoritative CFS-style
    # projected master affine. Legacy heightmaps are corrected for the
    # historical first-pixel-centre origin reconstruction bias.
    master_grid = cfs_georef.get_master_grid(
        read_dictionary,
        heightmap,
        printf=printf,
    )

    cfs_georef.validate_projection(
        read_dictionary['projection'],
        printf=printf,
    )

    cfs_georef.describe_master_grid(
        master_grid,
        printf=printf,
    )

    master_grid_origin = cfs_georef.master_grid_origin_latlon(master_grid)

    try:
        cfs_georef.write_master_grid_json(
            heightmap_dir_path,
            master_grid,
            filename="cfs_master_grid_used.json",
        )
    except Exception as exc:
        printf(
            "Warning: could not write CFS master-grid diagnostic: "
            + str(exc)
        )

    pc = GeoPointCloud()
    pc.addFromImage(
        heightmap,
        image_scale,
        master_grid_origin,
        read_dictionary['projection'],
    )

    # Add low resolution background
    if background is not None:
        background_pc = GeoPointCloud()
        background_pc.addFromImage(background, background_scale, master_grid_origin, read_dictionary['projection'])
        num_points = len(background_pc.points())
        last_print_time = time.time()

        for n, i in enumerate(background_pc.points()):
            if time.time() > last_print_time + status_print_duration:
                last_print_time = time.time()
                printf(str(round(100.0*float(n) / num_points, 2)) + "% through heightmap")

            # Convert to projected coordinates, then project to TGC using the high resolution pointcloud to ensure alignment
            easting, northing = background_pc.enuToProj(i[0], i[1])
            x, y, z = pc.projToTGC(easting, northing, 0.0)
            # Using 10 - the very soft circles means we need to scale 2.5x more to fill and smooth the terrain
            layer_json["height"].append(get_pixel(x, z, i[2], 2.5*background_scale, brush_type=10))

    # Convert the pointcloud into height elements.
    #
    # Integrated Adaptive generation has been retired.
    #
    # The heightmap.npy path now always uses the proven Dense / Original
    # source-lattice conversion. The standalone finished-course Adaptive
    # converter remains a separate workflow and is not changed by this patch.
    printf("Generating terrain with Dense / Original stamping")

    num_points = len(pc.points())
    last_print_time = time.time()

    try:
        terrain_brush_type = int(
            options_dict.get(
                'brush_type',
                72,
            )
        )
    except Exception:
        terrain_brush_type = 72

    if terrain_brush_type not in (
        72,
        9,
        10,
        15,
    ):
        printf(
            "Invalid terrain brush type "
            + str(terrain_brush_type)
            + "; using 72."
        )
        terrain_brush_type = 72

    configured_sizes = [
        1.0,
        2.0,
        3.0,
        4.0,
        6.0,
    ]

    try:
        requested_brush_scale = float(
            options_dict.get(
                'brush_scale',
                image_scale,
            )
        )
    except Exception:
        requested_brush_scale = image_scale

    valid_sizes = [
        value
        for value in configured_sizes
        if value + 1e-6 >= image_scale
    ]

    if not valid_sizes:
        printf(
            "ERROR: Lidar/DEM sample spacing "
            + str(image_scale)
            + " m exceeds the maximum configured 6 m brush footprint."
        )
        return course_json

    if (
        requested_brush_scale not in configured_sizes
        or requested_brush_scale + 1e-6 < image_scale
    ):
        requested_brush_scale = valid_sizes[0]

    for n, point in enumerate(
        pc.points()
    ):
        if (
            time.time()
            > last_print_time
            + status_print_duration
        ):
            last_print_time = time.time()

            printf(
                str(
                    round(
                        100.0
                        * float(n)
                        / num_points,
                        2,
                    )
                )
                + "% through heightmap"
            )

        x, y, z = pc.enuToTGC(
            point[0],
            point[1],
            0.0,
        )

        layer_json["height"].append(
            get_pixel(
                x,
                z,
                point[2],
                requested_brush_scale,
                brush_type=terrain_brush_type,
            )
        )

    # Optional QOL: after blue-mask terrain has been purged, lay a sparse,
    # a rounded bank instead of an abrupt vertical/no-terrain edge.

    # QOL: create a coarse DEM-following purple landscape outside the imported
    # detailed terrain instead of using one flat global elevation.
    if options_dict.get('auto_background_landscape', False):
        try:
            outside_background_resolution = float(
                options_dict.get('outside_background_resolution', 48.0)
            )
        except Exception:
            outside_background_resolution = 64.0

        layer_json["terrainHeight"] = generate_coarse_outside_landscape(
            heightmap,
            pc,
            image_scale,
            resolution_m=outside_background_resolution,
            world_half_extent_m=1000.0,
            printf=printf,
        )

    # Adaptive terrain is designed around 2K25 high-resolution bunker behavior.
    # Preserve current-format bunker settings and enable high-res stamping when present.
    if course_version >= 25:
        try:
            if "bunkerSettings2" in course_json and isinstance(course_json["bunkerSettings2"], dict):
                course_json["bunkerSettings2"]["highResStamping"] = True
        except Exception as exc:
            printf("Warning: could not force high-resolution bunker stamping: " + str(exc))

    # LiDAR candidates are deferred until course features exist.
    # This lets the optional 50 m filters use actual imported OSM/course
    # splines after CFS alignment/manual nudge has already been applied.
    lidar_tree_candidates = list(
        read_dictionary.get('trees', []) or []
    )

    lidar_building_candidates = list(
        read_dictionary.get('buildings', []) or []
    )

    printf(
        "LiDAR tree candidates stored in heightmap: "
        + str(len(lidar_tree_candidates))
    )

    printf(
        "LiDAR building candidates stored in heightmap: "
        + str(len(lidar_building_candidates))
    )

    # Download OpenStreetMaps Data for this smaller area
    if options_dict.get('use_osm', True):
        printf("Adding golf features to lidar data")

        # Get spline configuration file, if present
        spline_json = tgc_tools.get_spline_configuration_json(heightmap_dir_path)

        local_osm_file = str(options_dict.get('local_osm_file', '') or '').strip()
        local_osm_mode = bool(local_osm_file)
        result = None

        if local_osm_mode:
            printf("Local OSM mode: " + local_osm_file)
            try:
                with open(local_osm_file, 'r', encoding='utf-8-sig') as osm_input:
                    result = OSMTGC.parseOSMData(osm_input.read(), printf=printf)
            except OSError as exc:
                printf("Could not open local OpenStreetMap file: " + str(exc))
        else:
            upper_left_enu = pc.ulENU()
            lower_right_enu = pc.lrENU()
            upper_left_latlon = pc.enuToLatLon(*upper_left_enu)
            lower_right_latlon = pc.enuToLatLon(*lower_right_enu)
            result = OSMTGC.getOSMData(lower_right_latlon[0], upper_left_latlon[1], upper_left_latlon[0], lower_right_latlon[1], printf=printf)

        if result is None:
            printf("No OpenStreetMap data available; skipping OSM feature import.")
            osm_trees = []
        else:
            # CFS GeoReference Lock:
            # OSM source coordinates are WGS84 lon/lat (EPSG:4326).
            # The terrain HORIZONTAL projected CRS + saved master affine own
            # placement. No bunker/terrain-edge heuristic shift is used.
            manual_osm_ew = float(options_dict.get('adjust_ew', 0.0))
            manual_osm_ns = float(options_dict.get('adjust_ns', 0.0))

            final_osm_ew = manual_osm_ew
            final_osm_ns = manual_osm_ns

            printf(
                "CFS GeoReference Lock: exact CRS/grid placement active; "
                "heuristic OSM auto-alignment disabled."
            )
            printf(
                "Manual post-georeference OSM nudge: E/W "
                + str(round(final_osm_ew, 2))
                + " m, N/S "
                + str(round(final_osm_ns, 2))
                + " m"
            )

            osm_trees = OSMTGC.addOSMToTGC(
                course_json,
                pc,
                result,
                x_offset=final_osm_ew,
                y_offset=final_osm_ns,
                options_dict=options_dict,
                spline_configuration_json=spline_json,
                printf=printf,
                course_version=course_version,
                resolve_missing_nodes=not local_osm_mode
            )

        if len(osm_trees) > 0:
            printf("Adding trees from OpenStreetMap")
            for o in get_trees(course_json['theme'], options_dict.get('tree_variety', False), osm_trees, course_version):
                course_json[obj_tag].append(o)

        if (
            options_dict.get('cartpath', True) and
            options_dict.get('auto_flatten_cartpaths', False)
        ):
            printf("Auto Flatten Cartpaths: applying full-path flatten pass")
            cartpath_flatten_stamps = generate_cartpath_flatten_stamps(
                course_json,
                heightmap,
                pc,
                image_scale,
                course_version,
                get_pixel_fn=get_pixel,
                printf=printf,
            )
            layer_json["height"].extend(cartpath_flatten_stamps)

    # LiDAR object proximity filtering runs after OSM/course feature import.
    # The generated course features therefore define "immediate course" and
    # already include the final CFS OSM nudge.
    need_feature_filter = bool(
        options_dict.get('filter_lidar_trees_50m', False)
        or options_dict.get('filter_lidar_buildings_50m', False)
    )

    course_feature_tree = None

    if need_feature_filter:
        course_feature_tree = lidar_feature_filter.build_course_feature_index(
            course_json,
            course_version,
            printf=printf,
        )

    if options_dict.get('lidar_trees', False):
        tree_candidates = lidar_tree_candidates

        if options_dict.get('filter_lidar_trees_50m', False):
            tree_candidates = lidar_feature_filter.filter_lidar_tree_candidates(
                tree_candidates,
                pc,
                course_feature_tree,
                max_distance_m=50.0,
                printf=printf,
            )

        if len(tree_candidates) > 0:
            printf("Adding trees from LiDAR candidates")

            mask_pc = GeoPointCloud()
            mask_pc.addFromImage(
                im,
                image_scale,
                master_grid_origin,
                read_dictionary['projection'],
            )

            lidar_tree_groups = get_lidar_trees(
                course_json['theme'],
                options_dict.get('tree_variety', False),
                tree_candidates,
                pc,
                mask,
                mask_pc,
                image_scale,
                course_version,
            )

            lidar_tree_items = sum(
                len(group.get("Value", {}).get("items", []))
                for group in lidar_tree_groups
            )

            printf(
                "LiDAR trees written to "
                + str(obj_tag)
                + ": "
                + str(lidar_tree_items)
            )

            for group in lidar_tree_groups:
                course_json[obj_tag].append(group)
        else:
            printf(
                "No LiDAR tree candidates survived the selected filters."
            )

    if options_dict.get('lidar_buildings', False):
        building_splines = lidar_feature_filter.lidar_building_splines(
            lidar_building_candidates,
            pc,
            course_feature_tree,
            max_distance_m=50.0,
            apply_filter=bool(
                options_dict.get(
                    'filter_lidar_buildings_50m',
                    False,
                )
            ),
            new_building_func=OSMTGC.newBuilding,
            course_version=course_version,
            printf=printf,
        )

        for spline in building_splines:
            course_json[spline_tag].append(spline)

        if len(lidar_building_candidates) == 0:
            printf(
                "No LiDAR building footprints are stored in this heightmap. "
                "Re-run Process LiDAR after installing this patch to detect "
                "LAS classification-6 buildings."
            )

    # Automatically adjust course elevation
    printf("Moving course to lowest valid elevation")
    course_json = tgc_tools.elevate_terrain(course_json, None, printf=printf, course_version=course_version)

    printf("Course Description Complete")

    return course_json

def generate_flat_course(course_json, xml_data, options_dict={}, printf=print, course_version=-1):
    course_json, osm_trees = OSMTGC.addOSMFromXML(course_json, xml_data, options_dict=options_dict, printf=printf,
        course_version=course_version)
    if course_version not in tgc_definitions.version_tags:
        print("invalid version")
        print(course_version)
        return

    obj_tag = tgc_definitions.version_tags[course_version]['objects']

    if len(osm_trees) > 0:
        printf("Adding trees from OpenStreetMap")
        for o in get_trees(course_json['theme'], options_dict.get('tree_variety', False), osm_trees, course_version):
            course_json[obj_tag].append(o)

    return course_json

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python program.py COURSE_DIRECTORY HEIGHTMAP_DIRECTORY")
        sys.exit(0)
    else:
        course_dir_path = sys.argv[1]
        heightmap_dir_path = sys.argv[2]

    print("Getting course description")
    course_json = tgc_tools.get_course_json(course_dir_path)

    print("Generating course")
    course_json = generate_course(course_json, heightmap_dir_path)

    print("Saving new course description")
    tgc_tools.write_course_json(course_dir_path, course_json)
