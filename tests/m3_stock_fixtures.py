"""Deterministic TRAINING-only decimal and daily regression inputs."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quantlab.core import BacktestConfig, Bar, CostSpec, Dataset, StrategySpec, content_hash, to_dict
from quantlab.strategies import builtin_strategies


def daily_bars(contract='TAIFEX:TMF:202611', *, fractional=False):
    start = datetime(2025, 1, 2, 1, tzinfo=timezone.utc)
    result = []
    for index in range(100):
        at = start + timedelta(days=index)
        price = Decimal(1000 + (index % 20 if index % 40 < 20 else 20 - index % 20) * 10)
        if fractional:
            price = price / 10 + Decimal('.25')
        result.append(Bar(at, at + timedelta(hours=4, minutes=30), at.date().isoformat(), 'day', contract, price, price + 1, price - 1, price, 1000))
    return tuple(result)


def specs():
    long = {'op': 'gt', 'left': {'op': 'field', 'name': 'close'}, 'right': {'op': 'sma', 'field': 'close', 'period': 3, 'lag': 1}}
    short = {'op': 'lt', 'left': {'op': 'field', 'name': 'close'}, 'right': {'op': 'sma', 'field': 'close', 'period': 3, 'lag': 1}}
    return (*builtin_strategies(), StrategySpec('stock-scope-ast', 'trend', {'fast': 2, 'slow': 5}, {'long': long, 'short': short}))


def daily_dataset():
    bars = daily_bars()
    return Dataset(bars, {'source_type': 'synthetic', 'validation_status': 'valid', 'data_hash': content_hash(bars)}, {'valid': True})


def daily_config():
    return BacktestConfig(
        Decimal('1000000'),
        CostSpec(Decimal('15'), Decimal('.00002'), 1, 'none', '2020-01-01', 'synthetic-cost-v1'),
        initial_margin_per_contract=Decimal('1000'),
        maintenance_margin_per_contract=Decimal('800'),
        margin_version='synthetic-margin-v1',
        source_commit='stock-scope-regression',
    )


def behavior_hash(result):
    value = to_dict(result)
    # Exact source/runtime metadata is checked separately, not disguised as behavior.
    for key in ('source_hashes', 'engine_hash', 'run_hash', 'reproducibility_hash', 'python_version'):
        value['manifest'].pop(key)
    return content_hash(value)
