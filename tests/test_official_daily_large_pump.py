"""Real six-year-size cache workload in a connected host; synthetic market facts.

The finite test DAY set is not an exchange holiday calendar. This test measures
actual SQLite/hash/parser work and lock residence, not economic validity or SLA.
"""

from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
import gc
from pathlib import Path
from threading import local
from time import perf_counter
import unittest
from unittest.mock import patch

import test_official_daily_runtime_e2e as native
from test_daily_stock_store_bounds import make_official_batch, populate_six_year_refreshes
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application import daily_signal_projection
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.runtime import official_daily_source

FIRST = date(2019, 7, 1)
END = date(2025, 6, 12)


def six_year_calendar():
    # Explicit synthetic test authority, deliberately no real-calendar claim.
    first, stop = FIRST, date(2025, 8, 1)
    days = tuple(first + timedelta(days=i) for i in range((stop - first).days) if (first + timedelta(days=i)).weekday() < 5)
    return TradingCalendar(
        'large-synthetic-calendar',
        'v1',
        'SYNTHETIC_TEST_NOT_EXCHANGE',
        tuple(TradingSession(day, datetime.combine(day, time(1), timezone.utc), datetime.combine(day, time(5, 30), timezone.utc)) for day in days),
    )


class MeasuredLock:
    def __init__(self, lock):
        self.lock = lock
        self.local = local()
        self.samples = []
        self.records = []
        self.phase = 'unlabeled'

    def acquire(self, *args, **kwargs):
        acquired = self.lock.acquire(*args, **kwargs)
        if acquired:
            depth = getattr(self.local, 'depth', 0)
            if not depth:
                self.local.start = perf_counter()
                self.local.phase = self.phase
            self.local.depth = depth + 1
        return acquired

    def release(self):
        self.local.depth -= 1
        if not self.local.depth:
            elapsed = perf_counter() - self.local.start
            self.samples.append(elapsed)
            self.records.append({'phase': self.local.phase, 'seconds': elapsed})
        self.lock.release()

    def _is_owned(self):
        return self.lock._is_owned()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class OfficialDailyLargePumpTests(unittest.TestCase):
    def test_real_sqlite_large_cold_work_is_outside_locks_hot_pump_is_inert_and_revision_revalidates(self):
        fixture = native.ConnectedOfficialFixture(self, calendar_data=six_year_calendar())
        started = perf_counter()
        with closing(KlineStore(fixture.bundle.kline_store.path, arrival_clock=fixture.clock.now)) as store:
            publish = store.import_daily

            def observed_import(batch):
                # A real host keeps its normal ownership heartbeat running while
                # this explicit importer does work on a separate cache connection.
                fixture.bundle.heartbeat()
                return publish(batch)

            store.import_daily = observed_import
            try:
                data = populate_six_year_refreshes(store, fixture.calendar, FIRST, END, refreshes=250, instrument_id=fixture.spec.instrument_id)
            finally:
                del store.import_daily
        build_seconds = perf_counter() - started
        self.assertEqual((data['refreshes'], data['archive_payloads'], data['active_manifests']), (250, 573, 1))
        self.assertEqual(len(data['current'].payloads), 73)
        self.assertGreater(len(data['current'].bars), 1400)
        fixture.deploy_cached()
        fixture.close()
        fixture.refresh(native.OPEN - timedelta(minutes=30))
        with closing(KlineStore(fixture.bundle.kline_store.path, arrival_clock=fixture.clock.now)) as store:
            store.import_daily(make_official_batch(fixture.spec.instrument_id, FIRST, date(2025, 6, 13), nonce=250, calendar=fixture.calendar))
            archive_after_extend = store._db.execute('SELECT COUNT(*) FROM official_stock_payloads').fetchone()[0]

        measured = MeasuredLock(fixture.bundle.lock)
        fixture.bundle.lock = measured
        collections, gc_started = [], {}

        def collection(phase, info):
            if phase == 'start':
                gc_started[info['generation']] = (measured.phase, perf_counter())
            elif info['generation'] in gc_started:
                label, start = gc_started.pop(info['generation'])
                collections.append({'phase': label, 'generation': info['generation'], 'seconds': perf_counter() - start, 'collected': info['collected']})

        gc.callbacks.append(collection)
        self.addCleanup(gc.callbacks.remove, collection)
        lock_violations, full_reads, payload_reads = [], [], []

        def held():
            engine_held = bool(getattr(fixture.engine.lock._local, 'depth', 0))
            return measured._is_owned() or engine_held or fixture.bundle.sinopac_connection.lock._is_owned()

        original_history = fixture.engine.daily_signal_source.history

        def history(*args, **kwargs):
            if not kwargs.get('cached_only', False):
                full_reads.append((kwargs['start'].isoformat(), kwargs['through'].isoformat()))
                if held():
                    lock_violations.append('full-history')
            return original_history(*args, **kwargs)

        def parsed(function):
            def call(*args, **kwargs):
                if held():
                    lock_violations.append(function.__name__)
                return function(*args, **kwargs)

            return call

        def trace(statement):
            if statement.lstrip().upper().startswith('SELECT RAW FROM OFFICIAL_STOCK_PAYLOADS'):
                payload_reads.append(statement)
                if held():
                    lock_violations.append('payload-bytes')

        fixture.bundle.kline_store._db.set_trace_callback(trace)
        self.addCleanup(fixture.bundle.kline_store._db.set_trace_callback, None)
        with (
            patch.object(fixture.engine.daily_signal_source, 'history', side_effect=history),
            patch.object(official_daily_source, 'parse_daily', side_effect=parsed(official_daily_source.parse_daily)) as daily_parser,
            patch.object(official_daily_source, 'parse_events', side_effect=parsed(official_daily_source.parse_events)) as events_parser,
            patch.object(official_daily_source, 'sha256', side_effect=parsed(official_daily_source.sha256)) as digest,
            patch.object(
                daily_signal_projection, '_derive_daily_projection', side_effect=parsed(daily_signal_projection._derive_daily_projection)
            ) as projection,
        ):
            started = perf_counter()
            measured.phase = 'cold_pump'
            fixture.bundle.pump()
            cold_seconds = perf_counter() - started
            cold = {
                'daily_parses': daily_parser.call_count,
                'event_parses': events_parser.call_count,
                'sha_calls': digest.call_count,
                'payload_reads': len(payload_reads),
                'full_reads': len(full_reads),
                'semantic_derivations': projection.call_count,
            }
            self.assertGreaterEqual(cold['daily_parses'], 72)
            self.assertGreater(cold['sha_calls'], 0)
            self.assertGreater(cold['payload_reads'], 0)
            self.assertGreater(cold['semantic_derivations'], 0)
            self.assertEqual(fixture.engine.state.automatic.daily.intents[0].phase, 'READY')
            full_before = len(full_reads)
            measured.phase = 'hot_pump'
            for _ in range(3):
                fixture.bundle.pump()
            hot = {
                'daily_parses': daily_parser.call_count - cold['daily_parses'],
                'event_parses': events_parser.call_count - cold['event_parses'],
                'sha_calls': digest.call_count - cold['sha_calls'],
                'payload_reads': len(payload_reads) - cold['payload_reads'],
                'full_reads': len(full_reads) - full_before,
                'semantic_derivations': projection.call_count - cold['semantic_derivations'],
            }
            self.assertEqual(hot, dict.fromkeys(hot, 0))
            with closing(KlineStore(fixture.bundle.kline_store.path, arrival_clock=fixture.clock.now)) as store:
                store.import_daily(make_official_batch(fixture.spec.instrument_id, FIRST, date(2025, 6, 13), nonce=251, calendar=fixture.calendar))
            measured.phase = 'query_adopt'
            fixture.refresh(native.OPEN + timedelta(seconds=1))
            measured.phase = 'revision_pump'
            fixture.bundle.pump()
            revision = {
                'daily_parses': daily_parser.call_count - cold['daily_parses'],
                'sha_calls': digest.call_count - cold['sha_calls'],
                'full_reads': len(full_reads) - full_before,
                'semantic_derivations': projection.call_count - cold['semantic_derivations'],
            }
            self.assertGreater(revision['daily_parses'], 0)
            self.assertGreater(revision['sha_calls'], 0)
            self.assertGreater(revision['semantic_derivations'], 0)
        self.assertEqual(lock_violations, [])
        self.assertEqual(fixture.placed(), fixture.initial_orders + 1)
        maxima = {phase: max(row['seconds'] for row in measured.records if row['phase'] == phase) for phase in {row['phase'] for row in measured.records}}
        pump_max = max(value for phase, value in maxima.items() if phase.endswith('_pump'))
        report = {
            'synthetic_fixture': True,
            'months': 72,
            'bars': len(data['current'].bars),
            'refreshes': 250,
            'archived_payloads_initial': data['archive_payloads'],
            'archived_payloads_after_next_day_extension': archive_after_extend,
            'active_sources': len(data['current'].payloads),
            'active_manifests': data['active_manifests'],
            'fixture_build_seconds': build_seconds,
            'cold_pump_seconds': cold_seconds,
            'max_bundle_lock_seconds': max(measured.samples),
            'max_pump_bundle_lock_seconds': pump_max,
            'lock_phase_maxima': maxima,
            'gc_collections': collections,
            'gc_phase_seconds': {phase: sum(row['seconds'] for row in collections if row['phase'] == phase) for phase in maxima},
            'lock_violations': lock_violations,
            'cold': cold,
            'three_hot_pumps': hot,
            'revision_revalidation': revision,
        }
        target = Path.cwd() / '.gitnexus/verification/official-daily-large-pump.json'
        if target.parent.is_dir():
            target.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in report.items() if key != 'gc_collections'}, sort_keys=True))
        self.assertLess(pump_max, 0.5, 'cold public-source work must not reside in bundle/engine/owner locks')


if __name__ == '__main__':
    unittest.main()
