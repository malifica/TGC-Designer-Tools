"""Focused offline regression suite. Uses native overpy when installed.
The stdlib fixture adapter is ONLY a test fallback, never application code.
"""
from pathlib import Path
import argparse,ast,base64,copy,gzip,importlib.util,json,math,sys,tempfile,types,unittest,xml.etree.ElementTree as ET
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parent
USING_ADAPTER=False
try:
    import overpy
except ImportError:
    USING_ADAPTER=True
    overpy=types.ModuleType('overpy')
    class DataIncomplete(ValueError): pass
    class RelationWay:
        def __init__(self,ref,role): self.ref=int(ref);self.role=role
    class RelationNode(RelationWay): pass
    class Way:
        def __init__(self,element,nodes):
            self.id=int(element.get('id'));self.tags={t.get('k'):t.get('v') for t in element.findall('tag')}
            self._node_ids=[int(n.get('ref')) for n in element.findall('nd')];self.lookup=nodes
        def get_nodes(self,resolve_missing=False):
            try:return [self.lookup[i] for i in self._node_ids]
            except KeyError as exc:raise DataIncomplete(str(exc))
        @property
        def nodes(self):return self.get_nodes()
    class Overpass:
        def parse_xml(self,text):
            tree=ET.fromstring(text);nodes={}
            for n in tree.findall('node'):
                nodes[int(n.get('id'))]=types.SimpleNamespace(id=int(n.get('id')),lat=float(n.get('lat')),lon=float(n.get('lon')),tags={t.get('k'):t.get('v') for t in n.findall('tag')})
            ways=[Way(e,nodes) for e in tree.findall('way')];relations=[]
            for e in tree.findall('relation'):
                members=[(RelationNode if m.get('type')=='node' else RelationWay)(m.get('ref'),m.get('role','')) for m in e.findall('member')]
                relations.append(types.SimpleNamespace(id=int(e.get('id')),tags={t.get('k'):t.get('v') for t in e.findall('tag')},members=members))
            return types.SimpleNamespace(nodes=list(nodes.values()),ways=ways,relations=relations)
    overpy.RelationWay=RelationWay;overpy.RelationNode=RelationNode;overpy.Overpass=Overpass
    overpy.exception=types.SimpleNamespace(OverPyException=ValueError,DataIncomplete=DataIncomplete)
    sys.modules['overpy']=overpy

class Flat:
    def latlonToCV2(self,lat,lon,scale,x_offset=0,y_offset=0):
        return (int((float(lat)+y_offset)/scale),int((float(lon)+x_offset)/scale))

def osm_fixture(kind='fairway',fragmented=False,incomplete=False):
    nodes=[(1,10,10),(2,60,10),(3,60,60),(4,10,60),(5,25,25),(6,40,25),(7,40,40),(8,25,40)]
    s='<osm version="0.6">'+''.join('<node id="%d" lat="%s" lon="%s"/>'%(i,y,x) for i,x,y in nodes)
    def way(i,refs,tags=''):
        return '<way id="%d">'%i+''.join('<nd ref="%d"/>'%j for j in refs)+tags+'</way>'
    if fragmented:
        s+=way(100,[1,2,3])+way(101,[1,4,3])
        outer='<member type="way" ref="101" role="outer"/><member type="way" ref="100" role="outer"/>'
    else:
        s+=way(100,[1,2,3,4,1]);outer='<member type="way" ref="100" role="outer"/>'
    s+=way(102,[5,6,7] if incomplete else [5,6,7,8,5])
    s+='<relation id="200">'+outer+'<member type="way" ref="102" role="inner"/><tag k="type" v="multipolygon"/>'
    s+=('<tag k="natural" v="water"/>' if kind=='water' else '<tag k="golf" v="'+kind+'"/>')+'</relation></osm>'
    return overpy.Overpass().parse_xml(s)

