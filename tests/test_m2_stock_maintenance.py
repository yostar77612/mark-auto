"""Offline cost identity, date reminders and fail-closed coverage acceptance."""

from dataclasses import fields
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from quantlab.trading.application.codec import dumps, register
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.maintenance import ExpiryCoverage, key_expiry_status, maintenance_check
from quantlab.trading.domain.models import Side, Market
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.stock_maintenance import StockMaintenanceStore, StockMaintenanceSettings
from test_trading_domain import instrument
import test_sinopac_connection as connection_tests


def calendar(start=date(2026, 11, 1), count=80):
    # Explicit synthetic session list; no holiday inference is performed by product.
    return TradingCalendar(
        'test-maintenance',
        'fixture-v1',
        'synthetic-test-calendar',
        tuple(
            TradingSession(
                start + timedelta(days=i),
                datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc),
                datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc) + timedelta(hours=6),
            )
            for i in range(count)
        ),
    )


class CostVersionTests(unittest.TestCase):
    def test_legacy_schedule_fields_and_exact_wire_are_unchanged(self):
        register(FeeSchedule)
        fees = FeeSchedule()
        self.assertEqual(
            tuple(f.name for f in fields(fees)),
            ('version', 'buy_rate', 'sell_rate', 'sell_tax_rate', 'minimum_fee', 'futures_fee_per_contract', 'futures_tax_rate', 'slippage_ticks'),
        )
        self.assertEqual(
            dumps(fees),
            '{"@":"quantlab.trading.domain.costs.FeeSchedule","fields":{"buy_rate":{"@":"decimal","value":"0.001425"},"futures_fee_per_contract":{"@":"decimal","value":"30"},"futures_tax_rate":{"@":"decimal","value":"0.00002"},"minimum_fee":{"@":"decimal","value":"20"},"sell_rate":{"@":"decimal","value":"0.001425"},"sell_tax_rate":{"@":"decimal","value":"0.003"},"slippage_ticks":1,"version":"local-demo-cost-v1"}}',
        )

    def test_discount_minimum_stock_daytrade_etf_and_tmf(self):
        stock = instrument()
        ordinary = FeeSchedule.taiwan(discount=D('0.5'), minimum_fee=D('20'))
        self.assertEqual(ordinary.transaction(stock, Side.BUY, D('100'), 1000), D('72'))
        self.assertEqual(ordinary.transaction(stock, Side.SELL, D('100'), 1000), D('372'))
        self.assertEqual(ordinary.transaction(stock, Side.BUY, D('10'), 1), D('20'))
        intraday = FeeSchedule.taiwan(discount=D('0.5'), day_trade=True)
        etf = FeeSchedule.taiwan(discount=D('0.5'), stock_kind='ETF', day_trade=True)
        self.assertEqual(intraday.transaction(stock, Side.SELL, D('100'), 1000), D('222'))
        self.assertEqual(etf.transaction(stock, Side.SELL, D('100'), 1000), D('172'))
        tmf = instrument(Market.INDEX_FUTURE)
        fees = FeeSchedule.taiwan(futures_fee_per_contract=D('25'))
        self.assertEqual(fees.transaction(tmf, Side.BUY, D('20000'), 1), D('29'))
        self.assertEqual(fees.transaction(tmf, Side.SELL, D('20000'), 1), D('29'))

    def test_cost_version_changes_for_every_effective_setting_and_history_is_not_rewritten(self):
        base = FeeSchedule.taiwan()
        for change in (
            {'discount': D('.5')},
            {'minimum_fee': D('1')},
            {'futures_fee_per_contract': D('42')},
            {'slippage_ticks': 2},
            {'day_trade': True},
            {'stock_kind': 'ETF'},
        ):
            self.assertNotEqual(base.version, FeeSchedule.taiwan(**change).version)
        with tempfile.TemporaryDirectory() as root:
            store = StockMaintenanceStore(Path(root))
            first = store.save(StockMaintenanceSettings())
            old = store.store.load()['cost_versions_v1'][first.version]
            second = store.save(StockMaintenanceSettings(discount=D('.5')))
            self.assertNotEqual(first.version, second.version)
            self.assertEqual(store.store.load()['cost_versions_v1'][first.version], old)
            self.assertEqual(store.load().fees(), second)


