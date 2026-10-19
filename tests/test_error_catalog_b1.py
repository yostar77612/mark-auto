"""B1 catalogue and worker/log contract; no Qt windows or child processes."""

import ast
from contextlib import contextmanager, nullcontext
import hashlib
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from quantlab import desktop_runtime as runtime
from quantlab.analysis_recovery import RecoveryError
from quantlab.core import ValidationError
from quantlab.desktop_errors import error_message, exception_code
from quantlab.errors import ERROR_LABELS, ERROR_TABLE, ErrorCode


ROOT = Path(__file__).resolve().parents[1]
SECRET = 'private-token C:/private/account'
# Captured by AST-reading git show 17b5b1b:quantlab/errors.py, with the renderer
# from that commit. JSON: {code: [explanation, action, error_message(code)]},
# ensure_ascii=False, sort_keys=True, UTF-8. No baseline code is added in B1.
BASELINE_COUNT = 64
BASELINE_SHA256 = '32bbb3f29a7841c5689efadfa7f8a800b9d2bbcfa299d7372d2f110a3d73da49'


@contextmanager
def log_directory():
    # Inherit workspace ACLs; Python's Windows private temp ACL excludes the
    # restricted test runner. Only the real log file lives in this directory.
    directory = ROOT / 'tests' / ('.b1-log-' + uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()


def defined_keys(source):
    """Retain duplicate keys that importing a dict would silently discard."""
    keys = []
    for node in ast.walk(ast.parse(source)):
        literal = None
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'ERROR_LABELS', 'ERROR_TABLE'} for t in node.targets):
            literal = node.value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {'ERROR_LABELS', 'ERROR_TABLE'}
            and node.func.attr == 'update'
            and node.args
        ):
            literal = node.args[0]
        if isinstance(literal, ast.Dict):
            keys.extend(ast.literal_eval(key) for key in literal.keys)
    return keys


class ErrorCatalogTests(unittest.TestCase):
    def test_source_keys_are_unique_and_enum_is_exact(self):
        keys = defined_keys((ROOT / 'quantlab/errors.py').read_text(encoding='utf-8-sig'))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(ERROR_TABLE))
        self.assertEqual(len(ErrorCode.__members__), len(keys))
        self.assertEqual({member.value for member in ErrorCode}, set(keys))
        self.assertEqual(ERROR_LABELS, {code: row.explanation for code, row in ERROR_TABLE.items()})
        for code, row in ERROR_TABLE.items():
            self.assertRegex(code, r'^[a-z][a-z0-9_]*$')
            self.assertTrue(row.explanation and row.action)

    def test_duplicate_guard_observes_overwrites_in_literals_and_updates(self):
        for source in (
            "ERROR_TABLE = {'duplicate': 1, 'duplicate': 2}",
            "ERROR_LABELS = {'duplicate': 1}\nERROR_LABELS.update({'duplicate': 2})",
            "ERROR_TABLE = {'duplicate': 1}\nERROR_TABLE.update({'duplicate': 2})",
        ):
            keys = defined_keys(source)
            self.assertNotEqual(len(keys), len(set(keys)))

    def test_existing_message_bytes_match_17b5b1b(self):
        payload = {code: [row.explanation, row.action, error_message(code)] for code, row in ERROR_TABLE.items()}
        self.assertEqual(len(payload), BASELINE_COUNT)
        self.assertEqual(hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest(), BASELINE_SHA256)

    def test_single_text_table_and_literal_display_codes(self):
        paths = sorted((ROOT / 'quantlab').glob('*.py')) + sorted(ROOT.glob('desktop*.py')) + sorted((ROOT / 'desktop_pages').glob('*.py'))
        tables = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'error_message' and node.args:
                    code = node.args[0]
                    if isinstance(code, ast.Constant) and isinstance(code.value, str):
                        self.assertIn(code.value, ERROR_TABLE, str(path))
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'ErrorCode':
                    self.assertIn(node.attr, ErrorCode.__members__, str(path))
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values):
                        if not isinstance(key, ast.Constant) or key.value not in ERROR_TABLE:
                            continue
                        # Code-routing maps and UI string keys are not message tables.
                        is_text = isinstance(value, ast.Constant) and isinstance(value.value, str) and any('\u3400' <= c <= '\u9fff' for c in value.value)
                        is_row = isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'ErrorText'
                        if is_text or is_row:
                            tables.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(set(tables), {'quantlab/errors.py'})
        self.assertEqual(len(tables), len(ERROR_TABLE))

    def test_unknown_fallbacks_and_exception_pickle_paths_are_unchanged(self):
        for value in (None, [], {}, SECRET, 1):
            self.assertEqual(error_message(value), error_message('operation_failed'))
        for exc, expected in (
            (RuntimeError(SECRET), 'operation_failed'),
            (ValidationError(SECRET), 'validation_failed'),
            (OSError(SECRET), 'operation_failed_local'),
        ):
            exc.code = SECRET
            self.assertEqual(exception_code(exc), expected)
            self.assertEqual(str(exc), SECRET)
        exc = ValidationError(SECRET)
        exc.code = 'market_data_invalid'
        self.assertEqual(exception_code(exc), 'market_data_invalid')
        for exc in (exc, RecoveryError(SECRET)):
            restored = pickle.loads(pickle.dumps(exc))
            self.assertIs(type(restored), type(exc))
            self.assertEqual(str(restored), SECRET)
        self.assertEqual(RecoveryError.__module__, 'quantlab.analysis_recovery')


