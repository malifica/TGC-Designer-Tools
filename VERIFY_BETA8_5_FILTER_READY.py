"""Portable Filter Ready runtime checks for source and frozen builds.

Fixtures are defined here. verify() does not parse command-line arguments and
can be called by the frozen executable's --verify-filter-ready entry point.
"""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tgc_theme_filter_ready as ready
import tree_profile_manager as profiles


def _point(x=0.0, z=0.0, y=0.0):
    return {'x': x, 'y': y, 'z': z}


def _item(name, category='tree'):
    directory = {'tree': 'Trees', 'shrub': 'Bushes', 'grass': 'Grass',
                 'plant': 'Plants', 'rock': 'Rocks', 'prop': 'Props'}[category]
    return {
        'key': {'path': 'Assets/FilterReadyFixture/' + directory + '/' + name},
        'category': category, 'placement': 'item',
        'sample': {
            'position': _point(y='-Infinity'),
            'rotation': _point(),
            'scale': {'x': 0.05, 'y': 0.05, 'z': 0.05},
        },
    }


def _path(name, water=False, closed=False):
    coords = [(0.0, 0.0), (0.5, 0.0)]
    if closed:
        coords.append((0.0, 0.5))
    nodes = []
    for x, z in coords:
        node = {key: _point(x, z) for key in ('pointOne', 'pointTwo', 'waypoint')}
        if not closed:
            node['width'] = 0.25
        nodes.append(node)
    sample = {
        'path': {'waypoints': nodes, 'width': 0.25, 'hasCurves': False,
                 'state': 2 if closed else 0, 'absoluteY': closed},
        'height': 0.0, 'spacingRule': 0 if water else 2,
        'flexibilityRule': 0 if water else 1,
        'heightRule': 1 if closed else 0, 'spacing': 0.25,
        'disableHeightOffset': True, 'disableSurfaceTexture': True,
        'isWater': water,
    }
    if water:
        sample.update(heightOffset=0.0, edgeHeightOffset=0.0,
                      water={'flowDirection': 1.0, 'flowSpeed': 0.0})
    return {'key': {'path': 'Assets/FilterReadyFixture/' + name},
            'category': 'path_generator', 'placement': 'object_path2',
            'sample': sample}


def _group(asset, field='items', records=None):
    value = {'items': [], 'clusters': [], 'splines': [], 'objectPaths2': [], 'IsEmpty': False}
    value[field] = copy.deepcopy(records if records is not None else [asset['sample']])
    return {'Key': copy.deepcopy(asset['key']), 'Value': value}


def _brush(x, z, size_x=8.0, size_z=8.0, angle=0.0, value=1.0):
    return {'surfaceCategory': 0, 'position': _point(x, z, '-Infinity'),
            'rotation': _point(y=angle),
            'scale': {'x': size_x, 'y': 1.0, 'z': size_z},
            'type': 72, 'value': value, 'holeId': -1}


def _course():
    return {'name': 'Runtime fixture', 'version': 45, 'theme': 2,
            'height': [], 'terrainHeight': [], 'surfaceSplines2': [],
            'surfaceBrushes2': [], 'water': [], 'holes3': [],
            'placedObjects4': [], 'surfaces2': [{'name': 'default'}]}


def _other_corners():
    return [_brush(-976, 976), _brush(976, -976), _brush(-976, -976)]


class FilterReadyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tgc-filter-ready-verify-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = {'id': 'fixture', 'display_name': 'Fixture theme'}
        self.assets = [_item('TreeA'), _item('TreeB')]
        self.write_catalog(self.root, self.assets)
        self.profile_patch = patch.object(profiles, 'get_profile', side_effect=
                                          lambda choice: self.profile if choice == 'Fixture theme' else None)
        self.directory_patch = patch.object(profiles, '_profile_directories', return_value=[self.root])
        self.profile_patch.start()
        self.directory_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.addCleanup(self.directory_patch.stop)

    def write_catalog(self, root, assets, **changes):
        directory = root / 'filter_ready'
        directory.mkdir(parents=True, exist_ok=True)
        data = {'schema_version': 1, 'profile_id': 'fixture', 'complete': True,
                'assets': copy.deepcopy(assets)}
        data.update(changes)
        (directory / 'fixture.json').write_text(json.dumps(data), encoding='utf-8')

    def apply(self, course, enabled=True, **kwargs):
        return ready.apply_filter_ready(course, 'Fixture theme', enabled, printf=None, **kwargs)

    def test_01_off_is_exact_noop_and_ignores_unavailable_catalog(self):
        course = _course()
        with patch.object(ready, '_load_catalog', side_effect=AssertionError('must not load')):
            self.assertIs(ready.apply_filter_ready(course, 'missing', False, 19), course)

    def test_02_status_and_version_gating(self):
        status = ready.catalog_status('Fixture theme')
        self.assertTrue(status['available'])
        self.assertEqual(status['asset_count'], 2)
        self.assertFalse(ready.catalog_status('unknown')['available'])
        for version in (19, 23):
            self.assertFalse(ready.catalog_status('Fixture theme', version)['available'])
            with self.assertRaisesRegex(ready.FilterReadyError, '2K25'):
                self.apply(_course(), course_version=version)

    def test_03_catalog_validation_and_override_order(self):
        override = self.root / 'override'
        self.write_catalog(override, self.assets + [_item('Override')])
        with patch.object(profiles, '_profile_directories', return_value=[self.root, override]):
            self.assertEqual(ready.catalog_status('Fixture theme')['asset_count'], 3)
            self.write_catalog(override, self.assets, complete=False)
            self.assertFalse(ready.catalog_status('Fixture theme')['available'])
        self.write_catalog(self.root, self.assets + [self.assets[0]])
        self.assertIn('duplicate', ready.catalog_status('Fixture theme')['message'])
        bad = _item('Bad')
        bad['sample']['scale'] = 0
        self.write_catalog(self.root, [bad])
        self.assertFalse(ready.catalog_status('Fixture theme')['available'])
        self.write_catalog(self.root, self.assets, profile_id='other')
        self.assertFalse(ready.catalog_status('Fixture theme')['available'])

    def test_04_export_copy_changes_only_native_objects(self):
        course = _course()
        course['height'] = [_brush(0, 0, 2000, 2000)]
        course['holes3'] = [{'waypoints': [_point(-100, -50), _point(100, 50)],
                             'tees': [{'position': _point(-100, -50)}],
                             'pins': [{'position': _point(2, 3)}]}]
        original = copy.deepcopy(course)
        exported = self.apply(course)
        self.assertEqual(course, original)
        self.assertIsNot(exported, course)
        self.assertEqual({k: v for k, v in exported.items() if k != 'placedObjects4'},
                         {k: v for k, v in original.items() if k != 'placedObjects4'})
        self.assertEqual(len(exported['placedObjects4']), 2)
        for group in exported['placedObjects4']:
            self.assertEqual(set(group), {'Key', 'Value'})
            self.assertEqual(set(group['Value']), {'items', 'clusters', 'splines', 'objectPaths2', 'IsEmpty'})
            item = group['Value']['items'][0]
            self.assertEqual(item['position']['y'], '-Infinity')
            self.assertEqual(item['scale'], {'x': 0.05, 'y': 0.05, 'z': 0.05})
            self.assertLessEqual(abs(item['position']['x']), 980)
            self.assertLessEqual(abs(item['position']['z']), 980)
        exported['height'][0]['value'] = 0.7
        self.assertEqual(course, original)

    def test_05_legacy_full_catalog_seeds_only_individual_nature_assets(self):
        nature = [_item('Tree'), _item('Shrub', 'shrub'), _item('Grass', 'grass'),
                  _item('Plant', 'plant'), _item('Rock', 'rock')]
        omitted = [_item('Bench', 'prop'), _path('Fence'),
                   _path('ClosedRiver', True, True), _path('OpenRiver', True, False)]
        mislabeled = _item('TreeSign', 'prop')
        mislabeled['category'] = 'tree'
        omitted.append(mislabeled)
        item_water = _item('WaterWrapper', 'plant')
        item_water['sample']['isWater'] = True
        omitted.append(item_water)
        self.write_catalog(self.root, nature + omitted)
        exported = self.apply(_course())
        self.assertEqual([g['Key'] for g in exported['placedObjects4']], [a['key'] for a in nature])
        for group in exported['placedObjects4']:
            self.assertEqual(len(group['Value']['items']), 1)
            self.assertEqual(group['Value']['objectPaths2'], [])
        status = ready.catalog_status('Fixture theme')
        self.assertEqual(status['asset_count'], 5)
        self.assertEqual(status['source_asset_count'], len(nature + omitted))
        self.assertEqual(status['omitted_asset_count'], len(omitted))
        self.assertIn('nature', status['message'])

    def test_06_existing_active_native_assets_are_not_duplicated(self):
        assets = [_item('ExistingItem'), _item('ExistingCluster'), _item('ExistingSpline'),
                  _path('ExistingPath'), _item('EmptyGroup'), _item('ZeroCluster')]
        self.write_catalog(self.root, assets)
        course = _course()
        course['placedObjects4'] = [
            _group(assets[0]),
            _group(assets[1], 'clusters', [{'position': _point(), 'count': 3}]),
            _group(assets[2], 'splines', [{'waypoints': []}]),
            _group(assets[3], 'objectPaths2'),
            _group(assets[4], 'items', []),
            _group(assets[5], 'clusters', [{'position': _point(), 'count': 0}]),
        ]
        original = copy.deepcopy(course)
        exported = self.apply(course)
        self.assertEqual(exported['placedObjects4'][:4], original['placedObjects4'][:4])
        self.assertEqual(len(exported['placedObjects4']), 6)
        for old, updated in zip(original['placedObjects4'][4:], exported['placedObjects4'][4:]):
            self.assertEqual(updated['Key'], old['Key'])
            self.assertEqual(len(updated['Value']['items']), 1)
            self.assertEqual({k: v for k, v in updated['Value'].items() if k != 'items'},
                             {k: v for k, v in old['Value'].items() if k != 'items'})
        self.assertEqual(course, original)

    def test_07_repeat_export_and_reimport_do_not_accumulate(self):
        course = _course()
        first = self.apply(course)
        second = self.apply(course)
        self.assertEqual(first, second)
        self.assertEqual(self.apply(first), first)
        self.assertEqual(course['placedObjects4'], [])
        self.assertIs(self.apply(course, False), course)
        self.write_catalog(self.root, [_item('DifferentThemeAsset')])
        switched = self.apply(course)
        self.assertEqual(len(switched['placedObjects4']), 1)
        self.assertTrue(switched['placedObjects4'][0]['Key']['path'].endswith('DifferentThemeAsset'))
        self.assertEqual(course['placedObjects4'], [])

    def test_08_farthest_available_corner_and_playable_clearance(self):
        course = _course()
        course['holes3'] = [{'waypoints': [_point(-800, -800)], 'tees': [], 'pins': []}]
        exported = self.apply(course)
        for group in exported['placedObjects4']:
            point = group['Value']['items'][0]['position']
            self.assertGreater(point['x'], 900)
            self.assertGreater(point['z'], 900)
        course['surfaceBrushes2'] = _other_corners()
        exported = self.apply(course)
        for group in exported['placedObjects4']:
            point = group['Value']['items'][0]['position']
            self.assertGreater(point['x'], 900)
            self.assertGreater(point['z'], 900)

    def test_09_no_clear_corner_fails_without_mutation(self):
        course = _course()
        course['water'] = [_brush(0, 0, 2000, 2000, value=-3.0)]
        before = copy.deepcopy(course)
        with self.assertRaisesRegex(ready.FilterReadyError, '30 m clearance'):
            self.apply(course)
        self.assertEqual(course, before)

    def test_10_terrain_coverage_is_not_playable_coverage(self):
        course = _course()
        course['height'] = [_brush(0, 0, 2000, 2000)]
        course['terrainHeight'] = [_brush(0, 0, 8000, 8000)]
        self.assertEqual(len(self.apply(course)['placedObjects4']), 2)

    def test_11_relative_pins_block_their_world_location(self):
        self.write_catalog(self.root, [_item('Tree')])
        course = _course()
        course['surfaceBrushes2'] = _other_corners()
        course['holes3'] = [{'waypoints': [_point(850, 850)], 'tees': [], 'pins': []}]
        self.assertEqual(len(self.apply(course)['placedObjects4']), 1)
        course['holes3'][0]['pins'] = [{'position': _point(108, 108)}]
        with self.assertRaisesRegex(ready.FilterReadyError, '30 m clearance'):
            self.apply(course)

    def test_12_rotated_brushes_and_zero_elevation_water(self):
        self.write_catalog(self.root, [_item('Tree')])
        for field, value in (('surfaceBrushes2', 1), ('surfaceBrushes', 1), ('water', 0), ('water', -4)):
            with self.subTest(field=field, value=value):
                course = _course()
                course['surfaceBrushes2'] = _other_corners()
                blocker = _brush(950, 900, 200, 2, value=value)
                course.setdefault(field, []).append(blocker)
                self.assertEqual(len(self.apply(course)['placedObjects4']), 1)
                blocker['rotation']['y'] = 90.0
                with self.assertRaisesRegex(ready.FilterReadyError, '30 m clearance'):
                    self.apply(course)

    def test_13_bezier_controls_and_widths_protect_splines(self):
        course = _course()
        course['surfaceBrushes2'] = _other_corners()
        spline = _path('Geometry')['sample']['path']
        spline['surface'] = 0
        spline['opacity'] = 1
        for node in spline['waypoints']:
            for key in ('pointOne', 'pointTwo', 'waypoint'):
                node[key]['x'] += 800
                node[key]['z'] += 800
        course['surfaceSplines2'] = [spline]
        self.assertEqual(len(self.apply(course)['placedObjects4']), 2)
        spline['waypoints'][0]['pointOne'] = _point(978, 978)
        with self.assertRaisesRegex(ready.FilterReadyError, '30 m clearance'):
            self.apply(course)

    def test_14_existing_scenery_is_preserved_and_breaks_empty_plot_ties(self):
        course = _course()
        user_item = _item('UserObject')
        user_item['sample']['position'] = _point(-976, 976, '-Infinity')
        course['placedObjects4'] = [_group(user_item)]
        before = copy.deepcopy(course['placedObjects4'])
        exported = self.apply(course)
        self.assertEqual(exported['placedObjects4'][:1], before)
        for group in exported['placedObjects4'][1:]:
            point = group['Value']['items'][0]['position']
            self.assertFalse(point['x'] < 0 and point['z'] > 0)

    def test_15_inactive_exact_keys_are_reused_without_deduplicating_user_groups(self):
        tree, fence = _item('Tree'), _path('Fence')
        self.write_catalog(self.root, [tree, fence])
        course = _course()
        inactive_tree = _group(tree, 'items', [])
        inactive_tree['Value']['IsEmpty'] = True
        duplicate_tree = _group(tree, 'clusters', [{'position': _point(30, 40), 'count': 0}])
        inactive_fence = _group(fence, 'clusters', [{'position': _point(50, 60), 'count': 0}])
        inactive_fence['Value']['IsEmpty'] = True
        course['placedObjects4'] = [inactive_tree, duplicate_tree, inactive_fence]
        original = copy.deepcopy(course)
        exported = self.apply(course)
        self.assertEqual(course, original)
        self.assertEqual(len(exported['placedObjects4']), 3)
        self.assertEqual([g['Key'] for g in exported['placedObjects4']],
                         [g['Key'] for g in original['placedObjects4']])
        self.assertEqual(exported['placedObjects4'][1], original['placedObjects4'][1])
        self.assertEqual(exported['placedObjects4'][2], original['placedObjects4'][2])
        for index, field in ((0, 'items'),):
            updated = exported['placedObjects4'][index]['Value']
            previous = original['placedObjects4'][index]['Value']
            self.assertFalse(updated['IsEmpty'])
            self.assertEqual(len(updated[field]), 1)
            self.assertEqual({k: v for k, v in updated.items() if k not in (field, 'IsEmpty')},
                             {k: v for k, v in previous.items() if k not in (field, 'IsEmpty')})
        self.assertEqual(self.apply(exported), exported)

    def test_16_unknown_or_mismatched_categories_and_path_generators_fail_closed(self):
        excluded = []
        for category in ('prop', 'wildlife', 'path_generator', None, ['tree'], {'tree': True}):
            entry = _item('LabelMustNotChooseType')
            entry['category'] = category
            excluded.append(entry)
        for path in ('Assets/Props/TreeSign', 'Assets/trees/Tree', 'Assets/TreesFake/Tree',
                     'Assets/Grass/Tree', 'Assets/Unknown/Trees'):
            entry = _item('InvalidDirectory')
            entry['key']['path'] = path
            excluded.append(entry)
        generator = _path('TreeGenerator')
        generator['category'] = 'tree'
        generator['key']['path'] = 'Assets/Trees/TreeGenerator'
        excluded.append(generator)
        excluded.extend([None, {}, 'unknown'])
        self.write_catalog(self.root, [_item('ActualTree')] + excluded)
        self.assertEqual(ready.catalog_status('Fixture theme')['asset_count'], 1)
        self.assertEqual(len(self.apply(_course())['placedObjects4']), 1)
        self.write_catalog(self.root, excluded)
        self.assertIn('no eligible nature samples', ready.catalog_status('Fixture theme')['message'])
        with self.assertRaisesRegex(ready.FilterReadyError, 'no eligible nature samples'):
            self.apply(_course())

    def test_17_existing_non_nature_objects_and_prior_samples_are_preserved(self):
        course = _course()
        bench = _item('ExistingBench', 'prop')
        bench['sample']['position'] = _point(940, -940, '-Infinity')
        fence = _path('ExistingFence')
        river = _path('ExistingWater', True, True)
        course['placedObjects4'] = [_group(bench), _group(fence, 'objectPaths2'),
                                    _group(river, 'objectPaths2')]
        before = copy.deepcopy(course)
        exported = self.apply(course)
        self.assertEqual(exported['placedObjects4'][:3], before['placedObjects4'])
        self.assertEqual(len(exported['placedObjects4']), 5)
        self.assertEqual(course, before)

    def test_18_native_nature_directories_control_classification_not_basenames(self):
        entries = [_item('DeadFallenTree'), _item('Cactus', 'plant'),
                   _item('PV_Hole19_Walls_03_ACPrefab', 'rock'), _item('GroundCover', 'grass')]
        alternative_rock = _item('SingleRock', 'rock')
        alternative_rock['key']['path'] = alternative_rock['key']['path'].replace('/Rocks/', '/Rock/')
        entries.append(alternative_rock)
        for entry in entries:
            self.assertTrue(ready.is_nature_asset(entry))
        malformed = _item('BrokenNature')
        malformed['sample'] = None
        self.write_catalog(self.root, [malformed])
        self.assertIn('sample is missing', ready.catalog_status('Fixture theme')['message'])


