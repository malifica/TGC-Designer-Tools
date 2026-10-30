"""Offline ex-US regression checks. Network fixtures are NOT live-provider tests.
Run --live --osm <file> --region Scotland for read-only live discovery diagnostics.
"""
from pathlib import Path
import ast
import copy
import io
import json
import math
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode,parse_qs,urlparse,quote
import xml.etree.ElementTree as ET

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_origin
from PIL import Image
import uk_lidar_downloader as u
import scotland_s3 as s3
import exus_lidar_sources as e
import exus_raster as er

BUCK=(-2.9996820961,57.6636548251,-2.9817706039,57.6734809749)
SWISS=(8.0,46.9,8.01,46.91)
CANADA=(-75.71,45.39,-75.70,45.40)
JAPAN=(139.70,35.68,139.71,35.69)
SPAIN=(-3.71,40.41,-3.70,40.42)
KEY1='lidar/phase-1/dtm/27700/gridded/NJ46_1M_DTM_PHASE1.tif'
KEY2='lidar/phase-2/dtm/27700/gridded/NJ46_1M_DTM_PHASE2.tif'

class Response:
    def __init__(self,raw=b'',data=None,status=200,headers=None):
        self.content=raw;self.data=data;self.status_code=status;self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):
        if self.status_code>=400:raise u.requests.HTTPError(str(self.status_code))
    def json(self):return self.data
    def iter_content(self,size):
        for i in range(0,len(self.content),size):yield self.content[i:i+size]

class InventoryHTTP:
    """An in-memory S3 service; filenames are fixtures, not downloaded objects."""
    def __init__(self,keys,limit=1000,fail_prefix=None):
        self.keys=keys;self.limit=limit;self.calls=[];self.fail_prefix=fail_prefix
    def get(self,url,params=None,**kwargs):
        self.calls.append((url,copy.deepcopy(params)))
        if self.fail_prefix and params['prefix'].startswith(self.fail_prefix):raise u.requests.ConnectionError('fixture outage')
        assert 'srsp-catalog' not in url
        prefix=params['prefix'];delimiter=params.get('delimiter');entries=[];dirs=set()
        for key in sorted(self.keys):
            if not key.startswith(prefix):continue
            rest=key[len(prefix):]
            if delimiter and delimiter in rest:
                dirs.add(prefix+rest.split(delimiter)[0]+delimiter)
            else:entries.append(('object',key))
        entries=sorted(entries+[('prefix',v) for v in dirs],key=lambda v:v[1])
        start=int(params.get('continuation-token',0));limit=min(self.limit,int(params['max-keys']))
        selected=entries[start:start+limit];root=ET.Element('ListBucketResult')
        ET.SubElement(root,'EncodingType').text='url'
        end=start+len(selected);more=end<len(entries)
        ET.SubElement(root,'IsTruncated').text=str(more).lower()
        if more:ET.SubElement(root,'NextContinuationToken').text=str(end)
        for typ,key in selected:
            if typ=='prefix':ET.SubElement(ET.SubElement(root,'CommonPrefixes'),'Prefix').text=quote(key,safe='')
            else:
                o=ET.SubElement(root,'Contents');ET.SubElement(o,'Key').text=quote(key,safe='')
                ET.SubElement(o,'Size').text=str(self.keys[key]);ET.SubElement(o,'LastModified').text='2021-09-08T15:56:29.000Z'
        return Response(ET.tostring(root))
    def close(self):pass

