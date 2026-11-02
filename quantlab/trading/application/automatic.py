"""Completed-bar execution and durable protective exits using trusted cached facts."""

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from . import automatic_state as claims
from .account_risk import assert_account_resume, observe_account_limits
from .automatic_capacity import assert_automatic_observation, automatic_daily_pnl, shared_sim_allocations
from .coordinator import _entry_decision, _exit_decision
from .execution import ExecutionService
from .preflight import assert_preflight
from .sessions import resolve_session
from .state import ACTIVE
from quantlab.trading.domain.auto_cycle import EvaluationCursor, complete_buckets, force_exit_due, force_exit_window, position_overdue
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar, calendar_for_instrument
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderStatus
from quantlab.trading.domain.strategy import CompletedBar, is_tmf, resolve_tmf_near
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine

UNCERTAIN = frozenset((OrderStatus.SUBMITTING, OrderStatus.UNKNOWN, OrderStatus.CANCEL_PENDING))


def _assert_simulation(engine: 'TradingEngine') -> None:
    engine.assert_execution_allowed()
    if engine.configuration.environment is not Environment.BROKER_SIMULATION:
        raise DomainError('capability_missing', 'completed-bar automatic execution requires broker simulation')


def _store(engine, kind, automatic) -> None:
    if automatic is not None and automatic != engine.state.automatic:
        engine._persist(kind, replace(engine.state, automatic=automatic))


def pause_automatic(engine: 'TradingEngine', reason: str) -> None:
    """A separate automatic latch; a manual resume cannot change this state."""
    with engine.lock:
        _assert_simulation(engine)
        automatic = claims.pause(engine.state.automatic, reason)
        if automatic != engine.state.automatic or not engine.state.stopped:
            engine._persist('automatic_paused', replace(engine.state, stopped=True, automatic=automatic))


def _accounts(engine) -> tuple[str, ...]:
    return tuple(sorted({row.form.account_ref for row in engine.state.strategies if row.parameters is not None}))


def _healthy(engine) -> None:
    # The native manual ledger has dated per-account baselines. Its legacy
    # aggregate marker is preserved, never cleared or replaced with invented PnL.
    issues = tuple(code for code in engine.state.issues if code != 'daily_baseline_required')
    if engine.storage_failed or engine.state.engine_closed or not engine.state.reconciled or issues or engine.state.reconciliation:
        raise DomainError('reconciliation_required', 'automatic execution requires a healthy reconciled ledger')
    if engine.state.trading_day in engine.state.daily_locks:
        raise DomainError('risk_rejected')
    if any(job.status != 'APPLIED' for job in engine.state.corporate_actions) or any(job.status == 'FROZEN' for job in engine.state.rolls):
        raise DomainError('reconciliation_required', 'lifecycle work remains unresolved')


def _entry_proofs(engine) -> None:
    supported = tuple(spec for spec in engine.catalog.instruments if spec.market is Market.STOCK or is_tmf(spec))
    context = resolve_session(automatic_day_calendar(engine.calendar, supported), engine.clock.now())
    if context.trade_date != engine.state.trading_day:
        raise DomainError('account_daily_baseline_required', 'ledger day must be synchronized before accepting its closing evidence')
    allocations = shared_sim_allocations(engine)
    if not set(_accounts(engine)) <= {row.account_ref for row in allocations}:
        raise DomainError('manual_book_not_enabled', 'every automatic account needs a confirmed virtual book')
    automatic_daily_pnl(engine)  # Every shared book needs its own current dated baseline.
    validator = getattr(engine, 'automatic_entry_validator', None)
    if not callable(validator):
        raise DomainError('capability_missing', 'current server-side automatic entry proofs are required')
    for reference in _accounts(engine):
        validator(reference)
        assert_automatic_observation(engine, reference)
        assert_account_resume(engine, reference)
        assert_preflight(engine, reference)
    _healthy(engine)


def _assert_entry_window(engine) -> None:
    scopes = {
        (row.form.instrument_id, row.policy, engine.state.trading_day)
        for row in engine.state.strategies
        if row.parameters is not None and row.state == 'ACTIVE' and row.policy.kind is HoldingKind.INTRADAY
    }
    scopes.update(
        (lot.instrument_id, lot.policy, lot.holding_origin)
        for lot in engine.state.positions
        if lot.quantity and lot.origin == 'MANAGED' and lot.policy.kind is HoldingKind.INTRADAY
    )
    for instrument_id, policy, day in scopes:
        session = calendar_for_instrument(engine.calendar, engine.catalog.resolve(instrument_id)).day_session(day)
        window = force_exit_window(policy.kind, engine.catalog.resolve(instrument_id).market, session)
        if window is not None and engine.clock.now() >= window.due_at:
            raise DomainError('intraday_force_exit')


