"""Typed presentation boundary. No Qt, SDK, persistence or risk implementation."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Protocol

from quantlab.trading.domain.models import Environment, HoldingKind, Market, QuantityUnit, Side
from .broker_settings import BrokerReadiness, BrokerSettings


class UiAction(str, Enum):
    CREATE_STRATEGY = 'create_strategy'
    VALIDATE = 'validate'
    RESEARCH = 'research'
    DEPLOY = 'deploy'
    STEP = 'step'
    RECONCILE = 'reconcile'
    STOP_NEW = 'stop_new'
    RESUME = 'resume'
    CANCEL_ENTRIES = 'cancel_entries'
    FLATTEN = 'flatten'
    TRANSFER = 'transfer'
    SAVE_SETTINGS = 'save_settings'
    SWITCH_CONTEXT = 'switch_context'
    SHUTDOWN_ENGINE = 'shutdown_engine'
    SAVE_BROKER_SETTINGS = 'save_broker_settings'
    CHECK_READINESS = 'check_readiness'


@dataclass(frozen=True)
class StrategyForm:
    name: str
    market: Market
    holding_kind: HoldingKind
    min_days: int
    max_days: int
    direction: Side
    instrument_id: str
    account_ref: str
    environment: Environment
    allocation: Decimal
    risk_fraction: Decimal
    rule_kind: str = 'MA_CROSS'
    parent_strategy_id: str = ''
    new_entries_only: bool = True
    draft_json: str = ''
    expiry_action: str = 'EXIT'
    roll_contract_id: str = ''


@dataclass(frozen=True)
class SettingsForm:
    stock_allocation: Decimal
    futures_allocation: Decimal
    risk_fraction: Decimal
    daily_loss_fraction: Decimal = Decimal('0.10')
    night_enabled: bool = False


@dataclass(frozen=True)
class UiCommand:
    action: UiAction
    expected_version: int
    target_id: str = ''
    strategy: StrategyForm | None = None
    settings: SettingsForm | None = None
    environment: Environment | None = None
    account_ref: str = ''
    destination_strategy_id: str = ''
    broker_settings: BrokerSettings | None = None


@dataclass(frozen=True)
class UiReceipt:
    accepted: bool
    code: str
    message: str
    reference: str = ''


@dataclass(frozen=True)
class StrategyView:
    strategy_id: str
    name: str
    version: int
    market: Market
    instrument_id: str
    holding_kind: HoldingKind
    policy_label: str
    state: str
    account_ref: str
    environment: Environment
    evidence: str
    allocation: Decimal = Decimal('0')
    risk_fraction: Decimal = Decimal('0.02')
    expiry_action: str = 'EXIT'
    roll_contract_id: str = ''


@dataclass(frozen=True)
class PositionView:
    lot_id: str
    instrument_id: str
    strategy_id: str
    strategy_version: int
    policy_label: str
    quantity: int
    unit: QuantityUnit
    sellable_quantity: int
    entry_day: str
    held_days: int
    exit_window: str
    protection: str
    quote_time: str
    source: str
    account_ref: str = ''
    direction: Side = Side.BUY


@dataclass(frozen=True)
class ReconciliationView:
    account_ref: str
    instrument_id: str
    local_quantity: int | None
    broker_quantity: int | None
    sellable_quantity: int | None
    unit: QuantityUnit
    kind: str = 'POSITION'
    broker_order_ref: str = ''
    status: str = ''
    as_of: str = ''


@dataclass(frozen=True)
class OrderView:
    order_id: str
    instrument_id: str
    side: Side
    quantity: int
    filled: int
    unit: QuantityUnit
    state: str
    reduce_only: bool
    account_ref: str = ''


@dataclass(frozen=True)
class MarketView:
    instrument_id: str
    market: Market
    unit: QuantityUnit
    price: Decimal | None
    quote_time: str
    availability: str
    source: str
    underlying: str = ''
    delivery_month: str = ''
    expiry_day: str = ''


@dataclass(frozen=True)
class PerformanceView:
    strategy_id: str
    version: int
    market: Market
    policy_label: str
    environment: Environment
    net_pnl: Decimal
    unrealized_pnl: Decimal
    costs: Decimal
    drawdown: Decimal | None
    holding_days: str
    drawdown_coverage: str = 'LEGACY_UNKNOWN'
    drawdown_as_of: str = ''
    drawdown_basis: str = 'RECORDED_NET_LIQUIDATION_V1'
    attributed_pnl: Decimal | None = None


@dataclass(frozen=True)
class AccountView:
    account_ref: str
    environment: Environment
    market: Market
    allocation: Decimal
    readiness: str


@dataclass(frozen=True)
class UiState:
    environment: Environment
    account_ref: str
    engine_state: str
    policy_label: str
    allocated_cash: Decimal
    daily_pnl: Decimal
    remaining_risk: Decimal
    quote_status: str
    version: int
    trading_day: str
    synthetic_data: bool
    issues: tuple[str, ...] = ()
    strategies: tuple[StrategyView, ...] = ()
    positions: tuple[PositionView, ...] = ()
    orders: tuple[OrderView, ...] = ()
    markets: tuple[MarketView, ...] = ()
    performance: tuple[PerformanceView, ...] = ()
    accounts: tuple[AccountView, ...] = ()
    events: tuple[str, ...] = ()
    settings: SettingsForm = SettingsForm(Decimal('60000'), Decimal('40000'), Decimal('0.02'))
    cost_version: str = 'local-demo-cost-v1'
    risk_version: str = 'local-risk-v2'
    quote_revision: int = 0
    broker_settings: BrokerSettings = BrokerSettings()
    broker_readiness: BrokerReadiness | None = None
    reconciliation: tuple[ReconciliationView, ...] = ()
    reconciliation_verified: bool = False


class TradingFacade(Protocol):
    def snapshot(self) -> UiState: ...

    def execute(self, command: UiCommand) -> UiReceipt: ...
