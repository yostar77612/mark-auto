"""Test-only observer controls; no Windows/Qt or deadline acceptance claim."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
import ast
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from quantlab import walk_forward
from tests.test_walk_forward import inputs, fake_worker
from tests.active_writer_timeout_diagnostics import (MAX_FUNCTION_LABEL, MAX_REPORT_BYTES,
                                                      WriterDiagnostics, observe_writer)


class ActiveWriterDiagnosticTests(unittest.TestCase):
    def test_core_observer_preserves_33_calls_93_full_saves_exports_and_active_read(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def paused_worker(*args, **kwargs):
            calls.append(args[1][0].manifest['walk_forward_split']['role'])
            entered.set()
            if not release.wait(5):
                raise AssertionError('Writer not released')
            return fake_worker(*args, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data, plan = inputs(process_start_method='spawn')
            output = root / 'run'
            configure = walk_forward._configure_state_storage
            modes = []
            def checked_configuration(db, **kwargs):
                result = configure(db, **kwargs)
                modes.append((db.execute('PRAGMA synchronous').fetchone(),
                              db.execute('PRAGMA journal_mode').fetchone()))
                return result
            original_connect, original_write = sqlite3.connect, Path.write_text
            original_save, original_encode = walk_forward._save_state, json.dumps
            with patch.object(walk_forward, '_run_bounded', side_effect=paused_worker), \
                 patch.object(walk_forward, '_configure_state_storage', checked_configuration), \
                 observe_writer() as diagnosis, ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(diagnosis.run, walk_forward.run_walk_forward,
                    data, plan=plan, output_dir=output, holdout_registry_path=root/'controls'/'holdout.sqlite3')
                try:
                    self.assertTrue(entered.wait(5))
                    reader = walk_forward.read_walk_forward_state(output)
                    self.assertEqual(reader['status'], 'running')
                    self.assertEqual(reader['summary']['evaluations_reserved'], 1)
                    self.assertFalse(future.done())
                    self.assertEqual(calls, ['train'])
                finally:
                    release.set()
                result = future.result(timeout=10)
                self.assertEqual(result['status'], 'completed')
            self.assertEqual(len(calls), 33)
            self.assertEqual(modes, [((2,), ('wal',))])
            snapshot = diagnosis.snapshot()
            counts = {row['phase']: row['calls'] for row in snapshot['timings']}
            for phase in ('wfo.save', 'sqlite.commit', 'export.write', 'export.replace'):
                self.assertEqual(counts[phase], 93, phase)
            self.assertEqual(counts['wfo.evaluate'], 33)
            self.assertEqual(snapshot['active'], [])
            self.assertEqual(walk_forward.read_walk_forward_state(output), result)
            self.assertEqual(json.loads((output/'walk_forward.json').read_text()), result)
            self.assertFalse(list(root.glob('smoke-timeout-*.json')))
            self.assertIs(sqlite3.connect, original_connect)
            self.assertIs(Path.write_text, original_write)
            self.assertIs(walk_forward._save_state, original_save)
            self.assertIs(json.dumps, original_encode)

    def test_foreign_thread_is_excluded_and_timeout_is_emitted_before_writer_join(self):
        entered, release = threading.Event(), threading.Event()
        diagnosis = WriterDiagnostics()
        def paused_writer():
            with diagnosis.measure('sqlite.commit'):
                entered.set()
                if not release.wait(5):
                    raise AssertionError('Writer not released')
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(diagnosis.run, paused_writer)
            try:
                self.assertTrue(entered.wait(5))
                with diagnosis.measure('export.write'):
                    pass  # Reader-side operations must not pollute writer timings.
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    diagnosis.report_timeout(artifact_dir=Path(folder), evaluations_started=1,
                                              future_done=future.done())
                self.assertFalse(future.done())
                target, = Path(folder).glob('smoke-timeout-active-writer-*.json')
                evidence = json.loads(target.read_text())
                self.assertEqual(evidence['timeout_seconds'], 10)
                self.assertEqual(evidence['expected_evaluations'], 33)
                self.assertEqual(evidence['evaluations_started'], 1)
                self.assertFalse(evidence['future_done'])
                self.assertEqual([row['phase'] for row in evidence['active']], ['writer.body', 'sqlite.commit'])
                self.assertNotIn('export.write', {row['phase'] for row in evidence['timings']})
                self.assertIn('ACTIVE_WRITER_TIMEOUT_DIAGNOSTIC ', stderr.getvalue())
                raw = target.read_text()
                self.assertNotIn(folder, raw)
                self.assertNotIn('args', raw)
                self.assertTrue(evidence['writer_stack'])
                for frame in evidence['writer_stack']:
                    self.assertEqual(set(frame), {'module', 'line', 'function'})
            finally:
                release.set()
            future.result(timeout=5)

    def test_artifact_failure_does_not_mask_original_timeout(self):
        diagnosis = WriterDiagnostics()
        original = TimeoutError('Original gate')
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder)/'file'
            blocked.write_text('existing')
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(TimeoutError) as raised:
                try:
                    raise original
                except TimeoutError:
                    diagnosis.report_timeout(artifact_dir=blocked, evaluations_started=1, future_done=False)
                    raise
            self.assertIs(raised.exception, original)
            self.assertIn('ACTIVE_WRITER_DIAGNOSTIC_ERROR FileExistsError', stderr.getvalue())

    def test_exception_restores_all_observed_callables(self):
        targets = [(sqlite3, 'connect'), (Path, 'write_text'), (Path, 'replace'),
                   (walk_forward, '_save_state'), (walk_forward, 'to_dict'), (json, 'dumps')]
        originals = [getattr(owner, name) for owner, name in targets]
        with self.assertRaisesRegex(RuntimeError, 'original'):
            with observe_writer():
                raise RuntimeError('original')
        self.assertEqual([getattr(owner, name) for owner, name in targets], originals)

    def test_actual_adapter_handler_keeps_original_timeout_if_path_resolution_fails(self):
        # Compile only the actual handler, so this safety regression runs without Qt.
        path = Path(__file__).with_name('test_desktop_walk_forward.py')
        module = ast.parse(path.read_text())
        adapter = next(node for node in module.body if isinstance(node, ast.ClassDef)
                       and node.name == 'WalkForwardAdapterTests')
        method = next(node for node in adapter.body if isinstance(node, ast.FunctionDef)
                      and node.name == 'test_read_active_writer_reports_uncertain_running_state_without_recovery')
        handler = next(node for node in ast.walk(method) if isinstance(node, ast.Try)
                       and any(isinstance(item.type, ast.Name) and item.type.id == 'TimeoutError'
                               for item in node.handlers))
        extracted = ast.parse('def check(self, diagnosis, calls, future): pass')
        extracted.body[0].body = [handler]
        namespace = {'Path': Path, '__file__': str(path)}
        exec(compile(ast.fix_missing_locations(extracted), '<adapter-handler>', 'exec'), namespace)
        original = TimeoutError('Original gate')
        future, diagnosis = Mock(), Mock()
        future.result.side_effect = original
        with patch.object(Path, 'resolve', side_effect=OSError('Do not retain path error')), \
             self.assertRaises(TimeoutError) as raised:
            namespace['check'](self, diagnosis, ['train'], future)
        self.assertIs(raised.exception, original)
        future.result.assert_called_once_with(timeout=10)
        diagnosis.report_timeout.assert_not_called()

    def test_oversized_stack_function_name_is_not_retained(self):
        entered, release = threading.Event(), threading.Event()
        namespace = {}
        exec(compile('def paused(entered, release):\n entered.set()\n release.wait(5)\n',
                     '/DO_NOT_RETAIN/core.py', 'exec'), namespace)
        paused = namespace['paused']
        oversized = 'private_function_' + 'x' * 300000
        paused.__code__ = paused.__code__.replace(co_name=oversized)
        diagnosis = WriterDiagnostics()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(diagnosis.run, paused, entered, release)
            try:
                self.assertTrue(entered.wait(5))
                value = diagnosis.snapshot()
                encoded = json.dumps(value)
                self.assertNotIn(oversized, encoded)
                self.assertNotIn('DO_NOT_RETAIN', encoded)
                self.assertLess(len(encoded.encode('utf-8')), MAX_REPORT_BYTES)
                self.assertLessEqual(len(value['writer_stack']), 30)
                self.assertTrue(all(len(row['function']) <= MAX_FUNCTION_LABEL
                                    for row in value['writer_stack']))
            finally:
                release.set()
            future.result(timeout=5)

    def test_oversized_report_is_not_written_or_emitted(self):
        diagnosis = WriterDiagnostics()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(diagnosis, 'snapshot', return_value={'unsafe': 'x' * MAX_REPORT_BYTES}), \
                 redirect_stderr(stderr):
                diagnosis.report_timeout(artifact_dir=Path(folder), evaluations_started=1, future_done=False)
            self.assertFalse(list(Path(folder).iterdir()))
        self.assertEqual(stderr.getvalue(), 'ACTIVE_WRITER_DIAGNOSTIC_ERROR ValueError\n')
