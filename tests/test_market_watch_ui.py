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
from unittest.mock import patch

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_app.components.charts import CandlestickChart
from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading import market_watch as market_watch_module, series_reader
from desktop_app.features.trading.market_watch import MarketWatchWidget
from desktop_app.features.trading.market_watch_rows import (
    freshness_text,
    header_text,
    health_rows,
    quote_detail_rows,
    quote_detail_text,
    series_bars,
    watch_rows,
)
from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.application.contracts import (
    MarketHealthView,
    MarketSeriesPage,
    MarketSeriesQuery,
    MarketWatchView,
    OverviewMarketSummary,
    UiAction,
    UiCommand,
    UiReceipt,
    UiState,
)
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _dispatch
from tests import series_read_simulator as simulator

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
            ('watch.session', ui_text('presentation.labels.day')),
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

    def test_destroying_the_widget_cancels_a_request_still_in_flight(self):
        import threading

        import shiboken6

        from desktop_app.features.trading import market_watch

        other = MarketWatchWidget(FakeFacade(), RecordingChart(), self.facade.state)
        self.wait_for(lambda: not other._requests)
        gate, seen = threading.Event(), []
        other._submit(lambda: gate.wait(5), lambda value, error: seen.append(value))
        token = next(iter(other._requests)).token
        shiboken6.delete(other)
        gate.set()
        self.wait_for(lambda: token not in market_watch._LIVE_RESULTS)
        self.assertEqual(seen, [])

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
        watches = ('TMF',)
        self.facade.state = replace(self.facade.state, market_health=replace(self.facade.state.market_health, subscription_limit=17))
        self.widget.render(self.facade.state)
        for case, code in (
            ('slot limit', 'subscription_limit_reached'),
            ('disconnected engine', 'capability_missing'),
            ('no live market', 'capability_missing'),
        ):
            with self.subTest(case=case):
                error = ERROR_TABLE[code]
                message = error.explanation + ' ' + error.action
                self.facade.receipt = UiReceipt(False, code, message)
                self.widget.message.clear()
                self.widget.instrument.setText('TX')
                QTest.mouseClick(self.widget.add, Qt.MouseButton.LeftButton)
                self.wait_for(lambda: bool(self.widget.message.text()))
                expected = ui_text('watch.refused').format(message, 17) if code == 'subscription_limit_reached' else message
                self.assertEqual(self.widget.message.text(), expected)
                if code == 'subscription_limit_reached':
                    self.assertIn('17', self.widget.message.text())
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


class PendingRequestsTests(unittest.TestCase):
    def test_cancel_stops_every_in_flight_result_with_one_connection(self):
        from desktop_app.features.trading.market_watch import PendingRequests, _Result

        seen = []
        pending = PendingRequests()
        results = [_Result(lambda value, error, tag=tag: seen.append(tag)) for tag in range(3)]
        pending.update(results)
        pending.cancel()
        for result in results:
            result.finish(None, None)
        self.assertEqual(seen, [])


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


def series_state():
    """Both simulated stocks watched, so the table can select either one."""
    items = (simulator.STOCK, simulator.OTHER)
    views = tuple(MarketWatchView(instrument_id=item.instrument_id, health=MarketHealthView(item.instrument_id, 'LIVE')) for item in items)
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
        market_health=OverviewMarketSummary(tuple(view.health for view in views), 2),
        watchlist=tuple(item.instrument_id for item in items),
    )


class SeriesFacade:
    """The legacy watch's facade with every chart read served by a real engine (OPT-1 P11)."""

    def __init__(self, feed):
        self.feed, self.state = feed, series_state()

    def snapshot(self):
        return self.state

    def market_series(self, query):
        return self.feed.facade.market_series(query)


