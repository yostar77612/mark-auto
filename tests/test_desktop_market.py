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
    instrument = InstrumentRef('TAIFEX', symbol, f'TAIFEX:{native}:202610', '202610')
    bars = tuple(
        MarketBar(instrument, f'2026-10-0{i}', 'day', Decimal(100), Decimal(110), Decimal(90), Decimal(100 + i), 100, interval='session') for i in range(1, 4)
    )
    source = SourceProvenance(
        'https://example.org/synthetic',
        'a' * 64,
        '合成測試',
        'https://example.org/license',
        datetime(2026, 10, 4, tzinfo=timezone.utc),
        '2026-10-03',
        '2026-10-01',
        '2026-10-03',
    )
    return MarketSeries(instrument, bars, source)


@unittest.skipUnless(HAS_QT, "Install pinned desktop requirements to test Qt widgets")
class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = MarketDashboard()
        self.addCleanup(self.dispose, self.panel)

    def dispose(self, widget):
        import shiboken6

        widget.close()
        shiboken6.delete(widget)
        self.app.processEvents()

    def test_empty_offline_and_refresh_is_only_signal(self):
        self.assertIn('離線', self.panel.source_status.text())
        self.assertEqual(self.panel.positions_table.rowCount(), 0)
        self.assertIn('未知', self.panel.trading_labels['strategy'].text())
        spy = QSignalSpy(self.panel.refresh_requested)
        self.panel.refresh_button.click()
        self.assertEqual(spy.count(), 1)
        self.assertFalse(self.panel.preferences().get('network_enabled', False))

    def test_actual_contract_and_daily_gate(self):
        self.panel.set_market_series(series())
        self.assertEqual(self.panel.contract_combo.currentData(), 'TAIFEX:TMF:202610')
        self.assertIn('2026-10-03', self.panel.source_status.text())
        self.panel.timeframe_combo.setCurrentIndex(self.panel.timeframe_combo.findData('1m'))
        self.assertIn('不能', self.panel.message.text())
        self.assertEqual(self.panel.timeframe_combo.currentData(), '1d')

    def test_preferences_roundtrip_and_rejection(self):
        self.panel.set_market_series(series())
        prefs = self.panel.preferences()
        other = MarketDashboard()
        self.addCleanup(self.dispose, other)
        other.restore_preferences(prefs)
        self.assertEqual(other.preferences(), prefs)
        for bad in (
            {'version': 1, 'network_enabled': True},
            {'version': 1, 'watchlist': ['TAIFEX:TMF:NEAR']},
            {'version': 1, 'indicators': {'MA': {'enabled': True, 'periods': [0]}}},
        ):
            with self.assertRaises(ValueError):
                self.panel.restore_preferences(bad)
        self.assertEqual(self.panel.preferences(), prefs)

    def test_watchlist_search_add_remove(self):
        self.panel.set_market_series((series(), series('MXF', 'MTX')))
        self.panel.search.setText('MXF')
        self.assertEqual(self.panel.catalog_combo.count(), 1)
        self.panel.add_button.click()
        self.assertIn('TAIFEX:MTX:202610', self.panel.preferences()['watchlist'])
        self.panel.watchlist.setCurrentRow(self.panel.watchlist.count() - 1)
        self.panel.remove_button.click()
        self.assertNotIn('TAIFEX:MTX:202610', self.panel.preferences()['watchlist'])

    def test_host_tables_are_atomic_and_no_fake_state(self):
        self.panel.set_trading_status(strategy='未選擇', paper='已停止', risk='封鎖')
        self.panel.set_account_tables(positions=[{'contract_id': 'TAIFEX:TMF:202610', 'quantity': 1, 'average_price': '103'}])
        self.assertEqual(self.panel.positions_table.rowCount(), 1)
        with self.assertRaises(ValueError):
            self.panel.set_account_tables(positions=[{'contract_id': 'oops', 'quantity': True}])
        self.assertEqual(self.panel.positions_table.rowCount(), 1)

    def test_all_indicator_controls_and_stale_snapshot(self):
        self.panel.set_market_series(series(), stale=True, error='來源更新失敗')
        for check, controls in self.panel._indicator_widgets.values():
            check.setChecked(True)
        self.assertIn('MACD histogram 1×', self.panel.chart.panes)
        self.assertEqual(self.panel.chart.pane_styles['MACD histogram 1×'], 'histogram')
        self.assertNotIn('MACD histogram', self.panel.chart.panes)
        self.assertIn('VWAP 估計', self.panel.chart.overlays)
        self.assertTrue(all(value is None for value in self.panel.chart.overlays['VWAP 估計']))
        self.assertIn('過期快取', self.panel.cards['TMF'].text())
        self.assertIn('來源更新失敗', self.panel.message.text())
        self.panel.set_market_series(())
        self.assertFalse(self.panel.chart.bars)
        self.panel._indicator_widgets['EMA'][0].setChecked(False)
        self.assertFalse(self.panel.chart.bars)

    def test_sort_watchlist_and_resize(self):
        self.panel.set_market_series((series(), series('MXF', 'MTX')))
        self.panel.catalog_combo.setCurrentIndex(1)
        self.panel.add_button.click()
        self.panel.watchlist.setCurrentRow(1)
        self.panel._move_watch(-1)
        self.assertEqual(self.panel.preferences()['watchlist'][0], 'TAIFEX:MTX:202610')
        self.panel.resize(1093, 614)
        self.panel.show()
        self.app.processEvents()
        self.assertTrue(self.panel.refresh_button.isVisible())
        self.assertGreater(self.panel.chart.width(), 250)

    def test_missing_minute_resets_indicator_warmup(self):
        source = series()
        start = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
        bars = tuple(
            MarketBar(
                source.instrument,
                '2026-10-01',
                'day',
                Decimal(100),
                Decimal(110),
                Decimal(90),
                Decimal(100 + i),
                100,
                interval='1m',
                timestamp=start + timedelta(minutes=i),
                end=start + timedelta(minutes=i + 1),
                session_open=start,
                session_end=start + timedelta(hours=1),
            )
            for i in (0, 1, 3, 4)
        )
        minute = MarketSeries(source.instrument, bars, source.provenance)
        self.panel.set_market_series(minute)
        self.panel.timeframe_combo.setCurrentIndex(0)
        self.panel._indicator_widgets['MA'][1]['periods_0'].setValue(2)
        values = self.panel.chart.overlays['MA2']
        self.assertEqual(values, (None, Decimal('100.5'), None, Decimal('103.5')))

    def test_explicit_empty_watchlist_stays_empty_after_refresh(self):
        self.panel.set_market_series(series())
        self.panel.watchlist.setCurrentRow(0)
        self.panel.remove_button.click()
        self.panel.set_market_series(series())
        self.assertEqual(self.panel.preferences()['watchlist'], [])
        self.panel.restore_preferences(self.panel.preferences())
        self.panel.set_market_series(series())
        self.assertEqual(self.panel.preferences()['watchlist'], [])

    def test_main_view_is_human_readable_and_diagnostics_expand(self):
        data = series()
        self.panel.set_market_series(data)
        visible_text = ' '.join(
            [self.panel.source_status.text(), self.panel.message.text(), self.panel.cards['TMF'].text(), self.panel.contract_combo.currentText()]
        )
        for technical in ('TAIFEX:', 'exchange_trade_date_only', 'https://', 'sha256'):
            self.assertNotIn(technical, visible_text)
        self.assertIn('微臺指 2026/10', self.panel.cards['TMF'].text())
        self.assertIn('臺灣期貨交易所', self.panel.source_status.text())
        self.assertIn('https://example.org/synthetic', self.panel.diagnostics.toPlainText())
        self.assertTrue(self.panel.diagnostics.isHidden())
        self.panel.diagnostics_button.click()
        self.assertFalse(self.panel.diagnostics.isHidden())
        self.assertIs(self.panel.selected_series(), data)

    def test_cards_keep_latest_daily_while_chart_uses_older_history(self):
        from dataclasses import replace

        old = series()
        latest_bar = replace(old.bars[-1], trade_date='2026-10-08', close=Decimal(109))
        source = replace(old.provenance, as_of='2026-10-08', coverage_end='2026-10-08')
        latest = MarketSeries(old.instrument, old.bars + (latest_bar,), source)
        self.panel.set_market_series(old)
        self.panel.set_quote_series(latest)
        self.assertIn('2026-10-08', self.panel.cards['TMF'].text())
        self.assertIn('109.00', self.panel.cards['TMF'].text())
        self.assertIs(self.panel.selected_series(), old)
        self.assertEqual(self.panel.chart.bars[-1].trade_date, '2026-10-03')
        self.panel.set_market_series(old, stale=True)
        self.assertIn('2026-10-08', self.panel.cards['TMF'].text())
        self.assertNotIn('過期快取', self.panel.cards['TMF'].text())
        with self.assertRaises(ValueError):
            self.panel.set_quote_series((latest, latest))
        self.assertIn('2026-10-08', self.panel.cards['TMF'].text())
        self.panel.set_quote_series(())
        self.assertIn('尚無可用資料', self.panel.cards['TMF'].text())
        self.assertTrue(self.panel.chart.bars)


