"""Official <=5 m terrain acquisition: Finland, France, Germany, NL, NZ, Poland.

Automatic terrain routes, not portal-only placeholders. Every network contract
is checked at runtime. Coverage/format errors remain explicit; no coarser model,
DSM, rendered relief, or invented download URL replaces missing terrain.
"""
from __future__ import annotations
import concurrent.futures
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urljoin, urlparse
import pyproj
import uk_lidar_downloader as u

VERSION='TGC_BETA7_EXUS_SIX_COUNTRIES_V1'
REGIONS=('Finland','France','Germany','Netherlands','New Zealand','Poland')
AREAS={
 'Finland':[(19.,59.,32.,70.2)],
 'France':[(-5.2,41.3,9.7,51.2)], # metropolitan France + Corsica; not overseas
 'Germany':[(5.8,47.2,15.1,55.2)],
 'Netherlands':[(3.2,50.7,7.3,53.7)],
 'New Zealand':[(166.,-47.5,179.9,-34.)], # mainland public NZTM product
 'Poland':[(14.,49.,24.3,55.)],
}
PROVIDERS={
 'Finland':'https://paituli.csc.fi/download?data_id=mml_korkeusmalli_2m_all_tif_euref',
 'France':'https://cartes.gouv.fr/rechercher-une-donnee/dataset/IGNF_RGE-ALTI',
 'Germany':'https://www.bezreg-koeln.nrw.de/geobasis-nrw/produkte-und-dienste/hoehenmodelle/digitale-gelaendemodelle/digitales-gelaendemodell',
 'Netherlands':'https://www.pdok.nl/introductie/-/article/actueel-hoogtebestand-nederland-ahn',
 'New Zealand':'https://data.linz.govt.nz/layer/121859-new-zealand-lidar-1m-dem/',
 'Poland':'https://www.geoportal.gov.pl/en/services/download-service-wcs/',
}
FINLAND='https://paituli.csc.fi/geoserver/wcs'
NETHERLANDS='https://service.pdok.nl/rws/ahn/wcs/v1_0'
NRW='https://www.wcs.nrw.de/geobasis/wcs_nw_dgm'
BAVARIA_INDEX='https://geodaten.bayern.de/odd/a/dgm/dgm1/meta/metalink/09.meta4'
POLAND='https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF'
FRANCE='https://data.geopf.fr/wms-r/wms'
NZ_COLLECTION='https://nz-elevation.s3.ap-southeast-2.amazonaws.com/new-zealand/new-zealand/dem_1m/2193/collection.json'


def _local(tag):return tag.rsplit('}',1)[-1]


def xml_get(http,url,params,cancel=None,limit=16*1024*1024):
    u.check_cancel(cancel)
    # Stream metadata with a hard bound, including catalogues and capability documents.
    with http.get(url,params=params,stream=True,timeout=(15,90)) as response:
        response.raise_for_status();parts=[];size=0
        for block in response.iter_content(65536):
            u.check_cancel(cancel);size+=len(block)
            if size>limit:raise u.AcquisitionError('Provider metadata exceeds its size limit.')
            parts.append(block)
    raw=b''.join(parts)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise u.AcquisitionError('Unsafe external XML declaration in provider response.')
    root=ET.fromstring(raw)
    # TGC_BETA7_OGC_CAPABILITIES_EXCEPTION_FIX_V1
    # WMS Capabilities/Capability/Exception/Format declares the supported ERROR
    # FORMATS. Its presence in a successful catalogue is not an actual failure.
    # Detect real OGC error documents by their exact report/response elements,
    # not by a substring search for "Exception" anywhere in normal metadata.
    reports=[n for n in root.iter()
             if _local(n.tag) in ('ServiceExceptionReport','ExceptionReport')]
    if _local(root.tag) in ('ServiceException','Exception','ExceptionText'):
        reports.insert(0,root)
    if reports:
        messages=[]
        for report in reports:
            errors=[n for n in report.iter()
                    if _local(n.tag) in ('ServiceException','Exception')]
            if not errors:errors=[report]
            for error in errors:
                code=error.get('exceptionCode') or error.get('code') or ''
                locator=error.get('locator') or ''
                detail=' '.join(' '.join(error.itertext()).split())
                prefix=' / '.join(v for v in (code,locator) if v)
                message=((prefix+': ') if prefix and detail else prefix)+detail
                if message and message not in messages:messages.append(message)
        detail='; '.join(messages) or 'Empty '+_local(reports[0].tag)+' response.'
        raise u.AcquisitionError('Provider service error: '+detail[:800])
    return root


