"""Compose the market-wide daily quotes: their store, the screener's statistics and the official backfill.

Public data only: the transport carries no account, token or cookie, only two fixed official endpoints.
"""

from datetime import datetime, timezone
import logging
import re
import time
from urllib.parse import parse_qsl, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from quantlab.market_providers import _DeadlineHTTPSHandler, _NoRedirect
from quantlab.trading.adapters.official.market_daily_data import MAX_BYTES, TPEX_HOST, TPEX_PATH, TWSE_HOST, TWSE_PATH, OfficialDailySource
from quantlab.trading.adapters.storage.market_daily_store import MarketDailyStore
from quantlab.trading.application.market_daily import MarketDaily, MarketDailyBackfill
from quantlab.trading.domain.validation import DomainError

logger = logging.getLogger(__name__)
_TAIPEI = ZoneInfo('Asia/Taipei')
_ENDPOINTS = {
    (TWSE_HOST, TWSE_PATH): {'response': 'json', 'date': r'[0-9]{8}', 'type': 'ALLBUT0999'},
    (TPEX_HOST, TPEX_PATH): {'date': r'[0-9]{4}/[0-9]{2}/[0-9]{2}', 'type': 'EW', 'response': 'json'},
}


def validate_daily_url(url: str) -> str:
    """Only the two fixed official endpoints with exactly their own query keys and shapes."""
    if not isinstance(url, str) or len(url) > 200 or any(ord(char) <= 32 for char in url):
        raise DomainError('official_stock_invalid', 'bounded official URL required')
    parts = urlsplit(url)
    patterns = _ENDPOINTS.get((parts.netloc, parts.path))
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    params = dict(pairs)
    if parts.scheme != 'https' or parts.fragment or patterns is None or len(params) != len(pairs) or params.keys() != patterns.keys():
        raise DomainError('official_stock_invalid', 'official endpoint refused')
    if any(re.fullmatch(pattern, params[key]) is None for key, pattern in patterns.items()):
        raise DomainError('official_stock_invalid', 'official query refused')
    return url


def fetch_daily_official(url: str) -> bytes:
    """One bounded HTTPS GET without proxy, redirect or compression; the body, URL and upstream text are never logged."""
    validate_daily_url(url)
    deadline = time.monotonic() + 30
    handler = _DeadlineHTTPSHandler(deadline)
    opener = build_opener(ProxyHandler({}), _NoRedirect(), handler)
    request = Request(url, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': 'MarkAuto-market-daily/1'})
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
        # Only the external HTTP boundary is caught; the caller retries later and nothing is recorded.
        raise DomainError('official_stock_invalid', 'official fetch failed') from None
    finally:
        handler.cleanup()  # the deadline timers would otherwise live on for about 30 s after every request


def attach_market_daily(bundle, params, now):
    """The daily store and its screener-facing service, or None when the file cannot be opened (the screener then judges
    without market-wide daily quotes). Nothing is fetched until start_market_daily is called by the real engine."""
    try:
        store = MarketDailyStore((bundle.launch.root / 'market' / 'market_daily.sqlite3').resolve())
    except DomainError as error:
        logger.error('market daily store unavailable (%s)', error.code)
        return None
    bundle.market_daily_store = store
    store.purge(now().astimezone(_TAIPEI).date())
    return MarketDaily(store, params, now)


def start_market_daily(bundle, fetch=fetch_daily_official) -> None:
    """Start the 240-day official backfill (rate-limited, resumable). Only the real engine process calls this."""
    store = bundle.market_daily_store
    if store is None or bundle.market_daily_backfill is not None:
        return

    def today():
        return datetime.now(_TAIPEI).date()

    backfill = MarketDailyBackfill(store, OfficialDailySource(), fetch, today, lambda: datetime.now(timezone.utc))
    bundle.market_daily_backfill = backfill
    backfill.start()