class WatchSeriesReadTests(unittest.TestCase):
    """OPT-1 P11: what each read hands the legacy watch's chart equals a whole-series read, bar for bar."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.feed = simulator.TerminalFeed(self.temp.name)
        self.facade = SeriesFacade(self.feed)
        self.chart = RecordingChart()
        self.widget = MarketWatchWidget(self.facade, self.chart, self.facade.state)
        self.widget.resize(1000, 650)
        self.widget.show()
        deadline = time.monotonic() + 3
        while not (self.chart.bars and not self.widget._requests) and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(self.chart.bars)
        self.widget._submit = simulator.run_inline  # from here on every request completes at once: one deterministic step per call
        self.clock = [1000.0]
        patcher = patch.object(market_watch_module, 'monotonic', lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key, self.period = simulator.STOCK.instrument_id, '1m'
        self.widget._series_read = None  # the first read above was timed by the real clock: start over on the test's clock
        self.widget.load_series()

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone(3000)
        self.app.processEvents()
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()
        self.feed.close()
        self.temp.cleanup()

    def chart_matches_whole_read(self):
        expected = series_bars(self.feed.whole(self.key, self.period))
        return repr(self.chart.bars) == repr(expected)  # repr keeps Decimal exponents and every flag

    def refresh(self, retry=False):
        """One read: the queries it sent, and whether they read the selected instrument from its first page."""
        del self.feed.facade.queries[:]
        self.widget.load_series(retry=retry)
        return self.feed.facade.queries, simulator.whole_round(self.feed.facade.queries, self.key)

    def play(self, rounds=90):
        """The mismatching rounds and the rounds that read the whole series, over a script of every kind of change."""
        mismatches, wholes = [], []
        for number in range(rounds):
            self.clock[0] += 1.0
            self.feed.tick()
            if number % 17 == 5:
                self.feed.backfill_older()  # older history arrives: every index shifts
            if number % 11 == 3:
                self.feed.tick(lost=True)
            if number == 30:
                self.feed.tick(6 * 3600)  # the day session closes and the night session opens under the next trade date
            if number == 40:
                for _ in range(4):
                    self.feed.tick(lost=True)
            if number == 45:
                self.feed.tick(14 * 3600)  # the next morning's day session
            del self.feed.facade.queries[:]
            if number in (20, 22):
                self.key = simulator.OTHER.instrument_id if number == 20 else simulator.STOCK.instrument_id
                self.widget.table.selectRow(1 if number == 20 else 0)
            if number in (33, 48, 58):
                self.period = {33: '5m', 48: '1d', 58: '1m'}[number]
                self.widget.select_period(self.period)
            self.widget.load_series(retry=number in (66, 80))
            if not self.chart_matches_whole_read():
                mismatches.append(number)
            if simulator.whole_round(self.feed.facade.queries, self.key):
                wholes.append(number)
            if number in (66, 80):
                retries = [query for query in self.feed.facade.queries if query.retry_history]
                self.assertEqual([(query.instrument_id, query.offset) for query in retries], [(self.key, 0)])  # the first page of the whole read, once
        return mismatches, wholes

    def test_chart_bars_equal_whole_reads_through_every_kind_of_change(self):
        mismatches, wholes = self.play()
        self.assertEqual(mismatches, [])
        # Another instrument, another period, the retry button and every backfill of a long series read the whole series.
        self.assertLessEqual({20, 22, 33, 48, 58, 66, 80, 5, 39, 56, 73}, set(wholes))
        self.assertGreater(90 - len(wholes), 55)  # every other round only re-read the tail

    def test_removing_the_window_comparison_is_caught(self):
        with patch.object(series_reader, '_read_tail', simulator.without_window_check):
            mismatches, _ = self.play()
        self.assertTrue(mismatches)

    def test_steady_reads_are_one_bar_and_the_tail_and_the_chart_is_drawn_as_before(self):
        del self.chart.calls[:]
        for _ in range(12):
            self.feed.tick()
            queries, whole = self.refresh()
            self.assertFalse(whole)
            self.assertEqual([(query.offset > 0, query.limit == 1) for query in queries], [(False, True), (True, False)])
            self.assertTrue(self.chart_matches_whole_read())
        # The chart's own drawing is unchanged: a new minute appends, the forming minute is replaced, and the minute
        # that finishes (its last bar changes) sets the series again. Ticks come every 20 s, three to a minute.
        self.assertEqual(self.chart.calls, ['append', 'replace', 'set', 'replace', 'replace', 'set', 'replace', 'replace', 'set', 'replace', 'replace', 'set'])

    def test_the_cache_resyncs_after_the_bound_and_is_dropped_on_an_error_and_for_another_selection(self):
        self.feed.tick()
        self.assertFalse(self.refresh()[1])
        self.clock[0] += series_reader.SERIES_RESYNC_SECONDS
        self.assertTrue(self.refresh()[1])  # the periodic whole read
        self.feed.tick()
        self.assertFalse(self.refresh()[1])
        with patch.object(self.facade, 'market_series', side_effect=DomainError('state_conflict')):
            self.widget.load_series()
        self.assertIsNone(self.widget._series_read)
        self.feed.tick()
        self.assertTrue(self.refresh()[1])  # nothing is reused after an error
        self.assertTrue(self.chart_matches_whole_read())
        self.key = simulator.OTHER.instrument_id
        self.widget.table.selectRow(1)
        self.assertEqual({bar.contract_id for bar in self.chart.bars}, {self.key})  # no bar of the first stock is left behind
        self.assertTrue(self.chart_matches_whole_read())

    def test_a_read_queued_behind_one_in_flight_builds_on_what_the_first_one_read(self):
        requests = []
        self.widget._submit = lambda operation, completed: requests.append((operation, completed))
        self.widget._series_read = None
        self.widget.load_series()  # a whole read starts and stays in flight
        self.widget.load_series()  # the market moved on: this one queues behind it
        self.assertEqual(len(requests), 1)
        operation, completed = requests.pop()
        del self.feed.facade.queries[:]
        completed(operation(), None)  # the first read ends; its answer is superseded, so the queued read starts at once
        self.assertEqual(len(requests), 1)
        self.assertTrue(simulator.whole_round(self.feed.facade.queries, self.key))
        self.feed.tick()
        del self.feed.facade.queries[:]
        operation, completed = requests.pop()
        completed(operation(), None)
        self.assertFalse(simulator.whole_round(self.feed.facade.queries, self.key))  # it read only the tail of what the first one read
        self.assertTrue(self.chart_matches_whole_read())

    def test_a_tail_read_does_not_restart_the_resync_clock(self):
        self.clock[0] += 100  # the whole read of setUp is 100 s old
        self.feed.tick()
        self.assertFalse(self.refresh()[1])
        self.clock[0] += 21  # 121 s after the whole read, only 21 s after the tail read
        self.feed.tick()
        self.assertTrue(self.refresh()[1])


class ServerDispatchSeriesTests(unittest.TestCase):
    """OPT-1 P11: the tail reader through the real server dispatch of a real runtime bundle, as the desktop's IPC facade reaches it."""

    KEY = 'TWSE:2330'

    def call(self, bundle, operation, query):
        request = Request('series-probe', Environment.LOCAL, 'local-stock', datetime.now(timezone.utc) + timedelta(seconds=10), operation, series=query)
        return loads(dumps(_dispatch(bundle, request)))  # the encode and decode the IPC puts every answer through

    def minute_bars(self, now, first, last, close):
        """Finished one-minute bars from `first` down to `last` minutes before `now`."""
        bars = []
        for minutes in range(first, last - 1, -1):
            start = now - timedelta(minutes=minutes)
            price = Decimal(100 + (minutes + close) % 3)
            bars.append(LiveBar(self.KEY, start, start + timedelta(minutes=1), start.date(), 'DAY', price, price + 3, price - 1, price, 5, True))
        return tuple(bars)

    def test_steady_reads_equal_whole_reads_and_an_unpinned_tail_is_refused(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd(), ignore_cleanup_errors=True) as directory:
            bundle = build_runtime(RuntimeLaunch(Path(directory)))
            try:
                store, now, test = bundle.market_terminal.store, datetime.now(timezone.utc).replace(second=0, microsecond=0), self
                store.upsert(self.minute_bars(now, 600, 1, 0))
                receipt = self.call(bundle, Operation.MARKET_SELECT, MarketSeriesQuery(self.KEY)).receipt
                self.assertEqual(receipt.reference, 'HISTORY')  # the terminal engine now answers every series read

                class Facade:
                    queries = []

                    def market_series(self, query):
                        self.queries.append(query)
                        return test.call(bundle, Operation.MARKET_SERIES, query).series

                facade = Facade()

                def whole():
                    page = self.call(bundle, Operation.MARKET_SERIES, MarketSeriesQuery(self.KEY)).series
                    bars = page.bars
                    while page.next_offset is not None:
                        page = self.call(
                            bundle, Operation.MARKET_SERIES, MarketSeriesQuery(self.KEY, offset=page.next_offset, market_revision=page.market_revision)
                        ).series
                        bars += page.bars
                    return bars

                total = len(whole())
                with self.assertRaises(DomainError) as refused:
                    facade.market_series(MarketSeriesQuery(self.KEY, offset=total - series_reader.SERIES_TAIL_BARS))
                self.assertEqual(refused.exception.code, 'state_conflict')
                cached = series_reader.read_series(facade, self.KEY, '1m', None, pinned_tail=True)[:2]
                wholes = []
                for number in range(8):
                    if number == 3:
                        store.upsert(self.minute_bars(now, 645, 601, 0))  # older history arrives: every index shifts
                    elif number == 6:
                        store.upsert(self.minute_bars(now, 1, 1, number))  # the newest bar is rewritten
                    del facade.queries[:]
                    page, bars, was_whole = series_reader.read_series(facade, self.KEY, '1m', cached, pinned_tail=True)
                    self.assertEqual(repr(bars), repr(whole()), number)
                    cached = page, bars
                    if was_whole:
                        wholes.append(number)
                    else:
                        self.assertEqual([(query.offset > 0, query.limit == 1) for query in facade.queries], [(False, True), (True, False)])
                self.assertEqual(wholes, [3])  # only the backfill read the whole series
            finally:
                bundle.close()