def _axis_order(crs,labels):
    """Return indices of easting and northing in the *advertised* envelope."""
    if labels:
        labels=[v.lower() for v in labels]
        east={'x','e','east','easting','lon','long','longitude'}
        north={'y','n','north','northing','lat','latitude'}
        if len(labels)==2 and labels[0] in east and labels[1] in north:return 0,1
        if len(labels)==2 and labels[1] in east and labels[0] in north:return 1,0
        raise u.AcquisitionError('Cannot resolve provider axis labels: '+repr(labels))
    axes=crs.axis_info
    if len(axes)>=2:
        dirs=[a.direction.lower() for a in axes[:2]]
        if dirs==['east','north']:return 0,1
        if dirs==['north','east']:return 1,0
    raise u.AcquisitionError('Provider did not supply usable horizontal axes.')


def describe_wcs(root,expected_epsg,native_m,version='2.0.1'):
    """Read rectified native grids from WCS 2.0 or WCS 1.0 descriptions."""
    envelopes=[n for n in root.iter() if _local(n.tag) in ('Envelope','EnvelopeWithTimePeriod') and n.get('srsName')]
    selected=None
    for env in envelopes:
        try:
            crs=pyproj.CRS.from_user_input(env.get('srsName')).to_2d()
            if crs.to_epsg()==expected_epsg:selected=(env,crs);break
        except (ValueError,pyproj.exceptions.CRSError):continue
    if selected is None:raise u.AcquisitionError('Provider description does not advertise the required native projected CRS.')
    env,crs=selected;labels=env.get('axisLabels','').split()
    # WCS 1.0 uses traditional x/y tuples when labels are absent. EPSG:2180
    # declares north/east, which must not reverse that older wire protocol.
    ix,iy = (0,1) if version=='1.0.0' and not labels else _axis_order(crs,labels)
    low=env.findtext('{*}lowerCorner');high=env.findtext('{*}upperCorner')
    if low is None or high is None:
        positions=env.findall('{*}pos')
        if len(positions)>=2:low,high=positions[0].text,positions[1].text
    try:lo=list(map(float,low.split()));hi=list(map(float,high.split()))
    except (AttributeError,ValueError):raise u.AcquisitionError('WCS native extent cannot be read.')
    if len(lo)!=2 or len(hi)!=2 or not all(math.isfinite(v) for v in lo+hi):
        raise u.AcquisitionError('Invalid WCS native extent.')
    extent=(min(lo[ix],hi[ix]),min(lo[iy],hi[iy]),max(lo[ix],hi[ix]),max(lo[iy],hi[iy]))
    offsets=[]
    for node in root.iter():
        if _local(node.tag)=='offsetVector':
            try:
                v=list(map(float,node.text.split()))
                if len(v)==2:offsets.append(math.hypot(*v))
            except (ValueError,AttributeError):pass
    if offsets:
        spacing=max(offsets)
        if not math.isfinite(spacing) or spacing<=0 or spacing>5+1e-8:
            raise u.AcquisitionError('5 m requirement: advertised WCS native spacing is '+str(spacing)+' m.')
        # Also reject a silently replaced/coarsened named product.
        if spacing>native_m*1.01:
            raise u.AcquisitionError('Named product no longer has its documented native grid spacing.')
    else:spacing=native_m # published product specification; file header still checked
    if not labels:labels=[a.abbrev or ('x' if a.direction=='east' else 'y') for a in crs.axis_info[:2]]
    return crs,extent,labels,ix,iy,spacing


def split_windows(box,spacing,max_pixels=1800):
    """Native-grid, non-overlapping requests under provider per-request limits."""
    x0,y0,x1,y1=box
    x0=math.floor(x0/spacing)*spacing;y0=math.floor(y0/spacing)*spacing
    x1=math.ceil(x1/spacing)*spacing;y1=math.ceil(y1/spacing)*spacing
    nx=int(round((x1-x0)/spacing));ny=int(round((y1-y0)/spacing))
    count=math.ceil(nx/max_pixels)*math.ceil(ny/max_pixels)
    if nx<=0 or ny<=0 or count>u.MAX_TILES:raise u.AcquisitionError('Requested coverage is empty or exceeds the course-sized tile limit.')
    for row in range(0,ny,max_pixels):
        for col in range(0,nx,max_pixels):
            w=min(max_pixels,nx-col);h=min(max_pixels,ny-row)
            yield (x0+col*spacing,y0+row*spacing,x0+(col+w)*spacing,y0+(row+h)*spacing,w,h)


