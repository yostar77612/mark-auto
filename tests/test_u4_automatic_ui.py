"""Existing automatic/risk contracts through actual UI controls; no broker I/O."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from quantlab.trading.application.contracts import AccountRiskView, UiAction, UiReceipt, DailyIntentView
from desktop_app.shell.theme import style_automatic_controls
from quantlab.trading.application.preflight import PreflightCheck, PreflightView
from quantlab.trading.application.automatic_state import EvaluationStatus
from quantlab.trading.domain.auto_cycle import EvaluationCursor
from quantlab.trading.domain.models import Environment, OrderStatus
from quantlab.trading.domain.risk import AccountRiskLimits
from tests import test_trading_ui as support
from quantlab.trading.application.errors import ERROR_TABLE
from desktop_app.strings.catalog import ui_text


class AutomaticUiTests(unittest.TestCase):
    setUpClass = classmethod(support.TradingUiTests.setUpClass.__func__)

    def setUp(self):
        support.TradingUiTests.setUp(self)
        self.window.strategy_error_texts = {code: (text.explanation, text.action) for code, text in ERROR_TABLE.items()}
        self.window.style_automatic_controls = style_automatic_controls
        self.window.automatic_controls.render(self.window.state)

    tearDown = support.TradingUiTests.tearDown
    drain = support.TradingUiTests.drain

    def apply(self, **values):
        state = replace(self.window.state, version=self.window.state.version + 1, **values)
        self.facade.state = state
        self.window.apply_state(state)
        return state

    def accepted_reconciliation(self):
        self.apply(reconciliation_verified=True)
        with patch.object(self.facade, 'execute', side_effect=lambda command: (self.facade.commands.append(command), UiReceipt(True, 'completed', ''))[1]):
            self.window.automatic_controls.reconcile()
            self.drain()

    def test_stop_is_persistent_danger_and_cancel_default_without_send(self):
        stop = self.window.automatic_controls.stop
        self.assertEqual(stop.property('role'), 'danger')
        for page in range(6):
            self.window.navigation.setCurrentRow(page)
            self.app.processEvents()
            self.assertTrue(stop.isVisible())

        def cancel(box):
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            self.assertIn('保護性', box.text())
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            stop.click()
        self.assertEqual(self.facade.commands, [])

    def test_pause_reason_visible_in_header_overview_and_trading(self):
        controls = self.window.automatic_controls
        self.assertIn('已暫停', controls.header.text())
        self.assertIn('重新啟動', controls.header.text())
        for status, _, _, resume in controls.panels:
            self.assertIn('已暫停', status.text())
            self.assertIn('重新啟動', status.text())
            self.assertFalse(resume.isEnabled())

    def test_unverified_empty_position_projection_does_not_claim_zero_positions(self):
        self.apply(positions=(), financial_facts_verified=False)
        self.assertTrue(self.window.automatic_controls.cards[2].text().endswith(ui_text('watch.unknown')))
        self.apply(financial_facts_verified=True)
        self.assertTrue(self.window.automatic_controls.cards[2].text().endswith('0'))

    def test_resume_requires_accepted_auto_reconciliation_then_explicit_cancel_default(self):
        controls = self.window.automatic_controls
        controls.resume()
        self.assertEqual(self.facade.commands, [])
        self.accepted_reconciliation()
        self.assertIs(self.facade.commands[-1].action, UiAction.AUTO_RECONCILE)
        self.assertTrue(controls.panels[0][3].isEnabled())

        def cancel(box):
            self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', cancel):
            controls.resume()
        self.assertEqual(len(self.facade.commands), 1)
        with patch.object(self.window, '_confirm', return_value=True):
            controls.resume()
        self.drain()
        self.assertIs(self.facade.commands[-1].action, UiAction.AUTO_RESUME)
        self.assertEqual(self.facade.commands[-1].expected_version, self.window.state.version)

    def test_resume_rejects_scope_change_inside_confirmation(self):
        self.accepted_reconciliation()

        def changed(_):
            self.apply(context_epoch=self.window.state.context_epoch + 1)
            return True

        with patch.object(self.window, '_confirm', side_effect=changed):
            self.window.automatic_controls.resume()
        self.assertEqual(len(self.facade.commands), 1)

    def test_live_resume_widgets_handler_and_command_do_not_send(self):
        self.accepted_reconciliation()
        self.facade.commands.clear()
        self.apply(environment=Environment.LIVE)
        self.assertTrue(all(not panel[3].isEnabled() for panel in self.window.automatic_controls.panels))
        self.assertFalse(self.window.automatic_controls.header_resume.isEnabled())
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.automatic_controls.resume()
            self.window.command(UiAction.AUTO_RESUME)
        self.assertEqual(self.facade.commands, [])

    def test_preflight_shows_all_reasons_and_next_steps_without_inventing_pass(self):
        controls = self.window.automatic_controls
        self.assertEqual(len(controls.checks), 7)
        self.assertTrue(all('尚未檢查' in label.text() for label in controls.checks.values()))
        view = PreflightView(
            'local-stock',
            date.fromisoformat(self.window.state.trading_day),
            datetime.now(timezone.utc),
            (PreflightCheck('ca', 'NOT_REQUIRED'), PreflightCheck('market', 'FAIL', 'preflight_market')),
            True,
        )
        self.apply(preflight=(view,))
        self.assertIn('不需要 CA', controls.checks['ca'].text())
        self.assertIn('行情', controls.checks['market'].text())
        self.assertIn('確認', controls.checks['market'].text())
        controls.check()
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.CHECK_PREFLIGHT)
        self.assertEqual(command.account_ref, 'local-stock')

    def test_evaluation_uses_taipei_time_and_backend_result(self):
        now = datetime(2026, 11, 2, 1, 5, tzinfo=timezone.utc)
        evaluation = EvaluationStatus(EvaluationCursor('s', 1, 'TMF', '5m', now), now, now, 'COMPLETED', OrderStatus.FILLED)
        automatic = replace(self.window.state.automatic, evaluations=(evaluation,))
        self.apply(automatic=automatic)
        for _, details, _, _ in self.window.automatic_controls.panels:
            self.assertIn('09:05', details.text())
            self.assertNotIn('+00:00', details.text())
            self.assertNotIn('FILLED', details.text())

    def test_risk_defaults_account_draft_survives_poll_and_sends_typed_limits(self):
        risk = AccountRiskView('local-stock', AccountRiskLimits('local-stock'), Decimal('0'), Decimal('1800'), 0, False)
        self.apply(account_risks=(risk,))
        controls = self.window.account_risk_controls
        self.assertEqual(Decimal(controls.daily.text()), Decimal('3'))
        controls.daily.selectAll()
        QTest.keyClicks(controls.daily, '2')
        controls.order.selectAll()
        QTest.keyClicks(controls.order, '50000')
        self.apply()
        self.assertEqual(controls.daily.text(), '2')
        self.assertEqual(controls.order.text(), '50000')
        controls.save.setFocus()
        QTest.keyClick(controls.save, Qt.Key.Key_Space)
        self.drain()
        command = self.facade.commands[-1]
        self.assertIs(command.action, UiAction.SAVE_ACCOUNT_RISK)
        self.assertEqual(command.account_risk, AccountRiskLimits('local-stock', Decimal('.02'), Decimal('50000')))
        self.assertEqual(command.account_ref, 'local-stock')

    def test_invalid_nonfinite_risk_input_sends_nothing(self):
        risk = AccountRiskView('local-stock', AccountRiskLimits('local-stock'), None, Decimal('1800'), 0, True)
        self.apply(account_risks=(risk,))
        controls = self.window.account_risk_controls
        controls.daily.setText('NaN')
        controls.submit()
        self.assertEqual(self.facade.commands, [])

    def test_normal_daily_wait_is_neutral_and_does_not_request_resume(self):
        target = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)
        automatic = replace(self.window.state.automatic, state='WAITING_SESSION', reasons=('daily_waiting_session',), next_session_at=target)
        self.apply(automatic=automatic)
        controls = self.window.automatic_controls
        self.assertIn(ui_text('u4.waiting_session'), controls.header.text())
        self.assertEqual(controls.header.property('status'), 'neutral')
        self.assertFalse(controls.header_resume.isEnabled())
        self.assertIn('不需恢復', controls.header_resume.toolTip())
        for daily in controls.daily_panels:
            self.assertIn('09:00', daily.summary.text())
            self.assertNotIn('+00:00', daily.summary.text())
        self.assertEqual(self.facade.commands, [])
        self.apply(automatic=replace(automatic, state='PAUSED_WAITING_RESUME', reasons=('program_restarted',)))
        self.assertEqual(controls.header.property('status'), 'warning')

    def test_daily_intents_display_backend_window_and_unknown_without_financial_proposal(self):
        bar = datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc)
        opening = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)
        closing = datetime(2026, 11, 3, 5, 30, tzinfo=timezone.utc)
        ready = DailyIntentView('strategy-1', 1, 'TWSE:2330', 'ENTRY', '', bar, bar, '2026-11-03', opening, closing, 'READY')
        unknown = replace(ready, action='EXIT', lot_id='lot-1', phase='UNKNOWN', code='daily_signal_unresolved')
        automatic = replace(self.window.state.automatic, daily_intents=(ready, unknown), next_session_at=opening)
        self.apply(automatic=automatic)
        for daily in self.window.automatic_controls.daily_panels:
            self.assertEqual(daily.table.columnCount(), 6)
            self.assertEqual(daily.table.rowCount(), 2)
            self.assertEqual(daily.table.item(0, 3).text(), '2026/11/03')
            self.assertEqual(daily.table.item(0, 4).text(), '11/03 09:00 ~ 11/03 13:30')
            self.assertEqual(daily.table.item(0, 5).text(), ui_text('u4.daily_ready'))
            self.assertEqual(daily.table.item(1, 5).text(), ui_text('u4.daily_unknown'))
            self.assertIn(ERROR_TABLE['daily_signal_unresolved'].explanation, daily.table.item(1, 5).toolTip())
            self.assertNotIn('+00:00', daily.table.item(1, 5).toolTip())
            self.assertFalse(daily.empty.isVisible())
        self.assertEqual(self.facade.commands, [])

    def test_daily_dispatched_does_not_claim_a_fill_and_expiry_does_not_retarget(self):
        stamp = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)
        intent = DailyIntentView('strategy-1', 1, 'TWSE:2330', 'ENTRY', '', stamp, stamp, '2026-11-03', stamp, stamp, 'DISPATCHED', 'known-order')
        self.apply(automatic=replace(self.window.state.automatic, daily_intents=(intent,)))
        daily = self.window.automatic_controls.daily_panels[0]
        self.assertEqual(daily.table.item(0, 5).text(), ui_text('u4.daily_dispatched'))
        self.assertIn('known-order', daily.table.item(0, 5).toolTip())
        expired = replace(intent, phase='EXPIRED', code='daily_signal_expired')
        self.apply(automatic=replace(self.window.state.automatic, daily_intents=(expired,), next_session_at=None))
        self.assertEqual(daily.table.item(0, 3).text(), '2026/11/03')
        self.assertEqual(daily.table.item(0, 5).text(), ui_text('u4.daily_expired'))
        self.assertIn(ui_text('watch.unknown'), daily.summary.text())
        self.assertEqual(self.facade.commands, [])
