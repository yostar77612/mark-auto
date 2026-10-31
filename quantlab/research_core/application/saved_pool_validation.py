"""Saved campaign evidence; no provider calls or credential access."""

from __future__ import annotations
import re
from collections import Counter
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit
from quantlab.core import ValidationError, canonical_json, content_hash, to_dict
from quantlab.data import parse_timestamp
from quantlab.research import _keys, candidate_fingerprint
from quantlab.research_core.domain.saved_pool import SavedCandidatePool, SavedCandidatePoolError, _hash, _fail


def _check_result(result, split, spec, config, producer):
    """Check stored summary identities without evaluating or using its scores."""
    _keys(result, ('metrics', 'warnings', 'result_hash', 'manifest'))
    if not _hash(result['result_hash']) or type(result['metrics']) is not dict or type(result['warnings']) is not list:
        _fail('Invalid source split result summary')
    manifest = result['manifest']
    expected_manifest = {k: v for k, v in to_dict(split.manifest).items() if k != 'imported_at'}
    if (
        type(manifest) is not dict
        or manifest.get('schema_version') != 1
        or manifest.get('dataset_manifest') != expected_manifest
        or manifest.get('dataset_manifest_hash') != content_hash(expected_manifest)
        or manifest.get('data_hash') != split.manifest['data_hash']
        or manifest.get('spec_hash') != content_hash(spec)
        or manifest.get('strategy') != to_dict(spec)
        or manifest.get('config_hash') != content_hash(config)
        or manifest.get('config') != to_dict(config)
        or manifest.get('source_hashes') not in producer.get('result_source_hash_variants', (producer['result_source_hashes'],))
        or manifest.get('engine_hash') != content_hash(manifest.get('source_hashes'))
        or manifest.get('cost_hash') != content_hash((config.costs,) + tuple(config.cost_schedule))
        or manifest.get('source_commit') != config.source_commit
        or manifest.get('seed') != config.seed
        or manifest.get('source_type') != split.manifest['source_type']
        or manifest.get('calendar_hash') != split.manifest.get('calendar_hash')
        or manifest.get('calendar_version') != split.manifest.get('calendar_version')
        or manifest.get('settlement_mode') != config.settlement_mode
        or manifest.get('engine_version') != 'quantlab-event-v1'
        or type(manifest.get('schema_version')) is not int
        or not _hash(manifest.get('run_hash'))
        or manifest.get('reproducibility_hash') != manifest.get('run_hash')
    ):
        _fail('Source split result manifest/binding mismatch')


