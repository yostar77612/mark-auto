"""Explicit, one-call research interpretation of locally verified evidence.

This module owns no network or credentials. The desktop injects its reviewed
subscription provider. Campaigns, selection, OOS/holdout and generation budgets
are never modified. A stopped/unknown analysis is never implicitly resubmitted.
"""
from __future__ import annotations

import copy
from contextlib import closing
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .core import ValidationError, canonical_json, content_hash, to_dict
from .research import (_campaign_config, _dataset_identity, _evaluate_split,
                       _run_bounded, _unique_keys, _validated_provider_descriptor,
                       _validated_receipt_snapshot, PARAMETER_CONTRACTS, validate_dsl)

VERSION = 1
MAX_CANDIDATES = 5
MAX_WINDOW_BARS = 64
MAX_CONTEXT_BYTES = 56000
MAX_RECORD_BYTES = 524288
METRICS = ('net_pnl', 'realized_gross_pnl', 'unrealized_pnl', 'total_costs',
           'slippage_cost', 'return', 'max_drawdown', 'max_drawdown_pct',
           'trade_count', 'fill_count', 'win_rate', 'profit_factor', 'sharpe',
           'sharpe_observations', 'sharpe_sample_count', 'open_position')
INDICATORS = ('sma_20', 'rsi_14', 'macd', 'macd_signal', 'macd_histogram')
KINDS = ('market', 'entry_exit', 'backtest', 'weakness', 'risk', 'improvement', 'comparison')
ANALYSIS_PROMPT = '''markauto-research-analysis-v1. Interpret only the supplied historical training OHLC/indicators and deterministic train/validation evidence. You have no order authority. Return one JSON object without code, Markdown or additional keys: {"schema_version":1,"task":"critique" or "compare","findings":[{"kind":one of market/entry_exit/backtest/weakness/risk/improvement/comparison,"strategy_hashes":[supplied strategy hashes],"evidence_refs":[{"evidence_id":supplied evidence id,"field":supplied metric name, or ohlcv/sma_20/rsi_14/macd/macd_signal/macd_histogram for training evidence}],"text":qualitative explanation}]}.
For kind=improvement also include signal_parameter naming exactly one allowed signal parameter of the referenced strategy. Improvement findings reference exactly one strategy. No other finding has signal_parameter. A critique must include market, entry_exit, backtest, weakness, risk and improvement findings. A comparison must include comparison and risk findings. Use 1..24 findings, 1..5 strategies and 1..8 evidence references per finding. Write all qualitative explanation text in Traditional Chinese. Text is 1..600 characters, qualitative only, with no digits: numeric values are displayed from the referenced local evidence, never invented by you. Do not output calculated metrics, parameter values, quantity, position-sizing changes, stops, targets, commands, code, recommendations to trade now, or claims of profitability. Suggest only signal-parameter research changes. Null indicators/metrics are unavailable, not zero. Capped windows are partial observations; describe uncertainty. OOS/holdout results are not supplied and must not be inferred. Critique does not establish why an earlier version was generated, and suggestions do not modify any strategy.'''


def _fail(message):
    raise ValidationError(message)


