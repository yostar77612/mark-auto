"""Fetch bounded public ISIN classification, independently of SDK industry codes."""

from hashlib import sha256
from datetime import date
from html import unescape
import re
from urllib.request import urlopen

from quantlab.trading.adapters.shioaji.stock_grid import CLASSIFICATIONS, StockGridEvidence
from quantlab.trading.domain.validation import DomainError


def load_classification(code, exchange, now, *, opener=urlopen):
    uri = 'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=' + ('2' if exchange == 'TSE' else '4')
    try:
        with opener(uri, timeout=2.5) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError('classification response size')
        try:
            document = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            document = raw.decode('big5')
        published = re.search(r'Date\s+Stock\s+Updated\s*:\s*(\d{4})/(\d{2})/(\d{2})', unescape(re.sub(r'<[^>]*>', '', document)), re.IGNORECASE)
        if published is None:
            raise ValueError('classification publication date missing')
        source_date = date(*(int(value) for value in published.groups()))
        if not 0 <= (now.date() - source_date).days <= 7:
            raise ValueError('classification publication date stale or future')
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', document, re.IGNORECASE | re.DOTALL):
            cells = [unescape(re.sub(r'<[^>]*>', '', cell)).strip() for cell in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.IGNORECASE | re.DOTALL)]
            if not cells or not cells[0].split() or cells[0].split()[0] != code:
                continue
            isins = [cell for cell in cells if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{10}', cell)]
            classifications = [(product, cell) for product, (codes, _, _) in CLASSIFICATIONS.items() for cell in cells if cell in codes]
            if len(isins) != 1 or len(classifications) != 1:
                raise ValueError('classification row evidence')
            product, cfi = classifications[0]
            return StockGridEvidence(code, exchange, product, isins[0], cfi, uri, source_date.isoformat(), sha256(raw).hexdigest(), now)
    except Exception:
        raise DomainError('instrument_unresolved', 'public cash-security classification unavailable') from None
    raise DomainError('instrument_unresolved', 'cash-security classification row missing')
