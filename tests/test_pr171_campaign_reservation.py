"""PR #171 review items 6 and 9 (quantlab/research.py, a G3-locked file).

The tests marked expectedFailure describe the requested behaviour; they need the owner-approved
patch to research.py / saved_candidate_pool.py (see ADR 0007 follow-up) and flip to unexpected
successes once it is applied — then remove the markers. Nothing here weakens the G3 baseline test.
"""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from quantlab import research
from quantlab.core import Dataset, content_hash
from quantlab.research import FixtureGenerator, ResourceTimeout, run_campaign
from tests import test_research


def busy():
    error = sqlite3.OperationalError('database is locked')
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


class CampaignReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data, self.config = test_research.inputs()

    def run_with(self, failure):
        output = self.root / 'work' / 'campaign'
        with patch.object(research, '_reserve_holdout', side_effect=failure):
            state = run_campaign(self.data, config=self.config, generator=FixtureGenerator(), output_dir=output)
        saved = json.loads((output / 'campaign.json').read_text(encoding='utf-8'))
        return state, saved

    def test_reservation_is_bound_to_exactly_oos_plus_holdout_bars(self):
        """Characterization (passes before and after any refactor of the protected range)."""
        output = self.root / 'ok' / 'campaign'
        state = run_campaign(self.data, config=self.config, generator=FixtureGenerator(), output_dir=output)
        splits = research._campaign_config(self.data, self.config)
        protected = Dataset(splits['oos'].bars + splits['holdout'].bars, {}, {})
        registry = output.parent / '.holdout_registry.sqlite3'
        with sqlite3.connect(registry) as db:
            rows = db.execute('SELECT reservation_id, holdout_hash FROM reservations').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], content_hash(protected.bars))
        self.assertEqual(rows[0][0], state['holdout_registry']['reservation_id'])

    def test_reservation_deadline_ends_the_campaign_as_budget_exhausted(self):
        state, saved = self.run_with(ResourceTimeout('Range reservation exceeded experiment deadline'))
        self.assertEqual(state['status'], 'budget_exhausted')
        self.assertEqual(saved['status'], 'budget_exhausted')
        self.assertIn('elapsed_seconds', saved)
        self.assertTrue(saved['warnings'])

    def test_registry_busy_ends_the_campaign_as_budget_exhausted(self):
        state, saved = self.run_with(busy())
        self.assertEqual(saved['status'], 'budget_exhausted')

    def test_other_database_errors_are_not_swallowed(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.run_with(sqlite3.OperationalError('disk I/O error'))

    def test_one_shared_definition_of_the_protected_range(self):
        splits = research._campaign_config(self.data, self.config)
        union = research.protected_range(splits, union=True)
        self.assertEqual(union.bars, splits['oos'].bars + splits['holdout'].bars)
        self.assertIs(research.protected_range(splits, union=False), splits['holdout'])


if __name__ == '__main__':
    unittest.main()
