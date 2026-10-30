"""Saved campaign evidence; no provider calls or credential access."""

from __future__ import annotations
from collections import Counter
from decimal import Decimal, localcontext
from quantlab.core import ValidationError, canonical_json, content_hash, to_dict
from quantlab.research import _keys, candidate_fingerprint, validate_dsl, PARAMETER_CONTRACTS, training_summary
from quantlab.research_core.domain.saved_pool import SavedCandidatePoolError, _hash, _fail
from quantlab.research_core.application.saved_pool_validation import _check_result


def _compatible_request(provider, original_context, iteration, current_schema):
    """Pure request reconstruction from the exact two audited source protocols."""
    # Keep operation-specific dependencies out of module startup.
    from quantlab.research import PROMPT, registry_json_schema

    context = dict(original_context)
    if current_schema and iteration:
        context.update(
            task='improve_previous_candidate',
            improvement_instruction=(
                'Use previous training and validation feedback to propose a distinct candidate in the same family. '
                'Change parameters or rules, not just strategy_id. Keep risk controls unchanged. '
                'Do not claim performance improved before the new candidate is evaluated.'
            ),
        )
    response_format = {'type': 'json_object'}
    if provider.get('output_mode', 'json_object') == 'registry_json_schema':
        response_format = {
            'type': 'json_schema',
            'json_schema': {'name': 'quantlab_registry_candidate', 'strict': True, 'schema': registry_json_schema(context['family'])},
        }
        context['output_contract'] = (
            'registry_json_schema mode: choose your own integer parameter values, including basis points. '
            'Return rules={} to use the requested built-in family. Do not generate an AST. '
            'Choose lookbacks much shorter than training bar count; trend fast must be below slow.'
        )
    suffix = (
        '\nBefore returning JSON, compare your chosen parameters with previous.output.parameters. '
        'At least one parameter value must differ. A new strategy_id alone is invalid. '
        'Choose the changed value yourself within the same schema; do not alter risk controls.'
        if current_schema and context.get('task') == 'improve_previous_candidate'
        else ''
    )
    return {
        'model': provider['model'],
        'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': canonical_json(context) + suffix}],
        'max_tokens': provider['limits']['tokens_per_call'],
        'response_format': response_format,
    }


def _validate_legacy_receipts(provider, state, *, current_schema=False):
    """Validate bounded observed receipts, never infer response authenticity.

    Compatible response hashes cover unavailable full response envelopes. They
    cannot be compared to candidate output hashes. Failed child generations may
    consume provider budget without returning a receipt or candidate.
    """
    receipts = state['provider_receipts']
    if provider['mode'] == 'fixture':
        if type(receipts) is not list or receipts:
            _fail('Source provider receipts must be empty for fixtures')
        return
    returned = [attempt for attempt in state['attempts'] if attempt['output_hash'] is not None]
    limits = provider['limits']
    if type(receipts) is not list or len(receipts) != len(returned) or len(receipts) > limits['calls']:
        _fail('Source provider receipts do not match returned generations')
    # Keep operation-specific dependencies out of module startup.
    from quantlab.value_bounds import _exact_number

    tokens, spends = 0, []
    for receipt, attempt in zip(receipts, returned):
        try:
            _keys(receipt, ('response_hash', 'reserved_tokens', 'reserved_spend', 'status'))
            if (
                not _hash(receipt['response_hash'])
                or receipt['status'] != 'transport_returned_not_verified'
                or type(receipt['reserved_tokens']) is not int
                or not limits['tokens_per_call'] < receipt['reserved_tokens'] <= limits['tokens']
            ):
                _fail('Source provider receipt shape/status/resource mismatch')
            request = _compatible_request(provider, attempt['generator_context'], attempt['iteration'], current_schema)
            if receipt['reserved_tokens'] != len(canonical_json(request).encode('utf-8')) + limits['tokens_per_call']:
                _fail('Source provider receipt token reservation disagrees with audited request')
            spend = _exact_number(receipt['reserved_spend'])
            if not 0 <= spend <= _exact_number(limits['spend']) or (_exact_number(limits['rate']) == 0 and spend != 0):
                _fail('Source provider receipt spend exceeds resource bounds')
        except ValidationError as exc:
            raise SavedCandidatePoolError('Invalid compatible source provider receipt', 'source_provider_receipt_invalid') from exc
        tokens += receipt['reserved_tokens']
        spends.append(spend)
    # Exact finite addition, independent of caller Decimal context.
    with localcontext() as context:
        context.prec = 160
        total_spend = sum(spends, Decimal(0))
    if tokens > limits['tokens'] or total_spend > _exact_number(limits['spend']):
        _fail('Source provider receipts exceed aggregate resource limits')


