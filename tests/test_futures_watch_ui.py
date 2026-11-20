"""Offscreen terminal behaviour for watch-only futures: tab, search, quote text, order book and alert dialog."""

from dataclasses import replace
from decimal import Decimal
import time
import unittest

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from desktop_app.components.charts import CandlestickChart
from desktop_app.features.market.workspace import WorkspacePanel
from desktop_app.features.trading.alert_panel import AlertRuleDialog
from desktop_app.features.trading.market_terminal import MarketTerminalWidget
from desktop_app.features.trading.market_terminal_layout import PANEL_IDS, terminal_preset
from desktop_app.features.trading.market_terminal_rows import price_number, quote_values
from desktop_app.features.trading.order_book_panel import OrderBookPanel
from desktop_app.strings.catalog import ui_text
from quantlab.research_core.adapters.market_layout import LayoutStore
from quantlab.trading.application.contracts import MarketHealthView, MarketWatchView
from quantlab.trading.application.order_book_contracts import OrderBookView
from quantlab.trading.domain.alerts import RULE_KINDS, SCANNER_KINDS
from quantlab.trading.domain.watch import FIXED_INDICES, watch_future
from tests.test_market_terminal_ui import NOW, OTHER, STOCK, FakeFacade

BIG, SMALL, MICRO = (watch_future(code) for code in ('TXFR1', 'MXFR1', 'TMFR1'))


def future_quote(instrument, price='20123', volume=45678):
    return MarketWatchView(
        instrument_id=instrument.instrument_id,
        price=Decimal(price),
        reference_price=Decimal('20000'),
        change=Decimal(price) - Decimal('20000'),
        change_percent=(Decimal(price) - Decimal('20000')) / Decimal('200'),
        source_at=NOW,
        received_at=NOW,
        trade_date=NOW.date(),
        session='NIGHT',
        source='SHIOAJI',
        health=MarketHealthView(instrument.instrument_id, 'LIVE'),
        total_volume=volume,
    )


class FuturesFacade(FakeFacade):
    def __init__(self):
        super().__init__()
        self.state = replace(self.state, market_watch=(*self.state.market_watch, future_quote(BIG)))

    def symbol_directory(self):
        return STOCK, OTHER, BIG, SMALL, MICRO, *FIXED_INDICES

    def order_book(self, instrument_id):
        if instrument_id.startswith('TAIFEX:'):
            return OrderBookView(instrument_id)
        return super().order_book(instrument_id)


class FuturesTerminalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = FuturesFacade()
        self.widget = MarketTerminalWidget(
            self.facade,
            CandlestickChart(),
            self.facade.state,
            layout_store=LayoutStore(panel_ids=PANEL_IDS, default_layout=terminal_preset()),
            index_chart=CandlestickChart(show_volume=False),
            panel_factory=WorkspacePanel,
        )
        self.widget.resize(1366, 768)
        self.widget.show()
        self.wait_for(lambda: bool(self.widget.chart.bars) and not self.widget._requests)

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone(3000)
        self.app.processEvents()
        if shiboken6.isValid(self.widget):
            shiboken6.delete(self.widget)
        self.app.processEvents()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(predicate())

    def test_a_futures_tab_lists_the_three_contracts_with_their_quotes(self):
        tabs = self.widget.tabs
        self.assertEqual(
            [ui_text('terminal.tab_watchlist'), ui_text('terminal.tab_index'), ui_text('terminal.tab_future')], [tabs.tabText(i) for i in range(3)]
        )
        table = self.widget.future_table
        self.assertEqual(['TXFR1', 'MXFR1', 'TMFR1'], [table.item(row, 0).text() for row in range(table.rowCount())])
        self.assertEqual('臺股期貨近月', table.item(0, 1).text())
        self.assertEqual(
            ['20123', '+123.00', '+0.62%', ui_text('terminal.volume_future').format('45,678')], [table.item(0, column).text() for column in range(2, 6)]
        )
        self.assertEqual(ui_text('watch.unknown'), table.item(1, 2).text())  # an unsubscribed contract has no quote yet

    def test_choosing_a_futures_row_selects_it_and_it_can_be_watched(self):
        table = self.widget.future_table
        self.widget.select_instrument(table.item(0, 0).data(Qt.ItemDataRole.UserRole))
        self.wait_for(lambda: self.widget.current_instrument == BIG.instrument_id and not self.widget._requests)
        self.assertEqual((BIG.instrument_id, '1m'), self.facade.selections[-1])
        self.widget.toggle_current_watch()
        self.wait_for(lambda: self.facade.state.watchlist == (BIG.instrument_id,) and not self.widget._requests)
        self.assertEqual(ui_text('terminal.remove_watch'), self.widget.toggle_watch.text())
        self.assertEqual(BIG.instrument_id, self.widget.table.item(0, 0).data(Qt.ItemDataRole.UserRole))

    def test_search_finds_a_future_by_code_and_by_name_and_labels_it(self):
        for query in ('txfr1', '臺股期貨', '微型'):
            self.widget.search.input.setText(query)
            self.widget.search.search()
            labels = [self.widget.search.results.item(row).text() for row in range(self.widget.search.results.count())]
            self.assertTrue(labels and labels[0].endswith(ui_text('terminal.exchange_taifex')), (query, labels))
        self.widget.search.input.setText('txfr1')
        self.widget.search.search()
        QTest.keyClick(self.widget.search.input, Qt.Key.Key_Return)
        self.wait_for(lambda: self.widget.current_instrument == BIG.instrument_id and not self.widget._requests)
        self.assertEqual((), self.facade.state.watchlist)  # selecting never edits the watchlist

    def test_the_order_book_panel_says_futures_have_no_five_levels(self):
        panel = OrderBookPanel()
        self.addCleanup(panel.deleteLater)
        panel.render_view(OrderBookView(BIG.instrument_id), '#c62828', '#16803c')
        self.assertEqual(ui_text('orderbook.no_future'), panel.notice.text())
        panel.render_view(OrderBookView(FIXED_INDICES[0].instrument_id), '#c62828', '#16803c')
        self.assertEqual(ui_text('orderbook.no_index'), panel.notice.text())

    def test_future_quotes_use_whole_points_and_contract_volume(self):
        view = future_quote(BIG)
        self.assertEqual('20123', price_number(view.price, BIG))
        values = quote_values(BIG, view)
        self.assertEqual(('TXFR1', '臺股期貨近月', '20123', '+123.00', '+0.62%'), values[:5])
        self.assertEqual(ui_text('terminal.volume_future').format('45,678'), values[5])
        self.assertEqual(ui_text('terminal.volume_stock').format('1,234'), quote_values(STOCK, replace(future_quote(STOCK), total_volume=1234))[5])


class FuturesAlertDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_future_cannot_choose_stock_only_signal_kinds_and_is_told_why(self):
        dialog = AlertRuleDialog(BIG.instrument_id)
        self.addCleanup(dialog.deleteLater)
        offered = [dialog.kind.itemData(i) for i in range(dialog.kind.count())]
        self.assertEqual([kind for kind in RULE_KINDS if kind not in SCANNER_KINDS], offered)
        self.assertEqual(8, len(offered))
        note = dialog.findChild(type(dialog.error), 'alert_future_note')
        self.assertIsNotNone(note)
        self.assertEqual(ui_text('alert.future_stock_only'), note.text())

    def test_a_stock_keeps_all_twelve_kinds_and_no_note(self):
        dialog = AlertRuleDialog(STOCK.instrument_id)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(12, dialog.kind.count())
        self.assertIsNone(dialog.findChild(type(dialog.error), 'alert_future_note'))

    def test_creating_a_future_rule_from_the_dialog_produces_an_instrument_rule(self):
        dialog = AlertRuleDialog(BIG.instrument_id)
        self.addCleanup(dialog.deleteLater)
        dialog.editors['price'].setText('20500')
        dialog.create_rule()
        self.assertEqual((BIG.instrument_id, 'INSTRUMENT'), (dialog.rule.instrument_id, dialog.rule.scope))


if __name__ == '__main__':
    unittest.main()