def _keys(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        _fail('Invalid analysis fields')


def _hash(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def _bounded(value, maximum=MAX_RECORD_BYTES):
    count = 0
    def walk(item, depth=0):
        nonlocal count
        count += 1
        if depth > 16 or count > 20000:
            _fail('Analysis structure limit exceeded')
        if type(item) is dict:
            if any(type(key) is not str for key in item): _fail('Invalid analysis key')
            for child in item.values(): walk(child, depth + 1)
        elif type(item) is list:
            for child in item: walk(child, depth + 1)
        elif type(item) is float:
            if not math.isfinite(item): _fail('Nonfinite analysis value')
        elif item is not None and type(item) not in (str, int, bool):
            _fail('Analysis must contain strict JSON values')
    walk(value)
    if len(canonical_json(value).encode('utf-8')) > maximum:
        _fail('Analysis byte limit exceeded')


def _number(value, *, nullable=True):
    if value is None and nullable: return
    if type(value) not in (int, str): _fail('Invalid deterministic numeric evidence')
    try: parsed = Decimal(value)
    except (InvalidOperation, ValueError): _fail('Invalid deterministic numeric evidence')
    if not parsed.is_finite() or parsed.copy_abs() > Decimal('1e30'):
        _fail('Invalid deterministic numeric evidence')


def _safe_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        _fail('Absolute managed analysis path required')
    for item in (path, *path.parents):
        if item.is_symlink(): _fail('Analysis links refused')
        if item.exists():
            info = item.stat()
            if getattr(info, 'st_file_attributes', 0) & 0x400:
                _fail('Analysis reparse points refused')
    return path


def _implementation():
    root = Path(__file__).parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ('research_analysis.py', 'indicators.py')}


def _training_packet(dataset):
    from . import indicators
    groups = {}
    for bar in dataset.bars:
        groups.setdefault(bar.contract_id, []).append(bar)
    selected = {content_hash(bar) for bar in dataset.bars[-MAX_WINDOW_BARS:]}
    rows = []
    for contract, bars in groups.items():
        closes = [bar.close for bar in bars]
        line = indicators.macd(closes)
        values = {'sma_20': indicators.sma(closes, period=20),
                  'rsi_14': indicators.rsi(closes, period=14),
                  'macd': line['macd'], 'macd_signal': line['signal'],
                  'macd_histogram': line['histogram']}
        for index, bar in enumerate(bars):
            if content_hash(bar) not in selected: continue
            rows.append({'timestamp': bar.timestamp.isoformat(), 'end': bar.end.isoformat(),
                         'contract_id': contract,
                         **{key: str(getattr(bar, key)) for key in ('open', 'high', 'low', 'close')},
                         'volume': bar.volume,
                         'indicators': {key: None if series[index] is None else str(series[index])
                                        for key, series in values.items()}})
    rows.sort(key=lambda row: (row['timestamp'], row['contract_id']))
    packet = {'bar_count': len(dataset.bars), 'window_count': len(rows),
              'window_policy': 'last_64_training_bars_only',
              'data_hash': content_hash(dataset.bars),
              'formula_version': indicators.FORMULA_VERSION, 'bars': rows}
    packet['evidence_id'] = content_hash(packet)
    return packet


def validate_analysis_context(context):
    """Closed transmission grammar: no arbitrary manifests or held-out records."""
    _bounded(context, MAX_CONTEXT_BYTES)
    _keys(context, ('schema_version', 'task', 'training', 'strategies', 'evidence'))
    if type(context['schema_version']) is not int or context['schema_version'] != VERSION:
        _fail('Unsupported analysis context')
    if context['task'] not in ('critique', 'compare'): _fail('Invalid analysis task')
    strategies = context['strategies']
    if type(strategies) is not list or not 1 <= len(strategies) <= MAX_CANDIDATES:
        _fail('Invalid analysis candidate count')
    if context['task'] == 'critique' and len(strategies) != 1:
        _fail('Critique requires one strategy')
    if context['task'] == 'compare' and len(strategies) < 2:
        _fail('Comparison requires multiple strategies')
    hashes = set()
    for row in strategies:
        _keys(row, ('strategy_hash', 'spec'))
        spec = validate_dsl(row['spec'])
        if row['strategy_hash'] != content_hash(spec) or row['strategy_hash'] in hashes:
            _fail('Invalid or duplicate strategy binding')
        hashes.add(row['strategy_hash'])
    training = context['training']
    _keys(training, ('bar_count', 'window_count', 'window_policy', 'data_hash',
                     'formula_version', 'bars', 'evidence_id'))
    if (type(training['bar_count']) is not int or not 1 <= training['bar_count'] <= 100000
        or type(training['window_count']) is not int
        or training['window_count'] != min(MAX_WINDOW_BARS, training['bar_count'])
        or training['window_policy'] != 'last_64_training_bars_only'
        or not _hash(training['data_hash']) or type(training['formula_version']) is not str
        or not 1 <= len(training['formula_version']) <= 64
        or type(training['bars']) is not list or len(training['bars']) != training['window_count']
        or training['evidence_id'] != content_hash({k: v for k, v in training.items() if k != 'evidence_id'})):
        _fail('Invalid training evidence')
    for row in training['bars']:
        _keys(row, ('timestamp', 'end', 'contract_id', 'open', 'high', 'low', 'close', 'volume', 'indicators'))
        for key in ('timestamp', 'end', 'contract_id'):
            if type(row[key]) is not str or not 1 <= len(row[key]) <= 128:
                _fail('Invalid training observation')
        for key in ('open', 'high', 'low', 'close'): _number(row[key], nullable=False)
        if type(row['volume']) is not int or row['volume'] < 0: _fail('Invalid training volume')
        _keys(row['indicators'], INDICATORS)
        for value in row['indicators'].values(): _number(value)
    evidence = context['evidence']
    if type(evidence) is not list or len(evidence) != 2 * len(strategies):
        _fail('Missing train/validation evidence')
    roles, ids = set(), {training['evidence_id']}
    for row in evidence:
        _keys(row, ('evidence_id', 'strategy_hash', 'split', 'data_hash', 'config_hash', 'metrics'))
        key = (row['strategy_hash'], row['split'])
        if (type(row['strategy_hash']) is not str or type(row['split']) is not str
            or row['strategy_hash'] not in hashes or row['split'] not in ('train', 'validation')
            or key in roles or not _hash(row['data_hash']) or not _hash(row['config_hash'])
            or row['evidence_id'] != content_hash({k: v for k, v in row.items() if k != 'evidence_id'})
            or row['evidence_id'] in ids): _fail('Invalid evaluation evidence binding')
        _keys(row['metrics'], METRICS)
        for value in row['metrics'].values(): _number(value)
        roles.add(key); ids.add(row['evidence_id'])
    return copy.deepcopy(context)


def build_analysis_packet(*, source_campaign_dir, original_dataset, attempt_ids,
                          task='critique', max_runtime_seconds=120, cancelled=None):
    """Recompute selected training/validation summaries; never rerun held-out data.

    The caller's worker must also enforce its normal process-tree deadline. The
    dataset must be the exact original; source paths never enter model context.
    """
    from .saved_candidate_pool import _read_campaign, _validate_original_dataset
    folder = _safe_path(source_campaign_dir)
    if not _hash(folder.name): _fail('Invalid source campaign reference')
    if type(max_runtime_seconds) is not int or not 1 <= max_runtime_seconds <= 7200:
        _fail('Explicit analysis preparation runtime required')
    deadline = time.monotonic() + max_runtime_seconds
    def check():
        if cancelled is not None and cancelled(): _fail('Analysis preparation cancelled')
        if time.monotonic() >= deadline: _fail('Analysis preparation deadline exceeded')
    check()
    _validate_original_dataset(original_dataset)
    state = _read_campaign(folder)
    if state.get('status') not in ('completed', 'completed_with_errors'):
        _fail('A terminal saved campaign is required')
    binding = state.get('binding')
    if not isinstance(binding, dict) or state.get('campaign_id') != content_hash(binding):
        _fail('Invalid source campaign identity')
    if (binding.get('data_hash') != _dataset_identity(original_dataset)
        or state.get('source_manifest') != to_dict(original_dataset.manifest)):
        _fail('Exact original dataset required for analysis')
    from .__main__ import config_from_json
    config = copy.deepcopy(binding['config'])
    config['backtest_config'] = config_from_json(config['backtest_config'])
    splits = _campaign_config(original_dataset, config)
    if binding.get('split_hashes') != {name: _dataset_identity(split) for name, split in splits.items()}:
        _fail('Source split bindings differ')
    if (type(attempt_ids) is not list or not 1 <= len(attempt_ids) <= MAX_CANDIDATES
        or any(not _hash(value) for value in attempt_ids) or len(set(attempt_ids)) != len(attempt_ids)):
        _fail('Select bounded distinct saved attempts')
    attempts = state.get('attempts')
    if type(attempts) is not list or not 1 <= len(attempts) <= 15:
        _fail('Invalid source attempts')
    selected = []
    for reference in sorted(attempt_ids):
        matches = [row for row in attempts if isinstance(row, dict) and row.get('attempt_id') == reference]
        if len(matches) != 1: _fail('Missing or duplicate saved attempt')
        row = matches[0]
        if row.get('status') != 'evaluated': _fail('Selected attempt was not evaluated')
        spec = validate_dsl(row.get('spec'))
        if (row.get('strategy_hash') != content_hash(spec) or content_hash(validate_dsl(row.get('output'))) != content_hash(spec)
            or row.get('output_hash') != content_hash(row['output'])
            or set(row.get('metrics', {})) != {'train', 'validation'}):
            _fail('Invalid saved strategy or split results')
        selected.append((row, spec))
    check()
    training = _run_bounded(_training_packet, (splits['train'],), deadline=deadline, config=config)['value']
    context = {'schema_version': VERSION, 'task': task, 'training': training,
               'strategies': [], 'evidence': []}
    links = []
    for attempt, spec in selected:
        context['strategies'].append({'strategy_hash': content_hash(spec), 'spec': to_dict(spec)})
        for role in ('train', 'validation'):
            check()
            summary = _run_bounded(_evaluate_split, (splits[role], spec, config['backtest_config']),
                                   deadline=deadline, config=config)['value']
            stored = attempt['metrics'][role]
            if (type(stored) is not dict or stored.get('metrics') != summary['metrics']
                or stored.get('warnings') != summary['warnings'] or not _hash(stored.get('result_hash'))):
                _fail('Stored scores do not match deterministic re-evaluation')
            manifest = stored.get('manifest', {})
            for key in ('data_hash', 'dataset_manifest_hash', 'spec_hash', 'strategy',
                        'config_hash', 'config', 'cost_hash', 'calendar_hash', 'calendar_version'):
                if manifest.get(key) != summary['manifest'].get(key):
                    _fail('Stored result input bindings differ')
            evidence = {'strategy_hash': content_hash(spec), 'split': role,
                        'data_hash': content_hash(splits[role].bars),
                        'config_hash': content_hash(config['backtest_config']),
                        'metrics': {key: summary['metrics'].get(key) for key in METRICS}}
            evidence['evidence_id'] = content_hash(evidence)
            context['evidence'].append(evidence)
            links.append({'evidence_id': evidence['evidence_id'], 'attempt_id': attempt['attempt_id'],
                          'parent_id': attempt.get('parent_id'), 'stored_result_hash': stored['result_hash'],
                          'recomputed_result_hash': summary['result_hash'],
                          'recomputed_engine_hash': summary['manifest']['engine_hash']})
    validate_analysis_context(context)
    check()
    packet = {'schema_version': VERSION, 'context': context,
              'provenance': {'campaign_ref': folder.name, 'campaign_id': state['campaign_id'],
                             'source_journal_hash': content_hash(state),
                             'original_dataset_identity': _dataset_identity(original_dataset),
                             'verification': 'selected_train_validation_recomputed',
                             'archived_result_status': 'reference_only_unverified',
                             'result_links': links}, 'implementation': _implementation()}
    packet['packet_hash'] = content_hash(packet)
    _validate_packet(packet)
    return packet


def _validate_packet(packet):
    _bounded(packet)
    _keys(packet, ('schema_version', 'context', 'provenance', 'implementation', 'packet_hash'))
    if type(packet['schema_version']) is not int or packet['schema_version'] != VERSION or packet['packet_hash'] != content_hash({k: v for k, v in packet.items() if k != 'packet_hash'}):
        _fail('Invalid analysis packet binding')
    validate_analysis_context(packet['context'])
    _keys(packet['implementation'], ('research_analysis.py', 'indicators.py'))
    if any(not _hash(value) for value in packet['implementation'].values()): _fail('Invalid analysis implementation')
    provenance = packet['provenance']
    _keys(provenance, ('campaign_ref', 'campaign_id', 'source_journal_hash', 'original_dataset_identity', 'verification', 'archived_result_status', 'result_links'))
    if any(not _hash(provenance[key]) for key in ('campaign_ref', 'campaign_id', 'source_journal_hash', 'original_dataset_identity')):
        _fail('Invalid source reference')
    if (provenance['verification'] != 'selected_train_validation_recomputed'
        or provenance['archived_result_status'] != 'reference_only_unverified'):
        _fail('Unverified evidence or misleading archived-result claim')
    links = provenance['result_links']
    if type(links) is not list or len(links) != len(packet['context']['evidence']): _fail('Invalid result links')
    for link, evidence in zip(links, packet['context']['evidence']):
        _keys(link, ('evidence_id', 'attempt_id', 'parent_id', 'stored_result_hash', 'recomputed_result_hash', 'recomputed_engine_hash'))
        if (link['evidence_id'] != evidence['evidence_id']
            or any(not _hash(link[key]) for key in ('attempt_id', 'stored_result_hash', 'recomputed_result_hash', 'recomputed_engine_hash'))
            or link['parent_id'] is not None and not _hash(link['parent_id'])):
            _fail('Invalid linked result identity')


def validate_analysis_response(value, context):
    validate_analysis_context(context)
    _bounded(value, 16384)
    _keys(value, ('schema_version', 'task', 'findings'))
    if type(value['schema_version']) is not int or value['schema_version'] != VERSION or value['task'] != context['task']:
        _fail('Invalid analysis response task')
    rows = value['findings']
    if type(rows) is not list or not 1 <= len(rows) <= 24: _fail('Invalid finding count')
    strategies = {row['strategy_hash']: row['spec'] for row in context['strategies']}
    evidence = {row['evidence_id']: (row['strategy_hash'], set(METRICS)) for row in context['evidence']}
    evidence[context['training']['evidence_id']] = (None, {'ohlcv', *INDICATORS})
    kinds = set()
    for row in rows:
        _keys(row, ('kind', 'strategy_hashes', 'evidence_refs', 'text'), ('signal_parameter',))
        if row['kind'] not in KINDS: _fail('Invalid finding kind')
        targets = row['strategy_hashes']
        if (type(targets) is not list or not 1 <= len(targets) <= MAX_CANDIDATES
            or any(type(target) is not str or target not in strategies for target in targets) or len(set(targets)) != len(targets)):
            _fail('Invented analysis strategy reference')
        refs = row['evidence_refs']
        if type(refs) is not list or not 1 <= len(refs) <= 8: _fail('Missing analysis evidence')
        for ref in refs:
            _keys(ref, ('evidence_id', 'field'))
            if type(ref['evidence_id']) is not str or type(ref['field']) is not str:
                _fail('Invalid analysis evidence reference')
            known = evidence.get(ref['evidence_id'])
            if known is None or ref['field'] not in known[1] or known[0] is not None and known[0] not in targets:
                _fail('Invented metric or evidence reference')
        text = row['text']
        if (type(text) is not str or not 1 <= len(text) <= 600 or text != text.strip()
            or any(char.isdigit() or ord(char) < 32 for char in text)):
            _fail('Analysis text must be bounded qualitative prose; numeric values require references')
        if row['kind'] == 'improvement':
            if len(targets) != 1 or type(row.get('signal_parameter')) is not str or row.get('signal_parameter') not in PARAMETER_CONTRACTS[strategies[targets[0]]['family']]:
                _fail('Risk or unsupported parameter change refused')
        elif 'signal_parameter' in row: _fail('Unexpected parameter proposal')
        kinds.add(row['kind'])
    required = {'market', 'entry_exit', 'backtest', 'weakness', 'risk', 'improvement'} if context['task'] == 'critique' else {'comparison', 'risk'}
    if not required <= kinds: _fail('Incomplete research interpretation')
    return copy.deepcopy(value)


def make_analysis_plan(packet, *, model, registration, provider_implementation, timeout_seconds=30):
    """Local preview only; one immutable call budget, with no network/ledger writes."""
    packet = copy.deepcopy(packet)
    _validate_packet(packet)
    if (type(model) is not str or not re.fullmatch('[A-Za-z0-9._:-]{1,128}', model)
        or type(registration) is not str or not re.fullmatch('[a-f0-9]{32}', registration)
        or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120):
        _fail('Invalid explicit analysis provider choice')
    implementation = _validated_provider_descriptor({'version': 1, **provider_implementation})
    binding = {'schema_version': VERSION, 'packet': copy.deepcopy(packet), 'model': model,
               'registration': registration, 'max_calls': 1, 'timeout_seconds': timeout_seconds,
               'prompt_hash': content_hash(ANALYSIS_PROMPT), 'provider_implementation': implementation}
    # Timeout is an immutable first-launch control, not a way to obtain a new slot.
    request = {'model': model, 'instructions': ANALYSIS_PROMPT,
               'input': [{'role': 'user', 'content': canonical_json(packet['context'])}],
               'store': False, 'stream': True}
    if len(canonical_json(request).encode('utf-8')) > 65536:
        _fail('Analysis request byte limit')
    identity = {key: val for key, val in binding.items() if key != 'timeout_seconds'}
    return {'analysis_id': content_hash(identity), 'binding': binding}


def validate_analysis_plan(plan):
    _bounded(plan)
    _keys(plan, ('analysis_id', 'binding'))
    binding = plan['binding']
    _keys(binding, ('schema_version', 'packet', 'model', 'registration', 'max_calls',
                    'timeout_seconds', 'prompt_hash', 'provider_implementation'))
    if (type(binding['schema_version']) is not int or binding['schema_version'] != VERSION
        or type(binding['max_calls']) is not int or binding['max_calls'] != 1
        or type(binding['provider_implementation']) is not dict):
        _fail('Invalid fixed analysis controls')
    implementation = dict(binding['provider_implementation'])
    implementation.pop('version', None)
    expected = make_analysis_plan(binding['packet'], model=binding['model'], registration=binding['registration'],
                                  provider_implementation=implementation, timeout_seconds=binding['timeout_seconds'])
    if plan != expected: _fail('Analysis preview binding changed')
    return copy.deepcopy(plan)


def _descriptor_for_plan(plan, descriptor):
    """Pure binding checks also protect offline reads, not just live admission."""
    descriptor = _validated_provider_descriptor(descriptor)
    binding = plan['binding']
    expected = {**binding['provider_implementation'],
        'version': 1, 'mode': 'chatgpt_plan', 'model': binding['model'],
        'endpoint': 'https://api.openai.com/v1/responses',
        'registration': binding['registration'], 'campaign_id': 'analysis-' + plan['analysis_id'],
        'max_calls': 1, 'timeout_seconds': binding['timeout_seconds'], 'stall_seconds': 10,
        'max_request_bytes': 65536, 'max_response_bytes': 262144,
        'max_event_bytes': 65536, 'max_candidate_bytes': 16384, 'max_events': 2048,
        'billing_route': 'chatgpt_plan', 'paid_api_fallback': False,
        'token_upper_bound_enforced': False, 'spend_upper_bound_enforced': False,
        'account_credit_policy': 'unverified_user_setting', 'included_usage_policy_ack_required': True}
    # Canonical serialization distinguishes booleans from integers.
    if canonical_json(descriptor) != canonical_json(expected):
        _fail('Analysis provider differs from approved preview')
    return descriptor


def _provider(plan, provider):
    descriptor = _descriptor_for_plan(plan, provider.provider_descriptor())
    if Path(provider.path).name != 'chatgpt-analysis-' + plan['analysis_id'] + '.sqlite3':
        _fail('Analysis control ledger identity differs')
    return descriptor


def _snapshot(provider, descriptor):
    snapshot = provider.read_receipt_snapshot()
    _validated_receipt_snapshot(snapshot, descriptor)
    return snapshot


def _folder(root, identity):
    if not _hash(identity): _fail('Invalid analysis reference')
    return _safe_path(_safe_path(root) / identity)


def _read_journal(folder):
    journal = _safe_path(folder / 'analysis.sqlite3')
    if not journal.is_file(): _fail('Missing saved analysis evidence')
    if journal.stat().st_size > 2 * MAX_RECORD_BYTES:
        _fail('Analysis journal size limit')
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True, timeout=0)) as db:
        from .saved_candidate_pool import _prepare_bounded_read
        _prepare_bounded_read(db, {'state': [('id', 'INTEGER', 0, None, 1, 0),
                                            ('payload', 'TEXT', 1, None, 0, 0)]})
        size = db.execute('SELECT id, length(CAST(payload AS BLOB)) FROM state').fetchmany(2)
        if len(size) != 1 or size[0][0] != 1 or not 1 <= size[0][1] <= MAX_RECORD_BYTES:
            _fail('Invalid analysis journal')
        text = db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]
    value = json.loads(text, object_pairs_hook=_unique_keys)
    _validate_record(value)
    if value['plan']['analysis_id'] != folder.name: _fail('Analysis directory identity mismatch')
    return value


