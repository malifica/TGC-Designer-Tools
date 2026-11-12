"""Behavioral checks for source-derived heightmap-scale recommendations."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine
from rasterio.transform import from_origin

from tgc_source_scale import (
    inspect_dem_sources, inspect_lidar_points, make_scale_decision,
    normalize_scale_request, resolve_source_scale,
)


QUIET = lambda *args: None


def cloud(spacing, length=160.0, classification=2):
    axes = np.arange(0.125, length, spacing)
    x, y = np.meshgrid(axes, axes)
    return np.column_stack((x.ravel(), y.ravel(), np.full(x.size, 20.0),
                            np.zeros(x.size), np.full(x.size, classification)))


class ScaleChoiceTests(unittest.TestCase):
    def test_auto_and_manual_validation(self):
        for value in (None, "", "  AUTO  "):
            self.assertEqual(normalize_scale_request(value), "Auto")
        for value in (0.5, "1.5", 6):
            self.assertEqual(normalize_scale_request(value), float(value))
        for value in (True, False, 0, -1, "bad", float("nan"), "inf", 6.01):
            with self.assertRaises(ValueError, msg=repr(value)):
                normalize_scale_request(value)

    def test_decision_records_actual_choice_and_source(self):
        assessment = {"recommended_scale": 1.0, "minimum_scale": 1.0,
                      "notes": ["source information"]}
        automatic = make_scale_decision("Auto", assessment)
        manual = make_scale_decision("2", assessment)
        self.assertEqual(automatic["mode"], "auto")
        self.assertEqual(automatic["selected_scale"], 1)
        self.assertEqual(manual["mode"], "manual")
        self.assertEqual(manual["selected_scale"], 2)
        assessment["notes"].append("later change")
        self.assertEqual(len(automatic["assessment"]["notes"]), 1)
        json.dumps(automatic, allow_nan=False)
        with self.assertRaisesRegex(ValueError, "at least 1"):
            resolve_source_scale(0.5, assessment)


class DemSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def raster(self, name, spacing=1.0, crs="EPSG:32618", transform=None):
        path = self.root / name
        if transform is None:
            transform = from_origin(612000, 4546000, spacing, spacing)
        with rasterio.open(path, "w", driver="GTiff", width=16, height=20,
                           count=1, dtype="float32", crs=crs,
                           transform=transform) as dst:
            dst.write(np.arange(320, dtype="float32").reshape(20, 16), 1)
            dst.set_band_unit(1, "m")
        return path

    def test_native_dem_inspection_does_not_read_pixels(self):
        path = self.raster("native.tif")
        original_open = rasterio.open

        class HeaderOnly:
            def __init__(self, *args, **kwargs):
                self.dataset = original_open(*args, **kwargs)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.dataset.close()
            def __getattr__(self, name):
                if name in ("read", "read_masks", "dataset_mask"):
                    raise AssertionError("Source inspection must not read raster pixels")
                return getattr(self.dataset, name)

        with patch.object(rasterio, "open", HeaderOnly):
            result = inspect_dem_sources([path], printf=QUIET)
        self.assertEqual(result["recommended_scale"], 1.0)
        self.assertEqual(result["minimum_scale"], 1.0)
        self.assertEqual(result["dem_merge_resolution"], [1.0, 1.0])
        self.assertEqual(result["files"][0]["width"], 16)
        self.assertEqual(result["files"][0]["size_bytes"], path.stat().st_size)
        json.dumps(result, allow_nan=False)

    def test_mixed_tiles_use_coarsest_independent_of_file_order(self):
        fine = self.raster("fine.tif", 0.5)
        coarse = self.raster("coarse.tif", 2)
        results = [inspect_dem_sources(paths, printf=QUIET) for paths in ([fine, coarse], [coarse, fine])]
        for result in results:
            self.assertEqual(result["recommended_scale"], 2)
            self.assertEqual(result["minimum_scale"], 2)
            self.assertEqual(result["dem_merge_resolution"], [2, 2])
            self.assertTrue(result["statistics"]["mixed_resolution"])
            self.assertTrue(result["notes"])

    def test_non_square_uses_coarser_axis(self):
        path = self.raster("rectangle.tif", transform=from_origin(612000, 4546000, 1, 2))
        result = inspect_dem_sources([path], printf=QUIET)
        self.assertEqual(result["recommended_scale"], 2)
        self.assertEqual(result["dem_merge_resolution"], [1, 2])
        self.assertTrue(result["statistics"]["non_square_pixels"])

    def test_survey_feet_are_converted_not_labelled_metres(self):
        path = self.raster("feet.tif", crs="EPSG:2278", spacing=3)
        result = inspect_dem_sources([path], printf=QUIET)
        self.assertAlmostEqual(result["recommended_scale"], 3 * 1200 / 3937, places=10)
        self.assertEqual(result["dem_merge_resolution"], [3, 3])

    def test_geographic_pixels_are_measured_on_earth(self):
        path = self.raster("degrees.tif", crs="EPSG:4326", transform=from_origin(-73.7, 41.1, 0.00001, 0.00001))
        result = inspect_dem_sources([path], printf=QUIET)
        self.assertGreater(result["recommended_scale"], 1.0)
        self.assertLess(result["recommended_scale"], 1.2)
        self.assertAlmostEqual(result["dem_merge_resolution"][0], 0.00001)

    def test_unsupported_dem_geometry_and_coarse_source_rejected_before_build(self):
        for name, transform in (("rotated.tif", Affine(1, .1, 612000, .2, -1, 4546000)),
                                ("south_up.tif", Affine(1, 0, 612000, 0, 1, 4546000))):
            with self.subTest(name=name):
                path = self.raster(name, transform=transform)
                with self.assertRaisesRegex(ValueError, "north-up"):
                    inspect_dem_sources([path], printf=QUIET)
        with self.assertRaisesRegex(ValueError, "up to 6 m"):
            inspect_dem_sources([self.raster("coarse10.tif", spacing=10)], printf=QUIET)

    def test_missing_or_mixed_crs_is_not_guessed(self):
        no_crs = self.raster("missing.tif", crs=None)
        with self.assertRaisesRegex(ValueError, "no CRS"):
            inspect_dem_sources([no_crs], printf=QUIET)
        a = self.raster("a.tif")
        b = self.raster("b.tif", crs="EPSG:32617")
        with self.assertRaisesRegex(ValueError, "same coordinate system"):
            inspect_dem_sources([a, b], printf=QUIET)


class LidarSourceTests(unittest.TestCase):
    def test_regular_clouds_choose_supported_working_scale(self):
        for spacing in (0.5, 1.0, 2.0, 4.0):
            with self.subTest(spacing=spacing):
                points = cloud(spacing)
                result = inspect_lidar_points(points, printf=QUIET)
                self.assertEqual(result["recommended_scale"], spacing)
                self.assertEqual(result["statistics"]["ground_point_count"], len(points))
                self.assertLessEqual(result["statistics"]["representative_blocks"], 64)
                json.dumps(result, allow_nan=False)

    def test_duplicate_points_do_not_invent_finer_coverage(self):
        original = cloud(2.0)
        duplicate = np.repeat(original, 12, axis=0)
        result = inspect_lidar_points(duplicate, printf=QUIET)
        self.assertEqual(result["recommended_scale"], 2.0)

    def test_canopy_density_does_not_stand_in_for_ground_density(self):
        sparse_ground = cloud(2.0)
        dense_canopy = cloud(0.25, classification=5)
        result = inspect_lidar_points(np.concatenate((sparse_ground, dense_canopy)), printf=QUIET)
        self.assertEqual(result["recommended_scale"], 2.0)
        self.assertEqual(result["statistics"]["ground_point_count"], len(sparse_ground))

    def test_dense_corner_does_not_hide_sparse_wider_area(self):
        sparse_ground = cloud(2.0)
        dense_corner = cloud(0.125, length=20.0)
        result = inspect_lidar_points(np.concatenate((sparse_ground, dense_corner)), printf=QUIET)
        self.assertEqual(result["recommended_scale"], 2.0)

    def test_translation_and_file_order_do_not_change_supported_spacing(self):
        points = cloud(1.0)
        shifted = points.copy()
        shifted[:, :2] += (612340.3, 4545000.8)
        np.random.default_rng(12).shuffle(shifted)
        self.assertEqual(inspect_lidar_points(shifted, printf=QUIET)["recommended_scale"], 1.0)

    def test_source_points_are_never_quantized_or_modified(self):
        points = cloud(1.0)
        before = points.copy()
        points.flags.writeable = False
        metadata = {"origin": Path("example.laz"), "nominal_density": 20}
        result = inspect_lidar_points(points, source_metadata=metadata, printf=QUIET)
        np.testing.assert_array_equal(points, before)
        self.assertEqual(result["recommended_scale"], 1.0)
        self.assertEqual(result["source_metadata"]["origin"], "example.laz")
        json.dumps(result, allow_nan=False)

    def test_class_8_ground_is_supported_and_non_finite_points_ignored(self):
        points = cloud(1.0, classification=8)
        bad = np.array([[np.nan, 1, 20, 0, 2], [1, np.inf, 20, 0, 8], [1, 1, np.nan, 0, 2]])
        result = inspect_lidar_points(np.concatenate((points, bad)), printf=QUIET)
        self.assertEqual(result["recommended_scale"], 1.0)
        self.assertEqual(result["statistics"]["ground_point_count"], len(points))

    def test_unclassified_source_cannot_be_mislabelled_as_ground(self):
        with self.assertRaisesRegex(ValueError, "No finite classified ground"):
            inspect_lidar_points(cloud(0.5, classification=1), printf=QUIET)

    def test_sparse_source_has_explicit_low_confidence(self):
        result = inspect_lidar_points(cloud(12.0, length=160), printf=QUIET)
        self.assertEqual(result["recommended_scale"], 4.0)
        self.assertEqual(result["confidence"], "low")
        self.assertFalse(result["statistics"]["coverage_supported"])
        self.assertTrue(any("gaps" in note.lower() for note in result["notes"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
