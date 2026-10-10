"""Offline, fail-closed acceptance of explicitly evidenced official history.

This certifies an integration input, never sufficient history for economic ranking.
No network, inferred annual calendar, gap filling, or continuous-contract stitching.
Pinned: python -m tools.validate_official_history --cache CACHE --daily-json FILE --output NEW_DIR
Range: python -m tools.validate_official_history --cache CACHE --start YYYY-MM-DD
  --end YYYY-MM-DD --contract TAIFEX:TMF:YYYYMM --calendar SESSIONS.json
  --calendar-version VERSION --daily-csv DAILY.csv [--daily-csv MORE.csv]
  --as-of OFFSET_TIMESTAMP --output NEW_DIR
Range mode requires adjacent DAILY-source.json with download URL and SHA256.
Every requested date/session is accepted or the entire range is rejected.
"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import csv
import io
import hashlib
import json
from pathlib import Path

from quantlab.core import ValidationError, canonical_json, validate_contract, validate_date
from quantlab.data import SessionCalendar, import_taifex, validate_dataset, parse_timestamp, _dataset
from quantlab.downloads import inspect_archive, official_url

CONTRACT = 'TAIFEX:TMF:202610'
TICK_HASH = '6807f4c3b7f977cb7e5109b1135fe69bbfe18d7c6b71a445e6576bb6be6163a8'
ARCHIVE_HASH = 'e622c9375667f3b2b3544b4f4548eb07b6460646de2652bd7cff319e9c7c32ff'
DAILY_HASH = 'ca6f0f5ab806ea74847391c1184fb809fb89059cab55727f4107f4b31aa868b5'
SPEC = 'https://www.taifex.com.tw/cht/2/tMF'
DAILY_SOURCE = 'https://openapi.taifex.com.tw/v1/DailyMarketReportFut'


def verified_oct8_calendar():
    """Finite observed non-expiry sessions; not a generator for other dates."""
    return SessionCalendar([
        {'open': '2026-10-07T15:00:00+08:00', 'end': '2026-10-08T05:00:00+08:00',
         'trade_date': '2026-10-08', 'session': 'night', 'contract_id': CONTRACT,
         'include_end': True, 'source': SPEC + '; ' + DAILY_SOURCE},
        {'open': '2026-10-08T08:45:00+08:00', 'end': '2026-10-08T13:45:00+08:00',
         'trade_date': '2026-10-08', 'session': 'day', 'contract_id': CONTRACT,
         'include_end': True, 'source': SPEC + '; ' + DAILY_SOURCE},
    ], version='verified-TMF202610-20261008-two-sessions-v2')


def validate_full_sessions(dataset, calendar, contract_id):
    """Check leading, internal, trailing and entirely missing minute buckets.

    Independently recheck exact minute buckets beyond importer quality flags.
    Even genuine no-trade minutes are rejected here rather than fabricated.
    """
    validate_dataset(dataset)
    expected = {}
    for record in calendar.sessions:
        if record.get('closed') or record.get('contract_id') not in (None, '', contract_id):
            continue
        actual = calendar.lookup(record['open'], contract_id)
        if actual['open'] != record['open'] or actual['end'] != record['end']:
            continue
        stamp = record['open']
        while stamp < record['end']:
            end = min(stamp + timedelta(minutes=1), record['end'])
            expected[(stamp, end, record['trade_date'], record['session'], contract_id)] = True
            stamp = end
    observed = [(b.timestamp, b.end, b.trade_date, b.session, b.contract_id) for b in dataset.bars]
    missing = set(expected) - set(observed)
    unexpected = set(observed) - set(expected)
    if not expected or missing or unexpected or len(observed) != len(set(observed)):
        raise ValidationError(f'full-session coverage failed: missing={len(missing)}, unexpected={len(unexpected)}, duplicate={len(observed)-len(set(observed))}')
    return {'expected_minutes': len(expected), 'observed_minutes': len(observed),
            'missing_minutes': 0, 'unexpected_minutes': 0, 'boundaries_checked': True}


def verified_bytes(path, sha):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValidationError('source hash mismatch: ' + Path(path).name)
    return raw


def cache_inventory(cache):
    """Authenticate cached bytes against recorded hashes, without promoting dates."""
    manifest = json.loads((Path(cache) / 'latest.json').read_text())
    results = []
    for record in manifest['archives']:
        status, error = 'hash_verified_only', None
        try:
            official_url(record['source_url'])
            raw = verified_bytes(record['archive_path'], record['sha256'])
            members = inspect_archive(raw, record['format'])
            extracted = {m['name']: m['sha256'] for m in members}
            for member in record['files']:
                verified_bytes(member['path'], member['sha256'])
                if extracted.get(member['name']) != member['sha256']:
                    raise ValidationError('extracted file differs from archive')
        except (OSError, ValueError, KeyError) as exc:
            status, error = 'quarantined', str(exc)
        results.append({'trade_date': record['trade_date'], 'archive_sha256': record['sha256'],
                        'source_url': record['source_url'], 'status': status, 'error': error,
                        'ranking_eligible': False})
    return results


def load_verified_oct8(cache, daily_json):
    """Return actual immutable Dataset plus narrow acceptance evidence."""
    base = Path(cache) / '2026-10-08' / 'csv' / ARCHIVE_HASH
    archive = verified_bytes(base / 'archive.zip', ARCHIVE_HASH)
    members = inspect_archive(archive, 'csv')
    if len(members) != 1 or members[0]['sha256'] != TICK_HASH:
        raise ValidationError('pinned archive member mismatch')
    tick_path = base / 'Daily_2026_10_08.csv'
    verified_bytes(tick_path, TICK_HASH)
    verified_bytes(daily_json, DAILY_HASH)
    calendar = verified_oct8_calendar()
    dataset = import_taifex(tick_path, kind='ticks_csv', calendar=calendar, contract_id=CONTRACT)
    coverage = validate_full_sessions(dataset, calendar, CONTRACT)
    daily = import_taifex(Path(daily_json), kind='daily_json', calendar=calendar, contract_id=CONTRACT)
    validate_dataset(daily)
    comparisons = []
    if len(daily.bars) != 2:
        raise ValidationError('two independent daily session summaries required')
    for official in daily.bars:
        bars = [b for b in dataset.bars if (b.trade_date, b.session) == (official.trade_date, official.session)]
        prices = (bars[0].open, max(b.high for b in bars), min(b.low for b in bars), bars[-1].close)
        if prices != (official.open, official.high, official.low, official.close):
            raise ValidationError('independent daily OHLC mismatch')
        volume = sum(b.volume for b in bars)
        comparisons.append({'session': official.session, 'bars': len(bars), 'ohlc_match': True,
                            'outright_volume': volume, 'official_volume': official.volume,
                            'volume_delta': official.volume - volume,
                            'volume_reconciled': False})
    report = {'schema_version': 1, 'integration_accepted': True, 'ranking_eligible': False,
              'trade_dates': ['2026-10-08'], 'contract_id': CONTRACT, 'coverage': coverage,
              'source_hashes': {'archive': ARCHIVE_HASH, 'ticks': TICK_HASH, 'daily': DAILY_HASH},
              'calendar_hash': calendar.hash, 'data_hash': dataset.manifest['data_hash'],
              'session_comparisons': comparisons,
              'limitations': ['One trade date cannot establish economic or out-of-sample ranking validity.',
                             'Outright ticks exclude spreads and block trades; daily volume scope differs.',
                             'OHLC agreement and full minute coverage do not prove every tick is present.',
                             'Public download is not a redistribution license. Raw files remain local.',
                             'All other dates require separate explicit calendar and daily evidence.']}
    return dataset, report


DAILY_CSV_COLUMNS = ('交易日期', '契約', '到期月份(週別)', '開盤價', '最高價', '最低價',
                     '收盤價', '漲跌價', '漲跌%', '成交量', '結算價', '未沖銷契約數',
                     '最後最佳買價', '最後最佳賣價', '歷史最高價', '歷史最低價',
                     '是否因訊息面暫停交易', '交易時段', '價差對單式委託成交量')


def read_daily_evidence(paths, *, contract_id, start, end):
    """Observed official daily CSV, for OHLC evidence only, never minute synthesis.

    Each CSV requires its download's adjacent NAME-source.json with source_url
    and SHA256. Recorded provenance is checked, not treated as a signed license.
    """
    evidence, sources = {}, []
    for path in map(Path, paths):
        metadata = json.loads(path.with_name(path.stem + '-source.json').read_text())
        official_url(metadata['source_url'])
        raw = verified_bytes(path, metadata['sha256'])
        if len(raw) > 64 * 1024 * 1024:
            raise ValidationError('daily evidence exceeds size limit')
        reader = csv.DictReader(io.StringIO(raw.decode('cp950')), strict=True)
        if tuple(reader.fieldnames or ()) != DAILY_CSV_COLUMNS:
            raise ValidationError('unrecognized daily evidence CSV schema')
        sources.append({'filename': path.name, 'source_url': metadata['source_url'],
                        'sha256': metadata['sha256']})
        for number, row in enumerate(reader, 2):
            if number > 1_000_001:
                raise ValidationError('daily evidence row limit exceeded')
            # Observed TAIFEX CSV has a trailing comma. Only empty overflow is allowed.
            overflow = row.pop(None, [])
            if any(value.strip() for value in overflow) or any(v is None for v in row.values()):
                raise ValidationError('malformed daily evidence row')
            row = {k: v.strip() for k, v in row.items()}
            if row['契約'] != 'TMF' or row['到期月份(週別)'] != contract_id.rsplit(':', 1)[1]:
                continue
            date = datetime.strptime(row['交易日期'], '%Y/%m/%d').date().isoformat()
            if not start <= date <= end:
                continue
            session = {'一般': 'day', '盤後': 'night'}.get(row['交易時段'])
            if session is None:
                raise ValidationError('unrecognized daily evidence session')
            key = (date, session)
            if key in evidence:
                raise ValidationError('duplicate daily evidence session')
            try:
                prices = tuple(Decimal(row[k]) for k in ('開盤價','最高價','最低價','收盤價'))
                if any(not value.is_finite() or value <= 0 for value in prices):
                    raise ValueError()
            except (InvalidOperation, ValueError):
                raise ValidationError('invalid daily OHLC evidence') from None
            evidence[key] = prices
    if not evidence:
        raise ValidationError('no daily evidence for selected range and contract')
    return evidence, sources


def load_verified_range(cache, *, start, end, contract_id, calendar_path,
                        calendar_version, daily_csv, as_of):
    """All-or-nothing explicit range acceptance; no inferred calendar or dropped days."""
    validate_date(start); validate_date(end); validate_contract(contract_id)
    cutoff = parse_timestamp(as_of)
    if start > end:
        raise ValidationError('date range is reversed')
    calendar_raw = Path(calendar_path).read_bytes()
    records = json.loads(calendar_raw)
    if not isinstance(records, list):
        raise ValidationError('calendar JSON must be explicit session array')
    records = [r for r in records if start <= r['trade_date'] <= end and
               r.get('contract_id') in (None, '', contract_id)]
    calendar = SessionCalendar(records, version=calendar_version)
    expected = {(r['trade_date'], r['session']) for r in calendar.sessions if not r.get('closed')}
    if not expected or any(r['end'] > cutoff for r in calendar.sessions):
        raise ValidationError('calendar empty or contains sessions after as-of cutoff')
    daily, daily_sources = read_daily_evidence(daily_csv, contract_id=contract_id, start=start, end=end)
    if set(daily) != expected:
        raise ValidationError('calendar/daily evidence session or trading-date set mismatch')
    manifest = json.loads((Path(cache) / 'latest.json').read_text())
    archive_by_date = {}
    for record in manifest['archives']:
        if start <= record['trade_date'] <= end and record['format'] == 'csv':
            if record['trade_date'] in archive_by_date:
                raise ValidationError('ambiguous duplicate cached trade date')
            archive_by_date[record['trade_date']] = record
    dates = {date for date, _ in expected}
    if set(archive_by_date) != dates:
        raise ValidationError('cache/calendar trading-date set mismatch')
    bars, sources, comparisons = [], [], []
    for date in sorted(dates):
        record = archive_by_date[date]
        official_url(record['source_url'])
        archive = verified_bytes(record['archive_path'], record['sha256'])
        members = inspect_archive(archive, 'csv')
        if len(members) != 1 or len(record['files']) != 1:
            raise ValidationError('one observed CSV member required per archive')
        member = record['files'][0]
        if members[0]['name'] != member['name'] or members[0]['sha256'] != member['sha256']:
            raise ValidationError('archive member provenance mismatch')
        verified_bytes(member['path'], member['sha256'])
        day_calendar = SessionCalendar([r for r in records if r['trade_date'] == date],
                                       version=calendar_version + ':' + date)
        dataset = import_taifex(Path(member['path']), kind='ticks_csv', calendar=day_calendar,
                               contract_id=contract_id)
        try:
            validate_full_sessions(dataset, day_calendar, contract_id)
        except ValidationError as exc:
            raise ValidationError(f'{date}: rejected incomplete or invalid archive: {exc}; '
                                  f'gaps={canonical_json(dataset.quality.get("session_coverage_gaps", []))}') from exc
        if any(b.end > cutoff for b in dataset.bars):
            raise ValidationError('observed data exceeds as-of cutoff')
        for key in sorted(k for k in expected if k[0] == date):
            group = [b for b in dataset.bars if (b.trade_date, b.session) == key]
            ohlc = (group[0].open, max(b.high for b in group), min(b.low for b in group), group[-1].close)
            if ohlc != daily[key]:
                raise ValidationError(f'{date} {key[1]}: independent daily OHLC mismatch')
            comparisons.append({'trade_date': date, 'session': key[1], 'bars': len(group),
                                'ohlc_match': True, 'volume_reconciled': False})
        bars.extend(dataset.bars)
        sources.append({'trade_date': date, 'source_url': record['source_url'],
                        'archive_sha256': record['sha256'], 'csv_sha256': member['sha256']})
    provenance = {'archives': sources, 'daily': daily_sources,
                  'calendar_input_sha256': hashlib.sha256(calendar_raw).hexdigest()}
    dataset = _dataset(bars, calendar=calendar, source_type='official_local',
                       quality={'valid': True, 'errors': [], 'warnings': [
                           'Technical diagnostic replay only; insufficient economic OOS history.',
                           'Outright tick and daily volume scopes differ; no redistribution rights inferred.']},
                       extra={'ranking_eligible': False, 'timeframe_minutes': 1, 'bar_granularity': 'minute',
                              'source_hash': hashlib.sha256(canonical_json(provenance).encode()).hexdigest()})
    coverage = validate_full_sessions(dataset, calendar, contract_id)
    report = {'integration_accepted': True, 'ranking_eligible': False, 'contract_id': contract_id,
              'trade_dates': sorted(dates), 'trading_days': len(dates), 'bars': len(bars),
              'coverage': coverage, 'data_hash': dataset.manifest['data_hash'],
              'calendar_hash': calendar.hash, 'as_of': cutoff, 'sources': provenance,
              'session_comparisons': comparisons,
              'limitations': ['Technical validation only; no economic ranking or untouched-OOS claim.',
                             'OHLC and minute coverage do not establish completeness of every tick.']}
    return dataset, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--daily-json', type=Path, help='Pinned October 8 compatibility mode')
    parser.add_argument('--daily-csv', type=Path, action='append', default=[])
    parser.add_argument('--start'); parser.add_argument('--end'); parser.add_argument('--contract')
    parser.add_argument('--calendar', type=Path); parser.add_argument('--calendar-version')
    parser.add_argument('--as-of', help='Explicit UTC/offset observation cutoff for range mode')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if any((args.output / name).exists() for name in ('acceptance.json', 'dataset.json', 'calendar.json')):
        parser.error('fresh output directory required; existing evidence is never overwritten')
    try:
        if args.daily_json:
            if any((args.daily_csv, args.start, args.end, args.contract, args.calendar,
                    args.calendar_version, args.as_of)):
                parser.error('do not mix pinned October 8 and explicit range modes')
            dataset, report = load_verified_oct8(args.cache, args.daily_json)
            calendar_records = verified_oct8_calendar().sessions
        else:
            if not all((args.daily_csv, args.start, args.end, args.contract, args.calendar,
                        args.calendar_version, args.as_of)):
                parser.error('range mode requires daily-csv, start, end, contract, calendar, calendar-version, as-of')
            dataset, report = load_verified_range(args.cache, start=args.start, end=args.end,
                contract_id=args.contract, calendar_path=args.calendar, calendar_version=args.calendar_version,
                daily_csv=args.daily_csv, as_of=args.as_of)
            calendar_records = [r for r in json.loads(args.calendar.read_text())
                                if args.start <= r['trade_date'] <= args.end and
                                r.get('contract_id') in (None, '', args.contract)]
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'History acceptance rejected: {exc}\n')
    # No dataset is written on rejection; do not reuse an earlier successful output directory.
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'acceptance.json').write_text(canonical_json(report) + '\n')
    (args.output / 'calendar.json').write_text(canonical_json(calendar_records) + '\n')
    (args.output / 'dataset.json').write_text(canonical_json(dataset) + '\n')
    print(canonical_json(report))


if __name__ == '__main__':
    main()
