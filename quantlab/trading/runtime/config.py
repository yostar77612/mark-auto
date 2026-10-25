"""Explicit, hash-pinned runtime bundles. Loading never constructs an SDK client.

Documents are local selected files, not executable plugins. Resource payloads
use the existing bounded trusted-DTO codec and retain their source identities.
"""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import stat

from quantlab.trading.adapters.shioaji.stock_grid import StockGridEvidence
from quantlab.trading.application.broker_settings import BrokerSettings
from quantlab.trading.application.codec import MAX_BYTES, loads, register
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import CapabilitySnapshot, Environment, InstrumentSpec, Market
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError, decimal_value, identity


@dataclass(frozen=True)
class RuntimeLaunch:
    root: Path
    environment: Environment = Environment.LOCAL
    profile_path: Path | None = None
    account_ref: str = 'local-stock'
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1 or not isinstance(self.root, Path) or not self.root.is_absolute():
            raise DomainError('validation_failed', 'versioned absolute runtime location required')
        if (
            not isinstance(self.environment, Environment)
            or self.profile_path is not None
            and (not isinstance(self.profile_path, Path) or not self.profile_path.is_absolute())
        ):
            raise DomainError('validation_failed', 'explicit runtime environment and profile location required')
        identity(self.account_ref)
        if self.environment is Environment.LOCAL and (self.profile_path is not None or self.account_ref not in ('local-stock', 'local-futures')):
            raise DomainError('capability_missing', 'local lab cannot consume a broker profile or account')
        if self.environment is not Environment.LOCAL and self.account_ref in ('local-stock', 'local-futures'):
            raise DomainError('capability_missing', 'broker account alias must be explicitly selected')


@dataclass(frozen=True)
class ResourceReference:
    kind: str
    path: Path
    sha256: str

    def __post_init__(self) -> None:
        if self.kind not in ('catalog', 'calendar', 'fees', 'accounts', 'capabilities', 'history'):
            raise DomainError('validation_failed', 'unknown runtime resource kind')
        if not isinstance(self.path, Path) or not self.path.is_absolute() or str(self.path).startswith(('\\\\', '//')):
            raise DomainError('validation_failed', 'selected local absolute resource required')
        if type(self.sha256) is not str or len(self.sha256) != 64 or any(c not in '0123456789abcdef' for c in self.sha256):
            raise DomainError('validation_failed', 'resource SHA256 is required')


@dataclass(frozen=True)
class AccountMapping:
    account_ref: str
    sdk_account_id: str
    kind: str

    def __post_init__(self) -> None:
        identity(self.account_ref)
        identity(self.sdk_account_id)
        if self.kind not in ('STOCK', 'FUTURES'):
            raise DomainError('validation_failed', 'account market mapping required')


@dataclass(frozen=True)
class InstrumentMapping:
    spec: InstrumentSpec
    sdk_code: str
    stock_grid: StockGridEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.spec, InstrumentSpec):
            raise DomainError('instrument_unresolved', 'typed instrument required')
        identity(self.sdk_code)
        if self.sdk_code.endswith(('R1', 'R2')):
            raise DomainError('instrument_unresolved', 'continuous history symbols cannot bind execution')
        if self.stock_grid is not None and (
            not isinstance(self.stock_grid, StockGridEvidence) or self.spec.market is not Market.STOCK or self.stock_grid.sdk_code != self.sdk_code
        ):
            raise DomainError('instrument_unresolved', 'cash-security source evidence must match the explicit binding')


@dataclass(frozen=True)
class RuntimeProfile:
    profile_alias: str
    configuration: ExecutionConfiguration
    settings: BrokerSettings
    stock_allocation: Decimal
    futures_allocation: Decimal
    resources: tuple[ResourceReference, ...]
    source_path: Path
    source_sha256: str

    def __post_init__(self) -> None:
        identity(self.profile_alias)
        if (
            not isinstance(self.configuration, ExecutionConfiguration)
            or self.configuration.environment is Environment.LOCAL
            or not self.configuration.read_only
            or self.configuration.broker_simulation_enabled
            or self.configuration.live_execution_enabled
            or not isinstance(self.settings, BrokerSettings)
        ):
            raise DomainError('validation_failed', 'readonly typed broker profile required')
        if (
            self.settings.environment is not self.configuration.environment
            or self.settings.profile_alias != self.profile_alias
            or not self.settings.read_only
            or self.settings.execution_enabled
            or (self.settings.stock_account_ref, self.settings.futures_account_ref)
            != (self.configuration.stock_account_ref, self.configuration.futures_account_ref)
        ):
            raise DomainError('capability_missing', 'profile account/environment identities differ')
        for value in (self.stock_allocation, self.futures_allocation):
            decimal_value(value, 'configured allocation', nonnegative=True)
        if self.stock_allocation + self.futures_allocation > Decimal('100000'):
            raise DomainError('risk_rejected', 'single shared configured budget')
        if type(self.resources) is not tuple or not 5 <= len(self.resources) <= 6 or any(not isinstance(ref, ResourceReference) for ref in self.resources):
            raise DomainError('validation_failed', 'bounded typed resource references required')
        ResourceReference('catalog', self.source_path, self.source_sha256)


