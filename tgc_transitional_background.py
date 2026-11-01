"""Graduated Background: type-10 terrain on the red side of the final south-up mask."""
import math

import numpy as np
from scipy.ndimage import distance_transform_edt

_BRUSH_SCALES = (64., 32.)
_STRIPE = 192


def transition_scales(main_scale):
    seam = 4.0 * float(main_scale)
    if not math.isfinite(seam) or seam <= 0:
        raise ValueError("Graduated Background requires a positive main brush scale")
    return tuple(s for s in _BRUSH_SCALES if s > seam) + (seam,)


def _raster(a):
    a = np.asarray(a)
    return a[:, :, 0] if a.ndim == 3 and a.shape[2] == 1 else a


def _masks(mask, shape):
    if mask is None or mask.ndim != 3 or mask.shape[:2] != shape or mask.shape[2] < 3:
        raise ValueError("Graduated Background: mask.png must match the saved heightmap dimensions")
    # Same BGR colors as infill_image.get_binary_mask, without allocating its 2 full-size output rasters.
    b,g,r = mask[:,:,0],mask[:,:,1],mask[:,:,2]
    return (b < 40) & (g < 40) & (r > 130), (b > 200) & (g < 180) & (r < 70)


def validate_transition_input(source, mask, purge_water):
    """Provide a useful message before legacy linear infill or GeoPointCloud sees an empty plot."""
    src = _raster(source)
    if src.ndim != 2:
        raise ValueError("Graduated Background: expected a single-channel heightmap")
    red, blue = _masks(mask, src.shape)
    keep = np.isfinite(src) & ~red
    if not np.any(keep & ~blue if purge_water else keep):
        raise ValueError("Graduated Background: the mask leaves no usable detailed terrain. "
                         "Keep part of the measured heightmap unmasked before generating the course.")
    # The existing linear detail interpolator needs three noncollinear source centers.
    # Inspect row extrema rather than copying potentially millions of coordinate pairs.
    rr = np.flatnonzero(keep.any(axis=1))
    if len(rr) >= 2:
        p0,p1 = int(rr[0]),int(rr[-1])
        c0,c1 = int(keep[p0].argmax()),int(keep[p1].argmax())
        for i in rr:
            row = keep[i]
            j = int(row.argmax()); k = row.size-1-int(row[::-1].argmax())
            if j != k or (j-c0)*(p1-p0) != (c1-c0)*(int(i)-p0):
                return
    raise ValueError("Graduated Background: at least three noncollinear, unmasked elevation samples "
                     "are needed to build the detailed terrain.")


def _band_codes(src, detail, mask, spacing, scales):
    """One byte/cell; assign actual distances in bounded strips, including off-strip seam pixels."""
    red,blue = _masks(mask, src.shape)
    seam = ~red & ~blue & np.isfinite(detail)
    valid = red & np.isfinite(src)
    codes = np.full(src.shape, 255, np.uint8)
    if not valid.any():
        return codes
    # The fine centers occupy just one seam-brush width on the red side.
    # Then use one brush width of 32m centers; everything farther out is 64m.
    # Only one band owns each eligible source pixel. The physical footprints,
    # not duplicated stamp centers, overlap at band transitions.
    edges=np.cumsum(tuple(reversed(scales[1:])), dtype=float)
    if not len(edges) or not np.any(seam):
        codes[valid] = len(scales)-1
        return codes
    # Distances measured from the edge of the nearest detailed cell, with half a pixel
    # removed from the center distance. Beyond the last edge only the outer tier matters.
    pix_edges = np.asarray(edges, dtype=float) / spacing + 0.5
    halo = int(math.ceil(pix_edges[-1]))+1
    rows = src.shape[0]
    for lo in range(0,rows,_STRIPE):
        hi = min(rows,lo+_STRIPE)
        take=valid[lo:hi]
        if not take.any():
            continue
        a,b = max(lo-halo,0),min(hi+halo,rows)
        local_seam=seam[a:b]
        if local_seam.any():
            distances = distance_transform_edt(~local_seam)[lo-a:hi-a]
            codes[lo:hi][take] = np.searchsorted(pix_edges,distances[take],side='right')
        else:
            codes[lo:hi][take] = len(pix_edges)
    return codes


