"""One manual SIM engine on the authenticated owner; no strategy scheduling.

Only the query worker discovers resources and collects native observations.
Snapshots and command scope validation never query the SDK or broker finances.
"""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock
from time import monotonic
import sqlite3

from quantlab.trading.adapters.shioaji.gateway import PENDING_PREFIX, ShioajiAdapter
from quantlab.trading.adapters.shioaji.sdk import SDK_VERSION
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import UiAction, UiReceipt
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.manual_contracts import ManualScope, ManualTradingView
from quantlab.trading.application.manual_routing import refusal_command
from quantlab.trading.domain.models import Environment, Market, OrderStatus
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder
from .manual_resources import ManualResourceStore

MANUAL_ACTIONS = frozenset(
    (
        UiAction.ENABLE_MANUAL_BOOK,
        UiAction.PREVIEW_MANUAL,
        UiAction.SUBMIT_MANUAL,
        UiAction.TEST_SIM_ORDER,
        UiAction.CANCEL_MANUAL,
        UiAction.AMEND_MANUAL,
        UiAction.ADOPT_MANUAL_ORDER,
        UiAction.DECLARE_MANUAL_NOT_SENT,
    )
)
ATTEMPT_SOURCE = 'APP_CONFIRMED_SIM_MANUAL_ATTEMPT_KEY_PERMISSION_UNVERIFIED'


class ManualExecutionGateway:
    """Serialize adapter cache mutation; financial observations stay unavailable."""

    def __init__(self, adapter, lock):
        self.adapter, self.lock = adapter, lock

    def inspect(self, account_ref):
        return self.adapter.inspect(account_ref)

    def submit(self, plan, local_order_id):
        with self.lock:
            return self.adapter.submit(plan, local_order_id)

    def cancel(self, local_order_id):
        with self.lock:
            return self.adapter.cancel(local_order_id)

    def amend(self, local_order_id, price, quantity=None):
        with self.lock:
            return self.adapter.amend(local_order_id, price, quantity)

    def adopt_order(self, local_order_id, broker_order_ref):
        with self.lock:
            self.adapter.adopt_order(local_order_id, broker_order_ref)

    def release_unsent(self, local_order_id):
        with self.lock:
            self.adapter.release_unsent(local_order_id)

    def snapshot(self, account_ref):
        raise DomainError('manual_account_observation_required', 'simulation financial facts remain unavailable')

    def refresh(self, account_ref):
        raise DomainError('manual_account_observation_required', 'use account-scoped manual observations')

    def events(self, account_ref, after_sequence=0):
        raise DomainError('manual_account_observation_required', 'use the complete manual observation batch')

    def disconnect(self):
        with self.lock:
            self.adapter.disconnect()


