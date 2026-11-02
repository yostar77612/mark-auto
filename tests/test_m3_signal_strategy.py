"""M3 frozen signal strategy: immutability, canonical hash, revision, windows and target helpers."""

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest
from unittest import mock

from quantlab.trading.domain import promotion, signal_strategy
from quantlab.trading.domain.models import HoldingKind
from quantlab.trading.domain.promotion import DEFAULT_THRESHOLDS, PromotionThresholds, Stage
from quantlab.trading.domain.signal_strategy import (
    AutoStrategy,
    CandidateEvidence,
    CandidateSummary,
    DirectionPolicy,
    SignalBar,
    SignalPoint,
    SizingKind,
    SizingRule,
    TargetIntent,
    WindowMode,
    apply_direction,
    desired_target,
    window_bars,
)
from quantlab.trading.domain.validation import DomainError

D = Decimal
UTC = timezone.utc
SPEC = '{"family":"trend","parameters":{"fast":5,"quantity":1,"slow":20},"rules":null,"schema_version":1}'
ROOT = Path(__file__).resolve().parents[1]


def make(**changes: object) -> AutoStrategy:
    base = dict(
        strategy_id='auto-1',
        version=1,
        signal_spec_json=SPEC,
        candidate_fingerprint='fp-abc',
        holding_kind=HoldingKind.SWING,
        instrument_rule='2330',
        bar_interval='5m',
        window_mode=WindowMode.FULL_HISTORY,
        history_anchor=date(2026, 1, 5),
        direction_policy=DirectionPolicy.LONG_ONLY,
        sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('100000')),
        protective_stop_pct=D('0.03'),
        max_hold_days=5,
        cost_version='cost-v1',
        risk_ref='risk-v1',
        thresholds_version='m3-thresholds-v1',
    )
    base.update(changes)
    return AutoStrategy(**base)  # type: ignore[arg-type]


def intraday(**changes: object) -> AutoStrategy:
    base = dict(
        holding_kind=HoldingKind.INTRADAY,
        instrument_rule='TMF_NEAR',
        window_mode=WindowMode.PER_SESSION,
        history_anchor=None,
        direction_policy=DirectionPolicy.BOTH,
        sizing=SizingRule(SizingKind.FIXED_CONTRACTS, contracts=1),
        protective_stop_pct=D('0.01'),
        max_hold_days=0,
    )
    base.update(changes)
    return make(**base)


def bar(day: date, minute: int = 0, *, price: str = '100', trade_date: date | None = None) -> SignalBar:
    start = datetime(day.year, day.month, day.day, 1, 0, tzinfo=UTC) + timedelta(minutes=5 * minute)
    return SignalBar(start, start + timedelta(minutes=5), trade_date or day, 'day', D(price), D(price), D(price), D(price), 10)


