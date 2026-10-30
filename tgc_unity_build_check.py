"""Packaged-import smoke test. Runs in source or the staged EXE, never opens GUI."""
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

MARKER = 'TGC_BETA7_UNITY_INTEGRATION_V2'

def verify():
    import numpy as np
    import rasterio
    import tgc_unity_raw_svg as core
    import tgc_unity_import_ui as ui
    import OSMTGC
    import auto_red_mask
    import osm_water_mulch_lock as lock
    import tgc_unity_presets
    if tgc_unity_presets.PRESETS or hasattr(ui.UnityImportDialog, 'use_hbcc_preset'):
        raise RuntimeError('Unexpected bundled course-specific preset')
    # Generic asymmetric smoke fixture, not application defaults or a course preset.
    settings={'rows':5,'cols':5,'bits':16,'byte_order':'little',
              'width_m':8.,'length_m':8.,'height_m':100.,'base_elevation_m':0.,
              'normalization_divisor':65536,'orientation':'as_stored',
              'output_spacing_m':2.,'epsg':32631,'center_e':500000.,'center_n':5000000.,
              'curve_tolerance_m':.15,'max_segment_m':8.,'mapping':{'dry':'mulch'}}
    if 'mulch' not in core.KINDS or not hasattr(OSMTGC,'newMulch'):
        raise RuntimeError('Missing native dry-mulch import support')
    if not hasattr(lock,'DRY_LOCK_KEY'):
        raise RuntimeError('Missing dry-mulch material protection')
    if not hasattr(auto_red_mask,'_feature_mode_and_width_m'):
        raise RuntimeError('Missing terrain-mask support')
    with tempfile.TemporaryDirectory(prefix='tgc_unity_build_') as tmp:
        p=Path(tmp);raw=p/'test.raw';svg=p/'test.svg'
        values=(np.arange(25,dtype=np.uint16).reshape(5,5)*1000).astype('<u2')
        values.tofile(raw)
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" viewBox="0 0 8 8"><g inkscape:label="Mulch"><path id="dry" fill="#b29a76" d="M1 1h2v2h-2z"/></g><g inkscape:label="Water"><path id="pond" fill="blue" d="M5 5h2v2h-2z"/></g></svg>',encoding='utf-8')
        settings.update(rows=5,cols=5,width_m=8.,length_m=8.,orientation='as_stored',output_spacing_m=2.,output_prefix='Smoke')
        report,features,dem=core.create_pair(raw,svg,p/'out',settings,printf=lambda *_:None)
        with rasterio.open(report['outputs']['dem']) as src:
            if src.shape != (4,4) or src.res != (2.,2.) or src.crs.to_epsg()!=32631:
                raise RuntimeError('GeoTIFF size/CRS mismatch')
            if src.units != ('m',) or src.dtypes != ('float32',):
                raise RuntimeError('GeoTIFF height units/type mismatch')
            if not np.isclose(src.read(1)[0,0],3000*100/65536,atol=1e-5):
                raise RuntimeError('RAW height scale/resampling mismatch')
        root=ET.parse(report['outputs']['osm']).getroot()
        tags=[{t.get('k'):t.get('v') for t in w.findall('tag')} for w in root.findall('way')]
        dry=[t for t in tags if t.get('golf')=='mulch']
        wet=[t for t in tags if t.get('natural')=='water']
        if len(dry)!=1 or len(wet)!=1 or 'natural' in dry[0]:
            raise RuntimeError('Dry mulch/water tags were not kept separate')
        pts=[(0.,0.,0.),(10.,0.,0.),(10.,0.,10.),(0.,0.,10.),(0.,0.,0.)]
        spline=OSMTGC.newMulch(pts,course_version=25)
        if spline['surface']!=10 or not spline['isClosed'] or not spline['isFilled']:
            raise RuntimeError('Native mulch spline conversion failed')
    print('UNITY RAW + SVG BETA 7 BUILD CHECK PASSED: paired GeoTIFF/OSM, generic height scaling and dry mulch; no bundled course preset.')

if __name__ == '__main__':verify()
