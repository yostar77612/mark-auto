"""Shared page widget construction and advanced-input handling."""

from desktop_theme import set_theme_property
from PySide6.QtCore import Qt
from desktop_strings import ui_text
import json
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QCheckBox,
    QFileDialog as QFileDialog,
    QFormLayout,
    QMessageBox,
    QSizePolicy,
    QGroupBox,
)
from .bindings import PageContext
from .error_guidance import run_inline


PANEL_TITLE_HEIGHT = 19


class PanelCard(QWidget):
    """Shared panel chrome; callers supply catalog titles and own all actions."""

    def __init__(self, title='', parent=None):
        super().__init__(parent)
        self.setObjectName('panel_card')
        set_theme_property(self, 'themePart', 'panelCard')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.title_bar = QWidget(self)
        self.title_bar.setObjectName('panel_title_bar')
        self.title_bar.setFixedHeight(PANEL_TITLE_HEIGHT)
        self.title_bar.setAccessibleName(title or ui_text('panel.untitled'))
        set_theme_property(self.title_bar, 'themePart', 'panelTitleBar')
        header = QHBoxLayout(self.title_bar)
        header.setContentsMargins(8, 0, 8, 0)
        # Reuse Qt's section-title renderer so replacing a QGroupBox does not
        # add another visible QLabel to the page's explanation budget.
        self.title_label = QGroupBox(title)
        self.title_label.setFlat(True)
        self.title_label.setObjectName('panel_title')
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setAccessibleName(title or ui_text('panel.untitled'))
        set_theme_property(self.title_label, 'themePart', 'panelTitle')
        header.addWidget(self.title_label, 1)
        self.controls = QWidget(self.title_bar)
        self.controls.setObjectName('panel_controls')
        self.controls.setAccessibleName(ui_text('panel.controls'))
        self.controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._controls_layout = QHBoxLayout(self.controls)
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_layout.setSpacing(4)
        header.addWidget(self.controls, 0, Qt.AlignmentFlag.AlignRight)
        outer.addWidget(self.title_bar)
        # Keep content widgets direct children of the section. Page adapters move
        # sections by an existing inner widget's parentWidget().
        self.content = self
        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        outer.addLayout(self._content_layout, 1)

    def content_layout(self):
        return self._content_layout

    def add_control(self, widget):
        self._controls_layout.addWidget(widget)


class WidgetTools(PageContext):
    def __init__(self, host):
        self.setup_context(host)

    def _button(self, layout, text, name, callback, role='secondary'):
        button = QPushButton(text)
        button.setObjectName(name)
        host = getattr(self, 'host', self)
        owner = getattr(host, 'state', host)
        button.clicked.connect(
            lambda checked=False: self._safe(lambda: run_inline(button, lambda: self._confirm_button(button, callback), owner=owner, layout=layout))
        )
        if role not in ('primary', 'secondary', 'danger'):
            raise ValueError('Unknown button role')
        button.setProperty('role', role)
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch()
        layout.addRow(row) if isinstance(layout, QFormLayout) else layout.addLayout(row)
        self.actions.append(button)
        return button

    def _confirm_button(self, button, callback):
        if button.property('role') == 'danger':
            answer = self.host.question(
                ui_text('ui.confirm_button.danger_title'),
                ui_text('ui.confirm_button.confirmation_question').format(button.text()),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        return callback()

    def _text(self, layout, label, value='', multiline=False):
        layout.addWidget(QLabel(label))
        field = QPlainTextEdit(value) if multiline else QLineEdit(value)
        if multiline:
            field.setMaximumHeight(150)
        layout.addWidget(field)
        return field

    def _advanced(self, layout, title=ui_text('ui.advanced.default_title')):
        title = title if title.startswith(ui_text('ui.advanced.title')) else ui_text('ui.advanced.named_title').format(title)
        key = str(self.stack.count()) + ':' + title
        toggle = QCheckBox(title)
        toggle.setObjectName('advanced_' + str(len(self._section_toggles)))
        self._section_toggles[key] = toggle
        layout.addWidget(toggle)
        box = QWidget()
        inner = QVBoxLayout(box)
        inner.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        box.hide()
        toggle.toggled.connect(box.setVisible)
        toggle.toggled.connect(lambda checked: self._safe(self._save_section_preferences))
        return inner

    def _save_section_preferences(self):
        if self.settings is None or getattr(self, '_restoring_sections', False):
            return
        value = self.settings.load()
        value['advanced_sections'] = {key: toggle.isChecked() for key, toggle in self._section_toggles.items()}
        self.settings.save(value)

    def _payload(self, editor, build):
        text = editor.toPlainText()
        if text != self._advanced_values.get(editor, text):
            return json.loads(text)
        return build()

    def _remember(self, editor):
        self._advanced_values[editor] = editor.toPlainText()

    def _browse(self, target):
        name, _ = self.host.open_file(ui_text('ui.browse.dialog_title'))
        if name:
            target.setText(name)
            self.form_feedback(target, ui_text('ui.browse.selected_file_hint'))
