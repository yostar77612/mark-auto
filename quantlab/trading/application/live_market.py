"""Coordinate live market ports and Domain functions; no SDK, threads or IO.

History and live provenance stay separate so backfill cannot overwrite the live
suffix. Each deque has a hard minute bound as well as trade-date retention.
Callers schedule poll/backfill and supply calendar-session facts explicitly.
"""

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from quantlab.trading.domain.freshness import Freshness, LiveMarketSettings, classify_freshness
from quantlab.trading.domain.live_bars import LiveBar, MergedBars, MinuteState, aggregate_bars, compose_minute, finalize_minute, merge_history_live
from quantlab.trading.domain.quote_stats import QuoteStats, TradeDateClose, quote_stats
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.ports.interfaces import Clock, MarketDataPort, SessionResolver
from .contracts import MarketWatchView, OverviewMarketSummary
from .market_views import market_watch_view, overview_market_summary


@dataclass(frozen=True)
class SubscriptionAllocation:
    active: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    error_code: str = ''


@dataclass
class _InstrumentBuffer:
    history: deque[LiveBar]
    live: deque[LiveBar]
    minute: MinuteState | None = None
    tick: Tick | None = None
    first_live_start: datetime | None = None
    history_error: str = ''
    freshness: Freshness = Freshness.UNKNOWN


class LiveMarketService:
    def __init__(self, market: MarketDataPort, clock: Clock, resolver: SessionResolver, *, settings: LiveMarketSettings = LiveMarketSettings()) -> None:
        self.market, self.clock, self.resolver, self.settings = market, clock, resolver, settings
        self.market_revision = 0
        self.allocation = SubscriptionAllocation()
        self._strategy_ids: tuple[str, ...] = ()
        self._watch_ids: tuple[str, ...] = ()
        self._subscriptions: dict[str, str] = {}
        self._buffers: dict[str, _InstrumentBuffer] = {}

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
        for key in desired:
            if key not in self._subscriptions:
                receipt = self.market.subscribe((key,))
                if not receipt.active:
                    raise DomainError('capability_missing', receipt.reason)
                self._subscriptions[key] = receipt.subscription_id
                bound = self.settings.buffer_trade_days * 24 * 60
                self._buffers[key] = _InstrumentBuffer(deque(maxlen=bound), deque(maxlen=bound))
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

    def poll(self, *, connected: bool = True, in_session: bool | None = None) -> int:
        before = self._views()
        now = self.clock.now()
        for tick in self.market.drain_ticks(self.settings.queue_limit):
            if tick.instrument_id not in self._buffers:
                continue
            buffer = self._buffers[tick.instrument_id]
            update = compose_minute(buffer.minute, tick)
            if buffer.minute is not None and buffer.minute.bar.final and update.state.bar.start > buffer.minute.bar.start:
                buffer.live.append(buffer.minute.bar)
            buffer.minute = update.state
            buffer.live.extend(update.finalized)
            if update.accepted:
                if buffer.first_live_start is None:
                    buffer.first_live_start = update.state.bar.start
                if buffer.tick is None or tick.source_at >= buffer.tick.source_at:
                    buffer.tick = tick
        for buffer in self._buffers.values():
            if buffer.minute is not None:
                buffer.minute = finalize_minute(buffer.minute, now=now)
            self._trim(buffer)
            buffer.freshness = classify_freshness(
                buffer.tick.received_at if buffer.tick else None, now=now, connected=connected, in_session=in_session, settings=self.settings
            )
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
        try:
            cursor = start
            while cursor < end:
                window_end = min(cursor + timedelta(days=30), end)
                batch = self.market.history(instrument_id, cursor, window_end)
                converted = []
                for bar in batch.bars:
                    day, session = self.resolver.session_at(instrument_id, bar.start)
                    converted.append(
                        LiveBar(instrument_id, bar.start, bar.available_at, day, session, bar.open, bar.high, bar.low, bar.close, bar.volume, final=True)
                    )
                by_start = {bar.start: bar for bar in (*buffer.history, *converted) if buffer.first_live_start is None or bar.start < buffer.first_live_start}
                buffer.history.clear()
                buffer.history.extend(sorted(by_start.values(), key=lambda bar: bar.start))
                self._trim(buffer)
                if not batch.complete:
                    raise DomainError('market_data_invalid', batch.reason)
                cursor = window_end
            buffer.history_error = ''
        except DomainError as exc:
            buffer.history_error = exc.code
        if self._views() != before:
            self.market_revision += 1

    def watch(self, instrument_id: str, *, period: str = '1m', previous_trade_date: date | None = None, trade_date_closed: bool = False) -> MarketWatchView:
        buffer = self._buffers[instrument_id]
        live = (*buffer.live, *((buffer.minute.bar,) if buffer.minute else ()))
        merged = merge_history_live(tuple(buffer.history), live)
        stats = QuoteStats(None, None, None)
        if buffer.tick is not None and previous_trade_date is not None:
            closes = tuple(TradeDateClose(bar.trade_date, bar.close, bar.start) for bar in merged.bars if bar.final)
            stats = quote_stats(buffer.tick.price, previous_trade_date, closes)
        if period != '1m':
            merged = MergedBars(aggregate_bars(merged.bars, period, now=self.clock.now(), trade_date_closed=trade_date_closed), merged.gaps)
        return market_watch_view(instrument_id, buffer.tick, merged, buffer.freshness, stats, buffer.history_error)

    def _views(self) -> tuple[MarketWatchView, ...]:
        return tuple(self.watch(key) for key in self.allocation.active)

    def overview(self) -> OverviewMarketSummary:
        return overview_market_summary(self._views(), limit=self.settings.subscription_limit, revision=self.market_revision)

    def views(self) -> tuple[MarketWatchView, ...]:
        """Expose the same immutable read models to all application consumers."""
        return self._views()
