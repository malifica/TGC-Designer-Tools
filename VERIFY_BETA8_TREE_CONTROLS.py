"""Exercise installed production tree-routing functions and independent switches.

Synthetic OSM fixtures are explicit test objects, not parser replacements.
Optional --gui opens the actual Tk main window. --osm/--heightmap/--mask are not
needed by the builder. Existing topology/native-parser suites still run too.
"""
from pathlib import Path
import ast
import copy
import importlib.util
import math
import sys
import types
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import tgc_image_terrain as terrain
import lidar_feature_filter as features
import lidar_tree_topology as topology
import tgc_tree_filter_controls as controls

class Direct:
    def projToTGC(self,e,n,y):return (float(e),float(y),float(n))
    def latlonToTGC(self,lat,lon,dx=0,dz=0):return (float(lon)+dx,0.,float(lat)+dz)
class MaskGrid:
    def __init__(self):self.origin=(0.,0.);self.proj=None
    def projToCV2(self,e,n,scale):return ((n-self.origin[1])/scale,(e-self.origin[0])/scale)
class RelationWay:
    _type_value='way'
    def __init__(self,ref,role):self.ref=ref;self.role=role
class Way:
    def __init__(self,i,points,kind=''):
        self.id=i;self.tags={'golf':kind} if kind else {}
        self.nodes=[types.SimpleNamespace(id=100*i+j,lat=y,lon=x) for j,(x,y) in enumerate(points)]
        self.nodes.append(self.nodes[0])
    def get_nodes(self,resolve_missing=False):return self.nodes

def rect(a,b,c,d):return [(a,b),(c,b),(c,d),(a,d)]
def spline(surface,points):
    return {'surface':surface,'width':0.,'isFilled':True,'waypoints':[
        {k:{'x':float(x),'y':0.,'z':float(z)} for k in ('waypoint','pointOne','pointTwo')} for x,z in points]}
def course(surface=2):
    return {'theme':12,'surfaceSplines2':[spline(surface,rect(0,0,10,10)),spline(3,rect(4,4,6,6))],
            'holes3':[],'placedObjects4':[]}
def bad_context(mixed=False):
    way=Way(1,rect(0,0,10,10))
    rel=types.SimpleNamespace(id=19701664,tags={'golf':'rough;bunker' if mixed else 'fairway','type':'multipolygon'},
                              members=[RelationWay(1,'outer' if mixed else 'inner')])
    return (types.SimpleNamespace(ways=[way],relations=[rel]),Direct(),0.,0.,{})
def tree(e,n):return (float(e),float(n),3.,8.)

def tree_stage(candidates,options,mask=None,c=None,ctx=None):
    """Execute the exact installed generate_course tree section, not a rewrite."""
    source=ast.parse((ROOT/'tgc_image_terrain.py').read_text(encoding='utf-8-sig'))
    fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='generate_course')
    start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='need_feature_filter' for t in n.targets))
    end=next(i for i,n in enumerate(fn.body[start:],start) if isinstance(n,ast.If)
             and 'lidar_trees' in ast.unparse(n.test))
    block=compile(ast.Module(body=fn.body[start:end+1],type_ignores=[]),'<installed tree stage>','exec')
    messages=[]; c=copy.deepcopy(c if c is not None else course())
    env=dict(options_dict={'lidar_trees':True,**options},course_json=c,course_version=25,
             lidar_feature_filter=features,pc=Direct(),tree_osm_context=ctx,
             lidar_tree_candidates=candidates,read_dictionary={'projection':None},
             master_grid={'min_x':0.,'min_y':0.},mask=(np.zeros((100,100,3),dtype=np.uint8) if mask is None else mask),
             image_scale=1.,GeoPointCloud=MaskGrid,get_lidar_trees=terrain.get_lidar_trees,
             obj_tag='placedObjects4',printf=messages.append)
    def records(theme,variety,trees,*args,**kwargs):
        return [{'Value':{'items':[{'position':{'x':x,'z':z},'radius':r,'height':h} for x,z,r,h in trees]}}]
    with patch.object(terrain,'get_trees',side_effect=records):exec(block,env)
    saved=[(i['position']['x'],i['position']['z']) for g in c['placedObjects4'] for i in g['Value']['items']]
    return saved,messages,c


