"""Reference-only broker configuration and side-effect-free readiness use case."""

from dataclasses import dataclass
from datetime import datetime
import ntpath
from typing import Protocol

from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION


@dataclass(frozen=True)
class BrokerSettings:
    profile_alias: str = 'sinopac'
    environment: Environment = Environment.BROKER_SIMULATION
    stock_account_ref: str = ''
    futures_account_ref: str = ''
    account_mapping_ref: str = ''
    broker_secret_ref: str = ''
    certificate_ref: str = ''
    certificate_secret_ref: str = ''
    instrument_spec_ref: str = ''
    calendar_ref: str = ''
    fee_schedule_ref: str = ''
    capability_proof_ref: str = ''
    sdk_version: str = BROKER_SDK_VERSION
    read_only: bool = True
    execution_enabled: bool = False
    schema_version: int = 2

    def __post_init__(self) -> None:
        if (
            self.schema_version != 2
            or type(self.schema_version) is not int
            or not isinstance(self.environment, Environment)
            or self.environment not in (Environment.BROKER_SIMULATION, Environment.LIVE)
        ):
            raise DomainError('validation_failed', 'broker settings schema/environment')
        if type(self.read_only) is not bool or type(self.execution_enabled) is not bool:
            raise DomainError('validation_failed', 'broker settings flags')
        names = (
            'profile_alias',
            'stock_account_ref',
            'futures_account_ref',
            'account_mapping_ref',
            'broker_secret_ref',
            'certificate_ref',
            'certificate_secret_ref',
            'instrument_spec_ref',
            'calendar_ref',
            'fee_schedule_ref',
            'capability_proof_ref',
            'sdk_version',
        )
        if any(
            not isinstance(getattr(self, name), str) or len(getattr(self, name)) > 1000 or any(ord(char) < 32 for char in getattr(self, name)) for name in names
        ):
            raise DomainError('validation_failed', 'broker settings reference types')
        if not 1 <= len(self.profile_alias) <= 60 or not all(char.isascii() and (char.isalnum() or char in ('-', '_')) for char in self.profile_alias):
            raise DomainError('validation_failed', 'broker profile alias')
        for name, kind in (('broker_secret_ref', 'broker'), ('certificate_secret_ref', 'certificate')):
            value = getattr(self, name)
            if value and not _secret_reference(value, kind):
                raise DomainError('validation_failed', 'only scoped credential references may be saved')
        for name in ('account_mapping_ref', 'certificate_ref', 'instrument_spec_ref', 'calendar_ref', 'fee_schedule_ref', 'capability_proof_ref'):
            value = getattr(self, name)
            if value and not (ntpath.isabs(value) or value.startswith('/')):
                raise DomainError('validation_failed', 'only absolute document references may be saved')


@dataclass(frozen=True)
class ReferenceMetadata:
    reference: str
    exists: bool
    regular_file: bool
    size: int
    sha256: str
    reason: str = ''
    schema_version: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reference, str)
            or any(type(value) is not bool for value in (self.exists, self.regular_file))
            or type(self.size) is not int
            or self.size < 0
        ):
            raise DomainError('validation_failed', 'reference metadata types')
        if not isinstance(self.sha256, str) or self.sha256 and (len(self.sha256) != 64 or any(char not in '0123456789abcdef' for char in self.sha256)):
            raise DomainError('validation_failed', 'reference digest')
        if self.schema_version is not None and type(self.schema_version) is not int:
            raise DomainError('validation_failed', 'reference schema type')


class ReferenceInspector(Protocol):
    def inspect(self, reference: str) -> ReferenceMetadata: ...


@dataclass(frozen=True)
class ReadinessCheck:
    code: str
    passed: bool
    detail: str
    external_required: bool = False

    def __post_init__(self) -> None:
        if (
            self.code not in READINESS_CODES
            or self.detail not in READINESS_DETAILS
            or type(self.passed) is not bool
            or type(self.external_required) is not bool
        ):
            raise DomainError('validation_failed', 'readiness check code/types')


@dataclass(frozen=True)
class BrokerReadiness:
    profile_alias: str
    environment: Environment
    local_ready: bool
    external_verified: bool
    checks: tuple[ReadinessCheck, ...]
    checked_at: datetime
    references: tuple[ReferenceMetadata, ...] = ()

    def __post_init__(self) -> None:
        aware(self.checked_at)
        if (
            not isinstance(self.environment, Environment)
            or type(self.references) is not tuple
            or any(not isinstance(item, ReferenceMetadata) for item in self.references)
        ):
            raise DomainError('validation_failed', 'broker readiness reference/environment types')
        if (
            type(self.local_ready) is not bool
            or type(self.external_verified) is not bool
            or type(self.checks) is not tuple
            or any(not isinstance(check, ReadinessCheck) for check in self.checks)
        ):
            raise DomainError('validation_failed', 'broker readiness types')


