"""Same-surface cutouts for course splines and terrain masks.

Ownership is established by explicit multipolygon membership (including an
inner boundary that is also a same-kind relation's outer). Nearby features
alone never establish ownership. The input Overpy result is not mutated.
"""
from collections import defaultdict, namedtuple

import overpy
from shapely.geometry import Polygon
from shapely.ops import nearest_points
from shapely.geometry import LineString

Ring = namedtuple("Ring", "refs nodes")
Plan = namedtuple("Plan", "kind outers holes")
Ownership = namedtuple("Ownership", "plans kinds blocked_ways drop_relations omit_outer open_inner errors")


def surface_kind(tags):
    tags = tags or {}
    golf = tags.get("golf")
    if golf == "rough":
        return "rough"
    if golf in ("water_hazard", "lateral_water_hazard"):
        return "water"
    if not golf and (tags.get("natural") == "water" or tags.get("landuse") == "reservoir"
                     or tags.get("water") not in (None, "", "no")):
        return "water"
    return None


def role(member):
    return str(getattr(member, "role", "") or "").strip().lower() or "outer"


def _way_refs(rel, which):
    return [m.ref for m in rel.members if isinstance(m, overpy.RelationWay) and role(m) == which]


def _stitch(refs, lookup, resolve):
    """Retain source way IDs alongside each ring; never close an open chain."""
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate boundary member")
    completed, chains, ends = [], {}, defaultdict(list)
    for ref in refs:
        w = lookup.get(ref)
        if w is None:
            raise ValueError("missing boundary way %s" % ref)
        pts = list(w.get_nodes(resolve_missing=resolve))
        if len(pts) < 2:
            raise ValueError("empty or degenerate boundary way %s" % ref)
        if pts[0].id == pts[-1].id:
            if len({n.id for n in pts}) < 3:
                raise ValueError("degenerate closed boundary way %s" % ref)
            completed.append(Ring(frozenset([ref]), pts[:-1]))
        else:
            chains[ref] = pts
            ends[pts[0].id].append(ref); ends[pts[-1].id].append(ref)
    if any(len(v) != 2 for v in ends.values()):
        raise ValueError("open or branching boundary fragments")
    while chains:
        first = next(iter(chains))
        pts = list(chains.pop(first)); used = {first}
        while pts[-1].id != pts[0].id:
            candidates = [i for i in ends[pts[-1].id] if i in chains]
            if len(candidates) != 1:
                raise ValueError("ambiguous boundary fragments")
            ref = candidates[0]; part = chains.pop(ref); used.add(ref)
            pts.extend(part[1:] if part[0].id == pts[-1].id else part[-2::-1])
        if len({n.id for n in pts}) < 3:
            raise ValueError("degenerate stitched ring")
        completed.append(Ring(frozenset(used), pts[:-1]))
    return completed


def _polygon(coords):
    p = Polygon(coords)
    if p.is_empty or not p.is_valid or not p.area or not p.exterior.is_simple:
        raise ValueError("invalid or self-intersecting boundary")
    return p


def _assign(outer_polys, hole_polys):
    """Containment requires the entire inner polygon, not an average vertex."""
    assigned = [[] for _ in outer_polys]
    for i, p in enumerate(outer_polys):
        for q in outer_polys[:i]:
            if p.intersection(q).area > 0:
                raise ValueError("overlapping outer boundaries")
    for j, hole in enumerate(hole_polys):
        owners = [i for i, p in enumerate(outer_polys)
                  if p.contains(hole) and p.boundary.disjoint(hole.boundary)]
        if len(owners) != 1:
            raise ValueError("inner boundary lacks a single containing outer")
        assigned[owners[0]].append(j)
    for group in assigned:
        for index, j in enumerate(group):
            if any(not hole_polys[j].disjoint(hole_polys[k]) for k in group[:index]):
                raise ValueError("overlapping or touching cutouts")
    return assigned


