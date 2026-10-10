"""Bounded fixed-pool walk-forward selection, independent of AI generation.

Default evidence mode admits synthetic data only. Explicit historical_replay
allows real/proxy data as unverified, non-independent, non-rankable technical
replay. Legacy OOS exposure is not fully tracked by the shared holdout registry.
No mode claims untouched data, formal research ranking or paper qualification.
"""
from __future__ import annotations

import json
import multiprocessing
import math
import re
import platform
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from .core import (BacktestConfig, Dataset, StrategySpec, ValidationError,
                   canonical_json, content_hash, freeze, to_dict)
from .strategies import builtin_strategies, _validate_bars
from .data import validate_dataset
from .research import (_dataset_identity, _evaluate_split, _integer,
                       _keys, _reserve_holdout, _run_bounded,
                       ResourceTimeout, validate_dsl, _unique_keys)

MAX_STATE_BYTES = 16 * 1024 * 1024
SOURCE_FILES = ('walk_forward.py', 'saved_candidate_pool.py', 'research.py', 'core.py', 'data.py',
                'strategies.py', 'backtest.py')


def _bounded_number(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError('Finite bounded decimal required')
    parts = value.as_tuple()
    if abs(parts.exponent) > 32 or len(parts.digits) > 64 or value.copy_abs() > Decimal('1e15'):
        raise ValidationError('Decimal precision, exponent or magnitude exceeds resource bounds')


def _exact_number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValidationError('Finite numeric value required')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError('Finite numeric value required') from None
    _bounded_number(result)
    return result


def _bounded_value(value, *, max_nodes=4096):
    """Bound BEFORE canonical serialization or JSON numeric conversion."""
    count, byte_count = 0, 0
    def visit(item, depth=0):
        nonlocal count, byte_count
        count += 1
        if count > max_nodes or depth > 16:
            raise ValidationError('Plan/metadata structure exceeds resource bounds')
        if isinstance(item, Decimal):
            _bounded_number(item)
        elif is_dataclass(item) and not isinstance(item, type):
            for entry in fields(item):
                visit(getattr(item, entry.name), depth + 1)
        elif isinstance(item, dict):
            for key, child in item.items():
                if type(key) is not str:
                    raise ValidationError('JSON object keys must be strings')
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > 16384:
                raise ValidationError('Plan/metadata string exceeds resource bounds')
            byte_count += len(item.encode('utf-8'))
            if byte_count > 131072:
                raise ValidationError('Plan/metadata bytes exceed resource bounds')
            if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', item):
                _exact_number(item)
        elif type(item) is int:
            if item.bit_length() > 64:
                raise ValidationError('Integer exceeds resource bounds')
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValidationError('Nonfinite JSON value')
            _bounded_number(Decimal(str(item)))
        elif item is not None and type(item) is not bool and not isinstance(item, datetime):
            raise ValidationError('Unsupported plan/metadata type')
    visit(value)


def _bounds(value, name):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValidationError(name + ' requires [start, end) indexes')
    start, end = value
    _integer(start, 0, 100000, name + ' start')
    _integer(end, 1, 100000, name + ' end')
    if start >= end:
        raise ValidationError(name + ' must be nonempty and forward')
    return (start, end)


@dataclass(frozen=True)
class WalkForwardFold:
    train: tuple[int, int]
    validation: tuple[int, int]
    oos: tuple[int, int]

    def __post_init__(self):
        for name in ('train', 'validation', 'oos'):
            object.__setattr__(self, name, _bounds(getattr(self, name), name))


@dataclass(frozen=True)
class WalkForwardPlan:
    mode: str
    folds: tuple[WalkForwardFold, ...]
    final_holdout: tuple[int, int]
    backtest_config: BacktestConfig
    max_evaluations: int
    ranking: dict = field(default_factory=lambda: {'metric': 'net_pnl', 'minimum': '0', 'min_trades': 1, 'max_drawdown_pct': '0.10'})
    evidence_mode: str = 'synthetic_validation'
    gap_bars: int = 0
    max_runtime_seconds: int = 300
    max_bars: int = 100000
    process_start_method: str = 'spawn'
    worker_memory_mb: int = 512
    max_ipc_bytes: int = 4194304
    candidate_pool: tuple[StrategySpec, ...] = field(default_factory=builtin_strategies)
    schema_version: int = 1
    pool_origin: str = 'exact_builtin_pool'
    pool_admission: dict | None = None

    def __post_init__(self):
        _bounded_value(self, max_nodes=16384)
        _integer(self.schema_version, 1, 1, 'schema_version')
        if self.evidence_mode not in ('synthetic_validation', 'historical_replay'):
            raise ValidationError('Explicit synthetic_validation or historical_replay evidence mode required')
        if self.mode not in ('rolling', 'expanding'):
            raise ValidationError('mode must be rolling or expanding')
        if not isinstance(self.folds, (list, tuple)) or not 2 <= len(self.folds) <= 20 or any(not isinstance(f, WalkForwardFold) for f in self.folds):
            raise ValidationError('2..20 typed walk-forward folds required')
        object.__setattr__(self, 'folds', tuple(self.folds))
        object.__setattr__(self, 'final_holdout', _bounds(self.final_holdout, 'final_holdout'))
        if not isinstance(self.backtest_config, BacktestConfig):
            raise ValidationError('Explicit BacktestConfig with costs required')
        self.backtest_config.__post_init__()
        if self.backtest_config.roll_events or self.backtest_config.settlement_events or self.backtest_config.settlement_mode != 'unsettled_pnl':
            raise ValidationError('Walk-forward roll/settlement events require an unsupported split-scoped event protocol')
        if self.pool_origin not in ('exact_builtin_pool', 'saved_campaign_pool'):
            raise ValidationError('Explicit exact_builtin_pool or saved_campaign_pool origin required')
        evaluation_cap = 220 if self.pool_origin == 'exact_builtin_pool' else 620
        for name, low, high in (('max_evaluations', 1, evaluation_cap), ('gap_bars', 0, 1000),
                               ('max_runtime_seconds', 1, 7200), ('max_bars', 1, 100000),
                               ('worker_memory_mb', 128, 4096), ('max_ipc_bytes', 16384, 16777216)):
            _integer(getattr(self, name), low, high, name)
        if self.process_start_method not in multiprocessing.get_all_start_methods():
            raise ValidationError('Unsupported process start method')
        if not isinstance(self.ranking, dict):
            raise ValidationError('Typed ranking object required')
        _keys(dict(self.ranking), ('metric', 'minimum', 'min_trades', 'max_drawdown_pct'))
        if self.ranking['metric'] != 'net_pnl':
            raise ValidationError('Only predeclared net_pnl ranking supported')
        _exact_number(self.ranking['minimum'])
        _integer(self.ranking['min_trades'], 1, 1000000, 'min_trades')
        if not 0 <= _exact_number(self.ranking['max_drawdown_pct']) <= 1:
            raise ValidationError('max_drawdown_pct must be an exact fraction in [0, 1]')
        object.__setattr__(self, 'ranking', freeze(self.ranking))
        # An asserted snapshot permits deserialization, never admission. Saved
        # launches independently revalidate the authoritative inputs below.
        if (not isinstance(self.candidate_pool, (tuple, list))
            or any(not isinstance(spec, StrategySpec) for spec in self.candidate_pool)):
            raise ValidationError('Typed candidate pool required')
        if self.pool_origin == 'exact_builtin_pool':
            if (self.pool_admission is not None
                or canonical_json(self.candidate_pool) != canonical_json(builtin_strategies())):
                raise ValidationError('Only the exact five version-bound built-in candidates are supported')
        else:
            from .saved_candidate_pool import validate_admission_snapshot
            validate_admission_snapshot(self.pool_admission, self.candidate_pool)
            if self.max_evaluations > len(self.folds) * (2 * len(self.candidate_pool) + 1):
                raise ValidationError('Saved pool evaluation budget exceeds exact planned candidate-count bound')
            object.__setattr__(self, 'pool_admission', freeze(self.pool_admission))
        object.__setattr__(self, 'candidate_pool', tuple(self.candidate_pool))
        for spec in self.candidate_pool:
            validate_dsl(to_dict(spec))
        previous = None
        widths = None
        for fold in self.folds:
            train, validation, oos = fold.train, fold.validation, fold.oos
            if validation[0] != train[1] + self.gap_bars or oos[0] != validation[1] + self.gap_bars:
                raise ValidationError('Folds require exact predeclared gaps and forward split order')
            current_widths = (train[1] - train[0], validation[1] - validation[0], oos[1] - oos[0])
            if previous is not None:
                if (oos[0] < previous.oos[1] or train[1] <= previous.train[1]
                    or validation[0] <= previous.validation[0]):
                    raise ValidationError('Folds must advance with disjoint forward OOS ranges')
                if current_widths[1:] != widths[1:]:
                    raise ValidationError('Validation and OOS widths must remain fixed')
                if self.mode == 'rolling' and (current_widths[0] != widths[0] or train[0] <= previous.train[0]):
                    raise ValidationError('Rolling folds require a fixed advancing training window')
                if self.mode == 'expanding' and train[0] != previous.train[0]:
                    raise ValidationError('Expanding folds require a fixed training origin')
            previous, widths = fold, current_widths
        if self.final_holdout[0] < self.folds[-1].oos[1] + self.gap_bars:
            raise ValidationError('Final holdout must follow and be excluded from all folds')


def build_walk_forward_plan(*, backtest_config: BacktestConfig, train_bars: int,
                            validation_bars: int, oos_bars: int, fold_count: int,
                            final_holdout: tuple[int, int], start: int = 0,
                            step_bars: int | None = None, mode: str = 'rolling',
                            gap_bars: int = 0, **options) -> WalkForwardPlan:
    """Pure typed plan construction; this does not inspect prices or reserve data."""
    for name, value in (('train_bars', train_bars), ('validation_bars', validation_bars), ('oos_bars', oos_bars)):
        _integer(value, 1, 100000, name)
    _integer(fold_count, 2, 20, 'fold_count')
    _integer(start, 0, 100000, 'start')
    _integer(gap_bars, 0, 1000, 'gap_bars')
    step = oos_bars if step_bars is None else step_bars
    _integer(step, oos_bars, 100000, 'step_bars')
    folds = []
    for index in range(fold_count):
        train_start = start + index * step if mode == 'rolling' else start
        train_end = start + train_bars + index * step
        validation_start = train_end + gap_bars
        validation_end = validation_start + validation_bars
        oos_start = validation_end + gap_bars
        folds.append(WalkForwardFold((train_start, train_end), (validation_start, validation_end), (oos_start, oos_start + oos_bars)))
    options.setdefault('max_evaluations', fold_count * (2 * len(options.get('candidate_pool', builtin_strategies())) + 1))
    return WalkForwardPlan(mode=mode, folds=tuple(folds), final_holdout=final_holdout,
                           backtest_config=backtest_config, gap_bars=gap_bars, **options)


def walk_forward_plan_from_dict(payload: dict) -> WalkForwardPlan:
    """Strict desktop/JSON boundary; unknown keys and fabricated pool origins reject."""
    _bounded_value(payload, max_nodes=16384)
    required = ('mode', 'folds', 'final_holdout', 'backtest_config', 'max_evaluations')
    _keys(payload, required, tuple(f.name for f in fields(WalkForwardPlan) if f.name not in required))
    value = dict(payload)
    if type(value['folds']) is not list or not 2 <= len(value['folds']) <= 20:
        raise ValidationError('2..20 folds required')
    typed = []
    for fold in value['folds']:
        _keys(fold, ('train', 'validation', 'oos'))
        typed.append(WalkForwardFold(**fold))
    value['folds'] = tuple(typed)
    if type(value['backtest_config']) is dict:
        from .__main__ import config_from_json
        value['backtest_config'] = config_from_json(value['backtest_config'])
    if 'candidate_pool' in value:
        if type(value['candidate_pool']) is not list or not 1 <= len(value['candidate_pool']) <= 15:
            raise ValidationError('Bounded candidate pool required')
        value['candidate_pool'] = tuple(validate_dsl(spec) for spec in value['candidate_pool'])
    return WalkForwardPlan(**value)


def _validate_source(dataset, plan):
    if not isinstance(dataset, Dataset) or not isinstance(plan, WalkForwardPlan):
        raise ValidationError('Dataset and typed WalkForwardPlan required')
    plan.__post_init__()
    if not dataset.bars or len(dataset.bars) > plan.max_bars:
        raise ValidationError('Source bar resource budget exceeded')
    _bounded_value(dataset.manifest)
    _bounded_value(dataset.quality)
    source_bytes = 0
    for bar in dataset.bars:
        for value in (bar.open, bar.high, bar.low, bar.close):
            _bounded_number(value)
        if type(bar.volume) is not int or bar.volume.bit_length() > 64:
            raise ValidationError('Bar volume exceeds resource bounds')
        if type(bar.source_id) is not str or len(bar.source_id) > 4096:
            raise ValidationError('Bar source identifier exceeds resource bounds')
        source_bytes += len(bar.source_id.encode('utf-8'))
        if source_bytes > 16777216:
            raise ValidationError('Source identifier bytes exceed resource bounds')
    validate_dataset(dataset)
    if dataset.quality.get('missing_intervals', 0):
        raise ValidationError('Validated complete source intervals required')
    if plan.evidence_mode == 'synthetic_validation' and dataset.manifest.get('source_type') != 'synthetic':
        raise ValidationError('Real/proxy-data exposure provenance is unknown; choose historical_replay explicitly for non-independent technical replay')
    if dataset.manifest.get('source_type') != 'synthetic':
        if any(b.contract_id not in plan.backtest_config.instrument_expiries for b in dataset.bars):
            raise ValidationError('Explicit instrument expiries required for historical replay')
    if not dataset.bars or len(dataset.bars) > plan.max_bars or plan.final_holdout[1] != len(dataset.bars):
        raise ValidationError('Source bar budget or final-holdout tail boundary invalid')
    _validate_bars(dataset.bars)
    # Index boundaries must not divide a simultaneous event group or overlap
    # interval availability. Conservative like the existing campaign protocol.
    if any(a.end > b.timestamp for a, b in zip(dataset.bars, dataset.bars[1:])):
        raise ValidationError('Nonchronological or overlapping event intervals')


def _slice(dataset, bounds, *, fold_index, role):
    start, end = bounds
    bars = dataset.bars[start:end]
    # Whole-source identity lives in the experiment binding, not in a split's
    # result: excluded future prices cannot alter an earlier split's result hash.
    manifest = {key: dataset.manifest[key] for key in ('source_type', 'calendar_version', 'calendar_hash') if key in dataset.manifest}
    manifest.update(validation_status='valid', data_hash=content_hash(bars),
                    coverage={'start': bars[0].timestamp, 'end': bars[-1].end},
                    walk_forward_split={'fold': fold_index, 'role': role, 'start': start, 'end': end,
                                        'warmup': 'independent_no_prior_access'})
    return Dataset(tuple(bars), manifest, dict(dataset.quality))


def _passes_validation(summary, ranking):
    """Risk/trade gates precede profit ordering; no ambient Decimal arithmetic."""
    try:
        metrics = summary['metrics']
        drawdown = _exact_number(metrics.get('max_drawdown_pct'))
        trades = metrics.get('trade_count')
        return (type(trades) is int and trades >= ranking['min_trades']
                and 0 <= drawdown <= _exact_number(ranking['max_drawdown_pct'])
                and _exact_number(metrics.get('net_pnl')) >= _exact_number(ranking['minimum']))
    except (KeyError, TypeError, ValidationError):
        return False


def _read_state(db):
    row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
    if row is None:
        return None
    if type(row[0]) is not str or len(row[0].encode('utf-8')) > MAX_STATE_BYTES:
        raise ValidationError('Invalid walk-forward journal')
    state = json.loads(row[0], object_pairs_hook=_unique_keys,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('Nonfinite journal value')))
    if (type(state) is not dict or state.get('state_hash') != content_hash({k: v for k, v in state.items() if k != 'state_hash'})
        or state.get('experiment_id') != content_hash(state.get('binding'))
        or type(state.get('binding')) is not dict
        or type(state.get('evaluations')) is not list or len(state['evaluations']) > 620
        or type(state.get('folds')) is not list or len(state['folds']) > 20
        or state.get('status') not in ('running', 'completed', 'completed_with_errors',
                                      'cancelled', 'budget_exhausted', 'blocked_interrupted',
                                      'blocked_previously_consumed_range', 'blocked_registry_busy')):
        raise ValidationError('Invalid walk-forward journal identity')
    _validate_state(state)
    return state


