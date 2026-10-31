"""Focused dry-mulch tests. No game or Windows GUI is exercised."""
from pathlib import Path
import copy, importlib.util, json, sys, tempfile, types, unittest, xml.etree.ElementTree as ET
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
try:
    import overpy
except ImportError:
    # Only unit-test protocol objects are used below. Never installed as runtime code.
    print('TEST NOTE: overpy unavailable; using in-memory way/result protocol fixtures.')
    mod=types.ModuleType('overpy');mod.RelationWay=type('RelationWay',(),{})
    mod.exception=types.SimpleNamespace(OverPyException=RuntimeError)
    sys.modules['overpy']=mod
import OSMTGC as o
import auto_red_mask as masks
import osm_water_mulch_lock as lock

class Way:
    def __init__(self, tags, xy=None, id=1):
        self.tags=tags;self.id=id
        xy=xy or [(10,10),(30,10),(30,30),(10,30),(10,10)]
        self.nodes=[types.SimpleNamespace(id=(i if i<len(xy)-1 else 0),lon=x,lat=y,tags={}) for i,(x,y) in enumerate(xy)]
    def get_nodes(self,resolve_missing=False):return self.nodes
class PC:
    def ulENU(self):return (0,100)
    def lrENU(self):return (100,0)
    def enuToTGC(self,x,y,z):return (x,z,y)
    def latlonToTGC(self,lat,lon,x_offset=0,y_offset=0):return (float(lon)+x_offset,0.,float(lat)+y_offset)
    def latlonToCV2(self,lat,lon,scale,x_offset=0,y_offset=0):return ((float(lat)+y_offset)/scale,(float(lon)+x_offset)/scale)
def source():return {'surfaceSplines2':[],'holes3':[],'surfaces2':[{'name':'Other0'},{'name':'Other1'},{'name':'Old','blend':.7,'maskWater':True}], 'height':[{'keep':'unchanged'}], 'placedObjects4':{'keep':3}}
def run_import(way,options=None):
    course=source();r=types.SimpleNamespace(ways=[way],relations=[],nodes=way.nodes)
    o.addOSMToTGC(course,PC(),r,options_dict=options or {'tree':False,'wood':True,'water':False,'optimize_osm_spline_points':False},course_version=25,resolve_missing_nodes=False,printf=lambda *_:None)
    return course
class NativeTests(unittest.TestCase):
    def setUp(self):o.spline_configuration=None;o.last_imported_water_splines=[]
    def pts(self):return [(10,0,10),(30,0,10),(30,0,30),(10,0,30),(10,0,10)]
    def test_native_category(self):self.assertEqual(o.newMulch(self.pts(),25)['surface'],10)
    def test_filled_closed(self):
        s=o.newMulch(self.pts(),25);self.assertEqual((s['isClosed'],s['isFilled'],s['state']),(True,True,3))
    def test_no_water_registration(self):o.newMulch(self.pts(),25);self.assertEqual(o.last_imported_water_splines,[])
    def test_water_unchanged(self):
        s=o.newWaterHazard(self.pts(),True,25);self.assertEqual(s['surface'],10);self.assertEqual(o.last_imported_water_splines,[s])
    def test_forest_native_mulch(self):self.assertEqual(o.newForest(self.pts(),25)['surface'],10)
    def test_dry_import_independent_of_water_trees(self):
        c=run_import(Way({'natural':'wood'}))
        self.assertEqual(len(c['surfaceSplines2']),1);self.assertEqual(c['surfaceSplines2'][0]['surface'],10)
        self.assertEqual(c[lock.DRY_LOCK_KEY]['importedCount'],1);self.assertNotIn(lock.LOCK_KEY,c)
        self.assertEqual(c['surfaces2'][2]['name'],'Mulch05');self.assertEqual(c['height'],source()['height'])
        self.assertEqual(c['placedObjects4'],source()['placedObjects4'])
    def test_open_rejected(self):self.assertEqual(run_import(Way({'natural':'wood'},[(10,10),(30,10),(30,30)]))['surfaceSplines2'],[])
    def test_optional_disabled(self):
        self.assertEqual(run_import(Way({'natural':'wood'}),{'wood':False,'tree':False})['surfaceSplines2'],[])
    def test_woodchips_are_not_substituted_for_wood(self):
        self.assertEqual(run_import(Way({'surface':'woodchips','area':'yes'}))['surfaceSplines2'],[])
    def test_dry_wood_is_not_water(self):self.assertFalse(masks._is_water_feature(Way({'natural':'wood'})))
    def test_dry_material_serialized_gate(self):
        c=run_import(Way({'natural':'wood'}));c['surfaces2'][2]['name']='ChangedByTheme'
        meta={'surfaces2':copy.deepcopy(source()['surfaces2'])}
        a,b=lock.finalize_serialized(json.dumps(c),json.dumps(meta),25);aa,bb=json.loads(a),json.loads(b)
        self.assertEqual(aa['surfaces2'][2]['name'],'Mulch05');self.assertEqual(bb['surfaces2'][2]['name'],'Mulch05')
        self.assertEqual(aa['height'],c['height']);self.assertEqual(aa['surfaceSplines2'],c['surfaceSplines2'])
        self.assertNotIn(lock.LOCK_KEY,aa);self.assertEqual(aa['surfaces2'][2]['blend'],.7)
    def test_untagged_export_bytes_unchanged(self):
        a,b=' {"version":49} ',' {"courseVersion":49} ';self.assertEqual(lock.finalize_serialized(a,b,25),(a,b))

