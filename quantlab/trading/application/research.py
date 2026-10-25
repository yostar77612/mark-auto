"""Deterministic training-only research with shared fees, calendar and policies."""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from .codec import dumps, register
from .state import StrategyRecord
from .provenance import ProducerProfile
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import InstrumentSpec, Side
from quantlab.trading.domain.strategy import CompletedBar, Rule, ensure_execution_after_signal, features_at
from quantlab.trading.domain.validation import DomainError


@dataclass(frozen=True)
class ResearchTrade:
    entry_index: int
    exit_index: int
    quantity: int
    entry: Decimal
    exit: Decimal
    gross: Decimal
    costs: Decimal


@dataclass(frozen=True)
class ResearchResult:
    strategy_id: str
    version: int
    dataset_id: str
    producer: str
    partition: str
    net_pnl: Decimal
    costs: Decimal
    drawdown: Decimal
    trades: tuple[ResearchTrade, ...]
    observations: int
    fingerprint: str
    producer_profile: str = ''
    source_digest: str = ''


register(ResearchTrade, ResearchResult)


def entry_signal(strategy: StrategyRecord, history: tuple[CompletedBar, ...], now) -> bool:
    features = features_at(history, now)
    values = dict(features)
    if strategy.definition is not None:
        required = {rule.field for rule in strategy.definition.entry}
        if not required.issubset(values):
            return False
        return all(rule.evaluate(features) for rule in strategy.definition.entry)
    if strategy.form.rule_kind == 'BUY_AND_HOLD':
        return Rule('close', 'GT', Decimal('0')).evaluate(features)
    if strategy.form.rule_kind == 'MA_CROSS':
        if 'sma5' not in values:
            return False
        return Rule('close', 'GT' if strategy.form.direction is Side.BUY else 'LT', values['sma5']).evaluate(features)
    if strategy.form.rule_kind == 'BREAKOUT':
        if len(history) < 6:
            return False
        threshold = max(b.close for b in history[-6:-1]) if strategy.form.direction is Side.BUY else min(b.close for b in history[-6:-1])
        return Rule('close', 'GT' if strategy.form.direction is Side.BUY else 'LT', threshold).evaluate(features)
    raise DomainError('validation_failed', 'unregistered deterministic rule')


def exit_signal(strategy: StrategyRecord, history: tuple[CompletedBar, ...], now) -> bool:
    if strategy.definition is None or not history:
        return False
    features = features_at(history, now)
    if not {r.field for r in strategy.definition.exit}.issubset(dict(features)):
        return False
    return all(rule.evaluate(features) for rule in strategy.definition.exit)


@decimal_operation
def research(
    strategy: StrategyRecord,
    spec: InstrumentSpec,
    calendar: TradingCalendar,
    bars: tuple[CompletedBar, ...],
    fees: FeeSchedule,
    *,
    source_profile: ProducerProfile | None = None,
) -> ResearchResult:
    if len(bars) < strategy.policy.max_days + 6 or len(bars) > len(calendar.days):
        raise DomainError('validation_failed', 'research coverage insufficient')
    position = None
    trades: list[ResearchTrade] = []
    equity, peak, drawdown = Decimal('0'), Decimal('0'), Decimal('0')
    quantity = spec.lot_size
    for index in range(1, len(bars)):
        bar = bars[index]
        history = bars[:index]
        now = bar.opened_at
        if position is not None:
            entry_index, entry_price = position
            age = calendar.age(history[entry_index].opened_at.date(), bar.opened_at.date())
            rule_exit = age >= strategy.policy.min_days and exit_signal(strategy, history, now)
            if rule_exit or age >= strategy.policy.max_days or index == len(bars) - 1 or spec.expiry is not None and bar.opened_at.date() >= spec.expiry:
                sign = 1 if strategy.form.direction is Side.BUY else -1
                exit_price = bar.open - spec.tick_size * sign
                gross = (exit_price - entry_price) * quantity * spec.multiplier * sign
                costs = fees.transaction(spec, strategy.form.direction, entry_price, quantity) + fees.transaction(
                    spec, Side.SELL if sign == 1 else Side.BUY, exit_price, quantity
                )
                trades.append(ResearchTrade(entry_index, index, quantity, entry_price, exit_price, gross, costs))
                equity += gross - costs
                peak = max(peak, equity)
                drawdown = max(drawdown, peak - equity)
                position = None
        if position is None and index + strategy.policy.max_days < len(bars) and entry_signal(strategy, history, now):
            ensure_execution_after_signal(history[-1], now)
            if spec.expiry is None or bar.opened_at.date() < spec.expiry:
                sign = 1 if strategy.form.direction is Side.BUY else -1
                position = (index, bar.open + spec.tick_size * sign)
                if strategy.policy.max_days == 0:
                    exit_price = bar.close - spec.tick_size * sign
                    gross = (exit_price - position[1]) * quantity * spec.multiplier * sign
                    costs = fees.transaction(spec, strategy.form.direction, position[1], quantity) + fees.transaction(
                        spec, Side.SELL if sign == 1 else Side.BUY, exit_price, quantity
                    )
                    trades.append(ResearchTrade(index, index, quantity, position[1], exit_price, gross, costs))
                    equity += gross - costs
                    peak = max(peak, equity)
                    drawdown = max(drawdown, peak - equity)
                    position = None
    dataset = sha256(dumps(bars).encode()).hexdigest()
    fingerprint = research_fingerprint(strategy, spec, calendar, fees, dataset, source_profile)
    return ResearchResult(
        strategy.strategy_id,
        strategy.version,
        dataset,
        'markauto-trading-v2-training-1',
        'TRAINING',
        equity,
        sum((t.costs for t in trades), Decimal('0')),
        drawdown,
        tuple(trades),
        len(bars),
        fingerprint,
        source_profile.profile_id if source_profile else '',
        source_profile.source_digest if source_profile else '',
    )


def research_fingerprint(
    strategy: StrategyRecord, spec: InstrumentSpec, calendar: TradingCalendar, fees: FeeSchedule, dataset: str, source_profile: ProducerProfile | None
) -> str:
    material = (strategy.form, strategy.definition, strategy.policy, spec, calendar, fees, dataset, source_profile)
    return sha256(dumps(material).encode()).hexdigest()
