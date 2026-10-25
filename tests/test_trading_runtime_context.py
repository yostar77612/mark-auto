"""Real owned IPC contexts with explicitly synthetic fault ports, never broker QA."""

from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import tempfile
from threading import Event
import time as elapsed
import unittest
from unittest.mock import patch

from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.broker_settings import BrokerSettings
from quantlab.trading.application.codec import dumps
from quantlab.trading.application.contracts import SettingsForm, UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, Market, Quote
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import RemoteSnapshot
from quantlab.trading.runtime.bootstrap import WallClock, build_runtime
from quantlab.trading.runtime.build import synthetic_catalog
from quantlab.trading.runtime.config import AccountMapping, InstrumentMapping, RuntimeLaunch, load_profile, load_resources
from quantlab.trading.runtime.ipc import IpcFacade, read_session
from quantlab.trading.runtime.protocol import Operation
from quantlab.trading.runtime.server import serve

D = Decimal
WORKSPACE = Path(__file__).resolve().parents[2]


def profile_fixture(root: Path, environment: Environment) -> Path:
    initialize()
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    days = tuple(now.date() + timedelta(days=n) for n in (-2, -1, 0, 1, 2))
    calendar = TradingCalendar(
        'TEST_ONLY_CALENDAR',
        'test-v1',
        'SYNTHETIC_TEST_NOT_EXCHANGE',
        tuple(TradingSession(day, datetime.combine(day, time.min, timezone.utc), datetime.combine(day, time(23, 59, 59), timezone.utc)) for day in days),
    )
    spec = replace(synthetic_catalog().instruments[0], calendar_id=calendar.calendar_id, source='SYNTHETIC_TEST_NOT_BROKER')
    capabilities = (
        CapabilitySnapshot(
            'test-stock',
            environment,
            frozenset((Market.STOCK,)),
            False,
            False,
            False,
            True,
            False,
            'SYNTHETIC_FAULT_PORT_NOT_BROKER',
            now - timedelta(seconds=1),
            now + timedelta(days=1),
            'test-cap-v1',
        ),
    )
    values = {
        'catalog': (InstrumentMapping(spec, 'SYNTHETIC-STOCK'),),
        'calendar': calendar,
        'fees': FeeSchedule(version='test-cost-v1'),
        'accounts': (AccountMapping('test-stock', 'SYNTHETIC-ACCOUNT', 'STOCK'),),
        'capabilities': capabilities,
    }
    refs = []
    for kind, value in values.items():
        path = root / (kind + '.json')
        raw = json.dumps({'schema_version': 2, 'kind': kind, 'payload': dumps(value)}).encode()
        path.write_bytes(raw)
        refs.append({'kind': kind, 'path': str(path), 'sha256': sha256(raw).hexdigest()})
    settings = BrokerSettings(
        environment=environment,
        stock_account_ref='test-stock',
        account_mapping_ref=str(root / 'accounts.json'),
        instrument_spec_ref=str(root / 'catalog.json'),
        calendar_ref=str(root / 'calendar.json'),
        fee_schedule_ref=str(root / 'fees.json'),
        capability_proof_ref=str(root / 'capabilities.json'),
    )
    path = root / 'profile.json'
    path.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'profile_alias': settings.profile_alias,
                'environment': environment.value,
                'stock_account_ref': 'test-stock',
                'futures_account_ref': '',
                'stock_allocation': '100000',
                'futures_allocation': '0',
                'settings_payload': dumps(settings),
                'resources': refs,
            }
        ),
        encoding='utf-8',
    )
    return path


