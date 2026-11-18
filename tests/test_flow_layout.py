"""FlowLayout: wrapping, hidden items and the minimum size used by the strategy toolbar."""

import unittest

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from desktop_app.features.trading.flow_layout import FlowLayout


class FlowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.addCleanup(self._delete)
        self.layout = FlowLayout(self.host, spacing=10)
        self.buttons = []
        for index in range(4):
            button = QPushButton('b%d' % index, self.host)
            button.setFixedSize(100, 30)
            self.layout.addWidget(button)
            self.buttons.append(button)

    def _delete(self):
        import shiboken6

        self.app.processEvents()
        if shiboken6.isValid(self.host):
            shiboken6.delete(self.host)
        self.app.processEvents()

    def arrange(self, width):
        self.layout.setGeometry(QRect(0, 0, width, 1000))
        return [button.geometry() for button in self.buttons]

    def test_items_wrap_onto_further_rows_when_the_width_runs_out(self):
        rects = self.arrange(230)  # two fit (100 + 10 + 100), the third does not
        self.assertEqual([(rect.x(), rect.y()) for rect in rects], [(0, 0), (110, 0), (0, 40), (110, 40)])
        self.assertEqual(self.layout.heightForWidth(230), 70)
        self.assertEqual(self.layout.heightForWidth(1000), 30)  # all on one row

    def test_an_item_that_exactly_fills_the_row_stays_on_it(self):
        rects = self.arrange(320)  # 100 + 10 + 100 + 10 + 100 = 320 exactly
        self.assertEqual([rect.y() for rect in rects], [0, 0, 0, 40])

    def test_a_hidden_item_takes_no_room_and_leaves_no_gap(self):
        self.buttons[1].hide()
        rects = self.arrange(1000)
        self.assertEqual((rects[2].x(), rects[2].y()), (110, 0))  # directly after the first, no empty slot
        self.assertEqual(self.layout.heightForWidth(320), 30)  # three visible items fit one row; four needed two

    def test_minimum_size_is_the_widest_visible_item_and_ignores_hidden_ones(self):
        self.buttons[0].setFixedSize(300, 20)
        self.assertEqual(self.layout.minimumSize().width(), 300)
        self.buttons[0].hide()
        self.assertEqual(self.layout.minimumSize().width(), 100)
        self.assertEqual(self.layout.sizeHint(), self.layout.minimumSize())


if __name__ == '__main__':
    unittest.main()
