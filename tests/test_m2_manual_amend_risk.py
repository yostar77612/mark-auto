"""Manual entry amendments share adopted account limits before native mutation."""

from decimal import Decimal as D
import unittest

import test_manual_trading as manual

from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.manual_contracts import ManualMutationForm
from quantlab.trading.domain.models import Side
from quantlab.trading.domain.risk import AccountRiskLimits


class ManualAmendAccountRiskTests(unittest.TestCase):
    def setUp(self):
        self.case = manual.ManualCoreTests()
        self.case.setUp()
        self.addCleanup(self.case.owner.close)
        self.case.confirm_test()
        self.save_limit(D('250000'))

    def save_limit(self, notional):
        case = self.case
        receipt = LocalFacade(case.engine).execute(
            UiCommand(
                UiAction.SAVE_ACCOUNT_RISK,
                case.engine.state.version,
                account_ref=case.scope.account_ref,
                account_risk=AccountRiskLimits(case.scope.account_ref, max_order_notional=notional),
            )
        )
        self.assertTrue(receipt.accepted, receipt)

    def submit_short(self, price=D('25000')):
        case = self.case
        form, preview = case.normal('short-entry', side=Side.SELL, limit_price=price, stop_price=D('25050'))
        self.assertTrue(preview.allowed, preview.reasons)
        receipt = case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        case.observe()
        return receipt.reference

    def amend(self, order_id, price):
        case = self.case
        return case.service.execute(
            case.command(
                UiAction.AMEND_MANUAL,
                manual_mutation=ManualMutationForm(case.scope, 'amend-a', order_id, price, confirmed=True),
            )
        )

    def native_amends(self):
        return sum(row[0] == 'update_order' for row in self.case.native._seen)

    def test_sell_entry_amendment_cannot_increase_notional_over_account_cap(self):
        order_id = self.submit_short()
        before = self.native_amends()
        receipt = self.amend(order_id, D('25001'))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'account_order_limit')
        self.assertEqual(self.native_amends(), before)
        self.assertTrue(self.case.engine.state.stopped)
        self.assertIn('account_order_limit', self.case.engine.state.issues)
        self.assertEqual(self.case.engine.state.account_daily_locks, ())

    def test_sell_entry_amendment_exactly_at_account_cap_is_allowed(self):
        order_id = self.submit_short(D('24999'))
        before = self.native_amends()
        receipt = self.amend(order_id, D('25000'))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.native_amends(), before + 1)

    def test_protective_exit_amendment_remains_allowed_above_account_cap(self):
        self.submit_short()
        case = self.case
        case.native.fill(case.native.trades[-1], 1, D('25000'))
        case.observe()
        self.save_limit(D('1'))
        lot = case.engine.state.positions[-1]
        flattened = case.service.execute(case.command(UiAction.FLATTEN, target_id=lot.lot_id))
        self.assertTrue(flattened.accepted, flattened)
        order = case.engine.state.orders[-1]
        self.assertTrue(order.plan.reduce_only)
        before = self.native_amends()
        receipt = self.amend(order.order_id, D('25001'))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.native_amends(), before + 1)


if __name__ == '__main__':
    unittest.main()
