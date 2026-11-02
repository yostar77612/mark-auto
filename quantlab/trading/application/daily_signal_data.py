"""Bind official daily research and each saved signal to one point-in-time basis."""

from dataclasses import replace
from datetime import date, timedelta

from .codec import loads
from .contracts import DailySignalDataView
from .research import ResearchResult
from .daily_signal_projection import daily_projection, signal_window_fingerprint
from quantlab.trading.domain.daily_signal_data import DailyResearchBasis, DailySignalPolicy
from quantlab.trading.domain.auto_cycle import EvaluationCursor
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError

VIEW_TTL = timedelta(seconds=30)


def _source_history(engine, source, instrument_id, calendar, *, through, start):
    """Only native pump admission requests a prepared, revision-bound cache hit."""
    try:
        if getattr(engine, 'daily_signal_cached_only', False):
            history = source.cached_history(instrument_id, calendar, through=through, start=start)
            if history is None:
                raise DomainError('daily_signal_not_available', 'verified official history must be prepared outside the writer locks')
            return history
        return source.history(instrument_id, calendar, through=through, start=start)
    except DomainError:
        raise
    except Exception:
        raise DomainError('daily_signal_source_unverified', 'official source read failed') from None


def uses_official_daily(record) -> bool:
    return (
        record.form.environment is Environment.BROKER_SIMULATION
        and record.form.market is Market.STOCK
        and record.parameters is not None
        and record.parameters.bar_interval == '1d'
    )


def official_daily_result(engine, record, result, *, history=None):
    """A transport refresh can change bytes; prior training facts cannot change."""
    if not uses_official_daily(record):
        return None
    if not isinstance(result, ResearchResult) or not isinstance(result.daily_basis, DailyResearchBasis):
        raise DomainError('daily_signal_source_unverified', 'explicit official daily research basis required')
    source = getattr(engine, 'daily_signal_source', None)
    if source is None:
        raise DomainError('daily_signal_source_unverified', 'server-owned official daily source required')
    basis = result.daily_basis
    calendar = engine._strategy_calendar(record, record.form.instrument_id)
    history = history or _source_history(engine, source, record.form.instrument_id, calendar, through=basis.end, start=basis.start)
    completed_at = calendar.day_session(history.bars[-1].trade_date).closes_at
    if not completed_at <= history.observed_at <= engine.clock.now():
        raise DomainError('daily_signal_not_available', 'official facts must already be observed after their completed DAY')
    projected = daily_projection(history, calendar, basis, history.bars[-1].trade_date, cached_only=getattr(engine, 'daily_signal_cached_only', False))
    current = projected.research_basis
    if basis.policy_fingerprint != DailySignalPolicy().fingerprint or not basis.compatible(current):
        raise DomainError('daily_signal_basis_mismatch', 'research source policy or historical observations changed')
    expected = projected.dataset_id
    if result.dataset_id != expected or record.evidence_hash != result.fingerprint:
        raise DomainError('daily_signal_basis_mismatch', 'research dataset or committed evidence identity mismatch')
    return history


def _signal_window_hash(history, calendar, through: date, signals):
    return signal_window_fingerprint(history, calendar, through, signals)


def _eligible_signal_close(calendar, now):
    closed = tuple(row for row in calendar.sessions if row.kind == 'DAY' and row.closes_at <= now)
    if not closed:
        raise DomainError('daily_signal_not_available', 'no completed verified DAY')
    session = closed[-1]
    target = next((row for row in calendar.sessions if row.kind == 'DAY' and row.trade_date > session.trade_date), None)
    if target is None:
        raise DomainError('calendar_missing', 'next verified DAY required before saving a daily signal')
    if now >= target.opens_at:
        raise DomainError('daily_signal_not_available', 'late official data cannot mint an opening catch-up signal')
    return session


def official_daily_cursor(engine, record, instrument_id, calendar):
    """Check durable evaluation/intent identities before any source reconstruction."""
    from .automatic_state import claim_cursor

    try:
        session = _eligible_signal_close(calendar, engine.clock.now())
    except DomainError as error:
        _set_daily_data_view(engine, record, instrument_id, reason=error.code)
        return None
    cursor = EvaluationCursor(record.strategy_id, record.version, instrument_id, '1d', session.closes_at)
    if any(row.cursor == cursor for row in engine.state.automatic.daily.intents):
        return None
    if claim_cursor(engine.state.automatic, cursor, engine.clock.now()) is None:
        return None
    return cursor


