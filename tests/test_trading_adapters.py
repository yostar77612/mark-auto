"""Behavioral exchange faults and SDK boundary contracts; no network or credentials."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.simulated import FaultPlan, SimulatedBroker
from quantlab.trading.adapters.shioaji import InstrumentBinding, ShioajiAdapter, SDK_VERSION
from quantlab.trading.adapters.shioaji.mapping import account_from_sdk, history_from_sdk, sdk_order_fields
from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, InstrumentSpec, Market, OrderPlan, OrderStatus, QuantityUnit, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerPosition, OrderEvent

D = Decimal
NOW = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


def instrument(market: Market = Market.STOCK) -> InstrumentSpec:
    stock = market is Market.STOCK
    return InstrumentSpec(
        'TWSE:0050' if stock else 'TAIFEX:TMF:202611' if market is Market.INDEX_FUTURE else 'TAIFEX:FFF:202611',
        market,
        'TWD',
        QuantityUnit.SHARE if stock else QuantityUnit.CONTRACT,
        1000 if stock else 1,
        D('1') if stock else D('10') if market is Market.INDEX_FUTURE else D('2000'),
        D('0.01') if stock else D('1'),
        '0050' if stock else 'TAIEX' if market is Market.INDEX_FUTURE else '2330',
        'test-v1',
        'EXPLICIT_TEST_ONLY',
        NOW - timedelta(days=1),
        None if stock else date(2026, 11, 18),
        None if stock else D('20000'),
        'TWSE' if stock else 'TAIFEX',
        None if stock else '202611',
    )


def account(environment: Environment = Environment.LOCAL) -> AccountSnapshot:
    return AccountSnapshot('test-stock', environment, D('100000'), D('100000'), D('100000'), D('100000'), D('0'), D('0'), NOW, 0)


def capability(environment: Environment = Environment.LOCAL) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        'test-stock', environment, frozenset(Market), False, False, False, True, True, 'EXPLICIT_TEST_ONLY', NOW, NOW + timedelta(days=10), 'v1', False
    )


def plan(
    spec: InstrumentSpec,
    *,
    key: str = 'plan-1',
    quantity: int | None = None,
    side: Side = Side.BUY,
    reduce_only: bool = False,
    environment: Environment = Environment.LOCAL,
) -> OrderPlan:
    return OrderPlan(
        key,
        'test-stock',
        environment,
        spec.instrument_id,
        'swing',
        1,
        side,
        quantity if quantity is not None else 1000 if spec.market is Market.STOCK else 1,
        spec.unit,
        D('20') if spec.market is Market.STOCK else D('100'),
        D('19') if spec.market is Market.STOCK else D('90'),
        reduce_only,
        NOW,
        NOW + timedelta(hours=2),
        0,
    )


class SimulatorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock, self.spec = MutableClock(), instrument()
        self.broker = SimulatedBroker(self.clock, account(), (self.spec,), capability())

    def test_all_three_markets_execute_and_preserve_units(self) -> None:
        for market in Market:
            with self.subTest(market=market):
                spec = instrument(market)
                broker = SimulatedBroker(self.clock, account(), (spec,), capability())
                receipt = broker.submit(plan(spec), 'local-1')
                self.assertEqual(receipt.status, OrderStatus.ACCEPTED)
                broker.fill('local-1', plan(spec).quantity, plan(spec).limit_price, fee=D('10'))
                position = broker.list('test-stock')[0]
                self.assertEqual(position.unit, spec.unit)
                self.assertEqual(position.quantity, plan(spec).quantity)
                self.assertEqual(broker.refresh('test-stock').orders[0].status, OrderStatus.FILLED)

    def test_unknown_after_remote_accept_restarts_without_resubmitting(self) -> None:
        self.broker.queue_fault(FaultPlan(unknown_after_accept=True))
        receipt = self.broker.submit(plan(self.spec), 'unknown-1')
        self.assertFalse(receipt.outcome_known)
        self.assertEqual(receipt.status, OrderStatus.UNKNOWN)
        with self.assertRaises(DomainError):
            self.broker.refresh('test-stock')
        restarted = SimulatedBroker(self.clock, account(), (self.spec,), capability(), self.broker.remote_state)
        self.assertEqual(len(restarted.refresh('test-stock').orders), 1)
        self.assertEqual(restarted.submission_count, 0)
        self.assertEqual(restarted.refresh('test-stock').orders[0].status, OrderStatus.ACCEPTED)

    def test_partial_cancel_keeps_filled_inventory_and_unfilled_cancel(self) -> None:
        self.broker.queue_fault(FaultPlan(partial_quantity=1000))
        self.broker.submit(plan(self.spec, quantity=2000), 'partial')
        receipt = self.broker.cancel('partial')
        self.assertEqual(receipt.status, OrderStatus.CANCELED)
        self.assertEqual(self.broker.list('test-stock')[0].quantity, 1000)
        self.assertEqual(self.broker.refresh('test-stock').orders[0].cumulative_quantity, 1000)

    def test_cancel_fill_race_finishes_fill_without_clearing_it(self) -> None:
        self.broker.queue_fault(FaultPlan(partial_quantity=1000, cancel_fill_race=True))
        self.broker.submit(plan(self.spec, quantity=2000), 'race')
        self.assertEqual(self.broker.cancel('race').status, OrderStatus.FILLED)
        self.assertEqual(self.broker.list('test-stock')[0].quantity, 2000)

    def test_duplicate_reorder_and_lost_event_are_injectable(self) -> None:
        self.broker.queue_fault(FaultPlan(duplicate_event=True))
        self.broker.submit(plan(self.spec), 'duplicate')
        self.broker.fill('duplicate', 1000, D('20'))
        self.broker.reorder_events((2, 1, 1))
        delivered = self.broker.events('test-stock')
        self.assertEqual([item.sequence for item in delivered], [2, 1, 1])
        self.assertEqual(delivered[1].event_id, delivered[2].event_id)
        self.broker.queue_fault(FaultPlan(drop_event=True))
        self.broker.submit(plan(self.spec, key='missing'), 'missing')
        self.assertEqual(len(self.broker.events('test-stock')), 3)
        self.assertEqual(self.broker.refresh('test-stock').sequence, 3)
        self.assertEqual(len(self.broker.refresh('test-stock').orders), 2)

    def test_reject_disconnect_and_remote_duplicate_are_not_successes(self) -> None:
        self.broker.queue_fault(FaultPlan(reject=True))
        self.assertEqual(self.broker.submit(plan(self.spec), 'rejected').status, OrderStatus.REJECTED)
        with self.assertRaises(DomainError):
            self.broker.submit(plan(self.spec), 'rejected')
        self.broker.queue_fault(FaultPlan(disconnect_before_submit=True))
        with self.assertRaises(DomainError):
            self.broker.submit(plan(self.spec), 'not-confirmed')
        self.assertNotIn('not-confirmed', self.broker.remote_state.orders)

    def test_no_day_trade_same_day_sale_refused_then_explicit_trading_day_allows(self) -> None:
        self.broker.submit(plan(self.spec), 'entry')
        self.broker.fill('entry', 1000, D('20'))
        exit_plan = plan(self.spec, key='exit', side=Side.SELL, reduce_only=True)
        self.broker.submit(exit_plan, 'exit')
        with self.assertRaises(DomainError):
            self.broker.fill('exit', 1000, D('20'))
        self.assertEqual(self.broker.list('test-stock')[0].sellable_quantity, 0)
        self.broker.advance_trade_date(date(2026, 10, 26))
        self.broker.fill('exit', 1000, D('20'))
        self.assertEqual(self.broker.list('test-stock'), ())

    def test_unsettled_receivables_do_not_become_cash_until_explicit_settlement(self) -> None:
        self.broker.submit(plan(self.spec), 'entry')
        # This case isolates settlement timing using explicit injected economics.
        self.broker.fill('entry', 1000, D('20'), fee=D('0'))
        self.broker.advance_trade_date(date(2026, 10, 26))
        self.broker.submit(plan(self.spec, key='exit', side=Side.SELL, reduce_only=True), 'exit')
        self.broker.fill('exit', 1000, D('21'), fee=D('10'))
        before = self.broker.snapshot('test-stock')
        self.assertEqual(before.settled_cash, D('79990'))
        self.assertEqual(before.unsettled_receivables, D('21000'))
        self.broker.schedule_receivable(D('21000'), date(2026, 10, 28))
        self.broker.settle(date(2026, 10, 27))
        self.assertEqual(self.broker.snapshot('test-stock').settled_cash, before.settled_cash)
        self.broker.settle(date(2026, 10, 28))
        self.assertEqual(self.broker.snapshot('test-stock').settled_cash, D('100990'))

    def test_insufficient_exchange_cash_is_atomic_and_external_positions_remain_separate(self) -> None:
        self.broker.submit(plan(self.spec, quantity=10000), 'too-large')
        with self.assertRaises(DomainError):
            self.broker.fill('too-large', 10000, D('20'))
        self.assertEqual(self.broker.list('test-stock'), ())
        self.assertEqual(self.broker.refresh('test-stock').orders[0].cumulative_quantity, 0)
        external = BrokerPosition('test-stock', self.spec.instrument_id, 1000, 1000, QuantityUnit.SHARE, D('15'), 'EXTERNAL')
        self.broker.external_position(external)
        self.assertEqual(self.broker.list('test-stock'), (external,))

    def test_amend_reduces_quantity_price_only_and_preserves_fills(self) -> None:
        self.broker.queue_fault(FaultPlan(partial_quantity=1000))
        self.broker.submit(plan(self.spec, quantity=3000), 'amend')
        self.broker.amend('amend', D('20.01'), 2000)
        remote = self.broker.refresh('test-stock').orders[0]
        self.assertEqual((remote.plan.quantity, remote.cumulative_quantity), (2000, 1000))
        with self.assertRaises(DomainError):
            self.broker.amend('amend', D('20'), 4000)

    def test_public_event_rejects_floats_naive_time_and_invalid_units(self) -> None:
        valid = dict(
            event_id='e',
            local_order_id='l',
            broker_order_ref='b',
            status=OrderStatus.ACCEPTED,
            cumulative_quantity=0,
            last_fill_quantity=0,
            last_fill_price=D('0'),
            occurred_at=NOW,
            sequence=1,
            source='SIM',
        )
        for changed in ({'last_fill_price': 0.0}, {'occurred_at': NOW.replace(tzinfo=None)}, {'sequence': True}):
            with self.subTest(changed=changed), self.assertRaises(DomainError):
                OrderEvent(**(valid | changed))

    def test_fault_partial_and_cancel_race_use_the_same_authoritative_costs(self) -> None:
        from quantlab.trading.domain.costs import FeeSchedule

        self.broker.queue_fault(FaultPlan(partial_quantity=1000, cancel_fill_race=True))
        self.broker.submit(plan(self.spec, quantity=2000), 'cost-race')
        one_fill_fee = FeeSchedule().transaction(self.spec, Side.BUY, D('20'), 1000)
        self.assertEqual(self.broker.snapshot('test-stock').settled_cash, D('80000') - one_fill_fee)
        self.broker.cancel('cost-race')
        full_order_fee = FeeSchedule().transaction(self.spec, Side.BUY, D('20'), 2000)
        self.assertEqual(self.broker.snapshot('test-stock').settled_cash, D('60000') - full_order_fee)
        self.assertEqual(self.broker.remote_state.fees['cost-race'], full_order_fee)

    def test_same_day_add_on_does_not_inherit_sellability_from_older_shares(self) -> None:
        from dataclasses import replace

        self.broker.submit(plan(self.spec), 'first')
        self.broker.fill('first', 1000, D('20'))
        self.clock.value += timedelta(days=3)
        self.broker.advance_trade_date(date(2026, 10, 26))
        addition = replace(plan(self.spec, key='addition'), decision_at=self.clock.now(), deadline=self.clock.now() + timedelta(hours=1))
        self.broker.submit(addition, 'addition')
        self.broker.fill('addition', 1000, D('20'))
        self.broker.advance_trade_date(date(2026, 10, 26))
        self.assertEqual(self.broker.list('test-stock')[0].sellable_quantity, 1000)
        self.broker.advance_trade_date(date(2026, 10, 27))
        self.assertEqual(self.broker.list('test-stock')[0].sellable_quantity, 2000)

    def test_exchange_fill_cannot_exceed_limit_price(self) -> None:
        self.broker.submit(plan(self.spec), 'price-guard')
        with self.assertRaises(DomainError):
            self.broker.fill('price-guard', 1000, D('20.01'))
        self.assertEqual(self.broker.list('test-stock'), ())

    def test_broker_average_and_cash_ignore_ambient_decimal_context(self) -> None:
        from dataclasses import replace
        from decimal import localcontext, ROUND_DOWN

        order = replace(plan(self.spec, quantity=2000), limit_price=D('20.01'))
        self.broker.submit(order, 'precision')
        with localcontext() as context:
            context.prec, context.rounding = 2, ROUND_DOWN
            self.broker.fill('precision', 1000, D('20'))
            self.broker.fill('precision', 1000, D('20.01'))
        self.assertEqual(self.broker.refresh('test-stock').orders[0].average_price, D('20.005'))
        self.assertEqual(self.broker.snapshot('test-stock').settled_cash, D('59932'))


class SDKDouble:
    """An explicit SDK-shaped test double with failure controls, never a session."""

    def __init__(self) -> None:
        self.account = SimpleNamespace(account_type='S', broker_id='TEST', account_id='0000', signed=True)
        self.contract = SimpleNamespace(code='0050', security_type='STK')
        self.contracts = SimpleNamespace(get=lambda code: self.contract, info=lambda contract: SimpleNamespace(unit=1000, trading_suspended=False))
        self.quote = SimpleNamespace(subscribe=lambda *args, **kwargs: None, unsubscribe=lambda *args, **kwargs: None)
        self.placed: list[object] = []
        self.order_calls: list[dict[str, object]] = []
        self.raise_after_accept = False
        self.fail_queries = False
        self.trade_status = 'Submitted'

    def list_accounts(self) -> list[object]:
        return [self.account]

    def subscribe(self, contract: object, *, quote_type: str, version: str) -> None:
        return None

    def unsubscribe(self, contract: object, *, quote_type: str, version: str) -> None:
        return None

    def Order(self, **kwargs: object) -> object:
        self.order_calls.append(kwargs)
        return SimpleNamespace(id='sdk-1', **kwargs)

    def place_order(self, contract: object, order: object) -> object:
        trade = SimpleNamespace(contract=contract, order=order, status=SimpleNamespace(status=self.trade_status, deal_quantity=0, deals=[]))
        self.placed.append(trade)
        if self.raise_after_accept:
            raise TimeoutError('sensitive vendor diagnostic must never escape')
        return trade

    def update_status(self, *, account: object) -> None:
        if self.fail_queries:
            raise ConnectionError('sensitive vendor diagnostic must never escape')

    def list_trades(self) -> list[object]:
        return self.placed

    def account_balance(self, *, account: object) -> object:
        return SimpleNamespace(acc_balance=100000)

    def trading_limits(self, *, account: object) -> object:
        return SimpleNamespace(trading_available=100000)

    def settlements(self, *, account: object) -> list[object]:
        return []

    def list_positions(self, *, account: object, unit: object) -> list[object]:
        if unit != 'Share':
            raise AssertionError('must explicitly request shares')
        return []


class ShioajiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.clock, self.spec = SDKDouble(), MutableClock(), instrument()
        self.environment = Environment.BROKER_SIMULATION

    def adapter(self, *, enabled: bool = False) -> ShioajiAdapter:
        adapter = ShioajiAdapter(
            self.client,
            self.clock,
            self.environment,
            {'test-stock': self.client.account},
            (InstrumentBinding(self.spec, '0050'),),
            (capability(self.environment),),
            {'test-stock': D('100000')},
            sdk_version=SDK_VERSION,
            read_only=not enabled,
            execution_enabled=enabled,
        )
        adapter.attach_authenticated()
        adapter.quote_version = 'synthetic-v1-enum'
        return adapter

    def test_read_only_default_refuses_every_trading_command(self) -> None:
        adapter = self.adapter()
        self.assertFalse(adapter.inspect('test-stock').can_trade)
        with self.assertRaises(DomainError):
            adapter.submit(plan(self.spec, environment=self.environment), 'sdk-local')
        self.assertEqual(self.client.placed, [])
        self.assertEqual(self.client.order_calls, [])
        self.assertEqual(adapter.snapshot('test-stock').settled_cash, D('100000'))

    def test_stock_shares_become_sdk_lots_and_explicit_cash_account(self) -> None:
        adapter = self.adapter(enabled=True)
        receipt = adapter.submit(plan(self.spec, quantity=2000, environment=self.environment), 'sdk-local')
        self.assertEqual(receipt.status, OrderStatus.ACCEPTED)
        fields = self.client.order_calls[0]
        self.assertEqual((fields['quantity'], fields['order_lot'], fields['order_cond'], fields['daytrade_short']), (2, 'Common', 'Cash', False))
        self.assertIs(fields['account'], self.client.account)
        self.assertEqual(adapter.refresh('test-stock').orders[0].plan.quantity, 2000)

    def test_future_new_cover_mapping_never_inferrs_daytrade(self) -> None:
        spec = instrument(Market.INDEX_FUTURE)
        binding = InstrumentBinding(spec, 'TMFK6')
        for reduce, expected in ((False, 'New'), (True, 'Cover')):
            fields = sdk_order_fields(plan(spec, reduce_only=reduce, environment=self.environment), binding, self.client.account, odd_lot=False)
            self.assertEqual(fields['octype'], expected)
            self.assertNotIn('daytrade_short', fields)

    def test_unknown_accepted_timeout_remains_quarantined_no_retry(self) -> None:
        adapter = self.adapter(enabled=True)
        self.client.raise_after_accept = True
        receipt = adapter.submit(plan(self.spec, environment=self.environment), 'unknown')
        self.assertEqual(receipt.status, OrderStatus.UNKNOWN)
        with self.assertRaises(DomainError):
            adapter.submit(plan(self.spec, environment=self.environment), 'unknown')
        with self.assertRaises(DomainError):
            adapter.refresh('test-stock')
        self.assertEqual(len(self.client.placed), 1)

    def test_unrecognized_status_and_external_trade_do_not_silently_clear(self) -> None:
        adapter = self.adapter(enabled=True)
        adapter.submit(plan(self.spec, environment=self.environment), 'known')
        self.client.placed[0].status.status = 'VendorNewUnrecognizedStatus'
        with self.assertRaises(DomainError):
            adapter.refresh('test-stock')
        self.client.placed[0].order.id = 'external-phone-order'
        with self.assertRaises(DomainError):
            adapter.refresh('test-stock')

    def test_sdk_version_account_ca_and_actual_month_are_independent_gates(self) -> None:
        with self.assertRaises(DomainError):
            ShioajiAdapter(self.client, self.clock, self.environment, {}, (), (), {}, sdk_version='1.7.8')
        adapter = self.adapter(enabled=True)
        adapter.environment = Environment.LIVE
        adapter.capabilities['test-stock'] = capability(Environment.LIVE)
        self.assertFalse(adapter.inspect('test-stock').can_trade)
        with self.assertRaises(DomainError):
            InstrumentBinding(instrument(Market.INDEX_FUTURE), 'TMFR1')
        with self.assertRaises(DomainError):
            adapter.snapshot('omitted-or-other-account')

    def test_sdk_queries_fail_closed_and_sanitized(self) -> None:
        adapter = self.adapter()
        self.client.fail_queries = True
        with self.assertRaises(DomainError) as caught:
            adapter.refresh('test-stock')
        self.assertNotIn('sensitive', str(caught.exception))

    def test_account_fields_and_history_availability_match_documented_sdk(self) -> None:
        raw = SimpleNamespace(acc_balance=50000)
        limits = SimpleNamespace(trading_available=40000)
        result = account_from_sdk(raw, limits, 'test-stock', self.environment, D('50000'), D('1000'), NOW, 1, futures=False)
        self.assertEqual((result.settled_cash, result.broker_limit, result.settlement_reserved), (D('50000'), D('40000'), D('1000')))
        raw_bars = SimpleNamespace(ts=[int(NOW.timestamp()) * 1_000_000_000], Open=[20.0], High=[21.0], Low=[19.0], Close=[20.5], Volume=[100])
        bar = history_from_sdk(raw_bars, InstrumentBinding(self.spec, '0050'))[0]
        self.assertEqual((bar.available_at, bar.start), (NOW, NOW - timedelta(minutes=1)))
        self.assertIsInstance(bar.close, Decimal)
        raw_bars.Close.append(22.0)
        with self.assertRaises(DomainError):
            history_from_sdk(raw_bars, InstrumentBinding(self.spec, '0050'))

    def test_normalized_fill_events_have_actual_delta_economics_and_do_not_duplicate(self) -> None:
        adapter = self.adapter(enabled=True)
        adapter.submit(plan(self.spec, quantity=2000, environment=self.environment), 'fill-test')
        trade = self.client.placed[0]
        trade.status.status = 'PartFilled'
        trade.status.deal_quantity = 1
        trade.status.deals = [SimpleNamespace(seq='fill-1', quantity=1, price=19.99)]
        adapter.refresh('test-stock')
        event = adapter.events('test-stock')[-1]
        self.assertEqual((event.cumulative_quantity, event.last_fill_quantity, event.last_fill_price), (1000, 1000, D('19.99')))
        count = len(adapter.event_log)
        adapter.refresh('test-stock')
        self.assertEqual(len(adapter.event_log), count)

    def test_windows_secret_refs_are_exact_scoped_and_never_discovered(self) -> None:
        from quantlab.trading.adapters.shioaji.secrets import WindowsSecretResolver

        class Backend:
            payload = b'{"api_key":"synthetic-test-key","secret_key":"synthetic-test-value"}'

            def __init__(self) -> None:
                self.targets: list[str] = []

            def read(self, target: str) -> bytes:
                self.targets.append(target)
                return self.payload

        backend = Backend()
        resolver = WindowsSecretResolver(backend)
        credential = resolver.broker_credentials('MarkAuto/v2/broker/isolated-test')
        self.assertEqual(backend.targets, ['MarkAuto/v2/broker/isolated-test'])
        self.assertNotIn('synthetic-test', repr(credential))
        for reference in ('unrelated-key', 'MarkAuto/v2/broker/../../other', 'MarkAuto/v2/certificate/isolated-test'):
            with self.subTest(reference=reference), self.assertRaises(DomainError):
                resolver.broker_credentials(reference)
        self.assertEqual(len(backend.targets), 1)
        backend.payload = '{"api_key":"synthetic-test-key","secret_key":"synthetic-test-value"}'.encode('utf-16-le')
        self.assertEqual(resolver.broker_credentials('MarkAuto/v2/broker/isolated-test').api_key, 'synthetic-test-key')
        backend.payload = b'{"api_key":"x","api_key":"duplicate","secret_key":"test"}'
        with self.assertRaises(DomainError):
            resolver.broker_credentials('MarkAuto/v2/broker/isolated-test')

    def test_futures_cash_and_margin_are_not_subtracted_twice(self) -> None:
        margin = SimpleNamespace(today_balance=100000, equity=101000, initial_margin=20000, available_margin=80000)
        snapshot = account_from_sdk(margin, margin, 'test-stock', self.environment, D('100000'), D('0'), NOW, 1, futures=True)
        self.assertEqual((snapshot.settled_cash, snapshot.margin_used, snapshot.broker_limit), (D('100000'), D('20000'), D('100000')))

    def test_quote_without_verified_session_mapping_never_guesses_machine_date(self) -> None:
        adapter = self.adapter()
        self.client.snapshots = lambda contracts: [SimpleNamespace(ts=int(NOW.timestamp()) * 1_000_000_000, buy_price=20, sell_price=20.01, close=20)]
        with self.assertRaises(DomainError) as caught:
            adapter.latest(self.spec.instrument_id)
        self.assertEqual(caught.exception.code, 'calendar_missing')

    def test_broker_cumulative_fill_without_unique_complete_deals_is_quarantined(self) -> None:
        adapter = self.adapter(enabled=True)
        adapter.submit(plan(self.spec, quantity=2000, environment=self.environment), 'economics')
        trade = self.client.placed[0]
        trade.status.status, trade.status.deal_quantity = 'PartFilled', 1
        with self.assertRaises(DomainError):
            adapter.refresh('test-stock')
        trade.status.deals = [SimpleNamespace(seq='duplicated', quantity=1, price=20), SimpleNamespace(seq='duplicated', quantity=1, price=20)]
        trade.status.deal_quantity = 2
        trade.status.status = 'Filled'
        with self.assertRaises(DomainError):
            adapter.refresh('test-stock')

    def test_query_rate_limit_auth_and_transport_are_distinct_sanitized_failures(self) -> None:
        from quantlab.trading.adapters.shioaji.sdk import query_error

        class MarketDataQueryUsageLimitError(Exception):
            pass

        class TokenError(Exception):
            pass

        for error, expected in (
            (MarketDataQueryUsageLimitError('private'), 'rate_limited'),
            (TokenError('private'), 'capability_missing'),
            (ConnectionError('private'), 'reconciliation_required'),
        ):
            result = query_error(error, 'query unavailable')
            self.assertEqual(result.code, expected)
            self.assertNotIn('private', str(result))

    def test_subscription_ownership_is_refcounted_bounded_and_ids_never_reused(self) -> None:
        from unittest.mock import Mock

        adapter = self.adapter()
        self.client.subscribe, self.client.unsubscribe = Mock(), Mock()
        first = adapter.subscribe((self.spec.instrument_id,))
        second = adapter.subscribe((self.spec.instrument_id,))
        self.assertEqual(self.client.subscribe.call_count, 1)
        adapter.unsubscribe(first.subscription_id)
        self.client.unsubscribe.assert_not_called()
        third = adapter.subscribe((self.spec.instrument_id,))
        self.assertEqual(len({first.subscription_id, second.subscription_id, third.subscription_id}), 3)
        adapter.unsubscribe(second.subscription_id)
        self.client.unsubscribe.assert_not_called()
        adapter.unsubscribe(third.subscription_id)
        self.assertEqual(self.client.unsubscribe.call_count, 1)
        for _ in range(20):
            adapter.subscribe((self.spec.instrument_id,))
        with self.assertRaises(DomainError):
            adapter.subscribe((self.spec.instrument_id,))


if __name__ == '__main__':
    unittest.main()
