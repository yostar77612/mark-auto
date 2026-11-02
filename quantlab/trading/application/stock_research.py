"""Additive official-stock training: adjusted signals, raw fills, no hidden entitlements.

Legacy daily research is deliberately not modified. This runner emits the same
ResearchResult/ResearchEvidence types, with an immutable, replayable sidecar.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Callable

from .codec import dumps, register
from .provenance import ProducerProfile
from .research import ResearchResult, ResearchTrade, entry_signal, exit_signal, research_fingerprint
from .state import StrategyRecord
from .stock_history import StockResearchInputs
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import HoldingKind, InstrumentSpec, Market, Side
from quantlab.trading.domain.stock_history import CashDividendAction, CorporateAction, DailyStockBar, price_series
from quantlab.trading.domain.strategy import CompletedBar, ResearchEvidence
from quantlab.trading.domain.validation import DomainError

PRODUCER = 'markauto-official-stock-training-1'
CASH_PRODUCER = 'markauto-official-stock-cash-training-1'
CASH_METHOD = 'gross-issuer-cash-accrual-v1'
MAX_BARS = 6000


@dataclass(frozen=True)
class StockTaxTreatment:
    stock_kind: str
    day_trade: bool = False

    def __post_init__(self):
        if self.stock_kind not in ('STOCK', 'ETF') or type(self.day_trade) is not bool:
            raise DomainError('validation_failed', 'explicit stock tax treatment required')

    def validate(self, strategy: StrategyRecord, fees: FeeSchedule) -> None:
        expected = Decimal('0.001') if self.stock_kind == 'ETF' else Decimal('0.0015') if self.day_trade else Decimal('0.003')
        if fees.sell_tax_rate != expected or self.day_trade and strategy.policy.kind is not HoldingKind.INTRADAY:
            raise DomainError('validation_failed', 'cost treatment and holding policy disagree')


@dataclass(frozen=True)
class StockResearchArtifact:
    evidence: ResearchEvidence
    result: ResearchResult
    fees: FeeSchedule
    treatment: StockTaxTreatment
    metadata: tuple[tuple[str, str], ...]
    events: tuple[CorporateAction, ...]
    strategy: StrategyRecord
    instrument: InstrumentSpec
    calendar: TradingCalendar
    profile: ProducerProfile


@dataclass(frozen=True)
class CashEntitlement:
    event_index: int
    trade_index: int
    quantity: int
    gross_amount: Decimal


@dataclass(frozen=True)
class CashEntitlementSummary:
    """Separate gross accrual; payable is scheduled, never verified bank cash."""

    as_of: date
    entitlements: tuple[CashEntitlement, ...]
    gross_entitlement: Decimal
    gross_payable: Decimal
    gross_receivable: Decimal
    raw_net_plus_entitlement: Decimal


@dataclass(frozen=True)
class CashStockResearchArtifact(StockResearchArtifact):
    cash_accounting: CashEntitlementSummary


def artifact_material(result, metadata, events, fees, treatment, strategy, instrument, calendar, profile, *, cash_accounting=None):
    original = result, metadata, events, fees, treatment, strategy, instrument, calendar, profile
    return original if cash_accounting is None else (*original, cash_accounting)


@decimal_operation
def cash_entitlements(result: ResearchResult, inputs: StockResearchInputs, checkpoint: Callable[[], None]) -> CashEntitlementSummary:
    """Attribute issuer gross cash without changing raw trades or sizing cash."""
    bars, events = inputs.batch.bars, inputs.batch.events
    as_of = bars[-1].trade_date
    rows = []
    payable = receivable = Decimal('0')
    for event_index, event in enumerate(events):
        checkpoint()
        if type(event) is not CashDividendAction:
            continue
        for trade_index, trade in enumerate(result.trades):
            if bars[trade.entry_index].trade_date < event.ex_date <= bars[trade.exit_index].trade_date:
                amount = event.cash_per_share * trade.quantity
                rows.append(CashEntitlement(event_index, trade_index, trade.quantity, amount))
                if event.payment_date <= as_of:
                    payable += amount
                else:
                    receivable += amount
    gross = payable + receivable
    return CashEntitlementSummary(as_of, tuple(rows), gross, payable, receivable, result.net_pnl + gross)


def validate_request(strategy: StrategyRecord, spec: InstrumentSpec, treatment: StockTaxTreatment, fees: FeeSchedule, partition: str) -> None:
    if (
        not isinstance(strategy, StrategyRecord)
        or not isinstance(spec, InstrumentSpec)
        or not isinstance(fees, FeeSchedule)
        or not isinstance(treatment, StockTaxTreatment)
    ):
        raise DomainError('validation_failed', 'typed stock research request required')
    if partition != 'TRAINING' or spec.market is not Market.STOCK or strategy.form.market is not Market.STOCK:
        raise DomainError('validation_failed', 'official-stock training only')
    if strategy.state not in ('RULE_VALID', 'RESEARCHED') or strategy.form.instrument_id != spec.instrument_id:
        raise DomainError('validation_failed', 'validated stock strategy identity required')
    if (strategy.policy.kind, strategy.policy.min_days, strategy.policy.max_days) != (
        strategy.form.holding_kind,
        strategy.form.min_days,
        strategy.form.max_days,
    ):
        raise DomainError('validation_failed', 'strategy holding policy mismatch')
    if strategy.definition is not None and (strategy.definition.bar_interval != '1d' or strategy.definition.cost_version != fees.version):
        raise DomainError('validation_failed', 'daily strategy/cost version mismatch')
    if strategy.parameters is not None:
        raise DomainError('validation_failed', 'typed strategy execution semantics are not supported by the legacy daily stock runner')
    treatment.validate(strategy, fees)


def _completed(bar: DailyStockBar, sessions: dict[date, TradingSession]) -> CompletedBar:
    session = sessions[bar.trade_date]
    return CompletedBar(session.opens_at, session.closes_at, session.closes_at, bar.open, bar.close, bar.volume)


@decimal_operation
def backtest_stock(
    strategy: StrategyRecord,
    spec: InstrumentSpec,
    calendar: TradingCalendar,
    inputs: StockResearchInputs,
    *,
    profile: ProducerProfile,
    checkpoint: Callable[[], None],
) -> ResearchResult:
    bars, events, fees = inputs.batch.bars, inputs.batch.events, inputs.fees
    if not strategy.policy.max_days + 6 <= len(bars) <= MAX_BARS or len(events) > MAX_BARS:
        raise DomainError('official_stock_coverage_missing', 'bounded complete stock observations required')
    if len({event.ex_date for event in events}) != len(events):
        raise DomainError('validation_failed', 'one combined official event per date')
    sessions = {session.trade_date: session for session in calendar.sessions if session.kind == 'DAY'}
    if any(day not in sessions for day in (bar.trade_date for bar in bars)):
        raise DomainError('calendar_missing', 'stock day session required')
    trades, position = [], None
    equity = peak = drawdown = Decimal('0')
    sign = 1 if strategy.form.direction is Side.BUY else -1
    quantity = spec.lot_size
    event_days = {event.ex_date for event in events if type(event) is not CashDividendAction or sign != 1}
    for index in range(1, len(bars)):
        checkpoint()
        bar = bars[index]
        # Only the last 20 observations are needed by the existing declarative
        # rules. No bar or action after the last completed date enters a signal.
        window = bars[max(0, index - 20) : index]
        known_events = tuple(event for event in events if window[0].trade_date < event.ex_date <= window[-1].trade_date)
        adjusted = price_series(window, known_events)
        history = tuple(_completed(value, sessions) for value in adjusted.bars)
        now = sessions[bar.trade_date].opens_at
        if history[-1].available_at >= now:
            raise DomainError('validation_failed', 'execution must follow the completed signal')
        exit_price = None
        if position is not None:
            entry_index, entry_price = position
            # Only explicit long cash-only facts have a separate accrual model.
            # Price ratios, share/mixed events and short obligations remain unknown.
            if any(bars[entry_index].trade_date < day <= bar.trade_date for day in event_days):
                raise DomainError('stock_entitlement_unknown', 'held stock crosses an action without economic entitlement facts')
            age = index - entry_index  # coverage admission proves one bar per explicit session
            if (age >= strategy.policy.min_days and exit_signal(strategy, history, now)) or age >= strategy.policy.max_days or index == len(bars) - 1:
                exit_price = spec.shift_ticks(bar.open, -sign * fees.slippage_ticks)
        if position is None and index + strategy.policy.max_days < len(bars) and entry_signal(strategy, history, now):
            raw_entry = spec.shift_ticks(bar.open, sign * fees.slippage_ticks)
            if fees.entry_cash(spec, raw_entry, quantity, strategy.form.direction) > strategy.form.allocation:
                continue
            position = index, raw_entry
            if strategy.policy.kind is HoldingKind.INTRADAY:
                exit_price = spec.shift_ticks(bar.close, -sign * fees.slippage_ticks)
        if exit_price is not None:
            entry_index, entry_price = position
            gross = (exit_price - entry_price) * quantity * spec.multiplier * sign
            costs = fees.transaction(spec, strategy.form.direction, entry_price, quantity) + fees.transaction(
                spec, Side.SELL if sign == 1 else Side.BUY, exit_price, quantity
            )
            trades.append(ResearchTrade(entry_index, index, quantity, entry_price, exit_price, gross, costs))
            equity += gross - costs
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            position = None
    checkpoint()
    dataset = sha256(dumps(inputs.evidence()).encode()).hexdigest()
    fingerprint = research_fingerprint(strategy, spec, calendar, fees, dataset, profile)
    return ResearchResult(
        strategy.strategy_id,
        strategy.version,
        dataset,
        CASH_PRODUCER if any(type(event) is CashDividendAction for event in events) else PRODUCER,
        'TRAINING',
        equity,
        sum((trade.costs for trade in trades), Decimal('0')),
        drawdown,
        tuple(trades),
        len(bars),
        fingerprint,
        profile.profile_id,
        profile.source_digest,
    )


register(StockTaxTreatment, StockResearchArtifact, CorporateAction, DailyStockBar)
register(CashDividendAction, CashEntitlement, CashEntitlementSummary, CashStockResearchArtifact)
