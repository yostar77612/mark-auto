"""Preflight checks, durable day latches and read-only reminders."""

import ast
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab.trading.application.preflight import (
    PreflightCheck,
    PreflightFacts,
    PreflightView,
    assert_preflight,
    build_preflight,
    preview_preflight,
    record_preflight,
)
from quantlab.trading.application.codec import dumps, loads, register
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError

NOW = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
PASS = PreflightFacts(True, True, True, True, True, True, True)


@dataclass(frozen=True)
class DraftState:
    trading_day: date = NOW.date()
    preflight: tuple[PreflightView, ...] = ()
    preflight_blocks: tuple[tuple[str, date], ...] = ()
    stopped: bool = False
    version: int = 0
    events: tuple[str, ...] = ()


register(PreflightFacts, PreflightCheck, PreflightView, DraftState)


class DraftEngine:
    def __init__(self, environment=Environment.BROKER_SIMULATION, *, payload=None):
        self.state = loads(payload) if payload else DraftState()
        self.configuration = SimpleNamespace(environment=environment)
        self.gateways = {'stock': object(), 'futures': object()}
        self.clock = SimpleNamespace(now=lambda: NOW)
        self.journal = []

    def _persist(self, kind, proposed):
        self.state = replace(proposed, version=self.state.version + 1, events=(*self.state.events, kind))
        self.journal.append(dumps(self.state))


