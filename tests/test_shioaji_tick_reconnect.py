"""Mock session recovery through real ports and Application; no broker or secrets.

History outcomes are injected at the fake SDK boundary. Domain arithmetic stays
in its own suite; these cases assert subscription order, recovery and gap wiring.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import DataGap
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.live_market import RoutedMarketData
from shioaji_tick_fakes import TickSDK, tick_gateway
from test_trading_adapters import D, NOW


class HistorySDK(TickSDK):
    def __init__(self, specs):
        super().__init__(specs)
        self.history_calls = []
        self.fail_dates = set()
        self.empty = False
        self.fail_subscription = False

    def subscribe(self, contract, *, quote_type, version):
        if self.fail_subscription:
            raise RuntimeError('fake subscription failure')
        super().subscribe(contract, quote_type=quote_type, version=version)

    def kbars(self, *, contract, start, end, timeout):
        self.history_calls.append((contract.code, start, end, timeout))
        if start in self.fail_dates:
            raise ConnectionError('fake history failure')
        begin = datetime.fromisoformat(start).replace(tzinfo=NOW.tzinfo)
        stop = datetime.fromisoformat(end).replace(tzinfo=NOW.tzinfo) + timedelta(days=1)
        stamps = () if self.empty else tuple(begin + timedelta(hours=1, minutes=i + 1) for i in range(10))
        stamps = tuple(stamp for stamp in stamps if stamp < stop)
        return SimpleNamespace(
            ts=stamps, Open=[99] * len(stamps), High=[99] * len(stamps), Low=[99] * len(stamps), Close=[99] * len(stamps), Volume=[1] * len(stamps)
        )


class ReconnectTests(unittest.TestCase):
    def make_service(self, *, limit=3):
        settings = LiveMarketSettings(subscription_limit=limit)
        gateway, sdk, clock, resolver = tick_gateway(sdk_type=HistorySDK, market_settings=settings)
        routed = RoutedMarketData({key: gateway for key in gateway.bindings}, clock)
        return LiveMarketService(routed, clock, resolver, settings=settings), gateway, sdk, clock

    def test_disconnect_between_polls_restores_strategy_first_with_settings_limit(self):
        for limit in (2, 20):
            with self.subTest(limit=limit):
                service, gateway, sdk, clock = self.make_service(limit=limit)
                # Promote a watch after initial allocation so receipt insertion
                # order differs from strategy priority on recovery.
                watches = tuple(f'WATCH:{i}' for i in range(23))
                service.allocate((), watches)
                allocation = service.allocate(('WATCH:1',), watches)
                sdk.emit('1')
                service.poll(in_session=True)
                last_price = service.watch('WATCH:1').price
                sdk.calls.clear()
                lost_at = clock.now()
                sdk.callbacks['session_down']('fake session lost')
                clock.value += timedelta(days=65)
                gateway.attach_authenticated()  # fake account adoption, no credentials
                service.poll(in_session=True)
                restored = tuple(f'WATCH:{call[1]}' for call in sdk.calls if call[0] == 'subscribe')
                self.assertEqual(restored, allocation.active)
                self.assertEqual(len(restored), limit)
                self.assertEqual(len(gateway.subscriptions), limit)
                self.assertEqual(service.watch('WATCH:1').price, last_price)
                self.assertEqual(service.watch('WATCH:1').health.history_error, '')
                self.assertEqual(len(sdk.history_calls), limit * 3)
                self.assertEqual(
                    tuple(call[1:3] for call in sdk.history_calls[:3]),
                    tuple(
                        (start.date().isoformat(), end.date().isoformat())
                        for start, end in (
                            (lost_at, lost_at + timedelta(days=30)),
                            (lost_at + timedelta(days=30), lost_at + timedelta(days=60)),
                            (lost_at + timedelta(days=60), clock.now()),
                        )
                    ),
                )
                calls = len(sdk.calls), len(sdk.history_calls)
                service.poll(in_session=True)
                self.assertEqual((len(sdk.calls), len(sdk.history_calls)), calls)
                sdk.emit('1', datetime=clock.now(), close=102)
                service.poll(in_session=True)
                self.assertEqual(service.watch('WATCH:1').price, D('102'))

    def test_failed_or_empty_window_is_a_data_gap_and_later_windows_continue(self):
        for failure in ('query', 'empty'):
            with self.subTest(failure=failure):
                service, gateway, sdk, clock = self.make_service(limit=1)
                service.allocate(('WATCH:0',))
                sdk.emit()
                service.poll(in_session=True)
                lost_at = clock.now()
                gateway.disconnect()
                service.poll(in_session=True)
                self.assertEqual(service.watch('WATCH:0').health.freshness, 'STOPPED')
                clock.value += timedelta(days=65)
                if failure == 'query':
                    sdk.fail_dates.add(lost_at.date().isoformat())
                else:
                    sdk.empty = True
                gateway.attach_authenticated()
                service.poll(in_session=True)
                view = service.watch('WATCH:0')
                self.assertIn(DataGap(lost_at, lost_at + timedelta(days=30)), view.gaps)
                self.assertTrue(view.health.history_error)
                self.assertTrue(view.health.incomplete)
                self.assertEqual(len(sdk.history_calls), 3)
                self.assertEqual(view.price, D('100.25'))
                if failure == 'query':
                    self.assertTrue(any(bar.start >= lost_at + timedelta(days=30) for bar in view.bars))

    def test_recovery_inside_live_suffix_keeps_live_overlap_and_retry_removes_gap(self):
        service, gateway, sdk, clock = self.make_service(limit=1)
        service.allocate(('WATCH:0',))
        sdk.emit()
        service.poll(in_session=True)
        clock.value += timedelta(minutes=1)
        gateway.disconnect()
        lost_at = clock.now()
        sdk.empty = True
        clock.value += timedelta(minutes=4)
        gateway.attach_authenticated()
        service.poll(in_session=True)
        self.assertIn(DataGap(lost_at, clock.now()), service.watch('WATCH:0').gaps)
        sdk.emit(datetime=clock.now(), close=105)
        service.poll(in_session=True)
        sdk.empty = False
        service.backfill('WATCH:0', lost_at, clock.now())
        view = service.watch('WATCH:0')
        self.assertEqual(view.gaps, ())
        self.assertEqual(view.health.history_error, '')
        self.assertIn(lost_at, tuple(bar.start for bar in view.bars))
        self.assertEqual(view.bars[0].close, D('100.25'))
        self.assertEqual(view.bars[-1].close, D('105'))
        self.assertEqual(len(view.bars), len({bar.start for bar in view.bars}))

    def test_failed_restore_is_reported_and_retry_keeps_last_known_data(self):
        service, gateway, sdk, clock = self.make_service(limit=1)
        service.allocate(('WATCH:0',))
        sdk.emit()
        service.poll(in_session=True)
        gateway.disconnect()
        clock.value += timedelta(minutes=2)
        gateway.attach_authenticated()
        sdk.fail_subscription = True
        with self.assertRaises(DomainError):
            service.poll(in_session=True)
        self.assertEqual(service.watch('WATCH:0').price, D('100.25'))
        sdk.fail_subscription = False
        service.allocate(('WATCH:0',))
        service.poll(in_session=True)
        self.assertEqual(len(gateway.subscriptions), 1)
        self.assertEqual(service.watch('WATCH:0').price, D('100.25'))


if __name__ == '__main__':
    unittest.main()
