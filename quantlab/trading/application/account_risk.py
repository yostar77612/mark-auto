"""Account-scoped limits and valuation across every app-owned strategy.

Accounts adopt these limits with their first typed strategy, including tombstones.
Call for every new entry on adopted accounts, preserving existing manual guards.
"""

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING

from quantlab.trading.application.performance import unrealized_liquidation
from quantlab.trading.application.state import ACTIVE
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import Environment, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError

from quantlab.trading.domain.risk import AccountDailyBaseline, AccountRiskLimits, check_account_entry

if TYPE_CHECKING:
    from quantlab.trading.application.engine import TradingEngine

ZERO = Decimal('0')


def seed_account_baseline(engine: 'TradingEngine', account_ref: str) -> tuple[AccountDailyBaseline, ...]:
    """Only a proven zero genesis may supply an account's first daily baseline."""
    baselines = engine.state.account_daily_baselines
    if any(row.account_ref == account_ref for row in baselines):
        return baselines  # Neither a new version nor a new day resets history.
    positions = tuple(lot for lot in engine.state.positions if lot.account_ref == account_ref)
    orders = tuple(order for order in engine.state.orders if order.plan.account_ref == account_ref)
    if positions:
        return baselines  # Includes closed lots with realized history.
    source = 'EMPTY_LEDGER_GENESIS'
    if orders:
        from .manual_contracts import ManualPurpose

        book = next((row for row in engine.state.manual_books if row.account_ref == account_ref), None)
        if (
            engine.configuration.environment is not Environment.BROKER_SIMULATION
            or book is None
            or book.opening_day != engine.state.trading_day
            or book.source != 'APP_VIRTUAL_SIMULATION'
        ):
            return baselines
        diagnostics = {
            row.order_id
            for row in engine.state.manual_requests
            if row.scope.account_ref == account_ref and row.purpose is ManualPurpose.DIAGNOSTIC_TMF and row.outcome_known
        }
        for order in orders:
            if (
                order.status is not OrderStatus.CANCELED
                or order.filled
                or order.costs
                or order.order_id not in diagnostics
                or order.plan.strategy_id != book.book_id
            ):
                return baselines
            if not any(
                session.trade_date == engine.state.trading_day and session.kind == 'DAY' and session.opens_at <= order.plan.decision_at <= session.closes_at
                for session in engine.calendar.sessions
            ):
                return baselines
        source = 'APP_VIRTUAL_SIMULATION_GENESIS'
    return (*baselines, AccountDailyBaseline(account_ref, engine.state.trading_day, ZERO, source))


def halt_account_risk(engine: 'TradingEngine', plan: OrderPlan, code: str) -> None:
    """Persist denied new risk without touching independently legal reductions."""
    if plan.reduce_only:
        return
    locks = engine.state.account_daily_locks
    latch = (plan.account_ref, engine.state.trading_day)
    if code == 'account_daily_loss_limit' and latch not in locks:
        locks = (*locks, latch)
    engine._persist(
        'account_entry_risk_stopped',
        replace(engine.state, stopped=True, issues=tuple(sorted(set((*engine.state.issues, code)))), account_daily_locks=locks),
    )


@decimal_operation
def account_net_mark(engine: 'TradingEngine', account_ref: str) -> Decimal:
    """All account ownership, including manual, retired and realized closed lots."""
    positions = tuple(lot for lot in engine.state.positions if lot.account_ref == account_ref)
    for lot in positions:
        if lot.quantity:
            quote = engine.quotes.get(lot.instrument_id)
            if quote is not None and (quote.quality != 'VERIFIED' or not 0 <= (engine.clock.now() - quote.received_at).total_seconds() <= 30):
                raise DomainError('stale_quote', 'account position valuation is not current')
    entry_costs = sum((order.costs for order in engine.state.orders if order.plan.account_ref == account_ref and not order.plan.reduce_only), ZERO)
    return sum((lot.realized_pnl + unrealized_liquidation(engine, lot) for lot in positions), ZERO) - entry_costs


def account_position_scopes(engine: 'TradingEngine', account_ref: str) -> frozenset[tuple[str, Side]]:
    """Pending entries own a position slot, including UNKNOWN and cancellation."""
    positions = {(lot.instrument_id, lot.direction) for lot in engine.state.positions if lot.account_ref == account_ref and lot.quantity}
    positions.update(
        (order.plan.instrument_id, order.plan.side)
        for order in engine.state.orders
        if order.plan.account_ref == account_ref and not order.plan.reduce_only and order.status in ACTIVE
    )
    return frozenset(positions)


