"""Watch-only subscriptions and durable chart queries, independent of execution."""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from threading import RLock
from typing import Callable
from zoneinfo import ZoneInfo

from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import LiveBar, MinuteState, aggregate_bars, compose_minute, finalize_minute
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind
from quantlab.trading.ports.history import HistoryUsage, KlineStorePort, MarketSessionPort
from .contracts import MarketSeriesPage, MarketSeriesQuery, MarketWatchView, OverviewMarketSummary
from .history_sync import HistorySync, HistorySyncState
from .market_terminal_views import watch_view

_TAIPEI = ZoneInfo('Asia/Taipei')


@dataclass(frozen=True)
class MarketTerminalStatus:
    connected: bool
    subscription_count: int
    subscription_limit: int
    temporary_id: str
    usage: HistoryUsage | None
    history_state: HistorySyncState
    warning_code: str = ''


class MarketTerminalService:
    def __init__(
        self,
        store: KlineStorePort,
        history: HistorySync,
        session: MarketSessionPort,
        directory: Callable[[], tuple[WatchInstrument, ...]],
        *,
        watchlist: tuple[str, ...] = (),
        selected: str = 'INDEX:IX0001',
        save_watchlist: Callable[[tuple[str, ...]], None] = lambda value: None,
        save_selected: Callable[[str], None] = lambda value: None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        settings: LiveMarketSettings = LiveMarketSettings(),
        warning_code: Callable[[], str] = lambda: '',
    ):
        self.store, self.history, self.session = store, history, session
        self.directory = directory
        self.watchlist, self.selected = watchlist, selected
        self.save_watchlist, self.save_selected = save_watchlist, save_selected
        self.now, self.settings = now, settings
        self.warning_code = warning_code
        self.lock = RLock()
        self.subscriptions: dict[str, WatchInstrument] = {}
        self.temporary_id = ''
        self.active = False
        self._has_connected = False
        self._last_connected = False
        self._await_tick: set[str] = set()
        self._ticks: dict[str, Tick] = {}
        self._minutes: dict[str, MinuteState] = {}
        self._live: dict[str, tuple[LiveBar, ...]] = {}
        self._revision = 0
        self._pages: dict[tuple[str, str], tuple[int, tuple[LiveBar, ...]]] = {}
        self._view_bars: dict[str, tuple[int, tuple[LiveBar, ...]]] = {}
        self.on_tick: Callable[[Tick, tuple[LiveBar, ...]], None] = lambda tick, bars: None
        self.on_bars: Callable[[str, tuple[LiveBar, ...], datetime, date], None] = lambda key, bars, now, day: None

    def _all_instruments(self) -> dict[str, WatchInstrument]:
        items = {item.instrument_id: item for item in (*FIXED_INDICES, *self.directory())}
        for key in self.store.instrument_ids():
            prefix, _, code = key.partition(':')
            exchange = {'TWSE': 'TSE', 'TPEX': 'OTC', 'INDEX': 'INDEX'}.get(prefix)
            if key not in items and exchange is not None:
                items[key] = WatchInstrument(key, WatchKind.INDEX if prefix == 'INDEX' else WatchKind.STOCK, exchange, code, code)
        return items

    def instruments(self) -> tuple[WatchInstrument, ...]:
        items = self._all_instruments()
        if self.session.connected:
            return tuple(items.values())
        cached = set(self.store.instrument_ids())
        fixed = {item.instrument_id for item in FIXED_INDICES}
        return tuple(item for key, item in items.items() if key in cached | fixed)

    def resolve(self, instrument_id: str) -> WatchInstrument:
        item = self._all_instruments().get(instrument_id)
        if item is None:
            raise DomainError('symbol_not_found')
        return item

    def connected(self) -> None:
        with self.lock:
            self.active = True
            self.subscriptions.clear()
            self.temporary_id = ''
            for key in (*[item.instrument_id for item in FIXED_INDICES], *self.watchlist):
                self._subscribe(self.resolve(key))
            main = self.resolve(self.selected)
            if main.instrument_id not in self.subscriptions:
                self._temporary(main)
            if self._has_connected:
                self.history.reconnected(tuple(self.subscriptions.values()))
            else:
                self.history.connected(FIXED_INDICES, tuple(self.resolve(key) for key in self.watchlist), main)
            self._has_connected = self._last_connected = True
            self._revision += 1

    def disconnected(self) -> None:
        with self.lock:
            self.history.disconnected()
            self._last_connected = False
            self._await_tick.update(self._ticks)
            self._minutes = {key: replace(state, bar=replace(state.bar, incomplete=True)) for key, state in self._minutes.items()}
            self.subscriptions.clear()
            self.temporary_id = ''
            self._revision += 1

    def _subscribe(self, item: WatchInstrument) -> bool:
        if item.instrument_id in self.subscriptions:
            return True
        if len(self.subscriptions) >= self.settings.subscription_limit:
            return False
        self.session.subscribe(item)
        self.subscriptions[item.instrument_id] = item
        return True

    def _temporary(self, item: WatchInstrument) -> bool:
        if item.instrument_id in self.subscriptions:
            return True
        if self._subscribe(item):
            self.temporary_id = item.instrument_id
            return True
        return False

    def select(self, instrument_id: str, period: str = '1m') -> bool:
        MarketSeriesQuery(instrument_id, period)
        item = self.resolve(instrument_id)
        with self.lock:
            if self.temporary_id and self.temporary_id != instrument_id:
                self.session.unsubscribe(self.temporary_id)
                self.subscriptions.pop(self.temporary_id, None)
                self.temporary_id = ''
            self.save_selected(instrument_id)
            self.selected = instrument_id
            live = self._temporary(item) if self.session.connected else False
            if self.session.connected:
                self.history.browse(item, period, instrument_id in self.watchlist)
            return live

    def set_watchlist(self, requested: tuple[str, ...]) -> None:
        if len(set(requested)) != len(requested) or any(key in {item.instrument_id for item in FIXED_INDICES} for key in requested):
            raise DomainError('validation_failed', 'watchlist identities')
        instruments = tuple(self.resolve(key) for key in requested)
        temporary = int(self.selected not in requested and self.selected not in {item.instrument_id for item in FIXED_INDICES})
        if len(requested) + len(FIXED_INDICES) + temporary > self.settings.subscription_limit:
            raise DomainError('subscription_limit_reached')
        with self.lock:
            self.save_watchlist(requested)
            removed = set(self.watchlist) - set(requested)
            added = set(requested) - set(self.watchlist)
            self.watchlist = requested
            for key in removed:
                self.history.watch_removed(key)
                if key == self.selected:
                    self.temporary_id = key if key in self.subscriptions else ''
                elif key in self.subscriptions:
                    self.session.unsubscribe(key)
                    self.subscriptions.pop(key)
            if self.temporary_id in requested:
                self.temporary_id = ''
            if self.session.connected:
                for item in instruments:
                    self._subscribe(item)
                    if item.instrument_id in added:
                        self.history.watch_added(item)
            self._revision += 1

    def poll(self) -> None:
        if not self.session.connected:
            if self._last_connected:
                self.disconnected()
            return
        with self.lock:
            self.history.resume_if_new_day()
            lost = {item.instrument_id for item in self.session.drain_tick_losses()}
            for tick in self.session.drain_ticks(self.settings.queue_limit):
                self._accept(tick, tick.instrument_id in lost)
            now = self.now()
            for key, state in tuple(self._minutes.items()):
                final = finalize_minute(state, now=now)
                if final.bar.final and not state.bar.final:
                    self._minutes[key] = final
                    self._retain((final.bar,))
                    self.on_bars(key, self._live.get(key, ()), now, final.bar.trade_date)
            instruments = tuple(self.subscriptions[key] for key in self.subscriptions if key != self.temporary_id)
            today = now.astimezone(_TAIPEI).date()
            trading_day = any(tick.trade_date == today for tick in self._ticks.values())
            if not trading_day:
                trading_day = any((last := self.store.last_bar(item.instrument_id)) is not None and last.trade_date == today for item in instruments)
            self.history.after_close(instruments, trading_day=trading_day)

    def _accept(self, tick: Tick, incomplete: bool) -> None:
        if tick.instrument_id not in self.subscriptions:
            return
        update = compose_minute(self._minutes.get(tick.instrument_id), tick, incomplete=incomplete)
        self._minutes[tick.instrument_id] = update.state
        if not update.accepted:
            return
        self._await_tick.discard(tick.instrument_id)
        prior = self._ticks.get(tick.instrument_id)
        if prior is None or tick.source_at >= prior.source_at:
            self._ticks[tick.instrument_id] = tick
        self._retain(update.finalized)
        self._revision += 1
        self.on_tick(tick, (*self._live.get(tick.instrument_id, ()), update.state.bar))

    def _retain(self, bars: tuple[LiveBar, ...]) -> None:
        for bar in bars:
            if bar.incomplete:
                continue
            self.store.upsert((bar,), source='LIVE_TICKS')
            retained = self._live.get(bar.instrument_id, ())
            cutoff = self.now() - timedelta(days=self.settings.buffer_trade_days)
            self._live[bar.instrument_id] = tuple(item for item in (*retained, bar) if item.start >= cutoff)
            self._revision += 1

    def series(self, query: MarketSeriesQuery) -> MarketSeriesPage:
        item = self.resolve(query.instrument_id)
        with self.lock:
            if query.retry_history and self.session.connected:
                self.history.refresh(item, query.period, item.instrument_id in self.watchlist)
            if query.limit > self.settings.series_page_limit:
                raise DomainError('validation_failed', 'series page limit')
            key = query.instrument_id, query.period
            if query.offset:
                cached = self._pages.get(key)
                if cached is None or query.market_revision != cached[0]:
                    raise DomainError('state_conflict', 'chart page revision changed')
                revision, bars = cached
            else:
                now = self.now()
                start = now - timedelta(days=self.history.settings.daily_lookback_days)
                persisted = self.store.read(query.instrument_id, start, now)
                current = self._minutes.get(query.instrument_id)
                merged = {bar.start: bar for bar in persisted}
                if current is not None and not current.bar.final and current.bar.start not in merged:
                    merged[current.bar.start] = current.bar
                bars = tuple(sorted(merged.values(), key=lambda bar: bar.start))
                if query.period != '1m':
                    if query.period == '1d':
                        groups: dict[object, list[LiveBar]] = {}
                        for bar in bars:
                            groups.setdefault(bar.trade_date, []).append(bar)
                        local = now.astimezone(_TAIPEI)
                        bars = tuple(
                            result
                            for day, members in groups.items()
                            for result in aggregate_bars(
                                tuple(members), '1d', now=now, trade_date_closed=day < local.date() or day == local.date() and local.time() >= time(13, 30)
                            )
                        )
                    else:
                        bars = aggregate_bars(bars, query.period, now=now)
                revision = self.market_revision
                self._pages[key] = revision, bars
            limit = min(query.limit, self.settings.series_page_limit)
            stop = query.offset + limit
            return MarketSeriesPage(
                query.instrument_id,
                query.period,
                bars[query.offset : stop],
                offset=query.offset,
                total=len(bars),
                next_offset=stop if stop < len(bars) else None,
                market_revision=revision,
            )

    def views(self) -> tuple[MarketWatchView, ...]:
        with self.lock:
            history = self.history.state()
            errors = dict(history.history_error)
            keys = tuple(dict.fromkeys((*[item.instrument_id for item in FIXED_INDICES], *self.watchlist, self.selected)))
            result = []
            now = self.now()
            for key in keys:
                cached = self._view_bars.get(key)
                if cached is None or cached[0] != self.store.revision:
                    cached = self.store.revision, self.store.read(key, now - timedelta(days=30), now)
                    self._view_bars[key] = cached
                details = self.session.quote_details(key)
                view = watch_view(
                    key,
                    self._ticks.get(key),
                    cached[1],
                    now,
                    self.session.connected and key not in self._await_tick,
                    self.settings,
                    errors.get(key, ''),
                    details,
                )
                if key in self._minutes and self._minutes[key].bar.incomplete:
                    view = replace(view, health=replace(view.health, incomplete=True))
                result.append(view)
            return tuple(result)

    @property
    def market_revision(self) -> int:
        return self._revision + self.store.revision

    def health(self, views: tuple[MarketWatchView, ...]) -> OverviewMarketSummary:
        return OverviewMarketSummary(
            tuple(view.health for view in views),
            len(self.subscriptions),
            self.settings.subscription_limit,
            self.market_revision,
            any(view.health.freshness != 'LIVE' for view in views),
        )

    def status(self) -> MarketTerminalStatus:
        state = self.history.state()
        return MarketTerminalStatus(
            self.session.connected, len(self.subscriptions), self.settings.subscription_limit, self.temporary_id, state.usage, state, self.warning_code()
        )
