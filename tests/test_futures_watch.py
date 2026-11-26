"""Watch-only continuous futures: identity, sessions, adapter, history, service and alert rules (offline fakes)."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.market_session import MarketSession, TAIPEI, WatchSessionResolver
from quantlab.trading.adapters.shioaji.sdk import SDK_VERSION
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.alert_observer import AlertTickObserver
from quantlab.trading.application.contracts import MarketSeriesQuery, MarketWatchView
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.application.market_terminal_service import MarketTerminalService
from quantlab.trading.application.market_terminal_views import watch_view
from quantlab.trading.domain.alerts import SCANNER_KINDS, AlertKind, AlertRule
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.futures_hours import in_session, minutes_since_open, trade_date_at
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import (
    FIXED_INDICES,
    FUTURE_NAMES,
    STOCK_FUTURE_CATEGORY,
    WatchInstrument,
    WatchKind,
    is_future,
    is_stock_future_code,
    stock_future,
    watch_future,
)
from quantlab.trading.runtime.sinopac_calendar import built_in_calendar
from tests.test_market_session import FakeApi, FakeSecrets

BIG, SMALL, MICRO = (watch_future(code) for code in ('TXFR1', 'MXFR1', 'TMFR1'))
STOCK = WatchInstrument('TWSE:2330', WatchKind.STOCK, 'TSE', '2330', 'TSMC')


def taipei(*parts):
    return datetime(*parts, tzinfo=TAIPEI)


class WatchInstrumentTests(unittest.TestCase):
    def test_three_continuous_futures_use_the_taifex_prefix(self):
        self.assertEqual(('TXFR1', 'MXFR1', 'TMFR1'), tuple(FUTURE_NAMES))
        self.assertEqual(('TAIFEX:TXFR1', WatchKind.FUTURE, 'TAIFEX'), (BIG.instrument_id, BIG.kind, BIG.exchange))
        self.assertEqual('TAIFEX:TMFR1', MICRO.instrument_id)

    def test_kind_exchange_prefix_and_code_whitelist_are_enforced(self):
        bad = (
            ('TAIFEX:TXFR1', WatchKind.STOCK, 'TAIFEX', 'TXFR1'),  # kind must match the exchange
            ('TAIFEX:TXFR1', WatchKind.FUTURE, 'TSE', 'TXFR1'),
            ('TWSE:TXFR1', WatchKind.FUTURE, 'TAIFEX', 'TXFR1'),  # the prefix must be TAIFEX
            ('TAIFEX:TXFL6', WatchKind.FUTURE, 'TAIFEX', 'TXFL6'),  # a delivery month is not a watch item
            ('TAIFEX:TMF:202612', WatchKind.FUTURE, 'TAIFEX', 'TMF:202612'),  # never the executable TMF identity
            ('TAIFEX:TXFR2', WatchKind.FUTURE, 'TAIFEX', 'TXFR2'),
        )
        for instrument_id, kind, exchange, code in bad:
            with self.subTest(instrument_id=instrument_id, kind=kind, exchange=exchange), self.assertRaises(DomainError) as caught:
                WatchInstrument(instrument_id, kind, exchange, code, 'name')
            self.assertEqual('validation_failed', caught.exception.code)

    def test_existing_stock_and_index_identities_are_unchanged(self):
        self.assertEqual('TWSE:2330', STOCK.instrument_id)
        self.assertEqual(WatchKind.INDEX, FIXED_INDICES[0].kind)

    def test_a_continuous_stock_future_is_a_history_only_identity_carrying_its_category(self):
        item = stock_future('CDFR1', '台積電期貨 近月')
        self.assertEqual(
            ('TAIFEX:CDFR1', WatchKind.FUTURE, 'TAIFEX', 'CDFR1', STOCK_FUTURE_CATEGORY),
            (item.instrument_id, item.kind, item.exchange, item.code, item.category),
        )
        self.assertTrue(is_future(item.instrument_id))
        self.assertEqual(('TXFR1', 'MXFR1', 'TMFR1'), tuple(FUTURE_NAMES))  # the watch whitelist itself is untouched
        self.assertTrue(is_stock_future_code('CM1R1'))  # some products have a digit in their code

    def test_a_stock_future_needs_its_category_and_the_front_month_code_shape(self):
        refused = (
            ('CDFR1', ''),  # the category is what marks it: a bare future code outside the whitelist stays refused
            ('CDFR1', 'FUT'),
            ('CDFR2', STOCK_FUTURE_CATEGORY),  # second month
            ('CDFL6', STOCK_FUTURE_CATEGORY),  # a delivery month
            ('CDR1', STOCK_FUTURE_CATEGORY),
            ('CDFXR1', STOCK_FUTURE_CATEGORY),
            ('CDFL1', STOCK_FUTURE_CATEGORY),  # a delivery month of year 1 ends in 1 as well
            ('CD-R1', STOCK_FUTURE_CATEGORY),
            ('CD R1', STOCK_FUTURE_CATEGORY),
            ('cdfr1', STOCK_FUTURE_CATEGORY),
            ('cdfR1', STOCK_FUTURE_CATEGORY),  # product characters are upper case or digits
            ('CDfR1', STOCK_FUTURE_CATEGORY),
            ('CDF:R1', STOCK_FUTURE_CATEGORY),
            ('TMF:202612', STOCK_FUTURE_CATEGORY),  # never the executable TMF identity
        )
        for code, category in refused:
            with self.subTest(code=code, category=category), self.assertRaises(DomainError) as caught:
                WatchInstrument(f'TAIFEX:{code}', WatchKind.FUTURE, 'TAIFEX', code, 'name', category)
            self.assertEqual('validation_failed', caught.exception.code)
        for identity in (
            ('TAIFEX:CDFR1', WatchKind.STOCK, 'TAIFEX', 'CDFR1'),  # the category opens nothing else: kind must still match the exchange
            ('TWSE:CDFR1', WatchKind.FUTURE, 'TSE', 'CDFR1'),
        ):
            with self.subTest(identity=identity), self.assertRaises(DomainError):
                WatchInstrument(*identity, 'name', STOCK_FUTURE_CATEGORY)
        self.assertFalse(is_stock_future_code('CDFR1\n'))
        self.assertFalse(is_stock_future_code(None))


class FuturesHoursTests(unittest.TestCase):
    def test_day_session_belongs_to_its_own_date(self):
        self.assertEqual((date(2026, 11, 20), 'DAY'), trade_date_at(taipei(2026, 11, 20, 8, 45)))
        self.assertEqual((date(2026, 11, 20), 'DAY'), trade_date_at(taipei(2026, 11, 20, 13, 45, 30)))

    def test_night_session_belongs_to_the_next_trading_day_across_midnight(self):
        self.assertEqual((date(2026, 11, 20), 'NIGHT'), trade_date_at(taipei(2026, 11, 19, 15, 0)))  # Thursday evening
        self.assertEqual((date(2026, 11, 20), 'NIGHT'), trade_date_at(taipei(2026, 11, 19, 23, 59, 59)))
        self.assertEqual((date(2026, 11, 20), 'NIGHT'), trade_date_at(taipei(2026, 11, 20, 0, 0)))  # after midnight, same night
        self.assertEqual((date(2026, 11, 20), 'NIGHT'), trade_date_at(taipei(2026, 11, 20, 5, 0, 30)))
        # Friday evening and Saturday's small hours both belong to Monday.
        self.assertEqual((date(2026, 11, 23), 'NIGHT'), trade_date_at(taipei(2026, 11, 20, 20, 0)))
        self.assertEqual((date(2026, 11, 23), 'NIGHT'), trade_date_at(taipei(2026, 11, 21, 3, 0)))

    def test_times_outside_regular_hours_and_weekend_sessions_are_refused(self):
        for moment in (
            taipei(2026, 11, 20, 8, 44, 59),
            taipei(2026, 11, 20, 13, 46),
            taipei(2026, 11, 20, 14, 59),
            taipei(2026, 11, 20, 5, 1),
            taipei(2026, 11, 21, 10, 0),  # Saturday day session
            taipei(2026, 11, 21, 20, 0),  # Saturday evening
            taipei(2026, 11, 22, 3, 0),  # small hours after a Saturday evening
            taipei(2026, 11, 22, 20, 0),  # Sunday evening
            taipei(2026, 11, 23, 2, 0),  # small hours after a Sunday evening
        ):
            with self.subTest(moment=moment), self.assertRaises(DomainError) as caught:
                trade_date_at(moment)
            self.assertEqual('calendar_missing', caught.exception.code)
            self.assertFalse(in_session(moment))

    def test_in_session_matches_trade_date_at(self):
        self.assertTrue(in_session(taipei(2026, 11, 20, 10, 0)))
        self.assertTrue(in_session(taipei(2026, 11, 20, 23, 0)))
        self.assertTrue(in_session(taipei(2026, 11, 21, 4, 0)))
        self.assertFalse(in_session(taipei(2026, 11, 20, 14, 0)))

    def test_verified_day_set_skips_a_holiday_for_the_night_session(self):
        days = tuple(date(2026, 11, day) for day in (18, 19, 23, 24))  # Friday the 20th is a holiday
        self.assertEqual((date(2026, 11, 23), 'NIGHT'), trade_date_at(taipei(2026, 11, 19, 21, 0), days))
        self.assertEqual((date(2026, 11, 23), 'NIGHT'), trade_date_at(taipei(2026, 11, 20, 1, 0), days))
        self.assertEqual((date(2026, 11, 20), 'NIGHT'), trade_date_at(taipei(2026, 11, 19, 21, 0)))  # no day set: next weekday

    def test_scheduled_calendar_boundaries_around_the_2026_national_day_holiday(self):
        days = built_in_calendar().days
        self.assertNotIn(date(2026, 10, 9), days)
        self.assertEqual((date(2026, 10, 12), 'NIGHT'), trade_date_at(taipei(2026, 10, 8, 16, 0), days))
        self.assertEqual((date(2026, 10, 12), 'NIGHT'), trade_date_at(taipei(2026, 10, 9, 2, 0), days))
        self.assertEqual((date(2026, 11, 2), 'NIGHT'), trade_date_at(taipei(2026, 10, 30, 22, 0), days))
        # Past the covered year only the next weekday is known.
        self.assertEqual((date(2027, 1, 1), 'NIGHT'), trade_date_at(taipei(2026, 12, 31, 22, 0), days))

    def test_minutes_since_the_session_opened(self):
        self.assertEqual(5, minutes_since_open(taipei(2026, 11, 20, 8, 50)))
        self.assertEqual(10, minutes_since_open(taipei(2026, 11, 20, 15, 10)))
        self.assertEqual(570, minutes_since_open(taipei(2026, 11, 21, 0, 30)))


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'market' / 'symbol_directory.json'
        self.calls = []
        futures = [SimpleNamespace(code=code, exchange='TAIFEX') for code in ('TXFR1', 'MXFR1', 'TMFR1', 'TXFR2', 'TXFL6', 'MXFL6')]
        stocks = [SimpleNamespace(code='2330', exchange='TSE')]
        self.facade = SimpleNamespace(
            market_contracts=lambda kind: {'STK': stocks, 'IND': [], 'FUT': futures}[kind],
            market_contract_info=lambda base: self.calls.append(base.code) or SimpleNamespace(name='Name ' + base.code),
        )
        self.now = datetime(2026, 11, 20, 1, tzinfo=timezone.utc)

    def test_only_the_three_continuous_contracts_are_taken_with_fixed_chinese_names(self):
        items = SymbolDirectory(self.path).refresh(self.facade, self.now)
        futures = {item.instrument_id: item for item in items if item.kind is WatchKind.FUTURE}
        self.assertEqual({'TAIFEX:TXFR1', 'TAIFEX:MXFR1', 'TAIFEX:TMFR1'}, set(futures))
        self.assertEqual('臺股期貨近月', futures['TAIFEX:TXFR1'].name)
        self.assertEqual(['2330'], self.calls)  # futures never trigger a per-contract info lookup
        self.assertEqual(3, json.loads(self.path.read_text(encoding='utf-8'))['version'])
        self.assertEqual(items, SymbolDirectory(self.path).items)  # the new rows survive a cache round trip

    def test_a_contract_the_broker_does_not_list_is_not_offered(self):
        self.facade.market_contracts = lambda kind: [SimpleNamespace(code='TXFR1', exchange='TAIFEX')] if kind == 'FUT' else []
        items = SymbolDirectory(self.path).refresh(self.facade, self.now)
        self.assertEqual(['TAIFEX:TXFR1'], [item.instrument_id for item in items if item.kind is WatchKind.FUTURE])

    def test_an_unreadable_futures_list_never_blocks_stocks_and_is_retried_at_the_next_connection(self):
        def broken(kind):
            if kind == 'FUT':
                raise RuntimeError('vendor text')
            return [SimpleNamespace(code='2330', exchange='TSE')] if kind == 'STK' else []

        self.facade.market_contracts = broken
        directory = SymbolDirectory(self.path)
        with self.assertLogs('quantlab.trading.adapters.shioaji.symbol_directory', 'ERROR') as logs:
            items = directory.refresh(self.facade, self.now)
        self.assertNotIn('vendor text', ' '.join(logs.output))
        self.assertIn('TWSE:2330', {item.instrument_id for item in items})
        self.assertFalse(any(item.kind is WatchKind.FUTURE for item in items))
        self.facade.market_contracts = lambda kind: [SimpleNamespace(code='TXFR1', exchange='TAIFEX')] if kind == 'FUT' else []
        retried = directory.refresh(self.facade, self.now + timedelta(hours=1))  # same day, but the cache was incomplete
        self.assertIn('TAIFEX:TXFR1', {item.instrument_id for item in retried})

    def test_an_incomplete_cache_is_refreshed_again_after_a_restart_the_same_day(self):
        self.facade.market_contracts = lambda kind: self._broken(kind)
        SymbolDirectory(self.path).refresh(self.facade, self.now)
        restarted = SymbolDirectory(self.path)
        self.facade.market_contracts = lambda kind: [SimpleNamespace(code='TXFR1', exchange='TAIFEX')] if kind == 'FUT' else []
        items = restarted.refresh(self.facade, self.now + timedelta(hours=1))
        self.assertIn('TAIFEX:TXFR1', {item.instrument_id for item in items})

    @staticmethod
    def _broken(kind):
        if kind == 'FUT':
            raise RuntimeError('vendor text')
        return [SimpleNamespace(code='2330', exchange='TSE')] if kind == 'STK' else []

    def test_a_version_two_cache_still_loads_and_is_rebuilt_on_the_next_refresh(self):
        self.path.parent.mkdir(parents=True)
        old = {'version': 2, 'fetched_at': self.now.isoformat(), 'items': [['TWSE:2330', 'STOCK', 'TSE', '2330', 'TSMC', '']]}
        self.path.write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
        directory = SymbolDirectory(self.path)
        self.assertIn('TWSE:2330', {item.instrument_id for item in directory.items})  # readable offline
        self.assertFalse(any(item.kind is WatchKind.FUTURE for item in directory.items))
        items = directory.refresh(self.facade, self.now + timedelta(hours=1))  # same day, yet rebuilt
        self.assertEqual(3, sum(item.kind is WatchKind.FUTURE for item in items))
        self.assertEqual(3, json.loads(self.path.read_text(encoding='utf-8'))['version'])

    def test_a_cache_with_a_history_only_stock_future_row_is_ignored_like_any_unwatchable_future(self):
        self.path.parent.mkdir(parents=True)
        for row in (['TAIFEX:CDFR1', 'FUTURE', 'TAIFEX', 'CDFR1', '台積電期貨 近月', 'STKFUT'],):
            body = {'version': 3, 'fetched_at': self.now.isoformat(), 'items': [['TWSE:2330', 'STOCK', 'TSE', '2330', 'TSMC', ''], row]}
            self.path.write_text(json.dumps(body), encoding='utf-8')
            self.assertEqual(FIXED_INDICES, SymbolDirectory(self.path).items)  # the stock row is dropped with the file: it is rebuilt at the next refresh

    def test_a_cache_with_an_unwatchable_future_is_ignored_not_fatal(self):
        self.path.parent.mkdir(parents=True)
        bad = {'version': 3, 'fetched_at': self.now.isoformat(), 'items': [['TAIFEX:TXFL6', 'FUTURE', 'TAIFEX', 'TXFL6', 'x', '']]}
        self.path.write_text(json.dumps(bad), encoding='utf-8')
        self.assertEqual(FIXED_INDICES, SymbolDirectory(self.path).items)


class SessionHarness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.api = FakeApi()
        values = self.api.contracts.values
        for code, target in (('TXFR1', 'TXFL6'), ('MXFR1', 'MXFL6'), ('TMFR1', 'TMFL6')):
            values[code] = SimpleNamespace(code=code, security_type='FUT', exchange='TAIFEX', target_code=target)
        self.api.contracts.info = lambda base: SimpleNamespace(name='Name ' + base.code, reference=Decimal('20000'))
        sdk = SimpleNamespace(__version__=SDK_VERSION, Shioaji=lambda **kwargs: self.api, QuoteType=lambda value: value, QuoteVersion=lambda value: value)
        self.now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        clock = SimpleNamespace(now=lambda: self.now)
        directory = SymbolDirectory(Path(self.temp.name) / 'market' / 'symbol_directory.json')
        self.session = MarketSession(MarketDataSettings(enabled=True), FakeSecrets(), sdk, clock, directory)
        self.session.connect()


class FuturesSessionTests(SessionHarness):
    def test_directory_refresh_at_connect_lists_the_watch_futures(self):
        self.assertEqual({BIG, SMALL, MICRO}, {item for item in self.session.directory.items if item.kind is WatchKind.FUTURE})

    def test_subscribe_uses_the_tick_feed_and_keeps_the_previous_settlement_as_reference(self):
        self.session.subscribe(BIG)
        self.assertIn(('subscribe', 'TXFR1', 'tick'), self.api.calls)
        self.assertEqual(Decimal('20000'), self.session.quote_details(BIG.instrument_id)['reference_price'])
        self.assertEqual(1, sum(call[0] == 'login' for call in self.api.calls))

    def test_contract_check_accepts_only_a_taifex_future_for_a_future(self):
        values = self.api.contracts.values
        self.assertEqual('TXFR1', self.session._contract(BIG).code)
        wrong = (
            SimpleNamespace(code='TXFR1', security_type='STK', exchange='TSE'),  # a stock under the future's code
            SimpleNamespace(code='TXFR1', security_type='FUT', exchange='TSE'),  # a future on the wrong exchange
            SimpleNamespace(code='TXFR1', security_type='IND', exchange='TSE'),
            SimpleNamespace(code='OTHER', security_type='FUT', exchange='TAIFEX'),  # another contract's code
        )
        for contract in wrong:
            values['TXFR1'] = contract
            with self.subTest(contract=contract), self.assertRaises(DomainError) as caught:
                self.session._contract(BIG)
            self.assertEqual('symbol_not_found', caught.exception.code)
        values['2330'] = SimpleNamespace(code='2330', security_type='FUT', exchange='TAIFEX')  # a stock instrument must not take a future
        with self.assertRaises(DomainError) as caught:
            self.session._contract(STOCK)
        self.assertEqual('symbol_not_found', caught.exception.code)

    def test_a_refused_future_subscription_reports_the_fixed_subscription_code(self):
        self.api.contracts.values['TXFR1'] = SimpleNamespace(code='TXFR1', security_type='STK', exchange='TSE')
        with self.assertRaises(DomainError) as caught:
            self.session.subscribe(BIG)
        self.assertEqual('market_data_subscription_failed', caught.exception.code)
        self.assertNotIn(BIG.instrument_id, self.session.subscriptions)

    def test_five_levels_are_refused_for_a_future_without_touching_the_sdk(self):
        self.session.subscribe(BIG)
        before = len(self.api.calls)
        with self.assertRaises(DomainError) as caught:
            self.session.subscribe_bidask(BIG)
        self.assertEqual('validation_failed', caught.exception.code)
        self.assertEqual(before, len(self.api.calls))
        self.assertEqual({}, self.session.bidask_subscriptions)

    def test_the_futures_tick_callback_delivers_day_and_night_ticks_with_their_trade_dates(self):
        self.session.subscribe(BIG)
        deliver = self.api.callbacks['fop']
        stamp = lambda *parts: datetime(*parts)  # the SDK sends naive Taipei wall-clock times
        with self.assertLogs('quantlab.trading.adapters.shioaji.tick_stream', 'ERROR') as logs:  # only the between-sessions tick is rejected
            for moment, price in (
                (stamp(2026, 11, 19, 10, 0, 1), 20010),
                (stamp(2026, 11, 19, 16, 0, 1), 20020),  # Thursday evening: Friday's night session
                (stamp(2026, 11, 20, 1, 0, 1), 20030),  # after midnight, still Friday's
                (stamp(2026, 11, 20, 14, 0, 0), 20040),  # between sessions: dropped
                (stamp(2026, 11, 20, 20, 0, 1), 20050),  # Friday evening: Monday's night session
            ):
                deliver(SimpleNamespace(code='TXFR1', datetime=moment, close=price, volume=2, total_volume=100, open=20000, high=20100, low=19900))
            deliver(SimpleNamespace(code='TXFL6', datetime=stamp(2026, 11, 20, 20, 0, 2), close=20060, volume=1))  # the pointed-to month
        self.assertEqual(1, len(logs.output))
        ticks = self.session.drain_ticks(10)
        self.assertEqual(
            [
                (date(2026, 11, 19), 'DAY'),
                (date(2026, 11, 20), 'NIGHT'),
                (date(2026, 11, 20), 'NIGHT'),
                (date(2026, 11, 23), 'NIGHT'),
                (date(2026, 11, 23), 'NIGHT'),
            ],
            [(tick.trade_date, tick.session) for tick in ticks],
        )
        self.assertEqual({BIG.instrument_id}, {tick.instrument_id for tick in ticks})
        details = self.session.quote_details(BIG.instrument_id)
        self.assertEqual((100, Decimal('20100'), Decimal('19900')), (details['total_volume'], details['high'], details['low']))
        self.assertNotIn('bid', details)

    def test_the_previous_settlement_is_not_reused_on_a_later_trade_date(self):
        self.session.subscribe(BIG)
        deliver = self.api.callbacks['fop']
        deliver(SimpleNamespace(code='TXFR1', datetime=datetime(2026, 11, 20, 10, 0, 1), close=20010, volume=1))
        self.assertEqual(Decimal('20000'), self.session.quote_details(BIG.instrument_id)['reference_price'])
        deliver(SimpleNamespace(code='TXFR1', datetime=datetime(2026, 11, 20, 13, 44, 1), close=20020, volume=1))
        self.assertIn('reference_price', self.session.quote_details(BIG.instrument_id))  # same trade date
        deliver(SimpleNamespace(code='TXFR1', datetime=datetime(2026, 11, 20, 16, 0, 1), close=20030, volume=1))  # Monday's night
        self.assertNotIn('reference_price', self.session.quote_details(BIG.instrument_id))

    def test_a_resubscribe_on_a_later_trade_date_keeps_its_fresh_reference(self):
        self.session.subscribe(BIG)
        deliver = self.api.callbacks['fop']
        deliver(SimpleNamespace(code='TXFR1', datetime=datetime(2026, 11, 19, 10, 0, 1), close=20010, volume=1))
        self.session.unsubscribe(BIG.instrument_id)
        self.api.contracts.info = lambda base: SimpleNamespace(name='n', reference=Decimal('20100'))
        self.session.subscribe(BIG)
        deliver(SimpleNamespace(code='TXFR1', datetime=datetime(2026, 11, 20, 10, 0, 1), close=20110, volume=1))
        self.assertEqual(Decimal('20100'), self.session.quote_details(BIG.instrument_id)['reference_price'])

    def wall(self, *parts):
        return int(datetime(*parts, tzinfo=timezone.utc).timestamp() * 1e9)

    def test_futures_history_labels_day_and_night_bars_and_drops_off_session_minutes(self):
        rows = (
            self.wall(2026, 10, 30, 10, 1),  # day bar 10:00
            self.wall(2026, 10, 30, 14, 31),  # 14:30: between sessions
            self.wall(2026, 10, 30, 20, 1),  # Friday evening night bar
            self.wall(2026, 10, 31, 0, 11),  # Saturday small hours, same night
            self.wall(2026, 10, 31, 11, 1),  # Saturday day: not a session
        )
        count = len(rows)
        self.api.raw = SimpleNamespace(ts=list(rows), Open=[100] * count, High=[102] * count, Low=[99] * count, Close=[101] * count, Volume=[4] * count)
        start = datetime(2026, 10, 30, tzinfo=TAIPEI).astimezone(timezone.utc)
        bars = self.session.history(BIG, start, start + timedelta(days=2))
        self.assertEqual(
            [(date(2026, 10, 30), 'DAY'), (date(2026, 11, 2), 'NIGHT'), (date(2026, 11, 2), 'NIGHT')],
            [(bar.trade_date, bar.session) for bar in bars],
        )
        self.assertEqual(datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc), bars[0].start)
        self.assertIn(('kbars', 'TXFR1', '2026-10-30', '2026-11-01'), self.api.calls)

    def test_stock_future_history_asks_for_the_continuous_contract_and_labels_the_day_session(self):
        values = self.api.contracts.values
        values['CDFR1'] = SimpleNamespace(code='CDFR1', security_type='FUT', exchange='TAIFEX', target_code='CDFL6')
        item = stock_future('CDFR1', '台積電期貨 近月')
        rows = (
            self.wall(2026, 10, 30, 10, 1),  # day bar 10:00
            self.wall(2026, 10, 30, 14, 31),  # 14:30: after the 13:45 close, dropped
            self.wall(2026, 10, 31, 11, 1),  # Saturday: not a session
        )
        count = len(rows)
        self.api.raw = SimpleNamespace(ts=list(rows), Open=[100] * count, High=[102] * count, Low=[99] * count, Close=[101] * count, Volume=[4] * count)
        start = datetime(2026, 10, 30, tzinfo=TAIPEI).astimezone(timezone.utc)
        bars = self.session.history(item, start, start + timedelta(days=2))
        self.assertEqual([('TAIFEX:CDFR1', date(2026, 10, 30), 'DAY')], [(bar.instrument_id, bar.trade_date, bar.session) for bar in bars])
        self.assertIn(('kbars', 'CDFR1', '2026-10-30', '2026-11-01'), self.api.calls)
        values['CDFR1'] = SimpleNamespace(code='CDFR1', security_type='STK', exchange='TSE')  # the adapter still checks what the broker returns for the code
        with self.assertRaises(DomainError) as caught:
            self.session.history(item, start, start + timedelta(days=2))
        self.assertEqual('history_query_failed', caught.exception.code)

    def test_stock_ticks_and_history_keep_the_local_day_session(self):
        resolver = WatchSessionResolver()
        self.assertEqual((date(2026, 11, 20), 'DAY'), resolver.session_at(STOCK.instrument_id, taipei(2026, 11, 20, 20, 0)))


class Session:
    connected = True

    def __init__(self):
        self.subscribed, self.bidask = [], []

    def subscribe(self, item):
        self.subscribed.append(item.instrument_id)

    def unsubscribe(self, key):
        pass

    def subscribe_bidask(self, item):
        self.bidask.append(item.instrument_id)

    def unsubscribe_bidask(self, key):
        pass

    def bidask(self, instrument_id):
        return None

    def drain_ticks(self, limit):
        return ()

    def drain_tick_losses(self):
        return ()

    def usage(self):
        return None

    def quote_details(self, instrument_id):
        return {}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KlineStore(Path(self.temp.name) / 'klines.sqlite3')
        self.session = Session()
        self.now = datetime(2026, 11, 20, 3, 40, tzinfo=timezone.utc)  # 11:40 Taipei
        self.sync = HistorySync(self.store, self.session, now=lambda: self.now, autostart=False)
        self.service = MarketTerminalService(self.store, self.sync, self.session, lambda: (*FIXED_INDICES, BIG, SMALL), now=lambda: self.now)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.addCleanup(self.sync.close)

    def bar(self, instrument, start, day, session, close='20000'):
        price = Decimal(close)
        return LiveBar(instrument.instrument_id, start, start + timedelta(minutes=1), day, session, price, price, price, price, 3, final=True)

    def test_cached_future_keys_resolve_but_executable_tmf_keys_do_not(self):
        self.service.directory = lambda: FIXED_INDICES  # directory unavailable: the bar store still names the item
        self.store.upsert((self.bar(MICRO, self.now - timedelta(days=1), date(2026, 11, 19), 'DAY'),))
        cached = self.service.resolve(MICRO.instrument_id)
        self.assertEqual((WatchKind.FUTURE, 'TAIFEX', 'TMFR1', MICRO.name), (cached.kind, cached.exchange, cached.code, cached.name))
        tmf = replace(self.bar(MICRO, self.now - timedelta(days=1), date(2026, 11, 19), 'DAY'), instrument_id='TAIFEX:TMF:202612')
        self.store.upsert((tmf,))
        with self.assertRaises(DomainError) as caught:
            self.service.resolve('TAIFEX:TMF:202612')
        self.assertEqual('symbol_not_found', caught.exception.code)
        self.assertNotIn('TAIFEX:TMF:202612', {item.instrument_id for item in self.service.instruments()})

    def test_downloaded_stock_future_bars_in_the_store_are_data_only_and_never_watch_items(self):
        self.service.directory = lambda: FIXED_INDICES
        item = stock_future('CDFR1', '台積電期貨 近月')
        self.store.upsert((self.bar(item, self.now - timedelta(days=1), date(2026, 11, 19), 'DAY', close='1000'),))
        self.assertIn(item.instrument_id, self.store.instrument_ids())
        with self.assertRaises(DomainError) as caught:
            self.service.resolve(item.instrument_id)
        self.assertEqual('symbol_not_found', caught.exception.code)
        self.assertNotIn(item.instrument_id, {watch.instrument_id for watch in self.service.instruments()})

    def test_future_shares_the_subscription_quota_and_never_asks_for_five_levels(self):
        self.service.connected()
        self.assertTrue(self.service.select(BIG.instrument_id))
        self.assertIn(BIG.instrument_id, self.session.subscribed)
        self.assertEqual([], self.session.bidask)
        self.assertEqual(3, self.service.status().subscription_count)  # two indices plus the temporary future
        view = self.service.order_book(BIG.instrument_id)
        self.assertFalse(view.supported)
        self.service.set_watchlist((BIG.instrument_id, SMALL.instrument_id))
        self.assertEqual(4, self.service.status().subscription_count)

    def test_watching_futures_counts_against_the_same_limit_as_stocks(self):
        service = MarketTerminalService(
            self.store,
            self.sync,
            self.session,
            lambda: (*FIXED_INDICES, BIG, SMALL, MICRO),
            now=lambda: self.now,
            settings=LiveMarketSettings(subscription_limit=4),
        )
        service.set_watchlist((BIG.instrument_id, SMALL.instrument_id))  # two fixed indices plus two futures
        with self.assertRaises(DomainError) as caught:
            service.set_watchlist((BIG.instrument_id, SMALL.instrument_id, MICRO.instrument_id))
        self.assertEqual('subscription_limit_reached', caught.exception.code)
        self.assertEqual((BIG.instrument_id, SMALL.instrument_id), service.watchlist)

    def test_daily_future_bar_merges_night_and_day_into_one_trade_date_and_closes_at_1345(self):
        # Trade date 20th: Thursday night 20:00 (UTC+8) and the Friday morning, both on the 20th.
        night = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        morning = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)
        self.store.upsert(
            (
                self.bar(BIG, night, date(2026, 11, 20), 'NIGHT', '20000'),
                self.bar(BIG, morning, date(2026, 11, 20), 'DAY', '20100'),
            )
        )
        key = MarketSeriesQuery(BIG.instrument_id, '1d')
        daily = self.service.series(key).bars
        self.assertEqual(1, len(daily))
        self.assertEqual((Decimal('20000'), Decimal('20100'), 6), (daily[0].open, daily[0].close, daily[0].volume))
        self.assertFalse(daily[0].final)  # 11:40 Taipei: the day session is still open
        self.now = datetime(2026, 11, 20, 5, 40, tzinfo=timezone.utc)  # 13:40: still before the 13:45 close
        self.assertFalse(self.service.series(key).bars[0].final)
        self.now = datetime(2026, 11, 20, 5, 50, tzinfo=timezone.utc)  # 13:50
        self.assertTrue(self.service.series(key).bars[0].final)

    def test_an_evening_night_bar_belongs_to_tomorrows_open_daily_bar(self):
        self.now = datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)  # 20:30 Taipei, Friday evening
        night = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        self.store.upsert((self.bar(BIG, night, date(2026, 11, 23), 'NIGHT'),))
        daily = self.service.series(MarketSeriesQuery(BIG.instrument_id, '1d')).bars
        self.assertEqual(date(2026, 11, 23), daily[0].trade_date)
        self.assertFalse(daily[0].final)

    def test_a_friday_night_bar_opens_the_next_weekly_bar(self):
        self.now = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)  # Saturday 10:00 Taipei: the week of the 16th has closed
        friday = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)
        self.store.upsert(
            (
                self.bar(BIG, friday, date(2026, 11, 20), 'DAY', '20000'),
                self.bar(BIG, friday + timedelta(hours=11), date(2026, 11, 23), 'NIGHT', '20100'),  # Friday 20:00, trade date Monday
            )
        )
        weekly = self.service.series(MarketSeriesQuery(BIG.instrument_id, '1w')).bars
        self.assertEqual(
            [(date(2026, 11, 20), Decimal('20000'), True), (date(2026, 11, 23), Decimal('20100'), False)],
            [(item.trade_date, item.close, item.final) for item in weekly],
        )

    def test_intraday_future_periods_keep_day_and_night_apart(self):
        night = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        morning = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)
        self.store.upsert((self.bar(BIG, night, date(2026, 11, 20), 'NIGHT'), self.bar(BIG, morning, date(2026, 11, 20), 'DAY')))
        bars = self.service.series(MarketSeriesQuery(BIG.instrument_id, '15m')).bars
        self.assertEqual(['NIGHT', 'DAY'], [bar.session for bar in bars])

    def test_a_future_tick_in_the_night_session_forms_a_night_bar(self):
        self.service.connected()
        self.service.select(BIG.instrument_id)
        source = datetime(2026, 11, 20, 12, 0, 5, tzinfo=timezone.utc)
        self.session.drain_ticks = lambda limit: (Tick(BIG.instrument_id, Decimal('20000'), 2, source, source, date(2026, 11, 23), 'NIGHT'),)
        self.now = source
        self.service.poll()
        bars = self.service.series(MarketSeriesQuery(BIG.instrument_id)).bars
        self.assertEqual(('NIGHT', date(2026, 11, 23)), (bars[-1].session, bars[-1].trade_date))


class ViewTests(unittest.TestCase):
    def view(self, instrument, local, bars=(), details=None, trade_date=date(2026, 11, 20), session='NIGHT', price='20100'):
        moment = local.astimezone(timezone.utc)
        tick = Tick(instrument.instrument_id, Decimal(price), 1, moment, moment, trade_date, session)
        return watch_view(instrument.instrument_id, tick, bars, moment, True, LiveMarketSettings(), '', details or {})

    def test_change_is_measured_against_the_broker_reference_not_the_last_bar(self):
        bars = (
            LiveBar(
                BIG.instrument_id,
                datetime(2026, 11, 19, 5, 44, tzinfo=timezone.utc),
                datetime(2026, 11, 19, 5, 45, tzinfo=timezone.utc),
                date(2026, 11, 19),
                'DAY',
                *([Decimal('19990')] * 4),
                5,
                final=True,
            ),
        )
        view = self.view(BIG, taipei(2026, 11, 19, 20, 0), bars, {'reference_price': Decimal('20000')})
        self.assertEqual((Decimal('20000'), Decimal('100')), (view.reference_price, view.change))
        self.assertEqual(Decimal('0.5'), view.change_percent)
        self.assertEqual('LIVE', view.health.freshness)  # a night tick counts as in session

    def test_a_future_without_a_reference_falls_back_to_the_previous_trade_dates_close(self):
        bars = (
            LiveBar(
                BIG.instrument_id,
                datetime(2026, 11, 19, 5, 44, tzinfo=timezone.utc),
                datetime(2026, 11, 19, 5, 45, tzinfo=timezone.utc),
                date(2026, 11, 19),
                'DAY',
                *([Decimal('19900')] * 4),
                5,
                final=True,
            ),
        )
        view = self.view(BIG, taipei(2026, 11, 19, 20, 0), bars)
        self.assertEqual(Decimal('200'), view.change)

    def test_a_stock_keeps_its_bar_based_reference_first(self):
        bars = (
            LiveBar(
                STOCK.instrument_id,
                datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 19, 4, 1, tzinfo=timezone.utc),
                date(2026, 11, 19),
                'DAY',
                *([Decimal('99')] * 4),
                5,
                final=True,
            ),
        )
        view = self.view(STOCK, taipei(2026, 11, 20, 10, 0), bars, {'reference_price': Decimal('98')}, session='DAY', price='100')
        self.assertEqual(Decimal('1'), view.change)

    def test_between_futures_sessions_the_quote_is_not_live(self):
        view = self.view(BIG, taipei(2026, 11, 20, 14, 10), session='DAY')
        self.assertNotEqual('LIVE', view.health.freshness)


class AlertRuleTests(unittest.TestCase):
    def test_price_and_bar_rules_are_allowed_for_a_future(self):
        for kind in (
            AlertKind.PRICE_CROSS,
            AlertKind.CHANGE_PERCENT,
            AlertKind.FAST_MOVE,
            AlertKind.DAY_HIGH_LOW,
            AlertKind.PREV_DAY_BREAK,
            AlertKind.MA_CROSS,
            AlertKind.KD_CROSS,
            AlertKind.VOLUME_SURGE,
        ):
            with self.subTest(kind=kind):
                rule = AlertRule('rule-' + kind.value, kind, 'INSTRUMENT', BIG.instrument_id, {'price': '20000'} if kind is AlertKind.PRICE_CROSS else {})
                self.assertEqual(BIG.instrument_id, rule.instrument_id)

    def test_stock_market_signal_rules_are_refused_for_a_future(self):
        for kind in SCANNER_KINDS:
            with self.subTest(kind=kind), self.assertRaises(DomainError) as caught:
                AlertRule('rule-' + kind.value, kind, 'INSTRUMENT', BIG.instrument_id)
            self.assertEqual('alert_invalid_params', caught.exception.code)
        AlertRule('rule-limit', AlertKind.LIMIT_UP, 'INSTRUMENT', STOCK.instrument_id)  # still fine for a stock


class ObserverTests(unittest.TestCase):
    def test_opening_minutes_count_from_the_futures_session_open_not_nine_oclock(self):
        class Capture:
            rules = ()

            def __init__(self):
                self.seen = []

            def observe(self, observation):
                self.seen.append(observation)
                return ()

        capture = Capture()
        observer = AlertTickObserver(capture, lambda key: MarketWatchView(instrument_id=key), lambda key: (), lambda key: False)
        for local, session, day, expected in (
            (taipei(2026, 11, 20, 8, 55), 'DAY', date(2026, 11, 20), 10),
            (taipei(2026, 11, 20, 15, 10), 'NIGHT', date(2026, 11, 23), 10),
            (taipei(2026, 11, 21, 0, 30), 'NIGHT', date(2026, 11, 23), 570),
        ):
            moment = local.astimezone(timezone.utc)
            observer.on_tick(Tick(BIG.instrument_id, Decimal('20000'), 1, moment, moment, day, session), ())
            self.assertEqual(expected, capture.seen[-1].minutes_since_open)

    def test_a_daily_alert_bar_is_final_only_after_the_day_session_closes(self):
        class Rules:
            def __init__(self):
                self.rules = (SimpleNamespace(enabled=True, kind=AlertKind.VOLUME_SURGE, params={'period': '1d'}),)
                self.periods = []

            def observe(self, observation):
                if observation.bars:
                    self.periods.append((observation.period, observation.bars[-1].trade_date))
                return ()

        def minute(start, day, session):
            moment = start.astimezone(timezone.utc)
            return LiveBar(BIG.instrument_id, moment, moment + timedelta(minutes=1), day, session, *([Decimal('20000')] * 4), 3, final=True)

        for local, day, session, expected in (
            (taipei(2026, 11, 20, 20, 7), date(2026, 11, 23), 'NIGHT', []),  # Friday evening: Monday's trade date is still open
            (taipei(2026, 11, 21, 1, 7), date(2026, 11, 23), 'NIGHT', []),
            (taipei(2026, 11, 20, 13, 30), date(2026, 11, 20), 'DAY', []),  # before the 13:45 close
            (taipei(2026, 11, 20, 13, 46), date(2026, 11, 20), 'DAY', [('1d', date(2026, 11, 20))]),
        ):
            with self.subTest(local=local):
                service = Rules()
                observer = AlertTickObserver(service, lambda key: MarketWatchView(instrument_id=key), lambda key: (), lambda key: False)
                moment = local.astimezone(timezone.utc)
                observer.on_tick(Tick(BIG.instrument_id, Decimal('20000'), 1, moment, moment, day, session), ())
                first = minute(local - timedelta(minutes=2), day, session)
                second = minute(local - timedelta(minutes=1), day, session)
                observer.on_bars(BIG.instrument_id, (first,), moment, day)  # the first evaluation only records the baseline
                observer.on_bars(BIG.instrument_id, (first, second), moment + timedelta(minutes=1), day)
                self.assertEqual(expected, service.periods)


if __name__ == '__main__':
    unittest.main()
