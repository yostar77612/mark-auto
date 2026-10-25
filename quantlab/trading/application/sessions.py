"""Explicit non-local trading-day synchronization and attested daily baselines.

No SDK, credential discovery or inferred weekdays. A closing-value provider must
normalize every configured account to the same v2 net-mark basis and attest its
source identity. Until that external evidence exists, new risk remains stopped.
"""

from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import TYPE_CHECKING

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, trading_date

if TYPE_CHECKING:
    from .engine import TradingEngine

BASELINE_ISSUE = 'daily_baseline_required'
PNL_BASIS = 'MARKAUTO_V2_LEDGER_NET_MARK_1'


@dataclass(frozen=True)
class SessionContext:
    trade_date: date
    kind: str
    active: bool
    opens_at: datetime
    closes_at: datetime
    calendar_id: str
    calendar_version: str


@dataclass(frozen=True)
class DailyBaselineEvidence:
    environment: Environment
    account_refs: tuple[str, ...]
    previous_trade_date: date
    trade_date: date
    calendar_id: str
    calendar_version: str
    fee_version: str
    fee_fingerprint: str
    previous_close_total_pnl: Decimal
    as_of: datetime
    source_id: str
    pnl_basis: str = PNL_BASIS

    def __post_init__(self) -> None:
        if not isinstance(self.environment, Environment) or type(self.account_refs) is not tuple or not 1 <= len(self.account_refs) <= 64:
            raise DomainError('validation_failed', 'daily baseline environment/accounts')
        for account in self.account_refs:
            identity(account, 'account reference')
        if self.account_refs != tuple(sorted(set(self.account_refs))):
            raise DomainError('validation_failed', 'baseline accounts must be uniquely sorted')
        for name in ('calendar_id', 'calendar_version', 'fee_version', 'source_id'):
            identity(getattr(self, name), name)
        for day in (self.previous_trade_date, self.trade_date):
            trading_date(day)
        if self.previous_trade_date >= self.trade_date or self.pnl_basis != PNL_BASIS:
            raise DomainError('validation_failed', 'baseline valuation basis/dates')
        if type(self.fee_fingerprint) is not str or len(self.fee_fingerprint) != 64 or any(c not in '0123456789abcdef' for c in self.fee_fingerprint):
            raise DomainError('validation_failed', 'baseline cost fingerprint')
        decimal_value(self.previous_close_total_pnl, 'previous close net mark')
        aware(self.as_of)


