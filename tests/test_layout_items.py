"""Layout reads that never create QLayoutItem wrappers (see desktop_app/components/layout_items.py)."""

import gc
import unittest

import shiboken6
from PySide6.QtWidgets import QApplication, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLayout, QLayoutItem, QPushButton, QVBoxLayout, QWidget

from desktop_app.components.layout_items import child_layouts, layout_entries, layout_entry
from desktop_app.shell.accessibility import semantic_name
from desktop_app.shell.polish import _insert_after


def pinned_items(*layouts):
    """Item wrappers kept alive by these layouts' wrappers (what QLayout.itemAt() leaves behind)."""
    gc.collect()
    items = [item for item in gc.get_objects() if isinstance(item, QLayoutItem) and not isinstance(item, QLayout)]
    return [item for item in items if any(holder is layout for holder in gc.get_referrers(item) for layout in layouts)]


class LayoutItemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.addCleanup(shiboken6.delete, self.host)

    def test_entries_follow_layout_order_skip_spacers_and_include_child_layouts(self):
        outer = QVBoxLayout(self.host)
        first, second = QLabel('first'), QPushButton('second')
        row = QHBoxLayout()
        outer.addWidget(second)
        outer.insertWidget(0, first)
        outer.addStretch()
        outer.addLayout(row)
        inner = QPushButton('inner')
        row.addWidget(inner)
        self.assertEqual(layout_entries(outer, self.host), [first, second, row])
        self.assertEqual(layout_entries(row, self.host), [inner])
        self.assertIs(layout_entry(outer, 0, self.host), first)
        self.assertIs(layout_entry(outer, 3, self.host), row)
        self.assertIsNone(layout_entry(outer, 2, self.host))  # the stretch
        self.assertIsNone(layout_entry(outer, 4, self.host))
        self.assertIsNone(layout_entry(outer, -1, self.host))
        self.assertEqual(child_layouts(outer), [row])
        self.assertEqual(pinned_items(outer, row), [])

    def test_grid_and_form_layouts(self):
        grid = QGridLayout(self.host)
        widgets = [QLabel(str(index)) for index in range(3)]
        grid.addWidget(widgets[2], 1, 0)
        grid.addWidget(widgets[0], 0, 0)
        grid.addWidget(widgets[1], 0, 1)
        self.assertEqual(layout_entries(grid, self.host), [widgets[2], widgets[0], widgets[1]])  # insertion order, as itemAt
        other = QWidget()
        self.addCleanup(shiboken6.delete, other)
        form = QFormLayout(other)
        label, field = QLabel('name'), QPushButton()
        form.addRow(label, field)
        self.assertEqual(layout_entries(form, other), [label, field])

    def test_semantic_name_and_insert_after_leave_no_wrapper_behind_when_a_widget_moves(self):
        outer = QVBoxLayout(self.host)
        caption, field = QLabel('Caption'), QPushButton()
        outer.addWidget(caption)
        outer.addWidget(field)
        row = QHBoxLayout()
        outer.addLayout(row)
        nested = QPushButton()
        row.addWidget(nested)
        self.assertEqual(semantic_name(field), 'Caption')
        hint = QLabel('hint')
        self.assertTrue(_insert_after(outer, nested, hint))
        self.assertEqual(layout_entries(row, self.host), [nested, hint])
        self.assertEqual(pinned_items(outer, row), [])
        for widget in (field, nested):
            widget.setParent(None)  # Qt deletes the widget's layout item on its own
            self.addCleanup(shiboken6.delete, widget)
        self.assertEqual(pinned_items(outer, row), [])
        self.assertEqual(layout_entries(outer, self.host), [caption, row])
        self.assertEqual(layout_entries(row, self.host), [hint])


if __name__ == '__main__':
    unittest.main()
