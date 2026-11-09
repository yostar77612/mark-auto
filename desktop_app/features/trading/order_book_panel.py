"""Five-level quote ladder and trade tape; renders a view, never reaches data or orders."""

from decimal import Decimal
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QLabel, QProgressBar, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text

_TAIPEI = ZoneInfo('Asia/Taipei')
_SIDE_KEYS = {'BUY': 'orderbook.side_buy', 'SELL': 'orderbook.side_sell', 'NONE': 'orderbook.side_none'}


def price_text(value: Decimal) -> str:
    digits = 2 if value < Decimal('50') else 1 if value < Decimal('500') else 0
    return format(value, f'.{digits}f')


def clock_text(moment) -> str:
    return moment.astimezone(_TAIPEI).strftime('%H:%M:%S')


def ladder_rows(view) -> list[tuple[str, str, str, str]]:
    """Ten rows top to bottom: asks 5..1 then bids 1..5, as (bid volume, price, ask volume, kind)."""
    book = view.bidask
    if book is None:
        return []
    rows = [('', price_text(book.ask_prices[level]), str(book.ask_volumes[level]), 'ask') for level in range(4, -1, -1)]
    rows += [(str(book.bid_volumes[level]), price_text(book.bid_prices[level]), '', 'bid') for level in range(5)]
    return rows


def side_ratio_text(view) -> str:
    decided = view.buy_volume + view.sell_volume
    if decided == 0:
        return ''
    buy = Decimal(view.buy_volume) * 100 / Decimal(decided)
    return ui_text('orderbook.side_ratio').format(f'{buy:.0f}', f'{Decimal(100) - buy:.0f}')


def _table(name, headers):
    table = QTableWidget(0, len(headers))
    table.setObjectName(name)
    table.setAccessibleName(name)
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setMinimumSectionSize(30)
    table.verticalHeader().hide()
    return table


def _cell(text, colour=None, align_right=True):
    item = QTableWidgetItem(text)
    item.setTextAlignment((Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignCenter) | Qt.AlignmentFlag.AlignVCenter)
    if colour is not None:
        item.setForeground(colour)
    return item


class OrderBookPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('terminal_order_book')
        self.setAccessibleName(ui_text('orderbook.title'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        self.notice = QLabel(ui_text('orderbook.offline'))
        self.notice.setObjectName('order_book_notice')
        self.notice.setAccessibleName(ui_text('orderbook.title'))
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.notice)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.ladder = _table('order_book_ladder', (ui_text('orderbook.col_bid_volume'), ui_text('orderbook.col_price'), ui_text('orderbook.col_ask_volume')))
        self.ladder.setAccessibleName(ui_text('orderbook.ladder'))
        self.ladder.verticalHeader().setDefaultSectionSize(22)
        self.ladder.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ladder.setMinimumHeight(10 * 22 + 30)
        self.balance = QProgressBar()
        self.balance.setObjectName('order_book_balance')
        self.balance.setAccessibleName(ui_text('orderbook.ladder'))
        self.balance.setRange(0, 100)
        self.balance.setTextVisible(False)
        self.balance.setFixedHeight(8)
        self.totals = QLabel()
        self.totals.setObjectName('order_book_totals')
        self.totals.setAccessibleName(ui_text('orderbook.ladder'))
        self.totals.setTextFormat(Qt.TextFormat.PlainText)
        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.addWidget(self.ladder, 1)
        upper_layout.addWidget(self.balance)
        upper_layout.addWidget(self.totals)
        self.tape = _table(
            'order_book_tape',
            (ui_text('orderbook.col_time'), ui_text('orderbook.col_price'), ui_text('orderbook.col_volume'), ui_text('orderbook.col_side')),
        )
        self.tape.setAccessibleName(ui_text('orderbook.tape'))
        self.tape_summary = QLabel()
        self.tape_summary.setObjectName('order_book_tape_summary')
        self.tape_summary.setAccessibleName(ui_text('orderbook.tape'))
        self.tape_summary.setWordWrap(True)
        self.tape_summary.setTextFormat(Qt.TextFormat.PlainText)
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addWidget(self.tape, 1)
        lower_layout.addWidget(self.tape_summary)
        splitter.addWidget(upper)
        splitter.addWidget(lower)
        layout.addWidget(splitter, 1)
        self.setMinimumWidth(180)

    def clear(self, notice: str) -> None:
        self.notice.setText(notice)
        self.notice.show()
        self.ladder.setRowCount(0)
        self.tape.setRowCount(0)
        self.totals.setText('')
        self.tape_summary.setText('')
        self.balance.setValue(50)

    def render_view(self, view, up: str, down: str) -> None:
        if not view.supported:
            self.clear(ui_text('orderbook.no_index'))
            return
        buy, sell = QColor(up), QColor(down)
        rows = ladder_rows(view)
        if rows:
            self.notice.hide()
        else:
            self.notice.setText(ui_text('orderbook.limited') if view.bidask_limited else ui_text('orderbook.waiting'))
            self.notice.show()
        self.ladder.setRowCount(len(rows))
        for row, (bid_volume, price, ask_volume, kind) in enumerate(rows):
            colour = sell if kind == 'ask' else buy
            self.ladder.setItem(row, 0, _cell(bid_volume, buy))
            self.ladder.setItem(row, 1, _cell(price, colour, align_right=False))
            self.ladder.setItem(row, 2, _cell(ask_volume, sell))
        book = view.bidask
        if book is not None:
            total = book.total_bid_volume + book.total_ask_volume
            self.balance.setValue(round(book.total_bid_volume * 100 / total) if total else 50)
            self.totals.setText(ui_text('orderbook.totals').format(book.total_bid_volume, book.total_ask_volume))
        else:
            self.balance.setValue(50)
            self.totals.setText('')
        self.tape.setRowCount(len(view.tape))
        for row, entry in enumerate(view.tape):
            colour = buy if entry.side == 'BUY' else sell if entry.side == 'SELL' else None
            self.tape.setItem(row, 0, _cell(clock_text(entry.source_at), align_right=False))
            self.tape.setItem(row, 1, _cell(price_text(entry.price), colour))
            self.tape.setItem(row, 2, _cell(str(entry.volume), colour))
            self.tape.setItem(row, 3, _cell(ui_text(_SIDE_KEYS[entry.side]), colour, align_right=False))
        if view.since is None:
            self.tape_summary.setText(ui_text('orderbook.no_ticks'))
        else:
            self.tape_summary.setText(' · '.join(part for part in (ui_text('orderbook.since').format(clock_text(view.since)), side_ratio_text(view)) if part))
