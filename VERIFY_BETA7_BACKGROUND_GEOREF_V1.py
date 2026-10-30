"""Offline tests of the installed terrain functions; no game or network needed."""
from pathlib import Path
import ast
import copy
import json
import math
import sys
import unittest
import numpy as np
import pyproj
from scipy import ndimage
from scipy.ndimage import map_coordinates

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from GeoPointCloud import GeoPointCloud
from infill_image import infill_image_scipy
import cfs_georef

# Execute the actual installed function bodies without importing the terrain
# module's unrelated OSM/network/GUI dependencies. No function is reimplemented.
NAMES = {'get_pixel', '_normalize_background_heightmap', '_nearest_fill_invalid',
         '_sample_bilinear_2d', '_align_coarse_background_origin',
         '_outside_landscape_raster_frame', 'generate_coarse_outside_landscape'}
TEXT = (ROOT / 'tgc_image_terrain.py').read_text(encoding='utf-8-sig')
TREE = ast.parse(TEXT)
FUNCTIONS = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
if {n.name for n in FUNCTIONS} != NAMES:
    raise RuntimeError('Missing installed background georeference functions')
NS = {'np': np, 'math': math, 'json': json, 'ndimage': ndimage}
exec(compile(ast.Module(body=FUNCTIONS, type_ignores=[]), str(ROOT/'tgc_image_terrain.py'), 'exec'), NS)
quiet = lambda *args, **kwargs: None


def make_case(scale=2.0, rows=23, cols=31, r0=3, c0=5, r1=None, c1=None,
              epsg=32631, edge=(499123.25, 4999123.75)):
    r1 = rows - 4 if r1 is None else r1
    c1 = cols - 3 if c1 is None else c1
    yy, xx = np.indices((rows, cols), dtype=float)
    full = (40.0 + 0.17*xx + 0.39*yy + 0.007*xx*yy).astype(np.float32)
    arr = full.copy()
    valid = np.zeros(arr.shape, dtype=bool)
    valid[r0:r1, c0:c1] = True
    arr[~valid] = np.nan
    proj = pyproj.Proj('epsg:'+str(epsg), preserve_units=False)
    ref = GeoPointCloud(); ref.proj=proj; ref.origin=(0.0,0.0)
    ll = ref.projToLatLon(*edge)
    pc = GeoPointCloud(); pc.addFromImage(arr[:,:,None], scale, ll, proj)
    grid = dict(min_x=edge[0], min_y=edge[1], rows=rows, cols=cols,
                resolution=scale, lower_left_latlon=list(ll),
                row_order='south_up_internal', origin_semantics='southwest_cell_edge', xy_units='meters')
    return arr, full, pc, grid, proj, ll, valid


