"""Minute-only training: completed signal, next open, explicit forced exits.

This receipt intentionally cannot authorize the daily-policy execution engine.
The shared envelope remains readable, but its fingerprint has a minute namespace.
"""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from .codec import dumps, register
from .provenance import ProducerProfile
from .research import ResearchResult, ResearchTrade, entry_signal, exit_signal, research_fingerprint
from .state import StrategyRecord
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.minute_contract import HistoricalContractEvidence, is_tmf_contract
from quantlab.trading.domain.minute_research import MINUTE, TAIPEI, MinuteResearchSettings
from quantlab.trading.domain.models import HoldingKind, InstrumentSpec, Side
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError


@dataclass(frozen=True)
class MinuteResearchResult(ResearchResult):
    minute_settings: MinuteResearchSettings | None = None
    calendar_version: str = ''
    cost_version: str = ''
    price_basis: str = 'RAW_CONTRACT'


register(HistoricalContractEvidence, MinuteResearchSettings, MinuteResearchResult)


def validate_minute_request(strategy, spec, calendar, settings) -> tuple:
    if not isinstance(settings, MinuteResearchSettings) or not is_tmf_contract(spec):
        raise DomainError('capability_missing', 'minute training requires an explicit TMF contract')
    if strategy.form.instrument_id != spec.instrument_id or strategy.form.market is not spec.market:
        raise DomainError('validation_failed', 'minute strategy contract mismatch')
    if strategy.definition is not None and strategy.definition.bar_interval != settings.interval:
        raise DomainError('validation_failed', 'minute strategy interval mismatch')
    if settings.intraday != (strategy.policy.kind is HoldingKind.INTRADAY) or settings.intraday and settings.cutoff_minute > 13 * 60 + 35:
        raise DomainError('validation_failed', 'minute intraday policy or TMF cutoff mismatch')
    sessions = settings.sessions(calendar)
    evidence = settings.historical_contract
    if (
        evidence is not None and not evidence.covers(spec, sessions[0].opens_at, sessions[-1].closes_at)
        or evidence is None and sessions[0].opens_at < spec.effective_at
    ):
        raise DomainError('instrument_unresolved', 'historical contract applicability is unknown')
    return sessions


def validate_minute_job(strategy, spec, calendar, bars, settings) -> tuple:
    sessions = validate_minute_request(strategy, spec, calendar, settings)
    width = 1 if settings.interval == '1m' else 5
    expected = tuple((s, s.opens_at + i * MINUTE) for s in sessions for i in range(0, int((s.closes_at - s.opens_at) / MINUTE), width))
    if type(bars) is not tuple or len(bars) != len(expected):
        raise DomainError('validation_failed', 'minute research requires complete sessions')
    for bar, (session, start) in zip(bars, expected):
        if (
            not isinstance(bar, CompletedBar)
            or bar.opened_at != start
            or bar.ended_at != start + width * MINUTE
            or bar.available_at != bar.ended_at
            or spec.expiry is None
            or session.trade_date >= spec.expiry
        ):
            raise DomainError('validation_failed', 'minute completion grid or contract expiry')
    return tuple(s.trade_date for s, _ in expected)


def _age(settings, day_indices, bars, days, entry_index, index):
    if settings.holding_unit == 'TRADING_DAYS':
        return day_indices[days[index]] - day_indices[days[entry_index]]
    return int((bars[index].opened_at - bars[entry_index].opened_at) / MINUTE)


def _forced(settings, bars, days, index):
    local = bars[index].opened_at.astimezone(TAIPEI)
    cutoff = local.hour * 60 + local.minute >= settings.cutoff_minute
    return index == len(bars) - 1 or settings.intraday and (cutoff or days[index + 1] != days[index])


def _trade(strategy, spec, fees, bars, position, index):
    entry_index, entry_price = position
    sign = 1 if strategy.form.direction is Side.BUY else -1
    exit_price = spec.shift_ticks(bars[index].open, -sign * fees.slippage_ticks)
    costs = fees.round_trip(spec, entry_price, exit_price, spec.lot_size, strategy.form.direction)
    gross = (exit_price - entry_price) * spec.lot_size * spec.multiplier * sign
    return ResearchTrade(entry_index, index, spec.lot_size, entry_price, exit_price, gross, costs)


@decimal_operation
def research_minutes(
    strategy: StrategyRecord,
    spec: InstrumentSpec,
    calendar: TradingCalendar,
    bars: tuple[CompletedBar, ...],
    fees: FeeSchedule,
    *,
    settings: MinuteResearchSettings,
    source_profile: ProducerProfile | None = None,
) -> MinuteResearchResult:
    days = validate_minute_job(strategy, spec, calendar, bars, settings)
    if strategy.definition is not None and strategy.definition.cost_version != fees.version:
        raise DomainError('validation_failed', 'minute strategy cost version mismatch')
    day_indices = {day: index for index, day in enumerate(calendar.days)}
    position = None
    trades = []
    equity = peak = drawdown = Decimal('0')
    for index in range(1, len(bars)):
        now = bars[index].opened_at
        # Equality is intentional: completed-bar event precedes next-open event.
        # No current close, high, low or volume is available to the signal.
        history = bars[max(0, index - 21) : index]
        forced = _forced(settings, bars, days, index)
        closed = False
        if position is not None:
            age = _age(settings, day_indices, bars, days, position[0], index)
            if forced or age >= settings.maximum or age >= settings.minimum and exit_signal(strategy, history, now):
                trade = _trade(strategy, spec, fees, bars, position, index)
                trades.append(trade)
                equity += trade.gross - trade.costs
                peak = max(peak, equity)
                drawdown = max(drawdown, peak - equity)
                position, closed = None, True
        # Do not reverse/re-enter at the same event as a close. Day starts need
        # a completed bar from that day, so yesterday cannot cause overnight entry.
        if position is None and not closed and not forced and (not settings.intraday or days[index - 1] == days[index]):
            if entry_signal(strategy, history, now):
                sign = 1 if strategy.form.direction is Side.BUY else -1
                position = (index, spec.shift_ticks(bars[index].open, sign * fees.slippage_ticks))
    dataset = sha256(dumps((bars, settings)).encode()).hexdigest()
    base = research_fingerprint(strategy, spec, calendar, fees, dataset, source_profile)
    return MinuteResearchResult(
        strategy.strategy_id,
        strategy.version,
        dataset,
        'markauto-minute-training-1',
        'TRAINING',
        equity,
        sum((t.costs for t in trades), Decimal('0')),
        drawdown,
        tuple(trades),
        len(bars),
        sha256(('minute-research-v1:' + base).encode()).hexdigest(),
        source_profile.profile_id if source_profile else '',
        source_profile.source_digest if source_profile else '',
        settings,
        calendar.version,
        fees.version,
    )
