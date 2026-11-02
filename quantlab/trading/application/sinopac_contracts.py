"""Reference-only Sinopac settings and redacted connection read models."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import ntpath

from quantlab.trading.domain.maintenance import PreOpenMaintenance
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError, decimal_value, identity, integer
from .broker_settings import _secret_reference


@dataclass(frozen=True)
class SinopacConnectionSettings:
    environment: Environment = Environment.BROKER_SIMULATION
    key_ref: str = 'MarkAuto/v2/broker/sinopac'
    certificate_path: str = ''
    certificate_secret_ref: str = 'MarkAuto/v2/certificate/sinopac'
    fee_discount: Decimal = Decimal('1')
    api_key_expires_on: date | None = None
    minimum_fee: Decimal = Decimal('20')
    tmf_fee_per_contract: Decimal = Decimal('30')

    def __post_init__(self) -> None:
        if not isinstance(self.environment, Environment) or self.environment not in (Environment.BROKER_SIMULATION, Environment.LIVE):
            raise DomainError('validation_failed', 'connection environment')
        if not isinstance(self.key_ref, str) or not _secret_reference(self.key_ref, 'broker'):
            raise DomainError('validation_failed', 'connection key reference')
        if not isinstance(self.certificate_secret_ref, str) or not _secret_reference(self.certificate_secret_ref, 'certificate'):
            raise DomainError('validation_failed', 'certificate secret reference')
        if not isinstance(self.certificate_path, str) or len(self.certificate_path) > 1000 or any(ord(c) < 32 for c in self.certificate_path):
            raise DomainError('validation_failed', 'certificate file reference')
        if self.certificate_path and (not ntpath.isabs(self.certificate_path) or self.certificate_path.startswith(('\\\\', '//'))):
            raise DomainError('validation_failed', 'local absolute certificate reference required')
        if self.api_key_expires_on is not None and type(self.api_key_expires_on) is not date:
            raise DomainError('validation_failed', 'API key expiry date')
        decimal_value(self.fee_discount, 'fee discount', positive=True)
        decimal_value(self.minimum_fee, 'minimum fee', nonnegative=True)
        decimal_value(self.tmf_fee_per_contract, 'TMF fee', nonnegative=True)
        if self.fee_discount > 1:
            raise DomainError('validation_failed', 'fee discount')


@dataclass(frozen=True)
class SinopacAccountView:
    alias: str
    label: str
    market: Market
    signed: bool | None
    selected: bool = False
    selectable: bool = True
    reason: str = ''

    def __post_init__(self) -> None:
        identity(self.alias, 'account alias')
        identity(self.label, 'masked account label')
        if '*' not in self.label or self.market not in (Market.STOCK, Market.INDEX_FUTURE) or not isinstance(self.market, Market):
            raise DomainError('validation_failed', 'redacted broker account')
        if self.signed is not None and type(self.signed) is not bool or type(self.selected) is not bool or type(self.selectable) is not bool:
            raise DomainError('validation_failed', 'account selection facts')
        if self.reason:
            identity(self.reason, 'account reason')


@dataclass(frozen=True)
class SinopacReadiness:
    code: str
    state: str
    reason: str

    def __post_init__(self) -> None:
        if self.code not in ('market', 'accounts', 'simulation_orders', 'production_orders') or self.state not in (
            'READY',
            'BLOCKED',
            'UNKNOWN',
            'NOT_REQUIRED',
        ):
            raise DomainError('validation_failed', 'connection readiness')
        if self.reason:
            identity(self.reason, 'readiness reason')


@dataclass(frozen=True)
class SinopacConnectionView:
    settings: SinopacConnectionSettings = SinopacConnectionSettings()
    revision: int = 0
    generation: str = ''
    environment: Environment | None = None
    phase: str = 'DISCONNECTED'
    accounts: tuple[SinopacAccountView, ...] = ()
    readiness: tuple[SinopacReadiness, ...] = (
        SinopacReadiness('market', 'BLOCKED', 'not_connected'),
        SinopacReadiness('accounts', 'BLOCKED', 'not_connected'),
        SinopacReadiness('simulation_orders', 'BLOCKED', 'implementation_pending'),
        SinopacReadiness('production_orders', 'BLOCKED', 'production_orders_disabled'),
    )
    certificate_status: str = 'NOT_REQUIRED'
    error_code: str = ''
    api_key_remaining_days: int | None = None
    api_key_expiry_state: str = 'UNKNOWN'
    pre_open: PreOpenMaintenance | None = None

    def __post_init__(self) -> None:
        integer(self.revision, 'connection revision')
        if not isinstance(self.settings, SinopacConnectionSettings) or not isinstance(self.generation, str):
            raise DomainError('validation_failed', 'connection read model')
        if self.generation:
            identity(self.generation, 'connection generation')
        if self.environment is not None and (not isinstance(self.environment, Environment) or self.environment is Environment.LOCAL):
            raise DomainError('validation_failed', 'accepted connection environment')
        if self.phase not in ('DISCONNECTED', 'CONNECTING', 'CONNECTED', 'DISCONNECTING'):
            raise DomainError('validation_failed', 'connection phase')
        if type(self.accounts) is not tuple or any(not isinstance(account, SinopacAccountView) for account in self.accounts):
            raise DomainError('validation_failed', 'connection accounts')
        if len({account.alias for account in self.accounts}) != len(self.accounts):
            raise DomainError('validation_failed', 'duplicate account alias')
        if type(self.readiness) is not tuple or len(self.readiness) != 4 or any(not isinstance(item, SinopacReadiness) for item in self.readiness):
            raise DomainError('validation_failed', 'four readiness facts required')
        if {item.code for item in self.readiness} != {'market', 'accounts', 'simulation_orders', 'production_orders'}:
            raise DomainError('validation_failed', 'unique readiness facts required')
        if self.certificate_status not in ('NOT_REQUIRED', 'NOT_CONFIGURED', 'ACTIVATING', 'READY', 'FAILED', 'UNKNOWN'):
            raise DomainError('validation_failed', 'certificate state')
        if self.api_key_remaining_days is not None and type(self.api_key_remaining_days) is not int:
            raise DomainError('validation_failed', 'API key remaining days')
        if self.api_key_expiry_state not in ('UNKNOWN', 'VALID', 'DUE', 'EXPIRED'):
            raise DomainError('validation_failed', 'API key expiry state')
        if self.pre_open is not None and not isinstance(self.pre_open, PreOpenMaintenance):
            raise DomainError('validation_failed', 'typed pre-open maintenance required')
        days = self.api_key_remaining_days
        expected_state = 'UNKNOWN' if days is None else 'EXPIRED' if days <= 0 else 'DUE' if days <= 14 else 'VALID'
        if self.api_key_expiry_state != expected_state:
            raise DomainError('validation_failed', 'inconsistent API key expiry facts')
        if self.error_code:
            identity(self.error_code, 'connection error')
