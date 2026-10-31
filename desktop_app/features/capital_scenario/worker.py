"""Worker-only OOS reader and bounded scenario adapter; never persists results."""

from time import monotonic
from quantlab.capital_scenario import simulate, empty_result
from quantlab.core import ValidationError
from quantlab.significance import merge_oos_daily_returns
from quantlab.walk_forward import read_walk_forward_state
from quantlab.research_core.application.walk_forward_operations import _folder
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