class MaintenanceRulesTests(unittest.TestCase):
    def test_unknown_and_fourteen_day_boundary_and_no_fabricated_grace_period(self):
        today = date(2026, 11, 1)
        self.assertIsNone(key_expiry_status(None, today).remaining_days)
        self.assertEqual(key_expiry_status(None, today).state, 'UNKNOWN')
        for days, state in ((15, 'VALID'), (14, 'DUE'), (1, 'DUE'), (0, 'EXPIRED'), (-1, 'EXPIRED')):
            status = key_expiry_status(today + timedelta(days=days), today)
            self.assertEqual((status.remaining_days, status.state), (days, state))

    def test_calendar_requires_thirty_future_days_and_expiry_months(self):
        today = date(2026, 11, 1)
        expiry = ExpiryCoverage('fixture-expiries-v1', (('202611', date(2026, 11, 18)), ('202612', date(2026, 12, 16))))
        good = maintenance_check(calendar(), today, expires_on=date(2027, 1, 1), expiries=expiry)
        self.assertTrue(good.can_open_new)
        self.assertEqual(good.future_trading_days, 30)
        good.require_automatic_entry()
        for kwargs, expected in (
            ({'calendar': calendar(count=30)}, 'calendar_coverage_missing'),
            ({'expiries': None}, 'expiry_coverage_missing'),
            ({'expires_on': None}, 'api_key_expiry_unknown'),
        ):
            values = dict(calendar=calendar(), today=today, expires_on=date(2027, 1, 1), expiries=expiry)
            bad = maintenance_check(**(values | kwargs))
            self.assertIn(expected, bad.issues)
            with self.assertRaises(DomainError):
                bad.require_automatic_entry()

    def test_december_reminder_and_stock_does_not_require_futures_data(self):
        status = maintenance_check(calendar(date(2026, 12, 1)), date(2026, 12, 1), expires_on=date(2027, 3, 1), expiries=None, futures_required=False)
        self.assertTrue(status.can_open_new)
        self.assertIn('calendar_annual_update_due', status.reminders)

    def test_corrupt_persisted_collections_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            store = StockMaintenanceStore(Path(root))
            for key in ('cost_versions_v1', 'key_expiry_dates_v1'):
                store.store.save({key: []})
                before = store.store.path.read_bytes()
                with self.assertRaises(DomainError):
                    if key == 'cost_versions_v1':
                        store.save(StockMaintenanceSettings())
                    else:
                        store.set_key_expiry('MarkAuto/v2/broker/test', date(2027, 1, 1))
                self.assertEqual(store.store.path.read_bytes(), before)

    def test_runtime_uses_versioned_expiry_file_and_never_infers_missing_months(self):
        import json
        from quantlab.taifex_expiries import load_expiries

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            store = StockMaintenanceStore(root)
            reference = 'MarkAuto/v2/broker/fixture'
            store.set_key_expiry(reference, date(2027, 1, 1))
            path = root / 'synthetic-expiries.json'
            data = load_expiries()
            data['data_version'] = 'synthetic-test-only'
            data['expiries'] = [
                dict(contract_month=month, expiry_date=day, status='verified', source_index=0)
                for month, day in (('202611', '2026-11-18'), ('202612', '2026-12-16'))
            ]
            # Test-generated dates in the existing schema; no recorded provenance claimed.
            data['sources'][0]['sha256'] = 'a' * 64
            data['sources'][0]['retrieval_method'] = 'synthetic test fixture'
            path.write_text(json.dumps(data), encoding='utf-8')
            good = store.pre_open(calendar(), date(2026, 11, 1), reference, expiries_path=path)
            self.assertTrue(good.can_open_new)
            self.assertEqual(good.expiry_version, 'synthetic-test-only')
            data['expiries'].pop()
            path.write_text(json.dumps(data), encoding='utf-8')
            bad = store.pre_open(calendar(), date(2026, 11, 1), reference, expiries_path=path)
            self.assertIn('expiry_coverage_missing', bad.issues)
            with self.assertRaises(DomainError):
                bad.require_automatic_entry()
            path.write_text('invalid', encoding='utf-8')
            corrupt = store.pre_open(calendar(), date(2026, 11, 1), reference, expiries_path=path)
            self.assertFalse(corrupt.can_open_new)
            self.assertIsNone(corrupt.expiry_version)

    def test_persisted_date_scoped_by_reference_and_bad_date_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            store = StockMaintenanceStore(Path(root))
            self.assertIsNone(store.key_expiry('MarkAuto/v2/broker/a'))
            store.set_key_expiry('MarkAuto/v2/broker/a', date(2027, 1, 1))
            self.assertEqual(StockMaintenanceStore(Path(root)).key_expiry('MarkAuto/v2/broker/a'), date(2027, 1, 1))
            self.assertIsNone(store.key_expiry('MarkAuto/v2/broker/b'))
            body = store.store.load()
            body['key_expiry_dates_v1']['MarkAuto/v2/broker/a'] = 'invalid'
            store.store.save(body)
            before = store.store.path.read_bytes()
            with self.assertRaises(DomainError):
                store.key_expiry('MarkAuto/v2/broker/a')
            self.assertEqual(store.store.path.read_bytes(), before)


