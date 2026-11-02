"""Official-input admission over explicit synthetic ports; no runtime authority claim."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import official_daily_fixtures as official
import test_m2_automatic as memory
import test_trading_adapters as market
from quantlab.trading.application.automatic_state import AutomaticState
from quantlab.trading.application.codec import dumps
from quantlab.trading.application.daily_execution import observe_daily, dispatch_daily, assert_daily_dispatch
from quantlab.trading.application.daily_signal_data import (
    official_daily_result,
    stock_daily_window,
    assert_daily_intent_source,
    daily_signal_views,
    _signal_window_hash,
)
from quantlab.trading.application.daily_state import DailyState
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.application.research import research_fingerprint
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, OrderStatus, Reservation
from quantlab.trading.domain.stock_history import CorporateAction
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError

D = Decimal


class OfficialDailyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.engine = memory.MemoryEngine()
        self.engine.profile = None  # Pure source-admission fixture, never broker deployment authority.
        self.spec = self.engine.catalog.instruments[0]
        self.calendar = calendar_for_instrument(self.engine.calendar, self.spec)
        self.days = self.calendar.days[:31]
        self.day = self.days[-1]
        self.session = self.calendar.day_session(self.day)
        self.engine.clock.value = self.session.closes_at
        self.engine.state = replace(self.engine.state, trading_day=self.day)
        self.engine.refresh_facts()
        record = self.engine.make_record(interval='1d')
        record = replace(record, form=replace(record.form, rule_kind='BUY_AND_HOLD'))
        raw = tuple(
            CompletedBar(row.opens_at, row.closes_at, row.closes_at, D('10'), D('10'), 1000) for day in self.days for row in (self.calendar.day_session(day),)
        )
        self.training = official.fake_official_history(self.spec.instrument_id, raw[:-1], self.engine.clock.now())
        self.record, self.result = official.official_research_fixture(self.engine, record, self.training)
        self.history = official.fake_official_history(self.spec.instrument_id, raw, self.engine.clock.now())
        self.source = official.install_fake_official_source(self.engine, self.history)
        self.engine.record = self.record
        self.engine.state = replace(
            self.engine.state,
            strategies=(self.record,),
            stopped=False,
            automatic=AutomaticState(
                False, (), self.session.opens_at, daily=DailyState(authorized_run='explicit-fixture-run', owner_stamp=self.engine.automatic_owner_stamp())
            ),
        )
        self.engine._strategy_spec = lambda spec, record: spec

    def window(self):
        return stock_daily_window(self.engine, self.record, self.spec.instrument_id, self.calendar)

    def save(self):
        observe_daily(self.engine, ())
        self.assertEqual(len(self.engine.state.automatic.daily.intents), 1)
        return self.engine.state.automatic.daily.intents[0]

    def next_open(self):
        day = self.calendar.advance(self.day, 1)
        self.engine.clock.value = self.calendar.day_session(day).opens_at + timedelta(seconds=1)
        self.engine.state = replace(self.engine.state, trading_day=day)
        self.engine.refresh_facts()

    def test_valid_official_basis_and_source_only_signal_without_any_minute_tape(self):
        history = official_daily_result(self.engine, self.record, self.result)
        self.assertTrue(history.research_basis(self.days[0], self.days[-2]).compatible(self.result.daily_basis))
        intent = self.save()
        self.assertEqual(intent.cursor.bar_end, self.session.closes_at)
        self.assertEqual(intent.data_policy_fingerprint, self.history.policy.fingerprint)
        signals = self.history.signal_history(self.calendar, self.day)
        self.assertEqual(intent.data_fingerprint, _signal_window_hash(self.history, self.calendar, self.day, signals))
        self.assertEqual(len(intent.data_fingerprint), 64)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'COMPLETED')
        self.assertEqual(self.engine.state.orders, ())

    def test_old_or_missing_official_research_basis_cannot_save_a_signal(self):
        for result in (None, replace(self.result, daily_basis=None)):
            record = replace(self.record, research_blob=dumps(result) if result else '')
            self.engine.state = replace(self.engine.state, strategies=(record,))
            observe_daily(self.engine, ())
            self.assertEqual(self.engine.state.automatic.daily.intents, ())
            self.assertEqual(self.engine.state.automatic.evaluations, ())
            self.assertEqual(daily_signal_views(self.engine)[0].status, 'UNVERIFIED')

    def test_basis_policy_instrument_dates_and_semantic_price_or_event_revision_are_rejected(self):
        basis = self.result.daily_basis
        for changes in (
            {'policy_fingerprint': 'f' * 64},
            {'instrument_id': 'TWSE:2330'},
            {'start': self.days[1]},
            {'end': self.days[-1]},
            {'raw_digest': 'e' * 64},
            {'events_digest': 'c' * 64},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(DomainError) as caught:
                    official_daily_result(self.engine, self.record, replace(self.result, daily_basis=replace(basis, **changes)))
                self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        changed = replace(self.history, bars=(replace(self.history.bars[0], high=D('11')), *self.history.bars[1:]))
        self.source.publish(changed)
        with self.assertRaises(DomainError):
            official_daily_result(self.engine, self.record, self.result)
        event = CorporateAction(self.spec.instrument_id, self.days[10], D('10'), D('9'), 'c' * 64, 'https://www.twse.com.tw/fixture')
        self.source.publish(replace(self.history, events=(event,)))
        with self.assertRaises(DomainError):
            official_daily_result(self.engine, self.record, self.result)

    def test_direct_admission_requires_official_result_and_server_source(self):
        for result in (None, replace(self.result, daily_basis=None)):
            with self.subTest(result=result):
                with self.assertRaises(DomainError) as caught:
                    official_daily_result(self.engine, self.record, result)
                self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        del self.engine.daily_signal_source
        with self.assertRaises(DomainError) as caught:
            official_daily_result(self.engine, self.record, self.result)
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')

    def test_result_shape_cannot_impersonate_typed_official_research(self):
        imitation = SimpleNamespace(daily_basis=self.result.daily_basis, dataset_id=self.result.dataset_id, fingerprint=self.result.fingerprint)
        with self.assertRaises(DomainError) as caught:
            official_daily_result(self.engine, self.record, imitation)
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')

    def test_official_window_must_validate_research_before_any_durable_claim(self):
        with patch('quantlab.trading.application.daily_signal_data.official_daily_result', side_effect=DomainError('daily_signal_basis_mismatch')):
            observe_daily(self.engine, ())
        self.assertEqual(self.engine.state.automatic.evaluations, ())
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_basis_mismatch')

    def test_dataset_and_committed_research_identity_are_independently_bound(self):
        with self.assertRaises(DomainError) as caught:
            official_daily_result(self.engine, self.record, replace(self.result, dataset_id='f' * 64))
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        with self.assertRaises(DomainError) as caught:
            official_daily_result(self.engine, replace(self.record, evidence_hash='f' * 64), self.result)
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')

    def test_month_payload_and_decimal_scale_only_refresh_remain_compatible(self):
        bars = tuple(replace(row, open=D('10.00'), high=D('10.000'), low=D('10.0'), close=D('10.0000'), source_digest='d' * 64) for row in self.history.bars)
        changed = replace(self.history, bars=bars, source_digest='e' * 64)
        self.source.publish(changed)
        self.assertTrue(self.result.daily_basis.compatible(changed.research_basis(self.days[0], self.days[-2])))
        self.assertIsNotNone(self.window())
        official_daily_result(self.engine, self.record, self.result)
        self.save()

    def test_real_engine_evidence_guard_does_not_turn_profile_none_fixture_into_authority(self):
        with self.assertRaises(DomainError) as caught:
            TradingEngine._assert_strategy_evidence(self.engine, self.record)
        self.assertEqual(caught.exception.code, 'strategy_evidence_stale')

    def test_legacy_complete_minute_day_without_official_source_cannot_save(self):
        del self.engine.daily_signal_source
        minutes = tuple(
            LiveBar(self.spec.instrument_id, start, start + timedelta(minutes=1), self.day, 'DAY', D('10'), D('10'), D('10'), D('10'), 100, final=True)
            for offset in range(270)
            for start in (self.session.opens_at + timedelta(minutes=offset),)
        )
        observe_daily(self.engine, minutes)
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.assertEqual(self.engine.state.automatic.evaluations, ())
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_source_unverified')

    def test_late_source_cannot_mint_after_next_verified_day_open(self):
        self.next_open()
        requests = len(self.source.requests)
        self.assertIsNone(self.window())
        observe_daily(self.engine, ())
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.assertEqual(self.engine.state.automatic.evaluations, ())
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_not_available')
        self.assertEqual(len(self.source.requests), requests)

    def test_missing_next_verified_calendar_cannot_claim_or_save(self):
        calendar = replace(self.engine.calendar, sessions=tuple(row for row in self.engine.calendar.sessions if row.trade_date <= self.day))
        self.engine.calendar = calendar
        observe_daily(self.engine, ())
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.assertEqual(self.engine.state.automatic.evaluations, ())
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'calendar_missing')

    def test_research_and_live_signal_rebuild_the_same_pit_window(self):
        from quantlab.trading.application.research import research

        record = replace(self.record, policy=replace(self.record.policy, max_days=1), form=replace(self.record.form, max_days=1))
        seen = []
        with patch('quantlab.trading.application.research.entry_signal', side_effect=lambda record, bars, now: seen.append((bars, now)) or False):
            research(record, self.spec, self.calendar, self.history.raw_completed(self.calendar), self.engine.fees, daily_history=self.history)
        self.assertGreater(len(seen), 20)
        for studied, now in seen:
            through = self.days[self.days.index(now.date()) - 1]
            self.assertEqual(studied, self.history.signal_history(self.calendar, through))
        self.assertEqual(self.window()[1], self.history.signal_history(self.calendar, self.day))

    def test_saved_close_revision_after_research_end_is_rejected_before_dispatch_claim(self):
        intent = self.save()
        self.next_open()
        changed = replace(self.history, bars=(*self.history.bars[:-1], replace(self.history.bars[-1], close=D('11'), high=D('11'))))
        self.source.publish(changed)
        with self.assertRaises(DomainError) as caught:
            assert_daily_intent_source(self.engine, self.record, intent)
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        with (
            patch('quantlab.trading.application.automatic._entry_proofs') as entry,
            patch('quantlab.trading.application.coordinator._entry_decision') as decision,
        ):
            dispatch_daily(self.engine)
        entry.assert_not_called()
        decision.assert_not_called()
        self.assertEqual(self.engine.state.orders, ())
        self.assertEqual(self.engine.state.automatic.daily.intents[0].phase, 'READY')
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_saved_intent_requires_both_signal_hash_and_current_policy_hash(self):
        intent = self.save()
        for changes in ({'data_fingerprint': ''}, {'data_policy_fingerprint': ''}, {'data_policy_fingerprint': 'e' * 64}):
            with self.subTest(changes=changes):
                with self.assertRaises(DomainError) as caught:
                    assert_daily_intent_source(self.engine, self.record, replace(intent, **changes))
                self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')

    def test_snapshot_view_reads_cache_only_and_loses_verified_on_source_or_evidence_swap(self):
        self.assertIsNotNone(self.window())
        requests = len(self.source.requests)
        self.source.history = Mock(side_effect=AssertionError('snapshot must not read source'))
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'VERIFIED')
        self.assertEqual(len(self.source.requests), requests)
        self.engine.daily_signal_source = official.FakeOfficialDailySource((self.history,))
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'UNVERIFIED')
        self.engine.daily_signal_source = self.source
        self.engine.state = replace(self.engine.state, strategies=(replace(self.record, evidence_hash='f' * 64),))
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'UNVERIFIED')

    def test_initial_window_refuses_future_or_preclose_source_observation(self):
        for observed_at in (self.engine.clock.now() + timedelta(seconds=1), self.session.closes_at - timedelta(seconds=1)):
            self.source.publish(replace(self.history, observed_at=observed_at))
            with self.subTest(observed_at=observed_at):
                self.assertIsNone(self.window())
                self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_not_available')

    def test_research_basis_admission_also_refuses_future_or_pretraining_close_observation(self):
        for observed_at in (self.engine.clock.now() + timedelta(seconds=1), self.calendar.day_session(self.days[-2]).closes_at - timedelta(seconds=1)):
            self.source.publish(replace(self.history, observed_at=observed_at))
            with self.subTest(observed_at=observed_at):
                with self.assertRaises(DomainError) as caught:
                    official_daily_result(self.engine, self.record, self.result)
                self.assertEqual(caught.exception.code, 'daily_signal_not_available')

    def test_dispatch_rechecks_future_and_pre_saved_close_source_availability(self):
        intent = self.save()
        self.next_open()
        for observed_at in (self.engine.clock.now() + timedelta(seconds=1), self.session.closes_at - timedelta(seconds=1)):
            self.source.publish(replace(self.history, observed_at=observed_at))
            with self.subTest(observed_at=observed_at):
                with self.assertRaises(DomainError) as caught:
                    assert_daily_intent_source(self.engine, self.record, intent)
                self.assertEqual(caught.exception.code, 'daily_signal_not_available')
        self.assertEqual(self.engine.state.orders, ())

    def test_engine_evidence_calls_official_admission_after_valid_general_fingerprint(self):
        # A valid typed synthetic profile exercises this method boundary; no compute_profile claim.
        manifest = (('quantlab/trading/application/research.py', 'a' * 64),)
        self.engine.profile = ProducerProfile(
            'MARKAUTO-TRADING-V2-PROFILE-1',
            2,
            manifest,
            sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest(),
        )
        record, result = official.official_research_fixture(self.engine, self.record, self.training)
        official.install_fake_official_source(self.engine, self.history)
        TradingEngine._assert_strategy_evidence(self.engine, record)
        for basis, expected in ((None, 'daily_signal_source_unverified'), (replace(result.daily_basis, raw_digest='f' * 64), 'daily_signal_basis_mismatch')):
            with self.subTest(basis=basis):
                changed = replace(result, daily_basis=basis)
                candidate = replace(record, research_blob=dumps(changed))
                self.assertEqual(
                    changed.fingerprint,
                    research_fingerprint(candidate, self.spec, self.calendar, self.engine.fees, changed.dataset_id, self.engine.profile),
                )
                self.assertEqual(changed.source_digest, self.engine.profile.source_digest)
                with self.assertRaises(DomainError) as caught:
                    TradingEngine._assert_strategy_evidence(self.engine, candidate)
                self.assertEqual(caught.exception.code, expected)

    def test_final_dispatch_calls_source_admission_before_accepting_claimed_intent(self):
        intent = self.save()
        self.next_open()
        claimed = replace(intent, phase='CLAIMED')
        self.engine.state = replace(
            self.engine.state, automatic=replace(self.engine.state.automatic, daily=replace(self.engine.state.automatic.daily, intents=(claimed,)))
        )
        plan = replace(
            market.plan(self.spec),
            environment=Environment.BROKER_SIMULATION,
            account_ref=claimed.account_ref,
            strategy_id=self.record.strategy_id,
            strategy_version=self.record.version,
            reduce_only=False,
        )
        assert_daily_dispatch(self.engine, plan, claimed.key)
        for changes in ({'data_fingerprint': ''}, {'data_policy_fingerprint': ''}):
            with self.subTest(changes=changes):
                bad = replace(claimed, **changes)
                self.engine.state = replace(
                    self.engine.state, automatic=replace(self.engine.state.automatic, daily=replace(self.engine.state.automatic.daily, intents=(bad,)))
                )
                with self.assertRaises(DomainError) as caught:
                    assert_daily_dispatch(self.engine, plan, claimed.key)
                self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        self.engine.state = replace(
            self.engine.state, automatic=replace(self.engine.state.automatic, daily=replace(self.engine.state.automatic.daily, intents=(claimed,)))
        )
        self.source.publish(replace(self.history, bars=(*self.history.bars[:-1], replace(self.history.bars[-1], close=D('11'), high=D('11')))))
        with self.assertRaises(DomainError) as caught:
            assert_daily_dispatch(self.engine, plan, claimed.key)
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        self.assertEqual(self.engine.state.orders, ())

    def test_observe_routes_stock_official_history_and_attestation_without_generic_minutes(self):
        expected = self.history.signal_history(self.calendar, self.day)
        generic = tuple(replace(row, open=D('999'), close=D('999')) for row in expected)
        with (
            patch('quantlab.trading.application.automatic._history', return_value={self.spec.instrument_id: generic}) as raw_history,
            patch('quantlab.trading.application.daily_execution.entry_signal', return_value=True) as evaluate,
        ):
            intent = self.save()
        raw_history.assert_not_called()
        evaluate.assert_called_once_with(self.record, expected, self.session.closes_at)
        self.assertEqual(intent.data_fingerprint, _signal_window_hash(self.history, self.calendar, self.day, expected))
        self.assertEqual(intent.data_policy_fingerprint, self.history.policy.fingerprint)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'COMPLETED')
        self.assertEqual(self.engine.state.orders, ())

    def test_live_observe_dispatch_engine_and_execution_commit_reject_before_source_or_gateway(self):
        self.engine.automatic_entry_check = Mock(side_effect=DomainError('capability_missing'))
        self.engine.configuration.environment = Environment.LIVE
        self.engine.state = replace(self.engine.state, environment=Environment.LIVE)
        plan = market.plan(self.spec, environment=Environment.LIVE)
        reserve = Reservation('r', 'test-stock', self.spec.instrument_id, self.spec.underlying, D('10000'), D('10'), 1000, OrderStatus.RESERVED)
        broker, persist, fence = Mock(), Mock(), Mock()
        service = ExecutionService(broker, persist, fence, self.engine.clock.now)
        for operation in (
            lambda: observe_daily(self.engine, ()),
            lambda: dispatch_daily(self.engine),
            lambda: TradingEngine.submit(self.engine, plan, self.record.policy, 'live'),
            lambda: service.commit(self.engine.state, plan, self.record.policy, reserve, 'live', fence),
        ):
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.assertEqual(self.source.requests, [])
        self.assertEqual(self.engine.state.automatic.evaluations, ())
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.assertEqual(self.engine.events, [])
        broker.submit.assert_not_called()
        persist.assert_not_called()
        fence.assert_not_called()
        self.engine.automatic_submission_guard.assert_not_called()
        self.engine.automatic_entry_check.assert_not_called()