def _centers(codes, tier, step, radius):
    """One measured source center per grid tile, with conservative corner coverage.

    Use the eligible sample nearest the tile center. Only in a ragged/disconnected
    tile whose valid pixels extend beyond that stamp, cover the missed pixels
    with extra in-band centers. No secondary grid is blanket-stamped.
    """
    rows,cols=codes.shape
    step=min(step,max(rows,cols))
    # Stripes start on a tile boundary, so a tile is selected only once.
    stripe=max(1,_STRIPE//step)*step
    nx=(cols+step-1)//step
    for lo in range(0,rows,stripe):
        sub=codes[lo:lo+stripe]
        eligible=sub==tier
        y,x=np.nonzero(eligible)
        if not len(y):continue
        if step==1:
            yield y+lo,x
            continue

        # Integer rank: squared distance to the nominal tile center, then a
        # deterministic row-major tie-break. A wholly empty tile stays absent.
        by,bx=y//step,x//step
        dy,dx=y%step,x%step
        rank=((2*dy-step+1)**2+(2*dx-step+1)**2)*(step*step)+(dy*step+dx)
        best=np.full(((len(sub)+step-1)//step)*nx,np.iinfo(np.int64).max,np.int64)
        np.minimum.at(best,by*nx+bx,rank)
        keys=np.flatnonzero(best!=np.iinfo(np.int64).max)
        y0,x0=keys//nx*step,keys%nx*step
        offsets=best[keys]%(step*step)
        cy,cx=y0+offsets//step,x0+offsets%step
        yield cy+lo,cx

        # Complete tiles are already covered at this spacing. For cut tiles
        # use a circle of half the *actual serialized scale* as the test; never
        # assume a center outside the mask or inside missing DEM is usable.
        far_y=np.maximum(cy-y0+.5, np.minimum(y0+step,len(sub))-.5-cy)
        far_x=np.maximum(cx-x0+.5, np.minimum(x0+step,cols)-.5-cx)
        suspects=np.flatnonzero(far_x*far_x+far_y*far_y > radius*radius)
        extra_y=[]; extra_x=[]
        for k in suspects:
            yk,xk=y0[k],x0[k]
            yy,xx=np.nonzero(eligible[yk:yk+step,xk:xk+step])
            yy+=yk; xx+=xk
            sy,sx=cy[k],cx[k]
            while len(yy):
                far=(np.abs(yy-sy)+.5)**2 + (np.abs(xx-sx)+.5)**2
                miss=far > radius*radius+1.e-12
                if not np.any(miss):break
                j=np.argmax(far)
                sy,sx=yy[j],xx[j]
                extra_y.append(sy+lo);extra_x.append(sx)
                yy,xx=yy[miss],xx[miss]
        if extra_y:
            yield np.asarray(extra_y),np.asarray(extra_x)


def append_transitional_background(out, source, detail, mask, raster_frame, pc,
                                   main_scale, make_brush, printf=print):
    """Append coarse→fine red-mask stamps. The caller writes its ordinary dense layer next."""
    src,dt = _raster(source),_raster(detail)
    if src.ndim != 2 or dt.shape != src.shape:
        raise ValueError("Graduated Background: source and detailed rasters must share one grid")
    west,south,spacing = map(float,raster_frame)
    if not (math.isfinite(west) and math.isfinite(south) and math.isfinite(spacing) and spacing>0):
        raise ValueError("Graduated Background: invalid source raster georeference")
    scales=transition_scales(main_scale)
    codes=_band_codes(src,dt,mask,spacing,scales)
    counts=[]
    for i,size in enumerate(scales):
        # Established soft-brush footprint ratio: nominal spacing is size/2.5,
        # snapped to the nearest native cell. Never invent subpixel elevations.
        step=max(1,int(math.floor(size/(2.5*spacing)+.5)))
        start=len(out)
        for ys,xs in _centers(codes,len(scales)-1-i,step,size/(2.*spacing)):
            for r,c,elev in zip(ys.tolist(),xs.tolist(),src[ys,xs].tolist()):
                # Source *centers*, including any leading red rows/cols absent from
                # the rebased detailed cloud. No independently centered coarse cloud.
                x,_,z=pc.projToTGC(west+(c+.5)*spacing,south+(r+.5)*spacing,0.0)
                out.append(make_brush(x,z,float(elev),size,brush_type=10))
        counts.append(len(out)-start)
    printf("Graduated Background (outside to seam): " +
           ", ".join("10/%g: %d" % (s,n) for s,n in zip(scales,counts)) +
           " stamps; main scale %g m, seam scale %g m." % (main_scale,scales[-1]))
    return tuple(zip(scales,counts))
