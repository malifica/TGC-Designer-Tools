"""Headless data checks. Synthetic ROK4-style TIFFs, NOT live IGN downloads."""
from pathlib import Path
from urllib.parse import urlencode
from unittest import mock
import ast
import copy
import hashlib
import json
import struct
import tempfile
import unittest
import numpy as np
import rasterio
import uk_lidar_downloader as u
import exus_france_crs as fix
import exus_additional_countries as countries

USER_BBOX=(2.4647239,48.638023,2.4874426,48.6511569)
SMALL_BBOX=(2.475,48.644,2.47508,48.64408)
ENDPOINT='https://data.geopf.fr/wms-r/wms'
LAYER=next(iter(fix.LAYERS))


def metadata(bounds,res,layer=None):
    w,s,e,n=bounds
    params={'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetMap','LAYERS':layer or LAYER,
            'STYLES':'','FORMAT':'image/geotiff','CRS':'EPSG:2154',
            'BBOX':','.join(str(v) for v in bounds),'WIDTH':round((e-w)/res),'HEIGHT':round((n-s)/res)}
    return {'source_epsg':2154,'require_float':True,'requested_native_bounds':list(bounds),
            'ign_wms_request_url':ENDPOINT+'?'+urlencode(params)}


def custom_tiff(bounds,res,value=123.25,overrides=None,delete=(),citation='EPSG:2154|'):
    """Classic TIFF with explicit public ROK4 key layout, built without tifffile."""
    w,s,e,n=bounds;width=round((e-w)/res);height=round((n-s)/res)
    keys={1024:1,1025:1,1026:citation,2048:32767,2050:32767,2051:32767,2052:9001,
          2054:9102,2056:32767,3072:32767,3074:32767,3075:8,3076:9001,
          3078:49.,3079:44.,3084:3.,3085:46.5,3086:700000.,3087:6600000.}
    keys.update(overrides or {})
    for k in delete:keys.pop(k,None)
    dirs=[];doubles=[];ascii_text=''
    for key,v in sorted(keys.items()):
        if isinstance(v,str):
            dirs.extend((key,34737,len(v),len(ascii_text)));ascii_text+=v
        elif isinstance(v,float):
            dirs.extend((key,34736,1,len(doubles)));doubles.append(v)
        elif isinstance(v,(tuple,list)):
            dirs.extend((key,34736,len(v),len(doubles)));doubles.extend(v)
        else:dirs.extend((key,0,1,int(v)))
    directory=[1,1,0,len(keys)]+dirs
    arr=np.full((height,width),value,dtype='<f4') if np.isscalar(value) else np.asarray(value,dtype='<f4')
    assert arr.shape==(height,width)
    data=arr.tobytes()
    def field(tag,typ,vals,fmt):return tag,typ,len(vals),struct.pack('<'+str(len(vals))+fmt,*vals)
    fields=[field(256,4,[width],'I'),field(257,4,[height],'I'),field(258,3,[32],'H'),
        field(259,3,[1],'H'),field(262,3,[1],'H'),field(273,4,[0],'I'),field(277,3,[1],'H'),
        field(278,4,[height],'I'),field(279,4,[len(data)],'I'),field(339,3,[3],'H'),
        field(33550,12,[res,res,0.],'d'),field(33922,12,[0.,0.,0.,w,n,0.],'d'),
        field(34735,3,directory,'H'),field(34736,12,doubles,'d'),
        (34737,2,len(ascii_text)+1,ascii_text.encode()+b'\0'),(42113,2,7,b'-99999\0')]
    fields.sort();start=8+2+12*len(fields)+4;extras=bytearray();entries=[]
    for tag,typ,count,raw in fields:
        if len(raw)<=4:content=raw.ljust(4,b'\0')
        else:
            content=struct.pack('<I',start+len(extras));extras.extend(raw)
            if len(extras)%2:extras.append(0)
        entries.append((tag,typ,count,content))
    pixel_offset=start+len(extras)
    entries=[(tag,typ,count,struct.pack('<I',pixel_offset) if tag==273 else raw) for tag,typ,count,raw in entries]
    return b'II'+struct.pack('<HI',42,8)+struct.pack('<H',len(fields))+b''.join(struct.pack('<HHI4s',*v) for v in entries)+b'\0'*4+extras+data


