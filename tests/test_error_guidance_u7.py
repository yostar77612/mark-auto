"""Cheap U7 regression evidence: presentation is not broken."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QFormLayout, QPushButton, QVBoxLayout, QWidget

from desktop_forms import StrategyForm
from desktop_pages.async_status import AsyncStatus
from desktop_pages.error_guidance import NEXT_STEP_KEYS, clear_inline, next_step, run_inline, with_next_step
from desktop_pages.job_progress import JobFeedback, JobProgress
from desktop_pages.widgets import WidgetTools
from desktop_strings import ui_text
from quantlab.desktop_errors import error_message
from quantlab.errors import ERROR_TABLE
from tests.test_no_hardcoded_ui_text import UI_PACKAGE_MODULES
from tests.test_no_inline_stylesheet import stylesheet_calls


ROOT = Path(__file__).resolve().parents[1]
# These are actual B1 codes; generic validation covers data/calendar/range/bars
# and the existing single-job guard. No more-specific B1 codes exist for them.
COMMON_CODES = {
    'validation_failed',
    'market_data_invalid',
    'history_file_required',
    'history_sessions_required',
    'history_session_invalid',
    'history_date_invalid',
    'history_session_limit',
    'network_disabled',
    'operation_failed_plan',
    'configuration_blocked',
    'http_transport_failed',
    'authorization_busy',
}


class ErrorGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_common_code_is_real_and_resolves_and_unknown_is_unchanged(self):
        self.assertEqual(set(NEXT_STEP_KEYS), COMMON_CODES)
        self.assertLessEqual(COMMON_CODES, set(ERROR_TABLE))
        for code in ERROR_TABLE:
            with self.subTest(code=code):
                text = next_step(code)
                if code in COMMON_CODES:
                    self.assertTrue(text.strip())
                    self.assertIn(
                        NEXT_STEP_KEYS[code],
                        (
                            'errors.next.validation',
                            'errors.next.data',
                            'errors.next.calendar',
                            'errors.next.provider',
                            'errors.next.running',
                        ),
                    )
                else:
                    self.assertEqual(text, '')
        for code in ('bogus-code', None, [], 'operation_failed'):
            self.assertEqual(next_step(code), '')
            self.assertEqual(with_next_step('existing message', code), 'existing message')

    def test_fixed_hints_name_catalog_pages_and_have_no_sensitive_content(self):
        pages = [ui_text('ui.data_page.title'), ui_text('ui.strategy_page.title'), ui_text('ui.backtest_page.title'), ui_text('ui.settings_page.title')]
        for code in COMMON_CODES:
            text = next_step(code)
            self.assertTrue(any(page in text for page in pages))
            for forbidden in ('/', '\\', 'token', 'SECRET', 'OOS', 'holdout', '?' * 3):
                self.assertNotIn(forbidden, text)
            self.assertFalse(any(c.isdigit() for c in text))

    def test_catalog_source_is_unchanged(self):
        # Re-pinned after A1: the only catalogue change is the added paper_manual_order_lock entry.
        # Re-pinned for R1 (PR #76, owner approved): five reconciliation errors and the user_confirmed_consumed
        # entry were added, and unknown_outcome_requires_manual_resolution now points to the new dialog.
        # Re-pinned again (owner approved): the user_confirmed_consumed action names the 進階連線管理 section.
        source = (ROOT / 'quantlab/errors.py').read_text(encoding='utf-8-sig')
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), '514ef06e169776c6d7d75252d36382ee64dba8b51f7cd523d95f9de48de2a607')

    def test_form_failure_is_inline_without_message_box_then_clears(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = StrategyForm(page)
        layout.addWidget(form)
        form.fields['fast'].setText('invalid')
        messages = []

        def safe(callback):
            try:
                callback()
            except ValueError:
                messages.append(error_message('validation_failed'))

        host = SimpleNamespace(_safe=safe, _confirm_button=lambda button, callback: callback(), actions=[])
        button = WidgetTools._button(host, layout, 'test', 'test_run', form.build_payload)
        with (
            patch('PySide6.QtWidgets.QMessageBox.question', side_effect=AssertionError('dialog')),
            patch('PySide6.QtWidgets.QMessageBox.warning', side_effect=AssertionError('dialog')),
            patch('PySide6.QtWidgets.QMessageBox.critical', side_effect=AssertionError('dialog')),
        ):
            button.click()
        label = button._error_guidance_label
        self.assertIs(label.parentWidget(), page)
        self.assertEqual(label.text(), with_next_step(error_message('validation_failed'), 'validation_failed'))
        self.assertEqual(messages, [error_message('validation_failed')])
        self.assertEqual(label.objectName(), 'error_next_step')
        self.assertEqual(label.accessibleName(), label.text())
        self.assertTrue(label.wordWrap())
        self.assertFalse(label.isHidden())
        form.fields['fast'].setText('5')
        button.click()
        self.assertEqual(label.text(), '')
        self.assertTrue(label.isHidden())

    def test_private_error_values_are_neutralized_and_toggle_and_run_clear(self):
        page = QWidget()
        page.privacy = SimpleNamespace(enabled=True)
        layout = QVBoxLayout(page)
        button = QPushButton(page)
        layout.addWidget(button)

        def fail():
            raise ValueError('amount 987654 C:/private/account SECRET')

        with self.assertRaises(ValueError):
            run_inline(button, fail, owner=page, layout=layout)
        label = button._error_guidance_label
        self.assertIn(next_step('validation_failed'), label.text())
        for secret in ('987654', 'C:/private', 'account', 'SECRET', error_message('validation_failed')):
            self.assertNotIn(secret, label.text() + label.accessibleName())
        page.privacy.enabled = False
        label._privacy_render()
        self.assertTrue(label.text().startswith(error_message('validation_failed')))
        progress = JobProgress(Mock(), page)
        feedback = JobFeedback(progress, guidance_owner=page)
        feedback.begin('new-run')
        self.assertEqual(label.text(), '')
        label._privacy_render()
        self.assertEqual(label.text(), '')
        clear_inline(SimpleNamespace())

    def test_async_failure_uses_job_code_and_new_run_removes_hint(self):
        progress = JobProgress(Mock())
        feedback = JobFeedback(progress)
        feedback.begin('job')
        host = SimpleNamespace(job_progress=progress, job_feedback=feedback)
        shell = SimpleNamespace(last_operation='test')
        feedback.accept(shell, {'job_id': 'job', 'type': 'error', 'error_code': 'validation_failed'})
        status = AsyncStatus(host=host)
        status.read_job()
        self.assertIn(next_step('validation_failed'), status.label.text())
        self.assertTrue(status.label.wordWrap())
        self.assertTrue(status.label.objectName())
        self.assertEqual(status.label.accessibleName(), status.label.text())
        feedback.begin('next')
        status.read_job()
        self.assertEqual(status.label.text(), ui_text('async.loading'))
        status.set_state('empty')
        self.assertEqual(status.label.text(), ui_text('async.empty'))
        status.set_state('error', error_code='bogus', exception=ValueError('SECRET'))
        self.assertEqual(status.label.text(), ui_text('async.error_unknown'))
        AsyncStatus(host=SimpleNamespace()).read_job()

    def test_explicit_shared_state_clears_across_pages_and_isolates_other_hosts(self):
        state = SimpleNamespace(actions=[])

        def safe(callback):
            try:
                callback()
            except ValueError:
                pass

        host = SimpleNamespace(state=state, _safe=safe)
        tools = WidgetTools(host)
        first, second = QWidget(), QWidget()
        first_layout, second_layout = QFormLayout(first), QVBoxLayout(second)
        fail = Mock(side_effect=ValueError('private values'))
        first_button = tools._button(first_layout, 'test', 'test_first', fail)
        second_button = tools._button(second_layout, 'test', 'test_second', Mock())
        unrelated = SimpleNamespace()
        first_button.click()
        label = first_button._error_guidance_label
        self.assertIs(label.parentWidget(), first)
        self.assertEqual(state._error_guidance_labels, [label])
        self.assertFalse(label.isHidden())
        clear_inline(unrelated)
        self.assertFalse(label.isHidden())
        second_button.click()
        self.assertEqual(label.text(), '')
        self.assertTrue(label.isHidden())
        first_button.click()
        self.assertFalse(label.isHidden())
        feedback = JobFeedback(JobProgress(Mock()), guidance_owner=state)
        feedback.begin('next-run')
        self.assertEqual(label.text(), '')
        self.assertTrue(label.isHidden())

    def test_module_and_eager_name_are_registered(self):
        name = 'desktop_pages/error_guidance.py'
        self.assertIn(name, UI_PACKAGE_MODULES)
        self.assertEqual(stylesheet_calls((ROOT / name).read_text()), [])
        names = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text())
        self.assertIn('error_next_step', names)
        self.assertEqual(names, sorted(set(names)))
