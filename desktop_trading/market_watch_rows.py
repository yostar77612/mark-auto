"""Pure market-view formatting; no Qt, IO, aggregation or price calculations.

Application supplies all numeric facts and freshness. Missing facts remain
Unknown, including fields a connector has not supplied.
"""

from dataclasses import dataclass
from datetime import datetime
from desktop_strings import ui_text
from quantlab.trading.application.contracts import MarketHealthView, MarketWatchView, OverviewMarketSummary, MarketSeriesPage


def value_text(value) -> str:
    return ui_text('watch.unknown') if value is None or value == '' else str(value)


def session_text(value) -> str:
    labels = {'DAY': ui_text('presentation.labels.day'), 'NIGHT': ui_text('presentation.labels.night')}
    return labels.get(str(value).upper(), value_text(value))


def time_text(value: datetime | None) -> str:
    return ui_text('watch.unknown') if value is None else value.isoformat(sep=' ', timespec='seconds')


def freshness_text(health: MarketHealthView, updated: datetime | None = None) -> tuple[str, str]:
    labels = {
        'LIVE': (ui_text('watch.live'), 'live'),
        'DELAYED': (ui_text('watch.delayed').format(time_text(updated)), 'warning'),
        'STOPPED': (ui_text('watch.stopped').format(time_text(updated)), 'muted'),
        'CLOSED': (ui_text('watch.closed').format(time_text(updated)), 'muted'),
        'UNKNOWN': (ui_text('watch.unknown'), 'muted'),
    }
    return labels[health.freshness]


def watch_rows(views: tuple[MarketWatchView, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            view.instrument_id,
            (
                view.instrument_id,
                value_text(view.price) if view.health.freshness != 'UNKNOWN' else ui_text('watch.unknown'),
                value_text(view.change),
                value_text(view.change_percent),
                value_text(view.total_volume),
                freshness_text(view.health, view.received_at)[0],
            ),
        )
        for view in views
    )


def health_rows(summary: OverviewMarketSummary) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((item.instrument_id, (item.instrument_id, freshness_text(item)[0])) for item in summary.instruments)


def header_text(connection: str, summary: OverviewMarketSummary) -> str:
    states = ' · '.join(freshness_text(item)[0] for item in summary.instruments) or ui_text('watch.unknown')
    connection_text = {
        'CONNECTED': ui_text('watch.connected'),
        'DISCONNECTED': ui_text('watch.disconnected'),
        'CONNECTING': ui_text('watch.connecting'),
        'UNKNOWN': ui_text('watch.unknown'),
    }[connection]
    return ui_text('watch.header').format(connection_text, states, summary.subscription_count, summary.subscription_limit)


def quote_detail_rows(view: MarketWatchView) -> tuple[tuple[str, str], ...]:
    return (
        (ui_text('watch.bid'), value_text(view.bid)),
        (ui_text('watch.ask'), value_text(view.ask)),
        (ui_text('watch.open'), value_text(view.open)),
        (ui_text('watch.high'), value_text(view.high)),
        (ui_text('watch.low'), value_text(view.low)),
        (ui_text('watch.reference'), value_text(view.reference_price)),
        (ui_text('watch.volume'), value_text(view.total_volume)),
        (ui_text('watch.trade_date'), value_text(view.trade_date)),
        (ui_text('watch.session'), session_text(view.session)),
        (ui_text('watch.source'), value_text(view.source)),
        (ui_text('watch.latency'), value_text(view.receive_latency)),
        (ui_text('watch.updated'), time_text(view.received_at)),
        (ui_text('watch.source_time'), time_text(view.source_at)),
        (ui_text('watch.state'), freshness_text(view.health, view.received_at)[0]),
    )


def quote_detail_text(view: MarketWatchView) -> str:
    return '\n'.join(ui_text('watch.detail_line').format(label, text) for label, text in quote_detail_rows(view))


@dataclass(frozen=True)
class ChartBar:
    """Display-only shape for the injected CandlestickChart; no resampling."""

    contract_id: str
    interval: str
    start: datetime
    end: datetime
    open: object
    high: object
    low: object
    close: object
    volume: int
    trade_date: str
    partial: bool

    @property
    def timestamp(self):
        return self.start


def series_bars(page: MarketSeriesPage) -> tuple[ChartBar, ...]:
    return tuple(
        ChartBar(
            page.instrument_id,
            page.period,
            bar.start,
            bar.end,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.trade_date.isoformat(),
            not bar.final or bar.incomplete,
        )
        for bar in page.bars
    )


def series_status(page: MarketSeriesPage, health: MarketHealthView) -> str:
    return ui_text('watch.gap') if page.gaps or health.incomplete else ''
