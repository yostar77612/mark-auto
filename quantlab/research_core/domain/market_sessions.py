"""Bounded history responsibility; validation, digest and publication ordering preserved."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from quantlab.errors import fail
from quantlab.market import InstrumentRef, MarketSeries, MarketValidationError, day, utc
from quantlab.shared.time import aware_iso_utc


MAX_BARS = 100000


MAX_SESSIONS = 256


PRODUCT_SOURCES = {'TX': 'https://www.taifex.com.tw/cht/2/tX', 'MTX': 'https://www.taifex.com.tw/cht/2/mTX', 'TMF': 'https://www.taifex.com.tw/cht/2/tMF'}


UTC = timezone.utc


TAIPEI = timezone(timedelta(hours=8))


def _fail(message):
    fail(message, MarketValidationError)


def _stamp(text):
    if not isinstance(text, str) or len(text) > 40:
        _fail('invalid session timestamp')
    try:
        value = aware_iso_utc(text)
        if value.tzinfo is None:
            raise ValueError()
        return value.astimezone(UTC)
    except ValueError:
        _fail('explicit session timezone required')


@dataclass(frozen=True)
class MarketSession:
    instrument: InstrumentRef
    trade_date: str
    session: str
    open: datetime
    end: datetime
    include_end: bool = False
    source: str = ''

    def __post_init__(self):
        if not isinstance(self.instrument, InstrumentRef) or self.instrument.exchange != 'TAIFEX':
            _fail('explicit supported futures contract required')
        day(self.trade_date)
        utc(self.open)
        utc(self.end)
        if self.session not in ('day', 'night') or type(self.include_end) is not bool:
            _fail('invalid session flags')
        if not timedelta(0) < self.end - self.open <= timedelta(hours=24):
            _fail('session must be positive and at most 24 hours')
        if self.open.second or self.open.microsecond or self.end.second or self.end.microsecond:
            _fail('session boundaries must be minute aligned')
        native = self.instrument.contract_id.split(':')[1]
        if self.source != PRODUCT_SOURCES[native]:
            _fail('fixed independent official product reference required')
        # Dates are explicitly supplied, never inferred from weekends/holidays.
        local_open = self.open.astimezone(TAIPEI)
        if self.session == 'day' and (self.trade_date != local_open.date().isoformat() or self.end.astimezone(TAIPEI).date() != local_open.date()):
            _fail('day session must use its explicit local trade date')
        if self.session == 'night' and not local_open.date().isoformat() < self.trade_date:
            _fail('night attributed trade date must be explicitly later than its opening date')
        if (datetime.fromisoformat(self.trade_date).date() - local_open.date()).days > 14:
            _fail('session trade date attribution exceeds bounded window')


def _session_dict(s):
    return dict(
        contract_id=s.instrument.contract_id,
        trade_date=s.trade_date,
        session=s.session,
        open=s.open.isoformat(),
        end=s.end.isoformat(),
        include_end=s.include_end,
        source=s.source,
    )


def session_from_dict(value):
    keys = {'contract_id', 'trade_date', 'session', 'open', 'end', 'include_end', 'source'}
    if not isinstance(value, dict) or set(value) != keys:
        _fail('session fields do not match supported schema')
    cid = value['contract_id']
    if not isinstance(cid, str) or len(cid) > 40:
        _fail('invalid contract identity')
    parts = cid.split(':')
    if len(parts) != 3 or parts[1] not in PRODUCT_SOURCES:
        _fail('invalid contract identity')
    inst = InstrumentRef(parts[0], {'MTX': 'MXF'}.get(parts[1], parts[1]), cid, parts[2])
    return MarketSession(inst, value['trade_date'], value['session'], _stamp(value['open']), _stamp(value['end']), value['include_end'], value['source'])


def _sessions(values):
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_SESSIONS:
        _fail('bounded explicit sessions required')
    if any(not isinstance(s, MarketSession) for s in values):
        _fail('typed session policy required')
    result = tuple(sorted(values, key=lambda s: (s.instrument.contract_id, s.open, s.trade_date, s.session)))
    if sum(int((s.end - s.open).total_seconds() / 60) for s in result) > MAX_BARS:
        _fail('session minute budget exceeded')
    for i, s in enumerate(result):
        for other in result[i + 1 :]:
            if s.instrument == other.instrument and (s.trade_date, s.session) == (other.trade_date, other.session):
                _fail('duplicate contract trade-date session')
            if s.instrument == other.instrument and (other.open < s.end or (other.open == s.end and s.include_end)):
                _fail('overlapping explicit sessions')
    return result


@dataclass(frozen=True)
class HistoryLoad:
    series: tuple[MarketSeries, ...]
    policy_hash: str
    source_hash: str
    counters: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]
    cache_id: str


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()
