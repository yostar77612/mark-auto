from PySide6.QtWidgets import QWidget, QTabBar, QTabWidget
from tests.t10_fixture import WindowFixture
from desktop_accessibility import INTERACTIVE, visual_focus_order


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
            w.navigation.setCurrentRow(index); self.settle()
            page = w.stack.currentWidget()
            tabs = page.findChildren(QTabWidget)
            variants = [(None, 0)] + [(tab, i) for tab in tabs for i in range(tab.count())]
            for tab, position in variants:
                if tab: tab.setCurrentIndex(position)
                self.settle()
                expected = visual_focus_order(page)
                if not expected: continue
                actual = []; current = expected[0]
                for _ in range(len(w.findChildren(QWidget)) + 1):
                    if current in expected: actual.append(current)
                    current = current.nextInFocusChain()
                    if current is expected[0]: break
                self.assertEqual([x.objectName() for x in actual], [x.objectName() for x in expected],
                                 (index, position))
