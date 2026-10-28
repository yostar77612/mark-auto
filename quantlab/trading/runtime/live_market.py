"""Compose market ports for the host; no bar, freshness, quota or P&L rules."""

from datetime import date, datetime
from uuid import uuid4

from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.domain.models import Market, Quote
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.ports.contracts import DataBatch, SubscriptionReceipt
from quantlab.trading.ports.interfaces import Clock, MarketDataPort


class CalendarResolver:
    def __init__(self, engine: TradingEngine) -> None:
        self.calendar = engine.calendar
        self.catalog = engine.catalog

    def session_at(self, instrument_id: str, timestamp: datetime) -> tuple[date, str]:
        spec = self.catalog.resolve(instrument_id)
        session = self.calendar.session_at(timestamp, allow_night=spec.market is not Market.STOCK)
        return session.trade_date, session.kind


class RoutedMarketData:
    """Route typed market calls to owned connectors, once per shared connector."""

    def __init__(self, routes: dict[str, MarketDataPort], clock: Clock) -> None:
        self.routes = routes
        self.clock = clock
        self.ports = tuple({id(port): port for port in routes.values()}.values())
        self.subscriptions: dict[str, tuple[tuple[MarketDataPort, str], ...]] = {}
        self.cursor = 0

    def history(self, instrument_id: str, start: datetime, end: datetime) -> DataBatch:
        return self.routes[instrument_id].history(instrument_id, start, end)

    def latest(self, instrument_id: str) -> Quote | None:
        return self.routes[instrument_id].latest(instrument_id)

    def subscribe(self, instrument_ids: tuple[str, ...]) -> SubscriptionReceipt:
        receipts = []
        for port in self.ports:
            selected = tuple(key for key in instrument_ids if self.routes[key] is port)
            if selected:
                receipt = port.subscribe(selected)
                if not receipt.active:
                    return receipt
                receipts.append((port, receipt.subscription_id))
        key = uuid4().hex
        self.subscriptions[key] = tuple(receipts)
        return SubscriptionReceipt(key, instrument_ids, True, self.clock.now())

    def unsubscribe(self, subscription_id: str) -> None:
        for port, key in self.subscriptions.pop(subscription_id):
            port.unsubscribe(key)

    def drain_ticks(self, max_items: int) -> tuple[Tick, ...]:
        result: list[Tick] = []
        ports = self.ports[self.cursor :] + self.ports[: self.cursor]
        for port in ports:
            if len(result) == max_items:
                break
            result.extend(port.drain_ticks(max_items - len(result)))
        if self.ports:
            self.cursor = (self.cursor + 1) % len(self.ports)
        return tuple(result)


def attach_market(engine: TradingEngine) -> None:
    """Keep raw market connectors independent of account query cache wrappers."""
    if engine.live_market is not None:
        return
    # EngineFactory also accepts account-only ports. Discover the optional
    # market capability once at this composition boundary, before wrapping.
    if not all(callable(getattr(port, 'drain_ticks', None)) for port in engine.gateways.values()):
        return
    config = engine.configuration
    routes = {
        spec.instrument_id: engine.gateways[config.stock_account_ref if spec.market is Market.STOCK else config.futures_account_ref]
        for spec in engine.catalog.instruments
    }
    market = RoutedMarketData(routes, engine.clock)
    # Transfer bootstrap-owned subscriptions to the shared service so receipt
    # capacity and future removals have one owner. Ports without a receipt
    # inventory have no bootstrap subscriptions to transfer.
    for port in market.ports:
        for receipt in tuple(getattr(port, 'subscriptions', ())):
            port.unsubscribe(receipt)
    engine.live_market = LiveMarketService(market, engine.clock, CalendarResolver(engine), calendar=engine.calendar)
