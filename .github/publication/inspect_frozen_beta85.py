"""Read-only PyInstaller archive checks; never executes the Windows EXE or code."""
from pathlib import Path
import hashlib
import json
import marshal
import mmap
import struct
import zlib


class FrozenArchive:
    MAGIC = b'MEI\x0c\x0b\x0a\x0b\x0e'
    COOKIE = struct.Struct('!8sIIII64s')
    ENTRY = struct.Struct('!IIIIBc')

    def __init__(self, path):
        self.path = Path(path)
        self._stream = self.path.open('rb')
        self._data = mmap.mmap(self._stream.fileno(), 0, access=mmap.ACCESS_READ)
        location = self._data.rfind(self.MAGIC)
        if location < 0 or location + self.COOKIE.size > len(self._data):
            raise RuntimeError('Missing PyInstaller cookie')
        magic, size, offset, length, self.python_version, library = self.COOKIE.unpack(
            self._data[location:location+self.COOKIE.size])
        self.python_library = library.rstrip(b'\0').decode('ascii')
        self.start = location + self.COOKIE.size - size
        if self.start < 0 or offset + length > size - self.COOKIE.size:
            raise RuntimeError('Invalid PyInstaller package bounds')
        raw = self._data[self.start+offset:self.start+offset+length]
        self.toc = {}
        cursor = 0
        while cursor < len(raw):
            if cursor + self.ENTRY.size > len(raw):
                raise RuntimeError('Truncated PyInstaller entry')
            entry_size, position, compressed, uncompressed, flag, kind = self.ENTRY.unpack_from(raw, cursor)
            if entry_size < self.ENTRY.size + 1 or cursor + entry_size > len(raw):
                raise RuntimeError('Invalid PyInstaller entry size')
            name = raw[cursor+self.ENTRY.size:cursor+entry_size].rstrip(b'\0').decode('utf-8')
            if name in self.toc or flag not in (0, 1) or position + compressed > offset:
                raise RuntimeError('Invalid or duplicate PyInstaller archive member')
            self.toc[name] = (position, compressed, uncompressed, flag, kind.decode('ascii'))
            cursor += entry_size
        if cursor != len(raw):
            raise RuntimeError('Invalid PyInstaller table boundary')

    def extract(self, name):
        offset, compressed, uncompressed, flag, kind = self.toc[name]
        raw = bytes(self._data[self.start+offset:self.start+offset+compressed])
        raw = zlib.decompress(raw) if flag else raw
        if len(raw) != uncompressed:
            raise RuntimeError('PyInstaller member size mismatch: ' + name)
        return raw

    def close(self):
        self._data.close()
        self._stream.close()


