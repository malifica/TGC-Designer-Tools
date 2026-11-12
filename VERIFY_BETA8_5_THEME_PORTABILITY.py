"""Prove that a rebuilt Beta 8.5 EXE carries its own factory theme data.

This is a build-time helper, not a GUI/runtime behavior change. The existing
frozen verification flags run on a copy of the EXE in an otherwise empty folder.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


PORTABILITY_MARKER = 'TGC_BETA8_5_FACTORY_THEME_PORTABILITY_V1'
FACTORY_THEMES = {
    'alpine_conifer': 'Alpine Conifer',
    'carolina_piedmont_autumn': 'Carolina Piedmont (Autumn)',
    'desert_oasis_sands': 'Desert Oasis - Sands',
    'desert_southwest': 'Desert Southwest',
    'georgia_piedmont': 'Georgia Piedmont',
    'hudson_valley_mixed_forest': 'Hudson Valley Mixed Forest',
    'monterey_bay_coast': 'Monterey Bay Coast',
    'niagara_escarpment': 'Niagara Escarpment',
    'northern_rockies': 'Northern Rockies',
    'pacific_northwest': 'Pacific Northwest',
    'pine_woodlands': 'Pine Woodlands',
    'san_francisco_peninsula': 'San Francisco Peninsula',
    'south_carolina_lowcountry': 'South Carolina Lowcountry',
    'texas_hill_country': 'Texas Hill Country',
    'virginia_coastal_plain': 'Virginia Coastal Plain',
    'australian_sandbelt': 'Australian Sandbelt',
    'mediterranean_coast': 'Mediterranean Coast',
    'alpine_woodlands': 'Alpine Woodlands',
    'boreal_woodlands': 'Boreal Woodlands',
    'prairie_sandhills': 'Prairie Sandhills',
    'temperate_parkland': 'Temperate Parkland',
    'northern_pine_parkland': 'Northern Pine Parkland',
    'rocky_mountain_riverlands': 'Rocky Mountain Riverlands',
    'appalachian_foothills': 'Appalachian Foothills',
    'southern_pine_highlands': 'Southern Pine Highlands',
}
FILTER_READY_PREFIX = 'Filter Ready installed catalog checks: '


def _load_source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _record(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def _source_policy(root):
    """Load the current installed validators without profile-directory overrides."""
    profiles = _load_source_module('_portability_source_profiles', root / 'tree_profile_manager.py')
    previous = sys.modules.get('tree_profile_manager')
    sys.modules['tree_profile_manager'] = profiles
    try:
        nature = _load_source_module('_portability_source_nature', root / 'tgc_theme_filter_ready.py')
    finally:
        if previous is None:
            sys.modules.pop('tree_profile_manager', None)
        else:
            sys.modules['tree_profile_manager'] = previous
    return profiles, nature


def capture_source_inventory(root):
    """Freeze exact source JSON bytes before PyInstaller starts.

    Every factory profile/catalog is required. Extra custom, disabled and
    underscore JSON is retained as data, without requiring an unrelated custom
    theme to have a Filter Ready catalog.
    """
    root = Path(root).resolve()
    directory = root / 'tree_profiles'
    if not directory.is_dir():
        raise RuntimeError('The source tree_profiles directory is missing.')
    files = {}
    folded_names = set()
    for path in sorted(directory.rglob('*')):
        if path.is_file() and path.suffix.casefold() == '.json':
            relative = path.relative_to(root).as_posix()
            if relative.casefold() in folded_names:
                raise RuntimeError('Source theme JSON paths collide on Windows: ' + relative)
            folded_names.add(relative.casefold())
            files[relative] = path.read_bytes()
    profiles, nature = _source_policy(root)
    factory = {}
    for profile_id, label in FACTORY_THEMES.items():
        profile_name = 'tree_profiles/' + profile_id + '.json'
        catalog_name = 'tree_profiles/filter_ready/' + profile_id + '.json'
        if profile_name not in files or catalog_name not in files:
            raise RuntimeError('A factory theme profile/catalog is missing before build: ' + label)
        raw_profile = json.loads(files[profile_name].decode('utf-8-sig'))
        profile = profiles._validate_profile(raw_profile, profile_id + '.json')
        if (not profile or profile['id'] != profile_id or
                profile['display_name'] != label):
            raise RuntimeError('A factory profile identity is disabled or incorrect: ' + label)
        catalog = json.loads(files[catalog_name].decode('utf-8-sig'))
        if (not isinstance(catalog, dict) or catalog.get('schema_version') != 1 or
                catalog.get('profile_id') != profile_id or catalog.get('complete') is not True or
                not isinstance(catalog.get('assets'), list)):
            raise RuntimeError('A factory nature catalog is incomplete: ' + label)
        assets = [asset for asset in catalog['assets'] if nature.is_nature_asset(asset)]
        paths = [nature._validate_asset(asset) for asset in assets]
        if not paths or len(paths) != len(set(paths)):
            raise RuntimeError('A factory nature catalog has no unique eligible samples: ' + label)
        if profile_id == 'prairie_sandhills' and (
                profile.get('tree_generation') != 'none' or profile.get('assets')):
            raise RuntimeError('Prairie Sandhills must retain its explicit no-tree mode.')
        factory[profile_id] = {'display_name': label, 'nature_assets': len(paths),
                               'profile_path': profile_name, 'catalog_path': catalog_name,
                               'tree_generation': profile.get('tree_generation', 'profile')}
    return {'schema': PORTABILITY_MARKER, 'factory_profiles': factory,
            'files': {name: _record(data) for name, data in files.items()},
            '_bytes': files}


def verify_archive_bytes(root, frozen_exe, inventory):
    """Match archive bytes against the pre-build snapshot, including every factory profile and catalog."""
    root = Path(root).resolve()
    if inventory.get('schema') != PORTABILITY_MARKER:
        raise RuntimeError('Unknown source theme inventory schema.')
    if set(inventory['factory_profiles']) != set(FACTORY_THEMES):
        raise RuntimeError('The frozen source inventory does not contain all %d factory themes.' % len(FACTORY_THEMES))
    current_names = {p.relative_to(root).as_posix() for p in (root/'tree_profiles').rglob('*')
                     if p.is_file() and p.suffix.casefold() == '.json'}
    if current_names != set(inventory['_bytes']):
        raise RuntimeError('Source theme JSON membership changed during the build.')
    members = {}
    archive_theme_names = set()
    folded_theme_names = set()
    for member in frozen_exe.toc:
        normalized = str(member).replace('\\', '/')
        if normalized in members:
            raise RuntimeError('Duplicate normalized archive member: ' + normalized)
        members[normalized] = member
        folded = normalized.casefold()
        if folded.startswith('tree_profiles/') and folded.endswith('.json'):
            if folded in folded_theme_names:
                raise RuntimeError('Bundled theme JSON paths collide on Windows: ' + normalized)
            folded_theme_names.add(folded)
            archive_theme_names.add(normalized)
    if archive_theme_names != set(inventory['_bytes']):
        raise RuntimeError('Bundled theme JSON membership differs from the pre-build source snapshot.')
    checked = []
    for relative, expected in sorted(inventory['_bytes'].items()):
        if (root/relative).read_bytes() != expected:
            raise RuntimeError('Source theme JSON changed during the build: ' + relative)
        member = members.get(relative)
        if member is None or frozen_exe.extract(member) != expected:
            raise RuntimeError('Bundled theme data differs from the pre-build source: ' + relative)
        checked.append(relative)
    factory_files = {entry[key] for entry in inventory['factory_profiles'].values()
                     for key in ('profile_path','catalog_path')}
    if len(factory_files) != 2 * len(FACTORY_THEMES) or not factory_files.issubset(checked):
        raise RuntimeError('Not all %d factory profile/catalog files were verified.' % (2 * len(FACTORY_THEMES)))
    return {'factory_profile_count': len(FACTORY_THEMES), 'factory_json_files': 2 * len(FACTORY_THEMES),
            'all_source_json_files': len(checked), 'verified_paths': checked}


def verify_catalog_output(output, inventory):
    lines = [line.strip() for line in output.splitlines()
             if line.strip().startswith(FILTER_READY_PREFIX)]
    if len(lines) != 1:
        raise RuntimeError('The copied EXE did not emit one installed-catalog verification result.')
    match = re.fullmatch(re.escape(FILTER_READY_PREFIX) + r'(\d+)\. (.*)', lines[0])
    if match is None or int(match.group(1)) < len(FACTORY_THEMES):
        raise RuntimeError('The copied EXE did not verify at least %d installed factory catalogs.' % len(FACTORY_THEMES))
    summary = match.group(2)
    for entry in inventory['factory_profiles'].values():
        exact = '%s (%d)' % (entry['display_name'], entry['nature_assets'])
        pattern = r'(?:^|, )' + re.escape(exact) + r'(?=, |$)'
        if len(re.findall(pattern, summary)) != 1:
            raise RuntimeError('Copied EXE factory name/catalog count is missing or incorrect: ' + exact)
    return {'runtime_catalog_count': int(match.group(1)), 'all_factory_names_and_counts_verified': True,
            'summary': lines[0]}


def _clean_environment():
    environment = dict(os.environ)
    remove = {'PYTHONPATH','PYTHONHOME','PYTHONUSERBASE','PYTHONSTARTUP','PYTHONINSPECT','_MEIPASS2'}
    for key in list(environment):
        if key.upper() in remove or key.upper().startswith('_PYI_'):
            del environment[key]
    environment['PYTHONNOUSERSITE'] = '1'
    return environment


def verify_theme_portability(root, built, stage, inventory, *, frozen_exe=None, runner=None):
    """Run after the retained build gates and before any receipt/dist publication."""
    root, built, stage = Path(root).resolve(), Path(built).resolve(), Path(stage).resolve()
    if frozen_exe is None:
        from PyInstaller.archive.readers import CArchiveReader
        frozen_exe = CArchiveReader(str(built))
    runner = runner or subprocess.run
    archive_result = verify_archive_bytes(root, frozen_exe, inventory)
    log_directory = stage/'theme_portability'
    log_directory.mkdir(parents=True, exist_ok=True)
    original_hash = file_digest(built)
    report = {'schema': PORTABILITY_MARKER, 'status': 'checking',
              'exe_name': built.name, 'exe_sha256': original_hash,
              'archive': archive_result, 'factory_profiles': inventory['factory_profiles'],
              'source_json': inventory['files'], 'checks': []}
    environment = _clean_environment()
    # The system temporary directory is independent of the source and release
    # folder. Neither the copied EXE folder nor the cwd receives theme data.
    with tempfile.TemporaryDirectory(prefix='TGC_EXE_Only_') as directory:
        isolated = Path(directory)
        portable, unrelated = isolated/'EXE only', isolated/'Unrelated working directory'
        portable.mkdir(); unrelated.mkdir()
        copied = portable/built.name
        shutil.copy2(built, copied)
        if file_digest(copied) != original_hash or list(portable.iterdir()) != [copied]:
            raise RuntimeError('Could not create an exact, EXE-only verification copy.')
        if list(unrelated.iterdir()):
            raise RuntimeError('The verification working directory is not empty.')
        report['initial_copy_contains_only_exe'] = True
        report['unrelated_working_directory_initially_empty'] = True
        for flag in ('--verify-filter-ready','--verify-lidar-trees'):
            print('Verifying copied EXE alone: ' + flag, flush=True)
            result = runner([str(copied), flag], cwd=str(unrelated), env=environment,
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
            label = flag.lstrip('-')
            (log_directory/(label+'.stdout.txt')).write_text(result.stdout, encoding='utf-8')
            (log_directory/(label+'.stderr.txt')).write_text(result.stderr, encoding='utf-8')
            if result.returncode:
                raise RuntimeError('Copied EXE portability check failed: ' + flag + '\n' +
                                   (result.stderr or result.stdout)[-4000:])
            checked = {'flag': flag, 'exit_code': result.returncode}
            if flag == '--verify-filter-ready':
                checked.update(verify_catalog_output(result.stdout, inventory))
            elif 'LIDAR TREE SIZE TEST 1 PASSED:' not in result.stdout:
                raise RuntimeError('Copied EXE did not complete its tree-size verification.')
            report['checks'].append(checked)
        if (portable/'tree_profiles').exists() or (unrelated/'tree_profiles').exists():
            raise RuntimeError('Theme sidecar files appeared during the EXE-only verification.')
        if file_digest(copied) != original_hash or file_digest(built) != original_hash:
            raise RuntimeError('An executable changed during portability verification.')
    report['temporary_copy_removed'] = True
    report['no_external_theme_directory_supplied'] = True
    report['status'] = 'PASS'
    report_path = stage/'THEME_PORTABILITY_REPORT.json'
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print('EXE-ONLY THEME PORTABILITY PASSED: all %d factory themes and catalogs. Report: %s' % (len(FACTORY_THEMES), report_path), flush=True)
    return report
