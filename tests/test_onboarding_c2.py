"""Cheap offscreen contracts for the compact workflow bar, without shown windows."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget
from desktop_app.shell.onboarding import GettingStarted, WORKFLOW_ORDER
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.theme import build_app_stylesheet
from quantlab.research_core.adapters.settings_store import SettingsStore
from tests.test_desktop_ui_polish_b import disposable_directory
from tests import test_paper as paper_fixtures


# e0e604f GettingStarted, shared interpreter, offscreen, dark AND light QSS: 288 px.
# This historical measurement is a bound for reclamation, not a platform font oracle.
BASELINE_E0E604F_HEIGHT = 288


class CompactOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = disposable_directory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.shell = SimpleNamespace(root=self.root, navigation=SimpleNamespace(setCurrentRow=Mock()))

    def bar(self):
        bar = GettingStarted(self.shell)
        self.addCleanup(bar.close)
        self.addCleanup(bar.deleteLater)
        return bar

    def test_single_row_height_full_text_and_navigation_in_both_themes(self):
        self.assertEqual(WORKFLOW_ORDER, (1, 2, 3, 4, 5, 0, 6))
        for theme in ('dark', 'light'):
            with self.subTest(theme=theme):
                bar = self.bar()
                bar.setStyleSheet(build_app_stylesheet(theme))
                bar.ensurePolished()
                bar.refresh()
                self.assertIsInstance(bar.layout(), QHBoxLayout)
                self.assertEqual(bar.findChildren(QHBoxLayout), [bar.layout()])
                self.assertEqual(bar.findChildren(QVBoxLayout), [])
                self.assertLessEqual(bar.sizeHint().height(), 40)
                self.assertLessEqual(bar.maximumHeight(), 40)
                self.assertGreaterEqual(BASELINE_E0E604F_HEIGHT - bar.sizeHint().height(), BASELINE_E0E604F_HEIGHT - 40)
                for index, (button, label) in enumerate(zip(bar.buttons, bar.labels)):
                    button.click()
                    self.shell.navigation.setCurrentRow.assert_called_with(index)
                    self.assertIn(ui_text('onboarding.pending'), button.text())
                    self.assertIn(ui_text('onboarding.pending'), label.text())
                    self.assertGreaterEqual(button.sizeHint().width(), button.fontMetrics().horizontalAdvance(button.text()))
                    self.assertGreaterEqual(button.minimumWidth(), button.sizeHint().width())
                    self.assertEqual(button.property('role'), 'onboardingChip')
                    self.assertEqual(button.property('state'), 'pending')
                self.assertIn('[role="onboardingChip"][state="done"]', bar.styleSheet())
                self.assertIn('[role="onboardingChip"][state="pending"]', bar.styleSheet())

    def test_dismiss_restore_reopen_and_unrelated_settings_roundtrip(self):
        store = SettingsStore(self.root / 'settings.json')
        unrelated = {'appearance.theme': 'light', 'advanced_sections': {'diagnostics': True}}
        store.save(unrelated)
        self.shell.settings = store
        bar = self.bar()
        with patch.object(store, 'save', wraps=store.save) as save:
            bar.findChild(QPushButton, 'onboarding_dismiss').click()
            save.assert_called_once_with(dict(unrelated, onboarding_dismissed=True))
        self.assertTrue(bar.isHidden())
        self.assertTrue(self.bar().isHidden())
        bar.set_dismissed(False)  # unchanged onboarding_help callback
        self.assertFalse(bar.isHidden())
        self.assertEqual(store.load(), dict(unrelated, onboarding_dismissed=False))

    def test_each_completion_hides_and_removes_layout_height(self):
        bar = self.bar()
        parent = QWidget()
        self.addCleanup(parent.close)
        self.addCleanup(parent.deleteLater)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        content = QWidget()
        content.setFixedHeight(100)
        layout.addWidget(content)
        parent.ensurePolished()
        visible_height = layout.sizeHint().height()
        self.assertFalse(layout.itemAt(0).isEmpty())
        self.shell._dataset_ready = True
        bar.refresh()
        self.assertTrue(bar.isHidden())
        self.assertTrue(layout.itemAt(0).isEmpty())
        self.assertEqual(layout.sizeHint().height(), visible_height - bar.sizeHint().height())
        self.assertEqual(layout.sizeHint().height(), content.sizeHint().expandedTo(content.minimumSize()).height())

    def test_completed_tuple_from_existing_filesystem_and_controls(self):
        bar = self.bar()
        self.assertEqual(bar.completed, (False,) * 5)
        for filename, expected in (
            ('active_candidate.json', (False, True, False, False, False)),
            ('selection.json', (False, True, False, True, False)),
        ):
            path = self.root / filename
            path.write_text('{}', encoding='utf-8')
            bar.refresh()
            self.assertEqual(bar.completed, expected)
            self.assertTrue(bar.isHidden())
            path.unlink()
        self.shell.result_choice = SimpleNamespace(count=lambda: 1)
        self.shell.comparison_list = SimpleNamespace(count=lambda: 1, selectedItems=lambda: [object()])
        bar.refresh()
        self.assertEqual(bar.completed, (False, False, True, True, False))
        for button, done in zip(bar.buttons, bar.completed):
            self.assertEqual(button.property('state'), 'done' if done else 'pending')
            self.assertIn(ui_text('onboarding.done') if done else ui_text('onboarding.pending'), button.text())

    def test_paper_snapshot_completion_and_invalid_database(self):
        bar = self.bar()
        path = self.root / 'paper.sqlite3'
        path.write_bytes(b'invalid database')
        bar.refresh()
        self.assertEqual(bar.completed, (False,) * 5)
        path.unlink()
        fixture = paper_fixtures.PaperTests()
        self.addCleanup(fixture.doCleanups)
        with patch.object(paper_fixtures.tempfile, 'TemporaryDirectory', disposable_directory):
            fixture.setUp()
        fixture.path.rename(path)
        bar.refresh()
        self.assertEqual(bar.completed, (False, False, False, False, True))
        self.assertTrue(bar.isHidden())

    def test_existing_automation_names_preserved(self):
        bar = self.bar()
        catalog = json.loads((Path(__file__).parent / 'fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        for page in ('data', 'strategy', 'backtest', 'compare', 'paper'):
            for prefix in ('onboarding_go_', 'onboarding_status_'):
                name = prefix + page
                self.assertIn(name, catalog)
                self.assertIsNotNone(bar.findChild(QWidget, name))

    def test_bare_host_dismissal_without_settings(self):
        bar = self.bar()
        bar.findChild(QPushButton, 'onboarding_dismiss').click()
        bar.refresh()
        self.assertTrue(bar.isHidden())
        bar.set_dismissed(False)
        self.assertFalse(bar.isHidden())
