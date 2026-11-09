"""Sector alert thresholds. The engine validates ranges and persists; this dialog only edits and sends."""

from dataclasses import replace
from decimal import Decimal

from PySide6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.sector_alerts import RANGES

# name -> (kind, scale): amounts are shown in units of 10,000 NT$ (萬) and stored in NT$.
FIELDS = (
    ('snapshot_seconds', 'int', 1),
    ('burst_multiple', 'decimal', 1),
    ('burst_floor', 'int', 10_000),
    ('baseline_minutes', 'int', 1),
    ('direction_pct', 'decimal', 1),
    ('warmup_minutes', 'int', 1),
    ('flow_minutes', 'int', 1),
    ('flow_floor', 'int', 10_000),
    ('flow_multiple', 'decimal', 1),
    ('big_order', 'int', 10_000),
    ('monitor_groups', 'int', 1),
    ('monitor_keep_minutes', 'int', 1),
    ('monitor_budget', 'int', 1),
    ('cooldown_minutes', 'int', 1),
)


class SectorAlertSettingsDialog(QDialog):
    def __init__(self, facade, params, submit, parent=None, on_saved=lambda: None):
        super().__init__(parent)
        self.facade, self.params, self.submit, self.on_saved = facade, params, submit, on_saved
        self.setObjectName('sector_settings')
        self.setWindowTitle(ui_text('sector.settings_title'))
        self.setAccessibleName(ui_text('sector.settings_title'))
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.burst = QCheckBox(ui_text('sector.settings_burst'))
        self.burst.setObjectName('sector_settings_burst')
        self.burst.setAccessibleName(ui_text('sector.settings_burst'))
        self.burst.setChecked(params.burst_enabled)
        self.flow = QCheckBox(ui_text('sector.settings_flow'))
        self.flow.setObjectName('sector_settings_flow')
        self.flow.setAccessibleName(ui_text('sector.settings_flow'))
        self.flow.setChecked(params.flow_enabled)
        form.addRow(self.burst)
        form.addRow(self.flow)
        self.inputs = {}
        for name, kind, scale in FIELDS:
            low, high = RANGES[name]
            if kind == 'int':
                widget = QSpinBox()
                widget.setRange(int(low // scale), min(int(high // scale), 2_000_000))
                widget.setValue(int(getattr(params, name) // scale))
            else:
                widget = QDoubleSpinBox()
                widget.setDecimals(1 if name != 'direction_pct' else 2)
                widget.setSingleStep(0.1)
                widget.setRange(float(low), float(high))
                widget.setValue(float(getattr(params, name)))
            widget.setObjectName('sector_settings_' + name)
            widget.setAccessibleName(ui_text('sector.settings_' + name))
            self.inputs[name] = (widget, kind, scale)
            form.addRow(ui_text('sector.settings_' + name), widget)
        self.message = QLabel()
        self.message.setObjectName('sector_settings_message')
        self.message.setAccessibleName(ui_text('sector.settings_title'))
        root.addWidget(self.message)
        buttons = QHBoxLayout()
        save = QPushButton(ui_text('sector.settings_save'))
        save.setObjectName('sector_settings_save')
        save.setAccessibleName(ui_text('sector.settings_save'))
        save.clicked.connect(lambda checked=False: self.save())
        cancel = QPushButton(ui_text('sector.settings_cancel'))
        cancel.setObjectName('sector_settings_cancel')
        cancel.setAccessibleName(ui_text('sector.settings_cancel'))
        cancel.clicked.connect(lambda checked=False: self.reject())
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def collect(self):
        values = {'burst_enabled': self.burst.isChecked(), 'flow_enabled': self.flow.isChecked()}
        for name, (widget, kind, scale) in self.inputs.items():
            values[name] = widget.value() * scale if kind == 'int' else Decimal(str(round(widget.value(), 2)))
        return replace(self.params, **values)

    def save(self):
        try:
            params = self.collect()
        except Exception:
            self.message.setText(ui_text('sector.settings_failed'))
            return

        def completed(value, error):
            if error is not None:
                self.message.setText(ui_text('sector.settings_failed'))
                return
            self.params = value
            self.on_saved()
            self.accept()

        self.submit(lambda: self.facade.sector_settings(params), completed)