READINESS_CODES = frozenset(
    (
        'sdk_version',
        'account_selection',
        'broker_secret_ref',
        'account_mapping_ref',
        'instrument_spec_ref',
        'calendar_ref',
        'fee_schedule_ref',
        'capability_proof_ref',
        'certificate_ref',
        'certificate_secret_ref',
        'execution_default_disabled',
        'external_account_verified',
        'external_capability_verified',
        'external_broker_simulation_verified',
        'external_ca_verified',
    )
)
READINESS_DETAILS = frozenset(
    (
        'verified_metadata',
        'missing_reference',
        'invalid_reference',
        'metadata_unavailable',
        'unsupported_version',
        'configuration_valid',
        'execution_disabled',
        'execution_not_authorized',
        'not_required',
        'external_verification_required',
    )
)


def _secret_reference(value: str, kind: str) -> bool:
    prefix = f'MarkAuto/v2/{kind}/'
    suffix = value[len(prefix) :] if value.startswith(prefix) else ''
    return 1 <= len(suffix) <= 80 and all(char.isascii() and (char.isalnum() or char in ('-', '_')) for char in suffix)


def check_readiness(settings: BrokerSettings, inspector: ReferenceInspector, now: datetime) -> BrokerReadiness:
    """Inspect only explicitly supplied references. Never resolves a secret/login."""
    if not isinstance(settings, BrokerSettings):
        raise DomainError('validation_failed', 'typed broker settings required')
    aware(now)
    checks: list[ReadinessCheck] = []
    references: list[ReferenceMetadata] = []

    def add(code: str, passed: bool, success: str = 'configuration_valid', failure: str = 'invalid_reference', *, external: bool = False) -> None:
        checks.append(ReadinessCheck(code, passed, success if passed else failure, external))

    add('sdk_version', settings.sdk_version == BROKER_SDK_VERSION, failure='unsupported_version')
    selected = tuple(value for value in (settings.stock_account_ref, settings.futures_account_ref) if value)
    add('account_selection', bool(selected) and len(set(selected)) == len(selected), failure='missing_reference')
    add(
        'broker_secret_ref',
        _secret_reference(settings.broker_secret_ref, 'broker'),
        failure='missing_reference' if not settings.broker_secret_ref else 'invalid_reference',
    )
    for name in ('account_mapping_ref', 'instrument_spec_ref', 'calendar_ref', 'fee_schedule_ref', 'capability_proof_ref'):
        reference = getattr(settings, name)
        if not reference:
            add(name, False, failure='missing_reference')
            continue
        try:
            metadata = inspector.inspect(reference)
            valid = (
                isinstance(metadata, ReferenceMetadata)
                and metadata.reference == reference
                and metadata.exists
                and metadata.regular_file
                and 0 < metadata.size <= 1024 * 1024
                and len(metadata.sha256) == 64
                and all(char in '0123456789abcdef' for char in metadata.sha256)
                and metadata.schema_version == 2
            )
            add(name, valid, success='verified_metadata', failure='metadata_unavailable')
            if valid:
                references.append(metadata)
        except (DomainError, OSError, ValueError):
            add(name, False, failure='metadata_unavailable')
    live = settings.environment is Environment.LIVE
    if live:
        try:
            certificate = inspector.inspect(settings.certificate_ref) if settings.certificate_ref else None
            valid = (
                isinstance(certificate, ReferenceMetadata)
                and certificate.reference == settings.certificate_ref
                and certificate.exists
                and certificate.regular_file
                and 0 < certificate.size <= 1024 * 1024
                and len(certificate.sha256) == 64
            )
            if valid:
                references.append(certificate)
        except (DomainError, OSError, ValueError):
            valid = False
        add('certificate_ref', valid, success='verified_metadata', failure='missing_reference' if not settings.certificate_ref else 'metadata_unavailable')
        add('certificate_secret_ref', _secret_reference(settings.certificate_secret_ref, 'certificate'), failure='missing_reference')
    else:
        add('certificate_ref', True, success='not_required')
        add('certificate_secret_ref', True, success='not_required')
    add('execution_default_disabled', settings.read_only and not settings.execution_enabled, success='execution_disabled', failure='execution_not_authorized')
    local_ready = all(check.passed for check in checks)
    for code in ('external_account_verified', 'external_capability_verified', 'external_broker_simulation_verified'):
        add(code, False, failure='external_verification_required', external=True)
    add('external_ca_verified', not live, success='not_required', failure='external_verification_required', external=live)
    return BrokerReadiness(settings.profile_alias, settings.environment, local_ready, False, tuple(checks), now, tuple(references))
