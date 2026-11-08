import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from tests.native_capabilities import symlinks_available, SYMLINK_REASON
from unittest.mock import Mock, patch
import zipfile

from quantlab.automatic_backup import AutomaticBackup, MAX_ARCHIVES
from quantlab.research_core.adapters.workspace_store import AppPaths
from quantlab.desktop_runtime import RuntimeSafetyError
from quantlab.research_core.adapters.workspace_backup import BackupManager


class AutomaticBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.paths = AppPaths(self.base / 'workspace', self.base / 'bootstrap').ensure()
        self.now = 20000 * 86400
        self.auto = AutomaticBackup(self.paths, clock=lambda: self.now)
        self.directory = self.base / 'archives'

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
        (self.paths.state / 'replay.sqlite3-wal').write_bytes(raw)
        for folder in (self.paths.credentials, self.paths.cache, self.paths.controls, self.paths.root / 'models'):
            folder.mkdir(exist_ok=True)
            (folder / 'excluded').write_bytes(b'private')
        self.enable()
        archive = self.auto.claim_due(quiescent=True)['path']
        BackupManager(self.paths).create(archive)
        self.auto.complete(archive=archive, status='success')
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {'state/replay.sqlite3-wal', 'manifest.json'})
            self.assertEqual(json.loads(z.read('manifest.json'))['schema_version'], 2)
            self.assertEqual(z.read('state/replay.sqlite3-wal'), raw)
        (self.paths.controls / 'excluded').write_bytes(b'new irreversible budget')
        (self.paths.state / 'replay.sqlite3-wal').write_bytes(b'changed')
        BackupManager(self.paths).restore(archive)
        self.assertEqual((self.paths.state / 'replay.sqlite3-wal').read_bytes(), raw)
        self.assertEqual((self.paths.controls / 'excluded').read_bytes(), b'new irreversible budget')
        self.assertIsNone(AutomaticBackup(self.paths, clock=lambda: self.now).claim_due(quiescent=True))

    def test_unsafe_destinations_do_not_write_config(self):
        for path in (self.paths.root, self.paths.state / 'nested', self.paths.bootstrap / 'nested', Path('relative')):
            with self.subTest(path=path), self.assertRaises(RuntimeSafetyError):
                self.auto.configure(enabled=True, directory=str(path))
            self.assertFalse(self.auto.path.exists())

    @unittest.skipUnless(symlinks_available(), SYMLINK_REASON)
    def test_symlink_destination_does_not_write_config(self):
        link = self.base / 'linked'
        link.symlink_to(self.paths.root, target_is_directory=True)
        with self.assertRaises(RuntimeSafetyError):
            self.auto.configure(enabled=True, directory=str(link / 'nested'))
        self.assertFalse(self.auto.path.exists())

    def test_malformed_settings_preserved(self):
        self.enable()
        valid = self.auto.load()
        for key, wrong in [
            ('enabled', 1),
            ('schema_version', True),
            ('last_attempt_day', True),
            ('last_attempt_day', -1),
            ('directory', []),
            ('last_status', 'unknown'),
            ('last_archive', {}),
        ]:
            bad = dict(valid)
            bad[key] = wrong
            raw = json.dumps(bad).encode()
            self.auto.path.write_bytes(raw)
            with self.subTest(key=key), self.assertRaises(RuntimeSafetyError):
                self.auto.claim_due(quiescent=True)
            self.assertEqual(raw, self.auto.path.read_bytes())

    def test_failure_cancel_and_failed_write_are_bounded(self):
        self.enable()
        for status in ('cancelled', 'error'):
            archive = self.auto.claim_due(quiescent=True)['path']
            self.auto.complete(archive=archive, status=status)
            self.assertIsNone(self.auto.claim_due(quiescent=True))
            self.now += 86400
        before = self.auto.path.read_bytes()
        with patch('quantlab.automatic_backup.atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.auto.claim_due(quiescent=True)
        self.assertEqual(before, self.auto.path.read_bytes())
        self.assertFalse(self.directory.exists())

    def test_limits_preserve_unknown_files_and_do_not_consume_attempt(self):
        self.enable()
        self.directory.mkdir()
        for n in range(MAX_ARCHIVES):
            (self.directory / f'markauto-{self.auto.workspace_id[:16]}-{n}-unknown.zip').write_bytes(b'unrecognized')
        before = self.auto.path.read_bytes()
        with self.assertRaisesRegex(RuntimeSafetyError, 'storage limit'):
            self.auto.claim_due(quiescent=True)
        self.assertEqual(before, self.auto.path.read_bytes())
        self.assertEqual(len(list(self.directory.iterdir())), MAX_ARCHIVES)
        self.auto.configure(enabled=True, directory=str(self.base / 'other'))
        with patch('quantlab.automatic_backup.shutil.disk_usage') as usage:
            usage.return_value.free = 1
            with self.assertRaisesRegex(RuntimeSafetyError, 'free space'):
                self.auto.claim_due(quiescent=True)
        self.assertIsNone(self.auto.load()['last_attempt_day'])

    def test_byte_cap_and_orphan_temporaries_preserved(self):
        self.enable()
        self.directory.mkdir()
        orphan = self.directory / 'orphan.zip.tmp'
        with orphan.open('wb') as stream:
            stream.truncate(2 * 1024 * 1024 * 1024)
        with self.assertRaisesRegex(RuntimeSafetyError, 'storage limit'):
            self.auto.claim_due(quiescent=True)
        self.assertEqual(orphan.stat().st_size, 2 * 1024 * 1024 * 1024)
        self.assertIsNone(self.auto.load()['last_attempt_day'])

    def test_real_archive_write_failure_leaves_no_success_or_temp(self):
        self.enable()
        archive = self.auto.claim_due(quiescent=True)['path']
        with patch('quantlab.runtime_support.os.replace', side_effect=OSError('failed archive write')):
            with self.assertRaises(OSError):
                BackupManager(self.paths).create(archive)
        self.auto.complete(archive=archive, status='error')
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertIsNone(self.auto.claim_due(quiescent=True))

    def test_credential_and_control_hardlinks_never_enter_archive(self):
        self.enable()
        for directory in (self.paths.credentials, self.paths.controls):
            with self.subTest(directory=directory):
                source = directory / 'sensitive'
                source.write_bytes(b'private credential or irreversible budget')
                link = self.paths.state / 'innocent-name'
                os.link(source, link)
                try:
                    archive = self.base / 'unsafe.zip'
                    with self.assertRaisesRegex(RuntimeSafetyError, 'Hard-linked'):
                        BackupManager(self.paths).create(archive)
                    self.assertFalse(archive.exists())
                    self.assertEqual(source.read_bytes(), b'private credential or irreversible budget')
                finally:
                    link.unlink()

    def test_config_hardlink_and_special_file_are_rejected(self):
        self.enable()
        raw = self.auto.path.read_bytes()
        source = self.paths.controls / 'sentinel'
        source.write_bytes(raw)
        self.auto.path.unlink()
        os.link(source, self.auto.path)
        with self.assertRaisesRegex(RuntimeSafetyError, 'Hard-linked'):
            self.auto.configure(enabled=False, directory='')
        self.assertEqual(source.read_bytes(), raw)
        self.auto.path.unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.auto.path)
            with self.assertRaisesRegex(RuntimeSafetyError, 'regular file'):
                self.auto.load()

    def test_managed_hardlink_and_success_symlink_are_rejected(self):
        self.enable()
        self.directory.mkdir()
        target = self.base / 'target'
        target.write_bytes(b'keep')
        link = self.directory / f'markauto-{self.auto.workspace_id[:16]}-linked.zip'
        os.link(target, link)
        with self.assertRaisesRegex(RuntimeSafetyError, 'unsafe matching'):
            self.auto.claim_due(quiescent=True)
        self.assertIsNone(self.auto.load()['last_attempt_day'])
        link.unlink()
        archive = Path(self.auto.claim_due(quiescent=True)['path'])
        os.link(target, archive)
        with self.assertRaisesRegex(RuntimeSafetyError, 'Hard-linked'):
            self.auto.complete(archive=archive, status='success')

    @unittest.skipUnless(symlinks_available(), SYMLINK_REASON)
    def test_success_symlink_is_rejected(self):
        self.enable()
        self.directory.mkdir()
        target = self.base / 'target'
        target.write_bytes(b'keep')
        archive = Path(self.auto.claim_due(quiescent=True)['path'])
        archive.symlink_to(target)
        with self.assertRaises(RuntimeSafetyError):
            self.auto.complete(archive=archive, status='success')
        self.assertEqual(self.auto.load()['last_status'], 'attempted')
        self.assertEqual(target.read_bytes(), b'keep')

    def test_managed_links_rejected_despite_incomplete_directory_metadata(self):
        self._managed_link_metadata('hardlink')

    @unittest.skipUnless(symlinks_available(), SYMLINK_REASON)
    def test_managed_symlinks_rejected_despite_incomplete_directory_metadata(self):
        self._managed_link_metadata('symlink')

    def _managed_link_metadata(self, kind):
        self.enable()
        self.directory.mkdir()
        target = self.base / 'target'
        target.write_bytes(b'keep')
        before = self.auto.path.read_bytes()
        for name in (f'markauto-{self.auto.workspace_id[:16]}-linked.zip', 'orphan.zip.tmp'):
            with self.subTest(name=name, kind=kind):
                link = self.directory / name
                if kind == 'hardlink':
                    os.link(target, link)
                    self.assertEqual(link.lstat().st_nlink, 2)
                else:
                    link.symlink_to(target)
                try:
                    # Windows DirEntry.stat() omits link counts. Also cover
                    # stale regular-file metadata for a replaced symlink.
                    cached = list(target.stat())
                    for field in (stat.ST_INO, stat.ST_DEV, stat.ST_NLINK):
                        cached[field] = 0
                    entry = Mock(spec=os.DirEntry)
                    entry.name = link.name
                    entry.path = str(link)
                    entry.stat.return_value = os.stat_result(cached)
                    with patch('quantlab.automatic_backup.os.scandir') as scan:
                        scan.return_value.__enter__.return_value = [entry]
                        with self.assertRaisesRegex(RuntimeSafetyError, 'unsafe matching'):
                            self.auto.claim_due(quiescent=True)
                    self.assertEqual(self.auto.path.read_bytes(), before)
                    self.assertIsNone(self.auto.load()['last_attempt_day'])
                    self.assertEqual(target.read_bytes(), b'keep')
                    self.assertEqual(link.read_bytes(), b'keep')
                    if kind == 'symlink':
                        self.assertTrue(link.is_symlink())
                    else:
                        self.assertEqual(link.lstat().st_nlink, 2)
                finally:
                    link.unlink()

    def test_unavailable_old_destination_can_be_disabled_or_replaced(self):
        self.enable()
        self.auto.claim_due(quiescent=True)
        watermark = self.auto.load()['last_attempt_day']
        replacement = self.base / 'replacement'
        original_check = self.auto.destination_directory

        def check(path):
            if Path(path).resolve() == self.directory.resolve():
                raise RuntimeSafetyError('old drive unavailable')
            return original_check(path)

        with patch.object(self.auto, 'destination_directory', side_effect=check) as checked:
            self.auto.configure(enabled=False, directory=str(self.directory))
            checked.assert_not_called()
        self.assertEqual(self.auto.load()['last_attempt_day'], watermark)
        self.enable()
        with patch.object(self.auto, 'destination_directory', side_effect=check) as checked:
            self.auto.configure(enabled=True, directory=str(replacement))
            checked.assert_called_once_with(str(replacement))
        self.assertEqual(self.auto.load()['directory'], str(replacement.resolve()))
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
            with self.assertRaises(RuntimeSafetyError):
                self.auto.claim_due(quiescent=True)
        with self.assertRaises(RuntimeSafetyError):
            self.auto.complete(archive='unknown.zip', status='success')


