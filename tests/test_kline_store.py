"""Offline persistence, successful-query coverage and recovery contracts."""

from dataclasses import replace
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
import unittest.mock

from quantlab.trading.adapters.storage import kline_store as kline_store_module
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.validation import DomainError

START = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)


def minute(offset=0, close='10.123456789123456789'):
    start = START + timedelta(minutes=offset)
    price = Decimal(close)
    return LiveBar('TWSE:2330', start, start + timedelta(minutes=1), date(2026, 10, 30), 'REGULAR', price, price, price, price, 12, final=True)


class KlineStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'market' / 'klines.sqlite3'
        self.store = KlineStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_minute_extent_gives_first_last_and_coverage_end_without_counting(self):
        self.assertIsNone(self.store.minute_extent('TWSE:2330'))
        self.store.upsert((minute(0), minute(5), minute(2)))
        extent = self.store.minute_extent('TWSE:2330')
        self.assertEqual(extent[:2], (minute(0).start, minute(5).start))
        self.assertIsNone(extent[2])  # nothing marked as covered yet
        self.store.mark_coverage('TWSE:2330', minute(0).start, minute(5).end)
        self.assertEqual(self.store.minute_extent('TWSE:2330')[2], minute(5).end)
        self.assertIsNone(self.store.minute_extent('TWSE:2317'))

    def vm_steps(self, instrument_id):
        steps = []
        self.store._db.set_progress_handler(lambda: steps.append(1) and 0, 1)
        try:
            self.store.minute_extent(instrument_id)
        finally:
            self.store._db.set_progress_handler(None, 0)
        return len(steps)

    def test_minute_extent_does_constant_work_however_many_bars_an_instrument_has(self):
        self.store.upsert(tuple(replace(minute(offset), instrument_id='TWSE:1101') for offset in range(2000)))
        small = self.vm_steps('TWSE:1101')
        self.store.upsert(tuple(replace(minute(offset), instrument_id='TWSE:1101') for offset in range(2000, 20000)))
        large = self.vm_steps('TWSE:1101')
        self.assertLess(small, 200)  # a pair of index seeks, not a walk over 2,000 rows
        self.assertLessEqual(large, small + 20)  # ten times the rows, the same work

    def test_instrument_ids_match_the_full_union_scan_for_minute_and_daily_rows(self):
        self.assertEqual(self.store.instrument_ids(), ())
        for instrument, offsets in (('TWSE:2330', range(5)), ('TPEX:6488', range(3)), ('INDEX:IX0001', range(2)), ('TWSE:1101', range(1))):
            self.store.upsert(tuple(replace(minute(offset), instrument_id=instrument) for offset in offsets))
        with self.store._db:
            for instrument in ('TWSE:2330', 'TWSE:0050', 'TWSE:9999'):
                self.store._db.execute('INSERT INTO bars_1d VALUES(?,?,?,?,?,?,?,?,?)', (instrument, '2026-10-29', '1', '1', '1', '1', 1, 'digest', 'OFFICIAL'))
        union = tuple(
            row[0] for row in self.store._db.execute('SELECT instrument_id FROM bars_1m UNION SELECT instrument_id FROM bars_1d ORDER BY instrument_id')
        )
        self.assertEqual(self.store.instrument_ids(), union)
        self.assertEqual(union, ('INDEX:IX0001', 'TPEX:6488', 'TWSE:0050', 'TWSE:1101', 'TWSE:2330', 'TWSE:9999'))

    def test_decimal_roundtrip_sorted_half_open_read_and_last(self):
        self.store.upsert((minute(2), minute(0), minute(1)))
        self.assertEqual(self.store.read('TWSE:2330', START, START + timedelta(minutes=2)), (minute(0), minute(1)))
        self.assertEqual(self.store.last_bar('TWSE:2330'), minute(2))
        self.assertIsNone(self.store.last_bar('TWSE:9999'))
        self.store.close()
        self.store = KlineStore(self.path)
        self.assertEqual(self.store.last_bar('TWSE:2330').close, Decimal('10.123456789123456789'))

    def test_repeated_reads_decode_only_new_or_upserted_rows_and_match_a_fresh_store(self):
        import quantlab.trading.adapters.storage.kline_store as module

        self.store.upsert(tuple(minute(offset) for offset in range(10)), source='LIVE_TICKS')
        hour = timedelta(hours=1)
        self.assertEqual(len(self.store.read_cached('TWSE:2330', START, START + hour)), 10)
        decoded = []
        original = module._decode

        def counting(row):
            decoded.append(row[1])
            return original(row)

        with unittest.mock.patch.object(module, '_decode', counting):
            # Nothing changed: the sliding window decodes nothing again.
            self.assertEqual(len(self.store.read_cached('TWSE:2330', START, START + hour + timedelta(seconds=5))), 10)
            self.assertEqual(decoded, [])
            # An official correction of an old bar and a new bar: only rows from the corrected bar on are decoded.
            self.store.upsert((minute(3, close='20'),))
            self.store.upsert((minute(10, close='21'),), source='LIVE_TICKS')
            # A live bar never replaces an official one; the read must still show the official price.
            self.store.upsert((minute(3, close='30'),), source='LIVE_TICKS')
            bars = self.store.read_cached('TWSE:2330', START + timedelta(minutes=1), START + hour + timedelta(seconds=10))
            self.assertEqual(len(decoded), 8)
        self.assertEqual([bar.start for bar in bars], [minute(offset).start for offset in range(1, 11)])
        self.assertEqual(bars[2].close, Decimal('20'))
        self.assertEqual(bars[-1].close, Decimal('21'))
        # A range ending earlier than the cached one is a plain read; every answer equals a fresh store's.
        # A narrow read that ends before a later correction keeps that correction pending for the next wide read.
        self.store.upsert((minute(8, close='40'),))
        self.assertEqual(len(self.store.read_cached('TWSE:2330', START, START + timedelta(minutes=5))), 5)
        self.assertEqual(self.store.read_cached('TWSE:2330', START, START + hour + timedelta(seconds=20))[8].close, Decimal('40'))
        with closing(KlineStore(self.path)) as fresh:
            self.assertEqual(
                self.store.read_cached('TWSE:2330', START, START + timedelta(minutes=4)), fresh.read('TWSE:2330', START, START + timedelta(minutes=4))
            )
            self.assertEqual(self.store.read_cached('TWSE:2330', START, START + hour), fresh.read('TWSE:2330', START, START + hour))

    def test_cached_reads_evict_oldest_with_pending_upserts_and_plain_reads_never_fill_the_cache(self):
        hour = timedelta(hours=1)

        def bars(code, offsets, close='10'):
            return tuple(replace(minute(offset, close), instrument_id='TWSE:' + code) for offset in offsets)

        codes = [str(2300 + index) for index in range(7)]
        for code in codes:
            self.store.upsert(bars(code, range(3)), source='LIVE_TICKS')
        self.store.read('TWSE:' + codes[0], START, START + hour)
        self.assertEqual(self.store._recent, {})
        for code in codes:
            self.store.read_cached('TWSE:' + code, START, START + hour)
            # Every cached instrument keeps receiving live minutes, as during market hours.
            for other in codes:
                self.store.upsert(bars(other, (3,), close='11'), source='LIVE_TICKS')
        self.assertLessEqual(len(self.store._recent), 4)
        self.assertTrue(set(self.store._dirty) <= set(self.store._recent))
        with closing(KlineStore(self.path)) as fresh:
            for code in codes:
                self.assertEqual(self.store.read_cached('TWSE:' + code, START, START + hour), fresh.read('TWSE:' + code, START, START + hour))

    def test_official_history_overwrites_live_and_live_cannot_overwrite_official(self):
        self.store.upsert((minute(close='11'),), source='LIVE_TICKS')
        self.store.upsert((minute(close='12'),), source='SHIOAJI_KBARS')
        self.store.upsert((minute(close='13'),), source='LIVE_TICKS')
        self.assertEqual(self.store.last_bar('TWSE:2330').close, Decimal('12'))
        self.store.upsert((minute(close='14'),))
        self.assertEqual(self.store.last_bar('TWSE:2330').close, Decimal('14'))

    def test_coverage_includes_empty_holidays_and_merges_adjacency(self):
        day = timedelta(days=1)
        self.store.mark_coverage('TWSE:2330', START + day, START + day * 2)
        self.store.mark_coverage('TWSE:2330', START + day * 3, START + day * 4)
        self.assertEqual(
            self.store.missing_ranges('TWSE:2330', START, START + day * 5),
            ((START, START + day), (START + day * 2, START + day * 3), (START + day * 4, START + day * 5)),
        )
        self.store.mark_coverage('TWSE:2330', START + day * 2, START + day * 3)
        self.store.mark_coverage('TWSE:2330', START, START + day)
        self.assertEqual(self.store.missing_ranges('TWSE:2330', START, START + day * 4), ())
        self.assertEqual(self.store.read('TWSE:2330', START, START + day * 4), ())
        self.assertEqual(self.store.missing_ranges('TWSE:9999', START, START + day), ((START, START + day),))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM coverage').fetchone(), (1,))

    def test_query_counter_is_durable_and_scoped_to_day(self):
        self.store.record_queried_bars(START.date(), 12)
        self.store.record_queried_bars(START.date(), 3)
        self.store.close()
        self.store = KlineStore(self.path)
        self.assertEqual(self.store.queried_bars(START.date()), 15)
        self.assertEqual(self.store.queried_bars(START.date() + timedelta(days=1)), 0)

    def test_corruption_preserved_and_rebuilt_with_warning(self):
        self.store.close()
        self.path.write_bytes(b'not a database; preserve these user bytes')
        self.store = KlineStore(self.path)
        self.assertEqual(self.store.warning_code, 'kline_store_unavailable')
        self.assertEqual(self.store.recovered_path.read_bytes(), b'not a database; preserve these user bytes')
        self.assertIsNone(self.store.last_bar('TWSE:2330'))
        self.store.upsert((minute(),))
        self.assertEqual(self.store.last_bar('TWSE:2330'), minute())

    def test_unknown_schema_preserves_existing_user_data(self):
        self.store.upsert((minute(),))
        self.store.close()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
            db.commit()
        self.store = KlineStore(self.path)
        with closing(sqlite3.connect(self.store.recovered_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM bars_1m').fetchone(), (1,))
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone(), ('99',))

    def test_input_boundary_rejects_forming_nan_float_naive_and_bad_ohlc_atomically(self):
        invalid = (
            replace(minute(), final=False),
            replace(minute(), incomplete=True),
            replace(minute(), open=Decimal('NaN')),
            replace(minute(), close=10.0),
            replace(minute(), start=START.replace(tzinfo=None)),
            replace(minute(), high=Decimal('1')),
            replace(minute(), volume=True),
            replace(minute(), end=START + timedelta(minutes=2)),
        )
        for bar in invalid:
            with self.subTest(bar=bar), self.assertRaises(DomainError):
                self.store.upsert((minute(1), bar))
        self.assertIsNone(self.store.last_bar('TWSE:2330'))

    def test_utc_normalization_keeps_offsets_from_creating_duplicate_minutes(self):
        taipei = timezone(timedelta(hours=8))
        bar = minute()
        local = replace(bar, start=bar.start.astimezone(taipei), end=bar.end.astimezone(taipei))
        self.store.upsert((local, bar))
        self.assertEqual(self.store.read('TWSE:2330', START, START + timedelta(minutes=1)), (bar,))

    def test_live_bar_does_not_claim_query_coverage(self):
        self.store.upsert((minute(),), source='LIVE_TICKS')
        self.assertEqual(self.store.missing_ranges('TWSE:2330', START, START + timedelta(minutes=1)), ((START, START + timedelta(minutes=1)),))

    @staticmethod
    def sdk_minutes(instrument_id, opening, day, count, seed):
        """`count` minutes from `opening` in one trade date, priced as the SDK's float text ('2012.25', '2035.0')."""
        bars = []
        for index in range(count):
            start = opening + timedelta(minutes=index * 3)
            base = round(2000 + (index * 37 + seed) % 101 * 0.25, 2)
            first, last = base, round(base + (index % 7 - 3) * 0.5, 2)
            prices = [Decimal(repr(value)) for value in (first, max(first, last) + (index % 3), min(first, last) - (index % 4) * 0.25, last)]
            session = 'NIGHT' if start.astimezone(timezone(timedelta(hours=8))).hour >= 15 else 'DAY'
            bars.append(LiveBar(instrument_id, start, start + timedelta(minutes=1), day, session, *prices, 1 + index % 9, final=True))
        return tuple(bars)

    def test_read_daily_equals_aggregating_the_stored_minutes_of_each_trade_date(self):
        from quantlab.trading.domain.live_bars import aggregate_bars

        night = datetime(2026, 11, 18, 7, tzinfo=timezone.utc)  # 15:00 in Taipei: the night session of the 19th opens
        stored = (
            *self.sdk_minutes('TAIFEX:TXFR1', night, date(2026, 11, 19), 400, 1),
            *self.sdk_minutes('TAIFEX:TXFR1', night + timedelta(days=1), date(2026, 11, 20), 400, 5),
            *self.sdk_minutes('TWSE:2330', night, date(2026, 11, 19), 50, 9),
        )
        self.store.upsert(stored)
        start, end = night + timedelta(minutes=30), night + timedelta(days=1, minutes=600)
        daily = self.store.read_daily('TAIFEX:TXFR1', start, end)
        minutes = self.store.read('TAIFEX:TXFR1', start, end)
        groups = {}
        for bar in minutes:
            groups.setdefault(bar.trade_date, []).append(bar)
        expected = tuple(aggregate_bars(tuple(members), '1d', now=end, trade_date_closed=True)[0] for members in groups.values())
        self.assertEqual(len(daily), 2)
        self.assertEqual(daily, expected)
        # The SDK's float text comes back as the very same text, so a chart shows the stored digits.
        self.assertEqual(
            [tuple(map(str, (bar.open, bar.high, bar.low, bar.close))) for bar in daily],
            [tuple(map(str, (bar.open, bar.high, bar.low, bar.close))) for bar in expected],
        )
        self.assertEqual({bar.session for bar in daily}, {'ALL'})
        self.assertEqual(self.store.read_daily('TWSE:2317', start, end), ())

    def test_read_daily_compares_extremes_as_numbers_not_text(self):
        def at(offset, opening, high, low, closing):
            start = START + timedelta(minutes=offset)
            return LiveBar(
                'TWSE:2330', start, start + timedelta(minutes=1), date(2026, 10, 30), 'DAY', *map(Decimal, (opening, high, low, closing)), 1, final=True
            )

        # As text '99.9' > '100.5' and '9.5' > '10.0'; as numbers the high is 100.5 and the low 9.5.
        self.store.upsert((at(0, '99.5', '99.5', '99.0', '99.5'), at(1, '100.0', '100.5', '9.5', '100.0'), at(2, '99.0', '99.9', '10.0', '99.0')))
        (day,) = self.store.read_daily('TWSE:2330', START, START + timedelta(minutes=3))
        self.assertEqual((day.open, day.high, day.low, day.close, day.volume), (Decimal('99.5'), Decimal('100.5'), Decimal('9.5'), Decimal('99.0'), 3))
        self.assertEqual((day.start, day.end), (START, START + timedelta(minutes=3)))

    def test_read_daily_keeps_a_price_finer_than_a_double_ordered(self):
        self.store.upsert((minute(0), minute(1, '10.123456789123456781')))
        (day,) = self.store.read_daily('TWSE:2330', START, START + timedelta(minutes=2))
        self.assertEqual((day.open, day.close, day.volume), (Decimal('10.123456789123456789'), Decimal('10.123456789123456781'), 24))
        self.assertTrue(day.low <= min(day.open, day.close) <= max(day.open, day.close) <= day.high)
        self.assertLess(day.high - day.low, Decimal('1e-14'))


def _corrupt_middle(path):
    """Overwrite 2,000 bytes in the middle of the file: quick_check fails, the schema still reads."""
    raw = bytearray(path.read_bytes())
    middle = len(raw) // 2
    raw[middle : middle + 2000] = b'\xff' * 2000
    path.write_bytes(bytes(raw))
    return bytes(raw)


class IntegrityCheckScheduleTests(unittest.TestCase):
    """OPT-1 P10: when the full integrity check must run, a corrupt cache is still preserved and rebuilt."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'market' / 'klines.sqlite3'
        store = KlineStore(self.path)
        store.upsert(tuple(minute(index) for index in range(3000)))
        self.store = store

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def assertPreservedAndRebuilt(self, corrupted):
        self.assertEqual(self.store.warning_code, 'kline_store_unavailable')
        self.assertEqual(self.store.recovered_path.read_bytes(), corrupted)
        self.assertIsNone(self.store.last_bar('TWSE:2330'))
        self.store.upsert((minute(),))
        self.assertEqual(self.store.last_bar('TWSE:2330'), minute())

    def test_corruption_after_an_unclean_exit_is_preserved_and_rebuilt(self):
        self.store._db.close()  # the process ends without KlineStore.close()
        corrupted = _corrupt_middle(self.path)
        self.store = KlineStore(self.path)
        self.assertPreservedAndRebuilt(corrupted)

    def test_corruption_after_a_clean_close_with_a_non_empty_wal_is_preserved(self):
        self.store.close()
        corrupted = _corrupt_middle(self.path)
        wal = Path(str(self.path) + '-wal')
        wal.write_bytes(b'\x00' * 4096)  # left behind by a writer that did not checkpoint
        self.store = KlineStore(self.path)
        self.assertPreservedAndRebuilt(corrupted)


def _failing_connection(fragment):
    """A sqlite3 connection whose statements containing fragment fail, as a full or locked disk would."""

    class Failing(sqlite3.Connection):
        def execute(self, sql, *args):
            if fragment in sql:
                raise sqlite3.OperationalError('disk I/O error')
            return super().execute(sql, *args)

    real = sqlite3.connect
    return unittest.mock.patch.object(sqlite3, 'connect', lambda *a, **k: real(*a, factory=Failing, **k))


TOKEN_WRITE = 'INSERT OR REPLACE INTO meta VALUES(?,?)'
TOKEN_DELETE = 'DELETE FROM meta WHERE key=?'


class IntegrityCheckFlagTests(unittest.TestCase):
    """OPT-1 P10: quick_check is skipped only when every earlier store closed cleanly, the WAL is empty and the check is recent."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'market' / 'klines.sqlite3'
        self.store = KlineStore(self.path)
        self.store.upsert(tuple(minute(index) for index in range(3000)))
        self.others = []

    def tearDown(self):
        for store in (self.store, *self.others):
            store.close()
        self.temp.cleanup()

    def meta(self, key):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def tokens(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {key for (key,) in db.execute("SELECT key FROM meta WHERE key GLOB 'open:*'")}

    def set_meta(self, key, value):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, value))
            db.commit()

    def checks(self, open_store):
        with unittest.mock.patch.object(KlineStore, '_full_check', autospec=True, side_effect=KlineStore._full_check) as check:
            store = open_store()
        return store, check.call_count

    def reopen(self):
        self.store, count = self.checks(lambda: KlineStore(self.path))
        return count

    def another(self):
        store, count = self.checks(lambda: KlineStore(self.path))
        self.others.append(store)
        return store, count

    def test_clean_close_and_recent_check_skip_the_full_check(self):
        self.assertEqual(self.tokens(), {self.store._token})
        checked = self.meta('last_full_check')
        self.assertIsNotNone(checked)
        self.store.close()
        self.assertEqual(self.tokens(), set())
        self.assertEqual(self.reopen(), 0)
        self.assertEqual(self.meta('last_full_check'), checked)
        self.assertEqual(self.store.warning_code, '')
        self.assertEqual(len(self.store.read('TWSE:2330', minute().start, minute(3000).start)), 3000)

    def test_token_left_by_an_unclean_exit_runs_the_full_check_and_is_then_cleared(self):
        self.store._db.close()  # the process ends without KlineStore.close()
        self.assertEqual(len(self.tokens()), 1)
        self.assertEqual(self.reopen(), 1)
        self.assertEqual(self.tokens(), {self.store._token})  # the checked open clears the stale token
        self.store.close()
        self.assertEqual(self.reopen(), 0)

    def test_non_empty_wal_runs_the_full_check(self):
        self.store.close()
        Path(str(self.path) + '-wal').write_bytes(b'\x00' * 4096)
        self.assertEqual(self.reopen(), 1)

    def test_unreadable_wal_counts_as_non_empty(self):
        with unittest.mock.patch.object(Path, 'stat', side_effect=PermissionError):
            self.assertIsNone(kline_store_module._wal_bytes(self.path))
        with unittest.mock.patch.object(Path, 'stat', side_effect=FileNotFoundError):
            self.assertEqual(kline_store_module._wal_bytes(self.path), 0)
        self.store.close()
        with unittest.mock.patch.object(kline_store_module, '_wal_bytes', return_value=None):
            self.assertEqual(self.reopen(), 1)

    def test_missing_check_time_runs_the_full_check(self):
        self.store.close()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM meta WHERE key='last_full_check'")
            db.commit()
        self.assertEqual(self.reopen(), 1)

    def test_periodic_full_check_interval_is_the_owner_chosen_30_days(self):
        self.assertEqual(kline_store_module._FULL_CHECK_INTERVAL, timedelta(days=30))  # owner decision 2026-11-21 (M6 D3)

    def test_overdue_future_or_unreadable_check_time_runs_the_full_check(self):
        now = datetime.now(timezone.utc)
        interval = kline_store_module._FULL_CHECK_INTERVAL
        for value in (
            (now - interval - timedelta(days=1)).isoformat(),
            (now + timedelta(days=1)).isoformat(),
            now.replace(tzinfo=None).isoformat(),
            'not a time',
        ):
            with self.subTest(value=value):
                self.store.close()
                self.set_meta('last_full_check', value)
                self.assertEqual(self.reopen(), 1)
                self.assertNotEqual(self.meta('last_full_check'), value)  # the passed check is recorded
        self.store.close()
        self.set_meta('last_full_check', (now - interval + timedelta(days=1)).isoformat())
        self.assertEqual(self.reopen(), 0)

    def test_a_store_that_dies_while_another_closes_last_is_still_seen(self):
        other, count = self.another()
        self.assertEqual(count, 1)  # the first store's token is live
        self.store._db.close()  # the first store exits without close() while the other is open
        other.close()  # the other store is the last connection: SQLite checkpoints and deletes the WAL
        self.others.remove(other)
        self.assertFalse(Path(str(self.path) + '-wal').exists())
        self.assertEqual(self.reopen(), 1)
        self.store.close()
        self.assertEqual(self.reopen(), 0)

    def test_a_live_store_keeps_its_token_when_another_store_opens(self):
        other, _ = self.another()
        other.close()
        self.others.remove(other)
        third, count = self.another()
        self.assertEqual(count, 1)
        self.assertIn(self.store._token, self.tokens())  # a non-empty WAL means it may be live: never cleared
        self.store._db.close()  # now the first store dies, and the third store closes last
        third.close()
        self.others.remove(third)
        self.assertEqual(self.reopen(), 1)

    def test_a_locked_full_check_is_still_temporarily_unavailable_without_recovery(self):
        self.store._db.close()  # the left-over token forces the full check
        with _failing_connection('PRAGMA quick_check'), self.assertRaises(DomainError) as raised:
            KlineStore(self.path)
        self.assertEqual((raised.exception.code, raised.exception.detail), ('kline_store_unavailable', 'cache is temporarily unavailable'))
        self.assertEqual([name for name in self.path.parent.iterdir() if '.bad-' in name.name], [])
        self.assertEqual(self.reopen(), 1)

    def test_failed_open_token_write_falls_back_to_the_full_check(self):
        self.store.close()
        with _failing_connection(TOKEN_WRITE):
            self.assertEqual(self.reopen(), 1)
        self.assertEqual(self.store.warning_code, '')
        self.assertEqual(self.tokens(), set())  # the failed write was rolled back
        self.store.upsert((minute(3000),))
        self.assertEqual(self.store.last_bar('TWSE:2330'), minute(3000))

    def test_failed_close_token_delete_leaves_the_next_open_checking(self):
        self.store.close()
        with _failing_connection(TOKEN_DELETE):
            store = KlineStore(self.path)
            store.close()
        self.assertEqual(self.tokens(), {store._token})
        self.assertEqual(self.reopen(), 1)

    def test_corruption_found_by_the_fallback_check_is_preserved_and_rebuilt(self):
        self.store.close()
        corrupted = _corrupt_middle(self.path)
        with _failing_connection(TOKEN_WRITE):
            self.store = KlineStore(self.path)
        self.assertEqual(self.store.warning_code, 'kline_store_unavailable')
        self.assertEqual(self.store.recovered_path.read_bytes(), corrupted)
        self.assertIsNone(self.store.last_bar('TWSE:2330'))

    def test_corruption_found_by_the_periodic_check_is_preserved_and_rebuilt(self):
        self.store.close()
        overdue = datetime.now(timezone.utc) - kline_store_module._FULL_CHECK_INTERVAL - timedelta(days=1)
        self.set_meta('last_full_check', overdue.isoformat())
        corrupted = _corrupt_middle(self.path)
        self.store = KlineStore(self.path)
        self.assertEqual(self.store.warning_code, 'kline_store_unavailable')
        self.assertEqual(self.store.recovered_path.read_bytes(), corrupted)


if __name__ == '__main__':
    unittest.main()
