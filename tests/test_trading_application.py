"""End-to-end v2 application acceptance against durable local exchange faults."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quantlab.trading.adapters.simulated.broker import FaultPlan
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.contracts import SettingsForm, StrategyForm, UiAction, UiCommand
from quantlab.trading.application.events import poll_events, reconcile
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.workflows import fill_local_pending, mark_risk, step
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerPosition
from quantlab.trading.runtime.build import create_engine


D = Decimal
WORKSPACE = Path(__file__).resolve().parents[2]


class ApplicationLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        (WORKSPACE / 't').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='v2-application-', dir=WORKSPACE / 't')
        self.root = Path(self.temp.name)
        self.engine = create_engine(self.root / 'platform')
        self.facade = LocalFacade(self.engine)
        self.command(UiAction.RECONCILE)
        self.command(UiAction.RESUME)

    def tearDown(self) -> None:
        self.close_engine()
        self.temp.cleanup()

    def close_engine(self) -> None:
        if self.engine is not None:
            self.engine.journal.close()
            self.engine.simulation.ledger.close()
            self.engine = None

    def restart(self) -> None:
        self.close_engine()
        self.engine = create_engine(self.root / 'platform')
        self.facade = LocalFacade(self.engine)

    def command(self, action: UiAction, *, accepted: bool = True, **values: object):
        receipt = self.facade.execute(UiCommand(action, self.engine.state.version, **values))
        self.assertEqual(receipt.accepted, accepted, receipt)
        return receipt

    def deploy(
        self, market: Market = Market.STOCK, *, parent: str = '', max_days: int = 5, kind: HoldingKind = HoldingKind.SWING, direction: Side = Side.BUY
    ) -> str:
        spec = next(s for s in self.engine.catalog.instruments if s.market is market)
        account = 'local-stock' if market is Market.STOCK else 'local-futures'
        form = StrategyForm(
            'acceptance-' + market.value,
            market,
            kind,
            0 if kind is HoldingKind.INTRADAY else 3,
            max_days,
            direction,
            spec.instrument_id,
            account,
            Environment.LOCAL,
            D('30000'),
            D('0.02'),
            'BUY_AND_HOLD',
            parent,
        )
        reference = self.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        self.command(UiAction.VALIDATE, target_id=reference)
        self.command(UiAction.RESEARCH, target_id=reference)
        self.command(UiAction.DEPLOY, target_id=reference)
        return reference

    def order_plan(self, reference: str, *, quantity: int | None = None, name: str = 'entry') -> OrderPlan:
        record = self.engine.strategy(reference)
        spec = self.engine.catalog.resolve(record.form.instrument_id)
        quote = self.engine.quotes[spec.instrument_id]
        price = quote.ask if record.form.direction is Side.BUY else quote.bid
        sign = 1 if record.form.direction is Side.BUY else -1
        return OrderPlan(
            name,
            record.form.account_ref,
            Environment.LOCAL,
            spec.instrument_id,
            record.strategy_id,
            record.version,
            record.form.direction,
            quantity or spec.lot_size,
            spec.unit,
            price,
            price - spec.tick_size * 10 * sign,
            False,
            self.engine.clock.now(),
            self.engine.clock.now() + timedelta(seconds=30),
            self.engine.state.version,
        )

    def submit(self, reference: str, *, fault: FaultPlan | None = None, quantity: int | None = None, key: str = 'entry') -> tuple[str, OrderPlan]:
        plan = self.order_plan(reference, quantity=quantity, name=key)
        if fault is not None:
            self.engine.gateways[plan.account_ref].queue_fault(fault)
        order_id = self.engine.submit(plan, self.engine.strategy(reference).policy, key)
        return order_id, plan

    def test_all_three_markets_complete_entry_hold_exit_and_preserve_environment(self) -> None:
        references = [self.deploy(market) for market in Market]
        # Each local market completes a real ledger lifecycle. Two 20k-margin
        # futures plus costs cannot concurrently fit the initial 40k cash account;
        # their shared-capital rejection is verified separately below.
        for index, reference in enumerate(references):
            self.submit(reference, key=f'market-{index}')
            fill_local_pending(self.engine)
            positions = [p for p in self.engine.state.positions if p.quantity]
            self.assertEqual(len(positions), 1)
            for _ in range(3):
                step(self.engine, self.engine.history)
            self.assertIsNotNone(self.engine.exit_lot(positions[0].lot_id))
            fill_local_pending(self.engine)
            self.assertFalse(any(p.quantity for p in self.engine.state.positions))
            self.assertFalse(any(r.quantity for r in self.engine.reservations()))
            resume_receipt = self.facade.execute(UiCommand(UiAction.RESUME, self.engine.state.version))
            self.assertTrue(resume_receipt.accepted, resume_receipt)
        self.assertEqual(len([p for p in self.engine.state.positions if not p.quantity]), 3)
        self.assertTrue(all(o.status is OrderStatus.FILLED for o in self.engine.state.orders))
        self.assertTrue(all(view.environment is Environment.LOCAL for view in self.facade.snapshot().performance))
        self.assertGreater(self.engine.state.costs, 0)

    def test_two_futures_do_not_reuse_the_same_margin_cash(self) -> None:
        index = self.deploy(Market.INDEX_FUTURE)
        future = self.deploy(Market.STOCK_FUTURE)
        self.submit(index, key='index-margin')
        before = self.engine.gateways['local-futures'].submission_count
        with self.assertRaises(DomainError):
            self.submit(future, key='future-margin')
        self.assertEqual(self.engine.gateways['local-futures'].submission_count, before)
        self.assertGreater(self.engine.reservations()[0].cash, D('20000'))

    def test_future_short_lifecycle_and_coincident_exit_signals_reduce_once(self) -> None:
        reference = self.deploy(Market.INDEX_FUTURE, direction=Side.SELL)
        self.submit(reference)
        fill_local_pending(self.engine)
        lot = self.engine.state.positions[0]
        self.assertEqual(lot.direction, Side.SELL)
        for _ in range(3):
            step(self.engine, self.engine.history)
        first = self.engine.exit_lot(lot.lot_id)
        self.assertIsNotNone(first)
        self.assertIsNone(self.engine.exit_lot(lot.lot_id, protective=True))
        self.assertEqual(len([o for o in self.engine.state.orders if o.plan.reduce_only]), 1)
        fill_local_pending(self.engine)
        self.assertEqual(self.engine.state.positions[0].quantity, 0)
        self.assertFalse(self.engine.gateways['local-futures'].remote_state.positions)

    def test_stock_five_trading_days_and_restart_preserve_remote_order_and_policy(self) -> None:
        reference = self.deploy()
        order_id, _ = self.submit(reference)
        fill_local_pending(self.engine)
        original = self.engine.state.positions[0]
        for _ in range(2):
            step(self.engine, self.engine.history)
        self.restart()
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.engine.state.reconciled)
        self.assertEqual(self.engine.state.positions[0].entry_trade_date, original.entry_trade_date)
        self.assertIn(order_id, self.engine.gateways['local-stock'].remote_state.orders)
        self.command(UiAction.RECONCILE)
        for _ in range(3):
            step(self.engine, self.engine.history)
        position = self.engine.state.positions[0]
        self.assertEqual(self.engine.calendar.age(position.entry_trade_date, self.engine.state.trading_day), 5)
        self.assertEqual(position.policy, original.policy)
        self.assertEqual(position.sellable_quantity, position.quantity)
        self.assertIsNotNone(self.engine.exit_lot(position.lot_id))
        fill_local_pending(self.engine)
        remote = self.engine.gateways['local-stock'].snapshot('local-stock')
        self.assertGreater(remote.unsettled_receivables, 0)
        for _ in range(2):
            step(self.engine, self.engine.history)
        self.assertEqual(self.engine.gateways['local-stock'].snapshot('local-stock').unsettled_receivables, 0)

    def test_exact_idempotency_retry_and_conflicting_content(self) -> None:
        reference = self.deploy()
        order_id, plan = self.submit(reference)
        broker = self.engine.gateways[plan.account_ref]
        count = broker.submission_count
        self.assertEqual(self.engine.submit(plan, self.engine.strategy(reference).policy, 'entry'), order_id)
        self.assertEqual(broker.submission_count, count)
        with self.assertRaises(DomainError) as raised:
            self.engine.submit(replace(plan, limit_price=plan.limit_price + D('0.05')), self.engine.strategy(reference).policy, 'entry')
        self.assertEqual(raised.exception.code, 'state_conflict')
        self.assertEqual(broker.submission_count, count)

    def test_unknown_after_accept_durable_restart_and_query_without_resubmit(self) -> None:
        reference = self.deploy()
        order_id, plan = self.submit(reference, fault=FaultPlan(unknown_after_accept=True))
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.UNKNOWN)
        reservation = self.engine.reservations()[0]
        self.assertGreater(reservation.cash, 0)
        self.assertGreater(reservation.risk, 0)
        self.assertEqual(self.engine.submit(plan, self.engine.strategy(reference).policy, 'entry'), order_id)
        self.restart()
        broker = self.engine.gateways['local-stock']
        self.assertIn(order_id, broker.remote_state.orders)
        self.command(UiAction.RECONCILE)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.ACCEPTED)
        self.assertEqual(broker.submission_count, 0)
        self.assertEqual(len(broker.remote_state.orders), 1)

    def test_partial_fill_cancel_retains_owned_risk_and_releases_only_remainder(self) -> None:
        reference = self.deploy()
        order_id, plan = self.submit(reference, fault=FaultPlan(partial_quantity=1000), quantity=2000)
        poll_events(self.engine)
        before = self.engine.state.orders[0].reservation
        self.assertEqual(self.engine.state.positions[0].quantity, 1000)
        service = ExecutionService(self.engine.gateways[plan.account_ref], self.engine._persist, self.engine.fence, self.engine.clock.now)
        service.cancel(self.engine.state, order_id)
        poll_events(self.engine)
        order = self.engine.state.orders[0]
        self.assertEqual(order.status, OrderStatus.CANCELED)
        self.assertEqual(order.filled, 1000)
        self.assertEqual(order.reservation.quantity, 1000)
        self.assertEqual(order.reservation.cash, 0)
        self.assertGreater(order.reservation.risk, 0)
        self.assertLess(order.reservation.risk, before.risk)
        required = self.engine.fees.loss_at_stop(self.engine.catalog.resolve(plan.instrument_id), plan.limit_price, plan.stop_price, order.filled, plan.side)
        self.assertGreaterEqual(order.reservation.risk, required)

    def test_partial_cancel_fill_race_cannot_erase_filled_position(self) -> None:
        reference = self.deploy()
        order_id, plan = self.submit(reference, fault=FaultPlan(partial_quantity=1000, cancel_fill_race=True), quantity=2000)
        poll_events(self.engine)
        ExecutionService(self.engine.gateways[plan.account_ref], self.engine._persist, self.engine.fence, self.engine.clock.now).cancel(
            self.engine.state, order_id
        )
        poll_events(self.engine)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.FILLED)
        self.assertEqual(self.engine.state.orders[0].filled, plan.quantity)
        self.assertEqual(self.engine.state.positions[0].quantity, plan.quantity)

    def test_exit_of_partial_fill_does_not_release_unfilled_entry_cash(self) -> None:
        reference = self.deploy()
        broker = self.engine.gateways['local-stock']
        broker.capabilities = replace(broker.capabilities, day_trade=True)
        entry_id, plan = self.submit(reference, fault=FaultPlan(partial_quantity=1000), quantity=2000)
        poll_events(self.engine)
        prior_cash = self.engine.state.orders[0].reservation.cash
        self.assertGreater(prior_cash, 0)
        exit_id = self.engine.exit_lot(self.engine.state.positions[0].lot_id, protective=True)
        exit_order = next(o for o in self.engine.state.orders if o.order_id == exit_id)
        spec = self.engine.catalog.resolve(plan.instrument_id)
        fee = self.engine.fees.transaction(spec, exit_order.plan.side, exit_order.plan.limit_price, 1000)
        self.engine.simulation.fill(plan.account_ref, exit_id, 1000, exit_order.plan.limit_price, fee)
        self.engine.simulation.persist_remote()
        poll_events(self.engine)
        entry = next(o for o in self.engine.state.orders if o.order_id == entry_id)
        self.assertEqual(entry.filled, 1000)
        self.assertEqual(entry.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(entry.reservation.quantity, 1000)
        self.assertEqual(entry.reservation.cash, prior_cash)
        self.assertEqual(self.engine.state.positions[0].quantity, 0)

    def test_duplicate_events_do_not_duplicate_fills_and_accounts_are_independent(self) -> None:
        stock = self.deploy()
        future = self.deploy(Market.INDEX_FUTURE)
        self.submit(stock, fault=FaultPlan(duplicate_event=True), key='stock')
        self.submit(future, fault=FaultPlan(duplicate_event=True), key='future')
        fill_local_pending(self.engine)
        self.assertEqual(sorted(p.quantity for p in self.engine.state.positions), [1, 1000])
        state = self.engine.state
        poll_events(self.engine)
        self.assertEqual(self.engine.state, state)

    def test_sequence_gap_quarantines_and_query_reconstructs_missing_fill(self) -> None:
        reference = self.deploy()
        order_id, plan = self.submit(reference, fault=FaultPlan(drop_event=True))
        broker = self.engine.gateways[plan.account_ref]
        fee = self.engine.fees.transaction(self.engine.catalog.resolve(plan.instrument_id), plan.side, plan.limit_price, plan.quantity)
        self.engine.simulation.fill(plan.account_ref, order_id, plan.quantity, plan.limit_price, fee)
        self.engine.simulation.persist_remote()
        with self.assertRaises(DomainError):
            poll_events(self.engine)
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.engine.state.reconciled)
        reconcile(self.engine)
        self.assertEqual(self.engine.state.positions[0].quantity, plan.quantity)
        self.assertEqual(broker.submission_count, 1)

    def test_out_of_order_events_quarantine_without_double_bookkeeping(self) -> None:
        reference = self.deploy()
        order_id, plan = self.submit(reference)
        broker = self.engine.gateways[plan.account_ref]
        self.engine.simulation.fill(plan.account_ref, order_id, plan.quantity, plan.limit_price, D('20'))
        broker.reorder_events(tuple(reversed(tuple(e.sequence for e in broker.remote_state.events))))
        with self.assertRaises(DomainError):
            poll_events(self.engine)
        self.assertFalse(self.engine.state.positions)
        self.assertFalse(self.engine.state.reconciled)
        reconcile(self.engine)
        self.assertEqual(self.engine.state.positions[0].quantity, plan.quantity)

    def test_terminal_rejection_cannot_be_revived_by_later_acceptance_event(self) -> None:
        reference = self.deploy()
        _, plan = self.submit(reference, fault=FaultPlan(reject=True))
        broker = self.engine.gateways[plan.account_ref]
        poll_events(self.engine)
        first = broker.remote_state.events[-1]
        broker.remote_state.events.append(replace(first, event_id='inconsistent-late-accept', sequence=first.sequence + 1, status=OrderStatus.ACCEPTED))
        with self.assertRaises(DomainError):
            poll_events(self.engine)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.REJECTED)
        self.assertFalse(self.engine.reservations())
        self.assertFalse(self.engine.state.reconciled)

    def test_reused_event_identity_with_different_economics_is_quarantined(self) -> None:
        reference = self.deploy()
        _, plan = self.submit(reference)
        broker = self.engine.gateways[plan.account_ref]
        poll_events(self.engine)
        first = broker.remote_state.events[-1]
        # The transport has delivered a different event under an already-used
        # identity. This is not an exact duplicate and cannot be silently ignored.
        broker.remote_state.events.append(
            replace(
                first,
                sequence=first.sequence + 1,
                status=OrderStatus.FILLED,
                cumulative_quantity=plan.quantity,
                last_fill_quantity=plan.quantity,
                last_fill_price=plan.limit_price,
            )
        )
        with self.assertRaises(DomainError):
            poll_events(self.engine)
        self.assertFalse(self.engine.state.positions)
        self.assertFalse(self.engine.state.reconciled)

    def test_external_mobile_order_and_position_freeze_scope_and_are_never_flattened(self) -> None:
        reference = self.deploy()
        broker = self.engine.gateways['local-stock']
        external_plan = self.order_plan(reference, name='external')
        broker.submit(external_plan, 'mobile-unfilled')
        self.command(UiAction.RECONCILE, accepted=False)
        self.assertIn('external_order_difference', self.engine.state.issues)
        broker.cancel('mobile-unfilled')
        broker.external_position(BrokerPosition('local-stock', external_plan.instrument_id, 2000, 2000, external_plan.unit, D('10'), 'EXTERNAL'))
        self.command(UiAction.RECONCILE, accepted=False)
        self.assertIn('external_position_difference', self.engine.state.issues)
        self.assertFalse(self.engine.state.positions)
        before = broker.remote_state.positions[external_plan.instrument_id]
        before_submissions = broker.submission_count
        receipt = self.command(UiAction.FLATTEN, target_id='mobile-unowned', accepted=False)
        self.assertEqual(receipt.code, 'exit_unavailable')
        self.assertEqual(broker.submission_count, before_submissions)
        self.assertEqual(broker.remote_state.positions[external_plan.instrument_id], before)

    def test_today_new_stock_protective_exit_is_explicitly_blocked(self) -> None:
        reference = self.deploy()
        self.submit(reference)
        fill_local_pending(self.engine)
        self.assertIsNone(self.engine.exit_lot(self.engine.state.positions[0].lot_id, protective=True))
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('exit_unavailable', self.engine.state.issues)
        self.assertEqual(len(self.engine.state.orders), 1)

    def test_journal_failure_before_submit_retains_state_and_never_calls_broker(self) -> None:
        reference = self.deploy()
        broker = self.engine.gateways['local-stock']
        plan = self.order_plan(reference)
        prior_orders = self.engine.state.orders
        self.engine.journal.fail_writes = True
        with self.assertRaises(DomainError):
            self.engine.submit(plan, self.engine.strategy(reference).policy, 'disk-full')
        self.assertEqual(broker.submission_count, 0)
        self.assertEqual(self.engine.state.orders, prior_orders)
        self.assertTrue(self.engine.storage_failed)
        self.assertTrue(self.engine.state.stopped)

    def test_journal_failure_after_remote_accept_recovers_without_repeating_submission(self) -> None:
        reference = self.deploy()
        plan = self.order_plan(reference)
        original_append = self.engine.journal.append

        def fail_receipt(kind, *args, **kwargs):
            if kind == 'submission_receipt':
                raise OSError('injected durable write failure after exchange acceptance')
            return original_append(kind, *args, **kwargs)

        with patch.object(self.engine.journal, 'append', fail_receipt), self.assertRaises(DomainError):
            self.engine.submit(plan, self.engine.strategy(reference).policy, 'accept-before-disk-failure')
        remote_ids = tuple(self.engine.gateways['local-stock'].remote_state.orders)
        self.assertEqual(len(remote_ids), 1)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.SUBMITTING)
        self.assertTrue(self.engine.storage_failed)
        self.restart()
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.UNKNOWN)
        self.command(UiAction.RECONCILE)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.ACCEPTED)
        self.assertEqual(tuple(self.engine.gateways['local-stock'].remote_state.orders), remote_ids)
        self.assertEqual(self.engine.gateways['local-stock'].submission_count, 0)

    def test_second_writer_and_expired_owner_are_fenced_before_broker_call(self) -> None:
        reference = self.deploy()
        broker = self.engine.gateways['local-stock']
        wall = datetime.now(timezone.utc)
        with self.assertRaises(DomainError):
            Ledger(self.engine.journal.path, 'platform-local', wall)
        newer = Ledger(self.engine.journal.path, 'platform-local', wall + timedelta(seconds=40))
        try:
            with self.assertRaises(DomainError):
                self.engine.submit(self.order_plan(reference), self.engine.strategy(reference).policy, 'stale-owner')
            self.assertEqual(broker.submission_count, 0)
        finally:
            newer.close()

    def test_strategy_new_version_keeps_old_position_policy_until_explicit_transfer(self) -> None:
        reference = self.deploy()
        self.submit(reference)
        fill_local_pending(self.engine)
        old = self.engine.state.positions[0]
        updated = self.deploy(parent=old.strategy_id, max_days=30, kind=HoldingKind.POSITION)
        self.assertEqual(self.engine.state.positions[0].strategy_version, 1)
        self.assertEqual(self.engine.state.positions[0].policy.max_days, 5)
        self.command(UiAction.TRANSFER, target_id=old.lot_id, destination_strategy_id=updated)
        moved = self.engine.state.positions[0]
        self.assertEqual(moved.strategy_version, 2)
        self.assertEqual(moved.policy.max_days, 30)
        self.assertEqual(moved.entry_trade_date, old.entry_trade_date)

    def test_unvalidated_strategy_version_cannot_take_over_existing_position(self) -> None:
        reference = self.deploy()
        self.submit(reference)
        fill_local_pending(self.engine)
        old = self.engine.state.positions[0]
        form = replace(self.engine.strategy(reference).form, parent_strategy_id=old.strategy_id, holding_kind=HoldingKind.POSITION, max_days=30)
        draft_reference = self.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        self.command(UiAction.TRANSFER, target_id=old.lot_id, destination_strategy_id=draft_reference, accepted=False)
        self.assertEqual(self.engine.state.positions[0], old)

    def test_presentation_boundary_rejects_untyped_strategy_and_float_money(self) -> None:
        reference = self.deploy()
        form = self.engine.strategy(reference).form
        for value in ('untyped', replace(form, allocation=1000.0), replace(form, name=123)):
            with self.subTest(value=value):
                self.command(UiAction.CREATE_STRATEGY, strategy=value, accepted=False)

    def test_fresh_quote_does_not_authorize_entry_outside_explicit_market_session(self) -> None:
        reference = self.deploy()
        record = self.engine.strategy(reference)
        current = self.engine.quotes[record.form.instrument_id]
        self.engine.clock.current = self.engine.calendar.day_session(self.engine.state.trading_day).closes_at + timedelta(minutes=1)
        self.engine.quote(replace(current, source_at=self.engine.clock.now(), received_at=self.engine.clock.now(), sequence=current.sequence + 1))
        broker = self.engine.gateways[record.form.account_ref]
        with self.assertRaises(DomainError):
            self.submit(reference, key='closed-session')
        self.assertEqual(broker.submission_count, 0)

    def test_partial_fault_fees_match_remote_cash_and_local_net_pnl(self) -> None:
        reference = self.deploy()
        self.submit(reference, fault=FaultPlan(partial_quantity=1000), quantity=2000)
        poll_events(self.engine)
        order = self.engine.state.orders[0]
        remote = self.engine.gateways['local-stock'].snapshot('local-stock')
        self.assertEqual(remote.equity, D('60000') - order.costs)
        self.assertEqual(self.engine.state.realized_pnl, -order.costs)

    def test_daily_loss_latch_survives_settings_reconciliation_and_restart(self) -> None:
        reference = self.deploy(Market.INDEX_FUTURE)
        self.submit(reference)
        fill_local_pending(self.engine)
        lot = self.engine.state.positions[0]
        current = self.engine.quotes[lot.instrument_id]
        price = current.last - D('1100')
        self.engine.quote(replace(current, bid=price, ask=price + D('1'), last=price, sequence=current.sequence + 1))
        mark_risk(self.engine)
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.assertTrue(self.engine.state.stopped)
        self.command(UiAction.SAVE_SETTINGS, settings=SettingsForm(D('60000'), D('40000'), D('0.03')))
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.restart()
        self.command(UiAction.RECONCILE)
        self.command(UiAction.RESUME, accepted=False)
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)

    def test_commit_revalues_existing_loss_before_accepting_new_entry(self) -> None:
        future = self.deploy(Market.INDEX_FUTURE)
        stock = self.deploy()
        self.submit(future)
        fill_local_pending(self.engine)
        lot = self.engine.state.positions[0]
        current = self.engine.quotes[lot.instrument_id]
        price = current.last - D('1100')
        self.engine.quote(replace(current, bid=price, ask=price + D('1'), last=price, sequence=current.sequence + 1))
        with self.assertRaises(DomainError):
            self.submit(stock, key='new-risk-after-loss')
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)

    def test_restore_old_backup_with_submitting_queue_never_replays_old_command(self) -> None:
        reference = self.deploy()
        plan = self.order_plan(reference)
        original_append = self.engine.journal.append

        def fail_receipt(kind, *args, **kwargs):
            if kind == 'submission_receipt':
                raise OSError('crash before receipt persisted')
            return original_append(kind, *args, **kwargs)

        with patch.object(self.engine.journal, 'append', fail_receipt), self.assertRaises(DomainError):
            self.engine.submit(plan, self.engine.strategy(reference).policy, 'restore-pending')
        saved = self.root / 'backup.sqlite'
        self.engine.journal.backup(saved)
        self.close_engine()
        # Restore only this test's own trading database. The independent exchange
        # ledger remains current, just as a real broker cannot be rolled back.
        target = self.root / 'platform' / 'trading-v2.sqlite'
        target.write_bytes(saved.read_bytes())
        self.engine = create_engine(self.root / 'platform')
        self.facade = LocalFacade(self.engine)
        self.assertEqual(self.engine.state.orders[0].status, OrderStatus.UNKNOWN)
        self.assertFalse(self.engine.state.reconciled)
        self.assertTrue(self.engine.state.stopped)
        self.assertEqual(self.engine.gateways['local-stock'].submission_count, 0)
        self.command(UiAction.RECONCILE)
        self.assertEqual(self.engine.gateways['local-stock'].submission_count, 0)
        self.assertEqual(len(self.engine.gateways['local-stock'].remote_state.orders), 1)


class DashboardApplicationTests(unittest.TestCase):
    """One application table owns daily metrics and position valuation wiring."""

    def test_daily_values_and_live_only_position_valuation(self):
        from test_live_market_wiring import memory_engine
        from quantlab.trading.application.state import StrategyRecord, LocalOrder
        from quantlab.trading.application.performance import seed_track
        from quantlab.trading.domain.models import HoldingPolicy, PositionLot, Quote, Reservation

        engine = memory_engine()
        now = engine.clock.now()
        day = engine.state.trading_day
        next_day = engine.calendar.advance(day, 1)
        next_now = engine.calendar.day_session(next_day).opens_at + timedelta(minutes=5)
        spec = engine.catalog.instruments[0]
        form = StrategyForm(
            'dashboard', spec.market, HoldingKind.SWING, 3, 5, Side.BUY, spec.instrument_id, 'local-stock', Environment.LOCAL, D('30000'), D('.02')
        )
        record = StrategyRecord('strategy', 1, form, HoldingPolicy())
        plan = OrderPlan(
            'today',
            'local-stock',
            Environment.LOCAL,
            spec.instrument_id,
            'strategy',
            1,
            Side.BUY,
            1000,
            spec.unit,
            D('10'),
            D('9'),
            False,
            next_now,
            next_now + timedelta(seconds=30),
            0,
        )
        reserve = Reservation('reserve', 'local-stock', spec.instrument_id, 'group', D('0'), D('0'), 0, OrderStatus.FILLED)
        old_plan = replace(plan, plan_id='old', decision_at=now, deadline=now + timedelta(seconds=30))
        old_order = LocalOrder('old', 'old', 'hash', old_plan, record.policy, reserve, OrderStatus.FILLED, filled=1000, fill_count_day=day, daily_fill_count=4)
        order = LocalOrder('today', 'today', 'hash', plan, record.policy, reserve, OrderStatus.FILLED, filled=1000, fill_count_day=next_day, daily_fill_count=2)
        lot = PositionLot('today', 'local-stock', spec.instrument_id, 'strategy', 1, record.policy, 1000, D('10'), next_day, 0)
        track = replace(seed_track('strategy', 1, now, day), trade_date=next_day, last_at=next_now, equity=D('125'), peak=D('125'), daily_baseline=D('100'))
        engine.clock.current = next_now

        class MarketService:
            market_revision = 0

            def __init__(self, freshness):
                from quantlab.trading.application.contracts import MarketHealthView, MarketWatchView

                health = MarketHealthView(spec.instrument_id, freshness)
                self.view = MarketWatchView(spec.instrument_id, health=health)

            def views(self):
                return (self.view,)

            def overview(self):
                from quantlab.trading.application.contracts import OverviewMarketSummary

                return OverviewMarketSummary((self.view.health,))

        for age, quality, shared_health, expected_pnl, expected_today in (
            (0, 'VERIFIED', None, D('1000'), D('25')),
            (11, 'VERIFIED', None, None, None),
            (61, 'VERIFIED', None, None, None),
            (0, 'UNVERIFIED', None, None, None),
            (0, 'VERIFIED', 'LIVE', D('1000'), D('25')),
            (0, 'VERIFIED', 'DELAYED', None, None),
            (0, 'VERIFIED', 'STOPPED', None, None),
            (0, 'VERIFIED', 'CLOSED', None, None),
            (0, 'VERIFIED', 'UNKNOWN', None, None),
        ):
            with self.subTest(age=age, quality=quality, shared_health=shared_health):
                engine.live_market = MarketService(shared_health) if shared_health is not None else None
                engine.state = replace(
                    engine.state, trading_day=next_day, strategies=(record,), orders=(old_order, order), positions=(lot,), performance_tracks=(track,)
                )
                engine.quotes[spec.instrument_id] = Quote(
                    spec.instrument_id,
                    D('11'),
                    D('11'),
                    D('11'),
                    next_now - timedelta(seconds=age),
                    next_now - timedelta(seconds=age),
                    next_day,
                    quality=quality,
                )
                view = LocalFacade(engine).snapshot()
                self.assertEqual((view.strategies[0].today_order_count, view.strategies[0].today_pnl), (1, expected_today))
                self.assertEqual((view.positions[0].unrealized_pnl, view.unrealized_pnl), (expected_pnl, expected_pnl))
                self.assertEqual(view.today_fill_count, 2)
                self.assertEqual(view.positions[0].quote_time, engine.quotes[spec.instrument_id].source_at.isoformat())
                self.assertIn(str(engine.calendar.advance(next_day, 5)), view.positions[0].exit_window)
        engine.state = replace(
            engine.state, performance_tracks=(replace(track, daily_baseline=None),), orders=(replace(order, fill_count_day=None, daily_fill_count=None),)
        )
        self.assertIsNone(LocalFacade(engine).snapshot().strategies[0].today_pnl)
        self.assertIsNone(LocalFacade(engine).snapshot().today_fill_count)
        for stopped, reconciled, locks, expected in (
            (False, True, (), 'RUNNING'),
            (True, True, (), 'PAUSED'),
            (False, False, (), 'PAUSED'),
            (True, True, (next_day,), 'RISK_STOPPED'),
        ):
            with self.subTest(stopped=stopped, reconciled=reconciled, locks=locks):
                engine.state = replace(engine.state, strategies=(replace(record, state='ACTIVE'),), stopped=stopped, reconciled=reconciled, daily_locks=locks)
                self.assertEqual(LocalFacade(engine).snapshot().strategies[0].activity_state, expected)

    def test_local_day_rollover_and_dated_fill_counts(self):
        from types import SimpleNamespace
        from test_live_market_wiring import memory_engine
        from quantlab.trading.application.events import apply_event
        from quantlab.trading.application.state import LocalOrder, StrategyRecord
        from quantlab.trading.application.performance import seed_track
        from quantlab.trading.domain.models import HoldingPolicy, Quote, Reservation
        from quantlab.trading.ports.contracts import OrderEvent

        engine = memory_engine()
        spec = engine.catalog.instruments[0]
        now = engine.clock.now()
        day = engine.state.trading_day
        form = StrategyForm('daily', spec.market, HoldingKind.SWING, 3, 5, Side.BUY, spec.instrument_id, 'local-stock', Environment.LOCAL, D('30000'), D('.02'))
        record = StrategyRecord('strategy', 1, form, HoldingPolicy())
        plan = OrderPlan(
            'entry',
            'local-stock',
            Environment.LOCAL,
            spec.instrument_id,
            'strategy',
            1,
            Side.BUY,
            3000,
            spec.unit,
            D('10'),
            D('9'),
            False,
            now,
            now + timedelta(seconds=30),
            0,
        )
        reserve = Reservation('reserve', 'local-stock', spec.instrument_id, 'group', D('0'), D('0'), 3000, OrderStatus.ACCEPTED)
        order = LocalOrder('entry', 'entry', 'hash', plan, record.policy, reserve, OrderStatus.ACCEPTED)
        engine.state = replace(engine.state, strategies=(record,), orders=(order,), performance_tracks=(seed_track('strategy', 1, now, day),))

        class Gateway:
            def inspect(self, account):
                return SimpleNamespace(day_trade=True)

        class Simulation:
            def advance(self, trade_day, current):
                engine.clock.current = current

        engine.gateways = {'local-stock': Gateway()}
        engine.quotes[spec.instrument_id] = Quote(spec.instrument_id, D('10'), D('10'), D('10'), now, now, day)
        for sequence, current_day in enumerate((day, engine.calendar.advance(day, 1)), 1):
            with self.subTest(day=current_day):
                current = engine.calendar.day_session(current_day).opens_at + timedelta(minutes=5)
                engine.clock.current = current
                engine.state = replace(engine.state, trading_day=current_day)
                apply_event(
                    engine,
                    OrderEvent(
                        f'fill-{sequence}', 'entry', 'broker', OrderStatus.PARTIALLY_FILLED, sequence * 1000, 1000, D('10'), current, sequence, 'SIMULATED'
                    ),
                )
                self.assertEqual(LocalFacade(engine).snapshot().today_fill_count, 1)
        engine.gateways = {}
        engine.simulation = Simulation()
        current = engine.clock.now()
        engine.quotes[spec.instrument_id] = Quote(spec.instrument_id, D('10'), D('10'), D('10'), current, current, current_day)
        step(engine, {})
        current = engine.clock.now()
        engine.quotes[spec.instrument_id] = Quote(spec.instrument_id, D('10'), D('10'), D('10'), current, current, engine.state.trading_day)
        view = LocalFacade(engine).snapshot()
        self.assertEqual((view.strategies[0].today_order_count, view.strategies[0].today_pnl, view.today_fill_count), (0, D('0'), 0))


if __name__ == '__main__':
    unittest.main()
