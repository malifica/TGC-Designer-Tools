"""Verify the two selectable tree-sizing paths without opening a course or GUI."""
from __future__ import annotations
import copy
import math
import random
from unittest.mock import patch


def verify():
    import tgc_image_terrain as terrain
    import tree_profile_manager as profiles
    trees = [(0., 0., .02, .03), (2., 0., .2, 1.), (4., 0., 1., 3.),
             (6., 0., 1., 12.), (8., 0., 5., 8.)]
    modes = [profiles.STANDARD_SCALE_MODE, profiles.HEROIC_SCALE_MODE,
             profiles.EPIC_SCALE_MODE, profiles.MYTHIC_SCALE_MODE]
    stats = {'p10': .65, 'p50': 1.4, 'p90': 2.4}
    profile = {'assets': [
        {'path': 'normal_a', 'shape': 'normal', 'weight': 6, 'uniform_scale': stats},
        {'path': 'normal_b', 'shape': 'normal', 'weight': 2, 'uniform_scale': stats},
        {'path': 'skinny_a', 'shape': 'skinny', 'weight': 3, 'uniform_scale': stats}],
        'scale_defaults': {axis: stats for axis in 'xyz'}}
    source = copy.deepcopy((trees, profile))
    def items(groups):
        return {(i['position']['x'], i['position']['z']): (g['Key']['path'], i)
                for g in groups for i in g['Value']['items']}
    count = 0
    state = random.getstate()
    try:
        with patch.object(profiles, 'get_profile', return_value=profile):
            for mode in modes:
                for kind in ('lidar', 'osm'):
                    results = {}
                    for enabled in (False, True):
                        random.seed(78413)
                        results[enabled] = items(terrain.get_trees(
                            12, True, trees, 25, tree_profile='selected',
                            tree_scale_mode=mode, tree_source=kind,
                            custom_theme_weighted_planting=enabled))
                    assert len(results[False]) == len(results[True]) == len(trees)
                    current_scales = terrain._tree_scales_from_lidar(trees, mode)
                    for idx, (x, z, radius, height) in enumerate(trees):
                        path, old_item = results[True][x, z]
                        current_path, current_item = results[False][x, z]
                        assert path == current_path
                        assert old_item['position'] == current_item['position']
                        assert old_item['rotation'] == current_item['rotation']
                        asset = next(a for a in profile['assets'] if a['path'] == path)
                        rp = .5 if kind == 'osm' else sum(t[2] < radius for t in trees) / (len(trees)-1)
                        hp = .5 if kind == 'osm' else sum(t[3] < height for t in trees) / (len(trees)-1)
                        expected = profiles.scale_for_asset(profile, asset, rp, hp, mode)
                        for axis, a, b in zip('xyz', expected, current_scales[idx]):
                            assert math.isclose(old_item['scale'][axis], a, abs_tol=1e-13)
                            assert math.isclose(current_item['scale'][axis], b, abs_tol=1e-13)
                        count += 1
        assert (trees, profile) == source
        assert terrain.get_trees(12, True, [], 25, custom_theme_weighted_planting=True) == []
        # With no selected custom profile, the checkbox must have no effect.
        with patch.object(profiles, 'get_profile', return_value=None):
            for mode in modes:
                random.seed(78413)
                a = terrain.get_trees(12, True, trees, 25, tree_scale_mode=mode)
                random.seed(78413)
                b = terrain.get_trees(12, True, trees, 25, tree_scale_mode=mode,
                                      custom_theme_weighted_planting=True)
                assert a == b
        # The existing source-grid/red-mask test still forwards the new switch.
        import numpy as np
        class MaskGrid:
            def projToCV2(self, x, z, scale): return z, x
        class CourseGrid:
            def projToTGC(self, x, z, height): return x, height, z
        mask = np.zeros((10, 10, 3), dtype=np.uint8)
        mask[1, 1] = (0, 0, 255)
        for enabled in (False, True):
            with patch.object(terrain, 'get_trees', return_value=[]) as generate:
                terrain.get_lidar_trees(12, True, [(1.,1.,1.,2.), (2.,2.,.1,.3)],
                    CourseGrid(), mask, MaskGrid(), 1., 25,
                    custom_theme_weighted_planting=enabled, printf=lambda *_: None)
                assert generate.call_args.kwargs['custom_theme_weighted_planting'] is enabled
                assert generate.call_args.args[2] == [(2.,2.,.1,.3)]
    finally:
        random.setstate(state)
    print('Custom Theme Weighted Planting: ON/OFF checks passed (%d tree/mode/source cases).' % count)


if __name__ == '__main__':
    verify()
