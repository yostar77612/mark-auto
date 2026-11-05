"""Bounded daily projections; the append-only journal retains the full audit trail."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from quantlab.trading.domain.auto_cycle import evaluation_key_matches
from quantlab.trading.domain.models import Environment, OrderStatus

DAILY_RETENTION_TRADE_DAYS = 20
BROKER_TERMINAL = frozenset((OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED))
INTENT_TERMINAL = frozenset(('DISPATCHED', 'KNOWN_NO_ORDER', 'EXPIRED', 'INVALIDATED'))


@dataclass(frozen=True)
class DailyCloseArchive:
    account_ref: str
    trade_date: date
    as_of: datetime
    net_pnl: Decimal
    ledger_fingerprint: str
    order_digest: str
    order_count: int
    fee_fingerprint: str
    invalidated: bool = False


def order_digest(engine, account_ref: str, as_of: datetime) -> tuple[str, int]:
    """Financial order identity through one close, independent of tuple ordering."""
    from .daily_closes import _hash, _order_fingerprint

    rows = tuple(
        sorted(
            (order.order_id, _order_fingerprint(engine, order))
            for order in engine.state.orders
            if order.plan.account_ref == account_ref and order.plan.decision_at <= as_of
        )
    )
    return _hash(rows), len(rows)


def archive_changed(engine, archive: DailyCloseArchive) -> bool:
    """Old late fills/fees/new backdated orders remain visible after row pruning."""
    from .sessions import fee_fingerprint

    return archive.fee_fingerprint != fee_fingerprint(engine.fees) or order_digest(engine, archive.account_ref, archive.as_of) != (
        archive.order_digest,
        archive.order_count,
    )


def invalidate_daily_projection(state, keys):
    """Financial evidence failure preserves the old authority and revokes the run."""
    from .automatic_state import pause

    return replace(
        state,
        daily_account_closes=tuple(replace(row, invalidated=True) if (row.account_ref, row.trade_date) in keys else row for row in state.daily_account_closes),
        daily_close_archives=tuple(replace(row, invalidated=True) if (row.account_ref, row.trade_date) in keys else row for row in state.daily_close_archives),
        automatic=pause(state.automatic, 'daily_close_unverified'),
        stopped=True,
        issues=tuple(sorted(set((*state.issues, 'daily_close_unverified')))),
    )


def compact_daily_projection(engine, state):
    """Pure startup/controller projection; a closed saved engine needs no first write."""
    from .auto_strategy_service import compact_auto_projection

    # The auto-strategy tuples are bounded in every environment and are also the
    # migration path for journals written before they were compacted.
    return compact_auto_projection(_compact_daily_projection(engine, state))


def _compact_daily_projection(engine, state):
    from .daily_closes import _changed, _hash

    if engine.configuration.environment is not Environment.BROKER_SIMULATION:
        return state
    current = SimpleNamespace(state=state, catalog=engine.catalog, fees=engine.fees)
    changed = {(row.account_ref, row.trade_date) for row in state.daily_close_archives if not row.invalidated and archive_changed(current, row)}
    changed.update((row.account_ref, row.trade_date) for row in state.daily_account_closes if not row.invalidated and _changed(current, row))
    if changed:
        return invalidate_daily_projection(state, changed)
    days = tuple(row.trade_date for row in engine.calendar.sessions if row.kind == 'DAY')
    if state.trading_day not in days:
        return state  # Missing coverage never invents a trading-day retention age.
    elapsed = days[: days.index(state.trading_day) + 1]
    if len(elapsed) <= DAILY_RETENTION_TRADE_DAYS:
        return state
    cutoff = elapsed[-DAILY_RETENTION_TRADE_DAYS]
    verified = frozenset(elapsed)
    orders = {row.order_id: row for row in state.orders}
    invalidated_accounts = {row.account_ref for row in state.daily_close_archives if row.invalidated}
    removed = []
    retained = []
    for close in state.daily_account_closes:
        prefix = tuple(row for row in state.orders if row.plan.account_ref == close.account_ref and row.plan.decision_at <= close.as_of)
        if (
            close.trade_date in verified
            and close.trade_date < cutoff
            and close.consumed_on is not None
            and not close.invalidated
            and close.account_ref not in invalidated_accounts
            and all(row.status in BROKER_TERMINAL for row in prefix)
        ):
            removed.append(close)
        else:
            retained.append(close)

    archives = {row.account_ref: row for row in state.daily_close_archives}
    for close in sorted(removed, key=lambda row: row.as_of):
        prior = archives.get(close.account_ref)
        if prior is None or close.as_of > prior.as_of:
            digest = close.order_digest or _hash(tuple(sorted(close.order_fingerprints)))
            count = close.order_count if close.order_digest else len(close.order_fingerprints)
            archives[close.account_ref] = DailyCloseArchive(
                close.account_ref,
                close.trade_date,
                close.as_of,
                close.net_pnl,
                close.ledger_fingerprint,
                digest,
                count,
                close.fee_fingerprint,
            )
    removed_keys = {(row.account_ref, row.trade_date) for row in removed}
    quotes = tuple(row for row in state.daily_closing_quotes if (row.account_ref, row.trade_date) not in removed_keys)
    now = engine.clock.now()
    intents = []
    for intent in state.automatic.daily.intents:
        associated = tuple(row for row in state.orders if evaluation_key_matches(row.key, intent.cursor) or intent.order_id and row.order_id == intent.order_id)
        safe_orders = all(row.status in BROKER_TERMINAL for row in associated)
        canonical_present = (intent.phase != 'DISPATCHED' or bool(intent.order_id)) and (not intent.order_id or intent.order_id in orders)
        if not (
            intent.target_trade_date in verified
            and intent.target_trade_date < cutoff
            and now >= intent.deadline
            and intent.phase in INTENT_TERMINAL
            and safe_orders
            and canonical_present
        ):
            intents.append(intent)
    daily = replace(state.automatic.daily, intents=tuple(intents))
    proposed = replace(
        state,
        daily_account_closes=tuple(retained),
        daily_closing_quotes=quotes,
        daily_close_archives=tuple(archives[key] for key in sorted(archives)),
        automatic=replace(state.automatic, daily=daily),
    )
    return proposed


def compact_daily_state(engine) -> None:
    """One writer-held transition, without changing grants, money, orders or history."""
    with engine.lock:
        if engine.storage_failed or engine.state.engine_closed:
            return
        proposed = compact_daily_projection(engine, engine.state)
        if proposed != engine.state:
            engine._persist('daily_state_compacted', proposed)
