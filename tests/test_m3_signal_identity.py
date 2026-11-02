"""The M3 bridge executes the exact research callable and preserves its signals."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from quantlab import strategies
from quantlab.core import Bar, StrategySpec, canonical_json
from quantlab.research import candidate_fingerprint
from quantlab.trading.domain.signal_strategy import SignalBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import v1_signal_source as bridge

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = 'TAIFEX:TMF:202611'
UTC = timezone.utc


def bars():
    start = datetime(2026, 1, 5, tzinfo=UTC)
    prices = [1000 + ((i % 30) if i % 60 < 30 else (30 - i % 30)) * 10 for i in range(160)]
    return tuple(
        SignalBar(
            start + timedelta(minutes=i),
            start + timedelta(minutes=i + 1),
            start.date(),
            'day',
            Decimal(price),
            Decimal(price + 3),
            Decimal(price - 3),
            Decimal(price),
            0 if i % 19 == 0 else 10,
        )
        for i, price in enumerate(prices)
    )


def specs():
    values = list(strategies.builtin_strategies())
    values[-1] = replace(values[-1], parameters={'lookback': 10, 'max_range_bps': '2000'})
    long = {'op': 'gt', 'left': {'op': 'field', 'name': 'close'}, 'right': {'op': 'sma', 'field': 'close', 'period': 5, 'lag': 1}}
    short = {'op': 'lt', 'left': {'op': 'field', 'name': 'close'}, 'right': {'op': 'lowest', 'field': 'close', 'period': 3, 'lag': 1}}
    exit_rule = {'op': 'eq', 'left': {'op': 'return_bps', 'field': 'close', 'period': 2}, 'right': {'op': 'const', 'value': 0}}
    values.append(StrategySpec('ast', 'trend', {'fast': 2, 'slow': 5}, {'long': long, 'short': short, 'exit': exit_rule}))
    return values


class SignalIdentityTests(unittest.TestCase):
    def test_callable_identity_and_each_signal(self):
        self.assertIs(bridge.generate_signals, strategies.generate_signals)
        history = bars()
        original = tuple(Bar(b.starts_at, b.ends_at, b.trade_date.isoformat(), b.session, CONTRACT, b.open, b.high, b.low, b.close, b.volume) for b in history)
        for spec in specs():
            with self.subTest(family=spec.strategy_id), patch.object(bridge, 'generate_signals', wraps=strategies.generate_signals) as called:
                actual = bridge.V1SignalSource().signals(CONTRACT, history, canonical_json(spec))
                expected = strategies.generate_signals(original, spec)
                called.assert_called_once()
                self.assertEqual(called.call_args.args[0], original)
                self.assertEqual(called.call_args.args[1], spec)
                self.assertTrue(expected, 'fixture must exercise signals, not vacuous equality')
                self.assertEqual(tuple((p.at, p.target, p.reason) for p in actual), tuple((p.timestamp, p.target_position, p.reason) for p in expected))

    def test_empty_history_and_timezone_mapping(self):
        spec = canonical_json(specs()[0])
        self.assertEqual(bridge.V1SignalSource().signals(CONTRACT, (), spec), ())
        offset = timezone(timedelta(hours=8))
        local = tuple(replace(b, starts_at=b.starts_at.astimezone(offset), ends_at=b.ends_at.astimezone(offset)) for b in bars())
        self.assertEqual(bridge.V1SignalSource().signals(CONTRACT, local, spec), bridge.V1SignalSource().signals(CONTRACT, bars(), spec))

    def test_contract_tick_and_chronology_boundary(self):
        spec = canonical_json(specs()[0])
        for contract in ('2330', 'TAIFEX:TXF:202611', 'TMF_NEAR', 'TAIFEX:TMF:202613'):
            with self.subTest(contract=contract), self.assertRaises(DomainError) as caught:
                bridge.V1SignalSource().signals(contract, (), spec)
            self.assertEqual(caught.exception.code, 'validation_failed')
        fractional = replace(bars()[0], open=Decimal('1000.5'))
        for history in ((fractional,), tuple(reversed(bars())), (bars()[0], bars()[0])):
            with self.assertRaises(DomainError) as caught:
                bridge.V1SignalSource().signals(CONTRACT, history, spec)
            self.assertEqual(caught.exception.code, 'validation_failed')

    def test_spec_admission_uses_research_ast_and_fingerprint(self):
        for spec in specs():
            text = canonical_json(spec)
            self.assertEqual(bridge.validated_spec(text), spec)
            self.assertEqual(bridge.spec_fingerprint(text), candidate_fingerprint(spec))
            self.assertEqual(bridge.canonical_spec_json(text), text)
        valid = canonical_json(specs()[0])
        invalid = (
            'null',
            '[]',
            '{}',
            '{"family":"trend","family":"momentum"}',
            valid.replace('"rules":{}', '"rules":null'),
            valid.replace('"rules":{}', '"rules":{"long":{"op":"eval"},"short":{"op":"eval"}}'),
            'x' * 100001,
        )
        for text in invalid:
            with self.subTest(text=text[:60]), self.assertRaises(DomainError) as caught:
                bridge.V1SignalSource().signals(CONTRACT, (), text)
            self.assertEqual(caught.exception.code, 'candidate_spec_unsupported')
            self.assertEqual(str(caught.exception), 'candidate_spec_unsupported')

    def test_g3_locked_sources_are_byte_identical_to_task_base(self):
        contributing = (ROOT / 'docs/CONTRIBUTING.md').read_text(encoding='utf-8')
        locked_section = contributing.split('The G3 locked file set', 1)[1].split('The owner approved relocation', 1)[0]
        locked = re.findall(r'^- `([^`]+)`', locked_section, re.MULTILINE)
        self.assertEqual(len(locked), 30)
        for path in locked:
            with self.subTest(path=path):
                # The eight historical !eol G3 paths intentionally use platform
                # checkout conversion. Compare exact bytes under the same Git
                # filters, then independently verify canonical blob identity.
                baseline = subprocess.check_output(
                    ['git', 'cat-file', '--filters', '--path', path, f'0b7606658947c48457d23f3bd25e0f8dde33c3a7:{path}'], cwd=ROOT
                )
                current = (ROOT / path).read_bytes()
                self.assertEqual(hashlib.sha256(current).digest(), hashlib.sha256(baseline).digest())
                expected_blob = subprocess.check_output(['git', 'rev-parse', f'0b7606658947c48457d23f3bd25e0f8dde33c3a7:{path}'], cwd=ROOT).strip()
                current_blob = subprocess.check_output(['git', 'hash-object', '--stdin', '--path', path], input=current, cwd=ROOT).strip()
                self.assertEqual(current_blob, expected_blob)
        self.assertEqual(subprocess.check_output(['git', 'diff', '--stat', '0b7606658947c48457d23f3bd25e0f8dde33c3a7', '--', *locked], cwd=ROOT), b'')


if __name__ == '__main__':
    unittest.main()