class HTTP:
    def __init__(self,responses):self.responses=list(responses);self.calls=[]
    def request(self,method,url,**kw):
        self.calls.append((method,url,kw));r=self.responses.pop(0)
        if isinstance(r,Exception):raise r
        return r
    def get(self,url,**kw):return self.request('GET',url,**kw)
    def close(self):pass

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);s3._CACHE.clear()
    def tearDown(self):self.tmp.cleanup()
    def test_metric_warp_uses_horizontal_crs_only(self):
        from rasterio.warp import reproject as actual
        path=self.root/'compound.tif'
        box=(-2.99,57.665,-2.989,57.666)
        crs=pyproj.CRS.from_epsg(7405)
        tr=pyproj.Transformer.from_crs(4326,crs.to_2d(),always_xy=True)
        x,y=tr.transform(-2.9895,57.6655)
        with rasterio.open(path,'w',driver='GTiff',width=30,height=30,count=1,dtype='float32',
                           crs=crs,transform=from_origin(x-30,y+30,2,2),nodata=-9999.) as ds:
            ds.write(np.full((30,30),42,dtype='float32'),1)
        ds=u.Dataset('test','Spain','Fixture','dtm',metadata={'local_utm':True,'output_resolution_m':2})
        with mock.patch('rasterio.warp.reproject',wraps=actual) as called:
            result,meta=er.normalize(path,box,ds,{},printf=lambda s:None)
        self.assertFalse(pyproj.CRS.from_user_input(called.call_args.kwargs['src_crs']).is_compound)
        with rasterio.open(result) as out:
            values=out.read(1,masked=True).compressed();self.assertGreater(len(values),0)
            self.assertLess(float(np.max(np.abs(values-42))),.0001)
        self.assertFalse(meta['vertical_datum_conversion'])
    def test_japan_large_fine_request_keeps_coarser_choices(self):
        ds,notes=e.japan(None,(139.60,35.60,139.70,35.68),'dtm',None,lambda s:None)
        self.assertTrue(notes);self.assertGreater(len(ds),0)
        self.assertTrue(all(d.metadata['output_resolution_m']>=5 for d in ds))
    def test_all_requested_regions_exist(self):
        for name in ('Spain','Switzerland','Australia','Canada','Mexico','Japan','Scotland'):self.assertIn(name,u.REGIONS)
    def test_global_course_extent_validation(self):
        for b in (BUCK,SWISS,CANADA,JAPAN,SPAIN,(151,-34,151.01,-33.99),(-99.2,19.4,-99.19,19.41)):self.assertEqual(u.validate_bbox(b),b)
    def test_invalid_nan_inverted_world_extents(self):
        for b in ((170,5,-170,6),(0,0,180,80),(0,0,float('nan'),2),(10,50,9,50.1),(-156,19,-155.99,19.01)):
            with self.assertRaises(u.AcquisitionError):u.validate_bbox(b)
    def test_auto_country_routing(self):
        for bbox,region in ((BUCK,'Scotland'),(SWISS,'Switzerland'),(CANADA,'Canada'),(JAPAN,'Japan'),(SPAIN,'Spain'),( (-17.9,28.7,-17.89,28.71),'Spain')):
            self.assertIn(region,u.provider_regions(bbox))
    def test_explicit_wrong_country_no_download(self):
        with self.assertRaises(u.AcquisitionError):u.provider_regions(JAPAN,'Scotland')
    def test_grid_origins(self):
        self.assertEqual(s3.grid_origin('NJ'),(300000,800000));self.assertEqual(s3.grid_origin('TQ'),(500000,100000))
        self.assertEqual(s3.grid_letters(340000,864000),'NJ')
    def test_grid_roundtrip_all_supported_squares(self):
        for x in range(0,700000,100000):
            for y in range(0,1300000,100000):self.assertEqual(s3.grid_origin(s3.grid_letters(x,y)),(x,y))
    def test_subtiles_and_quadrants(self):
        self.assertEqual(list(s3.tile_bounds('NJ46SW.tif'))[0][1],(340000,860000,345000,865000))
        self.assertEqual(list(s3.tile_bounds('NJ4064_1M.tif'))[0][1],(340000,864000,341000,865000))
        self.assertEqual(s3.search_strips((340460,864180,341540,865280)),['NJ4'])
    def test_buckpool_report_exact_keys_replayed(self):
        h=InventoryHTTP({KEY1:31528789,KEY2:82722318})
        ds,notes=s3.discover(h,BUCK,'dtm',printf=lambda s:None)
        self.assertEqual({a.name for d in ds for a in d.assets},{'NJ46_1M_DTM_PHASE1.tif','NJ46_1M_DTM_PHASE2.tif'})
        self.assertEqual({a.bytes for d in ds for a in d.assets},{31528789,82722318})
        self.assertTrue(all(d.year=='' for d in ds));self.assertFalse(notes)
        self.assertLess(len(h.calls),30)
    def test_scotland_dtm_does_not_query_pointcloud_or_dsm(self):
        keys={KEY1:1,KEY2:2,'lidar/phase-1/dsm/27700/gridded/NJ46_DSM.tif':1,'lidar/phase-2/laz/27700/gridded/NJ4064.laz':1}
        h=InventoryHTTP(keys);s3.discover(h,BUCK,'dtm',printf=lambda s:None)
        self.assertFalse(any('/laz/' in p['prefix'] or '/dsm/' in p['prefix'] for _,p in h.calls))
    def test_scotland_skips_phase2_points_not_phase2_dtm(self):
        h=InventoryHTTP({KEY2:2,'lidar/phase-2/laz/27700/gridded/NJ4064.laz':1,'lidar/phase-3/laz/27700/gridded/NJ4064.laz':2})
        ds,n=s3.discover(h,BUCK,'all',printf=lambda s:None)
        self.assertEqual(len(ds),2);self.assertFalse(any('/phase-2/laz/' in a.url for d in ds for a in d.assets))
    def test_scotland_pagination_preserves_fine_tiles(self):
        keys={KEY1:1,'lidar/phase-1/dtm/27700/gridded/NJ4064_1m.tif':2,'lidar/phase-1/dtm/27700/gridded/NJ4165_1m.tif':3}
        h=InventoryHTTP(keys,limit=1);ds,n=s3.discover(h,BUCK,'dtm',printf=lambda s:None)
        self.assertEqual(sum(len(d.assets) for d in ds),3)
        self.assertTrue(any('continuation-token' in p for _,p in h.calls))
    def test_scotland_ignores_other_grid_tiles(self):
        h=InventoryHTTP({KEY1:1,'lidar/phase-1/dtm/27700/gridded/NJ49.tif':5,'lidar/phase-1/dtm/27700/gridded/TQ38.tif':3})
        ds,n=s3.discover(h,BUCK,'dtm',printf=lambda s:None);self.assertEqual(sum(len(d.assets) for d in ds),1)
    def test_scotland_file_prefix_not_lost(self):
        h=InventoryHTTP({'lidar/phase-1/dtm/27700/gridded/DTM_NJ46.tif':1})
        ds,n=s3.discover(h,BUCK,'dtm',printf=lambda s:None);self.assertEqual(len(ds),1)
    def test_scotland_other_collection_failure_keeps_found(self):
        h=InventoryHTTP({KEY1:1,KEY2:2},fail_prefix='lidar/phase-2/')
        ds,n=s3.discover(h,BUCK,'dtm',printf=lambda s:None);self.assertEqual(len(ds),1);self.assertTrue(n)
    def test_scotland_unknown_filename_not_false_no_coverage(self):
        h=InventoryHTTP({'lidar/phase-4/dtm/27700/gridded/12345678.tif':1})
        ds,n=s3.discover(h,BUCK,'dtm',printf=lambda s:None);self.assertFalse(ds);self.assertTrue(any('partial' in x for x in n))
    def test_scotland_cancel_no_network(self):
        event=threading.Event();event.set();h=InventoryHTTP({KEY1:1})
        with self.assertRaises(u.Cancelled):s3.discover(h,BUCK,'dtm',event,lambda s:None)
        self.assertFalse(h.calls)
    def test_s3_malformed_truncation(self):
        with self.assertRaises(u.AcquisitionError):s3.parse_page(b'<ListBucketResult><IsTruncated>true</IsTruncated></ListBucketResult>')
    def test_s3_non_inventory(self):
        with self.assertRaises(u.AcquisitionError):s3.parse_page(b'<html>bad</html>')
    def test_s3_endpoint_fallback_no_catalogue(self):
        h=InventoryHTTP({KEY1:1});original=h.get
        def get(url,**kw):
            if url==s3.ENDPOINTS[0]:raise u.requests.ConnectionError('fixture first host failed')
            return original(url,**kw)
        h.get=get;ds,n=s3.discover(h,BUCK,'dtm',printf=lambda s:None)
        self.assertTrue(ds);self.assertTrue(all(a.url.startswith(s3.ENDPOINTS[1]) for d in ds for a in d.assets))
    def test_discover_preserves_scotland_notices(self):
        with mock.patch.object(s3,'discover',return_value=([u.Dataset('s','Scotland','a','dtm',resolution='1 m')],['partial fixture'])):
            data,errors=u.discover(BUCK,'Scotland','dtm',http=HTTP([]),printf=lambda s:None)
        self.assertEqual(len(data),1);self.assertIn('partial fixture',errors)
    def test_country_support_honest(self):
        for country in ('Australia','Mexico'):
            self.assertIn('PORTAL',u.support_notice(country,'dtm'))
        for country in ('Canada','Spain','Japan','Wales'):
            self.assertIn('only',u.support_notice(country,'pointcloud'))
    def test_portal_only_makes_no_request(self):
        h=HTTP([]);ds,errors=u.discover((151,-34,151.01,-33.99),'Australia','dtm',http=h,printf=lambda s:None)
        self.assertFalse(ds);self.assertTrue(errors);self.assertFalse(h.calls)
    def test_stac_query_bbox_and_pagination(self):
        h=HTTP([Response(data={'features':[{'id':'1','assets':{}}],'links':[{'rel':'next','href':'?offset=100'}]}),Response(data={'features':[{'id':'2','assets':{}}]})])
        items,notes=e._stac_items(h,e.SWISS,'a',SWISS,printf=lambda s:None)
        self.assertEqual(len(items),2);self.assertIn('bbox',h.calls[0][2]['params']);self.assertFalse(notes)
    def test_stac_second_page_failure_retains_items(self):
        h=HTTP([Response(data={'features':[{'id':'1','assets':{}}],'links':[{'rel':'next','href':'?offset=100'}]}),u.requests.ConnectionError('fixture')])
        items,notes=e._stac_items(h,e.SWISS,'a',SWISS,printf=lambda s:None);self.assertEqual(len(items),1);self.assertTrue(notes)
    def test_swiss_latest_tile_resolution_separation(self):
        def item(year):return {'id':str(year),'bbox':list(SWISS),'properties':{'datetime':str(year)+'-01-01'},'assets':{
            'dtm':{'href':f'https://data.geo.admin.ch/swissalti3d_{year}_0.5_2056_5728.tif','gsd':.5,'proj:epsg':2056},
            'other':{'href':f'https://data.geo.admin.ch/swissalti3d_{year}_2_2056_5728.tif','gsd':2,'proj:epsg':2056},
            'jpg':{'href':'https://data.geo.admin.ch/thumb.jpg'}}}
        data=e.parse_swiss([item(2020),item(2024)],'dtm')
        self.assertEqual(len(data),2);self.assertTrue(all('2024' in d.assets[0].url for d in data));self.assertEqual({d.resolution for d in data},{'0.5 m','2 m'})
    def test_swiss_copc_and_archive_separate(self):
        item={'id':'a','bbox':list(SWISS),'assets':{'laz':{'href':'https://data.geo.admin.ch/a.copc.laz'},'zip':{'href':'https://data.geo.admin.ch/a.las.zip'}}}
        ds=e.parse_swiss([item],'pointcloud');self.assertEqual(len(ds),2)
    def test_canada_dtm_only_no_dsm_hillshade(self):
        item={'id':'a','assets':{'dtm':{'href':'https://datacube.services.geo.ca/terrain.tif'},'dsm':{'href':'https://datacube.services.geo.ca/surface.tif'},'hillshade':{'href':'https://datacube.services.geo.ca/shade.tif'}}}
        h=HTTP([Response(data={'features':[item]}),Response(data={'features':[]})]);ds,n=e.canada(h,CANADA,'dtm',None,lambda s:None)
        self.assertEqual(len(ds),1);self.assertEqual(ds[0].assets[0].transport,'cog');self.assertIn('terrain',ds[0].assets[0].url);self.assertTrue(ds[0].metadata['local_utm'])
    def test_canada_pointcloud_unavailable_explicit(self):
        ds,n=e.canada(HTTP([]),CANADA,'pointcloud',None,lambda s:None);self.assertFalse(ds);self.assertTrue(n)
    def test_spain_capabilities_actual_identifier(self):
        caps=b'<Capabilities><Contents><CoverageSummary><CoverageId>Elevacion25830_5</CoverageId></CoverageSummary><CoverageSummary><CoverageId>Elevacion25830_25</CoverageId></CoverageSummary></Contents></Capabilities>'
        desc=b'<CoverageDescriptions><CoverageDescription><boundedBy><Envelope srsName="EPSG:25830" axisLabels="x y"><lowerCorner>100000 4000000</lowerCorner><upperCorner>900000 4900000</upperCorner></Envelope></boundedBy></CoverageDescription></CoverageDescriptions>'
        ds,n=e.spain(HTTP([Response(caps),Response(desc)]),SPAIN,'dtm',None,lambda s:None)
        self.assertEqual(len(ds),1);q=parse_qs(urlparse(ds[0].assets[0].url).query)
        self.assertEqual(q['coverageId'],['Elevacion25830_5']);self.assertEqual(len(q['subset']),2);self.assertEqual(q['format'],['image/tiff'])
    def test_spain_unknown_axes_refused(self):
        caps=b'<Capabilities><CoverageSummary><CoverageId>Elevacion25830_5</CoverageId></CoverageSummary></Capabilities>'
        desc=b'<CoverageDescriptions><Envelope srsName="EPSG:25830" axisLabels="foo bar"><lowerCorner>0 0</lowerCorner><upperCorner>9 9</upperCorner></Envelope></CoverageDescriptions>'
        ds,n=e.spain(HTTP([Response(caps),Response(desc)]),SPAIN,'dtm',None,lambda s:None);self.assertFalse(ds);self.assertTrue(n)
    def test_japan_supported_zoom_product_separation(self):
        ds,n=e.japan(HTTP([]),JAPAN,'dtm',None,lambda s:None)
        self.assertEqual(len(ds),4);self.assertTrue(all(d.metadata['coverage_provisional'] for d in ds))
        self.assertTrue(all(a.metadata['z'] in (17,15) for d in ds for a in d.assets))
        self.assertTrue(all('/xyz/' in a.url and a.url.endswith('.png') for d in ds for a in d.assets))
    def test_gsi_decode_positive_negative_nodata(self):
        a=np.zeros((256,256,3),np.uint8);a[0,0]=[0,0,123];a[0,1]=[255,255,156];a[0,2]=[128,0,0]
        out=io.BytesIO();Image.fromarray(a).save(out,format='PNG');h=e.decode_gsi_png(out.getvalue())
        self.assertAlmostEqual(float(h[0,0]),1.23,places=5);self.assertAlmostEqual(float(h[0,1]),-1,places=5);self.assertTrue(np.isnan(h[0,2]))
    def test_gsi_image_size_error(self):
        out=io.BytesIO();Image.new('RGB',(10,10)).save(out,format='PNG')
        with self.assertRaises(u.AcquisitionError):e.decode_gsi_png(out.getvalue())
    def test_gsi_404_does_not_substitute_other_product(self):
        h=HTTP([Response(status=404)]);a=u.Asset('https://cyberjapandata.gsi.go.jp/x','a',transport='gsi_png')
        self.assertIsNone(e.gsi_raster(a,self.root/'none.tif',h,None,lambda s:None));self.assertEqual(len(h.calls),1)
    def test_gsi_500_not_treated_as_no_data(self):
        with self.assertRaises(u.requests.HTTPError):e.gsi_raster(u.Asset('https://cyberjapandata.gsi.go.jp/x','a'),self.root/'x',HTTP([Response(status=500)]),None,lambda s:None)
    def test_local_utm_zone_north_south(self):
        self.assertEqual(er.local_utm(JAPAN).to_epsg(),32654)
        self.assertEqual(er.local_utm((151,-34,151.1,-33.9)).to_epsg(),32756)
    def test_canada_metric_reprojection(self):
        p=self.root/'can.tif';pr=pyproj.Transformer.from_crs(4326,3979,always_xy=True);x,y=pr.transform(-75.705,45.395)
        with rasterio.open(p,'w',driver='GTiff',width=100,height=100,count=1,dtype='float32',crs='EPSG:3979',transform=from_origin(x-50,y+50,1,1),nodata=-9999.) as ds:ds.write(np.full((100,100),42,np.float32),1)
        d=u.Dataset('c','Canada','c','dtm',metadata={'local_utm':True,'output_resolution_m':1})
        _,meta=er.normalize(p,CANADA,d,{},printf=lambda s:None)
        with rasterio.open(p) as ds:
            self.assertEqual(ds.crs.to_epsg(),32618);self.assertAlmostEqual(float(ds.read(1,masked=True).mean()),42,places=4)
        self.assertFalse(meta['vertical_datum_conversion'])
    def test_japan_metric_scale_not_mercator(self):
        p=self.root/'j.tif';pr=pyproj.Transformer.from_crs(4326,3857,always_xy=True);x,y=pr.transform(139.705,35.685)
        with rasterio.open(p,'w',driver='GTiff',width=100,height=100,count=1,dtype='float32',crs=3857,transform=from_origin(x-250,y+250,5,5),nodata=-9999.) as ds:ds.write(np.full((100,100),100,np.float32),1)
        d=u.Dataset('j','Japan','j','dtm',metadata={'local_utm':True,'output_resolution_m':5})
        er.normalize(p,JAPAN,d,{},printf=lambda s:None)
        with rasterio.open(p) as ds:
            self.assertEqual(ds.crs.to_epsg(),32654);self.assertLess(ds.width,90);self.assertGreater(ds.width,78)
    def test_existing_uk_raster_not_reprojected(self):
        p=self.root/'uk';p.write_bytes(b'UNCHANGED');d=u.Dataset('s','Scotland','s','dtm')
        ret,meta=er.normalize(p,BUCK,d,{'hello':1},printf=lambda s:None)
        self.assertEqual(p.read_bytes(),b'UNCHANGED');self.assertEqual(meta,{'hello':1})
    def test_metric_cancel_preserves_original(self):
        p=self.root/'source.tif';p.write_bytes(b'OLD');event=threading.Event();event.set()
        with self.assertRaises(u.Cancelled):er.normalize(p,JAPAN,u.Dataset('j','Japan','j','dtm',metadata={'local_utm':True,'output_resolution_m':5}),{},cancel=event)
        self.assertEqual(p.read_bytes(),b'OLD')
    def test_existing_storage_retained_new_country_separate(self):
        self.assertEqual(u.storage_folder('Scotland'),'UK_Data');self.assertEqual(u.storage_folder('Japan'),'ExUS_Data')
    def test_gsi_download_full_pipeline_and_cache(self):
        bbox=(139.7000,35.6800,139.7004,35.6804)
        datasets,_=e.japan(None,bbox,'dtm',None,lambda s:None)
        d=next(d for d in datasets if d.metadata['source_layer']=='dem5a_png')
        image=np.zeros((256,256,3),np.uint8);image[:]=[0,16,146]  # 42.42 metres
        raw=io.BytesIO();Image.fromarray(image).save(raw,format='PNG')
        h=HTTP([Response(raw.getvalue()) for _ in d.assets])
        (self.root/'heightmap.npy').write_bytes(b'ORIGINAL_HEIGHTMAP')
        result=u.download(d,bbox,self.root,http=h,printf=lambda s:None)
        self.assertTrue(result.files);self.assertIn('ExUS_Data',result.data_dir)
        for path in result.files:
            with rasterio.open(path) as r:
                self.assertEqual(r.crs.to_epsg(),32654)
                self.assertAlmostEqual(float(r.read(1,masked=True).mean()),42.42,places=3)
        manifest=json.loads(Path(result.manifest).read_text(encoding='utf-8-sig'))
        self.assertTrue(manifest['complete']);self.assertFalse(manifest['outputs'][0]['metadata']['vertical_datum_conversion'])
        reuse=HTTP([]);second=u.download(d,bbox,self.root,http=reuse,printf=lambda s:None)
        self.assertEqual(second.files,result.files);self.assertFalse(reuse.calls)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'ORIGINAL_HEIGHTMAP')
    def test_gsi_all_missing_preserves_heightmap_no_final_folder(self):
        bbox=(139.7000,35.6800,139.7004,35.6804)
        d=e.japan(None,bbox,'dtm',None,lambda s:None)[0][1]
        (self.root/'heightmap.npy').write_bytes(b'ORIGINAL')
        with self.assertRaises(u.AcquisitionError):
            u.download(d,bbox,self.root,http=HTTP([Response(status=404) for _ in d.assets]),printf=lambda s:None)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'ORIGINAL')
        self.assertFalse(list((self.root/'ExUS_Data').glob('.partial*')))
    def test_builder_explicitly_bundles_and_checks_new_modules(self):
        text=(Path(__file__).parent/'BUILD_TGC_2K25_BETA7.py').read_text(encoding='utf-8-sig')
        self.assertIn("run(py,root/'VERIFY_BETA7_EXUS_DOWNLOAD.py')",text)
        self.assertNotIn("'--gui'",text)
        for name in ('scotland_s3','exus_lidar_sources','exus_raster'):
            self.assertIn("'--hidden-import','"+name+"'",text)
        self.assertIn('TGC_BETA7_SCOTLAND_DIRECT_S3_V1',text)

    def test_new_modules_python311_parse(self):
        for name in ('scotland_s3.py','exus_lidar_sources.py','exus_raster.py','uk_lidar_downloader.py','uk_lidar_ui.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8-sig'),feature_version=(3,11))
    def test_no_dead_catalogue_calls(self):
        self.assertNotIn('srsp-catalog',__import__('inspect').getsource(u.discover)+__import__('inspect').getsource(u.scotland_discover))
    def test_ui_exus_label_preserves_window_helper(self):
        text=(Path(__file__).parent/'uk_lidar_ui.py').read_text(encoding='utf-8-sig')
        self.assertIn('ex-US LiDAR / DEM From Local OSM',text);self.assertIn('open_large_window',text)
        self.assertIn('PanedWindow',text);self.assertIn('uk_selected',text)


