"""Add a theme's missing nature samples to an isolated 2K25 export copy.

The working course is never modified. There are no private markers in game JSON
and no ownership-based deletion: clean working data is the repeat-export boundary.
Native objects already present in an imported course are preserved and reused.
"""
from __future__ import annotations

import copy
from collections import Counter
import json
import math
from pathlib import Path
import re

import tree_profile_manager


EDGE_LIMIT_M = 980.0
GRID_PITCH_M = 4.0
PLAYABLE_CLEARANCE_M = 30.0
_MAX_LOCAL_COORDINATE_M = 1.0
_NON_PAINT_CATEGORIES = {5, 6, 11}
NATURE_ASSET_DIRECTORIES = {
    'tree': ('Trees',), 'shrub': ('Bushes',), 'grass': ('Grass',),
    'plant': ('Plants',), 'rock': ('Rocks', 'Rock'),
}


class FilterReadyError(ValueError):
    """The requested native sample collection cannot be safely exported."""


def is_nature_asset(asset):
    """Accept reviewed individual nature assets; old full catalogs stay safe.

    A category label alone cannot turn a prop or path generator into a nature
    sample. Missing or malformed eligible samples are still rejected by the
    native sample validator after filtering.
    """
    if not isinstance(asset, dict) or asset.get('placement') != 'item':
        return False
    category = asset.get('category')
    directories = NATURE_ASSET_DIRECTORIES.get(category, ()) if isinstance(category, str) else ()
    key = asset.get('key')
    path = key.get('path') if isinstance(key, dict) else None
    if (not directories or not isinstance(path, str) or
            not any(part in directories for part in path.split('/')[1:-1])):
        return False
    sample = asset.get('sample')
    return not (isinstance(sample, dict) and sample.get('isWater'))


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _point(value):
    if not isinstance(value, dict):
        return None
    x, z = _number(value.get('x')), _number(value.get('z'))
    return (x, z) if x is not None and z is not None else None


def _path_points(path):
    if not isinstance(path, dict):
        return []
    points = []
    for node in path.get('waypoints', []) or []:
        if not isinstance(node, dict):
            continue
        for key in ('pointOne', 'pointTwo', 'waypoint'):
            value = _point(node.get(key))
            if value is not None:
                points.append(value)
    return points


def _validate_asset(asset):
    if not isinstance(asset, dict):
        raise FilterReadyError('Filter Ready catalog contains an invalid asset entry.')
    key = asset.get('key')
    path = key.get('path') if isinstance(key, dict) else None
    if (not isinstance(path, str) or not path.startswith('Assets/') or
            '..' in path.split('/') or any(ord(c) < 32 for c in path)):
        raise FilterReadyError('Filter Ready catalog contains an invalid native asset path.')
    sample = asset.get('sample')
    if not isinstance(sample, dict):
        raise FilterReadyError('Filter Ready sample is missing for ' + path)
    placement = asset.get('placement')
    if placement == 'item':
        position = _point(sample.get('position'))
        if position is None or (sample.get('position') or {}).get('y') != '-Infinity':
            raise FilterReadyError('Filter Ready item must use native automatic terrain height: ' + path)
        if not isinstance(sample.get('scale'), dict) or not isinstance(sample.get('rotation'), dict):
            raise FilterReadyError('Filter Ready item needs a native scale and rotation: ' + path)
        for axis in ('x', 'y', 'z'):
            scale = _number((sample.get('scale') or {}).get(axis))
            rotation = _number((sample.get('rotation') or {}).get(axis))
            if scale is None or not 0.0 < scale <= 0.1 or rotation is None:
                raise FilterReadyError('Filter Ready item needs a small nonzero native scale: ' + path)
        points = [position]
    elif placement == 'object_path2':
        native_path = sample.get('path')
        points = _path_points(native_path)
        nodes = (native_path or {}).get('waypoints', []) if isinstance(native_path, dict) else []
        if len(nodes) < 2 or len(points) != 3 * len(nodes):
            raise FilterReadyError('Filter Ready path sample is incomplete: ' + path)
        if len(set(_point(node.get('waypoint')) for node in nodes)) < 2:
            raise FilterReadyError('Filter Ready path sample has no length: ' + path)
        width = _number(native_path.get('width'))
        if width is None or not 0.0 < width <= 1.0:
            raise FilterReadyError('Filter Ready path sample has an invalid width: ' + path)
        # Preserve the supplied native generator rules and Y/height relationship.
        # A water generator is a tiny native path, never a substituted prop item.
        if sample.get('isWater'):
            state = native_path.get('state')
            if state not in (0, 2, 3) or (state in (2, 3) and len(nodes) < 3):
                raise FilterReadyError('Filter Ready water path needs its native open or closed shape: ' + path)
    else:
        raise FilterReadyError('Filter Ready catalog has an unsupported placement for ' + path)
    if any(abs(v) > _MAX_LOCAL_COORDINATE_M for point in points for v in point):
        raise FilterReadyError('Filter Ready sample coordinates must stay local and compact: ' + path)
    return path