class FaultQueryGateway:
    """Synthetic port that actually disconnects once; no real SDK or credentials."""

    def __init__(self, resources, root):
        self.resources, self.root = resources, root
        self.calls = 0
        self.subscriptions = {}

    def trace(self, label):
        with (self.root / 'fault-port.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'call': label, 'environment': self.resources.profile.configuration.environment.value}) + '\n')

    def inspect(self, account_ref):
        return next(c for c in self.resources.capabilities if c.account_ref == account_ref)

    def snapshot(self, account_ref):
        self.trace('snapshot')
        return AccountSnapshot(
            account_ref,
            self.resources.profile.configuration.environment,
            D('100000'),
            D('100000'),
            D('100000'),
            D('100000'),
            D('0'),
            D('0'),
            datetime.now(timezone.utc),
            0,
        )

    def events(self, account_ref, after_sequence=0):
        self.calls += 1
        self.trace('events_fault' if self.calls == 1 else 'events_recovered')
        if self.calls == 1:
            raise DomainError('outcome_unknown', 'synthetic query disconnection')
        return ()

    def refresh(self, account_ref):
        self.trace('refresh')
        return RemoteSnapshot(self.snapshot(account_ref), (), (), 0, datetime.now(timezone.utc))

    def latest(self, instrument_id):
        now = datetime.now(timezone.utc)
        self.trace('quote')
        return Quote(instrument_id, D('10'), D('10.05'), D('10'), now, now, now.date(), source='SYNTHETIC_FAULT_PORT_NOT_BROKER')

    def submit(self, *args):
        self.trace('FORBIDDEN_SUBMIT')
        raise AssertionError('read-only host must never submit')

    def cancel(self, *args):
        self.trace('FORBIDDEN_CANCEL')
        raise AssertionError('read-only host must never cancel')

    def disconnect(self):
        self.trace('disconnect')


def fault_factory(launch, resources):
    journal = Ledger(launch.root / 'fault-engine-v2.sqlite', 'fault-test-engine', datetime.now(timezone.utc))
    try:
        gateway = FaultQueryGateway(resources, launch.root)
        engine = TradingEngine(
            journal,
            WallClock(),
            resources.calendar,
            resources.catalog,
            {'test-stock': gateway},
            configuration=resources.profile.configuration,
            fees=resources.fees,
        )
        engine._persist(
            'synthetic_fault_port_context',
            replace(
                engine.state,
                settings=SettingsForm(resources.profile.stock_allocation, resources.profile.futures_allocation, D('0.02')),
                broker_settings=resources.profile.settings,
            ),
        )
        return engine
    except BaseException:
        journal.close()
        raise


def failing_factory(launch, resources):
    raise DomainError('outcome_unknown', 'injected connection failure before adoption')


def stalled_factory(launch, resources):
    elapsed.sleep(10)  # Only a test-owned daemon thread; no SDK or credentials.
    return fault_factory(launch, resources)


class StalledQueryGateway(FaultQueryGateway):
    def events(self, account_ref, after_sequence=0):
        self.trace('query_stall_started')
        elapsed.sleep(10)
        return ()


def stalled_query_factory(launch, resources):
    engine = fault_factory(launch, resources)
    engine.gateways = {'test-stock': StalledQueryGateway(resources, launch.root)}
    return engine


def serve_fixture(root, environment, profile, failure):
    factory = stalled_factory if failure == 'stall' else stalled_query_factory if failure == 'query-stall' else failing_factory if failure else fault_factory
    serve(root, launch=RuntimeLaunch(root, environment, profile, 'test-stock'), engine_factory=factory)


class RuntimeContextConfigurationTests(unittest.TestCase):
    def setUp(self):
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='runtime-context-', dir=WORKSPACE / 't')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_profile_resources_are_typed_pinned_and_preserve_one_budget(self):
        path = profile_fixture(self.root / 'bundle', Environment.LIVE)
        profile = load_profile(path, Environment.LIVE)
        resources = load_resources(profile)
        self.assertEqual(profile.stock_allocation + profile.futures_allocation, D('100000'))
        self.assertEqual(resources.accounts[0].sdk_account_id, 'SYNTHETIC-ACCOUNT')
        self.assertTrue(profile.configuration.read_only)
        self.assertFalse(profile.configuration.live_execution_enabled)
        resource = profile.resources[0].path
        resource.write_bytes(resource.read_bytes() + b' ')
        with self.assertRaises(DomainError) as raised:
            load_resources(profile)
        self.assertEqual(raised.exception.code, 'capability_missing')

    def test_profile_unknown_fields_duplicate_keys_scope_and_environment_fail_closed(self):
        path = profile_fixture(self.root / 'bundle', Environment.BROKER_SIMULATION)
        original = path.read_text(encoding='utf-8')
        body = json.loads(original)
        variants = [
            original[:-1] + ',"schema_version":1}',
            json.dumps({**body, 'unexpected': True}),
            json.dumps({**body, 'stock_allocation': '100001'}),
            json.dumps({**body, 'stock_allocation': 100000.0}),
        ]
        for text in variants:
            path.write_text(text, encoding='utf-8')
            with self.subTest(text=text[:40]), self.assertRaises(DomainError):
                load_profile(path)
        path.write_text(original, encoding='utf-8')
        with self.assertRaises(DomainError):
            load_profile(path, Environment.LIVE)

    def test_unconfigured_boot_is_durable_readiness_without_calendar_sdk_or_financial_facts(self):
        launch = RuntimeLaunch(self.root / 'unconfigured', Environment.LIVE, account_ref='explicit-unconfigured-alias')
        with patch('quantlab.trading.runtime.broker.ShioajiClientFactory.create', side_effect=AssertionError('no SDK construction on startup')):
            bundle = build_runtime(launch)
            self.addCleanup(bundle.close)
            before = bundle.snapshot()
            self.assertIsNone(before.daily_pnl)
            self.assertIsNone(before.remaining_risk)
            self.assertFalse(before.financial_facts_verified)
            self.assertEqual(before.quote_status, 'NO_DATA')
            self.assertEqual(before.positions, ())
            checked = bundle.execute(UiCommand(UiAction.CHECK_READINESS, before.version))
            self.assertTrue(checked.accepted)
            self.assertFalse(bundle.snapshot().broker_readiness.external_verified)
            rejected = bundle.execute(UiCommand(UiAction.FLATTEN, bundle.snapshot().version, target_id='unknown'))
            self.assertFalse(rejected.accepted)
            self.assertEqual(rejected.code, 'capability_missing')

    def test_uncommitted_metadata_is_not_published(self):
        bundle = build_runtime(RuntimeLaunch(self.root / 'disk', Environment.BROKER_SIMULATION, account_ref='selected-alias'))
        self.addCleanup(bundle.close)
        before = bundle.snapshot()
        with patch.object(bundle.facade.journal, 'append', side_effect=OSError('synthetic disk failure')):
            result = bundle.execute(UiCommand(UiAction.CHECK_READINESS, before.version))
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, 'journal_failed')
        self.assertIsNone(bundle.facade.state.readiness)

    def test_timeout_and_stop_discard_late_completion_and_close_only_owned_candidate(self):
        for cancel in ('timeout', 'stop'):
            with self.subTest(cancel=cancel):
                folder = self.root / cancel
                profile = profile_fixture(folder / 'bundle', Environment.BROKER_SIMULATION)
                entered, release = Event(), Event()

                def controlled_factory(launch, resources):
                    candidate = fault_factory(launch, resources)
                    entered.set()
                    release.wait(5)
                    return candidate

                bundle = build_runtime(
                    RuntimeLaunch(folder / 'engine', Environment.BROKER_SIMULATION, profile, 'test-stock'), engine_factory=controlled_factory
                )
                bundle.connect_timeout = 0.05 if cancel == 'timeout' else 8.0
                try:
                    start = bundle.snapshot()
                    receipt = bundle.connect_read_only(UiCommand(UiAction.CONNECT_READ_ONLY, start.version))
                    self.assertEqual(receipt.code, 'connection_pending')
                    self.assertTrue(entered.wait(2))
                    if cancel == 'timeout':
                        elapsed.sleep(0.1)
                        self.assertEqual(bundle.snapshot().engine_state, 'DISCONNECTED')
                    else:
                        state = bundle.snapshot()
                        started = elapsed.monotonic()
                        self.assertTrue(bundle.execute(UiCommand(UiAction.STOP_NEW, state.version)).accepted)
                        self.assertLess(elapsed.monotonic() - started, 1)
                    release.set()
                    for worker in tuple(bundle.connection_threads):
                        worker.join(3)
                    self.assertFalse(bundle.connection_threads)
                    self.assertIsNone(bundle.engine, 'cancelled or expired completion cannot promote')
                    self.assertEqual(bundle.snapshot().engine_state, 'DISCONNECTED')
                    path = folder / 'engine/fault-engine-v2.sqlite'
                    moved = path.with_suffix('.closed')
                    path.rename(moved)
                    moved.rename(path)
                finally:
                    release.set()
                    for worker in tuple(bundle.connection_threads):
                        worker.join(3)
                    bundle.close()

    def test_failed_public_stamp_freezes_commands_without_declaring_healthy_trade_journal_failed(self):
        profile = profile_fixture(self.root / 'bundle', Environment.BROKER_SIMULATION)
        bundle = build_runtime(RuntimeLaunch(self.root / 'engine', Environment.BROKER_SIMULATION, profile, 'test-stock'), engine_factory=fault_factory)
        try:
            before = bundle.snapshot()
            self.assertTrue(bundle.connect_read_only(UiCommand(UiAction.CONNECT_READ_ONLY, before.version)).accepted)
            for worker in tuple(bundle.connection_threads):
                worker.join(3)
            self.assertIsNotNone(bundle.engine)
            published = bundle.snapshot()
            bundle.engine._persist('test_domain_transition', replace(bundle.engine.state, stopped=False))
            with patch.object(bundle.version_journal, 'append', side_effect=OSError('injected stamp disk failure')):
                with self.assertRaises(DomainError) as raised:
                    bundle.snapshot()
            self.assertEqual(raised.exception.code, 'journal_failed')
            self.assertTrue(bundle.control_failed)
            self.assertTrue(bundle.engine.state.stopped)
            self.assertFalse(bundle.engine.storage_failed, 'control failure cannot disable a healthy protection journal')
            refused = bundle.execute(UiCommand(UiAction.RESUME, published.version))
            self.assertFalse(refused.accepted)
            self.assertEqual(refused.code, 'journal_failed')
            bundle.engine._persist('test_protective_journal_still_healthy', bundle.engine.state)
            self.assertEqual(bundle.engine.journal.replay()[-1].kind, 'test_protective_journal_still_healthy')
            launch = bundle.launch
            bundle.close()
            restarted = build_runtime(launch, engine_factory=fault_factory)
            try:
                fresh = restarted.snapshot()
                self.assertGreater(fresh.version, published.version)
                old_command = restarted.execute(UiCommand(UiAction.STOP_NEW, published.version))
                self.assertFalse(old_command.accepted)
                self.assertEqual(old_command.code, 'state_conflict')
                self.assertEqual(fresh.engine_state, 'DISCONNECTED')
                self.assertFalse(fresh.financial_facts_verified)
            finally:
                restarted.close()
        finally:
            bundle.close()


