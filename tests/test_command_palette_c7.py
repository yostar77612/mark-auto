"""Cheap offscreen keyboard and closed-dispatch evidence; no broker or visual claims."""

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QListWidget, QPushButton, QStackedWidget, QWidget

from desktop_app.components.command_palette import CommandPalette
from desktop_app.shell.palette_commands import command_table
from desktop_app.shell.shortcuts import install_shortcuts
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.main_window import MainWindow
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
from tests.test_desktop_ui_polish_b import disposable_directory
from tests.test_t9_onboarding import sandbox_ui
from tests.layered_source_fixtures import physical_path


ALLOW = {*(f'page_{i}' for i in range(1, 8)), 'refresh', 'cancel_job', 'theme', 'privacy', 'focus_import', 'focus_backtest'}


class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        w = self.window = QWidget()
        self.addCleanup(w.close)
        w.navigation = QListWidget(w)
        w.stack = QStackedWidget(w)
        for i in range(7):
            w.navigation.addItem(str(i))
            w.stack.addWidget(QWidget())
        w.navigation.currentRowChanged.connect(w.stack.setCurrentIndex)
        w.navigation.setCurrentRow(0)
        w.market = w.stack.widget(5)
        w.market.refresh_button = QPushButton(w.market)
        w.cancel_button = QPushButton(w)
        w.jobs = SimpleNamespace(active=False)
        w.cancel_job = Mock()
        w.refresh_views, w.refresh_market, w.read_logs = Mock(), Mock(), Mock()
        w._safe = lambda callback: callback()
        combo = QComboBox(w)
        combo.addItems(['dark', 'light'])
        w.app_header = SimpleNamespace(theme=combo)
        w.privacy = SimpleNamespace(toggle=QCheckBox(w), enabled=True)
        w.account_id, w.cash, w.private_symbols = 'ACCOUNT_SENTINEL', 'CASH_SENTINEL', 'SYMBOL_SENTINEL'
        self.buttons = []
        for name in ('import_data', 'run_backtest'):
            button = QPushButton(w)
            button.setObjectName(name)
            self.buttons.append(button)
        install_shortcuts(w)
        self.palette = w.command_palette
        self.addCleanup(self.palette.hide)

    def choose(self, alias):
        self.window.palette_shortcut.activated.emit()
        QTest.keyClicks(self.palette.filter, alias)
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)

    def test_pure_registry_closed_unique_and_localized(self):
        commands = command_table()
        self.assertEqual({c.id for c in commands}, ALLOW)
        self.assertEqual(len(commands), len(ALLOW))
        for command in commands:
            self.assertEqual(command.label, ui_text(command.label_key))
            self.assertNotIn(command.label, ('', '???', command.label_key))
            self.assertFalse(command.id.startswith(('paper_', 'order', 'kill', 'submit', 'cancel_order', 'restore', 'chatgpt', 'analysis', 'walk_forward')))
        tree = ast.parse(Path('desktop_app/shell/palette_commands.py').read_text())
        self.assertFalse(any(isinstance(n, ast.ImportFrom) and (n.module or '').startswith('PySide') for n in ast.walk(tree)))

    def test_all_page_commands_match_shortcuts(self):
        for row in range(7):
            self.window.page_shortcuts[row].activated.emit()
            expected = self.window.stack.currentIndex()
            self.window.navigation.setCurrentRow((row + 1) % 7)
            self.choose('page ' + str(row + 1))
            self.assertEqual(self.window.stack.currentIndex(), expected)

    def test_keyboard_filter_arrows_tab_enter_escape(self):
        self.window.palette_shortcut.activated.emit()
        first = self.palette.results.currentRow()
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Down)
        self.assertEqual(self.palette.results.currentRow(), first + 1)
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Up)
        self.assertEqual(self.palette.results.currentRow(), first)
        QTest.keyClicks(self.palette.filter, 'MARKET')
        self.assertEqual(self.palette.results.count(), 1)
        self.assertIs(self.palette.filter.nextInFocusChain(), self.palette.results)
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Tab)
        QTest.keyClick(self.palette.results, Qt.Key.Key_Return)
        self.assertEqual(self.window.stack.currentIndex(), 5)
        self.window.palette_shortcut.activated.emit()
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Escape)
        self.assertFalse(self.palette._opened)

    def test_empty_and_disabled_selection_do_nothing(self):
        self.window.palette_shortcut.activated.emit()
        QTest.keyClicks(self.palette.filter, 'cancel job')
        self.assertIn(ui_text('palette.unavailable').split('{0}')[-1], self.palette.results.item(0).text())
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)
        self.window.cancel_job.assert_not_called()
        QTest.keyClicks(self.palette.filter, 'no match')
        self.assertEqual(self.palette.results.item(0).text(), ui_text('palette.empty'))
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)
        self.window.cancel_job.assert_not_called()

    def test_disabled_existing_button_and_control_cannot_dispatch(self):
        for alias, control, method in (
            ('start backtest', self.buttons[1], 'setFocus'),
            ('theme', self.window.app_header.theme, 'setCurrentIndex'),
            ('privacy', self.window.privacy.toggle, 'toggle'),
        ):
            control.setEnabled(False)
            with patch.object(control, method) as handler:
                self.window.palette_shortcut.activated.emit()
                QTest.keyClicks(self.palette.filter, alias)
                self.assertIn(ui_text('palette.prerequisite').split('{0}')[-1], self.palette.results.item(0).text())
                QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)
                handler.assert_not_called()
                self.palette.hide()

    def test_dispatch_rechecks_guard_and_uses_existing_callables(self):
        for row in range(7):
            with patch.object(self.window.navigation, 'setCurrentRow') as navigate:
                self.choose('page ' + str(row + 1))
                navigate.assert_called_once_with(row)
        self.choose('refresh')
        self.window.refresh_views.assert_called_once_with()
        self.window.jobs.active = True
        self.choose('cancel job')
        self.window.cancel_job.assert_called_once_with()
        self.window.palette_shortcut.activated.emit()
        QTest.keyClicks(self.palette.filter, 'cancel job')
        self.window.jobs.active = False
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)
        self.window.cancel_job.assert_called_once_with()
        self.palette.hide()
        with patch.object(self.window.app_header.theme, 'setCurrentIndex') as theme:
            self.choose('theme')
            theme.assert_called_once_with(1)
        with patch.object(self.window.privacy.toggle, 'toggle') as privacy:
            self.choose('privacy')
            privacy.assert_called_once_with()
        for alias, button in zip(('import data', 'start backtest'), self.buttons):
            with patch.object(button, 'setFocus') as focus, patch.object(button, 'click') as click:
                self.choose(alias)
                focus.assert_called_once_with()
                click.assert_not_called()

    def test_focus_actions_preserve_existing_confirm_and_start_nothing(self):
        start, confirm = Mock(), Mock(return_value=False)
        for button in self.buttons:
            button.clicked.connect(lambda checked=False: start() if confirm() else None)
        with patch.object(self.window, 'refresh_views'), patch.object(self.window, 'refresh_market'), patch.object(self.window, 'read_logs'):
            for command in self.palette.commands():
                self.palette.toggle()
                self.palette.filter.setText(command.alias)
                self.palette.execute()
                self.palette.hide()
        confirm.assert_not_called()
        start.assert_not_called()
        self.buttons[1].click()
        confirm.assert_called_once_with()
        start.assert_not_called()

    def test_reuse_focus_restore_and_no_double_enter(self):
        previous = QLineEdit(self.window)
        previous.setFocus()
        for _ in range(8):
            self.window.palette_shortcut.activated.emit()
        self.assertFalse(self.palette._opened)
        self.assertIs(self.window.command_palette, self.palette)
        self.assertIs(self.window.focusWidget(), previous)
        self.choose('refresh')
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)
        self.window.refresh_views.assert_called_once_with()
        self.palette.toggle()
        self.palette.results.setCurrentRow(-1)
        QTest.keyClick(self.palette.filter, Qt.Key.Key_Return)
        self.window.refresh_views.assert_called_once_with()

    def test_plain_text_privacy_names_and_stable_order(self):
        self.palette.toggle()
        ids = [self.palette.results.item(i).data(Qt.ItemDataRole.UserRole).id for i in range(self.palette.results.count())]
        self.assertEqual(ids, [c.id for c in command_table()])
        for widget in (self.palette, self.palette.filter, self.palette.results, self.palette.hint):
            self.assertTrue(widget.accessibleName())
        for i in range(self.palette.results.count()):
            item = self.palette.results.item(i)
            self.assertTrue(item.data(Qt.ItemDataRole.AccessibleTextRole))
            for sentinel in ('ACCOUNT_SENTINEL', 'CASH_SENTINEL', 'SYMBOL_SENTINEL'):
                self.assertNotIn(sentinel, item.text())
                self.assertNotIn(sentinel, item.data(Qt.ItemDataRole.AccessibleTextRole))
        command = replace(command_table()[0], label='<b>x</b>')
        with patch('desktop_app.components.command_palette.command_table', return_value=(command,)):
            self.palette.filter.setText('<b>x</b>')
            self.assertIn('<b>x</b>', self.palette.results.item(0).text())
            self.assertEqual(self.palette.filter.text(), '<b>x</b>')
        self.assertEqual(self.palette.hint.textFormat(), Qt.TextFormat.PlainText)

    def test_localized_substring_shortcut_hints_and_popup_escape(self):
        self.palette.toggle()
        for row in range(7):
            self.assertIn('Ctrl+' + str(row + 1), self.palette.results.item(row).text())
        self.assertIn('F5', self.palette.results.item(7).text())
        self.assertIn('Esc', self.palette.results.item(8).text())
        self.palette.filter.setText(ui_text('palette.cmd.settings')[-1:])
        matches = [self.palette.results.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.palette.results.count())]
        self.assertIn('page_7', [command.id for command in matches])
        QTest.keyClick(self.palette, Qt.Key.Key_Escape)
        self.assertFalse(self.palette._opened)

    def test_bare_hosts_and_lifetime_policy(self):
        bare = CommandPalette(SimpleNamespace())
        self.addCleanup(bare.close)
        self.assertEqual(bare.commands(), ())
        for path in ('command_palette.py', 'palette_commands.py'):
            source = Path(physical_path('desktop_pages' + '/' + str(path))).read_text()
            tree = ast.parse(source)
            forbidden = {'deleteLater', 'installEventFilter', 'exec', 'eval', 'QTimer', 'save', 'start_job', 'place_order', 'open', 'read_text', 'write_text'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ''
                    self.assertNotIn(name, forbidden)

    def test_real_controls_consent_providers_and_settings_stay_confined(self):
        with disposable_directory() as folder, sandbox_ui():
            paths = AppPaths(Path(folder) / 'workspace').ensure()
            jobs = JobManager(paths)
            self.addCleanup(jobs.close)
            window = MainWindow(paths, jobs, SettingsStore(paths.state / 'settings.json'))
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                window.privacy.toggle.setChecked(True)
                window.account_id = 'ACCOUNT_SENTINEL'
                window.cash = 'CASH_SENTINEL'
                window.private_symbols = 'SYMBOL_SENTINEL'
                palette = window.command_palette
                with (
                    patch.object(window, 'start_job') as start,
                    patch.object(window.widgets_page, '_confirm_button', return_value=None) as confirm,
                    patch('PySide6.QtWidgets.QMessageBox.question') as consent,
                    patch('desktop_app.features.assistant.connection.ConnectionController.request') as connection,
                    patch('quantlab.assistant.adapters.chatgpt.provider.ChatGPTPlanProvider.generate') as generate,
                    patch('quantlab.assistant.adapters.chatgpt.provider.ChatGPTPlanProvider.analyze') as analyze,
                    patch('quantlab.assistant.adapters.chatgpt.provider.PlanHTTPTransport.__init__', return_value=None) as transport,
                ):
                    self.assertEqual({c.id for c in palette.commands()}, ALLOW)
                    for command in palette.commands():
                        window.palette_shortcut.activated.emit()
                        QTest.keyClicks(palette.filter, command.alias)
                        for row in range(palette.results.count()):
                            item = palette.results.item(row)
                            for sentinel in ('ACCOUNT_SENTINEL', 'CASH_SENTINEL', 'SYMBOL_SENTINEL'):
                                self.assertNotIn(sentinel, item.text())
                                self.assertNotIn(sentinel, item.data(Qt.ItemDataRole.AccessibleTextRole))
                        QTest.keyClick(palette.filter, Qt.Key.Key_Return)
                        palette.hide()
                    for mock in (start, confirm, consent, connection, generate, analyze, transport):
                        mock.assert_not_called()
                    # Even a subsequent explicit click still enters the original button guard.
                    for name in ('import_data', 'run_backtest'):
                        button = window.findChild(QPushButton, name)
                        button.setEnabled(True)  # Simulate prerequisites solely to exercise both existing guard connections.
                        button.click()
                    self.assertEqual(confirm.call_count, 2)
                    start.assert_not_called()
                for file in paths.state.rglob('*.json'):
                    content = file.read_text(encoding='utf-8')
                    for sentinel in ('ACCOUNT_SENTINEL', 'CASH_SENTINEL', 'SYMBOL_SENTINEL'):
                        self.assertNotIn(sentinel, content)
            finally:
                window.close()

    def test_shortcut_regression_and_hints(self):
        shortcuts = [*self.window.page_shortcuts, self.window.refresh_shortcut, self.window.cancel_shortcut, self.window.palette_shortcut]
        sequences = [s.key().toString() for s in shortcuts]
        self.assertEqual(sequences, [*(f'Ctrl+{i}' for i in range(1, 8)), 'F5', 'Esc', 'Ctrl+K'])
        self.assertEqual(len(set(sequences)), len(sequences))
        self.assertIn('Ctrl+K', self.window.whatsThis())
        for row in range(7):
            self.window.page_shortcuts[row].activated.emit()
            self.assertEqual(self.window.stack.currentIndex(), row)
            self.window.refresh_shortcut.activated.emit()
        self.assertEqual(self.window.refresh_views.call_count, 5)
        self.window.refresh_market.assert_called_once_with()
        self.window.read_logs.assert_called_once_with()
        self.window.cancel_shortcut.activated.emit()
        self.window.cancel_job.assert_not_called()
        self.window.jobs.active = True
        self.window.cancel_shortcut.activated.emit()
        self.window.cancel_job.assert_called_once_with()
