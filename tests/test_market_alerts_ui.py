"""Offline controller scheduling, notification baseline and GUI responsiveness."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from threading import Event
import time
import unittest

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from desktop_app.features.trading.alert_panel import AlertPanel
from desktop_app.features.trading.market_alerts_ui import AlertPanelController
from desktop_app.features.trading.market_watch import _Result, start_request
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.alert_contracts import AlertOperation, AlertRuleData, AlertSnapshot
from quantlab.trading.domain.alerts import AlertEvent, AlertKind, AlertRule
from quantlab.trading.domain.validation import DomainError
from tests.test_alert_rules import ID, NOW


def event(event_id='old'):
    return AlertEvent(event_id, 'rule', AlertKind.PRICE_CROSS, ID, NOW, Decimal('100'), 'alert.event.price_cross', ('100', 'UP'))


class DeferredSubmit:
    def __init__(self):
        self.pending = []
        self.maximum = 0

    def __call__(self, operation, completed):
        self.pending.append((operation, completed))
        self.maximum = max(self.maximum, len(self.pending))

    def finish(self):
        operation, completed = self.pending.pop(0)
        try:
            result = operation()
        except DomainError as error:
            completed(None, error)
        else:
            completed(result, None)


class Backend:
    def __init__(self):
        self.snapshot = AlertSnapshot()
        self.calls = []
        self.error = None

    def __call__(self, command):
        self.calls.append(command.operation)
        if self.error is not None:
            raise self.error
        if command.operation is AlertOperation.ADD:
            self.snapshot = replace(self.snapshot, rules=(*self.snapshot.rules, command.rule))
        elif command.operation is AlertOperation.ENABLE:
            self.snapshot = replace(
                self.snapshot, rules=tuple(replace(rule, enabled=command.enabled) if rule.rule_id == command.rule_id else rule for rule in self.snapshot.rules)
            )
        elif command.operation is AlertOperation.DELETE:
            self.snapshot = replace(self.snapshot, rules=tuple(rule for rule in self.snapshot.rules if rule.rule_id != command.rule_id))
        elif command.operation is AlertOperation.CLEAR:
            self.snapshot = replace(self.snapshot, events=())
        return self.snapshot


class AlertControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend, self.submit = Backend(), DeferredSubmit()
        self.notifications, self.latest = [], []
        self.controller = AlertPanelController(
            self.backend, self.submit, lambda: ID, lambda *args: None, lambda key: key, self.notifications.append, lambda: ('#ff0000', '#00ff00')
        )
        self.controller.panel.latest_changed.connect(self.latest.append)

    def tearDown(self):
        self.controller.stop()
        shiboken6.delete(self.controller.panel)
        shiboken6.delete(self.controller)
        self.app.processEvents()

    def test_constructor_is_inert_and_poll_mutations_are_serialized(self):
        self.assertEqual([], self.backend.calls)
        self.assertEqual([], self.submit.pending)
        self.controller.start()
        self.controller.start()
        self.assertEqual(1, len(self.submit.pending))
        self.assertEqual([], self.backend.calls)
        self.assertEqual(1000, self.controller.timer.interval())
        for _ in range(10):
            self.controller.refresh()
        rule = AlertRule('rule', AlertKind.PRICE_CROSS, instrument_id=ID)
        self.controller.actions.add_rule(rule)
        self.controller.actions.set_enabled('rule', False)
        self.controller.actions.delete_rule('rule')
        self.controller.panel.clear_events()
        self.assertEqual(1, len(self.submit.pending))
        while self.submit.pending:
            self.submit.finish()
        self.assertEqual(
            [AlertOperation.SNAPSHOT, AlertOperation.ADD, AlertOperation.ENABLE, AlertOperation.DELETE, AlertOperation.CLEAR, AlertOperation.SNAPSHOT],
            self.backend.calls,
        )
        self.assertEqual(1, self.submit.maximum)
        self.assertEqual((), self.controller.actions.rules)

    def test_historical_events_restore_status_without_notification_then_new_event_notifies_once(self):
        self.backend.snapshot = AlertSnapshot(events=(event(),))
        self.controller.start()
        self.submit.finish()
        self.assertEqual(1, self.controller.panel.table.rowCount())
        self.assertEqual(1, len(self.latest))
        self.assertEqual([], self.notifications)
        self.backend.snapshot = replace(self.backend.snapshot, events=(event(), replace(event('new'), occurred_at=NOW + timedelta(minutes=1))))
        self.controller.refresh()
        self.submit.finish()
        self.assertEqual(2, self.controller.panel.table.rowCount())
        self.assertEqual(1, len(self.notifications))
        self.controller.refresh()
        self.submit.finish()
        self.assertEqual(1, len(self.notifications))

    def test_mutation_failure_is_visible_and_keeps_last_published_cache(self):
        rule = AlertRule('rule', AlertKind.PRICE_CROSS, instrument_id=ID)
        self.backend.snapshot = AlertSnapshot(rules=(AlertRuleData.from_rule(rule),), events=(event(),))
        self.controller.start()
        self.submit.finish()
        self.backend.error = DomainError('operation_failed', 'vendor-sensitive-detail')
        self.controller.panel.clear_events()
        self.assertEqual(1, self.controller.panel.table.rowCount())
        self.submit.finish()
        self.assertEqual(ui_text('alert.unavailable'), self.controller.panel.warning.text())
        self.assertEqual(1, self.controller.panel.table.rowCount())
        self.assertEqual((rule,), self.controller.actions.rules)
        self.backend.error = None
        self.controller.refresh()
        self.submit.finish()
        self.assertTrue(self.controller.panel.warning.isHidden())
        self.assertEqual([], self.notifications)

    def test_initial_failure_does_not_turn_restored_events_into_notifications(self):
        self.backend.error = DomainError('operation_failed')
        self.controller.start()
        self.submit.finish()
        self.backend.error = None
        self.backend.snapshot = AlertSnapshot(events=(event(),))
        self.controller.refresh()
        self.submit.finish()
        self.assertEqual([], self.notifications)
        self.assertEqual(1, self.controller.panel.table.rowCount())

    def test_stop_discards_inflight_results_and_pending_mutations(self):
        self.controller.start()
        self.controller.actions.add_rule(AlertRule('rule', AlertKind.PRICE_CROSS, instrument_id=ID))
        self.controller.stop()
        self.backend.snapshot = AlertSnapshot(events=(event(),))
        self.submit.finish()
        self.assertEqual((), self.controller.actions.events)
        self.assertEqual([], self.submit.pending)
        self.assertFalse(self.controller.timer.isActive())

    def test_synchronous_local_clear_failure_uses_panel_warning(self):
        service = self.controller.actions

        def failure():
            raise DomainError('operation_failed')

        service.clear_events = failure
        panel = AlertPanel(service, lambda: ID, lambda *args: None)
        try:
            panel.clear_events()
            self.assertEqual(ui_text('alert.unavailable'), panel.warning.text())
        finally:
            shiboken6.delete(panel)

    def test_existing_worker_boundary_keeps_gui_responsive_during_remote_wait(self):
        entered, release = Event(), Event()
        results, markers = set(), []

        def call(command):
            entered.set()
            if not release.wait(3):
                raise DomainError('operation_failed')
            return AlertSnapshot()

        def submit(operation, completed):
            def finish(value, error):
                results.discard(result)
                completed(value, error)

            result = _Result(finish)
            results.add(result)
            start_request(operation, result)

        controller = AlertPanelController(call, submit, lambda: ID, lambda *args: None, lambda key: key, None, lambda: ('#ff0000', '#00ff00'))
        try:
            controller.start()
            self.assertTrue(entered.wait(1))
            QTimer.singleShot(0, lambda: markers.append('responsive'))
            self.app.processEvents()
            self.assertEqual(['responsive'], markers)
            self.assertTrue(controller._busy)
            release.set()
            deadline = time.monotonic() + 3
            while results and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(5)
            self.assertFalse(results)
        finally:
            release.set()
            controller.stop()
            QThreadPool.globalInstance().waitForDone(3000)
            self.app.processEvents()
            shiboken6.delete(controller.panel)
            shiboken6.delete(controller)


if __name__ == '__main__':
    unittest.main()
