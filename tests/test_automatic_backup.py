import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from quantlab.automatic_backup import AutomaticBackup, MAX_ARCHIVES
from quantlab.desktop_runtime import AppPaths, BackupManager, RuntimeSafetyError


class AutomaticBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.paths = AppPaths(self.base/'workspace', self.base/'bootstrap').ensure()
        self.now = 20000 * 86400
        self.auto = AutomaticBackup(self.paths, clock=lambda: self.now)
        self.directory = self.base/'archives'

    def enable(self):
        self.auto.configure(enabled=True, directory=str(self.directory))

    def test_default_disabled_and_busy_does_not_consume_day(self):
        self.assertIsNone(self.auto.claim_due(quiescent=True))
        self.assertFalse(self.auto.path.exists())
        self.enable()
        original = self.auto.path.read_bytes()
        for busy in (False, None, 1):
            self.assertIsNone(self.auto.claim_due(quiescent=busy))
        self.assertEqual(original, self.auto.path.read_bytes())
        self.assertIsNotNone(self.auto.claim_due(quiescent=True))

    def test_daily_restart_rollback_and_toggle_dedup(self):
        self.enable()
        payload = self.auto.claim_due(quiescent=True)
        self.assertIsNotNone(payload)
        for delta in (0, -86400, 86399):
            restarted = AutomaticBackup(self.paths, clock=lambda: self.now + delta)
            self.assertIsNone(restarted.claim_due(quiescent=True))
        self.auto.configure(enabled=False, directory='')
        self.enable()
        self.assertIsNone(self.auto.claim_due(quiescent=True))
        self.now += 86400
        self.assertNotEqual(payload, self.auto.claim_due(quiescent=True))

    def test_real_guarded_archive_restores_raw_bytes_excludes_controls(self):
        self.paths.require_replay_wal()
        raw = b'\x00\xff\r\n WAL raw bytes'
        (self.paths.state/'replay.sqlite3-wal').write_bytes(raw)
        for folder in (self.paths.credentials, self.paths.cache, self.paths.controls, self.paths.root/'models'):
            folder.mkdir(exist_ok=True)
            (folder/'excluded').write_bytes(b'private')
        self.enable()
        archive = self.auto.claim_due(quiescent=True)['path']
        BackupManager(self.paths).create(archive)
        self.auto.complete(archive=archive, status='success')
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {'state/replay.sqlite3-wal', 'manifest.json'})
            self.assertEqual(json.loads(z.read('manifest.json'))['schema_version'], 2)
            self.assertEqual(z.read('state/replay.sqlite3-wal'), raw)
        (self.paths.controls/'excluded').write_bytes(b'new irreversible budget')
        (self.paths.state/'replay.sqlite3-wal').write_bytes(b'changed')
        BackupManager(self.paths).restore(archive)
        self.assertEqual((self.paths.state/'replay.sqlite3-wal').read_bytes(), raw)
        self.assertEqual((self.paths.controls/'excluded').read_bytes(), b'new irreversible budget')
        self.assertIsNone(AutomaticBackup(self.paths, clock=lambda:self.now).claim_due(quiescent=True))

    def test_unsafe_destinations_do_not_write_config(self):
        for path in (self.paths.root, self.paths.state/'nested', self.paths.bootstrap/'nested', Path('relative')):
            with self.subTest(path=path), self.assertRaises(RuntimeSafetyError):
                self.auto.configure(enabled=True, directory=str(path))
            self.assertFalse(self.auto.path.exists())
        link = self.base/'linked'; link.symlink_to(self.paths.root, target_is_directory=True)
        with self.assertRaises(RuntimeSafetyError):
            self.auto.configure(enabled=True, directory=str(link/'nested'))

    def test_malformed_settings_preserved(self):
        self.enable()
        valid = self.auto.load()
        for key, wrong in [('enabled',1), ('schema_version',True), ('last_attempt_day',True), ('last_attempt_day',-1), ('directory',[]), ('last_status','unknown'), ('last_archive',{})]:
            bad = dict(valid); bad[key] = wrong
            raw = json.dumps(bad).encode(); self.auto.path.write_bytes(raw)
            with self.subTest(key=key), self.assertRaises(RuntimeSafetyError):
                self.auto.claim_due(quiescent=True)
            self.assertEqual(raw, self.auto.path.read_bytes())

    def test_failure_cancel_and_failed_write_are_bounded(self):
        self.enable()
        for status in ('cancelled','error'):
            archive = self.auto.claim_due(quiescent=True)['path']
            self.auto.complete(archive=archive, status=status)
            self.assertIsNone(self.auto.claim_due(quiescent=True))
            self.now += 86400
        before = self.auto.path.read_bytes()
        with patch('quantlab.automatic_backup.atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.auto.claim_due(quiescent=True)
        self.assertEqual(before, self.auto.path.read_bytes())
        self.assertFalse(self.directory.exists())

    def test_limits_preserve_unknown_files_and_do_not_consume_attempt(self):
        self.enable(); self.directory.mkdir()
        for n in range(MAX_ARCHIVES):
            (self.directory/f'markauto-{self.auto.workspace_id[:16]}-{n}-unknown.zip').write_bytes(b'unrecognized')
        before = self.auto.path.read_bytes()
        with self.assertRaisesRegex(RuntimeSafetyError, 'storage limit'):
            self.auto.claim_due(quiescent=True)
        self.assertEqual(before, self.auto.path.read_bytes())
        self.assertEqual(len(list(self.directory.iterdir())), MAX_ARCHIVES)
        self.auto.configure(enabled=True, directory=str(self.base/'other'))
        with patch('quantlab.automatic_backup.shutil.disk_usage') as usage:
            usage.return_value.free = 1
            with self.assertRaisesRegex(RuntimeSafetyError, 'free space'):
                self.auto.claim_due(quiescent=True)
        self.assertIsNone(self.auto.load()['last_attempt_day'])

    def test_byte_cap_and_orphan_temporaries_preserved(self):
        self.enable(); self.directory.mkdir()
        orphan = self.directory/'orphan.zip.tmp'
        with orphan.open('wb') as stream: stream.truncate(2 * 1024 * 1024 * 1024)
        with self.assertRaisesRegex(RuntimeSafetyError, 'storage limit'):
            self.auto.claim_due(quiescent=True)
        self.assertEqual(orphan.stat().st_size, 2 * 1024 * 1024 * 1024)
        self.assertIsNone(self.auto.load()['last_attempt_day'])

    def test_real_archive_write_failure_leaves_no_success_or_temp(self):
        self.enable()
        archive = self.auto.claim_due(quiescent=True)['path']
        with patch('quantlab.desktop_runtime.os.replace', side_effect=OSError('failed archive write')):
            with self.assertRaises(OSError): BackupManager(self.paths).create(archive)
        self.auto.complete(archive=archive, status='error')
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertIsNone(self.auto.claim_due(quiescent=True))

    def test_credential_and_control_hardlinks_never_enter_archive(self):
        self.enable()
        for directory in (self.paths.credentials, self.paths.controls):
            with self.subTest(directory=directory):
                source = directory/'sensitive'
                source.write_bytes(b'private credential or irreversible budget')
                link = self.paths.state/'innocent-name'
                os.link(source, link)
                try:
                    archive = self.base/'unsafe.zip'
                    with self.assertRaisesRegex(RuntimeSafetyError, 'Hard-linked'):
                        BackupManager(self.paths).create(archive)
                    self.assertFalse(archive.exists())
                    self.assertEqual(source.read_bytes(), b'private credential or irreversible budget')
                finally: link.unlink()

    def test_config_hardlink_and_special_file_are_rejected(self):
        self.enable()
        raw = self.auto.path.read_bytes()
        source = self.paths.controls/'sentinel'; source.write_bytes(raw)
        self.auto.path.unlink(); os.link(source, self.auto.path)
        with self.assertRaisesRegex(RuntimeSafetyError, 'Hard-linked'):
            self.auto.configure(enabled=False, directory='')
        self.assertEqual(source.read_bytes(), raw)
        self.auto.path.unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.auto.path)
            with self.assertRaisesRegex(RuntimeSafetyError, 'regular file'):
                self.auto.load()

    def test_managed_hardlink_and_success_symlink_are_rejected(self):
        self.enable(); self.directory.mkdir()
        target = self.base/'target'; target.write_bytes(b'keep')
        link = self.directory/f'markauto-{self.auto.workspace_id[:16]}-linked.zip'
        os.link(target, link)
        with self.assertRaisesRegex(RuntimeSafetyError, 'unsafe matching'):
            self.auto.claim_due(quiescent=True)
        self.assertIsNone(self.auto.load()['last_attempt_day'])
        link.unlink()
        archive = Path(self.auto.claim_due(quiescent=True)['path'])
        archive.symlink_to(target)
        with self.assertRaises(RuntimeSafetyError):
            self.auto.complete(archive=archive, status='success')
        self.assertEqual(self.auto.load()['last_status'], 'attempted')
        self.assertEqual(target.read_bytes(), b'keep')
        archive.unlink(); os.link(target, archive)
        with self.assertRaisesRegex(RuntimeSafetyError, 'Hard-linked'):
            self.auto.complete(archive=archive, status='success')

    def test_unavailable_old_destination_can_be_disabled_or_replaced(self):
        self.enable()
        self.auto.claim_due(quiescent=True)
        watermark = self.auto.load()['last_attempt_day']
        replacement = self.base/'replacement'
        original_check = self.auto.destination_directory
        def check(path):
            if path == str(self.directory): raise RuntimeSafetyError('old drive unavailable')
            return original_check(path)
        with patch.object(self.auto, 'destination_directory', side_effect=check) as checked:
            self.auto.configure(enabled=False, directory=str(self.directory))
            checked.assert_not_called()
        self.assertEqual(self.auto.load()['last_attempt_day'], watermark)
        self.enable()
        with patch.object(self.auto, 'destination_directory', side_effect=check) as checked:
            self.auto.configure(enabled=True, directory=str(replacement))
            checked.assert_called_once_with(str(replacement))
        self.assertEqual(self.auto.load()['directory'], str(replacement))
        self.assertEqual(self.auto.load()['last_attempt_day'], watermark)
        self.assertIsNone(self.auto.claim_due(quiescent=True))

    def test_network_and_device_destinations_rejected_before_io(self):
        for name in ('//server/share', r'\\server\share', r'\\?\C:\backups', r'\\.\C:\backups'):
            with self.subTest(name=name), patch.object(self.auto, '_regular_ancestors') as check:
                with self.assertRaisesRegex(RuntimeSafetyError, 'local directory'):
                    self.auto.destination_directory(name)
                check.assert_not_called()

    def test_invalid_clock_and_stale_result_fail_closed(self):
        self.enable()
        for now in (float('nan'), float('inf'), -1, True):
            self.now = now
            with self.assertRaises(RuntimeSafetyError): self.auto.claim_due(quiescent=True)
        with self.assertRaises(RuntimeSafetyError):
            self.auto.complete(archive='unknown.zip', status='success')


if __name__ == '__main__': unittest.main()