def resume_automatic(engine: 'TradingEngine') -> None:
    """Explicit user action after current reconciliation, preflight and loss checks."""
    with engine.lock:
        _assert_simulation(engine)
        _entry_proofs(engine)
        automatic = claims.resume(engine.state.automatic, engine.clock.now(), user_confirmed=True, reconciled=True, preflight_passed=True)
        if automatic is None:
            raise DomainError('reconciliation_required', 'an automatic claim still has an unresolved outcome')
        engine.fence()
        engine._persist('automatic_resumed_explicitly', replace(engine.state, stopped=False, automatic=automatic))


def _decision_key(cursor: EvaluationCursor) -> str:
    return f'auto:{cursor.strategy_id}:{cursor.version}:{cursor.instrument_id}:{cursor.interval}:{cursor.bar_end.isoformat()}'


def _cursor_orders(engine, cursor):
    key = _decision_key(cursor)
    return tuple(order for order in engine.state.orders if order.key == key or order.key.startswith(key + ':exit:'))


def _evaluation_result(engine, cursor, previous_order_id=''):
    orders = _cursor_orders(engine, cursor)
    if not orders:
        return None, previous_order_id
    unknown = next((order for order in orders if order.status is OrderStatus.UNKNOWN), None)
    selected = next((order for order in orders if order.order_id == previous_order_id), unknown or orders[0])
    status = next(
        (status for status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING) if any(order.status is status for order in orders)),
        selected.status,
    )
    return status, selected.order_id


def _sync_results(engine, *, observed: bool = False) -> None:
    for row in tuple(engine.state.automatic.evaluations):
        status, order_id = _evaluation_result(engine, row.cursor, row.order_id)
        if status is OrderStatus.UNKNOWN:
            updated = replace(row, order_result=status, order_id=row.order_id or order_id)
            automatic = claims.pause(
                replace(engine.state.automatic, evaluations=tuple(updated if old.cursor == row.cursor else old for old in engine.state.automatic.evaluations)),
                'order_result_unknown',
            )
            if automatic != engine.state.automatic or not engine.state.stopped:
                engine._persist('automatic_evaluation_unknown', replace(engine.state, stopped=True, automatic=automatic))
            continue
        if status is None or status in UNCERTAIN:
            continue
        if row.phase == 'CLAIMED' or observed:
            _store(
                engine,
                'automatic_evaluation_observed',
                claims.complete_evaluation(
                    engine.state.automatic,
                    row.cursor,
                    status,
                    order_id=order_id,
                    observed=observed,
                ),
            )
    for row in tuple(engine.state.automatic.forced_attempts):
        order = next((order for order in engine.state.orders if order.key == row.key), None)
        if order is None or order.status == row.status:
            continue
        # UNKNOWN is resolved only by an explicit reconcile action. A canceled
        # request must have reached the durable local report ledger first.
        if row.status is OrderStatus.UNKNOWN and not observed:
            continue
        _store(
            engine,
            'automatic_force_observed',
            claims.transition_force_attempt(
                engine.state.automatic,
                row.lot_id,
                row.attempt,
                order.status,
                order_id=order.order_id,
                observed=observed or order.status is OrderStatus.CANCELED,
            ),
        )


def reconcile_automatic(engine: 'TradingEngine') -> None:
    """Use the runtime worker's accepted cache; reconciliation never resumes trading."""
    with engine.lock:
        _assert_simulation(engine)
        if engine.storage_failed or engine.state.engine_closed:
            raise DomainError('capability_missing')
        for reference in _accounts(engine):
            assert_automatic_observation(engine, reference)
        if any(not row.outcome_known for row in engine.state.manual_requests):
            raise DomainError('reconciliation_required', 'a manual operation still has an unresolved outcome')
        force_keys = {row.key for row in engine.state.automatic.forced_attempts}
        owned_result = any(_cursor_orders(engine, row.cursor) for row in engine.state.automatic.evaluations) or any(
            row.key in force_keys for row in engine.state.orders
        )
        _sync_results(engine, observed=True)
        unresolved = any(row.phase != 'COMPLETED' or row.order_result in UNCERTAIN for row in engine.state.automatic.evaluations)
        unresolved = unresolved or any(row.status in UNCERTAIN for row in engine.state.automatic.forced_attempts)
        if owned_result and not unresolved and 'outcome_unknown' in engine.state.issues:
            engine._persist(
                'automatic_outcome_confirmed', replace(engine.state, issues=tuple(code for code in engine.state.issues if code != 'outcome_unknown'))
            )
        _healthy(engine)
        pause_automatic(engine, 'reconciled_waiting_resume')


