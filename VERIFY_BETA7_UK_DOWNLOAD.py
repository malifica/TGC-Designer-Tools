"""Offline regression tests for UK acquisition. --gui adds a real Tk check.
Provider fixtures follow documented interfaces; they are NOT live-service tests.
"""
from pathlib import Path
import ast
import io
import json
import math
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin
import uk_lidar_downloader as u

BBOX=(-0.15,51.49,-0.14,51.50)

class Response:
    def __init__(self,data=None,body=b'',status=200,headers=None):
        self.data=data;self.body=body;self.content=body;self.status_code=status
        self.headers=headers or {};self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def raise_for_status(self):
        if self.status_code>=400:raise u.requests.HTTPError(str(self.status_code))
    def json(self):
        if self.data is None:raise ValueError('not JSON')
        return self.data
    def iter_content(self,size):
        for i in range(0,len(self.body),size):yield self.body[i:i+size]

class HTTP:
    def __init__(self,responses):self.responses=list(responses);self.calls=[]
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs));r=self.responses.pop(0)
        if isinstance(r,Exception):raise r
        return r
    def get(self,url,**kwargs):return self.request('GET',url,**kwargs)
    def close(self):pass

def ea_item(kind='lidar_composite_dtm',year='2022',tile='TQ38se',url='https://environment.data.gov.uk/tiles/a'):
    return {'product':{'id':kind,'label':kind},'year':{'label':year},'tile':{'label':tile},
            'resolution':{'label':'1m'},'uri':url}

def scot_col(name='scotland-gov/lidar/phase-5/dtm',format='GeoTIFF'):
    return {'name':name,'metadata':{'title':name,'dataFormat':format,'useConstraints':'Open Government Licence v3'}}

def raster(path,array=None):
    arr=np.arange(10000,dtype=np.float32).reshape(100,100) if array is None else array
    with rasterio.open(path,'w',driver='GTiff',width=100,height=100,count=1,dtype='float32',
                       crs='EPSG:27700',transform=from_origin(530000,180100,1,1),nodata=-9999) as f:f.write(arr,1)
    return arr

class Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.messages=[]
    def tearDown(self):self.t.cleanup()
    def test_bbox_uk(self):self.assertEqual(u.validate_bbox(BBOX),BBOX)
    def test_bbox_reject_nonuk_and_large(self):
        for b in ((-156,19,-155,20),(-8,49,2,61),(0,51,float('nan'),52)):
            with self.assertRaises(u.AcquisitionError):u.validate_bbox(b)
    def test_region_routing(self):
        self.assertIn('Scotland',u.provider_regions((-2.9,56.3,-2.8,56.4)))
        self.assertEqual(u.provider_regions((-6,54.5,-5.9,54.6)),['Northern Ireland'])
    def test_no_dsm_or_imagery(self):
        for value in ('DSM','lidar_composite_dsm','DTM hillshade','DTM intensity','aerial imagery'):
            self.assertIsNone(u.classify_product(value))
        self.assertEqual(u.classify_product('lidar_point_cloud'),'pointcloud')
        self.assertEqual(u.classify_product('phase-5/dtm'),'dtm')
    def test_england_groups_dedup(self):
        a=ea_item();b=ea_item(tile='TQ38sw',url='https://environment.data.gov.uk/tiles/b')
        data=u.parse_england({'results':[a,b,a,ea_item('lidar_composite_dsm')]})
        self.assertEqual(len(data),1);self.assertEqual(len(data[0].assets),2)
    def test_england_requires_schema(self):
        with self.assertRaises(u.AcquisitionError):u.parse_england({'error':'bad'})
    def test_england_spatial_post(self):
        h=HTTP([Response({'results':[ea_item()]})]);result=u.england_discover(h,BBOX,printf=self.messages.append)
        self.assertEqual(h.calls[0][0],'POST');self.assertEqual(h.calls[0][2]['json'],u.geojson_bbox(BBOX))
        self.assertEqual(h.calls[0][2]['headers']['Content-Type'],'application/geo+json');self.assertEqual(len(result),1)
    def test_england_pagination(self):
        h=HTTP([Response({'results':[ea_item()],'next':'https://environment.data.gov.uk/page2'}),Response({'results':[ea_item(url='https://environment.data.gov.uk/tiles/b')]})])
        self.assertEqual(len(u.england_discover(h,BBOX,printf=lambda s:None)[0].assets),2)
    def test_scotland_licence(self):
        d=u.parse_scotland_collections({'result':[scot_col(),scot_col('scotland-gov/lidar/phase-2/laz','LAZ'),scot_col('phase-5/dsm')]})
        self.assertEqual(len(d),1)
    def test_scotland_s3_url(self):
        a=u._scotland_asset({'name':'tile','data':{'product':{'s3':{'bucket':'srsp-open-data','key':'lidar/tile name.tif','region':'eu-west-2','size':10}}}})
        self.assertEqual(a.bytes,10);self.assertIn('tile%20name.tif',a.url)
    def test_scotland_query_contract(self):
        # New production contract: direct S3, product restriction passed, no catalogue.
        import scotland_s3
        fixture=u.Dataset('s','Scotland','Direct fixture','dtm')
        with mock.patch.object(scotland_s3,'discover',return_value=([fixture],[])) as direct:
            r=u.scotland_discover(HTTP([]),BBOX,printf=lambda s:None,kind='dtm')
        self.assertEqual(r,[fixture]);self.assertEqual(direct.call_args.args[2],'dtm')
        self.assertNotIn('srsp-catalog', __import__('inspect').getsource(u.scotland_discover))
    def test_scotland_incomplete_page_fails(self):
        import scotland_s3
        raw=b'<ListBucketResult><IsTruncated>true</IsTruncated></ListBucketResult>'
        with self.assertRaises(u.AcquisitionError):scotland_s3.parse_page(raw)
    def test_wales_cog_not_dsm(self):
        ds=u.wales_discover(None,(-4,52,-3.9,52.1),printf=lambda s:None)[0]
        self.assertEqual(ds.kind,'dtm');self.assertIn('32bit',ds.assets[0].url);self.assertEqual(ds.assets[0].transport,'cog')
    def test_provider_failure_is_not_no_coverage(self):
        h=HTTP([u.requests.ConnectionError('offline')]);data,errors=u.discover(BBOX,'England',http=h,printf=self.messages.append)
        self.assertEqual(data,[]);self.assertTrue(errors);self.assertTrue(any('unavailable' in m for m in self.messages))
    def test_cancelled_discovery(self):
        e=threading.Event();e.set()
        with self.assertRaises(u.Cancelled):u.discover(BBOX,cancel=e,http=HTTP([]),printf=lambda s:None)
    def test_transfer_ok(self):
        h=HTTP([Response(body=b'LASF123',headers={'Content-Length':'7'})]);p=self.root/'a.bin'
        u.transfer(u.Asset('https://example.org/a','test',7),p,http=h,printf=lambda s:None)
        self.assertEqual(p.read_bytes(),b'LASF123');self.assertFalse(p.with_name('a.bin.part').exists())
    def test_transfer_truncated_preserves_old(self):
        p=self.root/'a.bin';p.write_bytes(b'OLD')
        h=HTTP([Response(body=b'xx',headers={'Content-Length':'8'})])
        with self.assertRaises(u.AcquisitionError):u.transfer(u.Asset('https://example.org/a','test'),p,http=h,printf=lambda s:None)
        self.assertEqual(p.read_bytes(),b'OLD');self.assertFalse((self.root/'a.bin.part').exists())
    def test_transfer_html_error(self):
        h=HTTP([Response(body=b'<html>',headers={'Content-Type':'text/html'})])
        with self.assertRaises(u.AcquisitionError):u.transfer(u.Asset('https://example.org/a','test'),self.root/'a',http=h)
    def test_http_not_accepted(self):
        with self.assertRaises(u.AcquisitionError):u._safe_url('http://example.org/a')
    def test_zip_slip(self):
        p=self.root/'a.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('../escape.tif',b'xx')
        with self.assertRaises(u.AcquisitionError):u.unpack(p,self.root/'out','dtm')
        self.assertFalse((self.root/'escape.tif').exists())
    def test_zip_types_and_sidecars(self):
        p=self.root/'a.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('sub/a.tif',b'xx');z.writestr('sub/a.prj',b'crs');z.writestr('run.exe',b'MZ')
        out=u.unpack(p,self.root/'out','dtm')
        self.assertEqual(len(out),1);self.assertTrue((self.root/'out/sub/a.prj').is_file());self.assertFalse((self.root/'out/run.exe').exists())
    def test_cog_no_full_file_fallback(self):
        h=HTTP([Response(body=b'II'*100,status=200)])
        with self.assertRaises(u.AcquisitionError):u._range_check(h,'https://example.org/a.tif',None)
    def test_cog_range_valid(self):
        h=HTTP([Response(body=b'II'+b'\0'*14,status=206,headers={'Content-Range':'bytes 0-15/1000'})]);u._range_check(h,'https://example.org/a.tif',None)
        self.assertEqual(h.calls[0][2]['headers']['Range'],'bytes=0-15')
    def test_raster_native_window_and_pixels(self):
        source=self.root/'in.tif';arr=raster(source);dest=self.root/'out.tif'
        with mock.patch.object(u,'projected_bounds',return_value=(530010,180070,530030,180090)):
            p,meta=u.crop_raster(source,dest,BBOX,printf=lambda s:None)
        with rasterio.open(p) as f:
            np.testing.assert_array_equal(f.read(1),arr[10:30,10:30]);self.assertEqual(f.res,(1,1));self.assertEqual(f.crs.to_epsg(),27700)
        self.assertEqual(meta['valid_fraction'],1)
    def test_raster_nodata_not_flattened(self):
        source=self.root/'in.tif';arr=np.full((100,100),-9999,dtype=np.float32);raster(source,arr)
        with mock.patch.object(u,'projected_bounds',return_value=(530010,180070,530030,180090)):
            p,meta=u.crop_raster(source,self.root/'out.tif',BBOX,printf=lambda s:None)
        self.assertIsNone(p);self.assertEqual(meta['valid_cells'],0)
    def test_raster_missing_crs_refused(self):
        p=self.root/'no.tif'
        with rasterio.open(p,'w',driver='GTiff',width=10,height=10,count=1,dtype='float32',transform=from_origin(0,10,1,1)) as f:f.write(np.ones((10,10),np.float32),1)
        with self.assertRaises(u.AcquisitionError):u.crop_raster(p,self.root/'out.tif',BBOX,printf=lambda s:None)
    def test_raster_cancel_leaves_no_result(self):
        src=self.root/'in.tif';raster(src);e=threading.Event();e.set()
        with mock.patch.object(u,'projected_bounds',return_value=(530010,180070,530030,180090)):
            with self.assertRaises(u.Cancelled):u.crop_raster(src,self.root/'out.tif',BBOX,printf=lambda s:None,cancel=e)
        self.assertFalse((self.root/'out.tif').exists())
    def test_actual_shared_projector(self):
        import pyproj
        from tgc_cfs_display import importer_transformer
        crs=pyproj.Proj('EPSG:27700');t=importer_transformer(crs);a=u._projection(crs.crs,lambda s:None)
        lon=np.array([-.14,-3.,-2.8]);lat=np.array([51.5,52.1,56.3])
        np.testing.assert_array_equal(t.transform(lon,lat),a.transform(lon,lat))
    def test_download_and_cache_atomic(self):
        src=self.root/'tile.tif';arr=raster(src)
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.write(src,'tile.tif')
        ds=u.Dataset('test','England','DTM','dtm',resolution='1 m',assets=[u.Asset('https://example.org/tile','tile')])
        (self.root/'heightmap.npy').write_bytes(b'unchanged');(self.root/'mask.png').write_bytes(b'unchanged')
        h=HTTP([Response(body=b.getvalue())])
        with mock.patch.object(u,'projected_bounds',return_value=(530010,180070,530030,180090)):
            r=u.download(ds,BBOX,self.root,printf=lambda s:None,http=h)
        self.assertEqual(len(r.files),1);self.assertTrue(Path(r.manifest).is_file())
        r2=u.download(ds,BBOX,self.root,printf=lambda s:None,http=HTTP([]));self.assertEqual(r.files,r2.files)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'unchanged');self.assertEqual((self.root/'mask.png').read_bytes(),b'unchanged')
    def test_download_failure_cleanup(self):
        ds=u.Dataset('test','England','DTM','dtm',resolution='1 m',assets=[u.Asset('https://example.org/a','bad')])
        (self.root/'heightmap.npy').write_bytes(b'OLD');h=HTTP([Response(body=b'NOT TERRAIN')])
        with self.assertRaises(u.AcquisitionError):u.download(ds,BBOX,self.root,printf=lambda s:None,http=h)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'OLD');self.assertEqual(list((self.root/'UK_Data').glob('.partial*')),[])
    def test_no_source_mutation(self):
        a=ea_item();text=json.dumps(a);u.parse_england({'results':[a]});self.assertEqual(json.dumps(a),text)
    def test_snapshot_not_tk(self):
        from uk_lidar_ui import Value
        v=Value(2);results=[];t=threading.Thread(target=lambda:results.append(v.get()));t.start();t.join();self.assertEqual(results,[2])
    def test_las_crop_native_when_available(self):
        try:import laspy
        except ImportError:self.skipTest('Native laspy unavailable here; Windows build runs this with the installed dependency.')
        import pyproj
        h=laspy.LasHeader(point_format=3,version='1.2');h.add_crs(pyproj.CRS.from_epsg(27700));h.offsets=[530000,180000,0];h.scales=[.001,.001,.001]
        las=laspy.LasData(h);las.x=np.array([530010,530020,530090]);las.y=np.array([180010,180020,180090]);las.z=np.array([1.5,12.3,99])
        las.classification=[2,5,6];las.write(self.root/'source.las')
        with mock.patch.object(u,'projected_bounds',return_value=(530005,180005,530030,180030)):
            p,meta=u.crop_points(self.root/'source.las',self.root/'subset.las',BBOX,printf=lambda s:None)
        got=laspy.read(p);self.assertEqual(len(got.points),2);np.testing.assert_array_equal(got.z,[1.5,12.3]);np.testing.assert_array_equal(got.classification,[2,5]);self.assertEqual(got.header.parse_crs().to_epsg(),27700)
    def test_installed_gui_connections(self):
        path=Path(__file__).parent/'tgc_gui.py'
        if not path.is_file():self.fail('Run the verifier from the patched project directory.')
        text=path.read_text(encoding='utf-8-sig');tree=ast.parse(text)
        funcs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        self.assertIn('runUkLidarDem',funcs);self.assertIn('dem_files_override',[a.arg for a in funcs['runDEM'].args.args])
        self.assertIn('ex-US LiDAR / DEM From Local OSM',text);self.assertIn('USGS AWS EPT From Local OSM',text)
        body=ast.get_source_segment(text,funcs['runUkLidarDem'])
        self.assertIn('ignore_force_epsg=True',body);self.assertIn('same_project()',body);self.assertIn('custom_unmatched_osm',body)
    def test_builder_bundles_new_modules(self):
        text=(Path(__file__).parent/'BUILD_TGC_2K25_BETA7.py').read_text(encoding='utf-8-sig')
        self.assertIn("required.update({'uk_lidar_ui','uk_lidar_downloader'})",text)
        self.assertIn('VERIFY_BETA7_UK_DOWNLOAD.py',text)
    def _handoff_env(self):
        from uk_lidar_ui import Value
        project=self.root/'project';project.mkdir();osm=project/'map.osm';osm.write_text('<osm/>')
        src=(Path(__file__).parent/'tgc_gui.py').read_text(encoding='utf-8-sig')
        fn=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name=='runUkLidarDem')
        root=types.SimpleNamespace(filename=str(project))
        calls=[];alerts=[]
        options={'local_osm_file':Value(str(osm)),'custom_unmatched_osm':Value(False)}
        env={'root':root,'Path':Path,'math':math,'options_entries_dict':options,
             'lidar_processing_active':False,'dem_processing_active':False,
             'alert':alerts.append,'getAutoRedMaskSettings':lambda *a:(True,5.),
             '_mask_option_value':lambda opts,key,default:opts[key].get() if key in opts else default,
             'runLidar':lambda *a,**k:calls.append(('lidar',a,k)),
             'runDEM':lambda *a,**k:calls.append(('dem',a,k))}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'installed_uk_callback','exec'),env)
        return env,calls,alerts,project,osm
    def test_actual_lidar_handoff(self):
        import uk_lidar_ui
        env,calls,alerts,project,osm=self._handoff_env();capture={}
        def dialog(*args,**kwargs):capture.update(kwargs)
        with mock.patch.object(uk_lidar_ui,'UKDownloadDialog',side_effect=dialog):
            env['runUkLidarDem'](uk_lidar_ui.Value(2),uk_lidar_ui.Value('3857'),self.messages.append)
        self.assertTrue(env['lidar_processing_active']);capture['on_close']()
        result=u.DownloadResult(str(project),str(project/'UK_Data/data'),'pointcloud',['x.las'],'manifest')
        capture['on_ready'](result,'lidar',u.Dataset('x','England','Survey','pointcloud'))
        self.assertEqual(calls[0][0],'lidar');self.assertTrue(calls[0][2]['ignore_force_epsg'])
        self.assertEqual(calls[0][2]['lidar_dir_path_override'],result.data_dir);self.assertFalse(alerts)
        self.assertFalse(env['dem_processing_active'])
    def test_actual_dem_handoff(self):
        import uk_lidar_ui
        env,calls,alerts,project,osm=self._handoff_env();capture={}
        with mock.patch.object(uk_lidar_ui,'UKDownloadDialog',side_effect=lambda *a,**k:capture.update(k)):
            env['runUkLidarDem'](uk_lidar_ui.Value(1),uk_lidar_ui.Value(''),self.messages.append)
        capture['on_close']();result=u.DownloadResult(str(project),'data','dtm',['tile.tif'],'manifest')
        capture['on_ready'](result,'dem',u.Dataset('x','Wales','Survey','dtm'))
        self.assertEqual(calls[0][0],'dem');self.assertEqual(calls[0][2]['dem_files_override'],['tile.tif']);self.assertFalse(alerts)
    def test_project_switch_does_not_process_wrong_folder(self):
        import uk_lidar_ui
        env,calls,alerts,project,osm=self._handoff_env();capture={}
        with mock.patch.object(uk_lidar_ui,'UKDownloadDialog',side_effect=lambda *a,**k:capture.update(k)):
            env['runUkLidarDem'](uk_lidar_ui.Value(1),uk_lidar_ui.Value(''),self.messages.append)
        capture['on_close']();env['root'].filename=str(self.root/'different_project')
        capture['on_ready'](u.DownloadResult(str(project),'data','dtm',['tile.tif'],'manifest'),'dem',u.Dataset('x','Wales','Survey','dtm'))
        self.assertFalse(calls);self.assertTrue(alerts)
    def test_osm_switch_does_not_process_wrong_layout(self):
        import uk_lidar_ui
        env,calls,alerts,project,osm=self._handoff_env();capture={}
        with mock.patch.object(uk_lidar_ui,'UKDownloadDialog',side_effect=lambda *a,**k:capture.update(k)):
            env['runUkLidarDem'](uk_lidar_ui.Value(1),uk_lidar_ui.Value(''),self.messages.append)
        capture['on_close']();env['options_entries_dict']['local_osm_file']=uk_lidar_ui.Value(str(project/'different.osm'))
        capture['on_ready'](u.DownloadResult(str(project),'data','dtm',['tile.tif'],'manifest'),'dem',u.Dataset('x','Wales','Survey','dtm'))
        self.assertFalse(calls);self.assertTrue(alerts)
    def test_busy_and_custom_discovery_guard(self):
        import uk_lidar_ui
        env,calls,alerts,project,osm=self._handoff_env()
        with mock.patch.object(uk_lidar_ui,'UKDownloadDialog') as dialog:
            env['lidar_processing_active']=True;env['runUkLidarDem'](uk_lidar_ui.Value(1),None,self.messages.append)
            env['lidar_processing_active']=False;env['options_entries_dict']['custom_unmatched_osm']=uk_lidar_ui.Value(True)
            env['runUkLidarDem'](uk_lidar_ui.Value(1),None,self.messages.append)
            self.assertFalse(dialog.called);self.assertEqual(len(alerts),2)

    def test_python311_syntax(self):
        for name in ('uk_lidar_downloader.py','uk_lidar_ui.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8-sig'),feature_version=(3,11))


