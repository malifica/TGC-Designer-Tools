"""Exercise Filter Ready through the real compressed-course export boundary."""
import base64
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import osm_water_mulch_lock
import EXTRACT_FILTER_READY_CATALOG as extractor
import tgc_theme_filter_ready as filter_ready
import tgc_tools


def point(x=0.0, z=0.0):
    return {'x': x, 'y': 0.0, 'z': z}


def item():
    return {'position': {'x': 0.0, 'y': '-Infinity', 'z': 0.0},
            'rotation': point(), 'scale': {'x': .05, 'y': .05, 'z': .05}}


def asset(name, category='tree'):
    directory = {'tree': 'Trees', 'shrub': 'Bushes', 'grass': 'Grass',
                 'plant': 'Plants', 'rock': 'Rocks', 'prop': 'Props'}[category]
    return {'key': {'path': 'Assets/FilterReadyTest/' + directory + '/' + name}, 'category': category,
            'placement': 'item', 'sample': item()}


def native_path_asset():
    nodes = []
    for x in (0.0, .5):
        nodes.append({key: point(x) for key in ('pointOne', 'pointTwo', 'waypoint')})
    return {'key': {'path': 'Assets/FilterReadyTest/Fence'}, 'category': 'props',
            'placement': 'object_path2',
            'sample': {'path': {'waypoints': nodes, 'width': .25, 'state': 0,
                                'hasCurves': False, 'absoluteY': False},
                       'height': 0.0, 'spacingRule': 2, 'flexibilityRule': 1,
                       'heightRule': 0, 'spacing': .25, 'disableHeightOffset': True,
                       'disableSurfaceTexture': True, 'isWater': False}}


def rounded(value):
    return json.loads(json.dumps(value), parse_float=lambda x: round(float(x), 3))


def decode_course(path):
    # Inspect the actual nested game payload, rather than only an in-memory copy.
    outer = json.loads(gzip.decompress(Path(path).read_bytes()).decode('utf-16-le'))
    return {key: json.loads(gzip.decompress(base64.b64decode(value)).decode('utf-16-le'))
            for key, value in outer['binaryData'].items()}


class ExportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tgc_filter_ready_export_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile_root = self.root / 'tree_profiles'
        catalogs = self.profile_root / 'filter_ready'
        catalogs.mkdir(parents=True)
        for profile_id, assets in (
                ('fixture_a', [asset('ExistingClusterTree'), asset('Rock', 'rock'),
                               asset('Bench', 'prop'), native_path_asset()]),
                ('fixture_b', [asset('Grass', 'grass')])):
            (catalogs / (profile_id + '.json')).write_text(json.dumps({
                'schema_version': 1, 'profile_id': profile_id, 'complete': True,
                'assets': assets}), encoding='utf-8')
        profile_patch = mock.patch.object(filter_ready.tree_profile_manager, 'get_profile',
            side_effect=lambda choice: {'id': choice, 'display_name': choice})
        directories_patch = mock.patch.object(filter_ready.tree_profile_manager, '_profile_directories',
            return_value=[self.profile_root])
        profile_patch.start()
        directories_patch.start()
        self.addCleanup(profile_patch.stop)
        self.addCleanup(directories_patch.stop)
        self.course = {
            'version': 49, 'name': 'Export fixture', 'theme': 2,
            'height': 12.3456789,
            'holes3': [{'waypoints': [point(-100, -100), point(100, 100)],
                        'tees': [{'position': point(-100, -100)}], 'pins': [point(.5, .5)]}],
            'surfaceSplines2': [], 'surfaceBrushes': [], 'water': [],
            'surfaces2': [{'name': 'Grass01'}, {'name': 'Sand01'},
                          {'name': 'OriginalMulch', 'blend': .6, 'maskWater': True}],
            'placedObjects4': [{
                'Key': {'path': 'Assets/FilterReadyTest/Trees/ExistingClusterTree'},
                'Value': {'items': [], 'clusters': [{'position': point(10, 20), 'count': 5}],
                          'splines': [], 'objectPaths2': [], 'IsEmpty': False}}],
        }
        self.metadata = {'name': 'Export fixture', 'theme': 2,
                         'surfaces2': copy.deepcopy(self.course['surfaces2'])}
        self.thumbnail = {'image': base64.b64encode(b'fixture thumbnail').decode('ascii')}
        self.description_path = self.root / 'unpacked/course_description/course_description.json'
        for relative, data in (
                ('course_description/course_description.json', self.course),
                ('metadata/course_metadata.json', self.metadata),
                ('thumbnail/thumbnail.json', self.thumbnail)):
            path = self.root / 'unpacked' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding='utf-8')

    def export(self, filename, course=None, **kwargs):
        path = self.root / filename
        tgc_tools.pack_course_file(str(self.root), output_file=str(path),
            course_json=course, course_version=25, **kwargs)
        return decode_course(path)

    def test_off_preserves_legacy_export_including_precision(self):
        before = copy.deepcopy(self.course)
        legacy = self.export('legacy.course', self.course)
        exported = filter_ready.apply_filter_ready(self.course, 'fixture_a', False, printf=None)
        self.assertIs(exported, self.course)
        disabled = self.export('disabled.course', self.course, export_course_json=exported)
        self.assertEqual(disabled, legacy)
        self.assertEqual(disabled['CourseDescription']['height'], 12.346)
        self.assertEqual(self.course, before)

    def test_seeds_reach_native_payload_but_not_working_course(self):
        before = copy.deepcopy(self.course)
        seeded = filter_ready.apply_filter_ready(self.course, 'fixture_a', True, printf=None)
        packed = self.export('seeded.course', self.course, export_course_json=seeded)
        exported = packed['CourseDescription']
        self.assertEqual(exported, rounded(seeded))
        self.assertEqual(self.course, before)
        self.assertEqual(tgc_tools.get_course_json(str(self.root)), rounded(before))
        self.assertEqual(packed['CourseMetadata'], self.metadata)
        self.assertEqual(packed['Thumbnail'], self.thumbnail)
        self.assertEqual(exported['placedObjects4'][0], before['placedObjects4'][0])
        additions = exported['placedObjects4'][1:]
        self.assertEqual(len(additions), 1)  # The planted tree is reused; bench/fence are omitted.
        self.assertEqual(set(exported), set(before))  # No helper metadata in game JSON.
        for group in additions:
            self.assertEqual(set(group), {'Key', 'Value'})
            value = group['Value']
            self.assertFalse(value['IsEmpty'])
            self.assertEqual(len(value['items']), 1)
            self.assertEqual(value['objectPaths2'], [])
            self.assertEqual(group['Key']['path'], 'Assets/FilterReadyTest/Rocks/Rock')
            samples = ([sample['position'] for sample in value['items']] +
                       [node['waypoint'] for path in value['objectPaths2']
                        for node in path['path']['waypoints']])
            for sample in samples:
                self.assertTrue(900 < abs(sample['x']) < 1000)
                self.assertTrue(900 < abs(sample['z']) < 1000)

    def test_repeat_export_and_theme_change_do_not_accumulate(self):
        first = filter_ready.apply_filter_ready(self.course, 'fixture_a', True, printf=None)
        first_payload = self.export('first.course', self.course, export_course_json=first)
        again = filter_ready.apply_filter_ready(self.course, 'fixture_a', True, printf=None)
        again_payload = self.export('again.course', self.course, export_course_json=again)
        self.assertEqual(first_payload, again_payload)
        switched = filter_ready.apply_filter_ready(self.course, 'fixture_b', True, printf=None)
        switched_payload = self.export('switched.course', self.course, export_course_json=switched)
        paths = [group['Key']['path'] for group in switched_payload['CourseDescription']['placedObjects4']]
        self.assertEqual(paths, ['Assets/FilterReadyTest/Trees/ExistingClusterTree',
                                 'Assets/FilterReadyTest/Grass/Grass'])
        off = self.export('off_after_on.course', self.course)
        self.assertEqual(off['CourseDescription'], rounded(self.course))

    def test_reimported_native_samples_are_preserved_without_duplicates(self):
        seeded = filter_ready.apply_filter_ready(self.course, 'fixture_a', True, printf=None)
        imported = self.export('imported.course', self.course, export_course_json=seeded)['CourseDescription']
        before = copy.deepcopy(imported)
        repeated = filter_ready.apply_filter_ready(imported, 'fixture_a', True, printf=None)
        self.assertEqual(repeated, before)
        self.assertEqual(imported, before)
        off = filter_ready.apply_filter_ready(imported, 'fixture_a', False, printf=None)
        self.assertIs(off, imported)

    def test_export_override_without_working_save_keeps_disk_unchanged(self):
        before = self.description_path.read_bytes()
        seeded = filter_ready.apply_filter_ready(self.course, 'fixture_a', True, printf=None)
        packed = self.export('override_only.course', export_course_json=seeded)
        self.assertEqual(packed['CourseDescription'], rounded(seeded))
        self.assertEqual(self.description_path.read_bytes(), before)

    def test_final_water_material_lock_still_applies_after_seeding(self):
        self.course[osm_water_mulch_lock.LOCK_KEY] = {'material': 'Mulch05'}
        self.course['surfaceSplines2'] = [{'surface': 10, 'width': 1.0,
            'waypoints': [{key: point() for key in ('pointOne', 'pointTwo', 'waypoint')}]}]
        before = copy.deepcopy(self.course)
        seeded = filter_ready.apply_filter_ready(self.course, 'fixture_a', True, printf=None)
        packed = self.export('water_lock.course', self.course, export_course_json=seeded)
        self.assertEqual(packed['CourseDescription']['surfaces2'][2]['name'], 'Mulch05')
        self.assertEqual(packed['CourseMetadata']['surfaces2'][2]['name'], 'Mulch05')
        self.assertEqual(packed['CourseDescription']['surfaces2'][2]['blend'], .6)
        self.assertEqual(packed['CourseDescription']['water'], [])
        self.assertEqual(packed['CourseDescription']['placedObjects4'], rounded(seeded['placedObjects4']))
        self.assertEqual(self.course, before)
        self.assertEqual(tgc_tools.get_course_json(str(self.root)), rounded(before))


