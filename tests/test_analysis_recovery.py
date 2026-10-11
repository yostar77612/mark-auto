"""Real SQLite/tempdir protocol tests; no production helper or provider transport."""
import copy
from contextlib import closing
import multiprocessing as mp
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from quantlab.desktop_runtime import AppPaths
from quantlab import analysis_recovery as r
from quantlab import research_analysis as a
from tests.test_research_analysis import source, prepare, PROVENANCE


def _hold_operation(root, bootstrap, ready, release):
    paths = AppPaths(Path(root), Path(bootstrap))
    with r.operation_guard(paths, 'ui_import'):
        ready.set()
        release.wait(5)


def _crash_ledger_transaction(database):
    import os
    db = sqlite3.connect(database)
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('PRAGMA cache_size=1')
    db.execute('BEGIN IMMEDIATE')
    # Force real page spill and a hot journal, then die before commit.
    for i in range(100, 160):
        db.execute('INSERT INTO events VALUES (?,?,?)', (i, 'x' * 12000, 'f' * 64))
    os._exit(47)


class RecoveryLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_tmp = tempfile.TemporaryDirectory()
        data, state, folder = source(Path(cls.source_tmp.name))
        packet = prepare(folder, data, state)
        cls.plan = a.make_analysis_plan(packet, model='fixture-model', registration='a' * 32,
            provider_implementation=PROVENANCE, timeout_seconds=30)
        cls.base_request = {'campaign_reference': folder.name,
            'original_dataset': {'kind': 'local_dataset_file', 'path': str(folder / 'original.json')},
            'attempt_ids': [state['attempts'][0]['attempt_id']], 'task': 'critique',
            'model': 'fixture-model', 'registration': 'a' * 32, 'timeout_seconds': 30}

    @classmethod
    def tearDownClass(cls):
        cls.source_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bootstrap = Path(self.tmp.name) / 'bootstrap'
        self.bootstrap.mkdir()
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace', self.bootstrap).ensure()
        self.request = copy.deepcopy(self.base_request)

    def register(self, **changes):
        args = dict(job_id='b' * 32, helper_nonce='c' * 32, approved_plan=self.plan, request=self.request)
        args.update(changes)
        with r.admission(self.paths) as token:
            return r.register_launch(self.paths, **args, admission=token)

    def publish(self, launch, value=0):
        return r._StopPublisher(self.paths, launch, lambda: value).publish()

    def test_connection_setup_failure_closes_original_sqlite_handle(self):
        self.register()
        original_connect = sqlite3.connect
        opened = []
        class SetupFailure(sqlite3.Connection):
            was_closed = False
            def execute(connection, sql, *args):
                if sql == 'PRAGMA busy_timeout=250':
                    raise sqlite3.OperationalError('synthetic configuration failure')
                return super().execute(sql, *args)
            def close(connection):
                connection.was_closed = True
                return super().close()
        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs, factory=SetupFailure)
            opened.append(connection)  # Retain handles so GC cannot conceal a leak.
            return connection
        try:
            with patch.object(r.sqlite3, 'connect', side_effect=connect):
                with self.assertRaises(sqlite3.OperationalError):
                    r._connect(self.paths.controls / r._DATABASE)
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].was_closed)
            with self.assertRaises(sqlite3.ProgrammingError):
                opened[0].execute('SELECT 1')
        finally:
            for connection in opened:
                connection.close()

    def test_corrupt_schema_setup_closes_real_write_connection(self):
        self.register()
        database = self.paths.controls / r._DATABASE
        raw = bytearray(database.read_bytes())
        raw[100] = 255  # Corrupt first B-tree page, retaining original SQLite header.
        database.write_bytes(raw)
        original_connect = sqlite3.connect
        opened = []
        class TrackedConnection(sqlite3.Connection):
            was_closed = False
            def close(connection):
                connection.was_closed = True
                return super().close()
        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs, factory=TrackedConnection)
            opened.append(connection)
            return connection
        try:
            with patch.object(r.sqlite3, 'connect', side_effect=connect):
                with self.assertRaises(sqlite3.DatabaseError):
                    r._connect(database, write=True)
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].was_closed)
            with self.assertRaises(sqlite3.ProgrammingError):
                opened[0].execute('SELECT 1')
        finally:
            for connection in opened:
                connection.close()

    def test_production_ledger_connections_close_without_garbage_collection(self):
        original_connect = sqlite3.connect
        opened = []
        class TrackedConnection(sqlite3.Connection):
            was_closed = False
            def close(connection):
                connection.was_closed = True
                return super().close()
        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs, factory=TrackedConnection)
            opened.append(connection)
            return connection
        try:
            with patch.object(r.sqlite3, 'connect', side_effect=connect):
                launch = self.register()
                self.publish(launch)
                r.inspect_recovery(self.paths)
                r.validate_stop_receipt(self.paths, launch['job_id'])
                with r.admission(self.paths) as token:
                    r.advance_restore_epoch(self.paths, 'd' * 32, admission=token)
            self.assertGreater(len(opened), 5)
            for connection in opened:
                self.assertTrue(connection.was_closed)
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute('SELECT 1')
        finally:
            for connection in opened:
                connection.close()

    def test_legacy_inspection_and_restore_do_not_initialize(self):
        before = sorted(str(p.relative_to(self.bootstrap)) for p in self.bootstrap.rglob('*'))
        self.assertTrue(r.inspect_recovery(self.paths).legacy)
        self.assertEqual(before, sorted(str(p.relative_to(self.bootstrap)) for p in self.bootstrap.rglob('*')))
        with r.admission(self.paths) as token:
            self.assertIsNone(r.advance_restore_epoch(self.paths, 'd' * 32, admission=token))
        self.assertFalse((self.bootstrap / r._SENTINEL).exists())
        self.assertFalse((self.paths.controls / r._DATABASE).exists())

    def test_prejournal_receipt_releases_conflicts_without_journal_repair(self):
        launch = self.register()
        disposition = r.inspect_recovery(self.paths)
        self.assertEqual(disposition.status, 'unresolved')
        self.assertEqual(disposition.workspace_unresolved, (launch,))
        for operation in r.SOURCE_WRITERS | r.ANALYSIS_STARTS | r.WORKSPACE_MUTATIONS:
            with self.subTest(operation=operation), self.assertRaises(r.RecoveryError):
                r.require_operation(self.paths, operation)
        for operation in ('ui_backtest', 'ui_compare', 'ui_analysis_read'):
            r.require_operation(self.paths, operation)
        self.assertFalse((self.paths.state / 'analyses').exists())
        self.publish(launch)
        self.assertEqual(r.validate_stop_receipt(self.paths, launch['job_id']), launch)
        self.assertEqual(r.inspect_recovery(self.paths).status, 'stopped')
        self.assertEqual(r.inspect_recovery(self.paths).workspace_stopped, (launch,))
        r.require_operation(self.paths, 'ui_backup_create')
        with self.assertRaises(r.RecoveryError):
            self.register(job_id='e' * 32)  # Stop evidence never recycles a request.

    def test_helper_generation_and_gate_cannot_replay(self):
        launch = self.register()
        self.assertEqual(r.read_launch(self.paths, launch['job_id'], expected=launch, for_admission=True), launch)
        wrong = {**launch, 'helper_nonce': 'e' * 32}
        with self.assertRaises(r.RecoveryError):
            r.read_launch(self.paths, launch['job_id'], expected=wrong)
        with self.assertRaises(r.RecoveryError):
            self.publish(wrong)
        self.publish(launch)
        with self.assertRaises(r.RecoveryError):
            r.read_launch(self.paths, launch['job_id'], for_admission=True)

    def test_only_exact_integer_zero_observation_publishes(self):
        launch = self.register()
        for value in (False, True, None, '0', 1, -1, 0.0):
            with self.subTest(value=value), self.assertRaises(r.RecoveryError):
                self.publish(launch, value)
            with self.assertRaises(r.RecoveryError):
                r.validate_stop_receipt(self.paths, launch['job_id'])
        with self.assertRaises(OSError):
            r._StopPublisher(self.paths, launch, lambda: (_ for _ in ()).throw(OSError('query failed'))).publish()
        self.assertTrue(r.inspect_recovery(self.paths).unresolved)

    def test_publication_failure_rolls_back_and_lost_ack_is_idempotent(self):
        launch = self.register()
        original = r._append
        def failed_append(db, state, events):
            original(db, state, events)
            raise sqlite3.OperationalError('simulated write failure before commit')
        with patch.object(r, '_append', side_effect=failed_append), self.assertRaises(sqlite3.OperationalError):
            self.publish(launch)
        self.assertTrue(r.inspect_recovery(self.paths).unresolved)
        receipt = self.publish(launch)  # Pretend the caller never received this ACK.
        count = r._load(self.paths)['length']
        self.assertEqual(self.publish(launch), receipt)
        self.assertEqual(r._load(self.paths)['length'], count)
        r.validate_stop_receipt(self.paths, launch['job_id'])

    def test_original_journal_bindings_remain_exact(self):
        launch = self.register()
        self.publish(launch)
        record = {'plan': self.plan, 'provider_descriptor': a.expected_provider_descriptor(self.plan)}
        r.validate_stop_receipt(self.paths, launch['job_id'], record=record)
        for mutate in (lambda x: x['plan']['binding'].update(timeout_seconds=31),
                       lambda x: x['provider_descriptor'].update(model='different')):
            broken = copy.deepcopy(record)
            mutate(broken)
            with self.assertRaises(ValueError):
                r.validate_stop_receipt(self.paths, launch['job_id'], record=broken)
        with self.assertRaises(r.RecoveryError):
            r.validate_stop_receipt(self.paths, 'f' * 32, record=record)

    def test_restore_epoch_monotonic_idempotent_and_old_receipt_rejected(self):
        launch = self.register()
        with r.admission(self.paths) as token:
            with self.assertRaises(r.RecoveryError):
                r.advance_restore_epoch(self.paths, 'd' * 32, admission=token)
        self.publish(launch)
        with r.admission(self.paths) as token:
            self.assertEqual(r.advance_restore_epoch(self.paths, 'd' * 32, admission=token), 1)
            self.assertEqual(r.advance_restore_epoch(self.paths, 'd' * 32, admission=token), 1)
            self.assertEqual(r.advance_restore_epoch(self.paths, 'e' * 32, admission=token), 2)
        with self.assertRaises(r.RecoveryError):
            r.validate_stop_receipt(self.paths, launch['job_id'])
        self.assertFalse(r.inspect_recovery(self.paths).unresolved)
        self.assertEqual(r.inspect_recovery(self.paths).workspace_stopped, ())
        # Positive historical stop still means no live writer, not repair authority.

    def test_copied_workspace_and_original_bootstrap_are_not_adopted(self):
        launch = self.register()
        self.publish(launch)
        copy_root = Path(self.tmp.name) / 'copy'
        shutil.copytree(self.paths.root, copy_root)
        copied = AppPaths(copy_root, self.bootstrap)
        with self.assertRaises(r.RecoveryError):
            r.validate_stop_receipt(copied, launch['job_id'])
        copy_bootstrap = Path(self.tmp.name) / 'other-install'
        shutil.copytree(self.bootstrap, copy_bootstrap)
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(AppPaths(self.paths.root, copy_bootstrap))
        moved = Path(self.tmp.name) / 'old-root'
        self.paths.root.rename(moved)
        self.paths.root.mkdir()
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)

    def test_other_workspace_keeps_non_ai_reads_but_source_writes_stay_blocked(self):
        self.register()
        other = AppPaths(Path(self.tmp.name) / 'other-workspace', self.bootstrap).ensure()
        result = r.inspect_recovery(other)
        self.assertTrue(result.unresolved)
        self.assertFalse(result.workspace_unresolved)
        for operation in ('ui_backtest', 'ui_compare', 'ui_analysis_read', 'ui_backup_create'):
            r.require_operation(other, operation)
        for operation in r.SOURCE_WRITERS | r.ANALYSIS_STARTS:
            with self.assertRaises(r.RecoveryError):
                r.require_operation(other, operation)

    def test_missing_controls_never_become_legacy(self):
        self.register()
        database = self.paths.controls / r._DATABASE
        original = database.read_bytes()
        database.unlink()
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        database.write_bytes(original)
        (self.bootstrap / r._SENTINEL).unlink()
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)

    def test_unknown_controls_preserve_safe_non_ai_operations(self):
        self.register()
        (self.paths.controls / r._DATABASE).unlink()
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        for operation in r.SAFE_OPERATIONS:
            self.assertIsNone(r.require_operation(self.paths, operation))
        for operation in r.SOURCE_WRITERS | r.ANALYSIS_STARTS | r.WORKSPACE_MUTATIONS:
            with self.assertRaises(r.RecoveryError):
                r.require_operation(self.paths, operation)

    def test_initialization_failure_leaves_fail_closed_marker(self):
        with patch.object(r, '_append', side_effect=sqlite3.OperationalError('failure')), self.assertRaises(sqlite3.Error):
            self.register()
        self.assertTrue((self.bootstrap / r._SENTINEL).exists())
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)

    def test_tampered_chain_schema_version_and_records_rejected(self):
        self.register()
        database = self.paths.controls / r._DATABASE
        original = database.read_bytes()
        mutations = ["PRAGMA user_version=99", "CREATE TABLE extra(value TEXT)",
            "UPDATE events SET digest='" + '0' * 64 + "' WHERE sequence=3",
            "UPDATE events SET payload='{}' WHERE sequence=3"]
        for statement in mutations:
            with self.subTest(statement=statement):
                database.write_bytes(original)
                with closing(sqlite3.connect(database)) as db, db:
                    db.execute('DROP TRIGGER no_update')
                    db.execute(statement)
                    db.execute(r._SCHEMA['no_update'])
                with self.assertRaises(r.RecoveryError):
                    r.inspect_recovery(self.paths)
        database.write_bytes(b'not a database')
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)

    def test_real_hot_journal_requires_explicit_original_admission_recovery(self):
        launch = self.register()
        database = self.paths.controls / r._DATABASE
        child = mp.get_context('spawn').Process(target=_crash_ledger_transaction, args=(str(database),))
        child.start()
        try:
            child.join(10)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode, 47)
        finally:
            if child.is_alive():
                child.kill()
                child.join(2)
            child.close()
        journal = Path(str(database) + '-journal')
        self.assertTrue(journal.exists())
        before = {str(p): p.read_bytes() for p in self.bootstrap.rglob('*') if p.is_file()}
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.bootstrap.rglob('*') if p.is_file()})
        with self.assertRaises(r.RecoveryError):
            r.recover_control_journal(self.paths, admission=None)
        with r.admission(self.paths) as token:
            self.assertTrue(r.recover_control_journal(self.paths, admission=token))
            self.assertFalse(r.recover_control_journal(self.paths, admission=token))
        self.assertFalse(journal.exists())
        self.assertEqual(r.read_launch(self.paths, launch['job_id']), launch)
        self.assertTrue(r.inspect_recovery(self.paths).unresolved)
        self.publish(launch)
        r.validate_stop_receipt(self.paths, launch['job_id'])

    def test_duplicate_analysis_or_helper_generation_rejected_on_full_read(self):
        launch = self.register()
        self.publish(launch)
        database = self.paths.controls / r._DATABASE
        original = database.read_bytes()
        for key in ('analysis_id', 'helper_nonce'):
            database.write_bytes(original)
            duplicate = {**launch, 'job_id': 'd' * 32, 'helper_nonce': 'e' * 32,
                'analysis_id': 'f' * 64, 'ledger_basename': 'chatgpt-analysis-' + 'f' * 64 + '.sqlite3'}
            duplicate[key] = launch[key]
            duplicate['ledger_basename'] = 'chatgpt-analysis-' + duplicate['analysis_id'] + '.sqlite3'
            state = r._load(self.paths)
            with closing(sqlite3.connect(database)) as db, db:
                r._append(db, state, [('launch', duplicate)])
            with self.assertRaises(r.RecoveryError):
                r.inspect_recovery(self.paths)

    def test_capacity_reserves_final_receipt_and_rejects_competing_epoch(self):
        first = self.register()
        self.publish(first)
        original_paths = self.paths
        self.paths = AppPaths(Path(self.tmp.name) / 'second-workspace', self.bootstrap).ensure()
        plan = a.make_analysis_plan(self.plan['binding']['packet'], model='other-model',
            registration='a' * 32, provider_implementation=PROVENANCE, timeout_seconds=30)
        with patch.object(r, 'MAX_ROWS', 7):
            second = self.register(job_id='e' * 32, helper_nonce='f' * 32,
                approved_plan=plan, request={**self.request, 'model': 'other-model'})
            self.assertEqual(r._load(self.paths)['length'], 6)
            with r.admission(original_paths) as token:
                with self.assertRaises(r.RecoveryError):
                    r.advance_restore_epoch(original_paths, 'd' * 32, admission=token)
            self.assertEqual(r._load(self.paths)['length'], 6)
            state = r._load(self.paths)
            with closing(sqlite3.connect(self.paths.controls / r._DATABASE)) as db, db:
                with self.assertRaisesRegex(r.RecoveryError, 'receipt capacity'):
                    r._append(db, state, [('epoch', {'root': first['workspace']['root'],
                        'transaction_id': 'd' * 32, 'epoch': 1})])
            self.publish(second)
            self.assertEqual(r._load(self.paths)['length'], 7)
            r.validate_stop_receipt(self.paths, second['job_id'])
        self.paths = original_paths

    def test_capacity_registration_fails_before_consuming_reserved_space(self):
        with patch.object(r, 'MAX_ROWS', 3), self.assertRaises(r.RecoveryError):
            self.register()
        self.assertFalse(r.inspect_recovery(self.paths).unresolved)
        with patch.object(r, 'MAX_DATABASE', 64 * 1024), self.assertRaises(r.RecoveryError):
            self.register()
        self.assertFalse(r.inspect_recovery(self.paths).unresolved)
        self.assertEqual(r._load(self.paths)['length'], 1)
        launch = self.register()
        self.publish(launch)

    def test_strict_marker_and_event_bounds_and_test_receipt_kind(self):
        import json
        launch = self.register()
        marker = self.bootstrap / r._SENTINEL
        marker_raw = marker.read_bytes()
        for raw in (b'{"version":1,"version":1}', b'\xff', b'[' * 1200 + b']' * 1200,
                    b'x' * (r.MAX_RECORD + 1)):
            marker.write_bytes(raw)
            with self.assertRaises(r.RecoveryError):
                r.inspect_recovery(self.paths)
        marker.write_bytes(marker_raw)
        database = self.paths.controls / r._DATABASE
        original = database.read_bytes()
        for change in (lambda v: v.update(extra='untrusted'),
                       lambda v: v.update(epoch=True),
                       lambda v: v.update(helper_protocol='TEST_ONLY'),
                       lambda v: v.update(request_bytes=True)):
            database.write_bytes(original)
            with closing(sqlite3.connect(database)) as db, db:
                raw = db.execute('SELECT payload FROM events WHERE sequence=3').fetchone()[0]
                event = json.loads(raw)
                change(event['value'])
                db.execute('DROP TRIGGER no_update')
                db.execute('UPDATE events SET payload=?,digest=? WHERE sequence=3',
                           (r._json(event), r._hash(event)))
                db.execute(r._SCHEMA['no_update'])
            with self.assertRaises(r.RecoveryError):
                r.inspect_recovery(self.paths)
        database.write_bytes(original)
        state = r._load(self.paths)
        with r.admission(self.paths), closing(sqlite3.connect(database)) as db, db:
            r._append(db, state, [('receipt', {'protocol': 'TEST_ONLY', 'job_id': launch['job_id'],
                'launch_hash': r._hash(launch), 'active_processes': 0})])
        with self.assertRaises(r.RecoveryError):
            r.validate_stop_receipt(self.paths, launch['job_id'])

    def test_inspection_is_read_only_and_wal_header_never_adopted(self):
        self.register()
        before = {str(p): p.read_bytes() for p in self.bootstrap.rglob('*') if p.is_file()}
        for _ in range(3):
            r.inspect_recovery(self.paths)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.bootstrap.rglob('*') if p.is_file()})
        database = self.paths.controls / r._DATABASE
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
        before = {str(p): p.read_bytes() for p in self.bootstrap.rglob('*') if p.is_file()}
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.bootstrap.rglob('*') if p.is_file()})

    def test_links_hardlinks_and_oversize_are_rejected(self):
        self.register()
        database = self.paths.controls / r._DATABASE
        backup = database.with_suffix('.saved')
        database.rename(backup)
        database.symlink_to(backup)
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        database.unlink()
        import os
        os.link(backup, database)
        with self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)
        database.unlink()
        backup.rename(database)
        with patch.object(r, 'MAX_DATABASE', 1), self.assertRaises(r.RecoveryError):
            r.inspect_recovery(self.paths)

    def test_registration_requires_active_original_context_and_exact_source(self):
        with r.admission(self.paths) as token:
            pass
        with self.assertRaises(r.RecoveryError):
            r.register_launch(self.paths, job_id='b' * 32, helper_nonce='c' * 32,
                approved_plan=self.plan, request=self.request, admission=token)
        for changes in ({'registration': 'f' * 32}, {'campaign_reference': 'f' * 64}, {'attempt_ids': ['f' * 64]}):
            with self.assertRaises(ValueError):
                self.register(request={**self.request, **changes})
        self.assertTrue(r.inspect_recovery(self.paths).legacy)

    def test_reentrant_operation_guard_and_cross_process_serialization(self):
        with r.operation_guard(self.paths, 'ui_import') as first:
            with r.operation_guard(self.paths, 'ui_import') as second:
                self.assertIs(first, second)
        context = mp.get_context('spawn')
        ready, release = context.Event(), context.Event()
        child = context.Process(target=_hold_operation,
            args=(str(self.paths.root), str(self.bootstrap), ready, release))
        child.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.assertRaises(r.RecoveryError):
                self.register()
            self.assertTrue(r.inspect_recovery(self.paths).legacy)
        finally:
            release.set()
            child.join(5)
            if child.is_alive():
                child.kill()
                child.join(2)
        self.assertEqual(child.exitcode, 0)
        child.close()
        self.register()

    def test_concurrent_registration_admits_at_most_one(self):
        barrier = threading.Barrier(2)
        successes, failures = [], []
        def register(index):
            barrier.wait()
            try:
                successes.append(self.register(job_id=str(index) * 32))
            except r.RecoveryError as exc:
                failures.append(exc)
        threads = [threading.Thread(target=register, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(r.inspect_recovery(self.paths).launches), 1)


if __name__ == '__main__':
    unittest.main()
