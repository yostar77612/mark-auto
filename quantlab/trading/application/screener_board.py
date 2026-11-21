"""Read model of the stock screener tab: the lists, their K-line column and the manual download."""

from datetime import datetime
from time import monotonic
from typing import Callable, Protocol

from quantlab.trading.domain.screener import SURGE_BLACK, SURGE_RED, ScreenerParams
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from .screener_contracts import DownloadedRowView, ScreenerQuery, ScreenerRowView, ScreenerView
from .stock_screener import SCREENER_PRIORITY, StockScreener, download_window

_PATTERNS = {'ALL': (SURGE_RED, SURGE_BLACK), 'RED': (SURGE_RED,), 'BLACK': (SURGE_BLACK,)}
# Daily K-lines for the breakout list arrive with the market-wide daily store (M6-3); until then it only accumulates.
BREAKOUT_WINDOWS = (60, 120, 240)
DOWNLOADED_TTL = 30.0


class KlineCatalogPort(Protocol):
    def instrument_ids(self) -> tuple[str, ...]: ...
    def minute_extent(self, instrument_id: str) -> tuple[datetime, datetime, datetime | None] | None: ...
    def missing_ranges(self, instrument_id: str, start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]: ...


class DownloadPort(Protocol):
    def request(self, instrument: WatchInstrument, start: datetime, end: datetime, priority: int = 0) -> None: ...
    def is_backfilling(self, instrument_id: str) -> bool: ...
    def state(self): ...


def _reason(error: Exception) -> str:
    return error.code if isinstance(error, DomainError) else 'kline_store_unavailable'


class ScreenerBoard:
    """Builds ScreenerView for one query. Reads only: the one write is queueing a download through HistorySync."""

    def __init__(
        self,
        status: Callable[[], str],
        now: Callable[[], datetime],
        directory: Callable[[], tuple[WatchInstrument, ...]],
        screener: StockScreener,
        store: KlineCatalogPort,
        history: DownloadPort,
        params: Callable[[], ScreenerParams],
        *,
        lookback_days: int = 365,
        clock: Callable[[], float] = monotonic,
    ):
        self.status, self.now, self.directory, self.screener = status, now, directory, screener
        self.store, self.history, self.params = store, history, params
        self.lookback_days, self.clock = lookback_days, clock
        self._downloaded: tuple[float, tuple[DownloadedRowView, ...]] | None = None

    def view(self, query: ScreenerQuery) -> ScreenerView:
        if query.download_id:
            self.download(query.download_id)
        if query.list_id == 'DOWNLOADED':
            return self._downloaded_view()
        if query.list_id == 'BREAKOUT':
            return ScreenerView('BREAKOUT', 'ALL', 'ACCUMULATING', min_volume_lots=self.params().min_volume_lots, progress_needed=BREAKOUT_WINDOWS[0])
        return self._surge_view(query.pattern)

    def download(self, instrument_id: str) -> None:
        """Queue one year of 1-minute bars for a stock, the same path and priority as an automatic trigger."""
        instrument = next((item for item in self.directory() if item.instrument_id == instrument_id), None)
        if instrument is None:
            raise DomainError('validation_failed', 'unknown screener instrument')
        start, end = download_window(self.now(), self.lookback_days)
        self.history.request(instrument, start, end, SCREENER_PRIORITY)
        self._downloaded = None

    def _surge_view(self, pattern: str) -> ScreenerView:
        params, state = self.params(), self.status()
        if state in ('OFFLINE', 'EMPTY'):
            return ScreenerView('SURGE', pattern, state, min_volume_lots=params.min_volume_lots)
        result = self.screener.result()
        by_id = {item.code: item for item in self.directory() if item.kind is WatchKind.STOCK}
        wanted = _PATTERNS[pattern]
        entries = [entry for entry in result.surges if entry.code in by_id and (pattern == 'ALL' or entry.pattern in wanted)]
        rows, code = [], ''
        for entry in entries:
            instrument = by_id[entry.code]
            kline, code = self._kline_state(instrument, code)
            rows.append(
                ScreenerRowView(instrument.instrument_id, entry.code, instrument.name, entry.price, entry.change_pct, entry.volume_ratio, entry.pattern, kline)
            )
        shown = 'WARMUP' if not result.ranking and state in ('LIVE', 'STALE') else state
        return ScreenerView('SURGE', pattern, shown, tuple(rows), min_volume_lots=params.min_volume_lots, data_at=result.at, code=code)

    def _kline_state(self, instrument: WatchInstrument, code: str) -> tuple[str, str]:
        """'' none, YEAR a full year stored, DOWNLOADING queued or running, FAILED the last attempt failed."""
        instrument_id = instrument.instrument_id
        if self.history.is_backfilling(instrument_id):
            return 'DOWNLOADING', code
        if dict(self.history.state().history_error).get(instrument_id):
            return 'FAILED', code
        start, end = download_window(self.now(), self.lookback_days)
        try:
            return ('' if self.store.missing_ranges(instrument_id, start, end) else 'YEAR'), code
        except Exception as error:  # the K-line store is a disk boundary; the list must survive any failure of it
            return '', _reason(error)

    def _downloaded_view(self) -> ScreenerView:
        params = self.params()
        cached = self._downloaded
        if cached is None or self.clock() - cached[0] > DOWNLOADED_TTL:
            try:
                rows = self._downloaded_rows()
            except Exception as error:  # same boundary: show the reason code instead of failing the whole read
                return ScreenerView('DOWNLOADED', 'ALL', self.status(), min_volume_lots=params.min_volume_lots, code=_reason(error))
            cached = self._downloaded = (self.clock(), rows)
        return ScreenerView('DOWNLOADED', 'ALL', self.status(), downloaded=cached[1], min_volume_lots=params.min_volume_lots)

    def _downloaded_rows(self) -> tuple[DownloadedRowView, ...]:
        names = {item.instrument_id: item for item in self.directory()}
        rows = []
        for instrument_id in self.store.instrument_ids():
            extent = self.store.minute_extent(instrument_id)
            if extent is None:
                continue
            item = names.get(instrument_id)
            code = item.code if item is not None else instrument_id.split(':')[-1]
            rows.append(DownloadedRowView(instrument_id, code, item.name if item is not None else code, extent[0], extent[1], extent[2]))
        return tuple(sorted(rows, key=lambda row: row.code))
