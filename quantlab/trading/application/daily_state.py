"""Durable daily signal identities; current execution facts are never saved here."""

from dataclasses import dataclass, replace
from datetime import date, datetime

from quantlab.trading.domain.auto_cycle import EvaluationCursor, evaluation_key
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware, identity


@dataclass(frozen=True)
class DailyIntent:
    cursor: EvaluationCursor
    account_ref: str
    action: str
    instrument_id: str
    lot_id: str
    evidence_fingerprint: str
    calendar_id: str
    calendar_version: str
    target_trade_date: date
    not_before: datetime
    deadline: datetime
    created_at: datetime
    phase: str = 'READY'
    order_id: str = ''
    code: str = ''

    @property
    def key(self) -> str:
        key = evaluation_key(self.cursor)
        return key + f':exit:{self.lot_id}' if self.action == 'EXIT' else key


@dataclass(frozen=True)
class DailyState:
    intents: tuple[DailyIntent, ...] = ()
    authorized_run: str = ''
    owner_stamp: str = ''
    waiting_session: bool = False


def next_session(calendar: TradingCalendar, cursor: EvaluationCursor) -> TradingSession:
    """Use supplied DAY coverage, including gaps and DAY-less night sessions."""
    if cursor.interval != '1d':
        raise DomainError('validation_failed', 'a daily completed cursor is required')
    aware(cursor.bar_end)
    origin = next((row for row in calendar.sessions if row.kind == 'DAY' and row.closes_at == cursor.bar_end), None)
    if origin is None:
        raise DomainError('daily_close_unverified', 'cursor must identify an actual verified DAY close')
    target = next((row for row in calendar.sessions if row.kind == 'DAY' and row.trade_date > origin.trade_date), None)
    if target is None:
        raise DomainError('calendar_missing', 'next verified DAY is outside supplied coverage')
    return target


def create_intent(
    cursor: EvaluationCursor,
    account_ref: str,
    action: str,
    instrument_id: str,
    lot_id: str,
    evidence_fingerprint: str,
    calendar: TradingCalendar,
    created_at: datetime,
) -> DailyIntent:
    """Save identity only; current execution prices, quantities and cash stay live."""
    target = next_session(calendar, cursor)
    aware(created_at)
    identity(account_ref, 'daily account')
    identity(instrument_id, 'daily actual instrument')
    if action not in ('ENTRY', 'EXIT') or (action == 'EXIT') != bool(lot_id):
        raise DomainError('validation_failed', 'ENTRY has no lot; EXIT requires its owned lot ID')
    if lot_id:
        identity(lot_id, 'daily owned lot')
    if not isinstance(evidence_fingerprint, str) or len(evidence_fingerprint) != 64 or any(char not in '0123456789abcdef' for char in evidence_fingerprint):
        raise DomainError('validation_failed', 'daily researched fingerprint')
    if not cursor.bar_end <= created_at < target.opens_at:
        raise DomainError('daily_close_unverified', 'late history cannot mint a next-session catch-up signal')
    return DailyIntent(
        cursor,
        account_ref,
        action,
        instrument_id,
        lot_id,
        evidence_fingerprint,
        calendar.calendar_id,
        calendar.version,
        target.trade_date,
        target.opens_at,
        target.closes_at,
        created_at,
    )


def append_batch(state: DailyState, intents: tuple[DailyIntent, ...]) -> DailyState:
    """Store all actions from one close together; preserve the current run grant."""
    if not intents:
        return state
    first = intents[0]
    if any(row.cursor != first.cursor or row.account_ref != first.account_ref for row in intents):
        raise DomainError('daily_signal_invalidated', 'one close/account per atomic batch')
    if any(row.phase != 'READY' or row.order_id or row.code for row in intents):
        raise DomainError('daily_signal_invalidated', 'only new identities can be appended')
    keys = tuple(row.key for row in intents)
    if len(set(keys)) != len(keys):
        raise DomainError('daily_signal_invalidated', 'duplicate action/lot in close batch')
    additions = []
    for row in intents:
        prior = next((old for old in state.intents if old.key == row.key), None)
        if prior is not None and prior != row:
            raise DomainError('daily_signal_invalidated', 'saved action identity cannot be rewritten')
        if prior is None:
            additions.append(row)
    if not additions:
        return state
    ordered = tuple(sorted(additions, key=lambda row: (row.action == 'ENTRY', row.lot_id)))
    return replace(state, intents=(*state.intents, *ordered), waiting_session=True)


def authorize(state: DailyState, run_id: str, owner_stamp: str) -> DailyState:
    """Called only after explicit resume and current application proofs."""
    if not run_id or not owner_stamp:
        raise DomainError('daily_signal_not_authorized')
    if any(row.phase in ('CLAIMED', 'UNKNOWN') for row in state.intents):
        raise DomainError('daily_signal_unresolved')
    return replace(state, authorized_run=run_id, owner_stamp=owner_stamp, waiting_session=False)


