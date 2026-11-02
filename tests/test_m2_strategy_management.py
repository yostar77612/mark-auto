"""M2 typed strategy lifecycle and isolated capital against a real offline port."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import unittest

from test_live_order_guard import GuardJournal
from test_trading_adapters import MutableClock, account, capability
from quantlab.trading.adapters.simulated import FaultPlan, SimulatedBroker
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import StrategyForm, StrategyParameters, UiAction, UiCommand, strategy_defaults
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import poll_events, reconcile
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.research import research_fingerprint
from quantlab.trading.application.workflows import resume, run_research
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderPlan, OrderStatus, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar, synthetic_catalog, synthetic_history
from quantlab.trading.runtime.provenance import compute_profile

D = Decimal


class StrategyManagementTests(unittest.TestCase):
    def setUp(self):
        self.clock = MutableClock()
        self.calendar = synthetic_calendar()
        catalog = synthetic_catalog()
        self.specs = tuple(s for s in catalog.instruments if s.instrument_id in ('TWSE:2330', 'TWSE:DEMO01', 'TAIFEX:TMF:202612'))
        self.fees = FeeSchedule(
            buy_rate=D('0'),
            sell_rate=D('0'),
            sell_tax_rate=D('0'),
            minimum_fee=D('0'),
            futures_fee_per_contract=D('0'),
            futures_tax_rate=D('0'),
            slippage_ticks=0,
        )
        self.broker = SimulatedBroker(
            self.clock,
            account(),
            self.specs,
            replace(capability(), day_trade=True),
            fee_schedule=self.fees,
        )
        self.engine = TradingEngine(
            GuardJournal(),
            self.clock,
            self.calendar,
            Catalog(self.specs),
            {'test-stock': self.broker},
            configuration=ExecutionConfiguration(stock_account_ref='test-stock', futures_account_ref=''),
            ownership_clock=self.clock.now,
            source_profile=compute_profile(),
            fees=self.fees,
            historical_bars=synthetic_history(Catalog(self.specs), self.calendar),
        )
        self.facade = LocalFacade(self.engine)
        for spec in self.specs:
            price = D('20000') if spec.market is not Market.STOCK else D('10')
            self.engine.quote(Quote(spec.instrument_id, price - spec.tick_size, price, price, self.clock.now(), self.clock.now(), self.clock.now().date()))
        reconcile(self.engine)
        resume(self.engine)

    def command(self, action, *, accepted=True, **values):
        result = self.facade.execute(UiCommand(action, self.engine.state.version, **values))
        self.assertEqual(result.accepted, accepted, result)
        return result

    def form(self, instrument='TWSE:2330', allocation=D('20000')):
        return StrategyForm(
            'typed-stock',
            Market.STOCK,
            HoldingKind.SWING,
            2,
            10,
            Side.BUY,
            instrument,
            'test-stock',
            Environment.LOCAL,
            allocation,
            D('.02'),
            'BUY_AND_HOLD',
        )

    def parameters(self, **changes):
        return replace(StrategyParameters('1d', D('.03'), D('30000')), **changes)

    def create(self, instrument='TWSE:2330', allocation=D('20000'), **parameters):
        return self.command(
            UiAction.CREATE_TYPED_STRATEGY,
            strategy=self.form(instrument, allocation),
            strategy_parameters=self.parameters(**parameters),
        ).reference

    def research(self, reference):
        with self.engine.lock:
            self.engine.validate_strategy(reference)
            record = self.engine.strategy(reference)
            run_research(self.engine, reference, self.engine.history[record.form.instrument_id])

    def deploy(self, instrument='TWSE:2330', allocation=D('20000'), **parameters):
        reference = self.create(instrument, allocation, **parameters)
        self.research(reference)
        self.command(UiAction.DEPLOY, target_id=reference)
        return reference

    def plan(self, reference, *, quantity=1000, stop=D('9.95'), key='entry'):
        record = self.engine.strategy(reference)
        spec = self.engine.catalog.resolve(record.form.instrument_id)
        return OrderPlan(
            key,
            record.form.account_ref,
            self.engine.configuration.environment,
            spec.instrument_id,
            record.strategy_id,
            record.version,
            Side.BUY,
            quantity,
            spec.unit,
            D('10'),
            stop,
            False,
            self.clock.now(),
            self.clock.now() + timedelta(seconds=30),
            self.engine.state.version,
        )

    def submit(self, reference, **values):
        plan = self.plan(reference, **values)
        return self.engine.submit(plan, self.engine.strategy(reference).policy, plan.plan_id)

    def test_typed_command_and_view_roundtrip_without_changing_legacy_form(self):
        form, parameters = self.form(), self.parameters()
        command = UiCommand(UiAction.CREATE_TYPED_STRATEGY, self.engine.state.version, strategy=form, strategy_parameters=parameters)
        self.assertEqual(loads(dumps(command)), command)
        result = self.facade.execute(loads(dumps(command)))
        self.assertTrue(result.accepted, result)
        record = self.engine.strategy(result.reference)
        self.assertEqual(record.form, form)
        self.assertEqual(record.parameters, parameters)
        view = self.facade.snapshot().strategies[0]
        self.assertEqual(view.parameters, parameters)
        self.assertEqual(loads(dumps(view)), view)
        self.assertEqual(strategy_defaults(HoldingKind.POSITION).bar_interval, '1d')
        products = {p.instrument_id: p for p in self.facade.snapshot().strategy_products}
        self.assertNotIn(HoldingKind.INTRADAY, products['TWSE:2330'].holding_kinds)
        self.assertTrue(products['TWSE:2330'].stock_intraday_optional)
        self.assertEqual(products['TAIFEX:TMF:202612'].holding_kinds, (HoldingKind.INTRADAY, HoldingKind.CUSTOM))

    def test_typed_creation_requires_execution_parameters(self):
        result = self.command(UiAction.CREATE_TYPED_STRATEGY, accepted=False, strategy=self.form())
        self.assertEqual(result.code, 'strategy_parameters_invalid')
        self.assertEqual(self.engine.state.strategies, ())

    def test_engine_creation_rejects_untyped_parameter_payload(self):
        with self.assertRaises(DomainError) as rejected:
            self.engine.create_strategy(self.form(), 'untyped')
        self.assertEqual(rejected.exception.code, 'strategy_parameters_invalid')

    def test_deploy_requires_research_even_when_form_and_account_are_valid(self):
        reference = self.create()
        result = self.command(UiAction.DEPLOY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'risk_rejected')
        self.assertEqual(self.engine.strategy(reference).state, 'DRAFT')

    def test_researched_stage_without_verified_hash_cannot_deploy(self):
        reference = self.create()
        self.research(reference)
        record = self.engine.strategy(reference)
        self.engine.update_strategy(replace(record, evidence_hash=''), 'missing_research_attestation_fixture')
        result = self.command(UiAction.DEPLOY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'risk_rejected')

    def test_execution_parameter_change_invalidates_existing_research(self):
        reference = self.create()
        self.research(reference)
        record = self.engine.strategy(reference)
        self.engine.update_strategy(replace(record, parameters=replace(record.parameters, stop_fraction=D('.04'))), 'tampered_fixture')
        result = self.command(UiAction.DEPLOY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'strategy_evidence_stale')
        self.assertNotEqual(self.engine.strategy(reference).state, 'ACTIVE')

    def test_legacy_research_material_is_byte_identical_and_typed_material_is_distinct(self):
        reference = self.command(UiAction.CREATE_STRATEGY, strategy=self.form()).reference
        record = self.engine.strategy(reference)
        spec = self.engine.catalog.resolve(record.form.instrument_id)
        material = (record.form, record.definition, record.policy, spec, self.calendar, self.fees, 'dataset', self.engine.profile)
        expected = sha256(dumps(material).encode()).hexdigest()
        actual = research_fingerprint(record, spec, self.calendar, self.fees, 'dataset', self.engine.profile)
        self.assertEqual(actual, expected)
        typed = replace(record, parameters=self.parameters())
        self.assertNotEqual(research_fingerprint(typed, spec, self.calendar, self.fees, 'dataset', self.engine.profile), actual)

    def test_distinct_strategies_activate_together_but_cannot_overallocate_account(self):
        first = self.deploy(allocation=D('30000'))
        second = self.deploy('TWSE:DEMO01', allocation=D('30000'))
        self.assertEqual([s.state for s in self.engine.state.strategies], ['ACTIVE', 'ACTIVE'])
        revised = self.command(
            UiAction.REVISE_STRATEGY,
            target_id=second,
            strategy=self.form('TWSE:DEMO01', D('30001')),
            strategy_parameters=self.parameters(),
        ).reference
        self.research(revised)
        result = self.command(UiAction.DEPLOY, target_id=revised, accepted=False)
        self.assertEqual(result.code, 'strategy_allocation_exceeded')
        self.assertEqual(self.engine.strategy(first).state, 'ACTIVE')
        self.assertEqual(self.engine.strategy(second).state, 'ACTIVE')

    def test_disable_retains_positions_and_protection_and_can_reenable_same_evidence(self):
        reference = self.deploy()
        order = self.submit(reference)
        self.broker.fill(order, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        positions = self.engine.state.positions
        self.engine._persist('protective_stop_fixture', replace(self.engine.state, protection_stops=((order, D('9.95')),)))
        evidence = self.engine.strategy(reference).research_blob
        self.command(UiAction.DISABLE_STRATEGY, target_id=reference)
        self.assertEqual(self.engine.state.positions, positions)
        self.assertEqual(self.engine.state.protection_stops, ((order, D('9.95')),))
        self.assertEqual(self.engine.strategy(reference).research_blob, evidence)
        self.command(UiAction.DEPLOY, target_id=reference)
        self.assertEqual(self.engine.strategy(reference).state, 'ACTIVE')

    def test_clone_and_parameter_revision_create_unresearched_versions(self):
        first = self.deploy()
        original = self.engine.strategy(first)
        cloned = self.command(UiAction.CLONE_STRATEGY, target_id=first).reference
        clone = self.engine.strategy(cloned)
        self.assertEqual((clone.strategy_id, clone.version), (original.strategy_id, original.version + 1))
        self.assertEqual(clone.parameters, original.parameters)
        self.assertEqual((clone.state, clone.research_blob, clone.evidence_hash), ('DRAFT', '', ''))
        changed = self.parameters(entry_amount=D('15000'))
        revised = self.command(UiAction.REVISE_STRATEGY, target_id=cloned, strategy=clone.form, strategy_parameters=changed).reference
        revision = self.engine.strategy(revised)
        self.assertEqual(revision.version, clone.version + 1)
        self.assertEqual(revision.parameters, changed)
        self.assertEqual(revision.evidence_hash, '')
        self.assertEqual(self.engine.strategy(first), original)

    def test_parameter_revision_requires_complete_parameters(self):
        first = self.deploy()
        result = self.command(UiAction.REVISE_STRATEGY, target_id=first, strategy=self.form(), accepted=False)
        self.assertEqual(result.code, 'strategy_parameters_invalid')
        self.assertEqual(len(self.engine.state.strategies), 1)

    def test_typed_revision_of_legacy_record_requires_explicit_parameters(self):
        first = self.command(UiAction.CREATE_STRATEGY, strategy=self.form()).reference
        result = self.command(UiAction.REVISE_STRATEGY, target_id=first, strategy=self.form(), accepted=False)
        self.assertEqual(result.code, 'strategy_parameters_invalid')
        self.assertEqual(len(self.engine.state.strategies), 1)

    def test_direct_engine_revision_requires_complete_parameters(self):
        first = self.deploy()
        with self.assertRaises(DomainError) as rejected:
            self.engine.clone_strategy(first, self.form())
        self.assertEqual(rejected.exception.code, 'strategy_parameters_invalid')

    def test_delete_without_fills_hides_tombstone_and_never_reuses_version(self):
        reference = self.create()
        self.command(UiAction.DELETE_STRATEGY, target_id=reference)
        self.assertEqual(self.facade.snapshot().strategies, ())
        self.assertEqual(self.engine.strategy(reference).state, 'DELETED')
        next_version = self.command(UiAction.CLONE_STRATEGY, target_id=reference).reference
        self.assertEqual(self.engine.strategy(next_version).version, 2)

    def test_pending_order_blocks_delete_and_canceled_unfilled_order_allows_it(self):
        reference = self.deploy()
        order = self.submit(reference)
        result = self.command(UiAction.DELETE_STRATEGY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'state_conflict')
        service = ExecutionService(self.broker, self.engine._persist, self.engine.fence, self.clock.now)
        service.cancel(self.engine.state, order)
        poll_events(self.engine)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.CANCELED)
        self.command(UiAction.DELETE_STRATEGY, target_id=reference)
        self.assertEqual(self.facade.snapshot().strategies, ())

    def test_fully_filled_strategy_cannot_be_deleted(self):
        reference = self.deploy()
        order = self.submit(reference)
        self.broker.fill(order, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        result = self.command(UiAction.DELETE_STRATEGY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'strategy_has_fills')

    def test_fill_history_alone_prevents_deletion_without_a_retained_lot(self):
        reference = self.deploy()
        order = self.submit(reference)
        self.broker.fill(order, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        # Independently exercise history protection: a retained fill is enough,
        # even when a historical projection no longer retains its closed lot.
        self.engine._persist('historical_fill_only_fixture', replace(self.engine.state, positions=()))
        result = self.command(UiAction.DELETE_STRATEGY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'strategy_has_fills')

    def test_position_ownership_alone_prevents_deletion_without_order_history(self):
        reference = self.deploy()
        order = self.submit(reference)
        self.broker.fill(order, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        self.engine._persist('historical_position_only_fixture', replace(self.engine.state, orders=()))
        result = self.command(UiAction.DELETE_STRATEGY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'strategy_has_fills')

    def test_partially_filled_then_canceled_strategy_cannot_be_deleted(self):
        reference = self.deploy(allocation=D('30000'))
        self.broker.queue_fault(FaultPlan(partial_quantity=1000))
        order = self.submit(reference, quantity=2000)
        poll_events(self.engine)
        service = ExecutionService(self.broker, self.engine._persist, self.engine.fence, self.clock.now)
        service.cancel(self.engine.state, order)
        poll_events(self.engine)
        self.assertEqual((self.engine.state.orders[0].filled, self.engine.state.orders[0].status), (1000, OrderStatus.CANCELED))
        result = self.command(UiAction.DELETE_STRATEGY, target_id=reference, accepted=False)
        self.assertEqual(result.code, 'strategy_has_fills')

    def test_entry_cannot_spend_another_strategy_allocation(self):
        reference = self.deploy(allocation=D('8000'))
        self.deploy('TWSE:DEMO01', allocation=D('40000'))
        with self.assertRaises(DomainError):
            self.submit(reference)
        self.assertEqual(self.broker.submission_count, 0)
        self.assertEqual(self.engine.state.orders, ())

    def test_pending_entry_reservation_reduces_its_own_strategy_cash(self):
        reference = self.deploy(allocation=D('15000'))
        self.submit(reference)
        with self.assertRaises(DomainError):
            self.submit(reference, key='second-entry')
        self.assertEqual(self.broker.submission_count, 1)
        self.assertEqual(len(self.engine.state.orders), 1)

    def test_cumulative_strategy_losses_cannot_borrow_another_strategy_capital(self):
        original = self.deploy(allocation=D('20000'))
        revised = self.command(UiAction.CLONE_STRATEGY, target_id=original).reference
        self.research(revised)
        self.command(UiAction.DEPLOY, target_id=revised)
        independent = self.deploy('TWSE:DEMO01', allocation=D('30000'))
        owner = self.engine.strategy(original).strategy_id
        tracks = tuple(
            replace(track, equity=D('-3000') if track.version == 1 else D('-2000'), max_drawdown=D('5000')) if track.strategy_id == owner else track
            for track in self.engine.state.performance_tracks
        )
        self.engine._persist('strategy_loss_history_fixture', replace(self.engine.state, performance_tracks=tracks))
        with self.assertRaises(DomainError):
            self.submit(revised, quantity=2000)
        self.assertEqual(self.broker.submission_count, 0)
        self.submit(independent, key='independent-entry')
        self.assertEqual(self.broker.submission_count, 1)
        self.assertEqual(self.engine.state.orders[0].plan.strategy_id, self.engine.strategy(independent).strategy_id)

    def test_strategy_profits_do_not_expand_frozen_allocation(self):
        reference = self.deploy(allocation=D('15000'))
        owner = self.engine.strategy(reference).strategy_id
        tracks = tuple(
            replace(track, equity=D('5000'), peak=D('5000')) if track.strategy_id == owner else track for track in self.engine.state.performance_tracks
        )
        self.engine._persist('strategy_profit_history_fixture', replace(self.engine.state, performance_tracks=tracks))
        with self.assertRaises(DomainError):
            self.submit(reference, quantity=2000)
        self.assertEqual(self.broker.submission_count, 0)

    def test_near_month_view_resolves_roll_and_exposes_blocked_contract_reason(self):
        front = next(s for s in self.specs if s.market is Market.INDEX_FUTURE)
        next_month = next(s for s in synthetic_catalog().instruments if s.instrument_id == 'TAIFEX:TMF:202703')
        form = replace(self.form(), market=front.market, holding_kind=HoldingKind.INTRADAY, min_days=0, max_days=0, instrument_id=front.instrument_id)
        reference = self.command(
            UiAction.CREATE_TYPED_STRATEGY, strategy=form, strategy_parameters=self.parameters(bar_interval='5m', instrument_rule='TMF_NEAR')
        ).reference
        previous = self.calendar.days[self.calendar.index(front.expiry) - 1]
        self.engine.catalog = Catalog((*self.specs, next_month))
        self.engine._persist('roll_boundary_fixture', replace(self.engine.state, trading_day=previous))
        view = next(s for s in self.facade.snapshot().strategies if f'{s.strategy_id}:{s.version}' == reference)
        self.assertEqual((view.resolved_instrument_id, view.entry_block_code), (next_month.instrument_id, ''))
        self.engine._persist('settlement_boundary_fixture', replace(self.engine.state, trading_day=front.expiry))
        view = self.facade.snapshot().strategies[0]
        self.assertEqual((view.resolved_instrument_id, view.entry_block_code), ('', 'strategy_settlement_day'))
        self.engine.catalog = Catalog(self.specs)
        self.engine._persist('missing_next_contract_fixture', replace(self.engine.state, trading_day=previous))
        view = self.facade.snapshot().strategies[0]
        self.assertEqual((view.resolved_instrument_id, view.entry_block_code), ('', 'instrument_unresolved'))

    def test_entry_cannot_spend_another_strategy_risk_budget(self):
        reference = self.deploy(allocation=D('20000'))
        self.deploy('TWSE:DEMO01', allocation=D('30000'))
        with self.assertRaises(DomainError) as rejected:
            self.submit(reference, stop=D('9.50'))
        self.assertEqual(rejected.exception.code, 'risk_rejected')
        self.assertEqual(self.broker.submission_count, 0)

    def test_pending_entry_reservation_reduces_its_own_strategy_risk(self):
        reference = self.deploy(allocation=D('30000'))
        self.submit(reference, stop=D('9.60'))
        with self.assertRaises(DomainError) as rejected:
            self.submit(reference, stop=D('9.60'), key='second-entry')
        self.assertEqual(rejected.exception.code, 'risk_rejected')
        self.assertEqual(self.broker.submission_count, 1)

    def test_whole_lot_guard_applies_even_when_account_allows_odd_lots(self):
        reference = self.deploy()
        self.broker.capabilities = replace(self.broker.capabilities, odd_lot=True)
        with self.assertRaises(DomainError) as rejected:
            self.submit(reference, quantity=999)
        self.assertEqual(rejected.exception.code, 'strategy_size_insufficient')
        self.assertEqual(self.broker.submission_count, 0)

    def test_per_entry_amount_guard_is_independent_of_available_strategy_capital(self):
        reference = self.deploy(allocation=D('30000'), entry_amount=D('9999'))
        with self.assertRaises(DomainError) as rejected:
            self.submit(reference)
        self.assertEqual(rejected.exception.code, 'strategy_size_insufficient')
        self.assertEqual(self.broker.submission_count, 0)

    def test_tmf_contract_count_is_frozen_even_when_two_contracts_fit_budget(self):
        spec = next(s for s in self.specs if s.market is Market.INDEX_FUTURE)
        form = replace(
            self.form(allocation=D('60000')), market=spec.market, holding_kind=HoldingKind.INTRADAY, min_days=0, max_days=0, instrument_id=spec.instrument_id
        )
        reference = self.command(UiAction.CREATE_TYPED_STRATEGY, strategy=form, strategy_parameters=self.parameters(bar_interval='5m', contracts=1)).reference
        self.research(reference)
        self.command(UiAction.DEPLOY, target_id=reference)
        record = self.engine.strategy(reference)
        now = self.clock.now()
        plan = OrderPlan(
            'two-tmf',
            'test-stock',
            Environment.LOCAL,
            spec.instrument_id,
            record.strategy_id,
            record.version,
            Side.BUY,
            2,
            spec.unit,
            D('20000'),
            D('19990'),
            False,
            now,
            now + timedelta(seconds=30),
            self.engine.state.version,
        )
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(plan, record.policy, 'two-tmf')
        self.assertEqual(rejected.exception.code, 'strategy_size_insufficient')
        self.assertEqual(self.broker.submission_count, 0)

    def test_live_typed_entry_never_reaches_broker(self):
        reference = self.deploy()
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE, live_execution_enabled=True)
        plan = self.plan(reference)
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(plan, self.engine.strategy(reference).policy, 'live-entry')
        self.assertEqual(rejected.exception.code, 'production_orders_disabled')
        self.assertEqual(self.broker.submission_count, 0)


if __name__ == '__main__':
    unittest.main()
