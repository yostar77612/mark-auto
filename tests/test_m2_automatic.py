"""Automatic orchestration with a durable in-memory ledger and no SDK queries."""

from dataclasses import replace
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from decimal import Decimal
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_trading_adapters import MutableClock, instrument
from quantlab.trading.application import automatic
from quantlab.trading.application.automatic_state import AutomaticState, EvaluationStatus
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.manual_book import ManualBook
from quantlab.trading.application.preflight import PreflightFacts, build_preflight
from quantlab.trading.application.state import AppState, LocalOrder, StrategyRecord, replace_order
from quantlab.trading.domain.auto_cycle import EvaluationCursor
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, OrderPlan, OrderStatus, PositionLot, Quote, Reservation, Side
from quantlab.trading.domain.risk import AccountDailyBaseline
from quantlab.trading.domain.strategy import CompletedBar, StrategyParameters
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation
from quantlab.trading.runtime.build import synthetic_calendar

D = Decimal
S = OrderStatus
SIM = Environment.BROKER_SIMULATION


class MemoryEngine:
    def __init__(self):
        self.lock = RLock()
        self.clock = MutableClock()
        self.calendar = synthetic_calendar()
        self.catalog = Catalog((instrument(), instrument(Market.INDEX_FUTURE)))
        self.configuration = SimpleNamespace(environment=SIM)
        self.storage_failed = False
        self.history = {}
        self.events = []
        self.gateways = {
            'test-stock': SimpleNamespace(
                cancel=Mock(return_value=SimpleNamespace(status=S.CANCELED)),
                snapshot=Mock(side_effect=AssertionError('no financial query')),
                refresh=Mock(side_effect=AssertionError('no refresh')),
                events=Mock(side_effect=AssertionError('no broker polling')),
            )
        }
        self.state = AppState(environment=SIM, account_ref='test-stock', trading_day=self.clock.now().date(), reconciled=True)
        self.state = replace(
            self.state,
            manual_books=(ManualBook('manual-book', 'test-stock', D('40000'), self.state.trading_day, market=Market.STOCK),),
            account_daily_baselines=(AccountDailyBaseline('test-stock', self.state.trading_day, D('0'), 'EMPTY_LEDGER_GENESIS'),),
        )
        self.record = self.make_record()
        self.state = replace(self.state, strategies=(self.record,))
        self.fees = FeeSchedule(
            buy_rate=D('0'),
            sell_rate=D('0'),
            sell_tax_rate=D('0'),
            minimum_fee=D('0'),
            futures_fee_per_contract=D('0'),
            futures_tax_rate=D('0'),
            slippage_ticks=0,
        )
        self.refresh_facts()
        self.automatic_observation_validator = Mock()
        self.automatic_entry_validator = Mock()
        self.automatic_submission_guard = Mock(side_effect=lambda *args, **kwargs: nullcontext())
        self.exit_status = S.ACCEPTED
        self.exit_calls = []

    def make_record(self, *, strategy_id='strategy', version=1, interval='5m', kind=HoldingKind.CUSTOM, instrument_id='TWSE:0050', state='ACTIVE'):
        spec = self.catalog.resolve(instrument_id)
        policy = HoldingPolicy(kind, 0, 0 if kind is HoldingKind.INTRADAY else 10)
        form = StrategyForm('strategy', spec.market, kind, policy.min_days, policy.max_days, Side.BUY, instrument_id, 'test-stock', SIM, D('20000'), D('.02'))
        return StrategyRecord(strategy_id, version, form, policy, state=state, parameters=StrategyParameters(interval, D('.03'), D('10000')))

    def refresh_facts(self):
        now = self.clock.now()
        self.manual_observations = {'test-stock': ManualAccountObservation('test-stock', SIM, (), (), (), now)}
        self.quotes = {spec.instrument_id: Quote(spec.instrument_id, D('10'), D('10'), D('10'), now, now, now.date()) for spec in self.catalog.instruments}
        result = build_preflight('test-stock', self.state.trading_day, now, SIM, PreflightFacts(True, True, True, None, True, True, True))
        self.state = replace(self.state, preflight=(result,))

    def risk(self):
        return SimpleNamespace(policy=SimpleNamespace(total_budget=D('100000')))

    def fence(self):
        pass

    def strategy(self, reference):
        return next(row for row in self.state.strategies if reference == f'{row.strategy_id}:{row.version}')

    def assert_execution_allowed(self):
        if self.configuration.environment is Environment.LIVE:
            raise DomainError('production_orders_disabled')

    def _persist(self, kind, state):
        self.state = replace(state, version=self.state.version + 1)
        self.events.append((kind, self.state))

    def order(self, key, *, status=S.ACCEPTED, lot=None):
        now = self.clock.now()
        order_id = f'order-{len(self.state.orders) + 1}'
        record = self.record if lot is None else next(row for row in self.state.strategies if row.strategy_id == lot.strategy_id)
        spec = self.catalog.resolve(record.form.instrument_id if lot is None else lot.instrument_id)
        plan = OrderPlan(
            key,
            'test-stock',
            SIM,
            spec.instrument_id,
            record.strategy_id,
            record.version,
            Side.BUY if lot is None else Side.SELL,
            1000 if lot is None else lot.quantity,
            spec.unit,
            D('10'),
            D('9'),
            lot is not None,
            now,
            now + timedelta(seconds=30),
            self.state.version,
            lot.lot_id if lot else None,
        )
        reserve = Reservation(order_id, 'test-stock', spec.instrument_id, spec.underlying, D('10000'), D('100'), plan.quantity, S.RESERVED)
        order = LocalOrder(order_id, key, key, plan, record.policy, reserve, status)
        self._persist('fake_order', replace(self.state, orders=(*self.state.orders, order)))
        return order

    def exit_lot(self, lot_id, *, protective=False, key=''):
        self.exit_calls.append((lot_id, protective, key, self.state.automatic))
        lot = next(row for row in self.state.positions if row.lot_id == lot_id)
        return self.order(key, status=self.exit_status, lot=lot).order_id