def _validate_provider(provider, *, current_schema=False):
    """Only the audited fixture and compatible-provider protocols are supported."""
    if type(provider) is not dict:
        _fail('Unsupported source provider protocol')
    if provider.get('mode') == 'fixture':
        _keys(provider, ('mode', 'model', 'endpoint'))
        if provider['model'] is not None or provider['endpoint'] is not None:
            _fail('Unsupported source provider protocol')
    elif provider.get('mode') in ('manual', 'manual_unverified'):
        _fail('Manual source lacks persisted sealed exchange package and audited implementation evidence')
    elif provider.get('mode') == 'chatgpt_plan' and current_schema:
        # Full pure-data descriptor/receipt validation follows attempt validation.
        try:
            _keys(provider, ('mode', 'model', 'endpoint', 'descriptor'))
        except ValidationError as exc:
            raise SavedCandidatePoolError('Unsupported source provider descriptor', 'source_provider_provenance_invalid') from exc
    elif provider.get('mode') == 'openai_compatible':
        _keys(provider, ('mode', 'model', 'endpoint', 'limits', 'network_opt_in', 'transport_type'), ('output_mode',))
        if (
            provider.get('output_mode', 'json_object') not in ('json_object', 'registry_json_schema')
            or provider['network_opt_in'] is not True
            or any(type(provider[name]) is not str or not provider[name] for name in ('model', 'endpoint', 'transport_type'))
        ):
            _fail('Unsupported source provider protocol')
        endpoint = provider['endpoint']
        try:
            parsed = urlsplit(endpoint)
            invalid = (
                not endpoint.startswith(('https://', 'http://127.0.0.1:', 'http://localhost:', 'http://[::1]:'))
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or '?' in endpoint
                or '#' in endpoint
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint)
                or parsed.port == 0
            )
        except ValueError:
            invalid = True
        if invalid:
            _fail('Unsupported source provider protocol endpoint')
        _keys(provider['limits'], ('calls', 'tokens', 'spend', 'rate', 'tokens_per_call', 'timeout'))
        # Keep operation-specific dependencies out of module startup.
        from quantlab.value_bounds import _exact_number

        for key, low, high in (('calls', 0, 100), ('tokens', 0, 1000000), ('tokens_per_call', 1, 32768), ('timeout', 1, 120)):
            if type(provider['limits'][key]) is not int or not low <= provider['limits'][key] <= high:
                _fail('Unsupported source provider protocol')
        if _exact_number(provider['limits']['spend']) < 0 or _exact_number(provider['limits']['rate']) < 0:
            _fail('Unsupported source provider protocol')
        # The audited protocols do not persist the inherited Decimal context.
        # Do not guess default precision/rounding or admit plausible charges.
        if _exact_number(provider['limits']['rate']) != 0:
            _fail('Source provider Decimal context is not recorded for nonzero-rate receipts')
    else:
        _fail('Unsupported source provider protocol')