def _load_catalog(choice):
    profile = tree_profile_manager.get_profile(choice)
    if not profile:
        raise FilterReadyError('Choose a regional theme with a complete Filter Ready catalog.')
    profile_id = str(profile.get('id', ''))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', profile_id):
        raise FilterReadyError('The selected theme has an invalid catalog identifier.')
    selected = None
    # Match the profile manager: bundled, source, then the directory beside EXE.
    # A later invalid user override must not silently fall back to bundled data.
    for directory in tree_profile_manager._profile_directories():
        candidate = Path(directory) / 'filter_ready' / (profile_id + '.json')
        if candidate.exists():
            selected = candidate
    if selected is None:
        raise FilterReadyError('This theme does not yet have a complete Filter Ready asset catalog.')
    try:
        catalog = json.loads(selected.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise FilterReadyError('The Filter Ready catalog could not be read: ' + str(exc)) from exc
    if (not isinstance(catalog, dict) or catalog.get('schema_version') != 1 or
            catalog.get('profile_id') != profile_id or catalog.get('complete') is not True):
        raise FilterReadyError('The selected theme needs a complete matching Filter Ready catalog.')
    assets = catalog.get('assets')
    if not isinstance(assets, list) or not assets:
        raise FilterReadyError('The selected Filter Ready catalog has no asset samples.')
    nature_assets = [asset for asset in assets if is_nature_asset(asset)]
    if not nature_assets:
        raise FilterReadyError('The selected Filter Ready catalog has no eligible nature samples. '
                               'Choose a theme with trees, shrubs, grass, plants or rocks.')
    paths = [_validate_asset(asset) for asset in nature_assets]
    if len(paths) != len(set(paths)):
        raise FilterReadyError('The Filter Ready catalog contains duplicate native asset paths.')
    catalog = dict(catalog, assets=nature_assets, source_asset_count=len(assets),
                   omitted_asset_count=len(assets) - len(nature_assets),
                   counts={'assets': len(nature_assets),
                           'categories': dict(sorted(Counter(asset['category'] for asset in nature_assets).items())),
                           'placements': {'item': len(nature_assets)}})
    return profile, catalog


def catalog_status(choice, course_version=25):
    """Return availability for UI gating without modifying or loading a course."""
    if course_version != 25:
        return {'available': False, 'asset_count': 0,
                'message': 'Filter Ready requires a PGA TOUR 2K25 course.'}
    try:
        profile, catalog = _load_catalog(choice)
    except (FilterReadyError, OSError, ValueError, TypeError) as exc:
        return {'available': False, 'asset_count': 0, 'message': str(exc)}
    count = len(catalog['assets'])
    return {'available': True, 'asset_count': count, 'profile_id': profile['id'],
            'source_asset_count': catalog['source_asset_count'],
            'omitted_asset_count': catalog['omitted_asset_count'],
            'message': '%d nature asset types; missing trees, shrubs, grass, plants and rocks are placed once in an unused corner on export.' % count}


def _group_active(value):
    if not isinstance(value, dict):
        return False
    if any(isinstance(value.get(key), list) and value[key]
           for key in ('items', 'splines', 'objectPaths2')):
        return True
    return any(isinstance(cluster, dict) and (_number(cluster.get('count')) or 0) > 0
               for cluster in value.get('clusters', []) or [])


def _box(points, padding=0.0):
    if not points:
        return None
    return (min(p[0] for p in points) - padding, min(p[1] for p in points) - padding,
            max(p[0] for p in points) + padding, max(p[1] for p in points) + padding)


def _distance(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dz = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dz)


def _spline_box(spline):
    points = _path_points(spline)
    if not points:
        if isinstance(spline, dict) and spline.get('waypoints'):
            raise FilterReadyError('Filter Ready cannot locate an existing course spline. Check its coordinates or turn Filter Ready off.')
        return None
    widths = [max(0.0, _number(spline.get('width')) or 0.0),
              max(0.0, _number(spline.get('secondaryWidth')) or 0.0)]
    for node in spline.get('waypoints', []) or []:
        if isinstance(node, dict):
            widths.append(max(0.0, _number(node.get('width')) or 0.0))
    # Control-point bounding boxes enclose cubic Bezier curves; include widths.
    return _box(points, max(widths, default=0.0))


def _brush_box(brush):
    if not isinstance(brush, dict):
        return None
    point = _point(brush.get('position'))
    if point is None:
        raise FilterReadyError('Filter Ready cannot locate an existing surface or water brush. Check its coordinates or turn Filter Ready off.')
    scale = brush.get('scale') or {}
    rx, rz = _number(scale.get('x')), _number(scale.get('z'))
    if rx is None or rz is None:
        raise FilterReadyError('Filter Ready cannot determine an existing brush footprint. Turn Filter Ready off or repair the brush.')
    angle = math.radians(_number((brush.get('rotation') or {}).get('y')) or 0.0)
    rx, rz = abs(rx) / 2.0, abs(rz) / 2.0
    ex = abs(math.cos(angle)) * rx + abs(math.sin(angle)) * rz
    ez = abs(math.sin(angle)) * rx + abs(math.cos(angle)) * rz
    return (point[0] - ex, point[1] - ez, point[0] + ex, point[1] + ez)


def _obstacles(course):
    playable = []
    existing = []
    for key in ('surfaceSplines2', 'surfaceSplines'):
        for spline in course.get(key, []) or []:
            if not isinstance(spline, dict) or (_number(spline.get('opacity', 1)) or 0) <= 0:
                continue
            if spline.get('surface') in _NON_PAINT_CATEGORIES:
                continue
            bound = _spline_box(spline)
            if bound is not None:
                playable.append(bound)
    for key in ('surfaceBrushes2', 'surfaceBrushes', 'water'):
        for brush in course.get(key, []) or []:
            if not isinstance(brush, dict):
                continue
            # Water brush value is an elevation, so zero/negative water remains
            # an obstacle. Paint brushes with zero value are erase operations.
            if key != 'water' and ((_number(brush.get('value', 1)) or 0) <= 0 or
                                   brush.get('surfaceCategory') in _NON_PAINT_CATEGORIES):
                continue
            bound = _brush_box(brush)
            if bound is not None:
                playable.append(bound)
    for hole in course.get('holes3', []) or []:
        if not isinstance(hole, dict):
            continue
        route = [_point(p) for p in hole.get('waypoints', []) or []]
        if any(p is None for p in route):
            raise FilterReadyError('Filter Ready cannot locate a hole waypoint. Check the course layout or turn Filter Ready off.')
        for point in route:
            playable.append(_box([point], 20.0))
        for first, second in zip(route, route[1:]):
            playable.append(_box([first, second], 20.0))
        for tee in hole.get('tees', []) or []:
            point = _point(tee.get('position', tee)) if isinstance(tee, dict) else None
            if point is not None:
                playable.append(_box([point], 10.0))
        # Native 2K25 pin positions are offsets from the final hole waypoint.
        for pin in hole.get('pins', []) or []:
            offset = _point(pin.get('position', pin)) if isinstance(pin, dict) else None
            if offset is not None and route:
                playable.append(_box([(route[-1][0] + offset[0], route[-1][1] + offset[1])], 10.0))
    for group in course.get('placedObjects4', []) or []:
        if not isinstance(group, dict):
            continue
        value = group.get('Value') or {}
        if not isinstance(value, dict):
            continue
        for item in list(value.get('items', []) or []) + list(value.get('clusters', []) or []):
            if isinstance(item, dict):
                point = _point(item.get('position'))
                if point is not None:
                    existing.append(_box([point]))
        for generator in value.get('objectPaths2', []) or []:
            if not isinstance(generator, dict):
                continue
            bound = _spline_box(generator.get('path') or {})
            if bound is not None:
                (playable if generator.get('isWater') else existing).append(bound)
    return playable, existing


def _choose_corner(course, count):
    columns = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / float(columns)))
    width, depth = columns * GRID_PITCH_M, rows * GRID_PITCH_M
    if max(width, depth) >= EDGE_LIMIT_M:
        raise FilterReadyError('The Filter Ready catalog is too large for a compact corner collection.')
    playable, existing = _obstacles(course)
    candidates = [
        ('northwest', -EDGE_LIMIT_M, EDGE_LIMIT_M - depth),
        ('northeast', EDGE_LIMIT_M - width, EDGE_LIMIT_M - depth),
        ('southeast', EDGE_LIMIT_M - width, -EDGE_LIMIT_M),
        ('southwest', -EDGE_LIMIT_M, -EDGE_LIMIT_M),
    ]
    viable = []
    for name, x, z in candidates:
        bound = (x, z, x + width, z + depth)
        clearance = min((_distance(bound, obstacle) for obstacle in playable), default=2.0 * EDGE_LIMIT_M)
        if clearance < PLAYABLE_CLEARANCE_M:
            continue
        occupied = sum(_distance(bound, obstacle) == 0.0 for obstacle in existing)
        object_clearance = min((_distance(bound, obstacle) for obstacle in existing), default=2.0 * EDGE_LIMIT_M)
        # Keep the largest distance from play. Existing scenery is a tie breaker,
        # not a blanket ban that rejects every forested corner of a course.
        viable.append(((clearance, -occupied, object_clearance), name, x, z))
    if not viable:
        raise FilterReadyError(
            'Filter Ready could not find an unused corner with 30 m clearance from course features. '
            'Leave a clear corner inside the 2000 m plot, move the layout inward, or turn Filter Ready off.')
    _, name, x, z = max(viable, key=lambda candidate: candidate[0])
    return name, x, z, columns


