"""Full local combinations for A03, H04 and R02; no production edits or mocks."""

from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import test_trading_application as support
from quantlab.trading.adapters.simulated.broker import FaultPlan
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.contracts import StrategyForm, UiAction
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.events import poll_events
from quantlab.trading.application.workflows import execute_day, fill_local_pending, mark_risk, step
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import create_engine


D = Decimal


class AcceptanceCombinationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = support.ApplicationLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    @property
    def engine(self):
        return self.fixture.engine

    def install_spec_data(self, spec) -> None:
        present = tuple(s for s in self.engine.catalog.instruments if s.instrument_id != spec.instrument_id)
        self.engine.catalog = Catalog((*present, spec))
        broker = self.engine.gateways['local-stock' if spec.market is Market.STOCK else 'local-futures']
        broker.instruments[spec.instrument_id] = spec

    def test_a03_data_only_new_stock_future_completes_shared_application_entry_and_exit(self) -> None:
        source = next(s for s in self.engine.catalog.instruments if s.market is Market.STOCK_FUTURE)
        added = replace(
            source,
            instrument_id='TAIFEX:2412F:202612',
            underlying='2412',
            version='A03-data-only-v1',
            source='LOCAL_SYNTHETIC_ACCEPTANCE_NOT_BROKER',
            margin=D('10000'),
        )
        self.install_spec_data(added)
        self.engine.history[added.instrument_id] = self.engine.history[source.instrument_id]
        current = self.engine.quotes[source.instrument_id]
        self.engine.quote(replace(current, instrument_id=added.instrument_id, source='LOCAL_SYNTHETIC_A03', sequence=self.engine.quote_count + 1))
        form = StrategyForm(
            'A03 added contract',
            Market.STOCK_FUTURE,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            added.instrument_id,
            'local-futures',
            Environment.LOCAL,
            D('30000'),
            D('0.02'),
            'BUY_AND_HOLD',
        )
        reference = self.fixture.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            self.fixture.command(action, target_id=reference)
        order_id, _ = self.fixture.submit(reference)
        fill_local_pending(self.engine)
        position = next(p for p in self.engine.state.positions if p.lot_id == order_id)
        self.assertEqual((position.instrument_id, position.quantity), (added.instrument_id, 1))
        self.assertIs(self.engine.risk().fees, self.engine.fees)
        self.assertIn(added.instrument_id, {v.instrument_id for v in self.fixture.facade.snapshot().markets})
        for _ in range(3):
            step(self.engine, self.engine.history)
        exit_id = self.engine.exit_lot(position.lot_id)
        self.assertIsNotNone(exit_id)
        fill_local_pending(self.engine)
        self.assertEqual(next(p for p in self.engine.state.positions if p.lot_id == order_id).quantity, 0)
        self.assertEqual(next(o for o in self.engine.state.orders if o.order_id == exit_id).status, OrderStatus.FILLED)
        self.assertGreater(self.engine.state.costs, 0)

    def test_h04_session_close_exits_intraday_only_and_keeps_swing_on_same_account(self) -> None:
        # Explicit local fixture margins leave enough real simulated account cash
        # for both positions; neither the 100k pool nor risk limits are changed.
        for spec in tuple(self.engine.catalog.instruments):
            if spec.market in (Market.INDEX_FUTURE, Market.STOCK_FUTURE):
                self.install_spec_data(replace(spec, margin=D('10000'), version='H04-local-margin-v1', source='LOCAL_SYNTHETIC_MARGIN_NOT_BROKER'))
        swing_ref = self.fixture.deploy(Market.INDEX_FUTURE)
        day_ref = self.fixture.deploy(Market.STOCK_FUTURE, kind=HoldingKind.INTRADAY, max_days=0)
        swing_id, _ = self.fixture.submit(swing_ref, key='h04-swing')
        day_id, _ = self.fixture.submit(day_ref, key='h04-intraday')
        fill_local_pending(self.engine)
        self.assertEqual(len([p for p in self.engine.state.positions if p.quantity]), 2)
        self.assertEqual({p.account_ref for p in self.engine.state.positions}, {'local-futures'})
        self.engine.clock.current = self.engine.calendar.day_session(self.engine.state.trading_day).closes_at
        for quote in tuple(self.engine.quotes.values()):
            self.engine.quote(replace(quote, source_at=self.engine.clock.now(), received_at=self.engine.clock.now(), sequence=self.engine.quote_count + 1))
        execute_day(self.engine, self.engine.history, allow_entries=False)
        swing = next(p for p in self.engine.state.positions if p.lot_id == swing_id)
        intraday = next(p for p in self.engine.state.positions if p.lot_id == day_id)
        self.assertEqual(swing.quantity, 1)
        self.assertEqual(swing.policy.kind, HoldingKind.SWING)
        self.assertEqual(intraday.quantity, 0)
        self.assertEqual({o.plan.exit_lot_id for o in self.engine.state.orders if o.plan.reduce_only}, {day_id})

    def test_r02_unknown_entry_cancel_cannot_suppress_legal_protective_exit(self) -> None:
        future_ref = self.fixture.deploy(Market.INDEX_FUTURE)
        stock_ref = self.fixture.deploy()
        future_id, _ = self.fixture.submit(future_ref, key='r02-owned-future')
        fill_local_pending(self.engine)
        unknown_id, _ = self.fixture.submit(stock_ref, key='r02-unknown-stock', fault=FaultPlan(unknown_after_accept=True))
        unknown = next(o for o in self.engine.state.orders if o.order_id == unknown_id)
        self.assertEqual(unknown.status, OrderStatus.UNKNOWN)
        held_cash, held_risk = unknown.reservation.cash, unknown.reservation.risk
        self.assertGreater(held_cash, 0)
        future_lot = next(p for p in self.engine.state.positions if p.lot_id == future_id)
        current = self.engine.quotes[future_lot.instrument_id]
        price = current.last - D('1100')
        self.engine.quote(replace(current, bid=price, ask=price + D('1'), last=price, sequence=self.engine.quote_count + 1))
        mark_risk(self.engine)
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.assertTrue(self.engine.state.stopped)
        still_unknown = next(o for o in self.engine.state.orders if o.order_id == unknown_id)
        self.assertEqual((still_unknown.reservation.cash, still_unknown.reservation.risk), (held_cash, held_risk))
        exits = [o for o in self.engine.state.orders if o.plan.exit_lot_id == future_id]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].status, OrderStatus.ACCEPTED)
        exit_order = exits[0]
        spec = self.engine.catalog.resolve(exit_order.plan.instrument_id)
        fee = self.engine.fees.transaction(spec, exit_order.plan.side, exit_order.plan.limit_price, exit_order.plan.quantity)
        self.engine.simulation.fill('local-futures', exit_order.order_id, exit_order.plan.quantity, exit_order.plan.limit_price, fee)
        self.engine.simulation.persist_remote()
        self.assertEqual(self.engine.gateways['local-futures'].remote_state.orders[exit_order.order_id].status, OrderStatus.FILLED)
        self.engine.gateways['local-stock'].connect('local-simulation', Environment.LOCAL)
        poll_events(self.engine)
        self.assertEqual(next(p for p in self.engine.state.positions if p.lot_id == future_id).quantity, 0)
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)

    def test_e06_parent_os_kill_before_submit_and_after_remote_accept_preserves_unknown(self) -> None:
        fixtures = []
        children = []
        records = []
        driver = Path(__file__).with_name('trading_crash_driver.py')
        try:
            for phase in ('before-submit', 'after-accept'):
                fixture = support.ApplicationLifecycleTests()
                fixture.setUp()
                fixtures.append(fixture)
                fixture.deploy()
                root = fixture.root / 'platform'
                marker = fixture.root / 'crash-ready.json'
                fixture.close_engine()
                child = subprocess.Popen(
                    [sys.executable, str(driver), str(root), phase, str(marker)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
                children.append(child)
                deadline = time.monotonic() + 15
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists(), f'owned crash driver failed at {phase}; exit={child.poll()}')
                record = json.loads(marker.read_text(encoding='utf-8'))
                self.assertEqual(record['pid'], child.pid)
                self.assertEqual(record['local_status'], 'SUBMITTING')
                self.assertEqual(record['remote_orders'], 0 if phase == 'before-submit' else 1)
                records.append(record)
            for child in children:
                child.kill()  # Actual parent-issued OS termination, never os._exit.
            for child in children:
                self.assertNotEqual(child.wait(timeout=5), 0)
            for fixture in fixtures:
                with self.assertRaises(DomainError) as refused:
                    create_engine(fixture.root / 'platform')
                self.assertEqual(refused.exception.code, 'ownership_conflict')
            started = time.monotonic()
            waiting = list(zip(fixtures, records))
            while waiting and time.monotonic() - started < 35:
                self._recover_killed(waiting)
                if waiting:
                    time.sleep(0.2)
            self.assertFalse(waiting, 'real lease did not expire within the 35 second bound')
            print('OS_CRASH_EVIDENCE ' + json.dumps({'lease_wait_seconds': time.monotonic() - started, 'scenarios': records}, sort_keys=True))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
            for fixture in fixtures:
                fixture.tearDown()

    def _recover_killed(self, waiting) -> None:
        for fixture, record in tuple(waiting):
            try:
                engine = create_engine(fixture.root / 'platform')
            except DomainError as exc:
                if exc.code != 'ownership_conflict':
                    raise
                continue
            fixture.engine, fixture.facade = engine, LocalFacade(engine)
            order = engine.state.orders[0]
            self.assertEqual(order.status, OrderStatus.UNKNOWN)
            self.assertTrue(engine.state.stopped)
            self.assertFalse(engine.state.reconciled)
            self.assertEqual(order.reservation.cash, D(record['reserved_cash']))
            self.assertEqual(order.reservation.risk, D(record['reserved_risk']))
            broker = engine.gateways['local-stock']
            self.assertEqual(len(broker.remote_state.orders), record['remote_orders'])
            self.assertEqual(broker.submission_count, 0)
            fixture.command(UiAction.RECONCILE, accepted=record['phase'] == 'after-accept')
            expected = OrderStatus.ACCEPTED if record['phase'] == 'after-accept' else OrderStatus.UNKNOWN
            self.assertEqual(engine.state.orders[0].status, expected)
            self.assertTrue(engine.state.stopped)
            self.assertEqual(broker.submission_count, 0)
            record.update(recovered_status=expected.value, resubmitted=0, startup_stopped=True)
            waiting.remove((fixture, record))


if __name__ == '__main__':
    unittest.main()
