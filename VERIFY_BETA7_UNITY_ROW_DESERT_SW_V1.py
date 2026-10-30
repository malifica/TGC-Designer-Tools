"""Focused installed-source checks; no complete app, Windows EXE or game launch.
Tree generation functions are loaded verbatim from tgc_image_terrain in isolation.
"""
from pathlib import Path
import argparse, ast, copy, importlib.util, itertools, json, math, random, sys, unittest
from collections import Counter
from functools import partial

parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parent));parser.add_argument('--ui',action='store_true')
args,unused=parser.parse_known_args();ROOT=Path(args.root).resolve();sys.path.insert(0,str(ROOT))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

manager=load('_desert_profile_manager_check',ROOT/'tree_profile_manager.py')
defs=load('_desert_definitions_check',ROOT/'tgc_definitions.py')
raw=json.loads((ROOT/'tree_profiles/desert_southwest.json').read_text(encoding='utf-8-sig'))
profile=manager.get_profile('Desert Southwest')
gui=(ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig');gtree=ast.parse(gui)

# No mock algorithm: compile the actual saved tree-writing functions with their real
# definitions and profile manager, without importing unrelated parser/GUI modules.
needed={'get_object_item','get_placed_object','_tree_scales_from_lidar','_get_profile_trees','get_trees'}
terrain=ast.parse((ROOT/'tgc_image_terrain.py').read_text(encoding='utf-8-sig'))
nodes=[n for n in terrain.body if isinstance(n,ast.FunctionDef) and n.name in needed]
if {n.name for n in nodes}!=needed:raise RuntimeError('Missing current tree-generation functions')
space={'json':json,'math':math,'random':random,'itertools':itertools,'tree_profile_manager':manager,'tgc_definitions':defs}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'installed tree functions','exec'),space)

def assignment(name):
    return next(n for n in gtree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))

def flatten(groups):
    return {(i['position']['x'],i['position']['z']):(g['Key']['path'],i) for g in groups for i in g['Value']['items']}

TREES=[(100.+i,200.-i,.8+(i%9)*.6,3.+(i%13)*1.4) for i in range(90)]