class PreflightTests(unittest.TestCase):
    def check_failure_and_unknown(self, field, key, code):
        for value, state in ((False, 'FAIL'), (None, 'UNKNOWN')):
            with self.subTest(value=value):
                facts = replace(PASS, **{field: value})
                view = build_preflight('stock', NOW.date(), NOW, Environment.LIVE, facts)
                check = next(row for row in view.checks if row.key == key)
                self.assertEqual((check.state, check.code), (state, code))
                self.assertTrue(view.blocked_today)
                self.assertEqual(view.block_reasons, (code,))
                self.assertTrue(all(row.state == 'PASS' for row in view.checks if row.key != key))

    def test_connection_failure_and_unknown_block_independently(self):
        self.check_failure_and_unknown('connected', 'connection', 'preflight_connection')

    def test_account_failure_and_unknown_block_independently(self):
        self.check_failure_and_unknown('account_ready', 'account', 'preflight_account')

    def test_permission_failure_and_unknown_block_independently(self):
        self.check_failure_and_unknown('permission_ready', 'permission', 'preflight_permission')

    def test_ca_failure_and_unknown_block_independently_in_live(self):
        self.check_failure_and_unknown('ca_ready', 'ca', 'preflight_ca')

    def test_market_failure_and_unknown_block_independently(self):
        self.check_failure_and_unknown('realtime', 'market', 'preflight_market')

    def test_service_failure_and_unknown_block_independently(self):
        self.check_failure_and_unknown('service_open', 'service', 'preflight_service')

    def test_reconciliation_failure_and_unknown_block_independently(self):
        self.check_failure_and_unknown('reconciled', 'reconciliation', 'preflight_reconciliation')

    def test_all_seven_passes_are_named_and_unblocked(self):
        view = build_preflight('stock', NOW.date(), NOW, Environment.LIVE, PASS)
        self.assertEqual(tuple(row.key for row in view.checks), ('connection', 'account', 'permission', 'ca', 'market', 'service', 'reconciliation'))
        self.assertTrue(all(row.state == 'PASS' and row.code == '' for row in view.checks))
        self.assertFalse(view.blocked_today)
        self.assertEqual(view.block_reasons, ())

    def test_sim_and_local_ca_are_not_required_even_when_unavailable_or_unknown(self):
        for environment in (Environment.LOCAL, Environment.BROKER_SIMULATION):
            for ca in (False, None):
                with self.subTest(environment=environment, ca=ca):
                    view = build_preflight('stock', NOW.date(), NOW, environment, replace(PASS, ca_ready=ca))
                    check = next(row for row in view.checks if row.key == 'ca')
                    self.assertEqual((check.state, check.code), ('NOT_REQUIRED', ''))
                    self.assertFalse(view.blocked_today)
                    self.assertEqual(view.block_reasons, ())

    def test_failure_is_recorded_as_stop_and_named_warning_in_journal(self):
        engine = DraftEngine()
        view = record_preflight(engine, 'stock', replace(PASS, permission_ready=None))
        self.assertTrue(engine.state.stopped)
        self.assertEqual(engine.state.preflight, (view,))
        self.assertEqual(engine.state.preflight_blocks, (('stock', NOW.date()),))
        persisted = loads(engine.journal[-1])
        self.assertTrue(persisted.stopped)
        self.assertEqual(persisted.preflight[0].block_reasons, ('preflight_permission',))
        self.assertEqual(persisted.events[-1], 'preflight_recorded')

    def test_passing_rerun_cannot_clear_same_day_latch_or_its_original_reason(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', replace(PASS, connected=False))
        view = record_preflight(engine, 'stock', PASS)
        self.assertTrue(all(check.state in ('PASS', 'NOT_REQUIRED') for check in view.checks))
        self.assertTrue(view.blocked_today)
        self.assertEqual(view.block_reasons, ('preflight_connection',))
        self.assertEqual(engine.state.preflight_blocks, (('stock', NOW.date()),))
        with self.assertRaises(DomainError) as rejected:
            assert_preflight(engine, 'stock')
        self.assertEqual(rejected.exception.code, 'preflight_blocked')

    def test_a_preview_reads_the_facts_but_changes_nothing_and_never_latches_the_day(self):
        engine = DraftEngine()
        before = (engine.state, tuple(engine.journal))
        failing = preview_preflight(engine, 'stock', replace(PASS, connected=False, reconciled=None))
        self.assertTrue(failing.blocked_today)
        self.assertEqual(failing.block_reasons, ('preflight_connection', 'preflight_reconciliation'))
        self.assertEqual((engine.state, tuple(engine.journal)), before)  # no version, no stop, no row, no latch, no journal entry
        # The day is still open for the real record: a later passing record is not blocked by the earlier preview.
        recorded = record_preflight(engine, 'stock', PASS)
        self.assertFalse(recorded.blocked_today)
        assert_preflight(engine, 'stock')
        self.assertFalse(engine.state.stopped)

    def test_a_preview_never_replaces_or_clears_a_recorded_latch(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', replace(PASS, connected=False))
        recorded = engine.state
        view = preview_preflight(engine, 'stock', PASS)
        self.assertFalse(view.blocked_today)  # what it reads now ...
        self.assertEqual(engine.state, recorded)  # ... while the recorded latch is untouched
        with self.assertRaises(DomainError):
            assert_preflight(engine, 'stock')

    def test_a_preview_of_an_unknown_account_is_refused(self):
        with self.assertRaises(DomainError) as refused:
            preview_preflight(DraftEngine(), 'other', PASS)
        self.assertEqual(refused.exception.code, 'capability_missing')

    def test_multiple_failures_keep_day_reasons_when_later_checks_pass(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', replace(PASS, connected=False))
        record_preflight(engine, 'stock', replace(PASS, realtime=None))
        view = record_preflight(engine, 'stock', PASS)
        self.assertEqual(view.block_reasons, ('preflight_connection', 'preflight_market'))
        self.assertTrue(engine.state.stopped)

    def test_replayed_failure_remains_stopped_and_latched_after_passing_rerun(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', replace(PASS, service_open=False))
        restored = DraftEngine(payload=engine.journal[-1])
        self.assertTrue(restored.state.stopped)
        view = record_preflight(restored, 'stock', PASS)
        self.assertTrue(view.blocked_today)
        self.assertEqual(view.block_reasons, ('preflight_service',))
        with self.assertRaises(DomainError):
            assert_preflight(restored, 'stock')

    def test_next_day_requires_new_check_and_does_not_reuse_previous_pass(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', PASS)
        assert_preflight(engine, 'stock')
        engine.state = replace(engine.state, trading_day=NOW.date() + timedelta(days=1))
        with self.assertRaises(DomainError) as rejected:
            assert_preflight(engine, 'stock')
        self.assertEqual(rejected.exception.code, 'preflight_blocked')
        view = record_preflight(engine, 'stock', PASS)
        self.assertFalse(view.blocked_today)
        assert_preflight(engine, 'stock')

    def test_prior_day_failure_does_not_block_new_day_after_fresh_pass(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', replace(PASS, account_ready=False))
        engine.state = replace(engine.state, trading_day=NOW.date() + timedelta(days=1))
        with self.assertRaises(DomainError):
            assert_preflight(engine, 'stock')
        view = record_preflight(engine, 'stock', PASS)
        self.assertFalse(view.blocked_today)
        self.assertEqual(view.block_reasons, ())
        assert_preflight(engine, 'stock')
        # A passed check records evidence; it never acts as an implicit resume.
        self.assertTrue(engine.state.stopped)

    def test_pass_for_other_account_cannot_authorize_this_account(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', PASS)
        with self.assertRaises(DomainError):
            assert_preflight(engine, 'futures')
        record_preflight(engine, 'futures', PASS)
        assert_preflight(engine, 'stock')
        assert_preflight(engine, 'futures')

    def test_failure_latch_is_scoped_to_account(self):
        engine = DraftEngine()
        record_preflight(engine, 'stock', replace(PASS, permission_ready=False))
        record_preflight(engine, 'futures', PASS)
        with self.assertRaises(DomainError):
            assert_preflight(engine, 'stock')
        assert_preflight(engine, 'futures')

    def test_unknown_account_cannot_record_pass(self):
        engine = DraftEngine()
        with self.assertRaises(DomainError) as rejected:
            record_preflight(engine, 'not-selected', PASS)
        self.assertEqual(rejected.exception.code, 'capability_missing')
        self.assertEqual(engine.journal, [])

    def test_missing_check_cannot_admit_entries(self):
        engine = DraftEngine()
        with self.assertRaises(DomainError) as rejected:
            assert_preflight(engine, 'stock')
        self.assertEqual(rejected.exception.code, 'preflight_blocked')

    def test_day_latch_is_authoritative_even_if_a_projection_claims_pass(self):
        engine = DraftEngine()
        view = build_preflight('stock', NOW.date(), NOW, Environment.BROKER_SIMULATION, PASS)
        engine.state = replace(engine.state, preflight=(view,), preflight_blocks=(('stock', NOW.date()),))
        with self.assertRaises(DomainError):
            assert_preflight(engine, 'stock')

    def test_blocked_projection_is_authoritative_even_without_day_latch(self):
        engine = DraftEngine()
        view = build_preflight('stock', NOW.date(), NOW, Environment.BROKER_SIMULATION, replace(PASS, realtime=False))
        engine.state = replace(engine.state, preflight=(view,))
        with self.assertRaises(DomainError):
            assert_preflight(engine, 'stock')

    def test_passing_check_never_resumes_an_already_stopped_engine(self):
        engine = DraftEngine()
        engine.state = replace(engine.state, stopped=True)
        view = record_preflight(engine, 'stock', PASS)
        self.assertFalse(view.blocked_today)
        self.assertTrue(engine.state.stopped)
        assert_preflight(engine, 'stock')

    def test_keep_awake_is_only_a_reminder_with_no_power_or_sdk_imports(self):
        with patch('os.system', side_effect=AssertionError('no power commands')), patch('subprocess.Popen', side_effect=AssertionError('no child commands')):
            engine = DraftEngine()
            view = record_preflight(engine, 'stock', PASS)
            self.assertIs(view.keep_awake_reminder, True)
        module = __import__('quantlab.trading.application.preflight', fromlist=['preflight'])
        tree = ast.parse(inspect.getsource(module))
        imports = {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        imports.update(alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertFalse(imports & {'os', 'subprocess', 'ctypes', 'shioaji'})


if __name__ == '__main__':
    unittest.main()
