"""Generated archived-schema records, never relabelled current producer runs.

These are explicit schema fixtures with manufactured result summaries and source
hash labels. They are not actual provider receipts or archived market runs.
"""
import copy
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from quantlab.core import Dataset, canonical_json, content_hash, to_dict
from quantlab.reporting import demo_config, synthetic_dataset
from quantlab.research import (_campaign_config, _dataset_identity, demo_campaign_config,
                               PARAMETER_CONTRACTS, training_summary, validate_dsl, candidate_fingerprint, _reserve_holdout)
from quantlab.saved_candidate_pool import AUDITED_PRODUCER
from quantlab.strategies import builtin_strategies


def shifted_dataset(dataset, days=-30):
    bars = tuple(replace(bar, timestamp=bar.timestamp + timedelta(days=days),
                         end=bar.end + timedelta(days=days),
                         trade_date=(bar.timestamp + timedelta(days=days)).date().isoformat())
                 for bar in dataset.bars)
    manifest = {**dataset.manifest, 'data_hash': content_hash(bars), 'source_hash': content_hash(bars),
                'coverage': {'start': bars[0].timestamp, 'end': bars[-1].end}}
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
    return Dataset(bars, manifest, dict(dataset.quality))


def source_summary(split, spec, config, score='0', producer=None):
    producer = producer or AUDITED_PRODUCER
    manifest = {k: v for k, v in to_dict(split.manifest).items() if k != 'imported_at'}
    result_manifest = {
        'schema_version': 1, 'engine_version': 'quantlab-event-v1',
        'dataset_manifest': manifest, 'dataset_manifest_hash': content_hash(manifest),
        'data_hash': split.manifest['data_hash'], 'spec_hash': content_hash(spec), 'strategy': to_dict(spec),
        'config_hash': content_hash(config), 'config': to_dict(config),
        'source_hashes': dict(producer['result_source_hashes']),
        'engine_hash': content_hash(producer['result_source_hashes']),
        'cost_hash': content_hash((config.costs,) + tuple(config.cost_schedule)),
        'source_commit': config.source_commit, 'seed': config.seed,
        'source_type': split.manifest['source_type'], 'calendar_hash': split.manifest.get('calendar_hash'),
        'calendar_version': split.manifest.get('calendar_version'), 'settlement_mode': config.settlement_mode,
        'run_hash': content_hash(['generated result fixture', spec, split.manifest['data_hash']]),
    }
    result_manifest['reproducibility_hash'] = result_manifest['run_hash']
    return {'metrics': {'net_pnl': score, 'trade_count': 1, 'max_drawdown_pct': '0.01'},
            'warnings': ['Generated schema fixture; no evaluation or model invocation.'],
            'result_hash': content_hash(['generated summary fixture', result_manifest]), 'manifest': result_manifest}


def write_source(folder, state):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(state)
    with closing(sqlite3.connect(folder / 'campaign.sqlite3')) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (encoded,))
    (folder / 'campaign.json').write_text(encoded, encoding='utf-8')


