"""M3 lifecycle fixtures use the existing Journal contract, never a gateway."""

from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from quantlab.trading.application.auto_strategy_views import AutoStrategyView, BuildDialogOptions, CandidateSummaryView, PromotionProgressView
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.promotion_service import AutoStrategyEvent, AutoStrategyRecord, PromotionService
from quantlab.trading.application.signal_research import ExecutionEvidence
from quantlab.trading.application.research import ResearchTrade
from quantlab.trading.domain.models import Environment, Side
from quantlab.trading.domain.promotion import ExecutionExpectation, PauseReason, RunState, SimObservation, Stage, StageState
from quantlab.trading.domain.signal_strategy import CandidateEvidence, CandidateSummary
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import StoredEvent
from tests.test_m3_signal_strategy import intraday

D = Decimal
DAY = date(2026, 1, 5)
NOW = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)


class MemoryJournal:
    def __init__(self):
        self.events = []
        self.fail = False

    def replay(self):
        return tuple(self.events)

    def append(self, kind, payload, now, *, expected_sequence):
        if self.fail:
            raise OSError('fixture write failure')
        if expected_sequence != len(self.events):
            raise DomainError('version_conflict', 'fixture CAS')
        event = StoredEvent(len(self.events) + 1, kind, payload, 'previous', 'digest')
        self.events.append(event)
        return event


def built(**changes):
    auto = intraday()
    candidate = CandidateEvidence('candidate', 'campaign', auto.candidate_fingerprint, 'statistical_edge', True, 12, NOW, 'TMF', '1d', auto.signal_spec_json)
    base = dict(
        auto=auto,
        account_ref='sim-account',
        execution_instrument_id='TAIFEX:TMF:202601',
        allocated_amount=D('100000'),
        candidate=candidate,
        expectation=ExecutionExpectation(D('.02'), D('.001'), D('.5')),
        behavior_hash='behavior',
        source_digest='source',
        dataset_id='dataset',
        result_hash='result',
        start_in_sim=True,
    )
    base.update(changes)
    a = base['auto']
    base.setdefault(
        'evidence',
        ExecutionEvidence(
            a.strategy_id,
            a.version,
            a.frozen_hash,
            base['dataset_id'],
            base['result_hash'],
            base['behavior_hash'],
            base['source_digest'],
            base['expectation'],
            (ResearchTrade(0, 1, 1, D('100'), D('101'), D('10'), D('2')),),
            D('8'),
            D('2'),
            2,
            base['allocated_amount'],
            (Side.BUY,),
        ),
    )
    for name in ('expectation', 'behavior_hash', 'source_digest', 'dataset_id', 'result_hash', 'allocated_amount'):
        base.pop(name)
    return AutoStrategyRecord(**base)


def observation(**changes):
    base = dict(
        trading_days=10,
        full_trading_days=10,
        completed_trades=10,
        round_trips=5,
        wins=5,
        net_return=D('.01'),
        max_drawdown_pct=D('.01'),
        orders=20,
        rejected_or_unknown_orders=0,
        unresolved_reconciliation=False,
        history_complete=True,
    )
    base.update(changes)
    return SimObservation(**base)


