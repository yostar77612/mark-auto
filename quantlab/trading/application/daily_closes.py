"""Captured application-ledger closing facts, separate from broker fund reports."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import TYPE_CHECKING

from .codec import dumps
from .performance import liquidation_value
from .sessions import DailyBaselineEvidence, fee_fingerprint
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar, calendar_for_instrument
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, Market, OrderStatus, Quote
from quantlab.trading.domain.strategy import is_tmf
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine

SOURCE_ID = 'APP_VERIFIED_DAY_CLOSE_V1'
ZERO = Decimal('0')
TERMINAL = frozenset((OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED))


@dataclass(frozen=True)
class ClosingQuote:
    account_ref: str
    trade_date: date
    session_close_at: datetime
    quote: Quote
    bar: LiveBar
    scope_fingerprint: str


@dataclass(frozen=True)
class DailyAccountClose:
    account_ref: str
    trade_date: date
    as_of: datetime
    captured_at: datetime
    net_pnl: Decimal
    closing_quotes: tuple[ClosingQuote, ...]
    ledger_fingerprint: str
    order_fingerprints: tuple[tuple[str, str], ...]
    calendar_id: str
    calendar_version: str
    fee_fingerprint: str
    source_id: str = 'APP_VERIFIED_DAY_CLOSE_V1'
    consumed_on: date | None = None
    invalidated: bool = False
    closing_quote_refs: tuple[str, ...] = ()
    order_digest: str = ''
    order_count: int = 0


def _assert_provider(engine):
    engine.assert_execution_allowed()
    if engine.configuration.environment is not Environment.BROKER_SIMULATION or engine.storage_failed or engine.state.engine_closed:
        raise DomainError('capability_missing', 'healthy broker simulation ledger required')


def _supported(engine, market=None):
    return tuple(spec for spec in engine.catalog.instruments if (spec.market is Market.STOCK or is_tmf(spec)) and (market is None or spec.market is market))


def _account_calendar(engine, reference):
    from .manual_book import CAPACITY_SOURCE, manual_market

    books = tuple(book for book in engine.state.manual_books if book.account_ref == reference)
    if len(books) != 1 or books[0].source != CAPACITY_SOURCE:
        raise DomainError('manual_book_not_enabled')
    return automatic_day_calendar(engine.calendar, _supported(engine, manual_market(engine, reference)))


def _hash(value):
    return sha256(dumps(value).encode()).hexdigest()


def _order_fingerprint(engine, order):
    spec = engine.catalog.resolve(order.plan.instrument_id)
    grid = (spec.market, spec.multiplier, spec.unit, spec.lot_size, spec.tick_size, spec.price_bands, spec.tick_rule_id)
    return _hash((order.plan, order.filled, order.average_price, order.costs, grid))


def _financial_fingerprint(engine, reference, instrument_id=None):
    lots = tuple(
        (lot.lot_id, lot.instrument_id, lot.quantity, lot.entry_price, lot.realized_pnl, lot.direction)
        for lot in engine.state.positions
        if lot.account_ref == reference and (instrument_id is None or lot.instrument_id == instrument_id)
    )
    orders = tuple(
        (order.order_id, _order_fingerprint(engine, order))
        for order in engine.state.orders
        if order.plan.account_ref == reference and (instrument_id is None or order.plan.instrument_id == instrument_id)
    )
    return _hash((lots, orders, fee_fingerprint(engine.fees)))


def _changed(engine, close):
    if close.fee_fingerprint != fee_fingerprint(engine.fees):
        return True
    if close.order_digest:
        from .daily_retention import order_digest

        if order_digest(engine, close.account_ref, close.as_of) != (close.order_digest, close.order_count):
            return True
        return close.consumed_on is None and close.ledger_fingerprint != _financial_fingerprint(engine, close.account_ref)
    previous = dict(close.order_fingerprints)
    current = {order.order_id: order for order in engine.state.orders if order.plan.account_ref == close.account_ref}
    if any(order_id not in current or _order_fingerprint(engine, current[order_id]) != fingerprint for order_id, fingerprint in previous.items()):
        return True
    if any(order_id not in previous and order.plan.decision_at <= close.as_of for order_id, order in current.items()):
        return True
    return close.consumed_on is None and close.ledger_fingerprint != _financial_fingerprint(engine, close.account_ref)


def _invalidate(engine, keys):
    from .daily_retention import invalidate_daily_projection

    proposed = invalidate_daily_projection(engine.state, keys)
    if proposed != engine.state:
        engine._persist('daily_close_invalidated', proposed)


def _freeze_quotes(engine, reference, bars):
    now = engine.clock.now()
    rows = engine.state.daily_closing_quotes
    for bar in bars:
        spec = engine.catalog.resolve(bar.instrument_id)
        from .manual_book import manual_market

        if spec.market is not manual_market(engine, reference):
            continue
        session = calendar_for_instrument(engine.calendar, spec).day_session(bar.trade_date)
        if not bar.final or bar.incomplete or bar.session != 'DAY' or bar.start != session.opens_at or bar.end != session.closes_at or now < bar.end:
            continue
        existing = next(
            (row for row in rows if (row.account_ref, row.trade_date, row.quote.instrument_id) == (reference, bar.trade_date, bar.instrument_id)), None
        )
        if existing is not None:
            if existing.bar != bar:
                _invalidate(engine, {(reference, bar.trade_date)})
            continue
        quote = engine.quotes.get(bar.instrument_id)
        delay = LiveMarketSettings.delayed_seconds
        if (
            quote is None
            or quote.quality != 'VERIFIED'
            or quote.source != 'SHIOAJI'
            or quote.session != 'DAY'
            or quote.trade_date != bar.trade_date
            or not 0 <= (now - quote.source_at).total_seconds() <= delay
            or not 0 <= (now - quote.received_at).total_seconds() <= delay
            or quote.source_at > session.closes_at
        ):
            continue
        row = ClosingQuote(reference, bar.trade_date, session.closes_at, quote, bar, _financial_fingerprint(engine, reference, bar.instrument_id))
        rows = (*rows, row)
    if rows != engine.state.daily_closing_quotes:
        engine._persist('daily_closing_quotes_captured', replace(engine.state, daily_closing_quotes=rows))


@decimal_operation
def _seal_account(engine, reference, day, calendar):
    if 'daily_close_unverified' in engine.state.issues:
        return  # An invalidated candidate cannot be silently recaptured later.
    if any((row.account_ref, row.trade_date) == (reference, day) for row in engine.state.daily_account_closes):
        return
    session = calendar.day_session(day)
    now = engine.clock.now()
    marks = tuple(row for row in engine.state.daily_closing_quotes if (row.account_ref, row.trade_date) == (reference, day))
    if not marks and now.astimezone(session.opens_at.tzinfo).date() != day:
        return  # No next-morning PnL may become an uncaptured prior close.
    observation = engine.manual_observations[reference]
    # The shared observation guard already proves as_of <= now.
    if observation.as_of < session.closes_at:
        return  # Keep quote candidates while the normal query worker catches up.
    orders = tuple(order for order in engine.state.orders if order.plan.account_ref == reference)
    if any(order.status not in TERMINAL or order.plan.decision_at > session.closes_at for order in orders) or any(
        request.scope.account_ref == reference and not request.outcome_known for request in engine.state.manual_requests
    ):
        return
    if any(mark.scope_fingerprint != _financial_fingerprint(engine, reference, mark.quote.instrument_id) for mark in marks):
        _invalidate(engine, {(reference, day)})
        return
    quotes = {mark.quote.instrument_id: mark.quote for mark in marks}
    lots = tuple(lot for lot in engine.state.positions if lot.account_ref == reference)
    if any(lot.quantity and lot.instrument_id not in quotes for lot in lots):
        return
    pnl = sum((lot.realized_pnl for lot in lots), ZERO) - sum((order.costs for order in orders if not order.plan.reduce_only), ZERO)
    pnl += sum(
        (liquidation_value(engine.catalog.resolve(lot.instrument_id), lot, quotes[lot.instrument_id], engine.fees) for lot in lots if lot.quantity), ZERO
    )
    from .daily_retention import order_digest

    digest, count = order_digest(engine, reference, session.closes_at)
    close = DailyAccountClose(
        reference,
        day,
        session.closes_at,
        now,
        pnl,
        (),
        _financial_fingerprint(engine, reference),
        (),
        calendar.calendar_id,
        calendar.version,
        fee_fingerprint(engine.fees),
        closing_quote_refs=tuple(mark.quote.instrument_id for mark in marks),
        order_digest=digest,
        order_count=count,
    )
    engine._persist('daily_account_close_sealed', replace(engine.state, daily_account_closes=(*engine.state.daily_account_closes, close)))


def observe_daily_closes(engine: 'TradingEngine', bars: tuple[LiveBar, ...]) -> None:
    """Capture trusted quotes and app ledger closes; never query, resume or send."""
    from .automatic_capacity import assert_automatic_observation

    with engine.lock:
        _assert_provider(engine)
        from .daily_retention import compact_daily_state

        compact_daily_state(engine)
        guard = getattr(engine, 'automatic_submission_guard', None)
        if not callable(guard):
            raise DomainError('capability_missing', 'current owner read guard required')
        for reference in sorted(engine.gateways):
            with guard(reference, reduce_only=True):
                assert_automatic_observation(engine, reference)
                calendar = _account_calendar(engine, reference)
                _freeze_quotes(engine, reference, bars)
                days = {engine.state.trading_day} | {row.trade_date for row in engine.state.daily_closing_quotes if row.account_ref == reference}
                for day in sorted(days):
                    _seal_account(engine, reference, day, calendar)


def daily_close_evidence(engine: 'TradingEngine', target_day: date) -> DailyBaselineEvidence:
    """Read sealed facts only. Root confirms the evidence and marks consumption."""
    with engine.lock:
        _assert_provider(engine)
        calendar = automatic_day_calendar(engine.calendar, _supported(engine))
        index = calendar.index(target_day)
        if index == 0:
            raise DomainError('daily_close_unverified', 'no prior verified DAY')
        previous = calendar.days[index - 1]
        closes = []
        for reference in sorted(engine.gateways):
            close = next((row for row in engine.state.daily_account_closes if (row.account_ref, row.trade_date) == (reference, previous)), None)
            account_calendar = _account_calendar(engine, reference)
            if (
                close is None
                or close.invalidated
                or close.source_id != SOURCE_ID
                or _changed(engine, close)
                or (close.calendar_id, close.calendar_version) != (account_calendar.calendar_id, account_calendar.version)
                or close.as_of != account_calendar.day_session(previous).closes_at
            ):
                raise DomainError('daily_close_unverified', 'each account needs an unchanged verified prior close')
            closes.append(close)
        if not closes:
            raise DomainError('daily_close_unverified', 'confirmed account closes required')
        return DailyBaselineEvidence(
            Environment.BROKER_SIMULATION,
            tuple(sorted(engine.gateways)),
            previous,
            target_day,
            calendar.calendar_id,
            calendar.version,
            engine.fees.version,
            fee_fingerprint(engine.fees),
            sum((row.net_pnl for row in closes), ZERO),
            calendar.day_session(previous).closes_at,
            SOURCE_ID,
            account_previous_close=tuple((row.account_ref, row.net_pnl) for row in closes),
        )
