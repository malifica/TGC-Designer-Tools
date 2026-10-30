"""Exercise exported relation edits through the existing OSM consumers.

Uses analytical terrain and private temporary files. This checks actual OSM
parsing, CFS projection, hole masks/imagery, tree topology, and native spline
import; it does not run Windows, PyInstaller, or the 2K25 game.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pyproj

from GeoPointCloud import GeoPointCloud
import OSMTGC
from auto_red_mask import _relation_rings, _rasterize_multipolygon
import lidar_tree_topology
import osm_alignment_viewer as viewer
import osm_mask_alignment as mask
from tgc_cfs_display import importer_transformer
import tgc_local_alignment as engine


def rectangle(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], dtype=float)


def fixture(folder, kind="bunker", shared=False):
    """A feature/hole, an unrelated hole, and an untagged rough outer."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    projection = pyproj.Proj("EPSG:32611")
    transformer = importer_transformer(projection)
    min_x, min_y, resolution, size = 575641., 5497180., 2., 128
    lon0, lat0 = transformer.transform(min_x, min_y, direction="INVERSE")
    grid = dict(version=1, rows=size, cols=size, resolution=resolution,
                min_x=min_x, min_y=min_y, max_x=min_x+size*resolution,
                max_y=min_y+size*resolution, crs_wkt=projection.crs.to_wkt(),
                horizontal_epsg=32611, origin_semantics="southwest_cell_edge",
                row_order="south_up_internal", xy_units="meters",
                lower_left_latlon=[lat0, lon0])
    data = dict(heightmap=np.full((size, size), 100., dtype=float),
                projection=projection, master_grid=grid, image_scale=resolution,
                origin=(lat0, lon0))
    nudge = (1.5, -.5)
    rings = {101: rectangle(50, 50, 70, 70), 102: rectangle(20, 20, 200, 200),
             103: rectangle(140, 50, 160, 70)}
    if shared:
        rings = {101: rectangle(50, 50, 70, 70), 102: rectangle(20, 20, 50, 50)}
    root = ET.Element("osm", version="0.6", generator="Relation consumer verifier")
    references, used, next_id = {}, {}, 1
    for wid, points in rings.items():
        refs = []
        for point in points:
            key = tuple(point)
            if key not in used:
                lon, lat = transformer.transform(point[0]+min_x, point[1]+min_y, direction="INVERSE")
                used[key] = next_id
                ET.SubElement(root, "node", id=str(next_id), lon=f"{lon:.12f}", lat=f"{lat:.12f}")
                next_id += 1
            refs.append(used[key])
        references[wid] = refs
    for wid, refs in references.items():
        way = ET.SubElement(root, "way", id=str(wid))
        for ref in refs:
            ET.SubElement(way, "nd", ref=str(ref))
        if wid == 101:
            ET.SubElement(way, "tag", k="golf", v=kind)
            ET.SubElement(way, "tag", k="name", v="Independent consumer fixture")
        elif shared:
            ET.SubElement(way, "tag", k="golf", v="rough")
    if not shared:
        relation = ET.SubElement(root, "relation", id="303")
        for wid, role in ((102, "outer"), (101, "inner"), (103, "inner")):
            ET.SubElement(relation, "member", type="way", ref=str(wid), role=role)
        ET.SubElement(relation, "tag", k="type", v="multipolygon")
        ET.SubElement(relation, "tag", k="golf", v="rough")
    source = folder / "source.osm"
    ET.ElementTree(root).write(source, encoding="utf-8", xml_declaration=True)
    np.save(folder / "heightmap.npy", data)
    return data, source, nudge, rings


class RelationConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tgc-relation-consumers-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def export(self, data, source, nudge, offsets, filename="corrected.osm"):
        report = engine.analyze(data, source, *nudge)
        available = {str(f.get("selection_id", f.get("way_id"))) for f in report["features"]}
        self.assertTrue(set(offsets).issubset(available), (set(offsets), available))
        before = source.read_bytes()
        result = engine.apply_reviewed(report, list(offsets), source.parent / filename,
            current_data=data, current_nudge=nudge, current_osm_file=source,
            manual_overrides={sid: dict(east_m=xy[0], north_m=xy[1]) for sid, xy in offsets.items()})
        self.assertEqual(source.read_bytes(), before)
        return Path(result["output"])

    def consumers(self, data, path, nudge, kind, expected, relation=True):
        parsed = mask._load_complete_osm(path)
        grid, projection = data["master_grid"], data["projection"]
        transform = importer_transformer(projection)
        ways = {w.id: w for w in parsed.ways}

        def xy(way):
            nodes = way.get_nodes(resolve_missing=False)
            projected = np.column_stack(transform.transform(
                [float(n.lon) for n in nodes], [float(n.lat) for n in nodes]))
            return projected-[grid["min_x"], grid["min_y"]]

        np.testing.assert_allclose(xy(ways[101]), expected["feature"], atol=1e-5)
        hole_way, outer_way = None, ways[102]
        if relation:
            self.assertEqual(len(parsed.relations), 1)
            rel = parsed.relations[0]
            self.assertEqual(rel.id, 303)
            self.assertEqual(rel.tags, {"type": "multipolygon", "golf": "rough"})
            self.assertEqual([(m.role, m.__class__.__name__) for m in rel.members],
                             [("outer", "RelationWay"), ("inner", "RelationWay"), ("inner", "RelationWay")])
            outer_way = ways[rel.members[0].ref]
            hole_way = ways[rel.members[1].ref]
            np.testing.assert_allclose(xy(hole_way), expected["hole"], atol=1e-5)
            np.testing.assert_allclose(xy(ways[rel.members[2].ref]), rectangle(140, 50, 160, 70), atol=1e-5)
            for way in parsed.ways:
                if way.id < 0:
                    self.assertEqual(way.tags, {}, "A cloned cutout must not create a second feature")
        np.testing.assert_allclose(xy(outer_way), expected["outer"], atol=1e-5)

        overlays = viewer._collect_overlay_features(parsed, projection, grid, printf=lambda *_: None)
        by_label = {f["label"]: f for f in overlays}
        np.testing.assert_allclose(np.asarray(by_label["101"]["points"])*grid["resolution"]+nudge,
                                   expected["feature"]+nudge, atol=1e-5)
        outer_label = "303:"+str(outer_way.id) if relation else "102"
        np.testing.assert_allclose(np.asarray(by_label[outer_label]["points"])*grid["resolution"]+nudge,
                                   expected["outer"]+nudge, atol=1e-5)
        if relation and hole_way.id != 101:
            label = "303:"+str(hole_way.id)
            self.assertIn(label, by_label)
            self.assertEqual(by_label[label]["dash"], (4, 3))
            np.testing.assert_allclose(np.asarray(by_label[label]["points"])*grid["resolution"]+nudge,
                                       expected["hole"]+nudge, atol=1e-5)

        pc = GeoPointCloud()
        pc.proj, pc.origin = projection, (grid["min_x"], grid["min_y"])
        pc.xmin = pc.ymin = 0.
        pc.xmax = pc.ymax = pc.width = pc.height = 256.
        captured = {"bunker": [], "tee": [], "rough": []}
        with ExitStack() as stack:
            for name, target in (("newBunker", "bunker"), ("newTeeBox", "tee"), ("newRough", "rough")):
                original = getattr(OSMTGC, name)
                def capture(points, *args, _original=original, _target=target, **kwargs):
                    captured[_target].append(np.array([[x+128., z+128.] for x, _, z in points]))
                    return _original(points, *args, **kwargs)
                stack.enter_context(patch.object(OSMTGC, name, capture))
            course = {}
            OSMTGC.addOSMToTGC(course, pc, parsed, x_offset=nudge[0], y_offset=nudge[1],
                options_dict={"tree": False, "optimize_osm_spline_points": False},
                printf=lambda *_: None, course_version=25, resolve_missing_nodes=False)
        self.assertEqual({k: len(v) for k, v in captured.items()},
                         {"bunker": int(kind == "bunker"), "tee": int(kind == "tee"), "rough": 1})
        self.assertEqual(len(course["surfaceSplines2"]), 2)
        np.testing.assert_allclose(captured[kind][0], expected["feature"]+nudge, atol=1e-5)
        np.testing.assert_allclose(captured["rough"][0], expected["outer"]+nudge, atol=1e-5)

        if relation:
            projector = mask._FastGridProjector(projection, (grid["min_x"], grid["min_y"]))
            outers, inners, _, outer_bad, inner_bad = _relation_rings(
                parsed.relations[0], ways, projector, grid["resolution"], *nudge)
            self.assertEqual((len(outers), len(inners), outer_bad, inner_bad), (1, 2, 0, 0))
            rough_pixels = _rasterize_multipolygon(outers, inners, data["heightmap"].shape)
            image = np.full((*data["heightmap"].shape, 3), .123, dtype=np.float32)
            image = OSMTGC.addOSMToImage(parsed, image, projector, grid["resolution"],
                                      x_offset=nudge[0], y_offset=nudge[1], printf=lambda *_: None)
            from shapely.geometry import Point, Polygon
            outer, hole = Polygon(expected["outer"]), Polygon(expected["hole"])
            feature, other = Polygon(expected["feature"]), Polygon(rectangle(140, 50, 160, 70))
            points = [(60., 60.), tuple(np.mean(expected["hole"][:-1], axis=0)),
                      tuple(np.mean(expected["feature"][:-1], axis=0)), (150., 60.),
                      (22., 100.), (205., 100.), (100., 150.)]
            for point in points:
                p = Point(point)
                row, col = (int((point[1]+nudge[1])/grid["resolution"]),
                            int((point[0]+nudge[0])/grid["resolution"]))
                is_rough = outer.contains(p) and not hole.covers(p) and not other.covers(p)
                self.assertEqual(bool(rough_pixels[row, col]), is_rough, (point, path))
                color = ((.85, .85, .7) if kind == "bunker" else (0., .8, 0.)) if feature.contains(p) else (
                    (0., .55, .15) if is_rough else (.123, .123, .123))
                np.testing.assert_allclose(image[row, col], color, atol=1e-6, err_msg=str(point))
            warnings = []
            areas = lidar_tree_topology.source_areas((parsed, pc, *nudge, {}), warnings.append)
            self.assertFalse(warnings, warnings)
            self.assertEqual(len([a for a in areas if a.kind == "rough"]), 1)
        return parsed

    def scenario(self, kind, offsets, feature_shift=(0., 0.), hole_shift=(0., 0.), outer_shift=(0., 0.)):
        data, source, nudge, rings = fixture(self.folder / kind, kind)
        output = self.export(data, source, nudge, offsets)
        return data, output, nudge, self.consumers(data, output, nudge, kind,
            dict(feature=rings[101]+feature_shift, hole=rings[101]+hole_shift, outer=rings[102]+outer_shift))

    def test_feature_only_keeps_rough_cutout_and_native_surface_count(self):
        for kind in ("bunker", "tee"):
            with self.subTest(kind=kind):
                self.scenario(kind, {"101": (35., 10.)}, feature_shift=(35., 10.))

    def test_cutout_only_leaves_feature_and_native_surface_count(self):
        for kind in ("bunker", "tee"):
            with self.subTest(kind=kind):
                self.scenario(kind, {"rough-ring:303:inner:0": (35., 10.)}, hole_shift=(35., 10.))

    def test_feature_and_cutout_together(self):
        for kind in ("bunker", "tee"):
            with self.subTest(kind=kind):
                self.scenario(kind, {"101": (35., 10.), "rough-ring:303:inner:0": (35., 10.)},
                              feature_shift=(35., 10.), hole_shift=(35., 10.))

    def test_feature_and_cutout_can_receive_different_moves(self):
        for kind in ("bunker", "tee"):
            with self.subTest(kind=kind):
                self.scenario(kind, {"101": (35., 10.), "rough-ring:303:inner:0": (5., 40.)},
                              feature_shift=(35., 10.), hole_shift=(5., 40.))

    def test_rough_outer_only_leaves_both_holes_and_feature(self):
        self.scenario("bunker", {"rough-ring:303:outer:0": (8., 6.)}, outer_shift=(8., 6.))

    def test_explicit_group_moves_outer_feature_and_matching_cutout(self):
        offsets = {sid: (8., 6.) for sid in ("101", "rough-ring:303:inner:0", "rough-ring:303:outer:0")}
        self.scenario("tee", offsets, feature_shift=(8., 6.), hole_shift=(8., 6.), outer_shift=(8., 6.))

    def test_shared_node_detachment_survives_actual_consumers(self):
        for kind in ("bunker", "tee"):
            with self.subTest(kind=kind):
                data, source, nudge, rings = fixture(self.folder / kind, kind, shared=True)
                output = self.export(data, source, nudge, {"101": (8., 6.)})
                self.consumers(data, output, nudge, kind,
                    dict(feature=rings[101]+(8., 6.), outer=rings[102]), relation=False)

    def test_saved_clone_can_be_reanalyzed_and_rebuilt_as_current_mask(self):
        data, output, nudge, _ = self.scenario("bunker", {"rough-ring:303:inner:0": (35., 10.)},
                                             hole_shift=(35., 10.))
        refined = self.export(data, output, nudge, {"rough-ring:303:inner:0": (2., 0.)}, filename="refined.osm")
        self.consumers(data, refined, nudge, "bunker", dict(feature=rectangle(50, 50, 70, 70),
            hole=rectangle(50, 50, 70, 70)+(37., 10.), outer=rectangle(20, 20, 200, 200)))
        source = output.parent / "source.osm"
        mask.rebuild_aligned_mask(output.parent, source, *nudge, auto_red_mask_enabled=True,
                                 auto_red_mask_buffer_m=5., printf=lambda *_: None)
        before = cv2.imread(str(output.parent / "mask.png"))
        self.assertFalse(mask.get_alignment_status(output.parent, refined, *nudge, True, 5.)["ok_for_import"])
        mask.rebuild_aligned_mask(output.parent, refined, *nudge, auto_red_mask_enabled=True,
                                 auto_red_mask_buffer_m=5., printf=lambda *_: None)
        self.assertTrue(mask.get_alignment_status(output.parent, refined, *nudge, True, 5.)["ok_for_import"])
        self.assertFalse(np.array_equal(before, cv2.imread(str(output.parent / "mask.png"))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
