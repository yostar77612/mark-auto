"""Cheap saved-series overlay checks, without worker or provider execution."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QListWidget, QVBoxLayout, QWidget

import desktop_privacy as privacy
from desktop_pages.compare_equity import CAP, PAINT_LIMIT, PATTERNS, EquityOverlay, attach_overlay, drawdown, paint_points, project_equity
from desktop_pages.compare_table import FIELDS, SavedResultsTable, SideBySideTable, saved_row
from desktop_strings import ui_text


def rows(values, start=date(2026, 1, 1)):
    return [{'trade_date': (start + timedelta(days=i)).isoformat(), 'equity': value} for i, value in enumerate(values)]


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_known_drawdown_and_dropped_values(self):
        points, count = project_equity(rows([100, 120, 90, 150, 75, float('nan'), float('inf')]))
        self.assertEqual(count, 2)
        self.assertEqual([value for _, value in drawdown(points)], list(map(Decimal, ('0', '0', '.25', '0', '.5'))))
        for corrupt in (None, {}, 'bad'):
            self.assertEqual(project_equity(corrupt), ((), 0))
        self.assertEqual(project_equity([None, {}, {'equity': 'bad', 'trade_date': 'bad'}]), ((), 3))
        corrupt = SimpleNamespace(manifest={'strategy': {}}, metrics={}, equity=None)
        self.assertEqual(saved_row(corrupt, 0)['_overlay'], ((), 0))
        parent = QWidget()
        panel = EquityOverlay(parent)
        panel.set_records([('A', project_equity(rows(['1e-300', '1e300']))[0], 0)])
        self.assertEqual(panel.canvas.dropped, 1)

    def test_date_alignment_shared_ticks_and_gaps(self):
        parent = QWidget()
        panel = EquityOverlay(parent)
        first, _ = project_equity(rows([100, 110, 90]))
        second, _ = project_equity(rows([50, 60], date(2026, 1, 3)))
        panel.set_records([('A', first, 0), ('B', second, 0)])
        self.assertEqual(panel.canvas.axes()[0], panel.canvas.axes()[1])
        self.assertEqual(panel.canvas.x_range, (date(2026, 1, 1).toordinal(), date(2026, 1, 4).toordinal()))
        self.assertNotIn(first[0][0], panel.canvas.series[1][1])
        reduced = paint_points((first[0], first[2]))
        self.assertNotEqual(reduced[0][2], reduced[1][2])
        self.assertEqual(panel.canvas.series[1][1][second[0][0]], Decimal(1))
        self.assertIn('1.0', panel.summary.text())

    def test_empty_one_many_cap_and_bounded_painting(self):
        parent = QWidget()
        panel = EquityOverlay(parent)
        panel.set_records([])
        self.assertFalse(panel.canvas.series)
        points, _ = project_equity(rows([100, 110]))
        panel.set_records([('A', points, 0)])
        self.assertEqual(len(panel.canvas.series), 1)
        panel.set_records([('A', points, 0)] * (CAP + 1))
        self.assertEqual(len(panel.canvas.series), CAP)
        self.assertEqual(len(set(PATTERNS)), CAP)
        self.assertIn(ui_text('compare.overlay.cap').format(CAP, CAP + 1), panel.summary.text())
        large = tuple((i, Decimal(i + 1)) for i in range(100000))
        self.assertLessEqual(len(paint_points(large)), PAINT_LIMIT)
        panel.canvas.resize(700, 300)
        image = QImage(panel.canvas.size(), QImage.Format.Format_ARGB32)
        panel.canvas.render(image)
        self.assertFalse(image.isNull())

    def test_privacy_safe_labels_readout_and_auxiliary_exclusion(self):
        parent = QWidget()
        parent.privacy = SimpleNamespace(enabled=False)
        panel = EquityOverlay(parent)
        source = SimpleNamespace(
            manifest={'strategy': {}, 'dataset_manifest': {'coverage': {'start': '2026-01-01', 'end': '2026-01-03'}}},
            metrics={},
            equity=rows([100, 125]) + [{'trade_date': '2026-01-03', 'equity': '9999', 'split': 'oos'}],
            oos={'equity': 'OOS_SECRET'},
            holdout={'equity': 'HOLDOUT_SECRET'},
        )
        source.equity[0]['holdout'] = 'NESTED_SECRET'
        row = saved_row(source, 0)
        source.manifest['split'] = 'holdout'
        self.assertEqual(saved_row(source, 0)['_overlay'], ((), 0))
        del source.manifest['split']
        panel.set_records([('Private abcdef1234567890', *row['_overlay'])])
        self.assertNotIn('abcdef1234567890', panel.legend.text())
        self.assertIn('Private', panel.legend.text())
        self.assertEqual(len(panel.canvas.days), 2)
        panel.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
        self.assertIn('2026-01-02', panel.detail.text())
        self.assertIn('1.2500', panel.detail.text())
        panel.canvas.resize(700, 300)
        panel.canvas.mouseMoveEvent(SimpleNamespace(position=lambda: QPointF(60, 100)))
        self.assertIn('2026-01-01', panel.detail.text())
        self.assertTrue(panel.accessibleName())
        for private in (True, False):
            parent.privacy.enabled = private
            panel._privacy_render()
            text = '\n'.join((panel.legend.text(), panel.summary.text(), panel.detail.text(), panel.canvas.accessibleDescription(), panel.toolTip()))
            for forbidden in ('OOS_SECRET', 'HOLDOUT_SECRET', 'NESTED_SECRET', '9999'):
                self.assertNotIn(forbidden, text)
            self.assertEqual('Private' in text, not private)
            self.assertEqual('1.0000' in panel.detail.text(), not private)
            if private:
                self.assertEqual(panel.detail.text(), privacy.mask_money(''))

    def test_lazy_selection_and_refresh_are_display_only(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        page.comparison_list = QListWidget(page)
        page.comparison_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        page.saved_results_table = SavedResultsTable(page.comparison_list)
        page.start_job = Mock(side_effect=AssertionError('job invoked'))
        attach_overlay(page, layout)
        self.assertFalse(hasattr(page, '_equity_overlay'))
        points = project_equity(rows([100, 110]))
        page.comparison_list.addItem('A')
        page.comparison_list.item(0).setData(Qt.ItemDataRole.UserRole, 'saved')
        page.saved_results_table.set_saved([('saved', {'name': 'A', '_overlay': points})])
        with (
            patch('quantlab.reporting.load_result', side_effect=AssertionError('read invoked')),
            patch('quantlab.backtest.run_backtest', side_effect=AssertionError('engine invoked')),
            patch('quantlab.provider.HTTPTransport.__call__', side_effect=AssertionError('provider invoked')),
            patch('quantlab.strategies.generate_signals', side_effect=AssertionError('strategy invoked')),
        ):
            page.comparison_list.item(0).setSelected(True)
            self.assertEqual(len(page._equity_overlay.canvas.series), 1)
            page.saved_results_table.set_saved([('saved', {'name': 'B', '_overlay': points})])
            self.assertIn('B', page._equity_overlay.legend.text())
            page.comparison_list.item(0).setSelected(False)
            self.assertFalse(page._equity_overlay.canvas.series)
            page._equity_overlay.canvas.render(QImage(640, 300, QImage.Format.Format_ARGB32))
        page.start_job.assert_not_called()
        self.assertEqual(page.saved_results_table.columnCount(), len(FIELDS))
        side = SideBySideTable(page.saved_results_table)
        side.set_rows([{}])
        self.assertEqual((side.rowCount(), side.columnCount()), (5, 2))

    def test_new_strings_and_read_only_source(self):
        source = Path('desktop_pages/compare_equity.py').read_text(encoding='utf-8')
        for forbidden in ('QTimer', 'start_job(', 'deleteLater', 'setStyleSheet', 'optimise', 'recommend', 'weight', 'best'):
            self.assertNotIn(forbidden, source)
        catalog = Path('desktop_strings.py').read_text(encoding='utf-8').split('# F2:')[1].split('# F3:')[0]
        for forbidden in ('best', 'recommend', 'weight', '?' * 3):
            self.assertNotIn(forbidden, catalog.lower())


if __name__ == '__main__':
    unittest.main()
