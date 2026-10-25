"""Local composition root. All data and rules below are labeled synthetic."""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from quantlab.trading.adapters.simulated.broker import RemoteState, SimulatedBroker
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.codec import dumps, loads, register
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, InstrumentSpec, Market, QuantityUnit, Quote
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder, BrokerPosition, OrderEvent, SettlementItem
from .broker import FilesystemReferenceInspector
from .provenance import compute_profile
from .research_worker import SpawnResearchRunner

TAIPEI = timezone(timedelta(hours=8))


@dataclass
class SimulationClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


@dataclass(frozen=True)
class RemoteImage:
    account: AccountSnapshot
    orders: tuple[BrokerOrder, ...]
    positions: tuple[BrokerPosition, ...]
    position_dates: tuple[tuple[str, date], ...]
    events: tuple[OrderEvent, ...]
    sequence: int
    settlements: tuple[SettlementItem, ...]
    cancel_races: frozenset[str]
    fees: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True)
class RemoteImages:
    items: tuple[RemoteImage, ...]
    clock: datetime
    corporate_receipts: frozenset[str] = frozenset()


def synthetic_calendar() -> TradingCalendar:
    # This generator defines a synthetic lab calendar only. It does not claim
    # exchange holidays, actual sessions or eligibility for imported real data.
    start = date(2025, 10, 23)
    days = tuple(start + timedelta(days=n) for n in range(800) if (start + timedelta(days=n)).weekday() < 5)
    sessions = tuple(TradingSession(day, datetime.combine(day, time(9), TAIPEI), datetime.combine(day, time(13, 30), TAIPEI)) for day in days)
    return TradingCalendar('synthetic-days-v2', 'synthetic-20251023-training-20261023-paper-v2', 'LOCAL_SYNTHETIC_NOT_EXCHANGE', sessions)


def synthetic_catalog() -> Catalog:
    effective = datetime(2026, 1, 1, tzinfo=TAIPEI)
    common = dict(currency='TWD', version='synthetic-spec-v2', source='LOCAL_SYNTHETIC_NOT_BROKER', effective_at=effective)
    stock = InstrumentSpec(
        'TWSE:2330', Market.STOCK, unit=QuantityUnit.SHARE, lot_size=1000, multiplier=Decimal('1'), tick_size=Decimal('0.05'), underlying='2330', **common
    )
    index = InstrumentSpec(
        'TAIFEX:TMF:202612',
        Market.INDEX_FUTURE,
        unit=QuantityUnit.CONTRACT,
        lot_size=1,
        multiplier=Decimal('10'),
        tick_size=Decimal('1'),
        underlying='TAIWAN_INDEX',
        expiry=date(2026, 12, 16),
        margin=Decimal('20000'),
        exchange='TAIFEX',
        delivery_month='202612',
        **common,
    )
    future = InstrumentSpec(
        'TAIFEX:2330F:202612',
        Market.STOCK_FUTURE,
        unit=QuantityUnit.CONTRACT,
        lot_size=1,
        multiplier=Decimal('2000'),
        tick_size=Decimal('0.05'),
        underlying='2330',
        expiry=date(2026, 12, 16),
        margin=Decimal('20000'),
        exchange='TAIFEX',
        delivery_month='202612',
        **common,
    )
    roll_index = replace(index, instrument_id='TAIFEX:TMF:202703', delivery_month='202703', expiry=date(2027, 3, 17))
    roll_stock = replace(future, instrument_id='TAIFEX:2330F:202703', delivery_month='202703', expiry=date(2027, 3, 17))
    extras = tuple(replace(stock, instrument_id=f'TWSE:DEMO{n:02d}', underlying=f'DEMO{n:02d}') for n in range(1, 16))
    return Catalog((stock, index, future, roll_index, roll_stock, *extras))


@decimal_operation
def synthetic_history(catalog: Catalog, calendar: TradingCalendar) -> dict[str, tuple[CompletedBar, ...]]:
    result = {}
    paper_origin = calendar.index(date(2026, 10, 23))
    for spec in catalog.instruments:
        base = Decimal('20000') if spec.market is Market.INDEX_FUTURE else Decimal('50') if spec.market is Market.STOCK_FUTURE else Decimal('10')
        bars = []
        for index, day in enumerate(calendar.days):
            session = calendar.day_session(day)
            # Keep the paper path fixed when extending training lookback.
            phase = index - paper_origin
            step = Decimal(phase % 12) - Decimal('6')
            opened = spec.shift_ticks(base, int(step))
            closed = spec.shift_ticks(opened, 2 if phase % 7 < 4 else -2)
            bars.append(CompletedBar(session.opens_at, session.closes_at, session.closes_at + timedelta(seconds=1), opened, closed, 100000))
        result[spec.instrument_id] = tuple(bars)
    return result