def _history(engine, instrument_id, interval, buckets=()) -> dict[str, tuple[CompletedBar, ...]]:
    duration = {'1m': timedelta(minutes=1), '5m': timedelta(minutes=5)}.get(interval)
    historical = tuple(
        bar
        for bar in engine.history.get(instrument_id, ())
        if (bar.ended_at - bar.opened_at == duration if duration else bar.ended_at - bar.opened_at > timedelta(minutes=5))
    )
    converted = tuple(CompletedBar(bar.start, bar.end, bar.end, bar.open, bar.close, bar.volume) for bar in buckets)
    by_end = {bar.ended_at: bar for bar in (*historical, *converted)}
    return {instrument_id: tuple(by_end[end] for end in sorted(by_end))}


def on_completed_bars(engine: 'TradingEngine', bars: tuple[LiveBar, ...]) -> None:
    """Claim once before evaluating each finalized bucket after explicit resume."""
    with engine.lock:
        _assert_simulation(engine)
        cache = getattr(engine, 'automatic_minute_bars', {})
        for instrument_id in {bar.instrument_id for bar in bars}:
            # Retain conflicting final deliveries: complete_buckets excludes
            # that minute, rather than silently accepting the last correction.
            current = tuple(bar for bar in cache.get(instrument_id, ()) if bar.trade_date == engine.state.trading_day)
            incoming = tuple(
                bar for bar in bars if bar.instrument_id == instrument_id and bar.trade_date == engine.state.trading_day and bar.final and not bar.incomplete
            )
            cache[instrument_id] = tuple(dict.fromkeys((*current, *incoming)))
        engine.automatic_minute_bars = cache
        if engine.state.automatic.auto_paused:
            return
        try:
            _entry_proofs(engine)
            _assert_entry_window(engine)
            if engine.state.stopped:
                raise DomainError('automatic_paused')
        except DomainError as error:
            pause_automatic(engine, error.code)
            return
        for record in tuple(engine.state.strategies):
            owned = tuple(
                lot
                for lot in engine.state.positions
                if lot.quantity and lot.origin == 'MANAGED' and (lot.strategy_id, lot.strategy_version) == (record.strategy_id, record.version)
            )
            if record.parameters is None or (record.state != 'ACTIVE' and not owned):
                continue
            entry_id = record.form.instrument_id
            if record.state == 'ACTIVE' and record.parameters.instrument_rule == 'TMF_NEAR':
                entry_id = resolve_tmf_near(engine.catalog.instruments, engine.calendar, engine.state.trading_day).instrument_id
            instruments = {lot.instrument_id for lot in owned} | ({entry_id} if record.state == 'ACTIVE' else set())
            for instrument_id in sorted(instruments & {bar.instrument_id for bar in bars}):
                spec = engine.catalog.resolve(instrument_id)
                session = calendar_for_instrument(engine.calendar, spec).day_session(engine.state.trading_day)
                interval = record.parameters.bar_interval
                buckets = complete_buckets(cache.get(instrument_id, ()), interval, session, engine.clock.now())
                history = _history(engine, instrument_id, interval, buckets)
                for bar in buckets:
                    cursor = EvaluationCursor(record.strategy_id, record.version, instrument_id, interval, bar.end)
                    automatic = claims.claim_cursor(engine.state.automatic, cursor, engine.clock.now(), bar.end + (bar.end - bar.start))
                    if automatic is None:
                        continue
                    _store(engine, 'automatic_evaluation_claimed', automatic)
                    key, code = _decision_key(cursor), ''
                    try:
                        for lot in owned:
                            if lot.instrument_id == instrument_id:
                                _exit_decision(
                                    engine, lot, history, intraday_timer=False, evaluate_signal=True, as_of=bar.end, decision_key=key + ':exit:' + lot.lot_id
                                )
                        if record.state == 'ACTIVE' and instrument_id == entry_id:
                            _entry_decision(engine, record, history, decision_key=key, as_of=bar.end)
                    except DomainError as error:
                        if engine.storage_failed:
                            raise
                        code = error.code
                    result, order_id = _evaluation_result(engine, cursor)
                    result = OrderStatus.UNKNOWN if result is None and code == 'outcome_unknown' else result
                    _store(
                        engine,
                        'automatic_evaluation_completed',
                        claims.complete_evaluation(
                            engine.state.automatic,
                            cursor,
                            result,
                            order_id=order_id,
                            code=code,
                        ),
                    )
                    if result in UNCERTAIN or code:
                        pause_automatic(engine, code or 'order_result_unknown')
                        return


