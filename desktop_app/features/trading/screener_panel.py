"""The stock screener list that sits beside the quote tabs: surge, breakout and downloaded K-lines. Read-only."""

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from desktop_app.features.trading.market_terminal_rows import number, price_number
from desktop_app.features.trading.market_watch import PendingRequests, _Result, start_request
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.screener_contracts import ScreenerQuery

REFRESH_MS = 5000
_TAIPEI = ZoneInfo('Asia/Taipei')
_STOCK = SimpleNamespace(exchange='TSE')  # tick-size digits of an ordinary share, as the quote tables show it
LISTS = ('SURGE', 'BREAKOUT', 'DOWNLOADED')
PATTERNS = ('ALL', 'RED', 'BLACK')
_COLUMNS = {
    'SURGE': (
        'terminal.col_code',
        'terminal.col_name',
        'terminal.col_price',
        'terminal.col_percent',
        'screen.col_ratio',
        'screen.col_pattern',
        'screen.col_kline',
    ),
    'BREAKOUT': (
        'terminal.col_code',
        'terminal.col_name',
        'terminal.col_price',
        'terminal.col_percent',
        'screen.col_breakout',
        'screen.col_vol_ratio',
        'screen.col_kline',
    ),
    'DOWNLOADED': ('terminal.col_code', 'terminal.col_name', 'screen.col_first', 'screen.col_last', 'screen.col_updated'),
}
_PATTERN_TEXT = {'SURGE_RED': 'screen.cond_surge_red', 'SURGE_BLACK': 'screen.cond_surge_black'}
_STATE_NOTES = {'OFFLINE': 'screen.offline', 'EMPTY': 'screen.empty', 'WARMUP': 'screen.warmup', 'STALE': 'screen.stale', 'CLOSED': 'sector.closed'}


def list_name(list_id):
    return ui_text({'SURGE': 'screen.list_surge', 'BREAKOUT': 'screen.list_breakout', 'DOWNLOADED': 'screen.list_downloaded'}[list_id])


def _day_text(moment):
    return '' if moment is None else moment.astimezone(_TAIPEI).strftime('%Y-%m-%d')


def _kline_cell(state):
    key = {'YEAR': 'year', 'DOWNLOADING': 'downloading', 'FAILED': 'failed'}.get(state)
    return ('', '') if key is None else (ui_text('screen.kline_' + key), ui_text('screen.kline_' + key + '_tip'))


