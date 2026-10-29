"""Pure shared reconciliation display cells; no Qt, IO or reconciliation decisions."""

from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import ReconciliationView
from desktop_app.features.trading.labels import state_label


def reconciliation_cells(item: ReconciliationView) -> tuple[str, ...]:
    unit = ui_text('v2.shares' if item.unit.value == 'SHARE' else 'v2.contracts')

    def quantity(value: int | None) -> str:
        return ui_text('v2.reconciliation_quantity_unknown') if value is None else f'{value:+,} {unit}'

    delta = None if item.local_quantity is None or item.broker_quantity is None else item.broker_quantity - item.local_quantity
    status = state_label(item.status)
    if status == item.status:
        status = ui_text('v2.reconciliation_pending')
    return (
        item.account_ref,
        item.instrument_id,
        ui_text('v2.reconciliation_position' if item.kind == 'POSITION' else 'v2.reconciliation_order'),
        quantity(item.local_quantity),
        quantity(item.broker_quantity),
        quantity(delta),
        quantity(item.sellable_quantity),
        item.broker_order_ref or ui_text('v2.reconciliation_not_applicable'),
        status,
        item.as_of,
    )
