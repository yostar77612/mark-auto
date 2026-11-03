"""Independent regression probes for cursor, source-failure and view guards."""

from dataclasses import replace
from datetime import timedelta
import sqlite3
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_official_daily_admission as fixture
from quantlab.trading.application.daily_execution import observe_daily
from quantlab.trading.application.daily_signal_data import assert_daily_intent_source, daily_signal_views, stock_daily_window, uses_official_daily
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.daily_source_cache import prepare_daily_sources
from quantlab.trading.runtime.bootstrap import RuntimeBundle


class DailyBasisReviewApplicationTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.OfficialDailyAdmissionTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.engine, self.source = self.case.engine, self.case.source

    def test_claimed_cursor_returns_before_source_even_without_saved_actions(self):
        with patch('quantlab.trading.application.daily_execution._make_actions', return_value=()):
            observe_daily(self.engine, ())
        self.assertEqual(self.engine.state.automatic.evaluations[0].phase, 'COMPLETED')
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.source.history = Mock(side_effect=AssertionError('claimed cursor must not rebuild'))
        observe_daily(self.engine, ())
        self.source.history.assert_not_called()

    def test_existing_intent_blocks_reconstruction_even_without_evaluation_row(self):
        intent = self.case.save()
        self.engine.state = replace(self.engine.state, automatic=replace(self.engine.state.automatic, evaluations=()))
        self.source.history = Mock(side_effect=AssertionError('saved intent must not rebuild'))
        observe_daily(self.engine, ())
        self.source.history.assert_not_called()
        self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))

    def test_every_source_exception_is_recoverable_and_never_claims(self):
        original = self.source.history
        for error in (OverflowError('bad ROC year'), sqlite3.OperationalError('temporary read'), RuntimeError('provider read')):
            with self.subTest(error=type(error).__name__):
                self.source.history = Mock(side_effect=error)
                observe_daily(self.engine, ())
                self.assertFalse(self.engine.storage_failed)
                self.assertEqual(self.engine.state.automatic.evaluations, ())
                self.assertEqual(self.engine.state.automatic.daily.intents, ())
                self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_source_unverified')
        self.source.history = original
        observe_daily(self.engine, ())
        self.assertEqual(len(self.engine.state.automatic.daily.intents), 1)
        self.assertFalse(self.engine.storage_failed)

    def test_application_window_boundary_contains_non_source_parse_failure(self):
        with patch('quantlab.trading.application.daily_signal_data.loads', side_effect=OverflowError()):
            self.assertIsNone(self.case.window())
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_source_unverified')

    def test_dispatch_mismatch_immediately_invalidates_a_verified_view(self):
        intent = self.case.save()
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'VERIFIED')
        self.source.publish(
            replace(self.case.history, bars=(*self.case.history.bars[:-1], replace(self.case.history.bars[-1], close=fixture.D('11'), high=fixture.D('11'))))
        )
        with self.assertRaises(DomainError) as caught:
            assert_daily_intent_source(self.engine, self.case.record, intent)
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        view = daily_signal_views(self.engine)[0]
        self.assertEqual((view.status, view.reason), ('UNVERIFIED', 'daily_signal_basis_mismatch'))

    def test_view_expires_without_any_source_reads(self):
        self.assertIsNotNone(self.case.window())
        view = daily_signal_views(self.engine)[0]
        self.assertEqual(view.verified_at, self.engine.clock.now())
        self.assertEqual(view.available_at, self.case.history.observed_at)
        self.source.history = Mock(side_effect=AssertionError('render must be cache-only'))
        self.engine.clock.value = view.expires_at - timedelta(microseconds=1)
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'VERIFIED')
        self.engine.clock.value = view.expires_at
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'UNVERIFIED')
        self.source.history.assert_not_called()

    def test_official_daily_discriminator_requires_broker_simulation_independently(self):
        self.assertTrue(uses_official_daily(self.case.record))
        for environment in (Environment.LOCAL, Environment.LIVE):
            record = replace(self.case.record, form=replace(self.case.record.form, environment=environment))
            self.assertFalse(uses_official_daily(record))

    def test_locked_read_miss_never_falls_back_to_full_verification(self):
        from quantlab.trading.application.reservations import current_reservations

        self.engine.daily_signal_cached_only = True
        before = self.engine.state
        reserved = current_reservations(self.engine)
        self.source.cached_history = Mock(return_value=None)
        self.source.history = Mock(side_effect=AssertionError('locked full verification'))
        self.assertIsNone(stock_daily_window(self.engine, self.case.record, self.case.spec.instrument_id, self.case.calendar))
        self.source.cached_history.assert_called_once_with(
            self.case.spec.instrument_id, self.case.calendar, through=self.case.day, start=self.case.result.daily_basis.start
        )
        self.source.history.assert_not_called()
        self.assertEqual(self.engine.state.automatic.daily.intents, ())
        self.assertEqual(self.engine.state.orders, before.orders)
        self.assertEqual(self.engine.state.automatic.evaluations, before.automatic.evaluations)
        self.assertEqual(current_reservations(self.engine), reserved)
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_not_available')

    def test_dispatch_source_io_error_is_a_typed_refusal_with_invalidated_view(self):
        intent = self.case.save()
        self.source.history = Mock(side_effect=sqlite3.OperationalError('temporary read'))
        with self.assertRaises(DomainError) as caught:
            assert_daily_intent_source(self.engine, self.case.record, intent)
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        self.assertEqual(daily_signal_views(self.engine)[0].status, 'UNVERIFIED')
        self.assertFalse(self.engine.storage_failed)

    def test_preparation_does_not_hold_bundle_engine_or_owner_locks(self):
        from threading import RLock, Thread

        self.engine.daily_signal_cached_only = True
        owner_lock = RLock()
        bundle = SimpleNamespace(
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=self.engine,
            lock=RLock(),
            closing=False,
            resources_closed=False,
            control_failed=False,
        )
        checked = []
        original = self.source.history

        def unlocked(label):
            def peer():
                with bundle.lock, self.engine.lock, owner_lock:
                    checked.append(label)

            thread = Thread(target=peer)
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive(), 'source IO holds an ownership lock')

        def read(*args, **kwargs):
            unlocked('history')
            return original(*args, **kwargs)

        def miss(*args, **kwargs):
            unlocked('cached_history')
            return None

        self.source.cached_history = Mock(side_effect=miss)
        self.source.history = Mock(side_effect=read)
        prepare_daily_sources(bundle, self.engine)
        self.assertTrue(checked)
        self.assertEqual(checked.count('cached_history'), 2)
        self.assertEqual(checked.count('history'), 2)
        self.assertEqual(self.source.cached_history.call_count, 2)
        self.assertEqual(self.source.history.call_count, 2)
        self.assertEqual({row.kwargs['through'] for row in self.source.history.call_args_list}, {self.case.day, self.case.result.daily_basis.end})

    def test_preparation_skips_already_evaluated_cursor(self):
        with patch('quantlab.trading.application.daily_execution._make_actions', return_value=()):
            observe_daily(self.engine, ())
        self.engine.daily_signal_cached_only = True
        from threading import RLock

        bundle = SimpleNamespace(
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=self.engine,
            lock=RLock(),
            closing=False,
            resources_closed=False,
            control_failed=False,
        )
        self.source.history = Mock(side_effect=AssertionError('no duplicate warming'))
        prepare_daily_sources(bundle, self.engine)
        self.source.history.assert_not_called()

    def test_saved_intent_is_not_prewarmed_until_its_dispatch_window(self):
        self.case.save()
        self.engine.daily_signal_cached_only = True
        from threading import RLock

        bundle = SimpleNamespace(
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=self.engine,
            lock=RLock(),
            closing=False,
            resources_closed=False,
            control_failed=False,
        )
        self.source.cached_history = Mock(side_effect=AssertionError('saved pre-open intent needs no new window'))
        self.source.history = Mock(side_effect=AssertionError('saved pre-open intent needs no new window'))
        prepare_daily_sources(bundle, self.engine)
        self.source.history.assert_not_called()
        self.source.cached_history.assert_not_called()

    def test_expired_intent_never_rebuilds_a_dispatch_window(self):
        intent = self.case.save()
        self.engine.daily_signal_cached_only = True
        self.engine.clock.value = intent.deadline
        self.engine.state = replace(self.engine.state, strategies=(replace(self.case.record, state='DISABLED'),))
        from threading import RLock

        bundle = SimpleNamespace(
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=self.engine,
            lock=RLock(),
            closing=False,
            resources_closed=False,
            control_failed=False,
        )
        self.source.cached_history = Mock(side_effect=AssertionError('expired intent must not rebuild'))
        self.source.history = Mock(side_effect=AssertionError('expired intent must not rebuild'))
        prepare_daily_sources(bundle, self.engine)
        self.source.history.assert_not_called()
        self.source.cached_history.assert_not_called()

    def test_typed_sim_entry_without_manual_book_cannot_select_legacy_admission(self):
        engine = self.engine
        self.case.next_open()
        record = replace(self.case.record, parameters=replace(self.case.record.parameters, bar_interval='5m'))
        order = engine.order('plan-fixture')
        plan = replace(order.plan, strategy_id=record.strategy_id, strategy_version=record.version)
        engine.state = replace(engine.state, strategies=(record,), manual_books=(), orders=())
        plan = replace(plan, state_version=engine.state.version)
        engine.automatic_entry_check = Mock()
        engine._assert_strategy_evidence = Mock()
        engine._strategy_calendar = lambda *_: self.case.calendar
        engine.automatic_entry_validator = Mock(side_effect=DomainError('preflight_connection'))
        engine.account = Mock(side_effect=AssertionError('missing manual book must not choose legacy admission'))
        with (
            patch('quantlab.trading.application.sessions.synchronize_session'),
            patch('quantlab.trading.application.automatic_capacity.assert_automatic_observation'),
        ):
            with self.assertRaises(DomainError) as caught:
                TradingEngine.submit(engine, plan, record.policy, 'no-legacy-entry')
        self.assertEqual(caught.exception.code, 'preflight_connection')
        engine.automatic_entry_validator.assert_called_once_with(plan.account_ref)
        engine.account.assert_not_called()
        self.assertEqual(engine.state.orders, ())

    def test_untyped_sim_entry_cannot_use_the_legacy_account_admission(self):
        engine = self.engine
        self.assertIs(engine.configuration.environment, Environment.BROKER_SIMULATION)
        engine.configuration.read_only = False
        engine.state = replace(engine.state, stopped=False)
        bundle = SimpleNamespace(
            lock=RLock(),
            engine=engine,
            market_terminal=None,
            _expire_connection=Mock(),
            closing=False,
            manual_runtime=None,
            query_instruments=(),
            control_failed=False,
        )
        with (
            patch('quantlab.trading.application.coordinator.run_cycle') as run,
            patch('quantlab.trading.application.market_cycle.poll_market'),
        ):
            RuntimeBundle.pump(bundle)
        # Protective processing remains scheduled, without legacy entry authority.
        run.assert_called_once_with(engine, engine.history, allow_entries=False)
