"""One clock-driven decision cycle shared by local and controlled broker engines.

Only normalized reports create fills. This coordinator never advances a clock,
inventories broker holdings as managed lots, or simulates an exchange response.
"""

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Callable

from .events import poll_events
from .research import entry_signal, exit_signal
from .sessions import assert_daily_baseline, resolve_session, synchronize_session
from .state import ACTIVE
from quantlab.trading.domain.models import HoldingKind, OrderPlan, Side
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine
    from .state import StrategyRecord
    from quantlab.trading.domain.models import PositionLot
    from quantlab.trading.domain.strategy import CompletedBar

CLOSE_BUFFER = timedelta(minutes=5)


def _attention(engine: 'TradingEngine', code: str) -> None:
    if engine.storage_failed:
        raise DomainError('journal_failed', 'decision journal is unavailable')
    if code not in engine.state.issues or not engine.state.stopped:
        engine._persist('decision_requires_attention', replace(engine.state, stopped=True, issues=tuple(sorted(set((*engine.state.issues, code))))))


def _attempt(engine: 'TradingEngine', operation: Callable[[], object]) -> None:
    try:
        operation()
    except DomainError as exc:
        if engine.storage_failed:
            raise
        _attention(engine, exc.code)


def _intraday_due(engine: 'TradingEngine', lot: 'PositionLot') -> bool:
    session = engine.calendar.day_session(lot.holding_origin)
    return engine.clock.now() >= session.closes_at - CLOSE_BUFFER


def _exit_decision(engine: 'TradingEngine', lot: 'PositionLot', history: dict[str, tuple['CompletedBar', ...]]) -> None:
    spec = engine.catalog.resolve(lot.instrument_id)
    quote = engine.quotes.get(lot.instrument_id)
    fresh = quote is not None and 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
    entry = next(o for o in engine.state.orders if o.order_id == lot.lot_id)
    stop = dict(engine.state.protection_stops).get(lot.lot_id, entry.plan.stop_price)
    protective = fresh and (quote.last <= stop if lot.direction is Side.BUY else quote.last >= stop)
    expiry = spec.expiry is not None and engine.state.trading_day >= engine.calendar.advance(spec.expiry, 0)
    intraday = lot.policy.kind is HoldingKind.INTRADAY and _intraday_due(engine, lot)
    age = engine.calendar.age(lot.holding_origin, engine.state.trading_day)
    deadline = lot.policy.kind is not HoldingKind.INTRADAY and age >= lot.policy.max_days
    record = engine.strategy(f'{lot.strategy_id}:{lot.strategy_version}')
    bars = tuple(b for b in history.get(spec.instrument_id, ()) if b.available_at < engine.clock.now())
    normal = age >= lot.policy.min_days and bool(bars) and exit_signal(record, bars, engine.clock.now())
    if protective or expiry or intraday or deadline or normal:
        engine.exit_lot(lot.lot_id, protective=protective or expiry or intraday)


def _entry_decision(engine: 'TradingEngine', record: 'StrategyRecord', history: dict[str, tuple['CompletedBar', ...]]) -> None:
    if record.state != 'ACTIVE' or any(p.quantity and p.strategy_id == record.strategy_id for p in engine.state.positions):
        return
    key = f'{record.strategy_id}:{record.version}:{engine.state.trading_day}'
    # A terminal rejection/cancellation is still a decision for this key. A new
    # tick must not silently retry it with a different request hash.
    if any(o.key == key or (o.status in ACTIVE and not o.plan.reduce_only and o.plan.strategy_id == record.strategy_id) for o in engine.state.orders):
        return
    spec = engine.catalog.resolve(record.form.instrument_id)
    bars = tuple(b for b in history.get(spec.instrument_id, ()) if b.available_at < engine.clock.now())
    if not bars or not entry_signal(record, bars, engine.clock.now()):
        return
    quote = engine.quotes.get(spec.instrument_id)
    if quote is None:
        raise DomainError('stale_quote', 'no verified decision quote')
    price = quote.ask if record.form.direction is Side.BUY else quote.bid
    sign = 1 if record.form.direction is Side.BUY else -1
    now = engine.clock.now()
    plan = OrderPlan(
        f'decision:{record.strategy_id}:{engine.state.trading_day}',
        record.form.account_ref,
        engine.configuration.environment,
        spec.instrument_id,
        record.strategy_id,
        record.version,
        record.form.direction,
        spec.lot_size,
        spec.unit,
        price,
        price - spec.tick_size * 10 * sign,
        False,
        now,
        now + timedelta(seconds=30),
        engine.state.version,
    )
    engine.submit(plan, record.policy, key)


def run_cycle(engine: 'TradingEngine', history: dict[str, tuple['CompletedBar', ...]], *, allow_entries: bool = True) -> None:
    """Poll real reports, protect known holdings, then consider eligible new risk."""
    from .lifecycle import run_lifecycle
    from .workflows import mark_risk

    with engine.lock:
        engine.assert_execution_allowed()
        if engine.state.engine_closed:
            raise DomainError('capability_missing', 'engine is closed')
        _attempt(engine, lambda: synchronize_session(engine))
        _attempt(engine, lambda: poll_events(engine))
        # Lifecycle and each lot remain independent: an unrelated unknown report
        # cannot prevent a legal reduction of another confirmed managed scope.
        _attempt(engine, lambda: run_lifecycle(engine))
        for lot in tuple(engine.state.positions):
            if lot.quantity and lot.origin == 'MANAGED':
                _attempt(engine, lambda lot=lot: _exit_decision(engine, lot, history))
        if not engine.state.daily_baseline_required:
            _attempt(engine, lambda: mark_risk(engine))
        if not allow_entries or engine.state.stopped or not engine.state.reconciled or engine.state.issues or engine.state.reconciliation:
            return
        if any(o.status.value in ('SUBMITTING', 'UNKNOWN', 'CANCEL_PENDING') for o in engine.state.orders):
            return
        try:
            assert_daily_baseline(engine)
            session = resolve_session(engine.calendar, engine.clock.now(), night_enabled=engine.state.settings.night_enabled)
        except DomainError as exc:
            _attention(engine, exc.code)
            return
        if not session.active or engine.clock.now() >= session.closes_at - CLOSE_BUFFER:
            return
        for record in tuple(engine.state.strategies):
            if engine.state.stopped:
                break
            _attempt(engine, lambda record=record: _entry_decision(engine, record, history))
