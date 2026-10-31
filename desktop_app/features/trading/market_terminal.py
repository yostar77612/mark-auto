"""Read-only terminal; application ports own subscriptions, history, and prices."""

from dataclasses import replace
from PySide6.QtCore import Qt, QEvent, QThreadPool
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QMenu, QDialog, QVBoxLayout, QLabel
from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.market_watch import _Result, _Request
from desktop_app.features.trading.market_watch_rows import series_bars
from desktop_app.features.trading.market_terminal_rows import number, price_number, state_label, diagnostic_text, source_text
from desktop_app.features.trading.market_terminal_widgets import identify, build_terminal, render_quote_table, render_status, render_chart
from quantlab.trading.application.contracts import MarketSeriesQuery, MarketWatchView, UiCommand, UiAction
from quantlab.trading.domain.watch import FIXED_INDICES


class MarketTerminalWidget(QWidget):
    def __init__(
        self, facade, chart, state, parent=None, *, layout_store, index_chart, panel_factory, alerts_panel=None, colours=lambda widget: ('#c62828', '#16803c')
    ):
        super().__init__(parent)
        self.facade, self.chart, self.index_chart, self.state = facade, chart, index_chart, state
        self.colours = colours
        self.current_instrument = FIXED_INDICES[0].instrument_id
        self.period, self.periods, self._requests = '1m', {}, set()
        self._generation, self._series_loading, self._pending, self._busy = 0, False, False, False
        self._selecting, self._selection_pending, self._ready = False, False, False
        self._pending_retry = False
        self._directory, self._history_only, self._terminal_status = tuple(FIXED_INDICES), False, None
        self._sorts, self._last_series, self._occurred_at = {}, None, None
        self._last_warning = ''
        identify(self, 'market_terminal', ui_text('terminal.title'))
        build_terminal(self, layout_store, alerts_panel, panel_factory)
        self.render(state)
        self.refresh_directory(initial=True)

    def _submit(self, operation, completed):
        def finish(value, error):
            self._requests.discard(result)
            if error is not None:
                self.show_message(ui_text('watch.request_error'))
            completed(value, error)

        result = _Result(finish)
        self._requests.add(result)
        self.destroyed.connect(result.cancel)
        QThreadPool.globalInstance().start(_Request(operation, result))

    def refresh_directory(self, *, initial=False):
        generation = self._generation

        def fetch():
            return self.facade.symbol_directory(), self.facade.market_preferences(), self.facade.market_status()

        def completed(value, error):
            if error is None:
                items, selected, self._terminal_status = value
                self._directory = tuple({item.instrument_id: item for item in (*FIXED_INDICES, *items)}.values())
                self._ready = True
                if initial and generation == self._generation:
                    self.select_instrument(selected or self.current_instrument)
                else:
                    self.render(self.state)

        self._submit(fetch, completed)

    def _view(self, key):
        return next((item for item in self.state.market_watch if item.instrument_id == key), MarketWatchView(instrument_id=key))

    def _market_environment(self):
        settings = self.state.market_data_settings
        return settings.environment if settings.enabled else self.state.environment

    def render(self, state):
        was_connected = self.state.market_connection == 'CONNECTED'
        self.state = state
        directory = {item.instrument_id: item for item in self._directory}
        render_quote_table(self, self.table, [directory[key] for key in state.watchlist if key in directory])
        render_quote_table(self, self.index_table, FIXED_INDICES)
        view = self._view(self.current_instrument)
        instrument = directory.get(self.current_instrument)
        name = instrument.code + ' ' + instrument.name if instrument is not None else self.current_instrument
        freshness = ui_text('terminal.history_only') if self._history_only else state_label(view.health.freshness)
        self.title.setText(
            ' '.join(
                (
                    name,
                    price_number(view.price if view.health.freshness != 'UNKNOWN' else None, instrument, view.price_tick),
                    number(view.change, signed=True),
                    number(view.change_percent, signed=True, percent=True),
                )
            )
        )
        self.freshness.setText(ui_text('terminal.state_dot') + ' ' + freshness)
        self.freshness.setStyleSheet('color:' + {'LIVE': '#238636', 'DELAYED': '#a66b00'}.get(view.health.freshness, '#808080'))
        self.title.setStyleSheet('color:' + self._colour(view).name())
        self.toggle_watch.setText(ui_text('terminal.remove_watch') if self.current_instrument in state.watchlist else ui_text('terminal.add_watch'))
        self.toggle_watch.setAccessibleName(self.toggle_watch.text())
        self.toggle_watch.setEnabled(self.current_instrument not in {item.instrument_id for item in FIXED_INDICES})
        self.search.offline.setVisible(state.market_connection != 'CONNECTED')
        index = self._view(FIXED_INDICES[0].instrument_id)
        self.index_title.setText(
            ' '.join(
                (ui_text('terminal.taiex'), number(index.price), number(index.change, signed=True), number(index.change_percent, signed=True, percent=True))
            )
        )
        self.index_title.setStyleSheet('color:' + self._colour(index).name())
        self.history_error.setText(ui_text('watch.history_error').format(view.health.history_error) if view.health.history_error else '')
        self.retry.setVisible(bool(view.health.history_error))
        self._render_status()
        if state.market_connection == 'CONNECTED' and not was_connected:
            self.refresh_directory()
        if self._ready and not self._series_loading and not self._selecting:
            self.load_series()

    def sort_quotes(self, table, column):
        previous = self._sorts.get(table)
        order = Qt.SortOrder.DescendingOrder if previous == (column, Qt.SortOrder.AscendingOrder) else Qt.SortOrder.AscendingOrder
        self._sorts[table] = column, order
        table.horizontalHeader().setSortIndicatorShown(True)
        table.sortItems(column, order)

    def _colour(self, view):
        up, down = self.colours(self)
        return QColor(
            up if view.change is not None and view.change > 0 else down if view.change is not None and view.change < 0 else self.palette().text().color()
        )

    def _render_status(self):
        render_status(self)

    def select_instrument(self, instrument_id, occurred_at=None):
        changed = self.current_instrument != instrument_id or self.period != self.periods.get(instrument_id, '1m')
        self.current_instrument = instrument_id
        self.period = self.periods.get(instrument_id, '1m')
        self._generation += 1
        self._occurred_at = occurred_at
        if self._selecting:
            self._selection_pending = True
            return
        self._selecting = True
        if changed:
            self.chart.set_series(())
            self._last_series = None
        self.render(self.state)
        key, period, generation = self.current_instrument, self.period, self._generation

        def operation():
            accepted = self.facade.select_market_instrument(key, period)
            return accepted, self.facade.snapshot(), self.facade.market_status()

        def completed(value, error):
            self._selecting = False
            if self._selection_pending:
                self._selection_pending = False
                self.select_instrument(self.current_instrument, self._occurred_at)
                return
            if error is None and generation == self._generation:
                accepted, state, self._terminal_status = value
                self._history_only = accepted is False and self._terminal_status.connected
                self.render(state)

        self._submit(operation, completed)

    def select_period(self, period):
        self.periods[self.current_instrument] = period
        self.period = period
        self.select_instrument(self.current_instrument)

    def load_series(self, *, retry=False):
        if self._selecting or not self._ready:
            return
        if self._series_loading:
            self._pending = True
            self._pending_retry = self._pending_retry or retry
            return
        self._series_loading = True
        key, period, generation = self.current_instrument, self.period, self._generation
        for name, item in self.period_buttons.items():
            item.setChecked(name == period)
        self.history_error.setText(ui_text('terminal.history_loading'))

        def fetch():
            page = self.facade.market_series(MarketSeriesQuery(key, period, retry_history=retry))
            bars = page.bars
            while page.next_offset is not None:
                page = self.facade.market_series(MarketSeriesQuery(key, period, offset=page.next_offset, market_revision=page.market_revision))
                bars += page.bars
            index = self.facade.market_series(MarketSeriesQuery(FIXED_INDICES[0].instrument_id, '1m'))
            if index.next_offset is not None:
                index = self.facade.market_series(
                    MarketSeriesQuery(index.instrument_id, '1m', offset=max(0, index.total - len(index.bars)), market_revision=index.market_revision)
                )
            return replace(page, bars=bars, offset=0), index, self.facade.market_status()

        def completed(value, error):
            self._series_loading = False
            if error is None and generation == self._generation:
                page, index, self._terminal_status = value
                render_chart(self, page)
                self._focus_event()
                latest = index.bars[-1].trade_date if index.bars else None
                self.index_chart.set_series(
                    series_bars(replace(index, bars=tuple(bar for bar in index.bars if bar.trade_date == latest))),
                    source_label=source_text(self._market_environment()),
                    status_label=state_label(self._view(index.instrument_id).health.freshness),
                )
                history = self._terminal_status.history_state
                error_code = dict(history.history_error).get(key, '')
                self.history_error.setText(
                    ui_text('watch.history_error').format(error_code) if error_code else ui_text('terminal.history_loading') if history.running == key else ''
                )
                self.retry.setVisible(bool(error_code))
                self._render_status()
            elif error is not None:
                self.history_error.setText(ui_text('watch.request_error'))
                self.retry.show()
            elif generation != self._generation:
                self._pending = True
            if self._pending:
                self._pending = False
                pending_retry, self._pending_retry = self._pending_retry, False
                self.load_series(retry=pending_retry)

        self._submit(fetch, completed)

    def _focus_event(self):
        if self._occurred_at is None:
            return
        for index, bar in enumerate(self.chart.bars):
            if bar.start <= self._occurred_at < bar.end:
                self.chart._start = max(0, index - self.chart._count // 2)
                self.chart.crosshair_index = index
                self.chart.update()
                break
        self._occurred_at = None

    def toggle_current_watch(self):
        key = self.current_instrument
        watches = self.state.watchlist
        if key in watches:
            self._save_watchlist(tuple(item for item in watches if item != key))
        else:
            limit = self.state.market_health.subscription_limit - 2
            if len(watches) >= limit:
                self.show_message(ui_text('terminal.watch_full').format(limit))
                return
            self._save_watchlist((*watches, key))

    def _save_watchlist(self, watches):
        if self._busy:
            return
        self._busy = True
        command = UiCommand(
            UiAction.SAVE_SETTINGS, self.state.version, watchlist=watches, context_id=self.state.context_id, context_epoch=self.state.context_epoch
        )

        def operation():
            receipt = self.facade.execute(command)
            return receipt, self.facade.snapshot() if receipt.accepted else None

        def completed(value, error):
            self._busy = False
            if error is None:
                receipt, state = value
                if state is not None:
                    self.render(state)
                    self.select_instrument(self.current_instrument)
                else:
                    self.show_message(receipt.message)

        self._submit(operation, completed)

    def _context_menu(self, point):
        item = self.table.itemAt(point)
        if item is None:
            return
        key = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(ui_text('terminal.remove_watch'), lambda: self._save_watchlist(tuple(value for value in self.state.watchlist if value != key)))
        for step, text in ((-1, ui_text('terminal.up')), (1, ui_text('terminal.down'))):
            menu.addAction(text, lambda checked=False, selected=step: self._move_watch(key, selected))
        menu.exec(self.table.viewport().mapToGlobal(point))

    def _move_watch(self, key, step):
        watches = list(self.state.watchlist)
        index = watches.index(key)
        watches.insert(max(0, min(len(watches) - 1, index + step)), watches.pop(index))
        self._save_watchlist(tuple(watches))

    def show_message(self, text):
        self.message.setText(text)
        self.message_timer.start()

    def show_diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(ui_text('terminal.diagnostics'))
        layout = QVBoxLayout(dialog)
        detail = QLabel(diagnostic_text(self._view(self.current_instrument), self._market_environment()))
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detail)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def eventFilter(self, watched, event):
        if watched is self.index_chart and event.type() == QEvent.Type.MouseButtonRelease:
            self.select_instrument(FIXED_INDICES[0].instrument_id)
        return super().eventFilter(watched, event)
