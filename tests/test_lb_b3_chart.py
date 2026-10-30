"""Cheap offscreen B3 chart contracts without window display or event loops."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QWidget
import shiboken6

from desktop_app.features.market.indicator_presenter import DEFAULT_INDICATORS
from desktop_app.features.market.dashboard import MarketDashboard
from desktop_app.strings.catalog import ui_text
from quantlab import indicators
from tests.test_desktop_market import series


NEW = ('ATR', 'SuperTrend', 'SAR', 'OBV', 'MA channel')


class ChartExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = MarketDashboard()
        self.addCleanup(shiboken6.delete, self.panel)

    def enable_new(self):
        config = deepcopy(DEFAULT_INDICATORS)
        for key in NEW:
            config[key]['enabled'] = True
        return config

    def test_old_config_roundtrip_and_new_parameters(self):
        old = self.panel.preferences()
        old['indicators'] = {k: v for k, v in old['indicators'].items() if k not in NEW}
        self.panel.restore_preferences(old)
        current = self.panel.preferences()
        self.assertEqual({k: v for k, v in current['indicators'].items() if k not in NEW}, old['indicators'])
        for key in NEW:
            self.assertEqual(current['indicators'][key], DEFAULT_INDICATORS[key])
            self.assertIn(key, self.panel._indicator_widgets)
        current['indicators'] = self.enable_new()
        self.panel.restore_preferences(current)
        self.assertEqual(self.panel.preferences(), current)
        for key, param, invalid in [
            ('ATR', 'period', True),
            ('SuperTrend', 'multiplier', float('nan')),
            ('SAR', 'step', 0.3),
            ('MA channel', 'percent', float('inf')),
        ]:
            bad = deepcopy(current)
            bad['indicators'][key][param] = invalid
            with self.assertRaises(ValueError):
                self.panel.restore_preferences(bad)
            self.assertEqual(self.panel.preferences(), current)

    def test_exact_labels_routing_and_failure_isolation(self):
        p = self.panel
        p.set_market_series(series())
        config = self.enable_new()
        p._apply_indicators(config)
        self.assertEqual(set(p.chart.panes), {'ATR(14)', 'OBV'})
        labels = {'SuperTrend(10,3)', 'SAR(0.02,0.2)', 'MA channel(20,2%) middle', 'MA channel(20,2%) upper', 'MA channel(20,2%) lower'}
        self.assertTrue(labels <= set(p.chart.overlays))
        for label in ('ATR(14)', 'SuperTrend(10,3)', 'SAR(0.02,0.2)', 'OBV', 'MA channel(20,2%)'):
            self.assertIn(label, p.indicator_summary.text())
        for function, key, label in [
            ('atr', 'ATR', 'ATR(14)'),
            ('supertrend', 'SuperTrend', 'SuperTrend(10,3)'),
            ('sar', 'SAR', 'SAR(0.02,0.2)'),
            ('obv', 'OBV', 'OBV'),
            ('ma_channel', 'MA channel', 'MA channel(20,2%) middle'),
        ]:
            with patch.object(indicators, function, side_effect=indicators.IndicatorResourceLimitError):
                p._apply_indicators(config)
                self.assertNotIn(label, p.chart.overlays | p.chart.panes)
                self.assertIn('MA5', p.chart.overlays)
                self.assertIn(p._indicator_failure_text([key]), p.message.text())
                self.assertIn(ui_text('market.apply_indicators.calculation_failed'), p.indicator_summary.text())
                self.assertEqual(len(p.chart.panes) + len(p.chart.overlays), 11 - (3 if key == 'MA channel' else 1))

    def test_new_widget_names_are_registered(self):
        import json
        from pathlib import Path

        fixture = set(json.loads(Path('tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8')))
        for widget in self.panel.findChildren(QWidget):
            name = widget.objectName()
            if any(key in name for key in NEW):
                self.assertIn(name, fixture)

    def test_control_parameters_render_and_sar_rollback(self):
        p = self.panel
        p.set_market_series(series())
        for key in NEW:
            p._indicator_widgets[key][0].setChecked(True)
        p._indicator_widgets['ATR'][1]['period'].setValue(2)
        self.assertIn('ATR(2)', p.chart.panes)
        self.assertIn('ATR(2)', p.indicator_summary.text())
        previous = p.preferences()
        p._indicator_widgets['SAR'][1]['step'].setValue(0.3)
        self.assertEqual(p.preferences(), previous)
        self.assertEqual(p._indicator_widgets['SAR'][1]['step'].value(), 0.02)
        self.assertEqual(p.message.text(), ui_text('market.indicator.invalid_sar'))
