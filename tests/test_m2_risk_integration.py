"""M2 account/preflight admission through the real engine and in-memory exchange."""

from dataclasses import replace
from decimal import Decimal
import json
import unittest
from unittest.mock import Mock, patch

import test_m2_strategy_management as fixtures
from quantlab.trading.application.account_risk import account_entry_rejection, account_position_count, assert_account_resume, observe_account_limits
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import StrategyForm, StrategyParameters, UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import poll_events
from quantlab.trading.application.manual_book import ManualBook
from quantlab.trading.application.preflight import PreflightFacts, record_preflight
from quantlab.trading.domain.models import Environment, HoldingKind, OrderStatus, PositionLot, Side
from quantlab.trading.domain.risk import AccountRiskLimits
from quantlab.trading.domain.validation import DomainError

D = Decimal


class AccountRiskIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Compose the fixture; importing its TestCase into this module's globals
        # would silently execute the complete base suite a second time.
        self.case = fixtures.StrategyManagementTests()
        self.case.setUp()
        self.engine, self.facade, self.broker = self.case.engine, self.case.facade, self.case.broker

    def limits(self, **changes):
        value = replace(AccountRiskLimits('test-stock'), **changes)
        self.case.command(UiAction.SAVE_ACCOUNT_RISK, account_ref='test-stock', account_risk=value)
        return value

    def historical_loss(self, amount, *, strategy_id='retired-owner'):
        lot = PositionLot(
            'recorded-closed-lot',
            'test-stock',
            'TWSE:2330',
            strategy_id,
            1,
            self.engine.state.strategies[0].policy,
            0,
            D('10'),
            self.engine.state.trading_day,
            0,
            realized_pnl=-amount,
        )
        self.engine._persist('recorded_prior_fill_history_fixture', replace(self.engine.state, positions=(lot,)))

    def assert_entry_rejected(self, reference, code, *, quantity=1000, key='denied'):
        plan = self.case.plan(reference, quantity=quantity, key=key)
        before = self.broker.submission_count
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(plan, self.engine.strategy(reference).policy, key)
        self.assertEqual(rejected.exception.code, code)
        self.assertEqual(self.broker.submission_count, before)
        return rejected.exception

    def test_default_daily_loss_is_three_percent_of_this_accounts_sixty_thousand(self):
        reference = self.case.deploy()
        self.historical_loss(D('1800'))
        self.assert_entry_rejected(reference, 'account_daily_loss_limit')
        self.assertIn(('test-stock', self.engine.state.trading_day), self.engine.state.account_daily_locks)
        self.assertTrue(self.engine.state.stopped)
        view = self.facade.snapshot().account_risks[0]
        self.assertEqual((view.daily_loss_limit, view.daily_pnl), (D('1800'), D('-1800')))

    def test_loss_one_cent_below_boundary_still_allows_an_actual_entry(self):
        reference = self.case.deploy()
        self.historical_loss(D('1799.99'))
        order_id = self.case.submit(reference)
        self.assertEqual(self.broker.submission_count, 1)
        self.assertEqual(next(order for order in self.engine.state.orders if order.order_id == order_id).status, OrderStatus.ACCEPTED)
        self.assertEqual(self.engine.state.account_daily_locks, ())

    def test_order_notional_exact_cap_is_accepted_and_above_cap_stops_the_port(self):
        reference = self.case.deploy(allocation=D('30000'))
        self.limits(max_order_notional=D('10000'))
        self.case.submit(reference, key='at-cap')
        self.assertEqual(self.broker.submission_count, 1)
        self.assert_entry_rejected(reference, 'account_order_limit', quantity=2000, key='above-cap')
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('account_order_limit', self.engine.state.issues)

    def test_pending_entry_takes_a_position_slot_before_the_first_fill(self):
        first = self.case.deploy(allocation=D('30000'))
        second = self.case.deploy('TWSE:DEMO01', allocation=D('30000'))
        self.limits(max_positions=1)
        self.case.submit(first)
        self.assertEqual(self.engine.state.positions, ())
        self.assert_entry_rejected(second, 'account_position_limit')

    def test_unknown_and_cancel_pending_entries_retain_their_position_slot(self):
        first = self.case.deploy(allocation=D('30000'))
        second = self.case.deploy('TWSE:DEMO01', allocation=D('30000'))
        self.limits(max_positions=1)
        order_id = self.case.submit(first)
        order = next(row for row in self.engine.state.orders if row.order_id == order_id)
        for status in (OrderStatus.UNKNOWN, OrderStatus.CANCEL_PENDING, OrderStatus.SUBMITTING, OrderStatus.PARTIALLY_FILLED):
            with self.subTest(status=status):
                self.engine._persist('pending_status_fixture', replace(self.engine.state, orders=(replace(order, status=status),)))
                self.assertEqual(account_position_count(self.engine, 'test-stock'), 1)
                self.assertEqual(account_entry_rejection(self.engine, self.case.plan(second)), 'account_position_limit')

    def test_position_slots_include_other_owners_but_do_not_double_count_the_same_scope(self):
        reference = self.case.deploy()
        order_id = self.case.submit(reference)
        self.broker.fill(order_id, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        lot = self.engine.state.positions[0]
        same_scope = replace(lot, lot_id='other-owner-same-product', strategy_id='other-owner')
        other_scope = replace(lot, lot_id='manual-other-product', strategy_id='manual-owner', instrument_id='TWSE:DEMO01')
        self.engine._persist('multiple_owned_lots_fixture', replace(self.engine.state, positions=(lot, same_scope, other_scope)))
        self.assertEqual(account_position_count(self.engine, 'test-stock'), 2)

    def test_legal_reduction_ignores_new_entry_caps_and_failed_preflight(self):
        reference = self.case.deploy()
        order_id = self.case.submit(reference)
        self.broker.fill(order_id, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        lot = self.engine.state.positions[0]
        self.limits(max_order_notional=D('1'), max_positions=1)
        record_preflight(self.engine, 'test-stock', PreflightFacts(False, True, True, None, True, True, True))
        self.engine._persist(
            'daily_loss_latch_fixture',
            replace(self.engine.state, account_daily_locks=(('test-stock', self.engine.state.trading_day),), stopped=True),
        )
        exit_id = self.engine.exit_lot(lot.lot_id, protective=True)
        self.assertIsNotNone(exit_id)
        exit_order = next(row for row in self.engine.state.orders if row.order_id == exit_id)
        self.assertTrue(exit_order.plan.reduce_only)
        self.assertEqual(exit_order.status, OrderStatus.ACCEPTED)
        self.assertEqual(self.broker.submission_count, 2)

    def test_stop_new_cancels_pending_entries_and_preserves_accepted_protective_exit(self):
        first = self.case.deploy(allocation=D('30000'))
        second = self.case.deploy('TWSE:DEMO01', allocation=D('30000'))
        entry_id = self.case.submit(first)
        self.broker.fill(entry_id, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        exit_id = self.engine.exit_lot(self.engine.state.positions[0].lot_id, protective=True)
        pending_id = self.case.submit(second, key='pending-entry')
        self.case.command(UiAction.STOP_NEW)
        orders = {row.order_id: row for row in self.engine.state.orders}
        self.assertEqual(orders[pending_id].status, OrderStatus.CANCELED)
        self.assertEqual(orders[exit_id].status, OrderStatus.ACCEPTED)
        self.assertTrue(self.engine.state.stopped)

    def test_stop_new_with_manual_books_still_cancels_only_entries(self):
        first = self.case.deploy(allocation=D('30000'))
        second = self.case.deploy('TWSE:DEMO01', allocation=D('30000'))
        entry_id = self.case.submit(first)
        self.broker.fill(entry_id, 1000, D('10'), fee=D('0'))
        poll_events(self.engine)
        exit_id = self.engine.exit_lot(self.engine.state.positions[0].lot_id, protective=True)
        pending_id = self.case.submit(second, key='pending-entry')
        book = ManualBook('manual-book-fixture', 'test-stock', D('60000'), self.engine.state.trading_day)
        self.engine._persist('manual_book_fixture', replace(self.engine.state, manual_books=(book,)))
        self.case.command(UiAction.STOP_NEW)
        self.assertEqual(self.broker.remote_state.orders[pending_id].status, OrderStatus.CANCELED)
        self.assertEqual(self.broker.remote_state.orders[exit_id].status, OrderStatus.ACCEPTED)
        self.assertTrue(self.engine.state.manual_books[0].halted)

    def test_missing_preflight_blocks_actual_entry_even_when_global_state_is_running(self):
        reference = self.case.deploy()
        self.engine._persist('missing_preflight_fixture', replace(self.engine.state, preflight=()))
        self.assertFalse(self.engine.state.stopped)
        self.assert_entry_rejected(reference, 'preflight_blocked')
        self.assertTrue(self.engine.state.stopped)

    def test_a_preview_through_the_facade_changes_nothing_and_leaves_the_day_open(self):
        import quantlab.trading.runtime.protocol  # noqa: F401  (registers the wire types)
        from quantlab.trading.domain.models import Quote

        self.case.deploy()
        self.engine.quotes.clear()
        before = self.engine.state
        # A stale version is accepted: the preview writes nothing, so there is nothing to conflict with.
        receipt = self.facade.execute(UiCommand(UiAction.PREVIEW_PREFLIGHT, before.version - 1, account_ref='test-stock'))
        self.assertTrue(receipt.accepted)
        self.assertTrue(receipt.preflight.blocked_today)
        self.assertIn('preflight_market', receipt.preflight.block_reasons)
        self.assertEqual(loads(dumps(receipt)), receipt)
        self.assertEqual(self.engine.state, before)  # no version, no stop, no row, no day latch
        now = self.engine.clock.now()
        self.engine.quotes['TWSE:2330'] = Quote('TWSE:2330', D('9.95'), D('10'), D('10'), now, now, self.engine.state.trading_day)
        self.case.command(UiAction.CHECK_PREFLIGHT, account_ref='test-stock')
        self.assertFalse(self.engine.state.preflight[0].blocked_today)
        self.assertEqual(self.engine.state.preflight_blocks, ())

    def test_failed_preflight_is_latched_for_the_day_after_a_successful_recheck(self):
        reference = self.case.deploy()
        self.engine.quotes.clear()
        self.case.command(UiAction.CHECK_PREFLIGHT, account_ref='test-stock')
        # Restore the exact verified decision quote, not historical/future market data.
        from quantlab.trading.domain.models import Quote

        now = self.engine.clock.now()
        self.engine.quotes['TWSE:2330'] = Quote('TWSE:2330', D('9.95'), D('10'), D('10'), now, now, self.engine.state.trading_day)
        self.case.command(UiAction.CHECK_PREFLIGHT, account_ref='test-stock')
        view = self.engine.state.preflight[0]
        self.assertTrue(view.blocked_today)
        self.assertIn('preflight_market', view.block_reasons)
        self.assertTrue(all(row.state in ('PASS', 'NOT_REQUIRED') for row in view.checks))
        self.engine._persist('global_resume_does_not_clear_daily_latch_fixture', replace(self.engine.state, stopped=False, issues=()))
        self.assert_entry_rejected(reference, 'preflight_blocked')

    def test_failed_preflight_view_alone_denies_actual_entry(self):
        reference = self.case.deploy()
        record_preflight(self.engine, 'test-stock', PreflightFacts(False, True, True, None, True, True, True))
        self.engine._persist('isolated_failed_view_guard_fixture', replace(self.engine.state, preflight_blocks=(), stopped=False, issues=()))
        self.assert_entry_rejected(reference, 'preflight_blocked')

    def test_durable_preflight_block_alone_denies_actual_entry(self):
        reference = self.case.deploy()
        self.engine._persist(
            'isolated_daily_preflight_latch_fixture',
            replace(self.engine.state, preflight_blocks=(('test-stock', self.engine.state.trading_day),), stopped=False),
        )
        self.assertFalse(self.engine.state.preflight[0].blocked_today)
        self.assert_entry_rejected(reference, 'preflight_blocked')

    def test_global_resume_checks_passed_preflight_again(self):
        self.case.deploy()
        self.engine._persist('missing_preflight_for_resume_fixture', replace(self.engine.state, stopped=True, preflight=()))
        result = self.case.command(UiAction.RESUME, accepted=False)
        self.assertEqual(result.code, 'preflight_blocked')
        self.assertTrue(self.engine.state.stopped)

    def test_healthy_local_typed_day_step_collects_new_day_preflight_and_remains_accepted(self):
        from quantlab.trading.application.codec import register
        from quantlab.trading.runtime.build import RemoteImage, RemoteImages, SimulationClock, SimulationControl

        register(RemoteImage, RemoteImages)
        clock = SimulationClock(self.engine.clock.now())
        self.case.clock = self.engine.clock = self.broker.clock = clock
        self.engine.simulation = SimulationControl(clock, self.engine.gateways, fixtures.GuardJournal())
        self.case.deploy(allocation=D('30000'), entry_amount=D('10000'))
        before = self.engine.state.trading_day
        receipt = self.facade.execute(UiCommand(UiAction.STEP, self.engine.state.version))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.engine.state.trading_day, self.engine.calendar.advance(before, 1))
        view = next(row for row in self.engine.state.preflight if row.account_ref == 'test-stock')
        self.assertEqual(view.trade_date, self.engine.state.trading_day)
        self.assertFalse(view.blocked_today)
        self.assertTrue(all(row.state in ('PASS', 'NOT_REQUIRED') for row in view.checks))

    def test_changing_limits_never_resets_a_daily_loss_lock(self):
        self.case.deploy()
        self.historical_loss(D('1800'))
        observe_account_limits(self.engine)
        locks, baseline = self.engine.state.account_daily_locks, self.engine.state.account_daily_baselines
        self.limits(daily_loss_fraction=D('.50'))
        self.case.command(
            UiAction.SAVE_SETTINGS,
            settings=replace(self.engine.state.settings, stock_allocation=D('70000'), futures_allocation=D('30000')),
        )
        self.assertEqual(self.engine.state.account_daily_locks, locks)
        self.assertEqual(self.engine.state.account_daily_baselines, baseline)
        with self.assertRaises(DomainError) as rejected:
            assert_account_resume(self.engine)
        self.assertEqual(rejected.exception.code, 'account_daily_loss_limit')

    def test_global_resume_cannot_clear_a_recovered_but_latched_account(self):
        self.case.deploy()
        self.engine._persist(
            'daily_loss_recovered_but_latched_fixture',
            replace(self.engine.state, account_daily_locks=(('test-stock', self.engine.state.trading_day),), stopped=True, issues=()),
        )
        result = self.case.command(UiAction.RESUME, accepted=False)
        self.assertEqual(result.code, 'account_daily_loss_limit')
        self.assertTrue(self.engine.state.stopped)

    def test_recovered_profit_cannot_clear_the_direct_account_entry_latch(self):
        reference = self.case.deploy()
        self.engine._persist(
            'recovered_account_entry_latch_fixture',
            replace(self.engine.state, account_daily_locks=(('test-stock', self.engine.state.trading_day),)),
        )
        self.assertEqual(account_entry_rejection(self.engine, self.case.plan(reference)), 'account_daily_loss_limit')

    def test_other_adopted_account_loss_is_observed_before_a_healthy_accounts_entry(self):
        reference = self.case.deploy()
        other_account = replace(fixtures.account(), account_ref='other-futures')
        other_capability = replace(fixtures.capability(), account_ref='other-futures')
        other = fixtures.SimulatedBroker(self.engine.clock, other_account, self.case.specs, other_capability, fee_schedule=self.engine.fees)
        self.engine.gateways['other-futures'] = other
        self.engine.configuration = replace(self.engine.configuration, futures_account_ref='other-futures')
        self.engine.create_strategy(
            replace(
                self.case.form(),
                market=fixtures.Market.INDEX_FUTURE,
                holding_kind=HoldingKind.CUSTOM,
                min_days=0,
                max_days=0,
                instrument_id='TAIFEX:TMF:202612',
                account_ref='other-futures',
            ),
            self.case.parameters(),
        )
        lot = PositionLot(
            'other-account-closed-lot',
            'other-futures',
            'TAIFEX:TMF:202612',
            'retired-other-owner',
            1,
            self.engine.state.strategies[-1].policy,
            0,
            D('20000'),
            self.engine.state.trading_day,
            0,
            realized_pnl=D('-1200'),
        )
        self.engine._persist('other_account_realized_loss_fixture', replace(self.engine.state, positions=(lot,)))
        plan = self.case.plan(reference)
        with self.assertRaises(DomainError):
            self.engine.submit(plan, self.engine.strategy(reference).policy, plan.plan_id)
        self.assertIn(('other-futures', self.engine.state.trading_day), self.engine.state.account_daily_locks)
        self.assertTrue(self.engine.state.stopped)
        self.assertEqual(self.broker.submission_count, 0)

    def test_missing_account_baseline_halts_before_an_actual_order_can_reach_the_port(self):
        reference = self.case.deploy()
        self.engine._persist('missing_daily_close_fixture', replace(self.engine.state, account_daily_baselines=()))
        self.assert_entry_rejected(reference, 'account_daily_baseline_required')
        self.assertTrue(self.engine.state.stopped)

    def test_typed_adoption_cannot_be_bypassed_by_a_legacy_strategy_entry(self):
        typed = self.case.create()
        self.case.command(UiAction.DELETE_STRATEGY, target_id=typed)
        legacy = self.case.command(UiAction.CREATE_STRATEGY, strategy=self.case.form()).reference
        self.case.research(legacy)
        self.case.command(UiAction.DEPLOY, target_id=legacy)
        self.historical_loss(D('1800'))
        self.assertEqual(self.engine.state.account_risk_limits, ())
        self.assert_entry_rejected(legacy, 'account_daily_loss_limit')

    def test_restart_preserves_risk_baselines_loss_and_preflight_latches_and_stays_stopped(self):
        self.case.deploy()
        self.historical_loss(D('1800'))
        observe_account_limits(self.engine)
        record_preflight(self.engine, 'test-stock', PreflightFacts(False, True, True, None, True, True, True))
        before = self.engine.state
        restarted = TradingEngine(
            self.engine.journal,
            self.engine.clock,
            self.engine.calendar,
            self.engine.catalog,
            self.engine.gateways,
            configuration=self.engine.configuration,
            ownership_clock=self.engine.ownership_clock,
            source_profile=self.engine.profile,
            fees=self.engine.fees,
        )
        for field in ('account_risk_limits', 'account_daily_baselines', 'account_daily_locks', 'preflight', 'preflight_blocks'):
            self.assertEqual(getattr(restarted.state, field), getattr(before, field))
        self.assertTrue(restarted.state.stopped)
        self.assertFalse(restarted.state.reconciled)
        self.assertEqual(self.broker.submission_count, 0)

    def test_old_wire_state_additive_defaults_do_not_fabricate_admission_evidence(self):
        payload = json.loads(dumps(self.engine.state))
        for field in ('account_risk_limits', 'account_daily_baselines', 'account_daily_locks', 'preflight', 'preflight_blocks'):
            del payload['fields'][field]
        restored = loads(json.dumps(payload))
        self.assertEqual(restored.account_risk_limits, ())
        self.assertEqual(restored.account_daily_baselines, ())
        self.assertEqual(restored.preflight, ())
        self.assertEqual(restored.preflight_blocks, ())

    def test_risk_and_preflight_dtos_roundtrip_and_unknown_baseline_stays_unknown(self):
        self.case.create()
        self.engine._persist('unknown_close_fixture', replace(self.engine.state, account_daily_baselines=()))
        view = self.facade.snapshot()
        self.assertEqual(loads(dumps(view)), view)
        risk = view.account_risks[0]
        self.assertEqual(risk.daily_loss_limit, D('1800'))
        self.assertIsNone(risk.daily_pnl)
        self.assertIn('account_daily_baseline_required', risk.reasons)
        self.assertTrue(view.preflight[0].keep_awake_reminder)

    def test_simulation_virtual_risk_views_do_not_claim_verified_broker_financials(self):
        self.case.create()
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.BROKER_SIMULATION)
        self.engine._persist('simulation_monitoring_fixture', replace(self.engine.state, environment=Environment.BROKER_SIMULATION))
        view = self.facade.snapshot()
        self.assertFalse(view.financial_facts_verified)
        self.assertIsNone(view.daily_pnl)
        self.assertIsNone(view.remaining_risk)
        self.assertEqual(view.account_risks[0].daily_loss_limit, D('1800'))

    def test_live_cannot_reach_the_port_through_new_settings_preflight_stop_or_entry_routes(self):
        reference = self.case.deploy()
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE, live_execution_enabled=True)
        self.engine._persist('historical_live_monitoring_fixture', replace(self.engine.state, environment=Environment.LIVE))
        with (
            patch.object(self.broker, 'submit', Mock(side_effect=AssertionError('LIVE submit reached port'))),
            patch.object(self.broker, 'cancel', Mock(side_effect=AssertionError('LIVE cancel reached port'))),
        ):
            for action, fields in (
                (UiAction.CHECK_PREFLIGHT, {'account_ref': 'test-stock'}),
                (UiAction.SAVE_ACCOUNT_RISK, {'account_risk': AccountRiskLimits('test-stock')}),
                (UiAction.STOP_NEW, {}),
                (UiAction.RESUME, {}),
                (UiAction.FLATTEN, {'target_id': 'absent-owned-lot'}),
            ):
                with self.subTest(action=action):
                    self.facade.execute(UiCommand(action, self.engine.state.version, **fields))
            plan = replace(self.case.plan(reference), environment=Environment.LIVE)
            with self.assertRaises(DomainError) as rejected:
                self.engine.submit(plan, self.engine.strategy(reference).policy, 'live-entry')
            self.assertEqual(rejected.exception.code, 'production_orders_disabled')
            self.broker.submit.assert_not_called()
            self.broker.cancel.assert_not_called()


