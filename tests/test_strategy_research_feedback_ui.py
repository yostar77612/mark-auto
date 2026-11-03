"""Visible progress and exact-target results over existing readonly research commands."""

from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from functools import partial
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from desktop_app.features.trading.widgets import selected_id
from desktop_app.features.trading import TradingWindow
from desktop_app.components.async_status import AsyncStatus
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import UiAction, UiReceipt
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment
from tests import test_trading_ui as support


class StrategyResearchFeedbackTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)
    tearDown = support.TradingUiTests.tearDown
    drain = support.TradingUiTests.drain

    def setUp(self):
        with patch.object(support, 'TradingWindow', partial(TradingWindow, research_status_factory=AsyncStatus)):
            support.TradingUiTests.setUp(self)
        self.window.strategy_error_texts = {code: (entry.explanation, entry.action) for code, entry in ERROR_TABLE.items()}
        strategy = replace(self.window.state.strategies[0], state='RULE_VALID', evidence='NONE', allocation=Decimal('30000'))
        self.facade.state = replace(self.window.state, strategies=(strategy,), positions=())
        self.window.apply_state(self.facade.state)
        self.window.strategies.selectRow(0)
        self.window.navigation.setCurrentRow(1)
        self.window.strategy_tabs.setCurrentIndex(1)
        self.feedback = self.window.strategy_controls.research_feedback

    @contextmanager
    def held(self, action=UiAction.RESEARCH, *, evidence='LOCAL_SYNTHETIC_TRAINING', accepted=True, code='completed', crash=False):
        entered, release = Event(), Event()
        original = self.facade.state
        strategy = replace(original.strategies[0], state='RULE_VALID' if action is UiAction.VALIDATE else 'RESEARCHED', evidence=evidence)
        result = replace(original, version=original.version + 1, strategies=(strategy, *original.strategies[1:]))

        def execute(command):
            self.facade.commands.append(command)
            entered.set()
            if not release.wait(3):
                raise TimeoutError('test release missing')
            if crash:
                raise ConnectionError('PRIVATE_PERSON SECRET')
            self.facade.state = result if accepted else original
            return UiReceipt(accepted, code, 'PRIVATE_PERSON SECRET', command.target_id)

        with patch.object(self.facade, 'execute', side_effect=execute):
            (self.window.validate_button if action is UiAction.VALIDATE else self.window.research_button).click()
            try:
                self.assertTrue(entered.wait(1))
                yield
            finally:
                release.set()
                self.drain()

    def test_both_actions_immediately_show_progress_and_prevent_duplicate_submission(self):
        for action in (UiAction.RESEARCH, UiAction.VALIDATE):
            with self.subTest(action=action), self.held(action):
                before = len(self.facade.commands)
                self.assertTrue(self.feedback.status.isVisible())
                self.assertIn(ui_text('research.feedback.running'), self.feedback.status.label.text())
                self.assertFalse(self.window.context_details.isVisible())
                self.window.apply_state(self.window.state)
                self.assertFalse(self.window.research_button.isEnabled())
                self.assertFalse(self.window.validate_button.isEnabled())
                self.assertEqual(self.window.research_button.toolTip(), ui_text('research.feedback.running'))
                self.window.research_button.click()
                self.window.validate_button.click()
                self.assertEqual(len(self.facade.commands), before)
            self.assertTrue(self.window.research_button.isEnabled())
            self.assertTrue(self.window.validate_button.isEnabled())

    def test_local_success_survives_polling_and_keyboard_next_only_navigates(self):
        with self.held():
            pass
        text = self.feedback.status.label.text()
        self.assertIn(ui_text('research.feedback.passed'), text)
        self.assertIn(ui_text('research.feedback.local'), text)
        self.assertNotIn('PRIVATE_PERSON', text)
        self.window.apply_state(self.window.state)
        self.assertEqual(self.feedback.status.label.text(), text)
        self.assertTrue(self.feedback.status.isVisible())
        self.assertEqual(self.feedback.status.action.accessibleName(), ui_text('research.feedback.activate'))
        self.feedback.status.action.setFocus()
        QTest.keyClick(self.feedback.status.action, Qt.Key.Key_Space)
        self.assertEqual(self.window.strategy_tabs.currentIndex(), 0)
        self.assertTrue(self.window.deploy_button.isEnabled())
        self.assertIs(self.window.focusWidget(), self.window.deploy_button)
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.RESEARCH])

    def test_official_source_comes_from_result_even_in_local_environment(self):
        with self.held(evidence='OFFICIAL_DAILY_TRAINING'):
            pass
        self.assertIs(self.window.state.environment, Environment.LOCAL)
        self.assertIn(ui_text('research.feedback.official'), self.feedback.status.label.text())
        self.assertNotIn(ui_text('research.feedback.local'), self.feedback.status.label.text())

    def test_validation_success_requires_research_and_next_does_not_run_it(self):
        with self.held(UiAction.VALIDATE, evidence='NONE'):
            pass
        self.assertIn(ui_text('research.feedback.validated'), self.feedback.status.label.text())
        self.assertIn(ui_text('research.feedback.no_data'), self.feedback.status.label.text())
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.feedback.status.action.click()
        self.assertIs(self.window.focusWidget(), self.window.research_button)
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.VALIDATE])

    def test_rejection_uses_error_table_reason_and_next_step_without_private_message(self):
        with self.held(accepted=False, code='research_worker_failed'):
            pass
        text = self.feedback.status.label.text()
        self.assertIn(ui_text('research.feedback.failed'), text)
        self.assertIn(ERROR_TABLE['research_worker_failed'].explanation, text)
        self.assertIn(ERROR_TABLE['research_worker_failed'].action, text)
        self.assertNotIn('PRIVATE_PERSON', text)
        self.assertNotIn('SECRET', text)
        self.assertFalse(self.feedback.status.action.isVisible())

    def test_transport_failure_is_unconfirmed_and_releases_controls(self):
        with self.held(crash=True):
            pass
        text = self.feedback.status.label.text()
        self.assertIn(ui_text('research.feedback.unconfirmed'), text)
        self.assertIn(ERROR_TABLE['operation_failed'].action, text)
        self.assertNotIn('SECRET', text)
        self.assertTrue(self.window.research_button.isEnabled())
        self.assertTrue(self.window.validate_button.isEnabled())

    def test_unknown_evidence_never_claims_success_or_official_source(self):
        with self.held(evidence='UNRECOGNIZED_PRIVATE_SOURCE'):
            pass
        text = self.feedback.status.label.text()
        self.assertIn(ui_text('research.feedback.unconfirmed'), text)
        self.assertNotIn(ui_text('research.feedback.passed'), text)
        self.assertNotIn('UNRECOGNIZED_PRIVATE_SOURCE', text)
        self.assertFalse(self.feedback.status.action.isVisible())

    def test_selection_changes_cannot_retarget_the_completed_result_or_next_action(self):
        other = replace(self.window.state.strategies[0], strategy_id='strategy-2', name='Second strategy')
        self.facade.state = replace(self.window.state, version=self.window.state.version + 1, strategies=(*self.window.state.strategies, other))
        self.window.apply_state(self.facade.state)
        self.window.strategies.selectRow(0)
        with self.held():
            self.window.strategies.selectRow(1)
        self.window.strategies.selectRow(1)
        self.assertIn('Local strategy', self.feedback.status.label.text())
        self.assertNotIn('Second strategy', self.feedback.status.label.text())
        self.feedback.status.action.click()
        self.assertEqual(selected_id(self.window.strategies), 'strategy-1:1')
        self.assertEqual(len(self.facade.commands), 1)

    def test_changed_context_hides_result_and_retained_callback_cannot_navigate(self):
        with self.held():
            changed = replace(self.window.state, context_id='another', context_epoch=self.window.state.context_epoch + 1)
            self.window.apply_state(changed)
        self.assertEqual(self.window.state.context_id, 'another')
        self.assertFalse(self.feedback.status.isVisible())
        self.feedback.return_to_list()
        self.assertEqual(self.window.strategy_tabs.currentIndex(), 1)
        self.assertEqual(len(self.facade.commands), 1)

    def test_stale_result_never_replaces_newer_stop_state_or_offers_activation(self):
        with self.held():
            changed = replace(self.window.state, version=self.window.state.version + 2, engine_state='STOPPED')
            self.window.apply_state(changed)
        self.assertEqual(self.window.state.version, changed.version)
        self.assertEqual(self.window.state.engine_state, 'STOPPED')
        self.assertIn(ui_text('research.feedback.unconfirmed'), self.feedback.status.label.text())
        self.assertFalse(self.feedback.status.action.isVisible())

    def test_existing_priority_stop_flow_also_preserves_the_new_feedback(self):
        support.TradingUiTests.test_priority_stop_is_accepted_while_research_blocks_and_old_result_cannot_restore_running(self)
        self.assertFalse(self.feedback.pending)
        self.assertIn(ui_text('research.feedback.unconfirmed'), self.feedback.status.label.text())
        self.assertFalse(self.feedback.status.action.isVisible())

    def test_busy_query_rejection_does_not_invent_a_pending_research(self):
        entered, release = Event(), Event()

        def snapshot():
            entered.set()
            release.wait(3)
            return self.facade.state

        with patch.object(self.facade, 'snapshot', side_effect=snapshot):
            self.window.refresh()
            try:
                self.assertTrue(entered.wait(1))
                self.window.research_button.click()
                self.assertFalse(self.feedback.pending)
                self.assertFalse(self.feedback.status.isVisible())
                self.assertEqual(self.facade.commands, [])
            finally:
                release.set()
                self.drain()

    def test_live_result_next_retains_existing_disabled_activation(self):
        strategy = replace(self.window.state.strategies[0], environment=Environment.LIVE)
        self.facade.state = replace(self.window.state, version=self.window.state.version + 1, environment=Environment.LIVE, strategies=(strategy,))
        self.window.apply_state(self.facade.state)
        self.window.strategies.selectRow(0)
        with self.held(evidence='OFFICIAL_DAILY_TRAINING'):
            pass
        self.assertEqual(self.feedback.status.action.text(), ui_text('research.feedback.list'))
        self.feedback.status.action.click()
        self.assertFalse(self.window.deploy_button.isEnabled())
        self.window.deploy_button.click()
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.RESEARCH])
