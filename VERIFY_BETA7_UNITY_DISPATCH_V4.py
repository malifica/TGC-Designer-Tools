"""Verify Unity alongside an existing Beta 7 startup dispatcher.

These tests execute the actual dispatch structure with controlled verifier/GUI
modules. They prove routing and preservation contracts, not the underlying
Local Alignment engine or the Windows executable.
"""
from pathlib import Path
import ast
import importlib.util
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / 'tgc_tree_size_test1_entry.py'
BUILD = ROOT / 'BUILD_TGC_2K25_BETA7.py'


def same(node, expression):
    return ast.dump(node, include_attributes=False) == ast.dump(ast.parse(expression, mode='eval').body, include_attributes=False)


def branches(node):
    while isinstance(node, ast.If):
        yield node
        node = node.orelse[0] if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) else None


def dispatch_tree():
    tree = ast.parse(ENTRY.read_text(encoding='utf-8-sig'))
    # Keep the actual top-level dispatcher(s); replace only the heavy tree verifier.
    tree.body = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return ast.fix_missing_locations(tree)


def exercise(flag=None, unity_error=False):
    calls = []
    unity = types.ModuleType('tgc_unity_build_check')
    def verify():
        calls.append('unity')
        if unity_error:
            raise RuntimeError('expected verifier failure')
    unity.verify = verify
    local = types.ModuleType('tgc_local_alignment')
    local.self_check = lambda: calls.append('local') or {'fixture': True}
    gui = types.ModuleType('tgc_gui')
    original_import = __import__
    def traced_import(name, *args, **kwargs):
        if name == 'tgc_gui':
            calls.append('gui')
        return original_import(name, *args, **kwargs)
    env = {'__name__': '__main__', 'verify_frozen_tree_sizes': lambda: calls.append('trees')}
    with patch.dict(sys.modules, {'tgc_unity_build_check': unity, 'tgc_local_alignment': local, 'tgc_gui': gui}), \
         patch.object(sys, 'argv', ['app'] + ([flag] if flag else [])), \
         patch('builtins.__import__', side_effect=traced_import), contextlib.redirect_stdout(io.StringIO()):
        try:
            exec(compile(dispatch_tree(), str(ENTRY), 'exec'), env)
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise
    return calls


class DispatchV4Tests(unittest.TestCase):
    def test_python311_syntax(self):
        ast.parse(ENTRY.read_text(encoding='utf-8-sig'), feature_version=(3, 11))
        ast.parse(BUILD.read_text(encoding='utf-8-sig'), feature_version=(3, 11))

    def test_single_unity_dispatch(self):
        checks = [n for n in ast.walk(dispatch_tree()) if isinstance(n, ast.If)
                  and same(n.test, "'--verify-unity-import' in sys.argv")]
        self.assertEqual(len(checks), 1)

    def test_unity_runs_without_gui(self):
        self.assertEqual(exercise('--verify-unity-import'), ['unity'])

    def test_unity_failure_propagates(self):
        with self.assertRaisesRegex(RuntimeError, 'expected verifier failure'):
            exercise('--verify-unity-import', unity_error=True)

    def test_existing_tree_dispatch_runs(self):
        self.assertEqual(exercise('--verify-lidar-trees'), ['trees'])

    def test_regular_gui_launch_runs(self):
        self.assertEqual(exercise(), ['gui'])

    def test_unknown_flag_keeps_gui_fallback(self):
        self.assertEqual(exercise('--unrelated-test-flag'), ['gui'])

    def test_local_alignment_dispatch_when_present(self):
        checks = [n for n in ast.walk(dispatch_tree()) if isinstance(n, ast.If)
                  and same(n.test, "'--verify-local-alignment' in sys.argv")]
        if not checks:
            self.skipTest('This older source has no Local Alignment branch.')
        self.assertEqual(len(checks), 1)
        self.assertEqual(exercise('--verify-local-alignment'), ['local'])

    def test_local_alignment_build_hooks_when_present(self):
        entry = ENTRY.read_text(encoding='utf-8-sig')
        if '--verify-local-alignment' not in entry:
            self.skipTest('This older source has no Local Alignment integration.')
        tree = ast.parse(BUILD.read_text(encoding='utf-8-sig'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        for expression in ("run(py,root/'tgc_tree_size_test1_entry.py','--verify-local-alignment')",
                           "run(built,'--verify-local-alignment')"):
            self.assertEqual(sum(same(n, expression) for n in calls), 1, expression)
        for name in ('VERIFY_BETA7_LOCAL_ALIGNMENT_ENGINE.py', 'VERIFY_BETA7_LOCAL_ALIGNMENT.py', 'VERIFY_BETA7_LOCAL_MANUAL.py'):
            self.assertTrue(any(same(n, 'run(py,root/'+repr(name)+')') for n in calls), name)

    def test_local_alignment_modules_retained_when_present(self):
        if '--verify-local-alignment' not in ENTRY.read_text(encoding='utf-8-sig'):
            self.skipTest('This older source has no Local Alignment integration.')
        spec = importlib.util.spec_from_file_location('_unity_v4_build_test', BUILD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = list(map(str, module.build_arguments('python', ROOT, ROOT/'test-stage')))
        hidden = [args[i+1] for i, a in enumerate(args[:-1]) if a == '--hidden-import']
        hidden += [a.split('=', 1)[1] for a in args if a.startswith('--hidden-import=')]
        for name in ('tgc_local_alignment', 'tgc_local_alignment_detector', 'tgc_local_alignment_export', 'tgc_local_alignment_ui', 'tgc_cfs_widgets'):
            self.assertIn(name, hidden)
        self.assertTrue(any(a == '--collect-all' and args[i+1] == 'shapely' for i, a in enumerate(args[:-1])))


if __name__ == '__main__':
    unittest.main(verbosity=2)
