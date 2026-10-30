"""Synthetic, offscreen pop-out sharing, isolation, lifetime and frame geometry."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref
import uuid

from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QSignalSpy
import shiboken6

from desktop_app.features.market.dashboard import MarketDashboard
from desktop_app.features.market.market import MarketPage
from desktop_app.features.market.chart_popout import restore_position, save_position
from tests.test_desktop_market import series
from tests.test_desktop_window_position import FramedWindow
from tests.test_result_reference_layers import fixture
from tests.test_t9_onboarding import sandbox_ui


class PopoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dashboard = MarketDashboard()
        self.addCleanup(shiboken6.delete, self.dashboard)

    def temporary(self):
        folder = Path(__file__).resolve().parents[1] / ('.tmp-c10-' + uuid.uuid4().hex)
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder)
        return folder

    def test_real_main_close_and_atomic_settings_layout_isolation(self):
        from desktop_app.shell.window import MainWindow
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore

        with sandbox_ui():
            paths = AppPaths(self.temporary()).ensure()
            store = SettingsStore(paths.state / 'settings.json')
            store.save({'legacy': {'keep': True}})
            jobs = JobManager(paths)
            w = MainWindow(paths, jobs, store, services=_c_create_ui_services(_c_create_operation_ports()))
            try:
                for timer in w.findChildren(QTimer):
                    timer.stop()
                w.market.workspace.save_named('retained')
                layout = paths.state / 'display_profile' / 'market-layout-v1.json'
                before = layout.read_bytes()
                p = w.market.popout.open(visible=False)
                # Exercise visible close semantics without mapping a native window.
                with patch.object(p, 'isVisible', return_value=True), patch.object(p, 'isMinimized', return_value=False):
                    with patch.object(store, 'save', wraps=store.save) as save:
                        for i in range(100):
                            p.move(100 + i, 150)
                            p.resize(700 + i, 500)
                        self.assertEqual(save.call_count, 0)
                        p.close()
                        self.assertEqual(save.call_count, 1)
                self.assertEqual(store.load()['legacy'], {'keep': True})
                self.assertIn('market_popout', store.load())
                self.assertEqual(layout.read_bytes(), before)
                self.assertTrue(w.isEnabled())
                w.market.set_market_series(series())
                p = w.market.popout.open(visible=False)
                event = QCloseEvent()
                w.closeEvent(event)
                self.assertTrue(event.isAccepted())
                self.assertTrue(p.closed)
                self.assertIsNone(w.market.popout.window)
            finally:
                w.close()
                jobs.close()
                shiboken6.delete(w)

    def test_exact_trace_binding_and_stale_error_status(self):
        d = self.dashboard
        data, result, item = fixture()
        d.set_market_series(item, stale=True, error='synthetic failure')
        d.timeframe_combo.setCurrentIndex(d.timeframe_combo.findData('1m'))
        d.market = d
        d.state = SimpleNamespace(
            root=self.temporary(),
            result_choice=SimpleNamespace(currentData=lambda: 'synthetic'),
            _market_data_bindings={item.instrument.contract_id: data.manifest['data_hash']},
            _market_research_series={item.instrument.contract_id: item},
        )
        (d.state.root / 'dataset.json').touch()
        d.host = SimpleNamespace(result_snapshot_lines=lambda *args: ())
        p = d.popout.open(visible=False)
        with patch('desktop_app.features.market.market.load_dataset', return_value=data):
            MarketPage.bind_result_layers(d, result)
            self.assertTrue(d.chart.markers)
            self.assertIsNotNone(d.chart.trace)
            self.equal(p)
            for changes in (
                lambda: d.state._market_data_bindings.update({item.instrument.contract_id: 'f' * 64}),
                lambda: d.state._market_research_series.update(
                    {item.instrument.contract_id: replace(item, provenance=replace(item.provenance, sha256='b' * 64))}
                ),
            ):
                d.state._market_data_bindings[item.instrument.contract_id] = data.manifest['data_hash']
                changes()
                MarketPage.bind_result_layers(d, result)
                self.assertFalse(d.chart.markers)
                self.assertIsNone(d.chart.trace)
                self.equal(p)
        self.assertIn(d.chart.status_label, p.status.text())
        self.assertEqual(p.status.toolTip(), d.message.toolTip())
        self.assertIn('synthetic failure', p.status.toolTip())
        self.assertTrue(p.safety.text())
        p.close()

    def equal(self, window):
        main = self.dashboard.chart
        for field in ('bars', 'overlays', 'panes', 'source_label', 'status_label', 'trace', 'markers', 'reference_lines', 'drawings', 'error'):
            self.assertEqual(getattr(main, field), getattr(window.chart, field), field)
        self.assertIs(main.bars, window.chart.bars)
        self.assertIs(main.overlays, window.chart.overlays)
        self.assertIs(self.dashboard._series, window.series_store)

    def test_shared_source_all_updates_and_local_view(self):
        d = self.dashboard
        d.set_market_series((series(), series('TX', 'TX')))
        original = d.chart
        before = d.workspace.serialize()
        splitter = d.main_splitter.saveState()
        refresh, sample = QSignalSpy(d.refresh_requested), QSignalSpy(d.sample_requested)
        with patch.object(QWidget, 'showNormal'), patch.object(QWidget, 'raise_') as raised, patch.object(QWidget, 'activateWindow'):
            p = d.popout.open()
            self.assertIs(d.popout.open(), p)
            self.assertEqual(raised.call_count, 2)
        self.equal(p)
        for change in (
            lambda: d.set_market_series((series(), series('TX', 'TX')), stale=True, error='synthetic failure'),
            lambda: d.set_quote_series(series(), stale=True),
            lambda: d.timeframe_combo.setCurrentIndex(7),
            lambda: d._indicator_widgets['EMA'][0].setChecked(True),
            lambda: d.contract_combo.setCurrentIndex(1),
            lambda: d.contract_combo.setCurrentIndex(0),
        ):
            change()
            self.equal(p)
        d.market = d
        d.state = SimpleNamespace()
        MarketPage.bind_result_layers(d)
        self.equal(p)
        main_view = d.chart.visible_range
        p.chart.interaction._zoom(0.5)
        p.chart.interaction._pan(-3)
        p.chart.reset_view()
        self.assertEqual(d.chart.visible_range, main_view)
        prefs = d.preferences()
        p.close()
        p.closeEvent(QCloseEvent())
        self.assertIsNone(d.popout.window)
        self.assertIs(d.chart, original)
        self.assertEqual(d.chart.objectName(), 'market_candles')
        self.assertEqual(d.preferences(), prefs)
        self.assertEqual(d.workspace.serialize(), before)
        self.assertEqual(d.main_splitter.saveState(), splitter)
        self.assertEqual((refresh.count(), sample.count()), (0, 0))
        d.set_market_series(series())
        fresh = d.popout.open(visible=False)
        self.assertIsNot(fresh, p)
        self.equal(fresh)
        fresh.close()

    def test_persistence_failure_uses_b1_and_minimized_close_does_not_write(self):
        from quantlab.desktop_errors import error_message

        d = self.dashboard
        store = Mock()
        d.state = SimpleNamespace(settings=store)
        store.load.side_effect = ValueError('private failure detail')
        p = d.popout.open(visible=False)
        self.assertEqual(d.message.text(), error_message('operation_failed_local'))
        with patch.object(p, 'isVisible', return_value=True), patch.object(p, 'isMinimized', return_value=True):
            p.close()
        store.save.assert_not_called()
        store.load.side_effect = None
        store.load.return_value = {}
        p = d.popout.open(visible=False)
        store.save.side_effect = OSError('private failure detail')
        with patch.object(p, 'isVisible', return_value=True), patch.object(p, 'isMinimized', return_value=False):
            p.close()
        self.assertEqual(d.message.text(), error_message('operation_failed_local'))
        self.assertIsNone(d.popout.window)

    def test_new_module_passes_gate_including_untracked_source(self):
        from tools.quality_gate import python_findings

        root = Path(__file__).resolve().parents[1]
        source = (root / 'desktop_app/features/market/chart_popout.py').read_text(encoding='utf-8')
        self.assertEqual(python_findings(source, 'desktop_app/features/market/chart_popout.py', desktop=True), [])

    def test_disconnect_no_timers_no_retention_and_empty_data(self):
        d = self.dashboard
        calls = Mock()
        d.chart.display_changed.connect(calls)
        count = d.chart.receivers('2display_changed()')
        rendered = d.receivers('2series_rendered(QString)')
        p = d.popout.open(visible=False)
        self.assertTrue(p.isWindow())
        self.assertTrue(p.accessibleName())
        self.assertTrue(d.popout.action.toolTip())
        self.assertEqual(p.findChildren(QTimer), [])
        self.assertEqual(d.chart.receivers('2display_changed()'), count + 1)
        self.assertEqual(d.receivers('2series_rendered(QString)'), rendered + 1)
        ref = weakref.ref(p)
        p.close()
        del p
        self.assertIsNone(ref())
        self.assertEqual(d.chart.receivers('2display_changed()'), count)
        self.assertEqual(d.receivers('2series_rendered(QString)'), rendered)
        d.set_market_series(series())
        self.assertTrue(calls.called)

    def test_destroy_owner_closes_first(self):
        owner = MarketDashboard()
        p = owner.popout.open(visible=False)
        chart = p.chart
        shiboken6.delete(owner)
        self.assertTrue(p.closed)
        self.assertIsNone(p.controller)
        self.assertTrue(shiboken6.isValid(chart))
        shiboken6.delete(p)

    def test_no_host_operations_or_hidden_writes(self):
        d = self.dashboard
        store = Mock()
        store.load.return_value = {'legacy': {'keep': True}}
        d.state = SimpleNamespace(settings=store)
        d.host = SimpleNamespace(start_job=Mock(), question=Mock())
        d.refresh_market, d.load_market_cache = Mock(), Mock()
        p = d.popout.open(visible=False)
        for i in range(100):
            p.move(i, i)
            p.resize(600 + i, 400)
        p.hide()
        p.close()
        store.save.assert_not_called()
        d.host.start_job.assert_not_called()
        d.host.question.assert_not_called()
        d.refresh_market.assert_not_called()
        d.load_market_cache.assert_not_called()


class GeometryTests(unittest.TestCase):
    def test_frame_roundtrip_and_merge(self):
        w = FramedWindow()
        w.width = lambda: w.size[0]
        w.height = lambda: w.size[1]
        value = {'legacy': {'keep': True}, 'market': {'selected': 'fixture'}, 'window': {'x': 7}}
        store = Mock()
        store.load.side_effect = lambda: deepcopy(value)
        store.save.side_effect = lambda v: value.update(v)
        screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        save_position(w, store)
        self.assertEqual(value['market_popout'], {'x': 120, 'y': 140, 'width': 900, 'height': 650})
        restore_position(w, value['market_popout'], [screen], screen)
        save_position(w, store)
        self.assertEqual(w.moves[-1], (120, 140))
        self.assertEqual(value['legacy'], {'keep': True})
        self.assertEqual(value['window'], {'x': 7})
        self.assertEqual(value['market'], {'selected': 'fixture'})

    def test_invalid_and_secondary_screens(self):
        primary = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        for left in (-1920, 1920):
            secondary = SimpleNamespace(availableGeometry=lambda: QRect(left, 0, 1920, 1080))
            w = FramedWindow()
            restore_position(w, {'x': left + 100, 'y': 100, 'width': 700, 'height': 500}, [primary, secondary], primary)
            self.assertEqual(w.moves[-1], (left + 100, 100))
        for bad in (None, {}, {'x': 999999, 'y': -99999}, {'x': float('nan'), 'y': True}, {'x': '10', 'y': 10}, {'x': -9999, 'y': 1}):
            w = FramedWindow()
            restore_position(w, bad, [primary], primary)
            rect = QRect(*w.moves[-1], *w.size)
            self.assertTrue(primary.availableGeometry().contains(rect))
        w = FramedWindow()
        restore_position(w, {'width': True, 'height': 'bad'}, [], None)
        self.assertLessEqual(w.size[0], 1280)
