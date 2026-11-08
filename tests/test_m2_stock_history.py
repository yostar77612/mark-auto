"""Offline synthetic native-schema fixtures; no live exchange provenance claimed."""

from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from quantlab.trading.adapters.official.stock_data import StockDataSource, daily_url, parse_daily, parse_events, events_url
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.stock_history import StockHistorySync, months_between
from quantlab.trading.domain.stock_history import CorporateAction, price_series
from quantlab.trading.domain.validation import DomainError

ID = 'TWSE:2330'
START, END = date(2020, 1, 1), date(2020, 2, 1)
FIELDS = ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交筆數']
EVENT_FIELDS = ['股票代號', '除權息日期', '除權息前收盤價', '除權息參考價']


def native(month=START, *, prices=('100', '102', '98', '100'), rows=None):
    return json.dumps(
        {
            'stat': 'OK',
            'fields': FIELDS,
            'data': rows if rows is not None else [[f'{month.year - 1911:03d}/{month.month:02d}/02', '1,234', '123400', *prices, '0', '123']],
        },
        ensure_ascii=False,
    ).encode()


def event_data(rows=()):
    return json.dumps({'stat': 'OK', 'fields': EVENT_FIELDS, 'data': list(rows)}, ensure_ascii=False).encode()


class OfficialStockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'klines.sqlite3'
        self.store = KlineStore(self.path)
        self.addCleanup(lambda: self.store.close())

    def source(self, daily=None, events=None):
        return StockDataSource(lambda url: (events if events is not None else event_data()) if 'TWT48U' in url else daily if daily is not None else native())

    def test_native_twse_values_dates_and_provenance(self):
        bars = parse_daily(native(), ID, START)
        self.assertEqual((bars[0].trade_date, bars[0].close, bars[0].volume), (date(2020, 1, 2), D('100'), 1234))
        self.assertEqual(bars[0].source, 'OFFICIAL')
        self.assertEqual(bars[0].source_digest, sha256(native()).hexdigest())
        self.assertIn('stockNo=2330', daily_url(ID, START))

    def test_native_tpex_thousand_shares_not_lots(self):
        raw = json.dumps({'aaData': [['109/01/02', '1.234', '123.4', '100', '102', '98', '100', '0', '10']]}).encode()
        bar = parse_daily(raw, 'TPEX:6488', START)[0]
        self.assertEqual(bar.volume, 1234)
        self.assertEqual(bar.instrument_id, 'TPEX:6488')
        self.assertIn('/afterTrading/tradingStock?code=6488', daily_url('TPEX:6488', START))

    def test_missing_invalid_duplicate_and_wrong_month_are_not_fabricated(self):
        good = json.loads(native())
        bad_documents = [
            b'{}',
            b'{"stat":"OK","stat":"BAD"}',
            native(prices=('--', '102', '98', '100')),
            native(prices=('1,00', '102', '98', '100')),
            native(prices=('100', '99', '98', '100')),
            native(date(2020, 2, 1)),
            native(rows=[]),
            native(rows=good['data'] * 2),
        ]
        for raw in bad_documents:
            with self.subTest(raw_length=len(raw)), self.assertRaises(DomainError):
                parse_daily(raw, ID, START)

    def test_refresh_requires_explicit_consent_and_closed_days(self):
        calls = []
        source = StockDataSource(lambda url: calls.append(url))
        sync = StockHistorySync(self.store, source)
        for consent, today in ((False, END), (True, START)):
            with self.assertRaises(DomainError):
                sync.refresh(ID, START, END, today=today, consent=consent)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.daily_history(ID, START, END).bars, ())

    def test_atomic_official_daily_import_and_empty_event_source_survive_reopen(self):
        batch = StockHistorySync(self.store, self.source()).refresh(ID, START, END, today=END, consent=True)
        stored = self.store.daily_history(ID, START, END)
        self.assertEqual(stored.bars, batch.bars)
        self.assertEqual(set(stored.payloads), set(batch.payloads))
        self.assertTrue(self.store.daily_coverage(ID, START, END))
        self.assertFalse(self.store.daily_coverage(ID, START, date(2020, 3, 1)))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT source FROM bars_1d').fetchall(), [('OFFICIAL',)])
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchall(), [('1',)])
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
        self.store.close()
        self.store = KlineStore(self.path)
        self.assertEqual(set(self.store.daily_history(ID, START, END).payloads), set(batch.payloads))

    def test_late_event_failure_keeps_prior_bars_payloads_and_coverage(self):
        sync = StockHistorySync(self.store, self.source())
        sync.refresh(ID, START, END, today=END, consent=True)
        before = self.store.daily_history(ID, START, END)
        broken = StockHistorySync(self.store, self.source(daily=native(prices=('200', '202', '198', '200')), events=b'bad'))
        with self.assertRaises(DomainError):
            broken.refresh(ID, START, END, today=END, consent=True)
        self.assertEqual(self.store.daily_history(ID, START, END), before)
        self.assertTrue(self.store.daily_coverage(ID, START, END))

    def test_successful_correction_preserves_previous_source_bytes_by_digest(self):
        first = StockHistorySync(self.store, self.source()).refresh(ID, START, END, today=END, consent=True)
        second = StockHistorySync(self.store, self.source(daily=native(prices=('200', '202', '198', '200')))).refresh(ID, START, END, today=END, consent=True)
        self.assertNotEqual(first.bars, second.bars)
        self.assertEqual(self.store.daily_history(ID, START, END).bars, second.bars)
        for payload in first.payloads:
            self.assertEqual(self.store.official_payload(payload.source_url, payload.digest), payload)

    def test_invalid_import_cannot_change_history(self):
        batch = StockHistorySync(self.store, self.source()).refresh(ID, START, END, today=END, consent=True)
        corrupt = replace(batch, payloads=(replace(batch.payloads[0], raw=b'tampered'), *batch.payloads[1:]))
        with self.assertRaises(DomainError):
            self.store.import_daily(corrupt)
        self.assertEqual(self.store.daily_history(ID, START, END).bars, batch.bars)

    def test_price_adjustment_is_reproducible_raw_execution_prices_unchanged(self):
        first = parse_daily(native(), ID, START)[0]
        second = replace(first, trade_date=date(2020, 1, 3), open=D('90'), high=D('92'), low=D('88'), close=D('90'))
        raw = event_data([['2330', '109/01/03', '100', '90']])
        events = parse_events(raw, ID, START, END, events_url(ID, START, END))
        adjusted = price_series((first, second), events)
        self.assertEqual(adjusted.bars[0].close, D('90'))
        self.assertEqual(adjusted.bars[1].close, D('90'))
        self.assertEqual(first.close, D('100'))
        self.assertEqual(price_series((first, second), events, adjusted=False).bars, (first, second))
        self.assertEqual(adjusted, price_series((first, second), events))
        self.assertNotEqual(adjusted.events_digest, price_series((first, second), ()).events_digest)
        self.assertIn(('adjustment_method', 'official-reference-ratio-backward-v1'), adjusted.evidence())

    def test_future_events_are_excluded_and_duplicate_combined_events_refused(self):
        bar = parse_daily(native(), ID, START)[0]
        event = CorporateAction(ID, END, D('100'), D('80'), 'a' * 64, events_url(ID, START, END))
        self.assertEqual(price_series((bar,), (event,)).bars, (bar,))
        with self.assertRaises(DomainError):
            price_series((bar,), (event, event))

    def test_transaction_failure_after_delete_rolls_back_previous_history(self):
        sync = StockHistorySync(self.store, self.source())
        sync.refresh(ID, START, END, today=END, consent=True)
        before = self.store.daily_history(ID, START, END)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_daily BEFORE INSERT ON bars_1d BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
        with self.assertRaises(DomainError):
            StockHistorySync(self.store, self.source(daily=native(prices=('200', '202', '198', '200')))).refresh(ID, START, END, today=END, consent=True)
        self.assertEqual(self.store.daily_history(ID, START, END), before)

    def test_point_in_time_signals_do_not_see_later_adjustment_factors(self):
        first = parse_daily(native(), ID, START)[0]
        second = replace(first, trade_date=date(2020, 1, 3))
        event = CorporateAction(ID, second.trade_date, D('100'), D('80'), 'a' * 64, events_url(ID, START, END))
        before = price_series((first, second), (event,), as_of=first.trade_date)
        after = price_series((first, second), (event,), as_of=second.trade_date)
        self.assertEqual(before.bars, (first,))
        self.assertEqual(after.bars[0].close, D('80'))
        self.assertEqual(first.close, D('100'))

    def test_five_year_inputs_certify_every_explicit_session_and_freeze_provenance(self):
        from datetime import datetime, timedelta, timezone
        from urllib.parse import parse_qs, urlsplit
        from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
        from quantlab.trading.domain.costs import FeeSchedule

        end = date(2025, 1, 1)
        months = months_between(START, end)

        def transport(url):
            if 'TWT48U' in url:
                return event_data()
            value = parse_qs(urlsplit(url).query)['date'][0]
            return native(date(int(value[:4]), int(value[4:6]), 1))

        days = (START - timedelta(days=1), *(month.replace(day=2) for month in months), end)
        sessions = tuple(
            TradingSession(
                day, datetime.combine(day, datetime.min.time(), timezone.utc), datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=6)
            )
            for day in days
        )
        calendar = TradingCalendar('sparse-synthetic-calendar', 'test-v1', 'synthetic-not-real-market', sessions)
        sync = StockHistorySync(self.store, StockDataSource(transport))
        sync.refresh(ID, START, end, today=end, consent=True)
        fees = FeeSchedule.taiwan()
        inputs = sync.research_inputs(ID, START, end, calendar, fees)
        self.assertEqual(len(inputs.batch.bars), 60)
        self.assertIs(inputs.fees, fees)
        evidence = inputs.evidence()
        self.assertIn(('execution_and_pnl_prices', 'RAW'), evidence)
        self.assertIn(('cost_version', fees.version), evidence)
        self.assertEqual(len(inputs.signals_at(date(2020, 1, 2)).bars), 1)
        self.assertEqual(sync.chart_prices(ID, START, end, adjusted=False).bars, inputs.batch.bars)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM bars_1d WHERE trade_date=?', ('2020-01-02',))
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
        with self.assertRaises(DomainError) as missing:
            sync.research_inputs(ID, START, end, calendar, fees)
        self.assertEqual(missing.exception.code, 'official_stock_coverage_missing')
        self.assertEqual(inputs.evidence(), evidence)

    def test_five_year_request_uses_every_month_and_refuses_uncovered_research(self):
        self.assertEqual(len(months_between(date(2020, 1, 1), date(2025, 1, 1))), 60)
        self.assertEqual(months_between(date(2020, 12, 31), date(2021, 2, 1)), (date(2020, 12, 1), date(2021, 1, 1)))
        from quantlab.trading.runtime.sinopac_calendar import built_in_calendar

        with self.assertRaises(DomainError) as error:
            StockHistorySync(self.store, self.source()).research_prices(ID, START, date(2025, 1, 1), built_in_calendar())
        self.assertEqual(error.exception.code, 'official_stock_coverage_missing')


