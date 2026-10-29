"""Read-only market watch panels and facade wiring; no trading or market math.

The composition root injects a CandlestickChart instance. This keeps reusable
chart infrastructure outside the trading presentation import boundary. Series
pages always come from Application, including every selected period.
"""

from dataclasses import replace
from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QLabel, QLineEdit, QPushButton, QTableWidget, QHeaderView, QHBoxLayout, QVBoxLayout, QSplitter, QScrollArea, QLayout
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import MarketSeriesQuery, MarketWatchView, UiAction, UiCommand
from desktop_app.features.trading.market_watch_rows import freshness_text, header_text, quote_detail_text, watch_rows, series_bars, series_status
from desktop_app.features.trading.widgets import rows, selected_id


class _Result(QObject):
    ready = Signal(object, object)

    def __init__(self, completed):
        super().__init__()
        self.completed = completed
        self.ready.connect(self.finish)

    @Slot()
    def cancel(self):
        self.completed = None

    @Slot(object, object)
    def finish(self, value, error):
        if self.completed is not None:
            self.completed(value, error)
        self.deleteLater()


class _Request(QRunnable):
    def __init__(self, operation, result):
        super().__init__()
        self.operation, self.result = operation, result

    def run(self):
        try:
            value = self.operation()
        except Exception as error:
            self.result.ready.emit(None, error)
        else:
            self.result.ready.emit(value, None)


