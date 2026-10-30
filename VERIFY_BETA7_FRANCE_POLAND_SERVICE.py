"""Headless regression checks: real GeoTIFF processing, simulated HTTP only.
The two course extents and IGN parsed WKT are taken from the user's supplied
files. No successful live-provider connection or Windows GUI test is implied.
"""
from pathlib import Path
from urllib.parse import parse_qs,urlparse,urlencode
from unittest import mock
import ast
import copy
import json
import struct
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
import uk_lidar_downloader as u
import exus_additional_countries as c
import exus_france_crs as f
import exus_service_raster as svc
from VERIFY_BETA7_FRANCE_CRS import custom_tiff,metadata,Response,USER_BBOX

POLAND_BBOX=(20.819559887101928,52.37964802514927,20.851469512898074,52.39143087485073)
PL_NATIVE=(623778.,503080.,625578.,504447.)
FR_NATIVE=(660560.,6837660.5,661460.,6838560.5)
DIAGNOSTIC_WKT='PROJCS["EPSG:2154",GEOGCS["unknown",DATUM["unnamed",SPHEROID["unretrievable - using WGS84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],PROJECTION["Lambert_Conformal_Conic_2SP"],PARAMETER["latitude_of_origin",46.5],PARAMETER["central_meridian",3],PARAMETER["standard_parallel_1",49],PARAMETER["standard_parallel_2",44],PARAMETER["false_easting",700000],PARAMETER["false_northing",6600000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'


def extended_tiff(bounds,res,value=123.25):
    # Legal extra SHORT-value space after the declared GeoKey entries.
    # Existing doubles are unchanged; the extra, unused shorts are never keys.
    raw=bytearray(custom_tiff(bounds,res,value))
    for i in range(struct.unpack_from('<H',raw,8)[0]):
        entry=10+12*i
        if struct.unpack_from('<H',raw,entry)[0]==34735:
            n=struct.unpack_from('<I',raw,entry+4)[0]
            struct.pack_into('<I',raw,entry+4,n+4)
            break
    return bytes(raw)


def plain_tiff(bounds,res,epsg=2180,dtype='float32',value=101.5):
    w,s,e,n=bounds;cols=round((e-w)/res);rows=round((n-s)/res)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=cols,height=rows,count=1,dtype=dtype,
                      crs='EPSG:'+str(epsg),transform=from_origin(w,n,res,res)) as out:
            out.write(np.full((1,rows,cols),value,dtype=dtype))
        return mem.read()


def poland_dataset(bbox=POLAND_BBOX):
    box=u.projected_bounds(bbox,'EPSG:2180',lambda s:None);assets=[]
    for i,(*bounds,w,h) in enumerate(c.split_windows(box,1.)):
        params={'SERVICE':'WCS','VERSION':'1.0.0','REQUEST':'GetCoverage',
                'COVERAGE':'DTM_PL','FORMAT':'GEOTIFF','CRS':'EPSG:2180',
                'RESPONSE_CRS':'EPSG:2180','BBOX':','.join(map(str,bounds)),
                'RESX':'1.0','RESY':'1.0'}
        url=c.POLAND+'?'+urlencode(params)
        assets.append(u.Asset(url,'Poland_dtm_%d.tif'%(i+1),metadata={
            'source_epsg':2180,'requested_native_bounds':bounds,'native_wcs_request_url':url,
            'wcs_bbox_order':'xy','native_spacing_m':1.,'expected_width':w,'expected_height':h}))
    return c._dataset('Poland','fixture:poland','NMT GRID1 fixture',1.,assets,c.PROVIDERS['Poland'])


def france_dataset(bbox=USER_BBOX):
    assets=[];box=u.projected_bounds(bbox,'EPSG:2154',lambda s:None)
    for i,(*bounds,w,h) in enumerate(c.split_windows(box,.5)):
        m=metadata(bounds,.5);assets.append(u.Asset(m['ign_wms_request_url'],'IGN_terrain_%d.tif'%(i+1),metadata=m))
    return c._dataset('France','fixture:france','IGN MNT fixture',.5,assets,c.PROVIDERS['France'])


