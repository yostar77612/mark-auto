"""Generated resource provenance and exact common-window coverage, no SDK."""

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.account_discovery import discover_accounts
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment, QuantityUnit
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.sinopac_calendar import built_in_calendar, DATES_SHA256
from quantlab.trading.runtime.sinopac_resources import generated_resources


class GeneratedResourcesTests(unittest.TestCase):
    def test_calendar_is_exact_242_dates_and_half_open_shared_window(self):
        calendar = built_in_calendar()
        self.assertEqual(len(calendar.days), 242)
        self.assertEqual(sha256(('\n'.join(day.isoformat() for day in calendar.days) + '\n').encode()).hexdigest(), DATES_SHA256)
        self.assertNotIn(date(2026, 7, 10), calendar.days)
        self.assertNotIn(date(2026, 2, 13), calendar.days)
        self.assertIn(date(2026, 2, 23), calendar.days)
        self.assertEqual(calendar.session_at(datetime(2026, 11, 2, 1, tzinfo=timezone.utc)).kind, 'DAY')
        for stamp in (datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc), datetime(2027, 1, 4, 1, tzinfo=timezone.utc)):
            with self.assertRaises(DomainError):
                calendar.session_at(stamp)

    def test_actual_tmf_month_limits_and_exchange_margin_not_broker_funds(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        raw_account = SimpleNamespace(account_type='F', broker_id='F002000', account_id='1234567', signed=True)
        accounts = discover_accounts([raw_account], Environment.BROKER_SIMULATION, alias_key=b'fake-account-alias-key-for-tests!')
        actual = SimpleNamespace(code='TMFK6', security_type='FUT', exchange='TAIFEX', region='TW', target_code=None)
        info = SimpleNamespace(
            **vars(actual),
            root='TMF',
            delivery_month='202611',
            delivery_date=date(2026, 11, 18),
            multiplier=10,
            tick_basis='fixed',
            tick_rule=None,
            tick=1,
            limit_up=33000,
            limit_down=27000,
        )
        facade = SimpleNamespace(execution_contracts=lambda kind: [actual], contracts=SimpleNamespace(get=lambda code: actual, info=lambda item: info))
        owner = SimpleNamespace(
            accounts=accounts,
            configuration=SinopacConnectionSettings(),
            shared=SimpleNamespace(facade=facade),
            clock=SimpleNamespace(now=lambda: now),
            query_ready=True,
        )
        resources = generated_resources(owner, accounts[0].alias)
        spec = resources.catalog.instruments[0]
        self.assertEqual(spec.delivery_month, '202611')
        self.assertEqual(spec.unit, QuantityUnit.CONTRACT)
        self.assertEqual(spec.multiplier, Decimal('10'))
        self.assertEqual(spec.margin, Decimal('35050'))
        self.assertIn('exchange', resources.margin_source)
        self.assertEqual(resources.limits[0].upper, Decimal('33000'))
        self.assertEqual(resources.limits[0].observed_at, now)
        self.assertFalse(resources.capabilities[0].can_trade)
        self.assertFalse(hasattr(resources, 'cash'))
        info.limit_up = None
        missing = generated_resources(owner, accounts[0].alias)
        self.assertEqual(missing.limits, ())


if __name__ == '__main__':
    unittest.main()