class FrozenHashTests(unittest.TestCase):
    def test_golden_hash_is_stable_across_platforms(self) -> None:
        # Pinned: any change to the canonical body (field set, order-insensitive JSON, Decimal text) must be a deliberate new protocol.
        self.assertEqual(make().frozen_hash, '0fe5500cc84625f7745ab3d3fbea927763015fcd2f10023b147661129fd3cbbb')

    def test_equal_content_hashes_equal_whatever_the_decimal_spelling(self) -> None:
        a = make(protective_stop_pct=D('0.03'), sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('100000')))
        b = make(protective_stop_pct=D('0.0300'), sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('1E+5')))
        self.assertEqual(a, a)
        self.assertEqual(a.frozen_hash, b.frozen_hash)
        self.assertEqual(len(a.frozen_hash), 64)

    def test_every_field_changes_the_hash(self) -> None:
        base = make().frozen_hash
        alternatives = {
            'strategy_id': dict(strategy_id='auto-2'),
            'version': dict(version=2),
            'signal_spec_json': dict(signal_spec_json=SPEC.replace('"fast":5', '"fast":6')),
            'candidate_fingerprint': dict(candidate_fingerprint='fp-other'),
            'holding_kind': dict(holding_kind=HoldingKind.POSITION, bar_interval='1d', max_hold_days=5),
            'instrument_rule': dict(instrument_rule='2317'),
            'bar_interval': dict(bar_interval='1d'),
            'window_mode': dict(holding_kind=HoldingKind.INTRADAY, window_mode=WindowMode.PER_SESSION, history_anchor=None, max_hold_days=0),
            'history_anchor': dict(history_anchor=date(2026, 1, 6)),
            'direction_policy': dict(direction_policy=DirectionPolicy.BOTH),
            'sizing': dict(sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('100001'))),
            'protective_stop_pct': dict(protective_stop_pct=D('0.031')),
            'max_hold_days': dict(max_hold_days=6),
            'cost_version': dict(cost_version='cost-v2'),
            'risk_ref': dict(risk_ref='risk-v2'),
            'thresholds_version': dict(thresholds_version='m3-thresholds-test'),
        }
        self.assertEqual(set(alternatives), {f.name for f in fields(AutoStrategy) if f.name != 'protocol_version'})
        extra = PromotionThresholds(version='m3-thresholds-test')
        with mock.patch.dict(promotion._KNOWN_THRESHOLDS, {extra.version: extra}):
            hashes = {name: make(**change).frozen_hash for name, change in alternatives.items()}
        for name, digest in hashes.items():
            with self.subTest(name):
                self.assertNotEqual(digest, base)
        self.assertEqual(len(set(hashes.values())), len(hashes))

    def test_sizing_kind_and_protocol_version_are_hashed_too(self) -> None:
        self.assertNotEqual(intraday().frozen_hash, intraday(sizing=SizingRule(SizingKind.FIXED_CONTRACTS, contracts=2)).frozen_hash)
        base = make().frozen_hash
        with mock.patch.object(signal_strategy, 'PROTOCOL_VERSION', 'm3-auto-test'):
            self.assertNotEqual(make(protocol_version='m3-auto-test').frozen_hash, base)
        with self.assertRaises(DomainError):
            make(protocol_version='m3-auto-v2')


class ImmutabilityTests(unittest.TestCase):
    def test_instances_are_frozen_and_have_no_mutating_methods(self) -> None:
        auto = make()
        for name in ('stage', 'version', 'frozen_hash', 'protective_stop_pct'):
            with self.subTest(name), self.assertRaises((FrozenInstanceError, AttributeError)):
                setattr(auto, name, 1)
        names = {f.name for f in fields(AutoStrategy)}
        self.assertEqual({n for n in dir(AutoStrategy) if not n.startswith('_')} - names, {'stage', 'frozen_hash', 'revised'})

    def test_revised_makes_a_new_backtest_version_and_keeps_the_old_one(self) -> None:
        old = make()
        old_hash = old.frozen_hash
        new = old.revised(protective_stop_pct=D('0.05'), sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('50000')))
        self.assertEqual((new.version, new.stage, new.strategy_id), (2, Stage.BACKTEST, 'auto-1'))
        self.assertEqual((old.version, old.protective_stop_pct, old.frozen_hash), (1, D('0.03'), old_hash))
        self.assertEqual((new.protective_stop_pct, new.sizing.amount), (D('0.05'), D('50000')))
        self.assertNotEqual(new.frozen_hash, old_hash)
        self.assertEqual(new.revised().version, 3)

    def test_revision_cannot_touch_identity_or_break_validation(self) -> None:
        for change in (dict(version=9), dict(strategy_id='x'), dict(protocol_version='m3-auto-v1')):
            with self.subTest(change), self.assertRaises(DomainError):
                make().revised(**change)
        with self.assertRaises(DomainError):
            make().revised(protective_stop_pct=D('2'))
        with self.assertRaises(TypeError):
            make().revised(unknown_field=1)

    def test_a_new_build_starts_at_backtest(self) -> None:
        self.assertIs(make().stage, Stage.BACKTEST)
        self.assertIs(intraday().stage, Stage.BACKTEST)


