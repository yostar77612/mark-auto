"""immutable preflight facts and journaled daily admission latch."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING

from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from quantlab.trading.application.engine import TradingEngine


@dataclass(frozen=True)
class PreflightFacts:
    connected: bool | None
    account_ready: bool | None
    permission_ready: bool | None
    ca_ready: bool | None
    realtime: bool | None
    service_open: bool | None
    reconciled: bool | None


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    state: str
    code: str = ''


@dataclass(frozen=True)
class PreflightView:
    account_ref: str
    trade_date: date
    checked_at: datetime
    checks: tuple[PreflightCheck, ...]
    blocked_today: bool
    keep_awake_reminder: bool = True
    block_reasons: tuple[str, ...] = ()


def build_preflight(
    account_ref: str, trade_date: date, now: datetime, environment: Environment, facts: PreflightFacts, *, already_blocked: bool = False
) -> PreflightView:
    values = (
        ('connection', facts.connected, 'preflight_connection'),
        ('account', facts.account_ready, 'preflight_account'),
        ('permission', facts.permission_ready, 'preflight_permission'),
        ('ca', facts.ca_ready, 'preflight_ca'),
        ('market', facts.realtime, 'preflight_market'),
        ('service', facts.service_open, 'preflight_service'),
        ('reconciliation', facts.reconciled, 'preflight_reconciliation'),
    )
    checks = tuple(
        PreflightCheck(key, 'NOT_REQUIRED')
        if key == 'ca' and environment in (Environment.LOCAL, Environment.BROKER_SIMULATION)
        else PreflightCheck(key, 'PASS' if passed is True else 'UNKNOWN' if passed is None else 'FAIL', '' if passed is True else code)
        for key, passed, code in values
    )
    reasons = tuple(row.code for row in checks if row.state not in ('PASS', 'NOT_REQUIRED'))
    return PreflightView(account_ref, trade_date, now, checks, already_blocked or bool(reasons), block_reasons=reasons)


def record_preflight(engine: 'TradingEngine', account_ref: str, facts: PreflightFacts) -> PreflightView:
    if account_ref not in engine.gateways:
        raise DomainError('capability_missing')
    day = engine.state.trading_day
    latch = (account_ref, day)
    result = build_preflight(
        account_ref, day, engine.clock.now(), engine.configuration.environment, facts, already_blocked=latch in engine.state.preflight_blocks
    )
    previous = next((row for row in engine.state.preflight if row.account_ref == account_ref and row.trade_date == day), None)
    if previous is not None:
        result = replace(result, block_reasons=tuple(sorted(set((*previous.block_reasons, *result.block_reasons)))))
    blocks = engine.state.preflight_blocks
    if result.blocked_today and latch not in blocks:
        blocks = (*blocks, latch)
    views = tuple(row for row in engine.state.preflight if row.account_ref != account_ref) + (result,)
    engine._persist('preflight_recorded', replace(engine.state, preflight=views, preflight_blocks=blocks, stopped=engine.state.stopped or result.blocked_today))
    return result


def preview_preflight(engine: 'TradingEngine', account_ref: str, facts: PreflightFacts) -> PreflightView:
    """The checklist as it reads right now, for display only.

    Unlike record_preflight this writes nothing: no new version, no stop, and above all no same-day latch, which a
    failing record can never undo. The real record is made by the owner's click or by the daily admission itself.
    """
    if account_ref not in engine.gateways:
        raise DomainError('capability_missing')
    return build_preflight(account_ref, engine.state.trading_day, engine.clock.now(), engine.configuration.environment, facts)


def assert_preflight(engine: 'TradingEngine', account_ref: str) -> None:
    day = engine.state.trading_day
    result = next((row for row in engine.state.preflight if row.account_ref == account_ref and row.trade_date == day), None)
    if result is None or result.blocked_today or (account_ref, day) in engine.state.preflight_blocks:
        raise DomainError('preflight_blocked', 'this day has no passed preflight')


def engine_preflight_facts(engine: 'TradingEngine', account_ref: str, *, quote_source: str | None = None) -> PreflightFacts:
    """Read trusted generic-port facts; unified sessions supply their own proof."""
    from .state import ACTIVE
    from quantlab.trading.domain.freshness import LiveMarketSettings

    if account_ref not in engine.gateways:
        raise DomainError('capability_missing')
    now = engine.clock.now()
    capability = engine.gateways[account_ref].inspect(account_ref)
    current = capability.checked_at <= now < capability.expires_at
    selected = capability.account_ref == account_ref and capability.environment is engine.configuration.environment
    instruments = {lot.instrument_id for lot in engine.state.positions if lot.account_ref == account_ref and lot.quantity}
    typed = False
    for row in engine.state.strategies:
        if row.form.account_ref != account_ref or row.state in ('DELETED', 'RETIRED', 'DISABLED'):
            continue
        instrument = row.form.instrument_id
        if row.parameters is not None:
            typed = True
            if row.parameters.instrument_rule == 'TMF_NEAR':
                from quantlab.trading.domain.strategy import resolve_tmf_near

                instrument = resolve_tmf_near(engine.catalog.instruments, engine.calendar, engine.state.trading_day).instrument_id
        instruments.add(instrument)
    if not instruments:
        first = next(
            (
                spec
                for spec in engine.catalog.instruments
                if spec.market in capability.markets and spec.effective_at <= now and (spec.expiry is None or spec.expiry >= engine.state.trading_day)
            ),
            None,
        )
        if first is not None:
            instruments.add(first.instrument_id)
    delay = LiveMarketSettings.delayed_seconds
    realtime = bool(instruments) and all(
        (quote := engine.quotes.get(instrument)) is not None
        and quote.quality == 'VERIFIED'
        and (quote_source is None or quote.source == quote_source)
        and 0 <= (now - quote.source_at).total_seconds() <= delay
        and 0 <= (now - quote.received_at).total_seconds() <= delay
        for instrument in instruments
    )
    try:
        if typed and engine.configuration.environment is Environment.BROKER_SIMULATION:
            from quantlab.trading.domain.automatic_calendar import calendar_for_instrument

            service = bool(instruments) and all(
                calendar_for_instrument(engine.calendar, engine.catalog.resolve(instrument)).session_at(now).kind == 'DAY' for instrument in instruments
            )
        else:
            session = engine.calendar.session_at(now)
            service = session.kind == 'DAY'
    except DomainError as error:
        if error.code not in ('session_closed', 'calendar_missing'):
            raise
        service = False
    uncertain = any(order.status in ACTIVE and order.status.value in ('SUBMITTING', 'UNKNOWN', 'CANCEL_PENDING') for order in engine.state.orders)
    reconciled = engine.state.reconciled and not engine.state.reconciliation and not uncertain
    return PreflightFacts(
        current and capability.can_query,
        current and selected,
        current and selected and capability.can_trade,
        capability.ca_ready if engine.configuration.environment is Environment.LIVE else None,
        realtime,
        service,
        reconciled,
    )
