"""M2-2b review fixes: unknown outcomes recover explicitly, pre-SDK refusals are not unknown outcomes."""

from copy import copy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

import test_manual_trading as base
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.manual_book import book_for
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualMutationForm, ManualOrderForm
from quantlab.trading.domain.models import Environment, OrderStatus, Quote, Side
from quantlab.trading.domain.validation import DomainError

D = Decimal


class ReviewSDK(base.ManualSDK):
    def __init__(self, spec):
        super().__init__(spec)
        self.lose_order = False  # place_order times out and the broker never saw the order
        self.drop_tag = False  # the broker echo carries no custom_field
        self.amend_mode = 'OK'  # TIMEOUT: raises and does not apply; TIMEOUT_APPLIED: raises after applying

    def place_order(self, contract, order, timeout=30000, cb=None):
        if self.lose_order:
            self._record('place_order', contract, order, timeout=timeout)
            raise TimeoutError('native private diagnostics must not escape')
        try:
            return super().place_order(contract, order, timeout, cb)
        finally:
            if self.drop_tag and self.trades:
                self.trades[-1].order.custom_field = ''

    def cancel_order(self, trade, timeout=30000, cb=None):
        if self.cancel_mode != 'TIMEOUT_APPLIED':
            return super().cancel_order(trade, timeout=timeout, cb=cb)
        self._record('cancel_order', trade, timeout=timeout)
        trade.status.status = 'Cancelled'
        raise TimeoutError('native private cancel diagnostics')

    def update_order(self, trade, *, price, timeout=30000, cb=None):
        if self.amend_mode == 'OK':
            return super().update_order(trade, price=price, timeout=timeout, cb=cb)
        self._record('update_order', trade, price=price, timeout=timeout)
        if self.amend_mode == 'TIMEOUT_APPLIED':
            trade.status.modified_price = price
        raise TimeoutError('native private amend diagnostics')


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.case = case = base.ManualCoreTests()
        case.sdk_class = ReviewSDK
        case.setUp()
        self.native, self.service, self.engine, self.adapter = case.native, case.service, case.engine, case.adapter
        case.confirm_test()
        self.baseline = {name: self.count(name) for name in ('place_order', 'cancel_order', 'update_order')}

    def count(self, name):
        return [row[0] for row in self.native._seen].count(name)

    def delta(self, name):
        return self.count(name) - self.baseline[name]

    def run_command(self, action, **fields):
        return self.service.execute(self.case.command(action, **fields))

    def submit(self, request_id='normal-a', **fields):
        form, _ = self.case.normal(request_id, **fields)
        return form, self.run_command(UiAction.SUBMIT_MANUAL, manual_order=form)

    def mutation(self, request_id, order_id, price=None):
        return ManualMutationForm(self.case.scope, request_id, order_id, price, confirmed=True)

    def resume(self):
        return self.run_command(UiAction.RESUME, manual_book=ManualBookForm(self.case.scope, D('40000'), True))

    def pending(self):
        return self.service.snapshot(self.case.scope).pending

    def request(self, request_id):
        return next(row for row in self.engine.state.manual_requests if row.request_id == request_id)

    def order(self, request_id):
        return next(row for row in self.engine.state.orders if row.key == request_id)


