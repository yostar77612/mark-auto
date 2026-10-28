"""Offscreen market display/wiring and settings-path persistence evidence.

These tests do not verify market calculations or native Windows appearance.
"""

from dataclasses import replace
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import time
import unittest

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_charts import CandlestickChart
from desktop_strings import ui_text
from desktop_trading.market_watch import MarketWatchWidget
from desktop_trading.market_watch_rows import freshness_text, header_text, health_rows, quote_detail_rows, quote_detail_text, series_bars, watch_rows
from quantlab.desktop_runtime import SettingsStore
from quantlab.trading.application.contracts import (
    MarketHealthView,
    MarketSeriesPage,
    MarketWatchView,
    OverviewMarketSummary,
    UiAction,
    UiCommand,
    UiReceipt,
    UiState,
)
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _dispatch

NOW = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)


def bar(at=NOW, *, final=False):
    return LiveBar('TMF', at, at + timedelta(minutes=1), date(2026, 10, 28), 'DAY', Decimal('100'), Decimal('102'), Decimal('99'), Decimal('101'), 7, final)


def view(freshness='LIVE', instrument='TMF'):
    return MarketWatchView(
        instrument_id=instrument,
        price=Decimal('101'),
        reference_price=Decimal('99'),
        change=Decimal('2'),
        change_percent=Decimal('2.02'),
        source_at=NOW,
        received_at=NOW,
        trade_date=NOW.date(),
        session='DAY',
        source='fixture',
        health=MarketHealthView(instrument, freshness),
        bid=Decimal('100'),
        ask=Decimal('102'),
        open=Decimal('98'),
        high=Decimal('103'),
        low=Decimal('97'),
        total_volume=42,
        receive_latency='0:00:00',
    )


def state():
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
        market_watch=(view(),),
        market_health=OverviewMarketSummary((view().health,), 1),
        watchlist=('TMF',),
    )


class FakeFacade:
    def __init__(self):
        self.state = state()
        self.queries, self.commands = [], []
        self.strategy_subscriptions = ('strategy-only',)
        self.receipt = UiReceipt(True, 'completed', '')
        self.page = MarketSeriesPage('TMF', '1m', (bar(),), total=1, market_revision=1)

    def snapshot(self):
        return self.state

    def execute(self, command):
        self.commands.append(command)
        if self.receipt.accepted:
            self.state = replace(self.state, watchlist=command.watchlist)
        return self.receipt

    def market_series(self, query):
        self.queries.append(query)
        return replace(self.page, instrument_id=query.instrument_id, period=query.period)


class RecordingChart(CandlestickChart):
    def __init__(self):
        self.calls = []
        super().__init__()

    def set_series(self, *args, **kwargs):
        self.calls.append('set')
        return super().set_series(*args, **kwargs)

    def append_bar(self, item):
        self.calls.append('append')
        return super().append_bar(item)

    def replace_last_bar(self, item):
        self.calls.append('replace')
        return super().replace_last_bar(item)


