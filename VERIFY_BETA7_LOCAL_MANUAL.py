"""Headless manual-review/export checks on small analytical terrain fixtures."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import numpy as np

import VERIFY_BETA7_LOCAL_ALIGNMENT_ENGINE as fixtures
import tgc_local_alignment as engine


class LocalManualAlignmentTests(unittest.TestCase):
    # Reuse only the fixture setup, not the existing test suite.
    setUp = fixtures.LocalAlignmentEngineTests.setUp
    analyze = fixtures.LocalAlignmentEngineTests.analyze

    def save(self, report, manual=None, accepted=(101,), output=None, **kwargs):
        live = dict(current_data=self.data, current_nudge=self.nudge, current_osm_file=self.source)
        live.update(kwargs)
        return engine.apply_reviewed(report, accepted, output or self.output,
                                     manual_overrides=manual, **live)

    @staticmethod
    def feature(report, wid=101):
        return next(f for f in report['features'] if f['way_id'] == wid)

    def add_polygon(self, wid, points, kind='tee'):
        root = ET.fromstring(self.source.read_bytes())
        next_id = max(int(n.get('id')) for n in root.findall('node')) + 1
        refs, lines = [], []
        for offset, (x, y) in enumerate(points):
            nid = next_id + offset
            refs.append(nid)
            lon, lat = self.transform.transform(self.min_x + x, self.min_y + y, direction='INVERSE')
            lines.append('<node id="%d" lon="%.12f" lat="%.12f"/>' % (nid, lon, lat))
        lines.append('<way id="%d">' % wid + ''.join('<nd ref="%d"/>' % nid for nid in refs + refs[:1])
                     + '<tag k="golf" v="%s"/></way>' % kind)
        self.source.write_bytes(self.source.read_bytes().replace(b'</osm>', '\n'.join(lines).encode() + b'</osm>'))
        self.raw = self.source.read_bytes()

    def translate_source(self, east, north):
        root = ET.fromstring(self.source.read_bytes())
        for node in root.findall('node'):
            x, y = self.transform.transform(float(node.get('lon')), float(node.get('lat')))
            lon, lat = self.transform.transform(x + east, y + north, direction='INVERSE')
            node.set('lon', '%.12f' % lon)
            node.set('lat', '%.12f' % lat)
        self.source.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
        self.raw = self.source.read_bytes()

    def assert_movements(self, before, after, shifts):
        old, new = ET.fromstring(before), ET.fromstring(after)
        new_nodes = {n.get('id'): n for n in new.findall('node')}
        expected = {}
        for way in old.findall('way'):
            if int(way.get('id')) in shifts:
                for nd in way.findall('nd'):
                    expected[nd.get('ref')] = shifts[int(way.get('id'))]
        for node in old.findall('node'):
            other = new_nodes[node.get('id')]
            if node.get('id') not in expected:
                self.assertEqual((node.get('lon'), node.get('lat')), (other.get('lon'), other.get('lat')))
                continue
            a = np.array(self.transform.transform(float(node.get('lon')), float(node.get('lat'))))
            b = np.array(self.transform.transform(float(other.get('lon')), float(other.get('lat'))))
            self.assertLess(np.linalg.norm(b - a - expected[node.get('id')]), 1e-5)

    def test_keep_and_weak_features_accept_manual_moves_beyond_search_radius(self):
        original_raw = self.raw
        for expected in ('keep_current', 'insufficient_evidence'):
            with self.subTest(status=expected):
                self.source.write_bytes(original_raw)
                data = copy.deepcopy(self.data)
                if expected == 'keep_current':
                    self.translate_source(-3., 2.)
                else:
                    data['heightmap'][35:45, 35:45] = np.nan
                raw = self.source.read_bytes()
                report = engine.analyze(data, self.source, *self.nudge)
                feature = self.feature(report)
                self.assertEqual(feature['status'], expected)
                self.assertFalse(feature['movable'])
                self.assertTrue(feature['manual_movable'])
                self.assertEqual(feature['manual_reason'], '')
                shift = engine.validate_manual_offset(report, 101, 12.5, -6.25)
                self.assertGreater(np.linalg.norm(shift), report['config']['search_radius_m'])
                result = self.save(report, {101: {'east_m': shift[0], 'north_m': shift[1]}},
                                   output=self.folder / (expected + '.osm'), current_data=data)
                self.assertEqual(result['accepted_features'][0]['correction_method'], 'manual')
                self.assertEqual(result['accepted_features'][0]['status'], expected)
                self.assert_movements(raw, Path(result['output']).read_bytes(), {101: shift})
                self.assertEqual(self.source.read_bytes(), raw)

    def test_manual_replaces_detector_offset_and_preserves_report_and_global_nudge(self):
        report = self.analyze()
        before = copy.deepcopy(report)
        self.assertTrue(self.feature(report)['movable'])
        self.assertEqual([self.feature(report)['proposed_east_m'], self.feature(report)['proposed_north_m']], [-3., 2.])
        result = self.save(report, {101: {'east_m': 6., 'north_m': -5.}})
        self.assert_movements(self.raw, self.output.read_bytes(), {101: [6., -5.]})
        self.assertEqual(result['global_nudge_m'], self.nudge)
        self.assertEqual(report, before)
        self.assertEqual(report['report_sha256'], engine._report_digest(report))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_mixed_automatic_manual_and_unselected_objects(self):
        self.add_polygon(202, [(120., 125.), (130., 125.), (130., 135.), (120., 135.)])
        self.add_polygon(303, [(145., 35.), (155., 35.), (155., 45.), (145., 45.)], 'bunker')
        report = self.analyze()
        self.assertTrue(self.feature(report, 101)['movable'])
        self.assertTrue(self.feature(report, 202)['manual_movable'])
        result = self.save(report, {202: {'east_m': 15., 'north_m': -9.}}, accepted=[101, 202])
        self.assert_movements(self.raw, self.output.read_bytes(), {101: [-3., 2.], 202: [15., -9.]})
        self.assertEqual([(f['way_id'], f['correction_method']) for f in result['accepted_features']],
                         [(101, 'automatic'), (202, 'manual')])
        self.assertEqual(result['applied_way_ids'], [101, 202])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_preview_zero_finite_values_and_shifted_terrain_bounds(self):
        report = self.analyze()
        self.assertEqual(engine.validate_manual_offset(report, '101', 0, 0), (0., 0.))
        for east, north in ((float('nan'), 0), (0, float('inf')), (True, 0), ('bad', 0), (-1000, 0), (0, 1000)):
            with self.subTest(offset=(east, north)), self.assertRaises(engine.AlignmentError):
                engine.validate_manual_offset(report, 101, east, north)
        coordinates = np.asarray(self.feature(report)['coords_m'])
        # East nudge keeps this inside; negative north nudge puts that outside.
        engine.validate_manual_offset(report, 101, -coordinates[:, 0].min() - .5, 0.)
        with self.assertRaisesRegex(engine.AlignmentError, 'terrain bounds'):
            engine.validate_manual_offset(report, 101, 0., -coordinates[:, 1].min() + .25)
        with self.assertRaisesRegex(engine.AlignmentError, 'nonzero'):
            self.save(report, {101: {'east_m': 0., 'north_m': 0.}})
        with self.assertRaisesRegex(engine.AlignmentError, 'too small'):
            self.save(report, {101: {'east_m': 1e-300, 'north_m': 0.}})
        self.assertFalse(self.output.exists())

    def test_v1_manifest_and_manual_refinement_preserve_original_and_parent_history(self):
        report = self.analyze()
        first = self.save(report)
        first_bytes = self.output.read_bytes()
        legacy_path = Path(first['manifest'])
        legacy = json.loads(legacy_path.read_text(encoding='utf-8'))
        # A legacy schema fixture has the V1 version and no per-way method field.
        legacy['feature_version'] = 'beta7-local-alignment-v1'
        for feature in legacy['accepted_features']:
            feature.pop('correction_method')
        legacy['manifest_sha256'] = engine._digest({k: v for k, v in legacy.items() if k != 'manifest_sha256'})
        legacy_path.write_text(json.dumps(legacy), encoding='utf-8')
        again = engine.analyze(self.data, self.output, *self.nudge)
        f = self.feature(again)
        self.assertEqual(f['status'], 'already_corrected')
        self.assertFalse(f['movable'])
        self.assertTrue(f['manual_movable'])
        refined_path = self.folder / 'refined.osm'
        with self.assertRaisesRegex(engine.AlignmentError, 'not an eligible'):
            self.save(again, output=refined_path, current_osm_file=self.output)
        second = self.save(again, {101: {'east_m': 1.25, 'north_m': -.75}},
                           output=refined_path, current_osm_file=self.output)
        record = json.loads(Path(second['manifest']).read_text(encoding='utf-8'))
        self.assertEqual(record['feature_version'], engine.FEATURE_VERSION)
        self.assertEqual(record['parent_manifest_sha256'], legacy['manifest_sha256'])
        self.assertEqual(record['original_source_osm_path'], str(self.source.resolve()))
        self.assertEqual(record['original_source_osm_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(record['applied_way_ids'], [101])
        self.assertEqual(record['accepted_features'][0]['correction_method'], 'manual')
        self.assertEqual(record['accepted_features'][0]['status'], 'already_corrected')
        self.assert_movements(first_bytes, refined_path.read_bytes(), {101: [1.25, -.75]})
        self.assertEqual(self.output.read_bytes(), first_bytes)
        self.assertEqual(self.source.read_bytes(), self.raw)
        newest = engine.analyze(self.data, refined_path, *self.nudge)
        self.assertEqual(self.feature(newest)['status'], 'already_corrected')
        self.assertTrue(self.feature(newest)['manual_movable'])
        self.assertFalse(self.feature(newest)['movable'])

    def test_shared_relations_can_be_detached_but_invalid_rings_remain_blocked(self):
        extras = [
            '<way id="202"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="golf" v="rough"/></way>',
            '<relation id="303"><member type="way" ref="101" role="outer"/></relation>',
            '<relation id="303"><member type="node" ref="1" role="point"/></relation>',
        ]
        variants = [self.raw.replace(b'</osm>', extra.encode() + b'</osm>') for extra in extras]
        root = ET.fromstring(self.raw)
        root.find('way').findall('nd')[-1].set('ref', '2')
        variants.append(ET.tostring(root, encoding='utf-8'))
        root = ET.fromstring(self.raw)
        nds = root.find('way').findall('nd')
        nds[1].set('ref', '49')
        nds[48].set('ref', '2')
        variants.append(ET.tostring(root, encoding='utf-8'))
        for index, raw in enumerate(variants):
            with self.subTest(variant=index):
                self.source.write_bytes(raw)
                report = self.analyze()
                feature = self.feature(report)
                if index < 3:
                    self.assertTrue(feature['manual_movable'])
                    self.assertEqual(engine.validate_manual_offset(report, 101, 1., 0.), (1., 0.))
                    result = self.save(report, {101: {'east_m': 1., 'north_m': 0.}})
                    self.assertTrue(result['cloned_nodes'])
                    self.assertEqual(self.source.read_bytes(), raw)
                    self.output.unlink()
                    engine.manifest_path(self.output).unlink()
                    continue
                self.assertFalse(feature['manual_movable'])
                self.assertTrue(feature['manual_reason'])
                with self.assertRaises(engine.AlignmentError):
                    engine.validate_manual_offset(report, 101, 1., 0.)
                with self.assertRaises(engine.AlignmentError):
                    self.save(report, {101: {'east_m': 1., 'north_m': 0.}})
                self.assertFalse(self.output.exists())

    def test_manual_export_retains_all_live_state_checks(self):
        report = self.analyze()
        manual = {101: {'east_m': 6., 'north_m': -5.}}
        self.source.write_bytes(self.raw + b'\n')
        with self.assertRaisesRegex(engine.AlignmentError, 'SHA-256'):
            self.save(report, manual)
        self.source.write_bytes(self.raw)
        altered = copy.deepcopy(self.data)
        altered['heightmap'][0, 0] += .25
        with self.assertRaisesRegex(engine.AlignmentError, 'Terrain or master grid'):
            self.save(report, manual, current_data=altered)
        altered = copy.deepcopy(self.data)
        altered['master_grid']['source'] = 'changed grid metadata'
        with self.assertRaisesRegex(engine.AlignmentError, 'Terrain or master grid'):
            self.save(report, manual, current_data=altered)
        with self.assertRaisesRegex(engine.AlignmentError, 'nudge changed'):
            self.save(report, manual, current_nudge=[0, 0])
        other = self.folder / 'other.osm'
        other.write_bytes(self.raw)
        with self.assertRaisesRegex(engine.AlignmentError, 'selected OSM changed'):
            self.save(report, manual, current_osm_file=other)
        for key in ('current_data', 'current_nudge', 'current_osm_file'):
            with self.subTest(key=key), self.assertRaisesRegex(engine.AlignmentError, 'Live terrain'):
                self.save(report, manual, **{key: None})
        self.assertFalse(self.output.exists())

    def test_manual_selection_is_explicit_and_report_is_protected(self):
        report = self.analyze()
        bad = [
            ({101: {'east_m': 1., 'north_m': 0.}}, []),
            ({999: {'east_m': 1., 'north_m': 0.}}, [101]),
            ({999: {'east_m': 1., 'north_m': 0.}}, [999]),
            ({101: {'east_m': 1.}}, [101]),
            ({101: {'east_m': 1., 'north_m': 0., 'typo': 1}}, [101]),
            ({101: {'east_m': 1., 'north_m': 0.}, '101': {'east_m': 2., 'north_m': 0.}}, [101]),
        ]
        for manual, selected in bad:
            with self.subTest(manual=manual), self.assertRaises(engine.AlignmentError):
                self.save(report, manual, accepted=selected)
        changed = copy.deepcopy(report)
        changed['features'][0]['manual_movable'] = False
        with self.assertRaisesRegex(engine.AlignmentError, 'report changed'):
            engine.validate_manual_offset(changed, 101, 1, 0)
        with self.assertRaisesRegex(engine.AlignmentError, 'report changed'):
            self.save(changed, {101: {'east_m': 1., 'north_m': 0.}})
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
