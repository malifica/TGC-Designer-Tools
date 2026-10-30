"""Acquisition-only source/grid checks. Never upgrade a coarse DEM by resampling.

Grid spacing is NOT vertical accuracy. Raw LAS/LAZ returns have no raster cell
size; their existing import/detection path remains separate from this DEM policy.
"""
from __future__ import annotations
import math
import re
import numpy as np
import pyproj

VERSION = 'TGC_EXUS_NATIVE_5M_POLICY_V1'
MAX_DEM_SPACING_M = 5.0


def _fail(message):
    from uk_lidar_downloader import AcquisitionError
    raise AcquisitionError('5 m terrain requirement: ' + message)


def resolution_numbers(text):
    """Read explicitly unit-labelled spacing, including 0.5 m, 50 cm, 1–5 m."""
    text = str(text or '').lower().replace(',', '.')
    values = []
    for match in re.finditer(r'(?<![\w.])(\d+(?:\.\d+)?)\s*(?:(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*)?(cm|metres?|meters?|m)\b', text):
        factor = .01 if match[3] == 'cm' else 1.
        values.extend(float(v)*factor for v in (match[1], match[2]) if v is not None)
    return values


def dataset_spacing(dataset):
    values = resolution_numbers(dataset.resolution)
    metadata = dataset.metadata or {}
    for key in ('native_resolution_m', 'source_resolution_m'):
        if key in metadata:
            value = metadata[key]
            try:
                values.extend(float(v) for v in (value if isinstance(value, (tuple,list)) else [value]))
            except (ValueError, TypeError):
                _fail('invalid source-spacing metadata for '+dataset.title)
    if not values or any(not math.isfinite(v) or v <= 0 for v in values):
        _fail('native source spacing is not established for '+dataset.title+'. No coarse fallback is used.')
    value = max(values)
    if value > MAX_DEM_SPACING_M + 1e-8:
        _fail('%g m source rejected: %s. A smaller output pixel would not add detail.' % (value, dataset.title))
    if 'output_resolution_m' in metadata:
        output = float(metadata['output_resolution_m'])
        if not math.isfinite(output) or output <= 0 or output > MAX_DEM_SPACING_M + 1e-8:
            _fail('invalid or coarser-than-5 m requested output grid.')
    return value


def validate_dataset(dataset):
    if dataset.kind == 'dtm':
        return dataset_spacing(dataset)
    # There is no meaningful fixed raster resolution on a raw point cloud.
    return None


def filter_datasets(datasets, printf=print):
    retained, notices = [], []
    for dataset in datasets:
        try:
            validate_dataset(dataset)
            retained.append(dataset)
        except RuntimeError as exc:
            notices.append(str(exc));printf('NOTICE: '+str(exc))
    return retained, notices


def raster_spacing_m(src, bbox=None):
    """Check the real native raster transform before a crop or horizontal warp.

    Projected axes use their documented linear units. Geographic grids use
    geodesic pixel distances at the corners/centre of the requested crop.
    Neither degree-valued spacings nor unsupported CRSs are treated as metres.
    """
    if not src.crs:
        _fail('raster has no CRS.')
    crs = pyproj.CRS.from_user_input(src.crs).to_2d()
    t = src.transform
    if src.count != 1 or src.dtypes[0] in ('uint8','int8'):
        _fail('expected numerical elevations, not an 8-bit map or an RGB picture.')
    if crs.is_projected:
        axes = crs.axis_info
        if len(axes)<2 or any('degree' in a.unit_name.lower() for a in axes[:2]):
            _fail('projected axes do not have documented linear units.')
        factors = [float(a.unit_conversion_factor) for a in axes[:2]]
        # World X/Y are always easting/northing here, independent of EPSG axis order.
        if not all(math.isfinite(f) and f>0 for f in factors):
            _fail('invalid linear-unit conversion.')
        factor = max(factors)
        spacing = (math.hypot(t.a,t.d)*factor, math.hypot(t.b,t.e)*factor)
    elif crs.is_geographic:
        geod = crs.get_geod()
        west,south,east,north = src.bounds
        if bbox is not None:
            tr = pyproj.Transformer.from_crs('EPSG:4326',crs,always_xy=True)
            x,y=tr.transform([bbox[0],bbox[2]],[bbox[1],bbox[3]],errcheck=True)
            west,south,east,north=max(west,min(x)),max(south,min(y)),min(east,max(x)),min(north,max(y))
        measurements=[]
        for x in (west,(west+east)/2,east):
            for y in (south,(south+north)/2,north):
                measurements.append((abs(geod.inv(x,y,x+t.a,y+t.d)[2]),
                                     abs(geod.inv(x,y,x+t.b,y+t.e)[2])))
        spacing=tuple(max(p[i] for p in measurements) for i in (0,1))
    else:
        _fail('unrecognized raster coordinate system.')
    if any(not math.isfinite(v) or v<=0 or v>MAX_DEM_SPACING_M+1e-6 for v in spacing):
        _fail('actual raster grid is %s m; file rejected before resampling.' % (tuple(round(v,6) for v in spacing),))
    return tuple(float(v) for v in spacing)


def validate_outputs(records, bbox, dataset):
    import rasterio
    validate_dataset(dataset)
    if dataset.kind!='dtm':return
    for path,info in records:
        with rasterio.open(path) as src:
            info['verified_grid_spacing_m']=list(raster_spacing_m(src,bbox))
        info['native_source_spacing_m']=dataset_spacing(dataset)
        info['resolution_policy']=VERSION


def processing_scale(value, printf=print):
    """Cap this acquisition's automatic handoff, not the application's settings."""
    scale=float(value)
    if not math.isfinite(scale) or scale<=0:_fail('invalid automatic-processing scale.')
    if scale>MAX_DEM_SPACING_M:
        printf('NOTICE: ex-US automatic processing capped at 5 m (current Map Scale is %g m). The global setting is unchanged.' % scale)
        return MAX_DEM_SPACING_M
    return scale
