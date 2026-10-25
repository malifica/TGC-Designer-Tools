"""Beta 7 regression tests. --gui adds a real Tk/worker/canvas smoke test.

Uses native overpy when available. The older verifier's explicit XML fixture
adapter is allowed ONLY for this test process when native overpy is absent.
"""
from pathlib import Path
import argparse
import ast
import copy
import importlib.util
import json
import math
import sys
import tempfile
import time
import types
import unittest
import xml.etree.ElementTree as ET
import numpy as np
import pyproj
from PIL import Image
ROOT=Path(__file__).resolve().parent
USING_ADAPTER=False
try:
    import overpy
except ImportError:
    USING_ADAPTER=True
    spec=importlib.util.spec_from_file_location('_beta7_xml_test_adapter',ROOT/'VERIFY_BETA6_MULTIPOLYGON_MULCH_V1.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    import overpy
import tgc_cfs_display as d
from GeoPointCloud import GeoPointCloud
import osm_alignment_viewer as v
import osm_mask_alignment as m


def osm_xml(proj, x=400000., y=3280000., scale=2.):
    inv=pyproj.Transformer.from_proj(proj,GeoPointCloud()._platlon,True)
    points=[(10,10),(30,10),(30,30),(10,30),(16,16),(24,16),(24,24),(16,24)]
    nodes=[]
    for i,(xx,yy) in enumerate(points,1):
        lon,lat=inv.transform(x+xx*scale,y+yy*scale)
        nodes.append('<node id="%d" lon="%.12f" lat="%.12f"/>'%(i,lon,lat))
    return ('<osm version="0.6">'+''.join(nodes)+
      '<way id="11"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>'+
      '<way id="12"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/><tag k="golf" v="rough"/></way>'+
      '<relation id="21"><member type="way" ref="11" role="outer"/><member type="way" ref="12" role="inner"/><tag k="type" v="multipolygon"/><tag k="golf" v="fairway"/></relation></osm>')


class Tests(unittest.TestCase):
    def test_01_beta7_identity(self):
        tree=ast.parse((ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        values={t.id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                for t in n.targets if isinstance(t,ast.Name) and t.id in ('TGC_APP_TITLE','TGC_GUI_VERSION')}
        self.assertEqual(values,{'TGC_APP_TITLE':'TGC Designer Tools 2K25 - Beta 7','TGC_GUI_VERSION':'v0.5.0-2k25-beta7'})
    def test_02_neutral_tone(self):self.assertEqual(d.tone_lut(),list(range(256)))
    def test_03_brighter(self):self.assertGreater(d.tone_lut(1.3,1.)[100],100)
    def test_04_darker(self):self.assertLess(d.tone_lut(.6,1.)[100],100)
    def test_05_contrast_increase(self):
        a=d.tone_lut(1.,2.);self.assertLess(a[90],90);self.assertGreater(a[160],160)
    def test_06_contrast_reduce(self):
        a=d.tone_lut(1.,.5);self.assertGreater(a[90],90);self.assertLess(a[160],160)
    def test_07_tone_saturation(self):
        a=d.tone_lut(2.,3.);self.assertEqual(a[0],0);self.assertEqual(a[255],255)
    def test_08_tone_finite(self):
        with self.assertRaises(ValueError):d.tone_lut(float('nan'),1.)
    def test_09_screen_edges(self):
        self.assertEqual(d.screen_point(0,0,100,2,1),(0.,100.))
        self.assertEqual(d.screen_point(0,100,100,2,1),(0.,0.))
    def test_10_cell_center_all_zooms(self):
        for z in [.1,.33,1,2,6,12,20,30]:
            x,y=d.screen_point(4.5,6.5,10,2,z)
            self.assertAlmostEqual(x,4.5*z);self.assertAlmostEqual(y,3.5*z)
    def test_11_nudge_not_rescaled(self):
        for res in [1,2,4,6]:
            a=d.screen_point(10,20,100,res,30)
            b=d.screen_point(10,20,100,res,30,3.7,-3.9)
            self.assertAlmostEqual((b[0]-a[0])/30*res,3.7)
            self.assertAlmostEqual(-(b[1]-a[1])/30*res,-3.9)
    def test_12_native_projection_parity(self):
        for epsg,lat,lon in [(6628,19.80,-155.99),(6635,20.,-155.82),(32605,20.,-155.82),(32614,29.6,-98.4)]:
            pc=GeoPointCloud();pc.proj=pyproj.Proj('epsg:'+str(epsg),preserve_units=False)
            got=d.importer_transformer(pc.proj).transform(lon,lat)
            self.assertEqual(got,pc.latlonToProj(lat,lon))
    def test_13_project_switching(self):
        for epsg in [6628,32614,6635,32605,6628]:
            p=pyproj.Proj('epsg:'+str(epsg),preserve_units=False)
            a=d.importer_transformer(p).transform(-155.99,19.8)
            b=pyproj.Transformer.from_proj(GeoPointCloud()._platlon,p,True).transform(-155.99,19.8)
            self.assertEqual(a,b)
    def test_14_mask_matches_import(self):
        p=pyproj.Proj('epsg:6628');pc=GeoPointCloud();pc.proj=p;pc.origin=(448066.,105915.)
        f=m._FastGridProjector(p,pc.origin)
        for shift in [(0,0),(3.7,-3.9),(-8.2,7.1)]:
            for lat,lon in [(19.8,-155.99),(19.805,-155.985),(19.79,-155.995)]:
                self.assertEqual(f.latlonToCV2(lat,lon,2,*shift),pc.latlonToCV2(lat,lon,2,*shift))
    def test_15_custom_placement_unchanged(self):
        cp=types.SimpleNamespace(project=lambda lon,lat:(lon+1000,lat+2000))
        f=m._FastGridProjector('unused', (990,1990),custom_placement=cp)
        self.assertEqual(f.latlonToCV2(10,20,2,4,-2),(9,17))
    def test_16_cfs_projection_matches_import(self):
        p=pyproj.Proj('epsg:6628');pc=GeoPointCloud();pc.proj=p
        r=overpy.Overpass().parse_xml(osm_xml(p,448066.,105915.))
        g=dict(min_x=448066.,min_y=105915.,resolution=2.)
        fs=v._collect_overlay_features(r,p,g,printf=lambda *_:None)
        self.assertEqual(len(fs),2)
        byid={w.id:w for w in r.ways}
        for f in fs:
            wid=int(f['label'].split(':')[-1])
            for point,n in zip(f['points'],byid[wid].get_nodes()):
                x,y=pc.latlonToProj(n.lat,n.lon)
                self.assertAlmostEqual(point[0]*2+g['min_x'],x,places=8)
                self.assertAlmostEqual(point[1]*2+g['min_y'],y,places=8)
    def test_17_relation_inner_retained(self):
        p=pyproj.Proj('epsg:32614');r=overpy.Overpass().parse_xml(osm_xml(p))
        fs=v._collect_overlay_features(r,p,dict(min_x=400000.,min_y=3280000.,resolution=2),printf=lambda *_:None)
        self.assertEqual(len(fs),2);self.assertTrue(any(f['kind']=='rough' for f in fs))
    def test_18_stale_alignment_marker(self):
        a={'patch_id':m.PATCH_ID,'schema_version':m.SCHEMA_VERSION}
        expected={**a,'alignment_geometry_version':d.ALIGNMENT_GEOMETRY_VERSION}
        ok,msg=m._signatures_match(a,expected)
        self.assertFalse(ok);self.assertIn('Beta 7',msg)
    def test_19_current_alignment_marker(self):
        a={'patch_id':m.PATCH_ID,'schema_version':m.SCHEMA_VERSION,'alignment_geometry_version':d.ALIGNMENT_GEOMETRY_VERSION,
           'adjust_ew_m':0.,'adjust_ns_m':0.}
        self.assertTrue(m._signatures_match(a,dict(a))[0])
    def test_20_tile_memory_bound(self):
        im=Image.new('RGB',(760,1155))
        tile,origin=d.viewport_tile(im,30.,9000,17000,1280,800)
        self.assertLessEqual(tile.width,1280+50);self.assertLessEqual(tile.height,800+50)
        self.assertLess(tile.width*tile.height*3,4_000_000)
    def test_21_tile_does_not_modify_input(self):
        im=Image.fromarray(np.arange(900,dtype=np.uint8).reshape(10,30,3));raw=im.tobytes()
        d.viewport_tile(im,30,10,20,100,80,1.5,2.)
        self.assertEqual(im.tobytes(),raw)
    def test_22_cell_center_raster_parity(self):
        arr=np.zeros((10,10,3),np.uint8);arr[3,4,:]=255;im=Image.fromarray(arr)
        for zoom in [1,2,10,30]:
            t,o=d.viewport_tile(im,zoom,0,0,400,400,pad=0)
            x,y=d.screen_point(4.5,6.5,10,2,zoom)
            self.assertGreaterEqual(t.getpixel((int(x)-o[0],int(y)-o[1]))[0],140)
    def test_23_tone_independent_of_pan(self):
        im=Image.new('RGB',(100,100),(75,75,75))
        a,_=d.viewport_tile(im,30,0,0,200,100,1.4,1.1)
        b,_=d.viewport_tile(im,30,1500,1000,200,100,1.4,1.1)
        self.assertEqual(a.getpixel((50,50)),b.getpixel((50,50)))
    def test_24_no_overlay_toning(self):
        original=dict(v.FEATURE_COLORS)
        d.viewport_tile(Image.new('RGB',(20,20)),30,0,0,300,300,2,3)
        self.assertEqual(v.FEATURE_COLORS,original)
    def test_25_zoom_reject_invalid(self):
        for z in [0,31,float('nan')]:
            with self.assertRaises(ValueError):d.viewport_tile(Image.new('RGB',(2,2)),z,0,0,20,20)
    def test_26_hillshade_default_and_bounded_render(self):
        source=(ROOT/'osm_alignment_viewer.py').read_text(encoding='utf-8-sig')
        self.assertIn('value="Hillshade"',source);self.assertIn('viewport_tile',source)
        self.assertNotIn('pil.resize(size',source)
    def test_27_shared_ui_and_mask_transformer(self):
        self.assertIn('importer_transformer(projection)',(ROOT/'osm_alignment_viewer.py').read_text())
        self.assertIn('importer_transformer(projection)',(ROOT/'osm_mask_alignment.py').read_text())
    def test_28_display_only_no_disk_writes(self):
        t=ast.parse((ROOT/'tgc_cfs_display.py').read_text())
        banned={'save','dump','write_text','write_bytes','imwrite','unlink'}
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in banned for n in ast.walk(t)))
    def test_29_background_none_outside(self):
        t,_=d.viewport_tile(Image.new('RGB',(10,10)),30,1000,1000,100,100)
        self.assertIsNone(t)
    @unittest.skipIf(USING_ADAPTER,'Native overpy unavailable; geometry tests used the explicitly labelled XML fixture adapter')
    def test_30_native_overpy(self):
        p=pyproj.Proj('epsg:32614');r=overpy.Overpass().parse_xml(osm_xml(p))
        self.assertEqual(len(r.relations),1)


def gui_check(screenshot=None):
    import tkinter as tk
    root=tk.Tk();root.withdraw();errors=[]
    root.report_callback_exception=lambda *args:errors.append(args)
    p=pyproj.Proj('epsg:32614');rows,cols=100,120;x,y=400000.,3280000.
    inv=pyproj.Transformer.from_proj(p,GeoPointCloud()._platlon,True);lon,lat=inv.transform(x,y)
    grid=dict(version=1,min_x=x,min_y=y,max_x=x+cols*2,max_y=y+rows*2,rows=rows,cols=cols,resolution=2.,
              row_order='south_up_internal',origin_semantics='southwest_cell_edge',lower_left_latlon=[lat,lon],horizontal_epsg=32614)
    yy,xx=np.mgrid[:rows,:cols];h=(10+xx*.1+np.sin(yy/7)*3).astype(np.float32)
    with tempfile.TemporaryDirectory(prefix='tgc_beta7_cfs_') as td:
        td=Path(td);np.save(td/'heightmap.npy',dict(heightmap=h,image_scale=2.,projection=p,master_grid=grid,origin=(lat,lon)))
        (td/'layout.osm').write_text(osm_xml(p))
        ew=tk.Entry(root);ew.insert(0,'3.70');ns=tk.Entry(root);ns.insert(0,'-3.90')
        logs=[];a=v.AlignmentViewer(root,td,td/'layout.osm',ew,ns,printf=logs.append)
        def pump(seconds=.1):
            end=time.monotonic()+seconds
            while time.monotonic()<end:root.update();time.sleep(.005)
        deadline=time.monotonic()+20
        while not a.ready and time.monotonic()<deadline:pump(.04)
        assert a.ready, logs
        assert a.view_var.get()=='Hillshade'
        saved=a.heightmap.copy();features=copy.deepcopy(a.features);shifts=(a.shift_ew,a.shift_ns)
        a.brightness_var.set(1.3);a.contrast_var.set(.75);d.tone_changed(a);pump(.15)
        assert a.brightness_text.get()=='130%' and a.contrast_text.get()=='75%'
        d.reset_tone(a);pump(.1)
        assert (a.brightness_var.get(),a.contrast_var.get())==(1.,1.)
        a._change_zoom(1000);pump(.2)
        assert a.zoom==30.
        assert a.photo.width()<=a.canvas.winfo_width()+50
        assert a.photo.height()<=a.canvas.winfo_height()+50
        a.canvas.xview_moveto(.5);a.canvas.yview_moveto(.4);pump(.2)
        assert tuple(a.canvas.coords(a.image_item))!=(0.,0.)
        a._view_changed();pump(.1)
        for view in ['Visual','Blend','Hillshade']:
            a.view_var.set(view);a._view_changed();pump(.05)
        assert np.array_equal(a.heightmap,saved) and a.features==features
        assert shifts==(a.shift_ew,a.shift_ns)
        a._set_controls_enabled(False)
        assert str(a.brightness_slider['state'])=='disabled'
        a._set_controls_enabled(True)
        assert str(a.zoom_combo['state'])=='readonly'
        a._key_nudge(types.SimpleNamespace(widget=a.brightness_slider),.1,0.)
        assert shifts==(a.shift_ew,a.shift_ns)
        a._fit_zoom();pump(.15)
        assert not errors,errors
        if screenshot:
            from PIL import ImageGrab
            ImageGrab.grab().save(screenshot)
        a._request_close();root.destroy()
    print('PASS: actual Tk worker load, Hillshade, sliders, reset, 30x, scroll redraw, source preservation, busy state and control focus.')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--gui',action='store_true');ap.add_argument('--screenshot');args=ap.parse_args()
    print('OSM reader: '+('stdlib XML fixture adapter (test-only)' if USING_ADAPTER else 'native overpy'))
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if not result.wasSuccessful():sys.exit(1)
    if args.gui:gui_check(args.screenshot)
