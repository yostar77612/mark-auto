"""Read models assembled from application state, never writable projections."""

from decimal import Decimal
from typing import TYPE_CHECKING

from .contracts import AccountView, MarketView, OrderView, OverviewMarketSummary, PerformanceView, PositionView, StrategyView, UiState
from .errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment, Market, Side
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.policies import holding_window
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.quote_stats import unrealized_pnl

if TYPE_CHECKING:
    from .engine import TradingEngine

ZERO = Decimal('0')


def _financial_facts_current(engine: 'TradingEngine') -> bool:
    from .events import validate_observation

    if engine.configuration.environment is Environment.LOCAL:
        return True
    state, confirmed = engine.state, engine.confirmed_observations
    if not state.reconciled or state.daily_baseline_required or state.daily_baseline_evidence is None or confirmed is None:
        return False
    if {account for account, _ in confirmed[0]} != set(engine.gateways):
        return False
    try:
        for account, remote in confirmed[0]:
            validate_observation(engine, account, remote)
    except DomainError:
        return False
    return True


def policy_name(policy) -> str:
    return f'{policy.kind.value}:{policy.min_days}-{policy.max_days}'


@decimal_operation
def snapshot(engine: 'TradingEngine') -> UiState:
    state = engine.state
    strategies = tuple(
        StrategyView(
            s.strategy_id,
            s.form.name,
            s.version,
            s.form.market,
            s.form.instrument_id,
            s.policy.kind,
            policy_name(s.policy),
            s.state,
            s.form.account_ref,
            s.form.environment,
            ERROR_TABLE['strategy_evidence_stale'].explanation if s.evidence == 'SOURCE_PROFILE_CHANGED' else s.evidence,
            min(s.form.allocation, state.settings.stock_allocation if s.form.market is Market.STOCK else state.settings.futures_allocation),
            min(s.form.risk_fraction, state.settings.risk_fraction),
            s.form.expiry_action,
            s.form.roll_contract_id,
        )
        for s in state.strategies
    )
    positions = []
    for lot in state.positions:
        if not lot.quantity:
            continue
        spec = engine.catalog.resolve(lot.instrument_id)
        quote = engine.quotes.get(lot.instrument_id)
        try:
            window = holding_window(lot.policy, lot.holding_origin, engine.calendar)
            exit_window = f'{window.earliest_normal_exit} ~ {window.latest_exit}'
            held = engine.calendar.age(lot.holding_origin, state.trading_day)
        except DomainError:
            exit_window, held = 'CALENDAR_MISSING', 0
        protection = 'EXIT_BLOCKED' if not lot.sellable_quantity else 'LOCAL_DAY_ONLY'
        positions.append(
            PositionView(
                lot.lot_id,
                lot.instrument_id,
                lot.strategy_id,
                lot.strategy_version,
                policy_name(lot.policy),
                lot.quantity,
                spec.unit,
                lot.sellable_quantity,
                lot.entry_trade_date.isoformat(),
                held,
                exit_window,
                protection,
                quote.source_at.isoformat() if quote else '',
                lot.origin,
                lot.account_ref,
                lot.direction,
            )
        )
    markets = []
    for spec in engine.catalog.instruments:
        quote = engine.quotes.get(spec.instrument_id)
        fresh = quote is not None and 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
        markets.append(
            MarketView(
                spec.instrument_id,
                spec.market,
                spec.unit,
                quote.last if quote else None,
                quote.source_at.isoformat() if quote else '',
                'FRESH' if fresh else 'STALE' if quote else 'NO_DATA',
                quote.source if quote else 'LOCAL_SYNTHETIC' if state.environment is Environment.LOCAL else 'NO_DATA',
                spec.underlying,
                spec.delivery_month or '',
                spec.expiry.isoformat() if spec.expiry else '',
            )
        )
    performance = []
    verified = _financial_facts_current(engine)
    tracks = {(track.strategy_id, track.version): track for track in state.performance_tracks}
    for strategy in state.strategies:
        related = tuple(p for p in state.positions if (p.strategy_id, p.strategy_version) == (strategy.strategy_id, strategy.version))
        orders = tuple(o for o in state.orders if (o.plan.strategy_id, o.plan.strategy_version) == (strategy.strategy_id, strategy.version))
        costs = sum((o.costs for o in orders), ZERO)
        realized = sum((p.realized_pnl for p in related), ZERO) - sum((o.costs for o in orders if not o.plan.reduce_only), ZERO)
        unrealized: Decimal | None = ZERO
        for lot in related:
            if not lot.quantity:
                continue
            quote = engine.quotes.get(lot.instrument_id)
            if (
                not verified
                or quote is None
                or quote.quality != 'VERIFIED'
                or not 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
                or not 0 <= (engine.clock.now() - quote.received_at).total_seconds() <= 30
            ):
                unrealized = None
                break  # A partial version valuation is not its total unrealized PnL.
            spec = engine.catalog.resolve(lot.instrument_id)
            signed_quantity = lot.quantity * (1 if lot.direction is Side.BUY else -1)
            unrealized += unrealized_pnl(quote.last, signed_quantity, spec, lot.entry_price * signed_quantity * spec.multiplier, freshness=Freshness.LIVE)
        track = tracks.get((strategy.strategy_id, strategy.version))
        if track:
            realized += track.realized_adjustment
        performance.append(
            PerformanceView(
                strategy.strategy_id,
                strategy.version,
                strategy.form.market,
                policy_name(strategy.policy),
                state.environment,
                realized,
                unrealized,
                costs,
                track.max_drawdown if track else None,
                ','.join(str(engine.calendar.age(p.entry_trade_date, state.trading_day)) for p in related),
                'COMPLETE' if track and track.history_complete else 'LEGACY_UNKNOWN',
                track.last_at.isoformat() if track else '',
                attributed_pnl=track.equity if track and track.history_complete else None,
            )
        )
    accounts = tuple(
        AccountView(
            ref,
            state.environment,
            Market.STOCK if ref == engine.configuration.stock_account_ref else Market.INDEX_FUTURE,
            state.settings.stock_allocation if ref == engine.configuration.stock_account_ref else state.settings.futures_allocation,
            'LOCAL_READY' if state.environment is Environment.LOCAL else 'EXTERNAL_REQUIRED',
        )
        for ref in engine.gateways
    )
    status = 'CLOSED' if state.engine_closed else 'WAITING_RECONCILIATION' if not state.reconciled else 'STOPPED' if state.stopped else 'RUNNING'
    issues = tuple(ERROR_TABLE.get(code, ERROR_TABLE['operation_failed']).explanation for code in state.issues)
    reserved = sum((r.risk for r in engine.reservations()), ZERO)
    remaining = max(ZERO, Decimal('100000') * state.settings.daily_loss_fraction - max(ZERO, -state.daily_pnl) - reserved)
    quote_status = (
        'NO_DATA'
        if not markets or all(m.availability == 'NO_DATA' for m in markets)
        else 'FRESH'
        if all(m.availability == 'FRESH' for m in markets)
        else 'STALE'
    )
    return UiState(
        environment=state.environment,
        account_ref=state.account_ref,
        engine_state=status,
        policy_label=strategies[-1].policy_label if strategies else 'SWING:3-5',
        allocated_cash=state.settings.stock_allocation + state.settings.futures_allocation,
        daily_pnl=state.daily_pnl if verified else None,
        remaining_risk=remaining if verified else None,
        quote_status=quote_status,
        version=state.version,
        trading_day=state.trading_day.isoformat(),
        synthetic_data=state.environment is Environment.LOCAL,
        issues=issues,
        strategies=strategies,
        positions=tuple(positions),
        orders=tuple(
            OrderView(
                o.order_id, o.plan.instrument_id, o.plan.side, o.plan.quantity, o.filled, o.plan.unit, o.status.value, o.plan.reduce_only, o.plan.account_ref
            )
            for o in state.orders
        ),
        markets=tuple(markets),
        performance=tuple(performance),
        accounts=accounts,
        events=state.events,
        settings=state.settings,
        cost_version=engine.fees.version,
        risk_version=engine.risk().policy.version,
        quote_revision=engine.quote_count,
        broker_settings=state.broker_settings,
        broker_readiness=state.broker_readiness,
        reconciliation=state.reconciliation,
        reconciliation_verified=state.reconciled,
        financial_facts_verified=verified,
        market_revision=engine.live_market.market_revision if engine.live_market is not None else 0,
        market_watch=engine.live_market.views() if engine.live_market is not None else (),
        market_health=engine.live_market.overview() if engine.live_market is not None else OverviewMarketSummary(),
    )
