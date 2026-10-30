"""Fixed operation names and admission rules."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from quantlab.core import ValidationError
from quantlab.research_core.application.analysis_operations import (
    _handle_ui_analysis_preview,
    _handle_ui_analysis_read,
    _handle_ui_analysis_reconcile,
    _handle_ui_analysis_run,
)
from quantlab.research_core.application.ui_operations.assistant import _handle_ui_chatgpt_auth, _handle_ui_chatgpt_reconcile, _handle_ui_chatgpt_usage
from quantlab.research_core.application.ui_operations.backup import _handle_ui_backup_create, _handle_ui_backup_restore
from quantlab.research_core.application.ui_operations.data import (
    _handle_ui_compare,
    _handle_ui_demo,
    _handle_ui_disable,
    _handle_ui_import,
    _handle_ui_refresh,
    _handle_ui_select,
)
from quantlab.research_core.application.ui_operations.derived import (
    _handle_ui_capital_scenario,
    _handle_ui_walk_forward_preview,
    _handle_ui_walk_forward_read,
    _handle_ui_walk_forward_reconcile,
    _handle_ui_walk_forward_run,
)
from quantlab.research_core.application.ui_operations.idea import _handle_ui_idea_adopt, _handle_ui_idea_research
from quantlab.research_core.application.ui_operations.market import _handle_ui_market_refresh
from quantlab.research_core.application.paper_operations import (
    _handle_ui_paper_cancel,
    _handle_ui_paper_cancel_all,
    _handle_ui_paper_kill,
    _handle_ui_paper_reconcile,
    _handle_ui_paper_replay,
    _handle_ui_paper_snapshot,
    _handle_ui_paper_submit,
)
from quantlab.research_core.application.research_operations import _handle_ui_backtest, _handle_ui_campaign

UI_OPERATIONS = frozenset(
    (
        'ui_' + op
        for op in (
            'analysis_preview',
            'analysis_run',
            'analysis_read',
            'analysis_reconcile',
            'walk_forward_preview',
            'walk_forward_run',
            'walk_forward_read',
            'walk_forward_reconcile',
            'demo',
            'import',
            'refresh',
            'market_refresh',
            'chatgpt_auth',
            'chatgpt_usage',
            'chatgpt_reconcile',
            'backtest',
            'campaign',
            'compare',
            'select',
            'disable',
            'paper_snapshot',
            'paper_reconcile',
            'paper_kill',
            'paper_replay',
            'paper_submit',
            'paper_cancel',
            'paper_cancel_all',
            'capital_scenario',
            'idea_research',
            'idea_adopt',
            'backup_create',
            'backup_restore',
        )
    )
)

_UI_OPERATION_HANDLERS = {
    'ui_capital_scenario': _handle_ui_capital_scenario,
    'ui_idea_research': _handle_ui_idea_research,
    'ui_idea_adopt': _handle_ui_idea_adopt,
    'ui_analysis_preview': _handle_ui_analysis_preview,
    'ui_analysis_read': _handle_ui_analysis_read,
    'ui_analysis_reconcile': _handle_ui_analysis_reconcile,
    'ui_analysis_run': _handle_ui_analysis_run,
    'ui_backtest': _handle_ui_backtest,
    'ui_backup_create': _handle_ui_backup_create,
    'ui_backup_restore': _handle_ui_backup_restore,
    'ui_campaign': _handle_ui_campaign,
    'ui_chatgpt_auth': _handle_ui_chatgpt_auth,
    'ui_chatgpt_reconcile': _handle_ui_chatgpt_reconcile,
    'ui_chatgpt_usage': _handle_ui_chatgpt_usage,
    'ui_compare': _handle_ui_compare,
    'ui_demo': _handle_ui_demo,
    'ui_disable': _handle_ui_disable,
    'ui_import': _handle_ui_import,
    'ui_market_refresh': _handle_ui_market_refresh,
    'ui_paper_cancel': _handle_ui_paper_cancel,
    'ui_paper_cancel_all': _handle_ui_paper_cancel_all,
    'ui_paper_kill': _handle_ui_paper_kill,
    'ui_paper_reconcile': _handle_ui_paper_reconcile,
    'ui_paper_replay': _handle_ui_paper_replay,
    'ui_paper_snapshot': _handle_ui_paper_snapshot,
    'ui_paper_submit': _handle_ui_paper_submit,
    'ui_refresh': _handle_ui_refresh,
    'ui_select': _handle_ui_select,
    'ui_walk_forward_preview': _handle_ui_walk_forward_preview,
    'ui_walk_forward_read': _handle_ui_walk_forward_read,
    'ui_walk_forward_reconcile': _handle_ui_walk_forward_reconcile,
    'ui_walk_forward_run': _handle_ui_walk_forward_run,
}


def prepare_operation(ports: UiOperationPorts, operation, payload, paths, *, emit=None, descendants_stopped=False):
    """Allowlisted process-worker adapter; no Qt objects are created here."""
    if operation not in UI_OPERATIONS:
        raise ValidationError(ports.text('ui.execute_ui_operation.unknown_operation'))
    if operation == 'ui_capital_scenario' and type(payload) is not dict:
        raise ValidationError(ports.text('capital.invalid'))
    if operation == 'ui_campaign' and (
        not isinstance(payload.get('provider'), dict) or payload['provider'].get('mode') not in ('fixture', 'manual', 'chatgpt_plan')
    ):
        raise ValidationError(ports.text('ui.execute_ui_operation.subscription_only'))
    root = ports.files._root(paths)
    if payload.get('synthetic_quick_start') is True:
        if operation not in ('ui_demo', 'ui_backtest'):
            raise ValidationError(ports.text('ui.execute_ui_operation.unknown_operation'))
        root = root / 'synthetic-quick-start'
        ports.files.mkdir(root, exist_ok=True)
        if operation == 'ui_backtest':
            payload = {**payload, 'dataset': str(root / 'synthetic-demo-dataset.json')}
    return (payload, root)
