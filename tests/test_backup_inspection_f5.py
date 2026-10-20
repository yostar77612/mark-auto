"""Cheap read-only F5 projections and restore compatibility checks."""

import hashlib
import json
import os
from pathlib import Path
import struct
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
import uuid

from quantlab import backup_inspection as reader


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / ('f5-' + uuid.uuid4().hex)
        self.root.mkdir(mode=0o755)
        self.addCleanup(shutil.rmtree, self.root)
        self.archive = self.root / 'backup.zip'
        self.state = self.root / 'state.json'

    def archive_with(self, *names):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('manifest.json', '{"credential":"private-content"}')
            for name in names:
                archive.writestr(name, 'OOS-bearing-payload private-content')
        # Windows ZipInfo normalizes separators while writing; pin raw members.
        for name in names:
            if '\\' in name:
                raw = self.archive.read_bytes().replace(name.replace('\\', '/').encode(), name.encode())
                self.archive.write_bytes(raw)

    def digest(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}

    def test_missing_corrupt_moved_and_oversized_state(self):
        self.assertIsNone(reader.latest_metadata(self.state))
        for value in ('broken', '[]', '{}', ' ' * (reader.MAX_STATE_BYTES + 1)):
            self.state.write_text(value)
            self.assertIsNone(reader.latest_metadata(self.state))
        self.state.write_text(json.dumps({'last_archive': str(self.archive)}))
        self.assertIsNone(reader.latest_metadata(self.state))

    def test_metadata_only_stats_archive_and_fixed_time(self):
        self.archive_with('state/settings.json')
        os.utime(self.archive, (1700000000, 1700000000))
        self.state.write_text(json.dumps({'last_archive': str(self.archive)}))
        original_open = Path.open

        def opened(path, *args, **kwargs):
            self.assertNotEqual(path, self.archive)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', opened):
            value = reader.latest_metadata(self.state)
        self.assertEqual(value.modified, 1700000000)
        self.assertEqual(value.size, self.archive.stat().st_size)
        self.assertEqual(reader.human_size(1024), '1.0 KiB')
        self.archive.rename(self.root / 'moved.zip')
        self.assertIsNone(reader.latest_metadata(self.state))

    def test_preview_no_writes_no_member_reads_and_private_names_filtered(self):
        self.archive_with('state/settings.json', 'state/OOS-private-token-cookie.txt', 'state/credentials.json')
        before = self.digest()
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('no payloads')):
            value = reader.inspect_archive(self.archive)
        self.assertFalse(value.error_code)
        self.assertEqual(value.count, 4)
        self.assertEqual(value.names, ('manifest.json', 'state/settings.json'))
        self.assertEqual(value.hidden, 2)
        self.assertNotIn('OOS', repr(value))
        self.assertNotIn('credentials', repr(value))
        self.assertEqual(before, self.digest())

    def test_member_limit_truncates_count(self):
        self.archive_with(*(f'state/item-{i}.json' for i in range(70)))
        value = reader.inspect_archive(self.archive)
        self.assertEqual(value.count, 71)
        self.assertEqual(value.truncated, 21)
        self.assertLessEqual(len(value.names), reader.MAX_DISPLAY_MEMBERS)

    def test_reads_only_eocd_and_bounded_central_metadata(self):
        self.archive_with('state/settings.json')
        raw = self.archive.read_bytes()
        offset = struct.unpack_from('<L', raw, len(raw) - 6)[0]
        original_open = Path.open
        reads = []

        class Guarded:
            def __init__(self, source):
                self.source = source

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.source.close()

            def seek(self, *args):
                return self.source.seek(*args)

            def read(self, size):
                reads.append((self.source.tell(), size))
                if self.source.tell() < offset or size > reader.MAX_CENTRAL_BYTES:
                    raise AssertionError('payload or unbounded read')
                return self.source.read(size)

        with patch.object(Path, 'open', lambda path, *args, **kwargs: Guarded(original_open(path, *args, **kwargs))):
            value = reader.inspect_archive(self.archive)
        self.assertFalse(value.error_code)
        self.assertEqual(reads, [(len(raw) - 22, 22), (offset, len(raw) - 22 - offset)])

    def test_zip_slip_absolute_duplicate_and_symlink_rejected_without_writes(self):
        for name in ('../escape', '/absolute', 'C:/absolute', 'state/../../escape', 'state\\escape', 'state/settings.json/../escape', 'manifest.json'):
            with self.subTest(name=name):
                if name == 'manifest.json':
                    self.archive_with('MANIFEST.JSON')
                else:
                    self.archive_with(name)
                before = self.digest()
                self.assertEqual(reader.inspect_archive(self.archive).error_code, 'validation_failed')
                self.assertEqual(before, self.digest())
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('manifest.json', '{}')
            info = zipfile.ZipInfo('state/link')
            info.external_attr = 0o120777 << 16
            archive.writestr(info, 'target')
        self.assertEqual(reader.inspect_archive(self.archive).error_code, 'validation_failed')

    def test_invalid_corrupt_missing_manifest_and_excessive_central(self):
        for raw in (b'', b'not a zip', b'PK\x05\x06' + bytes(18)):
            self.archive.write_bytes(raw)
            self.assertEqual(reader.inspect_archive(self.archive).error_code, 'validation_failed')
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('state/settings.json', '{}')
        self.assertEqual(reader.inspect_archive(self.archive).error_code, 'validation_failed')
        self.archive_with('state/settings.json')
        raw = bytearray(self.archive.read_bytes())
        struct.pack_into('<L', raw, len(raw) - 10, reader.MAX_CENTRAL_BYTES + 1)
        self.archive.write_bytes(raw)
        self.assertEqual(reader.inspect_archive(self.archive).error_code, 'validation_failed')


