"""Exact whole-market event schemas (TWSE TWT49U, TPEx exDailyQ) for cache-only daily signal event evidence.

A stock missing from a verified whole-market response means no event; that conclusion is only drawn after the
entire response (range, row count, every row) has been verified.
"""

from datetime import date, datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import parse_qs, urlsplit

from .stock_data import TPEX_EVENT_PATH, _day, _document, _number, _rows, _table, stock_identity
from quantlab.trading.domain.stock_history import CorporateAction
from quantlab.trading.domain.validation import DomainError

TWSE_PATHS = ('/rwd/zh/exRight/TWT49U', '/exchangeReport/TWT49U')


def _global_query(parsed, keys):
    query = parse_qs(parsed.query, strict_parsing=True)
    if parsed.scheme != 'https' or parsed.fragment or set(query) != keys or any(len(value) != 1 for value in query.values()):
        raise ValueError('global daily event request required')
    return {key: value[0] for key, value in query.items()}


def daily_event_scope(source_url: str) -> tuple[date, date]:
    """The endpoints use inclusive dates; the cache port uses an exclusive end."""
    parsed = urlsplit(source_url)
    try:
        if parsed.netloc == 'www.tpex.org.tw' and parsed.path == TPEX_EVENT_PATH:
            query = _global_query(parsed, {'l', 'd', 'ed'})
            if query['l'] != 'zh-tw':
                raise ValueError('event language')
            first, last = _day(query['d']), _day(query['ed'])
        elif parsed.netloc == 'www.twse.com.tw' and parsed.path in TWSE_PATHS:
            query = _global_query(parsed, {'response', 'startDate', 'endDate'})
            if query['response'] != 'json':
                raise ValueError('event format')
            first, last = (datetime.strptime(query[key], '%Y%m%d').date() for key in ('startDate', 'endDate'))
        else:
            raise ValueError('global daily event request required')
        if first > last:
            raise ValueError('event date range')
        return first, last + timedelta(days=1)
    except (KeyError, ValueError, OverflowError):
        raise DomainError('daily_signal_source_unverified', 'unsupported whole-market event request') from None


def parse_daily_signal_events(raw: bytes, instrument_id: str, source_url: str) -> tuple[CorporateAction, ...]:
    """Missing stock rows mean no event only after the entire response is verified."""
    venue, code = stock_identity(instrument_id)
    first, end = daily_event_scope(source_url)
    if venue != ('TPEX' if urlsplit(source_url).netloc == 'www.tpex.org.tw' else 'TWSE'):
        raise DomainError('daily_signal_source_unverified', 'event exchange mismatch')
    body = _document(raw)
    last = end - timedelta(days=1)
    try:
        if venue == 'TWSE':
            if body.get('stat') != 'OK' or body.get('strDate') != first.strftime('%Y%m%d') or body.get('endDate') != last.strftime('%Y%m%d'):
                raise ValueError('event response range not attested')
            fields, rows = _table(body)
            columns = ('資料日期', '股票代號')
        else:
            if str(body.get('stat')).upper() != 'OK' or body.get('date') != f'{first:%Y%m%d}~{last:%Y%m%d}':
                raise ValueError('event response range not attested')
            fields, rows = _table(body)  # also attests totalCount == number of rows
            columns = ('除權息日期', '代號')
        if not {*columns, '除權息前收盤價', '除權息參考價'}.issubset(fields):
            raise ValueError('unsupported whole-market event schema')
        result, seen = [], set()
        digest = sha256(raw).hexdigest()
        for row in _rows(fields, rows):
            if venue == 'TWSE':
                matched = re.fullmatch(r'(\d{3})年(\d{2})月(\d{2})日', row[columns[0]])
                if matched is None:
                    raise ValueError('native event date')
                year, month, day = map(int, matched.groups())
                ex_date = date(year + 1911, month, day)
            else:
                ex_date = _day(row[columns[0]])
            if not re.fullmatch(r'[0-9A-Z]{4,8}', row[columns[1]]):
                raise ValueError('native event identity')
            key = row[columns[1]], ex_date
            previous, reference = _number(row['除權息前收盤價']), _number(row['除權息參考價'])
            if not first <= ex_date < end or key in seen or previous <= 0 or reference <= 0:
                raise ValueError('duplicate/out-of-range event or missing reference price')
            seen.add(key)
            if row[columns[1]] == code:
                result.append(CorporateAction(instrument_id, ex_date, previous, reference, digest, source_url))
        return tuple(sorted(result, key=lambda row: row.ex_date))
    except (KeyError, ValueError, TypeError, ArithmeticError):
        raise DomainError('daily_signal_source_unverified', 'unsupported whole-market event response') from None
