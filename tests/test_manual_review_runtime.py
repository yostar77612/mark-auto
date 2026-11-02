"""Owner-confirmed resolution of unknown submissions through the real bundle, codec and dispatch."""

from dataclasses import replace
from decimal import Decimal
import unittest

import test_manual_runtime_integration as integration
from test_manual_review_fixes import ReviewSDK
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualMutationForm, ManualOrderForm
from quantlab.trading.domain.models import Side
from quantlab.trading.runtime.protocol import Operation

D = Decimal


class RuntimeResolutionTests(unittest.TestCase):
    def setUp(self):
        self.case = case = integration.ManualRuntimeIntegrationTests('setUp')
        case.sdk_class = ReviewSDK
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.native = case.native
        case.ready()
        prepared = case.request(Operation.COMMAND, case.command(UiAction.TEST_SIM_ORDER))
        preview = prepared.state.manual.preview
        form = ManualOrderForm(
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
        self.assertTrue(case.request(Operation.COMMAND, case.command(UiAction.TEST_SIM_ORDER, manual_order=form)).receipt.accepted)
        case.bundle.poll_ports()
        self.assertEqual(case.state().manual.test_status, 'PASSED')
        self.placed = self.count('place_order')

    def count(self, name):
        return [row[0] for row in self.native._seen].count(name)

    def send(self, action, **fields):
        return self.case.request(Operation.COMMAND, self.case.command(action, **fields)).receipt

    def submit_unknown(self):
        scope = self.case.state().manual.scope
        order = ManualOrderForm(scope, 'unknown-request', self.case.spec.instrument_id, Side.BUY, 1, D('25000'), D('24950'))
        prepared = self.case.request(Operation.COMMAND, self.case.command(UiAction.PREVIEW_MANUAL, manual_order=order))
        order = replace(order, confirmed=True, preview_id=prepared.state.manual.preview.preview_id)
        self.assertEqual(self.send(UiAction.SUBMIT_MANUAL, manual_order=order).code, 'outcome_unknown')
        self.case.bundle.poll_ports()
        self.assertEqual(self.case.bundle.manual_runtime.error, '')
        return self.case.state().manual

    def resolve(self, action, manual, **fields):
        form = ManualMutationForm(manual.scope, 'resolve-' + action.value, manual.pending.order_id, confirmed=True)
        return self.send(action, manual_mutation=form, **fields)

    def resume(self):
        manual = self.case.state().manual
        return self.send(UiAction.RESUME, manual_book=ManualBookForm(manual.scope, manual.capital, True))

    def test_declared_not_sent_recovers_the_book_without_a_resend(self):
        self.native.lose_order = True
        manual = self.submit_unknown()
        self.assertEqual((manual.pending.candidates, manual.can_submit), ((), False))
        receipt = self.resolve(UiAction.DECLARE_MANUAL_NOT_SENT, manual)
        self.assertTrue(receipt.accepted, receipt)
        self.case.bundle.poll_ports()
        self.assertTrue(self.resume().accepted)
        self.assertTrue(self.case.state().manual.can_submit)
        self.assertEqual(self.count('place_order'), self.placed + 1)

    def test_adopted_broker_order_recovers_the_book_without_a_resend(self):
        self.native.place_mode, self.native.drop_tag = 'TIMEOUT', True
        manual = self.submit_unknown()
        self.assertEqual(manual.pending.candidates, ('sdk-2',))
        receipt = self.resolve(UiAction.ADOPT_MANUAL_ORDER, manual, target_id='sdk-2')
        self.assertTrue(receipt.accepted, receipt)
        self.case.bundle.poll_ports()
        self.assertTrue(self.case.state().manual.last_result.outcome_known)
        self.assertTrue(self.resume().accepted)
        self.assertEqual(self.count('place_order'), self.placed + 1)

    def test_tagged_broker_order_is_found_without_any_owner_action(self):
        self.native.place_mode = 'TIMEOUT'
        self.submit_unknown()
        self.assertTrue(self.case.state().manual.last_result.outcome_known)
        self.assertTrue(self.resume().accepted)


if __name__ == '__main__':
    unittest.main()
