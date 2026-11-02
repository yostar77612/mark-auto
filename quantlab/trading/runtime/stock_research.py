"""Offline stock training composition; no broker, download or activation capability."""

from contextlib import closing

from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.stock_research import StockTaxTreatment
from quantlab.trading.application.stock_research_service import StockResearchService
from .market_connection import MarketClock
from .provenance import compute_profile
from .stock_history import compose_stock_history
from .stock_maintenance import StockMaintenanceStore


def run_stock_research(root, store, strategy, spec, calendar, start, end, *, stock_kind, day_trade=False, clock=None, cancelled=lambda: False):
    """Explicit tax eligibility; settings supply the same immutable FeeSchedule type.

    The dedicated journal never writes into the trading engine or marks a
    strategy deployable. A successful return means its artifact was committed.
    """
    initialize()
    clock = clock or MarketClock()
    treatment = StockTaxTreatment(stock_kind, day_trade)
    fees = StockMaintenanceStore(root).load().fees(stock_kind=stock_kind, day_trade=day_trade)
    profile = compute_profile()
    with closing(Ledger(root / 'official-stock-research.sqlite', 'official-stock-research-v1', clock.now())) as journal:
        service = StockResearchService(compose_stock_history(store), journal, clock, calendar, profile, profile_reader=compute_profile)
        return service.run(strategy, spec, start, end, fees, treatment, cancelled=cancelled)
