from quantlab.core import content_hash
from desktop_strings import ui_text
from datetime import datetime
from decimal import Decimal


def result_snapshot_lines(result, bars, selected):
    """Read the final actual open-lot snapshot, never derive a fill from a signal.

    Range endpoints preserve the existing whole-position conservative policy:
    every original-entry lot can trigger; the most adverse triggered level
    wins (with existing gap handling). An average-price stop is not that rule.
    No line is projected back through historical candles or beyond this event.
    """
    from desktop_charts import ReferenceLine
    from decimal import Context, InvalidOperation, ROUND_HALF_EVEN, localcontext

    if not result.equity:
        return ()
    row = result.equity[-1]
    lots = result.metrics.get('open_lots', ())
    position = result.metrics.get('open_position')
    if not lots or type(position) is not int or not position:
        return ()
    if row.get('contract_id') != selected or row.get('position') != position:
        return ()

    try:
        as_of = _parse_snapshot_timestamp(row['timestamp'])
        indices = [i for i, bar in enumerate(bars) if bar.contract_id == selected and bar.end == as_of]
        if len(indices) != 1:
            return ()  # No nearest-time or date-only guess.
        side = 1 if position > 0 else -1
        fills = {fill.fill_id: fill for fill in result.fills}
        if len(fills) != len(result.fills) or any(fill.timestamp > as_of for fill in result.fills):
            return ()
        opening = {fid: fill for fid, fill in fills.items() if fill.reason in ('target_open', 'roll_open')}
        remaining = {fid: fill.quantity for fid, fill in opening.items()}
        configuration = result.manifest['config']
        configured = {content_hash(event): event for event in configuration['settlement_events']}
        applied = _validate_snapshot_settlements(result, configured, as_of)
        if applied is None:
            return ()
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            if not _reconcile_snapshot_ledger(result, opening, fills, applied, remaining, as_of):
                return ()
            values = _collect_snapshot_lots(lots, selected, side, position, opening, remaining, configured, applied, configuration, as_of)
            if values is None:
                return ()
            entries, bases, quantities = values
            return _build_snapshot_lines(result, entries, bases, quantities, position, side, indices[0], as_of, ReferenceLine)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return ()  # Legacy/incomplete snapshots do not invent reference prices.


def _parse_snapshot_timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value


def _validate_snapshot_settlements(result, configured, as_of):
    applied = {}
    available = {(_parse_snapshot_timestamp(event['timestamp']), event['contract_id']) for event in result.equity}
    for settlement in result.metrics['settlements']:
        event = settlement['event']
        event_id = content_hash(event)
        if (
            event_id not in configured
            or settlement['event_id'] != event_id
            or event_id in applied
            or settlement['kind'] != event.get('kind', 'daily')
            or _parse_snapshot_timestamp(event['timestamp']) > as_of
            or (_parse_snapshot_timestamp(event['timestamp']), event['contract_id']) not in available
        ):
            return None
        applied[event_id] = event
    return applied


def _reconcile_snapshot_ledger(result, opening, fills, applied, remaining, as_of):
    exit_quantities = {}
    # Reconcile full opening quantities against every closed FIFO match.
    # Several residual fragments may legitimately refer to one opening fill.
    for match in result.ledger:
        fill = opening.get(match['entry_fill_id'])
        quantity = match['quantity']
        if (
            fill is None
            or type(quantity) is not int
            or quantity <= 0
            or match['contract_id'] != fill.contract_id
            or match['side'] != ('long' if fill.side == 'buy' else 'short')
            or Decimal(str(match['entry_price'])) != fill.price
            or _parse_snapshot_timestamp(match['entry_timestamp']) != fill.timestamp
            or not fill.timestamp <= _parse_snapshot_timestamp(match['exit_timestamp']) <= as_of
        ):
            return False
        exit_id = match['exit_fill_id']
        if exit_id is not None:
            exit_fill = fills.get(exit_id)
            if (
                exit_fill is None
                or exit_id in opening
                or exit_fill.contract_id != fill.contract_id
                or exit_fill.side == fill.side
                or exit_fill.timestamp != _parse_snapshot_timestamp(match['exit_timestamp'])
                or exit_fill.price != Decimal(str(match['exit_price']))
            ):
                return False
            exit_quantities[exit_id] = exit_quantities.get(exit_id, 0) + quantity
        else:
            event = applied.get(match['exit_event_id'])
            if (
                event is None
                or event.get('kind') != 'final'
                or match['exit_event_type'] != 'final_settlement'
                or event['contract_id'] != fill.contract_id
                or _parse_snapshot_timestamp(event['timestamp']) != _parse_snapshot_timestamp(match['exit_timestamp'])
                or Decimal(str(event['price'])) != Decimal(str(match['exit_price']))
            ):
                return False
        remaining[fill.fill_id] -= quantity
        if remaining[fill.fill_id] < 0:
            return False
    if any(exit_quantities.get(fid, 0) != fill.quantity for fid, fill in fills.items() if fid not in opening):
        return False
    return True


