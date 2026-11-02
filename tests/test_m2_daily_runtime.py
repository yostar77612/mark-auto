"""Public RuntimeBundle.pump with native execution and market callback inputs."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from threading import RLock
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

import test_m2_daily_native as native
import test_manual_runtime_integration as built_fixtures
from test_trading_sdk_facade import QuoteType, QuoteVersion
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.daily_execution import observe_daily
from quantlab.trading.application import automatic
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.manual_contracts import ManualOrderForm
from quantlab.trading.application.preflight import record_preflight
from quantlab.trading.application.sinopac_contracts import SinopacAccountView
from quantlab.trading.application.workflows import run_research
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import Environment, HoldingKind, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.strategy import StrategyParameters
from quantlab.trading.runtime.automatic import AutomaticRuntime
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.build import synthetic_history
from quantlab.trading.runtime.preflight import sinopac_preflight_facts
from quantlab.trading.runtime.protocol import Operation
from quantlab.trading.runtime.daily_automatic import _open, route_daily

D = Decimal


class TapeTerminal:
    """Only the external market port is substituted; alerts precede queuing."""

    def __init__(self):
        self.tape = []
        self.deliveries = []
        self.on_tick = lambda tick, bars: self.deliveries.append(('alert_tick', tuple(bars)))
        self.on_bars = lambda instrument, bars, now, day: self.deliveries.append(('alert_bars', tuple(bars)))

    def poll(self):
        tape, self.tape = self.tape, []
        for instrument, bars, now in tape:
            self.on_bars(instrument, bars, now, now.date())


def public_bundle(fixture):
    """Use the actual host method with native owner/core and explicit port inputs."""
    bundle = object.__new__(RuntimeBundle)
    bundle.__dict__.update(vars(fixture.bundle))
    bundle.lock = RLock()
    bundle.version_offset = 0
    bundle.transitioning = False
    bundle.facade = LocalFacade(fixture.engine)
    bundle.market_terminal = TapeTerminal()
    bundle.alerts = SimpleNamespace(poll_scanner=lambda: None)
    bundle.manual_runtime.adapter = fixture.case.adapter
    runtime = AutomaticRuntime(bundle)
    bundle.automatic_runtime = runtime
    fixture.bundle, fixture.runtime = bundle, runtime
    fixture.engine.automatic_observation_validator = runtime.validate_observation
    fixture.engine.automatic_entry_validator = runtime.validate_entry
    fixture.engine.automatic_submission_guard = runtime.submission_guard
    fixture.engine.automatic_owner_stamp = runtime.owner_stamp
    runtime.attach_terminal()
    return bundle


class DailyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native.DailyNativeFixture(self.addCleanup)
        self.bundle = public_bundle(self.fixture)

    def deliver(self, bars):
        fixture = self.fixture
        instrument_id = bars[0].instrument_id if bars else fixture.spec.instrument_id
        self.bundle.market_terminal.tape.append((instrument_id, bars, fixture.clock.now()))
        self.bundle.pump()

    def deploy_future_with_normal_five_minute_exit(self):
        fixture, engine = self.fixture, self.fixture.engine
        spec = fixture.case.spec
        definition = json.dumps(
            {
                'schema_version': 2,
                'strategy_id': 'mixed-future',
                'version': 1,
                'market': spec.market.value,
                'holding_policy': {'kind': HoldingKind.CUSTOM.value, 'min_days': 0, 'max_days': 10, 'night_enabled': False, 'expiry_action': 'EXIT'},
                'bar_interval': '5m',
                'direction': 'LONG_ONLY',
                'entry': [{'field': 'close', 'operator': 'GT', 'value': '0'}],
                'exit': [{'field': 'close', 'operator': 'LT', 'value': '24999'}],
                'cost_version': engine.fees.version,
                'risk_ref': engine.risk().policy.version,
            }
        )
        form = StrategyForm(
            'mixed-open-future',
            spec.market,
            HoldingKind.CUSTOM,
            0,
            10,
            Side.BUY,
            spec.instrument_id,
            'future-alias',
            Environment.BROKER_SIMULATION,
            D('40000'),
            D('.02'),
            'STRUCTURED_JSON',
            draft_json=definition,
        )
        reference = engine.create_strategy(form, StrategyParameters('5m', D('.001'), D('40000')))
        with engine.lock:
            engine.validate_strategy(reference)
            run_research(engine, reference, engine.history[spec.instrument_id])
            engine.deploy(reference)
        return engine.strategy(reference)

    def test_public_pump_saves_close_signal_after_alert_callback_without_native_send(self):
        fixture = self.fixture
        record = fixture.deploy()
        fixture.start()
        close = fixture.session().closes_at
        fixture.refresh(close - timedelta(seconds=1))
        fixture.clock.value = close
        before, orders = fixture.placed(), fixture.engine.state.orders
        self.deliver(fixture.minutes())
        self.assertEqual(len(self.bundle.market_terminal.deliveries), 1)
        self.assertEqual(self.bundle.market_terminal.deliveries[0][0], 'alert_bars')
        self.assertFalse(self.bundle.automatic_runtime.queue)
        intents = fixture.engine.state.automatic.daily.intents
        self.assertEqual(len(intents), 1)
        self.assertEqual((intents[0].cursor.strategy_id, intents[0].phase), (record.strategy_id, 'READY'))
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(fixture.engine.state.orders, orders)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertTrue(fixture.engine.state.automatic.daily.waiting_session)

    def test_public_pump_does_not_save_incomplete_or_forming_daily_tail(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        close = fixture.session().closes_at
        fixture.refresh(close - timedelta(seconds=1))
        fixture.clock.value = close
        minutes = fixture.minutes()
        self.deliver((*minutes[:-1], replace(minutes[-1], final=False)))
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())
        self.assertEqual(fixture.placed(), fixture.initial_native_orders)
        self.assertTrue(fixture.engine.state.automatic.daily.waiting_session)

    def test_verified_close_can_save_after_cached_order_capability_expires(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        close = fixture.session().closes_at
        fixture.refresh(close - timedelta(seconds=1))
        fixture.clock.value = close
        for reference, capability in tuple(fixture.case.adapter.capabilities.items()):
            fixture.case.adapter.capabilities[reference] = replace(capability, checked_at=close - timedelta(minutes=1), expires_at=close)
        before = fixture.placed()
        self.deliver(fixture.minutes())
        self.assertEqual(len(fixture.engine.state.automatic.daily.intents), 1)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertTrue(fixture.engine.state.automatic.daily.waiting_session)
        self.assertEqual(fixture.placed(), before)

    def test_completed_day_cache_survives_pause_until_explicit_resume_before_close(self):
        fixture = self.fixture
        fixture.deploy()
        close = fixture.session().closes_at
        fixture.refresh(close - timedelta(seconds=1))
        minutes = fixture.minutes()
        self.deliver(minutes[:-1])
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        receipt = fixture.runtime.execute(
            UiCommand(UiAction.AUTO_RESUME, fixture.engine.state.version, environment=Environment.BROKER_SIMULATION, account_ref=fixture.account_ref)
        )
        self.assertTrue(receipt.accepted, receipt)
        fixture.clock.value = close
        self.deliver((minutes[-1],))
        self.assertEqual(len(fixture.engine.state.automatic.daily.intents), 1)
        self.assertEqual(fixture.placed(), fixture.initial_native_orders)

    def test_daily_runtime_live_controls_and_pumps_make_no_native_calls(self):
        fixture = self.fixture
        fixture.deploy()
        self.bundle.launch.environment = Environment.LIVE
        fixture.engine.configuration = replace(fixture.engine.configuration, environment=Environment.LIVE)
        before = tuple(fixture.case.native._seen)
        runtime = self.bundle.automatic_runtime
        for action in (UiAction.AUTO_RESUME, UiAction.AUTO_RECONCILE):
            command = UiCommand(action, fixture.engine.state.version, environment=Environment.LIVE, account_ref=fixture.account_ref)
            receipt = runtime.execute(command)
            self.assertFalse(receipt.accepted)
            self.assertEqual(receipt.code, 'production_orders_disabled')
        self.bundle.market_terminal.tape.append((fixture.spec.instrument_id, fixture.minutes(), fixture.clock.now()))
        self.bundle.pump()
        runtime.pump_futures(fixture.case.adapter)
        self.assertEqual(tuple(fixture.case.native._seen), before)
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())

    def test_preserved_normal_overnight_run_continues_through_public_pump_at_current_price(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        fixture.close()
        fixture.close_other_accounts()
        run = fixture.engine.state.automatic.daily.authorized_run
        before = fixture.placed()
        fixture.clock.value += timedelta(hours=8)
        self.bundle.pump()
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertEqual(fixture.engine.state.automatic.daily.authorized_run, run)
        self.assertEqual(fixture.placed(), before)
        fixture.refresh(fixture.next_session().opens_at + timedelta(minutes=1), stock_price=D('12'))
        self.bundle.pump()
        self.assertEqual(fixture.placed(), before + 1, fixture.engine.state.automatic)
        order = fixture.engine.state.orders[-1]
        self.assertEqual((order.plan.limit_price, order.plan.quantity), (D('12'), 2000))
        self.assertEqual(fixture.engine.state.automatic.daily.authorized_run, run)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)

    def test_disconnected_waiting_run_needs_explicit_resume_after_real_next_day_adoption(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        fixture.close()
        fixture.close_other_accounts()
        before = fixture.placed()
        fixture.base.owner_view = replace(fixture.base.owner_view, phase='DISCONNECTED')
        self.bundle.pump()
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertFalse(fixture.engine.state.automatic.daily.authorized_run)
        fixture.base.owner_view = replace(fixture.base.owner_view, phase='CONNECTED')
        fixture.refresh(fixture.next_session().opens_at + timedelta(minutes=1), stock_price=D('12'))
        self.bundle.pump()
        self.assertEqual(fixture.placed(), before)
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        receipt = self.bundle.automatic_runtime.execute(
            UiCommand(UiAction.AUTO_RESUME, fixture.engine.state.version, environment=Environment.BROKER_SIMULATION, account_ref=fixture.account_ref)
        )
        self.assertTrue(receipt.accepted, receipt)
        self.bundle.pump()
        self.assertEqual(fixture.placed(), before + 1, fixture.engine.state.automatic)

    def test_minute_run_rejects_a_healthy_current_owner_revision_different_from_run_owner(self):
        fixture = self.fixture
        fixture.deploy(interval='1m')
        fixture.start()
        fixture.base.owner_view = replace(fixture.base.owner_view, revision=fixture.base.owner_view.revision + 1)
        view = fixture.base.owner_view
        manual = self.bundle.manual_runtime
        manual.stamp = view.generation, view.revision, tuple(sorted(manual.owner.selected)), manual.owner.shared
        fixture.adopt(fixture.clock.now())
        self.assertEqual(sinopac_preflight_facts(self.bundle, fixture.account_ref).permission_ready, True)
        self.assertEqual(sinopac_preflight_facts(self.bundle, fixture.account_ref).reconciled, True)
        before = fixture.placed()
        self.bundle.pump()
        self.assertEqual(fixture.placed(), before)
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertIn('state_conflict', fixture.engine.state.automatic.reasons)

    def test_closed_stock_daily_does_not_swallow_open_future_five_minute_normal_exit(self):
        fixture = self.fixture
        fixture.deploy()
        record = self.deploy_future_with_normal_five_minute_exit()
        fixture.start()
        session = fixture.session(spec=fixture.case.spec)
        opening_end = session.opens_at.replace(hour=9, minute=5)
        fixture.refresh(opening_end)
        opening = tuple(
            bar for bar in fixture.minutes(spec=fixture.case.spec, price=D('25000')) if opening_end - timedelta(minutes=5) <= bar.start < opening_end
        )
        before = fixture.placed()
        self.deliver(opening)
        self.assertEqual(fixture.placed(), before + 1, fixture.engine.state.automatic)
        fixture.case.native.fill(fixture.case.native.trades[-1], 1, D('25000'))
        fixture.adopt(fixture.clock.now())
        lot = next(row for row in fixture.engine.state.positions if row.strategy_id == record.strategy_id and row.quantity)
        fixture.close()
        now = fixture.session().closes_at + timedelta(minutes=1)
        fixture.quote(fixture.case.spec, now, D('24998'))
        fixture.adopt(now)
        end = fixture.session().closes_at
        minutes = tuple(bar for bar in fixture.minutes(spec=fixture.case.spec, price=D('24998')) if end - timedelta(minutes=5) <= bar.start < end)
        before = fixture.placed()
        self.deliver((*minutes[:-1], replace(minutes[-1], final=False)))
        self.assertEqual(fixture.placed(), before)
        self.deliver((minutes[-1],))
        self.assertEqual(fixture.placed(), before + 1, fixture.engine.state.automatic)
        order = fixture.engine.state.orders[-1]
        self.assertTrue(order.plan.reduce_only)
        self.assertEqual((order.plan.exit_lot_id, order.plan.strategy_id), (lot.lot_id, record.strategy_id))
        self.assertLess(order.plan.limit_price, D('24999'))
        self.assertEqual(fixture.engine.quotes[fixture.spec.instrument_id].source_at, fixture.session().closes_at - timedelta(seconds=1))
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertTrue(fixture.engine.state.automatic.daily.authorized_run)
        self.deliver(minutes)
        self.assertEqual(fixture.placed(), before + 1)
        cursor = [row for row in fixture.engine.state.automatic.evaluations if row.cursor.strategy_id == record.strategy_id and row.cursor.bar_end == end]
        self.assertEqual(len(cursor), 1)
        self.assertEqual(cursor[0].phase, 'COMPLETED')
        fixture.case.native.fill(fixture.case.native.trades[-1], 1, order.plan.limit_price)
        fixture.adopt(now + timedelta(seconds=1))
        self.assertFalse(any(row.strategy_id == record.strategy_id and row.quantity for row in fixture.engine.state.positions))
        next_end = end + timedelta(minutes=5)
        fixture.quote(fixture.case.spec, next_end + timedelta(minutes=1), D('25000'))
        fixture.adopt(fixture.clock.now())
        fresh_entry_minutes = tuple(bar for bar in fixture.minutes(spec=fixture.case.spec, price=D('25000')) if end <= bar.start < next_end)
        self.deliver(fresh_entry_minutes)
        self.assertEqual(fixture.placed(), before + 1, 'closed stock scope must still block new risk')
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertEqual(fixture.case.native.financial_queries, 0)

    def test_daily_open_uses_verified_bounds_and_requires_an_active_instrument(self):
        fixture = self.fixture
        fixture.deploy()
        session = fixture.session()
        fixture.clock.value = session.opens_at - timedelta(microseconds=1)
        self.assertFalse(_open(fixture.engine))
        fixture.clock.value = session.opens_at
        self.assertTrue(_open(fixture.engine))
        fixture.clock.value = session.closes_at - timedelta(microseconds=1)
        self.assertTrue(_open(fixture.engine))
        fixture.clock.value = session.closes_at
        self.assertFalse(_open(fixture.engine))
        fixture.engine.disable_strategy(fixture.reference)
        fixture.clock.value = session.opens_at
        self.assertFalse(_open(fixture.engine))


class DailyOwnerStampTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native.DailyNativeFixture(self.addCleanup)
        self.bundle = public_bundle(self.fixture)

    def test_owner_grant_requires_current_connected_signed_healthy_scope(self):
        fixture, bundle = self.fixture, self.bundle
        runtime, owner, manual = fixture.runtime, bundle.sinopac_connection, bundle.manual_runtime
        self.assertEqual(len(runtime.owner_stamp()), 64)
        cases = [
            (bundle.launch, 'environment', Environment.LIVE),
            (bundle, 'engine', None),
            (bundle, 'sinopac_connection', None),
            (bundle, 'manual_runtime', None),
            (manual, 'owner', object()),
            (bundle, 'closing', True),
            (bundle, 'resources_closed', True),
            (bundle, 'control_failed', True),
            (fixture.base, 'owner_view', replace(fixture.base.owner_view, phase='DISCONNECTED')),
            (fixture.base, 'owner_view', replace(fixture.base.owner_view, environment=Environment.LIVE)),
            (owner, 'query_ready', False),
            (owner, 'shared', None),
            (manual, 'error', 'manual_account_observation_required'),
            (manual, 'stamp', ('obsolete-generation', *manual.stamp[1:])),
            (fixture.base, 'owner_view', replace(fixture.base.owner_view, accounts=())),
            (fixture.base, 'owner_view', replace(fixture.base.owner_view, accounts=fixture.base.owner_view.accounts[:1])),
            (
                fixture.base,
                'owner_view',
                replace(fixture.base.owner_view, accounts=tuple(replace(row, signed=False) for row in fixture.base.owner_view.accounts)),
            ),
        ]
        before = tuple(fixture.case.native._seen)
        for target, attribute, value in cases:
            with self.subTest(attribute=attribute, value=value), patch.object(target, attribute, value):
                with self.assertRaises(DomainError):
                    runtime.owner_stamp()
                self.assertEqual(tuple(fixture.case.native._seen), before)
        shared = SimpleNamespace(callback_errors=1)
        with patch.object(owner, 'shared', shared), patch.object(manual, 'stamp', (*manual.stamp[:3], shared)):
            with self.assertRaises(DomainError):
                runtime.owner_stamp()
        with patch.object(bundle, 'sinopac_connection', None), patch.object(manual, 'owner', None):
            with self.assertRaises(DomainError):
                runtime.owner_stamp()

    def test_owner_grant_rechecks_host_identities_after_writer_acquisition(self):
        fixture, bundle = self.fixture, self.bundle
        runtime, engine = fixture.runtime, fixture.engine
        self.assertEqual(len(runtime.owner_stamp()), 64)
        for attribute in ('engine', 'sinopac_connection', 'manual_runtime'):
            original = getattr(bundle, attribute)
            lock = engine.lock

            class ReplacementAtAcquire:
                def __enter__(self):
                    lock.__enter__()
                    setattr(bundle, attribute, object())

                def __exit__(self, *args):
                    return lock.__exit__(*args)

            try:
                with self.subTest(attribute=attribute), patch.object(engine, 'lock', ReplacementAtAcquire()):
                    with self.assertRaises(DomainError):
                        runtime.owner_stamp()
            finally:
                setattr(bundle, attribute, original)

    def test_owner_grant_identity_covers_generation_revision_and_selected_accounts(self):
        fixture, bundle = self.fixture, self.bundle
        runtime, owner, manual = fixture.runtime, bundle.sinopac_connection, bundle.manual_runtime
        original = runtime.owner_stamp()
        view = fixture.base.owner_view
        for field, changed in (('generation', 'new-login'), ('revision', view.revision + 1)):
            changed_view = replace(view, **{field: changed})
            stamp = changed_view.generation, changed_view.revision, tuple(sorted(owner.selected)), owner.shared
            with self.subTest(field=field), patch.object(fixture.base, 'owner_view', changed_view), patch.object(manual, 'stamp', stamp):
                self.assertNotEqual(runtime.owner_stamp(), original)
        selected = (owner.selected[0],)
        with patch.object(owner, 'selected', selected), patch.object(manual, 'stamp', (view.generation, view.revision, selected, owner.shared)):
            self.assertNotEqual(runtime.owner_stamp(), original)

    def test_owner_grant_collects_authenticated_facts_with_writer_and_owner_locked(self):
        fixture, bundle = self.fixture, self.bundle
        engine, owner = fixture.engine, bundle.sinopac_connection
        observed = []

        def snapshot():
            observed.append((getattr(engine.lock._local, 'depth', 0) > 0, owner.lock._is_owned()))
            return fixture.base.owner_view

        with patch.object(owner, 'snapshot', snapshot):
            fixture.runtime.owner_stamp()
        self.assertEqual(observed, [(True, True)])


class DailyRouteGuardTests(unittest.TestCase):
    """Negative cache/control inputs isolate routing; native happy paths stay above."""

    def healthy(self):
        fixture = native.DailyNativeFixture(self.addCleanup)
        public_bundle(fixture)
        fixture.deploy()
        fixture.start()
        return fixture

    def waiting(self):
        fixture = self.healthy()
        fixture.close()
        fixture.close_other_accounts()
        return fixture

    def test_route_rejects_each_incomplete_connection_account_permission_or_reconciliation_fact(self):
        for field in ('connected', 'account_ready', 'permission_ready', 'reconciled'):
            fixture = self.healthy()
            facts = replace(sinopac_preflight_facts(fixture.bundle, fixture.account_ref), **{field: False})
            with self.subTest(field=field), patch('quantlab.trading.runtime.daily_automatic.sinopac_preflight_facts', return_value=facts):
                self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
            self.assertTrue(fixture.engine.state.automatic.auto_paused)
            self.assertIn('preflight_reconciliation', fixture.engine.state.automatic.reasons)

    def test_running_route_pauses_when_current_market_or_service_fails(self):
        for field in ('realtime', 'service_open'):
            fixture = self.healthy()
            facts = replace(sinopac_preflight_facts(fixture.bundle, fixture.account_ref), **{field: False})
            with self.subTest(field=field), patch('quantlab.trading.runtime.daily_automatic.sinopac_preflight_facts', return_value=facts):
                self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
            self.assertTrue(fixture.engine.state.automatic.auto_paused)

    def test_waiting_route_keeps_authority_without_using_incomplete_current_cache_as_preflight(self):
        fixture = self.waiting()
        fixture.refresh(fixture.next_session().opens_at + timedelta(minutes=1), stock_price=D('12'))
        facts = replace(sinopac_preflight_facts(fixture.bundle, fixture.account_ref), reconciled=False)
        before = fixture.placed()
        with patch('quantlab.trading.runtime.daily_automatic.sinopac_preflight_facts', return_value=facts):
            self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertTrue(fixture.engine.state.automatic.daily.waiting_session)
        self.assertFalse(fixture.engine.state.preflight_blocks)
        self.assertEqual(fixture.placed(), before)

    def test_closed_wait_does_not_seal_an_incomplete_or_stale_worker_cache(self):
        for stale in (False, True):
            fixture = self.waiting()
            if stale:
                fixture.clock.value += timedelta(seconds=31)
            else:
                fixture.engine.manual_observations = {fixture.account_ref: fixture.engine.manual_observations[fixture.account_ref]}
            with self.subTest(stale=stale):
                self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
            self.assertFalse(fixture.engine.state.automatic.auto_paused)
            self.assertTrue(fixture.engine.state.automatic.daily.waiting_session)

    def test_closed_no_batch_pump_seals_actual_post_close_observation(self):
        fixture = self.healthy()
        close = fixture.session().closes_at
        fixture.refresh(close - timedelta(seconds=1))
        fixture.clock.value = close
        observe_daily(fixture.engine, fixture.minutes())
        self.assertFalse(any(row.account_ref == fixture.account_ref for row in fixture.engine.state.daily_account_closes))
        fixture.adopt(close + timedelta(seconds=1))
        self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertTrue(any(row.account_ref == fixture.account_ref for row in fixture.engine.state.daily_account_closes))

    def test_open_resource_failure_is_waitable_only_for_a_preserved_wait_and_capability_error(self):
        fixture = self.healthy()
        with patch('quantlab.trading.runtime.daily_automatic.sinopac_preflight_facts', side_effect=DomainError('capability_missing')):
            self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        fixture = self.waiting()
        fixture.refresh(fixture.next_session().opens_at + timedelta(minutes=1))
        with patch('quantlab.trading.runtime.daily_automatic.sinopac_preflight_facts', side_effect=DomainError('journal_failed')):
            self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertIn('journal_failed', fixture.engine.state.automatic.reasons)

    def test_open_preserved_wait_accepts_resource_refresh_delay_without_resuming_or_sending(self):
        fixture = self.waiting()
        fixture.refresh(fixture.next_session().opens_at + timedelta(minutes=1))
        before = fixture.placed()
        with patch('quantlab.trading.runtime.daily_automatic.sinopac_preflight_facts', side_effect=DomainError('capability_missing')):
            self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertTrue(fixture.engine.state.automatic.daily.waiting_session)
        self.assertEqual(fixture.placed(), before)

    def test_paused_route_does_not_replace_its_reason_with_missing_run_error(self):
        fixture = self.healthy()
        automatic.pause_automatic(fixture.engine, 'user_stop')
        reasons = fixture.engine.state.automatic.reasons
        self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertEqual(fixture.engine.state.automatic.reasons, reasons)

    def test_legacy_ungranted_control_state_cannot_look_like_a_running_route(self):
        fixture = self.healthy()
        state = fixture.engine.state
        fixture.engine._persist(
            'legacy_ungranted_control_fixture', replace(state, automatic=replace(state.automatic, daily=replace(state.automatic.daily, authorized_run='')))
        )
        self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertIn('daily_signal_not_authorized', fixture.engine.state.automatic.reasons)

    def test_route_explains_unknown_durable_orders_and_manual_requests_before_using_cached_reports(self):
        from quantlab.trading.domain.models import OrderStatus

        for request_unknown in (False, True):
            fixture = self.healthy()
            state = fixture.engine.state
            if request_unknown:
                requests = (replace(state.manual_requests[0], outcome_known=False, status='UNKNOWN'), *state.manual_requests[1:])
                changed = replace(state, manual_requests=requests)
            else:
                changed = replace(state, orders=(replace(state.orders[0], status=OrderStatus.UNKNOWN), *state.orders[1:]))
            fixture.engine._persist('unknown_outbox_control_fixture', changed)
            with self.subTest(request_unknown=request_unknown):
                self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
            self.assertIn('order_result_unknown', fixture.engine.state.automatic.reasons)

    def test_route_explains_an_obsolete_run_grant_before_attempting_daily_save(self):
        fixture = self.healthy()
        state = fixture.engine.state
        fixture.engine._persist(
            'obsolete_run_owner_fixture', replace(state, automatic=replace(state.automatic, daily=replace(state.automatic.daily, owner_stamp='obsolete-owner')))
        )
        self.assertFalse(route_daily(fixture.runtime, fixture.engine, ()))
        self.assertIn('state_conflict', fixture.engine.state.automatic.reasons)

    def test_pure_open_ignores_legacy_strategies_and_empty_lots_but_keeps_owned_instruments(self):
        fixture = self.healthy()
        record = fixture.engine.strategy(fixture.reference)
        projection = SimpleNamespace(
            clock=fixture.clock,
            calendar=fixture.engine.calendar,
            catalog=fixture.engine.catalog,
            state=replace(fixture.engine.state, strategies=(replace(record, parameters=None),), positions=()),
        )
        self.assertFalse(_open(projection))
        projection.state = replace(projection.state, strategies=())
        future = fixture.case.spec
        projection.state = replace(projection.state, positions=(SimpleNamespace(instrument_id=future.instrument_id, quantity=0),))
        self.assertFalse(_open(projection))
        projection.state = replace(projection.state, positions=(SimpleNamespace(instrument_id=future.instrument_id, quantity=1),))
        self.assertTrue(_open(projection))


class BuiltDailyRuntimeTests(unittest.TestCase):
    def test_build_runtime_shared_native_fop_callback_reaches_daily_save_without_marketwatch_tmf(self):
        fixture = built_fixtures.ManualRuntimeIntegrationTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        bundle, clock = fixture.bundle, fixture.clock
        owner = bundle.sinopac_connection
        owner.shared.facade._module.QuoteType = QuoteType
        owner.shared.facade._module.QuoteVersion = QuoteVersion
        owner.publish(accounts=(SinopacAccountView(fixture.alias, '***offline-fixture', fixture.spec.market, True, True),))
        calendar = calendar_for_instrument(fixture.resources.calendar, fixture.spec)
        clock.value = calendar.day_session(clock.now().date()).opens_at
        spec = replace(fixture.spec, effective_at=calendar.sessions[0].opens_at)
        fixture.spec = spec
        fixture.resources = replace(
            fixture.resources,
            calendar=calendar,
            catalog=Catalog((spec,)),
            bindings=(replace(fixture.resources.bindings[0], spec=spec),),
            margin_source='BROKER_VERIFIED_OFFLINE_FIXTURE',
        )

        def resources(_owner, _reference):
            value = fixture.resources
            return replace(
                value,
                capabilities=tuple(replace(row, checked_at=clock.now(), expires_at=clock.now() + timedelta(hours=8)) for row in value.capabilities),
                limits=tuple(replace(row, observed_at=clock.now()) for row in value.limits),
            )

        owner.resource_factory = resources
        fixture.ready()
        prepared = fixture.request(Operation.COMMAND, fixture.command(UiAction.TEST_SIM_ORDER))
        self.assertTrue(prepared.receipt.accepted, prepared.receipt)
        preview = prepared.state.manual.preview
        form = ManualOrderForm(
            preview.scope,
            preview.request_id,
            preview.instrument_id,
            preview.side,
            preview.quantity,
            preview.limit_price,
            preview.stop_price,
            preview.purpose,
            True,
            preview.preview_id,
        )
        result = fixture.request(Operation.COMMAND, fixture.command(UiAction.TEST_SIM_ORDER, manual_order=form))
        self.assertTrue(result.receipt.accepted, result.receipt)
        bundle.poll_ports()
        self.assertEqual(fixture.state().manual.test_status, 'PASSED')
        engine = bundle.engine
        engine.research_runner.close()
        engine.research_runner = None  # Use the supported synchronous real research producer in this composition smoke.
        engine.history = synthetic_history(engine.catalog, engine.calendar)
        form = StrategyForm(
            'built-daily-fop',
            spec.market,
            HoldingKind.CUSTOM,
            0,
            10,
            Side.BUY,
            spec.instrument_id,
            fixture.alias,
            Environment.BROKER_SIMULATION,
            D('40000'),
            D('.02'),
            'BUY_AND_HOLD',
        )
        reference = engine.create_strategy(form, StrategyParameters('1d', D('.001'), D('40000')))
        with engine.lock:
            engine.validate_strategy(reference)
            run_research(engine, reference, engine.history[spec.instrument_id])
            engine.deploy(reference)
            record_preflight(engine, fixture.alias, sinopac_preflight_facts(bundle, fixture.alias))
        receipt = bundle.execute(fixture.command(UiAction.AUTO_RESUME))
        self.assertTrue(receipt.accepted, receipt)
        bundle.poll_ports()
        self.assertEqual(bundle.manual_runtime.automatic_subscription, (spec.instrument_id,))
        callback = next(row[1][0] for row in fixture.native._seen if row[0] == 'set_on_tick_fop_v1_callback')
        session = calendar_for_instrument(engine.calendar, spec).day_session(engine.state.trading_day)
        before = sum(row[0] == 'place_order' for row in fixture.native._seen)
        for minute in range((session.closes_at - session.opens_at) // timedelta(minutes=1)):
            clock.value = session.opens_at + timedelta(minutes=minute, seconds=10)
            callback('TAIFEX', SimpleNamespace(code='TMFL6', datetime=clock.now(), close=25000, volume=1))
        clock.value = session.closes_at - timedelta(seconds=1)
        bundle.poll_ports()
        clock.value = session.closes_at
        bundle.pump()
        self.assertEqual(len(engine.state.automatic.daily.intents), 1, engine.state.automatic)
        intent = engine.state.automatic.daily.intents[0]
        self.assertEqual((intent.cursor.strategy_id, intent.phase), (engine.strategy(reference).strategy_id, 'READY'))
        self.assertTrue(bundle.automatic_runtime.future_minutes[spec.instrument_id].bar.final)
        self.assertNotIn(spec.instrument_id, bundle.market_terminal._minutes)
        self.assertEqual(sum(row[0] == 'place_order' for row in fixture.native._seen), before)
        self.assertEqual(fixture.native.financial_queries, 0)
        observe_daily(engine, ())
        self.assertEqual(len(engine.state.automatic.daily.intents), 1)


if __name__ == '__main__':
    unittest.main()
