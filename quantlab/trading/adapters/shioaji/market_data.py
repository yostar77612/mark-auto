"""Bounded history, reference-counted subscriptions and explicit session mapping."""

from datetime import datetime, timedelta
from typing import Protocol

from quantlab.trading.domain.models import InstrumentSpec, Quote
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.ports.contracts import DataBatch, SubscriptionReceipt
from quantlab.trading.ports.interfaces import Clock
from .mapping import history_from_sdk
from .sdk import InstrumentBinding, SDKClient, TradeDateResolver, query_error, sdk_decimal, sdk_time, sdk_value


class MarketDataContext(Protocol):
    connected: bool
    client: SDKClient
    clock: Clock
    bindings: dict[str, InstrumentBinding]
    subscriptions: dict[str, tuple[str, ...]]
    subscription_counter: int
    session_resolver: TradeDateResolver | None
    quote_version: object

    def resolve(self, instrument_id: str) -> InstrumentSpec: ...


def history(context: MarketDataContext, instrument_id: str, start: datetime, end: datetime) -> DataBatch:
    aware(start)
    aware(end)
    if not context.connected or end <= start or end - start > timedelta(days=30):
        raise DomainError('validation_failed', 'connected history range must be within 30 days')
    context.resolve(instrument_id)
    try:
        raw = context.client.kbars(
            contract=context.client.contracts.get(context.bindings[instrument_id].sdk_code), start=start.date().isoformat(), end=end.date().isoformat()
        )
    except Exception as exc:
        raise query_error(exc, 'history query failed') from None
    bars = tuple(bar for bar in history_from_sdk(raw, context.bindings[instrument_id]) if start <= bar.start and bar.available_at <= end)
    return DataBatch(instrument_id, bars, 'SHIOAJI', bool(bars), '' if bars else 'no_data')


def subscribe(context: MarketDataContext, instrument_ids: tuple[str, ...]) -> SubscriptionReceipt:
    if not context.connected or type(instrument_ids) is not tuple or not 1 <= len(instrument_ids) <= 20 or len(set(instrument_ids)) != len(instrument_ids):
        raise DomainError('capability_missing', 'subscription configuration/capacity')
    if context.quote_version is None:
        raise DomainError('capability_missing', 'explicit pinned SDK quote version required')
    active = {instrument_id for group in context.subscriptions.values() for instrument_id in group}
    if len(active | set(instrument_ids)) > 20 or len(context.subscriptions) >= 20:
        raise DomainError('capability_missing', 'total subscription capacity')
    subscribed: list[object] = []
    try:
        for instrument_id in instrument_ids:
            context.resolve(instrument_id)
            if instrument_id not in active:
                contract = context.client.contracts.get(context.bindings[instrument_id].sdk_code)
                context.client.subscribe(contract, quote_type='tick', version=context.quote_version)
                subscribed.append(contract)
    except Exception:
        for contract in subscribed:
            context.client.unsubscribe(contract, quote_type='tick', version=context.quote_version)
        raise DomainError('capability_missing', 'subscription failed; partial subscriptions removed') from None
    context.subscription_counter += 1
    subscription_id = f'shioaji-sub-{context.subscription_counter}'
    context.subscriptions[subscription_id] = instrument_ids
    return SubscriptionReceipt(subscription_id, instrument_ids, True, context.clock.now())


def unsubscribe(context: MarketDataContext, subscription_id: str) -> None:
    own = context.subscriptions.get(subscription_id, ())
    other = {instrument_id for key, group in context.subscriptions.items() if key != subscription_id for instrument_id in group}
    for instrument_id in own:
        if instrument_id not in other:
            context.client.unsubscribe(context.client.contracts.get(context.bindings[instrument_id].sdk_code), quote_type='tick', version=context.quote_version)
    # Keep receipt until every unsubscription succeeded, so a failure is visible.
    context.subscriptions.pop(subscription_id, None)


def latest(context: MarketDataContext, instrument_id: str) -> Quote | None:
    if not context.connected:
        raise DomainError('capability_missing', 'disconnected quote')
    context.resolve(instrument_id)
    try:
        rows = context.client.snapshots([context.client.contracts.get(context.bindings[instrument_id].sdk_code)])
    except Exception as exc:
        raise query_error(exc, 'quote query failed') from None
    if not rows:
        return None
    if len(rows) != 1:
        raise DomainError('reconciliation_required', 'quote count')
    raw = rows[0]
    source_at = sdk_time(sdk_value(raw, 'ts'))
    if context.session_resolver is None:
        raise DomainError('calendar_missing', 'explicit trade-date/session mapping required')
    trade_date, session = context.session_resolver.session_at(instrument_id, source_at)
    return Quote(
        instrument_id,
        sdk_decimal(sdk_value(raw, 'buy_price'), 'bid'),
        sdk_decimal(sdk_value(raw, 'sell_price'), 'ask'),
        sdk_decimal(sdk_value(raw, 'close'), 'last'),
        source_at,
        context.clock.now(),
        trade_date,
        session,
        source='SHIOAJI',
    )
