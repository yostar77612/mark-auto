"""Read-only observations cannot turn reports into permission to trade."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import threading
import unittest
from unittest.mock import patch

from test_trading_coordinator import laboratory
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.coordinator import run_cycle, run_readonly_cycle
from quantlab.trading.application.events import poll_events, reconcile
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


class ReadonlyCoordinationTests(unittest.TestCase):
    def test_readonly_reconciles_without_execution_or_rewriting_identical_observations(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            with patch.object(port, 'submit', wraps=port.submit) as submit, patch.object(port, 'cancel', wraps=port.cancel) as cancel:
                run_readonly_cycle(engine)
                self.assertTrue(engine.state.reconciled)
                self.assertTrue(engine.state.stopped)
                version, pnl = engine.state.version, engine.state.daily_pnl
                for _ in range(3):
                    run_readonly_cycle(engine)
                self.assertEqual(engine.state.version, version)
                self.assertEqual(engine.state.daily_pnl, pnl)
                submit.assert_not_called()
                cancel.assert_not_called()
                with self.assertRaises(DomainError):
                    run_cycle(engine, history)

    def test_readonly_stop_is_available_while_report_query_is_blocked_and_old_batch_is_discarded(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            entered, release = threading.Event(), threading.Event()
            report = port.refresh('test-stock')
            errors = []

            def slow(account):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('test query was not released')
                return report

            def observe():
                try:
                    run_readonly_cycle(engine)
                except Exception as exc:
                    errors.append(exc)

            with patch.object(port, 'refresh', side_effect=slow), patch.object(port, 'cancel', wraps=port.cancel) as cancel:
                worker = threading.Thread(target=observe)
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    receipt = LocalFacade(engine).execute(UiCommand(UiAction.STOP_NEW, engine.state.version))
                    self.assertTrue(receipt.accepted, receipt)
                    version = engine.state.version
                    release.set()
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                    self.assertEqual(engine.state.version, version, 'a query started before STOP cannot rewrite its newer book')
                    cancel.assert_not_called()
                finally:
                    release.set()
                    worker.join(3)

    def test_supplied_reports_require_complete_current_readonly_identity(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            remote = port.refresh('test-stock')
            bad = (
                {},
                {'other': remote},
                {'test-stock': replace(remote, as_of=engine.clock.now() - timedelta(seconds=31))},
                {'test-stock': replace(remote, as_of=engine.clock.now() + timedelta(seconds=1))},
                {'test-stock': replace(remote, account=replace(remote.account, environment=Environment.LIVE))},
                {'test-stock': replace(remote, account=replace(remote.account, as_of=engine.clock.now() - timedelta(seconds=31)))},
            )
            for reports in bad:
                before = engine.state
                with self.subTest(reports=reports), self.assertRaises(DomainError):
                    reconcile(engine, snapshots=reports)
                self.assertEqual(engine.state, before)
            engine.configuration = replace(engine.configuration, read_only=False)
            with self.assertRaises(DomainError):
                reconcile(engine, snapshots={'test-stock': remote})

    def test_failed_observation_quarantines_without_commands_and_recovers_on_fresh_report(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            with patch.object(port, 'refresh', side_effect=OSError('injected offline')):
                run_readonly_cycle(engine)
            self.assertFalse(engine.state.reconciled)
            self.assertTrue(engine.state.stopped)
            self.assertIn('reconciliation_required', engine.state.issues)
            self.assertEqual(port.received, [])
            run_readonly_cycle(engine)
            self.assertTrue(engine.state.reconciled)
            self.assertEqual(engine.state.issues, ())

    def test_daily_loss_observation_latches_stop_without_sending_cancel_or_exit(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            engine._persist('injected_paid_costs', replace(engine.state, costs=Decimal('10001'), realized_pnl=Decimal('-10001')))
            with patch.object(port, 'submit', wraps=port.submit) as submit, patch.object(port, 'cancel', wraps=port.cancel) as cancel:
                run_readonly_cycle(engine)
                self.assertEqual(engine.state.daily_pnl, Decimal('-10001'))
                self.assertIn(engine.state.trading_day, engine.state.daily_locks)
                self.assertTrue(engine.state.stopped)
                submit.assert_not_called()
                cancel.assert_not_called()

    def test_identical_report_does_not_extend_its_expired_freshness(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            remote = port.refresh('test-stock')
            with patch.object(port, 'refresh', return_value=remote):
                run_readonly_cycle(engine)
                self.assertTrue(engine.state.reconciled)
                engine.clock.value += timedelta(seconds=31)
                run_readonly_cycle(engine)
                self.assertFalse(engine.state.reconciled)
                self.assertIn('reconciliation_required', engine.state.issues)
                self.assertTrue(engine.state.stopped)

    def test_session_change_invalidates_baseline_even_when_cached_report_never_changes(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            remote = port.refresh('test-stock')
            before_day = engine.state.trading_day
            with patch.object(port, 'refresh', return_value=remote):
                run_readonly_cycle(engine)
                next_day = engine.calendar.advance(before_day, 1)
                engine.clock.value = engine.calendar.day_session(next_day).opens_at + timedelta(minutes=1)
                run_readonly_cycle(engine)
            self.assertEqual(engine.state.trading_day, next_day)
            self.assertTrue(engine.state.daily_baseline_required)
            self.assertFalse(engine.state.reconciled)
            self.assertTrue(engine.state.stopped)

    def test_manual_reconciliation_checks_both_nested_and_envelope_timestamps(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            remote = port.refresh('test-stock')
            for bad in (
                replace(remote, as_of=engine.clock.now() - timedelta(seconds=31)),
                replace(remote, account=replace(remote.account, as_of=engine.clock.now() - timedelta(seconds=31))),
                replace(remote, account=replace(remote.account, as_of=engine.clock.now() + timedelta(seconds=1))),
            ):
                with self.subTest(report=bad), patch.object(port, 'refresh', return_value=bad):
                    with self.assertRaises(DomainError):
                        reconcile(engine)
                    self.assertFalse(engine.state.reconciled)
                    self.assertTrue(engine.state.stopped)

    def test_presentation_does_not_renew_confirmed_facts_while_waiting_for_next_poll(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            reconcile(engine)
            self.assertTrue(LocalFacade(engine).snapshot().financial_facts_verified)
            engine.clock.value += timedelta(seconds=31)
            self.assertTrue(engine.state.reconciled, 'presentation must not mutate the engine book')
            view = LocalFacade(engine).snapshot()
            self.assertFalse(view.financial_facts_verified)
            self.assertIsNone(view.daily_pnl)
            self.assertIsNone(view.remaining_risk)

    def test_duplicate_event_quarantine_retains_failure_without_journal_churn(self):
        with laboratory(readonly=True) as (engine, broker, port, spec, history):
            with patch.object(port, 'events', side_effect=DomainError('reconciliation_required')):
                for index in range(3):
                    with self.assertRaises(DomainError):
                        poll_events(engine)
                    if index == 0:
                        version = engine.state.version
                    self.assertEqual(engine.state.version, version)
            self.assertFalse(engine.state.reconciled)
            self.assertTrue(engine.state.stopped)

    def test_nonlocal_flatten_keeps_position_until_actual_fill_report(self):
        with laboratory() as (engine, broker, port, spec, history):
            run_cycle(engine, history)
            broker.fill(engine.state.orders[0].order_id, 1, engine.state.orders[0].plan.limit_price)
            run_cycle(engine, history, allow_entries=False)
            lot = engine.state.positions[0]
            with patch('quantlab.trading.application.facade.fill_local_pending', side_effect=AssertionError('nonlocal cannot invent fills')):
                receipt = LocalFacade(engine).execute(UiCommand(UiAction.FLATTEN, engine.state.version, target_id=lot.lot_id))
            self.assertTrue(receipt.accepted, receipt)
            self.assertTrue(receipt.reference)
            self.assertIn('券商回報', receipt.message)
            self.assertEqual(engine.state.positions[0].quantity, 1)
            exit_order = engine.state.orders[-1]
            self.assertTrue(exit_order.plan.reduce_only)
            broker.fill(exit_order.order_id, 1, exit_order.plan.limit_price)
            run_cycle(engine, history, allow_entries=False)
            self.assertEqual(engine.state.positions[0].quantity, 0)
