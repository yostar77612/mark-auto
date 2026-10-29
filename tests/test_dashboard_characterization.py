"""Host-offscreen characterization of the pre-dashboard overview contract.

Preserves control identities and refresh behavior; does not test financial math.
"""

from dataclasses import replace
import unittest

from PySide6.QtWidgets import QApplication, QListWidget, QPushButton

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.labels import event_label, policy_label, state_label
from tests.test_trading_ui import RecordingFacade


class OverviewCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = RecordingFacade()
        self.window = TradingWindow(self.facade, self.facade.state)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_overview_identities_and_buttons(self):
        page = self.window.pages.widget(0)
        for name in ('overview_new_strategy', 'overview_step', 'overview_stop', 'overview_reconcile'):
            with self.subTest(name=name):
                self.assertIsNotNone(page.findChild(QPushButton, name))
        for name in ('pending_issue_details', 'recent_events'):
            with self.subTest(name=name):
                self.assertIsNotNone(page.findChild(QListWidget, name))
        self.assertEqual(self.window.overview_deployments.objectName(), 'overview_strategy_summary')
        self.assertEqual(self.window.overview_status.text(), ui_text('v2.local_data'))

    def test_apply_state_overview_refresh_and_market_only_preservation(self):
        state = replace(self.facade.state, version=2, issues=('attention',), events=('started', 'stopped'))
        self.window.apply_state(state)
        strategy = state.strategies[0]
        self.assertEqual(
            self.window.overview_deployments.text(),
            f'{strategy.name} · v{strategy.version} · {policy_label(strategy.policy_label)} · {state_label(strategy.state)}',
        )
        self.assertEqual(self.window.issue_details.item(0).text(), 'attention')
        self.assertEqual([self.window.events.item(i).text() for i in range(2)], [event_label(code) for code in state.events])
        item = self.window.issue_details.item(0)
        self.window.apply_state(replace(state, market_revision=1))
        self.assertIs(self.window.issue_details.item(0), item)
        self.window.apply_state(replace(state, version=3, financial_facts_verified=False))
        self.assertEqual(self.window.overview_status.text(), ui_text('v2.context_facts_pending'))