def _translated_sample(asset, x, z):
    sample = copy.deepcopy(asset['sample'])
    if asset['placement'] == 'item':
        points = [sample['position']]
    else:
        points = [node[key] for node in sample['path']['waypoints']
                  for key in ('pointOne', 'pointTwo', 'waypoint')]
    for point in points:
        point['x'] = round(float(point['x']) + x, 6)
        point['z'] = round(float(point['z']) + z, 6)
    return sample


def apply_filter_ready(course_json, choice, enabled, course_version=25, printf=print):
    """Return a seed-only export copy when enabled; otherwise return input as-is.

    Always pass the clean working course. Re-imported native placements are
    preserved as ordinary user objects; this function never guesses ownership.
    Call only after course positioning/rotation/scaling have finished.
    """
    if not enabled:
        return course_json
    if course_version != 25:
        raise FilterReadyError('Filter Ready requires a PGA TOUR 2K25 course. Turn it off for this course format.')
    if not isinstance(course_json, dict):
        raise FilterReadyError('Filter Ready needs a valid course description.')
    profile, catalog = _load_catalog(choice)
    groups = course_json.get('placedObjects4', [])
    if groups is None:
        groups = []
    if not isinstance(groups, list):
        raise FilterReadyError('Filter Ready needs the native placedObjects4 list.')
    active = {group['Key']['path'] for group in groups
              if isinstance(group, dict) and isinstance(group.get('Key'), dict)
              and isinstance(group['Key'].get('path'), str) and _group_active(group.get('Value'))}
    missing = [asset for asset in catalog['assets'] if asset['key']['path'] not in active]
    if not missing:
        if printf:
            printf('Filter Ready: all %d nature asset types are already planted; no extra samples are needed.' % len(catalog['assets']))
        return copy.deepcopy(course_json)
    corner, x0, z0, columns = _choose_corner(course_json, len(missing))
    exported = copy.deepcopy(course_json)
    if exported.get('placedObjects4') is None:
        exported['placedObjects4'] = []
    output = exported.setdefault('placedObjects4', [])
    for index, asset in enumerate(missing):
        x = x0 + GRID_PITCH_M * (index % columns + 0.5)
        z = z0 + GRID_PITCH_M * (index // columns + 0.5)
        sample = _translated_sample(asset, x, z)
        # placedObjects4 serializes a native key/value collection. Reuse an
        # inactive exact-Key group rather than introduce a duplicate Key.
        # Existing duplicate groups are not deduplicated or otherwise changed.
        target = 'items'
        group = next((candidate for candidate in output
                      if isinstance(candidate, dict) and candidate.get('Key') == asset['key']
                      and not _group_active(candidate.get('Value'))), None)
        if group is None:
            value = {'items': [], 'clusters': [], 'splines': [], 'objectPaths2': [], 'IsEmpty': False}
            group = {'Key': copy.deepcopy(asset['key']), 'Value': value}
            output.append(group)
        else:
            value = group.get('Value')
            if not isinstance(value, dict) or (target in value and not isinstance(value[target], list)):
                raise FilterReadyError('Filter Ready found a malformed existing asset group. Repair its native placement list or turn Filter Ready off.')
        value.setdefault(target, []).append(sample)
        value['IsEmpty'] = False
    if printf:
        printf('Filter Ready: added %d missing nature samples in the %s corner for %s; %d nature asset types were already planted.' %
               (len(missing), corner, profile['display_name'], len(catalog['assets']) - len(missing)))
    return exported
