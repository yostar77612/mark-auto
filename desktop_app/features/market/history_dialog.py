from desktop_app.components.validation_feedback import show_feedback

from desktop_app.components.fields import named_field
from desktop_app.strings.catalog import ui_text
from desktop_app.components.timeinput import DateInput, history_utc_hint
from copy import deepcopy
from quantlab.desktop_errors import error_message, exception_code
import re
from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QComboBox,
    QListWidget,
    QCheckBox,
    QSpinBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QTimeEdit,
    QFormLayout,
)
from desktop_app.features.market.rows import _label


class MarketHistoryDialog(QDialog):
    """Typed, local-only import request. Dates are never inferred from a clock/calendar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(ui_text('market.init.import_history'))
        self.resize(800, 720)
        self.sessions = []
        self._payload = None
        layout = QVBoxLayout(self)
        layout.addWidget(_label(ui_text('market.init.history_source_hint'), 'history_disclosure'))
        self.path = named_field(QLineEdit(), 'history_path', ui_text('market.init.file_path'))
        self.path.setPlaceholderText(ui_text('market.init.browse_history'))
        file_row = QHBoxLayout()
        file_row.addWidget(self.path)
        self.browse = named_field(QPushButton(ui_text('market.init.browse_file')), 'history_browse', ui_text('market.init.history_file_accessible_name'))
        self.browse.clicked.connect(self.choose_file)
        file_row.addWidget(self.browse)
        layout.addLayout(file_row)
        form = QFormLayout()
        layout.addLayout(form)
        self.product = named_field(QComboBox(), 'history_product', ui_text('market.init.product'))
        for label, value in [
            (ui_text('market.init.index_futures'), 'TX'),
            (ui_text('market.init.mini_futures'), 'MTX'),
            (ui_text('market.init.micro_futures'), 'TMF'),
        ]:
            self.product.addItem(label, value)
        form.addRow(ui_text('market.init.product_caption'), self.product)
        self.month = named_field(QLineEdit(), 'history_month', ui_text('market.init.expiry_month'))
        self.month.setPlaceholderText(ui_text('market.init.expiry_month_placeholder'))
        form.addRow(ui_text('market.init.expiry_month_required'), self.month)
        self.expiry_type = named_field(QComboBox(), 'history_expiry_type', ui_text('market.init.contract_type'))
        self.expiry_type.addItem(ui_text('market.init.monthly_contract'), 'monthly')
        self.expiry_type.addItem(ui_text('market.init.weekly_contract'), 'weekly')
        self.week = named_field(QSpinBox(), 'history_week', ui_text('market.init.expiry_week'))
        self.week.setRange(1, 5)
        self.week.setEnabled(False)
        expiry_row = QHBoxLayout()
        expiry_row.addWidget(self.expiry_type)
        expiry_row.addWidget(self.week)
        form.addRow(ui_text('market.init.contract_type_caption'), expiry_row)
        self.trade_date = named_field(DateInput(), 'history_trade_date', ui_text('market.init.trading_day'))
        self.trade_date.setPlaceholderText(ui_text('market.init.trading_day_hint'))
        form.addRow(ui_text('market.init.trading_day_required'), self.trade_date)
        self.session = named_field(QComboBox(), 'history_session', ui_text('market.init.session_kind'))
        self.session.addItem(ui_text('market.init.day_session'), 'day')
        self.session.addItem(ui_text('market.init.night_session'), 'night')
        form.addRow(ui_text('market.init.session_caption'), self.session)
        self.open_date = named_field(DateInput(), 'history_open_date', ui_text('market.init.open_date'))
        self.open_date.setPlaceholderText('YYYY-MM-DD')
        self.end_date = named_field(DateInput(), 'history_end_date', ui_text('market.init.close_date'))
        self.end_date.setPlaceholderText(ui_text('market.init.date_hint'))
        self.open_time = named_field(QTimeEdit(QTime(8, 45)), 'history_open_time', ui_text('market.init.open_time'))
        self.end_time = named_field(QTimeEdit(QTime(13, 45)), 'history_end_time', ui_text('market.init.close_time'))
        for widget in (self.open_time, self.end_time):
            widget.setDisplayFormat('HH:mm')
        for title, date_widget, time_widget in [
            (ui_text('market.init.open_time_caption'), self.open_date, self.open_time),
            (ui_text('market.init.close_time_caption'), self.end_date, self.end_time),
        ]:
            row = QHBoxLayout()
            row.addWidget(date_widget)
            row.addWidget(time_widget)
            row.addWidget(history_utc_hint(date_widget, time_widget, self))
            form.addRow(title, row)
        self.include_end = named_field(QCheckBox(ui_text('market.init.include_close')), 'history_include_end', ui_text('market.init.include_close_caption'))
        form.addRow(self.include_end)
        self.source = _label('', 'history_product_source')
        layout.addWidget(self.source)
        layout.addWidget(_label(ui_text('market.init.session_defaults_hint'), 'history_policy_disclosure'))
        self.confirm = named_field(QCheckBox(ui_text('market.init.session_consent')), 'history_confirm', ui_text('market.init.confirm_session'))
        layout.addWidget(self.confirm)
        row = QHBoxLayout()
        self.add = named_field(QPushButton(ui_text('market.init.add_confirmed_session')), 'history_add_session', ui_text('market.init.add_session'))
        self.add.clicked.connect(self.add_session)
        row.addWidget(self.add)
        self.remove = named_field(QPushButton(ui_text('market.init.remove_selected_session')), 'history_remove_session', ui_text('market.init.remove_session'))
        self.remove.clicked.connect(self.remove_session)
        row.addWidget(self.remove)
        layout.addLayout(row)
        self.session_list = named_field(QListWidget(), 'history_sessions', ui_text('market.init.confirmed_sessions'))
        layout.addWidget(self.session_list)
        self.error = _label('', 'history_error')
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ui_text('market.init.import_confirmed_sessions'))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(ui_text('market.init.cancel'))
        self.buttons.accepted.connect(self.accept_import)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for widget in (self.month, self.trade_date, self.open_date, self.end_date):
            widget.textChanged.connect(self._unconfirm)
        for widget in (self.product, self.expiry_type):
            widget.currentIndexChanged.connect(self._unconfirm)
        self.week.valueChanged.connect(self._unconfirm)
        for widget in (self.open_time, self.end_time):
            widget.timeChanged.connect(self._unconfirm)
        self.include_end.toggled.connect(self._unconfirm)
        self.session.currentIndexChanged.connect(self._session_defaults)
        self.expiry_type.currentIndexChanged.connect(lambda: self.week.setEnabled(self.expiry_type.currentData() == 'weekly'))
        self.product.currentIndexChanged.connect(self._source_label)
        self._source_label()
        from desktop_app.components.expiry_inputs import attach_history_picker

        attach_history_picker(self, form)

    def _unconfirm(self, *args):
        self.confirm.setChecked(False)

    def _source_label(self, *args):
        from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES

        self.source.setText(ui_text('market.source_label.session_rule_reference').format(PRODUCT_SOURCES[self.product.currentData()]))

    def _session_defaults(self, *args):
        night = self.session.currentData() == 'night'
        self.open_time.setTime(QTime(15, 0) if night else QTime(8, 45))
        self.end_time.setTime(QTime(5, 0) if night else QTime(13, 45))
        self._unconfirm()

    def choose_file(self):
        name, _ = QFileDialog.getOpenFileName(self, ui_text('market.choose_file.dialog_title'), '', 'TAIFEX CSV / RPT (*.csv *.rpt *.CSV *.RPT)')
        if name:
            self.path.setText(name)

    def session_payload(self):
        from datetime import date, datetime, timezone, timedelta
        from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES, session_from_dict

        if not self.confirm.isChecked():
            raise ValueError('history_confirmation_required')
        month = self.month.text().strip()
        if not re.fullmatch('\\d{4}(?:0[1-9]|1[0-2])', month):
            raise ValueError('history_expiry_invalid')
        expiry = month + ('W' + str(self.week.value()) if self.expiry_type.currentData() == 'weekly' else '')

        def local_time(field, clock):
            value = field.text().strip()
            if not re.fullmatch('\\d{4}-\\d{2}-\\d{2}', value):
                raise ValueError('history_date_invalid')
            try:
                day = date.fromisoformat(value)
            except ValueError:
                raise ValueError('history_date_invalid') from None
            return (
                datetime(day.year, day.month, day.day, clock.time().hour(), clock.time().minute(), tzinfo=timezone(timedelta(hours=8)))
                .astimezone(timezone.utc)
                .isoformat()
            )

        product = self.product.currentData()
        value = dict(
            contract_id=f'TAIFEX:{product}:{expiry}',
            trade_date=self.trade_date.text().strip(),
            session=self.session.currentData(),
            open=local_time(self.open_date, self.open_time),
            end=local_time(self.end_date, self.end_time),
            include_end=self.include_end.isChecked(),
            source=PRODUCT_SOURCES[product],
        )
        try:
            session_from_dict(value)
        except (ValueError, TypeError, KeyError):
            raise ValueError('history_session_invalid') from None
        return value

    def add_session(self):
        try:
            if len(self.sessions) >= 128:
                raise ValueError('history_session_limit')
            value = self.session_payload()
            if value in self.sessions:
                raise ValueError('history_session_duplicate')
            from datetime import datetime

            for existing in self.sessions:
                if existing['contract_id'] != value['contract_id']:
                    continue
                if (existing['trade_date'], existing['session']) == (value['trade_date'], value['session']):
                    raise ValueError('history_session_day_overlap')
                a, b = (datetime.fromisoformat(existing['open']), datetime.fromisoformat(existing['end']))
                c, d = (datetime.fromisoformat(value['open']), datetime.fromisoformat(value['end']))
                if max(a, c) < min(b, d) or (b == c and existing['include_end']) or (d == a and value['include_end']):
                    raise ValueError('history_session_overlap')
            self.sessions.append(value)
            label = ui_text('market.add_session.session_summary').format(
                value['contract_id'],
                value['trade_date'],
                value['session'],
                self.open_date.text(),
                self.open_time.text(),
                self.end_date.text(),
                self.end_time.text(),
                ui_text('market.add_session.included') if value['include_end'] else ui_text('market.add_session.excluded'),
            )
            self.session_list.addItem(label)
            self.confirm.setChecked(False)
            self.error.clear()
        except (ValueError, TypeError, KeyError) as exc:
            show_feedback(self.error, error_message(exception_code(exc)))

    def remove_session(self):
        row = self.session_list.currentRow()
        if row >= 0:
            self.sessions.pop(row)
            self.session_list.takeItem(row)

    def request_payload(self):
        from pathlib import Path

        path = self.path.text().strip()
        if not path or Path(path).suffix.lower() not in ('.csv', '.rpt'):
            raise ValueError('history_file_required')
        if not self.sessions:
            raise ValueError('history_sessions_required')
        return {'history_import': True, 'local_path': path, 'sessions': deepcopy(self.sessions), 'dated_policy_confirmed': True}

    def accept_import(self):
        try:
            self._payload = self.request_payload()
        except ValueError as exc:
            show_feedback(self.error, error_message(exception_code(exc)))
            return
        self.accept()

    def payload(self):
        if self._payload is None:
            raise ValueError(ui_text('market.payload.confirmation_required'))
        return deepcopy(self._payload)
