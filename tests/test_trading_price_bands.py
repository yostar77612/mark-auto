"""Executable variable-price grids, conservative costs and pinned SDK band shapes."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace
import json
import unittest

import test_trading_adapters as fixtures
import test_trading_application as application_support
from test_trading_sdk_facade import StrictSDK, contract, Unit, QuoteType, QuoteVersion
from quantlab.trading.adapters.shioaji import InstrumentBinding, ShioajiAdapter, SDK_VERSION
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.simulated import SimulatedBroker
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.contracts import StrategyForm, UiAction
from quantlab.trading.application.coordinator import run_cycle
from quantlab.trading.application.workflows import fill_local_pending, step
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, OrderStatus, PriceBand, Quote, Side
from quantlab.trading.domain.risk import RiskPolicy, RiskService
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_history

D = Decimal
BANDS = (PriceBand(D('0'), D('50'), D('0.05')), PriceBand(D('50'), None, D('0.1')))


def spec_for(market=Market.STOCK_FUTURE):
    return replace(
        fixtures.instrument(market),
        tick_size=D('0.05'),
        tick_rule_id='explicit-two-band-test-v1',
        price_bands=BANDS,
        multiplier=D('1') if market is Market.STOCK else D('10'),
        margin=None if market is Market.STOCK else D('100'),
    )


def zero_fees(ticks=2):
    return FeeSchedule('band-cost-test-v1', D('0'), D('0'), D('0'), D('0'), D('0'), D('0'), ticks)


class PriceBandDomainTests(unittest.TestCase):
    def test_all_markets_share_half_open_grid_and_cross_boundary_rounding(self):
        for market in Market:
            item = spec_for(market)
            with self.subTest(market=market):
                self.assertEqual(item.tick_for(D('49.95')), D('0.05'))
                self.assertEqual(item.tick_for(D('50')), D('0.1'))
                self.assertEqual(item.round_price(D('49.99'), up=True), D('50'))
                self.assertEqual(item.round_price(D('49.99')), D('49.95'))
                self.assertEqual(item.round_price(D('50.04'), up=True), D('50.1'))
                with self.assertRaises(DomainError):
                    item.validate_price(D('50.05'))
                item.validate_price(D('50.1'))

    def test_tick_movement_uses_previous_band_below_exact_boundary(self):
        item = spec_for()
        self.assertEqual(item.shift_ticks(D('49.95'), 2), D('50.1'))
        self.assertEqual(item.shift_ticks(D('50'), -1), D('49.95'))
        self.assertEqual(item.shift_ticks(D('50.1'), -3), D('49.9'))
        self.assertEqual(item.shift_ticks(D('49.95'), 10), D('50.9'))
        self.assertEqual(item.shift_ticks(D('49.95'), 1000000), D('100049.9'))
        for value in (True, D('1'), 1.5, '1'):
            with self.assertRaises(DomainError):
                item.shift_ticks(D('50'), value)
        with self.assertRaises(DomainError):
            item.shift_ticks(D('0.05'), -1)

    def test_complete_ordered_gapless_bounded_profiles_are_mandatory(self):
        invalid = (
            (PriceBand(D('1'), None, D('1')),),
            (PriceBand(D('0'), D('50'), D('0.05')),),
            (PriceBand(D('0'), D('40'), D('0.05')), PriceBand(D('50'), None, D('0.1'))),
            (PriceBand(D('0'), D('60'), D('0.05')), PriceBand(D('50'), None, D('0.1'))),
            (PriceBand(D('0'), None, D('0.05')), PriceBand(D('50'), None, D('0.1'))),
            BANDS[::-1],
            list(BANDS),
            tuple([BANDS[0]] * 65),
        )
        for bands in invalid:
            with self.subTest(bands=bands), self.assertRaises(DomainError):
                replace(spec_for(), price_bands=bands)
        with self.assertRaises(DomainError):
            replace(spec_for(), tick_size=D('0.01'))

    def test_band_numbers_are_finite_decimal_positive_and_grid_aligned(self):
        for lower, upper, tick in (
            (D('-1'), None, D('1')),
            (D('0'), D('0'), D('1')),
            (D('0'), None, D('0')),
            (D('0'), None, D('NaN')),
            (0.0, None, D('1')),
            (D('0'), D('10'), D('0.03')),
            (D('10.01'), None, D('0.1')),
        ):
            with self.subTest(lower=lower, upper=upper, tick=tick), self.assertRaises(DomainError):
                PriceBand(lower, upper, tick)

    def test_fixed_grid_and_legacy_fee_values_are_exactly_preserved(self):
        item = fixtures.instrument(Market.INDEX_FUTURE)
        fees = zero_fees()
        self.assertEqual(item.shift_ticks(D('100'), -10), D('90'))
        self.assertEqual(item.round_price(D('100.1'), up=True), D('101'))
        self.assertEqual(fees.slippage(item, 2), D('80'))
        self.assertEqual(fees.slippage(item, 2, prices=(D('100.25'), D('99.75'))), D('80'))
        self.assertEqual(fees.loss_at_stop(item, D('100'), D('90'), 2), D('280'))

    def test_slippage_crosses_bands_and_missing_price_uses_global_conservative_bound(self):
        item, fees = spec_for(), zero_fees()
        self.assertEqual(item.slippage_distance(D('49.95'), 2), D('0.15'))
        self.assertEqual(fees.slippage(item, 10, legs=1, prices=(D('49.95'),)), D('15'))
        self.assertEqual(fees.slippage(item, 10, legs=1), D('30'))
        self.assertEqual(fees.loss_at_stop(item, D('49.95'), D('49.9'), 10), D('30'))
        self.assertEqual(fees.entry_cash(item, D('49.95'), 10), D('1030'))
        with self.assertRaises(DomainError):
            fees.slippage(item, 1, prices=(D('50'),))

    def test_vwap_between_ticks_is_a_valid_cost_basis_and_not_rounded_inward(self):
        item, fees = spec_for(), zero_fees()
        self.assertEqual(item.slippage_distance(D('49.975'), 2), D('0.225'))
        self.assertEqual(fees.slippage(item, 10, legs=1, prices=(D('49.975'),)), D('22.5'))
        self.assertGreaterEqual(fees.slippage(item, 10, legs=1), fees.slippage(item, 10, legs=1, prices=(D('49.975'),)))
        self.assertEqual(item.slippage_distance(D('0.05'), 2), D('0.10'))
        self.assertEqual(item.slippage_distance(D('49.975'), 0), D('0'))

    def test_band_arithmetic_ignores_hostile_ambient_decimal_context(self):
        item = spec_for()
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(item.shift_ticks(D('49.95'), 2), D('50.1'))
            self.assertEqual(zero_fees().loss_at_stop(item, D('49.95'), D('49.9'), 10), D('30'))

    def test_typed_profile_codec_retains_bands_and_old_fixed_documents_use_default(self):
        initialize()
        item = spec_for()
        self.assertEqual(loads(dumps(item)), item)
        fixed = fixtures.instrument()
        previous = json.loads(dumps(fixed))
        del previous['fields']['price_bands']
        self.assertEqual(loads(json.dumps(previous)), fixed)

    def test_risk_resizes_for_cross_band_costs_and_rejects_invalid_stop_and_quote_grid(self):
        item, fees = spec_for(), zero_fees()
        request = replace(fixtures.plan(item, quantity=1000), limit_price=D('49.95'), stop_price=D('49.9'))
        quote = Quote(item.instrument_id, D('49.9'), D('49.95'), D('49.95'), fixtures.NOW, fixtures.NOW, fixtures.NOW.date())
        service = RiskService(RiskPolicy(), fees)
        decision = service.preview(request, item, quote, fixtures.account(), fixtures.capability(), now=fixtures.NOW, policy=HoldingPolicy())
        self.assertTrue(decision.allowed)
        self.assertEqual((decision.quantity, decision.risk_required), (666, D('1998')))
        for changed_request, changed_quote in (
            (replace(request, limit_price=D('50.1'), stop_price=D('50.05')), quote),
            (request, replace(quote, ask=D('50.05'))),
        ):
            result = service.preview(changed_request, item, changed_quote, fixtures.account(), fixtures.capability(), now=fixtures.NOW)
            self.assertFalse(result.allowed)
            self.assertEqual(result.code, 'validation_failed')

    def test_all_market_simulators_partial_vwap_restart_and_cross_band_exit_preserve_cash(self):
        for market in Market:
            with self.subTest(market=market):
                item, clock = spec_for(market), fixtures.MutableClock()
                broker = SimulatedBroker(clock, fixtures.account(), (item,), fixtures.capability(), fee_schedule=zero_fees())
                unit_quantity = 1000 if market is Market.STOCK else 1
                request = replace(fixtures.plan(item, quantity=2 * unit_quantity), limit_price=D('49.95'), stop_price=D('49.9'))
                broker.submit(request, 'band-entry')
                broker.fill('band-entry', unit_quantity, D('49.9'))
                with self.assertRaises(DomainError):
                    broker.fill('band-entry', unit_quantity, D('50.05'))
                self.assertEqual(broker.refresh('test-stock').orders[0].cumulative_quantity, unit_quantity)
                broker.fill('band-entry', unit_quantity, D('49.95'))
                self.assertEqual(broker.list('test-stock')[0].average_cost, D('49.925'))
                restarted = SimulatedBroker(clock, fixtures.account(), (item,), fixtures.capability(), broker.remote_state, fee_schedule=zero_fees())
                self.assertEqual(restarted.submission_count, 0)
                clock.value += timedelta(days=3)
                restarted.advance_trade_date(clock.now().date())
                exit_request = replace(
                    request,
                    plan_id='band-exit',
                    side=Side.SELL,
                    reduce_only=True,
                    limit_price=D('50.1'),
                    stop_price=D('50.1'),
                    decision_at=clock.now(),
                    deadline=clock.now() + timedelta(hours=1),
                )
                restarted.submit(exit_request, 'band-exit')
                restarted.fill('band-exit', 2 * unit_quantity, D('50.1'))
                snapshot = restarted.refresh('test-stock')
                self.assertEqual(snapshot.positions, ())
                self.assertEqual(snapshot.account.margin_used, D('0'))
                self.assertTrue(all(order.status is OrderStatus.FILLED for order in snapshot.orders))
                if market is Market.STOCK:
                    self.assertEqual(snapshot.account.settled_cash, D('150'))
                    self.assertEqual(snapshot.account.unsettled_receivables, D('100200'))
                else:
                    self.assertEqual(snapshot.account.settled_cash, D('100003.5'))

    def test_real_application_research_deploy_coordinator_holding_and_exit_use_band_authority(self):
        fixture = application_support.ApplicationLifecycleTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        engine = fixture.engine
        source = next(item for item in engine.catalog.instruments if item.market is Market.STOCK_FUTURE)
        item = replace(
            source,
            tick_size=D('0.05'),
            price_bands=BANDS,
            tick_rule_id='explicit-two-band-test-v1',
            multiplier=D('10'),
            margin=D('1000'),
            version='band-app-local-v1',
            source='LOCAL_SYNTHETIC_BAND_ACCEPTANCE',
        )
        engine.catalog = Catalog(tuple(item if existing.instrument_id == item.instrument_id else existing for existing in engine.catalog.instruments))
        engine.gateways['local-futures'].instruments[item.instrument_id] = item
        engine.history[item.instrument_id] = synthetic_history(Catalog((item,)), engine.calendar)[item.instrument_id]
        current = engine.quotes[item.instrument_id]
        engine.quote(replace(current, bid=D('50'), ask=D('50.1'), last=D('50.1'), sequence=engine.quote_count + 1))
        form = StrategyForm(
            'Band full application',
            Market.STOCK_FUTURE,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            item.instrument_id,
            'local-futures',
            Environment.LOCAL,
            D('30000'),
            D('0.02'),
            'BUY_AND_HOLD',
        )
        reference = fixture.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            fixture.command(action, target_id=reference)
        run_cycle(engine, engine.history)
        order = next(order for order in engine.state.orders if order.plan.instrument_id == item.instrument_id and not order.plan.reduce_only)
        self.assertEqual((order.plan.limit_price, order.plan.stop_price), (D('50.1'), D('49.55')))
        self.assertEqual(order.reservation.risk, engine.fees.loss_at_stop(item, D('50.1'), D('49.55'), 1))
        fill_local_pending(engine)
        lot = next(lot for lot in engine.state.positions if lot.quantity)
        for _ in range(3):
            step(engine, engine.history)
        current = engine.quotes[item.instrument_id]
        engine.quote(replace(current, bid=D('50.2'), ask=D('50.3'), last=D('50.2'), sequence=engine.quote_count + 1))
        exit_id = engine.exit_lot(lot.lot_id)
        self.assertIsNotNone(exit_id)
        fill_local_pending(engine)
        self.assertEqual(next(position for position in engine.state.positions if position.lot_id == lot.lot_id).quantity, 0)
        self.assertEqual(next(order for order in engine.state.orders if order.order_id == exit_id).status, OrderStatus.FILLED)
        self.assertEqual(engine.state.costs, engine.fees.transaction(item, Side.BUY, D('50.1'), 1) + engine.fees.transaction(item, Side.SELL, D('50.2'), 1))


class SDKPriceBandTests(unittest.TestCase):
    def bridge(self):
        vendor = StrictSDK()
        vendor._contracts.tick_bands = lambda info: [{'min': 0.0, 'max': 50.0, 'tick': 0.05}, {'min': 50.0, 'max': None, 'tick': 0.1}]
        return ShioajiSDKFacade(vendor, SimpleNamespace(__version__=SDK_VERSION, Unit=Unit, QuoteType=QuoteType, QuoteVersion=QuoteVersion)), vendor

    def adapter(self, *, bands=BANDS, basis='price', rule='explicit-two-band-test-v1'):
        item = spec_for()
        client = fixtures.SDKDouble()
        client.synthetic_contract = contract('FFFK6', futures=True)
        info = SimpleNamespace(
            delivery_month=item.delivery_month, delivery_date=item.expiry, multiplier=float(item.multiplier), tick=None, tick_basis=basis, tick_rule=rule
        )
        client.contracts = SimpleNamespace(get=lambda code: client.synthetic_contract, info=lambda base: info, tick_bands=lambda data: bands)
        adapter = ShioajiAdapter(
            client,
            fixtures.MutableClock(),
            Environment.BROKER_SIMULATION,
            {'test-stock': client.account},
            (InstrumentBinding(item, 'FFFK6'),),
            (fixtures.capability(Environment.BROKER_SIMULATION),),
            {'test-stock': D('100000')},
            sdk_version=SDK_VERSION,
        )
        return adapter, item, info

    def test_official_min_max_tick_table_normalizes_to_decimal_frozen_bands_without_timeout(self):
        bridge, vendor = self.bridge()
        self.assertEqual(bridge.contracts.tick_bands(contract('CDFL6', futures=True)), BANDS)
        for raw in (
            [],
            [{'min': 0, 'max': None, 'tick': 0}],
            [{'lower': 0, 'max': None, 'tick': 1}],
            [{'min': 0, 'max': 40, 'tick': 0.05}, {'min': 50, 'max': None, 'tick': 0.1}],
        ):
            vendor._contracts.tick_bands = lambda info, raw=raw: raw
            with self.subTest(raw=raw), self.assertRaises(DomainError):
                bridge.contracts.tick_bands(contract('CDFL6', futures=True))

    def test_gateway_accepts_exact_authoritative_bands_even_without_scalar_tick(self):
        adapter, item, info = self.adapter()
        self.assertIsNone(info.tick)
        self.assertEqual(adapter.resolve(item.instrument_id), item)

    def test_gateway_rejects_missing_basis_rule_mismatched_bands_and_unknown_rule(self):
        for kwargs in ({'basis': None}, {'rule': None}, {'rule': 'wrong-rule'}, {'basis': 'premium'}, {'bands': (PriceBand(D('0'), None, D('0.05')),)}):
            adapter, item, _ = self.adapter(**kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(DomainError):
                adapter.resolve(item.instrument_id)

    def test_fixed_future_requires_explicit_fixed_evidence_and_preserves_scalar_behavior(self):
        adapter, band_item, info = self.adapter(basis='fixed', rule=None)
        fixed = replace(band_item, price_bands=())
        adapter.bindings[fixed.instrument_id] = InstrumentBinding(fixed, 'FFFK6')
        info.tick = float(fixed.tick_size)
        self.assertEqual(adapter.resolve(fixed.instrument_id), fixed)
        info.tick_basis = None
        with self.assertRaises(DomainError):
            adapter.resolve(fixed.instrument_id)


if __name__ == '__main__':
    unittest.main()