class UnknownSubmissionTests(ReviewCase):
    def test_timeout_with_visible_order_is_found_by_its_tag_and_never_resent(self):
        placed = 0
        self.native.place_mode = 'TIMEOUT'
        _, receipt = self.submit()
        self.assertEqual(receipt.code, 'outcome_unknown')
        self.case.observe()
        self.assertTrue(self.request('normal-a').outcome_known)
        self.assertIs(self.order('normal-a').status, OrderStatus.ACCEPTED)
        self.assertEqual(self.order('normal-a').broker_ref, 'sdk-2')
        self.assertTrue(self.service.snapshot(self.case.scope).halted)
        self.assertTrue(self.resume().accepted)
        self.assertEqual(self.delta('place_order'), placed + 1)

    def test_untagged_broker_order_waits_for_owner_adoption_then_recovers(self):
        placed = 0
        self.native.place_mode, self.native.drop_tag = 'TIMEOUT', True
        _, receipt = self.submit()
        self.assertEqual(receipt.code, 'outcome_unknown')
        self.case.observe()  # tolerated: no raise, still halted and unresolved
        self.assertFalse(self.engine.state.reconciled)
        view = self.service.snapshot(self.case.scope)
        self.assertTrue(view.halted)
        self.assertEqual(view.pending.candidates, ('sdk-2',))
        order = self.order('normal-a')
        unconfirmed = ManualMutationForm(self.case.scope, 'adopt-a', order.order_id)
        self.assertEqual(self.run_command(UiAction.ADOPT_MANUAL_ORDER, manual_mutation=unconfirmed).code, 'manual_confirmation_required')
        wrong = self.run_command(UiAction.ADOPT_MANUAL_ORDER, manual_mutation=self.mutation('adopt-a', order.order_id), target_id='sdk-9')
        self.assertEqual(wrong.code, 'reconciliation_required')
        self.assertFalse(self.request('normal-a').outcome_known)
        adopted = self.run_command(UiAction.ADOPT_MANUAL_ORDER, manual_mutation=self.mutation('adopt-b', order.order_id))
        self.assertTrue(adopted.accepted, adopted)
        self.case.observe()
        self.assertTrue(self.request('normal-a').outcome_known)
        self.assertIs(self.order('normal-a').status, OrderStatus.ACCEPTED)
        self.assertTrue(self.resume().accepted)
        self.assertEqual(self.delta('place_order'), placed + 1)
        self.assertEqual(self.run_command(UiAction.ADOPT_MANUAL_ORDER, manual_mutation=self.mutation('adopt-b', order.order_id)).code, 'ok')
        # An adopted order exists at the broker: it can be neither adopted again nor declared unsent.
        for action in (UiAction.ADOPT_MANUAL_ORDER, UiAction.DECLARE_MANUAL_NOT_SENT):
            again = self.run_command(action, manual_mutation=self.mutation('again-' + action.value, order.order_id))
            self.assertEqual(again.code, 'state_conflict')
        self.assertIs(self.order('normal-a').status, OrderStatus.ACCEPTED)

    def test_adopted_fill_reaches_the_book_through_the_normal_event_path(self):
        self.native.place_mode, self.native.drop_tag = 'TIMEOUT', True
        self.submit()
        self.native.fill(self.native.trades[-1], 1, D('25000'))
        self.case.observe()  # positions cannot be checked while the submission is unknown
        order = self.order('normal-a')
        self.assertTrue(self.run_command(UiAction.ADOPT_MANUAL_ORDER, manual_mutation=self.mutation('adopt-a', order.order_id)).accepted)
        self.case.observe()
        self.assertEqual(self.engine.state.positions[-1].quantity, 1)

    def test_order_that_never_reached_the_broker_is_declared_not_sent_without_resend(self):
        placed = 0
        self.native.lose_order = True
        _, receipt = self.submit()
        self.assertEqual(receipt.code, 'outcome_unknown')
        self.case.observe()
        self.assertFalse(self.engine.state.reconciled)
        order = self.order('normal-a')
        self.assertEqual(self.pending().candidates, ())
        self.assertGreater(order.reservation.cash, 0)
        nothing = self.run_command(UiAction.ADOPT_MANUAL_ORDER, manual_mutation=self.mutation('adopt-a', order.order_id))
        self.assertEqual(nothing.code, 'reconciliation_required')
        unconfirmed = ManualMutationForm(self.case.scope, 'declare-a', order.order_id)
        self.assertEqual(self.run_command(UiAction.DECLARE_MANUAL_NOT_SENT, manual_mutation=unconfirmed).code, 'manual_confirmation_required')
        declared = self.run_command(UiAction.DECLARE_MANUAL_NOT_SENT, manual_mutation=self.mutation('declare-b', order.order_id))
        self.assertTrue(declared.accepted, declared)
        order = self.order('normal-a')
        self.assertIs(order.status, OrderStatus.REJECTED)
        self.assertEqual((order.reservation.cash, order.reservation.risk), (0, 0))
        self.assertEqual((self.request('normal-a').status, self.request('normal-a').reason), ('REJECTED', 'manual_declared_not_sent'))
        self.case.observe()
        self.assertTrue(self.engine.state.reconciled)
        self.assertTrue(self.resume().accepted)
        self.assertEqual(self.delta('place_order'), placed + 1)
        self.native.lose_order = False
        _, receipt = self.submit('normal-b')
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.delta('place_order'), placed + 2)

    def test_declaring_not_sent_is_refused_while_a_matching_broker_order_exists(self):
        self.native.place_mode, self.native.drop_tag = 'TIMEOUT', True
        self.submit()
        self.case.observe()
        order = self.order('normal-a')
        refused = self.run_command(UiAction.DECLARE_MANUAL_NOT_SENT, manual_mutation=self.mutation('declare-a', order.order_id))
        self.assertEqual(refused.code, 'state_conflict')
        self.assertIs(self.order('normal-a').status, OrderStatus.UNKNOWN)

    def test_resolution_requires_an_unknown_submission_and_a_fresh_observation(self):
        self.native.lose_order = True
        self.submit()
        self.case.observe()
        order = self.order('normal-a')
        known = self.engine.state.orders[0]
        self.assertEqual(self.run_command(UiAction.DECLARE_MANUAL_NOT_SENT, manual_mutation=self.mutation('declare-a', known.order_id)).code, 'state_conflict')
        self.case.clock.value += timedelta(seconds=31)
        stale = self.run_command(UiAction.DECLARE_MANUAL_NOT_SENT, manual_mutation=self.mutation('declare-b', order.order_id))
        self.assertEqual(stale.code, 'manual_account_observation_required')
        self.assertIs(self.order('normal-a').status, OrderStatus.UNKNOWN)

    def test_an_unclaimed_external_broker_order_still_quarantines_the_book(self):
        foreign = copy(self.native.trades[0])
        foreign.order = copy(foreign.order)
        foreign.order.id = 'external-phone-order'
        foreign.order.custom_field = ''
        self.native.trades.append(foreign)
        with self.assertRaises(DomainError) as caught:
            self.case.observe()
        self.assertEqual(caught.exception.code, 'reconciliation_required')
        self.assertTrue(self.service.snapshot(self.case.scope).halted)


