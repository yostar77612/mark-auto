"""A real stalled research child cannot hold the trading writer or stop control."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep
import unittest

from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.research import research
from quantlab.trading.application.workflows import fill_local_pending
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderPlan, Side
from quantlab.trading.runtime.build import create_engine
from quantlab.trading.runtime.research_worker import SpawnResearchRunner, WorkerFault


class ResearchIsolationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[2] / 't'
        parent.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=parent, prefix='research-isolation-')
        self.engine = create_engine(Path(self.temp.name))
        self.facade = LocalFacade(self.engine)

    def tearDown(self):
        self.engine.research_runner.close()
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.temp.cleanup()

    def command(self, action, **kwargs):
        result = self.facade.execute(UiCommand(action, self.engine.state.version, **kwargs))
        self.assertTrue(result.accepted, result)
        return result

    def strategy(self, instrument, market, account):
        form = StrategyForm(
            'isolation', market, HoldingKind.SWING, 3, 5, Side.BUY, instrument, account, Environment.LOCAL, Decimal('30000'), Decimal('.02'), 'BUY_AND_HOLD'
        )
        reference = self.command(UiAction.CREATE_STRATEGY, strategy=form).reference
        self.command(UiAction.VALIDATE, target_id=reference)
        return reference

    def test_stalled_real_child_allows_protective_exit_and_priority_stop(self):
        engine = self.engine
        reference = self.strategy('TAIFEX:TMF:202612', Market.INDEX_FUTURE, 'local-futures')
        self.command(UiAction.RESEARCH, target_id=reference)
        self.command(UiAction.DEPLOY, target_id=reference)
        self.command(UiAction.RECONCILE)
        self.command(UiAction.RESUME)
        spec = engine.catalog.resolve('TAIFEX:TMF:202612')
        quote = engine.quotes[spec.instrument_id]
        plan = OrderPlan(
            'isolation-entry',
            'local-futures',
            Environment.LOCAL,
            spec.instrument_id,
            'strategy-1',
            1,
            Side.BUY,
            1,
            spec.unit,
            quote.ask,
            quote.ask - 10,
            False,
            engine.clock.now(),
            engine.clock.now() + timedelta(seconds=30),
            engine.state.version,
        )
        engine.submit(plan, engine.strategy(reference).policy, 'isolation-entry')
        fill_local_pending(engine)
        second = self.strategy('TWSE:DEMO01', Market.STOCK, 'local-stock')
        runner = SpawnResearchRunner(max_seconds=10, diagnostic_fault=WorkerFault.STALL_AFTER_DECODE)
        engine.research_runner = runner
        replies = []
        thread = Thread(target=lambda: replies.append(self.facade.execute(UiCommand(UiAction.RESEARCH, engine.state.version, second))))
        thread.start()
        try:
            deadline = monotonic() + 5
            while not runner.last_child_ready and thread.is_alive() and monotonic() < deadline:
                sleep(0.01)
            self.assertTrue(runner.last_child_ready, 'a real decoded child must be stalled before testing protection')
            started = monotonic()
            engine.quote(replace(quote, bid=plan.stop_price - 2, ask=plan.stop_price - 1, last=plan.stop_price - 2, sequence=quote.sequence + 100))
            self.command(UiAction.STOP_NEW)
            self.assertLess(monotonic() - started, 0.3)
            self.assertTrue(engine.state.stopped)
            self.assertTrue(any(o.plan.reduce_only for o in engine.state.orders))
            self.assertTrue(thread.is_alive(), 'research must still be separate while controls succeed')
        finally:
            runner.close()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(runner.last_cleanup_verified)
        self.assertFalse(replies[0].accepted)

    def test_same_version_cost_and_calendar_changes_invalidate_fingerprint(self):
        reference = self.strategy('TWSE:2330', Market.STOCK, 'local-stock')
        engine = self.engine
        record, spec = engine.strategy(reference), engine.catalog.resolve('TWSE:2330')
        bars = tuple(b for b in engine.history[spec.instrument_id] if spec.effective_at <= b.opened_at and b.available_at < engine.clock.now())
        first = research(record, spec, engine.calendar, bars, engine.fees, source_profile=engine.profile)
        fees = replace(engine.fees, buy_rate=Decimal('.002'))
        changed_fee = research(record, spec, engine.calendar, bars, fees, source_profile=engine.profile)
        sessions = list(engine.calendar.sessions)
        sessions[0] = replace(sessions[0], closes_at=sessions[0].closes_at + timedelta(minutes=1))
        calendar = replace(engine.calendar, sessions=tuple(sessions))
        changed_calendar = research(record, spec, calendar, bars, engine.fees, source_profile=engine.profile)
        self.assertNotEqual(first.fingerprint, changed_fee.fingerprint)
        self.assertNotEqual(first.fingerprint, changed_calendar.fingerprint)
        self.assertEqual(first.source_digest, engine.profile.source_digest)


if __name__ == '__main__':
    unittest.main()
