"""Fenced execution orchestration independent of Qt, SQLite and vendor SDK."""

from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Callable

from .codec import dumps, loads
from .context import AccountGateway, Catalog, ExecutionConfiguration, LocalSimulationControl, ResearchRunner
from .concurrency import WriterLock
from .contracts import StrategyForm
from .broker_settings import ReferenceInspector
from .provenance import ProducerProfile
from .execution import ExecutionService
from .performance import seed_track
from .registry import initialize
from .state import ACTIVE, AppState, StrategyRecord
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, OrderPlan, OrderStatus, Quote, Reservation, Side
from quantlab.trading.domain.policies import ExitCoordinator, check_entry_eligibility, holding_window
from quantlab.trading.domain.risk import RiskPolicy, RiskService
from quantlab.trading.domain.validation import DomainError, decimal_value
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.ports.interfaces import Clock
from quantlab.trading.ports.contracts import RemoteSnapshot
from quantlab.trading.ports.storage import Journal

ZERO = Decimal('0')


class TradingEngine:
    def __init__(
        self,
        journal: Journal,
        clock: Clock,
        calendar: TradingCalendar,
        catalog: Catalog,
        gateways: dict[str, AccountGateway],
        *,
        simulation: LocalSimulationControl | None = None,
        ownership_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        configuration: ExecutionConfiguration | None = None,
        reference_inspector: ReferenceInspector | None = None,
        source_profile: ProducerProfile | None = None,
        research_runner: ResearchRunner | None = None,
        fees: FeeSchedule | None = None,
        historical_bars: dict[str, tuple[CompletedBar, ...]] | None = None,
    ):
        initialize()
        self.journal, self.clock, self.calendar, self.catalog = journal, clock, calendar, catalog
        self.gateways, self.simulation, self.ownership_clock = gateways, simulation, ownership_clock
        self.configuration = configuration or ExecutionConfiguration()
        if historical_bars is not None and (type(historical_bars) is not dict or len(historical_bars) > len(catalog.instruments)):
            raise DomainError('validation_failed', 'bounded typed market history mapping required')
        self.history: dict[str, tuple[CompletedBar, ...]] = {}
        for instrument_id, series in (historical_bars or {}).items():
            catalog.resolve(instrument_id)
            if type(series) is not tuple or len(series) > 10000 or any(not isinstance(bar, CompletedBar) for bar in series):
                raise DomainError('validation_failed', 'bounded immutable completed-bar series required')
            if tuple(bar.opened_at for bar in series) != tuple(sorted(set(bar.opened_at for bar in series))):
                raise DomainError('validation_failed', 'market history must have unique chronological bar identities')
            self.history[instrument_id] = series
        self.reference_inspector = reference_inspector
        self.profile = source_profile
        self.research_runner = research_runner
        self.lock = WriterLock()
        self.quotes: dict[str, Quote] = {}
        self.quote_count = 0
        # Read-only polling may return the same immutable cached report many
        # times. A successful unchanged observation must not rewrite the book.
        self.confirmed_observations: tuple[tuple[tuple[str, RemoteSnapshot], ...], int, int] | None = None
        self.recent_quote_sequences: dict[str, int] = {}
        self.latencies: deque[float] = deque(maxlen=10000)
        self.storage_failed = False
        self.fees = fees if fees is not None else FeeSchedule()
        self.explicit_cost_schedule = fees is not None
        self.state = AppState(
            trading_day=clock.now().date(),
            environment=self.configuration.environment,
            account_ref=self.configuration.stock_account_ref or self.configuration.futures_account_ref,
        )
        for event in self.journal.replay():
            restored = loads(event.payload)
            if not isinstance(restored, AppState) or restored.version != event.sequence:
                raise DomainError('journal_failed', 'state event sequence mismatch')
            if restored.environment is not self.configuration.environment:
                raise DomainError('startup_workspace_incompatible', 'execution environments cannot share a ledger')
            self.state = restored
        overrides = {s.instrument_id: s for s in self.state.instrument_overrides}
        if overrides:
            self.catalog = Catalog(tuple(overrides.get(s.instrument_id, s) for s in self.catalog.instruments))
        # No outbox item is ever automatically resubmitted on restart/restore.
        pending = tuple(replace(o, status=OrderStatus.UNKNOWN) if o.status is OrderStatus.SUBMITTING else o for o in self.state.orders)
        from .research import ResearchResult

        strategies = []
        for record in self.state.strategies:
            result = loads(record.research_blob) if record.research_blob else None
            stale = isinstance(result, ResearchResult) and self.profile is not None and result.source_digest != self.profile.source_digest
            if stale and record.state in ('ACTIVE', 'RESEARCHED'):
                record = replace(record, state='RULE_VALID', evidence='SOURCE_PROFILE_CHANGED')
            strategies.append(record)
        self._persist(
            'startup_reconciliation_required',
            replace(self.state, orders=pending, strategies=tuple(strategies), stopped=True, reconciled=False, engine_closed=False),
        )
        from .sessions import synchronize_session

        synchronize_session(self)

    def _persist(self, kind: str, proposed: AppState) -> None:
        value = replace(proposed, version=self.state.version + 1, events=(*self.state.events[-199:], kind))
        try:
            event = self.journal.append(kind, dumps(value), self.ownership_clock(), expected_sequence=self.state.version)
        except Exception as exc:
            self.storage_failed = True
            self.state = replace(self.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*self.state.issues, 'journal_failed')))))
            if isinstance(exc, DomainError):
                raise
            raise DomainError('journal_failed', 'durable append failed') from None
        if event.sequence != value.version:
            raise DomainError('journal_failed', 'journal sequence mismatch')
        self.state = value

    def fence(self) -> None:
        if self.storage_failed:
            raise DomainError('journal_failed')
        try:
            self.journal.heartbeat(self.ownership_clock())
        except Exception as exc:
            self.storage_failed = True
            code = exc.code if isinstance(exc, DomainError) else 'journal_failed'
            self.state = replace(self.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*self.state.issues, code)))))
            if isinstance(exc, DomainError):
                raise
            raise DomainError('journal_failed', 'writer health unavailable') from None

    def account(self, account_ref: str):
        snapshot = self.gateways[account_ref].snapshot(account_ref)
        settings = self.state.settings
        allocated = settings.stock_allocation if account_ref == self.configuration.stock_account_ref else settings.futures_allocation
        return replace(snapshot, version=self.state.version, allocated_cash=min(snapshot.allocated_cash, allocated))

    def assert_execution_allowed(self) -> None:
        config = self.configuration
        if config.environment is not Environment.LOCAL and not self.explicit_cost_schedule:
            raise DomainError('capability_missing', 'explicit verified cost schedule required outside local simulation')
        if (
            config.read_only
            or config.environment is Environment.BROKER_SIMULATION
            and not config.broker_simulation_enabled
            or config.environment is Environment.LIVE
            and not config.live_execution_enabled
        ):
            raise DomainError('capability_missing', 'execution remains disabled in this environment')

    def reservations(self) -> tuple[Reservation, ...]:
        from .reservations import current_reservations

        return current_reservations(self)

    def risk(self) -> RiskService:
        settings = self.state.settings
        return RiskService(RiskPolicy(trade_fraction=settings.risk_fraction, daily_fraction=settings.daily_loss_fraction), self.fees)

    def quote(self, quote: Quote) -> None:
        with self.lock:
            from .sessions import synchronize_session

            synchronize_session(self)
            self.catalog.resolve(quote.instrument_id)
            prior = self.quotes.get(quote.instrument_id)
            if prior and (quote.source_at < prior.source_at or quote.sequence is not None and prior.sequence is not None and quote.sequence <= prior.sequence):
                raise DomainError('stale_quote', 'nonmonotone quote')
            self.quotes[quote.instrument_id] = quote
            self.quote_count += 1
            if not self.state.engine_closed and not self.storage_failed:
                for lot in tuple(self.state.positions):
                    if not lot.quantity or lot.instrument_id != quote.instrument_id:
                        continue
                    entry = next(o for o in self.state.orders if o.order_id == lot.lot_id)
                    stop_price = dict(self.state.protection_stops).get(lot.lot_id, entry.plan.stop_price)
                    triggered = quote.last <= stop_price if lot.direction is Side.BUY else quote.last >= stop_price
                    if triggered:
                        try:
                            self.exit_lot(lot.lot_id, protective=True)
                        except DomainError as exc:
                            if self.storage_failed:
                                raise
                            if exc.code not in self.state.issues:
                                self._persist(
                                    'quote_protection_requires_attention',
                                    replace(self.state, stopped=True, issues=tuple(sorted(set((*self.state.issues, exc.code))))),
                                )

    @decimal_operation
    def create_strategy(self, form: StrategyForm) -> str:
        if (
            not isinstance(form, StrategyForm)
            or type(form.name) is not str
            or type(form.instrument_id) is not str
            or type(form.parent_strategy_id) is not str
            or type(form.rule_kind) is not str
        ):
            raise DomainError('validation_failed', 'typed strategy form required')
        if (
            not isinstance(form.market, Market)
            or not isinstance(form.holding_kind, HoldingKind)
            or not isinstance(form.direction, Side)
            or type(form.new_entries_only) is not bool
        ):
            raise DomainError('validation_failed', 'strategy enum/bool types')
        decimal_value(form.allocation, 'strategy allocation', positive=True)
        decimal_value(form.risk_fraction, 'strategy risk', positive=True)
        spec = self.catalog.resolve(form.instrument_id)
        if form.market is not spec.market or form.environment is not self.configuration.environment or form.account_ref not in self.gateways:
            raise DomainError('capability_missing', 'local context required')
        if (
            not form.name.strip()
            or len(form.name) > 100
            or form.rule_kind not in ('MA_CROSS', 'BREAKOUT', 'BUY_AND_HOLD', 'STRUCTURED_JSON')
            or not form.new_entries_only
        ):
            raise DomainError('validation_failed', 'strategy form')
        if form.risk_fraction not in (Decimal('0.02'), Decimal('0.03')) or not ZERO < form.allocation <= Decimal('100000'):
            raise DomainError('risk_rejected', 'strategy allocation/risk')
        policy = HoldingPolicy(form.holding_kind, form.min_days, form.max_days, expiry_action=form.expiry_action)
        if spec.market is Market.STOCK and form.expiry_action != 'EXIT':
            raise DomainError('validation_failed', 'cash stocks do not roll expiry contracts')
        if form.expiry_action == 'ROLL':
            successor = next(
                (s for s in self.state.strategies if s.strategy_id == form.parent_strategy_id and s.form.roll_contract_id == spec.instrument_id), None
            )
            if form.roll_contract_id:
                target = self.catalog.resolve(form.roll_contract_id)
                if (
                    target.market is not spec.market
                    or target.underlying != spec.underlying
                    or target.expiry is None
                    or spec.expiry is None
                    or target.expiry <= spec.expiry
                ):
                    raise DomainError('instrument_unresolved', 'explicit later same-underlying contract required')
            elif successor is None:
                raise DomainError('instrument_unresolved', 'explicit next contract required for initial roll policy')
        holding_window(policy, self.state.trading_day, self.calendar)
        parent = next((s for s in self.state.strategies if s.strategy_id == form.parent_strategy_id), None)
        if form.parent_strategy_id and parent is None:
            raise DomainError('validation_failed', 'unknown strategy parent')
        strategy_id = parent.strategy_id if parent else 'strategy-' + str(len(self.state.strategies) + 1)
        version = max((s.version for s in self.state.strategies if s.strategy_id == strategy_id), default=0) + 1
        definition, draft_hash = None, ''
        if form.rule_kind == 'STRUCTURED_JSON':
            from quantlab.trading.domain.strategy import parse_strategy

            definition = parse_strategy(form.draft_json)
            expected_direction = 'LONG_ONLY' if form.direction is Side.BUY else 'SHORT_ONLY'
            if (
                definition.market is not form.market
                or definition.policy != policy
                or definition.direction != expected_direction
                or definition.bar_interval != '1d'
            ):
                raise DomainError('validation_failed', 'draft does not match explicit market, policy, direction or supported interval')
            if definition.cost_version != self.fees.version or definition.risk_ref != self.risk().policy.version:
                raise DomainError('validation_failed', 'draft cost/risk references must match authoritative versions')
            draft_hash = sha256(form.draft_json.encode()).hexdigest()
            definition = replace(definition, strategy_id=strategy_id, version=version)
            form = replace(form, draft_json='')
        record = StrategyRecord(strategy_id, version, form, policy, definition=definition, draft_hash=draft_hash)
        initial_track = seed_track(strategy_id, version, self.clock.now(), self.state.trading_day)
        self._persist(
            'strategy_version_created',
            replace(self.state, strategies=(*self.state.strategies, record), performance_tracks=(*self.state.performance_tracks, initial_track)),
        )
        return f'{strategy_id}:{version}'

    def strategy(self, reference: str) -> StrategyRecord:
        result = next((s for s in reversed(self.state.strategies) if reference in (s.strategy_id, f'{s.strategy_id}:{s.version}')), None)
        if result is None:
            raise DomainError('validation_failed', 'unknown strategy')
        return result

    def update_strategy(self, record: StrategyRecord, kind: str) -> None:
        records = tuple(record if (s.strategy_id, s.version) == (record.strategy_id, record.version) else s for s in self.state.strategies)
        self._persist(kind, replace(self.state, strategies=records))

    def validate_strategy(self, reference: str) -> None:
        strategy = self.strategy(reference)
        spec = self.catalog.resolve(strategy.form.instrument_id)
        capability = self.gateways[strategy.form.account_ref].inspect(strategy.form.account_ref)
        if spec.market is Market.STOCK and strategy.policy.kind is HoldingKind.INTRADAY and not capability.day_trade:
            raise DomainError('intraday_eligibility_missing')
        check_entry_eligibility(spec, strategy.policy, capability, strategy.form.direction, self.clock.now())
        self.update_strategy(replace(strategy, state='RULE_VALID'), 'strategy_rules_validated')

    def deploy(self, reference: str) -> None:
        strategy = self.strategy(reference)
        if strategy.state != 'RESEARCHED' or not strategy.evidence_hash:
            raise DomainError('risk_rejected', 'research evidence required for local deployment')
        from .research import ResearchResult, research_fingerprint

        evidence = loads(strategy.research_blob) if strategy.research_blob else None
        expected = (
            research_fingerprint(strategy, self.catalog.resolve(strategy.form.instrument_id), self.calendar, self.fees, evidence.dataset_id, self.profile)
            if isinstance(evidence, ResearchResult)
            else ''
        )
        if (
            not isinstance(evidence, ResearchResult)
            or self.profile is None
            or evidence.fingerprint != expected
            or evidence.source_digest != self.profile.source_digest
        ):
            raise DomainError('strategy_evidence_stale', 'current rules, costs, instrument, calendar or producer do not match research')
        self.validate_strategy(reference)
        for existing in self.state.strategies:
            if (
                existing.state == 'ACTIVE'
                and existing.form.account_ref == strategy.form.account_ref
                and existing.form.instrument_id == strategy.form.instrument_id
            ):
                if existing.strategy_id != strategy.strategy_id:
                    raise DomainError('state_conflict', 'one active strategy per account and instrument')
                self.update_strategy(replace(existing, state='RETIRED'), 'prior_deployment_retired')
        strategy = replace(strategy, state='ACTIVE')
        self.update_strategy(strategy, 'local_deployment_activated')

    @decimal_operation
    def submit(self, plan: OrderPlan, policy: HoldingPolicy, key: str) -> str:
        with self.lock:
            spec = self.catalog.resolve(plan.instrument_id)
            quote = self.quotes.get(plan.instrument_id)
            if quote is None:
                raise DomainError('stale_quote', 'no verified quote')
            gateway = self.gateways.get(plan.account_ref)
            if gateway is None or plan.environment is not self.configuration.environment:
                raise DomainError('capability_missing', 'execution environment not enabled')
            self.assert_execution_allowed()
            session = self.calendar.session_at(self.clock.now(), allow_night=policy.night_enabled)
            if quote.trade_date != session.trade_date or quote.session != session.kind:
                raise DomainError('session_closed', 'quote/calendar session mismatch')
            # Exact retries precede state-version checks; remote UNKNOWN is never resubmitted.
            digest = sha256(dumps(plan).encode()).hexdigest()
            prior = next((o for o in self.state.orders if o.key == key), None)
            if prior:
                if prior.request_hash != digest:
                    raise DomainError('state_conflict', 'idempotency content conflict')
                return prior.order_id
            if plan.state_version != self.state.version:
                raise DomainError('state_conflict', 'order was prepared against another state')
            from .sessions import synchronize_session, assert_daily_baseline

            synchronize_session(self)
            if not plan.reduce_only:
                assert_daily_baseline(self)
            from .scope import refresh_scope

            refresh_scope(self, plan)
            plan = replace(plan, state_version=self.state.version)
            if not plan.reduce_only:
                from .workflows import mark_risk, total_mark

                actual_pnl = total_mark(self) - self.state.daily_baseline_pnl
                if actual_pnl != self.state.daily_pnl:
                    mark_risk(self)
                if self.state.trading_day in self.state.daily_locks:
                    raise DomainError('risk_rejected', 'daily loss stop remains latched')
                # Internal valuation may append a derived mark, but the caller's
                # expected state was checked before it. Rebind only that version;
                # original intent hash remains the retry identity.
                plan = replace(plan, state_version=self.state.version)
            strategy = next((s for s in self.state.strategies if (s.strategy_id, s.version) == (plan.strategy_id, plan.strategy_version)), None)
            if not plan.reduce_only and (
                strategy is None
                or strategy.state != 'ACTIVE'
                or strategy.form.instrument_id != plan.instrument_id
                or strategy.form.direction is not plan.side
                or strategy.form.account_ref != plan.account_ref
            ):
                raise DomainError('risk_rejected', 'active matching deployment required')
            if not plan.reduce_only and any(
                lot.quantity and lot.account_ref == plan.account_ref and lot.instrument_id == plan.instrument_id and lot.direction is not plan.side
                for lot in self.state.positions
            ):
                raise DomainError('risk_rejected', 'opposing entry cannot silently net an existing policy-owned lot')
            if not plan.reduce_only and (
                any(job.status != 'APPLIED' for job in self.state.corporate_actions) or any(job.status == 'FROZEN' for job in self.state.rolls)
            ):
                raise DomainError('reconciliation_required', 'durable lifecycle work remains unresolved')
            account = self.account(plan.account_ref)
            risk = self.risk()
            strategy_cash_limit = None
            if strategy is not None:
                risk = RiskService(replace(risk.policy, trade_fraction=min(risk.policy.trade_fraction, strategy.form.risk_fraction)), self.fees)
                pending_cash = sum((o.reservation.cash for o in self.state.orders if o.plan.strategy_id == strategy.strategy_id), ZERO)
                owned_cash = ZERO
                for lot in self.state.positions:
                    if lot.strategy_id == strategy.strategy_id and lot.quantity:
                        instrument = self.catalog.resolve(lot.instrument_id)
                        owned_cash += lot.entry_price * lot.quantity if instrument.market.value == 'STOCK' else (instrument.margin or ZERO) * lot.quantity
                strategy_cash_limit = max(ZERO, strategy.form.allocation - owned_cash - pending_cash)
            decision = risk.preview(
                plan,
                spec,
                quote,
                account,
                gateway.inspect(plan.account_ref),
                now=self.clock.now(),
                reservations=self.reservations(),
                daily_pnl=self.state.daily_pnl,
                daily_locked=self.state.trading_day in self.state.daily_locks,
                allocations=(account,) if plan.reduce_only else tuple(self.account(a) for a in self.gateways),
                policy=policy,
                strategy_cash_limit=strategy_cash_limit,
            )
            if not decision.allowed or decision.quantity != plan.quantity:
                raise DomainError(decision.code, 'commit requires a legal sized plan')
            if plan.reduce_only:
                self._check_exit(plan)
            reservation = Reservation(
                plan.plan_id,
                plan.account_ref,
                plan.instrument_id,
                spec.underlying,
                decision.cash_required,
                decision.risk_required,
                plan.quantity,
                OrderStatus.RESERVED,
            )
            execution = ExecutionService(
                gateway, self._persist, self.fence, self.clock.now, self.simulation.persist_remote if self.simulation else lambda: None
            )
            return execution.commit(self.state, plan, policy, reservation, key, lambda: self.fence(), request_hash=digest)

    def _check_exit(self, plan: OrderPlan) -> None:
        if any(row.account_ref == plan.account_ref and row.instrument_id == plan.instrument_id for row in self.state.reconciliation):
            raise DomainError('reconciliation_required', 'position/order direction or quantity requires explicit reconciliation')
        lot = next((p for p in self.state.positions if p.lot_id == plan.exit_lot_id), None)
        if lot is None or lot.account_ref != plan.account_ref or lot.instrument_id != plan.instrument_id or lot.quantity < plan.quantity:
            raise DomainError('risk_rejected', 'owned exit lot required')
        if plan.side is lot.direction:
            raise DomainError('risk_rejected', 'exit must reduce direction')
        pending = sum(o.plan.quantity - o.filled for o in self.state.orders if o.plan.exit_lot_id == lot.lot_id and o.status in ACTIVE)
        result = ExitCoordinator().plan(
            lot,
            self.catalog.resolve(lot.instrument_id),
            self.gateways[lot.account_ref].inspect(lot.account_ref),
            self.calendar,
            self.state.trading_day,
            now=self.clock.now(),
            pending_exit_quantity=pending,
            protective=True,
        )
        if result.blocked or result.quantity < plan.quantity:
            raise DomainError(result.reason, 'exit is not executable')

    def exit_lot(self, lot_id: str, *, protective: bool = False) -> str | None:
        lot = next((p for p in self.state.positions if p.lot_id == lot_id), None)
        if lot is None or not lot.quantity:
            return None
        pending = sum(o.plan.quantity - o.filled for o in self.state.orders if o.plan.exit_lot_id == lot_id and o.status in ACTIVE)
        result = ExitCoordinator().plan(
            lot,
            self.catalog.resolve(lot.instrument_id),
            self.gateways[lot.account_ref].inspect(lot.account_ref),
            self.calendar,
            self.state.trading_day,
            now=self.clock.now(),
            pending_exit_quantity=pending,
            protective=protective,
        )
        if result.blocked:
            if result.requires_attention and result.reason not in self.state.issues:
                self._persist('exit_blocked', replace(self.state, stopped=True, issues=tuple(sorted(set((*self.state.issues, result.reason))))))
            return None
        quote = self.quotes[lot.instrument_id]
        side = Side.SELL if lot.direction is Side.BUY else Side.BUY
        price = quote.bid if side is Side.SELL else quote.ask
        plan = OrderPlan(
            'exit-' + str(self.state.version),
            lot.account_ref,
            self.configuration.environment,
            lot.instrument_id,
            lot.strategy_id,
            lot.strategy_version,
            side,
            result.quantity,
            self.catalog.resolve(lot.instrument_id).unit,
            price,
            price,
            True,
            self.clock.now(),
            self.clock.now() + timedelta(seconds=30),
            self.state.version,
            lot_id,
        )
        return self.submit(plan, lot.policy, f'exit:{lot_id}:{self.state.version}')
