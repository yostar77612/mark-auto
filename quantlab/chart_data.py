"""Read-only, deterministic OHLCV aggregation; version 1.

No interpolation or upsampling. Minute bins anchor at explicit session_open;
short expiry/session bins end at session_end. Gaps are retained as partial bins
and warnings, never invented bars. Exact duplicates deduplicate; conflicts reject.
Unknown volume stays None. Daily combines known sessions by exchange trade_date;
weekly groups ISO exchange-date weeks, never civil timestamps. Without an explicit
calendar daily/weekly completeness is unknown and outputs remain partial. Weekly
closure additionally needs as_of beyond ISO week's Sunday (UTC, conservative).

SessionCalendar.lookup is reused for TMF without relaxing its trading contract.
Other display instruments use explicitly supplied session_open/session_end; the
TMF-only calendar cannot certify another instrument. Minute outputs use scheduled
bucket end as availability time and partial=True until that end when as_of supplied.
"""
from dataclasses import dataclass, replace
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from .market import MarketBar, MarketValidationError

AGGREGATION_VERSION = 'market-ohlcv-v1'
TIMEFRAMES = ('1m', '3m', '5m', '15m', '30m', '60m', '1d', '1w')


@dataclass(frozen=True)
class AggregationResult:
    bars: tuple[MarketBar, ...]
    warnings: tuple[str, ...] = ()
    duplicate_count: int = 0
    source_ids: tuple[str, ...] = ()


def _fail(message):
    raise MarketValidationError(message)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        _fail('as_of must be a timezone-aware UTC datetime')


def _order(bar):
    # Exchange trade date and night/day order also work for official date-only rows.
    return (bar.contract_id, bar.trade_date, {'night': 0, 'day': 1, 'combined': 2}[bar.session],
            bar.timestamp or datetime.min.replace(tzinfo=timezone.utc), bar.interval)


def _bounds(bar, calendar):
    opening, closing = bar.session_open, bar.session_end
    if calendar is not None:
        if not bar.contract_id.startswith('TAIFEX:TMF:'):
            _fail('TMF SessionCalendar cannot certify another display instrument')
        if bar.timestamp is not None:
            record = calendar.lookup(bar.timestamp, bar.contract_id)
            if (record['trade_date'], record['session']) != (bar.trade_date, bar.session):
                _fail('bar trade_date/session disagrees with explicit calendar')
            if opening is not None and opening != record['open']:
                _fail('bar session_open disagrees with explicit calendar')
            if closing is not None and closing != record['end']:
                _fail('bar session_end disagrees with explicit calendar')
            opening, closing = record['open'], record['end']
    if bar.timestamp is not None:
        if opening is None or closing is None:
            _fail('intraday bars need explicit session bounds or calendar')
        if not opening <= bar.timestamp < bar.end <= closing:
            _fail('bar interval exceeds explicit session bounds')
    return opening, closing


def _expected(calendar, contract, dates):
    if calendar is None:
        return []
    if not contract.startswith('TAIFEX:TMF:'):
        _fail('TMF SessionCalendar cannot certify another display instrument')
    result = []
    for record in calendar.sessions:
        if record['trade_date'] not in dates:
            continue
        try:
            chosen = calendar.lookup(record['open'], contract)
        except ValueError:
            continue
        identity = (chosen['open'], chosen['end'], chosen['trade_date'], chosen['session'])
        if identity not in result:
            result.append(identity)
    return result


def _coverage(group, expected):
    if not expected:
        return False
    for opening, closing, trade_date, session in expected:
        selected = [b for b in group if b.trade_date == trade_date and b.session == session]
        if not selected or any(b.partial for b in selected):
            return False
        if all(b.interval == 'session' and b.timestamp is None for b in selected):
            continue
        if any(b.timestamp is None for b in selected):
            return False
        selected.sort(key=lambda b: b.timestamp)
        if selected[0].timestamp != opening or selected[-1].end != closing:
            return False
        if any(a.end != b.timestamp for a, b in zip(selected, selected[1:])):
            return False
    # Calendar must certify every input session too, not just a subset.
    return all(any((b.trade_date, b.session) == (e[2], e[3]) for e in expected) for b in group)


