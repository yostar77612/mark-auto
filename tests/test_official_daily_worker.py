"""Real owned spawn transport over explicitly synthetic official-input facts."""

from dataclasses import replace
from datetime import timedelta
import multiprocessing
import unittest

import test_official_daily_research as fixtures
from quantlab.trading.application.research import research
from quantlab.trading.domain.stock_history import CorporateAction
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.research_worker import SpawnResearchRunner


class OfficialDailyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OfficialDailyResearchTests()
        self.fixture.setUp()
        self.runner = SpawnResearchRunner(self.fixture.engine.clock, max_seconds=15)
        self.addCleanup(self.runner.close)

    def run_job(self, history):
        row = self.fixture
        return self.runner.run(
            row.record,
            row.spec,
            row.calendar,
            history.raw_completed(row.calendar),
            row.engine.fees,
            deadline=row.engine.clock.now() + timedelta(seconds=15),
            daily_history=history,
        )

    def assert_owned_child_cleaned(self):
        self.assertTrue(self.runner.last_child_ready)
        self.assertIsNotNone(self.runner.last_child_pid)
        self.assertTrue(self.runner.last_cleanup_verified)
        self.assertNotIn(self.runner.last_child_pid, {child.pid for child in multiprocessing.active_children()})

    def test_official_daily_roundtrip_matches_direct_basis_dataset_and_fingerprint(self):
        row = self.fixture
        expected = research(row.record, row.spec, row.calendar, row.raw, row.engine.fees, daily_history=row.history)
        result = self.run_job(row.history)
        self.assert_owned_child_cleaned()
        self.assertEqual(result, expected)
        self.assertEqual(result.daily_basis, expected.daily_basis)
        self.assertEqual(result.dataset_id, expected.dataset_id)
        self.assertEqual(result.fingerprint, expected.fingerprint)
        self.assertEqual(self.runner.clock, row.engine.clock)
        self.assertEqual(self.runner.max_seconds, 15)

    def test_child_entitlement_error_preserves_whitelisted_code_and_cleans_owned_process(self):
        row = self.fixture
        event = CorporateAction(row.spec.instrument_id, row.days[5], fixtures.D('100'), fixtures.D('99'), 'c' * 64, 'https://www.twse.com.tw/fixture')
        history = replace(row.history, events=(event,))
        with self.assertRaises(DomainError) as caught:
            self.run_job(history)
        self.assertEqual(caught.exception.code, 'stock_entitlement_unknown')
        self.assert_owned_child_cleaned()
