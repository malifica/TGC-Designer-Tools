"""Offline tests for the paired Unity importer. No game/Windows claims."""
import copy,hashlib,importlib.util,json,math,os,sys,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import tgc_unity_raw_svg as c
from tgc_unity_svg_paths import flatten_path,matrix

class PathTests(unittest.TestCase):
    def points(self,d,**kw):return flatten_path(d,**kw)[0][0]
    def test_square(self):
        p=self.points('M0 0 h10 v10 h-10 z');self.assertTrue(np.array_equal(p[0],p[-1]))
        from shapely.geometry import Polygon
        self.assertAlmostEqual(Polygon(p).area,100)
    def test_relative_move(self):self.assertTrue(np.allclose(self.points('m2 3 4 0 0 5 z')[1],[6,3]))
    def test_scientific(self):self.assertTrue(np.allclose(self.points('M1e1 -2e0 L12-3')[-1],[12,-3]))
    def test_multi_subpath(self):self.assertEqual(len(flatten_path('M0 0 L1 0 L1 1z M2 2h1v1z')),2)
    def test_nearly_closed_ring(self):
        parts=flatten_path('M0 0L10 0L10 10L0 10L0.00000000001 0Z M20 20h10v10h-10z')
        self.assertTrue(all(np.array_equal(p[0],p[-1]) for p,closed in parts if closed))
    def test_cubic(self):
        p=self.points('M0 0C0 10 10 10 10 0',tolerance=.01);self.assertGreater(len(p),8);self.assertAlmostEqual(max(p[:,1]),7.5)
    def test_smooth_cubic(self):self.assertTrue(np.allclose(self.points('M0 0C0 1 1 1 1 0S2-1 2 0')[-1],[2,0]))
    def test_quadratic(self):self.assertGreater(max(self.points('M0 0Q5 10 10 0')[:,1]),4.9)
    def test_smooth_quadratic(self):self.assertTrue(np.allclose(self.points('M0 0Q5 10 10 0T20 0')[-1],[20,0]))
    def test_arc(self):
        p=self.points('M-10 0A10 10 0 1 0 10 0A10 10 0 1 0-10 0Z',tolerance=.01)
        from shapely.geometry import Polygon
        self.assertAlmostEqual(Polygon(p).area,math.pi*100,delta=.5)
    def test_zero_arc(self):self.assertTrue(np.allclose(self.points('M0 0A0 10 0 0 0 3 4')[-1],[3,4]))
    def test_transform(self):self.assertTrue(np.allclose(self.points('M1 2L2 3',transform=matrix('translate(10,20) scale(2)'))[0],[12,24]))
    def test_transform_rotate(self):self.assertTrue(np.allclose(self.points('M2 0L3 0',transform=matrix('rotate(90 1 0)'))[0],[1,1]))
    def test_reject_unknown(self):
        with self.assertRaises(ValueError):flatten_path('M0 0R2 3')
    def test_reject_incomplete(self):
        with self.assertRaises(ValueError):flatten_path('M0 0C2 3')
    def test_invalid_arc_flag(self):
        with self.assertRaises(ValueError):flatten_path('M0 0A10 10 0 4 0 1 2')
    def test_max_segment(self):self.assertLessEqual(np.linalg.norm(np.diff(self.points('M0 0C0 0 30 30 50 10',max_step=2),axis=0),axis=1).max(),2.00001)

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.raw=self.p/'terrain.raw';self.svg=self.p/'test.svg'
        self.data=np.arange(25,dtype='<u2').reshape(5,5)*1000;self.data.tofile(self.raw)
        self.s={'rows':5,'cols':5,'bits':16,'byte_order':'little','width_m':8.,'length_m':8.,'height_m':173.,'base_elevation_m':0.,'orientation':'as_stored','output_spacing_m':2.,'mapping':{},'output_prefix':'Test'}
        self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" viewBox="0 0 8 8"><g inkscape:label="Greens"><path id="p" d="M2 2h2v2h-2z"/></g></svg>')
    def tearDown(self):self.tmp.cleanup()
    def test_inspect(self):self.assertEqual(c.inspect_raw(self.raw)['square_candidates'],[{'bits':16,'rows':5,'cols':5}])
    def test_formula(self):self.assertAlmostEqual(float(c.load_raw(self.raw,self.s)[4,4]),24000*173/65536,places=5)
    def test_no_minmax_stretch(self):self.assertLess(c.load_raw(self.raw,self.s).max(),173)
    def test_offset(self):self.s['base_elevation_m']=100;self.assertAlmostEqual(c.load_raw(self.raw,self.s)[0,0],100)
    def test_mirror(self):self.s['orientation']='flip_horizontal';self.assertEqual(float(c.load_raw(self.raw,self.s)[0,0]),4000*173/65536)
    def test_all_orientations(self):
        for name in c.ORIENTATIONS:self.assertEqual(sorted(c.orient(self.data,name).ravel()),sorted(self.data.ravel()))
    def test_big_endian(self):self.data.astype('>u2').tofile(self.raw);self.s['byte_order']='big';self.assertEqual(float(c.load_raw(self.raw,self.s)[0,4]),4000*173/65536)
    def test_8bit(self):np.arange(25,dtype='u1').tofile(self.raw);self.s['bits']=8;self.assertEqual(float(c.load_raw(self.raw,self.s)[4,4]),24*173/256)
    def test_wrong_size(self):self.s['rows']=6;self.assertRaises(ValueError,c.load_raw,self.raw,self.s)
    def test_bad_height(self):self.s['height_m']=float('nan');self.assertRaises(ValueError,c.load_raw,self.raw,self.s)
    def test_svg_layer(self):fs,_=c.read_svg(self.svg,8,8);self.assertEqual(fs[0]['kind'],'green');self.assertAlmostEqual(fs[0]['geometry'].area,4)
    def test_color_override(self):fs,_=c.read_svg(self.svg,8,8,{'Greens|black':'water'});self.assertEqual(fs[0]['kind'],'water')
    def test_id_override(self):fs,_=c.read_svg(self.svg,8,8,{'p':'bunker'});self.assertEqual(fs[0]['kind'],'bunker')
    def test_viewbox_scale(self):fs,_=c.read_svg(self.svg,16,8);self.assertAlmostEqual(fs[0]['geometry'].area,8)
    def test_no_routes_invented(self):fs,_=c.read_svg(self.svg,8,8);self.assertFalse(any(f['kind']=='hole' for f in fs))
    def test_unsupported_entities(self):self.svg.write_text('<!DOCTYPE svg><svg/>');self.assertRaises(ValueError,c.read_svg,self.svg,8,8)
    def test_hidden(self):self.svg.write_text(self.svg.read_text().replace('<path','<path style="display:none"'));fs,_=c.read_svg(self.svg,8,8);self.assertFalse(fs)
    def test_polygon_hole(self):
        self.svg.write_text(self.svg.read_text().replace('M2 2h2v2h-2z','M0 0h8v8h-8z M2 2v2h2v-2z'))
        fs,_=c.read_svg(self.svg,8,8);self.assertEqual(len(fs[0]['geometry'].interiors),1);self.assertAlmostEqual(fs[0]['geometry'].area,60)
    def test_evenodd(self):
        self.svg.write_text(self.svg.read_text().replace('id="p"','id="p" fill-rule="evenodd"').replace('M2 2h2v2h-2z','M0 0h8v8h-8z M2 2h2v2h-2z'))
        fs,_=c.read_svg(self.svg,8,8);self.assertAlmostEqual(fs[0]['geometry'].area,60)
    def test_hole_partition(self):
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        p=Polygon([(0,0),(10,0),(10,10),(0,10)],[[(2,2),(4,2),(4,4),(2,4)]])
        qs=c._holeless(p);self.assertTrue(all(not q.interiors for q in qs));self.assertLess(unary_union(qs).symmetric_difference(p).area,1e-8)
    def test_degenerate_part_excluded_with_report(self):
        from shapely.geometry import Polygon,MultiPolygon
        g=MultiPolygon([Polygon([(0,0),(1,0),(1,1),(0,1)]),Polygon([(2,2),(2.00001,2),(2.00001,2.00001)])])
        f={'id':'p','group':'Bunkers','fill':'white','kind':'bunker','geometry':g}
        info=c.write_osm(self.p/'a.osm',[f],8,8)
        self.assertEqual(info['feature_counts']['bunker'],1);self.assertEqual(len(info['ignored_sub_cm2_parts']),1)
    def test_pair(self):
        import rasterio
        from pyproj import Transformer
        before=[c.sha256(self.raw),c.sha256(self.svg)];r,fs,dem=c.create_pair(self.raw,self.svg,self.p/'out',self.s,printf=lambda _:None)
        with rasterio.open(r['outputs']['dem']) as d:
            self.assertEqual(d.shape,(4,4));self.assertEqual(d.res,(2,2));self.assertEqual(d.units,('m',));self.assertEqual(d.tags()['TGC_AUTHORED_SURFACE'],'bilinear');self.assertEqual(d.crs.to_epsg(),32631)
            self.assertAlmostEqual(float(d.read(1)[0,0]),3000*173/65536,places=5)
        root=ET.parse(r['outputs']['osm']).getroot();self.assertEqual(root.get('upload'),'never')
        ids={n.get('id') for n in root.findall('node')};self.assertTrue(all(nd.get('ref') in ids for nd in root.findall('.//nd')))
        tr=Transformer.from_crs(4326,32631,always_xy=True);node=root.find('node');x,y=tr.transform(float(node.get('lon')),float(node.get('lat')))
        self.assertAlmostEqual(x,500000-4+2,places=4);self.assertAlmostEqual(y,5000000+4-2,places=4)
        self.assertEqual(before,[c.sha256(self.raw),c.sha256(self.svg)])
    def test_preserve_existing_output(self):
        out=self.p/'out';out.mkdir();(out/'valuable').write_text('retain');self.assertRaises(ValueError,c.create_pair,self.raw,self.svg,out,self.s);self.assertEqual((out/'valuable').read_text(),'retain')
    def test_atomic_failure(self):
        self.svg.write_text('invalid SVG');self.assertRaises(Exception,c.create_pair,self.raw,self.svg,self.p/'out',self.s);self.assertFalse((self.p/'out').exists());self.assertFalse(list(self.p.glob('.*staging*')))
    def test_refuse_false_resolution(self):self.s['output_spacing_m']=1;self.assertRaises(ValueError,c.create_pair,self.raw,self.svg,self.p/'out',self.s)
    def test_bilinear_linear_surface(self):
        a=np.add.outer(np.arange(8)*2.,np.arange(8)*3.).astype('f4');b=c.resample_authored_dem(a,1,2,printf=lambda _:None);self.assertAlmostEqual(float(b[0,0]),2.5);self.assertAlmostEqual(float(b[1,1]),12.5)
    def test_no_reduction_copy(self):
        a=np.ones((2,2));b=c.resample_authored_dem(a,2,2);b[0,0]=3;self.assertEqual(a[0,0],1)
    def test_missing_route_number(self):
        self.svg.write_text(self.svg.read_text().replace('Greens','Hole routes'));self.assertRaises(ValueError,c.read_svg,self.svg,8,8)
    def test_explicit_route(self):
        self.svg.write_text(self.svg.read_text().replace('Greens','Hole routes').replace('id="p"','id="p" data-hole="1" data-par="3"'))
        fs,_=c.read_svg(self.svg,8,8);self.assertEqual(fs[0]['hole'],'1');self.assertEqual(fs[0]['par'],'3')

if __name__=='__main__':unittest.main(verbosity=2)
