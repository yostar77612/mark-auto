"""App-owned SIM capital and durable manual intent; never research authority."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from .manual_contracts import ManualPurpose, ManualScope
from quantlab.trading.domain.models import AccountSnapshot, Environment, HoldingKind, HoldingPolicy, Market, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine

ZERO = Decimal('0')
MANUAL_PREFIX = 'manual-sim-'
CAPACITY_SOURCE = 'APP_VIRTUAL_SIMULATION'


@dataclass(frozen=True)
class ManualBook:
    book_id: str
    account_ref: str
    capital: Decimal
    opening_day: date
    halted: bool = False
    reasons: tuple[str, ...] = ()
    test_status: str = 'UNTESTED'
    test_reason: str = ''
    source: str = CAPACITY_SOURCE
    market: Market | None = None


@dataclass(frozen=True)
class ManualRequest:
    scope: ManualScope
    request_id: str
    operation: str
    form_hash: str
    purpose: ManualPurpose = ManualPurpose.MANUAL
    plan: OrderPlan | None = None
    policy: HoldingPolicy = HoldingPolicy(HoldingKind.CUSTOM, 0, 0)
    order_id: str = ''
    price: Decimal | None = None
    status: str = 'PENDING'
    outcome_known: bool = False
    reason: str = ''


@dataclass(frozen=True)
class ManualReceivable:
    account_ref: str
    event_id: str
    amount: Decimal
    available_on: date
    source: str = 'APP_VIRTUAL_STOCK_SALE_CONSERVATIVE_T_PLUS_2'


@dataclass(frozen=True)
class ManualAcquisition:
    lot_id: str
    event_id: str
    quantity: int
    available_on: date
    source: str = 'APP_OWNED_CASH_FILL_CONSERVATIVE_T_PLUS_2'


@dataclass(frozen=True)
class ManualRiskCapacity(AccountSnapshot):
    """Internal RiskService input; never a broker/account-view financial fact."""

    source: str = CAPACITY_SOURCE


def book_for(engine: 'TradingEngine', account_ref: str) -> ManualBook | None:
    return next((book for book in engine.state.manual_books if book.account_ref == account_ref), None)


def manual_market(engine: 'TradingEngine', account_ref: str) -> Market:
    book = book_for(engine, account_ref)
    if book is not None and book.market is not None:
        return book.market
    cached = getattr(engine, 'manual_markets', {})
    if account_ref in cached:
        return cached[account_ref]
    markets = engine.gateways[account_ref].inspect(account_ref).markets
    if len(markets) != 1 or next(iter(markets)) not in (Market.STOCK, Market.INDEX_FUTURE):
        raise DomainError('capability_missing', 'one explicit market per native account required')
    return next(iter(markets))


def request_for(engine: 'TradingEngine', request_id: str) -> ManualRequest | None:
    return next((request for request in engine.state.manual_requests if request.request_id == request_id), None)


def manual_plan_request(engine: 'TradingEngine', plan: OrderPlan, key: str) -> ManualRequest | None:
    request = request_for(engine, key)
    if request is None or request.operation != 'SUBMIT' or request.plan is None:
        return None
    if request.plan != plan or request.scope.account_ref != plan.account_ref or request.scope.environment is not plan.environment:
        raise DomainError('state_conflict', 'durable manual intent economics changed')
    return request


def manual_policy() -> HoldingPolicy:
    # A manual risk estimate is not an automatic stop or a deployed strategy.
    return HoldingPolicy(HoldingKind.CUSTOM, 0, 0)


def diagnostic_passed(engine: 'TradingEngine', generation: str) -> bool:
    for request in engine.state.manual_requests:
        if (
            request.operation == 'SUBMIT'
            and request.purpose is ManualPurpose.DIAGNOSTIC_TMF
            and request.scope.connection_generation == generation
            and request.outcome_known
            and request.status == 'CANCELED'
        ):
            order = next((row for row in engine.state.orders if row.order_id == request.order_id), None)
            if order is not None and order.broker_ref and order.status is OrderStatus.CANCELED and order.filled == 0:
                return True
    return False


def manual_net_pnl(engine: 'TradingEngine', book: ManualBook) -> Decimal:
    lots = tuple(lot for lot in engine.state.positions if lot.strategy_id == book.book_id)
    entry_costs = sum((order.costs for order in engine.state.orders if order.plan.strategy_id == book.book_id and not order.plan.reduce_only), ZERO)
    result = sum((lot.realized_pnl for lot in lots), ZERO) - entry_costs
    for lot in lots:
        if lot.quantity:
            quote = engine.quotes.get(lot.instrument_id)
            if (
                quote is None
                or quote.quality != 'VERIFIED'
                or not 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
                or not 0 <= (engine.clock.now() - quote.received_at).total_seconds() <= 30
            ):
                raise DomainError('stale_quote')
            spec = engine.catalog.resolve(lot.instrument_id)
            result += (quote.last - lot.entry_price) * lot.quantity * spec.multiplier * (1 if lot.direction is Side.BUY else -1)
    return result


def manual_capacity(engine: 'TradingEngine', book: ManualBook) -> ManualRiskCapacity:
    lots = tuple(lot for lot in engine.state.positions if lot.strategy_id == book.book_id)
    entry_costs = sum((order.costs for order in engine.state.orders if order.plan.strategy_id == book.book_id and not order.plan.reduce_only), ZERO)
    realized = sum((lot.realized_pnl for lot in lots), ZERO) - entry_costs
    owned = ZERO
    for lot in lots:
        if lot.quantity:
            spec = engine.catalog.resolve(lot.instrument_id)
            if spec.market is Market.STOCK:
                owned += lot.entry_price * lot.quantity
            else:
                if spec.margin is None:
                    raise DomainError('instrument_unresolved', 'verified futures margin required')
                owned += spec.margin * lot.quantity
    cash = max(ZERO, book.capital + realized)
    unsettled = sum(
        (row.amount for row in engine.state.manual_receivables if row.account_ref == book.account_ref and row.available_on > engine.state.trading_day), ZERO
    )
    return ManualRiskCapacity(
        book.account_ref,
        Environment.BROKER_SIMULATION,
        max(ZERO, book.capital + manual_net_pnl(engine, book)),
        book.capital,
        cash,
        cash,
        unsettled,
        owned,
        engine.clock.now(),
        engine.state.version,
    )


def manual_stock_availability(engine: 'TradingEngine'):
    positions = []
    books = {book.book_id for book in engine.state.manual_books}
    for lot in engine.state.positions:
        if lot.strategy_id not in books or engine.catalog.resolve(lot.instrument_id).market is not Market.STOCK:
            positions.append(lot)
            continue
        entry = next((order for order in engine.state.orders if order.order_id == lot.lot_id), None)
        matured = sum(row.quantity for row in engine.state.manual_acquisitions if row.lot_id == lot.lot_id and row.available_on <= engine.state.trading_day)
        eligible = min(lot.quantity, max(0, matured - entry.released_quantity)) if entry and lot.direction is Side.BUY else 0
        # Pending owned exits are subtracted once by the existing ExitCoordinator.
        # This is a conservative app-owned availability, not a broker free-share
        # field or permission to sell external/pledged/same-day inventory.
        from dataclasses import replace

        positions.append(replace(lot, sellable_quantity=eligible))
    return tuple(positions)


def assert_manual_plan(engine: 'TradingEngine', request: ManualRequest, plan: OrderPlan) -> ManualBook:
    book = book_for(engine, plan.account_ref)
    if engine.configuration.environment is not Environment.BROKER_SIMULATION or book is None or plan.strategy_id != book.book_id:
        raise DomainError('capability_missing', 'confirmed simulation manual book required')
    validator = getattr(engine, 'manual_scope_validator', None)
    if not callable(validator):
        raise DomainError('capability_missing', 'accepted session scope required')
    validator(request.scope)
    observations = getattr(engine, 'manual_observations', {})
    if set(observations) != set(engine.gateways) or any(not 0 <= (engine.clock.now() - row.as_of).total_seconds() <= 30 for row in observations.values()):
        raise DomainError('manual_account_observation_required')
    if not plan.reduce_only:
        if book.halted or engine.state.stopped or not engine.state.reconciled:
            raise DomainError('risk_rejected', 'manual new risk is stopped')
        if book.opening_day != engine.state.trading_day:
            raise DomainError('manual_day_baseline_required')
        if not diagnostic_passed(engine, request.scope.connection_generation) and request.purpose is not ManualPurpose.DIAGNOSTIC_TMF:
            raise DomainError('manual_futures_test_required' if manual_market(engine, plan.account_ref) is Market.STOCK else 'manual_test_required')
    return book


def manual_risk_context(engine: 'TradingEngine', request: ManualRequest, plan: OrderPlan):
    assert_manual_plan(engine, request, plan)
    accounts = tuple(manual_capacity(engine, current) for current in engine.state.manual_books)
    account = next(row for row in accounts if row.account_ref == plan.account_ref)
    capability = engine.gateways[plan.account_ref].inspect(plan.account_ref)
    # This is the app's explicitly authorized SIM attempt policy. It is not a
    # claim that a signed account or login proves trading-key permission.
    if capability.environment is not Environment.BROKER_SIMULATION or not capability.can_trade:
        raise DomainError('capability_missing')
    pnl = sum((manual_net_pnl(engine, current) for current in engine.state.manual_books), ZERO)
    return account, accounts, capability, pnl
