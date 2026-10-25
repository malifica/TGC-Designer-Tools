"""DEM preview/mask reporting and non-destructive OSM feature selection.

Only a temporary rendering view is selected. Original OSM results/files remain
unchanged for final course import, tree topology, CFS placement and extent logic.
No geometry is clipped, simplified, reprojected differently or reclassified here.
"""
import time
from types import SimpleNamespace
import cv2


def relevant_tags(tags):
    tags = tags or {}
    # Roads include highway=residential. That is NOT a residential LANDUSE area.
    # Golf with unusual tags is retained so the established diagnostics can see it.
    if tags.get('golf') is not None or tags.get('highway') is not None:
        return True
    if tags.get('natural') == 'water' or tags.get('waterway') is not None:
        return True
    return tags.get('leisure') in ('golf_course', 'driving_range')


def select_render_features(result):
    """Keep golf/roads/water and ALL members needed for complete selected rings.

    Standalone coastline, residential landuse and regional context are not
    rendering candidates. An otherwise irrelevant way needed as an inner/outer
    boundary remains; geometry dependency is not the same as a surface feature.
    The original overpy way/node objects are reused, preserving node resolution.
    """
    if result is None or not hasattr(result, 'ways'):
        return result, None
    ways = list(result.ways or ())
    relations = list(getattr(result, 'relations', ()) or ())
    selected = [r for r in relations
                if (getattr(r, 'tags', {}) or {}).get('type', '').lower() == 'multipolygon'
                and relevant_tags(getattr(r, 'tags', {}))]
    refs = set()
    for rel in selected:
        for member in getattr(rel, 'members', ()) or ():
            # Native overpy class names; compatible with existing local test adapters.
            name = member.__class__.__name__
            if name in ('RelationNode', 'RelationRelation'):
                continue
            if str(getattr(member, 'role', '') or '').strip().lower() not in ('', 'outer', 'inner'):
                continue
            ref = getattr(member, 'ref', None)
            if ref is not None:
                refs.add(ref)
    keep = [w for w in ways if relevant_tags(getattr(w, 'tags', {})) or w.id in refs]
    view = SimpleNamespace(ways=keep, relations=selected,
                           nodes=getattr(result, 'nodes', ()))
    summary = dict(total_ways=len(ways), kept_ways=len(keep),
                   total_relations=len(relations), kept_relations=len(selected),
                   skipped_coastline=sum((getattr(w, 'tags', {}) or {}).get('natural') == 'coastline'
                                         for w in ways if w not in keep),
                   skipped_residential=sum((getattr(w, 'tags', {}) or {}).get('landuse') == 'residential'
                                           for w in ways if w not in keep))
    return view, summary


class _Reporter:
    def __init__(self, printf, has_mask):
        self.printf = printf
        self.start = time.perf_counter()
        self.progress = None
        # Integrate the previously installed status panel, but do not require
        # that optional update or change its files.
        try:
            from tgc_output_progress import OutputProgress
        except ImportError:
            OutputProgress = None
        if OutputProgress is not None:
            self.progress = OutputProgress(printf, 'DEM preview/mask')
        self.step(0, 'Starting DEM preview/mask; Auto Red Mask ' + ('ON' if has_mask else 'OFF'))

    def step(self, percent, text):
        self.printf('DEM preview/mask [%d%% phase] %s (%.2f s elapsed)' %
                    (percent, text, time.perf_counter()-self.start))
        if self.progress is not None:
            self.progress.stage(percent, text)

    def finish(self):
        text = 'DEM preview/mask complete in %.2f s' % (time.perf_counter()-self.start)
        self.printf(text)
        if self.progress is not None:
            self.progress.finish('DEM preview/mask ready')


def build_mask(dem_region, pc, image_scale, osm_result, *, normalize, draw,
               auto_mask, auto_red_mask_enabled=False,
               auto_red_mask_buffer_m=5.0, x_offset=0.0, y_offset=0.0,
               printf=print):
    report = _Reporter(printf, auto_red_mask_enabled)
    report.step(5, 'Normalizing DEM preview')
    image = cv2.cvtColor(normalize(dem_region), cv2.COLOR_GRAY2RGB)
    if osm_result:
        view, info = select_render_features(osm_result)
        if info is not None:
            printf('DEM OSM render selection: %(kept_ways)d/%(total_ways)d ways, '
                   '%(kept_relations)d/%(total_relations)d multipolygon relations; '
                   'roads/streams and ring members retained; standalone coastline '
                   'and residential landuse ignored.' % info)
        report.step(15, 'Rendering golf, water and relevant OSM geometry; coordinate transforms reused')
        image = draw(view, image, pc, image_scale, x_offset=x_offset,
                     y_offset=y_offset, printf=printf)
        printf('OSM features rendered into DEM preview/mask.')
        report.step(70, 'OSM overlay complete')
        if auto_red_mask_enabled:
            report.step(75, 'Building Auto Red Mask with unchanged buffer and cleanup rules')
            image = auto_mask(view, image, pc, image_scale,
                              buffer_m=auto_red_mask_buffer_m,
                              x_offset=x_offset, y_offset=y_offset, printf=printf)
            report.step(95, 'Auto Red Mask complete')
    elif auto_red_mask_enabled:
        printf('Auto Red Mask requested, but no OSM result is available; leaving DEM mask unchanged.')
    report.finish()
    return image