def _admit_source_attempt(
    index, attempt, schedule, state, previous, by_id, provider, binding, config, splits, current_schema, seen, pool, provenance, producer, _bounded_value
):
    _keys(
        attempt,
        (
            'attempt_id',
            'sequence',
            'parent_id',
            'family',
            'iteration',
            'status',
            'provider',
            'prompt_template_hash',
            'split_hashes',
            'output',
            'output_hash',
            'strategy_hash',
            'metrics',
            'cost',
            'elapsed_seconds',
            'warnings',
        ),
        ('spec', 'generator_context') + (('candidate_fingerprint', 'duplicate_of') if current_schema else ()),
    )
    family, iteration = schedule[index - 1]
    if (
        type(attempt['sequence']) is not int
        or attempt['sequence'] != index
        or type(attempt['iteration']) is not int
        or (attempt['family'], attempt['iteration']) != (family, iteration)
        or attempt['attempt_id'] != content_hash([state['campaign_id'], index])
        or attempt['parent_id'] != previous.get(family)
        or attempt['provider'] != provider
        or attempt['prompt_template_hash'] != binding['prompt_template_hash']
        or attempt['split_hashes'] != {k: binding['split_hashes'][k] for k in ('train', 'validation')}
        or attempt['status'] not in ('evaluated', 'rejected', 'failed', 'timed_out')
    ):
        _fail('Invalid source attempt sequence, parent, status or provenance')
    parent = by_id.get(previous.get(family))
    expected_context = {
        'family': family,
        'iteration': iteration,
        'seed': config['seed'],
        'parameter_contract': PARAMETER_CONTRACTS[family],
        'training': training_summary(splits['train']),
        'validation': {'bar_count': len(splits['validation'].bars), 'hash': content_hash(splits['validation'].bars)},
        'previous': {'output': parent['output'], 'metrics': {k: v['metrics'] for k, v in parent['metrics'].items()}, 'status': parent['status']}
        if parent
        else None,
    }
    if attempt.get('generator_context') != expected_context:
        _fail('Source generation context disagrees with exact prior source splits/attempt')
    previous[family] = attempt['attempt_id']
    by_id[attempt['attempt_id']] = attempt
    output = attempt['output']
    if (attempt['output_hash'] is None and output is not None) or (attempt['output_hash'] is not None and attempt['output_hash'] != content_hash(output)):
        _fail('Source attempt output hash mismatch')
    spec = None
    explicit_duplicate = False
    if 'spec' in attempt or attempt['status'] == 'evaluated':
        _bounded_value(output)
        spec = validate_dsl(output)
        if to_dict(spec) != attempt.get('spec') or spec.family != family or attempt['strategy_hash'] != content_hash(spec):
            _fail('Source original output/validated spec/strategy hash mismatch')
        fingerprint = candidate_fingerprint(spec)
        if current_schema and attempt.get('candidate_fingerprint') != fingerprint:
            _fail('Source candidate fingerprint disagrees with validated behavior')
        if fingerprint in seen:
            explicit_duplicate = (
                current_schema
                and attempt['status'] == 'rejected'
                and attempt.get('duplicate_of') == seen[fingerprint]
                and 'duplicate_candidate_not_retested' in attempt['warnings']
                and attempt['metrics'] == {}
            )
            if not explicit_duplicate:
                _fail('Duplicate source candidate behavioral structure is ambiguous')
        elif 'duplicate_of' in attempt:
            _fail('Source duplicate rejection does not match an earlier candidate')
        else:
            seen[fingerprint] = attempt['attempt_id']
    elif attempt['strategy_hash'] is not None or 'candidate_fingerprint' in attempt or 'duplicate_of' in attempt:
        _fail('Source strategy hash has no validated spec')
    if type(attempt['metrics']) is not dict or set(attempt['metrics']) - {'train', 'validation'}:
        _fail('Invalid source attempt split metrics')
    if attempt['status'] == 'evaluated' and set(attempt['metrics']) != {'train', 'validation'}:
        _fail('Evaluated source attempt is missing split results')
    for role, summary in attempt['metrics'].items():
        if spec is None:
            _fail('Source split result has no validated spec')
        _check_result(summary, splits[role], spec, config['backtest_config'], producer)
    admitted = attempt['status'] == 'evaluated'
    row = {
        'attempt_id': attempt['attempt_id'],
        'sequence': index,
        'parent_id': attempt['parent_id'],
        'family': family,
        'iteration': iteration,
        'source_status': attempt['status'],
        'output_hash': attempt['output_hash'],
        'strategy_hash': attempt['strategy_hash'],
        'attempt_hash': content_hash(attempt),
        'admitted': admitted,
        'reason': (
            'evaluated_validated_candidate'
            if admitted
            else 'source_duplicate_rejected'
            if explicit_duplicate
            else 'excluded_source_attempt_' + attempt['status']
        ),
    }
    if explicit_duplicate:
        row['duplicate_of'] = attempt['duplicate_of']
    if spec is not None:
        row['behavioral_fingerprint'] = candidate_fingerprint(spec)
    if admitted:
        row['pool_index'] = len(pool)
        pool.append(spec)
    provenance.append(row)