class ProfileTests(unittest.TestCase):
    def test_enabled_and_visible_once(self):
        self.assertIsNotNone(profile);self.assertEqual(manager.get_profile_choices().count('Desert Southwest'),1)
        self.assertTrue(raw['enabled']);self.assertEqual(profile['id'],'desert_southwest')
    def test_source_and_count(self):
        self.assertEqual(raw['source_sha256'],'2167a31d466ed8941d31984ef5f6a4a545549ebd76f15199e9926ae46e87087f')
        self.assertEqual(len(raw['assets']),15);self.assertEqual(sum(a['count'] for a in raw['assets']),674)
    def test_paths_and_pools(self):
        self.assertEqual(len({a['path'] for a in profile['assets']}),15)
        self.assertEqual(Counter(a['shape'] for a in profile['assets']),{'normal':9,'skinny':6})
        for a in profile['assets']:
            self.assertIn('/Trees/',a['path']);self.assertNotIn('/Bushes/',a['path'])
            self.assertEqual('/Saguaro_Cactus/' in a['path'],a['shape']=='skinny')
    def test_weight_frequencies(self):
        self.assertAlmostEqual(sum(a['weight'] for a in profile['assets']),1.)
        for a in raw['assets']:self.assertAlmostEqual(a['weight'],a['count']/674)
    def test_native_theme_and_materials(self):
        p=profile['visual_material_preset'];self.assertEqual(p['theme'],2)
        self.assertEqual(p['surfaces2'][6]['name'],'Green38_PaynesValley')
        self.assertEqual(p['surfaces2'][8]['name'],'Fairway38_PaynesValley')
        self.assertEqual(p['surfaces2'][0]['name'],'Sand30_TPC_Louisiana')
        self.assertFalse({'treeOptions','backdrop','detailDensity','terrainHeight','height','placedObjects4'} & set(p))
    def test_material_application_preserves_other_fields(self):
        seed={'theme':99,'height':[1,2],'terrainHeight':[3],'treeOptions':{'density':123},'detailDensity':456,'backdrop':7,'placedObjects4':[{'untouched':True}]}
        result=manager.apply_visual_material_preset(copy.deepcopy(seed),'Desert Southwest',printf=lambda *_:None)
        for k in set(seed)-{'theme'}:self.assertEqual(result[k],seed[k])
        self.assertEqual(result['theme'],2);self.assertEqual(result['surfaces2'],raw['visual_material_preset']['surfaces2'])
    def test_metadata_theme_sync(self):
        result=manager.apply_visual_material_preset({'courseTheme':99,'courseVersion':49,'_id':'keep'},'Desert Southwest',metadata=True)
        self.assertEqual(result['courseTheme'],2);self.assertEqual(result['courseVersion'],49);self.assertEqual(result['_id'],'keep')
    def test_standard_lidar_scaling_unchanged(self):self.check_mode(manager.STANDARD_SCALE_MODE)
    def test_heroic_lidar_scaling_unchanged(self):self.check_mode(manager.HEROIC_SCALE_MODE)
    def test_epic_lidar_scaling_unchanged(self):self.check_mode(manager.EPIC_SCALE_MODE)
    def test_mythic_lidar_scaling_unchanged(self):self.check_mode(manager.MYTHIC_SCALE_MODE)
    def check_mode(self,mode):
        expected=space['_tree_scales_from_lidar'](TREES,mode)
        result=space['get_trees'](2,True,TREES,course_version=25,tree_profile='Desert Southwest',tree_scale_mode=mode)
        flat=flatten(result);self.assertEqual(len(flat),len(TREES))
        for tree,sc in zip(TREES,expected):
            path,item=flat[tree[:2]];self.assertEqual(tuple(item['scale'][a] for a in 'xyz'),sc)
            self.assertEqual(item['position']['y'],'-Infinity')
            self.assertEqual('/Saguaro_Cactus/' in path,tree[3]/tree[2]>=2.5)
        for group in result:self.assertEqual(set(group['Value']),{'items','clusters','splines','objectPaths2','IsEmpty'})
    def test_epic_mythic_ratios(self):
        h=space['_tree_scales_from_lidar'](TREES,manager.HEROIC_SCALE_MODE)
        for mode,mult in [(manager.EPIC_SCALE_MODE,1.2),(manager.MYTHIC_SCALE_MODE,1.8)]:
            for a,b in zip(h,space['_tree_scales_from_lidar'](TREES,mode)):
                for x,y in zip(a,b):self.assertAlmostEqual(x*mult,y)
    def test_profile_scale_stats_cannot_change_lidar_sizes(self):
        altered=copy.deepcopy(profile);altered['scale_defaults']={a:dict(p10=100.,p50=200.,p90=300.) for a in 'xyz'}
        for a in altered['assets']:a['uniform_scale']=dict(p10=100.,p50=200.,p90=300.)
        random.seed(7);first=space['_get_profile_trees'](profile,TREES,25,tree_scale_mode=manager.HEROIC_SCALE_MODE)
        random.seed(7);second=space['_get_profile_trees'](altered,TREES,25,tree_scale_mode=manager.HEROIC_SCALE_MODE)
        self.assertEqual(first,second)
    def test_osm_generation_uses_palette(self):
        result=space['get_trees'](2,True,TREES,25,tree_profile='Desert Southwest',tree_source='osm')
        self.assertEqual(len(flatten(result)),len(TREES))
        self.assertTrue({g['Key']['path'] for g in result}<={a['path'] for a in profile['assets']})
        self.assertEqual(len(manager._pool(profile,source_kind='osm')),15)
    def test_unselected_theme_unchanged(self):
        random.seed(19);a=space['get_trees'](2,True,TREES,25,tree_profile=manager.DESIGNER_THEME_LABEL)
        manager.load_profiles(force=True)
        random.seed(19);b=space['get_trees'](2,True,TREES,25,tree_profile=None)
        self.assertEqual(a,b)

