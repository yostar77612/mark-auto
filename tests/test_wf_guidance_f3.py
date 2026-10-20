"""Cheap display-only F3 checks: catalogue hints and reused estimate projection."""

import copy
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_pages.notification_log import NotificationLog
from desktop_pages.strategy import StrategyPage
from desktop_pages.wf_wizard import WalkForwardWizard, duration_estimate_text, failure_hint
from desktop_presentation import display_number
from desktop_strings import ui_text
from quantlab.core import ValidationError
from quantlab.errors import ERROR_TABLE
from quantlab.wf_estimate import MEASURED_EVALUATION_SECONDS, estimated_seconds


class GuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_b1_code_has_catalogue_only_advisory(self):
        for code, entry in ERROR_TABLE.items():
            with self.subTest(code=code):
                self.assertEqual(failure_hint(code), ui_text('wf.failure_hint').format(code, entry.explanation, entry.action))
                self.assertIn('\u53ef\u80fd', failure_hint(code))
                self.assertIn('\u4e0d\u6703\u81ea\u52d5\u91cd\u8a66', failure_hint(code))
        for unknown in (None, '', 'OOS_SECRET /private/name.csv', {}, ['validation_failed']):
            self.assertEqual(failure_hint(unknown), failure_hint('operation_failed'))

    def page(self, operation='ui_walk_forward_run'):
        return SimpleNamespace(
            host=SimpleNamespace(record_event=Mock(), start_job=Mock(), safe=Mock()),
            state=SimpleNamespace(last_operation=operation, status=QLabel(), _wf_launch=None, _wf_preview=None),
            wf_wizard=SimpleNamespace(message=QLabel(), summary=Mock(), timeline=Mock(), preview_summary=QLabel()),
            walk_forward_status=QLabel(),
            walk_forward_consent=QCheckBox(),
            walk_forward_start=QPushButton(),
            walk_forward_preview=Mock(),
            walk_forward_advanced=Mock(),
            preview_walk_forward=Mock(),
        )

    def test_failure_matches_notification_and_never_projects_private_payload(self):
        for private in (False, True):
            for code in (*ERROR_TABLE, None, 'unknown OOS_SECRET /private/name.csv'):
                with self.subTest(private=private, code=code):
                    page = self.page()
                    page.host.privacy = SimpleNamespace(enabled=private)
                    event = {
                        'type': 'error',
                        'error_code': code,
                        'error': 'RAW_EXCEPTION /private/name.csv',
                        'result': {'oos': 'OOS_SECRET', 'final_holdout': 'HOLDOUT_SECRET'},
                    }
                    self.assertTrue(StrategyPage._walk_forward_event(page, event))
                    notice = NotificationLog().accept_event(page.state.last_operation, event)
                    self.assertEqual(page.wf_wizard.message.text(), failure_hint(notice.error_code))
                    for secret in ('OOS_SECRET', 'HOLDOUT_SECRET', 'RAW_EXCEPTION', '/private/name.csv'):
                        self.assertNotIn(secret, page.wf_wizard.message.text())
                    page.host.start_job.assert_not_called()
                    self.assertFalse(page.walk_forward_consent.isChecked())

    def test_failed_packet_and_result_code_fallback(self):
        page = self.page('ui_walk_forward_preview')
        event = {'type': 'failed', 'result': {'error_code': 'validation_failed'}}
        StrategyPage._walk_forward_event(page, event)
        notice = NotificationLog().accept_event(page.state.last_operation, event)
        self.assertEqual(page.wf_wizard.message.text(), failure_hint(notice.error_code))
        page.host.record_event.assert_not_called()
        page.host.start_job.assert_not_called()
        self.assertFalse(hasattr(page.state, '_wf_pending_reconcile'))

    def test_failed_result_without_code_uses_generic_hint(self):
        page = self.page('ui_walk_forward_read')
        page.walk_forward_results = Mock()
        page.result_panel = Mock()
        page._refresh_walk_forward_references = Mock()
        event = {'type': 'result', 'result': {'status': 'failed', 'oos': 'OOS_SECRET', 'final_holdout': 'HOLDOUT_SECRET'}}
        with patch('desktop_walk_forward.preview_text', return_value=''), patch('desktop_pages.wf_wizard.display_result_rows', return_value=[]):
            StrategyPage._walk_forward_event(page, event)
        notice = NotificationLog().accept_event(page.state.last_operation, event)
        self.assertEqual(page.wf_wizard.message.text(), failure_hint(notice.error_code))
        self.assertEqual(notice.error_code, 'operation_failed')

    def test_hint_label_has_explicit_catalogue_accessible_name(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'desktop_pages/wf_wizard.py').read_text(encoding='utf-8'))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and ast.unparse(node.func) == 'self.message.setAccessibleName'
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.unparse(calls[0].args[0]), "ui_text('wf.failure_hint_name')")
        self.assertTrue(ui_text('wf.failure_hint_name'))

    def test_new_preview_and_run_clear_hint_and_keep_consent_required(self):
        page = self.page()
        page.wf_wizard.message.setText(failure_hint())
        StrategyPage._invalidate_walk_forward_preview(page)
        self.assertEqual(page.wf_wizard.message.text(), '')
        self.assertFalse(page.walk_forward_start.isEnabled())
        page.wf_wizard.message.setText(failure_hint())
        with self.assertRaises(ValidationError):
            StrategyPage.run_walk_forward(page)
        self.assertEqual(page.wf_wizard.message.text(), '')
        page.host.start_job.assert_not_called()

    def test_count_and_conservative_duration_are_the_existing_projection(self):
        result = {
            'folds': [{'index': 0, 'train': {'start': 0, 'end': 10}, 'validation': {'start': 10, 'end': 15}, 'oos': {'start': 15, 'end': 20}}],
            'final_holdout': {'start': 20, 'end': 30},
            'candidate_count': 5,
            'oos_values': 'OOS_SECRET',
            'holdout_values': 'HOLDOUT_SECRET',
        }
        wizard = SimpleNamespace(timeline=Mock(), summary=Mock(), preview_summary=QLabel(), sync_consent=Mock())
        for count in (0, 1, 1000):
            result['planned_evaluations_upper_bound'] = count
            before = copy.deepcopy(result)
            WalkForwardWizard.show_preview(wizard, result)
            self.assertEqual(before, result)
            text = wizard.preview_summary.text()
            self.assertIn(ui_text('wf.summary').format('1', '5', display_number(count)), text)
            seconds = estimated_seconds(count, MEASURED_EVALUATION_SECONDS)
            if count:
                self.assertEqual(duration_estimate_text(count), ui_text('wf.duration_estimate').format(display_number(seconds)))
                self.assertIn(duration_estimate_text(count), text)
                for wording in ('\u9810\u4f30', '\u6700\u591a', '\u975e\u5b8c\u6210\u4fdd\u8b49'):
                    self.assertIn(wording, text)
            else:
                self.assertIsNone(seconds)
                self.assertEqual(duration_estimate_text(count), '')
            self.assertNotIn('OOS_SECRET', text)
            self.assertNotIn('HOLDOUT_SECRET', text)
        for count in (-1, True, 1.0, '1000', None):
            self.assertEqual(duration_estimate_text(count), '')

    def test_same_estimate_label_precedes_consent_on_final_step(self):
        steps = [QWidget() for _ in range(5)]
        layouts = [QVBoxLayout(step) for step in steps]
        page = self.page()
        page.state.jobs = SimpleNamespace(active=False)
        page.state._wf_preview = {'planned_evaluations_upper_bound': 1000}
        label = QLabel(duration_estimate_text(1000))
        layouts[3].addWidget(label)
        layouts[4].addWidget(page.walk_forward_consent)
        layouts[4].addWidget(page.walk_forward_start)
        wizard = SimpleNamespace(
            position=3,
            page=page,
            layouts=layouts,
            preview_summary=label,
            message=QLabel(),
            stack=Mock(),
            validate_step=lambda step: '',
            update_header=Mock(),
        )
        wizard.sync_consent = lambda: WalkForwardWizard.sync_consent(wizard)
        self.assertTrue(WalkForwardWizard.go_to(wizard, 4))
        self.assertIs(layouts[4].itemAt(0).widget(), label)
        self.assertIs(layouts[4].itemAt(1).widget(), page.walk_forward_consent)
        self.assertFalse(label.isHidden())
        self.assertFalse(page.walk_forward_consent.isChecked())
        self.assertFalse(page.walk_forward_start.isEnabled())
        page.walk_forward_consent.setChecked(True)
        wizard.sync_consent()
        self.assertTrue(page.walk_forward_start.isEnabled())
        page.state.jobs.active = True
        wizard.sync_consent()
        self.assertFalse(page.walk_forward_start.isEnabled())
        self.assertTrue(WalkForwardWizard.go_to(wizard, 3))
        self.assertIs(label.parentWidget(), steps[3])


if __name__ == '__main__':
    unittest.main()