@dataclass(frozen=True)
class RuntimeResources:
    profile: RuntimeProfile
    catalog: Catalog
    calendar: TradingCalendar
    fees: FeeSchedule
    accounts: tuple[AccountMapping, ...]
    capabilities: tuple[CapabilitySnapshot, ...]
    history: tuple[tuple[str, tuple[CompletedBar, ...]], ...] = ()
    bindings: tuple[InstrumentMapping, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile, RuntimeProfile)
            or not isinstance(self.catalog, Catalog)
            or not isinstance(self.calendar, TradingCalendar)
            or not isinstance(self.fees, FeeSchedule)
        ):
            raise DomainError('validation_failed', 'typed runtime resources required')
        if (
            type(self.bindings) is not tuple
            or not self.bindings
            or any(not isinstance(binding, InstrumentMapping) for binding in self.bindings)
            or tuple(binding.spec for binding in self.bindings) != self.catalog.instruments
        ):
            raise DomainError('instrument_unresolved', 'complete explicit SDK bindings must match the catalog')
        if (
            type(self.accounts) is not tuple
            or not self.accounts
            or any(not isinstance(account, AccountMapping) for account in self.accounts)
            or type(self.capabilities) is not tuple
            or any(not isinstance(capability, CapabilitySnapshot) for capability in self.capabilities)
        ):
            raise DomainError('capability_missing', 'typed account and capability resources required')


register(AccountMapping, InstrumentMapping, StockGridEvidence)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _read(path: Path, *, scope: Path | None = None) -> bytes:
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise DomainError('validation_failed', 'local absolute configuration file required')
    try:
        if scope is not None and not path.resolve().is_relative_to(scope.resolve()):
            raise DomainError('validation_failed', 'runtime resources must stay in their selected bundle')
        for parent in (path, *path.parents):
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise DomainError('validation_failed', 'redirected runtime resource refused')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            raise DomainError('validation_failed', 'bounded runtime resource required')
        with path.open('rb') as stream:
            import os

            opened = os.fstat(stream.fileno())
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (
            (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or opened.st_ino != info.st_ino
            or len(raw) != info.st_size
        ):
            raise DomainError('validation_failed', 'runtime resource changed during inspection')
        return raw
    except OSError as exc:
        raise DomainError('capability_missing', 'selected runtime resource is unavailable') from exc


def _document(raw: bytes, *, version: int = 1) -> dict:
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))
        if type(value) is not dict or type(value.get('schema_version')) is not int or value['schema_version'] != version:
            raise ValueError('version')
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainError('validation_failed', 'invalid versioned runtime document') from exc


def read_runtime_document(path: Path, *, version: int = 1) -> dict:
    """Read one explicit local document using the shared bounded path policy."""
    return _document(_read(path), version=version)


def load_profile(path: Path, expected_environment: Environment | None = None) -> RuntimeProfile:
    initialize()
    raw = _read(path)
    body = _document(raw)
    required = {
        'schema_version',
        'profile_alias',
        'environment',
        'stock_account_ref',
        'futures_account_ref',
        'stock_allocation',
        'futures_allocation',
        'settings_payload',
        'resources',
    }
    if set(body) != required:
        raise DomainError('validation_failed', 'runtime profile fields must match its version')
    try:
        environment = Environment(body['environment'])
        if environment is Environment.LOCAL or expected_environment is not None and environment is not expected_environment:
            raise ValueError('environment')
        settings = loads(body['settings_payload'])
        stock, futures = body['stock_account_ref'], body['futures_account_ref']
        config = ExecutionConfiguration(environment, stock, futures, True, False, False)
        if (
            not isinstance(settings, BrokerSettings)
            or settings.environment is not environment
            or settings.stock_account_ref != stock
            or settings.futures_account_ref != futures
            or settings.profile_alias != body['profile_alias']
            or not settings.read_only
            or settings.execution_enabled
        ):
            raise ValueError('settings context')
        allocations = tuple(Decimal(body[name]) if type(body[name]) is str else None for name in ('stock_allocation', 'futures_allocation'))
        for value in allocations:
            decimal_value(value, 'configured allocation', nonnegative=True)
        if sum(allocations) > Decimal('100000') or not stock and allocations[0] or not futures and allocations[1]:
            raise ValueError('single shared budget')
        if type(body['resources']) is not list or not 5 <= len(body['resources']) <= 6:
            raise ValueError('resource set')
        references = []
        for item in body['resources']:
            if type(item) is not dict or set(item) != {'kind', 'path', 'sha256'} or type(item['path']) is not str:
                raise ValueError('reference')
            references.append(ResourceReference(item['kind'], Path(item['path']), item['sha256']))
        kinds = [ref.kind for ref in references]
        if len(set(kinds)) != len(kinds) or not {'catalog', 'calendar', 'fees', 'accounts', 'capabilities'} <= set(kinds):
            raise ValueError('resource coverage')
        configured = {
            'catalog': settings.instrument_spec_ref,
            'calendar': settings.calendar_ref,
            'fees': settings.fee_schedule_ref,
            'accounts': settings.account_mapping_ref,
            'capabilities': settings.capability_proof_ref,
        }
        if any(not configured[kind] or Path(configured[kind]) != ref.path for ref in references if (kind := ref.kind) in configured):
            raise ValueError('settings references differ from pinned resource bundle')
        return RuntimeProfile(settings.profile_alias, config, settings, *allocations, tuple(references), path, sha256(raw).hexdigest())
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        if isinstance(exc, DomainError):
            raise
        raise DomainError('validation_failed', 'invalid runtime profile values') from exc


