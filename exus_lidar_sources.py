"""Isolated ex-US acquisition adapters. No changes to CFS/import transformations.

Official interfaces: Swiss STAC; NRCan STAC; IGN WCS 2.0.1; GSI PNG DEM tiles.
Australia/Mexico expose official portal handoff only, not invented download APIs.
"""
from __future__ import annotations
import io
import math
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin, urlencode

import numpy as np
import pyproj
import uk_lidar_downloader as u

VERSION='TGC_BETA7_EXUS_SOURCES_V1'
REGIONS = ('Auto', 'Australia', 'Canada', 'England', 'Finland', 'France', 'Germany', 'Japan', 'Mexico', 'Netherlands', 'New Zealand', 'Northern Ireland', 'Poland', 'Scotland', 'Spain', 'Switzerland', 'Wales')
PROVIDERS = {'Spain': 'https://centrodedescargas.cnig.es/CentroDescargas/', 'Switzerland': 'https://www.swisstopo.admin.ch/en/download-geodata-swisstopo', 'Australia': 'https://elevation.fsdf.org.au/', 'Canada': 'https://geo.ca/elevation/', 'Mexico': 'https://www.inegi.org.mx/app/geo2/elevacionesmex/', 'Japan': 'https://maps.gsi.go.jp/', 'Finland': 'https://paituli.csc.fi/download?data_id=mml_korkeusmalli_2m_all_tif_euref', 'France': 'https://cartes.gouv.fr/rechercher-une-donnee/dataset/IGNF_RGE-ALTI', 'Germany': 'https://www.bezreg-koeln.nrw.de/geobasis-nrw/produkte-und-dienste/hoehenmodelle/digitale-gelaendemodelle/digitales-gelaendemodell', 'Netherlands': 'https://www.pdok.nl/introductie/-/article/actueel-hoogtebestand-nederland-ahn', 'New Zealand': 'https://data.linz.govt.nz/layer/121859-new-zealand-lidar-1m-dem/', 'Poland': 'https://www.geoportal.gov.pl/en/services/download-service-wcs/'}
# Routing envelopes are NOT coverage claims or political boundary datasets.
AREAS = {'England': [(-6.5, 49.8, 2.2, 55.9)], 'Scotland': [(-8.3, 54.6, -0.6, 61.1)], 'Wales': [(-5.6, 51.3, -2.3, 53.6)], 'Northern Ireland': [(-8.3, 53.95, -5.4, 55.5)], 'Spain': [(-9.5, 35.7, 4.5, 44), (-18.5, 27.4, -13.2, 29.6), (-5.5, 35, -2.8, 35.9)], 'Switzerland': [(5.8, 45.7, 10.6, 47.9)], 'Australia': [(112, -44, 154.5, -10)], 'Canada': [(-141, 41.5, -52, 84)], 'Mexico': [(-118.5, 14.3, -86, 32.8)], 'Japan': [(122, 20, 154.5, 46)], 'Finland': [(19.0, 59.0, 32.0, 70.2)], 'France': [(-5.2, 41.3, 9.7, 51.2)], 'Germany': [(5.8, 47.2, 15.1, 55.2)], 'Netherlands': [(3.2, 50.7, 7.3, 53.7)], 'New Zealand': [(166.0, -47.5, 179.9, -34.0)], 'Poland': [(14.0, 49.0, 24.3, 55.0)]}
SWISS='https://data.geo.admin.ch/api/stac/v0.9'
CANADA='https://datacube.services.geo.ca/stac/api'
SPAIN='https://servicios.idee.es/wcs-inspire/mdt'
GSI='https://cyberjapandata.gsi.go.jp/xyz/'
GSI_LAYERS=(('dem1a_png',17,1,'DEM1A — LiDAR-derived 1 m'),
            ('dem5a_png',15,5,'DEM5A — LiDAR-derived 5 m'),
            ('dem5b_png',15,5,'DEM5B — photogrammetric 5 m'),
            ('dem5c_png',15,5,'DEM5C — photogrammetric 5 m'))
PORTAL_ONLY={'Australia':
    'Australia: use the official ELVIS portal to select the course area and obtain provider files. '
    'Automatic ELVIS ordering/download is not implemented in this build. Use the normal local LAS/LAZ or GeoTIFF import afterward.',
    'Mexico':
    'Mexico: use INEGI to select Terreno (not Superficie), available resolution and coverage. '
    'Automatic INEGI tile discovery/download is not implemented in this build. Use georeferenced local GeoTIFF/LAS/LAZ afterward; no national high-resolution coverage is assumed.'}


