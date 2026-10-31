"""Authenticated-wire-compatible alert commands and live observer timing tests."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import unittest

from quantlab.trading.application.alert_contracts import AlertCommand, AlertProxy
from quantlab.trading.application.alert_observer import AlertTickObserver
from quantlab.trading.application.alert_service import AlertService
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import MarketHealthView, MarketWatchView
from quantlab.trading.domain.alerts import AlertKind, AlertRule
from quantlab.trading.domain.ticks import Tick
from tests.test_alert_rules import ID, NOW, bar, fixtures
from tests.test_alert_ui import MemoryStore


class AlertTransportTests(unittest.TestCase):
    def test_roundtrip_snapshot_commands_proxy_and_nonfinite_boundary(self):
        service = AlertService(MemoryStore(), now=NOW)

        def call(command):
            return loads(dumps(service.execute(loads(dumps(command)))))

        proxy = AlertProxy(call)
        proxy.refresh()
        rule, observation = next(fixtures())
        proxy.add_rule(rule)
        self.assertEqual((rule,), proxy.rules)
        service.observe(observation)
        proxy.refresh()
        self.assertEqual(tuple(service.events), proxy.events)
        proxy.set_enabled(rule.rule_id, False)
        self.assertFalse(proxy.rules[0].enabled)
        proxy.clear_events()
        self.assertEqual((), proxy.events)
        proxy.delete_rule(rule.rule_id)
        self.assertEqual((), proxy.rules)
        self.assertEqual(AlertCommand(), loads(dumps(AlertCommand())))

    def test_tick_observer_previous_price_reference_and_only_live(self):
        service = AlertService(MemoryStore(), now=NOW)
        service.add_rule(AlertRule('r', AlertKind.PRICE_CROSS, instrument_id=ID))
        view = MarketWatchView(ID, reference_price=D(90), health=MarketHealthView(ID, 'LIVE'))
        reads = []
        observer = AlertTickObserver(service, lambda key: view, lambda key: reads.append(key) or (), lambda key: False)
        tick = Tick(ID, D(99), 1, NOW, NOW, NOW.date())
        self.assertEqual((), observer.on_tick(tick, ()))
        self.assertEqual(
            1, len(observer.on_tick(replace(tick, price=D(101), source_at=NOW + timedelta(seconds=1), received_at=NOW + timedelta(seconds=1)), ()))
        )
        self.assertEqual([ID], reads)
        view = replace(view, health=MarketHealthView(ID, 'STOPPED'))
        self.assertEqual((), observer.on_tick(replace(tick, price=D(99), source_at=NOW + timedelta(seconds=60), received_at=NOW + timedelta(seconds=60)), ()))

    def test_completed_bar_observer_ignores_seed_and_forming_then_fires(self):
        service = AlertService(MemoryStore(), now=NOW)
        service.add_rule(AlertRule('r', AlertKind.FAST_MOVE, instrument_id=ID, params={'minutes': 1}))
        view = MarketWatchView(ID, health=MarketHealthView(ID, 'LIVE'))
        observer = AlertTickObserver(service, lambda key: view, lambda key: (), lambda key: False)
        tick = Tick(ID, D(100), 1, NOW + timedelta(minutes=1), NOW + timedelta(minutes=1), NOW.date())
        first = bar('100', minute=0)
        forming = bar('200', opening='100', minute=1, final=False)
        self.assertEqual((), observer.on_tick(tick, (first, forming)))
        self.assertEqual(
            (),
            observer.on_tick(
                replace(tick, source_at=NOW + timedelta(minutes=1, seconds=1), received_at=NOW + timedelta(minutes=1, seconds=1)), (first, forming)
            ),
        )
        tick = replace(tick, source_at=NOW + timedelta(minutes=2), received_at=NOW + timedelta(minutes=2))
        events = observer.on_tick(tick, (first, replace(forming, final=True)))
        self.assertEqual(1, len(events))
        self.assertEqual(AlertKind.FAST_MOVE, events[0].kind)
        self.assertEqual((), observer.on_tick(tick, (first, replace(forming, final=True))))


if __name__ == '__main__':
    unittest.main()
