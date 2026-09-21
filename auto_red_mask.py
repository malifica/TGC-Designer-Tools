# TGC_AUTO_RED_MASK_V2_MULTIPOLYGON
import math
import cv2
import numpy as np

_AREA_GOLF_TYPES = {
    "green", "tee", "fairway", "bunker", "rough", "driving_range",
    "water_hazard", "lateral_water_hazard", "clubhouse",
}

# Final cleanup is intentionally conservative and internal-only.  One mask
# pixel equals the current processing map scale, so a 2 px minimum eliminates
# single-pixel red slivers without materially changing the selected metric
# Auto Red Mask buffer.  Tiny enclosed red islands under 25 raster pixels are
# also removed; the large exterior red region is never removed by this rule.
_AUTO_RED_MASK_MIN_RED_WIDTH_PX = 2
_AUTO_RED_MASK_MIN_INTERNAL_RED_AREA_PX = 25


def _source_parts(osm_source):
    """Return (ways, relations) from either an Overpass result or a way list."""
    if osm_source is None:
        return [], []
    if hasattr(osm_source, "ways"):
        return list(getattr(osm_source, "ways", []) or []), list(getattr(osm_source, "relations", []) or [])
    return list(osm_source or []), []


def _tags(obj):
    return getattr(obj, "tags", {}) or {}


def _feature_mode_and_width_m(obj):
    tags = _tags(obj)
    golf_type = tags.get("golf")
    natural_type = tags.get("natural")
    waterway_type = tags.get("waterway")
    highway_type = tags.get("highway")
    golf_cart_type = tags.get("golf_cart")
    amenity_type = tags.get("amenity")
    area_tag = str(tags.get("area", "") or "").lower()

    if golf_type == "hole":
        return None, 0.0
    if golf_type in _AREA_GOLF_TYPES:
        return "area", 0.0
    if golf_type == "cartpath":
        return ("area", 0.0) if area_tag == "yes" else ("line", 2.0)
    if golf_type == "path":
        return ("area", 0.0) if area_tag == "yes" else ("line", 1.7)
    if natural_type == "water":
        return "area", 0.0
    if waterway_type is not None:
        return ("area", 0.0) if area_tag == "yes" else ("line", 6.0)
    if highway_type is not None and golf_cart_type not in (None, "no"):
        return ("area", 0.0) if area_tag == "yes" else ("line", 2.0)
    if amenity_type == "parking" and golf_cart_type not in (None, "no"):
        return "area", 0.0
    return None, 0.0


def _feature_signature(obj):
    tags = _tags(obj)
    # Only fields that define the semantic feature handled by this mask.
    return (
        tags.get("golf"),
        tags.get("natural"),
        tags.get("waterway"),
        tags.get("highway"),
        tags.get("golf_cart"),
        tags.get("amenity"),
    )


def _is_water_feature(obj):
    tags = _tags(obj)
    return (
        tags.get("natural") == "water"
        or tags.get("waterway") is not None
        or tags.get("golf") in ("water_hazard", "lateral_water_hazard")
    )


def _get_way_nodes(way):
    try:
        return list(way.get_nodes(resolve_missing=False))
    except Exception:
        try:
            return list(way.get_nodes(resolve_missing=True))
        except Exception:
            return []


def _node_key(node):
    node_id = getattr(node, "id", None)
    if node_id is not None:
        return ("id", int(node_id))
    try:
        return (
            "ll",
            round(float(node.lat), 11),
            round(float(node.lon), 11),
        )
    except Exception:
        return ("obj", id(node))


def _nodes_to_pixels(nodes, pc, image_scale, x_offset=0.0, y_offset=0.0):
    pts = []
    keys = []
    for node in nodes:
        try:
            row, col = pc.latlonToCV2(
                node.lat, node.lon, image_scale, x_offset, y_offset
            )
        except Exception:
            continue
        keys.append(_node_key(node))
        pts.append((float(col), float(row)))
    return keys, pts


def _way_fragment(way, pc, image_scale, x_offset=0.0, y_offset=0.0):
    nodes = _get_way_nodes(way)
    if len(nodes) < 2:
        return None
    keys, pts = _nodes_to_pixels(
        nodes, pc, image_scale, x_offset=x_offset, y_offset=y_offset
    )
    if len(keys) < 2 or len(pts) < 2:
        return None

    # Drop consecutive duplicate nodes; these confuse ring stitching and add no geometry.
    out_keys = [keys[0]]
    out_pts = [pts[0]]
    for key, pt in zip(keys[1:], pts[1:]):
        if key == out_keys[-1]:
            continue
        out_keys.append(key)
        out_pts.append(pt)

    if len(out_keys) < 2:
        return None
    return {"keys": out_keys, "pts": out_pts}


