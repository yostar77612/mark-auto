"""Entry sizing fits the strategy's isolated risk budget instead of tripping risk_rejected."""

from decimal import Decimal
from types import SimpleNamespace
import unittest

from quantlab.trading.application.coordinator import fit_risk_budget
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Market, Side
from test_trading_adapters import instrument

D = Decimal


def engine_with(reservations=(), orders=()):
    return SimpleNamespace(fees=FeeSchedule.taiwan(), reservations=lambda: reservations, state=SimpleNamespace(orders=orders))


def record(allocation, risk_fraction):
    return SimpleNamespace(strategy_id='strategy-1', form=SimpleNamespace(allocation=D(allocation), risk_fraction=D(risk_fraction), direction=Side.BUY))


class EntryRiskFitTests(unittest.TestCase):
    def setUp(self):
        self.spec = instrument(Market.STOCK)
        self.price, self.stop = D('100'), D('97')

    def loss(self, quantity):
        return FeeSchedule.taiwan().loss_at_stop(self.spec, self.price, self.stop, quantity, Side.BUY)

    def test_size_shrinks_to_the_largest_whole_lots_inside_the_budget(self):
        budget = self.loss(3 * self.spec.lot_size) + D('1')
        fitted = fit_risk_budget(engine_with(), record(budget / D('0.02'), '0.02'), self.spec, self.price, self.stop, 10 * self.spec.lot_size)
        self.assertEqual(fitted, 3 * self.spec.lot_size)
        self.assertLessEqual(self.loss(fitted), budget)
        self.assertGreater(self.loss(fitted + self.spec.lot_size), budget)

    def test_a_size_that_already_fits_is_unchanged(self):
        fitted = fit_risk_budget(engine_with(), record('1000000', '0.5'), self.spec, self.price, self.stop, 2 * self.spec.lot_size)
        self.assertEqual(fitted, 2 * self.spec.lot_size)

    def test_a_budget_below_one_lot_gives_zero(self):
        fitted = fit_risk_budget(engine_with(), record('1000', '0.01'), self.spec, self.price, self.stop, 5 * self.spec.lot_size)
        self.assertEqual(fitted, 0)

    def test_risk_already_reserved_by_the_same_strategy_reduces_the_room(self):
        budget = self.loss(3 * self.spec.lot_size) + D('1')
        reserved = SimpleNamespace(reservation_id='order-1', risk=self.loss(2 * self.spec.lot_size))
        order = SimpleNamespace(order_id='order-1', plan=SimpleNamespace(strategy_id='strategy-1'))
        fitted = fit_risk_budget(
            engine_with((reserved,), (order,)), record(budget / D('0.02'), '0.02'), self.spec, self.price, self.stop, 10 * self.spec.lot_size
        )
        self.assertEqual(fitted, self.spec.lot_size)
        other = SimpleNamespace(order_id='order-1', plan=SimpleNamespace(strategy_id='someone-else'))
        unaffected = fit_risk_budget(
            engine_with((reserved,), (other,)), record(budget / D('0.02'), '0.02'), self.spec, self.price, self.stop, 10 * self.spec.lot_size
        )
        self.assertEqual(unaffected, 3 * self.spec.lot_size)


if __name__ == '__main__':
    unittest.main()
