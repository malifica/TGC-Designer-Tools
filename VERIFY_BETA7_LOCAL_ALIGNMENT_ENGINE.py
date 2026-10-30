"""Headless numerical/export contract checks using analytical fixtures only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
import pyproj

import tgc_local_alignment as engine
import tgc_local_alignment_export as exporter
from tgc_cfs_display import importer_transformer
from tgc_local_alignment_detector import Terrain


class LocalAlignmentEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.source = self.folder / "source.osm"
        self.output = self.folder / "corrected.osm"
        self.nudge = [1., -.5]
        self.projection = pyproj.Proj("EPSG:32611")
        self.transform = importer_transformer(self.projection)
        self.min_x, self.min_y = 576000., 5497500.
        resolution, size = 2., 96
        xx, yy = np.meshgrid((np.arange(size) + .5) * resolution, (np.arange(size) + .5) * resolution)
        radial = np.hypot(xx - 80., yy - 80.)
        t = np.clip((12. - radial) / 4., 0., 1.)
        z = 100. - 2. * t * t * (3. - 2. * t) + .25 * np.exp(-.5 * ((radial - 12.) / 1.) ** 2)
        lon0, lat0 = self.transform.transform(self.min_x, self.min_y, direction="INVERSE")
        grid = {"version": 1, "resolution": resolution, "rows": size, "cols": size,
                "min_x": self.min_x, "min_y": self.min_y, "max_x": self.min_x + size * resolution,
                "max_y": self.min_y + size * resolution, "crs_wkt": self.projection.crs.to_wkt(),
                "row_order": "south_up_internal", "origin_semantics": "southwest_cell_edge",
                "lower_left_latlon": [lat0, lon0], "xy_units": "meters"}
        self.data = {"heightmap": z, "projection": self.projection, "master_grid": grid, "image_scale": resolution}
        theta = np.linspace(0, 2 * np.pi, 96, endpoint=False)
        ring = np.column_stack([80. + 12. * np.cos(theta), 80. + 12. * np.sin(theta)])
        source_xy = ring + np.array([3., -2.]) - self.nudge
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="engine fixture">',
                 '<!-- Preserve misleading <node id="999" lat="1" lon="2"/> comment. -->']
        for index, (x, y) in enumerate(source_xy, 1):
            lon, lat = self.transform.transform(x + self.min_x, y + self.min_y, direction="INVERSE")
            lines.append("<node id='%d' lon=\"%.12f\" lat='%.12f' version='3'/>" % (index, lon, lat))
        lines.append('<way id="101" version="4">' + ''.join('<nd ref="%d"/>' % i for i in list(range(1, 97)) + [1]) + '<tag k="golf" v="bunker"/><tag k="name" v="Synthetic rim"/></way>')
        lines.append('</osm>')
        self.source.write_bytes('\r\n'.join(lines).encode("utf-8"))
        self.raw = self.source.read_bytes()

    def analyze(self):
        return engine.analyze(self.data, self.source, *self.nudge)

    def apply(self, report, accepted=(101,), **kwargs):
        values = dict(current_data=self.data, current_nudge=self.nudge, current_osm_file=self.source)
        values.update(kwargs)
        return engine.apply_reviewed(report, accepted, self.output, **values)

    def test_cell_centers_and_south_up(self):
        xx, yy = np.meshgrid((np.arange(48) + .5) * 2, (np.arange(48) + .5) * 2)
        z = 100 + .13 * xx - .07 * yy
        terrain = Terrain(z, 2.)
        points = np.array([[31., 45.], [41.5, 72.25], [65.75, 31.5]])
        self.assertLess(np.max(np.abs(terrain.sample(terrain.z, points) - (100 + .13 * points[:, 0] - .07 * points[:, 1]))), 1e-10)

    def test_actual_nonzero_nudge_fit_export_and_lineage(self):
        report = self.analyze()
        f = report["features"][0]
        self.assertTrue(f["movable"])
        self.assertEqual([f["proposed_east_m"], f["proposed_north_m"]], [-3., 2.])
        self.assertTrue(np.allclose(np.array(f["fit_coords_m"]) - f["coords_m"], self.nudge))
        result = self.apply(report)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(result["changed_nodes"], 96)
        self.assertEqual(result["global_nudge_m"], self.nudge)
        old = ET.fromstring(self.raw).findall("node")
        new = ET.fromstring(self.output.read_bytes()).findall("node")
        for a, b in zip(old, new):
            old_xy = np.array(self.transform.transform(float(a.get("lon")), float(a.get("lat"))))
            new_xy = np.array(self.transform.transform(float(b.get("lon")), float(b.get("lat"))))
            self.assertLess(np.linalg.norm(new_xy - old_xy - [-3., 2.]), 1e-5)
            self.assertEqual({k: v for k, v in a.attrib.items() if k not in ("lat", "lon")},
                             {k: v for k, v in b.attrib.items() if k not in ("lat", "lon")})
        self.assertIn(b'<!-- Preserve misleading <node id="999"', self.output.read_bytes())
        again = engine.analyze(self.data, self.output, *self.nudge)
        self.assertEqual(again["features"][0]["status"], "already_corrected")
        self.assertFalse(again["features"][0]["movable"])
        self.assertEqual(again["original_source_osm_path"], str(self.source.resolve()))
        self.assertEqual(again["original_source_osm_sha256"], hashlib.sha256(self.raw).hexdigest())

    def test_shared_or_relation_topology_abstains_before_fit(self):
        extras = [
            '<way id="202"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="golf" v="rough"/></way>',
            '<relation id="303"><member type="way" ref="101" role="outer"/><tag k="type" v="multipolygon"/></relation>',
            '<relation id="303"><member type="node" ref="1" role="point"/><tag k="type" v="route"/></relation>',
        ]
        for extra in extras:
            with self.subTest(extra=extra):
                self.source.write_bytes(self.raw.replace(b'</osm>', extra.encode() + b'</osm>'))
                with patch('tgc_local_alignment_detector.analyse_feature', side_effect=AssertionError("Blocked geometry reached detector")):
                    report = self.analyze()
                self.assertEqual(report["features"][0]["status"], "unsupported_topology")
                self.assertFalse(report["features"][0]["movable"])
                with self.assertRaisesRegex(engine.AlignmentError, "not an eligible"):
                    self.apply(report)
                self.assertFalse(self.output.exists())

    def test_source_terrain_grid_nudge_and_selected_source_must_match(self):
        report = self.analyze()
        self.source.write_bytes(self.raw + b'\n')
        with self.assertRaisesRegex(engine.AlignmentError, "SHA-256"):
            self.apply(report)
        self.source.write_bytes(self.raw)
        changed = copy.deepcopy(self.data)
        changed["heightmap"][0, 0] += .1
        with self.assertRaisesRegex(engine.AlignmentError, "Terrain or master grid"):
            self.apply(report, current_data=changed)
        changed = copy.deepcopy(self.data)
        changed["master_grid"]["source"] = "different terrain source"
        with self.assertRaisesRegex(engine.AlignmentError, "Terrain or master grid"):
            self.apply(report, current_data=changed)
        with self.assertRaisesRegex(engine.AlignmentError, "nudge changed"):
            self.apply(report, current_nudge=[0, 0])
        other = self.folder / 'other.osm'
        other.write_bytes(self.raw)
        with self.assertRaisesRegex(engine.AlignmentError, "selected OSM changed"):
            self.apply(report, current_osm_file=other)
        for name in ('current_data', 'current_nudge', 'current_osm_file'):
            with self.subTest(name=name), self.assertRaisesRegex(engine.AlignmentError, "Live terrain"):
                self.apply(report, **{name: None})
        self.assertFalse(self.output.exists())

    def test_explicit_ids_eligibility_and_report_integrity(self):
        report = self.analyze()
        for accepted in ([], [999], [101, 101]):
            with self.subTest(ids=accepted), self.assertRaises(engine.AlignmentError):
                self.apply(report, accepted)
        modified = copy.deepcopy(report)
        modified["features"][0]["proposed_east_m"] = 1
        with self.assertRaisesRegex(engine.AlignmentError, "report changed"):
            self.apply(modified)
        for status in ("keep_current", "insufficient_evidence", "already_corrected"):
            modified = copy.deepcopy(report)
            modified["features"][0]["status"] = status
            modified["report_sha256"] = engine._report_digest(modified)
            with self.subTest(status=status), self.assertRaisesRegex(engine.AlignmentError, "not an eligible"):
                self.apply(modified)
        self.assertFalse(self.output.exists())

    def test_output_and_manifest_no_overwrite(self):
        report = self.analyze()
        for path in (self.output, engine.manifest_path(self.output)):
            with self.subTest(path=path):
                path.write_bytes(b'existing untouched data')
                with self.assertRaisesRegex(engine.AlignmentError, "already exists"):
                    self.apply(report)
                self.assertEqual(path.read_bytes(), b'existing untouched data')
                path.unlink()
        with self.assertRaisesRegex(engine.AlignmentError, "source OSM cannot"):
            engine.apply_reviewed(report, [101], self.source, self.data, self.nudge, self.source)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_atomic_pair_rollback_if_second_publication_fails(self):
        report = self.analyze()
        publish = exporter._publish_no_replace
        count = [0]
        def fail_second(*args):
            count[0] += 1
            if count[0] == 2:
                raise OSError("simulated output publication failure")
            return publish(*args)
        with patch.object(exporter, '_publish_no_replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated output"):
                self.apply(report)
        self.assertFalse(self.output.exists())
        self.assertFalse(engine.manifest_path(self.output).exists())
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['source.osm'])

    def test_cancel_no_files_and_unsupported_modes(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(engine.AlignmentCancelled):
            engine.analyze(self.data, self.source, cancel_event=event)
        event.clear()
        def cancel_after_feature(percent, message):
            if percent > 20:
                event.set()
        with self.assertRaises(engine.AlignmentCancelled):
            engine.analyze(self.data, self.source, *self.nudge, progress_callback=cancel_after_feature, cancel_event=event)
        with self.assertRaisesRegex(engine.AlignmentError, "georeferenced"):
            engine.analyze(self.data, self.source, custom_unmatched_osm=True)
        with self.assertRaisesRegex(engine.AlignmentError, "tees and bunkers"):
            engine.analyze(self.data, self.source, kinds=('green',))
        bad = copy.deepcopy(self.data)
        bad['master_grid']['row_order'] = 'north_up'
        with self.assertRaisesRegex(engine.AlignmentError, "south-up"):
            engine.analyze(bad, self.source)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['source.osm'])

    def test_flat_and_missing_terrain_do_not_create_movable_objects(self):
        for missing in (False, True):
            data = copy.deepcopy(self.data)
            if missing:
                data['heightmap'][35:45, 35:45] = np.nan
            else:
                data['heightmap'][:] = 100
            with self.subTest(missing=missing):
                report = engine.analyze(data, self.source, *self.nudge)
                self.assertFalse(report['features'][0]['movable'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
