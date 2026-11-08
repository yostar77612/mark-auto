"""Recorded official bytes through the operational importer; tests never download."""

from contextlib import closing, redirect_stdout
from datetime import date, datetime, time, timezone
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.official_daily_source import OfficialDailyStockSource
from quantlab.trading.runtime.stock_history import validate_stock_url
from tools import import_official_daily as tool

FIXTURES = Path(__file__).parent / 'fixtures/daily_basis_import'
START, END = date(2025, 6, 2), date(2025, 6, 13)
NOW = datetime(2025, 6, 13, 1, 1, tzinfo=timezone.utc)
DAY_DATES = tuple(date(2025, 6, day) for day in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 23, 24, 25, 26, 27, 30)) + tuple(
    date(2025, 7, day) for day in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30, 31)
)
EVENT_URL = tool.daily_events_url(date(2025, 6, 1), date(2025, 7, 1))


def calendar():
    return TradingCalendar(
        'recorded-June-fixture',
        'v1',
        'EXPLICIT_OFFLINE_TEST_DATES',
        tuple(TradingSession(day, datetime.combine(day, time(1), timezone.utc), datetime.combine(day, time(5, 30), timezone.utc)) for day in DAY_DATES),
    )


class OfficialDailyImportTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / 'cache.sqlite'
        self.manifest = FIXTURES / 'manifest.json'
        self.transport = Mock(side_effect=AssertionError('tests must not use network'))

    def run_import(self, **kwargs):
        options = dict(manifest=self.manifest, transport=self.transport, clock=lambda: NOW)
        options.update(kwargs)
        return tool.import_official_daily(self.cache, 'TWSE:6225', START, END, **options)

    def read(self, instrument='TWSE:6225'):
        with closing(KlineStore(self.cache)) as store:
            return OfficialDailyStockSource(store, SimpleNamespace(now=lambda: NOW)).history(instrument, calendar(), through=date(2025, 6, 12), start=START)

    def changed_manifest(self, change, *, file_change=None):
        body = json.loads(self.manifest.read_text())
        for item in body['documents']:
            raw = (FIXTURES / item['file']).read_bytes()
            if file_change is not None:
                raw = file_change(item, raw)
            (self.root / item['file']).write_bytes(raw)
        change(body)
        target = self.root / 'manifest.json'
        target.write_text(json.dumps(body))
        return target

    def refuse(self, **options):
        with self.assertRaises(DomainError):
            self.run_import(**options)
        self.assertFalse(self.cache.exists(), 'rejected input must not open/create the target database')

    def test_real_recorded_raw_and_complete_negative_events_survive_sqlite_reopen(self):
        result = self.run_import()
        history = self.read()
        self.assertEqual((result['status'], result['bars'], result['events']), ('IMPORTED', 9, 0))
        self.assertEqual(history.bars[-1].close, Decimal('11.65'))
        self.assertEqual(history.events, ())
        self.assertEqual(history.bars[0].source_digest, '8f3bbac0d2a7f95ff48da767569bbd5dc5350af48ec8177388eb48a85f298166')
        self.assertEqual(history.observed_at, NOW)
        self.transport.assert_not_called()

    def test_recorded_ex_dividend_positive_preserves_raw_prices_and_reference(self):
        result = tool.import_official_daily(self.cache, 'TWSE:2330', START, END, manifest=self.manifest, clock=lambda: NOW, transport=self.transport)
        history = self.read('TWSE:2330')
        self.assertEqual(result['events'], 1)
        self.assertEqual((history.events[0].previous_close, history.events[0].reference_price), (Decimal('1065'), Decimal('1060.49')))
        self.assertEqual(history.events[0].ex_date, date(2025, 6, 12))
        self.assertEqual(history.bars[-1].close, Decimal('1045'))

    def test_download_requires_explicit_per_invocation_consent_before_transport(self):
        self.refuse(manifest=None, archive=self.root / 'recording')
        self.transport.assert_not_called()

    def test_truthy_non_boolean_consent_is_not_consent(self):
        self.refuse(manifest=None, consent_download=1, archive=self.root / 'recording')
        self.transport.assert_not_called()

    def test_download_requires_new_archive_before_transport(self):
        self.refuse(manifest=None, consent_download=True)
        self.transport.assert_not_called()

    def test_download_never_overwrites_archive(self):
        target = self.root / 'recording'
        target.mkdir()
        (target / 'keep').write_text('original')
        self.refuse(manifest=None, consent_download=True, archive=target)
        self.assertEqual((target / 'keep').read_text(), 'original')
        self.transport.assert_not_called()

    def test_no_today_or_future_daily_import_is_requested(self):
        self.refuse(manifest=None, consent_download=True, archive=self.root / 'new', clock=lambda: NOW.replace(day=12))
        self.transport.assert_not_called()

    def test_manifest_digest_cannot_be_forged(self):
        path = self.changed_manifest(lambda body: body['documents'][0].update(sha256='0' * 64))
        with self.assertRaises(DomainError):
            tool.load_manifest(path)

    def test_manifest_cannot_escape_adjacent_payload_directory(self):
        nested = self.root / 'nested'
        nested.mkdir()
        body = json.loads(self.manifest.read_text())
        for item in body['documents']:
            raw = (FIXTURES / item['file']).read_bytes()
            (nested / item['file']).write_bytes(raw)
        (self.root / 'outside.json').write_bytes((FIXTURES / body['documents'][0]['file']).read_bytes())
        body['documents'][0]['file'] = '../outside.json'
        path = nested / 'manifest.json'
        path.write_text(json.dumps(body))
        self.refuse(manifest=path)

    def test_manifest_requires_supported_official_endpoint(self):
        path = self.changed_manifest(lambda body: body['documents'][0].update(url='https://example.org/TWT49U'))
        with self.assertRaises(DomainError):
            tool.load_manifest(path)

    def test_manifest_rejects_duplicate_payload_identity(self):
        path = self.changed_manifest(lambda body: body['documents'].append(body['documents'][0]))
        with self.assertRaises(DomainError):
            tool.load_manifest(path)

    def test_manifest_byte_limit_is_checked_before_json_decode(self):
        path = self.changed_manifest(lambda body: None)
        path.write_bytes(path.read_bytes() + b' ' * (1024 * 1024))
        with self.assertRaises(DomainError):
            tool.load_manifest(path)

    def test_manifest_document_count_is_bounded(self):
        path = self.root / 'oversized.json'
        item = json.loads(self.manifest.read_text())['documents'][0]
        path.write_text(json.dumps({'documents': [item] * 243}))
        with patch.object(Path, 'stat', side_effect=AssertionError('must reject before payload IO')), self.assertRaises(DomainError):
            tool.load_manifest(path)

    def test_manifest_payload_size_is_checked_before_read(self):
        original = Path.stat

        def observed_stat(path, *args, **kwargs):
            if path.name == 'twse_actions_20250601_20250630.json':
                return SimpleNamespace(st_size=tool.MAX_BYTES + 1, st_mode=original(path, *args, **kwargs).st_mode)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'stat', observed_stat), self.assertRaises(DomainError):
            tool.load_manifest(self.manifest)

    def test_manifest_payload_symlink_is_refused_before_read(self):
        original = Path.is_symlink

        def observed_link(path):
            return path.name == 'twse_actions_20250601_20250630.json' or original(path)

        with patch.object(Path, 'is_symlink', observed_link), self.assertRaises(DomainError):
            tool.load_manifest(self.manifest)

    def test_manifest_aggregate_bytes_are_bounded(self):
        with patch.object(tool, 'MAX_TOTAL_BYTES', 100), self.assertRaises(DomainError):
            tool.load_manifest(self.manifest)

    def duplicate_response(self, body, *, global_events):
        original = next(row for row in body['documents'] if ('TWT49U' in row['url']) == global_events and (global_events or 'stockNo=6225' in row['url']))
        duplicate = dict(original, file='duplicate.json')
        raw = (self.root / original['file']).read_bytes() + b'\n'
        duplicate['sha256'] = sha256(raw).hexdigest()
        (self.root / duplicate['file']).write_bytes(raw)
        body['documents'].append(duplicate)

    def test_ambiguous_monthly_payloads_are_not_arbitrarily_selected(self):
        self.refuse(manifest=self.changed_manifest(lambda body: self.duplicate_response(body, global_events=False)))

    def test_ambiguous_complete_event_payloads_are_not_arbitrarily_selected(self):
        self.refuse(manifest=self.changed_manifest(lambda body: self.duplicate_response(body, global_events=True)))

    def test_monthly_payload_is_required_for_each_requested_month(self):
        path = self.changed_manifest(lambda body: body.update(documents=[row for row in body['documents'] if 'stockNo=6225' not in row['url']]))
        self.refuse(manifest=path)

    def test_missing_global_event_response_does_not_imply_no_events(self):
        path = self.changed_manifest(lambda body: body.update(documents=[item for item in body['documents'] if 'TWT49U' not in item['url']]))
        self.refuse(manifest=path)

    def test_event_date_range_must_cover_entire_requested_window(self):
        def short_range(item, raw):
            if 'TWT49U' in item['url']:
                raw = (FIXTURES.parent / 'daily_signal_data/twse_actions_20250611_20250612.json').read_bytes()
                item['sha256'] = sha256(raw).hexdigest()
            return raw

        path = self.changed_manifest(
            lambda body: body['documents'][0].update(url=tool.daily_events_url(date(2025, 6, 11), date(2025, 6, 13))), file_change=short_range
        )
        self.refuse(manifest=path)

    def test_event_response_schema_cannot_be_silently_treated_as_empty(self):
        def change_file(item, raw):
            if 'TWT49U' in item['url']:
                raw = b'{"stat":"OK","fields":[],"data":[]}'
                item['sha256'] = sha256(raw).hexdigest()
            return raw

        self.refuse(manifest=self.changed_manifest(lambda body: None, file_change=change_file))

    def test_payload_stock_title_is_independent_of_manifest_url(self):
        def change_file(item, raw):
            if 'stockNo=6225' in item['url']:
                body = json.loads(raw)
                body['title'] = body['title'].replace('6225', '2330')
                raw = json.dumps(body).encode()
                item['sha256'] = sha256(raw).hexdigest()
            return raw

        self.refuse(manifest=self.changed_manifest(lambda body: None, file_change=change_file))

    def test_unknown_venue_is_refused_before_any_input_io(self):
        with (
            patch.object(tool, 'load_manifest', side_effect=AssertionError('unsupported venue must be refused before input IO')),
            self.assertRaises(DomainError),
        ):
            tool.import_official_daily(self.cache, 'EMERGING:6488', START, END, manifest=self.manifest, clock=lambda: NOW)
        self.assertFalse(self.cache.exists())

    def test_invalid_refresh_leaves_existing_sqlite_facts_unchanged(self):
        self.run_import()
        before = self.read()
        bad = self.changed_manifest(lambda body: body['documents'][0].update(sha256='0' * 64))
        with self.assertRaises(DomainError):
            self.run_import(manifest=bad)
        self.assertEqual(self.read(), before)

    def test_fake_download_archive_is_replayable_without_any_second_download(self):
        from quantlab.trading.adapters.official.stock_data import daily_url

        daily = (FIXTURES / 'twse_6225_202506.json').read_bytes()
        events = (FIXTURES / 'twse_actions_20250601_20250630.json').read_bytes()
        # Use the actual recorded request interval rather than relabel its attestation.
        end = date(2025, 7, 1)
        now = datetime(2025, 7, 1, 1, tzinfo=timezone.utc)
        transport = Mock(side_effect=lambda url: daily if url == daily_url('TWSE:6225', START) else events)
        archive = self.root / 'recording'
        result = tool.import_official_daily(
            self.cache, 'TWSE:6225', date(2025, 6, 1), end, consent_download=True, archive=archive, transport=transport, clock=lambda: now
        )
        self.assertEqual(result['bars'], 21)
        self.assertEqual(transport.call_count, 2)
        receipt = json.loads((archive / 'manifest.json').read_text())
        self.assertEqual(receipt['retrieved_at'], now.isoformat())
        self.assertEqual(len(receipt['documents']), 2)
        second = self.root / 'recovered.sqlite'
        replay = tool.import_official_daily(
            second, 'TWSE:6225', date(2025, 6, 1), end, manifest=archive / 'manifest.json', transport=self.transport, clock=lambda: now
        )
        self.assertEqual(replay['source_digest'], result['source_digest'])
        self.transport.assert_not_called()

    def test_canonical_twt49u_endpoint_is_supported_without_widening_old_endpoints(self):
        self.assertEqual(validate_stock_url(EVENT_URL), EVENT_URL)
        self.assertEqual(
            validate_stock_url(EVENT_URL.replace('/rwd/zh/exRight/', '/exchangeReport/')), EVENT_URL.replace('/rwd/zh/exRight/', '/exchangeReport/')
        )

    def test_twt49u_url_rejects_altered_identity_dates_and_query(self):
        for url in (
            EVENT_URL.replace('https:', 'http:'),
            EVENT_URL.replace('www.twse.com.tw', 'www.twse.com.tw.example.org'),
            EVENT_URL + '&stockNo=2330',
            EVENT_URL + '&response=json',
            EVENT_URL + '&unexpected=',
            EVENT_URL + '#fragment',
            EVENT_URL.replace('20250601', '20250230'),
            EVENT_URL.replace('20250601', '20250701'),
            EVENT_URL.replace('20250601', '2025601'),
        ):
            with self.subTest(url=url), self.assertRaises(DomainError):
                validate_stock_url(url)

    def test_cli_reports_controlled_refusal_without_network_or_cache(self):
        out = StringIO()
        with redirect_stdout(out), patch.object(tool, 'fetch_stock_official', side_effect=AssertionError('network')):
            code = tool.main(['--cache', str(self.cache), '--instrument', 'TWSE:6225', '--start', START.isoformat(), '--end', END.isoformat()])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())['code'], 'official_stock_consent_required')
        self.assertFalse(self.cache.exists())

    def test_cli_offline_manifest_actually_creates_the_requested_sqlite_cache(self):
        out = StringIO()
        with redirect_stdout(out):
            code = tool.main(
                [
                    '--cache',
                    str(self.cache),
                    '--instrument',
                    'TWSE:6225',
                    '--start',
                    START.isoformat(),
                    '--end',
                    END.isoformat(),
                    '--manifest',
                    str(self.manifest),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual((json.loads(out.getvalue())['status'], json.loads(out.getvalue())['bars']), ('IMPORTED', 9))
        with closing(KlineStore(self.cache)) as store:
            rows = store.daily_history('TWSE:6225', START, END)
            self.assertEqual((len(rows.bars), rows.bars[-1].close, rows.events), (9, Decimal('11.65'), ()))


if __name__ == '__main__':
    unittest.main()
