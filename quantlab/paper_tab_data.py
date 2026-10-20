"""Qt-free paper presentation projections; never fetch or mutate data."""

from decimal import Decimal, InvalidOperation


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def working_order(row):
    return row.get('status') in ('accepted', 'partial', 'submitting', 'cancel_pending', 'unknown')


def account_counts(account):
    account = account or {}
    orders = account.get('orders') or {}
    return {
        'positions': len(account.get('positions') or {}),
        'orders': len(orders),
        'fills': len(account.get('fills') or {}),
        'active': sum(working_order(row) for row in orders.values()),
    }


def scaled_fractions(values):
    numbers = [number(value) for value in values]
    maximum = max((abs(value) for value in numbers if value is not None), default=Decimal(0))
    return [None if value is None else abs(value) / maximum if maximum else Decimal(0) for value in numbers]


def position_rows(account):
    """Gross simulated unrealized P&L from journaled marks, FIFO lots and fills.

    Match the entire position and require the fill's explicit multiplier. A
    missing mark, lot, price or contract match is unknown, including flat rows.
    The paper engine supports a single contract; never apply its mark across
    multiple contracts. No guessed cost basis or price is used.
    """
    account = account or {}
    positions, orders, fills = (account.get(key) or {} for key in ('positions', 'orders', 'fills'))
    mark = number(account.get('last_mark_price'))
    totals, quantities, invalid = {}, {}, set()
    for lot in account.get('lots') or []:
        fill = fills.get(lot.get('entry_fill_id')) or {}
        intent = (orders.get(fill.get('order_id')) or {}).get('intent') or {}
        contract = intent.get('contract_id')
        price, quantity, direction, multiplier = (
            number(value) for value in (lot.get('price'), lot.get('quantity'), lot.get('direction'), fill.get('multiplier'))
        )
        if mark is None or None in (price, quantity, direction, multiplier) or direction not in (-1, 1) or quantity <= 0 or multiplier <= 0:
            invalid.add(contract)
            continue
        quantities[contract] = quantities.get(contract, Decimal(0)) + quantity * direction
        totals[contract] = totals.get(contract, Decimal(0)) + (mark - price) * quantity * direction * multiplier
    return [
        {
            'contract_id': contract,
            'position': quantity,
            'pnl': totals.get(contract) if len(positions) == 1 and not invalid and quantities.get(contract) == number(quantity) else None,
        }
        for contract, quantity in positions.items()
    ]


EVENT_LIMIT = 200
EVENT_OPERATIONS = frozenset(('intent', 'risk_reject', 'ack', 'cancel', 'amend', 'fill', 'reconcile', 'restart', 'kill', 'manual_lock', 'event'))


def event_rows(account, journal=None):
    """Only structural journal metadata crosses into the audit view.

    Never copy arbitrary payloads, identities, messages, credentials or research
    records. Without supplied journal metadata show existing fill event counts.
    """
    account = account or {}
    events = journal if isinstance(journal, (list, tuple)) else account.get('journal_events') or account.get('events')
    if not isinstance(events, (list, tuple)):
        events = [{'operation': 'fill'} for _ in range(min(len(account.get('fills') or {}), EVENT_LIMIT))]
    return [
        {'sequence': index, 'operation': event.get('operation') if event.get('operation') in EVENT_OPERATIONS else None}
        for index, event in enumerate(events[-EVENT_LIMIT:], start=max(1, len(events) - EVENT_LIMIT + 1))
        if isinstance(event, dict)
    ]
