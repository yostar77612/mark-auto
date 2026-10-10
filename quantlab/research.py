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
PROMPT = '''quantlab-v2: Propose one strategy for the requested family using only the supplied training summary and prior train/validation results. Return one JSON object, without prose or code.
Required keys: strategy_id (1..64 ASCII letters, digits, underscore or hyphen), family (exactly the requested family), parameters (object), rules (object). Optional schema_version must be 1.
Choose parameter values yourself. The current context's parameter_contract lists the exact parameter keys to emit; family names are never parameter keys. Required parameters by family:
trend: fast and slow integers, 1 <= fast < slow <= 1000.
mean_reversion: lookback integer 2..1000, entry_bps positive decimal string <= 10000.
channel_breakout: lookback integer 2..1000.
momentum: lookback integer 2..1000, threshold_bps positive decimal string <= 10000, max_holding_bars integer 1..1000.
volatility_compression: lookback integer 2..1000, max_range_bps positive decimal string <= 10000.
Use only the required family parameters; do not alter quantity, stops, costs, margin or risk controls. Prefer lookbacks comfortably shorter than the training bar count.
Use rules={} to use the built-in causal family signal logic. Alternatively rules must contain long and short boolean AST nodes, optionally exit. Numeric AST nodes: {"op":"const","value":decimal_string_or_integer}; {"op":"field","name":OHLCV_field,"lag":nonnegative_integer}; or {"op":indicator,"field":OHLCV_field,"period":integer_1_to_500,"lag":nonnegative_integer}. OHLCV_field is open, high, low, close or volume; indicator is sma, highest, lowest or return_bps; lag is optional and at most 500. Boolean nodes: {"op":comparison,"left":numeric_node,"right":numeric_node} with comparison gt/gte/lt/lte/eq; {"op":"and" or "or","args":[boolean_nodes]} with 2..8 arguments; {"op":"not","arg":boolean_node}. Maximum AST depth 12 and 128 nodes. No other operators, expressions, executable code, or extra keys.
Training summaries are descriptive, not proof of profitability. Risk controls are immutable.'''
PARAMETER_CONTRACTS = {
    'trend': {'fast': 'integer 1..999, strictly below slow', 'slow': 'integer 2..1000, strictly above fast'},
    'mean_reversion': {'lookback': 'integer 2..1000', 'entry_bps': 'decimal string greater than 0 and at most 10000'},
    'channel_breakout': {'lookback': 'integer 2..1000'},
    'momentum': {'lookback': 'integer 2..1000', 'threshold_bps': 'decimal string greater than 0 and at most 10000', 'max_holding_bars': 'integer 1..1000'},
    'volatility_compression': {'lookback': 'integer 2..1000', 'max_range_bps': 'decimal string greater than 0 and at most 10000'},
}


def registry_json_schema(family):
    """Constrain registry-family parameter generation, not arbitrary AST creation.

    All values remain model choices. Integer basis points are a supported subset
    of the decimal DSL. Cross-field semantics still require validate_dsl.
    """
    if family not in PARAMETER_CONTRACTS:
        raise ValidationError('Unknown schema family')
    properties = {}
    for name in PARAMETER_CONTRACTS[family]:
        minimum = 1 if name in ('fast', 'max_holding_bars', 'entry_bps', 'threshold_bps', 'max_range_bps') else 2
        maximum = 10000 if name.endswith('_bps') else (999 if name == 'fast' else 1000)
        properties[name] = {'type': 'integer', 'minimum': minimum, 'maximum': maximum}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['strategy_id', 'family', 'parameters', 'rules', 'schema_version'],
            'properties': {
                'strategy_id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,64}$'},
                'family': {'type': 'string', 'const': family},
                'parameters': {'type': 'object', 'additionalProperties': False,
                               'required': list(properties), 'properties': properties},
                'rules': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                'schema_version': {'type': 'integer', 'const': 1}}}


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


