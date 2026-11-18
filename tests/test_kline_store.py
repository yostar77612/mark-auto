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


if __name__ == '__main__':
    unittest.main()
