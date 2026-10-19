"""Cheap live-window coverage of default inputs and visible domain vocabulary."""

import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QScrollArea, QWidget
import desktop_ui
from desktop_strings import ui_text
from desktop_ui import MainWindow
from quantlab.desktop_runtime import AppPaths
from tests.test_t9_onboarding import sandbox_ui
from tests.snapshot_cache import default_metrics
from tools.ui_snapshot import _input_widgets

ROOT = Path(__file__).resolve().parents[1]


def coverage_policy():
    document = (ROOT / 'docs/analysis/t16_final_targets.md').read_text(encoding='utf-8')
    return json.loads(document.split('<!-- t16-input-policy -->\n```json\n', 1)[1].split('\n```', 1)[0])


class TooltipCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        context = sandbox_ui()
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        network = patch('socket.socket', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        folder = tempfile.TemporaryDirectory(prefix='t16-tooltips-')
        self.addCleanup(folder.cleanup)
        paths = AppPaths(Path(folder.name) / 'workspace').ensure()
        jobs = SimpleNamespace(active=False, poll=lambda: [], start=Mock(), close=Mock())
        self.window = MainWindow(paths, jobs)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
        for timer in self.window.findChildren(QTimer):
            timer.stop()
        self.window.resize(1366, 768)
        self.window.show()
        self.app.processEvents()

    def pages(self):
        for index in range(self.window.stack.count()):
            self.window.navigation.setCurrentRow(index)
            self.app.processEvents()
            page = self.window.stack.widget(index)
            yield index, page.widget() if isinstance(page, QScrollArea) else page

    def test_every_default_input_has_tooltip_or_explicit_obvious_label(self):
        policy = coverage_policy()
        obvious = {ui_text(key): key for key in policy['obvious_controls']}
        seen = set()
        counts = []
        missing = []
        for index, page in self.pages():
            inputs = _input_widgets(page)
            counts.append(len(inputs))
            for widget in inputs:
                if widget.toolTip().strip():
                    continue
                if isinstance(widget, QCheckBox) and widget.text() in obvious:
                    seen.add(obvious[widget.text()])
                else:
                    missing.append((index, widget.objectName(), widget.accessibleName()))
        self.assertEqual(counts, [8, 7, 6, 1, 9, 4, 6])
        self.assertEqual(missing, [], 'Non-obvious inputs without tooltips')
        self.assertEqual(seen, set(policy['obvious_controls']), 'Remove stale or overly broad exceptions')
        self.assertTrue(all(policy['obvious_controls'].values()))

    def test_other_strategy_families_keep_tooltips_after_rebuilding_fields(self):
        form = self.window.strategy_form
        for index in range(form.family.count()):
            form.family.setCurrentIndex(index)
            for key, field in form.fields.items():
                self.assertTrue(field.toolTip().strip(), (index, key))
            payload = form.build_payload()
            form.from_payload(payload)
            self.assertEqual(form.build_payload(), payload)
            self.assertTrue(all(field.toolTip().strip() for field in form.fields.values()))

    def test_default_text_has_only_allowlisted_domain_tokens_and_no_hashes(self):
        # Shared metrics-only capture: rasterising or re-measuring pages is slow on CI hosts.
        tokens = set()
        for metrics in default_metrics()['pages'].values():
            text = '\n'.join(metrics['visible_text'] + metrics['combo_items'] + metrics['table_headers'])
            tokens.update(re.findall(r'\b[A-Z][A-Z_]{2,}\b', text))
            self.assertNotRegex(text, r'\b[a-f0-9]{32,}\b')
        self.assertEqual(tokens, set(coverage_policy()['domain_terms']))

    def test_presentation_geometry_and_default_visible_text_match_part_b(self):
        names = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        widgets = [self.window, *self.window.findChildren(QWidget)]
        self.assertEqual(sorted({widget.objectName() for widget in widgets if widget.objectName()}), names)
        public_names = json.loads((ROOT / 'tests/fixtures/desktop_ui_public_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in vars(desktop_ui) if not name.startswith('_')), public_names)
        baseline = json.loads((ROOT / 'tests/fixtures/desktop_pages_before/metrics.json').read_text(encoding='utf-8'))
        actual_pages = default_metrics()['pages']
        self.assertEqual(set(actual_pages), set(baseline['pages']))
        for name, expected in baseline['pages'].items():
            for key in ('visible_input_count', 'label_char_count', 'visible_text', 'combo_items', 'table_headers', 'unlabeled_inputs'):
                self.assertEqual(actual_pages[name][key], expected[key], (name, key))


if __name__ == '__main__':
    unittest.main()
