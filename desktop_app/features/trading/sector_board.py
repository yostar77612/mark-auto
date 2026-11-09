"""Sector board tab: ranking, members and a stock detail. Reads views only; no trading, no market math."""

from dataclasses import replace
from decimal import Decimal
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QSplitter, QTableWidget, QVBoxLayout, QWidget

from desktop_app.features.trading.market_terminal_widgets import QuoteItem
from desktop_app.features.trading.market_watch import _Request, _Result
from desktop_app.features.trading.market_watch_rows import series_bars
from desktop_app.features.trading.order_book_panel import OrderBookPanel
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import MarketSeriesQuery
from quantlab.trading.application.sector_contracts import SectorGroupsCommand, SectorQuery

_TAIPEI = ZoneInfo('Asia/Taipei')
REFRESH_MS = 2000
FILTERS = (('all', 'sector.filter_all'), ('INDUSTRY', 'sector.filter_industry'), ('CONCEPT', 'sector.filter_concept'))
PERIODS = (('1m', 'terminal.period_1m'), ('5m', 'terminal.period_5m'), ('15m', 'terminal.period_15m'), ('1d', 'terminal.period_1d'))
RANK_COLUMNS = ('group', 'kind', 'pct', 'breadth', 'limit_up', 'amount', 'share', 'count')
MEMBER_COLUMNS = ('code', 'name', 'price', 'change', 'ratio', 'amount', 'side')


def percent_text(value, signed=True):
    return ui_text('sector.no_value') if value is None else format(value, '+.2f' if signed else '.2f') + '%'


def amount_text(value):
    return ui_text('sector.amount_eok').format(format(Decimal(value) / Decimal(10**8), '.1f'))


def clock_text(moment):
    return moment.astimezone(_TAIPEI).strftime('%H:%M:%S')


def _table(name, headers, stretch=0, name_width=112):
    table = QTableWidget(0, len(headers))
    table.setObjectName(name)
    table.setAccessibleName(name)
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Interactive)
    header.resizeSection(stretch, name_width)
    header.setMinimumSectionSize(30)
    header.setSortIndicatorShown(True)
    table.verticalHeader().hide()
    return table


