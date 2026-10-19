from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.t10_fixture import WindowFixture


class ShortcutTests(WindowFixture):
    def test_sidebar_keys_and_help(self):
        w = self.window
        w.activateWindow()
        self.settle()
        for index in range(7):
            QTest.keyClick(w, Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
            self.settle()
            self.assertEqual(w.stack.currentIndex(), index)
            self.assertIn('Ctrl+' + str(index + 1), w.navigation.item(index).toolTip())
        self.assertIn('F5', w.market.refresh_button.toolTip())
        self.assertIn('Esc', w.cancel_button.toolTip())

    def test_refresh_dispatch_and_idle_cancel(self):
        w = self.window
        for index in range(7):
            w.navigation.setCurrentRow(index)
            with patch.object(w, 'refresh_views') as views, patch.object(w, 'refresh_market') as market, patch.object(w, 'read_logs') as logs:
                w.refresh_shortcut.activated.emit()
                self.assertEqual((views.call_count, market.call_count, logs.call_count), (int(index < 5), int(index == 5), int(index == 6)))
        with patch.object(w, 'cancel_job') as cancel:
            w.cancel_shortcut.activated.emit()
            cancel.assert_not_called()
            with patch.object(type(w.jobs), 'active', new_callable=lambda: property(lambda _: True)):
                w.cancel_shortcut.activated.emit()
            cancel.assert_called_once_with()