@unittest.skipUnless(HAS_QT, 'Install pinned desktop requirements to test Qt widgets')
class IndicatorWorkBoundaryTests(unittest.TestCase):
    """Synthetic-only normal-control regressions frozen before the AUTO fix.

    Editing parameters is atomic. A later data/timeframe change can instead make
    an indicator explicitly unavailable, without discarding new candles or
    claiming that old indicator curves use the new data/settings.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        instrument = InstrumentRef('TAIFEX', 'TX', 'TAIFEX:TX:202610', '202610')
        bars = []
        for n in range(5001):
            timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=n // 300, minutes=n % 300)
            opening = timestamp.replace(hour=0, minute=0)
            bars.append(
                MarketBar(
                    instrument,
                    timestamp.date().isoformat(),
                    'day',
                    Decimal(100),
                    Decimal(101),
                    Decimal(99),
                    Decimal(100),
                    1,
                    interval='1m',
                    timestamp=timestamp,
                    end=timestamp + timedelta(minutes=1),
                    session_open=opening,
                    session_end=opening + timedelta(minutes=300),
                    source_id='synthetic',
                )
            )
        source = SourceProvenance(
            'https://example.org/synthetic',
            'a' * 64,
            '合成測試，非真實行情',
            'https://example.org/license',
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            bars[-1].trade_date,
            bars[0].trade_date,
            bars[-1].trade_date,
            mode='history',
        )
        cls.large = MarketSeries(instrument, tuple(bars), source)
        cls.small = MarketSeries(instrument, tuple(bars[:1000]), source)

    def setUp(self):
        import sys

        self.panel = MarketDashboard()
        self.addCleanup(DashboardTests.dispose, self, self.panel)
        self.panel.timeframe_combo.setCurrentIndex(self.panel.timeframe_combo.findData('1m'))
        self.panel.set_market_series(self.large)
        self.errors = []
        old = sys.excepthook
        self.addCleanup(setattr, sys, 'excepthook', old)
        sys.excepthook = lambda kind, value, trace: self.errors.append(str(value))

    def check_parameter_rollback(self, key):
        p = self.panel
        enabled, controls = p._indicator_widgets[key]
        enabled.setChecked(True)
        prefs = p.preferences()
        old_overlays = dict(p.chart.overlays)
        old_panes = dict(p.chart.panes)
        saved = QSignalSpy(p.preferences_changed)
        changed = QSignalSpy(controls['period'].valueChanged)
        observed = []
        controls['period'].valueChanged.connect(lambda value: observed.append(value))
        controls['period'].setValue(1000)
        self.assertEqual(self.errors, [])
        self.assertEqual(p.preferences(), prefs)
        self.assertEqual(controls['period'].value(), prefs['indicators'][key]['period'])
        self.assertEqual(dict(p.chart.overlays), old_overlays)
        self.assertEqual(dict(p.chart.panes), old_panes)
        self.assertEqual(saved.count(), 0)
        self.assertEqual(changed.count(), 1, 'rollback must block nested valueChanged signals')
        self.assertEqual(observed, [1000])
        self.assertIn(key, p.message.text())
        self.assertIn('限制', p.message.text())
        self.assertIn('還原', p.message.text())
        controls['period'].setValue(21)
        self.assertEqual(self.errors, [])
        self.assertEqual(saved.count(), 1)
        self.assertEqual(p.preferences()['indicators'][key]['period'], 21)
        self.assertNotIn('無法計算', p.message.text())
        self.assertEqual(len(p.chart.bars), 5001)
        if key == 'Bollinger':
            self.assertEqual(next(i for i, v in enumerate(p.chart.overlays['BB middle']) if v is not None), 20)

    def test_bollinger_5001_by_1000_atomic_rollback_and_recovery(self):
        self.check_parameter_rollback('Bollinger')

    def test_kd_5001_by_1000_atomic_rollback_and_recovery(self):
        self.check_parameter_rollback('KD')

    def test_data_growth_keeps_new_candles_and_other_indicators(self):
        p = self.panel
        p.set_market_series(self.small)
        enabled, controls = p._indicator_widgets['Bollinger']
        controls['period'].setValue(1000)
        enabled.setChecked(True)
        self.assertIsNotNone(p.chart.overlays['BB middle'][-1])
        saved = QSignalSpy(p.preferences_changed)
        p.set_market_series(self.large)
        self.assertEqual(self.errors, [])
        self.assertEqual(p.chart.bars, p._display_bars)
        self.assertEqual(len(p.chart.bars), 5001)
        self.assertNotIn('BB middle', p.chart.overlays)
        self.assertIsNotNone(p.chart.overlays['MA5'][-1])
        self.assertEqual(controls['period'].value(), 1000)
        self.assertEqual(p.preferences()['indicators']['Bollinger']['period'], 1000)
        self.assertIn('Bollinger', p.message.text())
        self.assertIn('未顯示', p.message.text())
        self.assertEqual(saved.count(), 0)
        p.set_market_series(self.small)
        self.assertIsNotNone(p.chart.overlays['BB middle'][-1])
        self.assertNotIn('無法計算', p.message.text())

    def test_timeframe_expansion_omits_unavailable_kd(self):
        p = self.panel
        p.timeframe_combo.setCurrentIndex(p.timeframe_combo.findData('5m'))
        enabled, controls = p._indicator_widgets['KD']
        controls['period'].setValue(1000)
        enabled.setChecked(True)
        self.assertIsNotNone(p.chart.panes['KD k'][-1])
        p.timeframe_combo.setCurrentIndex(p.timeframe_combo.findData('1m'))
        self.assertEqual(self.errors, [])
        self.assertEqual(len(p.chart.bars), 5001)
        self.assertNotIn('KD k', p.chart.panes)
        self.assertIsNotNone(p.chart.overlays['MA5'][-1])
        self.assertIn('KD', p.message.text())
        self.assertIn('未顯示', p.message.text())
        self.assertEqual(p.preferences()['indicators']['KD']['period'], 1000)

    def test_saved_parameters_are_safe_on_large_snapshot_and_recover(self):
        p = self.panel
        prefs = p.preferences()
        for key in ('Bollinger', 'KD'):
            prefs['indicators'][key].update(enabled=True, period=1000)
        p.restore_preferences(prefs)
        p.set_market_series(self.large)
        self.assertEqual(self.errors, [])
        self.assertEqual(p.preferences(), prefs)
        self.assertNotIn('BB middle', p.chart.overlays)
        self.assertNotIn('KD k', p.chart.panes)
        self.assertIsNotNone(p.chart.overlays['MA5'][-1])
        self.assertIn('Bollinger', p.message.text())
        self.assertIn('KD', p.message.text())
        p.set_market_series(self.small)
        self.assertIsNotNone(p.chart.overlays['BB middle'][-1])
        self.assertIsNotNone(p.chart.panes['KD k'][-1])
        self.assertNotIn('無法計算', p.message.text())

    def test_macd_invalid_edit_rolls_back_without_recursive_signals(self):
        p = self.panel
        _, controls = p._indicator_widgets['MACD']
        prefs = p.preferences()
        saved = QSignalSpy(p.preferences_changed)
        changed = QSignalSpy(controls['fast'].valueChanged)
        controls['fast'].setValue(controls['slow'].value())
        self.assertEqual(self.errors, [])
        self.assertEqual(p.preferences(), prefs)
        self.assertEqual(controls['fast'].value(), prefs['indicators']['MACD']['fast'])
        self.assertEqual(saved.count(), 0)
        self.assertEqual(changed.count(), 1)
        self.assertIn('MACD', p.message.text())

    def test_core_work_cap_and_widget_domain_unchanged(self):
        from quantlab import indicators

        self.assertEqual(indicators.MAX_WINDOW_WORK, 5_000_000)
        for key in ('Bollinger', 'KD'):
            controls = self.panel._indicator_widgets[key][1]
            self.assertEqual((controls['period'].minimum(), controls['period'].maximum()), (1, 1000))
        values = (Decimal(100),) * 5001
        self.assertTrue(issubclass(indicators.IndicatorResourceLimitError, ValueError))
        with self.assertRaisesRegex(indicators.IndicatorResourceLimitError, 'work limit'):
            indicators.bollinger(values, period=1000)
        with self.assertRaisesRegex(indicators.IndicatorResourceLimitError, 'work limit'):
            indicators.kd(values, values, values, period=1000)
        with self.assertRaisesRegex(indicators.IndicatorResourceLimitError, 'observation limit'):
            indicators.sma((Decimal(100),) * 100001)
        with self.assertRaises(ValueError) as caught:
            indicators.sma([True])
        self.assertNotIsInstance(caught.exception, indicators.IndicatorResourceLimitError)

    def test_two_unavailable_indicators_can_be_repaired_individually(self):
        p = self.panel
        prefs = p.preferences()
        for key in ('Bollinger', 'KD'):
            prefs['indicators'][key].update(enabled=True, period=1000)
        p.restore_preferences(prefs)
        saved = QSignalSpy(p.preferences_changed)
        p._indicator_widgets['KD'][1]['period'].setValue(20)
        self.assertEqual(self.errors, [])
        self.assertEqual(p.preferences()['indicators']['KD']['period'], 20)
        self.assertIsNotNone(p.chart.panes['KD k'][-1])
        self.assertNotIn('BB middle', p.chart.overlays)
        self.assertIn('Bollinger', p.message.text())
        self.assertNotIn('KD 無法', p.message.text())
        p._indicator_widgets['Bollinger'][0].setChecked(False)
        self.assertFalse(p.preferences()['indicators']['Bollinger']['enabled'])
        self.assertEqual(saved.count(), 2)
        self.assertNotIn('無法計算', p.message.text())
        self.assertIsNotNone(p.chart.panes['KD k'][-1])

    def test_two_unavailable_indicators_can_be_disabled_individually(self):
        p = self.panel
        prefs = p.preferences()
        for key in ('Bollinger', 'KD'):
            prefs['indicators'][key].update(enabled=True, period=1000)
        p.restore_preferences(prefs)
        p._indicator_widgets['Bollinger'][0].setChecked(False)
        self.assertFalse(p.preferences()['indicators']['Bollinger']['enabled'])
        self.assertNotIn('BB middle', p.chart.overlays)
        self.assertNotIn('KD k', p.chart.panes)
        self.assertIn('KD', p.message.text())
        p._indicator_widgets['KD'][1]['period'].setValue(20)
        self.assertEqual(p.preferences()['indicators']['KD']['period'], 20)
        self.assertIsNotNone(p.chart.panes['KD k'][-1])
        self.assertNotIn('無法計算', p.message.text())
        self.assertEqual(self.errors, [])

    def test_unexpected_value_error_is_not_mislabeled_as_resource_limit(self):
        from unittest.mock import patch

        p = self.panel
        original = p.message.text()
        with patch('desktop_market.indicators.sma', side_effect=ValueError('INTERNAL BUG SENTINEL')):
            with self.assertRaisesRegex(ValueError, 'INTERNAL BUG SENTINEL'):
                p._apply_indicators()
        self.assertEqual(p.message.text(), original)
        self.assertNotIn('限制', p.message.text())
