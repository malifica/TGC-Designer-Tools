"""Restore shared source-derived tree scales; patch Beta 6 without replacing unrelated code."""
from __future__ import annotations
import argparse
import ast
import datetime
import hashlib
import json
from pathlib import Path

MARKER = 'TGC_BETA6_LIDAR_TREE_SCALE_AUTHORITY_V1'
TITLE_MARKER = 'TGC_LIDAR_TREE_SIZE_TEST_TITLE_V1'


def function_text(source, name):
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise ValueError('Expected exactly one function ' + name)
    n = nodes[0]
    return ''.join(source.splitlines(keepends=True)[n.lineno-1:n.end_lineno])


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Source guard mismatch; no changes saved: ' + old[:100])
    return source.replace(old, new, 1)


def patch_engine(source):
    if MARKER in source:
        helper = function_text(source, '_tree_scales_from_lidar')
        profile = function_text(source, '_get_profile_trees')
        builtin = function_text(source, 'get_trees')
        if 'scale_for_asset(' in profile or '_tree_scales_from_lidar(' not in profile or '_tree_scales_from_lidar(' not in builtin:
            raise ValueError('Tree authority marker present but integration is incomplete')
        return source
    profile = function_text(source, '_get_profile_trees')
    builtin = function_text(source, 'get_trees')
    start = builtin.index('    mythic = tree_scale_mode == tree_profile_manager.MYTHIC_SCALE_MODE')
    end = builtin.index('    for tree in trees:', start)
    formulas = builtin[start:end]
    for expected in ('min_radius_scale = 0.70', 'max_radius_scale = 1.65',
                     'min_height_scale = 0.85', 'max_height_scale = 1.55',
                     'min_tree_radius = min(trees, key=lambda x: x[2])[2]',
                     'MYTHIC_SCALE_MULTIPLIER', 'EPIC_SCALE_MULTIPLIER'):
        if expected not in formulas:
            raise ValueError('Unexpected existing LiDAR scaling implementation: ' + expected)
    helper = '''def _tree_scales_from_lidar(trees, tree_scale_mode=None):
    """TGC_BETA6_LIDAR_TREE_SCALE_AUTHORITY_V1.

    Preserve the established Designer-Theme LiDAR mapping for ALL palettes.
    X/Z use measured crown radius; Y uses measured height. Regional profile
    scale/uniform_scale/scale_defaults NEVER participate. These are native
    transform scales, not a claim of per-prefab physical-metre calibration.
    The accepted source population supplies the existing min/max mapping;
    a theme change alone must not change any transform scale.
    """
    if not trees:
        return []
    for index, tree in enumerate(trees):
        if len(tree) != 4:
            raise ValueError('Tree %d must contain x, z, radius and height' % index)
        if not all(math.isfinite(float(v)) for v in tree):
            raise ValueError('Tree %d contains non-finite coordinates or dimensions' % index)
        if float(tree[2]) <= 0.0 or float(tree[3]) <= 0.0:
            raise ValueError('Tree %d must have positive source radius and height' % index)

''' + formulas + '''    return [
        ((r-min_tree_radius)*radius_multiplier + min_radius_scale,
         (h-min_tree_height)*height_multiplier + min_height_scale,
         (r-min_tree_radius)*radius_multiplier + min_radius_scale)
        for _x, _z, r, h in trees
    ]
'''
    new_builtin = replace_once(builtin, formulas, '    source_scales = _tree_scales_from_lidar(trees, tree_scale_mode)\n\n')
    new_builtin = replace_once(new_builtin, '    for tree in trees:\n', '    for tree, (sx, sy, sz) in zip(trees, source_scales):\n')
    new_builtin = replace_once(new_builtin,
        "        t['scale']['y'] = (h-min_tree_height)*height_multiplier + min_height_scale\n"
        "        t['scale']['x'] = (r-min_tree_radius)*radius_multiplier + min_radius_scale\n"
        "        t['scale']['z'] = (r-min_tree_radius)*radius_multiplier + min_radius_scale\n",
        "        t['scale']['y'] = sy\n        t['scale']['x'] = sx\n        t['scale']['z'] = sz\n")
    new_profile = replace_once(profile,
        '    radii = [float(t[2]) for t in trees]\n    heights = [float(t[3]) for t in trees]\n',
        '    source_scales = _tree_scales_from_lidar(trees, tree_scale_mode)\n')
    new_profile = replace_once(new_profile, '    for tree in trees:\n',
                               '    for tree, (sx, sy, sz) in zip(trees, source_scales):\n')
    a = new_profile.index('        if tree_source == "osm":\n')
    b = new_profile.index('        item = get_object_item(', a)
    if 'tree_profile_manager.scale_for_asset(' not in new_profile[a:b]:
        raise ValueError('Profile sizing guard mismatch')
    new_profile = new_profile[:a] + '        # Selection only: source_scales are independent of the chosen asset.\n\n' + new_profile[b:]
    source = replace_once(source, profile, helper + '\n\n' + new_profile)
    source = replace_once(source, builtin, new_builtin)
    old_rank = function_text(source, '_population_percentile')
    source = replace_once(source, old_rank, '')
    compile(source, 'tgc_image_terrain.py', 'exec')
    return source


def patch_gui(source):
    if TITLE_MARKER in source:
        return source
    source = replace_once(source, 'root.title(TGC_APP_TITLE)',
        'root.title(TGC_APP_TITLE)\n# ' + TITLE_MARKER + '\n'
        'root.title(TGC_APP_TITLE + " - LiDAR Tree Size TEST 1")')
    compile(source, 'tgc_gui.py', 'exec')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    originals = {name: (root/name).read_bytes() for name in ('tgc_image_terrain.py', 'tgc_gui.py')}
    edited = {
        'tgc_image_terrain.py': patch_engine(originals['tgc_image_terrain.py'].decode('utf-8-sig')),
        'tgc_gui.py': patch_gui(originals['tgc_gui.py'].decode('utf-8-sig')),
    }
    changed = [name for name in edited if edited[name].encode('utf-8') != originals[name]]
    if not changed:
        print('LiDAR Tree Size TEST 1 already applied; no source changes.')
        return
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root/'_patch_backups'/('LIDAR_TREE_SIZE_TEST1_' + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for name in changed:
        (backup/name).write_bytes(originals[name])
        manifest[name] = {'before_sha256': hashlib.sha256(originals[name]).hexdigest(),
                          'after_sha256': hashlib.sha256(edited[name].encode('utf-8')).hexdigest()}
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    try:
        for name in changed:
            (root/name).write_bytes(edited[name].encode('utf-8'))
        for name in changed:
            if (root/name).read_bytes() != edited[name].encode('utf-8'):
                raise IOError('Source write verification failed: ' + name)
    except BaseException:
        for name in changed:
            (root/name).write_bytes(originals[name])
        raise
    print('Applied LiDAR Tree Size TEST 1. Backup:', backup)
    print('Tree palettes select assets only. Standard/Heroic LiDAR mapping retained; Epic 1.20x / Mythic 1.80x Heroic.')

if __name__ == '__main__':
    main()