class AutomaticApplicationTests(unittest.TestCase):
    def setUp(self):
        self.engine = MemoryEngine()

    def at(self, hour, minute=0, second=0):
        session = calendar_for_instrument(self.engine.calendar, instrument()).day_session(self.engine.state.trading_day)
        self.engine.clock.value = session.opens_at.replace(hour=hour, minute=minute, second=second)
        self.engine.refresh_facts()

    def bars(self, *, count=5, offset=0, final=True, instrument_id='TWSE:0050'):
        session = calendar_for_instrument(self.engine.calendar, self.engine.catalog.resolve(instrument_id)).day_session(self.engine.state.trading_day)
        return tuple(
            LiveBar(
                instrument_id,
                session.opens_at + timedelta(minutes=i),
                session.opens_at + timedelta(minutes=i + 1),
                self.engine.state.trading_day,
                'DAY',
                D('10'),
                D('11'),
                D('9'),
                D('10'),
                1,
                final,
            )
            for i in range(offset, offset + count)
        )

    def start(self):
        self.at(9)
        automatic.resume_automatic(self.engine)

    def evaluate(self, bars):
        with patch.object(automatic, '_entry_decision') as decision:
            automatic.on_completed_bars(self.engine, bars)
        return decision

    def intraday(self, *, state='ACTIVE', quantity=1000, origin='MANAGED'):
        self.engine.record = self.engine.make_record(kind=HoldingKind.INTRADAY, state=state)
        self.engine.state = replace(self.engine.state, strategies=(self.engine.record,))
        lot = PositionLot(
            'lot', 'test-stock', 'TWSE:0050', 'strategy', 1, self.engine.record.policy, quantity, D('10'), self.engine.state.trading_day, quantity, origin
        )
        self.engine.state = replace(self.engine.state, positions=(lot,))
        return lot

    def held(self, *, state='ACTIVE'):
        self.engine.record = replace(self.engine.record, state=state)
        self.engine.state = replace(self.engine.state, strategies=(self.engine.record,))
        entry = self.engine.order('seed-entry', status=S.FILLED)
        lot = PositionLot(
            entry.order_id,
            'test-stock',
            'TWSE:0050',
            self.engine.record.strategy_id,
            self.engine.record.version,
            self.engine.record.policy,
            1000,
            D('10'),
            self.engine.state.trading_day,
            1000,
        )
        self.engine.state = replace(self.engine.state, positions=(*self.engine.state.positions, lot))
        return lot

    def pump(self):
        with patch.object(automatic, '_exit_decision') as normal:
            automatic.pump_automatic(self.engine)
        return normal

    def test_live_each_public_entrypoint_rejects_before_ports(self):
        self.engine.configuration.environment = Environment.LIVE
        with (
            patch.object(automatic, '_entry_proofs', wraps=automatic._entry_proofs) as proofs,
            patch.object(automatic, 'assert_automatic_observation', wraps=automatic.assert_automatic_observation) as observation,
        ):
            for function, args in (
                (automatic.resume_automatic, ()),
                (automatic.pause_automatic, ('stop',)),
                (automatic.reconcile_automatic, ()),
                (automatic.on_completed_bars, (self.bars(),)),
                (automatic.pump_automatic, ()),
            ):
                with self.subTest(function=function.__name__), self.assertRaises(DomainError) as caught:
                    function(self.engine, *args)
                self.assertEqual(caught.exception.code, 'production_orders_disabled')
            proofs.assert_not_called()
            observation.assert_not_called()
        self.assertFalse(self.engine.events)
        self.assertFalse(self.engine.automatic_observation_validator.called)

    def test_local_realtime_path_refuses_without_changing_day_step(self):
        self.engine.configuration.environment = Environment.LOCAL
        with self.assertRaises(DomainError) as caught:
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(caught.exception.code, 'capability_missing')

    def test_resume_is_explicit_separate_and_journaled(self):
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.start()
        self.assertFalse(self.engine.state.automatic.auto_paused)
        self.assertFalse(self.engine.state.stopped)
        self.assertEqual(self.engine.state.automatic.resumed_at, self.engine.clock.now())
        automatic.pause_automatic(self.engine, 'disconnected')
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('disconnected', self.engine.state.automatic.reasons)
        self.assertEqual(self.engine.events[-1][0], 'automatic_paused')

    def test_native_per_account_baseline_does_not_clear_legacy_marker(self):
        self.engine.state = replace(self.engine.state, daily_baseline_required=True, issues=('daily_baseline_required',))
        self.start()
        self.assertFalse(self.engine.state.automatic.auto_paused)
        self.assertTrue(self.engine.state.daily_baseline_required)
        self.assertEqual(self.engine.state.issues, ('daily_baseline_required',))

    def test_missing_or_previous_day_account_baseline_blocks_resume(self):
        for baselines in ((), (replace(self.engine.state.account_daily_baselines[0], trade_date=self.engine.state.trading_day - timedelta(days=1)),)):
            with self.subTest(baselines=baselines):
                self.engine.state = replace(self.engine.state, account_daily_baselines=baselines)
                with self.assertRaises(DomainError) as caught:
                    automatic.resume_automatic(self.engine)
                self.assertEqual(caught.exception.code, 'account_daily_baseline_required')
                self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_next_session_cannot_reuse_old_ledger_day_and_preflight_before_pump(self):
        old_day = self.engine.state.trading_day
        self.engine.clock.value += timedelta(days=3)
        self.engine.refresh_facts()
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'account_daily_baseline_required')
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertEqual(self.engine.state.trading_day, old_day)

    def test_failed_preflight_blocks_resume(self):
        self.engine.state = replace(self.engine.state, preflight=())
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'preflight_blocked')

    def test_shared_virtual_budget_overallocation_blocks_resume(self):
        self.engine.state = replace(self.engine.state, manual_books=(replace(self.engine.state.manual_books[0], capital=D('70000')),))
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'manual_allocation_exceeds_settings')

    def test_missing_confirmed_virtual_book_cannot_show_running(self):
        self.engine.state = replace(self.engine.state, manual_books=())
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'manual_book_not_enabled')
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_other_shared_book_also_requires_current_baseline(self):
        other = ManualBook('other-book', 'other', D('1000'), self.engine.state.trading_day, market=Market.STOCK)
        self.engine.state = replace(self.engine.state, manual_books=(*self.engine.state.manual_books, other))
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'account_daily_baseline_required')

    def test_storage_failure_and_pending_lifecycle_block_resume(self):
        self.engine.storage_failed = True
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)
        self.engine.storage_failed = False
        for field, job in (('corporate_actions', SimpleNamespace(status='PENDING')), ('rolls', SimpleNamespace(status='FROZEN'))):
            original = self.engine.state
            self.engine.state = replace(original, **{field: (job,)})
            with self.subTest(field=field), self.assertRaises(DomainError):
                automatic.resume_automatic(self.engine)
            self.engine.state = original

    def test_reconciliation_difference_blocks_resume(self):
        self.engine.state = replace(self.engine.state, reconciliation=(object(),))
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)

    def test_stale_observation_blocks_resume(self):
        self.engine.clock.value += timedelta(seconds=31)
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'manual_account_observation_required')

    def test_current_owner_validator_must_pass(self):
        self.engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'state_conflict')

    def test_missing_current_entry_proof_port_blocks_resume(self):
        del self.engine.automatic_entry_validator
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'capability_missing')
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_current_entry_proof_denial_blocks_stale_passed_preflight(self):
        self.engine.automatic_entry_validator.side_effect = DomainError('preflight_permission')
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'preflight_permission')
        self.engine.automatic_entry_validator.assert_called_once_with('test-stock')
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_entry_proof_denial_pauses_completed_bar_before_claim(self):
        self.start()
        self.at(9, 5)
        self.engine.automatic_entry_validator.side_effect = DomainError('preflight_permission')
        self.assertFalse(self.evaluate(self.bars()).called)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertIn('preflight_permission', self.engine.state.automatic.reasons)
        self.assertFalse(self.engine.state.automatic.evaluations)

    def test_protective_and_reconcile_paths_do_not_require_new_entry_proof(self):
        self.intraday()
        self.at(10)
        self.engine.automatic_entry_validator.side_effect = DomainError('preflight_service')
        self.assertEqual(self.pump().call_count, 1)
        automatic.reconcile_automatic(self.engine)
        self.engine.automatic_entry_validator.assert_not_called()

    def test_unhealthy_and_closed_state_cannot_resume(self):
        for values in ({'issues': ('outcome_unknown',)}, {'reconciled': False}, {'engine_closed': True}, {'daily_locks': (self.engine.state.trading_day,)}):
            original = self.engine.state
            self.engine.state = replace(original, **values)
            with self.subTest(values=values), self.assertRaises(DomainError):
                automatic.resume_automatic(self.engine)
            self.engine.state = original

    def test_account_loss_latch_cannot_resume(self):
        self.engine.state = replace(self.engine.state, account_daily_locks=(('test-stock', self.engine.state.trading_day),))
        with self.assertRaises(DomainError) as caught:
            automatic.resume_automatic(self.engine)
        self.assertEqual(caught.exception.code, 'account_daily_loss_limit')

    def test_interrupted_claim_cannot_resume(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        self.engine.state = replace(
            self.engine.state, automatic=AutomaticState(evaluations=(EvaluationStatus(cursor, self.engine.clock.now(), phase='INTERRUPTED'),))
        )
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)

    def test_resume_ownership_fence_precedes_persist(self):
        self.engine.fence = Mock(side_effect=DomainError('state_conflict'))
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertFalse(self.engine.events)

    def test_no_completed_bucket_no_evaluation(self):
        self.start()
        self.at(9, 5)
        for bars in (self.bars(count=4), self.bars(final=False), self.bars()[:2] + self.bars()[3:]):
            self.engine.automatic_minute_bars = {}
            self.assertFalse(self.evaluate(bars).called)
        self.assertFalse(self.engine.state.automatic.evaluations)

    def test_forming_clock_does_not_evaluate_final_future_end(self):
        self.start()
        self.at(9, 4)
        self.assertFalse(self.evaluate(self.bars()).called)

    def test_durable_claim_before_decision_and_end_inclusive(self):
        self.start()
        self.at(9, 5)
        calls = []

        def decide(engine, record, history, *, decision_key, as_of):
            claim = engine.state.automatic.evaluations[0]
            self.assertEqual(claim.phase, 'CLAIMED')
            self.assertEqual(engine.events[-1][0], 'automatic_evaluation_claimed')
            self.assertEqual(history['TWSE:0050'][-1].available_at, as_of)
            self.assertIn(':strategy:1:TWSE:0050:5m:', decision_key)
            calls.append(decision_key)

        with patch.object(automatic, '_entry_decision', side_effect=decide):
            automatic.on_completed_bars(self.engine, self.bars())
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'COMPLETED')

    def test_bucket_accumulates_across_callback_batches(self):
        self.start()
        self.at(9, 5)
        self.assertFalse(self.evaluate(self.bars(count=2)).called)
        self.assertEqual(self.evaluate(self.bars(count=3, offset=2)).call_count, 1)

    def test_forming_delivery_does_not_poison_later_final_bucket(self):
        self.start()
        self.at(9, 5)
        self.assertFalse(self.evaluate(self.bars(final=False)).called)
        self.assertEqual(self.evaluate(self.bars()).call_count, 1)

    def test_conflicting_final_minute_is_never_used(self):
        self.start()
        self.at(9, 5)
        bars = self.bars()
        self.assertFalse(self.evaluate((*bars, replace(bars[1], close=D('11')))).called)

    def test_only_typed_active_matching_instrument_evaluates(self):
        self.start()
        self.at(9, 5)
        for record in (
            replace(self.engine.record, parameters=None),
            replace(self.engine.record, state='DISABLED'),
            self.engine.make_record(instrument_id='TAIFEX:TMF:202611'),
        ):
            self.engine.state = replace(self.engine.state, strategies=(record,))
            self.engine.automatic_minute_bars = {}
            self.assertFalse(self.evaluate(self.bars()).called)

    def test_unrelated_callback_cannot_trigger_another_instrument_warm_cache(self):
        self.start()
        self.at(9, 5)
        tmf = 'TAIFEX:TMF:202611'
        self.engine.state = replace(self.engine.state, strategies=(self.engine.make_record(instrument_id=tmf),))
        self.engine.automatic_minute_bars = {tmf: self.bars(instrument_id=tmf, offset=15)}
        self.assertFalse(self.evaluate(self.bars()).called)

    def test_version_and_interval_get_independent_cursors(self):
        self.start()
        self.at(9, 5)
        self.engine.state = replace(
            self.engine.state,
            strategies=(self.engine.record, replace(self.engine.record, version=2), self.engine.make_record(strategy_id='other', interval='1m')),
        )
        self.assertEqual(self.evaluate(self.bars()).call_count, 7)
        self.assertEqual(len(self.engine.state.automatic.cursors), 3)

    def test_resume_does_not_replay_earlier_or_equal_bars(self):
        self.at(9, 5)
        automatic.resume_automatic(self.engine)
        self.assertFalse(self.evaluate(self.bars()).called)
        self.at(9, 10)
        self.assertEqual(self.evaluate(self.bars(offset=5)).call_count, 1)

    def test_paused_and_global_stop_cannot_evaluate(self):
        self.at(9, 5)
        self.assertFalse(self.evaluate(self.bars()).called)
        self.start()
        self.at(9, 5)
        self.engine.state = replace(self.engine.state, stopped=True)
        self.assertFalse(self.evaluate(self.bars()).called)
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_lost_reconciliation_pauses_before_claim(self):
        self.start()
        self.at(9, 5)
        self.engine.state = replace(self.engine.state, reconciled=False)
        self.assertFalse(self.evaluate(self.bars()).called)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertFalse(self.engine.state.automatic.evaluations)

    def test_submit_unknown_preserves_reservation_and_never_replays(self):
        self.start()
        self.at(9, 5)

        def decide(engine, record, history, *, decision_key, as_of):
            engine.order(decision_key, status=S.UNKNOWN)
            raise DomainError('outcome_unknown')

        with patch.object(automatic, '_entry_decision', side_effect=decide) as decision:
            automatic.on_completed_bars(self.engine, self.bars())
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(decision.call_count, 1)
        self.assertEqual(self.engine.state.orders[0].reservation.cash, D('10000'))
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.UNKNOWN)

    def test_unknown_without_visible_order_still_preserves_uncertain_claim(self):
        self.start()
        self.at(9, 5)
        with patch.object(automatic, '_entry_decision', side_effect=DomainError('outcome_unknown')):
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.UNKNOWN)
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)

    def test_rejected_decision_is_final_for_that_bar(self):
        self.start()
        self.at(9, 5)
        with patch.object(automatic, '_entry_decision', side_effect=DomainError('risk_rejected')) as decision:
            automatic.on_completed_bars(self.engine, self.bars())
            self.assertTrue(self.engine.state.automatic.auto_paused)
            self.assertTrue(self.engine.state.stopped)
            automatic.resume_automatic(self.engine)
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(decision.call_count, 1)
        self.assertEqual(self.engine.state.automatic.evaluations[0].code, 'risk_rejected')

    def test_history_does_not_mix_daily_or_forming_bars_into_five_minute_signals(self):
        self.start()
        self.at(9, 5)
        now = self.engine.clock.now()
        daily = CompletedBar(now - timedelta(days=1, hours=4), now - timedelta(days=1), now - timedelta(days=1), D('10'), D('10'), 1)
        minute = CompletedBar(now - timedelta(minutes=6), now - timedelta(minutes=5), now - timedelta(minutes=5), D('10'), D('10'), 1)
        five = CompletedBar(now - timedelta(minutes=10), now - timedelta(minutes=5), now - timedelta(minutes=5), D('10'), D('10'), 1)
        self.engine.history = {'TWSE:0050': (daily, minute, five)}
        decision = self.evaluate(self.bars())
        self.assertEqual(len(decision.call_args.args[2]['TWSE:0050']), 2)

    def test_force_claim_persisted_before_exit_even_disabled_and_paused(self):
        self.intraday(state='DISABLED')
        self.at(13, 20)
        self.pump()
        lot_id, protective, key, state = self.engine.exit_calls[0]
        self.assertEqual((lot_id, protective, key), ('lot', True, 'forced-exit:lot:1'))
        self.assertEqual(state.forced_attempts[0].status, S.SUBMITTING)
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('intraday_force_exit', self.engine.state.automatic.reasons)

    def test_intraday_new_entries_stop_at_force_time_even_when_flat(self):
        self.engine.record = self.engine.make_record(kind=HoldingKind.INTRADAY)
        self.engine.state = replace(self.engine.state, strategies=(self.engine.record,))
        self.start()
        self.at(13, 20)
        self.assertFalse(self.evaluate(self.bars(offset=255)).called)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertIn('intraday_force_exit', self.engine.state.automatic.reasons)

    def test_due_intraday_guard_runs_before_any_other_strategy(self):
        intraday = self.engine.make_record(strategy_id='intraday', kind=HoldingKind.INTRADAY)
        self.engine.state = replace(self.engine.state, strategies=(self.engine.record, intraday))
        self.start()
        self.at(13, 20)
        self.assertFalse(self.evaluate(self.bars(offset=255)).called)

    def test_disabled_owned_intraday_scope_blocks_other_new_entries_at_due(self):
        self.intraday(state='DISABLED')
        other = self.engine.make_record(strategy_id='swing')
        self.engine.state = replace(self.engine.state, strategies=(*self.engine.state.strategies, other))
        self.start()
        self.at(13, 20)
        self.assertFalse(self.evaluate(self.bars(offset=255)).called)

    def test_no_force_before_product_due(self):
        self.intraday()
        self.at(13, 19, 59)
        self.assertEqual(self.pump().call_count, 1)
        self.assertFalse(self.engine.exit_calls)

    def test_tmf_uses_futures_hours_not_stock_close(self):
        record = self.engine.make_record(kind=HoldingKind.INTRADAY, instrument_id='TAIFEX:TMF:202611')
        self.engine.record = record
        self.engine.state = replace(
            self.engine.state,
            strategies=(record,),
            positions=(
                PositionLot(
                    'lot',
                    'test-stock',
                    record.form.instrument_id,
                    record.strategy_id,
                    record.version,
                    record.policy,
                    1,
                    D('10'),
                    self.engine.state.trading_day,
                    1,
                ),
            ),
        )
        self.at(13, 30)
        self.pump()
        self.assertFalse(self.engine.exit_calls)
        self.at(13, 35)
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 1)

    def test_retry_waits_thirty_seconds_then_observed_cancel(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        self.at(13, 20, 29)
        self.pump()
        gateway = self.engine.gateways['test-stock']
        self.assertFalse(gateway.cancel.called)
        self.at(13, 20, 30)
        self.pump()
        self.assertEqual(gateway.cancel.call_count, 1)
        self.assertEqual(self.engine.state.orders[0].status, S.CANCEL_PENDING)
        self.assertEqual(len(self.engine.exit_calls), 1)
        self.pump()
        self.assertEqual(gateway.cancel.call_count, 1)
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[0], status=S.CANCELED))
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 2)
        self.assertEqual(self.engine.exit_calls[-1][2], 'forced-exit:lot:2')

    def test_partial_fill_cancel_then_retry_only_remaining_lot(self):
        lot = self.intraday()
        self.at(13, 20)
        self.pump()
        order = replace(self.engine.state.orders[0], status=S.PARTIALLY_FILLED, filled=400)
        self.engine.state = replace(replace_order(self.engine.state, order), positions=(replace(lot, quantity=600, sellable_quantity=600),))
        self.at(13, 20, 30)
        self.pump()
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[0], status=S.CANCELED))
        self.pump()
        self.assertEqual(self.engine.state.orders[-1].plan.quantity, 600)

    def test_unknown_force_never_cancelled_or_resent(self):
        self.intraday()
        self.engine.exit_status = S.UNKNOWN
        self.at(13, 20)
        self.pump()
        self.at(13, 21)
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 1)
        self.assertFalse(self.engine.gateways['test-stock'].cancel.called)
        self.assertIn('order_result_unknown', self.engine.state.automatic.reasons)
        self.assertEqual(self.engine.state.orders[0].reservation.cash, D('10000'))

    def test_unknown_force_without_order_record_cannot_be_retried(self):
        self.intraday()
        self.at(13, 20)
        self.engine.exit_lot = Mock(side_effect=DomainError('outcome_unknown'))
        self.pump()
        self.at(13, 21)
        self.pump()
        self.assertEqual(self.engine.exit_lot.call_count, 1)
        self.assertEqual(self.engine.state.automatic.forced_attempts[0].status, S.UNKNOWN)

    def test_unknown_cancel_never_retries(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        self.engine.gateways['test-stock'].cancel.side_effect = DomainError('outcome_unknown')
        self.at(13, 20, 30)
        self.pump()
        self.at(13, 21)
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 1)
        self.assertEqual(self.engine.state.orders[0].status, S.UNKNOWN)

    def test_force_cancel_requires_current_submission_guard_before_cancel_intent(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        del self.engine.automatic_submission_guard
        self.at(13, 20, 30)
        self.pump()
        self.engine.gateways['test-stock'].cancel.assert_not_called()
        self.assertEqual(self.engine.state.orders[0].status, S.ACCEPTED)
        self.assertEqual(self.engine.state.orders[0].reservation.cash, D('10000'))
        self.assertIn('capability_missing', self.engine.state.automatic.reasons)

    def test_force_cancel_owner_guard_denial_retains_working_protection(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        self.engine.automatic_submission_guard.side_effect = DomainError('state_conflict')
        self.at(13, 20, 30)
        self.pump()
        self.engine.gateways['test-stock'].cancel.assert_not_called()
        self.assertEqual(self.engine.state.orders[0].status, S.ACCEPTED)
        self.assertIn('state_conflict', self.engine.state.automatic.reasons)
        self.engine.automatic_submission_guard.assert_called_once_with('test-stock', reduce_only=True)

    def test_cancel_journal_and_port_execute_inside_reduction_owner_guard(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        held = []

        @contextmanager
        def guard(reference, *, reduce_only):
            self.assertEqual((reference, reduce_only), ('test-stock', True))
            held.append(True)
            try:
                yield
            finally:
                held.pop()

        self.engine.automatic_submission_guard = guard
        original = self.engine._persist

        def persist(kind, state):
            if kind == 'cancel_pending':
                self.assertTrue(held)
            original(kind, state)

        self.engine._persist = persist
        self.engine.gateways['test-stock'].cancel.side_effect = lambda order_id: self.assertTrue(held) or SimpleNamespace(status=S.CANCELED)
        self.at(13, 20, 30)
        self.pump()
        self.assertEqual(self.engine.state.orders[0].status, S.CANCEL_PENDING)
        self.assertFalse(held)

    def test_retry_cutoff_and_post_close_anomaly(self):
        self.intraday()
        self.start()
        self.at(13, 28, 1)
        self.pump()
        self.assertFalse(self.engine.exit_calls)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('intraday_force_exit', self.engine.state.automatic.reasons)
        self.at(13, 30, 1)
        self.pump()
        self.assertIn('automatic_overdue_position', self.engine.state.automatic.reasons)
        self.assertFalse(self.engine.exit_calls)

    def test_working_force_order_is_retained_after_retry_cutoff(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        self.at(13, 28, 1)
        self.pump()
        self.assertFalse(self.engine.gateways['test-stock'].cancel.called)
        self.assertEqual(len(self.engine.exit_calls), 1)

    def test_normal_exit_is_not_cancelled_after_force_retry_cutoff(self):
        lot = self.intraday()
        self.engine.order('normal-exit', lot=lot)
        self.at(13, 28, 1)
        self.pump()
        self.assertFalse(self.engine.gateways['test-stock'].cancel.called)
        self.assertFalse(self.engine.exit_calls)

    def test_closed_or_failed_journal_never_pumps_protection(self):
        self.intraday()
        self.at(13, 20)
        self.engine.state = replace(self.engine.state, engine_closed=True)
        with self.assertRaises(DomainError):
            automatic.pump_automatic(self.engine)
        self.engine.state = replace(self.engine.state, engine_closed=False)
        self.engine.storage_failed = True
        with self.assertRaises(DomainError):
            automatic.pump_automatic(self.engine)
        self.assertFalse(self.engine.exit_calls)

    def test_manual_observed_cancel_resolves_force_without_fictitious_pending_phase(self):
        self.intraday()
        self.at(13, 20)
        self.pump()
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[0], status=S.CANCELED))
        self.at(13, 20, 30)
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 2)

    def test_existing_normal_exit_cancelled_before_first_force(self):
        lot = self.intraday()
        self.engine.order('normal-exit', lot=lot)
        self.at(13, 20)
        self.pump()
        self.assertFalse(self.engine.exit_calls)
        self.assertEqual(self.engine.state.orders[0].status, S.CANCEL_PENDING)
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[0], status=S.CANCELED))
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 1)

    def test_protection_runs_while_paused_and_disconnected(self):
        self.intraday(state='DISABLED')
        self.at(10)
        self.engine.state = replace(self.engine.state, reconciled=False, stopped=True, issues=('disconnected',))
        self.engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
        normal = self.pump()
        self.assertEqual(normal.call_count, 1)
        self.assertFalse(normal.call_args.kwargs['intraday_timer'])
        self.assertFalse(normal.call_args.kwargs['evaluate_signal'])

    def test_pumps_never_reevaluate_actual_normal_exit_signal(self):
        self.held()
        self.start()
        self.at(9, 5, 1)
        self.engine.automatic_minute_bars = {'TWSE:0050': self.bars()}
        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True) as signal:
            for _ in range(5):
                automatic.pump_automatic(self.engine)
        signal.assert_not_called()
        self.assertFalse(self.engine.exit_calls)

    def test_actual_normal_exit_evaluates_once_only_after_completed_bucket(self):
        lot = self.held()
        self.start()
        self.at(9, 5)
        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True) as signal:
            automatic.on_completed_bars(self.engine, self.bars(final=False))
            signal.assert_not_called()
            automatic.on_completed_bars(self.engine, self.bars())
            automatic.on_completed_bars(self.engine, self.bars())
            self.at(9, 5, 1)
            for _ in range(5):
                automatic.pump_automatic(self.engine)
        self.assertEqual(signal.call_count, 1)
        self.assertEqual(len(self.engine.exit_calls), 1)
        call = self.engine.exit_calls[0]
        self.assertTrue(call[2].endswith(':exit:' + lot.lot_id))
        self.assertEqual(call[3].evaluations[0].phase, 'CLAIMED')
        evaluation = self.engine.state.automatic.evaluations[0]
        self.assertEqual(evaluation.order_result, S.ACCEPTED)
        self.assertEqual(evaluation.order_id, self.engine.state.orders[-1].order_id)

    def test_disabled_and_retired_owned_records_keep_completed_bar_exit_rules(self):
        for state in ('DISABLED', 'RETIRED'):
            self.setUp()
            self.held(state=state)
            self.start()
            self.at(9, 5)
            with (
                self.subTest(state=state),
                patch('quantlab.trading.application.coordinator.exit_signal', return_value=True) as signal,
                patch.object(automatic, '_entry_decision') as entry,
            ):
                automatic.on_completed_bars(self.engine, self.bars())
                self.assertEqual(signal.call_count, 1)
                entry.assert_not_called()
                self.assertEqual(len(self.engine.exit_calls), 1)

    def test_completed_exit_uses_bar_end_inclusive_and_only_its_owned_instrument(self):
        lot = self.held()
        self.start()
        self.at(9, 5)
        with patch.object(automatic, '_exit_decision') as exit_decision:
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(exit_decision.call_count, 1)
        self.assertEqual(exit_decision.call_args.args[1].lot_id, lot.lot_id)
        self.assertTrue(exit_decision.call_args.kwargs['evaluate_signal'])
        self.assertEqual(exit_decision.call_args.kwargs['as_of'], self.bars()[-1].end)
        self.assertFalse(exit_decision.call_args.kwargs['intraday_timer'])

    def test_completed_exit_does_not_claim_other_strategy_version_or_external_ownership(self):
        for changes in ({'strategy_version': 2}, {'strategy_id': 'other'}, {'origin': 'EXTERNAL'}, {'quantity': 0, 'sellable_quantity': 0}):
            self.setUp()
            lot = self.held()
            self.engine.state = replace(self.engine.state, positions=(replace(lot, **changes),))
            self.start()
            self.at(9, 5)
            with self.subTest(changes=changes), patch.object(automatic, '_exit_decision') as exit_decision, patch.object(automatic, '_entry_decision'):
                automatic.on_completed_bars(self.engine, self.bars())
                exit_decision.assert_not_called()

    def test_protective_stop_still_executes_without_evaluating_normal_signal(self):
        self.held()
        self.start()
        self.at(9, 5)
        self.engine.quotes['TWSE:0050'] = replace(self.engine.quotes['TWSE:0050'], last=D('9'), bid=D('9'), ask=D('9'))
        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True) as signal:
            automatic.pump_automatic(self.engine)
        signal.assert_not_called()
        self.assertEqual(len(self.engine.exit_calls), 1)
        self.assertTrue(self.engine.exit_calls[0][1])

    def test_crash_after_exit_claim_cannot_reevaluate_or_resend_on_bar_replay(self):
        self.held()
        self.start()
        self.at(9, 5)
        persist = self.engine._persist

        def crash(kind, state):
            if kind == 'automatic_evaluation_completed':
                self.engine.storage_failed = True
                raise DomainError('journal_failed')
            persist(kind, state)

        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True) as signal:
            with patch.object(self.engine, '_persist', side_effect=crash), self.assertRaises(DomainError):
                automatic.on_completed_bars(self.engine, self.bars())
            self.engine.storage_failed = False
            self.engine.state = replace(self.engine.state, stopped=True, automatic=automatic.claims.restart(self.engine.state.automatic))
            automatic.on_completed_bars(self.engine, self.bars())
            automatic.reconcile_automatic(self.engine)
            automatic.resume_automatic(self.engine)
            automatic.on_completed_bars(self.engine, self.bars())
        self.assertEqual(signal.call_count, 1)
        self.assertEqual(len(self.engine.exit_calls), 1)

    def test_multilot_exit_correlates_unknown_prefix_and_reconciles_same_order_id(self):
        self.held()
        self.held()
        self.start()
        self.at(9, 5)
        original = self.engine.exit_lot
        statuses = iter((S.ACCEPTED, S.UNKNOWN))

        def exit_lot(lot_id, **kwargs):
            self.engine.exit_status = next(statuses)
            return original(lot_id, **kwargs)

        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True), patch.object(self.engine, 'exit_lot', side_effect=exit_lot):
            automatic.on_completed_bars(self.engine, self.bars())
        row = self.engine.state.automatic.evaluations[0]
        self.assertEqual(row.order_result, S.UNKNOWN)
        self.assertEqual(row.order_id, self.engine.state.orders[-1].order_id)
        fixed_id = row.order_id
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], status=S.CANCELED))
        self.engine.state = replace(self.engine.state, issues=('outcome_unknown',), reconciled=True)
        automatic.reconcile_automatic(self.engine)
        row = self.engine.state.automatic.evaluations[0]
        self.assertEqual(row.order_id, fixed_id)
        self.assertEqual(row.order_result, S.CANCELED)
        self.assertNotIn('outcome_unknown', self.engine.state.issues)
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_multilot_result_keeps_previous_order_id_when_other_leg_becomes_unknown(self):
        self.held()
        self.held()
        self.start()
        self.at(9, 5)
        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True):
            automatic.on_completed_bars(self.engine, self.bars())
        row = self.engine.state.automatic.evaluations[0]
        original_id = row.order_id
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], status=S.UNKNOWN))
        result, order_id = automatic._evaluation_result(self.engine, row.cursor, original_id)
        self.assertEqual((result, order_id), (S.UNKNOWN, original_id))
        changed = replace(row, order_result=S.UNKNOWN)
        self.engine.state = replace(
            self.engine.state,
            automatic=replace(self.engine.state.automatic, auto_paused=True, evaluations=(changed,)),
            stopped=True,
            issues=('outcome_unknown',),
        )
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], status=S.CANCELED))
        automatic.reconcile_automatic(self.engine)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_id, original_id)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.ACCEPTED)

    def test_later_unknown_exit_report_pauses_and_updates_pinned_evaluation_without_new_bar(self):
        self.held()
        self.held()
        self.start()
        self.at(9, 5)
        with patch('quantlab.trading.application.coordinator.exit_signal', return_value=True):
            automatic.on_completed_bars(self.engine, self.bars())
        previous_id = self.engine.state.automatic.evaluations[0].order_id
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], status=S.UNKNOWN))
        automatic.pump_automatic(self.engine)
        row = self.engine.state.automatic.evaluations[0]
        self.assertEqual(row.order_result, S.UNKNOWN)
        self.assertEqual(row.order_id, previous_id)
        self.assertTrue(self.engine.state.stopped)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertIn('order_result_unknown', self.engine.state.automatic.reasons)
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], status=S.CANCELED))
        automatic.reconcile_automatic(self.engine)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_id, previous_id)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.ACCEPTED)
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_normal_exit_receives_completed_current_interval_history(self):
        self.intraday()
        self.at(9, 5)
        self.engine.automatic_minute_bars = {'TWSE:0050': self.bars()}
        normal = self.pump()
        history = normal.call_args.args[2]['TWSE:0050']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].ended_at, self.engine.clock.now())

    def test_account_risk_stop_also_latches_automatic_without_blocking_protection(self):
        self.intraday()
        self.start()
        self.at(10)
        self.engine.state = replace(self.engine.state, account_daily_locks=(('test-stock', self.engine.state.trading_day),))
        self.assertEqual(self.pump().call_count, 1)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertIn('account_daily_loss_limit', self.engine.state.automatic.reasons)

    def test_external_or_zero_lots_are_not_automatically_reduced(self):
        self.intraday(origin='EXTERNAL')
        self.at(13, 20)
        self.pump()
        self.assertFalse(self.engine.exit_calls)
        self.intraday(quantity=0)
        self.pump()
        self.assertFalse(self.engine.exit_calls)

    def test_reconcile_updates_unknown_from_accepted_ledger_but_keeps_paused(self):
        self.start()
        self.at(9, 5)
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        state = AutomaticState(
            evaluations=(EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id),)
        )
        self.engine.state = replace(self.engine.state, automatic=state, stopped=True)
        automatic.reconcile_automatic(self.engine)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.CANCELED)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertTrue(self.engine.state.stopped)
        automatic.resume_automatic(self.engine)
        self.assertFalse(self.engine.state.automatic.auto_paused)

    def test_actual_unknown_issue_clears_only_after_owned_known_ledger_reconcile(self):
        self.start()
        self.at(9, 5)
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        automatic_state = AutomaticState(
            evaluations=(EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id),)
        )
        self.engine.state = replace(self.engine.state, automatic=automatic_state, stopped=True, issues=('outcome_unknown',))
        automatic.reconcile_automatic(self.engine)
        self.assertEqual(self.engine.state.issues, ())
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.CANCELED)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        automatic.resume_automatic(self.engine)
        self.assertFalse(self.engine.state.automatic.auto_paused)

    def test_unknown_issue_cannot_clear_while_manual_request_unknown(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        row = EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id)
        self.engine.state = replace(
            self.engine.state,
            automatic=AutomaticState(evaluations=(row,)),
            issues=('outcome_unknown',),
            manual_requests=(SimpleNamespace(outcome_known=False),),
        )
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertIn('outcome_unknown', self.engine.state.issues)
        self.assertEqual(self.engine.state.automatic.evaluations[0].order_result, S.UNKNOWN)

    def test_reconcile_preserves_unrelated_issue_after_resolving_auto_unknown(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        row = EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id)
        self.engine.state = replace(self.engine.state, automatic=AutomaticState(evaluations=(row,)), issues=('outcome_unknown', 'account_daily_loss_limit'))
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertEqual(self.engine.state.issues, ('account_daily_loss_limit',))
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_reconcile_does_not_clear_unknown_for_missing_order_claim(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        row = EvaluationStatus(cursor, self.engine.clock.now(), phase='INTERRUPTED')
        self.engine.state = replace(self.engine.state, automatic=AutomaticState(evaluations=(row,)), issues=('outcome_unknown',))
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertIn('outcome_unknown', self.engine.state.issues)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'INTERRUPTED')

    def test_reconcile_only_resolves_owned_automatic_outcome_issue(self):
        self.engine.order('manual-order', status=S.CANCELED)
        self.engine.state = replace(self.engine.state, issues=('outcome_unknown',))
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertIn('outcome_unknown', self.engine.state.issues)

    def test_other_unresolved_evaluation_prevents_clearing_unknown_issue(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        known = EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id)
        missing = EvaluationStatus(replace(cursor, version=2), self.engine.clock.now(), phase='INTERRUPTED')
        self.engine.state = replace(self.engine.state, automatic=AutomaticState(evaluations=(known, missing)), issues=('outcome_unknown',))
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertIn('outcome_unknown', self.engine.state.issues)

    def test_other_unresolved_force_prevents_clearing_unknown_issue(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        known = EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id)
        force = automatic.claims.ForcedAttempt('other-lot', 1, self.engine.clock.now(), S.UNKNOWN)
        self.engine.state = replace(self.engine.state, automatic=AutomaticState(evaluations=(known,), forced_attempts=(force,)), issues=('outcome_unknown',))
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertIn('outcome_unknown', self.engine.state.issues)

    def test_reconcile_must_validate_current_observation_again(self):
        self.engine.clock.value += timedelta(seconds=31)
        with self.assertRaises(DomainError):
            automatic.reconcile_automatic(self.engine)
        self.assertFalse(self.engine.events)

    def test_reconcile_closed_or_failed_engine_does_not_write_claims(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        order = self.engine.order(automatic._decision_key(cursor), status=S.CANCELED)
        row = EvaluationStatus(cursor, self.engine.clock.now(), phase='COMPLETED', order_result=S.UNKNOWN, order_id=order.order_id)
        self.engine.state = replace(self.engine.state, automatic=AutomaticState(evaluations=(row,)), issues=('outcome_unknown',))
        self.engine.events.clear()
        for values, failed in (({'engine_closed': True}, False), ({'engine_closed': False}, True)):
            self.engine.state = replace(self.engine.state, **values)
            self.engine.storage_failed = failed
            with self.assertRaises(DomainError):
                automatic.reconcile_automatic(self.engine)
            self.assertFalse(self.engine.events)

    def test_reconcile_cannot_guess_unsent_interrupted_claim(self):
        cursor = EvaluationCursor('strategy', 1, 'TWSE:0050', '5m', self.engine.clock.now())
        self.engine.state = replace(
            self.engine.state, automatic=AutomaticState(evaluations=(EvaluationStatus(cursor, self.engine.clock.now(), phase='INTERRUPTED'),))
        )
        automatic.reconcile_automatic(self.engine)
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'INTERRUPTED')
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)

    def test_forced_unknown_requires_explicit_reconcile_and_resume_before_retry(self):
        self.intraday()
        self.engine.exit_status = S.UNKNOWN
        self.at(13, 20)
        self.pump()
        order = replace(self.engine.state.orders[0], status=S.CANCELED)
        self.engine.state = replace_order(self.engine.state, order)
        self.at(13, 21)
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 1)
        self.assertEqual(self.engine.state.automatic.forced_attempts[0].status, S.UNKNOWN)
        automatic.reconcile_automatic(self.engine)
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 1)
        automatic.resume_automatic(self.engine)
        self.engine.exit_status = S.ACCEPTED
        self.pump()
        self.assertEqual(len(self.engine.exit_calls), 2)

    def test_all_flows_use_cached_facts_without_broker_financial_queries(self):
        self.start()
        self.at(9, 5)
        self.evaluate(self.bars())
        automatic.reconcile_automatic(self.engine)
        self.pump()
        for gateway in self.engine.gateways.values():
            gateway.snapshot.assert_not_called()
            gateway.refresh.assert_not_called()
            gateway.events.assert_not_called()
