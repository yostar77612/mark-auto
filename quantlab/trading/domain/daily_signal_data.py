"""Official stock signal windows with one reproducible research price basis."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json

from .calendar import TradingCalendar
from .stock_history import ADJUSTMENT_METHOD, CorporateAction, DailyStockBar, price_series, valid_digest
from .strategy import CompletedBar
from .validation import DomainError, aware, identity, trading_date


def _signal_digest(rows) -> str:
    return sha256(json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _decimal_text(value) -> str:
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


@dataclass(frozen=True)
class DailySignalPolicy:
    source_id: str = 'OFFICIAL_STOCK_DAILY_V1'
    price_mode: str = 'ADJUSTED'
    adjustment_method: str = ADJUSTMENT_METHOD
    scope: str = 'EXCHANGE_REPORTED_DAILY_V1'
    window_bars: int = 20
    as_of_rule: str = 'EX_DATE_THROUGH_COMPLETED_DAY_V1'

    def __post_init__(self):
        if (
            self.source_id != 'OFFICIAL_STOCK_DAILY_V1'
            or self.price_mode != 'ADJUSTED'
            or self.adjustment_method != ADJUSTMENT_METHOD
            or self.scope != 'EXCHANGE_REPORTED_DAILY_V1'
            or type(self.window_bars) is not int
            or self.window_bars != 20
            or self.as_of_rule != 'EX_DATE_THROUGH_COMPLETED_DAY_V1'
        ):
            raise DomainError('daily_signal_source_unverified', 'unsupported official daily signal policy')

    @property
    def fingerprint(self) -> str:
        return _signal_digest((self.source_id, self.price_mode, self.adjustment_method, self.scope, self.window_bars, self.as_of_rule))


@dataclass(frozen=True)
class DailyResearchBasis:
    instrument_id: str
    start: date
    end: date
    policy_fingerprint: str
    raw_digest: str
    events_digest: str
    source_digest: str

    def compatible(self, other: 'DailyResearchBasis') -> bool:
        return isinstance(other, DailyResearchBasis) and (
            self.instrument_id,
            self.start,
            self.end,
            self.policy_fingerprint,
            self.raw_digest,
            self.events_digest,
        ) == (other.instrument_id, other.start, other.end, other.policy_fingerprint, other.raw_digest, other.events_digest)


def _completed_daily(calendar: TradingCalendar, bars: tuple[DailyStockBar, ...]) -> tuple[CompletedBar, ...]:
    sessions = tuple(row for row in calendar.sessions if row.kind == 'DAY' and bars[0].trade_date <= row.trade_date <= bars[-1].trade_date)
    if tuple(row.trade_date for row in sessions) != tuple(bar.trade_date for bar in bars):
        raise DomainError('daily_signal_not_available', 'each expected verified DAY needs its actual official OHLC')
    return tuple(
        CompletedBar(session.opens_at, session.closes_at, session.closes_at, Decimal(_decimal_text(bar.open)), Decimal(_decimal_text(bar.close)), bar.volume)
        for session, bar in zip(sessions, bars)
    )


@dataclass(frozen=True)
class OfficialDailyHistory:
    instrument_id: str
    bars: tuple[DailyStockBar, ...]
    events: tuple[CorporateAction, ...]
    observed_at: datetime
    source_digest: str
    policy: DailySignalPolicy = DailySignalPolicy()

    def __post_init__(self):
        identity(self.instrument_id)
        aware(self.observed_at)
        venue, separator, symbol = self.instrument_id.partition(':')
        if venue not in ('TWSE', 'TPEX') or not separator or not symbol or ':' in symbol:
            raise DomainError('daily_signal_source_unverified', 'official TWSE/TPEX stock identity required')
        if not isinstance(self.policy, DailySignalPolicy) or not valid_digest(self.source_digest):
            raise DomainError('daily_signal_source_unverified', 'official signal policy and snapshot digest required')
        if type(self.bars) is not tuple or not self.bars:
            raise DomainError('daily_signal_not_available', 'actual immutable official daily rows required')
        if any(not isinstance(row, DailyStockBar) or row.instrument_id != self.instrument_id for row in self.bars):
            raise DomainError('daily_signal_source_unverified', 'single official stock history required')
        days = tuple(row.trade_date for row in self.bars)
        if days != tuple(sorted(set(days))):
            raise DomainError('daily_signal_source_unverified', 'official daily dates must be ordered and unique')
        if type(self.events) is not tuple or any(not isinstance(row, CorporateAction) or row.instrument_id != self.instrument_id for row in self.events):
            raise DomainError('daily_signal_source_unverified', 'single stock official corporate actions required')
        if len({row.ex_date for row in self.events}) != len(self.events):
            raise DomainError('daily_signal_source_unverified', 'one combined official action per ex-date required')
        family = 'https://www.twse.com.tw/' if venue == 'TWSE' else 'https://www.tpex.org.tw/'
        if any(not row.source_url.startswith(family) for row in self.events):
            raise DomainError('daily_signal_source_unverified', 'corporate action exchange must match the instrument')

    def raw_completed(self, calendar: TradingCalendar) -> tuple[CompletedBar, ...]:
        """Historical RAW fills; observed_at separately records snapshot availability."""
        return _completed_daily(calendar, self.bars)

    def signal_history(self, calendar: TradingCalendar, through: date) -> tuple[CompletedBar, ...]:
        trading_date(through)
        available = tuple(row for row in self.bars if row.trade_date <= through)
        if not available or available[-1].trade_date != through:
            raise DomainError('daily_signal_not_available', 'the completed signal DAY must have an official row')
        window = available[-self.policy.window_bars :]
        adjusted = price_series(window, self.events, as_of=through)
        return _completed_daily(calendar, adjusted.bars)

    def trim(self, start: date, end: date) -> 'OfficialDailyHistory':
        trading_date(start)
        trading_date(end)
        if start > end:
            raise DomainError('daily_signal_not_available', 'history range must be inclusive and chronological')
        return replace(
            self,
            bars=tuple(row for row in self.bars if start <= row.trade_date <= end),
            events=tuple(row for row in self.events if start <= row.ex_date <= end),
        )

    def research_basis(self, start: date, end: date) -> DailyResearchBasis:
        window = self.trim(start, end)
        raw = tuple(
            (row.instrument_id, row.trade_date.isoformat(), *(_decimal_text(value) for value in (row.open, row.high, row.low, row.close)), row.volume)
            for row in window.bars
        )
        events = tuple(
            (row.instrument_id, row.ex_date.isoformat(), _decimal_text(row.previous_close), _decimal_text(row.reference_price))
            for row in sorted(window.events, key=lambda row: row.ex_date)
        )
        return DailyResearchBasis(self.instrument_id, start, end, self.policy.fingerprint, _signal_digest(raw), _signal_digest(events), self.source_digest)