def _read_projection(folder):
    projection = _safe_path(folder / 'analysis.json')
    if not projection.is_file(): _fail('Missing saved analysis evidence')
    if projection.stat().st_size > MAX_RECORD_BYTES: _fail('Analysis export size limit')
    with projection.open('rb') as source:
        raw = source.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES: _fail('Analysis export size limit')
    return json.loads(raw, object_pairs_hook=_unique_keys)


def _read(folder):
    value = _read_journal(folder)
    if canonical_json(value) != canonical_json(_read_projection(folder)):
        _fail('Analysis journal/export mismatch')
    return value


def _read_analysis_journal(output_root, analysis_id):
    # Internal desktop provider preparation only. Not a replacement for strict
    # saved reads; reconciliation rereads this evidence under its own lock.
    return _read_journal(_folder(output_root, analysis_id))


def _validate_record(record):
    _bounded(record)
    _keys(record, ('schema_version', 'plan', 'provider_descriptor', 'status', 'response',
                   'response_hash', 'receipt_snapshot', 'real_model_status'))
    if type(record['schema_version']) is not int or record['schema_version'] != VERSION or record['status'] not in ('running', 'completed', 'blocked'):
        _fail('Invalid analysis record state')
    validate_analysis_plan(record['plan'])
    descriptor = _descriptor_for_plan(record['plan'], record['provider_descriptor'])
    receipts = _validated_receipt_snapshot(record['receipt_snapshot'], descriptor)
    if len(receipts) > 1 or record['real_model_status'] != 'not_verified': _fail('Invalid analysis receipt claim')
    if record['status'] == 'completed':
        validate_analysis_response(record['response'], record['plan']['binding']['packet']['context'])
        request = analysis_request(record['plan'])
        if (record['response_hash'] != content_hash(record['response']) or len(receipts) != 1
            or receipts[0]['status'] != 'completed' or receipts[0]['response_hash'] != record['response_hash']
            or receipts[0]['request_hash'] != content_hash(request)
            or receipts[0]['request_bytes'] != len(canonical_json(request).encode('utf-8'))):
            _fail('Analysis response lacks matching completed receipt')
    elif record['response'] is not None or record['response_hash'] is not None:
        _fail('Incomplete analysis cannot publish output')


