"""Explicit deferred broker daily entries; local steps and known exits stay legal."""

from dataclasses import replace
from decimal import Decimal as D
import unittest

import test_m2_automatic_engine as native_fixtures
import test_m2_strategy_management as local_fixtures

from quantlab.trading.application import automatic
from quantlab.trading.application.codec import register
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.workflows import run_research
from quantlab.trading.domain.models import OrderStatus
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import RemoteImage, RemoteImages, SimulationClock, SimulationControl


class AutomaticDailyBoundaryTests(unittest.TestCase):
    def setUp(self):
        # Keep the TestCase class behind a module alias so discovery runs only
        # these boundary tests, while reusing the actual SDK/engine composition.
        self.case = native_fixtures.AutomaticEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def deploy_daily(self):
        case = self.case
        original = case.deploy(activate=False)
        reference = case.engine.clone_strategy(case.reference, form=original.form, parameters=replace(original.parameters, bar_interval='1d'))
        with case.engine.lock:
            case.engine.validate_strategy(reference)
            record = case.engine.strategy(reference)
            run_research(case.engine, reference, case.engine.history[record.form.instrument_id])
            case.engine.deploy(reference)
        case.reference = reference
        return case.engine.strategy(reference)

    def test_researched_broker_daily_strategy_has_explicit_no_order_no_reservation_boundary(self):
        case = self.case
        record = self.deploy_daily()
        self.assertEqual(record.parameters.bar_interval, '1d')
        self.assertTrue(record.evidence_hash)
        case.start()
        orders, reservations, native = case.engine.state.orders, case.engine.reservations(), case.placed()
        with self.assertRaises(DomainError) as rejected:
            case.engine.submit(case.direct_plan(record), record.policy, 'broker-daily-explicit-pending')
        self.assertEqual(rejected.exception.code, 'automatic_daily_execution_pending')
        self.assertEqual(case.placed(), native)
        self.assertEqual(case.engine.state.orders, orders)
        self.assertEqual(case.engine.reservations(), reservations)

    def test_broker_daily_view_reports_pending_and_paused_after_explicit_resume(self):
        case = self.case
        record = self.deploy_daily()
        case.start()
        self.assertFalse(case.engine.state.stopped)
        self.assertFalse(case.engine.state.automatic.auto_paused)
        view = next(row for row in LocalFacade(case.engine).snapshot().strategies if (row.strategy_id, row.version) == (record.strategy_id, record.version))
        self.assertEqual(view.entry_block_code, 'automatic_daily_execution_pending')
        self.assertEqual(view.activity_state, 'PAUSED')

    def test_local_daily_public_day_step_still_advances_and_executes(self):
        case = local_fixtures.StrategyManagementTests()
        case.setUp()
        register(RemoteImage, RemoteImages)
        clock = SimulationClock(case.engine.clock.now())
        case.clock = case.engine.clock = case.broker.clock = clock
        case.engine.simulation = SimulationControl(clock, case.engine.gateways, local_fixtures.GuardJournal())
        reference = case.deploy(allocation=D('30000'), entry_amount=D('10000'))
        record = case.engine.strategy(reference)
        self.assertEqual(record.parameters.bar_interval, '1d')
        day = case.engine.state.trading_day
        receipt = case.facade.execute(UiCommand(UiAction.STEP, case.engine.state.version))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(case.engine.state.trading_day, case.engine.calendar.advance(day, 1))
        self.assertTrue(any(row.plan.strategy_id == record.strategy_id for row in case.engine.state.orders))
        self.assertNotIn('automatic_daily_execution_pending', case.engine.state.issues)
        view = next(row for row in case.facade.snapshot().strategies if row.strategy_id == record.strategy_id)
        self.assertEqual(view.entry_block_code, '')

    def test_known_daily_owned_reduction_is_not_blocked_by_deferred_entry_boundary(self):
        case = self.case
        record, lot = case.open_and_fill()
        case.engine.update_strategy(replace(record, parameters=replace(record.parameters, bar_interval='1d')), 'offline_existing_daily_owned_version')
        native = case.placed()
        closed = case.engine.exit_lot(lot.lot_id, protective=True, key='daily-owned-known-protection')
        self.assertIsNotNone(closed)
        self.assertEqual(case.placed(), native + 1)
        self.assertEqual(case.engine.state.orders[-1].status, OrderStatus.ACCEPTED)
        self.assertTrue(case.engine.state.orders[-1].plan.reduce_only)

    def test_tmf_1335_native_order_counts_in_its_actual_trading_day(self):
        case = self.case
        record = case.deploy()
        case.at(13, 34)
        case.start()
        case.at(13, 35)
        before = case.placed()
        automatic.on_completed_bars(case.engine, (case.bar(),))
        self.assertEqual(case.placed(), before + 1, case.engine.state.automatic)
        view = next(row for row in LocalFacade(case.engine).snapshot().strategies if (row.strategy_id, row.version) == (record.strategy_id, record.version))
        self.assertEqual(view.today_order_count, 1)


if __name__ == '__main__':
    unittest.main()
