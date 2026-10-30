from quantlab.core import ValidationError
from quantlab import significance as _significance
from quantlab import verdict as _verdict

METRICS = ('net_pnl', 'trade_count', 'max_drawdown_pct', 'max_drawdown', 'total_costs', 'realized_gross_pnl', 'unrealized_pnl', 'return', 'open_position')


def _score(record):
    record = record or {}
    metrics = record.get('result', {}).get('metrics', {})
    return {'status': record.get('status', 'not_evaluated'), 'metrics': {key: metrics[key] for key in METRICS if key in metrics}}


def compact_walk_forward(state, reference):
    """Bounded IPC projection, never the potentially 16-MiB journal payload."""
    if state['experiment_id'] != reference:
        raise ValidationError('Walk-forward journal reference does not match its binding')
    plan = state['binding']['plan']
    pool = plan['candidate_pool']
    folds = []
    for fold in state['folds']:
        selection = fold['selection']
        folds.append(
            {
                'index': fold['index'],
                'status': fold['status'],
                'winner': selection['spec']['strategy_id'] if selection else None,
                'winner_hash': selection['strategy_hash'] if selection else None,
                'winner_pool_index': selection['pool_index'] if selection else None,
                'candidates': [
                    {
                        'strategy_id': pool[c['pool_index']]['strategy_id'],
                        'family': pool[c['pool_index']]['family'],
                        'pool_index': c['pool_index'],
                        'strategy_hash': c['strategy_hash'],
                        'train': _score(c.get('train')),
                        'validation': _score(c.get('validation')),
                    }
                    for c in fold['candidates']
                ],
                'oos': _score(fold.get('oos')),
            }
        )
    return {
        'reference': reference,
        'status': state['status'],
        'display_status': 'running_or_interrupted_no_stop_proof' if state['status'] == 'running' else state['status'],
        'source_identity': state['binding']['source_identity'],
        'source_type': state['source_manifest']['source_type'],
        'ranking': plan['ranking'],
        'pool_origin': plan.get('pool_origin', 'exact_builtin_pool'),
        'pool_admission': plan.get('pool_admission'),
        'summary': state['summary'],
        'folds': folds,
        'elapsed_seconds': state['elapsed_seconds'],
        'journal': 'walk_forward/' + reference + '/walk_forward.sqlite3',
        'oos_statistics': oos_statistics_data(state),
    }


def oos_statistics_data(state):
    """Fixed bounded statistics; daily returns never enter IPC."""
    if state.get('status') != 'completed':
        return {'available': False}
    merged = _significance.merge_oos_daily_returns(state)
    result = {'available': True, 'reason': merged['reason'], 'skipped_folds': merged.get('skipped_folds', 0)}
    if merged['reason']:
        return result
    stats = _significance.mean_positive_test(merged['returns'])
    required = _significance.required_observations(merged['returns'])
    result.update(stats=stats, required=required, decline=_significance.oos_decline_test(state), verdict=_verdict.judge(stats, required, merged['returns'], ()))
    if 'decline' in result:
        result['decline'] = {key: value for key, value in result['decline'].items() if not key.startswith('p_value_increase')}
    return result