def _dataset(region,identifier,title,spacing,assets,source,notes='',extra=None):
    meta={'native_resolution_m':spacing,'output_resolution_m':spacing,'local_utm':True,'source_documentation':source}
    meta.update(extra or {})
    return u.Dataset(identifier,region,title,'dtm','',str(spacing)+' m',
       'See official provider licence; source attribution retained',
       'Source: '+title,source,assets,
       notes+' Native spacing is not vertical accuracy. File headers/NoData are checked before import.',meta)


def wcs_dataset(http,bbox,cancel,printf,region,url,ids,epsg,spacing,title,version='2.0.1'):
    printf(region+': reading official terrain service capabilities and native grid.')
    caps=xml_get(http,url,{'SERVICE':'WCS','VERSION':version,'REQUEST':'GetCapabilities'},cancel)
    if _local(caps.tag) not in ('Capabilities','WCS_Capabilities'):
        raise u.AcquisitionError('Unrecognized WCS capabilities, not a coverage response.')
    if version=='1.0.0':
        names=[n.text for n in caps.findall('.//{*}CoverageOfferingBrief/{*}name') if n.text]
    else:names=[n.text for n in caps.findall('.//{*}CoverageId') if n.text]
    allowed=[name for name in names if name in ids]
    if not allowed:raise u.AcquisitionError('Expected bare-earth coverage is not advertised: '+', '.join(ids))
    cid=allowed[0]
    desc=xml_get(http,url,{'SERVICE':'WCS','VERSION':version,'REQUEST':'DescribeCoverage',
                  ('COVERAGE' if version=='1.0.0' else 'CoverageId'):cid},cancel)
    crs,extent,axes,ix,iy,native=describe_wcs(desc,epsg,spacing,version)
    requested=u.projected_bounds(bbox,crs,printf)
    if not u.intersects(requested,extent):return [],[]
    box=(max(requested[0],extent[0]),max(requested[1],extent[1]),min(requested[2],extent[2]),min(requested[3],extent[3]))
    # Never assume WCS pixel rendering implies survey coverage.
    assets=[]
    for i,(w,s,e,n,cols,rows) in enumerate(split_windows(box,native)):
        params=[('SERVICE','WCS'),('VERSION',version),('REQUEST','GetCoverage')]
        if version=='1.0.0':
            bounds=(w,s,e,n)  # WCS 1.0 BBOX is x/y, not EPSG axis order.
            params += [('COVERAGE',cid),('CRS',f'EPSG:{epsg}'),('RESPONSE_CRS',f'EPSG:{epsg}'),
                       ('BBOX',','.join('%.6f'%v for v in bounds)),('FORMAT','GEOTIFF'),('RESX',str(native)),('RESY',str(native))]
        else:
            params += [('CoverageId',cid),('FORMAT','image/tiff'),
                       ('SUBSET',f'{axes[ix]}({w:.6f},{e:.6f})'),('SUBSET',f'{axes[iy]}({s:.6f},{n:.6f})')]
        request_url=url+'?'+urlencode(params)
        metadata={'requested_native_bounds':[w,s,e,n],'source_epsg':epsg}
        if region=='Poland' and version=='1.0.0':
            metadata.update({'native_wcs_request_url':request_url, 'wcs_bbox_order':'xy',
                             'native_spacing_m':native, 'expected_width':cols,
                             'expected_height':rows})
        assets.append(u.Asset(request_url,f'{region}_dtm_{i+1}.tif',None,'file',metadata))
    ds=_dataset(region,region.lower().replace(' ','-')+':'+cid,title,native,assets,PROVIDERS[region],
                'Numeric WCS terrain, not styled map imagery. Download is divided into native-grid windows.')
    return [ds],[]


def finland(s,bbox,kind,cancel,printf):
    return wcs_dataset(s,bbox,cancel,printf,'Finland',FINLAND,
       ('paituli__mml_dem_2m_2018','paituli:mml_dem_2m_2018'),3067,2.,'NLS Finland / CSC Paituli 2 m terrain')


