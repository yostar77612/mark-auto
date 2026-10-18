"""Shared result views: exact source semantics, numeric interactions and local time."""
import copy
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from desktop_strings import ui_text
from desktop_pages.result_widgets import ResultTable, KpiCards, TaipeiFillsTable, position_text, taipei_time, shown
from desktop_pages.equity import EquityPlot
from desktop_pages.result_panels import WalkForwardResults
from tests import test_desktop_pages


class ResultWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_numeric_header_sort_and_missing(self):
        table = ResultTable(); table.set_rows([{'v': '1000.5'}, {'v': '-3'}, {'v': '20'}, {'v': None}, {}])
        table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.assertEqual([table.item(i, 0).text() for i in range(3)], ['-3', '20', '1,000.5'])
        table.sortItems(0, Qt.SortOrder.DescendingOrder)
        self.assertEqual([table.item(i, 0).text() for i in range(2, 5)], ['1,000.5', '20', '-3'])
        self.assertTrue(table.isSortingEnabled()); table.close()

    def test_copy_action_and_ctrl_c_include_headers_and_sorted_rows(self):
        table = ResultTable(); table.set_rows([{'a': 10, 'b': 0.125}, {'a': 2, 'b': None}])
        table.sortItems(0); table.show(); table.setFocus(); self.app.processEvents()
        expected = 'a\tb\n2\t' + ui_text('forms.metric.text_1') + '\n10\t0.125'
        self.assertEqual(table.copy_text(), expected)
        QApplication.clipboard().clear(); QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), expected)
        QApplication.clipboard().clear(); table.actions()[0].trigger()
        self.assertEqual(QApplication.clipboard().text(), expected); table.close()

    def test_none_missing_zero_and_bounded_formatting(self):
        self.assertEqual(shown(), ui_text('forms.metric.text_2'))
        self.assertEqual(shown(None), ui_text('forms.metric.text_1'))
        self.assertEqual(shown(0.0), '0')
        self.assertEqual(shown('1234567.123456'), '1,234,567.1235')
        self.assertEqual(shown('0.125', 'return'), '12.50%')
        self.assertEqual(shown('1000000', 'cash'), '1,000,000 TWD')
        self.assertEqual(shown('00123', 'order_id'), '00123')
        self.assertEqual(shown('1e101'), ui_text('presentation.display_number.text_1'))
        self.assertEqual(shown('internal_code', 'profit_factor'), ui_text('presentation.display_number.text_1'))
        table = ResultTable(); table.set_rows([{'x': None}, {}, {'x': 0.0}])
        self.assertEqual([table.item(i, 0).text() for i in range(3)], [ui_text('forms.metric.text_1'), ui_text('forms.metric.text_2'), '0'])
        table.close()

    def test_header_click_sorts_numbers(self):
        table = ResultTable(); table.set_rows([{'v': 100}, {'v': 2}, {'v': 20}]); table.show()
        self.app.processEvents()
        header = table.horizontalHeader()
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 8))
        values = [table.item(i, 0).text() for i in range(3)]
        self.assertIn(values, (['2', '20', '100'], ['100', '20', '2']))
        self.assertGreaterEqual(header.sortIndicatorSection(), 0); table.close()

    def test_kpi_reasons_only_truly_undefined_and_source_unchanged(self):
        card = KpiCards(('profit_factor', 'sharpe'))
        values = {'profit_factor': None, 'profit_factor_reason': 'no closed lots', 'sharpe': 0.0, 'sharpe_reason': 'zero daily-return sample variance'}
        before = copy.deepcopy(values); card.set_values(values)
        self.assertFalse(card.reasons['profit_factor'].isHidden())
        self.assertIn('尚無', card.reasons['profit_factor'].text())
        self.assertTrue(card.reasons['sharpe'].isHidden()); self.assertEqual(card.labels['sharpe'].text(), '0')
        self.assertEqual(values, before)
        card.set_values({}); self.assertTrue(card.reasons['profit_factor'].isHidden())
        self.assertEqual(card.labels['profit_factor'].text(), ui_text('forms.metric.text_2')); card.close()

    def test_positions_and_taipei_fill_adapter(self):
        self.assertEqual(position_text(-2), '空單 2 口'); self.assertEqual(position_text(3), '多單 3 口')
        self.assertEqual(position_text(0), '空手（無持倉）')
        self.assertEqual(taipei_time('2024-01-01T00:00:00Z'), '2024-01-01 08:00:00')
        self.assertEqual(taipei_time('2024-01-01T00:00:00'), ui_text('forms.set_rows.text_5'))
        table = TaipeiFillsTable(); rows = [{'timestamp': '2024-01-01T00:00:00Z', 'price': '10000', 'quantity': 10, 'fill_id': 'f'}, {'quantity': 2}]
        before = copy.deepcopy(rows); table.set_rows(rows)
        self.assertEqual(table.item(0, 0).text(), '2024-01-01 08:00:00')
        self.assertIn('f', table.item(0, 0).toolTip()); table.sortItems(3)
        self.assertEqual(table.item(0, 3).text(), '2'); self.assertEqual(rows, before); table.close()

    def test_chart_time_axis_hover_and_shared_drawdown(self):
        plot = EquityPlot(); plot.resize(800, 340)
        rows = [{'timestamp': '2024-01-01T00:00:00Z', 'equity': '100'}, {'timestamp': '2024-01-02T00:00:00Z', 'equity': '80'}, {'timestamp': '2024-01-04T00:00:00Z', 'equity': '120'}]
        plot.set_values(rows)
        self.assertEqual(plot.drawdowns, [0, -0.2, 0]); xs = plot.x_positions()
        self.assertAlmostEqual((xs[1] - xs[0]) / (xs[2] - xs[0]), 1/3)
        self.assertEqual(plot.value_at(xs[1]), (rows[1]['timestamp'], 80.0))
        self.assertIn('2024-01-01', plot.axis_labels()['time'][0]); self.assertIn('-20.00%', plot.axis_labels()['drawdown'])
        self.assertEqual(len(plot.axis_labels()['value']), 3)
        plot.show(); QTest.mouseMove(plot, QPoint(int(xs[1]), 100)); self.app.processEvents()
        self.assertIsNotNone(plot.cursor_x); self.assertFalse(plot.grab().isNull()); plot.close()

    def test_chart_empty_single_and_nonpositive_peak(self):
        plot = EquityPlot(); plot.set_values([]); self.assertIsNone(plot.value_at(0)); plot.grab()
        plot.set_values([{'trade_date': '2024-01-01', 'equity': '0'}]); self.assertEqual(plot.value_at(0), ('2024-01-01', 0.0))
        self.assertEqual(plot.drawdowns, [None]); self.assertFalse(plot.grab().isNull())
        plot.set_values([{'equity': 'bad'}, {'equity': float('nan')}]); self.assertEqual(plot.values, []); plot.close()

    def test_walk_forward_one_row_per_fold_and_missing_metrics(self):
        panel = WalkForwardResults()
        panel.set_result({'summary': {'evaluated_oos_folds': 1, 'evaluations_reserved': 5, 'evaluation_limit': 10}, 'folds': [
            {'index': 0, 'status': 'evaluated', 'oos': {'metrics': {'net_pnl': '0', 'return': '.125', 'profit_factor': None}}},
            {'index': 1, 'status': 'not_evaluated'}]})
        self.assertEqual(panel.table.rowCount(), 2); self.assertEqual(panel.table.item(0, 2).text(), '0 TWD')
        self.assertEqual(panel.table.item(0, 3).text(), '12.50%')
        self.assertEqual(panel.table.item(0, 4).text(), ui_text('forms.metric.text_1'))
        self.assertEqual(panel.table.item(1, 2).text(), ui_text('forms.metric.text_2')); panel.close()


