"""Shared virtual SIM cash and current-owner observation checks."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from quantlab.trading.application.automatic_capacity import automatic_capacity, assert_automatic_observation, shared_sim_allocations, automatic_risk_context
from test_trading_adapters import MutableClock, capability, instrument, plan
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.manual_book import CAPACITY_SOURCE, ManualBook, ManualReceivable, ManualRiskCapacity
from quantlab.trading.application.state import AppState, LocalOrder
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, OrderStatus, PositionLot, Quote, Reservation, Side
from quantlab.trading.domain.risk import AccountDailyBaseline, RiskPolicy, RiskService
from quantlab.trading.domain.strategy import StrategyParameters
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder, BrokerPosition, RemoteSnapshot
from quantlab.trading.ports.manual import ManualAccountObservation, UnmappedBrokerOrder

D = Decimal


class AutomaticCapacityTests(unittest.TestCase):
    def setUp(self):
        clock = MutableClock()
        self.stock, self.future = instrument(), instrument(Market.INDEX_FUTURE)
        self.fees = FeeSchedule(
            buy_rate=D('0'),
            sell_rate=D('0'),
            sell_tax_rate=D('0'),
            minimum_fee=D('0'),
            futures_fee_per_contract=D('0'),
            futures_tax_rate=D('0'),
            slippage_ticks=0,
        )
        books = (
            ManualBook('manual-stock', 'stock', D('60000'), clock.now().date(), market=Market.STOCK),
            ManualBook('manual-futures', 'futures', D('40000'), clock.now().date(), market=Market.INDEX_FUTURE),
        )
        gateways = {
            ref: Mock(
                snapshot=Mock(side_effect=AssertionError('no SDK snapshot')),
                refresh=Mock(side_effect=AssertionError('no SDK refresh')),
                events=Mock(side_effect=AssertionError('no SDK events')),
                inspect=Mock(side_effect=AssertionError('no SDK inspect')),
            )
            for ref in ('stock', 'futures')
        }
        self.engine = SimpleNamespace(
            configuration=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            clock=clock,
            catalog=Catalog((self.stock, self.future)),
            fees=self.fees,
            state=replace(
                AppState(), environment=Environment.BROKER_SIMULATION, trading_day=clock.now().date(), manual_books=books, reconciled=True, stopped=False
            ),
            gateways=gateways,
            risk=lambda: RiskService(RiskPolicy(), self.fees),
            quotes={self.stock.instrument_id: self.quote(self.stock, D('10'), clock), self.future.instrument_id: self.quote(self.future, D('100'), clock)},
            reservations=Mock(side_effect=AssertionError('pending reservations are subtracted only by RiskService')),
            automatic_observation_validator=Mock(),
            automatic_entry_validator=Mock(),
            assert_execution_allowed=Mock(),
            manual_observations={ref: ManualAccountObservation(ref, Environment.BROKER_SIMULATION, (), (), (), clock.now()) for ref in gateways},
        )

    @staticmethod
    def quote(spec, price, clock):
        return Quote(spec.instrument_id, price, price, price, clock.now(), clock.now(), clock.now().date())

    def lot(self, owner='auto', *, account='stock', quantity=1000, realized=D('0'), lot_id='owned'):
        spec = self.stock if account == 'stock' else self.future
        return PositionLot(
            lot_id,
            account,
            spec.instrument_id,
            owner,
            1,
            HoldingPolicy(HoldingKind.CUSTOM, 0, 0),
            quantity,
            D('10') if account == 'stock' else D('100'),
            self.engine.state.trading_day,
            quantity,
            realized_pnl=realized,
        )

    def order(self, owner='auto', *, account='stock', quantity=1000, status=OrderStatus.ACCEPTED, cost=D('0'), reduce_only=False, key='entry', cash=D('0')):
        spec = self.stock if account == 'stock' else self.future
        intent = replace(
            plan(spec, environment=Environment.BROKER_SIMULATION, quantity=quantity),
            plan_id=key,
            account_ref=account,
            strategy_id=owner,
            limit_price=D('10') if account == 'stock' else D('100'),
            stop_price=D('9.95') if account == 'stock' else D('99'),
            reduce_only=reduce_only,
        )
        reservation = Reservation(key, account, spec.instrument_id, spec.underlying, cash, D('0'), quantity, status)
        return LocalOrder(key, key, key, intent, HoldingPolicy(HoldingKind.CUSTOM, 0, 0), reservation, status, costs=cost)

    def typed(self, owner='auto', state='ACTIVE'):
        return SimpleNamespace(strategy_id=owner, version=1, parameters=StrategyParameters('5m', D('.01'), D('30000')), state=state)

    def assert_no_sdk_query(self):
        for gateway in self.engine.gateways.values():
            gateway.snapshot.assert_not_called()
            gateway.refresh.assert_not_called()
            gateway.events.assert_not_called()
            gateway.inspect.assert_not_called()

    def test_capacity_is_explicit_virtual_subclass_never_broker_observation(self):
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertIsInstance(capacity, ManualRiskCapacity)
        self.assertNotIsInstance(capacity, RemoteSnapshot)
        self.assertEqual((capacity.source, capacity.environment), (CAPACITY_SOURCE, Environment.BROKER_SIMULATION))
        self.assertEqual((capacity.equity, capacity.allocated_cash, capacity.settled_cash, capacity.broker_limit), (D('60000'),) * 4)
        self.assertEqual((capacity.version, capacity.as_of), (self.engine.state.version, self.engine.clock.now()))
        self.assert_no_sdk_query()

    def test_missing_confirmed_book_cannot_create_funds(self):
        self.engine.state = replace(self.engine.state, manual_books=())
        with self.assertRaises(DomainError) as rejected:
            automatic_capacity(self.engine, 'stock')
        self.assertEqual(rejected.exception.code, 'manual_book_not_enabled')

    def test_duplicate_confirmed_books_cannot_duplicate_capital(self):
        book = self.engine.state.manual_books[0]
        self.engine.state = replace(self.engine.state, manual_books=(replace(book, capital=D('30000')), replace(book, book_id='duplicate', capital=D('30000'))))
        with self.assertRaises(DomainError) as rejected:
            automatic_capacity(self.engine, 'stock')
        self.assertEqual(rejected.exception.code, 'manual_book_not_enabled')

    def test_nonvirtual_book_source_is_not_accepted_as_confirmed_pool(self):
        book = replace(self.engine.state.manual_books[0], source='BROKER_BALANCE')
        self.engine.state = replace(self.engine.state, manual_books=(book,))
        with self.assertRaises(DomainError):
            automatic_capacity(self.engine, 'stock')

    def test_capacity_never_runs_for_live_or_local(self):
        for environment, code in ((Environment.LIVE, 'production_orders_disabled'), (Environment.LOCAL, 'capability_missing')):
            with self.subTest(environment=environment):
                self.engine.configuration.environment = environment
                with self.assertRaises(DomainError) as rejected:
                    automatic_capacity(self.engine, 'stock')
                self.assertEqual(rejected.exception.code, code)
        self.assert_no_sdk_query()

    def test_all_manual_auto_retired_ownership_consumes_same_pool(self):
        lots = (self.lot('manual-stock', lot_id='manual'), self.lot('auto', lot_id='auto'), self.lot('retired', lot_id='retired'))
        self.engine.state = replace(self.engine.state, positions=lots, strategies=(self.typed(), self.typed('retired', 'RETIRED')))
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.margin_used, capacity.settled_cash, capacity.equity), (D('30000'), D('60000'), D('60000')))

    def test_other_account_ownership_and_fees_do_not_reduce_target_pool(self):
        self.engine.state = replace(
            self.engine.state,
            positions=(self.lot(account='futures', quantity=1, realized=D('-5000')),),
            orders=(self.order(account='futures', quantity=1, cost=D('1000')),),
        )
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.margin_used, capacity.settled_cash, capacity.equity), (D('0'), D('60000'), D('60000')))

    def test_closed_losses_and_entry_costs_reduce_cash_but_exit_cost_is_not_double_charged(self):
        self.engine.state = replace(
            self.engine.state,
            positions=(self.lot(quantity=0, realized=D('-110')),),
            orders=(self.order(cost=D('20'), status=OrderStatus.FILLED), self.order(cost=D('10'), reduce_only=True, key='exit', status=OrderStatus.FILLED)),
        )
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.settled_cash, capacity.equity, capacity.margin_used), (D('59870'), D('59870'), D('0')))

    def test_unrealized_gain_changes_equity_but_not_settled_cash(self):
        self.engine.state = replace(self.engine.state, positions=(self.lot(),))
        self.engine.quotes[self.stock.instrument_id] = self.quote(self.stock, D('11'), self.engine.clock)
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.equity, capacity.settled_cash, capacity.margin_used), (D('61000'), D('60000'), D('10000')))

    def test_equity_and_settled_cash_floor_at_zero_without_new_capital(self):
        self.engine.state = replace(self.engine.state, positions=(self.lot(quantity=0, realized=D('-100000')),))
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.equity, capacity.settled_cash, capacity.broker_limit, capacity.allocated_cash), (D('0'), D('0'), D('0'), D('60000')))

    def test_only_future_unsettled_proceeds_for_account_are_reserved(self):
        today = self.engine.state.trading_day
        receivables = (
            ManualReceivable('stock', 'unsettled-auto', D('12000'), today + timedelta(days=1)),
            ManualReceivable('stock', 'matures-today', D('3000'), today),
            ManualReceivable('futures', 'other', D('8000'), today + timedelta(days=1)),
        )
        self.engine.state = replace(self.engine.state, manual_receivables=receivables)
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.settlement_reserved, capacity.settled_cash), (D('12000'), D('60000')))

    def test_pending_reservations_are_not_pre_subtracted_from_capacity(self):
        self.engine.state = replace(self.engine.state, orders=(self.order('manual-stock', cash=D('20000')),))
        capacity = automatic_capacity(self.engine, 'stock')
        self.assertEqual((capacity.settled_cash, capacity.margin_used, capacity.settlement_reserved), (D('60000'), D('0'), D('0')))
        self.engine.reservations.assert_not_called()

    def preview_shared_cash(self, owned_owner, pending_owner):
        pending = self.order(pending_owner, quantity=2000, cash=D('20000'))
        self.engine.state = replace(self.engine.state, positions=(self.lot(owned_owner, quantity=2000),), orders=(pending,), strategies=(self.typed(),))
        capacities = shared_sim_allocations(self.engine)
        capacity = next(row for row in capacities if row.account_ref == 'stock')
        intent = self.order('new-owner', quantity=5000).plan
        capabilities = replace(capability(Environment.BROKER_SIMULATION), account_ref='stock')
        decision = self.engine.risk().preview(
            intent,
            self.stock,
            self.engine.quotes[self.stock.instrument_id],
            capacity,
            capabilities,
            now=self.engine.clock.now(),
            reservations=(pending.reservation,),
            allocations=capacities,
            policy=HoldingPolicy(HoldingKind.SWING, 2, 10),
        )
        self.assertEqual((capacity.settled_cash, capacity.margin_used), (D('60000'), D('20000')))
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.quantity, 2000)
        self.assert_no_sdk_query()

    def test_automatic_commitment_reduces_manual_preview_cash(self):
        self.preview_shared_cash('auto', 'manual-stock')

    def test_manual_commitment_reduces_automatic_preview_cash(self):
        self.preview_shared_cash('manual-stock', 'auto')

    def test_typed_future_uses_same_conservative_margin_when_broker_margin_missing(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=None)))
        self.engine.state = replace(self.engine.state, positions=(self.lot(account='futures', quantity=1),), strategies=(self.typed(state='RETIRED'),))
        capacity = automatic_capacity(self.engine, 'futures')
        self.assertEqual(capacity.margin_used, D('50000'))

    def test_typed_future_nonbroker_margin_provenance_uses_conservative_fallback(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=D('35050'))))
        self.engine.unverified_automatic_margins = frozenset((self.future.instrument_id,))
        self.engine.state = replace(self.engine.state, positions=(self.lot(account='futures', quantity=2),), strategies=(self.typed(state='RETIRED'),))
        self.assertEqual(automatic_capacity(self.engine, 'futures').margin_used, D('100000'))

    def test_typed_future_verified_margin_is_not_replaced_by_other_instrument_provenance(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=D('35050'))))
        self.engine.unverified_automatic_margins = frozenset(('TMF:202612',))
        self.engine.state = replace(self.engine.state, positions=(self.lot(account='futures', quantity=2),), strategies=(self.typed(),))
        self.assertEqual(automatic_capacity(self.engine, 'futures').margin_used, D('70100'))

    def test_existing_manual_future_retains_its_explicit_margin_authority(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=D('35050'))))
        self.engine.unverified_automatic_margins = frozenset((self.future.instrument_id,))
        self.engine.state = replace(self.engine.state, positions=(self.lot('manual-futures', account='futures', quantity=2),))
        self.assertEqual(automatic_capacity(self.engine, 'futures').margin_used, D('70100'))

    def test_manual_future_with_missing_margin_is_not_invented(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=None)))
        self.engine.state = replace(self.engine.state, positions=(self.lot('manual-futures', account='futures', quantity=1),))
        with self.assertRaises(DomainError) as rejected:
            automatic_capacity(self.engine, 'futures')
        self.assertEqual(rejected.exception.code, 'instrument_unresolved')

    def test_different_strategy_version_does_not_supply_missing_margin_authority(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=None)))
        record = self.typed('manual-futures')
        record.version = 2
        self.engine.state = replace(self.engine.state, positions=(self.lot('manual-futures', account='futures', quantity=1),), strategies=(record,))
        with self.assertRaises(DomainError):
            automatic_capacity(self.engine, 'futures')

    def test_closed_futures_need_no_margin_or_quote(self):
        self.engine.catalog = Catalog((self.stock, replace(self.future, margin=None)))
        self.engine.quotes.pop(self.future.instrument_id)
        self.engine.state = replace(self.engine.state, positions=(self.lot('manual-futures', account='futures', quantity=0, realized=D('-100')),))
        capacity = automatic_capacity(self.engine, 'futures')
        self.assertEqual((capacity.margin_used, capacity.settled_cash, capacity.equity), (D('0'), D('39900'), D('39900')))

    def test_known_futures_margin_is_multiplied_by_held_contracts(self):
        self.engine.state = replace(self.engine.state, positions=(self.lot('manual-futures', account='futures', quantity=2),))
        capacity = automatic_capacity(self.engine, 'futures')
        self.assertEqual(capacity.margin_used, D('40000'))

    def test_shared_allocations_include_both_books_within_all_configured_caps(self):
        allocations = shared_sim_allocations(self.engine)
        self.assertEqual({row.account_ref: row.allocated_cash for row in allocations}, {'stock': D('60000'), 'futures': D('40000')})
        self.assertTrue(all(row.source == CAPACITY_SOURCE for row in allocations))
        self.assert_no_sdk_query()

    def test_stock_book_sum_cannot_exceed_stock_configuration(self):
        stock, futures = self.engine.state.manual_books
        self.engine.state = replace(self.engine.state, manual_books=(replace(stock, capital=D('61000')), replace(futures, capital=D('39000'))))
        with self.assertRaises(DomainError) as rejected:
            shared_sim_allocations(self.engine)
        self.assertEqual(rejected.exception.code, 'manual_allocation_exceeds_settings')

    def test_futures_book_sum_cannot_exceed_futures_configuration(self):
        stock, futures = self.engine.state.manual_books
        self.engine.state = replace(self.engine.state, manual_books=(replace(stock, capital=D('59000')), replace(futures, capital=D('41000'))))
        with self.assertRaises(DomainError):
            shared_sim_allocations(self.engine)

    def test_book_sum_cannot_exceed_platform_budget(self):
        self.engine.risk = lambda: RiskService(RiskPolicy(total_budget=D('80000')), self.fees)
        with self.assertRaises(DomainError):
            shared_sim_allocations(self.engine)

    def test_complete_fresh_current_generation_cache_never_queries_sdk(self):
        assert_automatic_observation(self.engine, 'stock')
        expected = [(ref, row) for ref, row in self.engine.manual_observations.items()]
        self.assertEqual([call.args for call in self.engine.automatic_observation_validator.call_args_list], expected)
        self.assert_no_sdk_query()

    def test_entry_observation_never_allows_live_or_local(self):
        for environment in (Environment.LIVE, Environment.LOCAL):
            with self.subTest(environment=environment):
                self.engine.configuration.environment = environment
                with self.assertRaises(DomainError):
                    assert_automatic_observation(self.engine, 'stock')
        self.assert_no_sdk_query()

    def test_entry_requires_configured_target_account(self):
        with self.assertRaises(DomainError) as rejected:
            assert_automatic_observation(self.engine, 'unknown')
        self.assertEqual(rejected.exception.code, 'capability_missing')

    def test_missing_other_account_observation_blocks_shared_budget_entry(self):
        self.engine.manual_observations.pop('futures')
        with self.assertRaises(DomainError) as rejected:
            assert_automatic_observation(self.engine, 'stock')
        self.assertEqual(rejected.exception.code, 'manual_account_observation_required')

    def test_extra_unconfigured_account_observation_is_not_complete_current_cache(self):
        self.engine.manual_observations['other'] = ManualAccountObservation('other', Environment.BROKER_SIMULATION, (), (), (), self.engine.clock.now())
        with self.assertRaises(DomainError):
            assert_automatic_observation(self.engine, 'stock')

    def test_stale_or_future_observation_of_other_account_blocks_entry(self):
        original = self.engine.manual_observations['futures']
        for offset in (-31, 1):
            with self.subTest(offset=offset):
                self.engine.manual_observations['futures'] = replace(original, as_of=self.engine.clock.now() + timedelta(seconds=offset))
                with self.assertRaises(DomainError):
                    assert_automatic_observation(self.engine, 'stock')

    def test_cross_account_cache_payload_cannot_authorize_entry(self):
        self.engine.manual_observations['futures'] = self.engine.manual_observations['stock']
        with self.assertRaises(DomainError):
            assert_automatic_observation(self.engine, 'stock')

    def test_non_sim_observation_cannot_authorize_sim_entry(self):
        self.engine.manual_observations['futures'] = replace(self.engine.manual_observations['futures'], environment=Environment.LIVE)
        with self.assertRaises(DomainError):
            assert_automatic_observation(self.engine, 'stock')

    def test_untyped_observation_is_not_normalized_evidence(self):
        self.engine.manual_observations['futures'] = SimpleNamespace(
            account_ref='futures', environment=Environment.BROKER_SIMULATION, as_of=self.engine.clock.now(), unmapped=(), orders=()
        )
        with self.assertRaises(DomainError):
            assert_automatic_observation(self.engine, 'stock')

    def test_current_owner_generation_validator_is_required(self):
        self.engine.automatic_observation_validator = None
        with self.assertRaises(DomainError) as rejected:
            assert_automatic_observation(self.engine, 'stock')
        self.assertEqual(rejected.exception.code, 'capability_missing')

    def test_changed_owner_generation_is_rejected_without_a_query(self):
        self.engine.automatic_observation_validator = Mock(side_effect=DomainError('state_conflict', 'SDK generation changed'))
        with self.assertRaises(DomainError) as rejected:
            assert_automatic_observation(self.engine, 'stock')
        self.assertEqual(rejected.exception.code, 'state_conflict')
        self.assert_no_sdk_query()

    def test_unreconciled_book_cannot_open_automatic_entries(self):
        self.engine.state = replace(self.engine.state, reconciled=False)
        with self.assertRaises(DomainError) as rejected:
            assert_automatic_observation(self.engine, 'stock')
        self.assertEqual(rejected.exception.code, 'reconciliation_required')

    def test_local_unknown_submitting_or_cancel_pending_other_account_blocks_entry(self):
        for status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING):
            with self.subTest(status=status):
                self.engine.state = replace(self.engine.state, orders=(self.order(account='futures', quantity=1, status=status),))
                with self.assertRaises(DomainError):
                    assert_automatic_observation(self.engine, 'stock')

    def test_remote_unknown_submitting_or_cancel_pending_other_account_blocks_entry(self):
        original = self.engine.manual_observations['futures']
        intent = self.order(account='futures', quantity=1).plan
        for status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING):
            with self.subTest(status=status):
                remote = BrokerOrder('remote-owned', intent, 0, D('0'), status, 'sdk-ref', self.engine.clock.now())
                self.engine.manual_observations['futures'] = replace(original, orders=(remote,))
                with self.assertRaises(DomainError):
                    assert_automatic_observation(self.engine, 'stock')

    def test_unmapped_remote_order_other_account_blocks_entry(self):
        self.engine.manual_observations['futures'] = replace(self.engine.manual_observations['futures'], unmapped=(UnmappedBrokerOrder('external'),))
        with self.assertRaises(DomainError):
            assert_automatic_observation(self.engine, 'stock')

    def prepare_context(self, *, reduce_only=False):
        intent = self.order(reduce_only=reduce_only).plan
        record = self.typed()
        record.form = SimpleNamespace(account_ref='stock', environment=Environment.BROKER_SIMULATION)
        state = vars(self.engine.state).copy()
        state['automatic'] = SimpleNamespace(auto_paused=False)
        state['account_daily_baselines'] = tuple(
            AccountDailyBaseline(ref, self.engine.state.trading_day, D('0'), 'trusted-close') for ref in self.engine.gateways
        )
        self.engine.state = SimpleNamespace(**state)
        typed_capability = replace(capability(Environment.BROKER_SIMULATION), account_ref='stock')
        self.engine.gateways['stock'].inspect.side_effect = None
        self.engine.gateways['stock'].inspect.return_value = typed_capability
        if reduce_only:
            intent = replace(intent, side=Side.SELL)
            self.engine.state.positions = (self.lot(),)
            observed = BrokerPosition('stock', self.stock.instrument_id, 1000, 1000, intent.unit, D('10'))
            self.engine.manual_observations['stock'] = replace(self.engine.manual_observations['stock'], positions=(observed,))
        return intent, record, typed_capability

    def test_context_returns_shared_virtual_capacity_and_current_capability(self):
        intent, record, proof = self.prepare_context()
        account, allocations, current, pnl = automatic_risk_context(self.engine, intent, record)
        self.assertIs(current, proof)
        self.assertEqual((account.account_ref, account.allocated_cash, pnl), ('stock', D('60000'), D('0')))
        self.assertEqual({row.account_ref for row in allocations}, {'stock', 'futures'})
        self.engine.gateways['stock'].inspect.assert_called_once_with('stock')

    def test_context_rejects_live_plan_before_capability_or_native_access(self):
        intent, record, _ = self.prepare_context()
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, replace(intent, environment=Environment.LIVE), record)
        self.assertEqual(rejected.exception.code, 'production_orders_disabled')
        self.assert_no_sdk_query()

    def test_context_requires_a_typed_matching_record(self):
        intent, record, _ = self.prepare_context()
        cases = (None, SimpleNamespace(**{**vars(record), 'parameters': None}))
        for wrong in cases:
            with self.subTest(record=wrong), self.assertRaises(DomainError) as rejected:
                automatic_risk_context(self.engine, intent, wrong)
            self.assertEqual(rejected.exception.code, 'capability_missing')
        for field, value in (('strategy_id', 'other'), ('version', 2)):
            wrong = SimpleNamespace(**{**vars(record), field: value})
            with self.subTest(field=field), self.assertRaises(DomainError):
                automatic_risk_context(self.engine, intent, wrong)
        for field, value in (('account_ref', 'futures'), ('environment', Environment.LOCAL)):
            wrong = SimpleNamespace(**{**vars(record), 'form': SimpleNamespace(**{**vars(record.form), field: value})})
            with self.subTest(field=field), self.assertRaises(DomainError):
                automatic_risk_context(self.engine, intent, wrong)
        self.assert_no_sdk_query()

    def test_context_checks_observation_before_entry_admission(self):
        intent, record, _ = self.prepare_context()
        self.engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'state_conflict')
        self.assert_no_sdk_query()

    def test_context_cannot_bypass_the_engine_live_execution_guard(self):
        intent, record, _ = self.prepare_context()
        self.engine.assert_execution_allowed.side_effect = DomainError('production_orders_disabled')
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'production_orders_disabled')
        self.assert_no_sdk_query()

    def test_context_paused_automatic_state_cannot_open_new_risk(self):
        intent, record, _ = self.prepare_context()
        self.engine.state.automatic.auto_paused = True
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'automatic_paused')
        self.assert_no_sdk_query()

    def test_context_requires_current_entry_validator_port(self):
        intent, record, _ = self.prepare_context()
        self.engine.automatic_entry_validator = None
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'capability_missing')
        self.assert_no_sdk_query()

    def test_context_must_obey_current_entry_proof_failure(self):
        intent, record, _ = self.prepare_context()
        self.engine.automatic_entry_validator.side_effect = DomainError('preflight_permission')
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'preflight_permission')
        self.engine.automatic_entry_validator.assert_called_once_with('stock')
        self.assert_no_sdk_query()

    def test_protective_context_does_not_need_an_entry_validator_or_entry_proofs(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.automatic_entry_validator = None
        self.assertEqual(automatic_risk_context(self.engine, intent, record)[3], D('0'))

    def test_context_missing_target_book_cannot_supply_virtual_capital(self):
        intent, record, _ = self.prepare_context()
        self.engine.state.manual_books = self.engine.state.manual_books[1:]
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'manual_book_not_enabled')

    def test_context_day_pnl_uses_all_book_baselines_not_generic_or_cumulative_marks(self):
        intent, record, _ = self.prepare_context()
        self.engine.state.positions = (self.lot(quantity=0, realized=D('-150')), self.lot(account='futures', quantity=0, realized=D('40')))
        self.engine.state.account_daily_baselines = (
            AccountDailyBaseline('stock', self.engine.state.trading_day, D('-100'), 'trusted-close'),
            AccountDailyBaseline('futures', self.engine.state.trading_day, D('10'), 'trusted-close'),
        )
        self.engine.state.daily_pnl = D('12345')
        self.assertEqual(automatic_risk_context(self.engine, intent, record)[3], D('-20'))

    def test_context_missing_any_shared_current_day_baseline_blocks_entries(self):
        intent, record, _ = self.prepare_context()
        current = self.engine.state.account_daily_baselines
        for rows in (current[:1], (current[0], replace(current[1], trade_date=self.engine.state.trading_day - timedelta(days=1)))):
            with self.subTest(rows=rows):
                self.engine.state.account_daily_baselines = rows
                with self.assertRaises(DomainError) as rejected:
                    automatic_risk_context(self.engine, intent, record)
                self.assertEqual(rejected.exception.code, 'account_daily_baseline_required')

    def test_protective_context_uses_only_current_scope_without_unrelated_quotes_or_unknowns(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.state.automatic.auto_paused = True
        self.engine.state.stopped = True
        self.engine.state.reconciled = False
        self.engine.state.account_daily_baselines = ()
        unrelated = self.order(account='futures', quantity=1, status=OrderStatus.UNKNOWN)
        self.engine.state.orders = (unrelated,)
        self.engine.state.positions += (self.lot(account='futures', quantity=1),)
        self.engine.quotes.clear()
        self.engine.manual_observations['futures'] = replace(self.engine.manual_observations['futures'], as_of=self.engine.clock.now() - timedelta(seconds=31))
        account, allocations, _, pnl = automatic_risk_context(self.engine, intent, record)
        self.assertEqual((account.equity, account.margin_used, pnl), (D('60000'), D('0'), D('0')))
        self.assertEqual(allocations, (account,))
        self.assertEqual([row.args[0] for row in self.engine.automatic_observation_validator.call_args_list], ['stock'])

    def test_protective_context_needs_no_observation_for_other_account(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.manual_observations.pop('futures')
        self.assertEqual(automatic_risk_context(self.engine, intent, record)[3], D('0'))

    def test_protective_virtual_equity_is_recorded_realized_cash_without_market_value(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.state.positions += (self.lot(quantity=0, realized=D('-110'), lot_id='closed'),)
        self.engine.state.orders = (self.order(cost=D('20'), status=OrderStatus.FILLED),)
        self.engine.quotes.clear()
        account = automatic_risk_context(self.engine, intent, record)[0]
        self.assertEqual((account.equity, account.settled_cash), (D('59870'), D('59870')))

    def test_protective_context_still_requires_fresh_current_observation_and_owner(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        current = self.engine.manual_observations['stock']
        for observation in (None, replace(current, as_of=current.as_of - timedelta(seconds=31))):
            self.engine.manual_observations['stock'] = observation
            with self.subTest(observation=observation), self.assertRaises(DomainError):
                automatic_risk_context(self.engine, intent, record)
        self.engine.manual_observations['stock'] = current
        self.engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'state_conflict')

    def test_protective_context_rejects_target_instrument_reconciliation_difference(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.state.reconciliation = (SimpleNamespace(account_ref='stock', instrument_id=self.stock.instrument_id),)
        with self.assertRaises(DomainError) as rejected:
            automatic_risk_context(self.engine, intent, record)
        self.assertEqual(rejected.exception.code, 'reconciliation_required')

    def test_protective_context_ignores_other_account_and_instrument_reconciliation_differences(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.state.reconciliation = (
            SimpleNamespace(account_ref='futures', instrument_id=self.stock.instrument_id),
            SimpleNamespace(account_ref='stock', instrument_id=self.future.instrument_id),
        )
        self.assertEqual(automatic_risk_context(self.engine, intent, record)[3], D('0'))

    def test_protective_context_rejects_local_and_remote_unknown_in_same_instrument(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        current = self.engine.manual_observations['stock']
        for remote in (False, True):
            for status in UNRESOLVED_STATUSES:
                with self.subTest(remote=remote, status=status):
                    row = self.order(status=status)
                    self.engine.state.orders = () if remote else (row,)
                    observed = BrokerOrder(row.order_id, row.plan, 0, D('0'), status, 'sdk-owned', self.engine.clock.now())
                    self.engine.manual_observations['stock'] = replace(current, orders=(observed,) if remote else ())
                    with self.assertRaises(DomainError):
                        automatic_risk_context(self.engine, intent, record)

    def test_protective_context_ignores_same_account_other_instrument_unknown(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        row = self.order(account='futures', quantity=1, status=OrderStatus.UNKNOWN)
        row = replace(row, plan=replace(row.plan, account_ref='stock'))
        self.engine.state.orders = (row,)
        remote = BrokerOrder(row.order_id, row.plan, 0, D('0'), OrderStatus.UNKNOWN, 'sdk-other', self.engine.clock.now())
        self.engine.manual_observations['stock'] = replace(self.engine.manual_observations['stock'], orders=(remote,))
        self.assertEqual(automatic_risk_context(self.engine, intent, record)[3], D('0'))

    def test_protective_context_rejects_changed_missing_duplicate_or_wrong_unit_position(self):
        from quantlab.trading.domain.models import QuantityUnit

        intent, record, _ = self.prepare_context(reduce_only=True)
        current = self.engine.manual_observations['stock']
        position = current.positions[0]
        for rows in (
            (),
            (replace(position, quantity=900, sellable_quantity=900),),
            (replace(position, quantity=500, sellable_quantity=500),) * 2,
            (replace(position, unit=QuantityUnit.CONTRACT),),
        ):
            with self.subTest(rows=rows):
                self.engine.manual_observations['stock'] = replace(current, positions=rows)
                with self.assertRaises(DomainError) as rejected:
                    automatic_risk_context(self.engine, intent, record)
                self.assertEqual(rejected.exception.code, 'reconciliation_required')

    def test_protective_context_signed_short_quantity_matches_sell_lot(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.state.positions = (replace(self.lot(), direction=Side.SELL),)
        position = replace(self.engine.manual_observations['stock'].positions[0], quantity=-1000)
        self.engine.manual_observations['stock'] = replace(self.engine.manual_observations['stock'], positions=(position,))
        self.assertEqual(automatic_risk_context(self.engine, replace(intent, side=Side.BUY), record)[3], D('0'))

    def test_protective_quantity_scope_ignores_other_account_instrument_external_and_zero_positions(self):
        intent, record, _ = self.prepare_context(reduce_only=True)
        self.engine.state.positions += (
            replace(self.lot(), account_ref='futures'),
            replace(self.lot(), instrument_id=self.future.instrument_id),
            replace(self.lot(), origin='EXTERNAL'),
        )
        current = self.engine.manual_observations['stock']
        other = replace(current.positions[0], instrument_id=self.future.instrument_id)
        zero = replace(current.positions[0], quantity=0, sellable_quantity=0)
        self.engine.manual_observations['stock'] = replace(current, positions=(*current.positions, other, zero))
        unrelated = self.order(status=OrderStatus.UNKNOWN)
        self.engine.state.orders = (replace(unrelated, plan=replace(unrelated.plan, account_ref='futures')),)
        self.assertEqual(automatic_risk_context(self.engine, intent, record)[3], D('0'))


UNRESOLVED_STATUSES = (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING)


if __name__ == '__main__':
    unittest.main()
