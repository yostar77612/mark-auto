"""Seven-page boundaries, compatibility, host dispatch and pre-change visual contract."""

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget
from desktop_app.shell.pages import MarketPage, DataPage, StrategyPage, BacktestPage, ComparePage, PaperPage, SettingsPage, PageHost
from desktop_app.shell.main_window import MainWindow
from quantlab.core import ValidationError
from quantlab.core import content_hash
from quantlab.desktop_runtime import AppPaths, JobManager
from tests.layered_source_fixtures import page_sources

ROOT = Path(__file__).resolve().parents[1]
PAGES = (MarketPage, DataPage, StrategyPage, BacktestPage, ComparePage, PaperPage, SettingsPage)
MOVED = {
    'market': ('refresh_market', 'save_market_preferences', 'load_market_cache', 'bind_result_layers'),
    'data': ('import_market_file', 'import_market_history', 'import_data', 'download_data'),
    'strategy': (
        '_walk_forward_section',
        '_connect_walk_forward_inputs',
        '_walk_forward_origin_changed',
        'pick_walk_forward_original',
        '_walk_forward_saved_source',
        '_invalidate_walk_forward_preview',
        '_walk_forward_input_key',
        'preview_walk_forward',
        'run_walk_forward',
        'read_walk_forward',
        '_refresh_walk_forward_references',
        '_walk_forward_event',
        '_family_changed',
        'run_campaign',
        'export_manual_request',
        'inspect_candidate',
        'use_candidate',
        'use_builtin',
    ),
    'backtest': ('run_backtest', 'show_result'),
    'compare': (
        '_analysis_section',
        '_invalidate_analysis_preview',
        'pick_analysis_original',
        '_analysis_request',
        'preview_analysis',
        'run_analysis',
        'read_analysis',
        '_analysis_saved_changed',
        '_selected_recovery_launch',
        'reconcile_saved_analysis',
        '_recovery_display_fingerprint',
        '_refresh_recovery_controls',
        '_analysis_event',
        '_refresh_analysis_saved',
        'select_strategy',
    ),
    'paper': ('load_form_file', 'demo_paper_policy', 'paper_job', 'kill_paper', '_show_account', '_remember_stop', 'freeze_paper'),
    'settings': (
        'auto_restore_chatgpt',
        'show_chatgpt_sign_in',
        '_chatgpt_quiesce',
        '_chatgpt_dispatch',
        '_chatgpt_cancel',
        '_chatgpt_open_browser',
        '_plan_usage_request',
        '_current_plan_binding',
        'inspect_plan_usage',
        '_record_connection_error',
        '_chatgpt_event',
        'save_settings',
        'load_settings',
        'configure_workspace',
        'open_releases',
        'record_event',
        'read_logs',
        'backup',
    ),
}


def classes(path):
    return {n.name: n for n in ast.parse(path.read_text(encoding='utf-8-sig'), feature_version=(3, 11)).body if isinstance(n, ast.ClassDef)}


class PageBoundaryTests(unittest.TestCase):
    def test_class_line_limits(self):
        node = classes(ROOT / 'desktop_app/shell/main_window.py')['MainWindow']
        self.assertLessEqual(node.end_lineno - node.lineno + 1, 400)
        for page in PAGES:
            import inspect

            node = classes(Path(inspect.getfile(page)))[page.__name__]
            self.assertLessEqual(node.end_lineno - node.lineno + 1, 500)
            self.assertTrue(issubclass(page, QWidget))

    def test_mainwindow_has_no_moved_page_bodies(self):
        node = classes(ROOT / 'desktop_app/shell/main_window.py')['MainWindow']
        names = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
        forbidden = {'_dashboard', '_data_page', '_strategy_page', '_backtest_page', '_compare_page', '_paper_page', '_settings_page', 'refresh_views'}
        forbidden.update(name for group in MOVED.values() for name in group)
        self.assertFalse(names & forbidden)

    def test_pages_never_import_or_discover_shell(self):
        for path in page_sources(ROOT):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'), feature_version=(3, 11))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(n.name == 'desktop_app.shell.main_window' for n in node.names))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'desktop_app.shell.main_window')
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, ('window', 'parent', 'parentWidget', '__getattr__'))


class PageInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='markauto-pages-test-')
        self.paths = AppPaths(Path(self.temp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.window = MainWindow(self.paths, self.jobs)
        for timer in self.window.findChildren(QTimer):
            timer.stop()

    def tearDown(self):
        self.jobs.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_widget_walk_matches_pre_change_fixture(self):
        actual = sorted({w.objectName() for w in [self.window, *self.window.findChildren(QWidget)] if w.objectName()})
        expected = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, expected)
        for group, names in MOVED.items():
            page = getattr(self.window, group + '_page')
            self.assertIsInstance(page.host, PageHost)
            self.assertIs(page.state, self.window.page_state)
            for name in names:
                self.assertIs(getattr(self.window, name).__self__, page)
        self.assertIs(self.window.result_card, self.window.backtest_page.result_card)
        self.assertIs(self.window.market, self.window.market_page)

    def test_page_buttons_dispatch_through_host_and_preserve_consent(self):
        w = self.window
        with patch.object(w, 'start_job', return_value='test-job') as start:
            w.findChild(QPushButton, 'create_demo').click()
            start.assert_called_once_with('ui_demo', {'bars': 960})
            start.reset_mock()
            with self.assertRaises(ValidationError):
                w.data_page.download_data()
            start.assert_not_called()
            w.data_page.download_import.enabled.setChecked(False)
            w.network_data.setChecked(True)
            w.data_page.download_data()
            start.assert_called_once_with('ui_refresh', {'days': 1, 'network_opt_in': True})
            self.assertFalse(w.network_data.isChecked())
        with patch.object(w.page_host, 'start_job') as start, patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            w.market.refresh_requested.emit()
            start.assert_called_once_with('ui_market_refresh', {'network_opt_in': True})

    def test_loaded_backtest_still_binds_actual_market_reference_layers(self):
        from tests.test_result_reference_layers import fixture
        from quantlab.reporting import save_dataset, export_report

        data, result, series = fixture(mtm=True)
        save_dataset(data, self.paths.state / 'dataset.json')
        exported = export_report(result, self.paths.state / 'reports')
        w = self.window
        contract = series.instrument.contract_id
        w.market.set_market_series(series)
        w._market_data_bindings = {contract: data.manifest['data_hash']}
        w._market_research_series = {contract: series}
        w.market.timeframe_combo.setCurrentIndex(w.market.timeframe_combo.findData('1m'))
        w.result_choice.blockSignals(True)
        w.result_choice.addItem('Engineering fixture', str(exported['result']))
        w.result_choice.blockSignals(False)
        w.show_result()
        self.assertEqual(len(w.market.chart.reference_lines), 6)
        self.assertTrue(w.market.chart.markers)
        self.assertTrue(w._selection_allowed)
        w._market_data_bindings[contract] = 'f' * 64
        w.bind_result_layers(result)
        self.assertFalse(w.market.chart.reference_lines)

    def test_strategy_and_backtest_dispatch_and_shared_state(self):
        w = self.window
        with patch.object(w, 'start_job', return_value='test-job') as start:
            w.backtest_page.run_backtest()
            self.assertEqual(start.call_args.args[0], 'ui_backtest')
            self.assertEqual(start.call_args.args[1]['candidate'], None)
            start.reset_mock()
            w.provider_mode.setCurrentIndex(w.provider_mode.findData('fixture'))
            for index, split in enumerate(('train', 'validation', 'oos', 'holdout')):
                w.campaign_form.fields[split + '_start'].setText(str(index * 120))
                w.campaign_form.fields[split + '_end'].setText(str((index + 1) * 120))
            w.strategy_page.run_campaign()
            self.assertEqual(start.call_args.args[0], 'ui_campaign')
            self.assertEqual(start.call_args.args[1]['provider'], {'mode': 'fixture'})
        w._wf_preview = {'test': True}
        w.config.setPlainText('{}')
        self.assertIsNone(w._wf_preview)
        self.assertIsNone(w.strategy_page.state._wf_preview)

    def test_compare_and_backup_buttons_use_host_and_keep_restore_consent(self):
        w = self.window
        w.comparison_list.addItem('fixture')
        item = w.comparison_list.item(0)
        item.setData(Qt.ItemDataRole.UserRole, 'fixture/result.json')
        item.setSelected(True)
        w.backups = Mock()
        w.backup_path.setText('fixture.zip')
        with patch.object(w.page_host, 'start_job', return_value='job') as start:
            w.findChild(QPushButton, 'compare_results').click()
            start.assert_called_once_with('ui_compare', {'results': ['fixture/result.json']})
            start.reset_mock()
            with self.assertRaises(ValidationError):
                w.settings_page.backup(True)
            start.assert_not_called()
            w.restore_confirm.setChecked(True)
            w.settings_page.backup(True)
            start.assert_called_once_with('ui_backup_restore', {'path': 'fixture.zip'})
            self.assertFalse(w.restore_confirm.isChecked())

    def test_paper_consent_and_policy_payload_stay_fail_closed(self):
        w = self.window
        with (
            patch.object(w.page_host, 'start_job') as start,
            patch.object(w.policy_form, 'build_payload', return_value={'fixed': 'policy'}),
            patch.object(w.snapshot_form, 'build_payload', return_value={'account_id': 'fixture'}),
        ):
            with self.assertRaises(ValidationError):
                w.paper_page.paper_job('replay', max_bars=3)
            start.assert_not_called()
            w.paper_confirm.setChecked(True)
            w.paper_page.paper_job('replay', max_bars=3)
            start.assert_called_once_with(
                'ui_paper_replay', {'max_bars': 3, 'snapshot': {'account_id': 'fixture'}, 'reconcile_confirmed': True, 'policy': {'fixed': 'policy'}}
            )
            self.assertFalse(w.paper_confirm.isChecked())

    def test_settings_signals_and_analysis_state_cross_page_boundaries(self):
        w = self.window
        request = Mock(request_id='fixture-request')
        w._analysis_preview = {'old': 'preview'}
        w.analysis_consent.setChecked(True)
        w._invalidate_analysis_preview()
        self.assertIsNone(w.page_state._analysis_preview)
        self.assertFalse(w.analysis_consent.isChecked())
        with (
            patch.object(w, '_quiesce_and_recover') as quiesce,
            patch.object(w, 'poll_jobs'),
            patch.object(w.chatgpt_controller, 'acknowledge_quiescence') as acknowledge,
        ):
            w.chatgpt_controller.quiesce_requested.emit(request)
            quiesce.assert_called_once_with(preserve_primary_sign_in=True)
            acknowledge.assert_called_once_with('fixture-request', joined=True)
        w.settings_page.auto_restore_chatgpt()
        self.assertTrue(w._pending_chatgpt_restore)
        self.assertIs(w.automatic_backup_panel.window, w.settings_page)

    def test_result_dispatch_and_public_renderer_patch_remain_live(self):
        w = self.window
        w.last_operation = 'ui_compare'
        with (
            patch.object(w, 'refresh_views'),
            patch.object(w, 'notify_local') as notify,
            patch.object(w.jobs, 'poll', return_value=[{'type': 'result', 'result': {'rows': []}}]),
        ):
            w.poll_jobs()
            self.assertEqual(json.loads(w.comparison.toPlainText()), {'rows': []})
            self.assertEqual(json.loads(w.summary.toPlainText()), {'rows': []})
            notify.assert_called_once()
        with patch('desktop_app.shell.main_window.saved_analysis_entries', side_effect=ValidationError('fixture')):
            w._refresh_analysis_saved()
            self.assertTrue(w.analysis_checkpoint_notice.text())

    def test_analysis_preview_event_and_connection_error_share_shell_state(self):
        w = self.window
        request = {'fixture': 'request'}
        plan = {'analysis_id': 'fixture', 'binding': {'registration': 'fixture', 'packet': {'context': {'task': 'critique'}}}}
        result = {'analysis_id': 'fixture', 'plan': plan, 'account_status': {}, 'receipt_snapshot': {'receipts': []}}
        w.last_operation = 'ui_analysis_preview'
        w._analysis_request_key = content_hash(request)
        with (
            patch.object(w.compare_page, '_analysis_request', return_value=request),
            patch.object(w.chatgpt_controller, 'set_account_status'),
            patch('desktop_app.shell.main_window.analysis_preview_text', return_value='validated preview'),
        ):
            self.assertTrue(w._analysis_event({'type': 'result', 'result': result}))
        self.assertIs(w._analysis_preview, result)
        self.assertEqual(w.analysis_preview.toPlainText(), 'validated preview')
        self.assertTrue(w.analysis_start.isEnabled())
        with patch.object(w.page_host, 'start_job') as start:
            with self.assertRaises(ValidationError):
                w.run_analysis()
            start.assert_not_called()
        w.last_operation = 'ui_chatgpt_usage'
        w.chatgpt_controller.account_status_known = True
        self.assertTrue(w._chatgpt_event({'type': 'error'}))
        self.assertFalse(w.chatgpt_controller.account_status_known)

    def test_settings_preserve_inert_values_and_save_window_geometry(self):
        w = self.window
        self.assertEqual(w.page_host.window_position().x(), w.x())
        self.assertEqual(w.page_host.window_position().y(), w.y())
        store = Mock()
        store.load.return_value = {'legacy_provider': {'inert': True}}
        w.settings = store
        w.persist_logs.setChecked(False)
        w.local_notifications.setChecked(False)
        w.settings_page.save_settings()
        saved = store.save.call_args.args[0]
        self.assertEqual(saved['legacy_provider'], {'inert': True})
        self.assertEqual(saved['window'], {'x': w.x(), 'y': w.y(), 'width': w.width(), 'height': w.height()})
        self.assertFalse(saved['persist_logs'])
        self.assertFalse(w.jobs.logging_enabled)
        self.assertFalse(w.chatgpt_panel.consent.isChecked())


class PageSnapshotTests(unittest.TestCase):
    def test_all_seven_workspaces_have_accessible_task_focused_defaults(self):
        from tests.snapshot_cache import default_metrics
        from desktop_app.strings.catalog import ui_text

        actual = default_metrics()
        expected = json.loads((ROOT / 'tests/fixtures/desktop_pages_before/metrics.json').read_text(encoding='utf-8'))
        self.assertEqual(list(actual['pages']), list(expected['pages']))
        for name, page in actual['pages'].items():
            with self.subTest(page=name):
                self.assertEqual(page['unlabeled_inputs'], [])
                self.assertLessEqual(page['primary_button_count'], 1)
                for button in page['disabled_buttons']:
                    self.assertTrue(button['tooltip'])
                    self.assertTrue(button['hint'])
                self.assertGreater(page['button_count'], 0)
        data = actual['pages'][ui_text('ui.data_page.title')]
        self.assertLess(data['visible_input_count'], expected['pages'][ui_text('ui.data_page.title')]['visible_input_count'])
        self.assertIn(ui_text('redesign.data.local'), data['visible_text'])
        strategy = actual['pages'][ui_text('ui.strategy_page.title')]
        self.assertTrue(
            {ui_text('redesign.strategy.ideas'), ui_text('redesign.strategy.research'), ui_text('redesign.strategy.manual')} <= set(strategy['visible_text'])
        )
        settings = actual['pages'][ui_text('ui.settings_page.title')]
        self.assertNotIn(ui_text('ui.settings_page.read_logs'), settings['visible_text'])
        self.assertIn(ui_text('appearance.theme'), settings['visible_text'])


if __name__ == '__main__':
    unittest.main()