def _state_summary(state):
    return {
        'planned_folds': len(state['binding']['plan']['folds']),
        'evaluated_oos_folds': sum(f['status'] == 'evaluated' for f in state['folds']),
        'evaluations_reserved': len(state['evaluations']),
        'evaluation_limit': state['binding']['plan']['max_evaluations'],
        'planned_evaluations_upper_bound': len(state['binding']['plan']['folds']) * (2 * len(state['binding']['plan']['candidate_pool']) + 1),
        'model_calls': 0, 'final_holdout_status': state['final_holdout_status'],
        'evidence_mode': state['evidence_mode'], 'exposure_status': state['exposure_status'],
        'independent_oos': False, 'ranking_eligible': False, 'paper_eligible': False,
        'strategy_qualification': 'not_assessed', 'portfolio_return': None,
        'portfolio_return_reason': 'independent_flat_start_folds_not_a_continuous_portfolio'}


def _save_state(db, output_dir, state):
    state['summary'] = _state_summary(state)
    state['state_hash'] = content_hash({k: v for k, v in state.items() if k != 'state_hash'})
    encoded = canonical_json(state)
    if len(encoded.encode('utf-8')) > MAX_STATE_BYTES:
        raise ValidationError('Walk-forward journal byte budget exceeded')
    db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (encoded,))
    db.commit()
    path = output_dir / 'walk_forward.json.tmp'
    path.write_text(encoded, encoding='utf-8')
    path.replace(output_dir / 'walk_forward.json')


