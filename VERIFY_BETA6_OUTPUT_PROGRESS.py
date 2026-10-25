"""Output writer and projection regression checks; no downloads or source mutation."""
from pathlib import Path
import ast
import importlib.util
import json
import math
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np
import pyproj

import tgc_output_progress as out
from GeoPointCloud import GeoPointCloud


class OutputTests(unittest.TestCase):
    def pc(self, epsg=32610):
        p=GeoPointCloud();p.proj=pyproj.Proj('EPSG:'+str(epsg));p.origin=(700000.,4000000.);return p

    def test_01_projection_identical(self):
        p=self.pc();q=out.image_projector(p)
        for lat in (0.,37.31415,39.33,70.):
            for lon in (-122.5001,-120.,-100.):
                self.assertEqual(p.latlonToProj(lat,lon),q.latlonToProj(lat,lon))
                for s in (0.5,1.,2.,6.):
                    self.assertEqual(p.latlonToCV2(lat,lon,s,2.,-2.),q.latlonToCV2(lat,lon,s,2.,-2.))

    def test_02_original_not_modified(self):
        p=self.pc();before=dict(vars(p));out.image_projector(p);self.assertEqual(vars(p),before)

    def test_03_specialized_projector_preserved(self):
        class Custom(GeoPointCloud):pass
        p=Custom();self.assertIs(out.image_projector(p),p)

    def test_04_instance_override_preserved(self):
        p=self.pc();p.latlonToProj=lambda a,b:(a,b);self.assertIs(out.image_projector(p),p)

    def test_05_transform_created_once(self):
        with mock.patch.object(pyproj.Transformer,'from_proj', wraps=pyproj.Transformer.from_proj) as f:
            q=out.image_projector(self.pc())
            for _ in range(50):q.latlonToCV2(39.,-120.,2.)
            self.assertEqual(f.call_count,1)

    def test_06_new_origin_retained(self):
        p=self.pc();p.origin=(100.,200.);q=out.image_projector(p)
        self.assertEqual(p.latlonToCV2(39.,-120.,2.),q.latlonToCV2(39.,-120.,2.))

    def test_07_separate_crs(self):
        for epsg in (32610,32614,26910,3857):
            p=self.pc(epsg);q=out.image_projector(p)
            self.assertEqual(p.latlonToCV2(39.3,-120.1,1.),q.latlonToCV2(39.3,-120.1,1.))

    def test_08_npy_payload_and_format(self):
        with tempfile.TemporaryDirectory() as d:
            a=np.arange(128,dtype=np.float32).reshape(16,8);a[4,2]=np.nan
            data=dict(heightmap=a[::2,::2],visual=np.flip(a,0),trees=[(1.,2.,3.,4.)],projection=self.pc().proj,pointcloud=[],image_scale=2.)
            normal=Path(d)/'normal.npy';np.save(normal,data)
            fixed=Path(d)/'heightmap.npy';out.save_npy(fixed,data)
            self.assertEqual(normal.read_bytes(),fixed.read_bytes())
            loaded=np.load(fixed,allow_pickle=True).item()
            np.testing.assert_array_equal(loaded['heightmap'],data['heightmap'])
            self.assertEqual(loaded['trees'],data['trees'])

    def test_09_npy_failure_preserves_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'heightmap.npy';p.write_bytes(b'existing')
            with mock.patch.object(np,'save',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):out.save_npy(p,{'a':1})
            self.assertEqual(p.read_bytes(),b'existing');self.assertEqual(len(list(Path(d).iterdir())),1)

    def test_10_npy_replace_failure_preserves_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'heightmap.npy';p.write_bytes(b'existing')
            with mock.patch.object(out.os,'replace',side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):out.save_npy(p,{'a':1})
            self.assertEqual(p.read_bytes(),b'existing');self.assertEqual(len(list(Path(d).iterdir())),1)

    def test_11_png_pixel_identity(self):
        with tempfile.TemporaryDirectory() as d:
            im=np.random.default_rng(23).random((95,107,3),dtype=np.float32)*255
            a=Path(d)/'normal.png';b=Path(d)/'mask.png'
            cv2.imwrite(str(a),im);out.save_png(b,im)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            np.testing.assert_array_equal(cv2.imread(str(a)),cv2.imread(str(b)))

    def test_12_png_error_preserves_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'mask.png';p.write_bytes(b'existing')
            with mock.patch.object(cv2,'imwrite',return_value=False):
                with self.assertRaises(OSError):out.save_png(p,np.zeros((2,2,3),np.uint8))
            self.assertEqual(p.read_bytes(),b'existing');self.assertEqual(len(list(Path(d).iterdir())),1)

    def test_13_progress_monotonic(self):
        log=[];p=out.OutputProgress(log.append);p.stage(50,'mask');p.stage(30,'other');p.finish()
        events=[out.decode_event(x) for x in log if out.decode_event(x)]
        self.assertEqual([x['percent'] for x in events],[0,50,50,100]);self.assertTrue(events[-1]['done'])

    def test_14_measured_byte_reporting(self):
        log=[];p=out.OutputProgress(log.append)
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'heightmap.npy';out.save_npy(dest,{'heightmap':np.zeros((256,256),np.float32)},p)
        self.assertTrue(any('MiB' in x for x in log));self.assertEqual(p.percent,0)

    def test_15_parser_ignores_unrelated_text(self):
        for s in ('normal log',out.PREFIX+'{broken',out.PREFIX+'{}',out.PREFIX+'{"percent":101}'):
            self.assertIsNone(out.decode_event(s))

    def test_16_no_generated_terrain_or_tree_imports(self):
        source=Path(out.__file__).read_text()
        self.assertNotIn('import tgc_image_terrain',source);self.assertNotIn('import tree_mapper',source)

    def test_17_integration_wiring(self):
        root=Path(__file__).resolve().parent
        lidar=(root/'lidar_map_api.py').read_text(encoding='utf-8-sig')
        gui=(root/'tgc_gui.py').read_text(encoding='utf-8-sig')
        ast.parse(lidar);ast.parse(gui)
        self.assertIn('tgc_output_progress.image_projector(pc, output_progress)',lidar)
        self.assertIn('tgc_output_progress.image_projector(grid_pc, output_progress)',lidar)
        self.assertIn('lidarPrintf = lidarOutputProgress.printf',gui)
        self.assertIn('lidarOutputProgress.pack(',gui)
        self.assertNotIn('deformable_course_terrain',gui)
        # The image paths still receive complete relation-bearing results.
        calls=[n for n in ast.walk(ast.parse(lidar)) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='addOSMToImage']
        self.assertEqual(len(calls),3)
        self.assertTrue(all(not(isinstance(n.args[0],ast.Attribute) and n.args[0].attr=='ways') for n in calls))


if __name__=='__main__':unittest.main(verbosity=2)