class ServiceHTTP:
    """Independent fixture server interprets BBOX as x/y, or explicitly y/x."""
    def __init__(self,poland_order='xy',fail_second=False,shift=0):
        self.calls=[];self.poland_order=poland_order;self.fail_second=fail_second;self.full=0;self.shift=shift
    def get(self,url,**kw):
        q=parse_qs(urlparse(url).query);self.calls.append(url)
        b=list(map(float,q['BBOX'][0].split(',')))
        fr=q['SERVICE'][0]=='WMS'
        if not fr and self.poland_order=='yx':b=[b[1],b[0],b[3],b[2]]
        res=.5 if fr else float(q['RESX'][0])
        cols=round((b[2]-b[0])/res);rows=round((b[3]-b[1])/res)
        if cols*rows>32*24:
            self.full+=1
            if self.fail_second and self.full==2:
                self.fail_second=False
                raise u.requests.ConnectionError('Simulated transfer interruption on second terrain tile')
        if self.shift:b=[b[0]+self.shift,b[1],b[2]+self.shift,b[3]]
        return Response(extended_tiff(b,res) if fr else plain_tiff(b,res))
    def close(self):pass


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.log=[]
    def tearDown(self):self.tmp.cleanup()
    def test_exact_uploaded_parsed_header_is_recognized(self):
        self.assertTrue(f._parsed_lambert93(rasterio.crs.CRS.from_wkt(DIAGNOSTIC_WKT)))
    def test_extra_directory_values_reproduce_old_rejection_and_now_parse(self):
        p=self.root/'extra.tif';p.write_bytes(extended_tiff(FR_NATIVE,.5))
        raw=p.read_bytes()
        for i in range(struct.unpack_from('<H',raw,8)[0]):
            tag,typ,n,offset=struct.unpack_from('<HHII',raw,10+12*i)
            if tag==34735:
                declared=struct.unpack_from('<4H',raw,offset)[3]
                self.assertNotEqual(n,4+4*declared) # old rejection
                break
        keys=f._geotiff_keys(p);self.assertTrue(f._documented_lambert93(keys))
        with rasterio.open(p) as src:
            self.assertTrue(f._parsed_lambert93(src.crs))
            eff,audit=f.resolve_raster_crs(src,metadata(FR_NATIVE,.5),self.log.append)
            self.assertEqual(eff.to_epsg(),2154);self.assertTrue(audit['metadata_repaired'])
    def test_extra_keys_do_not_become_fake_coordinate_entries(self):
        p=self.root/'extra.tif';p.write_bytes(extended_tiff((660560.,6837660.5,660564.,6837664.5),.5))
        self.assertEqual(len(f._geotiff_keys(p)),19)
    def test_gdal_signature_fallback_when_raw_reader_cannot_read(self):
        b=(660560.,6837660.5,660564.,6837664.5);p=self.root/'extra.tif';p.write_bytes(custom_tiff(b,.5))
        with rasterio.open(p) as src,mock.patch.object(f,'_geotiff_keys',side_effect=u.AcquisitionError('Missing or invalid GeoTIFF coordinate-key directory.')):
            eff,audit=f.resolve_raster_crs(src,metadata(b,.5),self.log.append)
            self.assertEqual(eff.to_epsg(),2154);self.assertTrue(audit['parsed_crs_contract_checked'])
    def test_conflicting_raw_keys_cannot_fall_back_to_parsed_header(self):
        b=(660560.,6837660.5,660564.,6837664.5);p=self.root/'extra.tif';p.write_bytes(custom_tiff(b,.5))
        with rasterio.open(p) as src,mock.patch.object(f,'_geotiff_keys',return_value={1026:'EPSG:3857'}):
            with self.assertRaises(u.AcquisitionError):f.resolve_raster_crs(src,metadata(b,.5),self.log.append)
    def test_parsed_header_wrong_origin_rejected(self):
        crs=rasterio.crs.CRS.from_wkt(DIAGNOSTIC_WKT.replace('6600000','6600001'))
        self.assertFalse(f._parsed_lambert93(crs))
    def test_parsed_header_known_other_datum_rejected(self):
        self.assertFalse(f._parsed_lambert93(rasterio.crs.CRS.from_wkt(DIAGNOSTIC_WKT.replace('DATUM["unnamed"','DATUM["WGS_1984"'))))
    def test_parsed_header_other_citation_rejected(self):
        self.assertFalse(f._parsed_lambert93(rasterio.crs.CRS.from_wkt(DIAGNOSTIC_WKT.replace('EPSG:2154','EPSG:3857'))))
    def test_france_wrong_grid_still_rejected(self):
        ds=france_dataset();http=ServiceHTTP(shift=25)
        with self.assertRaises(u.AcquisitionError):u.download(ds,USER_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(http.calls),1);self.assertEqual(http.full,0)
    def test_france_four_real_numeric_tiles_and_preflight(self):
        ds=france_dataset();before=copy.deepcopy(ds);http=ServiceHTTP()
        result=u.download(ds,USER_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(result.files),4);self.assertEqual(len(http.calls),5);self.assertEqual(ds,before)
        for p in result.files:
            with rasterio.open(p) as src:
                self.assertEqual(src.crs.to_epsg(),32631);self.assertEqual(src.res,(.5,.5))
                vals=src.read(1,masked=True).compressed();self.assertTrue(len(vals));np.testing.assert_allclose(vals,123.25,atol=.001)
    def test_wcs1_description_without_labels_uses_xy(self):
        desc=ET.fromstring('<CoverageOffering><Envelope srsName="EPSG:2180"><pos>100000 200000</pos><pos>800000 900000</pos></Envelope></CoverageOffering>')
        _,bounds,_,ix,iy,_=c.describe_wcs(desc,2180,1.,'1.0.0')
        self.assertEqual(bounds,(100000.,200000.,800000.,900000.));self.assertEqual((ix,iy),(0,1))
    def test_wcs2_still_respects_declared_axes(self):
        desc=ET.fromstring('<CoverageDescriptions><Envelope srsName="EPSG:2180" axisLabels="N E"><lowerCorner>200000 100000</lowerCorner><upperCorner>900000 800000</upperCorner></Envelope></CoverageDescriptions>')
        _,bounds,_,ix,iy,_=c.describe_wcs(desc,2180,1.,'2.0.1')
        self.assertEqual(bounds,(100000.,200000.,800000.,900000.));self.assertEqual((ix,iy),(1,0))
    def test_user_poland_first_tile_has_9point8_mb_float_payload(self):
        ds=poland_dataset();b=ds.assets[0].metadata['requested_native_bounds']
        self.assertEqual(tuple(b),PL_NATIVE)
        self.assertEqual(ds.assets[0].metadata['expected_width']*ds.assets[0].metadata['expected_height']*4,9842400)
    def test_poland_old_swapped_request_reproduces_extent_error(self):
        ds=poland_dataset();a=ds.assets[0];b=a.metadata['requested_native_bounds'];swapped=[b[1],b[0],b[3],b[2]]
        p=self.root/'old.tif';p.write_bytes(plain_tiff(swapped,1.))
        with rasterio.open(p) as src,self.assertRaisesRegex(u.AcquisitionError,'extent mismatch'):
            svc.validate_extent(src,a.metadata,self.log.append)
    def test_poland_two_tiles_pipeline_keeps_original_coordinates(self):
        ds=poland_dataset();before=copy.deepcopy(ds);http=ServiceHTTP()
        result=u.download(ds,POLAND_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(result.files),2);self.assertEqual(len(http.calls),3);self.assertEqual(ds,before)
        for p in result.files:
            with rasterio.open(p) as src:
                self.assertEqual(src.crs.to_epsg(),32634);self.assertEqual(src.res,(1.,1.))
                np.testing.assert_allclose(src.read(1,masked=True).compressed(),101.5,atol=.001)
    def test_poland_nonstandard_server_order_negotiated_with_tiny_files(self):
        ds=poland_dataset();http=ServiceHTTP(poland_order='yx');before=copy.deepcopy(ds)
        result=u.download(ds,POLAND_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(result.files),2);self.assertEqual(len(http.calls),4);self.assertEqual(ds,before)
        self.assertTrue(any('alternate request order' in s for s in self.log))
        m=json.loads(Path(result.manifest).read_text())
        self.assertTrue(all(a['metadata']['wcs_bbox_order']=='yx' for a in m['dataset']['assets']))
    def test_wrong_extent_fails_before_full_poland_downloads(self):
        http=ServiceHTTP(shift=500)
        with self.assertRaises(u.AcquisitionError):u.download(poland_dataset(),POLAND_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(http.calls),2);self.assertEqual(http.full,0)
        self.assertTrue(list((self.root/'ExUS_Data'/'Diagnostics').glob('SERVICE_GRID*.json')))
    def test_tiny_checks_do_not_claim_data_coverage(self):
        a=poland_dataset().assets[0];b=a.metadata['requested_native_bounds']
        probe=svc._alter(a,[b[0],b[1],b[0]+32,b[1]+24],32,24,probe=True)
        p=self.root/'nodata.tif';p.write_bytes(plain_tiff(probe.metadata['requested_native_bounds'],1.,value=np.nan))
        svc._validate_probe(p,probe.metadata,self.log.append)
    def test_transport_timeout_does_not_trigger_axis_retry(self):
        http=mock.Mock();http.get.side_effect=u.requests.ConnectTimeout('fixture')
        with self.assertRaises(u.requests.ConnectTimeout):u.download(poland_dataset(),POLAND_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(http.get.call_count,1)
    def test_invalid_mime_not_cached(self):
        r=Response(b'<html>Failure</html>');r.headers={'Content-Type':'text/html'}
        http=mock.Mock();http.get.return_value=r
        with self.assertRaises(u.AcquisitionError):u.download(poland_dataset(),POLAND_BBOX,self.root,http=http,printf=self.log.append)
        self.assertFalse(list((self.root/'ExUS_Data'/'SourceCache').glob('*.tif')))
    def test_other_countries_repeated_subset_parameters_are_untouched(self):
        a=u.Asset('https://example.org/wcs?SUBSET=E(1,2)&SUBSET=N(3,4)','a.tif')
        self.assertIsNone(svc.service_kind(a))
        ds=u.Dataset('other','Finland','unchanged','dtm',assets=[a])
        self.assertEqual(svc.prepare_services(ds,self.root,self.root,object()),ds)
    def test_official_host_required_for_cache_route(self):
        a=france_dataset().assets[0];a.url=a.url.replace('data.geopf.fr','data.geopf.fr.example.org');a.metadata['ign_wms_request_url']=a.url
        self.assertIsNone(svc.service_kind(a))
    def test_complete_cache_reuses_no_network(self):
        ds=poland_dataset();http=ServiceHTTP();r=u.download(ds,POLAND_BBOX,self.root,http=http,printf=self.log.append)
        no_network=mock.Mock();no_network.get.side_effect=AssertionError('No new HTTP permitted')
        again=u.download(ds,POLAND_BBOX,self.root,http=no_network,printf=self.log.append)
        self.assertEqual(r.files,again.files);no_network.get.assert_not_called()
    def test_failed_later_tile_keeps_complete_source_downloads(self):
        ds=poland_dataset();http=ServiceHTTP(fail_second=True)
        with self.assertRaises(u.requests.ConnectionError):u.download(ds,POLAND_BBOX,self.root,http=http,printf=self.log.append)
        first_full=[v for v in http.calls if 'Poland' not in v][1]
        self.assertFalse(list((self.root/'ExUS_Data').glob('.partial_*')))
        before=len(http.calls)
        result=u.download(ds,POLAND_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(result.files),2);self.assertEqual(len(http.calls)-before,1)
        self.assertTrue(any('reusing complete source' in s for s in self.log))
    def test_corrupt_source_cache_is_not_used(self):
        ds=poland_dataset();a=ds.assets[0];http=ServiceHTTP()
        svc.cached_transfer(a,self.root/'one.bin',self.root,http,printf=self.log.append)
        raw=next((self.root/'SourceCache').glob('*.tif'));raw.write_bytes(b'bad')
        svc.cached_transfer(a,self.root/'two.bin',self.root,http,printf=self.log.append)
        self.assertEqual(len(http.calls),2);self.assertEqual((self.root/'one.bin').read_bytes(),(self.root/'two.bin').read_bytes())
    def test_cancellation_does_not_publish_partial_data(self):
        event=threading.Event();event.set();http=ServiceHTTP()
        with self.assertRaises(u.Cancelled):u.download(poland_dataset(),POLAND_BBOX,self.root,http=http,cancel=event,printf=self.log.append)
        self.assertEqual(http.calls,[]);self.assertFalse(list((self.root/'ExUS_Data').glob('.partial_*')))
    def test_current_project_files_are_preserved(self):
        (self.root/'heightmap.npy').write_bytes(b'original-terrain');(self.root/'mask.png').write_bytes(b'original-mask')
        u.download(poland_dataset(),POLAND_BBOX,self.root,http=ServiceHTTP(),printf=self.log.append)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'original-terrain')
        self.assertEqual((self.root/'mask.png').read_bytes(),b'original-mask')
    def test_10m_raw_raster_still_rejected(self):
        p=self.root/'coarse.tif';b=(623780,503080,624100,503320);p.write_bytes(plain_tiff(b,10.))
        with self.assertRaises(u.AcquisitionError):svc._validate_probe(p,{},self.log.append)
    def test_transfer_logs_response_wait_speed_and_elapsed(self):
        a=poland_dataset().assets[0]
        svc.cached_transfer(a,self.root/'raw.bin',self.root,ServiceHTTP(),printf=self.log.append)
        self.assertTrue(any('response received' in s for s in self.log))
        self.assertTrue(any('MB/s' in s and 'elapsed' in s for s in self.log))
    def test_python311_syntax(self):
        for name in ('exus_france_crs.py','exus_service_raster.py','exus_additional_countries.py','uk_lidar_downloader.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8-sig'),feature_version=(3,11))


if __name__=='__main__':unittest.main(verbosity=2)
