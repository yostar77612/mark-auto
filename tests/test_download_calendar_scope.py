"""Explicit calendar selection must not consume an unrelated top-of-page archive."""

from datetime import date, timedelta
import unittest
from unittest.mock import patch

from quantlab import downloads
from quantlab.core import ValidationError
from quantlab.reporting import load_dataset
from tests import test_download_auto_import as base
from tests.test_downloads import zip_bytes

FUTURE = 'https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_2026_10_27.zip'


class DownloadCalendarScopeTests(unittest.TestCase):
    def fixture(self):
        fixture = base.DownloadAutoImportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.page += f'<input onclick="window.open(\'{FUTURE}\')">'.encode()
        return fixture

    def test_auto_import_downloads_both_declared_dates_without_requesting_unrelated_future_archive(self):
        fixture = self.fixture()
        result = fixture.run_workflow()
        self.assertEqual(fixture.fetches, [downloads.SOURCE_URL, *reversed(fixture.urls)])
        self.assertEqual(result['downloaded_archives'], 2)
        self.assertEqual(result['explicit_calendar_trade_dates'], ['2026-10-12', '2026-10-13'])
        self.assertEqual({row['trade_date'] for row in result['archives']}, {'2026-10-12', '2026-10-13'})
        data = load_dataset(fixture.workspace / 'dataset.json')
        self.assertEqual(len(data.bars), 4)
        self.assertTrue(data.quality['valid'])
        self.assertFalse((fixture.cache / '2026-10-27').exists())

    def test_download_only_retains_original_observed_provisional_behavior(self):
        fixture = self.fixture()
        fixture.archives[FUTURE] = zip_bytes(name='Daily_2026_10_27.csv', content=fixture.csv('13'))
        result = downloads.refresh(fixture.cache, transport=fixture.transport)
        self.assertEqual(fixture.fetches, [downloads.SOURCE_URL, FUTURE])
        self.assertEqual(result['archives'][0]['trade_date'], '2026-10-27')
        self.assertEqual(result['archives'][0]['completion_status'], 'provisional_unverified')
        self.assertFalse(result['archives'][0]['ranking_eligible'])
        self.assertNotIn('explicit_calendar_trade_dates', result)
        self.assertFalse((fixture.workspace / 'dataset.json').exists())

    def test_no_calendar_match_fetches_no_archive_and_preserves_previous_manifest_and_data(self):
        fixture = self.fixture()
        fixture.page = f'<input onclick="window.open(\'{FUTURE}\')">'.encode()
        fixture.cache.mkdir()
        latest = fixture.cache / 'latest.json'
        latest.write_bytes(b'previous manifest')
        previous = {'dataset.json': b'previous data', 'dataset_calendar.json': b'previous calendar'}
        for name, raw in previous.items():
            (fixture.workspace / name).write_bytes(raw)
        with self.assertRaises(ValidationError):
            fixture.run_workflow()
        self.assertEqual(fixture.fetches, [downloads.SOURCE_URL])
        self.assertEqual(latest.read_bytes(), b'previous manifest')
        self.assertEqual({name: (fixture.workspace / name).read_bytes() for name in previous}, previous)

    def test_invalid_or_unbounded_date_selection_is_refused_before_network(self):
        fixture = self.fixture()
        for dates in (
            frozenset(),
            {'2026-10-12'},
            ('2026-10-12',),
            True,
            '2026-10-12',
            frozenset({True}),
            frozenset({'2026-13-40'}),
            frozenset({'20261012'}),
            frozenset((date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(257)),
        ):
            with self.subTest(dates=dates), self.assertRaises(ValidationError):
                downloads.refresh(fixture.cache, transport=fixture.transport, trade_dates=dates)
        self.assertEqual(fixture.fetches, [])

    def test_import_rechecks_archive_dates_even_if_downloader_evidence_is_substituted(self):
        fixture = self.fixture()
        previous = {'dataset.json': b'previous data', 'dataset_calendar.json': b'previous calendar'}
        for name, raw in previous.items():
            (fixture.workspace / name).write_bytes(raw)
        with patch.object(downloads, 'refresh', return_value={'archives': [{'trade_date': '2026-10-27'}]}) as refresh:
            with self.assertRaisesRegex(ValidationError, 'download_import_failed'):
                fixture.run_workflow()
        self.assertEqual(refresh.call_args.kwargs['trade_dates'], frozenset({'2026-10-12', '2026-10-13'}))
        self.assertEqual({name: (fixture.workspace / name).read_bytes() for name in previous}, previous)
        self.assertEqual(fixture.fetches, [])
