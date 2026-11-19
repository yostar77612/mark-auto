"""OPT-1 P4: open_sqlite is the former inline `sqlite_uri(path) + '?mode=…'` open, call for call."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from quantlab.shared.sqlite_open import open_sqlite
from quantlab.windows_paths import sqlite_uri


def _inline(path, mode, timeout):
    """The pre-OPT-1 call shape at every migrated site."""
    return sqlite3.connect(sqlite_uri(path) + '?mode=' + mode, uri=True, timeout=timeout)


class OpenSqliteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sqlite-open-')
        self.addCleanup(self.temporary.cleanup)
        # '#' and '%' must stay filename data inside the URI.
        self.root = Path(self.temporary.name) / 'SYNTHETIC #1 100% offline'
        self.root.mkdir()
        self.journal = self.root / 'journal.sqlite3'
        with closing(sqlite3.connect(self.journal)) as db, db:
            db.execute('CREATE TABLE evidence(n)')
            db.execute('INSERT INTO evidence VALUES (1)')

    def test_call_shape_is_identical_for_every_mode_and_timeout(self):
        for mode in ('ro', 'rw', 'rwc'):
            for timeout in (0, 1, 5.0, 30):
                calls = []
                with patch('sqlite3.connect', side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
                    _inline(self.journal, mode, timeout)
                    open_sqlite(self.journal, mode=mode, timeout=timeout)
                with self.subTest(mode=mode, timeout=timeout):
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(calls[0], calls[1])
                    self.assertEqual(calls[1], ((sqlite_uri(self.journal) + '?mode=' + mode,), {'uri': True, 'timeout': timeout}))

    def test_read_only_reads_and_refuses_writes(self):
        for opener in (lambda: _inline(self.journal, 'ro', 1), lambda: open_sqlite(self.journal, mode='ro', timeout=1)):
            with closing(opener()) as db:
                self.assertEqual(db.execute('SELECT n FROM evidence').fetchone(), (1,))
                self.assertEqual(db.isolation_level, '')
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    db.execute('INSERT INTO evidence VALUES (2)')
                self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_READONLY)

    def test_missing_file_fails_the_same_way_and_is_not_created(self):
        missing = self.root / 'never-create.sqlite3'
        for mode in ('ro', 'rw'):
            errors = []
            for opener in (lambda: _inline(missing, mode, 0), lambda: open_sqlite(missing, mode=mode, timeout=0)):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    opener()
                errors.append((type(caught.exception), str(caught.exception), caught.exception.sqlite_errorcode))
            with self.subTest(mode=mode):
                self.assertEqual(errors[0], errors[1])
                self.assertFalse(missing.exists())

    def test_rwc_creates_and_rw_writes(self):
        created = self.root / 'created.sqlite3'
        with closing(open_sqlite(created, mode='rwc', timeout=0)) as db, db:
            db.execute('CREATE TABLE t(n)')
        self.assertTrue(created.is_file())
        with closing(open_sqlite(created, mode='rw', timeout=0)) as db, db:
            db.execute('INSERT INTO t VALUES (7)')
        with closing(_inline(created, 'ro', 0)) as db:
            self.assertEqual(db.execute('SELECT n FROM t').fetchall(), [(7,)])


if __name__ == '__main__':
    unittest.main()
