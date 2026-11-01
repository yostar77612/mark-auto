"""Runtime alert composition with fake sessions, live ticks and session-end bars."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from quantlab.trading.application.alert_contracts import AlertCommand, AlertOperation, AlertRuleData
from quantlab.trading.application.contracts import MarketHealthView, MarketWatchView
from quantlab.trading.domain.alerts import AlertKind, AlertRule
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.market_alerts import attach_alerts
from tests.test_alert_service import FakeFacade, fake_sdk

BASE = datetime(2026, 11, 2, 1, 10, tzinfo=timezone.utc)
ID = 'TWSE:2330'
OTHER = 'TWSE:2317'


def candle(close=100, *, at=BASE, opening=100, high=None, low=None, final=True):
    return LiveBar(
        ID,
        at,
        at + timedelta(minutes=1),
        at.astimezone(timezone(timedelta(hours=8))).date(),
        'DAY',
        D(opening),
        D(max(opening, close) if high is None else high),
        D(min(opening, close) if low is None else low),
        D(close),
        10,
        final,
    )


class TraceFacade(FakeFacade):
    def __init__(self, trace):
        super().__init__()
        self.trace = trace

    def subscribe_scanner(self, scanner, **kwargs):
        self.trace.append('scanner-subscribe')
        super().subscribe_scanner(scanner, **kwargs)

    def unsubscribe_scanner(self, scanner, **kwargs):
        self.trace.append('scanner-unsubscribe')
        super().unsubscribe_scanner(scanner, **kwargs)


class FakeSession:
    def __init__(self, trace):
        self.connected = True
        self.facade, self.sdk_module, self.trace = TraceFacade(trace), fake_sdk(), trace

    def disconnect(self):
        self.trace.append('logout')
        self.connected = False


class FakeMarket:
    def __init__(self, trace):
        self.trace = trace
        self.watchlist = (ID,)
        self.time = BASE
        self.freshness = 'LIVE'
        self.backfill_id = ''
        self.queued_ids = set()
        self.saved = []
        self.fail_save = False
        self.bars = ()
        self.session = NS(connected=True)
        self.history = NS(
            settings=NS(daily_lookback_days=365),
            state=lambda: NS(running=self.backfill_id),
            is_backfilling=lambda key: key == self.backfill_id or key in self.queued_ids,
            on_complete=lambda key: self.trace.append('prior-history-complete'),
        )
        self.store = NS(read=self.read)
        self.reads = 0
        self.on_tick = lambda tick, bars: self.trace.append('prior-tick')
        self.on_bars = lambda *args: self.trace.append('prior-bars')
        self.save_watchlist = self.save

    def now(self):
        return self.time

    def read(self, instrument_id, start, end):
        self.reads += 1
        return tuple(bar for bar in self.bars if bar.instrument_id == instrument_id and start <= bar.start < end)

    def views(self):
        return tuple(
            MarketWatchView(key, reference_price=D(100), health=MarketHealthView(key, self.freshness)) for key in (ID, OTHER, 'INDEX:IX0001', 'INDEX:IX0043')
        )

    def save(self, requested):
        if self.fail_save:
            raise DomainError('operation_failed', 'fake save failure')
        self.trace.append('persist-watchlist')
        self.saved.append(requested)


class MarketAlertsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.trace = []
        self.market = FakeMarket(self.trace)
        self.connection = NS(on_connected=lambda session: self.trace.append('prior-connected'), on_disconnected=lambda: self.trace.append('prior-disconnected'))
        self.bundle = NS(launch=NS(root=Path(self.tmp.name)), market_terminal=self.market, market_connection=self.connection)
        attach_alerts(self.bundle)
        self.alerts = self.bundle.alerts

    def add(self, rule):
        return self.alerts.execute(AlertCommand(AlertOperation.ADD, rule=AlertRuleData.from_rule(rule)))

    def tick(self, price, *, instrument_id=ID, seconds=0, bars=()):
        stamp = BASE + timedelta(seconds=seconds)
        self.market.time = stamp
        tick = Tick(instrument_id, D(price), 1, stamp, stamp, stamp.date())
        self.market.on_tick(tick, bars)

    def snapshot(self):
        return self.alerts.execute(AlertCommand())

    def test_startup_is_offline_and_market_callbacks_remain_chained(self):
        self.assertEqual((), self.snapshot().rules)
        self.assertEqual((), self.snapshot().events)
        self.assertEqual([], self.trace)
        self.tick(99)
        self.assertEqual(['prior-tick'], self.trace)
        self.assertIsNone(self.alerts.service.scanner)

    def test_instrument_watchlist_fixed_indices_and_market_scanner_scope(self):
        self.add(AlertRule('individual', AlertKind.PRICE_CROSS, instrument_id=ID))
        self.add(AlertRule('watch', AlertKind.CHANGE_PERCENT, scope='WATCHLIST', params={'percent': 2}))
        self.add(AlertRule('market', AlertKind.PRICE_JUMP, scope='MARKET'))
        session = FakeSession(self.trace)
        self.connection.on_connected(session)
        self.tick(99)
        self.tick(102, seconds=1)
        self.assertEqual({'individual', 'watch'}, {event.rule_id for event in self.snapshot().events})
        self.tick(105, instrument_id='INDEX:IX0001', seconds=2)
        self.assertEqual('INDEX:IX0001', self.snapshot().events[-1].instrument_id)
        session.facade.callback(NS(scanner=NS(id='trade_surge'), exchange='TSE', quote=NS(code='2317', close='102', datetime=BASE)))
        events = self.alerts.poll_scanner()
        self.assertEqual(1, len(events))
        self.assertEqual('market', events[0].rule_id)
        self.assertEqual(OTHER, events[0].instrument_id)

    def test_successful_watchlist_persistence_updates_filter_failed_save_does_not(self):
        self.add(AlertRule('watch', AlertKind.VOLUME_BURST, scope='WATCHLIST'))
        session = FakeSession(self.trace)
        self.connection.on_connected(session)
        self.market.save_watchlist((OTHER,))
        self.assertEqual((OTHER,), self.alerts.service.watchlist)
        self.market.fail_save = True
        with self.assertRaises(DomainError):
            self.market.save_watchlist((ID,))
        self.assertEqual((OTHER,), self.alerts.service.watchlist)
        for code in ('2330', '2317'):
            session.facade.callback(NS(scanner=NS(id='burst'), exchange='TSE', quote=NS(code=code, close='102', datetime=BASE)))
        self.assertEqual((OTHER,), tuple(event.instrument_id for event in self.alerts.poll_scanner()))
        self.assertEqual([(OTHER,)], self.market.saved)

    def test_scanner_subscriptions_stop_before_logout_and_reconnect_enabled_only(self):
        self.add(AlertRule('scanner', AlertKind.LIMIT_UP, scope='MARKET'))
        first = FakeSession(self.trace)
        self.connection.on_connected(first)
        self.assertEqual('prior-connected', self.trace[0])
        self.assertEqual(6, sum(item == 'scanner-subscribe' for item in self.trace))
        self.connection.on_disconnected()
        first.disconnect()
        self.assertLess(self.trace.index('scanner-unsubscribe'), self.trace.index('logout'))
        self.assertEqual('prior-disconnected', self.trace[-2])
        self.assertIsNone(self.alerts.service.scanner)
        second = FakeSession(self.trace)
        self.connection.on_connected(second)
        self.assertEqual(6, len(second.facade.calls))
        self.alerts.execute(AlertCommand(AlertOperation.ENABLE, rule_id='scanner', enabled=False))
        self.assertEqual(12, len(second.facade.calls))
        self.assertTrue(all(call[0] == 'unsubscribe' for call in second.facade.calls[6:]))

    def test_delayed_stopped_and_backfill_ticks_do_not_trigger(self):
        self.add(AlertRule('r', AlertKind.PRICE_CROSS, instrument_id=ID))
        for offset, freshness, running in ((0, 'DELAYED', ''), (100, 'STOPPED', ''), (200, 'LIVE', ID)):
            self.market.freshness, self.market.backfill_id = freshness, running
            self.tick(99, seconds=offset)
            self.tick(101, seconds=offset + 1)
            self.assertEqual((), self.snapshot().events)
        self.market.freshness, self.market.backfill_id = 'LIVE', ''
        self.tick(99, seconds=300)
        self.tick(101, seconds=301)
        self.assertEqual(1, len(self.snapshot().events))

    def test_prior_day_range_comes_from_official_cached_bars(self):
        prior = BASE - timedelta(days=3)
        self.market.bars = (candle(at=prior, high=105, low=95),)
        self.add(AlertRule('r', AlertKind.PREV_DAY_BREAK, instrument_id=ID))
        self.tick(101)
        self.tick(106, seconds=1)
        self.assertEqual(1, len(self.snapshot().events))
        self.assertEqual(AlertKind.PREV_DAY_BREAK, self.snapshot().events[0].kind)
        self.assertEqual(1, self.market.reads)

    def test_final_heartbeat_uses_current_clock_and_works_after_session_close(self):
        self.add(AlertRule('r', AlertKind.FAST_MOVE, instrument_id=ID, params={'minutes': 1}))
        first = candle(at=BASE - timedelta(minutes=1))
        forming = candle(200, final=False)
        self.tick(100, bars=(first, forming))
        self.assertEqual((), self.snapshot().events)
        now = BASE + timedelta(minutes=1)
        # Complete-bar signals are valid at session-end even when tick freshness is CLOSED.
        self.market.freshness = 'CLOSED'
        self.market.on_bars(ID, (first, replace(forming, final=True)), now, now.date())
        self.assertEqual(1, len(self.snapshot().events))
        self.assertEqual(now, self.snapshot().events[0].occurred_at)
        self.market.on_bars(ID, (first, replace(forming, final=True)), now, now.date())
        self.assertEqual(1, len(self.snapshot().events))
        self.assertIn('prior-bars', self.trace)

    def test_final_heartbeat_rejects_disconnected_stale_backfill_and_incomplete(self):
        self.add(AlertRule('r', AlertKind.FAST_MOVE, instrument_id=ID, params={'minutes': 1}))
        first = candle(at=BASE - timedelta(minutes=1))
        forming = candle(200, final=False)
        self.tick(100, bars=(first, forming))
        now = BASE + timedelta(minutes=1)
        bars = (first, replace(forming, final=True))
        self.market.session.connected = False
        self.market.on_bars(ID, bars, now, now.date())
        self.market.session.connected = True
        self.market.freshness = 'STOPPED'
        self.market.on_bars(ID, bars, now, now.date())
        self.market.freshness, self.market.backfill_id = 'LIVE', ID
        self.market.on_bars(ID, bars, now, now.date())
        self.market.backfill_id = ''
        self.market.on_bars(ID, (first, replace(forming, final=True, incomplete=True)), now, now.date())
        self.assertEqual((), self.snapshot().events)

    def test_queued_backfill_suppresses_ticks_without_seeding_incomplete_history(self):
        self.add(AlertRule('r', AlertKind.PRICE_CROSS, instrument_id=ID))
        self.market.queued_ids.add(ID)
        self.tick(99)
        self.tick(101, seconds=1)
        self.assertEqual((), self.snapshot().events)
        self.assertEqual(0, self.market.reads)
        self.market.queued_ids.clear()
        self.market.history.on_complete(ID)
        self.tick(99, seconds=2)
        self.tick(101, seconds=3)
        self.assertEqual(1, len(self.snapshot().events))
        self.assertEqual(1, self.market.reads)

    def test_backfill_completion_without_any_ticks_invalidates_and_reseeds_history(self):
        self.add(AlertRule('r', AlertKind.PREV_DAY_BREAK, instrument_id=ID))
        self.tick(101)
        self.assertEqual(1, self.market.reads)
        self.assertEqual((), self.snapshot().events)
        # Official history appears entirely between poll ticks.
        self.market.bars = (candle(at=BASE - timedelta(days=3), high=105, low=95),)
        self.market.history.on_complete(ID)
        self.alerts.poll_scanner()
        self.assertEqual(1, self.market.reads)
        self.assertIn('prior-history-complete', self.trace)
        self.tick(106, seconds=1)
        self.assertEqual(2, self.market.reads)
        self.assertEqual(1, len(self.snapshot().events))
        self.assertEqual(D(106), self.snapshot().events[0].value)

    def test_reconnect_does_not_compare_new_ticks_against_previous_session_price(self):
        self.add(AlertRule('r', AlertKind.PRICE_CROSS, instrument_id=ID))
        self.tick(99)
        self.connection.on_disconnected()
        self.connection.on_connected(FakeSession(self.trace))
        self.tick(101, seconds=10)
        self.assertEqual((), self.snapshot().events)
        self.tick(99, seconds=11)
        self.tick(101, seconds=12)
        self.assertEqual(1, len(self.snapshot().events))


if __name__ == '__main__':
    unittest.main()
