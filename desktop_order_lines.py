"""Paper snapshot projection and gesture intents; no execution objects or I/O."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext, Context

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen

from desktop_strings import ui_text


def tick_price(pixel, *, top, bottom, low, high, tick):
    """Qt coordinates cross into Decimal once, before all price arithmetic."""
    if not all(isinstance(v, Decimal) and v.is_finite() for v in (low, high, tick)) or tick <= 0 or high <= low:
        raise ValueError(ui_text('orders.invalid_snapshot'))
    with localcontext(Context(prec=34)):
        ratio = (Decimal(str(bottom)) - Decimal(str(pixel))) / (Decimal(str(bottom)) - Decimal(str(top)))
        price = ((low + ratio * (high - low)) / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
    if price <= 0:
        raise ValueError(ui_text('orders.invalid_snapshot'))
    return price


class PaperOrderChartMixin:
    """Chart adapter for the read-only snapshot projection."""

    def set_paper_snapshot(self, snapshot, *, mode='paper', tick=Decimal('1'), request=None):
        if self.trace is not None:
            mode = None
        self.paper_orders.set_snapshot(snapshot, mode=mode, tick=tick, request=request)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.paper_orders.release(event.position(), self.price_rect)
        self._drag = None
        self.update()
        event.accept()


class PaperOrderLines:
    def __init__(self):
        self.snapshot = None
        self.mode = None
        self.tick = Decimal('1')
        self.request = None
        self.drag = None
        self.hits = ()
        self.scale = None
        self.notice = ''

    def set_snapshot(self, snapshot, *, mode, tick=Decimal('1'), request=None):
        self.drag, self.hits, self.notice = None, (), ''
        self.snapshot, self.mode, self.request = None, None, None
        if mode != 'paper':
            return
        if type(snapshot) is not dict or snapshot.get('verification') != 'synthetic_paper_only' or type(snapshot.get('orders')) is not dict:
            raise ValueError(ui_text('orders.invalid_snapshot'))
        if not isinstance(tick, Decimal) or not tick.is_finite() or tick <= 0:
            raise ValueError(ui_text('orders.invalid_snapshot'))
        for oid, order in snapshot['orders'].items():
            try:
                if not isinstance(oid, str) or type(order) is not dict:
                    raise ValueError
                if order.get('status') not in ('accepted', 'partial'):
                    continue
                intent = order['intent']
                if intent['order_type'] != 'limit':
                    continue
                if (
                    type(intent['quantity']) is not int
                    or type(order['filled_quantity']) is not int
                    or type(intent['limit_price']) is not str
                    or intent['side'] not in ('buy', 'sell')
                    or not isinstance(intent['contract_id'], str)
                ):
                    raise ValueError
                price = Decimal(intent['limit_price'])
                if not price.is_finite() or price <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError, InvalidOperation):
                raise ValueError(ui_text('orders.invalid_snapshot')) from None
        self.snapshot, self.mode, self.tick, self.request = deepcopy(snapshot), mode, tick, request

    def lines(self, contract):
        if not self.snapshot or self.mode != 'paper' or not self.snapshot.get('account_id'):
            return ()
        result = []
        for oid, order in self.snapshot['orders'].items():
            intent = order.get('intent', {})
            if order.get('status') not in ('accepted', 'partial') or intent.get('contract_id') != contract or intent.get('order_type') != 'limit':
                continue
            remaining = intent['quantity'] - order['filled_quantity']
            price = Decimal(intent['limit_price'])
            if remaining > 0 and price.is_finite() and price > 0:
                result.append((oid, intent['side'], remaining, price))
        return tuple(result)

    def price_bounds(self, chart, visible, start, end, references, marker_index, low, high):
        orders = self.lines(visible[0].contract_id)
        if orders:
            # Price arithmetic for amend gestures never passes through float.
            values = [v for b in visible for v in (b.low, b.high)]
            values.extend(Decimal(str(v)) for seq in chart.overlays.values() for v in seq[start:end] if v is not None)
            values.extend(line.price for line in references)
            values.extend(m.price for i in range(start, end) for m in marker_index.get(i, ()) if m.kind == 'fill' and chart.layer_visibility['fill'])
            values.extend(row[3] for row in orders)
            values = [value if isinstance(value, Decimal) else Decimal(str(value)) for value in values]
            low, high = min(values), max(values)
            pad = max((high - low) * Decimal('0.06'), Decimal('0.5'))
            low, high = low - pad, high + pad
        return low, high

    def paint(self, painter, rect, contract, y, low, high):
        self.scale = (Decimal(str(low)), Decimal(str(high)))
        hits = []
        painter.save()
        painter.setClipRect(rect)
        for oid, side, quantity, price in self.lines(contract):
            yy = y(price)
            if not rect.top() <= yy <= rect.bottom():
                continue
            hits.append((oid, yy))
            painter.setPen(QPen(QColor('#64d9df'), 2, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), yy), QPointF(rect.right(), yy))
            label = ui_text('orders.line').format(ui_text('orders.buy') if side == 'buy' else ui_text('orders.sell'), quantity, price)
            painter.drawText(QPointF(rect.left() + 6, yy - 5), label)
        painter.restore()
        self.hits = tuple(hits)

    def press(self, position, rect):
        if not self.snapshot or not self.request or not rect.contains(position):
            return False
        if self.snapshot.get('kill_switch') or self.snapshot.get('reconciliation_required') or self.snapshot.get('consecutive_loss_halt'):
            return False
        for oid, yy in self.hits:
            if abs(position.y() - yy) <= 6:
                self.drag = (oid, self.scale)
                return True
        return False

    def release(self, position, rect):
        drag, self.drag = self.drag, None
        if drag is None:
            return False
        if rect.contains(position):
            try:
                oid, (low, high) = drag
                price = tick_price(position.y(), top=rect.top(), bottom=rect.bottom(), low=low, high=high, tick=self.tick)
                if price != Decimal(self.snapshot['orders'][oid]['intent']['limit_price']):
                    self.request(oid, price)
                    self.notice = ui_text('orders.pending')
            except Exception:
                self.notice = ui_text('orders.failed')
        return True
