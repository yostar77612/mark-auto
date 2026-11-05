"""PR #171 review regressions: retryable failures stay retryable, unknown ones stay terminal.

Synthetic only: no network, market data, OOS or broker. A planned window, once consumed, is
never refunded by any path here.
"""

from contextlib import closing
from datetime import timedelta
import json
import sqlite3
from threading import Thread
import time
import unittest
from unittest.mock import patch

from quantlab.core import content_hash
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import e1_protocol as protocol
from quantlab.trading.runtime import e1_qualification as qualification
from quantlab.trading.runtime import e1_source as source
from quantlab.trading.runtime import e1_store as store
from quantlab.verdict import LEVELS
from tests import test_e1_qualification as fixtures
from tests.test_e1_qualification import AFTER

# The synthetic fixture without its own tests (they run once, in test_e1_qualification).
E1QualificationTests = type(
    'E1Fixture', (fixtures.E1QualificationTests,), {name: None for name in dir(fixtures.E1QualificationTests) if name.startswith('test_')}
)


def busy_error():
    error = sqlite3.OperationalError('database is locked')
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


class RetryableFailureTests(E1QualificationTests):
    def test_projection_errors_are_retryable_but_conflicts_stay_terminal(self):
        ref = self.freeze()
        rows = json.loads(self.raw)
        rows[3]['Open'] = 'x' * 500  # one malformed planned row
        self.fetch.return_value = json.dumps(rows).encode()
        self.now = AFTER
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.state(ref)[1], 'reserved')
        self.fetch.return_value = self.raw
        self.assertIsNone(self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.state(ref)[1], 'captured')
        rows = json.loads(self.raw)
        rows[0]['Last'] = '99999'  # conflicting revision of stored data
        self.fetch.return_value = json.dumps(rows).encode()
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.state(ref)[1], 'failed')

    def test_retry_after_captured_state_returns_to_captured(self):
        ref = self.freeze()
        self.fetch.return_value = json.dumps(json.loads(self.raw)[:-1]).encode()
        self.capture(ref)
        self.fetch.side_effect = TimeoutError('slow')
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.state(ref)[1], 'captured')

    def test_process_exit_during_fetch_is_terminal_and_reraised(self):
        ref = self.freeze()
        self.now = AFTER

        self.fetch.side_effect = SystemExit('process ended')
        with self.assertRaises(SystemExit):
            self.host.capture(ref, network_authorized=True)
        self.assertEqual(self.state(ref)[1], 'failed')

    def test_shutdown_requests_are_recorded_then_reraised_unchanged(self):
        ref = self.freeze()
        self.now = AFTER
        self.fetch.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.host.capture(ref, network_authorized=True)
        self.assertEqual(self.state(ref)[1], 'failed')  # accounting kept; never swallowed

    def test_evaluate_shutdown_request_is_recorded_then_reraised(self):
        ref = self.freeze()
        self.capture(ref)
        with patch.object(qualification, '_run_bounded', side_effect=SystemExit(7)), self.assertRaises(SystemExit) as raised:
            self.host.evaluate(ref)
        self.assertEqual(raised.exception.code, 7)
        self.assertEqual(self.state(ref)[1], 'failed')
        self.assertEqual(self.summaries(), ())

    def test_exceptions_remain_redacted_domain_errors(self):
        ref = self.freeze()
        self.capture(ref)
        with patch.object(qualification, '_run_bounded', side_effect=RuntimeError('private')):
            self.unavailable(lambda: self.host.evaluate(ref))
        self.assertEqual(self.state(ref)[1], 'failed')

    def test_evaluate_before_sessions_close_or_wrong_state_changes_nothing(self):
        ref = self.freeze()
        self.now = self.calendar.sessions[0]['end'] + timedelta(seconds=1)
        self.unavailable(lambda: self.host.evaluate(ref))
        self.assertEqual(self.state(ref)[1], 'reserved')

    def test_lock_contention_in_the_write_phase_is_retryable(self):
        ref = self.freeze()
        self.now = AFTER
        real = store.connection
        calls = []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) == 3:  # load, claim, then the capture write
                raise busy_error()
            return real(*args, **kwargs)

        with patch.object(store, 'connection', side_effect=flaky):
            self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.state(ref)[1], 'reserved')
        self.capture(ref)
        self.assertEqual(self.state(ref)[1], 'captured')


class RegistryContentionTests(E1QualificationTests):
    def hold(self, seconds):
        """Another process-like writer (as research _reserve_holdout) holding the registry."""
        ready = []

        def work():
            with closing(sqlite3.connect(self.registry, timeout=1)) as db:
                db.execute('BEGIN IMMEDIATE')
                ready.append(1)
                time.sleep(seconds)
                db.rollback()

        thread = Thread(target=work)
        thread.start()
        deadline = time.monotonic() + 5
        while not ready and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready, 'lock holder did not start')
        return thread

    def test_every_e1_connection_waits_for_a_lock_instead_of_failing_at_once(self):
        ref = self.freeze()
        self.now = AFTER
        thread = self.hold(0.6)
        began = time.monotonic()
        try:
            self.assertIsNone(self.host.capture(ref, network_authorized=True))
        finally:
            thread.join()
        self.assertGreaterEqual(time.monotonic() - began, 0.4)
        self.assertEqual(self.state(ref)[1], 'captured')

    def test_read_connections_wait_too(self):
        ref = self.freeze()
        thread = self.hold(0.5)
        try:
            self.assertEqual(self.state(ref)[1], 'reserved')
        finally:
            thread.join()

    def test_wait_is_bounded_and_contention_before_the_claim_changes_nothing(self):
        ref = self.freeze()
        self.now = AFTER
        thread = self.hold(1.5)
        try:
            with patch.object(store, 'BUSY_SECONDS', 0.2):
                began = time.monotonic()
                self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
                self.assertLess(time.monotonic() - began, 1.2)
        finally:
            thread.join()
        self.fetch.assert_not_called()
        self.assertEqual(self.state(ref)[1], 'reserved')
        self.capture(ref)
        self.assertEqual(self.state(ref)[1], 'captured')

    def test_freeze_waits_for_the_registry_too(self):
        with store.connection(self.registry, write=True, create=True):
            pass  # an existing, empty bootstrap registry that another writer then holds
        thread = self.hold(0.5)
        try:
            ref = self.freeze()
        finally:
            thread.join()
        self.assertEqual(self.state(ref)[1], 'reserved')

    def test_statement_budget_does_not_include_lock_wait(self):
        ref = self.freeze()
        with patch.object(store, 'STATEMENT_SECONDS', 0.05):
            thread = self.hold(0.3)
            try:
                self.assertEqual(self.state(ref)[1], 'reserved')
            finally:
                thread.join()