def fee_fingerprint(fees: FeeSchedule) -> str:
    if not isinstance(fees, FeeSchedule):
        raise DomainError('validation_failed', 'typed cost schedule required')
    values = tuple((field.name, str(getattr(fees, field.name))) for field in fields(fees))
    return sha256(json.dumps(values, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def resolve_session(calendar: TradingCalendar, now: datetime, *, night_enabled: bool = False) -> SessionContext:
    aware(now)
    if not isinstance(calendar, TradingCalendar) or type(night_enabled) is not bool:
        raise DomainError('validation_failed', 'calendar/session policy')
    eligible = tuple(s for s in calendar.sessions if s.kind == 'DAY' or night_enabled)
    active = next((s for s in eligible if s.opens_at <= now <= s.closes_at), None)
    previous_days = tuple(s for s in calendar.sessions if s.kind == 'DAY' and s.opens_at <= now)
    session = active or (previous_days[-1] if previous_days else None)
    if session is None:
        raise DomainError('calendar_missing', 'no verified already-open day session')
    return SessionContext(session.trade_date, session.kind, active is not None, session.opens_at, session.closes_at, calendar.calendar_id, calendar.version)


def validate_baseline(
    evidence: DailyBaselineEvidence,
    *,
    environment: Environment,
    account_refs: tuple[str, ...],
    calendar: TradingCalendar,
    fees: FeeSchedule,
    now: datetime,
    trade_date: date,
    trusted_sources: frozenset[str],
) -> None:
    aware(now)
    trading_date(trade_date)
    if not isinstance(calendar, TradingCalendar) or not isinstance(fees, FeeSchedule) or type(account_refs) is not tuple or not account_refs:
        raise DomainError('validation_failed', 'typed baseline validation context required')
    if not isinstance(evidence, DailyBaselineEvidence) or environment is Environment.LOCAL:
        raise DomainError(BASELINE_ISSUE, 'non-local typed baseline evidence required')
    if type(trusted_sources) is not frozenset or evidence.source_id not in trusted_sources:
        raise DomainError(BASELINE_ISSUE, 'closing source is not attested by the trusted provider')
    if evidence.environment is not environment or evidence.account_refs != tuple(sorted(account_refs)):
        raise DomainError(BASELINE_ISSUE, 'every configured account and environment must match')
    if evidence.trade_date != trade_date or evidence.calendar_id != calendar.calendar_id or evidence.calendar_version != calendar.version:
        raise DomainError(BASELINE_ISSUE, 'baseline date/calendar identity mismatch')
    index = calendar.index(trade_date)
    if index == 0 or evidence.previous_trade_date != calendar.days[index - 1]:
        raise DomainError(BASELINE_ISSUE, 'baseline does not cover the previous verified trading day')
    close = calendar.day_session(evidence.previous_trade_date).closes_at
    if evidence.as_of != close or evidence.as_of > aware(now):
        raise DomainError(BASELINE_ISSUE, 'baseline must value the exact prior day close')
    if evidence.fee_version != fees.version or evidence.fee_fingerprint != fee_fingerprint(fees):
        raise DomainError(BASELINE_ISSUE, 'baseline cost values changed, including same-version changes')


def _matches_committed_baseline(engine: 'TradingEngine', context: SessionContext) -> bool:
    evidence = engine.state.daily_baseline_evidence
    if evidence is None or not isinstance(engine.state.daily_baseline_pnl, Decimal) or engine.state.daily_baseline_pnl != evidence.previous_close_total_pnl:
        return False
    try:
        # Only confirm_daily_baseline writes this durable attestation. Public IPC
        # has no command that can provide evidence or clear the required latch.
        validate_baseline(
            evidence,
            environment=engine.configuration.environment,
            account_refs=tuple(engine.gateways),
            calendar=engine.calendar,
            fees=engine.fees,
            now=engine.clock.now(),
            trade_date=context.trade_date,
            trusted_sources=frozenset((evidence.source_id,)),
        )
        return True
    except DomainError:
        return False


def synchronize_session(engine: 'TradingEngine') -> bool:
    with engine.lock:
        return _synchronize_session(engine)


def _synchronize_session(engine: 'TradingEngine') -> bool:
    if engine.configuration.environment is Environment.LOCAL:
        return False  # Local lab dates advance only through their explicit control.
    context = resolve_session(engine.calendar, engine.clock.now(), night_enabled=engine.state.settings.night_enabled)
    state = engine.state
    rollback = context.trade_date < state.trading_day
    required = rollback or state.daily_baseline_required or not _matches_committed_baseline(engine, context)
    changed = context.trade_date != state.trading_day
    if not changed and required == state.daily_baseline_required:
        return False
    issues = tuple(sorted(set((*state.issues, BASELINE_ISSUE, *(('state_conflict',) if rollback else ())))))
    if rollback and state.daily_baseline_required and state.stopped and issues == state.issues:
        return False
    engine._persist(
        'broker_session_baseline_required',
        replace(
            state,
            trading_day=state.trading_day if rollback else context.trade_date,
            daily_baseline_required=True,
            stopped=True,
            reconciled=False,
            issues=issues,
        ),
    )
    # Previous baseline/PnL and every dated daily lock intentionally remain intact.
    return True


def assert_daily_baseline(engine: 'TradingEngine') -> None:
    if engine.configuration.environment is Environment.LOCAL:
        return
    synchronize_session(engine)
    context = resolve_session(engine.calendar, engine.clock.now(), night_enabled=engine.state.settings.night_enabled)
    if engine.state.daily_baseline_required or engine.state.trading_day != context.trade_date or not _matches_committed_baseline(engine, context):
        raise DomainError(BASELINE_ISSUE, 'new risk waits for an attested previous-close baseline')


@decimal_operation
def confirm_daily_baseline(engine: 'TradingEngine', evidence: DailyBaselineEvidence, *, trusted_sources: frozenset[str]) -> None:
    with engine.lock:
        _confirm_daily_baseline(engine, evidence, trusted_sources=trusted_sources)


def _confirm_daily_baseline(engine: 'TradingEngine', evidence: DailyBaselineEvidence, *, trusted_sources: frozenset[str]) -> None:
    from .events import reconcile
    from .workflows import total_mark

    synchronize_session(engine)
    context = resolve_session(engine.calendar, engine.clock.now(), night_enabled=engine.state.settings.night_enabled)
    if engine.state.trading_day != context.trade_date:
        raise DomainError(BASELINE_ISSUE, 'clock/calendar rollback requires investigation')
    validate_baseline(
        evidence,
        environment=engine.configuration.environment,
        account_refs=tuple(engine.gateways),
        calendar=engine.calendar,
        fees=engine.fees,
        now=engine.clock.now(),
        trade_date=context.trade_date,
        trusted_sources=trusted_sources,
    )
    # Reconcile only account facts; a required baseline remains a separate issue.
    reconcile(engine)
    if not engine.state.reconciled:
        raise DomainError('reconciliation_required', 'fresh account reconciliation required')
    current = total_mark(engine)  # Unknown/stale open-position marks cannot become 0.
    pnl = current - evidence.previous_close_total_pnl
    locks = engine.state.daily_locks
    if -pnl >= Decimal('100000') * engine.state.settings.daily_loss_fraction and context.trade_date not in locks:
        locks = (*locks, context.trade_date)
    issues = tuple(code for code in engine.state.issues if code != BASELINE_ISSUE)
    engine._persist(
        'daily_baseline_attested',
        replace(
            engine.state,
            daily_baseline_required=False,
            daily_baseline_evidence=evidence,
            daily_baseline_pnl=evidence.previous_close_total_pnl,
            daily_pnl=pnl,
            daily_locks=locks,
            stopped=True,
            issues=issues,
        ),
    )
