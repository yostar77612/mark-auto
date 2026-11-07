"""M3 engine/codec/IPC wiring with synthetic evidence only, never a broker login."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from quantlab.trading.application.auto_strategy_service import auto_strategy_views
from quantlab.trading.application.auto_strategy_views import BuildDialogOptions
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import AutoStrategyCommand, UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.state import AppState
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.promotion import PauseReason, RunState, Stage, StageState
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.auto_strategy import AutoStrategyRuntime
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.build import create_engine
from quantlab.trading.runtime.candidate_catalog import ResearchWorkspaceCandidateCatalog
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.protocol import Operation, Request, Response
from quantlab.trading.runtime.server import _dispatch
from tests.test_m3_promotion_service import built, observation
from tests.test_m3_candidate_intake import request as build_request


class M3IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='m3-integration-')
        self.root = Path(self.temp.name)
        self.engine = create_engine(self.root)
        self.facade = LocalFacade(self.engine)
        self.row = built(account_ref='local-futures')

    def tearDown(self):
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.temp.cleanup()

    def install(self, stage=Stage.BACKTEST, run=RunState.RUNNING, eligible=False):
        row = replace(self.row, state=StageState(stage, run, PauseReason.MANUAL if run is RunState.PAUSED else None), eligible=eligible)
        self.engine._persist('fixture_auto_projection', replace(self.engine.state, auto_strategies=(row,)))
        return row

    def command(self, action, *, confirmed=False, **changes):
        data = dict(
            action=action,
            expected_version=self.engine.state.version,
            account_ref='local-futures',
            environment=self.engine.configuration.environment,
            auto_strategy=AutoStrategyCommand(self.row.auto.strategy_id, self.row.auto.version, self.row.auto.frozen_hash, confirmed),
        )
        data.update(changes)
        return UiCommand(**data)

    def test_legacy_state_without_auto_fields_decodes_unchanged(self):
        document = json.loads(dumps(AppState()))
        document['fields'].pop('auto_strategies')
        document['fields'].pop('auto_promotion_evaluations')
        self.assertEqual(loads(json.dumps(document)), AppState())

    def test_record_build_is_engine_state_envelope_and_sequential(self):
        with self.engine.lock:
            self.engine.auto_service().record_built(self.row, now=self.engine.clock.now())
        self.assertEqual(self.engine.state.auto_strategies, (self.row,))
        for event in self.engine.journal.replay():
            state = loads(event.payload)
            self.assertIsInstance(state, AppState)
            self.assertEqual(state.version, event.sequence)

    def test_unrelated_engine_writes_do_not_desynchronize_new_service(self):
        with self.engine.lock:
            self.engine.auto_service().record_built(self.row, now=self.engine.clock.now())
            self.engine._persist('ordinary_event', self.engine.state)
            self.engine.auto_service().retire(self.row.auto.strategy_id, 1, now=self.engine.clock.now())
        self.assertEqual(self.engine.state.auto_strategies[0].state.run_state, RunState.RETIRED)

    def test_stale_service_sequence_fails_closed(self):
        service = self.engine.auto_service()
        self.engine._persist('ordinary_event', self.engine.state)
        with self.assertRaises(DomainError) as error:
            service.record_built(self.row, now=self.engine.clock.now())
        self.assertEqual(error.exception.code, 'state_conflict')
        self.assertFalse(self.engine.state.auto_strategies)

    def test_restart_pauses_running_auto_record_without_second_event_format(self):
        self.install(Stage.BROKER_SIM)
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.engine = create_engine(self.root)
        self.assertEqual(self.engine.state.auto_strategies[0].state.pause_reason, PauseReason.RESTART)
        self.assertTrue(self.engine.state.stopped)

    def test_failed_journal_append_does_not_publish_auto_projection(self):
        before = self.engine.state.auto_strategies
        self.engine.journal.append = Mock(side_effect=OSError('fixture'))
        with self.assertRaises(DomainError):
            self.engine.auto_service().record_built(self.row, now=self.engine.clock.now())
        self.assertEqual(self.engine.state.auto_strategies, before)
        self.assertTrue(self.engine.storage_failed)

    def test_expected_version_and_frozen_hash_conflicts(self):
        self.install(Stage.BROKER_SIM)
        for change in (dict(expected_version=-1), dict(auto_strategy=AutoStrategyCommand('auto-1', 1, 'wrong'))):
            result = self.facade.execute(self.command(UiAction.PAUSE_AUTO_STRATEGY, **change))
            self.assertEqual(result.code, 'state_conflict')
            self.assertEqual(self.engine.state.auto_strategies[0].state.run_state, RunState.RUNNING)

    def test_pause_uses_existing_state_writer(self):
        self.install(Stage.BROKER_SIM)
        receipt = self.facade.execute(self.command(UiAction.PAUSE_AUTO_STRATEGY))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.engine.state.auto_strategies[0].state.pause_reason, PauseReason.MANUAL)
        self.assertEqual(self.engine.state.events[-1], 'auto_paused')

    def test_resume_cannot_claim_fresh_checks_from_ui(self):
        self.install(Stage.BROKER_SIM, RunState.PAUSED)
        self.engine.auto_runtime = AutoStrategyRuntime(self.engine, ResearchWorkspaceCandidateCatalog(self.root))
        receipt = self.facade.execute(self.command(UiAction.RESUME_AUTO_STRATEGY))
        self.assertFalse(receipt.accepted)
        self.assertEqual(self.engine.state.auto_strategies[0].state.run_state, RunState.PAUSED)

    def test_retire_requires_confirmation(self):
        self.install()
        self.assertEqual(self.facade.execute(self.command(UiAction.RETIRE_AUTO_STRATEGY)).code, 'auto_confirmation_required')
        self.assertTrue(self.facade.execute(self.command(UiAction.RETIRE_AUTO_STRATEGY, confirmed=True)).accepted)
        self.assertEqual(self.engine.state.auto_strategies[0].state.run_state, RunState.RETIRED)

    def test_owner_approval_only_records_intent_and_never_enables_execution(self):
        self.install(Stage.BROKER_SIM, eligible=True)
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.BROKER_SIMULATION)
        self.assertEqual(self.facade.execute(self.command(UiAction.APPROVE_LIVE_INTENT)).code, 'auto_confirmation_required')
        gateway_methods = []
        for gateway in self.engine.gateways.values():
            for name in ('submit', 'cancel', 'replace', 'place_order', 'update_order', 'cancel_order'):
                method = Mock(side_effect=AssertionError('financial gateway called'))
                setattr(gateway, name, method)
                gateway_methods.append(method)
        receipt = self.facade.execute(self.command(UiAction.APPROVE_LIVE_INTENT, confirmed=True))
        self.assertTrue(receipt.accepted, receipt)
        row = self.engine.state.auto_strategies[0]
        self.assertEqual(row.state.stage, Stage.LIVE_APPROVED)
        self.assertFalse(row.eligible)
        self.assertEqual(row.live_approved_on, self.engine.state.trading_day)
        self.assertFalse(row.permits_new_entries)
        for method in gateway_methods:
            method.assert_not_called()

    def test_owner_lifecycle_never_calls_financial_gateway_in_any_environment(self):
        methods = []
        for gateway in self.engine.gateways.values():
            for name in ('submit', 'cancel', 'replace', 'place_order', 'update_order', 'cancel_order'):
                method = Mock(side_effect=AssertionError('financial gateway called'))
                setattr(gateway, name, method)
                methods.append(method)
        for environment in Environment:
            with self.subTest(environment=environment):
                self.engine.configuration = replace(self.engine.configuration, environment=environment)
                self.install(Stage.BROKER_SIM)
                self.assertTrue(self.facade.execute(self.command(UiAction.PAUSE_AUTO_STRATEGY)).accepted)
                self.assertFalse(self.facade.execute(self.command(UiAction.RESUME_AUTO_STRATEGY)).accepted)
                self.assertFalse(self.facade.execute(self.command(UiAction.APPROVE_LIVE_INTENT, confirmed=True)).accepted)
                self.assertTrue(self.facade.execute(self.command(UiAction.RETIRE_AUTO_STRATEGY, confirmed=True)).accepted)
        for method in methods:
            method.assert_not_called()

    def test_approval_refuses_local_live_and_ineligible(self):
        self.install(Stage.BROKER_SIM, eligible=True)
        for environment in (Environment.LOCAL, Environment.LIVE):
            self.engine.configuration = replace(self.engine.configuration, environment=environment)
            self.assertEqual(self.facade.execute(self.command(UiAction.APPROVE_LIVE_INTENT, confirmed=True)).code, 'auto_not_eligible')
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.BROKER_SIMULATION)
        self.install(Stage.BROKER_SIM, eligible=False)
        self.assertEqual(self.facade.execute(self.command(UiAction.APPROVE_LIVE_INTENT, confirmed=True)).code, 'auto_not_eligible')

    def test_views_roundtrip_without_accepting_live_available_from_wire(self):
        self.install()
        view = auto_strategy_views(self.engine.state)[0]
        initialize()
        self.assertEqual(loads(dumps(view)), view)
        self.assertEqual(loads(dumps(BuildDialogOptions())), BuildDialogOptions())
        body = json.loads(dumps(view))
        body['fields']['live_available'] = True
        with self.assertRaises(DomainError):
            loads(json.dumps(body))

    def test_default_catalog_is_unavailable_not_fixture_qualification(self):
        self.engine.auto_runtime = AutoStrategyRuntime(self.engine, ResearchWorkspaceCandidateCatalog(self.root))
        with self.assertRaises(DomainError) as error:
            self.facade.candidates()
        self.assertEqual(error.exception.code, 'candidate_unavailable')

    def test_promotion_evaluation_remains_idempotent_across_projection_refresh(self):
        self.install(Stage.BROKER_SIM)
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.BROKER_SIMULATION)
        row = replace(self.engine.state.auto_strategies[0], observation_started_on=self.engine.state.trading_day)
        self.engine._persist('fixture_epoch', replace(self.engine.state, auto_strategies=(row,)))
        day = self.engine.state.trading_day
        with self.engine.lock:
            first = self.engine.auto_service().evaluate_after_close('auto-1', 1, day, observation(), observation_started_on=day, now=self.engine.clock.now())
            version = self.engine.state.version
            second = self.engine.auto_service().evaluate_after_close('auto-1', 1, day, observation(), observation_started_on=day, now=self.engine.clock.now())
        self.assertEqual(first, second)
        self.assertEqual(self.engine.state.version, version)
        self.assertEqual(len(self.engine.state.auto_promotion_evaluations), 1)
        self.assertTrue(auto_strategy_views(self.engine.state)[0].progress.history_complete)

    def bundle(self):
        return RuntimeBundle(RuntimeLaunch(self.root), self.facade, (), self.engine)

    def request(self, operation, command=None):
        return Request('m3-request', Environment.LOCAL, 'local-futures', datetime.now(timezone.utc) + timedelta(seconds=10), operation, command)

    def test_auto_operation_roundtrip_dispatch_and_account_binding(self):
        self.install(Stage.BROKER_SIM)
        bundle = self.bundle()
        request = loads(dumps(self.request(Operation.AUTO_STRATEGY_COMMAND, self.command(UiAction.PAUSE_AUTO_STRATEGY))))
        response = _dispatch(bundle, request)
        self.assertTrue(response.receipt.accepted)
        self.assertIsInstance(loads(dumps(response)), Response)
        with self.assertRaises(DomainError) as error:
            _dispatch(
                bundle, self.request(Operation.AUTO_STRATEGY_COMMAND, self.command(UiAction.RETIRE_AUTO_STRATEGY, confirmed=True, account_ref='local-stock'))
            )
        self.assertEqual(error.exception.code, 'state_conflict')

    def test_authenticated_futures_snapshot_and_command_keep_selected_auto_rows(self):
        self.install(Stage.BROKER_SIM)
        bundle = self.bundle()
        self.assertEqual(self.engine.state.account_ref, 'local-stock')
        response = _dispatch(bundle, self.request(Operation.SNAPSHOT))
        self.assertEqual(tuple(row.account_ref for row in response.state.auto_strategies), ('local-futures',))
        # Preserve the legacy ordinary projection/account semantics; the context
        # client relabels the selected account, while M3 rows must not disappear.
        self.assertEqual(response.state.account_ref, 'local-stock')
        response = _dispatch(bundle, self.request(Operation.AUTO_STRATEGY_COMMAND, self.command(UiAction.PAUSE_AUTO_STRATEGY)))
        self.assertTrue(response.receipt.accepted)
        self.assertEqual(len(response.state.auto_strategies), 1)
        self.assertEqual(response.state.auto_strategies[0].run_state, RunState.PAUSED)
        stock_request = replace(self.request(Operation.SNAPSHOT), account_ref='local-stock')
        self.assertEqual(_dispatch(bundle, stock_request).state.auto_strategies, ())

    def test_auto_operation_rejects_wrong_action_and_missing_command(self):
        with self.assertRaises(DomainError):
            self.request(Operation.AUTO_STRATEGY_COMMAND)
        with self.assertRaises(DomainError):
            _dispatch(self.bundle(), self.request(Operation.BUILD_AUTO_STRATEGY, self.command(UiAction.PAUSE_AUTO_STRATEGY)))

    def test_build_command_roundtrip_is_reference_only_and_default_fails_without_write(self):
        self.engine.auto_runtime = AutoStrategyRuntime(self.engine, ResearchWorkspaceCandidateCatalog(self.root))
        request = replace(build_request(), account_ref='local-futures')
        command = self.command(UiAction.BUILD_AUTO_STRATEGY, auto_strategy=None, auto_build=request)
        self.assertEqual(loads(dumps(command)), command)
        self.assertNotIn('oos', dumps(command).lower())
        version = self.engine.state.version
        receipt = self.facade.execute(command)
        self.assertEqual(receipt.code, 'candidate_unavailable')
        self.assertEqual(self.engine.state.version, version)
        self.assertFalse(self.engine.state.auto_strategies)

    def test_build_payload_type_is_rejected_without_publishing(self):
        version = self.engine.state.version
        receipt = self.facade.execute(self.command(UiAction.BUILD_AUTO_STRATEGY, auto_build='untyped'))
        self.assertEqual(receipt.code, 'validation_failed')
        self.assertEqual(self.engine.state.version, version)

    def test_live_build_is_hard_disabled_before_catalog_or_gateway(self):
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE)
        runtime = Mock()
        self.engine.auto_runtime = runtime
        receipt = self.facade.execute(self.command(UiAction.BUILD_AUTO_STRATEGY, auto_build=replace(build_request(), account_ref='local-futures')))
        self.assertEqual(receipt.code, 'production_orders_disabled')
        runtime.build.assert_not_called()

    def test_same_day_resume_discards_old_epoch_progress(self):
        row = self.install(Stage.BROKER_SIM)
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.BROKER_SIMULATION)
        day = self.engine.state.trading_day
        now = self.engine.clock.now()
        row = replace(row, observation_started_on=day, observation_started_at=now - timedelta(days=10))
        self.engine._persist('fixture_epoch', replace(self.engine.state, auto_strategies=(row,)))
        with self.engine.lock:
            self.engine.auto_service().evaluate_after_close('auto-1', 1, day, observation(), observation_started_on=day, now=now)
            self.engine.auto_service().pause('auto-1', 1, now=now)
            self.engine.auto_service().resume('auto-1', 1, trade_date=day, reconciled=True, cause_cleared=True, now=now + timedelta(seconds=1))
        projected = self.engine.state.auto_strategies[0]
        self.assertEqual(projected.observation_started_at, now + timedelta(seconds=1))
        self.assertEqual(loads(dumps(projected)), projected)
        view = auto_strategy_views(self.engine.state)[0]
        self.assertFalse(view.progress.eligible)
        self.assertFalse(view.progress.history_complete)
        self.assertEqual(view.progress.checks, ())

    def test_candidate_operation_propagates_unavailable(self):
        with self.assertRaises(DomainError) as error:
            _dispatch(self.bundle(), self.request(Operation.LIST_CANDIDATES))
        self.assertEqual(error.exception.code, 'candidate_unavailable')


if __name__ == '__main__':
    unittest.main()