def load_resources(profile: RuntimeProfile) -> RuntimeResources:
    values = {}
    for ref in profile.resources:
        raw = _read(ref.path, scope=profile.source_path.parent)
        if sha256(raw).hexdigest() != ref.sha256:
            raise DomainError('capability_missing', 'runtime resource identity changed')
        body = _document(raw, version=2)
        if set(body) != {'schema_version', 'kind', 'payload'} or body['kind'] != ref.kind:
            raise DomainError('validation_failed', 'runtime resource kind mismatch')
        values[ref.kind] = loads(body['payload'])
    bindings, calendar, fees, accounts, capabilities = (values[k] for k in ('catalog', 'calendar', 'fees', 'accounts', 'capabilities'))
    if type(bindings) is not tuple or not bindings or len(bindings) > 1000 or any(not isinstance(item, InstrumentMapping) for item in bindings):
        raise DomainError('instrument_unresolved', 'explicit normalized instrument and SDK-code mappings required')
    instruments = tuple(item.spec for item in bindings)
    if len({s.instrument_id for s in instruments}) != len(instruments) or len({item.sdk_code for item in bindings}) != len(bindings):
        raise DomainError('instrument_unresolved', 'unique bounded typed instrument catalog required')
    if not isinstance(calendar, TradingCalendar) or not isinstance(fees, FeeSchedule):
        raise DomainError('validation_failed', 'typed calendar and fee authority required')
    if any(spec.calendar_id != calendar.calendar_id for spec in instruments):
        raise DomainError('calendar_missing', 'instrument calendar identity differs from selected resource')
    expected = {ref for ref in (profile.configuration.stock_account_ref, profile.configuration.futures_account_ref) if ref}
    if (
        type(accounts) is not tuple
        or any(not isinstance(item, AccountMapping) for item in accounts)
        or {a.account_ref for a in accounts} != expected
        or len(accounts) != len(expected)
    ):
        raise DomainError('capability_missing', 'every configured account needs exactly one mapping')
    for account in accounts:
        kind = 'STOCK' if account.account_ref == profile.configuration.stock_account_ref else 'FUTURES'
        if account.kind != kind:
            raise DomainError('capability_missing', 'account market mapping mismatch')
    if (
        type(capabilities) is not tuple
        or any(not isinstance(cap, CapabilitySnapshot) for cap in capabilities)
        or {c.account_ref for c in capabilities} != expected
        or len(capabilities) != len(expected)
        or any(c.environment is not profile.configuration.environment for c in capabilities)
    ):
        raise DomainError('capability_missing', 'explicit account/environment capability evidence required')
    for capability in capabilities:
        allowed = (
            frozenset((Market.STOCK,))
            if capability.account_ref == profile.configuration.stock_account_ref
            else frozenset((Market.INDEX_FUTURE, Market.STOCK_FUTURE))
        )
        if not capability.markets <= allowed:
            raise DomainError('capability_missing', 'capability markets cross configured account scope')
    history = values.get('history', ())
    if type(history) is not tuple or len(history) > len(instruments):
        raise DomainError('validation_failed', 'bounded typed history required')
    catalog = Catalog(instruments)
    identities = []
    for pair in history:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[1]) is not tuple
            or len(pair[1]) > 10000
            or any(not isinstance(bar, CompletedBar) for bar in pair[1])
        ):
            raise DomainError('validation_failed', 'completed history resource required')
        catalog.resolve(pair[0])
        identities.append(pair[0])
    if len(set(identities)) != len(identities):
        raise DomainError('validation_failed', 'history identity duplicated')
    return RuntimeResources(profile, catalog, calendar, fees, accounts, capabilities, history, bindings)
