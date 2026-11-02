"""Offline cache admission: synthetic schema cases and separately labelled public bytes."""

from dataclasses import replace
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.official.stock_data import daily_url, events_url, parse_daily, parse_events, StockDataSource
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.adapters.official.daily_signal_events import daily_event_scope, parse_daily_signal_events
from quantlab.trading.application.stock_history import StockHistorySync
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.stock_history import price_series
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.stock_history import OfficialPayload, OfficialStockBatch
from quantlab.trading.runtime.official_daily_source import OfficialDailyStockSource

ID = 'TWSE:2330'
FIRST, THROUGH, END = date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 4)
FIELDS = ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交筆數']
EVENT_FIELDS = ['股票代號', '除權息日期', '除權息前收盤價', '除權息參考價']
FIXTURES = Path(__file__).parent / 'fixtures/daily_signal_data'


def document(fields, rows, **extra):
    return json.dumps(dict(stat='OK', fields=fields, data=rows, **extra), ensure_ascii=False).encode()


def calendar(days=(FIRST, THROUGH)):
    return TradingCalendar(
        'fixture',
        'v1',
        'RECORDED_TEST_DATES',
        tuple(TradingSession(day, datetime.combine(day, time(1), timezone.utc), datetime.combine(day, time(5, 30), timezone.utc)) for day in days),
    )


def sample(*, instrument=ID, first=FIRST, through=THROUGH, event_rows=()):
    days = (first, through) if first != through else (first,)
    raw = document(FIELDS, [[f'{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}', '1,000', '100000', '100', '102', '98', '100', '0', '1'] for day in days])
    events = document(EVENT_FIELDS, list(event_rows))
    daily = OfficialPayload(daily_url(instrument, first.replace(day=1)), sha256(raw).hexdigest(), raw)
    source = events_url(instrument, first, through + timedelta(days=1))
    event = OfficialPayload(source, sha256(events).hexdigest(), events)
    return OfficialStockBatch(
        instrument,
        first,
        through + timedelta(days=1),
        parse_daily(raw, instrument, first.replace(day=1)),
        parse_events(events, instrument, first, through + timedelta(days=1), source),
        (daily, event),
    )


class CachedStore:
    """Immutable fake port; no implicit transport or import operation."""

    def __init__(self, batch):
        self.batch, self.coverage, self.calls = batch, True, []

    def daily_history(self, instrument_id, start, end):
        self.calls.append(('history', instrument_id, start, end))
        return replace(
            self.batch,
            start=start,
            end=end,
            bars=tuple(b for b in self.batch.bars if start <= b.trade_date < end),
            events=tuple(e for e in self.batch.events if start <= e.ex_date < end),
        )

    def daily_coverage(self, instrument_id, start, end):
        self.calls.append(('coverage', instrument_id, start, end))
        return self.coverage

    def official_payload(self, url, digest):
        self.calls.append(('payload', url, digest))
        return next(p for p in self.batch.payloads if (p.source_url, p.digest) == (url, digest))


