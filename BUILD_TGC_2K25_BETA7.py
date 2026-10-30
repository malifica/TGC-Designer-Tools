"""Build the current Beta 7 checkout with the local alignment workflow.
Stage and verify the Windows executable before replacing dist output.
"""
from pathlib import Path
import ast
import datetime
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys

APP_TITLE='TGC Designer Tools 2K25 - Beta 7'
VERSION='v0.5.0-2k25-beta7'
EXE_NAME='tgc_gui_2k25_beta7'
CORE_VERIFIERS=(
    'VERIFY_BETA6_TREE_TOPOLOGY.py',
    'VERIFY_BETA6_MULTIPOLYGON_MULCH_V1.py',
    'VERIFY_BETA6_SPLINE_SURFACE_FIX_V1.py',
    'VERIFY_BETA6_OSM_ROAD_SPLIT_V4.py',
    'VERIFY_BETA6_CFS_MASK_ALIGNMENT_WORKFLOW_V1.py',
    'VERIFY_BETA6_CFS_ASYNC_MASK_REBUILD_V3.py',
    'VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5.py',
    'VERIFY_BETA6_CUSTOM_UNMATCHED_OSM_V5_1.py',
)
OPTIONAL_VERIFIERS=('VERIFY_BETA6_DEM_PREVIEW_FIX.py','VERIFY_BETA6_OUTPUT_PROGRESS.py')


def run(*args):
    command=[str(a) for a in args]
    print('\n> '+subprocess.list2cmdline(command),flush=True)
    subprocess.run(command,check=True)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def build_arguments(py, root, stage):
    args=[py,'-m','PyInstaller','--noconfirm','--clean','--onefile','--name',EXE_NAME,
          '--paths',root,'--workpath',stage/'work','--distpath',stage/'dist','--specpath',stage/'spec',
          '--add-binary',str(root/'laszip/laszip-cli.exe')+';laszip',
          '--additional-hooks-dir',root/'PyInstaller/hooks',
          '--runtime-hook',root/'PyInstaller/rthook_rasterio.py',
          '--add-data',str(root/'tree_profiles')+';tree_profiles',
          '--hidden-import','tgc_cfs_display','--hidden-import','lidar_tree_topology',
          '--hidden-import','tgc_tree_filter_controls',
          '--hidden-import','tgc_project_paths',
          '--hidden-import','uk_lidar_ui','--hidden-import','uk_lidar_downloader',
          '--hidden-import','scotland_s3','--hidden-import','exus_lidar_sources','--hidden-import','exus_raster',
          '--hidden-import','exus_additional_countries','--hidden-import','exus_resolution_policy',
          '--hidden-import','exus_france_crs','--hidden-import','exus_service_raster',
          '--hidden-import','tgc_local_alignment',
          '--hidden-import','tgc_local_alignment_detector',
          '--hidden-import','tgc_local_alignment_export',
          '--hidden-import','tgc_local_alignment_ui',
          '--hidden-import','tgc_cfs_widgets',
          '--collect-all','shapely']
    for module in ('tgc_projection_cache','tgc_dem_preview','tgc_output_progress'):
        if (root/(module+'.py')).is_file():args+=['--hidden-import',module]
    if (root/'tgc_lidar_fast_native.dll').is_file():
        args+=['--add-binary',str(root/'tgc_lidar_fast_native.dll')+';.']
    # TGC_UNITY_V3_HIDDEN_IMPORTS: preserve newer flags/imports and add only missing ones.
    for _unity_module in ('tgc_unity_raw_svg', 'tgc_unity_svg_paths', 'tgc_unity_import_ui', 'tgc_unity_presets', 'tgc_unity_build_check'):
        _unity_present = any(
            str(_arg) == "--hidden-import=" + _unity_module or
            (str(_arg) == "--hidden-import" and _i + 1 < len(args) and str(args[_i + 1]) == _unity_module)
            for _i, _arg in enumerate(args))
        if not _unity_present:
            args += ["--hidden-import", _unity_module]
    # TGC_BETA7_SHARED_CFS_UI_V1_BUILD: add UI module without replacing current flags.
    _ui_present = any(str(a) == '--hidden-import=tgc_ui_style' or
                      (str(a) == '--hidden-import' and i+1 < len(args) and str(args[i+1]) == 'tgc_ui_style')
                      for i,a in enumerate(args))
    if not _ui_present: args += ['--hidden-import','tgc_ui_style']
    # TGC_BETA7_LOCAL_FEATURES_V6_BUILD: additive, retain ALL existing arguments.
    for _local_module in ('tgc_local_alignment_topology','tgc_local_feature_filters'):
        _present = any(str(a) == '--hidden-import='+_local_module or
                       (str(a) == '--hidden-import' and i+1 < len(args) and str(args[i+1]) == _local_module)
                       for i,a in enumerate(args))
        if not _present: args += ['--hidden-import', _local_module]
    args.append(root/'tgc_tree_size_test1_entry.py')
    return args


