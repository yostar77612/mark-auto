"""M3 stage state machine, named thresholds and promotion/drift evaluation (pure, no I/O).

Ratios and ``*_pct`` values are fractions of the allocated amount (``Decimal('0.02')`` is 2%).
``LIVE_APPROVED`` records an owner decision only; no automatic trigger can reach it.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .arithmetic import decimal_operation
from .models import Environment, HoldingKind
from .validation import DomainError, decimal_value, identity, integer


THRESHOLDS_VERSION = 'm3-thresholds-v1'


class Stage(str, Enum):
    BACKTEST = 'BACKTEST'
    BROKER_SIM = 'BROKER_SIM'
    LIVE_APPROVED = 'LIVE_APPROVED'


class RunState(str, Enum):
    RUNNING = 'RUNNING'
    PAUSED = 'PAUSED'
    RETIRED = 'RETIRED'


class PauseReason(str, Enum):
    DRIFT = 'DRIFT'
    EVIDENCE_CHANGED = 'EVIDENCE_CHANGED'
    ORDER_FAILURES = 'ORDER_FAILURES'
    RESTART = 'RESTART'
    MANUAL = 'MANUAL'


class Trigger(str, Enum):
    """What causes a transition. ``OWNER_*`` come only from a UI command; ``AUTO_*`` from the engine."""

    OWNER_BUILD = 'OWNER_BUILD'
    AUTO_START_SIM = 'AUTO_START_SIM'
    AUTO_PAUSE = 'AUTO_PAUSE'
    OWNER_PAUSE = 'OWNER_PAUSE'
    OWNER_RESUME = 'OWNER_RESUME'
    OWNER_APPROVE_LIVE = 'OWNER_APPROVE_LIVE'
    AUTO_APPROVAL_EXPIRED = 'AUTO_APPROVAL_EXPIRED'
    AUTO_NEW_VERSION = 'AUTO_NEW_VERSION'
    OWNER_RETIRE = 'OWNER_RETIRE'


AUTOMATIC_TRIGGERS = frozenset(t for t in Trigger if t.value.startswith('AUTO_'))
_AUTO_PAUSE_REASONS = frozenset((PauseReason.DRIFT, PauseReason.EVIDENCE_CHANGED, PauseReason.ORDER_FAILURES, PauseReason.RESTART))


@dataclass(frozen=True)
class PromotionThresholds:
    version: str = THRESHOLDS_VERSION
    BUILD_REQUIRED_VERDICT: str = 'statistical_edge'
    BUILD_MIN_RESEARCH_TRADES: int = 10
    EXECUTOR_MAX_BARS: int = 5000
    PROMOTION_MIN_TRADING_DAYS: int = 10
    PROMOTION_MIN_TRADES: int = 5
    PROMOTION_MIN_ROUND_TRIPS_POSITION: int = 3
    PROMOTION_POSITION_REVIEW_DAYS: int = 120
    PROMOTION_FULL_DAY_REQUIRED: bool = True
    PROMOTION_MIN_RETURN_RATIO: Decimal = Decimal('0.5')
    PROMOTION_MAX_DRAWDOWN_RATIO: Decimal = Decimal('1.0')
    PROMOTION_WIN_RATE_TOLERANCE: Decimal = Decimal('0.15')
    PROMOTION_WIN_RATE_MIN_TRADES: int = 10
    PROMOTION_MAX_REJECT_RATE: Decimal = Decimal('0.05')
    DRIFT_DRAWDOWN_MULTIPLE: Decimal = Decimal('1.5')
    DRIFT_MIN_REFERENCE_PCT: Decimal = Decimal('0.02')
    ORDER_FAILURE_PAUSE_COUNT: int = 3
    LIVE_APPROVAL_DAYS: int = 30

    def __post_init__(self) -> None:
        identity(self.version)
        identity(self.BUILD_REQUIRED_VERDICT)
        for name in (
            'BUILD_MIN_RESEARCH_TRADES',
            'EXECUTOR_MAX_BARS',
            'PROMOTION_MIN_TRADING_DAYS',
            'PROMOTION_MIN_TRADES',
            'PROMOTION_MIN_ROUND_TRIPS_POSITION',
            'PROMOTION_POSITION_REVIEW_DAYS',
            'PROMOTION_WIN_RATE_MIN_TRADES',
            'ORDER_FAILURE_PAUSE_COUNT',
            'LIVE_APPROVAL_DAYS',
        ):
            integer(getattr(self, name), name, 1)
        if type(self.PROMOTION_FULL_DAY_REQUIRED) is not bool:
            raise DomainError('validation_failed', 'PROMOTION_FULL_DAY_REQUIRED')
        for name in (
            'PROMOTION_MIN_RETURN_RATIO',
            'PROMOTION_MAX_DRAWDOWN_RATIO',
            'PROMOTION_WIN_RATE_TOLERANCE',
            'PROMOTION_MAX_REJECT_RATE',
            'DRIFT_DRAWDOWN_MULTIPLE',
            'DRIFT_MIN_REFERENCE_PCT',
        ):
            decimal_value(getattr(self, name), name, nonnegative=True)


DEFAULT_THRESHOLDS = PromotionThresholds()
_KNOWN_THRESHOLDS = {DEFAULT_THRESHOLDS.version: DEFAULT_THRESHOLDS}


def thresholds_for(version: str) -> PromotionThresholds:
    """Resolve the thresholds pinned into a frozen strategy; an unknown version is refused."""
    try:
        return _KNOWN_THRESHOLDS[version]
    except (KeyError, TypeError):
        raise DomainError('validation_failed', 'unknown thresholds version') from None


@dataclass(frozen=True)
class ExecutionExpectation:
    """E2 expectation, as fractions of the allocated amount."""

    max_drawdown_pct: Decimal
    per_day_return: Decimal
    win_rate: Decimal

    def __post_init__(self) -> None:
        decimal_value(self.max_drawdown_pct, 'expected drawdown', nonnegative=True)
        decimal_value(self.per_day_return, 'expected daily return')
        decimal_value(self.win_rate, 'expected win rate', nonnegative=True)
        if self.win_rate > 1:
            raise DomainError('validation_failed', 'expected win rate')


@dataclass(frozen=True)
class SimObservation:
    """Broker-simulation results since the observation period began (restarted by every resume)."""

    trading_days: int
    full_trading_days: int
    completed_trades: int
    round_trips: int
    wins: int
    net_return: Decimal
    max_drawdown_pct: Decimal
    orders: int
    rejected_or_unknown_orders: int
    unresolved_reconciliation: bool
    history_complete: bool

    def __post_init__(self) -> None:
        for name in ('trading_days', 'full_trading_days', 'completed_trades', 'round_trips', 'wins', 'orders', 'rejected_or_unknown_orders'):
            integer(getattr(self, name), name)
        decimal_value(self.net_return, 'simulated return')
        decimal_value(self.max_drawdown_pct, 'simulated drawdown', nonnegative=True)
        if self.full_trading_days > self.trading_days or self.wins > self.completed_trades or self.rejected_or_unknown_orders > self.orders:
            raise DomainError('validation_failed', 'observation counts')
        if type(self.unresolved_reconciliation) is not bool or type(self.history_complete) is not bool:
            raise DomainError('validation_failed', 'observation flags')


@dataclass(frozen=True)
class Check:
    """One evaluated condition; ``actual``/``limit`` are what the audit event and the UI show."""

    name: str
    passed: bool
    actual: Decimal | None = None
    limit: Decimal | None = None


@dataclass(frozen=True)
class PromotionVerdict:
    eligible: bool
    checks: tuple[Check, ...]
    review_needed: bool


@dataclass(frozen=True)
class DriftVerdict:
    paused: bool
    reference_drawdown_pct: Decimal
    drift_line_pct: Decimal
    observed_drawdown_pct: Decimal


def reference_drawdown(expected_max_drawdown_pct: Decimal, thresholds: PromotionThresholds = DEFAULT_THRESHOLDS) -> Decimal:
    return max(decimal_value(expected_max_drawdown_pct, 'expected drawdown', nonnegative=True), thresholds.DRIFT_MIN_REFERENCE_PCT)


@decimal_operation
def evaluate_drift(expected_max_drawdown_pct: Decimal, observed_drawdown_pct: Decimal, thresholds: PromotionThresholds = DEFAULT_THRESHOLDS) -> DriftVerdict:
    """Pause when the simulated drawdown reaches the drift line (inclusive)."""
    observed = decimal_value(observed_drawdown_pct, 'observed drawdown', nonnegative=True)
    reference = reference_drawdown(expected_max_drawdown_pct, thresholds)
    line = reference * thresholds.DRIFT_DRAWDOWN_MULTIPLE
    return DriftVerdict(observed >= line, reference, line, observed)


@decimal_operation
def evaluate_promotion(
    kind: HoldingKind,
    expectation: ExecutionExpectation,
    observation: SimObservation,
    thresholds: PromotionThresholds = DEFAULT_THRESHOLDS,
) -> PromotionVerdict:
    """Evaluate every condition (all are reported); incomplete history is never eligible."""
    if not isinstance(kind, HoldingKind) or kind is HoldingKind.CUSTOM:
        raise DomainError('validation_failed', 'promotion holding kind')
    t, o = thresholds, observation
    checks: list[Check] = []

    def add(name: str, passed: bool, actual: int | Decimal | None = None, limit: int | Decimal | None = None) -> None:
        checks.append(Check(name, passed, None if actual is None else Decimal(actual), None if limit is None else Decimal(limit)))

    days = o.full_trading_days if t.PROMOTION_FULL_DAY_REQUIRED else o.trading_days
    add('history_complete', o.history_complete)
    if kind is HoldingKind.POSITION:
        add('round_trips', o.round_trips >= t.PROMOTION_MIN_ROUND_TRIPS_POSITION, o.round_trips, t.PROMOTION_MIN_ROUND_TRIPS_POSITION)
    else:
        add('trading_days', days >= t.PROMOTION_MIN_TRADING_DAYS, days, t.PROMOTION_MIN_TRADING_DAYS)
        add('trades', o.completed_trades >= t.PROMOTION_MIN_TRADES, o.completed_trades, t.PROMOTION_MIN_TRADES)
    return_floor = max(Decimal(0), t.PROMOTION_MIN_RETURN_RATIO * expectation.per_day_return * days)
    add('return', o.net_return >= return_floor, o.net_return, return_floor)
    drawdown_cap = t.PROMOTION_MAX_DRAWDOWN_RATIO * reference_drawdown(expectation.max_drawdown_pct, t)
    add('drawdown', o.max_drawdown_pct <= drawdown_cap, o.max_drawdown_pct, drawdown_cap)
    if o.completed_trades >= t.PROMOTION_WIN_RATE_MIN_TRADES:
        win_rate = Decimal(o.wins) / Decimal(o.completed_trades)
        win_floor = expectation.win_rate - t.PROMOTION_WIN_RATE_TOLERANCE
        add('win_rate', win_rate >= win_floor, win_rate, win_floor)
    reject_rate = Decimal(o.rejected_or_unknown_orders) / Decimal(o.orders) if o.orders else Decimal(0)
    add('reject_rate', reject_rate <= t.PROMOTION_MAX_REJECT_RATE, reject_rate, t.PROMOTION_MAX_REJECT_RATE)
    add('reconciliation_clean', not o.unresolved_reconciliation)
    review_needed = kind is HoldingKind.POSITION and o.trading_days > t.PROMOTION_POSITION_REVIEW_DAYS and o.round_trips < t.PROMOTION_MIN_ROUND_TRIPS_POSITION
    return PromotionVerdict(all(c.passed for c in checks), tuple(checks), review_needed)


@dataclass(frozen=True)
class StageState:
    stage: Stage
    run_state: RunState
    pause_reason: PauseReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, Stage) or not isinstance(self.run_state, RunState):
            raise DomainError('validation_failed', 'stage state types')
        if (self.run_state is RunState.PAUSED) != (self.pause_reason is not None):
            raise DomainError('validation_failed', 'pause reason required exactly when paused')
        if self.stage is Stage.BACKTEST and self.run_state is RunState.PAUSED:
            raise DomainError('validation_failed', 'the backtest stage never executes, so it cannot be paused')


INITIAL_STATE = StageState(Stage.BACKTEST, RunState.RUNNING)


@dataclass(frozen=True)
class TransitionContext:
    """Facts the caller has established; every field defaults to the refusing value."""

    environment: Environment
    start_in_sim: bool = False
    reproduced: bool = False
    preopen_checks_passed: bool = False
    reconciled: bool = False
    cause_cleared: bool = False
    eligible: bool = False
    pause_reason: PauseReason | None = None


def next_stage(current: StageState | None, trigger: Trigger, context: TransitionContext) -> StageState:
    """The only stage transition function. ``current=None`` is a candidate that is not built yet.

    Anything not in the spec section 9 table raises ``DomainError('stage_transition_denied')``.
    """
    if (current is not None and not isinstance(current, StageState)) or not isinstance(trigger, Trigger) or not isinstance(context, TransitionContext):
        raise DomainError('validation_failed', 'transition types')
    denied = DomainError('stage_transition_denied', f'{current} + {trigger.value}')
    if current is None:
        if trigger is Trigger.OWNER_BUILD:
            return INITIAL_STATE
        raise denied
    stage, run = current.stage, current.run_state
    if run is RunState.RETIRED:
        raise denied
    if trigger is Trigger.OWNER_RETIRE:
        return StageState(stage, RunState.RETIRED)
    if trigger is Trigger.AUTO_START_SIM:
        if (
            stage is Stage.BACKTEST
            and context.start_in_sim
            and context.reproduced
            and context.preopen_checks_passed
            and context.environment is Environment.BROKER_SIMULATION
        ):
            return StageState(Stage.BROKER_SIM, RunState.RUNNING)
        raise denied
    if stage is Stage.BACKTEST:
        raise denied
    if trigger is Trigger.AUTO_PAUSE or trigger is Trigger.OWNER_PAUSE:
        reason = context.pause_reason
        valid = reason in _AUTO_PAUSE_REASONS if trigger is Trigger.AUTO_PAUSE else reason is PauseReason.MANUAL
        if run is not RunState.RUNNING or not valid:
            raise denied
        # A drift pause also voids the owner's approval; other pauses keep it until it expires.
        return StageState(Stage.BROKER_SIM if reason is PauseReason.DRIFT else stage, RunState.PAUSED, reason)
    if trigger is Trigger.OWNER_RESUME:
        if run is RunState.PAUSED and context.reconciled and context.cause_cleared and context.environment is Environment.BROKER_SIMULATION:
            return StageState(stage, RunState.RUNNING)
        raise denied
    if trigger is Trigger.OWNER_APPROVE_LIVE:
        if stage is Stage.BROKER_SIM and run is RunState.RUNNING and context.eligible:
            return StageState(Stage.LIVE_APPROVED, RunState.RUNNING)
        raise denied
    if trigger is Trigger.AUTO_APPROVAL_EXPIRED or trigger is Trigger.AUTO_NEW_VERSION:
        if stage is Stage.LIVE_APPROVED:
            return StageState(Stage.BROKER_SIM, run, current.pause_reason)
        raise denied
    raise denied
