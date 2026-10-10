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


if __name__ == '__main__':
    unittest.main()
