"""M5-1: tick side, five-level normalisation, tape buffer, bidask subscription follows selection."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from quantlab.trading.adapters.shioaji.bidask_stream import ShioajiBidAskStream, normalise_bidask
from quantlab.trading.adapters.shioaji.tick_stream import tick_side
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_terminal_service import TAPE_LIMIT, MarketTerminalService
from quantlab.trading.application.order_book_contracts import OrderBookView, TapeEntry
from quantlab.trading.domain.bidask import BidAskSnapshot
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES
from tests.test_market_terminal_service import NOW, OTHER, STOCK, Session

import quantlab.trading.runtime.protocol  # noqa: F401  (registers wire types)


def raw_bidask(code='2330', levels=5):
    return SimpleNamespace(
        code=code,
        datetime=datetime(2026, 11, 9, 9, 30, 1),
        bid_price=['100.5', '100', '99.5', '99', '98.5'][:levels],
        bid_volume=[10, 20, 30, 40, 50][:levels],
        ask_price=['101', '101.5', '102', '102.5', '103'][:levels],
        ask_volume=[5, 6, 7, 8, 9][:levels],
    )


def tick(side='NONE', volume=3, offset=0, instrument=STOCK.instrument_id, price='100'):
    at = NOW + timedelta(seconds=offset)
    return Tick(instrument, Decimal(price), volume, at, at, at.date(), side=side)


class TickSideTests(unittest.TestCase):
    def test_tick_type_maps_outer_inner_and_unknown(self):
        self.assertEqual(tick_side(SimpleNamespace(tick_type=1)), 'BUY')
        self.assertEqual(tick_side(SimpleNamespace(tick_type=2)), 'SELL')
        self.assertEqual(tick_side(SimpleNamespace(tick_type=0)), 'NONE')
        self.assertEqual(tick_side(SimpleNamespace(tick_type=SimpleNamespace(value=1))), 'BUY')
        self.assertEqual(tick_side(SimpleNamespace()), 'NONE')
        self.assertEqual(tick_side(SimpleNamespace(tick_type='1')), 'NONE')

    def test_tick_default_side_is_none_and_invalid_side_is_rejected(self):
        self.assertEqual(tick().side, 'NONE')
        with self.assertRaises(DomainError):
            tick(side='MAYBE')


class BidAskTests(unittest.TestCase):
    def test_normalises_five_levels_with_decimal_prices_in_utc(self):
        snapshot = normalise_bidask(raw_bidask(), STOCK.instrument_id)
        self.assertEqual(snapshot.bid_prices[0], Decimal('100.5'))
        self.assertEqual(snapshot.ask_prices[4], Decimal('103'))
        self.assertEqual(snapshot.source_at, datetime(2026, 11, 9, 1, 30, 1, tzinfo=timezone.utc))
        self.assertEqual((snapshot.total_bid_volume, snapshot.total_ask_volume), (150, 35))

    def test_short_levels_are_rejected_and_the_callback_never_raises(self):
        with self.assertRaises(ValueError):
            normalise_bidask(raw_bidask(levels=3), STOCK.instrument_id)
        stream = ShioajiBidAskStream({'2330': STOCK.instrument_id})
        stream.set_active({STOCK.instrument_id})
        stream.on_bidask(None, raw_bidask(levels=3))
        self.assertIsNone(stream.latest(STOCK.instrument_id))

    def test_only_active_instruments_keep_the_latest_snapshot(self):
        stream = ShioajiBidAskStream({'2330': STOCK.instrument_id, '6104': OTHER.instrument_id})
        stream.on_bidask(None, raw_bidask())
        self.assertIsNone(stream.latest(STOCK.instrument_id))
        stream.set_active({STOCK.instrument_id})
        stream.on_bidask(None, raw_bidask())
        stream.on_bidask(None, raw_bidask('6104'))
        self.assertIsNotNone(stream.latest(STOCK.instrument_id))
        self.assertIsNone(stream.latest(OTHER.instrument_id))
        stream.set_active(set())
        self.assertIsNone(stream.latest(STOCK.instrument_id))


class OrderBookServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KlineStore(Path(self.temp.name) / 'klines.sqlite3')
        self.session = Session()
        self.history = HistorySync(self.store, self.session, now=lambda: NOW, autostart=False)
        self.service = MarketTerminalService(self.store, self.history, self.session, lambda: (*FIXED_INDICES, STOCK, OTHER), now=lambda: NOW)

    def tearDown(self):
        self.history.close()
        self.store.close()
        self.temp.cleanup()

    def connect(self, selected=None):
        if selected:
            self.service.selected = selected
        self.session.connected = True
        self.service.connected()

    def test_bidask_follows_the_selected_stock_only(self):
        self.connect(STOCK.instrument_id)
        self.assertEqual(self.session.bidask_subscribed, [STOCK.instrument_id])
        self.service.select(OTHER.instrument_id)
        self.assertEqual(self.session.bidask_unsubscribed, [STOCK.instrument_id])
        self.assertEqual(self.session.bidask_subscribed, [STOCK.instrument_id, OTHER.instrument_id])
        self.service.select(FIXED_INDICES[0].instrument_id)
        self.assertEqual(self.session.bidask_unsubscribed, [STOCK.instrument_id, OTHER.instrument_id])
        self.assertFalse(self.service.order_book(FIXED_INDICES[0].instrument_id).supported)

    def test_selecting_the_same_stock_twice_does_not_resubscribe(self):
        self.connect(STOCK.instrument_id)
        self.service.select(STOCK.instrument_id)
        self.assertEqual(self.session.bidask_subscribed, [STOCK.instrument_id])

    def test_over_quota_bidask_degrades_without_failing_the_selection(self):
        def refuse(item):
            raise DomainError('subscription_limit_reached')

        self.session.subscribe_bidask = refuse
        self.connect(STOCK.instrument_id)
        view = self.service.order_book(STOCK.instrument_id)
        self.assertTrue(view.supported)
        self.assertTrue(view.bidask_limited)
        self.assertIsNone(view.bidask)

    def test_bidask_is_returned_only_for_the_subscribed_stock(self):
        snapshot = normalise_bidask(raw_bidask(), STOCK.instrument_id)
        self.session.latest_bidask = snapshot
        self.connect(STOCK.instrument_id)
        self.assertEqual(self.service.order_book(STOCK.instrument_id).bidask, snapshot)
        self.assertIsNone(self.service.order_book(OTHER.instrument_id).bidask)

    def test_tape_is_newest_first_with_side_totals_and_since(self):
        self.connect(STOCK.instrument_id)
        self.session.pending = [tick('BUY', 5, 1), tick('SELL', 2, 2), tick('NONE', 1, 3), tick('BUY', 4, 4)]
        self.service.poll()
        view = self.service.order_book(STOCK.instrument_id)
        self.assertEqual([entry.volume for entry in view.tape], [4, 1, 2, 5])
        self.assertEqual((view.buy_volume, view.sell_volume, view.undecided_volume), (9, 2, 1))
        self.assertEqual(view.since, NOW + timedelta(seconds=1))

    def test_tape_is_bounded_and_resets_on_reconnect(self):
        self.connect(STOCK.instrument_id)
        self.session.pending = [tick('BUY', 1, index // 10, price=str(100 + index % 5)) for index in range(TAPE_LIMIT + 50)]
        while self.session.pending:
            self.service.poll()
        view = self.service.order_book(STOCK.instrument_id)
        self.assertEqual(len(view.tape), TAPE_LIMIT)
        self.assertEqual(view.buy_volume, TAPE_LIMIT + 50)
        self.session.connected = False
        self.service.poll()
        self.connect(STOCK.instrument_id)
        self.assertEqual(self.service.order_book(STOCK.instrument_id).tape, ())

    def test_index_ticks_never_enter_the_tape(self):
        self.connect(STOCK.instrument_id)
        index = FIXED_INDICES[0].instrument_id
        self.session.pending = [tick('NONE', 0, 1, instrument=index, price='20000')]
        self.service.poll()
        self.assertEqual(self.service.order_book(index).tape, ())

    def test_full_budget_with_the_bidask_slot_keeps_selection_and_book_consistent(self):
        class Limited(Session):
            limit = 4

            def subscribe(self, item):
                if len(self.subscribed) - len(self.unsubscribed) + len(self.bidask_subscribed) - len(self.bidask_unsubscribed) >= self.limit:
                    raise DomainError('subscription_limit_reached')
                super().subscribe(item)

        self.session = Limited()
        self.service = MarketTerminalService(
            self.store,
            self.history,
            self.session,
            lambda: (*FIXED_INDICES, STOCK, OTHER),
            now=lambda: NOW,
            settings=replace(LiveMarketSettings(), subscription_limit=4),
        )
        self.service.watchlist = (STOCK.instrument_id,)
        self.connect(STOCK.instrument_id)
        self.assertEqual(self.service.status().subscription_count, 4)
        # The selected stock's ticks outrank its five levels: the old book is released first, the tick
        # subscription succeeds, and the new book degrades to 'limited' instead of failing the selection.
        self.assertTrue(self.service.select(OTHER.instrument_id))
        self.assertEqual(self.session.bidask_unsubscribed, [STOCK.instrument_id])
        self.assertEqual(self.session.bidask_subscribed, [STOCK.instrument_id])
        self.assertTrue(self.service.order_book(OTHER.instrument_id).bidask_limited)

    def test_bidask_unsubscribe_failure_still_moves_to_the_new_stock(self):
        self.connect(STOCK.instrument_id)

        def broken(key):
            raise DomainError('market_data_not_connected')

        self.session.unsubscribe_bidask = broken
        self.service.select(OTHER.instrument_id)
        self.assertEqual(self.session.bidask_subscribed[-1], OTHER.instrument_id)

    def test_dropped_temporary_stock_starts_a_fresh_tape(self):
        self.connect(STOCK.instrument_id)
        self.session.pending = [tick('BUY', 5, 1)]
        self.service.poll()
        self.service.select(OTHER.instrument_id)
        self.assertEqual(self.service.order_book(STOCK.instrument_id).tape, ())

    def test_order_book_view_survives_the_wire_codec(self):
        snapshot = normalise_bidask(raw_bidask(), STOCK.instrument_id)
        view = OrderBookView(
            STOCK.instrument_id,
            True,
            snapshot,
            False,
            (TapeEntry(NOW, Decimal('100.5'), 3, 'BUY'),),
            3,
            0,
            0,
            NOW,
        )
        self.assertEqual(loads(dumps(view)), view)


class BidAskSnapshotValidationTests(unittest.TestCase):
    def test_wrong_level_count_is_rejected(self):
        with self.assertRaises(DomainError):
            BidAskSnapshot(STOCK.instrument_id, NOW, (Decimal(1),), (1,), (Decimal(2),), (1,))


class SessionBidAskTests(unittest.TestCase):
    def setUp(self):
        from tests.test_market_session import MarketSessionTests

        self.case = MarketSessionTests('test_only_reference_login_history_and_no_trading_surface')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.api, self.session = self.case.api, self.case.session
        self.session.connect()

    def test_bidask_subscription_is_a_separate_slot_and_delivers_latest_only(self):
        self.session.subscribe_bidask(STOCK)
        self.assertIn(('subscribe', '2330', 'bidask'), self.api.calls)
        self.api.callbacks['bidask'](None, raw_bidask())
        self.assertEqual(self.session.bidask(STOCK.instrument_id).bid_prices[0], Decimal('100.5'))
        self.session.unsubscribe_bidask(STOCK.instrument_id)
        self.assertIn(('unsubscribe', '2330', 'bidask'), self.api.calls)
        self.assertIsNone(self.session.bidask(STOCK.instrument_id))

    def test_indices_have_no_bidask_and_disconnect_releases_it(self):
        with self.assertRaises(DomainError):
            self.session.subscribe_bidask(FIXED_INDICES[0])
        self.session.subscribe_bidask(STOCK)
        self.session.disconnect()
        self.assertIn(('unsubscribe', '2330', 'bidask'), self.api.calls)

    def test_bidask_counts_against_the_subscription_limit(self):
        self.session.live_settings = self.session.live_settings.__class__(**{**vars(self.session.live_settings), 'subscription_limit': 1})
        self.session.subscribe_bidask(STOCK)
        with self.assertRaises(DomainError):
            self.session.subscribe(FIXED_INDICES[0])

    def test_stock_tick_carries_outer_and_inner_side(self):
        self.session.subscribe(STOCK)
        for kind, expected in ((1, 'BUY'), (2, 'SELL'), (0, 'NONE')):
            raw = SimpleNamespace(code='2330', datetime=datetime(2026, 10, 30, 9, 0), close=100, volume=1, tick_type=kind)
            self.api.callbacks['stock'](None, raw)
            self.assertEqual(self.session.drain_ticks(1)[0].side, expected)


class OrderBookPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def view(self, **changes):
        base = dict(
            instrument_id=STOCK.instrument_id,
            supported=True,
            bidask=normalise_bidask(raw_bidask(), STOCK.instrument_id),
            tape=(TapeEntry(NOW, Decimal('100.5'), 3, 'BUY'), TapeEntry(NOW - timedelta(seconds=5), Decimal('100'), 2, 'SELL')),
            buy_volume=3,
            sell_volume=1,
            since=NOW - timedelta(minutes=5),
        )
        return OrderBookView(**{**base, **changes})

    def test_ladder_orders_asks_descending_then_bids_and_shows_totals_and_ratio(self):
        from desktop_app.features.trading.order_book_panel import OrderBookPanel, ladder_rows, side_ratio_text

        rows = ladder_rows(self.view())
        self.assertEqual([row[1] for row in rows], ['103.0', '102.5', '102.0', '101.5', '101.0', '100.5', '100.0', '99.5', '99.0', '98.5'])
        panel = OrderBookPanel()
        panel.render_view(self.view(), '#ff0000', '#00aa00')
        self.assertEqual(panel.ladder.rowCount(), 10)
        self.assertEqual(panel.tape.rowCount(), 2)
        self.assertEqual(panel.tape.item(0, 3).text(), '外')
        self.assertEqual(panel.tape.item(1, 3).text(), '內')
        self.assertIn('150', panel.totals.text())
        self.assertIn('75%', side_ratio_text(self.view()))
        self.assertIn('自', panel.tape_summary.text())
        self.assertFalse(panel.notice.isVisibleTo(panel))

    def test_index_and_missing_data_states(self):
        from desktop_app.features.trading.order_book_panel import OrderBookPanel

        panel = OrderBookPanel()
        panel.render_view(OrderBookView('INDEX:IX0001'), '#ff0000', '#00aa00')
        self.assertEqual(panel.notice.text(), '指數無五檔')
        panel.render_view(OrderBookView(STOCK.instrument_id, supported=True), '#ff0000', '#00aa00')
        self.assertEqual(panel.notice.text(), '等待五檔資料…')
        panel.render_view(OrderBookView(STOCK.instrument_id, supported=True, bidask_limited=True), '#ff0000', '#00aa00')
        self.assertEqual(panel.notice.text(), '訂閱額度不足，無法顯示五檔')
        panel.clear('行情未連線')
        self.assertEqual(panel.ladder.rowCount(), 0)


class LayoutUpgradeTests(unittest.TestCase):
    def test_old_saved_layout_gains_the_order_book_and_keeps_other_panels(self):
        import json

        from desktop_app.features.trading.market_terminal_layout import OPTIONAL_PANELS, PANEL_IDS, terminal_preset
        from quantlab.research_core.adapters.market_layout import LayoutStore

        old = terminal_preset()
        del old['panels']['orderbook']
        old['panels']['chart']['size'] = 1234
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'layout.json'
            path.write_text(json.dumps({'version': 1, 'current': old, 'layouts': {'Mine': old}}), encoding='utf-8')
            store = LayoutStore(folder, panel_ids=PANEL_IDS, file_name='layout.json', default_layout=terminal_preset(), optional_panels=OPTIONAL_PANELS)
        self.assertEqual(store.current['panels']['chart']['size'], 1234)
        self.assertEqual(store.current['panels']['orderbook'], terminal_preset()['panels']['orderbook'])
        self.assertEqual(set(store.layouts['Mine']['panels']), set(PANEL_IDS))

    def test_wrong_extra_panel_is_still_rejected(self):
        from desktop_app.features.trading.market_terminal_layout import OPTIONAL_PANELS, PANEL_IDS, terminal_preset
        from quantlab.research_core.adapters.market_layout import validate_layout

        value = terminal_preset()
        value['panels']['ghost'] = dict(value['panels']['chart'])
        self.assertIsNone(validate_layout(value, PANEL_IDS, fill=terminal_preset(), optional=OPTIONAL_PANELS))
        gap = terminal_preset()
        del gap['panels']['chart']
        self.assertIsNone(validate_layout(gap, PANEL_IDS, fill=terminal_preset(), optional=OPTIONAL_PANELS))


if __name__ == '__main__':
    unittest.main()
