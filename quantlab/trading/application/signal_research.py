"""Training-only E2 for frozen signal targets, using M2 financial primitives.

M2's fixed-direction research loops have no SignalSource hook. This module only
orchestrates target changes; ResearchTrade, fees, tick prices, trading-day age and
minute-session validation retain their existing authorities. No gateway or AI
receives this evidence. Minute acquisition/refill remains M3-7 integration work.

HistoricalContractEvidence is a supplied applicability reference, not independent
authentication. Trusted composition must authenticate provenance and run this
synchronous operation through the existing M2 worker deadline/cancellation path
(15-minute job budget); this standalone function does not enforce that deadline.
"""

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

from .provenance import ProducerProfile
from .research import ResearchTrade
from .signal_executor import SignalExecutor
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.minute_contract import is_tmf_contract
from quantlab.trading.domain.minute_research import TAIPEI, FixedModelMinuteSettings, MinuteResearchSettings
from quantlab.trading.domain.models import HoldingKind, InstrumentSpec, Side
from quantlab.trading.domain.promotion import ExecutionExpectation, thresholds_for
from quantlab.trading.domain.signal_strategy import AutoStrategy, SignalBar, WindowMode
from quantlab.trading.domain.validation import DomainError, aware, decimal_value
from quantlab.trading.ports.signals import SignalSource


@dataclass(frozen=True)
class ExecutionEvidence:
    strategy_id: str
    version: int
    frozen_hash: str
    dataset_id: str
    result_hash: str
    behavior_hash: str
    source_digest: str
    expectation: ExecutionExpectation
    trades: tuple[ResearchTrade, ...]
    net_pnl: Decimal
    costs: Decimal
    observations: int
    allocated_amount: Decimal
    trade_directions: tuple[Side, ...]
    partition: str = 'TRAINING'

    @property
    def completed_trades(self) -> int:
        return len(self.trades)


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(type(value).__name__)


