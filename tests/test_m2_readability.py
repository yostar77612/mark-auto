"""Owner-added M2-6 dates, first-start presentation and accessible explanations."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget

from desktop_app.features.trading.wizard import StrategyWizard
from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from tests import test_m2_trading_page as support


class M2ReadabilityTests(unittest.TestCase):
    setUpClass = classmethod(support.M2TradingPageTests.setUpClass.__func__)
    setUp = support.M2TradingPageTests.setUp
    tearDown = support.M2TradingPageTests.tearDown
    drain = support.M2TradingPageTests.drain

    def show_state(self, state):
        self.window._rendered_version = None
        self.window.state = self.facade.state = state
        self.window.apply_state(state)
        self.window.navigation.setCurrentRow(0)
        self.app.processEvents()

    def test_taipei_today_rolls_over_separately_from_local_simulation_date(self):
        with patch('desktop_app.features.trading.context_header.datetime', wraps=datetime, create=True) as clock:
            clock.now.return_value = datetime(2026, 11, 1, 15, 59, tzinfo=timezone.utc)
            self.window.apply_state(self.window.state)
            self.assertIn('今天 11/01', self.window.compact_context.text())
            self.assertIn('模擬交易日 10/23', self.window.compact_context.text())
            clock.now.return_value = datetime(2026, 11, 1, 16, 1, tzinfo=timezone.utc)
            self.window.apply_state(replace(self.window.state, market_revision=1))
            self.assertIn('今天 11/02', self.window.compact_context.text())
            self.assertIn('模擬交易日 10/23', self.window.compact_context.text())

    def test_broker_environments_show_today_without_the_simulation_date(self):
        with patch('desktop_app.features.trading.context_header.datetime', wraps=datetime, create=True) as clock:
            clock.now.return_value = datetime(2026, 11, 1, 16, 1, tzinfo=timezone.utc)
            for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
                self.show_state(replace(self.window.state, environment=environment))
                self.assertIn('今天 11/02', self.window.compact_context.text())
                self.assertNotIn('10/23', self.window.compact_context.text())
                self.assertNotIn('模擬交易日', self.window.compact_context.text())
                self.assertNotIn('10/23', self.window.compact_context.toolTip())
                self.assertNotIn('10-23', self.window.compact_context.toolTip())

    def test_actual_first_local_runtime_is_neutral_but_actual_restart_warns(self):
        with tempfile.TemporaryDirectory(prefix='m2-first-overview-') as folder:
            launch = RuntimeLaunch(Path(folder))
            bundle = build_runtime(launch)
            try:
                initial = bundle.snapshot()
                self.assertEqual(initial.events, ('startup_reconciliation_required',))
                self.show_state(initial)
                dashboard = self.window.dashboard
                self.assertEqual(dashboard.lights['engine'].text(), ui_text('m2t.starting'))
                self.assertEqual(dashboard.lights['engine'].property('level'), 'muted')
                self.assertEqual(dashboard.lights['reconciliation'].property('level'), 'muted')
                self.assertFalse(dashboard.red_summary.isVisible())
                self.assertEqual(dashboard.issue_details.property('overviewLevel'), 'muted')
                self.assertEqual(dashboard.issue_details.palette().color(QPalette.ColorRole.Text).name(), '#526071')
                self.assertFalse(bundle.snapshot().reconciliation_verified)
                self.assertTrue(bundle.engine.state.stopped)
            finally:
                bundle.close()
            restarted = build_runtime(launch)
            try:
                self.show_state(restarted.snapshot())
                self.assertTrue(self.window.dashboard.red_summary.isVisible())
                self.assertEqual(self.window.dashboard.issue_details.property('overviewLevel'), 'red')
            finally:
                restarted.close()

    def test_populated_stopped_and_real_issues_are_never_neutralized(self):
        original = self.window.state
        initial = replace(
            original,
            engine_state='WAITING_RECONCILIATION',
            strategies=(),
            positions=(),
            orders=(),
            issues=(),
            reconciliation=(),
            reconciliation_verified=False,
            version=1,
            events=('startup_reconciliation_required',),
        )
        for changes in (
            {'positions': original.positions},
            {'orders': original.orders},
            {'strategies': original.strategies},
            {'engine_state': 'STOPPED'},
            {'issues': ('Synthetic reconciliation failure',)},
        ):
            with self.subTest(changes=changes):
                self.show_state(replace(initial, **changes))
                dashboard = self.window.dashboard
                self.assertTrue(dashboard.red_summary.isVisible())
                self.assertEqual(dashboard.issue_details.property('overviewLevel'), 'red')
                self.assertEqual(dashboard.issue_details.palette().color(QPalette.ColorRole.Text).name(), '#651414')

    def test_empty_strategy_action_navigates_and_opens_existing_wizard(self):
        self.show_state(replace(self.window.state, strategies=(), version=2))
        self.window.navigation.setCurrentRow(0)
        action = self.window.findChild(QPushButton, 'dashboard_new_strategy')
        self.assertIsNotNone(action)
        self.assertTrue(action.isVisibleTo(self.window.pages.currentWidget()))
        self.assertTrue(self.window.dashboard.strategy_summary.isVisible())
        self.assertEqual(self.window.dashboard.strategy_summary.text(), ui_text('m2t.empty_strategy_reason'))
        with patch.object(StrategyWizard, 'exec', return_value=StrategyWizard.DialogCode.Rejected) as opened:
            action.click()
        opened.assert_called_once()
        self.assertEqual(self.window.navigation.currentRow(), 1)
        self.assertEqual(self.facade.commands, [])

    def test_four_pages_keep_complete_explanations_and_keyboard_close(self):
        for index, name, full in (
            (0, 'overview_start', ui_text('v2.start_hint')),
            (3, 'trading_control', ui_text('v2.control_hint')),
            (4, 'performance_explanation', ui_text('v2.performance_hint') + '\n\n' + ui_text('v2.performance_valuation_hint')),
            (5, 'settings_context', ui_text('m2.connection.context_help') + '\n\n' + ui_text('v2.external_hint')),
        ):
            with self.subTest(page=index):
                self.window.navigation.setCurrentRow(index)
                row = self.window.findChild(QWidget, name + '_help_row')
                self.assertIsNotNone(row)
                self.window.pages.currentWidget().ensureWidgetVisible(row)
                row.button.setFocus()
                QTest.keyClick(row.button, Qt.Key.Key_Space)
                self.app.processEvents()
                self.assertTrue(row.dialog.isVisible())
                self.assertEqual(row.details.text(), full)
                self.assertGreaterEqual(row.details.height(), row.details.heightForWidth(row.details.width()))
                self.assertEqual(row.button.toolTip(), full)
                self.assertTrue(row.button.accessibleName())
                self.assertTrue(row.summary.text())
                self.assertLess(len(row.summary.text()), len(full))
                QTest.keyClick(row.dialog, Qt.Key.Key_Escape)
                self.assertFalse(row.dialog.isVisible())

    def test_performance_headers_are_plain_and_retain_full_definitions(self):
        self.assertEqual(self.window.performance.horizontalHeaderItem(7).text(), ui_text('m2t.adjusted_pnl'))
        self.assertEqual(self.window.performance.horizontalHeaderItem(8).text(), ui_text('m2t.recorded_drawdown'))
        self.assertEqual(self.window.performance.horizontalHeaderItem(7).toolTip(), ui_text('v2.attributed_pnl_hint'))
        self.assertIn(ui_text('v2.performance_valuation_hint'), self.window.performance.horizontalHeaderItem(8).toolTip())
