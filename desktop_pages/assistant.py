"""Collapsed, session-only, plain-text read-only research chat."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QPlainTextEdit, QMessageBox

from desktop_pages.assistant_runtime import ReplyProcess, host_context
from desktop_strings import ui_text
from quantlab.assistant_chat import ChatDispatcher, fixture_reply
from quantlab.errors import ERROR_TABLE


class AssistantPanel(QWidget):
    def __init__(self, host=None, *, dispatcher=None, worker=None, consent=None):
        super().__init__()
        self.host = host
        self.dispatcher = dispatcher or ChatDispatcher(host_context(getattr(host, 'root', '.')))
        paths = getattr(host, 'paths', None)
        self.worker = worker or ReplyProcess(getattr(paths, 'bootstrap', None))
        self.ask_consent = consent or self._consent
        layout = QVBoxLayout(self)
        self.title = QLabel(ui_text('assistant.title'))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        self.mode = QComboBox()
        self.mode.addItem(ui_text('assistant.fixture'), 'fixture')
        self.mode.addItem(ui_text('assistant.chatgpt'), 'chatgpt')
        self.mode.setAccessibleName(ui_text('assistant.source'))
        layout.addWidget(self.mode)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMaximumBlockCount(500)
        self.transcript.setAccessibleName(ui_text('assistant.transcript'))
        layout.addWidget(self.transcript)
        self.input = QLineEdit()
        self.input.setMaxLength(1024)
        self.input.setAccessibleName(ui_text('assistant.input'))
        self.input.setPlaceholderText(ui_text('assistant.hint'))
        layout.addWidget(self.input)
        self.send = QPushButton(ui_text('assistant.send'))
        self.send.setAccessibleName(ui_text('assistant.send'))
        layout.addWidget(self.send)
        for name, widget in (
            ('assistant_panel', self),
            ('assistant_mode', self.mode),
            ('assistant_transcript', self.transcript),
            ('assistant_input', self.input),
            ('assistant_send', self.send),
        ):
            widget.setObjectName(name)
        self.setTabOrder(self.mode, self.transcript)
        self.setTabOrder(self.transcript, self.input)
        self.setTabOrder(self.input, self.send)
        self.input.returnPressed.connect(self.submit)
        self.send.clicked.connect(self.submit)
        self.shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.input)
        self.shortcut.activated.connect(self.submit)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)

    def _consent(self):
        return (
            QMessageBox.question(
                self,
                ui_text('assistant.consent_title'),
                ui_text('assistant.consent_body'),
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Ok
        )

    def reply(self, text, *, chatgpt=False):
        label = ui_text('assistant.chatgpt') if chatgpt else ui_text('assistant.fixture')
        self.transcript.appendPlainText(label + '\n' + text + '\n' + ui_text('assistant.disclaimer'))

    def error_reply(self, *, chatgpt=False):
        self.reply(ERROR_TABLE['agent_tool_refused'].explanation, chatgpt=chatgpt)

    def submit(self):
        prompt = self.input.text().strip()
        if not prompt or self.worker.active:
            return
        remote = self.mode.currentData() == 'chatgpt'
        if remote and not self.ask_consent():
            return
        self.transcript.appendPlainText(ui_text('assistant.user') + '\n' + prompt)
        self.input.clear()
        if not remote:
            # Tool requests are explicit closed JSON, never authority/evidence.
            if prompt.startswith('/tool '):
                name, _, arguments = prompt[6:].partition(' ')
                self.reply(self.dispatcher.render_tool(name, arguments or '{}'))
            elif fixture_reply(prompt) == 'help':
                self.reply(ui_text('assistant.fixture_help'))
            else:
                self.reply(ui_text('assistant.fixture_research'))
            return
        controller = getattr(self.host, 'chatgpt_controller', None)
        connection = getattr(self.host, 'chatgpt_panel', None)
        model = getattr(connection, 'model', None)
        try:
            self.worker.start(
                {
                    'consent': True,
                    'prompt': prompt,
                    'registration': getattr(controller, 'active_registration', None),
                    'model': model.currentData() if model is not None else None,
                }
            )
            self.send.setEnabled(False)
            self.timer.start()
        except Exception:
            self.error_reply(chatgpt=True)

    def poll(self):
        result = self.worker.poll()
        if result is None:
            return
        self.timer.stop()
        self.send.setEnabled(True)
        if result.get('ok') is True and type(result.get('text')) is str:
            self.reply(result['text'], chatgpt=True)
        else:
            self.error_reply(chatgpt=True)

    def cancel(self):
        pending = self.worker.active
        self.timer.stop()
        self.worker.cancel()
        self.send.setEnabled(True)
        if pending:
            self.error_reply(chatgpt=True)

    def hideEvent(self, event):
        self.cancel()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)