def candidate_fingerprint(spec: StrategySpec) -> str:
    """Canonical behavioral structure, excluding cosmetic strategy IDs.

    Normalize numeric spellings and explicit default quantity/lag. This detects
    repeated structures, not every logically equivalent Boolean expression.
    Decimal tuples avoid ambient rounding and giant exponent expansion.
    """
    validate_strategy(spec)
    def number(value):
        parsed = _number(value)
        if not parsed:
            return [0, '0', 0]
        sign, digits, exponent = parsed.as_tuple()
        digits = list(digits)
        while digits[-1] == 0:
            digits.pop()
            exponent += 1
        return [sign, ''.join(str(d) for d in digits), exponent]
    def rule(node):
        result = {}
        for key, value in node.items():
            if key == 'value' and node['op'] == 'const':
                result[key] = number(value)
            elif isinstance(value, dict):
                result[key] = rule(value)
            elif isinstance(value, (list, tuple)):
                result[key] = [rule(item) for item in value]
            else:
                result[key] = value
        if node['op'] in ('field', 'sma', 'highest', 'lowest', 'return_bps'):
            result.setdefault('lag', 0)
        return result
    parameters = dict(spec.parameters)
    parameters.setdefault('quantity', 1)
    return content_hash({'family': spec.family,
                         'parameters': {key: number(value) for key, value in parameters.items()},
                         'rules': {key: rule(value) for key, value in spec.rules.items()}})


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
                 tokens_per_call: int = 2048, cost_per_token: str = '0',
                 output_mode: str = 'json_object'):
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
        if output_mode not in ('json_object', 'registry_json_schema'):
            raise ValidationError('Unsupported provider output mode')
        self.output_mode = output_mode
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
        request_context = copy.deepcopy(context)
        response_format = {'type': 'json_object'}
        if self.output_mode == 'registry_json_schema':
            response_format = {'type': 'json_schema', 'json_schema': {
                'name': 'quantlab_registry_candidate', 'strict': True,
                'schema': registry_json_schema(context.get('family'))}}
            request_context['output_contract'] = (
                'registry_json_schema mode: choose your own integer parameter values, including basis points. '
                'Return rules={} to use the requested built-in family. Do not generate an AST. '
                'Choose lookbacks much shorter than training bar count; trend fast must be below slow.')
        request = {'model': self.model, 'messages': [
            {'role': 'system', 'content': PROMPT},
            {'role': 'user', 'content': canonical_json(request_context) + (
                '\nBefore returning JSON, compare your chosen parameters with previous.output.parameters. '
                'At least one parameter value must differ. A new strategy_id alone is invalid. '
                'Choose the changed value yourself within the same schema; do not alter risk controls.'
                if request_context.get('task') == 'improve_previous_candidate' else '')}],
            'max_tokens': self.tokens_per_call, 'response_format': response_format}
        # Reserve input bytes as a conservative token upper bound plus output cap.
        tokens = len(canonical_json(request).encode('utf-8')) + self.tokens_per_call
        spend = Decimal(tokens) * self.cost_per_token
        budget_identity = {'model': self.model, 'endpoint': self.endpoint,
            'calls': self.max_calls, 'tokens': self.max_tokens, 'spend': str(self.max_spend),
            'rate': str(self.cost_per_token), 'per_call': self.tokens_per_call, 'timeout': self.timeout}
        # Preserve the pre-option identity for default JSON-object budgets.
        if self.output_mode != 'json_object':
            budget_identity['output_mode'] = self.output_mode
        binding = content_hash(budget_identity)
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
        context = copy.deepcopy(context)
        context['task'] = 'improve_previous_candidate'
        context['improvement_instruction'] = (
            'Use previous training and validation feedback to propose a distinct candidate in the same family. '
            'Change parameters or rules, not just strategy_id. Keep risk controls unchanged. '
            'Do not claim performance improved before the new candidate is evaluated.')
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


def training_summary(dataset):
    """Small deterministic description of this training split only, never bars.

    This is descriptive context, not an optimizer or a candidate recommendation.
    Caller supplies the already partitioned training dataset.
    """
    bars = dataset.bars
    if not bars:
        raise ValidationError('Training summary requires bars')
    return {'bar_count': len(bars), 'hash': content_hash(bars),
            'first_close': str(bars[0].close), 'last_close': str(bars[-1].close),
            'high': str(max(b.high for b in bars)), 'low': str(min(b.low for b in bars)),
            'total_volume': sum(b.volume for b in bars)}


def _eligible(summary, ranking):
    metrics = summary['metrics']
    value = metrics.get('net_pnl')
    trades = metrics.get('trade_count', metrics.get('closed_trades', 0))
    return value is not None and _number(value) >= _number(ranking['minimum']) and trades >= ranking['min_trades']


