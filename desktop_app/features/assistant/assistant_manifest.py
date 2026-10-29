"""Read-only manifest details inside the existing collapsed assistant area."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from desktop_app.strings.catalog import ui_text
from quantlab.errors import ERROR_TABLE


def field_label(field):
    labels = {
        'spec_hash': ui_text('manifest.strategy_revision'),
        'data_hash': ui_text('manifest.data_hash'),
        'cost_hash': ui_text('manifest.cost_hash'),
        'engine_version': ui_text('manifest.engine_version'),
        'commission_per_side': ui_text('manifest.commission'),
        'tax_rate': ui_text('manifest.tax_rate'),
        'slippage_ticks': ui_text('manifest.slippage'),
        'tax_rounding': ui_text('manifest.rounding'),
        'effective_from': ui_text('manifest.effective_from'),
    }
    parts = field.split('.')
    label = labels.get(parts[-1], ui_text('manifest.not_recorded'))
    return ui_text('manifest.schedule').format(parts[1], label) if parts[0] == 'cost_schedule' else label


class ManifestDetails(QWidget):
    def __init__(self, dispatcher, parent=None):
        super().__init__(parent)
        self.dispatcher = dispatcher
        self.arguments = {}
        self.cursor = None
        layout = QVBoxLayout(self)
        self.title = QLabel(ui_text('manifest.title'))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        self.refresh_button = QPushButton(ui_text('manifest.refresh'))
        layout.addWidget(self.refresh_button)
        self.left, self.right = QComboBox(), QComboBox()
        self.left.setAccessibleName(ui_text('manifest.left'))
        self.right.setAccessibleName(ui_text('manifest.right'))
        layout.addWidget(self.left)
        layout.addWidget(self.right)
        self.read = QPushButton(ui_text('manifest.read'))
        self.compare = QPushButton(ui_text('manifest.compare'))
        layout.addWidget(self.read)
        layout.addWidget(self.compare)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                ui_text('manifest.field'),
                ui_text('manifest.left'),
                ui_text('manifest.right'),
                ui_text('manifest.status'),
                ui_text('manifest.warning'),
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAccessibleName(ui_text('manifest.title'))
        layout.addWidget(self.table)
        self.more = QPushButton(ui_text('manifest.next'))
        self.more.setEnabled(False)
        layout.addWidget(self.more)
        self.refresh_button.clicked.connect(self.refresh)
        self.read.clicked.connect(lambda: self.load(False))
        self.compare.clicked.connect(lambda: self.load(True))
        self.more.clicked.connect(self.next_page)
        self.left.currentIndexChanged.connect(self.clear)
        self.right.currentIndexChanged.connect(self.clear)
        for name, widget in (
            ('manifest_details', self),
            ('manifest_refresh', self.refresh_button),
            ('manifest_left', self.left),
            ('manifest_right', self.right),
            ('manifest_read', self.read),
            ('manifest_compare', self.compare),
            ('manifest_table', self.table),
            ('manifest_next', self.more),
        ):
            widget.setObjectName(name)

    def clear(self, *_):
        self.table.setRowCount(0)
        self.cursor = None
        self.more.setEnabled(False)
        self.title.setText(ui_text('manifest.title'))

    def failure(self, page):
        self.clear()
        code = page.get('error', {}).get('code', 'agent_tool_refused')
        self.title.setText(ERROR_TABLE.get(code, ERROR_TABLE['agent_tool_refused']).explanation)

    def refresh(self):
        self.clear()
        self.left.clear()
        self.right.clear()
        page = self.dispatcher.call('list_saved_results', '{}')
        if not page.get('ok'):
            self.failure(page)
            return
        for row in page['items']:
            self.left.addItem(row['id'], row['id'])
            self.right.addItem(row['id'], row['id'])
        if page.get('truncated'):
            self.title.setText(ui_text('manifest.catalog_truncated'))

    def load(self, compare=False):
        self.clear()
        self.tool = 'compare_result_manifests' if compare else 'get_result_manifest'
        self.arguments = {'result_id': self.left.currentData()}
        if compare:
            self.arguments['other_id'] = self.right.currentData()
        self.next_page()

    def next_page(self):
        arguments = {**self.arguments}
        if self.cursor:
            arguments['cursor'] = self.cursor
        page = self.dispatcher.call(self.tool, json.dumps(arguments))
        if not page.get('ok'):
            self.failure(page)
            return
        self.table.setRowCount(len(page['items']))
        for index, row in enumerate(page['items']):
            compared = 'left' in row
            values = [
                field_label(row['field']),
                row.get('left') if compared else row['value'],
                row.get('right'),
                (ui_text('manifest.different') if row.get('status') == 'different' else ui_text('manifest.same')) if compared else None,
                ui_text('manifest.non_comparable') if row.get('non_comparable') else None,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(ui_text('manifest.not_recorded') if value is None else str(value))
                if row.get('status') == 'different':
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(index, column, item)
        self.cursor = page['next_cursor']
        self.more.setEnabled(self.cursor is not None)
        self.title.setText(ui_text('manifest.truncated') if page['truncated'] else ui_text('manifest.title'))
