"""Native dependency/source tests; --osm/--dem also benchmark an actual preview."""
from pathlib import Path
import ast, copy, hashlib, importlib.util, json, sys, threading, time, types, unittest
from unittest.mock import patch
import numpy as np
import pyproj
import tgc_projection_cache as cache
import tgc_dem_preview as dp
from GeoPointCloud import GeoPointCloud


def obj(i,tags=None):return types.SimpleNamespace(id=i,tags=tags or {})
class RelationWay:
    def __init__(self,ref,role):self.ref=ref;self.role=role
class RelationNode(RelationWay):pass
class RelationRelation(RelationWay):pass


def pc(crs=32610):
    p=GeoPointCloud();p.proj=pyproj.Proj('EPSG:'+str(crs));p.origin=(100.,200.);p.width=1000;p.height=2000
    return p

class Tests(unittest.TestCase):
    def setUp(self):cache.clear_thread_cache()
    def test_01_one_factory_per_direction(self):
        p=pc();real=pyproj.Transformer.from_proj
        with patch.object(pyproj.Transformer,'from_proj',wraps=real) as f:
            for _ in range(100):xy=p.latlonToProj(38.,-122.)
            self.assertEqual(f.call_count,1)
            for _ in range(100):p.projToLatLon(*xy)
            self.assertEqual(f.call_count,2)
    def test_02_original_coordinates(self):
        for epsg,lat,lon in [(32610,38.,-122.),(6628,20.,-155.82),(6635,20.,-155.82),(32755,-30.,147.)]:
            p=pc(epsg);f=pyproj.Transformer.from_proj(p._platlon,p.proj,True)
            for d in (0.,.001,-.001):
                self.assertEqual(p.latlonToProj(lat+d,lon),f.transform(lon,lat+d))
    def test_03_reverse_unchanged(self):
        p=pc();xy=p.latlonToProj(38.,-122.);tr=pyproj.Transformer.from_proj(p.proj,p._platlon,True)
        lon,lat=tr.transform(*xy);self.assertEqual(p.projToLatLon(*xy),(lat,lon))
    def test_04_origin_not_cached(self):
        p=pc();a=p.latlonToENU(38.,-122.);p.origin=(103.,195.);b=p.latlonToENU(38.,-122.)
        self.assertEqual(b,(a[0]-3,a[1]+5))
    def test_05_crs_change_invalidates(self):
        p=pc();a=p.latlonToProj(38.,-122.);p.proj=pyproj.Proj('EPSG:32611');b=p.latlonToProj(38.,-122.)
        self.assertNotEqual(a,b);self.assertEqual(b,pyproj.Transformer.from_proj(p._platlon,p.proj,True).transform(-122.,38.))
    def test_06_each_thread_has_own_transform(self):
        p=pc();results=[]
        a=cache.from_proj(p._platlon,p.proj)
        t=threading.Thread(target=lambda:results.append(cache.from_proj(p._platlon,p.proj)));t.start();t.join()
        self.assertIsNot(a,results[0])
    def test_07_bounded_cache(self):
        src=pyproj.Proj('EPSG:4326')
        for _ in range(36):cache.from_proj(src,pyproj.Proj('EPSG:32610'))
        self.assertLessEqual(len(cache._STATE.pairs),32)
    def test_08_no_pc_state_change(self):
        p=pc();before=dict(p.__dict__);p.latlonToProj(38.,-122.);self.assertEqual(before,p.__dict__)
    def test_09_copies_work(self):
        p=pc();a=p.latlonToProj(38.,-122.);q=copy.copy(p);self.assertEqual(a,q.latlonToProj(38.,-122.))
    def test_10_forward_axis_order(self):
        p=pc();x,y=p.latlonToProj(38.,-122.);self.assertTrue(0<x<1e6 and 3e6<y<5e6)
    def test_11_roads_and_streams_kept(self):
        for tags in [{'highway':'residential'},{'highway':'service'},{'waterway':'stream'},{'golf':'cartpath'},{'golf':'hole'},{'natural':'water'}]:self.assertTrue(dp.relevant_tags(tags))
    def test_12_context_not_selected(self):
        for tags in [{'natural':'coastline'},{'landuse':'residential'},{'boundary':'administrative'},{'route':'road'}]:self.assertFalse(dp.relevant_tags(tags))
    def test_13_relation_members_not_lost(self):
        ways=[obj(1),obj(2),obj(3,{'natural':'coastline'})]
        r=obj(20,{'type':'multipolygon','golf':'fairway'});r.members=[RelationWay(1,'outer'),RelationWay(2,' inner ')]
        source=types.SimpleNamespace(ways=ways,relations=[r],nodes=[])
        v,info=dp.select_render_features(source);self.assertEqual([w.id for w in v.ways],[1,2]);self.assertEqual(v.relations,[r])
    def test_14_road_in_residential_area_kept(self):
        self.assertTrue(dp.relevant_tags({'highway':'residential','landuse':'residential'}))
    def test_15_unselected_members_not_expanded(self):
        w=obj(1);r=obj(2,{'type':'multipolygon','landuse':'residential'});r.members=[RelationWay(1,'outer')]
        v,_=dp.select_render_features(types.SimpleNamespace(ways=[w],relations=[r],nodes=[]));self.assertEqual(v.ways,[])
    def test_16_input_not_mutated(self):
        w=obj(1,{'golf':'green'});s=types.SimpleNamespace(ways=[w],relations=[],nodes=[])
        v,_=dp.select_render_features(s);self.assertIs(v.ways[0],w);self.assertIsNot(v.ways,s.ways);self.assertEqual(len(s.ways),1)
    def test_17_none_and_legacy_lists(self):
        self.assertEqual(dp.select_render_features(None),(None,None));s=[obj(1)];self.assertIs(dp.select_render_features(s)[0],s)
    def test_18_no_osm_gray_unchanged(self):
        import cv2
        gray=np.arange(25,dtype=np.float32).reshape(5,5)/25
        got=dp.build_mask(gray,None,2,None,normalize=lambda a:a.copy(),draw=None,auto_mask=None,printf=lambda *_:None)
        self.assertTrue(np.array_equal(got,cv2.cvtColor(gray,cv2.COLOR_GRAY2RGB)))
    def test_19_full_options_forwarded(self):
        calls=[]
        def draw(s,im,p,scale,**kw):calls.append(('draw',scale,kw));return im
        def auto(s,im,p,scale,**kw):calls.append(('auto',scale,kw));return im
        s=types.SimpleNamespace(ways=[],relations=[],nodes=[])
        dp.build_mask(np.zeros((3,3),np.float32),None,4,s,normalize=lambda a:a,draw=draw,auto_mask=auto,auto_red_mask_enabled=True,auto_red_mask_buffer_m=17,x_offset=3,y_offset=-4,printf=lambda *_:None)
        self.assertEqual([a[0] for a in calls],['draw','auto']);self.assertEqual(calls[1][2]['buffer_m'],17)
        self.assertEqual(calls[0][2]['x_offset'],3);self.assertEqual(calls[1][2]['y_offset'],-4)
    def test_20_off_does_not_call_auto(self):
        def fail(*a,**k):raise AssertionError('auto called')
        dp.build_mask(np.zeros((2,2),np.float32),None,2,types.SimpleNamespace(ways=[],relations=[]),normalize=lambda a:a,draw=lambda s,im,*a,**k:im,auto_mask=fail,printf=lambda *_:None)
    def test_21_phase_messages(self):
        logs=[];dp.build_mask(np.zeros((2,2),np.float32),None,2,None,normalize=lambda a:a,draw=None,auto_mask=None,printf=logs.append)
        self.assertTrue(any('[0% phase]' in l for l in logs));self.assertTrue(any('complete in' in l for l in logs))
    def test_22_only_three_function_hooks(self):
        root=Path(__file__).resolve().parent
        geo=(root/'GeoPointCloud.py').read_text(encoding='utf-8-sig');dem=(root/'dem_map_api.py').read_text(encoding='utf-8-sig')
        self.assertEqual(geo.count('from tgc_projection_cache import from_proj'),2)
        self.assertEqual(dem.count('from tgc_dem_preview import build_mask'),1)
    def test_23_custom_offsets_pixel_math_unchanged(self):
        p=pc();tr=pyproj.Transformer.from_proj(p._platlon,p.proj,True)
        q=copy.copy(p);q.latlonToProj=lambda lat,lon:tr.transform(lon,lat)
        for scale in (1.,2.,4.,6.):
            for x,y in ((0,0),(2,-2),(-28,31)):
                self.assertEqual(p.latlonToCV2(38.,-122.,scale,x,y),q.latlonToCV2(38.,-122.,scale,x,y))
    def test_24_native_overpy(self):
        try:import overpy
        except ImportError:self.skipTest('native overpy unavailable')
        if not getattr(overpy,'__file__',None):self.skipTest('test XML adapter is not native overpy')
        r=overpy.Overpass().parse_xml('<osm version="0.6"><node id="1" lat="20" lon="-155"/><node id="2" lat="20.1" lon="-155"/><way id="3"><nd ref="1"/><nd ref="2"/><tag k="waterway" v="stream"/></way></osm>')
        v,_=dp.select_render_features(r);self.assertEqual(len(v.ways),1);self.assertEqual(len(v.ways[0].get_nodes(resolve_missing=False)),2)


def main():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':sys.exit(main())
