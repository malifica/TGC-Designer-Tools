"""Recover exact bundled profile data from the hash-verified release archive."""
from pathlib import Path
import hashlib
import json
import zipfile
from PyInstaller.archive.readers import CArchiveReader

RELEASE_SHA256 = '00d175629e240cf203689e5b70684b924b8aff23ccaa9a269fbd8103154a582b'
archive_path = next(Path('_release_reference').glob('*.zip'))
assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == RELEASE_SHA256, 'Release archive digest mismatch'
destination = Path('tree_profiles/pacific_northwest.json')
assert not destination.exists(), 'Unexpected existing Pacific Northwest profile'
suffix = 'tree_profiles/pacific_northwest.json'
with zipfile.ZipFile(archive_path) as archive:
    matches = [n for n in archive.namelist() if n.replace('\\','/').endswith(suffix)]
    if matches:
        assert len(matches) == 1, matches
        data = archive.read(matches[0])
        provenance = 'external JSON in verified release ZIP'
    else:
        exe_names = [n for n in archive.namelist() if n.replace('\\','/').endswith('tgc_gui_2k25_beta6.exe')]
        assert len(exe_names) == 1, archive.namelist()
        exe = Path('_release_reference/profile_reference.exe')
        exe.write_bytes(archive.read(exe_names[0]))
        reader = CArchiveReader(str(exe))
        matches = [n for n in reader.toc if n.replace('\\','/').endswith(suffix)]
        assert len(matches) == 1, 'Pacific Northwest not found in released EXE: ' + repr([n for n in reader.toc if 'tree_profiles' in n])
        data = reader.extract(matches[0])
        provenance = 'embedded JSON in verified released EXE; EXE not executed'
profile = json.loads(data.decode('utf-8-sig'))
assert profile['id'] == 'pacific_northwest' and len(profile['assets']) == 7
assert profile['display_name'] == 'Pacific Northwest'
destination.write_bytes(data)
print('Restored released Pacific Northwest profile:', hashlib.sha256(data).hexdigest())
print('Profile provenance:', provenance)