def netherlands(s,bbox,kind,cancel,printf):
    return wcs_dataset(s,bbox,cancel,printf,'Netherlands',NETHERLANDS,('dtm_05m',),28992,.5,'PDOK AHN bare-earth DTM 0.5 m')


def poland(s,bbox,kind,cancel,printf):
    # Use the provider's advertised identifier, not the broken Orthoimagery example.
    printf('Poland: discovering the NMT GRID1 GeoTIFF coverage name.')
    caps=xml_get(s,POLAND,{'SERVICE':'WCS','VERSION':'1.0.0','REQUEST':'GetCapabilities'},cancel)
    names=[n.text for n in caps.findall('.//{*}CoverageOfferingBrief/{*}name') if n.text]
    ids=[n for n in names if 'terrain' in n.lower() or 'nmt' in n.lower() or re.search(r'(^|[:_])dtm([:_]|$)',n.lower()) or n.lower()=='grid1']
    if len(ids)!=1:raise u.AcquisitionError('Cannot identify one bare-earth NMT coverage in the Polish GRID1 service.')
    # Reuse the capability response, avoiding a second request.
    class FirstResponse:
        def __init__(self,delegate):self.delegate=delegate;self.first=True
        def get(self,url,**kwargs):
            if self.first and kwargs.get('params',{}).get('REQUEST')=='GetCapabilities':
                self.first=False
                class R:
                    def __enter__(self):return self
                    def __exit__(self,*a):pass
                    def raise_for_status(self):pass
                    def iter_content(self,n):yield ET.tostring(caps)
                return R()
            return self.delegate.get(url,**kwargs)
    return wcs_dataset(FirstResponse(s),bbox,cancel,printf,'Poland',POLAND,tuple(ids),2180,1.,
                        'GUGiK NMT GRID1 — bare-earth terrain','1.0.0')


def france(s,bbox,kind,cancel,printf):
    printf('France: checking IGN numeric GeoTIFF terrain layers, not rendered hillshade.')
    caps=xml_get(s,FRANCE,{'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetCapabilities'},cancel,32*1024*1024)
    if _local(caps.tag) not in ('WMS_Capabilities','WMT_MS_Capabilities'):
        raise u.AcquisitionError('IGN did not return WMS capabilities.')
    formats=[n.text for n in caps.findall('.//{*}GetMap/{*}Format')]
    if 'image/geotiff' not in formats:
        raise u.AcquisitionError('IGN does not advertise numeric GeoTIFF output; PNG/JPEG terrain is not substituted.')
    byname={n.findtext('{*}Name'):n for n in caps.findall('.//{*}Layer') if n.findtext('{*}Name')}
    specifications=[('IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93',.5,'IGN LiDAR HD bare-earth MNT 0.5 m'),
                    ('ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES',5.,'IGN RGE ALTI — 5 m terrain')]
    results=[]
    for layer,res,title in specifications:
        if layer not in byname:continue
        # Native Lambert-93 avoids a Web Mercator pixel/ground-scale shortcut.
        box=u.projected_bounds(bbox,pyproj.CRS.from_epsg(2154),printf)
        assets=[]
        for i,(w,ss,e,n,width,height) in enumerate(split_windows(box,res)):
            params={'SERVICE':'WMS','VERSION':'1.3.0','REQUEST':'GetMap','LAYERS':layer,'STYLES':'',
                    'FORMAT':'image/geotiff','CRS':'EPSG:2154','BBOX':','.join('%.6f'%v for v in (w,ss,e,n)),
                    'WIDTH':width,'HEIGHT':height}
            assets.append(u.Asset(FRANCE+'?'+urlencode(params),f'IGN_terrain_{i+1}.tif',None,'file',
                                  {'requested_native_bounds':[w,ss,e,n],'source_epsg':2154,'require_float':True,
                                   'ign_wms_request_url':FRANCE+'?'+urlencode(params)}))
        results.append(_dataset('France','france:'+layer,title,res,assets,PROVIDERS['France'],
            'Metropolitan France/Corsica. The selected product stays separate; missing LiDAR HD is not filled from RGE ALTI.'))
    if not results:raise u.AcquisitionError('Neither supported IGN bare-earth terrain layer is advertised.')
    return results,[]


