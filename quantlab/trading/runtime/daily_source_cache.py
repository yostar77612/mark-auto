"""Prepare immutable official snapshots without holding runtime ownership locks."""

from quantlab.trading.application.codec import loads
from quantlab.trading.application.daily_execution import records
from quantlab.trading.application.daily_signal_data import official_daily_cursor, uses_official_daily
from quantlab.trading.application.daily_signal_projection import prepare_daily_projection
from quantlab.trading.application.research import ResearchResult
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


def _requests(engine):
    requests = set()
    for record in records(engine):
        if not uses_official_daily(record):
            continue
        calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(record.form.instrument_id))
        result = loads(record.research_blob) if record.research_blob else None
        if not isinstance(result, ResearchResult) or result.daily_basis is None:
            continue
        basis = result.daily_basis
        cursor = official_daily_cursor(engine, record, record.form.instrument_id, calendar)
        pending = tuple(
            row
            for row in engine.state.automatic.daily.intents
            if (row.cursor.strategy_id, row.cursor.version) == (record.strategy_id, record.version)
            and row.phase in ('READY', 'CLAIMED')
            and row.not_before <= engine.clock.now() < row.deadline
        )
        owned = any(lot.quantity and (lot.strategy_id, lot.strategy_version) == (record.strategy_id, record.version) for lot in engine.state.positions)
        if cursor is not None and (record.state == 'ACTIVE' or owned):
            day = next(row.trade_date for row in calendar.sessions if row.kind == 'DAY' and row.closes_at == cursor.bar_end)
            requests.add((record.form.instrument_id, calendar, day, basis.start, basis))
            requests.add((record.form.instrument_id, calendar, basis.end, basis.start, basis))
        for intent in pending:
            day = next((row.trade_date for row in calendar.sessions if row.kind == 'DAY' and row.closes_at == intent.cursor.bar_end), None)
            if day is not None:
                requests.add((intent.instrument_id, calendar, day, basis.start, basis))
        if pending:
            requests.add((record.form.instrument_id, calendar, basis.end, basis.start, basis))
    return requests


def prepare_daily_sources(bundle, engine):
    if bundle.launch.environment is not Environment.BROKER_SIMULATION or not getattr(engine, 'daily_signal_cached_only', False):
        return
    with bundle.lock, engine.lock:
        if bundle.engine is not engine or bundle.closing or bundle.resources_closed or bundle.control_failed:
            return
        source = engine.daily_signal_source
        if source is None or engine.state.automatic.auto_paused:
            return
        try:
            requests = _requests(engine)
        except DomainError:
            return
    # Reacquisition and final owner checks happen in AutomaticRuntime.pump. Any
    # intervening store revision makes the locked cached-only read fail closed.
    for instrument_id, calendar, through, start, basis in requests:
        try:
            history = source.cached_history(instrument_id, calendar, through=through, start=start)
            if history is None:
                history = source.history(instrument_id, calendar, through=through, start=start)
            prepare_daily_projection(history, calendar, basis, through)
        except DomainError:
            continue
