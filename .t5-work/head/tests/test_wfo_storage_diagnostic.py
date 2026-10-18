"""Diagnostic correctness only; these tests are not a storage-performance gate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('diagnose_wfo_storage', ROOT / 'tools/diagnose_wfo_storage.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class WfoStorageDiagnosticTests(unittest.TestCase):
    def test_pinned_synthetic_streams_reconstruct_exact_bytes(self):
        for name, count in (('smoke', 63), ('large', 574)):
            payloads, metadata = probe.load_stream(name)
            self.assertEqual(len(payloads), count)
            self.assertEqual(sum(len(x.encode('utf-8')) for x in payloads), metadata['payload_bytes'])
            self.assertEqual(hashlib.sha256(''.join(payloads).encode('utf-8')).hexdigest(), metadata['stream_sha256'])

    def test_archive_tampering_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'wfo-storage-manifest.json').write_bytes((probe.FIXTURES / 'wfo-storage-manifest.json').read_bytes())
            (directory / 'wfo-storage-smoke.json.gz').write_bytes(b'not an archive')
            with patch.object(probe, 'FIXTURES', directory), self.assertRaisesRegex(ValueError, 'size/hash'):
                probe.load_stream('smoke')

    def test_both_modes_and_control_preserve_every_commit_export(self):
        payloads = ['{"state_hash":"synthetic","value":' + str(i) + '}' for i in range(3)]
        with tempfile.TemporaryDirectory() as temporary:
            for i, mode in enumerate(probe.MODES):
                report = probe.replay(payloads, Path(temporary) / str(i), mode, measured=i != 4)
                self.assertEqual(report['commits'], 3)
                self.assertEqual(report['exports'], 3)
                self.assertEqual(report['stream_sha256'], probe.digest(''.join(payloads).encode()))
                self.assertEqual(bool(report['phases']), i != 4)
                self.assertEqual(report['synchronous'], 2)
        self.assertEqual(probe.MODES, ('DELETE', 'PERSIST', 'PERSIST', 'DELETE', 'DELETE'))

    def test_export_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, 'replace', side_effect=OSError('synthetic failure')):
                with self.assertRaises(OSError):
                    probe.replay(['{}'], Path(temporary) / 'round', 'DELETE')

    def test_report_write_preserves_existing_sibling_temp_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sibling = directory / 'report.tmp'
            sibling.write_text('unrelated data', encoding='utf-8')
            report = directory / 'report.json'
            probe.write_report(report, {'status': 'INCOMPLETE'})
            self.assertEqual(json.loads(report.read_text()), {'status': 'INCOMPLETE'})
            self.assertEqual(sibling.read_text(), 'unrelated data')
            self.assertEqual(set(directory.iterdir()), {sibling, report})

    def test_report_write_does_not_follow_existing_sibling_temp_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            unrelated = directory / 'unrelated.txt'
            unrelated.write_text('unrelated data', encoding='utf-8')
            sibling = directory / 'report.tmp'
            try:
                sibling.symlink_to(unrelated)
            except (OSError, NotImplementedError):
                self.skipTest('Host does not permit symlink creation')
            report = directory / 'report.json'
            probe.write_report(report, {'status': 'INCOMPLETE'})
            self.assertEqual(json.loads(report.read_text()), {'status': 'INCOMPLETE'})
            self.assertFalse(report.is_symlink())
            self.assertTrue(sibling.is_symlink())
            self.assertEqual(unrelated.read_text(), 'unrelated data')
            self.assertEqual(set(directory.iterdir()), {unrelated, sibling, report})

    def test_report_replace_failure_preserves_prior_report_and_cleans_owned_temp(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report = directory / 'report.json'
            report.write_text('prior evidence', encoding='utf-8')
            with patch.object(probe.os, 'replace', side_effect=OSError('synthetic failure')):
                with self.assertRaises(OSError):
                    probe.write_report(report, {'status': 'INCOMPLETE'})
            self.assertEqual(report.read_text(), 'prior evidence')
            self.assertEqual(list(directory.iterdir()), [report])

    def test_deadline_kills_owned_worker_and_reports_incomplete(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(runtime_root=Path(temporary), storage_root=Path(temporary),
                             library_sha256=None, fixture='smoke', seconds=1, report=Path(temporary) / 'report.json')
            with patch.object(subprocess, 'Popen') as spawn:
                spawn.return_value.wait.side_effect = [subprocess.TimeoutExpired('probe', 1), -9]
                self.assertEqual(probe.supervise(args), 2)
                spawn.return_value.kill.assert_called_once_with()
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertTrue(report['partial_round_counts_unknown'])

    def test_timeout_preserves_completed_rounds(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(runtime_root=Path(temporary), storage_root=Path(temporary),
                             library_sha256=None, fixture='smoke', seconds=1,
                             report=Path(temporary) / 'report.json')
            def started(command, **kwargs):
                partial = Path(command[command.index('--report') + 1])
                probe.write_report(partial, {'status': 'INCOMPLETE', 'rounds': [{'commits': 63}],
                                             'active_round': {'index': 1}})
                from unittest.mock import Mock
                child = Mock()
                child.wait.side_effect = [subprocess.TimeoutExpired('probe', 1), -9]
                return child
            with patch.object(subprocess, 'Popen', side_effect=started):
                self.assertEqual(probe.supervise(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['rounds'], [{'commits': 63}])
            self.assertEqual(report['active_round'], {'index': 1})
            self.assertEqual(report['status'], 'INCOMPLETE')

    def test_stalled_termination_still_reports_incomplete(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(runtime_root=Path(temporary), storage_root=Path(temporary),
                             library_sha256=None, fixture='smoke', seconds=1,
                             report=Path(temporary) / 'report.json')
            with patch.object(subprocess, 'Popen') as spawn:
                spawn.return_value.wait.side_effect = subprocess.TimeoutExpired('probe', 1)
                self.assertEqual(probe.supervise(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertFalse(report['worker_termination_confirmed'])

    def test_runtime_pin_failure_prevents_replay(self):
        from argparse import Namespace
        from types import ModuleType
        import sys
        fake = ModuleType('quantlab.sqlite_runtime')
        def reject(*args, **kwargs):
            raise RuntimeError('pin mismatch')
        fake.verify = reject
        with patch.dict(sys.modules, {'quantlab.sqlite_runtime': fake}):
            with patch.object(probe, 'replay') as replay:
                with self.assertRaisesRegex(RuntimeError, 'pin mismatch'):
                    probe.worker(Namespace(runtime_root=ROOT, library_sha256=None))
                replay.assert_not_called()

    def test_deadline_above_180_rejected(self):
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            arguments = ['probe', '--report', temporary + '/report.json', '--runtime-root', temporary,
                         '--storage-root', temporary, '--seconds', '181']
            with patch.object(sys, 'argv', arguments), self.assertRaises(SystemExit) as caught:
                probe.main()
            self.assertEqual(caught.exception.code, 2)

    def test_worker_failure_cannot_be_complete(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(runtime_root=Path(temporary), storage_root=Path(temporary),
                             library_sha256=None, fixture='smoke', seconds=1, report=Path(temporary) / 'report.json')
            with patch.object(subprocess, 'Popen') as spawn:
                spawn.return_value.wait.return_value = 1
                self.assertEqual(probe.supervise(args), 2)
            self.assertEqual(json.loads(args.report.read_text())['status'], 'ERROR')


class WalObservationTests(unittest.TestCase):
    def test_complete_pinned_smoke_abba_counts_hash_bytes_and_reopen(self):
        payloads, metadata = probe.load_stream('smoke')
        self.assertEqual(probe.WAL_MODES, ('DELETE', 'WAL', 'WAL', 'DELETE'))
        with tempfile.TemporaryDirectory() as temporary:
            for index, mode in enumerate(probe.WAL_MODES):
                result = probe.replay(payloads, Path(temporary) / str(index), mode, wal_observation=True)
                self.assertEqual((result['commits'], result['exports'], result['full_readback_count']), (63, 63, 63))
                self.assertEqual(result['payload_bytes'], metadata['payload_bytes'])
                self.assertEqual(result['stream_sha256'], metadata['stream_sha256'])
                self.assertEqual(result['reopened_integrity'], 'ok')
                self.assertEqual(result['synchronous'], 2)
                self.assertEqual(result['reopened_synchronous'], 2)
                self.assertEqual(result['journal_mode_readback'], mode.lower())
                self.assertEqual(result['wal_autocheckpoint'], 1000)
                self.assertEqual(result['close_count'], 2)
                self.assertGreaterEqual(result['elapsed_seconds'], result['close_seconds'] + result['checkpoint_seconds'])
                if mode == 'WAL':
                    self.assertEqual(result['checkpoint_result'], (0, 0, 0))
                    self.assertGreater(result['wal_peak_observed_bytes'], 0)
                    self.assertGreater(result['pre_checkpoint_bytes']['walk_forward.sqlite3-wal'], 0)
                else:
                    self.assertIsNone(result['checkpoint_result'])
                self.assertEqual(result['retained_bytes'].get('walk_forward.sqlite3-wal', 0), 0)

    def test_upsert_full_smoke_and_predeclared_distinct_comparison_order(self):
        self.assertEqual(probe.WAL_ROUNDS, (
            ('journal_mode', 'DELETE', 'replace'), ('journal_mode', 'WAL', 'replace'),
            ('journal_mode', 'WAL', 'replace'), ('journal_mode', 'DELETE', 'replace'),
            ('sql_operation', 'DELETE', 'replace'), ('sql_operation', 'DELETE', 'upsert'),
            ('sql_operation', 'DELETE', 'upsert'), ('sql_operation', 'DELETE', 'replace')))
        payloads, metadata = probe.load_stream('smoke')
        with tempfile.TemporaryDirectory() as temporary:
            for operation in ('replace', 'upsert'):
                result = probe.replay(payloads, Path(temporary) / operation, 'DELETE',
                                      wal_observation=True, operation=operation)
                self.assertEqual(result['sql_operation'], operation)
                self.assertEqual((result['commits'], result['exports']), (63, 63))
                self.assertEqual(result['payload_bytes'], metadata['payload_bytes'])
                self.assertEqual(result['stream_sha256'], metadata['stream_sha256'])
                self.assertEqual(result['reopened_integrity'], 'ok')
                self.assertGreater(result['pages_reopened']['page_count'], 0)
                self.assertGreaterEqual(result['pages_reopened']['freelist_count'], 0)
            for operation, opt_in in (('unknown', True), ('upsert', False)):
                with self.assertRaises(ValueError):
                    probe.replay(['{}'], Path(temporary) / 'invalid', 'DELETE',
                                 wal_observation=opt_in, operation=operation)

    def test_wal_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                probe.replay(['{}'], Path(temporary) / 'round', 'WAL')

    def test_wal_cli_uses_actual_temp_and_rejects_relocation_or_large(self):
        import sys
        base = ['probe', '--report', 'unused.json', '--runtime-root', '.', '--wal-abba']
        with patch.object(sys, 'argv', base), patch.object(probe, 'supervise_wal', return_value=2) as supervise:
            self.assertEqual(probe.main(), 2)
            args = supervise.call_args.args[0]
            self.assertEqual(args.storage_root, Path(tempfile.gettempdir()).resolve())
            self.assertEqual(args.seconds, 180)
            self.assertEqual(args.fixture, 'smoke')
        with tempfile.TemporaryDirectory() as temporary:
            for extras in (['--fixture', 'large'], ['--storage-root', temporary], ['--seconds', '181']):
                with patch.object(sys, 'argv', base + extras), self.assertRaises(SystemExit) as caught:
                    probe.main()
                self.assertEqual(caught.exception.code, 2)

    def test_wal_runtime_failure_remains_nonzero_and_owned_child_is_cleaned(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(runtime_root=Path(temporary), library_sha256=None,
                             seconds=10, report=Path(temporary) / 'report.json')
            self.assertEqual(probe.supervise_wal(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertEqual(report['acceptance'], 'NOT_ESTABLISHED')
            self.assertEqual(report['mode_order'], [mode for _, mode, _ in probe.WAL_ROUNDS])
            self.assertEqual(report['round_plan'], [
                {'comparison': pair, 'mode': mode, 'sql_operation': operation}
                for pair, mode, operation in probe.WAL_ROUNDS])
            self.assertTrue(report['worker_termination_confirmed'])

    def test_wal_timeout_retains_rounds_and_active_round(self):
        from argparse import Namespace
        original_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(runtime_root=Path(temporary), library_sha256=None,
                             seconds=1, report=Path(temporary) / 'report.json')
            def launch(command, **kwargs):
                import sys
                path = command[command.index('--report') + 1]
                script = ('import sys,time,json; from pathlib import Path; sys.stdin.buffer.read(1); '
                          'Path(sys.argv[1]).write_text(json.dumps({"status":"INCOMPLETE",'
                          '"rounds":[{"commits":63}],"active_round":{"index":1}})); time.sleep(60)')
                return original_popen([sys.executable, '-c', script, path], **kwargs)
            with patch.object(probe.subprocess, 'Popen', side_effect=launch):
                self.assertEqual(probe.supervise_wal(args), 2)
            report = json.loads(args.report.read_text())
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertEqual(report['rounds'], [{'commits': 63}])
            self.assertEqual(report['active_round'], {'index': 1})
            self.assertTrue(report['partial_round_counts_unknown'])
            self.assertTrue(report['worker_termination_confirmed'])


if __name__ == '__main__':
    unittest.main()
