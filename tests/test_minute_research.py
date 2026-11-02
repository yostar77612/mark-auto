"""Synthetic training-only minute grids and exact next-open/cost evidence."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.minute_research import research_minutes, validate_minute_request
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.research import ResearchResult, research_fingerprint
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.minute_contract import HistoricalContractEvidence
from quantlab.trading.domain.minute_research import TAIPEI, MinuteResearchSettings, complete_minutes
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Side
from quantlab.trading.domain.strategy import Rule, StrategyDefinition, StrategyParameters
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_catalog
from quantlab.trading.runtime.research_worker import ResearchJob, SpawnResearchRunner


def fixture(days=(date(2026, 10, 29),), *, length=20, opening=13 * 60 + 20):
    initialize()
    spec = synthetic_catalog().instruments[1]
    sessions = tuple(
        TradingSession(
            day,
            datetime(day.year, day.month, day.day, opening // 60, opening % 60, tzinfo=TAIPEI),
            datetime(day.year, day.month, day.day, opening // 60, opening % 60, tzinfo=TAIPEI) + timedelta(minutes=length),
        )
        for day in days
    )
    calendar = TradingCalendar('fake-minute-calendar', 'fixture-v1', 'RECORDED_TEST', sessions)
    rows = []
    for session in sessions:
        for i in range(length):
            start = session.opens_at + timedelta(minutes=i)
            price = Decimal(20000 + i)
            rows.append(
                LiveBar(spec.instrument_id, start, start + timedelta(minutes=1), session.trade_date, 'DAY', price, price + 1, price - 1, price, i + 1, True)
            )
    form = StrategyForm(
        'minute-training',
        spec.market,
        HoldingKind.INTRADAY,
        0,
        0,
        Side.BUY,
        spec.instrument_id,
        'local-futures',
        Environment.LOCAL,
        Decimal('100000'),
        Decimal('0.02'),
        'BUY_AND_HOLD',
    )
    strategy = StrategyRecord('minute-fixture', 1, form, HoldingPolicy(HoldingKind.INTRADAY, 0, 0), 'RULE_VALID')
    settings = MinuteResearchSettings(days[0], days[-1], minimum=1, maximum=3)
    return strategy, spec, calendar, tuple(rows), FeeSchedule(), settings


class MinuteResearchTests(unittest.TestCase):
    def setUp(self):
        self.strategy, self.spec, self.calendar, self.rows, self.fees, self.settings = fixture()
        self.now = self.calendar.sessions[-1].closes_at + timedelta(days=1)

    def bars(self, settings=None, rows=None):
        return complete_minutes(self.rows if rows is None else rows, self.spec.instrument_id, self.calendar, settings or self.settings, self.now)

    def run_research(self, *, settings=None, bars=None, strategy=None, fees=None):
        settings = settings or self.settings
        return research_minutes(strategy or self.strategy, self.spec, self.calendar, bars or self.bars(settings), fees or self.fees, settings=settings)

    def test_exact_next_open_fees_tax_and_default_tick(self):
        result = self.run_research()
        first = result.trades[0]
        self.assertEqual((first.entry_index, first.exit_index), (1, 4))
        self.assertEqual((first.entry, first.exit, first.gross, first.costs), (Decimal('20002'), Decimal('20003'), Decimal('10'), Decimal('70')))
        self.assertEqual(result.costs, sum((t.costs for t in result.trades), Decimal(0)))
        zero = self.run_research(fees=replace(self.fees, slippage_ticks=0))
        self.assertEqual(zero.trades[0].gross - first.gross, Decimal('20'))
        self.assertNotEqual(zero.fingerprint, result.fingerprint)

    def test_five_minutes_aggregate_complete_session_only(self):
        settings = replace(self.settings, interval='5m', maximum=5)
        bars = self.bars(settings)
        self.assertEqual(len(bars), 4)
        self.assertEqual((bars[0].open, bars[0].close, bars[0].volume), (Decimal('20000'), Decimal('20004'), 15))
        result = self.run_research(settings=settings, bars=bars)
        self.assertEqual((result.trades[0].entry_index, result.trades[0].exit_index), (1, 2))
        with self.assertRaises(DomainError):
            self.bars(settings, self.rows[:-1])

    def test_typed_parameters_fail_closed_for_both_minute_intervals(self):
        for interval in ('1m', '5m'):
            settings = replace(self.settings, interval=interval)
            parameters = StrategyParameters(interval, Decimal('0.01'), Decimal('100000'), contracts=3)
            definition = StrategyDefinition(
                'minute-fixture',
                1,
                self.spec.market,
                self.strategy.policy,
                interval,
                'LONG_ONLY',
                (Rule('close', 'GT', Decimal('0')),),
                (Rule('close', 'LT', Decimal('1')),),
                self.fees.version,
                'fixture-risk',
            )
            for rules in (None, definition):
                legacy = replace(self.strategy, definition=rules)
                with self.subTest(interval=interval, definition=rules is not None):
                    self.assertTrue(self.run_research(settings=settings, strategy=legacy).trades)
                    for typed in (parameters, replace(parameters, contracts=1, instrument_rule='TMF_NEAR')):
                        with self.assertRaisesRegex(DomainError, 'typed strategy parameters') as raised:
                            self.run_research(settings=settings, strategy=replace(legacy, parameters=typed))
                        self.assertEqual(raised.exception.code, 'capability_missing')

    def test_historical_applicability_preserves_evidence_and_grid_boundaries(self):
        session = self.calendar.sessions[0]
        observed = replace(self.spec, effective_at=session.closes_at)
        proof = HistoricalContractEvidence(observed, 'TMFK6', session.opens_at, session.closes_at, 'SYNTHETIC_FIXTURE', 'a' * 64)
        for evidence, accepted in (
            (None, False),
            (proof, True),
            (replace(proof, spec=self.spec), False),
            (replace(proof, valid_from=session.opens_at + timedelta(minutes=1)), False),
            (replace(proof, valid_until=session.closes_at - timedelta(minutes=1)), False),
        ):
            settings = replace(self.settings, historical_contract=evidence)
            with self.subTest(evidence=evidence):
                if accepted:
                    self.assertEqual(validate_minute_request(self.strategy, observed, self.calendar, settings), (session,))
                else:
                    with self.assertRaisesRegex(DomainError, 'historical contract applicability') as raised:
                        validate_minute_request(self.strategy, observed, self.calendar, settings)
                    self.assertEqual(raised.exception.code, 'instrument_unresolved')
        self.assertEqual(validate_minute_request(self.strategy, self.spec, self.calendar, self.settings), (session,))
        invalid = replace(self.calendar, sessions=(replace(session, closes_at=session.closes_at + timedelta(seconds=1)),))
        for evidence in (None, proof):
            with self.assertRaisesRegex(DomainError, 'minute session or forced-close grid') as raised:
                validate_minute_request(self.strategy, observed, invalid, replace(self.settings, historical_contract=evidence))
            self.assertEqual(raised.exception.code, 'calendar_missing')

    def test_no_current_close_leakage(self):
        rule = Rule('close', 'GT', Decimal('20005'))
        definition = StrategyDefinition(
            'minute-fixture',
            1,
            self.spec.market,
            self.strategy.policy,
            '1m',
            'LONG_ONLY',
            (rule,),
            (Rule('close', 'LT', Decimal('1')),),
            self.fees.version,
            'fixture-risk',
        )
        strategy = replace(self.strategy, definition=definition)
        bars = self.bars()
        result = self.run_research(strategy=strategy, bars=bars)
        self.assertEqual(result.trades[0].entry_index, 7)
        changed = bars[:7] + (replace(bars[7], close=Decimal('1')),) + bars[8:]
        altered = self.run_research(strategy=strategy, bars=changed)
        self.assertEqual(altered.trades[0].entry_index, 7)
        self.assertEqual(altered.trades[0].entry, result.trades[0].entry)

    def test_intraday_cutoff_and_no_overnight(self):
        strategy, spec, calendar, rows, fees, settings = fixture((date(2026, 10, 29), date(2026, 10, 30)))
        settings = replace(settings, maximum=1000)
        bars = complete_minutes(rows, spec.instrument_id, calendar, settings, self.now + timedelta(days=2))
        result = research_minutes(strategy, spec, calendar, bars, fees, settings=settings)
        self.assertEqual(len(result.trades), 2)
        for trade in result.trades:
            self.assertEqual(bars[trade.entry_index].opened_at.date(), bars[trade.exit_index].opened_at.date())
            self.assertEqual(bars[trade.exit_index].opened_at.astimezone(TAIPEI).strftime('%H:%M'), '13:35')

    def test_trading_days_use_explicit_calendar_not_weekends(self):
        strategy, spec, calendar, rows, fees, settings = fixture((date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3)))
        settings = replace(settings, holding_unit='TRADING_DAYS', minimum=1, maximum=1, intraday=False)
        strategy = replace(
            strategy, policy=HoldingPolicy(HoldingKind.SWING, 1, 1), form=replace(strategy.form, holding_kind=HoldingKind.SWING, min_days=1, max_days=1)
        )
        bars = complete_minutes(rows, spec.instrument_id, calendar, settings, datetime(2026, 11, 4, tzinfo=timezone.utc))
        result = research_minutes(strategy, spec, calendar, bars, fees, settings=settings)
        first = result.trades[0]
        self.assertEqual((first.entry_index, first.exit_index), (1, 20))
        self.assertEqual(calendar.age(bars[1].opened_at.date(), bars[20].opened_at.date()), 1)

    def test_rejects_gap_duplicate_forming_wrong_identity_timezone_and_ohlc(self):
        variants = [self.rows[:-1], (self.rows[0],) + self.rows[:-1]]
        for changes in (
            {'final': False},
            {'incomplete': True},
            {'instrument_id': 'INDEX:IX0001'},
            {'start': self.rows[0].start + timedelta(hours=8)},
            {'high': Decimal('1')},
        ):
            variants.append((replace(self.rows[0], **changes),) + self.rows[1:])
        for rows in variants:
            with self.subTest(rows=rows[0].start), self.assertRaises(DomainError):
                self.bars(rows=rows)
        with self.assertRaises(DomainError):
            complete_minutes(self.rows, self.spec.instrument_id, self.calendar, self.settings, self.rows[1].end)

    def test_evidence_roundtrip_and_minute_namespace_does_not_authorize_daily_engine(self):
        result = self.run_research()
        self.assertIsInstance(result, ResearchResult)
        self.assertEqual(loads(dumps(result)), result)
        self.assertEqual(result.minute_settings, self.settings)
        self.assertEqual(result.calendar_version, self.calendar.version)
        self.assertEqual(result.cost_version, self.fees.version)
        daily_fingerprint = research_fingerprint(self.strategy, self.spec, self.calendar, self.fees, result.dataset_id, None)
        self.assertNotEqual(result.fingerprint, daily_fingerprint)

    def test_spawn_matches_inline_and_cleans_owned_process(self):
        runner = SpawnResearchRunner()
        self.addCleanup(runner.close)
        result = runner.run(
            self.strategy,
            self.spec,
            self.calendar,
            self.bars(),
            self.fees,
            deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
            minute_settings=self.settings,
        )
        self.assertEqual(result, self.run_research())
        self.assertTrue(runner.last_cleanup_verified)
        self.assertIsNotNone(runner.last_child_pid)

    def test_settings_and_worker_reject_unsupported_or_partial_input(self):
        for changes in ({'partition': 'OTHER'}, {'interval': '15m'}, {'maximum': 0}, {'minimum': 4}, {'cutoff_minute': 1440}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(self.settings, **changes)
        with self.assertRaises(DomainError):
            self.run_research(bars=self.bars()[:-1])
        with self.assertRaises(DomainError):
            self.run_research(settings=replace(self.settings, cutoff_minute=14 * 60))

    def test_short_side_and_configurable_adverse_two_tick_slippage(self):
        strategy = replace(self.strategy, form=replace(self.strategy.form, direction=Side.SELL))
        result = self.run_research(strategy=strategy, fees=replace(self.fees, slippage_ticks=2))
        trade = result.trades[0]
        self.assertEqual((trade.entry, trade.exit, trade.gross), (Decimal('19999'), Decimal('20006'), Decimal('-70')))
        self.assertEqual(trade.costs, self.fees.round_trip(self.spec, trade.entry, trade.exit, trade.quantity, Side.SELL))

    def test_minutes_do_not_count_bars_and_minimum_rule_exit_is_respected(self):
        definition = StrategyDefinition(
            'minute-fixture',
            1,
            self.spec.market,
            self.strategy.policy,
            '5m',
            'LONG_ONLY',
            (Rule('close', 'GT', Decimal('0')),),
            (Rule('close', 'GT', Decimal('0')),),
            self.fees.version,
            'fixture-risk',
        )
        strategy = replace(self.strategy, definition=definition)
        settings = replace(self.settings, interval='5m', minimum=6, maximum=10)
        result = self.run_research(strategy=strategy, settings=settings)
        self.assertEqual((result.trades[0].entry_index, result.trades[0].exit_index), (1, 3))

    def test_raw_price_metadata_changes_evidence_without_changing_trade_math(self):
        first = self.run_research(settings=replace(self.settings, raw_data_digest='a' * 64))
        second = self.run_research(settings=replace(self.settings, raw_data_digest='b' * 64))
        self.assertEqual(first.trades, second.trades)
        self.assertNotEqual(first.dataset_id, second.dataset_id)
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_non_divisible_session_and_unaligned_cutoff_are_not_truncated(self):
        session = self.calendar.sessions[0]
        calendar = replace(self.calendar, sessions=(replace(session, closes_at=session.closes_at - timedelta(minutes=1)),))
        with self.assertRaises(DomainError):
            complete_minutes(self.rows[:-1], self.spec.instrument_id, calendar, replace(self.settings, interval='5m'), self.now)
        with self.assertRaises(DomainError):
            self.run_research(settings=replace(self.settings, interval='5m', cutoff_minute=13 * 60 + 34))

    def test_expired_contract_is_not_rolled_or_given_index_prices(self):
        for spec in (replace(self.spec, expiry=self.settings.first_day, delivery_month='202610'), replace(self.spec, instrument_id='INDEX:IX0001')):
            with self.subTest(instrument=spec.instrument_id), self.assertRaises(DomainError):
                research_minutes(self.strategy, spec, self.calendar, self.bars(), self.fees, settings=self.settings)

    def test_cutoff_cannot_be_relaxed_beyond_tmf_and_intraday_policy_must_match(self):
        with self.assertRaises(DomainError):
            self.run_research(settings=replace(self.settings, cutoff_minute=13 * 60 + 36))
        with self.assertRaises(DomainError):
            self.run_research(settings=replace(self.settings, intraday=False))

    def test_calendar_night_only_middle_day_is_not_silently_omitted(self):
        session = self.calendar.sessions[0]
        middle = TradingSession(date(2026, 10, 30), session.opens_at + timedelta(days=1), session.closes_at + timedelta(days=1), 'NIGHT')
        last = replace(session, trade_date=date(2026, 11, 2), opens_at=session.opens_at + timedelta(days=4), closes_at=session.closes_at + timedelta(days=4))
        calendar = replace(self.calendar, sessions=(session, middle, last))
        with self.assertRaises(DomainError):
            replace(self.settings, last_day=last.trade_date).sessions(calendar)

    def test_worker_boundary_checks_minute_receipt_settings_and_versions(self):
        job = ResearchJob('a' * 32, self.strategy, self.spec, self.calendar, self.bars(), self.fees, minute_settings=self.settings)
        result = self.run_research()
        self.assertEqual(SpawnResearchRunner._validate_result(job, result), result)
        for changes in (
            {'minute_settings': replace(self.settings, maximum=4)},
            {'cost_version': 'other'},
            {'calendar_version': 'other'},
            {'price_basis': 'INDEX_PROXY'},
            {'producer': 'other'},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(DomainError, 'minute result metadata mismatch'):
                SpawnResearchRunner._validate_result(job, replace(result, **changes))

    def test_five_minute_spawn_matches_inline_with_current_source_profile(self):
        from quantlab.trading.runtime.provenance import compute_profile

        settings = replace(self.settings, interval='5m', maximum=5)
        bars = self.bars(settings)
        profile = compute_profile()
        runner = SpawnResearchRunner()
        self.addCleanup(runner.close)
        result = runner.run(
            self.strategy,
            self.spec,
            self.calendar,
            bars,
            self.fees,
            deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
            minute_settings=settings,
            source_profile=profile,
        )
        expected = research_minutes(self.strategy, self.spec, self.calendar, bars, self.fees, settings=settings, source_profile=profile)
        self.assertEqual(result, expected)
        self.assertEqual(result.source_digest, profile.source_digest)
        self.assertTrue(runner.last_cleanup_verified)
