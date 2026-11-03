"""Derived date displays never replace the current owner admission authority."""

from dataclasses import replace
from datetime import date, datetime, timezone
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.application.sinopac_contracts import SinopacConnectionView
from quantlab.trading.domain.maintenance import KeyExpiryStatus, PreOpenMaintenance
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.runtime.sinopac_connection import SinopacConnection
from quantlab.trading.runtime.sinopac_calendar import built_in_calendar
from quantlab.trading.runtime.sinopac_connection import _maintenance_fallback_calendar


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

    def snapshot_owner(self):
        self.now = datetime(2026, 6, 16, 15, 59, tzinfo=timezone.utc)
        self.owner.lock = RLock()
        self.owner.clock = SimpleNamespace(now=lambda: self.now)
        self.owner.selected = ('account',)
        self.owner.accounts = (SimpleNamespace(alias='account', market=Market.STOCK),)
        self.owner.configuration = self.owner._view.settings
        self.owner.maintenance = SimpleNamespace(pre_open=Mock(return_value=self.maintenance))
        self.owner.closed, self.owner.session, self.owner.shared = True, None, None
        return self.owner

    def test_fifty_seven_snapshots_build_one_fallback_but_refresh_every_proof(self):
        owner = self.snapshot_owner()
        with patch('quantlab.trading.runtime.sinopac_connection.built_in_calendar', wraps=built_in_calendar) as factory:
            for _ in range(57):
                owner.snapshot()
            self.assertEqual(factory.call_count, 1)
        self.assertEqual(owner.maintenance.pre_open.call_count, 57)
        calendars = [call.args[0] for call in owner.maintenance.pre_open.call_args_list]
        self.assertTrue(all(calendar is calendars[0] for calendar in calendars))

    def test_cached_sessions_do_not_cache_clock_key_expiry_or_maintenance_versions(self):
        owner = self.snapshot_owner()
        first = self.maintenance
        second = replace(
            first, key=KeyExpiryStatus(date(2026, 6, 17), 0, 'EXPIRED'), calendar_version='calendar-v2', expiry_version='expiry-v2', issues=('api_key_expired',)
        )
        owner.maintenance.pre_open.side_effect = (first, second)
        with patch('quantlab.trading.runtime.sinopac_connection.built_in_calendar', wraps=built_in_calendar) as factory:
            before = owner.snapshot()
            self.now = datetime(2026, 6, 16, 16, 1, tzinfo=timezone.utc)
            owner.configuration = replace(owner.configuration, key_ref='MarkAuto/v2/broker/changed-key')
            after = owner.snapshot()
            self.assertEqual(factory.call_count, 1)
        calls = owner.maintenance.pre_open.call_args_list
        self.assertEqual(calls[0].args[1], date(2026, 6, 16))
        self.assertEqual(calls[1].args[1], date(2026, 6, 17))
        self.assertEqual(calls[1].args[2], 'MarkAuto/v2/broker/changed-key')
        self.assertIs(calls[0].args[0], calls[1].args[0])
        self.assertEqual(after.pre_open, second)
        self.assertEqual(after.api_key_expiry_state, 'EXPIRED')
        self.assertGreater(after.revision, before.revision)

    def test_replacing_calendar_factory_observes_new_calendar_version(self):
        owner = self.snapshot_owner()
        original = built_in_calendar()
        changed = replace(original, version='explicit-calendar-replacement-v2')
        owner.maintenance.pre_open.side_effect = lambda calendar, *_args, **_kwargs: replace(self.maintenance, calendar_version=calendar.version)
        with patch('quantlab.trading.runtime.sinopac_connection.built_in_calendar', return_value=original) as first:
            owner.snapshot()
            owner.snapshot()
            first.assert_called_once_with()
        with patch('quantlab.trading.runtime.sinopac_connection.built_in_calendar', return_value=changed) as second:
            view = owner.snapshot()
            second.assert_called_once_with()
        self.assertEqual(view.pre_open.calendar_version, changed.version)
        self.assertEqual(owner.maintenance.pre_open.call_args.args[0], changed)

    def test_fallback_calendar_cache_has_one_finite_entry_and_no_inferred_year(self):
        calendar = built_in_calendar()
        for _ in range(64):
            self.assertIs(_maintenance_fallback_calendar(Mock(return_value=calendar)), calendar)
        self.assertEqual(_maintenance_fallback_calendar.cache_info().maxsize, 1)
        self.assertEqual(_maintenance_fallback_calendar.cache_info().currsize, 1)
        self.assertEqual(len(calendar.days), 242)
        self.assertEqual(max(calendar.days), date(2026, 12, 31))

    def test_cached_calendar_does_not_hide_session_or_callback_health_change(self):
        owner = self.snapshot_owner()
        owner.closed = False
        owner.worker = None
        owner._view = replace(owner._view, phase='CONNECTED')
        owner.session = SimpleNamespace(connected=True)
        owner.shared = SimpleNamespace(callback_errors=())
        with patch('quantlab.trading.runtime.sinopac_connection.built_in_calendar', wraps=built_in_calendar) as factory:
            owner.snapshot()
            owner.session.connected = False
            with patch('quantlab.trading.runtime.sinopac_transition.readiness', return_value=owner._view.readiness):
                lost = owner.snapshot()
                self.assertEqual(lost.phase, 'DISCONNECTED')
                self.assertEqual(lost.error_code, 'session_lost')
                owner.shared.callback_errors = ('bad-callback',)
                failed = owner.snapshot()
                self.assertEqual(failed.error_code, 'callback_failed')
            self.assertEqual(factory.call_count, 1)

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