class LayoutAndBuildTests(unittest.TestCase):
    def test_button_same_parent(self):
        d=assignment('dembutton').value;u=assignment('unityImportButton').value
        self.assertEqual(ast.dump(d.args[0]),ast.dump(u.args[0]));self.assertEqual(u.args[0].id,'lidarControlFrame')
    def test_no_empty_unity_row(self):
        self.assertFalse(any(isinstance(n,ast.Name) and n.id=='unityImportFrame' for n in ast.walk(gtree)))
    def test_button_command_retained(self):
        u=assignment('unityImportButton').value
        command=next(k.value for k in u.keywords if k.arg=='command')
        expected=ast.parse('partial(runUnityRawSVG, scale_entry, lidarPrintf, auto_red_mask_var, auto_red_mask_buffer_var)',mode='eval').body
        self.assertEqual(ast.dump(command),ast.dump(expected))
    def test_button_packed_after_dem(self):
        nodes=[n for n in ast.walk(gtree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='unityImportButton' and n.func.attr=='pack']
        self.assertEqual(len(nodes),1);kw={k.arg:k.value for k in nodes[0].keywords}
        self.assertEqual(kw['after'].id,'dembutton');self.assertEqual(kw['side'].id,'LEFT');self.assertEqual(ast.literal_eval(kw['pady']),5)
    def test_profile_selector_dynamic(self):
        self.assertIn('tree_profile_manager.get_profile_choices()',gui)
    def test_packaging_uses_profile_folder(self):
        b=load('_desert_build',ROOT/'BUILD_TGC_2K25_BETA7.py');self.assertEqual(b.EXE_NAME,'tgc_gui_2k25_beta7')
        build=list(map(str,b.build_arguments('python',ROOT,ROOT/'test_stage')))
        entries=[build[i+1] for i,x in enumerate(build[:-1]) if x=='--add-data']
        self.assertIn(str(ROOT/'tree_profiles')+';tree_profiles',entries)
    def test_python311_syntax(self):ast.parse(gui,feature_version=(3,11))

@unittest.skipUnless(args.ui,'UI check requested with --ui')
class LiveRowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        self.tk=tk;self.root=tk.Tk();self.root.geometry('1440x260+9000+9000')
        self.root.title('Unity row verification (test only)')
        self.called=[]
        ns={'tk':tk,'ttk':ttk,'Frame':tk.Frame,'Label':tk.Label,'Button':tk.Button,'LEFT':tk.LEFT,'END':tk.END,
            'tool_bg':'#d4d7db','text_fg':'#172b3c','lidar':self.root,'partial':partial,'options_entries_dict':{},
            'AUTO_RED_MASK_BUFFER_DEFAULT_M':5,'lidarPrintf':lambda *_:None,
            'runLidar':lambda *a:None,'runDEM':lambda *a:None,'runUnityRawSVG':lambda *a:self.called.append(a)}
        begin=assignment('lidarControlFrame').lineno;end=assignment('unityImportButton').end_lineno
        for n in gtree.body:
            if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='unityImportButton':end=n.end_lineno
        code='\n'.join(gui.splitlines()[begin-1:end]);exec(compile(code,'actual import-row code','exec'),ns)
        # Use the installed shared presentation helper when present.
        if (ROOT/'tgc_ui_style.py').exists():
            style=load('_desert_style',ROOT/'tgc_ui_style.py');style.install(self.root)
        self.ns=ns;self.root.update()
    def tearDown(self):self.root.destroy()
    def test_actual_row_and_right_order(self):
        ns=self.ns;d=ns['dembutton'];u=ns['unityImportButton'];l=ns['lidarbutton']
        self.assertEqual(u.master,d.master);self.assertEqual(d.winfo_y(),u.winfo_y())
        self.assertEqual(l.winfo_y(),u.winfo_y());self.assertGreater(u.winfo_x(),d.winfo_x()+d.winfo_width())
        self.assertLessEqual(u.winfo_rootx()+u.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
    def test_callback_invocation(self):
        self.ns['unityImportButton'].invoke();self.assertEqual(len(self.called),1)
        self.assertIs(self.called[0][0],self.ns['scale_entry'])
    def test_normal_widths(self):
        for width in (1280,1440,1680):
            self.root.geometry(str(width)+'x260+9000+9000');self.root.update()
            u=self.ns['unityImportButton'];d=self.ns['dembutton']
            self.assertEqual(u.winfo_y(),d.winfo_y())
            self.assertLessEqual(u.winfo_rootx()+u.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
    def test_dynamic_theme_picker(self):
        from tkinter import ttk
        combo=ttk.Combobox(self.root,values=manager.get_profile_choices());combo.set('Desert Southwest')
        self.assertEqual(combo.get(),'Desert Southwest');self.assertIn('Desert Southwest',combo['values'])

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+unused,verbosity=2)
