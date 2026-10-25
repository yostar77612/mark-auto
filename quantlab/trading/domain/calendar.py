"""Versioned explicit sessions; never infer holidays or fabricate trading days."""

from dataclasses import dataclass
from datetime import date, datetime

from .validation import DomainError, aware, identity, integer, trading_date


@dataclass(frozen=True)
class TradingSession:
    trade_date: date
    opens_at: datetime
    closes_at: datetime
    kind: str = 'DAY'

    def __post_init__(self) -> None:
        trading_date(self.trade_date)
        aware(self.opens_at)
        aware(self.closes_at)
        if self.closes_at <= self.opens_at or self.kind not in ('DAY', 'NIGHT'):
            raise DomainError('calendar_missing', 'invalid session')


@dataclass(frozen=True)
class TradingCalendar:
    calendar_id: str
    version: str
    source: str
    sessions: tuple[TradingSession, ...]

    def __post_init__(self) -> None:
        identity(self.calendar_id)
        identity(self.version)
        identity(self.source)
        if type(self.sessions) is not tuple or not self.sessions or len(self.sessions) > 50000:
            raise DomainError('calendar_missing', 'explicit sessions required')
        previous: datetime | None = None
        identities: set[tuple[date, str]] = set()
        for session in self.sessions:
            if not isinstance(session, TradingSession) or previous is not None and session.opens_at < previous:
                raise DomainError('calendar_missing', 'sessions overlap or are unordered')
            key = (session.trade_date, session.kind)
            if key in identities:
                raise DomainError('calendar_missing', 'duplicate session')
            identities.add(key)
            previous = session.closes_at

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(sorted({s.trade_date for s in self.sessions}))

    def index(self, day: date) -> int:
        trading_date(day)
        try:
            return self.days.index(day)
        except ValueError as exc:
            raise DomainError('calendar_missing', day.isoformat()) from exc

    def age(self, entry_day: date, current_day: date) -> int:
        value = self.index(current_day) - self.index(entry_day)
        if value < 0:
            raise DomainError('calendar_missing', 'current day precedes entry')
        return value

    def advance(self, entry_day: date, days: int) -> date:
        integer(days, 'holding days')
        offset = self.index(entry_day) + days
        if offset >= len(self.days):
            raise DomainError('calendar_missing', 'holding window exceeds verified coverage')
        return self.days[offset]

    def session_at(self, now: datetime, *, allow_night: bool = False) -> TradingSession:
        aware(now)
        for session in self.sessions:
            if session.opens_at <= now <= session.closes_at:
                if session.kind == 'NIGHT' and not allow_night:
                    raise DomainError('session_closed', 'night execution disabled')
                return session
        raise DomainError('session_closed', 'no verified trading session')

    def day_session(self, day: date) -> TradingSession:
        self.index(day)
        for session in self.sessions:
            if session.trade_date == day and session.kind == 'DAY':
                return session
        raise DomainError('calendar_missing', 'day session missing')