class WorkerLogTests(unittest.TestCase):
    def manager(self, directory, packets):
        paths = SimpleNamespace(logs=Path(directory))
        paths.ensure = lambda: paths
        manager = runtime.JobManager(paths)
        manager._operation = 'ui_campaign'
        manager.job_id = 'b1-offline'
        manager.process = SimpleNamespace(is_alive=lambda: True)
        pending = list(packets)
        manager.receiver = SimpleNamespace(poll=lambda: bool(pending), recv_bytes=lambda limit: json.dumps(pending.pop(0)).encode('utf-8'))
        return manager

    def test_worker_exception_code_reaches_real_jsonl_and_schema(self):
        for exc, expected in ((ValidationError(SECRET), 'validation_failed'), (OSError(SECRET), 'operation_failed_local')):
            with self.subTest(exception=type(exc).__name__), log_directory() as directory:
                packets = []
                sender = SimpleNamespace(send_bytes=lambda raw: packets.append(json.loads(raw)), close=Mock())
                with (
                    patch.object(runtime.sys, 'platform', 'win32'),
                    patch.object(runtime, '_worker_recovery_guard', return_value=nullcontext()),
                    patch.object(runtime, '_worker_operation_executor', return_value=Mock(side_effect=exc)),
                ):
                    runtime._job_worker(sender, SimpleNamespace(wait=lambda seconds: True), 'ui_campaign', {}, '.', None, 'b1-offline')
                self.assertEqual(packets[-1]['error_code'], expected)
                manager = self.manager(directory, packets)
                manager.poll()
                raw = manager.event_log.path.read_text(encoding='utf-8')
                records = [json.loads(line) for line in raw.splitlines()]
                self.assertEqual(records[-1]['error_code'], expected)
                self.assertEqual(records[-1]['event'], 'error')
                self.assertNotIn(SECRET, raw)
                self.assertNotIn('error_type', raw)
                self.assertEqual([json.loads(line) for line in manager.event_log.tail()], records)

    def test_untrusted_or_missing_packet_code_uses_fixed_fallback(self):
        for code in (None, SECRET, [], {}):
            with self.subTest(code=code), log_directory() as directory:
                packet = {'job_id': 'b1-offline', 'type': 'error', 'message': SECRET, 'error_code': code}
                manager = self.manager(directory, [packet])
                manager.poll()
                record = json.loads(manager.event_log.path.read_text(encoding='utf-8'))
                self.assertEqual(record['error_code'], 'operation_failed')
                self.assertNotIn(SECRET, json.dumps(record))

    def test_logging_disabled_and_diagnostic_write_failures_remain_nonfatal(self):
        with log_directory() as directory:
            manager = self.manager(directory, [])
            manager.logging_enabled = False
            manager._log('error', error_code='validation_failed')
            self.assertFalse(manager.event_log.path.exists())
            manager.logging_enabled = True
            with patch.object(manager.event_log, 'append', side_effect=OSError(SECRET)):
                manager._log('error', error_code='validation_failed')
