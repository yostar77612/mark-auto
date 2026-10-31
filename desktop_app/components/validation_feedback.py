"""Fixed-code feedback presentation; callers retain validation and privacy."""

from desktop_app.strings.catalog import ui_text


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


def show_feedback(label, message, *, code=None, accessible=False):
    """Render caller-approved text; never accept or stringify exceptions."""
    text = with_next_step(message, code) if code is not None else message
    label.setText(text)
    if accessible:
        label.setAccessibleName(label.text())
