"""Manual OSM boundary ownership and lossless local topology edits (V6 all surfaces).

Rough boundaries are read from OSM, never fitted to terrain. A directly tagged
feature and a relation member can share one way while representing independently
editable surfaces. Export separates those owners only when their offsets differ.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import explain_validity

from tgc_local_alignment import AlignmentError

ROUGH_KINDS = {"rough", "heavyrough"}
_ATTRIBUTE = re.compile(rb"([A-Za-z_:][A-Za-z0-9_:.-]*)\s*=\s*([\"'])(.*?)\2", re.S)
ZERO = (0.0, 0.0)


def _tags(element):
    return {tag.get("k"): tag.get("v") for tag in element.findall("tag")}


def _index(root, kind):
    result = {}
    for item in root.findall(kind):
        key = item.get("id")
        try:
            valid = str(int(key)) == key
        except (ValueError, TypeError):
            valid = False
        if not valid or key in result:
            raise AlignmentError("Invalid or duplicate OSM " + kind + " ID.")
        result[key] = item
    return result


def _rings(relation, ways, role):
    """Assemble complete rings from member fragments without guessing edges."""
    fragments = []
    for index, member in enumerate(relation.findall("member")):
        actual_role = member.get("role", "") or "outer"
        if actual_role != role:
            continue
        if member.get("type") != "way" or member.get("ref") not in ways:
            raise AlignmentError("Surface/rough relation %s has a missing/non-way %s member." % (relation.get("id"), role))
        wid = member.get("ref")
        refs = [nd.get("ref") for nd in ways[wid].findall("nd")]
        if len(refs) < 2:
            raise AlignmentError("Surface/rough relation %s has an incomplete %s boundary." % (relation.get("id"), role))
        fragments.append((refs, [index], [wid]))
    result = []
    while fragments:
        refs, indexes, wids = fragments.pop(0)
        refs = list(refs)
        while refs[0] != refs[-1]:
            matches = [(i, fragment[0][0] == refs[-1]) for i, fragment in enumerate(fragments)
                       if fragment[0][0] == refs[-1] or fragment[0][-1] == refs[-1]]
            if len(matches) != 1:
                raise AlignmentError("Surface/rough relation %s has an open or branching %s boundary." % (relation.get("id"), role))
            i, forward = matches[0]
            other, other_indexes, other_wids = fragments.pop(i)
            refs.extend((other if forward else list(reversed(other)))[1:])
            indexes.extend(other_indexes)
            wids.extend(other_wids)
        if len(refs) < 4 or len(set(refs[:-1])) != len(refs)-1:
            raise AlignmentError("Surface/rough relation %s has a non-simple %s boundary." % (relation.get("id"), role))
        pairs = sorted(zip(indexes, wids))
        result.append((refs, [p[0] for p in pairs], [p[1] for p in pairs]))
    return sorted(result, key=lambda ring: min(ring[1]))


def _projector(nodes, grid, projection):
    from tgc_cfs_display import importer_transformer
    transform = importer_transformer(projection)
    cache = {}

    def coordinates(refs):
        for nid in dict.fromkeys(refs):
            if nid in cache:
                continue
            if nid not in nodes:
                raise AlignmentError("An OSM boundary refers to a missing node.")
            node = nodes[nid]
            try:
                lon, lat = float(node.get("lon")), float(node.get("lat"))
                if not (math.isfinite(lon) and math.isfinite(lat) and abs(lon) <= 180 and abs(lat) <= 90):
                    raise ValueError("geographic coordinate")
                x, y = transform.transform(lon, lat, errcheck=True)
                if not math.isfinite(x+y):
                    raise ValueError("projected coordinate")
                cache[nid] = [x-grid["min_x"], y-grid["min_y"]]
            except Exception as exc:
                raise AlignmentError("An OSM boundary contains invalid coordinates.") from exc
        return [cache[nid] for nid in refs]
    return coordinates


def _geometry(feature, refs, coordinates):
    feature.update(node_ids=[], coords_m=[], geometry_valid=False, topology_reasons=[])
    try:
        feature["node_ids"] = [int(nid) for nid in refs]
        points = coordinates(refs)
        feature["coords_m"] = points
        if len(refs) < 4 or refs[0] != refs[-1] or len(set(refs[:-1])) != len(refs)-1:
            raise AlignmentError("This rough boundary must be a complete closed ring.")
        poly = Polygon(points)
        if not poly.is_valid or poly.is_empty or poly.area <= 1e-6:
            raise AlignmentError("Invalid rough boundary: " + explain_validity(poly))
        if len({tuple(p) for p in points[:-1]}) != len(points)-1:
            raise AlignmentError("This rough boundary repeats polygon coordinates.")
        feature.update(geometry_valid=True, centroid_m=list(poly.centroid.coords[0]),
                       area_m2=float(poly.area), bounds_m=list(poly.bounds))
    except Exception as exc:
        feature["topology_reasons"] = [str(exc)]


# TGC_BETA7_ALL_FEATURES_V6
SURFACE_NAMES = {
    "tee": "Tee", "bunker": "Bunker", "green": "Green", "fairway": "Fairway",
    "rough": "Rough", "heavyrough": "Heavy rough", "water": "Water", "mulch": "Mulch",
    "cartpath": "Cart path", "path": "Path", "road": "Road", "range": "Driving range",
    "wood": "Natural wood", "building": "Building", "hole": "Hole route",
    "forest": "Forest (outline only)", "woodchips": "Woodchips (outline only)",
    "parking_lot": "Surface parking lot",
}
LINE_KINDS = {"cartpath", "path", "road", "hole"}


def surface_kind(tags):
    """Local editor classification; original OSM tags are never rewritten."""
    golf = str(tags.get("golf", "")).lower()
    aliases = {"water_hazard": "water", "lateral_water_hazard": "water",
               "driving_range": "range", "heavy_rough": "heavyrough"}
    kind = aliases.get(golf, golf)
    if kind in SURFACE_NAMES and kind not in ("mulch", "wood", "forest", "woodchips", "parking_lot"):
        return kind
    from OSMTGC import classifyDryAreaForTGC, _surface_parking_area
    if _surface_parking_area(tags):
        return "parking_lot"
    dry_kind = classifyDryAreaForTGC(tags)
    if dry_kind:
        return dry_kind
    if tags.get("natural") == "water" or tags.get("waterway"):
        return "water"
    if tags.get("building") not in (None, "", "no"):
        return "building"
    if tags.get("highway") in ("path", "footway", "cycleway", "steps", "bridleway", "pedestrian"):
        return "path"
    if tags.get("highway"):
        return "road"
    # Retain these editable outlines without labeling them as native mulch.
    if not golf and tags.get("natural") not in ("tree", "meadow", "grassland") and tags.get("area") != "no":
        if tags.get("landuse") == "forest":
            return "forest"
        if tags.get("surface") == "woodchips":
            return "woodchips"
    return None


def _surface_geometry(feature, refs, coordinates):
    """Closed areas and explicit open routes; never close missing relation pieces."""
    if refs and refs[0] == refs[-1]:
        _geometry(feature, refs, coordinates)
        feature["is_closed"] = True
        return
    feature.update(node_ids=[], coords_m=[], geometry_valid=False,
                   topology_reasons=[], is_closed=False)
    allow_line = feature.get("kind") in LINE_KINDS or bool(feature.get("tags", {}).get("waterway"))
    try:
        if not allow_line or feature.get("boundary_role") in ("inner", "outer"):
            raise AlignmentError("This area needs a complete closed boundary; missing edges were not guessed.")
        from shapely.geometry import LineString
        points = coordinates(refs)
        feature.update(node_ids=[int(n) for n in refs], coords_m=points)
        line = LineString(points)
        if len(refs) < 2 or not line.is_valid or not line.is_simple or line.length <= 1e-6:
            raise AlignmentError("This route is incomplete or self-intersecting.")
        feature.update(geometry_valid=True, centroid_m=list(line.centroid.coords[0]),
                       bounds_m=list(line.bounds), area_m2=0.)
    except Exception as exc:
        feature["topology_reasons"] = [str(exc)]


def augment_inventory(raw, grid, projection, primary):
    """V5 ownership model extended to complete multipolygons and every surface.

    Direct objects and relation rings are independent owners. Same-shape direct
    objects are linked to their matching relation cutout. Unselected neighbours
    remain stationary. Whole relations can be selected using Related boundaries.
    """
    root = ET.fromstring(raw)
    nodes, ways, relations = (_index(root, kind) for kind in ("node", "way", "relation"))
    coordinates = _projector(nodes, grid, projection)
    relation_targets, consumed = [], set()
    for rid, relation in relations.items():
        tags = _tags(relation)
        kind = surface_kind(tags)
        if not kind or tags.get("type") != "multipolygon":
            continue
        rough = kind in ROUGH_KINDS
        for role in ("outer", "inner"):
            try:
                rings = _rings(relation, ways, role)
                ring_error = ""
            except AlignmentError as exc:
                indexes, wids = [], []
                for i, member in enumerate(relation.findall("member")):
                    if (member.get("role", "") or "outer") == role and member.get("type") == "way":
                        indexes.append(i)
                        if member.get("ref") in ways:
                            wids.append(member.get("ref"))
                if not indexes:
                    continue
                rings, ring_error = [([], indexes, wids)], str(exc)
            for number, (refs, indexes, wids) in enumerate(rings):
                prefix = "rough" if rough else "surface"
                sid = "%s-ring:%s:%s:%d" % (prefix, rid, role, number)
                owned = [wid for wid in wids if role == "outer" and
                         surface_kind(_tags(ways[wid])) == kind and wid not in consumed]
                consumed.update(owned)
                # Preserve V5's rough kind/IDs so its existing manifests/tests work.
                displayed_kind = "rough" if rough else kind
                label = SURFACE_NAMES[kind] + (" hole" if role == "inner" else " outer")
                feature = dict(selection_id=sid, id=sid, target_type=prefix+"_ring",
                    kind=displayed_kind, surface_kind=kind, way_id=int(wids[0]) if wids else 0,
                    relation_id=int(rid), display_id="R%s %s %d" % (rid, role, number+1),
                    label=label, boundary_role=role, tags=tags, member_way_ids=[int(w) for w in wids],
                    owned_way_ids=[int(w) for w in owned], member_indexes=indexes,
                    shared_nodes=[], relation_memberships=[], node_relation_memberships=[],
                    kind_from_relation=True, course_name="", linked_ids=[], related_ids=[], manual_only=True)
                _surface_geometry(feature, refs, coordinates)
                if ring_error:
                    feature["topology_reasons"] = [ring_error]
                relation_targets.append(feature)
    targets, primary_way_ids = [], set()
    for feature in primary:
        wid = str(feature["way_id"])
        # Relation-derived open fragments are represented by their complete ring,
        # not by a second invalid or independently movable pseudo-polygon.
        if wid in consumed or wid not in ways or _tags(ways[wid]).get("golf") not in ("tee", "bunker"):
            continue
        if wid in primary_way_ids:
            continue
        primary_way_ids.add(wid)
        feature.update(selection_id=wid, target_type="feature_way", display_id=wid,
                       label=feature["kind"].title(), boundary_role="feature",
                       member_way_ids=[int(wid)], owned_way_ids=[int(wid)],
                       member_indexes=[], linked_ids=[], related_ids=[], is_closed=True,
                       surface_kind=feature["kind"], kind_from_relation=False)
        targets.append(feature)
    targets.extend(relation_targets)
    for wid, way in ways.items():
        kind = surface_kind(_tags(way))
        if not kind or wid in consumed or wid in primary_way_ids:
            continue
        rough = kind in ROUGH_KINDS
        # Direct tees/bunkers are still available when their auto-fit checkbox is off.
        if kind in ("tee", "bunker"):
            sid, target_type = wid, "feature_way"
        else:
            prefix = "rough" if rough else "surface"
            sid, target_type = prefix+"-way:"+wid, prefix+"_way"
        feature = dict(selection_id=sid, id=sid, target_type=target_type,
                       kind="rough" if rough else kind, surface_kind=kind, way_id=int(wid),
                       display_id=wid, label=SURFACE_NAMES[kind]+(" way" if rough else ""),
                       boundary_role="way", tags=_tags(way), member_way_ids=[int(wid)],
                       owned_way_ids=[int(wid)], member_indexes=[], shared_nodes=[],
                       relation_memberships=[], node_relation_memberships=[], kind_from_relation=False,
                       course_name="", linked_ids=[], related_ids=[], manual_only=True)
        _surface_geometry(feature, [nd.get("ref") for nd in way.findall("nd")], coordinates)
        targets.append(feature)
    by_id = {f["selection_id"]: f for f in targets}
    if len(by_id) != len(targets):
        raise AlignmentError("The editor inventory contains duplicate boundary owners.")
    boundaries = [f for f in targets if "relation_id" in f]
    direct = [f for f in targets if "relation_id" not in f]
    related, linked = defaultdict(set), defaultdict(set)
    for feature in direct:
        sid, wid = feature["selection_id"], feature["way_id"]
        node_ids, touched = set(feature.get("node_ids", [])), set()
        for boundary in boundaries:
            bid = boundary["selection_id"]
            if wid in boundary["member_way_ids"] or node_ids.intersection(boundary.get("node_ids", [])):
                related[sid].add(bid); related[bid].add(sid)
                touched.add(boundary["relation_id"])
            if boundary["boundary_role"] == "inner" and wid in boundary["member_way_ids"]:
                linked[sid].add(bid); linked[bid].add(sid)
        for boundary in boundaries:
            if boundary["relation_id"] in touched:
                related[sid].add(boundary["selection_id"])
                related[boundary["selection_id"]].add(sid)
    groups = defaultdict(list)
    for f in boundaries:
        groups[f["relation_id"]].append(f["selection_id"])
    for ids in groups.values():
        for sid in ids:
            related[sid].update(set(ids)-{sid})
    # Differently tagged direct features can share nodes without sharing motion.
    for i, left in enumerate(direct):
        a = set(left.get("node_ids", []))
        for right in direct[i+1:]:
            if a.intersection(right.get("node_ids", [])):
                related[left["selection_id"]].add(right["selection_id"])
                related[right["selection_id"]].add(left["selection_id"])
    for sid, feature in by_id.items():
        feature["linked_ids"], feature["related_ids"] = sorted(linked[sid]), sorted(related[sid])
    return targets


def manual_eligibility(feature):
    """Eligibility is geometry/ownership based, never merely blocked by a relation."""
    allowed_types = {"feature_way", "rough_way", "rough_ring", "surface_way", "surface_ring"}
    if feature.get("target_type") not in allowed_types:
        return False, "This object has no supported boundary owner. Analyze the current OSM again."
    if feature.get("kind") not in SURFACE_NAMES:
        return False, "This OSM feature type is not recognized as an editable surface or route."
    refs = feature.get("node_ids", [])
    reasons = set(feature.get("topology_reasons", [])) - {
        "shared_node_requires_joint_review", "relation_member_requires_joint_review"}
    if feature.get("geometry_valid") is not True or reasons:
        return False, "Incomplete or invalid boundary geometry: " + "; ".join(sorted(reasons))
    try:
        points = np.asarray(feature.get("coords_m", []), dtype=float)
        if points.shape != (len(refs), 2) or not np.all(np.isfinite(points)):
            return False, "Invalid boundary coordinates."
        closed = feature.get("is_closed", bool(refs and refs[0] == refs[-1]))
        if closed:
            if len(refs) < 4 or refs[0] != refs[-1] or len(set(refs[:-1])) != len(refs)-1:
                return False, "This area must be a closed ring with unique OSM nodes."
            if not np.array_equal(points[0], points[-1]):
                return False, "The area is not closed."
            poly = Polygon(points)
            if not poly.is_valid or poly.area <= 1e-6 or len({tuple(p) for p in points[:-1]}) != len(points)-1:
                return False, "The area is not a valid simple ring."
        else:
            from shapely.geometry import LineString
            if len(refs) < 2 or not LineString(points).is_simple or LineString(points).length <= 1e-6:
                return False, "The route is not a valid line."
    except (ValueError, TypeError) as exc:
        return False, str(exc)
    return True, ""


def _xml_spans(raw):
    """Locate numeric reference spans using parser-confirmed element positions."""
    parser = expat.ParserCreate()
    stack, top, indexes = [], None, {}
    node_spans, nd_spans, member_spans, positions = {}, {}, {}, {}

    def attrs_at(begin):
        end, quote = begin, None
        while end < len(raw):
            byte = raw[end]
            if quote is not None:
                if byte == quote: quote = None
            elif byte in (34, 39): quote = byte
            elif byte == 62: break
            end += 1
        return {m.group(1).decode("ascii"): (begin+m.start(3), begin+m.end(3))
                for m in _ATTRIBUTE.finditer(raw[begin:end+1])}

    def start(name, attributes):
        nonlocal top, indexes
        if len(stack) == 1:
            top = (name, attributes.get("id"))
            indexes = defaultdict(int)
            positions.setdefault(name, parser.CurrentByteIndex)
            if name == "node":
                node_spans[top[1]] = attrs_at(parser.CurrentByteIndex)
        elif len(stack) == 2 and top:
            index = indexes[name]
            indexes[name] += 1
            if name == "nd" and top[0] == "way":
                nd_spans[(top[1], index)] = attrs_at(parser.CurrentByteIndex).get("ref")
            elif name == "member" and top[0] == "relation":
                member_spans[(top[1], index)] = attrs_at(parser.CurrentByteIndex).get("ref")
        stack.append(name)

    def end(name):
        if len(stack) == 1 and name == "osm":
            positions["root_end"] = parser.CurrentByteIndex
        stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.ExternalEntityRefHandler = lambda *_: 0
    parser.Parse(raw, True)
    return node_spans, nd_spans, member_spans, positions


def _validate_rough_relations(root, relation_ids, grid, projection):
    nodes, ways, relations = (_index(root, kind) for kind in ("node", "way", "relation"))
    coordinates = _projector(nodes, grid, projection)
    for rid in relation_ids:
        relation = relations[rid]
        outer_rings, inner_rings = _rings(relation, ways, "outer"), _rings(relation, ways, "inner")
        if not outer_rings:
            raise AlignmentError("Surface/rough relation %s needs a complete outer boundary." % rid)
        outers = [Polygon(coordinates(ring[0])) for ring in outer_rings]
        holes = [Polygon(coordinates(ring[0])) for ring in inner_rings]
        if any(poly.is_empty or not poly.is_valid or poly.area <= 1e-6 for poly in outers+holes):
            raise AlignmentError("The move would create an invalid boundary in rough relation %s." % rid)
        if not MultiPolygon(outers).is_valid:
            raise AlignmentError("The move would overlap outer boundaries in rough relation %s." % rid)
        for i, hole in enumerate(holes):
            owners = [outer for outer in outers if outer.contains(hole) and outer.boundary.disjoint(hole)]
            if len(owners) != 1:
                raise AlignmentError("The rough hole would leave or touch its outer boundary in relation %s. Move the relevant boundaries together." % rid)
            if any(not hole.disjoint(other) for other in holes[:i]):
                raise AlignmentError("The move would overlap rough holes in relation %s." % rid)


def render_translations(raw, features, shifts, grid, projection):
    """Return edited bytes plus an auditable ownership/clone summary.