def _dataset_identity(dataset):
    value = to_dict(dataset)
    value['manifest'].pop('imported_at', None)
    return content_hash(value)


def _reserve_holdout(dataset, *, registry_path, campaign_id, selection_hash, output_dir,
                     guard_dataset: Dataset | None = None, deadline: float | None = None):
    """Atomically consume a shared workspace holdout, including overlapping dates.

    Coverage envelopes are conservative per contract: gaps inside a prior holdout
    interval remain treated as seen. Training prefixes and directory names do not
    influence identity. This protects ordinary workspace reuse, not deletion or
    copying of the entire authoritative registry by its owner.
    """
    def envelope(source):
        coverage = {}
        for bar in source.bars:
            start = bar.timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            end = bar.end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            if bar.contract_id in coverage:
                previous = coverage[bar.contract_id]
                coverage[bar.contract_id] = (min(previous[0], start), max(previous[1], end))
            else:
                coverage[bar.contract_id] = (start, end)
        return coverage
    coverage = envelope(dataset)
    # Optional admission guard is checked in the SAME transaction as reservation.
    # Existing callers still check/reserve exactly their original holdout envelope.
    checked_coverage = envelope(guard_dataset) if guard_dataset is not None else coverage
    for contract, (start, end) in coverage.items():
        if contract in checked_coverage:
            old = checked_coverage[contract]
            checked_coverage[contract] = (min(old[0], start), max(old[1], end))
        else:
            checked_coverage[contract] = (start, end)
    holdout_hash = content_hash(dataset.bars)
    reservation_id = content_hash({'bars_hash': holdout_hash, 'coverage': coverage})
    registry_path = Path(registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = 10 if deadline is None else max(0, min(10, deadline - time.monotonic()))
    if deadline is not None and timeout <= 0:
        raise ResourceTimeout('Range reservation exceeded experiment deadline')
    with closing(sqlite3.connect(registry_path, timeout=timeout)) as registry, registry:
        registry.execute('CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, holdout_hash TEXT NOT NULL, campaign_id TEXT NOT NULL, selection_hash TEXT NOT NULL, source_directory TEXT NOT NULL)')
        registry.execute('CREATE TABLE IF NOT EXISTS coverage (reservation_id TEXT NOT NULL, contract_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY(reservation_id,contract_id))')
        registry.execute('BEGIN IMMEDIATE')
        if deadline is not None and time.monotonic() >= deadline:
            raise ResourceTimeout('Range reservation exceeded experiment deadline')
        conflicts = set()
        for contract, (start, end) in checked_coverage.items():
            rows = registry.execute('SELECT DISTINCT reservation_id FROM coverage WHERE contract_id=? AND start < ? AND end > ?', (contract, end, start)).fetchall()
            conflicts.update(row[0] for row in rows)
        if conflicts:
            return {'status': 'previously_consumed', 'holdout_hash': holdout_hash,
                    'reservation_id': reservation_id, 'conflicts': sorted(conflicts),
                    'registry_path': str(registry_path.resolve())}
        if deadline is not None and time.monotonic() >= deadline:
            raise ResourceTimeout('Range reservation exceeded experiment deadline')
        registry.execute('INSERT INTO reservations VALUES (?,?,?,?,?)',
            (reservation_id, holdout_hash, campaign_id, selection_hash, str(Path(output_dir).resolve())))
        registry.executemany('INSERT INTO coverage VALUES (?,?,?,?)',
            [(reservation_id, contract, start, end) for contract, (start, end) in coverage.items()])
        # Context manager commits before returning the consumed marker to caller.
    return {'status': 'reserved_consumed', 'holdout_hash': holdout_hash,
            'reservation_id': reservation_id, 'conflicts': [],
            'registry_path': str(registry_path.resolve())}


def _validated_provider_descriptor(value):
    """Bound opt-in provenance JSON; reviewed providers own semantic redaction.

    This validates structure, not arbitrary plugins' truthfulness or secrecy.
    No conversion hooks, paths, source imports or descriptor IO live here.
    """
    count = 0
    def visit(item, depth=0):
        nonlocal count
        count += 1
        if depth > 8 or count > 512:
            raise ValidationError('Provider descriptor structure exceeds bounds')
        if item is None or type(item) in (bool, int):
            if type(item) is int and abs(item) > 2**53:
                raise ValidationError('Provider descriptor integer exceeds bounds')
            return
        if type(item) is str:
            if len(item.encode('utf-8')) > 2048:
                raise ValidationError('Provider descriptor string exceeds bounds')
            return
        if type(item) is dict:
            if len(item) > 64:
                raise ValidationError('Provider descriptor object exceeds bounds')
            for key, child in item.items():
                if type(key) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', key):
                    raise ValidationError('Invalid provider descriptor key')
                visit(child, depth + 1)
            return
        if type(item) is list:
            if len(item) > 64:
                raise ValidationError('Provider descriptor list exceeds bounds')
            for child in item:
                visit(child, depth + 1)
            return
        raise ValidationError('Provider descriptor must contain strict JSON primitives')
    if type(value) is not dict or value.get('version') != 1 or type(value.get('version')) is not int:
        raise ValidationError('Unsupported provider descriptor version')
    visit(value)
    if len(canonical_json(value).encode('utf-8')) > 16384:
        raise ValidationError('Provider descriptor byte budget exceeded')
    return copy.deepcopy(value)


def _provider_identity(generator):
    mode = getattr(generator, 'mode', 'custom_unverified')
    provider = {'mode': mode, 'model': getattr(generator, 'model', None),
                'endpoint': getattr(generator, 'endpoint', None)}
    if isinstance(generator, CompatibleProvider):
        if generator.output_mode != 'json_object':
            provider['output_mode'] = generator.output_mode
        provider['limits'] = {'calls': generator.max_calls, 'tokens': generator.max_tokens,
            'spend': str(generator.max_spend), 'rate': str(generator.cost_per_token),
            'tokens_per_call': generator.tokens_per_call, 'timeout': generator.timeout}
        provider['network_opt_in'] = generator.network_opt_in
        provider['transport_type'] = type(generator.transport).__module__ + '.' + type(generator.transport).__qualname__
    # Absent capability adds no key: legacy provider sub-bindings are unchanged.
    descriptor = getattr(generator, 'provider_descriptor', None)
    if descriptor is not None:
        if not callable(descriptor):
            raise ValidationError('Provider descriptor capability must be callable')
        provider['descriptor'] = _validated_provider_descriptor(descriptor())
    return provider


def _validated_receipt_snapshot(snapshot, expected_descriptor):
    """Strict allowlisted audit envelope; no raw bodies/paths/credentials accepted."""
    if (type(snapshot) is not dict or set(snapshot) != {'version', 'provider_descriptor_hash', 'receipts'}
        or type(snapshot['version']) is not int or snapshot['version'] != 1
        or snapshot['provider_descriptor_hash'] != content_hash(expected_descriptor)):
        raise ValidationError('Provider receipt binding mismatch')
    receipts = snapshot['receipts']
    if type(receipts) is not list or len(receipts) > 100:
        raise ValidationError('Provider receipt snapshot exceeds bounds')
    fields = {'billing_route', 'paid_api_fallback', 'token_upper_bound_enforced',
              'spend_upper_bound_enforced', 'account_credit_policy', 'sequence',
              'request_hash', 'request_bytes', 'status', 'response_hash', 'token_usage',
              'received_bytes', 'elapsed_seconds'}
    statuses = {
        'completed', 'reserved_unknown', 'failed_or_interrupted', 'eligibility_blocked',
        'quota_paused', 'transient_blocked', 'invalid_request', 'configuration_blocked',
        'credential_diagnosis', 'grant_blocked', 'remote_error', 'cancelled',
        'deadline_exceeded', 'http_transport_failed', 'invalid_json', 'duplicate_json_key',
        'nonfinite_json', 'json_depth', 'json_object_required', 'stream_byte_limit',
        'event_count', 'event_byte_limit', 'done_without_completion', 'ambiguous_event_type',
        'duplicate_event_type', 'invalid_utf8', 'invalid_stream_chunk', 'truncated_event',
        'invalid_terminal_status', 'ambiguous_terminal', 'missing_output', 'invalid_output',
        'tools_or_unknown_output', 'incomplete_message', 'refusal_or_unknown_content',
        'ambiguous_candidate', 'candidate_byte_limit', 'candidate_family_mismatch',
        'invalid_credential', 'compressed_response', 'redirect_rejected', 'invalid_content_type',
        'request_byte_limit', 'ambiguous_terminal', 'invalid_event', 'invalid_response_id',
        'response_id_mismatch', 'response_incomplete', 'refusal_or_tool_event',
        'eof_without_completion'}
    for sequence, receipt in enumerate(receipts, 1):
        if type(receipt) is not dict or set(receipt) != fields:
            raise ValidationError('Invalid provider receipt fields')
        if (receipt['billing_route'] != 'chatgpt_plan' or receipt['account_credit_policy'] != 'unverified_user_setting'
            or any(receipt[key] is not False for key in ('paid_api_fallback', 'token_upper_bound_enforced', 'spend_upper_bound_enforced'))
            or type(receipt['sequence']) is not int or receipt['sequence'] != sequence
            or receipt['status'] not in statuses):
            raise ValidationError('Invalid provider receipt claims')
        for key in ('request_hash', 'response_hash'):
            value = receipt[key]
            if key == 'response_hash' and value is None:
                continue
            if type(value) is not str or not re.fullmatch('[a-f0-9]{64}', value):
                raise ValidationError('Invalid provider receipt digest')
        if type(receipt['request_bytes']) is not int or not 1 <= receipt['request_bytes'] <= 65536:
            raise ValidationError('Invalid provider receipt byte count')
        received = receipt['received_bytes']
        if received is not None and (type(received) is not int or not 0 <= received <= 1048576 + 8192):
            raise ValidationError('Invalid provider receipt byte count')
        elapsed = receipt['elapsed_seconds']
        if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 3600):
            raise ValidationError('Invalid provider receipt runtime')
        usage = receipt['token_usage']
        if usage != 'unknown':
            if (type(usage) is not dict or set(usage) != {'input_tokens', 'output_tokens', 'total_tokens'}
                or any(type(value) is not int or not 0 <= value <= 2**53 for value in usage.values())
                or usage['input_tokens'] + usage['output_tokens'] != usage['total_tokens']):
                raise ValidationError('Invalid observed token usage')
    return copy.deepcopy(receipts)


