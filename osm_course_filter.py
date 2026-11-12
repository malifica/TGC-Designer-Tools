"""Nonmutating, offline course-boundary selection shared by import and previews.

Only golf playing features are scoped. Environment, coordinate dependencies,
and unrelated relations remain available. The source Result is never edited.
"""
from __future__ import annotations

from collections import Counter
import copy
import math

import overpy
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep


COURSE_FILTER_VERSION = "TGC_BETA8_5_COURSE_FILTER_V1"
_ENV_GOLF = frozenset(("water_hazard", "lateral_water_hazard", "cartpath", "cart_path", "path", "clubhouse"))
_AREA_GOLF = frozenset(("green", "tee", "teebox", "tee_box", "fairway", "bunker", "rough",
                        "driving_range", "putting_green", "practice_green", "practice_area", "fringe", "apron", "semi_rough"))


def course_filter_key(text):
    return str(text or "").strip().casefold()


def _tags(value):
    return value if isinstance(value, dict) else (getattr(value, "tags", None) or {})


def _value(tags, key):
    return str(tags.get(key, "") or "").strip().casefold()


def is_golf_feature(value):
    """True for playing-feature tags; hazards, paths and clubhouse are environment."""
    golf = _value(_tags(value), "golf")
    return bool(golf and golf not in _ENV_GOLF)


def is_environment_feature(value):
    tags = _tags(value)
    return (
        _value(tags, "golf") in _ENV_GOLF
        or _value(tags, "natural") in ("water", "wetland", "coastline", "wood", "tree", "tree_row")
        or _value(tags, "landuse") in ("forest", "reservoir", "basin")
        or any(_value(tags, key) not in ("", "no") for key in ("water", "waterway", "building", "building:part", "highway", "railway"))
        or _value(tags, "amenity") in ("parking", "parking_entrance")
        or _value(tags, "golf_cart") in ("yes", "designated")
    )


def is_golf_only(value):
    return is_golf_feature(value) and not is_environment_feature(value)


def _is_boundary(value):
    return _value(_tags(value), "leisure") == "golf_course"


def _node_ids(way):
    return list(getattr(way, "_node_ids", None) or [])


def _member_type(member):
    if isinstance(member, overpy.RelationWay):
        return "way"
    if isinstance(member, overpy.RelationNode):
        return "node"
    if isinstance(member, overpy.RelationRelation):
        return "relation"
    return "unknown"


class _GeometryError(ValueError):
    pass


