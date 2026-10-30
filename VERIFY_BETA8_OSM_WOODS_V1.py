"""Standard OSM woodland/woodchip areas vs individual trees. Offline temporary fixtures."""
from pathlib import Path
import ast,copy,os,sys,tempfile,types,unittest,xml.etree.ElementTree as ET
import numpy as np
import overpy
import OSMTGC as o
import auto_red_mask as masks
import osm_preview_relations as overlay
import osm_water_mulch_lock as lock
from shapely.geometry import Polygon
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parent
class Way:
    def __init__(self,ident,tags,xy,ids=None):
        self.id=ident;self.tags=dict(tags)
        if ids is None:
            ids=list(range(ident*100,ident*100+len(xy)))
            if len(xy)>2 and xy[0]==xy[-1]:ids[-1]=ids[0]
        self.nodes=[types.SimpleNamespace(id=i,lon=float(x),lat=float(y),tags={}) for i,(x,y) in zip(ids,xy)]
    def get_nodes(self,resolve_missing=False):return self.nodes
class PC:
    def ulENU(self):return (0.,100.)
    def lrENU(self):return (100.,0.)
    def enuToTGC(self,x,y,z):return (x,z,y)
    def latlonToTGC(self,lat,lon,x_offset=0.,y_offset=0.):return (float(lon)+x_offset,0.,float(lat)+y_offset)
    def latlonToCV2(self,lat,lon,scale,x_offset=0.,y_offset=0.):return ((float(lat)+y_offset)/scale,(float(lon)+x_offset)/scale)
def rect(a=10,b=10,c=90,d=90):return [(a,b),(c,b),(c,d),(a,d),(a,b)]
def source():return dict(surfaceSplines2=[],holes3=[],surfaces2=[{'name':'Keep0'},{'name':'Keep1'},{'name':'Old','blend':.7,'maskWater':True}],height=[{'preserve':123}],placedObjects4={'keep':'exact'},terrainHeight=[{'keep':'exact'}])
def result(ways=None,rels=None,nodes=None):return types.SimpleNamespace(ways=ways or [],relations=rels or [],nodes=nodes or [])
def member(wid,role):return overpy.RelationWay(ref=wid,role=role)
def relation(ident,tags,members):return types.SimpleNamespace(id=ident,tags={'type':'multipolygon',**tags},members=members)
def run(r,**options):
    c=source();log=[];opts=dict(wood=True,tree=False,water=False,optimize_osm_spline_points=False);opts.update(options)
    trees=o.addOSMToTGC(c,PC(),r,options_dict=opts,course_version=25,resolve_missing_nodes=False,printf=log.append)
    return c,trees,log
