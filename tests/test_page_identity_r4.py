"""Cheap real-window identity/position regression, without showing a window."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from desktop_app.shell.onboarding import WORKFLOW_ORDER, install_onboarding
from desktop_app.shell.palette_commands import DEFAULT_PAGE_ORDER, MOUNT_PAGE_ORDER, command_table, page_index, page_widget
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.window import MainWindow
from quantlab.research_core.adapters.workspace_store import AppPaths
from desktop_app.research_bootstrap import create_job_manager
from quantlab.research_core.adapters.settings_store import SettingsStore
from tests.test_desktop_ui_polish_b import disposable_directory
from tests.test_t9_onboarding import sandbox_ui
# Source scans below use current physical paths.


def reverse_pages(window):
    """Use onboarding's remove/add path, keeping navigation and stack aligned."""
    window.navigation.blockSignals(True)
    try:
        items = [window.navigation.takeItem(0) for _ in range(window.navigation.count())]
        pages = [window.stack.widget(index) for index in range(window.stack.count())]
        for page in pages:
            window.stack.removeWidget(page)
        for item, page in reversed(tuple(zip(items, pages))):
            window.navigation.addItem(item)
            window.stack.addWidget(page)
        window.navigation.setCurrentRow(-1)
    finally:
        window.navigation.blockSignals(False)


class PageIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_real_window_default_and_reordered_dispatch(self):
        captured = {}

        def onboarding(window):
            captured['mount_widgets'] = [window.stack.widget(i) for i in range(7)]
            captured['mount_labels'] = [window.navigation.item(i).text() for i in range(7)]
            install_onboarding(window)
            captured['labels'] = [window.navigation.item(i).text() for i in range(7)]
            captured['hints'] = [window.navigation.item(i).toolTip() for i in range(7)]

        with disposable_directory() as folder, sandbox_ui():
            paths = AppPaths(Path(folder) / 'workspace').ensure()
            jobs = create_job_manager(paths)
            try:
                with patch('desktop_app.shell.onboarding.install_onboarding', side_effect=onboarding):
                    window = MainWindow(paths, jobs, SettingsStore(paths.state / 'settings.json'), services=_c_create_ui_services(_c_create_operation_ports()))
                try:
                    for timer in window.findChildren(QTimer):
                        timer.stop()
                    self.assertEqual(WORKFLOW_ORDER, (1, 2, 3, 4, 5, 0, 6))
                    self.assertEqual(tuple(MOUNT_PAGE_ORDER[i] for i in WORKFLOW_ORDER), DEFAULT_PAGE_ORDER)
                    self.assertEqual(len(set(DEFAULT_PAGE_ORDER)), 7)
                    self.assertEqual(set(DEFAULT_PAGE_ORDER), {'data', 'strategy', 'backtest', 'compare', 'paper', 'market', 'settings'})
                    self.assertEqual(captured['labels'], [ui_text('redesign.nav.' + page_id) for page_id in DEFAULT_PAGE_ORDER])
                    self.assertTrue(window.navigation.item(page_index(window, 'compare')).isHidden())
                    self.assertEqual(
                        [window.navigation.item(i).text() for i in range(7) if not window.navigation.item(i).isHidden()][:4],
                        [ui_text('redesign.nav.' + page_id) for page_id in ('data', 'strategy', 'backtest', 'paper')],
                    )
                    hints = [ui_text('onboarding.hint.' + str(i)) for i in WORKFLOW_ORDER]
                    self.assertEqual(captured['hints'], hints)
                    self.assertEqual([shortcut.key().toString() for shortcut in window.page_shortcuts], [f'Ctrl+{i}' for i in range(1, 8)])
                    self.assertEqual(
                        [s.key().toString() for s in (window.palette_shortcut, window.refresh_shortcut, window.cancel_shortcut)], ['Ctrl+K', 'F5', 'Esc']
                    )
                    widgets = {page_id: page_widget(window, page_id) for page_id in DEFAULT_PAGE_ORDER}
                    for row, page_id in enumerate(DEFAULT_PAGE_ORDER):
                        self.assertIs(widgets[page_id], captured['mount_widgets'][WORKFLOW_ORDER[row]])
                        self.assertEqual(page_index(window, page_id), row)
                        window.page_shortcuts[row].activated.emit()
                        self.assertIs(window.stack.currentWidget(), widgets[page_id])
                        self.assertEqual(window.navigation.item(row).toolTip(), ui_text('keyboard.page').format(captured['labels'][row], row + 1))
                    self.assertIs(widgets['settings'].widget(), window.settings_page)
                    self.assertIs(widgets['market'], window.market)
                    self.assertIsNone(page_widget(window, 'unknown'))
                    self.assertEqual(page_index(window, 'unknown'), -1)
                    with (
                        patch.object(window, '_safe', side_effect=lambda callback: callback()),
                        patch.object(window, 'read_logs') as logs,
                        patch.object(window, 'refresh_market') as market,
                        patch.object(window, 'refresh_views') as views,
                    ):
                        # Explicit F5 proof after the real onboarding installation.
                        window.navigation.setCurrentRow(page_index(window, 'settings'))
                        window.refresh_shortcut.activated.emit()
                        logs.assert_called_once_with()
                        logs.reset_mock()
                        # Populate before reorder: execution must resolve again, not cache a row.
                        palette = window.command_palette
                        palette.filter.setText('settings page 7')
                        palette._opened = True
                        reverse_pages(window)
                        palette.execute()
                        self.assertIs(window.stack.currentWidget(), widgets['settings'])
                        self.assertEqual(page_index(window, 'settings'), 0)
                        self.assertIs(window.stack.widget(6), widgets['data'])
                        for row, page_id in enumerate(reversed(DEFAULT_PAGE_ORDER)):
                            with self.subTest(page=page_id):
                                for mock in (logs, market, views):
                                    mock.reset_mock()
                                self.assertEqual(page_index(window, page_id), row)
                                # Ctrl+N addresses the current visual position N.
                                window.page_shortcuts[row].activated.emit()
                                self.assertIs(window.stack.currentWidget(), widgets[page_id])
                                window.refresh_shortcut.activated.emit()
                                self.assertEqual(logs.call_count, int(page_id == 'settings'))
                                self.assertEqual(market.call_count, int(page_id == 'market'))
                                self.assertEqual(views.call_count, int(page_id not in ('settings', 'market')))
                        for command in command_table():
                            if not command.page_id:
                                continue
                            if command.handler in ('focus_import', 'focus_backtest'):
                                palette.focus_button(command).setEnabled(True)
                            palette.filter.setText(command.alias)
                            palette._opened = True
                            palette.execute()
                            self.assertIs(window.stack.currentWidget(), widgets[command.page_id])
                finally:
                    window.close()
            finally:
                jobs.close()

    def test_no_numeric_page_identity_comparisons(self):
        paths = [Path('desktop_app/shell/main_window.py'), *Path('desktop_app').rglob('*.py')]
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if not isinstance(node, ast.Compare):
                    continue
                operands = [node.left, *node.comparators]
                page_calls = [
                    value
                    for value in operands
                    if isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr in ('currentIndex', 'currentRow')
                    and isinstance(value.func.value, ast.Attribute)
                    and value.func.value.attr in ('stack', 'navigation')
                ]
                if page_calls:
                    self.assertFalse(any(isinstance(value, ast.Constant) and isinstance(value.value, int) for value in operands), (path, node.lineno))
