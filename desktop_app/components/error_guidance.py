"""Display-only next steps for existing B1 codes; no work or recovery actions."""

from desktop_app.components.validation_feedback import show_feedback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel

import desktop_app.components.privacy as _privacy
from quantlab.desktop_errors import error_message, exception_code


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
            show_feedback(label, shown, code=code, accessible=True)

        _privacy.bind_text(label, render)
        label.show()
        raise
