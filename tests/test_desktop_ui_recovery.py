"""Regression tests for accessible page selection and no-data preference reload."""

import os
import importlib.util

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import QItemSelectionModel, QPointF, QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from desktop_app.shell.main_window import MainWindow
    from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, CredentialVault
    from quantlab.research_core.adapters.workspace_backup import BackupManager


@unittest.skipUnless(HAS_QT, 'Install pinned desktop requirements to test Qt widgets')
class UiRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.network = patch('socket.socket', side_effect=AssertionError('unexpected network'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.launch = patch('subprocess.Popen', side_effect=AssertionError('unexpected child launch'))
        self.launch.start()
        self.addCleanup(self.launch.stop)
        self.secrets = patch.object(CredentialVault, 'load', side_effect=AssertionError('credential values forbidden'))
        self.secrets.start()
        self.addCleanup(self.secrets.stop)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.store = SettingsStore(self.paths.state / 'settings.json')
        self.windows = []
        self.addCleanup(self.close_windows)

    def close_windows(self):
        for window in self.windows:
            window.timer.stop()
            window.close()
            window.deleteLater()
        self.jobs.close()
        self.app.processEvents()

    def window(self):
        window = MainWindow(self.paths, self.jobs, self.store, BackupManager(self.paths, self.jobs))
        window.timer.stop()
        self.windows.append(window)
        return window

    def test_selection_only_switches_all_seven_content_pages(self):
        window = self.window()
        for row in range(window.navigation.count()):
            with self.subTest(page=row):
                window.navigation.selectionModel().select(window.navigation.model().index(row, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.app.processEvents()
                self.assertEqual(window.stack.currentIndex(), row)
                self.assertEqual(window.navigation.currentRow(), row)

    def test_normal_click_navigation_still_switches_content(self):
        window = self.window()
        window.show()
        self.app.processEvents()
        row = 1
        pos = QPointF(window.navigation.visualItemRect(window.navigation.item(row)).center())
        for kind, buttons in [(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)]:
            self.app.sendEvent(window.navigation.viewport(), QMouseEvent(kind, pos, pos, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(window.stack.currentIndex(), row)

    def test_ma_save_and_full_startup_restore_without_data(self):
        first = self.window()
        check, fields = first.market._indicator_widgets['MA']
        fields['periods_0'].setValue(6)
        check.setChecked(False)
        saved = self.store.load()
        self.assertEqual(saved['market']['indicators']['MA'], {'enabled': False, 'periods': [6, 10, 20, 60]})
        first.close()
        reopened = self.window()
        check, fields = reopened.market._indicator_widgets['MA']
        self.assertFalse(check.isChecked())
        self.assertEqual(fields['periods_0'].value(), 6)
        self.assertEqual(reopened.market.preferences()['indicators']['MA'], saved['market']['indicators']['MA'])
        self.assertIn('停用', reopened.market.indicator_summary.text())
        self.assertNotIn('MA 5', reopened.market.indicator_summary.text())
        self.assertFalse((self.paths.state / 'dataset.json').exists())

    def test_no_data_timeframe_change_keeps_saved_global_ma_and_summary(self):
        window = self.window()
        check, fields = window.market._indicator_widgets['MA']
        fields['periods_0'].setValue(6)
        check.setChecked(False)
        window.market.timeframe_combo.setCurrentIndex(2)
        saved = self.store.load()['market']
        self.assertEqual(saved['timeframe'], '5m')
        self.assertEqual(saved['indicators']['MA']['periods'][0], 6)
        window.market.restore_preferences(saved)
        self.assertEqual(window.market._timeframe, '5m')
        self.assertEqual(fields['periods_0'].value(), 6)
        self.assertIn('停用', window.market.indicator_summary.text())
        self.assertEqual(window.market.preferences()['indicators']['MA'], saved['indicators']['MA'])

    def test_ma_configuration_is_global_across_contract_selection(self):
        from decimal import Decimal
        from datetime import datetime, timezone
        from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance

        window = self.window()
        check, fields = window.market._indicator_widgets['MA']
        fields['periods_0'].setValue(6)
        check.setChecked(False)
        snapshots = []
        for month in ('202610', '202611'):
            instrument = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:' + month, month)
            bar = MarketBar(instrument, '2026-10-01', 'day', Decimal(100), Decimal(110), Decimal(90), Decimal(101), 100, interval='session')
            provenance = SourceProvenance(
                'https://example.org/synthetic',
                'a' * 64,
                'synthetic fixture',
                'https://example.org/license',
                datetime(2026, 10, 2, tzinfo=timezone.utc),
                '2026-10-01',
                '2026-10-01',
                '2026-10-01',
            )
            snapshots.append(MarketSeries(instrument, (bar,), provenance))
        window.market.set_market_series(snapshots)
        for snapshot in snapshots:
            window.market.contract_combo.setCurrentIndex(window.market.contract_combo.findData(snapshot.instrument.contract_id))
            self.assertEqual(window.market.preferences()['indicators']['MA'], {'enabled': False, 'periods': [6, 10, 20, 60]})
            self.assertIn('停用', window.market.indicator_summary.text())

    def test_no_data_reload_reflects_other_enabled_indicator(self):
        window = self.window()
        preferences = window.market.preferences()
        preferences['indicators']['MA']['enabled'] = False
        preferences['indicators']['EMA']['enabled'] = True
        window.market.restore_preferences(preferences)
        self.assertIn('EMA', window.market.indicator_summary.text())
        self.assertNotIn('MA 5', window.market.indicator_summary.text())
        self.assertFalse(window.market._indicator_widgets['MA'][0].isChecked())


if __name__ == '__main__':
    unittest.main()
