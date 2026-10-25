"""Resolved-only tree shapes and current-project CFS selection regression tests."""
from pathlib import Path
import ast
import copy
import importlib.util
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import lidar_tree_topology as topology
import tgc_project_paths as paths
import VERIFY_BETA6_TREE_TOPOLOGY as fixture


class Tests(unittest.TestCase):
    def test_kukio_inner_only_mixed_relation(self):
        w = fixture.Way(1570416668, fixture.rect(4, 4, 6, 6), 'tee')
        r = fixture.relation(21745952, 'rough;bunker', (w.id, 'inner'))
        sf = fixture.build(fixture.course(), fixture.source([w], [r]))
        self.assertTrue(fixture.allowed(sf, 100, 100))
        self.assertFalse(fixture.allowed(sf, 5, 5)) # independently valid tee
        self.assertFalse(sf.global_denials)
        self.assertTrue(any('21745952' in n and 'ignored' in n for n in sf.warnings))

    def test_four_inner_only_relations_do_not_veto_all(self):
        rs = [fixture.relation(i, 'fairway', (999, 'inner')) for i in
              (19701664, 19767814, 19767815, 21429491)]
        sf = fixture.build(fixture.course(), fixture.source([], rs))
        trees = [(float(i), 50., 3., 10.) for i in range(999)]
        self.assertEqual(topology.filter_candidates(trees, fixture.Direct(), sf, lambda _: None), trees)
        self.assertFalse(sf.global_denials)

    def test_resolved_triangle_not_bounding_rectangle(self):
        w = fixture.Way(1, [(0,0),(10,0),(0,10)], 'fairway')
        sf = fixture.build(fixture.course(), fixture.source([w]))
        self.assertFalse(fixture.allowed(sf, 2, 2))
        self.assertTrue(fixture.allowed(sf, 9, 9))

    def test_resolved_concave_shape_keeps_notch(self):
        w = fixture.Way(1, [(0,0),(10,0),(10,10),(7,10),(7,3),(3,3),(3,10),(0,10)], 'bunker')
        sf = fixture.build(fixture.course(), fixture.source([w]))
        self.assertTrue(fixture.allowed(sf, 5, 8))
        self.assertFalse(fixture.allowed(sf, 1, 8))

    def test_missing_inner_does_not_fill_outer(self):
        sf = fixture.build(fixture.course(), fixture.source(
            [fixture.Way(1, fixture.rect(0,0,100,100))],
            [fixture.relation(1, 'fairway', (1,'outer'), (999,'inner'))]))
        self.assertEqual(len(sf.exclusions), 0)
        self.assertTrue(fixture.allowed(sf, 50, 50))

    def test_independent_valid_way_survives_invalid_parent(self):
        w = fixture.Way(1, fixture.rect(0,0,10,10), 'green')
        sf = fixture.build(fixture.course(), fixture.source([w], [fixture.relation(1, 'green', (1,'outer'), (999,'inner'))]))
        self.assertFalse(fixture.allowed(sf, 5, 5))
        self.assertTrue(fixture.allowed(sf, 50, 50))

    def test_old_global_metadata_not_authoritative(self):
        sf = topology.SurfaceFilter({}, [], [], ('stale global fault',))
        self.assertTrue(sf.decision(5, 5)[0]);self.assertEqual(sf.global_denials, ())

    def test_zero_area_native_contour_is_skipped(self):
        def empty_contour(s, version):
            return {'contour': [(0,0),(1,0),(2,0)], 'edge_margin':0., 'bbox':(0,0,2,0)}
        c=fixture.course(fixture.spline(2, fixture.rect(0,0,10,10)))
        sf=topology.build_filter(c,25,empty_contour,lambda _:None)
        self.assertTrue(sf.decision(2,5)[0]);self.assertTrue(sf.warnings)

    def test_bad_native_builder_does_not_stop_other_shapes(self):
        def builder(s, version):
            if s.get('broken'):raise ValueError('broken test boundary')
            return fixture.f._surface_region_entry(s, version)
        broken=fixture.spline(1, fixture.rect(0,0,10,10));broken['broken']=True
        c=fixture.course(broken, fixture.spline(0, fixture.rect(20,0,30,10)))
        sf=topology.build_filter(c,25,builder,lambda _:None)
        self.assertTrue(sf.decision(5,5)[0]);self.assertFalse(sf.decision(25,5)[0])

    def test_no_fault_envelope_builder(self):
        source=(ROOT/'lidar_tree_topology.py').read_text(encoding='utf-8-sig')
        functions={n.name for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({'deny_all','envelope','quarantine'} & functions)
        self.assertNotIn('ALL new LiDAR trees disabled',source)

    def test_real_exclusions_may_legitimately_reject_all(self):
        # Never globally veto for an OSM fault is NOT a promise of a nonzero count.
        sf=fixture.build(fixture.course(fixture.spline(1, fixture.rect(0,0,10,10))))
        rows=[(2.,2.,3.,10.),(3.,3.,3.,10.)]
        self.assertEqual(topology.filter_candidates(rows, fixture.Direct(), sf, lambda _:None), [])
        self.assertEqual(sf.last_counts['rejected_green'],2)

    def test_invalid_outer_hole_relationship_is_skipped(self):
        ways=[fixture.Way(1,fixture.rect(0,0,10,10)),fixture.Way(2,fixture.rect(20,20,30,30))]
        sf=fixture.build(fixture.course(),fixture.source(ways,[fixture.relation(1,'green',(1,'outer'),(2,'inner'))]))
        self.assertTrue(fixture.allowed(sf));self.assertTrue(sf.warnings)

    def test_selected_project_wins_over_process_directory(self):
        with tempfile.TemporaryDirectory(prefix='TGC project ') as td:
            p=Path(td);(p/'heightmap.npy').touch();root=types.SimpleNamespace(filename=str(p))
            chooser=Mock(side_effect=AssertionError('must not open dialog'))
            self.assertEqual(paths.select_heightmap_folder(root,chooser,lambda _:None),str(p.resolve()))
            chooser.assert_not_called()

    def test_switch_project_a_b_a(self):
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'Hawaii A';b=Path(td)/'Other B';a.mkdir();b.mkdir()
            for p in (a,b):(p/'heightmap.npy').touch()
            root=types.SimpleNamespace(filename=str(a));chooser=Mock()
            for p in (a,b,a):
                root.filename=str(p)
                self.assertEqual(paths.select_heightmap_folder(root,chooser,lambda _:None),str(p.resolve()))
            chooser.assert_not_called()

    def test_missing_heightmap_dialog_starts_in_current_project(self):
        with tempfile.TemporaryDirectory() as td:
            current=Path(td)/'current';external=Path(td)/'selected';current.mkdir();external.mkdir()
            (external/'heightmap.npy').touch();root=types.SimpleNamespace(filename=str(current))
            chooser=Mock(return_value=str(external));logs=[]
            self.assertEqual(paths.select_heightmap_folder(root,chooser,logs.append),str(external.resolve()))
            self.assertEqual(chooser.call_args.kwargs['initialdir'],str(current.resolve()))
            self.assertTrue(any('explicitly selected' in s for s in logs))

    def test_cancel_does_not_choose_an_old_folder(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(paths.select_heightmap_folder(types.SimpleNamespace(filename=td),Mock(return_value=''),lambda _:None),'')

    def test_bad_selection_returns_notice_without_viewer(self):
        with tempfile.TemporaryDirectory() as td:
            logs=[]
            self.assertEqual(paths.select_heightmap_folder(types.SimpleNamespace(filename=td),Mock(return_value=td),logs.append),'')
            self.assertTrue(any('no heightmap.npy' in x for x in logs))

    def test_folder_selector_is_readonly(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);f=p/'heightmap.npy';f.write_bytes(b'not read by selector')
            before={x.name:x.read_bytes() for x in p.iterdir()}
            paths.select_heightmap_folder(types.SimpleNamespace(filename=td),Mock(),lambda _:None)
            self.assertEqual(before,{x.name:x.read_bytes() for x in p.iterdir()})

    def test_installed_cfs_entry_uses_current_folder(self):
        source=ast.parse((ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='openCFSAlignmentViewer')
        raw=ast.unparse(fn)
        self.assertIn('select_heightmap_folder',raw)
        self.assertNotIn('last_alignment_heightmap_dir or root.filename',raw)

    def test_folder_switch_resets_remembered_heightmap(self):
        source=ast.parse((ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='getCourseDirectory')
        with tempfile.TemporaryDirectory() as td:
            root=types.SimpleNamespace(filename='previous')
            env=dict(root=root,Path=Path,tk=types.SimpleNamespace(filedialog=types.SimpleNamespace(askdirectory=lambda **k:td)),
                     drawPlaceholder=lambda:None,tgc_tools=types.SimpleNamespace(get_course_json=lambda _:None),
                     name_entry=Mock(),last_alignment_heightmap_dir='old-project')
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'gui selection','exec'),env)
            env['getCourseDirectory'](Mock())
            self.assertEqual(root.filename,td);self.assertIsNone(env['last_alignment_heightmap_dir'])
            (Path(td)/'heightmap.npy').touch();env['getCourseDirectory'](Mock())
            self.assertEqual(env['last_alignment_heightmap_dir'],td)

    def test_rebuild_defaults_dont_reuse_old_folder(self):
        source=ast.parse((ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        for name in ('rebuildOSMMaskAction','rebuildOSMMaskFromCurrentAlignment'):
            fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertIn('select_heightmap_folder',ast.unparse(fn))
            self.assertNotIn('heightmap_dir_path or last_alignment_heightmap_dir',ast.unparse(fn))

    def test_gui_control_defaults_remain(self):
        s=(ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig')
        self.assertIn('options_entries_dict["filter_lidar_trees_surfaces"] = tk.BooleanVar(value=False)',s)
        self.assertIn('options_entries_dict["exclude_lidar_trees_red_mask"] = tk.BooleanVar(value=True)',s)
        self.assertIn('filterLidarTreesCheck.select()',s)

    def test_beta7_identity(self):
        tree=ast.parse((ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig'))
        values={t.id:n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) for t in n.targets if isinstance(t,ast.Name)}
        self.assertEqual(values['TGC_GUI_VERSION'],'v0.5.0-2k25-beta7')
        self.assertEqual(values['TGC_APP_TITLE'],'TGC Designer Tools 2K25 - Beta 7')

if __name__=='__main__':unittest.main(verbosity=2)
