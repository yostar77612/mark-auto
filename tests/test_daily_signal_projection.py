"""Pure memo values are not admission; native missing preparation never computes."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_official_daily_admission as fixture
from quantlab.trading.application import daily_signal_projection as projection
from quantlab.trading.application.codec import dumps
from quantlab.trading.application.codec import loads
from quantlab.trading.application.contracts import UiReceipt
from quantlab.trading.application.daily_execution import observe_daily
from quantlab.trading.application.daily_signal_data import official_daily_result, stock_daily_window, assert_daily_intent_source, daily_signal_views
from quantlab.trading.application.reservations import current_reservations
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.daily_source_cache import prepare_daily_sources
from quantlab.trading.runtime.automatic import AutomaticRuntime
from quantlab.trading.runtime.daily_deployment import prepare_daily_deployment


def clear_cache():
    with projection._mutex:
        projection._cache.clear()


class DailySignalProjectionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.OfficialDailyAdmissionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.addCleanup(clear_cache)
        clear_cache()
        self.engine, self.source = self.case.engine, self.case.source
        self.history, self.calendar, self.basis, self.through = self.case.history, self.case.calendar, self.case.result.daily_basis, self.case.day

    def prepare(self, history=None, calendar=None, basis=None, through=None):
        return projection.prepare_daily_projection(history or self.history, calendar or self.calendar, basis or self.basis, through or self.through)

    def cached(self, history=None, calendar=None, basis=None, through=None):
        return projection.daily_projection(history or self.history, calendar or self.calendar, basis or self.basis, through or self.through, cached_only=True)

    def missing(self, **values):
        with self.assertRaises(DomainError) as caught:
            self.cached(**values)
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')

    def bundle(self):
        return SimpleNamespace(
            launch=SimpleNamespace(environment=Environment.BROKER_SIMULATION),
            engine=self.engine,
            lock=RLock(),
            closing=False,
            resources_closed=False,
            control_failed=False,
        )

    def test_original_committed_wire_dataset_and_signal_hashes_are_exact(self):
        # Generated from committed678db76's original functions with this fixed
        # labelled synthetic fixture; neither result is a new hash scheme.
        result = self.prepare()
        self.assertEqual(result.dataset_id, 'a7ce61df078432b889d648b48a7b7c89f4bb71419ad81c510bf606b24f26a2f6')
        self.assertEqual(result.signal_fingerprint, '6c0898ae24857be99733bb2d50d3067bfd9ecd24a1e70763efcad054a1d5db02')
        self.assertEqual(result.research_basis.raw_digest, '2f2abb61fc02572e070b72da69b9990521209a53ca16f1eb644a1614d9cabf54')
        self.assertEqual(result.research_basis.source_digest, self.history.source_digest)
        self.assertEqual(result.signals, self.history.signal_history(self.calendar, self.through))

    def test_native_miss_refuses_without_calling_math_or_changing_cache(self):
        with patch.object(projection, '_derive_daily_projection', side_effect=AssertionError('cold locked work')) as derive:
            self.missing()
        derive.assert_not_called()
        self.assertEqual(len(projection._cache), 0)

    def test_prepared_hit_reuses_values_without_rebuilding_or_reencoding(self):
        expected = self.prepare()
        with patch.object(projection, '_derive_daily_projection', side_effect=AssertionError('rebuild')) as derive:
            self.assertIs(self.cached(), expected)
            self.assertIs(self.cached(), expected)
        derive.assert_not_called()

    def test_derivation_runs_outside_the_cache_mutex(self):
        original = projection._derive_daily_projection

        def derive(*args):
            self.assertTrue(projection._mutex.acquire(blocking=False), 'math held cache mutex')
            projection._mutex.release()
            return original(*args)

        with patch.object(projection, '_derive_daily_projection', side_effect=derive) as called:
            self.prepare()
        called.assert_called_once()

    def test_cache_is_bounded_and_eviction_is_lru_with_fail_closed_miss(self):
        first = self.prepare()
        variants = [replace(self.history, observed_at=self.history.observed_at + timedelta(seconds=n)) for n in range(1, projection.MAX_PROJECTIONS + 1)]
        for history in variants[:-1]:
            self.prepare(history=history)
        self.assertEqual(len(projection._cache), 128)
        self.assertIs(self.cached(), first)  # The initial entry is now newest.
        self.prepare(history=variants[-1])
        self.assertEqual(len(projection._cache), 128)
        self.assertIs(self.cached(), first)
        self.missing(history=variants[0])

    def test_research_end_history_is_an_independent_key_that_must_be_prepared(self):
        self.prepare()
        training = self.history.trim(self.basis.start, self.basis.end)
        self.missing(history=training, through=self.basis.end)
        result = self.prepare(history=training, through=self.basis.end)
        self.assertEqual(result.dataset_id, self.prepare().dataset_id)
        self.assertIs(self.cached(history=training, through=self.basis.end), result)

    def test_original_transport_basis_is_retained_in_dataset_and_cache_identity(self):
        before = self.prepare()
        basis = replace(self.basis, source_digest='d' * 64)
        self.missing(basis=basis)
        after = self.prepare(basis=basis)
        self.assertNotEqual(after.dataset_id, before.dataset_id)
        raw = self.history.trim(basis.start, basis.end).raw_completed(self.calendar)
        self.assertEqual(after.dataset_id, sha256(dumps((raw, basis)).encode()).hexdigest())
        self.assertEqual(after.signal_fingerprint, before.signal_fingerprint)

    def test_transport_refresh_remains_compatible_but_needs_current_value_key(self):
        before = self.prepare()
        history = replace(self.history, source_digest='e' * 64, observed_at=self.history.observed_at + timedelta(seconds=1))
        self.missing(history=history)
        after = self.prepare(history=history)
        self.assertTrue(before.research_basis.compatible(after.research_basis))
        self.assertEqual(after.dataset_id, before.dataset_id)
        self.assertEqual(after.signal_fingerprint, before.signal_fingerprint)

    def test_complete_calendar_content_not_only_name_and_version_is_keyed(self):
        before = self.prepare()
        calendar = replace(
            self.calendar,
            sessions=tuple(
                replace(row, opens_at=row.opens_at + timedelta(seconds=1), closes_at=row.closes_at + timedelta(seconds=1)) for row in self.calendar.sessions
            ),
        )
        self.assertEqual((calendar.calendar_id, calendar.version), (self.calendar.calendar_id, self.calendar.version))
        self.missing(calendar=calendar)
        after = self.prepare(calendar=calendar)
        self.assertNotEqual(after.dataset_id, before.dataset_id)
        self.assertNotEqual(after.signal_fingerprint, before.signal_fingerprint)

    def test_raw_price_and_event_values_cannot_reuse_an_old_projection(self):
        before = self.prepare()
        history = replace(self.history, bars=(replace(self.history.bars[0], close=Decimal(11), high=Decimal(11)), *self.history.bars[1:]))
        self.missing(history=history)
        self.assertNotEqual(self.prepare(history=history).dataset_id, before.dataset_id)
        event = fixture.CorporateAction(
            self.history.instrument_id, self.history.bars[-1].trade_date, Decimal(10), Decimal(9), 'a' * 64, 'https://www.twse.com.tw/test'
        )
        revised = replace(self.history, events=(event,))
        self.missing(history=revised)
        self.assertNotEqual(self.prepare(history=revised).signal_fingerprint, before.signal_fingerprint)

    def test_through_day_and_original_research_range_are_distinct_key_inputs(self):
        self.prepare()
        day = self.history.bars[-2].trade_date
        self.missing(through=day)
        basis = replace(self.basis, start=self.history.bars[1].trade_date)
        self.missing(basis=basis)

    def test_native_window_missing_math_preserves_cursor_intents_and_reservations(self):
        self.engine.daily_signal_cached_only = True
        before = self.engine.state
        reservations = current_reservations(self.engine)
        with patch.object(projection, '_derive_daily_projection', side_effect=AssertionError('locked cold math')) as derive:
            observe_daily(self.engine, ())
        derive.assert_not_called()
        self.assertEqual(self.engine.state.automatic.evaluations, before.automatic.evaluations)
        self.assertEqual(self.engine.state.automatic.daily.intents, before.automatic.daily.intents)
        self.assertEqual(current_reservations(self.engine), reservations)
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_not_available')
        self.assertTrue(self.source.requests, 'current source authority must still be read before memo lookup')

    def test_native_preparation_warms_both_exact_histories_outside_all_writer_locks(self):
        self.engine.daily_signal_cached_only = True
        bundle = self.bundle()
        original = projection._derive_daily_projection

        def derive(*args):
            self.assertFalse(bundle.lock._is_owned())
            self.assertFalse(self.engine.lock._is_owned())
            return original(*args)

        with patch.object(projection, '_derive_daily_projection', side_effect=derive) as called:
            prepare_daily_sources(bundle, self.engine)
        self.assertEqual(called.call_count, 2)
        self.assertEqual({request[1] for request in self.source.requests}, {self.through, self.basis.end})
        training = self.source.history(self.history.instrument_id, self.calendar, through=self.basis.end, start=self.basis.start)
        current = self.source.history(self.history.instrument_id, self.calendar, through=self.through, start=self.basis.start)
        with patch.object(projection, '_derive_daily_projection', side_effect=AssertionError('not prepared')) as unexpected:
            self.cached(history=training, through=self.basis.end)
            self.cached(history=current)
            self.assertIsNotNone(stock_daily_window(self.engine, self.case.record, self.history.instrument_id, self.calendar))
        unexpected.assert_not_called()

    def test_locked_native_source_miss_refuses_without_history_fallback(self):
        self.engine.daily_signal_cached_only = True
        with patch.object(self.source, 'cached_history', return_value=None) as lookup:
            with patch.object(self.source, 'history', side_effect=AssertionError('locked acquisition')) as history:
                self.assertIsNone(stock_daily_window(self.engine, self.case.record, self.history.instrument_id, self.calendar))
        self.assertEqual(lookup.call_count, 1)
        history.assert_not_called()
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_not_available')

    def test_locked_native_source_hit_never_calls_history_method(self):
        self.engine.daily_signal_cached_only = True
        self.prepare()
        original = self.source.cached_history
        with patch.object(self.source, 'cached_history', wraps=original) as lookup:
            with patch.object(self.source, 'history', side_effect=AssertionError('hot history method')) as history:
                self.assertIsNotNone(stock_daily_window(self.engine, self.case.record, self.history.instrument_id, self.calendar))
        self.assertGreater(lookup.call_count, 0)
        history.assert_not_called()

    def test_pump_preparation_hot_history_never_calls_acquisition_method(self):
        self.engine.daily_signal_cached_only = True
        bundle = self.bundle()
        expected = {
            day: self.source.history(self.history.instrument_id, self.calendar, through=day, start=self.basis.start) for day in (self.through, self.basis.end)
        }

        def cached(instrument_id, calendar, *, through, start):
            self.assertFalse(bundle.lock._is_owned())
            self.assertFalse(self.engine.lock._is_owned())
            self.assertEqual((instrument_id, calendar, start), (self.history.instrument_id, self.calendar, self.basis.start))
            return expected[through]

        with patch.object(self.source, 'cached_history', side_effect=cached, create=True) as lookup:
            with patch.object(self.source, 'history', side_effect=AssertionError('hot source.history call')) as history:
                prepare_daily_sources(bundle, self.engine)
                prepare_daily_sources(bundle, self.engine)
        self.assertEqual(lookup.call_count, 4)
        history.assert_not_called()
        self.assertIsNotNone(self.cached(history=expected[self.through]))
        self.assertIsNotNone(self.cached(history=expected[self.basis.end], through=self.basis.end))

    def test_pump_preparation_only_absent_cache_acquires_outside_writer_locks(self):
        self.engine.daily_signal_cached_only = True
        bundle = self.bundle()
        original = self.source.history

        def acquire(*args, **kwargs):
            self.assertFalse(bundle.lock._is_owned())
            self.assertFalse(self.engine.lock._is_owned())
            return original(*args, **kwargs)

        with patch.object(self.source, 'cached_history', return_value=None, create=True) as lookup:
            with patch.object(self.source, 'history', side_effect=acquire) as history:
                prepare_daily_sources(bundle, self.engine)
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(history.call_count, 2)
        self.assertEqual({call.kwargs['through'] for call in history.call_args_list}, {self.through, self.basis.end})

    def test_pump_preparation_never_retries_cache_authority_or_temporal_refusals(self):
        self.engine.daily_signal_cached_only = True
        for code in ('daily_signal_source_unverified', 'daily_signal_not_available', 'official_stock_invalid'):
            with self.subTest(code=code):
                with patch.object(self.source, 'cached_history', side_effect=DomainError(code), create=True) as lookup:
                    with patch.object(self.source, 'history') as history:
                        prepare_daily_sources(self.bundle(), self.engine)
                self.assertEqual(lookup.call_count, 2)
                history.assert_not_called()
        self.assertEqual(len(projection._cache), 0)

    def test_hit_never_caches_source_authority_or_clock_evidence_comparisons(self):
        self.prepare()
        self.engine.daily_signal_cached_only = True
        self.source.cached_history = Mock(side_effect=DomainError('daily_signal_source_unverified'))
        self.assertIsNone(stock_daily_window(self.engine, self.case.record, self.history.instrument_id, self.calendar))
        self.assertEqual(daily_signal_views(self.engine)[0].reason, 'daily_signal_source_unverified')
        self.source.cached_history.assert_called_once()
        altered = replace(self.case.record, evidence_hash='bad')
        with self.assertRaises(DomainError) as caught:
            official_daily_result(self.engine, altered, self.case.result, history=self.history)
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        self.engine.clock.value = self.history.observed_at - timedelta(seconds=1)
        with self.assertRaises(DomainError) as caught:
            official_daily_result(self.engine, self.case.record, self.case.result, history=self.history)
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')

    def test_saved_signal_guard_uses_prepared_math_but_rechecks_actual_saved_hash(self):
        intent = self.case.save()
        self.engine.daily_signal_cached_only = True
        # save used the same immutable through-day values, so it is prepared.
        with self.assertRaises(DomainError) as caught:
            assert_daily_intent_source(self.engine, self.case.record, replace(intent, data_fingerprint='f' * 64))
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        clear_cache()
        with patch.object(projection, '_derive_daily_projection', side_effect=AssertionError('cold dispatch')) as derive:
            with self.assertRaises(DomainError) as caught:
                assert_daily_intent_source(self.engine, self.case.record, intent)
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')
        derive.assert_not_called()

    def test_actual_automatic_pump_contains_ordinary_preparation_errors_without_poisoning_journal(self):
        self.engine.daily_signal_cached_only = True
        bundle = self.bundle()
        bundle.sinopac_connection = SimpleNamespace(lock=RLock())
        bundle.manual_runtime = SimpleNamespace(stamp=None)
        runtime = AutomaticRuntime(bundle)
        runtime.owner_stamp = self.engine.automatic_owner_stamp  # Existing explicit synthetic host proof.
        before = self.engine.state
        reservations = current_reservations(self.engine)
        with patch.object(projection, '_derive_daily_projection', side_effect=OverflowError('synthetic semantic read')) as derive:
            runtime.pump()
        self.assertGreater(derive.call_count, 0, 'the actual preparation boundary must be reached')
        self.assertFalse(self.engine.storage_failed)
        self.assertEqual(self.engine.state.orders, before.orders)
        self.assertEqual(self.engine.state.automatic.evaluations, before.automatic.evaluations)
        self.assertEqual(self.engine.state.automatic.daily.intents, before.automatic.daily.intents)
        self.assertEqual(current_reservations(self.engine), reservations)
        self.assertEqual(self.prepare().dataset_id, 'a7ce61df078432b889d648b48a7b7c89f4bb71419ad81c510bf606b24f26a2f6')

    def test_preparation_keeps_domain_codes_and_never_catches_base_exceptions(self):
        for exception, code in (
            (OverflowError('ordinary semantic error'), 'daily_signal_source_unverified'),
            (DomainError('daily_signal_not_available'), 'daily_signal_not_available'),
        ):
            with self.subTest(code=code), patch.object(projection, '_derive_daily_projection', side_effect=exception):
                with self.assertRaises(DomainError) as caught:
                    self.prepare()
                self.assertEqual(caught.exception.code, code)
        with patch.object(projection, '_derive_daily_projection', side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.prepare()
        self.assertEqual(len(projection._cache), 0)

    def test_public_deployment_prepares_exact_research_end_projection_before_locked_guard(self):
        import test_daily_deployment as deployment

        case = deployment.DailyDeploymentTests()
        case.setUp()
        self.addCleanup(case.doCleanups)

        def execute(command):
            with case.engine.lock:
                official_daily_result(case.engine, case.record, loads(case.record.research_blob))
            return UiReceipt(True, 'completed', '')

        case.facade.execute.side_effect = execute
        with patch.object(projection, '_derive_daily_projection', wraps=projection._derive_daily_projection) as derive:
            receipt = prepare_daily_deployment(case.bundle, case.command)
        self.assertTrue(receipt.accepted, receipt.code)
        self.assertEqual(derive.call_count, 1, 'the locked guard must hit the exact outside-prepared training history')


if __name__ == '__main__':
    unittest.main()