def plan_open_surfaces(result, resolve_missing=False, enabled_kinds=("rough","water")):
    rels = {r.id:r for r in result.relations if r.tags.get('type') == 'multipolygon'}
    ways = {w.id:w for w in result.ways}
    kinds, outs, outer_rings, outer_keys = {}, {}, {}, defaultdict(set)
    errors = {}
    for rid, r in rels.items():
        refs = _way_refs(r, "outer")
        kind = surface_kind(r.tags)
        if not kind and not any(k in r.tags for k in ("golf","natural","landuse","amenity","waterway","building")):
            seen = {surface_kind(ways[ref].tags) for ref in refs if ref in ways} - {None}
            if len(seen) == 1:
                kind = next(iter(seen))
        if kind not in enabled_kinds:
            continue
        kinds[rid] = kind
        outs[rid] = refs
        try:
            if any(role(m) == "outer" and not isinstance(m,overpy.RelationWay) for m in r.members):
                raise ValueError("non-way outer boundary")
            rings = _stitch(refs, ways, resolve_missing)
            if not rings: raise ValueError("no complete outer boundary")
            outer_rings[rid] = rings
            outer_keys[kind].update(ring.refs for ring in rings)
        except (ValueError, overpy.exception.OverPyException) as e:
            errors[rid] = str(e)

    drops, blocked, same_refs, omit, plans = set(), set(), {}, {}, {}
    candidate_outers = {k:set().union(*(set(outs[r]) for r in kinds if kinds[r]==k)) for k in ("rough","water")}
    owned_holes = defaultdict(set)
    prelim = {}
    def eligible(ref, kind):
        return ref not in ways or surface_kind(ways[ref].tags) == kind
    for rid, kind in kinds.items():
        r = rels[rid]
        inners = _way_refs(r, "inner")
        # Also accept an explicitly referenced child multipolygon's outer
        # boundary. Its own independent bunkers/greens are untouched.
        children = [m for m in r.members if role(m) == 'inner' and not isinstance(m,overpy.RelationWay)]
        relevant = kind == "water" or any(eligible(w, kind) or w in candidate_outers[kind] for w in inners)
        for m in children:
            if m.__class__.__name__ == 'RelationRelation' and m.ref in rels:
                if kinds.get(m.ref) == kind or kind == 'water':
                    inners.extend(_way_refs(rels[m.ref], "outer")); relevant = True
            elif m.__class__.__name__ == 'RelationRelation' or kind == 'water':
                relevant = True; errors[rid] = "missing/unsupported non-way inner boundary"
        if not relevant:
            continue
        if rid not in errors:
            try:
                all_inners = _stitch(inners, ways, resolve_missing)
                same = [ring for ring in all_inners if ring.refs in outer_keys[kind]
                        or any(eligible(w,kind) for w in ring.refs)]
                holes = all_inners if kind == 'water' else same
                if not holes and kind != 'water':
                    continue
                prelim[rid] = Plan(kind, outer_rings[rid], holes)
                same_refs[rid] = set().union(*(ring.refs for ring in same))
                owned_holes[kind].update(ring.refs for ring in same)
                # Check geographic topology for both the raster and native
                # consumers before allowing any fallback rendering.
                poly = lambda ring: _polygon([(float(n.lon),float(n.lat)) for n in ring.nodes])
                _assign([poly(x) for x in outer_rings[rid]],[poly(x) for x in holes])
            except (ValueError, overpy.exception.OverPyException) as e:
                errors[rid] = str(e)
        # A failed conversion must not fall back to independently filled outers.
        if rid in errors:
            drops.add(rid)
        # Suppress same-surface ways, not different mapped features using
        # the same boundary (notably bunkers and greens).
        blocked.update(w for w in outs[rid]+inners if eligible(w,kind))
        if rid in errors:
            for key in outer_keys[kind]:
                if key and key.issubset(inners):
                    owned_holes[kind].add(key)

    for rid, kind in kinds.items():
        rings = outer_rings.get(rid, [])
        skip = [r for r in rings if r.refs in owned_holes[kind]]
        if skip:
            omit[rid] = set().union(*(ring.refs for ring in skip))
            blocked.update(w for w in omit[rid] if eligible(w,kind))
            if len(skip) == len(rings):
                drops.add(rid)
        if rid in drops:
            continue
        if rid in prelim or skip:
            p = prelim.get(rid, Plan(kind,rings,[]))
            plans[rid] = p
            blocked.update(w for w in outs[rid] if eligible(w,kind))

    return Ownership(plans, kinds, blocked, drops, omit,
                     {rid: refs for rid, refs in same_refs.items() if rid in plans},
                     {rid: why for rid, why in errors.items() if rid in drops})


def lollipop_paths(outers, holes):
    """One simple exterior per shell, with a 0.18 m access slit to each void.

    Choose the nearest unopened island each time. The slit ends on the current
    exterior (which can include a previous slit); never draw an arbitrary
    chord through a concave bank or an intervening island. GEOS subtracts the
    corridor, so the output can never accidentally add fill inside a hole.
    """
    outer_polys = [_polygon(points) for points in outers]
    hole_polys = [_polygon(points) for points in holes]
    assignments = _assign(outer_polys, hole_polys)
    result = []
    for shell, group in zip(outer_polys, assignments):
        geom = Polygon(shell.exterior.coords, [hole_polys[i].exterior.coords for i in group])
        while geom.interiors:
            before = len(geom.interiors)
            ring = min(geom.interiors,key=lambda r: geom.exterior.distance(r))
            a,b = nearest_points(geom.exterior,ring)
            link = LineString([a,b]); radius = 0.09
            # On very narrow strips reduce the width rather than cutting a
            # second unrelated bank or splitting the playable component.
            while radius >= 0.006:
                trial = geom.difference(link.buffer(radius,quad_segs=1,cap_style='square'))
                if (trial.geom_type=='Polygon' and trial.is_valid and
                        len(trial.interiors)==before-1 and not trial.is_empty):
                    geom = trial; break
                radius *= .5
            else:
                raise ValueError("cannot open an island without damaging adjacent geometry")
        result.append(list(geom.exterior.coords)[:-1])
    return result
