"""Read-only replay of stored sector minutes: pick a trading day, then step or play through its minutes."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout

from desktop_app.features.trading.sector_board import amount_text
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.sector_contracts import SectorHistoryQuery

COLUMNS = ('group', 'pct', 'share', 'breadth', 'limit_up', 'minute_amount', 'count')
PLAY_MILLISECONDS = 700


class _Item(QTableWidgetItem):
    """Sorts by the numeric value kept in UserRole, not by the displayed text."""

    def __init__(self, text, value):
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, value)
        if not isinstance(value, str):
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        mine, theirs = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        if isinstance(mine, str) or isinstance(theirs, str):
            return str(mine) < str(theirs)
        return mine < theirs


def history_cells(row):
    """Display text and sort value for each column of one stored group minute."""
    # An incomplete minute stores no amount (0); show that it is unknown instead of a misleading zero.
    amount = amount_text(row.amount) if row.complete else ui_text('sector.no_value') + ui_text('sector.replay_incomplete')
    return (
        (row.name, row.name),
        (f'{row.equal_pct_bps / 100:+.2f}%', row.equal_pct_bps),
        (f'{row.share_bps / 100:.2f}%', row.share_bps),
        (f'{row.breadth_bps / 100:.0f}%', row.breadth_bps),
        (str(row.limit_up), row.limit_up),
        (amount, row.amount if row.complete else -1),
        (str(row.members), row.members),
    )


class SectorReplayDialog(QDialog):
    def __init__(self, facade, defer, parent=None):
        super().__init__(parent)
        self.facade, self.defer = facade, defer
        self.minutes, self.trade_date, self._generation = (), '', 0
        self.setWindowTitle(ui_text('sector.replay_title'))
        self.setAccessibleName(ui_text('sector.replay_title'))
        self.resize(820, 560)
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(ui_text('sector.replay_date')))
        self.days = QComboBox()
        self.days.setAccessibleName(ui_text('sector.replay_date'))
        self.days.currentIndexChanged.connect(lambda index: self.load_day())
        controls.addWidget(self.days)
        self.previous = self._button('sector.replay_previous', lambda: self.step(-1))
        self.play = self._button('sector.replay_play', self.toggle_play)
        self.next = self._button('sector.replay_next', lambda: self.step(1))
        for widget in (self.previous, self.play, self.next):
            controls.addWidget(widget)
        self.time = QLabel('')
        self.time.setAccessibleName(ui_text('sector.replay_title'))
        controls.addWidget(self.time, 1)
        root.addLayout(controls)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName(ui_text('sector.replay_slider'))
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.load_minute)
        root.addWidget(self.slider)
        self.message = QLabel(ui_text('sector.replay_loading'))
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setAccessibleName(ui_text('sector.replay_title'))
        self.table.setHorizontalHeaderLabels([ui_text('sector.col_' + name) for name in COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(PLAY_MILLISECONDS)
        self.timer.timeout.connect(self._advance)
        self._set_controls(False)
        self._request(SectorHistoryQuery())

    def _button(self, key, handler):
        widget = QPushButton(ui_text(key))
        widget.setAccessibleName(ui_text(key))
        widget.clicked.connect(lambda checked=False: handler())
        return widget

    def _set_controls(self, enabled):
        for widget in (self.previous, self.play, self.next, self.slider):
            widget.setEnabled(enabled)

    # --- requests (latest wins) ------------------------------------------------
    def _request(self, query):
        self._generation += 1
        generation = self._generation
        facade = self.facade

        def completed(view, error):
            if generation == self._generation:
                self.render(view if error is None else None)

        self.defer(lambda: facade.sector_history(query), completed)

    def load_day(self):
        day = self.days.currentData()
        if day:
            self.stop()
            self._request(SectorHistoryQuery(day))

    def load_minute(self, index):
        if self.trade_date and 0 <= index < len(self.minutes):
            self.time.setText(ui_text('sector.replay_time').format(self.trade_date, self.minutes[index]))
            self._request(SectorHistoryQuery(self.trade_date, self.minutes[index]))

    # --- playback ---------------------------------------------------------------
    def step(self, delta):
        self.slider.setValue(max(0, min(self.slider.maximum(), self.slider.value() + delta)))

    def toggle_play(self):
        if self.timer.isActive():
            self.stop()
            return
        if self.slider.value() >= self.slider.maximum():
            self.slider.setValue(0)
        self.play.setText(ui_text('sector.replay_pause'))
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.play.setText(ui_text('sector.replay_play'))

    def _advance(self):
        if self.slider.value() >= self.slider.maximum():
            self.stop()
        else:
            self.step(1)

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    # --- rendering --------------------------------------------------------------
    def render(self, view):
        if view is None or view.failed:
            self.stop()
            self.message.setText(ui_text('sector.replay_failed'))
            self.message.show()
            return
        if not view.days:
            self.message.setText(ui_text('sector.replay_empty'))
            self.message.show()
            self._set_controls(False)
            return
        if self.days.count() != len(view.days):
            self.days.blockSignals(True)
            self.days.clear()
            for day in view.days:
                self.days.addItem(day, day)
            self.days.blockSignals(False)
        if not view.trade_date:
            self.load_day()
            return
        if view.trade_date != self.trade_date or view.minutes != self.minutes:
            self.trade_date, self.minutes = view.trade_date, view.minutes
            self.slider.blockSignals(True)
            self.slider.setRange(0, max(0, len(view.minutes) - 1))
            self.slider.setValue(view.minutes.index(view.minute) if view.minute in view.minutes else 0)
            self.slider.blockSignals(False)
            self._set_controls(bool(view.minutes))
        if view.minute:
            self.time.setText(ui_text('sector.replay_time').format(view.trade_date, view.minute))
        self.message.setVisible(not view.rows)
        if not view.rows:
            self.message.setText(ui_text('sector.replay_empty'))
        self._fill(view.rows)

    def _fill(self, rows):
        sort_column = self.table.horizontalHeader().sortIndicatorSection() if self.table.isSortingEnabled() else 1
        sort_order = self.table.horizontalHeader().sortIndicatorOrder() if self.table.isSortingEnabled() else Qt.SortOrder.DescendingOrder
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, (text, value) in enumerate(history_cells(row)):
                item = _Item(text, value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole + 1, row.group_id)
                self.table.setItem(index, column, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(sort_column, sort_order)
