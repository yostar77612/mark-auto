from desktop_app.strings.catalog import ui_text
from desktop_app.features.walk_forward.presenter import FAMILY_NAMES, status_label


def result_rows(result):
    rows = []
    for fold in result.get('folds', []):
        for candidate in fold['candidates']:
            winner = (
                ui_text('walk_forward.result_rows.candidate_number').format(str(fold['winner_pool_index'] + 1))
                if fold.get('winner_pool_index') is not None
                else ui_text('walk_forward.result_rows.selected')
                if fold['winner']
                else ui_text('walk_forward.result_rows.none')
            )
            row = {
                ui_text('walk_forward.result_rows.fold'): fold['index'] + 1,
                ui_text('walk_forward.result_rows.status'): status_label(fold['status']),
                ui_text('walk_forward.result_rows.winner'): winner,
                ui_text('walk_forward.result_rows.candidate_index'): candidate['pool_index'] + 1,
                ui_text('walk_forward.result_rows.candidate'): FAMILY_NAMES.get(candidate.get('family'), ui_text('walk_forward.result_rows.saved_candidate')),
            }
            for role, label in (('train', ui_text('walk_forward.result_rows.training')), ('validation', ui_text('walk_forward.result_rows.validation'))):
                score = candidate[role]
                row[ui_text('walk_forward.result_rows.segment_status').format(label)] = status_label(score['status'])
                for key, caption in (
                    ('net_pnl', ui_text('walk_forward.result_rows.net_pnl')),
                    ('trade_count', ui_text('walk_forward.result_rows.closed_lots')),
                    ('max_drawdown_pct', ui_text('walk_forward.result_rows.max_drawdown_ratio')),
                ):
                    row[label + caption] = score['metrics'].get(key)
            if candidate.get('strategy_hash') is not None and candidate['strategy_hash'] == fold.get('winner_hash'):
                row[ui_text('walk_forward.result_rows.forward_status')] = status_label(fold['oos']['status'])
                names = {
                    'net_pnl': ui_text('walk_forward.result_rows.net_pnl'),
                    'trade_count': ui_text('walk_forward.result_rows.closed_lots'),
                    'max_drawdown_pct': ui_text('walk_forward.result_rows.max_drawdown_ratio'),
                    'max_drawdown': ui_text('walk_forward.result_rows.max_drawdown'),
                    'total_costs': ui_text('walk_forward.result_rows.total_cost'),
                    'realized_gross_pnl': ui_text('walk_forward.result_rows.realized_gross_pnl'),
                    'unrealized_pnl': ui_text('walk_forward.result_rows.unrealized_pnl'),
                    'return': ui_text('walk_forward.result_rows.return_ratio'),
                    'open_position': ui_text('walk_forward.result_rows.open_quantity'),
                }
                for key, value in fold['oos']['metrics'].items():
                    row[ui_text('walk_forward.result_rows.forward_fold').format(names[key])] = value
            rows.append(row)
        if not fold['candidates']:
            rows.append(
                {
                    ui_text('walk_forward.result_rows.fold'): fold['index'] + 1,
                    ui_text('walk_forward.result_rows.status'): status_label(fold['status']),
                    ui_text('walk_forward.result_rows.winner'): ui_text('walk_forward.result_rows.none'),
                }
            )
    return rows
