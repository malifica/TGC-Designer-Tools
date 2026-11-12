"""Exercise the LiDAR confirmation boundary and retained source-grid contract.

No Tk windows, network requests, or downloaded test data are required.  Density
policy tests are separate; this verifies that source inspection cannot rasterize
or write a project, and that the confirmed cloud is read and quantized once.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pyproj

from GeoPointCloud import GeoPointCloud
import lidar_map_api as api


def quiet(*_args, **_kwargs):
    pass


def cloud():
    pc = GeoPointCloud()
    pc.proj = pyproj.Proj("EPSG:32618")
    pc.origin = (611000.0, 4545000.0)
    row, col = np.mgrid[0:20, 0:20]
    pc.point_matrix = np.column_stack((
        col.ravel() + 0.25,
        row.ravel() + 0.25,
        60.0 + 0.1 * row.ravel() + 0.07 * col.ravel(),
        1.0 + (row.ravel() + col.ravel()) % 13,
        np.full(row.size, 2),
    ))
    return pc


def assessment():
    return {
        "version": "fixture",
        "source_type": "LiDAR",
        "recommended_scale": 1.0,
        "minimum_scale": 0.0,
        "confidence": "high",
        "summary": "Fixture ground coverage",
        "reason": "Independent scale-policy verification covers the estimator.",
        "notes": [],
        "statistics": {"ground_points": 400},
    }


def decision(scale=1.0):
    return {
        "version": "fixture",
        "mode": "auto",
        "selected_scale": float(scale),
        "assessment": assessment(),
    }


class SourcePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "project"

    def inspect(self, pc=None, **kwargs):
        pc = cloud() if pc is None else pc
        with mock.patch.object(api, "load_usgs_directory", return_value=pc), \
                mock.patch("tgc_source_scale.inspect_lidar_points", return_value=assessment()):
            return api.inspect_lidar_source(str(self.source), printf=quiet, **kwargs)

    def prepare(self, pack, chosen=None, output=None, **kwargs):
        chosen = decision() if chosen is None else chosen
        with mock.patch.object(api.OSMTGC, "getOSMData", return_value=None):
            return api.prepare_lidar_previews(
                str(self.source), chosen["selected_scale"],
                str(self.output if output is None else output),
                printf=quiet, prepared_source=pack, scale_decision=chosen,
                **kwargs,
            )

    def test_inspection_preserves_raw_coordinates_and_creates_no_grid_or_files(self):
        pc = cloud()
        before = pc.points().copy()
        with mock.patch.object(api, "load_usgs_directory", return_value=pc) as read, \
                mock.patch("tgc_source_scale.inspect_lidar_points", return_value=assessment()) as inspect, \
                mock.patch.object(pc, "pointsAsCV2", side_effect=AssertionError("Early rasterization")), \
                mock.patch.object(api.tgc_tools, "create_directory", side_effect=AssertionError("Early project write")), \
                mock.patch.object(api.OSMTGC, "getOSMData", side_effect=AssertionError("Early preview")):
            pack = api.inspect_lidar_source(str(self.source), printf=quiet)
        read.assert_called_once()
        self.assertIs(inspect.call_args.args[0], pc)
        self.assertIs(pack["pc"], pc)
        self.assertFalse(pack["consumed"])
        self.assertFalse(self.output.exists())
        np.testing.assert_array_equal(before, pc.points())

    def test_confirmation_reuses_one_raw_read_and_quantizes_once(self):
        pc = cloud()
        with mock.patch.object(api, "load_usgs_directory", return_value=pc) as read, \
                mock.patch("tgc_source_scale.inspect_lidar_points", return_value=assessment()), \
                mock.patch.object(pc, "pointsAsCV2", wraps=pc.pointsAsCV2) as quantize:
            pack = api.inspect_lidar_source(str(self.source), printf=quiet)
            self.assertEqual(quantize.call_count, 0)
            prepared = self.prepare(pack)
            read.assert_called_once()
            quantize.assert_called_once_with(1.0)
            with self.assertRaisesRegex(ValueError, "already been prepared"):
                self.prepare(pack)
            self.assertEqual(quantize.call_count, 1)
        self.assertEqual(prepared["sample_scale"], 1.0)
        self.assertEqual(prepared["scale_decision"], decision())
        self.assertTrue(pack["consumed"])

    def test_changed_scale_or_source_rejects_before_project_write(self):
        pack = self.inspect()
        with self.assertRaisesRegex(ValueError, "does not match"):
            api.prepare_lidar_previews(
                str(self.source), 2.0, str(self.output),
                prepared_source=pack, scale_decision=decision(1.0), printf=quiet,
            )
        with self.assertRaisesRegex(ValueError, "directory changed"):
            api.prepare_lidar_previews(
                str(self.root / "different"), 1.0, str(self.output),
                prepared_source=pack, scale_decision=decision(), printf=quiet,
            )
        with self.assertRaisesRegex(ValueError, "overrides changed"):
            self.prepare(pack, force_epsg=32618)
        self.assertFalse(pack["consumed"])
        self.assertFalse(self.output.exists())

    def test_invalid_scales_and_decision_records_never_consume_source(self):
        pack = self.inspect()
        for scale in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                api.prepare_lidar_previews(
                    str(self.source), scale, str(self.output),
                    prepared_source=pack, printf=quiet,
                )
        with self.assertRaises(ValueError):
            self.prepare(pack, chosen={"selected_scale": 1.0, "bad": float("nan")})
        self.assertFalse(pack["consumed"])
        self.assertFalse(self.output.exists())

    def generate(self, prepared):
        pc = prepared["pc"]
        height, width = prepared["course_image"].shape[:2]
        with mock.patch.object(api.tree_mapper, "getTreeCoordinates", return_value=[]), \
                mock.patch.object(api.lidar_feature_filter, "detect_lidar_building_footprints", return_value=[]):
            api.generate_lidar_heightmap(
                pc, prepared["img_points"], prepared["sample_scale"],
                prepared["output_dir_path"], crop_bounds=(0, 0, width, height),
                printf=quiet, scale_decision=prepared.get("scale_decision"),
            )
        path = Path(prepared["output_dir_path"]) / "heightmap.npy"
        return np.load(str(path), allow_pickle=True).item()

    def test_confirmed_scale_is_saved_and_matches_legacy_numerical_output(self):
        chosen = decision()
        auto = self.generate(self.prepare(self.inspect(), chosen=chosen))
        legacy_output = self.root / "legacy"
        with mock.patch.object(api, "load_usgs_directory", return_value=cloud()), \
                mock.patch.object(api.OSMTGC, "getOSMData", return_value=None):
            legacy_preview = api.prepare_lidar_previews(
                str(self.source), 1.0, str(legacy_output), printf=quiet,
            )
        legacy = self.generate(legacy_preview)
        self.assertEqual(auto["source_scale_decision"], chosen)
        self.assertNotIn("source_scale_decision", legacy)
        self.assertEqual(auto["image_scale"], 1.0)
        self.assertEqual(auto["master_grid"], legacy["master_grid"])
        np.testing.assert_array_equal(auto["heightmap"], legacy["heightmap"])
        np.testing.assert_array_equal(auto["visual"], legacy["visual"])
        self.assertEqual((self.output / "mask.png").read_bytes(),
                         (legacy_output / "mask.png").read_bytes())
        json.dumps(auto["source_scale_decision"], allow_nan=False)

    def test_tree_only_saves_separate_scale_and_preserves_dem_grid_and_mask(self):
        self.output.mkdir()
        projection = pyproj.Proj("EPSG:32618")
        original = {
            "source": "DEM", "image_scale": 2.0,
            "heightmap": np.arange(24, dtype=np.float32).reshape(4, 6, 1),
            "visual": np.zeros((4, 6, 3), dtype=np.float32),
            "projection": projection,
            "master_grid": {"resolution": 2.0, "rows": 4, "cols": 6},
            "source_scale_decision": {"mode": "auto", "selected_scale": 2.0},
            "trees": [],
        }
        dem_path = self.output / "heightmap.npy"
        np.save(str(dem_path), original)
        mask_path = self.output / "mask.png"
        mask_path.write_bytes(b"unchanged existing mask")
        pack = self.inspect()
        chosen = decision(1.0)

        def fake_prepare(*args, **kwargs):
            self.assertIs(kwargs["prepared_source"], pack)
            self.assertEqual(kwargs["scale_decision"], chosen)
            return {"pc": cloud(), "img_points": np.empty((0, 5)),
                    "osm_result": None, "scale_decision": chosen}

        def fake_generate(*args, **kwargs):
            self.assertEqual(kwargs["scale_decision"], chosen)
            np.save(str(Path(args[3]) / "heightmap.npy"), {
                "projection": projection,
                "trees": [(611010.0, 4545010.0, 3.0, 11.0)],
            })

        with mock.patch.object(api, "prepare_lidar_previews", side_effect=fake_prepare), \
                mock.patch.object(api, "generate_lidar_heightmap", side_effect=fake_generate):
            count = api.attach_lidar_trees_to_existing_dem(
                str(self.source), str(dem_path), sample_scale=1.0,
                prepared_source=pack, scale_decision=chosen, printf=quiet,
            )
        updated = np.load(str(dem_path), allow_pickle=True).item()
        self.assertEqual(count, 1)
        self.assertEqual(updated["image_scale"], 2.0)
        self.assertEqual(updated["master_grid"], original["master_grid"])
        self.assertEqual(updated["source_scale_decision"], original["source_scale_decision"])
        self.assertEqual(updated["tree_source_scale_decision"], chosen)
        self.assertEqual(updated["tree_source_sample_scale"], 1.0)
        np.testing.assert_array_equal(updated["heightmap"], original["heightmap"])
        np.testing.assert_array_equal(updated["visual"], original["visual"])
        self.assertEqual(mask_path.read_bytes(), b"unchanged existing mask")
        self.assertFalse((self.output / "_TGC_LIDAR_TREE_EXTRACT").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
