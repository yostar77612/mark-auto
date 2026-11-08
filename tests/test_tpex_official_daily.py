"""TPEx (OTC) official daily bars and whole-market event evidence, against responses recorded from the official site."""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from quantlab.trading.adapters.official.daily_signal_events import daily_event_scope, parse_daily_signal_events
from quantlab.trading.adapters.official.stock_data import daily_url, events_url, parse_daily, parse_events, tpex_events_url
from quantlab.trading.domain.validation import DomainError

FIXTURES = Path(__file__).parent / 'fixtures' / 'tpex_official'
EVENTS = (FIXTURES / 'events_20250602_20250613.json').read_bytes()
JUNE = (FIXTURES / 'daily_6788_202506.json').read_bytes()
MAY = (FIXTURES / 'daily_6788_202505.json').read_bytes()
STOCK = 'TPEX:6788'
EVENT_URL = tpex_events_url(date(2025, 6, 2), date(2025, 6, 14))


def altered(raw: bytes, change) -> bytes:
    body = json.loads(raw.decode('utf-8-sig'))
    change(body)
    return json.dumps(body, ensure_ascii=False).encode()


class TpexDailyTests(unittest.TestCase):
    def test_urls_use_the_current_official_endpoints_and_are_admitted(self):
        from quantlab.trading.runtime.stock_history import validate_stock_url

        url = daily_url(STOCK, date(2025, 6, 1))
        self.assertTrue(url.startswith('https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?'))
        self.assertEqual(validate_stock_url(url), url)
        self.assertEqual(
            EVENT_URL,
            'https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d=114%2F06%2F02&ed=114%2F06%2F13',
        )
        self.assertEqual(events_url(STOCK, date(2025, 6, 2), date(2025, 6, 14)), EVENT_URL)
        self.assertEqual(validate_stock_url(EVENT_URL), EVENT_URL)
        self.assertEqual(daily_event_scope(EVENT_URL), (date(2025, 6, 2), date(2025, 6, 14)))

    def test_retired_and_stock_filtered_endpoints_are_refused(self):
        from quantlab.trading.runtime.stock_history import validate_stock_url

        retired = 'https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d=114/06&stkno=6788'
        filtered = EVENT_URL + '&stkno=6788'  # the official site ignores a stock filter, so it must not be trusted
        for url in (retired, filtered, EVENT_URL.replace('www.tpex.org.tw', 'www.example.com')):
            with self.assertRaises(DomainError):
                validate_stock_url(url)

    def test_monthly_bars_are_parsed_in_shares(self):
        bars = parse_daily(JUNE, STOCK, date(2025, 6, 1))
        self.assertEqual(len(bars), 21)
        first, last = bars[0], bars[-1]
        self.assertEqual(
            (first.trade_date, first.open, first.high, first.low, first.close), (date(2025, 6, 2), *map(Decimal, ('213.00', '220.00', '210.50', '211.00')))
        )
        self.assertEqual(first.volume, 954_000)
        self.assertEqual((last.trade_date, last.close, last.volume), (date(2025, 6, 30), Decimal('240.50'), 2_317_000))
        self.assertEqual(parse_daily(MAY, STOCK, date(2025, 5, 1))[0].trade_date, date(2025, 5, 2))

    def test_a_response_for_another_stock_or_month_is_rejected(self):
        with self.assertRaises(DomainError):
            parse_daily(JUNE, 'TPEX:6789', date(2025, 6, 1))
        with self.assertRaises(DomainError):
            parse_daily(JUNE, STOCK, date(2025, 5, 1))

    def test_a_row_count_that_is_not_attested_is_rejected(self):
        torn = altered(JUNE, lambda body: body['tables'][0]['data'].pop())
        with self.assertRaises(DomainError):
            parse_daily(torn, STOCK, date(2025, 6, 1))

    def test_source_scope_recognises_both_tpex_requests(self):
        from quantlab.trading.runtime.official_daily_source import _source_scope

        self.assertEqual(_source_scope(daily_url(STOCK, date(2025, 6, 1)), STOCK), ('daily', date(2025, 6, 1), None))
        self.assertEqual(_source_scope(EVENT_URL, STOCK), ('global_events', date(2025, 6, 2), date(2025, 6, 14)))
        with self.assertRaises(ValueError):
            _source_scope(EVENT_URL, 'TWSE:2330')  # another exchange's host

    def test_whole_market_events_give_the_stocks_event_and_prove_no_event_for_others(self):
        events = parse_daily_signal_events(EVENTS, STOCK, EVENT_URL)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].ex_date, events[0].previous_close, events[0].reference_price), (date(2025, 6, 2), Decimal('225.00'), Decimal('215.00')))
        self.assertEqual(parse_events(EVENTS, STOCK, date(2025, 6, 2), date(2025, 6, 14), EVENT_URL), events)
        self.assertEqual(parse_daily_signal_events(EVENTS, 'TPEX:6488', EVENT_URL), ())

    def test_an_unverifiable_event_response_never_counts_as_no_event(self):
        cases = {
            'range not attested': altered(EVENTS, lambda b: b.update(date='20250602~20250612')),
            'not ok': altered(EVENTS, lambda b: b.update(stat='error')),
            'row count not attested': altered(EVENTS, lambda b: b['tables'][0]['data'].pop()),
            'outside range': altered(EVENTS, lambda b: b['tables'][0]['data'][0].__setitem__(0, '114/07/01')),
            'duplicate row': altered(EVENTS, lambda b: (b['tables'][0]['data'].append(b['tables'][0]['data'][0]), b['tables'][0].update(totalCount=45))),
            'missing reference price': altered(EVENTS, lambda b: b['tables'][0]['data'][0].__setitem__(4, '0.00')),
        }
        for name, raw in cases.items():
            with self.subTest(name), self.assertRaises(DomainError):
                parse_daily_signal_events(raw, 'TPEX:6488', EVENT_URL)

    def test_the_importer_downloads_and_publishes_a_tpex_stock_atomically(self):
        from tools.import_official_daily import import_official_daily

        responses = {daily_url(STOCK, date(2025, 6, 1)): JUNE, EVENT_URL: EVENTS}
        requested = []

        def transport(url):
            requested.append(url)
            return responses[url]

        with TemporaryDirectory() as temp:
            result = import_official_daily(
                Path(temp) / 'klines.sqlite3',
                STOCK,
                date(2025, 6, 2),
                date(2025, 6, 14),
                consent_download=True,
                archive=Path(temp) / 'archive',
                transport=transport,
                clock=lambda: datetime(2025, 6, 20, tzinfo=timezone.utc),
            )
            self.assertEqual((result['status'], result['bars'], result['events']), ('IMPORTED', 10, 1))
            self.assertEqual(sorted(requested), sorted(responses))
            self.assertEqual(len(list((Path(temp) / 'archive').glob('*.json'))), 3)  # two payloads and the manifest
            again = import_official_daily(
                Path(temp) / 'klines.sqlite3',
                STOCK,
                date(2025, 6, 2),
                date(2025, 6, 14),
                manifest=Path(temp) / 'archive' / 'manifest.json',
                clock=lambda: datetime(2025, 6, 21, tzinfo=timezone.utc),
            )
            self.assertEqual((again['bars'], again['events']), (10, 1))  # replayable offline from the archive


if __name__ == '__main__':
    unittest.main()
