"""Save close-time decisions and dispatch them using current admitted facts."""

from dataclasses import replace

from . import automatic_state as claims, daily_state as pending
from .automatic_baseline import automatic_baseline_rows
from .daily_closes import SOURCE_ID, daily_close_evidence, observe_daily_closes
from .preflight import PreflightFacts, assert_preflight, record_preflight
from .research import entry_signal, exit_signal
from .state import ACTIVE
from quantlab.trading.domain.auto_cycle import EvaluationCursor, complete_buckets
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import Environment, OrderStatus
from quantlab.trading.domain.strategy import resolve_tmf_near
from quantlab.trading.domain.validation import DomainError


def records(engine):
    return tuple(row for row in engine.state.strategies if row.parameters is not None and row.parameters.bar_interval == '1d')


def scheduled_waiting(engine):
    """Expected missing next-day facts defer background marks, never commitment risk."""
    automatic = engine.state.automatic
    expected = {'daily_baseline_required', 'account_daily_baseline_required', 'manual_day_baseline_required'}
    return (
        not automatic.auto_paused
        and bool(automatic.daily.authorized_run)
        and automatic.daily.waiting_session
        and not set(engine.state.issues) - expected
        and not any(set(book.reasons) - {'manual_day_baseline_required'} for book in engine.state.manual_books if book.halted)
    )


def _simulation(engine):
    engine.assert_execution_allowed()
    if engine.configuration.environment is not Environment.BROKER_SIMULATION:
        raise DomainError('capability_missing')


def owner_stamp(engine):
    callback = getattr(engine, 'automatic_owner_stamp', None)
    if not callable(callback):
        raise DomainError('capability_missing', 'authenticated automatic run owner required')
    return callback()


def authorize_run(engine, automatic):
    daily = pending.authorize(pending.expire(automatic.daily, engine.clock.now()), automatic.resumed_at.isoformat(), owner_stamp(engine))
    return replace(automatic, daily=daily)


def _authorized(engine):
    automatic = engine.state.automatic
    daily = automatic.daily
    if automatic.auto_paused or not daily.authorized_run or daily.owner_stamp != owner_stamp(engine):
        raise DomainError('daily_signal_not_authorized')
    return daily


def _store(engine, kind, daily):
    if daily != engine.state.automatic.daily:
        engine._persist(kind, replace(engine.state, automatic=replace(engine.state.automatic, daily=daily)))


def _entry_instrument(engine, record):
    if record.parameters.instrument_rule == 'TMF_NEAR':
        return resolve_tmf_near(engine.catalog.instruments, engine.calendar, engine.state.trading_day).instrument_id
    return record.form.instrument_id


def _make_actions(engine, record, cursor, calendar, history):
    now = engine.clock.now()
    bars = tuple(bar for bar in history if bar.available_at <= cursor.bar_end)
    owned = tuple(
        lot
        for lot in engine.state.positions
        if lot.quantity and lot.origin == 'MANAGED' and (lot.strategy_id, lot.strategy_version) == (record.strategy_id, record.version)
    )
    result = []
    for lot in sorted(owned, key=lambda row: row.lot_id):
        if lot.instrument_id == cursor.instrument_id and exit_signal(record, bars, cursor.bar_end):
            result.append(pending.create_intent(cursor, record.form.account_ref, 'EXIT', lot.instrument_id, lot.lot_id, record.evidence_hash, calendar, now))
    if (
        record.state == 'ACTIVE'
        and cursor.instrument_id == _entry_instrument(engine, record)
        and not owned
        and not any(order.plan.strategy_id == record.strategy_id and not order.plan.reduce_only and order.status in ACTIVE for order in engine.state.orders)
        and entry_signal(record, bars, cursor.bar_end)
    ):
        result.append(pending.create_intent(cursor, record.form.account_ref, 'ENTRY', cursor.instrument_id, '', record.evidence_hash, calendar, now))
    return tuple(result)


