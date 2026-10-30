from pathlib import Path


import re

from quantlab.core import ValidationError, content_hash, to_dict

from quantlab.walk_forward import (
    _validate_source,
    walk_forward_plan_from_dict,
    walk_forward_binding,
    planned_evaluations,
    run_walk_forward,
    read_walk_forward_state,
    reconcile_interrupted_walk_forward,
)

from quantlab.research_core.application.walk_forward_projection import compact_walk_forward


def _folder(paths, reference):
    if type(reference) is not str or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValidationError('Walk-forward reference must be an immutable SHA-256 identity')
    state_root = Path(paths.state).resolve()
    base = (state_root / 'walk_forward').resolve()
    if not base.is_relative_to(state_root):
        raise ValidationError('Walk-forward state directory escapes the workspace')
    folder = base / reference
    if not folder.resolve().is_relative_to(base):
        raise ValidationError('Walk-forward reference escapes its state directory')
    return folder


def _binding(data, plan, registry):
    return walk_forward_binding(data, plan, registry)


def source_campaign_folder(paths, reference):
    if type(reference) is not str or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValidationError('Source campaign reference must be an immutable SHA-256 identity')
    root = Path(paths.state).resolve()
    base = (root / 'campaigns').resolve()
    folder = base / reference
    if not base.is_relative_to(root) or not folder.resolve().is_relative_to(base):
        raise ValidationError('Source campaign reference escapes the workspace')
    return folder


def _prepare_saved_plan(data, plan_payload, paths, saved_source, registry):
    from quantlab.research_core.application.job_requests import validate_walk_forward_request
    from quantlab.saved_candidate_pool import admit_saved_campaign_pool
    from quantlab.research_core.adapters.saved_pool_source import load_original_dataset

    chronology = validate_walk_forward_request(plan_payload, saved_source)
    _validate_source(data, chronology)
    folder = source_campaign_folder(paths, saved_source['campaign_reference'])
    path = Path(saved_source['original_dataset']['path'])
    original = load_original_dataset(path)
    admitted = admit_saved_campaign_pool(
        source_campaign_dir=folder,
        source_campaign_ref=saved_source['campaign_reference'],
        original_dataset=original,
        original_dataset_ref=str(path),
        first_training_timestamp=data.bars[chronology.folds[0].train[0]].timestamp,
        authoritative_registry_path=registry,
    )
    pool, admission = (admitted.candidate_pool, to_dict(admitted.admission))
    bound = len(chronology.folds) * (2 * len(pool) + 1)
    if plan_payload['max_evaluations'] > bound:
        return (
            None,
            {
                'admission_status': 'rejected',
                'reason_code': 'evaluation_budget_exceeds_pool_bound',
                'candidate_count': len(pool),
                'fold_count': len(chronology.folds),
                'evaluation_limit': plan_payload['max_evaluations'],
                'planned_evaluations_upper_bound': bound,
                'pool_origin': 'saved_campaign_pool',
                'pool_admission': admission,
                'candidate_pool': [to_dict(spec) for spec in pool],
                'model_calls': 0,
            },
        )
    plan = walk_forward_plan_from_dict({**plan_payload, 'candidate_pool': [to_dict(spec) for spec in pool], 'pool_admission': admission})
    return (plan, None)


def _range(data, bounds):
    start, end = bounds
    return {
        'start': start,
        'end': end,
        'start_time': data.bars[start].timestamp.isoformat(),
        'end_time': data.bars[end - 1].end.isoformat(),
        'bars': end - start,
    }