Unselected direct ways and unselected relation members retain their exact
geometry. Selected owners share original nodes/ways when their offset agrees;
otherwise only their geometry references are detached to new local IDs.
"""
    from tgc_cfs_display import importer_transformer
    root = ET.fromstring(raw)
    nodes, ways, relations = (_index(root, kind) for kind in ("node", "way", "relation"))
    by_id = {f["selection_id"]: f for f in features}
    direct_owner, member_owner = {}, {}
    for feature in features:
        sid = feature["selection_id"]
        for wid in feature.get("owned_way_ids", []):
            if str(wid) in direct_owner:
                raise AlignmentError("More than one manual target owns the same direct way.")
            direct_owner[str(wid)] = sid
        if feature.get("target_type") in {"rough_ring", "surface_ring"}:
            for index in feature["member_indexes"]:
                key = (str(feature["relation_id"]), index)
                if key in member_owner:
                    raise AlignmentError("A surface relation member appears in multiple boundary targets.")
                member_owner[key] = sid
    member_demands, way_members = {}, defaultdict(list)
    explicit_node_refs = set()
    for rid, relation in relations.items():
        for index, member in enumerate(relation.findall("member")):
            if member.get("type") == "way":
                wid = member.get("ref")
                owner = member_owner.get((rid, index))
                demand = tuple(shifts.get(owner, ZERO))
                member_demands[(rid, index)] = demand
                way_members[wid].append((rid, index))
            elif member.get("type") == "node":
                explicit_node_refs.add(member.get("ref"))
    next_way = min([0]+[int(wid) for wid in ways])-1
    next_node = min([0]+[int(nid) for nid in nodes])-1
    # Instances are (source way ID, residual). One is the retained original way.
    instance_ids, original_shift, member_refs = {}, {}, {}
    clone_ways = []
    for wid, way in ways.items():
        memberships = way_members.get(wid, [])
        demands = [member_demands[key] for key in memberships]
        owner = direct_owner.get(wid)
        if owner is not None or _tags(way) or not demands:
            base_shift = tuple(shifts.get(owner, ZERO))
        elif ZERO in demands:
            base_shift = ZERO
        else:
            base_shift = demands[0]
        original_shift[wid] = base_shift
        instance_ids[(wid, base_shift)] = wid
        for key in memberships:
            demand = member_demands[key]
            instance = (wid, demand)
            if instance not in instance_ids:
                new_id = str(next_way); next_way -= 1
                instance_ids[instance] = new_id
                clone_ways.append({"way_id": int(new_id), "source_way_id": int(wid),
                                   "east_m": demand[0], "north_m": demand[1], "geometry_only": True})
            member_refs[key] = instance_ids[instance]
    node_demands = defaultdict(set)
    for (wid, shift), instance_id in instance_ids.items():
        for nd in ways[wid].findall("nd"):
            nid = nd.get("ref")
            if nid not in nodes:
                if shift == ZERO:
                    continue
                raise AlignmentError("An affected OSM way refers to a missing node.")
            node_demands[nid].add(shift)
    node_instances, original_node_shift, clone_nodes = {}, {}, []
    for nid, node in nodes.items():
        demands = node_demands[nid]
        if _tags(node) or nid in explicit_node_refs or not demands or ZERO in demands:
            base_shift = ZERO
        else:
            base_shift = sorted(demands)[0]
        original_node_shift[nid] = base_shift
        node_instances[(nid, base_shift)] = nid
        for shift in sorted(demands):
            if (nid, shift) in node_instances:
                continue
            new_id = str(next_node); next_node -= 1
            node_instances[(nid, shift)] = new_id
            clone_nodes.append({"node_id": int(new_id), "source_node_id": int(nid),
                               "east_m": shift[0], "north_m": shift[1], "geometry_only": True})
    transformer = importer_transformer(projection)
    node_spans, nd_spans, member_spans, positions = _xml_spans(raw)
    edits, expected_nodes, cloned_node_xml, cloned_way_xml = [], {}, [], []
    modified_nodes = []

    def coordinate(nid, shift):
        node = nodes[nid]
        if shift == ZERO:
            try:
                old = transformer.transform(float(node.get("lon")), float(node.get("lat")), errcheck=True)
            except Exception:
                old = None
            return node.get("lon"), node.get("lat"), old
        old = transformer.transform(float(node.get("lon")), float(node.get("lat")), errcheck=True)
        expected = (old[0]+shift[0], old[1]+shift[1])
        lon, lat = transformer.transform(*expected, direction="INVERSE", errcheck=True)
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise AlignmentError("A translated coordinate is not finite.")
        return "%.12f" % lon, "%.12f" % lat, expected

    def replace_span(span, text):
        if span is None:
            raise AlignmentError("Could not locate a parser-confirmed OSM coordinate/reference.")
        edits.append((span[0], span[1], str(text).encode("ascii")))

    for (nid, shift), output_id in node_instances.items():
        lon, lat, expected = coordinate(nid, shift)
        expected_nodes[output_id] = expected
        if output_id == nid:
            if shift != ZERO:
                replace_span(node_spans[nid].get("lon"), lon)
                replace_span(node_spans[nid].get("lat"), lat)
                modified_nodes.append(int(nid))
        else:
            cloned_node_xml.append('  <node id="%s" lon="%s" lat="%s"/>\n' % (output_id, lon, lat))
    expected_way_refs, changed_way_refs = {}, []
    for (wid, shift), output_id in instance_ids.items():
        old_refs = [nd.get("ref") for nd in ways[wid].findall("nd")]
        refs = [node_instances[(nid, shift)] if nid in nodes else nid for nid in old_refs]
        expected_way_refs[output_id] = refs
        if output_id == wid:
            for index, (before, after) in enumerate(zip(old_refs, refs)):
                if before != after:
                    replace_span(nd_spans.get((wid, index)), after)
                    changed_way_refs.append({"way_id": int(wid), "index": index,
                                             "before": int(before), "after": int(after)})
        else:
            cloned_way_xml.append('  <way id="%s">%s</way>\n' %
                                  (output_id, ''.join('<nd ref="%s"/>' % nid for nid in refs)))
    changed_members = []
    for key, output_id in member_refs.items():
        rid, index = key
        before = relations[rid].findall("member")[index].get("ref")
        if before != output_id:
            replace_span(member_spans.get(key), output_id)
            changed_members.append({"relation_id": int(rid), "index": index,
                                    "before": int(before), "after": int(output_id)})
    inserts = defaultdict(bytes)
    if cloned_node_xml:
        location = positions.get("way", positions.get("relation", positions["root_end"]))
        inserts[location] += ''.join(cloned_node_xml).encode("ascii")
    if cloned_way_xml:
        location = positions.get("relation", positions["root_end"])
        inserts[location] += ''.join(cloned_way_xml).encode("ascii")
    edits.extend((location, location, content) for location, content in inserts.items())
    edited = raw
    for begin, end, value in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        edited = edited[:begin]+value+edited[end:]
    new_root = ET.fromstring(edited)
    new_nodes, new_ways, new_relations = (_index(new_root, kind) for kind in ("node", "way", "relation"))
    if set(new_nodes) != set(expected_nodes) or set(new_ways) != set(expected_way_refs) or set(new_relations) != set(relations):
        raise AlignmentError("Unexpected OSM elements appeared during topology export.")
    max_error = 0.
    for nid, expected in expected_nodes.items():
        node = new_nodes[nid]
        if expected is None:
            continue
        point = transformer.transform(float(node.get("lon")), float(node.get("lat")), errcheck=True)
        error = math.hypot(point[0]-expected[0], point[1]-expected[1])
        if not math.isfinite(error) or error > 1e-5:
            raise AlignmentError("A corrected node failed its projection roundtrip.")
        max_error = max(max_error, error)
    # Verify semantic identity in addition to the lossless span replacement.
    for nid, before in nodes.items():
        after = new_nodes[nid]
        if ({k:v for k,v in before.attrib.items() if k not in {"lat", "lon"}}
                != {k:v for k,v in after.attrib.items() if k not in {"lat", "lon"}}
                or _tags(before) != _tags(after)):
            raise AlignmentError("An original node's metadata changed.")
        if original_node_shift[nid] == ZERO and (before.get("lon"), before.get("lat")) != (after.get("lon"), after.get("lat")):
            raise AlignmentError("An unselected node changed.")
    for wid, refs in expected_way_refs.items():
        after = new_ways[wid]
        if [nd.get("ref") for nd in after.findall("nd")] != refs:
            raise AlignmentError("Unexpected way reference changes.")
        if wid in ways:
            if ways[wid].attrib != after.attrib or _tags(ways[wid]) != _tags(after):
                raise AlignmentError("An original way's identity or tags changed.")
        elif _tags(after):
            raise AlignmentError("Auxiliary boundary ways must not create duplicate surfaces.")
    for rid, before in relations.items():
        after = new_relations[rid]
        if before.attrib != after.attrib or _tags(before) != _tags(after):
            raise AlignmentError("An original relation's identity or tags changed.")
        old_members, new_members = before.findall("member"), after.findall("member")
        if len(old_members) != len(new_members):
            raise AlignmentError("Relation member order or count changed.")
        for index, (old, new) in enumerate(zip(old_members, new_members)):
            expected = dict(old.attrib)
            if (rid,index) in member_refs: expected["ref"] = member_refs[(rid,index)]
            if new.attrib != expected:
                raise AlignmentError("Unexpected relation membership change.")
    affected = {str(by_id[sid]["relation_id"]) for sid in shifts
                if by_id[sid].get("target_type") in {"rough_ring", "surface_ring"}}
    _validate_rough_relations(new_root, affected, grid, projection)
    # Confirm every explicit target translates as a whole and actually moves.
    result_coords = _projector(new_nodes, grid, projection)
    for sid, shift in shifts.items():
        feature = by_id[sid]
        old_points = np.asarray(feature["coords_m"], dtype=float)
        if feature.get("target_type") in {"rough_ring", "surface_ring"}:
            relation = new_relations[str(feature["relation_id"])]
            ring_number = int(sid.rsplit(":",1)[1])
            refs = _rings(relation, new_ways, feature["boundary_role"])[ring_number][0]
        else:
            refs = [nd.get("ref") for nd in new_ways[str(feature["way_id"])].findall("nd")]
        actual = np.asarray(result_coords(refs), dtype=float)
        if actual.shape != old_points.shape or not np.allclose(actual, old_points+shift, rtol=0., atol=1e-5):
            raise AlignmentError("The exported boundary did not retain its reviewed shape and displacement.")
        if np.array_equal(actual, old_points):
            raise AlignmentError("The manual movement is too small to change the saved OSM coordinates.")
    return edited, {"changed_nodes": len(modified_nodes)+len(clone_nodes),
                    "modified_node_ids": modified_nodes, "cloned_nodes": clone_nodes,
                    "cloned_ways": clone_ways, "changed_way_references": changed_way_refs,
                    "changed_relation_references": changed_members,
                    "max_projection_roundtrip_error_m": max_error,
                    "output_counts": {kind:len(new_root.findall(kind)) for kind in ("node","way","relation")}}
