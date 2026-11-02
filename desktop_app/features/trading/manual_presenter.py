"""Render server-owned manual simulation facts without calculating authority."""

from zoneinfo import ZoneInfo
from decimal import Decimal

from PySide6.QtCore import QSignalBlocker

from desktop_app.features.trading.widgets import selected_id
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import ManualPurpose
from quantlab.trading.domain.models import Environment, Market, QuantityUnit, Side


def money(value):
    return ui_text('watch.unknown') if value is None else ui_text('m2m.money').format(f'{value:,.2f}')


def clock(value):
    return value.astimezone(ZoneInfo('Asia/Taipei')).strftime('%m/%d %H:%M:%S') if value and value.tzinfo else ui_text('watch.unknown')


def quantity_text(preview):
    if preview.quantity_unit is QuantityUnit.SHARE:
        quantity = f'{Decimal(preview.quantity) / preview.lot_size:,.3f}'.rstrip('0').rstrip('.') + ' ' + ui_text('m2t.lots')
    elif preview.quantity_unit is QuantityUnit.CONTRACT:
        quantity = f'{preview.quantity:,} ' + ui_text('v2.contracts')
    else:
        quantity = ui_text('watch.unknown')
    return quantity


def preview_text(preview):
    values = ui_text('m2m.preview_details').format(
        preview.instrument_id,
        ui_text('m2m.buy') if preview.side is Side.BUY else ui_text('m2m.sell'),
        quantity_text(preview),
        preview.limit_price,
        preview.stop_price,
        money(preview.total_cash),
        money(preview.fee_cash),
        money(preview.risk_cash),
        money(preview.available_cash),
        clock(preview.quote_at),
        clock(preview.expires_at),
    )
    return (
        values
        + '\n'
        + ui_text('m2m.sources').format(
            ui_text('m2m.virtual_source') if preview.funds_source == 'APP_VIRTUAL_SIMULATION' else ui_text('watch.unknown'),
            ui_text('m2m.cost_estimate') if preview.cost_source else ui_text('watch.unknown'),
        )
        + '\n'
        + ui_text('u2.quotes').format(
            preview.bid if preview.bid is not None else ui_text('watch.unknown'),
            preview.ask if preview.ask is not None else ui_text('watch.unknown'),
            clock(preview.quote_at),
        )
    )


def reason_text(code):
    reasons = {
        'manual_book_not_enabled': ui_text('m2m.need_book'),
        'manual_confirmation_required': ui_text('m2m.need_confirmation'),
        'manual_account_observation_required': ui_text('m2m.need_observation'),
        'manual_test_required': ui_text('m2m.need_test'),
        'manual_futures_test_required': ui_text('m2m.need_futures_test'),
        'manual_test_pending': ui_text('m2m.pending'),
        'manual_unprotected_position': ui_text('m2m.unprotected'),
        'manual_restarted': ui_text('m2m.restarted'),
        'manual_day_baseline_required': ui_text('m2m.need_day_baseline'),
        'manual_quantity_amend_unsupported': ui_text('m2m.amend_hint'),
        'manual_not_submitted': ui_text('m2m.not_submitted'),
        'manual_allocation_exceeds_settings': ui_text('m2m.allocation_exceeds_settings'),
        'production_orders_disabled': ui_text('m2t.orders_disabled'),
        'insufficient_funds': ui_text('m2m.insufficient_funds'),
        'risk_rejected': ui_text('m2m.risk_rejected'),
        'risk_resized': ui_text('m2m.risk_resized'),
        'stale_quote': ui_text('m2m.stale_quote'),
        'session_closed': ui_text('m2m.session_closed'),
        'calendar_missing': ui_text('m2m.calendar_missing'),
        'instrument_unresolved': ui_text('m2m.instrument_unknown'),
        'reconciliation_required': ui_text('m2m.need_observation'),
        'outcome_unknown': ui_text('m2m.pending'),
        'state_conflict': ui_text('v2.state_conflict'),
        'ownership_conflict': ui_text('m2m.ownership_conflict'),
        'broker_rejected': ui_text('m2m.broker_rejected'),
        'journal_failed': ui_text('m2m.journal_failed'),
        'price_deviation': ui_text('u2.price_deviation'),
        'exit_unavailable': ui_text('u2.exit_unavailable'),
        'exit_already_pending': ui_text('u2.exit_unavailable'),
    }
    return reasons.get(code, ui_text('m2m.not_ready'))


