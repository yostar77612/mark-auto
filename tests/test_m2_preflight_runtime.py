"""Current-owner preflight collection uses caches and actual diagnostic evidence."""

from dataclasses import fields, replace
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_trading_adapters import MutableClock, capability, instrument, plan
from test_live_order_guard import GuardJournal
from quantlab.trading.application.codec import loads
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.manual_book import ManualBook, ManualRequest
from quantlab.trading.application.manual_contracts import ManualPurpose, ManualScope
from quantlab.trading.application.preflight import PreflightFacts, build_preflight
from quantlab.trading.application.sinopac_contracts import SinopacAccountView, SinopacConnectionSettings, SinopacConnectionView
from quantlab.trading.application.state import AppState, LocalOrder
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, OrderStatus, PositionLot, Quote, Reservation, Side
from quantlab.trading.domain.risk import AccountRiskLimits
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder
from quantlab.trading.ports.manual import ManualAccountObservation, UnmappedBrokerOrder
from quantlab.trading.runtime.build import synthetic_calendar
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.preflight import engine_preflight_facts, sinopac_preflight_facts

D = Decimal


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self):
        self.clock = MutableClock()
        self.stock, self.future = instrument(), instrument(Market.INDEX_FUTURE)
        self.caps = {
            'stock': replace(capability(Environment.BROKER_SIMULATION), account_ref='stock', markets=frozenset((Market.STOCK,))),
            'futures': replace(capability(Environment.BROKER_SIMULATION), account_ref='futures', markets=frozenset((Market.INDEX_FUTURE,))),
        }
        self.gateways = {
            ref: SimpleNamespace(
                inspect=Mock(side_effect=lambda account_ref: self.caps[account_ref]),
                snapshot=Mock(side_effect=AssertionError('preflight must not query SDK funds')),
                refresh=Mock(side_effect=AssertionError('preflight must not refresh SDK')),
                events=Mock(side_effect=AssertionError('preflight must not query SDK events')),
            )
            for ref in self.caps
        }
        books = (
            ManualBook('manual-stock', 'stock', D('60000'), self.clock.now().date(), market=Market.STOCK),
            ManualBook('manual-futures', 'futures', D('40000'), self.clock.now().date(), market=Market.INDEX_FUTURE),
        )
        self.engine = SimpleNamespace(
            configuration=ExecutionConfiguration(Environment.BROKER_SIMULATION, 'stock', 'futures', False, True),
            gateways=self.gateways,
            clock=self.clock,
            calendar=synthetic_calendar(),
            catalog=Catalog((self.stock, self.future)),
            state=replace(
                AppState(), environment=Environment.BROKER_SIMULATION, trading_day=self.clock.now().date(), manual_books=books, reconciled=True, stopped=False
            ),
            quotes={self.stock.instrument_id: self.quote(self.stock)},
            manual_observations={ref: ManualAccountObservation(ref, Environment.BROKER_SIMULATION, (), (), (), self.clock.now()) for ref in self.caps},
        )
        self.view = SinopacConnectionView(
            settings=SinopacConnectionSettings(),
            revision=3,
            generation='current-generation',
            environment=Environment.BROKER_SIMULATION,
            phase='CONNECTED',
            accounts=(
                SinopacAccountView('stock', '***1', Market.STOCK, True, True),
                SinopacAccountView('futures', '***2', Market.INDEX_FUTURE, True, True),
            ),
        )
        self.shared = SimpleNamespace(callback_errors=0, activate_ca=Mock(side_effect=AssertionError('preflight never activates CA')))
        self.owner = SimpleNamespace(
            preferences=SimpleNamespace(check_selection=Mock()),
            snapshot=Mock(return_value=self.view),
            selected=('stock', 'futures'),
            shared=self.shared,
            query_ready=True,
        )
        self.manual = SimpleNamespace(stamp=(self.view.generation, self.view.revision, ('futures', 'stock'), self.shared), error='')
        self.bundle = SimpleNamespace(
            sinopac_connection=self.owner,
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=self.engine,
            manual_runtime=self.manual,
            closing=False,
            resources_closed=False,
        )
        self.add_diagnostic()

    def quote(self, spec, **changes):
        value = Quote(spec.instrument_id, D('10'), D('10'), D('10'), self.clock.now(), self.clock.now(), self.clock.now().date(), source='SHIOAJI')
        return replace(value, **changes)

    def add_diagnostic(self, **request_changes):
        intent = replace(plan(self.future, environment=Environment.BROKER_SIMULATION), account_ref='futures', strategy_id='manual-futures')
        reservation = Reservation('diagnostic', 'futures', self.future.instrument_id, self.future.underlying, D('0'), D('0'), 1, OrderStatus.CANCELED)
        order = LocalOrder(
            'diagnostic',
            'diagnostic',
            'diagnostic-hash',
            intent,
            HoldingPolicy(HoldingKind.CUSTOM, 0, 0),
            reservation,
            OrderStatus.CANCELED,
            broker_ref='actual-sdk-reference',
        )
        scope = ManualScope('sinopac-simulation', 0, Environment.BROKER_SIMULATION, 'futures', self.view.generation, self.view.revision)
        request = ManualRequest(
            scope,
            'diagnostic',
            'SUBMIT',
            'diagnostic-hash',
            ManualPurpose.DIAGNOSTIC_TMF,
            intent,
            order.policy,
            order_id=order.order_id,
            status='CANCELED',
            outcome_known=True,
        )
        request = replace(request, **request_changes)
        self.engine.state = replace(self.engine.state, orders=(order,), manual_requests=(request,))

    def set_view(self, **changes):
        self.view = replace(self.view, **changes)
        self.owner.snapshot.return_value = self.view

    def no_queries_or_ca(self):
        for gateway in self.gateways.values():
            gateway.snapshot.assert_not_called()
            gateway.refresh.assert_not_called()
            gateway.events.assert_not_called()
        self.shared.activate_ca.assert_not_called()

    def facts(self, account_ref='stock'):
        return sinopac_preflight_facts(self.bundle, account_ref)

    def test_ready_simulation_requires_actual_proof_and_uses_only_cached_facts(self):
        facts = self.facts()
        self.assertEqual(
            (facts.connected, facts.account_ready, facts.permission_ready, facts.ca_ready, facts.realtime, facts.service_open, facts.reconciled),
            (True, True, True, None, True, True, True),
        )
        self.assertFalse(build_preflight('stock', self.engine.state.trading_day, self.clock.now(), Environment.BROKER_SIMULATION, facts).blocked_today)
        self.no_queries_or_ca()

    def test_signed_login_and_attempt_capability_do_not_prove_key_permission(self):
        self.engine.state = replace(self.engine.state, manual_requests=())
        self.caps['stock'] = replace(self.caps['stock'], source='APP_CONFIRMED_SIM_MANUAL_ATTEMPT_KEY_PERMISSION_UNVERIFIED', can_trade=True)
        self.assertIsNone(self.facts().permission_ready)
        self.no_queries_or_ca()

    def test_previous_sdk_generation_diagnostic_cannot_prove_current_permission(self):
        request = self.engine.state.manual_requests[0]
        request = replace(request, scope=replace(request.scope, connection_generation='old-generation'))
        self.engine.state = replace(self.engine.state, manual_requests=(request,))
        self.assertIsNone(self.facts().permission_ready)

    def test_diagnostic_unknown_result_or_non_diagnostic_purpose_does_not_prove_permission(self):
        original = self.engine.state.manual_requests[0]
        for change in ({'outcome_known': False}, {'status': 'UNKNOWN'}, {'purpose': ManualPurpose.MANUAL}, {'operation': 'PREVIEW'}):
            with self.subTest(change=change):
                self.engine.state = replace(self.engine.state, manual_requests=(replace(original, **change),))
                self.assertIsNone(self.facts().permission_ready)

    def test_diagnostic_needs_real_unfilled_canceled_sdk_order(self):
        original = self.engine.state.orders[0]
        for change in ({'broker_ref': ''}, {'status': OrderStatus.UNKNOWN}, {'filled': 1}):
            with self.subTest(change=change):
                self.engine.state = replace(self.engine.state, orders=(replace(original, **change),))
                self.assertIsNone(self.facts().permission_ready)

    def test_disconnected_phase_is_not_current_connection(self):
        self.set_view(phase='DISCONNECTED')
        facts = self.facts()
        self.assertFalse(facts.connected)
        self.assertFalse(facts.account_ready)
        self.assertIsNone(facts.permission_ready)
        self.assertFalse(facts.realtime)
        self.assertFalse(facts.service_open)
        self.assertFalse(facts.reconciled)

    def test_query_not_ready_is_not_current_connection(self):
        self.owner.query_ready = False
        self.assertFalse(self.facts().connected)

    def test_missing_shared_owner_is_not_current_connection(self):
        self.owner.shared = None
        self.assertFalse(self.facts().connected)

    def test_callback_error_blocks_connection(self):
        self.shared.callback_errors = 1
        self.assertFalse(self.facts().connected)

    def test_closing_or_closed_resources_block_connection(self):
        for key in ('closing', 'resources_closed'):
            with self.subTest(key=key):
                setattr(self.bundle, key, True)
                self.assertFalse(self.facts().connected)
                setattr(self.bundle, key, False)

    def test_owner_environment_must_match_launched_environment(self):
        self.set_view(environment=Environment.LIVE)
        self.assertFalse(self.facts().connected)

    def test_unselected_account_cannot_pass_account_or_permission(self):
        self.owner.selected = ('futures',)
        facts = self.facts()
        self.assertFalse(facts.account_ready)
        self.assertFalse(facts.permission_ready)

    def test_another_selected_account_signature_cannot_authorize_target_account(self):
        stock, futures = self.view.accounts
        self.set_view(accounts=(futures, replace(stock, signed=False)))
        facts = self.facts()
        self.assertFalse(facts.account_ready)
        self.assertFalse(facts.permission_ready)

    def test_unsigned_or_unknown_signature_cannot_pass_account_or_permission(self):
        original = self.view.accounts
        for signed in (False, None):
            with self.subTest(signed=signed):
                self.set_view(accounts=(replace(original[0], signed=signed), original[1]))
                facts = self.facts()
                self.assertIs(facts.account_ready, signed)
                self.assertIs(facts.permission_ready, False if signed is False else None)

    def test_confirmed_virtual_book_is_required_for_account_capacity(self):
        self.engine.state = replace(self.engine.state, manual_books=())
        self.assertFalse(self.facts().account_ready)

    def test_other_account_book_does_not_supply_target_allocation_confirmation(self):
        self.engine.state = replace(self.engine.state, manual_books=(self.engine.state.manual_books[1],))
        self.assertFalse(self.facts().account_ready)

    def test_broker_financial_label_cannot_substitute_for_confirmed_virtual_book(self):
        stock, future = self.engine.state.manual_books
        self.engine.state = replace(self.engine.state, manual_books=(replace(stock, source='BROKER_FINANCES'), future))
        self.assertFalse(self.facts().account_ready)

    def test_expired_cached_account_capability_is_not_current_account_evidence(self):
        self.caps['stock'] = replace(self.caps['stock'], checked_at=self.clock.now() - timedelta(minutes=1), expires_at=self.clock.now())
        facts = self.facts()
        self.assertFalse(facts.account_ready)
        self.assertIsNone(facts.permission_ready)

    def test_cached_capability_account_and_environment_must_match_target(self):
        original = self.caps['stock']
        for change in ({'account_ref': 'futures'}, {'environment': Environment.LIVE}):
            with self.subTest(change=change):
                self.caps['stock'] = replace(original, **change)
                self.assertFalse(self.facts().account_ready)

    def test_future_or_stale_source_time_blocks_realtime_market(self):
        for offset in (-11, 1):
            with self.subTest(offset=offset):
                source = self.clock.now() + timedelta(seconds=offset)
                self.engine.quotes[self.stock.instrument_id] = self.quote(self.stock, source_at=source, received_at=max(source, self.clock.now()))
                self.assertFalse(self.facts().realtime)

    def test_future_receive_time_blocks_realtime_market(self):
        self.engine.quotes[self.stock.instrument_id] = self.quote(self.stock, received_at=self.clock.now() + timedelta(seconds=1))
        self.assertFalse(self.facts().realtime)

    def test_synthetic_or_unverified_quote_cannot_pass_unified_realtime_check(self):
        for change in ({'source': 'LOCAL_SIMULATED'}, {'quality': 'UNKNOWN'}):
            with self.subTest(change=change):
                self.engine.quotes[self.stock.instrument_id] = self.quote(self.stock, **change)
                self.assertFalse(self.facts().realtime)

    def test_irrelevant_future_catalog_quotes_are_not_all_required(self):
        futures = tuple(
            replace(
                self.future,
                instrument_id=f'TMF:{202701 + index}',
                delivery_month=str(202701 + index),
                expiry=self.future.expiry.replace(year=2027, month=1 + index),
            )
            for index in range(6)
        )
        self.engine.catalog = Catalog((self.stock, *futures))
        self.assertTrue(self.facts().realtime)
        self.engine.quotes = {futures[0].instrument_id: self.quote(futures[0])}
        self.assertTrue(self.facts('futures').realtime)

    def test_created_strategy_and_held_position_quotes_are_relevant(self):
        second = replace(self.stock, instrument_id='TWSE:2330', underlying='2330')
        self.engine.catalog = Catalog((self.stock, second, self.future))
        form = StrategyForm(
            'created', Market.STOCK, HoldingKind.SWING, 2, 10, Side.BUY, second.instrument_id, 'stock', Environment.BROKER_SIMULATION, D('20000'), D('.02')
        )
        self.engine.state = replace(self.engine.state, strategies=(SimpleNamespace(form=form, state='DRAFT', parameters=None),))
        self.assertFalse(self.facts().realtime)
        self.engine.quotes[second.instrument_id] = self.quote(second)
        self.engine.quotes.pop(self.stock.instrument_id)
        self.assertTrue(self.facts().realtime)
        lot = PositionLot('held', 'stock', self.stock.instrument_id, 'retired', 1, HoldingPolicy(), 1000, D('10'), self.clock.now().date(), 1000)
        self.engine.state = replace(self.engine.state, positions=(lot,))
        self.assertFalse(self.facts().realtime)

    def test_service_requires_verified_day_session(self):
        self.clock.value += timedelta(hours=8)
        self.assertFalse(self.facts().service_open)

    def test_night_session_does_not_pass_service_check(self):
        now = self.clock.now()
        self.engine.calendar = TradingCalendar(
            'night', 'night-v1', 'EXPLICIT_FIXTURE', (TradingSession(now.date(), now - timedelta(minutes=5), now + timedelta(hours=1), 'NIGHT'),)
        )
        self.assertFalse(self.facts().service_open)

    def test_current_query_error_blocks_service(self):
        self.manual.error = 'simulation_service_closed'
        self.assertFalse(self.facts().service_open)

    def test_connection_service_error_blocks_service(self):
        self.set_view(error_code='simulation_service_closed')
        self.assertFalse(self.facts().service_open)

    def test_reconciliation_needs_current_manual_owner_stamp(self):
        self.manual.stamp = ('previous-generation', self.view.revision, ('futures', 'stock'), self.shared)
        self.assertFalse(self.facts().reconciled)

    def test_reconciliation_cannot_use_cache_without_manual_owner(self):
        self.bundle.manual_runtime = None
        self.assertFalse(self.facts().reconciled)

    def test_missing_or_extra_configured_account_cache_is_not_complete(self):
        self.engine.manual_observations.pop('futures')
        self.assertFalse(self.facts().reconciled)
        self.engine.manual_observations['other'] = ManualAccountObservation('other', Environment.BROKER_SIMULATION, (), (), (), self.clock.now())
        self.assertFalse(self.facts().reconciled)

    def test_stale_or_future_other_account_observation_blocks_reconciliation(self):
        original = self.engine.manual_observations['futures']
        for offset in (-31, 1):
            with self.subTest(offset=offset):
                self.engine.manual_observations['futures'] = replace(original, as_of=self.clock.now() + timedelta(seconds=offset))
                self.assertFalse(self.facts().reconciled)

    def test_other_account_observation_identity_environment_and_type_are_checked(self):
        original = self.engine.manual_observations['futures']
        for row in (
            self.engine.manual_observations['stock'],
            replace(original, environment=Environment.LIVE),
            SimpleNamespace(account_ref='futures', environment=Environment.BROKER_SIMULATION, as_of=self.clock.now(), unmapped=(), orders=()),
        ):
            with self.subTest(row=row):
                self.engine.manual_observations['futures'] = row
                self.assertFalse(self.facts().reconciled)

    def test_unmapped_remote_order_blocks_reconciliation(self):
        self.engine.manual_observations['futures'] = replace(self.engine.manual_observations['futures'], unmapped=(UnmappedBrokerOrder('external'),))
        self.assertFalse(self.facts().reconciled)

    def test_uncertain_remote_or_local_order_outcome_blocks_reconciliation(self):
        original_order = self.engine.state.orders[0]
        original_remote = self.engine.manual_observations['futures']
        for status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING):
            with self.subTest(status=status, source='local'):
                self.engine.state = replace(self.engine.state, orders=(replace(original_order, status=status),))
                self.assertFalse(self.facts().reconciled)
            with self.subTest(status=status, source='remote'):
                self.engine.state = replace(self.engine.state, orders=(original_order,))
                remote = BrokerOrder('remote', original_order.plan, 0, D('0'), status, 'sdk-ref', self.clock.now())
                self.engine.manual_observations['futures'] = replace(original_remote, orders=(remote,))
                self.assertFalse(self.facts().reconciled)
            self.engine.manual_observations['futures'] = original_remote

    def test_reconciliation_state_and_differences_are_authoritative(self):
        self.engine.state = replace(self.engine.state, reconciled=False)
        self.assertFalse(self.facts().reconciled)
        self.engine.state = replace(self.engine.state, reconciled=True, reconciliation=(object(),))
        self.assertFalse(self.facts().reconciled)

    def test_sim_ca_is_not_activated_even_if_ready_or_failed_state_is_visible(self):
        for status in ('READY', 'FAILED', 'UNKNOWN', 'NOT_CONFIGURED'):
            with self.subTest(status=status):
                self.set_view(certificate_status=status)
                self.assertIsNone(self.facts().ca_ready)
        self.no_queries_or_ca()

    def test_live_ca_uses_only_existing_ready_certificate_view(self):
        self.bundle.launch.environment = Environment.LIVE
        self.set_view(environment=Environment.LIVE, certificate_status='READY')
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE)
        self.caps['stock'] = replace(self.caps['stock'], environment=Environment.LIVE)
        self.assertTrue(self.facts().ca_ready)
        self.set_view(certificate_status='NOT_CONFIGURED')
        self.assertFalse(self.facts().ca_ready)
        self.set_view(certificate_status='UNKNOWN')
        self.assertIsNone(self.facts().ca_ready)
        self.no_queries_or_ca()

    def test_owner_stamp_change_during_collection_is_rejected(self):
        original = self.view
        for change in ({'generation': 'new-generation'}, {'revision': original.revision + 1}, {'environment': Environment.LIVE}):
            with self.subTest(change=change):
                self.owner.snapshot.side_effect = (original, replace(original, **change))
                with self.assertRaises(DomainError) as rejected:
                    self.facts()
                self.assertEqual(rejected.exception.code, 'state_conflict')
        self.owner.snapshot.side_effect = None

    def test_selection_or_shared_owner_change_during_collection_is_rejected(self):
        original_shared, original_selected = self.owner.shared, self.owner.selected
        for attribute, value in (('shared', SimpleNamespace(callback_errors=0)), ('selected', ('stock',))):
            with self.subTest(attribute=attribute):
                calls = []

                def snapshot():
                    calls.append(1)
                    if len(calls) == 2:
                        setattr(self.owner, attribute, value)
                    return self.view

                self.owner.snapshot.side_effect = snapshot
                with self.assertRaises(DomainError):
                    self.facts()
                self.owner.shared, self.owner.selected = original_shared, original_selected
        self.owner.snapshot.side_effect = None

    def test_engine_or_connection_replacement_during_collection_is_rejected(self):
        original_engine, original_owner = self.bundle.engine, self.bundle.sinopac_connection
        for attribute in ('engine', 'sinopac_connection'):
            with self.subTest(attribute=attribute):
                calls = []

                def snapshot():
                    calls.append(1)
                    if len(calls) == 2:
                        setattr(self.bundle, attribute, object())
                    return self.view

                self.owner.snapshot.side_effect = snapshot
                with self.assertRaises(DomainError):
                    self.facts()
                self.bundle.engine, self.bundle.sinopac_connection = original_engine, original_owner
        self.owner.snapshot.side_effect = None

    def test_without_materialized_engine_facts_stay_unknown_or_blocked(self):
        self.bundle.engine = None
        facts = self.facts()
        self.assertFalse(facts.account_ready)
        self.assertIsNone(facts.permission_ready)
        self.assertIsNone(facts.realtime)
        self.assertFalse(facts.reconciled)
        self.no_queries_or_ca()

    def test_client_command_cannot_supply_preflight_facts(self):
        self.assertNotIn('preflight_facts', {field.name for field in fields(UiCommand)})

    def test_generic_local_collector_uses_cached_capabilities_without_ca_activation(self):
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LOCAL)
        self.caps['stock'] = replace(self.caps['stock'], environment=Environment.LOCAL)
        self.engine.quotes[self.stock.instrument_id] = self.quote(self.stock, source='LOCAL_SIMULATED')
        facts = engine_preflight_facts(self.engine, 'stock')
        self.assertTrue(facts.connected)
        self.assertTrue(facts.permission_ready)
        self.assertTrue(facts.realtime)
        self.assertIsNone(facts.ca_ready)
        self.no_queries_or_ca()


