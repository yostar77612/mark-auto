"""Pure analysis wire grammar shared by research execution and recovery."""
import copy
from decimal import Decimal, InvalidOperation
import math
import re
from .core import ValidationError, canonical_json, content_hash
from .research import validate_dsl, _validated_provider_descriptor, PARAMETER_CONTRACTS

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


from .errors import fail


def _fail(message):
    fail(message, ValidationError)



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



def expected_provider_descriptor(plan):
    """Pure exact provider identity; never constructs a provider or accesses credentials."""
    binding = plan['binding']
    return {**binding['provider_implementation'],
        'version': 1, 'mode': 'chatgpt_plan', 'model': binding['model'],
        'endpoint': 'https://api.openai.com/v1/responses',
        'registration': binding['registration'], 'campaign_id': 'analysis-' + plan['analysis_id'],
        'max_calls': 1, 'timeout_seconds': binding['timeout_seconds'], 'stall_seconds': 10,
        'max_request_bytes': 65536, 'max_response_bytes': 262144,
        'max_event_bytes': 65536, 'max_candidate_bytes': 16384, 'max_events': 2048,
        'billing_route': 'chatgpt_plan', 'paid_api_fallback': False,
        'token_upper_bound_enforced': False, 'spend_upper_bound_enforced': False,
        'account_credit_policy': 'unverified_user_setting', 'included_usage_policy_ack_required': True}



def analysis_request(plan):
    validate_analysis_plan(plan)
    return {'model': plan['binding']['model'], 'instructions': ANALYSIS_PROMPT,
            'input': [{'role': 'user', 'content': canonical_json(plan['binding']['packet']['context'])}],
            'store': False, 'stream': True}

