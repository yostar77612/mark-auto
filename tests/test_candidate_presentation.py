"""Candidate pane presentation only; isolated synthetic source fixtures."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from decimal import Decimal
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from desktop_forms import CandidateSummaryCard,SummaryCard,candidate_summary_text
from quantlab.core import canonical_json
from tests.test_performance_metrics import metric


def view(oos=None,holdout=None,qualified=False):
    return {'策略':'工程候選','紙上資格':qualified,'樣本外與保留集':{
        'oos':{'qualified':True,'evaluation':{'status':'evaluated','metrics':oos or {}}},
        'holdout':{'qualified':False,'evaluation':{'status':'evaluated','metrics':holdout or {}}}}}


class CandidatePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_split_identity_status_eligibility_and_exact_numbers(self):
        source=view({'net_pnl':'1.23456789','max_drawdown_pct':'0.01','trade_count':5},{'net_pnl':'-12','max_drawdown_pct':'0.20','trade_count':2})
        before=canonical_json(source);text=candidate_summary_text(source)
        self.assertIn('已保存研究的紙上門檻：未通過',text)
        self.assertIn('樣本外 OOS｜狀態：已評估｜門檻檢查：通過',text)
        self.assertIn('最終保留集｜狀態：已評估｜門檻檢查：未通過',text)
        first,last=text.split('最終保留集');self.assertIn('1.23456789',first);self.assertNotIn('1.23456789',last);self.assertIn('淨損益（TWD）：-12',last)
        self.assertEqual(canonical_json(source),before)
    def test_nested_manifests_hashes_unknown_fields_are_never_expanded(self):
        source=view();row=source['樣本外與保留集']['oos']['evaluation'];row.update(manifest={'config_hash':'a'*64,'raw_key':{'long':'x'*10000}},result_hash='b'*64,warnings=['raw warning'],other=['raw_list'])
        text=candidate_summary_text(source)
        for raw in ('config_hash','raw_key','a'*64,'b'*64,'raw warning','raw_list','manifest','evaluated','qualified'):self.assertNotIn(raw,text)
        self.assertLess(len(text),1000)
    def test_null_missing_and_zero_pf_are_distinct(self):
        text=candidate_summary_text(view(metric(('-10',)),metric(())))
        first,last=text.split('最終保留集');self.assertIn('獲利因子：0',first);self.assertIn('獲利因子：未定義',last);self.assertIn('尚無已平倉批次',last)
        self.assertIn('獲利因子：未提供',candidate_summary_text(view()))
        self.assertIn('分母為零',candidate_summary_text(view(metric(('10',)))))
    def test_sharpe_values_and_assumptions_remain_honest(self):
        golden=metric();text=candidate_summary_text(view(golden,metric(values=('10000',))))
        for expected in (str(golden['sharpe']),'夏普值觀測期數：3','假設每年期數：252','假設年無風險利率：0','數學最低觀測期數：2','至少需要 2 期','短樣本不能證明策略品質','不補值','間隔可能跨越多日','自由度修正 1'):
            self.assertIn(expected,text)
    def test_missing_failed_running_status_does_not_claim_evaluation(self):
        source=view();source['樣本外與保留集']['oos']={'qualified':False,'evaluation':{}}
        for state,label in (('failed','評估失敗'),('running','評估中'),('timed_out','已逾時'),('new_internal_status','未知狀態')):
            source['樣本外與保留集']['holdout']['evaluation']={'status':state,'error':'raw_exception'}
            text=candidate_summary_text(source);self.assertIn('樣本外 OOS｜狀態：尚無已保存評估',text);self.assertIn('最終保留集｜狀態：'+label,text);self.assertNotIn('raw_exception',text);self.assertNotIn('new_internal_status',text)
    def test_invalid_shapes_and_unbounded_values_fail_to_advanced(self):
        for value in ({'raw_key':'raw_value'},['raw_list'],True,'raw_code','9'*10000,Decimal('NaN')):
            source=view({'profit_factor':value,'sharpe':value,'net_pnl':value,'annualization':{'periods_per_year':value}})
            text=candidate_summary_text(source);self.assertIn('指標值無法辨識',text);self.assertNotIn('不適用（已定義）',text);self.assertLess(len(text),1600)
            for raw in ('raw_key','raw_value','raw_list','raw_code'):self.assertNotIn(raw,text)
        for value in (None,[],{'oos':[],'holdout':{'evaluation':{'status':{},'metrics':[]}}}):
            source={'樣本外與保留集':value};self.assertLess(len(candidate_summary_text(source)),1000)
    def test_long_name_hash_name_and_unknown_eligibility_are_bounded(self):
        source=view();source['策略']='name '*10000;source['紙上資格']='true'
        text=candidate_summary_text(source);self.assertLess(len(text),1000);self.assertIn('完整名稱見進階診斷',text);self.assertIn('紙上門檻：未提供',text)
        source['策略']='a'*64;text=candidate_summary_text(source);self.assertNotIn('a'*64,text)
    def test_legacy_count_and_absolute_drawdown_are_not_lost(self):
        text=candidate_summary_text(view({'max_drawdown':'123.45','closed_trades':7}))
        self.assertIn('最大回撤：123.45',text);self.assertIn('已平倉交易：7',text)
    def test_generic_paper_card_remains_scalar_and_unchanged(self):
        card=SummaryCard();card.set_values({'account_id':'engineering','cash':'1000000','reconciliation_required':True,'kill_switch':False})
        self.assertEqual(card.label.text(),'帳戶：engineering\n現金（TWD）：1000000\n需要對帳：是\n停止新委託：否');card.close()


class CandidatePresentationHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_actual_verified_candidate_keeps_full_advanced_provenance(self):
        from tests.saved_pool_fixtures import make_saved_source
        from quantlab.desktop_runtime import AppPaths,JobManager,SettingsStore,BackupManager
        from quantlab.reporting import save_dataset
        from desktop_ui import MainWindow,candidate_record
        with tempfile.TemporaryDirectory() as tmp:
            paths=AppPaths(Path(tmp)/'workspace',Path(tmp)/'bootstrap').ensure()
            folder,ref,data,state=make_saved_source(paths.state/'campaigns',candidates=1,registry_path=paths.controls/'holdout-registry.sqlite3');save_dataset(data,paths.state/'dataset.json')
            jobs=JobManager(paths);w=MainWindow(paths,jobs,SettingsStore(paths.state/'settings.json'),BackupManager(paths,jobs));w.show();self.app.processEvents()
            try:
                attempt=state['attempts'][0];reference={'campaign_folder':ref,'attempt_id':attempt['attempt_id'],'strategy_hash':attempt['strategy_hash']}
                before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
                spec,provenance=candidate_record(paths.state,reference)
                w.candidate_choice.addItem('工程候選',reference);w.candidate_choice.setCurrentIndex(w.candidate_choice.count()-1);w.inspect_candidate();self.app.processEvents()
                self.assertIsInstance(w.candidate_card,CandidateSummaryCard);self.assertIs(type(w.paper_card),SummaryCard)
                self.assertEqual(w.candidate_detail.toPlainText(),canonical_json({'strategy':spec,**provenance}));self.assertFalse(w.candidate_detail.isVisible())
                self.assertTrue(w._candidate_valid);self.assertTrue(w.use_candidate_button.isEnabled());self.assertTrue(provenance['paper_qualified'])
                text=w.candidate_card.label.text();self.assertLess(len(text),1000);self.assertNotIn('config_hash',text);self.assertNotIn(attempt['strategy_hash'],text)
                self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()})
            finally:jobs.close();w.close();self.app.processEvents()

if __name__=='__main__':unittest.main(verbosity=2)
