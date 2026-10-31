"""Optional natural=wood course splines, independent of tree points and terrain masks."""
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
    def test_other_land_cover_is_not_native_mulch(self):
        for tags in ({'landuse':'meadow'}, {'landuse':'forest'}, {'natural':'grassland'},
                     {'surface':'woodchips','area':'yes'}, {'landcover':'trees'},
                     {'natural':'wood','landuse':'meadow'}, {'natural':'wood','area':'no'}):
            with self.subTest(tags=tags):
                course, _, _ = run(self.woods(tags))
                self.assertEqual(course['surfaceSplines2'], [])
                self.assertNotIn(lock.DRY_LOCK_KEY, course)
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
    @staticmethod
    def surface_geometry(course):
        return unary_union([Polygon([(p['waypoint']['x'],p['waypoint']['z'])
            for p in s['waypoints']]) for s in course['surfaceSplines2']])

    def test_meadow_shell_never_imported_but_wood_inner_is(self):
        for outer_tags in ({}, {'natural':'wood'}):
            with self.subTest(outer_tags=outer_tags):
                woods=Way(2,{'natural':'wood'},rect(30,30,50,50))
                r=result([Way(1,outer_tags,rect()),woods],
                         [relation(9,{'landuse':'meadow'},[member(1,'outer'),member(2,'inner')])])
                course,_,_=run(r)
                self.assertEqual(len(course['surfaceSplines2']),1)
                # Compare the complete native spline, including curved handles,
                # to an import of the wood island on its own.
                self.assertEqual(course['surfaceSplines2'],run(result([woods]))[0]['surfaceSplines2'])

    def test_wood_relation_preserves_meadow_cutout(self):
        r=self.fixture();r.ways[1].tags={'landuse':'meadow'}
        course,_,_=run(r)
        self.assertLess(self.surface_geometry(course).symmetric_difference(
            Polygon(rect(),[rect(30,30,50,50)])).area,.01)

    def test_wood_relation_cannot_claim_closed_meadow_shell(self):
        r=self.fixture();r.ways[0].tags={'landuse':'meadow'}
        course,_,_=run(r)
        self.assertEqual(course['surfaceSplines2'],[])

    def test_meadow_shared_edge_is_not_a_shared_shell(self):
        edge=Way(1,{},[(10,50),(90,50)],[1,2])
        north=Way(2,{},[(90,50),(90,90),(10,90),(10,50)],[2,3,4,1])
        south=Way(3,{},[(90,50),(90,10),(10,10),(10,50)],[2,5,6,1])
        wood=relation(10,{'natural':'wood'},[member(1,'outer'),member(2,'outer')])
        meadow=relation(11,{'landuse':'meadow'},[member(1,'outer'),member(3,'outer')])
        r=result([edge,north,south],[wood,meadow])
        course,_,_=run(r)
        self.assertEqual(len(course['surfaceSplines2']),1)
        self.assertEqual(course['surfaceSplines2'],run(result([edge,north],[wood]))[0]['surfaceSplines2'])
        meadow.members=[member(2,'outer'),member(1,'outer')]
        self.assertEqual(run(r)[0]['surfaceSplines2'],[])

    def test_wood_relation_leaves_explicit_waterway_inner_independent(self):
        r=self.fixture();r.ways[1].tags={'waterway':'river','area':'yes'}
        course,_,_=run(r,water=True)
        self.assertEqual(course[lock.LOCK_KEY]['importedCount'],1)
        self.assertGreater(course[lock.DRY_LOCK_KEY]['importedCount'],0)

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
    def test_ground_cover_is_not_a_mask_feature(self):
        for tags in ({'natural':'wood'}, {'landuse':'meadow'}, {'landuse':'forest'},
                     {'surface':'woodchips'}, {'golf':'mulch'}):
            with self.subTest(tags=tags):
                w = Way(1, tags, rect())
                self.assertEqual(masks._feature_mode_and_width_m(w), (None, 0.))
                self.assertFalse(masks._is_water_feature(w))

    @staticmethod
    def layout(projection, with_ground_cover):
        # A real green inside a meadow, a water polygon, and a fairway with
        # a hole must render identically with and without the ground cover.
        root = ET.Element('osm', version='0.6'); coords = {}
        def way(wid, points, tags):
            refs = []
            for x, y in points:
                if (x,y) not in coords:
                    nid = len(coords) + 1; coords[x,y] = nid
                    lon,lat = projection(400000.25+x, 3280000.25+y, inverse=True)
                    ET.SubElement(root,'node',id=str(nid),lon=str(lon),lat=str(lat))
                refs.append(coords[x,y])
            w = ET.SubElement(root,'way',id=str(wid))
            for ref in refs: ET.SubElement(w,'nd',ref=str(ref))
            for k,v in tags.items(): ET.SubElement(w,'tag',k=k,v=v)
        def rel(rid,tags,outer,inner):
            r = ET.SubElement(root,'relation',id=str(rid))
            for wid,role in ((outer,'outer'),(inner,'inner')):
                ET.SubElement(r,'member',type='way',ref=str(wid),role=role)
            for k,v in dict(type='multipolygon',**tags).items(): ET.SubElement(r,'tag',k=k,v=v)
        way(1,rect(4,4,14,14),{'natural':'water'})
        way(2,rect(70,8,80,18),{'golf':'green'})
        extra = {'landuse':'forest','surface':'woodchips','natural':'wood'} if with_ground_cover else {}
        way(3,rect(20,55,65,95),{'golf':'fairway',**extra})
        way(4,rect(36,68,51,83),{}); rel(30,{'golf':'fairway'},3,4)
        if with_ground_cover:
            way(5,rect(64,3,92,44),{}); rel(31,{'landuse':'meadow'},5,2)
            way(6,rect(21,5,58,50),{'natural':'wood'}); way(7,rect(30,12,40,26),{})
            rel(32,{'natural':'wood'},6,7)
            way(8,rect(70,50,80,60),{'natural':'wood'})
            way(9,rect(5,48,15,64),{'landuse':'forest'})
            way(10,rect(65,75,85,87),{'area':'yes','surface':'woodchips'})
        return ET.tostring(root)

    def test_initial_and_shifted_saved_masks_are_ground_cover_invariant(self):
        import cv2, pyproj
        import lidar_map_api, osm_mask_alignment as aligned
        p = pyproj.Proj('epsg:32614')
        terrain = {'heightmap':np.arange(10000,dtype=np.float32).reshape(100,100),
                   'projection':p,'image_scale':1.,'master_grid':{'rows':100,'cols':100,
                   'lower_left_latlon':list(reversed(p(400000.,3280000.,inverse=True))),
                   'min_x':400000.,'min_y':3280000.,'max_x':400100.,'max_y':3280100.,
                   'resolution':1.,'row_order':'south_up_internal','origin_semantics':'southwest_cell_edge'}}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); source = folder/'layout.osm'; hp = folder/'heightmap.npy'
            np.save(hp, terrain); baselines = {}; quiet = lambda *_: None
            for enriched in (False,True):
                source.write_bytes(self.layout(p,enriched))
                for auto in (False,True):
                    for shifted in (False,True):
                        with self.subTest(enriched=enriched,auto=auto,shifted=shifted):
                            if shifted:
                                status = aligned.rebuild_aligned_mask(folder,source,2.,-1.,auto,3.,
                                                                      backup_existing=False,printf=quiet)
                                expected = status['record']; older = dict(expected)
                                del older['mask_feature_policy']
                                # Old, otherwise current sidecars need attention only on affected maps.
                                self.assertEqual(aligned._signatures_match(older,expected)[0], not enriched)
                            else:
                                lidar_map_api._write_osm_master_mask(terrain,hp,source,auto,3.,printf=quiet)
                            pixels = cv2.imread(str(folder/'mask.png'))
                            self.assertTrue(np.any(np.all(pixels==[255,0,0],axis=2)))  # water (BGR)
                            self.assertTrue(np.any(np.all(pixels==[51,255,0],axis=2)))  # green
                            self.assertEqual(bool(np.any(np.all(pixels==[0,0,255],axis=2))),auto)
                            key = auto,shifted
                            if enriched: np.testing.assert_array_equal(pixels,baselines[key])
                            else: baselines[key] = pixels
            self.assertFalse(np.array_equal(baselines[True,False],baselines[True,True]))

    def test_local_editor_and_filter(self):
        from tgc_local_alignment_topology import surface_kind
        from tgc_local_feature_filters import filter_kind
        self.assertEqual(surface_kind({'natural':'wood'}),'wood')
        self.assertEqual(filter_kind({'kind':'wood'}),'mulch')
        for tags,kind in (({'landuse':'forest'},'forest'),({'surface':'woodchips'},'woodchips')):
            self.assertEqual(surface_kind(tags),kind)
            self.assertEqual(filter_kind({'kind':kind}),'other')
        self.assertIsNone(surface_kind({'landuse':'meadow'}))

    def test_cfs_vector_overlay_can_show_natural_wood(self):
        from osm_alignment_viewer import _feature_style
        self.assertEqual(_feature_style({'natural':'wood'})[0],'mulch')
        for tags in ({'landuse':'forest'},{'landuse':'meadow'},{'surface':'woodchips'}):
            self.assertNotEqual(_feature_style(tags)[0],'mulch')

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
        b=(ROOT/'BUILD_TGC_2K25_BETA8_2.py').read_text();self.assertIn("EXE_NAME='tgc_gui_2k25_beta8_2'",b)
        self.assertIn('VERIFY_BETA8_OSM_WOODS_V1.py',(ROOT/'BUILD_TGC_2K25_BETA8.py').read_text())
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
