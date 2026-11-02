"""Explicit training window and complete session grids for minute research."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .calendar import TradingCalendar, TradingSession
from .live_bars import LiveBar
from .minute_contract import HistoricalContractEvidence
from .strategy import CompletedBar
from .validation import DomainError, aware, decimal_value, identity, integer, trading_date

TAIPEI = ZoneInfo('Asia/Taipei')
MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class MinuteResearchSettings:
    first_day: date
    last_day: date
    interval: str = '1m'
    holding_unit: str = 'MINUTES'
    minimum: int = 1
    maximum: int = 30
    intraday: bool = True
    cutoff_minute: int = 13 * 60 + 35
    partition: str = 'TRAINING'
    raw_data_digest: str = ''
    historical_contract: HistoricalContractEvidence | None = None

    def __post_init__(self) -> None:
        if self.historical_contract is not None and not isinstance(self.historical_contract, HistoricalContractEvidence):
            raise DomainError('validation_failed', 'typed historical contract evidence required')
        trading_date(self.first_day)
        trading_date(self.last_day)
        if (
            type(self.raw_data_digest) is not str
            or self.raw_data_digest
            and (len(self.raw_data_digest) != 64 or any(c not in '0123456789abcdef' for c in self.raw_data_digest))
        ):
            raise DomainError('validation_failed', 'minute raw data digest')
        integer(self.minimum, 'minimum holding')
        integer(self.maximum, 'maximum holding', 1)
        integer(self.cutoff_minute, 'intraday cutoff')
        if (
            self.first_day > self.last_day
            or self.interval not in ('1m', '5m')
            or self.holding_unit not in ('MINUTES', 'TRADING_DAYS')
            or self.minimum > self.maximum
            or self.maximum > 10000
            or type(self.intraday) is not bool
            or not 0 <= self.cutoff_minute < 1440
            or self.partition != 'TRAINING'
        ):
            raise DomainError('validation_failed', 'minute training settings')

    def sessions(self, calendar: TradingCalendar) -> tuple[TradingSession, ...]:
        calendar.day_session(self.first_day)
        calendar.day_session(self.last_day)
        days = tuple(day for day in calendar.days if self.first_day <= day <= self.last_day)
        day_sessions = {session.trade_date: session for session in calendar.sessions if session.kind == 'DAY'}
        if any(day not in day_sessions for day in days):
            raise DomainError('calendar_missing', 'day session missing')
        sessions = tuple(day_sessions[day] for day in days)
        step = 1 if self.interval == '1m' else 5
        for session in sessions:
            length = (session.closes_at - session.opens_at).total_seconds() / 60
            local = session.opens_at.astimezone(TAIPEI)
            cutoff_offset = self.cutoff_minute - (local.hour * 60 + local.minute)
            if (
                local.date() != session.trade_date
                or session.closes_at.astimezone(TAIPEI).date() != session.trade_date
                or local.second
                or local.microsecond
                or length % step
                or length < step * 2
                or self.intraday
                and not (step <= cutoff_offset < length and cutoff_offset % step == 0)
            ):
                raise DomainError('calendar_missing', 'minute session or forced-close grid')
        if sum(int((s.closes_at - s.opens_at) / MINUTE) for s in sessions) > 10000:
            raise DomainError('validation_failed', 'minute training window exceeds 10000 raw bars')
        return sessions


@dataclass(frozen=True)
class FixedModelMinuteSettings(MinuteResearchSettings):
    """Explicit fixed-parameter research, not verified historical contract terms.

    The supplied spec tick grid, multiplier and lot size plus FeeSchedule apply
    to every selected bar. Margin feasibility and daily limits are not modeled.
    Existing interval-reference DTOs retain their original wire representation.
    """

    sdk_code: str = ''
    model_version: str = 'minute-fixed-model-v1'
    basis: str = 'FIXED_MODEL'
    historical_applicability: str = 'UNKNOWN'

    def __post_init__(self) -> None:
        super().__post_init__()
        identity(self.sdk_code)
        if (
            self.historical_contract is not None
            or self.sdk_code.endswith(('R1', 'R2'))
            or self.model_version != 'minute-fixed-model-v1'
            or self.basis != 'FIXED_MODEL'
            or self.historical_applicability != 'UNKNOWN'
        ):
            raise DomainError('validation_failed', 'explicit fixed-model settings without historical proof required')


def complete_minutes(
    bars: tuple[LiveBar, ...],
    instrument_id: str,
    calendar: TradingCalendar,
    settings: MinuteResearchSettings,
    now: datetime,
) -> tuple[CompletedBar, ...]:
    """No coverage-record shortcut: every expected minute must exist exactly once."""
    aware(now)
    sessions = settings.sessions(calendar)
    expected = tuple((s, s.opens_at + n * MINUTE) for s in sessions for n in range(int((s.closes_at - s.opens_at) / MINUTE)))
    if type(bars) is not tuple or len(bars) != len(expected):
        raise DomainError('validation_failed', 'minute data incomplete; history refill required')
    for bar, (session, start) in zip(bars, expected):
        if (
            not isinstance(bar, LiveBar)
            or bar.instrument_id != instrument_id
            or bar.start != start
            or bar.end != start + MINUTE
            or bar.trade_date != session.trade_date
            or bar.session != 'DAY'
            or not bar.final
            or bar.incomplete
            or bar.end > now
        ):
            raise DomainError('validation_failed', 'minute grid, identity or completion mismatch')
        for value in (bar.open, bar.high, bar.low, bar.close):
            decimal_value(value, 'minute price', positive=True)
        integer(bar.volume, 'minute volume')
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise DomainError('validation_failed', 'minute OHLC')
    width = 1 if settings.interval == '1m' else 5
    return tuple(
        CompletedBar(group[0].start, group[-1].end, group[-1].end, group[0].open, group[-1].close, sum(b.volume for b in group))
        for i in range(0, len(bars), width)
        if (group := bars[i : i + width])
    )
