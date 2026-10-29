"""Application loss reporting via fake SDK delivery; no bar arithmetic tests."""

from datetime import timedelta
import unittest

from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.runtime.live_market import RoutedMarketData
from shioaji_tick_fakes import tick_gateway
from test_trading_adapters import NOW


class TickOverflowTests(unittest.TestCase):
    def test_configured_overflow_marks_affected_bar_and_records_one_issue(self):
        gateway, sdk, clock, resolver = tick_gateway(market_settings=LiveMarketSettings(queue_limit=1))
        routed = RoutedMarketData({'WATCH:0': gateway}, clock)
        service = LiveMarketService(routed, clock, resolver)
        service.allocate(('WATCH:0',))
        for _ in range(4):
            sdk.emit()
        service.poll(in_session=True)
        self.assertTrue(service.watch('WATCH:0').bars[0].incomplete)
        self.assertEqual(len(service.issues), 1)
        (issue,) = service.issues
        self.assertEqual((issue.instrument_id, issue.count, issue.code), ('WATCH:0', 3, 'tick_queue_overflow'))
        service.poll(in_session=True)
        self.assertEqual(len(service.issues), 1)

    def test_loss_before_first_tick_of_next_minute_is_remembered(self):
        gateway, sdk, clock, resolver = tick_gateway(market_settings=LiveMarketSettings(queue_limit=1))
        service = LiveMarketService(gateway, clock, resolver)
        service.allocate(('WATCH:0',))
        sdk.emit()
        clock.value += timedelta(minutes=1)
        sdk.emit(datetime=clock.now())
        service.poll(in_session=True)
        self.assertFalse(service.watch('WATCH:0').bars[0].incomplete)
        sdk.emit(datetime=clock.now())
        service.poll(in_session=True)
        bars = service.watch('WATCH:0').bars
        self.assertFalse(bars[0].incomplete)
        self.assertTrue(bars[1].incomplete)

    def test_late_overflow_marks_final_bar_without_contaminating_current_minute(self):
        gateway, sdk, clock, resolver = tick_gateway(market_settings=LiveMarketSettings(queue_limit=1))
        service = LiveMarketService(gateway, clock, resolver)
        service.allocate(('WATCH:0',))
        sdk.emit()
        service.poll(in_session=True)
        clock.value += timedelta(minutes=1)
        sdk.emit(datetime=clock.now())
        sdk.emit(datetime=NOW)
        service.poll(in_session=True)
        bars = service.watch('WATCH:0').bars
        self.assertTrue(bars[0].incomplete)
        self.assertFalse(bars[1].incomplete)


if __name__ == '__main__':
    unittest.main()
