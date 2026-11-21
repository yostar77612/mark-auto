"""Offline terminal behavior with a recording facade and real chart widgets."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QThreadPool, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractButton, QScrollArea
import shiboken6

from desktop_app.components.charts import CandlestickChart
from desktop_app.features.market.workspace import WorkspacePanel
from desktop_app.features.trading.market_terminal import MarketTerminalWidget
from desktop_app.features.trading.market_terminal_layout import PANEL_IDS, terminal_preset
from desktop_app.features.trading.market_terminal_rows import diagnostic_text, market_summary, quote_values
from desktop_app.features.trading.window import TradingWindow
from desktop_app.strings.catalog import ui_text
from quantlab.research_core.adapters.market_layout import LayoutStore, FILE_NAME
from quantlab.trading.application.contracts import MarketHealthView, MarketSeriesPage, MarketWatchView, OverviewMarketSummary, UiReceipt, UiState
from quantlab.trading.application.screener_contracts import DownloadedRowView, ScreenerQuery, ScreenerRowView, ScreenerView
from quantlab.trading.domain.screener import ScreenerParams
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind

NOW = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
STOCK = WatchInstrument('TWSE:2330', WatchKind.STOCK, 'TSE', '2330', '台積電')
OTHER = WatchInstrument('TWSE:2317', WatchKind.STOCK, 'TSE', '2317', '鴻海')


def quote(instrument=STOCK, freshness='LIVE', price=Decimal('100')):
    return MarketWatchView(
        instrument_id=instrument.instrument_id,
        price=price,
        reference_price=Decimal('99'),
        change=Decimal('1'),
        change_percent=Decimal('1.01'),
        source_at=NOW,
        received_at=NOW,
        trade_date=NOW.date(),
        session='DAY',
        source='SHIOAJI',
        health=MarketHealthView(instrument.instrument_id, freshness),
        total_volume=1234,
    )


def state(watches=()):
    views = tuple(quote(item) for item in (STOCK, OTHER, *FIXED_INDICES))
    return UiState(
        Environment.LOCAL,
        'local-stock',
        'CONNECTED',
        '',
        Decimal('0'),
        None,
        None,
        '',
        1,
        '',
        True,
        market_watch=views,
        market_connection='CONNECTED',
        market_health=OverviewMarketSummary(tuple(view.health for view in views), 2 + len(watches)),
        watchlist=watches,
    )


class FakeFacade:
    def __init__(self, watches=()):
        self.state = state(watches)
        self.queries, self.selections, self.commands = [], [], []
        self.current, self.temporary = FIXED_INDICES[0].instrument_id, ''
        self.subscribe_calls, self.unsubscribe_calls = [], []

    def symbol_directory(self):
        return STOCK, OTHER, *FIXED_INDICES

    def market_preferences(self):
        return self.current

    def market_status(self):
        return SimpleNamespace(
            connected=True,
            subscription_count=2 + len(self.state.watchlist) + bool(self.temporary),
            subscription_limit=20,
            temporary_id=self.temporary,
            usage=None,
            warning_code='',
            history_state=SimpleNamespace(running='', paused=False, history_error=()),
        )

    def select_market_instrument(self, key, period):
        self.current = key
        self.selections.append((key, period))
        temporary = key if key not in self.state.watchlist and key not in {item.instrument_id for item in FIXED_INDICES} else ''
        if self.temporary and self.temporary != temporary:
            self.unsubscribe_calls.append(self.temporary)
        if temporary and temporary != self.temporary:
            self.subscribe_calls.append(temporary)
        self.temporary = temporary
        return True

    def snapshot(self):
        return self.state

    def execute(self, command):
        self.commands.append(command)
        self.state = replace(self.state, watchlist=command.watchlist)
        # A temporary -> watch subscription is retained, not duplicated.
        if self.temporary in self.state.watchlist:
            self.temporary = ''
        return UiReceipt(True, 'completed', '')

    def order_book(self, instrument_id):
        from quantlab.trading.application.order_book_contracts import OrderBookView, TapeEntry
        from quantlab.trading.domain.bidask import BidAskSnapshot

        if instrument_id.startswith('INDEX:'):
            return OrderBookView(instrument_id)
        bids = tuple(Decimal('100') - Decimal('0.5') * level for level in range(5))
        asks = tuple(Decimal('100.5') + Decimal('0.5') * level for level in range(5))
        tape = tuple(
            TapeEntry(NOW - timedelta(seconds=index), Decimal('100.5') if index % 2 == 0 else Decimal('100'), 1 + index, 'BUY' if index % 2 == 0 else 'SELL')
            for index in range(12)
        )
        return OrderBookView(
            instrument_id,
            True,
            BidAskSnapshot(instrument_id, NOW, bids, (21, 35, 18, 40, 12), asks, (9, 14, 30, 22, 17)),
            False,
            tape,
            48,
            36,
            2,
            NOW - timedelta(minutes=30),
        )

    def market_series(self, query):
        self.queries.append(query)
        bar = LiveBar(
            query.instrument_id, NOW, NOW + timedelta(minutes=1), NOW.date(), 'DAY', Decimal('99'), Decimal('102'), Decimal('98'), Decimal('100'), 9, True
        )
        return MarketSeriesPage(query.instrument_id, query.period, (bar,), total=1, market_revision=1)


class TerminalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = FakeFacade()
        self.store = LayoutStore(panel_ids=PANEL_IDS, default_layout=terminal_preset())
        self.widget = MarketTerminalWidget(
            self.facade,
            CandlestickChart(),
            self.facade.state,
            layout_store=self.store,
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

    def test_search_keyboard_switches_without_adding_and_four_periods(self):
        for query, key in (('2330', STOCK.instrument_id), ('台積', STOCK.instrument_id), ('ix0001', FIXED_INDICES[0].instrument_id)):
            self.widget.search.input.setText(query)
            self.widget.search.search()
            QTest.keyClick(self.widget.search.input, Qt.Key.Key_Return)
            self.wait_for(lambda: self.widget.current_instrument == key and not self.widget._requests)
            self.assertEqual(self.facade.state.watchlist, ())
        self.assertEqual(tuple(self.widget.period_buttons), ('1m', '5m', '15m', '1d'))
        self.widget.select_period('15m')
        self.wait_for(lambda: self.widget.period == '15m' and not self.widget._requests)
        self.widget.select_instrument(STOCK.instrument_id)
        self.wait_for(lambda: not self.widget._requests)
        self.assertEqual(self.widget.period, '1m')
        self.widget.select_instrument(FIXED_INDICES[0].instrument_id)
        self.wait_for(lambda: not self.widget._requests)
        self.assertEqual(self.widget.period, '15m')

    def test_temporary_release_watch_promotion_and_full_feedback(self):
        self.widget.select_instrument(STOCK.instrument_id)
        self.wait_for(lambda: not self.widget._requests)
        self.widget.toggle_current_watch()
        self.wait_for(lambda: STOCK.instrument_id in self.widget.state.watchlist and not self.widget._requests)
        self.assertEqual(self.facade.subscribe_calls, [STOCK.instrument_id])
        self.assertEqual(self.widget.toggle_watch.text(), ui_text('terminal.remove_watch'))
        self.widget.toggle_current_watch()
        self.wait_for(lambda: not self.widget.state.watchlist and not self.widget._requests)
        self.widget.select_instrument(OTHER.instrument_id)
        self.wait_for(lambda: not self.widget._requests)
        self.assertIn(STOCK.instrument_id, self.facade.unsubscribe_calls)
        full = replace(self.facade.state, watchlist=tuple('TWSE:' + str(code) for code in range(1000, 1018)))
        self.widget.render(full)
        self.widget.toggle_current_watch()
        self.assertIn('18', self.widget.message.text())
        self.assertEqual(self.widget.message_timer.interval(), 5000)

    def test_six_columns_numeric_sort_and_original_order(self):
        self.facade.state = state((STOCK.instrument_id, OTHER.instrument_id))
        self.widget.render(self.facade.state)
        self.assertEqual(self.widget.table.columnCount(), 6)
        self.assertEqual([self.widget.table.item(row, 0).text() for row in range(2)], ['2330', '2317'])
        self.assertFalse(self.widget.table.horizontalScrollBar().isVisible())
        self.assertEqual(self.widget.table.item(0, 5).text(), '1,234張')
        self.assertEqual(self.widget.table.item(0, 2).text(), '100.0')
        unknown = quote(freshness='UNKNOWN')
        self.widget.render(replace(self.facade.state, market_watch=(unknown, quote(OTHER))))
        self.assertEqual(self.widget.table.item(0, 2).text(), ui_text('watch.unknown'))
        self.assertEqual(self.widget.table.item(0, 2).foreground().color().name(), '#808080')
        self.widget.render(replace(self.facade.state, market_watch=(quote(price=Decimal('100')), quote(OTHER, price=Decimal('9')))))
        self.widget.sort_quotes(self.widget.table, 2)
        self.assertEqual(self.widget.table.item(0, 0).text(), '2317')
        self.widget.sort_quotes(self.widget.table, 2)
        self.assertEqual(self.widget.table.item(0, 0).text(), '2330')

    def test_latest_selection_wins_and_alert_time_focuses_chart(self):
        self.widget.select_instrument(STOCK.instrument_id)
        self.widget.select_instrument(OTHER.instrument_id)
        self.widget.select_instrument(FIXED_INDICES[0].instrument_id, NOW)
        self.wait_for(lambda: not self.widget._requests)
        self.assertEqual(self.facade.current, FIXED_INDICES[0].instrument_id)
        self.assertEqual(self.widget.chart.bars[0].contract_id, FIXED_INDICES[0].instrument_id)
        self.assertEqual(self.widget.chart.crosshair_index, 0)

    def test_destroying_the_widget_cancels_a_request_still_in_flight(self):
        import threading

        from desktop_app.features.trading import market_watch

        other = MarketTerminalWidget(
            self.facade,
            CandlestickChart(),
            self.facade.state,
            layout_store=self.store,
            index_chart=CandlestickChart(show_volume=False),
            panel_factory=WorkspacePanel,
        )
        self.wait_for(lambda: not other._requests)
        gate, seen = threading.Event(), []
        other._submit(lambda: gate.wait(5), lambda value, error: seen.append(value), quiet=True)
        token = next(iter(other._requests)).token
        shiboken6.delete(other)  # never the shared fixture: tearDown deletes self.widget again
        gate.set()
        self.wait_for(lambda: token not in market_watch._LIVE_RESULTS)
        self.assertEqual(seen, [])

    def test_status_usage_pause_and_unknown_index(self):
        self.widget._terminal_status = SimpleNamespace(
            subscription_count=4,
            subscription_limit=20,
            temporary_id=STOCK.instrument_id,
            usage=SimpleNamespace(used_bytes=256 * 1024 * 1024, limit_bytes=512 * 1024 * 1024),
            warning_code='history_quota_low',
            history_state=SimpleNamespace(paused=True),
        )
        self.widget._render_status()
        self.assertIn('4/20', self.widget.status.text())
        self.assertIn('17', self.widget.status.text())
        self.assertIn('50.0%', self.widget.status.text())
        self.assertEqual(self.widget.history_error.text(), ui_text('terminal.quota_paused'))

    def test_search_debounce_enter_before_delay_and_escape(self):
        self.widget.search.input.setFocus()
        QTest.keyClicks(self.widget.search.input, '2330')
        self.assertTrue(self.widget.search.timer.isActive())
        QTest.keyClick(self.widget.search.input, Qt.Key.Key_Return)
        self.wait_for(lambda: self.widget.current_instrument == STOCK.instrument_id and not self.widget._requests)
        self.assertEqual(self.widget.search.input.text(), STOCK.code + ' ' + STOCK.name)
        QTest.keyClick(self.widget.search.input, Qt.Key.Key_Escape)
        self.assertEqual(self.widget.search.input.text(), '')
        self.assertTrue(self.widget.search.results.isHidden())

    def test_index_uses_latest_page_and_preserves_chart_view_for_identical_data(self):
        self.widget.select_instrument(STOCK.instrument_id)
        self.wait_for(lambda: not self.widget._requests)
        original = self.facade.market_series
        requests = []

        def paged(query):
            page = original(query)
            if query.instrument_id == FIXED_INDICES[0].instrument_id:
                requests.append(query)
                return replace(page, total=1001, next_offset=500 if query.offset == 0 else None)
            return page

        self.facade.market_series = paged
        self.widget.chart._count = 22
        self.widget.load_series()
        self.wait_for(lambda: not self.widget._requests)
        self.assertTrue(any(query.offset == 1000 for query in requests))
        self.assertEqual(self.widget.chart._count, 22)

    def test_forming_updates_preserve_view_and_same_instrument_alert_focuses(self):
        original = self.facade.market_series
        self.widget.chart._count = 22

        def changed(query):
            page = original(query)
            return replace(page, bars=(replace(page.bars[0], close=Decimal('101')),))

        self.facade.market_series = changed
        self.widget.load_series()
        self.wait_for(lambda: not self.widget._requests)
        self.assertEqual(self.widget.chart.bars[-1].close, Decimal('101'))
        self.assertEqual(self.widget.chart._count, 22)
        self.widget.chart.crosshair_index = None
        self.widget.select_instrument(self.widget.current_instrument, NOW)
        self.wait_for(lambda: not self.widget._requests)
        self.assertEqual(self.widget.chart.crosshair_index, 0)

    def test_disconnected_selection_does_not_claim_subscription_full(self):
        original = self.facade.market_status

        def status():
            value = original()
            value.connected = False
            return value

        self.facade.market_status = status
        self.facade.select_market_instrument = lambda key, period: False
        self.facade.state = replace(self.facade.state, market_connection='DISCONNECTED')
        self.widget.select_instrument(STOCK.instrument_id)
        self.wait_for(lambda: not self.widget._requests)
        self.assertFalse(self.widget._history_only)
        self.assertNotIn(ui_text('terminal.history_only'), self.widget.freshness.text())
        self.assertNotIn(ui_text('connection.failure.history_only'), self.widget.freshness.text())

    def test_presets_named_persistence_and_responsive_layout(self):
        for size in ((1366, 768), (1920, 1080)):
            self.widget.resize(*size)
            self.app.processEvents()
            self.assertEqual(self.widget.size().toTuple(), size)
            self.assertFalse(self.widget.findChildren(QScrollArea))
            self.assertGreater(self.widget.chart.width(), 400)
            self.assertGreater(self.widget.chart.height(), 200)
            self.assertLessEqual(self.widget.workspace.splitter.width(), self.widget.width())
        for panel in self.widget.workspace.panels.values():
            QTest.keyClick(panel.handle, Qt.Key.Key_C)
            self.assertTrue(panel.content.isHidden())
            QTest.keyClick(panel.handle, Qt.Key.Key_C)
            self.assertFalse(panel.content.isHidden())
        self.widget.workspace.apply_preset('chart_focus')
        self.assertTrue(self.widget.workspace.panels['index'].content.isHidden())
        self.widget.workspace.reset()
        self.assertFalse(self.widget.workspace.panels['index'].content.isHidden())
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = LayoutStore(folder, panel_ids=PANEL_IDS, file_name='market-terminal-layout-v1.json', default_layout=terminal_preset())
            self.widget.workspace.store = store
            self.assertTrue(self.widget.workspace.save_named('Research'))
            self.widget.workspace.move_panel('index', 'left')
            self.assertTrue(self.widget.workspace.restore_named('Research'))
            restored = LayoutStore(folder, panel_ids=PANEL_IDS, file_name='market-terminal-layout-v1.json', default_layout=terminal_preset())
            self.assertEqual(restored.layouts['Research'], terminal_preset())
            self.assertFalse((Path(folder) / FILE_NAME).exists())

    def test_switching_back_to_a_period_paints_its_last_bars_at_once_and_history_refreshes_itself(self):
        self.assertIsNone(self.widget.findChild(QAbstractButton, 'terminal_refresh_history'))
        key = self.widget.current_instrument
        self.widget.select_period('5m')
        self.wait_for(lambda: self.widget.period == '5m' and not self.widget._requests)
        five = self.widget.chart.bars
        self.widget.select_period('1m')
        self.wait_for(lambda: self.widget.period == '1m' and not self.widget._requests)
        self.assertNotEqual(self.widget.chart.bars, five)
        # Before any answer arrives, the cached 5m page is already on the chart.
        self.widget.select_period('5m')
        self.assertEqual(self.widget.chart.bars, five)
        self.assertEqual(self.widget._last_series[:2], (key, '5m'))
        self.wait_for(lambda: not self.widget._requests)
        self.assertEqual(self.widget.chart.bars, five)

    def test_accessible_controls_and_status_diagnostics(self):
        self.assertEqual(self.widget.chart.price_rect.top(), 86)  # the plain chart keeps its three header rows
        self.assertEqual(self.widget.index_chart.price_rect.top(), 12)
        for control in (
            *self.widget.findChildren(QAbstractButton),
            self.widget.search.input,
            self.widget.search.results,
            self.widget.table,
            self.widget.index_table,
        ):
            if control.objectName() and not control.objectName().startswith('qt_'):
                self.assertTrue(control.accessibleName(), control.objectName())
        summary = OverviewMarketSummary(tuple(MarketHealthView(str(code), 'LIVE') for code in range(10)), 10)
        self.assertEqual(market_summary(summary), ui_text('terminal.all_live'))
        bad = replace(summary, instruments=tuple(replace(item, freshness='STOPPED') for item in summary.instruments))
        self.assertIn(ui_text('terminal.others').format(7), market_summary(bad))
        self.assertNotIn('3 ', market_summary(bad))
        text = diagnostic_text(quote(), Environment.BROKER_SIMULATION)
        self.assertIn('09:00:00', text)
        self.assertNotIn('+00:00', text)
        self.assertIn(ui_text('terminal.source_sim'), text)
        self.assertEqual(quote_values(FIXED_INDICES[0], quote(FIXED_INDICES[0]))[-1], ui_text('watch.unknown'))

    def test_real_trading_window_contains_terminal_at_both_sizes(self):
        window = TradingWindow(self.facade, self.facade.state, market_watch=self.widget)
        window.poll.stop()
        try:
            for width, height in ((1366, 768), (1920, 1080)):
                screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, width + 40, height + 80))
                with patch.object(window, 'screen', return_value=screen):
                    window.resize(width, height)
                    window.navigation.setCurrentRow(2)
                    window.show()
                    self.wait_for(lambda: not self.widget._requests)
                    self.app.processEvents()
                    self.assertEqual(window.size().toTuple(), (width, height))
                    self.assertFalse(window.pages.currentWidget().findChildren(QScrollArea))
                    self.assertGreater(self.widget.chart.height(), 180)
                    self.assertGreater(self.widget.chart.width(), 500)
                    self.assertLessEqual(self.widget.workspace.splitter.width(), self.widget.width())
                    self.assertFalse(self.widget.table.horizontalScrollBar().isVisible())
                    self.assertLessEqual(
                        self.widget.table.columnViewportPosition(5) + self.widget.table.columnWidth(5), self.widget.table.viewport().width() + 1
                    )
        finally:
            window.poll.stop()
            QThreadPool.globalInstance().waitForDone(3000)
            self.app.processEvents()
            self.widget.setParent(None)
            shiboken6.delete(window)


class ScreenerFacade(FakeFacade):
    def __init__(self):
        super().__init__()
        self.screener_queries, self.screener_saved, self.params, self.fail = [], [], ScreenerParams(), False
        self.state_name, self.code, self.breakout_ready = 'LIVE', '', False
        self.gates, self.settings_fail, self.save_gate = {}, False, None

    def screener(self, query):
        self.screener_queries.append(query)
        gate = self.gates.get(query)
        if gate is not None:
            gate.wait(3)  # the reply is held until the test lets it go
        if self.fail:
            raise RuntimeError('screener down')
        if query.list_id == 'DOWNLOADED':
            rows = (DownloadedRowView(STOCK.instrument_id, '2330', '台積電', NOW - timedelta(days=364), NOW, NOW),)
            return ScreenerView('DOWNLOADED', 'ALL', self.state_name, downloaded=rows, min_volume_lots=500, code=self.code)
        if query.list_id == 'BREAKOUT' and self.breakout_ready:
            rows = (
                ScreenerRowView(STOCK.instrument_id, '2330', '台積電', Decimal('2000'), Decimal('3'), Decimal('2.4'), '120', 'YEAR', True),
                ScreenerRowView(OTHER.instrument_id, '2317', '鴻海', Decimal('210'), Decimal('1.5'), Decimal('3.1'), '60', '', False),
            )
            return ScreenerView('BREAKOUT', 'ALL', self.state_name, rows, min_volume_lots=500, data_at=NOW)
        if query.list_id == 'BREAKOUT':
            return ScreenerView('BREAKOUT', 'ALL', 'ACCUMULATING', min_volume_lots=500, progress_days=0, progress_needed=60)
        rows = (
            ScreenerRowView(STOCK.instrument_id, '2330', '台積電', Decimal('110'), Decimal('10'), Decimal('4.5'), 'SURGE_RED', 'YEAR'),
            ScreenerRowView(OTHER.instrument_id, '2317', '鴻海', Decimal('90'), Decimal('-8'), Decimal('3.2'), 'SURGE_BLACK', 'DOWNLOADING'),
        )
        wanted = {'ALL': ('SURGE_RED', 'SURGE_BLACK'), 'RED': ('SURGE_RED',), 'BLACK': ('SURGE_BLACK',)}[query.pattern]
        shown = tuple(row for row in rows if row.label in wanted)
        return ScreenerView('SURGE', query.pattern, self.state_name, shown, min_volume_lots=500, data_at=NOW, code=self.code)

    def screener_settings(self, params=None):
        if self.settings_fail:
            raise RuntimeError('settings down')
        if params is not None and self.save_gate is not None:
            self.save_gate.wait(3)
        if params is not None:
            self.params = params
            self.screener_saved.append(params)
        return self.params


class ScreenerTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = ScreenerFacade()
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
        self.panel = self.widget.screener

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

    def loaded(self, query):
        self.wait_for(lambda: query in self.facade.screener_queries and not self.panel._inflight and not self.panel._requests)

    def open_tab(self):
        self.widget.tabs.setCurrentWidget(self.panel)
        self.loaded(ScreenerQuery('SURGE', 'ALL', ''))

    def cells(self, row):
        return [self.panel.table.item(row, column).text() for column in range(self.panel.table.columnCount())]

    def headers(self):
        return [self.panel.table.horizontalHeaderItem(index).text() for index in range(self.panel.table.columnCount())]

    def test_the_fourth_quote_tab_is_the_screener_and_its_title_names_the_current_list(self):
        tabs = self.widget.tabs
        self.assertEqual(tabs.count(), 4)
        self.assertEqual(tabs.tabText(3), '選股：爆量 ▼')
        self.assertIs(tabs.widget(3), self.panel)
        self.assertEqual(self.facade.screener_queries, [])  # nothing is fetched while another tab is showing

    def test_the_menu_lists_the_choices_in_order_and_ends_with_the_settings(self):
        menu = self.panel.build_menu()
        self.assertEqual(
            [action.text() for action in menu.actions()],
            ['條件選股', '爆量', '帶量突破新高', '', 'K 線資料', '已下載 K 線', '', '條件設定…'],
        )
        self.assertEqual([action.isChecked() for action in menu.actions() if action.isCheckable()], [True, False, False])
        self.assertEqual([action.isEnabled() for action in menu.actions() if action.text() in ('條件選股', 'K 線資料')], [False, False])

    def test_clicking_the_tab_pops_the_menu_and_choosing_a_list_retitles_the_tab_and_loads_it(self):
        self.widget.tabs.tabBar().tabBarClicked.emit(3)
        self.assertTrue(self.panel._menu.isVisible())
        next(action for action in self.panel._menu.actions() if action.text() == '帶量突破新高').trigger()
        self.panel._menu.close()
        self.assertEqual(self.widget.tabs.tabText(3), '選股：帶量突破新高 ▼')
        self.widget.tabs.setCurrentWidget(self.panel)
        self.loaded(ScreenerQuery('BREAKOUT'))
        self.assertEqual(self.panel.info.text(), '資料累積中（0／60 日）')
        self.assertEqual(self.headers(), ['代碼', '名稱', '成交', '漲幅％', '突破(日)', '量÷均量', 'K線'])

    def test_the_surge_list_shows_the_columns_the_kline_marks_and_selects_the_stock(self):
        self.open_tab()
        self.assertEqual(self.headers(), ['代碼', '名稱', '成交', '漲幅％', '量比', '型態', 'K線'])
        self.assertEqual(self.cells(0), ['2330', '台積電', '110.0', '+10.00%', '4.50', '爆量長紅', '✓'])
        self.assertEqual(self.cells(1), ['2317', '鴻海', '90.0', '-8.00%', '3.20', '爆量長黑', '↓'])
        self.assertTrue(self.panel.info.text().startswith('成交量門檻 500 張以上'))
        self.assertTrue(self.panel.filter_row.isVisibleTo(self.panel))
        self.assertEqual({key: item.isChecked() for key, item in self.panel.filters.items()}, {'ALL': True, 'RED': False, 'BLACK': False})
        self.panel._choose(self.panel.table.item(1, 0))
        self.wait_for(lambda: self.facade.selections and self.facade.selections[-1][0] == OTHER.instrument_id and not self.widget._requests)

    def test_the_filter_buttons_ask_the_engine_for_red_or_black_only(self):
        self.open_tab()
        self.panel.filters['RED'].click()
        self.loaded(ScreenerQuery('SURGE', 'RED', ''))
        self.assertEqual(self.panel.table.rowCount(), 1)
        self.assertEqual(self.cells(0)[5], '爆量長紅')
        self.panel.filters['BLACK'].click()
        self.loaded(ScreenerQuery('SURGE', 'BLACK', ''))
        self.assertEqual([self.cells(row)[5] for row in range(self.panel.table.rowCount())], ['爆量長黑'])
        self.assertEqual({key: item.isChecked() for key, item in self.panel.filters.items()}, {'ALL': False, 'RED': False, 'BLACK': True})

    def test_after_the_close_the_list_says_it_is_the_last_close_and_a_reason_code_is_shown(self):
        self.facade.state_name, self.facade.code = 'CLOSED', 'kline_store_unavailable'
        self.open_tab()
        self.assertIn(ui_text('sector.closed'), self.panel.info.text())
        self.assertIn('原因代碼：kline_store_unavailable', self.panel.info.text())
        self.assertEqual(self.panel.table.rowCount(), 2)  # the list still shows

    def test_a_failed_read_shows_a_note(self):
        self.facade.fail = True
        self.open_tab()
        self.assertEqual(self.panel.info.text(), '讀取失敗，稍後自動重試')

    def test_the_downloaded_list_has_its_own_columns_and_no_filter(self):
        self.open_tab()
        self.panel.set_list('DOWNLOADED')
        self.loaded(ScreenerQuery('DOWNLOADED'))
        self.assertFalse(self.panel.filter_row.isVisibleTo(self.panel))
        self.assertEqual(self.headers(), ['代碼', '名稱', '最早', '最新', '最後更新'])
        self.assertEqual(self.cells(0), ['2330', '台積電', '2025-10-31', '2026-10-30', '2026-10-30'])

    def test_the_breakout_list_shows_the_window_the_strength_and_marks_provisional_rows(self):
        self.facade.breakout_ready = True
        self.open_tab()
        self.panel.set_list('BREAKOUT')
        self.loaded(ScreenerQuery('BREAKOUT'))
        self.assertEqual(self.headers(), ['代碼', '名稱', '成交', '漲幅％', '突破(日)', '量÷均量', 'K線'])
        self.assertEqual(self.cells(0), ['2330', '台積電', '2000', '+3.00%', '120 盤中', '2.40', '✓'])
        self.assertEqual(self.cells(1), ['2317', '鴻海', '210.0', '+1.50%', '60', '3.10', ''])
        self.assertFalse(self.panel.filter_row.isVisibleTo(self.panel))
        self.assertEqual(self.panel.info.text(), '資料時間 09:00:00')

    def test_a_late_answer_for_an_earlier_filter_never_draws(self):
        from threading import Event

        self.open_tab()
        drawn = []
        original = self.panel.render_view
        self.panel.render_view = lambda view: (drawn.append((view.list_id, view.pattern)), original(view))[1]
        gate = Event()
        self.facade.gates[ScreenerQuery('SURGE', 'RED', '')] = gate
        self.panel.filters['RED'].click()  # its answer is held back
        self.wait_for(lambda: ScreenerQuery('SURGE', 'RED', '') in self.facade.screener_queries)
        self.panel.filters['BLACK'].click()  # asked for while RED is still outstanding
        gate.set()
        self.loaded(ScreenerQuery('SURGE', 'BLACK', ''))
        self.wait_for(lambda: not self.panel._inflight)
        self.assertNotIn(('SURGE', 'RED'), drawn)
        self.assertEqual([self.cells(row)[5] for row in range(self.panel.table.rowCount())], ['爆量長黑'])

    def test_the_download_message_waits_for_the_engine_and_an_older_poll_never_overwrites_the_newer_answer(self):
        from threading import Event

        self.open_tab()
        drawn = []
        original = self.panel.render_view
        self.panel.render_view = lambda view: (drawn.append(view), original(view))[1]
        gate = Event()
        self.facade.gates[ScreenerQuery('SURGE', 'ALL', '')] = gate
        self.panel.refresh()  # a poll is in flight and held back
        self.wait_for(lambda: self.panel._inflight == 1)
        self.panel.download(STOCK.instrument_id)
        self.assertEqual(self.widget.message.text(), '')  # nothing is promised before the engine has answered
        self.wait_for(lambda: self.widget.message.text() == '已加入下載：2330')
        self.assertEqual(len(drawn), 1)  # the download's own answer drew
        gate.set()
        self.wait_for(lambda: not self.panel._inflight)
        self.assertEqual(len(drawn), 1)  # the older poll arrived late and was dropped

    def test_a_failed_settings_read_says_so_and_opens_no_dialog(self):
        self.open_tab()
        self.facade.settings_fail = True
        self.panel.open_settings()
        self.wait_for(lambda: self.widget.message.text() == '讀取失敗，稍後自動重試')
        self.assertIsNone(getattr(self.panel, 'settings_dialog', None))

    def test_closing_the_settings_dialog_while_the_save_is_in_flight_is_harmless(self):
        from threading import Event
        from unittest.mock import patch

        from PySide6.QtCore import QCoreApplication, QEvent

        self.open_tab()
        self.panel.open_settings()
        self.wait_for(lambda: getattr(self.panel, 'settings_dialog', None) is not None)
        dialog = self.panel.settings_dialog
        self.facade.save_gate = gate = Event()
        errors = []
        with patch('sys.excepthook', lambda *args: errors.append(args)):
            dialog.save()
            dialog.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # the dialog is deleted on close
            gate.set()
            self.wait_for(lambda: bool(self.facade.screener_saved) and not self.panel._requests)
            self.app.processEvents()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.facade.screener_saved), 1)  # the engine kept what was sent

    def test_the_row_menu_adds_to_the_watchlist_and_queues_a_download_through_the_engine(self):
        self.open_tab()
        menu = self.panel.row_menu(STOCK.instrument_id)
        self.assertEqual([action.text() for action in menu.actions()], ['加入自選', '下載近一年 K 線'])
        menu.actions()[1].trigger()
        self.loaded(ScreenerQuery('SURGE', 'ALL', STOCK.instrument_id))
        self.assertEqual(self.widget.message.text(), '已加入下載：2330')
        menu.actions()[0].trigger()
        self.wait_for(lambda: self.facade.state.watchlist == (STOCK.instrument_id,) and not self.widget._requests)

    def test_the_settings_dialog_sends_every_threshold_and_the_download_switches(self):
        self.open_tab()
        self.panel.open_settings()
        self.wait_for(lambda: getattr(self.panel, 'settings_dialog', None) is not None)
        dialog = self.panel.settings_dialog
        self.assertEqual(set(dialog.inputs) | set(dialog.flags), set(ScreenerParams.__dataclass_fields__))
        dialog.inputs['surge_ratio'][0].setValue(4)
        dialog.inputs['quiet_amount'][0].setValue(8000)  # in units of 10,000 NT$
        dialog.inputs['min_volume_lots'][0].setValue(800)
        dialog.flags['download_black'].setChecked(True)
        dialog.flags['download_red'].setChecked(False)
        dialog.flags['download_breakout'].setChecked(False)
        dialog.inputs['window_long'][0].setValue(300)
        dialog.inputs['breakout_volume_multiple'][0].setValue(3)
        dialog.inputs['average_days'][0].setValue(30)
        dialog.save()
        self.wait_for(lambda: bool(self.facade.screener_saved))
        saved = self.facade.screener_saved[-1]
        self.assertEqual(
            (saved.surge_ratio, saved.quiet_amount, saved.min_volume_lots, saved.download_black, saved.download_red),
            (Decimal(4), 80_000_000, 800, True, False),
        )
        self.assertEqual((saved.window_long, saved.breakout_volume_multiple, saved.average_days, saved.download_breakout), (300, Decimal(3), 30, False))
        self.assertEqual((saved.window_short, saved.window_mid, saved.breakout_intraday_ratio), (60, 120, Decimal(2)))
        self.assertEqual(saved.near_extreme_pct, ScreenerParams().near_extreme_pct)  # untouched fields keep their value


if __name__ == '__main__':
    unittest.main()
