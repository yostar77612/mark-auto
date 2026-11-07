"""Read models assembled from application state, never writable projections."""

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING

from .contracts import (
    AutomaticView,
    DailyIntentView,
    AccountRiskView,
    AccountView,
    MarketView,
    OrderView,
    OverviewMarketSummary,
    PerformanceView,
    PositionView,
    StrategyProductView,
    StrategyView,
    UiState,
)
from .errors import ERROR_TABLE
from .daily_signal_data import daily_signal_views
from quantlab.trading.domain.models import Environment, HoldingKind, Market, Side
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.policies import holding_window
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.freshness import Freshness, classify_freshness
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


def _order_trading_day(engine: 'TradingEngine', order):
    record = next((row for row in engine.state.strategies if (row.strategy_id, row.version) == (order.plan.strategy_id, order.plan.strategy_version)), None)
    calendar = engine.calendar
    if record is not None and record.parameters is not None and engine.configuration.environment is Environment.BROKER_SIMULATION:
        calendar = engine._strategy_calendar(record, order.plan.instrument_id)
    return next((session.trade_date for session in calendar.sessions if session.opens_at <= order.plan.decision_at <= session.closes_at), None)


@decimal_operation
def snapshot(engine: 'TradingEngine') -> UiState:
    from quantlab.trading.domain.strategy import is_tmf, resolve_tmf_near
    from quantlab.trading.domain.risk import AccountRiskLimits
    from .account_risk import account_net_mark, account_position_count, m2_account_refs

    from .auto_strategy_service import auto_strategy_views

    state = engine.state
    verified = _financial_facts_current(engine)
    tracks = {(track.strategy_id, track.version): track for track in state.performance_tracks}
    market_watch = engine.live_market.views() if engine.live_market is not None else ()
    health = {view.instrument_id: view.health.freshness for view in market_watch}
    resolved, blocked = {}, {}
    for record in state.strategies:
        reference = record.strategy_id, record.version
        resolved[reference] = record.form.instrument_id
        if record.parameters is not None and record.parameters.instrument_rule == 'TMF_NEAR':
            try:
                resolved[reference] = resolve_tmf_near(engine.catalog.instruments, engine.calendar, state.trading_day).instrument_id
            except DomainError as error:
                resolved[reference], blocked[reference] = '', error.code
    order_days = {order.order_id: _order_trading_day(engine, order) for order in state.orders}
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
            today_order_count=None
            if any(order_days[o.order_id] is None for o in state.orders if (o.plan.strategy_id, o.plan.strategy_version) == (s.strategy_id, s.version))
            else sum(
                order_days[o.order_id] == state.trading_day for o in state.orders if (o.plan.strategy_id, o.plan.strategy_version) == (s.strategy_id, s.version)
            ),
            today_pnl=(
                tracks[s.strategy_id, s.version].equity - tracks[s.strategy_id, s.version].daily_baseline
                if verified
                and (s.strategy_id, s.version) in tracks
                and tracks[s.strategy_id, s.version].trade_date == state.trading_day
                and tracks[s.strategy_id, s.version].daily_baseline is not None
                else None
            ),
            activity_state=(
                s.state
                if s.state != 'ACTIVE'
                else 'RISK_STOPPED'
                if state.trading_day in state.daily_locks
                else 'PAUSED'
                if state.stopped
                or not state.reconciled
                or state.engine_closed
                or (s.parameters is not None and state.environment is Environment.BROKER_SIMULATION and state.automatic.auto_paused)
                or (s.strategy_id, s.version) in blocked
                else 'RUNNING'
            ),
            parameters=s.parameters,
            recent_signal=s.recent_signal,
            margin_source=(
                (
                    'BROKER'
                    if engine.catalog.resolve(resolved[s.strategy_id, s.version]).margin is not None
                    and resolved[s.strategy_id, s.version] not in getattr(engine, 'unverified_automatic_margins', ())
                    else 'BUILTIN_CONSERVATIVE'
                )
                if resolved[s.strategy_id, s.version]
                else 'UNKNOWN'
            )
            if s.parameters is not None and s.form.market is not Market.STOCK
            else '',
            resolved_instrument_id=resolved[s.strategy_id, s.version],
            entry_block_code=blocked.get((s.strategy_id, s.version), ''),
        )
        for s in state.strategies
        if s.state != 'DELETED'
    )
    positions = []
    gross_marks: dict[str, Decimal | None] = {}
    for lot in state.positions:
        if not lot.quantity:
            continue
        spec = engine.catalog.resolve(lot.instrument_id)
        quote = engine.quotes.get(lot.instrument_id)
        freshness = (
            Freshness(health[lot.instrument_id])
            if lot.instrument_id in health
            else classify_freshness(
                quote.received_at if quote else None,
                now=engine.clock.now(),
                connected=True,
                in_session=any(session.opens_at <= engine.clock.now() <= session.closes_at for session in engine.calendar.sessions),
            )
        )
        if quote is None or quote.quality != 'VERIFIED':
            freshness = Freshness.UNKNOWN
        signed_quantity = lot.quantity * (1 if lot.direction is Side.BUY else -1)
        # Preserve PerformanceView's existing 30-second coverage contract while
        # calculating each gross mark only once. Dashboard coverage is stricter:
        # its shared LIVE classification must also permit displaying that mark.
        performance_live = (
            verified
            and quote is not None
            and quote.quality == 'VERIFIED'
            and 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
            and 0 <= (engine.clock.now() - quote.received_at).total_seconds() <= 30
        )
        gross_marks[lot.lot_id] = (
            unrealized_pnl(
                quote.last,
                signed_quantity,
                spec,
                lot.entry_price * signed_quantity * spec.multiplier,
                freshness=Freshness.LIVE if performance_live else Freshness.UNKNOWN,
            )
            if quote is not None
            else None
        )
        pnl = gross_marks[lot.lot_id] if freshness is Freshness.LIVE else None
        try:
            window = holding_window(lot.policy, lot.holding_origin, engine.calendar)
            exit_window = f'{window.earliest_normal_exit} ~ {window.latest_exit}'
            held = engine.calendar.age(lot.holding_origin, state.trading_day)
        except DomainError:
            exit_window, held = 'CALENDAR_MISSING', 0
        protection = 'EXIT_BLOCKED' if not lot.sellable_quantity else 'LOCAL_DAY_ONLY'
        if lot.strategy_id.startswith('manual-sim-'):
            protection = 'UNPROTECTED'
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
                unrealized_pnl=pnl,
                quote_freshness=freshness.value,
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
    for strategy in state.strategies:
        related = tuple(p for p in state.positions if (p.strategy_id, p.strategy_version) == (strategy.strategy_id, strategy.version))
        orders = tuple(o for o in state.orders if (o.plan.strategy_id, o.plan.strategy_version) == (strategy.strategy_id, strategy.version))
        costs = sum((o.costs for o in orders), ZERO)
        realized = sum((p.realized_pnl for p in related), ZERO) - sum((o.costs for o in orders if not o.plan.reduce_only), ZERO)
        unrealized: Decimal | None = ZERO
        for lot in related:
            if not lot.quantity:
                continue
            mark = gross_marks[lot.lot_id]
            if mark is None:
                unrealized = None
                break  # A partial version valuation is not its total unrealized PnL.
            unrealized += mark
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
    daily_loss_room = max(ZERO, Decimal('100000') * state.settings.daily_loss_fraction - max(ZERO, -state.daily_pnl))
    remaining = max(ZERO, daily_loss_room - reserved)
    quote_status = (
        'NO_DATA'
        if not markets or all(m.availability == 'NO_DATA' for m in markets)
        else 'FRESH'
        if all(m.availability == 'FRESH' for m in markets)
        else 'STALE'
    )
    strategies = tuple(
        replace(s, today_pnl=None)
        if any((p.strategy_id, p.strategy_version) == (s.strategy_id, s.version) and p.unrealized_pnl is None for p in positions)
        else s
        for s in strategies
    )
    unrealized_total = None if not verified or any(p.unrealized_pnl is None for p in positions) else sum((p.unrealized_pnl for p in positions), ZERO)
    fills = [o for o in state.orders if o.filled and (o.fill_count_day is None or o.fill_count_day == state.trading_day)]
    today_fills = None if any(o.daily_fill_count is None for o in fills) else sum(o.daily_fill_count for o in fills)
    account_risks = []
    for reference in sorted(m2_account_refs(engine)):
        limits = next((row for row in state.account_risk_limits if row.account_ref == reference), AccountRiskLimits(reference))
        book = next((row for row in state.manual_books if row.account_ref == reference), None)
        allocation = (
            book.capital
            if book is not None
            else state.settings.stock_allocation
            if reference == engine.configuration.stock_account_ref
            else state.settings.futures_allocation
        )
        baseline = next((row for row in state.account_daily_baselines if row.account_ref == reference and row.trade_date == state.trading_day), None)
        reasons = []
        pnl = None
        if baseline is None:
            reasons.append('account_daily_baseline_required')
        else:
            try:
                pnl = account_net_mark(engine, reference) - baseline.previous_close_pnl
            except DomainError as error:
                reasons.append(error.code)
        if (reference, state.trading_day) in state.account_daily_locks:
            reasons.append('account_daily_loss_limit')
        account_risks.append(
            AccountRiskView(
                reference,
                limits,
                pnl,
                allocation * limits.daily_loss_fraction,
                account_position_count(engine, reference),
                state.stopped or bool(reasons),
                tuple(reasons),
            )
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
        auto_strategies=auto_strategy_views(state),
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
        market_watch=market_watch,
        market_health=engine.live_market.overview() if engine.live_market is not None else OverviewMarketSummary(),
        unrealized_pnl=unrealized_total,
        remaining_daily_loss=daily_loss_room if verified else None,
        today_fill_count=today_fills,
        account_risks=tuple(account_risks),
        preflight=state.preflight,
        automatic=AutomaticView(
            'PAUSED_WAITING_RESUME' if state.automatic.auto_paused else 'WAITING_SESSION' if state.automatic.daily.waiting_session else 'RUNNING',
            (*state.automatic.reasons, 'daily_waiting_session')
            if state.automatic.daily.waiting_session and not state.automatic.auto_paused
            else state.automatic.reasons,
            state.automatic.evaluations,
            tuple(
                DailyIntentView(
                    row.cursor.strategy_id,
                    row.cursor.version,
                    row.instrument_id,
                    row.action,
                    row.lot_id,
                    row.cursor.bar_end,
                    row.created_at,
                    row.target_trade_date.isoformat(),
                    row.not_before,
                    row.deadline,
                    row.phase,
                    row.order_id,
                    row.code,
                    row.key,
                )
                for row in state.automatic.daily.intents
            ),
            min((row.not_before for row in state.automatic.daily.intents if row.phase == 'READY' and engine.clock.now() < row.deadline), default=None),
            daily_signal_data=daily_signal_views(engine),
        ),
        strategy_products=tuple(
            StrategyProductView(
                spec.instrument_id,
                spec.market,
                (HoldingKind.SWING, HoldingKind.POSITION, HoldingKind.CUSTOM) if spec.market is Market.STOCK else (HoldingKind.INTRADAY, HoldingKind.CUSTOM),
                stock_intraday_optional=spec.market is Market.STOCK,
            )
            for spec in engine.catalog.instruments
            if spec.market is Market.STOCK or is_tmf(spec)
        ),
    )
