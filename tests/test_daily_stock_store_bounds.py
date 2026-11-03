"""Explicit synthetic native-schema store fixtures; no live exchange provenance."""

from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
import unittest

import test_m2_stock_history as fixtures
from quantlab.trading.adapters.official.stock_data import StockDataSource, daily_url, events_url
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.stock_history import StockResearchInputs, months_between
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.stock_history import OfficialStockBatch


ID = 'TWSE:2330'
FIRST, END = date(2020, 1, 1), date(2020, 2, 1)
ARRIVAL = datetime(2025, 1, 3, 8, tzinfo=timezone.utc)


def make_official_batch(instrument_id, start, end, *, nonce=0, calendar=None):
    """Parse fake HTTP bytes through the actual source. A supplied calendar fixes DAY rows."""
    months = months_between(start, end)
    payloads_by_url = {}
    for month in months:
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        days = tuple(day for day in calendar.days if month <= day < next_month) if calendar is not None else (month + timedelta(days=1),)
        body = {
            'stat': 'OK',
            'fields': fixtures.FIELDS,
            'title': instrument_id.split(':')[1] + ' explicit synthetic fixture',
            'data': [[f'{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}', '1,000', '10000', '10', '10', '10', '10', '0', '1'] for day in days],
            'synthetic_refresh_nonce': nonce if month == months[-1] else 0,
        }
        payloads_by_url[daily_url(instrument_id, month)] = json.dumps(body, ensure_ascii=False).encode()
    payloads_by_url[events_url(instrument_id, start, end)] = json.dumps(
        {'stat': 'OK', 'fields': fixtures.EVENT_FIELDS, 'data': [], 'synthetic_refresh_nonce': nonce}, ensure_ascii=False
    ).encode()
    source = StockDataSource(payloads_by_url.__getitem__)
    bars, payloads = [], []
    for month in months:
        rows, payload = source.month(instrument_id, month)
        bars.extend(row for row in rows if start <= row.trade_date < end)
        payloads.append(payload)
    events, payload = source.events(instrument_id, start, end)
    return OfficialStockBatch(instrument_id, start, end, tuple(bars), events, (*payloads, payload))


def populate_six_year_refreshes(store, calendar, start, end, *, refreshes=250, instrument_id=ID):
    """One initial range then progressively earlier starts; every refresh fully covers its predecessor."""
    first = make_official_batch(instrument_id, start + timedelta(days=refreshes), end, calendar=calendar)
    store.import_daily(first)
    for nonce in range(1, refreshes + 1):
        store.import_daily(make_official_batch(instrument_id, start + timedelta(days=refreshes - nonce), end, nonce=nonce, calendar=calendar))
    current = store.daily_history(instrument_id, start, end)
    return {
        'initial': first,
        'current': current,
        'refreshes': refreshes,
        'archive_payloads': store._db.execute('SELECT COUNT(*) FROM official_stock_payloads').fetchone()[0],
        'active_manifests': store._db.execute('SELECT COUNT(*) FROM official_stock_batches WHERE instrument_id=?', (instrument_id,)).fetchone()[0],
    }


class OfficialDailyStoreBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'klines.sqlite'
        self.now = ARRIVAL
        self.store = KlineStore(self.path, arrival_clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.batch = make_official_batch(ID, FIRST, END)

    def accept(self, operation):
        try:
            return operation()
        except DomainError as error:
            self.fail('expected valid native store operation: ' + error.code)

    def reject(self, operation):
        with self.assertRaises(DomainError) as caught:
            operation()
        self.assertEqual(caught.exception.code, 'official_stock_invalid')

    def state_rows(self):
        return tuple(
            (table, self.store._db.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall())
            for table in (
                'bars_1d',
                'corporate_actions',
                'stock_cash_entitlements',
                'official_stock_payloads',
                'official_stock_batches',
                'official_stock_coverage',
                'official_stock_manifest_archive',
            )
        )

    def test_valid_official_import_reads_manifest_rowid_and_arrival(self):
        self.accept(lambda: self.store.import_daily(self.batch))
        current = self.accept(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertEqual(current.bars, self.batch.bars)
        self.assertEqual(current.payloads, tuple(sorted(self.batch.payloads, key=lambda row: (row.source_url, row.digest))))
        self.assertEqual(current.arrived_at, ARRIVAL)
        for payload in self.batch.payloads:
            self.assertEqual(self.store.official_payload_arrival(payload.source_url, payload.digest), ARRIVAL)

    def test_import_revision_is_exact_and_repeated_read_does_not_retime(self):
        self.assertEqual(self.store.revision, 0)
        self.store.import_daily(self.batch)
        self.assertEqual(self.store.revision, 1)
        self.now += timedelta(hours=1)
        current = self.store.daily_history(ID, FIRST, END)
        self.assertEqual(current.arrived_at, ARRIVAL)
        self.assertEqual(self.store.revision, 1)
        self.store.import_daily(self.batch)
        self.assertEqual(self.store.revision, 2)
        self.assertEqual(self.store.daily_history(ID, FIRST, END).arrived_at, self.now)

    def test_batch_input_arrival_never_becomes_storage_authority(self):
        self.store.import_daily(replace(self.batch, arrived_at=ARRIVAL + timedelta(days=10)))
        self.assertEqual(self.store.daily_history(ID, FIRST, END).arrived_at, ARRIVAL)

    def test_fully_superseded_manifest_is_compacted_but_old_evidence_bytes_survive(self):
        self.store.import_daily(self.batch)
        original = self.batch.payloads
        self.now += timedelta(hours=1)
        new = make_official_batch(ID, FIRST, END, nonce=1)
        self.store.import_daily(new)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM official_stock_batches').fetchone()[0], 1)
        self.assertEqual(set(self.store.daily_history(ID, FIRST, END).payloads), set(new.payloads))
        for payload in original:
            self.assertEqual(self.store.official_payload(payload.source_url, payload.digest), payload)

    def test_external_and_same_connection_mutations_invalidate_revision(self):
        self.store.import_daily(self.batch)
        before = self.store.revision
        with closing(sqlite3.connect(self.path)) as other:
            other.execute("UPDATE official_stock_payloads SET raw=? WHERE digest=?", (b'corrupt', self.batch.payloads[0].digest))
            other.commit()
        self.assertGreater(self.store.revision, before)
        before = self.store.revision
        self.store._db.execute("UPDATE official_stock_payloads SET raw=? WHERE digest=?", (b'also-corrupt', self.batch.payloads[1].digest))
        self.assertGreater(self.store.revision, before)
        with self.assertRaises(DomainError):
            self.store.daily_history(ID, FIRST, END)

    def test_revision_rejects_a_busy_import_lock_instead_of_returning_old_authority(self):
        self.store.import_daily(self.batch)
        acquired, release = Event(), Event()

        def hold():
            with self.store._lock:
                acquired.set()
                release.wait(2)

        thread = Thread(target=hold)
        thread.start()
        self.assertTrue(acquired.wait(1))
        started = monotonic()
        try:
            self.reject(lambda: self.store.verification_revision)
            self.assertLess(monotonic() - started, 0.2)
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_ordinary_revision_waits_for_import_lock_and_returns_fresh_shared_counter(self):
        self.store.import_daily(self.batch)
        entered, finished = Event(), Event()
        result, errors = [], []

        def read_revision():
            entered.set()
            try:
                result.append(self.store.revision)
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        thread = Thread(target=read_revision)
        try:
            with self.store._lock:
                thread.start()
                self.assertTrue(entered.wait(1))
                self.assertFalse(finished.wait(0.05))
                self.store.import_daily(self.batch)
        finally:
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result, [2])
        self.assertEqual(self.store.verification_revision, result[0])

    def test_verification_and_ordinary_revision_observe_the_same_mutation_counter(self):
        self.store.import_daily(self.batch)
        self.assertEqual((self.store.revision, self.store.verification_revision), (1, 1))
        self.store._db.execute('UPDATE official_stock_payloads SET arrived_at=NULL')
        self.assertEqual(self.store.verification_revision, 2)
        self.assertEqual(self.store.revision, 2)
        self.store._db.execute('UPDATE official_stock_payloads SET arrived_at=NULL')
        self.assertEqual(self.store.revision, 3)
        self.assertEqual(self.store.verification_revision, 3)

    def test_minute_mutation_revision_and_benign_metadata_keep_existing_semantics(self):
        import test_kline_store as minute_fixture

        self.assertEqual(self.store.revision, 0)
        self.store.upsert((minute_fixture.minute(),))
        self.assertEqual(self.store.revision, 1)
        self.store.mark_coverage(ID, minute_fixture.START, minute_fixture.START + timedelta(minutes=1))
        self.store.record_queried_bars(minute_fixture.START.date(), 1)
        self.assertEqual(self.store.revision, 1)
        self.store.upsert(())
        self.assertEqual(self.store.revision, 1)
        self.store.upsert((minute_fixture.minute(),))
        self.assertEqual(self.store.revision, 2)

    def test_benign_metadata_cannot_launder_an_unregistered_payload_rewrite(self):
        self.store.import_daily(self.batch)
        before = self.store.revision
        self.store._db.execute("UPDATE official_stock_payloads SET raw=? WHERE digest=?", (b'corrupt', self.batch.payloads[0].digest))
        self.store.record_queried_bars(FIRST, 1)
        self.assertGreater(self.store.revision, before)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))

    def test_only_fully_covered_manifests_are_removed(self):
        self.store.import_daily(self.batch)
        narrower = make_official_batch(ID, FIRST + timedelta(days=1), END, nonce=1)
        self.store.import_daily(narrower)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM official_stock_batches').fetchone()[0], 2)
        self.assertTrue(set(self.batch.payloads) <= set(self.store.daily_history(ID, FIRST, END).payloads))

    def test_failed_publication_does_not_advance_revision_or_change_old_data(self):
        self.store.import_daily(self.batch)
        for offset in range(241):
            start = date(1900, 1, 1) + timedelta(days=offset * 2)
            self.store._db.execute(
                'INSERT INTO official_stock_batches(instrument_id,start_date,end_date,sources,arrived_at) VALUES(?,?,?,?,?)',
                (
                    ID,
                    start.isoformat(),
                    (start + timedelta(days=1)).isoformat(),
                    json.dumps([(p.source_url, p.digest) for p in self.batch.payloads]),
                    ARRIVAL.isoformat(),
                ),
            )
        self.store._db.commit()
        before, revision = self.state_rows(), self.store.revision
        february = make_official_batch(ID, END, date(2020, 3, 1))
        self.reject(lambda: self.store.import_daily(february))
        self.assertEqual(self.state_rows(), before)
        self.assertEqual(self.store.revision, revision)

    def test_history_manifest_count_is_checked_before_any_payload_blob_read(self):
        self.store.import_daily(self.batch)
        for offset in range(243):
            start, end = FIRST - timedelta(days=offset), END + timedelta(days=offset)
            self.store._db.execute(
                'INSERT OR REPLACE INTO official_stock_batches(instrument_id,start_date,end_date,sources) VALUES(?,?,?,?)',
                (ID, start.isoformat(), end.isoformat(), json.dumps([(p.source_url, p.digest) for p in self.batch.payloads])),
            )
        self.store._db.commit()
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT source_url,digest,raw' in sql or 'SELECT raw FROM' in sql for sql in traced))

    def test_oversized_manifest_text_is_not_loaded_before_its_length_is_checked(self):
        self.store.import_daily(self.batch)
        oversized = json.dumps([[self.batch.payloads[0].source_url + 'x' * (128 * 1024), self.batch.payloads[0].digest]])
        self.store._db.execute('UPDATE official_stock_batches SET sources=?', (oversized,))
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT sources FROM official_stock_batches WHERE rowid' in sql for sql in traced))

    def test_legacy_arrival_is_unknown_after_schema_upgrade_not_backfilled_now(self):
        path = Path(self.temp.name) / 'legacy.sqlite'
        with closing(KlineStore(path, arrival_clock=lambda: ARRIVAL)) as original:
            original.import_daily(self.batch)
        with closing(sqlite3.connect(path)) as old:
            old.execute('ALTER TABLE official_stock_payloads DROP COLUMN arrived_at')
            old.execute('ALTER TABLE official_stock_batches DROP COLUMN arrived_at')
            old.commit()
        with closing(KlineStore(path, arrival_clock=lambda: ARRIVAL + timedelta(days=30))) as reopened:
            current = reopened.daily_history(ID, FIRST, END)
            self.assertEqual(current.bars, self.batch.bars)
            self.assertIsNone(current.arrived_at)
            for payload in self.batch.payloads:
                self.assertIsNone(reopened.official_payload_arrival(payload.source_url, payload.digest))

    def test_per_payload_arrival_remains_independent_of_another_later_response(self):
        self.store.import_daily(self.batch)
        early = self.batch.payloads[0]
        self.now += timedelta(days=1)
        later = make_official_batch(ID, END, date(2020, 3, 1))
        self.store.import_daily(later)
        self.assertEqual(self.store.official_payload_arrival(early.source_url, early.digest), ARRIVAL)
        self.assertEqual(self.store.daily_history(ID, FIRST, date(2020, 3, 1)).arrived_at, self.now)

    def test_corrupt_arrival_is_not_replaced_with_read_clock(self):
        self.store.import_daily(self.batch)
        self.store._db.execute("UPDATE official_stock_payloads SET arrived_at='2025-01-03T08:00:00'")
        for payload in self.batch.payloads:
            self.reject(lambda: self.store.official_payload_arrival(payload.source_url, payload.digest))
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))

    def test_six_year_250_refreshes_bound_active_sources_but_keep_all_old_payloads(self):
        result = populate_six_year_refreshes(self.store, None, date(2019, 1, 1), date(2025, 1, 1))
        self.assertEqual(result['active_manifests'], 1)
        self.assertEqual(len(result['current'].payloads), 73)
        self.assertEqual(result['archive_payloads'], 573)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM official_stock_manifest_archive').fetchone()[0], 251)
        for payload in result['initial'].payloads:
            self.assertEqual(self.store.official_payload(payload.source_url, payload.digest), payload)

    def archive_refreshes(self, count):
        for nonce in range(count):
            self.store.import_daily(make_official_batch(ID, FIRST, END, nonce=nonce))
        return self.store._db.execute('SELECT source_url,digest FROM official_stock_payloads ORDER BY source_url,digest').fetchall()

    def test_history_distinct_source_union_is_bounded_before_blob_loading(self):
        keys = self.archive_refreshes(122)
        self.assertEqual(len(keys), 244)
        self.store._db.execute('DELETE FROM official_stock_batches')
        for offset, part in enumerate((keys[:122], keys[122:])):
            self.store._db.execute(
                'INSERT INTO official_stock_batches(instrument_id,start_date,end_date,sources) VALUES(?,?,?,?)',
                (ID, (FIRST + timedelta(days=offset)).isoformat(), END.isoformat(), json.dumps(part)),
            )
        self.store._db.commit()
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT source_url,digest,raw' in sql or 'SELECT raw FROM' in sql for sql in traced))

    def test_single_manifest_source_count_cannot_bypass_the_union_budget(self):
        self.store.import_daily(self.batch)
        pairs = [(payload.source_url, payload.digest) for payload in self.batch.payloads] * 122
        self.store._db.execute('UPDATE official_stock_batches SET sources=?', (json.dumps(pairs),))
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT source_url,digest,raw' in sql for sql in traced))

    def test_aggregate_payload_bytes_are_checked_before_any_blob_is_read(self):
        keys = self.archive_refreshes(5)
        self.store._db.execute('DELETE FROM official_stock_batches')
        self.store._db.execute(
            'INSERT INTO official_stock_batches(instrument_id,start_date,end_date,sources) VALUES(?,?,?,?)',
            (ID, FIRST.isoformat(), END.isoformat(), json.dumps(keys[:9])),
        )
        for url, digest in keys[:9]:
            self.store._db.execute('UPDATE official_stock_payloads SET raw=zeroblob(?) WHERE source_url=? AND digest=?', (8 * 1024 * 1024, url, digest))
        self.store._db.commit()
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT source_url,digest,raw' in sql for sql in traced))

    def test_partially_covered_manifest_end_is_preserved(self):
        self.store.import_daily(self.batch)
        self.store.import_daily(make_official_batch(ID, FIRST, date(2020, 1, 15), nonce=1))
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM official_stock_batches').fetchone()[0], 2)
        self.assertTrue(set(self.batch.payloads) <= set(self.store.daily_history(ID, FIRST, END).payloads))

    def test_saved_evidence_reconstructs_exact_original_parser_inputs_after_compaction(self):
        self.store.import_daily(self.batch)
        original = StockResearchInputs(self.batch, FeeSchedule.taiwan(), 'explicit-synthetic-calendar').evidence()
        self.store.import_daily(make_official_batch(ID, FIRST, END, nonce=1))
        evidence = dict(original)
        references = json.loads(evidence['official_sources'])
        raw_by_url = {url: self.accept(lambda url=url, digest=digest: self.store.official_payload(url, digest)).raw for url, digest in references}
        source = StockDataSource(raw_by_url.__getitem__)
        bars, daily = source.month(ID, FIRST)
        events, event = source.events(ID, FIRST, END)
        restored = OfficialStockBatch(ID, FIRST, END, bars, events, (daily, event))
        self.assertEqual(StockResearchInputs(restored, FeeSchedule.taiwan(), 'explicit-synthetic-calendar').evidence(), original)

    def test_rejected_refresh_rolls_back_arrivals_compaction_and_coverage(self):
        self.store.import_daily(self.batch)
        before = self.state_rows()
        self.now += timedelta(days=1)
        self.store._db.execute("CREATE TRIGGER reject_new_bar BEFORE INSERT ON bars_1d BEGIN SELECT RAISE(ABORT, 'rejected'); END")
        self.reject(lambda: self.store.import_daily(make_official_batch(ID, FIRST, END, nonce=1)))
        self.assertEqual(self.state_rows(), before)
        self.assertEqual(self.store.daily_history(ID, FIRST, END).arrived_at, ARRIVAL)

    def test_payload_arrival_survives_reopen_without_consulting_a_new_clock(self):
        path = Path(self.temp.name) / 'reopened.sqlite'
        with closing(KlineStore(path, arrival_clock=lambda: ARRIVAL)) as initial:
            initial.import_daily(self.batch)
        with closing(KlineStore(path, arrival_clock=lambda: ARRIVAL + timedelta(days=30))) as reopened:
            self.assertEqual(reopened.daily_history(ID, FIRST, END).arrived_at, ARRIVAL)
            for payload in self.batch.payloads:
                self.assertEqual(reopened.official_payload_arrival(payload.source_url, payload.digest), ARRIVAL)

    def test_empty_or_missing_payload_arrival_remains_unknown(self):
        self.store.import_daily(self.batch)
        missing = ('https://www.twse.com.tw/missing', 'f' * 64)
        self.assertIsNone(self.store.official_payload_arrival(*missing))
        self.store._db.execute('UPDATE official_stock_payloads SET arrived_at=NULL WHERE digest=?', (self.batch.payloads[0].digest,))
        self.assertIsNone(self.accept(lambda: self.store.daily_history(ID, FIRST, END)).arrived_at)

    def test_revision_on_closed_store_is_a_typed_refusal_not_cached_authority(self):
        path = Path(self.temp.name) / 'closed.sqlite'
        closed = KlineStore(path)
        closed.close()
        self.reject(lambda: closed.revision)

    def test_revision_metadata_probe_never_waits_for_external_sqlite_lock(self):
        self.store.import_daily(self.batch)
        self.store._db.execute('PRAGMA journal_mode=DELETE')
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=0)) as other:
            other.execute('BEGIN EXCLUSIVE')
            started = monotonic()
            try:
                self.reject(lambda: self.store.verification_revision)
                self.assertLess(monotonic() - started, 0.2)
            finally:
                other.rollback()
        self.assertEqual(self.store._db.execute('PRAGMA busy_timeout').fetchone()[0], 2000)
        self.assertIsInstance(self.store.revision, int)

    def test_enclosing_refresh_removes_old_range_manifest_with_a_different_primary_key(self):
        self.store.import_daily(self.batch)
        earlier = FIRST - timedelta(days=1)
        widened = make_official_batch(ID, earlier, END, nonce=1)
        self.store.import_daily(widened)
        rows = self.store._db.execute('SELECT start_date,end_date FROM official_stock_batches').fetchall()
        self.assertEqual(rows, [(earlier.isoformat(), END.isoformat())])
        self.assertEqual(set(self.store.daily_history(ID, FIRST, END).payloads), set(widened.payloads))

    def source_digest(self, payloads):
        pairs = sorted({(payload.source_url, payload.digest) for payload in payloads})
        return sha256(json.dumps(pairs, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

    def test_same_range_replace_archives_original_full_row_before_compaction(self):
        self.store.import_daily(self.batch)
        row = self.store._db.execute('SELECT instrument_id,start_date,end_date,sources,arrived_at FROM official_stock_batches').fetchone()
        old_digest = self.source_digest(self.batch.payloads)
        self.now += timedelta(days=1)
        self.store.import_daily(make_official_batch(ID, FIRST, END, nonce=1))
        archived = self.accept(lambda: self.store.official_manifest_archive(old_digest))
        self.assertEqual(len(archived), 1)
        self.assertEqual((archived[0].instrument_id, archived[0].start, archived[0].end, archived[0].arrived_at), (ID, FIRST, END, ARRIVAL))
        self.assertEqual(archived[0].source_digest, old_digest)
        saved = self.store._db.execute(
            'SELECT instrument_id,start_date,end_date,sources,arrived_at FROM official_stock_manifest_archive WHERE archive_id=?', (archived[0].archive_id,)
        ).fetchone()
        self.assertEqual(saved, row)
        self.assertEqual(archived[0].sources, tuple(tuple(pair) for pair in json.loads(row[3])))

    def test_archival_of_old_database_manifest_keeps_unknown_arrival(self):
        path = Path(self.temp.name) / 'legacy-archive.sqlite'
        with closing(KlineStore(path, arrival_clock=lambda: ARRIVAL)) as old:
            old.import_daily(self.batch)
        with closing(sqlite3.connect(path)) as legacy:
            legacy.execute('DROP TABLE official_stock_manifest_archive')
            legacy.execute('ALTER TABLE official_stock_batches DROP COLUMN arrived_at')
            legacy.execute('ALTER TABLE official_stock_payloads DROP COLUMN arrived_at')
            legacy.commit()
        with closing(KlineStore(path, arrival_clock=lambda: ARRIVAL + timedelta(days=30))) as updated:
            updated.import_daily(make_official_batch(ID, FIRST, END, nonce=1))
            archived = updated.official_manifest_archive(self.source_digest(self.batch.payloads))
            self.assertEqual(len(archived), 1)
            self.assertIsNone(archived[0].arrived_at)
            self.assertEqual(archived[0].sources, tuple(sorted((payload.source_url, payload.digest) for payload in self.batch.payloads)))

    def test_identical_source_sets_at_distinct_actual_arrivals_are_not_overwritten(self):
        self.store.import_daily(self.batch)
        first = self.accept(lambda: self.store.official_manifest_archive(self.source_digest(self.batch.payloads)))
        self.assertEqual(len(first), 1)
        self.now += timedelta(days=1)
        self.store.import_daily(self.batch)
        records = self.accept(lambda: self.store.official_manifest_archive(self.source_digest(self.batch.payloads)))
        self.assertEqual({row.arrived_at for row in records}, {ARRIVAL, self.now})
        self.assertIn(first[0], records)
        self.assertEqual(len({row.archive_id for row in records}), 2)

    def test_history_reads_do_not_append_or_modify_archive(self):
        self.store.import_daily(self.batch)
        before = self.state_rows()
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.store.daily_history(ID, FIRST, END)
        self.store.official_manifest_archive(self.source_digest(self.batch.payloads))
        self.assertTrue(traced)
        self.assertTrue(all(sql.lstrip().upper().startswith('SELECT') for sql in traced))
        self.assertEqual(self.state_rows(), before)

    def test_union_source_digest_is_not_guessed_as_a_single_archived_manifest(self):
        self.store.import_daily(self.batch)
        self.store.import_daily(make_official_batch(ID, FIRST + timedelta(days=1), END, nonce=1))
        current = self.store.daily_history(ID, FIRST, END)
        self.assertGreater(len(current.payloads), len(self.batch.payloads))
        self.assertEqual(self.store.official_manifest_archive(self.source_digest(current.payloads)), ())
        self.assertEqual(len(self.store.official_manifest_archive(self.source_digest(self.batch.payloads))), 1)

    def test_archive_integrity_rejects_rewritten_metadata_under_the_original_digest(self):
        self.store.import_daily(self.batch)
        digest = self.source_digest(self.batch.payloads)
        self.store._db.execute("UPDATE official_stock_manifest_archive SET sources='[]'")
        self.reject(lambda: self.store.official_manifest_archive(digest))

    def test_archive_keeps_exact_legacy_json_even_when_canonical_source_set_is_unchanged(self):
        self.store.import_daily(self.batch)
        pairs = [(payload.source_url, payload.digest) for payload in self.batch.payloads]
        original = json.dumps([pairs[1], pairs[0], pairs[0]], indent=1)
        self.store._db.execute('UPDATE official_stock_batches SET sources=?', (original,))
        self.store._db.commit()
        self.store.import_daily(make_official_batch(ID, FIRST, END, nonce=1))
        records = self.store.official_manifest_archive(self.source_digest(self.batch.payloads))
        self.assertEqual(len(records), 2)
        self.assertTrue(any(row.sources == (pairs[1], pairs[0], pairs[0]) for row in records))
        self.assertIn((original,), self.store._db.execute('SELECT sources FROM official_stock_manifest_archive').fetchall())

    def test_archive_lookup_rejects_invalid_digest_and_does_not_fabricate_missing_records(self):
        self.reject(lambda: self.store.official_manifest_archive('not-a-digest'))
        self.assertEqual(self.store.official_manifest_archive('f' * 64), ())

    def test_malformed_legacy_manifest_refuses_import_with_a_typed_atomic_error(self):
        self.store.import_daily(self.batch)
        self.store._db.execute("UPDATE official_stock_batches SET sources='{bad'")
        self.store._db.commit()
        before, revision = self.state_rows(), self.store.revision
        try:
            self.store.import_daily(make_official_batch(ID, FIRST, END, nonce=1))
        except (DomainError, ValueError, TypeError, ArithmeticError) as error:
            self.assertIsInstance(error, DomainError, 'disk parse errors must cross the typed storage boundary')
            self.assertEqual(error.code, 'official_stock_invalid')
        else:
            self.fail('malformed legacy manifest was published')
        self.assertEqual(self.state_rows(), before)
        self.assertEqual(self.store.revision, revision)

    def test_single_payload_size_is_checked_before_loading_its_blob(self):
        self.store.import_daily(self.batch)
        self.store._db.execute('UPDATE official_stock_payloads SET raw=zeroblob(?) WHERE digest=?', (8 * 1024 * 1024 + 1, self.batch.payloads[0].digest))
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT source_url,digest,raw' in sql for sql in traced))

    def test_revision_detects_actual_same_connection_sqlite_backup_restore(self):
        self.store.import_daily(self.batch)
        revision = self.store.revision
        with closing(sqlite3.connect(Path(self.temp.name) / 'restore.sqlite')) as clone:
            self.store._db.backup(clone)
            clone.execute("UPDATE official_stock_payloads SET raw=? WHERE digest=?", (b'corrupt', self.batch.payloads[0].digest))
            clone.commit()
            clone.backup(self.store._db)
        self.assertGreater(self.store.revision, revision)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))

    def test_archive_mutations_use_append_only_insert_ignore_never_replace_update_or_delete(self):
        self.store.import_daily(self.batch)
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.store.import_daily(self.batch)
        writes = [
            sql for sql in traced if 'official_stock_manifest_archive' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE'))
        ]
        self.assertTrue(writes)
        self.assertTrue(all(sql.lstrip().upper().startswith('INSERT OR IGNORE INTO OFFICIAL_STOCK_MANIFEST_ARCHIVE') for sql in writes))

    def test_payload_byte_budget_counts_utf8_even_if_corrupt_sqlite_storage_is_text(self):
        self.store.import_daily(self.batch)
        self.store._db.execute('UPDATE official_stock_payloads SET raw=? WHERE digest=?', ('台' * (3 * 1024 * 1024), self.batch.payloads[0].digest))
        traced = []
        self.store._db.set_trace_callback(traced.append)
        self.reject(lambda: self.store.daily_history(ID, FIRST, END))
        self.assertFalse(any('SELECT source_url,digest,raw' in sql for sql in traced))
