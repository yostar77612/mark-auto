"""Pure SDK-to-port mapping; unsupported evidence fails closed."""

from datetime import datetime, timedelta
from decimal import Decimal

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import AccountSnapshot, Environment, Market, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder, BrokerPosition, HistoryBar, SettlementItem
from .sdk import InstrumentBinding, sdk_decimal, sdk_text, sdk_time, sdk_value

STATUS_MAP = {
    'Cancelled': OrderStatus.CANCELED,
    'Filled': OrderStatus.FILLED,
    'PartFilled': OrderStatus.PARTIALLY_FILLED,
    'Failed': OrderStatus.REJECTED,
    'PendingSubmit': OrderStatus.UNKNOWN,
    'PreSubmitted': OrderStatus.ACCEPTED,
    'Submitted': OrderStatus.ACCEPTED,
    'Inactive': OrderStatus.UNKNOWN,
}


def stock_sdk_quantity(plan: OrderPlan, binding: InstrumentBinding, *, odd_lot: bool) -> tuple[int, str]:
    binding.spec.validate_quantity(plan.quantity, plan.unit, odd_lot=odd_lot)
    if binding.spec.market is not Market.STOCK:
        return plan.quantity, ''
    if plan.quantity % 1000:
        if not odd_lot:
            raise DomainError('capability_missing', 'odd-lot capability')
        return plan.quantity, 'IntradayOdd'
    return plan.quantity // 1000, 'Common'


@decimal_operation
def sdk_order_fields(plan: OrderPlan, binding: InstrumentBinding, account: object, *, odd_lot: bool) -> dict[str, object]:
    """SDK kwargs are internal. No HoldingPolicy-to-DayTrade inference exists."""
    from .sdk import sdk_price

    binding.spec.validate_price(plan.limit_price)
    quantity, order_lot = stock_sdk_quantity(plan, binding, odd_lot=odd_lot)
    fields: dict[str, object] = {
        'action': 'Buy' if plan.side is Side.BUY else 'Sell',
        'price': sdk_price(plan.limit_price),
        'quantity': quantity,
        'price_type': 'LMT',
        'order_type': 'ROD',
        'account': account,
    }
    if binding.spec.market is Market.STOCK:
        fields.update(order_lot=order_lot, order_cond='Cash', daytrade_short=False)
    else:
        fields['octype'] = 'Cover' if plan.reduce_only else 'New'
    return fields


@decimal_operation
def order_from_sdk(raw: object, local_order_id: str, plan: OrderPlan, binding: InstrumentBinding, now: datetime) -> BrokerOrder:
    status = sdk_value(raw, 'status')
    raw_order = sdk_value(raw, 'order')
    state = sdk_text(sdk_value(status, 'status'))
    if state not in STATUS_MAP:
        raise DomainError('reconciliation_required', 'unrecognized SDK order status')
    cumulative = sdk_value(status, 'deal_quantity')
    if type(cumulative) is not int:
        raise DomainError('reconciliation_required', 'SDK deal quantity unit')
    lot = sdk_text(getattr(raw_order, 'order_lot', 'Common'))
    multiplier = 1000 if binding.spec.market is Market.STOCK and lot == 'Common' else 1
    cumulative *= multiplier
    price = sdk_decimal(getattr(raw_order, 'price', plan.limit_price), 'order price')
    deals = getattr(status, 'deals', ())
    if deals:
        quantities = tuple(sdk_value(item, 'quantity') for item in deals)
        references = tuple(sdk_text(sdk_value(item, 'seq')) for item in deals)
        if any(type(item) is not int or item <= 0 for item in quantities) or len(set(references)) != len(references):
            raise DomainError('reconciliation_required', 'SDK duplicate/invalid execution')
        total = sum(quantities)
        if type(total) is not int or total <= 0:
            raise DomainError('reconciliation_required', 'SDK execution quantity')
        if total * multiplier != cumulative:
            raise DomainError('reconciliation_required', 'SDK execution history incomplete')
        price = sum((sdk_decimal(sdk_value(item, 'price'), 'fill price') * sdk_value(item, 'quantity') for item in deals), Decimal('0')) / total
    elif cumulative:
        raise DomainError('reconciliation_required', 'SDK fills lack execution economics')
    if not cumulative:
        price = Decimal('0')
    reference = str(sdk_value(raw_order, 'id'))
    return BrokerOrder(local_order_id, plan, cumulative, price, STATUS_MAP[state], reference, now)