class ExpiryConnectionTests(unittest.TestCase):
    # Reuse only setup/command helpers, not another copy of the original suite.
    setUp = connection_tests.UnifiedConnectionTests.setUp
    command = connection_tests.UnifiedConnectionTests.command

    def test_expired_key_never_resolves_credentials_or_constructs_sdk(self):
        settings = SinopacConnectionSettings(api_key_expires_on=date(2026, 11, 1))
        receipt = self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=settings))
        self.assertTrue(receipt.accepted)
        self.owner.worker.join(2)
        view = self.owner.snapshot()
        self.assertEqual((view.phase, view.error_code, view.api_key_remaining_days), ('DISCONNECTED', 'api_key_expired', 0))
        self.assertEqual(self.creations, [])
        self.assertEqual(self.secrets.references, [])
        self.assertEqual(self.owner.maintenance.key_expiry(settings.key_ref), settings.api_key_expires_on)

    def test_valid_date_shows_days_without_secrets_in_view(self):
        settings = SinopacConnectionSettings(api_key_expires_on=date(2026, 11, 15))
        self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=settings))
        self.owner.worker.join(2)
        view = self.owner.snapshot()
        self.assertEqual((view.api_key_remaining_days, view.api_key_expiry_state), (14, 'DUE'))
        self.assertEqual(view.phase, 'CONNECTED')

    def test_pre_open_snapshot_carries_renewal_and_december_reminder(self):
        from quantlab.trading.application.codec import loads
        from quantlab.trading.application.registry import initialize

        initialize()
        self.clock.now = lambda: datetime(2026, 12, 1, tzinfo=timezone.utc)
        unknown = self.owner.snapshot()
        self.assertIsNone(unknown.pre_open.key.remaining_days)
        self.assertIn('api_key_expiry_unknown', unknown.pre_open.issues)
        self.assertEqual(self.creations, [])
        settings = SinopacConnectionSettings(api_key_expires_on=date(2026, 12, 15))
        self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=settings))
        self.owner.worker.join(2)
        view = self.owner.snapshot()
        self.assertEqual(view.pre_open.key.remaining_days, 14)
        self.assertIn('api_key_renewal_due', view.pre_open.reminders)
        self.assertIn('calendar_annual_update_due', view.pre_open.reminders)
        self.assertIn('calendar_coverage_missing', view.pre_open.issues)
        self.assertFalse(view.pre_open.can_open_new)
        self.assertEqual(loads(dumps(view)), view)
