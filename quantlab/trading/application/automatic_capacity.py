"""One confirmed app-owned SIM pool for manual and automatic execution."""

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING

from quantlab.trading.application.manual_book import CAPACITY_SOURCE, ManualRiskCapacity, manual_allocations_valid
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import Environment, Market, OrderStatus, Side
from quantlab.trading.domain.strategy import effective_strategy_spec
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation

from .account_risk import account_net_mark

if TYPE_CHECKING:
    from quantlab.trading.application.engine import TradingEngine
    from quantlab.trading.application.state import StrategyRecord
    from quantlab.trading.domain.models import OrderPlan

ZERO = Decimal('0')
UNRESOLVED = frozenset((OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING))


@decimal_operation
def automatic_capacity(engine: 'TradingEngine', account_ref: str, *, for_exit: bool = False) -> ManualRiskCapacity:
    """Reuse one confirmed virtual pool, including all recorded account ownership.

    ``for_exit`` is only for reduction preview. Its equity is the realized app
    ledger value, never broker net liquidation; reduction admission needs no
    unrelated market marks, margin facts, or additional spending capacity.
    """
    if engine.configuration.environment is not Environment.BROKER_SIMULATION:
        raise DomainError('production_orders_disabled' if engine.configuration.environment is Environment.LIVE else 'capability_missing')
    books = tuple(book for book in engine.state.manual_books if book.account_ref == account_ref)
    if len(books) != 1 or books[0].source != CAPACITY_SOURCE:
        raise DomainError('manual_book_not_enabled', 'one confirmed virtual SIM book per account is required')
    book = books[0]
    lots = tuple(lot for lot in engine.state.positions if lot.account_ref == account_ref)
    entry_costs = sum((order.costs for order in engine.state.orders if order.plan.account_ref == account_ref and not order.plan.reduce_only), ZERO)
    realized = sum((lot.realized_pnl for lot in lots), ZERO) - entry_costs
    owned = ZERO
    for lot in lots:
        if for_exit or not lot.quantity:
            continue
        spec = engine.catalog.resolve(lot.instrument_id)
        if spec.market is Market.STOCK:
            owned += lot.entry_price * lot.quantity
        else:
            record = next((row for row in engine.state.strategies if (row.strategy_id, row.version) == (lot.strategy_id, lot.strategy_version)), None)
            if record is not None and record.parameters is not None:
                if spec.instrument_id in getattr(engine, 'unverified_automatic_margins', frozenset()):
                    spec = replace(spec, margin=None)
                spec = effective_strategy_spec(spec)
            if spec.margin is None:
                raise DomainError('instrument_unresolved', 'unverified manual futures margin')
            owned += spec.margin * lot.quantity
    cash = max(ZERO, book.capital + realized)
    unsettled = sum(
        (row.amount for row in engine.state.manual_receivables if row.account_ref == account_ref and row.available_on > engine.state.trading_day), ZERO
    )
    return ManualRiskCapacity(
        account_ref,
        Environment.BROKER_SIMULATION,
        cash if for_exit else max(ZERO, book.capital + account_net_mark(engine, account_ref)),
        book.capital,
        cash,
        cash,
        unsettled,
        owned,
        engine.clock.now(),
        engine.state.version,
    )


def shared_sim_allocations(engine: 'TradingEngine') -> tuple[ManualRiskCapacity, ...]:
    """Every confirmed book shares the configured stock/futures/platform caps."""
    if not manual_allocations_valid(engine):
        raise DomainError('manual_allocation_exceeds_settings')
    return tuple(automatic_capacity(engine, book.account_ref) for book in engine.state.manual_books)


@decimal_operation
def automatic_daily_pnl(engine: 'TradingEngine') -> Decimal:
    """Shared SIM day mark from exact account closes; never sample a new close."""
    pnl = ZERO
    for book in engine.state.manual_books:
        baseline = next(
            (row for row in engine.state.account_daily_baselines if row.account_ref == book.account_ref and row.trade_date == engine.state.trading_day),
            None,
        )
        if baseline is None:
            raise DomainError('account_daily_baseline_required')
        pnl += account_net_mark(engine, book.account_ref) - baseline.previous_close_pnl
    return pnl


