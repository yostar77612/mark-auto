"""Automatic runtime cache/queue ownership; fake ports never perform native queries."""

from dataclasses import replace
from collections import deque
from datetime import timedelta
from decimal import Decimal
from threading import Event, Lock, RLock, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_trading_adapters import MutableClock, instrument
from test_trading_sdk_facade import QuoteType, QuoteVersion
import test_m2_preflight_runtime as preflight_fixtures
import test_manual_runtime_integration as native_fixtures
import quantlab.trading.application as application_package
from quantlab.trading.application.automatic_state import AutomaticState, pause
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.preflight import PreflightFacts
from quantlab.trading.application.sinopac_contracts import SinopacAccountView, SinopacConnectionView
from quantlab.trading.application.state import AppState, StrategyRecord
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, Side
from quantlab.trading.domain.strategy import StrategyParameters
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation, UnmappedBrokerOrder
from quantlab.trading.ports.tick_stream import TickLoss
from quantlab.trading.runtime.automatic import AutomaticRuntime

SIM = Environment.BROKER_SIMULATION


class AutomaticRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = MutableClock()
        self.view = SinopacConnectionView(
            environment=SIM,
            phase='CONNECTED',
            generation='generation',
            revision=3,
            accounts=(SinopacAccountView('account', '***fixture', Market.INDEX_FUTURE, True, True),),
        )
        self.shared = SimpleNamespace(callback_errors=0)
        self.owner = SimpleNamespace(lock=RLock(), snapshot=Mock(side_effect=lambda: self.view), selected=('account',), shared=self.shared, query_ready=True)
        self.observation = ManualAccountObservation('account', SIM, (), (), (), self.clock.now())
        typed = SimpleNamespace(parameters=object(), form=SimpleNamespace(account_ref='account'))
        self.engine = SimpleNamespace(
            lock=RLock(),
            state=replace(AppState(), environment=SIM, strategies=(typed,)),
            clock=self.clock,
            storage_failed=False,
            gateways={'account': Mock()},
            manual_observations={'account': self.observation},
        )
        self.manual = SimpleNamespace(owner=self.owner, stamp=('generation', 3, ('account',), self.shared), error='')
        self.events = []
        self.terminal = SimpleNamespace(
            on_tick=Mock(side_effect=lambda *args: self.events.append('alert_tick')), on_bars=Mock(side_effect=lambda *args: self.events.append('alert_bars'))
        )
        self.bundle = SimpleNamespace(
            engine=self.engine,
            manual_runtime=self.manual,
            sinopac_connection=self.owner,
            market_terminal=self.terminal,
            launch=SimpleNamespace(environment=SIM),
            lock=RLock(),
            version_offset=5,
            closing=False,
            resources_closed=False,
            control_failed=False,
        )
        self.runtime = AutomaticRuntime(self.bundle)
        self.application = SimpleNamespace(
            pause_automatic=Mock(side_effect=self.pause),
            resume_automatic=Mock(),
            reconcile_automatic=Mock(),
            on_completed_bars=Mock(side_effect=lambda *args: self.events.append('evaluate')),
            pump_automatic=Mock(side_effect=lambda *args: self.events.append('protective')),
        )
        self.app_patch = patch.object(application_package, 'automatic', self.application, create=True)
        self.app_patch.start()
        self.addCleanup(self.app_patch.stop)
        self.facts = PreflightFacts(True, True, True, None, True, True, True)
        self.health = patch('quantlab.trading.runtime.automatic.sinopac_preflight_facts', side_effect=lambda *args: self.facts)
        self.collect = self.health.start()
        self.addCleanup(self.health.stop)

    def pause(self, engine, reason):
        engine.state = replace(engine.state, automatic=pause(getattr(engine.state, 'automatic', AutomaticState()), reason))
        self.events.append('pause:' + reason)

    def bar(self, **changes):
        now = self.clock.now()
        return replace(LiveBar('TMF', now - timedelta(minutes=1), now, now.date(), 'DAY', *([Decimal('10')] * 4), 1, final=True), **changes)

    def command(self, action=UiAction.AUTO_RESUME, **changes):
        return replace(UiCommand(action, self.engine.state.version + self.bundle.version_offset, environment=SIM), **changes)

    def enqueue(self, bars=None):
        self.runtime._enqueue((self.bar(),) if bars is None else bars)

    def test_callbacks_chain_after_alerts_enqueue_only_completed_and_defer_engine(self):
        self.runtime.attach_terminal()
        bars = [self.bar(), self.bar(final=False), self.bar(incomplete=True)]
        self.terminal.on_tick(object(), bars)
        self.terminal.on_bars('TMF', bars, self.clock.now(), self.clock.now().date())
        bars.clear()
        self.assertEqual(self.events, ['alert_tick', 'alert_bars'])
        self.assertEqual(len(self.runtime.queue), 2)
        self.assertEqual(self.runtime.queue[0][-1], (self.bar(),))
        self.application.on_completed_bars.assert_not_called()
        self.runtime.pump()
        self.assertEqual(self.application.on_completed_bars.call_count, 2)
        self.assertEqual(self.events[-3:], ['evaluate', 'evaluate', 'protective'])
        self.assertEqual(len(self.runtime.queue), 0)

    def test_attach_idempotent_missing_terminal_and_empty_callback(self):
        self.bundle.market_terminal = None
        self.runtime.attach_terminal()
        self.bundle.market_terminal = self.terminal
        self.runtime.attach_terminal()
        callback = self.terminal.on_tick
        self.runtime.attach_terminal()
        self.assertIs(self.terminal.on_tick, callback)
        self.terminal.on_tick(object(), (self.bar(final=False),))
        self.assertEqual(len(self.runtime.queue), 0)

    def test_queue_overflow_drops_batch_and_pauses_before_any_entry_protective_still_runs(self):
        with patch('quantlab.trading.runtime.automatic.MAX_QUEUED_BATCHES', 1):
            self.enqueue()
            self.enqueue()
            self.enqueue()
        self.assertEqual(len(self.runtime.queue), 0)
        self.runtime.pump()
        self.application.on_completed_bars.assert_not_called()
        self.assertEqual(self.events, ['pause:automatic_market_gap', 'protective'])
        self.runtime.pump()
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.application.resume_automatic.assert_not_called()

    def test_oversized_batch_is_a_gap(self):
        with patch('quantlab.trading.runtime.automatic.MAX_BATCH_BARS', 1):
            self.enqueue((self.bar(), self.bar()))
        self.runtime.pump()
        self.application.on_completed_bars.assert_not_called()
        self.application.pause_automatic.assert_called_once_with(self.engine, 'automatic_market_gap')

    def test_queue_from_obsolete_engine_owner_or_stamp_is_never_evaluated(self):
        for field in ('engine', 'owner', 'stamp'):
            with self.subTest(field=field):
                self.enqueue()
                batch = self.runtime.queue.popleft()
                index = {'engine': 0, 'owner': 1, 'stamp': 2}[field]
                self.runtime.queue.append((*batch[:index], object(), *batch[index + 1 :]))
                self.runtime.pump()
        self.application.on_completed_bars.assert_not_called()
        self.assertEqual(self.application.pause_automatic.call_count, 3)

    def test_each_runtime_health_failure_stops_entries_but_not_protection(self):
        for key in ('connected', 'account_ready', 'permission_ready', 'realtime', 'service_open', 'reconciled'):
            for value in (False, None):
                with self.subTest(key=key, value=value):
                    self.facts = replace(self.facts, **{key: value})
                    self.enqueue()
                    self.runtime.pump()
                    self.facts = PreflightFacts(True, True, True, None, True, True, True)
        self.application.on_completed_bars.assert_not_called()
        self.assertEqual(self.application.pause_automatic.call_count, 12)
        self.assertEqual(self.application.pump_automatic.call_count, 12)

    def test_healthy_recovery_does_not_resume_and_ca_is_not_required(self):
        self.facts = replace(self.facts, realtime=False)
        self.runtime.pump()
        self.facts = replace(self.facts, realtime=True, ca_ready=False)
        self.enqueue()
        self.runtime.pump()
        self.application.on_completed_bars.assert_called_once()
        self.application.resume_automatic.assert_not_called()
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_health_collection_error_pauses_and_does_not_evaluate(self):
        self.collect.side_effect = DomainError('state_conflict')
        self.enqueue()
        self.runtime.pump()
        self.application.pause_automatic.assert_called_once_with(self.engine, 'state_conflict')
        self.application.on_completed_bars.assert_not_called()

    def test_actual_cached_collector_requires_current_generation_diagnostic_without_sdk_or_ca(self):
        from quantlab.trading.runtime.preflight import sinopac_preflight_facts

        fixture = preflight_fixtures.RuntimePreflightTests()
        fixture.setUp()
        bundle = fixture.bundle
        bundle.lock = fixture.engine.lock = fixture.owner.lock = RLock()
        bundle.control_failed = False
        fixture.manual.owner = fixture.owner
        fixture.engine.storage_failed = False
        typed = SimpleNamespace(
            parameters=StrategyParameters('5m', Decimal('.03'), Decimal('10000')),
            state='ENABLED',
            form=SimpleNamespace(account_ref='stock', instrument_id=fixture.stock.instrument_id),
        )
        fixture.engine.state = replace(fixture.engine.state, strategies=(typed,))
        runtime = AutomaticRuntime(bundle)
        self.collect.side_effect = sinopac_preflight_facts
        request = fixture.engine.state.manual_requests[0]
        fixture.engine.state = replace(
            fixture.engine.state, manual_requests=(replace(request, scope=replace(request.scope, connection_generation='obsolete')),)
        )
        runtime.pump()
        self.application.pause_automatic.assert_called_once_with(fixture.engine, 'preflight_permission')
        self.application.pause_automatic.reset_mock()
        fixture.engine.state = replace(fixture.engine.state, manual_requests=(request,))
        runtime.pump()
        self.application.pause_automatic.assert_not_called()
        self.application.resume_automatic.assert_not_called()
        fixture.no_queries_or_ca()

    def test_no_typed_strategies_retains_manual_behavior(self):
        self.engine.state = replace(self.engine.state, strategies=())
        self.enqueue()
        self.runtime.pump()
        self.collect.assert_not_called()
        self.application.pause_automatic.assert_not_called()
        self.application.pump_automatic.assert_not_called()

    def test_live_all_public_routes_fail_closed(self):
        self.bundle.launch.environment = Environment.LIVE
        for action in (UiAction.AUTO_RESUME, UiAction.AUTO_RECONCILE):
            for target in (None, SIM, Environment.LIVE):
                self.assertEqual(self.runtime.execute(self.command(action, environment=target)).code, 'production_orders_disabled')
        self.enqueue()
        self.runtime.pump()
        with self.assertRaises(DomainError) as error:
            self.runtime.validate_observation('account', self.observation)
        self.assertEqual(error.exception.code, 'production_orders_disabled')
        self.application.resume_automatic.assert_not_called()
        self.application.reconcile_automatic.assert_not_called()
        self.application.on_completed_bars.assert_not_called()
        self.application.pump_automatic.assert_not_called()
        self.assertEqual(self.engine.gateways['account'].mock_calls, [])

    def test_local_does_not_consume_realtime_bars_or_require_broker_health(self):
        self.bundle.launch.environment = Environment.LOCAL
        self.bundle.sinopac_connection = None
        self.bundle.manual_runtime = None
        self.enqueue()
        self.runtime.pump()
        self.collect.assert_not_called()
        self.application.on_completed_bars.assert_not_called()
        self.application.pump_automatic.assert_not_called()
        self.assertEqual(self.runtime.execute(self.command(environment=Environment.LOCAL)).code, 'capability_missing')
        self.application.resume_automatic.assert_not_called()

    def futures(self):
        self.future = instrument(Market.INDEX_FUTURE)
        self.tick_queue = FakeTickQueue()
        adapter = SimpleNamespace(
            tick_stream=self.tick_queue,
            connected=True,
            environment=SIM,
            subscriptions={'subscription': (self.future.instrument_id,)},
            bindings={self.future.instrument_id: SimpleNamespace(spec=self.future)},
        )
        self.manual.adapter = adapter
        return adapter

    def tick(self, source_at, *, instrument_id=None, price='10'):
        return Tick(instrument_id or self.future.instrument_id, Decimal(price), 1, source_at, source_at, source_at.date(), source='SHIOAJI')

    def test_futures_tick_rollover_enqueues_only_final_and_finalizes_without_next_tick_once(self):
        adapter = self.futures()
        start = self.clock.now()
        self.clock.value = start + timedelta(seconds=10)
        self.tick_queue.ticks.append(self.tick(self.clock.now()))
        self.runtime.pump_futures(adapter)
        self.assertEqual(len(self.runtime.queue), 0)
        self.clock.value = start + timedelta(seconds=61)
        self.tick_queue.ticks.append(self.tick(self.clock.now(), price='11'))
        self.runtime.pump_futures(adapter)
        self.assertEqual(len(self.runtime.queue), 1)
        self.assertEqual(self.runtime.queue[0][-1][0].end, start + timedelta(minutes=1))
        self.assertTrue(self.runtime.queue[0][-1][0].final)
        self.clock.value = start + timedelta(minutes=2)
        self.runtime.pump_futures(adapter)
        self.assertEqual(len(self.runtime.queue), 2)
        self.runtime.pump_futures(adapter)
        self.assertEqual(len(self.runtime.queue), 2)

    def test_futures_without_selected_subscription_connection_or_typed_strategy_never_drains(self):
        adapter = self.futures()
        for target, key, value in (
            (adapter, 'subscriptions', {}),
            (adapter, 'connected', False),
            (adapter, 'environment', Environment.LIVE),
            (adapter, 'tick_stream', None),
            (self.bundle.launch, 'environment', Environment.LIVE),
        ):
            original = getattr(target, key)
            setattr(target, key, value)
            self.runtime.pump_futures(adapter)
            setattr(target, key, original)
        self.engine.state = replace(self.engine.state, strategies=())
        self.runtime.pump_futures(adapter)
        self.runtime.pump_futures(None)
        self.assertEqual(self.tick_queue.drains, 0)

    def test_futures_never_consumes_stock_as_automatic_futures_or_modifies_terminal_callbacks(self):
        adapter = self.futures()
        stock = instrument()
        adapter.bindings[stock.instrument_id] = SimpleNamespace(spec=stock)
        adapter.subscriptions['stock'] = (stock.instrument_id,)
        self.tick_queue.ticks.extend((self.tick(self.clock.now(), instrument_id=stock.instrument_id), self.tick(self.clock.now())))
        callbacks = self.terminal.on_tick, self.terminal.on_bars
        self.runtime.pump_futures(adapter)
        self.assertEqual(set(self.runtime.future_minutes), {self.future.instrument_id})
        self.assertEqual((self.terminal.on_tick, self.terminal.on_bars), callbacks)

    def test_futures_adapter_generation_and_engine_reset_do_not_merge_minute_state(self):
        adapter = self.futures()
        self.tick_queue.ticks.append(self.tick(self.clock.now()))
        self.runtime.pump_futures(adapter)
        for changed in ('adapter', 'stamp', 'engine'):
            with self.subTest(changed=changed):
                if changed == 'adapter':
                    adapter = self.futures()
                elif changed == 'stamp':
                    self.manual.stamp = ('next-generation', 4, ('account',), self.shared)
                else:
                    self.bundle.engine = SimpleNamespace(**vars(self.engine))
                self.tick_queue.ticks.append(self.tick(self.clock.now(), price='20'))
                self.runtime.pump_futures(adapter)
                bar = self.runtime.future_minutes[self.future.instrument_id].bar
                self.assertEqual((bar.open, bar.volume), (Decimal('20'), 1))

    def test_futures_loss_marks_existing_and_incoming_minutes_incomplete_pauses_without_entry(self):
        adapter = self.futures()
        start = self.clock.now()
        self.tick_queue.ticks.append(self.tick(start))
        self.runtime.pump_futures(adapter)
        self.tick_queue.losses.append(TickLoss(self.future.instrument_id, start + timedelta(seconds=10), start + timedelta(minutes=1, seconds=20), 2))
        self.clock.value = start + timedelta(minutes=1, seconds=10)
        self.tick_queue.ticks.append(self.tick(self.clock.now()))
        self.runtime.pump_futures(adapter)
        self.assertTrue(self.runtime.future_minutes[self.future.instrument_id].bar.incomplete)
        self.runtime.pump()
        self.application.pause_automatic.assert_called_once_with(self.engine, 'automatic_market_gap')
        self.application.on_completed_bars.assert_not_called()
        self.assertEqual(len(self.runtime.queue), 0)

    def test_futures_loss_before_first_tick_persists_until_last_affected_minute(self):
        adapter = self.futures()
        start = self.clock.now()
        self.tick_queue.losses.append(TickLoss(self.future.instrument_id, start, start + timedelta(minutes=1), 2))
        self.runtime.pump_futures(adapter)
        self.tick_queue.ticks.append(self.tick(start))
        self.runtime.pump_futures(adapter)
        self.assertTrue(self.runtime.future_minutes[self.future.instrument_id].bar.incomplete)
        self.clock.value = start + timedelta(minutes=2)
        self.tick_queue.ticks.append(self.tick(self.clock.now()))
        self.runtime.pump_futures(adapter)
        self.assertNotIn(self.future.instrument_id, self.runtime.future_losses)

    def test_futures_loss_invalidates_already_forming_minute_without_needing_another_tick(self):
        adapter = self.futures()
        start = self.clock.now()
        self.tick_queue.ticks.append(self.tick(start))
        self.runtime.pump_futures(adapter)
        self.tick_queue.losses.append(TickLoss(self.future.instrument_id, start, start, 1))
        self.runtime.pump_futures(adapter)
        self.assertTrue(self.runtime.future_minutes[self.future.instrument_id].bar.incomplete)

    def test_futures_loss_unrelated_to_selected_future_is_ignored(self):
        adapter = self.futures()
        self.tick_queue.losses.append(TickLoss('unselected', self.clock.now(), self.clock.now(), 1))
        self.runtime.pump_futures(adapter)
        self.assertFalse(self.runtime.overflow)
        self.assertEqual(self.runtime.future_losses, {})

    def test_futures_stale_adapter_or_closing_runtime_does_not_drain(self):
        adapter = self.futures()
        self.manual.adapter = object()
        self.runtime.pump_futures(adapter)
        self.manual.adapter = adapter
        for key in ('closing', 'resources_closed', 'control_failed'):
            setattr(self.bundle, key, True)
            self.runtime.pump_futures(adapter)
            setattr(self.bundle, key, False)
        self.assertEqual(self.tick_queue.drains, 0)

    def test_validated_worker_observation_never_queries_ports_and_unrelated_unmapped_does_not_block_exit(self):
        self.assertTrue(self.runtime.validate_observation('account', self.observation))
        row = replace(self.observation, unmapped=(UnmappedBrokerOrder('unrelated'),))
        self.engine.manual_observations['account'] = row
        self.assertTrue(self.runtime.validate_observation('account', row))
        self.assertEqual(self.engine.gateways['account'].mock_calls, [])

    def test_observation_owner_generation_revision_selection_shared_and_cache_identity(self):
        self.manual.owner = object()
        with self.assertRaises(DomainError):
            self.runtime.validate_observation('account', self.observation)
        self.manual.owner = self.owner
        for stamp in (
            ('old', 3, ('account',), self.shared),
            ('generation', 2, ('account',), self.shared),
            ('generation', 3, (), self.shared),
            ('generation', 3, ('account',), object()),
        ):
            self.manual.stamp = stamp
            with self.assertRaises(DomainError):
                self.runtime.validate_observation('account', self.observation)
        self.manual.stamp = ('generation', 3, ('account',), self.shared)
        with self.assertRaises(DomainError):
            self.runtime.validate_observation('unselected', self.observation)
        unselected = replace(self.observation, account_ref='unselected')
        self.engine.manual_observations['unselected'] = unselected
        self.view = replace(self.view, accounts=(*self.view.accounts, SinopacAccountView('unselected', '***other', Market.INDEX_FUTURE, True, True)))
        with self.assertRaises(DomainError):
            self.runtime.validate_observation('unselected', unselected)
        with self.assertRaises(DomainError):
            self.runtime.validate_observation('account', replace(self.observation))

    def test_observation_health_and_freshness_each_fail_closed(self):
        for changes in (
            {'account_ref': 'wrong'},
            {'environment': Environment.LOCAL},
            {'source': 'UNVERIFIED'},
            {'as_of': self.clock.now() + timedelta(seconds=1)},
            {'as_of': self.clock.now() - timedelta(seconds=31)},
        ):
            row = replace(self.observation, **changes)
            self.engine.manual_observations['account'] = row
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.runtime.validate_observation('account', row)
        self.engine.manual_observations['account'] = self.observation
        for attribute, value in (('query_ready', False), ('shared', None)):
            old = getattr(self.owner, attribute)
            setattr(self.owner, attribute, value)
            with self.assertRaises(DomainError):
                self.runtime.validate_observation('account', self.observation)
            setattr(self.owner, attribute, old)
        for attribute, value in (('closing', True), ('resources_closed', True)):
            setattr(self.bundle, attribute, value)
            with self.assertRaises(DomainError):
                self.runtime.validate_observation('account', self.observation)
            setattr(self.bundle, attribute, False)
        self.shared.callback_errors = 1
        with self.assertRaises(DomainError):
            self.runtime.validate_observation('account', self.observation)
        self.shared.callback_errors = 0
        self.manual.error = 'unhealthy'
        with self.assertRaises(DomainError):
            self.runtime.validate_observation('account', self.observation)

    def test_observation_requires_connected_simulation_owner(self):
        for changes in ({'phase': 'DISCONNECTED'}, {'environment': Environment.LIVE}):
            self.view = replace(self.view, **changes)
            with self.assertRaises(DomainError):
                self.runtime.validate_observation('account', self.observation)
            self.view = SinopacConnectionView(environment=SIM, phase='CONNECTED', generation='generation', revision=3)

    def test_observation_selected_account_must_be_currently_signed_without_permission_or_market_gate(self):
        for account in ((), (replace(self.view.accounts[0], signed=False),), (replace(self.view.accounts[0], signed=None),)):
            original = self.view
            self.view = replace(self.view, accounts=account)
            with self.assertRaises(DomainError):
                self.runtime.validate_observation('account', self.observation)
            self.view = original
        self.facts = PreflightFacts(True, True, False, None, False, False, True)
        self.assertTrue(self.runtime.validate_observation('account', self.observation))
        self.collect.assert_not_called()

    def test_entry_rechecks_every_current_fact_despite_old_passed_preflight(self):
        self.engine.state = replace(
            self.engine.state, preflight=(preflight_fixtures.build_preflight('account', self.engine.state.trading_day, self.clock.now(), SIM, self.facts),)
        )
        self.assertTrue(self.runtime.validate_entry('account'))
        for key, code in (
            ('connected', 'preflight_connection'),
            ('account_ready', 'preflight_account'),
            ('permission_ready', 'preflight_permission'),
            ('realtime', 'preflight_market'),
            ('service_open', 'preflight_service'),
            ('reconciled', 'preflight_reconciliation'),
        ):
            for value in (False, None):
                original = self.facts
                self.facts = replace(self.facts, **{key: value})
                with self.subTest(key=key, value=value), self.assertRaises(DomainError) as error:
                    self.runtime.validate_entry('account')
                self.assertEqual(error.exception.code, code)
                self.facts = original
        self.facts = replace(self.facts, ca_ready=False)
        self.assertTrue(self.runtime.validate_entry('account'))
        self.assertEqual(self.engine.gateways['account'].mock_calls, [])

    def test_entry_environment_missing_owner_and_closure_guards(self):
        for target in (Environment.LOCAL, Environment.LIVE):
            self.bundle.launch.environment = target
            with self.assertRaises(DomainError):
                self.runtime.validate_entry('account')
        self.bundle.launch.environment = SIM
        for key in ('engine', 'sinopac_connection', 'manual_runtime'):
            original = getattr(self.bundle, key)
            setattr(self.bundle, key, None)
            with self.assertRaises(DomainError):
                self.runtime.validate_entry('account')
            setattr(self.bundle, key, original)
        for key in ('closing', 'resources_closed', 'control_failed'):
            setattr(self.bundle, key, True)
            with self.assertRaises(DomainError):
                self.runtime.validate_entry('account')
            setattr(self.bundle, key, False)
        self.manual.owner = object()
        with self.assertRaises(DomainError):
            self.runtime.validate_entry('account')

    def test_entry_final_owner_generation_revision_selection_shared_and_closure_cas(self):
        changes = (
            lambda: setattr(self, 'view', replace(self.view, generation='next')),
            lambda: setattr(self, 'view', replace(self.view, revision=4)),
            lambda: setattr(self.owner, 'selected', ('other',)),
            lambda: setattr(self.owner, 'shared', object()),
            lambda: setattr(self.bundle, 'sinopac_connection', object()),
            lambda: setattr(self.bundle, 'engine', object()),
            lambda: setattr(self.bundle, 'manual_runtime', object()),
            *(lambda key=key: setattr(self.bundle, key, True) for key in ('closing', 'resources_closed', 'control_failed')),
        )
        for change in changes:
            original = self.view, self.owner.selected, self.owner.shared
            self.collect.side_effect = lambda *args: (change(), self.facts)[1]
            with self.assertRaises(DomainError) as error:
                self.runtime.validate_entry('account')
            self.assertEqual(error.exception.code, 'state_conflict')
            self.view, self.owner.selected, self.owner.shared = original
            self.bundle.engine, self.bundle.sinopac_connection, self.bundle.manual_runtime = self.engine, self.owner, self.manual
            self.bundle.closing = self.bundle.resources_closed = self.bundle.control_failed = False

    def test_entry_actual_provider_requires_current_diagnostic_and_realtime_without_sdk_or_ca(self):
        from quantlab.trading.runtime.preflight import sinopac_preflight_facts

        fixture = preflight_fixtures.RuntimePreflightTests()
        fixture.setUp()
        fixture.engine.lock = fixture.owner.lock = RLock()
        fixture.bundle.control_failed = False
        fixture.manual.owner = fixture.owner
        runtime = AutomaticRuntime(fixture.bundle)
        self.collect.side_effect = sinopac_preflight_facts
        self.assertTrue(runtime.validate_entry('stock'))
        request = fixture.engine.state.manual_requests[0]
        fixture.engine.state = replace(
            fixture.engine.state, manual_requests=(replace(request, scope=replace(request.scope, connection_generation='obsolete')),)
        )
        with self.assertRaises(DomainError) as error:
            runtime.validate_entry('stock')
        self.assertEqual(error.exception.code, 'preflight_permission')
        fixture.engine.state = replace(fixture.engine.state, manual_requests=(request,))
        quote = fixture.engine.quotes[fixture.stock.instrument_id]
        fixture.engine.quotes[fixture.stock.instrument_id] = replace(
            quote, source_at=quote.source_at - timedelta(seconds=11), received_at=quote.received_at - timedelta(seconds=11)
        )
        with self.assertRaises(DomainError) as error:
            runtime.validate_entry('stock')
        self.assertEqual(error.exception.code, 'preflight_market')
        fixture.no_queries_or_ca()

    def test_reconcile_after_close_ignores_entry_only_service_market_permission_and_never_resumes(self):
        self.facts = replace(self.facts, service_open=False, realtime=False, permission_ready=False)
        self.assertTrue(self.runtime.execute(self.command(UiAction.AUTO_RECONCILE)).accepted)
        self.application.reconcile_automatic.assert_called_once_with(self.engine)
        self.application.resume_automatic.assert_not_called()
        self.collect.assert_not_called()

    def test_execute_known_action_routes_with_cas_and_no_sdk(self):
        self.assertFalse(self.runtime.handles(self.command(UiAction.RESUME)))
        for action in (UiAction.AUTO_RESUME, UiAction.AUTO_RECONCILE):
            self.assertTrue(self.runtime.handles(self.command(action)))
            self.assertTrue(self.runtime.execute(self.command(action, environment=None)).accepted)
        self.application.resume_automatic.assert_called_once_with(self.engine)
        self.application.reconcile_automatic.assert_called_once_with(self.engine)
        self.assertEqual(self.engine.gateways['account'].mock_calls, [])

    def test_execute_malformed_wrong_version_environment_or_account_never_calls_application(self):
        for changes in (
            {'expected_version': True},
            {'expected_version': -1},
            {'account_ref': 3},
            {'account_ref': 'wrong'},
            {'environment': Environment.LOCAL},
            {'action': UiAction.RESUME},
            {'action': 'auto_resume'},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.runtime.execute(self.command(**changes)).accepted)
        self.application.resume_automatic.assert_not_called()
        self.assertEqual(self.runtime.execute(self.command(environment=Environment.LIVE)).code, 'production_orders_disabled')

    def test_boolean_version_equal_to_current_integer_and_falsy_account_still_rejected(self):
        self.bundle.version_offset = 1
        self.assertEqual(self.runtime.execute(self.command(expected_version=True)).code, 'validation_failed')
        self.assertEqual(self.runtime.execute(self.command(account_ref=False)).code, 'validation_failed')
        self.application.resume_automatic.assert_not_called()

    def test_deny_only_envelope_never_resumes_or_reconciles_and_requires_exact_boolean(self):
        for action in (UiAction.AUTO_RESUME, UiAction.AUTO_RECONCILE):
            for denied in (True, 0, 1, None):
                self.assertFalse(self.runtime.execute(self.command(action, manual_no_admission=denied)).accepted)
        self.application.resume_automatic.assert_not_called()
        self.application.reconcile_automatic.assert_not_called()

    def test_execute_each_closure_flag_and_no_engine(self):
        for key in ('closing', 'resources_closed', 'control_failed'):
            setattr(self.bundle, key, True)
            self.assertFalse(self.runtime.execute(self.command()).accepted)
            setattr(self.bundle, key, False)
        command = self.command()
        self.bundle.engine = None
        self.assertFalse(self.runtime.execute(command).accepted)
        self.application.resume_automatic.assert_not_called()

    def test_execute_rechecks_engine_owner_and_version_offset_inside_composition_lock(self):
        for attribute, value in (('engine', object()), ('sinopac_connection', object()), ('version_offset', 6)):
            with self.subTest(attribute=attribute):
                command = self.command()
                original = getattr(self.bundle, attribute)
                self.bundle.lock = EnterHook(lambda: setattr(self.bundle, attribute, value))
                self.assertEqual(self.runtime.execute(command).code, 'state_conflict')
                setattr(self.bundle, attribute, original)
                self.bundle.lock = RLock()
        self.application.resume_automatic.assert_not_called()

    def test_validate_rechecks_engine_owner_and_manual_runtime_inside_engine_lock(self):
        for attribute in ('engine', 'sinopac_connection', 'manual_runtime'):
            with self.subTest(attribute=attribute):
                original = getattr(self.bundle, attribute)
                self.engine.lock = EnterHook(lambda: setattr(self.bundle, attribute, object()))
                with self.assertRaises(DomainError):
                    self.runtime.validate_observation('account', self.observation)
                setattr(self.bundle, attribute, original)
                self.engine.lock = RLock()

    def test_validation_from_engine_submit_never_waits_for_snapshot_composition_lock(self):
        self.bundle.lock = TimedLock()
        engine_held, bundle_held = Event(), Event()
        failures = []

        def submit_path():
            try:
                with self.engine.lock:
                    engine_held.set()
                    if not bundle_held.wait(1):
                        raise AssertionError('snapshot did not acquire composition lock')
                    self.runtime.validate_observation('account', self.observation)
                    self.runtime.validate_entry('account')
            except Exception as error:
                failures.append(error)

        def snapshot_path():
            try:
                if not engine_held.wait(1):
                    raise AssertionError('submit did not acquire engine lock')
                with self.bundle.lock:
                    bundle_held.set()
                    with self.engine.lock:
                        pass
            except Exception as error:
                failures.append(error)

        threads = (Thread(target=submit_path, daemon=True), Thread(target=snapshot_path, daemon=True))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])

    def test_pump_rechecks_engine_and_owner_inside_composition_lock(self):
        for attribute in ('engine', 'sinopac_connection'):
            with self.subTest(attribute=attribute):
                original = getattr(self.bundle, attribute)
                self.bundle.lock = EnterHook(lambda: setattr(self.bundle, attribute, object()))
                self.runtime.pump()
                setattr(self.bundle, attribute, original)
                self.bundle.lock = RLock()
        self.application.pump_automatic.assert_not_called()

    def test_execute_failed_health_pauses_and_explicit_resumption_errors_are_returned(self):
        self.facts = replace(self.facts, permission_ready=None)
        self.assertEqual(self.runtime.execute(self.command()).code, 'preflight_permission')
        self.application.resume_automatic.assert_not_called()
        self.facts = replace(self.facts, permission_ready=True)
        self.application.resume_automatic.side_effect = DomainError('preflight_blocked')
        self.assertEqual(self.runtime.execute(self.command()).code, 'preflight_blocked')

    def test_pump_closure_and_storage_states_do_no_work(self):
        for owner, key in ((self.bundle, 'closing'), (self.bundle, 'resources_closed'), (self.bundle, 'control_failed'), (self.engine, 'storage_failed')):
            setattr(owner, key, True)
            self.runtime.pump()
            setattr(owner, key, False)
        self.engine.state = replace(self.engine.state, engine_closed=True)
        self.runtime.pump()
        self.application.pump_automatic.assert_not_called()