def _validate_state(state):
    """Fail closed on inconsistent completed evidence, including recomputed checksums."""
    try:
        plan = state['binding']['plan']
        pool = plan['candidate_pool']
        replay = plan['evidence_mode'] == 'historical_replay'
        # Old checkpoint journals omit both optional pool fields; read them as
        # their original builtin protocol without rewriting the journal.
        origin = plan.get('pool_origin', 'exact_builtin_pool')
        if origin == 'exact_builtin_pool':
            if (plan.get('pool_admission') is not None or plan['max_evaluations'] > 220
                or canonical_json(pool) != canonical_json(builtin_strategies())):
                raise ValidationError('Invalid persisted builtin pool')
        elif origin == 'saved_campaign_pool':
            from .saved_candidate_pool import validate_admission_snapshot
            validate_admission_snapshot(plan.get('pool_admission'), tuple(validate_dsl(spec) for spec in pool))
            if plan['max_evaluations'] > min(620, len(plan['folds']) * (2 * len(pool) + 1)):
                raise ValidationError('Invalid persisted saved pool evaluation bound')
        else:
            raise ValidationError('Invalid persisted pool origin')
        if (state['binding']['protocol'] != ('fixed_builtin_walk_forward_v1' if origin == 'exact_builtin_pool' else 'fixed_saved_campaign_walk_forward_v1')
            or state['binding']['candidate_pool_hash'] != content_hash(pool)
            or type(state['model_calls']) is not int or state['model_calls'] != 0
            or state['scope'] != ('historical_replay_exposure_unverified' if replay else 'synthetic_fixed_pool_technical_evaluation')
            or state['exposure_status'] != ('unverified' if replay else 'synthetic_not_market_evidence')
            or state['independent_oos'] is not False
            or state['ranking_eligible'] is not False or state['paper_eligible'] is not False
            or state['evidence_mode'] != plan['evidence_mode']
            or state['final_holdout_status'] != 'excluded_not_evaluated'
            or state['summary'] != _state_summary(state)
            or len(state['evaluations']) > plan['max_evaluations']):
            raise ValidationError('Inconsistent walk-forward evidence labels or counters')
        by_sequence, keys = {}, set()
        for index, record in enumerate(state['evaluations'], 1):
            key = (record['fold'], record['role'], record['strategy_hash'])
            if (record['sequence'] != index or key in keys or record['role'] not in ('train', 'validation', 'oos')
                or record['strategy_hash'] not in [content_hash(spec) for spec in pool]
                or record['status'] not in ('running', 'evaluated', 'failed', 'timed_out', 'interrupted')):
                raise ValidationError('Inconsistent walk-forward evaluation ledger')
            keys.add(key)
            by_sequence[index] = record
        complete = state['status'] in ('completed', 'completed_with_errors')
        referenced = set()
        for index, fold in enumerate(state['folds']):
            if fold['index'] != index or fold['plan'] != plan['folds'][index]:
                raise ValidationError('Inconsistent fold plan')
            eligible = []
            for pool_index, candidate in enumerate(fold['candidates']):
                if candidate['pool_index'] != pool_index or candidate['strategy_hash'] != content_hash(pool[pool_index]):
                    raise ValidationError('Inconsistent candidate pool')
                for role in ('train', 'validation'):
                    if role in candidate:
                        record = candidate[role]
                        if (record != by_sequence[record['sequence']] or record['fold'] != index
                            or record['role'] != role or record['strategy_hash'] != candidate['strategy_hash']):
                            raise ValidationError('Inconsistent candidate evaluation')
                        referenced.add(record['sequence'])
                if (candidate.get('train', {}).get('status') == 'evaluated'
                    and candidate.get('validation', {}).get('status') == 'evaluated'
                    and _passes_validation(candidate['validation']['result'], plan['ranking'])):
                    eligible.append(candidate)
            selection = fold['selection']
            if selection is not None:
                winner = min(eligible, key=lambda row: (_exact_number(row['validation']['result']['metrics']['net_pnl']).copy_negate(), row['pool_index']))
                if (fold['selection_hash'] != content_hash(selection) or selection['spec'] != pool[selection['pool_index']]
                    or selection['strategy_hash'] != content_hash(selection['spec'])
                    or selection['pool_index'] != winner['pool_index'] or selection['ranking'] != plan['ranking']
                    or selection['validation_result_hash'] != winner['validation']['result']['result_hash']):
                    raise ValidationError('Inconsistent frozen selection')
            elif fold['selection_hash'] is not None:
                raise ValidationError('Unexpected selection hash')
            if fold['oos'] is not None:
                record = fold['oos']
                if (selection is None or record != by_sequence[record['sequence']] or record['fold'] != index
                    or record['role'] != 'oos' or record['strategy_hash'] != selection['strategy_hash']):
                    raise ValidationError('Inconsistent forward evaluation')
                referenced.add(record['sequence'])
            if complete and (len(fold['candidates']) != len(pool) or any(role not in c for c in fold['candidates'] for role in ('train', 'validation'))
                or fold['status'] not in ('evaluated', 'evaluation_failed', 'no_eligible_candidate')
                or (fold['status'] == 'no_eligible_candidate' and (eligible or selection is not None))
                or (fold['status'] in ('evaluated', 'evaluation_failed') and fold['oos'] is None)):
                raise ValidationError('Incomplete completed fold')
        if complete and (len(state['folds']) != len(plan['folds']) or referenced != set(by_sequence)
                         or any(r['status'] in ('running', 'interrupted') for r in by_sequence.values())
                         or (state['status'] == 'completed' and any(r['status'] != 'evaluated' for r in by_sequence.values()))):
            raise ValidationError('Incomplete completed experiment')
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValidationError('Invalid walk-forward journal consistency') from exc


