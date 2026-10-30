"""Focused V7 checks: real Tk events against installed method bodies.

--ui PATH selects a source for the isolated method harness.
--installed also runs the actual signed analysis/manual-export path.
No user project data is read or written. Modal responses are explicitly mocked.
The six RealDialogTests instantiate the supplied full dialog and real filters,
using analytical signed review fixtures and the actual manual validator/exporter.
The terrain-fit detector is not mocked or exercised: proposals are test inputs.
This is not a complete main application, Windows or in-game rendering test.
Installer-fix revision: include the filter refresh_note callback in method fixtures.
"""
from pathlib import Path
import argparse, ast, copy, hashlib, json, math, os, sys, tempfile, unittest
from types import SimpleNamespace
import numpy as np
import pyproj
import xml.etree.ElementTree as ET
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk, messagebox

parser = argparse.ArgumentParser()
parser.add_argument('--ui', type=Path, default=Path(__file__).resolve().parent/'tgc_local_alignment_ui.py')
parser.add_argument('--installed', action='store_true')
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0]] + remaining
ROOT = Path(__file__).resolve().parent

NAMES = ['_v7_review_rows','_v7_linked_rows','_v7_feedback','_v7_plan_approval','_v7_set_checked',
         'revert_manual_to_suggested','_check_rows','_tree_pressed','_toggle_row','_check_column',
         '_v7_move_only_focused','_effective_offset','_effective_points','_is_checkable',
         '_sync_manual_fields','_manual_entries_changed','_movement_ids','_group_offsets',
         '_remember_manual_group','_commit_manual_group','undo_manual_move','_cancel_drag',
         '_select_canvas_feature','_refresh_checks','_row_selected','_show_feature_details','_label']

def method_class(path):
    source = path.read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    classes = [c for c in tree.body if isinstance(c, ast.ClassDef)
               and any(isinstance(n,ast.FunctionDef) and n.name=='_v7_set_checked' for n in c.body)]
    if len(classes)!=1: raise ValueError('Expected one V7 editor class in '+str(path))
    methods = {n.name:n for n in classes[0].body if isinstance(n,ast.FunctionDef)}
    if set(NAMES)-methods.keys(): raise ValueError('Missing methods: '+str(set(NAMES)-methods.keys()))
    selected = ast.ClassDef(name='ActualMethods',bases=[],keywords=[],body=[copy.deepcopy(methods[n]) for n in NAMES],decorator_list=[])
    m=ast.Module(body=[selected],type_ignores=[]); ast.fix_missing_locations(m)
    ns=dict(math=math,tk=tk,ttk=ttk,messagebox=messagebox,_display_text=lambda x:str(x))
    exec(compile(m,str(path),'exec'),ns)
    return ns['ActualMethods']

class SourceChecks(unittest.TestCase):
    def test_v7_methods_and_python311_syntax(self):
        source=args.ui.read_text(encoding='utf-8-sig')
        ast.parse(source,feature_version=(3,11)); self.assertTrue(method_class(args.ui))
        self.assertIn('TGC_BETA7_LOCAL_ACCEPT_V7',source)
    def test_uses_existing_validators_not_confidence_override(self):
        tree=ast.parse(args.ui.read_text(encoding='utf-8-sig'))
        f=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_v7_set_checked')
        calls=[n.func.attr for n in ast.walk(f) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertIn('validate_manual_offsets',calls);self.assertIn('_commit_manual_group',calls)
        self.assertFalse(any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.slice,ast.Constant)
            and t.slice.value in ('movable','manual_movable','report_sha256') for t in n.targets) for n in ast.walk(f)))

HAS_DISPLAY=os.name=='nt' or bool(os.environ.get('DISPLAY'))