class ValidationTests(unittest.TestCase):
    def test_invalid_shapes_are_refused(self) -> None:
        table = {
            'custom kind': dict(holding_kind=HoldingKind.CUSTOM),
            'interval not allowed for swing': dict(bar_interval='1m'),
            'unknown interval': dict(bar_interval='15m'),
            'per-session window for swing': dict(window_mode=WindowMode.PER_SESSION, history_anchor=None),
            'full-history without anchor': dict(history_anchor=None),
            'anchor is a datetime': dict(history_anchor=datetime(2026, 1, 5)),
            'stop zero': dict(protective_stop_pct=D('0')),
            'stop one': dict(protective_stop_pct=D('1')),
            'stop negative': dict(protective_stop_pct=D('-0.01')),
            'stop as float': dict(protective_stop_pct=0.03),
            'swing hold zero': dict(max_hold_days=0),
            'swing hold over cap': dict(max_hold_days=11),
            'spec not json': dict(signal_spec_json='{'),
            'spec not an object': dict(signal_spec_json='[]'),
            'spec empty': dict(signal_spec_json=''),
            'unknown thresholds': dict(thresholds_version='m3-thresholds-v9'),
            'empty cost version': dict(cost_version=''),
            'version zero': dict(version=0),
            'direction as text': dict(direction_policy='BOTH'),
        }
        for label, change in table.items():
            with self.subTest(label), self.assertRaises(DomainError):
                make(**change)

    def test_kind_interval_window_and_hold_matrix(self) -> None:
        make(holding_kind=HoldingKind.SWING, bar_interval='1d', max_hold_days=10)
        make(holding_kind=HoldingKind.POSITION, bar_interval='1d', max_hold_days=60)
        intraday(bar_interval='1m')
        intraday(bar_interval='5m')
        table = {
            'position 5m': dict(holding_kind=HoldingKind.POSITION, bar_interval='5m', max_hold_days=60),
            'position hold over cap': dict(holding_kind=HoldingKind.POSITION, bar_interval='1d', max_hold_days=61),
            'intraday 1d': dict(bar_interval='1d'),
            'intraday with hold days': dict(max_hold_days=1),
            'intraday full history': dict(window_mode=WindowMode.FULL_HISTORY, history_anchor=date(2026, 1, 5)),
            'intraday with anchor': dict(history_anchor=date(2026, 1, 5)),
        }
        for label, change in table.items():
            with self.subTest(label), self.assertRaises(DomainError):
                (intraday if label.startswith('intraday') else make)(**change)

    def test_sizing_rules(self) -> None:
        SizingRule(SizingKind.FIXED_CONTRACTS, contracts=5)
        SizingRule(SizingKind.LOT_AMOUNT, amount=D('1'))
        for args in (
            (SizingKind.FIXED_CONTRACTS, 0, None),
            (SizingKind.FIXED_CONTRACTS, 6, None),
            (SizingKind.FIXED_CONTRACTS, None, None),
            (SizingKind.FIXED_CONTRACTS, 1, D('1')),
            (SizingKind.FIXED_CONTRACTS, True, None),
            (SizingKind.LOT_AMOUNT, None, None),
            (SizingKind.LOT_AMOUNT, None, D('0')),
            (SizingKind.LOT_AMOUNT, 1, D('1')),
            (SizingKind.LOT_AMOUNT, None, 100000),
        ):
            with self.subTest(args), self.assertRaises(DomainError):
                SizingRule(*args)

    def test_signal_bar_and_point_shapes(self) -> None:
        start = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5)
        ok = dict(starts_at=start, ends_at=end, trade_date=date(2026, 1, 5), session='day', open=D('10'), high=D('11'), low=D('9'), close=D('10'), volume=1)
        SignalBar(**ok)
        for change in (
            dict(ends_at=start),
            dict(starts_at=datetime(2026, 1, 5, 1, 0)),
            dict(session='evening'),
            dict(high=D('9.5')),
            dict(low=D('10.5')),
            dict(open=10),
            dict(close=D('0')),
            dict(volume=-1),
            dict(trade_date=datetime(2026, 1, 5)),
        ):
            with self.subTest(change), self.assertRaises(DomainError):
                SignalBar(**{**ok, **change})
        SignalPoint(end, -1, 'exit')
        for args in ((datetime(2026, 1, 5), 1, 'x'), (end, 1.0, 'x'), (end, True, 'x'), (end, 1, None)):
            with self.subTest(args), self.assertRaises(DomainError):
                SignalPoint(*args)  # type: ignore[arg-type]


