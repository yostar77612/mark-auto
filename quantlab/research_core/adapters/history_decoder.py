"""Bounded history responsibility; validation, digest and publication ordering preserved."""

import csv
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import os
import re
import time
from quantlab.market import MarketBar, MarketSeries, MarketValidationError, SourceProvenance, bar_key
from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES, UTC, TAIPEI, HistoryLoad, _fail, _hash, _session_dict


MAX_FILE_BYTES = 64 * 1024 * 1024


MAX_ROWS = 1_000_000


COLUMNS = ('成交日期', '商品代號', '到期月份(週別)', '成交時間', '成交價格', '成交數量(B+S)', '近月價格', '遠月價格', '開盤集合競價')


WARNINGS = (
    '本機匯入，來源未經連線核實；歷史行情，不是即時報價。',
    '交易日與時段由使用者明確指定；商品規格網址不是該日期行事曆認證。',
    '僅單式成交，B+S數量除以2；排除價差與大額交易，不與每日含價差成交量宣稱相同。',
    '逐筆及衍生分鐘資料之再散布授權未確認；僅供本機私人檢視。',
    '分鐘存在與OHLC吻合不證明逐筆完整；不得當作研究品質或交易資格認證。',
)


VERSION = 'taifex-market-ticks-v1'


SOURCE_URL = 'https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData'


def _check(deadline, cancelled):
    if cancelled is not None and cancelled():
        _fail('history import cancelled')
    if time.monotonic() >= deadline:
        _fail('history import time limit')


def _lines(stream, digest, deadline, cancelled):
    size = 0
    encoding = None
    while True:
        _check(deadline, cancelled)
        raw = stream.readline(4097)
        if not raw:
            break
        size += len(raw)
        if size > MAX_FILE_BYTES or len(raw) > 4096:
            _fail('native file byte/line limit')
        digest.update(raw)
        if encoding is None:
            try:
                raw.decode('utf-8-sig')
                encoding = 'utf-8-sig'
            except UnicodeError:
                encoding = 'cp950'
        try:
            line = raw.decode(encoding)
        except UnicodeError:
            _fail('native file encoding invalid')
        if '\x00' in line:
            _fail('binary native input refused')
        yield line


def _positive(text, name):
    if not re.fullmatch(r'[0-9]{1,12}', text):
        _fail('invalid ' + name)
    value = int(text)
    if value <= 0:
        _fail('nonpositive ' + name)
    return value


def _tick_time(d, t):
    if not re.fullmatch(r'\d{8}', d) or not re.fullmatch(r'\d{6}', t):
        _fail('invalid native date/time')
    try:
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:]), int(t[:2]), int(t[2:4]), int(t[4:]), tzinfo=TAIPEI).astimezone(UTC)
    except ValueError:
        _fail('invalid native date/time')


