"""V6 manual feature/relationship tests. No network or user project writes.

Run --installed to additionally exercise the actual analysis/export pipeline and
read back its saved OSM, using only analytical terrain and temporary files.
"""
from pathlib import Path
import copy
import hashlib
import json
import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
import pyproj
from tgc_cfs_display import importer_transformer
import tgc_local_alignment_topology as topology
from tgc_local_feature_filters import filter_kind

INSTALLED = '--installed' in sys.argv
if INSTALLED: sys.argv.remove('--installed')


def fixture(kind='fairway', inner_kind='green', fragmented=False):
    p = pyproj.Proj('EPSG:32611')
    tr = importer_transformer(p)
    grid = dict(version=1, rows=128, cols=128, resolution=2., min_x=575641., min_y=5497180.,
                max_x=575897., max_y=5497436., crs_wkt=p.crs.to_wkt(), horizontal_epsg=32611,
                origin_semantics='southwest_cell_edge', row_order='south_up_internal', xy_units='meters')
    lon,lat = tr.transform(grid['min_x'],grid['min_y'],direction='INVERSE')
    grid['lower_left_latlon']=[lat,lon]
    data=dict(heightmap=np.full((128,128),100.),projection=p,master_grid=grid,image_scale=2.,origin=(lat,lon))
    root=ET.Element('osm',version='0.6',upload='never')
    cache={};next_id=1
    def way(wid, xy, tags):
        nonlocal next_id
        refs=[]
        for x,y in xy:
            if (x,y) not in cache:
                lo,la=tr.transform(grid['min_x']+x,grid['min_y']+y,direction='INVERSE')
                cache[x,y]=str(next_id);next_id+=1
                ET.SubElement(root,'node',id=cache[x,y],lon='%.12f'%lo,lat='%.12f'%la)
            refs.append(cache[x,y])
        w=ET.SubElement(root,'way',id=str(wid),version='7')
        for ref in refs:ET.SubElement(w,'nd',ref=ref)
        for k,v in tags.items():ET.SubElement(w,'tag',k=k,v=v)
        return w
    rect=lambda x,y,w,h:[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]
    if fragmented:
        way(100,[(20,20),(200,20),(200,200)],{})
        way(103,[(20,20),(20,200),(200,200)],{})
    else:way(100,rect(20,20,180,180),{})
    way(101,rect(50,50,20,20),{'golf':inner_kind,'name':'Keep identity'})
    way(102,rect(140,50,20,20),{})
    # Unselected shared-node direct surface must remain at its original coordinates.
    way(200,[(50,50),(45,50),(45,45),(50,50)],{'golf':'rough'})
    way(201,[(210,30),(225,45),(230,70)],{'golf':'cartpath'})
    way(202,rect(210,100,12,12),{'golf':'mulch','surface':'mulch'})
    rel=ET.SubElement(root,'relation',id='303',version='9')
    for wid,role in [(100,'outer')]+([(103,'outer')] if fragmented else [])+[(101,'inner'),(102,'inner')]:
        ET.SubElement(rel,'member',type='way',ref=str(wid),role=role)
    for k,v in {'type':'multipolygon','golf':kind}.items():ET.SubElement(rel,'tag',k=k,v=v)
    raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    return raw,grid,p,data


def xy(raw,wid,p,grid):
    root=ET.fromstring(raw);nodes={n.get('id'):n for n in root.findall('node')};w=root.find("way[@id='%s']"%wid)
    tr=importer_transformer(p)
    return np.array([tr.transform(float(nodes[n.get('ref')].get('lon')),float(nodes[n.get('ref')].get('lat')))
                     for n in w.findall('nd')])-[grid['min_x'],grid['min_y']]


