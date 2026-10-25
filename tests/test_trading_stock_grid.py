"""Cash-stock price authority; public-record fixtures never claim broker proof."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest

import test_trading_adapters as fixtures
from quantlab.trading.adapters.shioaji import InstrumentBinding, ShioajiAdapter, SDK_VERSION
from quantlab.trading.adapters.shioaji.stock_grid import (
    COMMON_STOCK_BANDS,
    COMMON_STOCK_RULE,
    StockGridEvidence,
    TWD_ETF_BANDS,
    TWD_ETF_RULE,
    validate_stock_grid,
)
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, Quote
from quantlab.trading.domain.risk import RiskPolicy, RiskService
from quantlab.trading.domain.validation import DomainError

D = Decimal


def evidence(*, etf=False, **changes):
    value = StockGridEvidence(
        '0050' if etf else '2330',
        'TSE',
        'TWD_ETF' if etf else 'COMMON_STOCK',
        'TW0000050004' if etf else 'TW0002330008',
        'CEOGEU' if etf else 'ESVUFR',
        'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2',
        '2026-10-23',
        'a' * 64,
        fixtures.NOW,
    )
    return replace(value, **changes)


def instrument(*, etf=False):
    return replace(
        fixtures.instrument(),
        instrument_id='TWSE:0050' if etf else 'TWSE:2330',
        underlying='0050' if etf else '2330',
        price_bands=TWD_ETF_BANDS if etf else COMMON_STOCK_BANDS,
        tick_rule_id=TWD_ETF_RULE if etf else COMMON_STOCK_RULE,
    )


class CashStockGridTests(unittest.TestCase):
    def adapter(self, *, etf=False, spec=None, proof=None):
        item = instrument(etf=etf) if spec is None else spec
        record = evidence(etf=etf) if proof is None else proof
        client = fixtures.SDKDouble()
        client.synthetic_contract = SimpleNamespace(code=record.sdk_code, exchange='TSE', security_type='STK', region='TW')
        client.contracts.tick_bands = lambda info: self.fail('StockInfo has no documented tick_bands route')
        adapter = ShioajiAdapter(
            client,
            fixtures.MutableClock(),
            Environment.BROKER_SIMULATION,
            {'test-stock': client.account},
            (InstrumentBinding(item, record.sdk_code, record),),
            (fixtures.capability(Environment.BROKER_SIMULATION),),
            {'test-stock': D('100000')},
            sdk_version=SDK_VERSION,
        )
        return adapter, item, client

    def test_common_stock_exact_primary_grid_covers_all_thresholds(self):
        adapter, item, _ = self.adapter()
        self.assertEqual(adapter.resolve(item.instrument_id), item)
        for price, tick in (('9.99', '.01'), ('10', '.05'), ('50', '.1'), ('100', '.5'), ('500', '1'), ('1000', '5')):
            self.assertEqual(item.tick_for(D(price)), D(tick))
        self.assertEqual(item.shift_ticks(D('999'), 2), D('1005'))
        self.assertEqual(item.shift_ticks(D('1000'), -1), D('999'))
        with self.assertRaises(DomainError):
            item.validate_price(D('1001'))

    def test_supported_plain_twd_etf_uses_distinct_grid_without_sdk_tick_invention(self):
        adapter, item, _ = self.adapter(etf=True)
        self.assertEqual(adapter.resolve(item.instrument_id), item)
        self.assertEqual(item.tick_for(D('10')), D('.01'))
        self.assertEqual(item.tick_for(D('1000')), D('.05'))
        item.validate_price(D('1000.05'))

    def test_stock_scalar_without_explicit_exchange_grid_is_rejected(self):
        adapter, item, _ = self.adapter(spec=replace(instrument(), price_bands=(), tick_rule_id='fixed-demo-v1'))
        with self.assertRaises(DomainError):
            adapter.resolve(item.instrument_id)

    def test_unknown_stock_grid_stops_before_sdk_order_construction_or_submission(self):
        adapter, item, client = self.adapter(spec=replace(instrument(), price_bands=(), tick_rule_id='fixed-demo-v1'))
        adapter.read_only, adapter.execution_enabled = False, True
        adapter.attach_authenticated()
        request = fixtures.plan(item, environment=Environment.BROKER_SIMULATION)
        with self.assertRaises(DomainError) as refused:
            adapter.submit(request, 'unknown-stock-grid')
        self.assertEqual(refused.exception.code, 'instrument_unresolved')
        self.assertEqual(client.order_calls, [])
        self.assertEqual(client.placed, [])
        binding = adapter.bindings[item.instrument_id]
        adapter.bindings[item.instrument_id] = replace(binding, stock_grid=None)
        with self.assertRaises(DomainError):
            adapter.resolve(item.instrument_id)

    def test_product_class_cfi_grid_and_rule_must_agree(self):
        for changes in (
            {'product_class': 'UNKNOWN'},
            {'cfi_code': 'CEOGEU'},
            {'source_uri': 'https://untrusted.invalid/record'},
            {'exchange': 'OTC'},
            {'source_version': '2026/10/23'},
            {'source_sha256': 'missing'},
            {'as_of': fixtures.NOW.replace(tzinfo=None)},
        ):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                evidence(**changes)
        for spec in (replace(instrument(), tick_rule_id=TWD_ETF_RULE), replace(instrument(), price_bands=TWD_ETF_BANDS)):
            adapter, item, _ = self.adapter(spec=spec)
            with self.assertRaises(DomainError):
                adapter.resolve(item.instrument_id)

    def test_code_market_currency_and_suspension_mismatch_fail_closed(self):
        adapter, item, client = self.adapter()
        for changes in ({'exchange': 'OTC'}, {'code': '2317'}):
            original = client.synthetic_contract
            client.synthetic_contract = SimpleNamespace(**{**vars(original), **changes})
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                adapter.resolve(item.instrument_id)
            client.synthetic_contract = original
        for info in (
            SimpleNamespace(unit=1000, trading_suspended=False, currency='USD'),
            SimpleNamespace(unit=1000, trading_suspended=False),
            SimpleNamespace(unit=1000, trading_suspended=None, currency='TWD'),
        ):
            client.contracts.info = lambda contract, info=info: info
            with self.subTest(info=info), self.assertRaises(DomainError):
                adapter.resolve(item.instrument_id)

    def test_dated_source_record_and_receipt_both_must_be_fresh_not_future(self):
        for proof in (
            evidence(as_of=fixtures.NOW + timedelta(seconds=1)),
            evidence(as_of=fixtures.NOW - timedelta(days=8)),
            evidence(source_version='2020-01-01'),
            evidence(source_version='2026-10-24'),
        ):
            with self.subTest(proof=proof), self.assertRaises(DomainError):
                validate_stock_grid(instrument(), '2330', 'TSE', proof, fixtures.NOW)

    def test_stock_risk_includes_actual_high_price_band_slippage_instead_of_scalar(self):
        item = instrument()
        fees = FeeSchedule('zero-fees-explicit-grid-test', D('0'), D('0'), D('0'), D('0'), D('0'), D('0'), 1)
        request = replace(fixtures.plan(item, quantity=100), limit_price=D('1000'), stop_price=D('999'))
        quote = Quote(item.instrument_id, D('999'), D('1000'), D('1000'), fixtures.NOW, fixtures.NOW, fixtures.NOW.date())
        cap = replace(fixtures.capability(), odd_lot=True)
        decision = RiskService(RiskPolicy(), fees).preview(request, item, quote, fixtures.account(), cap, now=fixtures.NOW)
        self.assertTrue(decision.allowed)
        self.assertEqual((decision.quantity, decision.cash_required, decision.risk_required), (99, D('99990'), D('693')))
        self.assertGreater(decision.risk_required, D('100.98'))


if __name__ == '__main__':
    unittest.main()