def _decode(path, sessions, deadline, cancelled):
    by_contract = {}
    for index, s in enumerate(sessions):
        by_contract.setdefault(s.instrument.contract_id, []).append((index, s))
    counters = dict(rows=0, accepted_ticks=0, spread_rows=0, excluded_rows=0, outside_session_rows=0, missing_minutes=0)
    digest = hashlib.sha256()
    groups = {}
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_FILE_BYTES:
            _fail('native file size limit')
        reader = csv.reader(_lines(stream, digest, deadline, cancelled), strict=True)
        try:
            columns = next(reader)
            if tuple(c.strip().lstrip('\ufeff') for c in columns) != COLUMNS:
                _fail('unsupported native tick schema; fixed-width RPT is not supported')
            for line_number, row in enumerate(reader, 2):
                counters['rows'] += 1
                if counters['rows'] > MAX_ROWS:
                    _fail('native row limit')
                if len(row) != 9 or any(len(v) > 128 for v in row):
                    _fail('invalid native column width at row ' + str(line_number))
                d, native, expiry, t, p, q, near, far, _ = (v.strip() for v in row)
                if native not in PRODUCT_SOURCES:
                    counters['excluded_rows'] += 1
                    continue
                if '/' in expiry:
                    if not re.fullmatch(r'\d{6}(?:W[1-5])?/\d{6}(?:W[1-5])?', expiry):
                        _fail('invalid spread identity')
                    counters['spread_rows'] += 1
                    continue
                cid = f'TAIFEX:{native}:{expiry}'
                if cid not in by_contract:
                    counters['excluded_rows'] += 1
                    continue
                stamp = _tick_time(d, t)
                quantity = _positive(q, 'B+S quantity')
                if quantity % 2:
                    _fail('B+S quantity must be even')
                value = _positive(p, 'integral price')
                if value > 1_000_000_000 or near != '-' or far != '-':
                    _fail('invalid outright tick price/scope')
                matches = [(i, s) for i, s in by_contract[cid] if s.open <= stamp < s.end or (s.include_end and stamp == s.end)]
                if not matches:
                    counters['outside_session_rows'] += 1
                    continue
                if len(matches) != 1:
                    _fail('ambiguous session membership')
                index, s = matches[0]
                bucket = int((stamp - s.open).total_seconds() // 60)
                if stamp == s.end:
                    bucket -= 1
                key = (index, bucket)
                order = (stamp, line_number)
                if key not in groups:
                    groups[key] = [order, order, value, value, value, value, quantity // 2]
                else:
                    a = groups[key]
                    if order < a[0]:
                        a[0] = order
                        a[2] = value
                    if order > a[1]:
                        a[1] = order
                        a[5] = value
                    a[3] = max(a[3], value)
                    a[4] = min(a[4], value)
                    a[6] += quantity // 2
                counters['accepted_ticks'] += 1
            after = os.fstat(stream.fileno())
        except (csv.Error, StopIteration) as exc:
            raise MarketValidationError('malformed native tick file') from exc
    current = path.stat()
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    if identity(before) != identity(after) or identity(after) != identity(current):
        _fail('source changed while importing')
    if not groups:
        _fail('no actual trades within selected contract/session policy')
    source_hash = digest.hexdigest()
    bars = []
    for index, s in enumerate(sessions):
        expected = int((s.end - s.open).total_seconds() / 60)
        actual = {bucket for (i, bucket) in groups if i == index}
        missing = expected - len(actual)
        counters['missing_minutes'] += missing
        for bucket in sorted(actual):
            a = groups[(index, bucket)]
            start = s.open + timedelta(minutes=bucket)
            bars.append(
                MarketBar(
                    s.instrument,
                    s.trade_date,
                    s.session,
                    *[Decimal(x) for x in a[2:6]],
                    a[6],
                    interval='1m',
                    timestamp=start,
                    end=min(start + timedelta(minutes=1), s.end),
                    session_open=s.open,
                    session_end=s.end,
                    partial=bool(missing),
                    source_id=source_hash,
                )
            )
    return tuple(bars), source_hash, counters


def _bar_dict(b):
    return dict(
        contract_id=b.contract_id,
        trade_date=b.trade_date,
        session=b.session,
        open=str(b.open),
        high=str(b.high),
        low=str(b.low),
        close=str(b.close),
        volume=b.volume,
        timestamp=b.timestamp.isoformat(),
        end=b.end.isoformat(),
        session_open=b.session_open.isoformat(),
        session_end=b.session_end.isoformat(),
        partial=b.partial,
    )


def _result(bars, sessions, source_hash, counters, received_at):
    policy_hash = _hash([_session_dict(s) for s in sessions])
    cache_id = _hash(dict(version=VERSION, source_hash=source_hash, policy_hash=policy_hash))
    warnings = WARNINGS + ((f"缺少 {counters['missing_minutes']} 個分鐘區間；未補值，完整性未知。",) if counters['missing_minutes'] else ())
    groups = {}
    for b in bars:
        groups.setdefault(b.instrument, []).append(b)
    series = []
    for inst, values in sorted(groups.items(), key=lambda x: x[0].contract_id):
        values = tuple(sorted(values, key=bar_key))
        start = min(b.trade_date for b in values)
        end = max(b.trade_date for b in values)
        provenance = SourceProvenance(
            SOURCE_URL,
            source_hash,
            '本機TAIFEX原生格式檔案；來源與日期政策未經連線核實',
            SOURCE_URL,
            received_at,
            end,
            start,
            end,
            mode='history',
            timestamp_basis='原生成交當地時間轉UTC；交易日由明示使用者時段政策指定；政策SHA256=' + policy_hash,
            omitted_rows=counters['spread_rows'] + counters['excluded_rows'] + counters['outside_session_rows'],
            warnings=warnings,
        )
        series.append(MarketSeries(inst, values, provenance))
    return HistoryLoad(tuple(series), policy_hash, source_hash, tuple(sorted(counters.items())), warnings, cache_id)