def bavaria(s,bbox,cancel,printf):
    printf('Germany / Bavaria: reading the official DGM1 Metalink tile inventory (metadata only).')
    root=xml_get(s,BAVARIA_INDEX,None,cancel,64*1024*1024)
    if _local(root.tag)!='metalink':raise u.AcquisitionError('Bavaria did not return its DGM1 Metalink inventory.')
    box=u.projected_bounds(bbox,pyproj.CRS.from_epsg(25832),printf)
    assets=[];unparsed=0
    for entry in root.findall('.//{*}file'):
        u.check_cancel(cancel)
        name=entry.get('name','').rsplit('/',1)[-1]
        match=re.fullmatch(r'(\d{3})_(\d{4})\.tiff?',name,re.I)
        if not match:unparsed+=1;continue
        x,y=int(match[1])*1000,int(match[2])*1000
        if not u.intersects(box,(x,y,x+1000,y+1000)):continue
        urls=[n.text for n in entry.findall('{*}url') if n.text and n.text.startswith('https://')]
        if not urls:raise u.AcquisitionError('Matching Bavarian tile has no HTTPS download.')
        size=entry.findtext('{*}size')
        assets.append(u.Asset(u._safe_url(urls[0]),name,int(size) if size and size.isdigit() else None))
    notes=[]
    if unparsed:notes.append('Bavaria: %d inventory filenames had unsupported grid names; those entries were not guessed.'%unparsed)
    if not assets:return [],notes
    if len(assets)>u.MAX_TILES:raise u.AcquisitionError('Too many Bavarian tiles for a course-sized acquisition.')
    ds=_dataset('Germany','germany:bavaria-dgm1','Bavaria DGM1 — 1 m bare-earth terrain',1.,assets,
         'https://geodaten.bayern.de/opengeodata/OpenDataDetail.html?pn=dgm1','Bavaria only; DHHN2016 heights are retained.')
    ds.licence='CC BY 4.0 — Bayerische Vermessungsverwaltung'
    return [ds],notes


def germany(s,bbox,kind,cancel,printf):
    output=[];notes=[];attempted=False
    choices=[((5.85,50.25,9.5,52.6),'North Rhine-Westphalia',lambda:wcs_dataset(s,bbox,cancel,printf,'Germany',NRW,('nw_dgm',),25832,1.,'NRW DGM1 — 1 m bare-earth terrain')),
             ((8.9,47.2,13.85,50.65),'Bavaria',lambda:bavaria(s,bbox,cancel,printf))]
    for envelope,title,operation in choices:
        if not u.intersects(bbox,envelope):continue
        attempted=True
        try:
            datasets,errors=operation();output.extend(datasets);notes.extend(errors)
        except u.Cancelled:raise
        except Exception as exc:notes.append(title+': '+str(exc))
    if not attempted:notes.append('Germany automatic providers currently cover NRW and Bavaria only. No 10/25/30 m national fallback is used.')
    return output,notes


def _https_s3(value,base):
    if value.startswith('s3://nz-elevation/'):
        return 'https://nz-elevation.s3.ap-southeast-2.amazonaws.com/'+value[len('s3://nz-elevation/'):]
    resolved=u._safe_url(urljoin(base,value))
    host=urlparse(resolved).hostname or ''
    if host not in ('nz-elevation.s3.ap-southeast-2.amazonaws.com',
                    'nz-elevation.s3-ap-southeast-2.amazonaws.com','nz-elevation.s3.amazonaws.com'):
        raise u.AcquisitionError('LINZ item changed outside the official public elevation bucket.')
    return resolved


def parse_nz_item(item,base,bbox):
    b=item.get('bbox')
    if not isinstance(b,(list,tuple)) or len(b) not in (4,6):
        raise u.AcquisitionError('LINZ STAC item has no usable spatial bounds; coverage is not established.')
    extent=b if len(b)==4 else [b[0],b[1],b[3],b[4]]
    if not u.intersects(bbox,extent):return []
    results=[]
    for key,asset in item.get('assets',{}).items():
        url=asset.get('href','')
        if not url.lower().split('?')[0].endswith(('.tif','.tiff')):continue
        if any(word in (key+' '+str(asset.get('title',''))).lower() for word in ('hillshade','thumbnail','mask','dsm')):continue
        roles=asset.get('roles',[])
        if roles and 'data' not in roles:continue
        resolved=_https_s3(url,base)
        native=asset.get('gsd',(item.get('properties') or {}).get('gsd',1.))
        if float(native)>5:raise u.AcquisitionError('LINZ item declares terrain coarser than 5 m.')
        results.append(u.Asset(resolved,urlparse(resolved).path.rsplit('/',1)[-1],asset.get('file:size'),'cog',
                               {'native_resolution_m':float(native),'item_id':item.get('id',''),'bbox':extent}))
    return results


