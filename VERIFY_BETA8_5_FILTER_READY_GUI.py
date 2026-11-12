#!/usr/bin/env python3
"""Focused, display-free checks of the actual Filter Ready GUI source.

Usage: python VERIFY_BETA8_5_FILTER_READY_GUI.py [--source /path/to/tgc_gui.py]
The GUI functions and theme controls are compiled directly from their AST;
Tk widgets, dialogs, and pack operations are stubs, so no course is written.
"""
import argparse
import ast
import copy
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest


def find_source():
    """Use the installed sibling without assuming any parent-folder depth."""
    return Path(__file__).resolve().with_name("tgc_gui.py")


parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path,
                    help="GUI source to verify; defaults to tgc_gui.py beside this verifier")
args = parser.parse_args()
SOURCE_PATH = (args.source if args.source is not None else find_source()).resolve()
if not SOURCE_PATH.is_file():
    parser.error("GUI source was not found: %s. Keep this verifier beside tgc_gui.py "
                 "or pass --source with its full path." % SOURCE_PATH)
try:
    SOURCE_BYTES = SOURCE_PATH.read_bytes()
except OSError as exc:
    parser.error("Could not read GUI source %s: %s" % (SOURCE_PATH, exc))
SOURCE = SOURCE_BYTES.decode("utf-8-sig")
TREE = ast.parse(SOURCE, filename=str(SOURCE_PATH))
FUNCTIONS = {node.name: node for node in TREE.body if isinstance(node, ast.FunctionDef)}


class Variable:
    def __init__(self, value=""):
        self.value = value
        self.callbacks = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in self.callbacks:
            callback("var", "", "write")

    def trace_add(self, mode, callback):
        assert mode == "write"
        self.callbacks.append(callback)


class Widget:
    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.config = kwargs
        self.grid_options = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)

    def grid(self, **kwargs):
        self.grid_options = kwargs


def compile_nodes(nodes, env):
    module = ast.Module(body=copy.deepcopy(nodes), type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE_PATH), "exec"), env)


def theme_ui_nodes():
    start = next(n.lineno for n in TREE.body
                 if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "tree_profile_var"
                         for t in n.targets))
    end = next(n.lineno for n in TREE.body
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "tree_scale_mode_var"
                       for t in n.targets))
    return [n for n in TREE.body if start <= n.lineno < end]


