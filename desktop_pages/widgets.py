"""Shared page widget construction and advanced-input handling."""
from desktop_strings import ui_text
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QPlainTextEdit, QCheckBox, QFileDialog, QFormLayout, QMessageBox
from .bindings import PageContext


class WidgetTools(PageContext):
    def __init__(self, host):
        self.setup_context(host)


    def _button(self, layout, text, name, callback, role='secondary'):
        button = QPushButton(text); button.setObjectName(name); button.clicked.connect(lambda checked=False: self._safe(lambda: self._confirm_button(button, callback)))
        if role not in ('primary', 'secondary', 'danger'):
            raise ValueError('Unknown button role')
        button.setProperty('role', role)
        row = QHBoxLayout(); row.addWidget(button); row.addStretch()
        layout.addRow(row) if isinstance(layout, QFormLayout) else layout.addLayout(row)
        self.actions.append(button)
        return button


    def _confirm_button(self, button, callback):
        if button.property('role') == 'danger':
            answer = self.host.question(ui_text('ui._confirm_button.text_1'), ui_text('ui._confirm_button.text_2').format(button.text()),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        return callback()


    def _text(self, layout, label, value='', multiline=False):
        layout.addWidget(QLabel(label))
        field = QPlainTextEdit(value) if multiline else QLineEdit(value)
        if multiline: field.setMaximumHeight(150)
        layout.addWidget(field)
        return field


    def _advanced(self, layout, title=ui_text('ui.advanced.default_title')):
        title = title if title.startswith(ui_text('ui._advanced.text_1')) else ui_text('ui._advanced.text_2').format(title)
        key = str(self.stack.count()) + ':' + title
        toggle = QCheckBox(title); toggle.setObjectName('advanced_' + str(len(self._section_toggles)))
        self._section_toggles[key] = toggle
        layout.addWidget(toggle)
        box = QWidget(); inner = QVBoxLayout(box); inner.setContentsMargins(0,0,0,0)
        layout.addWidget(box); box.hide(); toggle.toggled.connect(box.setVisible)
        toggle.toggled.connect(lambda checked: self._safe(self._save_section_preferences))
        return inner


    def _save_section_preferences(self):
        if self.settings is None or getattr(self, '_restoring_sections', False): return
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
        name, _ = self.host.open_file(ui_text('ui._browse.text_1'))
        if name:
            target.setText(name)
            self.form_feedback(target, ui_text('ui._browse.text_2'))

