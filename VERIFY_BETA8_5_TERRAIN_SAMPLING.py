"""Focused numerical and preservation checks for independent stamp spacing."""
import json
import unittest

import numpy as np

from tgc_terrain_sampling import resolve_brush_scale, resolve_stamp_spacing, sample_terrain_stamps


TERRAIN_SAMPLING_VERIFIER_VERSION = "TGC_BETA8_5_TERRAIN_SAMPLING_V1"


def coordinate_set(stamps):
    return {tuple(point) for point in stamps[:, :2]}


class ResolutionTests(unittest.TestCase):
    def test_source_defaults_and_numeric_spacing(self):
        for value in (None, "", "  ", "Source", " sOuRcE "):
            self.assertEqual(resolve_stamp_spacing(value, 1.5), 1.5)
        self.assertEqual(resolve_stamp_spacing("2.5", 1.0), 2.5)
        self.assertEqual(resolve_stamp_spacing(6, 6), 6.0)

    def test_invalid_source_and_spacing_rejected(self):
        for source in (0, -1, np.nan, np.inf, -np.inf, "bad", None, True, 7):
            with self.subTest(source=source), self.assertRaises(ValueError):
                resolve_stamp_spacing(None, source)
        for spacing in (0, -1, 0.5, 6.001, np.nan, np.inf, "bad", True):
            with self.subTest(spacing=spacing), self.assertRaises(ValueError):
                resolve_stamp_spacing(spacing, 1)

    def test_brush_choice_covers_source_and_spacing(self):
        self.assertEqual(resolve_brush_scale(4, 1, 2), 4)
        self.assertEqual(resolve_brush_scale(1, 1, 2), 2)
        self.assertEqual(resolve_brush_scale(2, 1, 2.5), 3)
        self.assertEqual(resolve_brush_scale(4, 5, 5), 6)
        self.assertEqual(resolve_brush_scale(1, 6, 6), 6)
        for value in (None, "Auto", "bad", -1, 0, 5, np.nan, np.inf):
            with self.subTest(value=value):
                self.assertEqual(resolve_brush_scale(value, 1, 2.5), 3)
        with self.assertRaises(ValueError):
            resolve_brush_scale(6, 2, 1)


