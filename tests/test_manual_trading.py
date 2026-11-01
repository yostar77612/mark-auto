"""Real manual core through a strict, offline native SDK double; no client login."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.gateway import ShioajiAdapter
from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.shioaji.shared_session import SharedSDKSession
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import cursor
from quantlab.trading.application.manual_book import book_for, manual_capacity
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualMutationForm, ManualOrderForm, ManualPurpose, ManualScope
from quantlab.trading.application.manual_trading import ManualTradingService
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, Market, OrderStatus, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualPriceLimit
from quantlab.trading.runtime.build import synthetic_calendar
from test_live_order_guard import GuardJournal
from test_trading_adapters import MutableClock, instrument
from test_trading_sdk_facade import StrictSDK, Unit, contract

D = Decimal


class ManualSDK(StrictSDK):
    def __init__(self, spec):
        super().__init__()
        self.account = SimpleNamespace(account_type='F', broker_id='FAKE', account_id='manual-offline', signed=True)
        self._accounts = [self.account]
        self.item = contract('TMFL6', futures=True)
        self.info = SimpleNamespace(
            **vars(self.item),
            delivery_month=spec.delivery_month,
            delivery_date=spec.expiry,
            multiplier=float(spec.multiplier),
            tick=float(spec.tick_size),
            tick_basis='fixed',
            tick_rule=None,
        )
        self._contracts = SimpleNamespace(get=lambda code: self.item if code == 'TMFL6' else None, info=lambda item: self.info)
        self.trades = []
        self.cache_state = 'Healthy'
        self.cache_reasons = []
        self.place_mode = 'Submitted'
        self.cancel_mode = 'Cancelled'
        self.fill_on_cancel = False
        self.amend_ack = True
        self.financial_queries = 0

    def place_order(self, contract, order, timeout=30000, cb=None):
        self._record('place_order', contract, order, timeout=timeout)
        order.id = 'sdk-' + str(len(self.trades) + 1)
        trade = SimpleNamespace(
            contract=contract,
            order=order,
            status=SimpleNamespace(status=self.place_mode if self.place_mode != 'TIMEOUT' else 'Submitted', deal_quantity=0, deals=[], modified_price=None),
        )
        self.trades.append(trade)
        if self.place_mode == 'TIMEOUT':
            raise TimeoutError('native private diagnostics must not escape')
        return trade

    def cancel_order(self, trade, timeout=30000, cb=None):
        self._record('cancel_order', trade, timeout=timeout)
        if self.fill_on_cancel:
            self.fill(trade, trade.order.quantity, D(str(trade.order.price)))
        elif self.cancel_mode == 'TIMEOUT':
            raise TimeoutError('native private cancel diagnostics')
        else:
            trade.status.status = self.cancel_mode
        return trade

    def update_order(self, trade, *, price, timeout=30000, cb=None):
        # No qty parameter: price-only calls must not send any quantity field.
        self._record('update_order', trade, price=price, timeout=timeout)
        if self.amend_ack:
            trade.status.modified_price = price
        return trade

    def trade_cache_health(self, account):
        self._record('trade_cache_health', account)
        return SimpleNamespace(state=self.cache_state, reasons=self.cache_reasons)

    def list_trades(self):
        self._record('list_trades')
        return list(self.trades)

    def list_positions(self, account=None, unit=None, timeout=30000, cb=None):
        self._record('list_positions', account=account, unit=unit, timeout=timeout)
        signed = sum(trade.status.deal_quantity * (1 if trade.order.action == 'Buy' else -1) for trade in self.trades)
        return (
            []
            if not signed
            else [SimpleNamespace(code='TMFL6', direction='Buy' if signed > 0 else 'Sell', quantity=abs(signed), price=self.trades[0].order.price)]
        )

    def margin(self, account=None, timeout=30000, cb=None):
        self.financial_queries += 1
        raise AssertionError('manual risk must not invent or read broker financial funds')

    def fill(self, trade, cumulative, price):
        delta = cumulative - trade.status.deal_quantity
        trade.status.deals.append(SimpleNamespace(seq='fill-' + str(len(trade.status.deals) + 1), quantity=delta, price=float(price)))
        trade.status.deal_quantity = cumulative
        trade.status.status = 'Filled' if cumulative == trade.order.quantity else 'PartFilled'


class ManualCoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = MutableClock()
        self.spec = replace(instrument(Market.INDEX_FUTURE), instrument_id='TMF:202611', underlying='TMF', margin=D('35050'))
        self.native = getattr(self, 'sdk_class', ManualSDK)(self.spec)
        module = SimpleNamespace(__version__='1.7.9', Unit=Unit, Order=lambda **kwargs: SimpleNamespace(**kwargs))
        self.owner = SharedSDKSession(ShioajiSDKFacade(self.native, module, environment=Environment.BROKER_SIMULATION))
        self.owner.login(api_key='fake', secret_key='fake')
        self.execution = self.owner.consumer('execution')
        self.scope = ManualScope('accepted-sim', 2, Environment.BROKER_SIMULATION, 'future-alias', 'generation-a', 3)
        capability = SimpleNamespace()  # Build a real typed capability below.
        from quantlab.trading.domain.models import CapabilitySnapshot

        capability = CapabilitySnapshot(
            'future-alias',
            Environment.BROKER_SIMULATION,
            frozenset((Market.INDEX_FUTURE,)),
            True,
            True,
            False,
            True,
            True,
            'APP_CONFIRMED_SIM_MANUAL_ATTEMPT_KEY_PERMISSION_UNVERIFIED',
            self.clock.now(),
            self.clock.now() + timedelta(hours=3),
            'manual-attempt-v1',
        )
        self.adapter = ShioajiAdapter(
            self.execution,
            self.clock,
            Environment.BROKER_SIMULATION,
            {'future-alias': self.native.account},
            (InstrumentBinding(self.spec, 'TMFL6'),),
            (capability,),
            {'future-alias': D('40000')},
            sdk_version='1.7.9',
            read_only=False,
            execution_enabled=True,
            share_unit='Share',
        )
        self.adapter.attach_authenticated()
        self.journal = GuardJournal()
        self.engine = TradingEngine(
            self.journal,
            self.clock,
            synthetic_calendar(),
            Catalog((self.spec,)),
            {'future-alias': self.adapter},
            configuration=ExecutionConfiguration(Environment.BROKER_SIMULATION, '', 'future-alias', False, True),
            ownership_clock=self.clock.now,
            fees=FeeSchedule(version='explicit-offline-test-costs'),
        )
        self.engine.quote(Quote(self.spec.instrument_id, D('24999'), D('25000'), D('25000'), self.clock.now(), self.clock.now(), self.clock.now().date()))
        self.service = ManualTradingService(
            self.engine,
            validate_scope=self.validate_scope,
            limits=(ManualPriceLimit(self.spec.instrument_id, D('22500'), D('27500'), self.clock.now(), 'SDK_ACTUAL_TEST_LIMITS'),),
            cost_source='explicit-offline-test-costs',
            margin_source='exchange-test-reference-35050-TWD',
        )
        self.observe()

    def validate_scope(self, scope):
        if (scope.environment, scope.account_ref, scope.connection_generation, scope.connection_revision) != (
            self.scope.environment,
            self.scope.account_ref,
            self.scope.connection_generation,
            self.scope.connection_revision,
        ):
            raise DomainError('state_conflict')

    def command(self, action, **fields):
        if action is UiAction.FLATTEN and 'manual_book' not in fields:
            fields['manual_book'] = ManualBookForm(self.scope, book_for(self.engine, self.scope.account_ref).capital, True)
        return UiCommand(
            action,
            self.engine.state.version,
            environment=self.scope.environment,
            account_ref=self.scope.account_ref,
            context_id=self.scope.context_id,
            context_epoch=self.scope.context_epoch,
            connection_generation=self.scope.connection_generation,
            connection_revision=self.scope.connection_revision,
            **fields,
        )

    def observe(self):
        self.service.adopt((self.adapter.observe_manual('future-alias', cursor(self.engine, 'future-alias')),))

    def enable(self):
        receipt = self.service.execute(self.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(self.scope, D('40000'), True)))
        self.assertTrue(receipt.accepted, receipt)

    def prepare_test(self):
        receipt = self.service.execute(self.command(UiAction.TEST_SIM_ORDER))
        self.assertTrue(receipt.accepted, receipt)
        preview = self.service.snapshot(self.scope).preview
        return ManualOrderForm(
            preview.scope,
            preview.request_id,
            preview.instrument_id,
            preview.side,
            preview.quantity,
            preview.limit_price,
            preview.stop_price,
            preview.purpose,
            True,
            preview.preview_id,
        )

    def confirm_test(self):
        self.enable()
        form = self.prepare_test()
        receipt = self.service.execute(self.command(UiAction.TEST_SIM_ORDER, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        self.observe()
        self.assertEqual(self.service.snapshot(self.scope).test_status, 'PASSED')
        return form

    def normal(self, request_id='normal-a', **fields):
        form = ManualOrderForm(self.scope, request_id, self.spec.instrument_id, Side.BUY, 1, D('25000'), D('24950'))
        form = replace(form, **fields)
        receipt = self.service.execute(self.command(UiAction.PREVIEW_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        preview = self.service.snapshot(self.scope).preview
        return replace(form, confirmed=True, preview_id=preview.preview_id), preview

    def test_diagnostic_two_phases_uses_one_canonical_submit_and_confirmed_cancel(self):
        self.enable()
        view = self.service.snapshot(self.scope)
        self.assertTrue(view.can_test)
        self.assertFalse(view.can_submit)
        form = self.prepare_test()
        self.assertEqual(self.native.trades, [])
        self.assertEqual(form.quantity, 1)
        self.assertEqual(form.limit_price, D('22500'))
        receipt = self.service.execute(self.command(UiAction.TEST_SIM_ORDER, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        self.assertFalse(self.service.snapshot(self.scope).pending.outcome_known)
        self.assertEqual([row[0] for row in self.native._seen].count('place_order'), 1)
        self.assertEqual([row[0] for row in self.native._seen].count('cancel_order'), 1)
        self.observe()
        view = self.service.snapshot(self.scope)
        self.assertEqual(view.test_status, 'PASSED')
        self.assertTrue(view.can_submit)
        self.assertTrue(view.last_result.outcome_known)
        self.assertEqual(view.last_result.request_id, form.request_id)
        self.assertEqual(self.engine.state.strategies, ())
        self.assertIsNone(self.engine.state.daily_baseline_evidence)
        self.assertTrue(self.engine.state.daily_baseline_required)
        kinds = [row.kind for row in self.journal.events]
        self.assertLess(kinds.index('manual_request_pending'), kinds.index('order_submitting'))

    def test_unknown_submit_keeps_identity_reservation_and_never_retries(self):
        self.confirm_test()
        form, _ = self.normal()
        self.native.place_mode = 'TIMEOUT'
        command = self.command(UiAction.SUBMIT_MANUAL, manual_order=form)
        receipt = self.service.execute(command)
        self.assertEqual(receipt.code, 'outcome_unknown')
        order = self.engine.state.orders[-1]
        self.assertGreater(order.reservation.cash, 35050)
        view = self.service.snapshot(self.scope)
        self.assertEqual(view.pending.request_id, form.request_id)
        self.assertEqual(view.pending.order_id, order.order_id)
        self.assertFalse(view.pending.outcome_known)
        before = len(self.native.trades)
        self.assertEqual(self.service.execute(command).code, 'outcome_unknown')
        self.assertEqual(len(self.native.trades), before)
        self.assertEqual(self.service.execute(replace(command, manual_order=replace(form, quantity=2))).code, 'state_conflict')

    def test_fill_is_real_owned_inventory_and_manual_stop_is_not_automatic(self):
        self.confirm_test()
        form, _ = self.normal()
        receipt = self.service.execute(self.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted)
        self.native.fill(self.native.trades[-1], 1, D('25000'))
        self.observe()
        self.assertEqual(self.engine.state.positions[-1].quantity, 1)
        self.assertTrue(self.service.snapshot(self.scope).halted)
        self.assertLess(manual_capacity(self.engine, book_for(self.engine, 'future-alias')).settled_cash, D('40000'))
        before = len(self.native.trades)
        self.clock.value += timedelta(seconds=1)
        self.engine.quote(Quote(self.spec.instrument_id, D('24900'), D('24901'), D('24900'), self.clock.now(), self.clock.now(), self.clock.now().date()))
        self.assertEqual(len(self.native.trades), before)
        from quantlab.trading.application.views import snapshot

        self.assertEqual(snapshot(self.engine).positions[-1].protection, 'UNPROTECTED')

    def test_virtual_capacity_never_reads_broker_zero_or_unknown_financials(self):
        self.confirm_test()
        _, preview = self.normal()
        self.assertTrue(preview.allowed)
        self.assertGreater(preview.total_cash, D('35050'))
        self.assertLess(preview.total_cash, D('40000'))
        self.assertEqual(preview.funds_source, 'APP_VIRTUAL_SIMULATION')
        self.assertEqual(preview.protection, 'UNPROTECTED')
        self.assertEqual(self.native.financial_queries, 0)

    def test_partial_and_full_diagnostic_fill_never_passes_permission_gate(self):
        self.enable()
        self.native.fill_on_cancel = True
        form = self.prepare_test()
        receipt = self.service.execute(self.command(UiAction.TEST_SIM_ORDER, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        self.assertFalse(self.service.snapshot(self.scope).can_submit)
        self.observe()
        view = self.service.snapshot(self.scope)
        self.assertEqual(view.test_status, 'FAILED')
        self.assertTrue(view.halted)
        self.assertFalse(view.can_submit)
        self.assertEqual(self.engine.state.positions[-1].quantity, 1)
        self.assertEqual([row[0] for row in self.native._seen].count('place_order'), 1)
        # A single-contract diagnostic has no fractional partial fill. The
        # cancel/full-fill race must retain the complete contract, never flip it.
        self.assertEqual([trade.order.action for trade in self.native.trades], ['Buy'])

    def test_diagnostic_cancel_timeout_preserves_identity_and_risk(self):
        self.enable()
        self.native.cancel_mode = 'TIMEOUT'
        form = self.prepare_test()
        command = self.command(UiAction.TEST_SIM_ORDER, manual_order=form)
        receipt = self.service.execute(command)
        self.assertEqual(receipt.code, 'outcome_unknown')
        view = self.service.snapshot(self.scope)
        self.assertFalse(view.pending.outcome_known)
        self.assertEqual(view.pending.request_id, form.request_id)
        self.assertTrue(view.halted)
        self.assertGreater(self.engine.state.orders[-1].reservation.cash, 35050)
        self.service.execute(command)
        self.assertEqual([row[0] for row in self.native._seen].count('place_order'), 1)
        self.assertEqual([row[0] for row in self.native._seen].count('cancel_order'), 1)

    def test_manual_flatten_uses_canonical_path_without_automatic_cycle(self):
        self.confirm_test()
        form, _ = self.normal()
        self.assertTrue(self.service.execute(self.command(UiAction.SUBMIT_MANUAL, manual_order=form)).accepted)
        self.native.fill(self.native.trades[-1], 1, D('25000'))
        self.observe()
        lot = self.engine.state.positions[-1]
        before = len(self.native.trades)
        self.assertEqual(self.service.execute(self.command(UiAction.FLATTEN, target_id=lot.lot_id, manual_book=None)).code, 'manual_confirmation_required')
        self.assertEqual(len(self.native.trades), before)
        receipt = self.service.execute(self.command(UiAction.FLATTEN, target_id=lot.lot_id))
        self.assertTrue(receipt.accepted, receipt)
        self.assertTrue(self.engine.state.orders[-1].plan.reduce_only)
        self.assertEqual(self.native.trades[-1].order.octype, 'Cover')
        self.assertEqual(self.native.trades[-1].order.action, 'Sell')
        self.native.fill(self.native.trades[-1], 1, D('24999'))
        self.observe()
        self.assertEqual(self.engine.state.positions[-1].quantity, 0)
        self.assertEqual(self.engine.state.strategies, ())

    def test_quantity_price_risk_and_scope_rejections_never_reach_sdk(self):
        self.confirm_test()
        _, preview = self.normal(quantity=2)
        self.assertFalse(preview.allowed)
        self.assertEqual(preview.reasons, ('risk_resized',))
        before = len(self.native.trades)
        bad = ManualOrderForm(self.scope, 'bad', self.spec.instrument_id, Side.BUY, 1, D('25000.5'), D('24950'))
        self.assertTrue(self.service.execute(self.command(UiAction.PREVIEW_MANUAL, manual_order=bad)).accepted)
        self.assertFalse(self.service.snapshot(self.scope).preview.allowed)
        changed = replace(self.scope, connection_generation='old-generation')
        receipt = self.service.execute(self.command(UiAction.SUBMIT_MANUAL, manual_order=replace(bad, scope=changed)))
        self.assertEqual(receipt.code, 'state_conflict')
        self.assertEqual(len(self.native.trades), before)

    def test_price_only_amend_after_entry_ttl_preserves_reservation_until_ack(self):
        self.confirm_test()
        form, _ = self.normal()
        receipt = self.service.execute(self.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        order = self.engine.state.orders[-1]
        self.clock.value += timedelta(seconds=31)
        self.engine.quote(Quote(self.spec.instrument_id, D('24999'), D('25000'), D('25000'), self.clock.now(), self.clock.now(), self.clock.now().date()))
        self.observe()
        order = self.engine.state.orders[-1]
        mutation = ManualMutationForm(self.scope, 'amend-a', receipt.reference, D('24990'), confirmed=True)
        receipt = self.service.execute(self.command(UiAction.AMEND_MANUAL, manual_mutation=mutation))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.engine.state.orders[-1].reservation, order.reservation)
        self.assertFalse(self.service.snapshot(self.scope).pending.outcome_known)
        self.observe()
        self.assertTrue(self.service.snapshot(self.scope).last_result.outcome_known)
        self.assertEqual(self.service.snapshot(self.scope).last_result.status, 'AMENDED')
        self.assertEqual([row[0] for row in self.native._seen].count('update_order'), 1)

    def test_external_unknown_or_degraded_observation_blocks_new_book(self):
        self.native.cache_state = 'Degraded'
        with self.assertRaises(DomainError):
            self.observe()
        self.assertEqual(self.native.financial_queries, 0)

    def test_automatic_deployment_and_baseline_rules_remain_required(self):
        self.confirm_test()
        from quantlab.trading.application.sessions import assert_daily_baseline

        with self.assertRaises(DomainError) as error:
            assert_daily_baseline(self.engine)
        self.assertEqual(error.exception.code, 'daily_baseline_required')
        self.assertEqual(self.engine.state.strategies, ())

    def test_client_diagnostic_purpose_cannot_mint_backend_test_authority(self):
        self.enable()
        forged = ManualOrderForm(self.scope, 'client-diagnostic', self.spec.instrument_id, Side.BUY, 1, D('25000'), D('24999'), ManualPurpose.DIAGNOSTIC_TMF)
        receipt = self.service.execute(self.command(UiAction.PREVIEW_MANUAL, manual_order=forged))
        self.assertEqual(receipt.code, 'validation_failed')
        self.assertEqual(self.native.trades, [])

    def test_stop_new_cannot_be_cleared_by_new_book_or_bare_resume(self):
        self.enable()
        from quantlab.trading.application.facade import LocalFacade
        from quantlab.trading.application.workflows import resume

        facade = LocalFacade(self.engine)
        receipt = facade.execute(UiCommand(UiAction.STOP_NEW, self.engine.state.version))
        self.assertTrue(receipt.accepted)
        self.assertTrue(book_for(self.engine, 'future-alias').halted)
        self.assertTrue(self.engine.state.manual_stopped)
        self.assertFalse(self.service.snapshot(self.scope).can_test)
        self.assertEqual(self.service.execute(self.command(UiAction.RESUME)).code, 'manual_confirmation_required')
        with self.assertRaises(DomainError):
            resume(self.engine)
        self.assertTrue(self.engine.state.stopped)
        self.assertEqual(
            self.service.execute(self.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(self.scope, D('40000'), True))).code, 'state_conflict'
        )
        receipt = self.service.execute(self.command(UiAction.RESUME, manual_book=ManualBookForm(self.scope, D('40000'), True)))
        self.assertTrue(receipt.accepted, receipt)
        self.assertFalse(self.engine.state.stopped)

    def test_restart_requires_reconcile_and_explicit_resume_without_reset(self):
        self.confirm_test()
        old = book_for(self.engine, 'future-alias')
        restored = TradingEngine(
            self.journal,
            self.clock,
            self.engine.calendar,
            self.engine.catalog,
            self.engine.gateways,
            configuration=self.engine.configuration,
            ownership_clock=self.clock.now,
            fees=self.engine.fees,
        )
        self.engine = restored
        restored.quote(Quote(self.spec.instrument_id, D('24999'), D('25000'), D('25000'), self.clock.now(), self.clock.now(), self.clock.now().date()))
        self.service = ManualTradingService(
            restored,
            validate_scope=self.validate_scope,
            limits=tuple(self.service.limits.values()),
            cost_source=self.service.cost_source,
            margin_source=self.service.margin_source,
        )
        self.assertTrue(self.service.snapshot(self.scope).halted)
        self.observe()
        self.assertTrue(self.service.snapshot(self.scope).halted)
        self.assertEqual(book_for(restored, 'future-alias').capital, old.capital)
        changed = ManualBookForm(self.scope, D('39000'), True)
        self.assertEqual(self.service.execute(self.command(UiAction.RESUME, manual_book=changed)).code, 'state_conflict')
        self.assertTrue(self.service.execute(self.command(UiAction.RESUME, manual_book=ManualBookForm(self.scope, old.capital, True))).accepted)
        self.scope = replace(self.scope, connection_generation='generation-b')
        view = self.service.snapshot(self.scope)
        self.assertFalse(view.can_submit)
        self.assertTrue(view.can_test)
        self.assertEqual(view.test_status, 'UNTESTED')
        self.clock.value += timedelta(days=3)
        from quantlab.trading.application.sessions import synchronize_session

        synchronize_session(self.engine)
        self.adapter.capabilities['future-alias'] = replace(
            self.adapter.capabilities['future-alias'], checked_at=self.clock.now(), expires_at=self.clock.now() + timedelta(hours=3)
        )
        self.observe()
        receipt = self.service.execute(self.command(UiAction.RESUME, manual_book=ManualBookForm(self.scope, old.capital, True)))
        self.assertEqual(receipt.code, 'manual_day_baseline_required')
        self.assertEqual(book_for(self.engine, 'future-alias').capital, old.capital)

    def test_external_price_or_quantity_change_is_not_adopted(self):
        self.confirm_test()
        form, _ = self.normal()
        self.assertTrue(self.service.execute(self.command(UiAction.SUBMIT_MANUAL, manual_order=form)).accepted)
        self.native.trades[-1].order.quantity = 20
        with self.assertRaises(DomainError):
            self.observe()
        self.native.trades[-1].order.quantity = 1
        self.native.trades[-1].status.modified_price = 25010.0
        with self.assertRaises(DomainError):
            self.observe()
        self.assertTrue(self.service.snapshot(self.scope).halted)

    def test_initial_empty_book_can_start_next_session_without_resetting_history(self):
        self.enable()
        opening = book_for(self.engine, 'future-alias').opening_day
        next_day = self.engine.calendar.advance(opening, 1)
        self.clock.value = self.engine.calendar.day_session(next_day).opens_at + timedelta(minutes=1)
        self.adapter.capabilities['future-alias'] = replace(
            self.adapter.capabilities['future-alias'], checked_at=self.clock.now(), expires_at=self.clock.now() + timedelta(hours=3)
        )
        self.observe()
        book = book_for(self.engine, 'future-alias')
        self.assertEqual(book.opening_day, next_day)
        self.assertEqual(book.capital, D('40000'))
        self.assertFalse(self.engine.state.stopped)
        self.assertEqual(self.engine.state.manual_requests, ())
        self.assertEqual(self.engine.state.orders, ())
        self.assertIsNone(self.engine.state.daily_baseline_evidence)


class MultiAccountManualSDK(ManualSDK):
    def __init__(self, spec):
        super().__init__(spec)
        self.stock_account = SimpleNamespace(account_type='S', broker_id='FAKE', account_id='manual-stock', signed=True)
        self._accounts.append(self.stock_account)
        self.stock_item = contract('0050')
        self.stock_info = SimpleNamespace(**vars(self.stock_item), unit=1000, currency='TWD', trading_suspended=False)
        self._contracts = SimpleNamespace(
            get=lambda code: {'TMFL6': self.item, '0050': self.stock_item}[code], info=lambda item: self.stock_info if item.code == '0050' else self.info
        )

    def list_positions(self, account=None, unit=None, timeout=30000, cb=None):
        self._record('list_positions', account=account, unit=unit, timeout=timeout)
        trades = [trade for trade in self.trades if trade.order.account is account]
        signed = sum(trade.status.deal_quantity * (1 if trade.order.action == 'Buy' else -1) for trade in trades)
        if not signed:
            return []
        stock = account is self.stock_account
        first = next(trade for trade in trades if trade.status.deal_quantity)
        return [
            SimpleNamespace(
                code='0050' if stock else 'TMFL6',
                direction='Buy' if signed > 0 else 'Sell',
                quantity=abs(signed) * (1000 if stock else 1),
                price=first.order.price,
                yd_quantity=0,
                cond='Cash',
                collateral=0,
                margin_purchase_amount=0,
                short_sale_margin=0,
            )
        ]


class ManualStockTests(unittest.TestCase):
    def setUp(self):
        from test_trading_adapters import ShioajiContractTests

        self.case = case = ManualCoreTests()
        case.sdk_class = MultiAccountManualSDK
        case.setUp()
        stock_fixture = ShioajiContractTests()
        stock_fixture.setUp()
        binding = stock_fixture.adapter().bindings[stock_fixture.spec.instrument_id]
        self.stock = binding.spec
        adapter, engine = case.adapter, case.engine
        adapter.bindings[self.stock.instrument_id] = binding
        adapter.accounts['stock-alias'] = case.native.stock_account
        adapter.allocations['stock-alias'] = D('60000')
        adapter.capabilities['stock-alias'] = replace(
            adapter.capabilities['future-alias'], account_ref='stock-alias', markets=frozenset((Market.STOCK,)), day_trade=False, short_sell=False
        )
        adapter.account_sequences['stock-alias'] = 0
        engine.gateways['stock-alias'] = adapter
        engine.configuration = replace(engine.configuration, stock_account_ref='stock-alias')
        engine.catalog = Catalog((*engine.catalog.instruments, self.stock))
        engine.quote(Quote(self.stock.instrument_id, D('19.99'), D('20'), D('20'), case.clock.now(), case.clock.now(), case.clock.now().date()))
        case.service = ManualTradingService(
            engine,
            validate_scope=case.validate_scope,
            limits=(*case.service.limits.values(), ManualPriceLimit(self.stock.instrument_id, D('18'), D('22'), case.clock.now(), 'SDK_TEST_LIMITS')),
            cost_source=case.service.cost_source,
            margin_source=case.service.margin_source,
        )
        case.observe = self.observe
        self.observe()
        case.confirm_test()
        case.scope = replace(case.scope, account_ref='stock-alias')
        receipt = case.service.execute(case.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(case.scope, D('60000'), True)))
        self.assertTrue(receipt.accepted, receipt)

    def observe(self):
        case = self.case
        case.service.adopt(tuple(case.adapter.observe_manual(alias, cursor(case.engine, alias)) for alias in case.engine.gateways))

    def prepare(self, quantity=2000):
        case = self.case
        form = ManualOrderForm(case.scope, 'stock-order', self.stock.instrument_id, Side.BUY, quantity, D('20'), D('19.9'))
        receipt = case.service.execute(case.command(UiAction.PREVIEW_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        preview = case.service.snapshot(case.scope).preview
        return replace(form, confirmed=True, preview_id=preview.preview_id), preview

    def test_stock_whole_lot_partial_fill_cancel_and_permission_provenance(self):
        case = self.case
        view = case.service.snapshot(case.scope)
        self.assertTrue(view.can_submit)
        self.assertFalse(view.can_test)
        form, preview = self.prepare()
        self.assertTrue(preview.allowed)
        receipt = case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        native = case.native.trades[-1]
        self.assertEqual(native.order.quantity, 2)
        self.assertEqual(native.order.order_lot, 'Common')
        case.native.fill(native, 1, D('20'))
        self.observe()
        local = case.engine.state.orders[-1]
        self.assertEqual(local.filled, 1000)
        self.assertEqual(case.engine.state.positions[-1].quantity, 1000)
        mutation = ManualMutationForm(case.scope, 'stock-cancel', receipt.reference, confirmed=True)
        self.assertTrue(case.service.execute(case.command(UiAction.CANCEL_MANUAL, manual_mutation=mutation)).accepted)
        self.observe()
        self.assertEqual(case.engine.state.orders[-1].status, OrderStatus.CANCELED)
        self.assertEqual(case.engine.state.positions[-1].quantity, 1000)
        self.assertEqual(case.engine.state.positions[-1].sellable_quantity, 0)
        self.assertEqual(case.engine.state.orders[-1].reservation.cash, D('0'))
        self.assertGreater(case.engine.state.orders[-1].reservation.risk, D('0'))

    def test_odd_lot_and_unverified_same_day_stock_exit_are_rejected(self):
        case = self.case
        form = ManualOrderForm(case.scope, 'odd-lot', self.stock.instrument_id, Side.BUY, 999, D('20'), D('19.9'))
        self.assertEqual(case.service.execute(case.command(UiAction.PREVIEW_MANUAL, manual_order=form)).code, 'risk_rejected')
        form, _ = self.prepare(1000)
        self.assertTrue(case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form)).accepted)
        case.native.fill(case.native.trades[-1], 1, D('20'))
        self.observe()
        lot = case.engine.state.positions[-1]
        receipt = case.service.execute(case.command(UiAction.FLATTEN, target_id=lot.lot_id))
        self.assertEqual(receipt.code, 'exit_unavailable')
        self.assertEqual(case.native.trades[-1].order.action, 'Buy')

    def test_settled_owned_stock_exit_and_sale_proceeds_remain_unsettled(self):
        case = self.case
        form, _ = self.prepare(1000)
        self.assertTrue(case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form)).accepted)
        case.native.fill(case.native.trades[-1], 1, D('20'))
        self.observe()
        lot = case.engine.state.positions[-1]
        self.assertEqual(lot.sellable_quantity, 0)
        self.assertEqual(case.engine.state.manual_acquisitions[-1].quantity, 1000)
        # Friday -> Tuesday uses the explicit fixture calendar's two trading
        # sessions. Refresh capability/limits evidence; do not infer weekdays.
        due = case.engine.state.manual_acquisitions[-1].available_on
        case.clock.value = case.engine.calendar.day_session(due).opens_at + timedelta(minutes=1)
        for alias, capability in tuple(case.adapter.capabilities.items()):
            case.adapter.capabilities[alias] = replace(capability, checked_at=case.clock.now(), expires_at=case.clock.now() + timedelta(hours=3))
        case.service.limits = {key: replace(value, observed_at=case.clock.now()) for key, value in case.service.limits.items()}
        for spec in case.engine.catalog.instruments:
            price = D('20') if spec.market is Market.STOCK else D('25000')
            tick = spec.tick_for(price)
            case.engine.quote(Quote(spec.instrument_id, price - tick, price, price, case.clock.now(), case.clock.now(), due))
        self.observe()
        lot = case.engine.state.positions[-1]
        self.assertEqual(lot.sellable_quantity, 1000)
        self.assertTrue(case.engine.state.stopped)  # Cross-day missing closing evidence still blocks new risk.
        receipt = case.service.execute(case.command(UiAction.FLATTEN, target_id=lot.lot_id))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(case.native.trades[-1].order.quantity, 1)
        self.assertEqual(case.native.trades[-1].order.action, 'Sell')
        self.assertEqual(case.service.execute(case.command(UiAction.FLATTEN, target_id=lot.lot_id)).code, 'exit_already_pending')
        case.native.fill(case.native.trades[-1], 1, D('19.99'))
        self.observe()
        self.assertEqual(case.engine.state.positions[-1].quantity, 0)
        capacity = manual_capacity(case.engine, book_for(case.engine, 'stock-alias'))
        self.assertGreater(capacity.settlement_reserved, D('19000'))
        self.assertEqual(len(case.engine.state.manual_receivables), 1)
        self.observe()
        self.assertEqual(len(case.engine.state.manual_receivables), 1)
        from quantlab.trading.application.codec import loads

        exit_states = []
        for event in case.journal.events:
            state = loads(event.payload)
            if any(order.plan.reduce_only and order.filled for order in state.orders):
                exit_states.append(state)
        self.assertTrue(exit_states)
        self.assertTrue(all(state.manual_receivables for state in exit_states))


if __name__ == '__main__':
    unittest.main()
