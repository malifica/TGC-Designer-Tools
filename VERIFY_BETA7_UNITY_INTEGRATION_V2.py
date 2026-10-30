"""Beta 7 Unity contracts; additive build integration V3.
Checks accept extended/multiline dependency lists and preserve other build hooks.
No Windows/in-game claims.
"""
from pathlib import Path
import ast
import unittest
from unittest.mock import patch
import importlib.util
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
MODULES=('tgc_unity_raw_svg','tgc_unity_svg_paths','tgc_unity_import_ui','tgc_unity_presets','tgc_unity_build_check')

def text(name):return (ROOT/name).read_text(encoding='utf-8-sig')
def load_build():
    spec=importlib.util.spec_from_file_location('_beta7_build_contract',ROOT/'BUILD_TGC_2K25_BETA7.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class IntegrationTests(unittest.TestCase):
    def test_modules_present_python311(self):
        for name in MODULES:ast.parse(text(name+'.py'),filename=name,feature_version=(3,11))
    def test_gui_control_one(self):
        self.assertEqual(text('tgc_gui.py').count('text="Import Unity RAW + Course SVG"'),1)
        self.assertEqual(text('tgc_gui.py').count('def runUnityRawSVG('),1)
    def test_shared_dem_handoff(self):
        tree=ast.parse(text('tgc_gui.py'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='runUnityRawSVG')
        code=ast.get_source_segment(text('tgc_gui.py'),fn)
        self.assertIn('dem_files_override=[report["outputs"]["dem"]]',code)
        self.assertIn('set_value("custom_unmatched_osm", False)',code)
        self.assertIn('set_value("adjust_ew", 0.0)',code)
        self.assertIn('set_value("adjust_ns", 0.0)',code)
    def test_regular_dem_reducer_retained(self):
        code=text('dem_map_api.py')
        self.assertIn('if authored_unity_surface:',code)
        self.assertIn('dem = _reduce_dem_lidar_style(',code)
        self.assertIn('dem = resample_authored_dem(',code)
    def test_build_arguments_modules(self):
        b=load_build();args=list(map(str,b.build_arguments('python',ROOT,ROOT/'test-stage')))
        hidden=[args[i+1] for i,a in enumerate(args[:-1]) if a=='--hidden-import'] + [a.split('=',1)[1] for a in args if a.startswith('--hidden-import=')]
        for name in MODULES:self.assertEqual(hidden.count(name),1,name)
        for name in ('exus_service_raster','tgc_tree_filter_controls','tgc_project_paths','uk_lidar_ui'):self.assertIn(name,hidden)
    def test_verifiers_before_freeze(self):
        tree=ast.parse(text('BUILD_TGC_2K25_BETA7.py'))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        same=lambda n,e:ast.dump(n,include_attributes=False)==ast.dump(ast.parse(e,mode='eval').body,include_attributes=False)
        freeze=[n for n in main.body if isinstance(n,ast.Expr) and same(n.value,'run(*build_arguments(py,root,stage))')]
        self.assertEqual(len(freeze),1)
        for name in ('VERIFY_TGC_UNITY_RAW_SVG_V1.py','VERIFY_TGC_HBCC_MULCH_V1.py','VERIFY_BETA7_UNITY_INTEGRATION_V2.py'):
            calls=[n for n in main.body if isinstance(n,ast.Expr) and same(n.value,'run(py,root/'+repr(name)+')')]
            self.assertEqual(len(calls),1,name)
            self.assertLess(calls[0].lineno,freeze[0].lineno)
    def test_frozen_test_before_replace(self):
        tree=ast.parse(text('BUILD_TGC_2K25_BETA7.py'))
        same=lambda n,e:ast.dump(n,include_attributes=False)==ast.dump(ast.parse(e,mode='eval').body,include_attributes=False)
        checks=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and same(n,"run(built,'--verify-unity-import')")]
        replace=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and same(n,'os.replace(built,target)')]
        self.assertEqual(len(checks),1);self.assertEqual(len(replace),1)
        self.assertLess(checks[0].lineno,replace[0].lineno)
    def test_frozen_archive_module_contract(self):
        # Evaluate just required.update/set literals, never execute a build.
        tree=ast.parse(text('BUILD_TGC_2K25_BETA7.py'));found=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='required' and n.func.attr=='update':
                if n.args:
                    try:found.update(ast.literal_eval(n.args[0]))
                    except (ValueError,TypeError):pass
        self.assertTrue(set(MODULES).issubset(found))
    def test_entry_verify_never_imports_gui(self):
        # Execute the real entry with controlled verification module. GUI would raise.
        import types
        m=types.ModuleType('tgc_unity_build_check');called=[];m.verify=lambda:called.append(True)
        with patch.dict(sys.modules,{'tgc_unity_build_check':m,'tgc_gui':None}),patch.object(sys,'argv',['app','--verify-unity-import']):
            try:
                exec(compile(text('tgc_tree_size_test1_entry.py'),'entry','exec'),{'__name__':'__main__'})
            except SystemExit as exc:
                self.assertIn(exc.code,(0,None))
        self.assertEqual(called,[True])
    def test_no_bundled_presets(self):
        import tgc_unity_presets as presets
        self.assertEqual(presets.PRESETS,{})
        self.assertFalse(hasattr(presets,'HBCC_SETTINGS'))
        self.assertFalse(hasattr(presets,'hbcc_settings'))
    def test_no_course_specific_default_mapping(self):
        code=text('tgc_unity_presets.py')+text('tgc_unity_import_ui.py')
        self.assertNotIn('Trees|#faa0be',code)
        self.assertNotIn('2240',text('tgc_unity_import_ui.py'))
    def test_ui_generic_controls_retained(self):
        code=text('tgc_unity_import_ui.py')
        self.assertNotIn('HBCC preset',code)
        self.assertNotIn('def use_hbcc_preset',code)
        for action in ('load_settings','inspect','show_preview','match_orientation','convert'):
            self.assertIn('def '+action+'(',code)
    def test_module_smoke_test_no_gui(self):
        # The native mulch verifier exercises OSMTGC separately; this portable
        # source contract suite tests the pure conversion, without overpy stubs.
        import tempfile,xml.etree.ElementTree as ET,numpy as np,rasterio
        import tgc_unity_raw_svg as c
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=p/'test.raw';s=p/'test.svg';np.arange(25,dtype='<u2').tofile(r)
            s.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><path id="dry" d="M1 1h2v2h-2z"/></svg>',encoding='utf-8')
            settings=dict(rows=5,cols=5,bits=16,byte_order='little',height_m=100.,base_elevation_m=0.,width_m=8.,length_m=8.,orientation='as_stored',output_spacing_m=2.,mapping={'dry':'mulch'})
            report,_,_=c.create_pair(r,s,p/'out',settings,printf=lambda *_:None)
            with rasterio.open(report['outputs']['dem']) as src:self.assertEqual(src.shape,(4,4))
            tags={t.get('k'):t.get('v') for t in ET.parse(report['outputs']['osm']).getroot().find('way').findall('tag')}
            self.assertEqual(tags['surface'],'woodchips');self.assertNotIn('golf',tags);self.assertNotIn('natural',tags)
    def test_unity_dependencies_checked(self):
        tree=ast.parse(text('BUILD_TGC_2K25_BETA7.py')); found=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.For) and isinstance(n.target,ast.Name):
                expression='importlib.util.find_spec('+n.target.id+')'
                expected=ast.dump(ast.parse(expression,mode='eval').body,include_attributes=False)
                if any(isinstance(v,ast.Call) and ast.dump(v,include_attributes=False)==expected for v in ast.walk(n)):
                    try:found.update(ast.literal_eval(n.iter))
                    except (ValueError,TypeError):pass
        self.assertTrue({'rasterio','shapely','scipy'}.issubset(found))
    def test_build_identity_retained(self):
        b=load_build();self.assertEqual(b.VERSION,'v0.5.0-2k25-beta7');self.assertEqual(b.EXE_NAME,'tgc_gui_2k25_beta7')

if __name__=='__main__':unittest.main(verbosity=2)
