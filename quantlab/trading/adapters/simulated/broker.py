"""Authoritative simulated remote state, independent from the application's journal."""

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import (
    AccountSnapshot,
    CapabilitySnapshot,
    Environment,
    InstrumentSpec,
    Market,
    OrderPlan,
    OrderStatus,
    Quote,
    Side,
)
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, integer
from quantlab.trading.ports.contracts import (
    BrokerOrder,
    BrokerPosition,
    CommandReceipt,
    ConnectionState,
    DataBatch,
    HistoryBar,
    OrderEvent,
    RemoteSnapshot,
    SettlementItem,
    SubmissionReceipt,
    SubscriptionReceipt,
)
from quantlab.trading.ports.interfaces import Clock


@dataclass(frozen=True)
class FaultPlan:
    """One-shot faults are explicit; remote acceptance can precede a lost reply."""

    reject: bool = False
    unknown_after_accept: bool = False
    disconnect_before_submit: bool = False
    partial_quantity: int = 0
    duplicate_event: bool = False
    cancel_fill_race: bool = False
    drop_event: bool = False

    def __post_init__(self) -> None:
        integer(self.partial_quantity, 'partial_quantity')
        if any(
            type(getattr(self, key)) is not bool
            for key in ('reject', 'unknown_after_accept', 'disconnect_before_submit', 'duplicate_event', 'cancel_fill_race', 'drop_event')
        ):
            raise DomainError('validation_failed', 'fault flags')


@dataclass
class RemoteState:
    """Exchange state survives application/adapter restart when the same state is reused."""

    orders: dict[str, BrokerOrder] = field(default_factory=dict)
    positions: dict[str, BrokerPosition] = field(default_factory=dict)
    position_dates: dict[str, date] = field(default_factory=dict)
    events: list[OrderEvent] = field(default_factory=list)
    sequence: int = 0
    account: AccountSnapshot | None = None
    settlements: list[SettlementItem] = field(default_factory=list)
    cancel_races: set[str] = field(default_factory=set)
    fees: dict[str, Decimal] = field(default_factory=dict)


