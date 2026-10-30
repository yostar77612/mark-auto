"""Read-only backup metadata and an optional informational restore preview."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget, QLineEdit

from desktop_app.components.privacy import bind_text, enabled
from desktop_app.strings.catalog import ui_text
from quantlab.backup_inspection import human_size, identity, inspect_archive, latest_metadata, local_time
from quantlab.desktop_errors import error_message


class BackupInspectionPanel(QWidget):
    def __init__(self, page, *, format_time=local_time):
        super().__init__(page)
        self.page = page
        self.format_time = format_time
        self.preview = None
        self.selected = ''
        self.session_archive = None
        self.metadata = None
        layout = QVBoxLayout(self)
        self.latest = QLabel()
        self.summary = QLabel()
        for label in (self.latest, self.summary):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.preview_button = QPushButton(ui_text('backup_inspection.preview'))
        self.preview_button.setObjectName('preview_backup')
        self.preview_button.setProperty('role', 'secondary')
        self.preview_button.clicked.connect(self.inspect)
        layout.addWidget(self.preview_button)
        page.backup_path.textChanged.connect(self.invalidate)
        bind_text(self, self.render)
        self.refresh()

    def refresh(self, archive=None):
        if archive:
            self.session_archive = archive
        self.metadata = latest_metadata(self.page.automatic_backup_panel.scheduler.path, session_archive=self.session_archive)
        self.render()

    def invalidate(self):
        self.preview = None
        self.selected = ''
        self.render()

    def ready(self):
        if self.preview is None or self.preview.error_code or self.selected != self.page.backup_path.text():
            return False
        try:
            return identity(self.selected) == self.preview.identity
        except (OSError, ValueError):
            return False

    def inspect(self):
        self.selected = self.page.backup_path.text()
        self.preview = inspect_archive(self.selected)
        self.render()

    def render(self):
        private = enabled(self)
        masked = ui_text('backup_inspection.masked')
        self.page.backup_path.setEchoMode(QLineEdit.EchoMode.Password if private else QLineEdit.EchoMode.Normal)
        value = self.metadata
        formatted = ui_text('backup_inspection.unavailable')
        if value is not None and not private:
            try:
                formatted = self.format_time(value.modified)
            except (ValueError, OSError, OverflowError):
                pass
        self.latest.setText(
            ui_text('backup_inspection.latest').format(
                masked if private else formatted,
                masked if private else human_size(value.size) if value else ui_text('backup_inspection.unavailable'),
            )
        )
        if self.preview is None:
            text = ui_text('backup_inspection.optional')
        elif self.preview.error_code:
            text = error_message(self.preview.error_code)
        else:
            value = self.preview
            text = ui_text('backup_inspection.summary').format(value.count, masked if private else '\n'.join(value.names), value.hidden, value.truncated)
        self.summary.setText(text)