def gui_test():
    import tkinter as tk
    import time
    from uk_lidar_ui import UKDownloadDialog,MODES
    root=tk.Tk();root.withdraw();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);osm=p/'a.osm';osm.write_text('<osm/>');d=UKDownloadDialog(root,p,osm,printf=lambda s:None)
        root.update()
        assert 'ex-US' in d.window.title()
        assert set(e.REGIONS)<=set(d._region_combo['values'])
        for name in ('Australia','Mexico'):
            d.region.set(name);d._selection_changed();d.find();root.update()
            assert not d.busy and d.download_button.instate(['disabled'])
            assert 'PORTAL' in d.detail.get()
        d.region.set('Switzerland');d._selection_changed()
        ds=u.Dataset('a','Switzerland','Fixture Swiss selection','dtm',assets=[u.Asset('https://example.org/a.tif','a')])
        with mock.patch.object(u,'course_bbox',return_value=SWISS),mock.patch.object(u,'discover',return_value=([ds],[])):
            d.find();deadline=time.monotonic()+3
            while d.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
        assert d._selected() is ds and d.table.selection()==('0',)
        assert not d.download_button.instate(['disabled'])
        d.close();root.update();assert not errors
    root.destroy();print('Actual ex-US Tk country selector, portal-only state, discovery queue and selected dataset: PASS')


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--gui',action='store_true');parser.add_argument('--live',action='store_true')
    parser.add_argument('--osm');parser.add_argument('--region',default='Scotland',choices=u.REGIONS)
    parser.add_argument('--kind',default='dtm',choices=('dtm','pointcloud','all'));parser.add_argument('--output',default='EXUS_DISCOVERY.json')
    args=parser.parse_args()
    if args.live:
        if not args.osm:parser.error('--live requires --osm')
        bbox=u.course_bbox(args.osm);data,errors=u.discover(bbox,args.region,args.kind)
        from dataclasses import asdict
        Path(args.output).write_text(json.dumps({'bbox':bbox,'datasets':[asdict(d) for d in data],'notices':errors,'data_download_performed':False},indent=2),encoding='utf-8')
        print('Read-only discovery saved:',args.output);return
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if not result.wasSuccessful():raise SystemExit(1)
    if args.gui:gui_test()
if __name__=='__main__':main()
