"""Bounded plain-text assistant details; presentation grants no capabilities."""

import json
import re
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

import desktop_privacy as privacy
from desktop_strings import ui_text
from quantlab.agent_read_tools import TOOL_NAMES
from quantlab.errors import ERROR_TABLE


MAX_SUMMARY_CHARS = 240
MAX_ROWS = 40
MAX_TEXT_CHARS = 16384
_SECRET = re.compile(r'credential|password|secret|token|authorization|cookie|api.?key', re.I)


def redacted(value, private, key=''):
    """Known structured values only; credentials are omitted even outside privacy."""
    if _SECRET.search(key):
        return privacy.mask_money(value)
    if private and key in privacy.ACCOUNT_FIELDS:
        return privacy.mask_account_id(value)
    if private and (key in privacy.MONEY_FIELDS or key in ('cash', 'money', 'path', 'result_id', 'other_id', 'cursor')):
        return privacy.mask_money(value)
    if isinstance(value, dict):
        return {k: redacted(v, private, k) for k, v in value.items() if not _SECRET.search(k)}
    if isinstance(value, list):
        return [redacted(v, private, key) for v in value]
    return value


def parameter_summary(arguments, private=False):
    """Do not echo rejected/free-form arguments, unknown keys, or opaque cursors."""
    try:
        value = json.loads(arguments)
        if type(value) is not dict:
            raise ValueError
        safe = {}
        for key, item in value.items():
            if key in ('result_id', 'other_id') and type(item) is str and re.fullmatch(r'[0-9a-f]{64}', item):
                safe[key] = item
            elif key == 'limit' and type(item) is int and 1 <= item <= 50:
                safe[key] = item
            elif key == 'cursor':
                safe[key] = privacy.mask_money(item)
            elif key in privacy.ACCOUNT_FIELDS and type(item) is str and re.fullmatch(r'[A-Za-z0-9-]{1,32}', item):
                safe[key] = item
            elif key in privacy.MONEY_FIELDS | {'cash', 'money'} and type(item) in (str, int) and re.fullmatch(r'-?[0-9.]{1,96}', str(item)):
                safe[key] = item
            elif key == 'path' and type(item) is str:
                # Paths are never accepted D3 arguments, but host presentations can mask them.
                safe[key] = privacy.mask_money(item) if private else item[:128]
        return json.dumps(redacted(safe, private), ensure_ascii=False, sort_keys=True)[:MAX_SUMMARY_CHARS]
    except (TypeError, ValueError, RecursionError):
        return ui_text('assistant.parameters_hidden')


def shown_text(text, private):
    return privacy.mask_money(text) if private and text else text


class TextFold(QWidget):
    """Native checkable button supports click/Space; body always uses plain text."""

    def __init__(self, title, text='', *, copy=False, parent=None):
        super().__init__(parent)
        self.source = text[:MAX_TEXT_CHARS]
        layout = QVBoxLayout(self)
        self.toggle = QPushButton(title)
        self.toggle.setAccessibleName(title)
        self.toggle.setCheckable(True)
        layout.addWidget(self.toggle)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setAccessibleName(title)
        self.body.setMaximumHeight(180)
        # Own renderer replaces B11's generic raw preview cache.
        privacy.bind_text(self.body, self.refresh)
        layout.addWidget(self.body)
        self.body.hide()
        self.toggle.toggled.connect(self.body.setVisible)
        self.copy_button = None
        if copy:
            self.copy_button = QPushButton(ui_text('assistant.copy_code'))
            self.copy_button.setAccessibleName(ui_text('assistant.copy_code'))
            self.copy_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.copy_button.clicked.connect(self.copy_text)
            layout.addWidget(self.copy_button)

    def refresh(self):
        self.body.setPlainText(shown_text(self.source, privacy.enabled(self)))

    def copy_text(self):
        # Preserve source line endings too; QPlainTextEdit normalizes them.
        QApplication.clipboard().setText(shown_text(self.source, privacy.enabled(self)))


class ToolTimeline(QWidget):
    def __init__(self, *, clock=time.monotonic):
        super().__init__()
        self.clock = clock
        self.rows = []
        layout = QVBoxLayout(self)
        self.title = QLabel(ui_text('assistant.timeline'))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)

    def call(self, dispatcher, name, arguments):
        start = self.clock()
        try:
            raw = dispatcher.render_tool(name, arguments)
            result = json.loads(raw)
        except Exception:
            result = {'ok': False}
        elapsed = max(0, self.clock() - start)
        failed = result.get('ok') is not True
        if failed:
            code = 'agent_tool_refused'
            raw = code + ': ' + ERROR_TABLE[code].explanation
            summary = raw
        else:
            raw = json.dumps(result, ensure_ascii=False, sort_keys=True)
            summary = ui_text('assistant.result_summary').format(len(result.get('items', [])), result.get('truncated') is True)
        tool = name if name in TOOL_NAMES else ui_text('assistant.unknown_tool')
        # Retain only projected summaries, never rejected credentials or free text.
        arguments = '{}' if failed else parameter_summary(arguments)
        row = TextFold(ui_text('assistant.tool_row').format(tool, summary, elapsed), parent=self)
        row.source = raw[:MAX_TEXT_CHARS]
        parameters = QLabel()
        parameters.setTextFormat(Qt.TextFormat.PlainText)
        parameters.setWordWrap(True)
        row.layout().insertWidget(1, parameters)
        privacy.bind_text(parameters, lambda: parameters.setText(parameter_summary(arguments, privacy.enabled(parameters))))
        row.refresh()
        self.layout().addWidget(row)
        self.rows.append(row)
        while len(self.rows) > MAX_ROWS:
            oldest = self.rows.pop(0)
            self.layout().removeWidget(oldest)
            oldest.setParent(None)
            oldest.deleteLater()
        return ui_text('assistant.tool_recorded')


def code_blocks(text):
    """Only complete line-fenced blocks; preserve every character inside fences."""
    return [match.group(1) for match in re.finditer(r'^```[^\r\n]*\r?\n(.*?)^```[ \t]*(?:\r?\n|$)', text, re.M | re.S)]
