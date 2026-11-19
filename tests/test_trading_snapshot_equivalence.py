"""OPT-1 P2: `views.snapshot` must return exactly the UiState of the frozen pre-change implementation."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from quantlab.trading.application import views
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.workflows import fill_local_pending, step
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderPlan, Side
from quantlab.trading.runtime.build import create_engine
from tests.trading_snapshot_reference import _reference_order_trading_day, reference_snapshot

D = Decimal


class SnapshotEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix='v2-snapshot-')
        self.root = Path(self.temp.name)
        self.engine = create_engine(self.root / 'platform')
        self.facade = LocalFacade(self.engine)

    def tearDown(self) -> None:
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.temp.cleanup()

    def command(self, action: UiAction, **values: object) -> None:
        receipt = self.facade.execute(UiCommand(action, self.engine.state.version, **values))
        self.assertTrue(receipt.accepted, receipt)

    def deploy(self, market: Market, direction: Side = Side.BUY) -> str:
        spec = next(s for s in self.engine.catalog.instruments if s.market is market)
        account = 'local-stock' if market is Market.STOCK else 'local-futures'
        form = StrategyForm(
            'snapshot-' + market.value,
            market,
            HoldingKind.SWING,
            3,
            5,
            direction,
            spec.instrument_id,
            account,
            Environment.LOCAL,
            D('30000'),
            D('0.02'),
            'BUY_AND_HOLD',
            '',
        )
        reference = self.facade.execute(UiCommand(UiAction.CREATE_STRATEGY, self.engine.state.version, strategy=form)).reference
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            self.command(action, target_id=reference)
        return reference

    def submit(self, reference: str, key: str) -> str:
        record = self.engine.strategy(reference)
        spec = self.engine.catalog.resolve(record.form.instrument_id)
        quote = self.engine.quotes[spec.instrument_id]
        price = quote.ask if record.form.direction is Side.BUY else quote.bid
        sign = 1 if record.form.direction is Side.BUY else -1
        now = self.engine.clock.now()
        plan = OrderPlan(
            key,
            record.form.account_ref,
            Environment.LOCAL,
            spec.instrument_id,
            record.strategy_id,
            record.version,
            record.form.direction,
            spec.lot_size,
            spec.unit,
            price,
            price - spec.tick_size * 10 * sign,
            False,
            now,
            now + timedelta(seconds=30),
            self.engine.state.version,
        )
        return self.engine.submit(plan, record.policy, key)

    def assertSameSnapshot(self) -> None:
        # repr() keeps Decimal exponents and tuple order, so this is stricter than dataclass equality.
        old = reference_snapshot(self.engine)
        new = views.snapshot(self.engine)
        self.assertEqual(new, old)
        self.assertEqual(repr(new), repr(old))

    def trading_state(self) -> None:
        self.command(UiAction.RECONCILE)
        self.command(UiAction.RESUME)
        stock, future = self.deploy(Market.STOCK), self.deploy(Market.INDEX_FUTURE)
        self.deploy(Market.STOCK_FUTURE)  # a deployed strategy without orders
        self.submit(stock, 'stock-entry')
        fill_local_pending(self.engine)
        step(self.engine, self.engine.history)
        self.command(UiAction.RESUME)
        self.submit(future, 'future-entry')  # accepted, unfilled order stays open

    def scale(self, copies: int) -> None:
        """Clone strategies, orders, lots and tracks under new identities (S x O growth for the old scans)."""
        state = self.engine.state
        strategies, orders, positions, tracks = list(state.strategies), list(state.orders), list(state.positions), list(state.performance_tracks)
        for copy in range(1, copies):
            for record in state.strategies:
                strategy_id = f'{record.strategy_id}-c{copy}'
                strategies.append(replace(record, strategy_id=strategy_id))
                orders.extend(
                    replace(order, order_id=f'{order.order_id}-c{copy}', plan=replace(order.plan, strategy_id=strategy_id))
                    for order in state.orders
                    if order.plan.strategy_id == record.strategy_id
                )
                positions.extend(
                    replace(lot, lot_id=f'{lot.lot_id}-c{copy}', strategy_id=strategy_id) for lot in state.positions if lot.strategy_id == record.strategy_id
                )
                tracks.extend(replace(track, strategy_id=strategy_id) for track in state.performance_tracks if track.strategy_id == record.strategy_id)
        self.engine.state = replace(state, strategies=tuple(strategies), orders=tuple(orders), positions=tuple(positions), performance_tracks=tuple(tracks))

    def test_fresh_unreconciled_and_empty_engines(self):
        self.assertSameSnapshot()  # not reconciled, no strategies, no orders
        self.command(UiAction.RECONCILE)
        self.command(UiAction.RESUME)
        self.assertSameSnapshot()

    def test_trading_state_with_positions_orders_and_tracks(self):
        self.trading_state()
        self.assertTrue(self.engine.state.orders and any(lot.quantity for lot in self.engine.state.positions))
        self.assertSameSnapshot()
        self.engine.clock.current += timedelta(minutes=2)  # quotes leave the 30 s freshness window
        self.assertSameSnapshot()

    def test_scaled_strategies_and_orders(self):
        self.trading_state()
        self.scale(25)
        self.assertGreater(len(self.engine.state.orders), 40)
        self.assertSameSnapshot()

    def test_unverified_financial_facts(self):
        self.trading_state()
        with patch.object(views, '_financial_facts_current', return_value=False):
            self.assertSameSnapshot()

    def test_orders_outside_every_session_and_on_session_boundaries(self):
        self.trading_state()
        state = self.engine.state
        sessions = self.engine.calendar.sessions
        moments = [sessions[0].opens_at, sessions[0].closes_at, sessions[-1].closes_at, sessions[0].opens_at - timedelta(days=400)]
        moments += [sessions[-1].closes_at + timedelta(days=400), sessions[1].opens_at - timedelta(seconds=1)]
        orders = list(state.orders)
        for index, moment in enumerate(moments):
            orders[index % len(orders)] = replace(
                orders[index % len(orders)], plan=replace(orders[index % len(orders)].plan, decision_at=moment, deadline=moment + timedelta(seconds=30))
            )
            self.engine.state = replace(state, orders=tuple(orders))
            with self.subTest(moment=moment.isoformat()):
                self.assertSameSnapshot()
        self.assertTrue(any(_reference_order_trading_day(self.engine, order) is None for order in self.engine.state.orders))

    def test_no_strategies_but_orders_and_deleted_strategy(self):
        self.trading_state()
        state = self.engine.state
        deleted = replace(state.strategies[0], state='DELETED')
        self.engine.state = replace(state, strategies=(deleted, *state.strategies[1:]))
        self.assertSameSnapshot()
        self.engine.state = replace(state, strategies=())
        self.assertSameSnapshot()


class SessionDayTests(unittest.TestCase):
    """The bisect lookup returns the first session the former linear scan found, including touching sessions."""

    def test_random_calendars_with_touching_and_gapped_sessions(self):
        generator = random.Random(20261120)
        start = datetime(2026, 1, 5, 0, 45, tzinfo=timezone.utc)
        for case in range(200):
            sessions, cursor = [], start
            for index in range(generator.randint(1, 25)):
                opens = cursor + timedelta(minutes=generator.choice((0, 0, 1, 30, 600)))  # 0 = touches the previous close
                closes = opens + timedelta(minutes=generator.choice((1, 5, 300)))
                sessions.append(TradingSession(date(2026, 1, 5) + timedelta(days=index), opens, closes, generator.choice(('DAY', 'NIGHT'))))
                cursor = closes
            calendar = TradingCalendar('bench', 'v1', 'test', tuple(sessions))
            probes = [start - timedelta(minutes=1), cursor + timedelta(minutes=1)]
            probes += [
                moment
                for session in sessions
                for moment in (session.opens_at, session.closes_at, session.opens_at + (session.closes_at - session.opens_at) / 2)
            ]
            probes += [session.opens_at - timedelta(microseconds=1) for session in sessions]
            starts = {}
            for moment in probes:
                expected = next((session.trade_date for session in calendar.sessions if session.opens_at <= moment <= session.closes_at), None)
                with self.subTest(case=case, moment=moment.isoformat()):
                    self.assertEqual(views._session_day(calendar, moment, starts), expected)


if __name__ == '__main__':
    unittest.main()