@unittest.skipUnless(importlib.util.find_spec('tgc_unity_raw_svg'),'Unity importer not installed; native OSM tests still apply')
class SVGTests(unittest.TestCase):
    def setUp(self):
        import tgc_unity_raw_svg as core
        self.c=core;self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def svg(self,layer='Trees',path='M10 10h20v20h-20z'):
        p=self.p/'input.svg';p.write_text('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" viewBox="0 0 100 100"><g inkscape:label="'+layer+'"><path id="pink" fill="#faa0be" fill-rule="evenodd" d="'+path+'"/></g></svg>');return p
    def test_mulch_kind(self):self.assertIn('mulch',self.c.KINDS)
    def test_do_not_relabel_all_trees(self):self.assertEqual(self.c.read_svg(self.svg(),100,100)[0][0]['kind'],'wood')
    def test_named_mulch(self):self.assertEqual(self.c.read_svg(self.svg('Mulch'),100,100)[0][0]['kind'],'mulch')
    def test_user_override(self):self.assertEqual(self.c.read_svg(self.svg(),100,100,{'Trees|#faa0be':'mulch'})[0][0]['kind'],'mulch')
    def test_export_dry_tags(self):
        fs,_=self.c.read_svg(self.svg(),100,100,{'Trees|#faa0be':'mulch'})
        p=self.p/'a.osm';self.c.write_osm(p,fs,100,100,32631,500000,5000000)
        r=ET.parse(p).getroot();t={x.get('k'):x.get('v') for x in r.find('way').findall('tag')}
        self.assertNotIn('golf',t);self.assertEqual(t['surface'],'woodchips');self.assertEqual(t['area'],'yes');self.assertNotIn('natural',t)
    def test_inner_cutout_partition(self):
        fs,_=self.c.read_svg(self.svg(path='M10 10h40v40h-40z M20 20h20v20h-20z'),100,100,{'Trees|#faa0be':'mulch'})
        p=self.p/'a.osm';report=self.c.write_osm(p,fs,100,100,32631,500000,5000000)
        self.assertAlmostEqual(fs[0]['geometry'].area,1200);self.assertEqual(report['relations'],0);self.assertGreater(report['ways'],1)
        from pyproj import Transformer
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        r=ET.parse(p).getroot();tr=Transformer.from_crs(4326,32631,always_xy=True)
        pts={n.get('id'):tr.transform(float(n.get('lon')),float(n.get('lat'))) for n in r.findall('node')}
        polys=[Polygon([pts[nd.get('ref')] for nd in w.findall('nd')]) for w in r.findall('way')]
        self.assertAlmostEqual(unary_union(polys).area,1200,delta=.01)

if __name__=='__main__':unittest.main(verbosity=2)
