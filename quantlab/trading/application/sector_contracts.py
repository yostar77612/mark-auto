"""Read-only sector board DTOs shared by the engine and its UI client."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantlab.trading.domain.sector import LIMITS, SectorStat
from quantlab.trading.domain.sector_alerts import SectorAlert
from quantlab.trading.domain.validation import DomainError, aware, identity, integer

STATES = ('LIVE', 'STALE', 'CLOSED', 'OFFLINE', 'EMPTY')


@dataclass(frozen=True)
class SectorQuery:
    group_id: str = ''

    def __post_init__(self) -> None:
        if self.group_id:
            identity(self.group_id)


@dataclass(frozen=True)
class MemberView:
    instrument_id: str
    code: str
    name: str
    price: Decimal
    change_pct: Decimal
    volume_ratio: Decimal | None
    amount: int
    limit: str
    leader_at: datetime | None = None
    is_leader: bool = False

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.code)
        integer(self.amount, 'member amount')
        if self.limit not in LIMITS:
            raise DomainError('validation_failed', 'member limit state')
        if self.leader_at is not None:
            aware(self.leader_at)


@dataclass(frozen=True)
class SectorBoardView:
    state: str = 'OFFLINE'
    data_at: datetime | None = None
    age_seconds: int = 0
    interval_seconds: int = 10
    stock_count: int = 0
    groups: tuple[SectorStat, ...] = ()
    selected_group_id: str = ''
    members: tuple[MemberView, ...] = ()
    failed: bool = False
    alerts: tuple[SectorAlert, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise DomainError('validation_failed', 'sector board state')
        integer(self.age_seconds, 'sector data age')
        integer(self.interval_seconds, 'sector interval', 1)
        integer(self.stock_count, 'sector stock count')
        if self.data_at is not None:
            aware(self.data_at)


GROUP_ACTIONS = ('LIST', 'CREATE', 'RENAME', 'DELETE', 'RESTORE', 'SET_CODES')


@dataclass(frozen=True)
class SectorGroupsCommand:
    action: str = 'LIST'
    group_id: str = ''
    name: str = ''
    codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.action not in GROUP_ACTIONS:
            raise DomainError('validation_failed', 'sector group action')
        if self.group_id:
            identity(self.group_id)
        if (
            not isinstance(self.name, str)
            or len(self.name) > 100
            or not isinstance(self.codes, tuple)
            or len(self.codes) > 200
            or any(not isinstance(code, str) for code in self.codes)
        ):
            raise DomainError('validation_failed', 'sector group command shape')


@dataclass(frozen=True)
class GroupEditView:
    id: str
    name: str
    codes: tuple[str, ...]
    unknown_codes: tuple[str, ...] = ()
    builtin: bool = False
    edited: bool = False
    deleted: bool = False

    def __post_init__(self) -> None:
        identity(self.id)


@dataclass(frozen=True)
class SectorGroupsView:
    groups: tuple[GroupEditView, ...] = ()
    selected_id: str = ''
    warning: str = ''