class WindowTests(unittest.TestCase):
    def test_full_history_starts_at_the_anchor_and_skips_unfinished_bars(self) -> None:
        auto = make()
        bars = (bar(date(2026, 1, 2)), bar(date(2026, 1, 5)), bar(date(2026, 1, 5), 1), bar(date(2026, 1, 6)))
        now = bars[2].ends_at
        self.assertEqual(window_bars(auto, bars, now), bars[1:3])
        self.assertEqual(window_bars(auto, bars, bars[2].ends_at - timedelta(seconds=1)), bars[1:2])
        self.assertEqual(window_bars(auto, bars, bars[0].ends_at - timedelta(seconds=1)), ())

    def test_per_session_takes_only_the_given_trade_date(self) -> None:
        auto = intraday()
        night = bar(date(2026, 1, 5), 2, trade_date=date(2026, 1, 6))
        bars = (bar(date(2026, 1, 5)), night, bar(date(2026, 1, 6)))
        now = datetime(2026, 1, 7, tzinfo=UTC)
        self.assertEqual(window_bars(auto, bars, now, date(2026, 1, 6)), bars[1:])
        self.assertEqual(window_bars(auto, bars, now, date(2026, 1, 5)), bars[:1])
        self.assertEqual(window_bars(auto, bars, now, date(2026, 1, 9)), ())
        with self.assertRaises(DomainError):
            window_bars(auto, bars, now)

    def test_the_bar_limit_comes_from_the_pinned_thresholds_and_never_truncates(self) -> None:
        tight = PromotionThresholds(version='m3-thresholds-tight', EXECUTOR_MAX_BARS=3)
        bars = tuple(bar(date(2026, 1, 5), i) for i in range(4))
        now = bars[-1].ends_at
        with mock.patch.dict(promotion._KNOWN_THRESHOLDS, {tight.version: tight}):
            auto = make(thresholds_version=tight.version)
            self.assertEqual(window_bars(auto, bars[:3], now), bars[:3])
            with self.assertRaises(DomainError):
                window_bars(auto, bars, now)
        self.assertEqual(len(window_bars(make(), bars, now)), 4)
        self.assertEqual(DEFAULT_THRESHOLDS.EXECUTOR_MAX_BARS, 5000)

    def test_naive_now_is_refused(self) -> None:
        with self.assertRaises(DomainError):
            window_bars(make(), (), datetime(2026, 1, 5))


class TargetTests(unittest.TestCase):
    T0 = datetime(2026, 1, 5, 1, 5, tzinfo=UTC)

    def point(self, minutes: int, target: int, reason: str = 'r') -> SignalPoint:
        return SignalPoint(self.T0 + timedelta(minutes=minutes), target, reason)

    def test_desired_target_table(self) -> None:
        points = (self.point(0, 1), self.point(5, -1), self.point(10, 0), self.point(15, 2))
        table = [
            (-1, 0),
            (0, 1),
            (4, 1),
            (5, -1),
            (9, -1),
            (10, 0),
            (14, 0),
            (15, 2),
            (999, 2),
        ]
        for minutes, expected in table:
            with self.subTest(minutes=minutes):
                self.assertEqual(desired_target(points, self.T0 + timedelta(minutes=minutes)), expected)
        self.assertEqual(desired_target((), self.T0), 0)

    def test_order_of_points_does_not_matter_and_a_tie_takes_the_later_entry(self) -> None:
        points = (self.point(10, 3), self.point(0, 1), self.point(5, -1))
        self.assertEqual(desired_target(points, self.T0 + timedelta(minutes=7)), -1)
        self.assertEqual(desired_target(points, self.T0 + timedelta(minutes=10)), 3)
        tie = (self.point(5, 1), self.point(5, 2))
        self.assertEqual(desired_target(tie, self.T0 + timedelta(minutes=5)), 2)

    def test_direction_policy_table(self) -> None:
        for target, policy, expected in [
            (3, DirectionPolicy.BOTH, 3),
            (-3, DirectionPolicy.BOTH, -3),
            (0, DirectionPolicy.BOTH, 0),
            (3, DirectionPolicy.LONG_ONLY, 3),
            (-3, DirectionPolicy.LONG_ONLY, 0),
            (0, DirectionPolicy.LONG_ONLY, 0),
        ]:
            with self.subTest(target=target, policy=policy):
                self.assertEqual(apply_direction(target, policy), expected)

    def test_idempotency_key_is_utc_and_per_leg(self) -> None:
        taipei = timezone(timedelta(hours=8))
        intent = TargetIntent('auto-1', 1, datetime(2026, 1, 5, 9, 5, tzinfo=taipei), 1, 'enter', 'a' * 64)
        self.assertEqual(intent.idempotency_key(0), 'auto:aaaaaaaaaaaa:2026-01-05T01:05:00+00:00:0')
        self.assertNotEqual(intent.idempotency_key(0), intent.idempotency_key(1))
        with self.assertRaises(DomainError):
            intent.idempotency_key(-1)


