"""Explicit-account Shioaji composition. Read-only and disconnected by default."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, InstrumentSpec, Market, OrderPlan, OrderStatus, Quote
from quantlab.trading.domain.validation import DomainError, identity, integer
from quantlab.trading.ports.contracts import (
    BrokerOrder,
    BrokerPosition,
    CommandReceipt,
    ConnectionState,
    DataBatch,
    OrderEvent,
    RemoteSnapshot,
    SettlementItem,
    SubmissionReceipt,
    SubscriptionReceipt,
)
from quantlab.trading.ports.interfaces import Clock
from . import market_data
from .stock_grid import validate_stock_grid
from .mapping import account_from_sdk, order_from_sdk, position_from_sdk, sdk_order_fields, settlement_from_sdk, stock_sdk_quantity
from .sdk import (
    SDK_VERSION,
    InstrumentBinding,
    SDKClient,
    SecretResolver,
    TradeDateResolver,
    query_error,
    sdk_decimal,
    sdk_price,
    sdk_text,
    sdk_value,
)


class ShioajiAdapter:
    def __init__(
        self,
        client: SDKClient,
        clock: Clock,
        environment: Environment,
        accounts: dict[str, object],
        bindings: tuple[InstrumentBinding, ...],
        capabilities: tuple[CapabilitySnapshot, ...],
        allocations: dict[str, Decimal],
        *,
        sdk_version: str,
        secret_resolver: SecretResolver | None = None,
        read_only: bool = True,
        execution_enabled: bool = False,
        share_unit: object = 'Share',
        session_resolver: TradeDateResolver | None = None,
        quote_version: object = None,
    ) -> None:
        if sdk_version != SDK_VERSION or environment not in (Environment.BROKER_SIMULATION, Environment.LIVE):
            raise DomainError('capability_missing', 'unsupported SDK/environment')
        if type(read_only) is not bool or type(execution_enabled) is not bool:
            raise DomainError('validation_failed', 'execution flags')
        self.client, self.clock, self.environment = client, clock, environment
        self.accounts, self.allocations = dict(accounts), dict(allocations)
        self.bindings = {item.spec.instrument_id: item for item in bindings}
        self.capabilities = {item.account_ref: item for item in capabilities}
        self.secret_resolver = secret_resolver
        self.read_only, self.execution_enabled, self.share_unit = read_only, execution_enabled, share_unit
        self.session_resolver = session_resolver
        self.quote_version = quote_version
        self.connected = False
        self.trades: dict[str, object] = {}
        self.orders: dict[str, BrokerOrder] = {}
        self.sequence = 0
        self.account_sequences: dict[str, int] = {account_ref: 0 for account_ref in self.accounts}
        self.event_log: list[OrderEvent] = []
        self.subscriptions: dict[str, tuple[str, ...]] = {}
        self.subscription_counter = 0
        if set(self.accounts) != set(self.allocations) or set(self.accounts) != set(self.capabilities):
            raise DomainError('validation_failed', 'explicit account configuration incomplete')
        for account_ref, capability in self.capabilities.items():
            identity(account_ref)
            if capability.environment is not environment:
                raise DomainError('capability_missing', 'capability environment mismatch')

    @staticmethod
    def _account_identity(account: object) -> tuple[str, str, str]:
        return tuple(sdk_text(sdk_value(account, name)) for name in ('account_type', 'broker_id', 'account_id'))

    def connect(self, secret_ref: str, environment: Environment) -> ConnectionState:
        if environment is not self.environment or self.secret_resolver is None:
            raise DomainError('capability_missing', 'explicit secret reference/environment required')
        identity(secret_ref)
        try:
            credentials = self.secret_resolver.broker_credentials(secret_ref)
            logged_in = self.client.login(api_key=credentials.api_key, secret_key=credentials.secret_key, subscribe_trade=True)
            actual = {self._account_identity(account) for account in logged_in}
            if any(self._account_identity(account) not in actual for account in self.accounts.values()):
                self.client.logout()
                raise DomainError('capability_missing', 'configured account not returned by login')
        except DomainError:
            raise
        except Exception:
            raise DomainError('capability_missing', 'broker connection failed; inspect sanitized diagnostics') from None
        self.connected = True
        return ConnectionState(environment, True, tuple(self.accounts), self.clock.now())

    def attach_authenticated(self) -> ConnectionState:
        """Adopt an explicitly injected session after checking its actual accounts."""
        try:
            actual = {self._account_identity(account) for account in self.client.list_accounts()}
        except Exception:
            raise DomainError('capability_missing', 'account query unavailable') from None
        if any(self._account_identity(account) not in actual for account in self.accounts.values()):
            raise DomainError('capability_missing', 'account session mismatch')
        self.connected = True
        return ConnectionState(self.environment, True, tuple(self.accounts), self.clock.now())

    def activate_certificate(self, secret_ref: str) -> bool:
        if self.secret_resolver is None or not self.connected:
            raise DomainError('capability_missing', 'certificate reference/session required')
        identity(secret_ref)
        credentials = self.secret_resolver.certificate_credentials(secret_ref)
        try:
            activated = self.client.activate_ca(ca_path=credentials.ca_path, ca_passwd=credentials.ca_password, person_id=credentials.person_id)
        except Exception:
            raise DomainError('capability_missing', 'certificate activation failed') from None
        if activated is not True:
            raise DomainError('capability_missing', 'certificate activation not confirmed')
        return True

    def disconnect(self) -> None:
        try:
            self.client.logout()
        finally:
            self.connected = False

    def _account(self, account_ref: str) -> object:
        if not self.connected or account_ref not in self.accounts:
            raise DomainError('capability_missing', 'disconnected or unknown explicit account')
        capability = self.capabilities[account_ref]
        if not capability.can_query or capability.expires_at <= self.clock.now():
            raise DomainError('capability_missing', 'query capability missing/expired')
        return self.accounts[account_ref]

    def inspect(self, account_ref: str) -> CapabilitySnapshot:
        self._account(account_ref)
        evidence = self.capabilities[account_ref]
        signed = getattr(self.accounts[account_ref], 'signed', False) is True
        enabled = not self.read_only and self.execution_enabled and signed
        if self.environment is Environment.LIVE:
            enabled = enabled and evidence.ca_ready
        return replace(evidence, can_trade=evidence.can_trade and enabled)

    def resolve(self, instrument_id: str) -> InstrumentSpec:
        if instrument_id not in self.bindings:
            raise DomainError('instrument_unresolved', 'explicit real-month binding required')
        binding = self.bindings[instrument_id]
        try:
            contract = self.client.contracts.get(binding.sdk_code)
            info = self.client.contracts.info(contract)
        except Exception:
            raise DomainError('instrument_unresolved', 'broker contract query failed') from None
        if sdk_text(sdk_value(contract, 'code')) != binding.sdk_code:
            raise DomainError('instrument_unresolved', 'broker returned different contract')
        spec = binding.spec
        if spec.market is not Market.STOCK:
            if sdk_text(sdk_value(info, 'delivery_month')) != spec.delivery_month or sdk_value(info, 'delivery_date') != spec.expiry:
                raise DomainError('instrument_unresolved', 'delivery month/expiry evidence changed')
            if sdk_decimal(sdk_value(info, 'multiplier'), 'multiplier') != spec.multiplier:
                raise DomainError('instrument_unresolved', 'contract specification changed')
            basis = sdk_text(sdk_value(info, 'tick_basis'))
            rule = sdk_value(info, 'tick_rule')
            if basis == 'fixed':
                if rule is not None or spec.price_bands or sdk_decimal(sdk_value(info, 'tick'), 'tick') != spec.tick_size:
                    raise DomainError('instrument_unresolved', 'fixed tick evidence changed')
            elif basis == 'price':
                if sdk_text(rule) != spec.tick_rule_id or not spec.price_bands:
                    raise DomainError('instrument_unresolved', 'explicit price-band profile required')
                if self.client.contracts.tick_bands(info) != spec.price_bands:
                    raise DomainError('instrument_unresolved', 'authoritative price bands changed')
            else:
                raise DomainError('instrument_unresolved', 'unsupported or unknown tick basis')
        else:
            validate_stock_grid(spec, binding.sdk_code, sdk_text(sdk_value(contract, 'exchange')), binding.stock_grid, self.clock.now())
            if (
                sdk_text(sdk_value(info, 'currency')) != 'TWD'
                or sdk_decimal(sdk_value(info, 'unit'), 'stock lot') != spec.lot_size
                or getattr(info, 'trading_suspended', True) is not False
            ):
                raise DomainError('instrument_unresolved', 'stock currency, lot or trading suspension unknown')
        return spec

    def settlements(self, account_ref: str) -> tuple[SettlementItem, ...]:
        account = self._account(account_ref)
        if self._account_identity(account)[0] != 'S':
            return ()
        try:
            raw = self.client.settlements(account=account)
        except Exception as exc:
            raise query_error(exc, 'settlement query unavailable') from None
        return tuple(settlement_from_sdk(item, account_ref) for item in raw)

    @decimal_operation
    def snapshot(self, account_ref: str) -> AccountSnapshot:
        account = self._account(account_ref)
        futures = self._account_identity(account)[0] == 'F'
        try:
            balance = self.client.margin(account=account) if futures else self.client.account_balance(account=account)
            limits = balance if futures else self.client.trading_limits(account=account)
        except Exception as exc:
            raise query_error(exc, 'account query unavailable') from None
        reserved = sum((max(Decimal('0'), item.amount) for item in self.settlements(account_ref)), Decimal('0'))
        snapshot = account_from_sdk(
            balance, limits, account_ref, self.environment, self.allocations[account_ref], reserved, self.clock.now(), self.sequence, futures=futures
        )
        if futures:
            return snapshot
        holdings = self.list(account_ref)
        equity = snapshot.settled_cash
        for position in holdings:
            quote = self.latest(position.instrument_id)
            if quote is None or not 0 <= (self.clock.now() - quote.source_at).total_seconds() <= 30:
                raise DomainError('stale_quote', 'securities equity requires fresh valuation')
            equity += position.quantity * quote.last
        return replace(snapshot, equity=equity)

    def list(self, account_ref: str) -> tuple[BrokerPosition, ...]:
        account = self._account(account_ref)
        try:
            raw_positions = self.client.list_positions(account=account, unit=self.share_unit)
        except Exception as exc:
            raise query_error(exc, 'position query unavailable') from None
        result = []
        for raw in raw_positions:
            code = sdk_text(sdk_value(raw, 'code'))
            matches = [binding for binding in self.bindings.values() if binding.sdk_code == code]
            if len(matches) != 1:
                raise DomainError('reconciliation_required', 'external position has unresolved instrument')
            binding = matches[0]
            sellable = None
            if binding.spec.market is Market.STOCK:
                # Yesterday inventory is a conservative bound, not proof that
                # reserved, pledged or already pending sells are available.
                sellable = 0
            result.append(position_from_sdk(raw, account_ref, binding, sellable))
        return tuple(result)

    def _execution(self, plan: OrderPlan) -> object:
        account = self._account(plan.account_ref)
        capability = self.inspect(plan.account_ref)
        if plan.environment is not self.environment or not capability.can_trade or plan.deadline <= self.clock.now():
            raise DomainError('capability_missing', 'execution disabled, expired, or wrong environment')
        spec = self.resolve(plan.instrument_id)
        if spec.market not in capability.markets:
            raise DomainError('capability_missing', 'market capability missing')
        expected_type = 'S' if spec.market is Market.STOCK else 'F'
        if self._account_identity(account)[0] != expected_type:
            raise DomainError('capability_missing', 'market and explicit broker account type mismatch')
        return account

    def submit(self, plan: OrderPlan, local_order_id: str) -> SubmissionReceipt:
        identity(local_order_id)
        account = self._execution(plan)
        if local_order_id in self.orders:
            raise DomainError('state_conflict', 'adapter must not resubmit an existing local command')
        binding = self.bindings[plan.instrument_id]
        fields = sdk_order_fields(plan, binding, account, odd_lot=self.capabilities[plan.account_ref].odd_lot)
        order = self.client.Order(**fields)
        pending = BrokerOrder(local_order_id, plan, 0, Decimal('0'), OrderStatus.UNKNOWN, f'pending-{local_order_id}', self.clock.now())
        self.orders[local_order_id] = pending
        try:
            trade = self.client.place_order(self.client.contracts.get(binding.sdk_code), order)
            normalized = order_from_sdk(trade, local_order_id, plan, binding, self.clock.now())
            self.trades[local_order_id], self.orders[local_order_id] = trade, normalized
            self._record(normalized)
        except Exception:
            return SubmissionReceipt(local_order_id, None, OrderStatus.UNKNOWN, self.clock.now(), False, 'outcome_unknown')
        return SubmissionReceipt(local_order_id, normalized.broker_order_ref, normalized.status, self.clock.now())

    @decimal_operation
    def _record(self, order: BrokerOrder, previous: BrokerOrder | None = None) -> None:
        old_quantity = previous.cumulative_quantity if previous else 0
        old_average = previous.average_price if previous else Decimal('0')
        delta = order.cumulative_quantity - old_quantity
        price = (order.average_price * order.cumulative_quantity - old_average * old_quantity) / delta if delta else Decimal('0')
        self.sequence += 1
        account_ref = order.plan.account_ref
        self.account_sequences[account_ref] += 1
        sequence = self.account_sequences[account_ref]
        event = OrderEvent(
            f'shioaji-{account_ref}-{order.broker_order_ref}-{sequence}',
            order.local_order_id,
            order.broker_order_ref,
            order.status,
            order.cumulative_quantity,
            delta,
            price,
            self.clock.now(),
            sequence,
            'SHIOAJI_QUERY',
        )
        self.event_log.append(event)

    @decimal_operation
    def _change(self, local_order_id: str, price: Decimal | None, quantity: int | None) -> CommandReceipt:
        if local_order_id not in self.trades:
            raise DomainError('reconciliation_required', 'unknown trade cannot cancel/amend blindly')
        previous = self.orders[local_order_id]
        self._execution(previous.plan)
        if previous.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            raise DomainError('state_conflict', 'order not active')
        try:
            if price is None:
                self.client.cancel_order(self.trades[local_order_id])
                status = OrderStatus.CANCEL_PENDING
            else:
                spec = self.bindings[previous.plan.instrument_id].spec
                spec.validate_price(price)
                amount = previous.plan.quantity if quantity is None else quantity
                if type(amount) is not int or not previous.cumulative_quantity < amount <= previous.plan.quantity:
                    raise DomainError('validation_failed', 'only reducing amendment supported')
                changed_plan = replace(previous.plan, quantity=amount, limit_price=price)
                sdk_quantity, _ = stock_sdk_quantity(
                    changed_plan, self.bindings[spec.instrument_id], odd_lot=self.capabilities[changed_plan.account_ref].odd_lot
                )
                self.client.update_order(self.trades[local_order_id], price=sdk_price(price), qty=sdk_quantity)
                status = previous.status
        except DomainError:
            raise
        except Exception:
            status = OrderStatus.UNKNOWN
        # Neither SDK command return implies a terminal exchange result.
        self.orders[local_order_id] = replace(previous, status=status, updated_at=self.clock.now())
        return CommandReceipt(
            f'change-{local_order_id}-{self.sequence}',
            True,
            status,
            local_order_id,
            self.clock.now(),
            'outcome_unknown' if status is OrderStatus.UNKNOWN else '',
        )

    def cancel(self, local_order_id: str) -> CommandReceipt:
        return self._change(local_order_id, None, None)

    def amend(self, local_order_id: str, price: Decimal, quantity: int | None = None) -> CommandReceipt:
        return self._change(local_order_id, price, quantity)

    def refresh(self, account_ref: str) -> RemoteSnapshot:
        account = self._account(account_ref)
        try:
            self.client.update_status(account=account)
            trades = self.client.list_trades()
        except Exception as exc:
            raise query_error(exc, 'order query unavailable; no retry submission') from None
        expected = self._account_identity(account)
        for trade in trades:
            raw_order = sdk_value(trade, 'order')
            if self._account_identity(sdk_value(raw_order, 'account')) != expected:
                continue
            raw_id = str(sdk_value(raw_order, 'id'))
            matches = [order for order in self.orders.values() if order.broker_order_ref == raw_id]
            if len(matches) != 1:
                raise DomainError('reconciliation_required', 'unmapped external/unknown broker order requires explicit adoption')
            previous = matches[0]
            normalized = order_from_sdk(trade, previous.local_order_id, previous.plan, self.bindings[previous.plan.instrument_id], self.clock.now())
            if normalized.cumulative_quantity < previous.cumulative_quantity:
                raise DomainError('reconciliation_required', 'broker cumulative fill regressed')
            if (normalized.status, normalized.cumulative_quantity) != (previous.status, previous.cumulative_quantity):
                self._record(normalized, previous)
            self.trades[previous.local_order_id], self.orders[previous.local_order_id] = trade, normalized
        orders = tuple(order for order in self.orders.values() if order.plan.account_ref == account_ref)
        return RemoteSnapshot(self.snapshot(account_ref), orders, self.list(account_ref), self.account_sequences[account_ref], self.clock.now())

    def events(self, account_ref: str, after_sequence: int = 0) -> tuple[OrderEvent, ...]:
        integer(after_sequence, 'event cursor')
        self.refresh(account_ref)
        own = {order.local_order_id for order in self.orders.values() if order.plan.account_ref == account_ref}
        return tuple(event for event in self.event_log if event.sequence > after_sequence and event.local_order_id in own)

    def history(self, instrument_id: str, start: datetime, end: datetime) -> DataBatch:
        return market_data.history(self, instrument_id, start, end)

    def subscribe(self, instrument_ids: tuple[str, ...]) -> SubscriptionReceipt:
        return market_data.subscribe(self, instrument_ids)

    def unsubscribe(self, subscription_id: str) -> None:
        market_data.unsubscribe(self, subscription_id)

    def latest(self, instrument_id: str) -> Quote | None:
        return market_data.latest(self, instrument_id)