def validate_bbox(bbox):
    try:b=tuple(float(v) for v in bbox)
    except (ValueError,TypeError):raise u.AcquisitionError('Invalid acquisition bounding box.')
    if len(b)!=4 or not all(math.isfinite(v) for v in b):raise u.AcquisitionError('Invalid acquisition bounding box.')
    w,s,e,n=b
    if not(-180<=w<e<=180 and -85<s<n<85):
        raise u.AcquisitionError('Invalid or dateline-crossing OSM extent; select a smaller local area.')
    geod=pyproj.Geod(ellps='WGS84')
    _,_,width=geod.inv(w,(s+n)/2,e,(s+n)/2)
    _,_,height=geod.inv((w+e)/2,s,(w+e)/2,n)
    if width*height>u.MAX_AREA_KM2*1e6 or max(width,height)>100000:
        raise u.AcquisitionError('Acquisition area exceeds the 100 km² / 100 km span limit. Use a course-sized OSM export.')
    if not any(u.intersects(b,box) for boxes in AREAS.values() for box in boxes):
        raise u.AcquisitionError('OSM lies outside the supported ex-US country envelopes. Use USGS or local data.')
    return b


def regions_for_bbox(bbox,region='Auto'):
    if region not in REGIONS:raise u.AcquisitionError('Unknown country/region: '+str(region))
    if region!='Auto':
        if not any(u.intersects(bbox,box) for box in AREAS[region]):
            raise u.AcquisitionError('Selected OSM does not intersect the '+region+' routing extent.')
        return [region]
    center=((bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2)
    if -8.3<center[0]<-5.4 and 53.95<center[1]<55.5:return ['Northern Ireland']
    return [name for name,boxes in AREAS.items() if any(u.intersects(bbox,b) for b in boxes)]


def mode_notice(region,kind):
    if region in PORTAL_ONLY:return 'PROVIDER PORTAL ONLY — '+PORTAL_ONLY[region]
    if region=='Northern Ireland':return 'Northern Ireland: automatic acquisition is not implemented; use the official portal and local-file import.'
    if kind=='pointcloud' and region in ('Wales','Spain','Canada','Japan','Finland','France','Germany','Netherlands','New Zealand','Poland'):
        return region+': this adapter supplies terrain rasters only, not raw LiDAR points. Select Terrain only or use local point-cloud files.'
    return ''


def _stac_items(s,base,collection,bbox,cancel=None,printf=print):
    url=base+'/collections/'+collection+'/items'
    params={'bbox':','.join('%.8f'%v for v in bbox),'limit':100}
    seen_pages=set();items={};notes=[]
    for page in range(50):
        u.check_cancel(cancel)
        identity=(url,str(params))
        if identity in seen_pages:
            notes.append('Repeated STAC pagination link; catalogue selection is partial.');break
        seen_pages.add(identity)
        try:
            obj=u._json(s,'GET',url,cancel,params=params)
            if not isinstance(obj,dict) or not isinstance(obj.get('features'),list):
                raise u.AcquisitionError('Provider returned no STAC feature list.')
            for item in obj['features']:
                if isinstance(item,dict) and isinstance(item.get('assets'),dict):
                    key=str(item.get('id') or '')
                    if key:items[key]=item
            next_link=next((l for l in obj.get('links',[]) if l.get('rel')=='next'),None)
            printf('%s: catalogue page %d; %d item(s).' % (collection,page+1,len(items)))
            if not next_link:break
            if next_link.get('method','GET').upper()!='GET':
                raise u.AcquisitionError('Unsupported STAC next-page method; retained selection is partial.')
            url=u._safe_url(urljoin(url,next_link['href']));params=None
            # Never send a provider query body/authentication to a different host.
            if urlparse(url).hostname!=urlparse(base).hostname:
                raise u.AcquisitionError('STAC pagination switched host; stopped before following it.')
        except u.Cancelled:raise
        except Exception as exc:
            if not items:raise
            notes.append('Incomplete STAC search: '+str(exc));break
    else:notes.append('STAC page limit reached; dataset selection is partial.')
    return list(items.values()),notes


def _date(item):
    p=item.get('properties') or {}
    return str(p.get('datetime') or p.get('start_datetime') or p.get('end_datetime') or '')


def _asset_resolution(asset,item,default=None):
    p=item.get('properties') or {}
    for v in (asset.get('gsd'),asset.get('eo:gsd'),p.get('gsd'),p.get('eo:gsd'),default):
        try:
            f=float(v)
            if math.isfinite(f) and f>0:return f
        except (ValueError,TypeError):pass
    return None


def parse_swiss(items,kind):
    """Separate resolutions and EPSGs, latest dated version for each footprint.
    Do not mix point-cloud formats in the same selected collection.
    """
    latest={}
    for item in items:
        box=item.get('bbox')
        if not isinstance(box,list) or len(box)<4:continue
        footprint=tuple(round(float(v),7) for v in (box[:4] if len(box)==4 else [box[0],box[1],box[3],box[4]]))
        for key,a in item.get('assets',{}).items():
            href=a.get('href','');name=urlparse(href).path.rsplit('/',1)[-1]
            fmt='zip' if name.lower().endswith('.zip') else 'laz' if name.lower().endswith(('.laz','.copc')) else 'las' if name.lower().endswith('.las') else 'tif' if name.lower().endswith(('.tif','.tiff')) else ''
            if (kind=='dtm' and fmt!='tif') or (kind=='pointcloud' and fmt not in ('zip','laz','las')):continue
            if any(v in (str(key)+' '+str(a.get('title',''))).lower() for v in ('hillshade','thumbnail','preview')):continue
            epsg=a.get('proj:epsg') or (item.get('properties') or {}).get('proj:epsg')
            if not epsg:
                m=re.search(r'_(2056|21781)_',name);epsg=int(m.group(1)) if m else None
            if epsg and int(epsg)!=2056:continue
            # swissALTI3D assets encode grid resolution in their names when STAC lacks GSD.
            res=_asset_resolution(a,item)
            if res is None:
                m=re.search(r'_(0\.5|2)(?:_|m)',name);res=float(m.group(1)) if m else None
            signature=(footprint,res,epsg,fmt)
            if signature not in latest or _date(item)>_date(latest[signature][0]):latest[signature]=(item,a,res,fmt)
    groups={}
    for item,a,res,fmt in latest.values():
        name='swissALTI3D' if kind=='dtm' else 'swissSURFACE3D'
        resolution=('%g m'%res) if res is not None else ''
        key=(resolution,fmt)
        ds=groups.setdefault(key,u.Dataset('swiss:'+name+':'+resolution+':'+fmt,'Switzerland',name+' — latest per tile ('+fmt+')',kind,'',resolution,
            'swisstopo open geodata terms; attribution required','Source: Federal Office of Topography swisstopo',PROVIDERS['Switzerland'],
            notes='Official STAC assets; latest version per tile. Different tiles may have different acquisition dates. File headers remain authoritative.'))
        url=u._safe_url(a['href']);size=a.get('file:size')
        try:size=int(size) if size is not None else None
        except (ValueError,TypeError):size=None
        if url not in {v.url for v in ds.assets}:ds.assets.append(u.Asset(url,urlparse(url).path.rsplit('/',1)[-1],size))
        dates=ds.metadata.setdefault('tile_dates',[])
        if _date(item):dates.append(_date(item))
    for ds in groups.values():
        years=sorted({d[:4] for d in ds.metadata.get('tile_dates',[])})
        ds.year=('–'.join([years[0],years[-1]]) if len(years)>1 else years[0]) if years else ''
    return list(groups.values())


def switzerland(s,bbox,kind,cancel,printf):
    all_ds=[];errors=[]
    for product,col in [('dtm','ch.swisstopo.swissalti3d'),('pointcloud','ch.swisstopo.swisssurface3d')]:
        if kind not in ('all',product):continue
        items,notes=_stac_items(s,SWISS,col,bbox,cancel,printf)
        all_ds.extend(parse_swiss(items,product));errors+=notes
    return all_ds,errors


def canada(s,bbox,kind,cancel,printf):
    if kind=='pointcloud':return [],[mode_notice('Canada',kind)]
    result=[];errors=[]
    for resolution in (1,2):
        col='hrdem-mosaic-%dm'%resolution
        try:items,notes=_stac_items(s,CANADA,col,bbox,cancel,printf);errors+=notes
        except u.Cancelled:raise
        except Exception as exc:errors.append(col+': '+str(exc));continue
        ds=u.Dataset('canada:'+col,'Canada','NRCan HRDEM bare-earth mosaic %d m (window only)'%resolution,'dtm','',str(resolution)+' m',
            'Open Government Licence – Canada','Contains information licensed under the Open Government Licence – Canada. Natural Resources Canada.',
            PROVIDERS['Canada'],notes='Only the DTM asset is read. No full national/mosaic download. NoData remains NoData. Reprojected to a local metric course grid before import.',metadata={'output_resolution_m':resolution,'local_utm':True})
        for item in items:
            a=item['assets'].get('dtm')
            if not isinstance(a,dict) or not a.get('href'):continue
            url=u._safe_url(a['href'])
            if url not in {x.url for x in ds.assets}:ds.assets.append(u.Asset(url,str(item['id']),None,'cog'))
        if ds.assets:result.append(ds)
    return result,errors


def _xml(s,url,params,cancel):
    u.check_cancel(cancel)
    with s.get(url,params=params,timeout=(15,90)) as r:
        r.raise_for_status();raw=r.content
    if len(raw)>8*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise u.AcquisitionError('Unsafe or oversized WCS metadata.')
    root=ET.fromstring(raw)
    if 'Exception' in root.tag:
        raise u.AcquisitionError('WCS service error: '+' '.join(root.itertext())[:500])
    return root


def spain(s,bbox,kind,cancel,printf):
    if kind=='pointcloud':return [],[mode_notice('Spain',kind)]
    printf('Spain: reading official IGN MDT WCS capabilities; only 5 m terrain is offered.')
    caps=_xml(s,SPAIN,{'service':'WCS','version':'2.0.1','request':'GetCapabilities'},cancel)
    if caps.tag.split('}')[-1]!='Capabilities':raise u.AcquisitionError('Unrecognized IGN WCS capabilities.')
    result=[];errors=[]
    for summary in caps.findall('.//{*}CoverageSummary'):
        cid=summary.findtext('{*}CoverageId','')
        m=re.fullmatch(r'(?:.*:)?Elevacion(\d+)_5',cid)
        if not m:continue
        epsg=int(m.group(1))
        if epsg not in (25830,4083):continue  # No geographic-grid or unrelated coarse product shortcut.
        target_region=(-18.5,27.4,-13.2,29.6) if epsg==4083 else (-9.5,35,4.5,44)
        if not u.intersects(bbox,target_region):continue
        try:
            desc=_xml(s,SPAIN,{'service':'WCS','version':'2.0.1','request':'DescribeCoverage','coverageId':cid},cancel)
            env=desc.find('.//{*}Envelope')
            if env is None:raise u.AcquisitionError('No WCS envelope/axis information.')
            crs=pyproj.CRS.from_user_input(env.attrib.get('srsName',''))
            if crs.to_epsg()!=epsg:raise u.AcquisitionError('Coverage CRS differs from its declared identifier.')
            axes=env.attrib.get('axisLabels','').split()
            if len(axes)!=2:raise u.AcquisitionError('Cannot resolve WCS subset axes.')
            # Determine which declared axis is easting; do not assume axis order.
            if axes[0].lower() in ('x','e','easting','east') and axes[1].lower() in ('y','n','northing','north'):
                ix,iy=0,1
            elif axes[1].lower() in ('x','e','easting','east') and axes[0].lower() in ('y','n','northing','north'):
                ix,iy=1,0
            else:raise u.AcquisitionError('Unsupported WCS axis labels: '+' '.join(axes))
            lo=list(map(float,env.findtext('{*}lowerCorner','').split()));hi=list(map(float,env.findtext('{*}upperCorner','').split()))
            box=u.projected_bounds(bbox,crs,printf)
            extent=(lo[ix],lo[iy],hi[ix],hi[iy])
            if not u.intersects(box,extent):continue
            x0,y0,x1,y1=max(box[0],extent[0]),max(box[1],extent[1]),min(box[2],extent[2]),min(box[3],extent[3])
            params=[('service','WCS'),('version','2.0.1'),('request','GetCoverage'),('coverageId',cid),('format','image/tiff'),
                    ('subset','%s(%.3f,%.3f)'%(axes[ix],x0,x1)),('subset','%s(%.3f,%.3f)'%(axes[iy],y0,y1))]
            ds=u.Dataset('spain-wcs:'+cid,'Spain','IGN / CNIG MDT05 — 5 m terrain (WCS window)','dtm','','5 m',
                'CC BY 4.0 — IGN/CNIG','Source: IGN / CNIG, PNOA-LiDAR MDT05',PROVIDERS['Spain'],
                [u.Asset(SPAIN+'?'+urlencode(params),cid+'.tif',None,'file')],
                '5 m source, not 1 m terrain or raw LiDAR. Download is a bounded WCS coverage, not a rendered WMS map.',
                {'output_resolution_m':5,'local_utm':True})
            result.append(ds)
        except u.Cancelled:raise
        except Exception as exc:errors.append(cid+': '+str(exc))
    if not result and not errors:errors.append('IGN service did not advertise a supported 5 m projected coverage for this area; consult CNIG for other products.')
    return result,errors


def xyz_tiles(bbox,z):
    w,s,e,n=bbox;count=2**z
    xx=lambda lon:(lon+180)/360*count
    yy=lambda lat:(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*count
    x0,x1=math.floor(xx(w)),math.ceil(xx(e))-1
    y0,y1=math.floor(yy(n)),math.ceil(yy(s))-1
    if (x1-x0+1)*(y1-y0+1)>u.MAX_TILES:raise u.AcquisitionError('GSI tile count exceeds the course-sized limit; reduce the OSM extent.')
    return [(x,y) for y in range(y0,y1+1) for x in range(x0,x1+1)]


def japan(s,bbox,kind,cancel,printf):
    if kind=='pointcloud':return [],[mode_notice('Japan',kind)]
    u.check_cancel(cancel)
    # Template availability is explicitly provisional. No HEAD/centre-tile shortcut
    # may claim the whole course is covered. 404 and all-NoData are checked per tile.
    printf('Japan: documented GSI elevation-tile products. Availability is checked per tile during download, not inferred from a national coverage box.')
    output=[];notes=[]
    for layer,z,res,title in GSI_LAYERS:
        try:tiles=xyz_tiles(bbox,z)
        except u.AcquisitionError as exc:
            note=title+': '+str(exc);notes.append(note);printf('NOTICE: '+note);continue
        assets=[u.Asset(GSI+'%s/%d/%d/%d.png'%(layer,z,x,y),f'{layer}_{z}_{x}_{y}',None,'gsi_png',{'x':x,'y':y,'z':z}) for x,y in tiles]
        output.append(u.Dataset('japan-gsi:'+layer,'Japan','GSI '+title+' [coverage not yet checked]','dtm','',str(res)+' m source',
            'GSI content terms; attribution and applicable reuse requirements','Source: Geospatial Information Authority of Japan (GSI elevation tiles)',
            PROVIDERS['Japan'],assets,'Elevation-encoded PNG, not a screenshot. No silent coarser fallback; 404/NoData gaps remain gaps. Converted to local metric GeoTIFF before import.',
            {'output_resolution_m':res,'local_utm':True,'coverage_provisional':True,'source_layer':layer}))
    return output,notes


def decode_gsi_png(raw):
    from PIL import Image
    if len(raw)>4*1024*1024:raise u.AcquisitionError('Oversized GSI elevation tile.')
    with Image.open(io.BytesIO(raw)) as im:
        if im.format!='PNG' or im.size!=(256,256) or im.mode not in ('RGB','RGBA'):
            raise u.AcquisitionError('GSI tile is not a 256×256 RGB elevation PNG.')
        a=np.asarray(im.convert('RGB'),dtype=np.int32)
    v=a[:,:,0]*65536+a[:,:,1]*256+a[:,:,2]
    result=np.where(v>2**23,v-2**24,v).astype('float32')*.01
    result[v==2**23]=np.nan
    return result


def gsi_raster(asset,dest,http,cancel,printf):
    import rasterio
    from rasterio.transform import from_origin
    u.check_cancel(cancel)
    with http.get(asset.url,timeout=(15,90)) as r:
        if r.status_code==404:
            printf('NOTICE: GSI tile not available: '+asset.name);return None
        r.raise_for_status();arr=decode_gsi_png(r.content)
    u.check_cancel(cancel)
    if not np.isfinite(arr).any():
        printf('NOTICE: GSI tile contains only NoData: '+asset.name);return None
    x,y,z=(int(asset.metadata[k]) for k in ('x','y','z'))
    if not (0<=x<2**z and 0<=y<2**z):raise u.AcquisitionError('Invalid GSI tile coordinates.')
    half=20037508.342789244;size=2*half/(2**z)
    arr[~np.isfinite(arr)]=-9999.
    with rasterio.open(dest,'w',driver='GTiff',width=256,height=256,count=1,dtype='float32',crs='EPSG:3857',
                       transform=from_origin(-half+x*size,half-y*size,size/256,size/256),nodata=-9999.,compress='deflate') as ds:
        ds.write(arr,1);ds.update_tags(SOURCE_URL=asset.url,ELEVATION_UNITS='metres',TGC_INTERMEDIATE='Web Mercator must be reprojected before course import')
    return dest


def country_discover(region,s,bbox,kind,cancel,printf):
    from exus_additional_countries import REGIONS as extra_regions, discover as extra_discover
    if region in extra_regions:return extra_discover(region,s,bbox,kind,cancel,printf)
    if region in PORTAL_ONLY:
        u.check_cancel(cancel);printf('NOTICE: '+PORTAL_ONLY[region]);return [],['PORTAL ONLY: '+PORTAL_ONLY[region]]
    return {'Switzerland':switzerland,'Canada':canada,'Spain':spain,'Japan':japan}[region](s,bbox,kind,cancel,printf)