def _role(widget, role):
    if widget.property('role') != role:
        widget.setProperty('role', role)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def render_manual(controller, state):
    form, manual = controller.form, state.manual
    simulation = state.environment is Environment.BROKER_SIMULATION
    form.setVisible(simulation)
    _role(controller.window.reconcile_button, 'secondary' if simulation else 'primary')
    _role(form.submit, 'primary' if simulation else 'secondary')
    scope_changed = controller.scope != manual.scope
    if scope_changed:
        controller.scope = manual.scope
        controller.invalidate()
        form.capital.setText('' if manual.capital is None and manual.suggested_capital is None else str(manual.capital or manual.suggested_capital))
        form.price.clear()
        form.stop.clear()
    wanted = form.instrument.currentData()
    instruments = tuple((item.instrument_id, item.label) for item in manual.instruments)
    if instruments != controller.instruments:
        controller.instruments = instruments
        with QSignalBlocker(form.instrument):
            form.instrument.clear()
            for identity, caption in instruments:
                form.instrument.addItem(caption, identity)
            form.instrument.setCurrentIndex(max(0, form.instrument.findData(wanted)))
    instrument = next((item for item in manual.instruments if item.instrument_id == form.instrument.currentData()), None)
    if instrument:
        form.quantity.setSuffix(' ' + (ui_text('m2t.lots') if instrument.quantity_unit is QuantityUnit.SHARE else ui_text('v2.contracts')))
        form.contract_details.setText(
            ui_text('m2m.contract_details').format(
                instrument.instrument_id,
                instrument.lower_limit if instrument.lower_limit is not None else ui_text('watch.unknown'),
                instrument.upper_limit if instrument.upper_limit is not None else ui_text('watch.unknown'),
                clock(instrument.quote_at),
            )
        )
    else:
        form.contract_details.setText(ui_text('m2m.not_ready'))
    stock_sell = instrument is not None and instrument.market is Market.STOCK and form.side.currentData() == Side.SELL
    if stock_sell:
        form.contract_details.setText(form.contract_details.text() + '\n' + ui_text('m2m.stock_exit_hint'))
    unresolved = controller.unresolved(state)
    status = (
        ui_text('m2m.pending')
        if unresolved
        else ui_text('m2m.book').format(
            state.account_ref, money(manual.capital), money(manual.available_cash), ui_text('m2m.halted') if manual.halted else ui_text('m2m.enabled')
        )
    )
    reasons = tuple(dict.fromkeys(reason_text(code) for code in manual.reasons))
    tests = {
        'UNTESTED': ui_text('m2m.test_untested'),
        'PENDING': ui_text('m2m.test_pending'),
        'PASSED': ui_text('m2m.test_passed'),
        'FAILED': ui_text('m2m.test_failed'),
        'UNKNOWN': ui_text('m2m.test_unknown'),
    }
    test = tests.get(manual.test_status, ui_text('m2m.test_unknown'))
    if manual.test_reason:
        test += ' ' + reason_text(manual.test_reason)
    form.status.setText(status + ('\n' + ' '.join(reasons) if reasons else '') + '\n' + test)
    identities = tuple(
        identity
        for identity, scope in controller.intents.pending.items()
        if (scope.context_id, scope.account_ref, scope.environment) == (state.context_id, state.account_ref, state.environment)
    )
    form.status.setToolTip(ui_text('m2m.pending_identity').format(', '.join(identities)) if identities else '')
    ready = simulation and controller.matches(state) and not controller.busy() and not unresolved
    if manual.confirmed:
        form.capital.setText('' if manual.capital is None else str(manual.capital))
    form.capital.setEnabled(ready and not manual.confirmed)
    next_text = (
        ui_text('m2t.open_strategy')
        if state.environment is Environment.LOCAL
        else ui_text('m2m.open_manual')
        if controller.matches(state)
        else ui_text('m2m.open_connection')
    )
    for empty in (controller.window.positions_empty, controller.window.orders_empty):
        empty.next.setText(next_text)
        empty.next.setAccessibleName(next_text)
    for widget in (form.instrument, form.side, form.quantity, form.price, form.stop):
        widget.setEnabled(ready)
    form.prepare.setEnabled(ready and manual.can_prepare and not manual.confirmed)
    form.test_order.setEnabled(ready and manual.can_test)
    form.preview_button.setEnabled(ready and manual.can_preview and instrument is not None and instrument.tradable and not stock_sell)
    preview = controller.preview(state)
    form.preview.setText(
        preview_text(preview) + ('\n' + ' '.join(reason_text(code) for code in preview.reasons) if preview.reasons else '')
        if preview
        else ui_text('m2m.no_preview')
    )
    can_submit = manual.can_test if preview and preview.purpose is ManualPurpose.DIAGNOSTIC_TMF else manual.can_submit
    form.submit.setEnabled(ready and can_submit and preview is not None and preview.allowed)
    form.preview.setToolTip(ui_text('m2m.source_details').format(preview.funds_source, preview.cost_source) if preview else '')
    controller.cancel.setEnabled(ready and manual.can_mutate and controller.selected_order() is not None)
    controller.amend.setEnabled(controller.cancel.isEnabled())
    if simulation:
        position_id = selected_id(controller.window.positions)
        owned = any(
            position.lot_id == position_id and position.account_ref == state.account_ref and position.strategy_id == manual.book_id
            for position in state.positions
        )
        can_exit = ready and manual.can_mutate and manual.confirmed and manual.capital is not None and owned
        controller.window.flatten_button.setEnabled(can_exit)
        controller.window.flatten_button.setToolTip(ui_text('m2m.exit_source' if can_exit else 'm2m.not_ready'))
        controller.window.resume_button.setText(ui_text('m2m.resume'))
        controller.window.resume_button.setEnabled(ready and manual.confirmed and manual.halted and manual.capital is not None)
    else:
        controller.window.resume_button.setText(ui_text('v2.resume'))