def gui_test():
    import tkinter as tk
    from uk_lidar_ui import UKDownloadDialog, MODES
    import time
    root=tk.Tk();root.withdraw();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);(p/'course.osm').write_text('<osm/>')
        closed=[];ready=[];dialog=UKDownloadDialog(root,p,p/'course.osm',printf=lambda s:None,on_close=lambda:closed.append(1),on_ready=lambda *a:ready.append(a))
        root.update();assert dialog.region.get()=='Auto';assert MODES[dialog.mode.get()][1]=='dem'
        assert dialog.download_button.instate(['disabled']);assert dialog.process.get()
        dialog.region.set('Northern Ireland');dialog.find();assert not dialog.busy
        dialog.region.set('Wales');dialog.mode.set(list(MODES)[1]);dialog.find();assert not dialog.busy
        # Execute actual worker/queue plumbing with an offline provider result.
        dataset=u.Dataset('x','England','Fixture DTM','dtm',assets=[u.Asset('https://example.org/a','tile')])
        with mock.patch.object(u,'course_bbox',return_value=BBOX),mock.patch.object(u,'discover',return_value=([dataset],[])):
            dialog.region.set('England');dialog.mode.set(list(MODES)[0]);dialog.find()
            until=time.monotonic()+3
            while dialog.busy and time.monotonic()<until:root.update();time.sleep(.02)
        root.update();assert len(dialog.datasets)==1;assert dialog.table.selection()==('0',)
        assert not dialog.download_button.instate(['disabled'])
        dialog._selection_changed();assert not dialog.datasets
        dialog.close();root.update();assert closed==[1];assert not ready;assert not errors
    root.destroy();print('Actual Tk UK dialog defaults, restrictions, background discovery queue, selection and close: PASS')

if __name__=='__main__':
    gui='--gui' in sys.argv
    if gui:sys.argv.remove('--gui')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if not result.wasSuccessful():raise SystemExit(1)
    if gui:gui_test()