class RowTests(unittest.TestCase):
    def test_freshness_and_unknown_table(self):
        for freshness, key, role in (
            ('LIVE', 'watch.live', 'live'),
            ('DELAYED', 'watch.delayed', 'warning'),
            ('STOPPED', 'watch.stopped', 'muted'),
            ('CLOSED', 'watch.closed', 'muted'),
            ('UNKNOWN', 'watch.unknown', 'muted'),
        ):
            with self.subTest(freshness=freshness):
                item = view(freshness)
                text, colour = freshness_text(item.health, NOW)
                self.assertEqual(colour, role)
                self.assertIn(ui_text(key).split('{')[0], text)
                cells = watch_rows((item,))[0][1]
                self.assertEqual(cells[2:5], ('2', '2.02', '42'))
                self.assertEqual(cells[1], ui_text('watch.unknown') if freshness == 'UNKNOWN' else '101')
                if freshness in ('DELAYED', 'STOPPED', 'CLOSED'):
                    self.assertIn('2026-10-28', text)
        empty = MarketWatchView(instrument_id='TX')
        self.assertTrue(all(value == ui_text('watch.unknown') for _, value in quote_detail_rows(empty)))
        self.assertNotIn('0', quote_detail_text(empty))
        self.assertEqual(watch_rows((empty,))[0][1][1:], (ui_text('watch.unknown'),) * 5)

    def test_detail_header_health_and_series_projection(self):
        item = view()
        details = dict(quote_detail_rows(item))
        for key, expected in (
            ('watch.bid', '100'),
            ('watch.ask', '102'),
            ('watch.open', '98'),
            ('watch.high', '103'),
            ('watch.low', '97'),
            ('watch.reference', '99'),
            ('watch.volume', '42'),
            ('watch.session', 'DAY'),
            ('watch.source', 'fixture'),
            ('watch.latency', '0:00:00'),
        ):
            with self.subTest(key=key):
                self.assertEqual(details[ui_text(key)], expected)
        summary = OverviewMarketSummary((item.health,), 8)
        self.assertIn('8/20', header_text('CONNECTED', summary))
        self.assertIn(ui_text('watch.connected'), header_text('CONNECTED', summary))
        self.assertEqual(health_rows(summary), (('TMF', ('TMF', ui_text('watch.live'))),))
        for instrument in ('TMF', 'TX', 'TWSE:2330'):
            with self.subTest(instrument=instrument):
                page = MarketSeriesPage(instrument, '5m', (bar(),))
                self.assertEqual(series_bars(page)[0].contract_id, instrument)
                self.assertEqual(series_bars(page)[0].close, bar().close)


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = FakeFacade()
        self.chart = RecordingChart()
        self.widget = MarketWatchWidget(self.facade, self.chart, self.facade.state)
        self.widget.resize(1000, 650)
        self.widget.show()
        self.wait_for(lambda: bool(self.chart.bars))

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone(3000)
        self.app.processEvents()
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(condition())

    def test_periods_keyboard_accessibility_and_large_font(self):
        for period, button in self.widget.period_buttons.items():
            with self.subTest(period=period):
                before = len(self.facade.queries)
                button.setFocus()
                QTest.keyClick(button, Qt.Key.Key_Space)
                self.wait_for(lambda: len(self.facade.queries) > before)
                self.assertEqual(self.facade.queries[-1].period, period)
                self.assertEqual(self.facade.queries[-1].instrument_id, 'TMF')
        names = []
        for widget in (
            self.widget,
            self.widget.header,
            self.widget.instrument,
            self.widget.add,
            self.widget.remove,
            self.widget.table,
            self.chart,
            self.widget.panels,
            self.widget.detail,
            self.widget.gap,
            self.widget.history_error,
            self.widget.retry,
            self.widget.message,
            *self.widget.period_buttons.values(),
        ):
            with self.subTest(widget=widget.objectName()):
                self.assertTrue(widget.objectName())
                self.assertTrue(widget.accessibleName())
                names.append(widget.objectName())
        self.assertEqual(len(names), len(set(names)))
        self.widget.setFont(QFont('Arial', 20))
        self.widget.resize(800, 600)
        self.app.processEvents()
        self.assertTrue(self.widget.table.isVisible())
        self.assertTrue(self.chart.isVisible())
        self.assertTrue(self.widget.detail.isVisible())
        self.assertEqual(self.widget.instrument.nextInFocusChain(), self.widget.add)

    def test_refusal_and_removal_route_only_settings(self):
        error = ERROR_TABLE['capability_missing']
        message = error.explanation + ' ' + error.action
        self.facade.receipt = UiReceipt(False, 'capability_missing', message)
        watches = ('TMF', *(f'fixture-{index}' for index in range(19)))
        self.facade.state = replace(self.facade.state, watchlist=watches, market_health=replace(self.facade.state.market_health, subscription_count=20))
        self.widget.render(self.facade.state)
        self.widget.instrument.setText('TX')
        QTest.mouseClick(self.widget.add, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: bool(self.widget.message.text()))
        self.assertIn(message, self.widget.message.text())
        self.assertIn(ui_text('watch.refused').split('{0}')[1], self.widget.message.text())
        self.assertEqual(self.facade.commands[-1].watchlist, (*watches, 'TX'))
        self.assertEqual(self.facade.state.watchlist, watches)
        self.assertEqual(self.facade.strategy_subscriptions, ('strategy-only',))
        self.facade.state = state()
        self.widget.render(self.facade.state)
        self.facade.receipt = UiReceipt(True, 'completed', '')
        QTest.mouseClick(self.widget.remove, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: self.facade.state.watchlist == ())
        self.assertTrue(all(command.action is UiAction.SAVE_SETTINGS for command in self.facade.commands))
        self.assertTrue(all(command.settings is None for command in self.facade.commands))

    def test_incremental_series_and_full_replacement(self):
        changed = replace(bar(), close=Decimal('102'))
        self.facade.page = replace(self.facade.page, bars=(changed,), market_revision=2)
        self.widget.load_series()
        self.wait_for(lambda: self.chart.calls[-1] == 'replace')
        self.facade.page = replace(self.facade.page, bars=(changed, bar(NOW + timedelta(minutes=1))), market_revision=3)
        self.widget.load_series()
        self.wait_for(lambda: self.chart.calls[-1] == 'append')
        self.widget.select_period('5m')
        self.wait_for(lambda: self.chart.calls[-1] == 'set')
        self.assertEqual(self.chart.bars[0].interval, '5m')

    def test_gap_history_retry_flags_and_unknown_detail(self):
        health = MarketHealthView('TMF', 'STOPPED', 'market_data_invalid', True)
        self.widget.render(replace(self.facade.state, market_watch=(replace(view('STOPPED'), health=health),)))
        self.assertEqual(self.widget.gap.text(), ui_text('watch.gap'))
        self.assertIn('market_data_invalid', self.widget.history_error.text())
        self.assertFalse(self.widget.retry.isHidden())
        QTest.mouseClick(self.widget.retry, Qt.MouseButton.LeftButton)
        self.wait_for(lambda: any(query.retry_history for query in self.facade.queries))
        self.assertEqual(self.widget.table.item(0, 1).foreground().color().name(), '#808080')
        self.assertIn(ui_text('watch.stopped').split('{')[0], self.widget.detail.text())