class SimulationControl:
    def __init__(
        self, clock: SimulationClock, gateways: dict[str, SimulatedBroker], ledger: Ledger, version: int = 0, corporate_receipts: frozenset[str] = frozenset()
    ):
        self.clock, self.gateways, self.ledger, self.version = clock, gateways, ledger, version
        self.corporate_receipts = set(corporate_receipts)

    def advance(self, day: date, now: datetime) -> None:
        self.clock.current = now
        for broker in self.gateways.values():
            broker.advance_trade_date(day)
            broker.settle(day)
            # Capability freshness is simulated evidence with explicit source;
            # never applied to an external broker's account.
            broker.capabilities = replace(broker.capabilities, checked_at=now - timedelta(seconds=1), expires_at=now + timedelta(days=1))
        self.persist_remote()

    @decimal_operation
    def fill(self, account_ref: str, order_id: str, quantity: int, price: Decimal, fee: Decimal) -> None:
        broker = self.gateways[account_ref]
        broker.fill(order_id, quantity, price, fee=fee)
        order = broker.remote_state.orders[order_id]
        if order.plan.reduce_only and broker.resolve(order.plan.instrument_id).market is Market.STOCK:
            # Explicit synthetic T+2, using the supplied lab calendar, not weekdays.
            calendar = synthetic_calendar()
            broker.schedule_receivable(price * quantity, calendar.advance(self.clock.now().date(), 2))

    def persist_remote(self) -> None:
        items = []
        for broker in self.gateways.values():
            state = broker.remote_state
            assert state.account is not None
            items.append(
                RemoteImage(
                    state.account,
                    tuple(state.orders.values()),
                    tuple(state.positions.values()),
                    tuple(state.position_dates.items()),
                    tuple(state.events),
                    state.sequence,
                    tuple(state.settlements),
                    frozenset(state.cancel_races),
                    tuple(state.fees.items()),
                )
            )
        event = self.ledger.append(
            'simulated_exchange_snapshot',
            dumps(RemoteImages(tuple(items), self.clock.now(), frozenset(self.corporate_receipts))),
            datetime.now(timezone.utc),
            expected_sequence=self.version,
        )
        self.version = event.sequence

    def corporate_action_applied(self, action_id: str, account_ref: str) -> bool:
        events = self.ledger.replay()
        if not events:
            return False
        image = loads(events[-1].payload)
        return isinstance(image, RemoteImages) and f'{account_ref}:{action_id}' in image.corporate_receipts

    @decimal_operation
    def apply_corporate_action(
        self, action_id: str, instrument_id: str, new_spec: InstrumentSpec, ratio: Decimal, receivable: Decimal, payday: date | None, *, account_ref: str
    ) -> None:
        if self.corporate_action_applied(action_id, account_ref):
            return
        broker = self.gateways[account_ref]
        state = broker.remote_state
        position = state.positions.get(instrument_id)
        old_spec = broker.resolve(instrument_id)
        if (
            position is None
            or ratio <= 0
            or any(
                o.plan.instrument_id == instrument_id and o.status.value in ('ACCEPTED', 'PARTIALLY_FILLED', 'UNKNOWN', 'CANCEL_PENDING')
                for o in state.orders.values()
            )
        ):
            raise DomainError('reconciliation_required', 'corporate action requires confirmed position and no active order')
        signed = Decimal(position.quantity) * ratio
        sellable = Decimal(position.sellable_quantity) * ratio
        if signed != signed.to_integral_value() or sellable != sellable.to_integral_value():
            raise DomainError('reconciliation_required', 'fractional corporate adjustment')
        factor = old_spec.multiplier / (ratio * new_spec.multiplier)
        state.positions[instrument_id] = replace(position, quantity=int(signed), sellable_quantity=int(sellable), average_cost=position.average_cost * factor)
        assert state.account is not None
        margin_delta = (
            ((new_spec.margin or Decimal('0')) * abs(int(signed)) - (old_spec.margin or Decimal('0')) * abs(position.quantity))
            if old_spec.market is not Market.STOCK
            else Decimal('0')
        )
        state.account = replace(
            state.account,
            equity=state.account.equity + receivable,
            unsettled_receivables=state.account.unsettled_receivables + receivable,
            margin_used=state.account.margin_used + margin_delta,
            version=state.account.version + 1,
        )
        if receivable:
            if payday is None:
                raise DomainError('calendar_missing', 'explicit dividend payment date required')
            broker.schedule_receivable(receivable, payday)
        for gateway in self.gateways.values():
            gateway.instruments[instrument_id] = new_spec
        self.corporate_receipts.add(f'{account_ref}:{action_id}')
        self.persist_remote()

    @decimal_operation
    def rebuild_history(self, engine: TradingEngine) -> None:
        base = synthetic_catalog()
        history = synthetic_history(base, engine.calendar)
        for job in engine.state.corporate_actions:
            if job.status != 'APPLIED':
                continue
            factor = job.old_spec.multiplier / (job.action.quantity_ratio * job.new_spec.multiplier)
            adjusted = []
            for bar in history[job.instrument_id]:
                if bar.opened_at >= job.action.effective_at:
                    opened = job.new_spec.round_price((bar.open - job.action.cash_per_old_unit) * factor)
                    closed = job.new_spec.round_price((bar.close - job.action.cash_per_old_unit) * factor)
                    bar = replace(bar, open=opened, close=closed)
                adjusted.append(bar)
            history[job.instrument_id] = tuple(adjusted)
        engine.history = history
        for spec in engine.catalog.instruments:
            for gateway in self.gateways.values():
                gateway.instruments[spec.instrument_id] = spec
            bar = next(b for b in history[spec.instrument_id] if b.opened_at.date() == engine.state.trading_day)
            engine.quotes.pop(spec.instrument_id, None)
            engine.quote(
                Quote(
                    spec.instrument_id,
                    bar.open,
                    spec.shift_ticks(bar.open, 1),
                    bar.open,
                    self.clock.now(),
                    self.clock.now(),
                    engine.state.trading_day,
                    sequence=engine.quote_count + 1,
                )
            )


