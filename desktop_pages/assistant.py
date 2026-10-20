"""Collapsed, session-only, plain-text read-only research chat."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QPlainTextEdit, QMessageBox

from desktop_pages.assistant_runtime import ReplyProcess, host_context
from desktop_pages.assistant_details import MAX_ROWS, TextFold, ToolTimeline, code_blocks, shown_text
from desktop_pages.assistant_permissions import ResearchPermission, install_menu
from desktop_pages.assistant_completion import CompletionMenu, resolve_references
from desktop_pages.assistant_models import ModelControls
import desktop_privacy as privacy
from desktop_strings import ui_text
from quantlab.assistant_chat import ChatDispatcher, fixture_reply
from quantlab.errors import ERROR_TABLE


class AssistantPanel(QWidget):
    def __init__(self, host=None, *, dispatcher=None, worker=None, consent=None, clock=None):
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
        self._transcript_entries = []
        privacy.bind_text(self.transcript, self.refresh_transcript)
        self.timeline = ToolTimeline(**({'clock': clock} if clock is not None else {}))
        self.timeline.setObjectName('assistant_timeline')
        layout.addWidget(self.timeline)
        self.thinking = TextFold(ui_text('assistant.thinking'), parent=self)
        self.thinking.setObjectName('assistant_thinking')
        layout.addWidget(self.thinking)
        self.code_folds = []
        self.input = QLineEdit()
        self.input.setMaxLength(1024)
        self.input.setAccessibleName(ui_text('assistant.input'))
        self.input.setPlaceholderText(ui_text('assistant.hint'))
        layout.addWidget(self.input)
        self.completions = CompletionMenu(self.input, layout, self.dispatcher)
        self.permissions = ResearchPermission(getattr(host, 'settings', None), self)
        self.permission_menu = install_menu(layout, self.permissions, 'assistant_research_permission')
        self.dispatcher.consent = lambda: self.ask_consent()
        self.permissions.changed.connect(self._permission_changed)
        self._permission_changed()
        self.send = QPushButton(ui_text('assistant.send'))
        self.send.setAccessibleName(ui_text('assistant.send'))
        layout.addWidget(self.send)
        self.models = ModelControls(self, layout)
        self.model = self.models.model
        self.effort = self.models.effort
        self.mode.currentIndexChanged.connect(self.models.update_send)
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

    def _permission_changed(self):
        self.dispatcher.permission = self.permissions.mode

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

    def refresh_transcript(self):
        self.transcript.setPlainText(shown_text('\n'.join(self._transcript_entries), privacy.enabled(self.transcript)))

    def append_transcript(self, text):
        self._transcript_entries.append(text[:16384])
        del self._transcript_entries[:-MAX_ROWS]
        self.refresh_transcript()

    def reply(self, text, *, chatgpt=False, thinking=''):
        label = ui_text('assistant.chatgpt') if chatgpt else ui_text('assistant.fixture')
        self.append_transcript(label + '\n' + text + '\n' + ui_text('assistant.disclaimer'))
        self.thinking.source = thinking[:8192]
        self.thinking.toggle.setChecked(False)
        self.thinking.refresh()
        for block in code_blocks(text):
            fold = TextFold(ui_text('assistant.code'), block, copy=True, parent=self)
            self.layout().addWidget(fold)
            fold.refresh()
            self.code_folds.append(fold)
        while len(self.code_folds) > MAX_ROWS:
            fold = self.code_folds.pop(0)
            self.layout().removeWidget(fold)
            fold.setParent(None)
            fold.deleteLater()

    def error_reply(self, *, chatgpt=False):
        self.reply(ERROR_TABLE['agent_tool_refused'].explanation, chatgpt=chatgpt)

    def submit(self):
        prompt = self.input.text().strip()
        if not prompt or self.worker.active:
            return
        remote = self.mode.currentData() == 'chatgpt'
        if remote and not self.ask_consent():
            return
        if self.model.count() == 0:
            self.error_reply(chatgpt=remote)
            return
        selection = {}
        if remote:
            try:
                slug, effort = self.models.validate()
                selection = {'model': slug}
                if effort is not None:
                    selection.update(effort=effort, efforts=list(self.models.binding[2]))
            except ValueError:
                self.error_reply(chatgpt=True)
                return
        try:
            prompt = resolve_references(prompt, self.dispatcher)
        except ValueError:
            self.reply(ERROR_TABLE['agent_reference_not_found'].explanation, chatgpt=remote)
            return
        self.completions.close()
        tool_request = not remote and prompt.startswith('/tool ')
        self.append_transcript(ui_text('assistant.user') + '\n' + (ui_text('assistant.tool_request') if tool_request else prompt))
        self.input.clear()
        if not remote:
            # Tool requests are explicit closed JSON, never authority/evidence.
            if tool_request:
                name, _, arguments = prompt[6:].partition(' ')
                self.reply(self.timeline.call(self.dispatcher, name, arguments or '{}'))
            elif fixture_reply(prompt) == 'help':
                self.reply(ui_text('assistant.fixture_help'))
            else:
                self.reply(ui_text('assistant.fixture_research'))
            return
        controller = getattr(self.host, 'chatgpt_controller', None)
        try:
            self.models.set_usage(None)
            self._reply_binding = (getattr(controller, 'active_registration', None), selection['model'])
            self.worker.start(
                {
                    'consent': True,
                    'prompt': prompt,
                    'registration': getattr(controller, 'active_registration', None),
                    **selection,
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
        self.models.update_send(idle=True)
        if result.get('ok') is True and type(result.get('text')) is str:
            controller = getattr(self.host, 'chatgpt_controller', None)
            binding = (getattr(controller, 'active_registration', None), self.model.currentData())
            self.models.set_usage(result.get('context_usage') if binding == getattr(self, '_reply_binding', None) else None)
            self.reply(result['text'], chatgpt=True, thinking=result.get('thinking', ''))
        else:
            self.error_reply(chatgpt=True)

    def cancel(self):
        pending = self.worker.active
        self.timer.stop()
        self.worker.cancel()
        self.models.update_send(idle=True)
        if pending:
            self.error_reply(chatgpt=True)

    def hideEvent(self, event):
        self.cancel()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)
