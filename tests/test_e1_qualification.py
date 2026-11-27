"""Synthetic/mock E1 protocol tests. No network or real market/OOS data.

Production-mode cases mock the fixed official HTTPS capture. They test the code
contract only and are not market evidence or synthetic candidates shipped to users.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time
from tempfile import TemporaryDirectory
from threading import Event, Thread, Timer
import unittest
from unittest.mock import patch

from quantlab.core import canonical_json, content_hash, Dataset, to_dict
from quantlab.data import SessionCalendar
from quantlab.reporting import demo_config, synthetic_dataset
from quantlab.research import _reserve_holdout
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import e1_protocol as protocol
from quantlab.trading.runtime import e1_qualification as qualification
from quantlab.trading.runtime import e1_source as source
from quantlab.trading.runtime import e1_store as store
from quantlab.trading.runtime.candidate_catalog import ResearchWorkspaceCandidateCatalog
from quantlab.trading.runtime.e1_reader import read_e1_summaries

UTC = timezone.utc
BEFORE = datetime(2027, 1, 1, tzinfo=UTC)
AFTER = BEFORE + timedelta(days=200)
CONTRACT = 'TAIFEX:TMF:202712'
NEXT_MONTH = 'TAIFEX:TMF:202801'
SPEC = json.dumps({'strategy_id': 'synthetic_contract_test', 'family': 'trend', 'parameters': {'fast': 2, 'slow': 5}, 'rules': {}})


def fixtures(count=130):  # policy minimum_observations is 120 sessions
    sessions, rows = [], []
    for index in range(count):
        at = BEFORE + timedelta(days=index + 1, minutes=45)
        price = 20000 + index * 10 + index % 4
        sessions.append(
            {
                'open': at,
                'end': at + timedelta(hours=5),
                'trade_date': at.date().isoformat(),
                'session': 'day',
                'contract_id': CONTRACT,
                'source': 'explicit-synthetic-test-calendar',
            }
        )
        rows.append(
            {
                'Date': at.strftime('%Y%m%d'),
                'Contract': 'TMF',
                'ContractMonth(Week)': '202712',
                'Open': str(price),
                'High': str(price + 4),
                'Low': str(price - 4),
                'Last': str(price + 2),
                'Volume': '100',
                'TradingSession': '\u4e00\u822c',
            }
        )
    return SessionCalendar(sessions, version='synthetic-e1-calendar-v1'), json.dumps(rows).encode()


def mock_outcome(function, args, **kwargs):
    return {'value': {'verdict': 'statistical_edge', 'sample_count': len(args[0].bars), 'result_hash': content_hash(['synthetic-result', args[1]])}}


@contextmanager
def database(path):
    """Commit/rollback fixture writes, then release the handle before cleanup."""
    with closing(sqlite3.connect(path)) as db, db:
        yield db


class E1QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'state'
        self.workspace.mkdir()
        self.registry = self.root / 'controls' / 'holdout-registry.sqlite3'
        self.host = qualification.E1QualificationHost(self.workspace, registry_path=self.registry)
        self.calendar, self.raw = fixtures()
        self.config = replace(demo_config(), instrument_expiries={CONTRACT: '2027-12-15'})
        self.now = BEFORE
        self.clock = patch.object(protocol, 'utc_now', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.network = patch.object(source, 'fetch_daily', return_value=self.raw)
        self.fetch = self.network.start()
        self.addCleanup(self.network.stop)

    def freeze(self, **changes):
        values = {'campaign_ref': 'synthetic-campaign', 'contract_id': CONTRACT, 'signal_spec_json': SPEC, 'calendar': self.calendar, 'config': self.config}
        values.update(changes)
        return self.host.freeze(**values)

    def capture(self, reference):
        self.now = AFTER
        self.assertIsNone(self.host.capture(reference, network_authorized=True))

    def complete(self, reference):
        self.capture(reference)
        with patch.object(qualification, '_run_bounded', side_effect=mock_outcome):
            self.assertIsNone(self.host.evaluate(reference))

    def unavailable(self, function):
        with self.assertRaises(DomainError) as caught:
            function()
        self.assertEqual(str(caught.exception), 'candidate_unavailable')
        self.assertIsNone(caught.exception.__cause__)

    def state(self, reference):
        with store.connection(self.registry) as db:
            return store.load(db, reference, self.workspace)

    def summaries(self):
        return read_e1_summaries(self.workspace, registry_path=self.registry)

    def test_fixture_database_scope_commits_rolls_back_and_closes_without_collection(self):
        path = self.root / 'synthetic-lifecycle.sqlite3'
        with database(path) as committed:
            committed.execute('CREATE TABLE fixture (value TEXT)')
            committed.execute("INSERT INTO fixture VALUES ('committed')")
        with self.assertRaises(sqlite3.ProgrammingError):
            committed.execute('SELECT 1')
        with self.assertRaisesRegex(RuntimeError, 'synthetic rollback'):
            with database(path) as rolled_back:
                rolled_back.execute("INSERT INTO fixture VALUES ('rolled_back')")
                raise RuntimeError('synthetic rollback')
        with self.assertRaises(sqlite3.ProgrammingError):
            rolled_back.execute('SELECT 1')
        with database(path) as inspected:
            self.assertEqual(inspected.execute('SELECT value FROM fixture').fetchall(), [('committed',)])
        with self.assertRaises(sqlite3.ProgrammingError):
            inspected.execute('SELECT 1')

    def test_future_freeze_and_atomic_completion_project_one_exact_candidate(self):
        ref = self.freeze()
        self.assertEqual(self.state(ref)[1], 'reserved')
        self.assertEqual(self.summaries(), ())
        self.complete(ref)
        (evidence,) = self.summaries()
        self.assertEqual(evidence.candidate_ref, ref)
        self.assertEqual(evidence.signal_spec_json, protocol.canonical_spec_json(SPEC))
        self.assertEqual(evidence.completed_at, AFTER)
        self.assertEqual(evidence.sample_count, len(self.calendar.sessions))
        catalog = ResearchWorkspaceCandidateCatalog(self.workspace, qualification_registry=self.registry)
        self.assertEqual(catalog.resolve(ref), evidence)
        self.assertEqual(catalog.passed()[0].candidate_ref, ref)

    def test_historical_or_at_freeze_observations_refuse_without_creating_authority(self):
        self.now = AFTER
        self.unavailable(self.freeze)
        self.assertFalse(self.registry.exists())
        self.now = self.calendar.sessions[0]['open']
        self.unavailable(self.freeze)
        self.assertFalse(self.registry.exists())

    def test_mutating_caller_aliases_cannot_change_plan(self):
        ref = self.freeze()
        plan = self.state(ref)[0]
        changed = json.loads(SPEC)
        changed['parameters']['fast'] = 3
        self.assertEqual(self.state(ref)[0], plan)
        self.unavailable(lambda: self.freeze(signal_spec_json=json.dumps(changed)))
        self.assertEqual(self.state(ref)[0], plan)

    def test_shared_registry_prevents_legacy_campaign_and_duplicate_plan_overlap(self):
        ref = self.freeze()
        self.unavailable(self.freeze)
        first = synthetic_dataset(1).bars[0]
        bar = replace(
            first,
            timestamp=self.calendar.sessions[0]['open'],
            end=self.calendar.sessions[0]['end'],
            trade_date=self.calendar.sessions[0]['trade_date'],
            contract_id=CONTRACT,
        )
        row = _reserve_holdout(
            Dataset((bar,), {}, {}),
            registry_path=self.registry,
            campaign_id='synthetic-legacy',
            selection_hash='synthetic-freeze',
            output_dir=self.root / 'campaign',
        )
        self.assertEqual(row['status'], 'previously_consumed')
        self.assertEqual(self.state(ref)[1], 'reserved')

    def test_e1_window_is_consumed_for_every_delivery_month(self):
        def plan(contract, shift=timedelta(0)):
            rows = [
                {**row, 'contract_id': contract, 'open': row['open'] + shift, 'end': row['end'] + shift, 'trade_date': (row['open'] + shift).date().isoformat()}
                for row in self.calendar.sessions
            ]
            config = replace(self.config, instrument_expiries={contract: '2028-01-19'})
            calendar = SessionCalendar(rows, version='synthetic-e1-calendar-v1')
            return {'campaign_ref': 'synthetic-campaign', 'contract_id': contract, 'signal_spec_json': SPEC, 'calendar': calendar, 'config': config}

        def host(name):
            return qualification.E1QualificationHost(self.workspace, registry_path=self.root / name / 'holdout-registry.sqlite3')

        # The next-month plan is valid on its own registry ...
        self.assertTrue(protocol.is_hash(host('fresh-controls').freeze(**plan(NEXT_MONTH))))
        # ... but the same dates on another TMF month are the same market: one E1 attempt per window.
        self.freeze()
        self.unavailable(lambda: self.host.freeze(**plan(NEXT_MONTH)))
        # A later, non-overlapping window on that month stays available.
        self.assertTrue(protocol.is_hash(self.host.freeze(**plan(NEXT_MONTH, timedelta(days=200)))))
        # An earlier campaign holdout on one month also blocks an E1 plan on another.
        session = self.calendar.sessions[5]
        bar = replace(synthetic_dataset(1).bars[0], timestamp=session['open'], end=session['end'], trade_date=session['trade_date'], contract_id=CONTRACT)
        campaign_registry = self.root / 'campaign-controls' / 'holdout-registry.sqlite3'
        row = _reserve_holdout(
            Dataset((bar,), {}, {}), registry_path=campaign_registry, campaign_id='synthetic-legacy', selection_hash='synthetic', output_dir=self.root / 'c'
        )
        self.assertEqual(row['status'], 'reserved_consumed')
        self.unavailable(lambda: host('campaign-controls').freeze(**plan(NEXT_MONTH)))
        self.assertEqual(store.coverage_product('TWSE:2330'), 'TWSE:2330')
        self.assertEqual(store.coverage_product(CONTRACT), 'TAIFEX:TMF')
        self.assertEqual(store.coverage_product('TAIFEX:TMF:20271'), 'TAIFEX:TMF:20271')

    def test_window_shorter_than_minimum_observations_cannot_freeze(self):
        self.assertEqual(protocol.POLICY['minimum_observations'], 120)
        short, _ = fixtures(119)
        self.unavailable(lambda: self.freeze(calendar=short))
        enough, _ = fixtures(120)
        self.assertTrue(protocol.is_hash(self.freeze(calendar=enough)))

    def test_freeze_confirmation_waits_for_a_competing_writer(self):
        original = store.connection
        calls = []

        def connection(registry, **options):
            calls.append(options)
            if len(calls) == 2:  # reserve()'s confirmation, right after the durable reservation
                held, release = Event(), Event()

                def hold():
                    with original(registry, write=True):
                        held.set()
                        release.wait(5)

                thread = Thread(target=hold)
                thread.start()
                self.addCleanup(thread.join, 5)
                self.assertTrue(held.wait(5))
                Timer(0.3, release.set).start()
            return original(registry, **options)

        with patch.object(store, 'connection', side_effect=connection):
            ref = self.freeze()
        self.assertEqual(self.state(ref)[1], 'reserved')
        self.assertEqual([options.get('busy_ms', 0) for options in calls], [0, 2000])
        self.assertEqual([options.get('commit_busy_ms', 0) for options in calls], [2000, 0])
        for bad in (-1, 2001, True, '10'):
            for name in ('busy_ms', 'commit_busy_ms'):
                with self.assertRaises(DomainError):
                    with store.connection(self.registry, **{name: bad}):
                        pass

    def reader_during_reserve(self, hold_seconds):
        """Patch the clock so a competing reader holds the lock from inside reserve() until just before COMMIT."""
        released, started = Event(), []

        def inside_reserve():
            frame = sys._getframe()
            while frame is not None:
                if frame.f_code is store.reserve.__code__:
                    return True
                frame = frame.f_back
            return False

        def clock():
            # reserve() first reads the clock inside its write transaction, just before COMMIT.
            if not started and inside_reserve():
                started.append(True)
                held = Event()

                def read():
                    with closing(sqlite3.connect(self.registry, timeout=0)) as db:
                        db.execute('BEGIN')
                        db.execute('SELECT COUNT(*) FROM coverage').fetchone()
                        held.set()
                        released.wait(10)
                        db.rollback()

                thread = Thread(target=read)
                thread.start()
                self.addCleanup(thread.join, 10)
                self.assertTrue(held.wait(5))
                timer = Timer(hold_seconds, released.set)
                timer.start()
                self.addCleanup(timer.cancel)
                self.addCleanup(released.set)
            return self.now

        with store.connection(self.registry, write=True, create=True):
            pass  # schema exists, so the competitor's read has a table to lock
        return patch.object(protocol, 'utc_now', side_effect=clock), started

    def test_reservation_commit_waits_out_a_competitor_reader(self):
        # A competing freeze probing the lock briefly holds a read lock; the durable
        # reservation commit must wait it out instead of failing.
        reader, started = self.reader_during_reserve(0.3)
        with reader:
            ref = self.freeze()
        self.assertEqual(started, [True])
        self.assertEqual(self.state(ref)[1], 'reserved')

    def test_reader_held_past_the_commit_wait_fails_closed_and_leaves_nothing_durable(self):
        reader, started = self.reader_during_reserve(2.6)  # longer than the 2 s commit wait
        with reader:
            self.unavailable(self.freeze)
        self.assertEqual(started, [True])
        with database(self.registry) as db:
            for table in ('reservations', 'coverage', 'e1_plans'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0, table)
        # Nothing was consumed, so the same window can still be frozen once the lock is free.
        self.assertTrue(protocol.is_hash(self.freeze()))

    def test_begin_stays_fail_fast_while_another_writer_holds_the_lock(self):
        with store.connection(self.registry, write=True, create=True):
            pass
        held, release = Event(), Event()

        def hold():
            with store.connection(self.registry, write=True):
                held.set()
                release.wait(10)

        thread = Thread(target=hold)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(release.set)
        self.assertTrue(held.wait(5))
        started = time.monotonic()
        self.unavailable(self.freeze)
        self.assertLess(time.monotonic() - started, 1.0)  # the 2 s commit wait never applies to BEGIN

    def test_plan_frozen_under_an_older_shorter_minimum_can_still_be_cancelled(self):
        short, _ = fixtures(40)
        with patch.dict(protocol.POLICY, minimum_observations=30):
            ref = self.freeze(calendar=short)
        # Every session is over, so only the policy/minimum/digest guards can refuse these, not the clock.
        self.now = AFTER
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.fetch.assert_not_called()
        self.unavailable(lambda: self.host.evaluate(ref))
        self.assertEqual(self.state(ref)[1], 'reserved')  # refused before any claim, so no state change
        self.assertFalse(self.summaries())
        # ... but the store still loads it, so its end can be recorded; coverage stays consumed.
        self.assertIsNone(self.host.cancel(ref))
        self.assertEqual(self.state(ref)[1], 'cancelled')
        self.now = BEFORE
        self.unavailable(lambda: self.freeze(calendar=short))

    def test_plan_frozen_by_an_older_source_version_cannot_be_captured_or_evaluated(self):
        with patch.object(protocol, 'source_digest', return_value='a' * 64), patch.object(protocol, 'RUNTIME_SOURCE_DIGEST', 'a' * 64):
            ref = self.freeze()
        self.now = AFTER
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.fetch.assert_not_called()
        self.unavailable(lambda: self.host.evaluate(ref))
        self.assertEqual(self.state(ref)[1], 'reserved')
        self.assertIsNone(self.host.cancel(ref))  # the current source can still end it

    def test_validate_plan_refuses_a_foreign_policy_and_a_short_window(self):
        plan = protocol.make_plan(
            workspace=self.workspace,
            registry=self.registry,
            campaign_ref='synthetic-campaign',
            contract_id=CONTRACT,
            signal_spec_json=SPEC,
            calendar=self.calendar,
            config=self.config,
            evidence_mode='production',
        )

        def check(value):
            return protocol.validate_plan(value, workspace=self.workspace, registry=self.registry)

        check(plan)
        self.unavailable(lambda: check({**plan, 'policy': {**plan['policy'], 'minimum_closed_trades': 1}}))
        sessions = plan['calendar']['sessions']
        self.unavailable(lambda: check({**plan, 'calendar': {**plan['calendar'], 'sessions': sessions[:119]}}))

    def test_calendar_structure_accepts_one_session_and_refuses_none(self):
        rows = [to_dict(row) for row in self.calendar.sessions]
        one = {'contract_id': CONTRACT, 'calendar': {'version': 'v', 'sessions': rows[:1]}}
        self.assertEqual(len(protocol.calendar_for(one).sessions), 1)  # structural only; the minimum is validate_plan's
        self.unavailable(lambda: protocol.calendar_for({**one, 'calendar': {'version': 'v', 'sessions': []}}))

    def test_product_prefix_needs_the_separator_and_matches_the_bare_product(self):
        session = self.calendar.sessions[5]
        for contract, blocked in (('TAIFEX:TMFX:202712', False), ('TAIFEX:TM', False), ('TAIFEX:TMF', True), ('TAIFEX:TMF:202801', True)):
            with self.subTest(contract=contract):
                registry = self.root / ('prefix-' + contract.replace(':', '-')) / 'holdout-registry.sqlite3'
                with store.connection(registry, write=True, create=True) as db:
                    db.execute('INSERT INTO reservations VALUES (?,?,?,?,?)', ('r', 'h', 'c', 's', 'd'))
                    db.execute(
                        'INSERT INTO coverage VALUES (?,?,?,?)',
                        ('r', contract, protocol.coverage_time(session['open']), protocol.coverage_time(session['end'])),
                    )
                host = qualification.E1QualificationHost(self.workspace, registry_path=registry)
                values = {
                    'campaign_ref': 'synthetic-campaign',
                    'contract_id': CONTRACT,
                    'signal_spec_json': SPEC,
                    'calendar': self.calendar,
                    'config': self.config,
                }
                if blocked:
                    self.unavailable(lambda: host.freeze(**values))
                else:
                    self.assertTrue(protocol.is_hash(host.freeze(**values)))

    def test_cross_month_windows_overlapping_by_one_session_conflict_and_the_next_day_does_not(self):
        self.freeze()
        last = self.calendar.sessions[-1]

        def window(first_open):
            rows = []
            for index in range(len(self.calendar.sessions)):
                at = first_open + timedelta(days=index)
                rows.append({**last, 'contract_id': NEXT_MONTH, 'open': at, 'end': at + timedelta(hours=5), 'trade_date': at.date().isoformat()})
            config = replace(self.config, instrument_expiries={NEXT_MONTH: '2028-01-19'})
            calendar = SessionCalendar(rows, version='synthetic-e1-calendar-v1')
            return {'campaign_ref': 'synthetic-campaign', 'contract_id': NEXT_MONTH, 'signal_spec_json': SPEC, 'calendar': calendar, 'config': config}

        self.unavailable(lambda: self.host.freeze(**window(last['open'])))
        self.assertTrue(protocol.is_hash(self.host.freeze(**window(last['open'] + timedelta(days=1)))))

    def test_concurrent_freeze_has_one_winner_and_no_partial_rows(self):
        def run():
            try:
                return self.freeze()
            except DomainError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            values = list(executor.map(lambda _: run(), range(2)))
        self.assertEqual(sum(value is not None for value in values), 1)
        with database(self.registry) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM e1_plans').fetchone()[0], 1)

    def test_explicit_network_action_required_without_mutating_reservation(self):
        ref = self.freeze()
        self.unavailable(lambda: self.host.capture(ref))
        self.fetch.assert_not_called()
        self.assertEqual(self.state(ref)[1], 'reserved')

    def test_capture_failure_is_redacted_terminal_and_never_refunded(self):
        ref = self.freeze()
        self.fetch.side_effect = OSError('synthetic-private-source-payload')
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.state(ref)[1], 'failed')
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.assertEqual(self.fetch.call_count, 1)
        self.unavailable(self.freeze)
        self.assertEqual(self.summaries(), ())

    def test_conflicting_official_source_revision_fails_without_overwriting_capture(self):
        ref = self.freeze()
        self.capture(ref)
        with database(self.registry) as db:
            before = db.execute('SELECT payload FROM e1_captures ORDER BY slot').fetchall()
        rows = json.loads(self.raw)
        rows[0]['Last'] = '99999'
        self.fetch.return_value = json.dumps(rows).encode()
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        with database(self.registry) as db:
            self.assertEqual(db.execute('SELECT payload FROM e1_captures ORDER BY slot').fetchall(), before)
        self.assertEqual(self.state(ref)[1], 'failed')

    def test_capture_is_exclusive_and_conflicting_inflight_response_cannot_survive_as_evidence(self):
        ref = self.freeze()
        self.capture(ref)
        entered, release = Event(), Event()
        rows = json.loads(self.raw)
        rows[0]['Last'] = '99999'

        def blocked_fetch():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('synthetic capture timed out')
            return json.dumps(rows).encode()

        with patch.object(source, 'fetch_daily', side_effect=blocked_fetch) as fetch, ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.host.capture, ref, network_authorized=True)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.state(ref)[1], 'capturing')
                with patch.object(qualification, '_run_bounded') as worker:
                    self.unavailable(lambda: self.host.evaluate(ref))
                    worker.assert_not_called()
                self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
                fetch.assert_called_once()
                self.assertEqual(self.state(ref)[1], 'capturing')
                self.assertEqual(self.summaries(), ())
            finally:
                release.set()
            self.unavailable(pending.result)
        self.assertEqual(self.state(ref)[1], 'failed')
        self.assertEqual(self.summaries(), ())

    def test_unknown_inflight_capture_cannot_resume_or_evaluate(self):
        ref = self.freeze()
        self.capture(ref)
        with database(self.registry) as db:
            db.execute("UPDATE e1_plans SET status='capturing' WHERE reference=?", (ref,))
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        with patch.object(qualification, '_run_bounded') as worker:
            self.unavailable(lambda: self.host.evaluate(ref))
            worker.assert_not_called()
        self.assertEqual(self.state(ref)[1], 'capturing')
        self.assertEqual(self.summaries(), ())

    def test_fetch_started_before_close_cannot_capture_postclose_returned_snapshot(self):
        ref = self.freeze()
        end = self.calendar.sessions[0]['end']
        self.now = end - timedelta(seconds=1)

        def crossing_fetch():
            self.now = end + timedelta(seconds=1)
            return self.raw

        self.fetch.side_effect = crossing_fetch
        self.host.capture(ref, network_authorized=True)
        with database(self.registry) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM e1_captures').fetchone()[0], 0)
        self.assertEqual(self.state(ref)[1], 'captured')

    def test_old_source_and_terminal_history_do_not_block_current_qualified_evidence(self):
        with patch.object(protocol, 'source_digest', return_value='a' * 64), patch.object(protocol, 'RUNTIME_SOURCE_DIGEST', 'a' * 64):
            old = self.freeze()
            self.complete(old)
        self.now = BEFORE
        shift = timedelta(days=len(self.calendar.sessions) + 1)  # the next window must not overlap
        sessions = [
            dict(row, open=row['open'] + shift, end=row['end'] + shift, trade_date=(row['open'] + shift).date().isoformat()) for row in self.calendar.sessions
        ]
        self.calendar = SessionCalendar(sessions, version='synthetic-later-calendar')
        rows = json.loads(self.raw)
        for row, session in zip(rows, sessions):
            row['Date'] = session['trade_date'].replace('-', '')
        self.fetch.return_value = json.dumps(rows).encode()
        ref = self.freeze()
        self.now = AFTER + shift
        self.host.capture(ref, network_authorized=True)
        with patch.object(qualification, '_run_bounded', side_effect=mock_outcome):
            self.host.evaluate(ref)
        with database(self.registry) as db:
            # Terminal history is deliberately not evidence and never upgraded.
            db.executemany(
                'INSERT INTO e1_plans VALUES (?,?,?,?,?,?,?)',
                [(content_hash(index), str(self.workspace), '{}', 'failed', None, None, None) for index in range(1001)],
            )
        self.assertEqual([row.candidate_ref for row in self.summaries()], [ref])
        self.assertEqual(self.state(old)[1], 'completed')

    def test_evaluation_failure_cancel_and_unknown_attempt_cannot_retry(self):
        for failure in ('failed', 'cancelled', 'unknown'):
            with self.subTest(failure=failure), TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / 'state'
                workspace.mkdir()
                host = qualification.E1QualificationHost(workspace, registry_path=root / 'control.sqlite3')
                self.now = BEFORE
                ref = host.freeze(campaign_ref='synthetic', contract_id=CONTRACT, signal_spec_json=SPEC, calendar=self.calendar, config=self.config)
                self.now = AFTER
                host.capture(ref, network_authorized=True)
                if failure == 'cancelled':
                    host.cancel(ref)
                elif failure == 'unknown':
                    with database(host.registry) as db:
                        db.execute("UPDATE e1_plans SET status='evaluating' WHERE reference=?", (ref,))
                else:
                    with patch.object(qualification, '_run_bounded', side_effect=RuntimeError('private')) as worker:
                        self.unavailable(lambda: host.evaluate(ref))
                        worker.assert_called_once()
                with patch.object(qualification, '_run_bounded') as worker:
                    self.unavailable(lambda: host.evaluate(ref))
                    worker.assert_not_called()
                self.assertEqual(read_e1_summaries(workspace, registry_path=host.registry), ())

    def test_exact_dataset_and_attempt_are_durable_before_worker(self):
        ref = self.freeze()
        self.capture(ref)

        def worker(function, args, **kwargs):
            plan, status, binding, receipt = self.state(ref)
            self.assertEqual(status, 'evaluating')
            self.assertIsNone(receipt)
            self.assertEqual(binding['data_hash'], args[0].manifest['data_hash'])
            self.assertEqual(plan['spec_json'], args[1])
            self.assertLessEqual(kwargs['deadline'], qualification.time.monotonic() + 900)
            self.assertEqual(kwargs['config']['process_start_method'], 'spawn')
            return mock_outcome(function, args, **kwargs)

        with patch.object(qualification, '_run_bounded', side_effect=worker):
            self.host.evaluate(ref)

    def test_incomplete_or_invalid_session_set_never_evaluates(self):
        ref = self.freeze()
        self.fetch.return_value = json.dumps(json.loads(self.raw)[:-1]).encode()
        self.capture(ref)
        with patch.object(qualification, '_run_bounded') as worker:
            self.unavailable(lambda: self.host.evaluate(ref))
            worker.assert_not_called()
        self.assertEqual(self.state(ref)[1], 'failed')

    def test_synthetic_mode_exercises_real_bounded_engine_but_never_qualifies(self):
        ref = self.freeze(evidence_mode='synthetic_validation')
        self.capture(ref)
        self.host.evaluate(ref)
        self.assertEqual(self.state(ref)[1], 'completed')
        self.assertEqual(self.summaries(), ())

    def test_receipt_completion_clock_is_observed_after_worker(self):
        ref = self.freeze()
        self.capture(ref)

        def worker(function, args, **kwargs):
            self.now += timedelta(seconds=5)
            return mock_outcome(function, args, **kwargs)

        with patch.object(qualification, '_run_bounded', side_effect=worker):
            self.host.evaluate(ref)
        self.assertEqual(self.summaries()[0].completed_at, AFTER + timedelta(seconds=5))

    def test_receipt_and_reservation_tampering_refuse(self):
        ref = self.freeze()
        self.complete(ref)
        with database(self.registry) as db:
            original = db.execute('SELECT receipt FROM e1_plans').fetchone()[0]
            receipt = json.loads(original)
            receipt['outcome']['sample_count'] = 39
            db.execute('UPDATE e1_plans SET receipt=?', (canonical_json(receipt),))
        self.unavailable(self.summaries)
        with database(self.registry) as db:
            db.execute('UPDATE e1_plans SET receipt=?', (original,))
            db.execute("UPDATE reservations SET selection_hash='changed'")
        self.unavailable(self.summaries)

    def test_reader_does_not_select_oos_payload_and_does_not_write(self):
        ref = self.freeze()
        self.complete(ref)
        original = store.sqlite3.connect
        calls = []

        def connect(*args, **kwargs):
            calls.append(args[0])
            db = original(*args, **kwargs)

            def authorizer(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and table == 'e1_captures' and column == 'payload':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            db.set_authorizer(authorizer)
            return db

        with patch.object(store.sqlite3, 'connect', side_effect=connect):
            self.assertEqual(len(self.summaries()), 1)
        self.assertTrue(all('mode=ro' in uri for uri in calls))

    def test_current_source_drift_and_missing_authority_refuse_without_bootstrap(self):
        self.unavailable(self.summaries)
        self.assertFalse(self.registry.exists())
        ref = self.freeze()
        self.complete(ref)
        with patch.object(protocol, 'source_digest', return_value='f' * 64):
            self.unavailable(self.summaries)

    def test_legacy_json_and_sidecars_never_supply_evidence(self):
        (self.workspace / 'candidate-evidence.json').write_text('{"verdict":"statistical_edge"}')
        self.unavailable(self.summaries)
        self.unavailable(ResearchWorkspaceCandidateCatalog(self.workspace).passed)
        self.assertFalse(self.registry.exists())

    def test_registry_cannot_be_restorable_workspace_state_or_symlink(self):
        self.unavailable(lambda: qualification.E1QualificationHost(self.workspace, registry_path=self.workspace / 'registry.sqlite3'))
        link = self.root / 'alias'
        link.symlink_to(self.workspace, target_is_directory=True)
        self.unavailable(lambda: qualification.E1QualificationHost(link, registry_path=self.registry))

    def test_old_report_date_cannot_be_relabelled_with_future_session_timestamps(self):
        sessions = [dict(row) for row in self.calendar.sessions]
        sessions[0]['trade_date'] = BEFORE.date().isoformat()
        forged = SessionCalendar(sessions, version='synthetic-forged-calendar')
        self.unavailable(lambda: self.freeze(calendar=forged))
        self.assertFalse(self.registry.exists())

    def test_partial_or_night_session_cannot_claim_full_day_source(self):
        for change in ('night', 'partial'):
            sessions = [dict(row) for row in self.calendar.sessions]
            if change == 'night':
                sessions[0]['session'] = 'night'
            else:
                sessions[0]['end'] -= timedelta(minutes=1)
            calendar = SessionCalendar(sessions, version='synthetic-invalid-scope')
            self.unavailable(lambda: self.freeze(calendar=calendar))
        self.assertFalse(self.registry.exists())

    def test_clock_crossing_after_reservation_is_consumed_but_never_admitted(self):
        original = protocol.utc_now
        clock_calls = 0

        def crossing():
            nonlocal clock_calls
            clock_calls += 1
            # make_plan clock, validation clock, then reservation precommit clock.
            return BEFORE if clock_calls <= 3 else AFTER

        with patch.object(protocol, 'utc_now', side_effect=crossing):
            self.unavailable(self.freeze)
        self.assertIsNotNone(original())
        with database(self.registry) as db:
            self.assertEqual(db.execute('SELECT status FROM e1_plans').fetchone()[0], 'failed')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 1)
        self.unavailable(self.freeze)

    def test_uncertain_initial_commit_is_not_resumable(self):
        ref = self.freeze()
        with database(self.registry) as db:
            db.execute("UPDATE e1_plans SET status='committing',reserved_at=NULL WHERE reference=?", (ref,))
        self.unavailable(lambda: self.host.capture(ref, network_authorized=True))
        self.unavailable(lambda: self.host.evaluate(ref))
        self.assertEqual(self.summaries(), ())

    def test_rehashed_receipt_cannot_change_frozen_daily_sample_count(self):
        ref = self.freeze()
        self.complete(ref)
        with database(self.registry) as db:
            receipt = json.loads(db.execute('SELECT receipt FROM e1_plans').fetchone()[0])
            receipt['outcome']['sample_count'] -= 1
            receipt['receipt_hash'] = content_hash({key: value for key, value in receipt.items() if key != 'receipt_hash'})
            db.execute('UPDATE e1_plans SET receipt=?', (canonical_json(receipt),))
        self.unavailable(self.summaries)

    def test_failed_atomic_completion_cannot_return_qualified_evidence(self):
        ref = self.freeze()
        self.capture(ref)
        # A schema trigger is itself forbidden, so no work can be admitted.
        with database(self.registry) as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt ON e1_plans BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        with patch.object(qualification, '_run_bounded') as worker:
            self.unavailable(lambda: self.host.evaluate(ref))
            worker.assert_not_called()
        self.unavailable(self.summaries)


class E1VerdictInputsTests(unittest.TestCase):
    def test_evaluate_judges_closed_trades_and_robust_p_values(self):
        def outcome(returns, trades):
            result = type('Result', (), {'metrics': {'daily_returns': [{'return': value} for value in returns], 'trade_count': trades}})()
            with (
                patch.object(qualification, 'run_backtest', return_value=result),
                patch.object(qualification, 'validated_spec', side_effect=lambda text: text),
                patch.object(qualification, 'content_hash', return_value='0' * 64),
            ):
                return qualification._evaluate(None, SPEC, None)

        edge = ['.012', '-.008'] * 40
        # The version names the rule set; old frozen plans carry the old one and refuse.
        self.assertEqual(protocol.POLICY['version'], 'm3-e1-policy-v3')
        self.assertEqual(protocol.POLICY['minimum_closed_trades'], 30)
        self.assertEqual(outcome(edge, 30)['verdict'], 'statistical_edge')
        # One long holding cannot qualify, however many daily returns it spans.
        self.assertEqual(outcome(edge, 29)['verdict'], 'insufficient')
        self.assertEqual(outcome(edge, 1)['verdict'], 'insufficient')
        # Ten-day runs look significant only to the i.i.d. tests.
        held = (['.012'] * 10 + ['-.008'] * 10) * 8
        self.assertEqual(outcome(held, 80)['verdict'], 'luck_suspected')
        # A strong second half cannot rescue a losing first half (one regime carrying the window).
        self.assertEqual(protocol.POLICY['regime_check'], 'both_chronological_halves_compound_positive')
        regime = ['.0005', '-.0007'] * 60 + ['.012', '-.008'] * 60
        self.assertEqual(outcome(regime, 120)['verdict'], 'fragile_edge')
        # ... nor can a strong first half hide a losing second half.
        self.assertEqual(outcome(['.012', '-.008'] * 60 + ['.0005', '-.0007'] * 60, 120)['verdict'], 'fragile_edge')
        self.assertEqual(outcome(['.012', '-.008'] * 120, 120)['verdict'], 'statistical_edge')
        self.assertEqual(protocol.POLICY['holdout_scope'], 'product_all_delivery_months')


if __name__ == '__main__':
    unittest.main()
