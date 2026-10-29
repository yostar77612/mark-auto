"""Compose public frozen market views from Domain results; no market rules or IO."""

from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.live_bars import MergedBars
from quantlab.trading.domain.quote_stats import QuoteStats
from quantlab.trading.domain.ticks import Tick
from .contracts import MarketHealthView, MarketWatchView, OverviewMarketSummary


def market_watch_view(
    instrument_id: str,
    tick: Tick | None,
    series: MergedBars,
    freshness: Freshness,
    stats: QuoteStats,
    history_error: str,
    *,
    incomplete: bool | None = None,
) -> MarketWatchView:
    """``incomplete`` lets a caller supply a cached any-bar-incomplete result."""
    if incomplete is None:
        incomplete = any(bar.incomplete for bar in series.bars)
    health = MarketHealthView(instrument_id, freshness.value, history_error, bool(series.gaps) or incomplete)
    return MarketWatchView(
        instrument_id,
        tick.price if tick else None,
        stats.reference_price,
        stats.change,
        stats.change_percent,
        tick.source_at if tick else None,
        tick.received_at if tick else None,
        tick.trade_date if tick else None,
        tick.session if tick else '',
        tick.source if tick else '',
        series.bars,
        series.gaps,
        health,
        receive_latency=str(tick.received_at - tick.source_at) if tick else '',
    )


def overview_market_summary(views: tuple[MarketWatchView, ...], *, limit: int, revision: int) -> OverviewMarketSummary:
    health = tuple(view.health for view in views)
    warning = any(item.freshness != Freshness.LIVE.value or item.history_error or item.incomplete for item in health)
    return OverviewMarketSummary(health, len(views), limit, revision, warning)