class _Geometry:
    def __init__(self, nodes, ways, relations):
        self.nodes, self.ways, self.relations = nodes, ways, relations
        self.cache = {}

    def coordinate(self, node_id):
        node = self.nodes.get(node_id)
        if node is None:
            raise _GeometryError("missing node %s" % node_id)
        try:
            x, y = float(node.lon), float(node.lat)
        except (TypeError, ValueError, OverflowError):
            raise _GeometryError("invalid coordinates at node %s" % node_id)
        if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
            raise _GeometryError("invalid coordinates at node %s" % node_id)
        return x, y

    def ring(self, refs):
        if len(refs) < 4 or refs[0] != refs[-1] or len(set(refs[:-1])) < 3:
            raise _GeometryError("ring is incomplete; its first and last node IDs must match")
        polygon = Polygon([self.coordinate(ref) for ref in refs])
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise _GeometryError("ring is invalid or has no area")
        return polygon

    def way(self, way_id, boundary=False):
        key = ("way", way_id, boundary)
        if key in self.cache:
            return self.cache[key]
        way = self.ways.get(way_id)
        if way is None:
            raise _GeometryError("missing way %s" % way_id)
        refs = _node_ids(way)
        if boundary or _value(_tags(way), "golf") in _AREA_GOLF or (len(refs) >= 4 and refs[0] == refs[-1]):
            result = self.ring(refs)
        else:
            coords = [self.coordinate(ref) for ref in refs]
            if len(coords) < 2 or len(set(coords)) < 2:
                raise _GeometryError("way %s has incomplete line geometry" % way_id)
            result = LineString(coords)
            if not result.is_valid:
                raise _GeometryError("way %s has invalid line geometry" % way_id)
        self.cache[key] = result
        return result

    def stitched_rings(self, way_ids):
        if len(set(way_ids)) != len(way_ids):
            raise _GeometryError("duplicate way member in polygon boundary")
        closed, remaining = [], []
        for way_id in way_ids:
            way = self.ways.get(way_id)
            if way is None:
                raise _GeometryError("missing boundary way %s" % way_id)
            refs = _node_ids(way)
            if len(refs) < 2:
                raise _GeometryError("boundary way %s has fewer than two nodes" % way_id)
            for ref in refs:
                self.coordinate(ref)
            if refs[0] == refs[-1]:
                closed.append(self.ring(refs))
            else:
                remaining.append(refs)
        while remaining:
            chain = list(remaining.pop(0))
            while chain[0] != chain[-1]:
                matches = [(index, refs[0] != chain[-1]) for index, refs in enumerate(remaining)
                           if refs[0] == chain[-1] or refs[-1] == chain[-1]]
                if len(matches) != 1:
                    raise _GeometryError("boundary fragments are incomplete or have ambiguous joins at node %s" % chain[-1])
                index, reverse = matches[0]
                segment = remaining.pop(index)
                if reverse:
                    segment = list(reversed(segment))
                chain.extend(segment[1:])
            closed.append(self.ring(chain))
        return closed

    @staticmethod
    def _polygon_parts(geometries):
        parts = []
        for geometry in geometries:
            if isinstance(geometry, Polygon):
                parts.append(geometry)
            elif isinstance(geometry, MultiPolygon):
                parts.extend(geometry.geoms)
            else:
                raise _GeometryError("non-polygon geometry in multipolygon boundary")
        return parts

    def relation(self, rel_id, boundary=False, visiting=None):
        key = ("relation", rel_id, boundary)
        if key in self.cache:
            return self.cache[key]
        visiting = set() if visiting is None else set(visiting)
        if rel_id in visiting:
            raise _GeometryError("cyclic relation boundary at relation %s" % rel_id)
        visiting.add(rel_id)
        relation = self.relations.get(rel_id)
        if relation is None:
            raise _GeometryError("missing relation %s" % rel_id)
        multipolygon = _value(_tags(relation), "type") == "multipolygon"
        if boundary and not multipolygon:
            raise _GeometryError("selected course relation is not a multipolygon")
        members = list(getattr(relation, "members", None) or [])
        if not multipolygon:
            pieces = []
            for member in members:
                kind = _member_type(member)
                if kind == "way":
                    pieces.append(self.way(member.ref))
                elif kind == "node":
                    pieces.append(Point(self.coordinate(member.ref)))
                elif kind == "relation":
                    pieces.append(self.relation(member.ref, visiting=visiting))
            if not pieces:
                raise _GeometryError("relation %s has no complete geometry" % rel_id)
            result = GeometryCollection(pieces)
        else:
            fragments = {"outer": [], "inner": []}
            shapes = {"outer": [], "inner": []}
            for member in members:
                role = str(getattr(member, "role", "") or "").strip().casefold() or "outer"
                kind = _member_type(member)
                if kind == "node" and role in ("label", "admin_centre", "admin_center"):
                    continue
                if role not in fragments:
                    raise _GeometryError("unsupported polygon member role %r" % role)
                if kind == "way":
                    fragments[role].append(member.ref)
                elif kind == "relation":
                    shapes[role].append(self.relation(member.ref, boundary=True, visiting=visiting))
                else:
                    raise _GeometryError("non-way member in polygon boundary")
            for role in fragments:
                shapes[role].extend(self.stitched_rings(fragments[role]))
            outers = self._polygon_parts(shapes["outer"])
            inners = self._polygon_parts(shapes["inner"])
            if not outers:
                raise _GeometryError("multipolygon has no complete outer ring")
            exterior = outers[0] if len(outers) == 1 else MultiPolygon(outers)
            if not exterior.is_valid:
                raise _GeometryError("multipolygon outer rings overlap or are invalid")
            if inners:
                interior = inners[0] if len(inners) == 1 else MultiPolygon(inners)
                if not interior.is_valid or not exterior.covers(interior):
                    raise _GeometryError("multipolygon inner rings overlap or lie outside the outer boundary")
                if exterior.boundary.intersection(interior.boundary).length > 0:
                    raise _GeometryError("multipolygon inner and outer rings share a boundary segment")
                result = exterior.difference(interior)
            else:
                result = exterior
            if result.is_empty or not result.is_valid or result.area <= 0:
                raise _GeometryError("multipolygon has invalid or empty area")
        self.cache[key] = result
        return result


