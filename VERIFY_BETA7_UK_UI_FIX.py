"""Actual Tk widget checks under the application's TabStyle, no live downloads.
Run from the patched TGC source folder. --screenshot PATH saves a real dialog.
"""
from pathlib import Path
import argparse
import ast
import sys
import tempfile
import time
import unittest
from unittest import mock
import tkinter as tk
from tkinter import ttk
import uk_lidar_ui as ui
import uk_lidar_downloader as uk

BBOX=(-.1506692,53.7385853,-.1257384,53.7489575)


def set_app_theme(root):
    # Use the exact theme declaration in the installed application, without
    # importing tgc_gui (which enters mainloop and imports the acquisition stack).
    source=Path(__file__).parent/'tgc_gui.py'
    if source.is_file():
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)
               and isinstance(n.func,ast.Attribute) and n.func.attr=='theme_create'
               and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='TabStyle']
    else:
        raise RuntimeError('Run this verifier from the patched TGC source folder.')
    if len(calls)!=1:
        raise RuntimeError('Expected the installed TabStyle theme declaration.')
    args={k.arg:ast.literal_eval(k.value) for k in calls[0].keywords}
    style=ttk.Style(root)
    if 'TabStyle' not in style.theme_names():style.theme_create('TabStyle',**args)
    style.theme_use('TabStyle')
    return style


