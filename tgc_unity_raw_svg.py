"""Unity RAW + SVG -> co-registered local-use GeoTIFF / OSM.
TGC_UNITY_RAW_SVG_V1. Unknown SVG types are retained, not silently invented.
No downloads, no registration, no original-file changes. Synthetic UTM only.
"""
from __future__ import annotations
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import numpy as np
from tgc_unity_svg_paths import flatten_path, matrix, NUMBER

MARKER='TGC_UNITY_RAW_SVG_V1'
SVG_NS='http://www.w3.org/2000/svg'
LABEL='{http://www.inkscape.org/namespaces/inkscape}label'
LABEL2='{http://www.inkscape.org/namespaces/inkscape}label'
KINDS=('fairway','green','tee','bunker','rough','water','cartpath','mulch','wood','hole','unclassified','skip')
ORIENTATIONS=('as_stored','flip_horizontal','flip_vertical','rotate_180','rotate_90','rotate_270','transpose','anti_transpose')


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def inspect_raw(path):
    size=Path(path).stat().st_size
    candidates=[]
    for bits in (16,8):
        b=bits//8;n=math.isqrt(size//b)
        if n*n*b==size and n>=2:candidates.append({'bits':bits,'rows':n,'cols':n})
    stats={}
    if any(c['bits']==16 for c in candidates):
        c=next(c for c in candidates if c['bits']==16)
        for order,dt in [('little','<u2'),('big','>u2')]:
            a=np.memmap(path,dtype=dt,mode='r',shape=(c['rows'],c['cols']))
            stride=max(1,c['rows']//512);q=np.array(a[::stride,::stride],dtype=float)
            d=np.r_[np.abs(np.diff(q,axis=0)).ravel(),np.abs(np.diff(q,axis=1)).ravel()]
            stats[order]={'neighbor_p90':float(np.percentile(d,90)),'min':int(a.min()),'max':int(a.max())}
        ratios={o:v['neighbor_p90'] for o,v in stats.items()}
        best=min(ratios,key=ratios.get);other='big' if best=='little' else 'little'
        suggested=best if ratios[other]>max(1,ratios[best])*4 else None
    else:suggested=None
    return {'bytes':size,'square_candidates':candidates,'suggested_byte_order':suggested,'byte_order_tests':stats}


def orient(a,name):
    if name=='as_stored':return a
    if name=='flip_horizontal':return np.fliplr(a)
    if name=='flip_vertical':return np.flipud(a)
    if name=='rotate_180':return a[::-1,::-1]
    if name=='rotate_90':return np.rot90(a,1)
    if name=='rotate_270':return np.rot90(a,3)
    if name=='transpose':return a.T
    if name=='anti_transpose':return a.T[::-1,::-1]
    raise ValueError('Unknown RAW orientation '+str(name))


def load_raw(path, settings):
    rows=int(settings['rows']);cols=int(settings['cols']);bits=int(settings.get('bits',16))
    width=float(settings['width_m']);length=float(settings['length_m']);height=float(settings['height_m']);base=float(settings.get('base_elevation_m',0))
    if bits not in (8,16) or rows<2 or cols<2:raise ValueError('RAW needs >=2 rows/columns and 8 or 16 bits')
    if rows*cols>100000000:raise ValueError('RAW exceeds the 100-million-sample safety limit')
    if not all(math.isfinite(x) for x in (width,length,height,base)) or min(width,length,height)<=0:raise ValueError('Terrain dimensions/height must be finite and positive')
    expected=rows*cols*(bits//8)
    if Path(path).stat().st_size!=expected:raise ValueError('RAW byte size does not match dimensions and bit depth (expected '+str(expected)+')')
    order=settings.get('byte_order','little')
    if order not in ('little','big'):raise ValueError('Byte order must be little or big')
    dt=('u1' if bits==8 else ('<u2' if order=='little' else '>u2'))
    a=np.fromfile(path,dtype=dt).reshape(rows,cols)
    a=orient(a,settings.get('orientation','as_stored'))
    # Unity native importer/exporter uses 2**bits, not observed min/max scaling.
    divisor=float(settings.get('normalization_divisor',2**bits))
    if divisor not in (2**bits,2**bits-1):raise ValueError('Unsupported RAW normalization divisor')
    return a.astype(np.float32)*(height/divisor)+base


def bilinear_grid(a,rows,cols):
    """Bilinear values at fractional source row/column centres, edge-clamped."""
    a=np.asarray(a,dtype=np.float32);yy=np.clip(np.asarray(rows,float),0,a.shape[0]-1);xx=np.clip(np.asarray(cols,float),0,a.shape[1]-1)
    yi=np.floor(yy).astype(int);xi=np.floor(xx).astype(int);y1=np.minimum(yi+1,a.shape[0]-1);x1=np.minimum(xi+1,a.shape[1]-1)
    fy=(yy-yi).astype(np.float32)[:,None];fx=(xx-xi).astype(np.float32)[None,:]
    return ((1-fy)*((1-fx)*a[yi[:,None],xi]+fx*a[yi[:,None],x1])+fy*((1-fx)*a[y1[:,None],xi]+fx*a[y1[:,None],x1])).astype(np.float32)


def resample_authored_dem(dem,native_scale,target_scale,printf=print):
    """Pixel-centre surface resampling for tagged Unity rasters only."""
    if target_scale<=native_scale+1e-9:return np.array(dem,dtype=np.float32,copy=True)
    if not np.isfinite(dem).all():raise ValueError('Authored DEM reduction requires a complete finite surface')
    h,w=dem.shape;r=target_scale/native_scale
    rows=(np.arange(int(math.ceil(h/r)))+.5)*r-.5;cols=(np.arange(int(math.ceil(w/r)))+.5)*r-.5
    printf('Unity authored-surface reduction: bilinear; no lower-ground percentile.')
    return bilinear_grid(dem,rows,cols)


def _tag(e):return e.tag.rsplit('}',1)[-1]

def _kind(label):
    s=re.sub('[^a-z]','',label.lower())
    lookup={'fairway':'fairway','fairways':'fairway','green':'green','greens':'green','tee':'tee','tees':'tee','teeboxes':'tee','bunker':'bunker','bunkers':'bunker','rough':'rough','water':'water','waterhazards':'water','ponds':'water','cartpath':'cartpath','cartpaths':'cartpath','mulch':'mulch','mulchareas':'mulch','trees':'wood','woods':'wood','woodland':'wood','holeroutes':'hole','holes':'hole'}
    return lookup.get(s)


def _style(e,inherited):
    s=dict(inherited)
    for k in ('fill','stroke','fill-rule','display','visibility','opacity','fill-opacity','stroke-width'):
        if k in e.attrib:s[k]=e.get(k)
    s.update(dict(x.split(':',1) for x in e.get('style','').split(';') if ':' in x))
    return {k.strip():v.strip() for k,v in s.items()}


def _path_data(e):
    tag=_tag(e)
    def n(k,d=0):return float(e.get(k,d))
    if tag=='path':return e.get('d','')
    if tag in ('polygon','polyline'):
        a=[float(x) for x in re.findall(NUMBER,e.get('points',''))]
        if len(a)<4 or len(a)%2:raise ValueError('Invalid SVG points')
        return 'M '+' '.join(map(str,a))+(' Z' if tag=='polygon' else '')
    if tag=='line':return f'M {n("x1")} {n("y1")} L {n("x2")} {n("y2")}'
    if tag=='rect':
        x,y,w,h=n('x'),n('y'),n('width'),n('height');rx=min(abs(n('rx',e.get('ry',0))),w/2);ry=min(abs(n('ry',e.get('rx',0))),h/2)
        if min(w,h)<=0:return ''
        if rx==0 or ry==0:return f'M{x},{y} h{w} v{h} h{-w} z'
        return f'M{x+rx},{y} H{x+w-rx} A{rx},{ry} 0 0 1 {x+w},{y+ry} V{y+h-ry} A{rx},{ry} 0 0 1 {x+w-rx},{y+h} H{x+rx} A{rx},{ry} 0 0 1 {x},{y+h-ry} V{y+ry} A{rx},{ry} 0 0 1 {x+rx},{y} Z'
    if tag in ('circle','ellipse'):
        x,y=n('cx'),n('cy');rx=n('r') if tag=='circle' else n('rx');ry=n('r') if tag=='circle' else n('ry')
        if min(rx,ry)<=0:return ''
        return f'M{x-rx},{y} A{rx},{ry} 0 1 0 {x+rx},{y} A{rx},{ry} 0 1 0 {x-rx},{y} Z'
    return None


def read_svg(svg_path,width_m,length_m,mapping_rules=None,tolerance=.15,max_step=8):
    from shapely.geometry import Polygon,LineString
    from shapely.ops import unary_union,polygonize
    data=Path(svg_path).read_bytes()
    if len(data)>50*1024*1024:raise ValueError('SVG exceeds 50 MB')
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('SVG external/entity declarations are not supported')
    root=ET.fromstring(data)
    if _tag(root)!='svg':raise ValueError('Not an SVG file')
    vb=[float(x) for x in re.findall(NUMBER,root.get('viewBox',''))]
    if len(vb)!=4 or min(vb[2:])<=0:raise ValueError('SVG needs an explicit valid viewBox')
    scale=np.array([[width_m/vb[2],0,-vb[0]*width_m/vb[2]],[0,length_m/vb[3],-vb[1]*length_m/vb[3]],[0,0,1]])
    rules=mapping_rules or {};features=[];warnings=[];inventory=collections.Counter();groups={}
    blocked={'defs','metadata','namedview','clipPath','mask','symbol','pattern','script','style'}
    def filled_geometry(rings,fillrule):
        # Polygonize ALL rings together; classify faces with SVG nonzero/evenodd winding.
        def winding(pt,ring):
            x,y=pt;v=0
            for a,b in zip(ring,ring[1:]):
                cross=(b[0]-a[0])*(y-a[1])-(x-a[0])*(b[1]-a[1])
                if a[1]<=y<b[1] and cross>0:v+=1
                elif b[1]<=y<a[1] and cross<0:v-=1
            return v
        rings=[np.vstack([p,p[0]]) if not np.array_equal(p[-1],p[0]) else p for p in rings if len(p)>=3]
        if not rings:return Polygon()
        if len(rings)==1:
            p=Polygon(rings[0])
            if p.is_valid:return p
        faces=list(polygonize(unary_union([LineString(p) for p in rings])))
        selected=[]
        for face in faces:
            pt=face.representative_point();ws=sum(winding((pt.x,pt.y),p) for p in rings)
            if (abs(ws)%2 if fillrule=='evenodd' else ws!=0):selected.append(face)
        return unary_union(selected) if selected else Polygon()
    def walk(e,parent_matrix,style,group='Base',kind=None):
        tag=_tag(e)
        if tag in blocked:return
        s=_style(e,style)
        if s.get('display')=='none' or s.get('visibility') in ('hidden','collapse') or float(s.get('opacity','1'))==0:return
        label=next((v for k,v in e.attrib.items() if k.endswith('}label')),None)
        if tag in ('g','svg') and label:group=label;kind=_kind(label) or kind
        mat=parent_matrix@matrix(e.get('transform',''))
        if tag in ('image','use','text','foreignObject'):
            warnings.append('Skipped non-path/external SVG element '+tag+' '+e.get('id',''));return
        if e.get('clip-path') or 'clip-path' in s or e.get('mask') or 'mask' in s:raise ValueError('SVG clipped/masked geometry requires flattening first: '+e.get('id',''))
        d=_path_data(e)
        if d is not None:
            if not d.strip():return
            key=group+'|'+s.get('fill','black').lower();inventory[key]+=1
            classification=rules.get(e.get('id',''),rules.get(key,kind or 'unclassified'))
            if classification not in KINDS:raise ValueError('Unknown feature class '+classification)
            groups[key]=classification
            parts=flatten_path(d,scale@mat,tolerance,max_step)
            if classification=='skip':
                warnings.append('Explicitly skipped '+e.get('id',''));return
            if classification=='hole':
                geom=LineString(parts[0][0])
                # Routes require explicit source data, never infer tee-to-green associations.
                ref=e.get('data-hole') or e.get('data-ref');par=e.get('data-par')
                if not ref or not par:raise ValueError('Hole route '+e.get('id','')+' lacks data-hole/data-par')
            else:geom=filled_geometry([p for p,closed in parts],s.get('fill-rule','nonzero'));ref=par=None
            if geom.is_empty:warnings.append('Empty SVG geometry '+e.get('id',''));return
            if not geom.is_valid:raise ValueError('Invalid filled SVG geometry '+e.get('id',''))
            features.append({'id':e.get('id',f'element{len(features)+1}'),'group':group,'fill':s.get('fill','black'),'kind':classification,'geometry':geom,'hole':ref,'par':par,'subpaths':len(parts)})
        for child in e:walk(child,mat,s,group,kind)
    walk(root,np.eye(3),{'fill':'black'})
    return features,{'viewBox':vb,'physical_svg_units':root.get('width'),'classification_groups':groups,'inventory':dict(inventory),'warnings':warnings,'source_elements':len(features)}


def default_mapping(features,svg_info):
    """Conservative defaults: only trust named groups; caller reviews color exceptions."""
    return dict(svg_info['classification_groups'])


def _polygons(geom):
    if geom.geom_type=='Polygon':return [geom]
    if hasattr(geom,'geoms'):return [p for g in geom.geoms for p in _polygons(g)]
    return []


def _holeless(poly):
    """Partition a filled path with holes for TGC's closed-area cart-path importer.
    Exact polygon coverage is retained; no centerline/width is guessed.
    """
    if not poly.interiors:return [poly]
    from shapely.geometry import LineString
    from shapely.ops import split
    pending=[poly];out=[];limit=0
    while pending:
        p=pending.pop()
        if not p.interiors:out.append(p);continue
        limit+=1
        if limit>5000:raise ValueError('Hole partition limit reached')
        ring=p.interiors[0];x0,y0,x1,y1=ring.bounds;mx=(x0+x1)/2;my=(y0+y1)/2;bx=p.bounds
        cuts=[LineString([(bx[0]-10,my),(bx[2]+10,my)]),LineString([(mx,bx[1]-10),(mx,bx[3]+10)])]
        for cut in cuts:
            pieces=[q for q in split(p,cut).geoms if q.area>1e-8]
            if len(pieces)>1 and sum(len(q.interiors) for q in pieces)<len(p.interiors):pending.extend(pieces);break
        else:raise ValueError('Could not preserve inner rings while partitioning cart-path area')
    return out


def write_osm(path,features,width_m,length_m,epsg=32631,center_e=500000.,center_n=5000000.):
    from pyproj import Transformer
    from shapely.ops import unary_union
    tr=Transformer.from_crs(epsg,4326,always_xy=True);west=center_e-width_m/2;north=center_n+length_m/2
    root=ET.Element('osm',{'version':'0.6','generator':MARKER,'upload':'never'})
    corners=[tr.transform(west+x,north-y) for x,y in [(0,0),(width_m,0),(width_m,length_m),(0,length_m)]]
    ET.SubElement(root,'bounds',{'minlat':str(min(x[1] for x in corners)),'minlon':str(min(x[0] for x in corners)),'maxlat':str(max(x[1] for x in corners)),'maxlon':str(max(x[0] for x in corners))})
    nid=wid=rid=-1;nodes={};way_elements=[];rel_elements=[];counts=collections.Counter();partitions=[];degenerate_parts=[]
    def node(x,y):
        nonlocal nid
        key=(round(x,8),round(y,8))
        if key in nodes:return nodes[key]
        lon,lat=tr.transform(west+x,north-y);id=nid;nid-=1;nodes[key]=id
        ET.SubElement(root,'node',{'id':str(id),'lat':f'{lat:.10f}','lon':f'{lon:.10f}','version':'1','visible':'true'})
        return id
    def way(coords,tags):
        nonlocal wid
        id=wid;wid-=1;e=ET.Element('way',{'id':str(id),'version':'1','visible':'true'})
        for x,y in coords:ET.SubElement(e,'nd',{'ref':str(node(float(x),float(y)))})
        for k,v in tags.items():ET.SubElement(e,'tag',{'k':k,'v':str(v)})
        way_elements.append(e);return id
    tagmap={'fairway':{'golf':'fairway'},'green':{'golf':'green'},'tee':{'golf':'tee'},'bunker':{'golf':'bunker'},'rough':{'golf':'rough'},'water':{'natural':'water','golf':'water_hazard'},'cartpath':{'golf':'cartpath','highway':'path','golf_cart':'yes','area':'yes'},'mulch':{'surface':'woodchips','area':'yes'},'wood':{'natural':'wood'},'unclassified':{'note':'Unclassified SVG outline; assign a real feature before mapping'}}
    for feature in features:
        k=feature['kind'];g=feature['geometry'];tags={'source':'local Unity/SVG conversion; NOT surveyed/geographic'}
        if k=='hole':
            tags.update({'golf':'hole','ref':str(feature['hole']),'par':str(feature['par'])});way(g.coords,tags);counts[k]+=1;continue
        tags.update(tagmap[k])
        for poly in _polygons(g):
            if poly.area < 1e-4:
                degenerate_parts.append({'svg_id':feature['id'],'kind':k,'area_m2':poly.area})
                continue
            if k not in ('water', 'wood', 'unclassified') and poly.interiors:
                pieces=_holeless(poly)
                if unary_union(pieces).symmetric_difference(poly).area>1e-4:raise ValueError('Surface partition changed source footprint')
                partitions.append({'svg_id':feature['id'],'kind':k,'holes':len(poly.interiors),'pieces':len(pieces)})
                for p in pieces:way(p.exterior.coords,tags);counts[k]+=1
            elif poly.interiors:
                nonlocal_tags=dict(tags);rel=ET.Element('relation',{'id':str(rid),'version':'1','visible':'true'});rid-=1
                outer=way(poly.exterior.coords,{'tgc:svg_id':feature['id']});ET.SubElement(rel,'member',{'type':'way','ref':str(outer),'role':'outer'})
                for ring in poly.interiors:
                    inner=way(ring.coords,{'tgc:svg_id':feature['id']});ET.SubElement(rel,'member',{'type':'way','ref':str(inner),'role':'inner'})
                nonlocal_tags['type']='multipolygon'
                for a,b in nonlocal_tags.items():ET.SubElement(rel,'tag',{'k':a,'v':str(b)})
                rel_elements.append(rel);counts[k]+=1
            else:way(poly.exterior.coords,tags);counts[k]+=1
    for e in way_elements+rel_elements:root.append(e)
    ET.indent(root,space='  ');ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    return {'feature_counts':dict(counts),'nodes':len(nodes),'ways':len(way_elements),'relations':len(rel_elements),'surface_hole_partitions':partitions,'ignored_sub_cm2_parts':degenerate_parts,'unclassified_svg_ids':[f['id'] for f in features if f['kind']=='unclassified']}


def create_pair(raw_path,svg_path,out_dir,settings,printf=print):
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import mapping as geom_mapping
    out=Path(out_dir)
    if out.exists() and any(out.iterdir()):raise ValueError('Choose a NEW/empty output directory; no existing outputs are overwritten')
    out.mkdir(parents=True,exist_ok=True)
    s=dict(settings);a=load_raw(raw_path,s);W=float(s['width_m']);L=float(s['length_m']);res=float(s.get('output_spacing_m',2.0))
    native_x=W/(a.shape[1]-1);native_y=L/(a.shape[0]-1)
    if not math.isfinite(res) or res<=0:raise ValueError('Output spacing must be positive')
    if res+1e-8<max(native_x,native_y):raise ValueError('Output spacing finer than source. Use >= '+str(max(native_x,native_y))+' m; no fabricated resolution')
    h=int(math.ceil(L/res));w=int(math.ceil(W/res))
    if h*w>50000000:raise ValueError('Output exceeds 50-million-cell safety limit')
    dem=bilinear_grid(a,(np.arange(h)+.5)*res/native_y,(np.arange(w)+.5)*res/native_x)
    # Retain a synthetic projected frame for compatibility, not a claimed real location.
    epsg=int(s.get('epsg',32631));ce=float(s.get('center_e',500000));cn=float(s.get('center_n',5000000))
    from pyproj import CRS
    crs=CRS.from_epsg(epsg)
    if not crs.is_projected or any(abs(x.unit_conversion_factor-1)>1e-8 for x in crs.axis_info[:2]):raise ValueError('A metre-based projected CRS is required')
    features,svg_info=read_svg(svg_path,W,L,s.get('mapping',{}),float(s.get('curve_tolerance_m',.15)),float(s.get('max_segment_m',8)))
    prefix=re.sub(r'[^A-Za-z0-9_-]+','_',str(s.get('output_prefix',Path(svg_path).stem))).strip('_') or 'Unity'
    tif=out/(prefix+'_DEM_'+str(res).replace('.0','').replace('.','p')+'m.tif');osm=out/(prefix+'_Layout.osm')
    with rasterio.open(tif,'w',driver='GTiff',height=h,width=w,count=1,dtype='float32',crs='EPSG:'+str(epsg),transform=from_origin(ce-W/2,cn+L/2,res,res),compress='deflate',predictor=3,tiled=True,nodata=-9999.) as dst:
        dst.write(dem,1);dst.set_band_unit(1,'m')
        dst.update_tags(TGC_UNITY_RAW_SVG=MARKER,TGC_SYNTHETIC_GEOREFERENCE='YES',TGC_AUTHORED_SURFACE='bilinear',UNITY_WIDTH_M=W,UNITY_LENGTH_M=L,UNITY_HEIGHT_M=s['height_m'],RAW_ORIENTATION=s.get('orientation','as_stored'),RAW_NORMALIZATION_DIVISOR=s.get('normalization_divisor',2**int(s.get('bits',16))))
    osm_info=write_osm(osm,features,W,L,epsg,ce,cn)
    report={'format':MARKER,'inputs':{'raw':str(Path(raw_path).name),'raw_sha256':sha256(raw_path),'svg':str(Path(svg_path).name),'svg_sha256':sha256(svg_path)},'settings':s,'source_spacing_m':[native_x,native_y],'raw_elevation_range_m':[float(a.min()),float(a.max())],'output_elevation_range_m':[float(dem.min()),float(dem.max())],'raster_shape':[h,w],'extent_m':[w*res,h*res],'svg':svg_info,'osm':osm_info,'limitations':[]}
    if not osm_info['feature_counts'].get('hole'):report['limitations'].append('SVG contains no numbered hole routes or pars. Surface-only OSM: add routing in an OSM editor or Designer; no course routing was invented.')
    if osm_info['unclassified_svg_ids']:report['limitations'].append('Unclassified SVG elements retained as non-golf OSM geometry and in metric reference JSON. TGC does not import them as playing surfaces until assigned.')
    report['limitations'].append('Synthetic UTM frame, not real-world georeferencing. Local OSM only. Custom / Unmatched OFF: independent recentering breaks alignment. Do not upload OSM to OpenStreetMap.')
    if any(f['kind']=='wood' for f in features):
        report['limitations'].append('Woodland exports as natural=wood. Enable Import Natural Wood as Mulch for course splines; woodland never changes the automatic terrain mask or creates individual trees.')
    if any(f['kind']=='mulch' for f in features):
        report['limitations'].append('Woodchip areas keep their surface=woodchips tag. They do not import as woodland mulch or affect the automatic terrain mask.')
    if osm_info['ignored_sub_cm2_parts']:report['limitations'].append('Ignored '+str(len(osm_info['ignored_sub_cm2_parts']))+' topology slivers smaller than one square centimetre in OSM; original filled geometry is retained in the metric reference JSON.')
    (out/(prefix+'_ImportSettings.json')).write_text(json.dumps(s,indent=2),encoding='utf-8')
    (out/(prefix+'_ConversionReport.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    geo={'format':'TGC_SVG_METRIC_REFERENCE_V1','name':prefix+'_SVG_Metric_Reference','coordinate_note':'SVG viewBox mapped to metres, X right and Y down; NOT longitude/latitude','features':[{'type':'Feature','properties':{k:v for k,v in f.items() if k!='geometry'},'geometry':geom_mapping(f['geometry'])} for f in features]}
    (out/(prefix+'_SVG_Metric_Reference.json')).write_text(json.dumps(geo,separators=(',',':')),encoding='utf-8')
    report['outputs']={'dem':str(tif),'osm':str(osm)}
    printf('RAW/SVG conversion complete: '+str(w)+' x '+str(h)+' at '+str(res)+' m')
    for warning in report['limitations']:printf('NOTICE: '+warning)
    return report,features,dem


def preview_image(raw,features,width_m,length_m,max_size=900):
    from PIL import Image,ImageDraw
    from scipy.ndimage import zoom
    step=max(1,int(math.ceil(max(raw.shape)/max_size)));a=raw[::step,::step]
    gy,gx=np.gradient(a,length_m/(raw.shape[0]-1)*step,width_m/(raw.shape[1]-1)*step)
    shade=np.clip((1-.5*gx-.5*gy)/np.sqrt(1+gx*gx+gy*gy)*.65,0,1)
    im=Image.fromarray((shade*255).astype(np.uint8)).convert('RGB');draw=ImageDraw.Draw(im)
    sx=(im.width-1)/width_m;sy=(im.height-1)/length_m
    # White outlines retain the exact vector geometry; no color meanings invented.
    for f in features:
        for p in _polygons(f['geometry']):
            for ring in [p.exterior]+list(p.interiors):draw.line([(x*sx,y*sy) for x,y in ring.coords],fill='white',width=1)
    return im

# Commit the paired outputs together. A conversion error never leaves a usable-
# looking partial pair and never replaces an existing nonempty output folder.
_create_pair_unstaged=create_pair

def create_pair(raw_path,svg_path,out_dir,settings,printf=print):
    import shutil
    target=Path(out_dir).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):raise ValueError('Choose a new/empty output folder; existing outputs are not overwritten')
    target.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+target.name+'_staging_',dir=str(target.parent)))
    try:
        report,features,dem=_create_pair_unstaged(raw_path,svg_path,stage,settings,printf=printf)
        report['outputs']={k:str(target/Path(v).name) for k,v in report['outputs'].items()}
        for p in stage.glob('*_ConversionReport.json'):p.write_text(json.dumps(report,indent=2),encoding='utf-8')
        if target.exists():target.rmdir()
        os.replace(stage,target)
        return report,features,dem
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True)
        raise