@unittest.skipUnless(HAS_DISPLAY,'No Tk display; run on Windows or under Xvfb')
class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('780x320+10000+10000')
        self.callback_errors=[]
        self.root.report_callback_exception=lambda *a:self.callback_errors.append(a)
        self.messages=[];self.answer=True
        self.mocks=[patch.object(messagebox,'showinfo',side_effect=lambda *a,**k:self.messages.append(('info',a))),
                    patch.object(messagebox,'showerror',side_effect=lambda *a,**k:self.messages.append(('error',a))),
                    patch.object(messagebox,'askyesno',side_effect=self.ask)]
        for m in self.mocks:m.start()
        self.o=method_class(args.ui)();o=self.o;o.window=self.root
        o.tree=ttk.Treeview(self.root,columns=('kind','id','east','north','status'),selectmode='extended')
        o.tree.column('#0',width=45,stretch=False);o.tree.pack(fill='both',expand=True)
        o.operation=None;o.closed=False;o.report={'sentinel':'original report'};o.selected_ids=set()
        o.manual_overrides={};o._pending_entries={};o.manual_history=[];o._drag_state=None;o._pointer_action=None
        o._selection_row_hint=None;o._clicked_focused_row=False;o._last_focus_id=None;o._syncing_manual_fields=False
        o.link_holes_var=tk.BooleanVar(self.root,value=False);o.move_mode_var=tk.BooleanVar(self.root,value=False)
        o.status_var=tk.StringVar(self.root);o.detail_var=tk.StringVar(self.root)
        o.manual_east_var=tk.StringVar(self.root);o.manual_north_var=tk.StringVar(self.root)
        def feature(kind,east,north,movable=False,manual_only=False):
            return dict(kind=kind,label=kind.title(),proposed_east_m=east,proposed_north_m=north,
                movable=movable,manual_movable=True,manual_only=manual_only,
                status='review_candidate' if movable else ('manual_only' if manual_only else 'insufficient_evidence'),
                reasons=['best_match_at_search_boundary'],linked_ids=[],related_ids=[],
                fit_coords_m=[[10,10],[12,10],[12,12],[10,10]],geometry_valid=True,visible=True)
        o.features={'101':feature('tee',3.,-2.5),'102':feature('bunker',1.,.5,True),
                    '103':feature('tee',0.,0.),'surface-way:104':feature('green',0.,0.,manual_only=True),
                    'rough-ring:303:inner:0':feature('rough',0.,0.,manual_only=True)}
        for sid,f in o.features.items():o.tree.insert('','end',iid=sid,text='[ ]')
        o.tree.selection_set('101');o.tree.focus('101')
        o._feature_visible=lambda f:f.get('visible',True)
        o._queue_redraw=lambda:None;o._set_controls=lambda:None
        self.zooms=0
        def zoom():self.zooms+=1
        o.zoom_to_feature=zoom
        o._feature_filters=SimpleNamespace(reveal=lambda ids:None, refresh_note=lambda:None)
        self.validated=[]
        def validate(report,offsets):
            if report is not o.report:raise ValueError('Stale report')
            self.validated.append(copy.deepcopy(offsets))
            for sid,value in offsets.items():
                if not o.features[sid].get('manual_movable'):raise ValueError('Invalid boundary')
                if not all(math.isfinite(float(v)) for v in value.values()):raise ValueError('Nonfinite offset')
                if any(abs(v)>200 for v in value.values()):raise ValueError('Outside terrain')
            return copy.deepcopy(offsets)
        o._backend=lambda:SimpleNamespace(validate_manual_offsets=validate)
        o.tree.bind('<<TreeviewSelect>>',o._row_selected)
        o.tree.bind('<ButtonPress-1>',o._tree_pressed)
        o.tree.bind('<Double-1>',o._toggle_row)
        o.tree.bind('<space>',o._toggle_row)
        o.tree.bind('<ButtonRelease-1>',o._check_column)
        self.root.update();o._refresh_checks();self.root.update()
    def tearDown(self):
        for m in reversed(self.mocks):m.stop()
        self.root.destroy();self.assertFalse(self.callback_errors)
    def ask(self,*a,**kw):self.messages.append(('ask',a));return self.answer
    def state(self):return copy.deepcopy((self.o.manual_overrides,self.o.selected_ids,self.o.manual_history,self.o.report))
    def select(self,*rows):self.o.tree.selection_set(rows);self.o.tree.focus(rows[0]);self.root.update()
    def click(self,sid='101',x=16,count=1):
        box=self.o.tree.bbox(sid); y=box[1]+box[3]//2
        for _ in range(count):
            self.o.tree.event_generate('<ButtonPress-1>',x=x,y=y);self.root.update()
            self.o.tree.event_generate('<ButtonRelease-1>',x=x,y=y);self.root.update()
    def test_original_screenshot_weak_suggestion_accepts(self):
        report=copy.deepcopy(self.o.report)
        self.assertTrue(self.o.revert_manual_to_suggested())
        self.assertEqual(self.o.selected_ids,{'101'})
        self.assertEqual(self.o.manual_overrides['101'],dict(east_m=3.,north_m=-2.5))
        self.assertEqual(self.o.tree.item('101','text'),'[x]')
        self.assertEqual(self.o.report,report);self.assertTrue(any(m[0]=='ask' for m in self.messages))
    def test_declined_weak_suggestion_changes_nothing(self):
        self.answer=False;before=self.state();self.assertFalse(self.o.revert_manual_to_suggested());self.assertEqual(self.state(),before)
    def test_high_confidence_acceptance_needs_no_confirmation(self):
        self.select('102');self.assertTrue(self.o.revert_manual_to_suggested());self.assertIn('102',self.o.selected_ids)
        self.assertFalse(any(m[0]=='ask' for m in self.messages))
    def test_check_selected_accepts_weak_after_confirmation(self):
        self.o._check_rows(True);self.assertEqual(self.o.selected_ids,{'101'})
    def test_single_check_column_click_accepts_once(self):
        self.click();self.assertEqual(self.o.selected_ids,{'101'});self.assertEqual(len(self.o.manual_history),1)
    def test_double_check_column_click_does_not_cancel(self):
        self.click(count=2);self.assertEqual(self.o.selected_ids,{'101'});self.assertEqual(len(self.o.manual_history),1)
    def test_single_body_click_selects_without_approval(self):
        self.click('102',x=80);self.assertEqual(self.o.tree.focus(),'102');self.assertFalse(self.o.selected_ids)
    def test_double_body_click_accepts_once(self):
        self.click(x=80,count=2);self.assertEqual(self.o.selected_ids,{'101'});self.assertEqual(len(self.o.manual_history),1)
    def test_keyboard_space_group_accepts_and_unchecks(self):
        self.select('101','102');self.o._toggle_row(SimpleNamespace(num='??'))
        self.assertEqual(self.o.selected_ids,{'101','102'});self.o._toggle_row();self.assertFalse(self.o.selected_ids)
    def test_group_accept_one_undo_restores(self):
        self.select('101','102');self.o.revert_manual_to_suggested();self.assertEqual(len(self.o.manual_history),1)
        self.o.undo_manual_move();self.assertFalse(self.o.manual_overrides);self.assertFalse(self.o.selected_ids)
    def test_repeat_accept_is_idempotent(self):
        self.o.revert_manual_to_suggested();before=self.state();self.o.revert_manual_to_suggested();self.assertEqual(self.state(),before)
    def test_manual_draft_check_preserves_position(self):
        self.o.manual_overrides['101']=dict(east_m=9.,north_m=8.);self.o._check_rows(True)
        self.assertEqual(self.o.manual_overrides['101'],dict(east_m=9.,north_m=8.));self.assertFalse(any(m[0]=='ask' for m in self.messages))
    def test_accept_resets_manual_to_suggestion_and_checks(self):
        self.o.manual_overrides['101']=dict(east_m=9.,north_m=8.);self.o.revert_manual_to_suggested()
        self.assertEqual(self.o.manual_overrides['101'],dict(east_m=3.,north_m=-2.5));self.assertIn('101',self.o.selected_ids)
        self.o.undo_manual_move();self.assertEqual(self.o.manual_overrides['101'],dict(east_m=9.,north_m=8.));self.assertNotIn('101',self.o.selected_ids)
    def test_linked_hidden_cutout_follows_once(self):
        h='rough-ring:303:inner:0';self.o.features['101']['linked_ids']=[h];self.o.features[h]['linked_ids']=['101']
        self.o.features[h]['visible']=False;self.o.link_holes_var.set(True)
        self.o.revert_manual_to_suggested();self.assertEqual(self.o.selected_ids,{'101',h})
        self.assertEqual(self.o.manual_overrides[h],self.o.manual_overrides['101']);self.assertIn('1 linked hidden',self.o.status_var.get())
    def test_link_off_does_not_move_cutout(self):
        h='rough-ring:303:inner:0';self.o.features['101']['linked_ids']=[h]
        self.o.revert_manual_to_suggested();self.assertNotIn(h,self.o.manual_overrides)
    def test_conflicting_linked_proposals_rejected_atomically(self):
        self.o.features['101']['linked_ids']=['102'];self.o.features['102']['linked_ids']=['101'];self.o.link_holes_var.set(True)
        self.select('101','102');before=self.state();self.assertFalse(self.o.revert_manual_to_suggested());self.assertEqual(self.state(),before)
        self.assertTrue(any(m[0]=='error' for m in self.messages))
    def test_zero_suggestion_explained_not_invented(self):
        self.select('103');before=self.state();self.assertFalse(self.o.revert_manual_to_suggested());self.assertEqual(self.state(),before)
        self.assertIn('no nonzero move',self.o.status_var.get())
    def test_manual_only_surface_accept_does_not_clear_draft(self):
        g='surface-way:104';self.select(g);self.o.manual_overrides[g]=dict(east_m=2.,north_m=1.)
        before=self.state();self.assertFalse(self.o.revert_manual_to_suggested());self.assertEqual(self.state(),before)
        self.assertTrue(self.o._check_rows(True));self.assertIn(g,self.o.selected_ids)
    def test_pending_entries_are_not_lost(self):
        self.o._pending_entries['101']=('12','7');before=self.state()
        self.assertFalse(self.o.revert_manual_to_suggested());self.assertEqual(self.state(),before)
        self.assertEqual(self.o._pending_entries['101'],('12','7'))
    def test_invalid_geometry_rejected_without_override(self):
        self.o.features['101']['manual_movable']=False;before=self.state()
        self.assertFalse(self.o._check_rows(True));self.assertEqual(self.state(),before)
    def test_nonfinite_proposal_rejected(self):
        self.o.features['101']['proposed_east_m']=float('nan');before=self.state()
        self.assertFalse(self.o._check_rows(True));self.assertFalse(self.o.manual_overrides)
    def test_bounds_rejection_uses_existing_validator(self):
        self.o.features['101']['proposed_east_m']=300.;before=self.state()
        self.assertFalse(self.o._check_rows(True));self.assertEqual(self.state(),before)
    def test_busy_ui_never_accepts(self):
        self.o.operation='analyze';before=self.state();self.assertFalse(self.o.revert_manual_to_suggested());self.assertEqual(self.state(),before)
    def test_changed_report_during_confirmation_is_rejected(self):
        with patch.object(messagebox,'askyesno',side_effect=lambda *a,**k:(setattr(self.o,'report',{}) or True)):
            self.assertFalse(self.o.revert_manual_to_suggested())
        self.assertFalse(self.o.manual_overrides);self.assertFalse(self.o.selected_ids)
    def test_uncheck_preserves_preview_and_undo(self):
        self.o.revert_manual_to_suggested();self.o._check_rows(False);self.assertFalse(self.o.selected_ids)
        self.assertTrue(self.o.manual_overrides);self.o.undo_manual_move();self.assertIn('101',self.o.selected_ids)
    def test_hidden_selection_is_not_approved(self):
        self.select('101','102');self.o.features['102']['visible']=False;self.o._check_rows(True)
        self.assertEqual(self.o.selected_ids,{'101'})
    def test_release_on_other_row_is_not_a_click(self):
        a=self.o.tree.bbox('101');b=self.o.tree.bbox('102')
        self.o.tree.event_generate('<ButtonPress-1>',x=16,y=a[1]+a[3]//2);self.root.update()
        self.o.tree.event_generate('<ButtonRelease-1>',x=16,y=b[1]+b[3]//2);self.root.update()
        self.assertFalse(self.o.selected_ids)
    def test_body_click_keeps_ctrl_multiselection(self):
        self.click('101',x=80);box=self.o.tree.bbox('102');y=box[1]+box[3]//2
        self.o.tree.event_generate('<ButtonPress-1>',x=80,y=y,state=4);self.root.update()
        self.o.tree.event_generate('<ButtonRelease-1>',x=80,y=y,state=4);self.root.update()
        self.assertEqual(set(self.o.tree.selection()),{'101','102'});self.assertFalse(self.o.selected_ids)
    def test_independent_action_selects_only_focus_disables_linking(self):
        self.select('101','102');self.o.link_holes_var.set(True);self.o.features['101']['linked_ids']=['rough-ring:303:inner:0']
        self.assertTrue(self.o._v7_move_only_focused());self.assertEqual(self.o._movement_ids(),{'101'})
        self.assertTrue(self.o.move_mode_var.get());self.assertFalse(self.o.link_holes_var.get())
    def test_independent_action_keeps_prior_other_drafts_and_checks(self):
        self.o.manual_overrides['102']=dict(east_m=1.,north_m=1.);self.o.selected_ids.add('102')
        self.o._v7_move_only_focused();self.assertIn('102',self.o.manual_overrides);self.assertIn('102',self.o.selected_ids)
        self.assertIn('1 other previously checked',self.o.status_var.get())
    def test_independent_cutout_identity_not_silently_switched(self):
        h='rough-ring:303:inner:0';self.o.features[h]['boundary_role']='inner';self.select(h)
        self.o._v7_move_only_focused();self.assertEqual(self.o._movement_ids(),{h});self.assertIn('cutout, not the filled object',self.o.status_var.get())
    def test_independent_invalid_geometry_still_blocked(self):
        self.o.features['101']['manual_movable']=False;self.assertFalse(self.o._v7_move_only_focused())
        self.assertFalse(self.o.move_mode_var.get())

@unittest.skipUnless(args.installed and HAS_DISPLAY,'--installed and a Tk display required')
class InstalledExportTests(AcceptanceTests):
    # This subclass intentionally only contributes its two integration tests.
    pass

# Avoid inheriting the focused tests a second time in installed class.
for _name in [n for n in dir(InstalledExportTests) if n.startswith('test_')]:
    setattr(InstalledExportTests,_name,None)

def _test_signed_independent_export(self):
    import tgc_local_alignment as engine
    import numpy as np
    import xml.etree.ElementTree as ET
    raw,grid,proj,data=fixture('rough','tee')
    with tempfile.TemporaryDirectory(prefix='tgc-local-v7-') as temp:
        source=Path(temp)/'source.osm';source.write_bytes(raw)
        report=analytical_review(data,source,(1.5,-.5))
        by={str(f.get('selection_id',f['way_id'])):f for f in report['features']}
        feature=by['101'];feature.update(status='insufficient_evidence',movable=False,manual_only=False,
                                       proposed_east_m=3.,proposed_north_m=-2.5)
        report['report_sha256']=engine._report_digest(report)
        o=self.o;o.report=report;o.features=by
        o.tree.delete(*o.tree.get_children())
        for sid in by:o.tree.insert('','end',iid=sid,text='[ ]')
        o.tree.selection_set('101');o.tree.focus('101');o._backend=lambda:engine
        o._v7_move_only_focused();self.assertTrue(o.revert_manual_to_suggested())
        self.assertEqual(o.selected_ids,{'101'})
        output=Path(temp)/'saved.osm'
        engine.apply_reviewed(report,sorted(o.selected_ids),output,current_data=data,
            current_nudge=(1.5,-.5),current_osm_file=source,manual_overrides=o.manual_overrides)
        self.assertEqual(source.read_bytes(),raw)
        np.testing.assert_allclose(xy(output.read_bytes(),101,proj,grid)-xy(raw,101,proj,grid),np.tile((3,-2.5),(5,1)),atol=1e-5)
        root=ET.fromstring(output.read_bytes());cutout=root.find('relation').findall('member')[1].get('ref')
        self.assertNotEqual(cutout,'101')
        np.testing.assert_allclose(xy(output.read_bytes(),cutout,proj,grid),xy(raw,101,proj,grid),atol=1e-5)
        np.testing.assert_allclose(xy(output.read_bytes(),100,proj,grid),xy(raw,100,proj,grid),atol=1e-5)
        np.testing.assert_allclose(xy(output.read_bytes(),200,proj,grid),xy(raw,200,proj,grid),atol=1e-5)
        self.assertTrue(engine._inventory(output.read_bytes(),grid,proj,('tee','bunker'))[0])
        self.assertTrue(engine._lineage(output,hashlib.sha256(output.read_bytes()).hexdigest()))
InstalledExportTests.test_signed_independent_export=_test_signed_independent_export

def fixture(kind='fairway', inner_kind='green', fragmented=False):
    from tgc_cfs_display import importer_transformer
    p = pyproj.Proj('EPSG:32611')
    tr = importer_transformer(p)
    grid = dict(version=1, rows=128, cols=128, resolution=2., min_x=575641., min_y=5497180.,
                max_x=575897., max_y=5497436., crs_wkt=p.crs.to_wkt(), horizontal_epsg=32611,
                origin_semantics='southwest_cell_edge', row_order='south_up_internal', xy_units='meters')
    lon,lat = tr.transform(grid['min_x'],grid['min_y'],direction='INVERSE')
    grid['lower_left_latlon']=[lat,lon]
    data=dict(heightmap=np.full((128,128),100.),projection=p,master_grid=grid,image_scale=2.,origin=(lat,lon))
    root=ET.Element('osm',version='0.6',upload='never')
    cache={};next_id=1
    def way(wid, xy, tags):
        nonlocal next_id
        refs=[]
        for x,y in xy:
            if (x,y) not in cache:
                lo,la=tr.transform(grid['min_x']+x,grid['min_y']+y,direction='INVERSE')
                cache[x,y]=str(next_id);next_id+=1
                ET.SubElement(root,'node',id=cache[x,y],lon='%.12f'%lo,lat='%.12f'%la)
            refs.append(cache[x,y])
        w=ET.SubElement(root,'way',id=str(wid),version='7')
        for ref in refs:ET.SubElement(w,'nd',ref=ref)
        for k,v in tags.items():ET.SubElement(w,'tag',k=k,v=v)
        return w
    rect=lambda x,y,w,h:[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]
    if fragmented:
        way(100,[(20,20),(200,20),(200,200)],{})
        way(103,[(20,20),(20,200),(200,200)],{})
    else:way(100,rect(20,20,180,180),{})
    way(101,rect(50,50,20,20),{'golf':inner_kind,'name':'Keep identity'})
    way(102,rect(140,50,20,20),{})
    # Unselected shared-node direct surface must remain at its original coordinates.
    way(200,[(50,50),(45,50),(45,45),(50,50)],{'golf':'rough'})
    way(201,[(210,30),(225,45),(230,70)],{'golf':'cartpath'})
    way(202,rect(210,100,12,12),{'golf':'mulch','surface':'mulch'})
    rel=ET.SubElement(root,'relation',id='303',version='9')
    for wid,role in [(100,'outer')]+([(103,'outer')] if fragmented else [])+[(101,'inner'),(102,'inner')]:
        ET.SubElement(rel,'member',type='way',ref=str(wid),role=role)
    for k,v in {'type':'multipolygon','golf':kind}.items():ET.SubElement(rel,'tag',k=k,v=v)
    raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    return raw,grid,p,data

def xy(raw,wid,p,grid):
    from tgc_cfs_display import importer_transformer
    root=ET.fromstring(raw);nodes={n.get('id'):n for n in root.findall('node')};w=root.find("way[@id='%s']"%wid)
    tr=importer_transformer(p)
    return np.array([tr.transform(float(nodes[n.get('ref')].get('lon')),float(nodes[n.get('ref')].get('lat')))
                     for n in w.findall('nd')])-[grid['min_x'],grid['min_y']]

def analytical_review(data, source, nudge=(1.5,-.5), proposals=None):
    """Fixture report from real inventory/signatures. Proposals are test inputs,
    not claims about the detector. Export revalidates fresh source independently.
    """
    import tgc_local_alignment as engine
    from collections import Counter
    raw=source.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
    _,grid,proj=engine._data_contract(data)
    inventory,counts=engine._inventory(raw,grid,proj,('tee','bunker'))
    lineage=engine._lineage(source,sha)
    features=[]
    for original in inventory:
        f=copy.deepcopy(original)
        points=np.asarray(f.get('coords_m',[]),dtype=float)
        f['fit_coords_m']=(points+np.asarray(nudge)).tolist() if points.size else []
        f['proposed_east_m'],f['proposed_north_m']=(proposals or {}).get(f['selection_id'],(0.,0.))
        f['proposed_coords_m']=(np.asarray(f['fit_coords_m'])+[f['proposed_east_m'],f['proposed_north_m']]).tolist() if points.size else []
        f['global_nudge_m']=list(nudge)
        f['manual_movable'],f['manual_reason']=engine._manual_eligibility(original)
        f['movable']=False;f['status']='insufficient_evidence' if f['kind'] in ('tee','bunker') else 'manual_only'
        f['reasons']=[];f['accepted_by_default']=False
        features.append(f)
    signature=dict(engine.terrain_signature(data),input_osm_sha256=sha,global_nudge_m=list(nudge))
    report=dict(schema_version=engine.REPORT_SCHEMA_VERSION,feature_version=engine.FEATURE_VERSION,
                source_osm_path=str(source.resolve()),input_osm_sha256=sha,
                original_source_osm_path=lineage['original_source_osm_path'],
                original_source_path=lineage['original_source_osm_path'],
                original_input_osm_sha256=lineage['original_input_osm_sha256'],
                original_source_osm_sha256=lineage['original_input_osm_sha256'],
                lineage=lineage,signature=signature,grid=grid,global_nudge_m=list(nudge),
                config={'search_radius_m':4.},kinds=['tee','bunker'],inventory=inventory,
                features=features,summary={'counts':dict(Counter(f['status'] for f in features))})
    report['report_sha256']=engine._report_digest(report)
    return report

@unittest.skipUnless(args.installed and HAS_DISPLAY, '--installed and a Tk display required')
class RealDialogTests(unittest.TestCase):
    def setUp(self):
        global engine, LocalAlignmentDialog
        import tgc_local_alignment as engine
        from tgc_local_alignment_ui import LocalAlignmentDialog
        self.tmp=tempfile.TemporaryDirectory(prefix='tgc-v7-real-dialog-')
        self.root=tk.Tk(); self.root.geometry('900x700+0+0')
        self.errors=[];self.messages=[]
        self.root.report_callback_exception=lambda *exc:self.errors.append(exc)
        self.mocks=[patch('tkinter.messagebox.showerror',side_effect=lambda *a,**kw:self.messages.append(a)),
                    patch('tkinter.messagebox.showinfo',side_effect=lambda *a,**kw:self.messages.append(a)),
                    patch('tkinter.messagebox.askyesno',return_value=True)]
        for m in self.mocks:m.start()
        self.dialog=None
    def tearDown(self):
        if self.dialog is not None:self.dialog._finish()
        self.root.update_idletasks();self.root.destroy()
        for m in reversed(self.mocks):m.stop()
        self.tmp.cleanup()
        self.assertFalse(self.errors,self.errors)
    def open_case(self,kind='tee',bad_member=None):
        raw,self.grid,self.proj,self.data=fixture('rough',kind)
        if bad_member:
            root=ET.fromstring(raw)
            ET.SubElement(root.find('relation'),'member',type=bad_member,ref='999999',role='inner')
            raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        self.raw=raw;self.source=Path(self.tmp.name)/'source.osm';self.source.write_bytes(raw)
        self.nudge=(1.5,-.5)
        self.report=analytical_review(self.data,self.source,self.nudge,{'101':(3.,-2.5)})
        viewer=SimpleNamespace(window=self.root,osm_file=str(self.source),data=self.data,grid=self.grid,
            resolution=2.,rows=128,cols=128,backgrounds={'Hillshade':np.full((128,128,3),145,dtype=np.uint8)},
            features=[],shift_ew=self.nudge[0],shift_ns=self.nudge[1],
            brightness_var=tk.DoubleVar(self.root,value=1.),contrast_var=tk.DoubleVar(self.root,value=1.),
            ready=True,busy=False,closed=False,_set_controls_enabled=lambda enabled:None)
        self.dialog=LocalAlignmentDialog(viewer,engine=engine)
        # No auto-fit detector needed: load an explicitly constructed analytical review.
        self.dialog.window.after_cancel(self.dialog._start_id);self.dialog._start_id=None
        self.dialog._analysis_done(self.report)
        self.root.update()
        return self.dialog
    def focus(self,sid):
        d=self.dialog; d.tree.selection_set(sid);d.tree.focus(sid);d._row_selected();self.root.update()
    def export(self,name='out.osm'):
        d=self.dialog;out=Path(self.tmp.name)/name
        summary=engine.apply_reviewed(d.report,sorted(d.selected_ids),out,current_data=self.data,
            current_nudge=self.nudge,current_osm_file=self.source,
            manual_overrides={sid:d.manual_overrides[sid] for sid in d.selected_ids if sid in d.manual_overrides})
        self.assertEqual(self.source.read_bytes(),self.raw)
        record=json.loads(engine.manifest_path(out).read_text())
        self.assertEqual(record['output_osm_sha256'],hashlib.sha256(out.read_bytes()).hexdigest())
        return out,summary
    def test_real_filter_refresh_after_accept_and_undo(self):
        d=self.open_case();self.focus('101');d.independent_button.invoke();self.root.update()
        d.suggestion_button.invoke();self.root.update()
        self.assertEqual(d.selected_ids,{'101'})
        self.assertIn('0 checked move(s) hidden',d._feature_filters.note.get())
        d._feature_filters.variables['tee'].set(False);d._feature_filters.apply();self.root.update()
        self.assertIn('1 checked move(s) hidden',d._feature_filters.note.get())
        self.assertEqual(d.selected_ids,{'101'})
        d.undo_button.invoke();self.root.update();self.assertFalse(d.selected_ids)
    def test_real_button_acceptance_to_signed_export(self):
        d=self.open_case();self.focus('101');d.independent_button.invoke();d.suggestion_button.invoke();self.root.update()
        out,_=self.export()
        np.testing.assert_allclose(xy(out.read_bytes(),101,self.proj,self.grid)-xy(self.raw,101,self.proj,self.grid),np.tile((3.,-2.5),(5,1)),atol=1e-5)
        cutout=ET.fromstring(out.read_bytes()).find('relation').findall('member')[1].get('ref')
        self.assertNotEqual(cutout,'101')
        np.testing.assert_allclose(xy(out.read_bytes(),cutout,self.proj,self.grid),xy(self.raw,101,self.proj,self.grid),atol=1e-5)
    def independent_bad_parent(self,type_):
        d=self.open_case('green',type_);sid='surface-way:101';self.focus(sid)
        self.assertGreater(len(d._movement_ids()),1)
        d.independent_button.invoke();self.root.update()
        self.assertEqual(d._movement_ids(),{sid});self.assertFalse(d.link_holes_var.get())
        d.manual_east_var.set('2.0');d.manual_north_var.set('-1.0');d.set_offsets_button.invoke();self.root.update()
        self.assertEqual(d.selected_ids,{sid})
        self.assertFalse(self.messages)
        out,summary=self.export();output=out.read_bytes()
        np.testing.assert_allclose(xy(output,101,self.proj,self.grid)-xy(self.raw,101,self.proj,self.grid),np.tile((2.,-1.),(5,1)),atol=1e-5)
        for wid in [100,102,200,201,202]:
            np.testing.assert_allclose(xy(output,wid,self.proj,self.grid),xy(self.raw,wid,self.proj,self.grid),atol=1e-5)
        rel=ET.fromstring(output).find('relation');oldrel=ET.fromstring(self.raw).find('relation')
        self.assertEqual(rel.findall('member')[-1].attrib,oldrel.findall('member')[-1].attrib)
        cutout=rel.findall('member')[1].get('ref')
        np.testing.assert_allclose(xy(output,cutout,self.proj,self.grid),xy(self.raw,101,self.proj,self.grid),atol=1e-5)
    def test_real_independent_green_missing_parent_member(self):self.independent_bad_parent('way')
    def test_real_independent_green_nonway_parent_member(self):self.independent_bad_parent('relation')
    def test_real_invalid_linked_group_still_refused(self):
        d=self.open_case('green','way');self.focus('surface-way:101')
        d.manual_east_var.set('2.0');d.manual_north_var.set('-1.0');d.set_offsets_button.invoke();self.root.update()
        self.assertFalse(d.selected_ids);self.assertFalse(d.manual_overrides)
        self.assertTrue(any('missing/non-way inner' in str(m) for m in self.messages))
    def test_real_changed_source_rejected_on_save(self):
        d=self.open_case();self.focus('101');d.independent_button.invoke();d.suggestion_button.invoke();self.root.update()
        self.source.write_bytes(self.raw+b'\n')
        out=Path(self.tmp.name)/'rejected.osm'
        with self.assertRaises(engine.AlignmentError):
            engine.apply_reviewed(d.report,sorted(d.selected_ids),out,current_data=self.data,current_nudge=self.nudge,
                current_osm_file=self.source,manual_overrides=d.manual_overrides)
        self.assertFalse(out.exists());self.assertFalse(engine.manifest_path(out).exists())

if __name__=='__main__':unittest.main(verbosity=2)