class LiveStaysDisabledTests(ReviewCase):
    def test_resolution_operations_are_refused_in_the_production_environment(self):
        self.native.lose_order = True
        self.submit()
        self.case.observe()
        order = self.order('normal-a')
        for action in (UiAction.ADOPT_MANUAL_ORDER, UiAction.DECLARE_MANUAL_NOT_SENT):
            command = replace(self.case.command(action, manual_mutation=self.mutation('live-' + action.value, order.order_id)), environment=Environment.LIVE)
            receipt = self.service.execute(command)
            self.assertEqual((receipt.accepted, receipt.code), (False, 'production_orders_disabled'))
        self.assertIs(self.order('normal-a').status, OrderStatus.UNKNOWN)


class DiagnosticResolveTests(unittest.TestCase):
    """A diagnostic order that does exist can never be declared unsent or adopted."""

    def setUp(self):
        self.case = case = base.ManualCoreTests()
        case.sdk_class = ReviewSDK
        case.setUp()
        case.enable()
        self.form = case.prepare_test()

    def resolve(self, action, order_id):
        form = ManualMutationForm(self.case.scope, 'resolve-' + action.value, order_id, confirmed=True)
        return self.case.service.execute(self.case.command(action, manual_mutation=form))

    def test_diagnostic_with_an_unknown_cancel_is_not_declarable(self):
        self.case.native.cancel_mode = 'TIMEOUT'
        command = self.case.command(UiAction.TEST_SIM_ORDER, manual_order=self.form)
        self.assertEqual(self.case.service.execute(command).code, 'outcome_unknown')
        order = self.case.engine.state.orders[-1]
        self.assertIs(order.status, OrderStatus.UNKNOWN)
        for action in (UiAction.DECLARE_MANUAL_NOT_SENT, UiAction.ADOPT_MANUAL_ORDER):
            self.assertEqual(self.resolve(action, order.order_id).code, 'state_conflict')
        self.assertIs(self.case.engine.state.orders[-1].status, OrderStatus.UNKNOWN)

    def test_diagnostic_awaiting_its_cancel_receipt_is_not_declarable(self):
        self.assertTrue(self.case.service.execute(self.case.command(UiAction.TEST_SIM_ORDER, manual_order=self.form)).accepted)
        order = self.case.engine.state.orders[-1]
        self.assertFalse(self.case.service.snapshot(self.case.scope).pending.outcome_known)
        self.assertEqual(self.resolve(UiAction.DECLARE_MANUAL_NOT_SENT, order.order_id).code, 'state_conflict')
        self.assertIsNot(self.case.engine.state.orders[-1].status, OrderStatus.REJECTED)


