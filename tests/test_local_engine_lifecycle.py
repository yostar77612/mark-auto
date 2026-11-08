"""Whole LOCAL simulation lifecycle through the real runtime bundle: create, validate, research, deploy, reconcile, resume, step.

No broker, no network, no credentials. It guards the owner-visible promise that an activated strategy keeps running
through simulated days instead of silently stopping the engine.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from quantlab.trading.application.contracts import StrategyForm, StrategyParameters, UiAction, UiCommand
from quantlab.trading.domain.models import Environment, HoldingKind, Market, Side
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.protocol import Operation, Request
from quantlab.trading.runtime.server import _dispatch


class LocalEngineLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.bundle = build_runtime(RuntimeLaunch(Path(self.temp.name)))
        self.addCleanup(self.bundle.close)

    def request(self, operation, command=None):
        return _dispatch(
            self.bundle,
            Request(uuid4().hex, self.bundle.launch.environment, 'local-stock', datetime.now(timezone.utc) + timedelta(seconds=10), operation, command),
        )

    def state(self):
        return self.request(Operation.SNAPSHOT).state

    def act(self, action, target='', **fields):
        receipt = self.request(Operation.COMMAND, UiCommand(action, self.state().version, target, **fields)).receipt
        self.assertTrue(receipt.accepted, f'{action.value}: {receipt.code} {receipt.message}')
        return receipt

    def form(self, **overrides):
        values = dict(
            name='lifecycle',
            market=Market.STOCK,
            holding_kind=HoldingKind.SWING,
            min_days=3,
            max_days=5,
            direction=Side.BUY,
            instrument_id='TWSE:2330',
            account_ref='local-stock',
            environment=Environment.LOCAL,
            allocation=Decimal('60000'),
            risk_fraction=Decimal('0.02'),
        )
        values.update(overrides)
        return StrategyForm(**values)

    def test_activated_strategy_survives_simulated_days(self):
        # Entry amount above the isolated allocation: sizing must still fit the strategy's risk budget.
        parameters = StrategyParameters('1d', Decimal('0.03'), Decimal('100000'))
        reference = self.act(UiAction.CREATE_TYPED_STRATEGY, strategy=self.form(), strategy_parameters=parameters).reference
        self.act(UiAction.VALIDATE, reference)
        self.act(UiAction.RESEARCH, reference)
        self.act(UiAction.DEPLOY, reference)
        self.act(UiAction.RECONCILE)
        self.act(UiAction.CHECK_PREFLIGHT, account_ref='local-stock')
        self.act(UiAction.RESUME)
        for _ in range(8):
            self.act(UiAction.STEP)
            self.assertEqual(self.state().engine_state, 'RUNNING', self.state().issues)
        final = self.state()
        self.assertEqual(final.issues, ())
        self.assertTrue(final.orders, 'the activated strategy never placed a simulated order')
        self.assertTrue(all(order.filled for order in final.orders))

    def test_performance_holding_days_cover_only_open_positions(self):
        parameters = StrategyParameters('1d', Decimal('0.03'), Decimal('100000'))
        reference = self.act(UiAction.CREATE_TYPED_STRATEGY, strategy=self.form(), strategy_parameters=parameters).reference
        for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
            self.act(action, reference)
        self.act(UiAction.RECONCILE)
        self.act(UiAction.CHECK_PREFLIGHT, account_ref='local-stock')
        self.act(UiAction.RESUME)
        for _ in range(20):
            self.act(UiAction.STEP)
        final = self.state()
        lots = self.bundle.engine.state.positions
        open_lots = [lot for lot in lots if lot.quantity]
        self.assertGreater(len(lots), len(open_lots), 'scenario must include closed lots')
        ages = [age for age in final.performance[0].holding_days.split(',') if age]
        self.assertEqual(len(ages), len(open_lots))


if __name__ == '__main__':
    unittest.main()
