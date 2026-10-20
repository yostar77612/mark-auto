from PySide6.QtWidgets import QWidget, QTabBar, QTabWidget
from tests.t10_fixture import WindowFixture
from desktop_accessibility import INTERACTIVE, visual_focus_order
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6
import unittest

from desktop_market import MarketDashboard
from desktop_theme import apply_market_theme, build_market_stylesheet


class WorkspaceAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_workspace_controls_themes_font_and_keyboard_disclosure(self):
        page = MarketDashboard()
        try:
            workspace = page.workspace
            controls = [workspace.button, *(panel.handle for panel in workspace.panels.values())]
            for theme in ('dark', 'light'):
                page.setProperty('appearanceTheme', theme)
                apply_market_theme(page)
                self.assertIn('QToolButton:focus', build_market_stylesheet(theme))
                for factor in (1, 2):
                    font = QFont(page.font())
                    font.setPointSizeF(11 * factor)
                    page.setFont(font)
                    for control in controls:
                        control.ensurePolished()
                        self.assertTrue(control.accessibleName())
                        self.assertTrue(control.accessibleDescription())
                        self.assertTrue(control.toolTip())
                        self.assertTrue(control.focusPolicy() & Qt.FocusPolicy.TabFocus)
                        self.assertGreaterEqual(control.sizeHint().width(), control.fontMetrics().horizontalAdvance(control.text()))
            for key in workspace.preset_ids:
                workspace.actions[key].trigger()
                for panel in workspace.panels.values():
                    QTest.keyClick(panel.handle, Qt.Key.Key_C)
                    collapsed = panel.content.isHidden()
                    QTest.keyClick(panel.handle, Qt.Key.Key_C)
                    self.assertNotEqual(collapsed, panel.content.isHidden())
                    self.assertTrue(panel.handle.isVisibleTo(page))
            for size in ((1366, 768), (1280, 720), (1024, 600)):
                page.resize(*size)
                workspace.reset()
                self.assertTrue(all(panel.isVisibleTo(page) for panel in workspace.panels.values()))
                self.assertLessEqual(page.minimumWidth(), 1280)
            self.assertTrue({'save', 'reset', 'overview', 'chart_focus', 'watchlist_focus'} <= set(workspace.actions))
            self.assertIn(workspace.restore_menu.menuAction(), workspace.menu.actions())
            self.assertIn(workspace.delete_menu.menuAction(), workspace.menu.actions())
        finally:
            shiboken6.delete(page)


class AccessibilityWalkTests(WindowFixture):
    def test_all_controls_including_hidden_sections_have_names(self):
        offenders = []
        for widget in self.window.findChildren(QWidget):
            if isinstance(widget, INTERACTIVE) and not widget.accessibleName().strip():
                offenders.append((type(widget).__name__, widget.objectName()))
            if isinstance(widget, QTabBar):
                for index in range(widget.count()):
                    if not widget.accessibleTabName(index).strip():
                        offenders.append(('tab', widget.tabText(index)))
        self.assertEqual(offenders, [])

    def test_focus_chain_follows_visible_rows(self):
        w = self.window
        for index in range(7):
            w.navigation.setCurrentRow(index)
            self.settle()
            page = w.stack.currentWidget()
            tabs = page.findChildren(QTabWidget)
            variants = [(None, 0)] + [(tab, i) for tab in tabs for i in range(tab.count())]
            for tab, position in variants:
                if tab:
                    tab.setCurrentIndex(position)
                self.settle()
                expected = visual_focus_order(page)
                if not expected:
                    continue
                actual = []
                current = expected[0]
                for _ in range(len(w.findChildren(QWidget)) + 1):
                    if current in expected:
                        actual.append(current)
                    current = current.nextInFocusChain()
                    if current is expected[0]:
                        break
                self.assertEqual([x.objectName() for x in actual], [x.objectName() for x in expected], (index, position))
