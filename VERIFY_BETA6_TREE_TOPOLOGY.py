"""Topology tests independent of network, OSM parser mutation, and game UI."""
from pathlib import Path
import ast, copy, importlib.util, sys, types, unittest
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import lidar_feature_filter as f
import lidar_tree_topology as t

class Direct:
    def projToTGC(self,x,z,y):return (x,y,z)
    def latlonToTGC(self,lat,lon,dx=0,dz=0):return (float(lon)+dx,0.,float(lat)+dz)
class Way:
    def __init__(self,i,points,kind='',closed=True,ids=None):
        self.id=i;self.tags={'golf':kind} if kind else {}
        self.ns=[types.SimpleNamespace(id=(ids[j] if ids else i*100+j),lat=z,lon=x) for j,(x,z) in enumerate(points)]
        if closed:self.ns.append(self.ns[0])
    def get_nodes(self,resolve_missing=False):return self.ns
class RelationWay:
    _type_value='way'
    def __init__(self,i,role):self.ref=i;self.role=role

def rect(x0,z0,x1,z1):return [(x0,z0),(x1,z0),(x1,z1),(x0,z1)]
def spline(surface,points,width=0):
    return {'surface':surface,'width':width,'isFilled':True,'isClosed':True,
            'waypoints':[{k:{'x':float(x),'y':0.,'z':float(z)} for k in ('waypoint','pointOne','pointTwo')} for x,z in points]}
def course(*ss):return {'surfaceSplines2':list(ss)}
def relation(i,kind,*members):
    return types.SimpleNamespace(id=i,tags={'golf':kind,'type':'multipolygon'},members=[RelationWay(n,role) for n,role in members])
def source(ways,rels=(),dx=0,dz=0,options=None):
    return (types.SimpleNamespace(ways=ways,relations=list(rels)),Direct(),dx,dz,options or {})
def build(c,ctx=None):return f.build_lidar_tree_surface_filter(c,25,printf=lambda *_:None,osm_context=ctx)
def allowed(sf,x=5,z=5):return sf.decision(x,z)[0]

