"""Frozen pre-change dispatch oracle, with exact byte/hash/error parity."""
from collections import UserDict
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum, IntEnum
import hashlib
import json
import math
import random
import sys
import unittest
from quantlab.core import ValidationError, canonical_json, content_hash, freeze, validate_decimal, validate_utc

def original_json_value(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: original_json_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Decimal):
        validate_decimal(value, "decimal")
        return format(value, 'f')
    if isinstance(value, datetime):
        validate_utc(value)
        return value.isoformat().replace('+00:00', 'Z')
    if isinstance(value, Enum):
        return original_json_value(value.value)
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValidationError("JSON keys must be strings")
        return {k: original_json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [original_json_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("nonfinite JSON number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValidationError(f"unsupported JSON value {type(value).__name__}")


def original_bytes(value):
    return json.dumps(original_json_value(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')

class Text(str):
    pass
class Integer(int):
    pass
class Float(float):
    pass
class Number(IntEnum):
    ONE = 1
class Word(str, Enum):
    TEXT = 'word'
class General(Enum):
    DECIMAL = Decimal('1.2300')
@dataclass
class Record:
    scalar: object
    nested: object

class CoreScalarParityTests(unittest.TestCase):
    def assert_parity(self, value):
        expected = original_bytes(value)
        self.assertEqual(canonical_json(value).encode('utf-8'), expected)
        self.assertEqual(content_hash(value), hashlib.sha256(expected).hexdigest())

    def test_exact_scalar_and_subclass_bytes_and_hashes(self):
        values = [None, True, False, 0, -1, 2**100, 0.0, -0.0, 1e-200, 1e200,
                  '', '繁體中文😀', Text('subclass'), Integer(17), Float(-0.0),
                  Number.ONE, Word.TEXT, General.DECIMAL, Decimal('-0.000'),
                  datetime(2026, 1, 2, tzinfo=timezone.utc)]
        for value in values:
            with self.subTest(type=type(value).__name__):
                self.assert_parity(value)
                self.assert_parity({'nested': [value, (value,)], 'record': Record(value, {'a': value})})
        self.assert_parity(freeze({'nested': [1, True, {'a': 'b'}]}))
        self.assert_parity({Text('key'): Integer(9)})

    def test_seeded_nested_values(self):
        rng = random.Random(8821)
        atoms = [None, True, False, -23, 1e-12, -0.0, '文', Integer(4), Number.ONE,
                 Word.TEXT, Decimal('0.0300'), datetime(2026, 1, 2, tzinfo=timezone.utc)]
        def make(depth):
            if not depth or rng.randrange(4) == 0:
                return rng.choice(atoms)
            if rng.randrange(2):
                return [make(depth-1) for _ in range(rng.randrange(5))]
            return {str(i): make(depth-1) for i in range(rng.randrange(5))}
        for _ in range(80):
            self.assert_parity(make(5))

    def test_rejections_match_type_and_message(self):
        values = [float('nan'), float('inf'), float('-inf'), Float('nan'), Float('inf'),
                  Decimal('NaN'), Decimal('Infinity'), datetime(2026, 1, 2),
                  UserDict({'x': 1}), {1: 'bad'}, {True: 'bad'}, b'bytes', {1}, object(), '\ud800']
        limit = getattr(sys, 'get_int_max_str_digits', lambda: 0)()
        if limit:
            values.append(10 ** (limit + 1))
        for value in values:
            for item in [value, {'nested': [value]}]:
                with self.subTest(type=type(value).__name__):
                    try:
                        original_bytes(item)
                    except Exception as error:
                        with self.assertRaises(type(error)) as actual:
                            canonical_json(item).encode('utf-8')
                        self.assertEqual(str(actual.exception), str(error))
                    else:
                        self.fail('Frozen invalid fixture unexpectedly accepted')

    def test_deep_supported_values_and_existing_recursion_rejection(self):
        value = 1
        for _ in range(60):
            value = {'x': [value]}
        self.assert_parity(value)
        for _ in range(1500):
            value = [value]
        for function in [original_bytes, canonical_json]:
            with self.assertRaises(RecursionError):
                function(value)
