"""Disclosure migration keeps saved preferences intact until a real user edit."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from desktop_pages.design import section
from desktop_pages.widgets import WidgetTools
from desktop_strings import ui_text
from tests.test_t9_onboarding import sandbox_ui


class MemoryStore:
    def __init__(self, value):
        self.value = deepcopy(value)
        self.writes = []

    def load(self):
        return deepcopy(self.value)

    def save(self, value):
        self.value = deepcopy(value)
        self.writes.append(deepcopy(value))


class DisclosureMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def mount(self, value, key='redesign_data_details', expanded=False):
        owner = QWidget()
        self.addCleanup(owner.deleteLater)
        store = MemoryStore(value)
        state = SimpleNamespace(settings=store, _section_toggles={}, _restoring_sections=False)
        tools = WidgetTools(SimpleNamespace(state=state))
        state.save_sections = Mock(side_effect=tools._save_section_preferences)
        content = section(QVBoxLayout(owner), 'redesign.paper.conditions', expanded=expanded, key=key, state=state)
        return state, content, state._section_toggles[key]

    def assert_expanded(self, content, toggle, expected):
        self.assertEqual(toggle.isChecked(), expected)
        self.assertEqual(content.parentWidget().isHidden(), not expected)
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.DownArrow if expected else Qt.ArrowType.RightArrow)

    def test_fresh_mount_keeps_default_expanded_without_saving(self):
        for expanded in (False, True):
            with self.subTest(expanded=expanded):
                original = {'unrelated': {'keep': 'original'}}
                state, content, toggle = self.mount(original, expanded=expanded)
                self.assert_expanded(content, toggle, expanded)
                state.save_sections.assert_not_called()
                self.assertEqual(state.settings.writes, [])
                self.assertEqual(state.settings.load(), original)

    def test_current_explicit_boolean_wins_over_legacy_and_defaults(self):
        legacy = '2:' + ui_text('ui.advanced.default_title')
        for current in (False, True):
            with self.subTest(current=current):
                original = {'advanced_sections': {'redesign_data_details': current, legacy: not current, 'unknown': True}}
                state, content, toggle = self.mount(original, expanded=not current)
                self.assert_expanded(content, toggle, current)
                state.save_sections.assert_not_called()
                self.assertEqual(state.settings.load(), original)

    def test_legacy_data_backtest_and_compare_disclosures_restore_real_widgets(self):
        for key, prefix in (('redesign_data_details', '2:'), ('redesign_backtest_advanced', '4:'), ('redesign_compare_details', '5:')):
            for stored in (False, True):
                with self.subTest(key=key, stored=stored):
                    legacy = prefix + ui_text('ui.advanced.default_title')
                    original = {'advanced_sections': {legacy: stored}}
                    state, content, toggle = self.mount(original, key=key, expanded=not stored)
                    self.assert_expanded(content, toggle, stored)
                    self.assertEqual(state.settings.load(), original)
                    self.assertEqual(state.settings.writes, [])

    def test_paper_legacy_any_true_restores_preparation_but_current_false_wins(self):
        for sections, default, expected in (
            ({'6:policy': False, '6:snapshot': True}, False, True),
            ({'6:policy': True, 'paper_preparation': False}, True, False),
            ({'6:policy': False, '7:other': True}, False, False),
            ({'6:policy': False}, True, True),
            ({6: True, '6:policy': 1}, False, False),
        ):
            with self.subTest(sections=sections, default=default):
                state, content, toggle = self.mount({'advanced_sections': sections}, key='paper_preparation', expanded=default)
                self.assert_expanded(content, toggle, expected)
                self.assertEqual(state.settings.writes, [])

    def test_malformed_section_containers_and_boolean_values_use_default(self):
        for sections in (None, [], ['redesign_data_details'], 'corrupt', 1, {'redesign_data_details': 'false'}, {'redesign_data_details': 1}):
            for default in (False, True):
                with self.subTest(sections=sections, default=default):
                    original = {'advanced_sections': sections, 'unknown': {'keep': True}}
                    state, content, toggle = self.mount(original, expanded=default)
                    self.assert_expanded(content, toggle, default)
                    self.assertEqual(state.settings.load(), original)
                    self.assertEqual(state.settings.writes, [])

    def test_real_toggle_merges_owned_values_without_removing_unknown_keys(self):
        legacy = '2:' + ui_text('ui.advanced.default_title')
        original = {'advanced_sections': {legacy: False, 'future.disclosure': True}, 'unknown': {'keep': [1, 2]}}
        state, content, toggle = self.mount(original)
        toggle.setChecked(True)
        self.assert_expanded(content, toggle, True)
        state.save_sections.assert_called_once_with()
        self.assertEqual(len(state.settings.writes), 1)
        expected = deepcopy(original)
        expected['advanced_sections']['redesign_data_details'] = True
        self.assertEqual(state.settings.load(), expected)
        toggle.setChecked(True)
        self.assertEqual(len(state.settings.writes), 1)

    def test_restore_guard_suppresses_persistence_until_the_next_user_change(self):
        state, content, toggle = self.mount({'advanced_sections': {'future.disclosure': True}})
        state._restoring_sections = True
        toggle.setChecked(True)
        self.assert_expanded(content, toggle, True)
        self.assertEqual(state.settings.writes, [])
        state._restoring_sections = False
        toggle.setChecked(False)
        self.assertEqual(len(state.settings.writes), 1)
        self.assertEqual(state.settings.load()['advanced_sections'], {'future.disclosure': True, 'redesign_data_details': False})


class WindowDisclosurePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore

        sandbox = sandbox_ui()
        sandbox.__enter__()
        self.addCleanup(sandbox.__exit__, None, None, None)
        self.directory = tempfile.TemporaryDirectory(prefix='redesign-shell-preferences-')
        self.addCleanup(self.directory.cleanup)
        self.paths = AppPaths(Path(self.directory.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.addCleanup(self.jobs.close)
        self.store = SettingsStore(self.paths.state / 'settings.json')

    def open_window(self):
        from desktop_ui import MainWindow

        window = MainWindow(self.paths, self.jobs, self.store)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        for timer in window.findChildren(QTimer):
            timer.stop()
        return window

    def test_real_store_fresh_window_does_not_rewrite_file_or_override_open_default(self):
        original = {'unknown': {'keep': 'unchanged'}}
        self.store.save(original)
        before = self.store.path.read_bytes()
        with patch.object(self.store, 'save', wraps=self.store.save) as saved:
            window = self.open_window()
            self.assertTrue(window.page_state._section_toggles['redesign_compare_selection'].isChecked())
            self.assertFalse(window.page_state._section_toggles['paper_preparation'].isChecked())
            window.settings_page.load_settings()
            saved.assert_not_called()
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.load(), original)

    def test_first_window_does_not_create_a_settings_file_just_to_mount_disclosures(self):
        self.assertFalse(self.store.path.exists())
        with patch.object(self.store, 'save', wraps=self.store.save) as saved:
            window = self.open_window()
            self.assertTrue(window.page_state._section_toggles['redesign_compare_selection'].isChecked())
            saved.assert_not_called()
        self.assertFalse(self.store.path.exists())

    def test_real_store_legacy_reload_is_read_only_and_user_change_preserves_unknowns(self):
        original = {
            'advanced_sections': {
                '2:' + ui_text('ui.advanced.default_title'): True,
                '4:' + ui_text('ui.advanced.default_title'): True,
                '5:' + ui_text('ui.advanced.default_title'): True,
                '6:snapshot': True,
                'data:help': True,
                'settings:help': True,
                'market:help': True,
                'future.disclosure': False,
            },
            'unknown': {'keep': 'unchanged'},
        }
        self.store.save(original)
        before = self.store.path.read_bytes()
        with patch.object(self.store, 'save', wraps=self.store.save) as saved:
            window = self.open_window()
            toggles = window.page_state._section_toggles
            for key in ('redesign_data_details', 'redesign_backtest_advanced', 'redesign_compare_details', 'paper_preparation'):
                self.assertTrue(toggles[key].isChecked(), key)
                toggles[key].blockSignals(True)
                toggles[key].setChecked(False)
                toggles[key].blockSignals(False)
            window.settings_page.load_settings()
            for key in ('redesign_data_details', 'redesign_backtest_advanced', 'redesign_compare_details', 'paper_preparation'):
                self.assertTrue(toggles[key].isChecked(), key)
            self.assertFalse(window.page_state._restoring_sections)
            saved.assert_not_called()
            self.assertEqual(self.store.path.read_bytes(), before)
            toggles['redesign_data_details'].setChecked(False)
            saved.assert_called_once()
        result = self.store.load()
        self.assertIs(result['advanced_sections']['redesign_data_details'], False)
        for key, value in original['advanced_sections'].items():
            self.assertEqual(result['advanced_sections'][key], value, key)
        self.assertEqual(result['unknown'], original['unknown'])

    def test_real_store_corrupt_section_type_restores_defaults_without_repairing_file(self):
        original = {'advanced_sections': ['invalid', 'container'], 'unknown': {'keep': True}}
        self.store.save(original)
        before = self.store.path.read_bytes()
        with patch.object(self.store, 'save', wraps=self.store.save) as saved:
            window = self.open_window()
            window.settings_page.load_settings()
            self.assertTrue(window.page_state._section_toggles['redesign_compare_selection'].isChecked())
            self.assertFalse(window.page_state._section_toggles['redesign_data_details'].isChecked())
            self.assertFalse(window.page_state._section_toggles['paper_preparation'].isChecked())
            saved.assert_not_called()
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