class NativeTests(unittest.TestCase):
    def setUp(self):o.spline_configuration=None
    def woods(self,tags=None):return result([Way(1,tags or {'natural':'wood'},rect())],nodes=[types.SimpleNamespace(id=500,lat=50.,lon=50.,tags={'natural':'tree'})])
    def test_wood_only_no_tree_points(self):
        c,t,_=run(self.woods());self.assertEqual(len(c['surfaceSplines2']),1);self.assertEqual(t,[]);self.assertEqual(c['surfaceSplines2'][0]['surface'],10)
    def test_tree_only_no_wood(self):
        c,t,_=run(self.woods(),wood=False,tree=True);self.assertEqual(c['surfaceSplines2'],[]);self.assertEqual(len(t),1)
    def test_both_independent(self):
        c,t,_=run(self.woods(),tree=True);self.assertEqual((len(c['surfaceSplines2']),len(t)),(1,1))
    def test_neither(self):
        c,t,_=run(self.woods(),wood=False);self.assertEqual((c['surfaceSplines2'],t),([],[]))
    def test_default_woods_off(self):
        c=source();o.addOSMToTGC(c,PC(),self.woods(),options_dict={},course_version=25,resolve_missing_nodes=False,printf=lambda *_:None);self.assertEqual(c['surfaceSplines2'],[])
    def test_lidar_nodes_avoid_duplicates_but_keeps_woods(self):
        c,t,_=run(self.woods(),tree=True,lidar_trees=True);self.assertEqual(len(c['surfaceSplines2']),1);self.assertEqual(t,[])
    def test_forest_standard_alias(self):self.assertEqual(len(run(self.woods({'landuse':'forest'}))[0]['surfaceSplines2']),1)
    def test_woodchips_standard(self):self.assertEqual(len(run(self.woods({'surface':'woodchips','area':'yes'}))[0]['surfaceSplines2']),1)
    def test_no_private_tag_fallback(self):
        c,_,log=run(self.woods({'golf':'mulch','surface':'mulch'}));self.assertEqual(c['surfaceSplines2'],[]);self.assertTrue(any('obsolete' in x for x in log))
    def test_no_woodchip_tree_points(self):self.assertIsNone(o.classifyDryAreaForTGC({'natural':'tree','surface':'woodchips'}))
    def test_dry_material_not_water(self):
        c,t,_=run(self.woods());self.assertEqual(c[lock.DRY_LOCK_KEY]['importedCount'],1);self.assertNotIn(lock.LOCK_KEY,c);self.assertEqual(c['surfaces2'][2]['name'],'Mulch05')
    def test_other_course_data_unchanged(self):
        c,_,_=run(self.woods());s=source();[self.assertEqual(c[k],s[k]) for k in ('height','terrainHeight','placedObjects4','holes3')];self.assertEqual(c['surfaces2'][:2],s['surfaces2'][:2])
    def test_no_source_mutation(self):
        r=self.woods();b=copy.deepcopy(r);run(r);self.assertEqual(r.ways[0].tags,b.ways[0].tags);self.assertEqual(vars(r.ways[0].nodes[0]),vars(b.ways[0].nodes[0]))
    def test_open_wood_not_fabricated(self):self.assertEqual(run(result([Way(1,{'natural':'wood'},rect()[:-1])]))[0]['surfaceSplines2'],[])
    def test_distinct_end_ids_do_not_fabricate_closure(self):self.assertEqual(run(result([Way(1,{'natural':'wood'},rect(),ids=[1,2,3,4,5])]))[0]['surfaceSplines2'],[])
    def test_bowtie_rejected(self):self.assertEqual(run(result([Way(1,{'natural':'wood'},[(10,10),(50,50),(10,50),(50,10),(10,10)])]))[0]['surfaceSplines2'],[])
    def test_out_of_bounds_rejected(self):self.assertEqual(run(result([Way(1,{'natural':'wood'},rect(-1,10,50,50))]))[0]['surfaceSplines2'],[])
    def test_no_reclassification_of_water(self):
        c,_,_=run(result([Way(1,{'natural':'water','surface':'woodchips'},rect())]),water=True);self.assertIn(lock.LOCK_KEY,c);self.assertNotIn(lock.DRY_LOCK_KEY,c)
    def test_no_reclassification_of_paths(self):self.assertIsNone(o.classifyDryAreaForTGC({'surface':'woodchips','highway':'path'}))
    def test_newforest_native25_only(self):
        pts=[(x,0.,z) for x,z in rect()];self.assertEqual(o.newForest(pts,25)['surface'],10);self.assertEqual(o.newForest(pts,23)['surface'],7)