def inspect(exe, receipt, expected_profiles=None):
    """Verify exact embedded theme bytes against the original Windows receipt."""
    original = receipt['source_and_support']
    archive = FrozenArchive(exe)
    try:
        members = {}
        for name in archive.toc:
            normalized = name.replace('\\', '/')
            if normalized in members:
                raise RuntimeError('Duplicate normalized embedded resource')
            members[normalized] = name
        expected = {name: record for name, record in original.items()
                    if name.startswith('tree_profiles/') and name.endswith('.json')}
        actual = {name for name in members
                  if name.startswith('tree_profiles/') and name.endswith('.json')}
        if actual != set(expected):
            raise RuntimeError('Embedded theme JSON membership differs from the checked source')
        checked = {}
        active = {}
        catalogs = {}
        for name, record in sorted(expected.items()):
            raw = archive.extract(members[name])
            measured = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            if measured != record:
                raise RuntimeError('Embedded theme resource differs from the checked source: ' + name)
            checked[name] = measured
            value = json.loads(raw.decode('utf-8-sig'))
            if name.count('/') == 1 and not Path(name).name.startswith('_') and value.get('enabled', True):
                active[Path(name).stem] = {'display_name': value.get('display_name'), 'id': value.get('id')}
            elif name.startswith('tree_profiles/filter_ready/'):
                if value.get('complete') is not True or value.get('schema_version') != 1:
                    raise RuntimeError('Incomplete embedded nature catalog: ' + name)
                catalogs[Path(name).stem] = {'profile_id': value.get('profile_id'), 'asset_count': len(value.get('assets', []))}
        if len(active) != 25 or set(active) != set(catalogs):
            raise RuntimeError('The EXE does not contain all 25 active profiles and catalogs')
        if expected_profiles is not None and set(active) != set(expected_profiles):
            raise RuntimeError('Unexpected active regional profile IDs')
        if any(key != value['id'] for key, value in active.items()):
            raise RuntimeError('Profile path and identity differ')
        if any(key != value['profile_id'] for key, value in catalogs.items()):
            raise RuntimeError('Catalog path and identity differ')
        pyz_names = [name for name in archive.toc if name.lower().endswith('.pyz')]
        if len(pyz_names) != 1:
            raise RuntimeError('Expected one embedded Python module archive')
        pyz = archive.extract(pyz_names[0])
        if pyz[:4] != b'PYZ\0':
            raise RuntimeError('Invalid embedded Python archive header')
        toc_offset = struct.unpack('!i', pyz[8:12])[0]
        if not 12 <= toc_offset < len(pyz):
            raise RuntimeError('Invalid embedded Python archive table offset')
        # The PYZ table contains only names and integer offset/length tuples.
        # Compiled Python code objects are deliberately not unmarshalled.
        modules = dict(marshal.loads(pyz[toc_offset:]))
        for name, record in modules.items():
            if not isinstance(name, str) or not isinstance(record, tuple) or len(record) != 3:
                raise RuntimeError('Invalid Python module archive record')
            if any(type(value) is not int for value in record):
                raise RuntimeError('Invalid Python module archive offsets')
        required = {
            'tgc_gui', 'tgc_image_terrain', 'OSMTGC', 'osm_mask_alignment',
            'tgc_hillshade2', 'osm_alignment_viewer', 'tgc_local_alignment_ui',
            'tgc_theme_filter_ready', 'tree_profile_manager',
            'tgc_source_scale', 'tgc_source_scale_ui', 'tgc_unity_import_ui',
            'tgc_terrain_sampling', 'tgc_tools', 'osm_course_filter',
            'lidar_map_api', 'dem_map_api', 'tgc_local_alignment',
            'tgc_local_alignment_export', 'tgc_transitional_background',
            'VERIFY_BETA8_5_FILTER_READY', 'VERIFY_BETA8_5_HILLSHADE',
            'VERIFY_BETA8_5_COURSE_FILTER', 'VERIFY_BETA8_5_COURSE_FILTER_PIPELINE',
            'VERIFY_BETA8_5_TERRAIN_SAMPLING', 'VERIFY_BETA8_5_TERRAIN_SPACING_PIPELINE',
            'VERIFY_BETA8_5_SOURCE_SCALE', 'VERIFY_BETA8_5_DEM_SOURCE_SCALE',
            'VERIFY_BETA8_5_LIDAR_SCALE_PREFLIGHT', 'VERIFY_BETA8_5_SCALE_CONFIRMATION_PIPELINE',
            'VERIFY_BETA8_5_SCALE_DIALOG',
        }
        if not required.issubset(modules):
            raise RuntimeError('Missing required frozen Beta 8.5 modules')
        markers = {
            'tgc_gui': ['TGC Designer Tools 2K25 - Beta 8.5', 'v0.5.0-2k25-beta8.5',
                        'Match Course Name', 'Terrain Stamp Spacing (m)', 'Heightmap Scale', 'Filter Ready'],
            'osm_alignment_viewer': ['Hillshade 1', 'Hillshade 2'],
            'tgc_local_alignment_ui': ['Hillshade 1'],
            'tgc_hillshade2': ['TGC_HILLSHADE2_PATCH_V1'],
            'tgc_source_scale_ui': ['TGC_BETA8_5_AUTO_SOURCE_SCALE_UI_V1'],
        }
        checked_markers = {}
        for name, literals in markers.items():
            kind, offset, length = modules[name]
            if not 12 <= offset < toc_offset or offset + length > toc_offset:
                raise RuntimeError('Compiled module exceeds its archive')
            raw = zlib.decompress(pyz[offset:offset+length])
            if any(literal.encode('utf-8') not in raw for literal in literals):
                raise RuntimeError('Frozen module lacks the expected release or feature markers: ' + name)
            checked_markers[name] = literals
        return {'verified': True, 'method': 'Read-only CArchive resource hashes and PYZ module/marker inspection',
                'python_version': archive.python_version, 'python_library': archive.python_library,
                'archive_member_count': len(archive.toc), 'python_module_count': len(modules),
                'factory_profile_count': 25, 'factory_catalog_count': 25,
                'factory_json_files': 50, 'all_source_json_files': len(checked),
                'active_profiles': active, 'catalogs': catalogs, 'resource_hashes': checked,
                'required_feature_modules': sorted(required), 'compiled_literal_markers': checked_markers,
                'compiled_code_executed': False, 'windows_executable_run': False}
    finally:
        archive.close()


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    receipt = json.loads((root/'dist/tgc_gui_2k25_beta8_5.exe.build.json').read_text())
    result = inspect(root/'dist/tgc_gui_2k25_beta8_5.exe', receipt)
    (root/'frozen_archive_validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('verified', 'python_version', 'factory_profile_count',
        'factory_catalog_count', 'all_source_json_files', 'archive_member_count', 'python_module_count')}))