def _way_points_pixels(way, pc, image_scale, x_offset=0.0, y_offset=0.0):
    frag = _way_fragment(
        way, pc, image_scale, x_offset=x_offset, y_offset=y_offset
    )
    if frag is None:
        return None
    return np.asarray(frag["pts"], dtype=np.float64)


def _way_is_closed(way):
    nodes = _get_way_nodes(way)
    if len(nodes) < 3:
        return False
    return _node_key(nodes[0]) == _node_key(nodes[-1])


def _stitch_fragments(fragments):
    """Stitch unordered/reversed OSM way fragments into closed rings by endpoint node."""
    remaining = [
        {"keys": list(f["keys"]), "pts": list(f["pts"])}
        for f in fragments
        if f is not None and len(f["keys"]) >= 2
    ]
    rings = []
    incomplete = 0

    while remaining:
        chain = remaining.pop(0)
        keys = chain["keys"]
        pts = chain["pts"]

        # A single closed way is already a complete ring.
        if keys[0] == keys[-1]:
            if len(keys) >= 4:
                rings.append(np.asarray(pts, dtype=np.float64))
            continue

        progress = True
        while progress and keys[0] != keys[-1] and remaining:
            progress = False
            for idx, frag in enumerate(remaining):
                fk = frag["keys"]
                fp = frag["pts"]

                if keys[-1] == fk[0]:
                    keys.extend(fk[1:])
                    pts.extend(fp[1:])
                elif keys[-1] == fk[-1]:
                    rk = list(reversed(fk))
                    rp = list(reversed(fp))
                    keys.extend(rk[1:])
                    pts.extend(rp[1:])
                elif keys[0] == fk[-1]:
                    keys = fk[:-1] + keys
                    pts = fp[:-1] + pts
                elif keys[0] == fk[0]:
                    rk = list(reversed(fk))
                    rp = list(reversed(fp))
                    keys = rk[:-1] + keys
                    pts = rp[:-1] + pts
                else:
                    continue

                remaining.pop(idx)
                progress = True
                break

        if keys[0] == keys[-1] and len(keys) >= 4:
            rings.append(np.asarray(pts, dtype=np.float64))
        else:
            incomplete += 1

    return rings, incomplete


def _relation_rings(rel, way_lookup, pc, image_scale, x_offset=0.0, y_offset=0.0):
    outer_fragments = []
    inner_fragments = []
    member_info = []

    for member in getattr(rel, "members", []) or []:
        ref = getattr(member, "ref", None)
        if ref is None:
            continue
        way = way_lookup.get(ref)
        if way is None:
            # RelationNode / RelationRelation / missing way reference.
            continue

        role = str(getattr(member, "role", "") or "").strip().lower()
        # Empty role is conventionally treated as outer for legacy multipolygons.
        is_inner = role == "inner"
        is_outer = role in ("", "outer")
        if not is_inner and not is_outer:
            continue

        # Record relation membership even if geometry is incomplete so a broken
        # open fragment is never later fillPoly'd as a standalone fake area.
        member_info.append((int(ref), role, way))

        frag = _way_fragment(
            way,
            pc,
            image_scale,
            x_offset=x_offset,
            y_offset=y_offset,
        )
        if frag is None:
            continue

        if is_inner:
            inner_fragments.append(frag)
        else:
            outer_fragments.append(frag)

    outers, outer_incomplete = _stitch_fragments(outer_fragments)
    inners, inner_incomplete = _stitch_fragments(inner_fragments)
    return outers, inners, member_info, outer_incomplete, inner_incomplete


def _poly_i32(ring):
    return np.rint(np.asarray(ring, dtype=np.float64)).astype(np.int32).reshape((-1, 1, 2))


