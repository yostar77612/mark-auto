"""Confirmed manual intents sent through the existing asynchronous UI port."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from PySide6.QtWidgets import QHBoxLayout, QInputDialog

from desktop_app.features.trading.manual_form import ManualForm
from desktop_app.features.trading.manual_intents import ManualIntents, scope_matches
from desktop_app.features.trading.manual_presenter import preview_text, render_manual
from desktop_app.features.trading.widgets import button, selected_id
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.contracts import ManualBookForm, ManualMutationForm, ManualOrderForm, ManualPurpose
from quantlab.trading.domain.models import Environment, Market, Side
from quantlab.trading.domain.validation import DomainError


class ManualActions:
    def __init__(self, window, layout):
        self.window = window
        self.form = ManualForm(window, header=window.page_headers['trading'])
        self.intents = ManualIntents()
        self.scope, self.instruments = None, ()
        self._reviewed_inputs = None
        layout.insertWidget(4, self.form)
        row = QHBoxLayout()
        self.cancel = button('m2m.cancel', 'manual_cancel', role='danger')
        self.amend = button('m2m.amend', 'manual_amend')
        row.addWidget(self.cancel)
        row.addWidget(self.amend)
        row.addStretch()
        layout.addLayout(row)
        self.form.prepare.clicked.connect(self._prepare)
        self.form.preview_button.clicked.connect(self._preview)
        self.form.submit.clicked.connect(self._submit)
        self.form.test_order.clicked.connect(self._test)
        self.form.positions_button.clicked.connect(lambda: window.navigation.setCurrentRow(2))
        self.cancel.clicked.connect(lambda: self._mutate(False))
        self.amend.clicked.connect(lambda: self._mutate(True))
        self.form.instrument.currentIndexChanged.connect(self._changed)
        self.form.side.currentIndexChanged.connect(self._changed)
        self.form.quantity.valueChanged.connect(self._changed)
        self.form.price.textEdited.connect(self._changed)
        self.form.stop.textEdited.connect(self._changed)
        window.orders.itemSelectionChanged.connect(lambda: self.render(window.state))
        window.positions.itemSelectionChanged.connect(lambda: self.render(window.state))

    def busy(self):
        return self.window._operation is not None or self.window._priority_operation is not None

    def matches(self, state):
        return self.window._engine_reachable and scope_matches(state, state.manual.scope)

    def next_step(self):
        state = self.window.state
        if state.environment is Environment.LOCAL:
            self.window.navigation.setCurrentRow(1)
        elif self.matches(state):
            self.window.navigation.setCurrentRow(3)
            target = self.form.instrument if state.manual.confirmed else self.form.capital
            self.window.pages.widget(3).ensureWidgetVisible(target)
            target.setFocus()
        else:
            self.window.navigation.setCurrentRow(5)

    def unresolved(self, state):
        return self.intents.unresolved(state)

    def invalidate(self):
        self.intents.preview_id, self.intents.preview_request, self.intents.review_version = '', '', None
        self._reviewed_inputs = None

    def _inputs(self):
        form = self.form
        return form.instrument.currentData(), form.side.currentData(), form.quantity.value(), form.price.text(), form.stop.text()

    def _changed(self):
        self.invalidate()
        self.render(self.window.state)

    def render(self, state):
        render_manual(self, state)

    def preview(self, state):
        preview = state.manual.preview
        if (
            preview is not None
            and self.matches(state)
            and preview.scope == state.manual.scope
            and (preview.preview_id, preview.request_id, state.version) == (self.intents.preview_id, self.intents.preview_request, self.intents.review_version)
        ):
            if preview.expires_at.tzinfo is not None and preview.expires_at > datetime.now(timezone.utc):
                return preview
        return None

    def received(self, command, state, receipt):
        if command is not None and command.action is UiAction.PREVIEW_MANUAL and self._inputs() != self._reviewed_inputs:
            return
        self.intents.received(command, state, receipt)

    def selected_order(self):
        identity = selected_id(self.window.orders)
        state = self.window.state
        return next(
            (
                order
                for order in state.orders
                if order.order_id == identity and identity in state.manual.manual_order_ids and order.account_ref == state.account_ref
            ),
            None,
        )

    def _ready(self, capability):
        state = self.window.state
        return self.matches(state) and not self.busy() and not self.unresolved(state) and getattr(state.manual, capability)

    def _confirm(self, text):
        state = self.window.state
        stamp = (state.version, state.manual.scope)
        if not self.window._confirm(ui_text('m2m.confirm_scope').format(state.account_ref, text)):
            return False
        current = self.window.state
        if stamp != (current.version, current.manual.scope) or not self.matches(current):
            self.window._feedback(ui_text('v2.state_conflict'))
            return False
        return True

    def _send(self, action, *, order=None, book=None, mutation=None, target_id=''):
        state = self.window.state
        scope = state.manual.scope
        self.window.command(
            action,
            target_id,
            environment=scope.environment,
            account_ref=scope.account_ref,
            manual_order=order,
            manual_book=book,
            manual_mutation=mutation,
            connection_generation=scope.connection_generation,
            connection_revision=scope.connection_revision,
        )
        # Only retain intents actually handed to this window's worker.
        operation = self.window._operation
        if operation is not None and operation.command is not None and operation.command.action is action:
            intent = mutation or order
            if intent is not None and intent.confirmed:
                self.intents.pending[intent.request_id] = intent.scope
        self.render(state)

    def _prepare(self):
        if not self._ready('can_prepare') or self.window.state.manual.confirmed:
            return
        try:
            book = ManualBookForm(self.window.state.manual.scope, Decimal(self.form.capital.text()), True)
        except (InvalidOperation, DomainError):
            self.window._feedback(ui_text('m2m.invalid'))
            return
        if self._confirm(ui_text('m2m.confirm_book').format(book.capital)) and self._ready('can_prepare'):
            self._send(UiAction.ENABLE_MANUAL_BOOK, book=book)

    def _preview(self):
        if not self._ready('can_preview'):
            return
        state = self.window.state
        instrument = next((item for item in state.manual.instruments if item.instrument_id == self.form.instrument.currentData()), None)
        if instrument is None or not instrument.tradable:
            return
        if instrument.market is Market.STOCK and self.form.side.currentData() == Side.SELL:
            self.window._feedback(ui_text('m2m.stock_exit_hint'))
            return
        try:
            order = self.form.order(state.manual.scope, instrument, str(uuid4()))
        except (InvalidOperation, DomainError):
            self.window._feedback(ui_text('m2m.invalid'))
            return
        self.invalidate()
        self._reviewed_inputs = self._inputs()
        self._send(UiAction.PREVIEW_MANUAL, order=order)

    def _test(self):
        if self._ready('can_test'):
            self.invalidate()
            self._send(UiAction.TEST_SIM_ORDER)

    def _submit(self):
        state = self.window.state
        preview = self.preview(state)
        if preview is None or not preview.allowed:
            return
        diagnostic = preview.purpose is ManualPurpose.DIAGNOSTIC_TMF
        capability = 'can_test' if diagnostic else 'can_submit'
        if not self._ready(capability):
            return
        text = preview_text(preview) + '\n' + (ui_text('m2m.test_warning') if diagnostic else ui_text('m2m.submit_warning'))
        if not self._confirm(text) or not self._ready(capability) or self.preview(self.window.state) != preview:
            return
        order = ManualOrderForm(
            preview.scope,
            preview.request_id,
            preview.instrument_id,
            preview.side,
            preview.quantity,
            preview.limit_price,
            preview.stop_price,
            preview.purpose,
            True,
            preview.preview_id,
        )
        self.invalidate()
        self._send(UiAction.TEST_SIM_ORDER if diagnostic else UiAction.SUBMIT_MANUAL, order=order)

    def _mutate(self, amend):
        if not self._ready('can_mutate'):
            return
        order = self.selected_order()
        if order is None:
            return
        state = self.window.state
        stamp = (state.version, state.manual.scope, order.order_id)
        price = None
        if amend:
            text, accepted = QInputDialog.getText(self.window, ui_text('m2m.amend'), ui_text('m2m.amend_hint'))
            if not accepted:
                return
            try:
                price = Decimal(text)
                if not price.is_finite() or price <= 0:
                    raise InvalidOperation
            except InvalidOperation:
                self.window._feedback(ui_text('m2m.invalid'))
                return
        current = self.window.state
        selected = self.selected_order()
        if selected is None or stamp != (current.version, current.manual.scope, selected.order_id):
            self.window._feedback(ui_text('v2.state_conflict'))
            return
        text = (ui_text('m2m.confirm_amend') if amend else ui_text('m2m.confirm_cancel')).format(order.instrument_id, order.order_id, price)
        if self._confirm(text) and self._ready('can_mutate') and self.selected_order() == order:
            mutation = ManualMutationForm(state.manual.scope, str(uuid4()), order.order_id, price=price, confirmed=True)
            self._send(UiAction.AMEND_MANUAL if amend else UiAction.CANCEL_MANUAL, mutation=mutation)

    def resume(self):
        state = self.window.state
        if state.environment is not Environment.BROKER_SIMULATION:
            self.window.command(UiAction.RESUME)
            return
        if (
            self.matches(state)
            and not self.busy()
            and not self.unresolved(state)
            and state.manual.confirmed
            and state.manual.halted
            and state.manual.capital is not None
        ):
            book = ManualBookForm(state.manual.scope, state.manual.capital, True)
            if not self._confirm(ui_text('m2m.resume_warning')):
                return
            current = self.window.state
            if (
                self.matches(current)
                and not self.busy()
                and not self.unresolved(current)
                and current.manual.confirmed
                and current.manual.halted
                and current.manual.capital == book.capital
            ):
                self._send(UiAction.RESUME, book=book)

    def flatten(self, position, summary):
        state, manual = self.window.state, self.window.state.manual
        if (
            not self._ready('can_mutate')
            or not manual.confirmed
            or manual.capital is None
            or (position.account_ref, position.strategy_id) != (state.account_ref, manual.book_id)
        ):
            return
        book = ManualBookForm(manual.scope, manual.capital, True)
        if self._confirm(summary + '\n' + ui_text('m2m.exit_source')) and self._ready('can_mutate'):
            if selected_id(self.window.positions) != position.lot_id or self.window.state.manual.capital != book.capital:
                self.window._feedback(ui_text('v2.state_conflict'))
                return
            self._send(UiAction.FLATTEN, book=book, target_id=position.lot_id)