class PersistenceTests(unittest.TestCase):
    def test_settings_saved_via_runtime_command_and_restored_on_restart(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            SettingsStore(root / 'settings.json').save({'unrelated': {'keep': True}})
            bundle = build_runtime(RuntimeLaunch(root))
            try:
                initial = bundle.snapshot()
                watches = (initial.watchlist[-1],)
                command = UiCommand(UiAction.SAVE_SETTINGS, initial.version, watchlist=watches)
                request = Request(
                    'watch-save', Environment.LOCAL, 'local-stock', datetime.now(timezone.utc) + timedelta(seconds=10), Operation.COMMAND, command
                )
                response = _dispatch(bundle, request)
                self.assertTrue(response.receipt.accepted)
                self.assertEqual(response.state.watchlist, watches)
                bundle.pump()
                self.assertEqual(bundle.engine.live_market.watchlist, watches)
                self.assertEqual(SettingsStore(root / 'settings.json').load(), {'unrelated': {'keep': True}, 'market_watch_v2': list(watches)})
            finally:
                bundle.close()
            reopened = build_runtime(RuntimeLaunch(root))
            try:
                self.assertEqual(reopened.snapshot().watchlist, watches)
                reopened.pump()
                self.assertEqual(reopened.engine.live_market.allocation.active, watches)
                empty = UiCommand(UiAction.SAVE_SETTINGS, reopened.snapshot().version, watchlist=())
                self.assertTrue(reopened.execute(empty).accepted)
            finally:
                reopened.close()
            empty_reopened = build_runtime(RuntimeLaunch(root))
            try:
                self.assertEqual(empty_reopened.snapshot().watchlist, ())
                self.assertEqual(empty_reopened.engine.live_market.allocation.active, ())
            finally:
                empty_reopened.close()
