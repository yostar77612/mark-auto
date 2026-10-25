"""Reference-only readiness and the same application core through a broker port."""

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_trading_adapters as fixtures
from quantlab.trading.adapters.shioaji import InstrumentBinding
from quantlab.trading.adapters.shioaji.stock_grid import StockGridEvidence, TWD_ETF_BANDS, TWD_ETF_RULE
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.broker_settings import BrokerSettings, READINESS_CODES, READINESS_DETAILS, check_readiness
from quantlab.trading.application.codec import dumps, loads, register
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.events import reconcile
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION
from quantlab.trading.runtime.broker import FilesystemReferenceInspector, ShioajiClientFactory, build_broker_runtime
from quantlab.trading.runtime.build import synthetic_calendar

WORKSPACE = Path(__file__).resolve().parents[2]


class ClientFactory:
    sdk_version = BROKER_SDK_VERSION
    quote_version = 'synthetic-v1-enum'

    def __init__(self) -> None:
        self.created: list[Environment] = []
        self.client = fixtures.SDKDouble()

    def create(self, environment: Environment):
        self.created.append(environment)
        return self.client


class BrokerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        (WORKSPACE / 't').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='v2-broker-runtime-', dir=WORKSPACE / 't')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = fixtures.MutableClock()
        self.inspector = FilesystemReferenceInspector((self.root,))

    def complete_settings(self) -> BrokerSettings:
        refs = {}
        for name in ('account_mapping_ref', 'instrument_spec_ref', 'calendar_ref', 'fee_schedule_ref', 'capability_proof_ref'):
            path = self.root / (name + '.json')
            path.write_text('{"schema_version":2,"evidence":"synthetic test metadata only"}', encoding='utf-8')
            refs[name] = str(path)
        return BrokerSettings(stock_account_ref='test-stock', broker_secret_ref='MarkAuto/v2/broker/test-synthetic', **refs)

    def runtime(self, settings: BrokerSettings, factory: ClientFactory):
        cap = fixtures.capability(settings.environment)
        # Explicit ETF source/grid fixture for this SDK-shaped broker scope;
        # do not change the shared LOCAL simulator's scalar instrument helper.
        self.broker_spec = replace(fixtures.instrument(), price_bands=TWD_ETF_BANDS, tick_rule_id=TWD_ETF_RULE)
        grid = StockGridEvidence(
            '0050',
            'TSE',
            'TWD_ETF',
            'TW0000050004',
            'CEOGEU',
            'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2',
            self.clock.now().date().isoformat(),
            sha256(b'SYNTHETIC-BROKER-FIXTURE-NOT-A-DOWNLOADED-ISIN-SNAPSHOT').hexdigest(),
            self.clock.now(),
        )
        return build_broker_runtime(
            settings,
            factory,
            self.clock,
            {'test-stock': factory.client.account},
            (InstrumentBinding(self.broker_spec, '0050', grid),),
            (cap,),
            {'test-stock': Decimal('100000')},
        )

    def test_defaults_report_missing_external_requirements_without_any_secret_or_network(self) -> None:
        settings = BrokerSettings()
        with patch('quantlab.trading.adapters.shioaji.secrets.WindowsCredentialBackend.read', side_effect=AssertionError('must not read credentials')):
            readiness = check_readiness(settings, self.inspector, self.clock.now())
        self.assertFalse(readiness.local_ready)
        self.assertFalse(readiness.external_verified)
        self.assertTrue(settings.read_only)
        self.assertFalse(settings.execution_enabled)
        self.assertTrue(any(check.external_required and not check.passed for check in readiness.checks))
        self.assertTrue(all(check.code in READINESS_CODES and check.detail in READINESS_DETAILS for check in readiness.checks))

    def test_valid_metadata_records_hashes_but_never_grants_external_permissions(self) -> None:
        settings = self.complete_settings()
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        readiness = check_readiness(settings, self.inspector, self.clock.now())
        self.assertTrue(readiness.local_ready)
        self.assertFalse(readiness.external_verified)
        self.assertEqual(len(readiness.references), 5)
        self.assertTrue(all(len(item.sha256) == 64 and item.schema_version == 2 for item in readiness.references))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})

    def test_wrong_version_duplicate_json_and_unbounded_file_remain_not_ready(self) -> None:
        settings = self.complete_settings()
        path = Path(settings.calendar_ref)
        for payload in ('{"schema_version":1}', '{"schema_version":2,"schema_version":2}', '{"schema_version":2,"amount":NaN}', 'x' * (1024 * 1024 + 1)):
            with self.subTest(payload_length=len(payload)):
                path.write_text(payload, encoding='utf-8')
                readiness = check_readiness(settings, self.inspector, self.clock.now())
                self.assertFalse(readiness.local_ready)
                self.assertFalse(next(check.passed for check in readiness.checks if check.code == 'calendar_ref'))

    def test_relative_network_outside_scope_and_missing_paths_are_rejected(self) -> None:
        for reference in (
            'relative.json',
            r'\\unreachable-host\share\secret.json',
            str(self.root / 'absent.json'),
            str(WORKSPACE / '.repo' / 'pyproject.toml'),
        ):
            with self.subTest(reference=reference):
                self.assertFalse(self.inspector.inspect(reference).exists)

    def test_pasted_credentials_and_untagged_environment_are_refused_before_save(self) -> None:
        for values in (
            {'broker_secret_ref': 'synthetic-raw-key-not-a-ref'},
            {'certificate_secret_ref': 'synthetic-password-not-a-ref'},
            {'calendar_ref': 'synthetic-raw-key-not-a-path'},
            {'environment': 'BROKER_SIMULATION'},
            {'execution_enabled': 1},
        ):
            with self.subTest(values=tuple(values)), self.assertRaises(DomainError):
                BrokerSettings(**values)

    def test_live_certificate_is_independent_from_api_key_and_account(self) -> None:
        settings = replace(self.complete_settings(), environment=Environment.LIVE)
        report = check_readiness(settings, self.inspector, self.clock.now())
        self.assertFalse(report.local_ready)
        certificate = self.root / 'synthetic-only.pfx'
        certificate.write_bytes(b'non-secret test bytes, not a real certificate')
        settings = replace(settings, certificate_ref=str(certificate), certificate_secret_ref='MarkAuto/v2/certificate/test-synthetic')
        report = check_readiness(settings, self.inspector, self.clock.now())
        self.assertTrue(report.local_ready)
        self.assertFalse(report.external_verified)
        self.assertTrue(next(check.external_required for check in report.checks if check.code == 'external_ca_verified'))

    def test_factory_constructs_disconnected_readonly_adapter_without_login_or_credential_read(self) -> None:
        factory, settings = ClientFactory(), self.complete_settings()
        with patch('quantlab.trading.adapters.shioaji.secrets.WindowsCredentialBackend.read', side_effect=AssertionError('not automatic')):
            runtime = self.runtime(settings, factory)
        self.assertEqual(factory.created, [Environment.BROKER_SIMULATION])
        self.assertFalse(runtime.adapter.connected)
        self.assertTrue(runtime.adapter.read_only)
        self.assertFalse(runtime.adapter.execution_enabled)
        self.assertTrue(runtime.configuration.read_only)
        self.assertEqual(factory.client.placed, [])
        self.assertEqual(factory.client.order_calls, [])

    def test_factory_refuses_unsupported_version_or_execution_flags_before_client_construction(self) -> None:
        factory, settings = ClientFactory(), self.complete_settings()
        for changed in (replace(settings, sdk_version='1.7.8'), replace(settings, read_only=False), replace(settings, execution_enabled=True)):
            with self.subTest(changed=changed.sdk_version), self.assertRaises(DomainError):
                self.runtime(changed, factory)
        self.assertEqual(factory.created, [])

    def test_same_core_reconciles_broker_query_port_and_refuses_every_execution(self) -> None:
        factory = ClientFactory()
        runtime = self.runtime(self.complete_settings(), factory)
        # Known synthetic SDK-shaped transport only. No broker session exists.
        runtime.adapter.attach_authenticated()
        journal = Ledger(self.root / 'broker-core.sqlite', 'broker-simulation-test', self.clock.now())
        self.addCleanup(journal.close)
        fees = replace(FeeSchedule(), version='explicit-injected-broker-test', minimum_fee=Decimal('55'))
        calendar = synthetic_calendar()
        engine = runtime.compose_engine(
            journal,
            self.clock,
            calendar,
            fees,
            Catalog((self.broker_spec,)),
            ownership_clock=self.clock.now,
        )
        self.assertIs(engine.calendar, calendar)
        self.assertIs(engine.fees, fees)
        self.assertTrue(engine.configuration.read_only)
        reconcile(engine)
        self.assertTrue(engine.state.reconciled)
        self.assertEqual(engine.state.environment, Environment.BROKER_SIMULATION)
        self.assertEqual(engine.account('test-stock').settled_cash, Decimal('100000'))
        with self.assertRaises(DomainError):
            engine.assert_execution_allowed()
        factory.client.fail_queries = True
        with self.assertRaises(DomainError):
            reconcile(engine)
        self.assertFalse(engine.state.reconciled)
        self.assertTrue(engine.state.stopped)
        self.assertEqual(factory.client.placed, [])

    def test_reference_settings_and_readiness_save_check_restart_without_connector_side_effects(self) -> None:
        from quantlab.trading.application.contracts import UiAction, UiCommand
        from quantlab.trading.application.facade import LocalFacade
        from quantlab.trading.runtime.build import create_engine

        root = self.root / 'saved-reference-profile'
        engine = create_engine(root)
        try:
            engine.reference_inspector = self.inspector
            facade = LocalFacade(engine)
            settings = self.complete_settings()
            with patch(
                'quantlab.trading.adapters.shioaji.secrets.WindowsCredentialBackend.read', side_effect=AssertionError('readiness cannot resolve a secret')
            ):
                saved = facade.execute(UiCommand(UiAction.SAVE_BROKER_SETTINGS, engine.state.version, broker_settings=settings))
                self.assertTrue(saved.accepted, saved)
                checked = facade.execute(UiCommand(UiAction.CHECK_READINESS, engine.state.version))
                self.assertTrue(checked.accepted, checked)
            self.assertTrue(engine.state.broker_readiness.local_ready)
            self.assertFalse(engine.state.broker_readiness.external_verified)
            original_readiness = engine.state.broker_readiness
        finally:
            engine.journal.close()
            engine.simulation.ledger.close()
        restarted = create_engine(root)
        try:
            self.assertEqual(restarted.state.broker_settings, settings)
            self.assertEqual(restarted.state.broker_readiness, original_readiness)
            self.assertEqual(restarted.configuration.environment, Environment.LOCAL)
            self.assertTrue(restarted.state.stopped)
            self.assertFalse(restarted.state.reconciled)
        finally:
            restarted.journal.close()
            restarted.simulation.ledger.close()

    def test_settings_and_readiness_roundtrip_via_the_existing_typed_codec(self) -> None:
        from quantlab.trading.application import broker_settings

        register(BrokerSettings, broker_settings.ReferenceMetadata, broker_settings.ReadinessCheck, broker_settings.BrokerReadiness)
        settings = self.complete_settings()
        report = check_readiness(settings, self.inspector, self.clock.now())
        self.assertEqual(loads(dumps(settings)), settings)
        self.assertEqual(loads(dumps(report)), report)
        self.assertNotIn('synthetic-password', dumps(settings))

    def test_sdk_module_factory_requires_explicit_pinned_module_and_keeps_environment_flag(self) -> None:
        class Module:
            __version__ = BROKER_SDK_VERSION
            QuoteVersion = type('QuoteVersion', (), {'v1': 'synthetic-v1-enum'})

            def __init__(self) -> None:
                self.calls: list[bool] = []

            def Shioaji(self, *, simulation: bool):
                self.calls.append(simulation)
                return fixtures.SDKDouble()

        module = Module()
        factory = ShioajiClientFactory(module)
        self.assertEqual(module.calls, [])
        factory.create(Environment.BROKER_SIMULATION)
        factory.create(Environment.LIVE)
        self.assertEqual(module.calls, [True, False])
        module.__version__ = 'unverified'
        with self.assertRaises(DomainError):
            ShioajiClientFactory(module)


if __name__ == '__main__':
    unittest.main()