class PreflightDispatchTests(unittest.TestCase):
    def setUp(self):
        self.journal, clock = GuardJournal(), MutableClock()
        self.gateway = SimpleNamespace(
            inspect=Mock(return_value=replace(capability(Environment.BROKER_SIMULATION), account_ref='stock')),
            snapshot=Mock(side_effect=AssertionError('dispatcher must not query SDK funds')),
            refresh=Mock(side_effect=AssertionError('dispatcher must not refresh SDK')),
            events=Mock(side_effect=AssertionError('dispatcher must not query SDK events')),
        )
        self.engine = TradingEngine(
            self.journal,
            clock,
            synthetic_calendar(),
            Catalog((instrument(),)),
            {'stock': self.gateway},
            configuration=ExecutionConfiguration(Environment.BROKER_SIMULATION, 'stock', '', False, True),
            ownership_clock=clock.now,
            fees=FeeSchedule(),
        )
        self.manual = SimpleNamespace(handles=Mock(return_value=False), execute=Mock(side_effect=AssertionError('preflight is not a manual request')))
        self.owner_view = SinopacConnectionView(environment=Environment.BROKER_SIMULATION, generation='dispatcher-generation', revision=3, phase='CONNECTED')
        self.owner = SimpleNamespace(
            preferences=SimpleNamespace(check_selection=Mock()),
            lock=RLock(),
            snapshot=Mock(return_value=self.owner_view),
            selected=('stock',),
            shared=object(),
        )
        self.bundle = SimpleNamespace(
            lock=RLock(),
            engine=self.engine,
            facade=LocalFacade(self.engine),
            version_offset=7,
            sinopac_connection=self.owner,
            manual_runtime=self.manual,
            automatic_runtime=None,
            closing=False,
            closed=False,
            control_failed=False,
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            resources_closed=False,
        )
        self.passed = PreflightFacts(True, True, True, None, True, True, True)
        self.before = len(self.journal.events)

    def command(self, **changes):
        return replace(UiCommand(UiAction.CHECK_PREFLIGHT, self.engine.state.version + self.bundle.version_offset, account_ref='stock'), **changes)

    def execute(self, command=None, *, side_effect=None):
        with patch('quantlab.trading.runtime.preflight.sinopac_preflight_facts', return_value=self.passed, side_effect=side_effect) as provider:
            result = RuntimeBundle.execute(self.bundle, command or self.command())
        return result, provider

    def assert_no_record(self):
        self.assertEqual(len(self.journal.events), self.before)
        self.assertEqual(self.engine.state.preflight, ())

    def test_host_intercepts_and_journals_trusted_facts_with_public_version_offset(self):
        local_version, offset = self.engine.state.version, self.bundle.version_offset
        receipt, provider = self.execute()
        self.assertTrue(receipt.accepted, receipt)
        provider.assert_called_once_with(self.bundle, 'stock')
        self.assertEqual(self.engine.state.version, local_version + 1)
        self.assertEqual(self.bundle.version_offset, offset)
        self.assertEqual(len(self.journal.events), self.before + 1)
        stored = loads(self.journal.events[-1].payload)
        self.assertEqual(stored.preflight, self.engine.state.preflight)
        self.assertEqual(stored.preflight[0].account_ref, 'stock')
        self.assertFalse(stored.preflight[0].blocked_today)
        self.assertTrue(stored.stopped)
        self.manual.execute.assert_not_called()
        self.gateway.snapshot.assert_not_called()
        self.gateway.refresh.assert_not_called()
        self.gateway.events.assert_not_called()

    def test_host_empty_reference_uses_current_account_without_client_fact_input(self):
        receipt, provider = self.execute(self.command(account_ref=''))
        self.assertTrue(receipt.accepted, receipt)
        provider.assert_called_once_with(self.bundle, self.engine.state.account_ref)

    def test_host_requires_exact_integer_version_even_when_float_equals_public_version(self):
        public = self.engine.state.version + self.bundle.version_offset
        for value in (True, float(public), str(public)):
            with self.subTest(value=value):
                receipt, provider = self.execute(self.command(expected_version=value))
                self.assertEqual((receipt.accepted, receipt.code), (False, 'validation_failed'))
                provider.assert_not_called()
                self.assert_no_record()

    def test_host_requires_original_account_reference_to_be_a_string(self):
        for value in (0, False, 123):
            with self.subTest(value=value):
                receipt, provider = self.execute(self.command(account_ref=value))
                self.assertEqual((receipt.accepted, receipt.code), (False, 'validation_failed'))
                provider.assert_not_called()
                self.assert_no_record()

    def test_host_closing_refuses_collection(self):
        self.bundle.closing = True
        receipt, provider = self.execute()
        self.assertEqual((receipt.accepted, receipt.code), (False, 'capability_missing'))
        provider.assert_not_called()
        self.assert_no_record()

    def test_host_closed_refuses_collection(self):
        self.bundle.closed = True
        receipt, provider = self.execute()
        self.assertEqual((receipt.accepted, receipt.code), (False, 'capability_missing'))
        provider.assert_not_called()
        self.assert_no_record()

    def test_host_control_failure_refuses_collection(self):
        self.bundle.control_failed = True
        receipt, provider = self.execute()
        self.assertEqual((receipt.accepted, receipt.code), (False, 'capability_missing'))
        provider.assert_not_called()
        self.assert_no_record()

    def test_host_without_engine_refuses_collection(self):
        self.bundle.engine = None
        receipt, provider = self.execute()
        self.assertEqual((receipt.accepted, receipt.code), (False, 'capability_missing'))
        provider.assert_not_called()
        self.assert_no_record()

    def test_host_owner_removed_before_initial_lock_prevents_collection(self):
        @contextmanager
        def remove_owner_on_lock():
            with RLock():
                self.bundle.sinopac_connection = None
                yield

        self.bundle.lock = remove_owner_on_lock()
        receipt, provider = self.execute()
        self.assertEqual((receipt.accepted, receipt.code), (False, 'capability_missing'))
        provider.assert_not_called()
        self.assert_no_record()

    def test_host_provider_domain_error_is_mapped_without_record_or_raw_detail(self):
        receipt, provider = self.execute(side_effect=DomainError('preflight_market', 'private provider detail'))
        self.assertEqual((receipt.accepted, receipt.code), (False, 'preflight_market'))
        self.assertIn(ERROR_TABLE['preflight_market'].explanation, receipt.message)
        self.assertNotIn('private provider detail', receipt.message)
        provider.assert_called_once()
        self.assert_no_record()

    def test_host_engine_replacement_during_collection_prevents_record(self):
        def collect(bundle, reference):
            bundle.engine = SimpleNamespace(state=self.engine.state)
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_engine_version_change_during_collection_prevents_preflight_record(self):
        def collect(bundle, reference):
            self.engine._persist('concurrent_engine_event', self.engine.state)
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assertEqual(len(self.journal.events), self.before + 1)
        self.assertEqual(self.engine.state.events[-1], 'concurrent_engine_event')
        self.assertEqual(self.engine.state.preflight, ())

    def test_host_public_version_offset_change_during_collection_prevents_record(self):
        def collect(bundle, reference):
            bundle.version_offset += 1
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_closing_during_collection_prevents_record(self):
        def collect(bundle, reference):
            bundle.closing = True
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_control_failure_during_collection_prevents_record(self):
        def collect(bundle, reference):
            bundle.control_failed = True
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_closed_during_collection_prevents_record(self):
        def collect(bundle, reference):
            bundle.closed = True
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_owner_stamp_members_changed_after_collection_prevent_record(self):
        original = self.owner_view
        for change in ({'environment': Environment.LIVE}, {'generation': 'new-generation'}, {'revision': original.revision + 1}):
            with self.subTest(change=change):

                def collect(bundle, reference):
                    self.owner.snapshot.return_value = replace(original, **change)
                    return self.passed

                receipt, _ = self.execute(side_effect=collect)
                self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
                self.assert_no_record()
                self.owner.snapshot.return_value = original

    def test_host_owner_selection_changed_after_collection_prevents_record(self):
        def collect(bundle, reference):
            self.owner.selected = ()
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_shared_session_changed_after_collection_prevents_record(self):
        def collect(bundle, reference):
            self.owner.shared = object()
            return self.passed

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()

    def test_host_owner_lock_covers_stamp_reads_and_journal_commit(self):
        original_append = self.journal.append

        def snapshot():
            self.assertTrue(self.owner.lock._is_owned())
            return self.owner_view

        def append(*args, **kwargs):
            self.assertTrue(self.owner.lock._is_owned())
            return original_append(*args, **kwargs)

        self.owner.snapshot.side_effect = snapshot
        self.journal.append = Mock(side_effect=append)
        receipt, _ = self.execute()
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.owner.snapshot.call_count, 2)
        self.journal.append.assert_called_once()

    def actual_provider_ready(self):
        fixture = RuntimePreflightTests()
        fixture.setUp()
        self.engine.gateways, self.engine.catalog = fixture.gateways, fixture.engine.catalog
        self.engine.configuration = fixture.engine.configuration
        self.engine.quotes, self.engine.manual_observations = fixture.engine.quotes, fixture.engine.manual_observations
        self.engine._persist('ready_actual_provider_fixture', replace(fixture.engine.state, account_ref='stock'))
        fixture.owner.lock = RLock()
        fixture.manual.handles = Mock(return_value=False)
        fixture.manual.execute = Mock(side_effect=AssertionError('preflight is not a manual request'))
        self.owner, self.owner_view = fixture.owner, fixture.view
        self.bundle.sinopac_connection, self.bundle.manual_runtime = self.owner, fixture.manual
        self.before = len(self.journal.events)
        return fixture

    def test_host_rejects_disconnect_revision_after_real_collector_returned_pass(self):
        fixture = self.actual_provider_ready()

        def collect(bundle, reference):
            facts = sinopac_preflight_facts(bundle, reference)
            self.assertTrue(facts.connected and facts.account_ready and facts.permission_ready and facts.realtime and facts.service_open and facts.reconciled)
            self.owner.snapshot.return_value = replace(fixture.view, phase='DISCONNECTING', revision=fixture.view.revision + 1)
            return facts

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()
        fixture.no_queries_or_ca()

    def test_host_rejects_connection_replacement_after_real_collector_returned_pass(self):
        fixture = self.actual_provider_ready()

        def collect(bundle, reference):
            facts = sinopac_preflight_facts(bundle, reference)
            self.assertTrue(facts.connected and facts.account_ready and facts.permission_ready and facts.reconciled)
            bundle.sinopac_connection = SimpleNamespace(
                lock=RLock(), snapshot=Mock(return_value=fixture.view), selected=self.owner.selected, shared=self.owner.shared
            )
            return facts

        receipt, _ = self.execute(side_effect=collect)
        self.assertEqual((receipt.accepted, receipt.code), (False, 'state_conflict'))
        self.assert_no_record()
        fixture.no_queries_or_ca()

    def test_manual_no_admission_deny_only_envelope_cannot_bypass_preflight_host_boundary(self):
        for value, code in ((True, 'state_conflict'), (1, 'validation_failed')):
            with self.subTest(value=value):
                receipt, provider = self.execute(self.command(manual_no_admission=value))
                self.assertEqual((receipt.accepted, receipt.code), (False, code))
                provider.assert_not_called()
                self.assert_no_record()
        self.manual.execute.assert_not_called()

    def test_local_facade_rejects_invalid_original_reference_before_defaulting(self):
        facade = LocalFacade(self.engine)
        for value in (0, False, 123):
            with self.subTest(value=value):
                with patch('quantlab.trading.application.preflight.engine_preflight_facts', return_value=self.passed) as provider:
                    receipt = facade.execute(UiCommand(UiAction.CHECK_PREFLIGHT, self.engine.state.version, account_ref=value))
                self.assertEqual((receipt.accepted, receipt.code), (False, 'validation_failed'))
                provider.assert_not_called()
                self.assert_no_record()

    def test_local_risk_settings_reject_invalid_original_reference_before_falsy_default(self):
        facade = LocalFacade(self.engine)
        for value in (0, False, 123):
            with self.subTest(value=value):
                receipt = facade.execute(
                    UiCommand(UiAction.SAVE_ACCOUNT_RISK, self.engine.state.version, account_ref=value, account_risk=AccountRiskLimits('stock'))
                )
                self.assertEqual((receipt.accepted, receipt.code), (False, 'validation_failed'))
                self.assertEqual(self.engine.state.account_risk_limits, ())
                self.assert_no_record()


if __name__ == '__main__':
    unittest.main()