def palette():return [{'name':n,'blend':.6,'maskWater':True} for n in ['Sand09','PineStraw02','Mulch05','Asphalt01B','Concrete02','Cobbles01','Green07','Fringe07','Fairway07','LightRough07','HeavyRough07','Splat0_A','Splat1_B','Splat2_C','Splat3_D']]

def main(root=ROOT,osm_path=None):
    root=Path(root).resolve();sys.path.insert(0,str(root))
    import OSMTGC as osm
    import auto_red_mask as arm
    import osm_water_mulch_lock as lock
    points=[(0.,0.,0.),(15.,0.,0.),(15.,0.,20.),(0.,0.,20.),(0.,0.,0.)]
    silent=lambda *_:None
    def draw(data,byte=False,x=0,y=0):
        im=np.full((90,100,3),.31,np.float32)
        if byte:im=np.full((90,100,3),79,np.uint8)
        return osm.addOSMToImage(data,im,Flat(),1.,x_offset=x,y_offset=y,printf=silent)
    class Tests(unittest.TestCase):
        def setUp(self):osm.spline_configuration=None;osm.last_imported_water_splines=[]
        def test_01_relation_without_auto_mask(self):
            im=draw(osm_fixture());np.testing.assert_allclose(im[15,15],(0,.75,.2));np.testing.assert_allclose(im[30,30],(.31,)*3)
            np.testing.assert_allclose(im[80,80],(.31,)*3)
        def test_02_relation_rough(self):
            im=draw(osm_fixture('rough'));np.testing.assert_allclose(im[15,15],(0,.55,.15))
        def test_03_relation_water_hole_pure_blue(self):
            im=draw(osm_fixture('water'));np.testing.assert_array_equal(im[15,15],(0,0,1));np.testing.assert_allclose(im[30,30],(.31,)*3)
        def test_04_unordered_reversed_fragments(self):
            np.testing.assert_array_equal(draw(osm_fixture(fragmented=True)),draw(osm_fixture()))
        def test_05_incomplete_inner_does_not_fill_hole(self):
            np.testing.assert_allclose(draw(osm_fixture(incomplete=True)),.31)
        def test_06_offsets_propagate_without_new_transform(self):
            a=draw(osm_fixture());b=draw(osm_fixture(),x=7,y=9);np.testing.assert_array_equal(a[:81,:93],b[9:,7:])
        def test_07_uint8_water_is_255(self):
            im=draw(osm_fixture('water'),byte=True);np.testing.assert_array_equal(im[15,15],(0,0,255));np.testing.assert_array_equal(im[30,30],(79,)*3)
        def test_08_auto_on_keeps_relation_and_red(self):
            r=osm_fixture('water');im=arm.apply_auto_red_mask(r,draw(r),Flat(),1,buffer_m=5,printf=silent)
            np.testing.assert_array_equal(im[15,15],(0,0,1));np.testing.assert_array_equal(im[80,80],(1,0,0));self.assertFalse(np.array_equal(im[30,30],(0,0,1)))
        def test_09_all_production_image_calls_have_results(self):
            for filename,count in [('lidar_map_api.py',3),('dem_map_api.py',1),('osm_mask_alignment.py',1),('tgc_gui.py',1)]:
                calls=[n for n in ast.walk(ast.parse((root/filename).read_text(encoding='utf-8-sig'))) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='addOSMToImage']
                self.assertEqual(len(calls),count)
                for call in calls:self.assertFalse(isinstance(call.args[0],ast.Attribute) and call.args[0].attr=='ways')
        def test_10_default_water_and_stream_category_10(self):
            for area in (False,True):self.assertEqual(osm.newWaterHazard(points,area,25)['surface'],10)
        def test_11_legacy_overrides_cannot_turn_water_into_road(self):
            for value in ('surface1','surface2','surface3','asphalt','cartpath',7,8,10):
                osm.spline_configuration={'water':{'primarySurface':value,'pathWidth':.12},'stream':{'primarySurface':value,'pathWidth':3.7}}
                a=osm.newWaterHazard(points,True,25);b=osm.newWaterHazard(points,False,25)
                self.assertEqual(a['surface'],10);self.assertEqual(b['surface'],10);self.assertEqual(a['width'],.12);self.assertEqual(b['width'],3.7)
        def test_12_native_cartpath_and_road_are_separate(self):
            c=osm.newCartPath(points,False,25,optimize_points=False);r=osm.newRoad(points,False,25,optimize_points=False)
            self.assertEqual(c['surface'],7);self.assertEqual(r['surface'],8)
        def test_13_legacy_game_water_unchanged(self):
            self.assertEqual(osm.newWaterHazard(points,True,23)['surface'],8)
        def test_14_cartpath_width_3p4_retained(self):
            osm.spline_configuration={'cartpath':{'primarySurface':'cartpath','pathWidth':3.4}}
            s=osm.newCartPath(points,False,25,optimize_points=False);self.assertEqual(s['width'],3.4);self.assertEqual(s['surface'],7)
        def test_15_material_pin_only_one_slot(self):
            s=osm.newWaterHazard(points,True,25);c={'surfaceSplines2':[s],'surfaces2':palette(),'height':[{'value':4}]}
            c['surfaces2'][2]['name']='Concrete02';before=copy.deepcopy(c)
            lock.mark_import(c,[s],25,silent);self.assertEqual(c['surfaces2'][2]['name'],'Mulch05')
            del c[lock.LOCK_KEY];before['surfaces2'][2]['name']='Mulch05';self.assertEqual(c,before)
        def test_16_final_export_wins_after_theme_reapplication(self):
            s=osm.newWaterHazard(points,True,25);c={'surfaceSplines2':[s],'surfaces2':palette()};lock.mark_import(c,[s],25,silent)
            c['surfaces2'][2]['name']='Asphalt01B';m={'name':'test','surfaces2':palette()};m['surfaces2'][2]['name']='Concrete02'
            a,b=lock.finalize_serialized(json.dumps(c),json.dumps(m),25)
            self.assertEqual(json.loads(a)['surfaces2'][2]['name'],'Mulch05');self.assertEqual(json.loads(b)['surfaces2'][2]['name'],'Mulch05')
        def test_17_unmarked_course_not_reinterpreted(self):
            c={'surfaceSplines2':[{'surface':10}],'surfaces2':palette()};c['surfaces2'][2]['name']='Asphalt01B';a=json.dumps(c,indent=2);b='{"name":"existing"}'
            self.assertEqual(lock.finalize_serialized(a,b,25),(a,b))
        def test_18_no_imported_water_no_material_change(self):
            c={'surfaceSplines2':[],'surfaces2':palette()};before=copy.deepcopy(c);lock.mark_import(c,[],25,silent);self.assertEqual(c,before)
        def test_19_export_gate_is_before_encoding(self):
            t=(root/'tgc_tools.py').read_text(encoding='utf-8-sig');f=t[t.index('def pack_course_file'):t.index('def get_course_json')]
            self.assertLess(f.index('finalize_serialized('),f.index('desc_encoded ='))
        def test_20_no_relations_identical_to_way_only(self):
            r=osm_fixture();r=types.SimpleNamespace(ways=r.ways,relations=[],nodes=r.nodes)
            # A normal independent fairway, green and water way.
            r.ways[0].tags={'golf':'fairway'};r.ways[1].tags={'golf':'green'}
            np.testing.assert_array_equal(draw(r),draw(r.ways))
        def test_21_independent_green_in_fairway_island(self):
            r=osm_fixture();r.ways[1].tags={'golf':'green'}
            im=draw(r);np.testing.assert_allclose(im[30,30],(0,1,.2));np.testing.assert_allclose(im[15,15],(0,.75,.2))
        def test_22_full_water_relation_import_locked(self):
            r=osm_fixture('water')
            class CoursePC(Flat):
                def ulENU(self):return (0,90)
                def lrENU(self):return (100,0)
                def enuToTGC(self,x,y,z):return (x,-z,y)
                def latlonToTGC(self,lat,lon,x_offset=0,y_offset=0):return (float(lon)+x_offset,0,float(lat)+y_offset)
            c={'surfaceSplines2':[],'holes3':[],'surfaces2':palette()}
            osm.addOSMToTGC(c,CoursePC(),r,course_version=25,options_dict={'water':True,'tree':False},resolve_missing_nodes=False,printf=silent)
            self.assertTrue(c['surfaceSplines2']);self.assertTrue(all(s['surface']==10 for s in c['surfaceSplines2']))
            self.assertEqual(c[lock.LOCK_KEY]['importedCount'],len(c['surfaceSplines2']))
        def test_23_packed_export_after_profile_change(self):
            import tgc_tools
            c={'surfaceSplines2':[osm.newWaterHazard(points,True,25)],'surfaces2':palette()}
            lock.mark_import(c,osm.last_imported_water_splines,25,silent)
            c['surfaces2'][2]['name']='Concrete02'
            m={'name':'test','surfaces2':palette()};m['surfaces2'][2]['name']='Asphalt01B'
            with tempfile.TemporaryDirectory() as td:
                folder=Path(td)
                for sub,name,obj in [('course_description','course_description',c),('metadata','course_metadata',m),('thumbnail','thumbnail',{'image':''})]:
                    d=folder/'unpacked'/sub;d.mkdir(parents=True);(d/(name+'.json')).write_text(json.dumps(obj))
                dest=folder/'out.course';tgc_tools.pack_course_file(folder,output_file=dest,course_version=25)
                outer=json.loads(gzip.decompress(dest.read_bytes()))
                for field in ('CourseDescription','CourseMetadata'):
                    decoded=json.loads(gzip.decompress(base64.b64decode(outer['binaryData'][field])))
                    self.assertEqual(decoded['surfaces2'][2]['name'],'Mulch05')
        def test_24_real_kukio_relations_when_supplied(self):
            if osm_path is None:self.skipTest('Pass --osm for the uploaded Kukio file test')
            result=overpy.Overpass().parse_xml(Path(osm_path).read_text())
            self.assertEqual(sum(r.tags.get("type")=="multipolygon" for r in result.relations),5)
            import pyproj
            bounds=ET.fromstring(Path(osm_path).read_text()).find('bounds').attrib
            trans=pyproj.Transformer.from_crs(4326,32605,always_xy=True)
            xs,ys=trans.transform([float(bounds['minlon']),float(bounds['maxlon'])],[float(bounds['minlat']),float(bounds['maxlat'])]);ox,oy=min(xs)-20,min(ys)-20
            w=int(math.ceil((max(xs)-ox+20)/2));h=int(math.ceil((max(ys)-oy+20)/2))
            class Projector:
                def latlonToCV2(self,lat,lon,scale,x_offset=0,y_offset=0):
                    xx,yy=trans.transform(float(lon),float(lat));return (int((yy-oy+y_offset)/scale),int((xx-ox+x_offset)/scale))
            old=osm.addOSMToImage(result.ways,np.full((h,w,3),.31,np.float32),Projector(),2.,printf=silent)
            log=[];new=osm.addOSMToImage(result,np.full((h,w,3),.31,np.float32),Projector(),2.,printf=log.append)
            self.assertTrue(any('5 complete, 0 skipped' in s for s in log));changed=int(np.count_nonzero(np.any(new!=old,axis=2)));self.assertGreater(changed,1000)
            blue=lambda im:(im[:,:,0]==0)&(im[:,:,1]==0)&(im[:,:,2]==1)
            np.testing.assert_array_equal(blue(old),blue(new))
            print('Kukio fixture: 5 complete relations; changed overlay pixels=%d; standalone water unchanged.'%changed)
    print('OSM reader: '+('stdlib XML fixture adapter (overpy not installed in this environment)' if USING_ADAPTER else 'native overpy'))
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(ROOT));p.add_argument('--osm');a=p.parse_args();sys.exit(main(a.root,a.osm))
