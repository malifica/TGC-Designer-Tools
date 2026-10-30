"""Collect the existing Beta 8.1 executable and its source for publication.
No rebuilding, source changes, Git commands, authentication, or network requests.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

EXE = 'dist/tgc_gui_2k25_beta8_1.exe'
REQUIRED = (
    EXE, 'tgc_gui.py', 'tgc_image_terrain.py', 'tgc_beta8_entry.py',
    'BUILD_TGC_2K25_BETA8_1.py', 'BUILD_TGC_2K25_BETA8_1.bat',
    'BUILD_TGC_2K25_BETA7.py', 'BUILD_TGC_2K25_BETA8.py', 'tgc_tree_size_test1_entry.py',
    'tgc_local_alignment.py', 'tgc_local_alignment_detector.py',
    'tgc_local_alignment_export.py', 'tgc_local_alignment_ui.py',
    'tgc_local_alignment_topology.py', 'tgc_local_feature_filters.py',
    'tgc_cfs_display.py', 'tgc_cfs_widgets.py', 'tgc_ui_style.py',
    'tgc_unity_raw_svg.py', 'tgc_unity_svg_paths.py', 'tgc_unity_import_ui.py',
    'tree_profile_manager.py', 'tree_profiles/desert_southwest.json',
    'VERIFY_BETA8_THEME_PLANTING.py', 'requirements.txt',
)
PATTERNS = (
    'tgc_*.py', 'lidar_*.py', 'osm_*.py', 'tree_*.py', 'uk_*.py',
    'exus_*.py', 'usgs_*.py', 'VERIFY_BETA*.py', 'VERIFY_TGC_*.py',
    'BUILD_TGC_2K25_BETA7.*', 'BUILD_TGC_2K25_BETA8.*', 'BUILD_TGC_2K25_BETA8_1.*',
    'auto_red_mask.py', 'cfs_georef.py', 'dem_map_api.py', 'GeoPointCloud.py',
    'OSMTGC.py', 'infill_image.py', 'offset_ui_tool.py', 'scotland_s3.py',
)
SUPPORT = (
    'requirements.txt', 'lidar_fast_native.c', 'tgc_lidar_fast_native.dll',
    'laszip/laszip-cli.exe', 'extras/splines.json', 'LICENSE', 'NOTICE',
    'THIRD_PARTY_NOTICES.txt', 'BETA8_1_SOURCE_PREPARATION.json', 'RELEASE_NOTES_v0.5.0-2k25-beta8.1.md', 'COLLECT_BETA8_1_FOR_PUBLICATION.py',
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_file(root: Path, name: str) -> Path:
    p = root / name
    if p.is_symlink() or not p.is_file() or root not in p.resolve().parents:
        raise RuntimeError('Missing or unsafe input: ' + name)
    for parent in p.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise RuntimeError('Symlinked input directory: ' + name)
    return p


def collect(root: Path, destination: Path | None = None) -> Path:
    root = root.resolve()
    missing = [n for n in REQUIRED if not (root / n).is_file()]
    if missing:
        raise RuntimeError('Required existing Beta 8.1 build/source is missing:\n  ' + '\n  '.join(missing)
                           + '\nNothing was rebuilt or changed.')
    for name in REQUIRED:
        safe_file(root, name)
    with (root / EXE).open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise RuntimeError('The existing Beta 8.1 EXE is not a Windows executable.')
    gui = (root / 'tgc_gui.py').read_text('utf-8-sig')
    if 'TGC Designer Tools 2K25 - Beta 8.1' not in gui or 'v0.5.0-2k25-beta8.1' not in gui or 'Import Woods / Woodchip Areas (Mulch)' not in gui or 'Import Individual OSM Tree Points' not in gui:
        raise RuntimeError('The current GUI source does not contain the expected Beta 8.1 identity/option.')
    names = set(REQUIRED)
    for pattern in PATTERNS:
        for p in root.glob(pattern):
            if p.is_file() and not p.name.lower().startswith(('tgc_finisher', 'tgc_course_architect')):
                if p.suffix.lower() in ('.py', '.bat', '.spec'):
                    names.add(p.relative_to(root).as_posix())
    for directory, pattern in (
        ('tree_profiles', '*.json'), ('dist/tree_profiles', '*.json'),
        ('PyInstaller', '*.py'), ('licenses', '*'), ('laszip', '*LICENSE*'),
    ):
        if (root / directory).is_dir():
            for p in (root / directory).rglob(pattern):
                if p.is_file():
                    names.add(p.relative_to(root).as_posix())
    for name in SUPPORT:
        if (root / name).is_file():
            names.add(name)
    paths = {n: safe_file(root, n) for n in sorted(names)}
    if destination is None:
        destination = root / '_release_upload'
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = destination / ('TGC_BETA8_1_EXISTING_BUILD_AND_SOURCE_' + stamp + '.zip')
    fd, temporary = tempfile.mkstemp(prefix='.collect_beta8_1_', suffix='.zip', dir=destination)
    import os
    os.close(fd)
    temporary = Path(temporary)
    try:
        manifest = {
            'format': 'TGC Beta 8.1 existing-build publication input', 'version': 1,
            'exe': EXE, 'rebuild_performed': False, 'network_requests': False,
            'source_files_modified': False, 'files': {},
        }
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for name, path in paths.items():
                before = sha256(path)
                archive.write(path, name)
                if sha256(path) != before:
                    raise RuntimeError('Input changed while collecting: ' + name + '. Retry with the app/build closed.')
                manifest['files'][name] = {'sha256': before, 'bytes': path.stat().st_size}
            archive.writestr('UPLOAD_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Collection ZIP verification failed.')
            for name, spec in manifest['files'].items():
                h = hashlib.sha256()
                with archive.open(name) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(block)
                if h.hexdigest() != spec['sha256']:
                    raise RuntimeError('Collection content check failed: ' + name)
                if sha256(paths[name]) != spec['sha256']:
                    raise RuntimeError('Source changed while validating: ' + name)
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print('\nCollection complete. Upload this ZIP in the chat:\n' + str(output))
    print('\nNo build, source edit, publication, or network request was performed.')
    print('Existing EXE SHA256: ' + manifest['files'][EXE]['sha256'])
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(r'C:\TGC-Designer-Tools'))
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    collect(args.root, args.output_dir)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('COLLECTION FAILED: ' + str(exc), file=sys.stderr)
        sys.exit(1)
