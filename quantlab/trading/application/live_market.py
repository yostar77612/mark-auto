"""Coordinate live market ports and Domain functions; no SDK, threads or IO.

History and live provenance stay separate so backfill cannot overwrite the live
suffix. Each deque has a hard minute bound as well as trade-date retention.
Callers schedule poll/backfill and supply calendar-session facts explicitly.
"""

from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.freshness import Freshness, LiveMarketSettings, classify_freshness
from quantlab.trading.domain.live_bars import (
    DataGap,
    LiveBar,
    MergedBars,
    MinuteState,
    aggregate_bars,
    compose_minute,
    finalize_minute,
    merge_history_live,
    recover_data_gaps,
)
from quantlab.trading.domain.quote_stats import QuoteStats, TradeDateClose, quote_stats
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.ports.interfaces import Clock, MarketDataPort, SessionResolver
from quantlab.trading.ports.tick_stream import MarketConnectionSource, TickLoss, TickLossSource
from .contracts import MarketSeriesPage, MarketSeriesQuery, MarketWatchView, OverviewMarketSummary
from .codec import MAX_BYTES, dumps, register
from .market_views import market_watch_view, overview_market_summary

register(LiveBar)


def _affected_minute(timestamp: datetime, loss: TickLoss) -> bool:
    start = timestamp.replace(second=0, microsecond=0)
    return loss.first_source_at.replace(second=0, microsecond=0) <= start <= loss.last_source_at.replace(second=0, microsecond=0)


@dataclass(frozen=True)
class SubscriptionAllocation:
    active: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    error_code: str = ''


@dataclass
class _InstrumentBuffer:
    history: deque[LiveBar]
    live: deque[LiveBar]
    losses: deque[TickLoss]
    minute: MinuteState | None = None
    tick: Tick | None = None
    first_live_start: datetime | None = None
    history_error: str = ''
    freshness: Freshness = Freshness.UNKNOWN
    recovery: bool = False
    gaps: tuple[DataGap, ...] = ()


