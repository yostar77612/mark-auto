"""Final daily commitment admission independently binds every durable identity."""

from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch

import test_m2_automatic as fixtures
from official_daily_fixtures import fake_official_history, official_intent_fixture, official_research_fixture
from quantlab.trading.application.daily_execution import assert_daily_dispatch, dispatch_daily
from quantlab.trading.application.daily_state import DailyState, create_intent
from quantlab.trading.domain.auto_cycle import EvaluationCursor
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.strategy import CompletedBar


class DailyCommitTests(unittest.TestCase):
    def setUp(self):
        self.engine = fixtures.MemoryEngine()
        self.record = replace(self.engine.record, parameters=replace(self.engine.record.parameters, bar_interval='1d'), evidence_hash='a' * 64)
        calendar = calendar_for_instrument(self.engine.calendar, self.engine.catalog.resolve(self.record.form.instrument_id))
        target = calendar.day_session(self.engine.state.trading_day)
        origin = tuple(row for row in calendar.sessions if row.trade_date < target.trade_date)[-1]
        sessions = tuple(row for row in calendar.sessions if row.kind == 'DAY' and row.trade_date <= origin.trade_date)[-25:]
        bars = tuple(
            CompletedBar(
                row.opens_at,
                row.closes_at,
                row.closes_at,
                self.engine.quotes[self.record.form.instrument_id].last,
                self.engine.quotes[self.record.form.instrument_id].last,
                1000,
            )
            for row in sessions
        )
        history = fake_official_history(self.record.form.instrument_id, bars, origin.closes_at)
        self.record, _ = official_research_fixture(self.engine, self.record, history)
        self.engine.record = self.record
        self.engine.state = replace(self.engine.state, strategies=(self.record,))
        cursor = EvaluationCursor(self.record.strategy_id, self.record.version, self.record.form.instrument_id, '1d', origin.closes_at)
        self.intent = replace(
            create_intent(cursor, 'test-stock', 'ENTRY', cursor.instrument_id, '', self.record.evidence_hash, calendar, origin.closes_at), phase='CLAIMED'
        )
        self.intent = official_intent_fixture(self.engine, self.record, self.intent)
        self.engine.clock.value = target.opens_at
        self.plan = self.engine.order('fixture').plan
        self.grant = DailyState((self.intent,), 'run', 'verified-fake-owner')
        self.engine.state = replace(self.engine.state, orders=(), automatic=replace(self.engine.state.automatic, auto_paused=False, daily=self.grant))

    def rejected(self, code='daily_signal_invalidated', *, intent=None, plan=None, key=None):
        if intent is not None:
            self.engine.state = replace(self.engine.state, automatic=replace(self.engine.state.automatic, daily=replace(self.grant, intents=(intent,))))
        with self.assertRaises(DomainError) as caught:
            assert_daily_dispatch(self.engine, plan or self.plan, key or self.intent.key)
        self.assertEqual(caught.exception.code, code)

    def test_current_claim_passes_but_ready_missing_and_wrong_key_do_not(self):
        assert_daily_dispatch(self.engine, self.plan, self.intent.key)
        self.rejected('daily_signal_not_authorized', intent=replace(self.intent, phase='READY'))
        self.rejected('daily_signal_not_authorized', key='unclaimed')

    def test_current_run_owner_and_paused_latch_are_required(self):
        for changes in ({'authorized_run': ''}, {'owner_stamp': ''}, {'owner_stamp': 'another-owner'}):
            with self.subTest(changes=changes):
                self.engine.state = replace(
                    self.engine.state, automatic=replace(self.engine.state.automatic, auto_paused=False, daily=replace(self.grant, **changes))
                )
                self.rejected('daily_signal_not_authorized')
        self.engine.state = replace(self.engine.state, automatic=replace(self.engine.state.automatic, auto_paused=True, daily=self.grant))
        self.rejected('daily_signal_not_authorized')

    def test_live_and_local_cannot_enter_daily_commit(self):
        for environment, code in ((Environment.LIVE, 'production_orders_disabled'), (Environment.LOCAL, 'capability_missing')):
            with self.subTest(environment=environment):
                self.engine.configuration.environment = environment
                self.rejected(code)

    def test_calendar_identity_version_and_actual_bounds_are_bound(self):
        for changes in (
            {'calendar_id': 'another'},
            {'calendar_version': 'another'},
            {'not_before': self.intent.not_before + timedelta(seconds=1)},
            {'deadline': self.intent.deadline - timedelta(seconds=1)},
        ):
            with self.subTest(changes=changes):
                self.rejected(intent=replace(self.intent, **changes))

    def test_time_bounds_and_ledger_day_are_checked_again_at_commit(self):
        for at in (self.intent.not_before - timedelta(microseconds=1), self.intent.deadline):
            with self.subTest(at=at):
                self.engine.clock.value = at
                self.rejected()
        self.engine.clock.value = self.intent.not_before
        self.engine.state = replace(self.engine.state, trading_day=self.intent.target_trade_date - timedelta(days=1))
        self.rejected()

    def test_plan_identity_environment_account_and_action_cannot_be_substituted(self):
        for changes in (
            {'environment': Environment.LOCAL},
            {'account_ref': 'other'},
            {'strategy_id': 'other'},
            {'strategy_version': 2},
            {'instrument_id': 'other'},
            {'reduce_only': True},
        ):
            with self.subTest(changes=changes):
                self.rejected(plan=replace(self.plan, **changes))

    def test_exit_claim_binds_the_exact_owned_lot(self):
        intent = replace(self.intent, action='EXIT', lot_id='owned-lot')
        plan = replace(self.plan, reduce_only=True, exit_lot_id='other-lot')
        self.rejected(intent=intent, plan=plan, key=intent.key)
        assert_daily_dispatch(self.engine, replace(plan, exit_lot_id='owned-lot'), intent.key)

    def test_research_version_parameters_and_entry_selection_stay_current(self):
        for changes in (
            {'parameters': None},
            {'parameters': replace(self.record.parameters, bar_interval='5m')},
            {'form': replace(self.record.form, environment=Environment.LOCAL)},
            {'form': replace(self.record.form, account_ref='other')},
            {'evidence_hash': 'b' * 64},
            {'state': 'DISABLED'},
            {'form': replace(self.record.form, instrument_id='TAIFEX:TMF202606')},
        ):
            with self.subTest(changes=changes):
                self.engine.state = replace(self.engine.state, strategies=(replace(self.record, **changes),))
                self.rejected()

    def ready(self):
        self.engine.state = replace(
            self.engine.state,
            stopped=False,
            automatic=replace(self.engine.state.automatic, daily=replace(self.grant, intents=(replace(self.intent, phase='READY'),))),
        )

    def test_dispatch_proves_current_entry_admission_before_claim_or_planning(self):
        self.ready()
        for code in ('stale_quote', 'account_daily_loss_limit', 'manual_account_observation_required'):
            with self.subTest(code=code):
                self.ready()
                self.engine.state = replace(self.engine.state, automatic=replace(self.engine.state.automatic, auto_paused=False))
                with (
                    patch('quantlab.trading.application.automatic._entry_proofs', side_effect=DomainError(code)),
                    patch('quantlab.trading.application.coordinator._entry_decision') as planner,
                ):
                    dispatch_daily(self.engine)
                planner.assert_not_called()
                self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'READY')
                self.assertTrue(self.engine.state.automatic.auto_paused)
                self.assertFalse(self.engine.state.automatic.daily.authorized_run)
                self.assertIn(code, self.engine.state.automatic.reasons)

    def test_dispatch_durable_claim_precedes_planning_and_known_empty_result_is_terminal(self):
        self.ready()

        def admitted(*args, **kwargs):
            self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'CLAIMED')
            self.assertEqual(self.engine.events[-1][0], 'daily_dispatch_claimed')
            self.assertEqual(kwargs['decision_key'], self.intent.key)

        with (
            patch('quantlab.trading.application.automatic._entry_proofs') as proofs,
            patch('quantlab.trading.application.coordinator._entry_decision', side_effect=admitted) as planner,
        ):
            dispatch_daily(self.engine)
            completed = self.engine.state
            proofs.side_effect = DomainError('stale_quote')
            dispatch_daily(self.engine)
        self.assertEqual(self.engine.state, completed)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'KNOWN_NO_ORDER')

    def test_invalidated_research_retires_signal_without_claim_or_planning(self):
        self.ready()
        self.engine.state = replace(self.engine.state, strategies=(replace(self.record, evidence_hash='b' * 64),))
        with patch('quantlab.trading.application.coordinator._entry_decision') as planner:
            dispatch_daily(self.engine)
        planner.assert_not_called()
        self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'INVALIDATED')
        self.assertFalse(self.engine.state.automatic.auto_paused)

    def test_unknown_exception_without_a_canonical_order_keeps_claim_unresolved(self):
        self.ready()
        with (
            patch('quantlab.trading.application.automatic._entry_proofs'),
            patch('quantlab.trading.application.coordinator._entry_decision', side_effect=DomainError('outcome_unknown')) as planner,
        ):
            dispatch_daily(self.engine)
            dispatch_daily(self.engine)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(self.engine.state.orders, ())
        self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'UNKNOWN')
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertFalse(self.engine.state.automatic.daily.authorized_run)


if __name__ == '__main__':
    unittest.main()
