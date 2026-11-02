"""Preview an owned manual exit, then confirm and submit that exact preview."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from desktop_app.features.trading.manual_presenter import clock, quantity_text, reason_text
from desktop_app.features.trading.widgets import selected_id
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import ManualOrderForm, UiAction
from quantlab.trading.domain.models import Side


class ManualExitPreview:
    def __init__(self, controller):
        self.controller = controller
        self.request = None
        self.review = None

    def start(self, position):
        controller, state = self.controller, self.controller.window.state
        manual = state.manual
        if (
            not controller._ready('can_mutate')
            or not manual.confirmed
            or manual.capital is None
            or (position.account_ref, position.strategy_id) != (state.account_ref, manual.book_id)
        ):
            return
        instrument = next((item for item in manual.instruments if item.instrument_id == position.instrument_id), None)
        side = Side.SELL if position.direction is Side.BUY else Side.BUY
        price = (instrument.bid if side is Side.SELL else instrument.ask) if instrument else None
        if price is None:
            controller.window._feedback(ui_text('m2m.stale_quote'))
            return
        quantity = min(position.quantity, position.sellable_quantity)
        if quantity <= 0:
            controller.window._feedback(ui_text('u2.exit_unavailable'))
            return
        order = ManualOrderForm(manual.scope, str(uuid4()), position.instrument_id, side, quantity, price, price, exit_lot_id=position.lot_id)
        controller.invalidate()
        self.request, self.review = order, None
        controller._send(UiAction.PREVIEW_MANUAL, order=order)

    def received(self, command, state, receipt):
        if command is None or command.action is not UiAction.PREVIEW_MANUAL or command.manual_order is None or not command.manual_order.exit_lot_id:
            return False
        preview = state.manual.preview
        if (
            command.manual_order == self.request
            and receipt is not None
            and receipt.accepted
            and preview is not None
            and preview.request_id == self.request.request_id
            and preview.scope == self.request.scope
            and receipt.reference == preview.preview_id
        ):
            self.review = preview, state.version, state.manual.capital
        else:
            self.request, self.review = None, None
        return True

    def render(self, state):
        controller = self.controller
        if self.review is None or controller.busy():
            return
        preview, version, capital = self.review
        order = self.request
        # Consume the review before entering the nested confirmation event loop.
        self.request, self.review = None, None
        if (
            not controller._ready('can_mutate')
            or state.manual.scope != preview.scope
            or state.version != version
            or selected_id(controller.window.positions) != order.exit_lot_id
            or state.manual.capital != capital
            or preview.expires_at <= datetime.now(timezone.utc)
        ):
            controller.window._feedback(ui_text('v2.state_conflict'))
            return
        if not preview.allowed:
            controller.window._feedback(' '.join(reason_text(code) for code in preview.reasons))
            return
        text = (
            ui_text('u2.exit_details').format(
                preview.instrument_id,
                ui_text('m2m.sell') if preview.side is Side.SELL else ui_text('m2m.buy'),
                quantity_text(preview),
                preview.limit_price,
                preview.bid if preview.bid is not None else ui_text('watch.unknown'),
                preview.ask if preview.ask is not None else ui_text('watch.unknown'),
                clock(preview.quote_at),
                clock(preview.expires_at),
            )
            + '\n'
            + ui_text('u2.exit_warning')
        )
        if not controller._confirm(text):
            return
        current = controller.window.state
        if (
            not controller._ready('can_mutate')
            or current.manual.preview != preview
            or current.manual.capital != capital
            or selected_id(controller.window.positions) != order.exit_lot_id
            or preview.expires_at <= datetime.now(timezone.utc)
        ):
            controller.window._feedback(ui_text('v2.state_conflict'))
            return
        confirmed = replace(
            order, quantity=preview.quantity, limit_price=preview.limit_price, stop_price=preview.stop_price, confirmed=True, preview_id=preview.preview_id
        )
        controller._send(UiAction.SUBMIT_MANUAL, order=confirmed)
