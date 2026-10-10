"""Instrumentation must observe real SQLite semantics without weakening gates."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import subprocess
import time

from tools.diagnose_paper_replay import (Timings, _instrument_connect, _write_json,
                                         _rollback_connection, _journal_mode_comparison)


class PaperDiagnosticTests(unittest.TestCase):
    def test_wrapped_sqlite_preserves_full_sync_commit_rollback_and_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'replays' / 'synthetic.sqlite3'
            path.parent.mkdir()
            timings = Timings()
            connect = _instrument_connect(sqlite3.connect, timings)
            db = connect(path)
            try:
                db.execute('PRAGMA synchronous=FULL')
                self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)
                with db:
                    db.execute('CREATE TABLE example (value INTEGER)')
                    db.execute('INSERT INTO example VALUES (?)', (7,))
                with self.assertRaises(RuntimeError):
                    with db:
                        db.execute('UPDATE example SET value=9')
                        raise RuntimeError('rollback')
                self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0], 7)
            finally:
                db.close()
            ordinary = sqlite3.connect(path)
            try:
                self.assertEqual(ordinary.execute('SELECT value FROM example').fetchone()[0], 7)
                self.assertEqual(ordinary.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            finally:
                ordinary.close()
            values = timings.snapshot()
            self.assertEqual(values['timings']['replay.transaction_exit']['calls'], 2)
            self.assertEqual(values['timings']['replay.connect']['calls'], 1)
            self.assertEqual(values['timings']['replay.close']['calls'], 1)
            self.assertEqual(values['active'], [])

    def test_timer_preserves_exception_and_does_not_record_arguments(self):
        timings = Timings()
        with self.assertRaisesRegex(ValueError, 'do not log me'):
            with timings.measure('fixed_phase'):
                raise ValueError('do not log me')
        snapshot = timings.snapshot()
        self.assertNotIn('do not log me', json.dumps(snapshot))
        self.assertEqual(snapshot['timings']['fixed_phase']['calls'], 1)
        self.assertEqual(snapshot['active'], [])

    def test_diagnostic_output_is_atomic_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            _write_json(path, {'observation_only': True})
            self.assertEqual(json.loads(path.read_text()), {'observation_only': True})
            with self.assertRaises(ValueError):
                _write_json(path, {'oversized': 'x' * (256 * 1024)})
            self.assertEqual(json.loads(path.read_text()), {'observation_only': True})
            self.assertFalse(path.with_suffix('.partial').exists())

    def test_rollback_modes_verify_full_sync_and_keep_real_commit_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('DELETE', 'TRUNCATE', 'PERSIST'):
                with self.subTest(mode=mode):
                    path = Path(directory) / (mode + '.sqlite3')
                    with _rollback_connection(sqlite3.connect, path, mode) as db:
                        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], mode.lower())
                        self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)
                        db.execute('CREATE TABLE replay (cursor INTEGER)')
                        db.execute('INSERT INTO replay VALUES (960)')
                    with self.assertRaises(RuntimeError):
                        with _rollback_connection(sqlite3.connect, path, mode) as db:
                            db.execute('UPDATE replay SET cursor=-1')
                            raise RuntimeError('rollback')
                    db = sqlite3.connect(path)
                    try:
                        self.assertEqual(db.execute('SELECT cursor FROM replay').fetchone()[0], 960)
                        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    finally:
                        db.close()

    def test_unsupported_or_unselected_mode_fails_before_probe_writes(self):
        connect = MagicMock()
        with self.assertRaises(ValueError):
            with _rollback_connection(connect, 'unused', 'WAL'):
                self.fail('WAL must not be used by this comparison')
        connect.assert_not_called()
        db = connect.return_value
        db.execute.return_value.fetchone.return_value = ('delete',)
        with self.assertRaises(RuntimeError):
            with _rollback_connection(connect, 'unused', 'PERSIST'):
                self.fail('Unselected mode must fail closed')
        db.__enter__.assert_not_called()
        db.close.assert_called_once()
        self.assertTrue(all(call.args[0].startswith('PRAGMA ') for call in db.execute.call_args_list))

    def test_journal_timeout_removes_only_controller_owned_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / 'keep.txt'
            sentinel.write_text('keep')
            roots = set()
            def timeout(command, **kwargs):
                root = Path(command[command.index('--journal-root') + 1])
                roots.add(root)
                (root / 'owned.txt').write_text('disposable')
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            with patch('subprocess.run', side_effect=timeout):
                results = _journal_mode_comparison(output, time.monotonic() + 10)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(item['timed_out'] and not item['complete'] for item in results))
            self.assertTrue(roots and all(not root.exists() for root in roots))
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_partial_commit_counts_cannot_be_reported_as_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            def partial(command, **kwargs):
                mode = command[command.index('--journal-child') + 1]
                _write_json(Path(command[2]), {'mode': mode, 'complete': True,
                    'commits_completed': 959, 'rollback_and_reopen_verified': True,
                    'verified_pragmas': {'journal_mode': mode.lower(), 'synchronous': 2},
                    'timings': {'replay.cursor_commit': {'calls': 959}}})
                return subprocess.CompletedProcess(command, 0)
            with patch('subprocess.run', side_effect=partial):
                results = _journal_mode_comparison(Path(directory), time.monotonic() + 10)
            self.assertEqual(len(results), 3)
            self.assertFalse(any(item['complete'] for item in results))
