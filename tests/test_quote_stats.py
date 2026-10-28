"""Quote calculation contracts and liquidation wiring; no broker or UI behavior."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from quantlab.trading.application.performance import unrealized_liquidation
from quantlab.trading.domain.models import HoldingPolicy, InstrumentSpec, Market, PositionLot, QuantityUnit, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.quote_stats import TradeDateClose, quote_stats, reference_price, unrealized_pnl

D = Decimal
NOW = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)


def spec_for(name='TMF', multiplier='10', market=Market.INDEX_FUTURE):
    return InstrumentSpec(
        name,
        market,
        'TWD',
        QuantityUnit.SHARE if market is Market.STOCK else QuantityUnit.CONTRACT,
        1,
        D(multiplier),
        D('1'),
        name,
        'v1',
        'SYNTHETIC',
        NOW,
        expiry=None if market is Market.STOCK else date(2026, 11, 18),
        delivery_month=None if market is Market.STOCK else '202611',
    )


class LiquidationCharacterizationTests(unittest.TestCase):
    def test_executable_side_costs_zero_and_stale_boundary(self):
        spec = spec_for(multiplier='50')
        base = PositionLot('lot', 'account', spec.instrument_id, 'strategy', 1, HoldingPolicy(), 2, D('100'), NOW.date(), 2)
        for direction, quantity, age, missing, expected in (
            (Side.BUY, 2, 0, False, D('193')),
            (Side.SELL, 2, 30, False, D('-307')),
            (Side.BUY, 0, 100, True, D('0')),
            (Side.BUY, 2, 30.001, False, None),
            (Side.BUY, 2, -1, False, None),
            (Side.BUY, 2, 0, True, None),
        ):
            with self.subTest(direction=direction, quantity=quantity, age=age, missing=missing):
                at = NOW - timedelta(seconds=age)
                quote = Quote(spec.instrument_id, D('102'), D('103'), D('102'), at, at, NOW.date())
                engine = SimpleNamespace(
                    catalog=SimpleNamespace(resolve=Mock(return_value=spec)),
                    quotes={} if missing else {spec.instrument_id: quote},
                    clock=SimpleNamespace(now=lambda: NOW),
                    fees=SimpleNamespace(transaction=Mock(return_value=D('3')), slippage=Mock(return_value=D('4'))),
                )
                lot = replace(base, direction=direction, quantity=quantity, sellable_quantity=quantity)
                if expected is None:
                    with self.assertRaises(DomainError) as caught:
                        unrealized_liquidation(engine, lot)
                    self.assertEqual(caught.exception.code, 'stale_quote')
                else:
                    self.assertEqual(unrealized_liquidation(engine, lot), expected)
                    if quantity:
                        price, side = (D('102'), Side.SELL) if direction is Side.BUY else (D('103'), Side.BUY)
                        engine.fees.transaction.assert_called_once_with(spec, side, price, quantity)
                        engine.fees.slippage.assert_called_once_with(spec, quantity, legs=1, prices=(price,))


class QuoteStatsTests(unittest.TestCase):
    def test_calendar_selected_previous_close_and_decimal_changes(self):
        # Monday's calendar-selected previous trade date is Friday. Futures'
        # Monday trade date begins with Friday's night session; calendar days
        # cannot select the reference. Stock uses the same supplied date rule.
        friday, monday = date(2026, 10, 23), date(2026, 10, 26)
        closes = (
            TradeDateClose(friday, D('99'), NOW - timedelta(days=5)),
            TradeDateClose(friday, D('100'), NOW - timedelta(days=4)),
            TradeDateClose(monday, D('999'), NOW),
        )
        for instrument, price, change, percent in (
            ('TMF', D('102.5'), D('2.5'), D('2.5')),
            ('TX', D('99.25'), D('-.75'), D('-.75')),
            ('STOCK', D('100'), D('0'), D('0')),
        ):
            with self.subTest(instrument=instrument):
                result = quote_stats(price, friday, closes)
                self.assertEqual((result.reference_price, result.change, result.change_percent), (D('100'), change, percent))
                self.assertIsInstance(result.change, D)
                self.assertIsInstance(result.change_percent, D)
        for missing in ((), (closes[-1],)):
            with self.subTest(missing=missing):
                self.assertIsNone(reference_price(friday, missing))
                result = quote_stats(D('10'), friday, missing)
                self.assertEqual((result.reference_price, result.change, result.change_percent), (None, None, None))

    def test_pnl_uses_only_spec_multiplier_and_quote_liveness(self):
        for spec, quantity, cost, expected in (
            (spec_for('TMF', '10'), 2, D('2000'), D('200')),
            (spec_for('TX', '200'), 2, D('40000'), D('4000')),
            (spec_for('STOCK', '1', Market.STOCK), 1000, D('100000'), D('10000')),
            (spec_for('SHORT', '10'), -2, D('-2000'), D('-200')),
        ):
            with self.subTest(instrument=spec.instrument_id):
                self.assertEqual(unrealized_pnl(D('110'), quantity, spec, cost, freshness=Freshness.LIVE), expected)
                for freshness in (Freshness.DELAYED, Freshness.STOPPED, Freshness.CLOSED, Freshness.UNKNOWN):
                    with self.subTest(freshness=freshness):
                        self.assertIsNone(unrealized_pnl(D('110'), quantity, spec, cost, freshness=freshness))


if __name__ == '__main__':
    unittest.main()