def validate_admission_snapshot(snapshot, pool, *, profiles, audited_producer):
    """Validate immutable plan shape only; launch still must re-admit real inputs."""
    if not isinstance(snapshot, dict):
        _fail('Saved pool needs an immutable admission snapshot')
    required = (
        'schema_version',
        'pool_origin',
        'source_campaign_ref',
        'source_campaign_id',
        'source_journal_hash',
        'source_selection_hash',
        'original_dataset_ref',
        'original_dataset_identity',
        'original_data_hash',
        'original_manifest_hash',
        'source_event_bounds',
        'first_training_timestamp',
        'source_split_hashes',
        'source_registry_identity',
        'producer',
        'provider_binding_hash',
        'provider_mode',
        'real_model_status',
        'attempts',
        'candidate_pool_hash',
        'candidate_count',
        'model_calls',
        'provenance_status',
        'snapshot_hash',
    )
    _keys(dict(snapshot), required)
    if (
        type(snapshot['schema_version']) is not int
        or snapshot['schema_version'] != 1
        or snapshot['pool_origin'] != 'saved_campaign_pool'
        or snapshot['producer'] not in profiles
        or snapshot['real_model_status'] != 'not_verified'
        or snapshot['provider_mode'] not in ('fixture', 'openai_compatible', 'chatgpt_plan')
        or (snapshot['provider_mode'] == 'chatgpt_plan' and snapshot['producer']['protocol'] == audited_producer['protocol'])
        or snapshot['provider_mode'] not in snapshot['producer'].get('provider_modes', ('fixture', 'openai_compatible', 'chatgpt_plan'))
        or type(snapshot['model_calls']) is not int
        or snapshot['model_calls'] != 0
        or snapshot['provenance_status'] != 'local_artifact_consistency_and_event_bounds_verified'
        or not 1 <= len(pool) <= 15
        or type(snapshot['candidate_count']) is not int
        or snapshot['candidate_count'] != len(pool)
        or snapshot['candidate_pool_hash'] != content_hash(pool)
        or snapshot['snapshot_hash'] != content_hash({k: v for k, v in snapshot.items() if k != 'snapshot_hash'})
    ):
        _fail('Invalid saved pool admission snapshot identity')
    for key in (
        'source_campaign_ref',
        'source_campaign_id',
        'source_journal_hash',
        'source_selection_hash',
        'original_dataset_identity',
        'original_data_hash',
        'original_manifest_hash',
        'provider_binding_hash',
        'candidate_pool_hash',
        'snapshot_hash',
    ):
        if not _hash(snapshot[key]):
            _fail('Invalid saved pool admission identity hash')
    if any(count > 3 for count in Counter(spec.family for spec in pool).values()):
        _fail('Saved pool permits at most 3 candidates per family')
    fingerprints = [candidate_fingerprint(spec) for spec in pool]
    if len(set(fingerprints)) != len(fingerprints):
        _fail('Duplicate source candidate behavioral structure is ambiguous')
    attempts = snapshot['attempts']
    if not isinstance(attempts, (tuple, list)) or not len(pool) <= len(attempts) <= 15:
        _fail('Invalid saved pool attempt provenance')
    admitted = [row for row in attempts if row.get('admitted') is True]
    if len(admitted) != len(pool):
        _fail('Saved pool admission count mismatch')
    for index, row in enumerate(admitted):
        if (
            type(row.get('pool_index')) is not int
            or row['pool_index'] != index
            or row.get('family') != pool[index].family
            or row.get('source_status') != 'evaluated'
            or row.get('strategy_hash') != content_hash(pool[index])
            or row.get('behavioral_fingerprint') != fingerprints[index]
        ):
            _fail('Saved pool order/provenance mismatch')

    identity = snapshot['source_registry_identity']
    _keys(dict(identity), ('resolved_path', 'reservation_id', 'agreement_policy'))
    if (
        identity['agreement_policy'] != 'persisted_source_reservation_matches_selected_authority'
        or not _hash(identity['reservation_id'])
        or type(identity['resolved_path']) is not str
        or not identity['resolved_path']
        or len(identity['resolved_path']) > 4096
        or '\x00' in identity['resolved_path']
        or not (PurePosixPath(identity['resolved_path']).is_absolute() or PureWindowsPath(identity['resolved_path']).is_absolute())
    ):
        _fail('Source registry snapshot identity is invalid')
    _keys(dict(snapshot['source_split_hashes']), ('train', 'validation', 'oos', 'holdout'))
    if any(not _hash(value) for value in snapshot['source_split_hashes'].values()):
        _fail('Invalid source split provenance hash')
    bounds = snapshot['source_event_bounds']
    _keys(dict(bounds), ('first_timestamp', 'last_end'))
    if not (parse_timestamp(bounds['first_timestamp']) < parse_timestamp(bounds['last_end']) < parse_timestamp(snapshot['first_training_timestamp'])):
        _fail('Every original source event end must be strictly before new first training timestamp')
    if (
        type(snapshot['original_dataset_ref']) is not str
        or not snapshot['original_dataset_ref']
        or len(snapshot['original_dataset_ref']) > 4096
        or '\x00' in snapshot['original_dataset_ref']
    ):
        _fail('Invalid original dataset reference')
    previous = {}
    for sequence, row in enumerate(attempts, 1):
        _keys(
            dict(row),
            (
                'attempt_id',
                'sequence',
                'parent_id',
                'family',
                'iteration',
                'source_status',
                'output_hash',
                'strategy_hash',
                'attempt_hash',
                'admitted',
                'reason',
            ),
            ('pool_index', 'behavioral_fingerprint', 'duplicate_of'),
        )
        if (
            type(row['sequence']) is not int
            or row['sequence'] != sequence
            or row['attempt_id'] != content_hash([snapshot['source_campaign_id'], sequence])
            or row['parent_id'] != previous.get(row['family'])
            or type(row['iteration']) is not int
            or not 0 <= row['iteration'] <= 2
            or row['source_status'] not in ('evaluated', 'failed', 'rejected', 'timed_out')
            or type(row['admitted']) is not bool
            or row['admitted'] != (row['source_status'] == 'evaluated')
            or row['reason']
            != (
                'evaluated_validated_candidate'
                if row['admitted']
                else 'source_duplicate_rejected'
                if 'duplicate_of' in row
                else 'excluded_source_attempt_' + row['source_status']
            )
            or (not row['admitted'] and 'pool_index' in row)
            or not _hash(row['attempt_hash'])
            or any(value is not None and not _hash(value) for value in (row['output_hash'], row['strategy_hash']))
        ):
            _fail('Invalid source attempt admission provenance')
        if 'duplicate_of' in row:
            if (
                snapshot['producer']['protocol'] == audited_producer['protocol']
                or row['source_status'] != 'rejected'
                or row['admitted'] is not False
                or not any(
                    prior['attempt_id'] == row['duplicate_of'] and prior.get('behavioral_fingerprint') == row.get('behavioral_fingerprint')
                    for prior in attempts[: sequence - 1]
                )
            ):
                _fail('Invalid explicitly excluded source duplicate')
        previous[row['family']] = row['attempt_id']


