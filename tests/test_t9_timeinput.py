"""Presentation equivalence against the pre-T9 free-text forms and validators."""

from copy import deepcopy
from datetime import datetime
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QDate, QDateTime, QTime, QTimeZone
from PySide6.QtWidgets import QApplication, QDateEdit, QDateTimeEdit, QLineEdit
from desktop_timeinput import DateInput, taipei_to_utc_iso, utc_iso_to_taipei
from desktop_forms import BacktestForm, PaperIntentForm, PaperQuoteForm, PaperPolicyForm, PaperActionForm, utc
from quantlab.core import ValidationError, content_hash, canonical_json, to_dict


class TaipeiInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def same(self, old, new):
        self.assertEqual(old, new)
        self.assertEqual(canonical_json(old), canonical_json(new))
        self.assertEqual(content_hash(old), content_hash(new))

    def edit(self, widget, local):
        widget.enabled_value.setChecked(True)
        widget.picker.setDateTime(
            QDateTime(QDate(local.year, local.month, local.day), QTime(local.hour, local.minute, local.second), QTimeZone.fromSecondsAheadOfUtc(8 * 3600))
        )  # explicit Taipei zone: the host's local zone (CI runs in UTC) must not matter

    def test_clock_matrix_and_utc_hints(self):
        for local, expected in (
            (datetime(2025, 1, 2, 9), '2025-01-02T01:00:00Z'),
            (datetime(2025, 1, 2, 15), '2025-01-02T07:00:00Z'),
            (datetime(2025, 1, 3, 5), '2025-01-02T21:00:00Z'),
            (datetime(2025, 1, 2, 7, 30), '2025-01-01T23:30:00Z'),
        ):
            with self.subTest(local=local):
                widget = DateInput(timestamp=True)
                self.assertIsInstance(widget.picker, QDateTimeEdit)
                self.assertTrue(widget.picker.calendarPopup())
                self.edit(widget, local)
                self.same(utc(expected, 'test'), utc(widget.text(), 'test'))
                self.assertEqual(taipei_to_utc_iso(local), expected)
                self.assertEqual(utc_iso_to_taipei(expected).replace(tzinfo=None), local)
                self.assertIn(expected, widget.hint.text())
                self.assertEqual(widget.picker.date().toString('yyyy-MM-dd'), local.date().isoformat())

    def test_unset_and_invalid_restoration_keep_validation(self):
        for raw in ('', 'bad', '2025-02-30', '2025-01-02T09:00:00+08:00'):
            widget = DateInput(raw, timestamp=True)
            self.assertEqual(widget.text(), raw)
            with self.assertRaises(ValidationError):
                utc(widget.text(), 'test')
        widget = DateInput(timestamp=True)
        widget.picker.setDate(QDate(2025, 1, 2))
        self.assertEqual(widget.text(), '')
        widget.clear()
        self.assertFalse(widget.enabled_value.isChecked())
        self.assertFalse(widget.picker.isEnabled())
        for raw in ('2025-01-02T01:00:00Z', '2025-01-02T01:00:00+00:00', '2025-01-02T01:00:00.123456Z'):
            widget.setText(raw)
            self.assertEqual(widget.text(), raw)
            self.assertEqual(widget.picker.time().hour(), 9)

    def legacy_form(self, factory):
        """Recreate the old string accessor at the unchanged payload boundary."""
        form = factory()
        for key, field in list(form.fields.items()):
            if isinstance(field, DateInput):
                old = QLineEdit(field.text())
                old.setAccessibleName(field.accessibleName())
                form.fields[key] = old
        return form

    def test_every_converted_form_payload_and_hash(self):
        contract = 'TAIFEX:TMF:202501'
        intent = dict(
            client_order_id='t9', strategy_hash='a' * 64, contract_id=contract, quantity=1, side='buy', order_type='market', created_at='2025-01-02T01:00:00Z'
        )
        quote = dict(
            account_id='paper',
            contract_id=contract,
            price='20000',
            timestamp=intent['created_at'],
            trade_date='2025-01-02',
            session_open='2025-01-02T00:45:00Z',
            session_end='2025-01-02T05:45:00Z',
            margin_per_contract='100000',
        )
        from quantlab.reporting import demo_config

        backtest = dict(config=to_dict(demo_config()), start_date='2025-01-01', end_date='2025-01-03')
        for factory, payload in ((PaperIntentForm, intent), (PaperQuoteForm, quote), (BacktestForm, backtest)):
            old, new = self.legacy_form(factory), factory()
            old.from_payload(deepcopy(payload))
            new.from_payload(deepcopy(payload))
            # Exercise native date/time edits for every converted field, including optional dates.
            for key, field in new.fields.items():
                if isinstance(field, DateInput) and field.text():
                    if field.timestamp:
                        self.edit(field, utc_iso_to_taipei(field.text()))
                    else:
                        field.picker.setDate(field.picker.date().addDays(1))
                        field.picker.setDate(QDate.fromString(old.fields[key].text(), 'yyyy-MM-dd'))
            self.same(old.build_payload(), new.build_payload())
            for key, field in new.fields.items():
                if isinstance(field, DateInput):
                    raw = old.fields[key].text()
                    old.fields[key].setText('invalid')
                    field.setText('invalid')
                    with self.assertRaises(ValidationError):
                        old.build_payload()
                    with self.assertRaises(ValidationError):
                        new.build_payload()
                    old.fields[key].setText(raw)
                    field.setText(raw)
        old, new = self.legacy_form(PaperActionForm), PaperActionForm()
        payload = dict(now=intent['created_at'], order_id='t9')
        old.from_payload(payload)
        new.from_payload(payload)
        self.edit(new.fields['now'], datetime(2025, 1, 2, 9))
        self.same(old.build_payload('cancel'), new.build_payload('cancel'))

    def test_night_policy_table_and_expiry_date_paths(self):
        from quantlab.paper import PaperBroker
        from quantlab.core import Instrument

        policy = dict(
            contract_id='TAIFEX:TMF:202501',
            risk_sessions=[
                dict(open='2025-01-02T07:00:00Z', end='2025-01-02T21:00:00Z', trade_date='2025-01-03', source='explicit test source', session='night')
            ],
            margin_schedule=[dict(effective_from='2025-01-03', margin_per_contract='100000', version='test')],
        )
        form = PaperPolicyForm().from_payload(policy)
        for col, local in ((0, datetime(2025, 1, 2, 15)), (1, datetime(2025, 1, 3, 5))):
            editor = form.sessions.table.indexWidget(form.sessions.table.model().index(0, col))
            self.edit(editor, local)
            self.assertIn(policy['risk_sessions'][0][('open', 'end')[col]], editor.hint.text())
        self.same(policy, form.build_payload())
        for table, column, day in ((form.sessions.table, 2, QDate(2025, 1, 3)), (form.margins.table, 0, QDate(2025, 1, 3))):
            editor = table.indexWidget(table.model().index(0, column))
            editor.picker.setDate(day.addDays(1))
            editor.picker.setDate(day)
        self.same(policy, form.build_payload())
        broker = object.__new__(PaperBroker)
        broker.instrument = Instrument(policy['contract_id'])
        broker._risk_sessions = policy['risk_sessions']
        broker._margin_schedule = policy['margin_schedule']
        broker._validate_policy()
        self.assertEqual(broker.quote_policy('2025-01-02T20:00:00Z')['trade_date'], '2025-01-03')
        self.assertEqual(broker.quote_policy('2025-01-02T20:00:00Z')['margin_per_contract'], '100000')
        date_editor = form.margins.table.indexWidget(form.margins.table.model().index(0, 0))
        self.assertIsInstance(date_editor.picker, QDateEdit)
        date_editor.clear()
        with self.assertRaises(ValidationError):
            form.build_payload()
        backtest = BacktestForm()
        backtest.expiries.add_row()
        from PySide6.QtWidgets import QTableWidgetItem

        backtest.expiries.table.setItem(0, 0, QTableWidgetItem('TAIFEX:TMF:202501'))
        editor = backtest.expiries.table.indexWidget(backtest.expiries.table.model().index(0, 1))
        editor.enabled_value.setChecked(True)
        editor.picker.setDate(QDate(2025, 1, 15))
        old = BacktestForm()
        old.expiries.add_row()
        for column, value in enumerate(('TAIFEX:TMF:202501', '2025-01-15')):
            old.expiries.table.setItem(0, column, QTableWidgetItem(value))
        self.same(old.build_payload(), backtest.build_payload())

    def test_history_day_night_payload_strings_unchanged(self):
        from desktop_market import MarketHistoryDialog
        from tests.test_market_history_ui import fill

        for night in (False, True):
            old, new = MarketHistoryDialog(), MarketHistoryDialog()
            for key in ('trade_date', 'open_date', 'end_date'):
                setattr(old, key, QLineEdit())
            fill(old, 'TMF', night=night)
            fill(new, 'TMF', night=night)
            for key in ('trade_date', 'open_date', 'end_date'):
                field = getattr(new, key)
                field.picker.setDate(field.picker.date().addDays(1))
                field.picker.setDate(QDate.fromString(getattr(old, key).text(), 'yyyy-MM-dd'))
            new.confirm.setChecked(True)
            self.same(old.session_payload(), new.session_payload())
            new.open_date.clear()
            with self.assertRaises(ValueError):
                new.session_payload()
            old.close()
            new.close()

    def test_same_value_restoration_keeps_history_confirmation(self):
        from desktop_market import MarketHistoryDialog
        from tests.test_market_history_ui import fill

        dialog = MarketHistoryDialog()
        fill(dialog, 'TMF')
        dialog.confirm.setChecked(True)
        dialog.trade_date.setText(dialog.trade_date.text())
        self.assertTrue(dialog.confirm.isChecked())
        dialog.trade_date.picker.setDate(dialog.trade_date.picker.date().addDays(1))
        self.assertFalse(dialog.confirm.isChecked())
        dialog.close()

    def test_history_required_midnight_and_previous_utc_day(self):
        from desktop_market import MarketHistoryDialog
        from desktop_timeinput import history_utc_hint
        from tests.test_market_history_ui import fill

        for start, end, night, expected_start, expected_end in (
            (datetime(2025, 1, 2, 15), datetime(2025, 1, 3, 5), True, '2025-01-02T07:00:00+00:00', '2025-01-02T21:00:00+00:00'),
            (datetime(2025, 1, 2, 7, 30), datetime(2025, 1, 2, 13, 45), False, '2025-01-01T23:30:00+00:00', '2025-01-02T05:45:00+00:00'),
        ):
            old, new = MarketHistoryDialog(), MarketHistoryDialog()
            for key in ('trade_date', 'open_date', 'end_date'):
                setattr(old, key, QLineEdit())
            for dialog in (old, new):
                fill(dialog, 'TMF', night=night)
                dialog.month.setText('202501')
                dialog.trade_date.setText('2025-01-03' if night else '2025-01-02')
                dialog.open_date.setText(start.date().isoformat())
                dialog.end_date.setText(end.date().isoformat())
                dialog.open_time.setTime(QTime(start.hour, start.minute))
                dialog.end_time.setTime(QTime(end.hour, end.minute))
                dialog.confirm.setChecked(True)
            actual = new.session_payload()
            self.same(old.session_payload(), actual)
            self.assertEqual(actual['open'], expected_start)
            self.assertEqual(actual['end'], expected_end)
            self.assertIn(expected_start.replace('+00:00', 'Z'), history_utc_hint(new.open_date, new.open_time).text())
            self.assertIn(expected_end.replace('+00:00', 'Z'), history_utc_hint(new.end_date, new.end_time).text())
            old.close()
            new.close()
