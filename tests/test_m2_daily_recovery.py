"""Explicit daily evaluation discard proves journal origin without retrying work."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_live_order_guard import GuardJournal
from test_m2_automatic import MemoryEngine
from quantlab.trading.application.automatic_state import claim_cursor, complete_evaluation, restart
from quantlab.trading.application.codec import dumps
from quantlab.trading.application.daily_recovery import recover_daily_evaluations
from quantlab.trading.application.daily_state import create_intent
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.auto_cycle import EvaluationCursor, evaluation_key
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import Environment, OrderStatus
from quantlab.trading.domain.validation import DomainError


class DailyRecoveryTests(unittest.TestCase):
    def setUp(self):
        initialize()
        self.engine = MemoryEngine()
        self.engine.record = self.engine.make_record(interval='1d')
        self.engine.state = replace(self.engine.state, strategies=(self.engine.record,))
        self.engine.journal = GuardJournal()
        self.calendar = calendar_for_instrument(self.engine.calendar, self.engine.catalog.instruments[0])
        self.session = self.calendar.day_session(self.engine.state.trading_day)
        self.engine.clock.value = self.session.closes_at
        self.engine.refresh_facts()
        self.cursor = EvaluationCursor(self.engine.record.strategy_id, 1, self.engine.record.form.instrument_id, '1d', self.session.closes_at)
        self.engine._persist = self.persist
        self.persist('initial_state', self.engine.state)
        self.initial = self.engine.state
        self.seed()

    def persist(self, kind, state):
        state = replace(state, version=self.engine.state.version + 1)
        self.engine.journal.append(kind, dumps(state), self.engine.clock.now(), expected_sequence=self.engine.state.version)
        self.engine.state = state
        self.engine.events.append((kind, state))

    def seed(self, *, kind='daily_evaluation_claimed', cursor=None):
        automatic = replace(self.engine.state.automatic, auto_paused=False, resumed_at=self.session.opens_at)
        claimed = claim_cursor(automatic, cursor or self.cursor, self.session.closes_at)
        self.persist(kind, replace(self.engine.state, automatic=claimed))
        self.persist('startup_reconciliation_required', replace(self.engine.state, automatic=restart(claimed)))

    def unresolved(self):
        before = self.engine.state
        recover_daily_evaluations(self.engine)
        self.assertIs(self.engine.state, before)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'INTERRUPTED')

    def test_pure_daily_discard_is_journaled_once_retains_cursor_pause_and_all_financial_facts(self):
        before = self.engine.state
        self.engine.history = Mock(side_effect=AssertionError('no evaluation'))
        recover_daily_evaluations(self.engine)
        after = self.engine.state
        row = after.automatic.evaluations[0]
        self.assertEqual((row.phase, row.code, row.order_result, row.order_id), ('COMPLETED', 'daily_signal_invalidated', None, ''))
        self.assertEqual(after.automatic.cursors, before.automatic.cursors)
        self.assertTrue(after.automatic.auto_paused)
        self.assertEqual(after.automatic.reasons, before.automatic.reasons)
        self.assertEqual(replace(after, automatic=before.automatic, version=before.version), before)
        self.assertEqual(self.engine.journal.replay()[-1].kind, 'daily_evaluation_discarded')
        recover_daily_evaluations(self.engine)
        self.assertIs(self.engine.state, after)
        for gateway in self.engine.gateways.values():
            gateway.snapshot.assert_not_called()
            gateway.refresh.assert_not_called()
            gateway.events.assert_not_called()
            gateway.cancel.assert_not_called()

    def test_live_refuses_before_journal_or_cached_ports(self):
        self.engine.configuration.environment = Environment.LIVE
        self.engine.journal.replay = Mock(side_effect=AssertionError('no journal'))
        with self.assertRaises(DomainError) as caught:
            recover_daily_evaluations(self.engine)
        self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.engine.automatic_observation_validator.assert_not_called()

    def test_local_closed_and_failed_engine_refuse(self):
        for environment, closed, failed in (
            (Environment.LOCAL, False, False),
            (Environment.BROKER_SIMULATION, True, False),
            (Environment.BROKER_SIMULATION, False, True),
        ):
            self.engine.configuration.environment = environment
            self.engine.state = replace(self.engine.state, engine_closed=closed)
            self.engine.storage_failed = failed
            with self.subTest(environment=environment, closed=closed, failed=failed), self.assertRaises(DomainError):
                recover_daily_evaluations(self.engine)

    def test_local_empty_account_scope_still_has_no_provider_authority(self):
        self.engine.configuration.environment = Environment.LOCAL
        self.engine.gateways = {}
        with self.assertRaises(DomainError) as caught:
            recover_daily_evaluations(self.engine)
        self.assertEqual(caught.exception.code, 'capability_missing')

    def test_current_full_observation_is_mandatory(self):
        self.engine.manual_observations = {}
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'INTERRUPTED')

    def test_current_owner_and_remote_cache_must_be_trusted(self):
        self.engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)

    def test_stale_cache_and_missing_shared_account_block(self):
        self.engine.clock.value += timedelta(seconds=31)
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)
        self.engine.clock.value -= timedelta(seconds=31)
        self.engine.gateways['other'] = SimpleNamespace()
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)

    def test_empty_accounts_cannot_prove_discard(self):
        self.engine.gateways = {}
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)

    def test_manual_unknown_is_never_cleared(self):
        self.engine.state = replace(self.engine.state, manual_requests=(SimpleNamespace(outcome_known=False),))
        self.engine._persist = Mock(side_effect=AssertionError('unknown manual request cannot reach commit'))
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'INTERRUPTED')
        self.engine._persist.assert_not_called()

    def test_any_local_unknown_blocks_even_an_unrelated_scope(self):
        self.engine.order('unrelated', status=OrderStatus.UNKNOWN)
        with self.assertRaises(DomainError):
            recover_daily_evaluations(self.engine)

    def test_missing_history_has_no_provenance(self):
        self.engine.journal.events = []
        self.unresolved()

    def test_wrong_event_kind_cannot_turn_a_minute_execution_claim_into_pure_work(self):
        self.engine.journal.events[1] = replace(self.engine.journal.events[1], kind='automatic_evaluation_claimed')
        self.unresolved()

    def test_wrong_payload_type_or_sequence_is_rejected(self):
        original = self.engine.journal.events[1]
        for payload in (dumps('not-state'), dumps(replace(self.engine.state, version=999))):
            self.engine.journal.events[1] = replace(original, payload=payload)
            with self.subTest(payload=payload), self.assertRaises(DomainError) as caught:
                recover_daily_evaluations(self.engine)
            self.assertEqual(caught.exception.code, 'journal_failed')

    def test_same_cursor_and_evaluation_time_must_match_the_recorded_transition(self):
        original = self.engine.state
        row = original.automatic.evaluations[0]
        for changed in (
            replace(row, evaluated_at=row.evaluated_at + timedelta(seconds=1)),
            replace(row, cursor=replace(row.cursor, bar_end=row.cursor.bar_end - timedelta(days=1))),
        ):
            self.engine.state = replace(original, automatic=replace(original.automatic, evaluations=(changed,)))
            self.unresolved()

    def test_prior_identical_claim_cannot_be_laundered_by_a_daily_named_snapshot(self):
        first = self.engine.journal.events[1]
        claimed = self.engine.journal.events[2]
        self.engine.journal.events[1] = replace(first, kind='automatic_evaluation_claimed')
        self.engine.journal.events[2] = replace(
            claimed,
            kind='daily_evaluation_claimed',
            payload=dumps(
                replace(
                    self.initial,
                    version=claimed.sequence,
                    automatic=replace(self.engine.state.automatic, evaluations=(replace(self.engine.state.automatic.evaluations[0], phase='CLAIMED'),)),
                )
            ),
        )
        self.unresolved()

    def test_latest_transition_must_be_the_daily_pure_claim(self):
        row = self.engine.state.automatic.evaluations[0]
        completed = complete_evaluation(self.engine.state.automatic, row.cursor, observed=True)
        self.persist('completed', replace(self.engine.state, automatic=completed))
        self.persist('automatic_evaluation_claimed', replace(self.engine.state, automatic=replace(completed, evaluations=(replace(row, phase='CLAIMED'),))))
        self.persist('startup', replace(self.engine.state, automatic=restart(self.engine.state.automatic)))
        self.unresolved()

    def test_only_interrupted_empty_daily_rows_are_discardable(self):
        initial = self.engine.state
        row = initial.automatic.evaluations[0]
        for changes in (
            {'phase': 'CLAIMED'},
            {'phase': 'COMPLETED'},
            {'order_result': OrderStatus.UNKNOWN},
            {'order_result': OrderStatus.ACCEPTED},
            {'order_id': 'canonical'},
        ):
            state = replace(initial, automatic=replace(initial.automatic, evaluations=(replace(row, **changes),)))
            self.engine.state = state
            recover_daily_evaluations(self.engine)
            self.assertIs(self.engine.state, state)

    def test_minute_cursor_is_never_discarded_even_with_a_daily_named_event(self):
        row = self.engine.state.automatic.evaluations[0]
        self.engine.state = self.initial
        self.engine.journal.events = self.engine.journal.events[:1]
        self.seed(cursor=replace(row.cursor, interval='5m'))
        self.unresolved()

    def test_current_record_must_exist_and_remain_typed_daily(self):
        initial = self.engine.state
        record = self.engine.record
        for strategies in (
            (),
            (replace(record, parameters=None),),
            (replace(record, parameters=replace(record.parameters, bar_interval='5m')),),
            (replace(record, version=2),),
        ):
            self.engine.state = replace(initial, strategies=strategies)
            self.unresolved()

    def test_saved_intent_of_every_phase_blocks_discard(self):
        initial = self.engine.state
        intent = create_intent(self.cursor, 'test-stock', 'ENTRY', self.cursor.instrument_id, '', 'a' * 64, self.calendar, self.engine.clock.now())
        for phase in ('READY', 'CLAIMED', 'UNKNOWN', 'DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED'):
            self.engine.state = replace(
                initial, automatic=replace(initial.automatic, daily=replace(initial.automatic.daily, intents=(replace(intent, phase=phase),)))
            )
            self.unresolved()

    def test_matching_known_order_is_left_for_canonical_report_reconciliation(self):
        self.engine.order(evaluation_key(self.cursor), status=OrderStatus.ACCEPTED)
        self.unresolved()

    def test_timezone_semantic_and_exit_namespace_matches_also_block(self):
        self.engine.order('auto:strategy:1:TWSE:0050:1d:' + self.cursor.bar_end.isoformat() + ':exit:lot', status=OrderStatus.FILLED)
        self.unresolved()

    def test_unrelated_known_reservation_and_existing_unknown_issue_stay_untouched(self):
        order = self.engine.order(evaluation_key(replace(self.cursor, bar_end=self.cursor.bar_end - timedelta(days=1))), status=OrderStatus.ACCEPTED)
        self.engine.state = replace(self.engine.state, issues=('outcome_unknown',), daily_pnl=Decimal('-17'))
        before = self.engine.state
        recover_daily_evaluations(self.engine)
        self.assertEqual(self.engine.state.orders, (order,))
        self.assertEqual(self.engine.state.issues, before.issues)
        self.assertEqual(self.engine.state.daily_pnl, before.daily_pnl)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'COMPLETED')

    def test_journal_claim_with_order_metadata_is_not_pure_even_if_current_row_was_erased(self):
        event = self.engine.journal.events[1]
        from quantlab.trading.application.codec import loads

        snapshot = loads(event.payload)
        row = snapshot.automatic.evaluations[0]
        for changes in ({'order_result': OrderStatus.ACCEPTED}, {'order_id': 'order'}):
            self.engine.journal.events[1] = replace(
                event, payload=dumps(replace(snapshot, automatic=replace(snapshot.automatic, evaluations=(replace(row, **changes),))))
            )
            self.unresolved()

    def test_actual_reconcile_daily_discards_only_pure_work_and_remains_paused(self):
        from quantlab.trading.application.daily_execution import reconcile_daily

        before = self.engine.state
        reconcile_daily(self.engine)
        after = self.engine.state
        self.assertEqual(after.automatic.evaluations[0].phase, 'COMPLETED')
        self.assertEqual(after.automatic.evaluations[0].code, 'daily_signal_invalidated')
        self.assertEqual(after.automatic.cursors, before.automatic.cursors)
        self.assertTrue(after.automatic.auto_paused)
        self.assertEqual(after.automatic.daily, before.automatic.daily)
        self.assertEqual(after.orders, before.orders)
        self.assertEqual(after.issues, before.issues)

    def test_actual_reconcile_daily_live_denies_before_recovery_journal(self):
        from quantlab.trading.application.daily_execution import reconcile_daily

        self.engine.configuration.environment = Environment.LIVE
        self.engine.state = replace(self.engine.state, automatic=replace(self.engine.state.automatic, evaluations=()))
        self.engine.journal.replay = Mock(side_effect=AssertionError('no LIVE journal'))
        with self.assertRaises(DomainError) as caught:
            reconcile_daily(self.engine)
        self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.engine.automatic_observation_validator.assert_not_called()

    def test_actual_reconcile_never_discards_unknown_dispatch_even_without_order(self):
        from quantlab.trading.application.daily_execution import reconcile_daily

        intent = create_intent(self.cursor, 'test-stock', 'ENTRY', self.cursor.instrument_id, '', 'a' * 64, self.calendar, self.engine.clock.now())
        before = replace(
            self.engine.state,
            automatic=replace(self.engine.state.automatic, daily=replace(self.engine.state.automatic.daily, intents=(replace(intent, phase='UNKNOWN'),))),
        )
        self.engine.state = before
        with self.assertRaises(DomainError) as caught:
            reconcile_daily(self.engine)
        self.assertEqual(caught.exception.code, 'daily_signal_unresolved')
        self.assertIs(self.engine.state, before)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'INTERRUPTED')
        self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'UNKNOWN')