class GeometryTests(unittest.TestCase):
    def targets(self,raw,grid,p):return topology.augment_inventory(raw,grid,p,[])
    def test_all_direct_surface_types(self):
        raw,g,p,_=fixture();root=ET.fromstring(raw);way=root.find("way[@id='202']")
        for kind in topology.SURFACE_NAMES:
            for t in list(way.findall('tag')):way.remove(t)
            ET.SubElement(way,'tag',k='golf',v=kind)
            rr=ET.tostring(root)
            feature=next(f for f in self.targets(rr,g,p) if f.get('owned_way_ids')==[202])
            self.assertTrue(topology.manual_eligibility(feature)[0],kind)
    def test_generic_relations_not_blocked(self):
        for kind in ('fairway','green','bunker','tee','water','mulch','rough','heavyrough'):
            raw,g,p,_=fixture(kind)
            targets=self.targets(raw,g,p)
            rings=[f for f in targets if f.get('relation_id')==303]
            self.assertEqual(len(rings),3)
            self.assertTrue(all(topology.manual_eligibility(f)[0] for f in rings),kind)
    def test_natural_water_relation(self):
        raw,g,p,_=fixture('water');root=ET.fromstring(raw);rel=root.find('relation')
        rel.find("tag[@k='golf']").set('k','natural')
        rings=[f for f in self.targets(ET.tostring(root),g,p) if f.get('relation_id')]
        self.assertEqual({f['kind'] for f in rings},{'water'})
    def test_linked_green_and_cutout_move_once(self):
        raw,g,p,_=fixture();fs=self.targets(raw,g,p);by={f['selection_id']:f for f in fs}
        sid='surface-way:101';hole='surface-ring:303:inner:0'
        self.assertEqual(by[sid]['linked_ids'],[hole])
        out,a=topology.render_translations(raw,fs,{sid:(2.,-1.),hole:(2.,-1.)},g,p)
        np.testing.assert_allclose(xy(out,101,p,g)-xy(raw,101,p,g),[[2,-1]]*5,atol=1e-5)
        np.testing.assert_allclose(xy(out,100,p,g),xy(raw,100,p,g),atol=1e-5)
        np.testing.assert_allclose(xy(out,200,p,g),xy(raw,200,p,g),atol=1e-5)
        self.assertFalse(a['cloned_ways'])
    def test_independent_feature_preserves_cutout(self):
        raw,g,p,_=fixture();fs=self.targets(raw,g,p)
        out,a=topology.render_translations(raw,fs,{'surface-way:101':(2.,-1.)},g,p)
        rel=ET.fromstring(out).find('relation');hole=rel.findall('member')[1].get('ref')
        self.assertNotEqual(hole,'101');self.assertEqual(len(a['cloned_ways']),1)
        np.testing.assert_allclose(xy(out,hole,p,g),xy(raw,101,p,g),atol=1e-5)
        self.assertFalse(ET.fromstring(out).find("way[@id='%s']"%hole).findall('tag'))
    def test_independent_cutout_preserves_feature(self):
        raw,g,p,_=fixture();fs=self.targets(raw,g,p)
        out,a=topology.render_translations(raw,fs,{'surface-ring:303:inner:0':(1.5,-.5)},g,p)
        hole=ET.fromstring(out).find('relation').findall('member')[1].get('ref')
        np.testing.assert_allclose(xy(out,101,p,g),xy(raw,101,p,g),atol=1e-5)
        np.testing.assert_allclose(xy(out,hole,p,g)-xy(raw,101,p,g),[[1.5,-.5]]*5,atol=1e-5)
    def test_fragmented_relation_group_retains_holes(self):
        raw,g,p,_=fixture(fragmented=True);fs=self.targets(raw,g,p)
        ids={f['selection_id']:(2.,3.) for f in fs if f.get('relation_id')==303 or f.get('way_id')==101}
        out,a=topology.render_translations(raw,fs,ids,g,p)
        for wid in (100,103,101,102):
            np.testing.assert_allclose(xy(out,wid,p,g)-xy(raw,wid,p,g),np.tile((2,3),(len(xy(raw,wid,p,g)),1)),atol=1e-5)
        self.assertFalse(a['cloned_ways'])
    def test_overlapping_selection_does_not_double_move(self):
        raw,g,p,_=fixture('rough','bunker');fs=self.targets(raw,g,p)
        shifts={f['selection_id']:(3.,2.) for f in fs if f.get('relation_id')==303 or f.get('way_id')==101}
        out,_=topology.render_translations(raw,fs,shifts,g,p)
        np.testing.assert_allclose(xy(out,101,p,g)-xy(raw,101,p,g),[[3,2]]*5,atol=1e-5)
    def test_invalid_hole_displacement_refused(self):
        raw,g,p,_=fixture();fs=self.targets(raw,g,p)
        for delta in ((200.,0.),(90.,0.)):
            with self.assertRaises(topology.AlignmentError):
                topology.render_translations(raw,fs,{'surface-ring:303:inner:0':delta},g,p)
    def test_open_path_remains_open(self):
        raw,g,p,_=fixture();fs=self.targets(raw,g,p);f=next(f for f in fs if f['way_id']==201)
        self.assertFalse(f['is_closed']);self.assertTrue(topology.manual_eligibility(f)[0])
        out,_=topology.render_translations(raw,fs,{f['selection_id']:(-1.,2.)},g,p)
        self.assertEqual(len(ET.fromstring(out).find("way[@id='201']").findall('nd')),3)
        np.testing.assert_allclose(xy(out,201,p,g)-xy(raw,201,p,g),[[-1,2]]*3,atol=1e-5)
    def test_incomplete_area_not_silently_closed(self):
        raw,g,p,_=fixture();root=ET.fromstring(raw);way=root.find("way[@id='202']");way.remove(way.findall('nd')[-1])
        f=next(f for f in self.targets(ET.tostring(root),g,p) if f['way_id']==202)
        self.assertFalse(topology.manual_eligibility(f)[0])
    def test_same_kind_tagged_outer_single_owner(self):
        raw,g,p,_=fixture('bunker','rough');root=ET.fromstring(raw)
        ET.SubElement(root.find("way[@id='100']"),'tag',k='golf',v='bunker')
        rr=ET.tostring(root);fs=self.targets(rr,g,p)
        self.assertEqual(sum(100 in f['owned_way_ids'] for f in fs),1)
        self.assertTrue(next(f for f in fs if 100 in f['owned_way_ids'])['kind_from_relation'])
    def test_rough_ids_stay_compatible(self):
        raw,g,p,_=fixture('rough','bunker');fs=self.targets(raw,g,p)
        ids={f['selection_id'] for f in fs}
        self.assertTrue({'101','rough-ring:303:outer:0','rough-ring:303:inner:0','rough-way:200'}<=ids)
    def test_aliases(self):
        for tags,expected in [({'natural':'water'},'water'),({'golf':'water_hazard'},'water'),
                              ({'surface':'mulch'},'mulch'),({'natural':'wood'},'wood'),
                              ({'highway':'footway'},'path'),({'building':'yes'},'building')]:
            self.assertEqual(topology.surface_kind(tags),expected)
    def test_original_tags_and_relation_roles_survive(self):
        raw,g,p,_=fixture();fs=self.targets(raw,g,p)
        out,_=topology.render_translations(raw,fs,{'surface-way:101':(1.,0.)},g,p)
        before,after=ET.fromstring(raw),ET.fromstring(out)
        for tag in ('way','relation'):
            for elem in before.findall(tag):
                new=after.find("%s[@id='%s']"%(tag,elem.get('id')))
                self.assertEqual(elem.attrib,new.attrib)
                self.assertEqual(topology._tags(elem),topology._tags(new))
        self.assertEqual([m.get('role') for m in before.find('relation').findall('member')],
                         [m.get('role') for m in after.find('relation').findall('member')])
    def test_view_groups_include_all_requested_types(self):
        self.assertEqual([filter_kind({'kind':k}) for k in ['bunker','tee','green','fairway','rough','water','mulch','cartpath']],
                         ['bunker','tee','green','fairway','rough','water','mulch','paths'])


