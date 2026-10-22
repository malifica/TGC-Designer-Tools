"""TGC_TREE_SURFACE_TOPOLOGY_V1: read-only LiDAR tree eligibility.

No terrain, spline, mask, tree model/scale or projection is modified. The
caller's final OSM projection is reused. Source rough is outer-minus-inner;
a rough region exempts a maintained surface ONLY when its complete outer
boundary is strictly inside that particular surface. The exception is local:
a separate green/bunker/tee covering that point still rejects the candidate.

TGC_TREE_SURFACE_NOTICE_DENY_V1: invalid OSM items become no-tree regions.
OSM tree-topology faults do not abort course generation.
Uses existing numpy/OpenCV dependencies. No shapely dependency is introduced.
"""
from collections import Counter, defaultdict
import math
import cv2
import numpy as np

MARKER = 'TGC_TREE_SURFACE_TOPOLOGY_V1'
NOTICE_MARKER = 'TGC_TREE_SURFACE_NOTICE_DENY_V1'
_MAINTAINED = {'green', 'tee', 'fairway', 'bunker'}
_ROUGH = {'rough', 'heavyrough'}
_SURFACE = {0: 'bunker', 1: 'green', 2: 'fairway', 3: 'rough', 4: 'heavyrough'}
# Bias uncertain shared edges toward rejection, not permission. This is NOT
# a tree-crown buffer: eligibility is evaluated at the tree's trunk/center.
_EDGE_EPS = 0.001


class Ring:
    def __init__(self, points):
        p = np.asarray(points, dtype=np.float64).reshape((-1, 2))
        if not np.isfinite(p).all():
            raise ValueError('non-finite polygon coordinates')
        if len(p) > 1:
            p = p[np.r_[True, np.any(np.diff(p, axis=0) != 0, axis=1)]]
        if len(p) > 1 and np.array_equal(p[0], p[-1]):
            p = p[:-1]
        if len(p) < 3:
            raise ValueError('polygon has fewer than three distinct vertices')
        self.p = p
        self.contour = p.astype(np.float32).reshape((-1, 1, 2))
        self.bbox = (*p.min(axis=0), *p.max(axis=0))
        self.area = abs(float(cv2.contourArea(self.contour)))
        if self.area <= 1e-8:
            raise ValueError('zero-area polygon')

    def hit(self, x, z, margin=0.0):
        a, b, c, d = self.bbox
        if x < a-margin or x > c+margin or z < b-margin or z > d+margin:
            return False
        return cv2.pointPolygonTest(self.contour, (float(x), float(z)), True) >= -margin