def create_engine(root: Path) -> TradingEngine:
    if not root.is_absolute() or root.is_symlink():
        raise DomainError('validation_failed', 'absolute isolated v2 root required')
    root.mkdir(parents=True, exist_ok=True)
    initialize()
    register(RemoteImage, RemoteImages)
    calendar, catalog = synthetic_calendar(), synthetic_catalog()
    clock = SimulationClock(calendar.day_session(date(2026, 10, 23)).opens_at + timedelta(minutes=5))
    remote_ledger = Ledger(root / 'simulated-exchange-v2.sqlite', 'local-exchange', datetime.now(timezone.utc))
    image_events = remote_ledger.replay()
    images = loads(image_events[-1].payload) if image_events else None
    if images is not None and not isinstance(images, RemoteImages):
        raise DomainError('journal_failed', 'remote simulation snapshot schema')
    if images:
        clock.current = images.clock
    gateways = {}
    for ref, allocation, markets in (
        ('local-stock', '60000', frozenset((Market.STOCK,))),
        ('local-futures', '40000', frozenset((Market.INDEX_FUTURE, Market.STOCK_FUTURE))),
    ):
        account = AccountSnapshot(
            ref,
            Environment.LOCAL,
            Decimal(allocation),
            Decimal(allocation),
            Decimal(allocation),
            Decimal(allocation),
            Decimal('0'),
            Decimal('0'),
            clock.now(),
            0,
        )
        capability = CapabilitySnapshot(
            ref,
            Environment.LOCAL,
            markets,
            False,
            ref == 'local-futures',
            False,
            True,
            True,
            'LOCAL_SYNTHETIC_CAPABILITY',
            clock.now() - timedelta(seconds=1),
            clock.now() + timedelta(days=1),
            'local-capability-v2',
        )
        image = next((i for i in images.items if i.account.account_ref == ref), None) if images else None
        remote = (
            RemoteState(
                orders={o.local_order_id: o for o in image.orders},
                positions={p.instrument_id: p for p in image.positions},
                position_dates=dict(image.position_dates),
                events=list(image.events),
                sequence=image.sequence,
                account=image.account,
                settlements=list(image.settlements),
                cancel_races=set(image.cancel_races),
                fees=dict(image.fees),
            )
            if image
            else None
        )
        gateways[ref] = SimulatedBroker(clock, account, catalog.instruments, capability, remote)
    control = SimulationControl(clock, gateways, remote_ledger, len(image_events), images.corporate_receipts if images else frozenset())
    try:
        journal = Ledger(root / 'trading-v2.sqlite', 'platform-local', datetime.now(timezone.utc))
    except BaseException:
        remote_ledger.close()
        raise
    try:
        engine = TradingEngine(
            journal,
            clock,
            calendar,
            catalog,
            gateways,
            simulation=control,
            reference_inspector=FilesystemReferenceInspector((root,)),
            source_profile=compute_profile(),
            research_runner=SpawnResearchRunner(),
        )
    except BaseException:
        journal.close()
        remote_ledger.close()
        raise
    # Snapshot clock is authoritative only inside this explicitly local lab.
    if engine.state.trading_day != clock.now().date():
        engine._persist('local_clock_restored', replace(engine.state, trading_day=clock.now().date()))
    control.rebuild_history(engine)
    for spec in engine.catalog.instruments:
        gateway = gateways['local-stock' if spec.market is Market.STOCK else 'local-futures']
        gateway.subscribe((spec.instrument_id,))
    control.persist_remote()
    return engine
