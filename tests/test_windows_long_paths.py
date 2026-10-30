"""Real Windows filesystem/SQLite regressions; synthetic data, no account requests."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import CostSpec, Instrument, ValidationError
from quantlab.desktop_runtime import AppPaths, RuntimeSafetyError, WorkspaceLocator, _read_json
from quantlab.research_core.adapters.workspace_backup import BackupManager
from quantlab.paper import PaperBroker, RiskLimits
from quantlab.paper_replay import _require_local_wal_path
from quantlab.runtime_support import atomic_write
from quantlab.walk_forward import read_walk_forward_state, run_walk_forward
from quantlab.windows_paths import canonical_path, native_path, sqlite_uri

import test_walk_forward as wfo_fixture
import test_market_history as history_fixture


@unittest.skipUnless(sys.platform == 'win32', 'Native Windows path and SQLite behavior')
class WindowsLongPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='markauto-long-path-')
        self.base = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self._remove_owned_tree)
        self.deep = self.base
        while len(str(self.deep)) < 400:
            self.deep /= 'SYNTHETIC-only-長路徑-百分比%與#-offline-0123456789'

    @staticmethod
    def _extended(path):
        text = str(path)
        return Path(text if text.startswith('\\\\?\\') else '\\\\?\\' + text)

    def _remove_owned_tree(self):
        # Only the exact TemporaryDirectory created by this test may be removed.
        expected_parent = Path(tempfile.gettempdir()).resolve()
        self.assertEqual(self.base.parent, expected_parent)
        self.assertTrue(self.base.name.startswith('markauto-long-path-'))
        shutil.rmtree(self._extended(self.base))

    def test_workspace_creation_atomic_write_and_bounded_read(self):
        paths = AppPaths(self.deep).ensure()
        output = paths.state / 'synthetic.json'
        atomic_write(output, b'{"synthetic":true}', durable=True)
        self.assertEqual(_read_json(output), {'synthetic': True})
        marker = self._extended(self.deep) / 'workspace-format.json'
        self.assertEqual(json.loads(marker.read_text())['schema_version'], 1)
        self.assertGreater(len(str(self.deep)), 400)

    def test_utf16_length_and_short_path_identity(self):
        self.assertEqual(native_path(self.base), self.base)
        example = Path('C:/') / ('\U0001f4c8' * 119)
        self.assertLess(len(str(example)), 240)
        self.assertTrue(str(native_path(example)).startswith('\\\\?\\'))
        folder = self.base / ('\U0001f4c8' * 65) / ('\U0001f4c9' * 50)
        self.assertGreater(len(str(folder).encode('utf-16-le')) // 2, 260)
        output = folder / 'synthetic.json'
        atomic_write(output, b'{"synthetic":true}')
        self.assertEqual(_read_json(output), {'synthetic': True})

    def test_atomic_write_supports_long_paths_without_app_bootstrap(self):
        output = self.deep / 'standalone.json'
        atomic_write(output, b'{"value":1}', durable=True)
        atomic_write(output, b'{"value":2}', durable=True)
        self.assertEqual(_read_json(output), {'value': 2})
        self.assertEqual(list(self._extended(self.deep).glob('*.tmp')), [])

    def test_pointer_preserves_identity_and_backup_cannot_enter_workspace(self):
        bootstrap = self.base / 'bootstrap'
        AppPaths(bootstrap).ensure()
        locator = WorkspaceLocator(bootstrap)
        selected = locator.configure(self.deep)
        self.assertEqual(selected, self.deep)
        self.assertEqual(_read_json(locator.pointer)['root'], str(self.deep))
        paths = locator.load().ensure()
        self.assertEqual(canonical_path(paths.root), self.deep)
        with self.assertRaisesRegex(RuntimeSafetyError, 'outside workspace'):
            BackupManager(paths)._create(self.deep / 'forbidden.zip')
        self.assertFalse(self._extended(self.deep / 'forbidden.zip').exists())

    def test_uri_modes_and_locks_survive_filename_escaping(self):
        journal = self.deep / '空白 space-百分比%-#hash.sqlite3'
        self._extended(self.deep).mkdir(parents=True)
        with closing(sqlite3.connect(str(self._extended(journal)))) as initial, initial:
            initial.execute('CREATE TABLE evidence(n)')
            initial.execute('INSERT INTO evidence VALUES (1)')
        uri = sqlite_uri(journal)
        with closing(sqlite3.connect(uri + '?mode=ro', uri=True)) as reader:
            self.assertEqual(reader.execute('SELECT n FROM evidence').fetchone(), (1,))
            with self.assertRaises(sqlite3.OperationalError) as caught:
                reader.execute('INSERT INTO evidence VALUES (2)')
            self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_READONLY)
        with closing(sqlite3.connect(uri + '?mode=rw', uri=True, timeout=0)) as first:
            first.execute('BEGIN EXCLUSIVE')
            with closing(sqlite3.connect(str(self._extended(journal)), timeout=0)) as second:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    second.execute('BEGIN EXCLUSIVE')
                self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
        missing = self.deep / 'never-create.sqlite3'
        for mode in ('ro', 'rw'):
            with self.subTest(mode=mode), self.assertRaises(sqlite3.OperationalError):
                sqlite3.connect(sqlite_uri(missing) + '?mode=' + mode, uri=True)
        self.assertFalse(self._extended(missing).exists())

    def test_network_and_device_namespaces_do_not_become_local_paths(self):
        for text in (r'\\server\share\journal.db', r'\\?\UNC\server\share\journal.db', r'\\.\C:\journal.db', r'\\?\GLOBALROOT\Device\journal.db'):
            path = Path(text)
            self.assertEqual(native_path(path), path)
            self.assertEqual(canonical_path(path), path)
            with self.subTest(path=text), patch.object(Path, 'resolve', return_value=path):
                with self.assertRaises(ValidationError):
                    _require_local_wal_path(path)

    def test_history_long_source_and_cache_keep_namespace_and_reload_guards(self):
        from quantlab import market_history as history
        from quantlab.market import MarketValidationError

        source = self.deep / 'SYNTHETIC-ticks.csv'
        cache = self.deep / 'history-cache'
        self._extended(self.deep).mkdir(parents=True)
        self._extended(source).write_bytes(history_fixture.fixture([history_fixture.row()]))
        result = history.import_history(source, cache, sessions=[history_fixture.session()])
        self.assertEqual(history.load_history(cache, result.cache_id), result)
        self.assertEqual(history.list_history(cache)[0].cache_id, result.cache_id)
        # The external source boundary still rejects namespace spellings before I/O.
        with self.assertRaises(MarketValidationError):
            history.import_history(self._extended(source), cache, sessions=[history_fixture.session()])

    def test_paper_writes_read_only_snapshot_and_restart_preserve_safety(self):
        now = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
        journal = self.deep / 'paper.sqlite3'
        options = dict(
            instrument=Instrument('TAIFEX:TMF:202610', expiry='2026-10-21'),
            costs=CostSpec(Decimal('10'), Decimal('.00002'), 0, 'half_up', '2026-01-01', 'synthetic-v1'),
            limits=RiskLimits(5, 3, Decimal('500'), 5),
            risk_sessions=(
                {'open': now - timedelta(minutes=15), 'end': now + timedelta(hours=4), 'trade_date': '2026-10-09', 'source': 'synthetic', 'session': 'day'},
            ),
            margin_schedule=({'effective_from': '2026-01-01', 'margin_per_contract': Decimal('10000'), 'version': 'synthetic'},),
        )
        broker = PaperBroker(journal, **options)
        broker.reconcile({'account_id': 'SYNTHETIC-only', 'cash': '100000', 'positions': {}, 'orders': {}, 'fills': {}})
        before = hashlib.sha256(self._extended(journal).read_bytes()).hexdigest()
        snapshot = PaperBroker.read_snapshot(journal)
        self.assertEqual(snapshot['cash'], '100000')
        self.assertFalse(snapshot['reconciliation_required'])
        self.assertEqual(hashlib.sha256(self._extended(journal).read_bytes()).hexdigest(), before)
        reopened = PaperBroker(journal, **options).snapshot()
        self.assertTrue(reopened['reconciliation_required'])
        self.assertEqual(reopened['orders'], {})
        missing = self.deep / 'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):
            PaperBroker.read_snapshot(missing)
        self.assertFalse(self._extended(missing).exists())

    def test_wfo_long_journal_reload_and_one_time_range_consumption(self):
        # The existing deterministic scorer isolates storage; no model or market claim.
        dataset, plan = wfo_fixture.inputs(ranking={'metric': 'net_pnl', 'minimum': '0', 'min_trades': 1, 'max_drawdown_pct': '0.10'})
        output = self.deep / 'experiment'
        registry = self.deep / 'controls' / 'holdout.sqlite3'
        with patch('quantlab.walk_forward._run_bounded', side_effect=wfo_fixture.fake_worker):
            completed = run_walk_forward(dataset, plan=plan, output_dir=output, holdout_registry_path=registry)
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['summary']['evaluated_oos_folds'], 3)
        loaded = read_walk_forward_state(output)
        self.assertEqual(loaded, completed)
        with patch('quantlab.walk_forward._run_bounded', side_effect=AssertionError('Consumed range must not be evaluated')):
            blocked = run_walk_forward(dataset, plan=plan, output_dir=self.deep / 'second', holdout_registry_path=self._extended(registry))
        self.assertEqual(blocked['status'], 'blocked_previously_consumed_range')
        self.assertEqual(blocked['binding']['registry_identity'], completed['binding']['registry_identity'])
        self.assertEqual(blocked['evaluations'], [])
        self.assertEqual(blocked['final_holdout_status'], 'excluded_not_evaluated')
        journal = self._extended(output / 'walk_forward.sqlite3')
        with closing(sqlite3.connect(str(journal))) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone(), ('wal',))


if __name__ == '__main__':
    unittest.main()
