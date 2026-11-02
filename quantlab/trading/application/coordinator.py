"""One clock-driven decision cycle shared by local and controlled broker engines.

Only normalized reports create fills. This coordinator never advances a clock,
inventories broker holdings as managed lots, or simulates an exchange response.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from .events import poll_events, reconcile, validate_observation
from .research import entry_signal, exit_signal
from .sessions import assert_daily_baseline, resolve_session, synchronize_session
from .state import ACTIVE
from quantlab.trading.domain.models import HoldingKind, OrderPlan, Side
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .daily_state import DailyIntent
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


def _exit_decision(
    engine: 'TradingEngine',
    lot: 'PositionLot',
    history: dict[str, tuple['CompletedBar', ...]],
    *,
    intraday_timer: bool = True,
    evaluate_signal: bool = True,
    as_of: datetime | None = None,
    decision_key: str = '',
) -> None:
    spec = engine.catalog.resolve(lot.instrument_id)
    quote = engine.quotes.get(lot.instrument_id)
    fresh = quote is not None and 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
    entry = next(o for o in engine.state.orders if o.order_id == lot.lot_id)
    stop = dict(engine.state.protection_stops).get(lot.lot_id, entry.plan.stop_price)
    protective = fresh and (quote.last <= stop if lot.direction is Side.BUY else quote.last >= stop)
    expiry = spec.expiry is not None and engine.state.trading_day >= engine.calendar.advance(spec.expiry, 0)
    intraday = intraday_timer and lot.policy.kind is HoldingKind.INTRADAY and _intraday_due(engine, lot)
    age = engine.calendar.age(lot.holding_origin, engine.state.trading_day)
    deadline = lot.policy.kind is not HoldingKind.INTRADAY and age >= lot.policy.max_days
    record = engine.strategy(f'{lot.strategy_id}:{lot.strategy_version}')
    decision_at = as_of or engine.clock.now()
    bars = (
        tuple(b for b in history.get(spec.instrument_id, ()) if b.available_at <= decision_at)
        if as_of is not None
        else tuple(b for b in history.get(spec.instrument_id, ()) if b.available_at < decision_at)
    )
    normal = evaluate_signal and age >= lot.policy.min_days and bool(bars) and exit_signal(record, bars, decision_at)
    if protective or expiry or intraday or deadline or normal:
        if decision_key:
            engine.exit_lot(lot.lot_id, protective=protective or expiry or intraday, key=decision_key)
        else:
            engine.exit_lot(lot.lot_id, protective=protective or expiry or intraday)


@decimal_operation
def _entry_decision(
    engine: 'TradingEngine',
    record: 'StrategyRecord',
    history: dict[str, tuple['CompletedBar', ...]],
    *,
    decision_key: str = '',
    as_of: datetime | None = None,
    daily_signal: 'DailyIntent | None' = None,
) -> None:
    if record.state != 'ACTIVE' or any(p.quantity and p.strategy_id == record.strategy_id for p in engine.state.positions):
        return
    key = decision_key or f'{record.strategy_id}:{record.version}:{engine.state.trading_day}'
    # A terminal rejection/cancellation is still a decision for this key. A new
    # tick must not silently retry it with a different request hash.
    if any(o.key == key or (o.status in ACTIVE and not o.plan.reduce_only and o.plan.strategy_id == record.strategy_id) for o in engine.state.orders):
        return
    spec = engine.catalog.resolve(record.form.instrument_id)
    if record.parameters is not None and record.parameters.instrument_rule == 'TMF_NEAR':
        from quantlab.trading.domain.strategy import resolve_tmf_near

        spec = resolve_tmf_near(engine.catalog.instruments, engine.calendar, engine.state.trading_day)
    decision_at = as_of or engine.clock.now()
    bars = (
        tuple(b for b in history.get(spec.instrument_id, ()) if b.available_at <= decision_at)
        if as_of is not None
        else tuple(b for b in history.get(spec.instrument_id, ()) if b.available_at < decision_at)
    )
    if daily_signal is None and (not bars or not entry_signal(record, bars, decision_at)):
        return
    quote = engine.quotes.get(spec.instrument_id)
    if quote is None:
        raise DomainError('stale_quote', 'no verified decision quote')
    price = quote.ask if record.form.direction is Side.BUY else quote.bid
    sign = 1 if record.form.direction is Side.BUY else -1
    quantity, stop = spec.lot_size, spec.shift_ticks(price, -10 * sign)
    if record.parameters is not None:
        from quantlab.trading.domain.strategy import strategy_quantity

        spec = engine._strategy_spec(spec, record)
        quantity = strategy_quantity(spec, record.parameters, price, record.form.allocation, engine.fees, record.form.direction).quantity
        if not quantity:
            raise DomainError('strategy_size_insufficient')
        stop = spec.round_price(price * (1 - record.parameters.stop_fraction * sign), up=sign < 0)
        engine.update_strategy(replace(record, recent_signal='ENTRY'), 'strategy_signal_evaluated')
    now = engine.clock.now()
    plan = OrderPlan(
        f'decision:{record.strategy_id}:{engine.state.trading_day}',
        record.form.account_ref,
        engine.configuration.environment,
        spec.instrument_id,
        record.strategy_id,
        record.version,
        record.form.direction,
        quantity,
        spec.unit,
        price,
        stop,
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


def run_readonly_cycle(engine: 'TradingEngine') -> None:
    """Observe outside the book lock, then reconcile a still-current book.

    SDK queries cannot hold the application lock while STOP or shutdown waits.
    If another command changes the book during a query, discard its batch and
    query again on the next cycle. This path never submits or cancels orders.
    """
    # Keep the common valuation authority independent of coordinator imports.
    from .workflows import observe_risk

    with engine.lock:
        if not engine.configuration.read_only or engine.state.engine_closed:
            raise DomainError('capability_missing', 'an open read-only engine is required')
        version = engine.state.version
        gateways = tuple(engine.gateways.items())
    try:
        observations = {account: gateway.refresh(account) for account, gateway in gateways}
    except Exception:
        with engine.lock:
            if not engine.state.engine_closed:
                _attention(engine, 'reconciliation_required')
                if engine.state.reconciled:
                    engine._persist('readonly_query_failed', replace(engine.state, reconciled=False, stopped=True))
        return
    with engine.lock:
        if engine.state.version != version or engine.state.engine_closed or tuple(engine.gateways.items()) != gateways:
            return
        try:
            # Time and verified session evidence can expire without a new DTO,
            # quote or book command. Never let a cache hit renew that evidence.
            synchronize_session(engine)
            for account, remote in observations.items():
                validate_observation(engine, account, remote)
            observation = tuple(observations.items())
            if engine.confirmed_observations == (observation, engine.state.version, engine.quote_count):
                return
            reconcile(engine, snapshots=observations)
        except DomainError as exc:
            if engine.storage_failed:
                raise
            _attention(engine, exc.code)
            if engine.state.reconciled:
                engine._persist('confirmed_observations_rejected', replace(engine.state, reconciled=False, stopped=True))
            return
        if engine.state.reconciled and not engine.state.daily_baseline_required:
            _attempt(engine, lambda: observe_risk(engine))
        engine.confirmed_observations = (observation, engine.state.version, engine.quote_count)
