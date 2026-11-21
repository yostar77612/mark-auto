"""A real chart-series engine driven round by round, for the OPT-1 P11 equivalence tests (no network, broker or credentials).

TerminalFeed is a MarketTerminalService over a real KlineStore: the engine that serves every chart read while the market
connection is enabled. Each round the test moves its clock, feeds ticks (new minutes, updates of the forming minute,
tick-loss marks, day and night sessions across trade dates) and writes history (an older backfill that shifts every
index, or a same-size rewrite of old bars), then compares what the chart code read with a plain whole-series read.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from desktop_app.features.trading.series_reader import SERIES_TAIL_BARS
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.contracts import MarketSeriesQuery
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_terminal_service import MarketTerminalService
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind
from quantlab.trading.ports.history import HistoryUsage
from quantlab.trading.ports.tick_stream import TickLoss

NOW = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)  # 09:00 in Taipei: the day session has just opened
STOCK = WatchInstrument('TWSE:2330', WatchKind.STOCK, 'TSE', '2330', 'TSMC')
OTHER = WatchInstrument('TWSE:2317', WatchKind.STOCK, 'TSE', '2317', 'HonHai')
_TAIPEI = ZoneInfo('Asia/Taipei')
# History older than this many minutes lies outside the tail window the reader re-reads (240 bars).
OLD_MINUTES = 400


def calendar(moment):
    """(trade date, session) under the futures calendar: from 15:00 the night session belongs to the next trade date."""
    local = moment.astimezone(_TAIPEI)
    night = local.hour >= 15 or local.hour < 5
    return (local + timedelta(hours=9)).date(), 'NIGHT' if night else 'DAY'


class _Session:
    """A connected market session: it only hands over the ticks and tick losses a test queued."""

    def __init__(self):
        self.connected, self.pending, self.losses = True, [], []

    def subscribe(self, item):
        pass

    def unsubscribe(self, key):
        pass

    def drain_ticks(self, limit):
        ticks, self.pending = tuple(self.pending[:limit]), self.pending[limit:]
        return ticks

    def drain_tick_losses(self):
        losses, self.losses = tuple(self.losses), []
        return losses

    def usage(self):
        return HistoryUsage(0, 100)

    def quote_details(self, instrument_id):
        return {}

    def subscribe_bidask(self, item):
        pass

    def unsubscribe_bidask(self, key):
        pass

    def bidask(self, instrument_id):
        return None

    def history(self, item, start, end):
        return ()


class RecordingFacade:
    """The chart code's series calls onto the engine, logging every query in order."""

    def __init__(self, service):
        self.service, self.queries = service, []

    def market_series(self, query):
        self.queries.append(query)
        return self.service.series(query)


class TerminalFeed:
    def __init__(self, folder, *, depth=1500):
        self.now, self.depth, self.shift, self.count = NOW, depth, 0, 0
        self.store = KlineStore(Path(folder) / 'klines.sqlite3')
        self.session = _Session()
        self.sync = HistorySync(self.store, self.session, now=lambda: self.now, autostart=False)
        self.service = MarketTerminalService(
            self.store,
            self.sync,
            self.session,
            lambda: (*FIXED_INDICES, STOCK, OTHER),
            watchlist=(STOCK.instrument_id, OTHER.instrument_id),
            now=lambda: self.now,
            settings=LiveMarketSettings(),
        )
        self.facade = RecordingFacade(self.service)
        self.write_history()
        self.service.connected()

    def close(self):
        self.sync.close()
        self.store.close()

    def write_history(self):
        """The history of both stocks: `depth` finished minutes before NOW. `shift` rewrites only bars older than OLD_MINUTES."""
        for item in (STOCK, OTHER):
            bars = []
            for minutes in range(self.depth, 0, -1):
                start = NOW - timedelta(minutes=minutes)
                day, session = calendar(start)
                close = Decimal(100 + (minutes + (self.shift if minutes > OLD_MINUTES else 0)) % 3)
                bars.append(
                    LiveBar(
                        item.instrument_id, start, start + timedelta(minutes=1), day, session, close, close + 3, close - 1, close, 1 + minutes % 5, final=True
                    )
                )
            self.store.upsert(tuple(bars))

    def backfill_older(self, minutes=45):
        """Older history arrives: the series grows at its start and every index after it shifts."""
        self.depth += minutes
        self.write_history()

    def rewrite_old(self):
        """The same bars with other values, all older than the tail window: the series keeps its size and its tail."""
        self.shift += 1
        self.write_history()

    def tick(self, seconds=20, *, lost=False):
        """Move the clock, deliver one STOCK tick (flagged lost when `lost`) and let the engine poll."""
        self.now += timedelta(seconds=seconds)
        self.count += 1
        day, session = calendar(self.now)
        self.session.pending.append(Tick(STOCK.instrument_id, Decimal(100 + self.count % 5), 1 + self.count % 4, self.now, self.now, day, session))
        if lost:
            self.session.losses.append(TickLoss(STOCK.instrument_id, self.now, self.now, 1))
        self.service.poll()

    def whole(self, key, period):
        """A plain whole-series read straight from the engine (not logged): the oracle every round is compared with."""
        page = self.service.series(MarketSeriesQuery(key, period))
        bars = page.bars
        while page.next_offset is not None:
            page = self.service.series(MarketSeriesQuery(key, period, offset=page.next_offset, market_revision=page.market_revision))
            bars += page.bars
        return replace(page, bars=bars, offset=0)


def whole_round(queries, key):
    """True when the queries of one round read `key` from its first page, as a whole read does."""
    return any(query.instrument_id == key and query.offset == 0 and query.limit > 1 for query in queries)


def run_inline(operation, completed, *, quiet=False):
    """Stand-in for a widget's `_submit`: the request runs and completes at once on the caller's thread, one deterministic step."""
    try:
        value = operation()
    except Exception as error:
        completed(None, error)
    else:
        completed(value, None)


def without_window_check(facade, key, period, cached_page, cached_bars, *, pinned):
    """series_reader._read_tail with the comparison of the re-read window removed: the mutation the equivalence tests must catch."""
    offset = max(0, len(cached_bars) - SERIES_TAIL_BARS)
    revision = facade.market_series(MarketSeriesQuery(key, period, limit=1)).market_revision if pinned and offset else None
    page = facade.market_series(MarketSeriesQuery(key, period, offset=offset, market_revision=revision))
    if page.next_offset is not None or page.total < len(cached_bars) or page.gaps != cached_page.gaps:
        return None
    return page, cached_bars[:offset] + page.bars
