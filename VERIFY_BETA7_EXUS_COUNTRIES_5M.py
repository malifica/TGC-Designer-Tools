"""Offline provider-contract + real raster tests. These are NOT live HTTP tests."""
from pathlib import Path
import ast
import io
import json
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs,urlparse
import xml.etree.ElementTree as ET
import numpy as np
import pyproj
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
import uk_lidar_downloader as u
import exus_lidar_sources as old
import exus_additional_countries as new
import exus_resolution_policy as policy

BOXES={'Finland':(24.9400,60.1700,24.9402,60.1702),'France':(2.3500,48.8500,2.3502,48.8502),
 'Germany':(7.,51.,7.0002,51.0002),'Bavaria':(11.58,48.14,11.5802,48.1402),
 'Netherlands':(4.9,52.37,4.9002,52.3702),'New Zealand':(174.77,-41.29,174.7702,-41.2898),
 'Poland':(21.,52.23,21.0002,52.2302)}

class Response:
    def __init__(self,data=None,raw=b'',status=200):self.data=data;self.content=raw;self.status_code=status;self.headers={}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):
        if self.status_code>=400:raise u.requests.HTTPError(str(self.status_code))
    def json(self):return self.data
    def iter_content(self,n):
        for k in range(0,len(self.content),n):yield self.content[k:k+n]

class HTTP:
    """Deterministic fake network; every request is captured for contract checks."""
    def __init__(self,queue):self.queue=list(queue);self.calls=[]
    def get(self,url,**kwargs):return self.request('GET',url,**kwargs)
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs));value=self.queue.pop(0)
        if isinstance(value,Exception):raise value
        return value
    def close(self):pass


def caps(identifier,version='2.0.1'):
    if version=='1.0.0':return f'<WCS_Capabilities><ContentMetadata><CoverageOfferingBrief><name>{identifier}</name></CoverageOfferingBrief></ContentMetadata></WCS_Capabilities>'.encode()
    return f'<Capabilities><Contents><CoverageSummary><CoverageId>{identifier}</CoverageId></CoverageSummary></Contents></Capabilities>'.encode()


def description(epsg,spacing,labels='x y',reverse=False):
    lower,upper='-10000000 -10000000','20000000 20000000'
    return f'<CoverageDescriptions><Envelope srsName="EPSG:{epsg}" axisLabels="{labels}"><lowerCorner>{lower}</lowerCorner><upperCorner>{upper}</upperCorner></Envelope><RectifiedGrid><offsetVector>{spacing} 0</offsetVector><offsetVector>0 {-spacing}</offsetVector></RectifiedGrid></CoverageDescriptions>'.encode()


def wcs_http(identifier,epsg,res,version='2.0.1',labels='x y'):
    return HTTP([Response(raw=caps(identifier,version)),Response(raw=description(epsg,res,labels))])


def float_tiff(bounds,res,epsg,value=123.25,dtype='float32',bands=1):
    w,s,e,n=bounds;width=round((e-w)/res);height=round((n-s)/res)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=width,height=height,count=bands,dtype=dtype,
                      crs=f'EPSG:{epsg}',transform=from_origin(w,n,res,res),nodata=None) as dst:
            dst.write(np.full((bands,height,width),value,dtype=dtype))
        return mem.read()


