"""Local discovered-catalog controls; never discover, probe or infer capabilities."""

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel

from desktop_chatgpt_ui import MODEL
from desktop_strings import ui_text


def advertised_efforts(controller, slug):
    metadata = getattr(controller, 'model_metadata', {})
    row = metadata.get(slug, {}) if type(metadata) is dict else {}
    values = row.get('reasoning_efforts', ()) if type(row) is dict else ()
    if type(values) not in (list, tuple) or len(values) > 16:
        return ()
    if any(type(v) is not str or re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', v) is None for v in values):
        return ()
    return tuple(dict.fromkeys(values))


def context_usage(usage):
    """Only explicit provider context counters; token totals aren't a limit."""
    if type(usage) is not dict or set(usage) != {'used', 'limit'}:
        return None
    used, limit = usage['used'], usage['limit']
    if type(used) is not int or type(limit) is not int or not -(2**53) <= used <= 2**53 or not 1 <= limit <= 2**53:
        return None
    percent = max(0, min(100, (used * 200 + limit) // (2 * limit)))
    return used, limit, percent


class ModelControls:
    def __init__(self, panel, layout):
        self.panel = panel
        self.controller = getattr(panel.host, 'chatgpt_controller', None)
        self.connection = getattr(panel.host, 'chatgpt_panel', None)
        self.settings = getattr(panel.host, 'settings', None)
        self.binding = None
        self.restored = False
        self.model = QComboBox()
        self.effort = QComboBox()
        self.empty = QLabel()
        self.usage = QLabel()
        for widget, name, label in (
            (self.model, 'assistant_model', ui_text('assistant.model')),
            (self.effort, 'assistant_effort', ui_text('assistant.effort')),
            (self.empty, 'assistant_models_empty', ui_text('assistant.models_empty')),
            (self.usage, 'assistant_context_usage', ui_text('assistant.context_unknown')),
        ):
            widget.setObjectName(name)
            widget.setAccessibleName(label)
            if isinstance(widget, QLabel):
                widget.setTextFormat(Qt.TextFormat.PlainText)
                widget.setText(label)
                widget.setWordWrap(True)
            layout.addWidget(widget)
        self.model.currentIndexChanged.connect(self.select_model)
        self.effort.currentIndexChanged.connect(self.persist)
        changed = getattr(self.controller, 'changed', None)
        if changed is not None:
            changed.connect(self.refresh)
        connection_model = getattr(self.connection, 'model', None)
        if connection_model is not None:
            connection_model.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        models = getattr(self.controller, 'models', ())
        models = models if type(models) in (list, tuple) else ()
        chosen = self.model.currentData()
        linked = getattr(self.connection, 'model', None)
        if linked is not None and linked.currentData() in models:
            chosen = linked.currentData()
        preference = None
        if models and not self.restored:
            self.restored = True
            try:
                saved = self.settings.load() if callable(getattr(self.settings, 'load', None)) else {}
                preference = saved.get('assistant_model_preference') if type(saved) is dict else None
                if type(preference) is dict and preference.get('model') in models:
                    chosen = preference['model']
            except Exception:
                pass
        labels = dict(getattr(self.controller, 'model_labels', ()) or ())
        self.model.blockSignals(True)
        self.model.clear()
        for slug in models:
            if type(slug) is str and re.fullmatch(MODEL, slug):
                self.model.addItem(labels.get(slug, slug), slug)
        index = self.model.findData(chosen)
        if index >= 0:
            self.model.setCurrentIndex(index)
        self.model.blockSignals(False)
        self.model.setEnabled(self.model.count() > 0)
        self.empty.setVisible(self.model.count() == 0)
        binding = (
            getattr(self.controller, 'active_registration', None),
            self.model.currentData(),
            advertised_efforts(self.controller, self.model.currentData()),
        )
        if binding != self.binding:
            self.binding = binding
            self.reset_effort()
            self.set_usage(None)
        if type(preference) is dict and preference.get('model') == self.model.currentData():
            if linked is not None and linked.currentData() != self.model.currentData():
                index = linked.findData(self.model.currentData())
                if index >= 0:
                    linked.setCurrentIndex(index)
            index = self.effort.findData(preference.get('effort'))
            if index >= 0:
                self.effort.setCurrentIndex(index)
        self.update_send()

    def reset_effort(self):
        values = advertised_efforts(self.controller, self.model.currentData())
        self.effort.blockSignals(True)
        self.effort.clear()
        self.effort.addItem(ui_text('assistant.effort_default') if values else ui_text('assistant.not_provided'), None)
        for value in values:
            self.effort.addItem(value, value)
        self.effort.setEnabled(bool(values))
        self.effort.blockSignals(False)

    def select_model(self, *_):
        self.reset_effort()
        self.set_usage(None)
        linked = getattr(self.connection, 'model', None)
        if linked is not None:
            index = linked.findData(self.model.currentData())
            if index >= 0 and linked.currentIndex() != index:
                # Reuse D9 invalidation and campaign-usage invalidation signals.
                linked.setCurrentIndex(index)
        self.binding = None
        self.refresh()
        self.persist()

    def validate(self):
        slug, effort = self.model.currentData(), self.effort.currentData()
        if type(slug) is not str or re.fullmatch(MODEL, slug) is None or slug not in getattr(self.controller, 'models', ()):
            raise ValueError('agent_tool_refused')
        if effort is not None and effort not in advertised_efforts(self.controller, slug):
            raise ValueError('agent_tool_refused')
        return slug, effort

    def persist(self, *_):
        try:
            slug, effort = self.validate()
            if callable(getattr(self.settings, 'load', None)) and callable(getattr(self.settings, 'save', None)):
                saved = self.settings.load()
                if type(saved) is dict:
                    self.settings.save({**saved, 'assistant_model_preference': {'model': slug, 'effort': effort}})
        except Exception:
            pass

    def set_usage(self, usage):
        values = context_usage(usage)
        self.usage.setText(ui_text('assistant.context_unknown') if values is None else ui_text('assistant.context_usage').format(*values))

    def update_send(self, *_, idle=False):
        self.panel.send.setEnabled((idle or not self.panel.worker.active) and self.model.count() > 0)