def _interrupt(state):
    for record in state['evaluations']:
        if record['status'] == 'running':
            record['status'] = 'interrupted'
    for fold in state['folds']:
        if fold['status'] in ('training', 'selection_frozen'):
            fold['status'] = 'interrupted'
    state['status'] = 'blocked_interrupted'
    state['warnings'].append('Interrupted execution is terminal; reserved evaluations and OOS ranges remain consumed.')


def read_walk_forward_state(output_dir: Path) -> dict:
    """Read the authoritative journal without evaluation or state changes."""
    path = Path(output_dir) / 'walk_forward.sqlite3'
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
        state = _read_state(db)
    if state is None:
        raise ValidationError('Missing walk-forward state')
    return state


def reconcile_interrupted_walk_forward(*, output_dir: Path, descendants_stopped: bool = False) -> dict:
    """Call only after the desktop host stops/joins its process tree; never replay."""
    if descendants_stopped is not True:
        raise ValidationError('Walk-forward descendants must be stopped before reconciliation')
    output_dir = Path(output_dir)
    lock_path = output_dir / 'walk_forward.lock.sqlite3'
    state_path = output_dir / 'walk_forward.sqlite3'
    with closing(sqlite3.connect(lock_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0)) as lock:
        lock.execute('BEGIN EXCLUSIVE')
        with closing(sqlite3.connect(state_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0)) as db:
            state = _read_state(db)
            if state is None:
                raise ValidationError('Missing walk-forward state')
            if state['status'] == 'running':
                _interrupt(state)
                _save_state(db, output_dir, state)
            return state


