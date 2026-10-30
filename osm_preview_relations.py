"""Relation-aware OSM imagery, independent of the Auto Red Mask switch.

Only the feature overlay is drawn here. Red exclusion, crop bounds, coordinate
transforms, and terrain pixels outside features belong to their existing code.
The legacy way renderer is retained for non-relation features.
"""
import math
import cv2
import numpy as np


def _tags(obj):
    return getattr(obj, 'tags', {}) or {}


def _style(obj):
    t = _tags(obj)
    golf = t.get('golf')
    from OSMTGC import classifyDryAreaForTGC
    if classifyDryAreaForTGC(t):
        return 'mulch', (.75, .45, .30)
    if golf in ('water_hazard', 'lateral_water_hazard') or t.get('natural') == 'water' or t.get('waterway') is not None:
        return 'water', (0., 0., 1.)
    return {
        'rough': ('rough', (0., .55, .15)),
        'heavyrough': ('rough', (0., .55, .15)),
        'fairway': ('fairway', (0., .75, .20)),
        'driving_range': ('fairway', (0., .75, .20)),
        'tee': ('tee', (0., .8, 0.)),
        'green': ('green', (0., 1., .2)),
        'bunker': ('bunker', (.85, .85, .7)),
    }.get(golf, (None, None))


def _fragment(way, pc, scale, x_offset, y_offset):
    # Never fetch missing local nodes online or fabricate ring-closing chords.
    nodes = list(way.get_nodes(resolve_missing=False))
    if len(nodes) < 2:
        raise ValueError('fewer than two nodes')
    keys, pts = [], []
    for node in nodes:
        key = int(node.id)
        if keys and keys[-1] == key:
            continue
        row, col = pc.latlonToCV2(node.lat, node.lon, scale, x_offset, y_offset)
        if not math.isfinite(float(row)) or not math.isfinite(float(col)):
            raise ValueError('non-finite projected coordinate')
        keys.append(key)
        pts.append((float(col), float(row)))
    return {'keys': keys, 'pts': pts}


def render(osm_result, im, pc, image_scale, x_offset=0., y_offset=0.,
           printf=print, way_renderer=None):
    """Paint complete relation areas with true inner holes, then normal ways.

    Float RGB is the existing production format. uint8 is accepted as well.
    The call back into addOSMToImage receives a *list*, so no recursion occurs.
    """
    from auto_red_mask import _stitch_fragments, _rasterize_multipolygon
    if way_renderer is None:
        raise ValueError('The existing way renderer is required')
    scale = float(image_scale)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('OSM overlay image_scale must be positive and finite')
    if im.ndim != 3 or im.shape[2] < 3:
        raise ValueError('OSM overlay requires an RGB image')

    is_byte = not np.issubdtype(im.dtype, np.floating)
    # Run the legacy float renderer with precisely its original conventions.
    image = im.astype(np.float32) / 255. if is_byte else im
    ways = list(getattr(osm_result, 'ways', ()) or ())
    relations = list(getattr(osm_result, 'relations', ()) or ())
    lookup = {w.id: w for w in ways}
    contexts, areas = {}, []
    skipped = 0
    for rel in relations:
        if _tags(rel).get('type') != 'multipolygon':
            continue
        kind, color = _style(rel)
        if kind is None:
            continue
        outer, inner, errors = [], [], []
        for member in getattr(rel, 'members', ()):
            role = str(getattr(member, 'role', '') or '').strip().lower()
            if role not in ('', 'outer', 'inner'):
                continue
            # Relation node members (labels, etc.) are not polygon fragments.
            if member.__class__.__name__ == 'RelationNode':
                continue
            ref = getattr(member, 'ref', None)
            contexts.setdefault(ref, []).append((kind, role))
            way = lookup.get(ref)
            if way is None:
                errors.append('missing member way %s' % ref)
                continue
            try:
                fragment = _fragment(way, pc, scale, x_offset, y_offset)
                (inner if role == 'inner' else outer).append(fragment)
            except Exception as exc:
                errors.append('way %s: %s' % (ref, exc))
        outers, outer_bad = _stitch_fragments(outer)
        inners, inner_bad = _stitch_fragments(inner)
        if errors or outer_bad or inner_bad or not outers:
            skipped += 1
            printf('OSM preview: incomplete multipolygon %s skipped (no invented fill): %s; open rings=%d/%d' %
                   (getattr(rel, 'id', '?'), '; '.join(errors), outer_bad, inner_bad))
            continue
        areas.append((kind, color, outers, inners))

    # Suppress relation fragments, but retain independently tagged closed inner
    # features (e.g. a green/rough island inside a fairway).
    independent = []
    for way in ways:
        ctx = contexts.get(way.id)
        if not ctx:
            independent.append(way)
            continue
        kind, _ = _style(way)
        if kind is None or all(kind == rel_kind for rel_kind, _ in ctx):
            continue
        try:
            nodes = list(way.get_nodes(resolve_missing=False))
            is_line = _tags(way).get('waterway') is not None and _tags(way).get('area') != 'yes'
            if is_line or (len(nodes) >= 4 and nodes[0].id == nodes[-1].id):
                independent.append(way)
        except Exception:
            pass

    def paint(kinds):
        for kind in kinds:
            for actual, color, outers, inners in areas:
                if actual != kind:
                    continue
                # One mask at a time; a large OSM does not allocate N full grids.
                mask = _rasterize_multipolygon(outers, inners, image.shape[:2])
                image[mask != 0, :3] = color

    paint(('rough', 'mulch', 'fairway'))
    image = way_renderer(independent, image, pc, scale, x_offset=x_offset,
                         y_offset=y_offset, printf=printf)
    paint(('tee', 'green', 'bunker'))
    # Restore normal bunker layering above any relation putting surface.
    bunkers = [w for w in independent if _tags(w).get('golf') == 'bunker']
    if bunkers:
        image = way_renderer(bunkers, image, pc, scale, x_offset=x_offset,
                             y_offset=y_offset, printf=lambda *_: None)
    paint(('water',))
    water = [w for w in independent if _style(w)[0] == 'water']
    if water:
        image = way_renderer(water, image, pc, scale, x_offset=x_offset,
                             y_offset=y_offset, printf=lambda *_: None)
    if areas or skipped:
        printf('OSM relation overlay (independent of Auto Red Mask): %d complete, %d skipped; inner islands retained.' % (len(areas), skipped))
    if is_byte:
        im[...] = np.clip(np.rint(image * 255.), 0, 255).astype(im.dtype)
        return im
    return image
