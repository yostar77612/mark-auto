"""Persistence, scope filtering and enabled-only SDK scanner subscriptions."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from quantlab.trading.adapters.shioaji.scanner_stream import ShioajiScannerStream
from quantlab.trading.adapters.storage.alert_store import JsonAlertStore
from quantlab.trading.application.alert_service import AlertService
from quantlab.trading.domain.alerts import AlertEvent, AlertKind, AlertObservation, AlertRule
from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.validation import DomainError
from tests.test_alert_rules import ID, NOW


class FakeFacade:
    def __init__(self):
        self.calls = []

    def set_on_scanner_callback(self, callback):
        self.callback = callback

    def subscribe_scanner(self, scanner, **kwargs):
        self.calls.append(('subscribe', scanner.id, kwargs))

    def unsubscribe_scanner(self, scanner, **kwargs):
        self.calls.append(('unsubscribe', scanner.id, kwargs))


def fake_sdk():
    def presets(names):
        return NS(**{name: (lambda key=name: NS(id=key)) for name in names})

    return NS(
        LimitScanner=presets(
            ('bid_near_limit_up', 'bid_touch_limit_up', 'limit_up_unlocked', 'ask_near_limit_down', 'ask_touch_limit_down', 'limit_down_unlocked')
        ),
        PriceMoveScanner=presets(('trade_surge', 'trade_drop')),
        VolumeScanner=presets(('burst',)),
        ShioajiError=RuntimeError,
        Region=NS(TW='TW'),
        SecurityType=NS(Stock='STK'),
        Exchange=NS(TSE='TSE', OTC='OTC'),
    )


class AlertServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = JsonAlertStore(self.root)

    def test_rules_persist_enable_delete_and_scanners_only_enabled(self):
        facade = FakeFacade()
        scanner = ShioajiScannerStream(facade, fake_sdk())
        service = AlertService(self.store, now=NOW, scanner=scanner)
        self.assertEqual([], facade.calls)
        rule = AlertRule('r', AlertKind.LIMIT_UP, scope='MARKET')
        service.add_rule(rule)
        self.assertEqual(6, len(facade.calls))
        service.add_rule(replace(rule, rule_id='r2'))
        self.assertEqual(6, len(facade.calls))
        service.set_enabled('r', False)
        self.assertEqual(6, len(facade.calls))
        service.delete_rule('r2')
        self.assertEqual(12, len(facade.calls))
        self.assertTrue(all(call[0] == 'unsubscribe' for call in facade.calls[6:]))
        restored = AlertService(JsonAlertStore(self.root), now=NOW)
        self.assertEqual((replace(rule, enabled=False),), restored.rules)
        for _, _, kwargs in facade.calls:
            self.assertEqual({'region': 'TW', 'security_type': 'STK', 'exchange': kwargs['exchange']}, kwargs)
            self.assertIn(kwargs['exchange'], ('TSE', 'OTC'))

    def test_watchlist_filters_local_events_includes_fixed_indices(self):
        service = AlertService(self.store, now=NOW)
        service.add_rule(AlertRule('r', AlertKind.CHANGE_PERCENT, scope='WATCHLIST'))
        observation = AlertObservation(ID, NOW, price=D(102), reference_price=D(100), freshness=Freshness.LIVE)
        self.assertEqual((), service.observe(observation))
        service.watchlist = (ID,)
        self.assertEqual(1, len(service.observe(observation)))
        self.assertEqual(1, len(service.observe(replace(observation, instrument_id='INDEX:IX0001'))))
        self.assertEqual((), service.observe(replace(observation, instrument_id='TWSE:2317')))
        service.clear_events()
        self.assertEqual(0, len(service.events))
        self.assertEqual(2, len(AlertService(JsonAlertStore(self.root), now=NOW).events))

    def test_scanner_pulses_rearm_but_cooldown_and_scope_filter(self):
        facade = FakeFacade()
        scanner = ShioajiScannerStream(facade, fake_sdk())
        service = AlertService(self.store, now=NOW, scanner=scanner)
        service.watchlist = (ID,)
        service.add_rule(AlertRule('r', AlertKind.PRICE_JUMP, scope='WATCHLIST'))

        def deliver(code, seconds):
            facade.callback(NS(scanner=NS(id='trade_surge'), exchange='TSE', quote=NS(code=code, close='102', datetime=NOW + timedelta(seconds=seconds))))
            return service.poll_scanner()

        self.assertEqual((), deliver('2317', 0))
        self.assertEqual(1, len(deliver('2330', 0)))
        self.assertEqual((), deliver('2330', 1))
        self.assertEqual(1, len(deliver('2330', 60)))
        self.assertEqual('UP', service.events[-1].message_args[1])

    def test_corrupt_rules_and_events_preserved_and_warned(self):
        self.store.directory.mkdir()
        self.store.rules_path.write_text('{broken', encoding='utf-8')
        service = AlertService(self.store, now=NOW)
        self.assertEqual((), service.rules)
        self.assertEqual('alert.rules_corrupt', service.warning)
        self.assertEqual('{broken', next(self.store.directory.glob('alert_rules.json.bad-*')).read_text(encoding='utf-8'))
        self.store.events_path.write_text('{broken', encoding='utf-8')
        self.assertEqual((), self.store.load_events(NOW))
        self.assertEqual(1, len(tuple(self.store.directory.glob('alert_events.jsonl.bad-*'))))

    def test_recent_500_events_memory_and_thirty_day_disk_retention(self):
        old = AlertEvent('old', 'r', AlertKind.VOLUME_BURST, ID, NOW - timedelta(days=31), None, 'alert.event.volume_burst')
        self.store.append_event(old)
        for index in range(505):
            self.store.append_event(replace(old, event_id=str(index), occurred_at=NOW))
        service = AlertService(self.store, now=NOW)
        self.assertEqual(500, len(service.events))
        self.assertEqual('5', service.events[0].event_id)
        lines = self.store.events_path.read_text(encoding='utf-8').splitlines()
        self.assertEqual(505, len(lines))
        self.assertFalse(any(json.loads(line)['event_id'] == 'old' for line in lines))

    def test_scanner_boundary_rejects_invalid_data_and_gap_without_raw_messages(self):
        facade = FakeFacade()
        stream = ShioajiScannerStream(facade, fake_sdk())
        stream.set_kinds(frozenset((AlertKind.VOLUME_BURST,)))
        with self.assertLogs('quantlab.trading.adapters.shioaji.scanner_stream', level='ERROR') as logs:
            facade.callback(NS(scanner=NS(id='burst'), exchange='TSE', quote=NS(code='2330', close='private-secret', datetime=NOW)))
        self.assertNotIn('private-secret', ''.join(logs.output))
        self.assertEqual((), stream.drain())
        facade.callback(NS(dropped_count=2))
        self.assertEqual('alert.scanner_gap', stream.warning)
        stream.close()
        self.assertFalse(stream.kinds)

    def test_partial_subscription_failure_is_sanitized_and_unsubscribed(self):
        facade = FakeFacade()
        original = facade.subscribe_scanner

        def fail_second(scanner, **kwargs):
            if kwargs['exchange'] == 'OTC':
                raise RuntimeError('vendor-secret')
            original(scanner, **kwargs)

        facade.subscribe_scanner = fail_second
        stream = ShioajiScannerStream(facade, fake_sdk())
        with self.assertRaises(DomainError) as caught:
            stream.set_kinds(frozenset((AlertKind.VOLUME_BURST,)))
        self.assertNotIn('vendor-secret', str(caught.exception))
        stream.close()
        self.assertEqual(['subscribe', 'unsubscribe'], [call[0] for call in facade.calls])

    def test_hundred_rule_bound_and_duplicates_preserve_saved_rules(self):
        rules = tuple(AlertRule(str(index), AlertKind.VOLUME_BURST, scope='MARKET') for index in range(100))
        self.store.save_rules(rules)
        service = AlertService(self.store, now=NOW)
        original = self.store.rules_path.read_bytes()
        with self.assertRaises(DomainError):
            service.add_rule(replace(rules[0], rule_id='extra'))
        self.assertEqual(original, self.store.rules_path.read_bytes())
        service.delete_rule('99')
        with self.assertRaises(DomainError):
            service.add_rule(rules[0])

    def test_failed_atomic_publication_keeps_original_file_and_memory(self):
        service = AlertService(self.store, now=NOW)
        rule = AlertRule('r', AlertKind.VOLUME_BURST, scope='MARKET')
        service.add_rule(rule)
        original = self.store.rules_path.read_bytes()
        with patch('pathlib.Path.replace', side_effect=OSError('test-disk-failure')):
            with self.assertRaises(DomainError) as caught:
                service.add_rule(replace(rule, rule_id='r2'))
        self.assertNotIn('test-disk-failure', str(caught.exception))
        self.assertEqual(original, self.store.rules_path.read_bytes())
        self.assertEqual((rule,), service.rules)


if __name__ == '__main__':
    unittest.main()