class UnknownAmendTests(ReviewCase):
    def amend(self, request_id='amend-a', price=D('24990')):
        order = self.order('normal-a')
        return self.run_command(UiAction.AMEND_MANUAL, manual_mutation=self.mutation(request_id, order.order_id, price))

    def cancel(self, request_id='cancel-a'):
        order = self.order('normal-a')
        return self.run_command(UiAction.CANCEL_MANUAL, manual_mutation=self.mutation(request_id, order.order_id))

    def setUp(self):
        super().setUp()
        self.assertTrue(self.submit()[1].accepted)

    def test_amend_the_broker_did_not_apply_closes_on_observation_and_cancel_works(self):
        self.native.amend_mode = 'TIMEOUT'
        self.assertEqual(self.amend().code, 'outcome_unknown')
        self.assertFalse(self.pending().outcome_known)
        self.case.observe()
        closed = self.request('amend-a')
        self.assertEqual((closed.outcome_known, closed.status, closed.reason), (True, 'REJECTED', 'manual_amend_not_applied'))
        self.assertTrue(self.cancel().accepted)
        self.assertEqual(self.delta('cancel_order'), 1)
        self.case.observe()
        self.assertIs(self.order('normal-a').status, OrderStatus.CANCELED)

    def test_cancel_is_allowed_while_an_unknown_amend_is_still_open(self):
        self.native.amend_mode = 'TIMEOUT'
        self.assertEqual(self.amend().code, 'outcome_unknown')
        self.assertEqual(self.amend('amend-b', D('24980')).code, 'outcome_unknown')
        unconfirmed = ManualMutationForm(self.case.scope, 'cancel-a', self.order('normal-a').order_id)
        self.assertEqual(self.run_command(UiAction.CANCEL_MANUAL, manual_mutation=unconfirmed).code, 'manual_confirmation_required')
        self.assertEqual(self.delta('cancel_order'), 0)
        self.assertTrue(self.cancel().accepted)
        self.assertEqual(self.delta('cancel_order'), 1)
        self.case.observe()
        self.assertTrue(self.request('amend-a').outcome_known)

    def test_an_unknown_cancel_still_blocks_a_second_cancel(self):
        self.native.cancel_mode = 'TIMEOUT'
        self.assertEqual(self.cancel().code, 'outcome_unknown')
        self.assertFalse(self.cancel('cancel-b').accepted)
        self.assertEqual(self.delta('cancel_order'), 1)

    def test_unknown_cancel_the_broker_did_not_apply_recovers_and_can_be_retried(self):
        self.native.cancel_mode = 'TIMEOUT'
        self.assertEqual(self.cancel().code, 'outcome_unknown')
        self.assertIs(self.order('normal-a').status, OrderStatus.UNKNOWN)
        self.assertTrue(self.engine.state.stopped)
        self.native.cache_state = 'Degraded'  # a stale trade cache never recovers by guessing
        with self.assertRaises(DomainError):
            self.case.observe()
        self.assertIs(self.order('normal-a').status, OrderStatus.UNKNOWN)
        self.assertFalse(self.request('cancel-a').outcome_known)
        self.native.cache_state = 'Healthy'
        self.case.observe()
        self.assertIs(self.order('normal-a').status, OrderStatus.ACCEPTED)
        closed = self.request('cancel-a')
        self.assertEqual((closed.outcome_known, closed.reason), (True, 'manual_cancel_not_applied'))
        self.native.cancel_mode = 'Cancelled'
        self.assertTrue(self.cancel('cancel-b').accepted)
        self.assertEqual(self.delta('cancel_order'), 2)

    def test_unknown_cancel_the_broker_applied_closes_as_canceled(self):
        self.native.cancel_mode = 'TIMEOUT_APPLIED'
        self.assertEqual(self.cancel().code, 'outcome_unknown')
        self.case.observe()
        self.assertEqual((self.request('cancel-a').outcome_known, self.request('cancel-a').status), (True, 'CANCELED'))
        self.assertIs(self.order('normal-a').status, OrderStatus.CANCELED)
        self.assertEqual(self.delta('cancel_order'), 1)

    def test_amend_that_was_applied_despite_the_timeout_closes_as_amended(self):
        self.native.amend_mode = 'TIMEOUT_APPLIED'
        self.assertEqual(self.amend().code, 'outcome_unknown')
        self.case.observe()
        self.assertEqual(self.request('amend-a').status, 'AMENDED')

    def test_amend_with_no_price_evidence_stays_open(self):
        self.native.amend_mode = 'TIMEOUT'
        self.assertEqual(self.amend().code, 'outcome_unknown')
        observation = self.adapter.observe_manual('future-alias', 0)
        self.service.adopt((replace(observation, amended_prices=()),))
        self.assertFalse(self.request('amend-a').outcome_known)