class SamplingTests(unittest.TestCase):
    def assert_report(self, stamps, report):
        self.assertEqual(stamps.ndim, 2)
        self.assertEqual(stamps.shape[1], 3)
        self.assertEqual(stamps.dtype, np.float64)
        self.assertTrue(np.all(np.isfinite(stamps)))
        self.assertEqual(report["total_count"], len(stamps))
        self.assertEqual(report["main_lattice_count"] + report["edge_retained_count"], len(stamps))
        self.assertEqual(report["direct_sample_count"] + report["interpolated_sample_count"], len(stamps))
        coordinates = [tuple(value) for value in stamps[:, :2]]
        self.assertEqual(coordinates, sorted(coordinates))
        self.assertEqual(len(coordinates), len(set(coordinates)))
        json.dumps(report, allow_nan=False)

    def test_native_legacy_exact_order_and_values(self):
        source = np.array([[1.25, np.nan, 3.5], [4.75, 5.0, np.inf]])
        before = source.copy()
        expected = np.array([[0, 0, 1.25], [0, 2, 3.5], [1, 0, 4.75], [1, 1, 5.0]])
        for spacing in (None, "Source", "", 1.0):
            stamps, report = sample_terrain_stamps(source, 1, spacing)
            np.testing.assert_array_equal(stamps, expected)
            self.assertEqual(report["mode"], "native")
            self.assertEqual(report["source_finite_count"], 4)
            self.assertEqual(report["edge_retained_count"], 0)
            self.assert_report(stamps, report)
        np.testing.assert_array_equal(source, before)

    def test_integer_ratio_is_exact_and_keeps_last_row_column(self):
        source = np.arange(48, dtype=np.float64).reshape(6, 8) + 0.125
        stamps, report = sample_terrain_stamps(source, 1, 2)
        expected = np.array([(row, col, source[row, col]) for row in (0, 2, 4, 5) for col in (0, 2, 4, 6, 7)])
        np.testing.assert_array_equal(stamps, expected)
        self.assertEqual(report["mode"], "direct")
        self.assertEqual(report["edge_retained_count"], 0)
        self.assertNotIn((0.0, 1.0), coordinate_set(stamps))
        self.assert_report(stamps, report)

    def test_decimal_integer_ratio_uses_original_samples(self):
        source = np.arange(64, dtype=np.float64).reshape(8, 8)
        stamps, report = sample_terrain_stamps(source, 0.1, 0.3)
        expected = np.array([(row, col, source[row, col]) for row in (0, 3, 6, 7) for col in (0, 3, 6, 7)])
        np.testing.assert_array_equal(stamps, expected)
        self.assertEqual(report["mode"], "direct")

    def test_quarter_interior_density_without_false_outer_edges(self):
        source = np.ones((101, 101), dtype=np.float32)
        stamps, report = sample_terrain_stamps(source, 1, 2)
        self.assertEqual(len(stamps), 51 * 51)
        self.assertLess(abs(len(stamps) / source.size - 0.25), 0.01)
        self.assertEqual(report["edge_retained_count"], 0)
        self.assert_report(stamps, report)

    def test_fractional_plane_sampling_and_extent(self):
        rows, columns = np.indices((5, 6), dtype=np.float64)
        source = 100 + 2 * rows + 3 * columns
        before = source.copy()
        stamps, report = sample_terrain_stamps(source, 1, 1.5)
        expected_positions = np.array([(row, col) for row in (0, 1.5, 3, 4) for col in (0, 1.5, 3, 4.5, 5)])
        np.testing.assert_array_equal(stamps[:, :2], expected_positions)
        np.testing.assert_allclose(stamps[:, 2], 100 + 2 * stamps[:, 0] + 3 * stamps[:, 1], rtol=0, atol=1e-12)
        self.assertEqual(report["mode"], "bilinear")
        self.assertEqual(report["interpolated_sample_count"], 11)
        np.testing.assert_array_equal(source, before)
        self.assert_report(stamps, report)

    def test_fractional_values_are_bilinear_not_nearest(self):
        rows, columns = np.indices((3, 3), dtype=np.float64)
        source = rows ** 2 + 5 * columns ** 2
        stamps, report = sample_terrain_stamps(source, 1, 1.5)
        value = stamps[(stamps[:, 0] == 1.5) & (stamps[:, 1] == 1.5), 2]
        np.testing.assert_array_equal(value, [15.0])
        self.assert_report(stamps, report)

    def test_positive_weight_nodata_corner_blocks_interpolation(self):
        source = np.arange(16, dtype=np.float64).reshape(4, 4)
        source[2, 2] = np.nan
        stamps, report = sample_terrain_stamps(source, 1, 1.5)
        self.assertNotIn((1.5, 1.5), coordinate_set(stamps))
        self.assertIn((1.0, 1.0), coordinate_set(stamps))
        self.assert_report(stamps, report)

    def test_zero_weight_nodata_corners_are_ignored(self):
        source = np.arange(9, dtype=np.float64).reshape(3, 3)
        source[:, 1] = np.nan
        stamps, report = sample_terrain_stamps(source, 1, 1.5)
        by_coord = {(row, col): value for row, col, value in stamps}
        self.assertEqual(by_coord[(0, 0)], 0)
        self.assertEqual(by_coord[(1.5, 0)], 4.5)
        self.assertEqual(by_coord[(1.5, 2)], 6.5)
        self.assertEqual(by_coord[(2, 2)], 8)
        self.assertNotIn((1.5, 1.5), by_coord)
        self.assert_report(stamps, report)

    def test_small_real_fraction_keeps_positive_corner_rule(self):
        source = np.arange(9, dtype=np.float64).reshape(3, 3)
        source[2, 0] = np.nan
        spacing = 1.000000000001
        stamps, report = sample_terrain_stamps(source, 1, spacing)
        self.assertEqual(report["mode"], "bilinear")
        self.assertNotIn((spacing, 0.0), coordinate_set(stamps))
        self.assertIn((1.0, 0.0), coordinate_set(stamps))
        self.assert_report(stamps, report)

    def test_all_eight_internal_nodata_neighbours_are_retained(self):
        source = np.full((7, 7), 100.0)
        source[3, 3] = np.nan
        stamps, report = sample_terrain_stamps(source, 1, 3)
        neighbours = {(float(row), float(col)) for row in (2, 3, 4) for col in (2, 3, 4) if (row, col) != (3, 3)}
        self.assertTrue(neighbours <= coordinate_set(stamps))
        self.assertEqual(report["main_lattice_count"], 8)
        self.assertEqual(report["edge_retained_count"], 8)
        self.assertEqual(report["total_count"], 16)
        self.assertNotIn((0.0, 1.0), coordinate_set(stamps))
        self.assert_report(stamps, report)

    def test_exact_edge_samples_are_not_duplicated(self):
        source = np.ones((5, 5), dtype=np.float64)
        source[1, 1] = np.nan
        stamps, report = sample_terrain_stamps(source, 1, 2)
        self.assertEqual(report["main_lattice_count"], 9)
        self.assertEqual(report["edge_retained_count"], 4)
        self.assertEqual(len(stamps), 13)
        self.assert_report(stamps, report)

    def test_single_pixel_and_thin_mask_islands_survive(self):
        source = np.full((7, 7), np.nan)
        source[3, 3] = 12.25
        stamps, report = sample_terrain_stamps(source, 1, 2)
        np.testing.assert_array_equal(stamps, [[3, 3, 12.25]])
        self.assertEqual(report["main_lattice_count"], 0)
        self.assertEqual(report["edge_retained_count"], 1)
        source[3, :] = np.arange(7) + 20
        stamps, report = sample_terrain_stamps(source, 1, 2)
        np.testing.assert_array_equal(stamps, [(3, col, 20 + col) for col in range(7)])
        self.assertEqual(report["edge_retained_count"], 7)
        self.assert_report(stamps, report)

    def test_empty_all_invalid_single_row_and_single_cell(self):
        for shape in ((0, 4), (4, 0), (0, 0), (0, 4, 1)):
            with self.subTest(shape=shape):
                stamps, report = sample_terrain_stamps(np.empty(shape), 1, 2)
                self.assertEqual(stamps.shape, (0, 3))
                self.assert_report(stamps, report)
        stamps, report = sample_terrain_stamps(np.array([[np.nan, np.inf, -np.inf]]), 1, 2)
        self.assertEqual(stamps.shape, (0, 3))
        self.assert_report(stamps, report)
        stamps, report = sample_terrain_stamps(np.array([[9.5]]), 1, 2)
        np.testing.assert_array_equal(stamps, [[0, 0, 9.5]])
        self.assert_report(stamps, report)
        stamps, report = sample_terrain_stamps(np.arange(5).reshape(1, 5), 1, 2)
        np.testing.assert_array_equal(stamps, [[0, 0, 0], [0, 2, 2], [0, 4, 4]])
        self.assertEqual(report["edge_retained_count"], 0)

    def test_readonly_strided_channel_source_is_unchanged(self):
        base = np.arange(48, dtype=np.float32).reshape(6, 8)
        base[1, 2] = np.nan
        source = base[:, ::2, None]
        source.flags.writeable = False
        before = base.copy()
        stamps, report = sample_terrain_stamps(source, 1, 1.5)
        np.testing.assert_array_equal(base, before)
        self.assertFalse(source.flags.writeable)
        self.assertFalse(np.shares_memory(stamps, source))
        self.assertEqual(report["source_shape"], [6, 4])
        self.assert_report(stamps, report)

    def test_masked_input_keeps_mask_and_data(self):
        source = np.ma.array(np.arange(25).reshape(5, 5), mask=False)
        source.mask[2, 2] = True
        before_data, before_mask = source.data.copy(), source.mask.copy()
        stamps, report = sample_terrain_stamps(source, 1, 2)
        self.assertNotIn((2.0, 2.0), coordinate_set(stamps))
        self.assertEqual(report["source_finite_count"], 24)
        np.testing.assert_array_equal(source.data, before_data)
        np.testing.assert_array_equal(source.mask, before_mask)
        self.assert_report(stamps, report)

    def test_invalid_heightmap_shapes_and_types(self):
        for value in (1, [1, 2, 3], np.ones((2, 2, 2)), np.array([["one"]]), np.array([[1j]]), np.array([[object()]])):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                sample_terrain_stamps(value, 1, 2)


if __name__ == "__main__":
    print("Independent terrain stamp spacing: numeric, mask, footprint and preservation checks.")
    unittest.main(verbosity=2)
