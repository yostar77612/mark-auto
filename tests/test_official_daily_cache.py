"""Immutable revision-keyed official history cache, explicit arrival and failures."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import sqlite3
from threading import RLock
import unittest
from unittest.mock import PropertyMock, patch

import test_official_daily_source as fixtures
from quantlab.trading.ports.stock_history import OfficialPayload
from quantlab.trading.adapters.storage.daily_stock_store import DailyStockStorage
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.official_daily_source import MAX_VERIFIED_HISTORIES, OfficialDailyStockSource, _verified_sources


class OfficialDailyCacheTests(unittest.TestCase):
    def setUp(self):
        self.store = fixtures.CachedStore(fixtures.sample())
        self.calendar = fixtures.calendar()
        self.now = datetime(2020, 1, 4, 2, tzinfo=timezone.utc)
        self.clock = fixtures.SimpleNamespace(now=lambda: self.now)
        self.source = OfficialDailyStockSource(self.store, self.clock)

    def read(self, *, source=None, calendar=None, start=fixtures.FIRST, through=fixtures.THROUGH, cached_only=False):
        return (source or self.source).history(fixtures.ID, calendar or self.calendar, through=through, start=start, cached_only=cached_only)

    def rejected(self, code, operation):
        with self.assertRaises(DomainError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_repeated_hit_does_not_read_or_parse_immutable_payloads(self):
        first = self.read()
        calls = tuple(self.store.calls)
        with patch('quantlab.trading.runtime.official_daily_source.parse_daily', side_effect=AssertionError('hot cache reparsed payload')):
            self.assertIs(self.read(cached_only=True), first)
            self.assertIs(self.read(), first)
        self.assertEqual(tuple(self.store.calls), calls)

    def test_cold_cached_only_never_reads_payloads(self):
        self.rejected('daily_signal_not_available', lambda: self.read(cached_only=True))
        self.assertEqual(self.store.calls, [])
        self.assertEqual(len(self.source._cache), 0)

    def test_busy_verification_revision_cannot_reuse_readable_ordinary_revision(self):
        self.read()
        calls = tuple(self.store.calls)
        self.assertEqual(self.store.revision, 0)
        with patch.object(type(self.store), 'verification_revision', new_callable=PropertyMock, side_effect=DomainError('official_stock_invalid')) as strict:
            with patch.object(type(self.store), 'revision', new_callable=PropertyMock, create=True, return_value=0) as ordinary:
                self.rejected('official_stock_invalid', lambda: self.read(cached_only=True))
                ordinary.assert_not_called()
            self.assertEqual(strict.call_count, 1)
        self.assertEqual(tuple(self.store.calls), calls)

    def test_postcheck_verification_revision_busy_cannot_return_warmed_history(self):
        self.read()
        calls = tuple(self.store.calls)
        self.assertEqual(self.store.revision, 0)
        with patch.object(
            type(self.store), 'verification_revision', new_callable=PropertyMock, side_effect=(0, DomainError('official_stock_invalid'))
        ) as strict:
            self.rejected('official_stock_invalid', lambda: self.read(cached_only=True))
            self.assertEqual(strict.call_count, 2)
        self.assertEqual(tuple(self.store.calls), calls)

    def test_new_revision_requires_outside_lock_reverification(self):
        first = self.read()
        self.store.revision += 1
        calls = tuple(self.store.calls)
        self.rejected('daily_signal_not_available', lambda: self.read(cached_only=True))
        self.assertEqual(tuple(self.store.calls), calls)
        second = self.read()
        self.assertIsNot(second, first)
        self.assertGreater(len(self.store.calls), len(calls))
        self.assertIs(self.read(cached_only=True), second)

    def test_new_revision_rechecks_bytes_and_does_not_cache_a_failure(self):
        self.read()
        original = self.store.batch
        self.store.batch = replace(original, payloads=(replace(original.payloads[0], raw=b'corrupt'), original.payloads[1]))
        self.store.revision += 1
        self.rejected('daily_signal_source_unverified', self.read)
        self.store.batch = original
        self.assertEqual(self.read().bars, original.bars)

    def test_revision_change_during_verification_cannot_publish_cache_entry(self):
        actual = self.store.daily_history

        def history(*args):
            result = actual(*args)
            self.store.revision += 1
            return result

        with patch.object(self.store, 'daily_history', side_effect=history):
            self.rejected('daily_signal_source_unverified', self.read)
        self.assertEqual(len(self.source._cache), 0)
        self.assertEqual(self.read().bars, self.store.batch.bars)

    def test_revision_change_during_hit_is_not_returned_as_current(self):
        self.read()
        with patch.object(type(self.store), 'verification_revision', new_callable=PropertyMock, side_effect=(0, 1)):
            self.rejected('daily_signal_source_unverified', lambda: self.read(cached_only=True))

    def test_inclusive_range_and_through_are_separate_cache_identities(self):
        self.read()
        for options in ({'start': None}, {'start': fixtures.THROUGH}, {'through': fixtures.FIRST}):
            with self.subTest(options=options):
                self.rejected('daily_signal_not_available', lambda: self.read(cached_only=True, **options))
                result = self.read(**options)
                self.assertIs(self.read(cached_only=True, **options), result)

    def test_another_instrument_cannot_reuse_a_calendar_equal_cached_history(self):
        self.read()
        self.rejected(
            'daily_signal_not_available',
            lambda: self.source.history('TWSE:0050', self.calendar, through=fixtures.THROUGH, start=fixtures.FIRST, cached_only=True),
        )

    def test_calendar_actual_sessions_are_part_of_cache_identity(self):
        self.read()
        changed = replace(self.calendar, sessions=tuple(replace(row, closes_at=row.closes_at + timedelta(minutes=1)) for row in self.calendar.sessions))
        self.rejected('daily_signal_not_available', lambda: self.read(calendar=changed, cached_only=True))
        self.assertIsNot(self.read(calendar=changed), self.read())

    def test_store_replacement_cannot_inherit_equal_revision_cache(self):
        original = self.read()
        self.source.store = fixtures.CachedStore(fixtures.sample())
        self.rejected('daily_signal_not_available', lambda: self.read(cached_only=True))
        self.assertIsNot(self.read(), original)

    def test_store_replacement_during_verification_cannot_publish_old_snapshot(self):
        actual = self.store.daily_history

        def history(*args):
            result = actual(*args)
            self.source.store = fixtures.CachedStore(fixtures.sample())
            return result

        with patch.object(self.store, 'daily_history', side_effect=history):
            self.rejected('daily_signal_source_unverified', self.read)
        self.assertEqual(len(self.source._cache), 0)

    def test_lru_retains_all_sixty_account_requests_and_evicts_at_named_bound(self):
        self.assertGreaterEqual(MAX_VERIFIED_HISTORIES, 64)
        calendars = [replace(self.calendar, version=f'fixture-{index}') for index in range(MAX_VERIFIED_HISTORIES + 1)]
        for calendar in calendars:
            self.read(calendar=calendar)
        self.assertEqual(len(self.source._cache), MAX_VERIFIED_HISTORIES)
        self.rejected('daily_signal_not_available', lambda: self.read(calendar=calendars[0], cached_only=True))
        self.assertEqual(self.read(calendar=calendars[-1], cached_only=True).bars, self.store.batch.bars)

    def test_all_non_domain_port_exceptions_are_sanitized_and_not_negative_cached(self):
        for operation in ('daily_history', 'daily_coverage', 'official_payload', 'official_payload_arrival'):
            with self.subTest(operation=operation):
                source = OfficialDailyStockSource(self.store, self.clock)
                with patch.object(self.store, operation, side_effect=RuntimeError('private transport detail')):
                    error = self.rejected('daily_signal_source_unverified', lambda: self.read(source=source))
                self.assertNotIn('private transport detail', str(error))
                self.assertEqual(self.read(source=source).bars, self.store.batch.bars)

    def test_unexpected_parser_revision_and_clock_exceptions_are_sanitized(self):
        with patch('quantlab.trading.runtime.official_daily_source.parse_daily', side_effect=RuntimeError('parser failure')):
            self.rejected('daily_signal_source_unverified', self.read)
        with patch.object(type(self.store), 'verification_revision', new_callable=PropertyMock, side_effect=OSError('revision failure')):
            self.rejected('daily_signal_source_unverified', self.read)
        with patch.object(self.clock, 'now', side_effect=OverflowError('clock failure')):
            self.rejected('daily_signal_source_unverified', self.read)

    def test_deliberate_domain_errors_keep_their_published_codes(self):
        with patch.object(self.store, 'daily_history', side_effect=DomainError('official_stock_invalid')):
            self.rejected('official_stock_invalid', self.read)

    def test_process_control_base_exceptions_are_not_converted(self):
        with patch.object(self.store, 'daily_history', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.read()

    def test_observed_at_is_actual_arrival_and_does_not_follow_read_clock(self):
        expected = self.store.arrival
        first = self.read()
        self.assertEqual(first.observed_at, expected)
        self.now += timedelta(hours=2)
        self.assertEqual(self.read(cached_only=True).observed_at, expected)
        self.assertNotEqual(first.observed_at, self.now)

    def test_unknown_payload_arrival_is_not_replaced_with_read_clock(self):
        self.store.arrival = None
        self.rejected('daily_signal_source_unverified', self.read)
        self.assertEqual(len(self.source._cache), 0)

    def test_late_events_arrival_cannot_mask_daily_payload_observed_before_close(self):
        daily = self.store.batch.payloads[0]
        before_close = self.calendar.day_session(fixtures.THROUGH).closes_at - timedelta(seconds=1)
        with patch.object(self.store, 'official_payload_arrival', side_effect=lambda url, digest: before_close if url == daily.source_url else self.now):
            self.rejected('daily_signal_not_available', self.read)

    def test_latest_required_payload_arrival_is_retained_without_fabrication(self):
        daily = self.store.batch.payloads[0]
        early, later = self.store.arrival, self.store.arrival + timedelta(hours=1)
        with patch.object(self.store, 'official_payload_arrival', side_effect=lambda url, digest: early if url == daily.source_url else later):
            result = self.read()
        self.assertEqual(result.observed_at, later)

    def test_future_arrival_and_rewound_clock_fail_closed_even_on_cache_hit(self):
        self.store.arrival = self.now + timedelta(seconds=1)
        self.rejected('daily_signal_not_available', self.read)
        self.store.arrival = self.now - timedelta(seconds=1)
        self.read()
        self.now -= timedelta(seconds=2)
        self.rejected('daily_signal_not_available', lambda: self.read(cached_only=True))

    def test_payload_verification_rejects_future_arrival_before_snapshot_construction(self):
        self.store.arrival = self.now + timedelta(seconds=1)
        sessions = {row.trade_date: row for row in self.calendar.sessions}
        self.rejected('daily_signal_not_available', lambda: _verified_sources(self.store, self.store.batch, fixtures.FIRST, fixtures.END, sessions, self.now))

    def test_full_snapshot_cannot_treat_night_only_earlier_day_as_day(self):
        changed = replace(self.calendar, sessions=(replace(self.calendar.sessions[0], kind='NIGHT'), self.calendar.sessions[1]))
        self.rejected('calendar_missing', lambda: self.read(calendar=changed))

    def test_every_day_is_closed_before_payload_verification_is_attempted(self):
        future = replace(self.calendar.sessions[0], opens_at=self.now, closes_at=self.now + timedelta(seconds=1))
        calendar = replace(self.calendar, sessions=(self.calendar.sessions[1], future))
        with patch('quantlab.trading.runtime.official_daily_source._verified_sources', wraps=_verified_sources) as verify:
            self.rejected('daily_signal_not_available', lambda: self.read(calendar=calendar))
        verify.assert_not_called()

    def test_authoritative_source_rejects_wrong_previous_close_even_with_valid_payload_hashes(self):
        self.store = fixtures.CachedStore(fixtures.sample(event_rows=(['2330', '109/01/03', '1251', '1060.49'],)))
        self.source = OfficialDailyStockSource(self.store, self.clock)
        self.rejected('daily_signal_source_unverified', self.read)

    def test_conflicting_archived_previous_close_is_not_hidden_by_current_valid_facts(self):
        current = fixtures.sample(event_rows=(['2330', '109/01/03', '100', '90'],))
        old_raw = fixtures.document(fixtures.EVENT_FIELDS, [['2330', '109/01/03', '110', '90']])
        old_url = fixtures.events_url(fixtures.ID, fixtures.FIRST - timedelta(days=1), fixtures.END)
        old = OfficialPayload(old_url, sha256(old_raw).hexdigest(), old_raw)
        self.store.batch = replace(current, payloads=(*current.payloads, old))
        self.rejected('daily_signal_source_unverified', self.read)


class ActualOfficialCacheTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.now = datetime(2020, 1, 4, 2, tzinfo=timezone.utc)
        self.store = DailyStockStorage(self.db, RLock(), arrival_clock=lambda: self.now)
        self.store.import_daily(fixtures.sample())
        self.source = OfficialDailyStockSource(self.store, fixtures.SimpleNamespace(now=lambda: self.now))

    def read(self, *, cached_only=False):
        return self.source.history(fixtures.ID, fixtures.calendar(), through=fixtures.THROUGH, start=fixtures.FIRST, cached_only=cached_only)

    def test_same_connection_sql_byte_edit_invalidates_hot_cache_then_fails_verification(self):
        original = self.read()
        revision = self.store.revision
        self.db.execute('UPDATE official_stock_payloads SET raw=? WHERE source_url=?', (b'changed bytes', fixtures.sample().payloads[0].source_url))
        self.assertGreater(self.store.revision, revision)
        with self.assertRaises(DomainError) as caught:
            self.read(cached_only=True)
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')
        with self.assertRaises(DomainError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'official_stock_invalid')
        self.assertEqual(original.bars, fixtures.sample().bars)

    def test_same_connection_backup_restore_cannot_keep_a_warmed_revision(self):
        self.read()
        replacement = sqlite3.connect(':memory:')
        self.addCleanup(replacement.close)
        self.db.backup(replacement)
        replacement.execute("UPDATE bars_1d SET close='99' WHERE trade_date='2020-01-03'")
        replacement.commit()
        revision = self.store.revision
        replacement.backup(self.db)
        self.assertGreater(self.store.revision, revision)
        with self.assertRaises(DomainError) as caught:
            self.read(cached_only=True)
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')
        with self.assertRaises(DomainError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')

    def test_null_legacy_arrival_remains_unverified_even_with_valid_bytes(self):
        self.db.execute('UPDATE official_stock_payloads SET arrived_at=NULL')
        with self.assertRaises(DomainError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        self.assertEqual(len(self.source._cache), 0)


if __name__ == '__main__':
    unittest.main()
