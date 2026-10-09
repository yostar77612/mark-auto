"""Offline, bounded strategy research. No broker, credential, or network clients.

Campaigns are immutable within an output directory. Deleting the directory destroys
its audit history; it does not make a previously examined holdout unseen again.
"""
from __future__ import annotations

import copy
import json
import math
import multiprocessing
import sys
import re
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from contextlib import closing
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlsplit

from .core import BacktestConfig, Dataset, StrategySpec, ValidationError, canonical_json, content_hash, to_dict
from .strategies import builtin_strategies, validate_strategy
from .backtest import run_backtest

FAMILIES = ('trend', 'mean_reversion', 'channel_breakout', 'momentum', 'volatility_compression')
FIELDS = {'open', 'high', 'low', 'close', 'volume'}
PROMPT = 'quantlab-v1: Return only the bounded strategy JSON DSL. Training and validation summaries only. Risk controls are immutable.'


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError('Duplicate JSON key')
        result[key] = value
    return result


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(f'{name} must be an integer in [{low}, {high}]')
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValidationError('Expected finite number')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError('Expected finite number') from exc
    if not result.is_finite() or abs(result) > Decimal('1e15'):
        raise ValidationError('Nonfinite or excessive number')
    return result


def _keys(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValidationError('Unknown or missing keys')


def _bounded_json(value):
    count = 0
    def walk(item, depth):
        nonlocal count
        count += 1
        if depth > 16 or count > 256:
            raise ValidationError('DSL depth/node budget exceeded')
        if type(item) is dict:
            for key, val in item.items():
                if type(key) is not str:
                    raise ValidationError('JSON keys must be strings')
                walk(val, depth + 1)
        elif type(item) is list:
            for val in item:
                walk(val, depth + 1)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValidationError('DSL must contain JSON values only')
        elif type(item) is float and not math.isfinite(item):
            raise ValidationError('Nonfinite JSON number')
    walk(value, 0)
    if len(json.dumps(value, allow_nan=False).encode('utf-8')) > 16384:
        raise ValidationError('DSL byte budget exceeded')


def _node(node, expected):
    if type(node) is not dict or 'op' not in node:
        raise ValidationError('Expected typed AST node')
    op = node['op']
    if op == 'const':
        _keys(node, ('op', 'value'))
        _number(node['value'])
        actual = 'number'
    elif op == 'field':
        _keys(node, ('op', 'name'), ('lag',))
        if type(node['name']) is not str or node['name'] not in FIELDS:
            raise ValidationError('Unknown OHLCV field')
        _integer(node.get('lag', 0), 0, 500, 'lag')
        actual = 'number'
    elif op in ('sma', 'highest', 'lowest', 'return_bps'):
        _keys(node, ('op', 'field', 'period'), ('lag',))
        if type(node['field']) is not str or node['field'] not in FIELDS:
            raise ValidationError('Unknown indicator field')
        _integer(node['period'], 1, 500, 'period')
        _integer(node.get('lag', 0), 0, 500, 'lag')
        actual = 'number'
    elif op in ('gt', 'gte', 'lt', 'lte', 'eq'):
        _keys(node, ('op', 'left', 'right'))
        _node(node['left'], 'number')
        _node(node['right'], 'number')
        actual = 'bool'
    elif op in ('and', 'or'):
        _keys(node, ('op', 'args'))
        if type(node['args']) is not list or not 2 <= len(node['args']) <= 8:
            raise ValidationError('Boolean operator requires 2..8 arguments')
        for arg in node['args']:
            _node(arg, 'bool')
        actual = 'bool'
    elif op == 'not':
        _keys(node, ('op', 'arg'))
        _node(node['arg'], 'bool')
        actual = 'bool'
    else:
        raise ValidationError('Unknown AST operator')
    if actual != expected:
        raise ValidationError('AST type mismatch')


def validate_dsl(payload: dict) -> StrategySpec:
    """Validate syntax, resource limits and executable registry semantics."""
    _bounded_json(payload)
    _keys(payload, ('strategy_id', 'family', 'parameters', 'rules'), ('schema_version',))
    if type(payload['strategy_id']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', payload['strategy_id']):
        raise ValidationError('Invalid strategy ID')
    if type(payload['family']) is not str or payload['family'] not in FAMILIES:
        raise ValidationError('Unknown family')
    _integer(payload.get('schema_version', 1), 1, 1, 'schema_version')
    if type(payload['parameters']) is not dict or len(payload['parameters']) > 12:
        raise ValidationError('Invalid parameter budget')
    rules = payload['rules']
    if rules:
        _keys(rules, ('long', 'short'), ('exit',))
        for value in rules.values():
            _node(value, 'bool')
    elif type(rules) is not dict:
        raise ValidationError('rules must be an object')
    spec = StrategySpec(**copy.deepcopy(payload))
    validate_strategy(spec)
    return spec


class Generator(Protocol):
    def generate(self, context: dict) -> dict: ...
    def improve(self, context: dict) -> dict: ...


class FixtureGenerator:
    """Deterministic test fixture, never a real-model evaluation."""
    mode = 'fixture'
    real_model_status = 'not_verified'
    def generate(self, context: dict) -> dict:
        spec = next(s for s in builtin_strategies() if s.family == context['family'])
        result = to_dict(spec)
        result['strategy_id'] = f"fixture_{context['family']}_{context['iteration']}"
        return result

    def improve(self, context: dict) -> dict:
        result = self.generate(context)
        # A deterministic parameter proposal, evaluated honestly, never a fixed rank.
        key = 'fast' if context['family'] == 'trend' else 'lookback'
        result['parameters'][key] += context['iteration']
        return result


class CompatibleProvider:
    """Explicit opt-in, injected OpenAI-compatible transport; no HTTP implementation.

    transport(endpoint, request, timeout_seconds) must enforce the timeout. Budget
    reservations are durable and conservative, including failures and crashes.
    No credentials are accepted here. Separate authorization is needed for real use.
    """
    mode = 'openai_compatible'
    real_model_status = 'not_verified'

    def __init__(self, *, model: str, endpoint: str, transport: Callable,
                 budget_path: Path, network_opt_in: bool = False,
                 timeout_seconds: int = 30, max_calls: int = 0,
                 max_tokens: int = 0, max_spend: str = '0',
                 tokens_per_call: int = 2048, cost_per_token: str = '0'):
        if not model or not isinstance(model, str) or not isinstance(endpoint, str) or not endpoint.startswith(('https://', 'http://127.0.0.1:', 'http://localhost:', 'http://[::1]:')):
            raise ValidationError('Explicit model and HTTPS or loopback HTTP endpoint required')
        # Validate before retaining the endpoint or creating any budget files:
        # campaign provenance persists this value even when networking is disabled.
        try:
            parts = urlsplit(endpoint)
            invalid = (not parts.hostname or parts.username is not None or
                       parts.password is not None or '?' in endpoint or '#' in endpoint or
                       any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint) or
                       parts.port == 0)
        except ValueError:
            invalid = True
        if invalid:
            raise ValidationError('Provider endpoint must be valid and cannot contain credentials, query or fragment')
        self.model, self.endpoint, self.transport = model, endpoint, transport
        self.network_opt_in = network_opt_in is True
        self.timeout = _integer(timeout_seconds, 1, 120, 'timeout')
        self.max_calls = _integer(max_calls, 0, 100, 'max_calls')
        self.max_tokens = _integer(max_tokens, 0, 1000000, 'max_tokens')
        self.tokens_per_call = _integer(tokens_per_call, 1, 32768, 'tokens_per_call')
        self.max_spend, self.cost_per_token = _number(max_spend), _number(cost_per_token)
        if self.max_spend < 0 or self.cost_per_token < 0:
            raise ValidationError('Negative spend budget')
        self.path = Path(budget_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.receipts = []
        if not callable(transport):
            raise ValidationError('Injected transport callable required')

    def generate(self, context: dict) -> dict:
        if not self.network_opt_in:
            raise ValidationError('Provider network access is disabled')
        request = {'model': self.model, 'messages': [
            {'role': 'system', 'content': PROMPT},
            {'role': 'user', 'content': canonical_json(context)}],
            'max_tokens': self.tokens_per_call, 'response_format': {'type': 'json_object'}}
        # Reserve input bytes as a conservative token upper bound plus output cap.
        tokens = len(canonical_json(request).encode('utf-8')) + self.tokens_per_call
        spend = Decimal(tokens) * self.cost_per_token
        binding = content_hash({'model': self.model, 'endpoint': self.endpoint,
            'calls': self.max_calls, 'tokens': self.max_tokens, 'spend': str(self.max_spend),
            'rate': str(self.cost_per_token), 'per_call': self.tokens_per_call, 'timeout': self.timeout})
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS budget (binding TEXT, calls INTEGER, tokens INTEGER, spend TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS calls (sequence INTEGER PRIMARY KEY, request_hash TEXT, status TEXT, response_hash TEXT, reserved_tokens INTEGER, reserved_spend TEXT)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM budget').fetchone()
            if row is None:
                row = (binding, 0, 0, '0')
                db.execute('INSERT INTO budget VALUES (?,?,?,?)', row)
            if row[0] != binding:
                raise ValidationError('Provider budget configuration is immutable')
            if row[1] + 1 > self.max_calls or row[2] + tokens > self.max_tokens or Decimal(row[3]) + spend > self.max_spend:
                raise ValidationError('Provider budget exhausted')
            sequence = row[1] + 1
            db.execute('UPDATE budget SET calls=?,tokens=?,spend=?', (sequence, row[2] + tokens, str(Decimal(row[3]) + spend)))
            db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)', (sequence, content_hash(request), 'reserved', None, tokens, str(spend)))
        try:
            response = self.transport(self.endpoint, request, self.timeout)
        except BaseException:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE calls SET status=? WHERE sequence=?', ('failed_or_interrupted', sequence))
            raise
        if not isinstance(response, dict):
            raise ValidationError('Malformed provider response')
        response_hash = content_hash(response)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE calls SET status=?, response_hash=? WHERE sequence=?', ('transport_returned_not_verified', response_hash, sequence))
        self.receipts.append({'response_hash': response_hash, 'reserved_tokens': tokens,
                              'reserved_spend': str(spend), 'status': 'transport_returned_not_verified'})
        try:
            content = response['choices'][0]['message']['content']
            if not isinstance(content, str) or len(content.encode('utf-8')) > 16384:
                raise ValidationError('Provider output byte budget exceeded')
            return json.loads(content, object_pairs_hook=_unique_keys, parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('Nonfinite JSON')))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError('Malformed compatible provider response') from exc

    def improve(self, context: dict) -> dict:
        return self.generate(context)


class ResourceTimeout(ValidationError):
    """Worker was terminated at the campaign's hard wall-clock deadline."""


def _isolated_worker(connection, function, args, memory_mb, max_bytes):
    """Only trusted local functions run here; untrusted strategies remain JSON DSL."""
    memory_enforced = False
    try:
        try:
            import resource
            if hasattr(resource, 'RLIMIT_AS'):
                cap = memory_mb * 1024 * 1024
                old_soft, old_hard = resource.getrlimit(resource.RLIMIT_AS)
                if old_hard != resource.RLIM_INFINITY:
                    cap = min(cap, old_hard)
                resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
                memory_enforced = True
        except (ImportError, OSError, ValueError):
            pass
        value = function(*args)
        message = {'status': 'ok', 'value': value, 'memory_limit_enforced': memory_enforced}
        encoded = canonical_json(message).encode('utf-8')
        if len(encoded) > max_bytes:
            raise ValidationError('Worker IPC byte budget exceeded')
    except BaseException as exc:
        # An error class is useful provenance without exposing provider secrets.
        encoded = canonical_json({'status': 'error', 'error': type(exc).__name__,
                                  'memory_limit_enforced': memory_enforced}).encode('utf-8')
    try:
        connection.send_bytes(encoded)
    finally:
        connection.close()


def _run_bounded(function, args, *, deadline, config):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ResourceTimeout('Campaign runtime budget exhausted')
    method = config.get('process_start_method', 'spawn')
    context = multiprocessing.get_context(method)
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_isolated_worker, args=(sender, function, args,
        config.get('worker_memory_mb', 512), config.get('max_ipc_bytes', 4194304)))
    try:
        process.start()
        sender.close()
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not receiver.poll(remaining):
            raise ResourceTimeout('Isolated worker exceeded campaign deadline')
        try:
            encoded = receiver.recv_bytes(config.get('max_ipc_bytes', 4194304))
        except (EOFError, OSError):
            raise ValidationError('Isolated worker exited or exceeded IPC budget') from None
        message = json.loads(encoded)
        if message['status'] != 'ok':
            if message.get('error') == 'ValidationError':
                raise ValidationError('Worker rejected input')
            raise RuntimeError('Worker failed: ' + str(message.get('error', 'unknown')))
        return message
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            process.join(timeout=max(0, min(0.05, deadline - time.monotonic())))
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.2)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.2)
            process.close()