class ManualRuntime:
    def __init__(self, bundle):
        self.bundle, self.owner = bundle, bundle.sinopac_connection
        self.service = self.adapter = self.stamp = None
        self.error = 'not_connected'
        self.last_scopes = {}
        self.refresh_lock = Lock()
        self.port_lock = Lock()
        self.resource_store = ManualResourceStore(bundle)

    def _accepted(self):
        view = self.owner.snapshot()
        if self.bundle.closing or self.bundle.resources_closed or view.phase != 'CONNECTED' or view.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('production_orders_disabled' if view.environment is Environment.LIVE else 'not_connected')
        if not self.owner.query_ready or self.owner.shared is None or self.owner.shared.callback_errors:
            raise DomainError('manual_account_observation_required')
        selected = tuple(sorted(self.owner.selected))
        if not selected:
            raise DomainError('accounts_not_selected')
        return view, selected, self.owner.shared

    def validate_scope(self, scope):
        view, selected, shared = self._accepted()
        if self.error:
            raise DomainError(self.error, 'manual observation is not currently healthy')
        if (
            self.stamp != (view.generation, view.revision, selected, shared)
            or (scope.connection_generation, scope.connection_revision, scope.environment) != (view.generation, view.revision, Environment.BROKER_SIMULATION)
            or scope.context_id != 'sinopac-simulation'
        ):
            raise DomainError('state_conflict', 'manual owner generation or selection changed')
        if scope.account_ref not in selected:
            raise DomainError('capability_missing', 'manual account is not selected')
        actual = next((row for row in self.owner.accounts if row.alias == scope.account_ref), None)
        if actual is None or actual.signed is not True:
            raise DomainError('account_not_signed' if actual is not None and actual.signed is False else 'account_sign_unknown')

    def snapshot(self, account_ref):
        view = self.owner.snapshot()
        if account_ref not in self.owner.selected or not view.generation:
            return ManualTradingView(reasons=('not_connected' if view.phase != 'CONNECTED' else 'accounts_not_selected',))
        prior = self.last_scopes.get(account_ref)
        scope = ManualScope('sinopac-simulation', 0, self.bundle.launch.environment, account_ref, view.generation, view.revision)
        if prior is not None and (prior.connection_generation, prior.connection_revision) == (view.generation, view.revision):
            scope = prior
        if self.service is None or account_ref not in self.bundle.engine.gateways:
            return ManualTradingView(scope, reasons=(self.error,))
        result = self.service.snapshot(scope)
        if self.error:
            return replace(
                result,
                halted=True,
                can_prepare=False,
                can_preview=False,
                can_submit=False,
                can_test=False,
                can_mutate=False,
                reasons=tuple(sorted(set((*result.reasons, self.error)))),
            )
        return result

    def handles(self, command):
        return command.action in MANUAL_ACTIONS or self.service is not None and command.action in (UiAction.RESUME, UiAction.FLATTEN, UiAction.RECONCILE)

    def connection_view(self, view, manual):
        reason = next((code for code in manual.reasons if code != 'manual_book_not_enabled'), 'manual_book_not_enabled')
        ready = (
            manual.scope is not None
            and manual.scope.environment is Environment.BROKER_SIMULATION
            and manual.scope.connection_generation == view.generation
            and manual.scope.connection_revision == view.revision
            and manual.test_status == 'PASSED'
            and manual.can_submit
        )
        if view.environment is Environment.LIVE:
            ready, reason = False, 'production_orders_disabled'
        rows = tuple(
            replace(row, state='READY' if ready else 'BLOCKED', reason='ready' if ready else reason) if row.code == 'simulation_orders' else row
            for row in view.readiness
        )
        return replace(view, readiness=rows)

    def execute(self, command):
        if command.environment is Environment.LIVE or self.bundle.launch.environment is Environment.LIVE:
            return UiReceipt(False, 'production_orders_disabled', '')
        if type(command.manual_no_admission) is not bool or command.manual_no_admission and refusal_command(command) is None:
            return UiReceipt(False, 'validation_failed', '')
        if self.service is None:
            return UiReceipt(False, self.error or 'manual_account_observation_required', '')
        if command.action is UiAction.RECONCILE:
            # The worker performs native waits. This control never falls through
            # to financial reconciliation, which cannot attest simulation funds.
            if command.expected_version != self.bundle.engine.state.version + self.bundle.version_offset:
                return UiReceipt(False, 'state_conflict', '')
            return UiReceipt(not self.error, self.error or 'ok', '')
        receipt = self.service.execute(replace(command, expected_version=command.expected_version - self.bundle.version_offset))
        confirmed = refusal_command(command)
        form = command.manual_order or command.manual_mutation if confirmed is not None else None
        result = self.service.snapshot(form.scope).last_result if form is not None and form.scope.account_ref in self.bundle.engine.gateways else None
        known = result is not None and result.outcome_known and result.scope == form.scope and result.request_id == form.request_id
        if receipt.accepted or known:
            self.last_scopes[command.account_ref] = ManualScope(
                command.context_id, command.context_epoch, command.environment, command.account_ref, command.connection_generation, command.connection_revision
            )
        return receipt

    def _materialize(self, stamp, resources):
        from quantlab.trading.application.manual_trading import ManualTradingService
        from quantlab.trading.ports.manual import ManualPriceLimit
        from .live_market import CalendarResolver

        view, selected, shared = self._accepted()
        if stamp != (view.generation, view.revision, selected, shared):
            raise DomainError('state_conflict', 'connection changed while collecting resources')
        with self.bundle.lock:
            if self.bundle.closing or self.bundle.resources_closed:
                raise DomainError('state_conflict', 'manual runtime is closing')
            retained = self.resource_store.retain(resources)
        first = resources[0]
        if any(row.calendar != first.calendar or row.fees != first.fees for row in resources):
            raise DomainError('capability_missing', 'one explicit calendar and fee basis required')
        accounts = {row.alias: row.native for resource in resources for row in resource.accounts}
        if set(accounts) != set(selected):
            raise DomainError('state_conflict', 'resource accounts differ from accepted selection')
        capabilities = tuple(
            replace(row, can_trade=True, short_sell=Market.INDEX_FUTURE in row.markets, day_trade=False, odd_lot=False, source=ATTEMPT_SOURCE)
            for resource in resources
            for row in resource.capabilities
        )
        markets = dict(retained.markets)
        stock = next((ref for ref in selected if markets[ref] is Market.STOCK), '')
        futures = next((ref for ref in selected if markets[ref] is Market.INDEX_FUTURE), '')
        configuration = ExecutionConfiguration(Environment.BROKER_SIMULATION, stock, futures, False, True)
        if self.adapter is not None:
            with self.port_lock:
                self.adapter.disconnect()  # Detach this consumer, never owner logout.
        adapter = ShioajiAdapter(
            shared.consumer('execution'),
            self.owner.clock,
            Environment.BROKER_SIMULATION,
            accounts,
            retained.bindings,
            capabilities,
            {ref: Decimal('60000') if markets[ref] is Market.STOCK else Decimal('40000') for ref in accounts},
            sdk_version=SDK_VERSION,
            read_only=False,
            execution_enabled=True,
            share_unit='Share',
        )
        try:
            adapter.attach_authenticated()
        except BaseException:
            adapter.disconnect()
            raise
        self.adapter, self.service = adapter, None
        gateway = ManualExecutionGateway(adapter, self.port_lock)
        catalog = Catalog(tuple(row.spec for row in retained.bindings))
        engine = self.bundle.engine
        with self.bundle.lock:
            if self.bundle.closing or self.bundle.resources_closed:
                raise DomainError('state_conflict', 'manual runtime is closing')
            if engine is None:
                journal = Ledger(self.bundle.launch.root / 'manual-trading-v2.sqlite', 'manual-sim-trading-v2', datetime.now(timezone.utc))
                try:
                    engine = TradingEngine(
                        journal, self.owner.clock, first.calendar, catalog, {ref: gateway for ref in accounts}, configuration=configuration, fees=first.fees
                    )
                except BaseException:
                    journal.close()
                    adapter.disconnect()
                    raise
                self.bundle.journals = (*self.bundle.journals, journal)
        with self.bundle.lock, engine.lock:
            if self.bundle.closing or self.bundle.resources_closed:
                raise DomainError('state_conflict', 'manual runtime is closing')
            old_version = self.bundle.facade.snapshot().version + self.bundle.version_offset
            obligations = {row.account_ref for row in engine.state.manual_books}
            obligations.update(row.plan.account_ref for row in engine.state.orders)
            obligations.update(row.account_ref for row in engine.state.positions)
            if not obligations <= set(markets):
                raise DomainError('startup_workspace_incompatible', 'manual obligations lost account market facts')
            engine.gateways = {ref: gateway for ref in set(accounts) | obligations}
            engine.manual_markets = {ref: markets[ref] for ref in engine.gateways}
            engine.configuration, engine.catalog, engine.calendar, engine.fees = configuration, catalog, first.calendar, first.fees
            adapter.session_resolver = CalendarResolver(engine)
            adapter.account_sequences.update({row.account_ref: row.sequence for row in engine.state.cursors if row.account_ref in accounts})
            for order in engine.state.orders:
                # An unknown submission keeps its placeholder so a later observation can still find it.
                reference = order.broker_ref or (PENDING_PREFIX + order.order_id if order.status is OrderStatus.UNKNOWN else '')
                if reference:
                    adapter.orders[order.order_id] = BrokerOrder(
                        order.order_id, order.plan, order.filled, order.average_price, order.status, reference, self.owner.clock.now()
                    )
            limits = tuple(
                ManualPriceLimit(row.instrument_id, row.lower, row.upper, row.observed_at, row.source) for resource in resources for row in resource.limits
            )
            self.stamp = stamp
            service = ManualTradingService(
                engine, validate_scope=self.validate_scope, limits=limits, cost_source=first.fee_source, margin_source=first.margin_source
            )
            self.bundle.version_offset = max(self.bundle.version_offset, old_version + 1 - engine.state.version)
            self.bundle.engine, self.bundle.facade = engine, LocalFacade(engine)
            self.service, self.adapter = service, adapter

    def _resources(self, selected):
        try:
            return tuple(self.owner.resources(ref) for ref in selected)
        except DomainError:
            raise
        except Exception:
            # The injected resource port crosses SDK/public-source IO. Raw
            # provider diagnostics must not become a UI or wire payload.
            raise DomainError('instrument_unresolved', 'broker resource observation unavailable') from None

    def _renew_facts(self, stamp, resources):
        from quantlab.trading.ports.manual import ManualPriceLimit

        engine = self.bundle.engine
        bindings = {row.spec.instrument_id: row for resource in resources for row in resource.bindings}
        changed = any(resource.calendar != engine.calendar or resource.fees != engine.fees for resource in resources)
        for key, row in bindings.items():
            old = self.adapter.bindings.get(key)
            if old is None or row.sdk_code != old.sdk_code or replace(row.spec, effective_at=old.spec.effective_at) != old.spec:
                changed = True
                break
            grid = replace(row.stock_grid, as_of=old.stock_grid.as_of) if row.stock_grid is not None and old.stock_grid is not None else row.stock_grid
            if grid != old.stock_grid:
                changed = True
                break
        if changed:
            self._materialize(stamp, resources)
            return
        current, selected, shared = self._accepted()
        if stamp != (current.generation, current.revision, selected, shared):
            raise DomainError('state_conflict', 'resource renewal belongs to an obsolete session')
        with engine.lock:
            for resource in resources:
                for row in resource.capabilities:
                    self.adapter.capabilities[row.account_ref] = replace(
                        row, can_trade=True, short_sell=Market.INDEX_FUTURE in row.markets, day_trade=False, odd_lot=False, source=ATTEMPT_SOURCE
                    )
                for row in resource.bindings:
                    self.adapter.bindings[row.spec.instrument_id] = replace(row, spec=engine.catalog.resolve(row.spec.instrument_id))
                for row in resource.limits:
                    self.service.limits[row.instrument_id] = ManualPriceLimit(row.instrument_id, row.lower, row.upper, row.observed_at, row.source)

    def _failed(self, code):
        self.error = code
        with self.bundle.lock:
            if self.service is not None and not self.bundle.closing:
                try:
                    self.service.adopt(())
                except DomainError:
                    pass  # The service durably latches the unknown observation.

    def refresh(self):
        if not self.refresh_lock.acquire(blocking=False):
            return
        try:
            deadline = monotonic() + 8.0
            view, selected, shared = self._accepted()
            stamp = view.generation, view.revision, selected, shared
            if stamp != self.stamp:
                self._materialize(stamp, self._resources(selected))
            elif any(row.expires_at <= self.owner.clock.now() for row in self.adapter.capabilities.values()):
                self._renew_facts(stamp, self._resources(selected))
            engine, adapter, service = self.bundle.engine, self.adapter, self.service
            with engine.lock:
                cursors = {row.account_ref: row.sequence for row in engine.state.cursors}
                instruments = tuple(row.instrument_id for row in engine.catalog.instruments)
                observed_version = engine.state.version
            # Every wait below runs outside the writer and composition locks.
            observations, quotes = [], []
            with self.port_lock:
                for ref in engine.gateways:
                    if monotonic() >= deadline:
                        raise DomainError('manual_account_observation_required', 'bounded manual observation deadline')
                    observations.append(adapter.observe_manual(ref, cursors.get(ref, 0)))
                for instrument_id in instruments:
                    if monotonic() >= deadline:
                        raise DomainError('manual_account_observation_required', 'bounded manual observation deadline')
                    try:
                        quote = adapter.latest(instrument_id)
                        if quote is not None:
                            quotes.append(quote)
                    except DomainError:
                        continue
            current, current_selected, current_shared = self._accepted()
            if stamp != (current.generation, current.revision, current_selected, current_shared):
                raise DomainError('state_conflict', 'observation belongs to an obsolete owner')
            if monotonic() >= deadline:
                raise DomainError('manual_account_observation_required', 'bounded manual observation deadline')
            with self.bundle.lock, engine.lock:
                if self.bundle.closing:
                    return
                if engine.state.version != observed_version:
                    return  # A command committed after collection began; refresh again.
                for quote in quotes:
                    if engine.quotes.get(quote.instrument_id) != quote:
                        engine.quote(quote)
                service.adopt(tuple(observations))
            self.error = ''
        except DomainError as error:
            self._failed(error.code)
        except (OSError, sqlite3.Error):
            self._failed('journal_failed')
        finally:
            self.refresh_lock.release()
