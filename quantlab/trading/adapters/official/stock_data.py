"""Bounded native-schema stock parsers with an injected, consent-gated transport.

The schema fixtures are synthetic, not evidence that a live exchange endpoint
was queried. An unsupported or incomplete response fails the complete refresh.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Callable
from urllib.parse import urlencode

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.stock_history import CorporateAction, DailyStockBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.stock_history import OfficialPayload

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50000


def stock_identity(instrument_id: str) -> tuple[str, str]:
    match = re.fullmatch(r'(TWSE|TPEX):([0-9]{4,6})', instrument_id)
    if match is None:
        raise DomainError('validation_failed', 'explicit listed/OTC stock identity required')
    return match[1], match[2]


def daily_url(instrument_id: str, month: date) -> str:
    exchange, code = stock_identity(instrument_id)
    if exchange == 'TWSE':
        return 'https://www.twse.com.tw/exchangeReport/STOCK_DAY?' + urlencode({'response': 'json', 'date': month.strftime('%Y%m01'), 'stockNo': code})
    return 'https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?' + urlencode(
        {'l': 'zh-tw', 'd': f'{month.year - 1911:03d}/{month.month:02d}', 'stkno': code}
    )


def events_url(instrument_id: str, start: date, end: date) -> str:
    exchange, code = stock_identity(instrument_id)
    if exchange == 'TWSE':
        return 'https://www.twse.com.tw/exchangeReport/TWT48U?' + urlencode(
            {'response': 'json', 'startDate': start.strftime('%Y%m%d'), 'endDate': end.strftime('%Y%m%d'), 'stockNo': code}
        )
    return 'https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?' + urlencode(
        {
            'l': 'zh-tw',
            'd': f'{start.year - 1911:03d}/{start.month:02d}/{start.day:02d}',
            'ed': f'{end.year - 1911:03d}/{end.month:02d}/{end.day:02d}',
            'stkno': code,
        }
    )


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _document(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise DomainError('official_stock_invalid', 'bounded response required')
    try:
        result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if type(result) is not dict:
            raise ValueError('object required')
        if 'stat' in result and result['stat'] != 'OK':
            raise ValueError('official result not OK')
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError('official_stock_invalid', 'unsupported or invalid response') from None


def _number(value) -> Decimal:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('decimal text required')
    text = value.strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', text):
        raise ValueError('missing or invalid number')
    return Decimal(text.replace(',', ''))


def _day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r'\d{3,4}/\d{2}/\d{2}', value):
        raise ValueError('native date')
    year, month, day = map(int, value.split('/'))
    return date(year + 1911 if year < 1911 else year, month, day)


def _table(body: dict, *, tpex: bool = False) -> tuple[list, list]:
    if tpex and 'aaData' in body:
        # The legacy TPEx st43 schema uses thousand shares, never lots.
        return ['日期', '成交仟股', '成交仟元', '開盤', '最高', '最低', '收盤', '漲跌', '筆數'], body['aaData']
    if 'tables' in body:
        if not isinstance(body['tables'], list) or len(body['tables']) != 1:
            raise ValueError('one native table required')
        body = body['tables'][0]
    fields, rows = body['fields'], body['data']
    if type(fields) is not list or len(fields) != len(set(fields)) or any(type(f) is not str for f in fields):
        raise ValueError('unique column names required')
    return fields, rows


def _rows(fields, rows):
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValueError('bounded native table required')
    for row in rows:
        if type(row) is not list or len(row) != len(fields):
            raise ValueError('native column count')
        yield dict(zip(fields, row))


@decimal_operation
def parse_daily(raw: bytes, instrument_id: str, month: date) -> tuple[DailyStockBar, ...]:
    exchange, _ = stock_identity(instrument_id)
    body = _document(raw)
    digest = sha256(raw).hexdigest()
    try:
        fields, rows = _table(body, tpex=exchange == 'TPEX')
        volume_key = '成交股數' if exchange == 'TWSE' else '成交仟股'
        prices = ('開盤價', '最高價', '最低價', '收盤價') if exchange == 'TWSE' else ('開盤', '最高', '最低', '收盤')
        result = []
        for row in _rows(fields, rows):
            day = _day(row['日期'])
            if (day.year, day.month) != (month.year, month.month):
                raise ValueError('response month mismatch')
            volume = _number(row[volume_key]) * (1 if exchange == 'TWSE' else 1000)
            if volume != volume.to_integral_value():
                raise ValueError('fractional shares')
            result.append(DailyStockBar(instrument_id, day, *(_number(row[key]) for key in prices), int(volume), digest))
        if not result or len({b.trade_date for b in result}) != len(result):
            raise ValueError('empty or duplicate daily observations')
        return tuple(sorted(result, key=lambda bar: bar.trade_date))
    except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
        raise DomainError('official_stock_invalid', 'daily response rejected; old history retained') from None


def parse_events(raw: bytes, instrument_id: str, start: date, end: date, source_url: str) -> tuple[CorporateAction, ...]:
    _, code = stock_identity(instrument_id)
    body = _document(raw)
    digest = sha256(raw).hexdigest()
    try:
        fields, rows = _table(body)
        required = {'股票代號', '除權息日期', '除權息前收盤價', '除權息參考價'}
        if not required.issubset(fields):
            raise ValueError('unverified event schema')
        result = []
        for row in _rows(fields, rows):
            if row['股票代號'] != code:
                continue
            day = _day(row['除權息日期'])
            if not start <= day < end:
                raise ValueError('event outside requested range')
            result.append(CorporateAction(instrument_id, day, _number(row['除權息前收盤價']), _number(row['除權息參考價']), digest, source_url))
        if len({e.ex_date for e in result}) != len(result):
            raise ValueError('duplicate combined event')
        return tuple(sorted(result, key=lambda event: event.ex_date))
    except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
        raise DomainError('official_stock_invalid', 'event response rejected; old history retained') from None


class StockDataSource:
    def __init__(self, transport: Callable[[str], bytes]):
        self.transport = transport

    def month(self, instrument_id: str, month: date):
        url = daily_url(instrument_id, month)
        raw = self.transport(url)
        return parse_daily(raw, instrument_id, month), OfficialPayload(url, sha256(raw).hexdigest(), raw)

    def events(self, instrument_id: str, start: date, end: date):
        url = events_url(instrument_id, start, end)
        raw = self.transport(url)
        return parse_events(raw, instrument_id, start, end, url), OfficialPayload(url, sha256(raw).hexdigest(), raw)
