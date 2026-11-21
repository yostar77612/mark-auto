"""Stock screener thresholds. The engine validates ranges and persists; this dialog only edits and sends."""

from dataclasses import replace
from decimal import Decimal

from PySide6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.screener import RANGES

# name -> (kind, scale): the amount is shown in units of 10,000 NT$ (萬) and stored in NT$.
FIELDS = (
    ('min_price', 'decimal', 1),
    ('min_volume_lots', 'int', 1),
    ('warmup_minutes', 'int', 1),
    ('list_rows', 'int', 1),
    ('surge_ratio', 'decimal', 1),
    ('red_change_pct', 'decimal', 1),
    ('black_change_pct', 'decimal', 1),
    ('near_extreme_pct', 'decimal', 1),
    ('quiet_amount', 'int', 10_000),
)
FLAGS = ('download_red', 'download_black')


class ScreenerSettingsDialog(QDialog):
    def __init__(self, facade, params, submit, parent=None, on_saved=lambda: None):
        super().__init__(parent)
        self.facade, self.params, self.defer, self.on_saved = facade, params, submit, on_saved
        self.setObjectName('screener_settings')
        self.setWindowTitle(ui_text('screen.settings_title'))
        self.setAccessibleName(ui_text('screen.settings_title'))
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.inputs = {}
        for name, kind, scale in FIELDS:
            low, high = RANGES[name]
            if kind == 'int':
                widget = QSpinBox()
                widget.setRange(int(low // scale), min(int(high // scale), 2_000_000_000))
                widget.setValue(int(getattr(params, name) // scale))
            else:
                widget = QDoubleSpinBox()
                widget.setDecimals(2)
                widget.setSingleStep(0.1)
                widget.setRange(float(low), float(high))
                widget.setValue(float(getattr(params, name)))
            widget.setObjectName('screener_settings_' + name)
            widget.setAccessibleName(ui_text('screen.set_' + name))
            self.inputs[name] = (widget, kind, scale)
            form.addRow(ui_text('screen.set_' + name), widget)
        self.flags = {}
        for name in FLAGS:
            box = QCheckBox(ui_text('screen.set_' + name))
            box.setObjectName('screener_settings_' + name)
            box.setAccessibleName(ui_text('screen.set_' + name))
            box.setChecked(getattr(params, name))
            self.flags[name] = box
            form.addRow(box)
        self.message = QLabel()
        self.message.setObjectName('screener_settings_message')
        self.message.setAccessibleName(ui_text('screen.settings_title'))
        root.addWidget(self.message)
        buttons = QHBoxLayout()
        save = QPushButton(ui_text('screen.set_save'))
        save.setObjectName('screener_settings_save')
        save.setAccessibleName(ui_text('screen.set_save'))
        save.clicked.connect(lambda checked=False: self.save())
        cancel = QPushButton(ui_text('screen.set_cancel'))
        cancel.setObjectName('screener_settings_cancel')
        cancel.setAccessibleName(ui_text('screen.set_cancel'))
        cancel.clicked.connect(lambda checked=False: self.reject())
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def collect(self):
        values = {name: box.isChecked() for name, box in self.flags.items()}
        for name, (widget, kind, scale) in self.inputs.items():
            values[name] = widget.value() * scale if kind == 'int' else Decimal(str(round(widget.value(), 2)))
        return replace(self.params, **values)

    def save(self):
        try:
            params = self.collect()
        except Exception:
            self.message.setText(ui_text('screen.set_failed'))
            return

        def completed(value, error):
            if error is not None:
                self.message.setText(ui_text('screen.set_failed'))
                return
            self.params = value
            self.on_saved()
            self.accept()

        self.defer(lambda: self.facade.screener_settings(params), completed)
