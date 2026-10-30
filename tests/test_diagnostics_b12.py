"""Cheap B12 privacy, bounded snapshot and clipboard contracts; no shown windows."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from desktop_app.features.settings.diagnostics import DiagnosticsPanel, snapshot_for_state
from desktop_app.components.job_progress import JobFeedback
from quantlab import __version__
from quantlab.desktop_runtime import AppPaths
from quantlab.diagnostics import LOG_BYTES, MAX_BYTES, MAX_ERRORS, TRUNCATION_MARKER, build_diagnostics, copy_diagnostics, read_error_records
from quantlab.errors import ERROR_TABLE
from quantlab.paper import LiveBroker, LiveTradingDisabled
from tests.test_t9_onboarding import sandbox_ui

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
SECRETS = (
    'Bearer fake-bearer-secret',
    'refresh-token-secret',
    'cookie=private-session',
    'ACC-12345',
    'C:/Users/Mark/private/secret.json',
    '/home/Mark/private',
    'exception message sentinel',
    'private@example.com',
    'Authorization: secret-header',
)


@contextmanager
def workspace():
    # Inherit the repository ACL instead of private TemporaryDirectory ACLs.
    root = ROOT / 'tests' / ('.b12-' + uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


class DiagnosticsTests(unittest.TestCase):
    def assert_private(self, text):
        for sentinel in SECRETS:
            self.assertNotIn(sentinel, text)

    def test_sections_and_determinism(self):
        inputs = {
            'workspace': True,
            'data': {'source': 'TAIFEX', 'mode': 'history', 'latest_bar_timestamp': '2026-10-19T11:59:00+00:00'},
            'job': {'operation': 'ui_backtest', 'stage': 'run_backtest', 'active': True},
            'errors': [{'error_code': 'validation_failed'}],
            'now': NOW,
        }
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), patch.object(Path, 'open', side_effect=AssertionError('I/O forbidden')):
            text = build_diagnostics(**inputs)
        self.assertEqual(text, build_diagnostics(**inputs))
        value = json.loads(text)
        self.assertEqual(set(value), {'app_version', 'workspace', 'data', 'job', 'last_errors', 'errors_status', 'startup_timing'})
        self.assertEqual(value['startup_timing'], 'unavailable')
        self.assertEqual(value['app_version'], __version__)
        self.assertEqual(value['workspace'], 'available')
        self.assertEqual(value['data']['source'], 'TAIFEX')
        self.assertEqual(value['data']['age_seconds'], 60)
        self.assertEqual(value['data']['latest_bar_timestamp'], '2026-10-19T11:59:00+00:00')
        self.assertEqual(value['job'], {'operation': 'ui_backtest', 'stage': 'run_backtest', 'state': 'active'})
        self.assertEqual(value['last_errors'], [{'error_code': 'validation_failed', 'explanation': ERROR_TABLE['validation_failed'].explanation}])

    def test_every_input_field_rejects_sensitive_values(self):
        for secret in SECRETS:
            with self.subTest(secret=secret):
                data = dict.fromkeys(('source', 'mode', 'latest_bar_timestamp', 'latest_bar_trade_date', 'account_id', 'token', 'exception'), secret)
                job = dict.fromkeys(('operation', 'stage', 'active', 'authorization', 'cookie', 'email'), secret)
                record = dict.fromkeys(('error_code', 'message', 'explanation', 'traceback', 'operation', 'event', 'time'), secret)
                text = build_diagnostics(workspace=secret, data=data, job=job, errors=[record], now=secret)
                self.assert_private(text)
                value = json.loads(text)
                self.assertEqual(value['last_errors'][0]['error_code'], 'operation_failed')
                self.assertEqual(value['data']['latest_bar_timestamp'], 'unavailable')
                self.assertEqual(value['job']['stage'], 'unknown')

    def test_exception_is_never_stringified(self):
        class PrivateError(Exception):
            def __str__(self):
                raise AssertionError('exception str forbidden')

            def __repr__(self):
                raise AssertionError('exception repr forbidden')

        error = PrivateError()
        text = build_diagnostics(workspace=error, data={'source': error}, job={'stage': error}, errors=[{'error_code': error, 'exception': error}])
        self.assertIn('operation_failed', text)

    def test_worker_error_and_log_code_share_b1_projection(self):
        feedback = JobFeedback(Mock())
        feedback.begin('test-job')
        shell = SimpleNamespace(last_operation='ui_import', _subscription_campaign=False, notify_local=Mock())
        packet = {'job_id': 'test-job', 'type': 'error', 'stage': 'load_data', 'error_code': 'validation_failed', 'message': ' '.join(SECRETS)}
        self.assertTrue(feedback.accept(shell, packet))
        with workspace() as root:
            log = root / 'desktop-events.jsonl'
            log.write_text(json.dumps({**packet, 'event': 'error', 'cookie': SECRETS[2]}) + '\n', encoding='utf-8')
            state = SimpleNamespace(paths=SimpleNamespace(root=root, logs=root), diagnostics_feedback=feedback, last_operation='ui_import')
            value = json.loads(snapshot_for_state(state, now=NOW))
            self.assertEqual(value['last_errors'][0]['error_code'], 'validation_failed')
            self.assertEqual(value['job']['stage'], 'load_data')
            self.assert_private(json.dumps(value))
            self.assertEqual(read_error_records(log)[0]['error_code'], 'validation_failed')
            log.write_text(json.dumps({'event': 'error', 'error_code': SECRETS[0], 'message': SECRETS[6]}) + '\n', encoding='utf-8')
            self.assertEqual(read_error_records(log)[0]['error_code'], 'operation_failed')
        # Persistent logging disabled / absent: memory still supplies the worker code.
        self.assertIn('validation_failed', snapshot_for_state(SimpleNamespace(diagnostics_feedback=feedback), now=NOW))

    def test_cached_series_does_not_echo_provenance_or_account(self):
        series = SimpleNamespace(
            bars=[SimpleNamespace(timestamp='2026-10-19T11:59:00Z', trade_date='2026-10-19', source_id=SECRETS[0], account_id=SECRETS[3])],
            instrument=SimpleNamespace(exchange='TWSE', account_id=SECRETS[3]),
            provenance=SimpleNamespace(mode='eod', source_url=SECRETS[4], token=SECRETS[1], cookie=SECRETS[2], attribution=SECRETS[6]),
        )
        market = SimpleNamespace(selected_series=lambda: series)
        value = json.loads(snapshot_for_state(SimpleNamespace(market=market, jobs=SimpleNamespace(active=True)), now=NOW))
        self.assertEqual(value['data']['source'], 'TWSE')
        self.assertEqual(value['data']['age_seconds'], 60)
        self.assert_private(json.dumps(value))
        series.bars[0].timestamp = None
        value = json.loads(snapshot_for_state(SimpleNamespace(market=market), now=NOW))
        self.assertEqual(value['data']['latest_bar_trade_date'], '2026-10-19')
        self.assertEqual(value['data']['age_seconds'], 'unavailable')

    def test_empty_workspace_read_only_and_missing_or_corrupt_log(self):
        with workspace() as root:
            jobs = SimpleNamespace(active=False, start=Mock(side_effect=AssertionError('job forbidden')))
            state = SimpleNamespace(paths=SimpleNamespace(root=root, logs=root), jobs=jobs)
            with (
                patch('socket.socket', side_effect=AssertionError('network forbidden')),
                patch.object(Path, 'mkdir', side_effect=AssertionError('write forbidden')),
            ):
                value = json.loads(snapshot_for_state(state, now=NOW))
            self.assertEqual(list(root.iterdir()), [])
            jobs.start.assert_not_called()
            self.assertEqual(value['errors_status'], 'unavailable')
            self.assertEqual(value['data']['source'], 'unavailable')
            self.assertEqual(value['job']['state'], 'idle')
            log = root / 'bad.jsonl'
            log.write_bytes(b'\xff\nnot json\n[]\n')
            self.assertEqual(read_error_records(log), [])
            with patch.object(Path, 'open', side_effect=PermissionError(SECRETS[4])):
                self.assertIsNone(read_error_records(log))
            log.write_bytes(b'[' * 2000 + b'\n')
            self.assertEqual(read_error_records(log), [])
        self.assertIn('unavailable', snapshot_for_state(SimpleNamespace(), now=NOW))

    def test_log_read_is_bounded_and_projection_ignores_all_extra_fields(self):
        stream = Mock()
        stream.tell.return_value = 10 * LOG_BYTES
        stream.read.return_value = json.dumps({'event': 'error', 'error_code': 'validation_failed', 'payload': list(SECRETS)}).encode()
        with patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'is_symlink', return_value=False), patch.object(Path, 'open') as opened:
            opened.return_value.__enter__.return_value = stream
            records = read_error_records('unused.jsonl')
        stream.read.assert_called_once_with(LOG_BYTES)
        stream.seek.assert_any_call(9 * LOG_BYTES)
        self.assertEqual(records, [{'error_code': 'validation_failed', 'explanation': ERROR_TABLE['validation_failed'].explanation}])
        self.assert_private(build_diagnostics(errors=records))

    def test_utf8_cap_truncation_preserves_newest_errors_and_sections(self):
        records = [{'error_code': code} for code in ERROR_TABLE] * 10
        text = build_diagnostics(errors=records)
        self.assertLessEqual(len(text.encode('utf-8')), MAX_BYTES)
        self.assertIn(TRUNCATION_MARKER, text)
        value = json.loads(text)
        self.assertLess(len(value['last_errors']), MAX_ERRORS)
        self.assertEqual(value['last_errors'][0]['error_code'], records[-1]['error_code'])
        self.assertTrue({'app_version', 'workspace', 'data', 'job', 'last_errors'} <= value.keys())

    def test_fake_clipboard_and_real_panel_action_copy_exact_builder_text(self):
        app = QApplication.instance() or QApplication([])
        text = build_diagnostics(now=NOW)
        clipboard = Mock()
        copy_diagnostics(text, clipboard)
        clipboard.setText.assert_called_once_with(text)
        panel = DiagnosticsPanel(lambda: text)
        with patch('desktop_app.features.settings.diagnostics.QApplication.clipboard', return_value=clipboard):
            panel.copy_button.click()
        self.assertEqual(panel.output.toPlainText(), text)
        self.assertEqual(panel.text, text)
        self.assertEqual(clipboard.setText.call_count, 2)
        self.assertEqual(clipboard.setText.call_args.args, (text,))
        self.assertFalse(panel.isVisible())
        panel.close()
        self.assertIsNotNone(app)

    def test_live_trading_remains_disabled_and_public_ui_names_unchanged(self):
        # Execute the existing registry assertion without the expensive dispatcher suite.
        from tests.test_ui_operations_registry import RegistryTests

        RegistryTests('test_public_names_unchanged').test_public_names_unchanged()
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker()

    def test_controls_are_hidden_until_existing_maintenance_toggle_opens(self):
        # Load the full shell only for the mounted-controls regression.
        from desktop_app.shell.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        with sandbox_ui():
            with tempfile.TemporaryDirectory(prefix='b12-maintenance-') as folder:
                paths = AppPaths(Path(folder) / 'workspace').ensure()
                jobs = SimpleNamespace(active=False, poll=lambda: [], start=Mock(), close=Mock())
                window = MainWindow(paths, jobs)
                try:
                    for timer in window.findChildren(QTimer):
                        timer.stop()
                    page = window.settings_page
                    self.assertFalse(page.maintenance_toggle.isChecked())
                    self.assertFalse(page.diagnostics_panel.isVisibleTo(page))
                    page.maintenance_toggle.setChecked(True)
                    self.assertTrue(page.diagnostics_panel.isVisibleTo(page))
                    actual = sorted({widget.objectName() for widget in [window, *window.findChildren(QWidget)] if widget.objectName()})
                    expected = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
                    self.assertEqual(actual, expected)
                    jobs.start.assert_not_called()
                finally:
                    window.close()
                    window.deleteLater()
        self.assertIsNotNone(app)