class _StopRun(Exception):
    def __init__(self, status):
        self.status = status


def planned_evaluations(plan: WalkForwardPlan) -> int:
    """Exact predeclared upper bound; failures still consume reserved slots."""
    return len(plan.folds) * (2 * len(plan.candidate_pool) + 1)


def walk_forward_binding(dataset: Dataset, plan: WalkForwardPlan, registry: Path) -> dict:
    """One canonical binding shared with read-only preview adapters."""
    registry = Path(registry).resolve()
    return {'protocol': ('fixed_builtin_walk_forward_v1' if plan.pool_origin == 'exact_builtin_pool'
                         else 'fixed_saved_campaign_walk_forward_v1'), 'plan': to_dict(plan),
            'source_identity': _dataset_identity(dataset), 'source_data_hash': dataset.manifest['data_hash'],
            'python_version': platform.python_version(), 'candidate_pool_hash': content_hash(plan.candidate_pool),
            'registry_identity': {'resolved_path': str(registry), 'coverage_policy': 'conservative_per_contract_envelopes'},
            'source_hashes': {name: content_hash(Path(__file__).with_name(name).read_text(encoding='utf-8')) for name in SOURCE_FILES}}


def run_walk_forward(dataset: Dataset, *, plan: WalkForwardPlan, output_dir: Path,
                     holdout_registry_path: Path, cancelled: Callable[[], bool] | None = None,
                     source_campaign_dir: Path | None = None, original_dataset: Dataset | None = None) -> dict:
    """Run one nonadaptive, fixed-pool experiment. Every restart is read/fail-closed.

    Planned OOS envelopes are consumed before ANY scoring, even if later cancelled.
    Prior-fold OOS bars may enter later predeclared historical windows; OOS metrics
    never enter selection. Final holdout is excluded and never scored.
    """
    started = time.monotonic()
    _validate_source(dataset, plan)
    if plan.pool_origin == 'saved_campaign_pool':
        from .saved_candidate_pool import admit_saved_campaign_pool
        if source_campaign_dir is None or original_dataset is None:
            raise ValidationError('Saved pool requires authoritative source campaign and exact original dataset at launch')
        admission = admit_saved_campaign_pool(source_campaign_dir=source_campaign_dir,
            source_campaign_ref=plan.pool_admission['source_campaign_ref'], original_dataset=original_dataset,
            original_dataset_ref=plan.pool_admission['original_dataset_ref'],
            first_training_timestamp=dataset.bars[plan.folds[0].train[0]].timestamp,
            authoritative_registry_path=holdout_registry_path)
        if (canonical_json(admission.admission) != canonical_json(plan.pool_admission)
            or canonical_json(admission.candidate_pool) != canonical_json(plan.candidate_pool)):
            raise ValidationError('Saved source/admission changed; preview again before any reservation')
    elif source_campaign_dir is not None or original_dataset is not None:
        raise ValidationError('Builtin and saved source inputs are mutually exclusive')
    output_dir = Path(output_dir).resolve()
    registry = Path(holdout_registry_path).resolve()
    if registry.is_relative_to(output_dir):
        raise ValidationError('Authoritative registry must be outside the experiment output directory')
    config = to_dict(plan)
    binding = walk_forward_binding(dataset, plan, registry)
    experiment_id = content_hash(binding)
    output_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(output_dir / 'walk_forward.lock.sqlite3', timeout=0)) as lock:
        try:
            lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError as exc:
            raise ValidationError('Walk-forward experiment is already running') from exc
        with closing(sqlite3.connect(output_dir / 'walk_forward.sqlite3', timeout=0)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            state = _read_state(db)
            if state is not None:
                if state['experiment_id'] != experiment_id:
                    raise ValidationError('Walk-forward source/config/pool/registry is immutable; output directory conflict')
                if state['status'] == 'running':
                    _interrupt(state)
                    _save_state(db, output_dir, state)
                return state
            state = {'experiment_id': experiment_id, 'binding': binding, 'status': 'running',
                     'source_manifest': to_dict(dataset.manifest), 'elapsed_seconds': 0,
                     'scope': 'historical_replay_exposure_unverified' if plan.evidence_mode == 'historical_replay' else 'synthetic_fixed_pool_technical_evaluation',
                     'evidence_mode': plan.evidence_mode,
                     'exposure_status': 'unverified' if plan.evidence_mode == 'historical_replay' else 'synthetic_not_market_evidence',
                     'independent_oos': False, 'ranking_eligible': False, 'paper_eligible': False, 'model_calls': 0,
                     'final_holdout_status': 'excluded_not_evaluated', 'registry_reservation': None,
                     'evaluations': [], 'folds': [], 'summary': {},
                     'warnings': [('Fixed built-in pool; no adaptive AI generation or imported AI provenance.'
                                   if plan.pool_origin == 'exact_builtin_pool' else
                                   'Fixed saved campaign pool; local artifact admission does not verify model inference, unseen exposure or profitability.'),
                                  'Technical evidence only; no formal ranking, paper qualification or profitability claim.',
                                  'historical_replay is exposure-unverified and not independent OOS; validation chooses only a scenario to replay.',
                                  'The default 10% validation drawdown cap and minimum one closed lot are engineering guards, not financial acceptance.',
                                  'Training scores are descriptive; a failed training engine evaluation still disqualifies an unverifiable candidate.',
                                  'Independent split warmup and flat starts; no cross-boundary positions or feature state.',
                                  'Later predeclared training may use earlier OOS bars after they become historical, never OOS metrics.',
                                  'Shared registry checks only registered exposures; legacy OOS exposure is not fully registered.',
                                  'OOS coverage envelopes are reserved once before scoring and stay consumed after cancellation.',
                                  'The excluded final holdout is not evaluated here; this is not a claim that it is untouched.',
                                  'Deleting/copying/restoring the authoritative registry cannot establish unseen data.',
                                  'Worker address-space limits apply only where supported; isolation is not a filesystem/network sandbox.']}
            deadline = started + plan.max_runtime_seconds
            def save():
                state['elapsed_seconds'] = time.monotonic() - started
                _save_state(db, output_dir, state)
            def check():
                if cancelled is not None and cancelled():
                    raise _StopRun('cancelled')
                if time.monotonic() >= deadline or len(state['evaluations']) >= plan.max_evaluations:
                    raise _StopRun('budget_exhausted')
            def evaluate(fold_index, role, split, spec):
                check()
                record = {'sequence': len(state['evaluations']) + 1, 'fold': fold_index, 'role': role,
                          'strategy_hash': content_hash(spec), 'status': 'running'}
                state['evaluations'].append(record)
                save()  # Durable reservation consumes the global slot BEFORE work.
                try:
                    result = _run_bounded(_evaluate_split, (split, spec, plan.backtest_config), deadline=deadline, config=config)
                    record.update(result=result['value'], status='evaluated',
                                  memory_limit_enforced=result.get('memory_limit_enforced', False))
                except Exception as exc:
                    record.update(status='timed_out' if isinstance(exc, ResourceTimeout) else 'failed', error=type(exc).__name__)
                    if isinstance(exc, ResourceTimeout):
                        raise _StopRun('budget_exhausted') from None
                finally:
                    save()
                return record
            save()
            try:
                check()
                oos_bars = tuple(bar for fold in plan.folds for bar in dataset.bars[fold.oos[0]:fold.oos[1]])
                protected = Dataset(oos_bars, {}, {})
                checked = Dataset(dataset.bars[plan.folds[0].train[0]:plan.final_holdout[1]], {}, {})
                # Reservation's selection_hash binds the predeclared pool/plan;
                # per-fold winner hashes are distinct and frozen later, before OOS.
                try:
                    reservation = _reserve_holdout(protected, registry_path=registry,
                        campaign_id=experiment_id, selection_hash=content_hash(config), output_dir=output_dir,
                        guard_dataset=checked, deadline=deadline)
                except ResourceTimeout:
                    raise _StopRun('budget_exhausted') from None
                except sqlite3.OperationalError as exc:
                    if getattr(exc, 'sqlite_errorcode', None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        raise _StopRun('budget_exhausted' if time.monotonic() >= deadline else 'blocked_registry_busy') from None
                    raise
                state['registry_reservation'] = reservation
                save()
                if reservation['status'] != 'reserved_consumed':
                    state['status'] = 'blocked_previously_consumed_range'
                    save()
                    return state
                for fold_index, fold in enumerate(plan.folds):
                    fold_state = {'index': fold_index, 'plan': to_dict(fold), 'status': 'training',
                                  'candidates': [], 'selection': None, 'selection_hash': None, 'oos': None}
                    state['folds'].append(fold_state)
                    save()
                    train = _slice(dataset, fold.train, fold_index=fold_index, role='train')
                    validation = _slice(dataset, fold.validation, fold_index=fold_index, role='validation')
                    for pool_index, spec in enumerate(plan.candidate_pool):
                        scores = {'pool_index': pool_index, 'strategy_hash': content_hash(spec)}
                        fold_state['candidates'].append(scores)
                        for role, split in (('train', train), ('validation', validation)):
                            scores[role] = evaluate(fold_index, role, split, spec)
                        save()
                    eligible = [row for row in fold_state['candidates']
                                if row['train']['status'] == 'evaluated' and row['validation']['status'] == 'evaluated'
                                and _passes_validation(row['validation']['result'], plan.ranking)]
                    if not eligible:
                        fold_state['status'] = 'no_eligible_candidate'
                        save()
                        continue
                    winner = sorted(eligible, key=lambda row: (_exact_number(row['validation']['result']['metrics']['net_pnl']).copy_negate(), row['pool_index']))[0]
                    spec = plan.candidate_pool[winner['pool_index']]
                    selection = {'pool_index': winner['pool_index'], 'spec': to_dict(spec),
                                 'strategy_hash': content_hash(spec), 'train_data_hash': train.manifest['data_hash'],
                                 'validation_data_hash': validation.manifest['data_hash'], 'ranking': to_dict(plan.ranking),
                                 'validation_result_hash': winner['validation']['result']['result_hash']}
                    fold_state.update(selection=selection, selection_hash=content_hash(selection), status='selection_frozen')
                    save()  # No OOS result or data is passed to selection.
                    oos = _slice(dataset, fold.oos, fold_index=fold_index, role='oos')
                    fold_state['oos'] = evaluate(fold_index, 'oos', oos, spec)
                    fold_state['status'] = 'evaluated' if fold_state['oos']['status'] == 'evaluated' else 'evaluation_failed'
                    save()
                state['status'] = 'completed_with_errors' if any(row['status'] != 'evaluated' for row in state['evaluations']) else 'completed'
            except _StopRun as stop:
                state['status'] = stop.status
                for fold in state['folds']:
                    if fold['status'] in ('training', 'selection_frozen'):
                        fold['status'] = stop.status
            save()
            return state
