"""M1-U regression contracts on the real offline research widget tree."""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton

from desktop_app.strings.catalog import ZH_TW, ui_text
from desktop_app.features.strategy.forms import FAMILY_LABELS
from desktop_app.shell.palette_commands import page_index
from tests import test_desktop_pages


class GlyphCatalogueTests(unittest.TestCase):
    def test_no_known_missing_glyphs_remain_in_string_catalogue(self):
        banned = ('\u25b8', '\u25be', '\u2212')
        self.assertEqual([], [(key, glyph) for key, value in ZH_TW.items() for glyph in banned if glyph in value])


class M1UiDefectTests(unittest.TestCase):
    setUpClass = classmethod(test_desktop_pages.PageInteractionTests.setUpClass.__func__)
    setUp = test_desktop_pages.PageInteractionTests.setUp
    tearDown = test_desktop_pages.PageInteractionTests.tearDown

    def test_single_help_entry_and_noninteractive_badge(self):
        w = self.window
        self.assertTrue(w.app_header.disclosure.isHidden())
        self.assertTrue(w.findChild(QPushButton, 'onboarding_help').isVisibleTo(w))
        self.assertIsInstance(w.app_header.badge, QLabel)
        self.assertTrue(w.status.isHidden())

    def test_progress_tracks_page_identity_and_remains_visible_after_partial_completion(self):
        w = self.window
        w._dataset_ready = True
        w.onboarding.refresh()
        self.assertFalse(w.onboarding.isHidden())
        self.assertEqual('done', w.onboarding.buttons[0].property('state'))
        w.onboarding.buttons[1].click()
        self.assertEqual(page_index(w, 'strategy'), w.stack.currentIndex())
        self.assertEqual('progress', w.onboarding.buttons[1].property('state'))
        self.assertTrue(w.onboarding.buttons[1].property('current'))
        self.assertFalse(w.navigation.item(page_index(w, 'compare')).isHidden())

    def test_native_advanced_disclosures_and_single_replay_caption(self):
        w = self.window
        for name, toggle in w._section_toggles.items():
            if toggle.objectName().startswith('advanced_') or toggle.objectName().endswith('_help_advanced'):
                self.assertIsInstance(toggle, QToolButton, name)
                self.assertTrue(toggle.isCheckable(), name)
                toggle.setChecked(True)
                self.assertEqual(Qt.ArrowType.DownArrow, toggle.arrowType(), name)
        captions = [label for label in w.paper_page.findChildren(QLabel) if label.text() == ui_text('redesign.paper.bars')]
        self.assertEqual(1, len(captions))

    def test_backtest_primary_follows_prerequisite_and_strategy_name_is_localized(self):
        w = self.window
        action = w.findChild(QPushButton, 'empty_backtest_action')
        self.assertEqual('primary', action.property('role'))
        w._dataset_ready = True
        w.onboarding.refresh()
        self.assertTrue(action.parentWidget().isHidden())
        self.assertEqual('primary', w.findChild(QPushButton, 'run_backtest').property('role'))
        w.backtest_page.refresh_run_summary()
        self.assertIn(FAMILY_LABELS['trend'], w.backtest_page.run_summary.text())
        hint = w.findChild(QLabel, 'run_backtest_prerequisite')
        self.assertIs(hint.parentWidget(), w.backtest_page._setup_panel)
        self.assertGreaterEqual(w.backtest_page._setup_panel.layout().indexOf(hint), 0)

    def test_compare_empty_state_has_readable_headers_and_strategy_tabs_have_tab_style(self):
        w = self.window
        table = w.compare_page.saved_results_table
        self.assertEqual(0, table.rowCount())
        self.assertFalse(table.empty_label.isHidden())
        self.assertEqual(ui_text('m1u.compare_empty'), table.empty_label.text())
        for column in range(table.columnCount()):
            header = table.horizontalHeaderItem(column)
            self.assertTrue(header.toolTip())
            self.assertLessEqual(table.fontMetrics().horizontalAdvance(header.text()) + 18, table.columnWidth(column))
        for button in (*w.strategy_page.mode_buttons.values(), w.strategy_page.walk_forward_entry):
            self.assertEqual('strategyTab', button.property('themePart'))
            self.assertTrue(button.isCheckable())


if __name__ == '__main__':
    unittest.main()
