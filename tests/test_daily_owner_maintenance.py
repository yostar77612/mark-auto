"""Derived date displays never replace the current owner admission authority."""

from dataclasses import replace
from datetime import date, datetime, timezone
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from quantlab.trading.application.sinopac_contracts import SinopacConnectionView
from quantlab.trading.domain.maintenance import KeyExpiryStatus, PreOpenMaintenance
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.runtime.sinopac_connection import SinopacConnection


class DailyOwnerMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.maintenance = PreOpenMaintenance(KeyExpiryStatus(date(2027, 1, 1), 200, 'VALID'), 'calendar-v1', 'expiry-v1', 30, date(2026, 7, 1), (), ())
        self.owner = object.__new__(SinopacConnection)
        self.owner._view = SinopacConnectionView(
            environment=Environment.BROKER_SIMULATION,
            generation='authenticated-owner',
            revision=10,
            api_key_remaining_days=200,
            api_key_expiry_state='VALID',
            pre_open=self.maintenance,
        )
        self.owner.preferences = SimpleNamespace(advance_revision=Mock(return_value=11))

    def test_countdown_and_rolling_horizon_update_without_replacing_owner_revision(self):
        new = replace(self.maintenance, key=replace(self.maintenance.key, remaining_days=199), through=date(2026, 7, 2))
        self.owner._publish_maintenance(new)
        self.assertEqual(self.owner._view.pre_open, new)
        self.assertEqual(self.owner._view.api_key_remaining_days, 199)
        self.assertEqual(self.owner._view.revision, 10)
        self.owner.preferences.advance_revision.assert_not_called()

    def test_each_actual_maintenance_authority_change_advances_revision(self):
        changes = (
            {'key': replace(self.maintenance.key, expires_on=date(2027, 1, 2))},
            {'key': KeyExpiryStatus(date(2027, 1, 1), 14, 'DUE')},
            {'key': KeyExpiryStatus(date(2027, 1, 1), 0, 'EXPIRED'), 'issues': ('api_key_expired',)},
            {'calendar_version': 'calendar-v2'},
            {'expiry_version': None},
            {'future_trading_days': 29},
            {'issues': ('calendar_coverage_missing',)},
            {'reminders': ('calendar_annual_update_due',)},
        )
        original = self.owner._view
        for fields in changes:
            with self.subTest(fields=fields):
                self.owner._view = original
                self.owner.preferences.advance_revision.reset_mock()
                new = replace(self.maintenance, **fields)
                self.owner._publish_maintenance(new)
                self.assertEqual(self.owner._view.revision, 11)
                self.assertEqual(self.owner._view.pre_open, new)
                self.owner.preferences.advance_revision.assert_called_once_with()

    def test_non_maintenance_owner_change_still_always_advances_revision(self):
        self.owner.publish(generation='new-owner')
        self.assertEqual(self.owner._view.revision, 11)
        self.owner.preferences.advance_revision.assert_called_once_with()

    def test_real_snapshot_routes_derived_maintenance_without_a_control_mutation(self):
        new = replace(self.maintenance, key=replace(self.maintenance.key, remaining_days=199), through=date(2026, 7, 2))
        self.owner.lock = RLock()
        self.owner.clock = SimpleNamespace(now=lambda: datetime(2026, 6, 16, tzinfo=timezone.utc))
        self.owner.selected = ('account',)
        self.owner.accounts = (SimpleNamespace(alias='account', market=Market.STOCK),)
        self.owner.configuration = self.owner._view.settings
        self.owner.maintenance = SimpleNamespace(pre_open=Mock(return_value=new))
        self.owner.closed, self.owner.session, self.owner.shared = True, None, None
        view = self.owner.snapshot()
        self.assertEqual(view.pre_open, new)
        self.assertEqual(view.api_key_remaining_days, 199)
        self.assertEqual(view.revision, 10)
        self.owner.preferences.advance_revision.assert_not_called()
