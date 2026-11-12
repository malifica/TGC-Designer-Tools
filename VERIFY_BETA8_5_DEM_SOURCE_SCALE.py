"""Exercise confirmed DEM scale decisions on real raster files and saved grids."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_origin

import dem_map_api as dem


def quiet(*_args):
    pass


class ConfirmedDEMScaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tgc_dem_scale_")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, values, scale=(1.0, 1.0), origin=(500000.0, 4500000.0),
              crs="EPSG:32618", unit="metre"):
        values = np.asarray(values, dtype=np.float32)
        path = self.root / name
        with rasterio.open(path, "w", driver="GTiff", width=values.shape[1],
                           height=values.shape[0], count=1, dtype="float32",
                           crs=crs, transform=from_origin(*origin, *scale),
                           nodata=np.nan) as dst:
            dst.write(values, 1)
            dst.set_band_unit(1, unit)
        return str(path)

    def decision(self, paths, minimum=None, selected=None):
        # Independent metadata arithmetic for the backend integration tests.
        # The policy module has its own inspector/density tests.
        sizes = []
        physical = []
        for path in paths:
            with rasterio.open(path) as src:
                sizes.append(tuple(float(v) for v in src.res))
                crs = pyproj.CRS.from_user_input(src.crs)
                if crs.is_projected:
                    factor = float(crs.axis_info[0].unit_conversion_factor)
                    physical.append(tuple(v * factor for v in src.res))
                else:
                    geod = crs.get_geod()
                    x = (src.bounds.left + src.bounds.right) / 2.0
                    y = (src.bounds.bottom + src.bounds.top) / 2.0
                    physical.append((abs(geod.inv(x, y, x + src.res[0], y)[2]),
                                     abs(geod.inv(x, y, x, y + src.res[1])[2])))
                source_crs = str(src.crs)
        if minimum is None:
            minimum = max(max(v) for v in physical)
        if selected is None:
            selected = minimum
        return {
            "version": "test_decision_v1", "mode": "auto",
            "selected_scale": float(selected),
            "assessment": {
                "source_type": "DEM", "source_count": len(paths),
                "minimum_scale": float(minimum), "recommended_scale": float(minimum),
                "source_crs": source_crs,
                "dem_merge_resolution": [max(v[i] for v in sizes) for i in (0, 1)],
                "reason": "Synthetic raster metadata test",
            },
        }

    def load(self, paths, decision):
        return dem._load_dem(paths, target_sample_scale=decision["selected_scale"],
                             source_scale_decision=decision, printf=quiet)

    def test_native_metres_preserve_every_elevation_and_origin(self):
        values = (np.arange(144, dtype=np.float32).reshape(12, 12) / 7.0) + 50.0
        values[4:6, 5:7] = np.nan
        path = self.write("native.tif", values)
        decision = self.decision([path])
        untouched = copy.deepcopy(decision)
        actual, scale, pc = self.load([path], decision)
        np.testing.assert_array_equal(actual, np.flipud(values))
        self.assertEqual(scale, 1.0)
        self.assertEqual(pc.origin, (500000.0, 4499988.0))
        self.assertEqual(decision, untouched)
        self.assertEqual(pc.source_scale_decision["resolved_scale"], scale)

    def test_manual_coarser_retains_existing_reducer(self):
        values = np.arange(256, dtype=np.float32).reshape(16, 16) / 4 + 20
        path = self.write("reduce.tif", values)
        plan = self.decision([path], selected=2.0)
        plan["mode"] = "manual"
        actual, scale, pc = self.load([path], plan)
        legacy, old_scale, old_pc = dem._load_dem([path], 2.0, printf=quiet)
        np.testing.assert_array_equal(actual, legacy)
        self.assertEqual((scale, pc.origin), (old_scale, old_pc.origin))
        self.assertEqual(actual.shape, (8, 8))

    def test_mixed_tiles_are_independent_of_selection_order(self):
        fine = self.write("fine.tif", np.full((16, 16), 30), scale=(0.5, 0.5))
        coarse = self.write("coarse.tif", np.full((4, 4), 60), scale=(2, 2),
                            origin=(500008.0, 4500000.0))
        a, scale_a, pc_a = self.load([fine, coarse], self.decision([fine, coarse]))
        b, scale_b, pc_b = self.load([coarse, fine], self.decision([coarse, fine]))
        np.testing.assert_array_equal(a, b)
        self.assertEqual(a.shape, (4, 8))
        self.assertEqual((scale_a, scale_b), (2.0, 2.0))
        self.assertEqual(pc_a.origin, pc_b.origin)
        np.testing.assert_array_equal(a[:, :4], np.full((4, 4), 30, np.float32))
        np.testing.assert_array_equal(a[:, 4:], np.full((4, 4), 60, np.float32))

    def test_non_square_grid_uses_confirmed_coarser_axis(self):
        path = self.write("rectangular.tif", np.full((8, 16), 40), scale=(1, 2))
        actual, scale, pc = self.load([path], self.decision([path]))
        self.assertEqual(scale, 2.0)
        self.assertEqual(actual.shape, (8, 8))
        np.testing.assert_array_equal(actual, np.full((8, 8), 40, np.float32))
        self.assertEqual((pc.width, pc.height), (16.0, 16.0))

    def test_feet_crs_uses_exact_confirmed_metric_spacing_and_vertical_units(self):
        path = self.write("feet.tif", np.full((16, 16), 100), scale=(3, 3),
                          origin=(1000000.0, 200000.0), crs="EPSG:2263", unit="foot")
        plan = self.decision([path])
        actual, scale, pc = self.load([path], plan)
        self.assertAlmostEqual(scale, 3 * 1200.0 / 3937.0, places=12)
        self.assertAlmostEqual(pc.width / actual.shape[1], scale, places=9)
        self.assertAlmostEqual(pc.height / actual.shape[0], scale, places=9)
        np.testing.assert_allclose(actual[np.isfinite(actual)], 30.48, atol=1e-5)

    def test_geographic_crs_uses_exact_confirmed_metric_spacing(self):
        path = self.write("geographic.tif", np.full((16, 16), 80), scale=(0.000009, 0.000009),
                          origin=(-73.7, 41.0), crs="EPSG:4326")
        plan = self.decision([path])
        actual, scale, pc = self.load([path], plan)
        self.assertAlmostEqual(scale, plan["selected_scale"], places=12)
        self.assertAlmostEqual(pc.width / actual.shape[1], scale, places=8)
        self.assertAlmostEqual(pc.height / actual.shape[0], scale, places=8)
        np.testing.assert_allclose(actual[np.isfinite(actual)], 80, atol=1e-5)

    def test_invalid_confirmation_fails_before_raster_open(self):
        path = self.write("bad.tif", np.full((8, 8), 10))
        plan = self.decision([path], selected=0.5)
        with patch.object(dem.rasterio, "open", side_effect=AssertionError("raster opened")):
            with self.assertRaisesRegex(ValueError, "native source spacing"):
                self.load([path], plan)

    def test_changed_source_spacing_fails_before_mosaic(self):
        path = self.write("changed.tif", np.full((8, 8), 10))
        plan = self.decision([path])
        self.write("changed.tif", np.full((8, 8), 10), scale=(2, 2))
        with patch.object(dem, "merge", side_effect=AssertionError("raster merged")):
            with self.assertRaisesRegex(RuntimeError, "spacing changed"):
                self.load([path], plan)

    def test_decision_survives_preview_crop_and_saved_master_grid(self):
        values = np.arange(100, dtype=np.float32).reshape(10, 10) + 30
        path = self.write("save.tif", values)
        plan = self.decision([path])
        with patch.object(dem, "_get_osm_for_grid", return_value=None):
            prepared = dem.prepare_dem_previews([path], sample_scale=1,
                source_scale_decision=plan, printf=quiet)
        out = self.root / "project"
        dem.generate_dem_output(prepared, str(out), (2, 1, 9, 8), printf=quiet)
        saved = np.load(out / "heightmap.npy", allow_pickle=True).item()
        self.assertEqual(saved["image_scale"], 1)
        self.assertEqual(saved["source_scale_decision"], prepared["source_scale_decision"])
        self.assertEqual(saved["master_grid"]["resolution"], 1)
        self.assertEqual(saved["master_grid"]["min_x"], 500002)
        self.assertEqual(saved["master_grid"]["min_y"], 4499991)
        np.testing.assert_array_equal(saved["heightmap"][:, :, 0], np.flipud(values)[1:8, 2:9])
        with dem.Image.open(out / "mask.png") as mask:
            self.assertEqual((mask.height, mask.width), saved["heightmap"].shape[:2])

    def test_source_inspection_confirmation_and_actual_grid_agree(self):
        from tgc_source_scale import inspect_dem_sources, make_scale_decision

        cases = [
            {"name": "metric", "scale": (1.0, 1.0)},
            {"name": "fine", "scale": (0.5, 0.5)},
            {"name": "nonsquare", "scale": (1.0, 2.0)},
            {"name": "feet", "scale": (3.0, 3.0), "crs": "EPSG:2263",
             "origin": (1000000.0, 200000.0)},
            {"name": "geographic", "scale": (0.000009, 0.000009), "crs": "EPSG:4326",
             "origin": (-73.7, 41.0)},
        ]
        for case in cases:
            options = dict(case)
            name = options.pop("name")
            with self.subTest(source=name):
                path = self.write(name + "_inspect.tif", np.full((20, 20), 20), **options)
                assessment = inspect_dem_sources([path], printf=quiet)
                decision = make_scale_decision("Auto", assessment)
                actual, scale, pc = self.load([path], decision)
                self.assertEqual(scale, decision["selected_scale"])
                self.assertEqual(pc.source_scale_decision["assessment"], assessment)
                self.assertAlmostEqual(pc.width / actual.shape[1], scale, places=8)
                self.assertAlmostEqual(pc.height / actual.shape[0], scale, places=8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