class _OfflineAPI:
    def query(self, *args, **kwargs):
        raise overpy.exception.DataIncomplete("Course-filtered OSM is offline; referenced geometry is missing from the supplied source")


def _new_filtered_result():
    # Legacy blank-filter verifiers provide a minimal overpy stub. The pure
    # key/classifier API and blank path must not require Result construction.
    class FilteredResult(overpy.Result):
        def get_way(self, way_id, resolve_missing=False):
            return super().get_way(way_id, resolve_missing=False)

        def get_node(self, node_id, resolve_missing=False):
            return super().get_node(node_id, resolve_missing=False)

        def get_relation(self, rel_id, resolve_missing=False):
            return super().get_relation(rel_id, resolve_missing=False)

    return FilteredResult(api=_OfflineAPI())


def _clone(element, result, suppress=False):
    cloned = copy.copy(element)
    cloned._result = result
    cloned.tags = copy.deepcopy(getattr(element, "tags", None) or {})
    cloned.attributes = copy.deepcopy(getattr(element, "attributes", None))
    if suppress:
        cloned._tgc_course_filter_original_tags = dict(cloned.tags)
        cloned.tags.pop("golf", None)
        cloned._tgc_course_filter_dependency_only = True
    if isinstance(element, overpy.Way):
        cloned._node_ids = list(_node_ids(element))
    if isinstance(element, overpy.Relation):
        cloned.members = []
        for member in getattr(element, "members", None) or []:
            copied = copy.copy(member)
            copied._result = result
            copied.attributes = copy.deepcopy(getattr(member, "attributes", None))
            copied.geometry = copy.deepcopy(getattr(member, "geometry", None))
            cloned.members.append(copied)
    return cloned


