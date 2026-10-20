"""Promote the approved Beta 6 Windows artifact unchanged; never rebuild the EXE."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

REPO = 'malifica/TGC-Designer-Tools'
BASE = '8003c468fd00106fec5cdef5524bea52b7960d57'
BUILD = '82e5791d4978f81b6d4c471a6c8811720c6b9f9f'
RUN = 39406930184
ARTIFACT = 12257707413
ARTIFACT_NAME = 'TGC_Beta6_LiDAR_Tree_Size_TEST1_Windows_x64'
ARTIFACT_SHA = 'ca9af9fb1a0805ba5d215ab65ab8c2e7da531ed3ad9de5a725f178127b60d362'
SOURCE_SHA = '39865111ced9bee6789bb0ea2f6a677c120f5a4341747cf6c6cd12eb71526880'
EXE_SHA = 'c3ec0f85206b8f0148a235e415a48e3c63bdcf94cd760c52e92414a196cf349f'
EXE_BYTES = 153525372
TAG = 'v0.5.0-2k25-beta6'
TITLE = 'TGC Designer Tools 2K25 - Beta 6 Hotfix'
EXE = 'tgc_gui_2k25_beta6.exe'
PACKAGE = 'TGC-Designer-Tools-2K25-v0.5.0-2k25-beta6-Windows-x64.zip'
STAGING = ['PROMOTE_BETA6_LIDAR_HOTFIX.py', '.github/workflows/publish-beta6-lidar-hotfix.yml']
SOURCE_FILES = {
    'tgc_image_terrain.py': '19cf8c224d0f5e62fd5e2236493a3516af14385c3f590667e36bc5f1a014457f',
    'tgc_gui.py': 'f4dd4e1aab50edddbed15772e6e04e20e165ebf5701c993cf04a1a8d3939e900',
    'tgc_tree_size_test1_entry.py': '0d4f8192c12e0b5985adb6df8e42a855f28da6ba3082da8f2cb5f0a48479be11',
    'tree_profiles/pacific_northwest.json': '9a1445f0acca854e018f1b922ba3d287bbf96847293d91eeee5054a793331aa9',
    'VERIFY_BETA6_SOURCE.py': 'e1ee9d8dc63e8817b01b836815605ac6ac35a53ae232185b87bbd0332f15ce1f',
}
DOC_FILES = ['README.md', 'CHANGELOG.md', 'BUILD_WINDOWS.md', 'BETA6_TREE_PROFILES.md',
             'BETA6_HOTFIX.md', 'RELEASE_NOTES_v0.5.0-2k25-beta6.md', 'tree_profiles/README.md',
             'BETA6_LIDAR_TREE_HOTFIX.md']
HOTFIX = '''## LiDAR tree-sizing hotfix - 2026-10-20

- Regional themes now select tree models without replacing LiDAR-derived tree scales.
- Built-in and regional tree palettes share the same source crown-radius and height calculation.
- Standard (Lidar) and Heroic retain their established LiDAR mapping; Epic is 1.20 x Heroic and Mythic is 1.80 x Heroic on X/Y/Z.
- Profile scale defaults, per-asset scale distributions and uniform-scale settings no longer override generated tree sizing.
- Tree detection, coordinates, final-grid masks, playing-surface exclusions, OSM alignment and material presets are unchanged.
- Pacific Northwest is included in both the bundled and editable profile directories.
- All previous Beta 6 spline-surface and CFS/mask hotfixes remain included.

The existing processed LiDAR heightmap can be reused; this correction does not require repeating LiDAR processing.

This restores the established source-measurement-to-transform-scale mapping, not a new metre-for-metre calibration of every tree model. Different native models can have different unscaled dimensions.

**Approved executable:** the Windows EXE is promoted byte-for-byte from the successfully tested build, without recompilation. The public filename is `tgc_gui_2k25_beta6.exe`; its window title still includes `LiDAR Tree Size TEST 1` as the original build identifier. That label is expected in this hotfix.

'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(*args, capture=False):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.check_output(args, text=True, encoding='utf-8').strip() if capture else subprocess.run(args, check=True)


def api(endpoint, payload=None):
    args = ['gh', 'api', endpoint]
    if payload is not None:
        args += ['--method', 'PATCH', '--input', '-']
        result = subprocess.run(args, input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, check=True)
        return json.loads(result.stdout)
    return json.loads(subprocess.check_output(args, text=True, encoding='utf-8'))


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Documentation/build source guard failed: ' + old[:100])
    return text.replace(old, new, 1)


def after_title(text, addition):
    title, rest = text.split('\n', 1)
    return title + '\n\n' + addition + rest.lstrip('\n')


def prepare(root, artifact_dir, output):
    root = Path(root)
    artifact_dir = Path(artifact_dir)
    output = Path(output)
    exe_data = (artifact_dir / 'tgc_gui_2k25_beta6_tree_size_TEST1.exe').read_bytes()
    if len(exe_data) != EXE_BYTES or digest(exe_data) != EXE_SHA:
        raise ValueError('Approved executable identity mismatch; will not publish')
    source_data = (artifact_dir / 'TEST1_EXACT_PATCHED_SOURCE.zip').read_bytes()
    if digest(source_data) != SOURCE_SHA:
        raise ValueError('Approved source archive identity mismatch')
    verification = (artifact_dir / 'TEST1_FROZEN_VERIFICATION.txt').read_text(encoding='utf-8-sig')
    if 'PASSED: 44 shipped profile/mode combinations' not in verification:
        raise ValueError('Approved compiled-EXE verification record missing')
    with zipfile.ZipFile(io.BytesIO(source_data)) as source:
        for name, expected in SOURCE_FILES.items():
            data = source.read(name)
            if digest(data) != expected:
                raise ValueError('Approved source hash mismatch: ' + name)
            if name.endswith('.py'):
                compile(data.decode('utf-8-sig'), name, 'exec')
            else:
                json.loads(data)
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    path = root/'RELEASE_NOTES_v0.5.0-2k25-beta6.md'
    text = after_title(path.read_text(encoding='utf-8'), HOTFIX)
    text = replace_once(text, '- The same Epic/Mythic multipliers apply to regional profile-calibrated scales.',
                        '- Regional and built-in palettes use the same LiDAR-derived sizing; profile size distributions are ignored.')
    path.write_text(text, encoding='utf-8')
    path = root/'README.md'
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, '## Beta 6\n', '## Beta 6\n\n' + HOTFIX)
    path.write_text(text, encoding='utf-8')
    path = root/'CHANGELOG.md'
    text = path.read_text(encoding='utf-8')
    index = text.index('## [0.5.0-2k25-beta6]')
    text = text[:index] + HOTFIX.replace('## LiDAR tree-sizing hotfix - 2026-10-20', '## [0.5.0-2k25-beta6] - 2026-10-20 - LiDAR tree-sizing hotfix') + text[index:]
    path.write_text(text, encoding='utf-8')
    path = root/'BETA6_HOTFIX.md'
    path.write_text(after_title(path.read_text(encoding='utf-8'), HOTFIX), encoding='utf-8')
    (root/'BETA6_LIDAR_TREE_HOTFIX.md').write_text('# Beta 6 LiDAR tree-sizing hotfix\n\n' + HOTFIX +
        '## Validation and provenance\n\n'
        'All eight retained Beta 6 source/workflow verifiers and the production tree-generation checks passed on Windows. '
        'The compiled EXE passed 44 regional-profile/mode combinations, extreme profile-size tests, source-value spacing, '
        'preset ratios and single-tree defaults. The maintainer subsequently confirmed the in-game test worked.\n\n'
        'The source files and shipped EXE come from the same approved Windows artifact. '
        'The former test entry-point name is retained to match the approved binary; normal launch starts the main GUI. '
        'Its `--verify-lidar-trees` switch runs the built-in regression check without opening the GUI.\n\n'
        f'Approved build commit: `{BUILD}`.\n\nApproved EXE SHA-256: `{EXE_SHA}`.\n', encoding='utf-8')
    path = root/'BETA6_TREE_PROFILES.md'
    text = replace_once(path.read_text(encoding='utf-8'),
        '2. **Heroic** — the established larger-scale regional/tree calibration.',
        '2. **Heroic** — the established larger LiDAR-derived size mapping.')
    text = replace_once(text,
        'For built-in Designer themes, Epic and Mythic multiply the full Heroic X/Y/Z output ranges. For regional profiles, they multiply the profile-calibrated X/Y/Z result. Heroic remains the default.',
        'Built-in Designer themes and regional profiles share the same LiDAR crown-radius/height calculation. Epic and Mythic multiply that shared Heroic X/Y/Z result. Regional profile scale data does not override it. Heroic remains the default.\n\nThis is the established source-population mapping to native transform scales, not physical per-prefab metre calibration. Theme selection changes the model palette; identical accepted LiDAR measurements and mode produce identical transform scales.')
    path.write_text(text, encoding='utf-8')
    path = root/'tree_profiles/README.md'
    text = replace_once(path.read_text(encoding='utf-8'), '- calibrated X/Y/Z or uniform scale ranges',
                        '- retained historical X/Y/Z or uniform scale statistics (not used for generated tree sizing)')
    text = replace_once(text,
        'Scale distributions are stored per asset or as profile defaults. Standard, Heroic, Epic, and Mythic modes apply the configured profile scaling rules without changing the selected regional asset palette.',
        'Historical scale statistics may remain in the JSON for compatibility, but are not used to size generated trees. All palettes share the established LiDAR crown-radius/height mapping. Standard and Heroic retain their existing ranges; Epic is 1.20 x Heroic and Mythic is 1.80 x Heroic. OSM-only candidates use the common built-in fallback instead of profile-specific scale distributions.')
    text = replace_once(text, '- Pacific Northwest when included by the active release package', '- Pacific Northwest')
    path.write_text(text, encoding='utf-8')
    path = root/'BUILD_WINDOWS.md'
    path.write_text(after_title(path.read_text(encoding='utf-8'),
        '## Approved Beta 6 LiDAR hotfix\n\n'
        'The published hotfix promotes the approved Windows EXE unchanged; no release-time rebuild is performed. '
        'See `BETA6_LIDAR_TREE_HOTFIX.md` and `BETA6_LIDAR_HOTFIX_MANIFEST.json`. '
        'Future source builds use `tgc_tree_size_test1_entry.py`, the same launcher as the approved binary, '
        'and verify tree sizing before and after compilation. The retained TEST 1 title suffix identifies that approved build.\n\n'), encoding='utf-8')
    path = root/'BUILD_TGC_2K25_BETA6.bat'
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, 'echo === Rasterio / GDAL ===',
        'echo === LiDAR tree-size hotfix verification ===\npython tgc_tree_size_test1_entry.py --verify-lidar-trees\nif errorlevel 1 goto :fail\n\necho === Rasterio / GDAL ===')
    if text.count('   tgc_gui.py\n') != 2:
        raise ValueError('Unexpected PyInstaller build entry points')
    text = text.replace('   tgc_gui.py\n', '   tgc_tree_size_test1_entry.py\n')
    text = replace_once(text, 'if not exist "dist\\%EXENAME%.exe" goto :fail',
        'if not exist "dist\\%EXENAME%.exe" goto :fail\n"dist\\%EXENAME%.exe" --verify-lidar-trees\nif errorlevel 1 goto :fail')
    text = replace_once(text, 'copy /y "BETA6_TREE_PROFILES.md" "%RELEASEDIR%\\" >nul',
        'copy /y "BETA6_TREE_PROFILES.md" "%RELEASEDIR%\\" >nul\ncopy /y "BETA6_LIDAR_TREE_HOTFIX.md" "%RELEASEDIR%\\" >nul')
    path.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
    manifest = {
        'release_tag': TAG, 'published_filename': EXE, 'binary_rebuilt': False,
        'approved_build_commit': BUILD, 'approved_workflow_run': RUN, 'approved_artifact_id': ARTIFACT,
        'approved_artifact_sha256': ARTIFACT_SHA, 'approved_source_archive_sha256': SOURCE_SHA,
        'exe_sha256': EXE_SHA, 'exe_bytes': EXE_BYTES, 'source_base_main': BASE,
        'approved_source_files_sha256': SOURCE_FILES,
        'window_title_note': 'LiDAR Tree Size TEST 1 identifier intentionally retained in the unchanged approved EXE',
        'course_finisher_changed': False, 'crazy_bunkers_changed': False,
    }
    (root/'BETA6_LIDAR_HOTFIX_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    output.mkdir(parents=True, exist_ok=True)
    (output/EXE).write_bytes(exe_data)
    with zipfile.ZipFile(output/PACKAGE, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as package:
        package.writestr(EXE, exe_data)
        for name in ['LICENSE'] + DOC_FILES + ['BETA6_LIDAR_HOTFIX_MANIFEST.json']:
            if '/' not in name:
                package.write(root/name, name)
        package.write(root/'extras/splines.json', 'splines.json')
        for file in sorted((root/'tree_profiles').rglob('*')):
            if file.is_file() and file.suffix in ('.json', '.md'):
                package.write(file, file.relative_to(root))
    with zipfile.ZipFile(output/PACKAGE) as package:
        if package.testzip() is not None or digest(package.read(EXE)) != EXE_SHA:
            raise ValueError('Release package validation failed')
        if package.read('tree_profiles/pacific_northwest.json') != (root/'tree_profiles/pacific_northwest.json').read_bytes():
            raise ValueError('Pacific Northwest package mismatch')
    expected = {}
    for name in [EXE, PACKAGE]:
        sha = digest((output/name).read_bytes())
        checksum_name = name+'.sha256.txt'
        (output/checksum_name).write_bytes((sha+'  '+name+'\n').encode('ascii'))
        expected[name] = sha
        expected[checksum_name] = digest((output/checksum_name).read_bytes())
    (output/'expected_assets.json').write_text(json.dumps(expected, indent=2), encoding='utf-8')
    print('Prepared exact approved EXE and validated release package:', json.dumps(expected), flush=True)
    return expected


def publish():
    if os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise ValueError('Unexpected publication repository')
    stage_sha = os.environ['GITHUB_SHA']
    changed = set(command('git', 'diff', '--name-only', BASE, 'HEAD', capture=True).splitlines())
    if changed != set(STAGING):
        raise ValueError('Main changed beyond the two publication staging files: '+repr(changed))
    prefix = 'repos/'+REPO
    release = api(prefix+'/releases/tags/'+TAG)
    old_tag = api(prefix+'/git/ref/tags/'+TAG)['object']['sha']
    if release['id'] != 410916440 or release['target_commitish'] != BASE or old_tag != BASE or release['immutable']:
        raise ValueError('Existing release identity changed; refusing to overwrite')
    artifact = api(prefix+'/actions/artifacts/'+str(ARTIFACT))
    if artifact['expired'] or artifact['digest'] != 'sha256:'+ARTIFACT_SHA or artifact['workflow_run']['head_sha'] != BUILD:
        raise ValueError('Approved CI artifact identity changed or expired')
    work = Path('_promotion_work')
    work.mkdir()
    approved = work/'approved'
    command('gh', 'run', 'download', str(RUN), '--repo', REPO, '--name', ARTIFACT_NAME, '--dir', str(approved))
    expected = prepare(Path.cwd(), approved, work/'release')
    exe_path = (work/'release'/EXE).resolve()
    self_test = subprocess.run([str(exe_path), '--verify-lidar-trees'], text=True, encoding='utf-8', capture_output=True, check=True)
    print(self_test.stdout, flush=True)
    if 'PASSED: 44 shipped profile/mode combinations' not in self_test.stdout:
        raise ValueError('Approved EXE self-test output mismatch')
    backup = work/'previous_release'
    command('gh', 'release', 'download', TAG, '--repo', REPO, '--dir', str(backup))
    for asset in release['assets']:
        if asset['name'] in expected and digest((backup/asset['name']).read_bytes()) != asset['digest'].split(':',1)[1]:
            raise ValueError('Previous release backup hash mismatch')
    if api(prefix+'/git/ref/heads/main')['object']['sha'] != stage_sha:
        raise ValueError('Main advanced during preparation; release unchanged')
    command('git', 'config', 'user.name', 'github-actions[bot]')
    command('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    command('git', 'rm', *STAGING)
    command('git', 'add', *SOURCE_FILES, *DOC_FILES, 'BUILD_TGC_2K25_BETA6.bat', 'BETA6_LIDAR_HOTFIX_MANIFEST.json')
    command('git', 'diff', '--cached', '--stat')
    command('git', 'commit', '-m', 'Beta 6 Hotfix: preserve LiDAR-derived tree sizes across regional themes')
    source_commit = command('git', 'rev-parse', 'HEAD', capture=True)
    command('git', 'push', 'origin', 'HEAD:main')
    files = [str(work/'release'/name) for name in expected]
    try:
        command('gh', 'release', 'upload', TAG, *files, '--repo', REPO, '--clobber')
        published = api(prefix+'/releases/tags/'+TAG)
        assets = {a['name']: a for a in published['assets']}
        for name, sha in expected.items():
            if assets[name]['digest'] != 'sha256:'+sha:
                raise ValueError('Published server hash mismatch: '+name)
        api(prefix+'/git/refs/tags/'+TAG, {'sha': source_commit, 'force': True})
        api(prefix+'/releases/'+str(release['id']), {
            'name': TITLE, 'body': Path('RELEASE_NOTES_v0.5.0-2k25-beta6.md').read_text(encoding='utf-8'),
            'target_commitish': source_commit, 'draft': False, 'prerelease': True,
        })
        downloaded = work/'verified_downloads'
        command('gh', 'release', 'download', TAG, '--repo', REPO, '--dir', str(downloaded))
        for name, sha in expected.items():
            if digest((downloaded/name).read_bytes()) != sha:
                raise ValueError('Re-downloaded public hash mismatch: '+name)
        with zipfile.ZipFile(downloaded/PACKAGE) as z:
            if z.testzip() is not None or digest(z.read(EXE)) != EXE_SHA:
                raise ValueError('Published ZIP does not contain the exact approved EXE')
        result = api(prefix+'/releases/tags/'+TAG)
        if result['target_commitish'] != source_commit or not result['prerelease'] or result['draft']:
            raise ValueError('Published release metadata mismatch')
        if api(prefix+'/git/ref/tags/'+TAG)['object']['sha'] != source_commit:
            raise ValueError('Published tag mismatch')
    except BaseException:
        print('Publication failed; restoring previous release files, tag and metadata.', flush=True)
        command('gh', 'release', 'upload', TAG, *[str(backup/name) for name in expected], '--repo', REPO, '--clobber')
        api(prefix+'/git/refs/tags/'+TAG, {'sha': old_tag, 'force': True})
        api(prefix+'/releases/'+str(release['id']), {key:release[key] for key in ['name','body','target_commitish','draft','prerelease']})
        raise
    summary = {'status':'PUBLISHED_AND_REDOWNLOADED_VERIFIED', 'release':result['html_url'],
               'source_commit':source_commit, 'exact_approved_exe_sha256':EXE_SHA, 'published_asset_sha256':expected}
    (work/'PUBLICATION_VERIFIED.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('# Beta 6 LiDAR hotfix published\n\nNo rebuild: exact approved EXE promoted.\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n')
    print(json.dumps(summary,indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', type=Path)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, default=Path('_promotion_work/release'))
    args = parser.parse_args()
    if args.prepare_only:
        prepare(args.root, args.prepare_only, args.output)
    else:
        publish()