def _merge(group, *, timeframe, timestamp, end, session, opening, closing, partial):
    volumes = [b.volume for b in group]
    sources = sorted({b.source_id for b in group})
    source_id = sources[0] if len(sources) == 1 else 'aggregate:' + hashlib.sha256(
        json.dumps(sources, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return replace(group[0], open=group[0].open, high=max(b.high for b in group),
                   low=min(b.low for b in group), close=group[-1].close,
                   volume=None if None in volumes else sum(volumes), interval=timeframe,
                   timestamp=timestamp, end=end, session=session, session_open=opening,
                   session_end=closing, partial=partial, source_id=source_id, settlement=None)


def aggregate_bars(bars, *, timeframe, calendar=None, as_of=None):
    """Aggregate a homogeneous source resolution per contract; sort deterministically.

    Conflicting duplicate identity, overlapping input, mixed source resolutions,
    ambiguous session boundaries and non-dividing/downsampled minutes fail closed.
    as_of is caller-supplied (never wall clock); unavailable input ends reject.
    """
    if timeframe not in TIMEFRAMES:
        _fail('unsupported timeframe')
    if as_of is not None:
        _utc(as_of)
    bars = tuple(bars)
    warnings, unique, duplicates = [], {}, 0
    for bar in bars:
        if not isinstance(bar, MarketBar):
            _fail('expected MarketBar')
        identity = (bar.contract_id, bar.trade_date, bar.session, bar.timestamp, bar.interval)
        if identity in unique:
            if unique[identity] != bar:
                _fail('conflicting duplicate market bar')
            duplicates += 1
        else:
            unique[identity] = bar
        if as_of is not None and bar.end is not None and bar.end > as_of:
            _fail('input bar is not available at as_of')
    ordered = sorted(unique.values(), key=_order)
    if list(bars) != sorted(bars, key=_order):
        warnings.append('out-of-order input sorted by contract/trade_date/session/time')
    if duplicates:
        warnings.append(f'{duplicates} exact duplicate bars removed')
    contracts = {}
    for bar in ordered:
        contracts.setdefault(bar.contract_id, []).append(bar)
    output = []
    for contract, source in contracts.items():
        if len({b.instrument for b in source}) != 1:
            _fail('one contract has conflicting instrument definitions')
        if len({b.interval for b in source}) != 1:
            _fail('mixed source resolutions are ambiguous')
        for previous, current in zip(source, source[1:]):
            if previous.timestamp is not None and current.timestamp is not None and current.timestamp < previous.end:
                _fail('overlapping or chronologically inconsistent source bars')
            if (previous.timestamp is not None and current.timestamp is not None
                    and (previous.trade_date, previous.session) == (current.trade_date, current.session)
                    and current.timestamp > previous.end):
                warnings.append(f'{contract} {previous.end.isoformat()}: missing source interval before {current.timestamp.isoformat()}')
        groups = {}
        if timeframe.endswith('m'):
            target = int(timeframe[:-1])
            if not source[0].interval.endswith('m'):
                _fail('daily/session/weekly source cannot manufacture intraday bars')
            minutes = int(source[0].interval[:-1])
            if target < minutes or target % minutes:
                _fail('target minutes must be a multiple of source minutes')
            for bar in source:
                opening, closing = _bounds(bar, calendar)
                if bar.timestamp is None:
                    _fail('minute source requires explicit timestamps')
                delta = (bar.timestamp - opening).total_seconds()
                if delta % (minutes * 60):
                    _fail('source bar is not session anchored')
                nominal_end = min(bar.timestamp + timedelta(minutes=minutes), closing)
                if bar.end != nominal_end and not (bar.partial and bar.end < nominal_end):
                    _fail('source duration disagrees with interval')
                start = opening + timedelta(minutes=(int(delta) // (target * 60)) * target)
                end = min(start + timedelta(minutes=target), closing)
                if bar.end > end:
                    _fail('source bar straddles target bucket')
                key = (bar.trade_date, bar.session, opening, closing, start, end)
                groups.setdefault(key, []).append(bar)
            for key, group in groups.items():
                _, session, opening, closing, start, end = key
                complete = group[0].timestamp == start and group[-1].end == end
                complete = complete and all(a.end == b.timestamp for a, b in zip(group, group[1:]))
                partial = not complete or any(b.partial for b in group) or (as_of is not None and as_of < end)
                if partial:
                    warnings.append(f'{contract} {start.isoformat()}: partial/gapped {timeframe} bar')
                output.append(_merge(group, timeframe=timeframe, timestamp=start, end=end,
                                     session=session, opening=opening, closing=closing, partial=partial))
        else:
            if source[0].interval == '1w' and timeframe == '1d':
                _fail('weekly source cannot manufacture daily bars')
            for bar in source:
                if bar.timestamp is not None and bar.interval.endswith('m'):
                    _bounds(bar, calendar)
                day = date.fromisoformat(bar.trade_date)
                key = bar.trade_date if timeframe == '1d' else day.isocalendar()[:2]
                groups.setdefault(key, []).append(bar)
            for key, group in groups.items():
                dates = {b.trade_date for b in group}
                if timeframe == '1w':
                    year, week = key
                    monday = date.fromisocalendar(year, week, 1)
                    dates = {(monday + timedelta(days=i)).isoformat() for i in range(7)}
                expected = _expected(calendar, contract, dates)
                complete = _coverage(group, expected)
                if timeframe == '1w':
                    week_end = datetime.combine(monday + timedelta(days=7), time(), timezone.utc)
                    complete = complete and as_of is not None and as_of >= week_end
                if as_of is not None and expected:
                    complete = complete and all(e[1] <= as_of for e in expected)
                partial = not complete or any(b.partial for b in group)
                if partial:
                    warnings.append(f'{contract} {key}: incomplete or unverified session coverage')
                timed = all(b.timestamp is not None for b in group)
                output.append(_merge(group, timeframe=timeframe,
                                     timestamp=group[0].timestamp if timed else None,
                                     end=group[-1].end if timed else None, session='combined',
                                     opening=None, closing=None, partial=partial))
    return AggregationResult(tuple(sorted(output, key=_order)), tuple(warnings), duplicates,
                             tuple(sorted({b.source_id for b in ordered})))