def filter_osm_course(osm_result, course_name_filter="", printf=print):
    """Scope golf features to complete named course boundaries using ``covers``.

    Blank input returns the input object itself. All nonblank outputs are new
    Overpy Results with cloned elements. ``_tgc_course_filter_report`` is a
    JSON-serializable dict; all ID inventories are sorted lists of integers.
    Invalid/missing selected boundaries raise ValueError before any mutation.
    """
    key = course_filter_key(course_name_filter)
    if not key:
        return osm_result
    previous = getattr(osm_result, "_tgc_course_filter_report", {})
    if previous.get("key") == key:
        return osm_result
    source = getattr(osm_result, "_tgc_course_filter_source", osm_result)
    nodes = {int(item.id): item for item in getattr(source, "nodes", [])}
    ways = {int(item.id): item for item in getattr(source, "ways", [])}
    relations = {int(item.id): item for item in getattr(source, "relations", [])}
    geometry = _Geometry(nodes, ways, relations)
    candidates = [(kind, item_id, str(_tags(item).get("name", "") or "").strip())
                  for kind, items in (("way", ways), ("relation", relations)) for item_id, item in items.items()
                  if _is_boundary(item) and str(_tags(item).get("name", "") or "").strip()]
    available = sorted({name for _, _, name in candidates}, key=lambda value: (value.casefold(), value))
    available_text = "; ".join(available) if available else "(no named leisure=golf_course boundaries in this OSM source)"
    selected = [(kind, item_id, name) for kind, item_id, name in candidates if key in name.casefold()]
    if not selected:
        raise ValueError("Course Name filter %r matched no course boundary. Available course names: %s" % (str(course_name_filter).strip(), available_text))
    boundaries = []
    for kind, item_id, name in selected:
        try:
            boundaries.append(geometry.way(item_id, boundary=True) if kind == "way" else geometry.relation(item_id, boundary=True))
        except Exception as exc:
            raise ValueError("Course Name filter cannot use %r (%s %s): %s. Available course names: %s" % (name, kind, item_id, exc, available_text)) from exc
    selected_geometry = unary_union(boundaries)
    if selected_geometry.is_empty or not selected_geometry.is_valid:
        raise ValueError("Course Name filter produced an invalid combined boundary. Available course names: " + available_text)
    prepared = prep(selected_geometry)
    invalid = []

    def covered(kind, item_id):
        try:
            shape = (Point(geometry.coordinate(item_id)) if kind == "node" else
                     geometry.way(item_id) if kind == "way" else geometry.relation(item_id))
            return bool(prepared.covers(shape))
        except Exception as exc:
            invalid.append({"type": kind, "id": int(item_id), "reason": str(exc)})
            return False

    closure_cache = {}

    def member_closure(rel_id):
        if rel_id in closure_cache:
            return closure_cache[rel_id]
        way_refs, node_refs, relation_refs = set(), set(), set()
        queue, visited = [rel_id], set()
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            relation = relations.get(current)
            if relation is None:
                continue
            for member in getattr(relation, "members", None) or []:
                kind = _member_type(member)
                ref = int(member.ref)
                if kind == "way":
                    way_refs.add(ref)
                elif kind == "node":
                    node_refs.add(ref)
                elif kind == "relation":
                    relation_refs.add(ref)
                    queue.append(ref)
        relation_refs.discard(rel_id)
        closure_cache[rel_id] = (way_refs, node_refs, relation_refs)
        return closure_cache[rel_id]

    core_ways = {item_id for item_id, item in ways.items() if is_golf_feature(item)}
    core_nodes = {item_id for item_id, item in nodes.items() if is_golf_feature(item)}
    core_relations = {item_id for item_id, item in relations.items() if is_golf_feature(item)}
    inferred_relations = set()
    # Legacy multipolygons sometimes put golf tags only on outer member ways.
    for item_id, relation in relations.items():
        if item_id in core_relations or _is_boundary(relation) or is_environment_feature(relation) or _value(_tags(relation), "type") != "multipolygon":
            continue
        outer = [ways.get(int(member.ref)) for member in getattr(relation, "members", None) or []
                 if _member_type(member) == "way" and str(getattr(member, "role", "") or "").strip().casefold() in ("", "outer")]
        kinds = {_value(_tags(way), "golf") for way in outer if way is not None and is_golf_feature(way)}
        if len(kinds) == 1:
            core_relations.add(item_id)
            inferred_relations.add(item_id)
    kept_golf_relations = {item_id for item_id in core_relations if covered("relation", item_id)}
    excluded_golf_relations = core_relations - kept_golf_relations
    # Do not resurrect an excluded parent relation's tagged child as a new
    # standalone feature unless a retained golf relation also owns that child.
    while True:
        rejected_children = set().union(*(member_closure(rid)[2] for rid in excluded_golf_relations)) if excluded_golf_relations else set()
        accepted_children = set().union(*(member_closure(rid)[2] for rid in kept_golf_relations)) if kept_golf_relations else set()
        drop = kept_golf_relations & (rejected_children - accepted_children)
        if not drop:
            break
        kept_golf_relations -= drop
        excluded_golf_relations |= drop
    rejected_ways, rejected_nodes, accepted_ways, accepted_nodes = set(), set(), set(), set()
    for rel_id in excluded_golf_relations:
        wr, nr, _ = member_closure(rel_id)
        rejected_ways.update(wr)
        rejected_nodes.update(nr)
    for rel_id in kept_golf_relations:
        wr, nr, _ = member_closure(rel_id)
        accepted_ways.update(wr)
        accepted_nodes.update(nr)
    kept_golf_ways = {item_id for item_id in core_ways if covered("way", item_id)
                      and (item_id not in rejected_ways or item_id in accepted_ways)}
    kept_golf_nodes = {item_id for item_id in core_nodes if covered("node", item_id)
                       and (item_id not in rejected_nodes or item_id in accepted_nodes)}
    excluded_golf_ways = core_ways - kept_golf_ways
    excluded_golf_nodes = core_nodes - kept_golf_nodes

    keep_ways = {item_id for item_id, item in ways.items() if item_id not in core_ways or item_id in kept_golf_ways or is_environment_feature(item)}
    keep_nodes = {item_id for item_id, item in nodes.items() if item_id not in core_nodes or item_id in kept_golf_nodes or is_environment_feature(item)}
    keep_relations = {item_id for item_id, item in relations.items() if item_id not in core_relations or item_id in kept_golf_relations or is_environment_feature(item)}
    selected_way_ids = {item_id for kind, item_id, _ in selected if kind == "way"}
    selected_relation_ids = {item_id for kind, item_id, _ in selected if kind == "relation"}
    # Other course outlines are metadata, not environmental features.
    excluded_boundary_ways = {item_id for item_id, item in ways.items() if _is_boundary(item) and item_id not in selected_way_ids}
    excluded_boundary_relations = {item_id for item_id, item in relations.items() if _is_boundary(item) and item_id not in selected_relation_ids}
    keep_ways -= excluded_boundary_ways
    keep_relations -= excluded_boundary_relations
    keep_ways |= selected_way_ids
    keep_relations |= selected_relation_ids
    initial_ways, initial_nodes, initial_relations = set(keep_ways), set(keep_nodes), set(keep_relations)
    needed_ways, needed_nodes, needed_relations = set(), set(), set()
    for rel_id in list(keep_relations):
        wr, nr, rr = member_closure(rel_id)
        needed_ways.update(wr)
        needed_nodes.update(nr)
        needed_relations.update(rr)
    keep_ways |= needed_ways & set(ways)
    keep_relations |= needed_relations & set(relations)
    for way_id in keep_ways:
        needed_nodes.update(_node_ids(ways[way_id]))
    keep_nodes |= needed_nodes & set(nodes)
    suppressed_ways = excluded_golf_ways & keep_ways
    suppressed_nodes = excluded_golf_nodes & keep_nodes
    suppressed_relations = excluded_golf_relations & keep_relations
    result = _new_filtered_result()
    for item_id, item in nodes.items():
        if item_id in keep_nodes:
            result.append(_clone(item, result, item_id in suppressed_nodes))
    for item_id, item in ways.items():
        if item_id in keep_ways:
            result.append(_clone(item, result, item_id in suppressed_ways))
    for item_id, item in relations.items():
        if item_id in keep_relations:
            result.append(_clone(item, result, item_id in suppressed_relations))
    for item in getattr(source, "areas", []) or []:
        result.append(_clone(item, result))
    inventories = {
        "included_way_ids": keep_ways, "included_node_ids": keep_nodes, "included_relation_ids": keep_relations,
        "included_golf_way_ids": kept_golf_ways, "included_golf_node_ids": kept_golf_nodes,
        "included_golf_relation_ids": kept_golf_relations,
        "excluded_golf_way_ids": excluded_golf_ways, "excluded_golf_node_ids": excluded_golf_nodes,
        "excluded_golf_relation_ids": excluded_golf_relations,
        "suppressed_golf_way_ids": suppressed_ways, "suppressed_golf_node_ids": suppressed_nodes,
        "suppressed_golf_relation_ids": suppressed_relations,
        "dependency_only_way_ids": keep_ways - initial_ways, "dependency_only_node_ids": keep_nodes - initial_nodes,
        "dependency_only_relation_ids": keep_relations - initial_relations,
        "selected_boundary_way_ids": selected_way_ids, "selected_boundary_relation_ids": selected_relation_ids,
        "excluded_boundary_way_ids": excluded_boundary_ways, "excluded_boundary_relation_ids": excluded_boundary_relations,
        "excluded_relation_member_way_ids": rejected_ways, "inferred_golf_relation_ids": inferred_relations,
        "missing_dependency_way_ids": needed_ways - set(ways), "missing_dependency_node_ids": needed_nodes - set(nodes),
        "missing_dependency_relation_ids": needed_relations - set(relations),
    }
    report = {"version": COURSE_FILTER_VERSION, "key": key, "selected_names": sorted({name for _, _, name in selected}, key=str.casefold),
              "available_course_names": available, "containment": "covers", "invalid_golf_features": invalid}
    report.update({name: sorted(int(value) for value in values) for name, values in inventories.items()})
    report["counts"] = {name.replace("_ids", ""): len(values) for name, values in inventories.items()}
    report["counts"].update(source_ways=len(ways), source_nodes=len(nodes), source_relations=len(relations))
    report["golf_way_type_counts"] = dict(sorted(Counter(_value(_tags(ways[item_id]), "golf") for item_id in kept_golf_ways).items()))
    result._tgc_course_filter_report = report
    result._tgc_course_filter_source = source
    if printf is not None:
        printf("Course Name filter: %s; kept %d golf ways, %d golf relations and %d golf nodes; excluded %d/%d/%d. Environment retained." %
               (", ".join(report["selected_names"]), len(kept_golf_ways), len(kept_golf_relations), len(kept_golf_nodes),
                len(excluded_golf_ways), len(excluded_golf_relations), len(excluded_golf_nodes)))
        if invalid:
            printf("Course Name filter: %d incomplete or invalid golf feature(s) excluded; details are in the filter report." % len(invalid))
    return result
