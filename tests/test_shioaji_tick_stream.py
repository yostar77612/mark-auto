"""SDK tick boundary checks with fake callbacks; no Domain bar arithmetic."""

from datetime import timedelta
from threading import Thread
import unittest

from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.validation import DomainError
from shioaji_tick_fakes import tick_gateway
from test_trading_adapters import D, NOW


class TickStreamTests(unittest.TestCase):
    def test_callbacks_register_once_through_facade_and_normalise(self):
        gateway, sdk, clock, resolver = tick_gateway()
        self.assertEqual(sdk.calls, [])
        gateway.subscribe(('WATCH:0',))
        gateway.subscribe(('WATCH:0',))
        self.assertEqual(sdk.calls[:2], [('stk', False), ('fop', False)])
        self.assertEqual(sum(call[0] == 'fop' for call in sdk.calls), 1)
        for kind, price in (('stk', 100.25), ('fop', '100.25')):
            with self.subTest(kind=kind, price=price):
                self.assertIsNone(sdk.emit(kind=kind, close=price))
                (tick,) = gateway.drain_ticks(1)
                self.assertEqual(tick.price, D('100.25'))
                self.assertIs(type(tick.price), D)
                self.assertEqual((tick.trade_date, tick.session), resolver.session_at('WATCH:0', NOW))
                self.assertEqual((tick.source_at, tick.received_at, tick.source), (NOW, clock.now(), 'SHIOAJI'))

    def test_normalisation_rejects_invalid_sdk_input_without_guessing(self):
        from quantlab.trading.adapters.shioaji.tick_stream import normalise_tick

        from types import SimpleNamespace

        class UnknownSession:
            def session_at(self, key, at):
                return at.date(), 'UNKNOWN'

        class MissingCalendar:
            def session_at(self, key, at):
                raise DomainError('calendar_missing', 'no calendar')

        for changes, received, resolver in (
            ({'close': 0}, NOW, None),
            ({'close': -1}, NOW, None),
            ({}, NOW - timedelta(seconds=1), None),
            ({}, NOW, UnknownSession()),
            ({}, NOW, MissingCalendar()),
            ({'volume': -1}, NOW, None),
            ({'datetime': NOW.replace(tzinfo=None)}, NOW, None),
        ):
            with self.subTest(changes=changes, received=received, resolver=resolver):
                _, _, _, valid_resolver = tick_gateway()
                raw = SimpleNamespace(**dict({'datetime': NOW, 'close': 10, 'volume': 1}, **changes))
                with self.assertRaises(DomainError):
                    normalise_tick(raw, 'WATCH:0', received, resolver or valid_resolver)
        with self.assertRaises(DomainError) as caught:
            normalise_tick(SimpleNamespace(datetime=NOW, close=10, volume=1), 'WATCH:0', NOW, None)
        self.assertEqual(caught.exception.code, 'calendar_missing')

    def test_callback_exception_is_recorded_and_next_tick_flows(self):
        gateway, sdk, _, _ = tick_gateway()
        gateway.subscribe(('WATCH:0',))

        class BrokenTick:
            code = '0'

            @property
            def datetime(self):
                raise RuntimeError('sensitive SDK message')

        with self.assertLogs('quantlab.trading.adapters.shioaji.tick_stream', level='ERROR') as logs:
            self.assertIsNone(sdk.callbacks['fop']('TAIFEX', BrokenTick()))
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn('sensitive SDK message', logs.output[0])
        sdk.emit()
        self.assertEqual(len(gateway.drain_ticks(9)), 1)

    def test_threaded_delivery_is_bounded_and_accounts_for_every_tick(self):
        for limit in (3, 100):
            with self.subTest(limit=limit):
                gateway, sdk, _, _ = tick_gateway(market_settings=LiveMarketSettings(queue_limit=limit))
                gateway.subscribe(('WATCH:0',))
                results = []
                producer = Thread(target=lambda: results.extend(sdk.emit() for _ in range(100)), daemon=True)
                producer.start()
                producer.join(1)
                self.assertFalse(producer.is_alive())
                self.assertEqual(len(results), 100)
                ticks = gateway.drain_ticks(100)
                losses = gateway.drain_tick_losses()
                self.assertEqual(len(ticks), limit)
                self.assertEqual(len(ticks) + sum(loss.count for loss in losses), 100)
                self.assertEqual(gateway.drain_tick_losses(), ())


if __name__ == '__main__':
    unittest.main()