def observe_daily(engine, bars):
    """Trusted same-owner completed bars only; this phase never submits orders."""
    from . import automatic

    with engine.lock:
        _simulation(engine)
        cache = automatic.remember_bars(engine, bars)
        closing_bars = []
        for instrument_id, minutes in cache.items():
            calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(instrument_id))
            session = calendar.day_session(engine.state.trading_day)
            if engine.clock.now() >= session.closes_at:
                closing_bars.extend(complete_buckets(minutes, '1d', session, engine.clock.now()))
        observe_daily_closes(engine, tuple(closing_bars))
        if engine.state.automatic.auto_paused or not engine.state.automatic.daily.authorized_run:
            return
        _authorized(engine)
        for record in records(engine):
            owned_ids = {
                lot.instrument_id
                for lot in engine.state.positions
                if lot.quantity and lot.origin == 'MANAGED' and (lot.strategy_id, lot.strategy_version) == (record.strategy_id, record.version)
            }
            instruments = owned_ids | ({_entry_instrument(engine, record)} if record.state == 'ACTIVE' else set())
            for instrument_id in sorted(instruments):
                calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(instrument_id))
                session = calendar.day_session(engine.state.trading_day)
                buckets = complete_buckets(cache.get(instrument_id, ()), '1d', session, engine.clock.now())
                for bar in buckets:
                    cursor = EvaluationCursor(record.strategy_id, record.version, instrument_id, '1d', bar.end)
                    target = pending.next_session(calendar, cursor)
                    claimed = claims.claim_cursor(engine.state.automatic, cursor, engine.clock.now(), target.closes_at)
                    if claimed is None:
                        continue
                    engine._persist('daily_evaluation_claimed', replace(engine.state, automatic=claimed))
                    history = automatic._history(engine, instrument_id, '1d', buckets)[instrument_id]
                    actions = _make_actions(engine, record, cursor, calendar, history)
                    daily = pending.append_batch(engine.state.automatic.daily, actions)
                    completed = claims.complete_evaluation(engine.state.automatic, cursor)
                    engine._persist(
                        'daily_signals_saved',
                        replace(engine.state, automatic=replace(completed, daily=replace(daily, waiting_session=True))),
                    )


def wait_session(engine):
    """An expected calendar close preserves a live run rather than granting one."""
    with engine.lock:
        _simulation(engine)
        if engine.state.automatic.auto_paused or not engine.state.automatic.daily.authorized_run:
            return
        daily = _authorized(engine)
        _store(engine, 'daily_waiting_session', replace(daily, waiting_session=True))


def prepare_daily_baseline(engine):
    """Accept real closing evidence without authorizing or resuming a run."""
    from .manual_book import release_manual_day_wait

    with engine.lock:
        _simulation(engine)
        observe_daily_closes(engine, ())
        current_day = engine.state.trading_day
        if not all(any(row.account_ref == ref and row.trade_date == current_day for row in engine.state.account_daily_baselines) for ref in engine.gateways):
            evidence = daily_close_evidence(engine, current_day)
            rows = automatic_baseline_rows(engine, evidence, trusted_sources=frozenset((SOURCE_ID,)))
            closes = tuple(
                replace(row, consumed_on=current_day) if row.trade_date == evidence.previous_trade_date else row for row in engine.state.daily_account_closes
            )
            engine._persist(
                'daily_account_baselines_applied',
                replace(
                    engine.state,
                    account_daily_baselines=rows,
                    automatic_daily_evidence=evidence,
                    daily_account_closes=closes,
                    issues=tuple(code for code in engine.state.issues if code != 'account_daily_baseline_required'),
                ),
            )
        release_manual_day_wait(engine)


def continue_daily_session(engine, facts: tuple[tuple[str, PreflightFacts], ...]):
    """Continue only a preserved run after current-day evidence and preflight."""
    from . import automatic

    with engine.lock:
        _simulation(engine)
        daily = _authorized(engine)
        if not daily.waiting_session:
            return
        if engine.state.manual_stopped:
            raise DomainError('automatic_paused')
        prepare_daily_baseline(engine)
        if any(book.halted for book in engine.state.manual_books):
            raise DomainError('automatic_paused')
        current_day = engine.state.trading_day
        for reference, proof in facts:
            if not any(row.account_ref == reference and row.trade_date == current_day for row in engine.state.preflight):
                record_preflight(engine, reference, proof)
            assert_preflight(engine, reference)
        automatic._entry_proofs(engine)
        daily = _authorized(engine)
        engine.fence()
        engine._persist(
            'daily_scheduled_session_continued',
            replace(engine.state, stopped=False, automatic=replace(engine.state.automatic, daily=replace(daily, waiting_session=False))),
        )


def _matching_record(engine, intent):
    record = engine.strategy(f'{intent.cursor.strategy_id}:{intent.cursor.version}')
    if (
        record.parameters is None
        or record.parameters.bar_interval != '1d'
        or record.form.environment is not Environment.BROKER_SIMULATION
        or record.form.account_ref != intent.account_ref
        or record.evidence_hash != intent.evidence_fingerprint
        or intent.action == 'ENTRY'
        and (record.state != 'ACTIVE' or _entry_instrument(engine, record) != intent.instrument_id)
    ):
        raise DomainError('daily_signal_invalidated')
    return record


