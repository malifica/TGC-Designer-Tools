"""Offline OGC response regressions; real raster I/O, no live-provider claim.

The capabilities fixture includes the standard WMS Exception/Format declaration
missing from the old France fixture. No network access or project changes occur.
"""
from pathlib import Path
import io
import json
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
import uk_lidar_downloader as u
import exus_additional_countries as country
import exus_resolution_policy as policy

BBOX=(2.3500,48.8500,2.3502,48.8502)
LIDAR='IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93'
RGE='ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES'
# Explicitly synthetic, namespace-correct provider response; not a live download.
CAPS=('''<?xml version="1.0" encoding="UTF-8"?>
<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
  <Service><Name>WMS</Name><Title>WMS API Géoplateforme - Diffusion d'images</Title>
    <Abstract>WMS-Raster</Abstract></Service>
  <Capability><Request>
    <GetCapabilities><Format>text/xml</Format></GetCapabilities>
    <GetMap><Format>image/jpeg</Format><Format>image/png</Format>
      <Format>image/tiff</Format><Format>image/geotiff</Format>
      <Format>image/x-bil;bits=32</Format></GetMap>
  </Request>
  <Exception><Format>XML</Format></Exception>
  <Layer><Title>WMS layers</Title><CRS>EPSG:2154</CRS>
    <Layer><Name>'''+LIDAR+'''</Name><Title>LiDAR HD MNT</Title></Layer>
    <Layer><Name>'''+RGE+'''</Name><Title>RGE ALTI</Title></Layer>
    <Layer><Name>IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93</Name></Layer>
  </Layer></Capability>
</WMS_Capabilities>''').encode('utf-8')

class Response:
    def __init__(self,raw,status=200,on_block=None):
        self.content=raw;self.status_code=status;self.headers={};self.on_block=on_block;self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def raise_for_status(self):
        if self.status_code>=400:raise u.requests.HTTPError('HTTP '+str(self.status_code))
    def iter_content(self,size):
        for i in range(0,len(self.content),size):
            if self.on_block:self.on_block()
            yield self.content[i:i+size]

class HTTP:
    def __init__(self,*responses):self.responses=list(responses);self.calls=[]
    def get(self,url,**kwargs):return self.request('GET',url,**kwargs)
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        if not self.responses:raise AssertionError('Unplanned HTTP call in offline test')
        result=self.responses.pop(0)
        if isinstance(result,Exception):raise result
        return result
    def close(self):pass


def parse(raw,**kwargs):
    return country.xml_get(HTTP(Response(raw)),'https://example.invalid/wms',{},**kwargs)

