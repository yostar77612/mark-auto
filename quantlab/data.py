"""Local-only normalized import and finite, explicit, versioned calendars.
TAIFEX 30-day CSV schema is based on an observed official 2026-10-08 sample.
Official daily API JSON and comma-delimited RPT are separately observed schemas.
Unobserved daily CSV and fixed-width RPT are rejected.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import csv
import hashlib
import io
import json
from .core import (Bar, Dataset, ValidationError, content_hash, validate_contract,
                   validate_date, validate_decimal, validate_int, validate_utc, freeze)

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
NORMALIZED_BAR_COLUMNS = ('timestamp', 'end', 'trade_date', 'session', 'contract_id', 'open', 'high', 'low', 'close', 'volume')
NORMALIZED_TICK_COLUMNS = ('timestamp', 'contract_id', 'price', 'quantity')


def parse_timestamp(value):
    """Require an explicit offset; normalize to UTC without guessing a timezone."""
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('explicit timezone-aware ISO timestamp required') from None


def taipei_timestamp(value):
    """TMF-era local wall time; Windows may optionally install tzdata."""
    if not isinstance(value, datetime) or value.tzinfo is not None or value.year < 2024:
        raise ValidationError('naive TMF-era local datetime required')
    try:
        zone = ZoneInfo('Asia/Taipei')
    except ZoneInfoNotFoundError:
        zone = timezone(timedelta(hours=8), 'Asia/Taipei')
    return value.replace(tzinfo=zone).astimezone(timezone.utc)


class SessionCalendar:
    """No weekday/holiday/expiry inference. Default intervals are [open,end).

    include_end=True explicitly accepts closing ticks. Contract-specific records
    shadow generic records for the same trade_date/session even after early close.
    closed=True records exclude a specific session; expires_at explicitly blocks
    later timestamps for a contract. These are supplied facts, never computed dates.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise TypeError('immutable SessionCalendar; construct a new version')
        object.__setattr__(self, name, value)

    def __init__(self, sessions, *, version):
        if not isinstance(version, str) or not version.strip():
            raise ValidationError('calendar version required')
        self.version, records, self._expiries = version, [], {}
        for supplied in sessions:
            if not isinstance(supplied, dict):
                raise ValidationError('calendar interval must be object')
            r = dict(supplied)
            for key in ('open', 'end', 'trade_date', 'session', 'source'):
                if key not in r:
                    raise ValidationError(f'calendar interval missing {key}')
            r['open'], r['end'] = parse_timestamp(r['open']), parse_timestamp(r['end'])
            validate_date(r['trade_date'], 'trade_date')
            if r['end'] <= r['open'] or r['session'] not in ('day', 'night') or not isinstance(r['source'], str) or not r['source']:
                raise ValidationError('invalid calendar interval/session/source')
            for flag in ('include_end', 'closed'):
                if flag in r and type(r[flag]) is not bool:
                    raise ValidationError(f'{flag} must be bool')
            if r.get('contract_id'):
                validate_contract(r['contract_id'])
            if 'expires_at' in r:
                if not r.get('contract_id'):
                    raise ValidationError('expiry requires specific contract')
                r['expires_at'] = parse_timestamp(r['expires_at'])
                old = self._expiries.get(r['contract_id'])
                if old is not None and old != r['expires_at']:
                    raise ValidationError('conflicting explicit expiry instants')
                self._expiries[r['contract_id']] = r['expires_at']
            records.append(r)
        records.sort(key=lambda r: (r['open'], r.get('contract_id') or '', r['session']))
        for i, r in enumerate(records):
            for other in records[i + 1:]:
                if other['open'] > r['end']:
                    break
                overlap = other['open'] < r['end'] or (other['open'] == r['end'] and r.get('include_end', False))
                if r.get('contract_id') == other.get('contract_id') and overlap:
                    raise ValidationError('overlapping calendar intervals at same specificity')
        self.sessions = freeze(tuple(records))
        self.hash = content_hash({'version': version, 'sessions': self.sessions})
        self._expiries = freeze(self._expiries)
        self._sealed = True

    def lookup(self, timestamp, contract_id):
        validate_utc(timestamp)
        validate_contract(contract_id)
        if contract_id in self._expiries and timestamp > self._expiries[contract_id]:
            raise ValidationError('contract expired according to explicit calendar')
        candidates = []
        for r in self.sessions:
            if r.get('contract_id') not in (None, '', contract_id):
                continue
            if not (r['open'] <= timestamp < r['end'] or (timestamp == r['end'] and r.get('include_end', False))):
                continue
            if not r.get('contract_id') and any(s.get('contract_id') == contract_id and s['trade_date'] == r['trade_date'] and s['session'] == r['session'] for s in self.sessions):
                continue
            candidates.append(r)
        if len(candidates) != 1 or candidates[0].get('closed', False):
            raise ValidationError('timestamp not covered by exactly one open calendar interval')
        return dict(candidates[0])


