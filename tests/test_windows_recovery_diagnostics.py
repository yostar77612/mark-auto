"""Portable observer regressions; these do not certify native Windows recovery."""
import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests import test_windows_recovery_feasibility as fixture
from tests.windows_recovery_diagnostics import (
    BARRIERS, MAX_RECORD_BYTES, MAX_REPORT_BYTES, FixtureDiagnostics,
    failure_snapshot, report_failure,
)


class WindowsRecoveryDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_original_invocation_runs_once_and_success_writes_nothing(self):
        diagnosis = FixtureDiagnostics(self.folder, 'helper')
        call = Mock(return_value=17)
        self.assertEqual(diagnosis.run(call, 'original'), 17)
        call.assert_called_once_with('original', diagnosis=diagnosis)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_original_exception_is_reraised_with_sanitized_native_codes(self):
        diagnosis = FixtureDiagnostics(self.folder, 'helper')
        error = PermissionError(5, 'SECRET message /private/path', 'SECRET filename')
        error.winerror = 32
        def failed(*, diagnosis):
            diagnosis.at('helper.job.create')
            raise error
        with self.assertRaises(PermissionError) as raised:
            diagnosis.run(failed)
        self.assertIs(raised.exception, error)
        record = failure_snapshot(self.folder, {'helper': Mock(poll=Mock(return_value=1))},
                                  'helper_before_gui')
        child = record['children']['helper']
        self.assertEqual(child['returncode'], 1)
        self.assertEqual(child['failure']['phase'], 'helper.job.create')
        self.assertEqual(child['failure']['errors'][0]['type'], 'PermissionError')
        self.assertEqual(child['failure']['errors'][0]['errno'], 5)
        self.assertEqual(child['failure']['errors'][0]['winerror'], 32)
        self.assertFalse(record['acceptance'])
        raw = json.dumps(record)
        for private in ('SECRET', '/private/path', str(self.folder)):
            self.assertNotIn(private, raw)
        self.assertLess(len(raw.encode()), MAX_REPORT_BYTES)

    def test_sqlite_codes_are_retained_without_sql_or_database_paths(self):
        diagnosis = FixtureDiagnostics(self.folder, 'gui')
        with closing(sqlite3.connect(':memory:')) as db, db:
            try:
                db.execute('SELECT SECRET_COLUMN FROM SECRET_TABLE')
            except sqlite3.OperationalError as error:
                expected = error.sqlite_errorcode
                diagnosis.at('gui.launch.commit')
                diagnosis.record_failure(error)
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')  # The fixture owns and closes the connection.
        record = failure_snapshot(self.folder, {}, 'normal')['children']['gui']['failure']
        self.assertEqual(record['errors'][0]['sqlite_errorcode'], expected)
        self.assertNotIn('SECRET', json.dumps(record))

    def test_actual_helper_preserves_primary_failure_before_cleanup_failure(self):
        # Exercise the actual helper body without invoking any native API.
        from quantlab import desktop_runtime
        primary, secondary = OSError(5, 'SECRET primary'), RuntimeError('SECRET cleanup')
        kernel = Mock()
        kernel.GetProcessId.return_value = 42
        kernel.CloseHandle.return_value = 1
        tree = Mock()
        tree.stop_and_join.side_effect = secondary
        diagnosis = FixtureDiagnostics(self.folder, 'helper')
        with patch.object(fixture, '_kernel', return_value=kernel), \
             patch.object(fixture, '_state', return_value=fixture.WAIT_TIMEOUT), \
             patch.object(desktop_runtime, '_WindowsProcessTree', return_value=tree), \
             patch.object(fixture, '_wait_file', side_effect=primary), \
             self.assertRaises(RuntimeError) as raised:
            diagnosis.run(fixture._fixture, 'helper', self.folder, 1, 'SECRET token', [2, 3])
        # Preserve the existing finalizer's behavior, but not its loss of evidence.
        self.assertIs(raised.exception, secondary)
        record = failure_snapshot(self.folder, {}, 'normal')['children']['helper']['failure']
        self.assertEqual(record['phase'], 'helper.gui_commit.wait')
        self.assertEqual(record['errors'][0]['type'], 'OSError')
        self.assertEqual(record['errors'][0]['errno'], 5)
        self.assertTrue(record['errors'][0]['frames'])
        self.assertTrue(all(set(frame) == {'module', 'line'} for frame in record['errors'][0]['frames']))
        tree.close.assert_called_once_with()
        self.assertNotIn('SECRET', json.dumps(record))

    def test_record_write_failure_never_masks_or_retries_original_failure(self):
        diagnosis = FixtureDiagnostics(self.folder, 'worker')
        original = ValueError('original')
        with patch.object(Path, 'write_text', side_effect=OSError('SECRET path')) as write:
            with self.assertRaises(ValueError) as raised:
                diagnosis.run(Mock(side_effect=original))
            diagnosis.record_failure(RuntimeError('later cleanup'))
        self.assertIs(raised.exception, original)
        self.assertEqual(write.call_count, 1)
        self.assertFalse(list(self.folder.iterdir()))

    def test_native_exit_without_python_record_is_explicitly_unavailable(self):
        process = Mock()
        process.poll.return_value = 0xC0000005
        value = failure_snapshot(self.folder, {'helper': process}, 'helper_before_gui')
        self.assertEqual(value['children']['helper']['returncode'], 0xC0000005)
        self.assertEqual(value['children']['helper']['failure'], {'status': 'unavailable'})
        self.assertFalse(value['children']['grandchild']['popen_owned'])
        self.assertEqual(process.method_calls, [('poll', (), {})])

    def test_untrusted_partial_oversized_and_extra_diagnostic_fields_are_rejected(self):
        path = self.folder / 'helper.failure.json'
        samples = ['{', 'x' * (MAX_RECORD_BYTES + 1), json.dumps({
            'role': 'helper', 'phase': 'helper.admission', 'errors': [], 'SECRET': 'TOKEN'}),
            json.dumps({'role': 'helper', 'phase': 'SECRET', 'errors': []})]
        for raw in samples:
            with self.subTest(length=len(raw)):
                path.write_text(raw, encoding='utf-8')
                value = failure_snapshot(self.folder, {}, 'normal')
                self.assertEqual(value['children']['helper']['failure'], {'status': 'unreadable'})
                self.assertNotIn('SECRET', json.dumps(value))

    def test_report_retains_original_snapshot_and_existing_artifact_pattern(self):
        (self.folder / 'gui-launch-committed.json').write_text('SECRET body', encoding='utf-8')
        artifacts = self.folder / 'artifacts'
        process = Mock(poll=Mock(return_value=1))
        text = report_failure(self.folder, {'helper': process}, 'helper_before_gui',
                              artifact_dir=artifacts, barrier='helper readiness')
        file, = artifacts.glob('smoke-timeout-*.json')
        value = json.loads(file.read_text(encoding='utf-8'))
        self.assertEqual(value['awaited_barrier'], 'helper readiness')
        self.assertEqual(set(value['barriers']), set(BARRIERS))
        self.assertTrue(value['barriers']['gui-launch-committed.json'])
        self.assertFalse(value['barriers']['helper-ready.json'])
        self.assertFalse(value['barriers']['cleanup-request.json'])
        self.assertEqual(value['children']['helper']['returncode'], 1)
        self.assertEqual(json.loads(text.split(' ', 1)[1]), value)
        self.assertNotIn('SECRET', text)
        self.assertLess(file.stat().st_size, MAX_REPORT_BYTES)
        self.assertEqual(process.method_calls, [('poll', (), {})])

    def test_report_failure_leaves_original_assertion_fail_closed(self):
        # Extract the actual failure closure without starting native children.
        source = Path(fixture.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        fail = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                    and node.name == 'fail_with_diagnostic')
        namespace = {'report_failure': report_failure, 'folder': self.folder,
                     'processes': {}, 'scenario': 'helper_before_gui',
                     'ROOT': self.folder, 'self': self}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fail], type_ignores=[])),
                     '<original-failure-closure>', 'exec'), namespace)
        with patch.object(Path, 'write_text', side_effect=OSError('SECRET artifact path')):
            with self.assertRaisesRegex(AssertionError, '^helper failed before expected barrier;') as raised:
                namespace['fail_with_diagnostic']('helper failed before expected barrier', 'helper readiness')
        self.assertIn('artifact_unavailable', str(raised.exception))
        self.assertNotIn('SECRET', str(raised.exception))

    def test_snapshot_failure_does_not_mask_original_assertion(self):
        process = Mock(poll=Mock(side_effect=OSError('SECRET poll')))
        text = report_failure(self.folder, {'helper': process}, 'normal',
                              artifact_dir=self.folder / 'artifacts')
        self.assertEqual(text, 'WINDOWS_RECOVERY_DIAGNOSTIC unavailable')
        self.assertFalse((self.folder / 'artifacts').exists())

    def test_error_chains_and_numbers_are_bounded_and_unnamed_types_are_redacted(self):
        secret_type = type('SECRET_TYPE', (Exception,), {})
        error = secret_type('SECRET body')
        error.errno = 10 ** 100
        error.winerror = True
        error.__context__ = error
        diagnosis = FixtureDiagnostics(self.folder, 'helper')
        diagnosis.record_failure(error)
        value = failure_snapshot(self.folder, {}, 'normal')
        errors = value['children']['helper']['failure']['errors']
        self.assertEqual(len(errors), 3)
        self.assertTrue(all(row['type'] == 'other' for row in errors))
        self.assertTrue(all(row['errno'] is None and row['winerror'] is None for row in errors))
        self.assertNotIn('SECRET', json.dumps(value))


if __name__ == '__main__':
    unittest.main()
