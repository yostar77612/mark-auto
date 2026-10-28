"""Application wiring with simulated ticks and fake time; no Domain arithmetic tests."""

from datetime import timedelta
from unittest.mock import patch
import unittest

from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import DataBatch, HistoryBar
from test_tick_adapters_contract import simulated_connector
from test_trading_adapters import NOW, D


class HistoryMarketStub:
    """Supply history outcomes while retaining the simulated live feed."""

    def __init__(self, broker, history_response):
        self.broker = broker
        self.history_response = history_response

    def history(self, instrument_id, start, end):
        return self.history_response(instrument_id, start, end)

    def subscribe(self, instrument_ids):
        return self.broker.subscribe(instrument_ids)

    def unsubscribe(self, subscription_id):
        self.broker.unsubscribe(subscription_id)

    def drain_ticks(self, max_items):
        return self.broker.drain_ticks(max_items)


class LiveMarketServiceTests(unittest.TestCase):
    def setUp(self):
        self.broker, self.clock, self.resolver = simulated_connector()
        self.service = LiveMarketService(self.broker, self.clock, self.resolver)

    def test_strategy_first_allocation_and_watch_refusal(self):
        watches = tuple(f'WATCH:{i}' for i in range(22))
        allocation = self.service.allocate(('WATCH:24', 'WATCH:23'), watches)
        self.assertEqual(allocation.active, ('WATCH:24', 'WATCH:23', *watches[:18]))
        self.assertEqual(allocation.refused, watches[18:])
        self.assertEqual(allocation.error_code, 'capability_missing')
        self.assertEqual(len(self.broker.subscriptions), 20)
        revision = self.service.market_revision
        for action in (lambda: self.service.add_watch('WATCH:22'), lambda: self.service.allocate(watches)):
            with self.subTest(action=action), self.assertRaises(DomainError) as caught:
                action()
            self.assertEqual(caught.exception.code, 'capability_missing')
            self.assertEqual(self.service.market_revision, revision)
        promoted = self.service.allocate(('WATCH:22',), allocation.active)
        self.assertEqual(promoted.active[0], 'WATCH:22')
        self.assertEqual(len(self.broker.subscriptions), 20)
        revision = self.service.market_revision
        self.service.allocate(('WATCH:22',), allocation.active)
        self.assertEqual(self.service.market_revision, revision)

    def test_history_failure_keeps_live_and_recovery_clears_error(self):
        key = 'WATCH:0'

        def history(instrument_id, start, end):
            if isinstance(outcome, DomainError):
                raise outcome
            return outcome

        self.service = LiveMarketService(HistoryMarketStub(self.broker, history), self.clock, self.resolver)
        self.service.allocate((key,))
        self.service.poll(in_session=True)
        live = self.service.watch(key).bars
        for failure in (DomainError('rate_limited', 'test'), DataBatch(key, (), 'TEST', False, 'no_data')):
            with self.subTest(failure=failure):
                outcome = failure
                self.service.backfill(key, NOW - timedelta(days=1), NOW)
                self.assertEqual(self.service.watch(key).bars, live)
                self.assertTrue(self.service.watch(key).health.history_error)
                self.assertTrue(self.service.overview().has_warning)
        outcome = DataBatch(key, (), 'TEST', True)
        self.service.backfill(key, NOW - timedelta(days=1), NOW)
        self.assertEqual(self.service.watch(key).health.history_error, '')

    def test_revision_tracks_changes_not_poll_calls(self):
        self.assertEqual(self.service.poll(), 0)
        self.service.allocate(('WATCH:0',))
        allocated = self.service.market_revision
        self.service.poll(in_session=True)
        received = self.service.market_revision
        self.assertEqual(received, allocated + 1)
        self.assertEqual(self.service.poll(in_session=True), received)
        # A replayed identical delivery must not increment the market revision.
        tick = self.service._buffers['WATCH:0'].tick
        with patch.object(self.broker, 'drain_ticks', return_value=(tick,)):
            self.assertEqual(self.service.poll(in_session=True), received)
        with patch.object(self.broker, 'drain_ticks', return_value=()):
            self.clock.value += timedelta(seconds=11)
            self.assertEqual(self.service.poll(in_session=True), received + 1)
            self.assertEqual(self.service.poll(in_session=True), received + 1)
            self.clock.value += timedelta(minutes=1)
            self.assertEqual(self.service.poll(in_session=True), received + 2)
        self.assertEqual(self.service.overview().market_revision, self.service.market_revision)

    def test_history_windows_and_trade_day_buffer_retention(self):
        key = 'WATCH:0'
        start = NOW - timedelta(days=65)
        windows = []

        def history(instrument_id, begin, end):
            windows.append((begin, end))
            bars = tuple(
                HistoryBar(key, begin + timedelta(days=i), begin + timedelta(days=i, minutes=1), D('100'), D('100'), D('100'), D('100'), 1, 'TEST')
                for i in range((end - begin).days)
            )
            return DataBatch(key, bars, 'TEST', True)

        service = LiveMarketService(HistoryMarketStub(self.broker, history), self.clock, self.resolver, settings=LiveMarketSettings(buffer_trade_days=2))
        service.allocate((key,))
        service.backfill(key, start, NOW)
        self.assertEqual(
            windows, [(start, start + timedelta(days=30)), (start + timedelta(days=30), start + timedelta(days=60)), (start + timedelta(days=60), NOW)]
        )
        self.assertLessEqual(len({bar.trade_date for bar in service.watch(key).bars}), 2)
        service.poll(in_session=True)
        # Finalizing in a quiet poll must not lose that minute on the next tick.
        first_start = service.watch(key).bars[-1].start
        with patch.object(self.broker, 'drain_ticks', return_value=()):
            self.clock.value += timedelta(minutes=1)
            service.poll(in_session=True)
        service.poll(in_session=True)
        self.assertIn(first_start, tuple(bar.start for bar in service.watch(key).bars))
        self.assertTrue(service.watch(key, period='5m').bars)