def make_saved_source(root, *, data=None, candidates=15, exclude_sequences=(), producer=None, provider=None, registry_path=None):
    """Return (folder, workspace_reference, exact_original_dataset, mutable_state)."""
    producer = producer or AUDITED_PRODUCER
    data = shifted_dataset(synthetic_dataset(240)) if data is None else data
    config = demo_campaign_config(data, demo_config())
    config['max_trials'] = candidates
    config['ranking']['minimum'] = '-1000000'
    splits = _campaign_config(data, config)
    provider = provider or {'mode': 'fixture', 'model': None, 'endpoint': None}
    binding = {'config': to_dict(config), 'data_hash': _dataset_identity(data),
               'split_hashes': {name: _dataset_identity(split) for name, split in splits.items()},
               'provider': provider, 'prompt_template_hash': producer['prompt_template_hash'],
               'engine_source_hashes': dict(producer['engine_source_hashes'])}
    campaign_id = content_hash(binding)
    state = {'campaign_id': campaign_id, 'binding': binding, 'status': 'completed',
             'source_manifest': to_dict(data.manifest), 'attempts': [], 'selected': [],
             'evaluations': {'oos': [], 'holdout': []}, 'holdout_consumed': False,
             'holdout_status': 'not_accessed', 'elapsed_seconds': 0.1,
             'real_model_status': 'not_verified', 'provider_receipts': [],
             'resource_enforcement': {}, 'warnings': ['Generated archived-schema fixture only.']}
    previous = {}
    schedule = [(family, iteration) for iteration in range(3) for family in config['families']][:candidates]
    for sequence, (family, iteration) in enumerate(schedule, 1):
        payload = to_dict(next(spec for spec in builtin_strategies() if spec.family == family))
        payload['strategy_id'] = f'generated_source_{family}_{iteration}'
        parameter = 'fast' if family == 'trend' else 'lookback'
        payload['parameters'][parameter] += iteration
        spec = validate_dsl(payload)
        parent = previous.get(family)
        context = {'family': family, 'iteration': iteration, 'seed': config['seed'],
            'parameter_contract': PARAMETER_CONTRACTS[family], 'training': training_summary(splits['train']),
            'validation': {'bar_count': len(splits['validation'].bars), 'hash': content_hash(splits['validation'].bars)},
            'previous': copy.deepcopy({'output': parent['output'], 'metrics': {k: v['metrics'] for k, v in parent['metrics'].items()},
                                      'status': parent['status']}) if parent else None}
        attempt = {'attempt_id': content_hash([campaign_id, sequence]), 'sequence': sequence,
            'parent_id': parent['attempt_id'] if parent else None, 'family': family, 'iteration': iteration,
            'status': 'evaluated', 'provider': provider, 'prompt_template_hash': binding['prompt_template_hash'],
            'split_hashes': {k: binding['split_hashes'][k] for k in ('train', 'validation')},
            'output': payload, 'output_hash': content_hash(payload), 'strategy_hash': content_hash(spec),
            'spec': to_dict(spec), 'generator_context': context,
            'metrics': {name: source_summary(splits[name], spec, config['backtest_config'], producer=producer) for name in ('train', 'validation')},
            'cost': '0' if provider['mode'] == 'fixture' else None, 'elapsed_seconds': 0.01, 'warnings': []}
        if producer['protocol'] != AUDITED_PRODUCER['protocol']:
            attempt['candidate_fingerprint'] = candidate_fingerprint(spec)
        if sequence in exclude_sequences:
            attempt.update(status='rejected', output=None, output_hash=None, strategy_hash=None, metrics={}, warnings=['ValidationError'])
            del attempt['spec']
            attempt.pop('candidate_fingerprint', None)
        state['attempts'].append(attempt)
        previous[family] = attempt
    for family in config['families']:
        winner = next((a for a in state['attempts'] if a['family'] == family and a['status'] == 'evaluated'), None)
        if winner:
            state['selected'].append({'attempt_id': winner['attempt_id'], 'strategy_hash': winner['strategy_hash'],
                                      'spec': winner['spec'], 'validation': winner['metrics']['validation']})
    if provider['mode'] == 'openai_compatible':
        from quantlab.saved_candidate_pool import _compatible_request
        for attempt in state['attempts']:
            if attempt['output_hash'] is not None:
                request = _compatible_request(provider, attempt['generator_context'], attempt['iteration'],
                    producer['protocol'] != AUDITED_PRODUCER['protocol'])
                state['provider_receipts'].append({
                    'response_hash': content_hash({'choices': [{'message': {'content': canonical_json(attempt['output'])}}]}),
                    'reserved_tokens': len(canonical_json(request).encode('utf-8')) + provider['limits']['tokens_per_call'],
                    'reserved_spend': '0', 'status': 'transport_returned_not_verified'})
    state['selection_hash'] = content_hash(state['selected'])
    if state['selected']:
        state.update(holdout_consumed=True, holdout_status='reserved_consumed', holdout_selection_hash=state['selection_hash'],
            holdout_registry={'status': 'reserved_consumed', 'holdout_hash': content_hash(splits['holdout'].bars)})
        for name in ('oos', 'holdout'):
            for candidate in state['selected']:
                state['evaluations'][name].append({'strategy_hash': candidate['strategy_hash'], 'status': 'evaluated',
                    **source_summary(splits[name], validate_dsl(candidate['spec']), config['backtest_config'], score='987654321', producer=producer)})
    folder = Path(root) / campaign_id
    if state['selected']:
        selected_registry = Path(registry_path) if registry_path is not None else Path(root) / 'source-registry.sqlite3'
        reservation = _reserve_holdout(splits['holdout'], registry_path=selected_registry, campaign_id=campaign_id,
            selection_hash=state['selection_hash'], output_dir=folder)
        if reservation['status'] != 'reserved_consumed':
            raise AssertionError('Generated fixture source holdout already consumed; use distinct historical data or fixture authority')
        state['holdout_registry'] = reservation
    write_source(folder, state)
    return folder, campaign_id, data, state


