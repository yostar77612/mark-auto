"""Live P1-04 budgets, preserved explanations and T8 layout boundaries."""
import json
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QLabel, QToolButton, QWidget
from desktop_strings import ui_text
from tests import test_t9_onboarding as onboarding
from tools.ui_snapshot import capture

ROOT = Path(__file__).resolve().parents[1]


class HelpReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with onboarding.sandbox_ui(), tempfile.TemporaryDirectory(prefix='t9-help-snapshot-') as folder:
            cls.metrics = capture(Path(folder) / 'snapshot')

    def test_live_label_budgets_and_t8_heights(self):
        baseline = json.loads((ROOT / 'docs/analysis/t9_label_baseline.json').read_text(encoding='utf-8'))
        for name, page in self.metrics['pages'].items():
            limits = baseline['pages'][name]
            self.assertLessEqual(page['label_char_count'], limits['merged_t8'], name)
            if limits.get('half_required'):
                self.assertLessEqual(page['label_char_count'], limits['section_2'] // 2, name)
        self.assertLessEqual(self.metrics['pages'][ui_text('ui._compare_page.text_1')]['page_height'], 768)
        for name, height in self.metrics['pages'][ui_text('ui._strategy_page.text_1')]['subpages'].items():
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
                ('settings', (window.workspace_path, window.log_view)),
                ('market', (window.market.source_status, window.market.message, window.market.indicator_summary,
                            window.market.findChild(QLabel, 'market_vwap_disclosure'))),
            ):
                toggle = window.findChild(QToolButton, name + '_help_advanced')
                details = window.findChild(QWidget, name + '_help_details')
                for widget in widgets:
                    self.assertTrue(details.isAncestorOf(widget))
                self.assertTrue(details.isHidden())
                toggle.setChecked(True)
                self.assertFalse(details.isHidden())
            for key in ('market.__init__.text_42', 'market.__init__.text_53'):
                self.assertTrue(any(label.text() == ui_text(key) for label in
                                    window.findChild(QWidget, 'market_help_details').findChildren(QLabel)), key)
        finally:
            harness.doCleanups()


if __name__ == '__main__':
    unittest.main()