def _quality():
    return {'valid': True, 'errors': [], 'warnings': [], 'missing_intervals': 0, 'duplicate_rows': 0, 'malformed_rows': []}


def _dataset(bars, *, calendar, source_type, quality, extra=None):
    bars = tuple(sorted(bars, key=lambda b: (b.timestamp, b.contract_id, b.end)))
    if not bars:
        quality['errors'].append('empty dataset')
    quality['valid'] = not quality['errors']
    manifest = {
        'schema_version': 1, 'source_type': source_type, 'source_url': '', 'source_filename': '', 'source_hash': '',
        'imported_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'product': 'TMF',
        'coverage': {'start': bars[0].timestamp if bars else None, 'end': max(b.end for b in bars) if bars else None},
        'encoding': 'in_memory', 'schema': 'normalized_v1', 'timezone': 'Asia/Taipei',
        'calendar_version': calendar.version, 'calendar_hash': calendar.hash, 'aggregation_version': 'explicit-session-v1',
        'license_note': 'No redistribution permission inferred; source license must be checked.',
        'validation_status': 'valid' if quality['valid'] else 'invalid', 'data_hash': content_hash(bars),
        'endpoint_convention': '[start,end); explicitly included session close assigned to final bucket',
    }
    if extra:
        manifest.update(extra)
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
    return Dataset(bars, manifest, quality)


def validate_dataset(dataset):
    """Recompute hashes and validate records, never trust an imported claim."""
    if not isinstance(dataset, Dataset) or not dataset.bars:
        raise ValidationError('nonempty Dataset required')
    if dataset.manifest.get('source_type') not in ('official_local', 'synthetic', 'proxy'):
        raise ValidationError('explicit source classification required')
    if dataset.manifest.get('validation_status') != 'valid' or dataset.quality.get('valid') is not True or dataset.quality.get('errors'):
        raise ValidationError('dataset quality is not valid')
    if dataset.manifest.get('data_hash') != content_hash(dataset.bars):
        raise ValidationError('data hash mismatch')
    manifest = {k: v for k, v in dataset.manifest.items() if k not in ('imported_at', 'manifest_hash')}
    if dataset.manifest.get('manifest_hash') != content_hash(manifest):
        raise ValidationError('manifest hash mismatch')
    previous = {}
    for bar in dataset.bars:
        bar.__post_init__()
        if bar.contract_id in previous and bar.timestamp < previous[bar.contract_id]:
            raise ValidationError('overlapping or unsorted bars')
        previous[bar.contract_id] = bar.end


