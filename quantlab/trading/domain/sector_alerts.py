"""Sector alert parameters and the pure burst (A) judgement; Decimal for ratios, integers for NT$."""

from dataclasses import dataclass, fields
from datetime import datetime, time
from decimal import Decimal

from .validation import DomainError, aware, decimal_value, identity, integer

DIRECTIONS = ('UP', 'DOWN', 'NEUTRAL')
KINDS = ('BURST', 'FLOW')
SESSION_OPEN, EVAL_END = time(9, 0), time(13, 25)

# name: (minimum, maximum) from the spec's parameter table (Appendix B).
RANGES = {
    'snapshot_seconds': (5, 30),
    'burst_multiple': (Decimal('1.5'), Decimal(20)),
    'burst_floor': (0, 1_000_000_000),
    'baseline_minutes': (10, 60),
    'direction_pct': (Decimal('0.1'), Decimal(2)),
    'warmup_minutes': (0, 30),
    'flow_minutes': (2, 10),
    'flow_floor': (0, 1_000_000_000),
    'flow_multiple': (Decimal(1), Decimal(10)),
    'big_order': (100_000, 50_000_000),
    'monitor_groups': (1, 5),
    'monitor_keep_minutes': (0, 15),
    'monitor_budget': (0, 200),
    'cooldown_minutes': (1, 60),
}
DECIMAL_FIELDS = ('burst_multiple', 'direction_pct', 'flow_multiple')


@dataclass(frozen=True)
class SectorAlertParams:
    burst_enabled: bool = True
    flow_enabled: bool = True
    snapshot_seconds: int = 10
    burst_multiple: Decimal = Decimal(3)
    burst_floor: int = 20_000_000
    baseline_minutes: int = 30
    direction_pct: Decimal = Decimal('0.3')
    warmup_minutes: int = 10
    flow_minutes: int = 3
    flow_floor: int = 10_000_000
    flow_multiple: Decimal = Decimal(2)
    big_order: int = 1_000_000
    monitor_groups: int = 3
    monitor_keep_minutes: int = 5
    monitor_budget: int = 45
    cooldown_minutes: int = 10

    def __post_init__(self) -> None:
        for name in ('burst_enabled', 'flow_enabled'):
            if type(getattr(self, name)) is not bool:
                raise DomainError('validation_failed', name)
        for name, (low, high) in RANGES.items():
            value = getattr(self, name)
            if name in DECIMAL_FIELDS:
                decimal_value(value, name)
            else:
                integer(value, name)
            if not low <= value <= high:
                raise DomainError('validation_failed', name + ' out of range')

    def as_dict(self) -> dict:
        return {field.name: str(getattr(self, field.name)) if field.name in DECIMAL_FIELDS else getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> 'SectorAlertParams':
        known = {field.name for field in fields(cls)}
        values = {key: (Decimal(str(value)) if key in DECIMAL_FIELDS else value) for key, value in data.items() if key in known}
        return cls(**values)


@dataclass(frozen=True)
class MinuteStat:
    """One complete or incomplete minute of one group; cumulative amount is NT$, deltas are per minute."""

    minute: datetime
    group_id: str
    amount: int
    cumulative: int
    share_bps: int
    equal_pct_bps: int
    breadth_bps: int
    limit_up: int
    limit_down: int
    members: int
    complete: bool = True

    def __post_init__(self) -> None:
        aware(self.minute)
        identity(self.group_id)
        for name in ('amount', 'cumulative', 'limit_up', 'limit_down', 'members'):
            integer(getattr(self, name), name)


@dataclass(frozen=True)
class SectorAlert:
    at: datetime
    group_id: str
    group_name: str
    kind: str
    direction: str
    amount: int
    baseline: int
    ratio: Decimal | None = None
    detail: int = 0
    members: int = 0
    monitored: int = 0

    def __post_init__(self) -> None:
        aware(self.at)
        identity(self.group_id)
        if self.kind not in KINDS or self.direction not in DIRECTIONS:
            raise DomainError('validation_failed', 'sector alert kind/direction')


def minute_direction(delta_bps: int, threshold: Decimal) -> str:
    delta = Decimal(delta_bps) / 100
    return 'UP' if delta > threshold else 'DOWN' if delta < -threshold else 'NEUTRAL'


def in_alert_window(minute: datetime, zone, params: SectorAlertParams) -> bool:
    """09:00-13:25 Taipei, and not inside the opening warm-up."""
    local = minute.astimezone(zone)
    elapsed = (local.hour * 60 + local.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
    return SESSION_OPEN <= local.time() <= EVAL_END and elapsed >= params.warmup_minutes


def judge_burst(amount: int, history: tuple[int, ...], params: SectorAlertParams) -> tuple[bool, int]:
    """Burst when this minute is >= multiple x the mean of the preceding complete minutes and >= the floor."""
    window = history[-params.baseline_minutes :]
    if not window:
        return False, 0
    baseline = sum(window) // len(window)
    if baseline <= 0:
        return False, baseline
    return amount >= baseline * params.burst_multiple and amount >= params.burst_floor, baseline
