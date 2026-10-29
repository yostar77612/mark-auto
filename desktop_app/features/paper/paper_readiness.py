"""Read-only preparation hints; authoritative paper gates stay in the worker."""

from desktop_app.strings.catalog import ui_text
from quantlab.desktop_feedback import stop_presentation
from quantlab.reporting import load_selection


def refresh_readiness(page):
    if not hasattr(page, 'readiness_selection'):
        return
    path = page.root / 'selection.json'
    selected = False
    if path.exists():
        try:
            selection = load_selection(path)
            page.readiness_selection.setText(ui_text('redesign.paper.selected').format(selection['strategy_hash'][:16]))
            selected = True
        except (OSError, ValueError, TypeError, KeyError):
            page.readiness_selection.setText(ui_text('redesign.paper.selection_unreadable'))
    else:
        page.readiness_selection.setText(ui_text('redesign.paper.no_selection'))
    account = getattr(page, '_stop_account', {}) or {}
    reconciled = bool(account.get('account_id')) and account.get('reconciliation_required') is False
    page.readiness_account.setText(ui_text('redesign.paper.account_reconciled') if reconciled else ui_text('redesign.paper.account_pending'))
    page.readiness_policy.setText(
        ui_text('redesign.paper.policy_loaded') if (page.root / 'paper_policy.json').exists() else ui_text('redesign.paper.policy_pending')
    )
    key = 'redesign.paper.next_empty'
    if selected:
        key = 'redesign.paper.next_ready' if reconciled else 'redesign.paper.next_reconcile'
    controls = getattr(page, 'replay_controls', None)
    if getattr(controls, 'running', False):
        key = 'replay.paused' if controls.paused else 'replay.running'
    elif getattr(getattr(page.page_state, 'jobs', None), 'active', False):
        key = 'ui.start_job.running'
    if getattr(page.page_state, 'manual_order_lock', False):
        key = 'redesign.paper.next_locked'
    text = ui_text(key)
    if key != 'redesign.paper.next_locked' and (account.get('consecutive_loss_halt') or account.get('quarantined')):
        text = stop_presentation(account)[0]
    page.readiness_next.setText(text)
