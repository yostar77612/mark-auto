"""Frozen host cases: all fixtures are engineering examples, never live-feed evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from tests import test_desktop_ui as ui_support
HAS_QT = ui_support.HAS_QT
from tests.test_market import TWSE, ROW, NOW


@unittest.skipUnless(HAS_QT, 'Install pinned desktop requirements to test Qt widgets')
class MarketHostTests(unittest.TestCase):
    setUpClass = ui_support.NativeDesktopTests.__dict__['setUpClass']
    setUp = ui_support.NativeDesktopTests.setUp
    cleanup_window = ui_support.NativeDesktopTests.cleanup_window

    def test_first_page_cached_history_no_network_or_placeholder_prices(self):
        from quantlab.market_providers import import_daily
        import_daily('twse', self.paths.state/'market_cache', TWSE, received_at=NOW)
        with patch('quantlab.market_providers.build_opener', side_effect=AssertionError('startup network')):
            self.window.refresh_views()
        self.assertIs(self.window.stack.widget(0), self.window.market)
        self.assertEqual(self.window.market.selected_series().bars[-1].close, 101)
        self.assertIn('尚無', self.window.market.cards['TMF'].text())
        self.assertIn('未知', self.window.market.trading_labels['paper'].text())
        self.assertEqual(len(self.window.market.chart.bars), 1)

    def test_explicit_refresh_consent_and_busy_guard(self):
        from PySide6.QtWidgets import QMessageBox
        from quantlab.core import ValidationError
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No), patch.object(self.window,'start_job') as start:
            self.window.refresh_market(); start.assert_not_called()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes), patch.object(self.window,'start_job') as start:
            self.window.refresh_market(); start.assert_called_once_with('ui_market_refresh', {'network_opt_in':True})
        from desktop_ui import execute_ui_operation
        with self.assertRaises(ValidationError): execute_ui_operation('ui_market_refresh',{},self.paths)
        class Active:
            active=True
        old=self.window.jobs;self.window.jobs=Active()
        try:
            with patch.object(QMessageBox,'question') as question:
                with self.assertRaises(ValidationError): self.window.refresh_market()
                question.assert_not_called()
        finally:self.window.jobs=old

    def test_independent_provider_failure_retains_cache(self):
        from desktop_ui import execute_ui_operation
        from quantlab.market_providers import import_daily, load_cached, MarketLoad
        a=import_daily('twse',self.paths.state/'market_cache',TWSE,received_at=NOW)
        old=(self.paths.state/'market_cache'/'twse.json').read_bytes()
        def refresh(provider,root,**kwargs):
            if provider=='twse':raise ValueError('offline')
            return MarketLoad((),False)
        with patch('quantlab.market_providers.refresh_daily',side_effect=refresh) as call:
            value=execute_ui_operation('ui_market_refresh',{'network_opt_in':True},self.paths)
        self.assertEqual(call.call_count,2)
        self.assertTrue(value['providers']['twse']['stale'])
        self.assertFalse(value['providers']['taifex']['stale'])
        self.assertEqual((self.paths.state/'market_cache'/'twse.json').read_bytes(),old)
        self.assertEqual(load_cached('twse',self.paths.state/'market_cache').series,a.series)

    def test_local_file_import_no_network_and_no_research_replacement(self):
        from desktop_ui import execute_ui_operation
        from quantlab.market_providers import load_cached
        path=Path(self.tmp.name)/'source.json';path.write_bytes(TWSE)
        with patch('quantlab.market_providers.build_opener',side_effect=AssertionError('local network')):
            result=execute_ui_operation('ui_market_refresh',{'local_path':str(path),'provider':'twse','format':'json'},self.paths)
        self.assertEqual(result['mode'],'official_local_import')
        self.assertEqual(load_cached('twse',self.paths.state/'market_cache').series[0].provenance.mode,'history')
        self.assertFalse((self.paths.state/'dataset.json').exists())

    def test_normal_backtest_uses_typed_inputs_without_json(self):
        self.window.strategy_form.fields['fast'].setText('7')
        self.window.backtest_form.fields['initial_cash'].setText('1234567')
        with patch.object(self.window,'start_job') as start:
            self.window.run_backtest()
        operation,payload=start.call_args.args
        self.assertEqual(operation,'ui_backtest')
        self.assertEqual(payload['parameters']['fast'],7)
        self.assertEqual(payload['config']['initial_cash'],'1234567')
        self.assertTrue(self.window.parameters.isHidden() or not self.window.parameters.isVisible())
        self.assertIsNone(payload['candidate'])

    def test_preferences_restart_no_consent_and_invalid_recovery(self):
        self.window.market.timeframe_combo.setCurrentIndex(2)
        self.window.market._indicator_widgets['RSI'][0].setChecked(True)
        self.window.save_settings()
        value=self.window.settings.load()
        self.assertEqual(value['market']['timeframe'],'5m')
        self.assertTrue(value['market']['indicators']['RSI']['enabled'])
        self.assertNotIn('network_opt_in',json.dumps(value))
        self.window.market.timeframe_combo.setCurrentIndex(0)
        self.window.settings.save(value);self.window.load_settings()
        self.assertEqual(self.window.market.timeframe_combo.currentData(),'5m')
        broken={**value,'market':{'version':999},'window':{'width':999999,'height':999999}}
        self.window.settings.save(broken);self.window.load_settings()
        self.assertIn('安全預設',self.window.status.text())
        self.assertEqual(self.window.settings.load(),broken)

    def test_paper_display_binds_fill_to_authoritative_order(self):
        intent={'contract_id':'TAIFEX:TMF:202610','side':'buy','quantity':1}
        account={'account_id':'test','cash':'123','positions':{'TAIFEX:TMF:202610':1},
            'orders':{'o':{'intent':intent,'status':'filled'}},
            'fills':{'f':{'order_id':'o','quantity':1,'price':'20000'}},'kill_switch':True,'reconciliation_required':True}
        self.window._show_account(account)
        self.assertEqual(self.window.market.positions_table.rowCount(),1)
        self.assertEqual(self.window.market.fills_table.item(0,1).text(),'TAIFEX:TMF:202610')
        self.assertIn('停止',self.window.market.trading_labels['risk'].text())
        self.window._show_account({'positions':{},'orders':{},'fills':{}})
        self.assertIn('未提供',self.window.paper_card.label.text())

    def test_manual_export_and_import_use_existing_campaign_without_network(self):
        from desktop_ui import execute_ui_operation
        from tests.test_research import inputs
        from quantlab.core import to_dict, content_hash, Dataset
        from quantlab.reporting import save_dataset
        from quantlab.strategies import builtin_strategies
        data, config = inputs()
        manifest=dict(data.manifest);manifest['manifest_hash']=content_hash(manifest)
        data=Dataset(data.bars,manifest,data.quality)
        config.update(max_improvements=0, max_trials=1, families=['trend'])
        config['ranking']['minimum']='-1000000'
        save_dataset(data,self.paths.state/'dataset.json')
        path=Path(self.tmp.name)/'request.json'
        with patch('quantlab.provider.HTTPTransport.__call__',side_effect=AssertionError('manual network')):
            exported=execute_ui_operation('ui_campaign',{'config':to_dict(config),'provider':{'mode':'manual'},'manual_export':str(path)},self.paths)
            self.assertTrue(path.exists());self.assertFalse((self.paths.state/'campaigns').exists())
            req=exported['request']
            response={k:req[k] for k in ('schema_version','request_id','data_hash','config_hash')}
            response['candidates']=[{'family':'trend','context_hash':req['families'][0]['context_hash'],'candidate':to_dict(builtin_strategies()[0])}]
            result=execute_ui_operation('ui_campaign',{'config':to_dict(config),'provider':{'mode':'manual','response_text':json.dumps(response)}},self.paths)
        self.assertEqual(result['attempts'][0]['status'],'evaluated')
        self.assertEqual(result['real_model_status'],'not_verified')
        self.assertTrue((self.paths.controls/'holdout-registry.sqlite3').exists())

    def test_corrupt_research_file_does_not_hide_independent_good_market_cache(self):
        from quantlab.market_providers import import_daily
        import_daily('twse',self.paths.state/'market_cache',TWSE,received_at=NOW)
        (self.paths.state/'dataset.json').write_text('{broken')
        self.window.refresh_views();self.window._busy(False)
        self.assertIn('驗證失敗',self.window.overview.text())
        self.assertFalse(self.window.run_button.isEnabled())
        self.assertEqual(self.window.market.selected_series().bars[-1].close,101)
        self.assertEqual((self.paths.state/'dataset.json').read_text(),'{broken')

    def test_restart_loads_saved_preferences_without_network(self):
        from desktop_ui import MainWindow
        self.window.market.timeframe_combo.setCurrentIndex(3)
        self.window.save_settings()
        with patch('quantlab.market_providers.build_opener',side_effect=AssertionError('restart network')):
            restored=MainWindow(self.paths,self.jobs,self.window.settings,self.window.backups)
        try:
            self.assertEqual(restored.market.timeframe_combo.currentData(),'15m')
            self.assertFalse(restored.ai_opt_in.isChecked())
            self.assertFalse(restored.paper_confirm.isChecked())
        finally: restored.close()

    def test_window_position_and_size_are_restored_with_offscreen_clamp(self):
        value=self.window.settings.load()
        value['window']={'x':999999,'y':-999999,'width':999999,'height':999999}
        self.window.settings.save(value);self.window.load_settings()
        available=self.window.screen().availableGeometry()
        self.assertGreaterEqual(self.window.x(),available.left())
        self.assertGreaterEqual(self.window.y(),available.top())
        self.assertLessEqual(self.window.width(),available.width())
        self.assertLessEqual(self.window.height(),available.height())
        self.window.save_settings()
        saved=self.window.settings.load()['window']
        self.assertIn('x',saved);self.assertIn('y',saved)

    def test_active_job_close_refusal_keeps_job_and_window(self):
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QMessageBox
        class Active:
            active=True
            def close(self):raise AssertionError('user refused close')
        old=self.window.jobs;self.window.jobs=Active()
        try:
            event=QCloseEvent()
            with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
        finally:self.window.jobs=old

    def test_latest_observed_cards_use_minute_only_history_and_preserve_newer_daily(self):
        from dataclasses import replace
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal
        from desktop_ui import latest_market_observations
        from quantlab.market import MarketSeries, QuoteSnapshot
        from quantlab.market_providers import parse_taifex_daily
        daily=parse_taifex_daily(json.dumps([ROW]).encode(),received_at=NOW)[0]
        def minute(date, price):
            start=datetime.fromisoformat(date+'T01:00:00+00:00')
            bar=replace(daily.bars[-1],trade_date=date,open=Decimal(price),high=Decimal(price),low=Decimal(price),close=Decimal(price),
                interval='1m',timestamp=start,end=start+timedelta(minutes=1),session_open=start,session_end=start+timedelta(hours=1))
            source=replace(daily.provenance,mode='history',as_of=date,coverage_start=date,coverage_end=date)
            return MarketSeries(daily.instrument,(bar,),source)
        old=minute('2026-10-07','99');new=minute('2026-10-09','111')
        self.assertIs(latest_market_observations([old])[0],old)
        self.assertIs(latest_market_observations([daily,old])[0],daily)
        self.assertIs(latest_market_observations([daily,new])[0],new)
        quote=QuoteSnapshot.from_series(latest_market_observations([daily,new])[0],stale=True)
        self.assertEqual(quote.mode,'history');self.assertTrue(quote.stale)
        self.assertIs(latest_market_observations([daily,minute('2026-10-08','111')])[0],daily)
        self.window.market.set_quote_series(latest_market_observations([old]),stale=True)
        self.assertIn('99.00',self.window.market.cards['MXF'].text())
        self.assertIn('過期快取',self.window.market.cards['MXF'].text())

    def test_synthetic_history_cannot_become_market_minutes(self):
        from desktop_ui import dataset_market_series
        from quantlab.reporting import synthetic_dataset
        with self.assertRaises(ValueError):dataset_market_series(synthetic_dataset(120),{'sessions':[],'version':'test'})

if __name__=='__main__':unittest.main()
