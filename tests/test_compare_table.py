"""Compare saved reports without changing admission or result semantics."""

import copy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton
from desktop_app.features.compare.compare_table import FIELDS, SavedResultsTable, SideBySideTable, saved_row
from desktop_app.strings.catalog import ui_text
from tests import test_desktop_pages


def report(metrics):
    return SimpleNamespace(
        manifest={
            'strategy': {'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}},
            'dataset_manifest': {'coverage': {'start': '2026-01-01', 'end': '2026-01-31'}},
        },
        equity=[],
        metrics=metrics,
    )


class CompareTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.legacy = QListWidget()
        self.legacy.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.table = SavedResultsTable(self.legacy)
        self.records = []
        for index, metrics in enumerate(({'net_pnl': '100', 'profit_factor': None}, {'net_pnl': '2', 'profit_factor': 0, 'trade_count': 0}, {})):
            path = str(Path('reports') / (str(index) * 64) / 'result.json')
            self.legacy.addItem('legacy')
            self.legacy.item(index).setData(Qt.ItemDataRole.UserRole, path)
            self.records.append((path, saved_row(report(metrics), 0)))
        self.table.set_saved(self.records)

    def tearDown(self):
        self.table.close()
        self.legacy.close()

    def test_one_row_per_result_columns_readable_name_and_taipei(self):
        self.assertEqual(self.table.rowCount(), 3)
        self.assertEqual(self.table.columnCount(), 10)
        self.assertIn('台北', self.table.horizontalHeaderItem(4).text())
        self.assertIn('描述', self.table.horizontalHeaderItem(7).text())
        self.assertIn('趨勢', self.table.item(0, 0).text())
        self.assertIn('fast=5', self.table.item(0, 0).text())
        self.assertEqual(self.table.item(0, 4).text(), '1970-01-01 08:00:00')
        self.assertIn('2026-01-31', self.table.item(0, 3).text())
        for r in range(3):
            for c in range(10):
                self.assertNotRegex(self.table.item(r, c).text(), r'[a-fA-F0-9]{8,}')
        self.assertIn('0' * 64, self.table.item(0, 0).toolTip())

    def test_numeric_sort_checks_follow_ids_and_legacy_selection(self):
        self.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.table.sortItems(FIELDS.index('net_pnl'), Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.table.item(0, 5).text(), '2 TWD')
        self.assertEqual(self.table.item(1, 5).text(), '100 TWD')
        self.assertEqual(self.table.item(1, 0).checkState(), Qt.CheckState.Checked)
        self.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual({i.data(Qt.ItemDataRole.UserRole) for i in self.legacy.selectedItems()}, {p for p, row in self.records[:2]})
        self.legacy.item(0).setSelected(False)
        self.assertEqual(self.table.item(1, 0).checkState(), Qt.CheckState.Unchecked)

    def test_missing_undefined_zero_and_source_unchanged(self):
        self.assertEqual(self.table.item(0, 6).text(), ui_text('forms.metric.undefined'))
        self.assertEqual(self.table.item(1, 6).text(), '0')
        self.assertEqual(self.table.item(2, 6).text(), ui_text('forms.metric.not_provided'))
        self.assertEqual(self.table.item(1, 9).text(), '0')
        source = report({'sharpe': None})
        before = copy.deepcopy(source)
        saved_row(source, 0)
        self.assertEqual(source, before)

    def test_side_by_side_uses_readable_names_and_keeps_undefined_reasons(self):
        table = SideBySideTable(self.table)
        table.set_rows([{'result_hash': '0' * 64, 'profit_factor': None, 'profit_factor_reason': 'no closed lots'}, {'net_pnl': 0}])
        self.assertEqual(table.columnCount(), 3)
        self.assertEqual(table.rowCount(), 5)
        self.assertIn('趨勢', table.horizontalHeaderItem(1).text())
        self.assertEqual(table.item(1, 1).text(), ui_text('forms.metric.undefined'))
        self.assertIn('no closed lots', table.item(1, 1).toolTip())
        self.assertEqual(table.item(1, 2).text(), ui_text('forms.metric.not_provided'))
        self.assertEqual(table.item(0, 2).text(), '0 TWD')
        table.close()


class CompareHostTests(unittest.TestCase):
    setUpClass = classmethod(test_desktop_pages.PageInteractionTests.setUpClass.__func__)
    setUp = test_desktop_pages.PageInteractionTests.setUp
    tearDown = test_desktop_pages.PageInteractionTests.tearDown

    def test_saved_reports_refresh_checkboxes_dispatch_original_payload(self):
        w = self.window
        paths = []
        for digit in ('a', 'b'):
            path = self.paths.state / 'reports' / (digit * 64) / 'result.json'
            path.parent.mkdir(parents=True)
            path.write_text('{}', encoding='utf-8')
            paths.append(str(path))
        with patch('desktop_app.shell.main_window.load_result', return_value=report({'net_pnl': '20'})), patch.object(w, 'show_result'):
            w.refresh_views()
            table = w.compare_page.saved_results_table
            self.assertEqual(table.rowCount(), 2)
            table.item(1, 0).setCheckState(Qt.CheckState.Checked)
            with patch.object(w.page_host, 'start_job', return_value='job') as start:
                w.findChild(QPushButton, 'compare_results').click()
                start.assert_called_once_with('ui_compare', {'results': [paths[1]]})
            w.refresh_views()
            self.assertEqual(table.item(1, 0).checkState(), Qt.CheckState.Checked)
        w.show()
        w.navigation.setCurrentRow(3)
        self.app.processEvents()
        self.assertFalse(w.comparison.isVisible())
        self.assertFalse(w.comparison_list.isVisible())
        self.assertLessEqual(w.compare_page.sizeHint().height(), 768)

    def test_snapshot_page_and_each_strategy_tab_meet_height_limit(self):
        from tools.ui_snapshot import page_metrics, tab_heights

        w = self.window
        w.resize(1366, 768)
        w.show()
        w.navigation.setCurrentRow(3)
        self.app.processEvents()
        self.assertLessEqual(page_metrics(w.compare_page)['page_height'], 768)
        w.navigation.setCurrentRow(1)
        self.app.processEvents()
        heights = tab_heights(w.strategy_page, self.app)
        self.assertEqual(len(heights), 3)
        self.assertTrue(all(height <= 1100 for height in heights.values()), heights)


if __name__ == '__main__':
    unittest.main()
