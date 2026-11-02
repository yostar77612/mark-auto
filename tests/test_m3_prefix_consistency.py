"""M3 execution prefixes against the unchanged v1 function (test-only bridge)."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import random
import unittest

from quantlab.core import Bar, StrategySpec
from quantlab.strategies import DEFAULTS, generate_signals
from quantlab.trading.application.signal_executor import SignalExecutor
from quantlab.trading.domain.signal_strategy import DirectionPolicy, SignalBar, SignalPoint, SizingKind, SizingRule
from tests.test_m3_signal_strategy import intraday, make

D = Decimal
C = 'TAIFEX:TMF:202610'


class DirectV1TestSource:
    """No production bridge dependency: this is deliberately confined to tests."""

    def signals(self, contract_ref, bars, signal_spec_json):
        body = json.loads(signal_spec_json)
        spec = StrategySpec('test-only', body['family'], body['parameters'], body['rules'], body['schema_version'])
        data = tuple(Bar(b.starts_at, b.ends_at, b.trade_date.isoformat(), b.session, contract_ref, b.open, b.high, b.low, b.close, b.volume) for b in bars)
        return tuple(SignalPoint(s.timestamp, s.target_position, s.reason) for s in generate_signals(data, spec))


def series(*, daily=False):
    rng = random.Random(314159)
    start = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    result = []
    for i in range(90):
        at = start + (timedelta(days=i) if daily else timedelta(days=i // 45, minutes=5 * (i % 45)))
        close = D(20000 + rng.randint(-150, 150) + (i % 15) * 20)
        result.append(
            SignalBar(at, at + (timedelta(hours=4) if daily else timedelta(minutes=5)), at.date(), 'day', close, close + 3, close - 3, close, 100 + i)
        )
    return tuple(result)


def specs():
    for family, parameters in DEFAULTS.items():
        for period in (3, 7):
            p = dict(parameters, quantity=1)
            if family == 'trend':
                p.update(fast=period - 1, slow=period + 2)
            else:
                p['lookback'] = period
            yield dict(family=family, parameters=p, rules={}, schema_version=1)
    field = {'op': 'field', 'name': 'close'}
    prior = {'op': 'sma', 'field': 'close', 'period': 3, 'lag': 1}
    for period in (2, 5):
        yield dict(
            family='trend',
            parameters={'fast': 1, 'slow': 3, 'quantity': 1},
            schema_version=1,
            rules={
                'long': {'op': 'gt', 'left': field, 'right': prior},
                'short': {'op': 'lt', 'left': field, 'right': prior},
                'exit': {'op': 'lt', 'left': {'op': 'return_bps', 'field': 'close', 'period': period}, 'right': {'op': 'const', 'value': '-30'}},
            },
        )


class PrefixTests(unittest.TestCase):
    def test_all_families_ast_parameters_daily_and_per_session(self):
        source = DirectV1TestSource()
        executor = SignalExecutor(source, C)
        cases = 0
        for daily in (False, True):
            bars = series(daily=daily)
            for body in specs():
                for policy in (DirectionPolicy.BOTH, DirectionPolicy.LONG_ONLY):
                    text = json.dumps(body, sort_keys=True, separators=(',', ':'))
                    auto = (
                        make(
                            signal_spec_json=text,
                            bar_interval='1d',
                            history_anchor=bars[0].trade_date,
                            direction_policy=policy,
                            sizing=SizingRule(SizingKind.FIXED_CONTRACTS, contracts=3),
                        )
                        if daily
                        else intraday(signal_spec_json=text, direction_policy=policy, sizing=SizingRule(SizingKind.FIXED_CONTRACTS, contracts=3))
                    )
                    groups = {None: bars} if daily else {day: tuple(b for b in bars if b.trade_date == day) for day in {b.trade_date for b in bars}}
                    full = {day: source.signals(C, group, text) for day, group in groups.items()}
                    for i, bar in enumerate(bars):
                        points = full[None if daily else bar.trade_date]
                        target = 0
                        for point in points:
                            if point.at <= bar.ends_at:
                                target = point.target
                        expected = (1 if target > 0 else -1 if target < 0 else 0) * 3
                        if policy is DirectionPolicy.LONG_ONLY:
                            expected = max(0, expected)
                        actual = executor.decide(auto, bars[: i + 1], bar.ends_at, 0)
                        with self.subTest(daily=daily, family=body['family'], policy=policy, i=i):
                            self.assertEqual(0 if actual is None else actual.desired_quantity, expected)
                        cases += 1
        self.assertEqual(cases, 4320)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.bars = series()[:3]
        self.auto = intraday()
        self.calls = []
        outer = self

        class Source:
            def signals(self, contract, bars, spec):
                outer.calls.append(bars)
                return (SignalPoint(bars[-1].ends_at, -7, 'short'), SignalPoint(bars[-1].ends_at + timedelta(days=1), 9, 'future'))

        self.executor = SignalExecutor(Source(), C)

    def test_no_completed_bars(self):
        self.assertIsNone(self.executor.decide(self.auto, self.bars, self.bars[0].starts_at, 1))
        self.assertEqual(self.calls, [])

    def test_history_anchor_empty_window(self):
        auto = make(history_anchor=date(2026, 11, 1))
        self.assertIsNone(self.executor.decide(auto, self.bars, self.bars[-1].ends_at, 1))
        self.assertEqual(self.calls, [])

    def test_future_bars_and_signals_excluded(self):
        intent = self.executor.decide(self.auto, self.bars, self.bars[0].ends_at, 0)
        self.assertEqual(self.calls, [self.bars[:1]])
        self.assertEqual((intent.desired_quantity, intent.bar_end), (-1, self.bars[0].ends_at))

    def test_equal_target_no_duplicate_intent(self):
        self.assertIsNone(self.executor.decide(self.auto, self.bars, self.bars[-1].ends_at, -1))

    def test_reversal_is_target_not_a_direct_order(self):
        intent = self.executor.decide(self.auto, self.bars, self.bars[-1].ends_at, 1)
        self.assertEqual(intent.desired_quantity, -1)
        self.assertNotEqual(intent.idempotency_key(0), intent.idempotency_key(1))
        self.assertEqual(intent.idempotency_key(0), self.executor.decide(self.auto, self.bars, self.bars[-1].ends_at, 1).idempotency_key(0))

    def test_direction_flatten_and_lot_rounding(self):
        auto = replace(self.auto, direction_policy=DirectionPolicy.LONG_ONLY)
        self.assertEqual(self.executor.decide(auto, self.bars, self.bars[-1].ends_at, 1).desired_quantity, 0)
        auto = make(sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('100000000')), direction_policy=DirectionPolicy.BOTH)
        intent = self.executor.decide(auto, self.bars, self.bars[-1].ends_at, 0)
        expected = -int(D('100000000') / self.bars[-1].close / 1000) * 1000
        self.assertEqual(intent.desired_quantity, expected)