class OwnedBrokerTagHostTests(unittest.TestCase):
    """Broker environment tags over synthetic ports are not external validation."""

    def setUp(self):
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='owned-context-ipc-', dir=WORKSPACE / 't')
        self.root = Path(self.temp.name)
        self.processes = []

    def tearDown(self):
        for process, facade in self.processes:
            if process.is_alive():
                try:
                    state = facade.snapshot()
                    facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, state.version))
                finally:
                    process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(3)
            self.assertFalse(process.is_alive(), 'only this test-owned host must finish')
            process.close()
        self.temp.cleanup()

    def start(self, root, environment, profile, *, failure=False):
        process = multiprocessing.get_context('spawn').Process(target=serve_fixture, args=(root, environment, profile, failure))
        process.start()
        facade = IpcFacade(root, environment=environment, account_ref='test-stock')
        self.processes.append((process, facade))
        deadline = elapsed.monotonic() + 15
        while elapsed.monotonic() < deadline:
            if not process.is_alive():
                self.fail('owned host exited before authenticated readiness')
            try:
                if read_session(root).process_id == process.pid:
                    facade.snapshot()
                    return process, facade
            except (OSError, ValueError, DomainError):
                pass
            elapsed.sleep(0.05)
        self.fail('owned host did not start within 15 seconds')

    def wait_connected(self, facade):
        deadline = elapsed.monotonic() + 8
        while elapsed.monotonic() < deadline:
            state = facade.snapshot()
            if state.engine_state not in ('CONNECTING', 'DISCONNECTED'):
                return state
            elapsed.sleep(0.05)
        self.fail('synthetic connector never promoted to the actual application core')

    def test_both_broker_tags_use_authenticated_ipc_and_actual_fault_pump_without_ordering(self):
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            with self.subTest(environment=environment):
                folder = self.root / environment.value
                profile = profile_fixture(folder / 'bundle', environment)
                process, facade = self.start(folder / 'engine', environment, profile)
                initial = facade.snapshot()
                self.assertEqual(initial.engine_state, 'DISCONNECTED')
                self.assertFalse((folder / 'engine/fault-port.jsonl').exists())
                connected = facade.execute(UiCommand(UiAction.CONNECT_READ_ONLY, initial.version))
                self.assertTrue(connected.accepted, connected)
                deadline = elapsed.monotonic() + 8
                trace = folder / 'engine/fault-port.jsonl'
                while elapsed.monotonic() < deadline:
                    if trace.exists() and 'events_recovered' in trace.read_text(encoding='utf-8'):
                        break
                    elapsed.sleep(0.05)
                content = trace.read_text(encoding='utf-8')
                self.assertIn('events_fault', content)
                self.assertIn('events_recovered', content)
                self.assertNotIn('FORBIDDEN_', content)
                observed = facade.snapshot()
                self.assertEqual(observed.environment, environment)
                self.assertFalse(observed.financial_facts_verified)
                self.assertEqual(observed.orders, ())
                facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, observed.version))
                process.join(10)
                self.assertEqual(process.exitcode, 0)

    def test_fresh_unconfigured_process_registers_nested_dtos_without_loading_any_profile(self):
        folder = self.root / 'no-profile'
        _, facade = self.start(folder, Environment.LIVE, None)
        state = facade.snapshot()
        self.assertEqual(state.engine_state, 'DISCONNECTED')
        self.assertEqual(state.environment, Environment.LIVE)
        self.assertIsNone(state.daily_pnl)
        self.assertFalse(state.financial_facts_verified)
        self.assertFalse((folder / 'fault-engine-v2.sqlite').exists())
        receipt = facade.execute(UiCommand(UiAction.CHECK_READINESS, state.version))
        self.assertTrue(receipt.accepted)
        self.assertFalse(facade.snapshot().broker_readiness.external_verified)

    def test_promoted_host_restart_never_reuses_a_published_version_and_old_command_is_rejected(self):
        environment = Environment.BROKER_SIMULATION
        profile = profile_fixture(self.root / 'bundle', environment)
        engine_root = self.root / 'engine'
        process, facade = self.start(engine_root, environment, profile)
        initial = facade.snapshot()
        self.assertTrue(facade.execute(UiCommand(UiAction.CONNECT_READ_ONLY, initial.version)).accepted)
        published = self.wait_connected(facade)
        stale = UiCommand(UiAction.STOP_NEW, published.version)
        self.assertTrue(facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, published.version)).accepted)
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        _, restarted = self.start(engine_root, environment, profile)
        fresh = restarted.snapshot()
        self.assertGreater(fresh.version, published.version)
        self.assertEqual(fresh.engine_state, 'DISCONNECTED')
        rejected = restarted.execute(stale)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.code, 'state_conflict')

    def test_failed_connection_keeps_metadata_settings_and_unknown_financial_state(self):
        environment = Environment.LIVE
        profile = profile_fixture(self.root / 'bundle', environment)
        _, facade = self.start(self.root / 'engine', environment, profile, failure=True)
        before = facade.snapshot()
        result = facade.execute(UiCommand(UiAction.CONNECT_READ_ONLY, before.version))
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, 'connection_pending')
        deadline = elapsed.monotonic() + 3
        while facade.snapshot().engine_state == 'CONNECTING' and elapsed.monotonic() < deadline:
            elapsed.sleep(0.05)
        after = facade.snapshot()
        self.assertEqual(after.engine_state, 'DISCONNECTED')
        self.assertEqual(after.broker_settings, before.broker_settings)
        self.assertFalse(after.financial_facts_verified)
        self.assertIsNone(after.daily_pnl)

    def test_stalled_connect_does_not_block_authenticated_stop_or_owned_host_shutdown(self):
        environment = Environment.LIVE
        profile = profile_fixture(self.root / 'bundle', environment)
        process, facade = self.start(self.root / 'engine', environment, profile, failure='stall')
        initial = facade.snapshot()
        self.assertTrue(facade.execute(UiCommand(UiAction.CONNECT_READ_ONLY, initial.version)).accepted)
        pending = facade.snapshot()
        self.assertEqual(pending.engine_state, 'CONNECTING')
        started = elapsed.monotonic()
        self.assertTrue(facade.execute(UiCommand(UiAction.STOP_NEW, pending.version)).accepted)
        stopped = facade.snapshot()
        self.assertEqual(stopped.engine_state, 'DISCONNECTED')
        self.assertTrue(facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, stopped.version)).accepted)
        process.join(3)
        self.assertLess(elapsed.monotonic() - started, 3)
        self.assertEqual(process.exitcode, 0)

    def test_stalled_sdk_query_does_not_hold_core_control_lock_or_block_shutdown(self):
        environment = Environment.BROKER_SIMULATION
        profile = profile_fixture(self.root / 'bundle', environment)
        process, facade = self.start(self.root / 'engine', environment, profile, failure='query-stall')
        initial = facade.snapshot()
        self.assertTrue(facade.execute(UiCommand(UiAction.CONNECT_READ_ONLY, initial.version)).accepted)
        self.wait_connected(facade)
        trace = self.root / 'engine/fault-port.jsonl'
        deadline = elapsed.monotonic() + 3
        while elapsed.monotonic() < deadline:
            if trace.exists() and 'query_stall_started' in trace.read_text(encoding='utf-8'):
                break
            elapsed.sleep(0.05)
        self.assertIn('query_stall_started', trace.read_text(encoding='utf-8'))
        started = elapsed.monotonic()
        self.assertEqual(facade.request(Operation.METRICS).metrics.process_id, process.pid)
        state = facade.snapshot()
        self.assertFalse(state.financial_facts_verified)
        self.assertLess(elapsed.monotonic() - started, 1)
        # Stop/shutdown are explicit non-asset controls. A concurrent derived
        # mark can cause a version conflict; refresh only that known conflict.
        for action in (UiAction.STOP_NEW, UiAction.SHUTDOWN_ENGINE):
            for attempt in range(3):
                state = facade.snapshot()
                receipt = facade.execute(UiCommand(action, state.version))
                if receipt.code != 'state_conflict':
                    break
            self.assertNotEqual(receipt.code, 'state_conflict')
            if action is UiAction.SHUTDOWN_ENGINE:
                self.assertTrue(receipt.accepted, receipt)
        process.join(3)
        self.assertEqual(process.exitcode, 0)


if __name__ == '__main__':
    unittest.main()
