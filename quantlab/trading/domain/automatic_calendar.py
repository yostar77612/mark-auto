"""Official automatic DAY hours on a supplied verified day set; no holiday inference.

TAIFEX TMF specification, page3 / Article8:
https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/1130201142.pdf
TWSE general trading:
https://www.twse.com.tw/zh/products/system/trading.html

The ledger envelope synchronizes the trade date only. Submit and exit decisions
must use calendar_for_instrument, never another selected product's broader hours.
"""

from datetime import datetime, time
from hashlib import sha256
from functools import lru_cache
import json
from zoneinfo import ZoneInfo

from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.models import InstrumentSpec, Market
from quantlab.trading.domain.strategy import is_tmf
from quantlab.trading.domain.validation import DomainError

TAIPEI = ZoneInfo('Asia/Taipei')
STOCK_OPEN = time(9)
STOCK_CLOSE = time(13, 30)
TMF_OPEN = time(8, 45)
TMF_CLOSE = time(13, 45)
TMF_EXPIRY_CLOSE = STOCK_CLOSE
HOURS_VERSION = 'official-automatic-day-hours-v1'
TWSE_SOURCE = 'https://www.twse.com.tw/zh/products/system/trading.html'
TMF_SOURCE = 'https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/1130201142.pdf'


def _project_calendar(base: TradingCalendar, key: str, sessions: tuple[TradingSession, ...], source: str) -> TradingCalendar:
    material = (
        HOURS_VERSION,
        base.calendar_id,
        base.version,
        base.source,
        key,
        tuple((row.trade_date.isoformat(), row.opens_at.isoformat(), row.closes_at.isoformat()) for row in sessions),
    )
    digest = sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()
    identity = sha256(key.encode()).hexdigest()[:24]
    return TradingCalendar('automatic:' + identity, HOURS_VERSION + ':' + digest[:24], source, sessions)


@lru_cache(maxsize=64)
def calendar_for_instrument(base: TradingCalendar, spec: InstrumentSpec) -> TradingCalendar:
    """Keep verified DAY dates, replace legacy common hours with product hours."""
    stock = spec.market is Market.STOCK
    if not stock and not is_tmf(spec):
        raise DomainError('strategy_instrument_restricted', 'automatic calendar supports stocks and actual TMF contracts only')
    opens = STOCK_OPEN if stock else TMF_OPEN
    sessions = tuple(
        TradingSession(
            row.trade_date,
            datetime.combine(row.trade_date, opens, tzinfo=TAIPEI),
            datetime.combine(row.trade_date, STOCK_CLOSE if stock else TMF_EXPIRY_CLOSE if row.trade_date == spec.expiry else TMF_CLOSE, tzinfo=TAIPEI),
        )
        for row in base.sessions
        if row.kind == 'DAY'
    )
    source = (TWSE_SOURCE if stock else TMF_SOURCE) + '|VERIFIED_BASE_DAY_SET'
    return _project_calendar(base, spec.market.value + ':' + spec.instrument_id, sessions, source)


@lru_cache(maxsize=64)
def automatic_day_calendar(base: TradingCalendar, instruments: tuple[InstrumentSpec, ...]) -> TradingCalendar:
    """Earliest open/latest close for ledger DAY synchronization only."""
    if not instruments:
        raise DomainError('instrument_unresolved', 'automatic day synchronization requires selected instruments')
    calendars = tuple(calendar_for_instrument(base, spec) for spec in instruments)
    sessions = tuple(
        TradingSession(
            day,
            min(calendar.day_session(day).opens_at for calendar in calendars),
            max(calendar.day_session(day).closes_at for calendar in calendars),
        )
        for day in calendars[0].days
    )
    key = 'LEDGER_DAY_SYNC_ONLY:' + ','.join(sorted({calendar.calendar_id for calendar in calendars}))
    source = '|'.join(sorted({calendar.source for calendar in calendars}))
    return _project_calendar(base, key, sessions, source)
