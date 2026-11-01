"""Actual Qt boundaries for the installed market-settings regressions; offline."""

import unittest
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton

from desktop_app.features.trading.market_data_panel import MarketDataPanel
from desktop_app.features.trading.alert_panel import AlertRuleDialog
from desktop_app.components.charts import CandlestickChart
from desktop_app.shell.theme import chart_legend
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.alerts import AlertKind
from quantlab.trading.domain.models import Environment


class MarketSettingsUiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_actual_combo_save_emits_typed_broker_simulation_and_live_settings(self):
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            with self.subTest(environment=environment):
                panel = MarketDataPanel()
                try:
                    panel.show()
                    panel.environment.setCurrentIndex(panel.environment.findData(environment))
                    self.app.processEvents()
                    emitted = QSignalSpy(panel.save_requested)
                    QTest.mouseClick(panel.findChild(QPushButton, 'market_data_save'), Qt.MouseButton.LeftButton)
                    self.assertEqual(emitted.count(), 1, panel.status.text())
                    saved = emitted.at(0)[0]
                    self.assertIsInstance(saved, MarketDataSettings)
                    self.assertIs(saved.environment, environment)
                    self.assertEqual(saved.secret_ref, 'MarkAuto/v2/broker/sinopac')
                    self.assertTrue(saved.enabled)
                finally:
                    shiboken6.delete(panel)

    def test_disabled_market_settings_always_show_disconnected(self):
        panel = MarketDataPanel()
        try:
            for connection in ('CONNECTED', 'CONNECTING', 'DISCONNECTED', 'FAILED', 'UNKNOWN', ''):
                for error in ('', 'market_data_login_failed'):
                    with self.subTest(connection=connection, error=error):
                        panel.apply(MarketDataSettings(enabled=False), connection, error)
                        self.assertEqual(panel.status.text(), ui_text('watch.disconnected'))
        finally:
            shiboken6.delete(panel)

    def test_enabled_market_settings_keep_their_own_connection_and_failure_states(self):
        panel = MarketDataPanel()
        try:
            for connection, error, expected in (
                ('CONNECTING', '', ui_text('watch.connecting')),
                ('CONNECTED', '', ui_text('watch.connected')),
                ('DISCONNECTED', '', ui_text('watch.disconnected')),
                ('DISCONNECTED', 'market_data_login_failed', ui_text('marketdata.connection_failed')),
                ('UNKNOWN', '', ui_text('watch.unknown')),
            ):
                with self.subTest(connection=connection, error=error):
                    panel.apply(MarketDataSettings(enabled=True), connection, error)
                    self.assertEqual(panel.status.text(), expected)
        finally:
            shiboken6.delete(panel)

    def test_alert_kind_combo_creates_all_twelve_typed_rules(self):
        for kind in AlertKind:
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
