"""Small, in-memory C9 presentation checks; baseline roles are frozen at e0e604f."""

from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QListWidget, QStackedWidget, QTabWidget, QVBoxLayout

import desktop_app.components.privacy as privacy
import desktop_app.shell.theme as theme
from desktop_app.features.compare.compare_table import FIELDS, SavedResultsTable, SideBySideTable
from desktop_app.features.settings.log_table import LogTable
from desktop_app.features.paper.paper import PaperPage
from desktop_app.components.result_widgets import ResultTable, bind_tab_count
from desktop_app.components.widgets import WidgetTools
from desktop_app.components.formatting import display_number
from desktop_app.strings.catalog import ui_text
from quantlab.paper import RiskLimits
from shiboken6 import delete


def fixture_rows():
    return [
        {
            'name': 'Alpha',
            'family': 'trend',
            'parameters': 'fast=5',
            'range': '2026-01',
            'created': '2026-01-01 08:00:00',
            'net_pnl': Decimal('123456789.123456789'),
            'profit_factor': Decimal('1.23456789'),
            'sharpe': None,
            'max_drawdown': Decimal('-0.125'),
            'trade_count': 12,
        },
        {'name': 'Beta', 'net_pnl': Decimal('-2.50'), 'profit_factor': None, 'sharpe': Decimal('0'), 'trade_count': 0},
        {'name': 'Gamma', 'net_pnl': Decimal('0'), 'profit_factor': Decimal('0')},
    ]


def cell_values(table):
    return {
        'headers': [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())],
        'cells': [
            [
                [table.item(r, c).text(), table.item(r, c).data(Qt.ItemDataRole.DisplayRole), table.item(r, c).data(Qt.ItemDataRole.UserRole)]
                for c in range(table.columnCount())
            ]
            for r in range(table.rowCount())
        ],
    }


class TableReadabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def keep(self, widget):
        self.addCleanup(widget.deleteLater)
        return widget

    def tables(self):
        legacy = self.keep(QListWidget())
        legacy.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        saved = self.keep(SavedResultsTable(legacy))
        rows = fixture_rows()
        for index in range(len(rows)):
            legacy.addItem(str(index))
            legacy.item(index).setData(Qt.ItemDataRole.UserRole, str(index))
        saved.set_saved([(str(i), row) for i, row in enumerate(rows)])
        side = self.keep(SideBySideTable(saved))
        side.set_rows(rows)
        logs = self.keep(LogTable())
        logs.load([json.dumps({'time': 1704067200, 'operation': 'ui_demo', 'event': event}) for event in ('result', 'error')])
        return saved, side, logs

    def test_display_sort_roles_and_headers_match_baseline_bytes(self):
        actual = json.dumps([cell_values(table) for table in self.tables()], ensure_ascii=True, default=str, sort_keys=True, indent=2) + '\n'
        expected = (Path(__file__).parent / 'fixtures' / 'table_values_e0e604f.json').read_bytes().replace(b'\r\n', b'\n')  # autocrlf-safe
        self.assertEqual(actual.encode('utf-8'), expected)

    def test_column_types_align_cells_and_headers_including_missing_values(self):
        for table, numeric_columns in zip(self.tables(), (set(range(5, 10)), {1, 2, 3}, set())):
            for c in range(table.columnCount()):
                numeric = c in numeric_columns
                expected = (Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
                for item in [table.horizontalHeaderItem(c)] + [table.item(r, c) for r in range(table.rowCount())]:
                    self.assertEqual(item.textAlignment(), expected)
                    if numeric:
                        self.assertEqual(item.font().family(), theme.NUMERIC_FONT_FAMILY)
                        self.assertTrue(item.font().fixedPitch())

    def test_financial_sign_colors_both_conventions_and_themes(self):
        saved, side, _ = self.tables()
        for name in theme.THEMES:
            for convention in theme.CONVENTIONS:
                for table in (saved, side):
                    table.setProperty('appearanceTheme', name)
                    table.setProperty('appearanceConvention', convention)
                    theme.apply_theme(table)
                pair = theme.up_down_colors(convention, theme=name, context='market')
                for r, row in enumerate(fixture_rows()):
                    sign = theme.financial_sign(row['net_pnl'])
                    expected = QColor(pair[0 if sign > 0 else 1] if sign else theme.THEMES[name]['text'])
                    for item in (saved.item(r, 5), side.item(0, r + 1)):
                        self.assertEqual(item.data(theme.SIGN_ROLE), sign)
                        self.assertEqual(item.foreground().color(), expected)

    def test_privacy_keeps_alignment_and_hides_money_tooltips(self):
        saved, side, _ = self.tables()
        for table in (saved, side):
            table.privacy = SimpleNamespace(enabled=True)
            for r in range(table.rowCount()):
                for c in range(table.columnCount()):
                    privacy.refresh_item(table, table.item(r, c))
            item = table.item(0, 5) if table is saved else table.item(0, 1)
            self.assertEqual(item.text(), privacy.mask_money(''))
            self.assertEqual(item.toolTip(), privacy.mask_money(''))
            self.assertEqual(item.textAlignment(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.privacy.enabled = False
            privacy.refresh_item(table, item)
            self.assertNotEqual(item.text(), privacy.mask_money(''))

    def test_sorting_and_checkbox_adapter(self):
        saved, _, _ = self.tables()
        saved.sortItems(FIELDS.index('net_pnl'), Qt.SortOrder.AscendingOrder)
        self.assertEqual(
            [saved.item(r, 5).data(Qt.ItemDataRole.UserRole)[1] for r in range(3)], [Decimal('-2.50'), Decimal('0'), Decimal('123456789.123456789')]
        )
        saved.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual([item.data(Qt.ItemDataRole.UserRole) for item in saved.legacy.selectedItems()], ['1'])

    def test_counts_follow_model_insert_remove_reset_and_empty_without_counter(self):
        tabs = self.keep(QTabWidget())
        table = ResultTable()
        table.setObjectName('existing_table')
        title = ui_text('results.positions')
        tabs.addTab(table, title)
        bind_tab_count(tabs, table)
        for mutate in (
            lambda: None,
            lambda: table.set_rows([{'price': Decimal('1.25')}]),
            lambda: table.insertRow(0),
            lambda: table.removeRow(0),
            lambda: table.setRowCount(0),
            lambda: table.set_rows([{}, {}, {}]),
        ):
            mutate()
            self.assertEqual(tabs.tabText(0), ui_text('tables.tab_count').format(title, display_number(table.rowCount())))
            self.assertEqual(tabs.indexOf(table), 0)
            self.assertEqual(table.objectName(), 'existing_table')
        self.assertEqual(tabs.tabBar().elideMode(), Qt.TextElideMode.ElideNone)

    def test_paper_existing_tabs_count_rows_with_bare_host(self):
        host = SimpleNamespace(
            state=SimpleNamespace(_section_toggles={}, _advanced_values={}, actions=[], stack=self.keep(QStackedWidget())),
            callbacks={'paper_risk_limits': lambda: RiskLimits(1, 1, Decimal('100'), 30)},
            mount_page=lambda page, title: QVBoxLayout(page),
        )
        tools = WidgetTools(host)
        for name in ('_advanced', '_button', '_text', '_remember'):
            setattr(host, name, getattr(tools, name))
        page = self.keep(PaperPage(host))
        tabs = page.findChild(QTabWidget)
        for index, (table, title) in enumerate(
            zip(
                (page.positions_table, page.orders_table, page.account_fills_table),
                (ui_text('results.positions'), ui_text('results.orders'), ui_text('results.fills')),
            )
        ):
            self.assertIs(tabs.widget(index), table)
            self.assertEqual(tabs.tabText(index), ui_text('tables.tab_count').format(title, display_number(0)))
            table.insertRow(0)
            self.assertEqual(tabs.tabText(index), ui_text('tables.tab_count').format(title, display_number(1)))
            table.removeRow(0)
            self.assertEqual(tabs.tabText(index), ui_text('tables.tab_count').format(title, display_number(0)))

    def test_tab_destruction_does_not_call_deleted_widgets(self):
        tabs = QTabWidget()
        table = ResultTable()
        tabs.addTab(table, ui_text('results.positions'))
        bind_tab_count(tabs, table)
        table.set_rows([{'price': Decimal('1.25')}])
        with patch('sys.excepthook') as errors:
            delete(tabs)
        errors.assert_not_called()


if __name__ == '__main__':
    unittest.main()