def _rasterize_multipolygon(outers, inners, shape):
    """Rasterize union(outers - contained inners) without one outer erasing another."""
    h, w = shape
    relation_mask = np.zeros((h, w), dtype=np.uint8)
    if not outers:
        return relation_mask

    outer_polys = [_poly_i32(r) for r in outers if len(r) >= 4]
    inner_polys = [_poly_i32(r) for r in inners if len(r) >= 4]

    for outer in outer_polys:
        comp = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(comp, [outer], 255)

        # Subtract only inner rings that belong inside this outer component.
        for inner in inner_polys:
            p = inner.reshape((-1, 2))
            if len(p) == 0:
                continue
            # Mean point is adequate for valid OSM inner rings; fall back to first point.
            probe = tuple(np.mean(p.astype(np.float64), axis=0).tolist())
            inside = cv2.pointPolygonTest(outer, probe, False)
            if inside < 0:
                probe = (float(p[0, 0]), float(p[0, 1]))
                inside = cv2.pointPolygonTest(outer, probe, False)
            if inside >= 0:
                cv2.fillPoly(comp, [inner], 0)

        cv2.bitwise_or(relation_mask, comp, dst=relation_mask)

    return relation_mask


def _standalone_member_allowed(way, member_context):
    """Avoid filling multipolygon fragments as independent polygons.

    A relation inner can still be a genuine independently tagged golf feature
    (for example rough inside a fairway); allow that only when it is a closed
    area with its own different semantics. Lines are also independent features.
    """
    contexts = member_context.get(getattr(way, "id", None))
    if not contexts:
        return True

    mode, _width = _feature_mode_and_width_m(way)
    if mode is None:
        return False
    if mode == "line":
        return True
    if not _way_is_closed(way):
        return False

    way_sig = _feature_signature(way)
    for role, rel_sig in contexts:
        if role == "inner" and way_sig != rel_sig:
            return True
        if way_sig != rel_sig and any(v is not None for v in way_sig):
            return True
    return False


def _cleanup_red_mask(outside):
    """Apply conservative post-buffer cleanup to the boolean red mask.

    Rules:
      * remove red structures that cannot survive a 2x2 opening (1 px slivers)
      * remove enclosed red connected-components smaller than 25 raster pixels
      * never remove the border-connected exterior merely because of its area

    Returns (cleaned_outside, width_removed_px, islands_removed,
    island_pixels_removed).
    """
    red = np.where(outside, 255, 0).astype(np.uint8)

    width_removed_px = 0
    if _AUTO_RED_MASK_MIN_RED_WIDTH_PX > 1 and np.any(red):
        # Preserve normal >=3 px bodies with a symmetric 3x3 opening, then OR
        # back every original pixel that participates in a fully-red 2x2 block.
        # This keeps genuine 2-pixel-wide strips intact while dropping 1-pixel
        # hairs/slivers, without the one-pixel shift caused by an even 2x2
        # morphology kernel.
        original_red = red > 0
        opened_3 = cv2.morphologyEx(
            red,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            iterations=1,
        ) > 0

        participates_in_2x2 = np.zeros_like(original_red)
        if original_red.shape[0] >= 2 and original_red.shape[1] >= 2:
            block_2x2 = (
                original_red[:-1, :-1]
                & original_red[1:, :-1]
                & original_red[:-1, 1:]
                & original_red[1:, 1:]
            )
            yy, xx = np.nonzero(block_2x2)
            for dy in (0, 1):
                for dx in (0, 1):
                    participates_in_2x2[yy + dy, xx + dx] = True

        min_width_red = opened_3 | participates_in_2x2
        width_removed_px = max(
            0,
            int(np.count_nonzero(original_red)) -
            int(np.count_nonzero(min_width_red)),
        )
        red = np.where(min_width_red, 255, 0).astype(np.uint8)

    islands_removed = 0
    island_pixels_removed = 0
    if np.any(red):
        component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            (red > 0).astype(np.uint8),
            connectivity=8,
        )
        height, width = red.shape[:2]
        for label_id in range(1, component_count):
            x = int(stats[label_id, cv2.CC_STAT_LEFT])
            y = int(stats[label_id, cv2.CC_STAT_TOP])
            comp_w = int(stats[label_id, cv2.CC_STAT_WIDTH])
            comp_h = int(stats[label_id, cv2.CC_STAT_HEIGHT])
            area = int(stats[label_id, cv2.CC_STAT_AREA])

            touches_border = (
                x <= 0
                or y <= 0
                or x + comp_w >= width
                or y + comp_h >= height
            )
            if (
                not touches_border
                and area < _AUTO_RED_MASK_MIN_INTERNAL_RED_AREA_PX
            ):
                red[labels == label_id] = 0
                islands_removed += 1
                island_pixels_removed += area

    return red > 0, width_removed_px, islands_removed, island_pixels_removed


