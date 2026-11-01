"""Project watch-only ticks and previous cached trading-day closes for presentation."""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from quantlab.trading.domain.freshness import LiveMarketSettings, classify_freshness
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.ticks import Tick
from .contracts import MarketHealthView, MarketWatchView

_TAIPEI = ZoneInfo('Asia/Taipei')


@decimal_operation
def watch_view(
    instrument_id: str,
    tick: Tick | None,
    bars: tuple[LiveBar, ...],
    now: datetime,
    connected: bool,
    settings: LiveMarketSettings,
    history_error: str,
    details: dict[str, object],
) -> MarketWatchView:
    if tick is None:
        return MarketWatchView(instrument_id=instrument_id, health=MarketHealthView(instrument_id, history_error=history_error))
    local = now.astimezone(_TAIPEI)
    in_session = local.weekday() < 5 and time(9) <= local.time() <= time(13, 30)
    freshness = classify_freshness(tick.received_at, now=now, connected=connected, in_session=in_session, settings=settings).value
    prior = next((bar.close for bar in reversed(bars) if bar.trade_date < tick.trade_date), None)
    prior = prior if prior is not None else details.get('reference_price')
    today = tuple(bar for bar in bars if bar.trade_date == tick.trade_date)
    change = tick.price - prior if prior is not None else None
    percent = change / prior * Decimal('100') if prior else None
    return MarketWatchView(
        instrument_id=instrument_id,
        price=tick.price,
        reference_price=prior,
        change=change,
        change_percent=percent,
        source_at=tick.source_at,
        received_at=tick.received_at,
        trade_date=tick.trade_date,
        session=tick.session,
        source=details.get('source', tick.source),
        health=MarketHealthView(instrument_id, freshness, history_error),
        open=details.get('open', today[0].open if today else None),
        high=details.get('high', max((bar.high for bar in today), default=None)),
        low=details.get('low', min((bar.low for bar in today), default=None)),
        bid=details.get('bid'),
        ask=details.get('ask'),
        total_volume=details.get('total_volume'),
        price_tick=details.get('price_tick'),
        receive_latency=f'{(tick.received_at - tick.source_at).total_seconds():.3f}s',
    )
