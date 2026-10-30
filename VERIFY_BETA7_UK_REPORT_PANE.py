"""Actual Tk report-pane regression tests; provider data is explicitly simulated.
Run beside the installed tgc_gui.py; no network, source update or EXE writes.
"""
from pathlib import Path
import argparse
import tempfile
import time
import tkinter as tk
from tkinter import font as tkfont
import unittest
from unittest import mock
import VERIFY_BETA7_UK_UI_FIX as old
import uk_lidar_ui as ui

class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.project=Path(self.temp.name)
        self.root=tk.Tk();self.root.geometry('200x60+0+0');old.set_app_theme(self.root)
        self.errors=[];self.root.report_callback_exception=lambda *x:self.errors.append(x)
        self.output=[]
        self.d=ui.UKDownloadDialog(self.root,self.project,self.project/'fixture.osm',printf=self.output.append)
        self.d.window.geometry('1180x820+10+10');self.root.update()
    def tearDown(self):
        if not self.d.closed:self.d._finish()
        self.root.update();self.root.destroy();self.temp.cleanup()
        self.assertEqual(self.errors,[])
    def found(self):
        self.data=old.datasets();self.d.queue.put(('found',(old.BBOX,self.data,[])))
        end=time.monotonic()+1
        while time.monotonic()<end and not self.d.datasets:self.root.update();time.sleep(.01)
        self.assertEqual(len(self.d.datasets),3);self.root.update()
    def bounds(self):
        d=self.d;self.root.update()
        top=d.window.winfo_rooty();bottom=top+d.window.winfo_height()
        self.assertGreaterEqual(d.log.winfo_rooty(),top)
        self.assertLessEqual(d.log.winfo_rooty()+d.log.winfo_height(),d._footer_frame.winfo_rooty())
        self.assertGreater(d.log.winfo_height(),40)
        for w in (d.portal_button,d.download_button,d.cancel_button):
            self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),bottom)
    def drag(self,delta):
        p=self.d._report_panes;x,y=p.sash_coord(0);x=max(25,x+5);y+=5
        p.event_generate('<ButtonPress-1>',x=x,y=y);self.root.update()
        self.assertTrue(self.d._report_dragging)
        p.event_generate('<B1-Motion>',x=x,y=y+delta);self.root.update()
        p.event_generate('<ButtonRelease-1>',x=x,y=y+delta);self.root.update()
    def test_default_report_at_least_10_visible_lines(self):
        line=tkfont.nametofont('TkFixedFont',self.root).metrics('linespace')
        self.assertGreaterEqual(self.d.log.winfo_height()-10,10*line)
        self.assertGreaterEqual(self.d._report_frame.winfo_height(),200);self.bounds()
    def test_real_mouse_drag_resizes_report(self):
        before=self.d.log.winfo_height();self.drag(-100)
        self.assertGreaterEqual(self.d.log.winfo_height(),before+80);self.bounds()
    def test_drag_both_directions(self):
        before=self.d.log.winfo_height();self.drag(-80);high=self.d.log.winfo_height();self.drag(80)
        self.assertGreater(high,before+60);self.assertAlmostEqual(self.d.log.winfo_height(),before,delta=12)
    def test_enlarging_window_grows_log(self):
        self.d.window.geometry('820x640');self.root.update();h=self.d.log.winfo_height()
        self.d.window.geometry('1180x900');self.root.update()
        self.assertGreater(self.d.log.winfo_height(),h+60);self.bounds()
    def test_user_split_ratio_survives_window_resize(self):
        self.drag(-100);ratio=self.d._report_fraction
        self.d.window.geometry('1180x1000');self.root.update()
        measured=self.d._report_panes.sash_coord(0)[1]/self.d._report_panes.winfo_height()
        self.assertAlmostEqual(ratio,measured,delta=.025)
    def test_upper_scrolling_does_not_move_report_or_footer(self):
        self.d.detail.set('Large detail paragraph\n'*40);self.root.update()
        positions=(self.d.log.winfo_rooty(),self.d.cancel_button.winfo_rooty())
        self.d._body_canvas.yview_moveto(1);self.root.update()
        self.assertEqual(positions,(self.d.log.winfo_rooty(),self.d.cancel_button.winfo_rooty()))
    def test_expanded_report_and_restored_selection(self):
        self.found();self.d.table.selection_set('2');self.d._details();self.drag(-60)
        ratio=self.d._report_fraction;before=self.d.log.winfo_height()
        self.d.expand_report_button.invoke();self.root.update()
        self.assertGreater(self.d.log.winfo_height(),before+200)
        self.assertTrue(self.d._report_expanded);self.assertFalse(self.d._upper_viewport.winfo_ismapped())
        self.bounds();self.d.expand_report_button.invoke();self.root.update()
        self.assertEqual(self.d.table.selection(),('2',));self.assertAlmostEqual(self.d._report_fraction,ratio)
        self.assertTrue(self.d._upper_viewport.winfo_ismapped());self.assertFalse(self.d.download_button.instate(['disabled']))
    def test_report_actions_available_while_busy(self):
        self.found();self.d._busy(True);self.root.update()
        for w in (self.d.expand_report_button,self.d.copy_report_button):self.assertFalse(w.instate(['disabled']))
        self.assertTrue(self.d.download_button.instate(['disabled']))
        self.d.expand_report_button.invoke();self.root.update();self.bounds();self.d._busy(False)
    def test_copy_full_report_and_preserve_readonly(self):
        lines=['row %d — complete URL/error detail' % i for i in range(100)]
        for line in lines:self.d._say(line)
        self.root.update();self.d.copy_report_button.invoke();self.root.update()
        self.assertEqual(self.d.window.clipboard_get(),'\n'.join(lines)+'\n')
        self.assertEqual(str(self.d.log['state']),'disabled');self.assertEqual(self.output,lines)
    def test_ctrl_a_selects_report_only(self):
        self.d._say('first\nsecond');self.d.log.focus_force();self.root.update()
        self.d.log.event_generate('<Control-a>');self.root.update()
        self.assertEqual(self.d.log.get('sel.first','sel.last'),'first\nsecond\n')
    def test_output_does_not_snap_away_from_old_lines(self):
        for i in range(150):self.d._say('Progress row '+str(i))
        self.root.update();self.d.log.yview_moveto(0);self.root.update();before=self.d.log.yview()[0]
        self.d._say('new row while reading older error');self.root.update()
        self.assertAlmostEqual(self.d.log.yview()[0],before,delta=.01)
    def test_follow_output_when_at_bottom(self):
        for i in range(100):self.d._say(str(i));self.root.update_idletasks()
        self.d.log.see('end');self.root.update();self.d._say('LAST COMPLETE MESSAGE');self.root.update()
        self.assertGreater(self.d.log.yview()[1],.99)
    def test_multiline_huge_status_never_squeezes_report(self):
        before=self.d.log.winfo_height();message='Exception '*400+'\n'+'stack trace\n'*80
        self.d._say(message);self.root.update()
        self.assertEqual(self.d.log.winfo_height(),before);self.assertEqual(self.d.log.get('1.0','end-1c'),message+'\n')
        self.bounds()
    def test_resize_during_live_queue_activity(self):
        self.found();self.d._busy(True)
        for i,size in enumerate(('820x640','1180x820','900x700','820x640')):
            self.d.window.geometry(size);self.d.queue.put(('log','Simulated progress '+str(i)))
            if self.d._pump_after_id is not None:
                self.d.window.after_cancel(self.d._pump_after_id);self.d._pump_after_id=None
            self.root.update();self.d._pump();self.root.update();self.bounds()
        self.assertIn('Simulated progress 3',self.d.log.get('1.0','end'));self.d._busy(False)
    def test_close_cancels_report_layout_callback(self):
        self.d._schedule_report_layout();queued=self.d._report_layout_after_id
        self.assertIsNotNone(queued);self.d._finish();self.root.update()
        self.assertIsNone(self.d._report_layout_after_id)
        self.assertNotIn(queued,self.root.tk.call('after','info'))
    def test_screenshot_not_required_and_source_no_global_bindings(self):
        source=Path(ui.__file__).read_text();self.assertIn('TGC_BETA7_UK_RESIZABLE_REPORT_V1',source)
        self.assertNotIn('.bind_all(',source);self.assertNotIn('.theme_use(',source)