def apply_auto_red_mask(osm_source, image_rgb, pc, image_scale, buffer_m=5.0,
                        x_offset=0.0, y_offset=0.0, printf=print):
    """Paint red outside golf/cart/water features plus a metric edge buffer.

    V2 understands OSM multipolygon relations. Outer-member way fragments are
    stitched into closed rings and inner rings are subtracted before buffering.
    The function remains backward-compatible with callers that pass only ways.
    """
    try:
        scale = float(image_scale)
    except Exception:
        scale = 0.0
    if not math.isfinite(scale) or scale <= 0.0:
        printf("Auto Red Mask: invalid image scale; leaving mask unchanged.")
        return image_rgb

    try:
        buffer_m = max(0.0, float(buffer_m))
    except Exception:
        buffer_m = 5.0

    ways, relations = _source_parts(osm_source)
    way_lookup = {getattr(way, "id", None): way for way in ways}

    h, w = image_rgb.shape[:2]
    core = np.zeros((h, w), dtype=np.uint8)
    relation_water = np.zeros((h, w), dtype=np.uint8)
    # Visualization-only fills for relation-based playable areas.
    # Processing semantics still depend only on red (remove) and blue (water).
    relation_fairway = np.zeros((h, w), dtype=np.uint8)
    relation_rough = np.zeros((h, w), dtype=np.uint8)

    area_count = 0
    line_count = 0
    relation_count = 0
    relation_outer_count = 0
    relation_inner_count = 0
    incomplete_relation_rings = 0
    member_context = {}

    # First build eligible multipolygon relations. This must happen before the
    # standalone way pass so open relation fragments are never fillPoly'd as
    # fake polygons with an implicit closing chord.
    for rel in relations:
        tags = _tags(rel)
        if str(tags.get("type", "") or "").lower() != "multipolygon":
            continue

        mode, _nominal_width_m = _feature_mode_and_width_m(rel)
        if mode != "area":
            continue

        outers, inners, members, outer_bad, inner_bad = _relation_rings(
            rel,
            way_lookup,
            pc,
            scale,
            x_offset=x_offset,
            y_offset=y_offset,
        )

        rel_sig = _feature_signature(rel)
        for way_id, role, _way in members:
            member_context.setdefault(way_id, []).append((role, rel_sig))

        if not outers:
            incomplete_relation_rings += outer_bad + inner_bad
            printf(
                "Auto Red Mask: multipolygon relation " +
                str(getattr(rel, "id", "?")) +
                " has no complete outer ring; skipped."
            )
            continue

        rel_mask = _rasterize_multipolygon(outers, inners, (h, w))
        if not np.any(rel_mask):
            continue

        cv2.bitwise_or(core, rel_mask, dst=core)
        golf_type = tags.get("golf")
        if golf_type == "fairway":
            cv2.bitwise_or(relation_fairway, rel_mask, dst=relation_fairway)
        elif golf_type == "rough":
            cv2.bitwise_or(relation_rough, rel_mask, dst=relation_rough)
        if _is_water_feature(rel):
            cv2.bitwise_or(relation_water, rel_mask, dst=relation_water)

        relation_count += 1
        relation_outer_count += len(outers)
        relation_inner_count += len(inners)
        incomplete_relation_rings += outer_bad + inner_bad

    # Standalone ways and independently tagged inner features.
    for way in ways:
        if not _standalone_member_allowed(way, member_context):
            continue

        mode, nominal_width_m = _feature_mode_and_width_m(way)
        if mode is None:
            continue
        pts = _way_points_pixels(
            way, pc, scale, x_offset=x_offset, y_offset=y_offset
        )
        if pts is None:
            continue
        pts_i = np.rint(pts).astype(np.int32).reshape((-1, 1, 2))

        if mode == "area":
            if len(pts_i) < 3:
                continue
            # A standalone area should be closed. Non-closed members of an
            # eligible relation were already excluded above.
            cv2.fillPoly(core, [pts_i], 255)
            if _is_water_feature(way):
                cv2.fillPoly(relation_water, [pts_i], 255)
            area_count += 1
        else:
            thickness_px = max(
                1,
                int(math.ceil(max(nominal_width_m, scale) / scale)),
            )
            cv2.polylines(
                core,
                [pts_i],
                False,
                255,
                thickness=thickness_px,
                lineType=cv2.LINE_8,
            )
            line_count += 1

    # Preserve already-rendered blue water. This covers normal way-based water;
    # relation_water above additionally covers multipolygon water whose member
    # ways carry no independent water tag.
    blue_existing = np.zeros((h, w), dtype=bool)
    try:
        arr = np.asarray(image_rgb)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            if np.issubdtype(arr.dtype, np.floating):
                blue_existing = (
                    (arr[:, :, 0] < 0.10)
                    & (arr[:, :, 1] < 0.10)
                    & (arr[:, :, 2] > 0.80)
                )
            else:
                blue_existing = (
                    (arr[:, :, 0] < 26)
                    & (arr[:, :, 1] < 26)
                    & (arr[:, :, 2] > 204)
                )
            core[blue_existing] = 255
    except Exception:
        pass

    if not np.any(core):
        printf(
            "Auto Red Mask: no eligible golf/cart/water features were "
            "rasterized; leaving mask unchanged."
        )
        return image_rgb

    buffer_px = int(math.ceil(buffer_m / scale))
    keep = core
    if buffer_px > 0:
        k = 2 * buffer_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        keep = cv2.dilate(core, kernel, iterations=1)

    result = np.array(image_rgb, copy=True)
    outside = keep == 0
    (
        outside,
        thin_red_pixels_removed,
        small_red_islands_removed,
        small_red_island_pixels_removed,
    ) = _cleanup_red_mask(outside)

    if (
        thin_red_pixels_removed
        or small_red_islands_removed
        or small_red_island_pixels_removed
    ):
        printf(
            "Auto Red Mask cleanup: 2 px minimum red width removed " +
            str(thin_red_pixels_removed) + " thin red pixel(s); removed " +
            str(small_red_islands_removed) + " enclosed red island(s) totaling " +
            str(small_red_island_pixels_removed) +
            " pixel(s) below the 25-pixel area minimum."
        )

    # Multipolygon relation geometry is not painted by the legacy way-only
    # OSM preview.  Fill relation fairways/roughs here so mask.png shows the
    # actual compound playable area rather than only its member outlines.
    # These greens are visualization-only: infill processing still keys only
    # on RED (remove) and BLUE (water).
    relation_fairway_px = (relation_fairway > 0) & (~blue_existing)
    relation_rough_px = (relation_rough > 0) & (~blue_existing)

    if np.issubdtype(result.dtype, np.floating):
        result[outside, 0] = 1.0
        result[outside, 1] = 0.0
        result[outside, 2] = 0.0

        # Match the existing TGC preview fairway green.
        result[relation_fairway_px, 0] = 0.0
        result[relation_fairway_px, 1] = 0.75
        result[relation_fairway_px, 2] = 0.20
        # Slightly darker rough green so compound rough is distinguishable.
        result[relation_rough_px, 0] = 0.0
        result[relation_rough_px, 1] = 0.55
        result[relation_rough_px, 2] = 0.15

        # Pure blue for relation water that the legacy way-only preview never drew.
        relation_blue = relation_water > 0
        result[relation_blue, 0] = 0.0
        result[relation_blue, 1] = 0.0
        result[relation_blue, 2] = 1.0
    else:
        result[outside, 0] = 255
        result[outside, 1] = 0
        result[outside, 2] = 0

        result[relation_fairway_px, 0] = 0
        result[relation_fairway_px, 1] = 191
        result[relation_fairway_px, 2] = 51
        result[relation_rough_px, 0] = 0
        result[relation_rough_px, 1] = 140
        result[relation_rough_px, 2] = 38

        relation_blue = relation_water > 0
        result[relation_blue, 0] = 0
        result[relation_blue, 1] = 0
        result[relation_blue, 2] = 255

    total = int(outside.size)
    kept = total - int(np.count_nonzero(outside))
    pct = 100.0 * kept / total if total else 0.0

    printf(
        "Auto Red Mask V2: +" + str(round(buffer_m, 2)) + " m; " +
        str(area_count) + " standalone area feature(s), " +
        str(line_count) + " line feature(s), " +
        str(relation_count) + " multipolygon relation(s) [" +
        str(relation_outer_count) + " outer ring(s), " +
        str(relation_inner_count) + " inner ring(s)]; kept " +
        str(round(pct, 1)) + "% of raster."
    )
    fairway_relations = int(np.count_nonzero(relation_fairway))
    rough_relations = int(np.count_nonzero(relation_rough))
    if fairway_relations or rough_relations:
        printf(
            "Auto Red Mask V2A preview: compound fairway/rough areas filled green "
            "in mask.png (fairway bright, rough dark)."
        )

    if incomplete_relation_rings:
        printf(
            "Auto Red Mask V2: warning: " +
            str(incomplete_relation_rings) +
            " multipolygon ring chain(s) were incomplete and were not filled."
        )

    return result