class ResultsHostTests(unittest.TestCase):
    setUpClass = classmethod(test_desktop_pages.PageInteractionTests.setUpClass.__func__)
    setUp = test_desktop_pages.PageInteractionTests.setUp
    tearDown = test_desktop_pages.PageInteractionTests.tearDown

    def test_advanced_dumps_collapsed_and_paper_tables_project_account(self):
        w = self.window; w.show(); self.app.processEvents()
        w.navigation.setCurrentRow(2); self.app.processEvents()
        self.assertFalse(w.result_detail.isVisible()); self.assertFalse(w.paper_detail.isVisible())
        self.assertFalse(w.result_card.isVisible()); self.assertFalse(w.paper_card.isVisible())
        w.navigation.setCurrentRow(4); self.app.processEvents()
        self.assertFalse(w.paper_detail.isVisible()); self.assertFalse(w.paper_card.isVisible())
        self.assertTrue(w.walk_forward_results.isHidden())
        account = {'account_id': 'demo', 'cash': '1000000', 'positions': {'TAIFEX:TMF:202601': -2}, 'orders': {}, 'fills': {}, 'reconciliation_required': False, 'kill_switch': False}
        before = copy.deepcopy(account); w._show_account(account)
        page = w.paper_page
        self.assertEqual(page.kpis.labels['cash'].text(), '1,000,000 TWD')
        self.assertEqual(page.kpis.labels['fills'].text(), '0')
        self.assertEqual(page.positions_table.item(0, 1).text(), '空單 2 口')
        self.assertEqual(account, before)
        self.assertIsInstance(w.backtest_page.fills_table, TaipeiFillsTable)
        self.assertIsInstance(w.strategy_page.result_panel, WalkForwardResults)


class BacktestResultHostTests(unittest.TestCase):
    from tests.test_result_reference_layers import ResultReferenceHostTests as Fixture
    setUpClass = Fixture.__dict__['setUpClass']
    setUp = Fixture.setUp
    cleanup_window = Fixture.cleanup_window
    install = Fixture.install

    def test_saved_result_projects_into_cards_table_and_chart_without_mutation(self):
        from quantlab.core import canonical_json
        _, result, _ = self.install(mtm=True)
        w = self.window; before = canonical_json(result)
        self.assertEqual(w.backtest_page.kpis.labels['net_pnl'].text(), shown(result.metrics['net_pnl'], 'net_pnl'))
        self.assertEqual(w.backtest_page.kpis.labels['profit_factor'].text(), ui_text('forms.metric.text_1'))
        self.assertEqual(w.fills_table.item(0, 0).text(), taipei_time(result.fills[0].timestamp))
        self.assertEqual(w.fills_table.rowCount(), len(result.fills))
        self.assertEqual(len(w.plot.values), len(result.equity))
        self.assertFalse(w.plot.grab().isNull())
        self.assertEqual(canonical_json(result), before)


if __name__ == '__main__':
    unittest.main()
