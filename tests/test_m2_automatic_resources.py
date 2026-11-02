"""Actual SDK near/next metadata and typed-only automatic session projections."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.adapters.shioaji.account_discovery import discover_accounts
from quantlab.trading.adapters.shioaji.stock_grid import StockGridEvidence
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment, QuantityUnit
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.live_market import CalendarResolver
from quantlab.trading.runtime.sinopac_resources import _future_binding, generated_resources

D = Decimal
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


class AutomaticResourcesTests(unittest.TestCase):
    def setUp(self):
        self.near = self.contract('TMFK6', '202611', date(2026, 11, 18), 27000, 33000)
        self.next = self.contract('TMFL6', '202612', date(2026, 12, 16), 28000, 34000)
        self.metadata = {row.code: row for row in (self.near, self.next)}
        self.rows = [self.next, self.near]  # SDK enumeration need not be chronological.
        self.facade = SimpleNamespace(
            execution_contracts=Mock(side_effect=lambda kind: tuple(self.rows)),
            contracts=SimpleNamespace(get=Mock(side_effect=lambda code: self.metadata[code]), info=Mock(side_effect=lambda row: self.metadata[row.code])),
        )
        raw = SimpleNamespace(account_type='F', broker_id='F002000', account_id='1234567', signed=True)
        accounts = discover_accounts([raw], Environment.BROKER_SIMULATION, alias_key=b'fake-account-alias-key-for-tests!')
        self.owner = SimpleNamespace(
            accounts=accounts,
            configuration=SinopacConnectionSettings(),
            shared=SimpleNamespace(facade=self.facade),
            clock=SimpleNamespace(now=lambda: NOW),
            query_ready=True,
        )
        self.reference = accounts[0].alias

    @staticmethod
    def contract(code, month, expiry, lower=27000, upper=33000, **changes):
        values = dict(
            code=code,
            security_type='FUT',
            exchange='TAIFEX',
            region='TW',
            target_code=None,
            root='TMF',
            delivery_month=month,
            delivery_date=expiry,
            multiplier=10,
            tick_basis='fixed',
            tick_rule=None,
            tick=1,
            limit_up=upper,
            limit_down=lower,
        )
        values.update(changes)
        return SimpleNamespace(**values)

    def resources(self, **kwargs):
        return generated_resources(self.owner, self.reference, **kwargs)

    def assert_unresolved(self, **kwargs):
        with self.assertRaises(DomainError) as caught:
            self.resources(**kwargs)
        self.assertEqual(caught.exception.code, 'instrument_unresolved')

    def resolver(self, *, book=True, typed=True):
        resources = self.resources(include_next=True)
        state = SimpleNamespace(manual_books=(object(),) if book else (), strategies=(SimpleNamespace(parameters=object() if typed else None),))
        return CalendarResolver(SimpleNamespace(calendar=resources.calendar, catalog=resources.catalog, state=state))

    def test_default_manual_catalog_contains_near_only(self):
        result = self.resources()
        self.assertEqual(tuple(row.instrument_id for row in result.catalog.instruments), ('TMF:202611',))
        self.assertEqual(tuple(row.sdk_code for row in result.bindings), ('TMFK6',))
        self.assertEqual(len(result.limits), 1)

    def test_explicit_false_does_not_require_next_metadata(self):
        self.rows = [self.near]
        result = self.resources(include_next=False)
        self.assertEqual(len(result.bindings), 1)
        self.assertEqual(result.bindings[0].sdk_code, self.near.code)

    def test_include_next_contains_exact_actual_near_and_next_with_separate_limits(self):
        result = self.resources(include_next=True)
        self.assertEqual(tuple(row.sdk_code for row in result.bindings), ('TMFK6', 'TMFL6'))
        specs = result.catalog.instruments
        self.assertEqual(tuple(row.instrument_id for row in specs), ('TMF:202611', 'TMF:202612'))
        self.assertEqual(tuple(row.expiry for row in specs), (date(2026, 11, 18), date(2026, 12, 16)))
        self.assertTrue(all(row.unit is QuantityUnit.CONTRACT and row.multiplier == 10 and row.tick_size == 1 for row in specs))
        self.assertEqual(
            tuple((row.instrument_id, row.lower, row.upper, row.observed_at) for row in result.limits),
            (('TMF:202611', D('27000'), D('33000'), NOW), ('TMF:202612', D('28000'), D('34000'), NOW)),
        )
        self.assertEqual(len(result.accounts), 1)
        self.assertEqual(len(result.capabilities), 1)
        self.assertFalse(result.capabilities[0].can_trade)
        self.assertFalse(hasattr(result, 'cash'))

    def test_next_is_selected_from_sdk_metadata_not_month_arithmetic(self):
        actual_next = self.contract('TMFF7', '202701', date(2027, 1, 20), 29000, 35000)
        self.metadata[actual_next.code] = actual_next
        self.rows = [actual_next, self.near]
        result = self.resources(include_next=True)
        self.assertEqual(tuple(row.instrument_id for row in result.catalog.instruments), ('TMF:202611', 'TMF:202701'))
        self.assertEqual(result.bindings[1].sdk_code, 'TMFF7')
        self.assertEqual(result.catalog.instruments[1].expiry, actual_next.delivery_date)

    def test_missing_next_fails_closed_without_inventing_contract(self):
        self.rows = [self.near]
        self.assert_unresolved(include_next=True)
        self.facade.contracts.get.assert_not_called()

    def test_empty_actual_catalog_fails_closed(self):
        self.rows = []
        self.assert_unresolved(include_next=True)

    def test_future_offset_default_is_near_and_offset_one_is_next(self):
        near, _ = _future_binding(self.facade, NOW)
        later, _ = _future_binding(self.facade, NOW, 1)
        self.assertEqual((near.sdk_code, later.sdk_code), ('TMFK6', 'TMFL6'))
        with self.assertRaises(DomainError):
            _future_binding(self.facade, NOW, 2)

    def test_near_sort_uses_expiry_before_sdk_code_and_enumeration_order(self):
        self.near.code = 'TMFZ6'
        self.next.code = 'TMFA6'
        self.metadata = {row.code: row for row in (self.near, self.next)}
        self.assertEqual(tuple(row.sdk_code for row in self.resources(include_next=True).bindings), ('TMFZ6', 'TMFA6'))

    def test_near_equal_expiry_has_deterministic_code_tiebreak(self):
        second = self.contract('TMFK6Z', '202611', self.near.delivery_date)
        self.metadata[second.code] = second
        self.rows = [second, self.near]
        self.assertEqual(self.resources().bindings[0].sdk_code, 'TMFK6')

    def test_wrong_root_cannot_supply_the_required_next_contract(self):
        self.next.root = 'MXF'
        self.assert_unresolved(include_next=True)

    def test_non_tmf_code_cannot_supply_required_next_even_if_root_claims_tmf(self):
        self.next.code = 'MXFL6'
        self.metadata = {row.code: row for row in (self.near, self.next)}
        self.assert_unresolved(include_next=True)

    def test_continuous_aliases_cannot_supply_actual_next(self):
        for suffix in ('R1', 'R2'):
            self.next.code = 'TMF' + suffix
            self.metadata = {row.code: row for row in (self.near, self.next)}
            self.facade.contracts.info.reset_mock()
            with self.subTest(suffix=suffix):
                self.assert_unresolved(include_next=True)
                self.assertFalse(any(call.args[0].code == self.next.code for call in self.facade.contracts.info.call_args_list))

    def test_expired_contract_cannot_count_toward_actual_pair(self):
        self.near.delivery_date = date(2026, 10, 21)
        self.near.delivery_month = '202610'
        self.assert_unresolved(include_next=True)
        self.assertEqual(self.resources().bindings[0].sdk_code, 'TMFL6')

    def test_expiry_filter_uses_taipei_date_not_utc_date(self):
        self.owner.clock.now = lambda: datetime(2026, 11, 18, 16, 1, tzinfo=timezone.utc)
        self.assert_unresolved(include_next=True)

    def test_expiry_day_contract_remains_actual_metadata_for_settlement_guard(self):
        self.owner.clock.now = lambda: datetime(2026, 11, 18, 1, tzinfo=timezone.utc)
        self.assertEqual(tuple(row.sdk_code for row in self.resources(include_next=True).bindings), ('TMFK6', 'TMFL6'))

    def test_wrong_exchange_next_is_rejected(self):
        self.next.exchange = 'FOREIGN'
        self.assert_unresolved(include_next=True)

    def test_wrong_multiplier_next_is_rejected(self):
        self.next.multiplier = 50
        self.assert_unresolved(include_next=True)

    def test_month_must_agree_with_actual_expiry(self):
        self.next.delivery_month = '202701'
        self.assert_unresolved(include_next=True)

    def test_missing_next_limits_do_not_copy_near_limits(self):
        self.next.limit_up = None
        result = self.resources(include_next=True)
        self.assertEqual(tuple(row.instrument_id for row in result.limits), ('TMF:202611',))
        self.assertEqual(len(result.catalog.instruments), 2)

    def test_invalid_next_limits_do_not_authorize_that_contract(self):
        self.next.limit_down = 35000
        self.assertEqual(tuple(row.instrument_id for row in self.resources(include_next=True).limits), ('TMF:202611',))

    def test_include_next_does_not_change_stock_catalog_or_query_future_contracts(self):
        stock = SimpleNamespace(code='2330', exchange='TSE', currency='TWD', trading_suspended=False, unit=1000, limit_down=90, limit_up=110)
        self.metadata['2330'] = stock
        raw = SimpleNamespace(account_type='S', broker_id='F002000', account_id='1234567', signed=True)
        self.owner.accounts = discover_accounts([raw], Environment.BROKER_SIMULATION, alias_key=b'fake-account-alias-key-for-tests!')
        self.reference = self.owner.accounts[0].alias
        self.facade.execution_contracts.side_effect = AssertionError('stock request cannot expand to futures')
        evidence = StockGridEvidence(
            '2330', 'TSE', 'COMMON_STOCK', 'TW0002330008', 'ESVUFR', 'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2', '2026-11-01', 'a' * 64, NOW
        )
        with patch('quantlab.trading.runtime.sinopac_resources.load_classification', return_value=evidence):
            result = self.resources(include_next=True)
        self.assertEqual(tuple(row.instrument_id for row in result.catalog.instruments), ('TWSE:2330',))
        self.assertEqual(tuple(row.sdk_code for row in result.bindings), ('2330',))
        self.facade.execution_contracts.assert_not_called()

    def test_typed_confirmed_context_uses_actual_future_session_at_1335(self):
        stamp = datetime(2026, 11, 2, 5, 35, tzinfo=timezone.utc)
        self.assertEqual(self.resolver().session_at('TMF:202611', stamp), (date(2026, 11, 2), 'DAY'))

    def test_manual_only_context_keeps_original_common_window(self):
        stamp = datetime(2026, 11, 2, 5, 35, tzinfo=timezone.utc)
        with self.assertRaises(DomainError):
            self.resolver(typed=False).session_at('TMF:202611', stamp)

    def test_typed_context_without_confirmed_book_keeps_common_window(self):
        stamp = datetime(2026, 11, 2, 5, 35, tzinfo=timezone.utc)
        with self.assertRaises(DomainError):
            self.resolver(book=False).session_at('TMF:202611', stamp)

    def test_typed_future_opens_0845_while_manual_stays_at_0900(self):
        stamp = datetime(2026, 11, 2, 0, 50, tzinfo=timezone.utc)
        self.assertEqual(self.resolver().session_at('TMF:202611', stamp), (date(2026, 11, 2), 'DAY'))
        with self.assertRaises(DomainError):
            self.resolver(typed=False).session_at('TMF:202611', stamp)

    def test_future_projection_preserves_actual_expiry_early_close(self):
        stamp = datetime(2026, 11, 18, 5, 35, tzinfo=timezone.utc)
        with self.assertRaises(DomainError):
            self.resolver().session_at('TMF:202611', stamp)
        self.assertEqual(self.resolver().session_at('TMF:202612', stamp), (date(2026, 11, 18), 'DAY'))

    def test_future_projection_cannot_extend_beyond_actual_close_or_verified_days(self):
        resolver = self.resolver()
        for stamp in (datetime(2026, 11, 2, 5, 45, 1, tzinfo=timezone.utc), datetime(2027, 1, 4, 1, tzinfo=timezone.utc)):
            with self.subTest(stamp=stamp), self.assertRaises(DomainError):
                resolver.session_at('TMF:202611', stamp)
