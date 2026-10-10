"""Frozen dashboard checks: empty never invents quotes, real identity selection,
explicit refresh, daily cannot produce minutes, validated preferences and host state.
Fixtures below are synthetic engineering data, never shipped market observations.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import importlib.util
from datetime import datetime, timezone, timedelta
from decimal import Decimal
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QSignalSpy
    from desktop_market import MarketDashboard
from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance


def series(symbol='TMF', native='TMF'):
    instrument=InstrumentRef('TAIFEX',symbol,f'TAIFEX:{native}:202610','202610')
    bars=tuple(MarketBar(instrument,f'2026-10-0{i}','day',Decimal(100),Decimal(110),Decimal(90),Decimal(100+i),100,interval='session') for i in range(1,4))
    source=SourceProvenance('https://example.org/synthetic','a'*64,'合成測試','https://example.org/license',datetime(2026,10,4,tzinfo=timezone.utc),'2026-10-03','2026-10-01','2026-10-03')
    return MarketSeries(instrument,bars,source)


@unittest.skipUnless(HAS_QT, "Install pinned desktop requirements to test Qt widgets")
class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.panel=MarketDashboard(); self.addCleanup(self.dispose,self.panel)
    def dispose(self, widget):
        import shiboken6
        widget.close(); shiboken6.delete(widget); self.app.processEvents()
    def test_empty_offline_and_refresh_is_only_signal(self):
        self.assertIn('離線',self.panel.source_status.text())
        self.assertEqual(self.panel.positions_table.rowCount(),0)
        self.assertIn('未知',self.panel.trading_labels['strategy'].text())
        spy=QSignalSpy(self.panel.refresh_requested)
        self.panel.refresh_button.click()
        self.assertEqual(spy.count(),1)
        self.assertFalse(self.panel.preferences().get('network_enabled',False))
    def test_actual_contract_and_daily_gate(self):
        self.panel.set_market_series(series())
        self.assertEqual(self.panel.contract_combo.currentData(),'TAIFEX:TMF:202610')
        self.assertIn('2026-10-03',self.panel.source_status.text())
        self.panel.timeframe_combo.setCurrentIndex(self.panel.timeframe_combo.findData('1m'))
        self.assertIn('不能',self.panel.message.text())
        self.assertEqual(self.panel.timeframe_combo.currentData(),'1d')
    def test_preferences_roundtrip_and_rejection(self):
        self.panel.set_market_series(series())
        prefs=self.panel.preferences()
        other=MarketDashboard(); self.addCleanup(self.dispose,other)
        other.restore_preferences(prefs)
        self.assertEqual(other.preferences(),prefs)
        for bad in ({'version':1,'network_enabled':True},{'version':1,'watchlist':['TAIFEX:TMF:NEAR']},{'version':1,'indicators':{'MA':{'enabled':True,'periods':[0]}}}):
            with self.assertRaises(ValueError): self.panel.restore_preferences(bad)
        self.assertEqual(self.panel.preferences(),prefs)
    def test_watchlist_search_add_remove(self):
        self.panel.set_market_series((series(),series('MXF','MTX')))
        self.panel.search.setText('MXF')
        self.assertEqual(self.panel.catalog_combo.count(),1)
        self.panel.add_button.click()
        self.assertIn('TAIFEX:MTX:202610',self.panel.preferences()['watchlist'])
        self.panel.watchlist.setCurrentRow(self.panel.watchlist.count()-1)
        self.panel.remove_button.click()
        self.assertNotIn('TAIFEX:MTX:202610',self.panel.preferences()['watchlist'])
    def test_host_tables_are_atomic_and_no_fake_state(self):
        self.panel.set_trading_status(strategy='未選擇',paper='已停止',risk='封鎖')
        self.panel.set_account_tables(positions=[{'contract_id':'TAIFEX:TMF:202610','quantity':1,'average_price':'103'}])
        self.assertEqual(self.panel.positions_table.rowCount(),1)
        with self.assertRaises(ValueError): self.panel.set_account_tables(positions=[{'contract_id':'oops','quantity':True}])
        self.assertEqual(self.panel.positions_table.rowCount(),1)

    def test_all_indicator_controls_and_stale_snapshot(self):
        self.panel.set_market_series(series(),stale=True,error='來源更新失敗')
        for check,controls in self.panel._indicator_widgets.values(): check.setChecked(True)
        self.assertIn('MACD histogram',self.panel.chart.panes)
        self.assertIn('VWAP 估計',self.panel.chart.overlays)
        self.assertTrue(all(value is None for value in self.panel.chart.overlays['VWAP 估計']))
        self.assertIn('過期快取',self.panel.cards['TMF'].text())
        self.assertIn('來源更新失敗',self.panel.message.text())
        self.panel.set_market_series(())
        self.assertFalse(self.panel.chart.bars)
        self.panel._indicator_widgets['EMA'][0].setChecked(False)
        self.assertFalse(self.panel.chart.bars)
    def test_sort_watchlist_and_resize(self):
        self.panel.set_market_series((series(),series('MXF','MTX')))
        self.panel.catalog_combo.setCurrentIndex(1); self.panel.add_button.click()
        self.panel.watchlist.setCurrentRow(1); self.panel._move_watch(-1)
        self.assertEqual(self.panel.preferences()['watchlist'][0],'TAIFEX:MTX:202610')
        self.panel.resize(1093,614); self.panel.show(); self.app.processEvents()
        self.assertTrue(self.panel.refresh_button.isVisible())
        self.assertGreater(self.panel.chart.width(),250)

    def test_missing_minute_resets_indicator_warmup(self):
        source=series(); start=datetime(2026,10,1,1,tzinfo=timezone.utc)
        bars=tuple(MarketBar(source.instrument,'2026-10-01','day',Decimal(100),Decimal(110),Decimal(90),Decimal(100+i),100,interval='1m',timestamp=start+timedelta(minutes=i),end=start+timedelta(minutes=i+1),session_open=start,session_end=start+timedelta(hours=1)) for i in (0,1,3,4))
        minute=MarketSeries(source.instrument,bars,source.provenance)
        self.panel.set_market_series(minute)
        self.panel.timeframe_combo.setCurrentIndex(0)
        self.panel._indicator_widgets['MA'][1]['periods_0'].setValue(2)
        values=self.panel.chart.overlays['MA2']
        self.assertEqual(values,(None,Decimal('100.5'),None,Decimal('103.5')))

    def test_explicit_empty_watchlist_stays_empty_after_refresh(self):
        self.panel.set_market_series(series())
        self.panel.watchlist.setCurrentRow(0); self.panel.remove_button.click()
        self.panel.set_market_series(series())
        self.assertEqual(self.panel.preferences()['watchlist'],[])
        self.panel.restore_preferences(self.panel.preferences())
        self.panel.set_market_series(series())
        self.assertEqual(self.panel.preferences()['watchlist'],[])

    def test_main_view_is_human_readable_and_diagnostics_expand(self):
        data=series(); self.panel.set_market_series(data)
        visible_text=' '.join([self.panel.source_status.text(),self.panel.message.text(),self.panel.cards['TMF'].text(),self.panel.contract_combo.currentText()])
        for technical in ('TAIFEX:','exchange_trade_date_only','https://','sha256'):
            self.assertNotIn(technical,visible_text)
        self.assertIn('微臺指 2026/10',self.panel.cards['TMF'].text())
        self.assertIn('臺灣期貨交易所',self.panel.source_status.text())
        self.assertIn('https://example.org/synthetic',self.panel.diagnostics.toPlainText())
        self.assertTrue(self.panel.diagnostics.isHidden())
        self.panel.diagnostics_button.click()
        self.assertFalse(self.panel.diagnostics.isHidden())
        self.assertIs(self.panel.selected_series(),data)

    def test_cards_keep_latest_daily_while_chart_uses_older_history(self):
        from dataclasses import replace
        old=series()
        latest_bar=replace(old.bars[-1],trade_date='2026-10-08',close=Decimal(109))
        source=replace(old.provenance,as_of='2026-10-08',coverage_end='2026-10-08')
        latest=MarketSeries(old.instrument,old.bars+(latest_bar,),source)
        self.panel.set_market_series(old)
        self.panel.set_quote_series(latest)
        self.assertIn('2026-10-08',self.panel.cards['TMF'].text())
        self.assertIn('109.00',self.panel.cards['TMF'].text())
        self.assertIs(self.panel.selected_series(),old)
        self.assertEqual(self.panel.chart.bars[-1].trade_date,'2026-10-03')
        self.panel.set_market_series(old,stale=True)
        self.assertIn('2026-10-08',self.panel.cards['TMF'].text())
        self.assertNotIn('過期快取',self.panel.cards['TMF'].text())
        with self.assertRaises(ValueError): self.panel.set_quote_series((latest,latest))
        self.assertIn('2026-10-08',self.panel.cards['TMF'].text())
        self.panel.set_quote_series(())
        self.assertIn('尚無可用資料',self.panel.cards['TMF'].text())
        self.assertTrue(self.panel.chart.bars)