class PromotionServiceTests(unittest.TestCase):
    def setUp(self):
        self.journal = MemoryJournal()
        self.service = PromotionService(self.journal, Environment.BROKER_SIMULATION, now=NOW)
        self.service.record_built(built(), now=NOW)

    def start(self, **changes):
        args = dict(trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)
        args.update(changes)
        return self.service.start_sim('auto-1', 1, **args)

    def evaluate(self, obs=None, **changes):
        args = dict(observation_started_on=DAY, now=NOW)
        args.update(changes)
        return self.service.evaluate_after_close('auto-1', 1, DAY + timedelta(days=10), obs or observation(), **args)

    def refresh(self, strategy_id, version, *, behavior_hash, source_digest, result_hash, now):
        evidence = replace(
            self.service.record(strategy_id, version).evidence, behavior_hash=behavior_hash, source_digest=source_digest, result_hash=result_hash
        )
        return self.service.refresh_evidence(strategy_id, version, evidence, now=now)

    def assert_code(self, code, function, *args, **kwargs):
        count = len(self.journal.events)
        with self.assertRaises(DomainError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(len(self.journal.events), count)

    def test_build_event_roundtrip_retains_e1_and_frozen_identity(self):
        event = loads(self.journal.events[0].payload)
        self.assertEqual(event.record, built())
        self.assertEqual(event.record.candidate, built().candidate)
        self.assertEqual(event.record.auto.frozen_hash, built().auto.frozen_hash)

    def test_duplicate_build_guard(self):
        self.assert_code('auto_frozen', self.service.record_built, built(), now=NOW)

    def test_build_stage_guard(self):
        row = built(auto=intraday(strategy_id='auto-2'), state=StageState(Stage.BROKER_SIM, RunState.RUNNING))
        self.assert_code('stage_transition_denied', self.service.record_built, row, now=NOW)

    def test_unknown_version_guard(self):
        self.assert_code('validation_failed', self.service.record, 'auto-1', 2)

    def test_replay_schema_guard(self):
        self.journal.events[0] = replace(self.journal.events[0], payload=dumps(built()))
        self.assert_code('validation_failed', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_replay_record_schema_guard(self):
        self.journal.events[0] = replace(self.journal.events[0], payload=dumps(AutoStrategyEvent('wrong')))
        self.assert_code('validation_failed', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_replay_frozen_version_guard(self):
        self.start()
        event = loads(self.journal.events[-1].payload)
        changed = replace(
            event.record,
            auto=replace(event.record.auto, protective_stop_pct=D('.02')),
            evidence=replace(event.record.evidence, frozen_hash=replace(event.record.auto, protective_stop_pct=D('.02')).frozen_hash),
        )
        self.journal.events[-1] = replace(self.journal.events[-1], payload=dumps(replace(event, record=changed)))
        self.assert_code('auto_frozen', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_replay_evaluation_shape_guard(self):
        self.start()
        self.evaluate()
        event = loads(self.journal.events[-1].payload)
        self.journal.events[-1] = replace(self.journal.events[-1], payload=dumps(replace(event, evaluation=None)))
        self.assert_code('validation_failed', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_replay_evaluation_identity_guard(self):
        self.start()
        self.evaluate()
        original = self.journal.events[-1]
        event = loads(original.payload)
        for change in (dict(strategy_id='other'), dict(version=2), dict(observation_started_on=DAY - timedelta(days=1))):
            with self.subTest(change=change):
                self.journal.events[-1] = replace(original, payload=dumps(replace(event, evaluation=replace(event.evaluation, **change))))
                self.assert_code('validation_failed', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_allocation_positive_guard(self):
        with self.assertRaises(DomainError):
            built(allocated_amount=D('0'))

    def test_replay_allocation_immutable_guard(self):
        self.start()
        event = loads(self.journal.events[-1].payload)
        self.journal.events[-1] = replace(
            self.journal.events[-1],
            payload=dumps(replace(event, record=replace(event.record, evidence=replace(event.record.evidence, allocated_amount=D('200000'))))),
        )
        self.assert_code('auto_frozen', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_replay_evidence_identity_immutable_guards(self):
        self.start()
        original = self.journal.events[-1]
        event = loads(original.payload)
        changes = (
            dict(account_ref='different'),
            dict(execution_instrument_id='TAIFEX:TMF:202602'),
            dict(candidate=replace(event.record.candidate, campaign_ref='different')),
            dict(expectation=replace(event.record.expectation, per_day_return=D('.002'))),
            dict(dataset_id='different'),
            dict(behavior_hash='different'),
        )
        for change in changes:
            evidence_changes = {k: v for k, v in change.items() if k in ('expectation', 'dataset_id', 'behavior_hash')}
            change = {k: v for k, v in change.items() if k not in evidence_changes}
            change['evidence'] = replace(event.record.evidence, **evidence_changes)
            with self.subTest(change=change):
                self.journal.events[-1] = replace(original, payload=dumps(replace(event, record=replace(event.record, **change))))
                self.assert_code('auto_frozen', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_replay_evaluation_type_guard(self):
        self.start()
        self.evaluate()
        event = loads(self.journal.events[-1].payload)
        self.journal.events[-1] = replace(self.journal.events[-1], payload=dumps(replace(event, evaluation='wrong')))
        self.assert_code('validation_failed', PromotionService, self.journal, Environment.BROKER_SIMULATION, now=NOW)

    def test_build_evidence_identity_guard(self):
        record = built()
        for change in (dict(strategy_id='other'), dict(version=2), dict(frozen_hash='other'), dict(partition='INVALID')):
            with self.subTest(change=change), self.assertRaises(DomainError):
                replace(record, evidence=replace(record.evidence, **change))

    def test_refresh_evidence_identity_guard(self):
        self.start()
        evidence = self.service.record('auto-1', 1).evidence
        self.assert_code('auto_evidence_changed', self.service.refresh_evidence, 'auto-1', 1, replace(evidence, version=2, behavior_hash='different'), now=NOW)

    def test_same_behavior_different_evidence_guard(self):
        self.start()
        evidence = self.service.record('auto-1', 1).evidence
        for change in (dict(allocated_amount=D('200000')), dict(dataset_id='different'), dict(trades=()), dict(trade_directions=())):
            with self.subTest(change=change):
                self.assert_code('auto_evidence_changed', self.service.refresh_evidence, 'auto-1', 1, replace(evidence, **change), now=NOW)

    def test_full_execution_evidence_survives_restart(self):
        self.start()
        original = self.service.record('auto-1', 1).evidence
        restored = PromotionService(self.journal, Environment.BROKER_SIMULATION, now=NOW)
        self.assertEqual(restored.record('auto-1', 1).evidence, original)
        self.assertEqual(restored.record('auto-1', 1).evidence.trades[0].entry, D('100'))
        self.assertEqual(restored.record('auto-1', 1).evidence.trade_directions, (Side.BUY,))

    def test_same_day_resume_cached_verdict_never_reenables(self):
        self.start()
        historical = self.evaluate()
        self.service.pause('auto-1', 1, now=NOW)
        resumed_day = DAY + timedelta(days=10)
        self.service.resume('auto-1', 1, trade_date=resumed_day, reconciled=True, cause_cleared=True, now=NOW)
        count = len(self.journal.events)
        result = self.service.evaluate_after_close('auto-1', 1, resumed_day, observation(), observation_started_on=resumed_day, now=NOW)
        self.assertEqual(result, historical)
        self.assertEqual(len(self.journal.events), count)
        self.assertFalse(self.service.record('auto-1', 1).eligible)
        self.assertEqual(self.service.record('auto-1', 1).observation_started_on, resumed_day)

    def test_build_flags_guard(self):
        for change in (dict(eligible=True), dict(observation_started_on=DAY)):
            with self.subTest(change=change):
                self.assert_code('stage_transition_denied', self.service.record_built, built(auto=intraday(strategy_id='auto-2'), **change), now=NOW)

    def test_start_conditions_independently_deny(self):
        for change in (dict(reproduced_behavior_hash='other'), dict(preopen_checks_passed=False)):
            with self.subTest(change=change):
                self.assert_code('stage_transition_denied', self.start, **change)
        other = PromotionService(MemoryJournal(), Environment.BROKER_SIMULATION, now=NOW)
        other.record_built(built(start_in_sim=False), now=NOW)
        with self.assertRaises(DomainError):
            other.start_sim('auto-1', 1, trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)

    def test_unique_resolved_instrument_guard(self):
        self.start()
        self.service.record_built(built(auto=intraday(strategy_id='auto-2', instrument_rule='TAIFEX:TMF:202601')), now=NOW)
        self.assert_code(
            'auto_instrument_busy',
            self.service.start_sim,
            'auto-2',
            1,
            trade_date=DAY,
            reproduced_behavior_hash='behavior',
            preopen_checks_passed=True,
            now=NOW,
        )

    def test_other_account_or_contract_does_not_conflict(self):
        self.start()
        for name, change in (('other-account', dict(account_ref='other')), ('other-contract', dict(execution_instrument_id='TAIFEX:TMF:202602'))):
            self.service.record_built(built(auto=intraday(strategy_id=name), **change), now=NOW)
            self.service.start_sim(name, 1, trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)

    def test_evaluation_idempotence_guard(self):
        self.start()
        verdict = self.evaluate()
        count = len(self.journal.events)
        self.assertEqual(verdict, self.evaluate(observation(net_return=D('-1'))))
        self.assertEqual(len(self.journal.events), count)
        self.assertTrue(verdict.eligible)
        self.assertTrue(self.service.record('auto-1', 1).eligible)

    def test_replay_cache_and_restart_guard(self):
        self.start()
        verdict = self.evaluate()
        restored = PromotionService(self.journal, Environment.BROKER_SIMULATION, now=NOW)
        record = restored.record('auto-1', 1)
        self.assertEqual(record.state.pause_reason, PauseReason.RESTART)
        self.assertFalse(record.permits_new_entries)
        self.assertTrue(record.protective_exits_required)
        self.assertFalse(record.eligible)
        self.assertEqual(restored.evaluate_after_close('auto-1', 1, DAY + timedelta(days=10), observation(), observation_started_on=DAY, now=NOW), verdict)
        self.assertFalse(restored.record('auto-1', 1).eligible)
        count = len(self.journal.events)
        PromotionService(self.journal, Environment.BROKER_SIMULATION, now=NOW)
        self.assertEqual(len(self.journal.events), count)

    def test_evaluation_running_guard(self):
        self.assert_code('stage_transition_denied', self.evaluate)

    def test_evaluation_epoch_guard(self):
        self.start()
        self.assert_code('validation_failed', self.evaluate, observation_started_on=DAY - timedelta(days=1))

    def test_evaluation_date_guard(self):
        self.start()
        self.assert_code(
            'validation_failed', self.service.evaluate_after_close, 'auto-1', 1, DAY - timedelta(days=1), observation(), observation_started_on=DAY, now=NOW
        )

    def test_no_local_or_live_promotion_evidence(self):
        self.start()
        for environment in (Environment.LOCAL, Environment.LIVE):
            self.service.environment = environment
            self.assert_code('stage_transition_denied', self.evaluate)
            self.assert_code('stage_transition_denied', self.service.check_drift, 'auto-1', 1, D('.04'), now=NOW)
        self.service.environment = Environment.BROKER_SIMULATION
        self.assertTrue(self.evaluate().eligible)

    def test_10_days_boundary_and_partial_day(self):
        self.start()
        self.assertFalse(self.evaluate(observation(full_trading_days=9)).eligible)
        result = self.service.evaluate_after_close('auto-1', 1, DAY + timedelta(days=11), observation(), observation_started_on=DAY, now=NOW)
        self.assertTrue(result.eligible)

    def test_incomplete_history_never_eligible(self):
        self.start()
        result = self.evaluate(observation(history_complete=False))
        self.assertFalse(result.eligible)
        self.assertFalse(result.checks[0].passed)
        self.assertEqual(loads(self.journal.events[-1].payload).evaluation.verdict, result)

    def test_drift_floor_and_exact_boundary_pause_guard(self):
        self.start()
        below = self.service.check_drift('auto-1', 1, D('.029999'), now=NOW)
        self.assertFalse(below.paused)
        self.assertEqual(below.drift_line_pct, D('.03'))
        at = self.service.check_drift('auto-1', 1, D('.03'), now=NOW)
        self.assertTrue(at.paused)
        row = self.service.record('auto-1', 1)
        self.assertEqual(row.state.pause_reason, PauseReason.DRIFT)
        self.assertFalse(row.permits_new_entries)
        self.assertTrue(row.protective_exits_required)
        count = len(self.journal.events)
        self.service.check_drift('auto-1', 1, D('.05'), now=NOW)
        self.assertEqual(len(self.journal.events), count)

    def test_drift_backtest_does_not_transition(self):
        self.service.check_drift('auto-1', 1, D('.05'), now=NOW)
        self.assertEqual(len(self.journal.events), 1)

    def test_resume_resets_epoch_and_eligibility(self):
        self.start()
        self.evaluate()
        self.service.pause('auto-1', 1, now=NOW)
        resumed_day = DAY + timedelta(days=12)
        row = self.service.resume('auto-1', 1, trade_date=resumed_day, reconciled=True, cause_cleared=True, now=NOW)
        self.assertFalse(row.eligible)
        self.assertEqual(row.observation_started_on, resumed_day)
        self.assert_code('validation_failed', self.service.evaluate_after_close, 'auto-1', 1, resumed_day, observation(), observation_started_on=DAY, now=NOW)
        result = self.service.evaluate_after_close(
            'auto-1',
            1,
            resumed_day,
            observation(trading_days=0, full_trading_days=0, completed_trades=0, round_trips=0, wins=0),
            observation_started_on=resumed_day,
            now=NOW,
        )
        self.assertFalse(result.eligible)

    def test_resume_needs_reconciliation_and_cause_clear(self):
        self.start()
        self.service.pause('auto-1', 1, now=NOW)
        for reconciled, cleared in ((False, True), (True, False)):
            self.assert_code('stage_transition_denied', self.service.resume, 'auto-1', 1, trade_date=DAY, reconciled=reconciled, cause_cleared=cleared, now=NOW)

    def test_resume_unique_guard(self):
        self.start()
        self.service.pause('auto-1', 1, now=NOW)
        self.service.record_built(built(auto=intraday(strategy_id='auto-2')), now=NOW)
        self.service.start_sim('auto-2', 1, trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)
        self.assert_code('auto_instrument_busy', self.service.resume, 'auto-1', 1, trade_date=DAY, reconciled=True, cause_cleared=True, now=NOW)

    def test_same_behavior_upgrade_and_idempotence_guard(self):
        self.start()
        row = self.refresh('auto-1', 1, behavior_hash='behavior', source_digest='new-source', result_hash='new-result', now=NOW)
        self.assertTrue(row.permits_new_entries)
        self.assertEqual(row.source_digest, 'new-source')
        count = len(self.journal.events)
        self.refresh('auto-1', 1, behavior_hash='behavior', source_digest='new-source', result_hash='new-result', now=NOW)
        self.assertEqual(len(self.journal.events), count)

    def test_changed_behavior_pause_guard(self):
        self.start()
        row = self.refresh('auto-1', 1, behavior_hash='changed', source_digest='new-source', result_hash='new-result', now=NOW)
        self.assertEqual(row.state.pause_reason, PauseReason.EVIDENCE_CHANGED)
        self.assertEqual(row.behavior_hash, 'behavior')
        self.assertEqual(row.source_digest, 'source')
        self.assertFalse(row.permits_new_entries)

    def test_changed_behavior_backtest_denies_guard(self):
        self.assert_code('auto_evidence_changed', self.refresh, 'auto-1', 1, behavior_hash='changed', source_digest='new', result_hash='new', now=NOW)

    def test_retirement_terminal_and_protection_retained(self):
        self.start()
        row = self.service.retire('auto-1', 1, now=NOW)
        self.assertEqual(row.state.run_state, RunState.RETIRED)
        self.assertFalse(row.permits_new_entries)
        self.assertTrue(row.protective_exits_required)
        self.assert_code('stage_transition_denied', self.service.resume, 'auto-1', 1, trade_date=DAY, reconciled=True, cause_cleared=True, now=NOW)

    def test_journal_failure_does_not_publish_state(self):
        self.journal.fail = True
        with self.assertRaises(OSError):
            self.start()
        self.assertEqual(self.service.record('auto-1', 1).state.stage, Stage.BACKTEST)

    def test_no_owner_approval_entry_and_live_approved_not_executable(self):
        self.assertFalse(hasattr(self.service, 'approve_live'))
        row = replace(built(), state=StageState(Stage.LIVE_APPROVED, RunState.RUNNING))
        self.assertFalse(row.permits_new_entries)
        self.assertFalse(BuildDialogOptions().live_available)

    def test_safe_view_allowlist_has_no_spec_evidence_or_trade_payload(self):
        summary = CandidateSummary('candidate', 'statistical_edge', NOW, '1d')
        self.assertEqual(CandidateSummaryView.from_summary(summary), CandidateSummaryView('candidate', 'statistical_edge', NOW, '1d'))
        self.assertEqual({f.name for f in fields(CandidateSummaryView)}, {'candidate_ref', 'verdict', 'completed_at', 'dataset_interval'})
        self.assertFalse({'signal_spec_json', 'candidate', 'expectation', 'trades', 'observation'} & {f.name for f in fields(AutoStrategyView)})
        self.assertIsNone(PromotionProgressView().observed_drawdown_pct)


if __name__ == '__main__':
    unittest.main()
