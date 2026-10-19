"""Saved-result selection and side-by-side presentation; no research operations."""

from datetime import datetime, timezone
import re

from PySide6.QtCore import Qt
from desktop_forms import PARAM_LABELS
from desktop_presentation import display_number, display_status, result_name
from desktop_strings import ui_text
from .result_widgets import ResultTable, MISSING, shown, taipei_time, column_label


FIELDS = ('name', 'family', 'parameters', 'range', 'created', 'net_pnl', 'profit_factor', 'sharpe', 'max_drawdown', 'trade_count')
PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def safe_text(value):
    return re.sub(r'[0-9a-fA-F]{8,}', ui_text('presentation.result_name.text_3'), str(value))


def saved_row(result, created):
    manifest = result.manifest
    spec = manifest.get('strategy', {})
    coverage = manifest.get('dataset_manifest', {}).get('coverage', {})
    dates = [str(coverage.get(key, ''))[:10] for key in ('start', 'end')]
    if not all(dates):
        dates = [str(row.get('timestamp', row.get('trade_date', '')))[:10] for row in result.equity]
    metrics = getattr(result, 'metrics', {})
    row = {key: metrics[key] for key in FIELDS if key in metrics}
    if 'trade_count' not in row and 'closed_trades' in metrics:
        row['trade_count'] = metrics['closed_trades']
    row.update(
        name=result_name(result, created),
        family=display_status(spec.get('family', '')),
        parameters=' / '.join(PARAM_LABELS.get(key, key) + '=' + display_number(value) for key, value in spec.get('parameters', {}).items())
        or ui_text('presentation.result_name.text_2'),
        range=ui_text('presentation.result_name.text_4').format(dates[0], dates[-1]) if dates else ui_text('presentation.result_name.text_5'),
        created=taipei_time(datetime.fromtimestamp(created, timezone.utc)),
    )
    return row


class SavedResultsTable(ResultTable):
    """Keep the legacy QListWidget as a hidden, bidirectional selection adapter."""

    def __init__(self, legacy):
        super().__init__()
        self.legacy = legacy
        legacy.table = self
        self.setObjectName('saved_results_table')
        self.setAccessibleName(ui_text('compare.saved'))
        self.setMinimumHeight(180)
        self.setMaximumHeight(220)
        self.itemChanged.connect(self._checked)
        legacy.itemSelectionChanged.connect(self._legacy_selected)
        self.set_saved([])

    def set_saved(self, records):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.legacy.selectedItems()}
        blocked = self.blockSignals(True)
        try:
            self.set_rows([row for path, row in records], FIELDS)
            self.setSortingEnabled(False)
            self.setHorizontalHeaderLabels([ui_text('compare.' + key) if key in FIELDS[:5] else column_label(key) for key in FIELDS])
            for r, (path, row) in enumerate(records):
                for c in range(self.columnCount()):
                    item = self.item(r, c)
                    item.setText(safe_text(item.text()))
                    item.setToolTip(str(path) + '\n' + item.toolTip())
                item = self.item(r, 0)
                item.setData(PATH_ROLE, path)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if path in selected else Qt.CheckState.Unchecked)
            self.setSortingEnabled(True)
            self.setColumnWidth(0, 260)
        finally:
            self.blockSignals(blocked)

    def _checked(self, item):
        if item.column() != 0:
            return
        path = item.data(PATH_ROLE)
        for index in range(self.legacy.count()):
            old = self.legacy.item(index)
            if old.data(Qt.ItemDataRole.UserRole) == path:
                old.setSelected(item.checkState() == Qt.CheckState.Checked)

    def _legacy_selected(self):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.legacy.selectedItems()}
        blocked = self.blockSignals(True)
        try:
            for r in range(self.rowCount()):
                item = self.item(r, 0)
                item.setCheckState(Qt.CheckState.Checked if item.data(PATH_ROLE) in selected else Qt.CheckState.Unchecked)
        finally:
            self.blockSignals(blocked)


class SideBySideTable(ResultTable):
    def __init__(self, saved):
        super().__init__()
        self.saved = saved
        self.setMinimumHeight(160)
        self.setMaximumHeight(200)

    def set_rows(self, rows, columns=None, formats=None):
        rows = list(rows)
        keys = ('net_pnl', 'profit_factor', 'sharpe', 'max_drawdown', 'trade_count')
        names = []
        for index, row in enumerate(rows):
            digest = str(row.get('result_hash', ''))
            label = next(
                (self.saved.item(r, 0).text() for r in range(self.saved.rowCount()) if digest and digest in str(self.saved.item(r, 0).data(PATH_ROLE))),
                ui_text('compare.result').format(index + 1),
            )
            names.append(safe_text(label))
        display = [
            {
                'metric': column_label(key),
                **{str(i): shown(row.get(key, row.get('closed_trades', MISSING) if key == 'trade_count' else MISSING), key) for i, row in enumerate(rows)},
            }
            for key in keys
        ]
        super().set_rows(display, ['metric'] + [str(i) for i in range(len(rows))])
        self.setHorizontalHeaderLabels([ui_text('compare.metric')] + names)
        for c, row in enumerate(rows, 1):
            for r, key in enumerate(keys):
                self.item(r, c).setToolTip(str(row.get(key, '')) + '\n' + str(row.get(key + '_reason', '')))
