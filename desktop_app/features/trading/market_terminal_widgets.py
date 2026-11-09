"""Terminal controls and panel composition, with no data access or trading actions."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, QHeaderView, QTabWidget, QTableWidgetItem

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.market_terminal_layout import TerminalWorkspace
from desktop_app.features.trading.order_book_panel import OrderBookPanel
from desktop_app.features.trading.market_terminal_search import SymbolSearch
from quantlab.trading.domain.watch import FIXED_INDICES
from desktop_app.features.trading.market_terminal_rows import quote_values, quota_text, market_summary
from desktop_app.features.trading.market_terminal_rows import source_text, state_label
from desktop_app.features.trading.market_watch_rows import series_bars


def identify(widget, name, text):
    widget.setObjectName(name)
    widget.setAccessibleName(text)
    return widget


def button(name, text):
    return identify(QPushButton(text), name, text)


def quote_table(host, name):
    table = identify(QTableWidget(0, 6), name, ui_text('terminal.quotes'))
    table.setHorizontalHeaderLabels(
        (
            ui_text('terminal.col_code'),
            ui_text('terminal.col_name'),
            ui_text('terminal.col_price'),
            ui_text('terminal.col_change'),
            ui_text('terminal.col_percent'),
            ui_text('terminal.col_volume'),
        )
    )
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setMinimumSectionSize(36)
    table.horizontalHeader().setSortIndicatorShown(False)
    table.verticalHeader().hide()
    table.setMinimumWidth(220)
    table.itemClicked.connect(lambda item: host.select_instrument(table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)))
    table.itemActivated.connect(lambda item: host.select_instrument(table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)))
    table.horizontalHeader().sectionClicked.connect(lambda column: host.sort_quotes(table, column))
    return table


def chart_panel(host):
    center = QWidget()
    layout = QVBoxLayout(center)
    layout.setContentsMargins(2, 0, 2, 0)
    title_row = QHBoxLayout()
    host.title = identify(QLabel(), 'terminal_chart_title', ui_text('terminal.chart'))
    host.title.setTextFormat(Qt.TextFormat.PlainText)
    host.title.setMinimumWidth(0)
    host.title.setWordWrap(True)
    host.freshness = identify(QLabel(), 'terminal_freshness', ui_text('watch.state'))
    title_row.addWidget(host.title, 1)
    title_row.addWidget(host.freshness)
    layout.addLayout(title_row)
    controls = QHBoxLayout()
    host.period_buttons = {}
    for period, text in (
        ('1m', ui_text('terminal.period_1m')),
        ('5m', ui_text('terminal.period_5m')),
        ('15m', ui_text('terminal.period_15m')),
        ('1d', ui_text('terminal.period_1d')),
    ):
        item = button('watch_period_' + period, text)
        item.setCheckable(True)
        item.setProperty('terminalPeriod', True)
        item.clicked.connect(lambda checked=False, selected=period: host.select_period(selected))
        host.period_buttons[period] = item
        controls.addWidget(item)
    controls.addStretch()
    host.toggle_watch = button('terminal_toggle_watch', ui_text('terminal.add_watch'))
    host.refresh_history = button('terminal_refresh_history', ui_text('terminal.refresh_history'))
    controls.addWidget(host.toggle_watch)
    controls.addWidget(host.refresh_history)
    layout.addLayout(controls)
    identify(host.chart, 'watch_chart', ui_text('watch.chart'))
    host.chart.setMinimumSize(100, 90)
    layout.addWidget(host.chart, 1)
    errors = QHBoxLayout()
    host.history_error = identify(QLabel(), 'watch_history_error', ui_text('watch.history_error_name'))
    host.retry = button('watch_retry', ui_text('watch.retry'))
    errors.addWidget(host.history_error, 1)
    errors.addWidget(host.retry)
    layout.addLayout(errors)
    return center


def build_terminal(host, layout_store, alerts_panel, panel_factory):
    root = QVBoxLayout(host)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(4)
    search_row = QHBoxLayout()
    host.search = SymbolSearch(lambda: host._directory, host.select_instrument)
    search_row.addWidget(host.search, 1)
    host.tabs = identify(QTabWidget(), 'terminal_quote_tabs', ui_text('terminal.quotes'))
    host.table, host.index_table = quote_table(host, 'terminal_quotes'), quote_table(host, 'terminal_indices')
    host.tabs.addTab(host.table, ui_text('terminal.tab_watchlist'))
    host.tabs.addTab(host.index_table, ui_text('terminal.tab_index'))
    host.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    host.table.customContextMenuRequested.connect(host._context_menu)
    host.alerts_content = alerts_panel or QWidget()
    if alerts_panel is None:
        QVBoxLayout(host.alerts_content).addWidget(QLabel(ui_text('terminal.alerts_soon')))
    index = QWidget()
    index_layout = QVBoxLayout(index)
    index_layout.setContentsMargins(2, 0, 2, 0)
    host.index_title = button('terminal_index_title', ui_text('terminal.taiex'))
    host.index_title.clicked.connect(lambda: host.select_instrument(FIXED_INDICES[0].instrument_id))
    index_layout.addWidget(host.index_title)
    identify(host.index_chart, 'terminal_index_chart', ui_text('terminal.taiex'))
    host.index_chart.setMinimumSize(100, 90)
    host.index_chart.installEventFilter(host)
    index_layout.addWidget(host.index_chart, 1)
    host.order_book = OrderBookPanel()
    host.workspace = TerminalWorkspace(
        host,
        {
            'quotes': (ui_text('terminal.quotes'), host.tabs),
            'alerts': (ui_text('terminal.alerts'), host.alerts_content),
            'chart': (ui_text('terminal.chart'), chart_panel(host)),
            'index': (ui_text('terminal.taiex'), index),
            'orderbook': (ui_text('orderbook.title'), host.order_book),
        },
        layout_store,
        panel_factory,
    )
    search_row.addWidget(host.workspace.button)
    root.addLayout(search_row)
    root.addWidget(host.workspace.splitter, 1)
    host.status = button('terminal_status', ui_text('terminal.status'))
    host.status.setMinimumWidth(0)
    host.status.setToolTip(ui_text('terminal.diagnostics'))
    host.status.clicked.connect(host.show_diagnostics)
    host.message = identify(QLabel(), 'watch_message', ui_text('watch.message'))
    host.message.setTextFormat(Qt.TextFormat.PlainText)
    status_row = QHBoxLayout()
    status_row.addWidget(host.status, 1)
    status_row.addWidget(host.message)
    root.addLayout(status_row)
    host.message_timer = QTimer(host)
    host.message_timer.setSingleShot(True)
    host.message_timer.setInterval(5000)
    host.message_timer.timeout.connect(host.message.clear)
    host.toggle_watch.clicked.connect(host.toggle_current_watch)
    host.refresh_history.clicked.connect(lambda: host.load_series(retry=True))
    host.retry.clicked.connect(lambda: host.load_series(retry=True))


class QuoteItem(QTableWidgetItem):
    def __init__(self, text, sort_value):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        if self.sort_value is None:
            return False
        if other.sort_value is None:
            return True
        return self.sort_value < other.sort_value


def render_quote_table(host, table, instruments):
    selected = table.item(table.currentRow(), 0)
    selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
    table.setSortingEnabled(False)
    table.setRowCount(len(instruments))
    for row, instrument in enumerate(instruments):
        view = host._view(instrument.instrument_id)
        values = (instrument.code, instrument.name, view.price, view.change, view.change_percent, view.total_volume)
        for column, text in enumerate(quote_values(instrument, view)):
            item = QuoteItem(text, None if text == ui_text('watch.unknown') else values[column])
            item.setData(Qt.ItemDataRole.UserRole, instrument.instrument_id)
            item.setToolTip(text)
            if text == ui_text('watch.unknown'):
                item.setForeground(QColor('#808080'))
            elif column in (2, 3, 4):
                item.setForeground(host._colour(view))
            if column > 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, column, item)
    if table in host._sorts:
        table.sortItems(*host._sorts[table])
    for row in range(table.rowCount()):
        if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == selected_id:
            table.selectRow(row)


def render_status(host):
    health, status = host.state.market_health, host._terminal_status
    count = status.subscription_count if status else health.subscription_count
    limit = status.subscription_limit if status else health.subscription_limit
    temporary = int(bool(status.temporary_id)) if status else 0
    connection = {
        'CONNECTED': ui_text('watch.connected'),
        'DISCONNECTED': ui_text('watch.disconnected'),
        'CONNECTING': ui_text('watch.connecting'),
        'UNKNOWN': ui_text('watch.unknown'),
    }[host.state.market_connection]
    host.status.setText(
        ui_text('terminal.status_line').format(
            connection, count, limit, max(0, limit - 2 - temporary), quota_text(status.usage if status else None), market_summary(health)
        )
    )
    if host.latest_alert:
        host.status.setText(host.status.text() + ' · ' + ui_text('alert.latest').format(host.latest_alert))
    if status and (status.warning_code == 'history_quota_low' or status.history_state.paused):
        host.history_error.setText(ui_text('terminal.quota_paused'))
    if status and status.warning_code == 'kline_store_unavailable' and host._last_warning != status.warning_code:
        host.show_message(ui_text('terminal.cache_rebuilt'))
    host._last_warning = status.warning_code if status else ''


def render_chart(host, page):
    bars = series_bars(page)
    key = page.instrument_id, page.period
    previous = host._last_series
    old = previous[2] if previous is not None and previous[:2] == key else ()
    if previous != (*key, bars):
        if old and len(old) <= len(bars) <= len(old) + 1 and bars[: len(old) - 1] == old[:-1] and bars[len(old) - 1].start == old[-1].start:
            if old[-1] != bars[len(old) - 1]:
                host.chart.replace_last_bar(bars[len(old) - 1])
            if len(bars) > len(old):
                host.chart.append_bar(bars[-1])
        else:
            host.chart.set_series(bars)
        host._last_series = *key, bars
    host.chart.source_label = source_text(host._market_environment())
    host.chart.status_label = (
        ui_text('connection.failure.history_only')
        if host._history_only
        else ui_text('watch.forming')
        if page.bars and not page.bars[-1].final
        else state_label(host._view(page.instrument_id).health.freshness)
    )
    host.chart.update()
