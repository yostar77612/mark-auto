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
    def test_only_changed_instrument_views_are_rebuilt(self):
        class RecordingService(LiveMarketService):
            calls = ()

            def watch(self, key, **kwargs):
                self.calls += (key,)
                return super().watch(key, **kwargs)

        broker, clock, resolver = simulated_connector()
        service = RecordingService(broker, clock, resolver)
        service.allocate(('WATCH:0', 'WATCH:1'))
        service.poll(in_session=True)
        service.calls = ()
        revision = service.market_revision
        service.poll(in_session=True)
        self.assertEqual(service.calls, ())
        self.assertEqual(service.market_revision, revision)
        tick = service._buffers['WATCH:0'].tick
        from dataclasses import replace

        with patch.object(broker, 'drain_ticks', return_value=(replace(tick, sequence=tick.sequence + 1, volume=2),)):
            service.poll(in_session=True)
        self.assertEqual(service.calls, ('WATCH:0',))
        self.assertEqual(service.market_revision, revision + 1)
        self.assertEqual(service._views(), tuple(service.watch(key) for key in service.allocation.active))

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

    def test_cached_history_prefix_matches_uncached_watch(self):
        key = 'WATCH:0'

        def history(shift):
            return tuple(
                HistoryBar(key, NOW - timedelta(minutes=m), NOW - timedelta(minutes=m - 1), D('100'), D('103'), D('99'), D(100 + (m + shift) % 3), 1, 'TEST')
                # History runs past the first live minute so the live cut removes bars.
                for m in range(600, -5, -1)
            )

        source = [history(0)]
        self.service = LiveMarketService(HistoryMarketStub(self.broker, lambda *_: DataBatch(key, source[0], 'TEST', True)), self.clock, self.resolver)
        self.service.allocate((key,))
        steps = (
            ('backfill before live', lambda: self.service.backfill(key, NOW - timedelta(days=1), NOW + timedelta(minutes=10))),
            ('first ticks', lambda: self.service.poll(in_session=True)),
            ('next minute', lambda: (setattr(self.clock, 'value', self.clock.value + timedelta(minutes=1)), self.service.poll(in_session=True))),
            ('backfill after live', lambda: self.service.backfill(key, NOW - timedelta(days=1), NOW)),
            # Same window and bar count with new closes: only the revision can invalidate the cache.
            ('same-size re-backfill', lambda: (source.__setitem__(0, history(1)), self.service.backfill(key, NOW - timedelta(days=1), NOW))),
        )
        for name, step in steps:
            with self.subTest(step=name):
                step()
                for period in ('1m', '5m'):
                    cached = self.service.watch(key, period=period)
                    self.service._buffers[key].prefix = None
                    self.assertEqual(cached, self.service.watch(key, period=period))

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


class _ScriptedMarket:
    """Ticks and tick losses handed out once per poll, identically to every service under comparison."""

    def __init__(self):
        self.ticks, self.losses = (), ()

    def subscribe(self, instrument_ids):
        from quantlab.trading.ports.contracts import SubscriptionReceipt

        return SubscriptionReceipt('scripted', tuple(instrument_ids), True, NOW)

    def unsubscribe(self, subscription_id):
        pass

    def history(self, instrument_id, start, end):
        raise AssertionError('history is not read in this comparison')

    def drain_ticks(self, max_items):
        ticks, self.ticks = self.ticks[:max_items], self.ticks[max_items:]
        return ticks

    def drain_tick_losses(self):
        losses, self.losses = self.losses, ()
        return losses


class _ScriptedClock:
    def __init__(self):
        self.value = NOW

    def now(self):
        return self.value


class _DayResolver:
    def session_at(self, instrument_id, timestamp):
        return timestamp.date(), 'DAY'


class TickLossEquivalenceTests(unittest.TestCase):
    """OPT-1 P9: poll() under tick losses equals the frozen pre-change poll in every observable field."""

    KEYS = ('WATCH:0', 'WATCH:1')

    def stack(self, cls):
        from quantlab.trading.application.live_market import LiveBar

        market, clock = _ScriptedMarket(), _ScriptedClock()
        service = cls(market, clock, _DayResolver(), settings=LiveMarketSettings(buffer_trade_days=1))  # deques hold 1,440
        service.allocate(self.KEYS)
        for index, key in enumerate(self.KEYS):
            buffer = service._buffers[key]
            for minute in range(1200, 0, -1):
                start = NOW - timedelta(minutes=minute)
                price = D(100 + (minute + index) % 7)
                buffer.history.append(LiveBar(key, start, start + timedelta(minutes=1), start.date(), 'DAY', price, price + 1, price - 1, price, 3, final=True))
        return service, market, clock

    @staticmethod
    def state(service):
        buffers = tuple(
            (
                key,
                repr(tuple(buffer.history)),
                repr(tuple(buffer.live)),
                repr(buffer.minute),
                repr(buffer.tick),
                buffer.history_revision,
                repr(tuple(buffer.losses)),
                buffer.first_live_start,
                buffer.freshness,
            )
            for key, buffer in sorted(service._buffers.items())
        )
        views = tuple(repr(service.watch(key, period=period)) for key in TickLossEquivalenceTests.KEYS for period in ('1m', '5m'))
        return buffers, repr(tuple(service.issues)), service.market_revision, tuple(sorted(service._view_cache)), views

    def test_random_ticks_and_losses_match_the_frozen_poll(self):
        import random

        from quantlab.trading.application.live_market import LiveMarketService
        from quantlab.trading.domain.ticks import Tick
        from quantlab.trading.ports.tick_stream import TickLoss
        from tests.live_market_poll_reference import ReferenceLiveMarketService

        generator = random.Random(20261120)
        new, reference = self.stack(LiveMarketService), self.stack(ReferenceLiveMarketService)
        sequence = 0
        for step in range(160):
            now = NOW + timedelta(seconds=20 * step)
            ticks, losses = [], []
            for _ in range(generator.randint(0, 30)):
                sequence += 1
                at = now - timedelta(seconds=generator.randint(0, 90))
                key = generator.choice(self.KEYS)
                ticks.append(Tick(key, D(100 + generator.randint(0, 9)), 1, at, now, at.date(), sequence=sequence))
            for _ in range(generator.choice((0, 0, 1, 3, 40, 120))):
                span = generator.choice((0, 0, 1, 5, 90, 1500))  # zero-length, short, long and wider-than-retention losses
                last = now - timedelta(minutes=generator.randint(0, 1300), seconds=generator.randint(0, 59))
                first = last - timedelta(minutes=span, seconds=generator.randint(0, 59))
                key = generator.choice((*self.KEYS, 'WATCH:9'))  # an unallocated instrument only reaches issues
                losses.append(TickLoss(key, first, last, generator.randint(1, 50)))
            for service, market, clock in (new, reference):
                clock.value = now
                market.ticks, market.losses = tuple(ticks), tuple(losses)
                service.poll(in_session=True)
            with self.subTest(step=step):
                self.assertEqual(self.state(new[0]), self.state(reference[0]))
        self.assertTrue(all(len(new[0]._buffers[key].losses) == new[0]._buffers[key].losses.maxlen == 1440 for key in self.KEYS))  # evicted
        self.assertTrue(any(bar.incomplete for key in self.KEYS for bar in new[0]._buffers[key].history))