def france_http():
    raw=b'<WMS_Capabilities><Capability><Request><GetMap><Format>image/geotiff</Format></GetMap></Request><Layer><Layer><Name>IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93</Name></Layer><Layer><Name>ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES</Name></Layer><Layer><Name>IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93</Name></Layer></Layer></Capability></WMS_Capabilities>'
    return HTTP([Response(raw=raw)])

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);new._NZ_CACHE.clear()
    def tearDown(self):self.temp.cleanup()
    def test_all_six_routable_and_alphabetical(self):
        self.assertEqual(u.REGIONS[1:],tuple(sorted(u.REGIONS[1:])))
        self.assertEqual(u.REGIONS,old.REGIONS)
        for name in new.REGIONS:
            with self.subTest(name=name):
                self.assertEqual(u.provider_regions(BOXES[name],name),[name]);self.assertIn(name,u.PROVIDERS)
    def test_six_are_not_portal_placeholders(self):
        for name in new.REGIONS:
            self.assertNotIn(name,old.PORTAL_ONLY);self.assertFalse(u.support_notice(name,'dtm'))
            self.assertIn('terrain',u.support_notice(name,'pointcloud').lower())
    def test_no_claim_of_raw_points_from_dem(self):
        for name in new.REGIONS:
            data,notes=new.discover(name,HTTP([]),BOXES[name],'pointcloud',printf=lambda s:None)
            self.assertEqual(data,[]);self.assertTrue(notes)
    def test_finland_public_keyless_2m(self):
        h=wcs_http('paituli__mml_dem_2m_2018',3067,2.,labels='E N')
        ds,n=new.finland(h,BOXES['Finland'],'dtm',None,lambda s:None)
        self.assertFalse(n);self.assertEqual(policy.dataset_spacing(ds[0]),2.)
        self.assertNotIn('api',parse_qs(urlparse(ds[0].assets[0].url).query))
    def test_netherlands_only_dtm_half_metre(self):
        h=wcs_http('dtm_05m',28992,.5)
        ds,n=new.netherlands(h,BOXES['Netherlands'],'dtm',None,lambda s:None)
        self.assertEqual(policy.dataset_spacing(ds[0]),.5);self.assertNotIn('dsm',ds[0].id)
    def test_germany_nrw_native_one_metre(self):
        h=wcs_http('nw_dgm',25832,1.)
        ds,n=new.germany(h,BOXES['Germany'],'dtm',None,lambda s:None)
        self.assertEqual(len(ds),1);self.assertIn('NRW',ds[0].title);self.assertFalse(n)
    def test_germany_not_nationwide_fallback(self):
        ds,n=new.germany(HTTP([]),(13.4,52.5,13.401,52.501),'dtm',None,lambda s:None)
        self.assertFalse(ds);self.assertIn('NRW and Bavaria',' '.join(n))
    def test_bavaria_reads_returned_links_not_guessed(self):
        box=u.projected_bounds(BOXES['Bavaria'],'EPSG:25832',lambda s:None);x=int(box[0]//1000);y=int(box[1]//1000)
        name=f'{x}_{y}.tif';url='https://download1.bayernwolke.de/a/dgm/dgm1/'+name
        raw=f'<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="{name}"><size>1234</size><url>{url}</url></file><file name="100_1000.tif"><url>https://example.org/unrelated.tif</url></file></metalink>'.encode()
        ds,n=new.bavaria(HTTP([Response(raw=raw)]),BOXES['Bavaria'],None,lambda s:None)
        self.assertEqual([a.url for a in ds[0].assets],[url]);self.assertEqual(ds[0].assets[0].bytes,1234)
    def test_bavaria_unsupported_names_not_invented(self):
        ds,n=new.bavaria(HTTP([Response(raw=b'<metalink><file name="unknown.tif"/></metalink>')]),BOXES['Bavaria'],None,lambda s:None)
        self.assertFalse(ds);self.assertTrue(n)
    def test_france_separate_fine_and_five_no_dsm(self):
        ds,n=new.france(france_http(),BOXES['France'],'dtm',None,lambda s:None)
        self.assertEqual([policy.dataset_spacing(d) for d in ds],[.5,5.]);self.assertFalse(n)
        for d in ds:
            self.assertTrue(all(a.metadata['require_float'] for a in d.assets))
            self.assertNotIn('MNS',d.id)
    def test_france_no_png_or_image_fallback(self):
        h=HTTP([Response(raw=b'<WMS_Capabilities><GetMap><Format>image/png</Format></GetMap></WMS_Capabilities>')])
        with self.assertRaises(u.AcquisitionError):new.france(h,BOXES['France'],'dtm',None,lambda s:None)
    def test_poland_advertised_dtm_not_ortho_example(self):
        h=wcs_http('DTM_PL',2180,1.,'1.0.0',labels='N E')
        ds,n=new.poland(h,BOXES['Poland'],'dtm',None,lambda s:None)
        q=parse_qs(urlparse(ds[0].assets[0].url).query)
        self.assertEqual(q['COVERAGE'],['DTM_PL']);self.assertEqual(q['RESX'],['1.0'])
        expected=ds[0].assets[0].metadata['requested_native_bounds'];encoded=list(map(float,q['BBOX'][0].split(',')))
        np.testing.assert_allclose(encoded,expected)  # WCS 1.0 uses x/y; EPSG north/east is not the wire order.
    def test_poland_refuses_unknown_surface(self):
        with self.assertRaises(u.AcquisitionError):new.poland(HTTP([Response(raw=caps('Orthoimagery','1.0.0'))]),BOXES['Poland'],'dtm',None,lambda s:None)
    def test_wcs_unknown_axes_refused(self):
        with self.assertRaises(u.AcquisitionError):new.describe_wcs(ET.fromstring(description(3067,2.,'foo bar')),3067,2.)
    def test_wcs_coarse_metadata_rejected(self):
        with self.assertRaises(u.AcquisitionError):new.describe_wcs(ET.fromstring(description(3067,10.,'E N')),3067,2.)
    def test_wcs_crs_mismatch_refused(self):
        with self.assertRaises(u.AcquisitionError):new.describe_wcs(ET.fromstring(description(3857,2.)),3067,2.)
    def test_wcs_no_silent_named_product_downgrade(self):
        with self.assertRaises(u.AcquisitionError):new.describe_wcs(ET.fromstring(description(3067,4.,'E N')),3067,2.)
    def test_wcs_windows_limits_no_gaps(self):
        cells=list(new.split_windows((0,0,4500,3000),.5))
        self.assertTrue(all(w*h<=1800**2 for *_,w,h in cells))
        self.assertEqual(sum(w*h*.25 for *_,w,h in cells),4500*3000)
    def test_xml_external_entities_rejected(self):
        with self.assertRaises(u.AcquisitionError):new.xml_get(HTTP([Response(raw=b'<!DOCTYPE x><Capabilities/>')]),'https://example.org',{},None)
    def test_xml_service_exception_not_no_coverage(self):
        with self.assertRaises(u.AcquisitionError):new.xml_get(HTTP([Response(raw=b'<ExceptionReport><Exception>Unavailable</Exception></ExceptionReport>')]),'https://example.org',{},None)
    def test_cancel_before_provider_request(self):
        event=threading.Event();event.set();h=HTTP([])
        with self.assertRaises(u.Cancelled):new.finland(h,BOXES['Finland'],'dtm',event,lambda s:None)
        self.assertEqual(h.calls,[])
    def test_new_zealand_static_collection_intersections(self):
        base=new.NZ_COLLECTION.rsplit('/',1)[0]+'/'
        col={'type':'Collection','links':[{'rel':'item','href':'near.json'},{'rel':'item','href':'far.json'}]}
        def item(id,bbox):return {'type':'Feature','id':id,'bbox':bbox,'properties':{'gsd':1},'assets':{'dem':{'href':id+'.tiff','roles':['data']},'hillshade':{'href':'shade.tif'}}}
        h=HTTP([Response(data=col),Response(data=item('near',BOXES['New Zealand'])),Response(data=item('far',[169,-46,169.1,-45.9]))])
        ds,n=new.new_zealand(h,BOXES['New Zealand'],'dtm',None,lambda s:None)
        self.assertEqual([a.url for a in ds[0].assets],[base+'near.tiff']);self.assertFalse(n)
    def test_new_zealand_partial_item_failure_retains_success(self):
        col={'type':'Collection','links':[{'rel':'item','href':'one.json'},{'rel':'item','href':'two.json'}]}
        item={'type':'Feature','id':'one','bbox':BOXES['New Zealand'],'assets':{'data':{'href':'one.tiff'}}}
        h=HTTP([Response(data=col),Response(data=item),u.requests.ConnectionError('fixture metadata failure')])
        ds,n=new.new_zealand(h,BOXES['New Zealand'],'dtm',None,lambda s:None)
        self.assertEqual(len(ds[0].assets),1);self.assertIn('incomplete',' '.join(n))
    def test_new_zealand_metadata_cache_not_project_coordinates(self):
        item={'type':'Feature','id':'one','bbox':BOXES['New Zealand'],'assets':{'data':{'href':'one.tiff'}}}
        self.assertTrue(new.parse_nz_item(item,new.NZ_COLLECTION,BOXES['New Zealand']))
        self.assertFalse(new.parse_nz_item(item,new.NZ_COLLECTION,(170,-44,170.1,-43.9)))
    def test_nz_outside_bucket_refused(self):
        with self.assertRaises(u.AcquisitionError):new._https_s3('https://example.org/not-linz.tif',new.NZ_COLLECTION)
    def test_resolution_5_accepted_10_rejected(self):
        for r in (.25,.5,1,2,5):self.assertEqual(policy.dataset_spacing(u.Dataset('a','France','a','dtm',resolution=f'{r} m')),r)
        with self.assertRaises(u.AcquisitionError):policy.dataset_spacing(u.Dataset('a','France','a','dtm',resolution='10 m',metadata={'output_resolution_m':1}))
    def test_unknown_resolution_is_not_silently_accepted(self):
        with self.assertRaises(u.AcquisitionError):policy.dataset_spacing(u.Dataset('a','France','a','dtm'))
    def test_mixed_resolution_maximum_wins(self):
        self.assertEqual(policy.dataset_spacing(u.Dataset('a','France','a','dtm',resolution='1–5 m')),5)
        with self.assertRaises(u.AcquisitionError):policy.dataset_spacing(u.Dataset('a','France','a','dtm',resolution='1–10 m'))
    def test_resolution_cm_units(self):self.assertEqual(policy.resolution_numbers('50 cm'),[.5])
    def test_nonfinite_spacing_rejected(self):
        with self.assertRaises(u.AcquisitionError):policy.dataset_spacing(u.Dataset('a','France','a','dtm',metadata={'native_resolution_m':float('nan')}))
    def test_contradictory_metadata_not_override_coarse_label(self):
        with self.assertRaises(u.AcquisitionError):policy.dataset_spacing(u.Dataset('a','France','a','dtm',resolution='10 m',metadata={'native_resolution_m':1}))
    def test_all_existing_discovery_subject_to_policy(self):
        good=u.Dataset('good','England','one','dtm',resolution='1 m')
        coarse=u.Dataset('bad','England','coarse','dtm',resolution='10 m')
        with mock.patch.object(u,'england_discover',return_value=[good,coarse]):
            ds,notes=u.discover((-.15,53.74,-.14,53.75),'England','dtm',http=HTTP([]),printf=lambda s:None)
        self.assertEqual(ds,[good]);self.assertTrue(any('10 m' in n for n in notes))
    def test_japan10_removed_not_just_relabelled(self):
        self.assertTrue(all(r<=5 for _,_,r,_ in old.GSI_LAYERS))
        self.assertNotIn('dem_png',[name for name,*_ in old.GSI_LAYERS])
    def test_raw_points_not_mislabelled_dem_grid(self):
        self.assertIsNone(policy.validate_dataset(u.Dataset('a','Scotland','raw','pointcloud',resolution='N/A')))
    def test_real_coarse_raster_rejected_before_crop(self):
        src=self.root/'coarse.tif';src.write_bytes(float_tiff((500000,6600000,500100,6600100),10,3067))
        with self.assertRaises(u.AcquisitionError):u.crop_raster(src,self.root/'out.tif',BOXES['Finland'],printf=lambda s:None)
        self.assertFalse((self.root/'out.tif').exists())
    def test_rgb_and_eight_bit_images_rejected(self):
        for bands in (1,3):
            with MemoryFile(float_tiff((500000,6600000,500010,6600010),1,3067,dtype='uint8',bands=bands)) as mem,mem.open() as src:
                with self.assertRaises(u.AcquisitionError):policy.raster_spacing_m(src)
    def test_pixel_dimensions_both_axes_checked(self):
        with MemoryFile() as mem:
            with mem.open(driver='GTiff',width=10,height=10,count=1,dtype='float32',crs='EPSG:3067',transform=from_origin(500000,6600100,1,8)) as src:
                with self.assertRaises(u.AcquisitionError):policy.raster_spacing_m(src)
    def test_geographic_degrees_not_metres(self):
        with MemoryFile() as mem:
            with mem.open(driver='GTiff',width=10,height=10,count=1,dtype='float32',crs='EPSG:4326',transform=from_origin(24,60,.001,.001)) as src:
                with self.assertRaises(u.AcquisitionError):policy.raster_spacing_m(src)
    def test_feet_conversion_not_treated_as_metres(self):
        with MemoryFile() as mem:
            with mem.open(driver='GTiff',width=10,height=10,count=1,dtype='float32',crs='EPSG:2277',transform=from_origin(3000000,10000000,10,10)) as src:
                self.assertAlmostEqual(policy.raster_spacing_m(src)[0],3.048006096,places=6)
    def test_coarse_request_preserves_project_before_network(self):
        (self.root/'heightmap.npy').write_bytes(b'original')
        d=u.Dataset('x','Japan','bad','dtm',resolution='10 m',assets=[u.Asset('https://example.org/terrain.tif','terrain')])
        h=HTTP([])
        with self.assertRaises(u.AcquisitionError):u.download(d,BOXES['France'],self.root,http=h,printf=lambda s:None)
        self.assertFalse(h.calls);self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'original')
    def test_wrong_requested_extent_rejected(self):
        src=self.root/'wrong.tif';src.write_bytes(float_tiff((500000,6600000,500010,6600010),1,3067))
        with self.assertRaises(u.AcquisitionError):u.crop_raster(src,self.root/'out.tif',BOXES['Finland'],printf=lambda s:None,
            source_metadata={'requested_native_bounds':[500100,6600100,500110,6600110]})
    def test_float_requirement_checks_wms_not_just_extension(self):
        src=self.root/'integer.tif';src.write_bytes(float_tiff((500000,6600000,500010,6600010),1,3067,dtype='int16'))
        with self.assertRaises(u.AcquisitionError):u.crop_raster(src,self.root/'out.tif',BOXES['Finland'],printf=lambda s:None,source_metadata={'require_float':True})
    def test_new_helpers_frozen(self):
        import BUILD_TGC_2K25_BETA7 as b
        args=list(map(str,b.build_arguments('python',Path('.'),Path('stage'))))
        self.assertIn('exus_resolution_policy',args);self.assertIn('exus_additional_countries',args)
    def test_python311_grammar(self):
        for name in ('exus_additional_countries.py','exus_resolution_policy.py','uk_lidar_downloader.py','exus_lidar_sources.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8-sig'),feature_version=(3,11))

    def test_native_crs_check_rejects_genuinely_wrong_crs(self):
        src=self.root/'wrong_crs.tif';src.write_bytes(float_tiff((500000,6600000,500010,6600010),1,3067))
        with self.assertRaises(u.AcquisitionError):u.crop_raster(src,self.root/'out.tif',BOXES['Finland'],printf=lambda s:None,source_metadata={'source_epsg':2154})
    def test_auto_processing_ceiling(self):
        notices=[];self.assertEqual(policy.processing_scale(10,notices.append),5)
        self.assertIn('global setting is unchanged',notices[0])
        self.assertEqual(policy.processing_scale(1,notices.append),1)
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(u.AcquisitionError):policy.processing_scale(value,notices.append)
    def test_auto_processing_ceiling_is_wired_before_snapshot(self):
        g=ast.parse((Path(__file__).parent/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in g.body if isinstance(n,ast.FunctionDef) and n.name=='runUkLidarDem')
        calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='processing_scale']
        self.assertEqual(len(calls),1)
        snapshots=[n.lineno for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Value']
        self.assertLess(calls[0].lineno,min(snapshots))
    def test_nz_hyphenated_official_aws_host(self):
        url='https://nz-elevation.s3-ap-southeast-2.amazonaws.com/new-zealand/tile.tiff'
        self.assertEqual(new._https_s3(url,new.NZ_COLLECTION),url)
    def test_nz_missing_bounds_is_error_not_no_coverage(self):
        with self.assertRaises(u.AcquisitionError):new.parse_nz_item({'type':'Feature'},new.NZ_COLLECTION,BOXES['New Zealand'])
    def test_nz_coarse_item_is_not_upsampled(self):
        item={'type':'Feature','bbox':list(BOXES['New Zealand']),'properties':{'gsd':8},'assets':{'dem':{'href':'coarse.tif'}}}
        with self.assertRaises(u.AcquisitionError):new.parse_nz_item(item,new.NZ_COLLECTION,BOXES['New Zealand'])
    def test_nz_repeated_error_circuit_breaker(self):
        col={'type':'Collection','links':[{'rel':'item','href':str(i)+'.json'} for i in range(30)]}
        h=HTTP([Response(data=col)]+[u.requests.ConnectionError('fixture unavailable') for _ in range(30)])
        ds,notes=new.new_zealand(h,BOXES['New Zealand'],'dtm',None,lambda s:None)
        self.assertFalse(ds);self.assertIn('repeated errors',' '.join(notes))

# Real numerical GeoTIFFs traverse the installed download -> crop -> local UTM ->
# published manifest path. Only the network responses are fixtures.
def pipeline_test(country,epsg,res):
    def run(self):
        bbox=BOXES[country];box=u.projected_bounds(bbox,pyproj.CRS.from_epsg(epsg),lambda s:None)
        w,s,e,n,width,height=next(new.split_windows(box,res));raw=float_tiff((w,s,e,n),res,epsg)
        d=new._dataset(country,'fixture:'+country,country+' terrain fixture',res,
            [u.Asset('https://example.org/fixture.tif','fixture',None,'file',{'requested_native_bounds':[w,s,e,n],'source_epsg':epsg})],new.PROVIDERS[country])
        (self.root/'heightmap.npy').write_bytes(b'unchanged');(self.root/'mask.png').write_bytes(b'unchanged')
        result=u.download(d,bbox,self.root,http=HTTP([Response(raw=raw)]),printf=lambda s:None)
        self.assertEqual(len(result.files),1)
        with rasterio.open(result.files[0]) as src:
            self.assertLessEqual(max(src.res),5);self.assertNotEqual(src.crs.to_epsg(),3857)
            a=src.read(1,masked=True).compressed();self.assertTrue(a.size);np.testing.assert_allclose(a,123.25,atol=.001)
        manifest=json.loads(Path(result.manifest).read_text());self.assertEqual(manifest['resolution_policy'],policy.VERSION)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'unchanged');self.assertEqual((self.root/'mask.png').read_bytes(),b'unchanged')
        again=u.download(d,bbox,self.root,http=HTTP([]),printf=lambda s:None);self.assertEqual(again.files,result.files)
    return run
for name,epsg,res in [('Finland',3067,2),('France',2154,.5),('Germany',25832,1),('Netherlands',28992,.5),('New Zealand',2193,1),('Poland',2180,1)]:
    setattr(Tests,'test_pipeline_'+name.replace(' ','_').lower(),pipeline_test(name,epsg,res))

if __name__=='__main__':unittest.main(verbosity=2)