class NatureCatalogExtractionTests(unittest.TestCase):
    @staticmethod
    def group(sample, field='items', records=None):
        value = {'items': [], 'clusters': [], 'splines': [], 'objectPaths2': []}
        value[field] = records if records is not None else [sample['sample']]
        return {'Key': copy.deepcopy(sample['key']), 'Value': value}

    def test_extraction_keeps_each_nature_type_once_across_sources(self):
        nature = [asset('Tree'), asset('Shrub', 'shrub'), asset('Grass', 'grass'),
                  asset('Cactus', 'plant'), asset('PV_Hole19_Walls_03_ACPrefab', 'rock')]
        groups = [self.group(entry) for entry in nature]
        groups += [self.group(asset('RockSign', 'prop')), self.group(native_path_asset(), 'objectPaths2')]
        nature_path = asset('UnreviewedTreePath')
        groups.append(self.group(nature_path, 'objectPaths2', [{'isWater': True}]))
        source = {'placedObjects4': groups}
        before = copy.deepcopy(source)
        second = {'placedObjects4': [self.group(nature[0], 'clusters', [{'count': 20}])]}
        catalog, report = extractor.build_catalog([source, second], 'fixture')
        self.assertEqual(source, before)
        self.assertEqual(catalog['asset_scope'], 'nature_only')
        self.assertTrue(catalog['complete'])
        self.assertEqual(len(catalog['assets']), 5)
        self.assertEqual({entry['key']['path'] for entry in catalog['assets']},
                         {entry['key']['path'] for entry in nature})
        self.assertEqual(catalog['counts']['placements'], {'item': 5})
        self.assertEqual(report['non_nature_groups_excluded'], 2)
        self.assertEqual(report['path_only_groups_excluded'], 1)
        for entry in catalog['assets']:
            self.assertTrue(filter_ready.is_nature_asset(entry))
            self.assertEqual(entry['sample'], extractor.ITEM_SAMPLE)

    def test_non_nature_and_inactive_only_sources_are_not_complete_catalogs(self):
        source = {'placedObjects4': [self.group(asset('Bench', 'prop')),
                  self.group(native_path_asset(), 'objectPaths2'),
                  self.group(asset('InactiveTree'), 'clusters', [{'count': 0}])]}
        with self.assertRaisesRegex(ValueError, 'no active individual nature assets'):
            extractor.build_catalog(source, 'fixture')

    def test_malformed_nature_cluster_and_conflicting_native_keys_are_rejected(self):
        tree = asset('Tree')
        with self.assertRaisesRegex(ValueError, 'finite numeric'):
            extractor.build_catalog({'placedObjects4': [self.group(tree, 'clusters', [{'count': float('nan')}])]}, 'fixture')
        first, second = self.group(tree), self.group(tree)
        second['Key']['unrecognizedKeyData'] = 1
        with self.assertRaisesRegex(ValueError, 'Different native Keys'):
            extractor.build_catalog({'placedObjects4': [first, second]}, 'fixture')


def verify():
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(ExportBoundaryTests),
                            unittest.defaultTestLoader.loadTestsFromTestCase(NatureCatalogExtractionTests)]))
    if not result.wasSuccessful():
        raise RuntimeError('Filter Ready compressed-course export verification failed.')
    return True


if __name__ == '__main__':
    verify()