class Tests(unittest.TestCase):
    def test_wms13_format_declaration_is_not_service_failure(self):
        root=parse(CAPS)
        self.assertEqual(country._local(root.tag),'WMS_Capabilities')
        self.assertEqual(root.findtext('.//{*}Exception/{*}Format'),'XML')
    def test_wms111_format_declarations_are_not_errors(self):
        root=parse(b'<WMT_MS_Capabilities><Capability><Exception><Format>application/vnd.ogc.se_xml</Format><Format>INIMAGE</Format></Exception></Capability></WMT_MS_Capabilities>')
        self.assertEqual(country._local(root.tag),'WMT_MS_Capabilities')
    def test_capabilities_xml_preserved(self):
        self.assertEqual(ET.tostring(parse(CAPS)),ET.tostring(ET.fromstring(CAPS)))
    def test_word_exception_in_description_is_not_error(self):
        self.assertEqual(parse(b'<Capabilities><Title>Exception information</Title><ExceptionFormats>XML</ExceptionFormats></Capabilities>').tag,'Capabilities')
    def test_prefixed_capability_exception(self):
        root=parse(b'<w:WMS_Capabilities xmlns:w="http://www.opengis.net/wms"><w:Capability><w:Exception><w:Format>XML</w:Format></w:Exception></w:Capability></w:WMS_Capabilities>')
        self.assertEqual(country._local(root.tag),'WMS_Capabilities')
    def test_true_wms_error_keeps_code_and_message(self):
        with self.assertRaisesRegex(u.AcquisitionError,'LayerNotDefined.*Unknown terrain layer'):
            parse(b'<ServiceExceptionReport version="1.3.0" xmlns="http://www.opengis.net/ogc"><ServiceException code="LayerNotDefined">Unknown terrain layer</ServiceException></ServiceExceptionReport>')
    def test_true_ows_report_namespaces(self):
        for ns in ('http://www.opengis.net/ows','http://www.opengis.net/ows/1.1','http://www.opengis.net/ows/2.0'):
            with self.subTest(namespace=ns),self.assertRaisesRegex(u.AcquisitionError,'InvalidParameterValue / CoverageId: Bad coverage'):
                parse(('<ows:ExceptionReport xmlns:ows="'+ns+'"><ows:Exception exceptionCode="InvalidParameterValue" locator="CoverageId"><ows:ExceptionText>Bad coverage</ows:ExceptionText></ows:Exception></ows:ExceptionReport>').encode())
    def test_multiple_real_errors_retained(self):
        with self.assertRaises(u.AcquisitionError) as caught:
            parse(b'<ServiceExceptionReport><ServiceException code="A">First failure</ServiceException><ServiceException code="B">Second failure</ServiceException></ServiceExceptionReport>')
        self.assertIn('A: First failure',str(caught.exception));self.assertIn('B: Second failure',str(caught.exception))
    def test_standalone_error_response(self):
        for raw in (b'<ServiceException code="X">Unavailable</ServiceException>',b'<Exception exceptionCode="X"><ExceptionText>Unavailable</ExceptionText></Exception>',b'<ExceptionText>Unavailable</ExceptionText>'):
            with self.subTest(raw=raw),self.assertRaisesRegex(u.AcquisitionError,'Unavailable'):parse(raw)
    def test_empty_error_report_still_fails(self):
        with self.assertRaisesRegex(u.AcquisitionError,'Empty ExceptionReport'):parse(b'<ExceptionReport/>')
    def test_wrapped_real_report_still_fails(self):
        with self.assertRaisesRegex(u.AcquisitionError,'Unavailable'):
            parse(b'<Response><ExceptionReport><Exception><ExceptionText>Unavailable</ExceptionText></Exception></ExceptionReport></Response>')
    def test_error_message_bounded(self):
        with self.assertRaises(u.AcquisitionError) as caught:parse(b'<ExceptionReport><Exception>'+b'x'*5000+b'</Exception></ExceptionReport>')
        self.assertLessEqual(len(str(caught.exception)),len('Provider service error: ')+800)
    def test_http_failure_not_suppressed(self):
        with self.assertRaises(u.requests.HTTPError):country.xml_get(HTTP(Response(CAPS,503)),country.FRANCE,{})
    def test_network_failure_not_no_coverage(self):
        with self.assertRaises(u.requests.ConnectionError):country.xml_get(HTTP(u.requests.ConnectionError('offline fixture')),country.FRANCE,{})
    def test_unsafe_xml_guard_kept(self):
        for raw in (b'<!DOCTYPE x><Capabilities/>',b'<!ENTITY x "anything"><Capabilities/>'):
            with self.subTest(raw=raw),self.assertRaisesRegex(u.AcquisitionError,'Unsafe'):parse(raw)
    def test_malformed_xml_not_accepted(self):
        with self.assertRaises(ET.ParseError):parse(b'<WMS_Capabilities><Capability>')
    def test_size_limit_and_response_close(self):
        response=Response(CAPS)
        with self.assertRaisesRegex(u.AcquisitionError,'size limit'):country.xml_get(HTTP(response),country.FRANCE,{},limit=100)
        self.assertTrue(response.closed)
    def test_cancel_before_and_during_metadata(self):
        event=threading.Event();event.set();http=HTTP(Response(CAPS))
        with self.assertRaises(u.Cancelled):country.xml_get(http,country.FRANCE,{},event)
        self.assertFalse(http.calls)
        event.clear();response=Response(CAPS,on_block=event.set)
        with self.assertRaises(u.Cancelled):country.xml_get(HTTP(response),country.FRANCE,{},event)
        self.assertTrue(response.closed)
    def test_get_parameters_timeout_and_stream_preserved(self):
        http=HTTP(Response(CAPS));params={'SERVICE':'WMS','REQUEST':'GetCapabilities','VERSION':'1.3.0'}
        country.xml_get(http,country.FRANCE,params)
        self.assertEqual(http.calls,[('GET',country.FRANCE,{'params':params,'stream':True,'timeout':(15,90)})])
    def test_france_two_terrain_products_not_surface_model(self):
        ds,notes=country.france(HTTP(Response(CAPS)),BBOX,'dtm',None,lambda s:None)
        self.assertEqual([d.id for d in ds],['france:'+LIDAR,'france:'+RGE]);self.assertFalse(notes)
        self.assertEqual([policy.dataset_spacing(d) for d in ds],[.5,5.])
    def test_main_discovery_routes_valid_france_caps(self):
        messages=[];ds,notes=u.discover(BBOX,'France','dtm',http=HTTP(Response(CAPS)),printf=messages.append)
        self.assertEqual(len(ds),2);self.assertFalse(notes)
        self.assertFalse(any('unavailable' in message.lower() for message in messages))
    def test_main_discovery_true_error_has_notice_not_silent_no_coverage(self):
        raw=b'<ExceptionReport><Exception exceptionCode="BadRequest"><ExceptionText>Layer is unavailable</ExceptionText></Exception></ExceptionReport>'
        ds,notes=u.discover(BBOX,'France','dtm',http=HTTP(Response(raw)),printf=lambda s:None)
        self.assertEqual(ds,[]);self.assertTrue(any('BadRequest' in n for n in notes))
    def test_france_request_projection_resolution_and_float_guards_unchanged(self):
        ds,_=country.france(HTTP(Response(CAPS)),BBOX,'dtm',None,lambda s:None)
        for d in ds:
            for asset in d.assets:
                q=parse_qs(urlparse(asset.url).query)
                self.assertEqual(q['FORMAT'],['image/geotiff']);self.assertEqual(q['CRS'],['EPSG:2154'])
                w,s,e,n=map(float,q['BBOX'][0].split(','));r=policy.dataset_spacing(d)
                self.assertAlmostEqual((e-w)/int(q['WIDTH'][0]),r);self.assertAlmostEqual((n-s)/int(q['HEIGHT'][0]),r)
                self.assertTrue(asset.metadata['require_float'])
    def test_no_png_fallback(self):
        raw=CAPS.replace(b'<Format>image/geotiff</Format>',b'')
        with self.assertRaisesRegex(u.AcquisitionError,'GeoTIFF'):country.france(HTTP(Response(raw)),BBOX,'dtm',None,lambda s:None)
    def test_missing_layer_still_reports_failure(self):
        raw=CAPS.replace(LIDAR.encode(),b'unsupported_lidar').replace(RGE.encode(),b'unsupported_rge')
        with self.assertRaisesRegex(u.AcquisitionError,'Neither supported'):country.france(HTTP(Response(raw)),BBOX,'dtm',None,lambda s:None)
    def test_wcs_and_metalink_documents_preserved(self):
        for raw in (b'<Capabilities><Contents><CoverageSummary><CoverageId>terrain</CoverageId></CoverageSummary></Contents></Capabilities>',b'<CoverageDescriptions><Envelope srsName="EPSG:2154"/></CoverageDescriptions>',b'<metalink><file name="one.tif"><url>https://example.invalid/one.tif</url></file></metalink>'):
            with self.subTest(raw=raw):self.assertEqual(ET.tostring(parse(raw)),ET.tostring(ET.fromstring(raw)))
    def test_native_five_metre_limit_still_rejects_coarse(self):
        with self.assertRaises(u.AcquisitionError):policy.validate_dataset(u.Dataset('coarse','France','Coarse','dtm',resolution='10 m',metadata={'output_resolution_m':1.}))
    def test_discovery_to_real_geotiff_pipeline(self):
        ds,_=country.france(HTTP(Response(CAPS)),BBOX,'dtm',None,lambda s:None)
        for d in ds:
            with self.subTest(product=d.id),tempfile.TemporaryDirectory() as temp:
                project=Path(temp);(project/'heightmap.npy').write_bytes(b'keep-heightmap');(project/'mask.png').write_bytes(b'keep-mask')
                replies=[]
                for asset in d.assets:
                    q=parse_qs(urlparse(asset.url).query);w,s,e,n=map(float,q['BBOX'][0].split(','));res=policy.dataset_spacing(d)
                    width=int(q['WIDTH'][0]);height=int(q['HEIGHT'][0])
                    with MemoryFile() as mem:
                        with mem.open(driver='GTiff',width=width,height=height,count=1,dtype='float32',crs='EPSG:2154',transform=from_origin(w,n,res,res)) as dst:
                            dst.write(np.full((1,height,width),123.25,dtype='float32'))
                        replies.append(Response(mem.read()))
                class GridHTTP:
                    def get(self,url,**kwargs):
                        # Also answer the new native-resolution preflight from
                        # its actual requested BBOX/dimensions, not a full tile.
                        q=parse_qs(urlparse(url).query)
                        w,s,e,n=map(float,q['BBOX'][0].split(','))
                        width=int(q['WIDTH'][0]);height=int(q['HEIGHT'][0])
                        with MemoryFile() as mem:
                            with mem.open(driver='GTiff',width=width,height=height,count=1,
                                          dtype='float32',crs='EPSG:2154',
                                          transform=from_origin(w,n,(e-w)/width,(n-s)/height)) as dst:
                                dst.write(np.full((1,height,width),123.25,dtype='float32'))
                            return Response(mem.read())
                result=u.download(d,BBOX,project,http=GridHTTP(),printf=lambda s:None)
                self.assertTrue(result.files)
                for file in result.files:
                    with rasterio.open(file) as src:
                        self.assertEqual(src.count,1);self.assertLessEqual(max(src.res),5)
                        values=src.read(1,masked=True).compressed();self.assertTrue(values.size);np.testing.assert_allclose(values,123.25,atol=.001)
                self.assertEqual((project/'heightmap.npy').read_bytes(),b'keep-heightmap');self.assertEqual((project/'mask.png').read_bytes(),b'keep-mask')
                self.assertEqual(json.loads(Path(result.manifest).read_text())['resolution_policy'],policy.VERSION)

if __name__=='__main__':
    unittest.main(verbosity=2)