class CandidateTypeTests(unittest.TestCase):
    def test_candidate_evidence_has_a_fixed_field_set_with_no_oos_values(self) -> None:
        self.assertEqual(
            [f.name for f in fields(CandidateEvidence)],
            [
                'candidate_ref',
                'campaign_ref',
                'candidate_fingerprint',
                'verdict',
                'oos_consumed',
                'sample_count',
                'completed_at',
                'dataset_family',
                'dataset_interval',
                'signal_spec_json',
            ],
        )
        self.assertEqual([f.name for f in fields(CandidateSummary)], ['candidate_ref', 'verdict', 'completed_at', 'dataset_interval'])
        for f in fields(CandidateEvidence):
            self.assertIn(f.type, (str, bool, int, datetime), f.name)

    def test_construction_and_boundaries(self) -> None:
        done = datetime(2026, 1, 5, tzinfo=UTC)
        ok = dict(
            candidate_ref='c1',
            campaign_ref='k1',
            candidate_fingerprint='fp',
            verdict='statistical_edge',
            oos_consumed=True,
            sample_count=40,
            completed_at=done,
            dataset_family='TMF',
            dataset_interval='1d',
            signal_spec_json=SPEC,
        )
        CandidateEvidence(**ok)
        CandidateSummary('c1', 'statistical_edge', done, '1d')
        for change in (
            dict(oos_consumed=1),
            dict(sample_count=-1),
            dict(completed_at=datetime(2026, 1, 5)),
            dict(dataset_interval='15m'),
            dict(signal_spec_json=''),
            dict(candidate_ref=''),
        ):
            with self.subTest(change), self.assertRaises(DomainError):
                CandidateEvidence(**{**ok, **change})
        with self.assertRaises(FrozenInstanceError):
            CandidateEvidence(**ok).verdict = 'x'  # type: ignore[misc]


class LayeringTests(unittest.TestCase):
    def test_domain_modules_import_only_stdlib_and_domain_and_ports_only_domain(self) -> None:
        allowed_stdlib = {'dataclasses', 'datetime', 'decimal', 'enum', 'functools', 'hashlib', 'json', 'typing'}
        for relative, internal in (
            ('quantlab/trading/domain/signal_strategy.py', 'quantlab.trading.domain'),
            ('quantlab/trading/domain/promotion.py', 'quantlab.trading.domain'),
            ('quantlab/trading/ports/signals.py', 'quantlab.trading.domain'),
            ('quantlab/trading/ports/candidates.py', 'quantlab.trading.domain'),
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = '.' * node.level + (node.module or '')
                    ok = module.split('.')[0] in allowed_stdlib or (node.level == 1 and 'domain' in relative) or module.startswith(internal)
                elif isinstance(node, ast.Import):
                    ok = all(alias.name.split('.')[0] in allowed_stdlib for alias in node.names)
                else:
                    continue
                with self.subTest(relative=relative, line=node.lineno):
                    self.assertTrue(ok, ast.dump(node))


if __name__ == '__main__':
    unittest.main()
