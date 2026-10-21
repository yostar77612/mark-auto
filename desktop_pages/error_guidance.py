"""Display-only next steps for existing B1 codes; no work or recovery actions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel

import desktop_privacy as _privacy
from desktop_strings import ui_text
from quantlab.desktop_errors import error_message, exception_code


NEXT_STEP_KEYS = {
    'validation_failed': 'errors.next.validation',
    'market_data_invalid': 'errors.next.data',
    'history_file_required': 'errors.next.data',
    'history_sessions_required': 'errors.next.calendar',
    'history_session_invalid': 'errors.next.calendar',
    'history_date_invalid': 'errors.next.calendar',
    'history_session_limit': 'errors.next.calendar',
    'network_disabled': 'errors.next.provider',
    'operation_failed_plan': 'errors.next.provider',
    'configuration_blocked': 'errors.next.provider',
    'http_transport_failed': 'errors.next.provider',
    'authorization_busy': 'errors.next.running',
}


def next_step(code):
    """Return fixed catalog guidance, or nothing for an unknown/unmapped code."""
    texts = {
        'errors.next.validation': ui_text('errors.next.validation').format(
            ui_text('ui.data_page.title'), ui_text('ui.strategy_page.title'), ui_text('ui.backtest_page.title')
        ),
        'errors.next.data': ui_text('errors.next.data').format(ui_text('ui.data_page.title')),
        'errors.next.calendar': ui_text('errors.next.calendar').format(ui_text('ui.data_page.title')),
        'errors.next.provider': ui_text('errors.next.provider').format(ui_text('ui.settings_page.title')),
        'errors.next.running': ui_text('errors.next.running').format(ui_text('ui.settings_page.title')),
    }
    return texts.get(NEXT_STEP_KEYS.get(code), '') if isinstance(code, str) else ''


def with_next_step(message, code):
    hint = next_step(code)
    return message + '\n' + hint if hint else message


def clear_inline(owner):
    for label in getattr(owner, '_error_guidance_labels', ()):
        label._privacy_render = lambda: None
        label.clear()
        label.setAccessibleName('')
        label.hide()


def run_inline(button, callback, *, owner, layout):
    """Keep existing exception handling and confirmations, adding a page label."""
    clear_inline(owner)
    try:
        return callback()
    except Exception as exc:
        code = exception_code(exc)
        label = getattr(button, '_error_guidance_label', None)
        if label is None:
            label = QLabel()
            label.setObjectName('error_next_step')
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addRow(label) if isinstance(layout, QFormLayout) else layout.addWidget(label)
            button._error_guidance_label = label
            labels = getattr(owner, '_error_guidance_labels', [])
            owner._error_guidance_labels = labels
            labels.append(label)
        # Fixed B1 text only: never display the exception's values or paths.
        message = error_message(code)

        def render():
            shown = _privacy.preview_text(message, _privacy.enabled(label))
            label.setText(with_next_step(shown, code))
            label.setAccessibleName(label.text())

        _privacy.bind_text(label, render)
        label.show()
        raise
