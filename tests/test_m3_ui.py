"""Real M3 widgets with reference-only fakes; never authoritative E1 evidence."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import time
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_app.components.async_status import AsyncStatus
from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.auto_strategy_rows import stage_text, state_text, strategy_rows, summary_text
from desktop_app.features.trading.build_auto_dialog import BuildAutoDialog
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.auto_strategy_views import AutoStrategyView, CandidateSummaryView, PromotionProgressView
from quantlab.trading.application.contracts import UiAction, UiReceipt
from quantlab.trading.domain.models import Environment, HoldingKind
from quantlab.trading.domain.promotion import Check, PauseReason, RunState, Stage
from tests.test_trading_ui import RecordingFacade


def view(**changes):
    item = AutoStrategyView(
        'frozen-one',
        2,
        HoldingKind.INTRADAY,
        'TMF_NEAR',
        Stage.BROKER_SIM,
        RunState.RUNNING,
        None,
        'a' * 64,
        PromotionProgressView(
            (Check('trading_days', True, Decimal(10), Decimal(10)), Check('trades', True, Decimal(6), Decimal(5))),
            True,
            True,
            drift_line_pct=Decimal('.03'),
            observed_drawdown_pct=Decimal('.01'),
        ),
    )
    return replace(item, **changes)


class Facade(RecordingFacade):
    def __init__(self):
        super().__init__()
        self.state = replace(self.state, auto_strategies=(view(),))
        self.catalog = ()

    def candidates(self):
        return self.catalog

    def execute(self, command):
        self.commands.append(command)
        return UiReceipt(True, 'ok', '', command.target_id)


class M3UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.facade = Facade()
        self.window = TradingWindow(self.facade, self.facade.state, research_status_factory=AsyncStatus)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)

    def tearDown(self):
        self.wait_workers()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_workers(self):
        deadline = time.monotonic() + 5
        while (self.window._operation is not None or self.window.auto_strategies.worker is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(self.window._operation)
        self.assertIsNone(self.window.auto_strategies.worker)

    def panel(self):
        self.window.auto_strategies.table.selectRow(0)
        return self.window.auto_strategies.panel

    def test_backtest_and_approved_intents_are_not_counted_as_running_or_eligible(self):
        for stage in (Stage.BACKTEST, Stage.LIVE_APPROVED):
            with self.subTest(stage=stage):
                row = view(stage=stage)
                self.assertEqual(state_text(row), ui_text('m3.state_waiting_checks'))
                self.assertEqual(summary_text((row,)), ui_text('m3.overview_card_value').format(0, 0, 0))
        self.assertEqual(summary_text((view(),)), ui_text('m3.overview_card_value').format(1, 0, 1))

    def test_build_form_reference_only_defaults_and_stock_disabled(self):
        candidate = CandidateSummaryView('opaque-ref', 'statistical_edge', datetime.now(timezone.utc), '1d')
        dialog = BuildAutoDialog(candidate, 'sim-futures')
        self.assertFalse(dialog.kind.model().item(1).isEnabled())
        self.assertFalse(dialog.kind.model().item(2).isEnabled())
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.confirm.isVisible())
        request = dialog.request()
        self.assertEqual(request.candidate_ref, 'opaque-ref')
        self.assertEqual(request.bar_interval, '5m')
        self.assertEqual(request.sizing.contracts, 1)
        self.assertEqual(request.protective_stop_pct, Decimal('.01'))
        self.assertTrue(request.start_in_sim)
        self.assertNotIn('signal_spec_json', request.__dataclass_fields__)
        dialog.interval.setCurrentIndex(0)
        self.assertIn(ui_text('u3.minute'), dialog.warning.text())
        dialog.close()
        dialog.deleteLater()

    def test_catalog_unavailable_is_fail_closed_and_async(self):
        controls = self.window.auto_strategies
        controls.load_candidates()
        self.assertFalse(controls.build_button.isEnabled())
        self.wait_workers()
        self.assertFalse(controls.build_button.isEnabled())
        self.assertIn(ui_text('m3.candidates_unavailable'), controls.status.label.text())
        self.assertEqual(self.facade.commands, [])

    def test_catalog_error_does_not_expose_exception(self):
        self.facade.candidates = lambda: (_ for _ in ()).throw(RuntimeError('private-path-secret'))
        self.window.auto_strategies.load_candidates()
        self.wait_workers()
        self.assertNotIn('private-path-secret', self.window.auto_strategies.status.label.text())
        self.assertFalse(self.window.auto_strategies.build_button.isEnabled())

    def test_close_is_nonblocking_and_refused_while_catalog_worker_runs(self):
        entered, release = Event(), Event()

        def blocked():
            entered.set()
            release.wait(5)
            return ()

        self.facade.candidates = blocked
        self.window.show()
        self.app.processEvents()
        self.window.auto_strategies.load_candidates()
        try:
            self.assertTrue(entered.wait(2))
            started = time.monotonic()
            self.assertFalse(self.window.close())
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(self.window.isVisible())
            self.assertIsNotNone(self.window.auto_strategies.worker)
        finally:
            release.set()
            self.wait_workers()
        self.assertTrue(self.window.close())

    def test_backtest_pause_is_disabled_with_waiting_explanation(self):
        panel = self.panel()
        panel.render(view(stage=Stage.BACKTEST))
        self.assertFalse(panel.buttons[UiAction.PAUSE_AUTO_STRATEGY].isEnabled())
        self.assertEqual(panel.buttons[UiAction.PAUSE_AUTO_STRATEGY].toolTip(), ui_text('m3.state_waiting_checks'))
        panel.act(UiAction.PAUSE_AUTO_STRATEGY)
        self.assertFalse(self.facade.commands)

    def test_context_change_invalidates_candidates(self):
        self.facade.catalog = (CandidateSummaryView('opaque-ref', 'statistical_edge', datetime.now(timezone.utc), '1d'),)
        controls = self.window.auto_strategies
        controls.load_candidates()
        self.wait_workers()
        self.assertTrue(controls.build_button.isEnabled())
        self.window.apply_state(replace(self.facade.state, version=2, account_ref='another-account'))
        self.assertFalse(controls.build_button.isEnabled())

    def test_approval_cancel_does_not_send_and_confirmation_is_bound(self):
        panel = self.panel()
        with patch.object(self.window, '_confirm', return_value=False):
            panel.act(UiAction.APPROVE_LIVE_INTENT)
        self.assertFalse(self.facade.commands)
        with patch.object(self.window, '_confirm', return_value=True):
            panel.act(UiAction.APPROVE_LIVE_INTENT)
        self.wait_workers()
        command = self.facade.commands[-1]
        self.assertEqual(command.environment, self.facade.state.environment)
        self.assertEqual(command.account_ref, self.facade.state.account_ref)
        self.assertEqual(command.action, UiAction.APPROVE_LIVE_INTENT)
        self.assertEqual(command.auto_strategy.version, 2)
        self.assertEqual(command.auto_strategy.frozen_hash, 'a' * 64)
        self.assertTrue(command.auto_strategy.confirmed)
        self.assertFalse(view().live_available)

    def test_confirmation_defaults_to_cancel(self):
        seen = []

        def inspect(box):
            seen.append(box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel))
            return QMessageBox.StandardButton.Cancel

        with patch.object(QMessageBox, 'exec', inspect):
            self.panel().act(UiAction.APPROVE_LIVE_INTENT)
        self.assertEqual(seen, [True])
        self.assertFalse(self.facade.commands)

    def test_context_change_during_confirmation_sends_nothing(self):
        panel = self.panel()

        def change(_):
            self.window.state = replace(self.window.state, context_epoch=100)
            return True

        with patch.object(self.window, '_confirm', side_effect=change):
            panel.act(UiAction.APPROVE_LIVE_INTENT)
        self.assertFalse(self.facade.commands)

    def test_state_version_change_during_owner_confirmation_sends_nothing(self):
        panel = self.panel()

        def advance(_):
            self.window.state = replace(self.window.state, version=self.window.state.version + 1)
            return True

        for action in (UiAction.APPROVE_LIVE_INTENT, UiAction.RETIRE_AUTO_STRATEGY):
            with self.subTest(action=action), patch.object(self.window, '_confirm', side_effect=advance):
                panel.render(view())
                panel.act(action)
                self.assertFalse(self.facade.commands)

    def test_state_version_change_during_build_dialog_sends_nothing(self):
        candidate = CandidateSummaryView('opaque-ref', 'statistical_edge', datetime.now(timezone.utc), '1d')
        controls = self.window.auto_strategies
        controls.candidate_scope = controls.scope()
        controls.loaded((candidate,))

        def advance(dialog):
            self.window.state = replace(self.window.state, version=self.window.state.version + 1)
            return dialog.DialogCode.Accepted

        with patch.object(BuildAutoDialog, 'exec', advance):
            controls.build_selected()
        self.assertFalse(self.facade.commands)

    def test_incomplete_history_and_retired_cannot_approve(self):
        panel = self.panel()
        panel.render(view(progress=PromotionProgressView(eligible=True, history_complete=False)))
        self.assertFalse(panel.buttons[UiAction.APPROVE_LIVE_INTENT].isEnabled())
        panel.render(view(run_state=RunState.RETIRED))
        self.assertTrue(all(not b.isEnabled() for b in panel.buttons.values()))
        panel.render(view(stage=Stage.LIVE_APPROVED))
        self.assertFalse(panel.buttons[UiAction.APPROVE_LIVE_INTENT].isEnabled())
        self.assertIn(ui_text('m2t.orders_disabled'), panel.stage.text())

    def test_pause_resume_retire_commands(self):
        panel = self.panel()
        panel.act(UiAction.PAUSE_AUTO_STRATEGY)
        self.wait_workers()
        self.assertFalse(self.facade.commands[-1].auto_strategy.confirmed)
        panel.render(view(run_state=RunState.PAUSED, pause_reason=PauseReason.MANUAL))
        panel.act(UiAction.RESUME_AUTO_STRATEGY)
        self.wait_workers()
        self.assertEqual(self.facade.commands[-1].action, UiAction.RESUME_AUTO_STRATEGY)
        with patch.object(self.window, '_confirm', return_value=False):
            panel.act(UiAction.RETIRE_AUTO_STRATEGY)
        self.assertEqual(len(self.facade.commands), 2)

    def test_translated_six_column_rows_and_approval_warning(self):
        row = strategy_rows((view(),))[0][1]
        self.assertEqual(len(row), 6)
        self.assertFalse(any('BROKER_SIM' in value or 'INTRADAY' in value for value in row))
        self.assertIn(ui_text('m2t.orders_disabled'), stage_text(view(stage=Stage.LIVE_APPROVED)))
        for reason in PauseReason:
            self.assertNotIn(reason.value, state_text(view(run_state=RunState.PAUSED, pause_reason=reason)))

    def test_ai_strategy_surfaces_are_hidden_while_parked(self):
        from desktop_app.components.result_panels import WalkForwardResults
        from desktop_app.features.trading.auto_strategy_rows import SHOW_AI_STRATEGY

        self.assertFalse(SHOW_AI_STRATEGY)
        tabs = self.window.strategy_tabs
        self.assertFalse(tabs.isTabVisible(tabs.indexOf(self.window.auto_strategies)))
        self.assertTrue(self.window.dashboard.auto_summary.isHidden())
        results = WalkForwardResults()
        self.assertTrue(results.build_auto.isHidden())
        results.deleteLater()

    def test_research_display_verdict_never_enables_build(self):
        from desktop_app.components.result_panels import WalkForwardResults

        results = WalkForwardResults()
        results.set_result({'verdict': 'statistical_edge', 'candidate_ref': 'untrusted-display-ref'})
        self.assertFalse(results.build_auto.isEnabled())
        self.assertEqual(results.build_auto.toolTip(), ui_text('m3.candidates_unavailable'))
        results.deleteLater()

    def test_owner_approval_keeps_reviewed_version_when_poll_updates(self):
        panel = self.panel()

        def update(_):
            panel.render(view(version=3, frozen_hash='b' * 64))
            return True

        with patch.object(self.window, '_confirm', side_effect=update):
            panel.act(UiAction.APPROVE_LIVE_INTENT)
        self.wait_workers()
        payload = self.facade.commands[-1].auto_strategy
        self.assertEqual((payload.version, payload.frozen_hash), (2, 'a' * 64))

    def test_build_failure_restores_controls_and_plain_status(self):
        controls = self.window.auto_strategies
        self.facade.catalog = (CandidateSummaryView('opaque-ref', 'statistical_edge', datetime.now(timezone.utc), '1d'),)
        controls.load_candidates()
        self.wait_workers()
        dialog = BuildAutoDialog(self.facade.catalog[0], self.facade.state.account_ref)
        self.facade.execute = lambda command: (_ for _ in ()).throw(RuntimeError('private-error'))
        self.window.command(UiAction.BUILD_AUTO_STRATEGY, auto_build=dialog.request())
        self.wait_workers()
        self.assertTrue(controls.build_button.isEnabled())
        self.assertEqual(controls.status.label.text(), ui_text('v2.connection_failed'))
        dialog.deleteLater()

    def test_progress_reads_audit_values_not_recomputed_metrics(self):
        panel = self.panel()
        self.assertIn('10/10', panel.days.text())
        self.assertIn('6/5', panel.progress.text())
        self.assertIn('3.00%', panel.drift.text())
        self.assertEqual(panel.gauge.value(), 33)


class M3CompositionStartupTests(unittest.TestCase):
    """Actual Qt windows on LOCAL and fake-SDK BROKER_SIMULATION composition."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def show_composed(self, engine):
        from quantlab.trading.application.facade import LocalFacade
        from quantlab.trading.runtime.auto_strategy import AutoStrategyRuntime
        from quantlab.trading.runtime.candidate_catalog import ResearchWorkspaceCandidateCatalog
        from pathlib import Path

        engine.auto_runtime = AutoStrategyRuntime(engine, ResearchWorkspaceCandidateCatalog(Path('/not-an-e1-producer')))
        facade = LocalFacade(engine)
        window = TradingWindow(facade, facade.snapshot(), research_status_factory=AsyncStatus)
        window.setProperty('allow_close_for_tests', True)
        window.poll.stop()
        try:
            window.resize(1366, 768)
            window.show()
            self.app.processEvents()
            self.assertTrue(window.isVisible())
            self.assertEqual(window.state.environment, engine.configuration.environment)
            self.assertFalse(window.auto_strategies.build_button.isEnabled())
            self.assertFalse(window.state.auto_strategies)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_local_composition_opens_real_window(self):
        import tempfile
        from pathlib import Path
        from quantlab.trading.runtime.build import create_engine

        with tempfile.TemporaryDirectory(prefix='m3-local-window-') as folder:
            engine = create_engine(Path(folder))
            try:
                self.show_composed(engine)
            finally:
                engine.journal.close()
                engine.simulation.ledger.close()

    def test_fake_broker_composition_opens_without_financial_calls(self):
        from tests.test_trading_broker_runtime import BrokerRuntimeTests, ClientFactory
        from quantlab.trading.adapters.storage.ledger import Ledger
        from quantlab.trading.application.context import Catalog
        from quantlab.trading.domain.costs import FeeSchedule
        from quantlab.trading.runtime.build import synthetic_calendar

        fixture = BrokerRuntimeTests('test_same_core_reconciles_broker_query_port_and_refuses_every_execution')
        fixture.setUp()
        journal = None
        try:
            factory = ClientFactory()
            runtime = fixture.runtime(fixture.complete_settings(), factory)
            runtime.adapter.attach_authenticated()  # In-memory SDK double only, no login.
            journal = Ledger(fixture.root / 'm3-window.sqlite', 'm3-window', fixture.clock.now())
            engine = runtime.compose_engine(
                journal, fixture.clock, synthetic_calendar(), FeeSchedule(), Catalog((fixture.broker_spec,)), ownership_clock=fixture.clock.now
            )
            self.show_composed(engine)
            self.assertEqual(factory.created, [Environment.BROKER_SIMULATION])
            self.assertFalse(runtime.adapter.execution_enabled)
            self.assertEqual(factory.client.placed, [])
            self.assertEqual(factory.client.order_calls, [])
        finally:
            if journal is not None:
                journal.close()
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
