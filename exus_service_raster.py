"""Small service-grid checks and reusable source files for IGN / Polish NMT.

No coordinate relabelling is done here. A wrong response is rejected before full
acquisition; a nonstandard WCS1 axis convention is negotiated by requesting a
second tiny window and comparing its *returned* coordinate bounds. Completed
source bytes are kept independently of disposable output staging.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode
import copy
import datetime
import hashlib
import json
import math
import os
import shutil
import time
import uuid

VERSION = 'TGC_BETA7_SERVICE_DOWNLOAD_V2'
POLAND_HOST = 'mapy.geoportal.gov.pl'
POLAND_PATH = '/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF'


def _u():
    import uk_lidar_downloader
    return uk_lidar_downloader


def _query(url):
    parsed=urlparse(str(url));out={}
    for key,value in parse_qsl(parsed.query,keep_blank_values=True):
        k=key.upper()
        if k in out:raise _u().AcquisitionError('Duplicate service request parameter: '+k)
        out[k]=value
    return parsed,out


def service_kind(asset):
    """Restrict caching/preflight to the supported official numeric services."""
    m=asset.metadata or {}
    if (asset.transport!='file' or not (m.get('ign_wms_request_url') or m.get('native_wcs_request_url'))):return None
    p,q=_query(asset.url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.fragment:
        return None
    if (p.hostname=='data.geopf.fr' and p.path in ('/wms-r','/wms-r/wms')
            and m.get('ign_wms_request_url')==asset.url and q.get('SERVICE')=='WMS'
            and q.get('REQUEST')=='GetMap' and q.get('FORMAT')=='image/geotiff'):
        return 'France'
    if (p.hostname==POLAND_HOST and p.path==POLAND_PATH
            and m.get('native_wcs_request_url')==asset.url and q.get('SERVICE')=='WCS'
            and q.get('VERSION')=='1.0.0' and q.get('REQUEST')=='GetCoverage'):
        return 'Poland'
    return None


def _atomic_json(path,obj):
    path=Path(path);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(obj,indent=2),encoding='utf-8')
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def _digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def cached_transfer(asset,target,root,http,cancel=None,printf=print):
    """Retain only complete TIFF transfers. Cache entries are never course inputs."""
    u=_u();u.check_cancel(cancel)
    if not service_kind(asset):return u.transfer(asset,target,cancel,printf,http)
    cache=Path(root)/'SourceCache';cache.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(asset.url.encode('utf-8')).hexdigest()
    raw=cache/(key+'.tif');meta=cache/(key+'.json');valid=False
    if raw.is_file() and meta.is_file():
        try:
            record=json.loads(meta.read_text(encoding='utf-8'))
            valid=(record.get('complete') is True and record.get('url')==asset.url
                   and raw.stat().st_size==record.get('bytes')
                   and _digest(raw)==record.get('sha256'))
        except (OSError,ValueError,TypeError):pass
    if valid:
        printf('ex-US reusing complete source download: '+asset.name+' (no network transfer).')
    else:
        if raw.exists() or meta.exists():
            printf('NOTICE: source cache is incomplete/changed; downloading a fresh copy: '+asset.name)
        temp=cache/(key+'.'+uuid.uuid4().hex+'.download')
        try:
            u.transfer(asset,temp,cancel,printf,http)
            with temp.open('rb') as f:head=f.read(4)
            if head not in (b'II*\0',b'MM\0*',b'II+\0',b'MM\0+'):
                raise u.AcquisitionError('Service response is not a TIFF; no source file cached: '+asset.name)
            u.check_cancel(cancel)
            record={'version':VERSION,'complete':True,'url':asset.url,'name':asset.name,
                    'bytes':temp.stat().st_size,'sha256':_digest(temp),
                    'downloaded_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
            os.replace(temp,raw);_atomic_json(meta,record)
        finally:
            if temp.exists():temp.unlink()
            partial=temp.with_name(temp.name+'.part')
            if partial.exists():partial.unlink()
    u.check_cancel(cancel)
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(raw,target)
    return target


def _diagnostic(src,metadata,reason,printf):
    """Save actual-vs-requested grid details outside temporary output staging."""
    try:
        path=Path(src.name).resolve()
        stage=next((p for p in path.parents if p.name.startswith('.partial_')),None)
        folder=(stage.parent if stage else path.parent)/'Diagnostics'
        folder.mkdir(parents=True,exist_ok=True)
        name='SERVICE_GRID_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json'
        record={'version':VERSION,'reason':str(reason),'source':str(src.name),
                'actual_crs_wkt':src.crs.to_wkt() if src.crs else None,
                'bounds':list(src.bounds),'transform':list(src.transform),
                'width':src.width,'height':src.height,'dtypes':list(src.dtypes),
                'request':metadata}
        _atomic_json(folder/name,record)
        printf('ex-US actual/requested grid report saved: '+str(folder/name))
    except Exception as exc:
        printf('NOTICE: could not save grid report: '+str(exc))


def validate_extent(src,metadata,printf=print):
    u=_u();expected=(metadata or {}).get('requested_native_bounds')
    if not expected:return
    try:
        if len(expected)!=4 or not all(math.isfinite(float(v)) for v in expected):
            raise u.AcquisitionError('Invalid requested native bounds in acquisition metadata.')
        if src.transform.b or src.transform.d or src.transform.a<=0 or src.transform.e>=0:
            raise u.AcquisitionError('Downloaded service grid is not north-up; no rotation/axis relabelling is applied.')
        actual=list(map(float,src.bounds));expected=list(map(float,expected))
        tol=max(abs(src.transform.a),abs(src.transform.e))*1.01
        delta=[a-b for a,b in zip(actual,expected)]
        if any(not math.isfinite(v) or abs(v)>tol for v in delta):
            # Name used by preflight to distinguish a geometric mismatch from a
            # connection, content, or CRS failure. It does NOT make this acceptable.
            err=u.AcquisitionError('Downloaded coverage extent mismatch. Requested west/south/east/north: '
                 +repr(expected)+'; received: '+repr(actual)+'; differences (m): '+repr(delta)
                 +'. No unverified axis swap or CRS override was applied.')
            err.service_extent_mismatch=True
            raise err
        if metadata.get('native_wcs_request_url'):
            p,q=_query(metadata['native_wcs_request_url'])
            if p.scheme!='https' or p.hostname!=POLAND_HOST or p.path!=POLAND_PATH:
                raise u.AcquisitionError('Polish native-grid validation requires the official NMT service.')
            if q.get('VERSION')!='1.0.0' or q.get('REQUEST')!='GetCoverage' or q.get('CRS')!='EPSG:2180':
                raise u.AcquisitionError('Unsupported Polish WCS request contract.')
            wire=list(map(float,q.get('BBOX','').split(',')))
            order=metadata.get('wcs_bbox_order','xy')
            intended=expected if order=='xy' else [expected[1],expected[0],expected[3],expected[2]]
            if order not in ('xy','yx') or len(wire)!=4 or any(abs(a-b)>1e-5 for a,b in zip(wire,intended)):
                raise u.AcquisitionError('Polish WCS request does not match its recorded native grid.')
            if src.crs is None:
                raise u.AcquisitionError('Polish response has no coordinate system.')
            import rasterio
            import pyproj
            expected_crs=rasterio.crs.CRS.from_epsg(2180)
            if not pyproj.CRS.from_wkt(src.crs.to_wkt()).to_2d().equals(
                    pyproj.CRS.from_wkt(expected_crs.to_wkt()).to_2d(),ignore_axis_order=True):
                raise u.AcquisitionError('Polish WCS response CRS is not EPSG:2180; no relabelling.')
            native=float(metadata.get('native_spacing_m',1.))
            if not (native==1. and abs(src.res[0]-native)<=1e-6 and abs(src.res[1]-native)<=1e-6):
                raise u.AcquisitionError('Polish NMT GRID1 response is not the selected native 1 m grid.')
            for name,actual_size in [('expected_width',src.width),('expected_height',src.height)]:
                expected_size=int(metadata.get(name,actual_size))
                if abs(actual_size-expected_size)>1:
                    raise u.AcquisitionError('Polish WCS response dimensions differ from requested grid.')
    except Exception as exc:
        _diagnostic(src,metadata,exc,printf)
        raise


def _alter(asset,bounds,width,height,order=None,probe=False):
    """Change the request, never the returned file's georeferencing."""
    a=copy.deepcopy(asset);p,q=_query(a.url);kind=service_kind(a)
    if not kind:raise _u().AcquisitionError('Not an allowlisted service-grid asset.')
    if kind=='France':
        q['BBOX']=','.join('%.6f'%v for v in bounds)
        q['WIDTH']=str(width);q['HEIGHT']=str(height)
    else:
        order=order or a.metadata.get('wcs_bbox_order','xy')
        b=bounds if order=='xy' else [bounds[1],bounds[0],bounds[3],bounds[2]]
        q['BBOX']=','.join('%.6f'%v for v in b)
        a.metadata.update({'wcs_bbox_order':order,'expected_width':width,'expected_height':height})
    a.url=p._replace(query=urlencode(q)).geturl()
    a.metadata['requested_native_bounds']=list(bounds)
    a.metadata['ign_wms_request_url' if kind=='France' else 'native_wcs_request_url']=a.url
    a.bytes=None
    if probe:a.name=kind+'_native_grid_check.tif'
    return a


