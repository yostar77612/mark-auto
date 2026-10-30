"""Cheap offline sequencing and confirmation contracts, without shown windows."""

import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QVBoxLayout, QWidget
from desktop_app.features.onboarding.quick_start import QuickStart
from desktop_app.features.onboarding.quick_start_chain import QuickStartChain
from desktop_app.shell import notifications
from desktop_app.components import job_progress
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message
from tests import test_backtest_summary_u4 as result_fixtures
import desktop_app.components.privacy as privacy


class SequencingTests(unittest.TestCase):
    def chain(self, failure=None):
        self.calls = []
        self.notices = []

        def start(op, payload):
            self.calls.append((op, payload))
            if failure == op:
                raise ValueError('private detail')
            return len(self.calls)

        def strategy():
            self.calls.append(('strategy', {}))
            if failure == 'strategy':
                raise ValueError('private detail')
            return {'family': 'trend'}

        def results(result):
            self.calls.append(('results', result))
            if failure == 'results':
                raise ValueError('private detail')

        return QuickStartChain(start, strategy, results, self.notices.append)

    def complete(self, chain):
        chain.accept({'job_id': chain.job_id, 'type': 'result', 'result': {}})
        chain.advance()

    def test_consent_busy_order_offline_and_repeat(self):
        chain = self.chain()
        with patch('socket.socket', side_effect=AssertionError('network')):
            self.assertFalse(chain.begin(False))
            self.assertFalse(chain.begin(True, busy=True))
            self.assertEqual(self.calls, [])
            for _ in range(2):
                self.assertTrue(chain.begin(True))
                self.assertFalse(chain.begin(True))
                chain.accept({'job_id': -1, 'type': 'result'})
                chain.advance()
                self.assertEqual(chain.stage, 'data')
                self.complete(chain)
                self.complete(chain)
                self.assertIsNone(chain.stage)
                self.assertIsNone(chain.pending)
        self.assertEqual([x[0] for x in self.calls], ['ui_demo', 'strategy', 'ui_backtest', 'results'] * 2)
        for op, payload in self.calls:
            if op.startswith('ui_'):
                self.assertTrue(payload['synthetic_quick_start'])

    def test_failure_stops_each_stage_and_resets(self):
        for failure in ('ui_demo', 'strategy', 'ui_backtest', 'results'):
            with self.subTest(failure=failure):
                chain = self.chain(failure)
                chain.begin(True)
                for _ in range(2):
                    self.complete(chain)
                ops = [x[0] for x in self.calls]
                self.assertEqual(ops[-1], failure)
                self.assertIsNone(chain.stage)
                self.assertEqual(self.notices[-1], 'error')

    def test_terminal_failure_cancellation_and_delayed_idle(self):
        for kind in ('failed', 'error', 'cancelled', 'canceled'):
            chain = self.chain()
            chain.begin(True)
            chain.accept({'job_id': chain.job_id, 'type': kind})
            chain.advance()
            self.assertEqual(len(self.calls), 1)
        chain = self.chain()
        chain.begin(True)
        chain.accept({'job_id': chain.job_id, 'type': 'result', 'result': {}})
        chain.advance(busy=True)
        self.assertEqual(len(self.calls), 1)
        chain.stop()
        chain.advance()
        self.assertEqual(len(self.calls), 1)


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def quick(self):
        self.parent = QWidget()
        self.addCleanup(self.parent.close)
        self.host = SimpleNamespace(jobs=SimpleNamespace(active=False), start_job=Mock(return_value='demo'), privacy=SimpleNamespace(enabled=True))
        quick = QuickStart(self.host, QVBoxLayout(self.parent))
        self.host.quick_start = quick
        return quick

    def test_dialog_default_cancel_and_busy_hint(self):
        quick = self.quick()
        self.assertEqual(quick.button.accessibleName(), ui_text('quick_start.action'))
        self.assertEqual(quick.button.toolTip(), ui_text('quick_start.tooltip'))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel) as question:
            quick.button.click()
            self.host.start_job.assert_not_called()
            self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
            self.assertIn('synthetic data, not real market data', question.call_args.args[2])
        self.host.jobs.active = True
        quick.refresh()
        self.assertFalse(quick.button.isEnabled())
        self.assertEqual(quick.button.toolTip(), ui_text('quick_start.busy'))
        with patch.object(QMessageBox, 'question') as question:
            quick.confirm()
            question.assert_not_called()

    def test_real_hooks_sequence_results_and_privacy_safe_notice(self):
        quick = self.quick()
        self.host.result_choice = QComboBox(self.parent)
        self.host.backtest_page = SimpleNamespace(show_result=Mock())
        self.host.navigation = SimpleNamespace(setCurrentRow=Mock())
        with patch('socket.socket', side_effect=AssertionError('network')):
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                quick.button.click()
            self.host.start_job.assert_called_once_with('ui_demo', {'bars': 960, 'synthetic_quick_start': True})
            notifications.record_event(self.host, {'job_id': 'demo', 'type': 'result', 'result': {}})
            notifications.end_event(self.host)
            args = self.host.start_job.call_args.args
            self.assertEqual(args[0], 'ui_backtest')
            self.assertEqual(args[1]['family'], 'trend')
            self.assertIsNone(args[1]['candidate'])
            notifications.record_event(
                self.host, {'job_id': 'demo', 'type': 'result', 'result': {'reports': [{'result': 'synthetic-quick-start/result.json'}]}}
            )
            notifications.end_event(self.host)
        self.host.navigation.setCurrentRow.assert_called_once_with(2)
        self.assertEqual(self.host.result_choice.currentText(), ui_text('quick_start.dataset'))
        self.assertIn('synthetic data, not real market data', quick.message.text())
        self.assertTrue(quick.button.isEnabled())
        quick.notice('error')
        self.assertEqual(quick.message.text(), error_message('operation_failed_local'))
        self.assertNotIn('private detail', quick.message.text())

    def test_existing_cancel_guard_stops_chain(self):
        quick = self.quick()
        quick.chain.begin(True)
        self.host.chatgpt_controller = SimpleNamespace(busy=False)
        self.host.job_feedback = SimpleNamespace(terminal=False)
        self.host.jobs.active = True
        self.assertTrue(job_progress.cancel_allowed(self.host))
        self.assertIsNone(quick.chain.stage)
        quick.chain.accept({'job_id': 'demo', 'type': 'result', 'result': {}})
        quick.tick()
        self.assertEqual(self.host.start_job.call_count, 1)

    def test_executor_isolation_reuses_handlers(self):
        import desktop_app.shell.main_window

        root = Path('synthetic-test-root')
        paths = SimpleNamespace()
        with (
            patch.object(desktop_app.shell.main_window, '_root', return_value=root),
            patch.object(Path, 'mkdir'),
            patch.dict(desktop_app.shell.main_window._UI_OPERATION_HANDLERS, {'ui_demo': Mock(return_value={}), 'ui_backtest': Mock(return_value={})}),
        ):
            for operation in ('ui_demo', 'ui_backtest'):
                desktop_app.shell.main_window.execute_ui_operation(operation, {'synthetic_quick_start': True}, paths)
                self.assertEqual(desktop_app.shell.main_window._UI_OPERATION_HANDLERS[operation].call_args.args[2], root / 'synthetic-quick-start')
            self.assertEqual(
                desktop_app.shell.main_window._UI_OPERATION_HANDLERS['ui_backtest'].call_args.args[0]['dataset'],
                str(root / 'synthetic-quick-start' / 'synthetic-demo-dataset.json'),
            )
            desktop_app.shell.main_window.execute_ui_operation('ui_demo', {}, paths)
            self.assertEqual(desktop_app.shell.main_window._UI_OPERATION_HANDLERS['ui_demo'].call_args.args[2], root)
        data = SimpleNamespace(bars=(1,), manifest={})
        with (
            patch.object(desktop_app.shell.main_window, 'synthetic_dataset', return_value=data),
            patch.object(desktop_app.shell.main_window, 'save_dataset') as save,
        ):
            output = desktop_app.shell.main_window._handle_ui_demo({'synthetic_quick_start': True}, paths, root / 'synthetic-quick-start')
            self.assertIn('synthetic-demo-dataset.json', output['dataset'])
            save.assert_called_once_with(data, root / 'synthetic-quick-start' / 'synthetic-demo-dataset.json')

    def test_failed_result_presentation_stops_before_navigation(self):
        quick = self.quick()
        self.host.result_choice = QComboBox(self.parent)
        self.host.backtest_page = SimpleNamespace(show_result=Mock(return_value=False))
        self.host.navigation = SimpleNamespace(setCurrentRow=Mock())
        quick.chain.begin(True)
        quick.chain.stage = 'backtest'
        quick.chain.accept({'job_id': 'demo', 'type': 'result', 'result': {'reports': [{'result': 'synthetic-result.json'}]}})
        quick.tick()
        self.host.navigation.setCurrentRow.assert_not_called()
        self.assertEqual(quick.message.text(), error_message('operation_failed_local'))
        self.assertIsNone(quick.chain.stage)


class ResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_results_label_and_existing_privacy_masking(self):
        fixture = result_fixtures.BacktestSummaryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = fixture.load()
        result.manifest = {'dataset_manifest': {'source_type': 'synthetic'}}
        page = fixture.page
        page.privacy = SimpleNamespace(enabled=True)
        with patch('desktop_app.features.backtest.backtest.load_result', return_value=result):
            page.show_result()
        self.assertFalse(page.synthetic_notice.isHidden())
        self.assertEqual(page.synthetic_notice.text(), ui_text('quick_start.disclaimer'))
        self.assertIn('synthetic data, not real market data', page.synthetic_notice.text())
        self.assertIn(privacy.mask_money(None), page.summary_card.label.text())
        self.assertNotIn('1,234.56', page.summary_card.label.text())
        self.assertNotIn('1,234.56', page.kpis.labels['net_pnl'].text())
        result.manifest = {}
        with patch('desktop_app.features.backtest.backtest.load_result', return_value=result):
            page.show_result()
        self.assertTrue(page.synthetic_notice.isHidden())