def _cross(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def _edges_cross(a, b, starts, ends):
    """Detect proper crossings or boundary touches (including collinear ones)."""
    ab = b-a
    cd = ends-starts
    s1 = _cross(ab, starts-a)
    s2 = _cross(ab, ends-a)
    s3 = _cross(cd, a-starts)
    s4 = _cross(cd, b-starts)
    eps = 1e-8
    overlap = ((np.maximum(a[0], b[0])+eps >= np.minimum(starts[:, 0], ends[:, 0])) &
               (np.minimum(a[0], b[0])-eps <= np.maximum(starts[:, 0], ends[:, 0])) &
               (np.maximum(a[1], b[1])+eps >= np.minimum(starts[:, 1], ends[:, 1])) &
               (np.minimum(a[1], b[1])-eps <= np.maximum(starts[:, 1], ends[:, 1])))
    return bool(np.any(overlap & (s1*s2 <= eps) & (s3*s4 <= eps)))


def strictly_inside(child, parent):
    """Full boundary containment, not just centroid/area/bounding-box guesses."""
    a, b, c, d = child.bbox
    A, B, C, D = parent.bbox
    if a <= A+_EDGE_EPS or b <= B+_EDGE_EPS or c >= C-_EDGE_EPS or d >= D-_EDGE_EPS:
        return False
    if child.area >= parent.area:
        return False
    if not all(parent.hit(x, z, -_EDGE_EPS) for x, z in child.p):
        return False
    ends = np.roll(parent.p, -1, axis=0)
    for i, p in enumerate(child.p):
        if _edges_cross(p, child.p[(i+1) % len(child.p)], parent.p, ends):
            return False
    return True


def simple_ring(ring):
    """Do not use a self-crossing rough outline to grant permission."""
    p = ring.p
    n = len(p)
    ends = np.roll(p, -1, axis=0)
    for i in range(n):
        ids = [j for j in range(i+2, n) if not (i == 0 and j == n-1)]
        if ids and _edges_cross(p[i], ends[i], p[ids], ends[ids]):
            return False
    return True


class Area:
    def __init__(self, kind, outer, holes=(), source='', margin=0.0):
        self.kind = kind
        self.outer = outer
        self.holes = list(holes)
        self.source = source
        self.margin = max(0.0, float(margin))
        self.islands = []

    def rough_at(self, x, z):
        # An inner ring's edge is not a rough-island permission.
        return (self.outer.hit(x, z, -_EDGE_EPS)
                and not any(h.hit(x, z, _EDGE_EPS) for h in self.holes))


class SurfaceFilter(dict):
    """Legacy region keys remain available; decisions use full topology."""
    def __init__(self, legacy, exclusions, warnings, global_denials=()):
        super().__init__(legacy)
        self.exclusions = exclusions
        self.warnings = warnings
        self.last_counts = {}
        self.global_denials = tuple(global_denials)
        self.quarantine = [a for a in exclusions if a.kind == 'ambiguous']

    def decision(self, x, z):
        if self.global_denials:
            return False, 'unresolved_osm', self.global_denials[0]
        # Invalid source regions override every island permission, regardless
        # of source order or another overlapping correctly tagged rough area.
        for area in self.quarantine:
            if area.outer.hit(x, z, area.margin):
                return False, 'ambiguous', area.source
        island = False
        for area in self.exclusions:
            if not area.outer.hit(x, z, area.margin):
                continue
            if area.kind != 'ambiguous' and any(r.rough_at(x, z) for r in area.islands):
                island = True
                continue
            return False, area.kind, area.source
        return True, 'rough_island' if island else 'outside_maintained', ''


def _tags(obj):
    return getattr(obj, 'tags', {}) or {}


def _kind(obj):
    return str(_tags(obj).get('golf', '')).strip().lower()


def _enabled(kind, options):
    if kind == 'tee':
        return bool(options.get('teebox', True))
    return bool(options.get(kind, True))


def _member_is_way(member):
    # Native overpy exposes _type_value. Fixture/adapter objects need not.
    value = getattr(member, '_type_value', None)
    return value == 'way' if value is not None else type(member).__name__ == 'RelationWay'


def _nodes(way):
    # Never silently retrieve different geometry over the network.
    return list(way.get_nodes(resolve_missing=False))


def _stitch(relation, lookup, role, warn):
    """Closed rings from unordered/reversed ways; never guess a closing edge."""
    fragments = []
    ok = True
    for m in getattr(relation, 'members', []):
        actual_role = str(getattr(m, 'role', '') or '').lower()
        if actual_role != role:
            continue
        if not _member_is_way(m):
            warn('relation %s: nested/non-way %s member is unsupported' % (relation.id, role))
            ok = False
            continue
        way = lookup.get(m.ref)
        try:
            ns = _nodes(way) if way is not None else []
            if len(ns) < 2:
                raise ValueError('missing way/nodes')
        except Exception:
            warn('relation %s: incomplete %s member %s' % (relation.id, role, m.ref))
            ok = False
            continue
        fragments.append(ns)
    rings = []
    while fragments:
        chain = fragments.pop(0)
        while chain[0].id != chain[-1].id:
            tail = chain[-1].id
            matches = [(i, ns[0].id == tail) for i, ns in enumerate(fragments)
                       if ns[0].id == tail or ns[-1].id == tail]
            if len(matches) != 1:
                warn('relation %s: open/branched %s ring; no island inferred' % (relation.id, role))
                ok = False
                break
            i, forward = matches[0]
            other = fragments.pop(i)
            chain.extend((other if forward else list(reversed(other)))[1:])
        if chain[0].id == chain[-1].id and len(chain) >= 4:
            rings.append(chain)
    return rings, ok


class SourceAreas(list):
    """List-compatible source geometry, with explicit global-deny diagnostics."""
    def __init__(self):
        super().__init__()
        self.global_denials = []


def source_areas(context, warn):
    result, pc, dx, dz, options = context
    ways = list(getattr(result, 'ways', []) or [])
    lookup = {w.id: w for w in ways}
    relations = list(getattr(result, 'relations', []) or [])
    consumed = set()
    areas = SourceAreas()

    def points(ns):
        output = []
        for node in ns:
            p = pc.latlonToTGC(node.lat, node.lon, dx, dz)
            x, z = float(p[0]), float(p[2])
            if not math.isfinite(x) or not math.isfinite(z):
                raise ValueError('non-finite projected coordinates')
            output.append((x, z))
        return output

    def ring(ns):
        return Ring(points(ns))

    def envelope(p):
        # This box is only a conservative no-tree area; it is never exported
        # as a surface or used to grant rough-island permission.
        arr = np.asarray(p, dtype=np.float64).reshape((-1, 2))
        if not len(arr) or not np.isfinite(arr).all():
            raise ValueError('no complete finite geometry')
        lo = arr.min(axis=0) - _EDGE_EPS
        hi = arr.max(axis=0) + _EDGE_EPS
        return Ring([(lo[0], lo[1]), (hi[0], lo[1]),
                     (hi[0], hi[1]), (lo[0], hi[1])])

    def deny_all(label, reason):
        message = label + ': ' + reason
        areas.global_denials.append(message)
        warn(message + '; complete affected bounds unavailable. '
             'ALL new LiDAR trees disabled for this import; course processing continues.')

    def quarantine(label, reason, outer_rings=None, outer_ways=None, exact=False):
        """Block an invalid item's full outer footprint, deliberately ignoring holes.

        Complete valid rings allow local exclusion. Open/branched or crossing
        geometry with ALL nodes present uses one enclosing box. Missing data
        without trustworthy bounds suppresses trees, not course generation.
        """
        blocked = []
        method = 'outer footprint(s)'
        if exact and outer_rings:
            try:
                blocked = [ring(ns) for ns in outer_rings]
                if not all(simple_ring(r) for r in blocked):
                    blocked = []
            except Exception:
                blocked = []
        if not blocked:
            try:
                if not outer_ways or any(w is None for w in outer_ways):
                    raise ValueError('outer member unavailable')
                p = []
                for w in outer_ways:
                    ns = _nodes(w)
                    if not ns:
                        raise ValueError('outer way has no nodes')
                    p.extend(points(ns))
                blocked = [envelope(p)]
                method = 'conservative exclusion envelope'
            except Exception:
                deny_all(label, reason)
                return
        for i, out in enumerate(blocked):
            areas.append(Area('ambiguous', out, source=label+' no-tree zone '+str(i+1),
                              margin=_EDGE_EPS))
        warn('%s: %s; trees disabled in %d %s, including any inner areas. '
             'No rough-island override for this item; course processing continues.' %
             (label, reason, len(blocked), method))

    for rel in relations:
        if str(_tags(rel).get('type', '')).lower() != 'multipolygon':
            continue
        members = list(getattr(rel, 'members', []) or [])
        kind = _kind(rel)
        if not kind:
            outer_kinds = {_kind(lookup.get(m.ref)) for m in members
                           if _member_is_way(m) and m.role == 'outer' and lookup.get(m.ref) is not None}
            outer_kinds.discard('')
            if len(outer_kinds) == 1:
                kind = next(iter(outer_kinds))
            elif len(outer_kinds) > 1:
                kind = ';'.join(sorted(outer_kinds))
        tokens = {p.strip() for p in kind.split(';') if p.strip()}
        ambiguous = len(tokens) > 1 and bool(tokens & (_MAINTAINED | _ROUGH))
        if kind not in _MAINTAINED | _ROUGH and not ambiguous:
            continue
        if not ambiguous and not _enabled(kind, options):
            continue
        label = 'OSM relation %s' % rel.id
        outer_ways = []
        for m in members:
            if str(getattr(m, 'role', '') or '').lower() != 'outer':
                continue
            outer_ways.append(lookup.get(m.ref) if _member_is_way(m) else None)
            if _member_is_way(m):
                consumed.add((m.ref, kind))
                if ambiguous:
                    consumed.update((m.ref, token) for token in tokens)
        try:
            ou, outer_ok = _stitch(rel, lookup, 'outer', warn)
            inn, inner_ok = _stitch(rel, lookup, 'inner', warn)
        except Exception as exc:
            quarantine(label, 'unreadable topology (%s: %s)' % (type(exc).__name__, str(exc)[:160]),
                       outer_ways=outer_ways)
            continue
        if ambiguous:
            quarantine(label, 'ambiguous golf=%s' % kind, ou, outer_ways, outer_ok)
            continue
        if not outer_ok or not ou:
            quarantine(label, 'incomplete outer topology', ou, outer_ways)
            continue
        if not inner_ok:
            quarantine(label, 'incomplete inner topology', ou, outer_ways, True)
            continue
        try:
            holes = [ring(ns) for ns in inn]
            outers = [ring(ns) for ns in ou]
            if not all(simple_ring(r) for r in outers + holes):
                raise ValueError('self-crossing boundary')
            # A complete rough component is required before granting permission.
            if kind in _ROUGH:
                for hole in holes:
                    if sum(strictly_inside(hole, out) for out in outers) != 1:
                        raise ValueError('rough inner ring is not inside exactly one outer')
        except Exception as exc:
            quarantine(label, 'unusable geometry (%s: %s)' %
                       (type(exc).__name__, str(exc)[:160]), ou, outer_ways, True)
            continue
        for i, out in enumerate(outers):
            areas.append(Area(kind, out, holes,
                              'OSM relation %s outer %d' % (rel.id, i+1)))

    for way in ways:
        kind = _kind(way)
        tokens = {p.strip() for p in kind.split(';') if p.strip()}
        ambiguous = len(tokens) > 1 and bool(tokens & (_MAINTAINED | _ROUGH))
        if kind not in _MAINTAINED | _ROUGH and not ambiguous:
            continue
        if (way.id, kind) in consumed or (not ambiguous and not _enabled(kind, options)):
            continue
        label = 'OSM way %s' % way.id
        try:
            ns = _nodes(way)
            closed = len(ns) >= 4 and ns[0].id == ns[-1].id
            if ambiguous:
                quarantine(label, 'ambiguous golf=%s' % kind,
                           [ns] if closed else [], [way], closed)
                continue
            if not closed:
                quarantine(label, 'open/incomplete area boundary', outer_ways=[way])
                continue
            r = ring(ns)
            if not simple_ring(r):
                quarantine(label, 'self-crossing area boundary', outer_ways=[way])
                continue
            areas.append(Area(kind, r, source=label))
        except Exception as exc:
            quarantine(label, 'unusable geometry (%s: %s)' %
                       (type(exc).__name__, str(exc)[:160]), outer_ways=[way])
    return areas

def build_filter(course_json, course_version, region_builder, printf=print, osm_context=None):
    import tgc_definitions
    if course_version not in tgc_definitions.version_tags:
        return None
    legacy = {k: [] for k in ('bunker', 'green_tee', 'fairway', 'rough')}
    native = []
    warnings = []

    def warn(text):
        warnings.append(text)
        printf('LiDAR tree topology NOTICE: ' + text)

    for i, s in enumerate(course_json.get(tgc_definitions.version_tags[course_version]['splines'], []) or []):
        if 'isFilled' in s:
            filled = bool(s['isFilled'])
        elif 'ClosedPath' in s:
            filled = bool(s['ClosedPath'])
        else:
            filled = s.get('state') == 3
        if not filled:
            continue
        try:
            kind = _SURFACE.get(int(s.get('surface', -999)))
        except (TypeError, ValueError):
            continue
        if kind is None:
            continue
        entry = region_builder(s, course_version)
        if entry is None:
            continue
        key = 'green_tee' if kind == 'green' else ('rough' if kind in _ROUGH else kind)
        legacy[key].append(entry)
        try:
            r = Ring(entry['contour'])
            native.append(Area(kind, r, source='native spline %d' % i, margin=entry['edge_margin']))
        except ValueError as exc:
            warn('native spline %d: %s' % (i, exc))
    exclusions = [a for a in native if a.kind in _MAINTAINED]
    global_denials = []
    if osm_context is not None:
        try:
            semantic = source_areas(osm_context, warn)
        except Exception as exc:
            # This catch is confined to the read-only tree-topology reader.
            # Never approve trees using partially failed source geometry.
            semantic = SourceAreas()
            message = 'unreadable OSM tree topology (%s: %s)' % (type(exc).__name__, str(exc)[:160])
            semantic.global_denials.append(message)
            warn(message + '; ALL new LiDAR trees disabled for this import; course processing continues.')
        global_denials = semantic.global_denials
        rough = [a for a in semantic if a.kind in _ROUGH]
        exclusions.extend(a for a in semantic if a.kind in _MAINTAINED or a.kind == 'ambiguous')
        mode = 'OSM outer-minus-inner + native Bezier boundaries'
    else:
        rough = [a for a in native if a.kind in _ROUGH and simple_ring(a.outer)]
        mode = 'native contained-rough islands'
    # Deliberately test full containment separately against EVERY maintained
    # region. A confirmed island in one region cannot overrule a second green.
    links = 0
    for a in exclusions:
        if a.kind == 'ambiguous':
            continue
        for r in rough:
            if strictly_inside(r.outer, a.outer):
                a.islands.append(r)
                links += 1
    printf('LiDAR tree topology: %s; %d maintained/ambiguous regions; %d rough areas; %d local island links.' %
           (mode, len(exclusions), len(rough), links))
    return SurfaceFilter(legacy, exclusions, warnings, global_denials)


def filter_candidates(lidar_trees, pc, surface_filter, printf=print):
    if surface_filter is None:
        printf('LiDAR tree playing-surface filter: no surface geometry available; candidates unchanged.')
        return list(lidar_trees)
    if not hasattr(surface_filter, 'decision'):
        printf('LiDAR tree topology NOTICE: incompatible tree surface filter; '
               'ALL new LiDAR trees disabled for this import; course processing continues.')
        return []
    kept = []
    counts = Counter()
    total = 0
    for tree in lidar_trees:
        total += 1
        try:
            e, n, radius, height = tree
            x, _, z = pc.projToTGC(float(e), float(n), 0.0)
            if not math.isfinite(x) or not math.isfinite(z):
                raise ValueError('non-finite candidate')
        except (TypeError, ValueError, OverflowError):
            counts['invalid_candidate'] += 1
            continue
        allowed, reason, source = surface_filter.decision(x, z)
        if allowed:
            kept.append(tree)
            counts['allowed_' + reason] += 1
        else:
            counts['rejected_' + reason] += 1
    surface_filter.last_counts = dict(counts)
    printf('LiDAR tree topology result: kept %d/%d; %s. Red-mask/proximity checks remain separate.' %
           (len(kept), total, ', '.join('%s=%d' % p for p in sorted(counts.items()))))
    return kept