def datasets():
    out=[]
    for i,(title,year,res) in enumerate((
        ('LIDAR Point Cloud','2016','N/A'),
        ('National LIDAR Programme Point Cloud','2018','1m'),
        ('National LIDAR Programme Point Cloud','2021','1m'),
    )):
        out.append(uk.Dataset('fixture-'+str(i),'England',title,'pointcloud',
            year=year,resolution=res,licence='Open Government Licence v3',
            notes='Coverage must be checked; intersecting tiles can contain gaps.',
            assets=[uk.Asset('https://example.invalid/tiles/'+str(i),'test tile')]))
    return out


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.project=Path(self.temp.name)
        self.osm=self.project/'Burstwick.osm';self.osm.write_text('<osm/>')
        self.root=tk.Tk();self.root.geometry('320x70+0+0');self.root.update()
        self.style=set_app_theme(self.root)
        self.globals={n:(self.style.configure(n),self.style.map(n),self.style.layout(n))
                      for n in ('TButton','Treeview','TNotebook')}
        self.errors=[];self.messages=[];self.ready=[];self.closed=[]
        self.root.report_callback_exception=lambda *a:self.errors.append(a)
        self.dialog=ui.UKDownloadDialog(self.root,self.project,self.osm,
            printf=self.messages.append,on_ready=lambda *a:self.ready.append(a),
            on_close=lambda:self.closed.append(1))
        self.dialog.window.geometry('1120x800+10+10');self.root.update()
        self.data=datasets()
    def tearDown(self):
        if not self.dialog.closed:self.dialog._finish()
        self.root.update_idletasks();self.root.destroy();self.temp.cleanup()
        self.assertEqual(self.errors,[])
    def found(self):
        self.dialog.region.set('England');self.dialog.mode.set(list(ui.MODES)[1])
        self.dialog.queue.put(('found',(BBOX,self.data,[])))
        self.wait(lambda:len(self.dialog.datasets)==3)
    def wait(self,predicate):
        end=time.monotonic()+4
        while not predicate() and time.monotonic()<end:
            self.root.update();time.sleep(.015)
        self.root.update();self.assertTrue(predicate())
    def choose(self,i):
        iid=str(i);x,y,w,h=self.dialog.table.bbox(iid)
        self.dialog.table.event_generate('<ButtonPress-1>',x=x+15,y=y+h//2)
        self.dialog.table.event_generate('<ButtonRelease-1>',x=x+15,y=y+h//2)
        self.root.update()
        self.assertEqual(self.dialog.table.selection(),(iid,))
    def test_private_styles_no_global_theme_changes(self):
        self.assertEqual(self.style.theme_use(),'TabStyle')
        for n,prior in self.globals.items():
            self.assertEqual((self.style.configure(n),self.style.map(n),self.style.layout(n)),prior)
    def test_four_actions_have_borders_padding_and_press_state(self):
        for w in (self.dialog.discover_button,self.dialog.download_button,self.dialog.portal_button,self.dialog.cancel_button):
            style=str(w['style']);self.assertEqual(style,self.dialog._button_style)
            self.assertEqual(str(self.style.lookup(style,'relief',state=())),'raised')
            self.assertGreaterEqual(int(self.style.lookup(style,'borderwidth')),2)
            self.assertEqual(str(self.style.lookup(style,'relief',state=('pressed',))),'sunken')
            self.assertGreater(w.winfo_height(),26)
    def test_empty_selection_disables_download(self):
        self.assertTrue(self.dialog.download_button.instate(['disabled']))
        self.assertIsNone(self.dialog._selected())
    def test_first_result_is_selected_focused_and_highlighted(self):
        self.found();t=self.dialog.table
        self.assertEqual(t.selection(),('0',));self.assertEqual(t.focus(),'0')
        self.assertIn('uk_selected',t.item('0','tags'))
        self.assertFalse(self.dialog.download_button.instate(['disabled']))
    def test_click_each_row_selects_exact_dataset(self):
        self.found()
        for i in (2,0,1):
            self.choose(i);self.assertIs(self.dialog._selected(),self.data[i])
            self.assertIn(self.data[i].year,self.dialog.selected_text.get())
    def test_only_one_row_highlighted(self):
        self.found();self.choose(2)
        tagged=[i for i in self.dialog.table.get_children() if 'uk_selected' in self.dialog.table.item(i,'tags')]
        self.assertEqual(tagged,['2'])
    def test_focus_out_retains_blue_white_selection(self):
        self.found();self.choose(1);self.dialog.portal_button.focus_force();self.root.update()
        self.assertEqual(self.dialog.table.selection(),('1',))
        self.assertIn('uk_selected',self.dialog.table.item('1','tags'))
        style=self.dialog._table_style
        for state in (('selected',),('selected','focus'),('selected','!focus')):
            self.assertEqual(self.style.lookup(style,'background',state=state),'#0078D7')
            self.assertEqual(self.style.lookup(style,'foreground',state=state),'#FFFFFF')
    def test_keyboard_up_down_changes_selection(self):
        self.found();t=self.dialog.table;t.focus_force();self.root.update()
        t.event_generate('<KeyPress-Down>');self.root.update();self.assertEqual(t.selection(),('1',))
        t.event_generate('<KeyPress-Up>');self.root.update();self.assertEqual(t.selection(),('0',))
    def test_enter_uses_normal_download_route(self):
        self.found();self.choose(2);t=self.dialog.table;t.focus_force();self.root.update()
        with mock.patch.object(self.dialog,'download') as download:
            t.event_generate('<KeyPress-Return>');self.root.update();download.assert_called_once()
    def test_no_selection_disables_download_and_clears_label(self):
        self.found();t=self.dialog.table;t.selection_remove(t.selection());self.root.update()
        self.assertTrue(self.dialog.download_button.instate(['disabled']))
        self.assertEqual(self.dialog.selected_text.get(),'Selected dataset: none')
    def test_busy_disables_actions_but_keeps_highlight(self):
        self.found();self.choose(2);self.dialog._busy(True);self.root.update()
        for w in (self.dialog.discover_button,self.dialog.portal_button,self.dialog.download_button):
            self.assertTrue(w.instate(['disabled']))
        self.assertFalse(self.dialog.cancel_button.instate(['disabled']))
        self.assertIn('uk_selected',self.dialog.table.item('2','tags'))
        self.assertIn('Cancel',self.dialog.cancel_button['text'])
        self.dialog._busy(False)
    def test_busy_completion_reenables_selected_download(self):
        self.found();self.dialog._busy(True);self.dialog._busy(False)
        self.assertFalse(self.dialog.download_button.instate(['disabled']))
        for w in self.dialog._controls:
            if isinstance(w,ttk.Combobox):self.assertTrue(w.instate(['readonly']))
    def test_cleared_dataset_during_busy_does_not_enable_download(self):
        self.found();self.dialog._busy(True);self.dialog.table.selection_remove('0');self.dialog._details()
        self.assertTrue(self.dialog.download_button.instate(['disabled']))
        self.dialog._busy(False);self.assertTrue(self.dialog.download_button.instate(['disabled']))
    def test_mode_or_region_change_requires_fresh_search(self):
        self.found();self.dialog.mode.set(next(iter(ui.MODES)));self.dialog._selection_changed()
        self.assertFalse(self.dialog.datasets);self.assertFalse(self.dialog.table.get_children())
        self.assertEqual(self.dialog.selected_text.get(),'Selected dataset: none')
        self.assertTrue(self.dialog.download_button.instate(['disabled']))
    def test_missing_invalid_or_stale_row_is_not_downloadable(self):
        self.found();t=self.dialog.table
        for iid in ('-1','999','not_an_index'):
            t.insert('','end',iid=iid,values=('bad',));t.selection_set(iid)
            self.root.update();self.assertIsNone(self.dialog._selected())
            self.assertTrue(self.dialog.download_button.instate(['disabled']))
    def test_selected_dataset_reaches_confirmation_and_worker(self):
        self.found();self.choose(2);self.dialog.process.set(False)
        result=uk.DownloadResult(str(self.project),str(self.project/'UK_Data'),
                                 'pointcloud',['tile.las'],'manifest.json')
        with mock.patch.object(ui.messagebox,'askyesno',return_value=True) as confirm, \
             mock.patch.object(uk,'download',return_value=result) as download:
            self.dialog.download_button.invoke();self.wait(lambda:not self.dialog.busy)
            self.assertIs(download.call_args.args[0],self.data[2])
            self.assertIn('2021',self.dialog.selected_text.get())
            self.assertIn(self.data[2].title,confirm.call_args.args[1])
        self.assertFalse(self.ready);self.assertFalse(self.dialog.closed)
    def test_declined_confirmation_has_no_download(self):
        self.found()
        with mock.patch.object(ui.messagebox,'askyesno',return_value=False),mock.patch.object(uk,'download') as download:
            self.dialog.download_button.invoke();download.assert_not_called()
        self.assertFalse(self.dialog.busy)
    def test_search_worker_and_selected_result_event(self):
        with mock.patch.object(uk,'course_bbox',return_value=BBOX), \
             mock.patch.object(uk,'discover',return_value=(self.data,[])):
            self.dialog.region.set('England');self.dialog.mode.set(list(ui.MODES)[1])
            self.dialog.discover_button.invoke();self.wait(lambda:not self.dialog.busy)
        self.assertEqual(self.dialog.table.selection(),('0',))
    def test_provider_button_uses_selected_region(self):
        self.found();self.data[2].region='Scotland';self.choose(2)
        with mock.patch.object(ui.webbrowser,'open') as opening:
            self.dialog.portal_button.invoke();opening.assert_called_once_with(uk.PROVIDERS['Scotland'])
    def test_worker_error_restores_controls_and_keeps_selection(self):
        self.found();self.dialog._busy(True)
        with mock.patch.object(ui.messagebox,'showerror'):
            self.dialog.queue.put(('error',('Test failure','fixture traceback')))
            self.wait(lambda:not self.dialog.busy)
        self.assertEqual(self.dialog.table.selection(),('0',))
        self.assertFalse(self.dialog.download_button.instate(['disabled']))
    def test_footer_buttons_visible_after_resize(self):
        self.found()
        for size in ('1180x820','900x700','820x640'):
            self.dialog.window.geometry(size);self.root.update()
            bottom=self.dialog.window.winfo_rooty()+self.dialog.window.winfo_height()
            right=self.dialog.window.winfo_rootx()+self.dialog.window.winfo_width()
            for w in (self.dialog.portal_button,self.dialog.download_button,self.dialog.cancel_button):
                self.assertTrue(w.winfo_ismapped())
                self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),bottom,size)
                self.assertLessEqual(w.winfo_rootx()+w.winfo_width(),right,size)
    def test_horizontal_and_vertical_scrollbars_connected(self):
        self.assertTrue(self.dialog.table['xscrollcommand']);self.assertTrue(self.dialog.table['yscrollcommand'])
    def test_close_cancels_queued_ui_callbacks(self):
        after_id = self.dialog._pump_after_id
        self.assertIsNotNone(after_id)
        self.dialog.close()
        self.assertIsNone(self.dialog._pump_after_id)
        self.assertNotIn(after_id, self.root.tk.call('after','info'))
    def test_close_does_not_trigger_processing(self):
        self.found();self.dialog.cancel_button.invoke();self.assertTrue(self.dialog.closed)
        self.assertEqual(self.closed,[1]);self.assertFalse(self.ready)
    def test_cancel_signals_existing_worker(self):
        self.dialog._busy(True);self.dialog.cancel_button.invoke()
        self.assertTrue(self.dialog.cancel.is_set());self.assertTrue(self.dialog.close_when_done)
        self.assertTrue(self.dialog.cancel_button.instate(['disabled']))
        self.dialog.queue.put(('cancelled','Cancelled fixture'));self.wait(lambda:self.dialog.closed)
    def test_fixture_unchanged_by_selection(self):
        self.found();before=repr(self.data)
        self.choose(2);self.choose(1);self.choose(0)
        self.assertEqual(repr(self.data),before);self.assertEqual(self.osm.read_text(),'<osm/>')
    def test_version_syntax_and_global_style_scope(self):
        path=Path(ui.__file__);s=path.read_text(encoding='utf-8-sig');tree=ast.parse(s,feature_version=(3,11))
        self.assertEqual(ui.VERSION,'TGC_BETA7_UK_UI_V4')
        self.assertNotIn('theme_use(',s)
        self.assertIn('TGC_BETA7_UK_BUTTON_SELECTION_FIX_V1',s)


