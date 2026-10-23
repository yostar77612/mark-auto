"""Live copy budgets, required task disclosures and preserved help access."""

import json
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QLabel, QToolButton, QWidget
from desktop_strings import ui_text
from tests import test_t9_onboarding as onboarding
from tests.snapshot_cache import default_metrics

ROOT = Path(__file__).resolve().parents[1]


class HelpReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with onboarding.sandbox_ui(), tempfile.TemporaryDirectory(prefix='t9-help-snapshot-'):
            cls.metrics = default_metrics()

    def test_live_label_budgets_and_task_layouts(self):
        baseline = json.loads((ROOT / 'docs/analysis/t9_label_baseline.json').read_text(encoding='utf-8'))
        for name, page in self.metrics['pages'].items():
            limits = baseline['pages'][name]
            self.assertLessEqual(page['label_char_count'], limits['merged_t8'], name)
            if limits.get('half_required'):
                explanatory_chars = page['label_char_count']
                if name == ui_text('ui.data_page.title'):
                    # The redesigned import task adds a workflow and an explicit
                    # mandatory-calendar disclosure. Keep both exactly once;
                    # the historical half budget still caps every other label,
                    # while the unchanged total cap above catches new clutter.
                    for key in ('redesign.data.flow', 'redesign.data.calendar_hint'):
                        text = ui_text(key)
                        self.assertEqual(page['visible_text'].count(text), 1, key)
                        explanatory_chars -= len(text)
                    self.assertEqual(page['primary_button_count'], 1)
                    self.assertIn(ui_text('redesign.data.synthetic'), page['visible_text'])
                    self.assertEqual(page['unlabeled_inputs'], [])
                self.assertLessEqual(explanatory_chars, limits['section_2'] // 2, name)
        self.assertLessEqual(self.metrics['pages'][ui_text('ui.compare_page.title')]['page_height'], 768)
        for name, height in self.metrics['pages'][ui_text('ui.strategy_page.title')]['subpages'].items():
            self.assertLessEqual(height, 1100, name)

    def test_full_explanations_hints_and_help_accessibility(self):
        harness = onboarding.OnboardingTests()
        harness.setUpClass()
        try:
            harness.setUp()
            window = harness.window
            hints = [label for label in window.findChildren(QLabel) if label.property('page_hint')]
            self.assertEqual(len(hints), 7)
            for hint in hints:
                self.assertTrue(hint.objectName().endswith('_page_hint'))
                self.assertTrue(0 < len(hint.text()) <= 30)
            from desktop_help import MOVED_STRINGS, CAPTIONS

            expected = set(MOVED_STRINGS)
            expected.update(key for captions in CAPTIONS.values() for key, _ in captions)
            expected.update('onboarding.empty.' + key for key in ('market', 'strategy', 'backtest', 'compare', 'paper'))
            found = set()
            for key, widget in window.help_relocations:
                original = ui_text(key)
                prefix = original.split('{')[0]
                self.assertTrue(widget.toolTip().startswith(prefix), key)
                if '{' not in original:
                    self.assertEqual(widget.toolTip(), original, key)
                self.assertIsNotNone(widget.parentWidget())
                found.add(key)
            self.assertEqual(found, expected)
            for button in window.findChildren(QToolButton):
                if button.objectName().startswith('help_') or button.objectName().endswith('_help_advanced'):
                    self.assertTrue(button.accessibleName())
                    self.assertTrue(button.toolTip())
            for name, widgets in (
                ('data', (window.overview,)),
                ('settings', (window.workspace_path,)),
                (
                    'market',
                    (
                        window.market.source_status,
                        window.market.message,
                        window.market.indicator_summary,
                        window.market.findChild(QLabel, 'market_vwap_disclosure'),
                    ),
                ),
            ):
                toggle = window.findChild(QToolButton, name + '_help_advanced')
                details = window.findChild(QWidget, name + '_help_details')
                for widget in widgets:
                    self.assertTrue(details.isAncestorOf(widget))
                self.assertTrue(details.isHidden())
                toggle.setChecked(True)
                self.assertFalse(details.isHidden())
            self.assertTrue(window.settings_page.settings_sections[3].isAncestorOf(window.log_view))
            for key in ('market.init.research_paper', 'market.init.vwap_hint'):
                self.assertTrue(any(label.text() == ui_text(key) for label in window.findChild(QWidget, 'market_help_details').findChildren(QLabel)), key)
        finally:
            harness.doCleanups()


if __name__ == '__main__':
    unittest.main()