class BackgroundGeoReferenceTests(unittest.TestCase):
    def test_01_coarse_centers_multiple_scales(self):
        for fine, coarse in [(2.,8.),(2.,12.),(1.,8.),(1.,12.),(1.,16.),
                             (2.,2.),(2.,5.),(1.09375,8.),(2.,1.)]:
            for leading in [False, True]:
                with self.subTest(fine=fine,coarse=coarse,leading=leading):
                    arr, full, pc, grid, proj, ll, valid = make_case(scale=fine)
                    b = np.arange(42.,dtype=float).reshape(6,7)
                    if leading: b[:2,:]=np.nan; b[:,:1]=np.nan; b[3,3]=np.nan
                    bp = GeoPointCloud(); bp.addFromImage(b,coarse,ll,proj)
                    before=bp.points().copy(); detail_before=pc.points().copy(); origin=pc.origin
                    shift=NS['_align_coarse_background_origin'](bp,fine,coarse)
                    self.assertAlmostEqual(shift,0.5*(fine-coarse))
                    rows,cols=np.where(np.isfinite(b))
                    for point,r,c in zip(bp.points(),rows,cols):
                        e,n=bp.enuToProj(point[0],point[1])
                        self.assertAlmostEqual(e,grid['min_x']+fine/2+c*coarse,places=6)
                        self.assertAlmostEqual(n,grid['min_y']+fine/2+r*coarse,places=6)
                        game=pc.projToTGC(e,n,0)
                        expected=pc.projToTGC(grid['min_x']+fine/2+c*coarse,
                                             grid['min_y']+fine/2+r*coarse,0)
                        np.testing.assert_allclose(game,expected,atol=1e-6,rtol=0)
                    np.testing.assert_array_equal(bp.points(),before)
                    np.testing.assert_array_equal(pc.points(),detail_before)
                    self.assertEqual(pc.origin,origin)

    def test_02_original_offsets_reproduced(self):
        for coarse,expected in [(8,3),(12,5)]:
            arr,full,pc,g,p,ll,v=make_case()
            bp=GeoPointCloud();bp.addFromImage(np.ones((3,4)),coarse,ll,p)
            e,n=bp.enuToProj(0,0)
            self.assertAlmostEqual(e-(g['min_x']+1),expected,places=6)
            self.assertAlmostEqual(n-(g['min_y']+1),expected,places=6)

    def test_03_real_infill_linear_plane(self):
        for fine,coarse in [(2.,8.),(2.,12.),(1.,8.),(2.,5.)]:
            with self.subTest(fine=fine,coarse=coarse):
                arr,full,pc,g,p,ll,v=make_case(scale=fine)
                r,c=np.indices(full.shape,dtype=float)
                full=100+0.3*(c+.5)*fine+0.7*(r+.5)*fine
                mask=np.full(full.shape+(3,),255,dtype=np.uint8)
                mask[~v]=[0,0,255]
                detail,bg,_=infill_image_scipy(full[:,:,None],mask,background_ratio=coarse/fine,printf=quiet)
                original=full.copy(); bp=GeoPointCloud();bp.addFromImage(bg,coarse,ll,p)
                NS['_align_coarse_background_origin'](bp,fine,coarse)
                for point in bp.points():
                    e,n=bp.enuToProj(point[0],point[1])
                    expected=100+.3*(e-g['min_x'])+.7*(n-g['min_y'])
                    self.assertAlmostEqual(point[2],expected,places=6)
                np.testing.assert_array_equal(full,original)
                np.testing.assert_allclose(detail[:,:,0][v],full[v],atol=1e-9)

    def test_04_outer_matches_independent_raster_sample(self):
        for scale in [1.,2.,4.]:
            for r0,c0 in [(0,0),(3,5),(8,2)]:
                with self.subTest(scale=scale,offset=(r0,c0)):
                    arr,full,pc,g,p,ll,v=make_case(scale=scale,r0=r0,c0=c0)
                    before=arr.copy(); pts=pc.points().copy(); origin=pc.origin
                    result=NS['generate_coarse_outside_landscape'](arr,pc,scale,
                        resolution_m=16,world_half_extent_m=96,printf=quiet,master_grid=g)
                    self.assertGreater(len(result),0)
                    # Independent nearest-fill implementation: EDT indices, then scipy sampler.
                    valid=np.isfinite(arr)
                    indices=ndimage.distance_transform_edt(~valid,return_distances=False,return_indices=True)
                    fill=np.where(valid,arr,arr[tuple(indices)])
                    smooth=ndimage.gaussian_filter(fill,sigma=max(.75,.35*16/scale),mode='nearest').astype(np.float32)
                    minc,minr=np.where(valid)[1].min(),np.where(valid)[0].min()
                    for s in result:
                        x,z=s['position']['x'],s['position']['z']
                        self.assertFalse(-pc.width/2<=x<=pc.width/2 and -pc.height/2<=z<=pc.height/2)
                        col=minc+np.clip((x+pc.width/2)/scale,0,pc.width/scale)
                        row=minr+np.clip((z+pc.height/2)/scale,0,pc.height/scale)
                        expected=float(map_coordinates(smooth,np.array([[row],[col]]),order=1,mode='nearest')[0])
                        self.assertAlmostEqual(s['value'],expected,places=4)
                        self.assertEqual(s['type'],10);self.assertEqual(s['scale']['x'],32)
                        self.assertEqual(s['scale']['z'],32)
                    np.testing.assert_array_equal(arr,before);np.testing.assert_array_equal(pc.points(),pts)
                    self.assertEqual(pc.origin,origin)

    def test_05_optional_grid_recovery_equals_explicit(self):
        a,_,pc,g,_,_,_=make_case()
        explicit=NS['generate_coarse_outside_landscape'](a,pc,2,world_half_extent_m=96,printf=quiet,master_grid=g)
        recovered=NS['generate_coarse_outside_landscape'](a,pc,2,world_half_extent_m=96,printf=quiet)
        self.assertEqual(len(explicit),len(recovered))
        for x,y in zip(explicit,recovered):
            self.assertEqual(x['position'],y['position'])
            self.assertAlmostEqual(x['value'],y['value'],places=5)

    def test_06_independent_crop_edges_and_holes(self):
        a,_,pc,g,p,ll,v=make_case()
        a[6:9,10:15]=np.nan
        pc=GeoPointCloud();pc.addFromImage(a[:,:,None],2,ll,p)
        frame=NS['_outside_landscape_raster_frame'](a,pc,2,g)
        self.assertEqual(frame,(g['min_x'],g['min_y'],2.))
        result=NS['generate_coarse_outside_landscape'](a,pc,2,world_half_extent_m=96,printf=quiet,master_grid=g)
        self.assertTrue(all(math.isfinite(s['value']) for s in result))

    def test_07_latlon_roundtrip_and_projected_crs(self):
        for epsg,edge in [(32631,(500000.,5000000.)),(26916,(400123.5,4850123.25)),
                          (2277,(700000.,4200000.))]:
            a,_,pc,g,_,_,_=make_case(epsg=epsg,edge=edge)
            frame=NS['_outside_landscape_raster_frame'](a,pc,2,g)
            self.assertEqual(frame,(edge[0],edge[1],2.))

    def test_08_legacy_master_half_cell_recovery(self):
        a,_,pc,g,p,ll,v=make_case()
        center=cfs_georef._projected_meters_to_latlon(g['min_x']+1,g['min_y']+1,p)
        rd={'origin':center,'projection':p,'image_scale':2}
        recovered=cfs_georef.get_master_grid(rd,a,printf=quiet)
        for k in ['min_x','min_y']:
            self.assertAlmostEqual(g[k],recovered[k],places=6)
        result=NS['generate_coarse_outside_landscape'](a,pc,2,world_half_extent_m=96,printf=quiet,master_grid=recovered)
        self.assertTrue(result)

    def test_09_empty_outer_source(self):
        a,_,pc,g,_,_,_=make_case()
        for arr in [np.full_like(a,np.nan),np.full_like(a,np.inf)]:
            self.assertEqual(NS['generate_coarse_outside_landscape'](arr,pc,2,printf=quiet,master_grid=g),[])

    def test_10_invalid_scales(self):
        a,_,pc,g,_,_,_=make_case()
        for scale in [0,-1,float('nan'),float('inf')]:
            with self.subTest(scale=scale):
                with self.assertRaises(ValueError):NS['_align_coarse_background_origin'](pc,scale,8)
                with self.assertRaises(ValueError):NS['_align_coarse_background_origin'](pc,2,scale)
                with self.assertRaises(ValueError):NS['_outside_landscape_raster_frame'](a,pc,scale,g)

    def test_11_invalid_or_stale_master_grid(self):
        a,_,pc,g,_,_,_=make_case()
        changes=[('resolution',4),('rows',g['rows']+1),('cols',g['cols']-1),
                 ('min_x',g['min_x']+2),('min_y',float('nan')),
                 ('origin_semantics','pixel_center'),('row_order','north_down'),('xy_units','feet')]
        for key,value in changes:
            bad=dict(g);bad[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):NS['_outside_landscape_raster_frame'](a,pc,2,bad)
        with self.assertRaises(ValueError):NS['_outside_landscape_raster_frame'](a,pc,2,{})

    def test_12_bad_detail_extents(self):
        a,_,pc,g,_,_,_=make_case();pc.width+=2
        with self.assertRaises(ValueError):NS['_outside_landscape_raster_frame'](a,pc,2,g)

    def test_13_single_finite_source_cell(self):
        a,_,pc,g,p,ll,v=make_case(r0=4,c0=7,r1=5,c1=8)
        result=NS['generate_coarse_outside_landscape'](a,pc,2,world_half_extent_m=64,printf=quiet,master_grid=g)
        self.assertGreater(len(result),0)
        np.testing.assert_allclose([s['value'] for s in result],a[4,7],atol=2e-5)

    def test_14_source_hooks(self):
        gen=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='generate_course')
        calls=[n for n in ast.walk(gen) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
        aligns=[n for n in calls if n.func.id=='_align_coarse_background_origin']
        self.assertEqual(len(aligns),1)
        self.assertEqual([ast.unparse(a) for a in aligns[0].args],['background_pc','image_scale','background_scale'])
        outs=[n for n in calls if n.func.id=='generate_coarse_outside_landscape']
        self.assertEqual(len(outs),1)
        kw={k.arg:ast.unparse(k.value) for k in outs[0].keywords}
        self.assertEqual(kw['master_grid'],'master_grid')
        # The runtime dependency is this existing module: no new hidden import needed.
        self.assertIn('from infill_image import infill_image_scipy',TEXT)

    def test_15_water_mask_and_input_preservation(self):
        a,full,pc,g,p,ll,v=make_case()
        mask=np.full(full.shape+(3,),255,dtype=np.uint8)
        mask[~v]=[0,0,255];mask[8:13,12:17]=[255,0,0]
        orig_full=full.copy();orig_mask=mask.copy()
        for fill,purge in [(False,False),(True,False),(False,True)]:
            detail,bg,_=infill_image_scipy(full[:,:,None],mask,background_ratio=4,
                fill_water=fill,purge_water=purge,printf=quiet)
            oldbg=bg.copy();bp=GeoPointCloud();bp.addFromImage(bg,8,ll,p)
            NS['_align_coarse_background_origin'](bp,2,8)
            np.testing.assert_array_equal(bg,oldbg)
            np.testing.assert_array_equal(full,orig_full);np.testing.assert_array_equal(mask,orig_mask)
            if purge:self.assertTrue(np.all(np.isnan(detail[8:13,12:17,0])))

    def test_16_python_311_syntax(self):
        ast.parse(TEXT,feature_version=(3,11))


if __name__=='__main__':
    unittest.main(verbosity=2)
