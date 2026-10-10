"""Actual instantiated host disclosures; synthetic offline engineering fixtures."""
import unittest
from unittest.mock import patch
from tests import test_desktop_ui as support

@unittest.skipUnless(support.HAS_QT,'Pinned Qt needed')
class MarketAcceptanceLabels(unittest.TestCase):
    setUpClass=support.NativeDesktopTests.__dict__['setUpClass']
    setUp=support.NativeDesktopTests.setUp
    cleanup_window=support.NativeDesktopTests.cleanup_window

    def test_actual_paper_page_visible_readonly_limits_match_enforced_broker(self):
        from desktop_ui import _paper,paper_risk_limits,write_json
        from PySide6.QtWidgets import QLabel
        w=self.window;label=w.findChild(QLabel,'paper_fixed_risk_summary')
        self.assertIsNotNone(label)
        for index in range(w.stack.count()):
            if w.stack.widget(index).isAncestorOf(label):w.navigation.setCurrentRow(index);break
        self.app.processEvents()
        self.assertTrue(label.isVisible())
        self.assertFalse(label.visibleRegion().isEmpty())
        self.assertTrue(w.stack.currentWidget().isAncestorOf(label))
        limits=paper_risk_limits()
        for text in (f'部位最多 {limits.max_position} 口',f'單筆最多 {limits.max_order_quantity} 口',
            f'每日損失上限 {limits.max_daily_loss} TWD',f'報價最多 {limits.max_quote_age_seconds} 秒',
            f'連續虧損上限 {limits.max_consecutive_losses} 次',f'{limits.window_seconds} 秒內最多 {limits.max_orders_per_window} 筆',
            '唯讀','停止新委託不會平倉'):
            self.assertIn(text,label.text())
        write_json(self.paths.state/'paper_policy.json',{'contract_id':'TAIFEX:TMF:202601','risk_sessions':[],'margin_schedule':[]})
        with patch('quantlab.paper.PaperBroker') as broker:_paper(self.paths.state)
        self.assertEqual(broker.call_args.kwargs['limits'],limits)

    def test_actual_dashboard_chart_discloses_unscaled_macd_histogram(self):
        from tests.test_desktop_market import series
        from quantlab.indicators import macd
        from dataclasses import replace
        from decimal import Decimal
        fixture=series();fixture=replace(fixture,bars=fixture.bars[:2]+(replace(fixture.bars[2],close=Decimal(105)),))
        w=self.window;w.navigation.setCurrentRow(0);w.market.set_market_series(fixture)
        prefs=w.market.preferences();prefs['indicators']['MACD']={'enabled':True,'fast':1,'slow':2,'signal':2}
        w.market.restore_preferences(prefs)
        self.app.processEvents()
        self.assertTrue(w.market.chart.isVisible())
        self.assertIn('MACD histogram 1×',w.market.chart.panes)
        self.assertEqual(w.market.chart.pane_styles['MACD histogram 1×'],'histogram')
        actual=w.market.selected_series()
        expected=macd([bar.close for bar in actual.bars],fast=1,slow=2,signal=2)['histogram']
        self.assertTrue(any(value is not None and value != 0 for value in expected))
        self.assertEqual(w.market.chart.panes['MACD histogram 1×'],expected)
