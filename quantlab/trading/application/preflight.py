"""Immutable opening-check facts and views; facts originate inside runtime."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class PreflightFacts:
    connected: bool | None
    account_ready: bool | None
    permission_ready: bool | None
    ca_ready: bool | None
    realtime: bool | None
    service_open: bool | None
    reconciled: bool | None


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    state: str
    code: str = ''


@dataclass(frozen=True)
class PreflightView:
    account_ref: str
    trade_date: date
    checked_at: datetime
    checks: tuple[PreflightCheck, ...]
    blocked_today: bool
    keep_awake_reminder: bool = True
    block_reasons: tuple[str, ...] = ()