def screenshot(path,size='1180x820'):
    from PIL import ImageGrab
    root=tk.Tk();root.geometry('200x60+0+0');old.set_app_theme(root)
    with tempfile.TemporaryDirectory() as td:
        d=ui.UKDownloadDialog(root,td,Path(td)/'UK_UI_Test.osm',printf=lambda s:None)
        d.window.geometry(size+'+20+20');d.region.set('England');d.mode.set(list(ui.MODES)[1]);root.update()
        d.queue.put(('found',(old.BBOX,old.datasets(),[])))
        end=time.monotonic()+.4
        while time.monotonic()<end:root.update();time.sleep(.01)
        for text in [
            'UI TEST PREVIEW — example rows and report messages, no live acquisition.',
            'The status/report is now an independent resizable pane.',
            'Drag the raised divider above this panel to make the report taller.',
            'Expand Report uses all available space; Restore Split brings the dataset list back.',
            'Copy Report copies the complete report, including off-screen messages.',
            '',
            'Example diagnostic: Scottish catalogue connection timed out.',
            'This UI patch does not change provider connections or claim to fix that timeout.',
            'Keep reading older output without being forced to the last line.',
            'Dataset selection, action buttons and processing callbacks remain unchanged.',
        ]:d._say(text)
        root.update();b=(d.window.winfo_rootx(),d.window.winfo_rooty(),d.window.winfo_rootx()+d.window.winfo_width(),d.window.winfo_rooty()+d.window.winfo_height())
        ImageGrab.grab().crop(b).save(path);d._finish()
    root.destroy()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--screenshot');args=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReportTests))
    if not result.wasSuccessful():raise SystemExit(1)
    if args.screenshot:screenshot(args.screenshot)
    print('Resizable report: real dragging, resize, expansion, clipboard, reading and worker-message checks passed.')
