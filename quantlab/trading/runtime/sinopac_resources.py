"""Generated typed resource bundle; broker finances are never synthesized.

The initial executable catalogue is ordinary cash security 2330 and the nearest
actual TMF contract. Other M1 watch symbols remain searchable/displayable. Fees
are explicit estimates; TMF margin is an exchange reference, not broker funds.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding, sdk_decimal, sdk_text, sdk_value
from quantlab.trading.adapters.shioaji.account_discovery import DiscoveredAccount
from quantlab.trading.adapters.shioaji.stock_grid import CLASSIFICATIONS
from quantlab.trading.application.context import Catalog
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.models import CapabilitySnapshot, InstrumentSpec, Market, QuantityUnit
from quantlab.trading.domain.validation import DomainError
from .sinopac_calendar import built_in_calendar, CALENDAR_ID
from .sinopac_classification import load_classification


@dataclass(frozen=True)
class ContractPriceLimits:
    instrument_id: str
    lower: Decimal
    upper: Decimal
    observed_at: datetime
    source: str = 'shioaji-1.7.9-ContractV2-info-daily-limits'


@dataclass(frozen=True)
class SinopacResources:
    catalog: Catalog
    bindings: tuple[InstrumentBinding, ...]
    calendar: TradingCalendar
    fees: FeeSchedule
    accounts: tuple[DiscoveredAccount, ...]
    capabilities: tuple[CapabilitySnapshot, ...]
    limits: tuple[ContractPriceLimits, ...]
    margin_source: str = 'exchange-TAIFEX-TMF-initial-35050-TWD-20260812-observed-20261101'
    fee_source: str = 'application-fee-estimate-v1-not-broker-billing'


def _stock_binding(facade, now):
    base = facade.contracts.get('2330')
    info = facade.contracts.info(base)
    exchange = sdk_text(sdk_value(base, 'exchange'))
    if exchange not in ('TSE', 'OTC') or sdk_text(sdk_value(info, 'currency')) != 'TWD' or getattr(info, 'trading_suspended', None) is not False:
        raise DomainError('instrument_unresolved', 'stock currency/exchange/trading status unavailable')
    evidence = load_classification('2330', exchange, now)
    _, rule, bands = CLASSIFICATIONS[evidence.product_class]
    lot = sdk_decimal(sdk_value(info, 'unit'), 'stock lot')
    if lot <= 0 or lot != lot.to_integral_value():
        raise DomainError('instrument_unresolved', 'stock lot size unavailable')
    spec = InstrumentSpec(
        'TWSE:2330' if exchange == 'TSE' else 'TPEX:2330',
        Market.STOCK,
        'TWD',
        QuantityUnit.SHARE,
        int(lot),
        Decimal(1),
        bands[0].tick,
        '2330',
        'shioaji-1.7.9-generated-v1',
        'shioaji-ContractV2-and-public-ISIN',
        now,
        exchange=exchange,
        tick_rule_id=rule,
        calendar_id=CALENDAR_ID,
        price_bands=bands,
    )
    return InstrumentBinding(spec, '2330', evidence), info


def _future_binding(facade, now, offset=0):
    candidates = []
    for base in facade.execution_contracts('FUT'):
        code = sdk_text(sdk_value(base, 'code'))
        if not code.startswith('TMF') or code.endswith(('R1', 'R2')):
            continue
        info = facade.contracts.info(base)
        if sdk_text(sdk_value(info, 'root')) == 'TMF' and sdk_value(info, 'delivery_date') >= now.astimezone(ZoneInfo('Asia/Taipei')).date():
            candidates.append((sdk_value(info, 'delivery_date'), code, info))
    if len(candidates) <= offset:
        raise DomainError('instrument_unresolved', 'actual unexpired TMF contract unavailable')
    _, code, info = sorted(candidates, key=lambda item: (item[0], item[1]))[offset]
    if sdk_text(sdk_value(info, 'exchange')) != 'TAIFEX' or sdk_decimal(sdk_value(info, 'multiplier'), 'TMF multiplier') != 10:
        raise DomainError('instrument_unresolved', 'TMF identity or multiplier mismatch')
    basis = sdk_text(sdk_value(info, 'tick_basis'))
    bands = facade.contracts.tick_bands(info) if basis == 'price' else ()
    if basis not in ('fixed', 'price') or basis == 'fixed' and sdk_value(info, 'tick_rule') is not None:
        raise DomainError('instrument_unresolved', 'TMF tick evidence unavailable')
    tick = bands[0].tick if bands else sdk_decimal(sdk_value(info, 'tick'), 'TMF tick')
    month = sdk_text(sdk_value(info, 'delivery_month'))
    spec = InstrumentSpec(
        'TMF:' + month,
        Market.INDEX_FUTURE,
        'TWD',
        QuantityUnit.CONTRACT,
        1,
        Decimal(10),
        tick,
        'TMF',
        'shioaji-1.7.9-generated-v1',
        'shioaji-ContractV2-TMF',
        now,
        expiry=sdk_value(info, 'delivery_date'),
        margin=Decimal('35050'),
        exchange='TAIFEX',
        delivery_month=month,
        tick_rule_id=sdk_text(sdk_value(info, 'tick_rule')) if bands else 'fixed-TMF-v1',
        calendar_id=CALENDAR_ID,
        price_bands=bands,
    )
    return InstrumentBinding(spec, code), info


def generated_resources(owner, account_ref, *, include_next=False):
    account = next((item for item in owner.accounts if item.alias == account_ref), None)
    if account is None:
        raise DomainError('capability_missing', 'discovered account required')
    now, facade = owner.clock.now(), owner.shared.facade
    binding, info = _stock_binding(facade, now) if account.market is Market.STOCK else _future_binding(facade, now)
    pairs = ((binding, info),)
    if include_next and account.market is Market.INDEX_FUTURE:
        pairs = (*pairs, _future_binding(facade, now, 1))
    discount = owner.configuration.fee_discount
    fees = FeeSchedule(
        version='sinopac-estimated-v1-discount-' + str(discount), buy_rate=Decimal('0.001425') * discount, sell_rate=Decimal('0.001425') * discount
    )
    limits = ()
    for current, current_info in pairs:
        lower, upper = getattr(current_info, 'limit_down', None), getattr(current_info, 'limit_up', None)
        if lower is not None and upper is not None:
            low, high = sdk_decimal(lower, 'daily lower limit'), sdk_decimal(upper, 'daily upper limit')
            if 0 < low < high:
                limits = (*limits, ContractPriceLimits(current.spec.instrument_id, low, high, now))
    capability = CapabilitySnapshot(
        account.alias,
        owner.configuration.environment,
        frozenset((account.market,)),
        False,
        False,
        False,
        owner.query_ready,
        False,
        'authenticated-account-query-readonly',
        now,
        now + timedelta(minutes=5),
        'sinopac-generated-v1',
    )
    bindings = tuple(current for current, _ in pairs)
    return SinopacResources(Catalog(tuple(current.spec for current in bindings)), bindings, built_in_calendar(), fees, (account,), (capability,), limits)
