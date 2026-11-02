"""M3 stage state machine, thresholds, promotion and drift: pure-function acceptance."""

from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal
from itertools import product
import unittest

from quantlab.trading.domain.models import Environment, HoldingKind
from quantlab.trading.domain.promotion import (
    AUTOMATIC_TRIGGERS,
    DEFAULT_THRESHOLDS,
    INITIAL_STATE,
    THRESHOLDS_VERSION,
    ExecutionExpectation,
    PauseReason,
    PromotionThresholds,
    RunState,
    SimObservation,
    Stage,
    StageState,
    TransitionContext,
    Trigger,
    evaluate_drift,
    evaluate_promotion,
    next_stage,
    reference_drawdown,
    thresholds_for,
)
from quantlab.trading.domain.validation import DomainError
from quantlab.verdict import STATISTICAL_EDGE

D = Decimal
SIM, LOCAL, LIVE = Environment.BROKER_SIMULATION, Environment.LOCAL, Environment.LIVE
BT = INITIAL_STATE
SIM_RUN = StageState(Stage.BROKER_SIM, RunState.RUNNING)
APPROVED = StageState(Stage.LIVE_APPROVED, RunState.RUNNING)


def paused(stage: Stage, reason: PauseReason) -> StageState:
    return StageState(stage, RunState.PAUSED, reason)


def retired(stage: Stage) -> StageState:
    return StageState(stage, RunState.RETIRED)


def ctx(environment: Environment = SIM, **facts: object) -> TransitionContext:
    return TransitionContext(environment, **facts)


ALL_FACTS = dict(start_in_sim=True, reproduced=True, preopen_checks_passed=True, reconciled=True, cause_cleared=True, eligible=True)
AUTO_REASONS = (PauseReason.DRIFT, PauseReason.EVIDENCE_CHANGED, PauseReason.ORDER_FAILURES, PauseReason.RESTART)


