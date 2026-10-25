"""Actual market refresh controls and native/offscreen operation accounting.

Only an immutable synthetic facade and test-owned Qt windows are used. These
tests never start a trading engine, resolve credentials or contact a broker.
"""

from dataclasses import replace
from decimal import Decimal
import time
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from desktop_strings import ui_text
from test_trading_ui import RecordingFacade
from tools.trading_load_probe import ObservedWindow, Probe


class MarketRefreshControlTests(unittest.TestCase):
    native_observations = []

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.facade = RecordingFacade()
        self.facade.state = replace(
            self.facade.state, markets=tuple(replace(item, price=Decimal('11'), availability='FRESH') for item in self.facade.state.markets)
        )
        self.window = ObservedWindow(self.facade, self.facade.snapshot())
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.navigation.setCurrentRow(2)
        self.window.resize(900, 640)
        self.other = None
        self.window.show()
        self.window.activateWindow()
        QApplication.setActiveWindow(self.window)
        self.app.processEvents()
        self.probe = Probe.__new__(Probe)
        self.probe.window = self.window
        self.probe.pending = self.probe.pending_operation = None
        self.probe.pending_rendered = False
        self.probe.sample_error = ''
        self.probe.refresh_requests = self.probe.refresh_completions = self.probe.refresh_failures = 0
        self.probe.latencies = []
        self.window.refresh_started.connect(self.probe.sample_started)
        self.window.refresh_rendered.connect(self.probe.sample_rendered)
        self.window.refresh_finished.connect(self.probe.sample_finished)

    def tearDown(self):
        self.drain()
        self.window.close()
        self.window.deleteLater()
        if self.other is not None:
            self.other.close()
            self.other.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(self.window))
        if self.other is not None:
            self.assertFalse(isValid(self.other))
        self.app.processEvents()

    def drain(self):
        deadline = time.monotonic() + 3
        while self.window._operation is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertIsNone(self.window._operation)
        self.assertIsNone(self.probe.pending_operation)
        self.app.processEvents()

    def changed_quote(self):
        self.facade.state = replace(
            self.facade.state,
            quote_revision=self.facade.state.quote_revision + 1,
            markets=tuple(replace(item, price=Decimal('12.35')) for item in self.facade.state.markets),
        )

    def mouse_refresh(self):
        self.probe.pending = time.perf_counter()
        QTest.mouseClick(self.window.market_refresh_button, Qt.MouseButton.LeftButton)
        self.drain()

    def assert_success(self, count=1):
        self.assertEqual(self.probe.refresh_requests, count)
        self.assertEqual(self.probe.refresh_completions, count)
        self.assertEqual(self.probe.refresh_failures, 0)
        self.assertEqual(len(self.probe.latencies), count)
        self.assertEqual(self.probe.sample_error, '')
        self.assertEqual(self.window.markets.item(0, 3).text(), '12.35')
        self.assertEqual(self.facade.commands, [], 'refresh cannot submit a business command')

    def test_accessible_market_button_is_visible_and_mouse_refresh_renders_actual_result(self):
        button = self.window.market_refresh_button
        self.assertEqual(button.objectName(), 'market_refresh_button')
        self.assertEqual(button.text(), ui_text('v2.refresh_market'))
        self.assertEqual(button.accessibleName(), ui_text('v2.refresh_market'))
        self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        self.assertTrue(button.isVisible())
        self.assertTrue(button.visibleRegion().contains(button.rect().center()))
        self.changed_quote()
        self.mouse_refresh()
        self.assert_success()

    def test_real_button_mouse_click_works_while_own_main_window_is_inactive(self):
        self.other = QWidget()
        self.other.setWindowTitle('Owned market refresh focus fixture')
        self.other.resize(240, 120)
        self.other.show()
        self.other.activateWindow()
        QApplication.setActiveWindow(self.other)
        self.app.processEvents()
        self.assertFalse(self.window.isActiveWindow())
        self.assertTrue(self.other.isActiveWindow())
        before = self.window.isActiveWindow()
        self.changed_quote()
        self.mouse_refresh()
        self.assert_success()
        self.native_observations.append(
            {
                'case': self._testMethodName,
                'platform': self.app.platformName(),
                'main_active_before_click': before,
                'other_owned_window_active_before_click': True,
                'requests': self.probe.refresh_requests,
                'successful_rendered_completions': self.probe.refresh_completions,
                'query_failures': self.probe.refresh_failures,
            }
        )

    def test_tab_space_button_activation_and_existing_f5_both_reach_real_refresh(self):
        self.window.navigation.setFocus()
        QTest.keyClick(self.window.navigation, Qt.Key.Key_Tab)
        self.assertEqual(self.app.focusWidget().objectName(), 'market_scroll')
        QTest.keyClick(self.app.focusWidget(), Qt.Key.Key_Tab)
        self.assertTrue(self.window.market_refresh_button.hasFocus())
        self.changed_quote()
        self.probe.pending = time.perf_counter()
        QTest.keyClick(self.window.market_refresh_button, Qt.Key.Key_Space)
        self.drain()
        self.assert_success()
        self.probe.pending = time.perf_counter()
        QTest.keyClick(self.window, Qt.Key.Key_F5)
        self.drain()
        self.assert_success(2)

    def test_button_query_error_preserves_prior_view_and_cannot_count_success(self):
        before = self.window.markets.item(0, 3).text()
        self.facade.failure = True
        self.mouse_refresh()
        self.assertEqual(self.probe.refresh_requests, 1)
        self.assertEqual(self.probe.refresh_completions, 0)
        self.assertEqual(self.probe.refresh_failures, 1)
        self.assertEqual(self.probe.latencies, [])
        self.assertEqual(self.probe.sample_error, 'UI refresh query failed')
        self.assertEqual(self.window.markets.item(0, 3).text(), before)
        self.assertEqual(self.window.notice.text(), ui_text('v2.connection_failed'))
        self.assertNotIn('private', self.window.notice.text())
        self.assertEqual(self.facade.commands, [])


if __name__ == '__main__':
    unittest.main()
