"""Screen-relative startup/layout checks. Uses real Tk, simulated monitor rectangles.
No network or application-data writes. Windows titlebar behavior needs Windows.
"""
from pathlib import Path
import ast
import tempfile
import tkinter as tk
import unittest
from unittest import mock
import tgc_window_layout as layout
import uk_lidar_ui as ui
import VERIFY_BETA7_UK_UI_FIX as original

class LargeWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.geometry('200x60+0+0')
        original.set_app_theme(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *a: self.errors.append(a)
        self.d = None
        self.rect = layout._work_area(self.root)
        self.expected = layout.large_geometry(self.rect)
    def tearDown(self):
        if self.d is not None and not self.d.closed:
            self.d._finish()
        self.root.update_idletasks()
        self.root.destroy()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])
    def start_function(self):
        source = (Path(__file__).parent/'tgc_gui.py').read_text(encoding='utf-8-sig')
        fn = next(n for n in ast.parse(source).body
                  if isinstance(n, ast.FunctionDef) and n.name == 'setStartupWindowSize')
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'installed_startup', 'exec'), ns)
        return ns['setStartupWindowSize']
    def dialog(self, rect=None):
        rect = self.rect if rect is None else rect
        with mock.patch.object(layout, '_work_area', return_value=rect):
            self.d = ui.UKDownloadDialog(self.root, self.temp.name,
                Path(self.temp.name)/'fixture.osm', printf=lambda s: None)
        self.root.update()
        return self.d
    def test_main_uses_large_default(self):
        with mock.patch.object(layout, '_work_area', return_value=self.rect):
            self.start_function()(self.root)
        self.root.update()
        self.assertEqual((self.root.winfo_width(),self.root.winfo_height()), self.expected[:2])
        self.assertEqual(tuple(self.root.resizable()), (1,1))
    def test_uk_matches_main_large_default(self):
        d=self.dialog()
        self.assertEqual((d.window.winfo_width(),d.window.winfo_height()),self.expected[:2])
        self.assertEqual(tuple(d.window.resizable()),(1,1))
    def test_no_fixed_cap_on_large_screens(self):
        for rect in ((0,0,2560,1400),(0,0,3840,2120),(0,0,3440,1400)):
            with self.subTest(rect=rect):
                w,h,x,y=layout.large_geometry(rect)
                self.assertGreater(w,1700); self.assertGreater(h,900)
                self.assertEqual(w,int(rect[2]*.95))
                self.assertEqual(h,int(rect[3]*.92))
    def test_small_display_stays_inside_work_area(self):
        for rect in ((0,0,800,560),(0,40,1024,728),(0,0,1366,728)):
            w,h,x,y=layout.large_geometry(rect)
            self.assertGreater(w,0);self.assertGreater(h,0)
            self.assertGreaterEqual(x,rect[0]);self.assertGreaterEqual(y,rect[1])
            self.assertLess(x+w,rect[2]);self.assertLess(y+h,rect[3])
    def test_negative_and_offset_monitor_coordinates(self):
        for rect in ((-1920,0,0,1040),(1920,40,4480,1440),(0,-1080,1920,-40)):
            w,h,x,y=layout.large_geometry(rect)
            window = mock.Mock()
            with mock.patch.object(layout, '_work_area', return_value=rect):
                layout.open_large_window(window)
            window.geometry.assert_called_once_with(f'{w}x{h}+{x}+{y}')
            window.resizable.assert_called_once_with(True, True)
    def test_uk_keeps_normal_window_decorations(self):
        d=self.dialog()
        self.assertFalse(str(d.window.transient()))
        self.assertFalse(d.window.overrideredirect())
        self.assertEqual(d.window.state(),'normal')
    def test_user_resize_not_reset_to_startup(self):
        d=self.dialog()
        for size in ('820x640', f'{self.expected[0]}x{self.expected[1]}', '900x700'):
            d.window.geometry(size);self.root.update()
            w,h=map(int,size.split('x'))
            self.assertEqual((d.window.winfo_width(),d.window.winfo_height()),(w,h))
    def test_default_report_is_large_and_footer_visible(self):
        d=self.dialog()
        line=int(d.log.tk.call('font','metrics',d.log.cget('font'),'-linespace'))
        if d.window.winfo_height() >= 820:
            self.assertGreaterEqual(d.log.winfo_height()-10,10*line)
        else:
            self.assertGreater(d.log.winfo_height(),40)
        bottom=d.window.winfo_rooty()+d.window.winfo_height()
        for w in (d.portal_button,d.download_button,d.cancel_button):
            self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),bottom)
        print('Large opening: %dx%d; report=%d px; text line=%d px.' %
              (d.window.winfo_width(),d.window.winfo_height(),d.log.winfo_height(),line))
    def test_helper_has_no_upper_limit_or_font_changes(self):
        source=Path(layout.__file__).read_text()
        tree=ast.parse(source)
        forbidden={'maxsize','theme_use','theme_create','configure'}
        for call in (n for n in ast.walk(tree) if isinstance(n,ast.Call)):
            if isinstance(call.func,ast.Attribute):
                self.assertNotIn(call.func.attr,forbidden)
        self.assertNotIn('tk scaling',source)
    def test_invalid_work_area_is_explicit(self):
        for rect in ((0,0,0,10),(0,0,10,0)):
            with self.assertRaises(ValueError):layout.large_geometry(rect)
    def test_display_only_no_source_or_project_file_writes(self):
        for path in (Path(layout.__file__),):
            tree=ast.parse(path.read_text())
            for call in (n for n in ast.walk(tree) if isinstance(n,ast.Call)):
                if isinstance(call.func,ast.Attribute):
                    self.assertNotIn(call.func.attr,('write_text','write_bytes','unlink','replace','remove'))
    def test_python311_syntax(self):
        for name in ('tgc_window_layout.py','uk_lidar_ui.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8-sig'),feature_version=(3,11))

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(LargeWindowTests))
    if not result.wasSuccessful():raise SystemExit(1)
