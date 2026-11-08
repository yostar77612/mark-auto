"""Compose an explicit official-stock downloader without changing legacy feeds.

Construction is offline. Call StockHistorySync.refresh only after its per-call
consent check; tests inject bytes and never invoke this network transport.
"""

from datetime import timedelta
import re
import time
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from quantlab.market_providers import _DeadlineHTTPSHandler, _NoRedirect
from quantlab.trading.adapters.official.stock_data import MAX_BYTES, TPEX_EVENT_PATH, StockDataSource, tpex_events_url
from quantlab.trading.adapters.official.daily_signal_events import daily_event_scope
from quantlab.trading.application.stock_history import StockHistorySync
from quantlab.trading.domain.validation import DomainError

_ENDPOINTS = {
    ('www.twse.com.tw', '/exchangeReport/STOCK_DAY'): {'response': 'json', 'date': r'\d{8}', 'stockNo': r'\d{4,6}'},
    ('www.twse.com.tw', '/exchangeReport/TWT48U'): {'response': 'json', 'startDate': r'\d{8}', 'endDate': r'\d{8}', 'stockNo': r'\d{4,6}'},
    ('www.tpex.org.tw', '/www/zh-tw/afterTrading/tradingStock'): {'code': r'\d{4,6}', 'date': r'\d{4}/\d{2}/01', 'response': 'json'},
}


def validate_stock_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 512:
        raise DomainError('official_stock_invalid', 'bounded official URL required')
    parts = urlsplit(url)
    if parts.netloc == 'www.tpex.org.tw' and parts.path == TPEX_EVENT_PATH:
        try:
            first, end = daily_event_scope(url)
        except DomainError:
            raise DomainError('official_stock_invalid', 'official event request refused') from None
        if url != tpex_events_url(first, end):
            raise DomainError('official_stock_invalid', 'canonical official event request required')
        return url
    if parts.path in ('/rwd/zh/exRight/TWT49U', '/exchangeReport/TWT49U'):
        try:
            first, end = daily_event_scope(url)
        except DomainError:
            raise DomainError('official_stock_invalid', 'official event request refused') from None
        canonical = f'https://www.twse.com.tw{parts.path}?startDate={first:%Y%m%d}&endDate={end - timedelta(days=1):%Y%m%d}&response=json'
        if url != canonical:
            raise DomainError('official_stock_invalid', 'canonical official event request required')
        return url
    patterns = _ENDPOINTS.get((parts.netloc, parts.path))
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    params = dict(pairs)
    if parts.scheme != 'https' or parts.fragment or patterns is None or len(params) != len(pairs) or params.keys() != patterns.keys():
        raise DomainError('official_stock_invalid', 'official endpoint refused')
    if any(re.fullmatch(pattern, params[key]) is None for key, pattern in patterns.items()):
        raise DomainError('official_stock_invalid', 'official query refused')
    return url


def fetch_stock_official(url: str) -> bytes:
    validate_stock_url(url)
    deadline = time.monotonic() + 30
    handler = _DeadlineHTTPSHandler(deadline)
    opener = build_opener(ProxyHandler({}), _NoRedirect(), handler)
    request = Request(url, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': 'MarkAuto-official-stock/1'})
    try:
        with opener.open(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != url or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise DomainError('official_stock_invalid', 'official response refused')
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                raise DomainError('official_stock_invalid', 'response size refused')
            chunks, size = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise DomainError('official_stock_invalid', 'response deadline')
                chunk = response.read(min(65536, MAX_BYTES - size + 1))
                if time.monotonic() >= deadline:
                    raise DomainError('official_stock_invalid', 'response deadline')
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DomainError('official_stock_invalid', 'response size exceeded')
                chunks.append(chunk)
            if length is not None and size != int(length):
                raise DomainError('official_stock_invalid', 'truncated response')
            return b''.join(chunks)
    except Exception:
        # Only the external HTTP boundary is caught; no URL, response body or
        # upstream error string is logged or displayed.
        raise DomainError('official_stock_invalid', 'official fetch failed; original data retained') from None
    finally:
        handler.cleanup()


def compose_stock_history(store, *, transport=fetch_stock_official):
    return StockHistorySync(store, StockDataSource(transport))
