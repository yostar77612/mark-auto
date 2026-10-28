"""Shared connector drain contract; no Domain bar or freshness calculations.

T4 can add its fake-SDK connector factory to the same cases.
"""

from dataclasses import replace
from datetime import timedelta
import unittest

from quantlab.trading.adapters.simulated.broker import SimulatedBroker
from quantlab.trading.adapters.simulated.tick_feed import SimulatedTickFeed
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.interfaces import MarketDataPort
from test_trading_adapters import MutableClock, account, capability, instrument, NOW


class ExplicitSessionResolver:
    def session_at(self, instrument_id, timestamp):
        return timestamp.date() + timedelta(days=1), 'NIGHT'


def simulated_connector():
    clock = MutableClock()
    specs = tuple(replace(instrument(), instrument_id=f'WATCH:{i}') for i in range(25))
    resolver = ExplicitSessionResolver()
    feed = SimulatedTickFeed(clock, resolver, start=NOW, seed=42)
    broker = SimulatedBroker(clock, account(), specs, capability(), tick_feed=feed)
    return broker, clock, resolver


class TickAdapterContractTests(unittest.TestCase):
    # Extend this factory table with the T4 fake-SDK connector, retaining cases.
    connector_factories = (('simulated', simulated_connector),)

    def test_explicit_no_catchup_feed_does_not_replay_skipped_simulation_days(self):
        broker, clock, resolver = simulated_connector()
        broker.tick_feed = SimulatedTickFeed(clock, resolver, start=NOW, catch_up=False)
        broker.subscribe(('WATCH:0',))
        broker.drain_ticks(10)
        clock.value += timedelta(days=3)
        ticks = broker.drain_ticks(10)
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].source_at, clock.now())
        self.assertEqual(broker.drain_ticks(10), ())

    def test_drain_contract(self):
        for name, factory in self.connector_factories:
            with self.subTest(connector=name):
                broker, clock, _ = factory()
                self.assertEqual(broker.drain_ticks(5), ())
                receipt = broker.subscribe(('WATCH:0', 'WATCH:1'))
                self.assertEqual(broker.drain_ticks(0), ())
                first = broker.drain_ticks(1)
                self.assertEqual(len(first), 1)
                clock.value += timedelta(seconds=2)
                batches = tuple(broker.drain_ticks(limit) for limit in (2, 1, 9))
                for batch, limit in zip(batches, (2, 1, 9)):
                    self.assertLessEqual(len(batch), limit)
                ticks = first + sum(batches, ())
                keys = tuple((tick.source_at, tick.instrument_id) for tick in ticks)
                self.assertEqual(keys, tuple(sorted(keys)))
                identities = tuple((tick.source, tick.sequence) for tick in ticks)
                self.assertEqual(len(identities), len(set(identities)))
                self.assertEqual(broker.drain_ticks(99), ())
                broker.unsubscribe(receipt.subscription_id)
                clock.value += timedelta(seconds=1)
                self.assertEqual(broker.drain_ticks(99), ())
                with self.assertRaises(DomainError):
                    broker.drain_ticks(-1)

    def test_simulated_seed_batching_and_resolver(self):
        results = []
        for limits in ((1, 5), (3, 3)):
            with self.subTest(limits=limits):
                broker, clock, resolver = simulated_connector()
                broker.subscribe(('WATCH:0', 'WATCH:1'))
                broker.drain_ticks(0)
                clock.value += timedelta(seconds=2)
                ticks = sum((broker.drain_ticks(limit) for limit in limits), ())
                results.append(ticks)
                for tick in ticks:
                    self.assertEqual((tick.trade_date, tick.session), resolver.session_at(tick.instrument_id, tick.source_at))
        self.assertEqual(results[0], results[1])


class ExistingMarketContractTests(unittest.TestCase):
    def test_existing_market_surface_and_simulator_defaults(self):
        for name in ('history', 'subscribe', 'unsubscribe', 'latest'):
            with self.subTest(method=name):
                self.assertTrue(callable(getattr(MarketDataPort, name)))
        clock, spec = MutableClock(), instrument()
        broker = SimulatedBroker(clock, account(), (spec,), capability())
        self.assertEqual(broker.subscriptions, {})
        self.assertIsNone(broker.latest(spec.instrument_id))
        receipt = broker.subscribe((spec.instrument_id,))
        self.assertTrue(receipt.active)
        self.assertEqual(receipt.instrument_ids, (spec.instrument_id,))
        broker.unsubscribe(receipt.subscription_id)
        self.assertEqual(broker.subscriptions, {})
        self.assertFalse(broker.history(spec.instrument_id, NOW, NOW.replace(hour=2)).complete)
