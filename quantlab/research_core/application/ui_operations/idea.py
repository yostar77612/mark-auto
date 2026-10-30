"""Existing idea worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path
from quantlab.core import ValidationError
from quantlab.research_core.application.research_operations import _handle_ui_campaign


def _handle_ui_idea_research(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False, transport=None, fetcher=None):
    from quantlab.idea_research import IdeaResearch, IdeaStore, new_task

    retry = 'retry_task_id' in payload
    if set(payload) != ({'retry_task_id', 'consent', 'registration', 'model'} if retry else {'request', 'registration', 'model'}):
        raise ValidationError(ports.text('idea.invalid_request'))
    if (payload['consent'] if retry else payload['request'].get('consent')) != {'network': True, 'plan_usage': True}:
        raise ValidationError(ports.text('idea.consent_required'))
    bootstrap = str(getattr(paths, 'bootstrap', None) or paths.root)
    reference = ports.auth.OAuthCredentialReference(bootstrap, payload['registration'])
    if transport is None:
        if ports.subscription.read_account_status(reference, Path(bootstrap) / 'control-v1') != {'state': 'ready', 'pending': False}:
            raise ValidationError(ports.text('idea.account_not_ready'))
        transport = ports.subscription.PlanHTTPTransport()
    store = IdeaStore(root)
    task = store.load(payload['retry_task_id']) if retry else new_task(payload['request'])
    messages = {
        'task': ports.text('idea.progress.task'),
        'search': ports.text('idea.progress.search'),
        'urls': ports.text('idea.progress.urls'),
        'source': ports.text('idea.progress.source'),
        'extracting': ports.text('idea.progress.extracting'),
        'candidates': ports.text('idea.progress.candidates'),
        'status': ports.text('idea.progress.status'),
    }

    def progress(kind, **values):
        if emit is not None:
            event = values.get('idea_event') or {}
            emit(kind, **{**values, 'message': messages.get(event.get('kind'), messages['status'])})

    research = IdeaResearch(task, caller=ports.idea_stream(reference, transport), model=payload['model'], root=root, emit=progress, fetcher=fetcher)
    record = research.retry_failed() if retry else research.run()
    if record['status'] == 'quota_paused':
        ports.subscription._persist_account_pause(reference, 'quota_paused')
    return {
        'task_id': record['task_id'],
        'status': record['status'],
        'stop_reason': record['stop_reason'],
        'searches': len(record['searches']),
        'sources': len(record['sources']),
        'candidates': len(record['candidates']),
        'backtestable': sum((1 for c in record['candidates'] if c.get('backtestable'))),
    }


def _handle_ui_idea_adopt(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.idea_research import IdeaStore, adoption_candidate, adoption_config, manual_response
    from quantlab.configuration import config_from_json

    if set(payload) != {'task_id', 'candidate_id', 'config'}:
        raise ValidationError(ports.text('idea.invalid_request'))
    candidate = adoption_candidate(IdeaStore(root).load(payload['task_id']), payload['candidate_id'])
    config = adoption_config(payload['config'], candidate['family'])
    checked = dict(config)
    if isinstance(checked.get('backtest_config'), dict):
        checked['backtest_config'] = config_from_json(checked['backtest_config'])
    response = manual_response(ports.manual.export_request(ports.inputs._dataset(root, {}), checked), candidate)
    state = _handle_ui_campaign(ports, {'config': config, 'provider': {'mode': 'manual', 'response_text': response}}, paths, root, emit=emit)
    return state
