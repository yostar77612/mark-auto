"""Scoped first-round UI-guideline acceptance; no broker or engine process."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QPushButton

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.page_help import HelpText
from desktop_app.features.trading.widgets import button
from desktop_app.strings.catalog import ui_text
from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment
from tests import test_m2_trading_page as support


class M2GuidelinesTests(unittest.TestCase):
    setUpClass = classmethod(support.M2TradingPageTests.setUpClass.__func__)
    setUp = support.M2TradingPageTests.setUp
    tearDown = support.M2TradingPageTests.tearDown
    drain = support.M2TradingPageTests.drain

    def test_each_help_control_sits_beside_the_text_it_explains_and_keeps_full_information(self):
        for index, name in ((0, 'overview'), (3, 'trading'), (4, 'performance'), (5, 'settings')):
            self.window.navigation.setCurrentRow(index)
            header = self.window.page_headers[name]
            title_controls = [header.itemAt(i).widget() for i in range(header.count())]
            rows = self.window.pages.widget(index).findChildren(HelpText)
            self.assertTrue(rows, name)
            for row in rows:
                self.assertNotIn(row.button, title_controls, row.objectName())
                self.assertIs(row.button.parentWidget(), row, row.objectName())
                self.assertIs(row.summary.parentWidget(), row, row.objectName())
                self.assertEqual(row.button.toolTip(), row.details.text())

    def test_button_roles_are_explicit_and_at_most_one_primary_per_touched_page(self):
        control = button('v2.reconcile', 'role_probe', role='danger')
        self.assertEqual(control.property('role'), 'danger')
        control.deleteLater()
        for index in (0, 3, 4, 5):
            page = self.window.pages.widget(index)
            primaries = [item for item in page.findChildren(QPushButton) if item.property('role') == 'primary']
            self.assertLessEqual(len(primaries), 1)
        self.assertEqual(self.window.reconcile_button.property('role'), 'primary')
        for name in ('stop_button', 'cancel_entries_button', 'flatten_button', 'overview_stop', 'overview_cancel_entries'):
            self.assertEqual(getattr(self.window, name).property('role'), 'danger', name)
            self.assertEqual(getattr(self.window, name).palette().color(QPalette.ColorRole.Button).name(), '#9b1c1c')

    def test_position_units_alignment_and_taipei_time_preserve_underlying_facts(self):
        table = self.window.positions
        self.assertEqual(table.item(0, 1).text(), ui_text('v2.long') + ' · 1 ' + ui_text('m2t.lots'))
        self.assertEqual(table.item(0, 11).text(), '10/23 13:30')
        self.assertTrue(table.item(0, 1).textAlignment() & Qt.AlignmentFlag.AlignRight)
        self.assertTrue(table.item(0, 2).textAlignment() & Qt.AlignmentFlag.AlignRight)
        self.assertEqual(self.window.state.positions[0].quantity, 1000)
        self.assertEqual(self.window.state.positions[0].quote_time, '2026-10-23T05:30:00Z')

    def test_each_dangerous_control_reaches_cancel_default_and_cancel_sends_nothing(self):
        self.window.positions.selectRow(0)
        boxes = []

        def cancel(box):
            boxes.append(box)
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            self.assertIs(box.textFormat(), Qt.TextFormat.PlainText)
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            for name in ('stop_button', 'cancel_entries_button', 'flatten_button', 'overview_stop', 'overview_cancel_entries'):
                getattr(self.window, name).click()
        self.assertEqual(len(boxes), 5)
        self.assertEqual(self.facade.commands, [])

    def test_confirmed_stop_and_cancel_keep_actions_and_reject_nested_context_change(self):
        for name, action in (('stop_button', UiAction.STOP_NEW), ('cancel_entries_button', UiAction.CANCEL_ENTRIES)):
            with patch.object(self.window, '_confirm', return_value=True):
                getattr(self.window, name).click()
            self.drain()
            self.assertIs(self.facade.commands[-1].action, action)
        before = len(self.facade.commands)

        def reenter(_):
            self.window.apply_state(replace(self.window.state, version=self.window.state.version + 1, account_ref='another-book'))
            return True

        with patch.object(self.window, '_confirm', side_effect=reenter):
            self.window.cancel_entries_button.click()
        self.assertEqual(len(self.facade.commands), before)
        self.assertEqual(self.window.notice.text(), ui_text('v2.state_conflict'))

    def test_six_default_position_columns_and_real_preference_restore(self):
        self.assertEqual({i for i in range(12) if not self.window.positions.isColumnHidden(i)}, {0, 1, 2, 5, 8, 9})
        with tempfile.TemporaryDirectory(prefix='m2-column-preferences-') as folder:
            store = SettingsStore(Path(folder) / 'presentation.json')
            for pass_index in range(2):
                initial = store.load().get('position_columns')
                window = TradingWindow(
                    self.facade,
                    self.facade.snapshot(),
                    position_columns=initial,
                    save_position_columns=lambda values: store.save({'position_columns': list(values)}),
                )
                window.poll.stop()
                window.setProperty('allow_close_for_tests', True)
                try:
                    if pass_index == 0:
                        window.show()
                        window.navigation.setCurrentRow(3)
                        menu = window.position_columns.menu
                        menu.popup(window.position_columns.button.mapToGlobal(window.position_columns.button.rect().bottomLeft()))
                        self.app.processEvents()
                        menu.setActiveAction(window.position_columns.actions[4])
                        QTest.keyClick(menu, Qt.Key.Key_Return)
                    self.assertFalse(window.positions.isColumnHidden(4))
                    self.assertEqual(store.load()['position_columns'], [0, 1, 2, 4, 5, 8, 9])
                    self.assertTrue(window.position_columns.actions[0].isChecked())
                    self.assertFalse(window.position_columns.actions[0].isEnabled())
                finally:
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_failed_preference_write_keeps_accepted_columns_and_explains_failure(self):
        self.window.position_columns.save = lambda values: (_ for _ in ()).throw(OSError('synthetic write failure'))
        self.window.position_columns.actions[4].trigger()
        self.assertTrue(self.window.positions.isColumnHidden(4))
        self.assertFalse(self.window.position_columns.actions[4].isChecked())
        self.assertEqual(self.window.notice.text(), ui_text('m2t.columns_failed'))

    def test_empty_positions_and_orders_explain_and_navigate_without_commands(self):
        self.window.apply_state(replace(self.window.state, version=2, positions=(), orders=(), strategies=()))
        for overlay in (self.window.positions_empty, self.window.orders_empty):
            self.assertTrue(overlay.isVisible())
            self.assertTrue(overlay.reason.text())
            self.assertTrue(overlay.parentWidget().rect().contains(overlay.geometry()))
            self.assertTrue(overlay.next.accessibleName())
            overlay.next.setFocus()
            QTest.keyClick(overlay.next, Qt.Key.Key_Space)
            self.assertEqual(self.window.navigation.currentRow(), 1)
            self.window.navigation.setCurrentRow(3)
        self.assertEqual(self.facade.commands, [])
        self.assertTrue(self.window.dashboard.strategy_summary.isVisibleTo(self.window.pages.widget(0)))
        self.assertEqual(self.window.dashboard.strategy_setup.property('role'), 'primary')

    def test_unknown_disconnected_broker_snapshot_does_not_claim_account_has_zero_exposure(self):
        for environment, account in ((Environment.BROKER_SIMULATION, 'sim-futures'), (Environment.LIVE, 'live-stock')):
            with self.subTest(environment=environment):
                self.window.apply_state(
                    replace(
                        self.window.state,
                        version=self.window.state.version + 1,
                        environment=environment,
                        account_ref=account,
                        engine_state='DISCONNECTED',
                        market_connection='DISCONNECTED',
                        financial_facts_verified=False,
                        positions=(),
                        orders=(),
                    )
                )
                self.assertFalse(self.window.state.financial_facts_verified)
                for overlay in (self.window.positions_empty, self.window.orders_empty):
                    self.assertTrue(overlay.isVisible())
                    self.assertIn('尚無可顯示的', overlay.reason.text())
                    self.assertNotIn('目前沒有', overlay.reason.text())
                    self.assertNotIn('策略', overlay.reason.text())
                    self.assertEqual(overlay.reason.accessibleName(), overlay.reason.text())
                    self.assertTrue(overlay.next.isEnabled())
                self.assertEqual(self.facade.commands, [])
