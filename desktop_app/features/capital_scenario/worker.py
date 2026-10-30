"""Worker-only OOS reader and bounded scenario adapter; never persists results."""

from time import monotonic
from quantlab.capital_scenario import simulate, empty_result
from quantlab.core import ValidationError
from quantlab.desktop_feedback import completion_summary
from quantlab.significance import merge_oos_daily_returns
from quantlab.walk_forward import read_walk_forward_state
from desktop_app.features.walk_forward.presenter import _folder
from desktop_app.strings.catalog import ui_text


def execute(payload, paths):
    keys = {'reference', 'start_equity', 'threshold', 'horizon_days', 'paths', 'seed'}
    if type(payload) is not dict or set(payload) != keys:
        raise ValidationError(ui_text('capital.invalid'))
    folder = _folder(paths, payload['reference'])
    state = read_walk_forward_state(folder)
    merged = merge_oos_daily_returns(state)
    if merged['reason']:
        return empty_result('rejected', merged['reason'])
    parameters = {key: payload[key] for key in keys - {'reference'}}
    return simulate(merged['returns'], **parameters, cancel=None, deadline=monotonic() + 45)


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
        # Reuse the shared fixed failure notice, never exception text.
        from desktop_app.components.job_progress import failure_notice

        notify(failure_notice(shell, packet), error=True, completion=True)
    status = getattr(shell, 'status', None)
    if status is not None and kind in ('result', 'error', 'failed', 'cancelled', 'canceled'):
        status.clear()
    return True  # Pure compute never refreshes saved strategy/paper views.
