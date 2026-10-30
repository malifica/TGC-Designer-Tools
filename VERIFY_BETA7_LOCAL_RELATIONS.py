"""Headless ownership, topology and provenance checks for manual rough edits."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

from VERIFY_BETA7_LOCAL_RELATION_CONSUMERS import fixture
from tgc_cfs_display import importer_transformer
import tgc_local_alignment as engine
import tgc_local_alignment_export as exporter


class ManualRelationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tgc-manual-relations-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data, self.source, self.nudge, _ = fixture(self.folder)
        self.output = self.folder / "corrected.osm"

    def replace(self, root):
        self.source.write_bytes(ET.tostring(root, encoding="utf-8"))

    def analyze(self):
        return engine.analyze(self.data, self.source, *self.nudge)

    def save(self, offsets, report=None, output=None, source=None):
        report = self.analyze() if report is None else report
        return engine.apply_reviewed(report, list(offsets), output or self.output,
            current_data=self.data, current_nudge=self.nudge, current_osm_file=source or self.source,
            manual_overrides={sid: dict(east_m=xy[0], north_m=xy[1]) for sid, xy in offsets.items()})

    def xy(self, root, wid):
        nodes = {n.get("id"):n for n in root.findall("node")}
        refs = root.find("way[@id='%s']" % wid).findall("nd")
        lonlat = np.array([[float(nodes[n.get('ref')].get(k)) for k in ('lon','lat')] for n in refs])
        transform = importer_transformer(self.data["projection"])
        return np.column_stack(transform.transform(*lonlat.T))

    def test_inventory_lists_manual_boundaries_without_running_rough_detection(self):
        with patch("tgc_local_alignment_detector.analyse_feature", side_effect=AssertionError("No automatic target is eligible")):
            report = self.analyze()
        targets = {f["selection_id"]:f for f in report["features"]}
        self.assertEqual(set(targets), {'101','rough-ring:303:outer:0','rough-ring:303:inner:0','rough-ring:303:inner:1'})
        self.assertEqual(targets['101']['linked_ids'], ['rough-ring:303:inner:0'])
        self.assertEqual(targets['rough-ring:303:inner:0']['linked_ids'], ['101'])
        self.assertIn('rough-ring:303:outer:0',targets['101']['related_ids'])
        self.assertEqual(report['summary']['features_evaluated'],1)
        for sid, feature in targets.items():
            self.assertTrue(feature['manual_movable'], sid)
            self.assertFalse(feature['movable'])
            if sid != '101':
                self.assertEqual(feature['status'],'manual_only')
                self.assertEqual((feature['proposed_east_m'],feature['proposed_north_m']),(0.,0.))
        self.assertEqual(engine.validate_manual_offset(report, 'rough-ring:303:outer:0',1000,0),(1000.,0.))
        with self.assertRaises(engine.AlignmentError):
            engine.validate_manual_offset(report,'101',1000,0)
        offsets = {'101':{'east_m':2.,'north_m':1.},
                   'rough-ring:303:inner:0':{'east_m':2.,'north_m':1.}}
        with patch.object(engine,'_report_digest',wraps=engine._report_digest) as digest:
            self.assertEqual(engine.validate_manual_offsets(report,offsets),offsets)
            self.assertEqual(digest.call_count,1,'Group validation must hash the report only once')

    def test_different_shared_node_offsets_detach_only_required_node(self):
        self.data,self.source,self.nudge,_ = fixture(self.folder, shared=True)
        before = ET.fromstring(self.source.read_bytes())
        result = self.save({'101':(2.,-1.), 'rough-way:102':(-3.,4.)})
        after = ET.fromstring(self.output.read_bytes())
        self.assertEqual(len(result['cloned_nodes']),1)
        self.assertFalse(result['cloned_ways'])
        np.testing.assert_allclose(self.xy(after,101)-self.xy(before,101),np.tile((2.,-1.),(5,1)),atol=1e-5)
        np.testing.assert_allclose(self.xy(after,102)-self.xy(before,102),np.tile((-3.,4.),(5,1)),atol=1e-5)

    def test_unrelated_relation_geometry_is_preserved_when_feature_and_hole_move(self):
        root = ET.fromstring(self.source.read_bytes())
        rel = ET.SubElement(root,'relation',id='404',version='9')
        ET.SubElement(rel,'member',type='way',ref='101',role='boundary')
        ET.SubElement(rel,'tag',k='type',v='boundary')
        self.replace(root)
        before = self.source.read_bytes()
        result = self.save({'101':(3.,2.),'rough-ring:303:inner:0':(3.,2.)})
        after = ET.fromstring(self.output.read_bytes())
        other = after.find("relation[@id='404']")
        wid = other.find('member').get('ref')
        self.assertLess(int(wid),0)
        self.assertEqual(other.attrib,rel.attrib)
        np.testing.assert_allclose(self.xy(after,wid),self.xy(root,101),atol=1e-5)
        self.assertEqual(after.find("relation[@id='303']").findall('member')[1].get('ref'),'101')
        self.assertEqual(self.source.read_bytes(),before)
        self.assertEqual(len(result['cloned_ways']),1)

    def test_tagged_node_and_node_relation_remain_stationary(self):
        root = ET.fromstring(self.source.read_bytes())
        original = root.find('node')
        ET.SubElement(original,'tag',k='survey',v='retained point')
        rel = ET.SubElement(root,'relation',id='405')
        ET.SubElement(rel,'member',type='node',ref=original.get('id'),role='survey')
        self.replace(root)
        result = self.save({'101':(2.,1.),'rough-ring:303:inner:0':(2.,1.)})
        after = ET.fromstring(self.output.read_bytes())
        self.assertEqual(ET.tostring(original),ET.tostring(after.find("node[@id='%s']" % original.get('id'))))
        self.assertEqual(after.find("relation[@id='405']").find('member').get('ref'),original.get('id'))
        self.assertEqual(len(result['cloned_nodes']),1)
        self.assertFalse(result['cloned_ways'])
        self.assertNotEqual(after.find("way[@id='101']").find('nd').get('ref'),original.get('id'))

    def test_complete_rough_ring_assembles_reversed_fragments(self):
        root = ET.fromstring(self.source.read_bytes())
        outer = root.find("way[@id='102']")
        refs = [n.get('ref') for n in outer.findall('nd')]
        for nd in list(outer): outer.remove(nd)
        for ref in refs[:3]: ET.SubElement(outer,'nd',ref=ref)
        other = ET.Element('way',id='104')
        for ref in [refs[0],refs[3],refs[2]]: ET.SubElement(other,'nd',ref=ref)
        root.insert(list(root).index(root.find('relation')),other)
        relation = root.find('relation')
        relation.insert(1,ET.Element('member',type='way',ref='104',role='outer'))
        self.replace(root)
        report = self.analyze()
        target = next(f for f in report['features'] if f['selection_id']=='rough-ring:303:outer:0')
        self.assertEqual(target['member_way_ids'],[102,104])
        self.assertEqual(len(target['coords_m']),5)
        self.assertTrue(target['manual_movable'])
        result = self.save({'rough-ring:303:outer:0':(2.,3.)},report)
        after = ET.fromstring(self.output.read_bytes())
        for wid in (102,104):
            np.testing.assert_allclose(self.xy(after,wid)-self.xy(root,wid),np.tile((2.,3.),(3,1)),atol=1e-5)
        self.assertFalse(result['cloned_ways'])

    def test_final_rough_containment_refuses_invalid_batch_without_output(self):
        raw = self.source.read_bytes()
        for offsets in ({'rough-ring:303:inner:0':(180.,0.)},
                        {'rough-ring:303:outer:0':(180.,0.)},
                        {'rough-ring:303:inner:0':(90.,0.)}):
            with self.subTest(offsets=offsets), self.assertRaisesRegex(engine.AlignmentError,'rough hole|rough holes'):
                self.save(offsets)
            self.assertFalse(self.output.exists())
            self.assertFalse(engine.manifest_path(self.output).exists())
            self.assertEqual(self.source.read_bytes(),raw)

    def test_clone_ids_skip_existing_negatives_and_original_bytes_survive(self):
        root = ET.fromstring(self.source.read_bytes())
        for nid in ('-7','-8'):
            original = root.find('node')
            root.insert(0,ET.Element('node',id=nid,lon=original.get('lon'),lat=original.get('lat')))
        way = ET.SubElement(root,'way',id='-9')
        ET.SubElement(way,'nd',ref='-7'); ET.SubElement(way,'nd',ref='-8')
        self.replace(root)
        marker = b'<!-- preserve <way id="-999"><nd ref="123"/></way> literally -->'
        self.source.write_bytes(self.source.read_bytes().replace(b'</osm>',marker+b'</osm>'))
        raw = self.source.read_bytes()
        result = self.save({'101':(2.,1.)})
        self.assertTrue(all(c['node_id'] < -8 for c in result['cloned_nodes']))
        self.assertTrue(all(c['way_id'] < -9 for c in result['cloned_ways']))
        self.assertIn(marker,self.output.read_bytes())
        self.assertEqual(self.source.read_bytes(),raw)
        after = ET.fromstring(self.output.read_bytes())
        self.assertEqual(ET.tostring(way),ET.tostring(after.find("way[@id='-9']")))

    def test_report_ownership_tampering_is_rejected_even_with_recomputed_digest(self):
        report = self.analyze()
        modified = copy.deepcopy(report)
        selected = next(f for f in modified['features'] if f['selection_id']=='rough-ring:303:inner:0')
        selected['member_indexes'] = [0]
        modified['report_sha256'] = engine._report_digest(modified)
        with self.assertRaisesRegex(engine.AlignmentError,'ownership'):
            self.save({'rough-ring:303:inner:0':(1.,0.)},modified)
        self.assertFalse(self.output.exists())

    def test_legacy_v2_manifest_and_new_target_provenance(self):
        result = self.save({'101':(2.,1.),'rough-ring:303:inner:0':(2.,1.)})
        path = engine.manifest_path(self.output)
        record = json.loads(path.read_text())
        record['feature_version'] = 'beta7-local-alignment-v2'
        record.pop('applied_target_ids')
        record['manifest_sha256'] = engine._digest({k:v for k,v in record.items() if k!='manifest_sha256'})
        path.write_text(json.dumps(record))
        report = engine.analyze(self.data,self.output,*self.nudge)
        self.assertEqual(report['features'][0]['status'],'already_corrected')
        refined = self.folder/'refined.osm'
        second = self.save({'rough-ring:303:inner:0':(.5,0.)},report,refined,self.output)
        self.assertEqual(second['applied_way_ids'],[101])
        self.assertEqual(second['applied_target_ids'],['101','rough-ring:303:inner:0'])
        manifest = json.loads(engine.manifest_path(refined).read_text())
        self.assertEqual(manifest['parent_manifest_sha256'],record['manifest_sha256'])
        self.assertEqual(manifest['original_source_osm_sha256'],hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertTrue(second['cloned_ways'])

    def test_topology_pair_publication_rolls_back_atomically(self):
        original = exporter._publish_no_replace
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError('relation publication failure')
            return original(*args)
        raw = self.source.read_bytes()
        with patch.object(exporter,'_publish_no_replace',side_effect=fail_second):
            with self.assertRaisesRegex(OSError,'relation publication failure'):
                self.save({'101':(2.,1.)})
        self.assertFalse(self.output.exists())
        self.assertFalse(engine.manifest_path(self.output).exists())
        self.assertFalse(list(self.folder.glob('.*.tmp')))
        self.assertEqual(self.source.read_bytes(),raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
