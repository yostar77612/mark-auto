"""One background history worker with coverage, priorities and conservative quotas."""

from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from threading import Condition, Lock, Thread
from time import monotonic, sleep
from typing import Callable
from zoneinfo import ZoneInfo

from quantlab.trading.domain.validation import DomainError, aware, decimal_value, integer
from quantlab.trading.domain.watch import WatchInstrument
from quantlab.trading.ports.history import HistorySessionPort, HistoryUsage, KlineStorePort

_TAIPEI = ZoneInfo('Asia/Taipei')


@dataclass(frozen=True)
class HistorySettings:
    minute_lookback_days: int = 60
    daily_lookback_days: int = 365
    chunk_days: int = 29
    earliest: date = date(2020, 3, 2)
    quota_reserve_ratio: Decimal = Decimal('0.10')
    daily_bar_limit: int = 3_000_000

    def __post_init__(self) -> None:
        for name in ('minute_lookback_days', 'daily_lookback_days', 'chunk_days', 'daily_bar_limit'):
            integer(getattr(self, name), name, 1)
        decimal_value(self.quota_reserve_ratio, 'quota reserve')
        if self.chunk_days > 29 or self.minute_lookback_days > self.daily_lookback_days or not 0 <= self.quota_reserve_ratio < 1:
            raise DomainError('validation_failed', 'history settings range')
        if type(self.earliest) is not date or self.earliest < date(2020, 3, 2):
            raise DomainError('validation_failed', 'history earliest date')


@dataclass(frozen=True)
class HistoryRequest:
    instrument: WatchInstrument
    start: datetime
    end: datetime
    priority: int = 0
    force: bool = False
    generation: int = 0


@dataclass(frozen=True)
class HistorySyncState:
    pending: int
    running: str
    paused: bool
    quota_known: bool
    usage: HistoryUsage | None
    history_error: tuple[tuple[str, str], ...]


