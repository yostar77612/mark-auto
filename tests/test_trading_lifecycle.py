"""Durable company-action and two-filled-leg futures lifecycle behavior."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch

import test_trading_application as support
from quantlab.trading.adapters.simulated.broker import FaultPlan
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.lifecycle import recover_corporate_actions, run_lifecycle, schedule_corporate_action
from quantlab.trading.application.workflows import fill_local_pending, step
from quantlab.trading.domain.lifecycle import CorporateAction
from quantlab.trading.domain.models import HoldingKind, Market, OrderStatus
from quantlab.trading.domain.validation import DomainError


D = Decimal


class DurableLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        # Compose the common application fixture without inheriting/rerunning its
        # acceptance tests or copying any implementation into this test module.
        self.fixture = support.ApplicationLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    @property
    def engine(self):
        return self.fixture.engine

    def stock_position(self):
        reference = self.fixture.deploy()
        self.fixture.submit(reference)
        fill_local_pending(self.engine)
        return self.engine.state.positions[0]

    def action(self, *, ratio=D('2'), cash=D('0')):
        old = self.engine.catalog.resolve('TWSE:2330')
        effective = self.engine.calendar.day_session(self.engine.state.trading_day).opens_at
        new = replace(old, version='corp-spec-v2', corporate_action_version='corp-action-v2', tick_size=old.tick_size / ratio, effective_at=effective)
        payable = self.engine.calendar.advance(self.engine.state.trading_day, 2) if cash else None
        action = CorporateAction('known-local-action', old.version, new.version, effective, ratio, cash, payable, 'LOCAL_SYNTHETIC_ACTION')
        return old, new, action

    def roll_position(self, market=Market.INDEX_FUTURE):
        reference = self.fixture.deploy(market, max_days=100, kind=HoldingKind.POSITION)
        source = self.engine.strategy(reference)
        target = next(s for s in self.engine.catalog.instruments if s.market is market and s.delivery_month == '202703')
        form = replace(source.form, parent_strategy_id=source.strategy_id, expiry_action='ROLL', roll_contract_id=target.instrument_id)
        reference = self.fixture.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            self.fixture.command(action, target_id=reference)
        plan = self.fixture.order_plan(reference)
        plan = replace(plan, stop_price=plan.limit_price - (D('100') if market is Market.INDEX_FUTURE else D('0.70')))
        self.engine.submit(plan, self.engine.strategy(reference).policy, 'expiry-owned-entry')
        fill_local_pending(self.engine)
        original = self.engine.state.positions[0]
        while self.engine.state.trading_day < date(2026, 12, 15):
            step(self.engine, self.engine.history)
        self.fixture.command(UiAction.RESUME)
        return original, target

    def drive_roll(self) -> None:
        for _ in range(3):
            run_lifecycle(self.engine)
            fill_local_pending(self.engine)

    def test_split_updates_position_spec_stop_and_risk_without_rewriting_original_order(self) -> None:
        original = self.stock_position()
        original_plan = self.engine.state.orders[0].plan
        _, new, action = self.action()
        job_id = schedule_corporate_action(self.engine, original.instrument_id, new, action)
        after = self.engine.state.positions[0]
        self.assertEqual(after.quantity, original.quantity * 2)
        self.assertEqual(after.entry_price, original.entry_price / 2)
        self.assertEqual(after.policy, original.policy)
        self.assertEqual(self.engine.state.orders[0].plan, original_plan)
        self.assertEqual(dict(self.engine.state.protection_stops)[original.lot_id], original_plan.stop_price / 2)
        self.assertEqual(self.engine.catalog.resolve(original.instrument_id), new)
        self.assertEqual(self.engine.state.corporate_actions[0].status, 'APPLIED')
        state = self.engine.state
        self.assertEqual(schedule_corporate_action(self.engine, original.instrument_id, new, action), job_id)
        self.assertEqual(self.engine.state, state)
        self.fixture.restart()
        self.fixture.command(UiAction.RECONCILE)
        self.assertEqual(self.engine.catalog.resolve(original.instrument_id), new)
        self.assertEqual(self.engine.state.positions[0].quantity, 2000)

    def test_dividend_is_receivable_until_payday_and_not_duplicate_on_retry(self) -> None:
        original = self.stock_position()
        before = self.engine.gateways[original.account_ref].snapshot(original.account_ref)
        _, new, action = self.action(ratio=D('1'), cash=D('2'))
        schedule_corporate_action(self.engine, original.instrument_id, new, action)
        account = self.engine.gateways[original.account_ref].snapshot(original.account_ref)
        self.assertEqual(account.settled_cash, before.settled_cash)
        self.assertEqual(account.unsettled_receivables - before.unsettled_receivables, D('2000'))
        schedule_corporate_action(self.engine, original.instrument_id, new, action)
        self.assertEqual(self.engine.gateways[original.account_ref].snapshot(original.account_ref), account)
        for _ in range(2):
            step(self.engine, self.engine.history)
        paid = self.engine.gateways[original.account_ref].snapshot(original.account_ref)
        self.assertEqual(paid.unsettled_receivables, 0)
        self.assertEqual(paid.settled_cash, before.settled_cash + D('2000'))

    def test_corporate_action_with_pending_order_freezes_before_any_remote_change(self) -> None:
        self.stock_position()
        reference = self.engine.state.strategies[0].strategy_id
        self.fixture.submit(reference, key='pending-entry')
        _, new, action = self.action()
        with self.assertRaises(DomainError):
            schedule_corporate_action(self.engine, new.instrument_id, new, action)
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.engine.state.corporate_actions)
        self.assertEqual(self.engine.state.positions[0].quantity, 1000)

    def test_future_multiplier_action_rebuilds_margin_stop_and_economic_basis(self) -> None:
        reference = self.fixture.deploy(Market.STOCK_FUTURE)
        self.fixture.submit(reference)
        fill_local_pending(self.engine)
        lot = self.engine.state.positions[0]
        old = self.engine.catalog.resolve(lot.instrument_id)
        new = replace(
            old,
            multiplier=old.multiplier * 2,
            tick_size=old.tick_size / 2,
            margin=D('30000'),
            version='adjusted-v2',
            corporate_action_version='multiplier-v2',
            effective_at=self.engine.calendar.day_session(self.engine.state.trading_day).opens_at,
        )
        action = CorporateAction('future-multiplier-action', old.version, new.version, new.effective_at, D('1'), D('0'), None, 'LOCAL_SYNTHETIC_ACTION')
        schedule_corporate_action(self.engine, lot.instrument_id, new, action)
        adjusted = next(p for p in self.engine.state.positions if p.lot_id == lot.lot_id)
        self.assertEqual(adjusted.entry_price * new.multiplier, lot.entry_price * old.multiplier)
        self.assertEqual(self.engine.gateways[lot.account_ref].snapshot(lot.account_ref).margin_used, D('30000'))
        self.assertEqual(adjusted.risk_entry_price, adjusted.entry_price)
        self.assertEqual(self.engine.catalog.resolve(lot.instrument_id), new)

    def test_rebuild_failure_after_confirm_cannot_demote_or_double_recognize_dividend(self) -> None:
        self.stock_position()
        _, new, action = self.action(ratio=D('1'), cash=D('2'))
        before_pnl = self.engine.state.realized_pnl
        with patch.object(self.engine.simulation, 'rebuild_history', side_effect=DomainError('stale_quote')):
            with self.assertRaises(DomainError):
                schedule_corporate_action(self.engine, new.instrument_id, new, action)
        self.assertEqual(self.engine.state.corporate_actions[0].status, 'APPLIED')
        recover_corporate_actions(self.engine)
        self.assertEqual(self.engine.state.realized_pnl, before_pnl + D('2000'))
        self.assertEqual(self.engine.gateways['local-stock'].snapshot('local-stock').unsettled_receivables, D('2000'))

    def test_unknown_action_is_not_blindly_replayed(self) -> None:
        self.stock_position()
        _, new, action = self.action()
        with patch.object(self.engine.simulation, 'apply_corporate_action', side_effect=DomainError('outcome_unknown')) as remote:
            with self.assertRaises(DomainError):
                schedule_corporate_action(self.engine, new.instrument_id, new, action)
            recover_corporate_actions(self.engine)
            self.assertEqual(remote.call_count, 1)
        self.assertEqual(self.engine.state.corporate_actions[0].status, 'UNKNOWN')
        self.assertEqual(self.engine.state.positions[0].quantity, 1000)
        self.assertTrue(self.engine.state.stopped)

    def test_action_remote_applied_then_journal_failure_recovers_without_second_application(self) -> None:
        self.stock_position()
        _, new, action = self.action()
        append = self.engine.journal.append

        def fail_confirmation(kind, *args, **kwargs):
            if kind == 'corporate_action_confirmed':
                raise OSError('simulated crash after external application')
            return append(kind, *args, **kwargs)

        with patch.object(self.engine.journal, 'append', fail_confirmation), self.assertRaises(DomainError):
            schedule_corporate_action(self.engine, new.instrument_id, new, action)
        self.assertEqual(self.engine.state.positions[0].quantity, 1000)
        self.assertTrue(self.engine.simulation.corporate_action_applied(action.action_id, 'local-stock'))
        self.fixture.restart()
        recover_corporate_actions(self.engine)
        self.fixture.command(UiAction.RECONCILE)
        self.assertEqual(self.engine.state.positions[0].quantity, 2000)
        self.assertEqual(self.engine.state.corporate_actions[0].status, 'APPLIED')

    def test_index_future_roll_has_two_filled_legs_and_new_researched_version(self) -> None:
        original, target = self.roll_position()
        before_cost = self.engine.state.costs
        self.drive_roll()
        job = self.engine.state.rolls[0]
        self.assertEqual(job.status, 'COMPLETED')
        close = next(o for o in self.engine.state.orders if o.order_id == job.close_order_id)
        opened = next(o for o in self.engine.state.orders if o.order_id == job.open_order_id)
        self.assertEqual(close.status, OrderStatus.FILLED)
        self.assertEqual(opened.status, OrderStatus.FILLED)
        self.assertTrue(close.plan.reduce_only)
        self.assertFalse(opened.plan.reduce_only)
        self.assertEqual(close.plan.instrument_id, original.instrument_id)
        self.assertEqual(opened.plan.instrument_id, target.instrument_id)
        self.assertNotEqual(opened.plan.strategy_version, original.strategy_version)
        self.assertGreater(close.costs, 0)
        self.assertGreater(opened.costs, 0)
        self.assertEqual(self.engine.state.costs - before_cost, close.costs + opened.costs)
        self.assertEqual(next(p for p in self.engine.state.positions if p.lot_id == original.lot_id).policy, original.policy)
        successor = self.engine.strategy(job.destination_strategy_ref)
        self.assertTrue(successor.evidence_hash)
        self.assertEqual(successor.form.expiry_action, 'ROLL')
        self.assertEqual(successor.form.roll_contract_id, '')
        new_lot = next(p for p in self.engine.state.positions if p.lot_id == opened.order_id)
        self.assertEqual(new_lot.entry_trade_date, self.engine.state.trading_day)
        self.assertEqual(new_lot.holding_origin, original.holding_origin)

    def test_stock_future_roll_uses_same_application_and_preserves_real_contract_identity(self) -> None:
        original, target = self.roll_position(Market.STOCK_FUTURE)
        self.drive_roll()
        job = self.engine.state.rolls[0]
        self.assertEqual(job.status, 'COMPLETED')
        close = next(o for o in self.engine.state.orders if o.order_id == job.close_order_id)
        opened = next(o for o in self.engine.state.orders if o.order_id == job.open_order_id)
        self.assertEqual((close.plan.instrument_id, opened.plan.instrument_id), (original.instrument_id, target.instrument_id))
        self.assertGreater(close.costs, 0)
        self.assertGreater(opened.costs, 0)
        self.assertEqual(next(p for p in self.engine.state.positions if p.quantity).instrument_id, target.instrument_id)

    def test_roll_never_opens_next_contract_before_old_leg_actual_fill(self) -> None:
        _, target = self.roll_position()
        run_lifecycle(self.engine)
        self.assertEqual(len(self.engine.state.rolls), 1)
        self.assertFalse(any(o.plan.instrument_id == target.instrument_id for o in self.engine.state.orders))
        self.assertEqual(self.engine.state.rolls[0].status, 'CLOSE_SUBMITTED')

    def test_unknown_roll_close_survives_restart_and_requires_query_before_progress(self) -> None:
        original, target = self.roll_position()
        self.engine.gateways[original.account_ref].queue_fault(FaultPlan(unknown_after_accept=True))
        run_lifecycle(self.engine)
        self.assertEqual(self.engine.state.rolls[0].status, 'CLOSE_UNKNOWN')
        self.assertFalse(any(o.plan.instrument_id == target.instrument_id for o in self.engine.state.orders))
        self.fixture.restart()
        self.fixture.command(UiAction.RECONCILE)
        self.fixture.command(UiAction.RESUME)
        self.drive_roll()
        self.assertEqual(self.engine.state.rolls[0].status, 'COMPLETED')
        self.assertEqual(len(self.engine.state.orders), 3)

    def test_unknown_roll_open_keeps_old_closed_and_never_blindly_resubmits(self) -> None:
        original, _ = self.roll_position()
        run_lifecycle(self.engine)
        fill_local_pending(self.engine)
        self.engine.gateways[original.account_ref].queue_fault(FaultPlan(unknown_after_accept=True))
        run_lifecycle(self.engine)
        self.assertEqual(self.engine.state.rolls[0].status, 'OPEN_UNKNOWN')
        self.assertEqual(next(p for p in self.engine.state.positions if p.lot_id == original.lot_id).quantity, 0)
        self.fixture.restart()
        self.fixture.command(UiAction.RECONCILE)
        self.fixture.command(UiAction.RESUME)
        self.drive_roll()
        self.assertEqual(self.engine.state.rolls[0].status, 'COMPLETED')
        self.assertEqual(len(self.engine.state.orders), 3)

    def test_crash_after_close_before_open_intent_recovers_same_successor_version(self) -> None:
        self.roll_position()
        run_lifecycle(self.engine)
        fill_local_pending(self.engine)
        append = self.engine.journal.append

        def fail_open_intent(kind, *args, **kwargs):
            if kind == 'roll_open_prepared':
                raise OSError('crash before durable roll open intent')
            return append(kind, *args, **kwargs)

        with patch.object(self.engine.journal, 'append', fail_open_intent):
            run_lifecycle(self.engine)
        self.assertTrue(self.engine.storage_failed)
        versions = len(self.engine.state.strategies)
        self.fixture.restart()
        self.fixture.command(UiAction.RECONCILE)
        self.fixture.command(UiAction.RESUME)
        self.drive_roll()
        self.assertEqual(self.engine.state.rolls[0].status, 'COMPLETED')
        self.assertEqual(len(self.engine.state.strategies), versions)
        self.assertEqual(len(self.engine.state.orders), 3)


if __name__ == '__main__':
    unittest.main()