class WorkspaceArchiveTests(unittest.TestCase):
    """The pre-migration archive copies every byte, verifies it, and refuses anything unsafe."""

    def setUp(self):
        from quantlab.research_core.adapters import workspace_archive as archive

        self.archive = archive
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name).resolve()
        self.boot, self.trading, self.out = self.base / 'boot', self.base / 'trading', self.base / 'out'
        for relative, data in (
            ('credentials/token.bin', b'\x00opaque\xff'),
            ('control-v1/registry.sqlite', b'SQLite control'),
            ('control-v1/registry.sqlite-wal', b'wal bytes'),
            ('state-v1/.hidden-unknown', b'kept even though nobody listed it'),
            ('state-v1/settings.json', b'{"a": 1}'),
        ):
            path = self.boot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.trading / 'market').mkdir(parents=True)
        (self.trading / 'trading-v2.sqlite').write_bytes(b'ledger' * 1000)
        (self.trading / 'market' / 'klines.sqlite3').write_bytes(b'bars')
        self.sources = {'bootstrap': self.boot, 'trading': self.trading}

    def snapshot(self):
        return {
            str(path.relative_to(self.base)): (path.read_bytes(), path.stat().st_mtime_ns)
            for root in self.sources.values()
            for path in root.rglob('*')
            if path.is_file()
        }

    def test_every_file_is_copied_exactly_verified_and_the_sources_are_untouched(self):
        before = self.snapshot()
        manifest = self.archive.create_archive(self.sources, self.out)
        self.assertEqual(manifest['file_count'], 7)
        self.assertEqual(manifest['total_bytes'], sum(len(data) for data, _ in before.values()))
        for entry in manifest['entries']:
            copied = (self.out / 'files' / entry['label'] / entry['path']).read_bytes()
            original = (self.sources[entry['label']] / entry['path']).read_bytes()
            self.assertEqual(copied, original)
        kinds = {e['path']: e['kind'] for e in manifest['entries']}
        self.assertEqual(
            (kinds['control-v1/registry.sqlite'], kinds['control-v1/registry.sqlite-wal'], kinds['state-v1/.hidden-unknown']),
            ('sqlite', 'sqlite-sidecar', 'file'),
        )
        self.assertEqual(self.archive.verify_archive(self.out)['file_count'], 7)
        self.assertEqual(self.snapshot(), before)  # nothing read-only was changed, not even a timestamp

    def test_unsafe_requests_are_refused_and_leave_no_destination(self):
        unsafe = {
            'destination exists': (self.sources, self.out, 'destination_exists'),
            'destination inside a source': (self.sources, self.trading / 'archive', 'destination_overlaps_source'),
            'source inside the destination': (self.sources, self.base, 'destination_overlaps_source'),
            'relative destination': (self.sources, Path('relative-archive'), 'path_not_local_absolute'),
            'network destination': (self.sources, Path('//server/share/archive'), 'path_not_local_absolute'),
            'missing source': ({'bootstrap': self.base / 'nowhere'}, self.base / 'a2', 'source_missing'),
            'bad label': ({'../x': self.boot}, self.base / 'a3', 'bad_source_label'),
        }
        self.out.mkdir()
        for name, (sources, destination, code) in unsafe.items():
            with self.subTest(name), self.assertRaises(self.archive.ArchiveError) as caught:
                self.archive.create_archive(sources, destination)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(list(self.out.iterdir()), [])  # the pre-existing destination was not touched
        self.assertFalse((self.base / 'a2').exists() or (self.base / 'a3').exists())

    def test_links_are_refused(self):
        with patch.object(self.archive, '_is_link', side_effect=lambda path: path.name == 'settings.json'):
            with self.assertRaises(self.archive.ArchiveError) as caught:
                self.archive.create_archive(self.sources, self.out)
        self.assertEqual(caught.exception.code, 'link_refused')
        self.assertFalse(self.out.exists())

    def test_too_little_free_space_is_refused_instead_of_archiving_part_of_the_workspace(self):
        with patch.object(self.archive.shutil, 'disk_usage', return_value=SimpleNamespace(free=1024)):
            with self.assertRaises(self.archive.ArchiveError) as caught:
                self.archive.create_archive(self.sources, self.out)
        self.assertEqual(caught.exception.code, 'not_enough_space')
        self.assertFalse(self.out.exists())

    def test_a_file_that_changes_while_it_is_copied_fails_the_run_and_removes_the_partial_archive(self):
        real = self.archive._copy_and_hash
        victim = self.trading / 'trading-v2.sqlite'

        def copy_then_write(source, target):
            digest = real(source, target)
            if source == victim.resolve():
                victim.write_bytes(victim.read_bytes() + b'a live writer appended this')
            return digest

        with patch.object(self.archive, '_copy_and_hash', side_effect=copy_then_write):
            with self.assertRaises(self.archive.ArchiveError) as caught:
                self.archive.create_archive(self.sources, self.out)
        self.assertEqual(caught.exception.code, 'source_changed_during_archive')
        self.assertFalse(self.out.exists())

    def test_cancelling_between_files_removes_only_the_partial_archive(self):
        calls = []

        def cancel_second():
            calls.append(1)
            return len(calls) == 2

        before = self.snapshot()
        with self.assertRaises(self.archive.ArchiveError) as caught:
            self.archive.create_archive(self.sources, self.out, cancelled=cancel_second)
        self.assertEqual(caught.exception.code, 'cancelled')
        self.assertFalse(self.out.exists())
        self.assertEqual(self.snapshot(), before)

    def test_verification_detects_a_changed_missing_or_extra_archived_file(self):
        self.archive.create_archive(self.sources, self.out)
        victim = self.out / 'files' / 'bootstrap' / 'state-v1' / 'settings.json'
        original = victim.read_bytes()
        victim.write_bytes(original.replace(b'1', b'2'))
        with self.assertRaises(self.archive.ArchiveError) as caught:
            self.archive.verify_archive(self.out)
        self.assertEqual(caught.exception.code, 'archive_verification_failed')
        victim.write_bytes(original)
        extra = self.out / 'files' / 'bootstrap' / 'extra.bin'
        extra.write_bytes(b'x')
        with self.assertRaises(self.archive.ArchiveError) as caught:
            self.archive.verify_archive(self.out)
        self.assertEqual(caught.exception.code, 'archive_files_differ_from_manifest')
        extra.unlink()
        victim.unlink()
        with self.assertRaises(self.archive.ArchiveError):
            self.archive.verify_archive(self.out)

    def test_the_command_line_tool_reports_only_counts_or_a_stable_refusal(self):
        import io
        from contextlib import redirect_stdout
        from tools import archive_workspace

        sources = ['--source', f'bootstrap={self.boot}', '--source', f'trading={self.trading}']
        destination = ['--destination', str(self.out)]
        runs = (
            (destination + sources, 'ARCHIVED', 0),
            (destination + ['--verify'], 'VERIFIED', 0),
            (destination + sources + ['--dry-run'], 'DRY_RUN', 0),
            (destination + sources, 'REFUSED', 2),  # archiving again onto the existing archive
        )
        for arguments, status, exit_code in runs:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = archive_workspace.main(arguments)
            report = json.loads(buffer.getvalue())
            self.assertEqual((report['status'], code), (status, exit_code))
        self.assertEqual(report['code'], 'destination_exists')
        self.assertEqual(set(report), {'status', 'code'})  # never a path or file content


if __name__ == '__main__':
    unittest.main()