class Response:
    def __init__(self,raw):self.raw=raw;self.headers={'Content-Length':str(len(raw))};self.status_code=200
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):pass
    def iter_content(self,n):
        for off in range(0,len(self.raw),n):yield self.raw[off:off+n]
class HTTP:
    def __init__(self,mapping):self.mapping=mapping;self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append(url)
        value=self.mapping[url]
        return Response(value() if callable(value) else value)
    def close(self):pass


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.log=[]
        box=u.projected_bounds(SMALL_BBOX,'EPSG:2154',lambda x:None)
        self.bounds=tuple(next(countries.split_windows(box,.5))[:4]);self.meta=metadata(self.bounds,.5)
    def tearDown(self):self.tmp.cleanup()
    def source(self,**kw):
        p=self.root/'source.tif';p.write_bytes(custom_tiff(self.bounds,.5,**kw));return p
    def crop(self,path=None,meta=None):
        return u.crop_raster(path or self.source(),self.root/'crop.tif',SMALL_BBOX,
            printf=self.log.append,source_metadata=self.meta if meta is None else meta)
    def test_reproduces_original_strict_crs_rejection(self):
        with rasterio.open(self.source()) as src:
            self.assertNotEqual(src.crs,rasterio.crs.CRS.from_epsg(2154))
            self.assertIn('Lambert',src.crs.to_wkt())
    def test_custom_datum_keys_restored(self):
        path,info=self.crop()
        self.assertTrue(info['metadata_repaired']);self.assertIn('original_crs_wkt',info)
        with rasterio.open(path) as src:self.assertEqual(src.crs.to_epsg(),2154)
    def test_source_file_is_never_edited(self):
        src=self.source();before=src.read_bytes();self.crop(src);self.assertEqual(before,src.read_bytes())
    def test_crop_preserves_positions_and_gradient_heights(self):
        w,s,e,n=self.bounds;cols=round((e-w)/.5);rows=round((n-s)/.5)
        values=np.arange(rows*cols,dtype='float32').reshape(rows,cols)/10+50
        src=self.source(value=values);path,info=self.crop(src)
        with rasterio.open(src) as a,rasterio.open(path) as b:
            np.testing.assert_array_equal(b.read(1),a.read(1));self.assertEqual(a.transform,b.transform)
            self.assertEqual(a.bounds,b.bounds);self.assertIn('TGC_EXUS_ORIGINAL_CRS',b.tags())
    def test_explicit_grs80_is_accepted(self):
        self.crop(self.source(overrides={2057:6378137.,2059:298.257222101}))
    def test_wrong_known_crs_is_not_overridden(self):
        self.assert_rejected(overrides={3072:3857})
    def test_wrong_geographic_datum_is_not_overridden(self):
        self.assert_rejected(overrides={2048:4326,2050:6326})
    def test_explicit_different_ellipsoid_is_rejected(self):
        self.assert_rejected(overrides={2059:298.257223563})
    def test_nonzero_datum_shift_is_rejected(self):self.assert_rejected(overrides={2062:[1.,2.,3.]})
    def test_wrong_citation_is_rejected(self):self.assert_rejected(citation='EPSG:3857|')
    def test_missing_citation_is_rejected(self):self.assert_rejected(delete=(1026,))
    def test_all_projection_parameters_are_checked(self):
        for k in (3078,3079,3084,3085,3086,3087):
            with self.subTest(key=k):self.assert_rejected(overrides={k:1.0})
    def test_wrong_units_are_rejected(self):self.assert_rejected(overrides={3076:9002})
    def test_wrong_projection_method_is_rejected(self):self.assert_rejected(overrides={3075:7})
    def test_unknown_extra_geokeys_are_not_ignored(self):self.assert_rejected(overrides={3092:1.0})
    def assert_rejected(self,**kwargs):
        with self.assertRaises(u.AcquisitionError):self.crop(self.source(**kwargs))
        self.assertFalse((self.root/'crop.tif').exists())
    def test_native_existing_epsg_file_still_works(self):
        path=self.source();a=None
        with rasterio.open(path) as src:profile=src.profile;a=src.read()
        path.unlink();profile['crs']='EPSG:2154'
        with rasterio.open(path,'w',**profile) as dst:dst.write(a)
        p,info=self.crop(path);self.assertNotIn('metadata_repaired',info)
    def test_custom_metadata_not_accepted_for_other_provider(self):
        m=copy.deepcopy(self.meta);m['ign_wms_request_url']=m['ign_wms_request_url'].replace('data.geopf.fr','example.org')
        with self.assertRaises(u.AcquisitionError):self.crop(meta=m)
    def test_no_request_context_no_override(self):
        with self.assertRaises(u.AcquisitionError):self.crop(meta={'source_epsg':2154})
    def test_fake_host_suffix_not_allowed(self):
        m=copy.deepcopy(self.meta);m['ign_wms_request_url']=m['ign_wms_request_url'].replace('data.geopf.fr','data.geopf.fr.example.org')
        with self.assertRaises(u.AcquisitionError):self.crop(meta=m)
    def test_different_product_not_allowed(self):
        m=copy.deepcopy(self.meta);m['ign_wms_request_url']=m['ign_wms_request_url'].replace('MNT_ELEVATION','MNS_ELEVATION')
        with self.assertRaises(u.AcquisitionError):self.crop(meta=m)
    def test_wrong_requested_dimensions_rejected(self):
        m=copy.deepcopy(self.meta);m['ign_wms_request_url']+='&WIDTH=1'
        with self.assertRaises(u.AcquisitionError):self.crop(meta=m)
    def test_extent_mismatch_still_rejected(self):
        m=copy.deepcopy(self.meta);m['requested_native_bounds'][0]+=3
        with self.assertRaises(u.AcquisitionError):self.crop(meta=m)
    def test_shifted_response_still_rejected(self):
        p=self.root/'source.tif';b=list(self.bounds);b[0]+=20;b[2]+=20;p.write_bytes(custom_tiff(b,.5))
        with self.assertRaises(u.AcquisitionError):self.crop(p)
    def test_ten_metre_response_rejected(self):
        w,s,e,n=self.bounds;b=(w,s,w+20,s+20);p=self.root/'ten.tif';p.write_bytes(custom_tiff(b,10))
        with self.assertRaises(u.AcquisitionError):self.crop(p)
    def test_small_metadata_reader_bounds(self):
        p=self.root/'broken.tif';p.write_bytes(b'II'+struct.pack('<HI',42,2**31))
        with self.assertRaises(u.AcquisitionError):fix._geotiff_keys(p)
    def test_parser_fix_remains_installed(self):
        xml=b'<WMS_Capabilities><Capability><Exception><Format>XML</Format></Exception></Capability></WMS_Capabilities>'
        caps=countries.xml_get(HTTP({'https://example.org/caps':xml}),'https://example.org/caps',{})
        self.assertEqual(caps.tag,'WMS_Capabilities')
    def test_diagnostics_outside_disposable_staging(self):
        folder=self.root/'ExUS_Data'/'.partial_fixture'/'unpacked';folder.mkdir(parents=True)
        p=folder/'bad.tif';p.write_bytes(custom_tiff(self.bounds,.5,citation='wrong|'))
        with self.assertRaises(u.AcquisitionError):self.crop(p)
        reports=list((folder.parent.parent/'Diagnostics').glob('IGN_CRS_*.json'))
        self.assertEqual(len(reports),1);d=json.loads(reports[0].read_text())
        self.assertIn('actual_crs_wkt',d);self.assertEqual(d['expected_epsg'],2154)
    def test_no_window_or_gui_test_gates_in_builder(self):
        t=(Path(__file__).parent/'BUILD_TGC_2K25_BETA7.py').read_text(encoding='utf-8-sig')
        tree=ast.parse(t)
        const=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        self.assertNotIn('--gui',const)
        for term in ('VERIFY_BETA7_LARGE_WINDOWS.py','VERIFY_BETA7_UK_UI_LAYOUT_FIX.py',
                     'VERIFY_BETA7_UK_UI_FIX.py','VERIFY_BETA7_UK_REPORT_PANE.py','VERIFY_BETA7_UK_REPORT_FONT_FIX.py'):
            self.assertNotIn(term,const)
        self.assertIn('--verify-lidar-trees',const);self.assertIn('exus_france_crs',const)
    def test_python311_syntax(self):
        for name in ('exus_france_crs.py','uk_lidar_downloader.py','BUILD_TGC_2K25_BETA7.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8-sig'),feature_version=(3,11))
    def test_four_tiles_through_download_crop_utm_manifest_and_cache(self):
        from urllib.parse import urlparse, parse_qs
        xml=b'<WMS_Capabilities><Capability><Request><GetMap><Format>image/geotiff</Format></GetMap></Request><Exception><Format>XML</Format></Exception><Layer><Layer><Name>IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93</Name></Layer></Layer></Capability></WMS_Capabilities>'
        class Caps(HTTP):
            def get(self,*a,**k):return Response(xml)
        choices,_=countries.france(Caps({}),USER_BBOX,'dtm',None,self.log.append);d=choices[0]
        self.assertEqual(len(d.assets),4)
        mapping={a.url:(lambda bounds=a.metadata['requested_native_bounds']:custom_tiff(bounds,.5)) for a in d.assets}
        (self.root/'heightmap.npy').write_bytes(b'existing-heightmap');(self.root/'mask.png').write_bytes(b'existing-mask')
        class ProbeHTTP(HTTP):
            def get(self,url,**kwargs):
                if url not in self.mapping:
                    q=parse_qs(urlparse(url).query)
                    box=tuple(map(float,q['BBOX'][0].split(',')))
                    self.calls.append(url)
                    return Response(custom_tiff(box,.5))
                return super().get(url,**kwargs)
        http=ProbeHTTP(mapping);r=u.download(d,USER_BBOX,self.root,http=http,printf=self.log.append)
        self.assertEqual(len(r.files),4);self.assertEqual(len(http.calls),5)  # one small native-grid check + four terrain tiles
        for p in r.files:
            with rasterio.open(p) as src:
                self.assertEqual(src.crs.to_epsg(),32631);self.assertLessEqual(max(src.res),5.)
                vals=src.read(1,masked=True).compressed();self.assertGreater(len(vals),0)
                np.testing.assert_allclose(vals,123.25,atol=.001)
        saved=json.loads(Path(r.manifest).read_text());self.assertTrue(saved['complete'])
        self.assertTrue(all(a['metadata']['metadata_repaired'] for a in saved['outputs']))
        again=u.download(d,USER_BBOX,self.root,http=HTTP({}),printf=self.log.append)
        self.assertEqual(r.files,again.files)
        self.assertEqual((self.root/'heightmap.npy').read_bytes(),b'existing-heightmap')
        self.assertEqual((self.root/'mask.png').read_bytes(),b'existing-mask')
        self.assertFalse(list((self.root/'ExUS_Data').glob('.partial_*')))
    def test_five_metre_product_pipeline(self):
        box=u.projected_bounds(SMALL_BBOX,'EPSG:2154',lambda x:None);b=tuple(next(countries.split_windows(box,5))[:4])
        p=self.root/'rge.tif';p.write_bytes(custom_tiff(b,5))
        m=metadata(b,5,'ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES')
        out,info=u.crop_raster(p,self.root/'out.tif',SMALL_BBOX,printf=self.log.append,source_metadata=m)
        self.assertTrue(out.exists());self.assertTrue(info['metadata_repaired'])

if __name__=='__main__':unittest.main(verbosity=2)