class Tests(unittest.TestCase):
    def test_defaults(self):
        out,logs,_=tree_stage([tree(2,2),tree(20,20)],{})
        self.assertEqual(out,[(2.,2.),(20.,20.)]);self.assertTrue(any('OSM/surfaces=OFF' in s for s in logs))
    def test_red_default_on(self):
        m=np.zeros((100,100,3),np.uint8);m[20,20]=(0,0,255)
        out,_,_=tree_stage([tree(20,20)],{},m);self.assertEqual(out,[])
    def test_red_off_keeps_red(self):
        m=np.zeros((100,100,3),np.uint8);m[20,20]=(0,0,255)
        self.assertEqual(tree_stage([tree(20,20)],{'exclude_lidar_trees_red_mask':False},m)[0],[(20.,20.)])
    def test_surface_on_rejects_fairway(self):
        self.assertEqual(tree_stage([tree(2,2)],{'filter_lidar_trees_surfaces':True})[0],[])
    def test_surface_on_preserves_island(self):
        self.assertEqual(tree_stage([tree(5,5)],{'filter_lidar_trees_surfaces':True})[0],[(5.,5.)])
    def test_surface_off_preserves_all_primary_surfaces(self):
        for surface in (0,1,2):
            with self.subTest(surface=surface):self.assertEqual(tree_stage([tree(2,2)],{},c=course(surface))[0],[(2.,2.)])
    def test_surface_on_preserves_all_island_types(self):
        for surface in (0,1,2):
            with self.subTest(surface=surface):self.assertEqual(tree_stage([tree(5,5),tree(2,2)],{'filter_lidar_trees_surfaces':True},c=course(surface))[0],[(5.,5.)])
    def test_global_deny_is_diagnostic_only_when_off(self):
        out,logs,_=tree_stage([tree(2,2),tree(20,20)],{},ctx=bad_context())
        self.assertEqual(len(out),2);text='\n'.join(logs)
        self.assertIn('19701664',text);self.assertIn('incomplete outer topology',text)
        self.assertIn('Diagnostic only',text);self.assertNotIn('ALL new LiDAR trees disabled',text)
    def test_unresolved_relation_ignored_when_on(self):
        out,logs,_=tree_stage([tree(2,2),tree(20,20)],{'filter_lidar_trees_surfaces':True},ctx=bad_context())
        self.assertEqual(out,[(20.,20.)])  # Valid native fairway still rejects 2,2.
        self.assertIn('unresolved item ignored','\n'.join(logs))
        self.assertNotIn('ALL new LiDAR trees disabled','\n'.join(logs))
    def test_mixed_tag_notice_keeps_full_tag(self):
        out,logs,_=tree_stage([tree(2,2),tree(20,20)],{},ctx=bad_context(True))
        self.assertEqual(len(out),2);self.assertIn('golf=rough;bunker','\n'.join(logs))
    def test_mixed_on_skips_relation_but_retains_valid_native_exclusions(self):
        out,logs,_=tree_stage([tree(2,2),tree(20,20)],{'filter_lidar_trees_surfaces':True},ctx=bad_context(True))
        self.assertEqual(out,[(20.,20.)])
        self.assertIn('unresolved item ignored','\n'.join(logs))
    def test_broken_reader_off_never_suppresses_candidates(self):
        with patch.object(topology,'source_areas',side_effect=ValueError('example source fault')):
            out,logs,_=tree_stage([tree(20,20)],{},ctx=bad_context())
        self.assertEqual(out,[(20.,20.)]);self.assertIn('example source fault','\n'.join(logs))
    def test_disabled_filter_does_not_build_native_or_filter(self):
        with patch.object(features,'build_lidar_tree_surface_filter',side_effect=AssertionError('must not enforce')),patch.object(features,'filter_lidar_tree_candidates_by_playing_surfaces',side_effect=AssertionError('must not filter')):
            self.assertEqual(len(tree_stage([tree(2,2)],{})[0]),1)
    def test_surface_on_invokes_reviewed_filter(self):
        with patch.object(features,'filter_lidar_tree_candidates_by_playing_surfaces',wraps=features.filter_lidar_tree_candidates_by_playing_surfaces) as f:
            tree_stage([tree(2,2)],{'filter_lidar_trees_surfaces':True});self.assertEqual(f.call_count,1)
    def test_fifty_m_stays_effective_with_both_new_filters_off(self):
        out,_,_=tree_stage([tree(20,20),tree(90,90)],{'filter_lidar_trees_50m':True,'exclude_lidar_trees_red_mask':False})
        self.assertEqual(out,[(20.,20.)])
    def test_fifty_m_off_keeps_distant_in_grid_tree(self):
        self.assertEqual(tree_stage([tree(90,90)],{'filter_lidar_trees_50m':False})[0],[(90.,90.)])
    def test_eight_switch_combinations(self):
        m=np.zeros((100,100,3),np.uint8);m[20,20]=(0,0,255)
        for surface in (False,True):
            for red in (False,True):
                for proximity in (False,True):
                    opts={'filter_lidar_trees_surfaces':surface,'exclude_lidar_trees_red_mask':red,'filter_lidar_trees_50m':proximity}
                    with self.subTest(**opts):
                        out,_,_=tree_stage([tree(2,2),tree(5,5),tree(20,20),tree(90,90)],opts,m)
                        self.assertEqual(out,([] if surface else [(2.,2.)])+[(5.,5.)]+([] if red else [(20.,20.)])+([] if proximity else [(90.,90.)]))
    def test_mask_threshold_and_nonred_colors(self):
        m=np.zeros((100,100,3),np.uint8)
        colors=[(0,0,255),(0,0,130),(40,0,255),(0,40,255),(255,0,0),(0,255,0),(39,39,131)]
        for i,col in enumerate(colors):m[20,20+i]=col
        out,_,_=tree_stage([tree(20+i,20) for i in range(len(colors))],{},m)
        self.assertEqual(out,[(float(20+i),20.) for i in (1,2,3,4,5)])
    def test_mask_bounds_preserved_off(self):
        out,logs,_=tree_stage([tree(-2,2),tree(2,100),tree(20,20)],{'exclude_lidar_trees_red_mask':False})
        self.assertEqual(out,[(20.,20.)]);self.assertIn('outside saved grid=2','\n'.join(logs))
    def test_coordinates_and_dimensions_preserved(self):
        rows=[(20.1,20.2,5.1,12.3),(22.2,22.1,2.4,8.8)];captured=[]
        with patch.object(terrain,'get_trees',side_effect=lambda th,v,ts,*a,**k:captured.extend(ts) or []):
            terrain.get_lidar_trees(12,True,rows,Direct(),np.zeros((100,100,3),np.uint8),MaskGrid(),1,25,exclude_red_mask=False,printf=lambda _:None)
        self.assertEqual(captured,rows)
    def test_all_red_switch(self):
        m=np.zeros((100,100,3),np.uint8);m[:,:,2]=255
        self.assertEqual(tree_stage([tree(20,20)],{},m)[0],[])
        self.assertEqual(tree_stage([tree(20,20)],{'exclude_lidar_trees_red_mask':False},m)[0],[(20.,20.)])
    def test_mask_and_osm_not_mutated(self):
        m=np.zeros((100,100,3),np.uint8);m[20,20]=(0,0,255);before=m.copy();ctx=bad_context(True)
        tags=copy.deepcopy(ctx[0].relations[0].tags)
        tree_stage([tree(20,20)],{'exclude_lidar_trees_red_mask':False},m,ctx=ctx)
        np.testing.assert_array_equal(m,before);self.assertEqual(ctx[0].relations[0].tags,tags)
    def test_non_tree_course_fields_preserved(self):
        c=course();before=copy.deepcopy(c);_,_,after=tree_stage([tree(20,20)],{},c=c)
        for k in before:
            if k!='placedObjects4':self.assertEqual(before[k],after[k])
        self.assertEqual(c,before)
    def test_empty_input_has_settings_notice(self):
        out,logs,_=tree_stage([],{});self.assertEqual(out,[]);self.assertTrue(any('LiDAR tree filters:' in x for x in logs))
    def test_zero_osm_context_off(self):
        self.assertEqual(controls.report_osm_notices(None,printf=lambda _:None),[])
    def test_missing_option_backward_compatibility_mask(self):
        mask=np.zeros((2,2,3),np.uint8);mask[0,0]=(0,0,255)
        with patch.object(terrain,'get_trees',return_value=[]) as func:
            terrain.get_lidar_trees(12,False,[tree(.1,.1)],Direct(),mask,MaskGrid(),1,25,printf=lambda _:None)
            self.assertEqual(func.call_args.args[2],[])
    def test_required_production_options(self):
        text=(ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig')
        self.assertIn('options_entries_dict["filter_lidar_trees_surfaces"] = tk.BooleanVar(value=False)',text)
        self.assertIn('options_entries_dict["exclude_lidar_trees_red_mask"] = tk.BooleanVar(value=True)',text)
        self.assertIn('filterLidarTreesCheck.select()',text)
    def test_beta7_identity(self):
        tree=ast.parse((ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        vals={t.id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) for t in n.targets if isinstance(t,ast.Name)}
        self.assertEqual(vals['TGC_GUI_VERSION'],'v0.5.0-2k25-beta8');self.assertEqual(vals['TGC_APP_TITLE'],'TGC Designer Tools 2K25 - Beta 8')
    def test_native_overpy_notice(self):
        import overpy
        if not getattr(overpy,'__file__',None):self.skipTest('Native overpy unavailable; lab uses explicitly labelled XML adapter')
        r=overpy.Overpass().parse_xml('<osm version="0.6"><node id="1" lat="0" lon="0"/><relation id="19701664"><member type="node" ref="1" role="inner"/><tag k="golf" v="fairway"/><tag k="type" v="multipolygon"/></relation></osm>')
        logs=[];controls.report_osm_notices((r,Direct(),0,0,{}),logs.append)
        self.assertIn('19701664','\n'.join(logs))


def gui_check():
    import tkinter as tk
    original=tk.Tk.mainloop
    tk.Tk.mainloop=lambda self,*a,**k:None
    try:
        import tgc_gui as g
    finally:tk.Tk.mainloop=original
    try:
        g.root.update_idletasks()
        o=g.options_entries_dict
        assert not o['filter_lidar_trees_surfaces'].get()
        assert o['exclude_lidar_trees_red_mask'].get()
        assert o['filter_lidar_trees_50m'].get()
        g.filterLidarSurfacesCheck.invoke();assert o['filter_lidar_trees_surfaces'].get()
        assert o['filter_lidar_trees_50m'].get() and o['exclude_lidar_trees_red_mask'].get()
        g.filterLidarRedMaskCheck.invoke();assert not o['exclude_lidar_trees_red_mask'].get()
        assert o['filter_lidar_trees_surfaces'].get() and o['filter_lidar_trees_50m'].get()
        g.filterLidarSurfacesCheck.invoke();g.filterLidarRedMaskCheck.invoke()
        assert g.root.title()=='TGC Designer Tools 2K25 - Beta 8'
        assert g.filterLidarSurfacesCheck.grid_info()['row']!=g.filterLidarRedMaskCheck.grid_info()['row']
        print('Actual Tk tree controls: default states, independent toggles, 50 m retention and Beta 7 title OK.')
    finally:g.root.destroy()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if not result.wasSuccessful():sys.exit(1)
    if '--gui' in sys.argv:gui_check()
