"""Cheap offline arithmetic and preview projection checks; no process timing."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from desktop_app.features.walk_forward.wf_wizard import WalkForwardWizard, duration_estimate_text
from desktop_app.strings.catalog import ui_text
from quantlab.wf_estimate import MEASURED_EVALUATION_SECONDS, estimated_seconds

ROOT = Path(__file__).resolve().parents[1]


class EstimateTests(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(estimated_seconds(33, 0.25), 8.25)

    def test_missing_measurement(self):
        self.assertIsNone(estimated_seconds(33, None))
        self.assertEqual(duration_estimate_text(33, None), ui_text('wf.duration_unknown'))
        self.assertGreater(MEASURED_EVALUATION_SECONDS, 0)

    def test_zero_and_invalid(self):
        for count in (0, -1, None, True, 1.5, '33'):
            self.assertIsNone(estimated_seconds(count, 1))
            self.assertEqual(duration_estimate_text(count, 1), '')
        for measurement in (0, -1, True, '1', float('inf'), float('nan')):
            self.assertIsNone(estimated_seconds(33, measurement))
        self.assertIsNone(estimated_seconds(10**400, 1.0))

    def test_measured_text_is_explicitly_an_estimate(self):
        self.assertEqual(duration_estimate_text(4, 0.25), ui_text('wf.duration_estimate').format('1'))
        self.assertIn('預估', duration_estimate_text(4, 0.25))
        self.assertIn('保守估計', duration_estimate_text(4))

    def test_preview_label_receives_estimate_without_changing_result(self):
        wizard = SimpleNamespace(timeline=Mock(), summary=Mock(), preview_summary=Mock(), sync_consent=Mock())
        result = {
            'folds': [{'index': 0, 'train': {'start': 0, 'end': 10}, 'validation': {'start': 10, 'end': 15}, 'oos': {'start': 15, 'end': 20}}],
            'final_holdout': {'start': 20, 'end': 30},
            'candidate_count': 5,
            'planned_evaluations_upper_bound': 11,
        }
        WalkForwardWizard.show_preview(wizard, result)
        self.assertIn('保守估計', wizard.preview_summary.setText.call_args.args[0])
        self.assertEqual(result['planned_evaluations_upper_bound'], 11)
        result['planned_evaluations_upper_bound'] = 0
        WalkForwardWizard.show_preview(wizard, result)
        self.assertNotIn('保守估計', wizard.preview_summary.setText.call_args.args[0])


class WorkerImportTests(unittest.TestCase):
    def test_static_worker_graph_has_no_qt_even_in_lazy_imports(self):
        # Follow every quantlab import (including function-local imports), with
        # package initializers and external roots. No interpreter/worker launch.
        pending, seen = ['quantlab.desktop_runtime'], set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            self.assertFalse(name.startswith(('PySide6', 'desktop_app.shell.main_window', 'desktop_app.shell.pages')), name)
            path = ROOT / (name.replace('.', '/') + '.py')
            if not path.is_file():
                continue
            if name.startswith('quantlab.'):
                pending.append('quantlab.__init__')
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node, ast.Import):
                    pending.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    prefix = name.rsplit('.', node.level)[0] + '.' if node.level else ''
                    pending.extend([prefix + node.module] if node.module else [prefix + alias.name for alias in node.names])
        self.assertIn('quantlab.runtime_support', seen)


if __name__ == '__main__':
    unittest.main()
