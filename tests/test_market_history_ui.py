"""Synthetic-only typed local history UI/worker/restart coverage; no exchange files."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from desktop_market import MarketHistoryDialog
from desktop_ui import execute_ui_operation
from quantlab.desktop_runtime import AppPaths
from tests import test_desktop_ui as support

HEADER = '成交日期,商品代號,到期月份(週別),成交時間,成交價格,成交數量(B+S),近月價格,遠月價格,開盤集合競價\n'
ROWS = '20261008,TX,202610,084500,30000,2,-,-,*\n20261008,TX,202610,084559,30002,4,-,-,\n20261008,TX,202610,084600,30001,2,-,-,\n'


def fill(dialog, product='TX', night=False):
    dialog.product.setCurrentIndex(dialog.product.findData(product))
    dialog.month.setText('202610')
    dialog.trade_date.setText('2026-10-08')
    dialog.session.setCurrentIndex(1 if night else 0)
    dialog.open_date.setText('2026-10-07' if night else '2026-10-08')
    dialog.end_date.setText('2026-10-08')
    dialog.confirm.setChecked(True)


def request(path):
    dialog = MarketHistoryDialog(); fill(dialog)
    dialog.path.setText(str(path)); dialog.add_session()
    result = dialog.request_payload(); dialog.deleteLater(); return result


class HistoryFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = MarketHistoryDialog()
        self.addCleanup(self.dialog.deleteLater)

    def test_dates_empty_and_unconfirmed_without_inference(self):
        d = self.dialog
        for field in (d.month,d.trade_date,d.open_date,d.end_date): self.assertEqual(field.text(),'')
        self.assertFalse(d.confirm.isChecked())
        d.add_session(); self.assertEqual(d.sessions,[])
        self.assertIn('確認',d.error.text())
        d.session.setCurrentIndex(1)
        self.assertEqual(d.end_time.time(),QTime(5,0))
        self.assertEqual(d.end_date.text(),'')

    def test_contract_day_utc_product_source_and_weekly(self):
        from quantlab.market_history import PRODUCT_SOURCES
        d=self.dialog; fill(d, 'MTX'); d.expiry_type.setCurrentIndex(1); d.week.setValue(2); d.confirm.setChecked(True)
        value=d.session_payload()
        self.assertEqual(value['contract_id'],'TAIFEX:MTX:202610W2')
        self.assertEqual(value['open'],'2026-10-08T00:45:00+00:00')
        self.assertEqual(value['end'],'2026-10-08T05:45:00+00:00')
        self.assertEqual(value['source'],PRODUCT_SOURCES['MTX'])
        self.assertIn('MXF',d.product.currentText())

    def test_night_cross_midnight_explicit_holiday_attribution(self):
        d=self.dialog; fill(d,'TMF',True)
        d.trade_date.setText('2026-10-12'); d.confirm.setChecked(True)
        value=d.session_payload()
        self.assertEqual(value['trade_date'],'2026-10-12')
        self.assertEqual(value['open'],'2026-10-07T07:00:00+00:00')
        self.assertEqual(value['end'],'2026-10-07T21:00:00+00:00')
        d.add_session(); self.assertEqual(len(d.sessions),1)
        self.assertIn('2026-10-12',d.session_list.item(0).text())

    def test_edit_resets_confirmation_expiry_short_close_endpoint(self):
        d=self.dialog; fill(d)
        d.end_time.setTime(QTime(13,30)); self.assertFalse(d.confirm.isChecked())
        d.include_end.setChecked(True); d.confirm.setChecked(True)
        value=d.session_payload(); self.assertTrue(value['include_end'])
        self.assertEqual(value['end'],'2026-10-08T05:30:00+00:00')
        d.product.setCurrentIndex(2); self.assertFalse(d.confirm.isChecked())

    def test_multiple_sessions_duplicate_overlap_remove(self):
        d=self.dialog; fill(d); d.add_session()
        d.confirm.setChecked(True); d.add_session(); self.assertEqual(len(d.sessions),1)
        self.assertIn('已加入',d.error.text())
        d.open_time.setTime(QTime(9,0)); d.confirm.setChecked(True); d.add_session()
        self.assertEqual(len(d.sessions),1); self.assertIn('重疊',d.error.text())
        fill(d,night=True); d.add_session(); self.assertEqual(len(d.sessions),2)
        d.session_list.setCurrentRow(0); d.remove_session(); self.assertEqual(len(d.sessions),1)

    def test_bad_dates_contracts_and_file_validation(self):
        d=self.dialog; fill(d); d.month.setText('202613'); d.confirm.setChecked(True)
        d.add_session(); self.assertEqual(d.sessions,[])
        d.month.setText('202610'); d.open_date.setText('2026-02-30'); d.confirm.setChecked(True)
        d.add_session(); self.assertEqual(d.sessions,[])
        fill(d); d.add_session(); d.path.setText('handwritten.json')
        d.accept_import(); self.assertIn('CSV',d.error.text()); self.assertEqual(d.result(),0)

    def test_choose_file_cancel_and_request_copy(self):
        d=self.dialog; d.path.setText('keep.csv')
        with patch.object(QFileDialog,'getOpenFileName',return_value=('','')): d.choose_file()
        self.assertEqual(d.path.text(),'keep.csv')
        with patch.object(QFileDialog,'getOpenFileName',return_value=('/tmp/local.RPT','')): d.choose_file()
        fill(d); d.add_session(); d.accept_import()
        value=d.payload(); value['sessions'].clear()
        self.assertEqual(len(d.payload()['sessions']),1)
        self.assertEqual(d.result(),QDialog.DialogCode.Accepted)


class HistoryHostTests(unittest.TestCase):
    setUpClass = support.NativeDesktopTests.__dict__['setUpClass']
    setUp = support.NativeDesktopTests.setUp
    def cleanup_window(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        support.NativeDesktopTests.cleanup_window(self)
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    wait_job = support.NativeDesktopTests.wait_job

    def source(self, name='ticks.csv', rows=ROWS):
        path=Path(self.tmp.name)/name; path.write_text(HEADER+rows,encoding='utf-8'); return path

    def test_dialog_cancel_does_not_start_worker_and_busy_guard(self):
        from quantlab.core import ValidationError
        with patch.object(self.window,'start_job') as start:
            self.window.import_market_history()
            dialog=self.window._history_dialog
            self.assertTrue(dialog.isVisible())
            self.window.import_market_history()
            self.assertIs(self.window._history_dialog,dialog)
            dialog.reject(); self.app.processEvents()
            self.assertIsNone(self.window._history_dialog)
            start.assert_not_called()
        class Busy: active=True
        original=self.window.jobs; self.window.jobs=Busy()
        try:
            with patch.object(MarketHistoryDialog,'open') as show:
                with self.assertRaises(ValidationError): self.window.import_market_history()
                show.assert_not_called()
        finally: self.window.jobs=original

    def test_accepted_typed_dialog_schedules_exact_worker(self):
        payload=request(self.source())
        with patch.object(MarketHistoryDialog,'payload',return_value=payload), patch.object(self.window,'start_job') as start:
            self.window.import_market_history()
            dialog=self.window._history_dialog
            start.assert_not_called()
            dialog.accept(); self.app.processEvents()
            start.assert_called_once_with('ui_market_refresh',payload)
            self.assertIsNone(self.window._history_dialog)

    def test_dialog_accept_during_close_never_starts_work(self):
        with patch.object(self.window,'start_job') as start:
            self.window.import_market_history()
            dialog=self.window._history_dialog
            self.window._closing=True
            dialog.accept(); self.app.processEvents()
            start.assert_not_called()
            self.assertIsNone(self.window._history_dialog)
            self.window._closing=False

    def test_worker_repeat_restart_no_network_and_no_research_write(self):
        from quantlab.market_history import list_history
        payload=request(self.source())
        with patch('socket.socket',side_effect=AssertionError('unexpected network')):
            first=execute_ui_operation('ui_market_refresh',payload,self.paths)
            second=execute_ui_operation('ui_market_refresh',payload,self.paths)
            self.window.load_market_cache()
        self.assertEqual(first['cache_id'],second['cache_id'])
        self.assertEqual(first['bars'],2)
        self.assertEqual(first['mode'],'local_unverified_history')
        self.assertEqual(len(list_history(self.paths.state/'market_history')),1)
        self.assertFalse((self.paths.state/'dataset.json').exists())
        self.assertEqual(self.window._market_data_bindings,{})
        self.window.market.contract_combo.setCurrentIndex(self.window.market.contract_combo.findData('TAIFEX:TX:202610'))
        self.assertEqual(len(self.window.market.selected_series().bars),2)
        self.assertEqual(self.window.market.selected_series().provenance.mode,'history')
        self.assertNotIn('來源更新失敗',self.window.market.message.text())
        self.assertIn('未驗證',self.window.market.message.text())
        # A fresh host reloads only the persisted bounded history cache.
        from desktop_ui import MainWindow
        from quantlab.desktop_runtime import JobManager, SettingsStore, BackupManager
        jobs=JobManager(self.paths)
        restarted=MainWindow(self.paths,jobs,SettingsStore(self.paths.state/'settings.json'),BackupManager(self.paths,jobs))
        try:
            self.assertEqual(len(restarted.market.selected_series().bars),2)
            self.assertEqual(restarted._market_data_bindings,{})
        finally: jobs.close(); restarted.close(); restarted.deleteLater()


    def test_background_real_process_repeat_and_failure_retains_good(self):
        payload=request(self.source())
        self.window.start_job('ui_market_refresh',payload); self.wait_job()
        snapshot={p.name:p.read_bytes() for p in (self.paths.state/'market_history').glob('*.json')}
        self.window.start_job('ui_market_refresh',payload); self.wait_job()
        self.assertEqual(snapshot,{p.name:p.read_bytes() for p in (self.paths.state/'market_history').glob('*.json')})
        bad=request(self.source('bad.csv','20261008,TX,202610,084500,NaN,2,-,-,\n'))
        self.window.start_job('ui_market_refresh',bad)
        deadline=time.monotonic()+15
        while self.jobs.active and time.monotonic()<deadline:
            self.app.processEvents(); self.window.poll_jobs(); time.sleep(.02)
        self.window.poll_jobs(); self.assertFalse(self.jobs.active); self.assertIn('失敗',self.window.status.text())
        self.assertEqual(snapshot,{p.name:p.read_bytes() for p in (self.paths.state/'market_history').glob('*.json')})
        self.window.start_job('ui_market_refresh',payload); self.wait_job()

    def test_cancel_real_running_worker_retains_cache_and_repeats(self):
        from quantlab.market_history import list_history
        payload=request(self.source()); execute_ui_operation('ui_market_refresh',payload,self.paths)
        old=list_history(self.paths.state/'market_history')
        large=self.source('large.rpt','20261008,TX,202610,084500,30000,2,-,-,\n'*500000)
        self.window.start_job('ui_market_refresh',request(large))
        self.assertTrue(self.jobs.active)
        deadline=time.monotonic()+10
        entered=False
        while self.jobs.active and time.monotonic()<deadline:
            self.app.processEvents(); self.window.poll_jobs()
            if '正在匯入本機逐筆歷史' in self.window.status.text(): entered=True; break
            time.sleep(.01)
        self.assertTrue(entered, 'worker must enter history adapter before cancellation')
        time.sleep(.1)
        self.assertTrue(self.jobs.active, 'large synthetic import must still be running')
        self.window.cancel_job(); self.window.poll_jobs()
        self.assertFalse(self.jobs.active)
        self.assertEqual(list_history(self.paths.state/'market_history'),old)
        self.window.start_job('ui_market_refresh',payload); self.wait_job()

    def test_malformed_history_marker_or_mixed_network_fields_fail_closed(self):
        payload=request(self.source())
        variants=[dict(payload,history_import=value,network_opt_in=True) for value in (False,'true',1,None)]
        variants.extend(dict(payload,**extra) for extra in ({'network_opt_in':True},{'provider':'taifex'},{'unknown':True}))
        with patch('quantlab.market_providers.refresh_daily',side_effect=AssertionError('history must never dispatch network')) as network, patch('quantlab.market_providers.import_daily',side_effect=AssertionError('history must never dispatch daily')) as daily, patch('quantlab.market_history.import_history') as importer:
            for value in variants:
                with self.subTest(payload=value):
                    with self.assertRaises(ValueError): execute_ui_operation('ui_market_refresh',value,self.paths)
            network.assert_not_called(); daily.assert_not_called(); importer.assert_not_called()

    def test_unconfirmed_adapter_rejected_before_file_io(self):
        payload=request(self.source()); payload['dated_policy_confirmed']=False
        with patch('quantlab.market_history.import_history') as importer:
            with self.assertRaises(ValueError): execute_ui_operation('ui_market_refresh',payload,self.paths)
            importer.assert_not_called()


if __name__ == '__main__': unittest.main()