def verify(printf=print, validate_installed=True):
    """Run portable tests, then validate any installed Filter Ready catalogs.

    No immutable profile hashes or donor counts are assumed: valid user profile
    overrides remain supported. Packaging separately ensures shipped catalogs
    are present; themes without recovered source catalogs remain unavailable.
    """
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FilterReadyTests)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if printf:
        printf(stream.getvalue())
    if not result.wasSuccessful():
        raise RuntimeError('Filter Ready runtime verification failed.')
    checked = []
    if validate_installed:
        for choice, profile in sorted(profiles.load_profiles(force=True).items()):
            exists = any((Path(directory) / 'filter_ready' / (profile['id'] + '.json')).is_file()
                         for directory in profiles._profile_directories())
            if not exists:
                continue
            status = ready.catalog_status(choice)
            if not status['available']:
                raise RuntimeError('Filter Ready catalog verification failed for %s: %s' %
                                   (choice, status['message']))
            original = _course()
            exported = ready.apply_filter_ready(original, choice, True, printf=None)
            if original != _course() or len(exported['placedObjects4']) != status['asset_count']:
                raise RuntimeError('Filter Ready isolated export failed for ' + choice)
            if any(len(group['Value']['items']) != 1 or group['Value']['objectPaths2']
                   for group in exported['placedObjects4']):
                raise RuntimeError('Filter Ready must plant one individual nature item per asset: ' + choice)
            checked.append('%s (%d)' % (choice, status['asset_count']))
        if not checked:
            raise RuntimeError('Filter Ready has no complete installed catalogs. Reinstall the Filter Ready theme data.')
        if printf:
            printf('Filter Ready installed catalog checks: %d. %s' % (len(checked), ', '.join(checked)))
    return True


if __name__ == '__main__':
    verify()