class RelationTests(unittest.TestCase):
    def fixture(self,fragment=False):
        outer=Way(1,{'natural':'wood'},rect());inner=Way(2,{},rect(30,30,50,50));ways=[outer,inner]
        members=[member(1,'outer'),member(2,'inner')]
        if fragment:
            ways=[Way(1,{},[(10,10),(90,10),(90,90)],[1,2,3]),Way(3,{},[(10,10),(10,90),(90,90)],[1,4,3]),inner];members=[member(3,'outer'),member(2,'inner'),member(1,'outer')]
        return result(ways,[relation(9,{'natural':'wood'},members)])
    def test_exact_inner_excluded(self):
        c,_,_=run(self.fixture());polys=[Polygon([(w['waypoint']['x'],w['waypoint']['z']) for w in s['waypoints']]) for s in c['surfaceSplines2']];u=unary_union(polys)
        self.assertLess(u.symmetric_difference(Polygon(rect(),[rect(30,30,50,50)])).area,.01)
    def test_no_duplicate_outer_way(self):self.assertEqual(len(run(self.fixture())[0]['surfaceSplines2']),2)
    def test_fragmented_unordered_reversed(self):self.assertEqual(len(run(self.fixture(True))[0]['surfaceSplines2']),2)
    def test_empty_role(self):
        r=self.fixture();r.relations[0].members[0].role='';self.assertEqual(len(run(r)[0]['surfaceSplines2']),2)
    def test_missing_inner_ref_rejected(self):
        r=self.fixture();r.relations[0].members.append(member(998,'inner'));self.assertEqual(run(r)[0]['surfaceSplines2'],[])
    def test_nonway_inner_rejected(self):
        r=self.fixture();r.relations[0].members.append(types.SimpleNamespace(role='inner',ref=2));self.assertEqual(run(r)[0]['surfaceSplines2'],[])
    def test_partial_outside_inner_rejected(self):
        r=self.fixture();r.ways[1]=Way(2,{},rect(80,80,95,95));self.assertEqual(run(r)[0]['surfaceSplines2'],[])
    def test_relation_tags_unchanged(self):
        r=self.fixture();run(r);self.assertEqual(r.relations[0].tags,{'type':'multipolygon','natural':'wood'})
    def test_separate_inner_green_remains_green(self):
        r=self.fixture();r.ways[1].tags={'golf':'green'};c,_,_=run(r);self.assertEqual([s['surface'] for s in c['surfaceSplines2']].count(1),1)
    def test_disabled_relation_does_not_fall_back_to_tagged_outer(self):self.assertEqual(run(self.fixture(),wood=False)[0]['surfaceSplines2'],[])
    def test_no_water_tracking(self):self.assertNotIn(lock.LOCK_KEY,run(self.fixture())[0])
class DisplayTests(unittest.TestCase):
    def test_mask_standard_wood(self):self.assertEqual(masks._feature_mode_and_width_m(Way(1,{'natural':'wood'},rect())),('area',0.))
    def test_mask_forest(self):self.assertEqual(masks._feature_mode_and_width_m(Way(1,{'landuse':'forest'},rect())),('area',0.))
    def test_mask_woodchips(self):self.assertEqual(masks._feature_mode_and_width_m(Way(1,{'surface':'woodchips'},rect())),('area',0.))
    def test_dry_never_blue_water(self):self.assertFalse(masks._is_water_feature(Way(1,{'natural':'wood'},rect())))
    def test_preview_woods_not_blue(self):
        out=o.addOSMToImage([Way(1,{'natural':'wood'},rect())],np.zeros((100,100,3),np.float32),PC(),1.,printf=lambda *_:None);np.testing.assert_allclose(out[50,50],[.75,.45,.3])
    def test_relation_preview_hole(self):
        r=RelationTests().fixture();out=o.addOSMToImage(r,np.zeros((100,100,3),np.float32),PC(),1.,printf=lambda *_:None);np.testing.assert_allclose(out[20,20],[.75,.45,.3]);np.testing.assert_allclose(out[40,40],[0,0,0])
    def test_mask_preserves_area_and_hole(self):
        r=RelationTests().fixture();out=masks.apply_auto_red_mask(r,np.ones((100,100,3),np.float32)*.5,PC(),1.,buffer_m=0,printf=lambda *_:None);self.assertFalse(np.allclose(out[20,20],[1,0,0]));np.testing.assert_allclose(out[40,40],[1,0,0])
    def test_local_editor_and_filter(self):
        from tgc_local_alignment_topology import surface_kind
        from tgc_local_feature_filters import filter_kind
        self.assertEqual(surface_kind({'natural':'wood'}),'wood');self.assertEqual(surface_kind({'surface':'woodchips'}),'mulch');self.assertEqual(filter_kind({'kind':'wood'}),'mulch')
    def test_cfs_uses_same_standard_semantics(self):
        s=(ROOT/'osm_alignment_viewer.py').read_text();n=next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=='_feature_style')
        ns={'OSMTGC':o,'FEATURE_COLORS':{'mulch':'test'}};exec(compile(ast.Module(body=[n],type_ignores=[]),'actual_cfs_method','exec'),ns)
        self.assertEqual(ns['_feature_style']({'natural':'wood'}),('mulch','test'));self.assertEqual(ns['_feature_style']({'surface':'woodchips'}),('mulch','test'))
