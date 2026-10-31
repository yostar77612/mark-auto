"""Bounded desktop operation grammar and IPC constants."""

DEFAULT_WORKER_STORAGE_FACTORY = 'desktop_app.research_bootstrap:create_worker_storage'
DEFAULT_JOB_PORT_FACTORY = 'desktop_app.research_bootstrap:create_job_ports'
DEFAULT_OPERATION_REGISTRAR = 'desktop_app.shell.main_window:execute_ui_operation'
MAX_JSON = 1024 * 1024

UI_OPERATIONS = frozenset(
    {
        'ui_demo',
        'ui_import',
        'ui_refresh',
        'ui_market_refresh',
        'ui_chatgpt_auth',
        'ui_chatgpt_usage',
        'ui_chatgpt_reconcile',
        'ui_backtest',
        'ui_campaign',
        'ui_walk_forward_preview',
        'ui_walk_forward_run',
        'ui_walk_forward_read',
        'ui_walk_forward_reconcile',
        'ui_analysis_preview',
        'ui_analysis_run',
        'ui_analysis_read',
        'ui_analysis_reconcile',
        'ui_compare',
        'ui_select',
        'ui_disable',
        'ui_paper_snapshot',
        'ui_paper_reconcile',
        'ui_paper_kill',
        'ui_paper_replay',
        'ui_paper_submit',
        'ui_paper_cancel',
        'ui_paper_cancel_all',
        'ui_capital_scenario',
        'ui_idea_research',
        'ui_idea_adopt',
        'ui_backup_create',
        'ui_backup_restore',
    }
)
OPERATIONS = UI_OPERATIONS | {'demo', 'backtest', 'campaign'}
ANALYSIS_OPERATIONS = frozenset({'ui_analysis_preview', 'ui_analysis_run', 'ui_analysis_read', 'ui_analysis_reconcile'})
WALK_FORWARD_OPERATIONS = frozenset(
    {
        'ui_walk_forward_preview',
        'ui_walk_forward_run',
        'ui_walk_forward_read',
        'ui_walk_forward_reconcile',
    }
)
