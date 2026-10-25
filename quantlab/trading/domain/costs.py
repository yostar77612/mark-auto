"""One explicit, versioned cost and slippage authority for all local markets.

Defaults are deliberately named local assumptions, not current broker quotations.
Deployment outside local simulation must use independently verified schedules.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from .arithmetic import decimal_operation
from .models import InstrumentSpec, Market, Side
from .validation import DomainError, decimal_value, identity, integer


ZERO = Decimal('0')


@dataclass(frozen=True)
class FeeSchedule:
    version: str = 'local-demo-cost-v1'
    buy_rate: Decimal = Decimal('0.001425')
    sell_rate: Decimal = Decimal('0.001425')
    sell_tax_rate: Decimal = Decimal('0.003')
    minimum_fee: Decimal = Decimal('20')
    futures_fee_per_contract: Decimal = Decimal('30')
    futures_tax_rate: Decimal = Decimal('0.00002')
    slippage_ticks: int = 1

    def __post_init__(self) -> None:
        identity(self.version)
        for name in ('buy_rate', 'sell_rate', 'sell_tax_rate', 'minimum_fee', 'futures_fee_per_contract', 'futures_tax_rate'):
            decimal_value(getattr(self, name), name, nonnegative=True)
        integer(self.slippage_ticks, 'slippage_ticks')

    @decimal_operation
    def transaction(self, spec: InstrumentSpec, side: Side, price: Decimal, quantity: int) -> Decimal:
        if not isinstance(spec, InstrumentSpec) or not isinstance(side, Side):
            raise DomainError('validation_failed', 'cost instrument/side')
        decimal_value(price, 'price', positive=True)
        integer(quantity, 'quantity')
        if not quantity:
            return ZERO
        notional = price * spec.multiplier * quantity
        if spec.market is Market.STOCK:
            fee = max(self.minimum_fee, notional * (self.buy_rate if side is Side.BUY else self.sell_rate))
            tax = notional * self.sell_tax_rate if side is Side.SELL else ZERO
        else:
            fee = self.futures_fee_per_contract * quantity
            tax = notional * self.futures_tax_rate
        return (fee + tax).quantize(Decimal('1'), rounding=ROUND_CEILING)

    @decimal_operation
    def round_trip(self, spec: InstrumentSpec, entry: Decimal, stop: Decimal, quantity: int, side: Side = Side.BUY) -> Decimal:
        exit_side = Side.SELL if side is Side.BUY else Side.BUY
        return self.transaction(spec, side, entry, quantity) + self.transaction(spec, exit_side, stop, quantity)

    @decimal_operation
    def incremental_transaction(self, spec: InstrumentSpec, side: Side, average_price: Decimal, cumulative_quantity: int, previous_fee: Decimal) -> Decimal:
        """Local per-order minimum-fee assumption, not broker-verified billing.

        Charge only the increase of the cumulative order fee so a partial fill
        does not repeatedly consume the order minimum. VWAP and cumulative
        quantity must describe this exact order; previously billed fees never
        become a cash refund merely because a later estimate is lower.
        """
        decimal_value(previous_fee, 'previous billed fee', nonnegative=True)
        total = self.transaction(spec, side, average_price, cumulative_quantity)
        return max(ZERO, total - previous_fee)

    @decimal_operation
    def slippage(self, spec: InstrumentSpec, quantity: int, legs: int = 2, *, prices: tuple[Decimal, ...] = ()) -> Decimal:
        integer(quantity, 'quantity')
        integer(legs, 'legs')
        if type(prices) is not tuple or prices and len(prices) != legs:
            raise DomainError('validation_failed', 'slippage leg price context')
        for price in prices:
            decimal_value(price, 'slippage reference', positive=True)
        if prices:
            distance = sum((spec.slippage_distance(price, self.slippage_ticks) for price in prices), ZERO)
        else:
            # Historical fixed-price callers retain exactly their old result.
            # Missing band price context uses the global largest tick plus one
            # outward-grid allowance for an unknown off-grid VWAP basis. It
            # never substitutes a smaller first-band scalar. This is a local
            # conservative cost bound, not a broker execution guarantee.
            ticks = self.slippage_ticks + (1 if spec.price_bands and self.slippage_ticks else 0)
            distance = max((band.tick for band in spec.price_bands), default=spec.tick_size) * ticks * legs
        return distance * spec.multiplier * quantity

    @decimal_operation
    def loss_at_stop(self, spec: InstrumentSpec, entry: Decimal, stop: Decimal, quantity: int, side: Side = Side.BUY) -> Decimal:
        return (
            abs(entry - stop) * spec.multiplier * quantity
            + self.round_trip(spec, entry, stop, quantity, side)
            + self.slippage(spec, quantity, prices=(entry, stop))
        )

    def unit_risk(self, spec: InstrumentSpec, entry: Decimal, stop: Decimal, side: Side = Side.BUY) -> Decimal:
        return self.loss_at_stop(spec, entry, stop, 1, side)

    @decimal_operation
    def entry_cash(self, spec: InstrumentSpec, price: Decimal, quantity: int, side: Side = Side.BUY) -> Decimal:
        principal = price * quantity if spec.market is Market.STOCK else (spec.margin or ZERO) * quantity
        return principal + self.transaction(spec, side, price, quantity) + self.slippage(spec, quantity, prices=(price, price))
