from PySide6.QtWidgets import QDialog, QPushButton
from desktop_app.strings.catalog import ui_text
from typing import Callable
from desktop_app.features.strategy.idea_layout import configure_idea_dialog
from desktop_app.features.strategy.idea_presenter import IdeaPresenter
from desktop_app.features.strategy.idea_rows import IdeaRows
from quantlab.research_core.ports.idea_records import IdeaRecords


class IdeaResearchDialog(QDialog):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.state = host.state
        self.record = None
        self.records: Callable[[], IdeaRecords] = lambda: host.idea_records(self.state.root)
        self.presenter = IdeaPresenter(self)
        self.rows = IdeaRows(self)
        configure_idea_dialog(self)

    def _refresh_model_summary(self):
        panel = getattr(self.state, 'chatgpt_panel', None)
        model = panel.model.currentText() if panel is not None and hasattr(panel, 'model') else ''
        self.model_summary.setText(ui_text('redesign.strategy.model') + ': ' + (model or ui_text('redesign.strategy.model_missing')))

    def showEvent(self, event):
        self._refresh_model_summary()
        super().showEvent(event)

    def _button(self, layout, key, name, callback):
        button = QPushButton(ui_text(key))
        button.setObjectName(name)
        button.clicked.connect(lambda checked=False: self.host.safe(callback))
        layout.addWidget(button)
        return button

    def discovery_mode(self):
        return self.presenter.discovery_mode()

    def _choose(self, mode):
        return self.presenter._choose(mode)

    def _set_fallback(self, visible):
        return self.presenter._set_fallback(visible)

    def busy(self):
        return self.presenter.busy()

    def refresh_controls(self):
        return self.presenter.refresh_controls()

    def _identity(self):
        return self.presenter._identity()

    def _consent(self):
        return self.presenter._consent()

    def _reset_consent(self):
        return self.presenter._reset_consent()

    def start(self):
        return self.presenter.start()

    def retry(self):
        return self.presenter.retry()

    def cancel(self):
        return self.presenter.cancel()

    def clear_temp(self):
        return self.presenter.clear_temp()

    def adopt(self):
        return self.presenter.adopt()

    def apply(self, event):
        return self.presenter.apply(event)

    def _upsert(self, field, key, value):
        return self.presenter._upsert(field, key, value)

    def load_record(self, task_id):
        return self.presenter.load_record(task_id)

    def job_ended(self, kind):
        return self.presenter.job_ended(kind)

    def render_searches(self):
        return self.rows.render_searches()

    def _origin(self, source):
        return self.rows._origin(source)

    def _row_url(self, row):
        return self.rows._row_url(row)

    def render_sources(self):
        return self.rows.render_sources()

    def show_source(self):
        return self.rows.show_source()

    def render_candidates(self):
        return self.rows.render_candidates()

    def show_candidate(self, row):
        return self.rows.show_candidate(row)

    def render_status(self):
        return self.rows.render_status()