def _set_daily_data_view(engine, record, instrument_id, *, history=None, day=None, reason=''):
    cache = getattr(engine, 'daily_signal_data_views', {})
    policy = history.policy if history is not None else None
    view = DailySignalDataView(
        record.strategy_id,
        record.version,
        instrument_id,
        status='VERIFIED' if history is not None and not reason else 'UNVERIFIED',
        source=policy.source_id if policy is not None else '',
        price_mode=policy.price_mode if policy is not None else '',
        adjustment_method=policy.adjustment_method if policy is not None else '',
        trade_date=day,
        available_at=history.observed_at if history is not None else None,
        source_digest=history.source_digest if history is not None else '',
        reason=reason,
        verified_at=engine.clock.now() if history is not None and not reason else None,
        expires_at=engine.clock.now() + VIEW_TTL if history is not None and not reason else None,
    )
    cache[(record.strategy_id, record.version, instrument_id)] = (view, record.evidence_hash, getattr(engine, 'daily_signal_source', None))
    engine.daily_signal_data_views = cache


def stock_daily_window(engine, record, instrument_id, calendar):
    """Return one official close, or an explicit unavailable row without a claim."""
    session = None
    try:
        session = _eligible_signal_close(calendar, engine.clock.now())
        result = loads(record.research_blob) if record.research_blob else None
        if not isinstance(result, ResearchResult) or result.daily_basis is None:
            raise DomainError('daily_signal_source_unverified')
        source = getattr(engine, 'daily_signal_source', None)
        if source is None:
            raise DomainError('daily_signal_source_unverified')
        history = _source_history(engine, source, instrument_id, calendar, through=session.trade_date, start=result.daily_basis.start)
        official_daily_result(engine, record, result, history=history)
        projected = daily_projection(history, calendar, result.daily_basis, session.trade_date, cached_only=getattr(engine, 'daily_signal_cached_only', False))
        signals = projected.signals
        raw = next(row for row in history.bars if row.trade_date == session.trade_date)
        bar = LiveBar(
            instrument_id, session.opens_at, session.closes_at, session.trade_date, 'DAY', raw.open, raw.high, raw.low, raw.close, raw.volume, final=True
        )
        fingerprint = projected.signal_fingerprint
        _set_daily_data_view(engine, record, instrument_id, history=history, day=session.trade_date)
        return bar, signals, fingerprint, history.policy.fingerprint
    except DomainError as error:
        _set_daily_data_view(engine, record, instrument_id, day=session.trade_date if session is not None else None, reason=error.code)
        return None
    except Exception:
        _set_daily_data_view(engine, record, instrument_id, day=session.trade_date if session is not None else None, reason='daily_signal_source_unverified')
        return None


def assert_daily_intent_source(engine, record, intent):
    """Check saved signal facts again before any durable dispatch/financial entry."""
    if not uses_official_daily(record):
        return
    try:
        _assert_daily_intent_source(engine, record, intent)
    except DomainError as error:
        _set_daily_data_view(engine, record, intent.instrument_id, reason=error.code)
        raise


def _assert_daily_intent_source(engine, record, intent):
    if not intent.data_fingerprint or intent.data_policy_fingerprint != DailySignalPolicy().fingerprint:
        raise DomainError('daily_signal_source_unverified', 'old or unattested stock signal cannot dispatch')
    calendar = engine._strategy_calendar(record, intent.instrument_id)
    session = next((row for row in calendar.sessions if row.kind == 'DAY' and row.closes_at == intent.cursor.bar_end), None)
    if session is None:
        raise DomainError('calendar_missing')
    result = loads(record.research_blob) if record.research_blob else None
    if not isinstance(result, ResearchResult) or result.daily_basis is None:
        raise DomainError('daily_signal_source_unverified')
    source = getattr(engine, 'daily_signal_source', None)
    if source is None:
        raise DomainError('daily_signal_source_unverified')
    history = _source_history(engine, source, intent.instrument_id, calendar, through=session.trade_date, start=result.daily_basis.start)
    official_daily_result(engine, record, result, history=history)
    projected = daily_projection(history, calendar, result.daily_basis, session.trade_date, cached_only=getattr(engine, 'daily_signal_cached_only', False))
    if intent.data_fingerprint != projected.signal_fingerprint:
        raise DomainError('daily_signal_basis_mismatch', 'saved signal prices or corporate actions changed')
    _set_daily_data_view(engine, record, intent.instrument_id, history=history, day=session.trade_date)


def daily_signal_views(engine):
    """Snapshot is cache-only; source reads are never triggered by rendering."""
    cache = getattr(engine, 'daily_signal_data_views', {})
    result = []
    for record in engine.state.strategies:
        if not uses_official_daily(record) or record.state == 'DELETED':
            continue
        key = record.strategy_id, record.version, record.form.instrument_id
        prior = cache.get(key)
        if prior is not None and prior[1] == record.evidence_hash and prior[2] is getattr(engine, 'daily_signal_source', None):
            row = prior[0]
            if row.status == 'VERIFIED' and (row.expires_at is None or not row.verified_at <= engine.clock.now() < row.expires_at):
                row = replace(row, status='UNVERIFIED', reason='daily_signal_not_available')
            result.append(row)
        else:
            result.append(DailySignalDataView(*key))
    return tuple(result)
