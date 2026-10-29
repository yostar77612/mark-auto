"""Logical layout checks: no PNG rasterisation, one window across font variants."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QPushButton, QWidget, QScrollArea
from tests.t10_fixture import WindowFixture
from unittest.mock import patch
import tempfile
from pathlib import Path


def layout_defects(page):
    truncated, overlaps = [], []
    for widget in page.findChildren(QWidget):
        if not widget.isVisibleTo(page):
            continue
        if isinstance(widget, (QLabel, QPushButton)) and widget.text():
            if isinstance(widget, QLabel) and widget.wordWrap():
                continue
            if widget.sizeHint().width() > widget.width():
                truncated.append((widget.objectName(), widget.text(), widget.width(), widget.sizeHint().width()))

    def inspect(layout):
        widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() and item.widget().isVisibleTo(page):
                widgets.append(item.widget())
            if item.layout():
                widgets.extend(inspect(item.layout()))
        for i, first in enumerate(widgets):
            for second in widgets[i + 1 :]:
                if first.parentWidget() is second.parentWidget() and first.geometry().intersects(second.geometry()):
                    overlaps.append((first.objectName(), second.objectName()))
        return widgets

    for widget in [page] + page.findChildren(QWidget):
        if widget.isVisibleTo(page) and widget.layout():
            inspect(widget.layout())
    return truncated, sorted(set(overlaps))


class ScaledLayoutTests(WindowFixture):
    def test_metrics_only_scale_options_reuse_window(self):
        from tools.ui_snapshot import capture

        with tempfile.TemporaryDirectory(prefix='t10-scale-metrics-') as folder:
            for scale in (1.5, 2):
                with patch('tools.ui_snapshot._save_png', side_effect=AssertionError('Unexpected rasterisation')):
                    metrics = capture(Path(folder) / str(scale), size=(1280, 720), scale=scale, images=False, window=self.window)
                self.assertEqual(metrics['scale'], scale)
                self.assertEqual(metrics['size'], [1280, 720])
                self.assertEqual(len(metrics['pages']), 7)
                for page in metrics['pages'].values():
                    self.assertEqual(page['unlabeled_inputs'], [])

    def test_minimum_and_market_panel_reflow(self):
        w = self.window
        self.assertEqual((w.minimumWidth(), w.minimumHeight()), (1280, 720))
        w.resize(1280, 720)
        w.navigation.setCurrentRow(5)
        self.settle()
        market = w.market
        before = market.main_splitter.widget(1).width()
        market.panel_toggle.setChecked(False)
        self.settle()
        self.assertTrue(market.right_panel.isHidden())
        self.assertGreater(market.main_splitter.widget(1).width(), before)
        market.panel_toggle.setChecked(True)
        self.settle()
        self.assertFalse(market.right_panel.isHidden())

    def test_fonts_and_minimum_size_have_no_layout_defects(self):
        from desktop_app.shell.theme import scale_window_fonts

        w = self.window
        original = QFont(w.font())
        try:
            for factor in (1, 1.5, 2):
                font = QFont(original)
                font.setPointSizeF(original.pointSizeF() * factor)
                w.setFont(font)
                scale_window_fonts(w, factor)
                w.resize(1280, 720)
                for index in range(7):
                    w.navigation.setCurrentRow(index)
                    self.settle()
                    with self.subTest(font=factor, page=index):
                        self.assertEqual((w.width(), w.height()), (1280, 720))
                        self.assertEqual(layout_defects(w.stack.currentWidget()), ([], []))
        finally:
            w.setFont(original)
            scale_window_fonts(w, 1)
            self.settle()

    def test_small_window_scrolls_with_content_confined_to_viewport(self):
        w = self.window
        try:
            w.setMinimumSize(0, 0)
            w.resize(1024, 600)
            for index in range(7):
                w.navigation.setCurrentRow(index)
                self.settle()
                self.assertEqual((w.width(), w.height()), (1024, 600))
                page = w.stack.currentWidget()
                scroll = page if isinstance(page, QScrollArea) else page.page_scroll
                self.assertTrue(scroll.viewport().rect().isValid())
                if scroll.widget() is w.strategy_page:
                    self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
                    inner = w.strategy_page.tabs.currentWidget()
                    self.assertIs(inner.widget().parentWidget(), inner.viewport())
                    self.assertGreaterEqual(inner.verticalScrollBar().maximum(), 0)
                elif scroll.verticalScrollBar().maximum() == 0:
                    self.assertLessEqual(scroll.widget().height(), scroll.viewport().height())
                else:
                    self.assertGreater(scroll.verticalScrollBar().maximum(), 0, index)
                self.assertIs(scroll.widget().parentWidget(), scroll.viewport())
                self.assertTrue(scroll.viewport().isVisible())
        finally:
            w.setMinimumSize(1280, 720)
            w.resize(1280, 720)
            self.settle()
