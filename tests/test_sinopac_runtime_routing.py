"""Real bundle/dispatch boundaries with fake SDKs, no subprocess or live broker."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4
from unittest.mock import patch

from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import ContextNavigationRequest, ContextOption, UiAction, UiCommand, UiReceipt
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _dispatch
from quantlab.trading.runtime.context_client import RuntimeContextManager
from quantlab.trading.runtime.sinopac_settings import SinopacSettingsStore
from test_market_session import FakeApi, FakeSecrets
from test_alert_service import fake_sdk


class HostView:
    def __init__(self, bundle, account='sinopac-pending'):
        self.bundle, self.account = bundle, account

    def request(self, operation, command=None):
        request = Request(uuid4().hex, self.bundle.launch.environment, self.account, datetime.now(timezone.utc) + timedelta(seconds=10), operation, command)
        return _dispatch(self.bundle, request)

    def snapshot(self):
        return self.request(Operation.SNAPSHOT).state

    def execute(self, command):
        return self.request(Operation.COMMAND, command).receipt

    def symbol_directory(self):
        return self.request(Operation.SYMBOL_DIRECTORY).instruments


class ConnectionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.local = build_runtime(RuntimeLaunch(root / 'local'))
        self.addCleanup(self.local.close)
        self.calls, self.apis, self.hosts = [], {}, {}
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            api = FakeApi()
            api.list_accounts = lambda: [SimpleNamespace(account_type='S', broker_id='9A95', account_id='1234567', signed=True)]
            api.list_positions = lambda **kw: []
            api.set_on_scanner_callback = lambda callback, _api=api: _api.callbacks.update(scanner=callback)
            api.subscribe_scanner = lambda scanner, **kwargs: None
            api.unsubscribe_scanner = lambda scanner, **kwargs: None
            original_login, original_logout = api.login, api.logout

            def login(*, _env=environment, _login=original_login, **kwargs):
                self.calls.append(('login', _env))
                return _login(**kwargs)

            def logout(*, _env=environment, _logout=original_logout):
                self.calls.append(('logout', _env))
                return _logout()

            api.login, api.logout = login, logout
            self.apis[environment] = api
            module = fake_sdk()
            module.__version__ = '1.7.9'
            module.QuoteType = module.QuoteVersion = module.Unit = lambda value: value

            def factory(env, _api=api, _module=module):
                return ShioajiSDKFacade(_api, _module, environment=env)

            bundle = build_runtime(
                RuntimeLaunch(root / environment.value, environment, account_ref='sinopac-pending', sinopac=True),
                sinopac_factory=factory,
                secret_resolver=FakeSecrets(),
            )
            self.addCleanup(bundle.close)
            self.hosts[environment] = bundle

        self.selected = ('local', 'local-stock')
        self.port = SimpleNamespace(
            list_contexts=self.options,
            open_sinopac=lambda env: HostView(self.hosts[env]),
            open_context=lambda context, alias: HostView(self.hosts[Environment(context)], alias),
            persist_selection=lambda context, alias: setattr(self, 'selected', (context, alias)),
        )
        self.client = CompositeFacade(self.port, 'local', HostView(self.local, 'local-stock'))

    def options(self):
        return (
            ContextOption('local', '', Environment.LOCAL, ('local-stock', 'local-futures')),
            *(ContextOption(env.value, '', env, bundle.sinopac_connection.selected or ('sinopac-pending',)) for env, bundle in self.hosts.items()),
        )

    def command(self, action, **kwargs):
        state = self.client.snapshot()
        return UiCommand(
            action, state.version, connection_revision=state.sinopac_connection.revision, connection_generation=state.sinopac_connection.generation, **kwargs
        )

    def connect(self, environment=Environment.BROKER_SIMULATION):
        result = self.client.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings(environment)))
        self.assertTrue(result.accepted, result)
        self.hosts[environment].sinopac_connection.worker.join(3)
        self.assertEqual(self.client.snapshot().sinopac_connection.phase, 'CONNECTED')

    def test_local_first_connect_selection_and_explicit_broker_navigation_use_one_login(self):
        before = self.client.snapshot()
        self.connect()
        connected = self.client.snapshot()
        for field in ('environment', 'account_ref', 'version', 'allocated_cash', 'daily_pnl', 'remaining_risk', 'positions', 'accounts'):
            self.assertEqual(getattr(connected, field), getattr(before, field), field)
        self.assertEqual(connected.market_data_settings.environment, Environment.BROKER_SIMULATION)
        self.assertEqual(len(self.client.symbol_directory()), 3)
        alias = connected.sinopac_connection.accounts[0].alias
        self.assertTrue(self.client.execute(self.command(UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=(alias,))).accepted)
        self.hosts[Environment.BROKER_SIMULATION].sinopac_connection.worker.join(2)
        state = self.client.snapshot()
        receipt = self.client.navigate_context(
            ContextNavigationRequest('local', state.context_epoch, Environment.BROKER_SIMULATION.value, Environment.BROKER_SIMULATION, alias)
        )
        self.assertTrue(receipt.accepted, receipt)
        switched = self.client.snapshot()
        self.assertEqual(switched.account_ref, alias)
        self.assertEqual(switched.configuration_id, 'SINOPAC:BROKER_SIMULATION')
        self.assertEqual(self.calls, [('login', Environment.BROKER_SIMULATION)])
        self.assertFalse(switched.financial_facts_verified)

    def test_environment_switch_confirms_old_logout_and_public_revision_stays_monotonic(self):
        self.connect()
        previous = self.client.snapshot().sinopac_connection.revision
        self.connect(Environment.LIVE)
        self.assertEqual(self.calls, [('login', Environment.BROKER_SIMULATION), ('logout', Environment.BROKER_SIMULATION), ('login', Environment.LIVE)])
        state = self.client.snapshot()
        self.assertEqual(state.environment, Environment.LOCAL)
        self.assertGreater(state.sinopac_connection.revision, previous)

    def test_unconfirmed_logout_prevents_new_environment_login(self):
        self.connect()
        self.apis[Environment.BROKER_SIMULATION].logout = lambda: False
        receipt = self.client.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings(Environment.LIVE)))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'outcome_unknown')
        self.assertNotIn(('login', Environment.LIVE), self.calls)

    def test_independent_revision_is_not_refreshed_away_between_guard_and_dispatch(self):
        self.connect()
        alias = self.client.snapshot().sinopac_connection.accounts[0].alias
        command = self.command(UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=(alias,))
        connection, calls = self.client._connection, []
        original = connection.snapshot

        def advancing_snapshot():
            calls.append(1)
            if len(calls) == 2:
                owner = self.hosts[Environment.BROKER_SIMULATION].sinopac_connection
                with owner.lock:
                    owner.publish(error_code='account_query_failed')
            return original()

        connection.snapshot = advancing_snapshot
        receipt = self.client.execute(command)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'state_conflict')
        self.assertEqual(self.hosts[Environment.BROKER_SIMULATION].sinopac_connection.selected, ())

    def test_legacy_market_logout_precedes_new_login_without_changing_local_book(self):
        connection = self.local.market_connection
        connection.settings = MarketDataSettings(enabled=True)
        connection.status = 'CONNECTED'
        connection.session = SimpleNamespace(connected=True, disconnect=lambda: self.calls.append(('legacy_logout',)))
        self.connect()
        self.assertEqual(self.calls, [('legacy_logout',), ('login', Environment.BROKER_SIMULATION)])
        self.assertEqual(self.client.snapshot().environment, Environment.LOCAL)

    def test_unknown_legacy_logout_is_not_assumed_released_on_retry(self):
        connection = self.local.market_connection
        connection.settings = MarketDataSettings(enabled=True)
        connection.status = 'CONNECTED'
        connection.session = SimpleNamespace(connected=True, disconnect=lambda: False)
        for _ in range(2):
            receipt = self.client.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings()))
            self.assertFalse(receipt.accepted)
            self.assertEqual(receipt.code, 'outcome_unknown')
        self.assertEqual(self.calls, [])

    def test_unknown_legacy_logout_blocks_old_market_commands(self):
        connection = self.local.market_connection
        connection.settings = MarketDataSettings(enabled=True)
        connection.status = 'CONNECTED'
        connection.session = SimpleNamespace(connected=True, disconnect=lambda: False)
        receipt = self.client.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings()))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'outcome_unknown')
        with patch.object(connection, 'execute', return_value=UiReceipt(True, 'connection_pending', '')) as legacy:
            for action in (UiAction.SAVE_MARKET_DATA_SETTINGS, UiAction.CONNECT_MARKET_DATA, UiAction.DISCONNECT_MARKET_DATA):
                with self.subTest(action=action):
                    receipt = self.client.execute(self.command(action, market_data_settings=MarketDataSettings(enabled=True)))
                    self.assertFalse(receipt.accepted)
                    self.assertEqual(receipt.code, 'state_conflict')
            legacy.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_unknown_legacy_logout_blocks_profile_login_without_an_engine(self):
        from test_trading_runtime_context import profile_fixture

        root = Path(self.temp.name) / 'legacy-profile'
        profile = profile_fixture(root / 'resources', Environment.BROKER_SIMULATION)
        with patch('quantlab.trading.runtime.broker.ShioajiClientFactory.create', side_effect=AssertionError('No real SDK')):
            with patch(
                'quantlab.trading.runtime.bootstrap.connect_profile_engine', side_effect=AssertionError('No profile login after unknown logout')
            ) as factory:
                bundle = build_runtime(RuntimeLaunch(root / 'engine', Environment.BROKER_SIMULATION, profile, 'test-stock'), engine_factory=factory)
                self.addCleanup(bundle.close)
                self.assertIsNone(bundle.engine)
                self.assertIsNotNone(bundle.resources)
                connection = bundle.market_connection
                connection.settings = MarketDataSettings(enabled=True)
                connection.status = 'CONNECTED'
                connection.session = SimpleNamespace(connected=True, disconnect=lambda: False)
                host = HostView(bundle, 'test-stock')
                receipt = host.execute(UiCommand(UiAction.DISCONNECT_SINOPAC, host.snapshot().version))
                self.assertFalse(receipt.accepted)
                self.assertEqual(receipt.code, 'outcome_unknown')
                receipt = host.execute(UiCommand(UiAction.CONNECT_READ_ONLY, host.snapshot().version))
                for worker in tuple(bundle.connection_threads):
                    worker.join(2)
                self.assertFalse(receipt.accepted)
                self.assertEqual(receipt.code, 'state_conflict')
                factory.assert_not_called()
                self.assertFalse(bundle.connection_threads)


class UnifiedRegistryTests(unittest.TestCase):
    def test_explicit_broker_startup_reuses_registered_unified_account_host(self):
        for environment, expected in ((Environment.BROKER_SIMULATION, 'sinopac-simulation'), (Environment.LIVE, 'sinopac-live')):
            with self.subTest(environment=environment), TemporaryDirectory(dir=Path.cwd()) as temporary:
                manager = RuntimeContextManager(Path(temporary))
                with patch('quantlab.trading.runtime.context_client.ensure_engine') as ensure:
                    manager.open_sinopac(environment)
                    launch = ensure.call_args.kwargs['launch']
                    SinopacSettingsStore(launch.root).save(SinopacConnectionSettings(environment), ('sinopac-selected',))
                    before = manager.list_contexts()
                    restored = RuntimeContextManager(Path(temporary))
                    self.assertEqual(restored.configure_launch(environment, 'sinopac-selected', None), expected)
                    self.assertEqual(restored.list_contexts(), before)
                    self.assertEqual(restored.selected_context, 'local')
                    self.assertEqual(restored._entries[expected].expected_configuration(), 'SINOPAC:' + environment.value)
                    self.assertEqual(restored._entries[expected].launch.root, launch.root)
                    self.assertTrue(restored._entries[expected].launch.sinopac)
                    ensure.assert_called_once()
                    legacy = restored.configure_launch(environment, 'legacy-explicit-account', None)
                    self.assertFalse(restored._entries[legacy].launch.sinopac)
                    self.assertTrue(restored._entries[legacy].expected_configuration().startswith('UNCONFIGURED:'))

    def test_legacy_metadata_only_context_port_refuses_new_connect_without_throwing(self):
        from test_context_navigation_v2 import NavigationStub

        port = NavigationStub()
        client = CompositeFacade(port, 'local', port.facades['local'])
        receipt = client.execute(UiCommand(UiAction.SAVE_AND_CONNECT_SINOPAC, 90, connection_revision=0, sinopac_settings=SinopacConnectionSettings()))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'capability_missing')

    def test_generated_host_seed_is_stable_across_account_selection_and_restart(self):
        with TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            manager = RuntimeContextManager(root)
            with patch('quantlab.trading.runtime.context_client.ensure_engine') as ensure:
                manager.open_sinopac(Environment.BROKER_SIMULATION)
                launch = ensure.call_args.kwargs['launch']
                self.assertTrue(launch.sinopac)
                self.assertEqual(launch.account_ref, 'sinopac-pending')
                self.assertEqual(ensure.call_args.kwargs['configuration_id'], 'SINOPAC:BROKER_SIMULATION')
                SinopacSettingsStore(launch.root).save(SinopacConnectionSettings(), ('sinopac-first', 'sinopac-second'))
                manager.persist_selection('sinopac-simulation', 'sinopac-first')
                restored = RuntimeContextManager(root)
                view = restored.open_context('sinopac-simulation', 'sinopac-second')
                self.assertEqual(view.launch.account_ref, 'sinopac-second')
                self.assertEqual(ensure.call_args.kwargs['launch'].account_ref, 'sinopac-pending')
                self.assertEqual(restored.selected_context, 'sinopac-simulation')
                self.assertEqual(restored.selected_account, 'sinopac-first')
                self.assertEqual(restored.connection_context, 'sinopac-simulation')


if __name__ == '__main__':
    unittest.main()
