"""Immutable, read-only market values. No broker or trading-core dependencies.

A daily source does not establish event/session timestamps. Missing times remain
None; callers must never reinterpret them as minute bars or executable quotes.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import re


class MarketValidationError(ValueError):
    """Invalid or unsupported market data; consumers must fail closed."""


def utc(value, *, optional=False):
    if value is None and optional:
        return
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise MarketValidationError('timestamp must be aware UTC')


def day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        raise MarketValidationError('invalid trade_date')
    try: date.fromisoformat(value)
    except ValueError as exc: raise MarketValidationError('invalid trade_date') from exc


def price(value, *, optional=False):
    if value is None and optional: return
    if not isinstance(value,Decimal) or not value.is_finite() or value < 0 or value > Decimal('1000000000') or len(value.as_tuple().digits)>24 or abs(value.as_tuple().exponent)>12:
        raise MarketValidationError('price must be a bounded finite nonnegative Decimal')


@dataclass(frozen=True)
class InstrumentRef:
    exchange: str
    symbol: str
    contract_id: str
    expiry: str | None = None

    def __post_init__(self):
        if self.exchange=='TWSE':
            ok=self.symbol=='TAIEX' and self.contract_id=='TWSE:TAIEX' and self.expiry is None
        elif self.exchange=='TAIFEX':
            native={'TX':'TX','MXF':'MTX','TMF':'TMF'}.get(self.symbol)
            ok=(native is not None and isinstance(self.expiry,str) and bool(re.fullmatch(r'\d{4}(?:0[1-9]|1[0-2])(?:W[1-5])?',self.expiry)) and self.contract_id==f'TAIFEX:{native}:{self.expiry}')
        else: ok=False
        if not ok: raise MarketValidationError('unsupported or mismatched instrument identity')


@dataclass(frozen=True)
class MarketBar:
    instrument: InstrumentRef
    trade_date: str
    session: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    interval: str = 'session'
    timestamp: datetime | None = None
    end: datetime | None = None
    session_open: datetime | None = None
    session_end: datetime | None = None
    partial: bool = False
    source_id: str = ''
    settlement: Decimal | None = None

    def __post_init__(self):
        if not isinstance(self.instrument,InstrumentRef): raise MarketValidationError('instrument required')
        day(self.trade_date)
        if self.session not in ('day','night','combined'): raise MarketValidationError('invalid session')
        if self.interval not in ('session','1m','3m','5m','15m','30m','60m','1d','1w'): raise MarketValidationError('invalid interval')
        for value in (self.open,self.high,self.low,self.close): price(value)
        price(self.settlement,optional=True)
        if not self.low<=min(self.open,self.close)<=max(self.open,self.close)<=self.high: raise MarketValidationError('invalid OHLC envelope')
        if self.volume is not None and (type(self.volume) is not int or not 0<=self.volume<=10**15): raise MarketValidationError('invalid volume')
        if type(self.partial) is not bool: raise MarketValidationError('partial must be bool')
        if not isinstance(self.source_id,str) or len(self.source_id)>128: raise MarketValidationError('invalid source_id')
        for value in (self.timestamp,self.end,self.session_open,self.session_end): utc(value,optional=True)
        if (self.timestamp is None)!=(self.end is None): raise MarketValidationError('paired event interval required')
        if self.timestamp is not None and self.timestamp>=self.end: raise MarketValidationError('empty event interval')
        if self.interval.endswith('m'):
            if self.timestamp is None or self.session_open is None or self.session_end is None: raise MarketValidationError('minute bars require explicit session bounds')
            seconds=int(self.interval[:-1])*60
            duration=(self.end-self.timestamp).total_seconds()
            if duration>seconds or (duration!=seconds and not self.partial and self.end!=self.session_end): raise MarketValidationError('minute interval duration mismatch')
            if (self.timestamp-self.session_open).total_seconds()%seconds: raise MarketValidationError('minute bar is not session-open anchored')
        if (self.session_open is None)!=(self.session_end is None): raise MarketValidationError('paired session bounds required')
        if self.session_open is not None:
            if self.session_open>=self.session_end: raise MarketValidationError('invalid session bounds')
            if self.timestamp is not None and not self.session_open<=self.timestamp<self.end<=self.session_end: raise MarketValidationError('bar outside session')

    @property
    def contract_id(self): return self.instrument.contract_id

    @property
    def symbol(self): return self.instrument.symbol


@dataclass(frozen=True)
class SourceProvenance:
    source_url: str
    sha256: str
    attribution: str
    license_url: str
    received_at: datetime
    as_of: str
    coverage_start: str
    coverage_end: str
    mode: str = 'eod'
    timestamp_basis: str = 'exchange_trade_date_only; event timestamps unavailable'
    omitted_rows: int = 0
    warnings: tuple[str,...] = ()

    def __post_init__(self):
        utc(self.received_at)
        for value in (self.as_of,self.coverage_start,self.coverage_end): day(value)
        if not self.coverage_start<=self.coverage_end or self.as_of!=self.coverage_end: raise MarketValidationError('invalid coverage')
        if not re.fullmatch('[0-9a-f]{64}',self.sha256): raise MarketValidationError('invalid source hash')
        if self.mode not in ('history','eod','realtime','delayed','offline'): raise MarketValidationError('invalid data mode')
        if type(self.omitted_rows) is not int or self.omitted_rows<0: raise MarketValidationError('invalid omitted rows')
        if not isinstance(self.warnings,tuple) or any(not isinstance(x,str) or len(x)>1000 for x in self.warnings): raise MarketValidationError('immutable warnings required')
        for value in (self.source_url,self.attribution,self.license_url,self.timestamp_basis):
            if not isinstance(value,str) or not value or len(value)>2000: raise MarketValidationError('invalid provenance')


def bar_key(bar):
    return (bar.trade_date,bar.timestamp.isoformat() if bar.timestamp else '', {'night':0,'day':1,'combined':2}[bar.session],bar.interval)


@dataclass(frozen=True)
class MarketSeries:
    instrument: InstrumentRef
    bars: tuple[MarketBar,...]
    provenance: SourceProvenance

    def __post_init__(self):
        if not isinstance(self.instrument,InstrumentRef) or not isinstance(self.provenance,SourceProvenance): raise MarketValidationError('typed series metadata required')
        if not isinstance(self.bars,tuple) or not 1<=len(self.bars)<=100000: raise MarketValidationError('bounded nonempty immutable bars required')
        keys=set()
        for bar in self.bars:
            if not isinstance(bar,MarketBar) or bar.instrument!=self.instrument: raise MarketValidationError('cross-contract series')
            key=bar_key(bar)
            if key in keys: raise MarketValidationError('duplicate bar identity')
            keys.add(key)
            if not self.provenance.coverage_start<=bar.trade_date<=self.provenance.coverage_end: raise MarketValidationError('bar outside provenance coverage')
        if tuple(sorted(self.bars,key=bar_key))!=self.bars: raise MarketValidationError('bars must be chronologically sorted')
        if len({b.interval for b in self.bars})!=1: raise MarketValidationError('mixed bar intervals')


@dataclass(frozen=True)
class QuoteSnapshot:
    instrument: InstrumentRef
    last: Decimal
    trade_date: str
    session: str
    received_at: datetime
    as_of: datetime | None
    mode: str
    source: SourceProvenance
    previous_close: Decimal | None = None
    settlement: Decimal | None = None
    stale: bool = False
    status_reason: str = ''
    reference_kind: str = 'previous_observed_regular_session_close'

    def __post_init__(self):
        price(self.last);price(self.previous_close,optional=True);price(self.settlement,optional=True)
        utc(self.received_at);utc(self.as_of,optional=True);day(self.trade_date)
        if not isinstance(self.instrument,InstrumentRef) or not isinstance(self.source,SourceProvenance): raise MarketValidationError('typed quote metadata required')
        if self.mode!=self.source.mode: raise MarketValidationError('quote cannot change source freshness mode')
        if self.mode in ('realtime','delayed') and self.as_of is None: raise MarketValidationError('timed feed requires source event timestamp')
        if type(self.stale) is not bool: raise MarketValidationError('stale must be bool')
        if not isinstance(self.status_reason,str) or len(self.status_reason)>1000: raise MarketValidationError('invalid status reason')
        if self.reference_kind!='previous_observed_regular_session_close': raise MarketValidationError('unsupported previous close reference')
        if self.session not in ('day','night','combined'): raise MarketValidationError('invalid session')

    @property
    def change(self): return self.last-self.previous_close if self.previous_close is not None else None

    @classmethod
    def from_series(cls,series, *, stale=False, status_reason=''):
        bar=series.bars[-1]
        previous=next((b.close for b in reversed(series.bars[:-1]) if b.trade_date<bar.trade_date and b.session in ('day','combined')),None)
        return cls(series.instrument,bar.close,bar.trade_date,bar.session,series.provenance.received_at,bar.end,series.provenance.mode,series.provenance,previous,bar.settlement,stale,status_reason)