class SectorBoardWidget(QWidget):
    def __init__(self, facade, chart, parent=None, *, colours=None, style=None, open_in_watch=None, add_to_watch=None):
        super().__init__(parent)
        self.facade, self.chart, self.style = facade, chart, style
        self.open_in_watch, self.add_to_watch = open_in_watch, add_to_watch
        self.colours = colours or (lambda widget: ('#c62828', '#16803c'))
        self.setObjectName('sector_board')
        self.setAccessibleName(ui_text('sector.tab_board'))
        self.filter, self.group_id, self.stock_id, self.period = 'all', '', '', '1m'
        self.rank_sort, self.member_sort = (2, Qt.SortOrder.DescendingOrder), (3, Qt.SortOrder.DescendingOrder)
        self.view = None
        self._requests, self._loading, self._detail_loading, self._selecting, self._again = set(), False, None, False, False
        self._wanted = ''
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.filter_buttons = {}
        for key, text in FILTERS:
            item = QPushButton(ui_text(text))
            item.setObjectName('sector_filter_' + key)
            item.setAccessibleName(ui_text(text))
            item.setCheckable(True)
            item.setChecked(key == 'all')
            item.clicked.connect(lambda checked=False, selected=key: self.set_filter(selected))
            self.filter_buttons[key] = item
            top.addWidget(item)
        self.edit_button = QPushButton(ui_text('sector.edit_button'))
        self.edit_button.setObjectName('sector_edit_button')
        self.edit_button.setAccessibleName(ui_text('sector.edit_button'))
        self.edit_button.clicked.connect(lambda checked=False: self.open_editor())
        top.addWidget(self.edit_button)
        top.addStretch()
        self.status = QLabel(ui_text('sector.offline'))
        self.status.setObjectName('sector_status')
        self.status.setAccessibleName(ui_text('sector.tab_board'))
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(self.status)
        root.addLayout(top)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.rank = _table('sector_rank', [ui_text('sector.col_' + name) for name in RANK_COLUMNS])
        self.rank.setAccessibleName(ui_text('sector.rank_title'))
        self.rank.itemClicked.connect(lambda item: self.select_group(self.rank.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)))
        self.rank.horizontalHeader().sectionClicked.connect(lambda column: self._sort(self.rank, 'rank_sort', column))
        self.members = _table(
            'sector_members',
            [ui_text('sector.col_' + name) for name in ('code', 'name', 'price', 'change', 'ratio', 'member_amount', 'side')],
            stretch=1,
            name_width=70,
        )
        self.members.setAccessibleName(ui_text('sector.members_title'))
        self.members.itemClicked.connect(lambda item: self.select_stock(self.members.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)))
        self.members.horizontalHeader().sectionClicked.connect(lambda column: self._sort(self.members, 'member_sort', column))
        self.members.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.members.customContextMenuRequested.connect(self._member_menu)
        self.members_hint = QLabel(ui_text('sector.pick_group'))
        self.members_hint.setObjectName('sector_members_hint')
        self.members_hint.setAccessibleName(ui_text('sector.members_title'))
        self.members_hint.setWordWrap(True)
        members_box = QWidget()
        members_layout = QVBoxLayout(members_box)
        members_layout.setContentsMargins(0, 0, 0, 0)
        self.members_title = QLabel(ui_text('sector.members_title'))
        self.members_title.setObjectName('sector_members_title')
        self.members_title.setAccessibleName(ui_text('sector.members_title'))
        self.members_title.setTextFormat(Qt.TextFormat.PlainText)
        members_layout.addWidget(self.members_title)
        members_layout.addWidget(self.members_hint)
        members_layout.addWidget(self.members, 1)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_title = QLabel(ui_text('sector.pick_stock'))
        self.detail_title.setObjectName('sector_detail_title')
        self.detail_title.setAccessibleName(ui_text('sector.detail_title'))
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        detail_layout.addWidget(self.detail_title)
        periods = QHBoxLayout()
        self.period_buttons = {}
        for key, text in PERIODS:
            item = QPushButton(ui_text(text))
            item.setObjectName('sector_period_' + key)
            item.setAccessibleName(ui_text(text))
            item.setCheckable(True)
            item.setChecked(key == self.period)
            item.clicked.connect(lambda checked=False, selected=key: self.select_period(selected))
            self.period_buttons[key] = item
            periods.addWidget(item)
        periods.addStretch()
        detail_layout.addLayout(periods)
        chart.setObjectName('sector_chart')
        chart.setAccessibleName(ui_text('sector.detail_title'))
        chart.setMinimumSize(100, 90)
        self.order_book = OrderBookPanel()
        self.order_book.clear(ui_text('sector.pick_stock'))
        column = QSplitter(Qt.Orientation.Vertical)
        column.setChildrenCollapsible(False)
        column.addWidget(chart)
        column.addWidget(self.order_book)
        column.setStretchFactor(0, 2)
        column.setStretchFactor(1, 3)
        detail_layout.addWidget(column, 1)
        for part in (self.rank, members_box, detail):
            splitter.addWidget(part)
        splitter.setSizes((580, 290, 310))
        root.addWidget(splitter, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)

    # --- async plumbing -------------------------------------------------
    def _submit(self, operation, completed):
        def finish(value, error):
            self._requests.discard(result)
            completed(value, error)

        result = _Result(finish)
        self._requests.add(result)
        self.destroyed.connect(result.cancel)
        QThreadPool.globalInstance().start(_Request(operation, result))

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    # --- data -------------------------------------------------------------
    def refresh(self):
        if self._loading:
            self._again = True
            return
        self._loading = True
        group = self.group_id

        def completed(value, error):
            self._loading = False
            if error is not None:
                self.render_failure()
            elif group == self.group_id:
                self.render_board(value)
            if self._again:
                self._again = False
                self.refresh()

        self._submit(lambda: self.facade.sector_board(SectorQuery(group)), completed)
        self._refresh_detail()

    def _refresh_detail(self):
        if not self.stock_id or self._selecting or self._detail_loading == (self.stock_id, self.period):
            return
        key, period = self.stock_id, self.period
        self._detail_loading = (key, period)

        def fetch():
            page = self.facade.market_series(MarketSeriesQuery(key, period))
            bars = page.bars
            while page.next_offset is not None:
                page = self.facade.market_series(MarketSeriesQuery(key, period, offset=page.next_offset, market_revision=page.market_revision))
                bars += page.bars
            return page, bars, self.facade.order_book(key)

        def completed(value, error):
            if self._detail_loading == (key, period):
                self._detail_loading = None
            if error is not None and key == self.stock_id:
                self.order_book.clear(ui_text('sector.error'))
            if error is None and key == self.stock_id and period == self.period:
                page, bars, book = value
                self.chart.set_series(series_bars(replace(page, bars=bars, offset=0)))
                self.order_book.render_view(book, *self.colours(self))

        self._submit(fetch, completed)

    # --- rendering ---------------------------------------------------------
    def _warn(self, on):
        """Amber status text without an inline stylesheet (theme-owned styling stays centralized)."""
        palette = self.status.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor('#e67e22') if on else self.palette().color(QPalette.ColorRole.WindowText))
        self.status.setPalette(palette)

    def render_failure(self):
        """The engine could not be read: show that, and never keep old numbers on screen as if they were current."""
        self.view = None
        self.status.setText(ui_text('sector.error'))
        self._warn(True)
        self.rank.setRowCount(0)
        self.members.setRowCount(0)
        self.members_hint.setText(ui_text('sector.error'))
        self.members_hint.show()

    def render_board(self, view):
        self.view = view
        if view.state == 'OFFLINE':
            text, stale = ui_text('sector.offline'), False
        elif view.state == 'EMPTY':
            text, stale = ui_text('sector.empty'), False
        elif view.state == 'CLOSED':
            text, stale = ui_text('sector.closed'), False
        else:
            text = ui_text('sector.data_time').format(clock_text(view.data_at) if view.data_at else ui_text('sector.no_value'), view.interval_seconds)
            stale = view.state == 'STALE'
            if stale:
                text += ' · ' + ui_text('sector.stale').format(view.age_seconds)
        if view.failed:
            text = ui_text('sector.error') if view.state in ('OFFLINE', 'EMPTY') else text + ' · ' + ui_text('sector.refresh_failed')
            stale = True
        self.status.setText(text)
        self._warn(stale)
        if view.state in ('OFFLINE', 'EMPTY'):
            self.rank.setRowCount(0)
            self.members.setRowCount(0)
            self.members_hint.setText(ui_text('sector.pick_group'))
            self.members_hint.show()
            return
        self._render_rank(view)
        self._render_members(view)
        if self.style is not None:
            self.style(self)

    def _fill(self, table, rows, sort):
        column, order = sort
        known = [item for item in rows if item[1][column][1] is not None]
        unknown = [item for item in rows if item[1][column][1] is None]
        known.sort(key=lambda item: item[1][column][1], reverse=order == Qt.SortOrder.DescendingOrder)
        rows = known + unknown
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row, (key, cells) in enumerate(rows):
            for column, (text, sort_value, colour, tip, *background) in enumerate(cells):
                item = QuoteItem(text, sort_value)
                item.setData(Qt.ItemDataRole.UserRole, key)
                if colour is not None:
                    item.setForeground(colour)
                if tip:
                    item.setToolTip(tip)
                if background:
                    item.setBackground(background[0])
                if column > 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, column, item)
        table.horizontalHeader().setSortIndicator(*sort)

    def _direction(self, value):
        up, down = self.colours(self)
        return QColor(up) if value is not None and value > 0 else QColor(down) if value is not None and value < 0 else None

    def _render_rank(self, view):
        rows = []
        for stat in view.groups:
            if self.filter != 'all' and stat.kind != self.filter:
                continue
            breadth = Decimal(stat.up_count) / Decimal(stat.valid_count) if stat.valid_count else None
            name = stat.name + (' · ' + ui_text('sector.few_members') if stat.valid_count and stat.valid_count < 4 else '')
            kind = ui_text('sector.kind_industry') if stat.kind == 'INDUSTRY' else ui_text('sector.kind_concept')
            rows.append(
                (
                    stat.group_id,
                    (
                        (name, stat.name, None, None),
                        (kind, stat.kind, None, None),
                        (percent_text(stat.equal_pct), stat.equal_pct, self._direction(stat.equal_pct), None),
                        (f'{stat.up_count}/{stat.valid_count}' if stat.valid_count else ui_text('sector.no_value'), breadth, None, None),
                        (str(stat.limit_up), stat.limit_up, None, None),
                        (amount_text(stat.amount), stat.amount, None, None),
                        (percent_text(stat.share * 100, signed=False) if stat.share is not None else ui_text('sector.no_value'), stat.share, None, None),
                        (f'{stat.valid_count}/{stat.listed_count}', stat.valid_count, None, None),
                    ),
                )
            )
        self._fill(self.rank, rows, self.rank_sort)
        for row in range(self.rank.rowCount()):
            if self.rank.item(row, 0).data(Qt.ItemDataRole.UserRole) == self.group_id:
                self.rank.selectRow(row)

    def _render_members(self, view):
        if not view.selected_group_id:
            self.members.setRowCount(0)
            self.members_title.setText(ui_text('sector.members_title'))
            self.members_hint.setText(ui_text('sector.pick_group'))
            self.members_hint.show()
            return
        stat = next((item for item in view.groups if item.group_id == view.selected_group_id), None)
        self.members_title.setText(ui_text('sector.members_of').format(stat.name if stat else ''))
        self.members_hint.hide()
        rows = []
        for member in view.members:
            colour = self._direction(member.change_pct)
            leader = ('★' if member.is_leader else '') + member.code
            tip = ui_text('sector.leader_tip').format(clock_text(member.leader_at)) if member.is_leader and member.leader_at else None
            limit_background = (QColor(self.colours(self)[0]).lighter(190),) if member.limit == 'UP' else ()
            limit_tip = ui_text('sector.limit_up_tip').format(clock_text(member.leader_at)) if member.limit == 'UP' and member.leader_at else None
            rows.append(
                (
                    member.instrument_id,
                    (
                        (leader, member.code, None, tip),
                        (member.name, member.name, None, None),
                        (format(member.price, 'f'), member.price, colour, limit_tip, *limit_background),
                        (percent_text(member.change_pct), member.change_pct, colour, None),
                        (
                            format(member.volume_ratio, '.2f') if member.volume_ratio is not None else ui_text('sector.no_value'),
                            member.volume_ratio,
                            None,
                            None,
                        ),
                        (amount_text(member.amount), member.amount, None, None),
                        (ui_text('sector.no_value'), None, None, None),
                    ),
                )
            )
        self._fill(self.members, rows, self.member_sort)
        for row in range(self.members.rowCount()):
            if self.members.item(row, 0).data(Qt.ItemDataRole.UserRole) == self.stock_id:
                self.members.selectRow(row)

    # --- interaction ---------------------------------------------------------
    def _sort(self, table, attribute, column):
        previous = getattr(self, attribute)
        order = Qt.SortOrder.AscendingOrder if previous == (column, Qt.SortOrder.DescendingOrder) else Qt.SortOrder.DescendingOrder
        setattr(self, attribute, (column, order))
        if self.view is not None:
            self._render_rank(self.view) if table is self.rank else self._render_members(self.view)

    def _member_menu(self, point):
        item = self.members.itemAt(point)
        if item is None:
            return
        instrument_id = self.members.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if self.add_to_watch is not None:
            menu.addAction(ui_text('sector.menu_add_watch'), lambda: self.add_to_watch(instrument_id))
        if self.open_in_watch is not None:
            menu.addAction(ui_text('sector.menu_open_watch'), lambda: self.open_in_watch(instrument_id))
        if self.group_id and not self.group_id.startswith('industry.'):
            menu.addAction(ui_text('sector.menu_remove_member'), lambda: self.remove_member(self.group_id, instrument_id.split(':')[-1]))
        if menu.actions():
            menu.exec(self.members.viewport().mapToGlobal(point))

    def remove_member(self, group_id, code):
        facade = self.facade

        def operation():
            current = next(group for group in facade.sector_groups(SectorGroupsCommand()).groups if group.id == group_id)
            return facade.sector_groups(SectorGroupsCommand('SET_CODES', group_id, codes=tuple(value for value in current.codes if value != code)))

        self._submit(operation, lambda value, error: self.refresh())

    def open_editor(self):
        from desktop_app.features.trading.sector_editor import SectorEditor

        def operation():
            return self.facade.symbol_directory()

        def opened(value, error):
            if error is not None:
                self.status.setText(ui_text('sector.error'))
            else:
                editor = SectorEditor(self.facade, value, self._submit, self, on_changed=self.refresh)
                editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                self.editor = editor
                editor.show()

        self._submit(operation, opened)

    def set_filter(self, key):
        self.filter = key
        for name, item in self.filter_buttons.items():
            item.setChecked(name == key)
        if self.view is not None:
            self._render_rank(self.view)

    def select_group(self, group_id):
        if group_id == self.group_id:
            return
        self.group_id = group_id
        if self.view is not None:
            self._render_rank(self.view)
        self.refresh()

    def select_period(self, period):
        self.period = period
        for name, item in self.period_buttons.items():
            item.setChecked(name == period)
        self._refresh_detail()

    def select_stock(self, instrument_id):
        if self._selecting:
            self._wanted = instrument_id
            return
        if instrument_id == self.stock_id:
            self._refresh_detail()
            return
        self.stock_id = instrument_id
        self._selecting = True
        member = next((m for m in (self.view.members if self.view else ()) if m.instrument_id == instrument_id), None)
        self.detail_title.setText(ui_text('sector.detail_of').format(member.code if member else '', member.name if member else ''))
        self.chart.set_series(())
        self.order_book.clear(ui_text('orderbook.waiting'))
        period = self.period

        def completed(value, error):
            self._selecting = False
            wanted, self._wanted = self._wanted, ''
            if error is not None:
                self.stock_id = ''
                self.detail_title.setText(ui_text('sector.error'))
                self.chart.set_series(())
                self.order_book.clear(ui_text('sector.error'))
            if wanted:
                self.select_stock(wanted)
            elif error is None:
                self._refresh_detail()

        self._submit(lambda: self.facade.select_market_instrument(instrument_id, period), completed)