class SourceHardeningTests(unittest.TestCase):
    def plan_rows(self):
        fixture = E1QualificationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ref = fixture.freeze()
        plan = fixture.state(ref)[0]
        return fixture, plan

    def test_row_cap_matches_market_providers_and_is_not_tmf_sized(self):
        fixture, plan = self.plan_rows()
        rows = json.loads(fixture.raw)
        other = {key: 'x' for key in source.FIELDS}
        other['Contract'] = 'TX'
        padded = [dict(other) for _ in range(30000)] + rows  # an all-products response
        selected, digest = source.projected_rows(json.dumps(padded).encode(), plan, AFTER)
        self.assertEqual(len(selected), len(rows))
        self.assertEqual(len(digest), 64)
        too_many = [dict(other) for _ in range(source.MAX_ROWS + 1)]
        with self.assertRaises(DomainError):
            source.projected_rows(json.dumps(too_many).encode(), plan, AFTER)

    def test_malformed_tmf_rows_are_still_refused(self):
        fixture, plan = self.plan_rows()
        rows = json.loads(fixture.raw)
        rows[0]['Open'] = 5
        with self.assertRaises(DomainError):
            source.projected_rows(json.dumps(rows).encode(), plan, AFTER)
        rows = json.loads(fixture.raw)
        rows.append(dict(rows[0]))
        with self.assertRaises(DomainError):
            source.projected_rows(json.dumps(rows).encode(), plan, AFTER)

    def test_total_deadline_is_enforced_after_the_read(self):
        from unittest.mock import Mock

        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.geturl.return_value = protocol.SOURCE_URL
        response.headers.get_content_type.return_value = 'application/json'
        response.read.return_value = b'[]'
        opener = Mock()
        opener.open.return_value = response
        clock = iter((0.0, 1000.0, 1000.0, 1000.0))
        with patch.object(source, 'build_opener', return_value=opener), patch.object(source.time, 'monotonic', side_effect=lambda: next(clock)):
            with self.assertRaises(DomainError):
                source.fetch_daily()

    def test_source_url_must_stay_the_market_providers_endpoint(self):
        with patch.object(source, 'SOURCE_URL', 'https://example.invalid/'), self.assertRaises(DomainError):
            source.fetch_daily()


class SharedOutcomeShapeTests(unittest.TestCase):
    def valid(self, **changes):
        value = {'verdict': 'statistical_edge', 'sample_count': 40, 'result_hash': 'a' * 64}
        value.update(changes)
        return value

    def test_shape_rules_are_shared_and_exact(self):
        self.assertTrue(protocol.valid_outcome_shape(self.valid()))
        for bad in (
            self.valid(verdict='nope'),
            self.valid(sample_count=True),
            self.valid(sample_count='40'),
            self.valid(result_hash='z' * 64),
            {**self.valid(), 'extra': 1},
            {'verdict': 'statistical_edge'},
            [],
            None,
        ):
            with self.subTest(bad=bad):
                self.assertFalse(protocol.valid_outcome_shape(bad))
        self.assertTrue(all(protocol.valid_outcome_shape(self.valid(verdict=level)) for level in LEVELS))

    def test_each_module_keeps_its_own_sample_count_semantics(self):
        qualification._outcome(self.valid(sample_count=1))
        qualification._outcome(self.valid(sample_count=protocol.POLICY['max_bars']))
        for count in (0, protocol.POLICY['max_bars'] + 1, -3):
            with self.subTest(count=count), self.assertRaises(DomainError):
                qualification._outcome(self.valid(sample_count=count))
        with self.assertRaises(DomainError):
            qualification._outcome(self.valid(verdict='nope'))


class ReaderDigestTests(E1QualificationTests):
    def test_reader_hashes_sources_once_not_once_per_plan(self):
        ref = self.freeze()
        self.complete(ref)
        with patch.object(protocol, 'source_digest', wraps=protocol.source_digest) as digest:
            self.assertEqual([row.candidate_ref for row in self.summaries()], [ref])
        self.assertEqual(digest.call_count, 1)

    def test_changed_sources_still_refuse_or_are_ignored(self):
        ref = self.freeze()
        self.complete(ref)
        with patch.object(protocol, 'source_digest', return_value='b' * 64), self.assertRaises(DomainError):
            self.summaries()
        self.assertEqual(content_hash([ref]), content_hash([ref]))


if __name__ == '__main__':
    unittest.main()
