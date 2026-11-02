"""Pure completed-bar and forced-exit timing rules; no SDK, I/O or calendar inference."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from quantlab.trading.domain.calendar import TradingSession
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import HoldingKind, Market
from quantlab.trading.domain.strategy import strategy_defaults
from quantlab.trading.domain.validation import DomainError

MINUTE = timedelta(minutes=1)
RETRY_INTERVAL = timedelta(seconds=30)
RETRY_CLOSE_BUFFER = timedelta(minutes=2)
EARLY_CLOSE_EXIT_BUFFER = timedelta(minutes=10)
TAIPEI = ZoneInfo('Asia/Taipei')


@dataclass(frozen=True)
class EvaluationCursor:
    strategy_id: str
    version: int
    instrument_id: str
    interval: str
    bar_end: datetime


def evaluation_key(cursor: EvaluationCursor) -> str:
    """Canonical UTC identity survives the wire codec's datetime normalization."""
    return f'auto:{cursor.strategy_id}:{cursor.version}:{cursor.instrument_id}:{cursor.interval}:{cursor.bar_end.astimezone(timezone.utc).isoformat()}'


def evaluation_key_matches(key: str, cursor: EvaluationCursor) -> bool:
    """Read historical timezone keys without rewriting durable order identities."""
    prefix = f'auto:{cursor.strategy_id}:{cursor.version}:{cursor.instrument_id}:{cursor.interval}:'
    if not key.startswith(prefix):
        return False
    timestamp = key[len(prefix) :].partition(':exit:')[0]
    try:
        end = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    return end.tzinfo is not None and end == cursor.bar_end


@dataclass(frozen=True)
class ForceExitWindow:
    due_at: datetime
    retry_cutoff: datetime
    closes_at: datetime


def complete_buckets(minute_bars: tuple[LiveBar, ...], interval: str, session: TradingSession, now: datetime) -> tuple[LiveBar, ...]:
    """Return complete day-session buckets, anchored to supplied session bounds.

    Equal duplicate deliveries count once. Conflicting deliveries for one minute
    make that minute unavailable. Daily bars require the entire supplied session;
    no missing minute, shortened tail or forming bar is synthesized.
    """
    if interval not in ('1m', '5m', '1d'):
        raise DomainError('validation_failed', 'automatic evaluation interval')
    if session.kind != 'DAY':
        return ()
    minutes = {}
    conflicts = set()
    for bar in minute_bars:
        key = bar.instrument_id, bar.start
        if key in minutes and minutes[key] != bar:
            conflicts.add(key)
        minutes[key] = bar
    duration = {'1m': MINUTE, '5m': MINUTE * 5, '1d': session.closes_at - session.opens_at}[interval]
    if duration % MINUTE:
        return ()
    groups = {}
    for key, bar in minutes.items():
        if key in conflicts:
            continue
        if not bar.final or bar.incomplete:
            continue
        if bar.trade_date != session.trade_date or bar.session != session.kind:
            continue
        if bar.start < session.opens_at:
            continue
        if bar.end - bar.start != MINUTE:
            continue
        start = session.opens_at + ((bar.start - session.opens_at) // duration) * duration
        groups.setdefault((bar.instrument_id, start), []).append(bar)
    result = []
    for (instrument_id, start), bars in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        ordered = sorted(bars, key=lambda bar: bar.start)
        end = start + duration
        if end > now or end > session.closes_at:
            continue
        expected = tuple(start + offset * MINUTE for offset in range(duration // MINUTE))
        if tuple(bar.start for bar in ordered) != expected:
            continue
        result.append(
            LiveBar(
                instrument_id,
                start,
                end,
                session.trade_date,
                session.kind,
                ordered[0].open,
                max(bar.high for bar in ordered),
                min(bar.low for bar in ordered),
                ordered[-1].close,
                sum(bar.volume for bar in ordered),
                final=True,
            )
        )
    return tuple(result)


def should_evaluate(cursor: EvaluationCursor | None, strategy_id: str, version: int, instrument_id: str, interval: str, bar_end: datetime) -> bool:
    """A cursor belongs to exactly one execution identity; accept only newer bars.

    The application keeps one cursor per identity and passes None for a genuinely
    new identity. Recording the cursor durably before submission belongs there.
    """
    if cursor is None:
        return True
    if (cursor.strategy_id, cursor.version, cursor.instrument_id, cursor.interval) != (strategy_id, version, instrument_id, interval):
        return False
    return bar_end > cursor.bar_end


def force_exit_window(kind: HoldingKind, market: Market, session: TradingSession) -> ForceExitWindow | None:
    """Use configured intraday time, capped at ten minutes before actual close.

    The early-close cap covers existing positions on a settlement/short session;
    it does not grant permission to enter a settlement-day position.
    """
    if kind is not HoldingKind.INTRADAY or session.kind != 'DAY':
        return None
    if market not in (Market.STOCK, Market.INDEX_FUTURE):
        raise DomainError('strategy_instrument_restricted')
    defaults = strategy_defaults(kind)
    configured = defaults.stock_exit_at if market is Market.STOCK else defaults.futures_exit_at
    configured_at = datetime.combine(session.trade_date, configured, tzinfo=TAIPEI)
    due_at = max(session.opens_at, min(configured_at, session.closes_at - EARLY_CLOSE_EXIT_BUFFER))
    return ForceExitWindow(due_at, session.closes_at - RETRY_CLOSE_BUFFER, session.closes_at)


def force_exit_due(window: ForceExitWindow, now: datetime, last_attempt_at: datetime | None = None) -> bool:
    """Timing only: caller must independently prove known outcome/cancel before retry."""
    if not window.due_at <= now <= window.retry_cutoff:
        return False
    return last_attempt_at is None or now - last_attempt_at >= RETRY_INTERVAL


def position_overdue(window: ForceExitWindow, now: datetime, remaining_quantity: int) -> bool:
    return remaining_quantity > 0 and now > window.closes_at
