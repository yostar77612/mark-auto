"""Watchlist input and subscription orchestration; no files, UI or order path.

The active strategy set always precedes watch subscriptions. Refused additions
are checked before any allocation, so they cannot evict an existing strategy.
"""

from typing import TYPE_CHECKING
from quantlab.trading.domain.validation import DomainError, identity

if TYPE_CHECKING:
    from .engine import TradingEngine


def validate_watchlist(value: tuple[str, ...]) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(key) is not str for key in value):
        raise DomainError('validation_failed', 'watchlist identities required')
    if len(value) > 20:
        raise DomainError('capability_missing', 'strategy subscriptions have priority')
    if len(set(value)) != len(value):
        raise DomainError('validation_failed', 'unique watchlist required')
    for key in value:
        identity(key)
    return value


def strategy_instruments(engine: 'TradingEngine') -> tuple[str, ...]:
    return tuple(record.form.instrument_id for record in engine.state.strategies if record.state == 'ACTIVE')


def prepare_watchlist(engine: 'TradingEngine', requested: tuple[str, ...]) -> tuple[str, ...]:
    watches = validate_watchlist(requested)
    if engine.live_market is None:
        raise DomainError('capability_missing', 'market data unavailable')
    for key in watches:
        engine.catalog.resolve(key)
    if len(set((*strategy_instruments(engine), *watches))) > engine.live_market.settings.subscription_limit:
        raise DomainError('capability_missing', 'strategy subscriptions have priority')
    return watches


def apply_watchlist(engine: 'TradingEngine', watches: tuple[str, ...]) -> None:
    if engine.live_market is not None:
        engine.live_market.watchlist = watches
        engine.live_market.allocate(strategy_instruments(engine), watches)


def restore_watchlist(engine: 'TradingEngine', watches: tuple[str, ...] | None) -> tuple[str, ...] | None:
    # Unset settings leave default subscriptions to the existing market cycle.
    # Restoring preferences must not allocate an unrelated catalog on startup.
    if watches is None or engine.live_market is None:
        return watches
    for key in watches:
        engine.catalog.resolve(key)
    apply_watchlist(engine, watches)
    return watches