def _reconcile_provider_receipts(generator, provider, state, attempt, generation_finished):
    """Parent calls only after bounded worker has stopped/joined, before selection."""
    hook = getattr(generator, 'read_receipt_snapshot', None)
    if hook is None:
        return
    try:
        if not callable(hook) or 'descriptor' not in provider:
            raise ValidationError('Receipt snapshot requires an opt-in descriptor')
        receipts = _validated_receipt_snapshot(hook(), provider['descriptor'])
        if generation_finished and len(receipts) <= len(state.get('provider_receipts', [])):
            raise ValidationError('Completed generation lacks a new durable receipt')
        state['provider_receipts'] = receipts
        if not generation_finished or any(receipt['status'] != 'completed' for receipt in receipts):
            state['status'] = 'blocked_provider_outcome'
    except Exception:
        # Keep the last validated snapshot, never the malformed data or exception.
        state['status'] = 'blocked_provider_audit'
        attempt['warnings'].append('Provider receipt audit could not be reconciled')


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
    provider = _provider_identity(generator)
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
            generation_finished = False
            try:
                context = {'family': family, 'iteration': iteration, 'seed': config['seed'],
                           'parameter_contract': copy.deepcopy(PARAMETER_CONTRACTS[family]),
                           'training': training_summary(splits['train']),
                           'validation': {'bar_count': len(splits['validation'].bars), 'hash': content_hash(splits['validation'].bars)},
                           'previous': copy.deepcopy({'output': parent['output'], 'metrics': {k: v['metrics'] for k, v in parent['metrics'].items()}, 'status': parent['status']}) if parent else None}
                attempt['generator_context'] = copy.deepcopy(context)
                generated = _run_bounded(_generate_candidate, (generator, context, iteration), deadline=deadline, config=config)
                generation_finished = True
                state['resource_enforcement']['process_memory_isolation'] = 'enforced_rlimit_as' if generated['memory_limit_enforced'] else 'unsupported_platform'
                payload = generated['value']['payload']
                if getattr(generator, 'read_receipt_snapshot', None) is None:
                    state['provider_receipts'].extend(generated['value']['receipts'])
                _bounded_json(payload)
                attempt['output'] = copy.deepcopy(payload)
                attempt['output_hash'] = content_hash(payload)
                spec = validate_dsl(payload)
                if spec.family != family:
                    raise ValidationError('Provider changed requested family')
                attempt['strategy_hash'] = content_hash(spec)
                attempt['spec'] = to_dict(spec)
                attempt['candidate_fingerprint'] = candidate_fingerprint(spec)
                duplicate = next((prior for prior in state['attempts'][:-1]
                                  if prior.get('candidate_fingerprint') == attempt['candidate_fingerprint']), None)
                if duplicate is not None:
                    attempt['duplicate_of'] = duplicate['attempt_id']
                    attempt['warnings'].append('duplicate_candidate_not_retested')
                    raise ValidationError('Repeated candidate structure')
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
                _reconcile_provider_receipts(generator, provider, state, attempt, generation_finished)
                attempt['elapsed_seconds'] = time.monotonic() - trial_start
                state['elapsed_seconds'] = prior_elapsed + time.monotonic() - started
                save(state)
            if state['status'] in ('blocked_provider_outcome', 'blocked_provider_audit'):
                return state
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