def aggregate_ticks(ticks, *, timeframe_minutes, calendar):
    """Ticks: UTC timestamp, contract_id, Decimal price, positive int quantity.

    Optional trade_id deduplicates identical payloads, conflicts fail closed.
    No trade_id means all same-time trades are retained. source_type defaults to
    synthetic. Unobserved intervals are never fabricated and block a backtest.
    """
    validate_int(timeframe_minutes, 'timeframe_minutes', 1)
    if timeframe_minutes > 1440 or len(ticks) > MAX_ROWS:
        raise ValidationError('aggregation resource limit exceeded')
    quality, groups, identities, source_types = _quality(), defaultdict(list), {}, set()
    quality['warnings'].append('No proof of feed completeness or real-market execution.')
    width = timedelta(minutes=timeframe_minutes)
    for index, supplied in enumerate(ticks):
        try:
            t = dict(supplied)
            timestamp = t['timestamp']
            validate_utc(timestamp)
            validate_contract(t['contract_id'])
            validate_decimal(t['price'], 'tick price', Decimal('1'), tick=True)
            validate_int(t['quantity'], 'tick quantity', 1)
            source_type = t.get('source_type', 'synthetic')
            if source_type not in ('synthetic', 'proxy', 'official_local'):
                raise ValidationError('invalid source_type')
            source_types.add(source_type)
            session = calendar.lookup(timestamp, t['contract_id'])
            if 'trade_date' in t and t['trade_date'] != session['trade_date']:
                raise ValidationError('tick trade_date disagrees with calendar')
            if 'session' in t and t['session'] != session['session']:
                raise ValidationError('tick session disagrees with calendar')
            if t.get('trade_id'):
                identity = (t['contract_id'], session['trade_date'], str(t['trade_id']))
                payload = content_hash(t)
                if identity in identities:
                    if identities[identity] != payload:
                        raise ValidationError('conflicting duplicate trade_id')
                    quality['duplicate_rows'] += 1
                    continue
                identities[identity] = payload
            offset = timestamp - session['open']
            bucket = offset // width
            if timestamp == session['end']:
                bucket = max(0, (offset - timedelta(microseconds=1)) // width)
            start = session['open'] + bucket * width
            key = (start, min(start + width, session['end']), session['trade_date'], session['session'], t['contract_id'], session['open'])
            groups[key].append((timestamp, index, t['price'], t['quantity']))
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            quality['malformed_rows'].append({'row': index + 1, 'error': str(exc)})
    if quality['malformed_rows']:
        quality['errors'].append('malformed ticks; partial data cannot be backtested')
    if len(source_types) > 1:
        quality['errors'].append('mixed source classifications prohibited')
    bars, previous = [], {}
    for key, values in sorted(groups.items()):
        start, end, trade_date, session, contract_id, session_open = key
        values.sort(key=lambda x: (x[0], x[1]))
        prices = [v[2] for v in values]
        bars.append(Bar(start, end, trade_date, session, contract_id, prices[0], max(prices), min(prices), prices[-1], sum(v[3] for v in values), content_hash(values)))
        scope = (contract_id, session_open)
        if scope in previous and start > previous[scope]:
            quality['missing_intervals'] += int((start - previous[scope]) / width)
        previous[scope] = end
    if quality['missing_intervals']:
        quality['errors'].append('unobserved intervals: no-trade versus missing-feed distinction unavailable')
    return _dataset(bars, calendar=calendar, source_type=sorted(source_types)[0] if source_types else 'synthetic', quality=quality,
                    extra={'timeframe_minutes': timeframe_minutes, 'schema': 'normalized_ticks_v1', 'source_hash': content_hash(ticks),
                           'duplicate_policy': 'explicit trade_id dedup only; same timestamps preserved'})


def _integer_text(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValidationError('nonnegative integer text required')
    return int(value)


OFFICIAL_TICK_COLUMNS = ('成交日期', '商品代號', '到期月份(週別)', '成交時間', '成交價格', '成交數量(B+S)', '近月價格', '遠月價格', '開盤集合競價')
OFFICIAL_SCHEMA_SOURCE = 'https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData'


def import_taifex(path: Path, *, kind: str, calendar: SessionCalendar, contract_id=None, encoding=None):
    """Local CSV/RPT importer; no fetching, archives, pickle, or arbitrary code.

    kinds ticks/ticks_csv support the observed TAIFEX 30-day CSV schema only.
    synthetic_bars/proxy_bars/synthetic_ticks/proxy_ticks support normalized
    interchange. Synthetic official-format tests use synthetic_taifex_ticks.
    daily_json supports observed DailyMarketReportFut API arrays as session bars.
    Unobserved daily CSV and fixed-width RPT schemas are rejected.
    Outright B+S quantity is divided by two and must be even. Spread records
    are excluded and counted; official daily inclusive volume has a different scope.
    """
    path = Path(path)
    if kind in ('daily_json', 'synthetic_daily_json'):
        return _import_daily_json(path, kind=kind, calendar=calendar, contract_id=contract_id, encoding=encoding)
    if path.suffix.lower() not in ('.csv', '.rpt') or not path.is_file():
        raise ValidationError('local .csv/.rpt file required')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationError('file-size limit exceeded')
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValidationError('file-size limit exceeded')
    if encoding is not None and encoding.lower() not in ('utf-8', 'utf-8-sig', 'big5', 'cp950'):
        raise ValidationError('encoding must be UTF-8, Big5 or CP950')
    decoded = None
    for candidate in ([encoding] if encoding else ['utf-8-sig', 'cp950']):
        try:
            decoded, encoding = raw.decode(candidate), candidate
            break
        except UnicodeDecodeError:
            pass
    if decoded is None or '\x00' in decoded:
        raise ValidationError('file encoding invalid or binary input')
    reader = csv.DictReader(io.StringIO(decoded, newline=''), strict=True)
    try:
        columns = [c.strip().lstrip('\ufeff') for c in (reader.fieldnames or [])]
    except csv.Error as exc:
        raise ValidationError(f'malformed CSV header: {exc}') from None
    reader.fieldnames = columns
    official = kind in ('ticks', 'ticks_csv', 'ticks_rpt', 'synthetic_taifex_ticks')
    normalized = kind in ('synthetic_bars', 'proxy_bars', 'synthetic_ticks', 'proxy_ticks')
    if not official and not normalized:
        raise ValidationError(f'unsupported schema/kind {kind!r}; observed columns: {columns!r}; daily and fixed-width RPT NOT_VERIFIED')
    expected = OFFICIAL_TICK_COLUMNS if official else NORMALIZED_BAR_COLUMNS if kind.endswith('_bars') else NORMALIZED_TICK_COLUMNS
    allowed = set(expected) if official else set(expected) | {'source_id', 'trade_id'}
    if not set(expected).issubset(columns) or len(columns) != len(set(columns)) or set(columns) - allowed:
        raise ValidationError(f'unsupported schema; required {expected!r}; observed columns: {columns!r}')
    if contract_id is not None:
        validate_contract(contract_id)
    source_type = ('synthetic' if kind == 'synthetic_taifex_ticks' else 'official_local') if official else kind.split('_')[0]
    quality, bars, ticks, seen = _quality(), [], [], set()
    excluded_spreads = {'rows': 0, 'b_plus_s_quantity': 0}
    quality['warnings'].append('Local content classification does not authenticate exchange provenance or grant redistribution permission.')
    if official:
        quality['warnings'].append('Outright-only ticks: B+S / 2. Daily reports can include allocated spread volume; do not compare totals without scope reconciliation.')
    try:
        for row_number, row in enumerate(reader, 2):
            if row_number > MAX_ROWS + 1:
                raise ValidationError('row limit exceeded')
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValidationError('wrong column count')
                row = {k: v.strip() for k, v in row.items()}
                if official:
                    if row['商品代號'] != 'TMF':
                        continue
                    months = row['到期月份(週別)'].split('/')
                    if len(months) == 2:
                        for month in months:
                            validate_contract('TAIFEX:TMF:' + month)
                        if contract_id is None or contract_id.rsplit(':', 1)[1] in months:
                            excluded_spreads['rows'] += 1
                            excluded_spreads['b_plus_s_quantity'] += _integer_text(row['成交數量(B+S)'])
                        continue
                    cid = 'TAIFEX:TMF:' + row['到期月份(週別)']
                    if contract_id is not None and cid != contract_id:
                        continue
                    validate_contract(cid)
                    if not (len(row['成交日期']) == 8 and len(row['成交時間']) == 6):
                        raise ValidationError('unexpected date/time precision')
                    timestamp = taipei_timestamp(datetime.strptime(row['成交日期'] + row['成交時間'], '%Y%m%d%H%M%S'))
                    if source_type == 'official_local' and row['成交日期'] < '20240729':
                        raise ValidationError('TMF data predates official launch 2024-07-29')
                    quantity = _integer_text(row['成交數量(B+S)'])
                    if quantity % 2:
                        raise ValidationError('B+S quantity must be even for single-sided volume')
                    if row['近月價格'] != '-' or row['遠月價格'] != '-':
                        raise ValidationError('spread trade unsupported')
                    ticks.append({'timestamp': timestamp, 'contract_id': cid, 'price': Decimal(row['成交價格']),
                                  'quantity': quantity // 2, 'source_type': source_type, 'source_row': row_number})
                    continue
                if contract_id is not None and row['contract_id'] != contract_id:
                    continue
                timestamp = parse_timestamp(row['timestamp'])
                session = calendar.lookup(timestamp, row['contract_id'])
                if kind.endswith('_ticks'):
                    ticks.append({'timestamp': timestamp, 'contract_id': row['contract_id'], 'price': Decimal(row['price']),
                                  'quantity': _integer_text(row['quantity']), 'trade_id': row.get('trade_id', ''), 'source_type': source_type})
                    continue
                bar = Bar(timestamp, parse_timestamp(row['end']), row['trade_date'], row['session'], row['contract_id'],
                          *(Decimal(row[name]) for name in ('open', 'high', 'low', 'close')),
                          _integer_text(row['volume']), row.get('source_id', f'line:{row_number}'))
                if bar.end > session['end'] or bar.trade_date != session['trade_date'] or bar.session != session['session']:
                    raise ValidationError('bar disagrees with calendar interval')
                identity = (bar.timestamp, bar.contract_id)
                if identity in seen:
                    quality['duplicate_rows'] += 1
                    raise ValidationError('duplicate bar identity')
                seen.add(identity)
                bars.append(bar)
            except (ValidationError, InvalidOperation, ValueError, KeyError) as exc:
                quality['malformed_rows'].append({'row': row_number, 'error': str(exc)})
    except csv.Error as exc:
        quality['errors'].append(f'malformed CSV: {exc}')
    extra = {'source_filename': path.name, 'source_hash': hashlib.sha256(raw).hexdigest(), 'encoding': encoding,
             'schema': 'taifex_30day_csv_observed_20261008_v1' if official else kind + '_v1',
             'source_url': OFFICIAL_SCHEMA_SOURCE if official else '',
             'official_schema_status': 'observed' if official else 'not_applicable',
             'volume_convention': 'outright B+S / 2; spread rows excluded' if official else 'single-sided contracts',
             'excluded_spreads': excluded_spreads if official else None}
    if official or kind.endswith('_ticks'):
        result = aggregate_ticks(ticks, timeframe_minutes=1, calendar=calendar)
        quality['errors'].extend(result.quality['errors'])
        quality['warnings'].extend(result.quality['warnings'])
        quality['missing_intervals'] = result.quality['missing_intervals']
        quality['duplicate_rows'] = result.quality['duplicate_rows']
        quality['malformed_rows'].extend(result.quality['malformed_rows'])
        bars = list(result.bars)
        extra['timeframe_minutes'] = 1
    else:
        previous = {}
        for bar in sorted(bars, key=lambda b: (b.timestamp, b.contract_id)):
            scope = (bar.contract_id, bar.trade_date, bar.session)
            if scope in previous:
                if bar.timestamp < previous[scope]:
                    quality['errors'].append('overlapping bars')
                elif bar.timestamp > previous[scope]:
                    quality['missing_intervals'] += 1
            previous[scope] = bar.end
        if quality['missing_intervals']:
            quality['errors'].append('gaps between bars; completeness unavailable')
    if quality['malformed_rows']:
        quality['errors'].append('malformed rows; partial data cannot be backtested')
    return _dataset(bars, calendar=calendar, source_type=source_type, quality=quality, extra=extra)


def _import_daily_json(path, *, kind, calendar, contract_id, encoding):
    """Observed official DailyMarketReportFut schema; whole-session bars only."""
    if path.suffix.lower() != '.json' or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationError('bounded local daily API .json file required')
    if encoding not in (None, 'utf-8', 'utf-8-sig'):
        raise ValidationError('daily API JSON must be UTF-8')
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValidationError('file-size limit exceeded')
    try:
        rows = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, ValueError):
        raise ValidationError('invalid daily API JSON') from None
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValidationError('daily API JSON requires bounded array')
    if contract_id is not None:
        validate_contract(contract_id)
    bars, seen, quality = [], set(), _quality()
    required = {'Date', 'Contract', 'ContractMonth(Week)', 'Open', 'High', 'Low', 'Last', 'Volume', 'TradingSession'}
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict) or not required <= row.keys():
                raise ValidationError(f'unsupported daily schema; required {sorted(required)}; observed {list(row) if isinstance(row, dict) else type(row).__name__}')
            if row['Contract'] != 'TMF':
                continue
            if '/' in row['ContractMonth(Week)']:
                continue
            cid = 'TAIFEX:TMF:' + row['ContractMonth(Week)']
            if contract_id is not None and cid != contract_id:
                continue
            validate_contract(cid)
            trade_date = datetime.strptime(row['Date'], '%Y%m%d').date().isoformat()
            session_name = {'一般': 'day', '盤後': 'night'}.get(row['TradingSession'])
            if session_name is None:
                raise ValidationError('unrecognized daily session')
            candidates = {}
            for record in calendar.sessions:
                if record['trade_date'] == trade_date and record['session'] == session_name and record.get('contract_id') in (None, '', cid):
                    actual = calendar.lookup(record['open'], cid)
                    candidates[(actual['open'], actual['end'])] = actual
            if len(candidates) != 1:
                raise ValidationError('daily session lacks unique explicit calendar interval')
            session = next(iter(candidates.values()))
            identity = (cid, trade_date, session_name)
            if identity in seen:
                quality['duplicate_rows'] += 1
                raise ValidationError('duplicate daily session identity')
            seen.add(identity)
            bar = Bar(session['open'], session['end'], trade_date, session_name, cid,
                      *(Decimal(row[name]) for name in ('Open', 'High', 'Low', 'Last')),
                      _integer_text(row['Volume']), f'line:{index}')
            bars.append(bar)
        except (ValidationError, ValueError, TypeError, InvalidOperation, KeyError) as exc:
            quality['malformed_rows'].append({'row': index, 'error': str(exc)})
    if quality['malformed_rows']:
        quality['errors'].append('malformed daily rows; partial data cannot be backtested')
    quality['warnings'].append('Whole-session bars only; minute paths are unavailable. SettlementPrice is not treated as a trade or close.')
    return _dataset(bars, calendar=calendar, source_type='synthetic' if kind == 'synthetic_daily_json' else 'official_local', quality=quality,
                    extra={'source_filename': path.name, 'source_hash': hashlib.sha256(raw).hexdigest(), 'encoding': 'utf-8-sig',
                           'schema': 'taifex_daily_market_api_observed_20261008_v1', 'source_url': 'https://openapi.taifex.com.tw/v1/DailyMarketReportFut',
                           'official_schema_status': 'observed', 'aggregation_version': 'whole-session-v1',
                           'volume_convention': 'official daily Volume; can include spread allocation', 'bar_granularity': 'session'})