class LiveMarketService:
    def __init__(
        self,
        market: MarketDataPort,
        clock: Clock,
        resolver: SessionResolver,
        *,
        calendar: TradingCalendar | None = None,
        settings: LiveMarketSettings = LiveMarketSettings(),
    ) -> None:
        self.market, self.clock, self.resolver, self.settings = market, clock, resolver, settings
        self.calendar = calendar
        self.watchlist: tuple[str, ...] | None = None
        self.market_revision = 0
        self.allocation = SubscriptionAllocation()
        self._strategy_ids: tuple[str, ...] = ()
        self._watch_ids: tuple[str, ...] = ()
        self._subscriptions: dict[str, str] = {}
        self._buffers: dict[str, _InstrumentBuffer] = {}
        self._view_cache: dict[str, MarketWatchView] = {}
        self.issues: deque[TickLoss] = deque(maxlen=settings.queue_limit)
        self._loss_source = market if isinstance(market, TickLossSource) else None
        self._connection_source = market if isinstance(market, MarketConnectionSource) else None
        self._disconnected_at: datetime | None = None
        self._recovered_disconnect: datetime | None = None

    def allocate(self, strategy_ids: tuple[str, ...], watch_ids: tuple[str, ...] = ()) -> SubscriptionAllocation:
        strategies = tuple(dict.fromkeys(strategy_ids))
        watches = tuple(item for item in dict.fromkeys(watch_ids) if item not in strategies)
        limit = self.settings.subscription_limit
        if len(strategies) > limit:
            raise DomainError('capability_missing', 'strategy subscription capacity')
        desired = (strategies + watches)[:limit]
        refused = watches[limit - len(strategies) :]
        before = self.allocation
        for key in tuple(self._subscriptions):
            if key not in desired:
                self.market.unsubscribe(self._subscriptions[key])
                del self._subscriptions[key]
                del self._buffers[key]
                self._view_cache.pop(key, None)
        for key in desired:
            if key not in self._subscriptions:
                receipt = self.market.subscribe((key,))
                if not receipt.active:
                    raise DomainError('capability_missing', receipt.reason)
                self._subscriptions[key] = receipt.subscription_id
                bound = self.settings.buffer_trade_days * 24 * 60
                self._buffers.setdefault(key, _InstrumentBuffer(deque(maxlen=bound), deque(maxlen=bound), deque(maxlen=bound)))
        self._strategy_ids, self._watch_ids = strategies, watches
        self.allocation = SubscriptionAllocation(desired, refused, 'capability_missing' if refused else '')
        if self.allocation != before:
            self.market_revision += 1
        return self.allocation

    def add_watch(self, instrument_id: str) -> SubscriptionAllocation:
        if instrument_id not in self.allocation.active and len(self.allocation.active) >= self.settings.subscription_limit:
            raise DomainError('capability_missing', 'watch subscription capacity')
        return self.allocate(self._strategy_ids, (*self._watch_ids, instrument_id))

    def _trim(self, buffer: _InstrumentBuffer) -> None:
        days = {bar.trade_date for bar in (*buffer.history, *buffer.live)}
        if buffer.minute is not None:
            days.add(buffer.minute.bar.trade_date)
        retained = set(sorted(days)[-self.settings.buffer_trade_days :])
        for bars in (buffer.history, buffer.live):
            kept = tuple(bar for bar in bars if bar.trade_date in retained)
            bars.clear()
            bars.extend(kept)

    def _recover_connection(self, connected: bool, now: datetime) -> None:
        if self._connection_source is not None:
            lost_at = self._connection_source.disconnected_at
            if lost_at is not None and lost_at != self._recovered_disconnect:
                self._disconnected_at = lost_at
        if not connected:
            if self._disconnected_at is None:
                self._disconnected_at = now
            return
        if self._disconnected_at is None:
            return
        # Retain buffers; only receipt ownership is replaced. Allocation order
        # already contains strategies first and obeys the typed settings limit.
        for key in tuple(self._subscriptions):
            self.market.unsubscribe(self._subscriptions[key])
            del self._subscriptions[key]
        for key in self.allocation.active:
            receipt = self.market.subscribe((key,))
            if not receipt.active:
                raise DomainError('capability_missing', receipt.reason)
            self._subscriptions[key] = receipt.subscription_id
        for key in self.allocation.active:
            self._buffers[key].recovery = True
            if self._disconnected_at < now:
                self.backfill(key, self._disconnected_at, now)
        self._recovered_disconnect = self._disconnected_at
        self._disconnected_at = None

    def poll(self, *, connected: bool | None = None, in_session: bool | None = None) -> int:
        if connected is None:
            connected = self._connection_source.connected if self._connection_source is not None else True
        self._recover_connection(connected, self.clock.now())
        before = self._views()
        previous = {key: (buffer.minute, buffer.tick, len(buffer.live), buffer.freshness) for key, buffer in self._buffers.items()}
        now = self.clock.now()
        for tick in self.market.drain_ticks(self.settings.queue_limit):
            if tick.instrument_id not in self._buffers:
                continue
            buffer = self._buffers[tick.instrument_id]
            update = compose_minute(buffer.minute, tick, incomplete=any(_affected_minute(tick.source_at, loss) for loss in buffer.losses))
            if buffer.minute is not None and buffer.minute.bar.final and update.state.bar.start > buffer.minute.bar.start:
                buffer.live.append(buffer.minute.bar)
            buffer.minute = update.state
            buffer.live.extend(update.finalized)
            if update.accepted:
                if buffer.first_live_start is None:
                    buffer.first_live_start = update.state.bar.start
                if buffer.tick is None or tick.source_at >= buffer.tick.source_at:
                    buffer.tick = tick
        if self._loss_source is not None:
            for loss in self._loss_source.drain_tick_losses():
                self.issues.append(loss)
                if loss.instrument_id not in self._buffers:
                    continue
                buffer = self._buffers[loss.instrument_id]
                buffer.losses.append(loss)
                if buffer.minute is not None and _affected_minute(buffer.minute.bar.start, loss):
                    buffer.minute = replace(buffer.minute, bar=replace(buffer.minute.bar, incomplete=True))
                for bars in (buffer.history, buffer.live):
                    marked = tuple(replace(bar, incomplete=True) if _affected_minute(bar.start, loss) else bar for bar in bars)
                    bars.clear()
                    bars.extend(marked)
                self._view_cache.pop(loss.instrument_id, None)
        for key, buffer in self._buffers.items():
            if buffer.minute is not None:
                buffer.minute = finalize_minute(buffer.minute, now=now)
            session = in_session
            if session is None:
                try:
                    self.resolver.session_at(key, now)
                    session = True
                except DomainError as exc:
                    if exc.code != 'session_closed':
                        raise
                    session = False
            buffer.freshness = classify_freshness(
                buffer.tick.received_at if buffer.tick else None, now=now, connected=connected, in_session=session, settings=self.settings
            )
            if (buffer.minute, buffer.tick, len(buffer.live), buffer.freshness) != previous[key]:
                old_minute = previous[key][0]
                if buffer.minute is not None and (old_minute is None or old_minute.bar.trade_date != buffer.minute.bar.trade_date):
                    self._trim(buffer)
                self._view_cache.pop(key, None)
        if self._views() != before:
            self.market_revision += 1
        return self.market_revision

    def backfill(self, instrument_id: str, start: datetime, end: datetime) -> None:
        aware(start)
        aware(end)
        if end <= start:
            raise DomainError('validation_failed', 'history range')
        before = self._views()
        buffer = self._buffers[instrument_id]
        cursor = start
        error = ''
        while cursor < end:
            window_end = min(cursor + timedelta(days=30), end)
            try:
                batch = self.market.history(instrument_id, cursor, window_end)
                converted = []
                for bar in batch.bars:
                    day, session = self.resolver.session_at(instrument_id, bar.start)
                    converted.append(
                        LiveBar(instrument_id, bar.start, bar.available_at, day, session, bar.open, bar.high, bar.low, bar.close, bar.volume, final=True)
                    )
                by_start = {
                    bar.start: bar
                    for bar in (*buffer.history, *converted)
                    if buffer.recovery or buffer.first_live_start is None or bar.start < buffer.first_live_start
                }
                buffer.history.clear()
                buffer.history.extend(sorted(by_start.values(), key=lambda bar: bar.start))
                self._trim(buffer)
                if not batch.complete:
                    raise DomainError('market_data_invalid', batch.reason)
                buffer.gaps = recover_data_gaps(buffer.gaps, cursor, window_end)
            except DomainError as exc:
                error = exc.code
                buffer.gaps = (*buffer.gaps, DataGap(cursor, window_end))[-self.settings.buffer_trade_days * 24 * 60 :]
            cursor = window_end
        buffer.history_error = error
        self._view_cache.pop(instrument_id, None)
        if self._views() != before:
            self.market_revision += 1

    def watch(self, instrument_id: str, *, period: str = '1m', previous_trade_date: date | None = None, trade_date_closed: bool = False) -> MarketWatchView:
        buffer = self._buffers[instrument_id]
        live = (*buffer.live, *((buffer.minute.bar,) if buffer.minute else ()))
        merged = merge_history_live(tuple(buffer.history), live, recover_suffix=buffer.recovery)
        merged = MergedBars(merged.bars, tuple(dict.fromkeys((*merged.gaps, *buffer.gaps))))
        stats = QuoteStats(None, None, None)
        if buffer.tick is not None and previous_trade_date is None and self.calendar is not None:
            index = self.calendar.index(buffer.tick.trade_date)
            previous_trade_date = self.calendar.days[index - 1] if index > 0 else None
        if buffer.tick is not None and previous_trade_date is not None:
            closes = tuple(TradeDateClose(bar.trade_date, bar.close, bar.start) for bar in merged.bars if bar.final)
            stats = quote_stats(buffer.tick.price, previous_trade_date, closes)
        if period != '1m':
            merged = MergedBars(aggregate_bars(merged.bars, period, now=self.clock.now(), trade_date_closed=trade_date_closed), merged.gaps)
        return market_watch_view(instrument_id, buffer.tick, merged, buffer.freshness, stats, buffer.history_error)

    def _views(self) -> tuple[MarketWatchView, ...]:
        for key in self.allocation.active:
            if key not in self._view_cache:
                self._view_cache[key] = self.watch(key)
        return tuple(self._view_cache[key] for key in self.allocation.active)

    def overview(self) -> OverviewMarketSummary:
        return overview_market_summary(self._views(), limit=self.settings.subscription_limit, revision=self.market_revision)

    def views(self) -> tuple[MarketWatchView, ...]:
        """Publish bounded summaries; full retention is available only via series."""
        tail = self.settings.snapshot_bar_tail
        return tuple(replace(view, bars=view.bars[-tail:], gaps=view.gaps[-tail:]) for view in self._views())

    def series(self, query: MarketSeriesQuery) -> MarketSeriesPage:
        """Read one retained series, capped by count and encoded byte budget.

        Pages use ascending offsets. Pass the returned revision on subsequent
        reads; a changed market requires restarting rather than mixing pages.
        Half the wire budget leaves room for the protocol envelope and metadata.
        Domain remains the sole authority for aggregation and gap/forming facts.
        """
        if query.market_revision is not None and query.market_revision != self.market_revision:
            raise DomainError('state_conflict', 'market changed; restart series read')
        if query.instrument_id not in self._buffers:
            raise DomainError('capability_missing', 'instrument not allocated')
        if query.retry_history:
            end = self.clock.now()
            self.backfill(query.instrument_id, end - timedelta(days=30), end)
        view = self.watch(query.instrument_id, period=query.period)
        selected = []
        size = 0
        for bar in view.bars[query.offset : query.offset + min(query.limit, self.settings.series_page_limit)]:
            encoded_size = len(dumps(bar).encode('utf-8'))
            if size + encoded_size > MAX_BYTES // 2:
                if not selected:
                    raise DomainError('validation_failed', 'series bar exceeds page budget')
                break
            selected.append(bar)
            size += encoded_size
        end = query.offset + len(selected)
        return MarketSeriesPage(
            query.instrument_id,
            query.period,
            tuple(selected),
            view.gaps,
            query.offset,
            len(view.bars),
            end if end < len(view.bars) else None,
            self.market_revision,
        )