def _cancel_exit(engine, order) -> None:
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
        return
    guard = getattr(engine, 'automatic_submission_guard', None)
    if not callable(guard):
        raise DomainError('capability_missing', 'current owner execution guard is required')
    with guard(order.plan.account_ref, reduce_only=True):
        service = ExecutionService(engine.gateways[order.plan.account_ref], engine._persist, engine.fence, engine.clock.now)
        service.cancel(engine.state, order.order_id)


def _force_lot(engine, lot, window) -> None:
    now = engine.clock.now()
    pause_automatic(engine, 'intraday_force_exit')
    if position_overdue(window, now, lot.quantity):
        pause_automatic(engine, 'automatic_overdue_position')
        return
    if not force_exit_due(window, now):
        return
    previous = next((row for row in engine.state.automatic.forced_attempts if row.lot_id == lot.lot_id), None)
    pending = tuple(order for order in engine.state.orders if order.plan.exit_lot_id == lot.lot_id and order.status in ACTIVE)
    if pending:
        if any(order.status in UNCERTAIN for order in pending):
            if any(order.status is OrderStatus.UNKNOWN for order in pending):
                pause_automatic(engine, 'order_result_unknown')
            return
        if previous is not None and not force_exit_due(window, now, previous.attempted_at):
            return
        for order in pending:
            _cancel_exit(engine, order)
        _sync_results(engine)
        return  # A cancel receipt is not terminal cancellation evidence.
    if previous is not None and 'order_result_unknown' in engine.state.automatic.reasons:
        return
    automatic = claims.claim_force_attempt(engine.state.automatic, lot.lot_id, window, now)
    if automatic is None:
        return
    _store(engine, 'automatic_force_claimed', automatic)
    attempt = next(row for row in automatic.forced_attempts if row.lot_id == lot.lot_id)
    code = ''
    try:
        engine.exit_lot(lot.lot_id, protective=True, key=attempt.key)
    except DomainError as error:
        if engine.storage_failed:
            raise
        code = error.code
    order = next((order for order in engine.state.orders if order.key == attempt.key), None)
    status = order.status if order is not None else OrderStatus.UNKNOWN if code == 'outcome_unknown' else OrderStatus.REJECTED
    _store(
        engine,
        'automatic_force_result',
        claims.transition_force_attempt(
            engine.state.automatic,
            lot.lot_id,
            attempt.attempt,
            status,
            order_id=order.order_id if order is not None else '',
        ),
    )
    if code:
        pause_automatic(engine, code)


def pump_automatic(engine: 'TradingEngine') -> None:
    """Protect known holdings while paused; never refresh or poll a broker port."""
    with engine.lock:
        _assert_simulation(engine)
        if engine.storage_failed or engine.state.engine_closed:
            raise DomainError('capability_missing')
        _sync_results(engine)
        observe_account_limits(engine)
        if engine.state.stopped and not engine.state.automatic.auto_paused:
            pause_automatic(engine, next((code for code in engine.state.issues if code != 'daily_baseline_required'), 'automatic_paused'))
        for lot in tuple(engine.state.positions):
            if not lot.quantity or lot.origin != 'MANAGED':
                continue
            record = next((row for row in engine.state.strategies if (row.strategy_id, row.version) == (lot.strategy_id, lot.strategy_version)), None)
            if record is None or record.parameters is None:
                continue
            try:
                spec = engine.catalog.resolve(lot.instrument_id)
                session = calendar_for_instrument(engine.calendar, spec).day_session(lot.holding_origin)
                window = force_exit_window(lot.policy.kind, spec.market, session)
                if window is not None and engine.clock.now() >= window.due_at:
                    _force_lot(engine, lot, window)
                else:
                    current_session = calendar_for_instrument(engine.calendar, spec).day_session(engine.state.trading_day)
                    buckets = complete_buckets(
                        getattr(engine, 'automatic_minute_bars', {}).get(lot.instrument_id, ()),
                        record.parameters.bar_interval,
                        current_session,
                        engine.clock.now(),
                    )
                    _exit_decision(
                        engine, lot, _history(engine, lot.instrument_id, record.parameters.bar_interval, buckets), intraday_timer=False, evaluate_signal=False
                    )
            except DomainError as error:
                if engine.storage_failed:
                    raise
                pause_automatic(engine, error.code)
