from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem
from quantlab.market import MarketSeries
from desktop_app.features.market.rows import _friendly_contract


class MarketPresenter:
    def __init__(self, view):
        self.view = view

    def set_market_series(self, series, *, stale=False, error=''):
        """Replace a validated snapshot atomically; called by host on GUI thread."""
        items = (series,) if isinstance(series, MarketSeries) else tuple(series)
        if any((not isinstance(item, MarketSeries) for item in items)) or len(items) > 1000 or type(stale) is not bool or (not isinstance(error, str)):
            raise ValueError('invalid market snapshot')
        ids = [item.instrument.contract_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate contract')
        self.view._series = dict(zip(ids, items))
        self.view._stale = stale
        self.view._error = error[:1000]
        if not self.view._selected and ids:
            self.view._selected = ids[0]
        if not self.view._watch_initialized and ids:
            self.view._watch = [self.view._selected] if self.view._selected in ids else [ids[0]]
            self.view._watch_initialized = True
        self.view._fill_contracts()
        self.view._filter_catalog()
        self.view._render_watch()
        self.view._render_cards()
        self.view._render_chart()

    def set_quote_series(self, series, *, stale=False):
        """Set independent card observations; historical chart selection is untouched.

        The host supplies its latest verified snapshot. An empty tuple clears cards
        rather than falling back to an older research chart. No reference prices
        are invented and explicit contract identity remains mandatory.
        """
        items = (series,) if isinstance(series, MarketSeries) else tuple(series)
        if any((not isinstance(item, MarketSeries) for item in items)) or len(items) > 1000 or type(stale) is not bool:
            raise ValueError('invalid market-card snapshot')
        ids = [item.instrument.contract_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate market-card contract')
        self.view._quote_series = dict(zip(ids, items))
        self.view._quote_stale = stale
        self.view._render_cards()

    def selected_series(self):
        """Immutable source snapshot for host provenance checks, or None."""
        return self.view._series.get(self.view._selected)

    def set_loading(self, loading):
        if type(loading) is not bool:
            raise ValueError('loading must be boolean')
        self.view.refresh_button.setEnabled(not loading)
        self.view.refresh_button.setText(ui_text('market.set_loading.updating') if loading else ui_text('market.set_loading.update_official'))

    def _fill_contracts(self):
        self.view.contract_combo.blockSignals(True)
        self.view.contract_combo.clear()
        for key, item in self.view._series.items():
            self.view.contract_combo.addItem(_friendly_contract(key), key)
        self.view.contract_combo.setCurrentIndex(self.view.contract_combo.findData(self.view._selected))
        self.view.contract_combo.blockSignals(False)

    def _filter_catalog(self):
        terms = self.view.search.text().upper().split()
        self.view.catalog_combo.clear()
        for key, item in self.view._series.items():
            label = _friendly_contract(key)
            searchable = f'{label} {item.instrument.symbol} {key}'
            if all((term in searchable.upper() for term in terms)):
                self.view.catalog_combo.addItem(label, key)
        self.view.add_button.setEnabled(self.view.catalog_combo.count() > 0)

    def _render_watch(self):
        self.view.watchlist.blockSignals(True)
        self.view.watchlist.clear()
        for key in self.view._watch:
            text = _friendly_contract(key) + (ui_text('market.render_watch.no_data_suffix') if key not in self.view._series else '')
            item = QListWidgetItem(text)
            item.setToolTip(key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.view.watchlist.addItem(item)
            if key == self.view._selected:
                self.view.watchlist.setCurrentItem(item)
        self.view.watchlist.blockSignals(False)

    def _add_watch(self):
        key = self.view.catalog_combo.currentData()
        if key and key not in self.view._watch and (len(self.view._watch) < 100):
            self.view._watch.append(key)
            self.view._render_watch()
            self.view.preferences_changed.emit()

    def _remove_watch(self):
        row = self.view.watchlist.currentRow()
        if row >= 0:
            self.view._watch.pop(row)
            self.view._render_watch()
            self.view.preferences_changed.emit()

    def _move_watch(self, delta):
        row = self.view.watchlist.currentRow()
        target = row + delta
        if 0 <= row < len(self.view._watch) and 0 <= target < len(self.view._watch):
            self.view._watch[row], self.view._watch[target] = (self.view._watch[target], self.view._watch[row])
            self.view._render_watch()
            self.view.watchlist.setCurrentRow(target)
            self.view.preferences_changed.emit()

    def _watch_selected(self, item, previous):
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            if key in self.view._series:
                self.view.contract_combo.setCurrentIndex(self.view.contract_combo.findData(key))
            else:
                self.view.message.setText(ui_text('market.watch_selected.contract_unavailable'))

    def _contract_changed(self, index):
        key = self.view.contract_combo.itemData(index)
        if key:
            self.view._prepare_chart_memory().capture(self.view, switching=True)
            self.view._selected = key
            self.view._render_chart()
            self.view._render_cards()
            self.view.selection_changed.emit(key)
            self.view.preferences_changed.emit()

    def _timeframe_changed(self, index):
        value = self.view.timeframe_combo.itemData(index)
        current = self.view._series.get(self.view._selected)
        if current and value.endswith('m') and any((not bar.interval.endswith('m') for bar in current.bars)):
            self.view.timeframe_combo.blockSignals(True)
            self.view.timeframe_combo.setCurrentIndex(self.view.timeframe_combo.findData(self.view._timeframe))
            self.view.timeframe_combo.blockSignals(False)
            self.view.message.setText(ui_text('market.timeframe_changed.minute_data_required'))
            return
        self.view._prepare_chart_memory().capture(self.view, switching=True)
        self.view._timeframe = value
        self.view._render_chart()
        self.view.preferences_changed.emit()
