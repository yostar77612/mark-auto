"""Date-only maintenance facts; unknown dates never become a healthy zero."""

from dataclasses import dataclass
from datetime import date

from .calendar import TradingCalendar
from .validation import DomainError, identity, trading_date


@dataclass(frozen=True)
class KeyExpiryStatus:
    expires_on: date | None
    remaining_days: int | None
    state: str


@dataclass(frozen=True)
class ExpiryCoverage:
    version: str
    months: tuple[tuple[str, date], ...]

    def __post_init__(self):
        identity(self.version)
        names = []
        for month, day in self.months:
            trading_date(day)
            if month != day.strftime('%Y%m'):
                raise DomainError('validation_failed', 'verified expiry month/date mismatch')
            names.append(month)
        if names != sorted(set(names)):
            raise DomainError('validation_failed', 'sorted unique expiry coverage required')


@dataclass(frozen=True)
class PreOpenMaintenance:
    key: KeyExpiryStatus
    calendar_version: str
    expiry_version: str | None
    future_trading_days: int
    through: date | None
    issues: tuple[str, ...]
    reminders: tuple[str, ...]

    @property
    def can_open_new(self) -> bool:
        return not self.issues

    def require_automatic_entry(self) -> None:
        if self.issues:
            raise DomainError(self.issues[0], 'automatic entry waits for verified maintenance coverage')


def key_expiry_status(expires_on: date | None, today: date) -> KeyExpiryStatus:
    trading_date(today)
    if expires_on is None:
        return KeyExpiryStatus(None, None, 'UNKNOWN')
    trading_date(expires_on)
    days = (expires_on - today).days
    # A date without a vendor time is treated conservatively: renewal is needed
    # at the start of that local date, not an invented 23:59 grace period.
    return KeyExpiryStatus(expires_on, days, 'EXPIRED' if days <= 0 else 'DUE' if days <= 14 else 'VALID')


def maintenance_check(
    calendar: TradingCalendar,
    today: date,
    *,
    expires_on: date | None,
    expiries: ExpiryCoverage | None,
    futures_required: bool = True,
) -> PreOpenMaintenance:
    key = key_expiry_status(expires_on, today)
    future = tuple(day for day in calendar.days if day > today)
    horizon = future[:30]
    issues, reminders = [], []
    if key.state in ('UNKNOWN', 'EXPIRED'):
        issues.append('api_key_expiry_unknown' if key.state == 'UNKNOWN' else 'api_key_expired')
    if key.state in ('DUE', 'EXPIRED'):
        reminders.append('api_key_renewal_due')
    if len(horizon) < 30 or calendar.days[0] > today:
        issues.append('calendar_coverage_missing')
    if today.month == 12:
        reminders.append('calendar_annual_update_due')
    if futures_required:
        required = {day.strftime('%Y%m') for day in (today, *horizon)}
        available = {} if expiries is None else dict(expiries.months)
        if not required.issubset(available):
            issues.append('expiry_coverage_missing')
    return PreOpenMaintenance(
        key,
        calendar.version,
        expiries.version if expiries else None,
        len(horizon),
        horizon[-1] if len(horizon) == 30 else None,
        tuple(issues),
        tuple(reminders),
    )
