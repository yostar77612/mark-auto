"""Review regressions: atomic daily saves, explicit proof levels and LIVE layers."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_live_order_guard as live_fixtures
import test_m2_automatic as memory
import test_trading_adapters as market
import test_trading_sdk_facade as sdk
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.application import daily_execution
from quantlab.trading.application.automatic_state import AutomaticState
from quantlab.trading.application.codec import loads
from quantlab.trading.application.coordinator import _entry_decision
from quantlab.trading.application.daily_state import DailyState, create_intent
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.manual_book import manual_day_ready
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.sessions import DailyBaselineEvidence, fee_fingerprint
from quantlab.trading.application.state import AppState
from quantlab.trading.domain.auto_cycle import EvaluationCursor
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar, calendar_for_instrument
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingPolicy, OrderStatus, PositionLot, Reservation
from quantlab.trading.domain.risk import AccountDailyBaseline
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerOrder

D = Decimal
SIM = Environment.BROKER_SIMULATION


class FailingDailyJournal(live_fixtures.GuardJournal):
    def __init__(self):
        super().__init__()
        self.fail_saved = True

    def append(self, kind, payload, now, *, expected_sequence):
        if kind == 'daily_signals_saved' and self.fail_saved:
            raise DomainError('journal_failed', 'injected atomic-save append failure')
        return super().append(kind, payload, now, expected_sequence=expected_sequence)


class DailyReviewGuardTests(unittest.TestCase):
    def engine(self):
        initialize()
        engine = memory.MemoryEngine()
        engine.record = engine.make_record(interval='1d')
        engine.record = replace(engine.record, form=replace(engine.record.form, rule_kind='BUY_AND_HOLD'), evidence_hash='a' * 64)
        engine.state = replace(engine.state, strategies=(engine.record,))
        calendar = calendar_for_instrument(engine.calendar, engine.catalog.instruments[0])
        session = calendar.day_session(engine.state.trading_day)
        engine.clock.value = session.closes_at
        engine.refresh_facts()
        engine.quotes = {key: replace(value, source='SHIOAJI') for key, value in engine.quotes.items()}
        daily = DailyState(authorized_run='explicit-run', owner_stamp=engine.automatic_owner_stamp())
        engine.state = replace(engine.state, stopped=False, automatic=AutomaticState(False, (), session.opens_at, daily=daily))
        return engine, calendar, session

    def minutes(self, engine, session):
        return tuple(
            LiveBar(
                engine.record.form.instrument_id,
                start,
                start + timedelta(minutes=1),
                session.trade_date,
                'DAY',
                D('10'),
                D('10'),
                D('10'),
                D('10'),
                100,
                final=True,
            )
            for offset in range((session.closes_at - session.opens_at) // timedelta(minutes=1))
            for start in (session.opens_at + timedelta(minutes=offset),)
        )

    def test_e29_saved_append_failure_keeps_claim_and_intents_atomic_in_memory_and_journal(self):
        engine, _, session = self.engine()
        journal = FailingDailyJournal()
        engine.journal, engine.ownership_clock = journal, engine.clock.now
        engine._persist = MethodType(TradingEngine._persist, engine)
        bars = self.minutes(engine, session)
        with self.assertRaises(DomainError) as caught:
            daily_execution.observe_daily(engine, bars)
        self.assertEqual(caught.exception.code, 'journal_failed')
        self.assertTrue(engine.storage_failed)
        self.assertTrue(engine.state.stopped)
        self.assertEqual(engine.state.automatic.evaluations[0].phase, 'CLAIMED')
        self.assertEqual(engine.state.automatic.daily.intents, ())
        durable = loads(journal.replay()[-1].payload)
        self.assertEqual(journal.replay()[-1].kind, 'daily_evaluation_claimed')
        self.assertEqual(durable.automatic.evaluations[0].phase, 'CLAIMED')
        self.assertEqual(durable.automatic.daily.intents, ())
        count = len(journal.replay())
        with self.assertRaises(DomainError):
            daily_execution.observe_daily(engine, bars)
        self.assertEqual(len(journal.replay()), count)

    def test_e29_success_saves_complete_evaluation_and_one_intent_in_one_durable_event(self):
        engine, _, session = self.engine()
        engine.journal, engine.ownership_clock = live_fixtures.GuardJournal(), engine.clock.now
        engine._persist = MethodType(TradingEngine._persist, engine)
        bars = self.minutes(engine, session)
        daily_execution.observe_daily(engine, bars)
        saved = tuple(event for event in engine.journal.replay() if event.kind == 'daily_signals_saved')
        self.assertEqual(len(saved), 1)
        snapshot = loads(saved[0].payload)
        self.assertEqual(snapshot.automatic.evaluations[0].phase, 'COMPLETED')
        self.assertEqual(tuple(row.action for row in snapshot.automatic.daily.intents), ('ENTRY',))
        daily_execution.observe_daily(engine, bars)
        self.assertEqual(len(engine.state.automatic.daily.intents), 1)
        self.assertEqual(sum(event.kind == 'daily_signals_saved' for event in engine.journal.replay()), 1)

    def test_e23_held_lot_prevents_entry_intent_at_save_even_when_entry_signal_is_true(self):
        engine, calendar, session = self.engine()
        record = engine.record
        lot = PositionLot(
            'owned',
            record.form.account_ref,
            record.form.instrument_id,
            record.strategy_id,
            record.version,
            record.policy,
            1000,
            D('10'),
            session.trade_date,
            1000,
        )
        engine.state = replace(engine.state, positions=(lot,))
        cursor = EvaluationCursor(record.strategy_id, record.version, record.form.instrument_id, '1d', session.closes_at)
        with (
            patch('quantlab.trading.application.daily_execution.entry_signal', return_value=True),
            patch('quantlab.trading.application.daily_execution.exit_signal', return_value=False),
        ):
            actions = daily_execution._make_actions(engine, record, cursor, calendar, ())
        self.assertEqual(actions, ())
        self.assertEqual(engine.state.orders, ())

    def test_c1_insufficient_whole_stock_lot_reports_the_exact_size_error(self):
        engine, _, _ = self.engine()
        record = replace(engine.record, parameters=replace(engine.record.parameters, entry_amount=D('1')))
        engine._strategy_spec = lambda spec, record: spec
        engine.submit = Mock()
        with self.assertRaises(DomainError) as caught:
            _entry_decision(engine, record, {}, decision_key='daily-size', daily_signal=object())
        self.assertEqual(caught.exception.code, 'strategy_size_insufficient')
        engine.submit.assert_not_called()

    def test_f4_saved_normal_exit_and_entry_both_keep_entry_level_admission_and_pause_on_denial(self):
        for action in ('ENTRY', 'EXIT'):
            engine, calendar, session = self.engine()
            record = engine.record
            cursor = EvaluationCursor(record.strategy_id, record.version, record.form.instrument_id, '1d', session.closes_at)
            lot = PositionLot(
                'owned',
                record.form.account_ref,
                record.form.instrument_id,
                record.strategy_id,
                record.version,
                record.policy,
                1000,
                D('10'),
                session.trade_date,
                1000,
            )
            intent = create_intent(
                cursor,
                record.form.account_ref,
                action,
                record.form.instrument_id,
                lot.lot_id if action == 'EXIT' else '',
                record.evidence_hash,
                calendar,
                session.closes_at,
            )
            engine.clock.value = intent.not_before + timedelta(minutes=1)
            engine.state = replace(
                engine.state,
                trading_day=intent.target_trade_date,
                positions=(lot,) if action == 'EXIT' else (),
                automatic=replace(engine.state.automatic, daily=replace(engine.state.automatic.daily, intents=(intent,))),
            )
            with (
                self.subTest(action=action),
                patch('quantlab.trading.application.automatic._entry_proofs', side_effect=DomainError('preflight_market')) as proofs,
                patch('quantlab.trading.application.automatic._assert_entry_window'),
                patch('quantlab.trading.application.coordinator._entry_decision'),
            ):
                daily_execution.dispatch_daily(engine)
            proofs.assert_called_once_with(engine)
            self.assertTrue(engine.state.automatic.auto_paused)
            self.assertIn('preflight_market', engine.state.automatic.reasons)
            self.assertEqual(engine.state.automatic.daily.intents[0].phase, 'READY')
            self.assertEqual(engine.state.orders, ())
            self.assertEqual(engine.exit_calls, [])

    def test_f4_successful_saved_normal_exit_stays_reduce_only_and_not_protective(self):
        engine, calendar, session = self.engine()
        record = engine.record
        cursor = EvaluationCursor(record.strategy_id, record.version, record.form.instrument_id, '1d', session.closes_at)
        lot = PositionLot(
            'owned',
            record.form.account_ref,
            record.form.instrument_id,
            record.strategy_id,
            record.version,
            record.policy,
            1000,
            D('10'),
            session.trade_date,
            1000,
        )
        intent = create_intent(cursor, record.form.account_ref, 'EXIT', lot.instrument_id, lot.lot_id, record.evidence_hash, calendar, session.closes_at)
        engine.clock.value = intent.not_before + timedelta(minutes=1)
        engine.state = replace(
            engine.state,
            trading_day=intent.target_trade_date,
            positions=(lot,),
            automatic=replace(engine.state.automatic, daily=replace(engine.state.automatic.daily, intents=(intent,))),
        )
        with patch('quantlab.trading.application.automatic._entry_proofs') as proofs, patch('quantlab.trading.application.automatic._assert_entry_window'):
            daily_execution.dispatch_daily(engine)
        proofs.assert_called_once_with(engine)
        self.assertEqual(tuple((row[0], row[1], row[2]) for row in engine.exit_calls), ((lot.lot_id, False, intent.key),))
        self.assertTrue(engine.state.orders[0].plan.reduce_only)
        self.assertEqual(engine.state.automatic.daily.intents[0].phase, 'DISPATCHED')

    def shared_day(self):
        engine, _, _ = self.engine()
        previous = engine.state.trading_day
        target = engine.calendar.advance(previous, 1)
        calendar = automatic_day_calendar(engine.calendar, engine.catalog.instruments)
        engine.clock.value = calendar.day_session(target).opens_at + timedelta(minutes=20)
        evidence = DailyBaselineEvidence(
            SIM,
            tuple(sorted(engine.gateways)),
            previous,
            target,
            calendar.calendar_id,
            calendar.version,
            engine.fees.version,
            fee_fingerprint(engine.fees),
            D('-17'),
            calendar.day_session(previous).closes_at,
            'APP_VERIFIED_DAY_CLOSE_V1',
            account_previous_close=(('test-stock', D('-17')),),
        )
        engine.state = replace(
            engine.state,
            trading_day=target,
            automatic_daily_evidence=evidence,
            account_daily_baselines=(AccountDailyBaseline('test-stock', target, D('-17'), evidence.source_id),),
        )
        return engine, engine.state.manual_books[0], evidence

    def test_s3_shared_old_book_intentionally_accepts_exact_committed_next_day_proof(self):
        engine, book, _ = self.shared_day()
        before = engine.state
        self.assertNotEqual(book.opening_day, engine.state.trading_day)
        self.assertTrue(manual_day_ready(engine, book))
        self.assertIs(engine.state, before)
        self.assertTrue(engine.state.automatic.daily.authorized_run)

    def test_s3_missing_or_inexact_close_source_amount_date_or_scope_stays_blocked(self):
        engine, book, evidence = self.shared_day()
        original = engine.state
        variants = (
            {'automatic_daily_evidence': None},
            {'account_daily_baselines': ()},
            {'account_daily_baselines': (replace(original.account_daily_baselines[0], previous_close_pnl=D('0')),)},
            {'account_daily_baselines': (replace(original.account_daily_baselines[0], source_id='different-source'),)},
            {'account_daily_baselines': (replace(original.account_daily_baselines[0], trade_date=book.opening_day),)},
            {'automatic_daily_evidence': replace(evidence, trade_date=engine.calendar.advance(engine.state.trading_day, 1))},
        )
        for changes in variants:
            engine.state = replace(original, **changes)
            with self.subTest(changes=changes):
                self.assertFalse(manual_day_ready(engine, book))

    def test_s3_next_day_allowance_requires_simulation_app_virtual_book_and_typed_strategy(self):
        engine, book, _ = self.shared_day()
        engine.configuration.environment = Environment.LOCAL
        self.assertFalse(manual_day_ready(engine, book))
        engine.configuration.environment = SIM
        self.assertFalse(manual_day_ready(engine, replace(book, source='BROKER_BALANCE')))
        engine.state = replace(engine.state, strategies=(replace(engine.record, parameters=None),))
        self.assertFalse(manual_day_ready(engine, book))

    def test_s3_same_day_manual_opening_remains_ready_without_automatic_evidence(self):
        engine, _, _ = self.engine()
        engine.state = replace(engine.state, strategies=(), automatic_daily_evidence=None, account_daily_baselines=())
        self.assertTrue(manual_day_ready(engine, engine.state.manual_books[0]))

    def test_live_commit_guards_state_and_plan_before_validate_journal_or_gateway(self):
        for state_environment, plan_environment in ((Environment.LIVE, Environment.LIVE), (Environment.LIVE, SIM), (SIM, Environment.LIVE)):
            spec = market.instrument()
            plan = market.plan(spec, environment=plan_environment)
            state = AppState(environment=state_environment, stopped=False, reconciled=True)
            reserve = Reservation('owned', 'test-stock', spec.instrument_id, spec.underlying, D('20000'), D('100'), 1000, OrderStatus.RESERVED)
            broker, persist, fence, validate = Mock(), Mock(), Mock(), Mock()
            service = ExecutionService(broker, persist, fence, lambda: market.NOW)
            with self.subTest(state=state_environment, plan=plan_environment), self.assertRaises(DomainError) as caught:
                service.commit(state, plan, HoldingPolicy(), reserve, 'new-key', validate)
            self.assertEqual(caught.exception.code, 'production_orders_disabled')
            persist.assert_not_called()
            fence.assert_not_called()
            validate.assert_not_called()
            broker.submit.assert_not_called()

    def test_live_gateway_mutations_have_an_independent_environment_guard(self):
        case, adapter = live_fixtures.live_adapter()
        plan = market.plan(case.spec, environment=Environment.LIVE)
        adapter.orders['owned'] = BrokerOrder('owned', plan, 0, D('0'), OrderStatus.ACCEPTED, 'broker-owned', market.NOW)
        adapter.trades['owned'] = object()
        with patch.object(adapter, 'inspect', return_value=replace(market.capability(Environment.LIVE), ca_ready=True)):
            for action in (lambda: adapter.submit(plan, 'new-order'), lambda: adapter.cancel('owned'), lambda: adapter.amend('owned', D('20.1'), 1000)):
                with self.assertRaises(DomainError) as caught:
                    action()
                self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.assertEqual(case.client.placed, [])
        self.assertEqual(case.client.order_calls, [])
        case.client.cancel_order.assert_not_called()
        case.client.update_order.assert_not_called()

    def test_live_sdk_facade_guards_each_native_mutation_independently(self):
        for operation in ('place_order', 'update_order', 'cancel_order'):
            vendor = sdk.StrictSDK()
            vendor.simulation = vendor.signed = vendor.ca_ready = True
            facade = ShioajiSDKFacade(vendor, SimpleNamespace(__version__='1.7.9'), environment=Environment.LIVE)
            arguments = (sdk.contract(), object()) if operation == 'place_order' else (object(),)
            keywords = {'price': 20.0, 'qty': 1} if operation == 'update_order' else {}
            with self.subTest(operation=operation):
                with self.assertRaises(DomainError) as caught:
                    getattr(facade, operation)(*arguments, **keywords)
                self.assertEqual(caught.exception.code, 'production_orders_disabled')
                self.assertEqual(vendor._seen, [])
