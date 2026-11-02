"""Actual worker/adopt/native execution with a failed unrelated account scope."""

from dataclasses import replace
from datetime import timedelta
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_m2_automatic_engine as fixtures
import test_m2_automatic_runtime as runtime_fixtures
from quantlab.trading.application import automatic
from quantlab.trading.application.events import cursor
from quantlab.trading.application.manual_trading import ManualTradingService
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import UnmappedBrokerOrder
from quantlab.trading.runtime.manual_trading import ManualRuntime


class AutomaticProtectiveTests(unittest.TestCase):
    def setUp(self):
        case = self.case = fixtures.AutomaticEngineTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.use_stock_fixture()
        self.record, self.lot = case.open_and_fill()
        self.engine, self.bundle = case.engine, case.bundle
        self.bundle.lock = RLock()
        self.bundle.sinopac_connection.clock = case.clock
        self.bundle.sinopac_connection.resource_factory = object()
        runtime = self.manual = ManualRuntime(self.bundle)
        runtime.service, runtime.adapter = case.case.service, case.case.adapter
        runtime.stamp = self.bundle.manual_runtime.stamp
        runtime.error = ''
        runtime.automatic_subscription = tuple(spec.instrument_id for spec in self.engine.catalog.instruments if spec.market.value == 'INDEX_FUTURE')
        self.bundle.manual_runtime = runtime
        self.engine.automatic_submission_guard = case.runtime.submission_guard

    def rows(self):
        return tuple(self.case.case.adapter.observe_manual(ref, cursor(self.engine, ref)) for ref in self.engine.gateways)

    def corrupted(self, account='stock-alias', *, first=False):
        rows = tuple(replace(row, unmapped=(UnmappedBrokerOrder('external-order'),)) if row.account_ref == account else row for row in self.rows())
        return tuple(sorted(rows, key=lambda row: row.account_ref != account)) if first else rows

    def adopt_bad_scope(self, account='stock-alias', *, first=False):
        with self.assertRaises(DomainError):
            self.manual.service.adopt(self.corrupted(account, first=first))

    def fail_worker_scope(self, account='stock-alias'):
        original = self.manual.adapter.observe_manual

        def collect(reference, sequence):
            row = original(reference, sequence)
            return replace(row, unmapped=(UnmappedBrokerOrder('external-order'),)) if reference == account else row

        with patch.object(self.manual.adapter, 'observe_manual', collect):
            self.manual.refresh()
        self.assertEqual(self.manual.error, 'reconciliation_required')

    def assert_exit_blocked(self):
        before = self.case.placed()
        with self.assertRaises(DomainError):
            self.engine.exit_lot(self.lot.lot_id, protective=True, key='scope-invalid-exit')
        self.assertEqual(self.case.placed(), before)

    def test_scope_validation_continues_after_first_failed_account_and_protects_known_future(self):
        self.adopt_bad_scope(first=True)
        self.assertEqual(self.engine.manual_observations, {})
        self.assertEqual(set(self.engine.manual_protective_observations), {'future-alias'})
        self.assertTrue(self.engine.state.stopped)
        self.assertFalse(self.engine.state.reconciled)
        before = self.case.placed()
        result = self.engine.exit_lot(self.lot.lot_id, protective=True, key='known-future-after-stock-failure')
        self.assertIsNotNone(result)
        self.assertEqual(self.case.placed(), before + 1)
        self.assertTrue(self.engine.state.orders[-1].plan.reduce_only)

    def test_failed_future_scope_cannot_protect_itself(self):
        self.adopt_bad_scope('future-alias')
        self.assertNotIn('future-alias', self.engine.manual_protective_observations)
        self.assert_exit_blocked()

    def test_scoped_observation_cannot_resume_or_admit_any_new_entry(self):
        self.adopt_bad_scope()
        before = self.case.placed()
        with self.assertRaises(DomainError):
            automatic.resume_automatic(self.engine)
        with self.assertRaises(DomainError):
            self.engine.submit(self.case.direct_plan(self.record), self.record.policy, 'scope-cache-must-not-authorize-entry')
        self.assertEqual(self.case.placed(), before)

    def test_worker_retains_only_same_epoch_validated_scope_and_native_exit_survives_error(self):
        self.fail_worker_scope()
        self.assertEqual(self.manual.protective_stamp, self.manual.stamp)
        self.assertEqual(set(self.engine.manual_protective_observations), {'future-alias'})
        before = self.case.placed()
        self.engine.exit_lot(self.lot.lot_id, protective=True, key='worker-proven-future-exit')
        self.assertEqual(self.case.placed(), before + 1)

    def test_worker_failed_account_never_receives_scoped_permission(self):
        self.fail_worker_scope('future-alias')
        self.assertNotIn('future-alias', self.engine.manual_protective_observations)
        self.assert_exit_blocked()

    def test_sdk_failure_clears_previously_validated_scoped_cache(self):
        self.fail_worker_scope()
        with patch.object(self.manual.adapter, 'observe_manual', side_effect=DomainError('manual_account_observation_required')):
            self.manual.refresh()
        self.assertEqual(self.engine.manual_protective_observations, {})
        self.assertIsNone(self.manual.protective_stamp)
        self.assert_exit_blocked()

    def test_owner_change_after_collection_clears_scoped_cache(self):
        self.fail_worker_scope()
        original = self.manual.adapter.observe_manual

        def collect(reference, sequence):
            row = original(reference, sequence)
            self.case.owner_view = replace(self.case.owner_view, generation='new-owner-generation', revision=4)
            return row

        with patch.object(self.manual.adapter, 'observe_manual', collect):
            self.manual.refresh()
        self.assertEqual(self.engine.manual_protective_observations, {})
        self.assert_exit_blocked()

    def test_age_and_missing_epoch_marker_cannot_borrow_scoped_cache(self):
        self.fail_worker_scope()
        self.manual.protective_stamp = None
        self.assert_exit_blocked()
        self.manual.protective_stamp = self.manual.stamp
        self.case.clock.value += timedelta(seconds=31)
        row = self.engine.manual_protective_observations['future-alias']
        with self.assertRaises(DomainError):
            self.case.runtime.validate_observation('future-alias', row)
        self.assert_exit_blocked()

    def test_empty_adopt_and_new_service_clear_scoped_cache(self):
        self.adopt_bad_scope()
        with self.assertRaises(DomainError):
            self.manual.service.adopt(())
        self.assertEqual(self.engine.manual_protective_observations, {})
        self.adopt_bad_scope()
        old = self.manual.service
        ManualTradingService(
            self.engine, validate_scope=old.validate_scope, limits=tuple(old.limits.values()), cost_source=old.cost_source, margin_source=old.margin_source
        )
        self.assertEqual(self.engine.manual_protective_observations, {})

    def test_new_non_scope_failure_cannot_inherit_previous_scope_failure_marker(self):
        self.adopt_bad_scope()
        rows = self.rows()
        with patch('quantlab.trading.application.manual_trading.manual_net_pnl', side_effect=DomainError('stale_quote')):
            with self.assertRaises(DomainError):
                self.manual.service.adopt(rows)
        self.assertEqual(self.engine.manual_protective_observations, {})

    def test_worker_preservation_requires_current_connected_ready_owner_and_scope_marker(self):
        for field in ('phase', 'ready', 'flag'):
            self.adopt_bad_scope()
            original = self.case.owner_view
            if field == 'phase':
                self.case.owner_view = replace(original, phase='DISCONNECTED')
            elif field == 'ready':
                self.manual.owner.query_ready = False
            else:
                self.manual.service.protective_batch_failed = False
            self.manual._failed('reconciliation_required', validated_stamp=self.manual.stamp)
            self.assertEqual(self.engine.manual_protective_observations, {})
            self.assertIsNone(self.manual.protective_stamp)
            self.case.owner_view = original
            self.manual.owner.query_ready = True

    def test_unverified_source_and_position_mismatch_never_receive_scoped_cache(self):
        for field in ('source', 'positions'):
            rows = tuple(
                replace(row, **({'source': 'UNVERIFIED'} if field == 'source' else {'positions': ()})) if row.account_ref == 'future-alias' else row
                for row in self.rows()
            )
            with self.assertRaises(DomainError):
                self.manual.service.adopt(rows)
            self.assertNotIn('future-alias', self.engine.manual_protective_observations)
            self.assert_exit_blocked()

    def test_margin_source_renewal_preserves_retained_contract_flags_and_changes_without_margin_value_change(self):
        binding = self.manual.adapter.bindings[self.lot.instrument_id]
        resource = SimpleNamespace(
            calendar=self.engine.calendar, fees=self.engine.fees, bindings=(binding,), capabilities=(), limits=(), margin_source='BROKER_VERIFIED_SIM_MARGIN'
        )
        self.engine.automatic_capabilities = dict(self.manual.adapter.capabilities)
        self.engine.unverified_automatic_margins = frozenset(('retained-old-contract', self.lot.instrument_id))
        self.manual._renew_facts(self.manual.stamp, (resource,))
        self.assertEqual(self.engine.unverified_automatic_margins, frozenset(('retained-old-contract',)))
        resource.margin_source = 'BUILTIN_CONSERVATIVE_MARGIN'
        self.manual._renew_facts(self.manual.stamp, (resource,))
        self.assertEqual(self.engine.unverified_automatic_margins, frozenset(('retained-old-contract', self.lot.instrument_id)))


class SubmissionGuardBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = runtime_fixtures.AutomaticRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.runtime, self.bundle = self.fixture.runtime, self.fixture.bundle

    def test_guard_environment_is_closed_before_yield_even_if_fact_port_returns_success(self):
        with patch.object(self.runtime, 'validate_entry', return_value=True):
            for environment in (fixtures.Environment.LIVE, fixtures.Environment.LOCAL):
                self.bundle.launch.environment = environment
                with self.assertRaises(DomainError):
                    with self.runtime.submission_guard('account'):
                        self.fail('invalid environment entered native body')

    def test_guard_missing_context_and_closing_context_do_not_yield(self):
        for key in ('engine', 'sinopac_connection', 'manual_runtime'):
            original = getattr(self.bundle, key)
            setattr(self.bundle, key, None)
            with self.assertRaises(DomainError):
                with self.runtime.submission_guard('account'):
                    self.fail('missing context entered native body')
            setattr(self.bundle, key, original)
        with patch.object(self.runtime, 'validate_entry', return_value=True):
            for key in ('closing', 'resources_closed', 'control_failed'):
                setattr(self.bundle, key, True)
                with self.assertRaises(DomainError):
                    with self.runtime.submission_guard('account'):
                        self.fail('closed context entered native body')
                setattr(self.bundle, key, False)

    def test_guard_last_cas_rechecks_owner_after_fact_validation(self):
        def invalidate(_reference):
            self.fixture.view = replace(self.fixture.view, revision=4)

        with patch.object(self.runtime, 'validate_entry', side_effect=invalidate):
            with self.assertRaises(DomainError):
                with self.runtime.submission_guard('account'):
                    self.fail('changed owner entered native body')

    def test_reduction_guard_uses_its_target_observation_without_entry_market_requirement(self):
        with patch.object(self.runtime, 'validate_entry', side_effect=DomainError('preflight_market')):
            with self.assertRaises(DomainError):
                with self.runtime.submission_guard('account'):
                    self.fail('new risk bypassed its current proof')
            with self.runtime.submission_guard('account', reduce_only=True):
                self.assertTrue(self.fixture.owner.lock._is_owned())


if __name__ == '__main__':
    unittest.main()
