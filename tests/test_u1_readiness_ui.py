"""Readiness explanations remain keyboard-accessible, read-only and scoped."""

from dataclasses import replace
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from desktop_app.features.trading.broker_panel import BrokerPanel
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment
from tests.test_sinopac_panel_ui import connected_view


class AccountReadinessUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = BrokerPanel(confirm=lambda text: False)
        self.panel.apply(connected_view())
        self.panel.resize(1000, 900)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        shiboken6.delete(self.panel)

    def test_unsigned_account_explains_official_steps_without_links_or_commands(self):
        guide = self.panel.account_guidance['future-1']
        self.assertEqual(guide.summary.text(), ui_text('u1.readiness.unsigned_next'))
        self.assertFalse(guide.details.isVisible())
        signals = [
            QSignalSpy(getattr(self.panel, name)) for name in ('save_connect_requested', 'accounts_requested', 'certificate_requested', 'disconnect_requested')
        ]
        guide.button.setFocus()
        QTest.keyClick(guide.button, Qt.Key.Key_Space)
        self.assertTrue(guide.details.isVisible())
        content = guide.details.text()
        for required in ('證券 API 簽署', '2890', '近月 TXF', '1 分鐘', '中斷連線', '儲存並連線', '模擬下單不需要 CA'):
            self.assertIn(required, content)
        for forbidden in ('https:', 'http:', '<a', 'person_id'):
            self.assertNotIn(forbidden, content)
        self.assertIs(guide.details.textFormat(), Qt.TextFormat.PlainText)
        self.assertFalse(guide.details.openExternalLinks())
        self.assertTrue(guide.button.accessibleName())
        self.assertEqual(guide.button.accessibleDescription(), content)
        QTest.keyClick(guide.button, Qt.Key.Key_Space)
        self.assertFalse(guide.details.isVisible())
        self.assertTrue(all(spy.count() == 0 for spy in signals))

    def test_poll_preserves_disclosure_and_updates_signed_unknown_and_removed_accounts(self):
        guide = self.panel.account_guidance['future-1']
        guide.button.click()
        view = connected_view(2)
        self.panel.apply(replace(view, accounts=tuple(replace(item, signed=None) for item in view.accounts)))
        self.assertIs(self.panel.account_guidance['future-1'], guide)
        self.assertTrue(guide.button.isChecked())
        self.assertEqual(guide.summary.text(), ui_text('u1.readiness.unknown_next'))
        self.panel.apply(replace(connected_view(3), accounts=()))
        self.assertEqual(self.panel.account_guidance, {})
        self.assertEqual(self.panel.account_boxes, {})

    def test_each_readiness_fact_has_next_steps_without_promoting_readiness(self):
        for code, guide in self.panel.readiness_guidance.items():
            guide.button.click()
            self.assertTrue(guide.details.isVisible(), code)
            self.assertTrue(guide.button.accessibleDescription(), code)
        self.assertIn(ui_text('m2.connection.blocked'), self.panel.readiness_labels['simulation_orders'].text())
        self.assertIn('即時', self.panel.readiness_guidance['market'].details.text())
        self.assertIn('恢復', self.panel.readiness_guidance['accounts'].details.text())
        self.assertIn('不需要 CA', self.panel.certificate_guidance.details.text())
        self.panel.unavailable()
        self.assertIn(ui_text('m2.connection.unknown'), self.panel.readiness_labels['market'].text())
        self.assertIn(ui_text('m2.connection.production_disabled'), self.panel.readiness_labels['production_orders'].text())

    def test_live_help_does_not_enable_certificate_or_execution(self):
        settings = SinopacConnectionSettings(Environment.LIVE)
        self.panel.apply(replace(connected_view(2), settings=settings, environment=Environment.LIVE))
        self.panel.certificate_guidance.button.click()
        self.assertTrue(self.panel.certificate_guidance.details.isVisible())
        self.assertIn('停用', self.panel.certificate_guidance.details.text())
        self.assertFalse(self.panel.activate_certificate.isEnabled())
        self.assertFalse(self.panel.choose_certificate.isEnabled())
        self.assertIn(ui_text('m2.connection.production_disabled'), self.panel.readiness_labels['production_orders'].text())