class OfficialDailySourceTests(unittest.TestCase):
    def setUp(self):
        self.store = CachedStore(sample())
        self.now = datetime(2020, 1, 4, 2, tzinfo=timezone.utc)
        self.clock = SimpleNamespace(now=lambda: self.now)

    def read(self, *, store=None, dates=None, through=THROUGH, start=None, instrument=ID):
        return OfficialDailyStockSource(store or self.store, self.clock).history(instrument, dates or calendar(), through=through, start=start)

    def refuse(self, *, code='daily_signal_source_unverified', **kwargs):
        with self.assertRaises(DomainError) as caught:
            self.read(**kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_actual_cache_reopen_retains_empty_event_negative_evidence_and_reads_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.sqlite3'
            batch = sample()
            with closing(KlineStore(path)) as store:
                source = StockDataSource(lambda url: batch.payloads[1].raw if 'TWT48U' in url else batch.payloads[0].raw)
                StockHistorySync(store, source).refresh(ID, FIRST, END, today=END, consent=True)
            with closing(KlineStore(path)) as store:
                statements = []
                store._db.set_trace_callback(statements.append)
                value = self.read(store=store)
                self.assertEqual(value.bars, batch.bars)
                self.assertEqual(value.events, ())
                self.assertTrue(statements)
                self.assertTrue(all(statement.lstrip().upper().startswith('SELECT') for statement in statements), statements)
            self.assertEqual(value.observed_at, self.now)
            self.assertEqual((value.policy.price_mode, value.policy.scope), ('ADJUSTED', 'EXCHANGE_REPORTED_DAILY_V1'))
            material = json.dumps(sorted((p.source_url, p.digest) for p in batch.payloads), separators=(',', ':'), ensure_ascii=True)
            self.assertEqual(value.source_digest, sha256(material.encode()).hexdigest())

    def test_event_values_are_verified_and_adjustment_uses_existing_authority(self):
        self.store = CachedStore(sample(event_rows=(['2330', '109/01/03', '100', '90'],)))
        history = self.read()
        series = price_series(history.bars, history.events)
        self.assertEqual((series.bars[0].close, series.bars[1].close), (D('90'), D('100')))
        self.assertEqual(history.bars[0].close, D('100'))

    def test_today_and_future_are_refused_before_any_cache_read(self):
        for now in (datetime(2020, 1, 3, 15, 59, tzinfo=timezone.utc), datetime(2020, 1, 2, 18, tzinfo=timezone.utc)):
            self.now = now
            self.refuse(code='daily_signal_not_available')
        self.assertEqual(self.store.calls, [])

    def test_prior_taipei_civil_day_is_available_even_while_utc_date_is_same(self):
        self.now = datetime(2020, 1, 3, 16, 1, tzinfo=timezone.utc)
        self.assertEqual(self.read().bars[-1].trade_date, THROUGH)

    def test_calendar_day_must_have_actually_closed(self):
        session = TradingSession(THROUGH, datetime(2020, 1, 3, 1, tzinfo=timezone.utc), self.now + timedelta(seconds=1))
        self.refuse(code='daily_signal_not_available', dates=TradingCalendar('x', 'v1', 'TEST', (session,)))
        self.assertEqual(self.store.calls, [], 'unfinished DAY must be rejected before cache I/O')

    def test_all_labeled_day_sessions_must_be_closed_not_only_requested_through(self):
        ordered = (calendar().day_session(THROUGH), TradingSession(FIRST, self.now, self.now + timedelta(hours=1)))
        self.refuse(code='daily_signal_not_available', dates=TradingCalendar('fixture', 'v1', 'TEST', ordered))

    def test_requested_through_bar_is_required_and_empty_range_is_not_invented(self):
        self.store.batch = replace(self.store.batch, bars=self.store.batch.bars[:1])
        self.refuse(code='daily_signal_not_available')
        self.store.calls.clear()
        self.refuse(code='daily_signal_not_available', start=END)
        self.assertEqual(self.store.calls, [], 'invalid range must be rejected before cache I/O')
        self.store.batch = replace(self.store.batch, bars=())
        self.refuse(code='daily_signal_not_available')

    def test_default_start_can_use_first_actual_cache_row_but_explicit_start_cannot_skip_a_day(self):
        self.store = CachedStore(sample(first=THROUGH))
        self.assertEqual(len(self.read().bars), 1)
        self.refuse(code='daily_signal_not_available', start=FIRST)

    def test_default_first_actual_day_does_not_apply_events_before_that_history_begins(self):
        batch = sample(event_rows=(['2330', '109/01/02', '100', '90'],))
        self.store = CachedStore(replace(batch, bars=batch.bars[1:]))
        self.assertEqual((len(self.read().bars), self.read().events), (1, ()))

    def test_missing_middle_day_is_not_filled_with_zero_or_carried_price(self):
        third = date(2020, 1, 6)
        self.store = CachedStore(sample(through=third))
        self.now = datetime(2020, 1, 7, tzinfo=timezone.utc)
        self.refuse(code='daily_signal_not_available', through=third, dates=calendar((FIRST, THROUGH, third)))

    def test_import_coverage_is_required_even_when_all_rows_are_present(self):
        self.store.coverage = False
        self.refuse(code='daily_signal_not_available')

    def test_bar_limit_is_6000_not_an_unbounded_cache_read(self):
        first = date(2000, 1, 1)
        days = tuple(first + timedelta(days=index) for index in range(6001))
        grouped = {}
        for day in days:
            grouped.setdefault(day.replace(day=1), []).append(day)
        bars, payloads = [], []
        for month, rows in grouped.items():
            raw = document(
                FIELDS, [[f'{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}', '1000', '100000', '100', '102', '98', '100', '0', '1'] for day in rows]
            )
            bars.extend(parse_daily(raw, ID, month))
            payloads.append(OfficialPayload(daily_url(ID, month), sha256(raw).hexdigest(), raw))
        end = days[-1] + timedelta(days=1)
        raw = document(EVENT_FIELDS, [])
        payloads.append(OfficialPayload(events_url(ID, first, end), sha256(raw).hexdigest(), raw))
        self.store = CachedStore(OfficialStockBatch(ID, first, end, tuple(bars), (), tuple(payloads)))
        self.now = datetime.combine(end, time(2), timezone.utc)
        self.refuse(code='daily_signal_not_available', dates=calendar(days), through=days[-1])

    def test_cached_ohlcv_edit_cannot_reuse_unchanged_payload_digest(self):
        for field, value in (('close', D('101')), ('volume', 2000)):
            with self.subTest(field=field):
                batch = sample()
                self.store = CachedStore(replace(batch, bars=(replace(batch.bars[0], **{field: value}), batch.bars[1])))
                self.refuse()

    def test_event_edit_or_silent_event_removal_cannot_reuse_valid_source_hash(self):
        batch = sample(event_rows=(['2330', '109/01/03', '100', '90'],))
        for events in ((), (replace(batch.events[0], reference_price=D('95')),)):
            with self.subTest(events=events):
                self.store = CachedStore(replace(batch, events=events))
                self.refuse()

    def test_empty_events_need_actual_complete_event_response_not_just_daily_coverage(self):
        self.store.batch = replace(self.store.batch, payloads=self.store.batch.payloads[:1])
        self.refuse()

    def test_empty_event_response_for_only_half_range_is_insufficient(self):
        batch = sample()
        event = replace(batch.payloads[1], source_url=events_url(ID, FIRST, THROUGH))
        self.store.batch = replace(batch, payloads=(batch.payloads[0], event))
        self.refuse()

    def test_empty_event_response_cannot_skip_beginning_of_history(self):
        batch = sample()
        event = replace(batch.payloads[1], source_url=events_url(ID, THROUGH, END))
        self.store.batch = replace(batch, payloads=(batch.payloads[0], event))
        self.refuse()

    def test_scoped_event_request_identity_and_ordered_range_are_required(self):
        batch = sample()
        for url in (
            events_url('TWSE:6225', FIRST, END),
            events_url(ID, END, FIRST),
            events_url(ID, FIRST, END) + '&unverified=true',
            events_url(ID, FIRST, END).replace('TWT48U', 'TWT47U'),
        ):
            with self.subTest(url=url):
                self.store = CachedStore(replace(batch, payloads=(batch.payloads[0], replace(batch.payloads[1], source_url=url))))
                self.refuse()

    def test_empty_event_response_ranges_can_cover_by_union(self):
        batch = sample()
        events = tuple(replace(batch.payloads[1], source_url=events_url(ID, first, end)) for first, end in ((FIRST, THROUGH), (THROUGH, END)))
        self.store.batch = replace(batch, payloads=(batch.payloads[0], *events))
        self.assertEqual(self.read().events, ())

    def test_payload_hash_and_immutable_payload_lookup_are_both_required(self):
        batch = sample()
        self.store.batch = replace(batch, payloads=(replace(batch.payloads[0], raw=batch.payloads[0].raw + b' '), batch.payloads[1]))
        self.refuse()
        self.store = CachedStore(batch)
        self.store.official_payload = lambda url, digest: replace(batch.payloads[0], raw=b'different')
        self.refuse()

    def test_other_stock_exchange_endpoint_or_duplicate_request_key_are_refused(self):
        batch = sample()
        url = batch.payloads[0].source_url
        for wrong in (
            url.replace('stockNo=2330', 'stockNo=6225'),
            url.replace('www.twse.com.tw', 'www.tpex.org.tw'),
            url.replace('STOCK_DAY', 'MI_INDEX'),
            url + '&stockNo=2330',
            url.replace('https:', 'http:'),
            url + '#fragment',
        ):
            with self.subTest(url=wrong):
                self.store = CachedStore(replace(batch, payloads=(replace(batch.payloads[0], source_url=wrong), batch.payloads[1])))
                self.refuse()

    def test_supported_rwd_daily_alias_preserves_exact_public_payload_identity(self):
        batch = sample()
        daily = replace(batch.payloads[0], source_url=batch.payloads[0].source_url.replace('/exchangeReport/STOCK_DAY', '/rwd/zh/afterTrading/STOCK_DAY'))
        self.store.batch = replace(batch, payloads=(daily, batch.payloads[1]))
        self.assertEqual(self.read().bars, batch.bars)

    def test_tpex_native_thousand_share_schema_uses_same_read_only_contract(self):
        instrument = 'TPEX:6488'
        raw = json.dumps({'aaData': [['109/01/02', '1.234', '123.4', '100', '102', '98', '100', '0', '10']]}).encode()
        daily = OfficialPayload(daily_url(instrument, FIRST.replace(day=1)), sha256(raw).hexdigest(), raw)
        empty = document(EVENT_FIELDS, [])
        event = OfficialPayload(events_url(instrument, FIRST, THROUGH), sha256(empty).hexdigest(), empty)
        batch = OfficialStockBatch(instrument, FIRST, THROUGH, parse_daily(raw, instrument, FIRST), (), (daily, event))
        value = self.read(store=CachedStore(batch), instrument=instrument, through=FIRST)
        self.assertEqual(value.bars[0].volume, 1234)

    def test_recorded_real_thin_stock_is_not_a_claim_of_missing_event_negative_evidence(self):
        raw = (FIXTURES / 'twse_6225_202506.json').read_bytes()
        instrument, through = 'TWSE:6225', date(2025, 6, 27)
        bars = parse_daily(raw, instrument, through.replace(day=1))
        selected = tuple(bar for bar in bars if bar.trade_date == through)
        self.assertEqual((selected[0].close, selected[0].volume), (D('11.40'), 11000))
        url = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20250601&stockNo=6225&response=json'
        batch = OfficialStockBatch(instrument, through, through + timedelta(days=1), selected, (), (OfficialPayload(url, sha256(raw).hexdigest(), raw),))
        self.now = datetime(2025, 6, 28, tzinfo=timezone.utc)
        self.refuse(store=CachedStore(batch), instrument=instrument, through=through, dates=calendar((through,)))

    def test_recorded_other_stock_payload_cannot_be_relabelled_under_valid_request_url(self):
        raw = (FIXTURES / 'twse_2330_202506.json').read_bytes()
        instrument, through = 'TWSE:6225', date(2025, 6, 27)
        bars = tuple(bar for bar in parse_daily(raw, instrument, through.replace(day=1)) if bar.trade_date == through)
        daily = OfficialPayload(daily_url(instrument, through.replace(day=1)), sha256(raw).hexdigest(), raw)
        event_raw = document(EVENT_FIELDS, [])
        event = OfficialPayload(events_url(instrument, through, through + timedelta(days=1)), sha256(event_raw).hexdigest(), event_raw)
        batch = OfficialStockBatch(instrument, through, through + timedelta(days=1), bars, (), (daily, event))
        self.now = datetime(2025, 6, 28, tzinfo=timezone.utc)
        self.refuse(store=CachedStore(batch), instrument=instrument, through=through, dates=calendar((through,)))

    def test_recorded_public_action_for_another_date_cannot_prove_empty_events_for_requested_range(self):
        batch = sample()
        raw = (FIXTURES / 'twse_ex_right_20250612.json').read_bytes()
        url = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250612&endDate=20250612&response=json'
        self.store.batch = replace(batch, payloads=(batch.payloads[0], OfficialPayload(url, sha256(raw).hexdigest(), raw)))
        self.refuse()

    def test_actual_public_ex_dividend_cache_has_real_positive_and_negative_day_evidence(self):
        first, through = date(2025, 6, 11), date(2025, 6, 12)
        raw = (FIXTURES / 'twse_2330_202506.json').read_bytes()
        event_raw = (FIXTURES / 'twse_actions_20250611_20250612.json').read_bytes()
        daily_url = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20250601&stockNo=2330&response=json'
        event_url = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250611&endDate=20250612&response=json'
        bars = tuple(b for b in parse_daily(raw, ID, first.replace(day=1)) if first <= b.trade_date <= through)
        events = parse_daily_signal_events(event_raw, ID, event_url)
        batch = OfficialStockBatch(
            ID,
            first,
            through + timedelta(days=1),
            bars,
            events,
            (OfficialPayload(daily_url, sha256(raw).hexdigest(), raw), OfficialPayload(event_url, sha256(event_raw).hexdigest(), event_raw)),
        )
        self.now = datetime(2025, 6, 13, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory, closing(KlineStore(Path(directory) / 'cache.sqlite3')) as store:
            store.import_daily(batch)
            history = self.read(store=store, dates=calendar((first, through)), start=first, through=through)
        self.assertEqual(tuple(b.close for b in history.bars), (D('1065'), D('1045')))
        self.assertEqual(tuple(e.ex_date for e in history.events), (through,))
        self.assertEqual((events[0].previous_close, events[0].reference_price), (D('1065'), D('1060.49')))
        adjusted = price_series(history.bars, history.events)
        self.assertEqual(tuple(b.close for b in adjusted.bars), (D('1060.49'), D('1045')))


class DailySignalEventsTests(unittest.TestCase):
    url = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250611&endDate=20250612&response=json'

    def setUp(self):
        self.raw = (FIXTURES / 'twse_actions_20250611_20250612.json').read_bytes()

    def refused(self, raw=None, *, url=None, instrument=ID):
        with self.assertRaises(DomainError):
            parse_daily_signal_events(self.raw if raw is None else raw, instrument, url or self.url)

    def changed(self, change):
        body = json.loads(self.raw)
        change(body)
        return json.dumps(body, ensure_ascii=False).encode()

    def test_public_range_inclusive_end_preserves_raw_digest_and_filters_stock(self):
        result = parse_daily_signal_events(self.raw, ID, self.url)
        self.assertEqual(daily_event_scope(self.url), (date(2025, 6, 11), date(2025, 6, 13)))
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].source_digest, result[0].source_url), (sha256(self.raw).hexdigest(), self.url))
        self.assertEqual(parse_daily_signal_events(self.raw, 'TWSE:6225', self.url), ())

    def test_single_day_actual_response_attests_exactly_one_civil_day(self):
        raw = (FIXTURES / 'twse_ex_right_20250612.json').read_bytes()
        url = self.url.replace('startDate=20250611', 'startDate=20250612')
        self.assertEqual(daily_event_scope(url), (date(2025, 6, 12), date(2025, 6, 13)))
        self.assertEqual(parse_daily_signal_events(raw, ID, url)[0].ex_date, date(2025, 6, 12))

    def test_unknown_wrong_venue_stock_scoped_and_duplicate_query_requests_are_refused(self):
        for url in (
            self.url.replace('twse.com.tw', 'tpex.org.tw'),
            self.url.replace('TWT49U', 'TWT48U'),
            self.url + '&stockNo=2330',
            self.url + '&startDate=20250611',
            self.url.replace('https:', 'http:'),
            self.url + '#fragment',
            self.url.replace('response=json', 'response=html'),
            self.url.replace('startDate=20250611', 'startDate=20250613'),
        ):
            with self.subTest(url=url):
                self.refused(url=url)
        self.refused(instrument='TPEX:6488')
        self.refused(url=self.url.replace('https:', 'http:'), instrument='TWSE:6225')

    def test_reversed_request_cannot_claim_empty_evidence_even_with_matching_response_metadata(self):
        url = self.url.replace('startDate=20250611', 'startDate=20250613')
        raw = self.changed(lambda b: b.update(strDate='20250613', endDate='20250612', data=[]))
        self.refused(raw, url=url)

    def test_stat_and_response_range_are_required_even_when_target_stock_is_absent(self):
        for key, value in (('stat', 'ERROR'), ('strDate', '20250610'), ('endDate', '20250613')):
            with self.subTest(key=key):
                self.refused(self.changed(lambda b: b.update({key: value})), instrument='TWSE:6225')
        self.refused(self.changed(lambda b: b.pop('stat')), instrument='TWSE:6225')

    def test_missing_schema_or_unknown_date_format_is_not_negative_evidence(self):
        self.refused(self.changed(lambda b: b['fields'].__setitem__(0, '除權息日期')))
        self.refused(self.changed(lambda b: (b['fields'].__setitem__(0, '除權息日期'), b.update(data=[]))))
        self.refused(self.changed(lambda b: b['data'][0].__setitem__(0, '2025/06/11')))

    def test_out_of_range_other_stock_row_invalidates_whole_response(self):
        self.refused(self.changed(lambda b: b['data'][0].__setitem__(0, '114年06月10日')), instrument='TWSE:6225')
        self.refused(self.changed(lambda b: b['data'][0].__setitem__(0, '114年06月13日')), instrument='TWSE:6225')
        self.refused(self.changed(lambda b: b['data'][0].__setitem__(1, 'unverified!')), instrument='TWSE:6225')

    def test_duplicate_other_stock_event_invalidates_negative_evidence(self):
        self.refused(self.changed(lambda b: b['data'].append(b['data'][0])), instrument='TWSE:6225')

    def test_missing_invalid_nonpositive_reference_price_is_refused_even_on_other_stock(self):
        column = json.loads(self.raw)['fields'].index('除權息參考價')
        for price in ('--', '0', '-1', 'NaN'):
            with self.subTest(price=price):
                self.refused(self.changed(lambda b: b['data'][0].__setitem__(column, price)), instrument='TWSE:6225')
        previous = json.loads(self.raw)['fields'].index('除權息前收盤價')
        self.refused(self.changed(lambda b: b['data'][0].__setitem__(previous, '0')), instrument='TWSE:6225')

    def test_verified_empty_global_table_is_distinct_from_missing_table(self):
        self.assertEqual(parse_daily_signal_events(self.changed(lambda b: b.update(data=[])), ID, self.url), ())
        self.refused(self.changed(lambda b: b.pop('data')))


if __name__ == '__main__':
    unittest.main()
