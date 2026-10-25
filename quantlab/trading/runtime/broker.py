"""Explicit broker composition; readiness never resolves credentials or connects."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Protocol, Callable

from quantlab.trading.adapters.shioaji import InstrumentBinding, ShioajiAdapter
from quantlab.trading.adapters.shioaji.sdk import SDKClient, SecretResolver, TradeDateResolver
from quantlab.trading.adapters.shioaji.secrets import WindowsSecretResolver
from quantlab.trading.application.broker_settings import BrokerReadiness, BrokerSettings, ReferenceMetadata, check_readiness
from quantlab.trading.application.context import Catalog, ExecutionConfiguration, ResearchRunner
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import CapabilitySnapshot, Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION, ConnectionState
from quantlab.trading.ports.interfaces import Clock
from quantlab.trading.ports.storage import Journal


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate document field')
        result[key] = value
    return result


class FilesystemReferenceInspector:
    """Hash one explicitly selected local file, never enumerate any directory."""

    def __init__(self, allowed_roots: tuple[Path, ...] = ()) -> None:
        self.allowed_roots = tuple(root.resolve() for root in allowed_roots)

    def inspect(self, reference: str) -> ReferenceMetadata:
        def invalid(reason: str) -> ReferenceMetadata:
            return ReferenceMetadata(reference, False, False, 0, '', reason)

        if not isinstance(reference, str) or not reference:
            return invalid('missing_reference')
        path = Path(reference)
        if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
            return invalid('invalid_reference')
        try:
            if self.allowed_roots and not any(path.resolve().is_relative_to(root) for root in self.allowed_roots):
                return invalid('invalid_reference')
            for ancestor in (path, *path.parents):
                info = ancestor.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
                    return invalid('invalid_reference')
            before = path.stat()
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 1024 * 1024:
                return invalid('metadata_unavailable')
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    return invalid('metadata_unavailable')
                raw = stream.read(1024 * 1024 + 1)
                after = os.fstat(stream.fileno())
            if len(raw) > 1024 * 1024 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                return invalid('metadata_unavailable')
            version = None
            if path.suffix.lower() == '.json':
                document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))
                if not isinstance(document, dict) or type(document.get('schema_version')) is not int:
                    return invalid('metadata_unavailable')
                version = document['schema_version']
            return ReferenceMetadata(reference, True, True, len(raw), sha256(raw).hexdigest(), '', version)
        except (OSError, ValueError, UnicodeError):
            return invalid('metadata_unavailable')


class BrokerClientFactory(Protocol):
    sdk_version: str
    quote_version: object

    def create(self, environment: Environment) -> SDKClient: ...


class SDKModule(Protocol):
    __version__: str
    QuoteVersion: object

    def Shioaji(self, *, simulation: bool) -> SDKClient: ...


class ShioajiClientFactory:
    """Caller explicitly imports the optional SDK; no implicit dependency loading."""

    def __init__(self, sdk_module: SDKModule) -> None:
        if sdk_module.__version__ != BROKER_SDK_VERSION:
            raise DomainError('capability_missing', 'unsupported broker SDK version')
        self.module = sdk_module
        self.sdk_version = sdk_module.__version__
        self.quote_version = getattr(sdk_module.QuoteVersion, 'v1')

    def create(self, environment: Environment) -> SDKClient:
        if environment not in (Environment.BROKER_SIMULATION, Environment.LIVE):
            raise DomainError('capability_missing', 'explicit broker environment required')
        return self.module.Shioaji(simulation=environment is Environment.BROKER_SIMULATION)


@dataclass(frozen=True)
class BrokerRuntime:
    settings: BrokerSettings
    adapter: ShioajiAdapter
    configuration: ExecutionConfiguration

    def compose_engine(
        self,
        journal: Journal,
        clock: Clock,
        calendar: TradingCalendar,
        fees: FeeSchedule,
        catalog: Catalog,
        *,
        ownership_clock: Callable[[], datetime],
        research_runner: ResearchRunner | None = None,
    ) -> TradingEngine:
        """Assemble selected typed resources without login or execution arming.

        The caller supplies validated reference contents; the metadata inspector
        does not pretend a reference is already a parsed market/cost contract.
        The factory's read-only configuration remains authoritative.
        """
        from .provenance import compute_profile

        bound = tuple(binding.spec for binding in self.adapter.bindings.values())
        if (
            not isinstance(calendar, TradingCalendar)
            or not isinstance(fees, FeeSchedule)
            or not isinstance(catalog, Catalog)
            or set(catalog.instruments) != set(bound)
        ):
            raise DomainError('capability_missing', 'explicit matching typed calendar, costs and instrument bindings required')
        return TradingEngine(
            journal,
            clock,
            calendar,
            catalog,
            {account: self.adapter for account in self.adapter.accounts},
            configuration=self.configuration,
            ownership_clock=ownership_clock,
            source_profile=compute_profile(),
            research_runner=research_runner,
            fees=fees,
        )

    def connect_read_only(self) -> ConnectionState:
        """Explicit external use only. Never called by construction or readiness."""
        if not self.configuration.read_only or self.adapter.execution_enabled:
            raise DomainError('capability_missing', 'readonly diagnostics scope required')
        return self.adapter.connect(self.settings.broker_secret_ref, self.settings.environment)

    def readiness(self, inspector: FilesystemReferenceInspector, now: datetime) -> BrokerReadiness:
        return check_readiness(self.settings, inspector, now)


def build_broker_runtime(
    settings: BrokerSettings,
    factory: BrokerClientFactory,
    clock: Clock,
    accounts: dict[str, object],
    bindings: tuple[InstrumentBinding, ...],
    capabilities: tuple[CapabilitySnapshot, ...],
    allocations: dict[str, Decimal],
    *,
    secret_resolver: SecretResolver | None = None,
    session_resolver: TradeDateResolver | None = None,
) -> BrokerRuntime:
    """Construct a genuine adapter with injected SDK, never connect or query it.

    Accounts are explicit SDK objects produced by the caller's controlled account
    mapping. Neither this factory nor readiness discovers accounts or credentials.
    The same adapter satisfies the core AccountGateway Protocol.
    """
    if not isinstance(settings, BrokerSettings) or settings.sdk_version != BROKER_SDK_VERSION or factory.sdk_version != BROKER_SDK_VERSION:
        raise DomainError('capability_missing', 'pinned SDK required')
    if not settings.read_only or settings.execution_enabled:
        raise DomainError('capability_missing', 'broker runtime starts in readonly diagnostic scope')
    expected = {value for value in (settings.stock_account_ref, settings.futures_account_ref) if value}
    if not expected or set(accounts) != expected or set(allocations) != expected or {cap.account_ref for cap in capabilities} != expected:
        raise DomainError('capability_missing', 'explicit configured account mappings required')
    client = factory.create(settings.environment)
    adapter = ShioajiAdapter(
        client,
        clock,
        settings.environment,
        accounts,
        bindings,
        capabilities,
        allocations,
        sdk_version=factory.sdk_version,
        secret_resolver=secret_resolver if secret_resolver is not None else WindowsSecretResolver(),
        read_only=True,
        execution_enabled=False,
        session_resolver=session_resolver,
        quote_version=factory.quote_version,
    )
    configuration = ExecutionConfiguration(settings.environment, settings.stock_account_ref, settings.futures_account_ref, True, False, False)
    return BrokerRuntime(settings, adapter, configuration)