def _collect_snapshot_lots(lots, selected, side, position, opening, remaining, configured, applied, configuration, as_of):
    expected = {fid: quantity for fid, quantity in remaining.items() if quantity}
    entries, bases, quantities, observed = [], [], [], {}
    for lot in lots:
        quantity = lot['quantity']
        entry, basis = Decimal(str(lot['price'])), Decimal(str(lot['basis_price']))
        if type(quantity) is not int or quantity <= 0 or lot['side'] != side or lot['contract_id'] != selected:
            return None
        if not entry.is_finite() or not basis.is_finite() or min(entry, basis) <= 0:
            return None
        fill = opening.get(lot['fill_id'])
        if (
            fill is None
            or fill.contract_id != selected
            or fill.price != entry
            or fill.side != ('buy' if side > 0 else 'sell')
            or quantity > fill.quantity
            or _parse_snapshot_timestamp(lot['timestamp']) != fill.timestamp
            or fill.timestamp > as_of
        ):
            return None
        observed[fill.fill_id] = observed.get(fill.fill_id, 0) + quantity
        expected_basis = entry
        # Settlement at the opening timestamp belongs to the prior bar,
        # before this next-open fill, so the boundary is strictly greater.
        events = sorted(
            (
                event
                for event in configured.values()
                if event['contract_id'] == selected and fill.timestamp < _parse_snapshot_timestamp(event['timestamp']) <= as_of
            ),
            key=lambda event: _parse_snapshot_timestamp(event['timestamp']),
        )
        for event in events:
            if content_hash(event) not in applied or event.get('kind', 'daily') != 'daily' or configuration['settlement_mode'] != 'daily_mtm':
                return None
            expected_basis = Decimal(str(event['price']))
        if basis != expected_basis:
            return None
        entries.append(entry)
        bases.append(basis)
        quantities.append(quantity)
    if observed != expected or sum(quantities) != abs(position):
        return None
    return entries, bases, quantities


def _build_snapshot_lines(result, entries, bases, quantities, position, side, index, as_of, reference_line):
    lines = [
        reference_line(
            ui_text('ui.result_snapshot_lines.average_fill_price'), sum((p * q for p, q in zip(entries, quantities)), Decimal(0)) / abs(position), index, as_of
        ),
        reference_line(
            ui_text('ui.result_snapshot_lines.mtm_basis'), sum((p * q for p, q in zip(bases, quantities)), Decimal(0)) / abs(position), index, as_of
        ),
    ]
    if result.manifest.get('protective_scope') == 'whole position at most adverse triggered original-entry lot level':
        parameters = result.manifest['strategy']['parameters']
        for key, label, direction in (
            ('stop_ticks', ui_text('ui.result_snapshot_lines.stop_loss'), -side),
            ('target_ticks', ui_text('ui.result_snapshot_lines.take_profit'), side),
        ):
            if key not in parameters:
                continue
            offset = parameters[key]
            if type(offset) is not int or offset <= 0:
                return ()
            levels = [price + direction * offset for price in entries]
            lower, upper = min(levels), max(levels)
            lines.append(reference_line(label + (ui_text('ui.result_snapshot_lines.lower_bound') if lower != upper else ''), lower, index, as_of))
            if lower != upper:
                lines.append(reference_line(ui_text('ui.result_snapshot_lines.upper_bound').format(label), upper, index, as_of))
    return tuple(lines)
