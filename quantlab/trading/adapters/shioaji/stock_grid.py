"""Versioned cash-security grids and explicit, source-attested classification.

StockInfo has no tick rule/band fields in Shioaji 1.7.9. Its category is an
industry code, not a reliable stock/ETF classifier. Never call the futures/
options-only contracts.tick_bands API for a stock or guess from its symbol.

The selected resource supplies its ISIN classification record and source hash.
This binds configuration; it is not a claim that the source was fetched or a
broker verified it. Runtime readiness must retain external verification pending.

Authorities captured 2026-10-25:
https://twse-regulation.twse.com.tw/TW/law/DAT07.aspx?FLCODE=FL007116&FLNO=62
https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html
https://www.twse.com.tw/zh/products/securities/etf/overview/rules.html
Classification: https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2
and strMode=4; public ISIN rows, not broker credentials or account eligibility.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from zoneinfo import ZoneInfo

from quantlab.trading.domain.models import InstrumentSpec, Market, PriceBand
from quantlab.trading.domain.validation import DomainError, aware, identity


COMMON_STOCK_RULE = 'twse-tpex-common-stock-20260924-v1'
TWD_ETF_RULE = 'twse-tpex-twd-etf-20261025-v1'
COMMON_STOCK_BANDS = tuple(
    PriceBand(Decimal(low), None if high is None else Decimal(high), Decimal(tick))
    for low, high, tick in (('0', '10', '0.01'), ('10', '50', '0.05'), ('50', '100', '0.1'), ('100', '500', '0.5'), ('500', '1000', '1'), ('1000', None, '5'))
)
TWD_ETF_BANDS = (PriceBand(Decimal('0'), Decimal('50'), Decimal('0.01')), PriceBand(Decimal('50'), None, Decimal('0.05')))
SOURCE_URIS = frozenset(('https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2', 'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4'))
# Deliberately limited to the ordinary-share and plain TWD ETF classifications
# whose public ISIN rows were checked. Unknown classes need explicit support,
# never a fallback to the smallest scalar tick.
CLASSIFICATIONS = MappingProxyType(
    {
        'COMMON_STOCK': (frozenset(('ESVUFR',)), COMMON_STOCK_RULE, COMMON_STOCK_BANDS),
        'TWD_ETF': (frozenset(('CEOGEU', 'CEOIEU')), TWD_ETF_RULE, TWD_ETF_BANDS),
    }
)


@dataclass(frozen=True)
class StockGridEvidence:
    sdk_code: str
    exchange: str
    product_class: str
    isin: str
    cfi_code: str
    source_uri: str
    source_version: str
    source_sha256: str
    as_of: datetime

    def __post_init__(self) -> None:
        for name in ('sdk_code', 'exchange', 'product_class', 'isin', 'cfi_code', 'source_uri', 'source_version', 'source_sha256'):
            identity(getattr(self, name), name)
        aware(self.as_of)
        if self.exchange not in ('TSE', 'OTC') or self.product_class not in CLASSIFICATIONS or self.source_uri not in SOURCE_URIS:
            raise DomainError('instrument_unresolved', 'explicit supported cash-security classification source required')
        if self.cfi_code not in CLASSIFICATIONS[self.product_class][0]:
            raise DomainError('instrument_unresolved', 'ISIN classification disagrees with selected product class')
        if (self.exchange == 'TSE') != self.source_uri.endswith('=2'):
            raise DomainError('instrument_unresolved', 'classification source market mismatch')
        if len(self.isin) != 12 or not self.isin.isascii() or not self.isin.isalnum() or self.isin != self.isin.upper():
            raise DomainError('instrument_unresolved', 'explicit ISIN identity required')
        try:
            if date.fromisoformat(self.source_version).isoformat() != self.source_version:
                raise ValueError('noncanonical version')
        except ValueError:
            raise DomainError('instrument_unresolved', 'dated classification snapshot required') from None
        if len(self.source_sha256) != 64 or any(char not in '0123456789abcdef' for char in self.source_sha256):
            raise DomainError('instrument_unresolved', 'classification snapshot SHA256 required')


def validate_stock_grid(spec: InstrumentSpec, sdk_code: str, exchange: str, evidence: StockGridEvidence | None, now: datetime) -> None:
    """Require an exact approved grid; metadata never grants execution rights."""
    aware(now)
    if not isinstance(evidence, StockGridEvidence) or spec.market is not Market.STOCK:
        raise DomainError('instrument_unresolved', 'cash-security classification evidence missing')
    if (
        evidence.sdk_code != sdk_code
        or evidence.exchange != exchange
        or spec.exchange not in {'TSE': ('TWSE', 'TSE'), 'OTC': ('TPEX', 'OTC')}.get(exchange, ())
    ):
        raise DomainError('instrument_unresolved', 'cash-security classification identity mismatch')
    snapshot_age = (evidence.as_of.astimezone(ZoneInfo('Asia/Taipei')).date() - date.fromisoformat(evidence.source_version)).days
    if not 0 <= (now - evidence.as_of).total_seconds() <= 7 * 86400 or not 0 <= snapshot_age <= 7:
        raise DomainError('instrument_unresolved', 'classification source is stale or future dated')
    _, expected_rule, expected_bands = CLASSIFICATIONS[evidence.product_class]
    if spec.currency != 'TWD' or spec.tick_rule_id != expected_rule or spec.price_bands != expected_bands or spec.tick_size != expected_bands[0].tick:
        raise DomainError('instrument_unresolved', 'cash-security grid differs from versioned exchange authority')