def _matches_chatgpt_implementation(descriptor, producer):
    """Exact reviewed tuple/target membership, independent of installed runtime."""
    if not isinstance(descriptor, dict):
        return False
    fields = ('source_sha256', 'dependency_versions', 'dependency_manifest_sha256', 'dependency_artifact_evidence')
    return any(
        all(descriptor.get(key) == variant[key] for key in fields) and descriptor.get('dependency_target') in variant['dependency_targets']
        for variant in producer.get('chatgpt_plan_implementations', ())
    )


def _validate_chatgpt_provider(provider, state, producer):
    """Pure archived descriptor/receipt checks; no auth modules or credentials."""
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research import PROMPT, _validated_provider_descriptor
    from quantlab.research_core.domain.receipts import _validated_receipt_snapshot

    _keys(provider, ('mode', 'model', 'endpoint', 'descriptor'))
    if (
        provider['mode'] != 'chatgpt_plan'
        or provider['endpoint'] != 'https://api.openai.com/v1/responses'
        or type(provider['model']) is not str
        or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', provider['model'])
    ):
        _fail('Unsupported source provider protocol')
    try:
        descriptor = _validated_provider_descriptor(provider['descriptor'])
        _keys(
            descriptor,
            (
                'source_sha256',
                'dependency_versions',
                'dependency_manifest_sha256',
                'dependency_target',
                'dependency_artifact_evidence',
                'version',
                'mode',
                'model',
                'endpoint',
                'registration',
                'campaign_id',
                'max_calls',
                'timeout_seconds',
                'stall_seconds',
                'max_request_bytes',
                'max_response_bytes',
                'max_event_bytes',
                'max_candidate_bytes',
                'max_events',
                'billing_route',
                'paid_api_fallback',
                'token_upper_bound_enforced',
                'spend_upper_bound_enforced',
                'account_credit_policy',
                'included_usage_policy_ack_required',
            ),
        )
    except ValidationError as exc:
        raise SavedCandidatePoolError('Unsupported source provider descriptor', 'source_provider_provenance_invalid') from exc
    if not _matches_chatgpt_implementation(descriptor, producer):
        _fail('Unsupported source provider protocol implementation tuple')
    if (
        descriptor['mode'] != provider['mode']
        or descriptor['model'] != provider['model']
        or descriptor['endpoint'] != provider['endpoint']
        or type(descriptor['registration']) is not str
        or not re.fullmatch('[a-f0-9]{32}', descriptor['registration'])
        or type(descriptor['campaign_id']) is not str
        or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', descriptor['campaign_id'])
        or descriptor['billing_route'] != 'chatgpt_plan'
        or descriptor['account_credit_policy'] != 'unverified_user_setting'
        or descriptor['included_usage_policy_ack_required'] is not True
        or any(descriptor[key] is not False for key in ('paid_api_fallback', 'token_upper_bound_enforced', 'spend_upper_bound_enforced'))
    ):
        _fail('Unsupported source provider protocol descriptor claims')
    for key, lower, upper in (
        ('max_calls', 0, 100),
        ('timeout_seconds', 1, 120),
        ('stall_seconds', 1, 120),
        ('max_request_bytes', 1024, 65536),
        ('max_response_bytes', 1024, 1048576),
        ('max_event_bytes', 65536, 65536),
        ('max_candidate_bytes', 16384, 16384),
        ('max_events', 2048, 2048),
    ):
        if type(descriptor[key]) is not int or not lower <= descriptor[key] <= upper:
            _fail('Unsupported source provider protocol descriptor limit')
    try:
        receipts = _validated_receipt_snapshot(
            {'version': 1, 'provider_descriptor_hash': content_hash(descriptor), 'receipts': state['provider_receipts']}, descriptor
        )
    except ValidationError as exc:
        raise SavedCandidatePoolError('Source provider receipt validation failed', 'source_provider_receipt_invalid') from exc
    attempts = state['attempts']
    if len(receipts) != len(attempts) or len(receipts) > descriptor['max_calls']:
        _fail('Source provider receipts do not match consumed attempts')
    for attempt, receipt in zip(attempts, receipts):
        context = dict(attempt['generator_context'])
        if attempt['iteration'] != 0:
            context.update(
                task='improve_previous_candidate',
                improvement_instruction=(
                    'Propose a distinct candidate in the same family using training and validation feedback only. Keep risk controls unchanged.'
                ),
            )
        request = {
            'model': provider['model'],
            'instructions': PROMPT,
            'input': [{'role': 'user', 'content': canonical_json(context)}],
            'store': False,
            'stream': True,
        }
        size = len(canonical_json(request).encode('utf-8'))
        if (
            receipt['status'] != 'completed'
            or receipt['request_hash'] != content_hash(request)
            or receipt['request_bytes'] != size
            or size > descriptor['max_request_bytes']
            or receipt['response_hash'] != attempt['output_hash']
            or not _hash(attempt['output_hash'])
            or type(receipt['received_bytes']) is not int
            or not 0 < receipt['received_bytes'] <= descriptor['max_response_bytes']
        ):
            _fail('Source provider receipt request/response evidence mismatch')


