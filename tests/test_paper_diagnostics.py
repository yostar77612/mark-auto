"""Instrumentation must observe real SQLite semantics without weakening gates."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.diagnose_paper_replay import Timings, _instrument_connect, _write_json


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
