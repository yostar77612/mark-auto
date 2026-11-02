"""Pure state safety cases; no broker, UI or product writes."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
import unittest

from quantlab.trading.domain.auto_cycle import EvaluationCursor, ForceExitWindow
from quantlab.trading.application.automatic_state import (
    AutomaticState,
    ForcedAttempt,
    claim_cursor,
    claim_force_attempt,
    complete_evaluation,
    pause,
    restart,
    resume,
    transition_force_attempt,
)
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.state import AppState
from quantlab.trading.domain.models import OrderStatus as S

T = datetime(2026, 11, 2, 5, tzinfo=timezone.utc)
C = EvaluationCursor('strategy', 1, 'TMF-202611', '5m', T + timedelta(minutes=5))
W = ForceExitWindow(T, T + timedelta(minutes=8), T + timedelta(minutes=10))


class AutomaticStateTests(unittest.TestCase):
    def active(self):
        return resume(AutomaticState(), T, user_confirmed=True, reconciled=True, preflight_passed=True)

    def claimed(self):
        return claim_cursor(self.active(), C, C.bar_end)

    def attempt(self, status=S.SUBMITTING, number=1):
        return replace(AutomaticState(), forced_attempts=(ForcedAttempt('lot', number, T, status, 'order'),))

    def test_additive_safe_defaults_and_codec(self):
        old = json.loads(dumps(AutomaticState()))
        old['fields'] = {}
        restored = loads(json.dumps(old))
        self.assertEqual(restored, AutomaticState())
        self.assertTrue(restored.auto_paused)
        self.assertEqual(restored.reasons, ('program_restarted',))
        state = claim_force_attempt(self.claimed(), 'lot', W, T)
        self.assertEqual(loads(dumps(state)), state)
        with self.assertRaises(FrozenInstanceError):
            state.auto_paused = True

    def test_manual_state_changes_cannot_resume_automatic(self):
        automatic = AutomaticState()
        app = replace(AppState(), stopped=False, manual_stopped=False, reconciled=True)
        self.assertFalse(app.stopped)
        self.assertIsNone(claim_cursor(automatic, C, C.bar_end))
        self.assertEqual(automatic, AutomaticState())

    def test_pause_retains_history_and_reasons(self):
        state = pause(pause(self.claimed(), 'stale_quote'), 'stale_quote')
        self.assertTrue(state.auto_paused)
        self.assertEqual(state.reasons, ('stale_quote',))
        self.assertEqual(state.cursors, (C,))
        self.assertEqual(state.resumed_at, T)

    def test_resume_requires_each_current_proof(self):
        for field in ('user_confirmed', 'reconciled', 'preflight_passed'):
            flags = dict(user_confirmed=True, reconciled=True, preflight_passed=True)
            flags[field] = False
            with self.subTest(field=field):
                self.assertIsNone(resume(AutomaticState(), T, **flags))

    def test_resume_blocks_each_uncertain_evaluation(self):
        for phase, result in (('CLAIMED', None), ('INTERRUPTED', None), ('COMPLETED', S.UNKNOWN)):
            state = replace(self.claimed(), evaluations=(replace(self.claimed().evaluations[0], phase=phase, order_result=result),))
            self.assertIsNone(resume(state, T, user_confirmed=True, reconciled=True, preflight_passed=True))

    def test_resume_blocks_each_uncertain_force_attempt(self):
        for status in (S.SUBMITTING, S.UNKNOWN, S.CANCEL_PENDING):
            self.assertIsNone(resume(self.attempt(status), T, user_confirmed=True, reconciled=True, preflight_passed=True))

    def test_restart_preserves_cursor_and_marks_inflight(self):
        state = replace(
            self.claimed(), forced_attempts=(ForcedAttempt('a', 1, T), ForcedAttempt('b', 1, T, S.CANCEL_PENDING), ForcedAttempt('c', 1, T, S.ACCEPTED))
        )
        restored = restart(loads(dumps(state)))
        self.assertTrue(restored.auto_paused)
        self.assertIn('program_restarted', restored.reasons)
        self.assertEqual(restored.cursors, (C,))
        self.assertEqual(restored.evaluations[0].phase, 'INTERRUPTED')
        self.assertEqual(tuple(row.status for row in restored.forced_attempts), (S.UNKNOWN, S.UNKNOWN, S.ACCEPTED))
        self.assertIsNone(claim_force_attempt(restored, 'a', W, T + timedelta(seconds=30)))

    def test_cursor_requires_automatic_resume_and_fresh_completed_time(self):
        self.assertIsNone(claim_cursor(AutomaticState(), C, C.bar_end))
        self.assertIsNone(claim_cursor(pause(self.active(), 'stale_quote'), C, C.bar_end))
        self.assertIsNone(claim_cursor(replace(self.active(), resumed_at=None), C, C.bar_end))
        self.assertIsNone(claim_cursor(self.active(), replace(C, bar_end=T), C.bar_end))
        self.assertIsNone(claim_cursor(self.active(), replace(C, bar_end=T - timedelta(seconds=1)), C.bar_end))
        self.assertIsNone(claim_cursor(self.active(), C, C.bar_end - timedelta(seconds=1)))
        self.assertIsNotNone(self.claimed())

    def test_claim_is_durable_before_execution_and_not_replayed(self):
        state = self.claimed()
        later = replace(C, bar_end=C.bar_end + timedelta(minutes=5))
        self.assertIsNone(claim_cursor(loads(dumps(state)), C, C.bar_end))
        self.assertIsNone(claim_cursor(state, later, later.bar_end))
        completed = complete_evaluation(state, C, S.ACCEPTED, order_id='one')
        self.assertIsNone(claim_cursor(completed, C, C.bar_end))
        self.assertIsNone(claim_cursor(completed, replace(C, bar_end=C.bar_end - timedelta(seconds=1)), C.bar_end))
        self.assertIsNotNone(claim_cursor(completed, later, later.bar_end))

    def test_distinct_identity_keeps_independent_cursor(self):
        for field, value in (('strategy_id', 'second'), ('version', 2), ('instrument_id', 'TMF-202612'), ('interval', '1m')):
            state = claim_cursor(self.claimed(), replace(C, **{field: value}), C.bar_end)
            self.assertEqual(len(state.cursors), 2)
        completed = complete_evaluation(self.claimed(), C)
        next_cursor = replace(C, bar_end=C.bar_end + timedelta(minutes=5))
        state = claim_cursor(completed, next_cursor, next_cursor.bar_end)
        self.assertEqual(state.cursors, (next_cursor,))

    def test_evaluation_completion_matches_claim_and_order(self):
        self.assertIsNone(complete_evaluation(self.claimed(), replace(C, version=2)))
        completed = complete_evaluation(self.claimed(), C, S.ACCEPTED, order_id='one')
        self.assertIsNone(complete_evaluation(completed, C, S.FILLED, order_id='two', observed=True))
        self.assertIsNone(complete_evaluation(completed, C, S.FILLED, order_id='one'))
        newer = replace(C, bar_end=C.bar_end + timedelta(minutes=5))
        advanced = claim_cursor(completed, newer, newer.bar_end)
        self.assertIsNone(complete_evaluation(advanced, C, S.FILLED, order_id='one', observed=True))

    def test_unknown_evaluation_stops_and_requires_observed_resolution(self):
        unknown = complete_evaluation(self.claimed(), C, S.UNKNOWN, order_id='one')
        self.assertTrue(unknown.auto_paused)
        self.assertIn('order_result_unknown', unknown.reasons)
        self.assertIsNone(complete_evaluation(unknown, C, S.REJECTED, order_id='one'))
        self.assertIsNone(complete_evaluation(unknown, C, S.UNKNOWN, order_id='one', observed=True))
        self.assertIsNone(complete_evaluation(unknown, C, None, order_id='one', observed=True))
        resolved = complete_evaluation(unknown, C, S.REJECTED, order_id='one', observed=True)
        self.assertTrue(resolved.auto_paused)
        self.assertIsNotNone(resume(resolved, C.bar_end, user_confirmed=True, reconciled=True, preflight_passed=True))

    def test_restarted_evaluation_needs_observation_before_resume(self):
        state = restart(self.claimed())
        self.assertIsNone(complete_evaluation(state, C))
        resolved = complete_evaluation(state, C, observed=True)
        active = resume(resolved, C.bar_end, user_confirmed=True, reconciled=True, preflight_passed=True)
        self.assertIsNone(claim_cursor(active, C, C.bar_end))

    def test_force_claim_works_while_paused_with_stable_key(self):
        state = claim_force_attempt(AutomaticState(), 'lot', W, T)
        self.assertTrue(state.auto_paused)
        self.assertEqual(state.forced_attempts[0].key, 'forced-exit:lot:1')
        self.assertEqual(state.forced_attempts[0].status, S.SUBMITTING)
        self.assertIsNone(claim_force_attempt(state, 'lot', W, T + timedelta(seconds=30)))
        second = claim_force_attempt(state, 'other', W, T)
        self.assertEqual(len(second.forced_attempts), 2)

    def test_force_retry_only_confirmed_terminal_miss(self):
        for status in (S.SUBMITTING, S.ACCEPTED, S.PARTIALLY_FILLED, S.CANCEL_PENDING, S.UNKNOWN, S.FILLED):
            self.assertIsNone(claim_force_attempt(self.attempt(status), 'lot', W, T + timedelta(seconds=30)))
        for status in (S.CANCELED, S.REJECTED):
            state = claim_force_attempt(self.attempt(status, 4), 'lot', W, T + timedelta(seconds=30))
            self.assertEqual(state.forced_attempts[0].key, 'forced-exit:lot:5')
            self.assertEqual(len(state.forced_attempts), 1)

    def test_force_timing_guard(self):
        self.assertIsNone(claim_force_attempt(AutomaticState(), 'lot', W, T - timedelta(seconds=1)))
        self.assertIsNone(claim_force_attempt(AutomaticState(), 'lot', W, W.retry_cutoff + timedelta(seconds=1)))
        self.assertIsNone(claim_force_attempt(self.attempt(S.CANCELED), 'lot', W, T + timedelta(seconds=29)))
        self.assertIsNotNone(claim_force_attempt(self.attempt(S.CANCELED), 'lot', W, W.retry_cutoff))

    def test_force_transitions_match_attempt_and_order(self):
        state = self.attempt()
        self.assertIsNone(transition_force_attempt(state, 'other', 1, S.ACCEPTED, order_id='order'))
        self.assertIsNone(transition_force_attempt(state, 'lot', 2, S.ACCEPTED, order_id='order'))
        self.assertIsNone(transition_force_attempt(state, 'lot', 1, S.ACCEPTED, order_id='wrong'))
        accepted = transition_force_attempt(state, 'lot', 1, S.ACCEPTED, order_id='order')
        self.assertEqual(accepted.forced_attempts[0].status, S.ACCEPTED)
        self.assertIsNone(transition_force_attempt(accepted, 'lot', 1, S.REJECTED, order_id='order'))

    def test_force_cancel_receipt_does_not_authorize_retry(self):
        pending = transition_force_attempt(self.attempt(S.ACCEPTED), 'lot', 1, S.CANCEL_PENDING, order_id='order')
        self.assertIsNone(transition_force_attempt(pending, 'lot', 1, S.CANCELED, order_id='order'))
        canceled = transition_force_attempt(pending, 'lot', 1, S.CANCELED, order_id='order', observed=True)
        self.assertIsNotNone(claim_force_attempt(canceled, 'lot', W, T + timedelta(seconds=30)))

    def test_trusted_terminal_cancel_need_not_invent_a_cancel_request_phase(self):
        for status in (S.ACCEPTED, S.PARTIALLY_FILLED):
            state = self.attempt(status)
            self.assertIsNone(transition_force_attempt(state, 'lot', 1, S.CANCELED, order_id='order'))
            canceled = transition_force_attempt(state, 'lot', 1, S.CANCELED, order_id='order', observed=True)
            self.assertEqual(canceled.forced_attempts[0].status, S.CANCELED)
            self.assertIsNotNone(claim_force_attempt(canceled, 'lot', W, T + timedelta(seconds=30)))

    def test_force_unknown_stops_never_retries_and_observed_only(self):
        unknown = transition_force_attempt(self.attempt(), 'lot', 1, S.UNKNOWN, order_id='order')
        self.assertTrue(unknown.auto_paused)
        self.assertIn('order_result_unknown', unknown.reasons)
        self.assertIsNone(transition_force_attempt(unknown, 'lot', 1, S.REJECTED, order_id='order'))
        resolved = transition_force_attempt(unknown, 'lot', 1, S.REJECTED, order_id='order', observed=True)
        self.assertTrue(resolved.auto_paused)
        self.assertIsNotNone(claim_force_attempt(resolved, 'lot', W, T + timedelta(seconds=30)))
        self.assertIsNone(transition_force_attempt(unknown, 'lot', 1, S.SUBMITTING, order_id='order', observed=True))

    def test_force_terminal_cannot_regress_or_take_late_callback(self):
        for status in (S.CANCELED, S.REJECTED, S.FILLED):
            self.assertIsNone(transition_force_attempt(self.attempt(status), 'lot', 1, S.ACCEPTED, order_id='order', observed=True))
        retried = claim_force_attempt(self.attempt(S.CANCELED), 'lot', W, T + timedelta(seconds=30))
        self.assertIsNone(transition_force_attempt(retried, 'lot', 1, S.FILLED, order_id='order', observed=True))


if __name__ == '__main__':
    unittest.main()