def main():
    if os.name!='nt':raise RuntimeError('Run the batch on Windows in your existing TGC Python environment.')
    root=Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parent).resolve()
    py=Path(sys.executable)
    os.chdir(root)
    for module in ('overpy','PyInstaller','cv2','pyproj','numpy','PIL','tkinter','scipy','shapely'):
        if importlib.util.find_spec(module) is None:raise RuntimeError('Missing existing dependency: '+module)
    # TGC_UNITY_V3_DEPENDENCIES: retain every existing Beta 7 requirement.
    for _unity_dependency in ('rasterio',):
        if importlib.util.find_spec(_unity_dependency) is None:
            raise RuntimeError("Missing Unity import dependency: " + _unity_dependency)
    try:
        from shapely import contains_xy
    except ImportError as exc:
        raise RuntimeError('Local alignment requires Shapely 2. Run this environment\'s python -m pip install "shapely>=2.0,<3".') from exc
    for name in ('tgc_gui.py','laszip/laszip-cli.exe','PyInstaller/rthook_rasterio.py','tree_profiles','tgc_tree_size_test1_entry.py'):
        if not (root/name).exists():raise RuntimeError('Required existing source/build asset is missing: '+str(root/name))
    print('=== Build TGC Designer Tools 2K25 - Beta 7 ===',flush=True)
    print('EXE: '+EXE_NAME+'.exe | Window: '+APP_TITLE)
    for name in CORE_VERIFIERS:
        if not (root/name).is_file():raise RuntimeError('Missing previous-hotfix verifier: '+name)
        run(py,root/name)
    for name in OPTIONAL_VERIFIERS:
        if (root/name).is_file():run(py,root/name)
    run(py,root/'VERIFY_BETA7_CFS.py')
    run(py,root/'VERIFY_BETA7_TREE_CONTROLS.py')
    run(py,root/'VERIFY_BETA7_RESOLVED_SHAPES.py')
    run(py,root/'VERIFY_BETA7_UK_DOWNLOAD.py')
    run(py,root/'VERIFY_BETA7_EXUS_DOWNLOAD.py')
    run(py,root/'VERIFY_BETA7_EXUS_COUNTRIES_5M.py')
    run(py,root/'VERIFY_BETA7_LOCAL_ALIGNMENT_ENGINE.py')
    run(py,root/'VERIFY_BETA7_LOCAL_ALIGNMENT.py')
    run(py,root/'VERIFY_BETA7_LOCAL_MANUAL.py')
    run(py,'-m','py_compile','tgc_gui.py','tgc_image_terrain.py','tgc_tree_filter_controls.py','VERIFY_BETA7_TREE_CONTROLS.py',
        'tgc_project_paths.py','lidar_tree_topology.py','VERIFY_BETA7_RESOLVED_SHAPES.py',
        'tgc_local_alignment.py','tgc_local_alignment_detector.py',
        'tgc_local_alignment_export.py','tgc_local_alignment_ui.py','tgc_cfs_widgets.py')
    run(py,root/'tgc_tree_size_test1_entry.py','--verify-lidar-trees')
    run(py,root/'tgc_tree_size_test1_entry.py','--verify-local-alignment')
    # Window-size, DPI, report-height and interactive GUI checks are developer-only.
    # Release builds retain data, coordinate, resolution, source and EXE checks.
    for name in ('VERIFY_BETA7_FRANCE_CAPABILITIES_FIX.py','VERIFY_BETA7_FRANCE_CRS.py','VERIFY_BETA7_FRANCE_POLAND_SERVICE.py'):
        if (root/name).is_file():run(py,root/name)
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    stage=root/'build'/('beta7_release_build_'+stamp)
    for sub in ('work','dist','spec'):(stage/sub).mkdir(parents=True,exist_ok=True)
    if (root/'tgc_lidar_fast_native.dll').is_file():print('Bundling existing native LiDAR DLL unchanged.')
    else:print('NOTICE: no existing native LiDAR DLL; retained Python fallback remains in use.')
    tracked=[p for p in root.glob('*.py') if p.is_file()]
    before={p.name:digest(p) for p in tracked}
    # TGC_UNITY_V3_SOURCE_CHECKS: existing release checks remain in order.
    run(py, root/'VERIFY_TGC_UNITY_RAW_SVG_V1.py')
    run(py, root/'VERIFY_TGC_HBCC_MULCH_V1.py')
    run(py, root/'VERIFY_BETA7_UNITY_INTEGRATION_V2.py')
    run(py, root/'VERIFY_BETA7_UNITY_DISPATCH_V4.py')
    run(py,root/'VERIFY_BETA7_UI_STYLE_V1.py')
    run(py,root/'VERIFY_BETA7_LOCAL_RELATIONS.py')
    run(py,root/'VERIFY_BETA7_LOCAL_RELATION_CONSUMERS.py')
    run(py,root/'VERIFY_BETA7_LOCAL_FEATURES_V6.py','--installed')
    run(py,root/'VERIFY_BETA7_LOCAL_UI_V6.py','--source')
    run(*build_arguments(py,root,stage))
    built=stage/'dist'/(EXE_NAME+'.exe')
    if not built.is_file():raise RuntimeError('The expected staged Beta 7 EXE was not created.')
    with built.open('rb') as f:
        if f.read(2)!=b'MZ':raise RuntimeError('Invalid Windows EXE header')
    run(built,'--verify-lidar-trees')
    run(built,'--verify-unity-import')
    run(built,'--verify-ui-style')
    run(built,'--verify-local-alignment')
    from PyInstaller.archive.readers import ZlibArchiveReader, CArchiveReader
    archive=ZlibArchiveReader(str(stage/'work'/EXE_NAME/'PYZ-00.pyz'))
    required={'tgc_cfs_display','osm_alignment_viewer','osm_mask_alignment','GeoPointCloud','tgc_gui',
              'lidar_tree_topology','tgc_tree_filter_controls','tgc_project_paths','osm_preview_relations','osm_water_mulch_lock','tree_profile_manager'}
    required.update({'uk_lidar_ui','uk_lidar_downloader'})
    required.update({'scotland_s3','exus_lidar_sources','exus_raster'})
    required.update({'exus_additional_countries','exus_resolution_policy'})
    required.add('exus_france_crs')
    required.add('exus_service_raster')
    required.update({'tgc_local_alignment','tgc_local_alignment_detector','tgc_local_alignment_export','tgc_local_alignment_ui','tgc_cfs_widgets','shapely'})
    # TGC_UNITY_V3_ARCHIVE_CHECK: preserve all current required modules.
    required.update({'tgc_unity_raw_svg', 'tgc_unity_svg_paths', 'tgc_unity_import_ui', 'tgc_unity_presets', 'tgc_unity_build_check'})
    required.update({'tgc_ui_style'})
    required.update({'tgc_local_alignment_topology','tgc_local_feature_filters'})
    if not required.issubset(archive.toc):raise RuntimeError('Missing frozen modules: '+repr(required-set(archive.toc)))
    bundled_names = [str(name).lower() for name in CArchiveReader(str(built)).toc]
    if not any('geos_c' in name and name.endswith('.dll') for name in bundled_names):
        raise RuntimeError('Frozen local alignment is missing the Shapely GEOS runtime')
    def constants(code):
        result=[]
        for c in code.co_consts:
            if isinstance(c,str):result.append(c)
            elif hasattr(c,'co_consts'):result.extend(constants(c))
        return result
    if 'TGC_BETA7_SCOTLAND_DIRECT_S3_V1' not in constants(archive.extract('scotland_s3')):
        raise RuntimeError('Frozen EXE is missing direct Scottish AWS discovery')
    if 'TGC_BETA7_IGN_LAMBERT93_CONTRACT_V1' not in constants(archive.extract('exus_france_crs')):
        raise RuntimeError('Frozen EXE is missing the guarded IGN CRS compatibility fix')
    if 'TGC_BETA7_SERVICE_DOWNLOAD_V2' not in constants(archive.extract('exus_service_raster')):
        raise RuntimeError('Frozen EXE is missing the France/Poland service repair')
    if 'TGC_BETA7_UNITY_INTEGRATION_V2' not in constants(archive.extract('tgc_unity_build_check')):
        raise RuntimeError('Frozen EXE is missing the integrated Unity importer')
    identity=constants(archive.extract('tgc_gui'))
    if APP_TITLE not in identity or VERSION not in identity:raise RuntimeError('Frozen Beta 7 identity mismatch')
    option_keys={'filter_lidar_trees_surfaces','exclude_lidar_trees_red_mask'}
    if not option_keys.issubset(set(identity)):
        raise RuntimeError('Frozen GUI is missing the new tree controls')
    if not option_keys.issubset(set(constants(archive.extract('tgc_image_terrain')))):
        raise RuntimeError('Frozen importer is missing tree-control routing')
    if 'TGC_BETA7_RESOLVED_SHAPES_V1' not in constants(archive.extract('lidar_tree_topology')):
        raise RuntimeError('Frozen EXE is missing the resolved-shape policy')
    if 'TGC_BETA7_CURRENT_PROJECT_CFS_V1' not in constants(archive.extract('tgc_project_paths')):
        raise RuntimeError('Frozen EXE is missing current-project CFS selection')
    if before!={p.name:digest(p) for p in tracked}:raise RuntimeError('Source changed during build; no EXE replaced.')
    checksum=digest(built)
    out=root/'dist';out.mkdir(exist_ok=True);target=out/built.name
    checksum_path=target.with_name(target.name+'.sha256.txt')
    backup=root/'backups'/('beta7_exe_'+stamp);backup.mkdir(parents=True)
    for path in (target,checksum_path):
        if path.exists():shutil.copy2(path,backup/path.name)
    temp_checksum=stage/'dist'/(built.name+'.sha256.txt')
    temp_checksum.write_bytes((checksum+'  '+built.name+'\n').encode('ascii'))
    replaced=False
    try:
        os.replace(built,target)
        replaced=True
        os.replace(temp_checksum,checksum_path)
    except Exception:
        # Restore any existing Beta 7, not Beta 6. Keep checked build for diagnosis.
        if replaced:
            if (backup/target.name).exists():shutil.copy2(backup/target.name,target)
            elif target.exists():target.unlink()
            if (backup/checksum_path.name).exists():shutil.copy2(backup/checksum_path.name,checksum_path)
        raise
    print('\nBUILD COMPLETE\nLaunch: '+str(target)+'\nWindow: '+APP_TITLE+'\nSHA-256: '+checksum)
    print('Beta 6 EXE was not replaced. No GitHub changes.')
    print('CFS: Local Tee/Bunker Alignment previews residual moves; only accepted proposals create a corrected OSM copy. Apply + Rebuild Mask afterward.')
    print('OSM/surface filtering defaults OFF; red-mask and 50 m controls remain independent. Reuse the heightmap and regenerate the course. CFS starts from the current working project.')
    print('Unity RAW + SVG importer and dry-mulch support included; no bundled course preset; frozen import smoke test passed.')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('\nBUILD FAILED: '+str(exc),file=sys.stderr,flush=True);sys.exit(1)
