"""Settings explanations stay available without expanding the default action row."""

import unittest

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

from desktop_app.components.help import _HELP_OBJECT_NAMES
from desktop_app.strings.catalog import ui_text
from tests import test_settings_sections as support


class SettingsHelpMenuTests(unittest.TestCase):
    setUpClass = classmethod(support.SettingsSectionsTests.setUpClass.__func__)
    setUp = support.SettingsSectionsTests.setUp

    def test_default_budget_keeps_all_original_help_topics_and_disclosures(self):
        page = self.page
        anchor = page.findChild(QToolButton, 'settings_help_topics')
        self.assertTrue(anchor.isVisibleTo(page))
        self.assertEqual(anchor.popupMode(), QToolButton.ToolButtonPopupMode.InstantPopup)
        self.assertFalse(anchor.menu().isVisible())
        buttons = page.findChildren(QPushButton) + page.findChildren(QToolButton)
        self.assertLessEqual(sum(button.isVisibleTo(page) for button in buttons), 8)
        keys = (
            'ui.settings_page.workspace_path',
            'ui.settings_page.state_path',
            'ui.settings_page.irreversible_records_hint',
            'ui.settings_page.log_path',
            'ui.settings_page.manual_update_hint',
            'chatgpt_ui.init.included_usage_hint',
            'automatic_backup.init.schedule_hint',
        )
        topics = [action.defaultWidget().findChild(QToolButton) for action in anchor.menu().actions()]
        self.assertEqual(len(topics), 7)
        self.assertEqual({button.objectName() for button in topics}, {_HELP_OBJECT_NAMES.get('help_' + key, 'help_' + key) for key in keys})
        for key in keys:
            button = next(widget for found, widget in self.window.help_relocations if found == key)
            self.assertIn(button, topics)
            self.assertTrue(button.toolTip().startswith(ui_text(key).split('{')[0]))
            self.assertEqual(button.accessibleName(), ui_text('help.accessible'))
            self.assertEqual(button.accessibleDescription(), button.toolTip())
            self.assertFalse(button.isVisibleTo(page))
        for toggle in (page.paths_toggle, page.backup_toggle, page.connection_toggle, page.maintenance_toggle, page.logs_toggle):
            self.assertTrue(toggle.isVisibleTo(page))
            self.assertTrue(toggle.isCheckable())

    def test_keyboard_opens_accessible_topics_and_closes_with_escape(self):
        anchor = self.page.findChild(QToolButton, 'settings_help_topics')
        menu = anchor.menu()
        observations = []

        def inspect_popup():
            observations.append(menu.isVisible())
            for action in menu.actions():
                row = action.defaultWidget()
                button = row.findChild(QToolButton)
                label = row.findChild(QLabel)
                observations.append(button.isVisible())
                observations.append(button.text() == ui_text('help.symbol'))
                observations.append(label.text() == button.toolTip() == action.text())
                accessible = QAccessible.queryAccessibleInterface(button)
                observations.append(accessible.text(QAccessible.Text.Description) == button.toolTip())
                QTest.keyClick(menu, Qt.Key.Key_Down)
                observations.append(QApplication.focusWidget() is button)
            QTest.keyClick(menu, Qt.Key.Key_Escape)

        self.window.activateWindow()
        self.app.processEvents()
        anchor.setFocus()
        QTimer.singleShot(0, inspect_popup)
        QTest.keyClick(anchor, Qt.Key.Key_Space)
        QTest.qWait(10)
        self.assertTrue(observations)
        self.assertTrue(all(observations), observations)
        self.assertFalse(menu.isVisible())

    def test_popup_allocates_visible_wrapped_text_geometry(self):
        anchor = self.page.findChild(QToolButton, 'settings_help_topics')
        menu = anchor.menu()
        self.addCleanup(menu.close)
        menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height())))
        self.app.processEvents()
        self.assertGreater(menu.width(), 480)
        multiline = []
        for action in menu.actions():
            row = action.defaultWidget()
            label = row.findChild(QLabel)
            button = row.findChild(QToolButton)
            self.assertTrue(label.isVisible())
            self.assertEqual(label.text(), button.toolTip())
            self.assertTrue(label.wordWrap())
            self.assertGreaterEqual(label.width(), 400)
            wrapped = label.fontMetrics().boundingRect(0, 0, label.width(), 10000, Qt.TextFlag.TextWordWrap, label.text())
            self.assertGreaterEqual(label.height(), wrapped.height())
            self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
            self.assertTrue(row.rect().contains(label.geometry()))
            self.assertTrue(menu.rect().contains(row.geometry()))
            multiline.append(label.height() > label.fontMetrics().lineSpacing())
        self.assertTrue(any(multiline))
