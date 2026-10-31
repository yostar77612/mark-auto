"""Offline integration checks for the source-to-result desktop workflow."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import csv
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from desktop_app.shell.palette_commands import page_index
from desktop_app.strings.catalog import ui_text
from desktop_app.shell.theme import scale_window_fonts
from desktop_app.shell.window import MainWindow
from desktop_app.shell.main_window import execute_ui_operation
from desktop_app.smoke import _smoke_steps
from quantlab.core import ValidationError, canonical_json, to_dict
from quantlab.research_core.adapters.workspace_store import AppPaths
from desktop_app.research_bootstrap import create_job_manager
from quantlab.reporting import export_report, save_dataset, synthetic_dataset, write_json, read_json
from quantlab.paper import PaperBroker
from tests.test_result_reference_layers import fixture


class DataResultWorkflowTests(unittest.TestCase):
    def capture_state(self, name, window=None):
        destination = os.environ.get('MARKAUTO_UI_QA_IMAGES')
        if not destination:
            return
        from tools.ui_snapshot import _save_png
        from PySide6.QtGui import QFontDatabase, QFont
        from desktop_app.shell.theme import apply_theme

        target = self.window if window is None else window
        if os.name == 'nt':
            for face in ('msjh.ttc', 'msjhbd.ttc'):
                QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / face))
        target.setFont(QFont('Microsoft JhengHei UI', 10))
        apply_theme(target)
        target.stack.currentWidget().verticalScrollBar().setValue(0)
        target.show()
        self.app.processEvents()
        out = Path(destination)
        out.mkdir(parents=True, exist_ok=True)
        _save_png(target, out / (name + '.png'), 1)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.environ.get('MARKAUTO_UI_QA_IMAGES') and os.name == 'nt':
            from PySide6.QtGui import QFontDatabase, QFont

            for face in ('msjh.ttc', 'msjhbd.ttc'):
                QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / face))
            cls.app.setFont(QFont('Microsoft JhengHei UI', 10))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mr-')
        root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'PYTHONUTF8': '1', 'LOCALAPPDATA': str(root / 'local'), 'APPDATA': str(root / 'roaming')})
        self.environment.start()
        self.paths = AppPaths(root / 'workspace').ensure()
        self.jobs = create_job_manager(self.paths)
        self.window = MainWindow(self.paths, self.jobs, services=_c_create_ui_services(_c_create_operation_ports()))
        for timer in self.window.findChildren(QTimer):
            timer.stop()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.jobs.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def load_fixture(self):
        data, result, _ = fixture(mtm=True)
        save_dataset(data, self.window.root / 'dataset.json')
        saved = export_report(result, self.window.root / 'reports')
        self.window.refresh_views()
        # Windows CI TEMP can use RUNNER~1 while export_report resolves its long name.
        # Select the actual discovered report by file identity, never by path spelling.
        expected = Path(saved['result']).resolve(strict=True)
        index = next(
            (row for row in range(self.window.result_choice.count()) if Path(self.window.result_choice.itemData(row)).resolve(strict=True) == expected),
            -1,
        )
        self.assertGreaterEqual(index, 0, 'The exported report must be discovered before any UI assertions')
        self.window.result_choice.setCurrentIndex(index)
        self.assertTrue(self.window.show_result())
        return data, result, saved

    def test_source_tabs_show_only_the_current_task_and_kind_fields(self):
        page = self.window.data_page
        self.assertEqual(page.sources.count(), 4)
        self.assertEqual(page.sources.currentIndex(), 0)
        self.assertTrue(page.import_path.isVisibleTo(page))
        self.assertFalse(self.window.findChild(QPushButton, 'create_demo').isVisibleTo(page))
        self.assertFalse(self.window.findChild(QPushButton, 'refresh_data').isVisibleTo(page))
        for kind, needs_contract in (('validated_dataset', False), ('ticks', True), ('daily_json', True), ('proxy_bars', False), ('synthetic_ticks', False)):
            with self.subTest(kind=kind):
                page.import_kind.setCurrentIndex(page.import_kind.findData(kind))
                self.assertEqual(page.contract_box.isVisibleTo(page), needs_contract)
                self.assertTrue(page.calendar_path.isVisibleTo(page))
        self.assertIn(ui_text('redesign.data.classification'), page.kind_notice.text())
        self.assertTrue(page.contract_filter.isVisibleTo(page))
        page.contract_filter.click()
        self.assertTrue(page.contract_box.isVisibleTo(page))
        page.contract_filter.click()
        self.assertFalse(page.contract_box.isVisibleTo(page))
        page.sources.setCurrentIndex(3)
        self.assertTrue(self.window.findChild(QPushButton, 'create_demo').isVisibleTo(page))
        self.assertFalse(page.import_path.isVisibleTo(page))

    def test_import_keeps_required_calendar_and_download_one_call_consent(self):
        page = self.window.data_page
        with patch.object(self.window, 'start_job', return_value='isolated-job') as start:
            page.import_path.setText('isolated-data.json')
            with self.assertRaises(ValidationError):
                page.import_data()
            start.assert_not_called()
            page.calendar_path.setText('isolated-calendar.json')
            page.import_data()
            start.assert_called_once_with(
                'ui_import', {'path': 'isolated-data.json', 'calendar': 'isolated-calendar.json', 'kind': 'validated_dataset', 'contract': 'TAIFEX:TMF:202601'}
            )
            start.reset_mock()
            with self.assertRaises(ValidationError):
                page.download_data()
            start.assert_not_called()
            page.download_import.enabled.setChecked(False)
            page.network_data.setChecked(True)
            page.days.setValue(3)
            page.download_data()
            start.assert_called_once_with('ui_refresh', {'days': 3, 'network_opt_in': True})
            self.assertFalse(page.network_data.isChecked())

    def test_normalized_import_does_not_apply_an_unseen_contract_filter(self):
        page = self.window.data_page
        page.import_path.setText('source.csv')
        page.calendar_path.setText('calendar.json')
        page.import_kind.setCurrentIndex(page.import_kind.findData('synthetic_bars'))
        with patch.object(self.window, 'start_job', return_value='isolated-job') as start:
            page.import_data()
            self.assertEqual(start.call_args.args[1]['contract'], '')
            page.contract_filter.setChecked(True)
            page.contract.setText('TAIFEX:TMF:202610')
            page.import_data()
            self.assertEqual(start.call_args.args[1]['contract'], 'TAIFEX:TMF:202610')

    def test_real_loaded_summary_next_step_and_stale_state_clear(self):
        page = self.window.data_page
        self.assertFalse(page.next_button.isEnabled())
        data, _, _ = self.load_fixture()
        self.assertIn(str(len(data.bars)), page.data_card.text())
        self.assertIn(str(data.manifest.get('product') or data.bars[0].contract_id), page.data_card.text())
        self.assertIn(ui_text('redesign.data.validation'), page.data_card.text())
        self.assertTrue(page.next_button.isEnabled())
        page.next_button.click()
        self.assertEqual(self.window.navigation.currentRow(), page_index(self.window, 'strategy'))
        page.set_dataset_summary(None)
        self.assertFalse(page.next_button.isEnabled())
        self.assertEqual(page.data_card.text(), ui_text('redesign.data.empty'))
        self.assertEqual(page.data_detail.toPlainText(), '')

    def test_common_cost_controls_remain_authoritative_and_summary_tracks_inputs(self):
        page = self.window.backtest_page
        self.load_fixture()
        self.window.navigation.setCurrentRow(page_index(self.window, 'backtest'))
        self.app.processEvents()
        page.backtest_form.fields['commission_per_side'].setText('37')
        self.assertIn('37', page.run_summary.text())
        self.assertFalse(page.backtest_form.fields['commission_per_side'].isVisibleTo(page))
        self.window.findChild(QToolButton, 'redesign_backtest_common').click()
        page.setup_toggle.setChecked(True)
        self.assertTrue(page.backtest_form.fields['commission_per_side'].isVisibleTo(page))
        with patch.object(self.window, 'start_job', return_value='isolated-job') as start:
            page.run_backtest()
        self.assertEqual(start.call_args.args[0], 'ui_backtest')
        self.assertEqual(start.call_args.args[1]['config']['costs']['commission_per_side'], '37')
        self.assertIsNone(start.call_args.args[1]['candidate'])

    def test_execution_summary_honors_json_override_and_rejects_stale_cost_display(self):
        page = self.window.backtest_page
        config = page.backtest_form.build_payload()['config']
        config['costs']['commission_per_side'] = '999'
        page.config.setPlainText(canonical_json(config))
        self.assertIn('999', page.run_summary.text())
        self.assertIn('0.002%', page.run_summary.text())
        page.backtest_form.fields['commission_per_side'].setText('37')
        self.assertIn('999', page.run_summary.text())
        self.assertNotIn('37', page.run_summary.text())
        page.config.setPlainText('{')
        self.assertEqual(page.run_summary.text(), ui_text('redesign.backtest.error_summary'))
        config['costs']['commission_per_side'] = 'invalid'
        page.config.setPlainText(canonical_json(config))
        page.refresh_run_summary()
        self.assertEqual(page.run_summary.text(), ui_text('redesign.backtest.error_summary'))

    def test_large_font_result_page_fits_desktop_width(self):
        self.load_fixture()
        window = self.window
        window.setFixedSize(1366, 768)
        font = QFont(window.font())
        font.setPointSizeF(font.pointSizeF() * 2)
        window.setFont(font)
        scale_window_fonts(window, 2)
        window.navigation.setCurrentRow(page_index(window, 'backtest'))
        self.app.processEvents()
        scroll = window.stack.currentWidget()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)

    def test_result_compare_navigation_preserves_selection_and_no_qualification_change(self):
        page = self.window.backtest_page
        self.load_fixture()
        allowed = self.window._selection_allowed
        page.compare_result()
        self.assertEqual(self.window.navigation.currentRow(), page_index(self.window, 'compare'))
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in self.window.comparison_list.selectedItems()]
        self.assertIn(page.result_choice.currentData(), selected)
        self.assertEqual(self.window._selection_allowed, allowed)
        self.window.compare_page.return_to_results()
        self.assertEqual(self.window.navigation.currentRow(), page_index(self.window, 'backtest'))
        self.window.findChild(QToolButton, 'redesign_backtest_fills').click()
        self.assertTrue(page.fills_table.isVisibleTo(page))
        self.window.findChild(QToolButton, 'redesign_backtest_report').click()
        self.assertTrue(page.kpis.isVisibleTo(page))
        page.result_choice.clear()
        self.assertFalse(self.window._selection_allowed)
        self.assertFalse(self.window.select_button.isEnabled())
        self.assertFalse(page.summary_card.isVisibleTo(page))

    def test_report_folder_opens_only_a_verified_workspace_result(self):
        page = self.window.backtest_page
        _, _, saved = self.load_fixture()
        with patch('desktop_app.features.backtest.backtest.QDesktopServices.openUrl', return_value=True) as opened:
            page.open_report()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), Path(saved['result']).parent)
            self.assertEqual(self.window.findChild(QPushButton, 'backtest_open_report').toolTip(), ui_text('privacy.exports_raw'))
            outside = Path(self.temp.name) / 'outside'
            outside.mkdir()
            write_json(outside / 'result.json', read_json(saved['result']))
            page.result_choice.blockSignals(True)
            page.result_choice.addItem('outside-workspace', str(outside / 'result.json'))
            page.result_choice.setCurrentIndex(page.result_choice.count() - 1)
            page.result_choice.blockSignals(False)
            with self.assertRaises(ValidationError):
                page.open_report()
            self.assertEqual(opened.call_count, 1)

    def test_offline_import_research_adopt_backtest_compare_replay_stop_and_reopen(self):
        window = self.window
        source = synthetic_dataset(120)
        csv_path = Path(self.temp.name) / 'bars.csv'
        columns = ('timestamp', 'end', 'trade_date', 'session', 'contract_id', 'open', 'high', 'low', 'close', 'volume', 'source_id')
        with csv_path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(to_dict(bar) for bar in source.bars)
        calendar_path = Path(self.temp.name) / 'calendar.json'
        policy = _smoke_steps()[4][1]['policy']
        write_json(calendar_path, {'version': 'isolated-ui-v1', 'sessions': policy['risk_sessions']})
        operations = []
        outcomes = []

        def dispatch(operation, payload):
            window.last_operation = operation
            result = execute_ui_operation(operation, deepcopy(payload), self.paths)
            operations.append(operation)
            outcomes.append(result)
            window.views_page.render_result({'type': 'result', 'result': result})
            return 'offline-ui-' + str(len(operations))

        with patch.object(window, 'start_job', side_effect=dispatch):
            page = window.data_page
            page.import_kind.setCurrentIndex(page.import_kind.findData('synthetic_bars'))
            page.import_path.setText(str(csv_path))
            page.calendar_path.setText(str(calendar_path))
            page.import_data()
            self.assertTrue(window._dataset_ready)
            self.assertIn('120', page.data_card.text())
            page.next_button.click()
            self.assertEqual(window.navigation.currentRow(), page_index(window, 'strategy'))

            strategy = window.strategy_page
            strategy.choose_mode('research')
            window.provider_mode.setCurrentIndex(window.provider_mode.findData('fixture'))
            campaign = deepcopy(_smoke_steps()[3][1]['config'])
            campaign['ranking']['minimum'] = '1000000000000'
            window.campaign_config.setPlainText(canonical_json(campaign))
            strategy.run_campaign()
            self.assertGreater(window.candidate_choice.count(), 0)
            strategy.inspect_candidate()
            self.assertTrue(window._candidate_valid)
            window.findChild(QPushButton, 'use_candidate').click()
            self.assertIsNotNone(window.active_candidate)
            self.assertEqual(window.navigation.currentRow(), page_index(window, 'backtest'))
            window.backtest_page.run_backtest()
            candidate_path = window.result_choice.currentData()
            self.assertTrue(candidate_path)
            self.assertFalse(window._selection_allowed, 'The fixture candidate cannot acquire paper qualification from a research backtest')
            with self.assertRaises(ValidationError):
                window.compare_page.select_strategy()
            self.assertFalse((window.root / 'selection.json').exists())

            strategy.use_builtin()
            self.assertIsNone(window.active_candidate)
            window.backtest_page.run_backtest()
            self.assertTrue(window._selection_allowed)
            window.backtest_page.compare_result()
            for row in range(window.comparison_list.count()):
                window.comparison_list.item(row).setSelected(True)
            selected = [item.data(Qt.ItemDataRole.UserRole) for item in window.comparison_list.selectedItems()]
            dispatch('ui_compare', {'results': selected})
            self.assertGreaterEqual(window.compare_page.comparison_table.rowCount(), 1)
            window.compare_page.select_strategy()
            self.assertTrue((window.root / 'selection.json').exists())

            paper = window.paper_page
            window.navigation.setCurrentRow(page_index(window, 'paper'))
            paper.demo_paper_policy()
            snapshot = paper.snapshot_form.build_payload()
            paper.paper_job('reconcile', snapshot=snapshot)
            self.assertFalse(paper._stop_account['reconciliation_required'])
            paper.replay_controls.speed.setCurrentIndex(paper.replay_controls.speed.findData(100))
            paper.paper_confirm.setChecked(True)
            paper.paper_job('replay', max_bars=30, _paced=True)
            controls = paper.replay_controls
            controls.timer.stop()
            for _ in range(25):
                controls.pacer.due = 0
                controls.tick()
            before_pause = outcomes[-1]['replay']['cursor']
            self.assertGreater(before_pause, 0)
            controls.toggle()
            self.assertTrue(controls.paused)
            self.capture_state('paper-paused')
            controls.tick()
            self.assertEqual(outcomes[-1]['replay']['cursor'], before_pause)
            controls.toggle()
            self.assertFalse(controls.paused)
            controls.pacer.due = 0
            controls.tick()
            self.assertGreater(outcomes[-1]['replay']['cursor'], before_pause)
            positions = dict(paper._stop_account['positions'])
            fills = dict(paper._stop_account['fills'])
            choice = object()
            dialog = SimpleNamespace(confirm_button=choice, observe_button=object(), exec=lambda: None, clickedButton=lambda: choice)
            with patch('desktop_app.features.paper.paper.stop_dialog', return_value=dialog):
                paper.kill_paper()
            stopped = PaperBroker.read_snapshot(window.root / 'paper.sqlite3')
            self.assertTrue(stopped['manual_order_lock'])
            self.assertTrue(stopped['kill_switch'])
            self.assertEqual(stopped['positions'], positions)
            self.assertEqual(stopped['fills'], fills)
            self.assertFalse(controls.running)
            self.assertFalse(paper.paper_confirm.isChecked())
            self.capture_state('paper-stopped')

        self.assertTrue(read_json(window.root / 'desktop_safety.json')['reconciliation_required'])
        self.assertEqual(operations[:3], ['ui_import', 'ui_campaign', 'ui_backtest'])
        self.assertIn('ui_paper_replay', operations)
        self.assertTrue(window.result_choice.count())
        window.close()
        reopened = MainWindow(self.paths, self.jobs, services=_c_create_ui_services(_c_create_operation_ports()))
        try:
            for timer in reopened.findChildren(QTimer):
                timer.stop()
            reopened._show_account(execute_ui_operation('ui_paper_snapshot', {}, self.paths)['account'])
            self.assertTrue(reopened.page_state.manual_order_lock)
            self.assertFalse(reopened.findChild(QPushButton, 'paper_replay').isEnabled())
            self.assertEqual(reopened.paper_page._stop_account['positions'], positions)
            self.assertEqual(reopened.paper_page._stop_account['fills'], fills)
            self.assertEqual(reopened.result_choice.count(), window.result_choice.count())
            reopened.navigation.setCurrentRow(page_index(reopened, 'paper'))
            self.capture_state('paper-reopened', reopened)
        finally:
            reopened.close()
            reopened.deleteLater()


if __name__ == '__main__':
    unittest.main()
