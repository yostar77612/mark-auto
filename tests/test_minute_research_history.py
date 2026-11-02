"""Real M1 SQLite/HistorySync integration and fake SDK contract/time mapping."""

from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from quantlab.trading.adapters.shioaji.minute_history import TMFMinuteHistorySession
from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.minute_research import research_minutes
from quantlab.trading.domain.minute_research import complete_minutes
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.history import HistoryUsage
from quantlab.trading.runtime.minute_research import MinuteHistoryTarget, MinuteResearchService
from tests.test_minute_research import fixture


class InlineRunner:
    def __init__(self):
        self.calls = 0
        self.after = lambda: None

    def run(self, strategy, spec, calendar, bars, fees, *, deadline, source_profile, minute_settings):
        self.calls += 1
        result = research_minutes(strategy, spec, calendar, bars, fees, settings=minute_settings, source_profile=source_profile)
        self.after()
        return result


class FakeHistory:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def usage(self):
        return HistoryUsage(0, 500 * 1024 * 1024)

    def history(self, instrument, start, end):
        self.calls.append((instrument.instrument_id, start, end))
        return tuple(row for row in self.rows if start <= row.start < end)


class MinuteCacheTests(unittest.TestCase):
    def setUp(self):
        self.strategy, self.spec, self.calendar, self.rows, self.fees, self.settings = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = KlineStore(Path(self.temp.name) / 'minutes.sqlite3')
        self.addCleanup(self.store.close)
        self.now = self.calendar.sessions[-1].closes_at + timedelta(days=1)
        self.session = FakeHistory(self.rows)
        self.history = HistorySync(self.store, self.session, now=lambda: self.now, autostart=False)
        self.addCleanup(self.history.close)
        self.runner = InlineRunner()
        self.service = MinuteResearchService(self.store, self.history, self.runner)

    def run_service(self):
        return self.service.run(self.strategy, self.spec, self.calendar, self.fees, self.settings, now=self.now, deadline=self.now + timedelta(minutes=15))

    def test_empty_cache_first_triggers_m1_refill_then_runs_exact_data(self):
        with self.assertRaisesRegex(DomainError, 'refill requested'):
            self.run_service()
        self.assertEqual(self.runner.calls, 0)
        self.assertTrue(self.history.run_next())
        self.assertEqual(self.session.calls[0][0], self.spec.instrument_id)
        result = self.run_service()
        self.assertEqual(result.observations, len(self.rows))
        self.assertEqual(self.runner.calls, 1)

    def test_successful_empty_coverage_is_not_complete_data(self):
        start, end = self.rows[0].start, self.rows[-1].end
        self.store.mark_coverage(self.spec.instrument_id, start, end)
        self.assertEqual(self.store.missing_ranges(self.spec.instrument_id, start, end), ())
        with self.assertRaisesRegex(DomainError, 'refill requested'):
            self.run_service()
        self.assertTrue(self.history.run_next())
        self.assertEqual(len(self.session.calls), 1)
        self.assertGreater(self.run_service().observations, 0)

    def test_sparse_response_remains_blocked_despite_coverage(self):
        self.session.rows = self.rows[:-1]
        with self.assertRaises(DomainError):
            self.run_service()
        self.history.run_next()
        with self.assertRaisesRegex(DomainError, 'refill requested'):
            self.run_service()
        self.assertEqual(self.runner.calls, 0)

    def test_cache_changes_during_worker_rejects_receipt(self):
        self.store.upsert(self.rows)
        self.runner.after = lambda: self.store.upsert((replace(self.rows[0], volume=99),))
        with self.assertRaisesRegex(DomainError, 'source_invalid_evidence'):
            self.run_service()
        self.assertEqual(self.runner.calls, 1)

    def test_unrelated_cache_update_does_not_invalidate_selected_training_snapshot(self):
        self.store.upsert(self.rows)
        self.runner.after = lambda: self.store.upsert((replace(self.rows[0], instrument_id='TAIFEX:TMF:202703'),))
        result = self.run_service()
        self.assertEqual(result.observations, len(self.rows))
        self.assertEqual(len(result.minute_settings.raw_data_digest), 64)

    def test_current_session_and_wrong_contract_never_start_history_or_worker(self):
        with self.assertRaises(DomainError):
            self.service.run(self.strategy, self.spec, self.calendar, self.fees, self.settings, now=self.rows[0].start, deadline=self.now)
        self.spec = replace(self.spec, instrument_id='INDEX:IX0001')
        with self.assertRaises(DomainError):
            self.run_service()
        self.assertFalse(self.history.run_next())
        self.assertEqual(self.runner.calls, 0)