class NativeAutomaticRuntimeTests(unittest.TestCase):
    def native_fixture(self):
        fixture = native_fixtures.ManualRuntimeIntegrationTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.bundle.sinopac_connection.shared.facade._module.QuoteType = QuoteType
        fixture.bundle.sinopac_connection.shared.facade._module.QuoteVersion = QuoteVersion
        fixture.bundle.sinopac_connection.publish(accounts=(SinopacAccountView(fixture.alias, '***fixture', fixture.spec.market, True, True),))
        fixture.ready()
        engine, bundle = fixture.bundle.engine, fixture.bundle
        form = StrategyForm(
            'automatic-native-fixture',
            fixture.spec.market,
            HoldingKind.CUSTOM,
            0,
            5,
            Side.BUY,
            fixture.spec.instrument_id,
            fixture.alias,
            SIM,
            Decimal('10000'),
            Decimal('.02'),
        )
        record = StrategyRecord(
            'automatic-native-fixture', 1, form, HoldingPolicy(HoldingKind.CUSTOM, 0, 5), parameters=StrategyParameters('1m', Decimal('.03'), Decimal('10000'))
        )
        with engine.lock:
            engine._persist('automatic_runtime_fixture', replace(engine.state, strategies=(record,)))
        return fixture, engine, bundle

    def test_real_bundle_fake_sdk_refuses_unproven_permission_without_new_native_queries(self):
        fixture, engine, bundle = self.native_fixture()
        before = tuple(fixture.native._seen)
        runtime = bundle.automatic_runtime
        observation = engine.manual_observations[fixture.alias]
        self.assertTrue(runtime.validate_observation(fixture.alias, observation))
        command = UiCommand(UiAction.AUTO_RESUME, engine.state.version + bundle.version_offset, environment=SIM, account_ref=fixture.alias)
        receipt = runtime.execute(command)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'preflight_permission')
        self.assertTrue(engine.state.automatic.auto_paused)
        self.assertIn('preflight_permission', engine.state.automatic.reasons)
        self.assertEqual(tuple(fixture.native._seen), before)

    def test_real_shared_sdk_fop_callback_drives_completed_future_bar_without_marketwatch_support(self):
        fixture, engine, bundle = self.native_fixture()
        bundle.poll_ports()
        adapter = bundle.manual_runtime.adapter
        self.assertEqual(bundle.manual_runtime.automatic_subscription, (fixture.spec.instrument_id,))
        callback = next(row[1][0] for row in fixture.native._seen if row[0] == 'set_on_tick_fop_v1_callback')
        runtime = bundle.automatic_runtime
        start = fixture.clock.now()
        before = tuple(fixture.native._seen)
        fixture.clock.value = start + timedelta(seconds=10)
        callback('TAIFEX', SimpleNamespace(code='TMFL6', datetime=fixture.clock.now(), close=25000, volume=1))
        runtime.pump_futures(adapter)
        self.assertEqual(len(runtime.queue), 0)
        fixture.clock.value = start + timedelta(seconds=61)
        callback('TAIFEX', SimpleNamespace(code='TMFL6', datetime=fixture.clock.now(), close=25001, volume=1))
        runtime.pump_futures(adapter)
        self.assertEqual(len(runtime.queue), 1)
        bar = runtime.queue[0][-1][0]
        self.assertEqual((bar.instrument_id, bar.end, bar.final, bar.incomplete), (fixture.spec.instrument_id, start + timedelta(minutes=1), True, False))
        self.assertNotIn(fixture.spec.instrument_id, bundle.market_terminal._minutes)
        self.assertEqual(tuple(fixture.native._seen), before)


class FakeTickQueue:
    def __init__(self):
        self.limit = 100
        self.ticks, self.losses = deque(), deque()
        self.drains = 0

    def drain_ticks(self, limit):
        self.drains += 1
        return tuple(self.ticks.popleft() for _ in range(min(limit, len(self.ticks))))

    def drain_tick_losses(self):
        self.drains += 1
        result = tuple(self.losses)
        self.losses.clear()
        return result


class EnterHook:
    """Change a captured owner/version at a deterministic lock boundary."""

    def __init__(self, callback):
        self.callback = callback

    def __enter__(self):
        self.callback()

    def __exit__(self, *_):
        return False


class TimedLock:
    """A lock inversion fails the test and releases its threads instead of hanging."""

    def __init__(self):
        self.lock = Lock()

    def __enter__(self):
        if not self.lock.acquire(timeout=0.5):
            raise AssertionError('validator acquired composition lock while holding engine lock')

    def __exit__(self, *_):
        self.lock.release()


if __name__ == '__main__':
    unittest.main()