def screenshot(path):
    from PIL import ImageGrab
    root=tk.Tk();root.geometry('200x60+0+0');set_app_theme(root)
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);osm=p/'Burstwick.osm';osm.write_text('<osm/>')
        d=ui.UKDownloadDialog(root,p,osm,printf=lambda s:None)
        d.window.geometry('1180x820+20+20');d.region.set('England');d.mode.set(list(ui.MODES)[1])
        d.queue.put(('found',(BBOX,datasets(),[])))
        until=time.monotonic()+1
        while time.monotonic()<until:root.update();time.sleep(.02)
        d.table.selection_set('2');d.table.focus('2');d._details();d.portal_button.focus_force();root.update()
        d._say('UI preview: example dataset rows; no live download performed.')
        root.update()
        b=(d.window.winfo_rootx(),d.window.winfo_rooty(),
           d.window.winfo_rootx()+d.window.winfo_width(),d.window.winfo_rooty()+d.window.winfo_height())
        ImageGrab.grab().crop(b).save(path);d.close()
    root.destroy()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--screenshot');args=parser.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DialogTests))
    if not result.wasSuccessful():raise SystemExit(1)
    if args.screenshot:screenshot(args.screenshot)
    print('UK UI: actual Tk selection, focus, buttons, worker and footer checks passed; no live acquisition.')
