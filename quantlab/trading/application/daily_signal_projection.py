"""Bounded pure daily math, prepared separately from current admission proofs.

The immutable key contains actual history values, the complete calendar, the
original research basis and through-day. A hit says nothing about current source
revision, arrival, owner, evidence or permission; callers still check those.
Native locked callers never compute on a miss, including after LRU eviction.
"""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from threading import Lock

from .codec import dumps
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.daily_signal_data import DailyResearchBasis, OfficialDailyHistory
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError


MAX_PROJECTIONS = 128
_cache = OrderedDict()
_mutex = Lock()


@dataclass(frozen=True)
class DailySignalProjection:
    research_basis: DailyResearchBasis
    dataset_id: str
    signals: tuple[CompletedBar, ...]
    signal_fingerprint: str


def signal_window_fingerprint(history, calendar, through: date, signals):
    day_opens = {row.trade_date: row.opens_at for row in calendar.sessions if row.kind == 'DAY'}
    start = next(row.trade_date for row in history.bars if day_opens[row.trade_date] == signals[0].opened_at)
    basis = history.research_basis(start, through)
    return sha256(
        dumps((basis.policy_fingerprint, basis.raw_digest, basis.events_digest, calendar.calendar_id, calendar.version, signals)).encode()
    ).hexdigest()


def _derive_daily_projection(history, calendar, original_basis, through):
    current = history.research_basis(original_basis.start, original_basis.end)
    raw = history.trim(original_basis.start, original_basis.end).raw_completed(calendar)
    # The historical wire identity includes the ORIGINAL transport digest.
    # A compatible refresh must not replace it with the current source digest.
    dataset = sha256(dumps((raw, original_basis)).encode()).hexdigest()
    signals = history.signal_history(calendar, through)
    return DailySignalProjection(current, dataset, signals, signal_window_fingerprint(history, calendar, through, signals))


def daily_projection(
    history: OfficialDailyHistory,
    calendar: TradingCalendar,
    original_basis: DailyResearchBasis,
    through: date,
    *,
    cached_only: bool = False,
) -> DailySignalProjection:
    key = history, calendar, original_basis, through
    with _mutex:
        found = _cache.get(key)
        if found is not None:
            _cache.move_to_end(key)
            return found
    if cached_only:
        raise DomainError('daily_signal_not_available', 'daily semantic projection must be prepared outside writer locks')
    # Encoding, adjustment and hashing may be expensive. Do not hold even the
    # small cache mutex while deriving; concurrent equal preparations are pure.
    result = _derive_daily_projection(history, calendar, original_basis, through)
    with _mutex:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > MAX_PROJECTIONS:
            _cache.popitem(last=False)
    return result


def prepare_daily_projection(history, calendar, original_basis, through):
    """Normalize ordinary read/semantic-processing failures before runtime admission."""
    try:
        return daily_projection(history, calendar, original_basis, through)
    except DomainError:
        raise
    except Exception:
        raise DomainError('daily_signal_source_unverified', 'daily semantic preparation failed') from None
