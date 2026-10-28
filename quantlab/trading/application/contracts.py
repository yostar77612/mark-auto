"""Typed presentation boundary. No Qt, SDK, persistence or risk implementation."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable

from quantlab.trading.domain.models import Environment, HoldingKind, Market, QuantityUnit, Side
from quantlab.trading.domain.live_bars import DataGap, LiveBar
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.validation import DomainError, identity, integer
from .broker_settings import BrokerReadiness, BrokerSettings


@dataclass(frozen=True)
class MarketHealthView:
    instrument_id: str = ''
    freshness: str = 'UNKNOWN'
    history_error: str = ''
    incomplete: bool = False


@dataclass(frozen=True)
class MarketWatchView:
    instrument_id: str = ''
    price: Decimal | None = None
    reference_price: Decimal | None = None
    change: Decimal | None = None
    change_percent: Decimal | None = None
    source_at: datetime | None = None
    received_at: datetime | None = None
    trade_date: date | None = None
    session: str = ''
    source: str = ''
    bars: tuple[LiveBar, ...] = ()
    gaps: tuple[DataGap, ...] = ()
    health: MarketHealthView = MarketHealthView()
    bid: Decimal | None = None
    ask: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    total_volume: int | None = None
    receive_latency: str = ''


@dataclass(frozen=True)
class OverviewMarketSummary:
    instruments: tuple[MarketHealthView, ...] = ()
    subscription_count: int = 0
    subscription_limit: int = LiveMarketSettings.subscription_limit
    market_revision: int = 0
    has_warning: bool = False


@dataclass(frozen=True)
class MarketSeriesQuery:
    instrument_id: str
    period: str = '1m'
    offset: int = 0
    limit: int = LiveMarketSettings.series_page_limit
    market_revision: int | None = None
    retry_history: bool = False

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        if type(self.retry_history) is not bool:
            raise DomainError('validation_failed', 'history retry flag')
        if self.period not in ('1m', '3m', '5m', '15m', '30m', '60m', '1d'):
            raise DomainError('validation_failed', 'market series period')
        integer(self.offset, 'series offset')
        integer(self.limit, 'series limit', 1)
        if self.market_revision is not None:
            integer(self.market_revision, 'market revision')


@dataclass(frozen=True)
class MarketSeriesPage:
    instrument_id: str
    period: str
    bars: tuple[LiveBar, ...] = ()
    gaps: tuple[DataGap, ...] = ()
    offset: int = 0
    total: int = 0
    next_offset: int | None = None
    market_revision: int = 0


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
    CONNECT_READ_ONLY = 'connect_read_only'
    ADD_CONTEXT = 'add_context'


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
    context_id: str = ''
    profile_ref: str = ''
    context_epoch: int | None = None
    watchlist: tuple[str, ...] | None = None


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
    today_order_count: int | None = None
    today_pnl: Decimal | None = None
    activity_state: str | None = None


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
    unrealized_pnl: Decimal | None = None
    quote_freshness: str = 'UNKNOWN'


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
    net_pnl: Decimal | None
    unrealized_pnl: Decimal | None
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
class ContextOption:
    context_id: str
    label: str
    environment: Environment
    account_refs: tuple[str, ...]
    status: str = 'CONFIGURED'


@dataclass(frozen=True)
class UiState:
    environment: Environment
    account_ref: str
    engine_state: str
    policy_label: str
    allocated_cash: Decimal
    daily_pnl: Decimal | None
    remaining_risk: Decimal | None
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
    contexts: tuple[ContextOption, ...] = ()
    context_id: str = ''
    context_epoch: int = 0
    financial_facts_verified: bool = True
    configuration_id: str = ''
    market_revision: int = 0
    market_watch: tuple[MarketWatchView, ...] = ()
    market_health: OverviewMarketSummary = OverviewMarketSummary()
    market_connection: str = 'UNKNOWN'
    watchlist: tuple[str, ...] = ()
    unrealized_pnl: Decimal | None = None
    remaining_daily_loss: Decimal | None = None
    today_fill_count: int | None = None


class TradingFacade(Protocol):
    def snapshot(self) -> UiState: ...

    def execute(self, command: UiCommand) -> UiReceipt: ...

    def market_series(self, query: MarketSeriesQuery) -> MarketSeriesPage: ...


@dataclass(frozen=True)
class ContextNavigationRequest:
    expected_context_id: str
    expected_epoch: int
    context_id: str
    environment: Environment
    account_ref: str


@runtime_checkable
class ContextNavigationPort(Protocol):
    def navigate_context(self, request: ContextNavigationRequest) -> UiReceipt: ...


class ContextPort(Protocol):
    def list_contexts(self) -> tuple[ContextOption, ...]: ...

    def open_context(self, context_id: str, account_ref: str) -> TradingFacade: ...

    def register_profile(self, profile_ref: str, environment: Environment) -> ContextOption: ...

    def persist_selection(self, context_id: str, account_ref: str) -> None: ...
