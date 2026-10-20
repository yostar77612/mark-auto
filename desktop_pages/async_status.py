"""Display-only asynchronous states; callers own work, age and recovery actions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_strings import ui_text
from desktop_theme import set_theme_property
from quantlab.errors import ERROR_TABLE
from .error_guidance import with_next_step


class AsyncStatus(QWidget):
    def __init__(self, parent=None, *, host=None):
        # Hosts used by page tests need not be QObjects.
        super().__init__(parent if isinstance(parent, QWidget) else None)
        self.host = host if host is not None else parent
        self.setProperty('role', 'asyncStatus')
        self.label = QLabel()
        self.label.setObjectName('error_next_step')
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.action = QPushButton()
        self.action.setProperty('role', 'secondary')
        self._callback = None
        self.action.clicked.connect(self._activate)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.action)
        self.set_state('empty')

    def _activate(self):
        if self._callback is not None:
            self._callback()

    def set_state(self, state, *, message=None, action_text=None, action=None, error_code=None, exception=None, retry=None, age=None, refresh=None):
        """Replace presentation and callback atomically; never stringify exceptions."""
        if type(state) is not str or state not in ('loading', 'empty', 'error', 'stale'):
            raise ValueError('Unknown async state')
        self._callback = None
        button_text = ''
        if state == 'loading':
            text = ui_text('async.loading')
        elif state == 'empty':
            text = ui_text('async.empty') if message is None else message
            button_text = action_text or ''
            self._callback = action if callable(action) and button_text else None
        elif state == 'error':
            entry = ERROR_TABLE.get(error_code) if isinstance(error_code, str) else None
            text = ui_text('async.error').format(error_code, entry.explanation, entry.action) if entry else ui_text('async.error_unknown')
            text = with_next_step(text, error_code)
            button_text = ui_text('async.retry')
            self._callback = retry if callable(retry) else None
        else:
            text = ui_text('async.stale') if age is None else ui_text('async.stale_age').format(age)
            button_text = ui_text('async.refresh')
            self._callback = refresh if callable(refresh) else None
        self.label.setText(text)
        self.label.setAccessibleName(text)
        self.setAccessibleName(text or ui_text('async.empty'))
        self.action.setText(button_text)
        self.action.setAccessibleName(button_text or ui_text('async.next'))
        self.action.setVisible(self._callback is not None)
        set_theme_property(self.action, 'role', 'primary' if state == 'empty' and self._callback is not None else 'secondary')
        set_theme_property(self, 'state', state)

    def read_job(self, host=None, *, error_code=None, retry=None):
        """Project existing job presentation; do not start or retry any work."""
        host = self.host if host is None else host
        progress = getattr(host, 'job_progress', None)
        feedback = getattr(host, 'job_feedback', None)
        if error_code is None:
            error_code = getattr(feedback, 'error_code', None)
        if getattr(progress, 'running', False):
            self.set_state('loading')
        elif getattr(feedback, 'terminal', False) and error_code is not None:
            self.set_state('error', error_code=error_code, retry=retry)
        else:
            self.set_state('empty')
