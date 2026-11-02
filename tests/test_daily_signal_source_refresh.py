"""Actual in-memory official-cache refreshes; synthetic exchange-shaped fixtures."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import sqlite3
from threading import RLock
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.official.stock_data import daily_url, events_url, parse_daily, parse_events
from quantlab.trading.adapters.storage.daily_stock_store import DailyStockStorage
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.stock_history import OfficialPayload, OfficialStockBatch
from quantlab.trading.runtime.official_daily_source import OfficialDailyStockSource


INSTRUMENT = 'TWSE:2330'
DAYS = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6))
EVENT = ('2330', '109/01/03', '100', '90')


def _document(fields, rows):
    return json.dumps(dict(stat='OK', fields=fields, data=rows), ensure_ascii=False).encode()


def _batch(days, event_rows=(EVENT,)):
    first, end = days[0], days[-1] + timedelta(days=1)
    raw = _document(
        ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交筆數'],
        [[f'{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}', '1000', '100000', '100', '102', '98', '100', '0', '1'] for day in days],
    )
    event_raw = _document(['股票代號', '除權息日期', '除權息前收盤價', '除權息參考價'], event_rows)
    event_url = events_url(INSTRUMENT, first, end)
    daily = OfficialPayload(daily_url(INSTRUMENT, first.replace(day=1)), sha256(raw).hexdigest(), raw)
    event = OfficialPayload(event_url, sha256(event_raw).hexdigest(), event_raw)
    return OfficialStockBatch(
        INSTRUMENT,
        first,
        end,
        parse_daily(raw, INSTRUMENT, first.replace(day=1)),
        parse_events(event_raw, INSTRUMENT, first, end, event_url),
        (daily, event),
    )


class OfficialDailyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.store = DailyStockStorage(self.db, RLock())
        self.clock = SimpleNamespace(now=lambda: datetime(2020, 1, 7, 2, tzinfo=timezone.utc))
        self.source = OfficialDailyStockSource(self.store, self.clock)

    def read(self, days=DAYS):
        calendar = TradingCalendar(
            'refresh-fixture',
            'v1',
            'SYNTHETIC_EXPLICIT_DATES',
            tuple(TradingSession(day, datetime.combine(day, time(1), timezone.utc), datetime.combine(day, time(5, 30), timezone.utc)) for day in days),
        )
        return self.source.history(INSTRUMENT, calendar, through=days[-1], start=days[0])

    def assert_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')

    def test_expanding_refresh_preserves_same_event_despite_new_manifest_url(self):
        first, expanded = _batch(DAYS[:2]), _batch(DAYS)
        self.store.import_daily(first)
        original = self.read(DAYS[:2])
        self.assertEqual(len(original.events), 1)
        self.store.import_daily(expanded)
        current = self.store.daily_history(INSTRUMENT, DAYS[0], DAYS[-1] + timedelta(days=1))
        self.assertEqual((len(current.bars), len(current.events), len(current.payloads)), (3, 1, 4))
        result = self.read()
        self.assertEqual(result.bars, expanded.bars)
        self.assertEqual(result.events, expanded.events)
        self.assertNotEqual(result.source_digest, original.source_digest)
        self.assertEqual(original.research_basis(DAYS[0], DAYS[1]).events_digest, result.research_basis(DAYS[0], DAYS[1]).events_digest)

    def test_expanding_refresh_cannot_hide_contradictory_old_positive(self):
        for previous, reference in (('100', '80'), ('110', '90')):
            with self.subTest(previous=previous, reference=reference):
                self.store.import_daily(_batch(DAYS[:2]))
                self.store.import_daily(_batch(DAYS, (('2330', '109/01/03', previous, reference),)))
                self.assert_refused()

    def test_expanding_refresh_cannot_move_old_positive_to_another_date(self):
        self.store.import_daily(_batch(DAYS[:2]))
        self.store.import_daily(_batch(DAYS, (('2330', '109/01/06', '100', '90'),)))
        self.assert_refused()

    def test_expanding_empty_response_cannot_erase_old_positive_evidence(self):
        self.store.import_daily(_batch(DAYS[:2]))
        self.store.import_daily(_batch(DAYS, ()))
        self.assert_refused()

    def test_same_facts_cannot_borrow_a_daily_payload_as_event_provenance(self):
        batch = _batch(DAYS)
        self.store.import_daily(batch)
        daily = batch.payloads[0]
        self.db.execute('UPDATE corporate_actions SET source_digest=?, source_url=?', (daily.digest, daily.source_url))
        self.assert_refused()

    def test_exact_interval_correction_replaces_manifest_and_changes_basis(self):
        self.store.import_daily(_batch(DAYS))
        original = self.read()
        corrected = _batch(DAYS, (('2330', '109/01/03', '100', '80'),))
        self.store.import_daily(corrected)
        result = self.read()
        self.assertEqual(result.events, corrected.events)
        self.assertFalse(original.research_basis(DAYS[0], DAYS[-1]).compatible(result.research_basis(DAYS[0], DAYS[-1])))


if __name__ == '__main__':
    unittest.main()
