"""Explicit DEPLOY prepares outside locks, then binds all current authority."""

from dataclasses import replace
from datetime import date
from threading import RLock, Thread
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_official_daily_admission as admission
import test_official_daily_runtime_e2e as native
from quantlab.trading.application.context import ExecutionConfiguration
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import UiAction, UiCommand, UiReceipt
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.daily_deployment import prepare_daily_deployment
from quantlab.trading.runtime.protocol import Operation


SIM = Environment.BROKER_SIMULATION


class DailyDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.case = admission.OfficialDailyAdmissionTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.engine = self.case.engine
        self.record = replace(self.case.record, state='DISABLED')
        self.engine.state = replace(self.engine.state, strategies=(self.record,))
        self.engine.configuration = ExecutionConfiguration(environment=SIM)
        self.engine.daily_signal_cached_only = True
        self.source = self.case.source
        self.owner = SimpleNamespace(lock=RLock(), shared=object())
        self.stamp = 'healthy-owner-stamp'
        self.runtime = SimpleNamespace(owner_stamp=lambda: self.stamp)
        self.facade = SimpleNamespace(engine=self.engine, execute=Mock(return_value=UiReceipt(True, 'completed', '')))
        self.bundle = SimpleNamespace(
            engine=self.engine,
            lock=RLock(),
            sinopac_connection=self.owner,
            automatic_runtime=self.runtime,
            manual_runtime=object(),
            facade=self.facade,
            launch=SimpleNamespace(environment=SIM),
            version_offset=7,
            closing=False,
            resources_closed=False,
            control_failed=False,
            transitioning=False,
        )
        self.command = UiCommand(UiAction.DEPLOY, self.engine.state.version + 7, target_id=f'{self.record.strategy_id}:{self.record.version}', environment=SIM)

    def rejects_after_change(self, change):
        actual = self.source.history

        def history(*args, **kwargs):
            result = actual(*args, **kwargs)
            change()
            return result

        self.source.history = history
        receipt = prepare_daily_deployment(self.bundle, self.command)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'state_conflict')
        self.facade.execute.assert_not_called()

    def test_warming_is_outside_all_locks_and_facade_keeps_original_version_translation(self):
        actual = self.source.history
        checked = []

        def history(*args, **kwargs):
            def peer():
                with self.bundle.lock, self.engine.lock, self.owner.lock:
                    checked.append(True)

            worker = Thread(target=peer)
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), 'deployment source read held a writer/owner lock')
            self.assertNotIn('cached_only', kwargs, 'warming must perform outside-lock full verification')
            return actual(*args, **kwargs)

        self.source.history = history
        prior = self.engine.state
        receipt = prepare_daily_deployment(self.bundle, self.command)
        self.assertTrue(receipt.accepted)
        self.assertEqual(checked, [True])
        self.facade.execute.assert_called_once_with(replace(self.command, expected_version=self.engine.state.version))
        self.assertIs(self.engine.state, prior, 'preparation has no journal transition of its own')
        self.assertTrue(self.engine.daily_signal_cached_only)

    def test_source_io_failure_is_typed_and_never_delegates_or_changes_state(self):
        prior = self.engine.state
        self.source.history = Mock(side_effect=OSError('private database detail'))
        receipt = prepare_daily_deployment(self.bundle, self.command)
        self.assertEqual(receipt.code, 'daily_signal_source_unverified')
        self.assertFalse(receipt.accepted)
        self.facade.execute.assert_not_called()
        self.assertIs(self.engine.state, prior)
        self.assertFalse(self.engine.storage_failed)

    def test_deliberate_source_refusal_preserves_its_typed_code(self):
        self.source.history = Mock(side_effect=DomainError('daily_signal_basis_mismatch'))
        self.assertEqual(prepare_daily_deployment(self.bundle, self.command).code, 'daily_signal_basis_mismatch')
        self.facade.execute.assert_not_called()

    def test_internal_facade_programming_failure_is_not_disguised_as_source_failure(self):
        self.facade.execute.side_effect = RuntimeError('internal application defect')
        with self.assertRaises(RuntimeError):
            prepare_daily_deployment(self.bundle, self.command)

    def test_live_all_three_layers_refuse_before_reading_source(self):
        self.source.history = Mock(side_effect=AssertionError('LIVE deployment reached source'))
        for layer in ('command', 'launch', 'engine'):
            with self.subTest(layer=layer):
                command = replace(self.command, environment=Environment.LIVE) if layer == 'command' else self.command
                self.bundle.launch = SimpleNamespace(environment=Environment.LIVE if layer == 'launch' else SIM)
                self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE if layer == 'engine' else SIM)
                receipt = prepare_daily_deployment(self.bundle, command)
                self.assertEqual(receipt.code, 'production_orders_disabled')
                self.assertFalse(receipt.accepted)
        self.source.history.assert_not_called()

    def test_local_or_non_native_or_non_official_strategy_retains_existing_route(self):
        self.source.history = Mock(side_effect=AssertionError('unrelated deployment read source'))
        self.engine.daily_signal_cached_only = False
        self.assertIsNone(prepare_daily_deployment(self.bundle, self.command))
        self.engine.daily_signal_cached_only = True
        self.bundle.launch = SimpleNamespace(environment=Environment.LOCAL)
        self.assertIsNone(prepare_daily_deployment(self.bundle, self.command))
        self.bundle.launch = SimpleNamespace(environment=SIM)
        self.engine.state = replace(self.engine.state, strategies=(replace(self.record, parameters=replace(self.record.parameters, bar_interval='5m')),))
        self.assertIsNone(prepare_daily_deployment(self.bundle, self.command))
        self.source.history.assert_not_called()

    def test_ineligible_state_or_missing_evidence_keeps_original_risk_rejected_precedence(self):
        self.source.history = Mock(side_effect=AssertionError('ineligible deployment read source'))
        self.engine.deploy = MethodType(TradingEngine.deploy, self.engine)
        self.engine.latencies = []
        facade = LocalFacade(self.engine)
        for record in (replace(self.record, state='DRAFT'), replace(self.record, evidence_hash='')):
            with self.subTest(state=record.state, evidence=bool(record.evidence_hash)):
                self.engine.state = replace(self.engine.state, strategies=(record,))
                self.assertIsNone(prepare_daily_deployment(self.bundle, self.command))
                receipt = facade.execute(replace(self.command, expected_version=self.engine.state.version))
                self.assertEqual(receipt.code, 'risk_rejected')
        self.source.history.assert_not_called()

    def test_invalid_expected_version_is_refused_before_io(self):
        self.source.history = Mock(side_effect=AssertionError('bad command read source'))
        self.assertEqual(prepare_daily_deployment(self.bundle, replace(self.command, expected_version=True)).code, 'validation_failed')
        self.assertEqual(prepare_daily_deployment(self.bundle, replace(self.command, expected_version=100000)).code, 'state_conflict')
        self.source.history.assert_not_called()

    def test_missing_source_and_missing_research_basis_never_warm(self):
        self.engine.daily_signal_source = None
        with patch('quantlab.trading.runtime.daily_deployment.loads', wraps=loads) as decode:
            self.assertEqual(prepare_daily_deployment(self.bundle, self.command).code, 'daily_signal_source_unverified')
        decode.assert_not_called()
        self.engine.daily_signal_source = self.source
        self.engine.state = replace(self.engine.state, strategies=(replace(self.record, research_blob=''),))
        self.source.history = Mock(side_effect=AssertionError('missing research read source'))
        self.assertEqual(prepare_daily_deployment(self.bundle, self.command).code, 'daily_signal_source_unverified')
        self.source.history.assert_not_called()

    def test_legacy_research_without_official_basis_refuses_before_source(self):
        self.source.history = Mock(side_effect=AssertionError('legacy evidence read source'))
        row = self.case.history.raw_completed(self.case.calendar)[0]
        wrong_wire_type = LiveBar(
            self.record.form.instrument_id, row.opened_at, row.ended_at, row.ended_at.date(), 'DAY', row.open, row.open, row.close, row.close, row.volume
        )
        for basis in (None, wrong_wire_type):
            with self.subTest(basis=type(basis).__name__):
                blob = dumps(replace(self.case.result, daily_basis=basis))
                self.engine.state = replace(self.engine.state, strategies=(replace(self.record, research_blob=blob),))
                self.assertEqual(prepare_daily_deployment(self.bundle, self.command).code, 'daily_signal_source_unverified')
        self.source.history.assert_not_called()

    def test_engine_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'engine', object()))

    def test_source_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.engine, 'daily_signal_source', object()))

    def test_facade_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'facade', SimpleNamespace(engine=self.engine)))

    def test_facade_engine_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.facade, 'engine', object()))

    def test_owner_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'sinopac_connection', object()))

    def test_runtime_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'automatic_runtime', object()))

    def test_manual_context_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'manual_runtime', object()))

    def test_shared_session_swap_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.owner, 'shared', object()))

    def test_offset_change_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'version_offset', 8))

    def test_current_version_change_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.engine, 'state', replace(self.engine.state, version=self.engine.state.version + 1)))

    def test_configuration_change_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.engine, 'configuration', replace(self.engine.configuration, read_only=True)))

    def test_launch_change_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'launch', SimpleNamespace(environment=SIM, profile='changed')))

    def test_launch_environment_change_in_composition_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle.launch, 'environment', Environment.LIVE))

    def test_record_change_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.engine, 'state', replace(self.engine.state, strategies=(replace(self.record, evidence_hash='b' * 64),))))

    def test_calendar_change_during_warm_refuses(self):
        changed = replace(self.case.calendar, version='changed-calendar')
        self.rejects_after_change(lambda: setattr(self.engine, '_strategy_calendar', lambda *args: changed))

    def test_owner_stamp_change_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self, 'stamp', 'new-owner-stamp'))

    def test_shutdown_and_control_changes_during_warm_refuse(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'closing', True))

    def test_resources_closed_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'resources_closed', True))

    def test_control_failed_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'control_failed', True))

    def test_transition_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.bundle, 'transitioning', True))

    def test_engine_closed_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.engine, 'state', replace(self.engine.state, engine_closed=True)))

    def test_storage_failed_during_warm_refuses(self):
        self.rejects_after_change(lambda: setattr(self.engine, 'storage_failed', True))


