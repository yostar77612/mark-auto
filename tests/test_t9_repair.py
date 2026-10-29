"""T9 repair: keyboard expiry parity and an independent legacy oracle."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QTableWidgetItem

from desktop_app.components.forms import BacktestForm
from quantlab.core import ValidationError, canonical_json, content_hash
from tests.test_ui_operations_registry import exercise, old_module
import desktop_app.shell.main_window as ui


class ExpiryKeyboardParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_keyboard_and_calendar_match_legacy_payload_and_hash(self):
        old, typed = BacktestForm(), BacktestForm()
        self.addCleanup(old.close)
        self.addCleanup(typed.close)
        old.expiries.add_row()
        values = ('TAIFEX:TMF:202610', '2026-10-21')
        for column, value in enumerate(values):
            old.expiries.table.setItem(0, column, QTableWidgetItem(value))
        typed.show()
        self.app.processEvents()
        QTest.mouseClick(typed.expiries.findChild(QPushButton, 'instrument_expiries_add'), Qt.MouseButton.LeftButton)
        table = typed.expiries.table
        for column, value in enumerate(values):
            table.setCurrentCell(0, column)
            table.edit(table.model().index(0, column))
            self.app.processEvents()
            editor = self.app.focusWidget()
            self.assertIsInstance(editor, QLineEdit)
            QTest.keyClicks(editor, value)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            self.app.processEvents()
        self.assertEqual(typed.build_payload(), old.build_payload())
        self.assertEqual(canonical_json(typed.build_payload()), canonical_json(old.build_payload()))
        self.assertEqual(content_hash(typed.build_payload()), content_hash(old.build_payload()))
        date = table.indexWidget(table.model().index(0, 1))
        self.assertTrue(date.picker.calendarPopup())
        date.picker.setDate(QDate(2026, 10, 20))
        date.picker.setDate(QDate(2026, 10, 21))
        self.assertEqual(date.manual.text(), values[1])
        self.assertEqual(content_hash(typed.build_payload()), content_hash(old.build_payload()))
        for raw in ('2026-02-30', '2026-1-21', '', '20261021'):
            with self.subTest(raw=raw):
                date.manual.setText(raw)
                old.expiries.table.item(0, 1).setText(raw)
                self.assertEqual(table.item(0, 1).text(), raw)
                with self.assertRaises(ValidationError):
                    old.build_payload()
                with self.assertRaises(ValidationError):
                    typed.build_payload()
        date.setText(values[1])
        date.enabled_value.setChecked(False)
        self.assertEqual(date.manual.text(), '')
        with self.assertRaises(ValidationError):
            typed.build_payload()


class LegacyOracleTests(unittest.TestCase):
    def test_current_handler_mutation_does_not_mutate_legacy_oracle(self):
        original = ui._UI_OPERATION_HANDLERS['ui_analysis_preview']

        def mutated(*args, **kwargs):
            return dict(original(*args, **kwargs), repair_mutation=True)

        with old_module() as old:
            self.assertIsNot(old.execute_ui_operation, ui.execute_ui_operation)
            self.assertNotIn('_UI_OPERATION_HANDLERS', vars(old))
            with patch.dict(ui._UI_OPERATION_HANDLERS, ui_analysis_preview=mutated):
                legacy = exercise(old.execute_ui_operation)
                current = exercise(ui.execute_ui_operation)
        self.assertIn('analysis_id', legacy['ui_analysis_preview']['result'])
        self.assertNotIn('repair_mutation', legacy['ui_analysis_preview']['result'])
        self.assertTrue(current['ui_analysis_preview']['result']['repair_mutation'])
        self.assertNotEqual(current['ui_analysis_preview'], legacy['ui_analysis_preview'])


if __name__ == '__main__':
    unittest.main()