def reconcile_interrupted_campaign(*, output_dir: Path, generator: Generator,
                                   descendants_stopped: bool = False) -> dict:
    """Reconcile an interrupted outer campaign after the host stops its subtree.

    No generation/evaluation or control reset is permitted here. SQLite remains
    authoritative; campaign.json is its replaceable projection. This function
    never creates a missing campaign or lock database. The caller must retain the
    exact original provider, not reconstruct different account/model/limit data.
    """
    if descendants_stopped is not True:
        raise ValidationError('Campaign descendants must be stopped before reconciliation')
    output_dir = Path(output_dir)
    db_path = output_dir / 'campaign.sqlite3'
    lock_path = output_dir / 'campaign.lock.sqlite3'
    if not db_path.is_file() or not lock_path.is_file():
        raise ValidationError('Existing campaign audit databases are required')
    lock = db = None
    try:
        lock = sqlite3.connect(lock_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0)
        lock.execute('BEGIN EXCLUSIVE')
        db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        if not row or type(row[0]) is not str or len(row[0].encode('utf-8')) > 16777216:
            raise ValidationError('Invalid campaign audit state')
        state = json.loads(row[0], object_pairs_hook=_unique_keys,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('Nonfinite campaign state')))
        if (type(state) is not dict or type(state.get('binding')) is not dict
            or state.get('campaign_id') != content_hash(state['binding'])
            or type(state.get('attempts')) is not list or len(state['attempts']) > 100
            or type(state.get('provider_receipts')) is not list
            or type(state.get('status')) is not str):
            raise ValidationError('Invalid campaign audit state')
        provider = _provider_identity(generator)
        if state['binding'].get('provider') != provider or 'descriptor' not in provider:
            raise ValidationError('Interrupted campaign provider identity mismatch')
        hook = getattr(generator, 'read_receipt_snapshot', None)
        if not callable(hook):
            raise ValidationError('Durable provider receipt snapshot is required')
        receipts = _validated_receipt_snapshot(hook(), provider['descriptor'])
        # Never reopen or rewrite a completed/previously blocked campaign.
        if state['status'] != 'running':
            return state
        for attempt in state['attempts']:
            if type(attempt) is not dict or type(attempt.get('warnings')) is not list:
                raise ValidationError('Invalid campaign attempt state')
            if attempt.get('status') == 'running':
                attempt['status'] = 'interrupted'
                attempt['warnings'].append('Interrupted outer worker consumed budget; no implicit retry')
        state['provider_receipts'] = receipts
        state['status'] = 'blocked_interrupted'
        encoded = canonical_json(state)
        if len(encoded.encode('utf-8')) > 16777216:
            raise ValidationError('Campaign audit state exceeds bounds')
        db.execute('UPDATE state SET payload=? WHERE id=1', (encoded,))
        db.commit()
        temporary = output_dir / 'campaign.json.tmp'
        temporary.write_text(encoded, encoding='utf-8')
        temporary.replace(output_dir / 'campaign.json')
        return state
    except Exception:
        raise ValidationError('Interrupted campaign audit reconciliation failed') from None
    finally:
        if db is not None:
            db.close()
        if lock is not None:
            try:
                lock.rollback()
            finally:
                lock.close()