def account_position_count(engine: 'TradingEngine', account_ref: str) -> int:
    return len(account_position_scopes(engine, account_ref))


def m2_account_refs(engine: 'TradingEngine') -> frozenset[str]:
    """Typed versions or explicitly saved limits adopt every account entry route."""
    typed = frozenset(row.form.account_ref for row in engine.state.strategies if row.parameters is not None)
    return typed | frozenset(row.account_ref for row in engine.state.account_risk_limits)


def _account_limits(engine: 'TradingEngine', account_ref: str) -> AccountRiskLimits:
    return next((row for row in engine.state.account_risk_limits if row.account_ref == account_ref), AccountRiskLimits(account_ref))


def _account_baseline(engine: 'TradingEngine', account_ref: str) -> AccountDailyBaseline | None:
    return next((row for row in engine.state.account_daily_baselines if row.account_ref == account_ref and row.trade_date == engine.state.trading_day), None)


def _configured_allocation(engine: 'TradingEngine', account_ref: str) -> Decimal:
    """Read confirmed application capacity; monitoring never queries SDK balances."""
    book = next((row for row in engine.state.manual_books if row.account_ref == account_ref), None)
    if book is not None:
        return book.capital
    settings = engine.state.settings
    return settings.stock_allocation if account_ref == engine.configuration.stock_account_ref else settings.futures_allocation


@decimal_operation
def account_entry_rejection(engine: 'TradingEngine', plan: OrderPlan, *, allocated_cash: Decimal | None = None) -> str:
    """Check account limits without changing state or resetting dated latches."""
    if plan.reduce_only:
        return ''
    if plan.account_ref not in m2_account_refs(engine):
        return ''
    if (plan.account_ref, engine.state.trading_day) in engine.state.account_daily_locks:
        return 'account_daily_loss_limit'
    baseline = _account_baseline(engine, plan.account_ref)
    if baseline is None:
        return 'account_daily_baseline_required'
    limits = _account_limits(engine, plan.account_ref)
    scopes = account_position_scopes(engine, plan.account_ref)
    spec = engine.catalog.resolve(plan.instrument_id)
    return check_account_entry(
        limits,
        engine.account(plan.account_ref).allocated_cash if allocated_cash is None else allocated_cash,
        account_net_mark(engine, plan.account_ref) - baseline.previous_close_pnl,
        plan.limit_price * plan.quantity * spec.multiplier,
        len(scopes),
        (plan.instrument_id, plan.side) not in scopes,
    )


@decimal_operation
def observe_account_limits(engine: 'TradingEngine') -> None:
    """Latch account loss without a signal or order; missing close stays pending."""
    state = engine.state
    locks = set(state.account_daily_locks)
    reasons: set[str] = set()
    for account_ref in sorted(m2_account_refs(engine)):
        if (account_ref, state.trading_day) in locks:
            reasons.add('account_daily_loss_limit')
            continue
        allocation = _configured_allocation(engine, account_ref)
        if allocation <= ZERO and not account_position_scopes(engine, account_ref):
            continue  # Disabled unused accounts do not turn zero PnL into a loss.
        baseline = _account_baseline(engine, account_ref)
        if baseline is None:
            reasons.add('account_daily_baseline_required')
            continue
        try:
            daily_pnl = account_net_mark(engine, account_ref) - baseline.previous_close_pnl
        except DomainError as exc:
            reasons.add(exc.code)
            continue
        code = check_account_entry(
            _account_limits(engine, account_ref),
            allocation,
            daily_pnl,
            ZERO,
            0,
            False,
        )
        if code:
            locks.add((account_ref, state.trading_day))
            reasons.add(code)
    if reasons:
        proposed = replace(state, stopped=True, issues=tuple(sorted(set(state.issues) | reasons)), account_daily_locks=tuple(sorted(locks)))
        if proposed != state:
            engine._persist('account_risk_observed', proposed)


def assert_account_resume(engine: 'TradingEngine', account_ref: str = '') -> None:
    """No resume path can clear today's loss stop or fabricate a daily baseline."""
    observe_account_limits(engine)
    adopted = m2_account_refs(engine)
    accounts = adopted & {account_ref} if account_ref else adopted
    for reference in sorted(accounts):
        if (reference, engine.state.trading_day) in engine.state.account_daily_locks:
            raise DomainError('account_daily_loss_limit')
        if _account_baseline(engine, reference) is None:
            raise DomainError('account_daily_baseline_required')