class PanelTests(InspectionTests):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from PySide6.QtWidgets import QCheckBox, QLineEdit, QPushButton, QWidget
        from desktop_pages.backup_inspection import BackupInspectionPanel

        self.page = QWidget()
        self.page.jobs = SimpleNamespace(active=False)
        self.page.backup_path = QLineEdit(self.page)
        self.page.restore_confirm = QCheckBox(self.page)
        self.page.automatic_backup_panel = SimpleNamespace(scheduler=SimpleNamespace(path=self.state))
        self.page.privacy = SimpleNamespace(enabled=False)
        self.clock = Mock(return_value='2023-11-14 22:13:20 UTC')
        self.panel = BackupInspectionPanel(self.page, format_time=self.clock)
        self.page.backup_inspection_panel = self.panel
        self.panel.restore_button = QPushButton(self.page)
        self.addCleanup(self.page.close)

    def test_optional_preview_path_and_archive_changes_do_not_gate_restore(self):
        self.archive_with('state/settings.json')
        self.page.backup_path.setText(str(self.archive))
        self.assertTrue(self.panel.restore_button.isEnabled())
        self.panel.inspect()
        self.assertTrue(self.panel.ready())
        self.assertTrue(self.panel.restore_button.isEnabled())
        self.page.restore_confirm.setChecked(True)
        self.assertTrue(self.panel.restore_button.isEnabled())
        self.page.backup_path.setText(str(self.root / 'other.zip'))
        self.assertIsNone(self.panel.preview)
        self.assertTrue(self.panel.restore_button.isEnabled())
        self.page.backup_path.setText(str(self.archive))
        self.panel.inspect()
        self.archive.write_bytes(b'corrupt')
        self.assertFalse(self.panel.ready())
        self.panel.inspect()
        self.assertTrue(self.panel.restore_button.isEnabled())
        self.assertIn('validation_failed', self.panel.summary.text())

    def test_privacy_fixed_clock_placeholders_and_no_oos_widgets(self):
        from desktop_strings import ui_text

        self.assertIn(ui_text('backup_inspection.unavailable'), self.panel.latest.text())
        self.archive_with('state/settings.json', 'state/OOS-private-token-cookie.txt')
        os.utime(self.archive, (1700000000, 1700000000))
        self.page.backup_path.setText(str(self.archive))
        self.panel.refresh(str(self.archive))
        self.panel.inspect()
        self.clock.assert_called_with(1700000000)
        self.assertIn('2023-11-14', self.panel.latest.text())
        self.assertIn('state/settings.json', self.panel.summary.text())
        for private in (True, False):
            self.page.privacy.enabled = private
            self.panel._privacy_render()
            texts = self.panel.latest.text() + self.panel.summary.text()
            self.assertNotIn('OOS', texts)
            self.assertNotIn('private-content', texts)
            self.assertEqual('state/settings.json' in texts, not private)
            self.assertEqual('2023-11-14' in texts, not private)
            self.assertEqual(self.page.backup_path.echoMode().name, 'Password' if private else 'Normal')

    def test_restore_job_payload_consent_reset_and_no_preview_dispatch(self):
        from desktop_pages.settings import SettingsPage
        from quantlab.core import ValidationError

        self.archive_with('state/settings.json')
        self.page.backup_path.setText(str(self.archive))
        self.page.chatgpt_panel = SimpleNamespace(abandon_primary_sign_in=Mock())
        self.page.backups = object()
        self.page.start_job = Mock()
        with self.assertRaises(ValidationError):
            SettingsPage.backup(self.page, True)
        self.page.restore_confirm.setChecked(True)
        SettingsPage.backup(self.page, True)
        self.page.start_job.assert_called_once_with('ui_backup_restore', {'path': str(self.archive)})
        self.assertFalse(self.page.restore_confirm.isChecked())
        self.page.start_job.reset_mock()
        self.page.restore_confirm.setChecked(True)
        with patch('threading.Thread.start', side_effect=AssertionError('preview thread')):
            self.panel.inspect()
        self.page.start_job.assert_not_called()
        self.assertEqual(len(self.panel.findChildren(__import__('PySide6.QtCore', fromlist=['QTimer']).QTimer)), 0)
        SettingsPage.backup(self.page, True)
        self.page.start_job.assert_called_once_with('ui_backup_restore', {'path': str(self.archive)})
        self.assertFalse(self.page.restore_confirm.isChecked())
        self.assertIsNone(self.panel.preview)

    def test_completion_refreshes_state_after_scheduler_complete(self):
        from desktop_automatic_backup import AutomaticBackupPanel

        self.archive_with('state/settings.json')
        scheduler = SimpleNamespace(complete=lambda **kwargs: self.state.write_text(json.dumps({'last_archive': str(self.archive)})))
        fake = SimpleNamespace(window=self.page, archive=str(self.archive), job_id='backup-1', scheduler=scheduler, status=Mock())
        AutomaticBackupPanel.handle_job_event(fake, {'type': 'result', 'job_id': 'backup-1'})
        self.assertEqual(self.panel.metadata.size, self.archive.stat().st_size)
        self.assertIsNone(fake.archive)


if __name__ == '__main__':
    unittest.main()