class ManualResumeAccountRiskTests(unittest.TestCase):
    def test_explicit_account_risk_limits_alone_block_manual_orders_before_the_sdk(self):
        import test_manual_trading as manual
        from quantlab.trading.application.account_risk import m2_account_refs
        from quantlab.trading.application.facade import LocalFacade

        case = manual.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        case.confirm_test()
        receipt = LocalFacade(case.engine).execute(
            UiCommand(
                UiAction.SAVE_ACCOUNT_RISK,
                case.engine.state.version,
                account_ref='future-alias',
                account_risk=AccountRiskLimits('future-alias', max_order_notional=D('1')),
            )
        )
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(case.engine.state.strategies, ())
        self.assertIn('future-alias', m2_account_refs(case.engine))
        self.assertTrue(any(row.account_ref == 'future-alias' for row in case.engine.state.account_daily_baselines))
        before = sum(row[0] == 'place_order' for row in case.native._seen)
        form, _ = case.normal('after-explicit-account-risk')
        submitted = case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertFalse(submitted.accepted)
        self.assertEqual(submitted.code, 'account_order_limit')
        self.assertEqual(sum(row[0] == 'place_order' for row in case.native._seen), before)

    def test_confirmed_manual_resume_cannot_clear_an_adopted_account_daily_lock(self):
        import test_manual_trading as manual
        from quantlab.trading.application.manual_contracts import ManualBookForm

        case = manual.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        case.confirm_test()
        form = StrategyForm(
            'adopted-virtual-account',
            case.spec.market,
            HoldingKind.CUSTOM,
            0,
            0,
            Side.BUY,
            case.spec.instrument_id,
            'future-alias',
            Environment.BROKER_SIMULATION,
            D('40000'),
            D('.02'),
            'BUY_AND_HOLD',
        )
        case.engine.create_strategy(form, StrategyParameters('1d', D('.01'), D('40000')))
        case.engine._persist(
            'account_loss_latch_fixture',
            replace(case.engine.state, account_daily_locks=(('future-alias', case.engine.state.trading_day),), stopped=True),
        )
        receipt = case.service.execute(case.command(UiAction.RESUME, manual_book=ManualBookForm(case.scope, D('40000'), True)))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'account_daily_loss_limit')
        self.assertTrue(case.engine.state.stopped)
        self.assertIn(('future-alias', case.engine.state.trading_day), case.engine.state.account_daily_locks)


if __name__ == '__main__':
    unittest.main()
