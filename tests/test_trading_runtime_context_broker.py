"""Controlled connector assembly with injected SDK-shaped faults, never login QA."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import test_trading_adapters as fixtures
from test_trading_runtime_context import profile_fixture
from quantlab.trading.adapters.shioaji.sdk import BrokerCredentials
from quantlab.trading.adapters.shioaji.stock_grid import COMMON_STOCK_BANDS, COMMON_STOCK_RULE, StockGridEvidence
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION
from quantlab.trading.runtime.broker import connect_profile_engine
from quantlab.trading.runtime.config import AccountMapping, InstrumentMapping, RuntimeLaunch, load_profile, load_resources

WORKSPACE = Path(__file__).resolve().parents[2]


class SelectedSecrets:
    def __init__(self):
        self.references = []

    def broker_credentials(self, reference):
        self.references.append(reference)
        if reference != 'MarkAuto/v2/broker/SYNTHETIC-ONLY':
            raise AssertionError('only the explicitly selected reference may be resolved')
        return BrokerCredentials('SYNTHETIC-KEY', 'SYNTHETIC-SECRET')

    def certificate_credentials(self, reference):
        raise AssertionError('readonly bootstrap must never activate or read a CA secret')


class LoginSDKDouble(fixtures.SDKDouble):
    def __init__(self):
        super().__init__()
        self.logins = self.logouts = self.subscribes = 0
        self.fail_login = False
        self.contracts = SimpleNamespace(
            get=lambda code: SimpleNamespace(code=code, exchange='TSE', security_type='STK', region='TW'),
            info=lambda contract: SimpleNamespace(unit=1000, trading_suspended=False, currency='TWD'),
        )

    def login(self, *, api_key, secret_key, subscribe_trade):
        self.logins += 1
        if self.fail_login:
            raise TimeoutError('SYNTHETIC secret-bearing diagnostic must be sanitized')
        assert (api_key, secret_key, subscribe_trade) == ('SYNTHETIC-KEY', 'SYNTHETIC-SECRET', True)
        return [self.account]

    def logout(self):
        self.logouts += 1

    def subscribe(self, contract, *, quote_type, version):
        self.subscribes += 1


class LoginFactory:
    sdk_version = BROKER_SDK_VERSION
    quote_version = 'SYNTHETIC-v1'

    def __init__(self):
        self.client = LoginSDKDouble()
        self.created = []

    def create(self, environment):
        self.created.append(environment)
        return self.client


class ControlledBrokerBootstrapTests(unittest.TestCase):
    def setUp(self):
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='runtime-sdk-shape-', dir=WORKSPACE / 't')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def resources(self, environment):
        path = profile_fixture(self.root / 'bundle', environment)
        body = json.loads(path.read_text(encoding='utf-8'))
        settings = replace(loads(body['settings_payload']), broker_secret_ref='MarkAuto/v2/broker/SYNTHETIC-ONLY')
        body['settings_payload'] = dumps(settings)
        reference = next(ref for ref in body['resources'] if ref['kind'] == 'accounts')
        document = Path(reference['path'])
        raw = json.dumps({'schema_version': 2, 'kind': 'accounts', 'payload': dumps((AccountMapping('test-stock', '0000', 'STOCK'),))}).encode()
        document.write_bytes(raw)
        reference['sha256'] = sha256(raw).hexdigest()
        catalog_ref = next(ref for ref in body['resources'] if ref['kind'] == 'catalog')
        catalog_path = Path(catalog_ref['path'])
        old = loads(json.loads(catalog_path.read_text(encoding='utf-8'))['payload'])[0]
        now = datetime.now(timezone.utc)
        # This is synthetic source attestation for an injected SDK-shaped test;
        # its hash must never be described as a downloaded official ISIN file.
        grid = StockGridEvidence(
            '2330',
            'TSE',
            'COMMON_STOCK',
            'TW0002330008',
            'ESVUFR',
            'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2',
            now.date().isoformat(),
            sha256(b'SYNTHETIC-CLASSIFICATION-FIXTURE-NOT-DOWNLOADED').hexdigest(),
            now,
        )
        spec = replace(old.spec, exchange='TWSE', tick_size=Decimal('0.01'), tick_rule_id=COMMON_STOCK_RULE, price_bands=COMMON_STOCK_BANDS)
        catalog_raw = json.dumps({'schema_version': 2, 'kind': 'catalog', 'payload': dumps((InstrumentMapping(spec, '2330', grid),))}).encode()
        catalog_path.write_bytes(catalog_raw)
        catalog_ref['sha256'] = sha256(catalog_raw).hexdigest()
        path.write_text(json.dumps(body), encoding='utf-8')
        return path, load_resources(load_profile(path, environment))

    def test_exact_reference_and_account_mapping_construct_the_same_readonly_application_core(self):
        path, resources = self.resources(Environment.LIVE)
        launch = RuntimeLaunch(self.root / 'engine', Environment.LIVE, path, 'test-stock')
        launch.root.mkdir()
        factory, secrets = LoginFactory(), SelectedSecrets()
        engine = connect_profile_engine(launch, resources, factory=factory, secret_resolver=secrets)
        try:
            self.assertEqual(factory.created, [Environment.LIVE])
            self.assertEqual(factory.client.logins, 1, 'no duplicate login during adapter assembly')
            self.assertEqual(secrets.references, ['MarkAuto/v2/broker/SYNTHETIC-ONLY'])
            self.assertIsNone(engine.simulation)
            self.assertTrue(engine.configuration.read_only)
            self.assertFalse(engine.configuration.live_execution_enabled)
            self.assertEqual(engine.state.settings.stock_allocation, resources.profile.stock_allocation)
            self.assertEqual(engine.fees, resources.fees)
            self.assertEqual(engine.calendar, resources.calendar)
            self.assertTrue(engine.state.daily_baseline_required)
            self.assertFalse(engine.gateways['test-stock'].inspect('test-stock').can_trade)
            self.assertEqual(factory.client.placed, [])
            self.assertEqual(factory.client.order_calls, [])
            self.assertGreater(factory.client.subscribes, 0)
            self.assertEqual(engine.journal.replay()[-1].kind, 'readonly_broker_context_configured')
        finally:
            engine.research_runner.close()
            engine.gateways['test-stock'].disconnect()
            engine.journal.close()

    def test_login_timeout_is_unknown_readonly_connection_and_sanitized_without_retry(self):
        path, resources = self.resources(Environment.BROKER_SIMULATION)
        launch = RuntimeLaunch(self.root / 'engine', Environment.BROKER_SIMULATION, path, 'test-stock')
        factory = LoginFactory()
        factory.client.fail_login = True
        with self.assertRaises(DomainError) as raised:
            connect_profile_engine(launch, resources, factory=factory, secret_resolver=SelectedSecrets())
        self.assertNotIn('SYNTHETIC secret-bearing', str(raised.exception))
        self.assertEqual(raised.exception.code, 'outcome_unknown')
        self.assertEqual(factory.client.logins, 1)
        self.assertEqual(factory.client.logouts, 1, 'close only this explicit login attempt')
        self.assertEqual(factory.client.placed, [])

    def test_wrong_environment_or_unreturned_account_never_reaches_an_order(self):
        path, resources = self.resources(Environment.LIVE)
        factory = LoginFactory()
        wrong = RuntimeLaunch(self.root / 'wrong', Environment.BROKER_SIMULATION, path, 'test-stock')
        with self.assertRaises(DomainError):
            connect_profile_engine(wrong, resources, factory=factory, secret_resolver=SelectedSecrets())
        self.assertEqual(factory.created, [])
        factory.client.account.account_id = 'UNCONFIGURED'
        correct = RuntimeLaunch(self.root / 'correct', Environment.LIVE, path, 'test-stock')
        with self.assertRaises(DomainError) as raised:
            connect_profile_engine(correct, resources, factory=factory, secret_resolver=SelectedSecrets())
        self.assertEqual(raised.exception.code, 'capability_missing')
        self.assertEqual(factory.client.logins, 1)
        self.assertEqual(factory.client.logouts, 1)
        self.assertEqual(factory.client.order_calls, [])

    def test_missing_stock_grid_source_refuses_before_client_or_secret_resolution(self):
        path, resources = self.resources(Environment.BROKER_SIMULATION)
        resources = replace(resources, bindings=tuple(replace(binding, stock_grid=None) for binding in resources.bindings))
        factory, secrets = LoginFactory(), SelectedSecrets()
        launch = RuntimeLaunch(self.root / 'missing-grid', Environment.BROKER_SIMULATION, path, 'test-stock')
        with self.assertRaises(DomainError) as raised:
            connect_profile_engine(launch, resources, factory=factory, secret_resolver=secrets)
        self.assertEqual(raised.exception.code, 'instrument_unresolved')
        self.assertEqual(factory.created, [])
        self.assertEqual(secrets.references, [])
