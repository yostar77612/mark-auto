"""Display-only TAIFEX session hours and trade dates for watched futures; never execution evidence.

Official regular hours (Taipei): day 08:45-13:45, night 15:00-05:00 next calendar day. A night
session belongs to the next trading day. Holidays come only from a supplied verified day set
(the existing scheduled calendar); beyond its coverage the next weekday is used, which can only
differ on a holiday, when no session trades.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .validation import DomainError

TAIPEI = ZoneInfo('Asia/Taipei')
DAY_OPEN = time(8, 45)
DAY_CLOSE = time(13, 45)
NIGHT_OPEN = time(15)
NIGHT_CLOSE = time(5)
# A closing match stamped exactly on the boundary still belongs to the session it closes.
_DAY_END = time(13, 46)
_NIGHT_END = time(5, 1)


def session_kind_at(moment: datetime) -> str | None:
    """DAY, NIGHT, or None between sessions; weekends are decided by trade_date_at."""
    local = moment.astimezone(TAIPEI).time()
    if DAY_OPEN <= local < _DAY_END:
        return 'DAY'
    if local >= NIGHT_OPEN or local < _NIGHT_END:
        return 'NIGHT'
    return None


def next_trade_day(after: date, days: tuple[date, ...]) -> date:
    """First verified trading day strictly after the date; the next weekday beyond coverage."""
    if days and after < days[-1]:
        return next(day for day in days if day > after)
    day = after + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def trade_date_at(moment: datetime, days: tuple[date, ...] = ()) -> tuple[date, str]:
    local = moment.astimezone(TAIPEI)
    kind = session_kind_at(local)
    if kind is None:
        raise DomainError('calendar_missing', 'time is outside the futures sessions')
    if kind == 'DAY':
        if local.weekday() >= 5:
            raise DomainError('calendar_missing', 'no futures day session on a weekend')
        return local.date(), 'DAY'
    # The evening of D, or the small hours of D+1, both belong to the day after D.
    evening = local.date() if local.time() >= NIGHT_OPEN else local.date() - timedelta(days=1)
    if evening.weekday() >= 5:
        raise DomainError('calendar_missing', 'no futures night session on a weekend evening')
    return next_trade_day(evening, days), 'NIGHT'


def in_session(moment: datetime) -> bool:
    """Regular hours only; like the stock check this ignores holidays."""
    try:
        trade_date_at(moment)
    except DomainError:
        return False
    return True


def minutes_since_open(moment: datetime) -> int:
    """Minutes since the open of the session the moment is in; negative before any open."""
    local = moment.astimezone(TAIPEI)
    kind = session_kind_at(local)
    minutes = local.hour * 60 + local.minute
    if kind == 'NIGHT':
        return minutes - 900 if minutes >= 900 else minutes + 540
    return minutes - 525