def assert_automatic_observation(engine: 'TradingEngine', account_ref: str, *, reduce_only: bool = False) -> None:
    """Admit new risk only with complete same-owner cached observations.

    Runtime injects automatic_observation_validator(account_ref, observation).
    It checks current SDK generation/selection against the accepted owner stamp;
    it must not perform an SDK query. Reductions validate only their current account here; the risk context
    also validates their instrument quantity against that observation.
    """
    if engine.configuration.environment is not Environment.BROKER_SIMULATION:
        raise DomainError('production_orders_disabled' if engine.configuration.environment is Environment.LIVE else 'capability_missing')
    if account_ref not in engine.gateways:
        raise DomainError('capability_missing', 'configured automatic account required')
    observations = getattr(engine, 'manual_observations', {})
    if not reduce_only and set(observations) != set(engine.gateways):
        raise DomainError('manual_account_observation_required', 'every configured account must be observed')
    validator = getattr(engine, 'automatic_observation_validator', None)
    if not callable(validator):
        raise DomainError('capability_missing', 'current owner generation validator required')
    selected = (
        {account_ref: observations.get(account_ref) or getattr(engine, 'manual_protective_observations', {}).get(account_ref)} if reduce_only else observations
    )
    for reference, row in selected.items():
        if (
            not isinstance(row, ManualAccountObservation)
            or row.account_ref != reference
            or row.environment is not Environment.BROKER_SIMULATION
            or not 0 <= (engine.clock.now() - row.as_of).total_seconds() <= 30
        ):
            raise DomainError('manual_account_observation_required', 'fresh complete same-account SIM observation required')
        validator(reference, row)
        if not reduce_only and (row.unmapped or any(order.status in UNRESOLVED for order in row.orders)):
            raise DomainError('reconciliation_required', 'remote order outcome remains unresolved')
    if not reduce_only and (not engine.state.reconciled or any(order.status in UNRESOLVED for order in engine.state.orders)):
        raise DomainError('reconciliation_required', 'all shared-budget order outcomes must be reconciled')


def _assert_exit_scope(engine: 'TradingEngine', plan: 'OrderPlan') -> None:
    """An unrelated quarantine cannot block a proven owned-instrument reduction."""
    if any(row.account_ref == plan.account_ref and row.instrument_id == plan.instrument_id for row in engine.state.reconciliation):
        raise DomainError('reconciliation_required', 'exit instrument remains quarantined')
    observation = engine.manual_observations.get(plan.account_ref) or getattr(engine, 'manual_protective_observations', {}).get(plan.account_ref)
    if any(
        row.plan.account_ref == plan.account_ref and row.plan.instrument_id == plan.instrument_id and row.status in UNRESOLVED
        for row in (*engine.state.orders, *observation.orders)
    ):
        raise DomainError('reconciliation_required', 'exit instrument has an unresolved order')
    lots = tuple(
        row for row in engine.state.positions if row.account_ref == plan.account_ref and row.instrument_id == plan.instrument_id and row.origin == 'MANAGED'
    )
    expected = sum(row.quantity * (1 if row.direction is Side.BUY else -1) for row in lots)
    observed = tuple(row for row in observation.positions if row.instrument_id == plan.instrument_id and row.quantity)
    if len(observed) > 1 or expected != sum(row.quantity for row in observed) or any(row.unit is not plan.unit for row in observed):
        raise DomainError('reconciliation_required', 'exit instrument quantity is not confirmed')


@decimal_operation
def automatic_risk_context(engine: 'TradingEngine', plan: 'OrderPlan', record: 'StrategyRecord'):
    """Native automatic SIM admission; the engine retains baseline/preflight gates."""
    engine.assert_execution_allowed()
    if plan.environment is not Environment.BROKER_SIMULATION:
        raise DomainError('production_orders_disabled' if plan.environment is Environment.LIVE else 'capability_missing')
    if (
        record is None
        or record.parameters is None
        or (record.strategy_id, record.version) != (plan.strategy_id, plan.strategy_version)
        or record.form.account_ref != plan.account_ref
        or record.form.environment is not plan.environment
    ):
        raise DomainError('capability_missing', 'matching typed automatic deployment required')
    assert_automatic_observation(engine, plan.account_ref, reduce_only=plan.reduce_only)
    if plan.reduce_only:
        _assert_exit_scope(engine, plan)
        account = automatic_capacity(engine, plan.account_ref, for_exit=True)
        allocations, pnl = (account,), ZERO
    else:
        entry_validator = getattr(engine, 'automatic_entry_validator', None)
        if not callable(entry_validator):
            raise DomainError('capability_missing', 'current automatic entry proof required')
        entry_validator(plan.account_ref)
        if engine.state.automatic.auto_paused:
            raise DomainError('automatic_paused')
        allocations = shared_sim_allocations(engine)
        account = next((row for row in allocations if row.account_ref == plan.account_ref), None)
        if account is None:
            raise DomainError('manual_book_not_enabled')
        pnl = automatic_daily_pnl(engine)
    capability = engine.gateways[plan.account_ref].inspect(plan.account_ref)
    return account, allocations, capability, pnl
