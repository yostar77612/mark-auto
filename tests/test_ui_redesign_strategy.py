"""Strategy tasks keep one configuration and the existing candidate safety gate."""

import os
import json
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton

from desktop_strings import ui_text
from desktop_theme import scale_window_fonts
from quantlab.core import ValidationError
from quantlab.strategies import builtin_strategies
from tests import test_desktop_pages, test_idea_research_ui


class StrategyWorkspaceTests(unittest.TestCase):
    setUpClass = classmethod(test_desktop_pages.PageInteractionTests.setUpClass.__func__)
    setUp = test_desktop_pages.PageInteractionTests.setUp
    tearDown = test_desktop_pages.PageInteractionTests.tearDown

    def test_each_task_exposes_only_its_workspace(self):
        page = self.window.strategy_page
        self.assertEqual(page.strategy_mode, 'ideas')
        self.assertTrue(page.idea_workspace.isVisibleTo(page))
        self.assertFalse(page.manual_workspace.isVisibleTo(page))
        page.mode_buttons['manual'].click()
        self.assertTrue(page.manual_workspace.isVisibleTo(page))
        self.assertFalse(page.idea_workspace.isVisibleTo(page))
        self.assertFalse(page.connection_workspace.isVisibleTo(page))
        page.mode_buttons['research'].click()
        self.assertEqual(page.tabs.currentIndex(), 1)
        self.assertTrue(page.use_candidate_button.isVisibleTo(page))
        self.assertFalse(page.use_candidate_button.isEnabled())
        self.assertFalse(page.manual_response.isVisibleTo(page))
        self.assertFalse(page.campaign_config.isVisibleTo(page))
        page.findChild(QPushButton, 'strategy_walk_forward_entry').click()
        self.assertEqual(page.tabs.currentIndex(), 2)
        self.assertFalse(any(button.isChecked() for button in page.mode_buttons.values()))
        self.assertTrue(page.wf_wizard.isVisibleTo(page))

    def test_task_buttons_support_keyboard_selection_and_keep_selected_task(self):
        page = self.window.strategy_page
        for mode, button in page.mode_buttons.items():
            for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
                button.setFocus()
                QTest.keyClick(button, key)
                self.assertEqual(page.strategy_mode, mode)
                self.assertTrue(button.isChecked())
                self.assertEqual(sum(item.isChecked() for item in page.mode_buttons.values()), 1)
        self.assertFalse(self.window.jobs.active)

    def test_small_desktop_uses_only_the_workspace_scrollbar(self):
        w = self.window
        page = w.strategy_page
        w.setFixedSize(1366, 768)
        w.onboarding.set_dismissed(True)
        for index in range(w.stack.count()):
            if w.stack.widget(index).isAncestorOf(page):
                w.navigation.setCurrentRow(index)
        w.show()
        scale_window_fonts(w, 1.5)
        for mode in ('ideas', 'research', 'manual', 'walk_forward'):
            page.choose_mode(mode)
            self.app.processEvents()
            with self.subTest(mode=mode):
                self.assertEqual(w.stack.currentWidget().verticalScrollBar().maximum(), 0)
                self.assertGreater(page.tabs.currentWidget().viewport().height(), 0)

    def test_model_and_consent_are_mirrors_of_existing_connection_panel(self):
        w = self.window
        page = w.strategy_page
        source = w.chatgpt_panel
        self.assertIs(w.chatgpt_controller, w.page_state.chatgpt_controller)
        w.chatgpt_controller.active_registration = 'a' * 32
        w.chatgpt_controller.registrations = (('a' * 32, 'plan_ready'),)
        w.chatgpt_controller.state = 'plan_ready'
        w.chatgpt_controller.models = ('offline-model-a', 'offline-model-b')
        w.chatgpt_controller.model_labels = (('offline-model-a', 'Offline model A'), ('offline-model-b', 'Offline model B'))
        w.chatgpt_controller.changed.emit()
        self.assertEqual(page.research_model.currentData(), source.model.currentData())
        page.research_model.setCurrentIndex(1)
        self.assertEqual(source.model.currentData(), 'offline-model-b')
        source.consent.setChecked(True)
        self.assertTrue(page.research_consent.isChecked())
        page.research_consent.setChecked(False)
        self.assertFalse(source.consent.isChecked())
        page.research_usage_consent.setChecked(True)
        self.assertTrue(source.included_usage_only.isChecked())
        source.included_usage_only.setChecked(False)
        self.assertFalse(page.research_usage_consent.isChecked())

    def test_connection_state_removes_redundant_login(self):
        w = self.window
        page = w.strategy_page
        controller = w.chatgpt_controller
        controller.active_registration = 'a' * 32
        controller.state = 'plan_ready'
        page.connection_status.setText('Offline connected fixture')
        self.assertTrue(page.chatgpt_sign_in_entry.isHidden())
        controller.active_registration = None
        controller.state = 'disconnected'
        page.connection_status.setText('Offline disconnected fixture')
        self.assertFalse(page.chatgpt_sign_in_entry.isHidden())

    def test_research_summary_tracks_authoritative_fields(self):
        page = self.window.strategy_page
        summary = page.findChild(QLabel, 'strategy_research_conditions')
        page.campaign_form.fields['train_start'].setText('7')
        page.campaign_form.fields['train_end'].setText('77')
        self.assertIn('7–77', summary.text())
        page.choose_mode('research')
        self.assertTrue(summary.isVisibleTo(page))
        self.assertFalse(page.campaign_form.isVisibleTo(page))
        toggle = next(button for button in page.findChildren(QToolButton) if button.text() == ui_text('redesign.strategy.research_limits'))
        toggle.setChecked(True)
        self.assertTrue(page.campaign_form.isVisibleTo(page))
        self.assertIs(page.campaign_form.fields['train_start'], self.window.campaign_form.fields['train_start'])

    def test_json_override_is_the_same_source_used_by_research_summary(self):
        page = self.window.strategy_page
        summary = page.findChild(QLabel, 'strategy_research_conditions')
        payload = {
            'splits': {'train': [9, 99], 'validation': [99, 120], 'oos': [120, 140], 'holdout': [140, 160]},
            'max_trials': 3,
            'max_improvements': 0,
            'ranking': {'minimum': '2', 'min_trades': 4},
        }
        page.campaign_config.setPlainText(json.dumps(payload))
        self.assertIn('9–99', summary.text())
        page.campaign_form.fields['train_start'].setText('77')
        self.assertIn('9–99', summary.text())
        page.campaign_config.setPlainText('{invalid')
        self.assertNotIn('9–99', summary.text())

    def test_rejected_candidate_shows_reason_and_cannot_be_adopted(self):
        page = self.window.strategy_page
        page.candidate_choice.addItem('Rejected offline candidate', {'campaign_folder': 'a' * 64})
        with patch.object(page.host, 'candidate_record', side_effect=ValidationError('Missing authoritative journal')):
            page.inspect_candidate()
        self.assertIn('Missing authoritative journal', page.candidate_notice.text())
        self.assertFalse(page.use_candidate_button.isEnabled())
        self.assertTrue(page.candidate_card.isHidden())
        self.assertEqual(page.candidate_notice.textFormat(), Qt.TextFormat.PlainText)

    def test_candidate_adoption_navigates_to_backtest_without_granting_paper(self):
        w = self.window
        page = w.strategy_page
        reference = {'campaign_folder': 'a' * 64, 'attempt_id': 'offline-attempt', 'strategy_hash': 'b' * 64}
        provenance = {'paper_qualified': False, 'evaluations': {}, 'source_type': 'synthetic'}
        spec = builtin_strategies()[0]
        with patch.object(page.host, 'candidate_record', return_value=(spec, provenance)):
            page.candidate_choice.addItem('Offline candidate', reference)
            page.inspect_candidate()
            self.assertTrue(page.use_candidate_button.isEnabled())
            previous_page = w.navigation.currentRow()
            page.use_candidate()
            self.assertEqual(w.navigation.currentRow(), previous_page)
            page.use_candidate_button.click()
        self.assertEqual(w.active_candidate, reference)
        self.assertTrue(w.parameters.isReadOnly())
        self.assertFalse(w.strategy_form.isEnabled())
        self.assertTrue(w.stack.currentWidget().isAncestorOf(w.backtest_page))
        self.assertFalse((w.root / 'selection.json').exists())