def make_chatgpt_source(root, *, implementation=0, candidates=15, producer=None, registry_path=None, dependency_target=None):
    """Explicit manufactured descriptor/receipts; no auth or provider instantiated."""
    from quantlab.saved_candidate_pool import CURRENT_PRODUCER
    from quantlab.research import PROMPT
    producer = producer or CURRENT_PRODUCER
    variant = producer['chatgpt_plan_implementations'][implementation]
    descriptor = {key: copy.deepcopy(variant[key]) for key in ('source_sha256', 'dependency_versions',
                  'dependency_manifest_sha256', 'dependency_artifact_evidence')}
    descriptor.update(version=1, mode='chatgpt_plan', model='fixture-model',
        endpoint='https://api.openai.com/v1/responses', registration='a' * 32,
        campaign_id='generated-fixture-campaign', dependency_target=dependency_target or variant['dependency_targets'][0],
        max_calls=15, timeout_seconds=60, stall_seconds=30, max_request_bytes=65536,
        max_response_bytes=1048576, max_event_bytes=65536, max_candidate_bytes=16384, max_events=2048,
        billing_route='chatgpt_plan', paid_api_fallback=False, token_upper_bound_enforced=False,
        spend_upper_bound_enforced=False, account_credit_policy='unverified_user_setting',
        included_usage_policy_ack_required=True)
    provider = {'mode': 'chatgpt_plan', 'model': descriptor['model'], 'endpoint': descriptor['endpoint'],
                'descriptor': descriptor}
    folder, reference, data, state = make_saved_source(root, candidates=candidates, producer=producer, provider=provider, registry_path=registry_path)
    for attempt in state['attempts']:
        context = copy.deepcopy(attempt['generator_context'])
        if attempt['iteration']:
            context.update(task='improve_previous_candidate', improvement_instruction=(
                'Propose a distinct candidate in the same family using training and validation feedback only. Keep risk controls unchanged.'))
        request = {'model': provider['model'], 'instructions': PROMPT,
            'input': [{'role': 'user', 'content': canonical_json(context)}], 'store': False, 'stream': True}
        state['provider_receipts'].append({'sequence': attempt['sequence'], 'request_hash': content_hash(request),
            'request_bytes': len(canonical_json(request).encode('utf-8')), 'status': 'completed',
            'response_hash': attempt['output_hash'], 'token_usage': 'unknown', 'received_bytes': 100,
            'elapsed_seconds': 0.01, 'billing_route': 'chatgpt_plan', 'paid_api_fallback': False,
            'token_upper_bound_enforced': False, 'spend_upper_bound_enforced': False,
            'account_credit_policy': 'unverified_user_setting'})
    write_source(folder, state)
    return folder, reference, data, state
