"""Source checks, plus --live isolated Tk checks for V6 filters and presentation."""
from pathlib import Path
import ast
import copy
import sys
import unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent
LIVE='--live' in sys.argv
if LIVE:sys.argv.remove('--live')
SOURCE='--source' in sys.argv
if SOURCE:sys.argv.remove('--source')

@unittest.skipUnless(SOURCE, 'Use --source with a complete installed Beta 7 checkout')
class InstalledSourceTests(unittest.TestCase):
    def test_hooks_and_guards(self):
        ui=(ROOT/'tgc_local_alignment_ui.py').read_text(encoding='utf-8-sig')
        engine=(ROOT/'tgc_local_alignment.py').read_text(encoding='utf-8-sig')
        exporter=(ROOT/'tgc_local_alignment_export.py').read_text(encoding='utf-8-sig')
        self.assertEqual(ui.count('self._feature_filters = FeatureFilters('),1)
        self.assertIn('TGC_BETA7_ALL_FEATURES_V6_UI',ui)
        self.assertIn('from tgc_local_alignment_topology import manual_eligibility',engine)
        self.assertIn('surface-ring:',exporter)
        self.assertIn('fresh_inventory',exporter)
        for n in ('tgc_local_alignment.py','tgc_local_alignment_export.py','tgc_local_alignment_ui.py',
                  'tgc_local_alignment_topology.py','tgc_local_feature_filters.py','tgc_ui_style.py','tgc_gui.py'):
            ast.parse((ROOT/n).read_text(encoding='utf-8-sig'),feature_version=(3,11))
    def test_no_old_universal_relation_block(self):
        tree=ast.parse((ROOT/'tgc_local_alignment.py').read_text(encoding='utf-8-sig'))
        f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_manual_eligibility')
        self.assertTrue(any(isinstance(n,ast.ImportFrom) and n.module=='tgc_local_alignment_topology' for n in ast.walk(f)))
    def test_scorecard_directory_and_generic_unity(self):
        gui=(ROOT/'tgc_gui.py').read_text(encoding='utf-8-sig')
        self.assertIn('output._tgc_field_display = True',gui)
        self.assertIn('_tgc_keep_child_colors = True',gui)
        if (ROOT/'tgc_unity_presets.py').exists():
            import tgc_unity_presets
            self.assertEqual(tgc_unity_presets.PRESETS,{})


@unittest.skipUnless(LIVE,'Use --live on a machine with Tk display support')
class TkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.withdraw()
        self.errors=[]
        self.root.report_callback_exception=lambda *a:self.errors.append(a)
    def tearDown(self):
        self.root.update_idletasks()
        self.root.destroy()
        self.assertFalse(self.errors)
    def test_shared_colors_and_scorecard_entries(self):
        import tkinter as tk
        import tgc_ui_style
        c=tgc_ui_style.install(self.root)
        self.assertEqual(c.palette['panel'],'#d4d7db')
        f=tk.Frame(self.root);f._tgc_keep_child_colors=True
        pairs=[('snow','black'),('bisque','black'),('gray40','white'),('firebrick1','black'),
               ('floral white','black'),('navy','white'),('gray10','white'),('dark green','white'),('gold','black')]
        for bg,fg in pairs:
            e=tk.Entry(f,readonlybackground=bg,foreground=fg,state='readonly');e.pack()
        c.style_tree(f)
        self.assertEqual([(e.cget('readonlybackground'),e.cget('foreground')) for e in f.winfo_children()],pairs)
    def test_directory_display_is_a_bordered_field(self):
        import tkinter as tk
        import tgc_ui_style
        c=tgc_ui_style.install(self.root)
        l=tk.Label(self.root,text='E:/TGC/Course');l._tgc_field_display=True
        c.style_tree(l)
        self.assertEqual(l.cget('background'),c.palette['field'])
        self.assertEqual(l.cget('relief'),'sunken');self.assertGreaterEqual(int(l.cget('borderwidth')),1)
        self.assertEqual(l.cget('text'),'E:/TGC/Course')
    def test_filters_preserve_hidden_drafts_and_checks(self):
        owner=self.owner();f=owner.filters
        prior=copy.deepcopy(owner.manual_overrides);checks=set(owner.selected_ids)
        f.variables['fairway'].set(False);f.apply()
        self.assertEqual(owner.tree.get_children(),('b','g'))
        self.assertNotIn('f',owner.tree.selection());self.assertEqual(owner.tree.focus(),'')
        self.assertEqual(owner.manual_overrides,prior);self.assertEqual(owner.selected_ids,checks)
        self.assertTrue(owner.tree.exists('f'));self.assertIn('1 checked move(s) hidden',f.note.get())
        f.set_all(True);self.assertEqual(owner.tree.get_children(),('b','g','f'))
    def test_filters_all_none_and_reveal(self):
        owner=self.owner();f=owner.filters
        f.set_all(False);self.assertFalse(owner.tree.get_children())
        f.reveal(['g']);self.assertEqual(owner.tree.get_children(),('g',))
        self.assertEqual(owner.selected_ids,{'f'})
    def test_hidden_rows_cleared_before_reanalysis(self):
        owner=self.owner();f=owner.filters
        f.set_all(False);f.clear_rows()
        self.assertFalse(any(owner.tree.exists(s) for s in ('b','g','f')))
        for sid in ('b','g','f'):owner.tree.insert('','end',iid=sid)
        f.set_all(True);self.assertEqual(owner.tree.get_children(),('b','g','f'))
    def test_open_route_hit_has_no_closing_chord(self):
        from tgc_local_feature_filters import line_hit
        owner=SimpleNamespace(_screen=lambda x,y:(x,y))
        path=[(0,0),(100,0),(100,100)]
        self.assertIsNone(line_hit(owner,path,50,50))
        self.assertIsNotNone(line_hit(owner,path,50,1))
    def test_resize_controls_and_palette(self):
        import tgc_ui_style
        tgc_ui_style.verify()
    def owner(self):
        import tkinter as tk
        from tkinter import ttk
        from tgc_local_feature_filters import FeatureFilters
        top=tk.Toplevel(self.root);top.withdraw();outer=ttk.Frame(top);outer.pack()
        controls=ttk.Frame(outer);controls.pack()
        o=SimpleNamespace(window=top,closed=False,features={'b':dict(kind='bunker'),
                        'g':dict(kind='green'),'f':dict(kind='fairway')},
                        selected_ids={'f'},manual_overrides={'f':dict(east_m=2.,north_m=1.)},
                        _last_focus_id='f',_cancel_drag=lambda:None,_refresh_checks=lambda:None,_row_selected=lambda:None)
        o.tree=ttk.Treeview(outer,selectmode='extended');o.tree.pack()
        for sid in o.features:o.tree.insert('','end',iid=sid)
        o.tree.selection_set('f');o.tree.focus('f')
        o.filters=FeatureFilters(o,outer,before=controls);o.filters.apply()
        return o

if __name__=='__main__':unittest.main(verbosity=2)
