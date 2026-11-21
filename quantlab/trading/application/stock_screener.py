"""Stock screener (M6): surge ranking and condition-triggered K-line downloads from the sector snapshot rounds.

Read-only market data. No order path, no trading signal. Rounds come from SectorService.on_round; this module never
calls the snapshot source itself. Amounts stay integer NT$, prices and ratios stay Decimal.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from threading import RLock
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from quantlab.trading.domain.market_daily import DailyStats, volume_breakout
from quantlab.trading.domain.screener import BREAKOUT, SURGE_BLACK, SURGE_RED, ScreenerParams
from quantlab.trading.domain.sector import QuoteRow, eligible_stock
from quantlab.trading.domain.watch import WatchInstrument
from .sector_service import SESSION_END, in_session

_TAIPEI = ZoneInfo('Asia/Taipei')
# Below the main chart (0) and every watchlist entry (2 + position): the screener never delays what the user is watching.
SCREENER_PRIORITY = 10_000


@dataclass(frozen=True)
class SurgeEntry:
    code: str
    price: Decimal
    change_pct: Decimal
    volume_ratio: Decimal
    pattern: str  # '' | SURGE_RED | SURGE_BLACK
    total_volume: int
    total_amount: int


@dataclass(frozen=True)
class BreakoutEntry:
    """A stock above its earlier high of `window` trading days on volume. strength is volume over its average (final)
    or the snapshot volume ratio (provisional, in session)."""

    code: str
    price: Decimal
    change_pct: Decimal
    window: int
    strength: Decimal
    provisional: bool
    total_volume: int
    total_amount: int


@dataclass(frozen=True)
class ScreenResult:
    """The latest judged round. ranking is False while the open is still settling (no list, no triggers).
    history_days is how many earlier trading days the market-wide daily quotes cover."""

    trade_date: date | None = None
    ranking: bool = False
    at: datetime | None = None
    surges: tuple[SurgeEntry, ...] = ()
    breakouts: tuple[BreakoutEntry, ...] = ()
    history_days: int = 0


class DailyPort(Protocol):
    def stats(self, day: date) -> dict[str, DailyStats]: ...
    def days(self, day: date) -> int: ...
    def record_close(self, day: date, rows: dict[str, QuoteRow]) -> None: ...


class HistoryRequestPort(Protocol):
    def request(self, instrument: WatchInstrument, start: datetime, end: datetime, priority: int = 0) -> None: ...


def eligible_row(code: str, row: QuoteRow, params: ScreenerParams) -> bool:
    """Ordinary shares priced and traded enough to matter; ETFs, warrants and penny or thin stocks are out."""
    return eligible_stock(code) and row.price >= params.min_price and row.total_volume >= params.min_volume_lots


def typical_amount(row: QuoteRow) -> int | None:
    """Stand-in for 'usually traded amount' until the market-wide daily K-lines exist: today's amount divided by the
    volume ratio (the ratio compares today's volume with the same period of earlier days)."""
    if row.volume_ratio is None or row.volume_ratio <= 0:
        return None
    return int(Decimal(row.total_amount) / row.volume_ratio)


def surge_pattern(row: QuoteRow, params: ScreenerParams, typical: int | None) -> str:
    """Long red or long black candle on surging volume; '' when the row is neither (or lacks the fields to say).

    Distance from the day's extreme is measured against that extreme: (high - price) / high for red,
    (price - low) / low for black."""
    if row.volume_ratio is None or row.volume_ratio < params.surge_ratio or row.open is None:
        return ''
    if row.change_pct >= params.red_change_pct and row.price > row.open and row.high is not None and typical is not None:
        near_high = (row.high - row.price) / row.high * 100 <= params.near_extreme_pct
        return SURGE_RED if near_high and typical < params.quiet_amount else ''
    if row.change_pct <= -params.black_change_pct and row.price < row.open and row.low is not None:
        return SURGE_BLACK if (row.price - row.low) / row.low * 100 <= params.near_extreme_pct else ''
    return ''


def rank_surges(rows: dict[str, QuoteRow], params: ScreenerParams, typical_of: Callable[[str, QuoteRow], int | None]) -> tuple[SurgeEntry, ...]:
    """Every eligible row with a volume ratio, highest ratio first; ties by amount, then code."""
    entries = [
        SurgeEntry(code, row.price, row.change_pct, row.volume_ratio, surge_pattern(row, params, typical_of(code, row)), row.total_volume, row.total_amount)
        for code, row in rows.items()
        if row.volume_ratio is not None and eligible_row(code, row, params)
    ]
    entries.sort(key=lambda entry: (-entry.volume_ratio, -entry.total_amount, entry.code))
    return tuple(entries)


def find_breakouts(rows: dict[str, QuoteRow], stats: dict[str, DailyStats], params: ScreenerParams, *, final: bool) -> tuple[BreakoutEntry, ...]:
    """Eligible stocks breaking an earlier high on volume, longest window first, then strongest volume."""
    found = []
    for code, row in rows.items():
        stat = stats.get(code)
        if stat is None or not eligible_row(code, row, params):
            continue
        hit = volume_breakout(
            row.price,
            row.total_volume,
            row.volume_ratio,
            stat,
            final=final,
            multiple=params.breakout_volume_multiple,
            intraday_ratio=params.breakout_intraday_ratio,
        )
        if hit is not None:
            found.append(BreakoutEntry(code, row.price, row.change_pct, hit[0], hit[1], not final, row.total_volume, row.total_amount))
    found.sort(key=lambda entry: (-entry.window, -entry.strength, entry.code))
    return tuple(found)


def download_window(now: datetime, lookback_days: int) -> tuple[datetime, datetime]:
    """One year back, ending at the previous weekday's close while the day is not over.

    A broker K-line query whose range reaches today times out while the session is open (measured 2026-11-20), so
    intraday requests stop at yesterday's close and the closing round fills today in."""
    local = now.astimezone(_TAIPEI)
    start = now - timedelta(days=lookback_days)
    if local.weekday() >= 5 or local.time() > SESSION_END:
        return start, now
    day = local.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return start, datetime.combine(day, SESSION_END, _TAIPEI)


def ranking_open(now: datetime, params: ScreenerParams) -> bool:
    """In session the list starts a few minutes after 09:00 (the opening volume ratio is distorted); off session the
    last round is final and always judged."""
    if not in_session(now):
        return True
    local = now.astimezone(_TAIPEI)
    return local.time() >= (datetime.combine(local.date(), time(9)) + timedelta(minutes=params.warmup_minutes)).time()


def _data_day(now: datetime, rows: dict[str, QuoteRow]) -> date:
    """The trading day the rows belong to: the newest quote date, never later than today (a stray future stamp)."""
    today = now.astimezone(_TAIPEI).date()
    return min(max(row.at.astimezone(_TAIPEI).date() for row in rows.values()), today)


class StockScreener:
    """Ranks the latest round and queues one-year K-line downloads, once per stock, condition and day."""

    def __init__(
        self,
        params: Callable[[], ScreenerParams],
        stocks: Callable[[], tuple[WatchInstrument, ...]],
        history: HistoryRequestPort,
        record: Callable[[WatchInstrument, str, datetime], None],
        *,
        lookback_days: int = 365,
        daily: DailyPort | None = None,
    ):
        self.params, self.stocks, self.history, self.record = params, stocks, history, record
        self.lookback_days, self.daily = lookback_days, daily
        self._lock = RLock()
        self._result = ScreenResult()
        self._fired: dict[date, set[tuple[str, str]]] = {}
        self._logged: dict[tuple[str, str], date] = {}
        self._refilled: date | None = None

    def seed(self, fired: tuple[tuple[date, str, str], ...]) -> None:
        """Triggers already written to the alert log (day, code, condition), so a restart does not repeat them.

        The log's day is the calendar day of the entry, which on a weekend or before the open is later than the trading
        day the rows belong to; a logged trigger therefore also covers any data day up to and including its own."""
        with self._lock:
            for day, code, condition in fired:
                self._fired.setdefault(day, set()).add((code, condition))
                self._logged[(code, condition)] = max(day, self._logged.get((code, condition), day))

    def result(self) -> ScreenResult:
        with self._lock:
            return self._result

    def on_round(self, now: datetime, rows: dict[str, QuoteRow]) -> None:
        if not rows:
            return
        params, local = self.params(), now.astimezone(_TAIPEI)
        day = _data_day(now, rows)
        # A stock that has not traded today still carries an earlier day's totals in the snapshot: it is not today's news.
        rows = {code: row for code, row in rows.items() if row.at.astimezone(_TAIPEI).date() == day}
        history_days = self.daily.days(day) if self.daily is not None else 0
        if not ranking_open(now, params):
            with self._lock:
                self._result = ScreenResult(day, False, now, history_days=history_days)
            return
        stats = self.daily.stats(day) if self.daily is not None else {}
        entries = rank_surges(rows, params, lambda code, row: _typical(stats.get(code), row))
        breakouts = find_breakouts(rows, stats, params, final=not in_session(now))
        with self._lock:
            self._result = ScreenResult(day, True, now, entries[: params.list_rows], breakouts, history_days)
            fired = self._fired.setdefault(day, set())
            self._fired = {day: fired}  # only the newest day is kept
            candidates = [(entry.code, entry.pattern) for entry in entries if entry.pattern]
            candidates += [(entry.code, BREAKOUT) for entry in breakouts]
            new = [key for key in candidates if self._wanted(key[1], params) and not self._done(day, fired, key)]
        if local.weekday() < 5 and local.time() > SESSION_END and day == local.date():
            self._refill(day, now)  # before the new triggers: those already reach now
            if self.daily is not None:
                self.daily.record_close(day, rows)
        self._download(day, new, now)

    def _done(self, day: date, fired: set[tuple[str, str]], key: tuple[str, str]) -> bool:
        return key in fired or self._logged.get(key, date.min) >= day

    @staticmethod
    def _wanted(condition: str, params: ScreenerParams) -> bool:
        return {SURGE_RED: params.download_red, SURGE_BLACK: params.download_black, BREAKOUT: params.download_breakout}[condition]

    def _download(self, day: date, keys: list[tuple[str, str]], now: datetime) -> None:
        by_code = {item.code: item for item in self.stocks()}
        start, end = download_window(now, self.lookback_days)
        for code, condition in keys:
            instrument = by_code.get(code)
            if instrument is None:
                continue
            self.history.request(instrument, start, end, SCREENER_PRIORITY)
            with self._lock:
                self._fired[day].add((code, condition))
            self.record(instrument, condition, now)

    def _refill(self, day: date, now: datetime) -> None:
        """After the close, extend today's triggered downloads from yesterday's close up to now (once per day)."""
        with self._lock:
            if self._refilled == day:
                return
            self._refilled = day
            codes = {code for code, _ in self._fired.get(day, ())}
        by_code = {item.code: item for item in self.stocks()}
        start, end = download_window(now, self.lookback_days)
        for code in sorted(codes & by_code.keys()):
            self.history.request(by_code[code], start, end, SCREENER_PRIORITY)


def _typical(stat: DailyStats | None, row: QuoteRow) -> int | None:
    """The usual traded amount: the stock's own average once its daily history covers it, else the estimate."""
    return stat.avg_amount if stat is not None and stat.avg_amount is not None else typical_amount(row)
