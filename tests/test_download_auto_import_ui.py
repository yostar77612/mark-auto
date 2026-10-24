"""Consent, dispatch and result activation through the actual desktop widgets."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from desktop_strings import ui_text
from desktop_ui import MainWindow
from quantlab.core import ValidationError
from quantlab.desktop_runtime import AppPaths, JobManager
from quantlab.reporting import save_dataset, synthetic_dataset


class DownloadAutoImportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.environ.get('MARKAUTO_UI_QA_IMAGES') and os.name == 'nt':
            from PySide6.QtGui import QFont, QFontDatabase

            for face in ('msjh.ttc', 'msjhbd.ttc'):
                QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / face))
            cls.app.setFont(QFont('Microsoft JhengHei UI', 10))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='download-ui-')
        root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'local'), 'APPDATA': str(root / 'roaming')})
        self.environment.start()
        self.paths = AppPaths(root / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.window = MainWindow(self.paths, self.jobs)
        for timer in self.window.findChildren(QTimer):
            timer.stop()
        self.page = self.window.data_page
        self.controls = self.page.download_import
        self.page.sources.setCurrentIndex(2)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.jobs.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def test_default_requires_explicit_settings_and_one_call_consent(self):
        self.assertTrue(self.controls.enabled.isChecked())
        self.assertEqual(self.page.download_button.text(), ui_text('download_import.action'))
        with patch.object(self.window, 'start_job', return_value='fixture-job') as start:
            self.page.network_data.setChecked(True)
            with self.assertRaisesRegex(ValidationError, 'download_import_settings_required'):
                self.page.download_data()
            start.assert_not_called()
            self.assertIn('合約', self.controls.status.text())
            self.assertIn('交易日曆', self.controls.status.text())
            self.controls.contract.setText('TAIFEX:TMF:202610')
            self.controls.calendar.setText('explicit-fixture-calendar.json')
            self.page.days.setValue(2)
            self.assertFalse(self.page.network_data.isChecked())
            self.page.network_data.setChecked(True)
            self.page.download_data()
            start.assert_called_once_with(
                'ui_refresh',
                {
                    'days': 2,
                    'network_opt_in': True,
                    'auto_import': {'calendar': 'explicit-fixture-calendar.json', 'contract': 'TAIFEX:TMF:202610', 'confirmed': True},
                },
            )
            self.assertFalse(self.page.network_data.isChecked())
            start.reset_mock()
            with self.assertRaises(ValidationError):
                self.page.download_data()
            start.assert_not_called()

    def test_mode_change_invalidates_consent_and_download_only_still_works(self):
        self.page.network_data.setChecked(True)
        self.controls.enabled.setChecked(False)
        self.assertFalse(self.page.network_data.isChecked())
        self.assertFalse(self.controls.contract.isEnabled())
        with patch.object(self.window, 'start_job', return_value='fixture-job') as start:
            self.page.network_data.setChecked(True)
            self.page.download_data()
            start.assert_called_once_with('ui_refresh', {'days': 1, 'network_opt_in': True})
        self.page.network_data.setChecked(True)
        self.controls.enabled.setChecked(True)
        self.assertFalse(self.page.network_data.isChecked())

    def test_completed_job_refreshes_active_dataset_and_human_status(self):
        data = synthetic_dataset(120)
        save_dataset(data, self.window.root / 'dataset.json')
        self.window.last_operation = 'ui_refresh'
        self.window.views_page.render_result(
            {'result': {'downloaded_archives': 2, 'auto_import': {'status': 'imported', 'bars': 120, 'contract': 'TAIFEX:TMF:202610'}}}
        )
        self.assertTrue(self.page.next_button.isEnabled())
        self.assertIn('120', self.page.data_card.text())
        self.assertEqual(self.controls.status.text(), ui_text('download_import.completed').format(2, 120, 'TAIFEX:TMF:202610'))

    def test_download_import_gaps_follow_current_job_and_clear_after_success(self):
        from tests.test_data_gaps_f1 import gap

        self.window.last_operation = 'ui_refresh'
        feedback = self.window.job_feedback
        feedback.begin('current-download')
        packet = {'type': 'progress', 'job_id': 'old-download', 'gap_report': {'code': 'validation_failed', 'quality': {'session_coverage_gaps': [gap()]}}}
        self.assertFalse(feedback.accept(self.window, packet))
        self.assertIsNone(self.page.gap_panel)
        packet['job_id'] = 'current-download'
        self.assertTrue(feedback.accept(self.window, packet))
        self.assertEqual(self.page.gap_panel.table.rowCount(), 1)
        self.assertTrue(feedback.accept(self.window, {'type': 'completed', 'job_id': 'current-download'}))
        self.assertTrue(self.page.gap_panel.isHidden())

    def test_download_layout_at_supported_sizes(self):
        from desktop_theme import apply_theme
        from PySide6.QtGui import QFont, QFontDatabase

        destination = os.environ.get('MARKAUTO_UI_QA_IMAGES')
        if destination and os.name == 'nt':
            for face in ('msjh.ttc', 'msjhbd.ttc'):
                QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / face))
            self.window.setFont(QFont('Microsoft JhengHei UI', 10))
        for theme in ('dark', 'light'):
            for width, height in ((1366, 768), (1920, 1080)):
                self.window.resize(width, height)
                self.window.setProperty('appearanceTheme', theme)
                apply_theme(self.window)
                self.app.processEvents()
                for widget in (self.controls.enabled, self.controls.contract, self.controls.calendar, self.page.download_button):
                    self.assertGreater(widget.width(), 40)
                    self.assertGreater(widget.height(), 15)
                if destination:
                    from tools.ui_snapshot import _save_png

                    target = Path(destination)
                    target.mkdir(parents=True, exist_ok=True)
                    _save_png(self.window, target / f'download-auto-import-{theme}-{width}.png', 1)