def position_from_sdk(raw: object, account_ref: str, binding: InstrumentBinding, sellable: int | None) -> BrokerPosition:
    quantity = sdk_value(raw, 'quantity')
    if type(quantity) is not int:
        raise DomainError('reconciliation_required', 'SDK position quantity')
    direction = sdk_text(sdk_value(raw, 'direction'))
    if direction not in ('Buy', 'Sell'):
        raise DomainError('reconciliation_required', 'SDK position direction')
    if direction == 'Sell':
        quantity = -quantity
    # list_positions must be requested with Unit.Share, never guessed from values.
    if binding.spec.market is Market.STOCK and sellable is None:
        sellable = 0
    if sellable is None:
        sellable = abs(quantity)
    return BrokerPosition(
        account_ref, binding.spec.instrument_id, quantity, sellable, binding.spec.unit, sdk_decimal(sdk_value(raw, 'price'), 'position price'), 'EXTERNAL'
    )


@decimal_operation
def account_from_sdk(
    raw_balance: object,
    raw_limit: object,
    account_ref: str,
    environment: Environment,
    allocated_cash: Decimal,
    settlement_reserved: Decimal,
    now: datetime,
    version: int,
    *,
    futures: bool,
) -> AccountSnapshot:
    if futures:
        equity = sdk_decimal(sdk_value(raw_balance, 'equity'), 'equity')
        cash = sdk_decimal(sdk_value(raw_balance, 'today_balance'), 'settled futures balance')
        margin = sdk_decimal(sdk_value(raw_balance, 'initial_margin'), 'initial margin')
        limit = sdk_decimal(sdk_value(raw_balance, 'available_margin'), 'available margin') + margin
    else:
        cash = sdk_decimal(sdk_value(raw_balance, 'acc_balance'), 'bank balance')
        # Bank balance is cash evidence, not complete securities net liquidation.
        equity = cash
        limit = sdk_decimal(sdk_value(raw_limit, 'trading_available'), 'available trading limit')
        margin = Decimal('0')
    return AccountSnapshot(account_ref, environment, equity, allocated_cash, cash, limit, settlement_reserved, margin, now, version)


def settlement_from_sdk(raw: object, account_ref: str) -> SettlementItem:
    from datetime import date

    raw_date = sdk_value(raw, 'date')
    if type(raw_date) is date:
        settlement_date = raw_date
    elif isinstance(raw_date, str):
        try:
            settlement_date = date.fromisoformat(raw_date)
        except ValueError:
            raise DomainError('reconciliation_required', 'SDK settlement date') from None
    else:
        raise DomainError('reconciliation_required', 'SDK settlement date type')
    return SettlementItem(account_ref, settlement_date, sdk_decimal(sdk_value(raw, 'amount'), 'settlement amount'), 'SHIOAJI')


def history_from_sdk(raw: object, binding: InstrumentBinding) -> tuple[HistoryBar, ...]:
    columns = tuple(tuple(sdk_value(raw, name)) for name in ('ts', 'Open', 'High', 'Low', 'Close', 'Volume'))
    if len({len(column) for column in columns}) != 1 or len(columns[0]) > 50000:
        raise DomainError('reconciliation_required', 'SDK history shape/size')
    bars = []
    for timestamp, open_, high, low, close, volume in zip(*columns):
        # SDK minute bars are published at their end timestamp. Availability is
        # that timestamp; presentation may display the preceding minute start.
        available_at = sdk_time(timestamp)
        bars.append(
            HistoryBar(
                binding.spec.instrument_id,
                available_at - timedelta(minutes=1),
                available_at,
                sdk_decimal(open_, 'open'),
                sdk_decimal(high, 'high'),
                sdk_decimal(low, 'low'),
                sdk_decimal(close, 'close'),
                volume,
                'SHIOAJI',
            )
        )
    if any(left.available_at >= right.available_at for left, right in zip(bars, bars[1:])):
        raise DomainError('reconciliation_required', 'SDK history duplicate/nonmonotone timestamp')
    return tuple(bars)
