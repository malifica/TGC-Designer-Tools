"""Focused offline course-selection checks; optionally inspect Fairview.osm.

Run: python VERIFY_BETA8_5_COURSE_FILTER.py [--osm path/to/Fairview.osm]
No user's OSM data is bundled with this verifier.
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import overpy
from osm_course_filter import course_filter_key, filter_osm_course, is_environment_feature, is_golf_feature, is_golf_only


COURSE_FILTER_VERIFIER_VERSION = "TGC_BETA8_5_COURSE_FILTER_V1"
OSM_FILE = None


class NoNetwork:
    def __init__(self):
        self.calls = 0

    def query(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Course selection must not access the network")


class Map:
    def __init__(self):
        self.elements = []
        self.next_id = 1
        self.coordinates = {}
        self.api = NoNetwork()

    def node(self, x, y, tags=None):
        if tags is None and (x, y) in self.coordinates:
            return self.coordinates[(x, y)]
        item_id = self.next_id
        self.next_id += 1
        self.elements.append(dict(type="node", id=item_id, lon=x, lat=y, tags=dict(tags or {})))
        if tags is None:
            self.coordinates[(x, y)] = item_id
        return item_id

    def way_refs(self, refs, tags=None):
        item_id = self.next_id
        self.next_id += 1
        self.elements.append(dict(type="way", id=item_id, nodes=list(refs), tags=dict(tags or {})))
        return item_id

    def way(self, points, tags=None):
        return self.way_refs([self.node(x, y) for x, y in points], tags)

    def rect(self, x0, y0, x1, y1, tags=None):
        return self.way([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], tags)

    def relation(self, members, tags=None):
        item_id = self.next_id
        self.next_id += 1
        self.elements.append(dict(type="relation", id=item_id, tags=dict(tags or {}),
                                  members=[dict(type=kind, ref=ref, role=role) for kind, ref, role in members]))
        return item_id

    def result(self):
        return overpy.Result.from_json(dict(elements=copy.deepcopy(self.elements)), api=self.api)


def source_snapshot(result):
    return dict(
        nodes=[(n.id, str(n.lat), str(n.lon), dict(n.tags)) for n in result.nodes],
        ways=[(w.id, tuple(w._node_ids), dict(w.tags)) for w in result.ways],
        relations=[(r.id, dict(r.tags), [(type(m).__name__, m.ref, m.role) for m in r.members]) for r in result.relations],
    )


class CourseFilterTests(unittest.TestCase):
    def world(self):
        world = Map()
        first = world.rect(0, 0, 10, 10, {"leisure": "golf_course", "name": "Selected Club"})
        second = world.rect(20, 0, 30, 10, {"leisure": "golf_course", "name": "Other Club"})
        return world, first, second

    def select(self, result, query="Selected"):
        return filter_osm_course(result, query, printf=None)

    def test_blank_identity_and_normalizer(self):
        marker = object()
        self.assertIs(filter_osm_course(marker, " \t "), marker)
        self.assertEqual(course_filter_key("  Straße  "), "strasse")

    def test_blank_import_with_minimal_overpy_stub(self):
        helper = Path(__file__).with_name("osm_course_filter.py")
        code = "import importlib.util,sys,types; sys.modules['overpy']=types.SimpleNamespace(); s=importlib.util.spec_from_file_location('filtered_stub',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); x=object(); assert m.filter_osm_course(x,'') is x; assert m.course_filter_key(' A ')== 'a'"
        result = subprocess.run([sys.executable, "-B", "-c", code, str(helper)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_case_substring_multiple_boundaries_and_repeat(self):
        world, first, second = self.world()
        a = world.rect(1, 1, 2, 2, {"golf": "green"})
        b = world.rect(21, 1, 22, 2, {"golf": "green"})
        raw = world.result()
        selected = self.select(raw, "  lEcTeD cL  ")
        self.assertEqual(selected._tgc_course_filter_report["included_golf_way_ids"], [a])
        self.assertIs(self.select(selected, "LECTED CL"), selected)
        both = self.select(selected, "club")
        self.assertEqual(set(both._tgc_course_filter_report["included_golf_way_ids"]), {a, b})
        self.assertEqual(set(both._tgc_course_filter_report["selected_boundary_way_ids"]), {first, second})

    def test_no_match_reports_available_names_without_source_changes(self):
        world, _, _ = self.world()
        raw = world.result()
        before = source_snapshot(raw)
        with self.assertRaisesRegex(ValueError, "Available course names:.*Other Club.*Selected Club"):
            self.select(raw, "not present")
        self.assertEqual(source_snapshot(raw), before)
        self.assertEqual(world.api.calls, 0)

    def test_nonmutation_cloned_tags_and_bindings(self):
        world, _, _ = self.world()
        way_id = world.rect(1, 1, 2, 2, {"golf": "bunker"})
        raw = world.result()
        before = source_snapshot(raw)
        filtered = self.select(raw)
        self.assertEqual(source_snapshot(raw), before)
        filtered.get_way(way_id).tags["name"] = "only in clone"
        self.assertNotIn("name", raw.get_way(way_id).tags)
        self.assertIs(filtered.get_way(way_id)._result, filtered)
        self.assertIs(raw.get_way(way_id)._result, raw)
        self.assertTrue(all(node._result is filtered for node in filtered.get_way(way_id).get_nodes(resolve_missing=True)))
        json.dumps(filtered._tgc_course_filter_report)

    def test_covers_includes_boundary_touching_but_rejects_crossing(self):
        world, _, _ = self.world()
        touch = world.rect(0, 1, 1, 2, {"golf": "tee"})
        crossing = world.rect(9, 2, 11, 3, {"golf": "fairway"})
        line = world.way([(1, 1), (11, 1)], {"golf": "hole", "ref": "1"})
        filtered = self.select(world.result())
        self.assertEqual(filtered._tgc_course_filter_report["included_golf_way_ids"], [touch])
        self.assertEqual(set(filtered._tgc_course_filter_report["excluded_golf_way_ids"]), {crossing, line})

    def test_environment_is_retained_outside_and_crossing(self):
        world, _, _ = self.world()
        tags = [{"golf": "water_hazard"}, {"golf": "lateral_water_hazard"}, {"golf": "cartpath"},
                {"golf": "path"}, {"golf": "clubhouse"}, {"natural": "wood"}, {"natural": "water"},
                {"waterway": "stream"}, {"building": "yes"}, {"highway": "service"}]
        ids = [world.rect(9, 2, 12, 3, tag) for tag in tags]
        tree = world.node(40, 40, {"natural": "tree"})
        filtered = self.select(world.result())
        for item_id, tag in zip(ids, tags):
            self.assertEqual(filtered.get_way(item_id).tags, tag)
        self.assertEqual(filtered.get_node(tree).tags, {"natural": "tree"})

    def test_mixed_environment_golf_loses_only_cloned_golf_tag(self):
        world, _, _ = self.world()
        tags = {"golf": "rough", "natural": "wood", "name": "Keep this woodland"}
        mixed = world.rect(21, 1, 22, 2, tags)
        raw = world.result()
        filtered = self.select(raw)
        self.assertEqual(filtered.get_way(mixed).tags, {"natural": "wood", "name": "Keep this woodland"})
        self.assertEqual(raw.get_way(mixed).tags, tags)
        self.assertIn(mixed, filtered._tgc_course_filter_report["suppressed_golf_way_ids"])
        self.assertTrue(is_golf_feature(tags))
        self.assertTrue(is_environment_feature(tags))
        self.assertFalse(is_golf_only(tags))

    def test_pins_and_required_coordinate_nodes(self):
        world, _, _ = self.world()
        inside = world.node(2, 2, {"golf": "pin", "ref": "1"})
        outside = world.node(22, 2, {"golf": "pin", "ref": "2"})
        dependency = world.node(24, 2, {"golf": "pin", "ref": "3"})
        other_node = world.node(25, 2)
        road = world.way_refs([dependency, other_node], {"highway": "service"})
        filtered = self.select(world.result())
        self.assertEqual(filtered._tgc_course_filter_report["included_golf_node_ids"], [inside])
        self.assertNotIn(outside, filtered.node_ids)
        self.assertIn(dependency, filtered.node_ids)
        self.assertNotIn("golf", filtered.get_node(dependency).tags)
        self.assertEqual([n.id for n in filtered.get_way(road).get_nodes(True)], [dependency, other_node])

    def test_split_outer_inner_rings_and_multiple_outer_areas(self):
        world = Map()
        outer1 = world.way([(0, 0), (10, 0), (10, 10)])
        outer2 = world.way([(0, 0), (0, 10), (10, 10)])
        inner1 = world.way([(4, 4), (6, 4), (6, 6)])
        inner2 = world.way([(4, 4), (4, 6), (6, 6)])
        outer3 = world.rect(20, 0, 30, 10)
        rel = world.relation([("way", outer2, "outer"), ("way", inner1, "inner"), ("way", outer3, "outer"),
                              ("way", outer1, "outer"), ("way", inner2, "inner")],
                             {"type": "multipolygon", "leisure": "golf_course", "name": "Split Club"})
        kept = world.rect(1, 1, 2, 2, {"golf": "green"})
        second = world.rect(21, 1, 22, 2, {"golf": "tee"})
        hole = world.rect(4.5, 4.5, 5.5, 5.5, {"golf": "green"})
        cross_hole = world.way([(2, 5), (8, 5)], {"golf": "hole"})
        filtered = self.select(world.result(), "split")
        report = filtered._tgc_course_filter_report
        self.assertEqual(set(report["included_golf_way_ids"]), {kept, second})
        self.assertEqual(set(report["excluded_golf_way_ids"]), {hole, cross_hole})
        self.assertEqual(report["selected_boundary_relation_ids"], [rel])
        for member in filtered.get_relation(rel).members:
            self.assertTrue(member.resolve(True).get_nodes(True))

    def test_incomplete_selected_boundary_never_invents_closure(self):
        world, _, _ = self.world()
        world.way([(1, 1), (3, 1), (3, 3), (1, 3)], {"leisure": "golf_course", "name": "Selected Broken"})
        with self.assertRaisesRegex(ValueError, "incomplete.*Available course names"):
            self.select(world.result())

    def test_missing_selected_boundary_nodes_and_invalid_bowtie_raise(self):
        world = Map()
        a, b = world.node(0, 0), world.node(1, 0)
        world.way_refs([a, b, 999999, a], {"leisure": "golf_course", "name": "Missing"})
        with self.assertRaisesRegex(ValueError, "missing node 999999"):
            self.select(world.result(), "missing")
        self.assertEqual(world.api.calls, 0)
        bowtie = Map()
        bowtie.way([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)], {"leisure": "golf_course", "name": "Bowtie"})
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.select(bowtie.result(), "bowtie")

    def test_incomplete_selected_relation_is_an_error(self):
        world = Map()
        outer = world.way([(0, 0), (10, 0), (10, 10)])
        world.relation([("way", outer, "outer")], {"type": "multipolygon", "leisure": "golf_course", "name": "Broken"})
        with self.assertRaisesRegex(ValueError, "fragments are incomplete"):
            self.select(world.result(), "broken")

    def test_incomplete_environment_relation_retained_and_network_disabled(self):
        world, _, _ = self.world()
        relation = world.relation([("way", 987654, "outer")], {"type": "multipolygon", "natural": "water"})
        raw = world.result()
        filtered = self.select(raw)
        self.assertEqual(filtered.get_relation(relation).tags, raw.get_relation(relation).tags)
        with self.assertRaises(overpy.exception.DataIncomplete):
            filtered.get_relation(relation).members[0].resolve(True)
        with self.assertRaises(overpy.exception.DataIncomplete):
            filtered.get_node(876543, resolve_missing=True)
        self.assertEqual(world.api.calls, 0)

    def test_shared_environment_relation_dependency_suppresses_golf(self):
        world, _, _ = self.world()
        outside = world.rect(21, 1, 22, 2, {"golf": "rough"})
        golf_rel = world.relation([("way", outside, "outer")], {"type": "multipolygon", "golf": "rough"})
        water_rel = world.relation([("way", outside, "outer")], {"type": "multipolygon", "natural": "water"})
        raw = world.result()
        filtered = self.select(raw)
        self.assertNotIn(golf_rel, filtered.relation_ids)
        self.assertIn(water_rel, filtered.relation_ids)
        self.assertNotIn("golf", filtered.get_way(outside).tags)
        self.assertEqual(raw.get_way(outside).tags["golf"], "rough")
        self.assertTrue(filtered.get_relation(water_rel).members[0].resolve(True).get_nodes(True))

    def test_excluded_relation_does_not_release_inside_tagged_fragments(self):
        world, _, _ = self.world()
        outer = world.rect(8, 1, 12, 5, {"golf": "rough"})
        inner = world.rect(9, 2, 9.5, 3, {"golf": "green"})
        relation = world.relation([("way", outer, "outer"), ("way", inner, "inner")], {"type": "multipolygon"})
        filtered = self.select(world.result())
        self.assertNotIn(relation, filtered.relation_ids)
        self.assertNotIn(inner, filtered.way_ids)
        self.assertIn(relation, filtered._tgc_course_filter_report["inferred_golf_relation_ids"])

    def test_shared_member_of_kept_golf_relation_remains_legitimate(self):
        world, _, _ = self.world()
        outer = world.rect(8, 1, 12, 5, {"golf": "rough"})
        shared = world.rect(9, 2, 9.5, 3, {"golf": "green"})
        world.relation([("way", outer, "outer"), ("way", shared, "inner")], {"type": "multipolygon", "golf": "rough"})
        kept = world.relation([("way", shared, "outer")], {"type": "multipolygon", "golf": "green"})
        filtered = self.select(world.result())
        self.assertIn(kept, filtered.relation_ids)
        self.assertEqual(filtered.get_way(shared).tags["golf"], "green")

    def test_nested_excluded_golf_relation_retains_only_dependency_semantics(self):
        world, _, _ = self.world()
        outside = world.rect(21, 1, 22, 2, {"golf": "rough"})
        golf_rel = world.relation([("way", outside, "outer")], {"type": "multipolygon", "golf": "rough"})
        env_rel = world.relation([("relation", golf_rel, "outer")], {"type": "multipolygon", "natural": "water"})
        filtered = self.select(world.result())
        self.assertIn(env_rel, filtered.relation_ids)
        self.assertIn(golf_rel, filtered._tgc_course_filter_report["suppressed_golf_relation_ids"])
        self.assertNotIn("golf", filtered.get_relation(golf_rel).tags)
        self.assertNotIn("golf", filtered.get_way(outside).tags)


class ActualFairviewTests(unittest.TestCase):
    def test_actual_fairview_inventory_and_environment(self):
        if OSM_FILE is None:
            self.skipTest("Optional --osm Fairview.osm was not supplied")
        api = NoNetwork()
        raw = overpy.Result.from_xml(Path(OSM_FILE).read_text(encoding="utf-8-sig"), api=api)
        before = source_snapshot(raw)
        selected = filter_osm_course(raw, " FairVIEW ", printf=None)
        report = selected._tgc_course_filter_report
        self.assertEqual(report["golf_way_type_counts"], {"hole": 18, "fairway": 19, "green": 20, "bunker": 55, "tee": 48, "driving_range": 1})
        self.assertEqual(len(report["included_golf_way_ids"]), 161)
        self.assertEqual(len(report["excluded_golf_way_ids"]), 55)
        self.assertEqual(len(report["included_golf_node_ids"]), 18)
        self.assertEqual(len(report["excluded_golf_node_ids"]), 9)
        self.assertEqual(len(selected.ways), 656)
        self.assertEqual(len(selected.relations), 21)
        self.assertEqual(selected.get_way(43386755).tags, raw.get_way(43386755).tags)
        for relation in raw.relations:
            other = selected.get_relation(relation.id)
            self.assertEqual(other.tags, relation.tags)
            self.assertEqual([(m.ref, m.role) for m in other.members], [(m.ref, m.role) for m in relation.members])
        self.assertEqual(source_snapshot(raw), before)
        self.assertEqual(api.calls, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm")
    args, remaining = parser.parse_known_args()
    OSM_FILE = args.osm
    print("Course Name boundary filtering: offline geometry, relations and preservation checks.")
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