@unittest.skipUnless(INSTALLED,'Use --installed to exercise the complete installed analysis/export engine')
class InstalledPipelineTests(unittest.TestCase):
    def test_actual_review_export_all_surfaces(self):
        import tgc_local_alignment as engine
        raw,g,p,data=fixture('fairway','green',fragmented=True)
        with tempfile.TemporaryDirectory(prefix='tgc-local-v6-') as temp:
            folder=Path(temp);source=folder/'source.osm';source.write_bytes(raw)
            report=engine.analyze(data,source,1.5,-.5)
            by={f['selection_id']:f for f in report['features']}
            for sid in ['surface-way:101','surface-way:201','surface-way:202','surface-ring:303:outer:0']:
                self.assertIn(sid,by);self.assertTrue(by[sid]['manual_movable'],by[sid])
                self.assertFalse(by[sid]['movable']);self.assertEqual(by[sid]['status'],'manual_only')
            ids=['surface-way:101','surface-ring:303:inner:0','surface-way:201','surface-way:202']
            overrides={sid:dict(east_m=2.,north_m=-1.) for sid in ids}
            engine.validate_manual_offsets(report,overrides)
            out=folder/'saved.osm'
            result=engine.apply_reviewed(report,ids,out,current_data=data,current_nudge=(1.5,-.5),
                                         current_osm_file=source,manual_overrides=overrides)
            self.assertEqual(source.read_bytes(),raw)
            for wid in (101,201,202):
                np.testing.assert_allclose(xy(out.read_bytes(),wid,p,g)-xy(raw,wid,p,g),
                                           np.tile((2.,-1.),(len(xy(raw,wid,p,g)),1)),atol=1e-5)
            self.assertEqual(list(result['global_nudge_m']),[1.5,-.5])
            again=engine.analyze(data,out,1.5,-.5)
            self.assertTrue(again['features'])
    def test_group_validation_and_failed_export_keep_source(self):
        import tgc_local_alignment as engine
        raw,g,p,data=fixture('water','green')
        with tempfile.TemporaryDirectory(prefix='tgc-local-v6-') as temp:
            folder=Path(temp);source=folder/'source.osm';source.write_bytes(raw)
            report=engine.analyze(data,source,0,0);target=folder/'bad.osm'
            with self.assertRaises(Exception):
                engine.apply_reviewed(report,['surface-ring:303:inner:0'],target,
                    current_data=data,current_nudge=(0,0),current_osm_file=source,
                    manual_overrides={'surface-ring:303:inner:0':dict(east_m=190.,north_m=0.)})
            self.assertEqual(source.read_bytes(),raw);self.assertFalse(target.exists())


if __name__=='__main__':unittest.main(verbosity=2)
