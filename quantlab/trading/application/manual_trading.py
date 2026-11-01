"""Explicit manual SIM commands through the existing fenced execution writer."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Callable
from uuid import uuid4

from .codec import dumps
from .contracts import UiAction, UiCommand, UiReceipt
from .engine import TradingEngine
from .errors import ERROR_TABLE
from .events import apply_event
from .execution import ExecutionService
from .manual_book import (
    CAPACITY_SOURCE,
    MANUAL_PREFIX,
    ManualBook,
    ManualRequest,
    book_for,
    manual_allocations_valid,
    manual_capacity,
    diagnostic_passed,
    manual_market,
    manual_net_pnl,
    manual_policy,
    manual_risk_context,
    manual_stock_availability,
    request_for,
)
from .manual_contracts import (
    ManualBookForm,
    ManualInstrumentView,
    ManualMutationForm,
    ManualOrderForm,
    ManualPendingView,
    ManualPreviewView,
    ManualPurpose,
    ManualScope,
    ManualTradingView,
)
from .state import ACTIVE
from quantlab.trading.domain.models import Environment, Market, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation, ManualPriceLimit

ZERO = Decimal('0')
TERMINAL = frozenset((OrderStatus.CANCELED, OrderStatus.FILLED, OrderStatus.REJECTED))


class ManualTradingService:
    def __init__(
        self,
        engine: TradingEngine,
        *,
        validate_scope: Callable[[ManualScope], None],
        limits: tuple[ManualPriceLimit, ...],
        cost_source: str,
        margin_source: str,
    ):
        self.engine, self.validate_scope = engine, validate_scope
        self.limits = {row.instrument_id: row for row in limits}
        self.cost_source, self.margin_source = cost_source, margin_source
        self.previews: dict[str, tuple[ManualOrderForm, ManualPreviewView]] = {}
        self.diagnostics: dict[str, ManualOrderForm] = {}
        engine.manual_scope_validator = validate_scope
        engine.manual_observations = {}
        engine.manual_markets = {account: manual_market(engine, account) for account in engine.gateways}
        with engine.lock:
            if engine.state.manual_books:
                books = tuple(replace(book, halted=True, reasons=('manual_restarted',)) for book in engine.state.manual_books)
                requests = []
                for request in engine.state.manual_requests:
                    if request.operation == 'SUBMIT' and not request.outcome_known:
                        order = next((row for row in engine.state.orders if row.key == request.request_id), None)
                        if order is not None:
                            request = replace(request, order_id=order.order_id, status='UNKNOWN', reason='outcome_unknown')
                        elif not request.order_id:
                            # The canonical SDK call requires a durable order.
                            # A complete replay with only the earlier manual
                            # intent proves this request never reached that call.
                            request = replace(request, status='REJECTED', outcome_known=True, reason='manual_not_submitted')
                    requests.append(request)
                engine._persist(
                    'manual_restart_requires_confirmation',
                    replace(engine.state, manual_books=books, manual_requests=tuple(requests), stopped=True, reconciled=False),
                )

    def _scope(self, command: UiCommand, form=None) -> ManualScope:
        if not isinstance(command, UiCommand):
            raise DomainError('validation_failed')
        if not isinstance(command.action, UiAction) or type(command.expected_version) is not int:
            raise DomainError('validation_failed')
        if form is not None and not isinstance(form, (ManualBookForm, ManualOrderForm, ManualMutationForm)):
            raise DomainError('validation_failed')
        if command.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('production_orders_disabled' if command.environment is Environment.LIVE else 'capability_missing')
        scope = (
            form.scope
            if form is not None
            else ManualScope(
                command.context_id, command.context_epoch, command.environment, command.account_ref, command.connection_generation, command.connection_revision
            )
        )
        if (scope.context_id, scope.context_epoch, scope.environment, scope.account_ref, scope.connection_generation, scope.connection_revision) != (
            command.context_id,
            command.context_epoch,
            command.environment,
            command.account_ref,
            command.connection_generation,
            command.connection_revision,
        ):
            raise DomainError('state_conflict', 'inner and accepted command scope differ')
        if scope.account_ref not in self.engine.gateways or self.engine.configuration.environment is not scope.environment:
            raise DomainError('capability_missing')
        self.validate_scope(scope)
        return scope

    def _fresh(self) -> None:
        engine = self.engine
        rows = engine.manual_observations
        if set(rows) != set(engine.gateways) or any(not 0 <= (engine.clock.now() - row.as_of).total_seconds() <= 30 for row in rows.values()):
            raise DomainError('manual_account_observation_required')
        if not engine.state.reconciled:
            raise DomainError('reconciliation_required')

    def _record_request(self, request: ManualRequest) -> None:
        requests = tuple(row for row in self.engine.state.manual_requests if row.request_id != request.request_id) + (request,)
        self.engine._persist('manual_request_' + request.status.lower(), replace(self.engine.state, manual_requests=requests))

    def _book(self, account_ref: str) -> ManualBook:
        book = book_for(self.engine, account_ref)
        if book is None:
            raise DomainError('manual_book_not_enabled')
        return book

    def _enable(self, form: ManualBookForm) -> None:
        if not isinstance(form, ManualBookForm) or not form.confirmed:
            raise DomainError('manual_confirmation_required')
        self._fresh()
        if book_for(self.engine, form.scope.account_ref) is not None:
            raise DomainError('state_conflict', 'existing book cannot reset capital or loss history')
        if sum((book.capital for book in self.engine.state.manual_books), ZERO) + form.capital > self.engine.risk().policy.total_budget:
            raise DomainError('risk_rejected', 'shared platform capital cap')
        market = manual_market(self.engine, form.scope.account_ref)
        allocation = self.engine.state.settings.stock_allocation if market is Market.STOCK else self.engine.state.settings.futures_allocation
        market_capital = sum((book.capital for book in self.engine.state.manual_books if manual_market(self.engine, book.account_ref) is market), ZERO)
        if form.capital + market_capital > allocation:
            raise DomainError('risk_rejected', 'confirmed manual capital exceeds account allocation')
        remote = self.engine.manual_observations[form.scope.account_ref]
        if remote.positions or any(order.status in ACTIVE for order in remote.orders):
            raise DomainError('reconciliation_required', 'new virtual book requires verified empty account')
        preserve_stop = self.engine.state.manual_stopped or bool(self.engine.state.manual_books) and self.engine.state.stopped
        book = ManualBook(
            MANUAL_PREFIX + uuid4().hex,
            form.scope.account_ref,
            form.capital,
            self.engine.state.trading_day,
            halted=preserve_stop,
            reasons=('risk_rejected',) if preserve_stop else (),
            market=market,
        )
        self.engine._persist(
            'manual_book_confirmed',
            replace(self.engine.state, manual_books=(*self.engine.state.manual_books, book), stopped=self.engine.state.stopped if preserve_stop else False),
        )

    def _resume(self, form: ManualBookForm) -> None:
        if not isinstance(form, ManualBookForm) or not form.confirmed:
            raise DomainError('manual_confirmation_required')
        self._fresh()
        book = self._book(form.scope.account_ref)
        if form.capital != book.capital:
            raise DomainError('state_conflict', 'manual capital and loss history cannot be reset')
        if book.opening_day != self.engine.state.trading_day:
            raise DomainError('manual_day_baseline_required')
        if any(not request.outcome_known for request in self.engine.state.manual_requests):
            raise DomainError('outcome_unknown')
        if any(lot.quantity and lot.strategy_id == book.book_id for lot in self.engine.state.positions):
            raise DomainError('manual_unprotected_position')
        if self.engine.state.trading_day in self.engine.state.daily_locks:
            raise DomainError('risk_rejected')
        books = tuple(replace(row, halted=False, reasons=()) if row.book_id == book.book_id else row for row in self.engine.state.manual_books)
        self.engine._persist('manual_resume_confirmed', replace(self.engine.state, manual_books=books, stopped=False, manual_stopped=False))

    def _diagnostic(self, scope: ManualScope) -> ManualOrderForm:
        self._book(scope.account_ref)
        passed = diagnostic_passed(self.engine, scope.connection_generation)
        if passed or any(not row.outcome_known for row in self.engine.state.manual_requests):
            raise DomainError('state_conflict' if passed else 'manual_test_pending')
        specs = [spec for spec in self.engine.catalog.instruments if spec.market is Market.INDEX_FUTURE and spec.underlying == 'TMF']
        if len(specs) != 1 or manual_market(self.engine, scope.account_ref) is not Market.INDEX_FUTURE:
            raise DomainError('instrument_unresolved', 'one actual TMF account/contract required')
        spec = specs[0]
        bounds = self.limits.get(spec.instrument_id)
        quote = self.engine.quotes.get(spec.instrument_id)
        if bounds is None or quote is None or bounds.observed_at.date() != self.engine.clock.now().date():
            raise DomainError('instrument_unresolved', 'current actual daily price limits required')
        price = spec.round_price(bounds.lower, up=True)
        if price >= quote.bid or price > bounds.upper:
            raise DomainError('risk_rejected', 'verified distant legal price unavailable')
        stop = spec.shift_ticks(price, -1)
        form = ManualOrderForm(scope, uuid4().hex, spec.instrument_id, Side.BUY, 1, price, stop, ManualPurpose.DIAGNOSTIC_TMF)
        self.diagnostics[form.request_id] = form
        if len(self.diagnostics) > 100:
            self.diagnostics.pop(next(iter(self.diagnostics)))
        return form

    def _prepare(self, form: ManualOrderForm) -> ManualPreviewView:
        if not isinstance(form, ManualOrderForm):
            raise DomainError('validation_failed')
        if form.purpose is ManualPurpose.DIAGNOSTIC_TMF and self.diagnostics.get(form.request_id) != replace(form, confirmed=False, preview_id=''):
            raise DomainError('validation_failed', 'only backend-minted diagnostic intent is permitted')
        self._fresh()
        engine, book = self.engine, self._book(form.scope.account_ref)
        spec = engine.catalog.resolve(form.instrument_id)
        quote = engine.quotes.get(form.instrument_id)
        if quote is None:
            raise DomainError('stale_quote')
        session = engine.calendar.session_at(engine.clock.now())
        if (quote.trade_date, quote.session) != (session.trade_date, session.kind):
            raise DomainError('session_closed')
        bounds = self.limits.get(form.instrument_id)
        if bounds is None or bounds.observed_at.date() != engine.clock.now().date() or not bounds.lower <= form.limit_price <= bounds.upper:
            raise DomainError('instrument_unresolved', 'current verified daily limits required')
        if manual_market(engine, form.scope.account_ref) is not spec.market:
            raise DomainError('capability_missing')
        if form.quantity % spec.lot_size:
            raise DomainError('risk_rejected', 'whole lots/contracts only')
        reduce_only = bool(form.exit_lot_id)
        plan = OrderPlan(
            uuid4().hex,
            form.scope.account_ref,
            Environment.BROKER_SIMULATION,
            form.instrument_id,
            book.book_id,
            1,
            form.side,
            form.quantity,
            spec.unit,
            form.limit_price,
            form.stop_price,
            reduce_only,
            engine.clock.now(),
            engine.clock.now() + timedelta(seconds=30),
            engine.state.version,
            form.exit_lot_id or None,
        )
        request = ManualRequest(form.scope, form.request_id, 'SUBMIT', '', form.purpose, plan, manual_policy())
        account, allocations, capability, pnl = manual_risk_context(engine, request, plan)
        if any(not row.outcome_known for row in engine.state.manual_requests):
            raise DomainError('outcome_unknown')
        if form.purpose is ManualPurpose.DIAGNOSTIC_TMF and (spec.underlying != 'TMF' or form.quantity != 1 or form.side is not Side.BUY or reduce_only):
            raise DomainError('validation_failed', 'diagnostic intent shape')
        if reduce_only:
            lot = next((row for row in engine.state.positions if row.lot_id == form.exit_lot_id), None)
            if lot is None or lot.strategy_id != book.book_id:
                raise DomainError('capability_missing', 'manual book-owned exit required')
            engine._check_exit(plan)
        decision = engine.risk().preview(
            plan,
            spec,
            quote,
            account,
            capability,
            now=engine.clock.now(),
            reservations=engine.reservations(),
            daily_pnl=pnl,
            daily_locked=engine.state.trading_day in engine.state.daily_locks,
            allocations=allocations,
            policy=request.policy,
        )
        allowed = decision.allowed and decision.quantity == form.quantity
        available = max(
            ZERO,
            min(account.allocated_cash, account.settled_cash, account.broker_limit)
            - account.margin_used
            - account.settlement_reserved
            - sum((row.cash for row in engine.reservations() if row.account_ref == account.account_ref), ZERO),
        )
        preview = ManualPreviewView(
            form.scope,
            form.request_id,
            uuid4().hex,
            form.instrument_id,
            form.side,
            form.quantity,
            form.limit_price,
            form.stop_price,
            form.purpose,
            allowed,
            decision.cash_required,
            decision.risk_required,
            engine.fees.transaction(spec, form.side, form.limit_price, form.quantity),
            available,
            CAPACITY_SOURCE,
            self.cost_source,
            quote.source_at,
            plan.deadline,
            () if allowed else (decision.code,),
            quantity_unit=spec.unit,
            lot_size=spec.lot_size,
        )
        self.previews[preview.preview_id] = (replace(form, confirmed=False, preview_id=''), preview)
        # Only a bounded transient UI preparation cache; durable admitted intents
        # are retained separately and never evicted to permit another send.
        if len(self.previews) > 100:
            self.previews.pop(next(iter(self.previews)))
        return preview

    def _replay(self, form, operation: str) -> UiReceipt | None:
        prior = request_for(self.engine, form.request_id)
        if prior is None:
            return None
        if prior.scope != form.scope or prior.operation != operation or prior.form_hash != sha256(dumps(form).encode()).hexdigest():
            raise DomainError('state_conflict', 'manual request identity reused with different command')
        return UiReceipt(
            prior.outcome_known and prior.status != 'REJECTED', prior.reason or ('ok' if prior.outcome_known else 'outcome_unknown'), '', prior.order_id
        )

    def _submit(self, form: ManualOrderForm) -> str:
        if not isinstance(form, ManualOrderForm) or not form.confirmed:
            raise DomainError('manual_confirmation_required')
        cached = self.previews.get(form.preview_id)
        if cached is None or cached[0] != replace(form, confirmed=False, preview_id='') or self.engine.clock.now() >= cached[1].expires_at:
            raise DomainError('state_conflict', 'matching unexpired preview required')
        preview = self._prepare(replace(form, confirmed=False, preview_id=''))
        if not preview.allowed:
            raise DomainError(preview.reasons[0])
        previous = cached[1]
        if (preview.total_cash, preview.risk_cash, preview.fee_cash, preview.funds_source, preview.cost_source) != (
            previous.total_cash,
            previous.risk_cash,
            previous.fee_cash,
            previous.funds_source,
            previous.cost_source,
        ):
            raise DomainError('state_conflict', 'confirmed preview economics changed')
        engine, book = self.engine, self._book(form.scope.account_ref)
        spec = engine.catalog.resolve(form.instrument_id)
        plan = OrderPlan(
            form.request_id,
            form.scope.account_ref,
            Environment.BROKER_SIMULATION,
            form.instrument_id,
            book.book_id,
            1,
            form.side,
            form.quantity,
            spec.unit,
            form.limit_price,
            form.stop_price,
            bool(form.exit_lot_id),
            engine.clock.now(),
            engine.clock.now() + timedelta(seconds=30),
            engine.state.version + 1,
            form.exit_lot_id or None,
        )
        request = ManualRequest(form.scope, form.request_id, 'SUBMIT', sha256(dumps(form).encode()).hexdigest(), form.purpose, plan, manual_policy())
        self._record_request(request)
        try:
            order_id = engine.submit(plan, request.policy, form.request_id)
        except DomainError as error:
            order = next((row for row in engine.state.orders if row.key == form.request_id), None)
            if not engine.storage_failed:
                self._record_request(
                    replace(
                        request,
                        order_id=order.order_id if order else '',
                        status='UNKNOWN' if order else 'REJECTED',
                        outcome_known=order is None,
                        reason=error.code if order is None else 'outcome_unknown',
                    )
                )
                if order is not None:
                    self._halt('outcome_unknown')
            raise
        order = next(row for row in engine.state.orders if row.order_id == order_id)
        request = replace(
            request,
            order_id=order_id,
            status=order.status.value,
            outcome_known=order.status not in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.FILLED, OrderStatus.CANCELED),
            reason='broker_rejected' if order.status is OrderStatus.REJECTED else 'outcome_unknown' if order.status is OrderStatus.UNKNOWN else '',
        )
        if form.purpose is ManualPurpose.DIAGNOSTIC_TMF:
            if order.status in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
                self._record_request(replace(request, status='TEST_CANCEL_PENDING', outcome_known=False))
                try:
                    ExecutionService(engine.gateways[form.scope.account_ref], engine._persist, engine.fence, engine.clock.now).cancel(engine.state, order_id)
                except Exception:
                    if not engine.storage_failed:
                        self._record_request(replace(request, status='UNKNOWN', outcome_known=False, reason='outcome_unknown'))
                        self._halt('outcome_unknown')
                    raise DomainError('outcome_unknown') from None
                return order_id
            if order.status is OrderStatus.FILLED:
                self._halt('manual_unprotected_position')
            if order.status in TERMINAL:
                request = replace(request, outcome_known=False)
                books = tuple(
                    replace(row, test_status='FAILED' if order.status is OrderStatus.REJECTED else 'PENDING', test_reason=request.reason)
                    if row.book_id == book.book_id
                    else row
                    for row in engine.state.manual_books
                )
                engine._persist('manual_diagnostic_receipt', replace(engine.state, manual_books=books))
        self._record_request(request)
        return order_id

    def _mutate(self, form: ManualMutationForm, operation: str) -> str:
        if not isinstance(form, ManualMutationForm) or not form.confirmed:
            raise DomainError('manual_confirmation_required')
        engine, book = self.engine, self._book(form.scope.account_ref)
        order = next((row for row in engine.state.orders if row.order_id == form.order_id), None)
        if order is None or order.plan.account_ref != form.scope.account_ref or order.plan.strategy_id != book.book_id:
            raise DomainError('capability_missing', 'owned manual order required')
        if form.quantity is not None:
            raise DomainError('manual_quantity_amend_unsupported')
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            raise DomainError('reconciliation_required')
        if any(not row.outcome_known and row.order_id == order.order_id for row in engine.state.manual_requests):
            raise DomainError('outcome_unknown')
        if operation == 'AMEND':
            self._fresh()
            if form.price is None:
                raise DomainError('validation_failed')
            spec = engine.catalog.resolve(order.plan.instrument_id)
            spec.validate_price(form.price)
            quote = engine.quotes.get(spec.instrument_id)
            if (
                quote is None
                or quote.quality != 'VERIFIED'
                or not 0 <= (engine.clock.now() - quote.source_at).total_seconds() <= 30
                or not 0 <= (engine.clock.now() - quote.received_at).total_seconds() <= 30
            ):
                raise DomainError('stale_quote')
            bounds = self.limits.get(spec.instrument_id)
            if bounds is None or bounds.observed_at.date() != engine.clock.now().date() or not bounds.lower <= form.price <= bounds.upper:
                raise DomainError('instrument_unresolved')
            # Price-only reductions retain the original conservative reservation
            # until terminal evidence. Increasing cash or stop risk is refused.
            if (order.plan.side is Side.BUY and not order.plan.stop_price < form.price <= order.plan.limit_price) or (
                order.plan.side is Side.SELL and not order.plan.limit_price <= form.price < order.plan.stop_price
            ):
                raise DomainError('risk_rejected', 'amendment would increase risk')
        request = ManualRequest(form.scope, form.request_id, operation, sha256(dumps(form).encode()).hexdigest(), order_id=order.order_id, price=form.price)
        self._record_request(request)
        engine.fence()
        try:
            if operation == 'CANCEL':
                ExecutionService(engine.gateways[form.scope.account_ref], engine._persist, engine.fence, engine.clock.now).cancel(engine.state, order.order_id)
            else:
                receipt = engine.gateways[form.scope.account_ref].amend(order.order_id, form.price, None)
                if receipt.status is OrderStatus.UNKNOWN:
                    raise DomainError('outcome_unknown')
        except Exception:
            self._record_request(replace(request, status='UNKNOWN', reason='outcome_unknown'))
            self._halt('outcome_unknown')
            raise DomainError('outcome_unknown') from None
        return order.order_id

    def _halt(self, reason: str) -> None:
        engine = self.engine
        books = tuple(replace(book, halted=True, reasons=tuple(sorted(set((*book.reasons, reason))))) for book in engine.state.manual_books)
        proposed = replace(engine.state, manual_books=books, stopped=True)
        if proposed != engine.state:
            engine._persist('manual_new_risk_halted', proposed)

    def _result(self, request: ManualRequest) -> ManualPendingView:
        return ManualPendingView(
            request.scope, request.request_id, request.operation, request.purpose, request.order_id, request.status, request.outcome_known, request.reason
        )

    def _flatten(self, command: UiCommand, scope: ManualScope) -> str:
        book = self._book(scope.account_ref)
        lot = next((row for row in self.engine.state.positions if row.lot_id == command.target_id and row.quantity), None)
        if lot is None or lot.account_ref != scope.account_ref or lot.strategy_id != book.book_id:
            raise DomainError('exit_unavailable')
        quote = self.engine.quotes.get(lot.instrument_id)
        if quote is None:
            raise DomainError('stale_quote')
        side = Side.SELL if lot.direction is Side.BUY else Side.BUY
        price = quote.bid if side is Side.SELL else quote.ask
        pending = sum(
            order.plan.quantity - order.filled for order in self.engine.state.orders if order.plan.exit_lot_id == lot.lot_id and order.status in ACTIVE
        )
        quantity = min(lot.quantity, lot.sellable_quantity) - pending
        if quantity <= 0:
            raise DomainError('exit_already_pending' if pending else 'exit_unavailable')
        form = ManualOrderForm(scope, uuid4().hex, lot.instrument_id, side, quantity, price, price, exit_lot_id=lot.lot_id)
        preview = self._prepare(form)
        order_id = self._submit(replace(form, confirmed=True, preview_id=preview.preview_id))
        order = next(row for row in self.engine.state.orders if row.order_id == order_id)
        if order.status is OrderStatus.REJECTED:
            raise DomainError('broker_rejected')
        return order_id

    def execute(self, command: UiCommand) -> UiReceipt:
        with self.engine.lock:
            try:
                form = command.manual_book or command.manual_order or command.manual_mutation
                scope = self._scope(command, form)
                operation = (
                    'SUBMIT'
                    if command.action in (UiAction.SUBMIT_MANUAL, UiAction.TEST_SIM_ORDER)
                    else 'CANCEL'
                    if command.action is UiAction.CANCEL_MANUAL
                    else 'AMEND'
                )
                if command.action in (UiAction.SUBMIT_MANUAL, UiAction.CANCEL_MANUAL, UiAction.AMEND_MANUAL, UiAction.TEST_SIM_ORDER) and form is not None:
                    if not isinstance(form, (ManualOrderForm, ManualMutationForm)):
                        raise DomainError('validation_failed')
                    replay = self._replay(form, operation)
                    if replay is not None:
                        return replay
                if command.expected_version != self.engine.state.version:
                    raise DomainError('state_conflict')
                if self.engine.state.engine_closed or self.engine.storage_failed:
                    raise DomainError('journal_failed' if self.engine.storage_failed else 'state_conflict')
                self.engine.assert_execution_allowed()
                if command.action is UiAction.ENABLE_MANUAL_BOOK:
                    self._enable(command.manual_book)
                    return UiReceipt(True, 'ok', '')
                if command.action is UiAction.RESUME:
                    self._resume(command.manual_book)
                    return UiReceipt(True, 'ok', '')
                if command.action is UiAction.PREVIEW_MANUAL:
                    preview = self._prepare(command.manual_order)
                    return UiReceipt(True, 'ok', '', preview.preview_id)
                if command.action is UiAction.TEST_SIM_ORDER and command.manual_order is None:
                    preview = self._prepare(self._diagnostic(scope))
                    return UiReceipt(True, 'ok', '', preview.preview_id)
                if command.action is UiAction.FLATTEN:
                    book = self._book(scope.account_ref)
                    if not isinstance(command.manual_book, ManualBookForm) or not command.manual_book.confirmed:
                        raise DomainError('manual_confirmation_required')
                    if command.manual_book.capital != book.capital:
                        raise DomainError('state_conflict')
                    return UiReceipt(True, 'ok', '', self._flatten(command, scope))
                if command.action in (UiAction.SUBMIT_MANUAL, UiAction.TEST_SIM_ORDER):
                    if not isinstance(command.manual_order, ManualOrderForm) or (command.action is UiAction.TEST_SIM_ORDER) != (
                        command.manual_order.purpose is ManualPurpose.DIAGNOSTIC_TMF
                    ):
                        raise DomainError('validation_failed')
                    reference = self._submit(command.manual_order)
                elif command.action in (UiAction.CANCEL_MANUAL, UiAction.AMEND_MANUAL):
                    reference = self._mutate(command.manual_mutation, operation)
                else:
                    raise DomainError('capability_missing')
                request = request_for(self.engine, form.request_id)
                code = request.reason if request is not None and request.reason else 'ok'
                return UiReceipt(code not in ('broker_rejected', 'outcome_unknown'), code, '', reference)
            except DomainError as error:
                text = ERROR_TABLE.get(error.code, ERROR_TABLE['operation_failed'])
                return UiReceipt(False, error.code, text.explanation + ' ' + text.action)

    def _complete_requests(self, observations: dict[str, ManualAccountObservation]) -> None:
        for request in tuple(self.engine.state.manual_requests):
            if request.outcome_known or not request.order_id:
                continue
            remote = observations.get(request.scope.account_ref)
            observed = next((row for row in remote.orders if row.local_order_id == request.order_id), None) if remote else None
            if observed is None:
                continue
            terminal = observed.status in TERMINAL
            amended = request.operation == 'AMEND' and dict(remote.amended_prices).get(request.order_id) == request.price
            submitted = (
                request.operation == 'SUBMIT'
                and request.purpose is not ManualPurpose.DIAGNOSTIC_TMF
                and observed.status not in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING)
            )
            if terminal or amended or submitted:
                reason = 'broker_rejected' if observed.status is OrderStatus.REJECTED else ''
                self._record_request(replace(request, status=observed.status.value if not amended else 'AMENDED', outcome_known=True, reason=reason))
                if request.purpose is ManualPurpose.DIAGNOSTIC_TMF:
                    passed = observed.status is OrderStatus.CANCELED and observed.cumulative_quantity == 0
                    books = tuple(
                        replace(book, test_status='PASSED' if passed else 'FAILED', test_reason=reason or ('' if passed else 'manual_unprotected_position'))
                        if book.account_ref == request.scope.account_ref
                        else book
                        for book in self.engine.state.manual_books
                    )
                    self.engine._persist('manual_diagnostic_observed', replace(self.engine.state, manual_books=books))

    def adopt(self, observations: tuple[ManualAccountObservation, ...]) -> None:
        with self.engine.lock:
            engine = self.engine
            rows = {row.account_ref: row for row in observations}
            try:
                from .sessions import synchronize_session

                synchronize_session(engine)
                if len(rows) != len(observations) or set(rows) != set(engine.gateways):
                    raise DomainError('manual_account_observation_required')
                for account, remote in rows.items():
                    if (
                        remote.environment is not Environment.BROKER_SIMULATION
                        or remote.source != 'SHIOAJI_SCOPED_REFRESH_HEALTHY'
                        or not 0 <= (engine.clock.now() - remote.as_of).total_seconds() <= 30
                    ):
                        raise DomainError('manual_account_observation_required')
                    for event in remote.events:
                        local = next((order for order in engine.state.orders if order.order_id == event.local_order_id), None)
                        if local is None or local.plan.account_ref != account:
                            raise DomainError('reconciliation_required')
                        apply_event(engine, event, reconciled=True)
                    expected = {}
                    for lot in engine.state.positions:
                        if lot.account_ref == account and lot.quantity:
                            expected[lot.instrument_id] = expected.get(lot.instrument_id, 0) + lot.quantity * (1 if lot.direction is Side.BUY else -1)
                    actual = {position.instrument_id: position.quantity for position in remote.positions if position.quantity}
                    if any(
                        engine.catalog.resolve(position.instrument_id).market is Market.STOCK and position.source != 'SHIOAJI_OBSERVED_UNFINANCED_CASH_LONG'
                        for position in remote.positions
                        if position.quantity
                    ):
                        raise DomainError('reconciliation_required', 'cash-long stock observation required')
                    if len(actual) != sum(bool(position.quantity) for position in remote.positions) or expected != actual:
                        raise DomainError('reconciliation_required')
                    owned = {order.order_id: order for order in engine.state.orders if order.plan.account_ref == account}
                    seen = {order.local_order_id for order in remote.orders}
                    if any(order.status in ACTIVE and order.order_id not in seen for order in owned.values()):
                        raise DomainError('outcome_unknown')
                    for order in remote.orders:
                        if (
                            order.local_order_id not in owned
                            or owned[order.local_order_id].plan != order.plan
                            or order.status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING)
                        ):
                            raise DomainError('reconciliation_required')
                    for order_id, price in remote.amended_prices:
                        local = owned.get(order_id)
                        if local is None:
                            raise DomainError('reconciliation_required')
                        approved = {request.price for request in engine.state.manual_requests if request.operation == 'AMEND' and request.order_id == order_id}
                        if price != local.plan.limit_price and price not in approved:
                            raise DomainError('reconciliation_required', 'unowned order price modification')
                engine.manual_observations = rows
                available = manual_stock_availability(engine)
                if available != engine.state.positions:
                    engine._persist('manual_owned_availability_observed', replace(engine.state, positions=available))
                if not engine.state.reconciled:
                    engine._persist('manual_account_observed', replace(engine.state, reconciled=True))
                if (
                    engine.state.manual_books
                    and not engine.state.orders
                    and not engine.state.manual_requests
                    and not any(lot.quantity for lot in engine.state.positions)
                    and not engine.state.manual_stopped
                    and not engine.state.daily_locks
                    and all(not book.halted for book in engine.state.manual_books)
                ):
                    # A confirmed but never-used empty book can begin its first
                    # verified session. This cannot reset an admitted intent,
                    # fill, loss, STOP_NEW latch or restarted book.
                    books = tuple(replace(book, opening_day=engine.state.trading_day) for book in engine.state.manual_books)
                    proposed = replace(engine.state, manual_books=books, stopped=False)
                    if proposed != engine.state:
                        engine._persist('manual_empty_genesis_session', proposed)
                self._complete_requests(rows)
                for book in engine.state.manual_books:
                    if any(lot.quantity and lot.strategy_id == book.book_id for lot in engine.state.positions):
                        self._halt('manual_unprotected_position')
                    if book.opening_day != engine.state.trading_day:
                        self._halt('manual_day_baseline_required')
                daily_pnl = sum((manual_net_pnl(engine, book) for book in engine.state.manual_books), ZERO)
                if -daily_pnl >= engine.risk().policy.total_budget * engine.state.settings.daily_loss_fraction:
                    if engine.state.trading_day not in engine.state.daily_locks:
                        engine._persist('manual_daily_loss_latched', replace(engine.state, daily_locks=(*engine.state.daily_locks, engine.state.trading_day)))
                    self._halt('risk_rejected')
            except DomainError as error:
                engine.manual_observations = {}
                self._halt(error.code)
                if engine.state.reconciled:
                    engine._persist('manual_observation_unresolved', replace(engine.state, reconciled=False))
                raise

    def _market_readiness(self, scope: ManualScope, spec) -> str:
        try:
            engine, now = self.engine, self.engine.clock.now()
            engine.assert_execution_allowed()
            capability = engine.gateways[scope.account_ref].inspect(scope.account_ref)
            if not capability.can_trade or not capability.checked_at <= now < capability.expires_at or spec.market not in capability.markets:
                raise DomainError('capability_missing')
            session = engine.calendar.session_at(now)
            quote, bounds = engine.quotes.get(spec.instrument_id), self.limits.get(spec.instrument_id)
            if (
                quote is None
                or quote.quality != 'VERIFIED'
                or not 0 <= (now - quote.source_at).total_seconds() <= 30
                or not 0 <= (now - quote.received_at).total_seconds() <= 30
            ):
                raise DomainError('stale_quote')
            if (quote.trade_date, quote.session) != (session.trade_date, session.kind):
                raise DomainError('session_closed')
            if (
                bounds is None
                or bounds.observed_at.date() != session.trade_date
                or bounds.observed_at > now
                or spec.effective_at > now
                or (spec.expiry and spec.expiry < session.trade_date)
            ):
                raise DomainError('instrument_unresolved')
            return ''
        except DomainError as error:
            return error.code

    def _instruments(self, scope: ManualScope) -> tuple[ManualInstrumentView, ...]:
        market = manual_market(self.engine, scope.account_ref)
        result = []
        for spec in self.engine.catalog.instruments:
            if spec.market is not market:
                continue
            quote, bounds = self.engine.quotes.get(spec.instrument_id), self.limits.get(spec.instrument_id)
            reason = self._market_readiness(scope, spec)
            result.append(
                ManualInstrumentView(
                    spec.instrument_id,
                    spec.instrument_id,
                    spec.market,
                    spec.unit,
                    spec.lot_size,
                    spec.lot_size,
                    None if spec.price_bands else spec.tick_size,
                    spec.price_bands,
                    bounds.lower if bounds else None,
                    bounds.upper if bounds else None,
                    quote.last if quote else None,
                    quote.bid if quote else None,
                    quote.ask if quote else None,
                    quote.source_at if quote else None,
                    spec.margin,
                    self.margin_source,
                    tradable=not reason,
                    reasons=(reason,) if reason else (),
                )
            )
        return tuple(result)

    def snapshot(self, scope: ManualScope) -> ManualTradingView:
        with self.engine.lock:
            book = book_for(self.engine, scope.account_ref)
            reasons = []
            try:
                self.validate_scope(scope)
                self._fresh()
                self.engine.assert_execution_allowed()
                capability = self.engine.gateways[scope.account_ref].inspect(scope.account_ref)
                if not capability.can_trade or not capability.checked_at <= self.engine.clock.now() < capability.expires_at:
                    raise DomainError('capability_missing')
            except DomainError as error:
                reasons.append(error.code)
            if scope.environment is not Environment.BROKER_SIMULATION:
                reasons.append('production_orders_disabled')
            scope_ready = not reasons
            requests = tuple(row for row in self.engine.state.manual_requests if row.scope.account_ref == scope.account_ref)
            pending = next((row for row in reversed(requests) if not row.outcome_known), None)
            preview = next((view for _, view in reversed(tuple(self.previews.values())) if view.scope == scope), None)
            market = manual_market(self.engine, scope.account_ref)
            allocation = self.engine.state.settings.stock_allocation if market is Market.STOCK else self.engine.state.settings.futures_allocation
            suggested = max(
                ZERO,
                allocation
                - sum(
                    (
                        row.capital
                        for row in self.engine.state.manual_books
                        if row.account_ref != scope.account_ref and manual_market(self.engine, row.account_ref) is market
                    ),
                    ZERO,
                ),
            )
            if book is None:
                return ManualTradingView(
                    scope,
                    suggested_capital=suggested,
                    reasons=tuple(reasons or ['manual_book_not_enabled']),
                    instruments=self._instruments(scope),
                    can_prepare=not reasons,
                )
            reasons.extend(book.reasons)
            if not manual_allocations_valid(self.engine):
                reasons.append('manual_allocation_exceeds_settings')
            if self.engine.state.stopped and not reasons:
                reasons.append('risk_rejected')
            try:
                capacity = manual_capacity(self.engine, book)
                available = max(
                    ZERO,
                    min(capacity.allocated_cash, capacity.settled_cash, capacity.broker_limit)
                    - capacity.margin_used
                    - capacity.settlement_reserved
                    - sum((row.cash for row in self.engine.reservations() if row.account_ref == scope.account_ref), ZERO),
                )
            except DomainError as error:
                available = None
                reasons.append(error.code)
            halted = book.halted or self.engine.state.stopped or bool(reasons)
            ready = not halted and not any(not row.outcome_known for row in self.engine.state.manual_requests)
            instruments = self._instruments(scope)
            market_ready = any(item.tradable for item in instruments)
            if not market_ready:
                reasons.extend(reason for item in instruments for reason in item.reasons)
                if not instruments:
                    reasons.append('instrument_unresolved')
            ready = ready and market_ready
            passed = diagnostic_passed(self.engine, scope.connection_generation)
            if not passed:
                reasons.append('manual_futures_test_required' if market is Market.STOCK else 'manual_test_required')
            return ManualTradingView(
                scope,
                book.book_id,
                book.capital,
                available,
                suggested,
                confirmed=True,
                halted=halted,
                reasons=tuple(sorted(set(reasons))),
                instruments=instruments,
                preview=preview,
                pending=self._result(pending) if pending else None,
                last_result=self._result(requests[-1]) if requests else None,
                manual_order_ids=tuple(row.order_id for row in self.engine.state.orders if row.plan.strategy_id == book.book_id),
                test_status='PASSED' if passed else 'UNTESTED' if book.test_status == 'PASSED' else book.test_status,
                test_reason=book.test_reason,
                can_preview=ready and passed,
                can_submit=ready and passed,
                can_test=ready and not passed and market is Market.INDEX_FUTURE,
                can_mutate=scope_ready,
            )