class SimulatedBroker:
    def __init__(
        self,
        clock: Clock,
        account: AccountSnapshot,
        instruments: tuple[InstrumentSpec, ...],
        capabilities: CapabilitySnapshot,
        remote_state: RemoteState | None = None,
        *,
        fee_schedule: FeeSchedule | None = None,
    ) -> None:
        if account.environment is not Environment.LOCAL or capabilities.environment is not Environment.LOCAL or account.account_ref != capabilities.account_ref:
            raise DomainError('capability_missing', 'local-only account mismatch')
        self.clock = clock
        self.account_ref = account.account_ref
        self.instruments = {item.instrument_id: item for item in instruments}
        self.capabilities = capabilities
        self.fees = fee_schedule if fee_schedule is not None else FeeSchedule()
        self.remote_state = remote_state if remote_state is not None else RemoteState()
        if self.remote_state.account is None:
            self.remote_state.account = account
        elif self.remote_state.account.account_ref != account.account_ref or self.remote_state.account.environment is not Environment.LOCAL:
            raise DomainError('state_conflict', 'remote account identity')
        self.connected = True
        self.submission_count = 0
        self.faults: deque[FaultPlan] = deque()
        self.quotes: dict[str, Quote] = {}
        self.bars: dict[str, tuple[HistoryBar, ...]] = {}
        self.subscriptions: dict[str, tuple[str, ...]] = {}
        self.subscription_counter = 0

    def queue_fault(self, fault: FaultPlan) -> None:
        if not isinstance(fault, FaultPlan):
            raise DomainError('validation_failed', 'fault plan required')
        self.faults.append(fault)

    def _query(self, account_ref: str) -> None:
        if account_ref != self.account_ref:
            raise DomainError('capability_missing', 'explicit account mismatch')
        if not self.connected:
            raise DomainError('reconciliation_required', 'simulated disconnect')

    def connect(self, secret_ref: str, environment: Environment) -> ConnectionState:
        if environment is not Environment.LOCAL or secret_ref not in ('', 'local-simulation'):
            raise DomainError('capability_missing', 'local simulator does not accept credentials')
        self.connected = True
        return ConnectionState(Environment.LOCAL, True, (self.account_ref,), self.clock.now())

    def disconnect(self) -> None:
        self.connected = False

    def inspect(self, account_ref: str) -> CapabilitySnapshot:
        self._query(account_ref)
        return self.capabilities

    def resolve(self, instrument_id: str) -> InstrumentSpec:
        if instrument_id not in self.instruments:
            raise DomainError('instrument_unresolved', 'actual known contract required')
        return self.instruments[instrument_id]

    def snapshot(self, account_ref: str) -> AccountSnapshot:
        self._query(account_ref)
        assert self.remote_state.account is not None
        return replace(self.remote_state.account, as_of=self.clock.now())

    def settlements(self, account_ref: str) -> tuple[SettlementItem, ...]:
        self._query(account_ref)
        return tuple(self.remote_state.settlements)

    def list(self, account_ref: str) -> tuple[BrokerPosition, ...]:
        self._query(account_ref)
        return tuple(sorted(self.remote_state.positions.values(), key=lambda item: item.instrument_id))

    def refresh(self, account_ref: str) -> RemoteSnapshot:
        self._query(account_ref)
        return RemoteSnapshot(
            self.snapshot(account_ref), tuple(self.remote_state.orders.values()), self.list(account_ref), self.remote_state.sequence, self.clock.now()
        )

    def events(self, account_ref: str, after_sequence: int = 0) -> tuple[OrderEvent, ...]:
        self._query(account_ref)
        integer(after_sequence, 'event cursor')
        return tuple(event for event in self.remote_state.events if event.sequence > after_sequence)

    def _emit(self, order: BrokerOrder, quantity: int = 0, price: Decimal = Decimal('0'), *, duplicate: bool = False, drop: bool = False) -> OrderEvent:
        self.remote_state.sequence += 1
        event = OrderEvent(
            f'sim-event-{self.remote_state.sequence}',
            order.local_order_id,
            order.broker_order_ref,
            order.status,
            order.cumulative_quantity,
            quantity,
            price,
            self.clock.now(),
            self.remote_state.sequence,
            'LOCAL_SIMULATED',
        )
        if not drop:
            self.remote_state.events.append(event)
            if duplicate:
                self.remote_state.events.append(event)
        return event

    @decimal_operation
    def submit(self, plan: OrderPlan, local_order_id: str) -> SubmissionReceipt:
        identity(local_order_id)
        self._query(plan.account_ref)
        now = self.clock.now()
        if plan.environment is not Environment.LOCAL or plan.deadline <= now:
            raise DomainError('capability_missing', 'environment or deadline')
        cap = self.inspect(plan.account_ref)
        if not cap.can_trade or cap.expires_at <= now:
            raise DomainError('capability_missing', 'expired or read-only capability')
        spec = self.resolve(plan.instrument_id)
        if spec.market not in cap.markets:
            raise DomainError('capability_missing', 'market capability')
        spec.validate_quantity(plan.quantity, plan.unit, odd_lot=cap.odd_lot)
        spec.validate_price(plan.limit_price)
        if local_order_id in self.remote_state.orders:
            # The exchange is deliberately not a local idempotency implementation.
            raise DomainError('state_conflict', 'remote duplicate submission refused')
        fault = self.faults.popleft() if self.faults else FaultPlan()
        if fault.disconnect_before_submit:
            self.disconnect()
            raise DomainError('outcome_unknown', 'connection lost during submission')
        self.submission_count += 1
        status = OrderStatus.REJECTED if fault.reject else OrderStatus.ACCEPTED
        order = BrokerOrder(local_order_id, plan, 0, Decimal('0'), status, f'sim-broker-{local_order_id}', now)
        self.remote_state.orders[local_order_id] = order
        self._emit(order, duplicate=fault.duplicate_event, drop=fault.drop_event)
        if fault.cancel_fill_race:
            self.remote_state.cancel_races.add(local_order_id)
        if fault.partial_quantity and not fault.reject:
            self.fill(local_order_id, min(plan.quantity, fault.partial_quantity), plan.limit_price)
        if fault.unknown_after_accept:
            self.disconnect()
            return SubmissionReceipt(local_order_id, None, OrderStatus.UNKNOWN, now, False, 'outcome_unknown')
        return SubmissionReceipt(
            local_order_id, order.broker_order_ref, self.remote_state.orders[local_order_id].status, now, True, 'broker_rejected' if fault.reject else ''
        )

    @decimal_operation
    def fill(self, local_order_id: str, quantity: int, price: Decimal, *, fee: Decimal | None = None) -> OrderEvent:
        """Inject an exchange fill; fees come from the shared domain cost calculator."""
        integer(quantity, 'fill quantity', 1)
        order = self.remote_state.orders[local_order_id]
        spec = self.resolve(order.plan.instrument_id)
        spec.validate_price(price)
        cumulative = order.cumulative_quantity + quantity
        average = (order.average_price * order.cumulative_quantity + price * quantity) / cumulative
        if fee is None:
            fee = self.fees.incremental_transaction(spec, order.plan.side, average, cumulative, self.remote_state.fees.get(local_order_id, Decimal('0')))
        decimal_value(fee, 'fee', nonnegative=True)
        if order.plan.side is Side.BUY and price > order.plan.limit_price or order.plan.side is Side.SELL and price < order.plan.limit_price:
            raise DomainError('validation_failed', 'fill would violate limit price')
        if order.status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED) or quantity > order.plan.quantity - order.cumulative_quantity:
            raise DomainError('state_conflict', 'fill exceeds active remainder')
        current = self.remote_state.positions.get(spec.instrument_id)
        signed = quantity if order.plan.side is Side.BUY else -quantity
        old_quantity = current.quantity if current else 0
        if order.plan.reduce_only and (old_quantity * signed >= 0 or abs(signed) > abs(old_quantity)):
            raise DomainError('risk_rejected', 'reduce-only would open/reverse position')
        if spec.market is Market.STOCK and signed < 0 and (current is None or quantity > current.sellable_quantity):
            raise DomainError('eligibility_unknown', 'stock position not currently sellable')
        account = self._account_after_fill(spec, current, old_quantity, signed, price, fee)
        order = replace(
            order,
            cumulative_quantity=cumulative,
            average_price=average,
            status=OrderStatus.FILLED if cumulative == order.plan.quantity else OrderStatus.PARTIALLY_FILLED,
            updated_at=self.clock.now(),
        )
        self.remote_state.orders[local_order_id] = order
        self._fill_position(spec, current, old_quantity, signed, price)
        self.remote_state.account = account
        self.remote_state.fees[local_order_id] = self.remote_state.fees.get(local_order_id, Decimal('0')) + fee
        return self._emit(order, quantity, price)

    def _fill_position(self, spec: InstrumentSpec, current: BrokerPosition | None, old_quantity: int, signed: int, price: Decimal) -> None:
        new_quantity = old_quantity + signed
        if not new_quantity:
            self.remote_state.positions.pop(spec.instrument_id, None)
            self.remote_state.position_dates.pop(spec.instrument_id, None)
            return
        if current and old_quantity * signed > 0:
            cost = (current.average_cost * abs(old_quantity) + price * abs(signed)) / abs(new_quantity)
        else:
            cost = current.average_cost if current and old_quantity * new_quantity > 0 else price
        sellable = abs(new_quantity)
        if spec.market is Market.STOCK and signed > 0 and not self.capabilities.day_trade:
            sellable = current.sellable_quantity if current else 0
        elif spec.market is Market.STOCK and current and signed < 0:
            sellable = max(0, current.sellable_quantity - abs(signed))
        self.remote_state.positions[spec.instrument_id] = BrokerPosition(
            self.account_ref, spec.instrument_id, new_quantity, min(abs(new_quantity), sellable), spec.unit, cost, 'MANAGED'
        )
        if spec.market is Market.STOCK and signed > 0:
            # Most recent acquisition date prevents a repeated same-day advance
            # from making today's add-on quantity sellable with older inventory.
            self.remote_state.position_dates[spec.instrument_id] = self.clock.now().date()
        else:
            self.remote_state.position_dates.setdefault(spec.instrument_id, self.clock.now().date())

    def _account_after_fill(
        self, spec: InstrumentSpec, current: BrokerPosition | None, old_quantity: int, signed: int, price: Decimal, fee: Decimal
    ) -> AccountSnapshot:
        assert self.remote_state.account is not None
        account = self.remote_state.account
        realized = Decimal('0')
        if current and old_quantity * signed < 0:
            realized = (price - current.average_cost) * min(abs(old_quantity), abs(signed)) * spec.multiplier * (1 if old_quantity > 0 else -1)
        # Unsettled stock sale proceeds are deliberately not reusable cash.
        proceeds = price * abs(signed) if spec.market is Market.STOCK and signed < 0 else Decimal('0')
        cash_change = -price * signed if spec.market is Market.STOCK and signed > 0 else realized if spec.market is not Market.STOCK else Decimal('0')
        cash = account.settled_cash + cash_change - fee
        if cash < 0:
            # Model exchange credit rejection atomically before use; tests normally
            # prevent this through the application reservation/risk path.
            raise DomainError('insufficient_funds', 'simulated settled cash')
        margin_change = Decimal('0')
        if spec.market is not Market.STOCK:
            if spec.margin is None:
                raise DomainError('risk_rejected', 'missing simulated margin')
            margin_change = spec.margin * (abs(old_quantity + signed) - abs(old_quantity))
        margin = account.margin_used + margin_change
        if margin > cash:
            raise DomainError('insufficient_funds', 'simulated margin')
        return replace(
            account,
            equity=account.equity + realized - fee,
            settled_cash=cash,
            unsettled_receivables=account.unsettled_receivables + proceeds,
            margin_used=margin,
            as_of=self.clock.now(),
            version=account.version + 1,
        )

    @decimal_operation
    def schedule_receivable(self, amount: Decimal, settlement_date: date) -> None:
        """The caller supplies a versioned calendar date; no weekday inference."""
        decimal_value(amount, 'settlement amount', positive=True)
        assert self.remote_state.account is not None
        if sum((item.amount for item in self.remote_state.settlements), Decimal('0')) + amount > self.remote_state.account.unsettled_receivables:
            raise DomainError('state_conflict', 'receivable already scheduled or absent')
        self.remote_state.settlements.append(SettlementItem(self.account_ref, settlement_date, amount, 'LOCAL_SIMULATED'))

    @decimal_operation
    def settle(self, trade_date: date) -> None:
        if type(trade_date) is not date:
            raise DomainError('validation_failed', 'settlement date')
        due = tuple(item for item in self.remote_state.settlements if item.settlement_date <= trade_date)
        amount = sum((item.amount for item in due), Decimal('0'))
        assert self.remote_state.account is not None
        account = self.remote_state.account
        self.remote_state.account = replace(
            account, settled_cash=account.settled_cash + amount, unsettled_receivables=account.unsettled_receivables - amount, version=account.version + 1
        )
        self.remote_state.settlements[:] = [item for item in self.remote_state.settlements if item not in due]

    def cancel(self, local_order_id: str) -> CommandReceipt:
        self._query(self.account_ref)
        order = self.remote_state.orders[local_order_id]
        if local_order_id in self.remote_state.cancel_races and order.cumulative_quantity < order.plan.quantity:
            self.remote_state.cancel_races.remove(local_order_id)
            self.fill(local_order_id, order.plan.quantity - order.cumulative_quantity, order.plan.limit_price)
            order = self.remote_state.orders[local_order_id]
        if order.status not in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED):
            order = replace(order, status=OrderStatus.CANCELED, updated_at=self.clock.now())
            self.remote_state.orders[local_order_id] = order
            self._emit(order)
        return CommandReceipt(f'cancel-{local_order_id}', True, order.status, local_order_id, self.clock.now())

    @decimal_operation
    def amend(self, local_order_id: str, price: Decimal, quantity: int | None = None) -> CommandReceipt:
        self._query(self.account_ref)
        order = self.remote_state.orders[local_order_id]
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            raise DomainError('state_conflict', 'amend terminal order')
        new_quantity = order.plan.quantity if quantity is None else quantity
        if type(new_quantity) is not int or not order.cumulative_quantity < new_quantity <= order.plan.quantity:
            raise DomainError('validation_failed', 'amend only reduces unfilled quantity')
        spec = self.resolve(order.plan.instrument_id)
        spec.validate_quantity(new_quantity, order.plan.unit, odd_lot=self.capabilities.odd_lot)
        spec.validate_price(price)
        plan = replace(order.plan, quantity=new_quantity, limit_price=price)
        order = replace(order, plan=plan, updated_at=self.clock.now())
        self.remote_state.orders[local_order_id] = order
        self._emit(order)
        return CommandReceipt(f'amend-{local_order_id}', True, order.status, local_order_id, self.clock.now())

    def advance_trade_date(self, trade_date: date) -> None:
        if type(trade_date) is not date:
            raise DomainError('validation_failed', 'explicit trade date')
        for instrument_id, position in tuple(self.remote_state.positions.items()):
            if self.remote_state.position_dates.get(instrument_id, trade_date) < trade_date:
                self.remote_state.positions[instrument_id] = replace(position, sellable_quantity=abs(position.quantity))

    def external_position(self, position: BrokerPosition) -> None:
        if position.account_ref != self.account_ref or position.source != 'EXTERNAL':
            raise DomainError('validation_failed', 'external account/source')
        self.remote_state.positions[position.instrument_id] = position

    def reorder_events(self, sequences: tuple[int, ...]) -> None:
        """Explicitly change delivery order, not the immutable exchange sequence."""
        if sorted(sequences) != sorted(event.sequence for event in self.remote_state.events):
            raise DomainError('validation_failed', 'event reorder must preserve every event')
        by_sequence: dict[int, deque[OrderEvent]] = {}
        for event in self.remote_state.events:
            by_sequence.setdefault(event.sequence, deque()).append(event)
        self.remote_state.events[:] = [by_sequence[seq].popleft() for seq in sequences]

    def history(self, instrument_id: str, start: datetime, end: datetime) -> DataBatch:
        self._query(self.account_ref)
        aware(start)
        aware(end)
        self.resolve(instrument_id)
        if end <= start:
            raise DomainError('validation_failed', 'history range')
        bars = tuple(bar for bar in self.bars.get(instrument_id, ()) if start <= bar.start and bar.available_at <= end)
        return DataBatch(instrument_id, bars, 'LOCAL_SIMULATED', bool(bars), '' if bars else 'no_data')

    def subscribe(self, instrument_ids: tuple[str, ...]) -> SubscriptionReceipt:
        self._query(self.account_ref)
        if type(instrument_ids) is not tuple or not 1 <= len(instrument_ids) <= 20 or len(set(instrument_ids)) != len(instrument_ids):
            raise DomainError('validation_failed', 'subscription limit')
        for instrument_id in instrument_ids:
            self.resolve(instrument_id)
        active = {item for items in self.subscriptions.values() for item in items}
        if len(active | set(instrument_ids)) > 20 or len(self.subscriptions) >= 20:
            raise DomainError('capability_missing', 'total subscription capacity')
        self.subscription_counter += 1
        subscription_id = f'sim-sub-{self.subscription_counter}'
        self.subscriptions[subscription_id] = instrument_ids
        return SubscriptionReceipt(subscription_id, instrument_ids, True, self.clock.now())

    def unsubscribe(self, subscription_id: str) -> None:
        self.subscriptions.pop(subscription_id, None)

    def latest(self, instrument_id: str) -> Quote | None:
        self._query(self.account_ref)
        self.resolve(instrument_id)
        return self.quotes.get(instrument_id)