class IdeaWorkspaceTests(unittest.TestCase):
    setUpClass = classmethod(test_idea_research_ui.DialogTests.setUpClass.__func__)
    setUp = test_idea_research_ui.DialogTests.setUp

    def test_candidate_summary_tracks_completion_and_rejection(self):
        dialog = self.dialog
        dialog.record = {
            'task_id': test_idea_research_ui.TASK,
            'status': 'running',
            'candidates': [{'candidate_id': 'offline-a', 'name': 'Offline idea', 'idea': '<b>Untrusted idea</b>', 'backtestable': True}],
        }
        dialog.render_candidates()
        self.assertFalse(dialog.adopt_button.isEnabled())
        self.assertIn(ui_text('redesign.strategy.idea_pending'), dialog.candidate_summary.text())
        dialog.record['status'] = 'completed'
        dialog.render_status()
        self.assertTrue(dialog.adopt_button.isEnabled())
        self.assertIn(ui_text('redesign.strategy.idea_ready'), dialog.candidate_summary.text())
        self.assertEqual(dialog.candidate_summary.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn('<b>Untrusted idea</b>', dialog.candidate_summary.text())
        dialog.record['candidates'][0].update(backtestable=False, rejection_reason='Unsupported rule')
        dialog.show_candidate(0)
        self.assertFalse(dialog.adopt_button.isEnabled())
        self.assertIn('Unsupported rule', dialog.candidate_summary.text())
        self.assertFalse(dialog.candidate_detail.isVisibleTo(dialog.workspaces.widget(1)))

    def test_model_summary_follows_existing_model_selection(self):
        model = self.state.chatgpt_panel.model
        model.addItem('Second offline model', 'second-offline')
        model.setCurrentIndex(1)
        self.assertIn('Second offline model', self.dialog.model_summary.text())

    def test_running_research_keeps_cancel_visible_on_results_workspace(self):
        dialog = self.dialog
        dialog.workspaces.setCurrentIndex(1)
        dialog.record = {'task_id': test_idea_research_ui.TASK, 'status': 'running'}
        self.state.jobs.active = True
        self.state.last_operation = 'ui_idea_research'
        dialog.refresh_controls()
        self.assertTrue(dialog.cancel_button.isVisibleTo(dialog))
        self.assertTrue(dialog.cancel_button.isEnabled())
        dialog.cancel_button.click()
        self.state.jobs.cancel.assert_called_once()


if __name__ == '__main__':
    unittest.main()
