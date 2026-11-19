"""Read models assembled from application state, never writable projections."""

from bisect import bisect_right
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
from quantlab.trading.domain.calendar import TradingCalendar
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


def _session_day(calendar, moment, starts):
    """First session containing `moment`, as the former linear scan returned it."""
    sessions = calendar.sessions
    if type(calendar) is not TradingCalendar:
        return next((session.trade_date for session in sessions if session.opens_at <= moment <= session.closes_at), None)
    # TradingCalendar guarantees opens_at < closes_at and opens_at >= the previous closes_at, so the sessions
    # containing `moment` are a contiguous run ending at the last session that opens at or before it.
    cached = starts.get(id(calendar))
    if cached is None or cached[0] is not calendar:
        cached = starts[id(calendar)] = (calendar, [session.opens_at for session in sessions])
    index = bisect_right(cached[1], moment) - 1
    found = None
    while index >= 0 and sessions[index].closes_at >= moment:
        found = index
        index -= 1
    return sessions[found].trade_date if found is not None else None


def _order_trading_days(engine: 'TradingEngine') -> dict:
    state = engine.state
    records: dict = {}
    for row in state.strategies:
        records.setdefault((row.strategy_id, row.version), row)  # the first match, as next() found it
    starts: dict = {}
    days = {}
    for order in state.orders:
        record = records.get((order.plan.strategy_id, order.plan.strategy_version))
        calendar = engine.calendar
        if record is not None and record.parameters is not None and engine.configuration.environment is Environment.BROKER_SIMULATION:
            calendar = engine._strategy_calendar(record, order.plan.instrument_id)
        days[order.order_id] = _session_day(calendar, order.plan.decision_at, starts)
    return days


def _by_strategy(rows, plan: bool) -> dict:
    """Rows grouped by (strategy_id, version) in their original order."""
    groups: dict = {}
    for row in rows:
        key = (row.plan.strategy_id, row.plan.strategy_version) if plan else (row.strategy_id, row.strategy_version)
        groups.setdefault(key, []).append(row)
    return groups


def _resolved_instruments(engine: 'TradingEngine', state):
    from quantlab.trading.domain.strategy import resolve_tmf_near

    resolved, blocked = {}, {}
    for record in state.strategies:
        reference = record.strategy_id, record.version
        resolved[reference] = record.form.instrument_id
        if record.parameters is not None and record.parameters.instrument_rule == 'TMF_NEAR':
            try:
                resolved[reference] = resolve_tmf_near(engine.catalog.instruments, engine.calendar, state.trading_day).instrument_id
            except DomainError as error:
                resolved[reference], blocked[reference] = '', error.code
    return resolved, blocked


def _strategy_view(engine: 'TradingEngine', state, s, verified, tracks, order_days, orders, resolved, blocked) -> StrategyView:
    key = (s.strategy_id, s.version)
    track = tracks.get(key)
    instrument = resolved[key]
    return StrategyView(
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
        today_order_count=None if any(order_days[o.order_id] is None for o in orders) else sum(order_days[o.order_id] == state.trading_day for o in orders),
        today_pnl=(
            track.equity - track.daily_baseline
            if verified and track is not None and track.trade_date == state.trading_day and track.daily_baseline is not None
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
            or key in blocked
            else 'RUNNING'
        ),
        parameters=s.parameters,
        recent_signal=s.recent_signal,
        margin_source=(
            (
                'BROKER'
                if engine.catalog.resolve(instrument).margin is not None and instrument not in getattr(engine, 'unverified_automatic_margins', ())
                else 'BUILTIN_CONSERVATIVE'
            )
            if instrument
            else 'UNKNOWN'
        )
        if s.parameters is not None and s.form.market is not Market.STOCK
        else '',
        resolved_instrument_id=instrument,
        entry_block_code=blocked.get(key, ''),
    )


def _position_views(engine: 'TradingEngine', state, verified, health):
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
    return positions, gross_marks


def _market_views(engine: 'TradingEngine', state) -> list:
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
    return markets


def _performance_views(engine: 'TradingEngine', state, tracks, gross_marks, orders_by_strategy, lots_by_strategy) -> list:
    performance = []
    for strategy in state.strategies:
        key = (strategy.strategy_id, strategy.version)
        related = tuple(lots_by_strategy.get(key, ()))
        orders = tuple(orders_by_strategy.get(key, ()))
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
        track = tracks.get(key)
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
                ','.join(str(engine.calendar.age(p.entry_trade_date, state.trading_day)) for p in related if p.quantity),
                'COMPLETE' if track and track.history_complete else 'LEGACY_UNKNOWN',
                track.last_at.isoformat() if track else '',
                attributed_pnl=track.equity if track and track.history_complete else None,
            )
        )
    return performance


def _account_risk_views(engine: 'TradingEngine', state) -> list:
    from quantlab.trading.domain.risk import AccountRiskLimits
    from .account_risk import account_net_mark, account_position_count, m2_account_refs

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
    return account_risks


def _automatic_view(engine: 'TradingEngine', state) -> AutomaticView:
    return AutomaticView(
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
    )


@decimal_operation
def snapshot(engine: 'TradingEngine') -> UiState:
    from quantlab.trading.domain.strategy import is_tmf

    from .auto_strategy_service import auto_strategy_views

    state = engine.state
    verified = _financial_facts_current(engine)
    tracks = {(track.strategy_id, track.version): track for track in state.performance_tracks}
    market_watch = engine.live_market.views() if engine.live_market is not None else ()
    health = {view.instrument_id: view.health.freshness for view in market_watch}
    resolved, blocked = _resolved_instruments(engine, state)
    order_days = _order_trading_days(engine)
    orders_by_strategy = _by_strategy(state.orders, plan=True)
    strategies = tuple(
        _strategy_view(engine, state, s, verified, tracks, order_days, orders_by_strategy.get((s.strategy_id, s.version), ()), resolved, blocked)
        for s in state.strategies
        if s.state != 'DELETED'
    )
    positions, gross_marks = _position_views(engine, state, verified, health)
    markets = _market_views(engine, state)
    performance = _performance_views(engine, state, tracks, gross_marks, orders_by_strategy, _by_strategy(state.positions, plan=False))
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
    unpriced = {(p.strategy_id, p.strategy_version) for p in positions if p.unrealized_pnl is None}
    strategies = tuple(replace(s, today_pnl=None) if (s.strategy_id, s.version) in unpriced else s for s in strategies)
    unrealized_total = None if not verified or any(p.unrealized_pnl is None for p in positions) else sum((p.unrealized_pnl for p in positions), ZERO)
    fills = [o for o in state.orders if o.filled and (o.fill_count_day is None or o.fill_count_day == state.trading_day)]
    today_fills = None if any(o.daily_fill_count is None for o in fills) else sum(o.daily_fill_count for o in fills)
    account_risks = _account_risk_views(engine, state)
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
        automatic=_automatic_view(engine, state),
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
