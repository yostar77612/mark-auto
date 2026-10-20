"""Cheap synthetic display-layout checks, with no workers or displayed windows."""

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QListWidget, QWidget
import shiboken6

from desktop_charts import CandlestickChart
from desktop_market import MarketDashboard
from desktop_market_layout import FILE_NAME, MAX_LAYOUTS, LayoutStore, preset, validate_layout
from desktop_pages.market import MarketPage
from quantlab.desktop_errors import error_message
from tests.test_desktop_market import series
from tools.quality_gate import python_findings

ROOT = Path(__file__).resolve().parents[1]


class MarketWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dashboard = MarketDashboard()
        self.workspace = self.dashboard.workspace
        self.addCleanup(shiboken6.delete, self.dashboard)

    def temporary(self):
        folder = ROOT / ('.tmp-c5-' + uuid.uuid4().hex)
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder)
        return folder

    def test_unique_panels_and_public_widgets(self):
        w = self.dashboard
        self.assertEqual(tuple(self.workspace.panels), ('cards', 'watchlist', 'chart'))
        self.assertEqual(w.findChildren(CandlestickChart), [w.chart])
        self.assertEqual(w.findChildren(QListWidget), [w.watchlist])
        for key, value in w.cards.items():
            self.assertEqual(w.findChildren(QWidget, 'market_card_' + key), [value])
        for key, panel in self.workspace.panels.items():
            self.assertEqual(panel.property('panelId'), key)
            self.assertEqual(panel.objectName(), 'market_dock_' + key)
        for name in (
            'market_dashboard',
            'market_watchlist',
            'market_search',
            'market_catalog',
            'market_contract',
            'market_timeframe',
            'market_refresh',
            'market_title',
            'market_safety',
        ):
            self.assertTrue(name == w.objectName() or w.findChild(QWidget, name) is not None)

    def test_presets_distinct_idempotent_and_sizes(self):
        states = []
        self.assertEqual(self.workspace.preset_ids, ('overview', 'chart_focus', 'watchlist_focus'))
        for key in self.workspace.preset_ids:
            self.workspace.actions[key].trigger()
            state = self.workspace.serialize()
            self.assertEqual(state, preset(key))
            self.workspace.actions[key].trigger()
            self.assertEqual(state, self.workspace.serialize())
            states.append(json.dumps(state, sort_keys=True))
        self.assertEqual(len(set(states)), 3)
        self.workspace.reset()
        self.assertIs(self.dashboard.main_splitter.widget(0), self.workspace.panels['watchlist'])
        self.assertIs(self.dashboard.main_splitter.widget(1), self.workspace.panels['chart'])
        self.assertEqual([preset('overview')['panels'][k]['size'] for k in ('watchlist', 'chart')], [190, 740])

    def test_all_action_moves_reorder_and_keyboard_collapse(self):
        for key, panel in self.workspace.panels.items():
            content = panel.content
            for area in ('top', 'left', 'center', 'right', 'bottom'):
                panel.actions['move_' + area].trigger()
                self.assertEqual(self.workspace.serialize()['panels'][key]['area'], area)
                if area in ('top', 'bottom'):
                    self.assertIs(panel.parentWidget(), getattr(self.workspace, area))
                else:
                    self.assertIs(panel.parentWidget(), self.dashboard.main_splitter)
            QTest.keyClick(panel.handle, Qt.Key.Key_C)
            self.assertTrue(content.isHidden())
            self.assertIs(panel.content, content)
            QTest.keyClick(panel.handle, Qt.Key.Key_C)
            self.assertFalse(content.isHidden())
        for panel in self.workspace.panels.values():
            panel.actions['move_top'].trigger()
        self.workspace.panels['chart'].actions['earlier'].trigger()
        self.assertEqual(self.workspace.serialize()['panels']['chart']['position'], 1)
        self.workspace.panels['chart'].actions['later'].trigger()
        self.assertEqual(self.workspace.serialize()['panels']['chart']['position'], 2)

    def test_names_roundtrip_overwrite_delete_and_memory_host(self):
        self.assertTrue(self.workspace.save_named('my1'))
        initial = self.workspace.serialize()
        self.workspace.apply_preset('chart_focus')
        self.assertTrue(self.workspace.restore_named('my1'))
        self.assertEqual(self.workspace.serialize(), initial)
        self.workspace.apply_preset('watchlist_focus')
        self.assertTrue(self.workspace.save_named('my1'))
        self.workspace.reset()
        self.workspace.restore_named('my1')
        self.assertEqual(self.workspace.serialize(), preset('watchlist_focus'))
        self.assertTrue(self.workspace.delete_named('my1'))
        self.assertFalse(self.workspace.restore_named('my1'))
        self.assertEqual(self.workspace.serialize(), preset('overview'))
        page = MarketPage(SimpleNamespace())
        try:
            self.assertIsNone(page.workspace.store.path)
            self.assertTrue(page.workspace.save_named('memory'))
            page.workspace.apply_preset('chart_focus')
            self.assertTrue(page.workspace.restore_named('memory'))
        finally:
            shiboken6.delete(page)

    def test_untrusted_names_count_and_integer_validation(self):
        folder = self.temporary()
        self.workspace.configure_store(folder / 'display_profile')
        for name in ('../x', 'C:\\x', 'con', '', 'x' * 10000):
            self.assertFalse(self.workspace.save_named(name))
        self.assertEqual(list(folder.rglob('*')), [])
        self.workspace.configure_store()
        for index in range(MAX_LAYOUTS):
            self.assertTrue(self.workspace.save_named(str(index)))
        self.assertFalse(self.workspace.save_named('overflow'))
        self.assertTrue(self.workspace.save_named('0'))
        bad = preset('overview')
        bad['panels']['unknown'] = bad['panels'].pop('chart')
        self.workspace.apply_layout(bad)
        self.assertEqual(self.workspace.serialize(), preset('overview'))
        for field, values in (
            ('size', (True, 1.5, '200', float('nan'))),
            ('position', (True, 1.0, '0', -1, 3)),
            ('area', ('unknown', [], 1)),
            ('collapsed', (1, 'false')),
        ):
            for value in values:
                bad = preset('chart_focus')
                bad['panels']['chart'][field] = value
                self.workspace.apply_layout(bad)
                self.assertEqual(self.workspace.serialize(), preset('overview'))
        bad = preset('chart_focus')
        bad['extra'] = 1
        self.assertIsNone(validate_layout(bad))
        bad = preset('overview')
        bad['panels']['chart']['size'] = 10**30
        self.assertEqual(validate_layout(bad)['panels']['chart']['size'], 2000)
        bad['panels']['chart']['size'] = -100000
        self.assertEqual(validate_layout(bad)['panels']['chart']['size'], 80)

    def test_corrupt_files_fallback_and_preserve_bytes(self):
        folder = self.temporary()
        path = folder / FILE_NAME
        self.assertEqual(LayoutStore(folder).current, preset('overview'))
        for raw in (b'', b'\xff\xfe', b'{', b'[]', b'null', b'NaN', b'{"version":2}', json.dumps({'version': 1, 'current': {}, 'layouts': {}}).encode()):
            path.write_bytes(raw)
            self.workspace.configure_store(folder)
            self.assertEqual(self.workspace.serialize(), preset('overview'))
            self.assertEqual(path.read_bytes(), raw)
        document = {'version': 1, 'current': preset('overview'), 'layouts': {'valid': preset('chart_focus'), 'bad': {'version': 1, 'panels': {}}}}
        path.write_text(json.dumps(document), encoding='utf-8')
        self.workspace.configure_store(folder)
        self.assertFalse(self.workspace.restore_named('bad'))
        self.assertEqual(self.workspace.serialize(), preset('overview'))
        self.assertTrue(self.workspace.restore_named('valid'))
        self.assertEqual(self.workspace.serialize(), preset('chart_focus'))

    def test_persistence_separate_no_content_and_startup_once(self):
        folder = self.temporary()
        artifacts = ['dataset.json', 'market_cache/snapshot.json', 'market_history/source.json', 'results/a.json', 'selection.json', 'paper/journal.json']
        for name in artifacts:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic-research-sentinel-secret-78652')
        before = {name: (folder.joinpath(name).read_bytes(), hashlib.sha256(folder.joinpath(name).read_bytes()).hexdigest()) for name in artifacts}
        profile = folder / 'display_profile'
        self.workspace.configure_store(profile)
        self.dashboard.cards['TMF'].setText('sentinel-price-435123')
        self.workspace.apply_preset('chart_focus')
        self.assertTrue(self.workspace.save_named('my1'))
        saved = self.workspace.serialize()
        self.workspace.reset()
        self.workspace.restore_named('my1')
        self.workspace.reset()
        after = {name: (folder.joinpath(name).read_bytes(), hashlib.sha256(folder.joinpath(name).read_bytes()).hexdigest()) for name in artifacts}
        self.assertEqual(before, after)
        self.assertEqual(set(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()) - set(artifacts), {'display_profile/' + FILE_NAME})
        raw = (profile / FILE_NAME).read_bytes()
        for sentinel in (b'sentinel-price-435123', b'synthetic-research', b'sentinel-secret'):
            self.assertNotIn(sentinel, raw)
        host = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(path=folder / 'settings.json')))
        with patch('desktop_market_layout.LayoutStore.load', autospec=True, side_effect=LayoutStore.load) as load:
            page = MarketPage(host)
            try:
                self.assertEqual(load.call_count, 1)
                self.assertEqual(page.workspace.serialize(), saved)
            finally:
                shiboken6.delete(page)
        self.workspace.configure_store(profile)
        self.assertEqual(self.workspace.serialize(), saved)

    def test_atomic_write_and_replace_failure(self):
        folder = self.temporary()
        self.workspace.configure_store(folder / 'display_profile')
        self.assertTrue(self.workspace.save_named('original'))
        path = self.workspace.store.path
        before = path.read_bytes()
        for target in ('desktop_market_layout.json.dump', 'desktop_market_layout.os.replace'):
            with patch(target, side_effect=OSError('sentinel-secret C:/private/path')):
                self.assertFalse(self.workspace.save_named('failed'))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob('*.tmp')), [])
            self.assertEqual(self.workspace.error.text(), error_message('operation_failed_local'))
            self.assertFalse(self.workspace.error.isHidden())
            self.assertNotIn('failed', self.workspace.store.layouts)

    def test_no_data_flow_state_and_safety_after_every_operation(self):
        host = SimpleNamespace(safe=Mock(), start_job=Mock(), question=Mock())
        page = MarketPage(host)
        try:
            page.set_market_series(series())
            page.set_quote_series(series())
            workspace = page.workspace
            identity = id(page.chart)

            def state():
                return (
                    deepcopy(page.preferences()),
                    page.chart.bars,
                    page.chart.overlays,
                    page.watchlist.currentRow(),
                    page.source_status.text(),
                    page.contract_combo.currentData(),
                    page.timeframe_combo.currentData(),
                    [page.watchlist.item(i).text() for i in range(page.watchlist.count())],
                )

            initial = state()
            refresh, sample, preferences, rendered = (
                QSignalSpy(signal) for signal in (page.refresh_requested, page.sample_requested, page.preferences_changed, page.series_rendered)
            )
            names = ('refresh_market', 'load_market_cache', 'set_market_series', 'set_quote_series', 'bind_result_layers')
            sentinels = [patch.object(page, name, side_effect=AssertionError(name)) for name in names]
            mocks = [item.start() for item in sentinels]
            try:
                with patch.object(page.chart, 'set_series', side_effect=AssertionError('set_series')) as chart_set:
                    operations = [lambda key=key: workspace.apply_preset(key) for key in workspace.preset_ids]
                    operations += [
                        lambda: workspace.save_named('my1'),
                        lambda: workspace.move_panel('chart', 'bottom'),
                        lambda: workspace.collapse('watchlist'),
                        lambda: workspace.restore_named('my1'),
                        workspace.reset,
                    ]
                    for operation in operations:
                        operation()
                        self.assertEqual(state(), initial)
                        self.assertEqual(id(page.chart), identity)
                    for key in workspace.panels:
                        workspace.collapse(key)
                    page.panel_toggle.setChecked(False)
                    for name in ('market_safety', 'market_source_status', 'market_live_disabled'):
                        widget = page.findChild(QWidget, name)
                        self.assertTrue(widget.isVisibleTo(page), name)
                        self.assertTrue(all(not panel.isAncestorOf(widget) for panel in workspace.panels.values()))
                        self.assertFalse(page.right_panel.isAncestorOf(widget))
                    workspace.reset()
                    self.assertEqual(workspace.serialize(), preset('overview'))
                    chart_set.assert_not_called()
            finally:
                for item in sentinels:
                    item.stop()
            for mock in mocks:
                mock.assert_not_called()
            self.assertEqual([spy.count() for spy in (refresh, sample, preferences, rendered)], [0, 0, 0, 0])
            host.start_job.assert_not_called()
            host.question.assert_not_called()
        finally:
            shiboken6.delete(page)

    def test_retained_wrappers_survive_fifty_presets_and_destroy(self):
        chart = self.dashboard.chart
        watch = self.dashboard.watchlist
        cards = dict(self.dashboard.cards)
        refs = [weakref.ref(widget) for widget in (chart, watch, *cards.values())]
        for index in range(50):
            self.workspace.apply_preset(self.workspace.preset_ids[index % 3])
        self.assertIs(self.dashboard.chart, chart)
        self.assertIs(self.dashboard.watchlist, watch)
        for key, widget in cards.items():
            self.assertIs(self.dashboard.cards[key], widget)
        self.assertTrue(all(ref() is not None and shiboken6.isValid(ref()) for ref in refs))
        other = MarketDashboard()
        other.workspace.apply_preset('chart_focus')
        shiboken6.delete(other)
        self.assertFalse(shiboken6.isValid(other))

    def test_schema_has_no_dynamic_execution(self):
        for filename in ('desktop_market_layout.py', 'desktop_market_workspace.py'):
            source = (ROOT / filename).read_text(encoding='utf-8')
            self.assertEqual(python_findings(source, filename, desktop=True), [])
            tree = ast.parse(source)
            calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
            self.assertFalse(set(calls) & {'eval', 'exec', 'compile'})
