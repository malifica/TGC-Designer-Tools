"""Beta 7 tree-filter switches and read-only OSM notices.

The resolved-shape topology algorithm lives in lidar_tree_topology.
With surface filtering OFF, inspect source topology only for diagnostics. No
candidate list, native surface, source OSM, coordinate frame or mask is changed.
"""

MARKER = "TGC_BETA7_TREE_CONTROLS_V1"


def report_controls(options, printf=print):
    """Report effective switches, including API callers that omit the new keys."""
    printf(
        "LiDAR tree filters: OSM/surfaces=%s; within 50 m=%s; red-mask exclusion=%s." % (
            "ON" if bool(options.get("filter_lidar_trees_surfaces", False)) else "OFF",
            "ON" if bool(options.get("filter_lidar_trees_50m", False)) else "OFF",
            "ON" if bool(options.get("exclude_lidar_trees_red_mask", True)) else "OFF",
        )
    )


def report_osm_notices(osm_context, printf=print):
    """Report source faults without enforcing topology when the switch is OFF.

    Uses the existing source validator, but does not build native exclusion
    regions, island links, or call any candidate eligibility method. Messages
    describe diagnostic outcomes, never a misleading 'all trees disabled'.
    Return values are for diagnostics only, not authorization or filtering.
    """
    if osm_context is None:
        printf("LiDAR OSM/surface tree filter OFF: no surface exclusions applied; no OSM context to inspect.")
        return []
    import lidar_tree_topology

    notices = []
    seen = set()

    def warn(message):
        text = str(message)
        reason = text.strip().rstrip('.')
        for separator in ('; unresolved item ignored', '; source topology ignored',
                          '; unresolved shape ignored', '; complete affected bounds',
                          '; ALL new LiDAR trees', '; trees disabled', '; course processing'):
            if separator in text:
                reason = text.split(separator, 1)[0].strip().rstrip('.')
                break
        if reason in seen:
            return
        seen.add(reason)
        notices.append(reason)
        printf("LiDAR OSM NOTICE (surface filter OFF): %s. Diagnostic only; no trees rejected by this item." % reason)

    try:
        lidar_tree_topology.source_areas(osm_context, warn)
    except Exception as exc:
        # Confine continuation to the optional diagnostic reader, not file writes,
        # terrain generation, projection setup for actual import, or other stages.
        warn("OSM tree-topology inspection unavailable (%s: %s)" %
             (type(exc).__name__, str(exc)[:240]))
    printf("LiDAR OSM/surface tree filter OFF: %d source notice(s); no surface exclusions applied. "
           "The 50 m and red-mask switches remain independent." % len(notices))
    return notices
