"""Explicit daily no-send resolution: full journal proof plus current native cache."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import MethodType
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import test_m2_automatic as memory
import test_m2_daily_native as native
import test_m2_daily_runtime as runtime_fixtures
from test_live_order_guard import GuardJournal
from quantlab.trading.application.automatic_state import restart
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import DailyNotSentForm, UiAction, UiCommand
from quantlab.trading.application.daily_execution import dispatch_daily, reconcile_daily
from quantlab.trading.application import daily_resolution
from quantlab.trading.application.daily_resolution import _same_key, declare_daily_not_sent
from quantlab.trading.application.daily_state import DailyState, claim_dispatch, create_intent
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.manual_book import ManualRequest
from quantlab.trading.application.manual_contracts import ManualScope
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.state import LocalOrder
from quantlab.trading.domain.auto_cycle import EvaluationCursor
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import Environment, OrderPlan, OrderStatus, PositionLot, Reservation, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder, BrokerPosition
from quantlab.trading.ports.manual import UnmappedBrokerOrder

D = Decimal
SIM = Environment.BROKER_SIMULATION


class ResolutionFixture:
    def __init__(self, *, action='ENTRY', restarted=True):
        initialize()
        engine = self.engine = memory.MemoryEngine()
        engine.journal = GuardJournal()
        engine.ownership_clock = engine.clock.now
        engine._persist = MethodType(TradingEngine._persist, engine)
        engine.record = replace(engine.make_record(interval='1d'), evidence_hash='a' * 64)
        calendar = calendar_for_instrument(engine.calendar, engine.catalog.instruments[0])
        target = calendar.day_session(engine.state.trading_day)
        origin = tuple(row for row in calendar.sessions if row.kind == 'DAY' and row.trade_date < target.trade_date)[-1]
        engine.clock.value = target.opens_at
        self.cursor = EvaluationCursor(engine.record.strategy_id, engine.record.version, engine.record.form.instrument_id, '1d', origin.closes_at)
        self.lot = PositionLot(
            'owned-exit-lot',
            'test-stock',
            self.cursor.instrument_id,
            engine.record.strategy_id,
            1,
            engine.record.policy,
            1000,
            D('10'),
            origin.trade_date,
            1000,
        )
        self.intent = create_intent(
            self.cursor,
            'test-stock',
            action,
            self.cursor.instrument_id,
            self.lot.lot_id if action == 'EXIT' else '',
            engine.record.evidence_hash,
            calendar,
            origin.closes_at,
        )
        daily = DailyState((self.intent,), 'owner-authorized-run', engine.automatic_owner_stamp())
        state = replace(
            engine.state,
            strategies=(engine.record,),
            positions=(self.lot,) if action == 'EXIT' else (),
            automatic=replace(engine.state.automatic, auto_paused=False, resumed_at=origin.opens_at, daily=daily),
            stopped=False,
        )
        engine._persist('daily_signals_saved', state)
        claimed = claim_dispatch(
            daily, self.intent.key, engine.clock.now(), calendar, run_id=daily.authorized_run, owner_stamp=daily.owner_stamp, environment=SIM
        )
        engine._persist('daily_dispatch_claimed', replace(engine.state, automatic=replace(engine.state.automatic, daily=claimed)))
        if restarted:
            engine._persist('startup_reconciliation_required', replace(engine.state, automatic=restart(engine.state.automatic), stopped=True, reconciled=False))
            engine.refresh_facts()
            engine._persist('manual_account_observed', replace(engine.state, reconciled=True))
        if action == 'EXIT':
            observation = engine.manual_observations['test-stock']
            position = BrokerPosition('test-stock', self.cursor.instrument_id, 1000, 1000, engine.catalog.instruments[0].unit, D('10'))
            engine.manual_observations['test-stock'] = replace(observation, positions=(position,))
        self.form = DailyNotSentForm(self.intent.key, True)

    def rewrite(self, index, transform=lambda state: state, *, kind=None, sequence=None):
        event = self.engine.journal.events[index]
        self.engine.journal.events[index] = replace(
            event, payload=dumps(transform(loads(event.payload))), kind=kind or event.kind, sequence=event.sequence if sequence is None else sequence
        )

    def local_order(self, key=None, *, side=Side.BUY, instrument_id=None):
        engine = self.engine
        spec = engine.catalog.instruments[0]
        now = engine.clock.now()
        plan = OrderPlan(
            'stored-order-plan',
            'test-stock',
            SIM,
            instrument_id or self.intent.instrument_id,
            engine.record.strategy_id,
            1,
            side,
            1000,
            spec.unit,
            D('10'),
            D('9'),
            False,
            now,
            now + timedelta(seconds=30),
            engine.state.version,
        )
        reserve = Reservation('stored-order', 'test-stock', plan.instrument_id, spec.underlying, D('10000'), D('100'), 1000, OrderStatus.RESERVED)
        return LocalOrder('stored-order', key or self.intent.key, 'stored-command-hash', plan, engine.record.policy, reserve, OrderStatus.SUBMITTING)

    def broker_order(self, *, side=Side.BUY, instrument_id=None, quantity=2000, price=D('99')):
        order = self.local_order('different-key', side=side, instrument_id=instrument_id)
        plan = replace(order.plan, quantity=quantity, limit_price=price)
        return BrokerOrder('broker-only-id', plan, 0, D('0'), OrderStatus.CANCELED, 'broker-reconciliation-reference', self.engine.clock.now())


class DailyNotSentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ResolutionFixture()
        self.engine = self.fixture.engine

    def refuse(self, *, fixture=None, form=None, code=None, account_ref=''):
        fixture = fixture or self.fixture
        before = fixture.engine.state
        with self.assertRaises(DomainError) as caught:
            declare_daily_not_sent(fixture.engine, form if form is not None else fixture.form, account_ref=account_ref)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertIs(fixture.engine.state, before)

    def test_confirmed_complete_unsent_claim_closes_without_releasing_money_or_resuming(self):
        engine = self.engine
        before = engine.state
        result = declare_daily_not_sent(engine, self.fixture.form, account_ref='test-stock')
        self.assertEqual(result, self.fixture.intent.key)
        row = engine.state.automatic.daily.intents[0]
        self.assertEqual((row.phase, row.code, row.order_id), ('KNOWN_NO_ORDER', 'daily_declared_not_sent', ''))
        self.assertTrue(engine.state.stopped)
        self.assertTrue(engine.state.automatic.auto_paused)
        self.assertFalse(engine.state.automatic.daily.authorized_run)
        self.assertFalse(engine.state.automatic.daily.owner_stamp)
        self.assertEqual(replace(engine.state, version=before.version, events=before.events, automatic=before.automatic, stopped=before.stopped), before)
        self.assertEqual(engine.journal.events[-1].kind, 'daily_declared_not_sent')
        engine.automatic_submission_guard.assert_called_with('test-stock', reduce_only=True)
        engine.automatic_observation_validator.assert_called()
        for gateway in engine.gateways.values():
            for operation in ('snapshot', 'refresh', 'events', 'cancel'):
                getattr(gateway, operation).assert_not_called()

    def test_current_claimed_phase_is_resolvable_but_terminal_phases_are_not(self):
        current = ResolutionFixture(restarted=False)
        self.assertEqual(declare_daily_not_sent(current.engine, current.form), current.intent.key)
        self.assertTrue(current.engine.state.stopped)
        self.assertTrue(current.engine.state.automatic.auto_paused)
        self.assertFalse(current.engine.state.automatic.daily.authorized_run)
        self.assertFalse(current.engine.state.automatic.daily.owner_stamp)
        for phase in ('READY', 'DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED'):
            fixture = ResolutionFixture()
            state = fixture.engine.state
            fixture.engine._persist(
                'phase_fixture',
                replace(
                    state,
                    automatic=replace(state.automatic, daily=replace(state.automatic.daily, intents=(replace(state.automatic.daily.intents[0], phase=phase),))),
                ),
            )
            with self.subTest(phase=phase):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_confirmation_is_strict_and_missing_or_wrong_forms_cannot_claim_owner_intent(self):
        for form in (
            object(),
            DailyNotSentForm(self.fixture.intent.key),
            DailyNotSentForm(self.fixture.intent.key, 1),
            DailyNotSentForm(self.fixture.intent.key, 'yes'),
        ):
            with self.subTest(form=form):
                self.refuse(form=form, code='daily_not_sent_confirmation_required')
        self.refuse(form=DailyNotSentForm('missing-key', True), code='daily_not_sent_unproven')
        self.refuse(form=DailyNotSentForm('', True), code='validation_failed')
        self.refuse(account_ref='other-account', code='state_conflict')

    def test_live_refuses_before_journal_or_owner_ports_and_local_closed_failed_also_refuse(self):
        self.engine.configuration.environment = Environment.LIVE
        self.engine.journal.replay = Mock(side_effect=AssertionError('LIVE must not read reconciliation'))
        self.refuse(code='production_orders_disabled')
        self.engine.automatic_submission_guard.assert_not_called()
        self.engine.automatic_observation_validator.assert_not_called()
        for environment, closed, failed in ((Environment.LOCAL, False, False), (SIM, True, False), (SIM, False, True)):
            fixture = ResolutionFixture()
            fixture.engine.configuration.environment = environment
            fixture.engine.state = replace(fixture.engine.state, engine_closed=closed)
            fixture.engine.storage_failed = failed
            if environment is Environment.LOCAL:
                fixture.engine.journal.replay = Mock(side_effect=AssertionError('LOCAL has no daily broker proof authority'))
            with self.subTest(environment=environment, closed=closed, failed=failed):
                self.refuse(fixture=fixture, code='capability_missing')

    def test_order_id_missing_guard_does_not_allow_a_canonical_unknown_order_to_be_discarded(self):
        state = self.engine.state
        self.engine._persist(
            'order_identity_fixture',
            replace(
                state,
                automatic=replace(
                    state.automatic, daily=replace(state.automatic.daily, intents=(replace(state.automatic.daily.intents[0], order_id='canonical-order'),))
                ),
            ),
        )
        self.refuse(code='daily_not_sent_unproven')

    def test_owner_guard_and_current_complete_fresh_reconciled_cache_are_required(self):
        for fault in ('guard-missing', 'owner-changed', 'observation-owner', 'missing-cache', 'stale-cache', 'not-reconciled', 'unmapped', 'remote-unknown'):
            fixture = ResolutionFixture()
            engine = fixture.engine
            if fault == 'guard-missing':
                engine.automatic_submission_guard = None
            elif fault == 'owner-changed':
                engine.automatic_submission_guard.side_effect = DomainError('state_conflict')
            elif fault == 'observation-owner':
                engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
            elif fault == 'missing-cache':
                engine.manual_observations = {}
            elif fault == 'stale-cache':
                engine.clock.value += timedelta(seconds=31)
            elif fault == 'not-reconciled':
                engine.state = replace(engine.state, reconciled=False)
            else:
                observation = engine.manual_observations['test-stock']
                changes = (
                    {'unmapped': (UnmappedBrokerOrder('unowned-broker-order'),)}
                    if fault == 'unmapped'
                    else {'orders': (replace(fixture.broker_order(), status=OrderStatus.UNKNOWN),)}
                )
                engine.manual_observations['test-stock'] = replace(observation, **changes)
            with self.subTest(fault=fault):
                self.refuse(fixture=fixture)

    def test_missing_or_incomplete_or_invalid_journal_is_never_negative_send_proof(self):
        for fault in ('empty', 'missing-start', 'gap', 'duplicate', 'event-sequence', 'snapshot-version', 'wrong-type', 'wrong-environment', 'missing-tail'):
            fixture = ResolutionFixture()
            events = fixture.engine.journal.events
            if fault == 'empty':
                events.clear()
            elif fault == 'missing-start':
                del events[0]
            elif fault == 'gap':
                del events[2]
            elif fault == 'duplicate':
                fixture.rewrite(2, lambda state: replace(state, version=2), sequence=2)
            elif fault == 'event-sequence':
                fixture.rewrite(2, sequence=99)
            elif fault == 'snapshot-version':
                fixture.rewrite(0, lambda state: replace(state, version=9))
            elif fault == 'wrong-type':
                events[0] = replace(events[0], payload=dumps(()))
            elif fault == 'wrong-environment':
                fixture.rewrite(0, lambda state: replace(state, environment=Environment.LIVE))
            else:
                events.pop()
            with self.subTest(fault=fault):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_claim_requires_the_dedicated_event_a_prior_ready_and_a_single_authorized_transition(self):
        for fault in (
            'wrong-kind',
            'prior-not-ready',
            'missing-prior',
            'claim-first',
            'claimed-phase',
            'missing-claimed-intent',
            'empty-run',
            'empty-owner',
            'duplicate-claim',
        ):
            fixture = ResolutionFixture()
            if fault == 'wrong-kind':
                fixture.rewrite(1, kind='automatic_evaluation_claimed')
            elif fault == 'prior-not-ready':
                fixture.rewrite(
                    0,
                    lambda state: replace(
                        state,
                        automatic=replace(
                            state.automatic, daily=replace(state.automatic.daily, intents=(replace(state.automatic.daily.intents[0], phase='UNKNOWN'),))
                        ),
                    ),
                )
            elif fault == 'missing-prior':
                fixture.rewrite(0, lambda state: replace(state, automatic=replace(state.automatic, daily=replace(state.automatic.daily, intents=()))))
            elif fault == 'claim-first':
                original_claim = loads(fixture.engine.journal.events[1].payload)
                fixture.rewrite(0, lambda state: replace(state, automatic=original_claim.automatic), kind='daily_dispatch_claimed')
            elif fault == 'claimed-phase':
                fixture.rewrite(
                    1,
                    lambda state: replace(
                        state,
                        automatic=replace(
                            state.automatic, daily=replace(state.automatic.daily, intents=(replace(state.automatic.daily.intents[0], phase='UNKNOWN'),))
                        ),
                    ),
                )
            elif fault == 'missing-claimed-intent':
                fixture.rewrite(1, lambda state: replace(state, automatic=replace(state.automatic, daily=replace(state.automatic.daily, intents=()))))
            elif fault in ('empty-run', 'empty-owner'):
                changes = {'authorized_run': ''} if fault == 'empty-run' else {'owner_stamp': ''}
                fixture.rewrite(1, lambda state: replace(state, automatic=replace(state.automatic, daily=replace(state.automatic.daily, **changes))))
            else:
                old = loads(fixture.engine.journal.events[1].payload)
                ready = replace(old.automatic, daily=replace(old.automatic.daily, intents=(replace(old.automatic.daily.intents[0], phase='READY'),)))
                fixture.engine._persist('daily_signals_saved', replace(fixture.engine.state, automatic=ready))
                fixture.engine._persist('daily_dispatch_claimed', replace(fixture.engine.state, automatic=old.automatic))
            with self.subTest(fault=fault):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_historical_identity_cannot_be_rewritten_even_when_the_key_is_unchanged(self):
        for changes in (
            {'account_ref': 'other'},
            {'evidence_fingerprint': 'b' * 64},
            {'calendar_id': 'other'},
            {'calendar_version': 'other'},
            {'deadline': self.fixture.intent.deadline + timedelta(seconds=1)},
            {'instrument_id': 'TWSE:2330'},
        ):
            fixture = ResolutionFixture()
            fixture.rewrite(
                1,
                lambda state: replace(
                    state,
                    automatic=replace(state.automatic, daily=replace(state.automatic.daily, intents=(replace(state.automatic.daily.intents[0], **changes),))),
                ),
            )
            with self.subTest(changes=changes):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_any_historical_matching_order_survives_later_row_removal_and_timezone_aliases(self):
        for legacy in (False, True):
            fixture = ResolutionFixture()
            key = fixture.intent.key
            if legacy:
                key = f'auto:{fixture.cursor.strategy_id}:{fixture.cursor.version}:{fixture.cursor.instrument_id}:1d:{fixture.cursor.bar_end.astimezone(ZoneInfo("Asia/Taipei")).isoformat()}'
            order = fixture.local_order(key)
            fixture.engine._persist('order_submitting', replace(fixture.engine.state, orders=(order,)))
            fixture.engine._persist('later_projection_removed_order', replace(fixture.engine.state, orders=()))
            with self.subTest(legacy=legacy):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_any_same_side_instrument_broker_order_is_a_candidate_despite_price_quantity_or_terminal_status(self):
        observation = self.engine.manual_observations['test-stock']
        self.engine.manual_observations['test-stock'] = replace(observation, orders=(self.fixture.broker_order(quantity=9000, price=D('99')),))
        self.refuse(code='daily_not_sent_order_found')

    def test_known_broker_orders_for_other_instruments_or_opposite_side_do_not_become_false_matches(self):
        for changes in ({'instrument_id': 'TWSE:2330'}, {'side': Side.SELL}):
            fixture = ResolutionFixture()
            observation = fixture.engine.manual_observations['test-stock']
            fixture.engine.manual_observations['test-stock'] = replace(observation, orders=(fixture.broker_order(**changes),))
            with self.subTest(changes=changes):
                self.assertEqual(declare_daily_not_sent(fixture.engine, fixture.form), fixture.intent.key)

    def correlated_other_order(self, fixture):
        local = replace(fixture.local_order('another-owned-intent'), status=OrderStatus.ACCEPTED, broker_ref='identified-broker-reference')
        fixture.engine._persist('another_known_order', replace(fixture.engine.state, orders=(local,)))
        remote = BrokerOrder(local.order_id, local.plan, 0, D('0'), OrderStatus.ACCEPTED, local.broker_ref, fixture.engine.clock.now())
        return local, remote

    def test_exactly_correlated_other_intent_keeps_its_cash_and_risk_reservation(self):
        local, remote = self.correlated_other_order(self.fixture)
        observation = self.engine.manual_observations['test-stock']
        self.engine.manual_observations['test-stock'] = replace(observation, orders=(remote,))
        before = self.engine.state
        self.assertGreater(local.reservation.cash, 0)
        self.assertGreater(local.reservation.risk, 0)
        self.assertEqual(declare_daily_not_sent(self.engine, self.fixture.form), self.fixture.intent.key)
        self.assertEqual(self.engine.state.orders, before.orders)
        self.assertEqual(self.engine.state.orders[0].reservation, local.reservation)

    def test_correlation_requires_local_order_id_broker_reference_and_complete_plan(self):
        for mismatch in ('local-id', 'broker-reference', 'plan'):
            fixture = ResolutionFixture()
            _, remote = self.correlated_other_order(fixture)
            if mismatch == 'local-id':
                remote = replace(remote, local_order_id='not-the-local-order')
            elif mismatch == 'broker-reference':
                remote = replace(remote, broker_order_ref='not-the-known-reference')
            else:
                remote = replace(remote, plan=replace(remote.plan, quantity=9000, limit_price=D('99')))
            observation = fixture.engine.manual_observations['test-stock']
            fixture.engine.manual_observations['test-stock'] = replace(observation, orders=(remote,))
            with self.subTest(mismatch=mismatch):
                self.refuse(fixture=fixture, code='daily_not_sent_order_found')

    def test_semantic_order_keys_preserve_timestamp_identity_and_exact_exit_suffix(self):
        intent = self.fixture.intent
        self.assertTrue(_same_key(intent.key, intent))
        legacy = f'auto:{self.fixture.cursor.strategy_id}:{self.fixture.cursor.version}:{self.fixture.cursor.instrument_id}:1d:{self.fixture.cursor.bar_end.astimezone(ZoneInfo("Asia/Taipei")).isoformat()}'
        self.assertTrue(_same_key(legacy, intent))
        for key in (
            'not-a-daily-key',
            intent.key + ':exit:another-lot',
            intent.key.replace(':1d:', ':5m:'),
            intent.key.replace(':1:', ':2:', 1),
            intent.key.replace(intent.cursor.instrument_id, 'TWSE:2330'),
        ):
            with self.subTest(key=key):
                self.assertFalse(_same_key(key, intent))

    def test_original_claim_strategy_scope_is_required_to_infer_entry_side(self):
        for changes in (
            {'parameters': None},
            {'parameters': replace(self.engine.record.parameters, bar_interval='5m')},
            {'form': replace(self.engine.record.form, account_ref='other')},
            {'form': replace(self.engine.record.form, environment=Environment.LIVE)},
            {'strategy_id': 'not-the-original-strategy'},
        ):
            fixture = ResolutionFixture()
            fixture.rewrite(1, lambda state: replace(state, strategies=(replace(state.strategies[0], **changes),)))
            with self.subTest(changes=changes):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_original_exit_lot_must_exist_in_the_same_account_and_instrument(self):
        for changes in (None, {'account_ref': 'other'}, {'instrument_id': 'TWSE:2330'}):
            fixture = ResolutionFixture(action='EXIT')
            fixture.rewrite(1, lambda state: replace(state, positions=() if changes is None else (replace(state.positions[0], **changes),)))
            with self.subTest(changes=changes):
                self.refuse(fixture=fixture, code='daily_not_sent_unproven')

    def test_any_unknown_manual_request_and_missing_other_account_observation_block_resolution(self):
        request = ManualRequest(ManualScope('audit', 0, SIM, 'test-stock', 'current-generation', 1), 'manual-request', 'SUBMIT', 'b' * 64, status='UNKNOWN')
        self.engine._persist('unresolved_manual_request', replace(self.engine.state, manual_requests=(request,)))
        self.refuse(code='reconciliation_required')
        fixture = ResolutionFixture()
        fixture.engine.gateways['unobserved-account'] = object()
        self.refuse(fixture=fixture, code='manual_account_observation_required')

    def test_expected_side_uses_original_entry_direction_and_opposite_long_or_short_exit(self):
        fixture = ResolutionFixture(action='EXIT')
        claim = daily_resolution._prove_unsent(fixture.engine, fixture.intent)
        self.assertEqual(daily_resolution._expected_side(claim, fixture.intent), Side.SELL)
        short_claim = replace(claim, positions=(replace(claim.positions[0], direction=Side.SELL),))
        self.assertEqual(daily_resolution._expected_side(short_claim, fixture.intent), Side.BUY)
        claim = daily_resolution._prove_unsent(self.engine, self.fixture.intent)
        short_entry = replace(claim, strategies=(replace(claim.strategies[0], form=replace(claim.strategies[0].form, direction=Side.SELL)),))
        self.assertEqual(daily_resolution._expected_side(short_entry, self.fixture.intent), Side.SELL)

    def test_writer_fence_failure_cannot_commit_a_negative_send_conclusion(self):
        self.engine.fence = Mock(side_effect=DomainError('journal_failed'))
        self.refuse(code='journal_failed')

    def test_failed_journal_append_keeps_unknown_and_all_financial_rows(self):
        before = self.engine.state
        self.engine.journal.append = Mock(side_effect=OSError('offline write failure'))
        with self.assertRaises(DomainError) as caught:
            declare_daily_not_sent(self.engine, self.fixture.form)
        self.assertEqual(caught.exception.code, 'journal_failed')
        self.assertEqual(self.engine.state.automatic.daily.intents, before.automatic.daily.intents)
        self.assertEqual(self.engine.state.orders, before.orders)
        self.assertEqual(self.engine.state.positions, before.positions)
        self.assertTrue(self.engine.storage_failed)

    def test_exit_resolution_binds_exact_lot_and_matches_opposite_of_original_position(self):
        fixture = ResolutionFixture(action='EXIT')
        self.assertTrue(_same_key(fixture.intent.key, fixture.intent))
        self.assertFalse(_same_key(fixture.intent.key.rsplit(':exit:', 1)[0], fixture.intent))
        self.assertFalse(_same_key(fixture.intent.key.replace(':exit:owned-exit-lot', ':exit:another-lot'), fixture.intent))
        observation = fixture.engine.manual_observations['test-stock']
        fixture.engine.manual_observations['test-stock'] = replace(observation, orders=(fixture.broker_order(side=Side.SELL),))
        self.refuse(fixture=fixture, code='daily_not_sent_order_found')
        fixture = ResolutionFixture(action='EXIT')
        self.assertEqual(declare_daily_not_sent(fixture.engine, fixture.form), fixture.intent.key)

    def test_plain_reconcile_still_cannot_silently_discard_an_unknown_dispatch(self):
        with self.assertRaises(DomainError) as caught:
            reconcile_daily(self.engine)
        self.assertEqual(caught.exception.code, 'daily_signal_unresolved')
        self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'UNKNOWN')

    def test_long_actual_journal_proof_cannot_reuse_an_observation_that_expired_during_replay(self):
        actual_proof = daily_resolution._prove_unsent

        def slow_proof(engine, intent):
            proven = actual_proof(engine, intent)
            engine.clock.value += timedelta(seconds=31)
            return proven

        with patch.object(daily_resolution, '_prove_unsent', slow_proof):
            self.refuse(code='manual_account_observation_required')


class NativeDailyNotSentTests(unittest.TestCase):
    def crash_and_restore(self, *, stock=True):
        fixture = native.DailyNativeFixture(self.addCleanup, stock=stock)
        bundle = runtime_fixtures.public_bundle(fixture)
        fixture.deploy(entry_amount=D('25000') if stock else D('40000'))
        fixture.start()
        fixture.close()
        fixture.close_other_accounts()
        fixture.next_day()
        old = fixture.engine
        old.journal = native.CrashAfterDailyClaim(old.journal)
        before = fixture.placed()
        with self.assertRaises(native.InjectedCrash):
            dispatch_daily(old)
        self.assertEqual(fixture.placed(), before)
        restored = TradingEngine(
            old.journal,
            fixture.clock,
            old.calendar,
            old.catalog,
            old.gateways,
            configuration=old.configuration,
            ownership_clock=fixture.clock.now,
            source_profile=old.profile,
            fees=old.fees,
            historical_bars=old.history,
        )
        restored.quotes = dict(old.quotes)
        fixture.engine = fixture.base.engine = fixture.case.engine = restored
        fixture.case.service.engine = restored
        bundle.engine, bundle.facade = restored, LocalFacade(restored)
        restored.automatic_observation_validator = fixture.runtime.validate_observation
        restored.automatic_entry_validator = fixture.runtime.validate_entry
        restored.automatic_submission_guard = fixture.runtime.submission_guard
        restored.automatic_owner_stamp = fixture.runtime.owner_stamp
        fixture.refresh(fixture.clock.now() + timedelta(seconds=1), stock_price=D('12'))
        intent = restored.state.automatic.daily.intents[0]
        self.assertEqual((intent.phase, intent.order_id), ('UNKNOWN', ''))
        return fixture, bundle, intent, before

    def declare(self, fixture, bundle, intent, *, environment=SIM, account_ref=None):
        return bundle.execute(
            UiCommand(
                UiAction.DECLARE_DAILY_NOT_SENT,
                fixture.engine.state.version + bundle.version_offset,
                environment=environment,
                account_ref=fixture.account_ref if account_ref is None else account_ref,
                daily_not_sent=DailyNotSentForm(intent.key, True),
            )
        )

    def test_actual_native_stock_claim_crash_can_be_declared_without_sending_then_explicitly_resumed(self):
        fixture, bundle, intent, before = self.crash_and_restore()
        old = fixture.engine.state
        with self.assertRaises(DomainError):
            reconcile_daily(fixture.engine)
        receipt = self.declare(fixture, bundle, intent)
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual((receipt.code, receipt.reference), ('daily_declared_not_sent', intent.key))
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(fixture.engine.state.orders, old.orders)
        self.assertEqual(fixture.engine.state.positions, old.positions)
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertTrue(fixture.engine.state.stopped)
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before)
        resume = bundle.execute(
            UiCommand(UiAction.AUTO_RESUME, fixture.engine.state.version + bundle.version_offset, environment=SIM, account_ref=fixture.account_ref)
        )
        self.assertTrue(resume.accepted, resume)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before, 'resolution must never retry the old saved signal')
        self.assertEqual(fixture.case.native.financial_queries, 0)

    def test_actual_native_future_diagnostic_with_another_canonical_key_is_not_the_missing_dispatch(self):
        fixture, bundle, intent, before = self.crash_and_restore(stock=False)
        diagnostic = fixture.engine.state.orders[0]
        self.assertNotEqual(diagnostic.key, intent.key)
        self.assertEqual(diagnostic.status, OrderStatus.CANCELED)
        self.assertEqual(diagnostic.plan.instrument_id, intent.instrument_id)
        receipt = self.declare(fixture, bundle, intent)
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(fixture.placed(), before)

    def test_native_live_declaration_refuses_before_sdk_or_journal_changes(self):
        fixture, bundle, intent, _ = self.crash_and_restore()
        before, state = tuple(fixture.case.native._seen), fixture.engine.state
        receipt = self.declare(fixture, bundle, intent, environment=Environment.LIVE)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'production_orders_disabled')
        self.assertIs(fixture.engine.state, state)
        self.assertEqual(tuple(fixture.case.native._seen), before)

    def test_native_selected_account_cannot_declare_another_accounts_intent(self):
        fixture, bundle, intent, _ = self.crash_and_restore()
        before, state = tuple(fixture.case.native._seen), fixture.engine.state
        receipt = self.declare(fixture, bundle, intent, account_ref='future-alias')
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'state_conflict')
        self.assertIs(fixture.engine.state, state)
        self.assertEqual(tuple(fixture.case.native._seen), before)


if __name__ == '__main__':
    unittest.main()
