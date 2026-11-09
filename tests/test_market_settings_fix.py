"""Actual Qt boundaries for the installed market-settings regressions; offline."""

import unittest
from dataclasses import replace
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton

from desktop_app.features.trading.broker_panel import BrokerPanel
from desktop_app.features.trading.alert_panel import AlertRuleDialog
from desktop_app.components.charts import CandlestickChart
from desktop_app.shell.theme import chart_legend
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import SinopacConnectionSettings, SinopacConnectionView
from quantlab.trading.domain.alerts import RULE_KINDS
from quantlab.trading.domain.models import Environment
from quantlab.trading.application.errors import ERROR_TABLE


class MarketSettingsUiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_actual_combo_save_emits_typed_broker_simulation_and_live_settings(self):
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            with self.subTest(environment=environment):
                panel = BrokerPanel(confirm=lambda text: False)
                try:
                    panel.show()
                    panel.environment.setCurrentIndex(panel.environment.findData(environment))
                    self.app.processEvents()
                    emitted = QSignalSpy(panel.save_connect_requested)
                    QTest.mouseClick(panel.save_connect, Qt.MouseButton.LeftButton)
                    self.assertEqual(emitted.count(), 1, panel.status.text())
                    saved = emitted.at(0)[0]
                    self.assertIsInstance(saved, SinopacConnectionSettings)
                    self.assertIs(saved.environment, environment)
                    self.assertEqual(saved.key_ref, 'MarkAuto/v2/broker/sinopac')
                    self.assertEqual(emitted.at(0)[1:], [0, ''])
                finally:
                    shiboken6.delete(panel)

    def test_default_connection_facts_never_infer_market_login_from_local_engine(self):
        from desktop_app.features.trading import TradingWindow
        from tests.test_trading_ui import RecordingFacade

        facade = RecordingFacade()
        window = TradingWindow(facade, replace(facade.snapshot(), engine_state='RUNNING'))
        window.poll.stop()
        window.setProperty('allow_close_for_tests', True)
        try:
            self.assertEqual(window.broker_panel.status.text(), ui_text('m2.connection.disconnected'))
            self.assertIn(ui_text('m2.connection.connect_first'), window.broker_panel.readiness_labels['market'].text())
            self.assertEqual(window.broker_panel.readiness_labels['market'].property('sinopacStatus'), 'BLOCKED')
            self.assertEqual(facade.commands, [])
        finally:
            window.close()
            shiboken6.delete(window)

    def test_enabled_market_settings_keep_their_own_connection_and_failure_states(self):
        panel = BrokerPanel(confirm=lambda text: False)
        try:
            for revision, (connection, error, expected) in enumerate(
                (
                    ('CONNECTING', '', ui_text('m2.connection.pending')),
                    ('CONNECTED', '', ui_text('m2.connection.connected')),
                    ('DISCONNECTED', '', ui_text('m2.connection.disconnected')),
                    ('DISCONNECTED', 'broker_login_failed', ui_text('m2.connection.login_failed')),
                    ('DISCONNECTED', 'market_sdk_missing', ERROR_TABLE['market_sdk_missing'].explanation + ERROR_TABLE['market_sdk_missing'].action),
                    ('DISCONNECTING', '', ui_text('m2.connection.disconnecting')),
                ),
                start=1,
            ):
                with self.subTest(connection=connection, error=error):
                    panel.apply(SinopacConnectionView(revision=revision, phase=connection, error_code=error))
                    self.assertIn(expected, panel.status.text())
        finally:
            shiboken6.delete(panel)

    def test_alert_kind_combo_creates_all_twelve_typed_rules(self):
        for kind in RULE_KINDS:
            with self.subTest(kind=kind):
                dialog = AlertRuleDialog('TWSE:2330')
                try:
                    dialog.kind.setCurrentIndex(dialog.kind.findData(kind))
                    create = next(button for button in dialog.findChildren(QPushButton) if button.text() == ui_text('alert.create'))
                    create.click()
                    self.assertIsNotNone(dialog.rule, dialog.error.text())
                    self.assertIs(dialog.rule.kind, kind)
                finally:
                    shiboken6.delete(dialog)


class MarketEmptyChartRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_message_and_errors_do_not_overlap_the_actual_legend_glyph_bounds(self):
        drawn = {}

        class Painter(QPainter):
            def drawText(self, *args):
                if isinstance(args[0], QPointF):
                    metrics = self.fontMetrics()
                    bounds = QRectF(args[0].x(), args[0].y() - metrics.ascent(), metrics.horizontalAdvance(args[-1]), metrics.height())
                else:
                    bounds = QRectF(self.fontMetrics().boundingRect(*args))
                drawn[str(args[-1])] = bounds
                return super().drawText(*args)

        chart = CandlestickChart()
        chart.setMinimumSize(100, 90)  # The actual M1 terminal's chart minimum.
        try:
            for size in (10, 14, 18):
                chart.setFont(QFont('DejaVu Sans', size))
                for width, height in ((600, 90), (700, 160), (800, 480)):
                    chart.resize(width, height)
                    for error in ('', 'unavailable'):
                        with self.subTest(font=size, height=height, error=error):
                            chart.error = error
                            drawn.clear()
                            with patch('desktop_app.components.charts.QPainter', Painter):
                                chart.grab()
                            message = drawn[error or ui_text('charts.paint_event.no_data')]
                            legend = drawn[chart_legend(chart)]
                            self.assertFalse(message.intersects(legend), (message, legend))
                            self.assertTrue(QRectF(chart.rect()).contains(message), message)
        finally:
            shiboken6.delete(chart)


if __name__ == '__main__':
    unittest.main()
