"""Authenticated account identities stay inside the adapter boundary."""

from dataclasses import dataclass, field
from hashlib import sha256
from hmac import new as hmac_new

from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError
from .sdk import sdk_text, sdk_value


def account_identity(raw: object) -> tuple[str, str, str]:
    values = tuple(sdk_text(sdk_value(raw, name)) for name in ('account_type', 'broker_id', 'account_id'))
    if any(not value or len(value) > 120 or any(ord(char) < 32 for char in value) for value in values):
        raise DomainError('reconciliation_required', 'account identity malformed')
    return values


@dataclass(frozen=True)
class DiscoveredAccount:
    alias: str
    label: str
    market: Market
    signed: bool | None
    native: object = field(repr=False, compare=False)


def keyed_account_digest(legacy_digest: str, alias_key: bytes) -> str:
    """Versioned HMAC also lets legacy hashes migrate without raw account data."""
    message = b'MarkAuto/account-identity/v2\0' + bytes.fromhex(legacy_digest)
    return hmac_new(alias_key, message, sha256).hexdigest()


def account_digest(raw: object, environment: Environment, alias_key: bytes) -> str:
    legacy = sha256('\0'.join((environment.value, *account_identity(raw))).encode('utf-8')).hexdigest()
    return keyed_account_digest(legacy, alias_key)


def discover_accounts(rows: list[object], environment: Environment, *, alias_key: bytes) -> tuple[DiscoveredAccount, ...]:
    if not isinstance(environment, Environment) or environment is Environment.LOCAL or len(rows) > 100:
        raise DomainError('capability_missing', 'bounded broker account discovery required')
    result, identities = [], set()
    for raw in rows:
        kind, broker, account = account_identity(raw)
        if kind not in ('S', 'F'):
            continue
        key = kind, broker, account
        if key in identities:
            raise DomainError('reconciliation_required', 'duplicate broker account identity')
        identities.add(key)
        digest = account_digest(raw, environment, alias_key)[:24]
        signed = getattr(raw, 'signed', None)
        if signed is not None and type(signed) is not bool:
            raise DomainError('reconciliation_required', 'account signed evidence malformed')
        result.append(
            DiscoveredAccount(
                'sinopac-' + digest,
                broker + '-***' + (account[-min(3, len(account) - 1) :] if len(account) > 1 else ''),
                Market.STOCK if kind == 'S' else Market.INDEX_FUTURE,
                signed,
                raw,
            )
        )
    return tuple(sorted(result, key=lambda item: item.alias))