class MarketWatchWidget(QWidget):
    def __init__(self, facade, chart, state, parent=None):
        super().__init__(parent)
        self.facade, self.chart, self.state = facade, chart, state
        self.period = '1m'
        self._bars, self._series_key, self._revision = (), None, -1
        self._generation, self._busy = 0, False
        self._series_loading, self._pending_request = False, None
        self._requests = set()
        self._identify(self, 'market_watch', ui_text('watch.title'))
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        header = QHBoxLayout()
        self.header = self._label('watch_header', ui_text('watch.header_name'))
        self.instrument = QLineEdit()
        self._identify(self.instrument, 'watch_instrument', ui_text('watch.instrument'))
        self.instrument.setPlaceholderText(ui_text('watch.instrument'))
        self.add = self._button('watch_add', ui_text('watch.add'))
        self.remove = self._button('watch_remove', ui_text('watch.remove'))
        for widget in (self.header, self.instrument, self.add, self.remove):
            header.addWidget(widget)
        layout.addLayout(header)
        self.panels = QSplitter(Qt.Orientation.Horizontal)
        self.panels.setChildrenCollapsible(False)
        self._identify(self.panels, 'watch_panels', ui_text('watch.title'))
        self.table = QTableWidget(0, 6)
        self._identify(self.table, 'watch_table', ui_text('watch.list'))
        self.table.setHorizontalHeaderLabels(
            (
                ui_text('watch.instrument'),
                ui_text('watch.price'),
                ui_text('watch.change'),
                ui_text('watch.percent'),
                ui_text('watch.volume'),
                ui_text('watch.state'),
            )
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setTabKeyNavigation(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.panels.addWidget(self.table)
        center = QWidget()
        self._identify(center, 'watch_chart_panel', ui_text('watch.chart'))
        center_layout = QVBoxLayout(center)
        center_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        periods = QHBoxLayout()
        self.period_buttons = {}
        choices = (
            ('1m', ui_text('watch.period_1m')),
            ('3m', ui_text('watch.period_3m')),
            ('5m', ui_text('watch.period_5m')),
            ('15m', ui_text('watch.period_15m')),
            ('30m', ui_text('watch.period_30m')),
            ('60m', ui_text('watch.period_60m')),
            ('1d', ui_text('watch.period_1d')),
        )
        for period, text in choices:
            button = self._button('watch_period_' + period, text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, selected=period: self.select_period(selected))
            periods.addWidget(button)
            self.period_buttons[period] = button
        center_layout.addLayout(periods)
        self._identify(chart, 'watch_chart', ui_text('watch.chart'))
        center_layout.addWidget(chart)
        self.gap = self._label('watch_gap', ui_text('watch.gap'))
        self.history_error = self._label('watch_history_error', ui_text('watch.history_error_name'))
        self.retry = self._button('watch_retry', ui_text('watch.retry'))
        for widget in (self.gap, self.history_error, self.retry):
            center_layout.addWidget(widget)
        self.panels.addWidget(center)
        self.detail = self._label('watch_detail', ui_text('watch.detail'))
        scroll = QScrollArea()
        self._identify(scroll, 'watch_detail_scroll', ui_text('watch.detail'))
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.detail)
        self.panels.addWidget(scroll)
        # Initial proportions; otherwise the chart's size hint squeezes the side panels to slivers.
        self.panels.setSizes((3000, 5000, 2000))
        layout.addWidget(self.panels)
        self.message = self._label('watch_message', ui_text('watch.message'))
        layout.addWidget(self.message)
        self.message.clear()
        self.add.clicked.connect(self.add_watch)
        self.instrument.returnPressed.connect(self.add_watch)
        self.remove.clicked.connect(self.remove_watch)
        self.retry.clicked.connect(lambda: self.load_series(retry=True))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        focus = [self.instrument, self.add, self.remove, self.table, *self.period_buttons.values(), chart, self.retry, scroll]
        for before, after in zip(focus, focus[1:]):
            QWidget.setTabOrder(before, after)
        self.render(state)

    @staticmethod
    def _identify(widget, name, text):
        widget.setObjectName(name)
        widget.setAccessibleName(text)

    def _label(self, name, text):
        label = QLabel()
        self._identify(label, name, text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def _button(self, name, text):
        button = QPushButton(text)
        self._identify(button, name, text)
        button.setMinimumHeight(36)
        return button

    def _submit(self, operation, completed):
        def finish(value, error):
            self._requests.discard(result)
            if error is not None:
                self.message.setText(ui_text('watch.request_error'))
            completed(value, error)

        result = _Result(finish)
        self._requests.add(result)
        self.destroyed.connect(result.cancel)
        QThreadPool.globalInstance().start(_Request(operation, result))

    def render(self, state):
        self.state = state
        self.header.setText(header_text(state.market_connection, state.market_health))
        by_id = {view.instrument_id: view for view in state.market_watch}
        views = tuple(by_id.get(key, MarketWatchView(instrument_id=key)) for key in state.watchlist)
        self.table.blockSignals(True)
        rows(self.table, watch_rows(views))
        colours = {'live': self.table.palette().text().color(), 'warning': QColor('#c6a000'), 'muted': QColor('#808080')}
        for index, view in enumerate(views):
            role = freshness_text(view.health, view.received_at)[1]
            for column in (1, 5):
                self.table.item(index, column).setForeground(colours[role])
        if self.table.rowCount() and not selected_id(self.table):
            self.table.selectRow(0)
        self.table.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self):
        key = selected_id(self.table)
        view = next((view for view in self.state.market_watch if view.instrument_id == key), MarketWatchView())
        self.detail.setText(quote_detail_text(view))
        self.gap.setText(ui_text('watch.gap') if view.health.incomplete or view.gaps else '')
        self.history_error.setText(ui_text('watch.history_error').format(view.health.history_error) if view.health.history_error else '')
        self.retry.setVisible(bool(view.health.history_error))
        if key and key in {view.instrument_id for view in self.state.market_watch}:
            self.load_series()
        else:
            self._generation += 1
            self.chart.set_series(())
            self._bars, self._series_key = (), None

    def select_period(self, period):
        self.period = period
        self.load_series()

    def load_series(self, *, retry=False):
        key, period = selected_id(self.table), self.period
        for name, button in self.period_buttons.items():
            button.setChecked(name == period)
        if not key or key not in {view.instrument_id for view in self.state.market_watch}:
            return
        self._generation += 1
        generation = self._generation
        if self._series_loading:
            self._pending_request = (key, period, retry)
            return
        self._series_loading = True

        def fetch():
            page = self.facade.market_series(MarketSeriesQuery(key, period, retry_history=retry))
            bars = page.bars
            while page.next_offset is not None:
                page = self.facade.market_series(MarketSeriesQuery(key, period, offset=page.next_offset, market_revision=page.market_revision))
                bars += page.bars
            return replace(page, bars=bars, offset=0)

        def completed(page, error):
            self._series_loading = False
            if self._pending_request is not None:
                pending_key, pending_period, pending_retry = self._pending_request
                self._pending_request = None
                if (pending_key, pending_period) == (selected_id(self.table), self.period):
                    self.load_series(retry=pending_retry)
                return
            if generation != self._generation or error is not None:
                return
            new = series_bars(page)
            same = self._series_key == (key, period) and page.market_revision >= self._revision
            if same and self._bars and len(new) == len(self._bars) and new[:-1] == self._bars[:-1] and new[-1].start == self._bars[-1].start:
                if new[-1] != self._bars[-1]:
                    self.chart.replace_last_bar(new[-1])
            elif same and self._bars and len(new) == len(self._bars) + 1 and new[:-1] == self._bars:
                self.chart.append_bar(new[-1])
            else:
                self.chart.set_series(
                    new,
                    source_label=ui_text('watch.source'),
                    status_label=ui_text('watch.forming') if page.bars and not page.bars[-1].final else ui_text('watch.title'),
                )
            self.chart.status_label = ui_text('watch.forming') if page.bars and not page.bars[-1].final else ui_text('watch.title')
            self._bars, self._series_key, self._revision = new, (key, period), page.market_revision
            health = next(view.health for view in self.state.market_watch if view.instrument_id == key)
            self.gap.setText(series_status(page, health))

        self._submit(fetch, completed)

    def add_watch(self):
        key = self.instrument.text().strip()
        if not key:
            self.message.setText(ui_text('watch.enter_instrument'))
            return
        self._save_watchlist(tuple(dict.fromkeys((*self.state.watchlist, key))))

    def remove_watch(self):
        key = selected_id(self.table)
        if key:
            self._save_watchlist(tuple(item for item in self.state.watchlist if item != key))

    def _save_watchlist(self, watches):
        if self._busy:
            return
        self._busy = True
        state = self.state
        command = UiCommand(UiAction.SAVE_SETTINGS, state.version, watchlist=watches, context_id=state.context_id, context_epoch=state.context_epoch)

        def operation():
            receipt = self.facade.execute(command)
            return receipt, self.facade.snapshot() if receipt.accepted else None

        def completed(value, error):
            self._busy = False
            if error is not None:
                return
            receipt, state = value
            self.message.setText(receipt.message if not receipt.accepted else '')
            if not receipt.accepted and receipt.code == 'subscription_limit_reached':
                self.message.setText(ui_text('watch.refused').format(receipt.message, self.state.market_health.subscription_limit))
            if state is not None:
                self.render(state)

        self._submit(operation, completed)