def revoke(state: DailyState) -> DailyState:
    """A fault revokes dispatch authority without rewriting signal identities."""
    return replace(state, authorized_run='', owner_stamp='', waiting_session=False)


def restart(state: DailyState) -> DailyState:
    """A durable dispatch claim may have reached the SDK; never reset it."""
    intents = tuple(replace(row, phase='UNKNOWN', code='daily_signal_unresolved') if row.phase == 'CLAIMED' else row for row in state.intents)
    return revoke(replace(state, intents=intents))


def claim_dispatch(
    state: DailyState,
    key: str,
    now: datetime,
    calendar: TradingCalendar,
    *,
    run_id: str,
    owner_stamp: str,
    environment: Environment,
) -> DailyState:
    """Caller journals this claim before crossing the existing execution guard."""
    if environment is Environment.LIVE:
        raise DomainError('production_orders_disabled')
    if environment is not Environment.BROKER_SIMULATION:
        raise DomainError('capability_missing')
    aware(now)
    if not state.authorized_run or not state.owner_stamp or (run_id, owner_stamp) != (state.authorized_run, state.owner_stamp):
        raise DomainError('daily_signal_not_authorized')
    intent = next((row for row in state.intents if row.key == key), None)
    if intent is None:
        raise DomainError('daily_signal_invalidated')
    if intent.phase in ('CLAIMED', 'UNKNOWN'):
        raise DomainError('daily_signal_unresolved')
    if intent.phase != 'READY':
        raise DomainError('daily_signal_invalidated', 'terminal actions cannot be dispatched again')
    if (calendar.calendar_id, calendar.version) != (intent.calendar_id, intent.calendar_version):
        raise DomainError('daily_signal_invalidated', 'calendar provenance changed')
    target = next_session(calendar, intent.cursor)
    if (target.trade_date, target.opens_at, target.closes_at) != (intent.target_trade_date, intent.not_before, intent.deadline):
        raise DomainError('daily_signal_invalidated', 'next verified DAY changed')
    if now < intent.not_before:
        raise DomainError('daily_waiting_session')
    if now >= intent.deadline:
        raise DomainError('daily_signal_expired')
    if any(
        row.cursor == intent.cursor
        and row.action == 'EXIT'
        and row.phase in ('READY', 'CLAIMED', 'UNKNOWN')
        and (intent.action == 'ENTRY' or row.lot_id < intent.lot_id)
        for row in state.intents
    ):
        raise DomainError('daily_signal_unresolved', 'earlier close exits must complete first')
    claimed = replace(intent, phase='CLAIMED')
    return replace(state, intents=tuple(claimed if row.key == key else row for row in state.intents), waiting_session=False)


def record_result(
    state: DailyState,
    key: str,
    *,
    known: bool,
    order_id: str = '',
    code: str = '',
    observed: bool = False,
) -> DailyState:
    """UNKNOWN can resolve only from an observed known canonical order."""
    intent = next((row for row in state.intents if row.key == key), None)
    if intent is None:
        raise DomainError('daily_signal_invalidated')
    if intent.order_id and intent.order_id != order_id:
        raise DomainError('daily_signal_invalidated', 'canonical order identity changed')
    phase = 'DISPATCHED' if known and order_id else 'KNOWN_NO_ORDER' if known else 'UNKNOWN'
    code = code or ('daily_signal_unresolved' if not known else '')
    if (intent.phase, intent.order_id, intent.code) == (phase, order_id, code):
        return revoke(state) if not known else state
    if intent.phase != 'CLAIMED' and not (intent.phase == 'UNKNOWN' and observed and known and order_id):
        raise DomainError('daily_signal_unresolved', 'a claim or observed positive resolution is required')
    result = replace(intent, phase=phase, order_id=order_id, code=code)
    updated = replace(state, intents=tuple(result if row.key == key else row for row in state.intents))
    return updated if known else revoke(updated)


def expire(state: DailyState, now: datetime) -> DailyState:
    """Only untouched signals expire; never reinterpret an in-flight outcome."""
    aware(now)
    intents = tuple(
        replace(row, phase='EXPIRED', code='daily_signal_expired') if row.phase == 'READY' and now >= row.deadline else row for row in state.intents
    )
    return replace(state, intents=intents, waiting_session=state.waiting_session and any(row.phase == 'READY' for row in intents))


def invalidate(state: DailyState, key: str, code: str = 'daily_signal_invalidated') -> DailyState:
    """Current-version checks may retire READY intent; UNKNOWN is never erased."""
    intent = next((row for row in state.intents if row.key == key), None)
    if intent is None:
        raise DomainError('daily_signal_invalidated')
    if intent.phase != 'READY':
        return state
    invalid = replace(intent, phase='INVALIDATED', code=code)
    intents = tuple(invalid if row.key == key else row for row in state.intents)
    return replace(state, intents=intents, waiting_session=state.waiting_session and any(row.phase == 'READY' for row in intents))
