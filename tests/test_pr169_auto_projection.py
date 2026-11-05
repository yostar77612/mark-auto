"""PR #169 review: bounded auto-strategy projection, build capability, retire guard."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from quantlab.trading.application.auto_strategy_service import (
    compact_auto_projection,
    compact_evaluations,
    compact_record,
    execute_auto_strategy,
    restarted_auto_records,
)
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import AutoStrategyCommand, UiAction, UiCommand
from quantlab.trading.application.daily_retention import compact_daily_projection
from quantlab.trading.application.promotion_service import PromotionEvaluation, PromotionService, needs_restart_pause
from quantlab.trading.application.research import ResearchTrade
from quantlab.trading.domain.models import Environment, OrderStatus
from quantlab.trading.domain.promotion import PauseReason, RunState, Stage, StageState
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import create_engine
from tests.test_m3_candidate_intake import request as build_request
from tests.test_m3_promotion_service import DAY, NOW, MemoryJournal, built, observation

D = Decimal


def with_trades(row, count):
    trades = tuple(ResearchTrade(i, i + 1, 1, D('100'), D('101'), D('10'), D('2')) for i in range(count))
    directions = (row.evidence.trade_directions[0],) * count
    return replace(row, evidence=replace(row.evidence, trades=trades, trade_directions=directions))


class CompactionTests(unittest.TestCase):
    def test_record_compaction_is_bounded_idempotent_and_change_detecting(self):
        big = with_trades(built(), 4000)
        small = compact_record(big)
        self.assertEqual(small.evidence.trades, ())
        self.assertEqual(small.evidence.completed_trades, 4000)
        self.assertEqual(compact_record(small), small)
        self.assertLess(len(dumps(small)), 5000)
        self.assertGreater(len(dumps(big)), 100 * len(dumps(small)))
        self.assertEqual(loads(dumps(small)), small)
        changed = compact_record(with_trades(built(), 3999))
        self.assertNotEqual(small.evidence.trades_digest, changed.evidence.trades_digest)

    def test_service_guards_still_detect_changed_trades_against_compact_record(self):
        journal = MemoryJournal()
        service = PromotionService(journal, Environment.BROKER_SIMULATION, now=NOW)
        service.record_built(built(), now=NOW)
        compact = compact_record(service.record('auto-1', 1))
        projected = PromotionService.from_projection(journal, Environment.BROKER_SIMULATION, (compact,), (), sequence=1)
        full = service.record('auto-1', 1).evidence
        # Identical full evidence is a no-op; altered trades are refused.
        self.assertEqual(projected.refresh_evidence('auto-1', 1, full, now=NOW), compact)
        with self.assertRaises(DomainError) as error:
            projected.refresh_evidence('auto-1', 1, replace(full, trades=()), now=NOW)
        self.assertEqual(error.exception.code, 'auto_evidence_changed')

    def test_one_evaluation_per_strategy_version_epoch(self):
        row = built()
        verdict = None
        service = PromotionService(MemoryJournal(), Environment.BROKER_SIMULATION, now=NOW)
        service.record_built(row, now=NOW)
        service.start_sim('auto-1', 1, trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)
        verdict = service.evaluate_after_close('auto-1', 1, DAY + timedelta(days=1), observation(), observation_started_on=DAY, now=NOW)
        items = []
        for offset in range(1, 40):
            items.append(PromotionEvaluation('auto-1', 1, DAY + timedelta(days=offset), DAY, observation(), verdict, NOW))
        other_epoch = PromotionEvaluation('auto-1', 1, DAY + timedelta(days=50), DAY + timedelta(days=50), observation(), verdict, NOW)
        kept = compact_evaluations((*items, other_epoch))
        self.assertEqual(kept, (items[-1], other_epoch))

    def test_older_date_after_pruning_is_refused_not_reevaluated(self):
        journal = MemoryJournal()
        service = PromotionService(journal, Environment.BROKER_SIMULATION, now=NOW)
        service.record_built(built(), now=NOW)
        service.start_sim('auto-1', 1, trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)
        verdict = service.evaluate_after_close('auto-1', 1, DAY + timedelta(days=5), observation(), observation_started_on=DAY, now=NOW)
        row = service.record('auto-1', 1)
        item = PromotionEvaluation('auto-1', 1, DAY + timedelta(days=5), DAY, observation(), verdict, row.observation_started_at)
        fresh = PromotionService.from_projection(journal, Environment.BROKER_SIMULATION, (row,), (item,), sequence=9)
        self.assertEqual(fresh.evaluate_after_close('auto-1', 1, DAY + timedelta(days=5), observation(), observation_started_on=DAY, now=NOW), verdict)
        with self.assertRaises(DomainError) as error:
            fresh.evaluate_after_close('auto-1', 1, DAY + timedelta(days=2), observation(), observation_started_on=DAY, now=NOW)
        self.assertEqual(error.exception.code, 'validation_failed')

    def test_restart_rule_is_shared(self):
        running = replace(built(), state=StageState(Stage.BROKER_SIM, RunState.RUNNING, None), eligible=True)
        backtest = built()
        self.assertTrue(needs_restart_pause(running))
        self.assertFalse(needs_restart_pause(backtest))
        paused = restarted_auto_records((running, backtest), Environment.BROKER_SIMULATION)
        self.assertEqual(paused[0].state.pause_reason, PauseReason.RESTART)
        self.assertFalse(paused[0].eligible)
        self.assertEqual(paused[1], backtest)
        journal = MemoryJournal()
        service = PromotionService(journal, Environment.BROKER_SIMULATION, now=NOW)
        service.record_built(built(), now=NOW)
        service.start_sim('auto-1', 1, trade_date=DAY, reproduced_behavior_hash='behavior', preopen_checks_passed=True, now=NOW)
        replayed = PromotionService(journal, Environment.BROKER_SIMULATION, now=NOW)
        self.assertEqual(replayed.record('auto-1', 1).state, restarted_auto_records((service.record('auto-1', 1),), Environment.BROKER_SIMULATION)[0].state)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pr169-')
        self.root = Path(self.temp.name)
        self.engine = create_engine(self.root)
        self.row = built(account_ref='local-futures')

    def tearDown(self):
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.temp.cleanup()

    def command(self, action, **changes):
        data = dict(
            action=action,
            expected_version=self.engine.state.version,
            account_ref='local-futures',
            environment=self.engine.configuration.environment,
            auto_strategy=AutoStrategyCommand('auto-1', 1, self.row.auto.frozen_hash, True),
        )
        data.update(changes)
        return UiCommand(**data)

    def test_old_full_evidence_journal_is_compacted_on_restart(self):
        big = with_trades(self.row, 3000)
        self.engine._persist('legacy_full_projection', replace(self.engine.state, auto_strategies=(big,)))
        self.assertGreater(len(dumps(self.engine.state)), 100_000)
        self.engine.journal.close()
        self.engine.simulation.ledger.close()
        self.engine = create_engine(self.root)
        self.assertEqual(self.engine.state.auto_strategies, (compact_record(big),))
        self.assertLess(len(dumps(self.engine.state)), 100_000)
        # Daily-retention path is a no-op once compact, and compacts in any environment.
        self.assertIs(compact_auto_projection(self.engine.state), self.engine.state)
        legacy = replace(self.engine.state, auto_strategies=(big,))
        self.assertEqual(compact_daily_projection(self.engine, legacy).auto_strategies, (compact_record(big),))

    def test_build_refuses_account_without_index_future_capability(self):
        runtime = Mock()
        self.engine.auto_runtime = runtime
        version = self.engine.state.version
        with self.assertRaises(DomainError) as error:
            execute_auto_strategy(
                self.engine,
                self.command(
                    UiAction.BUILD_AUTO_STRATEGY, account_ref='local-stock', auto_strategy=None, auto_build=replace(build_request(), account_ref='local-stock')
                ),
            )
        self.assertEqual(error.exception.code, 'capability_missing')
        runtime.build.assert_not_called()
        self.assertEqual(self.engine.state.version, version)

    def test_build_proceeds_for_futures_account(self):
        runtime = Mock()
        self.engine.auto_runtime = runtime
        execute_auto_strategy(
            self.engine, self.command(UiAction.BUILD_AUTO_STRATEGY, auto_strategy=None, auto_build=replace(build_request(), account_ref='local-futures'))
        )
        runtime.build.assert_called_once()

    def test_retire_refuses_every_active_order_status(self):
        from quantlab.trading.application.state import ACTIVE

        row = replace(self.row, state=StageState(Stage.BROKER_SIM, RunState.RUNNING, None))
        self.engine._persist('fixture', replace(self.engine.state, auto_strategies=(row,)))
        base = self.engine.state
        for status in OrderStatus:
            order = SimpleNamespace(plan=SimpleNamespace(strategy_id='auto-1', strategy_version=1), status=status)
            self.engine.state = replace(base, orders=(order,))
            with self.subTest(status=status):
                if status in ACTIVE:
                    with self.assertRaises(DomainError) as error:
                        execute_auto_strategy(self.engine, self.command(UiAction.RETIRE_AUTO_STRATEGY))
                    self.assertEqual(error.exception.code, 'auto_exit_required')
                else:
                    self.engine.state = base
        self.engine.state = base


if __name__ == '__main__':
    unittest.main()
