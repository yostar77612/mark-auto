"""Offline native-schema fixtures: download, strict validation and safe activation."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports

import csv
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab import downloads
from quantlab import download_import as workflow
from quantlab.core import ValidationError
from quantlab.data import OFFICIAL_TICK_COLUMNS
from quantlab.reporting import load_dataset
from tests.test_downloads import Response, zip_bytes


class DownloadAutoImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache, self.workspace = self.root / 'cache', self.root / 'workspace'
        self.workspace.mkdir()
        self.contract = 'TAIFEX:TMF:202610'
        self.calendar = self.root / 'calendar.json'
        sessions = [
            dict(
                open=f'2026-10-{day}T08:45:00+08:00',
                end=f'2026-10-{day}T08:47:00+08:00',
                trade_date=f'2026-10-{day}',
                session='day',
                source='explicit synthetic test calendar',
                contract_id=self.contract,
            )
            for day in ('12', '13')
        ]
        self.calendar.write_text(json.dumps({'version': 'offline-fixture-v1', 'sessions': sessions}), encoding='utf-8')
        self.payload = {'network_opt_in': True, 'days': 2, 'auto_import': {'calendar': str(self.calendar), 'contract': self.contract, 'confirmed': True}}
        self.urls = [f'https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_2026_10_{day}.zip' for day in ('12', '13')]
        self.page = ''.join(f'<input onclick="window.open(\'{url}\')">' for url in self.urls).encode()
        self.archives = dict(zip(self.urls, (zip_bytes(name=f'Daily_2026_10_{day}.csv', content=self.csv(day)) for day in ('12', '13'))))
        self.fetches = []

    def csv(self, day):
        output = io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\n')
        writer.writerow(OFFICIAL_TICK_COLUMNS)
        for stamp in ('084500', '084600'):
            writer.writerow([f'202610{day}', 'TMF', '202610', stamp, '25000', '2', '-', '-', ''])
            writer.writerow([f'202610{day}', 'TX', '202610', stamp, '25000', '2', '-', '-', ''])
        return output.getvalue().encode('utf-8')

    def transport(self, url, timeout):
        self.fetches.append(url)
        return Response(self.page if url == downloads.SOURCE_URL else self.archives[url], url)

    def run_workflow(self):
        original = downloads.refresh

        def refresh(cache, *, days, kind, trade_dates=None):
            return original(cache, days=days, kind=kind, transport=self.transport, trade_dates=trade_dates)

        with patch.object(downloads, 'refresh', side_effect=refresh):
            from quantlab.research_core.application.ui_operations.data import _handle_ui_refresh

            return _handle_ui_refresh(_c_create_operation_ports(), self.payload, SimpleNamespace(cache=self.cache), self.workspace)

    def test_all_downloaded_files_are_imported_and_the_original_validator_accepts(self):
        result = self.run_workflow()
        data = load_dataset(self.workspace / 'dataset.json')
        self.assertEqual(result['auto_import']['status'], 'imported')
        self.assertEqual(result['downloaded_archives'], 2)
        self.assertEqual(len(data.bars), 4)
        self.assertEqual({bar.contract_id for bar in data.bars}, {self.contract})
        self.assertEqual({bar.trade_date for bar in data.bars}, {'2026-10-12', '2026-10-13'})
        self.assertTrue(data.quality['valid'])
        self.assertEqual(len(data.manifest['download_sources']), 2)
        self.assertFalse(list(self.cache.glob('.download-import-*')))
        self.assertEqual(self.fetches, [downloads.SOURCE_URL, *reversed(self.urls)])

    def test_missing_settings_or_consent_never_download(self):
        for change in (
            {'calendar': ''},
            {'calendar': str(self.root / 'missing.json')},
            {'contract': 'TAIFEX:TX:202610'},
            {'contract': 'TAIFEX:TMF:invalid'},
            {'confirmed': False},
        ):
            with self.subTest(change=change):
                self.payload['auto_import'].update(change)
                with self.assertRaises(ValidationError):
                    self.run_workflow()
                self.assertEqual(self.fetches, [])
                self.payload['auto_import'] = {'calendar': str(self.calendar), 'contract': self.contract, 'confirmed': True}
        self.payload['network_opt_in'] = False
        with self.assertRaises(ValidationError):
            self.run_workflow()
        self.assertEqual(self.fetches, [])

    def test_quality_failure_retains_downloads_and_previous_active_data(self):
        old = {name: ('preserve-' + name).encode() for name in ('dataset.json', 'dataset_calendar.json')}
        for name, raw in old.items():
            (self.workspace / name).write_bytes(raw)
        calendar = json.loads(self.calendar.read_text())
        calendar['sessions'][0]['end'] = '2026-10-12T08:48:00+08:00'
        self.calendar.write_text(json.dumps(calendar), encoding='utf-8')
        with self.assertRaisesRegex(ValidationError, 'download_import_failed'):
            self.run_workflow()
        self.assertEqual({name: (self.workspace / name).read_bytes() for name in old}, old)
        self.assertEqual(json.loads((self.cache / 'latest.json').read_text())['downloaded_archives'], 2)

    def test_source_tampering_and_duplicate_archives_are_refused(self):
        manifest = downloads.refresh(self.cache, days=2, transport=self.transport)
        destination = self.root / 'combined.csv'
        member = manifest['archives'][0]['files'][0]
        Path(member['path']).write_bytes(b'changed')
        with self.assertRaises(ValidationError):
            workflow._combined(manifest, self.cache, destination, self.contract)
        manifest['archives'] = [manifest['archives'][1]] * 2
        with self.assertRaises(ValidationError):
            workflow._combined(manifest, self.cache, destination, self.contract)

    def test_failed_pair_publication_restores_exact_previous_bytes_and_keeps_backup(self):
        self.run_workflow()
        old = {name: (self.workspace / name).read_bytes() for name in ('dataset.json', 'dataset_calendar.json')}
        with patch.object(workflow, 'write_json', side_effect=OSError('synthetic publication denial')):
            with self.assertRaisesRegex(ValidationError, 'download_import_failed'):
                self.run_workflow()
        self.assertEqual({name: (self.workspace / name).read_bytes() for name in old}, old)
        for name, raw in old.items():
            self.assertTrue(any(path.read_bytes() == raw for path in (self.workspace / 'download_import_history').glob('*/' + name)))

    def test_combined_input_keeps_existing_row_and_byte_limits(self):
        manifest = downloads.refresh(self.cache, days=2, transport=self.transport)
        for limit, maximum in (('MAX_ROWS', 1), ('MAX_FILE_BYTES', 10)):
            with self.subTest(limit=limit), patch.object(workflow, limit, maximum):
                with self.assertRaisesRegex(ValidationError, 'download_import_source_invalid'):
                    workflow._combined(manifest, self.cache, self.root / 'combined.csv', self.contract)
        self.assertFalse((self.workspace / 'dataset.json').exists())

    def test_reparse_sources_and_paths_outside_cache_are_rejected_before_read(self):
        manifest = downloads.refresh(self.cache, days=2, transport=self.transport)
        member = manifest['archives'][0]['files'][0]
        source = Path(member['path'])
        original = Path.lstat

        def marked(path):
            info = original(path)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == source else info

        with patch.object(Path, 'lstat', marked):
            with self.assertRaisesRegex(ValidationError, 'download_import_source_invalid'):
                workflow._source(member, self.cache)
        outside = self.root / 'outside.csv'
        outside.write_bytes(source.read_bytes())
        member['path'] = str(outside)
        with self.assertRaisesRegex(ValidationError, 'download_import_source_invalid'):
            workflow._source(member, self.cache)
