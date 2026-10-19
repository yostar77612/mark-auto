"""P0-02/03/04/13: offline native-widget presentation contracts."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QMessageBox, QHeaderView
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager
from desktop_ui import MainWindow
from tools.ui_snapshot import page_metrics
from tests.snapshot_cache import default_metrics


class DesktopPolishATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / ('markauto-polish-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.paths = AppPaths(self.root / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.window = MainWindow(self.paths, self.jobs, SettingsStore(self.paths.state / 'settings.json'), BackupManager(self.paths, self.jobs))
        for timer in self.window.findChildren(QTimer):
            timer.stop()
        self.window.resize(1366, 768)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.jobs.close()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        shutil.rmtree(self.root)

    def test_p0_02_roles_names_and_confirmation(self):
        w = self.window
        expected = {'paper_kill', 'paper_cancel', 'restore_backup', 'instrument_expiries_remove', 'risk_sessions_remove', 'margin_schedule_remove'}
        danger = {b.objectName() for b in w.findChildren(QPushButton) if b.property('role') == 'danger'}
        self.assertEqual(danger, expected)
        for i in range(w.stack.count()):
            w.navigation.setCurrentRow(i)
            page = w.stack.widget(i)
            primary = [b for b in page.findChildren(QPushButton) if b.property('role') == 'primary']
            self.assertLessEqual(len(primary), 1)
        button = w.findChild(QPushButton, 'paper_kill')
        calls = []
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            w._confirm_button(button, lambda: calls.append(True))
        self.assertEqual(calls, [])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            w._confirm_button(button, lambda: calls.append(True))
        self.assertEqual(calls, [True])

    def test_p0_03_visible_labels_and_units(self):
        w = self.window
        for name in ('bars', 'days', 'replay_bars', 'candidate_choice', 'result_choice', 'provider_mode', 'analysis_saved'):
            field = getattr(w, name)
            labels = [x for x in w.findChildren(QLabel) if x.buddy() is field and x.text()]
            self.assertTrue(labels, name)
            self.assertFalse(labels[0].isHidden(), name)
        self.assertEqual(w.bars.suffix(), ' 根')
        self.assertEqual(w.days.suffix(), ' 日')
        self.assertEqual(w.replay_bars.suffix(), ' 根')
        self.assertEqual(w.chatgpt_panel.timeout.suffix(), ' 秒')
        self.assertEqual(w.bars.value(), 960)

    def test_p0_04_page_names_and_header_widths(self):
        w = self.window
        w.navigation.setCurrentRow(4)
        self.app.processEvents()
        for rows in (w.policy_form.sessions, w.policy_form.margins):
            table = rows.table
            for i in range(table.columnCount()):
                self.assertEqual(table.horizontalHeader().sectionResizeMode(i), QHeaderView.ResizeMode.ResizeToContents)
                self.assertGreaterEqual(table.columnWidth(i), table.fontMetrics().horizontalAdvance(table.horizontalHeaderItem(i).text()) + 12)
        obsolete = '策略' + '與版本'
        root = Path(__file__).resolve().parents[1]
        for path in [root / 'desktop_ui.py', root / 'README.md', *list((root / 'docs').rglob('*.md')), *list((root / 'docs').rglob('*.json'))]:
            if path.name == '06_PRODUCT_OPTIMIZATION_PLAN.md':
                continue  # the plan quotes the obsolete name as its problem statement
            self.assertNotIn(obsolete, path.read_text(encoding='utf-8'), str(path))

    def test_p0_13_all_disabled_actions_have_visible_prerequisite(self):
        w = self.window
        # Visibility is irrelevant to the checked hint/tooltip/hidden flags; a hidden window avoids a full relayout per toggle
        # (this test took ~2 minutes on software-rendering Linux CI, which has a fixed suite time cap).
        w.hide()
        for button in w.findChildren(QPushButton):
            button.setEnabled(False)
            self.assertTrue(button.toolTip(), button.objectName())
            self.assertTrue(button.property('disabled_hint'), button.objectName())
            hints = [x for x in w._disabled_hints if x.button is button]
            self.assertEqual(len(hints), 1, button.objectName())
            self.assertFalse(hints[0].label.isHidden())
            button.setEnabled(True)
            if button.isEnabled():
                self.assertEqual(button.property('disabled_hint'), '')
                self.assertTrue(hints[0].label.isHidden())
            else:
                # A disabled ancestor still requires an explanation.
                self.assertTrue(button.property('disabled_hint'))
                self.assertFalse(hints[0].label.isHidden())

    def test_snapshot_acceptance_1366x768(self):
        metrics = default_metrics()
        for name, page in metrics['pages'].items():
            self.assertEqual(page['unlabeled_inputs'], [], name)
            self.assertLessEqual(page['primary_button_count'], 1, name)
            for button in page['disabled_buttons']:
                self.assertTrue(button['tooltip'], button)
                self.assertEqual(button['tooltip'], button['hint'])
