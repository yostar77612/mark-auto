"""Each fail-closed guard of the manual SIM path has a test that fails when the guard is deleted."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest

import test_manual_trading as base
from test_trading_adapters import NOW, capability, instrument
from test_trading_domain import DAYS, calendar as domain_calendar
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.manual_book import book_for
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualMutationForm, ManualOrderForm
from quantlab.trading.domain.models import HoldingKind, HoldingPolicy, Market, OrderStatus, PositionLot, Quote, Side
from quantlab.trading.domain.policies import ExitCoordinator
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import CommandReceipt, SubmissionReceipt

D = Decimal


class GuardCase(unittest.TestCase):
    confirm = True

    def setUp(self):
        self.case = case = base.ManualCoreTests()
        case.setUp()
        self.native, self.service, self.engine, self.adapter, self.clock = case.native, case.service, case.engine, case.adapter, case.clock
        if self.confirm:
            case.confirm_test()
        else:
            case.enable()
        self.baseline = {name: self.count(name) for name in ('place_order', 'cancel_order', 'update_order')}

    def count(self, name):
        return [row[0] for row in self.native._seen].count(name)

    def delta(self, name):
        return self.count(name) - self.baseline[name]

    def run_command(self, action, **fields):
        return self.service.execute(self.case.command(action, **fields))

    def quote(self, bid, ask, last=None, **fields):
        now = self.clock.now()
        quote = Quote(self.case.spec.instrument_id, bid, ask, last or ask, fields.pop('source_at', now), fields.pop('received_at', now), now.date(), **fields)
        self.engine.quotes[quote.instrument_id] = quote

    def accepted_order(self, request_id='normal-a'):
        form, _ = self.case.normal(request_id)
        self.assertTrue(self.run_command(UiAction.SUBMIT_MANUAL, manual_order=form).accepted)
        return next(row for row in self.engine.state.orders if row.key == request_id)

    def filled_lot(self):
        self.accepted_order()
        self.native.fill(self.native.trades[-1], 1, D('25000'))
        self.case.observe()
        return self.engine.state.positions[-1]


class ConfirmationGuardTests(GuardCase):
    def test_backend_rejects_an_unconfirmed_submit_even_with_a_valid_preview(self):
        form, _ = self.case.normal()
        receipt = self.run_command(UiAction.SUBMIT_MANUAL, manual_order=replace(form, confirmed=False))
        self.assertEqual(receipt.code, 'manual_confirmation_required')
        self.assertEqual(self.delta('place_order'), 0)

    def test_backend_rejects_an_unconfirmed_cancel_and_amend(self):
        order = self.accepted_order()
        for action, price in ((UiAction.CANCEL_MANUAL, None), (UiAction.AMEND_MANUAL, D('24990'))):
            with self.subTest(action=action):
                form = ManualMutationForm(self.case.scope, 'unconfirmed-' + action.value, order.order_id, price)
                self.assertEqual(self.run_command(action, manual_mutation=form).code, 'manual_confirmation_required')
        self.assertEqual((self.delta('cancel_order'), self.delta('update_order')), (0, 0))


class PreviewGuardTests(GuardCase):
    def preview(self, request_id='preview-a', **fields):
        form = ManualOrderForm(self.case.scope, request_id, self.case.spec.instrument_id, Side.BUY, 1, D('25000'), D('24950'))
        return self.run_command(UiAction.PREVIEW_MANUAL, manual_order=replace(form, **fields))

    def test_limit_price_outside_the_verified_daily_band_is_refused(self):
        self.assertEqual(self.preview('high', limit_price=D('27501')).code, 'instrument_unresolved')
        self.assertEqual(self.preview('low', limit_price=D('22499'), stop_price=D('22400')).code, 'instrument_unresolved')

    def test_stale_daily_limits_are_refused(self):
        key = self.case.spec.instrument_id
        self.service.limits[key] = replace(self.service.limits[key], observed_at=self.clock.now() - timedelta(days=1))
        self.assertEqual(self.preview().code, 'instrument_unresolved')

    def test_quote_from_another_session_is_refused(self):
        self.quote(D('24999'), D('25000'), session='NIGHT')
        self.assertEqual(self.preview().code, 'session_closed')

    def test_missing_quote_is_refused(self):
        del self.engine.quotes[self.case.spec.instrument_id]
        self.assertEqual(self.preview().code, 'stale_quote')

    def test_unsigned_account_cannot_trade_and_never_reaches_the_sdk(self):
        self.native.account.signed = False
        self.assertFalse(self.adapter.inspect('future-alias').can_trade)
        self.assertEqual(self.preview().code, 'capability_missing')
        self.assertEqual(self.delta('place_order'), 0)

    def test_exit_must_be_opposite_to_the_owned_lot(self):
        lot = self.filled_lot()
        same_side = self.preview('exit-same', exit_lot_id=lot.lot_id)
        self.assertEqual(same_side.code, 'risk_rejected')
        opposite = self.preview('exit-ok', side=Side.SELL, limit_price=D('24999'), stop_price=D('25050'), exit_lot_id=lot.lot_id)
        self.assertTrue(opposite.accepted, opposite)


class DiagnosticGateTests(GuardCase):
    confirm = False

    def test_normal_orders_need_a_passed_diagnostic_for_this_connection(self):
        form = ManualOrderForm(self.case.scope, 'early', self.case.spec.instrument_id, Side.BUY, 1, D('25000'), D('24950'))
        self.assertEqual(self.run_command(UiAction.PREVIEW_MANUAL, manual_order=form).code, 'manual_test_required')
        self.assertEqual(self.delta('place_order'), 0)

    def test_a_diagnostic_without_its_durable_record_does_not_count(self):
        form = self.case.prepare_test()
        self.assertTrue(self.run_command(UiAction.TEST_SIM_ORDER, manual_order=form).accepted)
        self.case.observe()
        self.assertEqual(self.service.snapshot(self.case.scope).test_status, 'PASSED')
        self.engine._persist('forget', replace(self.engine.state, manual_requests=()))
        normal = ManualOrderForm(self.case.scope, 'after', self.case.spec.instrument_id, Side.BUY, 1, D('25000'), D('24950'))
        self.assertEqual(self.run_command(UiAction.PREVIEW_MANUAL, manual_order=normal).code, 'manual_test_required')


class AmendFreshnessTests(GuardCase):
    def amend(self, request_id):
        order = next(row for row in self.engine.state.orders if row.key == 'normal-a')
        return self.run_command(
            UiAction.AMEND_MANUAL, manual_mutation=ManualMutationForm(self.case.scope, request_id, order.order_id, D('24990'), confirmed=True)
        )

    def test_amend_needs_a_verified_fresh_quote(self):
        self.accepted_order()
        now = self.clock.now()
        cases = {
            'source-stale': dict(source_at=now - timedelta(seconds=31)),
            'received-in-future': dict(received_at=now + timedelta(seconds=5)),
            'unverified': dict(quality='DELAYED'),
        }
        for name, fields in cases.items():
            with self.subTest(name):
                self.quote(D('24999'), D('25000'), **fields)
                self.assertEqual(self.amend(name).code, 'stale_quote')
        with self.subTest('missing'):
            del self.engine.quotes[self.case.spec.instrument_id]
            self.assertEqual(self.amend('missing').code, 'stale_quote')
        self.assertEqual(self.delta('update_order'), 0)

    def test_amend_needs_a_fresh_account_observation(self):
        self.accepted_order()
        self.clock.value += timedelta(seconds=31)
        self.quote(D('24999'), D('25000'))
        self.assertEqual(self.amend('stale-observation').code, 'manual_account_observation_required')
        self.assertEqual(self.delta('update_order'), 0)
        self.case.observe()
        self.assertTrue(self.amend('fresh-observation').accepted)
        self.assertEqual(self.delta('update_order'), 1)


class DailyLossLockTests(GuardCase):
    def test_loss_at_the_daily_fraction_latches_the_day_and_halts_the_book(self):
        self.filled_lot()
        self.assertEqual(self.engine.state.daily_locks, ())
        self.clock.value += timedelta(seconds=1)
        self.quote(D('23999'), D('24000'))  # 1000 points * 10 = the 10% daily fraction of 100000
        self.case.observe()
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.assertIn('risk_rejected', book_for(self.engine, 'future-alias').reasons)
        resume = self.run_command(UiAction.RESUME, manual_book=ManualBookForm(self.case.scope, D('40000'), True))
        self.assertFalse(resume.accepted)

    def test_a_smaller_loss_does_not_latch(self):
        self.filled_lot()
        self.clock.value += timedelta(seconds=1)
        self.quote(D('24099'), D('24100'))
        self.case.observe()
        self.assertEqual(self.engine.state.daily_locks, ())


class FillRegressionTests(GuardCase):
    def test_cumulative_fill_that_goes_backwards_is_reconciliation_required(self):
        self.filled_lot()
        trade = self.native.trades[-1]
        trade.status.deals, trade.status.deal_quantity, trade.status.status = [], 0, 'Submitted'
        with self.assertRaises(DomainError) as caught:
            self.adapter.observe_manual('future-alias', 0)
        self.assertEqual((caught.exception.code, caught.exception.detail), ('reconciliation_required', 'broker cumulative fill regressed'))


class ChangeGuardTests(GuardCase):
    def test_amendment_may_only_reduce_the_unfilled_quantity(self):
        order = self.accepted_order()
        for quantity in (2, 0, 'one'):
            with self.subTest(quantity=quantity):
                with self.assertRaises(DomainError) as caught:
                    self.adapter.amend(order.order_id, D('24990'), quantity)
                self.assertEqual(caught.exception.code, 'validation_failed')
        self.assertEqual(self.delta('update_order'), 0)

    def test_only_a_working_order_can_be_cancelled_or_amended(self):
        order = self.accepted_order()
        self.adapter.orders[order.order_id] = replace(self.adapter.orders[order.order_id], status=OrderStatus.FILLED)
        for call in (lambda: self.adapter.cancel(order.order_id), lambda: self.adapter.amend(order.order_id, D('24990'))):
            with self.assertRaises(DomainError) as caught:
                call()
            self.assertEqual(caught.exception.code, 'state_conflict')
        self.assertEqual((self.delta('cancel_order'), self.delta('update_order')), (0, 0))


class CountingBroker:
    def __init__(self):
        self.submitted = 0

    def submit(self, plan, local_order_id):
        self.submitted += 1
        return SubmissionReceipt(local_order_id, 'broker-1', OrderStatus.ACCEPTED, NOW)

    def cancel(self, local_order_id):
        return CommandReceipt('cancel', True, OrderStatus.CANCELED, local_order_id, NOW)


class CommitGuardTests(GuardCase):
    def setUp(self):
        super().setUp()
        self.prior = self.accepted_order()
        self.broker = CountingBroker()
        engine = self.engine
        self.execution = ExecutionService(self.broker, engine._persist, engine.fence, engine.clock.now)

    def plan(self, **fields):
        now = self.clock.now()
        return replace(self.prior.plan, state_version=self.engine.state.version, deadline=now + timedelta(seconds=30), **fields)

    def commit(self, plan, key, request_hash):
        return self.execution.commit(self.engine.state, plan, self.prior.policy, self.prior.reservation, key, lambda: None, request_hash=request_hash)

    def test_same_key_and_content_returns_the_existing_order_without_a_second_send(self):
        self.assertEqual(self.commit(self.plan(), self.prior.key, self.prior.request_hash), self.prior.order_id)
        self.assertEqual(self.broker.submitted, 0)

    def test_same_key_with_changed_content_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.commit(self.plan(), self.prior.key, 'another-content-hash')
        self.assertEqual((caught.exception.code, caught.exception.detail), ('state_conflict', 'idempotency key reused with changed command'))
        self.assertEqual(self.broker.submitted, 0)

    def test_expired_plan_is_refused(self):
        expired = self.plan()
        self.clock.value += timedelta(seconds=31)
        with self.assertRaises(DomainError) as caught:
            self.commit(expired, 'fresh-key', 'fresh-hash')
        self.assertEqual((caught.exception.code, caught.exception.detail), ('state_conflict', 'expired or stale order plan'))
        self.assertEqual(self.broker.submitted, 0)

    def test_plan_prepared_against_another_state_version_is_refused(self):
        stale = replace(self.plan(), state_version=self.engine.state.version - 1)
        with self.assertRaises(DomainError) as caught:
            self.commit(stale, 'fresh-key', 'fresh-hash')
        self.assertEqual(caught.exception.detail, 'expired or stale order plan')
        self.assertEqual(self.broker.submitted, 0)


class StockScopeTests(unittest.TestCase):
    def setUp(self):
        self.stock = base.ManualStockTests()
        self.stock.setUp()
        self.case = self.stock.case
        form, _ = self.stock.prepare(1000)
        self.assertTrue(self.case.service.execute(self.case.command(UiAction.SUBMIT_MANUAL, manual_order=form)).accepted)
        self.case.native.fill(self.case.native.trades[-1], 1, D('20'))
        self.stock.observe()
        self.original_positions = self.case.native.list_positions

    def tweak(self, **fields):
        native, original = self.case.native, self.original_positions

        def positions(**kwargs):
            rows = original(**kwargs)
            for row in rows:
                for name, value in fields.items():
                    setattr(row, name, value)
            return rows

        native.list_positions = positions

    def test_only_unfinanced_cash_long_inventory_is_observed(self):
        observed = self.case.adapter.list('stock-alias', manual=True)
        self.assertEqual(observed[0].source, 'SHIOAJI_OBSERVED_UNFINANCED_CASH_LONG')
        for fields in (
            dict(cond='MarginTrading'),
            dict(direction='Sell'),
            dict(margin_purchase_amount=1),
            dict(collateral=1),
            dict(short_sale_margin=1),
        ):
            with self.subTest(fields):
                self.tweak(**fields)
                with self.assertRaises(DomainError) as caught:
                    self.case.adapter.list('stock-alias', manual=True)
                self.assertEqual(caught.exception.code, 'reconciliation_required')

    def test_service_refuses_stock_positions_not_marked_as_observed_cash_long(self):
        case = self.case
        observations = tuple(case.adapter.observe_manual(alias, 0) for alias in case.engine.gateways)
        self.assertIsNone(case.service.adopt(observations))
        marked = tuple(
            replace(row, positions=tuple(replace(position, source='EXTERNAL') for position in row.positions)) if row.account_ref == 'stock-alias' else row
            for row in observations
        )
        with self.assertRaises(DomainError) as caught:
            case.service.adopt(marked)
        self.assertEqual((caught.exception.code, caught.exception.detail), ('reconciliation_required', 'cash-long stock observation required'))


class StockAmendTests(unittest.TestCase):
    def test_amendment_cannot_shrink_to_the_filled_quantity(self):
        stock = base.ManualStockTests()
        stock.setUp()
        case = stock.case
        form, _ = stock.prepare(2000)
        self.assertTrue(case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form)).accepted)
        order = case.engine.state.orders[-1]
        case.native.fill(case.native.trades[-1], 1, D('20'))
        stock.observe()
        updates = [row[0] for row in case.native._seen].count('update_order')
        with self.assertRaises(DomainError) as caught:
            case.adapter.amend(order.order_id, D('19.95'), 1000)
        self.assertEqual(caught.exception.code, "validation_failed")
        self.assertEqual([row[0] for row in case.native._seen].count("update_order"), updates)


class SellableExitTests(unittest.TestCase):
    def test_exit_quantity_is_capped_by_the_sellable_inventory_when_not_same_day(self):
        spec = instrument(Market.STOCK)
        lot = PositionLot(
            'lot-1',
            'test-stock',
            spec.instrument_id,
            'swing',
            1,
            HoldingPolicy(HoldingKind.CUSTOM, 0, 0),
            2000,
            D('20'),
            DAYS[0],
            1000,
            holding_origin_trade_date=DAYS[0],
        )
        decision = ExitCoordinator().plan(lot, spec, capability(), domain_calendar(), DAYS[3], now=NOW, protective=True)
        self.assertEqual((decision.blocked, decision.quantity), (False, 1000))
        pending = ExitCoordinator().plan(lot, spec, capability(), domain_calendar(), DAYS[3], now=NOW, protective=True, pending_exit_quantity=400)
        self.assertEqual(pending.quantity, 600)


if __name__ == '__main__':
    unittest.main()
