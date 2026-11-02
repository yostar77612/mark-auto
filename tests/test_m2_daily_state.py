"""Durable daily identities, verified-session dispatch, and irreversible claims."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from quantlab.trading.application.codec import dumps, loads, register
from quantlab.trading.application.daily_state import (
    DailyIntent,
    DailyState,
    append_batch,
    authorize,
    claim_dispatch,
    create_intent,
    expire,
    invalidate,
    next_session,
    record_result,
    restart,
    revoke,
)
from quantlab.trading.domain.auto_cycle import EvaluationCursor, evaluation_key_matches
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError

TZ = ZoneInfo('Asia/Taipei')
FP = 'a' * 64


class DailyStateTests(unittest.TestCase):
    def setUp(self):
        register(EvaluationCursor, DailyIntent, DailyState)
        self.origin = TradingSession(date(2026, 11, 6), datetime(2026, 11, 6, 8, 45, tzinfo=TZ), datetime(2026, 11, 6, 13, 45, tzinfo=TZ))
        night_only = TradingSession(date(2026, 11, 9), datetime(2026, 11, 6, 15, tzinfo=TZ), datetime(2026, 11, 7, 5, tzinfo=TZ), 'NIGHT')
        self.target = TradingSession(date(2026, 11, 10), datetime(2026, 11, 10, 8, 45, tzinfo=TZ), datetime(2026, 11, 10, 13, 45, tzinfo=TZ))
        later = TradingSession(date(2026, 11, 11), datetime(2026, 11, 11, 8, 45, tzinfo=TZ), datetime(2026, 11, 11, 13, 45, tzinfo=TZ))
        self.calendar = TradingCalendar('verified', 'fixture-v1', 'OFFLINE_VERIFIED_FIXTURE', (self.origin, night_only, self.target, later))
        self.cursor = EvaluationCursor('strategy', 2, 'TMF:202611', '1d', self.origin.closes_at.astimezone(timezone.utc))
        self.intent = self.make()

    def make(self, *, action='ENTRY', lot_id='', instrument_id='TMF:202611', cursor=None, calendar=None, created_at=None, fingerprint=FP):
        return create_intent(
            cursor or self.cursor, 'account', action, instrument_id, lot_id, fingerprint, calendar or self.calendar, created_at or self.origin.closes_at
        )

    def state(self, *intents):
        return authorize(append_batch(DailyState(), tuple(intents) or (self.intent,)), 'run', 'owner')

    def claim(self, state=None, intent=None, **values):
        arguments = dict(run_id='run', owner_stamp='owner', environment=Environment.BROKER_SIMULATION)
        arguments.update(values)
        now = arguments.pop('now', self.target.opens_at)
        calendar = arguments.pop('calendar', self.calendar)
        return claim_dispatch(state or self.state(), (intent or self.intent).key, now, calendar, **arguments)

    def rejected(self, code, function, *args, **kwargs):
        with self.assertRaises(DomainError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_safe_defaults_no_execution_economics_and_frozen_codec(self):
        self.assertEqual(DailyState(), DailyState((), '', '', False))
        self.assertFalse({'price', 'quantity', 'cash', 'reservation', 'evaluations'} & {row.name for row in fields(DailyIntent)})
        state = self.state()
        self.assertEqual(loads(dumps(state)), state)
        self.assertEqual(loads(dumps(state)).intents[0].key, self.intent.key)
        with self.assertRaises(FrozenInstanceError):
            self.intent.phase = 'CLAIMED'

    def test_keys_use_automatic_namespace_and_each_owned_exit_slot(self):
        base = f'auto:strategy:2:TMF:202611:1d:{self.cursor.bar_end.isoformat()}'
        self.assertEqual(self.intent.key, base)
        self.assertEqual(self.make(action='EXIT', lot_id='lot-a').key, base + ':exit:lot-a')
        self.assertNotEqual(self.make(action='EXIT', lot_id='lot-a').key, self.make(action='EXIT', lot_id='lot-b').key)
        actual = self.make(action='EXIT', lot_id='old-lot', instrument_id='TMF:202610')
        self.assertEqual(actual.instrument_id, 'TMF:202610')
        self.assertTrue(actual.key.startswith(base + ':exit:'))

    def test_taipei_key_survives_codec_timezone_normalization(self):
        intent = self.make(cursor=replace(self.cursor, bar_end=self.origin.closes_at))
        self.assertEqual(loads(dumps(intent)).key, intent.key)

    def test_legacy_timezone_keys_match_semantically_and_invalid_identities_do_not(self):
        prefix = 'auto:strategy:2:TMF:202611:1d:'
        legacy = prefix + self.origin.closes_at.isoformat()
        self.assertTrue(evaluation_key_matches(legacy, self.cursor))
        self.assertTrue(evaluation_key_matches(legacy + ':exit:old-lot', self.cursor))
        for key in (
            prefix + self.origin.closes_at.replace(tzinfo=None).isoformat(),
            prefix + 'malformed',
            legacy.replace('strategy:2:', 'other:2:'),
            legacy.replace(':1d:', ':5m:'),
            legacy.replace(':202611:', ':202612:'),
            prefix + (self.origin.closes_at + timedelta(seconds=1)).isoformat(),
        ):
            with self.subTest(key=key):
                self.assertFalse(evaluation_key_matches(key, self.cursor))

    def test_next_day_uses_verified_gaps_and_skips_night_only_dates(self):
        self.assertEqual(next_session(self.calendar, self.cursor), self.target)
        self.assertEqual(
            (self.intent.target_trade_date, self.intent.not_before, self.intent.deadline), (self.target.trade_date, self.target.opens_at, self.target.closes_at)
        )

    def test_close_requires_daily_exact_verified_day_close_and_forward_coverage(self):
        self.rejected('validation_failed', self.make, cursor=replace(self.cursor, interval='5m'))
        self.rejected('daily_close_unverified', self.make, cursor=replace(self.cursor, bar_end=self.cursor.bar_end - timedelta(seconds=1)))
        night = self.calendar.sessions[1]
        self.rejected('daily_close_unverified', next_session, self.calendar, replace(self.cursor, bar_end=night.closes_at))
        self.rejected('daily_close_unverified', self.make, cursor=replace(self.cursor, bar_end=night.closes_at))
        self.rejected('calendar_missing', self.make, calendar=replace(self.calendar, sessions=(self.origin,)))

    def test_close_observation_cannot_precede_close_or_catch_up_at_next_open(self):
        for value in (self.origin.closes_at - timedelta(microseconds=1), self.target.opens_at, self.target.opens_at + timedelta(seconds=1)):
            self.rejected('daily_close_unverified', self.make, created_at=value)
        self.assertEqual(self.make(created_at=self.target.opens_at - timedelta(microseconds=1)).deadline, self.target.closes_at)

    def test_daily_action_lot_and_fingerprint_contract(self):
        for action, lot in (('ENTER', ''), ('EXIT', ''), ('ENTRY', 'lot')):
            self.rejected('validation_failed', self.make, action=action, lot_id=lot)
        for fingerprint in ('a' * 63, 'A' * 64, 'g' * 64, None):
            self.rejected('validation_failed', self.make, fingerprint=fingerprint)

    def test_daily_identities_and_times_are_bounded_domain_values(self):
        for account, instrument in (('', 'TMF'), ('account', '')):
            self.rejected('validation_failed', create_intent, self.cursor, account, 'ENTRY', instrument, '', FP, self.calendar, self.origin.closes_at)
        self.rejected('validation_failed', self.make, lot_id='bad\nlot', action='EXIT')
        self.rejected('validation_failed', self.make, created_at=self.origin.closes_at.replace(tzinfo=None))

    def test_batch_is_all_exits_in_lot_order_then_entry_and_preserves_grant(self):
        state = authorize(DailyState(), 'run', 'owner')
        a, b = self.make(action='EXIT', lot_id='a'), self.make(action='EXIT', lot_id='b')
        stored = append_batch(state, (self.intent, b, a))
        self.assertEqual(stored.intents, (a, b, self.intent))
        self.assertEqual((stored.authorized_run, stored.owner_stamp, stored.waiting_session), ('run', 'owner', True))
        self.assertEqual(append_batch(stored, ()), stored)
        self.assertEqual(append_batch(stored, (a, b, self.intent)), stored)
        active = authorize(stored, 'next-run', 'owner')
        self.assertEqual(append_batch(active, (a, b, self.intent)), active)

    def test_batch_rejects_mixed_close_or_account(self):
        exit_intent = self.make(action='EXIT', lot_id='a')
        for row in (replace(exit_intent, cursor=replace(self.cursor, version=3)), replace(exit_intent, account_ref='other')):
            self.rejected('daily_signal_invalidated', append_batch, DailyState(), (self.intent, row))

    def test_batch_rejects_duplicate_keys_and_nonready_or_result_payload(self):
        self.rejected('daily_signal_invalidated', append_batch, DailyState(), (self.intent, self.intent))
        for row in (replace(self.intent, phase='DISPATCHED'), replace(self.intent, order_id='order'), replace(self.intent, code='risk_rejected')):
            self.rejected('daily_signal_invalidated', append_batch, DailyState(), (row,))

    def test_existing_identity_cannot_be_rewritten_or_terminal_reanimated(self):
        for change in ({'instrument_id': 'other'}, {'evidence_fingerprint': 'b' * 64}, {'deadline': self.target.closes_at + timedelta(seconds=1)}):
            self.rejected('daily_signal_invalidated', append_batch, self.state(), (replace(self.intent, **change),))
        terminal = replace(self.state(), intents=(replace(self.intent, phase='EXPIRED'),))
        self.rejected('daily_signal_invalidated', append_batch, terminal, (self.intent,))

    def test_authorize_requires_both_server_grants_and_keeps_terminal_phases(self):
        for run, owner in (('', 'owner'), ('run', '')):
            self.rejected('daily_signal_not_authorized', authorize, DailyState(), run, owner)
        phases = ('DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED')
        state = DailyState(tuple(replace(self.intent, phase=phase) for phase in phases), waiting_session=True)
        authorized = authorize(state, 'run', 'owner')
        self.assertEqual(tuple(row.phase for row in authorized.intents), phases)
        self.assertFalse(authorized.waiting_session)

    def test_authorize_never_bypasses_inflight_or_unknown(self):
        for phase in ('CLAIMED', 'UNKNOWN'):
            self.rejected('daily_signal_unresolved', authorize, DailyState((replace(self.intent, phase=phase),)), 'new-run', 'new-owner')

    def test_revoke_preserves_identities_and_removes_run_owner_and_wait(self):
        state = replace(self.state(), waiting_session=True)
        self.assertEqual(revoke(state), DailyState(state.intents))

    def test_restart_marks_claimed_unknown_but_never_changes_ready_or_terminal_identity(self):
        rows = tuple(
            replace(self.intent, action='EXIT', lot_id=str(index), phase=phase, order_id='order-' + str(index))
            for index, phase in enumerate(('READY', 'CLAIMED', 'UNKNOWN', 'DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED'))
        )
        state = DailyState(rows, 'run', 'owner', True)
        restored = restart(loads(dumps(state)))
        self.assertEqual((restored.authorized_run, restored.owner_stamp, restored.waiting_session), ('', '', False))
        self.assertEqual(
            tuple(row.phase for row in restored.intents), ('READY', 'UNKNOWN', 'UNKNOWN', 'DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED')
        )
        self.assertEqual(tuple(row.key for row in restored.intents), tuple(row.key for row in rows))
        self.assertEqual(tuple(row.order_id for row in restored.intents), tuple(row.order_id for row in rows))
        self.assertEqual(restored.intents[2:], rows[2:])
        self.rejected('daily_signal_unresolved', authorize, restored, 'new-run', 'owner')

    def test_dispatch_claim_is_durable_identity_only_and_supports_entire_next_day(self):
        for now in (self.target.opens_at, self.target.opens_at + timedelta(minutes=45), self.target.closes_at - timedelta(microseconds=1)):
            state = self.claim(now=now)
            self.assertEqual(state.intents[0], replace(self.intent, phase='CLAIMED'))
            self.assertFalse(state.waiting_session)

    def test_dispatch_rejects_before_open_exact_close_and_later_days(self):
        self.rejected('daily_waiting_session', self.claim, now=self.target.opens_at - timedelta(microseconds=1))
        for now in (self.target.closes_at, self.target.closes_at + timedelta(days=1)):
            self.rejected('daily_signal_expired', self.claim, now=now)

    def test_dispatch_needs_exact_current_run_and_owner(self):
        for change in ({'run_id': ''}, {'run_id': 'old'}, {'owner_stamp': ''}, {'owner_stamp': 'other'}):
            self.rejected('daily_signal_not_authorized', self.claim, **change)
        for state in (revoke(self.state()), replace(self.state(), owner_stamp='')):
            self.rejected('daily_signal_not_authorized', self.claim, state)
        self.rejected('daily_signal_not_authorized', self.claim, replace(self.state(), authorized_run=''), run_id='')
        self.rejected('daily_signal_not_authorized', self.claim, replace(self.state(), owner_stamp=''), owner_stamp='')

    def test_dispatch_live_and_local_cannot_claim(self):
        self.rejected('production_orders_disabled', self.claim, environment=Environment.LIVE)
        self.rejected('capability_missing', self.claim, environment=Environment.LOCAL)

    def test_dispatch_missing_or_terminal_identity_never_reuses_slot(self):
        self.rejected(
            'daily_signal_invalidated',
            claim_dispatch,
            self.state(),
            'missing',
            self.target.opens_at,
            self.calendar,
            run_id='run',
            owner_stamp='owner',
            environment=Environment.BROKER_SIMULATION,
        )
        for phase in ('DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED'):
            self.rejected('daily_signal_invalidated', self.claim, replace(self.state(), intents=(replace(self.intent, phase=phase),)))
        for phase in ('CLAIMED', 'UNKNOWN'):
            self.rejected('daily_signal_unresolved', self.claim, replace(self.state(), intents=(replace(self.intent, phase=phase),)))

    def test_dispatch_calendar_identity_version_and_recorded_window_cannot_drift(self):
        for calendar in (replace(self.calendar, calendar_id='new'), replace(self.calendar, version='new')):
            self.rejected('daily_signal_invalidated', self.claim, calendar=calendar)
        for change in (
            {'target_trade_date': date(2026, 11, 11)},
            {'not_before': self.target.opens_at + timedelta(minutes=1)},
            {'deadline': self.target.closes_at + timedelta(minutes=1)},
        ):
            self.rejected('daily_signal_invalidated', self.claim, replace(self.state(), intents=(replace(self.intent, **change),)))

    def test_dispatch_detects_same_version_session_change(self):
        changed = replace(self.target, closes_at=self.target.closes_at - timedelta(minutes=1))
        calendar = replace(self.calendar, sessions=(*self.calendar.sessions[:2], changed, self.calendar.sessions[-1]))
        self.rejected('daily_signal_invalidated', self.claim, calendar=calendar)

    def test_exit_order_is_enforced_before_entry_and_later_lots(self):
        a, b = self.make(action='EXIT', lot_id='a'), self.make(action='EXIT', lot_id='b')
        state = self.state(self.intent, b, a)
        self.rejected('daily_signal_unresolved', self.claim, state, b)
        self.rejected('daily_signal_unresolved', self.claim, state, self.intent)
        state = self.claim(state, a)
        self.rejected('daily_signal_unresolved', self.claim, state, b)
        state = record_result(state, a.key, known=True, order_id='order-a')
        state = self.claim(state, b)
        state = record_result(state, b.key, known=True, code='exit_unavailable')
        self.assertEqual(state.intents[1].phase, 'KNOWN_NO_ORDER')
        self.assertEqual(self.claim(state).intents[-1].phase, 'CLAIMED')

    def test_unrelated_close_does_not_impose_exit_sequence(self):
        other = self.make(action='EXIT', lot_id='old', cursor=replace(self.cursor, version=1))
        state = replace(self.state(), intents=(other, self.intent))
        self.assertEqual(self.claim(state).intents[-1].phase, 'CLAIMED')

    def test_unknown_preceding_exit_blocks_same_close_even_if_an_old_grant_remains(self):
        previous = replace(self.make(action='EXIT', lot_id='a'), phase='UNKNOWN')
        state = replace(self.state(), intents=(previous, self.intent))
        self.rejected('daily_signal_unresolved', self.claim, state)

    def test_result_known_order_and_no_order_are_terminal_and_idempotent(self):
        for order_id, code, phase in (('order', '', 'DISPATCHED'), ('', 'risk_rejected', 'KNOWN_NO_ORDER')):
            state = record_result(self.claim(), self.intent.key, known=True, order_id=order_id, code=code)
            self.assertEqual((state.intents[0].phase, state.intents[0].code), (phase, code))
            self.assertEqual(record_result(state, self.intent.key, known=True, order_id=order_id, code=code), state)
            self.rejected('daily_signal_invalidated', self.claim, state)

    def test_result_requires_a_dispatch_claim_and_its_exact_key(self):
        self.rejected('daily_signal_unresolved', record_result, self.state(), self.intent.key, known=True, order_id='order')
        self.rejected('daily_signal_invalidated', record_result, self.claim(), 'missing', known=True, order_id='order')

    def test_unknown_revokes_all_remaining_batch_authority_and_retains_order(self):
        a = self.make(action='EXIT', lot_id='a')
        state = self.claim(self.state(a, self.intent), a)
        state = record_result(state, a.key, known=False, order_id='maybe-order')
        self.assertEqual((state.intents[0].phase, state.intents[0].order_id), ('UNKNOWN', 'maybe-order'))
        self.assertEqual(state.intents[0].code, 'daily_signal_unresolved')
        self.assertEqual((state.authorized_run, state.owner_stamp, state.waiting_session), ('', '', False))
        self.assertEqual(record_result(state, a.key, known=False, order_id='maybe-order'), state)
        self.rejected('daily_signal_not_authorized', self.claim, state)

    def test_unknown_requires_observed_positive_order_and_no_never_sent_reset(self):
        unknown = record_result(self.claim(), self.intent.key, known=False)
        for arguments in ({'known': True, 'order_id': 'order'}, {'known': True, 'observed': True}, {'known': False, 'observed': True, 'order_id': 'order'}):
            self.rejected('daily_signal_unresolved', record_result, unknown, self.intent.key, **arguments)
        resolved = record_result(unknown, self.intent.key, known=True, order_id='order', observed=True)
        self.assertEqual(resolved.intents[0].phase, 'DISPATCHED')
        self.assertEqual((resolved.authorized_run, resolved.owner_stamp), ('', ''))
        self.assertEqual(authorize(resolved, 'new-run', 'owner').intents, resolved.intents)

    def test_order_identity_cannot_change_during_result_or_resolution(self):
        state = record_result(self.claim(), self.intent.key, known=False, order_id='canonical')
        self.rejected('daily_signal_invalidated', record_result, state, self.intent.key, known=True, order_id='other', observed=True)
        self.rejected('daily_signal_invalidated', record_result, state, self.intent.key, known=True, observed=True)

    def test_expiry_only_changes_ready_and_never_washes_inflight(self):
        phases = ('READY', 'CLAIMED', 'UNKNOWN', 'DISPATCHED', 'KNOWN_NO_ORDER', 'INVALIDATED')
        rows = tuple(replace(self.intent, action='EXIT', lot_id=str(index), phase=phase, order_id='order-' + str(index)) for index, phase in enumerate(phases))
        state = DailyState(rows, 'run', 'owner', True)
        self.assertEqual(expire(state, self.target.closes_at - timedelta(microseconds=1)), state)
        expired = expire(state, self.target.closes_at)
        self.assertEqual(tuple(row.phase for row in expired.intents), ('EXPIRED', *phases[1:]))
        self.assertEqual(expired.intents[1:], rows[1:])
        self.assertEqual((expired.authorized_run, expired.owner_stamp, expired.waiting_session), ('run', 'owner', False))

    def test_expiry_keeps_waiting_for_a_different_future_ready_session(self):
        later = replace(self.intent, cursor=replace(self.cursor, version=3), deadline=self.target.closes_at + timedelta(days=1))
        state = DailyState((self.intent, later), 'run', 'owner', True)
        self.assertTrue(expire(state, self.target.closes_at).waiting_session)
        self.assertFalse(expire(self.state(), self.target.opens_at).waiting_session)

    def test_invalidation_only_retires_ready_target_with_reason(self):
        other = self.make(action='EXIT', lot_id='other')
        state = DailyState((self.intent, other), 'run', 'owner', True)
        invalid = invalidate(state, self.intent.key, 'strategy_evidence_stale')
        self.assertEqual((invalid.intents[0].phase, invalid.intents[0].code), ('INVALIDATED', 'strategy_evidence_stale'))
        self.assertEqual(invalid.intents[1], other)
        self.assertTrue(invalid.waiting_session)
        self.assertEqual((invalid.authorized_run, invalid.owner_stamp), ('run', 'owner'))
        self.assertFalse(invalidate(self.state(), self.intent.key).waiting_session)

    def test_invalidation_cannot_erase_claimed_unknown_or_terminal_outcomes(self):
        for phase in ('CLAIMED', 'UNKNOWN', 'DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED'):
            state = DailyState((replace(self.intent, phase=phase, order_id='order'),), 'run', 'owner')
            self.assertEqual(invalidate(state, self.intent.key), state)
        self.rejected('daily_signal_invalidated', invalidate, self.state(), 'missing')


if __name__ == '__main__':
    unittest.main()
