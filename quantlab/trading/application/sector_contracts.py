"""Read-only sector board DTOs shared by the engine and its UI client."""

from dataclasses import dataclass
from datetime import date, datetime
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
class MonitorCount:
    """Members actually receiving ticks for one monitored group."""

    group_id: str
    monitored: int
    total: int

    def __post_init__(self) -> None:
        identity(self.group_id)
        integer(self.monitored, 'monitored members')
        integer(self.total, 'group members')


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
    side_ratio: Decimal | None = None

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.code)
        integer(self.amount, 'member amount')
        if self.limit not in LIMITS:
            raise DomainError('validation_failed', 'member limit state')
        if self.leader_at is not None:
            aware(self.leader_at)


@dataclass(frozen=True)
class ShareBaseline:
    """Average cumulative turnover share of one group at this time of day over the previous stored days."""

    group_id: str
    share_bps: int
    days: int

    def __post_init__(self) -> None:
        identity(self.group_id)
        integer(self.share_bps, 'baseline share', 1)
        integer(self.days, 'baseline days', 1)


def _is_minute(value: str) -> bool:
    """Exactly HH:MM (00:00-23:59)."""
    try:
        datetime.strptime(value, '%H:%M')
    except (TypeError, ValueError):
        return False
    return len(value) == 5


def _history_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DomainError('validation_failed', 'history date') from None


@dataclass(frozen=True)
class SectorHistoryQuery:
    """No date: list the stored days. A date: its minutes and one minute's rows (the given one, else the last)."""

    trade_date: str = ''
    minute: str = ''

    def __post_init__(self) -> None:
        if self.trade_date:
            _history_date(self.trade_date)
        if self.minute and (not self.trade_date or not _is_minute(self.minute)):
            raise DomainError('validation_failed', 'history minute')


@dataclass(frozen=True)
class HistoryRow:
    """One group at one stored minute; percentages are basis points, amount is that minute's NT$."""

    group_id: str
    name: str
    equal_pct_bps: int
    share_bps: int
    breadth_bps: int
    limit_up: int
    amount: int
    members: int
    complete: bool

    def __post_init__(self) -> None:
        identity(self.group_id)
        if type(self.equal_pct_bps) is not int or type(self.complete) is not bool:
            raise DomainError('validation_failed', 'history row')
        for value, name in (
            (self.share_bps, 'share'),
            (self.breadth_bps, 'breadth'),
            (self.limit_up, 'limit up'),
            (self.amount, 'amount'),
            (self.members, 'members'),
        ):
            integer(value, 'history ' + name)


@dataclass(frozen=True)
class SectorHistoryView:
    days: tuple[str, ...] = ()
    trade_date: str = ''
    minutes: tuple[str, ...] = ()
    minute: str = ''
    rows: tuple[HistoryRow, ...] = ()
    failed: bool = False

    def __post_init__(self) -> None:
        for day in self.days + ((self.trade_date,) if self.trade_date else ()):
            _history_date(day)
        if any(not _is_minute(value) for value in self.minutes + ((self.minute,) if self.minute else ())):
            raise DomainError('validation_failed', 'history minute')


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
    monitored: tuple[str, ...] = ()
    monitor_counts: tuple[MonitorCount, ...] = ()
    baselines: tuple[ShareBaseline, ...] = ()

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
