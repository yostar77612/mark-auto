"""Paper-only read-only tabs and model-painted P&L distribution."""

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTabWidget, QStyledItemDelegate, QWidget, QVBoxLayout, QComboBox, QLabel, QTableWidget, QTableWidgetItem
from shiboken6 import isValid

import desktop_privacy as privacy
from desktop_strings import ui_text
from desktop_presentation import display_number
from desktop_theme import align_table_item, appearance, set_financial_item, up_down_colors
from .result_widgets import ResultTable
from quantlab.paper_tab_data import event_rows, position_rows, scaled_fractions, working_order, timeline_rows, TIMELINE_LIMIT

BAR_ROLE = int(Qt.ItemDataRole.UserRole) + 81
STATUS_ROLE = BAR_ROLE + 1


class PnlDelegate(QStyledItemDelegate):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        fraction = index.data(BAR_ROLE)
        if fraction is not None and not privacy.enabled(self.table):
            raw = index.data(Qt.ItemDataRole.UserRole)
            theme, convention = appearance(self.table)
            colors = up_down_colors(convention, theme=theme, context='market')
            color = QColor(colors[0 if raw[1] >= 0 else 1])
            color.setAlpha(65)
            rect = QRectF(option.rect).adjusted(3, option.rect.height() - 5, -3, -1)
            rect.setWidth(rect.width() * float(fraction))
            painter.save()
            painter.fillRect(rect, color)
            painter.restore()


class PaperTable(ResultTable):
    refreshed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resetting = False
        self.order_counts = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_rows(self, rows, columns=None, formats=None):
        rows = list(rows)
        self.resetting = True
        try:
            super().set_rows(rows, columns, formats)
            columns = columns or []
            if 'status' in columns:
                for row, record in enumerate(rows):
                    self.item(row, columns.index('status')).setData(STATUS_ROLE, record.get('status'))
            if 'pnl' in columns:
                column = columns.index('pnl')
                header = self.horizontalHeaderItem(column)
                header.setText(ui_text('paper.tabs.simulated_pnl'))
                header.setToolTip(ui_text('paper.tabs.pnl_basis'))
                self.resizeColumnToContents(column)
                self.setColumnWidth(column, min(self.columnWidth(column), 340))
                self.setProperty('pnlColumnName', 'paper_positions_pnl')
                align_table_item(header, numeric=True)
                fractions = scaled_fractions(row.get('pnl') for row in rows)
                for row, fraction in enumerate(fractions):
                    item = self.item(row, column)
                    item.setData(BAR_ROLE, fraction)
                    align_table_item(item, numeric=True)
                    set_financial_item(self, item, rows[row].get('pnl'))
            if 'position' in columns:
                for row in range(self.rowCount()):
                    # Reuse money privacy masking for position quantities.
                    privacy.item_display(self, self.item(row, columns.index('position')), 'cash')
        finally:
            self.resetting = False
        self.refreshed.emit()


def bind_paper_count(tabs, table, title):
    def refresh(*args):
        if not isValid(tabs) or not isValid(table) or table.resetting:
            return
        total = table.rowCount()
        if table.order_counts:
            active = sum(table.item(row, 4) is not None and working_order({'status': table.item(row, 4).data(STATUS_ROLE)}) for row in range(total))
            text = ui_text('paper.tabs.active_total').format(title, display_number(active), display_number(total))
        else:
            text = ui_text('tables.tab_count').format(title, display_number(total))
        tabs.setTabText(tabs.indexOf(table), text)

    for signal in (table.refreshed, table.model().rowsInserted, table.model().rowsRemoved, table.model().modelReset):
        signal.connect(refresh)
    refresh()


def build_tabs(page, layout):
    tabs = QTabWidget()
    tabs.setObjectName('paper_account_tabs')
    tabs.setAccessibleName(ui_text('paper.tabs.title'))
    tabs.tabBar().setObjectName('paper_account_tab_bar')
    tabs.tabBar().setAccessibleName(ui_text('paper.tabs.title'))
    tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
    layout.addWidget(tabs)
    for attr, name, title in (
        ('positions_table', 'paper_positions_results', ui_text('results.positions')),
        ('orders_table', 'paper_orders_results', ui_text('results.orders')),
        ('account_fills_table', 'paper_fills_results', ui_text('results.fills')),
        ('events_table', 'paper_events_results', ui_text('paper.tabs.events')),
    ):
        table = PaperTable()
        table.setObjectName(name)
        table.setAccessibleName(title)
        setattr(page, attr, table)
        tabs.addTab(table, title)
        bind_paper_count(tabs, table, title)
    delegate = PnlDelegate(page.positions_table)
    page.positions_table.horizontalHeader().setObjectName('paper_positions_pnl')
    page.positions_table.setItemDelegateForColumn(2, delegate)

    # The existing Events tab is the entry point; no new startup widgets/text.
    def activate(index):
        if tabs.widget(index) is page.events_table:
            open_timeline(page, tabs)
        timeline = getattr(page, 'timeline_table', None)
        if timeline is not None:
            timeline_index = tabs.indexOf(page.timeline_panel)
            tabs.setTabVisible(timeline_index, tabs.widget(index) is page.events_table or index == timeline_index)

    tabs.currentChanged.connect(activate)
    return tabs


