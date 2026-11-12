"""Check the summer hardwood palette and its actual Filter Ready export."""
import copy
import json
from pathlib import Path
import random
import re
import unittest

import tree_profile_manager as profiles
import tgc_theme_filter_ready as ready
from VERIFY_BETA8_5_FILTER_READY import _course

LABEL = 'American Hardwoods - Summer'
PROFILE_ID = 'american_hardwoods_summer'
ROOT = Path(__file__).resolve().parent
TREE_PREFIXES = ('American_Elm_', 'Elm_American_', 'White_Oak_', 'Oak_White_',
                 'SouthernLiveOak_', 'Silver_Maple_', 'Maple_Silver_',
                 'Green_Ash_', 'Beech_American_', 'Oak_Willow_')
SEASONAL = re.compile(r'autumn|fall|(?:^|_)(?:FA|FB)(?:_|\d|$)', re.IGNORECASE)


class SummerHardwoodChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profiles.load_profiles(force=True)
        cls.profile = profiles.get_profile(LABEL)
        cls.raw = json.loads((ROOT / 'tree_profiles' / (PROFILE_ID + '.json')).read_text(encoding='utf-8'))
        cls.catalog = json.loads((ROOT / 'tree_profiles' / 'filter_ready' / (PROFILE_ID + '.json')).read_text(encoding='utf-8'))

    def test_native_palette_and_catalog_agree(self):
        self.assertIsNotNone(self.profile)
        self.assertEqual(self.profile['id'], PROFILE_ID)
        trees = {a['path'] for a in self.profile['assets']}
        self.assertEqual(len(trees), 31)
        for path in trees:
            prefab = path.rsplit('/', 1)[-1]
            self.assertTrue(prefab.startswith(TREE_PREFIXES), path)
            self.assertIsNone(SEASONAL.search(prefab), path)
        catalog_trees = {a['key']['path'] for a in self.catalog['assets'] if a['category'] == 'tree'}
        self.assertEqual(catalog_trees, trees)
        self.assertEqual(len(self.catalog['assets']), 40)
        self.assertEqual(len({a['key']['path'] for a in self.catalog['assets']}), 40)
        for asset in self.catalog['assets']:
            self.assertTrue(ready.is_nature_asset(asset), asset['key'])
            self.assertEqual(asset['placement'], 'item')
            self.assertIsNone(SEASONAL.search(asset['key']['path'].rsplit('/', 1)[-1]))
            ready._validate_asset(asset)
        base = json.loads((ROOT / 'tree_profiles' / 'hudson_valley_mixed_forest.json').read_text(encoding='utf-8'))
        base_catalog = json.loads((ROOT / 'tree_profiles' / 'filter_ready' / 'hudson_valley_mixed_forest.json').read_text(encoding='utf-8'))
        source_assets = {a['path']: a for a in base['assets']}
        source_samples = {a['key']['path']: a for a in base_catalog['assets']}
        for asset in self.raw['assets']:
            self.assertEqual(asset, source_assets[asset['path']])
        for sample in self.catalog['assets']:
            self.assertEqual(sample, source_samples[sample['key']['path']])
        self.assertEqual(self.raw['visual_material_preset'], base['visual_material_preset'])

    def test_lidar_shapes_and_osm_use_only_hardwoods(self):
        approved = {a['path'] for a in self.profile['assets']}
        for kind in ('lidar', 'osm'):
            for shape in ('normal', 'skinny', None):
                with self.subTest(source=kind, shape=shape):
                    pool = profiles._pool(self.profile, shape, kind)
                    self.assertEqual({a['path'] for a in pool}, approved)
                    rng = random.Random(85026)
                    for _ in range(128):
                        self.assertIn(profiles.choose_asset(self.profile, shape, kind, rng)['path'], approved)

    def test_filter_ready_without_lidar_and_repeat_export(self):
        status = ready.catalog_status(LABEL, course_version=25)
        self.assertTrue(status['available'], status['message'])
        self.assertEqual(status['asset_count'], 40)
        original = _course()
        saved = copy.deepcopy(original)
        exported = ready.apply_filter_ready(original, LABEL, True, course_version=25, printf=None)
        self.assertEqual(original, saved)
        self.assertEqual(len(exported['placedObjects4']), 40)
        self.assertEqual({g['Key']['path'] for g in exported['placedObjects4']},
                         {a['key']['path'] for a in self.catalog['assets']})
        for group in exported['placedObjects4']:
            value = group['Value']
            self.assertEqual(len(value['items']), 1)
            self.assertFalse(value['clusters'] or value['splines'] or value['objectPaths2'])
            point = value['items'][0]['position']
            self.assertGreater(abs(point['x']), 900)
            self.assertGreater(abs(point['z']), 900)
        self.assertEqual(ready.apply_filter_ready(exported, LABEL, True, course_version=25, printf=None), exported)
        self.assertIs(ready.apply_filter_ready(original, LABEL, False, course_version=25, printf=None), original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
