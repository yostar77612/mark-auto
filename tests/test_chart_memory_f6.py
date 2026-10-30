"""Cheap read-only chart preference round trips and hostile settings boundaries."""

import json
import unittest
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import shiboken6
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from desktop_app.features.market.chart_memory import ChartMemory
from desktop_app.features.market.dashboard import DEFAULT_INDICATORS, MarketDashboard, _identity
from quantlab.chart_data import TIMEFRAMES
from quantlab.core import content_hash, to_dict
from tests.test_desktop_market import series


def snapshot(native='TMF', count=300):
    item = series(native, native)
    bars = tuple(replace(item.bars[0], trade_date=(date(2025, 1, 1) + timedelta(days=i)).isoformat()) for i in range(count))
    return replace(
        item, bars=bars, provenance=replace(item.provenance, as_of=bars[-1].trade_date, coverage_start=bars[0].trade_date, coverage_end=bars[-1].trade_date)
    )


class ChartMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self):
        panel = MarketDashboard()
        self.addCleanup(shiboken6.delete, panel)
        return panel

    def switch(self, panel, instrument):
        panel.contract_combo.setCurrentIndex(panel.contract_combo.findData(instrument))

    def timeframe(self, panel, value):
        panel.timeframe_combo.setCurrentIndex(panel.timeframe_combo.findData(value))

    def test_instrument_roundtrip_and_current_defaults(self):
        p = self.panel()
        a, b = snapshot(), snapshot('TX')
        p.set_market_series((a, b))
        p.chart._start, p.chart._count = 30, 25
        p._indicator_widgets['RSI'][0].setChecked(True)
        self.switch(p, b.instrument.contract_id)
        self.assertEqual(p.chart.visible_range, (200, 300))
        self.assertTrue(p._indicator_widgets['RSI'][0].isChecked())
        p.chart._start, p.chart._count = 70, 40
        p._indicator_widgets['RSI'][0].setChecked(False)
        self.switch(p, a.instrument.contract_id)
        self.assertEqual(p.chart.visible_range, (30, 55))
        self.assertTrue(p._indicator_widgets['RSI'][0].isChecked())
        self.switch(p, b.instrument.contract_id)
        self.assertEqual(p.chart.visible_range, (70, 110))
        self.assertFalse(p._indicator_widgets['RSI'][0].isChecked())

    def test_timeframe_roundtrip_and_restart_after_data_load(self):
        p = self.panel()
        item = snapshot()
        p.set_market_series(item)
        p.chart._start, p.chart._count = 40, 20
        p._indicator_widgets['RSI'][0].setChecked(True)
        self.timeframe(p, '1w')
        p.chart._start, p.chart._count = 2, 10
        p._indicator_widgets['RSI'][0].setChecked(False)
        self.timeframe(p, '1d')
        self.assertEqual(p.chart.visible_range, (40, 60))
        self.assertTrue(p._indicator_config['RSI']['enabled'])
        self.timeframe(p, '1w')
        self.assertEqual(p.chart.visible_range, (2, 12))
        self.assertFalse(p._indicator_config['RSI']['enabled'])
        saved = p.preferences()
        q = self.panel()
        refresh = QSignalSpy(q.refresh_requested)
        q.restore_preferences(saved)
        q.set_market_series(item)
        self.assertEqual(q.chart.visible_range, (2, 12))
        self.assertFalse(q._indicator_config['RSI']['enabled'])
        self.assertEqual(refresh.count(), 0)

    def test_default_enablement_is_restored_after_other_context_edit(self):
        p = self.panel()
        p.set_market_series((snapshot(), snapshot('TX')))
        original = {k for k, v in p._indicator_config.items() if v['enabled']}
        self.switch(p, 'TAIFEX:TX:202610')
        p._indicator_widgets['RSI'][0].setChecked(True)
        self.switch(p, 'TAIFEX:TMF:202610')
        self.assertEqual({k for k, v in p._indicator_config.items() if v['enabled']}, original)

    def test_latest_anchor_and_historical_position_on_growth(self):
        p = self.panel()
        p.set_market_series(snapshot())
        p.chart._start, p.chart._count = 275, 25
        p.set_market_series(snapshot(count=310))
        self.assertEqual(p.chart.visible_range, (285, 310))
        p.chart._start = 30
        p.set_market_series(snapshot(count=320))
        self.assertEqual(p.chart.visible_range, (30, 55))

    def test_clamp_and_reject_invalid_zoom(self):
        p = self.panel()
        for value in ('7', -1, float('nan'), float('inf'), 10**100, True, None):
            for field in ('start', 'count'):
                with self.subTest(value=value, field=field):
                    prefs = p.preferences()
                    zoom = {'start': 3, 'count': 20, 'latest': False, field: value}
                    prefs['chart_state'] = {'version': 1, 'entries': {'TAIFEX:TMF:202610/1d': {'zoom': zoom}}}
                    p.restore_preferences(prefs)
                    p.set_market_series(snapshot())
                    self.assertEqual(p.chart.visible_range, (200, 300))
        p = self.panel()
        prefs = p.preferences()
        prefs['chart_state'] = {'version': 1, 'entries': {'TAIFEX:TMF:202610/1d': {'zoom': {'start': 900, 'count': 500, 'latest': False}}}}
        p.restore_preferences(prefs)
        p.set_market_series(snapshot(count=30))
        self.assertEqual(p.chart.visible_range, (0, 30))

    def test_corrupt_container_future_version_and_legacy_settings(self):
        p = self.panel()
        for state in (None, [], 'bad', 5, {'version': 2}, {'version': True}, {'version': 1, 'entries': []}):
            prefs = p.preferences()
            prefs.update(watchlist=['TWSE:TAIEX'], timeframe='1w', chart_state=state)
            p.restore_preferences(prefs)
            self.assertEqual(p.preferences()['watchlist'], ['TWSE:TAIEX'])
            self.assertEqual(p.preferences()['timeframe'], '1w')
            self.assertEqual(p.preferences()['chart_state']['entries'], {})
        p = self.panel()
        prefs = p.preferences()
        del prefs['chart_state']
        p.restore_preferences(prefs)
        p.set_market_series(snapshot())
        self.assertEqual(p.chart.visible_range, (200, 300))

    def test_allowlist_identity_cap_and_bounded_entry_projection(self):
        entries = {
            f'TAIFEX:TMF:{year}01/1d': {'indicators': ['RSI', {}, 'unknown', 'MA', 5] * 100, 'extra': 'OOS_HOLDOUT_SENTINEL'} for year in range(2000, 2220)
        }
        entries.update({'bad/1d': {}, 'TAIFEX:TMF:202610/future': {}, 'TAIFEX:TMF:202610/1w': {'indicators': 'RSI'}})
        memory = ChartMemory(_identity, TIMEFRAMES, DEFAULT_INDICATORS, {'version': 1, 'entries': entries})
        self.assertEqual(len(memory.entries), 200)
        self.assertNotIn('TAIFEX:TMF:200001/1d', memory.entries)
        self.assertEqual(memory.entries['TAIFEX:TMF:221901/1d']['indicators'], ['MA', 'RSI'])
        self.assertNotIn('indicators', memory.entries['TAIFEX:TMF:202610/1w'])
        self.assertNotIn('OOS_HOLDOUT_SENTINEL', json.dumps(memory.payload()))
        self.assertTrue(all(len(json.dumps(entry)) < 400 for entry in memory.entries.values()))

    def test_readonly_series_hash_and_annotations_in_both_privacy_states(self):
        p = self.panel()
        item = snapshot()
        before = content_hash(to_dict(item))
        privacy = SimpleNamespace(enabled=False)
        p.privacy = privacy
        p.set_market_series(item)
        for enabled in (False, True):
            privacy.enabled = enabled
            drawings = p.chart.drawings
            orders = p.chart.paper_orders.snapshot
            prefs = p.preferences()
            prefs['chart_state'] = {
                'version': 1,
                'entries': {'TAIFEX:TMF:202610/1d': {'zoom': {'start': 10, 'count': 20, 'latest': False}, 'extra': 'OOS_HOLDOUT_SENTINEL'}},
            }
            texts = [w.text() for w in p.findChildren(type(p.source_status))]
            p.restore_preferences(prefs)
            self.assertEqual(p.chart.drawings, drawings)
            self.assertIs(p.chart.paper_orders.snapshot, orders)
            self.assertEqual(texts, [w.text() for w in p.findChildren(type(p.source_status))])
            self.assertNotIn('OOS_HOLDOUT_SENTINEL', json.dumps(p.preferences()))
            self.assertEqual(content_hash(to_dict(p.selected_series())), before)

    def test_popout_shared_zoom_without_saving_on_interactions(self):
        p = self.panel()
        p.set_market_series((snapshot(), snapshot('TX')))
        saves = QSignalSpy(p.preferences_changed)
        popout = p.popout.open(visible=False)
        self.addCleanup(popout.close)
        for _ in range(5):
            popout.chart._zoom(0.8)
            popout.chart._pan(-2)
        self.assertEqual(saves.count(), 0)
        self.assertEqual(p.chart.visible_range, popout.chart.visible_range)
        remembered = p.chart.visible_range
        self.switch(p, 'TAIFEX:TX:202610')
        self.switch(p, 'TAIFEX:TMF:202610')
        self.assertEqual(saves.count(), 2)
        self.assertEqual(p.chart.visible_range, remembered)
        self.assertEqual(popout.chart.visible_range, remembered)
        # A pop-out close merges view and position through one existing save.
        store = SimpleNamespace(load=Mock(return_value={'keep': True}), save=Mock())
        p.state = SimpleNamespace(settings=store)
        with patch.object(popout, 'isVisible', return_value=True), patch.object(popout, 'isMinimized', return_value=False):
            popout.close()
        store.save.assert_called_once()
        saved = store.save.call_args.args[0]
        self.assertTrue(saved['keep'])
        self.assertIn('chart_state', saved['market'])

    def test_write_failure_does_not_crash(self):
        p = self.panel()
        popout = p.popout.open(visible=False)
        self.addCleanup(popout.close)
        p.state = SimpleNamespace(settings=SimpleNamespace(load=lambda: {}, save=Mock(side_effect=OSError)))
        p.popout.save(popout)
        self.assertTrue(p.message.text())

    def test_memory_restore_preserves_all_non_view_layers(self):
        p = self.panel()
        p.set_market_series(snapshot())
        layers = {name: getattr(p.chart, name) for name in ('bars', 'trace', 'drawings', 'reference_lines', 'markers', 'overlays', 'panes')}
        # Nonempty sentinels prove the memory projection does not clear layers.
        p.chart.drawings = layers['drawings'] = (object(),)
        p.chart.reference_lines = layers['reference_lines'] = (object(),)
        orders = p.chart.paper_orders.snapshot
        memory = ChartMemory(
            _identity,
            TIMEFRAMES,
            DEFAULT_INDICATORS,
            {
                'version': 1,
                'entries': {'TAIFEX:TMF:202610/1d': {'zoom': {'start': 15, 'count': 30, 'latest': False}, 'indicators': ['MA', 'RSI', 'future', 5]}},
            },
        )
        memory.restore(p)
        self.assertEqual(p.chart.visible_range, (15, 45))
        self.assertEqual({key for key, value in p._indicator_config.items() if value['enabled']}, {'MA', 'RSI'})
        for name, value in layers.items():
            self.assertIs(getattr(p.chart, name), value)
        self.assertIs(p.chart.paper_orders.snapshot, orders)


if __name__ == '__main__':
    unittest.main()
