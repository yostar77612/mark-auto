from quantlab.capital_scenario import empty_result
from quantlab.desktop_feedback import completion_summary


def event(shell, packet):
    if getattr(shell, 'last_operation', None) != 'ui_capital_scenario':
        return False
    panel = getattr(getattr(shell, 'strategy_page', None), 'result_panel', None)
    kind = packet.get('type')
    if panel is not None:
        if kind == 'result':
            panel.set_scenario(packet.get('result', {}))
        elif kind in ('cancelled', 'canceled', 'error', 'failed'):
            status = 'cancelled' if kind in ('cancelled', 'canceled') else 'timed_out' if packet.get('error_type') == 'DeadlineExceeded' else 'rejected'
            panel.set_scenario(empty_result(status, status))
    record = getattr(shell, 'record_event', None)
    if record is not None:
        record('ui_capital_scenario', kind)
    notify = getattr(shell, 'notify_local', None)
    if notify is not None and kind == 'result':
        notify(completion_summary('ui_capital_scenario', packet.get('result', {})), completion=True)
    elif notify is not None and kind in ('error', 'failed'):
        from desktop_app.components.job_progress import failure_notice

        notify(failure_notice(shell, packet), error=True, completion=True)
    status = getattr(shell, 'status', None)
    if status is not None and kind in ('result', 'error', 'failed', 'cancelled', 'canceled'):
        status.clear()
    return True
