"""Offline market onboarding and the real Walk-forward display projection."""

from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from desktop_market import sample_market_series
from desktop_pages.market import MarketPage
from desktop_pages.result_widgets import ResultTable
from desktop_pages.wf_wizard import display_result_rows, WindowTimeline
from desktop_presentation import display_number
from desktop_strings import ui_text


class MarketEmptyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        state = SimpleNamespace(_section_toggles={}, jobs=SimpleNamespace(active=False))
        self.host = Mock(state=state)
        self.host.safe.side_effect = lambda callback: callback()
        self.page = MarketPage(self.host)
        self.page.bind_result_layers = Mock()
        self.addCleanup(self.page.deleteLater)

    def test_empty_and_sample_are_offline_and_clearing_restores_actions(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network:
            self.assertFalse(self.page.empty_actions.isHidden())
            self.assertTrue(self.page.refresh_button.isHidden())
            self.assertEqual(self.page.sample_button.text(), ui_text('market.load_sample'))
            self.assertEqual(self.page.official_button.text(), ui_text('market.download_official'))
            # A saved official selection may have no cache on this launch.
            self.page._selected = 'TWSE:TAIEX'
            self.page.sample_button.click()
            self.assertTrue(self.page.empty_actions.isHidden())
            self.assertFalse(self.page.refresh_button.isHidden())
            self.assertIn(ui_text('market.sample_label'), self.page.source_status.text())
            self.assertIn(ui_text('market.sample_label'), self.page.chart.source_label)
            self.assertIn(ui_text('market.sample_label'), self.page.cards['TMF'].text())
            self.assertIn(ui_text('market.not_realtime'), self.page.source_status.text())
            self.assertTrue(self.page.chart.bars)
            network.assert_not_called()
            self.host.start_job.assert_not_called()
        self.page.set_market_series(())
        self.assertFalse(self.page.empty_actions.isHidden())

    def test_official_action_requires_explicit_yes_each_time(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network:
            self.host.question.return_value = QMessageBox.StandardButton.No
            self.page.official_button.click()
            self.host.start_job.assert_not_called()
            self.assertEqual(self.host.question.call_args.args[-1], QMessageBox.StandardButton.No)
            self.host.question.return_value = QMessageBox.StandardButton.Yes
            self.page.official_button.click()
            self.host.start_job.assert_called_once_with('ui_market_refresh', {'network_opt_in': True})
            network.assert_not_called()

    def test_cached_date_and_not_realtime_replace_empty_actions(self):
        sample = sample_market_series()
        cached = replace(sample, provenance=replace(sample.provenance, source_url='https://www.taifex.com.tw', mode='eod', warnings=()))
        self.page.set_quote_series(cached, stale=True)
        self.page.set_market_series(cached, stale=True)
        self.assertTrue(self.page.empty_actions.isHidden())
        self.assertIn(cached.provenance.as_of, self.page.source_status.text())
        self.assertIn(ui_text('market.not_realtime'), self.page.source_status.text())
        self.assertIn(ui_text('market.not_realtime'), self.page.cards['TMF'].text())
        self.assertNotIn(ui_text('market.sample_label'), self.page.source_status.text())
        self.assertNotRegex(self.page.source_status.text(), r'\d{2}:\d{2}|T\d{2}')
        self.page.load_sample_market()
        self.assertEqual(self.page.selected_series(), cached)

    def test_walk_forward_real_result_table_handles_long_and_nonfinite_numbers(self):
        score = {
            'status': 'evaluated',
            'metrics': {'net_pnl': Decimal('7.982496649791122450851234567890'), 'trade_count': float('nan'), 'max_drawdown_pct': float('inf')},
        }
        result = {
            'folds': [
                {
                    'index': 0,
                    'status': 'evaluated',
                    'winner': True,
                    'winner_pool_index': 0,
                    'candidates': [{'pool_index': 0, 'family': 'trend', 'train': score, 'validation': score}],
                }
            ]
        }
        table = ResultTable()
        self.addCleanup(table.deleteLater)
        table.set_rows(display_result_rows(result))
        cells = [table.item(r, c).text() for r in range(table.rowCount()) for c in range(table.columnCount())]
        self.assertIn('7.9825', cells)
        for cell in cells:
            self.assertNotRegex(cell, r'\d+\.\d{5,}|(?i:nan|inf)|Decimal\(')
        self.assertEqual(cells.count(ui_text('presentation.display_number.diagnostics_required')), 4)
        for value in (Decimal('0.123456789012345678901234567890'), float('nan'), float('inf'), -float('inf')):
            self.assertNotRegex(display_number(value), r'\d+\.\d{5,}|(?i:nan|inf)')
        timeline = WindowTimeline()
        self.addCleanup(timeline.deleteLater)
        self.assertEqual([segment[0] for segment in timeline.segments(720)], ['train', 'validation', 'oos', 'holdout'])

    def test_completion_success_arms_timer_and_fade_hides_without_waiting(self):
        from PySide6.QtCore import QTimer
        from desktop_ui import MainWindow
        from quantlab.desktop_runtime import AppPaths
        from tests.test_t9_onboarding import sandbox_ui

        with sandbox_ui(), tempfile.TemporaryDirectory(prefix='t16-notice-') as temporary:
            jobs = SimpleNamespace(active=False, poll=lambda: [], close=Mock())
            window = MainWindow(AppPaths(Path(temporary) / 'workspace').ensure(), jobs)
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                window.notify_local(ui_text('outcome.success.body'), completion=True)
                self.assertTrue(window.notification_timer.isActive())
                self.assertEqual(window.notification_timer.interval(), 5000)
                window.notification_timer.timeout.emit()
                window.notification_fade.finished.emit()
                self.assertTrue(window.notification.isHidden())
            finally:
                window.close()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
