"""Immutable v2 application projections; every durable transition is journaled."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sessions import DailyBaselineEvidence

from .codec import register
from .contracts import ReconciliationView, SettingsForm, StrategyForm
from .broker_settings import BrokerReadiness, BrokerSettings
from quantlab.trading.domain.models import Environment, HoldingPolicy, InstrumentSpec, OrderPlan, OrderStatus, PositionLot, Reservation
from quantlab.trading.domain.strategy import StrategyDefinition
from .lifecycle_models import CorporateActionJob, RollJob
from .performance import VersionEquityTrack


@dataclass(frozen=True)
class StrategyRecord:
    strategy_id: str
    version: int
    form: StrategyForm
    policy: HoldingPolicy
    state: str = 'DRAFT'
    evidence: str = ''
    evidence_hash: str = ''
    research_blob: str = ''
    definition: StrategyDefinition | None = None
    draft_hash: str = ''


@dataclass(frozen=True)
class LocalOrder:
    order_id: str
    key: str
    request_hash: str
    plan: OrderPlan
    policy: HoldingPolicy
    reservation: Reservation
    status: OrderStatus
    filled: int = 0
    average_price: Decimal = Decimal('0')
    broker_ref: str = ''
    event_sequence: int = 0
    costs: Decimal = Decimal('0')
    released_quantity: int = 0


@dataclass(frozen=True)
class EventCursor:
    account_ref: str
    sequence: int


@dataclass(frozen=True)
class AppState:
    version: int = 0
    environment: Environment = Environment.LOCAL
    account_ref: str = 'local-stock'
    trading_day: date = date(2026, 10, 23)
    strategies: tuple[StrategyRecord, ...] = ()
    orders: tuple[LocalOrder, ...] = ()
    positions: tuple[PositionLot, ...] = ()
    settings: SettingsForm = SettingsForm(Decimal('60000'), Decimal('40000'), Decimal('0.02'))
    daily_pnl: Decimal = Decimal('0')
    daily_baseline_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    costs: Decimal = Decimal('0')
    daily_locks: tuple[date, ...] = ()
    daily_baseline_required: bool = False
    daily_baseline_evidence: 'DailyBaselineEvidence | None' = None
    stopped: bool = True
    reconciled: bool = False
    issues: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    event_hashes: tuple[tuple[str, str], ...] = ()
    events: tuple[str, ...] = ()
    last_remote_sequence: int = 0
    cursors: tuple[EventCursor, ...] = ()
    engine_closed: bool = False
    broker_settings: BrokerSettings = BrokerSettings()
    broker_readiness: BrokerReadiness | None = None
    corporate_actions: tuple[CorporateActionJob, ...] = ()
    rolls: tuple[RollJob, ...] = ()
    instrument_overrides: tuple[InstrumentSpec, ...] = ()
    protection_stops: tuple[tuple[str, Decimal], ...] = ()
    reconciliation: tuple[ReconciliationView, ...] = ()
    performance_tracks: tuple[VersionEquityTrack, ...] = ()


def replace_order(state: AppState, order: LocalOrder) -> AppState:
    return replace(state, orders=tuple(order if old.order_id == order.order_id else old for old in state.orders))


ACTIVE = frozenset((OrderStatus.SUBMITTING, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCEL_PENDING, OrderStatus.UNKNOWN))

register(AppState, StrategyRecord, LocalOrder, EventCursor)