def _digest(value) -> str:
    return sha256(json.dumps(value, default=_json_value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _validate_bars(auto, spec, calendar, bars, fees, now, partition, settings):
    if partition != 'TRAINING':  # guard: training_partition
        raise DomainError('auto_execution_data_insufficient', 'training partition required')
    if auto.cost_version != fees.version:  # guard: cost_version
        raise DomainError('auto_execution_data_insufficient', 'frozen cost version mismatch')
    contracts = (f'TMF:{spec.delivery_month}', f'TAIFEX:TMF:{spec.delivery_month}', 'TMF_NEAR')
    if auto.instrument_rule not in contracts or not is_tmf_contract(spec):  # guard: contract
        raise DomainError('auto_execution_data_insufficient', 'resolved TMF contract required')
    if len(bars) < 2:  # guard: minimum_bars
        raise DomainError('auto_execution_data_insufficient', 'at least two completed bars required')
    if any(b.ends_at >= now for b in bars):  # guard: available_before_now
        raise DomainError('auto_execution_data_insufficient', 'training bars must be available before now')
    if any(a.ends_at > b.starts_at for a, b in zip(bars, bars[1:])):  # guard: ordered_bars
        raise DomainError('auto_execution_data_insufficient', 'ordered non-overlapping bars required')
    if any(b.trade_date >= spec.expiry for b in bars):  # guard: expiry
        raise DomainError('auto_execution_data_insufficient', 'contract expired within training window')
    for bar in bars:
        calendar.index(bar.trade_date)
        for price in (bar.open, bar.high, bar.low, bar.close):
            spec.validate_price(price)
    if auto.window_mode is WindowMode.FULL_HISTORY:
        if bars[0].trade_date != auto.history_anchor:  # guard: anchor
            raise DomainError('auto_execution_data_insufficient', 'history must begin at frozen anchor')
        counts = (len(bars),)
    else:
        counts = tuple(sum(b.trade_date == day for b in bars) for day in {b.trade_date for b in bars})
    if max(counts) > thresholds_for(auto.thresholds_version).EXECUTOR_MAX_BARS:  # guard: window_limit
        raise DomainError('auto_execution_data_insufficient', 'execution window exceeds bar limit')
    if auto.bar_interval in ('1m', '5m'):
        return _validate_minutes(auto, spec, calendar, bars, settings)
    if settings is not None:  # guard: daily_settings
        raise DomainError('auto_execution_data_insufficient', 'minute settings do not describe daily data')
    if bars[0].starts_at < spec.effective_at:  # guard: daily_historical_contract
        raise DomainError('auto_execution_data_insufficient', 'historical contract applicability unknown')
    if tuple(b.trade_date for b in bars) != tuple(d for d in calendar.days if bars[0].trade_date <= d <= bars[-1].trade_date):  # guard: daily_coverage
        raise DomainError('auto_execution_data_insufficient', 'daily coverage incomplete')
    return None


def _validate_minutes(auto, spec, calendar, bars, settings):
    if not isinstance(settings, MinuteResearchSettings) or isinstance(settings, FixedModelMinuteSettings):  # guard: minute_settings
        raise DomainError('auto_execution_data_insufficient', 'explicit minute training settings required')
    if settings.interval != auto.bar_interval or settings.intraday != (auto.holding_kind is HoldingKind.INTRADAY):  # guard: minute_identity
        raise DomainError('auto_execution_data_insufficient', 'minute settings mismatch')
    if settings.cutoff_minute != 13 * 60 + 35:  # guard: frozen_cutoff
        raise DomainError('auto_execution_data_insufficient', 'M2 TMF cutoff is fixed at 13:35')
    sessions = settings.sessions(calendar)
    proof = settings.historical_contract
    applicable = sessions[0].opens_at >= spec.effective_at if proof is None else proof.covers(spec, sessions[0].opens_at, sessions[-1].closes_at)
    if not applicable:  # guard: minute_historical_contract
        raise DomainError('auto_execution_data_insufficient', 'historical contract applicability unknown')
    width = timedelta(minutes=1 if auto.bar_interval == '1m' else 5)
    expected = tuple((s, s.opens_at + i * width) for s in sessions for i in range(int((s.closes_at - s.opens_at) / width)))
    if len(bars) != len(expected):  # guard: minute_count
        raise DomainError('auto_execution_data_insufficient', 'complete minute sessions required')
    if any(
        b.starts_at != start or b.ends_at != start + width or b.trade_date != s.trade_date or b.session != 'day' for b, (s, start) in zip(bars, expected)
    ):  # guard: minute_grid
        raise DomainError('auto_execution_data_insufficient', 'minute completion grid mismatch')
    return settings


def _forced(auto, settings, bars, index):
    if index == len(bars) - 1:
        return True
    if auto.holding_kind is not HoldingKind.INTRADAY:
        return False
    local = bars[index].starts_at.astimezone(TAIPEI)
    return local.hour * 60 + local.minute >= settings.cutoff_minute or bars[index + 1].trade_date != bars[index].trade_date


def _close(spec, fees, bars, position, index, reference):
    entry_index, entry_price, quantity = position
    sign = 1 if quantity > 0 else -1
    side = Side.BUY if sign == 1 else Side.SELL
    exit_price = spec.shift_ticks(reference, -sign * fees.slippage_ticks)
    gross = (exit_price - entry_price) * abs(quantity) * spec.multiplier * sign
    costs = fees.round_trip(spec, entry_price, exit_price, abs(quantity), side)
    return ResearchTrade(entry_index, index, abs(quantity), entry_price, exit_price, gross, costs), side


def _stop_reference(auto, spec, bar, position):
    _, entry_price, quantity = position
    long = quantity > 0
    stop = spec.round_price(entry_price * (1 - auto.protective_stop_pct if long else 1 + auto.protective_stop_pct), up=not long)
    if bar.low <= stop if long else bar.high >= stop:
        return min(bar.open, stop) if long else max(bar.open, stop)
    return None


def _traverse(auto, spec, calendar, bars, fees, source, settings):
    executor = SignalExecutor(source, f'TAIFEX:TMF:{spec.delivery_month}', lot_size=spec.lot_size)
    position, trades, directions, marks = None, [], [], []
    realized = Decimal(0)
    for index in range(1, len(bars)):
        bar = bars[index]
        previous = bars[index - 1]
        intent = executor.decide(auto, bars[:index], previous.ends_at, 0)
        desired = 0 if intent is None else intent.desired_quantity
        forced = _forced(auto, settings, bars, index)
        same_day = auto.holding_kind is not HoldingKind.INTRADAY or previous.trade_date == bar.trade_date
        timed = position is not None and auto.max_hold_days > 0 and calendar.age(bars[position[0]].trade_date, bar.trade_date) >= auto.max_hold_days
        if position is not None and (forced or timed or desired != position[2]):
            trade, side = _close(spec, fees, bars, position, index, bar.open)
            trades.append(trade)
            directions.append(side)
            realized += trade.gross - trade.costs
            position = None
        if position is None and desired and not forced and not timed and same_day:
            sign = 1 if desired > 0 else -1
            position = (index, spec.shift_ticks(bar.open, sign * fees.slippage_ticks), desired)
        if position is not None:
            stop = _stop_reference(auto, spec, bar, position)
            if stop is not None:
                trade, side = _close(spec, fees, bars, position, index, stop)
                trades.append(trade)
                directions.append(side)
                realized += trade.gross - trade.costs
                position = None
        mark = realized
        if position is not None:
            _, entry_price, quantity = position
            side = Side.BUY if quantity > 0 else Side.SELL
            mark += (bar.close - entry_price) * quantity * spec.multiplier - fees.transaction(spec, side, entry_price, abs(quantity))
        marks.append(mark)
    return tuple(trades), tuple(directions), tuple(marks)


@decimal_operation
def research_auto_strategy(
    auto: AutoStrategy,
    spec: InstrumentSpec,
    calendar: TradingCalendar,
    bars: tuple[SignalBar, ...],
    fees: FeeSchedule,
    source: SignalSource,
    *,
    allocated_amount: Decimal,
    now: datetime,
    source_profile: ProducerProfile,
    partition: str = 'TRAINING',
    settings: MinuteResearchSettings | None = None,
) -> ExecutionEvidence:
    """No I/O; trusted composition supplies training provenance and resolved contract.

    Interval-reference checks do not authenticate that provenance. Minute session
    settings bound total raw minutes to 10000; each executor window is bounded by
    the frozen thresholds. Worker timeout/cancellation is an integration duty.

    Signal fills use the next open. Protective stops use the adverse gap/stop
    price plus slippage, including the entry bar. Cutoff/time exits cannot reopen
    on that bar; reversals close then open with independent adverse costs.
    """
    aware(now)
    decimal_value(allocated_amount, 'allocated amount', positive=True)
    settings = _validate_bars(auto, spec, calendar, bars, fees, now, partition, settings)
    trades, directions, marks = _traverse(auto, spec, calendar, bars, fees, source, settings)
    equity = sum((t.gross - t.costs for t in trades), Decimal(0))
    peak = drawdown = Decimal(0)
    for mark in marks:
        peak = max(peak, mark)
        drawdown = max(drawdown, peak - mark)
    days = len({b.trade_date for b in bars})
    wins = sum(t.gross > t.costs for t in trades)
    expectation = ExecutionExpectation(drawdown / allocated_amount, equity / allocated_amount / days, Decimal(wins) / len(trades) if trades else Decimal(0))
    dataset = _digest((bars, spec, calendar, fees, settings, allocated_amount))
    # Marks/expectation are behavior too: identical fills must not hide an
    # upgraded valuation algorithm changing the promotion/drift reference.
    behavior = _digest((auto.frozen_hash, dataset, trades, directions, marks, expectation))
    result = _digest((behavior, source_profile.source_digest, expectation, equity))
    return ExecutionEvidence(
        auto.strategy_id,
        auto.version,
        auto.frozen_hash,
        dataset,
        result,
        behavior,
        source_profile.source_digest,
        expectation,
        trades,
        equity,
        sum((t.costs for t in trades), Decimal(0)),
        len(bars),
        allocated_amount,
        directions,
    )
