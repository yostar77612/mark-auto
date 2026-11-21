"""Chart series reads that re-read only the tail of what the caller already holds (OPT-1 P8 sector board, P11 market terminal and watch)."""

from quantlab.trading.application.contracts import MarketSeriesQuery
from quantlab.trading.domain.validation import DomainError

# The refresh re-reads only this many trailing bars: the forming bar, the tail of an aggregated
# period and recent tick-loss marks (a loss marks the minutes it covers, which are the newest ones).
SERIES_TAIL_BARS = 240
# A whole-series read still happens at least this often. It bounds how long a change confined to bars older
# than the re-read window stays unshown when the window itself still lines up: a same-size history re-backfill,
# a loss mark on old minutes, or a session trim and an older backfill landing in the same refresh.
SERIES_RESYNC_SECONDS = 120.0


def read_series(facade, key, period, cached, *, retry_history=False, pinned_tail=False):
    """The selected instrument's chart series as (page, bars, whole).

    With `cached` (page, bars) from the previous read of the same instrument and period, only the last
    SERIES_TAIL_BARS are re-read and spliced on. Any sign that the earlier part may differ falls back to
    the whole read: more than one page of new bars, a shorter series, changed gaps, or a mismatch in the
    re-read window (a history backfill or trim shifts every index, so the window no longer lines up).

    `retry_history` is the retry button: the whole series is read and its first page asks the engine to
    fetch the history again. `pinned_tail` is for engines that serve a page past the first only from the
    snapshot that an earlier first-page read took, and only when the read names that snapshot's revision
    (the market terminal service does): the tail is then read after a one-bar first-page read that takes
    a fresh snapshot, and an engine that reports the snapshot gone falls back to the whole read.
    """
    if cached is not None and cached[1] and not retry_history:
        spliced = _read_tail(facade, key, period, *cached, pinned=pinned_tail)
        if spliced is not None:
            return (*spliced, False)
    page = facade.market_series(MarketSeriesQuery(key, period, retry_history=retry_history))
    bars = page.bars
    while page.next_offset is not None:
        page = facade.market_series(MarketSeriesQuery(key, period, offset=page.next_offset, market_revision=page.market_revision))
        bars += page.bars
    return page, bars, True


def _read_tail(facade, key, period, cached_page, cached_bars, *, pinned):
    offset = max(0, len(cached_bars) - SERIES_TAIL_BARS)
    revision = None
    if pinned and offset:
        revision = facade.market_series(MarketSeriesQuery(key, period, limit=1)).market_revision
    try:
        page = facade.market_series(MarketSeriesQuery(key, period, offset=offset, market_revision=revision))
    except DomainError as error:
        if revision is None or error.code != 'state_conflict':
            raise
        return None
    stable = len(cached_bars) - offset - 1  # cached bars in the window except the last, which may still be forming
    if page.next_offset is not None or page.total < len(cached_bars) or page.gaps != cached_page.gaps:
        return None
    if len(page.bars) <= stable or page.bars[stable].start != cached_bars[-1].start or page.bars[:stable] != cached_bars[offset:-1]:
        return None
    return page, cached_bars[:offset] + page.bars
