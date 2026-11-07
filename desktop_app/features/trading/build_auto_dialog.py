"""Reference-only build form. Qualification and evidence remain in the engine."""

from decimal import Decimal
from uuid import uuid4

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QSpinBox, QVBoxLayout

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.widgets import button, fit_available_screen, label
from quantlab.trading.application.auto_strategy_views import BuildDialogOptions, CandidateSummaryView
from quantlab.trading.application.contracts import AutoBuildRequest, SizingKind, SizingRule
from quantlab.trading.domain.models import HoldingKind


class BuildAutoDialog(QDialog):
    def __init__(self, candidate: CandidateSummaryView, account_ref: str, parent=None):
        super().__init__(parent)
        self.candidate = candidate
        self.account_ref = account_ref
        self.options = BuildDialogOptions()
        self.strategy_id = 'auto-' + uuid4().hex
        self.setObjectName('build_auto_dialog')
        self.setWindowTitle(ui_text('m3.dialog_title'))
        self.setAccessibleName(ui_text('m3.dialog_title'))
        layout = QVBoxLayout(self)
        layout.addWidget(label('m3.dialog_hint'))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.kind = QComboBox()
        for key, kind in (('m3.kind_intraday', HoldingKind.INTRADAY), ('m3.kind_swing', HoldingKind.SWING), ('m3.kind_position', HoldingKind.POSITION)):
            self.kind.addItem(ui_text(key), kind)
        for index in (1, 2):
            self.kind.model().item(index).setEnabled(False)
            self.kind.model().item(index).setToolTip(ui_text('m3.kind_stock_unavailable'))
        self.kind.setToolTip(ui_text('m3.kind_stock_unavailable'))
        self.instrument = QComboBox()
        self.instrument.addItem(ui_text('m3.near_month'), 'TMF_NEAR')
        self.interval = QComboBox()
        self.interval.addItem(ui_text('u3.minute'), '1m')
        self.interval.addItem(ui_text('u3.five_minutes'), '5m')
        self.interval.setCurrentIndex(1)
        self.contracts_size = QSpinBox()
        self.contracts_size.setRange(self.options.min_contracts, self.options.max_contracts)
        self.stop = QDoubleSpinBox()
        self.stop.setRange(0.01, 99.99)
        self.stop.setDecimals(2)
        self.stop.setValue(float(self.options.default_stop_pct * 100))
        for widget, name, key in (
            (self.kind, 'auto_holding_kind', 'm3.field_kind'),
            (self.instrument, 'auto_instrument', 'm3.field_instrument'),
            (self.interval, 'auto_interval', 'm3.field_interval'),
            (self.contracts_size, 'auto_size', 'm3.field_size_contracts'),
            (self.stop, 'auto_stop_pct', 'm3.field_stop'),
        ):
            widget.setObjectName(name)
            widget.setAccessibleName(ui_text(key))
            form.addRow(ui_text(key), widget)
        layout.addLayout(form)
        self.start = QCheckBox(ui_text('m3.field_start_sim'))
        self.start.setObjectName('auto_start_in_sim')
        self.start.setAccessibleName(ui_text('m3.field_start_sim'))
        self.start.setChecked(True)
        layout.addWidget(self.start)
        self.warning = label('m3.dialog_sim_only')
        layout.addWidget(self.warning)
        self.interval.currentIndexChanged.connect(self._warning)
        self._warning()
        layout.addWidget(label('m3.dialog_sim_only'))
        layout.addWidget(label('m3.fingerprint_pending'))
        controls = QHBoxLayout()
        controls.addStretch()
        cancel = button('m3.dialog_cancel', 'auto_cancel_build')
        cancel.clicked.connect(self.reject)
        self.confirm = button('m3.dialog_confirm', 'auto_confirm_build', role='primary')
        self.confirm.clicked.connect(self.accept)
        controls.addWidget(cancel)
        controls.addWidget(self.confirm)
        layout.addLayout(controls)
        self.resize(580, 430)

    def _warning(self):
        self.warning.setText(ui_text('m3.dialog_data_warning').format(self.interval.currentText()))

    def showEvent(self, event):
        super().showEvent(event)
        fit_available_screen(self)

    def request(self) -> AutoBuildRequest:
        return AutoBuildRequest(
            candidate_ref=self.candidate.candidate_ref,
            strategy_id=self.strategy_id,
            account_ref=self.account_ref,
            holding_kind=HoldingKind.INTRADAY,
            instrument_rule=self.instrument.currentData(),
            bar_interval=self.interval.currentData(),
            sizing=SizingRule(SizingKind.FIXED_CONTRACTS, contracts=self.contracts_size.value()),
            protective_stop_pct=Decimal(str(self.stop.value())) / Decimal(100),
            start_in_sim=self.start.isChecked(),
        )
