"""Parsers for the exchanges' public whole-market daily close quotes (TWSE MI_INDEX, TPEx daily close).

Public data: no account, no credential. Both endpoints answer for one day and the whole market at once. A holiday is a
recognised empty answer (None); anything else that does not match the expected shape is refused, never guessed.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import json
from urllib.parse import urlencode

from quantlab.trading.domain.market_daily import DailyQuote
from quantlab.trading.domain.sector import eligible_stock
from quantlab.trading.domain.validation import DomainError

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 5000
TWSE_HOST, TWSE_PATH = 'www.twse.com.tw', '/exchangeReport/MI_INDEX'
TPEX_HOST, TPEX_PATH = 'www.tpex.org.tw', '/www/zh-tw/afterTrading/otc'
TWSE_NO_DATA = '很抱歉，沒有符合條件的資料!'
TWSE_TABLE = '每日收盤行情'
TWSE_FIELDS = {'code': '證券代號', 'shares': '成交股數', 'amount': '成交金額', 'open': '開盤價', 'high': '最高價', 'low': '最低價', 'close': '收盤價'}
TPEX_FIELDS = {'code': '代號', 'shares': '成交股數', 'amount': '成交金額(元)', 'open': '開盤', 'high': '最高', 'low': '最低', 'close': '收盤'}


def twse_url(day: date) -> str:
    return f'https://{TWSE_HOST}{TWSE_PATH}?' + urlencode({'response': 'json', 'date': day.strftime('%Y%m%d'), 'type': 'ALLBUT0999'})


def tpex_url(day: date) -> str:
    return f'https://{TPEX_HOST}{TPEX_PATH}?' + urlencode({'date': day.strftime('%Y/%m/%d'), 'type': 'EW', 'response': 'json'})


def _invalid() -> DomainError:
    return DomainError('official_stock_invalid', 'unsupported or invalid daily quote response')


def _document(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise _invalid()
    try:
        document = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid() from None
    if type(document) is not dict:
        raise _invalid()
    return document


def _columns(fields, wanted: dict[str, str]) -> dict[str, int]:
    names = [str(field).strip() for field in fields]
    if any(label not in names for label in wanted.values()):
        raise _invalid()
    return {key: names.index(label) for key, label in wanted.items()}


def _number(text: str) -> Decimal | None:
    """A price or count as printed ('1,234.50'); the exchanges print '--' or '----' for no trade."""
    try:
        value = Decimal(str(text).replace(',', '').strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _quote(cells, columns: dict[str, int], day: date) -> DailyQuote | None:
    """None for a row that is not an ordinary share or did not trade (no open, high, low or close)."""
    code = str(cells[columns['code']]).strip()
    if not eligible_stock(code):
        return None
    prices = [_number(cells[columns[key]]) for key in ('open', 'high', 'low', 'close')]
    shares, amount = _number(cells[columns['shares']]), _number(cells[columns['amount']])
    if any(value is None or value <= 0 for value in prices) or shares is None or amount is None or shares < 0 or amount < 0:
        return None
    try:
        return DailyQuote(code, day, *prices, int(shares) // 1000, int(amount))
    except DomainError:
        return None


def _rows(table: dict, wanted: dict[str, str], day: date) -> tuple[DailyQuote, ...]:
    columns = _columns(table.get('fields', ()), wanted)
    data = table.get('data')
    if not isinstance(data, list) or len(data) > MAX_ROWS:
        raise _invalid()
    quotes = []
    for cells in data:
        if not isinstance(cells, list) or len(cells) <= max(columns.values()):
            raise _invalid()
        quote = _quote(cells, columns, day)
        if quote is not None:
            quotes.append(quote)
    if len({quote.code for quote in quotes}) != len(quotes):
        raise _invalid()
    if data and not quotes:
        raise _invalid()
    return tuple(quotes)


def parse_twse(raw: bytes, day: date) -> tuple[DailyQuote, ...] | None:
    """The day's ordinary shares, or None when the exchange says it has no data for that day (a holiday)."""
    document = _document(raw)
    if 'tables' not in document:
        if document.get('stat') == TWSE_NO_DATA:
            return None
        raise _invalid()
    if str(document.get('stat', '')).upper() != 'OK' or document.get('date') != day.strftime('%Y%m%d'):
        raise _invalid()
    tables = [table for table in document['tables'] if isinstance(table, dict) and TWSE_TABLE in str(table.get('title', ''))]
    if len(tables) != 1:
        raise _invalid()
    return _rows(tables[0], TWSE_FIELDS, day)


def parse_tpex(raw: bytes, day: date) -> tuple[DailyQuote, ...] | None:
    """The day's ordinary shares, or None when TPEx lists nothing for that day (a holiday)."""
    document = _document(raw)
    tables = document.get('tables')
    if str(document.get('stat', '')).upper() != 'OK' or not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], dict):
        raise _invalid()
    table = tables[0]
    if not table.get('data') and table.get('totalCount') == 0:
        return None
    if document.get('date') != day.strftime('%Y%m%d'):
        raise _invalid()
    return _rows(table, TPEX_FIELDS, day)


class OfficialDailySource:
    """The two public endpoints behind one port: markets are 'TWSE' (listed) and 'TPEX' (OTC)."""

    def url(self, market: str, day: date) -> str:
        return twse_url(day) if market == 'TWSE' else tpex_url(day)

    def parse(self, market: str, raw: bytes, day: date) -> tuple[DailyQuote, ...] | None:
        return parse_twse(raw, day) if market == 'TWSE' else parse_tpex(raw, day)
