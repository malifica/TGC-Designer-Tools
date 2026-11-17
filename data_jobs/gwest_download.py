from pathlib import Path
import hashlib, json, re, traceback, urllib.parse, xml.etree.ElementTree as ET
import requests
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin

OUT=Path('output'); OUT.mkdir(exist_ok=True)
BASE='https://srsp-open-data.s3.eu-west-2.amazonaws.com/'
BBOX=(287924,709424,290708,711102)
NS={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
SESSION=requests.Session()
SESSION.headers['User-Agent']='GWest-public-DTM-download/1.0'
CAT=[]; CAND={}; ERR=[]; REQUESTS=0

def listing(prefix,delimiter=None):
 global REQUESTS
 ans=[];dirs=[];token=None
 while True:
  REQUESTS+=1
  if REQUESTS>450: raise RuntimeError('Catalogue request safety limit')
  args={'list-type':'2','prefix':prefix,'max-keys':1000}
  if delimiter:args['delimiter']=delimiter
  if token:args['continuation-token']=token
  r=SESSION.get(BASE,params=args,timeout=60);r.raise_for_status();root=ET.fromstring(r.content)
  for item in root.findall('s:Contents',NS):
   ans.append({'key':item.findtext('s:Key',namespaces=NS),'size':int(item.findtext('s:Size',namespaces=NS)), 'last_modified':item.findtext('s:LastModified',namespaces=NS)})
  dirs.extend(x.text for x in root.findall('s:CommonPrefixes/s:Prefix',NS))
  token=root.findtext('s:NextContinuationToken',namespaces=NS)
  if not token:break
 return ans,dirs

def overlaps(key):
 name=Path(key).name.upper()
 for m in re.finditer(r'NN[_-]?(\d{2,10})(NE|NW|SE|SW)?(?!\d)',name):
  digits,quad=m.groups()
  if len(digits)%2:continue
  n=len(digits)//2;size=10**(5-n);e=200000+int(digits[:n])*size;no=700000+int(digits[n:])*size
  if quad:
   size/=2
   if 'E' in quad:e+=size
   if 'N' in quad:no+=size
  if e<BBOX[2] and e+size>BBOX[0] and no<BBOX[3] and no+size>BBOX[1]:return True
 return False

def collect(items):
 for it in items:
  key=it['key']; low=key.lower()
  if low.endswith(('.tif','.tiff')) and 'dtm' in low and overlaps(key):CAND[key]=it

def walk(prefix,depth=0):
 if depth>5:return
 items,dirs=listing(prefix,'/');CAT.append({'prefix':prefix,'folders':dirs,'first_keys':items[:4]})
 print('DIRECTORY',prefix,'folders',dirs,'files',len(items),flush=True);collect(items)
 for sub in dirs:
  low=sub.lower();last=sub.rstrip('/').split('/')[-1].lower()
  if last in ('dsm','laz','las','dsm-first','dsm-last') or any(x in low for x in ('/dsm/','/laz/','/las/','/4326/')):continue
  if 'dtm' in low and last in ('gridded','cog','cogs','27700','tiles','geotiff','geotiffs'):
   found=False
   for grid in ('NN8','NN9','nn8','nn9'):
    its,ds=listing(sub+grid);collect(its)
    if its:found=True
   if found:continue
  walk(sub,depth+1)

try:
 _,roots=listing('','/');print('ROOTS',roots,flush=True)
 for root in roots:
  if 'lidar' in root.lower():walk(root)
 (OUT/'catalogue_discovery.json').write_text(json.dumps({'directories':CAT,'candidates':list(CAND.values()),'requests':REQUESTS},indent=2))
 print('CANDIDATES',json.dumps(list(CAND.values()),indent=2),flush=True)
 assert CAND,'No matching DTM objects found'
 W=BBOX[2]-BBOX[0];H=BBOX[3]-BBOX[1];transform=from_origin(BBOX[0],BBOX[3],1,1)
 groups={}; records=[]
 with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.tiff',GDAL_HTTP_TIMEOUT='90',GDAL_HTTP_MAX_RETRY='2',GDAL_HTTP_RETRY_DELAY='2'):
  for key,it in sorted(CAND.items()):
   url=BASE+urllib.parse.quote(key,safe='/');print('READ',url,flush=True)
   try:
    with rasterio.open(url) as ds:
     if ds.crs is None or ds.crs.to_epsg()!=27700:raise ValueError('Not expected British National Grid')
     res=max(abs(ds.res[0]),abs(ds.res[1]))
     if res>5:raise ValueError('Coarser than 5 m')
     left=max(BBOX[0]-4*res,ds.bounds.left);bottom=max(BBOX[1]-4*res,ds.bounds.bottom);right=min(BBOX[2]+4*res,ds.bounds.right);top=min(BBOX[3]+4*res,ds.bounds.top)
     if left>=right or bottom>=top:continue
     win=from_bounds(left,bottom,right,top,ds.transform).round_offsets().round_lengths()
     src=ds.read(1,window=win,masked=True).astype('float32').filled(-9999)
     arr=np.full((H,W),-9999,np.float32)
     reproject(src,arr,src_transform=ds.window_transform(win),src_crs=ds.crs,src_nodata=-9999,dst_transform=transform,dst_crs=ds.crs,dst_nodata=-9999,resampling=Resampling.bilinear,num_threads=2)
     valid=np.isfinite(arr)&(arr!=-9999)
     group=key.split('/dtm/')[0] if '/dtm/' in key else key.rsplit('/',1)[0]
     if group not in groups:groups[group]={'array':np.full((H,W),-9999,np.float32),'sources':[],'native_resolution_m':res}
     groups[group]['array'][valid]=arr[valid];groups[group]['sources'].append(key);groups[group]['native_resolution_m']=max(groups[group]['native_resolution_m'],res)
     record={**it,'url':url,'group':group,'resolution_m':list(ds.res),'crs':str(ds.crs),'nodata':ds.nodata,'bounds':list(ds.bounds),'crop_valid_pixels':int(valid.sum()),'height_range':([float(arr[valid].min()),float(arr[valid].max())] if valid.any() else None),'tags':ds.tags()};records.append(record)
     print('RESULT',group,ds.res,record['crop_valid_pixels'],record['height_range'],flush=True)
   except Exception as e:
    print('READ FAILED',key,repr(e),flush=True);ERR.append({'key':key,'error':repr(e)})
 summaries=[]
 for group,g in groups.items():
  a=g.pop('array');valid=a!=-9999
  name=re.sub('[^A-Za-z0-9]+','_',group).strip('_');path=OUT/('GWest_'+name+'_DTM_1m_BNG.tif')
  profile=dict(driver='GTiff',height=H,width=W,count=1,dtype='float32',crs='EPSG:27700',transform=transform,nodata=-9999,compress='deflate',predictor=3,tiled=True,blockxsize=256,blockysize=256)
  with rasterio.open(path,'w',**profile) as dst:
   dst.write(a,1);dst.set_band_unit(1,'m');dst.update_tags(SOURCE='Scottish Government / JNCC; '+group,LICENSE='Open Government Licence v3.0',NATIVE_RESOLUTION_M=str(g['native_resolution_m']),PROCESSING='Georeferenced crop / mosaic; no gap filling or artificial terrain. Bilinear sampling only if required.',DOWNLOAD_EXTENT_BNG=str(BBOX))
  summary={'group':group,**g,'filename':path.name,'valid_pixels':int(valid.sum()),'total_pixels':int(a.size),'valid_percent':float(100*valid.mean()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()};summaries.append(summary)
  print('SAVED',json.dumps(summary),flush=True)
 (OUT/'download_report.json').write_text(json.dumps({'bounds_bng':BBOX,'source_objects':records,'groups':summaries,'errors':ERR},indent=2))
 assert summaries,'No source raster could be read'
except BaseException as e:
 (OUT/'discovery_error.json').write_text(json.dumps({'error':repr(e),'traceback':traceback.format_exc(),'directories':CAT,'candidates':list(CAND.values()),'errors':ERR},indent=2));raise
