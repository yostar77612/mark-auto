"""Display-only report adapters; generated offline engineering evidence."""
import ast
import copy
import json
import os
from decimal import Decimal
from pathlib import Path
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from quantlab.core import canonical_json, to_dict
from desktop_forms import BacktestSummaryCard, BacktestFillsTable, SummaryCard, ResultTable, backtest_summary_text
from tests.test_performance_metrics import metric
from tests import test_result_reference_layers as references


class BacktestPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_metric_presentation_preserves_values_and_source(self):
        source = metric(('150', '-30', '50', '-20'))
        source.update(net_pnl=Decimal('150'), total_costs=Decimal('1.23456789'), open_lots=[{'fill_id':'a'*64}], settlements=[{'event_id':'b'*64}], rolls=[{'raw_key':'raw_value'}])
        before = canonical_json(source); text = backtest_summary_text(source)
        self.assertIn('獲利因子：4', text); self.assertIn(str(source['sharpe']), text)
        self.assertIn('總費用（TWD）：1.23456789', text)
        self.assertEqual(canonical_json(source), before)
        for raw in ('daily_returns', 'open_lots', 'settlements', 'rolls', 'raw_key', 'a'*64, 'b'*64, '{', 'Descriptive only', 'closed FIFO'):
            self.assertNotIn(raw, text)
        for required in ('假設每年期數：252', '假設年無風險利率：0', '數學最低觀測期數：2', '不補值', '自由度修正 1', '短樣本不能證明策略品質', '未驗證全年交易日曆', '間隔可能跨越多日'):
            self.assertIn(required, text)
        self.assertLess(len(text), 1500)

    def test_pf_zero_remains_defined(self):
        text = backtest_summary_text(metric(('-10','-20')))
        self.assertIn('獲利因子：0', text)
        self.assertIn('獲利因子未定義原因：不適用（已定義）', text)

    def test_pf_no_closes_and_zero_denominator_distinguished(self):
        for pnls, reason in (((), '尚無已平倉批次'), (('20','30'), '分母為零'), (('0',), '分母為零')):
            text = backtest_summary_text(metric(pnls))
            self.assertIn('獲利因子：未定義', text); self.assertIn(reason, text)
            self.assertNotIn('獲利因子：0', text); self.assertNotIn('獲利因子：未提供', text)

    def test_legacy_missing_metric_is_not_declared_undefined(self):
        text = backtest_summary_text({'net_pnl':'0'})
        self.assertIn('獲利因子：未提供', text); self.assertIn('夏普值（描述性）：未提供', text)
        self.assertIn('年化假設：未提供', text)

    def test_sharpe_reasons_and_samples_localized(self):
        for values, reason in ((('10000',), '至少需要 2 期'), (('10000','10000'), '變異數為零'), (('10100', None, '10300'), '未略過任何觀測值')):
            text = backtest_summary_text(metric(values=values))
            self.assertIn('夏普值（描述性）：未定義', text); self.assertIn(reason, text)
            self.assertIn('夏普值觀測期數：'+str(len(values)), text)

    def test_unknown_explanations_do_not_echo_diagnostic_codes(self):
        source = metric(); source['sharpe_note']='new_internal_diagnostic';source['profit_factor_reason']='some_new_reason'
        source['annualization']['return_frequency']='future_frequency_code'
        text = backtest_summary_text(source)
        self.assertNotIn('new_internal_diagnostic', text); self.assertNotIn('some_new_reason', text); self.assertNotIn('future_frequency_code', text)
        self.assertIn('未辨識的說明，請查看進階診斷', text)

    def test_invalid_nested_nonfinite_scalars_do_not_leak_diagnostics(self):
        for value in ({'raw_key':'secret'}, ['raw_list'], 'raw_code', float('inf'), Decimal('NaN'), True, '9'*10000):
            source = metric();source['annualization']['periods_per_year']=value;source['net_pnl']=value;source['profit_factor']=value;source['profit_factor_reason']=None;source['sharpe']=value;source['sharpe_reason']=None
            text=backtest_summary_text(source)
            self.assertIn('假設每年期數：請查看進階診斷',text);self.assertIn('淨損益（TWD）：請查看進階診斷',text)
            self.assertNotIn('不適用（已定義）',text);self.assertIn('指標值無法辨識',text);self.assertLess(len(text),1500)
            for raw in ('raw_key','raw_list','raw_code','secret'):self.assertNotIn(raw,text)

    def test_generic_cards_and_tables_unchanged(self):
        card = SummaryCard();table=ResultTable()
        card.set_values({'key':{'value':'raw'}});table.set_rows([{'side':'buy','fill_id':'a'*64}])
        self.assertEqual(card.label.text(),'key：value：raw')
        self.assertEqual(table.item(0,0).text(),'buy');self.assertEqual(table.item(0,1).text(),'a'*64)
        card.close();table.close()

    def test_fill_presentation_exact_values_ids_tooltips_and_utc(self):
        rows=[{'timestamp':'2026-10-01T09:01:00.123456+08:00','contract_id':'TAIFEX:TMF:202610','side':'buy','quantity':3,'price':'20120','commission':'4.55','tax':'0.1234','reason':'target_open','fill_id':'a'*64,'order_id':'b'*64}]
        before=copy.deepcopy(rows);table=BacktestFillsTable();table.set_rows(rows)
        self.assertEqual(rows,before); self.assertEqual(table.columnCount(),8)
        self.assertEqual(table.item(0,0).text(),'2026-10-01 01:01:00.123456')
        self.assertEqual(table.item(0,2).text(),'買進');self.assertEqual(table.item(0,7).text(),'目標部位進場')
        for index,value in ((3,'3'),(4,'20120'),(5,'4.55'),(6,'0.1234')):self.assertEqual(table.item(0,index).text(),value)
        for col in range(table.columnCount()):
            self.assertNotIn('a'*64,table.item(0,col).text());self.assertIn('a'*64,table.item(0,col).toolTip())
            self.assertIn('b'*64,table.item(0,col).toolTip())
        table.set_rows([{**rows[0],'side':'sell','reason':'maintenance_liquidation'}])
        self.assertEqual(table.item(0,2).text(),'賣出');self.assertEqual(table.item(0,7).text(),'維持保證金不足平倉')
        table.close()

    def test_fill_extreme_numbers_keep_bounded_columns_and_exact_tooltips(self):
        table=BacktestFillsTable();huge='9'*400
        table.set_rows([{'price':huge}]);self.assertEqual(table.item(0,4).text(),huge);self.assertIn(huge,table.item(0,4).toolTip())
        self.assertTrue(all(table.columnWidth(i)<=340 for i in range(table.columnCount())));table.close()

    def test_fill_empty_unknown_and_naive_time_are_honest(self):
        table=BacktestFillsTable();table.set_rows([]);self.assertEqual(table.rowCount(),0);self.assertEqual(table.columnCount(),8)
        table.set_rows([{'timestamp':'2026-10-01T01:00:00','side':'unknown_side','reason':'new_diagnostic_code'}])
        self.assertIn('請核對進階診斷',table.item(0,0).text());self.assertNotIn('unknown_side',table.item(0,2).text());self.assertNotIn('new_diagnostic_code',table.item(0,7).text())
        for value in ({'future':'unknown_shape'}, ['new_code'], 5, {}, False):
            table.set_rows([{'side':value,'reason':value}]);self.assertIn('請核對進階診斷',table.item(0,2).text());self.assertIn('請核對進階診斷',table.item(0,7).text())
        table.close()


