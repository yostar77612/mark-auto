from desktop_app.strings.catalog import ui_text
from desktop_app.features.strategy.idea_labels import STATUS_TEXT


def dialog_for(shell):
    page = getattr(shell, 'strategy_page', None)
    return getattr(page, 'idea_dialog', None) if page is not None else None


def event(shell, packet):
    """Route ui_idea_research worker events to the dialog. Other operations pass through."""
    if getattr(shell, 'last_operation', None) == 'ui_idea_adopt':
        dialog = dialog_for(shell)
        if dialog is not None:
            kind = packet.get('type')
            if kind == 'result':
                dialog.status.setText(ui_text('redesign.strategy.idea_research_ready'))
                shell.strategy_page.choose_mode('research')
                dialog.hide()
            elif kind in ('error', 'failed', 'cancelled', 'canceled'):
                from quantlab.desktop_errors import error_message

                dialog.status.setText(ui_text('job.cancel_notice') if kind in ('cancelled', 'canceled') else error_message('operation_failed'))
                dialog.refresh_controls()
        return False
    if getattr(shell, 'last_operation', None) != 'ui_idea_research':
        return False
    dialog = dialog_for(shell)
    kind = packet.get('type')
    if dialog is not None:
        if kind == 'progress' and isinstance(packet.get('idea_event'), dict):
            dialog.apply(packet['idea_event'])
        elif kind == 'result':
            task_id = (packet.get('result') or {}).get('task_id')
            if task_id:
                dialog.load_record(task_id)
        elif kind in ('cancelled', 'canceled', 'error', 'failed'):
            dialog.job_ended(kind)
    record = getattr(shell, 'record_event', None)
    if record is not None and kind != 'progress':
        record('ui_idea_research', kind)
    notify = getattr(shell, 'notify_local', None)
    if notify is not None and kind == 'result':
        status = (packet.get('result') or {}).get('status')
        notify(
            ui_text(STATUS_TEXT[status]) if status in ('completed', 'cancelled', 'search_unavailable', 'quota_paused', 'no_sources', 'failed') else '',
            completion=True,
        )
    elif notify is not None and kind in ('error', 'failed'):
        from desktop_app.components.job_progress import failure_notice

        notify(failure_notice(shell, packet), error=True, completion=True)
    status = getattr(shell, 'status', None)
    if status is not None and kind in ('result', 'error', 'failed', 'cancelled', 'canceled'):
        status.clear()
    elif status is not None and kind == 'progress':
        status.setText(packet.get('message') or '')
    return True