def _collect_source_attempts(state, config, splits, current_schema, provider, binding, producer, _bounded_value):
    attempts = state['attempts']
    if type(attempts) is not list or not 1 <= len(attempts) <= min(15, config['max_trials']):
        _fail('Source must contain 1..15 bounded attempts')
    schedule = [(family, iteration) for iteration in range(config['max_improvements'] + 1) for family in config['families']]
    previous, seen, pool, provenance, by_id = {}, {}, [], [], {}
    for index, attempt in enumerate(attempts, 1):
        _admit_source_attempt(
            index,
            attempt,
            schedule,
            state,
            previous,
            by_id,
            provider,
            binding,
            config,
            splits,
            current_schema,
            seen,
            pool,
            provenance,
            producer,
            _bounded_value,
        )
    if not pool:
        _fail('No evaluated candidates remain in the saved source')
    if len(pool) > 15 or any(count > 3 for count in Counter(spec.family for spec in pool).values()):
        _fail('Saved pool requires 1..15 evaluated candidates and at most 3 per family')
    return pool, provenance, by_id


def _validate_source_selection(state, config, by_id, splits, producer):
    selected = state['selected']
    if type(selected) is not list or len(selected) > len(config['families']):
        _fail('Invalid source selection evidence')
    selected_families = []
    for candidate in selected:
        _keys(candidate, ('attempt_id', 'strategy_hash', 'spec', 'validation'))
        attempt = by_id.get(candidate['attempt_id'])
        if (
            attempt is None
            or attempt['status'] != 'evaluated'
            or any(candidate[key] != attempt[key] for key in ('strategy_hash', 'spec'))
            or candidate['validation'] != attempt['metrics']['validation']
        ):
            _fail('Source selection does not match its evaluated attempt')
        selected_families.append(attempt['family'])
    if selected_families != [family for family in config['families'] if family in selected_families]:
        _fail('Duplicate or unordered source selection')
    _keys(state['evaluations'], ('oos', 'holdout'))
    for role in ('oos', 'holdout'):
        records = state['evaluations'][role]
        if type(records) is not list or len(records) != len(selected):
            _fail('Incomplete source forward evaluation evidence')
        for record, candidate in zip(records, selected):
            _keys(record, ('strategy_hash', 'status', 'metrics', 'warnings', 'result_hash', 'manifest'))
            if record['status'] != 'evaluated' or record['strategy_hash'] != candidate['strategy_hash']:
                _fail('Invalid source forward evaluation identity')
            _check_result(
                {k: v for k, v in record.items() if k not in ('strategy_hash', 'status')},
                splits[role],
                validate_dsl(candidate['spec']),
                config['backtest_config'],
                producer,
            )
    if selected:
        if (
            state['holdout_consumed'] is not True
            or state['holdout_status'] != 'reserved_consumed'
            or state.get('holdout_selection_hash') != state['selection_hash']
            or type(state.get('holdout_registry')) is not dict
            or state['holdout_registry'].get('status') != 'reserved_consumed'
            or state['holdout_registry'].get('holdout_hash') != content_hash(splits['holdout'].bars)
        ):
            _fail('Invalid source consumed holdout evidence')
    elif (
        state['holdout_consumed'] is not False or state['holdout_status'] != 'not_accessed' or 'holdout_registry' in state or 'holdout_selection_hash' in state
    ):
        _fail('Unexpected source holdout evidence')
