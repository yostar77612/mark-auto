"""Exact TWSE TWT49U schema for cache-only daily signal event evidence."""

from datetime import date, datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import parse_qs, urlsplit

from .stock_data import _document, _number, _rows, _table, stock_identity
from quantlab.trading.domain.stock_history import CorporateAction
from quantlab.trading.domain.validation import DomainError


def daily_event_scope(source_url: str) -> tuple[date, date]:
    """The endpoint uses inclusive dates; the cache port uses an exclusive end."""
    parsed = urlsplit(source_url)
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        if (
            parsed.scheme != 'https'
            or parsed.netloc != 'www.twse.com.tw'
            or parsed.path not in ('/rwd/zh/exRight/TWT49U', '/exchangeReport/TWT49U')
            or parsed.fragment
            or set(query) != {'response', 'startDate', 'endDate'}
            or any(len(value) != 1 for value in query.values())
            or query['response'] != ['json']
        ):
            raise ValueError('global daily event request required')
        first, last = (datetime.strptime(query[key][0], '%Y%m%d').date() for key in ('startDate', 'endDate'))
        if first > last:
            raise ValueError('event date range')
        return first, last + timedelta(days=1)
    except (KeyError, ValueError, OverflowError):
        raise DomainError('daily_signal_source_unverified', 'unsupported TWT49U request') from None


def parse_daily_signal_events(raw: bytes, instrument_id: str, source_url: str) -> tuple[CorporateAction, ...]:
    """Missing stock rows mean no event only after the entire response is verified."""
    venue, code = stock_identity(instrument_id)
    first, end = daily_event_scope(source_url)
    if venue != 'TWSE':
        raise DomainError('daily_signal_source_unverified', 'event exchange mismatch')
    body = _document(raw)
    try:
        if body.get('stat') != 'OK' or body.get('strDate') != first.strftime('%Y%m%d') or body.get('endDate') != (end - timedelta(days=1)).strftime('%Y%m%d'):
            raise ValueError('event response range not attested')
        fields, rows = _table(body)
        if not {'資料日期', '股票代號', '除權息前收盤價', '除權息參考價'}.issubset(fields):
            raise ValueError('unsupported TWT49U schema')
        result, seen = [], set()
        digest = sha256(raw).hexdigest()
        for row in _rows(fields, rows):
            matched = re.fullmatch(r'(\d{3})年(\d{2})月(\d{2})日', row['資料日期'])
            if matched is None or not re.fullmatch(r'[0-9A-Z]{4,8}', row['股票代號']):
                raise ValueError('native event identity/date')
            year, month, day = map(int, matched.groups())
            ex_date = date(year + 1911, month, day)
            key = row['股票代號'], ex_date
            previous, reference = _number(row['除權息前收盤價']), _number(row['除權息參考價'])
            if not first <= ex_date < end or key in seen or previous <= 0 or reference <= 0:
                raise ValueError('duplicate/out-of-range event or missing reference price')
            seen.add(key)
            if row['股票代號'] == code:
                result.append(CorporateAction(instrument_id, ex_date, previous, reference, digest, source_url))
        return tuple(sorted(result, key=lambda row: row.ex_date))
    except (KeyError, ValueError, TypeError, ArithmeticError):
        raise DomainError('daily_signal_source_unverified', 'unsupported TWT49U response') from None
