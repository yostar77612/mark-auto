"""T10 log projection/export is derived only from the real redacted reader."""
import csv
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QCheckBox
from tests.test_t9_onboarding import sandbox_ui
from desktop_pages.log_table import LogTable
from desktop_strings import LOG_OPERATION_NAMES, LOG_EVENT_NAMES, ui_text
from quantlab.desktop_runtime import RedactedEventLog, OPERATIONS, UI_OPERATIONS, RuntimeSafetyError


class LogTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.context = sandbox_ui(); self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory(prefix='t10-logs-')
        self.addCleanup(self.temp.cleanup)
        self.log = RedactedEventLog(Path(self.temp.name) / 'events.jsonl')
        self.table = LogTable(); self.addCleanup(self.table.deleteLater)

    def seed(self):
        with patch('quantlab.desktop_runtime.time.time', return_value=1704067200):
            for event in ('started', 'progress', 'result', 'error', 'cancelled'):
                self.log.append('ui_demo', event)
        self.table.load(self.log.tail())

    def test_fixed_code_names_taipei_columns_and_safe_cells(self):
        self.assertEqual(set(LOG_OPERATION_NAMES), set(OPERATIONS))
        self.assertTrue(UI_OPERATIONS <= LOG_OPERATION_NAMES.keys())
        self.assertEqual(set(LOG_EVENT_NAMES), set(RedactedEventLog.EVENTS))
        for key in LOG_OPERATION_NAMES.values():
            self.assertRegex(ui_text(key), r'[\u4e00-\u9fff]')
        self.seed()
        self.assertEqual([self.table.horizontalHeaderItem(i).text() for i in range(3)],
                         [ui_text('logs.time'), ui_text('logs.operation'), ui_text('logs.result')])
        self.assertEqual(self.table.item(0, 0).text(), '2024-01-01 08:00:00')
        self.assertEqual(self.table.item(2, 2).text(), ui_text('logs.event.result'))
        for row in range(self.table.rowCount()):
            for column in range(3):
                self.assertNotRegex(self.table.item(row, column).text(), r'[{}]|\d{10,13}')

    def test_filter_and_export_match_visible_rows_cancel_is_noop(self):
        self.seed()
        toggle = QCheckBox(); self.addCleanup(toggle.deleteLater)
        toggle.toggled.connect(self.table.filter_errors); toggle.setChecked(True)
        self.assertEqual(self.table.rowCount(), 1)
        self.assertEqual(self.table.item(0, 2).text(), ui_text('logs.event.error'))
        destination = Path(self.temp.name) / 'export.csv'
        with patch('desktop_pages.log_table.choose_log_export', return_value=str(destination)):
            self.table.export()
        with destination.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[1:], [list(row) for row in self.table.visible_rows()])
        with patch('desktop_pages.log_table.choose_log_export', return_value=''):
            self.table.export()
        toggle.setChecked(False); self.assertEqual(self.table.rowCount(), 5)

    def test_hostile_inputs_rejected_by_real_redaction_never_reach_export(self):
        secrets = ['sentinel-token-SECRET', r'C:\private\sentinel-account', 'sentinel-response-password']
        for secret in secrets:
            for args, kwargs in (((secret, 'error'), {}), (('ui_demo', secret), {}),
                                 (('ui_demo', 'error'), {'error_code': secret})):
                with self.assertRaises(RuntimeSafetyError): self.log.append(*args, **kwargs)
        self.seed()
        destination = Path(self.temp.name) / 'safe.csv'
        with patch('desktop_pages.log_table.choose_log_export', return_value=str(destination)):
            self.table.export()
        displayed = str(self.table.visible_rows())
        exported = destination.read_text(encoding='utf-8-sig')
        for secret in secrets:
            self.assertNotIn(secret, displayed)
            self.assertNotIn(secret, exported)
            self.assertNotIn(secret, self.log.path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