def analysis_request(plan):
    validate_analysis_plan(plan)
    return {'model': plan['binding']['model'], 'instructions': ANALYSIS_PROMPT,
            'input': [{'role': 'user', 'content': canonical_json(plan['binding']['packet']['context'])}],
            'store': False, 'stream': True}


def _save(folder, record):
    _validate_record(record)
    text = canonical_json(record)
    journal = _safe_path(folder / 'analysis.sqlite3')
    with closing(sqlite3.connect(journal.as_uri() + '?mode=rwc', uri=True, timeout=0)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (text,))
    _write_projection(folder, text)


def _write_projection(folder, text):
    temporary = _safe_path(folder / 'analysis.json.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(_safe_path(folder / 'analysis.json'))


def read_analysis(output_root, analysis_id):
    """Offline saved-artifact read; it grants no authority to submit/retry a call."""
    record = _read(_folder(output_root, analysis_id))
    if record['plan']['analysis_id'] != analysis_id: _fail('Analysis directory identity mismatch')
    return record


def run_analysis(*, output_root, plan, provider, expected_analysis_id, user_confirmed=False, cancelled=None):
    """Use one independent durable provider budget; never mutate a source campaign.

    Host must rebuild the packet from source refs and compare this preview identity
    immediately before invoking. Cancellation must retain normal subtree controls.
    """
    plan = validate_analysis_plan(plan)
    if expected_analysis_id != plan['analysis_id']: _fail('Analysis inputs changed after preview')
    descriptor = _provider(plan, provider)
    folder = _folder(output_root, plan['analysis_id'])
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = _safe_path(folder / 'analysis.lock.sqlite3')
    with closing(sqlite3.connect(lock_path.as_uri() + '?mode=rwc', uri=True, timeout=0)) as lock:
        try: lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError: _fail('Analysis is already running')
        snapshot = _snapshot(provider, descriptor)
        journal = folder / 'analysis.sqlite3'
        if journal.exists() or (folder / 'analysis.json').exists():
            record = read_analysis(output_root, plan['analysis_id'])
            if record['plan'] != plan or record['provider_descriptor'] != descriptor:
                _fail('Existing analysis controls are immutable')
            if record['status'] == 'completed':
                if record['receipt_snapshot'] != snapshot: _fail('Saved analysis/control receipt mismatch')
                return {'record': record, 'cache_hit': True}
            _fail('Analysis interrupted or blocked; no implicit retry')
        if snapshot['receipts']: _fail('Analysis output missing after a consumed reservation; no resubmission')
        if user_confirmed is not True or getattr(provider, 'network_opt_in', False) is not True or getattr(provider, 'included_usage_policy_confirmed', False) is not True:
            _fail('Explicit one-call analysis authorization required')
        if cancelled is not None and cancelled(): _fail('Analysis cancelled before submission')
        if plan['binding']['packet']['implementation'] != _implementation():
            _fail('Analysis preparation implementation changed; rebuild the preview')
        request = analysis_request(plan)
        if len(canonical_json(request).encode('utf-8')) > descriptor['max_request_bytes']:
            _fail('Analysis request byte limit')
        provider.analysis_preflight()  # Local-only: paused accounts must not consume an analysis task.
        record = {'schema_version': VERSION, 'plan': copy.deepcopy(plan), 'provider_descriptor': descriptor,
                  'status': 'running', 'response': None, 'response_hash': None,
                  'receipt_snapshot': snapshot, 'real_model_status': 'not_verified'}
        _save(folder, record)
        try:
            response = provider.analyze(plan['binding']['packet']['context'], cancelled=cancelled)
            response = validate_analysis_response(response, plan['binding']['packet']['context'])
            record.update(status='completed', response=response, response_hash=content_hash(response),
                          receipt_snapshot=_snapshot(provider, descriptor))
            _save(folder, record)
            return {'record': record, 'cache_hit': False}
        except BaseException:
            record.update(status='blocked', response=None, response_hash=None)
            try:
                record['receipt_snapshot'] = _snapshot(provider, descriptor)
                _save(folder, record)
            except Exception:
                pass  # Preserve running evidence; never mask/reset the durable ledger.
            raise


def reconcile_analysis(*, output_root, analysis_id, provider, descendants_stopped=False):
    """Local-only reconciliation after host-owned proof of process-tree stop."""
    if descendants_stopped is not True: _fail('Analysis descendants must be stopped')
    folder = _folder(output_root, analysis_id)
    lock_path = _safe_path(folder / 'analysis.lock.sqlite3')
    if not lock_path.is_file(): _fail('Missing analysis lock evidence')
    with closing(sqlite3.connect(lock_path.as_uri() + '?mode=rw', uri=True, timeout=0)) as lock:
        try: lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError: _fail('Analysis is still running')
        record = _read_analysis_journal(output_root, analysis_id)
        descriptor = _provider(record['plan'], provider)
        if descriptor != record['provider_descriptor']: _fail('Original analysis provider required')
        snapshot = _snapshot(provider, descriptor)
        # A terminal journal must match the original durable provider ledger.
        # Never repair restored/forged evidence or reset a consumed reservation.
        if record['status'] != 'running' and record['receipt_snapshot'] != snapshot:
            _fail('Saved analysis/control receipt mismatch')
        if record['status'] == 'running' and record['receipt_snapshot']['receipts']:
            _fail('Invalid initial analysis receipts')
        if snapshot['receipts']:
            request = analysis_request(record['plan'])
            if (len(snapshot['receipts']) != 1
                or snapshot['receipts'][0]['request_hash'] != content_hash(request)
                or snapshot['receipts'][0]['request_bytes'] != len(canonical_json(request).encode('utf-8'))):
                _fail('Analysis recovery receipt request mismatch')
        projection = _safe_path(folder / 'analysis.json')
        if projection.exists():
            exported = _read_projection(folder)
            if canonical_json(exported) != canonical_json(record):
                # Only the exact initial running projection can lag a terminal
                # commit. A corrupt or altered export is not a crash checkpoint.
                initial = copy.deepcopy(record)
                initial.update(status='running', response=None, response_hash=None,
                               receipt_snapshot={**record['receipt_snapshot'], 'receipts': []})
                if canonical_json(exported) != canonical_json(initial):
                    _fail('Analysis journal/export mismatch')
        if record['status'] == 'running':
            record.update(status='blocked', receipt_snapshot=snapshot)
            _save(folder, record)
        else:
            _write_projection(folder, canonical_json(record))
        return record
