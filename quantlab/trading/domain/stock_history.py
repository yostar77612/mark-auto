"""Official stock observations and reproducible backward price adjustment.

Raw bars never change. Reference-price factors include the exchange's combined
cash/stock-rights calculation; missing reference prices are not guessed.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from .arithmetic import decimal_operation
from .validation import DomainError, decimal_value, identity, integer, trading_date

ADJUSTMENT_METHOD = 'official-reference-ratio-backward-v1'


@dataclass(frozen=True)
class DailyStockBar:
    instrument_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_digest: str
    source: str = 'OFFICIAL'

    def __post_init__(self):
        identity(self.instrument_id)
        trading_date(self.trade_date)
        for value in (self.open, self.high, self.low, self.close):
            decimal_value(value, 'daily price', positive=True)
        integer(self.volume, 'daily volume')
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise DomainError('validation_failed', 'daily OHLC ordering')
        if self.source != 'OFFICIAL' or not valid_digest(self.source_digest):
            raise DomainError('validation_failed', 'official daily provenance')


@dataclass(frozen=True)
class CorporateAction:
    instrument_id: str
    ex_date: date
    previous_close: Decimal
    reference_price: Decimal
    source_digest: str
    source_url: str

    def __post_init__(self):
        identity(self.instrument_id)
        trading_date(self.ex_date)
        decimal_value(self.previous_close, 'pre-event close', positive=True)
        decimal_value(self.reference_price, 'ex-event reference', positive=True)
        if not valid_digest(self.source_digest) or not self.source_url.startswith(('https://www.twse.com.tw/', 'https://www.tpex.org.tw/')):
            raise DomainError('validation_failed', 'official event provenance')


@dataclass(frozen=True)
class CashDividendAction(CorporateAction):
    """Explicit cash-only issuer distribution, not inferred from a price ratio.

    The source adapter must establish that no share/rights component exists.
    Payment date is a supplied schedule, not proof of net bank settlement.
    Original CorporateAction wire fields remain unchanged for old evidence.
    """

    cash_per_share: Decimal
    payment_date: date

    def __post_init__(self):
        super().__post_init__()
        decimal_value(self.cash_per_share, 'gross cash per share', positive=True)
        trading_date(self.payment_date)
        if self.payment_date < self.ex_date:
            raise DomainError('validation_failed', 'cash payment precedes entitlement')


@dataclass(frozen=True)
class StockPriceSeries:
    bars: tuple[DailyStockBar, ...]
    mode: str
    adjustment_method: str
    events_digest: str
    raw_digest: str

    def evidence(self) -> tuple[tuple[str, str], ...]:
        return (
            ('price_mode', self.mode),
            ('adjustment_method', self.adjustment_method),
            ('events_digest', self.events_digest),
            ('raw_digest', self.raw_digest),
        )


def valid_digest(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _digest(rows) -> str:
    return sha256(json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


@decimal_operation
def price_series(bars: tuple[DailyStockBar, ...], events: tuple[CorporateAction, ...], *, adjusted: bool = True, as_of: date | None = None) -> StockPriceSeries:
    """Only events inside the observation horizon affect past research prices."""
    if not bars or tuple(sorted(bars, key=lambda b: b.trade_date)) != bars or len({b.trade_date for b in bars}) != len(bars):
        raise DomainError('validation_failed', 'ordered unique daily history required')
    if as_of is not None:
        trading_date(as_of)
        bars = tuple(bar for bar in bars if bar.trade_date <= as_of)
        if not bars:
            raise DomainError('official_stock_coverage_missing', 'no completed history at signal date')
    instrument = bars[0].instrument_id
    if any(b.instrument_id != instrument for b in bars) or any(e.instrument_id != instrument for e in events):
        raise DomainError('validation_failed', 'single instrument required')
    if len({e.ex_date for e in events}) != len(events):
        raise DomainError('validation_failed', 'one combined official event per date')
    events = tuple(sorted((e for e in events if bars[0].trade_date < e.ex_date <= bars[-1].trade_date), key=lambda e: e.ex_date))
    raw_digest = _digest(
        [(b.instrument_id, b.trade_date.isoformat(), *(str(v) for v in (b.open, b.high, b.low, b.close)), b.volume, b.source_digest) for b in bars]
    )
    events_digest = _digest(
        [
            (e.instrument_id, e.ex_date.isoformat(), str(e.previous_close), str(e.reference_price), e.source_digest, e.source_url)
            + (('cash-only-v1', str(e.cash_per_share), e.payment_date.isoformat()) if isinstance(e, CashDividendAction) else ())
            for e in events
        ]
    )
    result = []
    for bar in bars:
        factor = Decimal('1')
        if adjusted:
            for event in events:
                if bar.trade_date < event.ex_date:
                    factor *= event.reference_price / event.previous_close
        result.append(replace(bar, open=bar.open * factor, high=bar.high * factor, low=bar.low * factor, close=bar.close * factor))
    return StockPriceSeries(tuple(result), 'ADJUSTED' if adjusted else 'RAW', ADJUSTMENT_METHOD if adjusted else 'none', events_digest, raw_digest)