class OfficialTransportTests(unittest.TestCase):
    def test_url_boundary_refuses_credentials_redirects_duplicate_and_unknown_parameters(self):
        from quantlab.trading.runtime.stock_history import validate_stock_url

        good = daily_url(ID, START)
        self.assertEqual(validate_stock_url(good), good)
        self.assertEqual(validate_stock_url(daily_url('TPEX:6488', START)), daily_url('TPEX:6488', START))
        for bad in (
            good.replace('https:', 'http:'),
            good + '&stockNo=2330',
            good + '&secret=none',
            good + '#fragment',
            good.replace('www.twse.com.tw', 'www.twse.com.tw.example.org'),
            good.replace('www.twse.com.tw', 'user@www.twse.com.tw'),
        ):
            with self.subTest(url=bad), self.assertRaises(DomainError):
                validate_stock_url(bad)

    def test_network_boundary_uses_fake_opener_and_sanitizes_failures(self):
        from io import BytesIO
        from unittest.mock import Mock, patch
        from quantlab.trading.runtime.stock_history import fetch_stock_official

        url = daily_url(ID, START)
        for status, length, encoding, body, accepted in (
            (200, '2', 'identity', b'{}', True),
            (302, '2', 'identity', b'{}', False),
            (200, '3', 'identity', b'{}', False),
            (200, '999999999', 'identity', b'{}', False),
            (200, '2', 'gzip', b'{}', False),
        ):
            response = Mock(status=status, headers={'Content-Length': length, 'Content-Encoding': encoding})
            response.geturl.return_value = url
            response.read.side_effect = BytesIO(body).read
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            opener = Mock()
            opener.open.return_value = response
            with patch('quantlab.trading.runtime.stock_history.build_opener', return_value=opener), self.subTest(status=status, length=length):
                if accepted:
                    self.assertEqual(fetch_stock_official(url), body)
                else:
                    with self.assertRaises(DomainError) as caught:
                        fetch_stock_official(url)
                    self.assertEqual(caught.exception.code, 'official_stock_invalid')
                    self.assertNotIn(url, str(caught.exception))

    def test_deadline_size_redirect_and_transport_failure_leave_no_http_owner(self):
        from unittest.mock import Mock, patch
        from quantlab.trading.runtime.stock_history import fetch_stock_official

        url = daily_url(ID, START)
        for fault in ('deadline', 'size', 'redirect', 'upstream'):
            response = Mock(status=200, headers={})
            response.geturl.return_value = url if fault != 'redirect' else 'https://example.invalid/'
            response.read.side_effect = [b'12345', b'']
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            opener, handler = Mock(), Mock()
            opener.open.return_value = response
            if fault == 'upstream':
                opener.open.side_effect = OSError('private upstream exception detail')
            ticks = [0, 31] if fault == 'deadline' else [0] * 8
            with (
                patch('quantlab.trading.runtime.stock_history.build_opener', return_value=opener),
                patch('quantlab.trading.runtime.stock_history._DeadlineHTTPSHandler', return_value=handler),
                patch('quantlab.trading.runtime.stock_history.time.monotonic', side_effect=ticks),
                patch('quantlab.trading.runtime.stock_history.MAX_BYTES', 4),
                self.subTest(fault=fault),
            ):
                with self.assertRaises(DomainError) as caught:
                    fetch_stock_official(url)
                self.assertEqual(caught.exception.code, 'official_stock_invalid')
                self.assertNotIn('private upstream', str(caught.exception))
                handler.cleanup.assert_called_once_with()
            if fault == 'deadline':
                response.read.assert_not_called()
