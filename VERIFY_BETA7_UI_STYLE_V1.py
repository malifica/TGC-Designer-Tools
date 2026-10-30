"""Portable source checks for the shared CFS UI. Run --live for real Tk tests."""
from pathlib import Path
import ast
import importlib.util
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
LIVE='--live' in sys.argv
if LIVE: sys.argv.remove('--live')

def text(name): return (ROOT/name).read_text(encoding='utf-8-sig')
def same(node,expr): return ast.dump(node,include_attributes=False)==ast.dump(ast.parse(expr,mode='eval').body,include_attributes=False)
def load_build():
    spec=importlib.util.spec_from_file_location('_tgc_shared_ui_build',ROOT/'BUILD_TGC_2K25_BETA7.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class SourceTests(unittest.TestCase):
    def test_python311(self):
        for n in ('tgc_ui_style.py','tgc_gui.py','osm_alignment_viewer.py','tgc_unity_import_ui.py',
                  'tgc_unity_presets.py','tgc_unity_build_check.py','tgc_tree_size_test1_entry.py',
                  'BUILD_TGC_2K25_BETA7.py'):
            ast.parse(text(n),filename=n,feature_version=(3,11))
    def test_main_installs_shared_style_once(self):
        self.assertEqual(text('tgc_gui.py').count('_shared_ui = install_shared_ui(root)'),1)
    def test_dynamic_cfs_palette(self):
        import tgc_ui_style as ui
        self.assertIn('tgc_cfs_widgets',ui.cfs_palette.__code__.co_names)
        self.assertNotIn('HBCC',text('tgc_ui_style.py'))
    def test_no_course_preset(self):
        import tgc_unity_presets as p
        self.assertEqual(p.PRESETS,{})
        self.assertFalse(hasattr(p,'HBCC_SETTINGS'))
        self.assertFalse(hasattr(p,'hbcc_settings'))
        code=text('tgc_unity_import_ui.py')
        self.assertNotIn('use_hbcc_preset',code)
        self.assertNotIn('HBCC preset',code)
        self.assertNotIn('Trees|#faa0be',code)
    def test_generic_unity_retained(self):
        code=text('tgc_unity_import_ui.py')
        for name in ('load_settings','inspect','show_preview','convert','match_orientation'):
            self.assertIn('def '+name+'(',code)
        self.assertIn('self.mapping=dict(s.get',code)
        self.assertIn("'mulch'",text('tgc_unity_raw_svg.py'))
    def test_local_wrapper_only(self):
        code=text('osm_alignment_viewer.py')
        self.assertEqual(code.count('open_local_alignment = wrap_local_alignment(open_local_alignment)'),1)
        self.assertEqual(code.count('            open_local_alignment(self)'),1)
        self.assertIn('from tgc_local_alignment_ui import open_local_alignment',code)
    def test_build_additions_once(self):
        args=list(map(str,load_build().build_arguments('python',ROOT,ROOT/'unused-stage')))
        hidden=[args[i+1] for i,a in enumerate(args[:-1]) if a=='--hidden-import']
        hidden.extend(a.split('=',1)[1] for a in args if a.startswith('--hidden-import='))
        self.assertEqual(hidden.count('tgc_ui_style'),1)
        for n in ('tgc_local_alignment_ui','tgc_cfs_widgets','exus_service_raster','tgc_unity_raw_svg'):
            self.assertIn(n,hidden)
    def test_source_check_before_freeze(self):
        calls=[n for n in ast.walk(ast.parse(text('BUILD_TGC_2K25_BETA7.py'))) if isinstance(n,ast.Call)]
        checks=[n for n in calls if same(n,"run(py,root/'VERIFY_BETA7_UI_STYLE_V1.py')")]
        freezes=[n for n in calls if same(n,'run(*build_arguments(py,root,stage))')]
        self.assertEqual(len(checks),1);self.assertEqual(len(freezes),1)
        self.assertLess(checks[0].lineno,freezes[0].lineno)
    def test_frozen_ui_before_publish(self):
        calls=[n for n in ast.walk(ast.parse(text('BUILD_TGC_2K25_BETA7.py'))) if isinstance(n,ast.Call)]
        checks=[n for n in calls if same(n,"run(built,'--verify-ui-style')")]
        pubs=[n for n in calls if same(n,'os.replace(built,target)')]
        self.assertEqual(len(checks),1);self.assertEqual(len(pubs),1)
        self.assertLess(checks[0].lineno,pubs[0].lineno)
    def test_ui_dispatch_no_main_gui(self):
        import types
        m=types.ModuleType('tgc_ui_style');calls=[];m.verify=lambda:calls.append('ui')
        with patch.dict(sys.modules,{'tgc_ui_style':m,'tgc_gui':None}),patch.object(sys,'argv',['app','--verify-ui-style']):
            try:exec(compile(text('tgc_tree_size_test1_entry.py'),'entry','exec'),{'__name__':'__main__'})
            except SystemExit as e:self.assertIn(e.code,(None,0))
        self.assertEqual(calls,['ui'])
    def test_local_verifiers_retained(self):
        build=text('BUILD_TGC_2K25_BETA7.py')
        for n in ('VERIFY_BETA7_LOCAL_ALIGNMENT_ENGINE.py','VERIFY_BETA7_LOCAL_ALIGNMENT.py','VERIFY_BETA7_LOCAL_MANUAL.py'):
            self.assertIn(n,build)
        self.assertIn("run(built,'--verify-local-alignment')",build)
    def test_no_data_layer_import(self):
        tree=ast.parse(text('tgc_ui_style.py')); names=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):names.extend(a.name for a in n.names)
            elif isinstance(n,ast.ImportFrom):names.append(n.module)
        for forbidden in ('OSMTGC','tgc_tools','tgc_image_terrain','rasterio','numpy'):
            self.assertNotIn(forbidden,names)
    def test_source_palette_helper_untouched_available(self):
        import importlib
        helper=importlib.import_module('tgc_cfs_widgets')
        self.assertTrue(callable(getattr(helper,'action_button',None)))
    def test_generic_conversion_smoke_not_removed(self):
        code=text('tgc_unity_build_check.py')
        self.assertIn('core.create_pair(',code)
        self.assertIn('OSMTGC.newMulch(',code)
        self.assertIn('3000*100/65536',code)

@unittest.skipUnless(LIVE,'Use --live on a machine with a graphical display')
class LiveTests(unittest.TestCase):
    def test_installed_cfs_palette_and_resize_smoke(self):
        import tgc_ui_style
        tgc_ui_style.verify()

if __name__=='__main__':unittest.main(verbosity=2)
