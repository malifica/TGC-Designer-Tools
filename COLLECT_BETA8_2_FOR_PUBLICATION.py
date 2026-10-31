"""Archive the tested, existing Beta 8.2 Windows build and its matching inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import zipfile

VERSION = 'v0.5.0-2k25-beta8.2'
EXE = 'dist/tgc_gui_2k25_beta8_2.exe'
RECEIPT = EXE + '.build.json'
CHECKSUM = EXE + '.sha256.txt'
SCHEMA = 'tgc-windows-build-inputs-v1'
REQUIRED = (
    'tgc_gui.py', 'tgc_image_terrain.py', 'tgc_beta8_entry.py', 'tgc_tree_size_test1_entry.py',
    'OSMTGC.py', 'auto_red_mask.py', 'osm_preview_relations.py', 'osm_mask_alignment.py',
    'tgc_local_alignment_topology.py', 'tgc_tree_filter_controls.py',
    'BUILD_TGC_2K25_BETA8.py', 'BUILD_TGC_2K25_BETA8_2.py', 'BUILD_TGC_2K25_BETA8_2.bat',
    'VERIFY_BETA8_2_PARKING.py', 'VERIFY_BETA8_OSM_WOODS_V1.py',
    'COLLECT_BETA8_2_FOR_PUBLICATION.py', 'RELEASE_NOTES_v0.5.0-2k25-beta8.2.md',
    'PyInstaller/rthook_rasterio.py', 'tree_profiles/desert_southwest.json',
    'laszip/laszip-cli.exe', 'laszip/LICENSE.txt', 'extras/splines.json',
    'requirements.txt', 'LICENSE',
)
PATTERNS = (
    'tgc_*.py', 'lidar_*.py', 'osm_*.py', 'tree_*.py', 'uk_*.py', 'exus_*.py', 'usgs_*.py',
    'VERIFY_BETA*.py', 'VERIFY_TGC_*.py', 'BUILD_TGC_2K25_BETA7.py',
    'auto_red_mask.py', 'cfs_georef.py', 'dem_map_api.py', 'GeoPointCloud.py',
    'infill_image.py', 'offset_ui_tool.py', 'scotland_s3.py',
    'tree_profiles/**/*.json', 'PyInstaller/**/*.py', 'licenses/**/*',
    'lidar_fast_native.c', 'tgc_lidar_fast_native.dll', 'NOTICE', 'THIRD_PARTY_NOTICES.txt',
)


def safe_input(root: Path, name: str) -> Path:
    path = root / name
    if not path.is_file() or root not in path.resolve().parents:
        raise RuntimeError('Missing or unsafe input: ' + name)
    for item in (path, *path.parents):
        if item == root:
            break
        attrs = getattr(item.lstat(), 'st_file_attributes', 0)
        if item.is_symlink() or attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise RuntimeError('Linked collection input: ' + name)
    return path


def measure(stream):
    length = 0
    h = hashlib.sha256()
    for data in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(data)
        length += len(data)
    return {'bytes': length, 'sha256': h.hexdigest()}


def file_record(path):
    with path.open('rb') as stream:
        return measure(stream)


def source_snapshot(root):
    """The builder and collector use exactly the same set of source/support paths."""
    root = Path(root).resolve()
    names = set(REQUIRED)
    for pattern in PATTERNS:
        for path in root.glob(pattern):
            if path.is_file() and not path.name.lower().startswith(('tgc_finisher', 'tgc_course_architect')):
                names.add(path.relative_to(root).as_posix())
    return {name: file_record(safe_input(root, name)) for name in sorted(names)}


def write_build_receipt(folder, built, checksum, source):
    """Called by the Windows builder only after all staged-EXE checks pass."""
    receipt = folder / Path(RECEIPT).name
    data = {'schema': SCHEMA, 'release': VERSION,
            'exe': {'path': EXE, 'bytes': built.stat().st_size, 'sha256': checksum},
            'source_and_support': source}
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return receipt


def check_pe(path):
    with path.open('rb') as f:
        header = f.read(64)
        if len(header) == 64 and header[:2] == b'MZ':
            f.seek(struct.unpack_from('<I', header, 60)[0])
            pe = f.read(26)
            if (len(pe) == 26 and pe[:4] == b'PE\0\0' and pe[4:6] == b'\x64\x86'
                    and pe[24:26] == b'\x0b\x02'):
                return
    raise RuntimeError('The existing Beta 8.2 executable is not a Windows x64 PE32+ file.')


def collect(root, destination=None):
    root = Path(root).resolve()
    exe = safe_input(root, EXE)
    receipt_path = safe_input(root, RECEIPT)
    checksum_path = safe_input(root, CHECKSUM)
    check_pe(exe)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    binary = file_record(exe)
    if (receipt.get('schema') != SCHEMA or receipt.get('release') != VERSION or
            receipt.get('exe') != dict(path=EXE, **binary) or
            checksum_path.read_text(encoding='ascii') != binary['sha256'] + '  ' + exe.name + '\n'):
        raise RuntimeError('The existing EXE, checksum and Beta 8.2 build receipt do not match.')
    source = source_snapshot(root)
    if source != receipt.get('source_and_support'):
        recorded = receipt.get('source_and_support') or {}
        changed = sorted(n for n in set(source) | set(recorded) if source.get(n) != recorded.get(n))
        raise RuntimeError('Files differ from the checked build: ' + ', '.join(changed))
    files = {**source, EXE: binary, RECEIPT: file_record(receipt_path), CHECKSUM: file_record(checksum_path)}
    manifest = {'format': 'TGC Beta 8.2 existing-build publication input', 'version': 1,
                'exe': EXE, 'rebuild_performed': False, 'network_requests': False,
                'source_files_modified': False, 'files': files}
    dest = (Path(destination) if destination else root/'_release_upload').resolve()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = dest / ('TGC_BETA8_2_EXISTING_BUILD_AND_SOURCE_' + stamp + '.zip')
    fd, tmp_name = tempfile.mkstemp(prefix='.collect_beta8_2_', suffix='.zip', dir=dest)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as z:
            for name in sorted(files):
                z.write(safe_input(root, name), name)
            z.writestr('UPLOAD_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
        with zipfile.ZipFile(tmp) as z:
            for name, record in files.items():
                with z.open(name) as stream:
                    matches = measure(stream) == record
                if not matches or file_record(safe_input(root, name)) != record:
                    raise RuntimeError('Input changed or archive verification failed: ' + name)
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    print('Collected the existing, unchanged Beta 8.2 executable and matching build inputs.')
    print('EXE SHA-256: ' + binary['sha256'])
    print('Upload this ZIP after testing:\n' + str(output))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    try:
        collect(args.root, args.output_dir)
    except Exception as exc:
        sys.exit('COLLECTION FAILED: ' + str(exc))