def _validate_probe(path,metadata,printf):
    import rasterio
    from exus_france_crs import resolve_raster_crs
    from exus_resolution_policy import raster_spacing_m
    with rasterio.open(path) as src:
        if src.crs is None or src.count!=1 or src.dtypes[0] in ('uint8','int8'):
            raise _u().AcquisitionError('Native-grid check did not return georeferenced numeric terrain.')
        raster_spacing_m(src,None)
        resolve_raster_crs(src,metadata,printf)
        validate_extent(src,metadata,printf)
    # A tiny probe may legitimately be NoData. Coverage is checked on the full
    # requested crop, not invented and not concluded from this format/grid test.


def prepare_services(dataset,root,stage,http,cancel=None,printf=print):
    """Probe each selected layer once; never download a full tile to try axes."""
    u=_u();dataset=copy.deepcopy(dataset);done=set()
    for asset in list(dataset.assets):
        kind=service_kind(asset)
        if not kind:continue
        p,q=_query(asset.url)
        group=(kind,p.netloc,p.path,q.get('LAYERS') or q.get('COVERAGE'))
        if group in done:continue
        done.add(group)
        bounds=asset.metadata['requested_native_bounds']
        spacing=float(asset.metadata.get('native_spacing_m',0.) or
                      ((bounds[2]-bounds[0])/int(q['WIDTH'])))
        cols=min(32,max(1,round((bounds[2]-bounds[0])/spacing)))
        rows=min(24,max(1,round((bounds[3]-bounds[1])/spacing)))
        # Start on the first tile's native lattice; no extra interpolation.
        box=[bounds[0],bounds[1],bounds[0]+cols*spacing,bounds[1]+rows*spacing]
        order=asset.metadata.get('wcs_bbox_order','xy')
        choices=[order]+([('yx' if order=='xy' else 'xy')] if kind=='Poland' else [])
        selected=None
        for trial in choices:
            u.check_cancel(cancel)
            probe=_alter(asset,box,cols,rows,trial,True)
            printf(kind+': checking a small %d x %d native grid before full downloads%s.'%
                   (cols,rows,(' (WCS 1.0 '+trial+' order)' if kind=='Poland' else '')))
            path=Path(stage)/(kind.lower()+'_grid_check_'+trial+'.tif')
            cached_transfer(probe,path,root,http,cancel,printf)
            try:
                _validate_probe(path,probe.metadata,printf)
                selected=trial;break
            except u.Cancelled:raise
            except u.AcquisitionError as exc:
                if kind!='Poland' or not getattr(exc,'service_extent_mismatch',False) or trial==choices[-1]:raise
                printf('Poland: small response grid does not match; checking the alternate request order before downloading full terrain.')
            finally:
                if path.exists():path.unlink()
        if selected is None:raise u.AcquisitionError(kind+': native-grid check did not complete.')
        printf(kind+': native-grid check passed. Full raster validation remains enabled.')
        if kind=='Poland':
            for i,other in enumerate(dataset.assets):
                if service_kind(other)!='Poland':continue
                op,oq=_query(other.url)
                if (op.netloc,op.path,oq.get('COVERAGE'))!=(p.netloc,p.path,q.get('COVERAGE')):continue
                b=other.metadata['requested_native_bounds'];res=other.metadata['native_spacing_m']
                dataset.assets[i]=_alter(other,b,round((b[2]-b[0])/res),round((b[3]-b[1])/res),selected)
            printf('Poland: verified request axis order '+selected+'; source raster coordinates are unchanged.')
    return dataset