class GUIControlsTests(unittest.TestCase):
    def setUp(self):
        self.statuses = {
            "Designer Theme": {"available": False, "asset_count": 0,
                               "message": "Select a theme with a source catalog."},
            "Alpine Conifer": {"available": True, "asset_count": 72,
                               "message": "72 nature assets on export"},
            "Pine Woodlands": {"available": True, "asset_count": 90, "message": ""},
            "Older Theme": {"available": False, "asset_count": 0, "message": ""},
        }
        self.env = {
            "options_entries_dict": {}, "courseSubFrame": object(),
            "check_fg": "black", "check_bg": "white", "W": "w", "LEFT": "left",
            "Frame": Widget, "Checkbutton": Widget, "Label": Widget,
            "tk": SimpleNamespace(StringVar=Variable, BooleanVar=Variable),
            "ttk": SimpleNamespace(Combobox=Widget),
            "tree_profile_manager": SimpleNamespace(
                DESIGNER_THEME_LABEL="Designer Theme",
                get_profile_choices=lambda: list(self.statuses)),
            "tgc_theme_filter_ready": SimpleNamespace(
                catalog_status=lambda choice: self.statuses[choice]),
        }
        compile_nodes([FUNCTIONS["refreshThemeFilterReadyControls"]], self.env)
        compile_nodes(theme_ui_nodes(), self.env)

    def test_default_off_and_adjacent_checkbox(self):
        env = self.env
        self.assertIs(env["options_entries_dict"]["theme_filter_ready"].get(), False)
        self.assertEqual(env["themeFilterReadyCheck"].config["state"], "disabled")
        self.assertEqual(env["themeFilterReadyCheck"].config["text"], "Filter Ready")
        self.assertIs(env["treeProfileCombo"].parent, env["treeProfileControlsFrame"])
        self.assertIs(env["themeFilterReadyCheck"].parent, env["treeProfileControlsFrame"])
        self.assertEqual(env["treeProfileCombo"].grid_options["row"], 0)
        self.assertEqual(env["themeFilterReadyCheck"].grid_options["row"], 0)
        self.assertEqual(env["treeProfileCombo"].grid_options["column"], 0)
        self.assertEqual(env["themeFilterReadyCheck"].grid_options["column"], 1)
        grid_nodes = [n for n in TREE.body if isinstance(n, ast.Expr)
                      and isinstance(n.value, ast.Call)
                      and isinstance(n.value.func, ast.Attribute)
                      and isinstance(n.value.func.value, ast.Name)
                      and n.value.func.value.id == "treeProfileControlsFrame"
                      and n.value.func.attr == "grid"]
        self.assertEqual(len(grid_nodes), 1)
        compile_nodes(grid_nodes, env)
        self.assertEqual(env["treeProfileControlsFrame"].grid_options["row"], 6)
        self.assertEqual(env["treeProfileControlsFrame"].grid_options["column"], 1)

    def test_available_catalog_and_fallback_count(self):
        env = self.env
        env["tree_profile_var"].set("Alpine Conifer")
        self.assertEqual(env["themeFilterReadyCheck"].config["state"], "normal")
        self.assertEqual(env["theme_filter_ready_status_var"].get(), "72 nature assets on export")
        env["options_entries_dict"]["theme_filter_ready"].set(True)
        env["tree_profile_var"].set("Pine Woodlands")
        self.assertTrue(env["options_entries_dict"]["theme_filter_ready"].get())
        self.assertEqual(env["theme_filter_ready_status_var"].get(), "90 nature assets on export")

    def test_unavailable_catalog_clears_enabled_choice(self):
        env = self.env
        env["tree_profile_var"].set("Alpine Conifer")
        env["options_entries_dict"]["theme_filter_ready"].set(True)
        env["tree_profile_var"].set("Older Theme")
        self.assertFalse(env["options_entries_dict"]["theme_filter_ready"].get())
        self.assertEqual(env["themeFilterReadyCheck"].config["state"], "disabled")
        self.assertEqual(env["theme_filter_ready_status_var"].get(),
                         "Source catalog not yet available for this theme.")

    def test_catalog_error_is_inline_and_disabled(self):
        env = self.env
        env["tree_profile_var"].set("Unknown")
        self.assertEqual(env["themeFilterReadyCheck"].config["state"], "disabled")
        self.assertIn("Filter Ready unavailable:", env["theme_filter_ready_status_var"].get())
        self.assertFalse(env["options_entries_dict"]["theme_filter_ready"].get())

    def test_existing_snapshot_loops_keep_option(self):
        env = self.env
        env["tree_profile_var"].set("Alpine Conifer")
        env["options_entries_dict"]["theme_filter_ready"].set(True)
        for name in ("generateCourseFromLidar", "importOSMFile"):
            loops = [n for n in ast.walk(FUNCTIONS[name])
                     if isinstance(n, ast.For)
                     and isinstance(n.iter, ast.Call)
                     and isinstance(n.iter.func, ast.Attribute)
                     and isinstance(n.iter.func.value, ast.Name)
                     and n.iter.func.value.id == "options_entries_dict"
                     and n.iter.func.attr == "items"]
            self.assertEqual(len(loops), 1, name)
            env["options_dict"] = {}
            compile_nodes(loops, env)
            self.assertIs(env["options_dict"]["theme_filter_ready"], True, name)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.alerts = []
        self.logs = []
        self.packs = []
        self.helper_calls = []
        self.previews = []
        self.destination = "/output/course.course"
        self.material_error = False
        self.helper_error = False
        self.initial_course = {"version": 49, "name": "Old name",
                               "useV43AltSurfaceSplineScale": True, "holes3": [],
                               "objects": [{"id": "existing"}]}

        def material_preset(value, choice, printf, metadata=False):
            self.events.append("material_metadata" if metadata else "material_course")
            if self.material_error:
                raise ValueError("material failure")
            result = copy.deepcopy(value)
            result["material_choice"] = choice
            return result

        def helper(value, choice, enabled, course_version, printf):
            self.events.append("helper")
            self.helper_calls.append((value, choice, enabled, course_version))
            if self.helper_error:
                raise ValueError("catalog failure")
            if not enabled:
                return value
            result = copy.deepcopy(value)
            result["objects"].append({"id": "filter_helper"})
            return result

        def pack(*positional, **keywords):
            self.events.append("pack")
            self.packs.append((positional, keywords))

        def preview(value):
            self.events.append("preview")
            self.previews.append(value)

        self.env = {
            "root": SimpleNamespace(filename="/project"),
            "course_json": self.initial_course,
            "course_version": 25,
            "course_name_var": Variable("New name"), "course_types": [],
            "options_entries_dict": {"tree_profile": Variable("Alpine Conifer"),
                                     "theme_filter_ready": Variable(True)},
            "alert": self.alerts.append,
            "print": lambda *items, **kwargs: self.logs.append(" ".join(map(str, items))),
            "drawPlaceholder": lambda: self.events.append("placeholder"),
            "drawCourse": preview,
            "tk": SimpleNamespace(filedialog=SimpleNamespace(
                asksaveasfilename=lambda **kwargs: self.destination)),
            "tgc_tools": SimpleNamespace(
                set_course_metadata_name=lambda *a: self.events.append("name_metadata"),
                get_metadata_json=lambda *a: {"name": "New name", "theme": 0},
                write_metadata_json=lambda *a: self.events.append("metadata_write"),
                pack_course_file=pack),
            "tree_profile_manager": SimpleNamespace(apply_visual_material_preset=material_preset),
            "tgc_theme_filter_ready": SimpleNamespace(apply_filter_ready=helper),
        }
        compile_nodes([FUNCTIONS["exportCourseAction"], FUNCTIONS["getCourseVersion"]], self.env)

    def export(self):
        self.env["exportCourseAction"]()

    def test_export_copy_after_materials_working_course_clean(self):
        self.export()
        self.assertEqual(self.events, ["name_metadata", "material_course", "material_metadata",
                                      "metadata_write", "helper", "placeholder", "pack", "preview"])
        working = self.env["course_json"]
        positional, keywords = self.packs[0]
        exported = keywords["export_course_json"]
        self.assertIs(positional[3], working)
        self.assertIsNot(exported, working)
        self.assertIs(self.previews[0], working)
        self.assertIs(self.helper_calls[0][0], working)
        self.assertEqual(working["objects"], [{"id": "existing"}])
        self.assertEqual(exported["objects"], [{"id": "existing"}, {"id": "filter_helper"}])
        self.assertEqual(exported["material_choice"], "Alpine Conifer")
        self.assertEqual(self.helper_calls[0][1:], ("Alpine Conifer", True, 25))
        self.assertEqual(positional[4], 25)
        self.assertEqual(working["name"], "New name")
        self.assertFalse(self.alerts)

    def test_repeated_export_and_theme_change_do_not_accumulate(self):
        self.export()
        self.env["options_entries_dict"]["tree_profile"].set("Pine Woodlands")
        self.export()
        for _, keywords in self.packs:
            self.assertEqual(len(keywords["export_course_json"]["objects"]), 2)
        self.assertEqual(self.env["course_json"]["objects"], [{"id": "existing"}])
        self.assertEqual(self.helper_calls[-1][1], "Pine Woodlands")

    def test_off_and_missing_option_still_call_helper(self):
        for missing in (False, True):
            if missing:
                del self.env["options_entries_dict"]["theme_filter_ready"]
            else:
                self.env["options_entries_dict"]["theme_filter_ready"].set(False)
            self.export()
            self.assertIs(self.helper_calls[-1][2], False)
            positional, keywords = self.packs[-1]
            self.assertIs(positional[3], keywords["export_course_json"])

    def test_helper_failure_stops_export(self):
        self.helper_error = True
        self.export()
        self.assertFalse(self.packs)
        self.assertFalse(self.previews)
        self.assertNotIn("placeholder", self.events)
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("Export stopped: Filter Ready", self.alerts[0])
        self.assertIn("catalog failure", self.alerts[0])

    def test_helper_failure_not_swallowed_by_material_warning(self):
        self.material_error = True
        self.helper_error = True
        self.export()
        self.assertIn("helper", self.events)
        self.assertTrue(any("could not sync regional theme" in s for s in self.logs))
        self.assertFalse(self.packs)
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("catalog failure", self.alerts[0])

    def test_save_cancel_skips_mutation_and_helper(self):
        self.destination = ""
        before = copy.deepcopy(self.env["course_json"])
        self.export()
        self.assertEqual(self.env["course_json"], before)
        self.assertFalse(self.events)
        self.assertFalse(self.alerts)

    def test_missing_course_and_root_guards(self):
        self.env["course_json"] = None
        self.export()
        self.assertIn("import a .course", self.alerts[-1])
        self.env["course_json"] = self.initial_course
        self.env["root"] = None
        self.export()
        self.assertIn("course directory", self.alerts[-1])
        self.assertFalse(self.events)

    def test_normalized_versions_not_raw_serialized_versions(self):
        get_version = self.env["getCourseVersion"]
        self.assertEqual(get_version(self.initial_course), 25)
        self.assertEqual(get_version({"version": 43, "useV30Rough": True, "holes2": []}), 23)
        self.assertEqual(get_version({"version": 32, "useV19DetailPlacement": True, "holes": []}), 19)
        self.assertEqual(get_version({"version": 49}), -1)


if __name__ == "__main__":
    compile(SOURCE, str(SOURCE_PATH), "exec")
    print("GUI source:", SOURCE_PATH)
    print("SHA256:", hashlib.sha256(SOURCE_BYTES).hexdigest())
    print("Checks execute actual GUI AST with widget/export stubs; no Tk display or Windows executable.")
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(GUIControlsTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(ExportTests),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