class Tests(unittest.TestCase):
    def test_01_green_rough_island(self):self.island(1)
    def test_02_fairway_rough_island(self):self.island(2)
    def test_03_bunker_rough_island(self):self.island(0)
    def island(self,s):
        sf=build(course(spline(s,rect(0,0,10,10)),spline(3,rect(4,4,6,6))))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,2,2))
    def test_04_green_background_rough_not_island(self):self.background(1)
    def test_05_fairway_background_rough_not_island(self):self.background(2)
    def test_06_bunker_background_rough_not_island(self):self.background(0)
    def background(self,s):
        self.assertFalse(allowed(build(course(spline(s,rect(0,0,10,10)),spline(3,rect(-2,-2,12,12))))))
    def test_07_crossing_rough_not_island(self):
        self.assertFalse(allowed(build(course(spline(2,rect(0,0,10,10)),spline(3,rect(4,4,12,6))))))
    def test_08_touching_rough_not_island(self):
        self.assertFalse(allowed(build(course(spline(2,rect(0,0,10,10)),spline(3,rect(0,4,6,6))))))
    def test_09_rough_island_edge_rejected(self):
        sf=build(course(spline(2,rect(0,0,10,10)),spline(3,rect(4,4,6,6))))
        self.assertFalse(allowed(sf,4,5))
    def test_10_other_green_inside_rough_still_rejects(self):
        sf=build(course(spline(2,rect(0,0,20,20)),spline(3,rect(3,3,15,15)),spline(1,rect(4,4,6,6))))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,10,10))
    def test_11_rough_hole_is_not_rough(self):
        ways=[Way(1,rect(0,0,10,10),'fairway'),Way(2,rect(3,3,7,7)),Way(3,rect(4,4,6,6))]
        rel=relation(100,'rough',(2,'outer'),(3,'inner'))
        sf=build(course(spline(2,rect(0,0,10,10))),source(ways,[rel]))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,3.5,3.5))
    def test_12_broad_rough_inner_fairway_not_override(self):
        ways=[Way(1,rect(0,0,10,10),'fairway'),Way(2,rect(-2,-2,12,12))]
        sf=build(course(spline(2,rect(0,0,10,10)),spline(3,rect(-2,-2,12,12))),source(ways,[relation(100,'rough',(2,'outer'),(1,'inner'))]))
        self.assertFalse(allowed(sf))
    def test_13_green_relation_rough_inner(self):self.osm_island('green')
    def test_14_bunker_relation_rough_inner(self):self.osm_island('bunker')
    def test_15_fairway_relation_rough_inner(self):self.osm_island('fairway')
    def osm_island(self,kind):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(4,4,6,6),'rough')]
        sf=build(course(),source(ways,[relation(100,kind,(1,'outer'),(2,'inner'))]))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,2,2))
    def test_16_untyped_inner_not_automatically_rough(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(4,4,6,6))]
        sf=build(course(),source(ways,[relation(100,'green',(1,'outer'),(2,'inner'))]))
        self.assertFalse(allowed(sf))
    def test_17_inner_green_remains_excluded(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(4,4,6,6),'green')]
        sf=build(course(),source(ways,[relation(100,'fairway',(1,'outer'),(2,'inner'))]))
        self.assertFalse(allowed(sf))
    def test_18_relation_tagged_rough_island(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(4,4,6,6))]
        sf=build(course(),source(ways,[relation(100,'green',(1,'outer'),(2,'inner')),relation(101,'rough',(2,'outer'))]))
        self.assertTrue(allowed(sf))
    def test_19_reversed_split_rings(self):
        a=Way(1,[(0,0),(10,0),(10,10)],closed=False,ids=[1,2,3]);b=Way(2,[(0,0),(0,10),(10,10)],closed=False,ids=[1,4,3]);c=Way(3,rect(4,4,6,6),'rough')
        sf=build(course(),source([a,b,c],[relation(100,'green',(2,'outer'),(1,'outer'),(3,'inner'))]))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,2,2))
    def test_20_incomplete_rough_cannot_permit(self):
        ways=[Way(1,rect(0,0,10,10),'green'),Way(2,rect(4,4,6,6))]
        sf=build(course(),source(ways,[relation(100,'rough',(2,'outer'),(999,'inner'))]))
        self.assertFalse(allowed(sf));self.assertTrue(sf.warnings)
    def test_21_source_green_missing_in_native_still_blocks(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10))],[relation(100,'green',(1,'outer'))]))
        self.assertFalse(allowed(sf))
    def test_22_source_same_final_offset(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10),'fairway')],dx=100,dz=200))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,105,205))
    def test_23_nonfinite_candidate_rejected(self):
        sf=build(course(spline(2,rect(0,0,10,10))))
        self.assertEqual(f.filter_lidar_tree_candidates_by_playing_surfaces([(float('nan'),5,1,10)],Direct(),sf,printf=lambda *_:None),[])
    def test_24_input_geometry_and_tree_attributes_unchanged(self):
        c=course(spline(2,rect(0,0,10,10)),spline(3,rect(4,4,6,6)));before=copy.deepcopy(c)
        trees=[(5.,5.,3.14159,12.345),(2.,2.,2.,8.)];sf=build(c)
        self.assertEqual(f.filter_lidar_tree_candidates_by_playing_surfaces(trees,Direct(),sf,printf=lambda *_:None),trees[:1]);self.assertEqual(c,before)
    def test_25_concave_parent_segment_escape(self):
        # All triangle vertices are inside, but the top edge crosses the notch.
        parent=t.Ring([(0,0),(10,0),(10,10),(7,10),(7,3),(3,3),(3,10),(0,10)])
        child=t.Ring([(1,8),(9,8),(5,1)])
        self.assertFalse(t.strictly_inside(child,parent))
    def test_26_multiple_outers(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(20,0,30,10)),Way(3,rect(4,4,6,6),'rough')]
        sf=build(course(),source(ways,[relation(100,'fairway',(1,'outer'),(2,'outer'),(3,'inner'))]))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,25,5))
    def test_27_ambiguous_relation_notices_and_blocks_item(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10))],[relation(100,'rough;bunker',(1,'outer'))]))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,20,20))
        self.assertFalse(sf.global_denials)
        self.assertTrue(any('ambiguous golf=rough;bunker' in w and 'continues' in w for w in sf.warnings))
    def test_28_width_coverage_preserved(self):
        sf=build(course(spline(2,rect(0,0,10,10),width=2)))
        self.assertFalse(allowed(sf,-.8,5));self.assertTrue(allowed(sf,-1.1,5))
    def test_29_scaling_preserves_native_island_decision(self):
        c=course(spline(2,rect(0,0,10,10)),spline(3,rect(4,4,6,6)))
        original=build(c)
        factor=1.21
        for s in c['surfaceSplines2']:
            s['width']*=factor
            for w in s['waypoints']:
                for k in ('waypoint','pointOne','pointTwo'):
                    for a in ('x','z'):w[k][a]*=factor
        scaled=build(c)
        for x,z in [(5,5),(2,2),(12,12),(4,5)]:self.assertEqual(allowed(original,x,z),allowed(scaled,x*factor,z*factor))
    def test_30_no_osm_fallback_not_global_rough_override(self):
        self.background(2)
    def test_31_primary_source_not_mutated(self):
        ways=[Way(1,rect(0,0,10,10),'fairway')];ctx=source(ways);before=copy.deepcopy(ways[0].tags)
        build(course(),ctx);self.assertEqual(ways[0].tags,before)
    def test_32_disabled_osm_surface_not_added(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10),'fairway')],options={'fairway':False}))
        self.assertTrue(allowed(sf))
    def test_33_production_context_is_connected(self):
        tree=ast.parse((ROOT/'tgc_image_terrain.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='generate_course')
        stores=[n for n in ast.walk(fn) if isinstance(n,ast.Assign) and any(isinstance(v,ast.Name) and v.id=='tree_osm_context' for v in n.targets)]
        self.assertEqual(len(stores),2)
        call=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='build_lidar_tree_surface_filter')
        self.assertTrue(any(k.arg=='osm_context' and isinstance(k.value,ast.Name) and k.value.id=='tree_osm_context' for k in call.keywords))
    def test_34_no_new_geometry_serialized(self):
        c=course(spline(2,rect(0,0,10,10)));before=copy.deepcopy(c)
        build(c,source([Way(1,rect(0,0,10,10),'fairway')]))
        self.assertEqual(c,before)

    def test_35_native_overpy_readonly_result(self):
        try: import overpy
        except ImportError: self.skipTest('native overpy unavailable in this environment')
        data = '<osm version="0.6">'+''.join('<node id="%d" lat="%s" lon="%s"/>' % (i+1,z,x) for i,(x,z) in enumerate(rect(0,0,10,10)+rect(4,4,6,6)))
        data += '<way id="1">'+''.join('<nd ref="%d"/>' % i for i in [1,2,3,4,1])+'</way>'
        data += '<way id="2">'+''.join('<nd ref="%d"/>' % i for i in [5,6,7,8,5])+'<tag k="golf" v="rough"/></way>'
        data += '<relation id="100"><member type="way" ref="1" role="outer"/><member type="way" ref="2" role="inner"/><tag k="type" v="multipolygon"/><tag k="golf" v="green"/></relation></osm>'
        result=overpy.Overpass().parse_xml(data)
        sf=build(course(),(result,Direct(),0,0,{}))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,2,2));self.assertEqual(len(result.relations),1)
    def test_36_missing_outer_suppresses_trees_not_course(self):
        sf=build(course(),source([],[relation(100,'green',(999,'outer'))]))
        self.assertTrue(sf.global_denials);self.assertFalse(allowed(sf,200,200))
        self.assertTrue(any('ALL new LiDAR trees' in w for w in sf.warnings))
    def test_37_state_only_native_surface(self):
        s=spline(1,rect(0,0,10,10));del s['isFilled'];s['state']=3
        self.assertFalse(allowed(build(course(s))))
    def test_38_inner_rough_multiple_nested_exclusions(self):
        # A tiny rough patch inside a green which is itself inside a fairway.
        sf=build(course(spline(2,rect(0,0,30,30)),spline(1,rect(2,2,12,12)),spline(3,rect(4,4,6,6))))
        self.assertTrue(allowed(sf));self.assertFalse(allowed(sf,8,8))


    def test_39_invalid_item_overrides_valid_rough_island(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(4,4,6,6),'rough')]
        sf=build(course(spline(2,rect(0,0,10,10))),source(ways,[relation(100,'rough;bunker',(1,'outer'),(2,'inner'))]))
        self.assertFalse(allowed(sf));self.assertEqual(sf.decision(5,5)[1],'ambiguous')
    def test_40_disjoint_bad_outers_do_not_block_gap(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(20,0,30,10))]
        sf=build(course(),source(ways,[relation(100,'rough;bunker',(1,'outer'),(2,'outer'))]))
        self.assertFalse(allowed(sf));self.assertFalse(allowed(sf,25,5));self.assertTrue(allowed(sf,15,5))
        self.assertEqual(len(sf.quarantine),2)
    def test_41_bad_inner_no_permission_even_outside_maintained(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10))],[relation(100,'rough',(1,'outer'),(999,'inner'))]))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,20,20));self.assertFalse(sf.global_denials)
    def test_42_mixed_tag_on_standalone_way(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10),'rough;bunker')]))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,20,20))
    def test_43_case_and_spaces_in_ambiguous_tokens(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10))],[relation(100,' Rough ; BUNKER ',(1,'outer'))]))
        self.assertFalse(allowed(sf));self.assertTrue(sf.warnings)
    def test_44_known_open_outer_uses_local_envelope(self):
        w=Way(1,[(0,0),(10,0),(10,10)],closed=False)
        sf=build(course(),source([w],[relation(100,'green',(1,'outer'))]))
        self.assertFalse(allowed(sf));self.assertFalse(allowed(sf,1,9));self.assertTrue(allowed(sf,20,20))
        self.assertFalse(sf.global_denials);self.assertTrue(any('envelope' in w for w in sf.warnings))
    def test_45_missing_second_outer_cannot_bound_whole_item(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10))],[relation(100,'rough;bunker',(1,'outer'),(999,'outer'))]))
        self.assertTrue(sf.global_denials);self.assertFalse(allowed(sf,20,20))
    def test_46_projection_error_no_stop_no_tree(self):
        class Broken(Direct):
            def latlonToTGC(self,*args):raise RuntimeError('bad projection')
        ctx=list(source([Way(1,rect(0,0,10,10),'fairway')]))
        ctx[1]=Broken();sf=build(course(),tuple(ctx))
        self.assertTrue(sf.global_denials);self.assertFalse(allowed(sf,20,20))
    def test_47_global_deny_overrides_good_islands(self):
        sf=build(course(spline(1,rect(0,0,10,10)),spline(3,rect(4,4,6,6))),source([],[relation(100,'green',(999,'outer'))]))
        self.assertFalse(allowed(sf))
    def test_48_ambiguous_source_is_not_changed(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(4,4,6,6),'rough')]
        rel=relation(100,'rough;bunker',(1,'outer'),(2,'inner'));ctx=source(ways,[rel])
        before=(copy.deepcopy(rel.tags),[(m.ref,m.role) for m in rel.members],[(w.id,copy.deepcopy(w.tags),[(n.id,n.lat,n.lon) for n in w.ns]) for w in ways])
        build(course(),ctx)
        after=(rel.tags,[(m.ref,m.role) for m in rel.members],[(w.id,w.tags,[(n.id,n.lat,n.lon) for n in w.ns]) for w in ways])
        self.assertEqual(before,after)
    def test_49_incompatible_filter_returns_no_trees(self):
        logs=[]
        self.assertEqual(t.filter_candidates([(20,20,1,10)],Direct(),{},logs.append),[])
        self.assertTrue(any('NOTICE' in line and 'continues' in line for line in logs))
    def test_50_notice_includes_object_and_continuation(self):
        logs=[];ctx=source([Way(1,rect(0,0,10,10))],[relation(21751752,'rough;bunker',(1,'outer'))])
        sf=f.build_lidar_tree_surface_filter(course(),25,printf=logs.append,osm_context=ctx)
        msg='\n'.join(logs)
        self.assertIn('NOTICE',msg);self.assertIn('21751752',msg);self.assertIn('rough;bunker',msg);self.assertIn('continues',msg)
    def test_51_rejection_count_and_unaffected_trees(self):
        sf=build(course(),source([Way(1,rect(0,0,10,10))],[relation(100,'rough;bunker',(1,'outer'))]))
        trees=[(5,5,1,10),(20,20,2,11)]
        kept=t.filter_candidates(trees,Direct(),sf,lambda *_:None)
        self.assertEqual(kept,trees[1:]);self.assertEqual(sf.last_counts['rejected_ambiguous'],1)
    def test_52_self_crossing_rough_gets_conservative_box(self):
        w=Way(1,[(0,0),(10,10),(0,10),(10,0)],'rough')
        sf=build(course(),source([w]))
        self.assertFalse(allowed(sf,2,5));self.assertTrue(allowed(sf,20,20));self.assertFalse(sf.global_denials)
    def test_53_untagged_relation_conflicting_outer_tags(self):
        ways=[Way(1,rect(0,0,10,10),'rough'),Way(2,rect(20,0,30,10),'bunker')]
        sf=build(course(),source(ways,[relation(100,'',(1,'outer'),(2,'outer'))]))
        self.assertFalse(allowed(sf));self.assertFalse(allowed(sf,25,5));self.assertTrue(allowed(sf,15,5))
    def test_54_invalid_inner_geometry_quarantines_outer(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,[(4,4),(4,5),(4,6)])]
        sf=build(course(),source(ways,[relation(100,'rough',(1,'outer'),(2,'inner'))]))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,20,20))
    def test_55_missing_way_nodes_unbounded(self):
        w=Way(1,rect(0,0,10,10),'fairway')
        def missing(**kw):raise RuntimeError('missing node')
        w.get_nodes=missing;sf=build(course(),source([w]))
        self.assertTrue(sf.global_denials);self.assertFalse(allowed(sf,20,20))
    def test_56_invalid_context_still_returns_safe_filter(self):
        sf=build(course(),('incomplete context',))
        self.assertTrue(sf.global_denials);self.assertFalse(allowed(sf,20,20))
    def test_57_unrelated_healthy_island_still_works(self):
        ways=[Way(1,rect(0,0,10,10)),Way(2,rect(20,0,30,10),'green'),Way(3,rect(24,4,26,6),'rough')]
        sf=build(course(),source(ways,[relation(100,'rough;bunker',(1,'outer'))]))
        self.assertFalse(allowed(sf));self.assertTrue(allowed(sf,25,5));self.assertFalse(allowed(sf,22,2))
    def test_58_healthy_empty_osm_remains_permissive(self):
        sf=build(course(),source([]));self.assertTrue(allowed(sf));self.assertFalse(sf.warnings)
    def test_59_unrelated_nongolf_relation_not_error(self):
        rel=relation(100,'forest',(999,'outer'));sf=build(course(),source([],[rel]))
        self.assertTrue(allowed(sf));self.assertFalse(sf.warnings)
    def test_60_ambiguous_nonfinite_outer_no_exception(self):
        w=Way(1,rect(0,0,10,10));w.ns[1].lon=float('nan')
        sf=build(course(),source([w],[relation(100,'rough;bunker',(1,'outer'))]))
        self.assertTrue(sf.global_denials);self.assertFalse(allowed(sf,20,20))

if __name__=='__main__':unittest.main(verbosity=2)
