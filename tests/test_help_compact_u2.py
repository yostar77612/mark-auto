"""U2: cheap offscreen checks of the existing explanation controls."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import json
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy, QToolButton

from desktop_app.strings.catalog import ui_text
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
from tests.test_t9_onboarding import sandbox_ui


class CompactHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from desktop_app.shell.window import MainWindow

        cls.app = QApplication.instance() or QApplication([])
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)
        cls.folder = tempfile.TemporaryDirectory(prefix='u2-help-')
        cls.addClassCleanup(cls.folder.cleanup)
        paths = AppPaths(Path(cls.folder.name) / 'workspace').ensure()
        cls.jobs = JobManager(paths)
        cls.addClassCleanup(cls.jobs.close)
        cls.window = MainWindow(paths, cls.jobs, SettingsStore(paths.state / 'settings.json'), services=_c_create_ui_services(_c_create_operation_ports()))
        cls.addClassCleanup(cls.window.close)
        for timer in cls.window.findChildren(QTimer):
            timer.stop()

    def test_all_pages_keep_help_names_and_nonexpanding_policies(self):
        names = set()
        for index in range(self.window.stack.count()):
            page = self.window.stack.widget(index)
            for button in page.findChildren(QToolButton):
                if button.objectName().startswith('help_'):
                    names.add(button.objectName())
                    self.assertNotIn(button.sizePolicy().horizontalPolicy(), (QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored))
                    self.assertTrue(button.accessibleName().strip())
                    self.assertTrue(button.toolTip().strip())
        fixture = json.loads((Path(__file__).parent / 'fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertTrue(names)
        self.assertEqual(names, {name for name in fixture if name.startswith('help_')})

    def test_strategy_compact_explanation_layout_focus_and_privacy(self):
        page = self.window.strategy_page
        buttons = [b for b in page.findChildren(QToolButton) if b.objectName().startswith('help_')]
        self.assertTrue(buttons)
        for private in (False, True):
            self.window.privacy.set_enabled(private)
            for button in buttons:
                with self.subTest(private=private, name=button.objectName()):
                    self.assertEqual(button.text(), ui_text('help.symbol'))
                    self.assertEqual(button.accessibleName(), ui_text('help.accessible'))
                    self.assertTrue(button.toolTip().strip())
                    self.assertEqual(button.toolTip(), ui_text('ui.strategy_page.bounded_families_hint'))
                    button.ensurePolished()
                    self.assertLessEqual(button.sizeHint().width(), 40)
                    layout = button.parentWidget().layout()
                    index = layout.indexOf(button)
                    self.assertEqual(layout.stretch(index), 0)
                    self.assertTrue(layout.itemAt(index).alignment() & Qt.AlignmentFlag.AlignLeft)
                    layout.setGeometry(QRect(0, 0, 1000, 1800))
                    self.assertLessEqual(button.width(), 40)
                    self.assertTrue(button.focusPolicy() & Qt.FocusPolicy.TabFocus)
                    current = page
                    chain = set()
                    while current not in chain:
                        chain.add(current)
                        current = current.nextInFocusChain()
                    self.assertIn(button, chain)
            for widget in page.findChildren(QToolButton) + page.findChildren(QLabel):
                if widget.text() == '?':
                    self.assertTrue(widget.accessibleName().strip())
                    self.assertTrue(widget.toolTip().strip())
        self.window.privacy.set_enabled(False)