def assert_daily_dispatch(engine, plan, key):
    """Final commitment admission; a generic direct daily order has no authority."""
    _simulation(engine)
    daily = _authorized(engine)
    intent = next((row for row in daily.intents if row.key == key), None)
    if intent is None or intent.phase != 'CLAIMED':
        raise DomainError('daily_signal_not_authorized')
    _matching_record(engine, intent)
    calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(intent.instrument_id))
    target = calendar.day_session(intent.target_trade_date)
    if (
        calendar.calendar_id != intent.calendar_id
        or calendar.version != intent.calendar_version
        or (target.opens_at, target.closes_at) != (intent.not_before, intent.deadline)
        or not intent.not_before <= engine.clock.now() < intent.deadline
        or engine.state.trading_day != intent.target_trade_date
        or plan.environment is not Environment.BROKER_SIMULATION
        or plan.account_ref != intent.account_ref
        or (plan.strategy_id, plan.strategy_version, plan.instrument_id) != (intent.cursor.strategy_id, intent.cursor.version, intent.instrument_id)
        or plan.reduce_only != (intent.action == 'EXIT')
        or intent.action == 'EXIT'
        and plan.exit_lot_id != intent.lot_id
    ):
        raise DomainError('daily_signal_invalidated')


def reconcile_daily(engine):
    """Known durable reports can resolve a claim; missing reports never prove no send."""
    _simulation(engine)
    if any(row.cursor.interval == '1d' and row.phase == 'INTERRUPTED' for row in engine.state.automatic.evaluations):
        from .daily_recovery import recover_daily_evaluations

        recover_daily_evaluations(engine)
    daily = engine.state.automatic.daily
    for intent in tuple(daily.intents):
        if intent.phase not in ('CLAIMED', 'UNKNOWN'):
            continue
        order = next((row for row in engine.state.orders if row.key == intent.key and (not intent.order_id or row.order_id == intent.order_id)), None)
        if order is not None and order.status not in (OrderStatus.SUBMITTING, OrderStatus.UNKNOWN, OrderStatus.CANCEL_PENDING):
            daily = pending.record_result(daily, intent.key, known=True, order_id=order.order_id, observed=True)
    _store(engine, 'daily_dispatch_reconciled', daily)
    if any(row.phase in ('CLAIMED', 'UNKNOWN') for row in daily.intents):
        raise DomainError('daily_signal_unresolved')


def dispatch_daily(engine):
    """Use current size/quote once; never reserve cash when merely saving a signal."""
    from . import automatic
    from .coordinator import _entry_decision

    with engine.lock:
        _simulation(engine)
        _store(engine, 'daily_signals_expired', pending.expire(engine.state.automatic.daily, engine.clock.now()))
        if engine.state.automatic.auto_paused or not engine.state.automatic.daily.authorized_run:
            return
        daily = _authorized(engine)
        for intent in tuple(daily.intents):
            if intent.phase != 'READY' or engine.clock.now() < intent.not_before:
                continue
            try:
                record = _matching_record(engine, intent)
                calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(intent.instrument_id))
                automatic._entry_proofs(engine)
                automatic._assert_entry_window(engine)
                if engine.state.stopped:
                    raise DomainError('automatic_paused')
                claimed = pending.claim_dispatch(
                    engine.state.automatic.daily,
                    intent.key,
                    engine.clock.now(),
                    calendar,
                    run_id=daily.authorized_run,
                    owner_stamp=owner_stamp(engine),
                    environment=engine.configuration.environment,
                )
            except DomainError as error:
                if error.code == 'daily_signal_invalidated':
                    _store(engine, 'daily_signal_invalidated', pending.invalidate(engine.state.automatic.daily, intent.key))
                    continue
                automatic.pause_automatic(engine, error.code)
                return
            _store(engine, 'daily_dispatch_claimed', claimed)
            code = ''
            try:
                if intent.action == 'ENTRY':
                    _entry_decision(engine, record, {}, decision_key=intent.key, daily_signal=intent)
                else:
                    lot = next((row for row in engine.state.positions if row.lot_id == intent.lot_id and row.quantity), None)
                    if lot is not None:
                        engine.exit_lot(lot.lot_id, protective=False, key=intent.key)
            except DomainError as error:
                code = error.code
            order = next((row for row in engine.state.orders if row.key == intent.key), None)
            unknown = (
                code == 'outcome_unknown'
                or engine.storage_failed
                or (order is not None and order.status in (OrderStatus.SUBMITTING, OrderStatus.UNKNOWN, OrderStatus.CANCEL_PENDING))
            )
            _store(
                engine,
                'daily_dispatch_result',
                pending.record_result(
                    engine.state.automatic.daily,
                    intent.key,
                    known=not unknown,
                    order_id=order.order_id if order is not None else '',
                    code=code or ('outcome_unknown' if unknown else ''),
                ),
            )
            if unknown or code:
                automatic.pause_automatic(engine, code or 'order_result_unknown')
                return
