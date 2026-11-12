"""Exercise real source-scale dialog actions with headless widget doubles.

These tests validate decisions and cancellation behavior, not rendered layout.
No Tk display or application import is required.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Variable:
    def __init__(self, master=None, value=""):
        self.value = value
        self.traces = []
    def get(self):
        return self.value
    def set(self, value):
        self.value = value
        for callback in tuple(self.traces):
            callback("variable", "", "write")
    def trace_add(self, mode, callback):
        self.traces.append(callback)


class Widget:
    def __init__(self, parent=None, *args, **kwargs):
        self.parent = parent
        self.options = dict(kwargs)
        self.bindings = {}
        self.protocols = {}
        self.destroyed = False
        self.destroy_count = 0
        self.text = ""
        self._grab = None
        self.wait_action = None
    def root(self):
        node = self
        while node.parent is not None:
            node = node.parent
        return node
    def configure(self, **kwargs):
        self.options.update(kwargs)
    config = configure
    def grid(self, *args, **kwargs):
        pass
    def pack(self, *args, **kwargs):
        pass
    def columnconfigure(self, *args, **kwargs):
        pass
    def rowconfigure(self, *args, **kwargs):
        pass
    def withdraw(self):
        pass
    def deiconify(self):
        pass
    def title(self, title):
        self.options["title"] = title
    def transient(self, parent):
        self.options["transient"] = parent
    def protocol(self, name, callback):
        self.protocols[name] = callback
    def bind(self, name, callback):
        self.bindings[name] = callback
    def insert(self, index, text):
        self.text += text
    def yview(self, *args):
        pass
    def set(self, *args):
        pass
    def update_idletasks(self):
        pass
    def winfo_screenwidth(self):
        return 1280
    def winfo_screenheight(self):
        return 720
    def geometry(self, value):
        self.options["geometry"] = value
    def minsize(self, *args):
        self.options["minsize"] = args
    def grab_current(self):
        return self.root()._grab
    def grab_set(self):
        self.root()._grab = self
    def grab_release(self):
        if self.root()._grab is self:
            self.root()._grab = None
    def focus_set(self):
        pass
    def destroy(self):
        self.destroyed = True
        self.destroy_count += 1
    def wait_window(self, dialog):
        if self.wait_action:
            self.wait_action(dialog)


def load_dialog_module():
    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    tk.Toplevel = Widget
    tk.Text = Widget
    tk.StringVar = Variable
    tk.TclError = type("TclError", (Exception,), {})
    tk.ttk = ttk
    for name in ("Frame", "Label", "Scrollbar", "LabelFrame", "Radiobutton", "Entry", "Button"):
        setattr(ttk, name, Widget)
    style = types.ModuleType("tgc_ui_style")
    style.install = lambda widget: None
    path = Path(__file__).with_name("tgc_source_scale_ui.py")
    spec = importlib.util.spec_from_file_location("source_scale_dialog_test_target", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"tkinter": tk, "tkinter.ttk": ttk, "tgc_ui_style": style}):
        spec.loader.exec_module(module)
    module._test_style = style
    return module


UI = load_dialog_module()


def assessment(scale=1.0, minimum=0.0, kind="LiDAR"):
    return {"source_type": kind, "recommended_scale": scale,
            "minimum_scale": minimum, "confidence": "high",
            "summary": "Inspected source", "reason": "Measured source coverage",
            "notes": ["Terrain stamp spacing remains separate."]}


class DialogActionTests(unittest.TestCase):
    def setUp(self):
        self.root = Widget()
        style_patch = patch.dict(sys.modules, {"tgc_ui_style": UI._test_style})
        style_patch.start()
        self.addCleanup(style_patch.stop)

    def dialog(self, **kwargs):
        return UI.SourceScaleDialog(self.root, kwargs.pop("assessment", assessment()), **kwargs)

    def test_auto_default_uses_recommended_scale_and_explicit_confirmation(self):
        dialog = self.dialog(source_label="course.laz")
        self.assertEqual(dialog.mode.get(), "auto")
        self.assertEqual(dialog.entry.options["state"], "disabled")
        self.assertEqual(dialog.continue_button.options["state"], "normal")
        self.assertIsNone(dialog.result)
        dialog.accept()
        self.assertEqual(dialog.result["selected_scale"], 1.0)
        self.assertEqual(dialog.result["mode"], "auto")
        self.assertTrue(dialog.result["confirmed"])
        self.assertEqual(dialog.result["source_label"], "course.laz")
        self.assertTrue(dialog.destroyed)

    def test_existing_manual_request_is_prefilled_and_applied(self):
        dialog = self.dialog(request="2")
        self.assertEqual(dialog.mode.get(), "manual")
        self.assertEqual(float(dialog.manual.get()), 2)
        self.assertEqual(dialog.entry.options["state"], "normal")
        dialog.accept()
        self.assertEqual(dialog.result["selected_scale"], 2)
        self.assertEqual(dialog.result["mode"], "manual")

    def test_manual_override_is_per_import_and_does_not_edit_assessment(self):
        source = assessment()
        dialog = self.dialog(assessment=source)
        dialog.mode.set("manual")
        dialog.manual.set("1.5")
        dialog.accept()
        self.assertEqual(dialog.result["selected_scale"], 1.5)
        self.assertEqual(dialog.result["assessment"]["recommended_scale"], 1)
        self.assertEqual(source["recommended_scale"], 1)

    def test_invalid_manual_values_block_continue_and_enter(self):
        for value in ("", "Auto", "zero", "0", "-1", "nan", "inf", "6.5"):
            with self.subTest(value=value):
                dialog = self.dialog()
                dialog.mode.set("manual")
                dialog.manual.set(value)
                self.assertEqual(dialog.continue_button.options["state"], "disabled")
                self.assertTrue(dialog.error.get())
                dialog.accept()
                self.assertIsNone(dialog.result)
                self.assertFalse(dialog.destroyed)
                dialog.cancel()

    def test_switching_back_to_auto_clears_manual_error(self):
        dialog = self.dialog()
        dialog.mode.set("manual")
        dialog.manual.set("bad")
        self.assertTrue(dialog.error.get())
        dialog.mode.set("auto")
        dialog.refresh()
        self.assertFalse(dialog.error.get())
        self.assertEqual(dialog.entry.options["state"], "disabled")
        self.assertEqual(dialog.continue_button.options["state"], "normal")
        dialog.accept()
        self.assertEqual(dialog.result["mode"], "auto")

    def test_dem_manual_cannot_claim_finer_source_detail(self):
        dialog = self.dialog(assessment=assessment(scale=2, minimum=2, kind="DEM"))
        dialog.mode.set("manual")
        dialog.manual.set("1")
        self.assertEqual(dialog.continue_button.options["state"], "disabled")
        dialog.accept()
        self.assertIsNone(dialog.result)
        dialog.manual.set("3")
        dialog.accept()
        self.assertEqual(dialog.result["selected_scale"], 3)

    def test_exact_native_precision_survives_manual_prefill(self):
        native = 3.0 * 1200 / 3937
        dialog = self.dialog(assessment=assessment(native, native, "DEM"))
        dialog.mode.set("manual")
        dialog.refresh()
        self.assertEqual(float(dialog.manual.get()), native)
        self.assertEqual(dialog.continue_button.options["state"], "normal")
        dialog.accept()
        self.assertEqual(dialog.result["selected_scale"], native)

    def test_cancel_window_close_and_escape_produce_no_decision(self):
        for action in (lambda d: d.cancel(), lambda d: d.protocols["WM_DELETE_WINDOW"](),
                       lambda d: d.bindings["<Escape>"](None)):
            dialog = self.dialog()
            action(dialog)
            self.assertIsNone(dialog.result)
            self.assertTrue(dialog.destroyed)
            self.assertIsNone(self.root.grab_current())

    def test_nested_modal_restores_previous_grab(self):
        previous = Widget(self.root)
        previous.grab_set()
        dialog = self.dialog()
        self.assertIs(self.root.grab_current(), dialog)
        dialog.cancel()
        self.assertIs(self.root.grab_current(), previous)

    def test_repeated_keyboard_or_button_actions_cannot_replace_confirmation(self):
        dialog = self.dialog()
        self.assertEqual(dialog.bindings["<Return>"](None), "break")
        result = dialog.result
        dialog.accept()
        dialog.cancel()
        self.assertIs(dialog.result, result)
        self.assertEqual(dialog.destroy_count, 1)
        cancelled = self.dialog()
        self.assertEqual(cancelled.bindings["<Escape>"](None), "break")
        cancelled.accept()
        self.assertIsNone(cancelled.result)
        self.assertEqual(cancelled.destroy_count, 1)

    def test_trees_decision_is_marked_without_changing_existing_dem_grid(self):
        dialog = self.dialog(operation="trees")
        dialog.accept()
        self.assertEqual(dialog.result["operation"], "trees")
        self.assertEqual(dialog.options["title"], "Confirm LiDAR Tree Scale")

    def test_gap_fill_keeps_fixed_existing_grid(self):
        fixed = 1.5
        dialog = self.dialog(assessment=assessment(fixed, fixed, "Existing heightmap"),
                             operation="gap_fill", fixed_scale=fixed)
        self.assertIsNone(dialog.entry)
        dialog.mode.set("manual")
        dialog.manual.set("4")
        dialog.accept()
        self.assertEqual(dialog.result["selected_scale"], fixed)
        self.assertEqual(dialog.result["mode"], "existing_grid")
        self.assertEqual(dialog.result["operation"], "gap_fill")

    def test_public_wrapper_waits_for_user_action_and_returns_it(self):
        self.root.wait_action = lambda dialog: dialog.accept()
        result = UI.confirm_source_scale(self.root, assessment(), request="Auto")
        self.assertTrue(result["confirmed"])
        self.root.wait_action = lambda dialog: dialog.cancel()
        self.assertIsNone(UI.confirm_source_scale(self.root, assessment()))

    def test_gap_fill_wrapper_rejects_invalid_stored_scale(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                UI.confirm_existing_grid(self.root, value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