class ExportTests(unittest.TestCase):
    def test_standard_svg_tags(self):
        import tgc_unity_raw_svg as core
        features=[dict(id='a',group='Trees',fill='#faa0be',kind='wood',geometry=Polygon(rect(10,10,20,20))),dict(id='b',group='Mulch',fill='#bca',kind='mulch',geometry=Polygon(rect(30,30,40,40)))]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'out.osm';core.write_osm(path,features,100,100);root=ET.parse(path).getroot();tags=[{t.get('k'):t.get('v') for t in w.findall('tag')} for w in root.findall('way')]
            self.assertEqual(tags[0]['natural'],'wood');self.assertEqual(tags[1]['surface'],'woodchips');self.assertTrue(all(t.get('golf')!='mulch' for t in tags));self.assertEqual(root.get('upload'),'never');self.assertFalse(any(k.startswith('tgc:') for t in tags for k in t))
    def test_build_does_not_restore_private_tag(self):
        s=(ROOT/'tgc_unity_build_check.py').read_text();self.assertIn("t.get('surface')=='woodchips'",s);self.assertNotIn("t.get('golf')=='mulch'",s)
    def test_beta8_kept(self):
        s=(ROOT/'BUILD_TGC_2K25_BETA8.py').read_text();self.assertIn("EXE_NAME='tgc_gui_2k25_beta8_1'",s);self.assertIn("VERIFY_BETA8_OSM_WOODS_V1.py",s)
    def test_no_liDAR_processing_change(self):
        s=(ROOT/'tgc_gui.py').read_text();self.assertIn('Add Trees From Lidar (Experimental)',s);self.assertIn('Import Individual OSM Tree Points',s)
@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'Tk display not available')
class UITests(unittest.TestCase):
    def test_actual_checkbox_block_independent_defaults_and_commands(self):
        import tkinter as tk
        from tkinter import Checkbutton
        s=(ROOT/'tgc_gui.py').read_text();a=s.index('# TGC_BETA8_STANDARD_OSM_WOODS_V1: independent');b=s.index('options_entries_dict["optimize_osm_spline_points"]',a)
        root=tk.Tk();root.withdraw()
        try:
            ns=dict(tk=tk,Checkbutton=Checkbutton,osmSubFrame=tk.Frame(root),options_entries_dict={},check_fg='black',check_bg='#d4d7db')
            exec(s[a:b],ns);v=ns['options_entries_dict'];self.assertFalse(v['wood'].get());self.assertFalse(v['tree'].get())
            ns['woodCheck'].invoke();self.assertTrue(v['wood'].get());self.assertFalse(v['tree'].get());ns['treeCheck'].invoke();self.assertTrue(v['tree'].get());self.assertTrue(v['wood'].get())
            ns['woodCheck'].invoke();self.assertFalse(v['wood'].get());self.assertTrue(v['tree'].get())
        finally:root.destroy()
if __name__=='__main__':unittest.main(verbosity=2)
