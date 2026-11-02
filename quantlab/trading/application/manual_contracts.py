"""Manual simulation intents and projections; none confers execution authority."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from quantlab.trading.domain.models import Environment, Market, PriceBand, QuantityUnit, Side
from quantlab.trading.domain.validation import DomainError, decimal_value, identity, integer


class ManualPurpose(str, Enum):
    MANUAL = 'MANUAL'
    DIAGNOSTIC_TMF = 'DIAGNOSTIC_TMF'


@dataclass(frozen=True)
class ManualScope:
    context_id: str
    context_epoch: int
    environment: Environment
    account_ref: str
    connection_generation: str
    connection_revision: int

    def __post_init__(self) -> None:
        for value in (self.context_id, self.account_ref, self.connection_generation):
            identity(value)
        integer(self.context_epoch, 'context epoch')
        integer(self.connection_revision, 'connection revision')
        if not isinstance(self.environment, Environment):
            raise DomainError('validation_failed', 'manual environment')


@dataclass(frozen=True)
class ManualBookForm:
    scope: ManualScope
    capital: Decimal
    confirmed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ManualScope) or type(self.confirmed) is not bool:
            raise DomainError('validation_failed', 'manual book intent')
        decimal_value(self.capital, 'app virtual capital', positive=True)


@dataclass(frozen=True)
class ManualOrderForm:
    scope: ManualScope
    request_id: str
    instrument_id: str
    side: Side
    quantity: int
    limit_price: Decimal
    stop_price: Decimal
    purpose: ManualPurpose = ManualPurpose.MANUAL
    confirmed: bool = False
    preview_id: str = ''
    exit_lot_id: str = ''

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ManualScope) or not isinstance(self.side, Side) or not isinstance(self.purpose, ManualPurpose):
            raise DomainError('validation_failed', 'manual order types')
        if type(self.confirmed) is not bool:
            raise DomainError('validation_failed', 'manual confirmation')
        for value in (self.request_id, self.instrument_id):
            identity(value)
        for value in (self.preview_id, self.exit_lot_id):
            if value != '':
                identity(value)
        integer(self.quantity, 'manual quantity', 1)
        decimal_value(self.limit_price, 'manual limit price', positive=True)
        decimal_value(self.stop_price, 'risk estimate price', positive=True)


@dataclass(frozen=True)
class ManualMutationForm:
    scope: ManualScope
    request_id: str
    order_id: str
    price: Decimal | None = None
    quantity: int | None = None
    confirmed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ManualScope) or type(self.confirmed) is not bool:
            raise DomainError('validation_failed', 'manual mutation types')
        identity(self.request_id)
        identity(self.order_id)
        if self.price is not None:
            decimal_value(self.price, 'amended limit price', positive=True)
        if self.quantity is not None:
            integer(self.quantity, 'amended total quantity', 1)


@dataclass(frozen=True)
class ManualInstrumentView:
    instrument_id: str
    label: str
    market: Market
    quantity_unit: QuantityUnit
    lot_size: int
    quantity_step: int
    price_tick: Decimal | None
    price_bands: tuple[PriceBand, ...] = ()
    lower_limit: Decimal | None = None
    upper_limit: Decimal | None = None
    last: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    quote_at: datetime | None = None
    margin_per_contract: Decimal | None = None
    margin_source: str = ''
    tradable: bool = False
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualPreviewView:
    scope: ManualScope
    request_id: str
    preview_id: str
    instrument_id: str
    side: Side
    quantity: int
    limit_price: Decimal
    stop_price: Decimal
    purpose: ManualPurpose
    allowed: bool
    total_cash: Decimal
    risk_cash: Decimal
    fee_cash: Decimal
    available_cash: Decimal
    funds_source: str
    cost_source: str
    quote_at: datetime
    expires_at: datetime
    reasons: tuple[str, ...] = ()
    protection: str = 'UNPROTECTED'
    quantity_unit: QuantityUnit | None = None
    lot_size: int = 1
    bid: Decimal | None = None
    ask: Decimal | None = None


@dataclass(frozen=True)
class ManualPendingView:
    scope: ManualScope
    request_id: str
    operation: str
    purpose: ManualPurpose = ManualPurpose.MANUAL
    order_id: str = ''
    status: str = 'PENDING'
    outcome_known: bool = False
    reason: str = ''
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualTradingView:
    scope: ManualScope | None = None
    book_id: str = ''
    capital: Decimal | None = None
    available_cash: Decimal | None = None
    suggested_capital: Decimal | None = None
    source: str = 'APP_VIRTUAL_SIMULATION'
    confirmed: bool = False
    halted: bool = True
    reasons: tuple[str, ...] = ('manual_book_not_enabled',)
    instruments: tuple[ManualInstrumentView, ...] = ()
    preview: ManualPreviewView | None = None
    pending: ManualPendingView | None = None
    last_result: ManualPendingView | None = None
    manual_order_ids: tuple[str, ...] = ()
    test_status: str = 'UNTESTED'
    test_reason: str = ''
    can_prepare: bool = False
    can_preview: bool = False
    can_submit: bool = False
    can_test: bool = False
    can_mutate: bool = False
    protection: str = 'UNPROTECTED'