class HistorySync:
    """Requests are nonblocking; exactly one worker issues SDK calls.

    run_next is the deterministic offline/manual driver. An internal lock keeps it
    serialized even if a caller invokes it while the background worker is active.
    Errors retain only public codes, never exception or credential text.
    """

    def __init__(
        self,
        store: KlineStorePort,
        session: HistorySessionPort,
        settings: HistorySettings | None = None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        clock: Callable[[], float] = monotonic,
        wait: Callable[[float], None] = sleep,
        autostart: bool = True,
    ):
        self.store, self.session = store, session
        self.settings = settings or HistorySettings()
        self.now, self.clock, self.wait = now, clock, wait
        self._condition = Condition()
        self._serial = Lock()
        self._queue: list[HistoryRequest] = []
        self._errors: dict[str, str] = {}
        self._running = ''
        self._paused = False
        self._paused_day: date | None = None
        self._usage: HistoryUsage | None = None
        self._closed = False
        self._requests: deque[float] = deque()
        self._after_close_day: date | None = None
        self._disconnected_at: datetime | None = None
        self._generations: dict[str, int] = {}
        self.on_complete: Callable[[str], None] = lambda instrument_id: None
        self._thread = Thread(target=self._work, name='market-history', daemon=True) if autostart else None
        if self._thread is not None:
            self._thread.start()

    def request(self, instrument: WatchInstrument, start: datetime, end: datetime, priority: int = 0, *, force: bool = False) -> None:
        start, end = aware(start).astimezone(timezone.utc), aware(end).astimezone(timezone.utc)
        earliest = datetime.combine(self.settings.earliest, time(), _TAIPEI).astimezone(timezone.utc)
        start = max(start, earliest)
        if end <= start:
            return
        with self._condition:
            if self._closed:
                return
            item = HistoryRequest(instrument, start, end, priority, force, self._generations.get(instrument.instrument_id, 0))
            retained = []
            for old in self._queue:
                if old.instrument.instrument_id == instrument.instrument_id and old.force == force and old.end >= item.start and old.start <= item.end:
                    item = replace(item, start=min(old.start, item.start), end=max(old.end, item.end), priority=min(old.priority, item.priority))
                else:
                    retained.append(old)
            self._queue = retained + [item]
            self._condition.notify_all()

    def _lookback(self, instrument: WatchInstrument, days: int, priority: int) -> None:
        end = self.now().astimezone(timezone.utc).replace(second=0, microsecond=0)
        self.request(instrument, end - timedelta(days=days), end, priority)

    def connected(self, indices: tuple[WatchInstrument, ...], watchlist: tuple[WatchInstrument, ...], main: WatchInstrument | None = None) -> None:
        if main is not None:
            self._lookback(main, self.settings.daily_lookback_days if main in (*indices, *watchlist) else self.settings.minute_lookback_days, 0)
        for index, instrument in enumerate((*indices, *watchlist)):
            self._lookback(instrument, self.settings.daily_lookback_days, 2 + index)
        self.resume()

    def watch_added(self, instrument: WatchInstrument) -> None:
        self._lookback(instrument, self.settings.daily_lookback_days, 1)

    def browse(self, instrument: WatchInstrument, period: str = '1m', is_watchlisted: bool = False) -> None:
        annual = is_watchlisted or period == '1d' or instrument.code in ('IX0001', 'IX0043')
        self._lookback(instrument, self.settings.daily_lookback_days if annual else self.settings.minute_lookback_days, 0)

    def refresh(self, instrument: WatchInstrument, period: str = '1m', is_watchlisted: bool = False) -> None:
        self.browse(instrument, period, is_watchlisted)
        self.resume()

    def watch_removed(self, instrument_id: str) -> None:
        with self._condition:
            self._generations[instrument_id] = self._generations.get(instrument_id, 0) + 1
            self._queue = [item for item in self._queue if item.instrument.instrument_id != instrument_id]

    def disconnected(self) -> None:
        self._disconnected_at = self.now().astimezone(timezone.utc)
        with self._condition:
            self._paused = True

    def reconnected(self, instruments: tuple[WatchInstrument, ...]) -> None:
        end = self.now().astimezone(timezone.utc).replace(second=0, microsecond=0)
        if self._disconnected_at is not None:
            for index, instrument in enumerate(instruments):
                self.request(instrument, self._disconnected_at.replace(second=0, microsecond=0), end, index)
        self._disconnected_at = None
        self.resume()

    def after_close(self, instruments: tuple[WatchInstrument, ...], *, trading_day: bool = True) -> None:
        local = self.now().astimezone(_TAIPEI)
        if not trading_day or local.weekday() >= 5 or local.time() < time(13, 35) or self._after_close_day == local.date():
            return
        self._after_close_day = local.date()
        start = datetime.combine(local.date(), time(9), _TAIPEI)
        end = datetime.combine(local.date(), time(13, 31), _TAIPEI)
        for index, instrument in enumerate(instruments):
            self.request(instrument, start, end, index, force=True)

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._paused_day = None
            self._condition.notify_all()

    def resume_if_new_day(self) -> None:
        with self._condition:
            if self._paused_day is not None and self.now().astimezone(_TAIPEI).date() != self._paused_day:
                self.resume()

    def state(self) -> HistorySyncState:
        with self._condition:
            return HistorySyncState(len(self._queue), self._running, self._paused, self._usage is not None, self._usage, tuple(self._errors.items()))

    def is_backfilling(self, instrument_id: str) -> bool:
        with self._condition:
            return self._running == instrument_id or any(item.instrument.instrument_id == instrument_id for item in self._queue)

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._queue and not self._paused)
                if self._closed:
                    return
            self.run_next()

    def _rate_limit(self) -> None:
        now = self.clock()
        while self._requests and now - self._requests[0] >= 10:
            self._requests.popleft()
        if len(self._requests) >= 40:
            self.wait(max(0, 10 - (now - self._requests[0])))
            now = self.clock()
            while self._requests and now - self._requests[0] >= 10:
                self._requests.popleft()
        self._requests.append(now)

    def _available(self) -> bool:
        try:
            self._usage = self.session.usage()
        except (OSError, RuntimeError, ValueError):
            # Usage is an external optional SDK operation; absence is explicitly allowed.
            self._usage = None
        usage = self._usage
        day = self.now().astimezone(_TAIPEI).date()
        return (
            usage is None or Decimal(usage.limit_bytes - usage.used_bytes) >= usage.limit_bytes * self.settings.quota_reserve_ratio
        ) and self.store.queried_bars(day) < self.settings.daily_bar_limit

    def run_next(self) -> bool:
        with self._serial:
            with self._condition:
                if self._closed or self._paused or not self._queue:
                    return False
                index = min(range(len(self._queue)), key=lambda i: self._queue[i].priority)
                item = self._queue.pop(index)
                self._running = item.instrument.instrument_id
            try:
                self._sync(item)
            except DomainError as exc:
                self._errors[item.instrument.instrument_id] = exc.code
            except (OSError, RuntimeError, ValueError):
                # The cache/session ports perform external disk and SDK I/O.
                self._errors[item.instrument.instrument_id] = 'history_query_failed'
            finally:
                with self._condition:
                    self._running = ''
                    self._condition.notify_all()
            return True

    def _sync(self, item: HistoryRequest) -> None:
        local = self.now().astimezone(_TAIPEI)
        intraday = local.weekday() < 5 and time(9) <= local.time() < time(13, 30)
        ranges = ((item.start, item.end),) if item.force and not intraday else self.store.missing_ranges(item.instrument.instrument_id, item.start, item.end)
        for start, end in ranges:
            while start < end:
                with self._condition:
                    if self._closed or item.generation != self._generations.get(item.instrument.instrument_id, 0):
                        return
                stop = min(end, start + timedelta(days=self.settings.chunk_days))
                if not self._available():
                    self.request(item.instrument, start, item.end, item.priority, force=item.force)
                    with self._condition:
                        self._paused = True
                        self._paused_day = self.now().astimezone(_TAIPEI).date()
                    self._errors[item.instrument.instrument_id] = 'history_quota_low'
                    return
                self._rate_limit()
                bars = self.session.history(item.instrument, start, stop)
                if any(bar.instrument_id != item.instrument.instrument_id or not start <= bar.start < stop or bar.end > stop for bar in bars):
                    raise DomainError('history_query_failed', 'history range identity')
                day = self.now().astimezone(_TAIPEI).date()
                self.store.record_queried_bars(day, len(bars))
                with self._condition:
                    if item.generation != self._generations.get(item.instrument.instrument_id, 0):
                        return
                self.store.upsert(bars, source='SHIOAJI_KBARS')
                self.store.mark_coverage(item.instrument.instrument_id, start, stop)
                start = stop
                # Yield between chunks so a newly selected main chart takes priority.
                with self._condition:
                    higher = any(other.priority < item.priority for other in self._queue)
                if higher and start < item.end:
                    self.request(item.instrument, start, item.end, item.priority, force=item.force)
                    return
        self._errors.pop(item.instrument.instrument_id, None)
        self.on_complete(item.instrument.instrument_id)

    def close(self) -> bool:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return self._thread is None or not self._thread.is_alive()
