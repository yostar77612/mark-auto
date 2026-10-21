"""Bounded, Qt-free presentation history. Never retain payloads or credentials."""

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime

from desktop_strings import ZH_TW, ui_text
from quantlab.desktop_feedback import OPERATION_LABELS, completion_summary
from quantlab.errors import ERROR_TABLE


KINDS = {
    'job': ui_text('notifications.kind.job'),
    'paper': ui_text('notifications.kind.paper'),
    'data': ui_text('notifications.kind.data'),
}
SEVERITIES = {'info': ui_text('notifications.info'), 'error': ui_text('notifications.error')}


def safe_operation(operation):
    return operation if type(operation) is str and operation.removeprefix('ui_') in OPERATION_LABELS else ''


def safe_summary(operation, result):
    """Only structural counts cross this boundary; no research evaluation values."""
    operation = safe_operation(operation)
    result = result if type(result) is dict else {}
    safe = {}
    for field in ('reports', 'rows', 'downloads', 'attempts', 'selected', 'receipts'):
        value = result.get(field)
        if type(value) in (list, tuple, dict):
            safe[field] = [None] * min(len(value), 10000)
    # Counts are validated integers, never strings from a worker.
    if type(result.get('bars')) is int and 0 <= result['bars'] <= 100000000:
        safe['bars'] = result['bars']
    providers = result.get('providers')
    if type(providers) is dict:
        safe['providers'] = {i: {'error': bool(type(row) is dict and row.get('error')), 'bars': 0} for i, row in enumerate(list(providers.values())[:200])}
    report = result.get('cancel_all_report')
    if operation == 'ui_paper_cancel_all' and type(report) is dict:
        safe['cancel_all_report'] = {}
        for field in ('cancelled_order_ids', 'failed_order_ids'):
            value = report.get(field)
            if type(value) in (list, tuple):
                safe['cancel_all_report'][field] = [None] * min(len(value), 10000)
    # Deliberately omit account, amounts, hashes, analysis ids, replay and OOS.
    text = completion_summary(operation, safe)
    if operation.startswith('ui_paper_'):
        text = ui_text('notifications.paper_summary').format(text)
    return text


@dataclass(frozen=True)
class Notification:
    id: int
    kind: str
    severity: str
    message: str
    error_code: str | None
    operation: str
    sequence: int
    time: str
    unread: bool = True


class NotificationLog:
    def __init__(self, maxlen=100, *, clock=None):
        if type(maxlen) is not int or not 1 <= maxlen <= 200:
            raise ValueError('Notification bound must be 1..200')
        self.entries = deque(maxlen=maxlen)
        self.sequence = 0
        self.clock = clock or datetime.now
        self._seen = deque(maxlen=maxlen)

    @property
    def unread_count(self):
        return sum(entry.unread for entry in self.entries)

    def append(self, *, operation='', error=False, code=None, message=None):
        operation = safe_operation(operation)
        code = code if type(code) is str and ERROR_TABLE.get(code) else None
        if error:
            code = code or 'operation_failed'
            entry = ERROR_TABLE.get(code)
            message = ui_text('async.error').format(code, entry.explanation, entry.action)
        elif type(message) is not str or message not in ZH_TW.values():
            message = safe_summary(operation, {})
        return self._append(operation, error, code, message)

    def _append(self, operation, error, code, message):
        self.sequence += 1
        kind = (
            'paper'
            if operation in ('ui_paper_submit', 'ui_paper_cancel', 'ui_paper_cancel_all')
            else 'data'
            if operation in ('ui_market_refresh', 'ui_refresh', 'ui_import')
            else 'job'
        )
        entry = Notification(self.sequence, kind, 'error' if error else 'info', message, code, operation, self.sequence, self.clock().strftime('%H:%M:%S'))
        self.entries.append(entry)
        return entry

    def accept_event(self, operation, event):
        """The terminal job handler's single ingress; duplicates never add rows."""
        kind = event.get('type')
        if kind not in ('result', 'completed', 'success', 'error', 'failed', 'cancelled', 'canceled'):
            return None
        job_id = event.get('job_id')
        identity = ('job', job_id) if type(job_id) in (str, int) else ('event', id(event))
        if identity in self._seen:
            return None
        self._seen.append(identity)
        operation = safe_operation(operation)
        result = event.get('result')
        result = result if type(result) is dict else {}
        providers = result.get('providers', {})
        failed = kind in ('error', 'failed') or result.get('status') in ('failed', 'error', 'blocked')
        failed = failed or (
            operation == 'ui_market_refresh' and type(providers) is dict and any(type(v) is dict and v.get('error') for v in providers.values())
        )
        if failed:
            return self.append(operation=operation, error=True, code=event.get('error_code') or result.get('error_code'))
        message = ui_text('job.cancelled') if kind in ('cancelled', 'canceled') else safe_summary(operation, result)
        return self._append(operation, False, None, message)

    def mark_viewed(self):
        self.entries = deque((replace(entry, unread=False) for entry in self.entries), maxlen=self.entries.maxlen)

    def dismiss(self, entry_id):
        self.entries = deque((entry for entry in self.entries if entry.id != entry_id), maxlen=self.entries.maxlen)

    def clear(self):
        self.entries.clear()
