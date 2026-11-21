"""Market-wide daily quotes for the screener (M6-3): per-stock statistics, the closing snapshot and the 240-day backfill.

Read-only market data from public sources: no account, no credential, no order path.
"""

from datetime import date, datetime, timedelta
import logging
from threading import Event, Thread
from time import monotonic
from typing import Callable, Protocol

from quantlab.trading.domain.market_daily import DailyQuote, DailyStats, daily_stats
from quantlab.trading.domain.screener import ScreenerParams
from quantlab.trading.domain.sector import QuoteRow, eligible_stock
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.market_daily import MarketDailySourcePort

logger = logging.getLogger(__name__)
OFFICIAL_MARKETS = ('TWSE', 'TPEX')
STATS_TTL = 60.0


class DailyStorePort(Protocol):
    revision: int

    def upsert(self, quotes: tuple[DailyQuote, ...]) -> None: ...
    def mark(self, trade_date: date, market: str, url: str, rows: int, at: datetime) -> None: ...
    def fetched(self, trade_date: date) -> dict[str, int]: ...
    def trade_days(self, before: date, limit: int) -> tuple[date, ...]: ...
    def history(self, before: date, days: int): ...


def snapshot_quotes(rows: dict[str, QuoteRow], day: date) -> tuple[DailyQuote, ...]:
    """The last round of a trading day as daily quotes; rows without open, high and low cannot make a daily bar."""
    quotes = []
    for code, row in rows.items():
        if not eligible_stock(code) or row.open is None or row.high is None or row.low is None:
            continue
        try:
            quotes.append(DailyQuote(code, day, row.open, row.high, row.low, row.price, row.total_volume, row.total_amount, 'SNAPSHOT'))
        except DomainError:
            continue  # a snapshot that contradicts itself (high below low) is not worth a daily bar
    return tuple(quotes)


class MarketDaily:
    """What the screener asks of the daily store: statistics before a day, how many days exist, and the closing write."""

    def __init__(
        self,
        store: DailyStorePort,
        params: Callable[[], ScreenerParams],
        now: Callable[[], datetime],
        *,
        ttl: float = STATS_TTL,
        clock: Callable[[], float] = monotonic,
    ):
        self.store, self.params, self.now, self.ttl, self.clock = store, params, now, ttl, clock
        self._cache: tuple[tuple, dict[str, DailyStats], float] | None = None

    def stats(self, day: date) -> dict[str, DailyStats]:
        """Statistics per stock from the trading days before `day`. While a backfill keeps changing the store the result
        is rebuilt at most once per ttl; a different day or different thresholds rebuild it at once."""
        params = self.params()
        shape = (day, params.windows, params.average_days)
        cached = self._cache
        if cached is not None and cached[0][:3] == shape and (cached[0][3] == self.store.revision or self.clock() - cached[2] < self.ttl):
            return cached[1]
        built = {code: daily_stats(rows, params.windows, params.average_days) for code, rows in self.store.history(day, max(params.windows))}
        self._cache = ((*shape, self.store.revision), built, self.clock())
        return built

    def days(self, day: date) -> int:
        """How many trading days before `day` the store holds (at most the longest window)."""
        return len(self.store.trade_days(day, max(self.params().windows)))

    def record_close(self, day: date, rows: dict[str, QuoteRow]) -> None:
        quotes = snapshot_quotes(rows, day)
        if quotes:
            self.store.upsert(quotes)
            self.store.mark(day, 'SNAPSHOT', 'snapshot:' + day.isoformat(), len(quotes), self.now())


class MarketDailyBackfill:
    """Fetches the last `target_days` trading days of the whole market, newest first, one request at a time.

    Every request is recorded in the store's ledger with its URL (a holiday as 0 rows), so an interrupted run resumes where
    it stopped and nothing is fetched twice. Today is skipped: the closing snapshot covers it and tomorrow's official
    fetch replaces it."""

    def __init__(
        self,
        store: DailyStorePort,
        source: MarketDailySourcePort,
        fetch: Callable[[str], bytes],
        today: Callable[[], date],
        now: Callable[[], datetime],
        *,
        target_days: int = 240,
        max_age_days: int = 400,
        pause: float = 4.0,
        idle: float = 3600.0,
    ):
        self.store, self.source, self.fetch, self.today, self.now = store, source, fetch, today, now
        self.target_days, self.max_age_days, self.pause, self.idle = target_days, max_age_days, pause, idle
        self._stopped = Event()
        self._thread: Thread | None = None

    def next_pending(self) -> tuple[date, str] | None:
        today = self.today()
        oldest, day, counted = today - timedelta(days=self.max_age_days), today - timedelta(days=1), 0
        while day >= oldest and counted < self.target_days:
            if day.weekday() < 5:
                done = self.store.fetched(day)
                for market in OFFICIAL_MARKETS:
                    if market not in done:
                        return day, market
                counted += any(done[market] > 0 for market in OFFICIAL_MARKETS)
            day -= timedelta(days=1)
        return None

    def step(self) -> bool:
        """Fetch and store the next missing day; False when everything wanted is already there.

        A refused or malformed response raises DomainError and records nothing, so the day is tried again later."""
        pending = self.next_pending()
        if pending is None:
            return False
        day, market = pending
        url = self.source.url(market, day)
        quotes = self.source.parse(market, self.fetch(url), day) or ()
        self.store.upsert(quotes)
        self.store.mark(day, market, url, len(quotes), self.now())
        return True

    def start(self) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._work, name='market-daily-backfill', daemon=True)
            self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _work(self) -> None:
        failures = 0
        while not self._stopped.is_set():
            try:
                worked = self.step()
                failures = 0
            except DomainError as error:
                failures += 1
                logger.warning('market daily backfill step failed (%s); retrying later', error.code)
                self._stopped.wait(min(1800.0, 60.0 * 2**failures))
                continue
            self._stopped.wait(self.pause if worked else self.idle)
