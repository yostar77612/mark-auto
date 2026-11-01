"""Order report display/preferences preserve canonical facts and row identity."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.widgets import selected_id
from desktop_app.strings.catalog import ui_text
from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.application.contracts import OrderView
from quantlab.trading.domain.models import QuantityUnit, Side
from tests import test_trading_ui as support
from tests import test_m2_manual_ui as manual_support
import trading_runtime


class OrderReportTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)

    def setUp(self):
        self.facade = support.RecordingFacade()
        self.account = 'sinopac-masked-long-alias-012345678901234567890123'
        self.order = OrderView('canonical-order-id', 'TWSE:2330', Side.BUY, 2000, 500, QuantityUnit.SHARE, 'ACCEPTED', False, self.account)
        self.facade.state = replace(self.facade.state, orders=(self.order,))
        self.windows = []
        self.window = self.open_window()

    def open_window(self, **options):
        window = TradingWindow(self.facade, self.facade.state, **options)
        window.poll.stop()
        window.setProperty('allow_close_for_tests', True)
        window.navigation.setCurrentRow(3)
        self.windows.append(window)
        return window

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(self.facade.commands, [])

    def test_default_six_columns_fit_populated_1366_and_preserve_account_and_selection(self):
        window = self.window
        with patch('desktop_app.features.trading.window.fit_available_screen'):
            window.resize(1366, 768)
            window.show()
            self.app.processEvents()
        self.assertEqual((window.width(), window.height()), (1366, 768))
        self.assertEqual([i for i in range(7) if not window.orders.isColumnHidden(i)], [0, 1, 2, 3, 4, 5])
        self.assertEqual([i for i in range(12) if not window.positions.isColumnHidden(i)], [0, 1, 2, 5, 8, 9])
        self.assertEqual(window.orders.item(0, 6).text(), self.account)
        self.assertEqual(window.orders.item(0, 6).toolTip(), self.account)
        self.assertEqual(window.orders.horizontalScrollBar().maximum(), 0)
        self.assertEqual(window.pages.widget(3).horizontalScrollBar().maximum(), 0)
        cell = window.orders.item(0, 0)
        self.assertGreaterEqual(window.orders.columnWidth(0), window.orders.fontMetrics().horizontalAdvance(cell.text()) + 4)
        window.orders.selectRow(0)
        window.apply_state(replace(window.state, version=window.state.version + 1, orders=(replace(self.order, filled=1000),)))
        self.assertEqual(selected_id(window.orders), 'canonical-order-id')
        self.assertEqual(window.orders.item(0, 6).text(), self.account)
        self.assertEqual(window.state.orders[0].quantity, 2000)
        self.assertEqual(window.state.orders[0].filled, 1000)

    def test_stock_total_and_partial_fill_use_lots_with_exact_share_tooltips(self):
        table = self.window.orders
        self.assertEqual(table.item(0, 2).text(), '2 ' + ui_text('m2t.lots'))
        self.assertEqual(table.item(0, 3).text(), '0.5 ' + ui_text('m2t.lots'))
        self.assertEqual(table.item(0, 2).toolTip(), '2,000 ' + ui_text('v2.shares'))
        self.assertEqual(table.item(0, 3).toolTip(), '500 ' + ui_text('v2.shares'))
        for column in (2, 3):
            self.assertTrue(table.item(0, column).textAlignment() & Qt.AlignmentFlag.AlignRight)
        self.assertEqual(self.window.state.orders[0], self.order)

    def test_future_total_and_fill_keep_contract_units(self):
        future = replace(self.order, instrument_id='TAIFEX:TMF:202611', quantity=1, filled=1, unit=QuantityUnit.CONTRACT)
        self.window.apply_state(replace(self.window.state, version=2, orders=(future,)))
        for column in (2, 3):
            self.assertEqual(self.window.orders.item(0, column).text(), '1 ' + ui_text('v2.contracts'))
            self.assertEqual(self.window.orders.item(0, column).toolTip(), '1 ' + ui_text('v2.contracts'))
        self.assertEqual(self.window.state.orders[0], future)

    def test_keyboard_account_choice_persists_without_erasing_position_or_other_preferences(self):
        with tempfile.TemporaryDirectory(prefix='m2-order-columns-') as folder:
            root = Path(folder)
            store = SettingsStore(root / 'trading-presentation-v1.json')
            position_choice = [0, 1, 2, 4, 5, 8, 9]
            store.save({'position_columns': position_choice, 'future_preference': {'preserved': True}})
            first = self.open_window(**trading_runtime._presentation_options(root))
            first.show()
            self.app.processEvents()
            columns = first.order_columns
            self.assertTrue(columns.button.accessibleName())
            self.assertTrue(columns.button.toolTip())
            columns.menu.popup(columns.button.mapToGlobal(columns.button.rect().bottomLeft()))
            columns.menu.setActiveAction(columns.actions[6])
            QTest.keyClick(columns.menu, Qt.Key.Key_Return)
            self.assertFalse(first.orders.isColumnHidden(6))
            self.assertEqual(store.load()['order_columns'], [0, 1, 2, 3, 4, 5, 6])
            self.assertEqual(store.load()['position_columns'], position_choice)
            first.position_columns.actions[4].trigger()
            self.assertEqual(store.load()['position_columns'], [0, 1, 2, 5, 8, 9])
            self.assertEqual(store.load()['order_columns'], [0, 1, 2, 3, 4, 5, 6])
            self.assertEqual(store.load()['future_preference'], {'preserved': True})
            restored = self.open_window(**trading_runtime._presentation_options(root))
            self.assertFalse(restored.orders.isColumnHidden(6))
            self.assertTrue(restored.positions.isColumnHidden(4))
            self.assertFalse(restored.order_columns.actions[0].isEnabled())
            self.assertEqual(restored.orders.item(0, 6).text(), self.account)

    def test_invalid_saved_order_index_uses_defaults_and_failed_save_keeps_accepted_choice(self):
        window = self.open_window(order_columns=[0, 7])
        self.assertEqual([i for i in range(7) if not window.orders.isColumnHidden(i)], [0, 1, 2, 3, 4, 5])
        window.order_columns.save = lambda values: (_ for _ in ()).throw(OSError('fake write failure'))
        window.order_columns.actions[6].trigger()
        self.assertTrue(window.orders.isColumnHidden(6))
        self.assertFalse(window.order_columns.actions[6].isChecked())
        self.assertEqual(window.notice.text(), ui_text('m2t.columns_failed'))

    def test_hidden_account_still_appears_in_native_cancel_confirmation(self):
        facade = manual_support.ManualFacade()
        window = TradingWindow(facade, facade.state)
        window.poll.stop()
        window.setProperty('allow_close_for_tests', True)
        self.windows.append(window)
        window.orders.selectRow(0)
        self.assertTrue(window.manual_controls.cancel.isEnabled())
        dialogs = []

        def cancel(dialog):
            dialogs.append(dialog.text())
            self.assertEqual(dialog.defaultButton(), dialog.button(QMessageBox.StandardButton.Cancel))
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            window.manual_controls.cancel.click()
        self.assertEqual(len(dialogs), 1)
        self.assertIn(facade.state.account_ref, dialogs[0])
        self.assertIn('owned-order', dialogs[0])
        self.assertEqual(window.orders.item(0, 6).text(), facade.state.account_ref)
        self.assertEqual(facade.commands, [])


if __name__ == '__main__':
    unittest.main()