class ThresholdTests(unittest.TestCase):
    def test_named_defaults_match_spec_section_10(self) -> None:
        t = DEFAULT_THRESHOLDS
        self.assertEqual(t.version, 'm3-thresholds-v1')
        self.assertEqual(THRESHOLDS_VERSION, t.version)
        self.assertEqual(t.BUILD_REQUIRED_VERDICT, STATISTICAL_EDGE)
        expected = dict(
            BUILD_MIN_RESEARCH_TRADES=10,
            EXECUTOR_MAX_BARS=5000,
            PROMOTION_MIN_TRADING_DAYS=10,
            PROMOTION_MIN_TRADES=5,
            PROMOTION_MIN_ROUND_TRIPS_POSITION=3,
            PROMOTION_POSITION_REVIEW_DAYS=120,
            PROMOTION_FULL_DAY_REQUIRED=True,
            PROMOTION_MIN_RETURN_RATIO=D('0.5'),
            PROMOTION_MAX_DRAWDOWN_RATIO=D('1.0'),
            PROMOTION_WIN_RATE_TOLERANCE=D('0.15'),
            PROMOTION_WIN_RATE_MIN_TRADES=10,
            PROMOTION_MAX_REJECT_RATE=D('0.05'),
            DRIFT_DRAWDOWN_MULTIPLE=D('1.5'),
            DRIFT_MIN_REFERENCE_PCT=D('0.02'),
            ORDER_FAILURE_PAUSE_COUNT=3,
            LIVE_APPROVAL_DAYS=30,
        )
        self.assertEqual({f.name: getattr(t, f.name) for f in fields(t) if f.name not in ('version', 'BUILD_REQUIRED_VERDICT')}, expected)

    def test_frozen_and_resolvable_by_version(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_THRESHOLDS.EXECUTOR_MAX_BARS = 1  # type: ignore[misc]
        self.assertIs(thresholds_for('m3-thresholds-v1'), DEFAULT_THRESHOLDS)
        for unknown in ('m3-thresholds-v2', '', None):
            with self.assertRaises(DomainError):
                thresholds_for(unknown)  # type: ignore[arg-type]

    def test_invalid_thresholds_are_refused(self) -> None:
        for change in (dict(PROMOTION_MIN_TRADING_DAYS=0), dict(DRIFT_DRAWDOWN_MULTIPLE=D('-1')), dict(PROMOTION_FULL_DAY_REQUIRED=1), dict(DRIFT_MIN_REFERENCE_PCT=0.02)):
            with self.subTest(change), self.assertRaises(DomainError):
                replace(DEFAULT_THRESHOLDS, **change)


EXPECT = ExecutionExpectation(max_drawdown_pct=D('0.05'), per_day_return=D('0.001'), win_rate=D('0.75'))


def observation(**changes: object) -> SimObservation:
    base = dict(
        trading_days=10,
        full_trading_days=10,
        completed_trades=5,
        round_trips=5,
        wins=3,
        net_return=D('0.005'),
        max_drawdown_pct=D('0.05'),
        orders=20,
        rejected_or_unknown_orders=1,
        unresolved_reconciliation=False,
        history_complete=True,
    )
    base.update(changes)
    return SimObservation(**base)  # type: ignore[arg-type]


def verdict(kind: HoldingKind = HoldingKind.INTRADAY, expectation: ExecutionExpectation = EXPECT, thresholds: PromotionThresholds = DEFAULT_THRESHOLDS, **changes: object):
    return evaluate_promotion(kind, expectation, observation(**changes), thresholds)


def failed(result) -> set[str]:
    return {c.name for c in result.checks if not c.passed}


class PromotionTests(unittest.TestCase):
    def test_exactly_on_every_limit_is_eligible(self) -> None:
        result = verdict()
        self.assertTrue(result.eligible, failed(result))
        self.assertEqual(failed(result), set())

    def test_boundary_table(self) -> None:
        # (label, kind, expectation override, observation change, failing check or None)
        intraday, swing, position = HoldingKind.INTRADAY, HoldingKind.SWING, HoldingKind.POSITION
        table = [
            ('days at minimum', intraday, {}, dict(), None),
            ('days one short', intraday, {}, dict(trading_days=9, full_trading_days=9, net_return=D('0.0045')), 'trading_days'),
            ('partial days are not counted', intraday, {}, dict(trading_days=12, full_trading_days=9), 'trading_days'),
            ('trades at minimum', swing, {}, dict(completed_trades=5), None),
            ('trades one short', swing, {}, dict(completed_trades=4, wins=3), 'trades'),
            ('return exactly the floor', intraday, {}, dict(net_return=D('0.005')), None),
            ('return one unit below the floor', intraday, {}, dict(net_return=D('0.0049999')), 'return'),
            ('zero return when no profit expected', intraday, dict(per_day_return=D('0')), dict(net_return=D('0')), None),
            ('negative return when a loss is expected', intraday, dict(per_day_return=D('-0.01')), dict(net_return=D('-0.0001')), 'return'),
            ('drawdown exactly the cap', intraday, {}, dict(max_drawdown_pct=D('0.05')), None),
            ('drawdown one unit above the cap', intraday, {}, dict(max_drawdown_pct=D('0.0500001')), 'drawdown'),
            ('small reference drawdown uses the 2% floor: at', intraday, dict(max_drawdown_pct=D('0.01')), dict(max_drawdown_pct=D('0.02')), None),
            ('small reference drawdown uses the 2% floor: above', intraday, dict(max_drawdown_pct=D('0.01')), dict(max_drawdown_pct=D('0.0201')), 'drawdown'),
            ('win rate exactly the floor', intraday, {}, dict(completed_trades=10, wins=6), None),
            ('win rate one trade below the floor', intraday, {}, dict(completed_trades=10, wins=5), 'win_rate'),
            ('win rate ignored below 10 trades', intraday, {}, dict(completed_trades=9, wins=0), None),
            ('reject rate exactly the cap', intraday, {}, dict(orders=20, rejected_or_unknown_orders=1), None),
            ('reject rate above the cap', intraday, {}, dict(orders=20, rejected_or_unknown_orders=2), 'reject_rate'),
            ('no orders is a clean reject rate', intraday, {}, dict(orders=0, rejected_or_unknown_orders=0), None),
            ('unresolved reconciliation', intraday, {}, dict(unresolved_reconciliation=True), 'reconciliation_clean'),
            ('history incomplete', intraday, {}, dict(history_complete=False), 'history_complete'),
            ('position needs only round trips', position, {}, dict(trading_days=1, full_trading_days=1, completed_trades=0, wins=0, round_trips=3, net_return=D('0.0005')), None),
            ('position one round trip short', position, {}, dict(round_trips=2), 'round_trips'),
            ('position ignores the day and trade minimums', position, {}, dict(trading_days=1, full_trading_days=1, completed_trades=0, wins=0, round_trips=3, net_return=D('0.0005')), None),
        ]
        for label, kind, expectation, change, failing in table:
            with self.subTest(label):
                result = verdict(kind, replace(EXPECT, **expectation), **change)
                self.assertEqual(failed(result), set() if failing is None else {failing})
                self.assertEqual(result.eligible, failing is None)

    def test_every_condition_is_reported_not_short_circuited(self) -> None:
        result = verdict(trading_days=1, full_trading_days=1, completed_trades=0, wins=0, net_return=D('-1'), max_drawdown_pct=D('0.9'), history_complete=False,
                         unresolved_reconciliation=True, orders=1, rejected_or_unknown_orders=1)
        self.assertEqual(failed(result), {'history_complete', 'trading_days', 'trades', 'return', 'drawdown', 'reject_rate', 'reconciliation_clean'})
        names = [c.name for c in verdict(completed_trades=10, wins=10).checks]
        self.assertEqual(names, ['history_complete', 'trading_days', 'trades', 'return', 'drawdown', 'win_rate', 'reject_rate', 'reconciliation_clean'])
        by_name = {c.name: c for c in verdict().checks}
        self.assertEqual((by_name['drawdown'].actual, by_name['drawdown'].limit), (D('0.05'), D('0.05')))
        self.assertEqual((by_name['trading_days'].actual, by_name['trading_days'].limit), (D(10), D(10)))

    def test_incomplete_history_is_never_eligible_whatever_else_holds(self) -> None:
        for kind in (HoldingKind.INTRADAY, HoldingKind.SWING, HoldingKind.POSITION):
            with self.subTest(kind):
                self.assertFalse(verdict(kind, history_complete=False).eligible)

    def test_partial_days_count_only_when_full_days_are_not_required(self) -> None:
        lenient = replace(DEFAULT_THRESHOLDS, PROMOTION_FULL_DAY_REQUIRED=False)
        partial = dict(trading_days=10, full_trading_days=6)
        self.assertEqual(failed(verdict(**partial)), {'trading_days'})
        self.assertEqual(failed(verdict(thresholds=lenient, **partial)), set())

    def test_position_review_is_a_notice_not_an_approval_or_rejection(self) -> None:
        common = dict(completed_trades=0, wins=0, round_trips=2)
        self.assertFalse(verdict(HoldingKind.POSITION, trading_days=120, full_trading_days=120, **common).review_needed)
        late = verdict(HoldingKind.POSITION, trading_days=121, full_trading_days=121, **common)
        self.assertTrue(late.review_needed)
        self.assertFalse(late.eligible)
        enough = verdict(HoldingKind.POSITION, trading_days=121, full_trading_days=121, completed_trades=0, wins=0, round_trips=3)
        self.assertFalse(enough.review_needed)
        self.assertFalse(verdict(HoldingKind.SWING, trading_days=500, full_trading_days=500, round_trips=0).review_needed)

    def test_custom_kind_and_bad_values_are_refused(self) -> None:
        with self.assertRaises(DomainError):
            verdict(HoldingKind.CUSTOM)
        for change in (dict(wins=6), dict(rejected_or_unknown_orders=21), dict(full_trading_days=11), dict(net_return=1.0), dict(history_complete=1)):
            with self.subTest(change), self.assertRaises(DomainError):
                observation(**change)
        with self.assertRaises(DomainError):
            ExecutionExpectation(D('0.05'), D('0.001'), D('1.5'))


class DriftTests(unittest.TestCase):
    def test_drift_table(self) -> None:
        # (expected backtest drawdown, observed simulated drawdown, paused, reference, line)
        table = [
            (D('0.10'), D('0.15'), True, D('0.10'), D('0.150')),
            (D('0.10'), D('0.1499999'), False, D('0.10'), D('0.150')),
            (D('0.10'), D('0.16'), True, D('0.10'), D('0.150')),
            (D('0.10'), D('0'), False, D('0.10'), D('0.150')),
            (D('0.01'), D('0.03'), True, D('0.02'), D('0.030')),
            (D('0.01'), D('0.0299999'), False, D('0.02'), D('0.030')),
            (D('0'), D('0.03'), True, D('0.02'), D('0.030')),
            (D('0.02'), D('0.03'), True, D('0.02'), D('0.030')),
            (D('0.0199'), D('0.0299'), False, D('0.02'), D('0.030')),
        ]
        for expected, observed, is_paused, reference, line in table:
            with self.subTest(expected=expected, observed=observed):
                result = evaluate_drift(expected, observed)
                self.assertEqual((result.paused, result.reference_drawdown_pct, result.drift_line_pct), (is_paused, reference, line))
                self.assertEqual(result.observed_drawdown_pct, observed)

    def test_multiple_comes_from_the_named_threshold(self) -> None:
        strict = replace(DEFAULT_THRESHOLDS, DRIFT_DRAWDOWN_MULTIPLE=D('1'))
        self.assertTrue(evaluate_drift(D('0.10'), D('0.10'), strict).paused)
        self.assertFalse(evaluate_drift(D('0.10'), D('0.10')).paused)
        self.assertEqual(reference_drawdown(D('0.5')), D('0.5'))

    def test_negative_drawdowns_are_refused(self) -> None:
        for expected, observed in ((D('-0.01'), D('0.01')), (D('0.01'), D('-0.01')), (0.01, D('0.01'))):
            with self.subTest(expected=expected), self.assertRaises(DomainError):
                evaluate_drift(expected, observed)  # type: ignore[arg-type]


def all_states() -> list[StageState | None]:
    states: list[StageState | None] = [None, BT]
    for stage in (Stage.BROKER_SIM, Stage.LIVE_APPROVED):
        states.append(StageState(stage, RunState.RUNNING))
        states.extend(paused(stage, reason) for reason in PauseReason)
    states.extend(retired(stage) for stage in Stage)
    return states


def all_contexts() -> list[TransitionContext]:
    names = tuple(ALL_FACTS)
    return [
        TransitionContext(environment, **dict(zip(names, flags)), pause_reason=reason)
        for environment in Environment
        for flags in product((False, True), repeat=len(names))
        for reason in (None, *PauseReason)
    ]


CONTEXTS = all_contexts()


def _result(state: StageState | None, trigger: Trigger, context: TransitionContext) -> StageState | None:
    try:
        return next_stage(state, trigger, context)
    except DomainError:
        return None


_GRID: list[tuple[StageState | None, Trigger, TransitionContext, StageState | None]] | None = None


def grid() -> list[tuple[StageState | None, Trigger, TransitionContext, StageState | None]]:
    """Every (state, trigger, context) with its result (None = denied), computed once."""
    global _GRID
    if _GRID is None:
        _GRID = [(state, trigger, context, _result(state, trigger, context)) for state in all_states() for trigger in Trigger for context in CONTEXTS]
    return _GRID


# The complete set of legal (from, trigger, to) edges: spec section 9, one line per row.
LEGAL_EDGES = frozenset(
    [(None, Trigger.OWNER_BUILD, BT), (BT, Trigger.AUTO_START_SIM, SIM_RUN)]
    + [(running, Trigger.OWNER_APPROVE_LIVE, APPROVED) for running in (SIM_RUN,)]
    + [
        (StageState(stage, RunState.RUNNING), trigger, StageState(Stage.BROKER_SIM if reason is PauseReason.DRIFT else stage, RunState.PAUSED, reason))
        for stage in (Stage.BROKER_SIM, Stage.LIVE_APPROVED)
        for trigger, reasons in ((Trigger.AUTO_PAUSE, AUTO_REASONS), (Trigger.OWNER_PAUSE, (PauseReason.MANUAL,)))
        for reason in reasons
    ]
    + [(paused(stage, reason), Trigger.OWNER_RESUME, StageState(stage, RunState.RUNNING)) for stage in (Stage.BROKER_SIM, Stage.LIVE_APPROVED) for reason in PauseReason]
    + [
        (StageState(Stage.LIVE_APPROVED, run, reason), trigger, StageState(Stage.BROKER_SIM, run, reason))
        for trigger in (Trigger.AUTO_APPROVAL_EXPIRED, Trigger.AUTO_NEW_VERSION)
        for run, reason in [(RunState.RUNNING, None)] + [(RunState.PAUSED, r) for r in PauseReason]
    ]
    + [(state, Trigger.OWNER_RETIRE, retired(state.stage)) for state in all_states() if state is not None and state.run_state is not RunState.RETIRED]
)


class StageMachineTests(unittest.TestCase):
    def test_every_state_trigger_context_combination_is_legal_or_denied(self) -> None:
        observed = {(state, trigger, result) for state, trigger, _, result in grid() if result is not None}
        self.assertEqual(observed - LEGAL_EDGES, set(), 'unlisted transition succeeded')
        self.assertEqual(LEGAL_EDGES - observed, set(), 'listed transition is unreachable')
        self.assertEqual(len(grid()), len(all_states()) * len(Trigger) * len(CONTEXTS))

    def test_denials_use_the_stage_transition_denied_code(self) -> None:
        for state, trigger, context, result in grid()[::997]:
            if result is None:
                with self.assertRaises(DomainError) as raised:
                    next_stage(state, trigger, context)
                self.assertEqual(raised.exception.code, 'stage_transition_denied')

    def test_positive_rows_with_their_minimal_conditions(self) -> None:
        table = [
            ('build', None, Trigger.OWNER_BUILD, ctx(), BT),
            ('build in any environment', None, Trigger.OWNER_BUILD, ctx(LOCAL), BT),
            ('start in simulation', BT, Trigger.AUTO_START_SIM, ctx(start_in_sim=True, reproduced=True, preopen_checks_passed=True), SIM_RUN),
            ('drift pause', SIM_RUN, Trigger.AUTO_PAUSE, ctx(pause_reason=PauseReason.DRIFT), paused(Stage.BROKER_SIM, PauseReason.DRIFT)),
            ('evidence pause', SIM_RUN, Trigger.AUTO_PAUSE, ctx(pause_reason=PauseReason.EVIDENCE_CHANGED), paused(Stage.BROKER_SIM, PauseReason.EVIDENCE_CHANGED)),
            ('order failure pause', SIM_RUN, Trigger.AUTO_PAUSE, ctx(pause_reason=PauseReason.ORDER_FAILURES), paused(Stage.BROKER_SIM, PauseReason.ORDER_FAILURES)),
            ('restart pause', SIM_RUN, Trigger.AUTO_PAUSE, ctx(LIVE, pause_reason=PauseReason.RESTART), paused(Stage.BROKER_SIM, PauseReason.RESTART)),
            ('manual pause', SIM_RUN, Trigger.OWNER_PAUSE, ctx(pause_reason=PauseReason.MANUAL), paused(Stage.BROKER_SIM, PauseReason.MANUAL)),
            ('resume', paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_RESUME, ctx(reconciled=True, cause_cleared=True), SIM_RUN),
            ('approve', SIM_RUN, Trigger.OWNER_APPROVE_LIVE, ctx(eligible=True), APPROVED),
            ('approve needs no environment fact', SIM_RUN, Trigger.OWNER_APPROVE_LIVE, ctx(LOCAL, eligible=True), APPROVED),
            ('approval expires', APPROVED, Trigger.AUTO_APPROVAL_EXPIRED, ctx(), SIM_RUN),
            ('new version voids approval', APPROVED, Trigger.AUTO_NEW_VERSION, ctx(), SIM_RUN),
            ('drift while approved voids approval', APPROVED, Trigger.AUTO_PAUSE, ctx(pause_reason=PauseReason.DRIFT), paused(Stage.BROKER_SIM, PauseReason.DRIFT)),
            ('other pause keeps approval', APPROVED, Trigger.AUTO_PAUSE, ctx(pause_reason=PauseReason.ORDER_FAILURES), paused(Stage.LIVE_APPROVED, PauseReason.ORDER_FAILURES)),
            ('resume keeps approval', paused(Stage.LIVE_APPROVED, PauseReason.MANUAL), Trigger.OWNER_RESUME, ctx(reconciled=True, cause_cleared=True), APPROVED),
            ('expiry keeps the pause', paused(Stage.LIVE_APPROVED, PauseReason.MANUAL), Trigger.AUTO_APPROVAL_EXPIRED, ctx(), paused(Stage.BROKER_SIM, PauseReason.MANUAL)),
            ('retire from backtest', BT, Trigger.OWNER_RETIRE, ctx(), retired(Stage.BACKTEST)),
            ('retire while paused', paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_RETIRE, ctx(), retired(Stage.BROKER_SIM)),
            ('retire when approved', APPROVED, Trigger.OWNER_RETIRE, ctx(), retired(Stage.LIVE_APPROVED)),
        ]
        for label, state, trigger, context, expected in table:
            with self.subTest(label):
                self.assertEqual(next_stage(state, trigger, context), expected)

    def test_removing_any_single_condition_denies(self) -> None:
        start = dict(start_in_sim=True, reproduced=True, preopen_checks_passed=True)
        resume = dict(reconciled=True, cause_cleared=True)
        table = [
            (BT, Trigger.AUTO_START_SIM, {**start, 'start_in_sim': False}, SIM),
            (BT, Trigger.AUTO_START_SIM, {**start, 'reproduced': False}, SIM),
            (BT, Trigger.AUTO_START_SIM, {**start, 'preopen_checks_passed': False}, SIM),
            (BT, Trigger.AUTO_START_SIM, start, LOCAL),
            (BT, Trigger.AUTO_START_SIM, start, LIVE),
            (paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_RESUME, {**resume, 'reconciled': False}, SIM),
            (paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_RESUME, {**resume, 'cause_cleared': False}, SIM),
            (paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_RESUME, resume, LOCAL),
            (paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_RESUME, resume, LIVE),
            (SIM_RUN, Trigger.OWNER_APPROVE_LIVE, dict(eligible=False), SIM),
            (SIM_RUN, Trigger.OWNER_RESUME, resume, SIM),
            (SIM_RUN, Trigger.AUTO_PAUSE, dict(pause_reason=None), SIM),
            (SIM_RUN, Trigger.AUTO_PAUSE, dict(pause_reason=PauseReason.MANUAL), SIM),
            (SIM_RUN, Trigger.OWNER_PAUSE, dict(pause_reason=PauseReason.DRIFT), SIM),
            (SIM_RUN, Trigger.OWNER_PAUSE, dict(pause_reason=None), SIM),
            (paused(Stage.BROKER_SIM, PauseReason.MANUAL), Trigger.OWNER_PAUSE, dict(pause_reason=PauseReason.MANUAL), SIM),
            (paused(Stage.BROKER_SIM, PauseReason.DRIFT), Trigger.OWNER_APPROVE_LIVE, dict(eligible=True), SIM),
        ]
        for state, trigger, facts, environment in table:
            with self.subTest(state=state, trigger=trigger, facts=facts, environment=environment), self.assertRaises(DomainError) as raised:
                next_stage(state, trigger, ctx(environment, **facts))
            self.assertEqual(raised.exception.code, 'stage_transition_denied')

    def test_never_auto_promotes_to_production(self) -> None:
        def enters_live_approved(state: StageState | None, result: StageState | None) -> bool:
            return result is not None and result.stage is Stage.LIVE_APPROVED and (state is None or state.stage is not Stage.LIVE_APPROVED)

        automatic = {(state, trigger) for state, trigger, _, result in grid() if trigger in AUTOMATIC_TRIGGERS and enters_live_approved(state, result)}
        self.assertEqual(automatic, set())
        every = {(state, trigger) for state, trigger, _, result in grid() if enters_live_approved(state, result)}
        self.assertEqual(every, {(SIM_RUN, Trigger.OWNER_APPROVE_LIVE)})
        self.assertEqual(AUTOMATIC_TRIGGERS, {Trigger.AUTO_START_SIM, Trigger.AUTO_PAUSE, Trigger.AUTO_APPROVAL_EXPIRED, Trigger.AUTO_NEW_VERSION})

    def test_retired_is_terminal(self) -> None:
        self.assertEqual([r for state, _, _, r in grid() if state is not None and state.run_state is RunState.RETIRED and r is not None], [])

    def test_backtest_cannot_be_skipped_and_only_the_owner_builds(self) -> None:
        from_nothing = {trigger for state, trigger, _, r in grid() if state is None and r is not None}
        self.assertEqual(from_nothing, {Trigger.OWNER_BUILD})
        self.assertEqual({r for state, trigger, _, r in grid() if state is None and r is not None}, {BT})
        from_backtest = {trigger for state, trigger, _, r in grid() if state == BT and r is not None}
        self.assertEqual(from_backtest, {Trigger.AUTO_START_SIM, Trigger.OWNER_RETIRE})

    def test_local_and_live_never_enter_or_reenter_broker_simulation_running(self) -> None:
        for state, trigger, context, result in grid():
            if context.environment is not SIM and trigger in (Trigger.AUTO_START_SIM, Trigger.OWNER_RESUME):
                self.assertIsNone(result, (state, trigger, context.environment))

    def test_state_invariants_and_type_checks(self) -> None:
        for bad in (
            lambda: StageState(Stage.BROKER_SIM, RunState.PAUSED),
            lambda: StageState(Stage.BROKER_SIM, RunState.RUNNING, PauseReason.DRIFT),
            lambda: StageState(Stage.BACKTEST, RunState.PAUSED, PauseReason.MANUAL),
            lambda: StageState('BROKER_SIM', RunState.RUNNING),  # type: ignore[arg-type]
            lambda: next_stage(BT, 'AUTO_START_SIM', ctx()),  # type: ignore[arg-type]
            lambda: next_stage(BT, Trigger.AUTO_START_SIM, SIM),  # type: ignore[arg-type]
        ):
            with self.assertRaises(DomainError):
                bad()


if __name__ == '__main__':
    unittest.main()
