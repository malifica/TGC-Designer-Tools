"""ex-US elevation acquisition. Does not change course terrain/CFS/tree algorithms.

England: EA survey-tile catalogue (DTM / point clouds).
Scotland: direct public AWS inventory (DTM / LAS/LAZ, unrestricted collections only).
Wales: Welsh Government 32-bit DTM COG, read by spatial window.
Spain/Switzerland/Canada/Japan: see exus_lidar_sources for product-specific routes.
Australia/Mexico/Northern Ireland: official portal handoff, not automatic download.

Network responses and downloaded files are untrusted: validate types, paths,
coverage, CRS and payloads; never return an HTML error page as a terrain file.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, quote, urljoin
import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import stat
import threading
import time
import uuid
import zipfile

import numpy as np
import pyproj
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

VERSION = 'TGC_BETA7_EXUS_DOWNLOAD_5M_V2'
EA_SEARCH = 'https://environment.data.gov.uk/backend/catalog/api/tiles/collections/survey/search'

WALES_DTM = 'https://dmwproductionblob.blob.core.windows.net/cogs/lidar/wales_dtm_32bit_cog.tif'
DEFAULT_BUFFER_M = 150.0
MAX_AREA_KM2 = 100.0
MAX_DOWNLOAD_BYTES = 16 * 1024**3
MAX_EXTRACT_BYTES = 48 * 1024**3
MAX_TILES = 500
REGIONS = ('Auto', 'Australia', 'Canada', 'England', 'Finland', 'France', 'Germany', 'Japan', 'Mexico', 'Netherlands', 'New Zealand', 'Northern Ireland', 'Poland', 'Scotland', 'Spain', 'Switzerland', 'Wales')
PROVIDERS = {'England': 'https://environment.data.gov.uk/survey', 'Scotland': 'https://remotesensingdata.gov.scot/data#/map', 'Wales': 'https://datamap.gov.wales/maps/lidar-viewer/', 'Northern Ireland': 'https://www.opendatani.gov.uk/', 'Spain': 'https://centrodedescargas.cnig.es/CentroDescargas/', 'Switzerland': 'https://www.swisstopo.admin.ch/en/download-geodata-swisstopo', 'Australia': 'https://elevation.fsdf.org.au/', 'Canada': 'https://geo.ca/elevation/', 'Mexico': 'https://www.inegi.org.mx/app/geo2/elevacionesmex/', 'Japan': 'https://maps.gsi.go.jp/', 'Finland': 'https://paituli.csc.fi/download?data_id=mml_korkeusmalli_2m_all_tif_euref', 'France': 'https://cartes.gouv.fr/rechercher-une-donnee/dataset/IGNF_RGE-ALTI', 'Germany': 'https://www.bezreg-koeln.nrw.de/geobasis-nrw/produkte-und-dienste/hoehenmodelle/digitale-gelaendemodelle/digitales-gelaendemodell', 'Netherlands': 'https://www.pdok.nl/introductie/-/article/actueel-hoogtebestand-nederland-ahn', 'New Zealand': 'https://data.linz.govt.nz/layer/121859-new-zealand-lidar-1m-dem/', 'Poland': 'https://www.geoportal.gov.pl/en/services/download-service-wcs/'}
RASTER_SUFFIXES = {'.tif', '.tiff', '.asc'}
POINT_SUFFIXES = {'.las', '.laz'}


class AcquisitionError(RuntimeError):
    pass


class Cancelled(AcquisitionError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled('ex-US download cancelled. Existing project outputs were not changed.')


@dataclass
class Asset:
    url: str
    name: str
    bytes: int | None = None
    transport: str = 'file'  # file or cog

    metadata: dict = field(default_factory=dict)


@dataclass
class Dataset:
    id: str
    region: str
    title: str
    kind: str  # dtm or pointcloud
    year: str = ''
    resolution: str = ''
    licence: str = 'See provider terms'
    attribution: str = ''
    source_page: str = ''
    assets: list[Asset] = field(default_factory=list)
    notes: str = 'Coverage must be checked; intersecting tiles can contain gaps.'

    metadata: dict = field(default_factory=dict)

    @property
    def known_bytes(self):
        if self.assets and all(a.bytes is not None for a in self.assets):
            return sum(a.bytes for a in self.assets)
        return None


@dataclass
class DownloadResult:
    project_dir: str
    data_dir: str
    kind: str
    files: list[str]
    manifest: str
    warnings: list[str] = field(default_factory=list)


def session():
    s = requests.Session()
    s.headers.update({'User-Agent': 'TGC-Designer-Tools-Beta7-exUS/1.0'})
    retry = Retry(total=2, connect=2, read=0, status=2,
                  backoff_factor=0.6, status_forcelist=(429, 502, 503, 504),
                  allowed_methods=frozenset(('GET', 'POST')), respect_retry_after_header=False)
    s.mount('https://', HTTPAdapter(max_retries=retry))
    return s


def _json(s, method, url, cancel=None, **kwargs):
    check_cancel(cancel)
    with s.request(method, url, timeout=(15, 90), **kwargs) as response:
        response.raise_for_status()
        if len(response.content) > 40 * 1024 * 1024:
            raise AcquisitionError('Provider catalogue response is unexpectedly large.')
        try:
            obj = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise AcquisitionError('Provider returned a non-JSON response: ' + url) from exc
    check_cancel(cancel)
    return obj


def validate_bbox(bbox):
    from exus_lidar_sources import validate_bbox as validate
    return validate(bbox)


def course_bbox(osm_file, buffer_m=DEFAULT_BUFFER_M, printf=print):
    # Reuse the already reviewed safe course-boundary selection, not every OSM node.
    import usgs_ept_downloader
    b = usgs_ept_downloader.read_osm_course_bounds(
        osm_file, buffer_m=buffer_m, printf=lambda message: printf(str(message).replace('AWS EPT', 'ex-US acquisition')))
    return validate_bbox(b)


def geojson_bbox(bbox):
    w, s, e, n = bbox
    return {'type': 'Polygon', 'coordinates': [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}


def wkt_bbox(bbox):
    pts = geojson_bbox(bbox)['coordinates'][0]
    return 'POLYGON((' + ','.join('%.10f %.10f' % tuple(p) for p in pts) + '))'


def intersects(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def provider_regions(bbox, region='Auto'):
    from exus_lidar_sources import regions_for_bbox
    return regions_for_bbox(bbox, region)


def _text(value):
    if isinstance(value, dict):
        return str(value.get('label') or value.get('id') or value.get('name') or '')
    return str(value or '')


def classify_product(value):
    s = re.sub(r'[^a-z0-9]+', ' ', str(value).lower())
    if any(x in s for x in ('hillshade','intensity','aerial','photograph','imagery')):
        return None
    if 'point cloud' in s or 'pointcloud' in s or re.search(r'\b(las|laz)\b', s):
        return 'pointcloud'
    if 'dtm' in s.split() or 'digital terrain' in s:
        return 'dtm'
    return None  # never route DSM or shaded relief as bare-earth terrain


def _safe_url(url):
    p = urlparse(str(url))
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise AcquisitionError('Provider returned an unsupported download URL.')
    return str(url)


def parse_england(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('results'), list):
        raise AcquisitionError('Environment Agency catalogue format changed: expected a results list.')
    groups = {}
    for item in obj['results']:
        if not isinstance(item, dict):
            continue
        product = item.get('product') or {}
        pid = str(product.get('id', '')) if isinstance(product, dict) else str(product)
        label = _text(product)
        kind = classify_product(pid + ' ' + label)
        if kind is None:
            continue
        url = item.get('uri')
        if not url:
            continue
        url = _safe_url(urljoin('https://environment.data.gov.uk/', url))
        year, resolution, tile = map(_text, (item.get('year'), item.get('resolution'), item.get('tile')))
        key = (pid, year, resolution, kind)
        ds = groups.setdefault(key, Dataset('ea:'+':'.join(key), 'England', label or pid, kind,
                          year, resolution, 'Open Government Licence v3',
                          'Contains Environment Agency data; retain the downloaded survey attribution.',
                          PROVIDERS['England']))
        if url not in {a.url for a in ds.assets}:
            size = item.get('size') or item.get('fileSize')
            try: size = int(size) if size is not None else None
            except (ValueError, TypeError): size = None
            ds.assets.append(Asset(url, tile or str(len(ds.assets)+1), size))
    if len(obj['results']) > 50000:
        raise AcquisitionError('Too many EA catalogue records for a course-sized request.')
    return list(groups.values())


def england_discover(s, bbox, cancel=None, printf=print):
    printf('UK / England: querying Environment Agency survey tiles for the OSM extent.')
    obj = _json(s, 'POST', EA_SEARCH, cancel, json=geojson_bbox(bbox),
                headers={'Content-Type':'application/geo+json', 'Accept':'application/json'})
    # Explicit next links are followed; do not silently truncate a paginated response.
    results = list(obj.get('results', [])) if isinstance(obj, dict) else []
    seen = set()
    while isinstance(obj, dict) and (obj.get('next') or obj.get('nextLink')):
        link = obj.get('next') or obj.get('nextLink')
        if isinstance(link, dict): link = link.get('href')
        link = _safe_url(urljoin(EA_SEARCH, str(link)))
        if link in seen or len(seen) >= 50:
            raise AcquisitionError('EA catalogue pagination could not be completed safely.')
        seen.add(link)
        obj = _json(s, 'GET', link, cancel)
        if not isinstance(obj.get('results'), list):
            raise AcquisitionError('Incomplete EA catalogue page.')
        results.extend(obj['results'])
    if not isinstance(obj, dict) or 'results' not in obj:
        return parse_england(obj)
    return parse_england({'results': results})


def _restricted(collection, kind):
    text = json.dumps(collection, ensure_ascii=False).lower()
    if 'non-commercial' in text or 'non commercial' in text or 'noncommercial' in text:
        return True
    # The provider's published exception applies even if a record omits its licence.
    return kind == 'pointcloud' and bool(re.search(r'phase[- _]?0?2(?:\b|/)', text))


def parse_scotland_collections(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('result'), list):
        raise AcquisitionError('Scottish catalogue format changed: expected a result list.')
    selected = []
    for col in obj['result']:
        meta = col.get('metadata') or {}
        name = str(col.get('name') or '')
        if '/ogc' in name.lower(): continue
        kind = classify_product(name + ' ' + str(meta.get('title', '')) + ' ' + str(meta.get('dataFormat', '')))
        if kind and not _restricted(col, kind):
            selected.append((col, kind))
    return selected


def _scotland_asset(item):
    # Product data is specified by the official JNCC catalogue types.
    data = item.get('data') or {}
    product = data.get('product') or {}
    if not product:
        return None
    if isinstance(product.get('http'), dict):
        d = product['http']; url = d.get('url'); size = d.get('size')
    elif isinstance(product.get('s3'), dict):
        d = product['s3']; bucket = str(d.get('bucket', '')); region = str(d.get('region') or 'eu-west-2')
        if not re.fullmatch(r'[a-z0-9.-]+', bucket) or not re.fullmatch(r'[a-z0-9-]+', region):
            raise AcquisitionError('Invalid Scottish S3 catalogue entry.')
        key = str(d.get('key', '')).lstrip('/')
        url = f'https://{bucket}.s3.{region}.amazonaws.com/' + quote(key, safe='/')
        size = d.get('size')
    else:
        return None
    if not url:
        return None
    try: size = int(size) if size is not None else None
    except (ValueError, TypeError): size = None
    return Asset(_safe_url(url), str(item.get('name') or item.get('id') or 'tile'), size)


def scotland_discover(s, bbox, cancel=None, printf=print, kind='all'):
    from scotland_s3 import discover as direct_discover
    data, notices = direct_discover(s, bbox, kind, cancel, printf)
    return data


def wales_discover(s, bbox, cancel=None, printf=print):
    if not intersects(bbox, (-5.6,51.3,-2.3,53.6)): return []
    check_cancel(cancel)
    # Range support and actual finite coverage are checked at download, not assumed
    # from this broad routing envelope. This must never fetch a national COG whole.
    printf('UK / Wales: offering a course-sized window of the official 32-bit DTM; finite coverage is checked during download.')
    return [Dataset('wales:dtm32', 'Wales', 'Welsh Government 1 m bare-earth DTM (COG window)', 'dtm',
                    '2020–2023', '1 m', 'See Welsh Government dataset terms',
                    'Welsh Government LiDAR; retain DataMapWales source attribution.',
                    PROVIDERS['Wales'], [Asset(WALES_DTM,'Wales_DTM',None,'cog')],
                    'Not a coverage guarantee. Reads only the selected window; no point-cloud product in this adapter.')]


def discover(bbox, region='Auto', kind='all', cancel=None, printf=print, http=None):
    from exus_lidar_sources import country_discover, mode_notice
    from scotland_s3 import discover as direct_scotland
    bbox = validate_bbox(bbox)
    if kind not in ('all','dtm','pointcloud'):raise AcquisitionError('Invalid product selection.')
    own=http is None;s=http or session();output=[];errors=[]
    try:
        for name in provider_regions(bbox,region):
            check_cancel(cancel)
            notice=mode_notice(name,kind)
            if notice:
                errors.append(notice);printf('NOTICE: '+notice);continue
            try:
                if name=='England':data=england_discover(s,bbox,cancel,printf);notes=[]
                elif name=='Scotland':data,notes=direct_scotland(s,bbox,kind,cancel,printf)
                elif name=='Wales':data=wales_discover(s,bbox,cancel,printf);notes=[]
                else:data,notes=country_discover(name,s,bbox,kind,cancel,printf)
                output.extend(data);errors.extend(notes)
                for note in notes:printf('NOTICE: '+str(note))
            except Cancelled:raise
            except Exception as exc:
                errors.append(name+': '+str(exc));printf('ex-US source unavailable: '+errors[-1])
        result=[d for d in output if kind=='all' or d.kind==kind]
        from exus_resolution_policy import filter_datasets
        result, resolution_notices = filter_datasets(result,printf)
        errors.extend(resolution_notices)
        result.sort(key=lambda d:(d.region,d.kind,d.title,d.year))
        printf('ex-US discovery: %d dataset choice(s). Errors, portal-only sources and partial searches are NOT interpreted as no coverage.'%len(result))
        return result,errors
    finally:
        if own:s.close()


def _projection(crs, printf=print):
    from tgc_cfs_display import importer_transformer
    proj = pyproj.Proj(crs)
    # Same source definition and always-XY convention used by CFS/final importer.
    tr = importer_transformer(proj)
    if pyproj.CRS(crs).to_epsg() == 27700:
        from pyproj.transformer import TransformerGroup
        source = pyproj.Proj(proj='latlong', datum='WGS84').crs
        group = TransformerGroup(source, proj.crs, always_xy=True)
        if not group.best_available:
            printf('WARNING: preferred British National Grid transformation grid (OSTN15) is unavailable. '
                   'The same installed transformation as CFS/import will be used, but alignment can be less accurate. '
                   'No grid, CRS or datum setting has been changed.')
    return tr


def projected_bounds(bbox, crs, printf=print):
    w,s,e,n=bbox
    t=_projection(crs,printf)
    v=np.linspace(0.,1.,33)
    lons=np.r_[w+(e-w)*v,w+(e-w)*v,np.full(33,w),np.full(33,e)]
    lats=np.r_[np.full(33,s),np.full(33,n),s+(n-s)*v,s+(n-s)*v]
    x,y=t.transform(lons,lats,errcheck=True)
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise AcquisitionError('Nonfinite ex-US download bounds; no file will be processed.')
    return (float(min(x)),float(min(y)),float(max(x)),float(max(y)))


def transfer(asset, target, cancel=None, printf=print, http=None):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    own=http is None;s=http or session();part=target.with_name(target.name+'.part')
    try:
        check_cancel(cancel)
        started=time.monotonic()
        printf('ex-US connecting / waiting for provider: '+asset.name)
        with s.get(_safe_url(asset.url),stream=True,timeout=(15,90)) as r:
            r.raise_for_status()
            mime=r.headers.get('Content-Type','').lower()
            if any(t in mime for t in ('text/html','application/json','application/xml','text/xml')):
                raise AcquisitionError('Download returned an error/document instead of terrain: '+asset.name)
            total=int(r.headers.get('Content-Length','0') or 0)
            if total>MAX_DOWNLOAD_BYTES:raise AcquisitionError('A selected file exceeds the 16 GB download limit.')
            if total and shutil.disk_usage(target.parent).free < total*2+256*1024**2:
                raise AcquisitionError('Insufficient free disk space for the selected tile.')
            count=0;last=0;body_started=time.monotonic()
            printf('ex-US response received for '+asset.name+' after %.1f s; transferring bytes.'%(body_started-started))
            with part.open('wb') as f:
                for b in r.iter_content(1024*1024):
                    check_cancel(cancel)
                    if not b: continue
                    count+=len(b)
                    if count>MAX_DOWNLOAD_BYTES:raise AcquisitionError('Download exceeds the 16 GB limit.')
                    f.write(b)
                    if time.monotonic()-last>=1:
                        suffix=(' / %.1f MB (%d%%)' % (total/1e6,min(100,100*count//total))) if total else ' (total size not supplied)'
                        elapsed=max(time.monotonic()-body_started,.001)
                        printf('ex-US download '+asset.name+': %.1f MB'% (count/1e6)+suffix+
                               ' | %.2f MB/s | %.0f s elapsed'%(count/1e6/elapsed,time.monotonic()-started))
                        last=time.monotonic()
            if not count or (total and count!=total):raise AcquisitionError('Incomplete download: '+asset.name)
            if asset.bytes and count!=asset.bytes:raise AcquisitionError('Downloaded size differs from catalogue: '+asset.name)
        os.replace(part,target)
        printf('ex-US downloaded '+asset.name+' in %.1f s'%(time.monotonic()-started))
        return target
    finally:
        if part.exists():part.unlink()
        if own:s.close()


def unpack(path, folder, kind, cancel=None):
    """Extract data and CRS sidecars only; reject dangerous archive paths before writes."""
    path=Path(path);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    wanted=RASTER_SUFFIXES if kind=='dtm' else POINT_SUFFIXES
    if not zipfile.is_zipfile(path):
        with path.open('rb') as handle:magic=handle.read(4)
        ext='.laz' if magic==b'LASF' else '.tif' if magic[:2] in (b'II',b'MM') else None
        if not ext or ext not in wanted:raise AcquisitionError('Unrecognized terrain payload: '+path.name)
        dest=folder/(path.stem+ext);shutil.copy2(path,dest);return [dest]
    output=[]
    with zipfile.ZipFile(path) as z:
        entries=z.infolist()
        if sum(i.file_size for i in entries)>MAX_EXTRACT_BYTES:
            raise AcquisitionError('Archive expands beyond the 48 GB safety limit.')
        for i in entries:
            p=PurePosixPath(i.filename.replace('\\','/'))
            if p.is_absolute() or '..' in p.parts or ':' in str(p) or stat.S_ISLNK(i.external_attr>>16):
                raise AcquisitionError('Unsafe path in downloaded archive.')
        for i in entries:
            check_cancel(cancel)
            if i.is_dir():continue
            p=PurePosixPath(i.filename.replace('\\','/'))
            if p.suffix.lower() not in wanted|{'.prj','.wkt','.xml'}:continue
            dest=folder.joinpath(*p.parts);dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as src,dest.open('wb') as dst:
                while True:
                    check_cancel(cancel);block=src.read(1024*1024)
                    if not block:break
                    dst.write(block)
            if p.suffix.lower() in wanted:output.append(dest)
    if not output:raise AcquisitionError('Selected product archive contains no expected '+kind+' data.')
    return output


def _range_check(s,url,cancel):
    check_cancel(cancel)
    with s.get(url,headers={'Range':'bytes=0-15','Accept-Encoding':'identity'},stream=True,timeout=(15,90)) as r:
        if r.status_code!=206 or not r.headers.get('Content-Range','').lower().startswith('bytes 0-'):
            raise AcquisitionError('COG server does not support byte ranges. Refusing a full national-raster download.')
        head=next(r.iter_content(16),b'')
        if head[:2] not in (b'II',b'MM'):raise AcquisitionError('COG endpoint did not return TIFF bytes.')


def crop_raster(source, dest, bbox, printf=print, cancel=None, http=None, source_metadata=None):
    import rasterio
    from rasterio.windows import Window, from_bounds
    is_url=str(source).startswith('https://')
    if is_url:
        own=http is None;s=http or session()
        try:_range_check(s,str(source),cancel)
        finally:
            if own:s.close()
    env={'GDAL_DISABLE_READDIR_ON_OPEN':'EMPTY_DIR','CPL_VSIL_CURL_ALLOWED_EXTENSIONS':'.tif,.tiff',
         'GDAL_HTTP_CONNECTTIMEOUT':'15','GDAL_HTTP_TIMEOUT':'90','GDAL_HTTP_MAX_RETRY':'2'}
    dest=Path(dest);temp=dest.with_name(dest.name+'.part.tif');valid=0;total=0
    try:
        with rasterio.Env(**env),rasterio.open(source) as src:
            if not src.crs:raise AcquisitionError('Raster has no CRS. It will not be relabeled or force-imported.')
            if src.count!=1:raise AcquisitionError('Expected a one-band elevation raster, not a rendered image.')
            if src.transform.b or src.transform.d:raise AcquisitionError('Rotated UK source raster requires explicit preprocessing; not silently resampled.')
            from exus_resolution_policy import raster_spacing_m
            checked_spacing = raster_spacing_m(src,bbox)
            supplied = source_metadata or {}
            if supplied.get('require_float') and not src.dtypes[0].startswith('float'):
                raise AcquisitionError('Provider returned styled/integer imagery where raw floating-point elevations were required.')
            from exus_france_crs import resolve_raster_crs
            effective_crs, crs_audit = resolve_raster_crs(src, supplied, printf)
            from exus_service_raster import validate_extent
            validate_extent(src,supplied,printf)
            box=projected_bounds(bbox,effective_crs,printf)
            if not intersects(box,src.bounds):return None,{}
            win=from_bounds(*box,transform=src.transform)
            c0=max(0,math.floor(win.col_off));r0=max(0,math.floor(win.row_off))
            c1=min(src.width,math.ceil(win.col_off+win.width));r1=min(src.height,math.ceil(win.row_off+win.height))
            win=Window(c0,r0,c1-c0,r1-r0)
            if win.width<=0 or win.height<=0:return None,{}
            if win.width*win.height>150_000_000:raise AcquisitionError('Raster window exceeds the course-sized memory limit.')
            profile={'driver':'GTiff','width':int(win.width),'height':int(win.height),'count':1,
                     'dtype':'float32','crs':effective_crs,'transform':src.window_transform(win),
                     'nodata':-9999.,'compress':'deflate','tiled':True,'blockxsize':256,'blockysize':256,'BIGTIFF':'IF_SAFER'}
            printf('ex-US raster crop: %d x %d at native spacing %s; %s'%(win.width,win.height,src.res,effective_crs))
            with rasterio.open(temp,'w',**profile) as dst:
                for y in range(0,int(win.height),128):
                    check_cancel(cancel);h=min(128,int(win.height)-y)
                    arr=src.read(1,window=Window(c0,r0+y,int(win.width),h),masked=True).astype('float32')
                    # Apply explicit raster scale/offset, if any, before the existing DEM importer.
                    scale=src.scales[0] if src.scales else 1.;offset=src.offsets[0] if src.offsets else 0.
                    vals=arr.filled(np.nan)*scale+offset;good=np.isfinite(vals)
                    valid+=int(good.sum());total+=vals.size
                    vals[~good]=-9999.;dst.write(vals,1,window=Window(0,y,int(win.width),h))
                    if y==0 or (y//128)%8==0 or y+h==int(win.height):
                        printf('ex-US raster window: %d%%'%round(100*(y+h)/win.height))
                dst.update_tags(**src.tags())
                if crs_audit:
                    dst.update_tags(TGC_EXUS_ORIGINAL_CRS=src.crs.to_wkt(),
                                    TGC_EXUS_CRS_VALIDATION=crs_audit['crs_validation'])
                dst.update_tags(TGC_UK_SOURCE=str(source),TGC_UK_CROP='native-grid window; no resampling')
            metadata={'verified_source_grid_spacing_m':list(checked_spacing),'crs':effective_crs.to_wkt(),'resolution':list(src.res),'valid_cells':valid,'cells':total,
                      'valid_fraction':valid/max(1,total),'bounds':list(rasterio.windows.bounds(win,src.transform))}
            metadata.update(crs_audit)
        if valid==0:temp.unlink();return None,metadata
        os.replace(temp,dest)
        if valid<total:printf('NOTICE: raster window contains %.1f%% NoData; no coverage is invented.'%(100*(1-valid/total)))
        return dest,metadata
    finally:
        if temp.exists():temp.unlink()


def crop_points(source,dest,bbox,printf=print,cancel=None):
    import laspy
    dest=Path(dest);part=dest.with_name(dest.stem+'.part.las');retained=0;classes={};count=0
    try:
        with laspy.open(source) as reader:
            header=copy.deepcopy(reader.header)
            source_points=int(reader.header.point_count)
            crs=header.parse_crs()
            if crs is None:raise AcquisitionError('Point-cloud CRS is missing. No forced EPSG or unit guessing is applied.')
            if not crs.is_projected:raise AcquisitionError('Expected projected LAS/LAZ coordinates; use local-data processing for this source.')
            box=projected_bounds(bbox,crs,printf)
            if not intersects(box,(header.mins[0],header.mins[1],header.maxs[0],header.maxs[1])):return None,{}
            with laspy.open(part,mode='w',header=header,do_compress=False) as writer:
                for pts in reader.chunk_iterator(500000):
                    check_cancel(cancel);count+=len(pts)
                    keep=(np.asarray(pts.x)>=box[0])&(np.asarray(pts.x)<=box[2])&(np.asarray(pts.y)>=box[1])&(np.asarray(pts.y)<=box[3])
                    if keep.any():
                        selected=pts[keep];writer.write_points(selected);retained+=len(selected)
                        vals,nums=np.unique(np.asarray(selected.classification),return_counts=True)
                        for v,n in zip(vals,nums):classes[str(int(v))]=classes.get(str(int(v)),0)+int(n)
                    printf('ex-US point-cloud crop: %d%%; %s retained'%(round(100*count/max(1,source_points)),format(retained,',')))
            meta={'crs':crs.to_wkt(),'points':retained,'source_points':source_points,'classes':classes}
        if retained==0:part.unlink();return None,meta
        os.replace(part,dest)
        if not any(classes.get(str(k),0) for k in (3,4,5)):
            printf('NOTICE: no classified vegetation returns in this subset. Unclassified points may exist; tree detection quality is not guaranteed.')
        return dest,meta
    finally:
        if part.exists():part.unlink()


def download(dataset,bbox,project_dir,osm_file='',cancel=None,printf=print,http=None):
    """Publish only a complete acquisition folder. Existing project output is untouched."""
    from exus_resolution_policy import validate_dataset, validate_outputs, VERSION as POLICY_VERSION
    validate_dataset(dataset)
    bbox=validate_bbox(bbox);project=Path(project_dir).resolve()
    if not project.is_dir():raise AcquisitionError('Working project folder no longer exists.')
    if not dataset.assets:raise AcquisitionError('No downloadable assets in the selected collection.')
    if len(dataset.assets)>MAX_TILES:raise AcquisitionError('More than 500 tiles selected; reduce the OSM extent.')
    root=project/storage_folder(dataset.region);root.mkdir(exist_ok=True)
    from exus_service_raster import (service_kind, prepare_services, cached_transfer,
                                     VERSION as SERVICE_VERSION)
    dataset=copy.deepcopy(dataset)  # Probe negotiation must not mutate GUI selection.
    fingerprint=[dataset.id,bbox,[(a.url,a.bytes) for a in dataset.assets],POLICY_VERSION]
    if any(service_kind(a) for a in dataset.assets):fingerprint.append(SERVICE_VERSION)
    if dataset.metadata:fingerprint.append(dataset.metadata)
    key=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()[:16]
    final=root/(re.sub('[^A-Za-z0-9_-]+','_',dataset.region+'_'+dataset.kind)+'_'+key)
    manifest_path=final/'UK_DOWNLOAD.json'
    if manifest_path.is_file():
        try:
            m=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            files=[final/p['path'] for p in m['outputs']]
            if m.get('complete') and all(p.is_file() and p.stat().st_size==e['bytes'] and file_digest(p)==e['sha256'] for p,e in zip(files,m['outputs'])):
                validate_outputs([(p,{}) for p in files],bbox,dataset)
                printf('ex-US download: reusing the checked, complete acquisition '+str(final))
                return DownloadResult(str(project),str(final/'data'),dataset.kind,[str(p) for p in files],str(manifest_path),m.get('warnings',[]))
        except Exception:pass
        raise AcquisitionError('Existing ex-US acquisition is incomplete or modified. It is preserved; rename that acquisition folder before retrying.')
    if final.exists():raise AcquisitionError('Existing ex-US acquisition folder is incomplete; it is preserved.')
    stage=root/('.partial_'+key+'_'+uuid.uuid4().hex[:8]);(stage/'data').mkdir(parents=True)
    own=http is None;s=http or session();records=[];warnings=[]
    try:
        dataset=prepare_services(dataset,root,stage,s,cancel,printf)
        for index,asset in enumerate(dataset.assets,1):
            check_cancel(cancel);printf('ex-US acquisition tile %d/%d: %s'%(index,len(dataset.assets),asset.name))
            if asset.transport=='cog':
                p,info=crop_raster(asset.url,stage/'data'/('tile_%04d.tif'%index),bbox,printf,cancel,s,source_metadata=asset.metadata)
                if p:records.append((p,info))
            elif asset.transport=='gsi_png':
                from exus_lidar_sources import gsi_raster
                raw_tile=stage/('gsi_%04d.tif'%index)
                raw=gsi_raster(asset,raw_tile,s,cancel,printf)
                if raw is not None:
                    p,info=crop_raster(raw,stage/'data'/('tile_%04d.tif'%index),bbox,printf,cancel)
                    if p:records.append((p,info))
                    raw_tile.unlink()
                else:
                    warnings.append('GSI unavailable/NoData tile: '+asset.name)
            elif asset.transport=='file':
                archive=(cached_transfer(asset,stage/('source_%04d.bin'%index),root,s,cancel,printf)
                         if service_kind(asset) else
                         transfer(asset,stage/('source_%04d.bin'%index),cancel,printf,s))
                members=unpack(archive,stage/('unpacked_%04d'%index),dataset.kind,cancel)
                for j,source in enumerate(members,1):
                    check_cancel(cancel)
                    dest=stage/'data'/('tile_%04d_%04d'%(index,j)+('.tif' if dataset.kind=='dtm' else '.las'))
                    p,info=(crop_raster(source,dest,bbox,printf,cancel,source_metadata=asset.metadata) if dataset.kind=='dtm' else crop_points(source,dest,bbox,printf,cancel))
                    if p:records.append((p,info))
                archive.unlink();shutil.rmtree(stage/('unpacked_%04d'%index))
            else:raise AcquisitionError('Unsupported acquisition transport: '+str(asset.transport))
        if not records:raise AcquisitionError('No usable data inside the course extent. The source may have no coverage here; no heightmap was changed.')
        check_cancel(cancel)
        if dataset.kind=='dtm' and dataset.metadata.get('local_utm'):
            from exus_raster import normalize
            records=[normalize(p,bbox,dataset,info,printf,cancel) for p,info in records]
        validate_outputs(records,bbox,dataset)
        if dataset.kind=='dtm':
            # The source may cover only part of the selection. Do not claim complete national coverage.
            warnings.append('Intersecting data was downloaded; inspect the preview for coverage gaps.')
        outputs=[{'path':p.relative_to(stage).as_posix(),'bytes':p.stat().st_size,'sha256':file_digest(p),'metadata':info} for p,info in records]
        manifest={'version':VERSION,'resolution_policy':POLICY_VERSION,'complete':True,'dataset':asdict(dataset),'bbox_wgs84':list(bbox),
                  'osm_file':str(osm_file),'project_dir':str(project),'buffer_m':DEFAULT_BUFFER_M,
                  'outputs':outputs,'warnings':warnings,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        (stage/'UK_DOWNLOAD.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        os.replace(stage,final)
        printf('ex-US data ready: '+str(final/'data')+'. Existing heightmap and mask have not been overwritten.')
        return DownloadResult(str(project),str(final/'data'),dataset.kind,[str(final/o['path']) for o in outputs],str(final/'UK_DOWNLOAD.json'),warnings)
    finally:
        if own:s.close()
        if stage.exists():shutil.rmtree(stage,ignore_errors=True)

def storage_folder(region):
    return 'UK_Data' if region in ('England','Scotland','Wales','Northern Ireland') else 'ExUS_Data'

def support_notice(region,kind):
    from exus_lidar_sources import mode_notice
    return mode_notice(region,kind)


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description='ex-US acquisition diagnostics (no course generation).')
    p.add_argument('--osm',required=True);p.add_argument('--region',choices=REGIONS,default='Auto')
    p.add_argument('--kind',choices=('all','dtm','pointcloud'),default='all')
    p.add_argument('--output',default='UK_catalogue.json')
    a=p.parse_args();bbox=course_bbox(a.osm);datasets,errors=discover(bbox,a.region,a.kind)
    Path(a.output).write_text(json.dumps({'bbox':bbox,'datasets':[asdict(d) for d in datasets],'source_errors':errors},indent=2),encoding='utf-8')
    print('Saved catalogue diagnostics:',a.output)
    if not datasets:raise SystemExit(2)


if __name__=='__main__':main()