class FakeSDK:
    def __init__(self, spec, rows):
        self.spec, self.rows = spec, rows
        self.codes, self.calls = [], []
        self.contracts = self
        self.quota = {'bytes': 0, 'limit_bytes': 500 * 1024 * 1024}
        self.on_query = lambda: None

    def get(self, code):
        self.codes.append(code)
        return SimpleNamespace(code=code)

    def usage(self):
        return SimpleNamespace(**self.quota) if self.quota is not None else None

    def kbars(self, *, contract, start, end):
        self.calls.append((contract.code, start, end))
        self.on_query()
        # Existing M1 convention, synthesized here: ns encode Taipei wall time.
        stamps = [int(row.end.replace(tzinfo=timezone.utc).timestamp()) * 1_000_000_000 for row in self.rows]
        return SimpleNamespace(
            ts=stamps,
            Open=[r.open for r in self.rows],
            High=[r.high for r in self.rows],
            Low=[r.low for r in self.rows],
            Close=[r.close for r in self.rows],
            Volume=[r.volume for r in self.rows],
        )


class TMFHistoryBindingTests(unittest.TestCase):
    def setUp(self):
        _, self.spec, self.calendar, self.rows, _, self.settings = fixture()
        self.sdk = FakeSDK(self.spec, self.rows)
        self.resolved = []
        self.context = SimpleNamespace(
            connected=True,
            client=self.sdk,
            bindings={self.spec.instrument_id: InstrumentBinding(self.spec, 'TMFL6')},
            clock=SimpleNamespace(now=lambda: self.rows[-1].end + timedelta(days=1)),
            resolve=self.resolve,
        )
        self.session = TMFMinuteHistorySession(self.context, self.calendar)
        self.target = MinuteHistoryTarget(self.spec.instrument_id)

    def resolve(self, instrument_id):
        self.resolved.append(instrument_id)
        if instrument_id != self.spec.instrument_id:
            raise DomainError('instrument_unresolved')
        return self.spec

    def query(self):
        return self.session.history(self.target, self.rows[0].start, self.rows[-1].end)

    def test_explicit_delivery_contract_and_right_label_taipei_mapping(self):
        rows = self.query()
        self.assertEqual(rows, self.rows)
        self.assertEqual(self.sdk.calls, [('TMFL6', '2026-10-29', '2026-10-29')])
        self.assertEqual(self.resolved, [self.spec.instrument_id])
        self.assertEqual(len(complete_minutes(rows, self.spec.instrument_id, self.calendar, self.settings, self.context.clock.now())), len(rows))

    def test_disconnected_unknown_quota_and_inflight_disconnect_fail_closed(self):
        self.context.connected = False
        with self.assertRaises(DomainError):
            self.query()
        self.assertEqual(self.sdk.calls, [])
        self.context.connected = True
        self.sdk.quota = None
        with self.assertRaisesRegex(DomainError, 'history_quota_low'):
            self.query()
        self.assertEqual(self.sdk.calls, [])
        self.sdk.quota = {'bytes': 0, 'limit_bytes': 500 * 1024 * 1024}
        self.sdk.on_query = lambda: setattr(self.context, 'connected', False)
        with self.assertRaisesRegex(DomainError, 'market_data_not_connected'):
            self.query()

    def test_foreign_target_and_continuous_contract_rejected(self):
        self.target = MinuteHistoryTarget('INDEX:IX0001')
        with self.assertRaisesRegex(DomainError, 'instrument_unresolved'):
            self.query()
        self.assertEqual(self.sdk.calls, [])
        with self.assertRaises(DomainError):
            InstrumentBinding(self.spec, 'TMFR1')

    def test_duplicate_sdk_rows_and_unmapped_hours_never_become_complete_grid(self):
        self.sdk.rows = (self.rows[0],) + self.rows
        with self.assertRaisesRegex(DomainError, 'market_data_not_connected'):
            self.query()
        self.sdk.rows = tuple(replace(row, start=row.start + timedelta(hours=8), end=row.end + timedelta(hours=8)) for row in self.rows)
        rows = self.query()
        self.assertEqual(rows, ())
        with self.assertRaises(DomainError):
            complete_minutes(rows, self.spec.instrument_id, self.calendar, self.settings, self.context.clock.now())
