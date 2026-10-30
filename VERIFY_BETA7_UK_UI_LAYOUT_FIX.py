"""Actual Tk layout regressions. No network, application builds, or project writes.
Uses the installed TGC TabStyle. DPI checks are Tk/font simulations, not a claim
that Windows display scaling was executed when this script runs on Linux.
"""
from pathlib import Path
from types import SimpleNamespace
import argparse
import ast
import json
import tempfile
import tkinter as tk
from tkinter import font as tkfont
import unittest
from unittest import mock
import VERIFY_BETA7_UK_UI_FIX as original
import uk_lidar_ui as ui


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.geometry('320x70+0+0')
        self.style = original.set_app_theme(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *a: self.errors.append(a)
        self.dialog = None
        self.original_scaling = float(self.root.tk.call('tk', 'scaling'))
        self.original_fonts = {name: tkfont.nametofont(name, self.root).actual()
                               for name in tkfont.names(self.root)}
        self.observations = []

    def tearDown(self):
        if self.dialog is not None and not self.dialog.closed:
            self.dialog._finish()
        self.root.update_idletasks()
        self.root.destroy()
        self.temp.cleanup()
        self.assertEqual(self.errors, [], 'Unexpected Tk callback failure')

    def new_dialog(self, dpi=None, long_text=False):
        if self.dialog is not None and not self.dialog.closed:
            self.dialog._finish()
        self.root.tk.call('tk', 'scaling', self.original_scaling if dpi is None else dpi / 72.0)
        for name, actual in self.original_fonts.items():
            tkfont.nametofont(name, self.root).configure(**actual)
        if dpi is not None:
            family = 'Segoe UI' if self.root.tk.call('tk', 'windowingsystem') == 'win32' else 'DejaVu Sans'
            fixed = 'Consolas' if family == 'Segoe UI' else 'DejaVu Sans Mono'
            for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
                tkfont.nametofont(name, self.root).configure(family=family, size=9)
            tkfont.nametofont('TkFixedFont', self.root).configure(family=fixed, size=10)
        project = Path(self.temp.name)
        if long_text:
            project = project / ('Long course project ' * 7) / ('Detailed survey acquisition ' * 5)
        self.dialog = ui.UKDownloadDialog(self.root, project, project/'Burstwick.osm', printf=lambda s: None)
        self.dialog.window.geometry('820x640+20+20')
        self.data = original.datasets()
        if long_text:
            self.data[2].title += ' — detailed regional collection information ' * 7
            self.data[2].notes = '\n'.join('Coverage note %d: %s' % (i, 'survey information ' * 12) for i in range(15))
        self.dialog.region.set('England')
        self.dialog.mode.set(list(ui.MODES)[1])
        self.dialog.queue.put(('found', (original.BBOX, self.data, [])))
        # Drain the real queue handler deterministically, not a network worker.
        after = self.dialog._pump_after_id
        if after is not None:
            self.dialog.window.after_cancel(after)
            self.dialog._pump_after_id = None
        self.dialog._pump()
        self.root.update()
        return self.dialog

    def assert_footer(self, label):
        d = self.dialog
        self.root.update()
        left, top = d.window.winfo_rootx(), d.window.winfo_rooty()
        right, bottom = left + d.window.winfo_width(), top + d.window.winfo_height()
        rectangles = []
        for w in (d.portal_button, d.download_button, d.cancel_button):
            a, b = w.winfo_rootx(), w.winfo_rooty()
            c, e = a+w.winfo_width(), b+w.winfo_height()
            self.assertTrue(w.winfo_ismapped(), label)
            self.assertGreaterEqual(a, left, label)
            self.assertGreaterEqual(b, top, label)
            self.assertLessEqual(c, right, label)
            self.assertLessEqual(e, bottom, label)
            self.assertGreater(w.winfo_width(), 20, label)
            self.assertGreater(w.winfo_height(), 20, label)
            # Visible within the direct parent, not merely within the toplevel.
            p = w.master
            self.assertGreaterEqual(w.winfo_x(), 0, label)
            self.assertGreaterEqual(w.winfo_y(), 0, label)
            self.assertLessEqual(w.winfo_x()+w.winfo_width(), p.winfo_width(), label)
            self.assertLessEqual(w.winfo_y()+w.winfo_height(), p.winfo_height(), label)
            rectangles.append((a,b,c,e))
        for i, first in enumerate(rectangles):
            for second in rectangles[i+1:]:
                self.assertFalse(min(first[2], second[2]) > max(first[0], second[0])
                                 and min(first[3], second[3]) > max(first[1], second[1]), label)
        self.observations.append({'case': label, 'window': [d.window.winfo_width(), d.window.winfo_height()],
                                  'footer_rows': d._footer_rows, 'buttons': rectangles,
                                  'window_bottom': bottom, 'body_yview': list(d._body_canvas.yview())})

    def test_original_820x640_stays_real_size(self):
        self.new_dialog()
        self.assertEqual((self.dialog.window.winfo_width(), self.dialog.window.winfo_height()), (820,640))
        self.assert_footer('original failing dimensions, unchanged minimum')

    def test_dpi_resize_matrix_idle_and_busy(self):
        for dpi in (96,120,144,192):
            self.new_dialog(dpi=dpi)
            for size in ('1180x820','900x700','820x640'):
                self.dialog.window.geometry(size)
                self.root.update()
                self.assertEqual((self.dialog.window.winfo_width(), self.dialog.window.winfo_height()),
                                 tuple(map(int, size.split('x'))))
                for busy in (False,True):
                    self.dialog._busy(busy)
                    self.assert_footer('%ddpi %s busy=%s' % (dpi,size,busy))
                self.dialog._busy(False)
        print('DPI matrix: 24 actual Tk layouts passed (96/120/144/192 DPI; 3 sizes; idle/busy).')

    def test_long_paths_and_multiline_dataset_details(self):
        for dpi in (96,192):
            self.new_dialog(dpi=dpi,long_text=True)
            self.dialog.table.selection_set('2');self.dialog._details()
            self.dialog._say('Download status: '+('long operation details ' * 40))
            for busy in (False,True):
                self.dialog._busy(busy)
                self.assert_footer('long content %ddpi busy=%s' % (dpi,busy))
            self.assertLess(self.dialog._body_canvas.yview()[1]-self.dialog._body_canvas.yview()[0], 1.0)
            self.dialog._busy(False)

    def test_scrolling_body_does_not_move_footer(self):
        self.new_dialog(dpi=192,long_text=True)
        d=self.dialog;self.root.update()
        positions=[(w.winfo_rootx(),w.winfo_rooty()) for w in (d.portal_button,d.download_button,d.cancel_button)]
        d._body_canvas.yview_moveto(1);self.root.update()
        self.assertEqual(positions,[(w.winfo_rootx(),w.winfo_rooty()) for w in (d.portal_button,d.download_button,d.cancel_button)])
        self.assert_footer('scrolled body')

    def test_tab_focus_reveals_body_controls(self):
        self.new_dialog(dpi=144)
        d=self.dialog
        d._body_canvas.yview_moveto(0)
        d.log.focus_force();self.root.update()
        top=d._body_canvas.winfo_rooty();bottom=top+d._body_canvas.winfo_height()
        # Report is independently visible below the upper scrolling body.
        self.assertGreaterEqual(d.log.winfo_rooty(), bottom)
        self.assertLessEqual(d.log.winfo_rooty()+d.log.winfo_height(),
                             d._footer_frame.winfo_rooty())
        d._region_combo.focus_force();self.root.update()
        self.assertGreaterEqual(d._region_combo.winfo_rooty(),top-20)
        self.assertLessEqual(d._region_combo.winfo_rooty()+d._region_combo.winfo_height(),bottom+20)
        self.assert_footer('keyboard focus')

    def test_mouse_wheel_scrolls_only_dialog_body(self):
        self.new_dialog(dpi=192,long_text=True)
        d=self.dialog;d._body_canvas.yview_moveto(0)
        before=d._body_canvas.yview()
        self.assertEqual(d._scroll_body(SimpleNamespace(num=None,delta=-120)), 'break')
        self.assertGreater(d._body_canvas.yview()[0],before[0])
        self.assertNotIn('bind_all(', Path(ui.__file__).read_text().replace('# Local bindings only; never bind_all() or change another window\'s wheel.',''))

    def test_reflow_preserves_selection_and_enabled_actions(self):
        self.new_dialog(dpi=192)
        d=self.dialog;d.table.selection_set('2');d._details()
        for size in ('1180x820','820x640','900x700','820x640'):
            d.window.geometry(size);self.root.update()
            d.portal_button.focus_force();self.root.update()
            self.assertIs(d._selected(),self.data[2])
            self.assertIn('uk_selected',d.table.item('2','tags'))
            self.assertFalse(d.download_button.instate(['disabled']))
            self.assert_footer(size)

    def test_long_cancel_caption_reflows_without_clipping(self):
        self.new_dialog(dpi=192)
        self.dialog._busy(True);self.root.update()
        self.assertIn('Cancel',self.dialog.cancel_button['text'])
        widths = sum(w.winfo_reqwidth() for w in (self.dialog.portal_button,
                     self.dialog.download_button,self.dialog.cancel_button)) + 24
        if widths > self.dialog._footer_frame.winfo_width():
            self.assertGreaterEqual(self.dialog._footer_rows,2)
        else:
            self.assertEqual(self.dialog._footer_rows,1)
        self.assert_footer('expanded cancel caption')
        self.dialog._busy(False);self.assert_footer('idle caption restored')

    def test_all_content_can_be_reached_via_scrollbar(self):
        self.new_dialog(dpi=192,long_text=True)
        d=self.dialog;d.table.selection_set('2');d._details();self.root.update()
        self.assertTrue(d._body_scrollbar['command'])
        self.assertTrue(d.log['yscrollcommand'])
        d._body_canvas.yview_moveto(1);self.root.update()
        self.assertAlmostEqual(d._body_canvas.yview()[1],1.0,places=4)
        self.assertGreaterEqual(d.log.winfo_rooty(),
                                d._body_canvas.winfo_rooty()+d._body_canvas.winfo_height())
        self.assertLessEqual(d.log.winfo_rooty()+d.log.winfo_height(),d._footer_frame.winfo_rooty())
        self.assertTrue(d._report_panes.winfo_ismapped())

    def test_original_visibility_test_not_removed_or_weakened(self):
        code=Path(original.__file__).read_text(encoding='utf-8-sig')
        module=ast.parse(code)
        test=next(n for n in ast.walk(module) if isinstance(n,ast.FunctionDef)
                  and n.name=='test_footer_buttons_visible_after_resize')
        text=ast.get_source_segment(code,test)
        self.assertIn("'820x640'",text)
        self.assertIn('self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),bottom,size)',text)
        self.assertIn('self.assertLessEqual(w.winfo_rootx()+w.winfo_width(),right,size)',text)
        self.assertFalse(test.decorator_list)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LayoutTests))
    if not result.wasSuccessful():raise SystemExit(1)
    print('UK layout: pinned footer, scrolling, fonts, DPI, selection and resize checks passed.')