class PreSdkRefusalTests(ReviewCase):
    def assert_engine_running(self, request_id):
        self.assertFalse(self.engine.state.stopped)
        self.assertFalse(book_for(self.engine, 'future-alias').halted)
        self.assertTrue(self.request(request_id).outcome_known)
        self.assertIsNone(self.pending())

    def test_domain_error_before_the_sdk_call_is_reported_as_is_and_does_not_stop(self):
        placed = 0
        with patch.object(self.adapter, 'resolve', side_effect=DomainError('instrument_unresolved')):
            _, receipt = self.submit()
        self.assertEqual(receipt.code, 'instrument_unresolved')
        self.assertEqual(self.delta('place_order'), placed)
        order = self.order('normal-a')
        self.assertIs(order.status, OrderStatus.REJECTED)
        self.assertEqual((order.reservation.cash, order.reservation.quantity), (0, 0))
        self.assertEqual(self.request('normal-a').reason, 'instrument_unresolved')
        self.assert_engine_running('normal-a')
        self.assertNotIn(order.order_id, self.adapter.orders)
        _, receipt = self.submit('normal-b')
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.delta('place_order'), placed + 1)

    def test_domain_error_from_the_facade_before_the_native_call_leaves_no_placeholder(self):
        plan = self.case.engine.state.orders[0].plan
        with patch.object(self.adapter.client, 'place_order', side_effect=DomainError('capability_missing')):
            with self.assertRaises(DomainError) as caught:
                self.adapter.submit(replace(plan, deadline=self.case.clock.now() + timedelta(seconds=30)), 'ghost-order')
        self.assertEqual(caught.exception.code, 'capability_missing')
        self.assertNotIn('ghost-order', self.adapter.orders)

    def test_sdk_exception_after_the_call_is_an_unknown_receipt_with_a_placeholder(self):
        plan = self.case.engine.state.orders[0].plan
        with patch.object(self.adapter.client, 'place_order', side_effect=TimeoutError('native')):
            receipt = self.adapter.submit(replace(plan, deadline=self.case.clock.now() + timedelta(seconds=30)), 'maybe-sent')
        self.assertIs(receipt.status, OrderStatus.UNKNOWN)
        self.assertIn('maybe-sent', self.adapter.orders)

    def test_cancel_refused_before_the_sdk_restores_the_order_and_does_not_stop(self):
        self.assertTrue(self.submit()[1].accepted)
        order = self.order('normal-a')
        with patch.object(self.adapter, 'cancel', side_effect=DomainError('state_conflict')):
            receipt = self.run_command(UiAction.CANCEL_MANUAL, manual_mutation=ManualMutationForm(self.case.scope, 'cancel-a', order.order_id, confirmed=True))
        self.assertEqual(receipt.code, 'state_conflict')
        self.assertIs(self.order('normal-a').status, OrderStatus.ACCEPTED)
        self.assert_engine_running('cancel-a')
        self.assertEqual(self.delta('cancel_order'), 0)
        retry = self.run_command(UiAction.CANCEL_MANUAL, manual_mutation=ManualMutationForm(self.case.scope, 'cancel-b', order.order_id, confirmed=True))
        self.assertTrue(retry.accepted, retry)
        self.assertEqual(self.delta('cancel_order'), 1)

    def test_amend_refused_before_the_sdk_does_not_stop(self):
        self.assertTrue(self.submit()[1].accepted)
        order = self.order('normal-a')
        with patch.object(self.adapter, 'amend', side_effect=DomainError('validation_failed')):
            receipt = self.run_command(
                UiAction.AMEND_MANUAL, manual_mutation=ManualMutationForm(self.case.scope, 'amend-a', order.order_id, D('24990'), confirmed=True)
            )
        self.assertEqual(receipt.code, 'validation_failed')
        self.assert_engine_running('amend-a')
        self.assertEqual(self.delta('update_order'), 0)

    def test_sdk_exception_after_the_cancel_call_is_still_unknown_and_halts(self):
        self.assertTrue(self.submit()[1].accepted)
        self.native.cancel_mode = 'TIMEOUT'
        order = self.order('normal-a')
        receipt = self.run_command(UiAction.CANCEL_MANUAL, manual_mutation=ManualMutationForm(self.case.scope, 'cancel-a', order.order_id, confirmed=True))
        self.assertEqual(receipt.code, 'outcome_unknown')
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.request('cancel-a').outcome_known)


