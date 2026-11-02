"""Synthetic TRAINING fixtures; no market-data, broker or candidate catalog IO."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.application.signal_research import _traverse, research_auto_strategy
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.minute_contract import HistoricalContractEvidence
from quantlab.trading.domain.minute_research import FixedModelMinuteSettings, MinuteResearchSettings, TAIPEI
from quantlab.trading.domain.models import HoldingKind, InstrumentSpec, Market, QuantityUnit, Side
from quantlab.trading.domain.promotion import DEFAULT_THRESHOLDS
from quantlab.trading.domain.signal_strategy import AutoStrategy, DirectionPolicy, SignalBar, SignalPoint, SizingKind, SizingRule, WindowMode
from quantlab.trading.domain.validation import DomainError


D = Decimal


def profile(letter='a'):
    manifest = (('quantlab/trading/synthetic_fixture.py', letter * 64),)
    digest = sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return ProducerProfile('MARKAUTO-TRADING-V2-PROFILE-1', 2, manifest, digest)


class Source:
    def __init__(self, targets=(1,)):
        self.targets = targets
        self.calls = []

    def signals(self, contract_ref, bars, signal_spec_json):
        self.calls.append((contract_ref, bars, signal_spec_json))
        return tuple(SignalPoint(b.ends_at, self.targets[min(i, len(self.targets) - 1)], 'synthetic') for i, b in enumerate(bars))


def fixture(*, minute=True, days=1, width=1):
    first = date(2026, 11, 2)
    sessions = tuple(
        TradingSession(first + timedelta(days=i), datetime(2026, 11, 2 + i, 13, 20, tzinfo=TAIPEI), datetime(2026, 11, 2 + i, 13, 40, tzinfo=TAIPEI))
        for i in range(days)
    )
    calendar = TradingCalendar('synthetic', 'synthetic-v1', 'SYNTHETIC', sessions)
    spec = InstrumentSpec(
        'TAIFEX:TMF:202611',
        Market.INDEX_FUTURE,
        'TWD',
        QuantityUnit.CONTRACT,
        1,
        D(10),
        D(1),
        'TAIEX',
        'synthetic-v1',
        'SYNTHETIC',
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        date(2026, 11, 30),
        D(50000),
        'TAIFEX',
        '202611',
    )
    fees = FeeSchedule()
    auto = AutoStrategy(
        'auto-synthetic',
        1,
        '{"family":"synthetic"}',
        'candidate-synthetic',
        HoldingKind.INTRADAY if minute else HoldingKind.SWING,
        'TMF_NEAR',
        f'{width}m' if minute else '1d',
        WindowMode.PER_SESSION if minute else WindowMode.FULL_HISTORY,
        None if minute else first,
        DirectionPolicy.BOTH,
        SizingRule(SizingKind.FIXED_CONTRACTS, 1),
        D('.01'),
        0 if minute else 2,
        fees.version,
        'synthetic-risk',
        'm3-thresholds-v1',
    )
    bars = []
    for session in sessions:
        for i in range(0, 20 if minute else 1, width if minute else 1):
            start = session.opens_at + timedelta(minutes=i)
            end = start + timedelta(minutes=width) if minute else session.closes_at
            price = D(20000 + len(bars))
            bars.append(SignalBar(start, end, session.trade_date, 'day', price, price + 1, price - 1, price, 10))
    settings = MinuteResearchSettings(first, sessions[-1].trade_date, interval=f'{width}m') if minute else None
    return dict(
        auto=auto,
        spec=spec,
        calendar=calendar,
        bars=tuple(bars),
        fees=fees,
        source=Source(),
        allocated_amount=D(100000),
        now=sessions[-1].closes_at + timedelta(days=1),
        source_profile=profile(),
        settings=settings,
    )


class SignalResearchTests(unittest.TestCase):
    def run_research(self, **changes):
        args = fixture()
        args.update(changes)
        return research_auto_strategy(**args)

    def reject(self, reason, **changes):
        args = fixture()
        args.update(changes)
        with self.assertRaisesRegex(DomainError, reason) as caught:
            research_auto_strategy(**args)
        self.assertEqual(caught.exception.code, 'auto_execution_data_insufficient')
        self.assertEqual(args['source'].calls, [])

    def test_next_open_cost_slippage_and_allocation(self):
        args = fixture()
        result = research_auto_strategy(**args)
        trade = result.trades[0]
        self.assertEqual((trade.entry_index, trade.exit_index), (1, 15))
        self.assertEqual((trade.entry, trade.exit), (D(20002), D(20014)))
        self.assertEqual(trade.gross, D(120))
        self.assertEqual(
            trade.costs, args['fees'].transaction(args['spec'], Side.BUY, trade.entry, 1) + args['fees'].transaction(args['spec'], Side.SELL, trade.exit, 1)
        )
        self.assertEqual(result.net_pnl, D(50))
        self.assertEqual(result.expectation.per_day_return, D('.0005'))
        doubled = research_auto_strategy(**{**args, 'allocated_amount': D(200000)})
        self.assertEqual(doubled.expectation.per_day_return, result.expectation.per_day_return / 2)
        zero = research_auto_strategy(**{**args, 'fees': replace(args['fees'], slippage_ticks=0)})
        self.assertEqual(zero.trades[0].gross - trade.gross, D(20))
        self.assertNotEqual(zero.behavior_hash, result.behavior_hash)
        self.assertEqual(result.completed_trades, 1)

    def test_mark_to_market_drawdown_includes_unrealized_peak(self):
        args = fixture(minute=False, days=4)
        bars = list(args['bars'])
        bars[1] = replace(bars[1], high=D(20201), close=D(20200))
        bars[2] = replace(bars[2], high=D(20101), close=D(20100))
        result = research_auto_strategy(**{**args, 'bars': tuple(bars)})
        # Entry 20002, peak at 20200 less paid entry fee = 1945.
        # Time exit at 20002, round-trip fees = -70. Drawdown = 2015.
        self.assertEqual(result.net_pnl, D(-70))
        self.assertEqual(result.expectation.max_drawdown_pct, D('0.02015'))

    def test_valuation_change_invalidates_behavior_even_with_identical_trades(self):
        args = fixture()
        original = research_auto_strategy(**args)

        def changed_valuation(*values):
            trades, directions, marks = _traverse(*values)
            return trades, directions, tuple(m * 2 for m in marks)

        with patch('quantlab.trading.application.signal_research._traverse', side_effect=changed_valuation):
            changed = research_auto_strategy(**args)
        self.assertEqual(original.trades, changed.trades)
        self.assertEqual(original.dataset_id, changed.dataset_id)
        self.assertNotEqual(original.behavior_hash, changed.behavior_hash)

    def test_contract_aliases_preserve_resolved_identity(self):
        args = fixture()
        canonical = research_auto_strategy(**args)
        for rule in ('TMF:202611', 'TAIFEX:TMF:202611'):
            result = research_auto_strategy(**{**args, 'auto': replace(args['auto'], instrument_rule=rule)})
            self.assertEqual(result.trades, canonical.trades)
        with self.assertRaisesRegex(DomainError, 'resolved TMF contract'):
            research_auto_strategy(**{**args, 'auto': replace(args['auto'], instrument_rule='TMF:202612')})

    def test_reversal_closes_then_opens_with_each_leg_cost(self):
        args = fixture()
        args['source'] = Source((1, -1, -1, 0))
        result = research_auto_strategy(**args)
        self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 2), (2, 4)])
        self.assertEqual(result.trade_directions, (Side.BUY, Side.SELL))
        self.assertEqual((result.trades[0].exit, result.trades[1].entry), (D(20001), D(20001)))
        self.assertGreater(sum(t.costs for t in result.trades), D(0))
        self.assertEqual(len(args['source'].calls), len(args['bars']) - 1)
        for index, (_, history, _) in enumerate(args['source'].calls, 1):
            self.assertEqual(history[-1], args['bars'][index - 1])
            self.assertTrue(all(b.ends_at <= args['bars'][index].starts_at for b in history))

    def test_direction_policy_shared_with_executor(self):
        args = fixture()
        args['source'] = Source((-1,))
        short = research_auto_strategy(**args)
        self.assertEqual(short.trade_directions, (Side.SELL,))
        long_only = research_auto_strategy(**{**args, 'auto': replace(args['auto'], direction_policy=DirectionPolicy.LONG_ONLY)})
        self.assertEqual(long_only.trades, ())
        self.assertEqual(long_only.expectation.win_rate, D(0))

    def test_stops_apply_on_entry_bar_and_use_adverse_gap_price(self):
        args = fixture()
        bars = list(args['bars'])
        bars[1] = replace(bars[1], low=D(19700))
        result = research_auto_strategy(**{**args, 'bars': tuple(bars)})
        self.assertEqual((result.trades[0].entry_index, result.trades[0].exit_index), (1, 1))
        self.assertEqual(result.trades[0].exit, D(19800))  # floor(20002 * .99) - slippage
        bars = list(args['bars'])
        bars[2] = replace(bars[2], open=D(19000), low=D(18900))
        result = research_auto_strategy(**{**args, 'bars': tuple(bars)})
        self.assertEqual(result.trades[0].exit, D(18999))
        self.assertGreater(result.expectation.max_drawdown_pct, D('.1'))

    def test_short_stop_and_gap_are_adverse(self):
        args = fixture()
        args['source'] = Source((-1,))
        bars = list(args['bars'])
        bars[1] = replace(bars[1], high=D(20400))
        result = research_auto_strategy(**{**args, 'bars': tuple(bars)})
        self.assertEqual(result.trades[0].exit, D(20201))
        bars = list(args['bars'])
        bars[2] = replace(bars[2], open=D(21000), high=D(21100))
        result = research_auto_strategy(**{**args, 'bars': tuple(bars)})
        self.assertEqual(result.trades[0].exit, D(21001))

    def test_time_stop_and_terminal_liquidation(self):
        args = fixture(minute=False, days=6)
        result = research_auto_strategy(**args)
        self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 3), (4, 5)])
        self.assertEqual(result.partition, 'TRAINING')

    def test_intraday_flat_cutoff_no_reentry_and_window_reset(self):
        args = fixture(days=2)
        result = research_auto_strategy(**args)
        self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 15), (21, 35)])
        for _, history, _ in args['source'].calls:
            self.assertEqual(len({bar.trade_date for bar in history}), 1)
        five = research_auto_strategy(**fixture(width=5))
        self.assertEqual([(t.entry_index, t.exit_index) for t in five.trades], [(1, 3)])

    def test_deterministic_hash_and_source_refresh(self):
        args = fixture()
        first = research_auto_strategy(**args)
        second = research_auto_strategy(**args)
        self.assertEqual(first, second)
        refreshed = research_auto_strategy(**{**args, 'source_profile': profile('b')})
        self.assertEqual(first.behavior_hash, refreshed.behavior_hash)
        self.assertNotEqual(first.result_hash, refreshed.result_hash)
        self.assertNotEqual(first.source_digest, refreshed.source_digest)
        changed = research_auto_strategy(**{**args, 'source': Source((-1,))})
        self.assertNotEqual(first.behavior_hash, changed.behavior_hash)

    def test_training_partition_guard(self):
        self.reject('training partition required', partition='OTHER')

    def test_cost_version_guard(self):
        self.reject('cost version mismatch', fees=FeeSchedule(version='other'))

    def test_contract_guard(self):
        args = fixture()
        self.reject('resolved TMF contract', auto=replace(args['auto'], instrument_rule='OTHER'))
        self.reject('resolved TMF contract', spec=replace(args['spec'], exchange='OTHER'))

    def test_minimum_bars_guard(self):
        args = fixture(minute=False, days=2)
        args['bars'] = args['bars'][:1]
        with self.assertRaisesRegex(DomainError, 'at least two'):
            research_auto_strategy(**args)

    def test_available_before_now_guard(self):
        args = fixture()
        self.reject('available before now', now=args['bars'][-1].ends_at)
        accepted = self.run_research(now=args['bars'][-1].ends_at + timedelta(microseconds=1))
        self.assertTrue(accepted.trades)

    def test_ordered_bars_guard(self):
        args = fixture(minute=False, days=3)
        bars = list(args['bars'])
        bars[1] = replace(bars[1], starts_at=bars[0].starts_at)
        with self.assertRaisesRegex(DomainError, 'ordered non-overlapping'):
            research_auto_strategy(**{**args, 'bars': tuple(bars)})

    def test_expiry_guard(self):
        args = fixture()
        self.reject('contract expired', spec=replace(args['spec'], expiry=date(2026, 11, 2)))

    def test_anchor_guard(self):
        args = fixture(minute=False, days=3)
        args['auto'] = replace(args['auto'], history_anchor=date(2026, 11, 1))
        with self.assertRaisesRegex(DomainError, 'frozen anchor'):
            research_auto_strategy(**args)

    def test_window_limit_guard(self):
        args = fixture()
        with patch('quantlab.trading.application.signal_research.thresholds_for', return_value=replace(DEFAULT_THRESHOLDS, EXECUTOR_MAX_BARS=19)):
            self.reject('exceeds bar limit')
        self.assertTrue(research_auto_strategy(**args).trades)

    def test_daily_settings_guard(self):
        args = fixture(minute=False, days=3)
        args['settings'] = fixture()['settings']
        with self.assertRaisesRegex(DomainError, 'minute settings do not describe daily'):
            research_auto_strategy(**args)

    def test_daily_historical_contract_guard(self):
        args = fixture(minute=False, days=3)
        args['spec'] = replace(args['spec'], effective_at=args['bars'][0].ends_at)
        with self.assertRaisesRegex(DomainError, 'historical contract applicability'):
            research_auto_strategy(**args)

    def test_daily_coverage_guard(self):
        args = fixture(minute=False, days=3)
        args['bars'] = (args['bars'][0], args['bars'][2])
        with self.assertRaisesRegex(DomainError, 'daily coverage incomplete'):
            research_auto_strategy(**args)

    def test_minute_settings_guard(self):
        settings = fixture()['settings']
        fixed = FixedModelMinuteSettings(settings.first_day, settings.last_day, sdk_code='TMFX6')
        self.reject('explicit minute training settings', settings=fixed)
        self.reject('explicit minute training settings', settings=None)

    def test_minute_identity_guard(self):
        args = fixture(width=5)
        args['settings'] = replace(args['settings'], interval='1m')
        with self.assertRaisesRegex(DomainError, 'minute settings mismatch'):
            research_auto_strategy(**args)

    def test_frozen_cutoff_guard(self):
        self.reject('cutoff is fixed', settings=replace(fixture()['settings'], cutoff_minute=13 * 60 + 30))

    def test_minute_historical_contract_guard(self):
        args = fixture()
        observed = replace(args['spec'], effective_at=args['bars'][-1].ends_at)
        self.reject('historical contract applicability', spec=observed)
        proof = HistoricalContractEvidence(observed, 'TMFX6', args['bars'][0].starts_at, args['bars'][-1].ends_at, 'SYNTHETIC', 'a' * 64)
        accepted = self.run_research(spec=observed, settings=replace(args['settings'], historical_contract=proof))
        self.assertTrue(accepted.trades)

    def test_minute_count_guard(self):
        self.reject('complete minute sessions', bars=fixture()['bars'][:-1])

    def test_minute_grid_guard(self):
        args = fixture()
        bars = (replace(args['bars'][0], session='night'), *args['bars'][1:])
        self.reject('minute completion grid', bars=bars)

    def test_invalid_allocation_is_not_silently_zero(self):
        for amount in (D(0), D(-1), D('NaN')):
            with self.subTest(amount=amount), self.assertRaises(DomainError):
                self.run_research(allocated_amount=amount)


if __name__ == '__main__':
    unittest.main()
