"""Official daily windows preserve PIT adjustment and RAW execution prices."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D, localcontext
from hashlib import sha256
import inspect
import json
from pathlib import Path
import unittest

from quantlab.trading.adapters.official.stock_data import parse_daily
from quantlab.trading.application.codec import dumps
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.daily_signal_data import DailyResearchBasis, DailySignalPolicy, OfficialDailyHistory
from quantlab.trading.domain.stock_history import ADJUSTMENT_METHOD, CorporateAction, DailyStockBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.daily_signals import OfficialDailySignalSource

FIXTURES = Path(__file__).parent / 'fixtures/daily_signal_data'
TAIPEI = timezone(timedelta(hours=8))


class DailySignalDataTests(unittest.TestCase):
    def setUp(self):
        # Synthetic explicit DAY coverage; these dates do not attest exchange holidays.
        self.days = tuple(date(2025, 5, 1) + timedelta(days=index) for index in range(40))
        self.calendar = self.calendar_for(self.days)
        self.bars = tuple(
            DailyStockBar('TWSE:2330', day, D(100 + index), D(103 + index), D(98 + index), D(101 + index), index + 1, 'b' * 64)
            for index, day in enumerate(self.days)
        )
        self.history = OfficialDailyHistory('TWSE:2330', self.bars, (), datetime(2025, 7, 1, tzinfo=TAIPEI), 'a' * 64)

    def calendar_for(self, days):
        return TradingCalendar(
            'test-official-day',
            'fixture-v1',
            'EXPLICIT_TEST_DAYS',
            tuple(
                TradingSession(
                    day,
                    datetime.combine(day, datetime.min.time(), TAIPEI).replace(hour=9),
                    datetime.combine(day, datetime.min.time(), TAIPEI).replace(hour=13, minute=30),
                )
                for day in days
            ),
        )

    def event(self, *, day=None, instrument_id='TWSE:2330'):
        return CorporateAction(instrument_id, day or self.days[10], D('100'), D('90'), 'c' * 64, 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U')

    def assert_code(self, code, operation):
        with self.assertRaises(DomainError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_fixed_policy_and_fingerprint_are_deterministic(self):
        policy = DailySignalPolicy()
        self.assertEqual(
            (policy.source_id, policy.price_mode, policy.adjustment_method, policy.scope, policy.window_bars, policy.as_of_rule),
            ('OFFICIAL_STOCK_DAILY_V1', 'ADJUSTED', ADJUSTMENT_METHOD, 'EXCHANGE_REPORTED_DAILY_V1', 20, 'EX_DATE_THROUGH_COMPLETED_DAY_V1'),
        )
        self.assertEqual(policy.fingerprint, DailySignalPolicy().fingerprint)
        self.assertEqual(len(policy.fingerprint), 64)

    def test_each_unsupported_policy_axis_is_rejected(self):
        for changes in (
            {'source_id': 'MINUTE_AGGREGATE'},
            {'price_mode': 'RAW'},
            {'adjustment_method': 'guess-dividend'},
            {'scope': 'MINUTE_TRADES_ONLY'},
            {'window_bars': 19},
            {'window_bars': 20.0},
            {'as_of_rule': 'ALL_FUTURE_EVENTS'},
        ):
            with self.subTest(changes=changes):
                self.assert_code('daily_signal_source_unverified', lambda: replace(self.history.policy, **changes))

    def test_history_and_basis_are_frozen_values(self):
        basis = self.history.research_basis(self.days[0], self.days[-1])
        for obj, field, value in ((self.history, 'source_digest', 'f' * 64), (self.history.policy, 'window_bars', 1), (basis, 'end', self.days[0])):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(obj, field, value)

    def test_snapshot_requires_timezone_digest_and_typed_policy(self):
        self.assert_code('validation_failed', lambda: replace(self.history, observed_at=datetime(2025, 7, 1)))
        for digest in ('', 'x' * 64, 'a' * 63):
            self.assert_code('daily_signal_source_unverified', lambda: replace(self.history, source_digest=digest))
        self.assert_code('daily_signal_source_unverified', lambda: replace(self.history, policy='verified'))

    def test_only_twse_tpex_stock_prefixes_are_admitted(self):
        for instrument in ('TAIFEX:TMF:202611', 'UNKNOWN:2330', '2330', 'TWSE:', 'TWSE:2330:other'):
            with self.subTest(instrument=instrument):
                matching = tuple(replace(row, instrument_id=instrument) for row in self.bars)
                self.assert_code('daily_signal_source_unverified', lambda: replace(self.history, instrument_id=instrument, bars=matching))
        bars = tuple(replace(row, instrument_id='TPEX:6225') for row in self.bars)
        self.assertEqual(replace(self.history, instrument_id='TPEX:6225', bars=bars).instrument_id, 'TPEX:6225')

    def test_history_requires_nonempty_immutable_ordered_unique_official_rows(self):
        for bars in ((), list(self.bars)):
            self.assert_code('daily_signal_not_available', lambda: replace(self.history, bars=bars))
        for bars in ((object(),), (*self.bars, self.bars[-1]), tuple(reversed(self.bars)), (replace(self.bars[0], instrument_id='TWSE:0050'), *self.bars[1:])):
            with self.subTest(kind=type(bars[0]).__name__):
                self.assert_code('daily_signal_source_unverified', lambda: replace(self.history, bars=bars))

    def test_events_must_be_typed_unique_same_instrument_and_exchange(self):
        event = self.event()
        for events in (
            [event],
            (object(),),
            (event, event),
            (self.event(instrument_id='TPEX:6225'),),
            (replace(event, source_url='https://www.tpex.org.tw/test'),),
        ):
            with self.subTest(events=events):
                self.assert_code('daily_signal_source_unverified', lambda: replace(self.history, events=events))
        bars = tuple(replace(row, instrument_id='TPEX:6225') for row in self.bars)
        tpex_event = replace(event, instrument_id='TPEX:6225', source_url='https://www.tpex.org.tw/test')
        self.assertEqual(replace(self.history, instrument_id='TPEX:6225', bars=bars, events=(tpex_event,)).events, (tpex_event,))

    def test_raw_completed_uses_actual_day_times_and_never_adjusts_fills(self):
        history = replace(self.history, events=(self.event(),))
        bars = history.raw_completed(self.calendar)
        self.assertEqual(tuple((bar.open, bar.close, bar.volume) for bar in bars), tuple((row.open, row.close, row.volume) for row in self.bars))
        for bar, session in zip(bars, self.calendar.sessions):
            self.assertEqual((bar.opened_at, bar.ended_at, bar.available_at), (session.opens_at, session.closes_at, session.closes_at))
        self.assertNotEqual(bars[-1].available_at, history.observed_at)

    def test_day_coverage_missing_ohlc_is_rejected_without_minute_requirement(self):
        missing = replace(self.history, bars=self.bars[:25] + self.bars[26:])
        self.assert_code('daily_signal_not_available', lambda: missing.raw_completed(self.calendar))
        self.assert_code('daily_signal_not_available', lambda: missing.signal_history(self.calendar, self.days[-1]))
        calendar = replace(self.calendar, sessions=tuple(row for row in self.calendar.sessions if row.trade_date != self.days[25]))
        self.assertEqual(len(missing.raw_completed(calendar)), 39)
        self.assertEqual(len(missing.signal_history(calendar, self.days[-1])), 20)

    def test_night_only_or_uncovered_dates_cannot_stand_in_for_day(self):
        calendar = replace(
            self.calendar, sessions=tuple(replace(row, kind='NIGHT') if row.trade_date == self.days[-1] else row for row in self.calendar.sessions)
        )
        self.assert_code('daily_signal_not_available', lambda: self.history.raw_completed(calendar))
        self.assert_code('daily_signal_not_available', lambda: self.history.signal_history(calendar, self.days[-1]))
        before = replace(self.calendar, sessions=self.calendar.sessions[:-1])
        self.assert_code('daily_signal_not_available', lambda: self.history.signal_history(before, self.days[-1]))

    def test_signal_window_is_at_most_twenty_and_warmup_is_allowed(self):
        self.assertEqual(len(self.history.signal_history(self.calendar, self.days[0])), 1)
        self.assertEqual(len(self.history.signal_history(self.calendar, self.days[18])), 19)
        bars = self.history.signal_history(self.calendar, self.days[35])
        self.assertEqual(len(bars), 20)
        self.assertEqual(bars[0].opened_at, self.calendar.day_session(self.days[16]).opens_at)
        self.assertEqual(bars[-1].ended_at, self.calendar.day_session(self.days[35]).closes_at)

    def test_missing_exact_through_day_or_date_type_is_rejected(self):
        for through in (self.days[0] - timedelta(days=1), self.days[-1] + timedelta(days=1)):
            self.assert_code('daily_signal_not_available', lambda: self.history.signal_history(self.calendar, through))
        missing = replace(self.history, bars=self.bars[:10] + self.bars[11:])
        self.assert_code('daily_signal_not_available', lambda: missing.signal_history(self.calendar, self.days[10]))
        self.assert_code('validation_failed', lambda: self.history.signal_history(self.calendar, datetime(2025, 5, 10, tzinfo=TAIPEI)))

    def test_only_the_selected_window_requires_coverage(self):
        history = replace(self.history, bars=self.bars[:2] + self.bars[3:])
        self.assertEqual(len(history.signal_history(self.calendar, self.days[-1])), 20)

    def test_whole_window_rebuilds_at_ex_date_without_adjusting_ex_date_itself(self):
        history = replace(self.history, events=(self.event(),))
        before = history.signal_history(self.calendar, self.days[9])
        current = history.signal_history(self.calendar, self.days[10])
        self.assertEqual(tuple(bar.close for bar in before), tuple(row.close for row in self.bars[:10]))
        self.assertEqual(tuple(bar.close for bar in current[:-1]), tuple(row.close * D('.9') for row in self.bars[:10]))
        self.assertEqual(current[-1].close, self.bars[10].close)
        self.assertEqual(current[-1].open, self.bars[10].open)
        self.assertEqual(history.bars, self.bars)

    def test_future_events_and_bars_cannot_enter_a_pit_signal(self):
        future = self.event(day=self.days[30])
        history = replace(self.history, events=(future,))
        result = history.signal_history(self.calendar, self.days[20])
        self.assertEqual(tuple(bar.close for bar in result), tuple(row.close for row in self.bars[1:21]))
        self.assertLess(result[-1].ended_at, self.calendar.day_session(self.days[21]).closes_at)

    def test_domain_does_not_guess_live_publication_finality(self):
        observed = self.calendar.day_session(self.days[-1]).opens_at
        history = replace(self.history, observed_at=observed)
        self.assertEqual(history.signal_history(self.calendar, self.days[-1])[-1].available_at, self.calendar.day_session(self.days[-1]).closes_at)
        self.assertEqual(history.observed_at, observed)

    def test_trim_is_inclusive_without_changing_input_or_provenance(self):
        event = self.event()
        end_event = self.event(day=self.days[20])
        history = replace(self.history, events=(self.event(day=self.days[5]), event, end_event, self.event(day=self.days[30])))
        trimmed = history.trim(self.days[10], self.days[20])
        self.assertEqual(trimmed.bars, self.bars[10:21])
        self.assertEqual(trimmed.events, (event, end_event))
        self.assertEqual((trimmed.observed_at, trimmed.source_digest, trimmed.policy), (history.observed_at, history.source_digest, history.policy))
        self.assertEqual(history.bars, self.bars)
        self.assertEqual(len(history.events), 4)
        self.assert_code('daily_signal_not_available', lambda: history.trim(self.days[20], self.days[10]))
        self.assert_code('daily_signal_not_available', lambda: history.trim(self.days[-1] + timedelta(days=1), self.days[-1] + timedelta(days=2)))

    def test_basis_compares_every_identity_axis_but_keeps_transport_digest_for_audit(self):
        basis = self.history.research_basis(self.days[5], self.days[20])
        self.assertIsInstance(basis, DailyResearchBasis)
        self.assertEqual((basis.start, basis.end, basis.source_digest), (self.days[5], self.days[20], self.history.source_digest))
        self.assertTrue(basis.compatible(replace(basis, source_digest='f' * 64)))
        self.assertFalse(basis.compatible(object()))
        for changes in (
            {'instrument_id': 'TWSE:0050'},
            {'start': self.days[4]},
            {'end': self.days[21]},
            {'policy_fingerprint': 'f' * 64},
            {'raw_digest': 'f' * 64},
            {'events_digest': 'f' * 64},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(basis.compatible(replace(basis, **changes)))

    def test_new_month_payload_and_appended_day_do_not_invalidate_unchanged_training(self):
        old = replace(self.history, bars=self.bars[:25])
        changed_transport = replace(self.history, bars=tuple(replace(row, source_digest='f' * 64) for row in self.bars), source_digest='e' * 64)
        self.assertTrue(old.research_basis(self.days[0], self.days[24]).compatible(changed_transport.research_basis(self.days[0], self.days[24])))

    def test_basis_uses_every_raw_ohlc_and_volume_value(self):
        original = self.history.research_basis(self.days[5], self.days[20])
        row = self.bars[10]
        for changes in (
            {'open': row.open + D('.1')},
            {'high': row.high + D('1')},
            {'low': row.low - D('1')},
            {'close': row.close + D('.1')},
            {'volume': row.volume + 1},
        ):
            with self.subTest(changes=changes):
                changed = replace(self.history, bars=(*self.bars[:10], replace(row, **changes), *self.bars[11:]))
                self.assertFalse(original.compatible(changed.research_basis(self.days[5], self.days[20])))

    def test_basis_keeps_original_event_facts_even_when_ratio_is_unchanged(self):
        event = self.event()
        history = replace(self.history, events=(event,))
        original = history.research_basis(self.days[0], self.days[20])
        for changes in (
            {'previous_close': D('101')},
            {'reference_price': D('91')},
            {'ex_date': self.days[11]},
            {'previous_close': D('200'), 'reference_price': D('180')},
        ):
            with self.subTest(changes=changes):
                changed = replace(history, events=(replace(event, **changes),))
                self.assertFalse(original.compatible(changed.research_basis(self.days[0], self.days[20])))

    def test_basis_ignores_event_transport_and_out_of_range_observations(self):
        event = self.event()
        history = replace(self.history, events=(event, self.event(day=self.days[30])))
        changed = replace(
            history,
            events=(replace(event, source_digest='f' * 64, source_url=event.source_url + '?new-payload'),),
            bars=(*self.bars[:-1], replace(self.bars[-1], high=D('999'))),
            source_digest='e' * 64,
        )
        self.assertTrue(history.research_basis(self.days[0], self.days[20]).compatible(changed.research_basis(self.days[0], self.days[20])))

    def test_semantic_digests_canonicalize_decimal_values_and_event_order(self):
        events = (self.event(), self.event(day=self.days[20]))
        history = replace(self.history, events=events)
        basis = history.research_basis(self.days[0], self.days[-1])
        equivalent = replace(
            history,
            bars=tuple(
                replace(row, open=D(str(row.open) + '.000'), high=D(str(row.high) + '.00'), low=D(str(row.low) + '.0'), close=D(str(row.close) + '.0000'))
                for row in self.bars
            ),
            events=tuple(replace(row, previous_close=D('100.00'), reference_price=D('90.000')) for row in reversed(events)),
        )
        with localcontext() as context:
            context.prec = 3
            self.assertTrue(basis.compatible(equivalent.research_basis(self.days[0], self.days[-1])))
            self.assertEqual(history.policy.fingerprint, equivalent.policy.fingerprint)

    def test_raw_completed_wire_dataset_is_invariant_to_decimal_scale(self):
        initialize()
        equivalent = replace(self.history, bars=tuple(replace(row, open=D(str(row.open) + '.00'), close=D(str(row.close) + '.000')) for row in self.bars))
        raw = self.history.raw_completed(self.calendar)
        with localcontext() as context:
            context.prec = 3
            current = equivalent.raw_completed(self.calendar)
        self.assertEqual(dumps(raw), dumps(current))
        self.assertEqual(tuple((row.open, row.close) for row in raw), tuple((row.open, row.close) for row in self.bars))

    def test_old_research_dataset_reproduces_after_equivalent_refresh(self):
        initialize()
        old = replace(self.history, bars=self.bars[:25])
        basis = old.research_basis(self.days[0], self.days[24])
        old_dataset = sha256(dumps((old.raw_completed(self.calendar), basis)).encode()).hexdigest()
        refreshed = replace(
            self.history,
            bars=tuple(replace(row, source_digest='f' * 64, open=D(str(row.open) + '.000'), close=D(str(row.close) + '.00')) for row in self.bars),
            source_digest='e' * 64,
        )
        current = refreshed.trim(basis.start, basis.end)
        self.assertTrue(basis.compatible(current.research_basis(basis.start, basis.end)))
        self.assertNotEqual(current.source_digest, basis.source_digest)
        self.assertEqual(sha256(dumps((current.raw_completed(self.calendar), basis)).encode()).hexdigest(), old_dataset)

    def test_recorded_sparse_6225_official_day_needs_no_nonempty_minute_tape(self):
        raw = (FIXTURES / 'twse_6225_202506.json').read_bytes()
        bars = parse_daily(raw, 'TWSE:6225', date(2025, 6, 1))
        history = OfficialDailyHistory('TWSE:6225', bars, (), datetime(2026, 11, 2, tzinfo=TAIPEI), sha256(raw).hexdigest())
        calendar = self.calendar_for(tuple(row.trade_date for row in bars))
        signal = history.signal_history(calendar, date(2025, 6, 27))
        self.assertEqual((signal[-1].close, signal[-1].volume), (D('11.40'), 11000))
        self.assertTrue(history.raw_completed(calendar))

    def test_recorded_2330_ex_date_rebuilds_adjusted_window_and_preserves_raw(self):
        raw = (FIXTURES / 'twse_2330_202506.json').read_bytes()
        event_raw = (FIXTURES / 'twse_ex_right_20250612.json').read_bytes()
        bars = parse_daily(raw, 'TWSE:2330', date(2025, 6, 1))
        payload = json.loads(event_raw)
        row = next(row for row in payload['data'] if row[1] == '2330')
        event = CorporateAction(
            'TWSE:2330',
            date(2025, 6, 12),
            D(row[3].replace(',', '')),
            D(row[4].replace(',', '')),
            sha256(event_raw).hexdigest(),
            'https://www.twse.com.tw/rwd/zh/exRight/TWT49U',
        )
        history = OfficialDailyHistory('TWSE:2330', bars, (event,), datetime(2026, 11, 2, tzinfo=TAIPEI), sha256(raw).hexdigest())
        calendar = self.calendar_for(tuple(row.trade_date for row in bars))
        before = history.signal_history(calendar, date(2025, 6, 11))
        adjusted = history.signal_history(calendar, date(2025, 6, 12))
        self.assertEqual(before[-1].close, D('1065.00'))
        self.assertEqual((adjusted[-2].close, adjusted[-1].close), (D('1060.49'), D('1045.00')))
        raw_bars = history.raw_completed(calendar)
        self.assertEqual(next(row.close for row in raw_bars if row.ended_at.date() == date(2025, 6, 11)), D('1065.00'))

    def test_source_port_is_read_only_and_has_explicit_keyword_range(self):
        parameters = inspect.signature(OfficialDailySignalSource.history).parameters
        self.assertEqual(tuple(parameters), ('self', 'instrument_id', 'calendar', 'through', 'start', 'cached_only'))
        self.assertEqual(parameters['cached_only'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameters['cached_only'].default, False)
        self.assertEqual(parameters['through'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(parameters['start'].default)
        self.assertFalse(any(name in OfficialDailySignalSource.__dict__ for name in ('submit', 'cancel', 'place_order')))

    def test_explicit_fake_source_never_fabricates_an_unpublished_close(self):
        from official_daily_fixtures import FakeOfficialDailySource, fake_official_history

        source = FakeOfficialDailySource()
        self.assert_code('daily_signal_source_unverified', lambda: source.history(self.history.instrument_id, self.calendar, through=self.days[-1]))
        history = fake_official_history(self.history.instrument_id, self.history.raw_completed(self.calendar), self.history.observed_at)
        source.publish(history)
        current = source.history(history.instrument_id, self.calendar, through=self.days[20], start=self.days[5])
        self.assertEqual(tuple(row.trade_date for row in current.bars), self.days[5:21])
        self.assertEqual(current.observed_at, history.observed_at)
        self.assert_code('daily_signal_not_available', lambda: source.history(history.instrument_id, self.calendar, through=self.days[-1] + timedelta(days=1)))

    def test_memory_fixture_generates_real_official_research_and_saved_signal_hash(self):
        from official_daily_fixtures import fake_official_history, official_intent_fixture, official_research_fixture
        import test_m2_automatic as fixtures
        from quantlab.trading.application.daily_signal_data import assert_daily_intent_source, official_daily_result
        from quantlab.trading.application.daily_state import create_intent
        from quantlab.trading.domain.auto_cycle import EvaluationCursor
        from quantlab.trading.domain.strategy import CompletedBar

        engine = fixtures.MemoryEngine()
        record = replace(engine.record, parameters=replace(engine.record.parameters, bar_interval='1d'))
        sessions = tuple(row for row in engine.calendar.sessions if row.kind == 'DAY' and row.closes_at < engine.clock.now())[-25:]
        bars = tuple(CompletedBar(row.opens_at, row.closes_at, row.closes_at, D('10'), D('11'), 1000) for row in sessions)
        history = fake_official_history(record.form.instrument_id, bars, engine.clock.now())
        record, result = official_research_fixture(engine, record, history)
        self.assertIsNotNone(result.daily_basis)
        self.assertEqual(official_daily_result(engine, record, result).research_basis(result.daily_basis.start, result.daily_basis.end), result.daily_basis)
        calendar = engine._strategy_calendar(record, record.form.instrument_id)
        cursor = EvaluationCursor(
            record.strategy_id, record.version, record.form.instrument_id, '1d', calendar.day_session(history.bars[-1].trade_date).closes_at
        )
        intent = create_intent(cursor, record.form.account_ref, 'ENTRY', cursor.instrument_id, '', result.fingerprint, calendar, cursor.bar_end)
        saved = official_intent_fixture(engine, record, intent)
        self.assertEqual(len(saved.data_fingerprint), 64)
        self.assertEqual(saved.data_policy_fingerprint, history.policy.fingerprint)
        assert_daily_intent_source(engine, record, saved)

    def test_fake_fixture_does_not_replace_an_existing_engine_calendar_authority(self):
        from official_daily_fixtures import install_fake_official_source
        from types import SimpleNamespace

        sentinel = lambda record, instrument_id=None: self.calendar
        engine = SimpleNamespace(_strategy_calendar=sentinel)
        source = install_fake_official_source(engine, self.history)
        self.assertIs(engine._strategy_calendar, sentinel)
        self.assertIs(install_fake_official_source(engine, self.history), source)


if __name__ == '__main__':
    unittest.main()
