"""Explicit, fixed-payload connection probe; no research or assistant tools."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QMessageBox
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message

PROMPT = 'Reply with OK.'


class ConnectionTest:
    def __init__(self, panel):
        self.panel = panel
        self.binding = None
        self.button = QPushButton(ui_text('connection_test.button'), panel)
        self.button.setObjectName('chatgpt_test')
        self.button.setAccessibleName(ui_text('connection_test.button'))
        self.button.setToolTip(ui_text('connection_test.disclosure'))
        self.status = QLabel(panel)
        self.status.setObjectName('chatgpt_test_status')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        panel.layout().addWidget(self.button)
        panel.layout().addWidget(self.status)
        self.button.clicked.connect(self.submit)
        panel.controller.changed.connect(self.render)
        panel.account.currentIndexChanged.connect(self.render)
        panel.model.currentIndexChanged.connect(self.render)
        self.render()

    def render(self, *_):
        p = self.panel
        c = p.controller
        binding = (c.active_registration, p.account.currentData(), p.model.currentData())
        if binding != self.binding:
            self.binding = binding
            if c.message == c.test_message:
                c.message = ui_text('connection_test.untested')
                p.status.setText(c.message)
            c.test_message = ui_text('connection_test.untested')
        eligible = (
            c.host_available
            and (not c.busy)
            and (c.state == 'plan_ready')
            and (p.account.currentData() == c.active_registration)
            and (c.active_registration is not None)
            and (p.model.currentData() in c.models)
            and c.account_status_known
            and (not c.account_paused)
            and (not c.account_pending)
            and (not c.unknown_count)
        )
        self.button.setEnabled(bool(eligible))
        reason = ''
        if c.account_status_known and (c.account_paused or c.account_pending or c.unknown_count):
            reason = error_message('active_or_unknown_request' if c.account_pending or c.unknown_count else c.account_state)
        self.button.setToolTip(ui_text('connection_test.disclosure') + '\n' + reason)
        self.status.setText(c.test_message + ('\n' + reason if reason else ''))

    def submit(self):
        if not self.button.isEnabled():
            return
        p = self.panel
        answer = QMessageBox.question(
            p,
            ui_text('assistant.consent_title'),
            ui_text('connection_test.disclosure'),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        p._safe(lambda: p.controller.request('test', p.account.currentData(), confirmed=True, model=p.model.currentData()))