class PriceDeviationAndExitAmendTests(ReviewCase):
    def preview(self, request_id, side, limit, stop):
        form = ManualOrderForm(self.case.scope, request_id, self.case.spec.instrument_id, side, 1, limit, stop)
        receipt = self.run_command(UiAction.PREVIEW_MANUAL, manual_order=form)
        self.assertTrue(receipt.accepted, receipt)
        return form, self.service.snapshot(self.case.scope).preview

    def test_marketable_limit_beyond_the_deviation_is_rejected_with_the_quote_shown(self):
        # bid 24999 / ask 25000; one percent of the opposite quote is the default limit.
        _, ok = self.preview('buy-ok', Side.BUY, D('25250'), D('25200'))
        self.assertTrue(ok.allowed, ok.reasons)
        self.assertEqual((ok.bid, ok.ask), (D('24999'), D('25000')))
        _, far = self.preview('buy-far', Side.BUY, D('25251'), D('25200'))
        self.assertEqual((far.allowed, far.reasons), (False, ('price_deviation',)))
        _, far = self.preview('sell-far', Side.SELL, D('24749'), D('24800'))
        self.assertEqual((far.allowed, far.reasons), (False, ('price_deviation',)))
        _, ok = self.preview('sell-ok', Side.SELL, D('24750'), D('24800'))
        self.assertTrue(ok.allowed, ok.reasons)

    def test_resting_limit_far_from_the_market_is_not_a_deviation(self):
        _, far = self.preview('buy-low', Side.BUY, D('22500'), D('22400'))
        self.assertTrue(far.allowed, far.reasons)

    def test_confirm_rechecks_the_deviation_against_the_current_quote(self):
        form, preview = self.preview('buy-a', Side.BUY, D('25000'), D('24950'))
        placed = 0
        self.case.clock.value += timedelta(seconds=1)
        now = self.case.clock.now()
        self.engine.quote(Quote(self.case.spec.instrument_id, D('24699'), D('24700'), D('24700'), now, now, now.date()))
        receipt = self.run_command(UiAction.SUBMIT_MANUAL, manual_order=replace(form, confirmed=True, preview_id=preview.preview_id))
        self.assertEqual(receipt.code, 'price_deviation')
        self.assertEqual(self.delta('place_order'), placed)

    def test_exit_order_can_be_amended_to_chase_the_market(self):
        self.assertTrue(self.submit()[1].accepted)
        self.native.fill(self.native.trades[-1], 1, D('25000'))
        self.case.observe()
        lot = self.engine.state.positions[-1]
        self.assertTrue(self.run_command(UiAction.FLATTEN, target_id=lot.lot_id).accepted)
        exit_order = self.engine.state.orders[-1]
        amended = self.run_command(
            UiAction.AMEND_MANUAL, manual_mutation=ManualMutationForm(self.case.scope, 'amend-exit', exit_order.order_id, D('24990'), confirmed=True)
        )
        self.assertTrue(amended.accepted, amended)
        self.assertEqual(self.delta('update_order'), 1)


if __name__ == '__main__':
    unittest.main()
