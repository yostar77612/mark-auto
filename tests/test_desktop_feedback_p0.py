"""Focused T2B presentation contracts, offline synthetic data only."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from quantlab.desktop_feedback import OPERATION_LABELS, completion_summary, stop_presentation
from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / ('markauto-feedback-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)

    def window(self):
        from desktop_ui import MainWindow
        paths = AppPaths(self.root).ensure()
        jobs = JobManager(paths)
        w = MainWindow(paths, jobs, SettingsStore(paths.state/'settings.json'), BackupManager(paths, jobs))
        w.timer.stop()
        self.addCleanup(w.deleteLater)
        self.addCleanup(w.close)
        self.addCleanup(jobs.close)
        return w

    def test_p014_single_completion_links_fades_and_persistent_error(self):
        from PySide6.QtTest import QTest
        from quantlab.desktop_errors import error_message
        w = self.window()
        w.last_operation = 'ui_demo'
        w._pending_chatgpt_restore = False
        with patch.object(w.jobs, 'poll', return_value=[{'type':'result', 'result':{'bars':960}}]):
            w.poll_jobs()
        self.assertEqual(w.status.text(), '')
        self.assertIn('960', w.notification.text())
        self.assertIn('查看結果', w.notification.text())
        self.assertEqual(w.notification_timer.interval(), 5000)
        w.notification.linkActivated.emit('result')
        self.assertEqual(w.navigation.currentRow(), 0)
        w.notification_timer.start(1)
        # The fade is a 300 ms animation after the timer fires; poll (bounded) instead of a fixed 450 ms wait,
        # which raced on loaded machines. The assertion itself is unchanged.
        for _ in range(150):
            if w.notification.isHidden(): break
            QTest.qWait(20)
        self.assertTrue(w.notification.isHidden())
        w.notify_local(error_message('operation_failed'), error=True)
        self.assertFalse(w.notification_timer.isActive())
        QTest.qWait(450)
        self.assertFalse(w.notification.isHidden())
        w.notification.linkActivated.emit('close')
        self.assertTrue(w.notification.isHidden())

    def test_p017_every_operation_has_distinct_summary(self):
        from desktop_ui import UI_OPERATIONS
        self.assertEqual(set(UI_OPERATIONS), {'ui_' + op for op in OPERATION_LABELS})
        summaries = [completion_summary('ui_' + op, {}) for op in OPERATION_LABELS]
        self.assertEqual(len(summaries), len(set(summaries)))
        self.assertIn('960 根（合成資料）', completion_summary('ui_demo', {'bars':960}))
        self.assertIn('淨損益 -706 TWD、29 筆交易', completion_summary('ui_backtest', {'reports':[{}], 'metrics':{'net_pnl':'-706', 'trade_count':29}}))
        self.assertIn('abcdef', completion_summary('ui_select', {'strategy_hash':'abcdef'}))
        account = {'account_id':'paper-demo', 'cash':'999976', 'positions':{'TMF':-1}, 'orders':{'o':{}}, 'fills':{'f':{}}, 'reconciliation_required':False}
        for op in ('snapshot', 'reconcile', 'submit', 'cancel', 'kill', 'replay'):
            with self.subTest(op=op):
                text = completion_summary('ui_paper_' + op, {'account':account, 'replay':{'cursor':100, 'processed_bars':40, 'new_fills':1}})
                self.assertIn('999976 TWD', text)
                self.assertIn('成交 1 筆', text)
                if op == 'replay': self.assertIn('處理 40 根、新增 1 筆成交', text)

    def test_market_success_omits_zero_failures_and_partial_failure_keeps_count(self):
        for providers in ({}, {'synthetic':{'bars':12}}, {'synthetic':{'bars':12, 'error':None}}):
            with self.subTest(providers=providers):
                text = completion_summary('ui_market_refresh', {'providers':providers})
                self.assertNotIn('失敗', text)
                self.assertIn(f'{len(providers)} 個來源', text)
        text = completion_summary('ui_market_refresh', {'providers':{'good':{'bars':12}, 'bad':{'error':'private-token'}}})
        self.assertIn('1 個失敗', text)
        self.assertIn('12 根', text)
        self.assertNotIn('private-token', text)

    def test_invalid_policy_replaces_previous_success_with_persistent_error(self):
        from quantlab.desktop_errors import error_message
        w = self.window()
        w.last_operation = 'ui_demo'
        w.notify_local(completion_summary('ui_demo', {'bars':960}), completion=True)
        w.local_notifications.setChecked(False)
        w._safe(lambda: w.paper_job('snapshot'))
        self.assertEqual(w.status.text(), error_message('validation_failed'))
        self.assertIn('失敗', w.notification.text())
        self.assertNotIn('示範資料建立完成', w.notification.text())
        self.assertFalse(w.notification_timer.isActive())
        self.assertFalse(w.notification.isHidden())
        self.assertFalse(w.jobs.active)
        self.assertFalse((w.root/'paper_policy.json').exists())

    def test_p018_demo_policy_scroll_highlight_and_loaded_form(self):
        from desktop_ui import execute_ui_operation
        w = self.window()
        execute_ui_operation('ui_demo', {'bars':960}, w.paths)
        w.navigation.setCurrentRow(4)
        scroll = w.stack.widget(4)
        with patch.object(scroll, 'ensureWidgetVisible', wraps=scroll.ensureWidgetVisible) as ensure:
            w.demo_paper_policy()
            ensure.assert_called_with(w.policy_form.sessions)
        self.assertEqual(w.status.text(), '已填入示範政策：4 個交易時段、1 筆保證金設定（合成資料）')
        self.assertTrue(w.policy_form.sessions.property('feedback'))
        self.assertEqual(w.policy_form.sessions.styleSheet(), '')
        self.assertEqual(w.policy_form.sessions.table.rowCount(), 4)
        self.assertEqual(w.policy_form.margins.table.rowCount(), 1)
        from quantlab.reporting import write_json
        path = self.root/'snapshot.json'
        write_json(path, {'account_id':'demo', 'cash':'1000', 'positions':{}, 'orders':{}, 'fills':{}})
        with patch('desktop_ui.QFileDialog.getOpenFileName', return_value=(str(path), 'JSON')):
            w.load_form_file(w.snapshot_form, w.snapshot)
        self.assertIn('已載入參考資料', w.status.text())
        self.assertTrue(w.snapshot_form.property('feedback'))
        self.assertEqual(w.snapshot_form.styleSheet(), '')
        w.use_builtin()
        self.assertIn('已切回內建家族', w.status.text())
        self.assertTrue(w.strategy_form.property('feedback'))
        self.assertEqual(w.strategy_form.styleSheet(), '')
        with patch('desktop_ui.QFileDialog.getOpenFileName', return_value=(str(path), 'JSON')):
            w._browse(w.import_path)
            self.assertIn('已填入選取檔案', w.status.text())
            w.pick_analysis_original()
            self.assertIn('已填入分析原始資料檔', w.status.text())
            w.pick_walk_forward_original()
            self.assertIn('已填入 Walk-forward 原始資料檔', w.status.text())

    def test_p019_three_stop_reasons_colors_and_stale_marker(self):
        w = self.window()
        account = {'account_id':'demo', 'cash':'1000', 'positions':{}, 'orders':{}, 'fills':{}, 'kill_switch':True, 'reconciliation_required':False}
        colors = []
        for reason, expected in (('replay','重播批次已結束（正常）'), ('user','緊急停止（使用者觸發）')):
            w._remember_stop(account, reason)
            w._show_account(account)
            self.assertIn(expected, w.paper_card.label.text())
            colors.append(w.paper_card.label.property('status'))
        risk = {**account, 'consecutive_loss_halt':True}
        w._show_account(risk)
        self.assertIn('風控觸發停止', w.paper_card.label.text())
        colors.append(w.paper_card.label.property('status'))
        self.assertEqual(colors, ['success', 'danger', 'warning'])
        self.assertIn('風控觸發停止', stop_presentation({**account, 'orders':{'r':{'status':'rejected', 'reason':'max_daily_loss'}}}, 'replay')[0])
        w._remember_stop(account, 'replay')
        w._show_account({**account, 'cash':'999'})
        self.assertNotIn('正常', w.paper_card.label.text())
        self.assertTrue(account['kill_switch'])

    def test_p020_card_matches_readonly_ledger_and_reference_counts_labelled(self):
        from desktop_ui import _paper
        from quantlab.paper import PaperBroker
        from quantlab.reporting import write_json
        w = self.window()
        write_json(w.root/'paper_policy.json', {'contract_id':'TAIFEX:TMF:202610', 'risk_sessions':[], 'margin_schedule':[]})
        broker = _paper(w.root)
        broker.reconcile({'account_id':'demo', 'cash':'1000000', 'positions':{}, 'orders':{}, 'fills':{}})
        before = broker.journal_events()
        w._show_account(PaperBroker.read_snapshot(broker.path))
        self.assertIn('現金（TWD）：1,000,000 TWD', w.paper_card.label.text())
        self.assertIn('帳戶成交筆數：0', w.paper_card.label.text())
        self.assertEqual(broker.journal_events(), before)
        from datetime import datetime, timezone
        from quantlab.paper import PaperBroker as Broker
        from quantlab.core import Instrument
        from quantlab.reporting import demo_config
        from desktop_ui import paper_risk_limits
        now = datetime(2026, 1, 5, 1, tzinfo=timezone.utc)
        session = {'open':'2026-01-05T00:45:00Z', 'end':'2026-01-05T04:45:00Z', 'trade_date':'2026-01-05', 'source':'synthetic', 'session':'day'}
        filled = Broker(self.root/'filled.sqlite3', instrument=Instrument('TAIFEX:TMF:202601'), costs=demo_config().costs,
                        limits=paper_risk_limits(), risk_sessions=(session,), margin_schedule=({'effective_from':'2026-01-01', 'margin_per_contract':'100000', 'version':'synthetic'},))
        filled.reconcile({'account_id':'demo', 'cash':'1000000', 'positions':{}, 'orders':{}, 'fills':{}})
        intent = {'client_order_id':'o', 'strategy_hash':'synthetic', 'contract_id':'TAIFEX:TMF:202601', 'side':'sell', 'quantity':1, 'order_type':'market', 'created_at':now}
        quote = {'account_id':'demo', 'contract_id':intent['contract_id'], 'timestamp':now, 'price':'20000', 'trade_date':'2026-01-05', 'session_open':session['open'], 'session_end':session['end'], 'margin_per_contract':'100000'}
        filled.submit(intent, quote=quote, now=now)
        filled.apply_event({'event_id':'f', 'fill_id':'f', 'order_id':'o', 'sequence':1, 'type':'fill', 'timestamp':now, 'quantity':1, 'price':'20000', 'commission':'20', 'tax':'4'})
        account = PaperBroker.read_snapshot(filled.path)
        w._show_account(account)
        text = w.paper_card.label.text()
        for expected in ('現金（TWD）：999,976 TWD', '帳戶部位項目：1', '帳戶委託筆數：1', '帳戶成交筆數：1', 'TAIFEX:TMF:202601：-1'):
            self.assertIn(expected, text)
        self.assertIn('參考快照成交筆數：0', w.snapshot_form.records.label.text())
        self.assertEqual(w.market.positions_table.rowCount(), 1)
        self.assertEqual(w.market.fills_table.rowCount(), 1)


if __name__ == '__main__':
    unittest.main()
