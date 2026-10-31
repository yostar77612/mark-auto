"""Offline smoke walk_forward; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations


def _walk_forward_smoke_fixture(paths):
    """Generated engineering bars only, in a separate disposable worker workspace."""
    from dataclasses import replace
    from decimal import Decimal
    from quantlab.core import Dataset, content_hash, to_dict
    from quantlab.reporting import demo_config, save_dataset, synthetic_dataset
    from quantlab.walk_forward import build_walk_forward_plan

    data = synthetic_dataset(200)
    cycle = (-120, -80, -40, 0, 40, 80, 120, 80, 40, 0, -40, -80)
    bars = []
    for index, bar in enumerate(data.bars):
        price = Decimal(20000 + cycle[index % len(cycle)])
        bars.append(replace(bar, open=price, high=price + 2, low=price - 2, close=price, source_id='synthetic-walk-forward-smoke-v1'))
    manifest = {
        **data.manifest,
        'source_filename': 'generated walk-forward engineering smoke',
        'source_hash': content_hash(bars),
        'data_hash': content_hash(bars),
    }
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
    data = Dataset(tuple(bars), manifest, dict(data.quality))
    # Default minimum one closed lot and 10% drawdown gate are NOT relaxed.
    # Twenty train/validation evaluations plus two actual forward evaluations.
    plan = build_walk_forward_plan(
        backtest_config=demo_config(),
        train_bars=60,
        validation_bars=40,
        oos_bars=40,
        fold_count=2,
        final_holdout=(180, 200),
        max_runtime_seconds=30,
        max_bars=200,
        max_evaluations=22,
        process_start_method='spawn',
        max_ipc_bytes=65536,
    )
    paths.ensure()
    save_dataset(data, paths.state / 'dataset.json')
    return {
        'status': 'pending',
        'source_type': 'synthetic',
        'generator': 'fixture',
        'scope': 'engineering synthetic packaging smoke only; never actual research PASS or Windows-client acceptance',
        'network_used': False,
        'model_calls': 0,
        'paper_eligible': False,
        'independent_oos': False,
        'ranking_eligible': False,
        'live_status': 'disabled',
        'real_model_status': 'not_verified',
        'real_market_status': 'not_verified',
        'windows_client_status': 'not_verified',
        'fixture_data_hash': manifest['data_hash'],
        'steps': [],
    }, {'plan': to_dict(plan)}


def _check_walk_forward_smoke_result(operation, result, paths, payload, report):
    """Bind compact worker replies to source, frozen plan, and bounded real journal."""
    import hashlib
    import json
    from decimal import Decimal
    from quantlab.core import content_hash
    from quantlab.reporting import load_dataset
    from quantlab.walk_forward import read_walk_forward_state
    from desktop_app.features.walk_forward.presenter import compact_walk_forward
    from quantlab.research_core.application.walk_forward_operations import preview_walk_forward

    if type(result) is not dict or len(json.dumps(result, allow_nan=False).encode('utf-8')) > 65536:
        raise ValueError('Walk-forward smoke result exceeds compact reply bound')
    data = load_dataset(paths.state / 'dataset.json')
    if data.manifest['data_hash'] != report['fixture_data_hash'] or data.manifest['source_type'] != 'synthetic':
        raise ValueError('Walk-forward synthetic source changed')
    from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports

    expected = preview_walk_forward(data, payload['plan'], paths, inputs=_c_create_operation_ports().inputs)
    reference = expected['preview_identity']
    if operation == 'ui_walk_forward_preview':
        if result != expected or (paths.state / 'walk_forward').exists() or (paths.controls / 'holdout-registry.sqlite3').exists():
            raise ValueError('Walk-forward preview mismatch or unexpected mutation')
        return {
            'reference': reference,
            'source_identity': expected['source_identity'],
            'engine_source_hashes': expected['source_hashes'],
            'candidate_pool_hash': content_hash(expected['candidate_pool']),
            'runtime_seconds': expected['runtime_seconds'],
            'evaluation_limit': expected['evaluation_limit'],
            'final_holdout_status': expected['final_holdout_status'],
            'preview_verified': True,
        }
    if operation not in ('ui_walk_forward_run', 'ui_walk_forward_read'):
        raise ValueError('Unknown walk-forward smoke operation')
    if result.get('reference') != reference or report.get('reference') != reference:
        raise ValueError('Walk-forward smoke reference mismatch')
    folder = paths.state / 'walk_forward' / reference
    journal = folder / 'walk_forward.sqlite3'
    if journal.is_symlink() or not 0 < journal.stat().st_size <= 1048576:
        raise ValueError('Walk-forward smoke journal exceeds fixture bound')
    state = read_walk_forward_state(folder)  # Validates hashes, ledger, winner and no-winner decisions.
    summary = state['summary']
    if (
        result != compact_walk_forward(state, reference)
        or state['status'] != 'completed'
        or state['binding']['plan'] != payload['plan']
        or state['binding']['source_hashes'] != expected['source_hashes']
        or state['source_manifest'] != dict(data.manifest)
        or summary['planned_folds'] != 2
        or summary['evaluated_oos_folds'] != 2
        or summary['evaluations_reserved'] != 22
        or summary['evaluation_limit'] != 22
        or summary['model_calls'] != 0
        or summary['final_holdout_status'] != 'excluded_not_evaluated'
        or summary['evidence_mode'] != 'synthetic_validation'
        or any(summary[key] is not False for key in ('independent_oos', 'ranking_eligible', 'paper_eligible'))
    ):
        raise ValueError('Walk-forward smoke journal or result mismatch')
    folds = []
    for fold in state['folds']:
        selected = fold['selection']
        winner = fold['candidates'][selected['pool_index']]
        validation = winner['validation']['result']['metrics']
        oos = fold['oos']['result']['metrics']
        zero_trade = sum(c['validation']['result']['metrics']['trade_count'] == 0 for c in fold['candidates'])
        if (
            fold['status'] != 'evaluated'
            or len(fold['candidates']) != 5
            or selected['spec']['strategy_id'] != 'mean_reversion-v1'
            or validation['trade_count'] < 1
            or oos['trade_count'] < 1
            or Decimal(validation['total_costs']) <= 0
            or Decimal(oos['total_costs']) <= 0
            or zero_trade < 1
        ):
            raise ValueError('Walk-forward smoke requires real closed trades and excludes zero-trade candidates')
        folds.append(
            {
                'index': fold['index'],
                'winner': selected['spec']['strategy_id'],
                'validation_closed_lots': validation['trade_count'],
                'oos_closed_lots': oos['trade_count'],
                'zero_trade_candidates_excluded': zero_trade,
            }
        )
    for record in state['evaluations']:
        start, end = payload['plan']['folds'][record['fold']][record['role']]
        manifest = record['result']['manifest']
        split = manifest['dataset_manifest']['walk_forward_split']
        if (
            record['status'] != 'evaluated'
            or end > payload['plan']['final_holdout'][0]
            or split != {'fold': record['fold'], 'role': record['role'], 'start': start, 'end': end, 'warmup': 'independent_no_prior_access'}
            or manifest['source_type'] != 'synthetic'
            or manifest['data_hash'] != content_hash(data.bars[start:end])
        ):
            raise ValueError('Walk-forward smoke evaluated unexpected source or excluded final holdout')
    if any((paths.state / name).exists() for name in ('selection.json', 'active_candidate.json', 'paper.sqlite3', 'paper_policy.json', 'campaigns')):
        raise ValueError('Walk-forward smoke unexpectedly mutated AI or paper state')
    digest = hashlib.sha256(journal.read_bytes()).hexdigest()
    if operation == 'ui_walk_forward_read' and report.get('journal_sha256') != digest:
        raise ValueError('Walk-forward smoke read mutated the completed journal')
    return {
        'journal_reloaded': True,
        'journal_sha256': digest,
        'state_hash': state['state_hash'],
        'summary': summary,
        'folds': folds,
        'compact_result_bytes': len(json.dumps(result).encode('utf-8')),
        'journal_bytes': journal.stat().st_size,
        'read_verified': operation == 'ui_walk_forward_read',
    }
