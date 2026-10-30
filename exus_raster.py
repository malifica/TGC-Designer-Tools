"""Metric normalization of NEW ex-US raster downloads only.
Existing UK/USGS/CFS/project files are never altered by this module.
"""
from pathlib import Path
import math
import os
import numpy as np
import pyproj
import uk_lidar_downloader as u


def local_utm(bbox):
    lon=(bbox[0]+bbox[2])/2;lat=(bbox[1]+bbox[3])/2
    if not -80<=lat<=84:raise u.AcquisitionError('This acquisition needs a polar CRS; local UTM normalization is unsupported here.')
    zone=max(1,min(60,int(math.floor((lon+180)/6))+1))
    return pyproj.CRS.from_epsg((32600 if lat>=0 else 32700)+zone)


def normalize(path,bbox,dataset,metadata,printf=print,cancel=None):
    """Canada / Spain / GSI: resample downloaded crop to local UTM, preserve Z.
    Never pass Mercator pixels or Canada-wide Lambert grid units as ground scale.
    No vertical datum shift, hole-filling, or elevation-value offset is introduced.
    """
    if not dataset.metadata.get('local_utm'):return path,metadata
    import rasterio
    from rasterio.warp import reproject,Resampling,calculate_default_transform
    from rasterio.transform import from_origin
    path=Path(path);temp=path.with_name(path.stem+'.metric.part.tif')
    target=local_utm(bbox)
    resolution=float(dataset.metadata['output_resolution_m'])
    if not math.isfinite(resolution) or not .25<=resolution<=5:raise u.AcquisitionError('Unsupported local raster spacing.')
    u.check_cancel(cancel)
    try:
        with rasterio.open(path) as src:
            from exus_resolution_policy import raster_spacing_m
            raster_spacing_m(src,bbox)
            if not src.crs:raise u.AcquisitionError('Cannot reproject a source with no CRS.')
            # Explicitly discard vertical axes from the horizontal warp definition.
            # Retain the full original CRS in metadata; never invoke a geoid shift.
            horizontal=pyproj.CRS.from_user_input(src.crs).to_2d()
            # Use a common target-aligned grid so independently cropped source tiles
            # mosaic without half-cell offsets. Bounds are limited to this source crop.
            tr,w,h=calculate_default_transform(horizontal,target,src.width,src.height,*src.bounds,resolution=resolution)
            west=math.floor(tr.c/resolution)*resolution
            north=math.ceil(tr.f/resolution)*resolution
            east=math.ceil((tr.c+w*resolution)/resolution)*resolution
            south=math.floor((tr.f-h*resolution)/resolution)*resolution
            w=int(round((east-west)/resolution));h=int(round((north-south)/resolution))
            if not (0<w and 0<h and w*h<=150_000_000):raise u.AcquisitionError('Metric raster size exceeds the acquisition limit.')
            transform=from_origin(west,north,resolution,resolution)
            profile=dict(driver='GTiff',width=w,height=h,count=1,dtype='float32',crs=target,transform=transform,
                         nodata=-9999.,compress='deflate',tiled=True,blockxsize=256,blockysize=256,BIGTIFF='IF_SAFER')
            printf('ex-US local metric grid: %s -> %s at %g m. Horizontal resampling only; elevations/vertical datum are not shifted.'%(src.crs,target.to_string(),resolution))
            with rasterio.open(temp,'w',**profile) as dst:
                reproject(source=rasterio.band(src,1),destination=rasterio.band(dst,1),
                    src_transform=src.transform,src_crs=horizontal,src_nodata=src.nodata,
                    dst_transform=transform,dst_crs=target,dst_nodata=-9999.,
                    resampling=Resampling.bilinear,num_threads=2,warp_mem_limit=64,
                    init_dest_nodata=True)
                dst.update_tags(**src.tags())
                dst.update_tags(TGC_EXUS_SOURCE_CRS=src.crs.to_wkt(),TGC_EXUS_COURSE_GRID=target.to_string(),
                                TGC_EXUS_RESAMPLING='bilinear horizontal reprojection; NoData preserved; no vertical conversion')
            source_crs=src.crs.to_wkt()
        u.check_cancel(cancel)
        valid=total=0
        with rasterio.open(temp) as check:
            if not check.crs.is_projected or check.crs.to_epsg() in (3857,3979):raise u.AcquisitionError('Raster not normalized to the requested local course grid.')
            for _,win in check.block_windows(1):
                u.check_cancel(cancel);a=check.read(1,window=win,masked=True)
                valid+=int(np.count_nonzero(~np.ma.getmaskarray(a)&np.isfinite(a.data)));total+=a.size
            if not valid:raise u.AcquisitionError('Metric reprojection produced no valid terrain.')
            updated=dict(metadata,source_crs=source_crs,crs=check.crs.to_wkt(),resolution=list(check.res),
                         bounds=list(check.bounds),valid_cells=valid,cells=total,valid_fraction=valid/total,
                         resampling='bilinear',vertical_datum_conversion=False)
        os.replace(temp,path)
        return path,updated
    finally:
        if temp.exists():temp.unlink()