def new_zealand(s,bbox,kind,cancel,printf):
    printf('New Zealand: reading official LINZ national 1 m DEM STAC metadata. Only intersecting COG windows are downloaded.')
    collection=u._json(s,'GET',NZ_COLLECTION,cancel)
    if not isinstance(collection,dict) or collection.get('type')!='Collection':
        raise u.AcquisitionError('LINZ did not return the national DEM STAC collection.')
    links=[l for l in collection.get('links',[]) if l.get('rel')=='item']
    if not links:raise u.AcquisitionError('LINZ collection has no advertised item links.')
    if len(links)>2000:raise u.AcquisitionError('Unexpectedly large LINZ collection; stopped rather than crawl an entire bucket.')
    # In-memory metadata cache is coordinate-free, bounded, and never contains a
    # project's origin/grid. Reusing catalogue documents cannot mix course grids.
    urls=list(dict.fromkeys(_https_s3(l['href'],NZ_COLLECTION) for l in links if l.get('href')))
    assets=[];notes=[];metadata_errors=0
    # Standard HTTP worker count is bounded. Per-thread sessions avoid sharing
    # mutable requests.Session state. Fake sessions used by unit tests stay serial.
    def get_one(url):
        u.check_cancel(cancel)
        cached=_NZ_CACHE.get(url)
        if cached and time.monotonic()-cached[0]<3600:return url,cached[1]
        own=isinstance(s,u.requests.Session)
        client=u.session() if own else s
        try:
            obj=u._json(client,'GET',url,cancel)
            return url,obj
        finally:
            if own:client.close()
    workers=6 if isinstance(s,u.requests.Session) else 1
    executor=concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures={executor.submit(get_one,url):url for url in urls}
    try:
        for count,future in enumerate(concurrent.futures.as_completed(futures),1):
            u.check_cancel(cancel)
            try:
                url,item=future.result()
                if not isinstance(item,dict) or item.get('type')!='Feature':raise u.AcquisitionError('Invalid LINZ STAC item.')
                if len(_NZ_CACHE)<2000 or url in _NZ_CACHE:_NZ_CACHE[url]=(time.monotonic(),item)
                assets.extend(parse_nz_item(item,url,bbox))
            except u.Cancelled:raise
            except Exception as exc:
                metadata_errors+=1
                notes.append('LINZ metadata incomplete: '+str(exc))
                if metadata_errors>=6:
                    notes.append('LINZ metadata search stopped after repeated errors; retained matches are partial, not complete coverage.')
                    break
            if count==1 or count%25==0 or count==len(urls):printf('LINZ metadata: %d/%d item(s); %d intersecting asset(s).'%(count,len(urls),len(assets)))
    finally:
        for f in futures:f.cancel()
        executor.shutdown(wait=True,cancel_futures=True)
    # A second failed metadata request must not erase already discovered assets.
    unique={a.url:a for a in assets}
    if not unique:return [],notes
    ds=_dataset('New Zealand','nz:national-dem1','LINZ New Zealand national LiDAR-derived 1 m DEM',1.,
       list(unique.values()),PROVIDERS['New Zealand'],
       'Main islands; NZVD2016 heights. Regional survey dates vary. Raster DTM, not raw points. COG byte-range access required.')
    ds.licence='CC BY 4.0 — Toitu Te Whenua Land Information New Zealand'
    return [ds],notes


_NZ_CACHE={}

def discover(region,s,bbox,kind,cancel=None,printf=print):
    if kind=='pointcloud':return [],[region+': this new adapter supplies bare-earth terrain, not raw LAS/LAZ. Choose Terrain only.']
    return {'Finland':finland,'France':france,'Germany':germany,'Netherlands':netherlands,
            'New Zealand':new_zealand,'Poland':poland}[region](s,bbox,kind,cancel,printf)