def preview_walk_forward(data, plan_payload, paths, saved_source=None):
    from quantlab.research_core.application.walk_forward_inputs import research_controls
    from quantlab.research_core.application.job_requests import validate_walk_forward_request

    validate_walk_forward_request(plan_payload, saved_source)
    registry = research_controls(paths) / 'holdout-registry.sqlite3'
    if saved_source is None:
        plan = walk_forward_plan_from_dict(plan_payload)
    else:
        from quantlab.research_core.domain.saved_pool import SavedCandidatePoolError

        try:
            plan, rejection = _prepare_saved_plan(data, plan_payload, paths, saved_source, registry)
        except SavedCandidatePoolError as exc:
            return {'admission_status': 'rejected', 'reason_code': exc.reason_code, 'pool_origin': 'saved_campaign_pool', 'model_calls': 0}
        if rejection is not None:
            return rejection
    _validate_source(data, plan)
    binding = _binding(data, plan, registry)
    replay = plan.evidence_mode == 'historical_replay'
    return {
        'preview_identity': content_hash(binding),
        'plan': to_dict(plan),
        'source_identity': binding['source_identity'],
        'source_data_hash': binding['source_data_hash'],
        'source_type': data.manifest['source_type'],
        'source_hashes': binding['source_hashes'],
        'registry_identity': binding['registry_identity'],
        'bar_count': len(data.bars),
        'folds': [{'index': i, **{role: _range(data, getattr(fold, role)) for role in ('train', 'validation', 'oos')}} for i, fold in enumerate(plan.folds)],
        'final_holdout': _range(data, plan.final_holdout),
        'final_holdout_status': 'excluded_not_evaluated',
        'candidate_pool': [to_dict(spec) for spec in plan.candidate_pool],
        'ranking': to_dict(plan.ranking),
        'pool_origin': plan.pool_origin,
        'pool_admission': to_dict(plan.pool_admission) if plan.pool_admission is not None else None,
        'candidate_count': len(plan.candidate_pool),
        'admission_status': 'admitted',
        'evaluation_limit': plan.max_evaluations,
        'planned_evaluations_upper_bound': planned_evaluations(plan),
        'runtime_seconds': plan.max_runtime_seconds,
        'model_calls': 0,
        'evidence_mode': plan.evidence_mode,
        'exposure_status': 'unverified' if replay else 'synthetic_not_market_evidence',
        'independent_oos': False,
        'ranking_eligible': False,
        'paper_eligible': False,
    }


def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False, dataset_loader=None):
    from quantlab.research_core.application.walk_forward_inputs import research_controls

    if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run'):
        required = {'plan'} if operation.endswith('_preview') else {'plan', 'preview_identity'}
        if 'saved_source' in payload:
            if not isinstance(payload.get('plan'), dict) or payload['plan'].get('pool_origin') != 'saved_campaign_pool':
                raise ValidationError('Built-in and saved pools cannot be mixed')
            required = required | {'saved_source'}
        if set(payload) != required:
            raise ValidationError('Unsupported walk-forward request fields')
        if dataset_loader is None:
            raise ValidationError('Dataset input port required')
        data = dataset_loader(Path(paths.state), {})
        preview = preview_walk_forward(data, payload['plan'], paths, payload.get('saved_source'))
        if operation.endswith('_preview'):
            return preview
        if preview.get('admission_status') == 'rejected':
            raise ValidationError('Saved pool admission changed or failed; preview again before starting')
        identity = preview['preview_identity']
        if payload['preview_identity'] != identity:
            raise ValidationError('Walk-forward source/config/pool changed; preview again before starting')
        output = _folder(paths, identity)
        if (output / 'walk_forward.sqlite3').exists():
            return compact_walk_forward(read_walk_forward_state(output), identity)
        source_options = {}
        if payload.get('saved_source') is not None:
            from quantlab.research_core.adapters.saved_pool_source import load_original_dataset

            source = payload['saved_source']
            source_options = {
                'source_campaign_dir': source_campaign_folder(paths, source['campaign_reference']),
                'original_dataset': load_original_dataset(Path(source['original_dataset']['path'])),
            }
        paths.require_walk_forward_wal()
        state = run_walk_forward(
            data,
            plan=walk_forward_plan_from_dict(preview['plan']),
            output_dir=output,
            holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3',
            **source_options,
        )
        return compact_walk_forward(state, identity)
    if operation == 'ui_walk_forward_read':
        if set(payload) != {'reference'}:
            raise ValidationError('Unsupported walk-forward read fields')
        return compact_walk_forward(read_walk_forward_state(_folder(paths, payload['reference'])), payload['reference'])
    if operation == 'ui_walk_forward_reconcile':
        if set(payload) != {'reference', 'stopped_job_id'} or descendants_stopped is not True:
            raise ValidationError('Exact stopped walk-forward subtree proof required')
        folder = _folder(paths, payload['reference'])
        if not (folder / 'walk_forward.sqlite3').exists():
            return {'reference': payload['reference'], 'status': 'stopped_before_journal', 'display_status': 'stopped_before_journal'}
        return compact_walk_forward(reconcile_interrupted_walk_forward(output_dir=folder, descendants_stopped=True), payload['reference'])
    raise ValidationError('Unsupported walk-forward operation')
