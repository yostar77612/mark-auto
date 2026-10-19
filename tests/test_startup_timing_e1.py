"""Cheap startup timing, privacy and offscreen B12 display contracts."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from desktop_pages.diagnostics import DiagnosticsPanel, snapshot_for_state
from desktop_strings import ui_text
from quantlab.diagnostics import MAX_BYTES, build_diagnostics
from quantlab.errors import ERROR_TABLE
from quantlab.startup_timing import MAX_STAGES, STAGES, TRUNCATION_MARKER, StartupTiming

ROOT = Path(__file__).resolve().parents[1]


class StartupTimingTests(unittest.TestCase):
    def test_exact_intervals_and_one_clock_read_per_mark(self):
        clock = Mock(side_effect=[100.0, 100.25, 102.0, 105.5, 106.0, 106.125])
        timing = StartupTiming(clock)
        names = ('application', 'bootstrap', 'workspace', 'window', 'ready')
        for name in names:
            timing.mark(name)
        self.assertEqual(
            timing.snapshot(),
            {'stages': [dict(stage=name, duration_seconds=duration) for name, duration in zip(names, (0.25, 1.75, 3.5, 0.5, 0.125))]},
        )
        self.assertEqual(clock.call_count, 1 + len(names))
        timing.snapshot()
        self.assertEqual(clock.call_count, 1 + len(names))

    def test_invalid_names_are_never_echoed_or_stringified(self):
        class Private:
            def __str__(self):
                raise AssertionError('must not stringify')

            __repr__ = __str__

        timing = StartupTiming(lambda: 0.0)
        secrets = ('C:/Users/Mark/private', '/home/private-user', 'Bearer secret-token', 'PASSWORD=private', 'cookie=secret', 'ready\nprivate')
        for name in (*secrets, None, [], {}, 42, Private()):
            with self.assertRaises(ValueError) as caught:
                timing.mark(name)
            self.assertEqual(str(caught.exception), 'Unknown startup stage')
        text = build_diagnostics(startup_timing=timing)
        for secret in secrets:
            self.assertNotIn(secret, text)
        self.assertEqual(timing.snapshot(), {'stages': []})
        self.assertEqual(json.loads(build_diagnostics(startup_timing={'stages': list(secrets)}))['startup_timing'], 'unavailable')

    def test_cap_marker_nonnegative_finite_and_detached_snapshot(self):
        clock = Mock(side_effect=[10.0, 9.0, float('nan'), float('inf'), 10.0, 11.0, 12.0, 13.0, 14.0])
        timing = StartupTiming(clock)
        for _ in range(MAX_STAGES + 20):
            timing.mark('ready')
        value = timing.snapshot()
        self.assertEqual(len(value['stages']), MAX_STAGES)
        self.assertEqual(value['truncation'], TRUNCATION_MARKER)
        self.assertEqual(clock.call_count, MAX_STAGES + 1)
        self.assertTrue(all(row['duration_seconds'] >= 0 for row in value['stages']))
        json.dumps(value, allow_nan=False)
        value['stages'][0]['stage'] = 'private'
        value['stages'].clear()
        self.assertEqual(len(timing.snapshot()['stages']), MAX_STAGES)
        self.assertEqual(timing.snapshot()['stages'][0]['stage'], 'ready')

    def test_memory_only_no_open_path_write_network_or_clock_on_import(self):
        # Reload only this pure module to exercise its import boundary.
        from importlib import reload

        import quantlab.startup_timing as module

        with (
            patch.dict(module.__dict__),
            patch('builtins.open', side_effect=AssertionError('open forbidden')),
            patch.object(Path, 'open', side_effect=AssertionError('path open forbidden')),
            patch.object(Path, 'write_text', side_effect=AssertionError('write forbidden')),
            patch.object(Path, 'write_bytes', side_effect=AssertionError('write forbidden')),
            patch('socket.socket', side_effect=AssertionError('network forbidden')),
            patch('time.monotonic', side_effect=AssertionError('import clock forbidden')),
        ):
            reload(module)
            timing = module.StartupTiming(lambda: 1.0)
            timing.mark('ready')
            self.assertEqual(module.timing_snapshot(timing)['stages'][0]['duration_seconds'], 0)

    def test_b12_byte_cap_keeps_whole_entries_and_timing(self):
        timing = StartupTiming(lambda: 1.0)
        for _ in range(MAX_STAGES + 1):
            timing.mark('window')
        errors = [{'error_code': code} for code in ERROR_TABLE] * 10
        text = build_diagnostics(startup_timing=timing, errors=errors)
        self.assertLessEqual(len(text.encode('utf-8')), MAX_BYTES)
        value = json.loads(text)
        self.assertEqual(value['startup_timing'], timing.snapshot())
        self.assertEqual(value['truncation'], TRUNCATION_MARKER)
        self.assertLess(len(value['last_errors']), len(errors))
        for row in value['last_errors']:
            self.assertEqual(row, {'error_code': row['error_code'], 'explanation': ERROR_TABLE[row['error_code']].explanation})
        self.assertEqual(value['last_errors'][0]['error_code'], errors[-1]['error_code'])

        # Exercise whole timing-entry removal without changing the production cap.
        with patch('quantlab.diagnostics.MAX_BYTES', 900):
            compact = build_diagnostics(startup_timing=timing, errors=errors)
        self.assertLessEqual(len(compact.encode('utf-8')), 900)
        compact_value = json.loads(compact)
        self.assertEqual(compact_value['last_errors'], [])
        self.assertEqual(compact_value['startup_timing']['truncation'], TRUNCATION_MARKER)
        self.assertLess(len(compact_value['startup_timing']['stages']), MAX_STAGES)
        self.assertEqual(compact_value['startup_timing']['stages'], timing.snapshot()['stages'][: len(compact_value['startup_timing']['stages'])])
        self.assertEqual(len(timing.snapshot()['stages']), MAX_STAGES)

    def test_offscreen_snapshot_and_copy_include_identical_timing(self):
        app = QApplication.instance() or QApplication([])
        timing = StartupTiming(Mock(side_effect=[1.0, 1.5]))
        timing.mark('ready')
        panel = DiagnosticsPanel(lambda: snapshot_for_state(SimpleNamespace(startup_timing=timing)))
        try:
            panel.refresh_button.click()
            text = panel.output.toPlainText()
            self.assertEqual(json.loads(text)['startup_timing']['stages'], [{'stage': 'ready', 'duration_seconds': 0.5}])
            panel.copy_button.click()
            self.assertEqual(app.clipboard().text(), panel.output.toPlainText())
            self.assertEqual(panel.text, text)
            self.assertEqual(panel.toolTip(), ui_text('diagnostics.startup_timing_hint'))
            self.assertFalse(panel.isVisible())
        finally:
            panel.close()
            panel.deleteLater()

    def test_desktop_marks_are_literal_allowlisted_and_after_existing_imports(self):
        tree = ast.parse((ROOT / 'desktop.py').read_text(encoding='utf-8'))
        gui = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_gui')
        marks = [
            node
            for node in ast.walk(gui)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'mark'
            and ast.unparse(node.func.value) == 'state.startup_timing'
        ]
        self.assertEqual(
            [node.args[0].value for node in sorted(marks, key=lambda node: node.lineno)], ['application', 'bootstrap', 'workspace', 'window', 'ready']
        )
        self.assertTrue(all(type(node.args[0]) is ast.Constant and node.args[0].value in STAGES for node in marks))
        timing_import = next(node for node in gui.body if isinstance(node, ast.ImportFrom) and node.module == 'quantlab.startup_timing')
        runtime_import = next(node for node in gui.body if isinstance(node, ast.ImportFrom) and node.module == 'quantlab.desktop_runtime')
        self.assertGreater(timing_import.lineno, runtime_import.lineno)


if __name__ == '__main__':
    unittest.main()
