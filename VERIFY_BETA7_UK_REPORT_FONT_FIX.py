"""Actual Tk font/layout regression checks. No provider, project or EXE writes.
DPI settings on Linux simulate font metrics; they do not claim Windows execution.
"""
from pathlib import Path
import ast
import tempfile
import tkinter as tk
from tkinter import font as tkfont
import unittest
import VERIFY_BETA7_UK_UI_FIX as original
import uk_lidar_ui as ui

class FontLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.geometry('200x60+0+0')
        original.set_app_theme(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *a: self.errors.append(a)
        self.d = None
        self.fonts = {name: tkfont.nametofont(name, self.root).actual()
                      for name in tkfont.names(self.root)}
        self.scaling = float(self.root.tk.call('tk', 'scaling'))

    def tearDown(self):
        if self.d is not None and not self.d.closed:
            self.d._finish()
        self.root.update_idletasks()
        self.root.destroy()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def new(self, dpi=None, fixed_size=10, ui_size=9):
        if self.d is not None and not self.d.closed:
            self.d._finish()
            self.root.update()
        self.root.tk.call('tk', 'scaling', self.scaling if dpi is None else dpi / 72.0)
        for name, actual in self.fonts.items():
            tkfont.nametofont(name, self.root).configure(**actual)
        if dpi is not None:
            windows = self.root.tk.call('tk', 'windowingsystem') == 'win32'
            for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
                tkfont.nametofont(name, self.root).configure(
                    family='Segoe UI' if windows else 'DejaVu Sans', size=ui_size)
            tkfont.nametofont('TkFixedFont', self.root).configure(
                family='Consolas' if windows else 'DejaVu Sans Mono', size=fixed_size)
        self.d = ui.UKDownloadDialog(self.root, self.temp.name,
                    Path(self.temp.name) / 'sample.osm', printf=lambda s: None)
        self.d.window.geometry('1180x820+10+10')
        self.root.update()
        return self.d

    def line(self):
        return int(self.d.log.tk.call('font', 'metrics', self.d.log.cget('font'), '-linespace'))

    def ten_lines(self):
        self.assertGreaterEqual(self.d.log.winfo_height() - 10, 10 * self.line())
        self.d.log.configure(state='normal')
        self.d.log.delete('1.0', 'end')
        self.d.log.insert('1.0', '\n'.join('Line %02d' % i for i in range(1, 31)))
        self.d.log.configure(state='disabled')
        self.d.log.yview_moveto(0)
        self.root.update()
        tenth = self.d.log.dlineinfo('10.0')
        self.assertIsNotNone(tenth, 'Tenth row must actually be visible, not only requested')
        inset = sum(self.d.log.winfo_pixels(self.d.log.cget(k))
                    for k in ('borderwidth', 'highlightthickness', 'pady'))
        self.assertLessEqual(tenth[1] + tenth[3], self.d.log.winfo_height() - inset)

    def footer(self):
        d = self.d
        self.root.update()
        right = d.window.winfo_rootx() + d.window.winfo_width()
        bottom = d.window.winfo_rooty() + d.window.winfo_height()
        for w in (d.portal_button, d.download_button, d.cancel_button):
            self.assertTrue(w.winfo_ismapped())
            self.assertLessEqual(w.winfo_rootx() + w.winfo_width(), right)
            self.assertLessEqual(w.winfo_rooty() + w.winfo_height(), bottom)
        self.assertGreater(d.log.winfo_height(), 40)
        self.assertLessEqual(d.log.winfo_rooty() + d.log.winfo_height(),
                             d._footer_frame.winfo_rooty())

    def drag(self, delta):
        p = self.d._report_panes
        x, y = p.sash_coord(0)
        x = max(25, x + 5); y += 5
        p.event_generate('<ButtonPress-1>', x=x, y=y); self.root.update()
        self.assertTrue(self.d._report_dragging)
        p.event_generate('<B1-Motion>', x=x, y=y + delta); self.root.update()
        p.event_generate('<ButtonRelease-1>', x=x, y=y + delta); self.root.update()

    def test_original_ten_line_assertion_retained(self):
        source = (Path(__file__).parent / 'VERIFY_BETA7_UK_REPORT_PANE.py').read_text(encoding='utf-8-sig')
        node = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef) and n.name == 'test_default_report_at_least_10_visible_lines')
        self.assertIn('self.assertGreaterEqual(self.d.log.winfo_height()-10,10*line)',
                      ast.get_source_segment(source, node))
        self.assertFalse(node.decorator_list)

    def test_native_default_has_ten_actual_lines(self):
        self.new(); self.ten_lines(); self.footer()

    def test_20_pixel_class_fixed_font(self):
        self.new(dpi=120)
        self.assertGreaterEqual(self.line(), 18)
        self.ten_lines(); self.footer()
        print('120 DPI fixed-font check: line=%d px; log=%d px.' %
              (self.line(), self.d.log.winfo_height()))

    def test_default_metric_matrix(self):
        for dpi in (96, 120, 144, 192):
            for size in (10, 12):
                with self.subTest(dpi=dpi, fixed_points=size):
                    self.new(dpi=dpi, fixed_size=size)
                    self.ten_lines(); self.footer()
        print('8 native-widget metric cases passed at 96/120/144/192 simulated DPI.')

    def test_default_ui_font_sizes(self):
        for size in (9, 11, 13):
            with self.subTest(ui_points=size):
                self.new(dpi=120, ui_size=size)
                self.ten_lines(); self.footer()

    def test_small_window_footer_and_expand_accessible(self):
        for dpi in (96, 120, 144, 192):
            self.new(dpi=dpi)
            for busy in (False, True):
                self.d.window.geometry('820x640'); self.d._busy(busy); self.root.update()
                self.assertEqual((self.d.window.winfo_width(), self.d.window.winfo_height()), (820, 640))
                self.footer()
                self.assertTrue(self.d.expand_report_button.winfo_ismapped())
                self.assertTrue(self.d.copy_report_button.winfo_ismapped())
                self.d._busy(False)

    def test_growth_20px_class_font(self):
        self.new(dpi=120)
        self.d.window.geometry('820x640'); self.root.update(); height = self.d.log.winfo_height()
        self.d.window.geometry('1180x900'); self.root.update()
        self.assertGreater(self.d.log.winfo_height(), height + 60)
        self.footer()

    def test_manual_smaller_split_is_respected(self):
        self.new(dpi=120); before = self.d.log.winfo_height()
        self.drag(90)
        self.assertTrue(self.d._report_user_split)
        self.assertLess(self.d.log.winfo_height(), before - 50)
        height = self.d.log.winfo_height()
        self.d._schedule_report_layout(); self.root.update()
        self.assertAlmostEqual(height, self.d.log.winfo_height(), delta=3)
        self.footer()

    def test_manual_split_ratio_after_resize(self):
        self.new(dpi=120); self.drag(-90)
        ratio = self.d._report_fraction
        self.d.window.geometry('1180x1000'); self.root.update()
        actual = self.d._report_panes.sash_coord(0)[1] / self.d._report_panes.winfo_height()
        self.assertAlmostEqual(ratio, actual, delta=.025)
        self.footer()

    def test_expansion_restore_selection_at_20px_class(self):
        self.new(dpi=120)
        self.d.queue.put(('found', (original.BBOX, original.datasets(), [])))
        if self.d._pump_after_id is not None:
            self.d.window.after_cancel(self.d._pump_after_id)
            self.d._pump_after_id = None
        self.d._pump(); self.root.update()
        self.d.table.selection_set('2'); self.d._details()
        before = self.d.log.winfo_height()
        self.d.expand_report_button.invoke(); self.root.update()
        self.assertGreater(self.d.log.winfo_height(), before + 200)
        self.footer()
        self.d.expand_report_button.invoke(); self.root.update()
        self.assertEqual(self.d.table.selection(), ('2',))
        self.ten_lines(); self.footer()

    def test_font_and_theme_not_modified_by_layout(self):
        self.new(dpi=120)
        before = {name: tkfont.nametofont(name, self.root).actual()
                  for name in tkfont.names(self.root)}
        for size in ('820x640', '1180x820', '1100x900'):
            self.d.window.geometry(size); self.root.update()
        after = {name: tkfont.nametofont(name, self.root).actual()
                 for name in before}
        self.assertEqual(before, after)

    def test_metrics_include_padding_and_toolbar(self):
        self.new(dpi=120)
        self.d.log.configure(pady=9, borderwidth=3, highlightthickness=2)
        self.d._schedule_report_layout(); self.root.update()
        self.ten_lines(); self.footer()
        preferred, minimum, sash = self.d._report_height_budget()
        self.assertGreaterEqual(preferred, 12 * self.line() + 28)
        self.assertGreater(minimum, 2 * self.line())
        self.assertGreater(sash, 0)

if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FontLayoutTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print('Font-aware report sizing verified; original tests and native font settings retained.')
