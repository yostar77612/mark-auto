"""Sector statistics from one snapshot round; pure functions, Decimal throughout."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .validation import DomainError, aware, decimal_value, identity, integer

KINDS = ('INDUSTRY', 'CONCEPT')
LIMITS = ('', 'UP', 'DOWN')
FEW_MEMBERS = 4


def eligible_stock(code: str) -> bool:
    """Ordinary listed/OTC shares only: four digits. ETFs (00xx), warrants, preferred shares are out."""
    return len(code) == 4 and code.isdigit() and not code.startswith('00')


@dataclass(frozen=True)
class SectorGroup:
    id: str
    name: str
    kind: str
    codes: tuple[str, ...]

    def __post_init__(self) -> None:
        identity(self.id)
        if self.kind not in KINDS or not self.name.strip():
            raise DomainError('validation_failed', 'sector group identity')


@dataclass(frozen=True)
class QuoteRow:
    code: str
    price: Decimal
    change_pct: Decimal
    limit: str
    total_volume: int
    total_amount: int
    volume_ratio: Decimal | None
    at: datetime

    def __post_init__(self) -> None:
        identity(self.code)
        decimal_value(self.price, 'snapshot price', positive=True)
        decimal_value(self.change_pct, 'snapshot change')
        integer(self.total_volume, 'snapshot volume')
        integer(self.total_amount, 'snapshot amount')
        aware(self.at)
        if self.limit not in LIMITS:
            raise DomainError('validation_failed', 'snapshot limit state')
        if self.volume_ratio is not None:
            decimal_value(self.volume_ratio, 'snapshot volume ratio', nonnegative=True)


@dataclass(frozen=True)
class SectorStat:
    group_id: str
    name: str
    kind: str
    equal_pct: Decimal | None
    up_count: int
    valid_count: int
    listed_count: int
    limit_up: int
    limit_down: int
    amount: int
    share: Decimal | None

    @property
    def breadth(self) -> Decimal | None:
        return Decimal(self.up_count) / Decimal(self.valid_count) if self.valid_count else None

    @property
    def few_members(self) -> bool:
        return self.valid_count < FEW_MEMBERS


def market_amount(rows: dict[str, QuoteRow]) -> int:
    return sum(row.total_amount for code, row in rows.items() if eligible_stock(code))


def compute_stats(groups: tuple[SectorGroup, ...], rows: dict[str, QuoteRow]) -> tuple[SectorStat, ...]:
    total = market_amount(rows)
    result = []
    for group in groups:
        members = [rows[code] for code in dict.fromkeys(group.codes) if code in rows]
        count = len(members)
        amount = sum(row.total_amount for row in members)
        result.append(
            SectorStat(
                group.id,
                group.name,
                group.kind,
                sum((row.change_pct for row in members), Decimal(0)) / count if count else None,
                sum(1 for row in members if row.change_pct > 0),
                count,
                len(set(group.codes)),
                sum(1 for row in members if row.limit == 'UP'),
                sum(1 for row in members if row.limit == 'DOWN'),
                amount,
                Decimal(amount) / Decimal(total) if total else None,
            )
        )
    return tuple(result)


SORT_KEYS = ('equal_pct', 'breadth', 'limit_up', 'amount', 'share', 'name')


def sort_stats(stats: tuple[SectorStat, ...], key: str = 'equal_pct', descending: bool = True) -> tuple[SectorStat, ...]:
    """Groups without a value sort last in either direction; ties keep the original order."""
    if key not in SORT_KEYS:
        raise DomainError('validation_failed', 'sector sort key')
    known = [item for item in stats if getattr(item, key) is not None]
    unknown = [item for item in stats if getattr(item, key) is None]
    return tuple(sorted(known, key=lambda item: getattr(item, key), reverse=descending) + unknown)