class ScreenerPanel(QWidget):
    """The host supplies the facade and the chart/watchlist actions; this panel never touches an order control."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host, self.list_id, self.pattern = host, 'SURGE', 'ALL'
        self.on_list_changed = lambda: None  # the host retitles the tab
        self._requests, self._inflight, self._again, self._serial = PendingRequests(), 0, False, 0
        self._menu = None
        self.destroyed.connect(self._requests.cancel)
        self.setObjectName('terminal_screener_panel')
        self.setAccessibleName(ui_text('screen.panel_name'))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self.filter_row = QWidget()
        filters = QHBoxLayout(self.filter_row)
        filters.setContentsMargins(2, 2, 2, 0)
        self.filters = {}
        for pattern, key in zip(PATTERNS, ('screen.filter_all', 'screen.filter_red', 'screen.filter_black')):
            item = QPushButton(ui_text(key))
            item.setObjectName('screener_filter_' + pattern.lower())
            item.setAccessibleName(ui_text('screen.filter_name') + ' ' + ui_text(key))
            item.setCheckable(True)
            item.clicked.connect(lambda checked=False, selected=pattern: self.set_pattern(selected))
            self.filters[pattern] = item
            filters.addWidget(item)
        filters.addStretch()
        root.addWidget(self.filter_row)
        self.info = QLabel()
        self.info.setObjectName('screener_info')
        self.info.setAccessibleName(ui_text('screen.panel_name'))
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setWordWrap(True)
        root.addWidget(self.info)
        self.table = QTableWidget(0, 0)
        self.table.setObjectName('terminal_screener')
        self.table.setAccessibleName(ui_text('screen.table_name'))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(36)
        self.table.verticalHeader().hide()
        self.table.setMinimumWidth(220)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemClicked.connect(self._choose)
        self.table.itemActivated.connect(self._choose)
        root.addWidget(self.table, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)
        self._apply_list()

    # --- selection ---------------------------------------------------------
    def tab_title(self):
        return ui_text('screen.tab_label').format(list_name(self.list_id))

    def build_menu(self):
        """The drop-down of the tab: lists on top, the settings dialog last."""
        menu = QMenu(self)
        for title in (ui_text('screen.menu_conditions'),):
            menu.addAction(title).setEnabled(False)
        for list_id in ('SURGE', 'BREAKOUT'):
            self._list_action(menu, list_id)
        menu.addSeparator()
        menu.addAction(ui_text('screen.menu_klines')).setEnabled(False)
        self._list_action(menu, 'DOWNLOADED')
        menu.addSeparator()
        menu.addAction(ui_text('screen.menu_settings'), self.open_settings)
        return menu

    def _list_action(self, menu, list_id):
        action = menu.addAction(list_name(list_id), lambda checked=False, selected=list_id: self.set_list(selected))
        action.setCheckable(True)
        action.setChecked(list_id == self.list_id)

    def show_menu(self, tab_bar, index):
        if self._menu is not None:
            self._menu.deleteLater()  # the previous popup; it is never deleted by Qt itself, so this is always a live object
        self._menu = self.build_menu()
        self._menu.popup(tab_bar.mapToGlobal(tab_bar.tabRect(index).bottomLeft()))

    def set_list(self, list_id):
        self.list_id = list_id
        self._apply_list()
        self.on_list_changed()
        self.refresh()

    def set_pattern(self, pattern):
        self.pattern = pattern
        self._apply_list()
        self.refresh()

    def _apply_list(self):
        self.filter_row.setVisible(self.list_id == 'SURGE')
        for pattern, item in self.filters.items():
            item.setChecked(pattern == self.pattern)
        headers = _COLUMNS[self.list_id]
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels([ui_text(key) for key in headers])

    # --- data --------------------------------------------------------------
    def _submit(self, operation, completed):
        def finish(value, error):
            self._requests.discard(result)
            completed(value, error)

        result = _Result(finish)
        self._requests.add(result)
        start_request(operation, result)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    def refresh(self):
        if self._inflight:
            self._again = True
            return
        self._load('')

    def _load(self, download_id):
        self._inflight += 1
        self._serial += 1
        serial, list_id, pattern = self._serial, self.list_id, self.pattern

        def completed(value, error):
            self._inflight -= 1
            if error is not None:
                self.info.setText(ui_text('screen.load_failed'))
            elif serial == self._serial and (list_id, pattern) == (self.list_id, self.pattern):
                # Only the newest request for the list on screen may draw: an older answer arriving late is stale.
                self.render_view(value)
            if download_id and error is None:
                self.host.show_message(ui_text('screen.download_queued').format(download_id.split(':')[-1]))
            if self._again and not self._inflight:
                self._again = False
                self.refresh()

        self._submit(lambda: self.host.facade.screener(ScreenerQuery(list_id, pattern, download_id)), completed)

    # --- rendering ---------------------------------------------------------
    def render_view(self, view):
        notes = []
        if view.list_id == 'SURGE':
            notes.append(ui_text('screen.min_volume').format(view.min_volume_lots))
        if view.state == 'ACCUMULATING':
            notes.append(ui_text('screen.accumulating').format(view.progress_days, view.progress_needed))
        elif view.state in _STATE_NOTES:
            notes.append(ui_text(_STATE_NOTES[view.state]))
        if view.data_at is not None and view.state in ('LIVE', 'STALE', 'CLOSED'):
            notes.append(ui_text('screen.data_time').format(view.data_at.astimezone(_TAIPEI).strftime('%H:%M:%S')))
        if view.code:
            notes.append(ui_text('screen.reason').format(view.code))
        if not view.rows and not view.downloaded and view.state in ('LIVE', 'STALE', 'CLOSED') and not view.code:
            notes.append(ui_text('screen.none'))
        self.info.setText(' · '.join(notes))
        rows = view.downloaded if view.list_id == 'DOWNLOADED' else view.rows
        selected = self.table.item(self.table.currentRow(), 0)
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.table.setRowCount(len(rows))
        up, down = self.host.colours(self.host)
        for row, item in enumerate(rows):
            cells = self._downloaded_cells(item) if view.list_id == 'DOWNLOADED' else self._row_cells(view.list_id, item)
            for column, (text, tip, colour) in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, item.instrument_id)
                cell.setToolTip(tip or text)
                if colour:
                    cell.setForeground(QColor(up if colour == 'UP' else down))
                if column > 1:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, cell)
            if item.instrument_id == selected_id:
                self.table.selectRow(row)

    def _row_cells(self, list_id, row):
        direction = 'UP' if row.change_pct > 0 else 'DOWN' if row.change_pct < 0 else ''
        kline, tip = _kline_cell(row.kline)
        ratio = '' if row.ratio is None else format(row.ratio, '.2f')
        if list_id == 'SURGE':
            pattern = ui_text(_PATTERN_TEXT[row.label]) if row.label else ''
            tail = ((ratio, '', ''), (pattern, pattern, {'SURGE_RED': 'UP', 'SURGE_BLACK': 'DOWN'}.get(row.label, '')))
        else:
            window = row.label + (' ' + ui_text('screen.provisional') if row.provisional else '')
            tail = ((window, window, ''), (ratio, '', ''))
        return (
            (row.code, '', ''),
            (row.name, '', ''),
            (price_number(row.price, _STOCK), '', direction),
            (number(row.change_pct, signed=True, percent=True), '', direction),
            *tail,
            (kline, tip, ''),
        )

    @staticmethod
    def _downloaded_cells(row):
        return (
            (row.code, '', ''),
            (row.name, '', ''),
            (_day_text(row.first), '', ''),
            (_day_text(row.last), '', ''),
            (_day_text(row.updated), '', ''),
        )

    # --- actions -----------------------------------------------------------
    def _choose(self, item):
        self.host.select_instrument(self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole))

    def row_menu(self, instrument_id):
        menu = QMenu(self)
        menu.addAction(ui_text('sector.menu_add_watch'), lambda: self.host.add_watch(instrument_id))
        menu.addAction(ui_text('screen.menu_download'), lambda: self.download(instrument_id))
        return menu

    def _context_menu(self, point):
        item = self.table.itemAt(point)
        if item is not None:
            menu = self.row_menu(self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole))
            menu.exec(self.table.viewport().mapToGlobal(point))
            menu.deleteLater()

    def download(self, instrument_id):
        self._load(instrument_id)  # not held back by a running poll: the click must reach the engine

    def open_settings(self):
        from desktop_app.features.trading.screener_settings_dialog import ScreenerSettingsDialog

        def opened(value, error):
            if error is not None:
                self.host.show_message(ui_text('screen.load_failed'))
                return
            dialog = ScreenerSettingsDialog(self.host.facade, value, self._submit, self, on_saved=self.refresh)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.settings_dialog = dialog
            dialog.show()

        self._submit(lambda: self.host.facade.screener_settings(), opened)
