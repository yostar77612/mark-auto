"""Exact WFO snapshot encoding; all original commit/export boundaries remain."""
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from quantlab.core import ValidationError, canonical_json, content_hash, freeze
from quantlab import walk_forward as wf


class ExampleEnum(Enum):
    NUMBER = 17
    TEXT = '繁體中文'


@dataclass(frozen=True)
class ExampleRecord:
    amount: Decimal
    at: datetime
    members: tuple


def state_with(value):
    return {'binding': {'plan': {'folds': [{}, {}], 'candidate_pool': [{}, {}], 'max_evaluations': 10}},
        'folds': [], 'evaluations': [], 'final_holdout_status': 'excluded_not_evaluated',
        'evidence_mode': 'synthetic_validation', 'exposure_status': 'synthetic_not_market_evidence',
        'state_hash': object(), 'extra': value}


def original_encoding(state):
    """Pre-optimization algorithm retained as the equivalence oracle."""
    state['summary'] = wf._state_summary(state)
    state['state_hash'] = content_hash({k: v for k, v in state.items() if k != 'state_hash'})
    return canonical_json(state)


class WalkForwardSnapshotSerializationTests(unittest.TestCase):
    def assert_encoding(self, value):
        state = state_with(value)
        expected = original_encoding(deepcopy(state))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                statements = []; db.set_trace_callback(statements.append)
                wf._save_state(db, root, state)
                stored = db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]
                self.assertEqual(stored, expected)
                self.assertEqual((root / 'walk_forward.json').read_bytes(), expected.encode('utf-8'))
                self.assertEqual(sum(row == 'COMMIT' for row in statements), 1)
                self.assertEqual(sum(row.startswith('INSERT OR REPLACE') for row in statements), 1)
                self.assertFalse(db.in_transaction)
        self.assertIs(state['extra'], value)
        self.assertEqual(state['state_hash'], json.loads(expected)['state_hash'])

    def test_all_supported_value_types_preserve_exact_canonical_bytes_and_caller_values(self):
        utc = datetime(2026, 1, 2, 3, 4, 5, 678900, tzinfo=timezone.utc)
        for value in (None, True, False, 0, -10, 2**100, 0.0, -0.0, 1.23e-12,
                      '繁體中文\\n"quote"\x00', {'😀': 'é', 'z': 2, 'a': 1},
                      Decimal('1.2300'), Decimal('-0.000'), utc,
                      freeze({'items': [Decimal('2.500'), {'frozen': True}]}),
                      ExampleEnum.NUMBER, ExampleEnum.TEXT,
                      ExampleRecord(Decimal('42.100'), utc, (ExampleEnum.NUMBER, {'nested': [None, True]}))):
            with self.subTest(value_type=type(value).__name__):
                self.assert_encoding(value)

    def test_seeded_nested_supported_values_preserve_exact_bytes(self):
        randomizer = random.Random(31973)
        atoms = [None, True, False, -27, 0, 10**22, 1.2345, -0.0,
                 '文\n"\\', Decimal('0.0100'), ExampleEnum.TEXT,
                 datetime(2026, 1, 1, tzinfo=timezone.utc)]
        def value(depth):
            if depth == 0 or randomizer.randrange(3) == 0:
                return randomizer.choice(atoms)
            if randomizer.randrange(2):
                values = [value(depth - 1) for _ in range(randomizer.randrange(5))]
                return tuple(values) if randomizer.randrange(2) else values
            return {str(i) + '文': value(depth - 1) for i in range(randomizer.randrange(5))}
        for _ in range(60):
            self.assert_encoding(value(4))

    def test_invalid_values_fail_before_any_sql_or_commit(self):
        invalid = [float('nan'), float('inf'), float('-inf'), Decimal('NaN'), Decimal('Infinity'),
                   datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
                   {1: 'non-string key'}, {True: 'non-string key'}, b'bytes', {1, 2}, object()]
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                expected = state_with(value)
                with self.assertRaises(ValidationError) as old:
                    original_encoding(expected)
                actual = state_with(value); db = Mock()
                with self.assertRaises(ValidationError) as new:
                    wf._save_state(db, Path('/unused'), actual)
                self.assertEqual(str(new.exception), str(old.exception))
                db.execute.assert_not_called(); db.commit.assert_not_called()

    def test_unicode_encoding_and_integer_digit_errors_remain_before_database_write(self):
        values = ['\ud800', {'\udfff': 'bad key encoding'}]
        if getattr(sys, 'get_int_max_str_digits', lambda: 0)():
            values.append(10 ** (sys.get_int_max_str_digits() + 1))
        for value in values:
            expected = state_with(value)
            with self.assertRaises((UnicodeEncodeError, ValueError)) as old:
                original_encoding(expected)
            db = Mock()
            with self.assertRaises(type(old.exception)):
                wf._save_state(db, Path('/unused'), state_with(value))
            db.execute.assert_not_called(); db.commit.assert_not_called()

    def test_byte_budget_uses_identical_encoded_snapshot_before_database_write(self):
        value = {'multibyte': '文' * 40}
        expected = original_encoding(state_with(value))
        for limit in (len(expected.encode('utf-8')) - 1, len(expected) - 1):
            db = Mock()
            with patch.object(wf, 'MAX_STATE_BYTES', limit), self.assertRaises(ValidationError):
                wf._save_state(db, Path('/unused'), state_with(value))
            db.execute.assert_not_called(); db.commit.assert_not_called()
        with patch.object(wf, 'MAX_STATE_BYTES', len(expected.encode('utf-8'))):
            self.assert_encoding(value)

    def test_commit_failure_does_not_publish_export(self):
        db = Mock(); db.commit.side_effect = sqlite3.OperationalError('fixture commit failure')
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(sqlite3.OperationalError):
                wf._save_state(db, Path(temporary), state_with({'value': 1}))
            self.assertEqual(list(Path(temporary).iterdir()), [])
        db.commit.assert_called_once()

    def test_export_failure_leaves_exact_committed_authoritative_snapshot(self):
        state = state_with({'value': 1})
        expected = original_encoding(deepcopy(state))
        with tempfile.TemporaryDirectory() as temporary, closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            with patch.object(Path, 'write_text', side_effect=OSError('fixture export failure')):
                with self.assertRaises(OSError):
                    wf._save_state(db, Path(temporary), state)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0], expected)


if __name__ == '__main__':
    unittest.main()
