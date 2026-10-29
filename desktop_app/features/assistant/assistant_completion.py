"""Local, inert completions. References cross only the frozen D3 read boundary."""

import json
import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from desktop_app.strings.catalog import ui_text
from quantlab.agent_read_tools import READ_REGISTRY
from quantlab.agent_skills import SkillLoader


MAX_COMPLETIONS = 20
MAX_REFERENCE_PAGES = 4
SHORT_HASH = 12
HASH = re.compile(r'[0-9a-f]{64}')
TOKEN = re.compile(r'(?<!\S)@([^\s]+)')


def reference_catalog(dispatcher):
    """Only identities from D3; never project metrics, rows or arbitrary labels."""
    entries = {}
    arguments = {'include_datasets': 1, 'limit': 50}
    for _ in range(MAX_REFERENCE_PAGES):
        page = dispatcher.call('list_saved_results', json.dumps(arguments))
        if not page.get('ok'):
            return {}
        for row in page['items']:
            identity, dataset = row.get('id'), row.get('data_hash')
            if type(identity) is not str or HASH.fullmatch(identity) is None or type(dataset) is not str or HASH.fullmatch(dataset) is None:
                return {}
            entries[('result', identity)] = identity
            entries.setdefault(('dataset', dataset), identity)
        if page['next_cursor'] is None:
            return entries
        arguments['cursor'] = page['next_cursor']
    # Never resolve an apparently unique short hash from a partial catalog.
    return {}


def reference_summary(kind):
    return ui_text('assistant.reference_result') if kind == 'result' else ui_text('assistant.reference_dataset')


def resolve_references(prompt, dispatcher):
    """Revalidate exact unique identities on every submit; stale means refusal.

    No payload from summary tools is interpolated into the conversation. D3's
    current evidence and content validation must succeed even after selection.
    """
    tokens = list(TOKEN.finditer(prompt))
    if not tokens:
        return prompt
    entries = reference_catalog(dispatcher)
    replacements = []
    for match in tokens:
        kind, separator, prefix = match[1].partition(':')
        if not separator or kind not in ('result', 'dataset') or re.fullmatch(r'[0-9a-f]{12,64}', prefix) is None:
            raise ValueError('agent_reference_not_found')
        matches = [(identity, result) for (entry_kind, identity), result in entries.items() if entry_kind == kind and identity.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError('agent_reference_not_found')
        identity, result = matches[0]
        name = 'get_backtest_summary' if kind == 'result' else 'get_data_quality_summary'
        if not dispatcher.call(name, json.dumps({'result_id': result})).get('ok'):
            raise ValueError('agent_reference_not_found')
        replacements.append((match.start(), match.end(), '@' + kind + ':' + identity + ' ' + reference_summary(kind)))
    for start, end, text in reversed(replacements):
        prompt = prompt[:start] + text + prompt[end:]
    return prompt


class CompletionMenu(QObject):
    """Inline popup in the existing collapsed assistant; focus stays on input.

    Explicit open state makes keyboard behavior identical for hidden QTest
    widgets and visible desktop widgets. QListWidget paints literal text.
    """

    def __init__(self, editor, layout, dispatcher):
        super().__init__(editor)
        self.editor, self.dispatcher = editor, dispatcher
        self.loader = SkillLoader(READ_REGISTRY)
        self.list = QListWidget()
        self.list.setObjectName('assistant_completions')
        self.list.setAccessibleName(ui_text('assistant.completions'))
        self.list.setMaximumHeight(160)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.insertWidget(layout.indexOf(editor) + 1, self.list)
        self.list.hide()
        self.open = False
        self.start = 0
        self.errors = ()
        editor.installEventFilter(self)
        editor.textChanged.connect(self.refresh)
        editor.cursorPositionChanged.connect(self.refresh)
        self.list.itemClicked.connect(lambda *_: self.accept())

    def close(self):
        self.open = False
        self.list.hide()
        self.editor.setFocus()

    def refresh(self, *_):
        before = self.editor.text()[: self.editor.cursorPosition()]
        match = re.search(r'(?:^|\s)(@[^\s]*)$', before)
        if before.startswith('/') and not re.search(r'\s', before):
            self.start = 0
            prefix = before[1:]
            rows = [('/' + name, '/' + name) for name in self.loader.completion_list() if name.startswith(prefix)]
            self.errors = tuple(self.loader.catalog_errors)
        elif match:
            self.start = before.rfind('@')
            prefix = before[self.start + 1 :]
            entries = reference_catalog(self.dispatcher)
            rows = []
            for kind, identity in sorted(entries):
                token = kind + ':' + identity[:SHORT_HASH]
                if token.startswith(prefix) or identity.startswith(prefix):
                    rows.append(('@' + token, '@' + token + ' ' + reference_summary(kind)))
            self.errors = ()
        else:
            self.close()
            return
        self.list.setAccessibleDescription('\n'.join(self.errors))
        self.list.clear()
        for invocation, label in rows[:MAX_COMPLETIONS]:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, invocation)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
            self.list.addItem(item)
        self.open = bool(self.list.count())
        self.list.setVisible(self.open)
        self.list.setCurrentRow(0)

    def accept(self):
        item = self.list.currentItem()
        if item is None:
            return
        end = self.editor.cursorPosition()
        text = self.editor.text()
        insertion = item.data(Qt.ItemDataRole.UserRole) + ' '
        self.editor.setText(text[: self.start] + insertion + text[end:])
        self.editor.setCursorPosition(self.start + len(insertion))
        self.close()

    def eventFilter(self, watched, event):
        if watched is self.editor and event.type() == QEvent.Type.KeyPress and self.open:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self.accept()
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = 1 if key == Qt.Key.Key_Down else -1
                self.list.setCurrentRow((self.list.currentRow() + step) % self.list.count())
                return True
        return super().eventFilter(watched, event)