class NativeDailyDeploymentTests(unittest.TestCase):
    def test_real_ipc_redeploy_after_revision_and_restart_preserves_public_version(self):
        fixture = native.ConnectedOfficialFixture(self)
        record = fixture.deploy()
        reference = f'{record.strategy_id}:{record.version}'
        disable = replace(fixture.case.command(UiAction.DISABLE_STRATEGY), target_id=reference)
        self.assertTrue(fixture.case.request(Operation.COMMAND, disable, account=fixture.stock_ref).receipt.accepted)
        before = fixture.case.state().version
        old_revision = fixture.bundle.kline_store.revision
        fixture.import_through(date(2025, 6, 11))
        self.assertGreater(fixture.bundle.kline_store.revision, old_revision)
        orders = fixture.placed()
        command = replace(fixture.case.command(UiAction.DEPLOY), target_id=reference)
        response = fixture.case.request(Operation.COMMAND, command, account=fixture.stock_ref)
        self.assertTrue(response.receipt.accepted, response.receipt)
        self.assertEqual(fixture.engine.strategy(reference).state, 'ACTIVE')
        self.assertGreater(response.state.version, before)
        self.assertEqual(response.state.version, fixture.engine.state.version + fixture.bundle.version_offset)
        self.assertGreaterEqual(fixture.bundle.high_water, response.state.version)
        self.assertTrue(fixture.engine.daily_signal_cached_only)
        self.assertEqual(fixture.placed(), orders)
        self.assertEqual(fixture.case.native.financial_queries, 0)
        launch = fixture.bundle.launch
        fixture.bundle.close()
        restored = build_runtime(launch, sinopac_clock=fixture.clock)
        self.addCleanup(restored.close)
        self.assertGreater(restored.snapshot().version, response.state.version)
        self.assertGreaterEqual(restored.high_water, response.state.version)


if __name__ == '__main__':
    unittest.main()
