"""Real Application + durable simulator through desktop widgets; no broker calls."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton
from shiboken6 import isValid

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading import TradingWindow
from desktop_app.features.trading.wizard import StrategyWizard
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.workflows import fill_local_pending, mark_risk, total_mark
from quantlab.trading.adapters.shioaji import ShioajiAdapter
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderPlan, QuantityUnit, Quote, Side
from quantlab.trading.ports.contracts import BrokerPosition
from quantlab.trading.runtime.build import create_engine


class TradingUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp = tempfile.TemporaryDirectory(prefix='trading-ui-real-')
        self.root = Path(self.temp.name).resolve()
        self.engine = create_engine(self.root)
        self.facade = LocalFacade(self.engine)
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.show()
        self.app.processEvents()

    def drain(self):
        deadline = time.monotonic() + 5
        if self.window._operation is not None or self.window._priority_operation is not None:
            # Match the host's event loop: repeated qWait calls can delay Python
            # workers reacquiring the GIL between otherwise short native writes.
            timer = QTimer()
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.setInterval(5)

            def finished_or_expired():
                if (self.window._operation is None and self.window._priority_operation is None) or time.monotonic() >= deadline:
                    self.app.exit(0)

            timer.timeout.connect(finished_or_expired)
            timer.start()
            try:
                self.app.exec()
            finally:
                timer.stop()
                timer.timeout.disconnect(finished_or_expired)
                timer.deleteLater()
                QCoreApplication.sendPostedEvents(timer, QEvent.Type.DeferredDelete)
        if self.window._operation is not None or self.window._priority_operation is not None:
            self._timeout_diagnostics()
        self.assertIsNone(self.window._operation)
        self.assertIsNone(self.window._priority_operation)
        self.app.processEvents()

    def _timeout_diagnostics(self):
        """Observe the failed deadline without waiting, retrying, or taking engine locks."""
        operations = {}
        for name in ('_operation', '_priority_operation'):
            operation = getattr(self.window, name)
            if operation is not None:
                command = operation.command
                operations[name] = {
                    'action': command.action.value if command is not None else 'SNAPSHOT',
                    'running': operation.isRunning(),
                    'finished': operation.isFinished(),
                    'interruption_requested': operation.isInterruptionRequested(),
                    'object_name': operation.objectName(),
                }
        thread_names = {thread.ident: thread.name for thread in threading.enumerate()}
        evidence = {
            'test': self.id(),
            'original_deadline_seconds': 5,
            'operations': operations,
            'engine_day': str(self.engine.state.trading_day),
            'engine_version': self.engine.state.version,
            'ui_version': self.window.state.version,
            'threads': [
                {'ident': ident, 'name': thread_names.get(ident, 'Qt/native Python thread'), 'stack': traceback.format_stack(frame)}
                for ident, frame in sys._current_frames().items()
            ],
        }
        print('TRADING_UI_DRAIN_TIMEOUT ' + json.dumps(evidence, ensure_ascii=True), file=sys.stderr, flush=True)

    def test_drain_rejects_real_pending_worker_at_original_deadline_and_dispatches_events(self):
        entered, release = threading.Event(), threading.Event()
        original_snapshot = self.facade.snapshot
        dispatches = []
        ticker = QTimer()
        ticker.setInterval(5)
        ticker.timeout.connect(lambda: dispatches.append(True))

        def blocked_snapshot():
            entered.set()
            if not release.wait(8):
                raise RuntimeError('owned blocked-worker cleanup cap expired')
            return original_snapshot()

        try:
            with patch.object(self.facade, 'snapshot', side_effect=blocked_snapshot):
                self.window.refresh()
                self.assertTrue(entered.wait(1), 'the real QThread must enter the controlled snapshot')
                ticker.start()
                started = time.monotonic()
                with patch('sys.stderr', new_callable=io.StringIO) as diagnostics:
                    with self.assertRaisesRegex(AssertionError, 'is not None'):
                        self.drain()
                self.assertGreaterEqual(time.monotonic() - started, 5)
                self.assertIsNotNone(self.window._operation)
                self.assertTrue(self.window._operation.isRunning())
                self.assertTrue(dispatches, 'the original deadline must still dispatch Qt events')
                self.assertIn('TRADING_UI_DRAIN_TIMEOUT ', diagnostics.getvalue())
        finally:
            ticker.stop()
            ticker.deleteLater()
            QCoreApplication.sendPostedEvents(ticker, QEvent.Type.DeferredDelete)
            release.set()
            self.drain()

    def tearDown(self):
        self.drain()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(self.window), 'the fixture must destroy its owned Qt window')
        self.app.processEvents()
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.temp.cleanup()

    def open_wizard(self, configure):
        """Enter the same outer QApplication loop used by the desktop host.

        Earlier startup tests run app.exec() and terminate it. Qt can then
        return Rejected from a new nested dialog loop before its zero-timer
        acceptance runs. processEvents() alone does not reset that lifecycle.
        Re-entering the real outer loop also lets the fixture select the active
        modal, instead of accepting an old deferred child found by object type.
        """
        failures, handled = [], []

        def accept_active():
            handled.append(True)
            wizard = self.app.activeModalWidget()
            try:
                self.assertIsInstance(wizard, StrategyWizard)
                self.assertIs(wizard.parentWidget(), self.window)
                configure(wizard)
                wizard.accept()
                self.assertEqual(wizard.result(), StrategyWizard.DialogCode.Accepted)
            except BaseException as exc:
                failures.append(exc)
                if isinstance(wizard, StrategyWizard):
                    wizard.reject()
                self.app.exit(1)

        def open_modal():
            QTimer.singleShot(0, accept_active)
            try:
                self.window.new_strategy()
            except BaseException as exc:
                failures.append(exc)
            finally:
                self.app.exit(0)

        QTimer.singleShot(0, open_modal)
        self.app.exec()
        if failures:
            raise failures[0]
        self.assertEqual(handled, [True], 'the visible modal must be exercised exactly once')
        self.drain()

    def make_strategy(self, *, intraday=False, structured=False):
        def accept_wizard(wizard):
            wizard.name.setText('UI-created-stock')
            if intraday:
                wizard.policy.setCurrentIndex(1)
            if structured:
                wizard.rules.setCurrentIndex(wizard.rules.findData('STRUCTURED_JSON'))

        self.open_wizard(accept_wizard)
        self.assertEqual(len(self.engine.state.strategies), 1, self.window.notice.text())
        self.window.strategies.selectRow(0)

    def test_stock_wizard_to_research_deployment_holding_exit_and_performance(self):
        self.make_strategy()
        self.assertEqual(self.engine.state.strategies[0].policy.kind, HoldingKind.SWING)
        self.window.validate_button.click()
        self.drain()
        self.assertEqual(self.engine.state.strategies[0].state, 'RULE_VALID')
        self.window.research_button.click()
        self.drain()
        self.assertEqual(self.engine.state.strategies[0].state, 'RESEARCHED')
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.deploy_button.click()
        self.drain()
        self.assertEqual(self.engine.state.strategies[0].state, 'ACTIVE')
        self.window.reconcile_button.click()
        self.drain()
        self.window.resume_button.click()
        self.drain()
        self.assertFalse(self.engine.state.stopped)
        observed_ages = []
        for _ in range(13):
            self.window.overview_step.click()
            self.drain()
            observed_ages.extend(p.held_days for p in self.window.state.positions)
        self.assertIn(0, observed_ages)
        self.assertGreaterEqual(max(observed_ages), 4)
        self.assertTrue(any(not p.quantity for p in self.engine.state.positions), 'no actual position reached its exit')
        self.assertTrue(any(o.plan.reduce_only and o.filled for o in self.engine.state.orders))
        self.assertGreater(self.engine.state.costs, 0)
        self.assertEqual(self.window.performance.rowCount(), 1)
        self.assertIn('local-stock', self.window.context.text())
        self.assertTrue(self.window.state.synthetic_data)
        self.assertFalse((self.root / 'state-v1').exists())

    def test_intraday_qualification_failure_stays_visible_without_changing_policy(self):
        self.make_strategy(intraday=True)
        self.window.validate_button.click()
        self.drain()
        self.assertEqual(self.engine.state.strategies[0].policy.kind, HoldingKind.INTRADAY)
        self.assertEqual(self.engine.state.strategies[0].state, 'DRAFT')
        self.assertTrue(self.window.notice.text())
        self.assertIn('當沖資格', self.window.notice.text())
        self.assertIn('跨日', self.window.notice.text())
        self.assertFalse(self.engine.state.orders)
        self.assertIn(ui_text('v2.intraday'), self.window.strategies.item(0, 4).text())

    def test_old_version_selection_routes_exact_version_and_changes_do_not_rewrite_old_policy(self):
        self.make_strategy()
        original = self.engine.state.strategies[0]
        newer = replace(original.form, parent_strategy_id=original.strategy_id, holding_kind=HoldingKind.POSITION, min_days=20, max_days=100)
        receipt = self.facade.execute(UiCommand(UiAction.CREATE_STRATEGY, self.engine.state.version, strategy=newer))
        self.assertTrue(receipt.accepted, receipt)
        self.window.apply_state(self.facade.snapshot())
        self.window.strategies.selectRow(0)
        self.window.validate_button.click()
        self.drain()
        self.assertEqual(self.engine.state.strategies[0].state, 'RULE_VALID')
        self.assertEqual(self.engine.state.strategies[1].state, 'DRAFT')
        self.assertEqual(self.engine.state.strategies[0].policy.kind, HoldingKind.SWING)
        self.assertEqual(self.engine.state.strategies[1].policy.kind, HoldingKind.POSITION)

    def test_structured_draft_runs_research_and_preserves_held_policy_across_restart(self):
        self.make_strategy(structured=True)
        strategy = self.engine.state.strategies[0]
        self.assertIsNotNone(strategy.definition)
        self.assertTrue(strategy.draft_hash)
        self.assertEqual(strategy.form.draft_json, '')
        for widget in (self.window.validate_button, self.window.research_button):
            widget.click()
            self.drain()
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.deploy_button.click()
        self.drain()
        for widget in (self.window.reconcile_button, self.window.resume_button, self.window.overview_step, self.window.overview_step):
            widget.click()
            self.drain()
        self.assertEqual(len(self.window.state.positions), 1)
        before = self.window.state.positions[0]
        self.assertEqual(before.held_days, 1)
        self.assertEqual(before.account_ref, 'local-stock')
        order_count = len(self.engine.state.orders)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.engine = create_engine(self.root)
        self.facade = LocalFacade(self.engine)
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.setProperty('allow_close_for_tests', True)
        self.window.poll.stop()
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.engine.state.reconciled)
        self.assertEqual(len(self.engine.state.orders), order_count)
        after = self.window.state.positions[0]
        self.assertEqual(
            (after.lot_id, after.held_days, after.policy_label, after.entry_day), (before.lot_id, before.held_days, before.policy_label, before.entry_day)
        )
        for widget in (self.window.reconcile_button, self.window.resume_button):
            widget.click()
            self.drain()
        for _ in range(5):
            self.window.overview_step.click()
            self.drain()
        self.assertTrue(any(o.plan.reduce_only and o.filled for o in self.engine.state.orders))

    def test_malicious_draft_is_rejected_before_research_without_side_effects(self):
        marker = self.root / 'must-not-exist.txt'

        def accept_untrusted(wizard):
            wizard.rules.setCurrentIndex(wizard.rules.findData('STRUCTURED_JSON'))
            wizard.draft.setPlainText('{"exec":"write_file_and_submit_order"}')

        self.open_wizard(accept_untrusted)
        self.assertFalse(marker.exists())
        self.assertFalse(self.engine.state.strategies)
        self.assertFalse(self.engine.state.orders)
        self.assertTrue(self.window.notice.text())

    def test_reference_settings_save_restart_and_metadata_check_never_connects_broker(self):
        panel = self.window.broker_panel
        panel.fields['profile_alias'].setText('offline-reference')
        panel.fields['stock_account_ref'].setText('stock-masked-alias')
        panel.fields['broker_secret_ref'].setText('MarkAuto/v2/broker/offline-reference')
        panel._edited()
        with patch.object(ShioajiAdapter, 'connect', side_effect=AssertionError('metadata check must not login')):
            panel._save()
            self.drain()
            self.assertEqual(self.engine.state.broker_settings.profile_alias, 'offline-reference')
            self.assertTrue(self.engine.state.broker_settings.read_only)
            self.assertFalse(self.engine.state.broker_settings.execution_enabled)
            self.assertFalse(panel.dirty)
            panel._check()
            self.drain()
        self.assertEqual(len(self.window.state.broker_readiness.checks), 15)
        self.assertFalse(self.window.state.broker_readiness.external_verified)
        self.assertFalse(self.engine.state.orders)
        self.assertIn('外部驗證', panel.status.text())
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.engine = create_engine(self.root)
        self.facade = LocalFacade(self.engine)
        self.window = TradingWindow(self.facade, self.facade.snapshot())
        self.window.setProperty('allow_close_for_tests', True)
        self.window.poll.stop()
        self.assertEqual(self.window.broker_panel.fields['profile_alias'].text(), 'offline-reference')
        self.assertEqual(self.window.broker_panel.checks.rowCount(), 15)
        self.assertFalse(self.window.state.broker_readiness.external_verified)
        self.assertIsNotNone(self.window.broker_panel.findChild(QPushButton, 'broker_check_button'))

    def test_explicit_future_roll_wizard_produces_two_filled_legs_and_new_strategy_version(self):
        def accept_roll(wizard):
            wizard.market.setCurrentIndex(1)
            wizard.policy.setCurrentIndex(3)
            wizard.maximum.setValue(100)
            wizard.expiry_action.setCurrentIndex(wizard.expiry_action.findData('ROLL'))
            wizard.rules.setCurrentIndex(wizard.rules.findData('STRUCTURED_JSON'))
            self.assertEqual(wizard.roll_contract.currentData(), 'TAIFEX:TMF:202703')

        self.open_wizard(accept_roll)
        self.assertEqual(len(self.engine.state.strategies), 1, self.window.notice.text())
        self.window.strategies.selectRow(0)
        for widget in (self.window.validate_button, self.window.research_button):
            widget.click()
            self.drain()
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.deploy_button.click()
        self.drain()
        for widget in (self.window.reconcile_button, self.window.resume_button):
            widget.click()
            self.drain()
        steps = 0
        while self.engine.state.trading_day < date(2026, 12, 15):
            self.assertLess(steps, 40, 'calendar never reached the explicit expiry window')
            self.window.overview_step.click()
            self.drain()
            steps += 1
        completed = [roll for roll in self.engine.state.rolls if roll.status == 'COMPLETED']
        self.assertEqual(len(completed), 1, self.window.notice.text())
        self.assertTrue(any(order.plan.reduce_only and order.filled and order.plan.instrument_id == 'TAIFEX:TMF:202612' for order in self.engine.state.orders))
        self.assertTrue(
            any(not order.plan.reduce_only and order.filled and order.plan.instrument_id == 'TAIFEX:TMF:202703' for order in self.engine.state.orders)
        )
        self.assertGreater(self.engine.state.costs, 0)
        self.assertEqual(self.engine.state.strategies[0].state, 'RETIRED')
        self.assertTrue(any(s.version > 1 and s.state == 'ACTIVE' for s in self.engine.state.strategies))
        carried = next(p for p in self.window.state.positions if p.instrument_id == 'TAIFEX:TMF:202703')
        self.assertEqual(carried.entry_day, '2026-12-15')
        self.assertGreater(carried.held_days, 20, 'roll must preserve the original policy holding origin')

    def test_mobile_position_and_pending_order_differences_are_visible_without_becoming_managed(self):
        stock = self.engine.gateways['local-stock']
        stock.external_position(BrokerPosition('local-stock', 'TWSE:2330', 2000, 2000, QuantityUnit.SHARE, Decimal('10')))
        spec = next(s for s in self.engine.catalog.instruments if s.market is Market.INDEX_FUTURE)
        quote = self.engine.quotes[spec.instrument_id]
        now = self.engine.clock.now()
        plan = OrderPlan(
            'mobile-order-plan',
            'local-futures',
            Environment.LOCAL,
            spec.instrument_id,
            'mobile',
            1,
            Side.SELL,
            1,
            QuantityUnit.CONTRACT,
            quote.bid,
            quote.bid + spec.tick_size * 100,
            False,
            now,
            now + timedelta(seconds=30),
            self.engine.state.version,
        )
        futures = self.engine.gateways['local-futures']
        receipt = futures.submit(plan, 'external-mobile-order')
        self.engine.simulation.persist_remote()
        self.window.reconcile_button.click()
        self.drain()
        self.assertFalse(self.engine.state.reconciled)
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.engine.state.positions, 'external holdings must not become managed lots')
        position = next(item for item in self.window.state.reconciliation if item.kind == 'POSITION' and item.instrument_id == 'TWSE:2330')
        self.assertEqual((position.local_quantity, position.broker_quantity, position.sellable_quantity), (0, 2000, 2000))
        order = next(item for item in self.window.state.reconciliation if item.kind == 'ORDER')
        self.assertEqual(order.broker_order_ref, receipt.broker_order_ref)
        self.assertEqual(order.broker_quantity, -1)
        stock_row = next(i for i in range(self.window.reconciliation.rowCount()) if self.window.reconciliation.item(i, 1).text() == 'TWSE:2330')
        self.assertEqual(self.window.reconciliation.item(stock_row, 3).text(), '+0 ' + ui_text('v2.shares'))
        self.assertEqual(self.window.reconciliation.item(stock_row, 4).text(), '+2,000 ' + ui_text('v2.shares'))
        self.window.reconciliation.selectRow(stock_row)
        self.window.flatten_button.click()
        self.assertIn('不會代為平倉', self.window.notice.text())
        rejected = self.facade.execute(UiCommand(UiAction.FLATTEN, self.engine.state.version, target_id='external-mobile-position'))
        self.assertFalse(rejected.accepted, 'unknown external lot must be explicitly rejected')
        self.assertEqual(stock.remote_state.positions['TWSE:2330'].quantity, 2000)
        self.assertFalse(self.engine.state.orders)

    def test_mobile_direction_flip_cannot_turn_managed_flatten_into_new_short_exposure(self):
        def accept_future(wizard):
            wizard.market.setCurrentIndex(1)
            wizard.rules.setCurrentIndex(wizard.rules.findData('STRUCTURED_JSON'))

        self.open_wizard(accept_future)
        self.window.strategies.selectRow(0)
        for widget in (self.window.validate_button, self.window.research_button):
            widget.click()
            self.drain()
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.deploy_button.click()
        self.drain()
        for widget in (self.window.reconcile_button, self.window.resume_button, self.window.overview_step):
            widget.click()
            self.drain()
        lot = next(p for p in self.engine.state.positions if p.quantity)
        broker = self.engine.gateways[lot.account_ref]
        broker.external_position(BrokerPosition(lot.account_ref, lot.instrument_id, -1, 1, QuantityUnit.CONTRACT, lot.entry_price))
        self.engine.simulation.persist_remote()
        self.window.reconcile_button.click()
        self.drain()
        difference = next(item for item in self.window.state.reconciliation if item.kind == 'POSITION')
        self.assertEqual((difference.local_quantity, difference.broker_quantity), (1, -1))
        self.assertFalse(self.engine.state.reconciled)
        before_orders = len(self.engine.state.orders)
        self.window.positions.selectRow(0)
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.flatten_button.click()
        self.drain()
        self.assertEqual(len(self.engine.state.orders), before_orders, 'flatten must not enlarge the actual short position')
        self.assertEqual(broker.remote_state.positions[lot.instrument_id].quantity, -1)

    def test_intraday_swing_and_position_real_holdings_coexist_with_exact_policies_and_directions(self):
        def accepted(action, **values):
            receipt = self.facade.execute(UiCommand(action, self.engine.state.version, **values))
            self.assertTrue(receipt.accepted, receipt)
            return receipt.reference

        accepted(UiAction.RECONCILE)
        accepted(UiAction.RESUME)
        stock_specs = [s for s in self.engine.catalog.instruments if s.market is Market.STOCK]
        future = next(s for s in self.engine.catalog.instruments if s.market is Market.INDEX_FUTURE)
        scenarios = (
            (HoldingKind.INTRADAY, future, Side.SELL, 0, 0),
            (HoldingKind.SWING, stock_specs[0], Side.BUY, 3, 5),
            (HoldingKind.POSITION, stock_specs[1], Side.BUY, 20, 60),
        )
        expected = {}
        for kind, spec, direction, minimum, maximum in scenarios:
            account = 'local-stock' if spec.market is Market.STOCK else 'local-futures'
            form = StrategyForm(
                'mixed-' + kind.value,
                spec.market,
                kind,
                minimum,
                maximum,
                direction,
                spec.instrument_id,
                account,
                Environment.LOCAL,
                Decimal('30000'),
                Decimal('0.02'),
                'BUY_AND_HOLD',
            )
            reference = accepted(UiAction.CREATE_STRATEGY, strategy=form)
            for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
                accepted(action, target_id=reference)
            record = self.engine.strategy(reference)
            quote = self.engine.quotes[spec.instrument_id]
            price = quote.ask if direction is Side.BUY else quote.bid
            sign = 1 if direction is Side.BUY else -1
            stop = price - spec.tick_size * (100 if spec.market is Market.INDEX_FUTURE else 10) * sign
            now = self.engine.clock.now()
            plan = OrderPlan(
                'mixed-entry-' + kind.value,
                account,
                Environment.LOCAL,
                spec.instrument_id,
                record.strategy_id,
                record.version,
                direction,
                spec.lot_size,
                spec.unit,
                price,
                stop,
                False,
                now,
                now + timedelta(seconds=30),
                self.engine.state.version,
            )
            self.engine.submit(plan, record.policy, 'mixed-key-' + kind.value)
            fill_local_pending(self.engine)
            expected[spec.instrument_id] = (kind, direction, minimum, maximum, spec.unit)
        accepted(UiAction.RECONCILE)
        self.window.refresh()
        self.drain()
        self.assertEqual(len(self.window.state.positions), 3)
        self.assertEqual(self.window.positions.rowCount(), 3)
        self.assertEqual(len(self.engine.state.positions), 3)
        for row, view in enumerate(self.window.state.positions):
            kind, direction, minimum, maximum, unit = expected[view.instrument_id]
            self.assertIs(view.direction, direction)
            self.assertTrue(view.policy_label.startswith(kind.value + ':'))
            self.assertIs(view.unit, unit)
            self.assertEqual(view.held_days, 0)
            self.assertEqual(view.entry_day, self.engine.state.trading_day.isoformat())
            self.assertIn(self.engine.calendar.advance(self.engine.state.trading_day, minimum).isoformat(), view.exit_window)
            self.assertIn(self.engine.calendar.advance(self.engine.state.trading_day, maximum).isoformat(), view.exit_window)
            self.assertIn(ui_text('v2.long' if direction is Side.BUY else 'v2.short'), self.window.positions.item(row, 1).text())
            self.assertEqual(self.window.positions.item(row, 6).text(), view.entry_day)
            self.assertEqual(self.window.positions.item(row, 8).text(), view.exit_window)
            self.assertEqual(self.window.positions.item(row, 4).text(), view.account_ref)

    def test_transfer_performance_separates_executed_profit_from_owned_liquidation_and_drawdown(self):
        def accepted(action, **values):
            receipt = self.facade.execute(UiCommand(action, self.engine.state.version, **values))
            self.assertTrue(receipt.accepted, receipt)
            return receipt.reference

        def quote(bid):
            now = self.engine.clock.now()
            self.engine.quote(
                Quote(
                    'TWSE:2330',
                    Decimal(bid),
                    Decimal(bid) + Decimal('0.05'),
                    Decimal(bid),
                    now,
                    now,
                    self.engine.state.trading_day,
                    sequence=self.engine.quote_count + 1,
                    source='LOCAL_UI_TRANSFER_FIXTURE',
                )
            )

        accepted(UiAction.RECONCILE)
        accepted(UiAction.RESUME)
        form = StrategyForm(
            'UI-transfer',
            Market.STOCK,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            'TWSE:2330',
            'local-stock',
            Environment.LOCAL,
            Decimal('30000'),
            Decimal('0.02'),
            'BUY_AND_HOLD',
        )
        original = accepted(UiAction.CREATE_STRATEGY, strategy=form)
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            accepted(action, target_id=original)
        quote('9.90')
        record, now = self.engine.strategy(original), self.engine.clock.now()
        plan = OrderPlan(
            'UI-handoff-entry',
            'local-stock',
            Environment.LOCAL,
            'TWSE:2330',
            record.strategy_id,
            record.version,
            Side.BUY,
            1000,
            QuantityUnit.SHARE,
            Decimal('9.95'),
            Decimal('9.45'),
            False,
            now,
            now + timedelta(seconds=30),
            self.engine.state.version,
        )
        self.engine.submit(plan, record.policy, 'UI-handoff-entry')
        fill_local_pending(self.engine)
        mark_risk(self.engine)
        quote('10.50')
        mark_risk(self.engine)
        newer = accepted(
            UiAction.CREATE_STRATEGY,
            strategy=replace(form, parent_strategy_id=record.strategy_id, holding_kind=HoldingKind.POSITION, min_days=20, max_days=100),
        )
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            accepted(action, target_id=newer)
        accepted(UiAction.TRANSFER, target_id=self.engine.state.positions[0].lot_id, destination_strategy_id=newer)
        quote('10.20')
        mark_risk(self.engine)
        self.window.apply_state(self.facade.snapshot())
        self.window.navigation.setCurrentRow(4)
        self.app.processEvents()
        rows = self.window.state.performance
        self.assertEqual(tuple(row.net_pnl for row in rows), (Decimal('-20'), Decimal('0')))
        self.assertEqual(tuple(row.attributed_pnl for row in rows), (Decimal('428'), Decimal('-299')))
        self.assertEqual(tuple(row.drawdown for row in rows), (Decimal('170'), Decimal('299')))
        self.assertEqual(sum(row.attributed_pnl for row in rows), total_mark(self.engine))
        for index, row in enumerate(rows):
            self.assertEqual(self.window.performance.item(index, 4).text(), str(row.net_pnl))
            self.assertEqual(self.window.performance.item(index, 7).text(), str(row.attributed_pnl))
            self.assertEqual(self.window.performance.item(index, 8).text(), str(row.drawdown))
        self.assertEqual(self.window.performance.horizontalHeaderItem(7).text(), ui_text('v2.attributed_pnl'))
        self.assertEqual(self.window.performance.horizontalHeaderItem(7).toolTip(), ui_text('v2.attributed_pnl_hint'))
