"""Offline amend action carried by the existing paper cancel worker envelope."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from .core import ValidationError, canonical_json
from .paper import PaperBroker


def execute(payload, root, *, prepare, finish):
    """Verify the pre-session snapshot before reconciling constructor's restart.

    No pre-existing reconciliation latch is cleared by this action. The worker
    explicitly acknowledges its synthetic amend; interruption leaves pending_amend
    for investigation and a simulated event before explicit reconciliation.
    """
    if payload.get('mode') != 'paper' or payload.get('reconcile_confirmed') is not True:
        raise ValidationError('paper amend requires explicit confirmation')
    if type(payload.get('price')) is not str or 'quantity' in payload:
        raise ValidationError('paper amend requires a price string and unchanged quantity')
    try:
        price = Decimal(payload['price'])
    except InvalidOperation:
        raise ValidationError('invalid amend price') from None
    before = PaperBroker.read_snapshot(root / 'paper.sqlite3')
    if before['reconciliation_required'] or before['kill_switch']:
        raise ValidationError('paper amend requires a reconciled unlocked account')
    if canonical_json(before) != canonical_json(payload.get('snapshot')):
        raise ValidationError('paper amend snapshot changed')
    if any(o.get('pending_amend') for o in before['orders'].values()):
        raise ValidationError('pending amend requires simulated acknowledgement')
    broker = prepare()
    broker.reconcile(before)
    now = datetime.fromisoformat(payload['now'].replace('Z', '+00:00'))
    order = broker.amend(payload['order_id'], price=price, amend_key=payload['amend_key'], quote=payload['quote'], now=now)
    broker.apply_event(
        dict(
            event_id='amend-ack:' + payload['amend_key'],
            order_id=payload['order_id'],
            sequence=order['sequence'] + 1,
            type='amend',
            timestamp=now,
            amend_key=payload['amend_key'],
        )
    )
    return finish(broker)
