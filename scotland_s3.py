"""Read-only Scottish public S3 inventory; no dependency on the JNCC catalogue.

Search the selected product and intersecting OS-grid easting strips only.
Object URLs are generated ONLY from S3-returned keys, never assumed filenames.
A filename match locates a tile, not its finite terrain/point-cloud coverage.
"""
from __future__ import annotations
import math
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from urllib.parse import quote, unquote

import uk_lidar_downloader as u

VERSION = 'TGC_BETA7_SCOTLAND_DIRECT_S3_V1'
ENDPOINTS = ('https://srsp-open-data.s3.eu-west-2.amazonaws.com/',
             'https://s3.eu-west-2.amazonaws.com/srsp-open-data/')
# No per-course or per-survey filenames/objects are embedded here.
LETTERS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'
GRID_RE = re.compile(r'(?<![A-Z0-9])([A-HJ-Z]{2})(\d{10}|\d{8}|\d{6}|\d{4}|\d{2})(NW|NE|SW|SE)?(?![A-Z0-9])', re.I)
MAX_REQUESTS = 800
MAX_DEPTH = 7
_CACHE = {}  # Small process-local directory cache; no credential or project data.


def grid_origin(letters):
    a, b = (LETTERS.index(c) for c in letters.upper())
    x = ((a - 2) % 5) * 5 + b % 5
    y = 19 - (a // 5) * 5 - b // 5
    if not (0 <= x <= 6 and 0 <= y <= 12):
        raise ValueError('Not a British National Grid square')
    return x * 100000, y * 100000


def grid_letters(x, y):
    origin = (math.floor(x/100000)*100000, math.floor(y/100000)*100000)
    for a in LETTERS:
        for b in LETTERS:
            try:
                if grid_origin(a+b) == origin:
                    return a+b
            except ValueError:
                pass
    raise u.AcquisitionError('Course extent falls outside the British National Grid search area.')


def tile_bounds(key):
    for m in GRID_RE.finditer(key):
        letters, digits, quadrant = m.groups()
        try:
            ox, oy = grid_origin(letters)
        except ValueError:
            continue
        half = len(digits)//2
        size = 10**(5-half)
        x, y = ox + int(digits[:half])*size, oy + int(digits[half:])*size
        if quadrant:
            if size != 10000:
                continue
            size = 5000
            x += size if 'E' in quadrant.upper() else 0
            y += size if 'N' in quadrant.upper() else 0
        yield m.group(0), (x, y, x+size, y+size)


def search_strips(bounds):
    """NJ4 covers NJ46 as well as NJ4064-style finer tiles; NJ46 alone does not."""
    x0,y0,x1,y1 = bounds
    result = set()
    for x in range(math.floor(x0/10000)*10000, math.ceil(x1/10000)*10000, 10000):
        for y in range(math.floor(y0/100000)*100000, math.ceil(y1/100000)*100000, 100000):
            result.add(grid_letters(x+1,y+1) + str((x%100000)//10000))
    return sorted(result)


def parse_page(raw):
    if len(raw) > 8*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise u.AcquisitionError('Unsafe or oversized Scottish inventory response.')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] != 'ListBucketResult':
        raise u.AcquisitionError('Scottish storage returned no S3 inventory; coverage is unknown.')
    text = lambda p,k,default='': p.findtext('{*}'+k, default=default)
    decode = unquote if text(root,'EncodingType') == 'url' else lambda s:s
    objects = [{'key':decode(text(e,'Key')), 'bytes':int(text(e,'Size','0')),
                'modified':text(e,'LastModified')} for e in root.findall('{*}Contents')]
    children = [decode(text(e,'Prefix')) for e in root.findall('{*}CommonPrefixes')]
    token = text(root,'NextContinuationToken') if text(root,'IsTruncated').lower()=='true' else ''
    if text(root,'IsTruncated').lower()=='true' and not token:
        raise u.AcquisitionError('Truncated Scottish inventory has no continuation token; results are partial.')
    return objects,children,token


class Inventory:
    def __init__(self, http, cancel, printf, max_requests=MAX_REQUESTS):
        self.http=http;self.cancel=cancel;self.printf=printf;self.calls=0
        self.max_requests=max_requests;self.endpoint=ENDPOINTS[0]

    def page(self, prefix, delimiter=None, token='', limit=1000):
        u.check_cancel(self.cancel)
        if self.calls >= self.max_requests:
            raise u.AcquisitionError('Targeted inventory request limit reached; retained matches are partial.')
        params={'list-type':'2','prefix':prefix,'max-keys':str(limit),'encoding-type':'url'}
        if delimiter is not None:params['delimiter']=delimiter
        if token:params['continuation-token']=token
        self.calls+=1;start=time.monotonic()
        with self.http.get(self.endpoint,params=params,timeout=(8,45)) as r:
            r.raise_for_status();result=parse_page(r.content)
        u.check_cancel(self.cancel)
        self.printf('Scotland AWS [%d]: %s%s (%.2fs)' %
                    (self.calls,prefix,' [next page]' if token else '',time.monotonic()-start))
        return result

    def pages(self,prefix,delimiter=None):
        token='';seen=set()
        while True:
            objects,children,next_token=self.page(prefix,delimiter,token)
            yield objects,children
            if not next_token:return
            if next_token in seen:
                raise u.AcquisitionError('Scottish inventory repeated a continuation token; results are partial.')
            seen.add(next_token);token=next_token


def discover(http,bbox,kind='dtm',cancel=None,printf=print):
    """Return (datasets, notices); skip restricted Phase 2 point clouds, not DTM."""
    if kind not in ('all','dtm','pointcloud'):raise u.AcquisitionError('Invalid Scottish product.')
    # This existing transform is used ONLY for spatial search, never relabels data.
    bounds=u.projected_bounds(bbox,'EPSG:27700',printf)
    # A small inventory-only guard protects tile selection near transformation edges.
    bounds=(bounds[0]-20,bounds[1]-20,bounds[2]+20,bounds[3]+20)
    strips=search_strips(bounds);inv=Inventory(http,cancel,printf)
    printf('Scotland: direct public AWS discovery. JNCC catalogue is NOT contacted.')
    printf('Scotland: product=%s; targeted grid strips=%s. Tile-name matches are not coverage guarantees.' % (kind,', '.join(strips)))
    first=None;errors=[]
    for endpoint in ENDPOINTS:
        inv.endpoint=endpoint
        try:
            first=inv.page('lidar/',delimiter='/');break
        except u.Cancelled:raise
        except Exception as exc:
            printf('Scotland endpoint unavailable: '+str(exc))
    if first is None:
        raise u.AcquisitionError('Both direct Scottish AWS endpoints failed. Coverage is UNKNOWN, not zero.')
    wanted={'dtm'} if kind=='dtm' else {'laz','las'} if kind=='pointcloud' else {'dtm','laz','las'}
    products={'dtm','dsm','laz','las','dem','intensity','imagery','metadata','wms','ogc'}
    queue=deque((p,0) for p in first[1]);seen_dirs=set();matches={};searched=set();restricted=set()
    # Root normally contains only a few collections, but do not silently truncate.
    token=first[2];tokens=set()
    while token:
        if token in tokens:raise u.AcquisitionError('Scottish collection list repeats a page.')
        tokens.add(token);_,children,token=inv.page('lidar/',delimiter='/',token=token)
        queue.extend((p,0) for p in children)

    def consider(obj):
        key=obj['key'];parts=key.lower().split('/')
        product='dtm' if 'dtm' in parts else 'pointcloud' if any(p in parts for p in ('laz','las')) else None
        if product is None or (kind!='all' and product!=kind):return
        if product=='pointcloud' and any(re.fullmatch(r'phase[-_ ]?0?2',p) for p in parts):return
        suffix=key.rsplit('.',1)[-1].lower()
        if suffix not in ({'tif','tiff','asc','zip'} if product=='dtm' else {'las','laz','zip'}):return
        if any(u.intersects(box,bounds) for _,box in tile_bounds(key)):
            matches[key]=(obj,product)

    def targeted(prefix,stem=''):
        for strip in strips:
            for case in (strip,strip.lower()):
                query=prefix+stem+case
                if query in searched:continue
                searched.add(query)
                for objects,_ in inv.pages(query):
                    for obj in objects:consider(obj)

    failures=0
    while queue:
        u.check_cancel(cancel);prefix,depth=queue.popleft()
        if prefix in seen_dirs:continue
        seen_dirs.add(prefix)
        parts=prefix.lower().strip('/').split('/')
        actual_products=set(parts)&products
        if actual_products and not actual_products&wanted:continue
        if (kind=='pointcloud' or ('laz' in parts or 'las' in parts)) and any(re.fullmatch(r'phase[-_ ]?0?2',p) for p in parts):
            restricted.add(prefix);continue
        if depth>MAX_DEPTH:
            errors.append('Unrecognized deep inventory layout; not searched: '+prefix);continue
        try:
            # Inspect just the directory structure/sample, then query selected strips.
            cache_key=(inv.endpoint,prefix)
            cached=_CACHE.get(cache_key)
            if cached and time.monotonic()-cached[0]<1800:
                objects,children,truncated=cached[1]
            else:
                objects,children,truncated=inv.page(prefix,delimiter='/',limit=64)
                if not truncated:
                    if len(_CACHE)>256:_CACHE.clear()
                    _CACHE[cache_key]=(time.monotonic(),(objects,children,truncated))
            for obj in objects:consider(obj)
            # Known national/phase folders are grid leaves even if their first keys
            # use numeric tile names which this adapter cannot infer safely.
            if objects or prefix.rstrip('/').endswith('/gridded'):
                stems={''}
                unsupported=False
                for obj in objects:
                    basename=obj['key'][len(prefix):];m=GRID_RE.search(basename)
                    if m:stems.add(basename[:m.start()])
                    elif obj['bytes'] and basename.lower().endswith(('.tif','.tiff','.las','.laz','.zip','.asc')):unsupported=True
                for stem in sorted(stems):targeted(prefix,stem)
                if unsupported:
                    errors.append('Some non-OS-grid filenames cannot be spatially matched in '+prefix+'; this collection search is partial.')
                if truncated and children:
                    # Mixed file/subdirectory inventories need additional directory pages.
                    t=truncated;seen=set()
                    while t:
                        if t in seen:raise u.AcquisitionError('Repeated directory continuation token')
                        seen.add(t);objs,more,t=inv.page(prefix,delimiter='/',token=t)
                        for obj in objs:consider(obj)
                        children+=more
            elif truncated:
                t=truncated;seen=set()
                while t:
                    if t in seen:raise u.AcquisitionError('Repeated directory continuation token')
                    seen.add(t);objs,more,t=inv.page(prefix,delimiter='/',token=t)
                    for obj in objs:consider(obj)
                    children+=more
            for child in children:
                seg=child.rstrip('/').rsplit('/',1)[-1]
                if seg.lower() in products and seg.lower() not in wanted:continue
                if re.fullmatch(r'\d{4,5}',seg) and seg!='27700':
                    errors.append('Unsupported inventory CRS folder (not relabelled): '+child);continue
                if re.fullmatch(r'[A-HJ-Z]{2}\d*(?:NW|NE|SW|SE)?',seg,re.I):
                    if not any(strip.upper().startswith(seg.upper()) or seg.upper().startswith(strip.upper()) for strip in strips):continue
                queue.append((child,depth+1))
            failures=0
        except u.Cancelled:raise
        except Exception as exc:
            errors.append('Partial Scottish search at '+prefix+': '+str(exc));printf('NOTICE: '+errors[-1]);failures+=1
            if inv.calls>=inv.max_requests or failures>=3:
                errors.append('Remaining Scottish collections were not checked; matches below are retained.');break
    groups={}
    for key,(obj,product) in sorted(matches.items()):
        parent=key.rsplit('/',1)[0]
        # Keep different resolutions separate; never blend surveys automatically.
        m=re.search(r'(?:^|_)(\d+(?:[p.]\d+)?)(CM|M)(?:_|\.)',key.rsplit('/',1)[-1],re.I)
        resolution=(m.group(1).replace('p','.')+' '+m.group(2).lower()) if m else ''
        group=(parent,product,resolution)
        title=parent.replace('lidar/','',1).replace('/27700/gridded','').replace('/',' / ')
        ds=groups.setdefault(group,u.Dataset('scotland-s3:'+parent+':'+resolution,'Scotland',title,product,'',resolution,
                'Open Government Licence v3 (Phase 2 point clouds excluded)',
                'Scottish public sector LiDAR / Scottish Government; retain collection attribution.',
                u.PROVIDERS['Scotland'],notes='AWS-listed tile; acquisition date not inferred from upload time. Finite coverage checked on download.'))
        ds.assets.append(u.Asset(inv.endpoint+quote(key,safe='/'),key.rsplit('/',1)[-1],obj['bytes']))
    if restricted:printf('NOTICE: Phase 2 LAS/LAZ excluded because the official registry specifies a non-commercial licence. Phase 2 DTM remains eligible.')
    notices=list(dict.fromkeys(errors))
    if not groups:
        notices.append('No supported OS-grid-named tiles matched this extent. This is NOT proof that Scotland has no coverage; consult the provider for alternate naming/collections.')
    for message in notices:printf('NOTICE: '+message)
    printf('Scotland direct AWS: %d dataset choice(s), %d tile(s), %d inventory requests. %s' %
           (len(groups),len(matches),inv.calls,'PARTIAL search; review notices.' if notices else 'Targeted supported grid-name search complete; coverage still requires file checks.'))
    return list(groups.values()),notices