def _generate_candidate(generator, context, iteration):
    payload = (generator.generate if iteration == 0 else generator.improve)(context)
    _bounded_json(payload)
    return {'payload': payload, 'receipts': copy.deepcopy(getattr(generator, 'receipts', []))}


def _evaluate_split(dataset, spec, backtest_config):
    return _summary(run_backtest(dataset, spec, backtest_config))


def demo_campaign_config(dataset: Dataset, backtest_config: BacktestConfig) -> dict:
    """Demonstration thresholds, not investment acceptance criteria."""
    n = len(dataset.bars)
    if n < 16:
        raise ValidationError('Demo needs at least 16 bars')
    cuts = [0, n // 2, n * 7 // 10, n * 85 // 100, n]
    return {'splits': {name: cuts[i:i + 2] for i, name in enumerate(('train', 'validation', 'oos', 'holdout'))},
            'backtest_config': backtest_config, 'families': list(FAMILIES),
            'max_trials': 15, 'max_improvements': 2, 'seed': 0,
            'max_runtime_seconds': 300, 'max_bars': 100000, 'purge_bars': 0,
            'ranking': {'metric': 'net_pnl', 'minimum': '0', 'min_trades': 0}}


def _campaign_config(dataset, config):
    if dataset.manifest.get('data_hash') != content_hash(dataset.bars):
        raise ValidationError('Source data hash missing or mismatched')
    if dataset.quality.get('valid') is not True or dataset.manifest.get('validation_status') != 'valid':
        raise ValidationError('Source data is not validated')
    _keys(config, ('splits', 'backtest_config', 'families', 'max_trials',
                  'max_improvements', 'seed', 'max_runtime_seconds', 'max_bars', 'purge_bars', 'ranking'),
          ('process_start_method', 'worker_memory_mb', 'max_ipc_bytes'))
    if not isinstance(config['backtest_config'], BacktestConfig):
        raise ValidationError('Explicit BacktestConfig with costs is required')
    for name, low, high in (('max_trials', 1, 15), ('max_improvements', 0, 2),
                            ('seed', 0, 2147483647), ('max_runtime_seconds', 1, 7200),
                            ('max_bars', 1, 100000), ('purge_bars', 0, 1000)):
        _integer(config[name], low, high, name)
    if config.get('process_start_method', 'spawn') not in multiprocessing.get_all_start_methods():
        raise ValidationError('Unsupported process start method')
    _integer(config.get('worker_memory_mb', 512), 128, 4096, 'worker_memory_mb')
    _integer(config.get('max_ipc_bytes', 4194304), 16384, 16777216, 'max_ipc_bytes')
    if len(dataset.bars) > config['max_bars']:
        raise ValidationError('Campaign bar resource budget exceeded')
    families = config['families']
    if type(families) is not list or not families or any(type(f) is not str or f not in FAMILIES for f in families) or len(set(families)) != len(families):
        raise ValidationError('Invalid campaign families')
    _keys(config['ranking'], ('metric', 'minimum', 'min_trades'))
    if config['ranking']['metric'] != 'net_pnl':
        raise ValidationError('Only predeclared net_pnl ranking is supported')
    _number(config['ranking']['minimum'])
    _integer(config['ranking']['min_trades'], 0, 1000000, 'min_trades')
    _keys(config['splits'], ('train', 'validation', 'oos', 'holdout'))
    previous = 0
    splits = {}
    for name in ('train', 'validation', 'oos', 'holdout'):
        bounds = config['splits'][name]
        if type(bounds) is not list or len(bounds) != 2:
            raise ValidationError('Split needs [start, end] indexes')
        start, end = bounds
        _integer(start, 0, len(dataset.bars), 'split start')
        _integer(end, 0, len(dataset.bars), 'split end')
        if start < previous or end <= start + config['purge_bars']:
            raise ValidationError('Overlapping, unordered or empty purged split')
        previous = end
        bars = dataset.bars[start:end - config['purge_bars']] if config['purge_bars'] else dataset.bars[start:end]
        if any(a.end > b.timestamp for a, b in zip(bars, bars[1:])):
            raise ValidationError('Overlapping event intervals in split')
        manifest = dict(dataset.manifest)
        manifest['parent_data_hash'] = dataset.manifest['data_hash']
        manifest['data_hash'] = content_hash(bars)
        manifest['research_split'] = {'name': name, 'start': start, 'end': end,
                                      'purge_bars': config['purge_bars'], 'warmup': 'independent_no_prior_access'}
        splits[name] = Dataset(tuple(bars), manifest, dict(dataset.quality))
    for left, right in zip(('train', 'validation', 'oos'), ('validation', 'oos', 'holdout')):
        if splits[left].bars[-1].end > splits[right].bars[0].timestamp:
            raise ValidationError('Nonchronological split timestamps')
    return splits


def _summary(result):
    return {'metrics': to_dict(result.metrics), 'warnings': list(result.warnings),
            'result_hash': content_hash(result), 'manifest': to_dict(result.manifest)}


def _eligible(summary, ranking):
    metrics = summary['metrics']
    value = metrics.get('net_pnl')
    trades = metrics.get('trade_count', metrics.get('closed_trades', 0))
    return value is not None and _number(value) >= _number(ranking['minimum']) and trades >= ranking['min_trades']


def _dataset_identity(dataset):
    value = to_dict(dataset)
    value['manifest'].pop('imported_at', None)
    return content_hash(value)


def _reserve_holdout(dataset, *, registry_path, campaign_id, selection_hash, output_dir):
    """Atomically consume a shared workspace holdout, including overlapping dates.

    Coverage envelopes are conservative per contract: gaps inside a prior holdout
    interval remain treated as seen. Training prefixes and directory names do not
    influence identity. This protects ordinary workspace reuse, not deletion or
    copying of the entire authoritative registry by its owner.
    """
    coverage = {}
    for bar in dataset.bars:
        start = bar.timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = bar.end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        if bar.contract_id in coverage:
            previous = coverage[bar.contract_id]
            coverage[bar.contract_id] = (min(previous[0], start), max(previous[1], end))
        else:
            coverage[bar.contract_id] = (start, end)
    holdout_hash = content_hash(dataset.bars)
    reservation_id = content_hash({'bars_hash': holdout_hash, 'coverage': coverage})
    registry_path = Path(registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(registry_path, timeout=10)) as registry, registry:
        registry.execute('CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, holdout_hash TEXT NOT NULL, campaign_id TEXT NOT NULL, selection_hash TEXT NOT NULL, source_directory TEXT NOT NULL)')
        registry.execute('CREATE TABLE IF NOT EXISTS coverage (reservation_id TEXT NOT NULL, contract_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY(reservation_id,contract_id))')
        registry.execute('BEGIN IMMEDIATE')
        conflicts = set()
        for contract, (start, end) in coverage.items():
            rows = registry.execute('SELECT DISTINCT reservation_id FROM coverage WHERE contract_id=? AND start < ? AND end > ?', (contract, end, start)).fetchall()
            conflicts.update(row[0] for row in rows)
        if conflicts:
            return {'status': 'previously_consumed', 'holdout_hash': holdout_hash,
                    'reservation_id': reservation_id, 'conflicts': sorted(conflicts),
                    'registry_path': str(registry_path.resolve())}
        registry.execute('INSERT INTO reservations VALUES (?,?,?,?,?)',
            (reservation_id, holdout_hash, campaign_id, selection_hash, str(Path(output_dir).resolve())))
        registry.executemany('INSERT INTO coverage VALUES (?,?,?,?)',
            [(reservation_id, contract, start, end) for contract, (start, end) in coverage.items()])
        # Context manager commits before returning the consumed marker to caller.
    return {'status': 'reserved_consumed', 'holdout_hash': holdout_hash,
            'reservation_id': reservation_id, 'conflicts': [],
            'registry_path': str(registry_path.resolve())}


def run_campaign(dataset: Dataset, *, config: dict, generator: Generator, output_dir: Path,
                 holdout_registry_path: Path | None = None) -> dict:
    """Durable reservations prevent duplicate trials on reruns or crashes.

    A separate SQLite lock serializes callers and is released by the OS on crash.
    Interrupted reservations consume budget and block implicit retries.
    """
    started = time.monotonic()
    dataset, config = copy.deepcopy(dataset), copy.deepcopy(config)
    splits = _campaign_config(dataset, config)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    registry_path = Path(holdout_registry_path) if holdout_registry_path is not None else output_dir.parent / '.holdout_registry.sqlite3'
    mode = getattr(generator, 'mode', 'custom_unverified')
    provider = {'mode': mode, 'model': getattr(generator, 'model', None),
                'endpoint': getattr(generator, 'endpoint', None)}
    if isinstance(generator, CompatibleProvider):
        provider['limits'] = {'calls': generator.max_calls, 'tokens': generator.max_tokens,
            'spend': str(generator.max_spend), 'rate': str(generator.cost_per_token),
            'tokens_per_call': generator.tokens_per_call, 'timeout': generator.timeout}
        provider['network_opt_in'] = generator.network_opt_in
        provider['transport_type'] = type(generator.transport).__module__ + '.' + type(generator.transport).__qualname__
    binding = {'config': to_dict(config), 'data_hash': _dataset_identity(dataset),
               'split_hashes': {k: _dataset_identity(v) for k, v in splits.items()},
               'provider': provider, 'prompt_template_hash': content_hash(PROMPT),
               'engine_source_hashes': {name: content_hash(Path(__file__).with_name(name).read_text(encoding='utf-8'))
                   for name in ('research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py')}}
    campaign_id = content_hash(binding)
    lock = sqlite3.connect(output_dir / 'campaign.lock.sqlite3', timeout=1)
    try:
        lock.execute('BEGIN EXCLUSIVE')
    except BaseException as exc:
        lock.close()
        if isinstance(exc, sqlite3.OperationalError):
            raise ValidationError('Campaign is already running') from exc
        raise
    try:
        db = sqlite3.connect(output_dir / 'campaign.sqlite3')
    except BaseException:
        try:
            lock.rollback()
        finally:
            lock.close()
        raise
    def save(state):
        encoded = canonical_json(state)
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (encoded,))
        db.commit()
        temporary = output_dir / 'campaign.json.tmp'
        temporary.write_text(encoded, encoding='utf-8')
        temporary.replace(output_dir / 'campaign.json')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        if row:
            state = json.loads(row[0])
            if state['campaign_id'] != campaign_id:
                raise ValidationError('Campaign config/data/provider is immutable; output directory conflict')
            if state['status'] != 'running':
                return state
            unfinished = [a for a in state['attempts'] if a['status'] == 'running']
            if unfinished:
                for attempt in unfinished:
                    attempt['status'] = 'interrupted'
                    attempt['warnings'].append('Interrupted attempt consumed budget; no implicit retry')
                state['status'] = 'blocked_interrupted'
                save(state)
                return state
            if state['holdout_consumed']:
                state['status'] = 'blocked_consumed_holdout'
                save(state)
                return state
        else:
            state = {'campaign_id': campaign_id, 'binding': binding, 'status': 'running',
                     'source_manifest': to_dict(dataset.manifest),
                     'attempts': [], 'selected': [], 'evaluations': {'oos': [], 'holdout': []},
                     'holdout_consumed': False, 'holdout_status': 'not_accessed', 'elapsed_seconds': 0,
                     'real_model_status': 'not_verified', 'provider_receipts': [],
                     'resource_enforcement': {'trials': 'persisted', 'bars': 'bounded',
                         'runtime': 'hard_subprocess_deadline', 'process_start_method': config.get('process_start_method', 'spawn'),
                         'process_memory_isolation': 'pending_worker_capability',
                         'worker_memory_mb': config.get('worker_memory_mb', 512),
                         'max_ipc_bytes': config.get('max_ipc_bytes', 4194304),
                         'provider_timeout': 'hard_campaign_deadline_plus_transport_timeout'},
                     'warnings': ['Fixture/custom transport results are not real-model verification.',
                         'Independent split warmup and flat starts; no cross-boundary positions or feature state.',
                         'No multiple-testing correction or investment acceptance claim; all attempts disclosed.',
                         'Holdout consumption is shared across sibling campaign directories; overlapping time ranges are conservatively already seen. Copying/deleting the authoritative workspace registry cannot establish unseen data.',
                         'Worker address-space cap applies where RLIMIT_AS is available; this is not a filesystem/network sandbox.']}
            save(state)
        prior_elapsed = state['elapsed_seconds']
        deadline = started + max(0, config['max_runtime_seconds'] - prior_elapsed)
        plan = [(family, iteration) for iteration in range(config['max_improvements'] + 1) for family in config['families']]
        for family, iteration in plan:
            if any(a['family'] == family and a['iteration'] == iteration for a in state['attempts']):
                continue
            elapsed = prior_elapsed + time.monotonic() - started
            if len(state['attempts']) >= config['max_trials'] or elapsed >= config['max_runtime_seconds']:
                break
            previous = [a for a in state['attempts'] if a['family'] == family]
            parent = previous[-1] if previous else None
            sequence = len(state['attempts']) + 1
            attempt = {'attempt_id': content_hash([campaign_id, sequence]), 'sequence': sequence,
                       'parent_id': parent['attempt_id'] if parent else None,
                       'family': family, 'iteration': iteration, 'status': 'running',
                       'provider': provider, 'prompt_template_hash': binding['prompt_template_hash'],
                       'split_hashes': {k: binding['split_hashes'][k] for k in ('train', 'validation')},
                       'output': None, 'output_hash': None, 'strategy_hash': None,
                       'metrics': {}, 'cost': '0' if mode == 'fixture' else None,
                       'elapsed_seconds': None, 'warnings': []}
            state['attempts'].append(attempt)
            save(state)
            trial_start = time.monotonic()
            try:
                context = {'family': family, 'iteration': iteration, 'seed': config['seed'],
                           'training': {'bar_count': len(splits['train'].bars), 'hash': content_hash(splits['train'].bars)},
                           'validation': {'bar_count': len(splits['validation'].bars), 'hash': content_hash(splits['validation'].bars)},
                           'previous': copy.deepcopy({'output': parent['output'], 'metrics': {k: v['metrics'] for k, v in parent['metrics'].items()}, 'status': parent['status']}) if parent else None}
                attempt['generator_context'] = copy.deepcopy(context)
                generated = _run_bounded(_generate_candidate, (generator, context, iteration), deadline=deadline, config=config)
                state['resource_enforcement']['process_memory_isolation'] = 'enforced_rlimit_as' if generated['memory_limit_enforced'] else 'unsupported_platform'
                payload = generated['value']['payload']
                state['provider_receipts'].extend(generated['value']['receipts'])
                _bounded_json(payload)
                attempt['output'] = copy.deepcopy(payload)
                attempt['output_hash'] = content_hash(payload)
                spec = validate_dsl(payload)
                if spec.family != family:
                    raise ValidationError('Provider changed requested family')
                attempt['strategy_hash'] = content_hash(spec)
                attempt['spec'] = to_dict(spec)
                for split in ('train', 'validation'):
                    if prior_elapsed + time.monotonic() - started >= config['max_runtime_seconds']:
                        raise ValidationError('Campaign runtime budget exhausted')
                    evaluated = _run_bounded(_evaluate_split, (splits[split], spec, config['backtest_config']), deadline=deadline, config=config)
                    attempt['metrics'][split] = evaluated['value']
                attempt['status'] = 'evaluated'
            except Exception as exc:
                attempt['status'] = 'timed_out' if isinstance(exc, ResourceTimeout) else ('rejected' if isinstance(exc, ValidationError) else 'failed')
                attempt['warnings'].append(type(exc).__name__)
            finally:
                attempt['elapsed_seconds'] = time.monotonic() - trial_start
                state['elapsed_seconds'] = prior_elapsed + time.monotonic() - started
                save(state)
        # Freeze by validation only BEFORE OOS/holdout evaluation.
        selected = []
        for family in config['families']:
            eligible = [a for a in state['attempts'] if a['family'] == family and a['status'] == 'evaluated'
                        and _eligible(a['metrics']['validation'], config['ranking'])]
            if eligible:
                winner = sorted(eligible, key=lambda a: (-_number(a['metrics']['validation']['metrics']['net_pnl']), a['sequence']))[0]
                selected.append({'attempt_id': winner['attempt_id'], 'strategy_hash': winner['strategy_hash'],
                                 'spec': winner['spec'], 'validation': winner['metrics']['validation']})
        state['selected'] = selected
        state['selection_hash'] = content_hash(selected)
        save(state)
        if prior_elapsed + time.monotonic() - started >= config['max_runtime_seconds']:
            state['status'] = 'budget_exhausted'
            save(state)
            return state
        if selected:
            reservation = _reserve_holdout(splits['holdout'], registry_path=registry_path,
                campaign_id=campaign_id, selection_hash=state['selection_hash'], output_dir=output_dir)
            state['holdout_registry'] = reservation
            state['holdout_status'] = reservation['status']
            if reservation['status'] == 'previously_consumed':
                state['holdout_consumed'] = True
                state['status'] = 'blocked_previously_consumed_holdout'
                state['warnings'].append('This holdout overlaps data already consumed by a workspace campaign; no new OOS/holdout evaluation was performed.')
                save(state)
                return state
            state['holdout_consumed'] = True
            state['holdout_selection_hash'] = state['selection_hash']
            save(state)
            for split in ('oos', 'holdout'):
                for candidate in selected:
                    record = {'strategy_hash': candidate['strategy_hash'], 'status': 'running'}
                    state['evaluations'][split].append(record)
                    save(state)
                    try:
                        if prior_elapsed + time.monotonic() - started >= config['max_runtime_seconds']:
                            raise ValidationError('Campaign runtime budget exhausted')
                        evaluated = _run_bounded(_evaluate_split, (splits[split], validate_dsl(candidate['spec']), config['backtest_config']), deadline=deadline, config=config)
                        record.update(evaluated['value'])
                        record['status'] = 'evaluated'
                    except Exception as exc:
                        record.update(status='failed', error=type(exc).__name__)
                    save(state)
        state['status'] = 'completed' if all(r['status'] == 'evaluated' for rows in state['evaluations'].values() for r in rows) else 'completed_with_errors'
        state['elapsed_seconds'] = prior_elapsed + time.monotonic() - started
        save(state)
        return state
    finally:
        try:
            db.close()
        finally:
            try:
                lock.rollback()
            finally:
                lock.close()
