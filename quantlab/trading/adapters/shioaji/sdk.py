"""SDK-facing types and conversions, confined to this adapter package."""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

from quantlab.trading.domain.models import InstrumentSpec, PriceBand
from quantlab.trading.domain.validation import DomainError, identity
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION
from .stock_grid import StockGridEvidence

SDK_VERSION = BROKER_SDK_VERSION


@dataclass(frozen=True)
class BrokerCredentials:
    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)


@dataclass(frozen=True)
class CertificateCredentials:
    ca_path: str = field(repr=False)
    ca_password: str = field(repr=False)
    person_id: str = field(repr=False)


@dataclass(frozen=True)
class InstrumentBinding:
    spec: InstrumentSpec
    sdk_code: str
    stock_grid: StockGridEvidence | None = None

    def __post_init__(self) -> None:
        identity(self.sdk_code)
        if self.sdk_code.endswith(('R1', 'R2')):
            raise DomainError('instrument_unresolved', 'continuous contracts are history-only')
        if self.stock_grid is not None and (not isinstance(self.stock_grid, StockGridEvidence) or self.stock_grid.sdk_code != self.sdk_code):
            raise DomainError('instrument_unresolved', 'typed stock-grid identity mismatch')


class SecretResolver(Protocol):
    def broker_credentials(self, reference: str) -> BrokerCredentials: ...
    def certificate_credentials(self, reference: str) -> CertificateCredentials: ...


class TradeDateResolver(Protocol):
    def session_at(self, instrument_id: str, timestamp: datetime) -> tuple[date, str]: ...


class SDKContractStore(Protocol):
    def get(self, code: str) -> object: ...
    def info(self, contract: object) -> object: ...
    def tick_bands(self, info: object) -> tuple[PriceBand, ...]: ...


class SDKClient(Protocol):
    """Real Python SDK method names. Only this package sees returned SDK objects."""

    contracts: SDKContractStore

    def login(self, *, api_key: str, secret_key: str, subscribe_trade: bool) -> list[object]: ...
    def logout(self) -> object: ...
    def activate_ca(self, *, ca_path: str, ca_passwd: str, person_id: str) -> bool: ...
    def list_accounts(self) -> list[object]: ...
    def account_balance(self, *, account: object) -> object: ...
    def trading_limits(self, *, account: object) -> object: ...
    def margin(self, *, account: object) -> object: ...
    def settlements(self, *, account: object) -> list[object]: ...
    def list_positions(self, *, account: object, unit: object) -> list[object]: ...
    def kbars(self, *, contract: object, start: str, end: str) -> object: ...
    def snapshots(self, contracts: list[object]) -> list[object]: ...
    def subscribe(self, contract: object, *, quote_type: str, version: object) -> None: ...
    def unsubscribe(self, contract: object, *, quote_type: str, version: object) -> None: ...
    def Order(self, **kwargs: object) -> object: ...
    def place_order(self, contract: object, order: object) -> object: ...
    def update_order(self, trade: object, *, price: float, qty: int) -> object: ...
    def cancel_order(self, trade: object) -> object: ...
    def update_status(self, *, account: object) -> object: ...
    def list_trades(self) -> list[object]: ...


def sdk_decimal(value: object, name: str) -> Decimal:
    """SDK native numbers are normalized once before crossing the port."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, float, int, str)):
        raise DomainError('validation_failed', f'SDK {name} type')
    try:
        result = Decimal(str(value))
    except (ValueError, ArithmeticError):
        raise DomainError('validation_failed', f'SDK {name} numeric') from None
    if not result.is_finite():
        raise DomainError('validation_failed', f'SDK {name} finite')
    return result


def sdk_price(price: Decimal) -> float:
    value = float(price)
    if sdk_decimal(value, 'price') != price:
        raise DomainError('validation_failed', 'SDK float cannot represent requested decimal price')
    return value


def sdk_value(raw: object, name: str) -> object:
    if not hasattr(raw, name):
        raise DomainError('reconciliation_required', f'SDK field missing: {name}')
    return getattr(raw, name)


def sdk_text(raw: object) -> str:
    value = getattr(raw, 'value', raw)
    if not isinstance(value, str):
        raise DomainError('validation_failed', 'SDK enum/string')
    return value


def sdk_time(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DomainError('reconciliation_required', 'SDK naive timestamp requires explicit source timezone')
        return value.astimezone(timezone.utc)
    if type(value) in (int, float):
        # SDK snapshot/history Unix timestamps use nanoseconds.
        try:
            return datetime.fromtimestamp(float(value) / 1_000_000_000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise DomainError('validation_failed', 'SDK timestamp range') from None
    raise DomainError('validation_failed', 'SDK timestamp')


def query_error(error: Exception, detail: str) -> DomainError:
    """Map documented vendor categories without exposing vendor message text."""
    names = {item.__name__ for item in type(error).__mro__}
    if 'MarketDataQueryUsageLimitError' in names:
        return DomainError('rate_limited', detail)
    if names.intersection(('AuthError', 'TokenError', 'CaError', 'CaExpiredError', 'CaPasswordError', 'AccountNotSignError', 'ShioajiPermissionError')):
        return DomainError('capability_missing', detail)
    return DomainError('reconciliation_required', detail)
