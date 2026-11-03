"""Additive daily-source freshness fields preserve older wire snapshots."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import unittest

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import DailySignalDataView
from quantlab.trading.application.registry import initialize


class DailyBasisFixesContractTests(unittest.TestCase):
    def test_freshness_fields_round_trip(self):
        initialize()
        now = datetime(2025, 6, 13, tzinfo=timezone.utc)
        row = DailySignalDataView('strategy', 1, 'TWSE:2330', verified_at=now, expires_at=now + timedelta(seconds=30))
        self.assertEqual(loads(dumps(row)), row)
        self.assertEqual(replace(row).expires_at, now + timedelta(seconds=30))

    def test_old_snapshot_loads_empty_freshness(self):
        initialize()
        old = json.loads(dumps(DailySignalDataView('strategy', 1, 'TWSE:2330')))
        del old['fields']['verified_at']
        del old['fields']['expires_at']
        row = loads(json.dumps(old))
        self.assertIsNone(row.verified_at)
        self.assertIsNone(row.expires_at)
