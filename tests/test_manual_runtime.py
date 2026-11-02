"""Pure composition and observation failure boundaries; no Qt/process/SDK."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import UiAction, UiCommand, UiReceipt
from quantlab.trading.application.manual_contracts import ManualScope, ManualTradingView
from quantlab.trading.application.sinopac_contracts import SinopacConnectionView
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.manual_resources import ManualResourceState
from quantlab.trading.runtime.manual_trading import ManualRuntime
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.sinopac_calendar import built_in_calendar
from test_trading_adapters import instrument, MutableClock


class ManualRuntimePureTests(unittest.TestCase):
    def setUp(self):
        initialize()
        self.view = SinopacConnectionView(environment=Environment.BROKER_SIMULATION, generation='generation-a', revision=9, phase='CONNECTED')
        self.shared = SimpleNamespace(callback_errors=0)
        self.owner = SimpleNamespace(
            snapshot=lambda: self.view,
            selected=('future-alias',),
            query_ready=True,
            shared=self.shared,
            accounts=(SimpleNamespace(alias='future-alias', signed=True),),
            preferences=SimpleNamespace(check_selection=lambda selected: None),
        )
        self.bundle = SimpleNamespace(
            sinopac_connection=self.owner,
            closing=False,
            resources_closed=False,
            version_offset=20,
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=None,
        )
        self.runtime = ManualRuntime(self.bundle)
        self.scope = ManualScope('sinopac-simulation', 0, Environment.BROKER_SIMULATION, 'future-alias', 'generation-a', 9)
        self.runtime.stamp = ('generation-a', 9, ('future-alias',), self.shared)
        self.runtime.error = ''

    def test_native_cas_invalidated_by_selection_revision_and_relogin(self):
        self.runtime.validate_scope(self.scope)
        for change in ({'revision': 10}, {'generation': 'generation-b'}):
            original = self.view
            self.view = replace(self.view, **change)
            with self.assertRaises(DomainError) as raised:
                self.runtime.validate_scope(self.scope)
            self.assertEqual(raised.exception.code, 'state_conflict')
            self.view = original
        self.owner.selected = ('other-alias',)
        with self.assertRaises(DomainError):
            self.runtime.validate_scope(self.scope)

    def test_failed_refresh_blocks_new_commands_even_if_previous_observation_fresh(self):
        self.runtime.error = 'manual_account_observation_required'
        with self.assertRaises(DomainError) as raised:
            self.runtime.validate_scope(self.scope)
        self.assertEqual(raised.exception.code, 'manual_account_observation_required')

    def test_provider_resource_failure_is_sanitized_at_resource_boundary(self):
        def fail_provider(_alias):
            raise RuntimeError('private-native-resource-detail')

        self.owner.resources = fail_provider
        with self.assertRaises(DomainError) as raised:
            self.runtime._resources(('future-alias',))
        self.assertEqual(raised.exception.code, 'instrument_unresolved')
        self.assertNotIn('private-native-resource-detail', str(raised.exception))

    def test_snapshot_is_pure_and_preserves_last_admitted_scope(self):
        admitted = replace(self.scope, context_epoch=6)
        self.runtime.last_scopes['future-alias'] = admitted
        self.bundle.engine = SimpleNamespace(gateways={'future-alias': object()})
        self.runtime.service = SimpleNamespace(snapshot=lambda scope: ManualTradingView(scope))
        self.owner.resources = lambda _: self.fail('snapshot queried SDK resources')
        self.assertEqual(self.runtime.snapshot('future-alias').scope, admitted)
        self.view = replace(self.view, revision=10)
        self.assertEqual(self.runtime.snapshot('future-alias').scope.context_epoch, 0)
        self.assertEqual(admitted.connection_revision, 9)

    def test_live_rejected_before_service_and_disconnected_snapshot_not_actionable(self):
        self.runtime.service = SimpleNamespace(execute=lambda _: self.fail('LIVE reached service'))
        result = self.runtime.execute(UiCommand(UiAction.TEST_SIM_ORDER, 0, environment=Environment.LIVE))
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, 'production_orders_disabled')
        self.owner.selected = ()
        snapshot = self.runtime.snapshot('future-alias')
        self.assertIsNone(snapshot.scope)
        self.assertFalse(snapshot.can_submit)

    def test_runtime_preserves_service_replay_before_outer_book_version_guard(self):
        sent = []
        self.runtime.service = SimpleNamespace(execute=lambda command: sent.append(command) or UiReceipt(True, 'ok', '', 'durable-id'))
        command = UiCommand(
            UiAction.SUBMIT_MANUAL,
            2,
            environment=Environment.BROKER_SIMULATION,
            account_ref='future-alias',
            context_id='sinopac-simulation',
            context_epoch=0,
            connection_generation='generation-a',
            connection_revision=9,
        )
        self.assertTrue(self.runtime.execute(command).accepted)
        self.assertEqual(sent[0].expected_version, -18)

    def test_resource_facts_round_trip_preserves_contract_and_masked_market_only(self):
        binding = InstrumentBinding(instrument(Market.INDEX_FUTURE), 'TMFL6')
        value = ManualResourceState((binding,), (('future-alias', Market.INDEX_FUTURE),))
        self.assertEqual(loads(dumps(value)), value)
        self.assertNotIn('native', dumps(value))
        with self.assertRaises(DomainError):
            ManualResourceState((binding, binding), value.markets)
        for changes in ({'schema_version': True}, {'markets': (('future-alias', 'INDEX_FUTURE'),)}, {'markets': (('future-alias',),)}):
            with self.assertRaises(DomainError):
                replace(value, **changes)

    def test_connection_readiness_is_selected_book_evidence_without_new_cas_token(self):
        ready = ManualTradingView(self.scope, test_status='PASSED', can_submit=True)
        projected = self.runtime.connection_view(self.view, ready)
        self.assertEqual(projected.revision, self.view.revision)
        self.assertEqual(next(row.state for row in projected.readiness if row.code == 'simulation_orders'), 'READY')
        for blocked in (replace(ready, can_submit=False, reasons=('manual_stopped',)), ManualTradingView()):
            projection = self.runtime.connection_view(self.view, blocked)
            self.assertEqual(next(row.state for row in projection.readiness if row.code == 'simulation_orders'), 'BLOCKED')
        production = next(row for row in projected.readiness if row.code == 'production_orders')
        self.assertEqual((production.state, production.reason), ('BLOCKED', 'production_orders_disabled'))

    def test_trusted_market_clock_port_does_not_change_real_lease_clock_or_calendar(self):
        clock = MutableClock()
        calendar = built_in_calendar()
        self.assertEqual(calendar.session_at(clock.now(), allow_night=False).kind, 'DAY')
        with self.assertRaises(DomainError):
            calendar.session_at(datetime(2026, 11, 1, 1, tzinfo=timezone.utc), allow_night=False)
        with TemporaryDirectory(dir=Path.cwd()) as root:
            bundle = build_runtime(
                RuntimeLaunch(Path(root), Environment.BROKER_SIMULATION, account_ref='sinopac-pending', sinopac=True),
                sinopac_clock=clock,
                sinopac_factory=lambda _: self.fail('startup created SDK'),
            )
            try:
                self.assertIs(bundle.sinopac_connection.clock, clock)
                self.assertIsNone(bundle.engine)
                # If readiness leases used the old market date, a wall-clock
                # heartbeat would be fenced immediately. No timeout is widened.
                bundle.heartbeat()
                self.assertFalse(bundle.control_failed)
            finally:
                bundle.close()


if __name__ == '__main__':
    unittest.main()