class BacktestPresentationHostTests(unittest.TestCase):
    setUpClass = references.ResultReferenceHostTests.__dict__['setUpClass']
    setUp = references.ResultReferenceHostTests.setUp
    cleanup_window = references.ResultReferenceHostTests.cleanup_window
    install = references.ResultReferenceHostTests.install
    def test_normal_ui_and_advanced_source_match(self):
        _,result,_=self.install(mtm=True);w=self.window
        self.assertIsInstance(w.result_card,BacktestSummaryCard);self.assertIsInstance(w.fills_table,BacktestFillsTable)
        before=canonical_json(result)
        self.assertIn('獲利因子：未定義',w.result_card.label.text())
        self.assertIn('尚無已平倉批次',w.result_card.label.text())
        raw=json.loads(w.result_detail.toPlainText())
        self.assertEqual(raw['metrics'],to_dict(result.metrics));self.assertEqual(raw['fills'],[to_dict(fill) for fill in result.fills])
        self.assertIn('open_lots',raw['metrics']);self.assertIn('daily_returns',raw['metrics'])
        self.assertFalse(w.result_detail.isVisible())
        self.assertEqual(canonical_json(result),before);self.assertEqual(len(w.market.chart.reference_lines),6)
        for col in range(w.fills_table.columnCount()):
            self.assertNotIn('fill_id',w.fills_table.horizontalHeaderItem(col).text())
        self.assertIn(result.fills[0].fill_id,w.fills_table.item(0,0).toolTip())


if __name__ == '__main__': unittest.main(verbosity=2)
