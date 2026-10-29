"""Pure incremental bars, aggregation and history merge; no calendar, storage or clocks.

Callers own one MinuteState per instrument and retain emitted final bars. Late
ticks in the forming minute update source-ordered OHLC; finalized minutes never
reopen. Sequence identities are scoped to source/trade date/session. No sequence
means no deduplication claim. Missing minutes are never synthesized.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from operator import attrgetter

from .ticks import Tick
from .validation import DomainError


@dataclass(frozen=True)
class LiveBar:
    instrument_id: str
    start: datetime
    end: datetime
    trade_date: date
    session: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    final: bool = False
    incomplete: bool = False


@dataclass(frozen=True)
class MinuteState:
    bar: LiveBar
    first_key: tuple[datetime, int]
    last_key: tuple[datetime, int]
    sequence_scope: tuple[str, date, str]
    seen: frozenset[int] = frozenset()
    previous_sequence: int = -1


@dataclass(frozen=True)
class TickUpdate:
    state: MinuteState
    finalized: tuple[LiveBar, ...] = ()
    accepted: bool = True


def compose_minute(state: MinuteState | None, tick: Tick, *, incomplete: bool = False) -> TickUpdate:
    """Accept one tick; return state plus the previous final bar on rollover.

    A caller can mark loss from queue overflow via incomplete. Sequence memory
    covers only the active minute, plus a high-water mark for prior minutes.
    """
    start = tick.source_at.replace(second=0, microsecond=0)
    scope = tick.source, tick.trade_date, tick.session
    key = tick.source_at, tick.sequence if tick.sequence is not None else -1
    previous_sequence = -1
    finalized: tuple[LiveBar, ...] = ()
    if state is not None:
        bar = state.bar
        if bar.instrument_id != tick.instrument_id:
            raise DomainError('validation_failed', 'one instrument per minute state')
        same_scope = scope == state.sequence_scope
        duplicate = same_scope and tick.sequence is not None and (tick.sequence in state.seen or tick.sequence <= state.previous_sequence)
        if duplicate:
            return TickUpdate(replace(state, bar=replace(bar, incomplete=bar.incomplete or incomplete)), accepted=False)
        if start < bar.start or start == bar.start and bar.final:
            return TickUpdate(replace(state, bar=replace(bar, incomplete=True)), accepted=False)
        if start == bar.start:
            if not same_scope:
                raise DomainError('validation_failed', 'conflicting minute session/source')
            updated = replace(
                bar,
                open=tick.price if key < state.first_key else bar.open,
                high=max(bar.high, tick.price),
                low=min(bar.low, tick.price),
                close=tick.price if key >= state.last_key else bar.close,
                volume=bar.volume + tick.volume,
                incomplete=bar.incomplete or incomplete,
            )
            seen = state.seen | {tick.sequence} if tick.sequence is not None else state.seen
            return TickUpdate(replace(state, bar=updated, first_key=min(key, state.first_key), last_key=max(key, state.last_key), seen=seen))
        finalized = () if bar.final else (replace(bar, final=True),)
        incomplete = incomplete or same_scope and start > bar.end
        if same_scope:
            previous_sequence = max(state.seen, default=state.previous_sequence)
    bar = LiveBar(
        tick.instrument_id,
        start,
        start + timedelta(minutes=1),
        tick.trade_date,
        tick.session,
        tick.price,
        tick.price,
        tick.price,
        tick.price,
        tick.volume,
        incomplete=incomplete,
    )
    return TickUpdate(MinuteState(bar, key, key, scope, frozenset() if tick.sequence is None else frozenset({tick.sequence}), previous_sequence), finalized)


def finalize_minute(state: MinuteState, *, now: datetime) -> MinuteState:
    """Close an elapsed minute without needing another tick; now is explicit."""
    return replace(state, bar=replace(state.bar, final=True)) if now >= state.bar.end else state


def aggregate_bars(bars: tuple[LiveBar, ...], period: str, *, now: datetime, trade_date_closed: bool = False) -> tuple[LiveBar, ...]:
    """Aggregate a single instrument's 1m bars on wall-clock interval boundaries.

    Intraday buckets never cross session/trade-date boundaries. Daily buckets
    combine all sessions of the resolver's trade date; only the caller can
    declare that trade date closed. Session breaks are not inferred as loss.
    """
    periods = {'3m': 3, '5m': 5, '15m': 15, '30m': 30, '60m': 60, '1d': 1440}
    if period not in periods:
        raise DomainError('validation_failed', 'unsupported live bar period')
    minutes = periods[period]

    def bucket(bar: LiveBar) -> tuple[str, date, str, datetime | None]:
        if period == '1d':
            return bar.instrument_id, bar.trade_date, '', None
        start = bar.start.replace(minute=0) + timedelta(minutes=bar.start.minute // minutes * minutes)
        return bar.instrument_id, bar.trade_date, bar.session, start

    groups: dict[tuple[str, date, str, datetime | None], list[LiveBar]] = {}
    for bar in sorted(bars, key=lambda bar: bar.start):
        groups.setdefault(bucket(bar), []).append(bar)
    result = []
    for (_, day, session, start), members in groups.items():
        first, last = members[0], members[-1]
        end = last.end if period == '1d' else start + timedelta(minutes=minutes)
        final = all(bar.final for bar in members) and (trade_date_closed if period == '1d' else now >= end)
        result.append(
            LiveBar(
                first.instrument_id,
                first.start if start is None else start,
                end,
                day,
                session or 'ALL',
                first.open,
                max(bar.high for bar in members),
                min(bar.low for bar in members),
                last.close,
                sum(bar.volume for bar in members),
                final,
                any(bar.incomplete for bar in members),
            )
        )
    return tuple(sorted(result, key=lambda bar: bar.start))


@dataclass(frozen=True)
class DataGap:
    start: datetime
    end: datetime


def recover_data_gaps(gaps: tuple[DataGap, ...], start: datetime, end: datetime) -> tuple[DataGap, ...]:
    """Subtract a successfully recovered interval, retaining uncovered pieces."""
    return tuple(piece for gap in gaps for piece in (DataGap(gap.start, min(gap.end, start)), DataGap(max(gap.start, end), gap.end)) if piece.start < piece.end)


_START = attrgetter('start')


@dataclass(frozen=True)
class MergedBars:
    bars: tuple[LiveBar, ...]
    gaps: tuple[DataGap, ...] = ()


def merge_history_live(history: tuple[LiveBar, ...], live: tuple[LiveBar, ...], *, recover_suffix: bool = False) -> MergedBars:
    """Live owns its suffix, except explicitly recovered disconnected minutes.

    Recovery retains history inside the suffix with live winning on overlap.
    Record a discontinuity without interpolation; missing bars stay missing.
    """
    ordered_live = tuple(sorted(live, key=_START))
    merged = join_history_live(history_before(history, ordered_live[0].start if ordered_live else None), ordered_live)
    if recover_suffix:
        by_start = {bar.start: bar for bar in (*history, *ordered_live)}
        return MergedBars(tuple(sorted(by_start.values(), key=_START)), merged.gaps)
    return merged


def history_before(history: tuple[LiveBar, ...], start: datetime | None) -> tuple[LiveBar, ...]:
    """History ordered by start and cut before the live suffix; callers may cache it."""
    return tuple(sorted((bar for bar in history if start is None or bar.start < start), key=_START))


def join_history_live(retained: tuple[LiveBar, ...], ordered_live: tuple[LiveBar, ...]) -> MergedBars:
    """Join history_before output with start-ordered live bars, recording a discontinuity."""
    gaps = ()
    if retained and ordered_live and retained[-1].end < ordered_live[0].start:
        gaps = (DataGap(retained[-1].end, ordered_live[0].start),)
    return MergedBars(retained + ordered_live, gaps)