def timeline_labels():
    return (
        ('', ui_text('paper.timeline.all')),
        ('intent', ui_text('paper.timeline.intent')),
        ('ack', ui_text('paper.timeline.ack')),
        ('fill', ui_text('paper.timeline.fill')),
        ('reject', ui_text('paper.timeline.reject')),
        ('reconcile', ui_text('paper.timeline.reconcile')),
        ('lock', ui_text('paper.timeline.lock')),
        ('other', ui_text('paper.timeline.other')),
    )


def open_timeline(page, tabs):
    """Add the adjacent timeline once the user first opens Events."""
    if getattr(page, 'timeline_table', None) is not None:
        return
    panel = QWidget(tabs)
    layout = QVBoxLayout(panel)
    selector = QComboBox(panel)
    selector.setObjectName('paper_timeline_filter')
    selector.setAccessibleName(ui_text('paper.timeline.filter'))
    for value, label in timeline_labels():
        selector.addItem(label, value)
    layout.addWidget(selector)
    notice = QLabel(panel)
    notice.setObjectName('paper_timeline_notice')
    notice.setWordWrap(True)
    layout.addWidget(notice)
    table = QTableWidget(0, 3, panel)
    table.setObjectName('paper_timeline_results')
    table.setAccessibleName(ui_text('paper.timeline.title'))
    table.setHorizontalHeaderLabels((ui_text('paper.timeline.time'), ui_text('paper.timeline.type'), ui_text('paper.timeline.summary')))
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(False)
    table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    layout.addWidget(table)
    QWidget.setTabOrder(selector, table)
    page.timeline_panel = panel
    page.timeline_table, page.timeline_filter, page.timeline_notice = table, selector, notice
    selector.currentIndexChanged.connect(lambda: filter_timeline(page))
    tabs.addTab(panel, ui_text('paper.timeline.title'))
    render_timeline(page)


def filter_timeline(page):
    selected = page.timeline_filter.currentData()
    table = page.timeline_table
    for index, row in enumerate(getattr(page, '_timeline_rows', [])):
        table.setRowHidden(index, bool(selected and selected != row['type']))


def render_timeline(page):
    table = getattr(page, 'timeline_table', None)
    if table is None:
        return
    rows = getattr(page, '_timeline_rows', [])
    labels = dict(timeline_labels())
    table.setRowCount(len(rows))
    for index, row in enumerate(rows):
        values = (row['time'] or ui_text('paper.timeline.unknown_time'), labels[row['type']], ui_text('paper.timeline.event').format(row['sequence']))
        for column, value in enumerate(values):
            table.setItem(index, column, QTableWidgetItem(value))
    text = ui_text('paper.timeline.truncated').format(TIMELINE_LIMIT) if getattr(page, '_timeline_truncated', False) else ''
    if not rows:
        text = ui_text('paper.timeline.empty')
    page.timeline_notice.setText(text)
    page.timeline_notice.setAccessibleName(text)
    filter_timeline(page)


def existing_journal(page):
    """Read the existing raw export only within a fixed display input bound."""
    root = getattr(page, 'root', None)
    if root is None:
        return None
    try:
        path = Path(root) / 'paper_journal_export.json'
        if path.stat().st_size > 4 * 1024 * 1024:
            return None
        with path.open(encoding='utf-8') as stream:
            text = stream.read(4 * 1024 * 1024 + 1)
        return json.loads(text) if len(text) <= 4 * 1024 * 1024 else None
    except (OSError, ValueError):
        return None


def refresh_tables(page, account, orders, fills):
    page.positions_table.set_rows(position_rows(account), ('contract_id', 'position', 'pnl'))
    page.orders_table.order_counts = True
    page.orders_table.set_rows(orders, ('order_id', 'contract_id', 'side', 'quantity', 'status'))
    page.account_fills_table.set_rows(fills, ('timestamp', 'contract_id', 'side', 'quantity', 'price', 'commission', 'tax'))
    events = getattr(page, 'events_table', None)
    if events is not None:
        journal = existing_journal(page)
        page._timeline_rows, page._timeline_truncated = timeline_rows(account, journal)
        render_timeline(page)
        rows = event_rows(account, journal)
        for row in rows:
            row['operation'] = ui_text('paper.tabs.event_operation').format(row['operation'] or ui_text('forms.metric.text_2'))
        events.set_rows(rows, ('sequence', 'operation'))
        events.setHorizontalHeaderLabels((ui_text('paper.tabs.sequence'), ui_text('paper.tabs.events')))