def _saved_pool_snapshot(
    state,
    source_campaign_ref,
    original_dataset_ref,
    binding,
    original_dataset,
    first_event,
    last_event,
    first_training_timestamp,
    registry_identity,
    producer,
    provider,
    provenance,
    pool,
):
    snapshot = {
        'schema_version': 1,
        'pool_origin': 'saved_campaign_pool',
        'source_campaign_ref': source_campaign_ref,
        'source_campaign_id': state['campaign_id'],
        'source_journal_hash': content_hash(state),
        'source_selection_hash': state['selection_hash'],
        'original_dataset_ref': original_dataset_ref,
        'original_dataset_identity': binding['data_hash'],
        'original_data_hash': original_dataset.manifest['data_hash'],
        'original_manifest_hash': content_hash(state['source_manifest']),
        'source_event_bounds': {'first_timestamp': first_event, 'last_end': last_event},
        'first_training_timestamp': first_training_timestamp,
        'source_split_hashes': binding['split_hashes'],
        'source_registry_identity': registry_identity,
        'producer': dict(producer),
        'provider_binding_hash': content_hash(provider),
        'provider_mode': provider['mode'],
        'real_model_status': state['real_model_status'],
        'attempts': provenance,
        'candidate_pool_hash': content_hash(pool),
        'candidate_count': len(pool),
        'model_calls': 0,
        'provenance_status': 'local_artifact_consistency_and_event_bounds_verified',
    }
    snapshot = to_dict(snapshot)
    snapshot['snapshot_hash'] = content_hash(snapshot)
    return SavedCandidatePool(tuple(pool), snapshot)
