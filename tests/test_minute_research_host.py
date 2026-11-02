"""Actual generated-resource/host/M1/worker/receipt composition, entirely fake SDK."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab.trading.adapters.shioaji.account_discovery import discover_accounts
from quantlab.trading.adapters.shioaji.gateway import ShioajiAdapter
from quantlab.trading.adapters.shioaji.sdk import SDK_VERSION
from quantlab.trading.runtime.minute_receipt_store import MinuteReceiptStore
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.minute_contract import HistoricalContractEvidence
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.bootstrap import build_runtime
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.manual_trading import ManualExecutionGateway
from quantlab.trading.runtime.sinopac_resources import generated_resources
from tests.test_minute_research import fixture
from tests.test_minute_research_history import FakeSDK


class GeneratedSDK(FakeSDK):
    def __init__(self, rows):
        super().__init__(None, rows)
        self.account = SimpleNamespace(account_type='F', broker_id='F002000', account_id='1234567', signed=True)
        self.contract = SimpleNamespace(code='TMFK6', security_type='FUT', exchange='TAIFEX', region='TW', target_code=None)
        self.details = SimpleNamespace(
            **vars(self.contract),
            root='TMF',
            delivery_month='202611',
            delivery_date=date(2026, 11, 18),
            multiplier=10,
            tick_basis='fixed',
            tick_rule=None,
            tick=1,
            limit_up=33000,
            limit_down=27000,
        )
        self.started, self.finished = Event(), Event()
        self.release = None
        self.query_thread = None
        self.error = False

    def execution_contracts(self, kind):
        return [self.contract]

    def get(self, code):
        if code != self.contract.code:
            raise DomainError('instrument_unresolved')
        return self.contract

    def info(self, contract):
        return self.details

    def list_accounts(self):
        return [self.account]

    def kbars(self, *, contract, start, end):
        self.query_thread = current_thread()
        self.started.set()
        if self.release is not None:
            self.release.wait(2)
        try:
            if self.error:
                raise RuntimeError('fake-sensitive-sdk-error')
            return super().kbars(contract=contract, start=start, end=end)
        finally:
            self.finished.set()


class MinuteHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = build_runtime(RuntimeLaunch(self.root))
        self.addCleanup(self.bundle.close)
        strategy, _, self.calendar, rows, _, self.settings = fixture(length=300, opening=8 * 60 + 45)
        self.sdk = GeneratedSDK(rows)
        accounts = discover_accounts([self.sdk.account], Environment.BROKER_SIMULATION)
        self.clock = SimpleNamespace(now=lambda: datetime(2026, 11, 2, 6, tzinfo=timezone.utc))
        owner = SimpleNamespace(
            accounts=accounts,
            configuration=SinopacConnectionSettings(),
            shared=SimpleNamespace(facade=self.sdk),
            clock=self.clock,
            query_ready=True,
        )
        self.resources = generated_resources(owner, accounts[0].alias)
        self.spec = self.resources.catalog.instruments[0]
        self.sdk.rows = tuple(replace(row, instrument_id=self.spec.instrument_id) for row in rows)
        self.adapter = ShioajiAdapter(
            self.sdk,
            self.clock,
            Environment.BROKER_SIMULATION,
            {accounts[0].alias: self.sdk.account},
            self.resources.bindings,
            self.resources.capabilities,
            {accounts[0].alias: Decimal('40000')},
            sdk_version=SDK_VERSION,
        )
        self.adapter.attach_authenticated()
        self.bundle.engine.catalog = self.resources.catalog
        self.bundle.engine.fees = self.resources.fees
        self.bundle.engine.gateways = {accounts[0].alias: ManualExecutionGateway(self.adapter, RLock())}
        self.strategy = replace(strategy, form=replace(strategy.form, instrument_id=self.spec.instrument_id, account_ref=accounts[0].alias))
        evidence = HistoricalContractEvidence(
            self.spec,
            'TMFK6',
            self.sdk.rows[0].start,
            self.sdk.rows[-1].end,
            'SYNTHETIC_VERIFIED_CONTRACT_FIXTURE',
            'a' * 64,
        )
        self.settings = replace(self.settings, historical_contract=evidence)
        self.receipt_path = self.root / 'research' / 'minute-receipts.sqlite3'

    def run_host(self, *, settings=None, calendar=None, seconds=10, cancel=None):
        return self.bundle.research_minutes(
            self.strategy,
            settings or self.settings,
            calendar=calendar or self.calendar,
            deadline=datetime.now(timezone.utc) + timedelta(seconds=seconds),
            cancel_event=cancel,
        )

    def test_generated_tmf_identity_refills_waits_runs_and_persists_replayable_receipt(self):
        self.assertEqual(self.spec.instrument_id, 'TMF:202611')
        self.assertGreater(self.spec.effective_at, self.sdk.rows[0].start)
        receipt = self.run_host()
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(receipt.raw_bars, self.sdk.rows)
        self.assertEqual(receipt.fees, self.resources.fees)
        self.assertEqual(receipt.result.minute_settings.historical_contract, self.settings.historical_contract)
        self.assertEqual(receipt.result.price_basis, 'RAW_CONTRACT')
        self.assertTrue(receipt.source_profile.source_digest)
        store = MinuteReceiptStore(self.receipt_path, datetime.now(timezone.utc))
        try:
            self.assertEqual(store.receipts, (receipt,))
        finally:
            store.close()
        # Complete cache does not require another remote query.
        self.run_host()
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(self.bundle.kline_store.queried_bars(self.clock.now().date()), len(self.sdk.rows))
        self.assertIsNone(self.bundle.minute_research_active)

    def test_receipt_recent_view_is_bounded_without_rewriting_older_rows(self):
        receipt = self.run_host()
        store = MinuteReceiptStore(self.receipt_path, datetime.now(timezone.utc))
        try:
            for _ in range(33):
                store.append(receipt, datetime.now(timezone.utc))
            self.assertEqual(len(store.receipts), 32)
            self.assertEqual(store.read(1), receipt)
            self.assertEqual(store.read(34), receipt)
        finally:
            store.close()
        reopened = MinuteReceiptStore(self.receipt_path, datetime.now(timezone.utc))
        try:
            self.assertEqual(len(reopened.receipts), 32)
            self.assertEqual(reopened.read(1), receipt)
        finally:
            reopened.close()

    def test_current_observation_is_not_historical_validity_and_common_window_is_not_tmf_session(self):
        with self.assertRaisesRegex(DomainError, 'historical contract applicability is unknown'):
            self.run_host(settings=replace(self.settings, historical_contract=None))
        with self.assertRaisesRegex(DomainError, 'calendar_missing'):
            self.run_host(calendar=self.resources.calendar)
        wrong = replace(self.settings.historical_contract, sdk_code='TMFOTHER')
        with self.assertRaisesRegex(DomainError, 'contract code mismatch'):
            self.run_host(settings=replace(self.settings, historical_contract=wrong))
        self.assertEqual(self.sdk.calls, [])
        self.assertFalse(self.receipt_path.exists())

    def test_failed_and_sparse_refill_produce_no_receipt(self):
        self.sdk.error = True
        with self.assertRaisesRegex(DomainError, 'refill failed'):
            self.run_host()
        self.sdk.error = False
        self.sdk.rows = self.sdk.rows[:-1]
        with self.assertRaisesRegex(DomainError, 'incomplete after refill'):
            self.run_host()
        self.assertFalse(self.receipt_path.exists())

    def test_timeout_invalidates_late_refill_and_never_publishes(self):
        self.sdk.release = Event()
        epoch = datetime.now(timezone.utc)
        deadline = epoch + timedelta(seconds=0.1)

        # Exercise timeout AFTER dispatch, not a race between profile hashing /
        # thread scheduling and a 100 ms wall deadline. Both budget clocks cross
        # the unchanged deadline only once the fake SDK signals it is blocked.
        def elapsed():
            return 0.1 if self.sdk.started.is_set() else 0.0

        class BudgetClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return (epoch + timedelta(seconds=elapsed())).astimezone(tz)

        started = monotonic()
        with (
            patch('quantlab.trading.runtime.minute_research_wait.datetime', BudgetClock),
            patch('quantlab.trading.runtime.minute_research_wait.monotonic', elapsed),
            self.assertRaisesRegex(DomainError, 'research_timeout'),
        ):
            self.bundle.research_minutes(self.strategy, self.settings, calendar=self.calendar, deadline=deadline)
        self.assertLess(monotonic() - started, 1)
        self.assertTrue(self.sdk.started.is_set())
        self.assertIsNotNone(self.sdk.query_thread)
        self.assertFalse(self.receipt_path.exists())
        self.assertIsNotNone(self.bundle.minute_research_retiring)
        self.sdk.release.set()
        self.sdk.query_thread.join(1)
        self.assertFalse(self.sdk.query_thread.is_alive())
        self.assertEqual(self.bundle.kline_store.read(self.spec.instrument_id, self.sdk.rows[0].start, self.sdk.rows[-1].end), ())
        interval = (self.sdk.rows[0].start, self.sdk.rows[-1].end)
        self.assertEqual(self.bundle.kline_store.missing_ranges(self.spec.instrument_id, *interval), (interval,))

    def test_cancel_and_host_shutdown_while_refilling_return_without_evidence(self):
        for close_host in (False, True):
            with self.subTest(close_host=close_host):
                self.sdk.release, self.sdk.started = Event(), Event()
                cancel, errors = Event(), []

                def execute():
                    try:
                        self.run_host(cancel=cancel)
                    except DomainError as exc:
                        errors.append(exc.code)

                worker = Thread(target=execute)
                worker.start()
                self.assertTrue(self.sdk.started.wait(1))
                if close_host:
                    self.bundle.cancel_owned_workers()
                else:
                    cancel.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, ['research_worker_failed'])
                self.assertFalse(self.receipt_path.exists())
                self.sdk.release.set()
                self.sdk.query_thread.join(1)

    def test_host_cost_change_during_job_rejects_publication(self):
        self.sdk.on_query = lambda: setattr(self.bundle.engine, 'fees', replace(self.resources.fees, version='changed-costs'))
        with self.assertRaisesRegex(DomainError, 'state_conflict'):
            self.run_host()
        self.assertFalse(self.receipt_path.exists())

    def test_receipt_metadata_tampering_and_canceled_commit_are_rejected(self):
        receipt = self.run_host()
        for changes in (
            {'fees': replace(receipt.fees, futures_fee_per_contract=Decimal('999'))},
            {'raw_bars': receipt.raw_bars[:-1]},
            {'source': 'OTHER'},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(DomainError):
                replace(receipt, **changes)
        path = self.root / 'research' / 'cancel.sqlite3'
        store = MinuteReceiptStore(path, datetime.now(timezone.utc))

        def cancel():
            raise DomainError('research_worker_failed', 'canceled before commit')

        try:
            with self.assertRaises(DomainError):
                store.append(receipt, datetime.now(timezone.utc), before_commit=cancel)
            self.assertEqual(store.receipts, ())
        finally:
            store.close()
        reopened = MinuteReceiptStore(path, datetime.now(timezone.utc))
        try:
            self.assertEqual(reopened.receipts, ())
        finally:
            reopened.close()

    def test_cancellation_during_shared_limiter_wait_never_starts_sdk_query(self):
        waiting, release, cancel = Event(), Event(), Event()
        elapsed, errors = [0.0], []
        authority = self.bundle.market_history
        authority.clock = lambda: elapsed[0]

        def wait(seconds):
            waiting.set()
            release.wait(2)
            elapsed[0] += seconds

        authority.wait = wait
        for _ in range(40):
            authority.reserve_query()

        def execute():
            try:
                self.run_host(cancel=cancel)
            except DomainError as exc:
                errors.append(exc.code)

        worker = Thread(target=execute)
        worker.start()
        try:
            self.assertTrue(waiting.wait(1))
            cancel.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, ['research_worker_failed'])
            self.assertFalse(self.sdk.started.is_set())
            self.assertFalse(self.receipt_path.exists())
        finally:
            release.set()
            worker.join(2)
            if self.bundle.minute_research_retiring is not None:
                self.assertTrue(self.bundle.minute_research_retiring.close(timeout=1))

    def test_pre_canceled_admission_leaves_no_active_job_or_store(self):
        cancel = Event()
        cancel.set()
        with self.assertRaisesRegex(DomainError, 'canceled'):
            self.run_host(cancel=cancel)
        self.assertIsNone(self.bundle.minute_research_active)
        self.assertEqual(self.sdk.calls, [])
        self.assertFalse(self.receipt_path.exists())


class HistoryCancellationBoundaryTests(unittest.TestCase):
    def test_blocked_cache_write_does_not_block_zero_timeout_close_or_claim_retirement(self):
        from quantlab.trading.adapters.storage.kline_store import KlineStore
        from quantlab.trading.application.history_sync import HistorySync
        from quantlab.trading.runtime.minute_research import MinuteHistoryTarget
        from tests.test_minute_research_history import FakeHistory

        _, spec, _, rows, _, _ = fixture()
        entered, release, canceled = Event(), Event(), Event()
        writes = []
        with TemporaryDirectory() as directory:
            store = KlineStore(Path(directory) / 'cache.sqlite3')

            class BlockingStore:
                def __getattr__(self, name):
                    return getattr(store, name)

                def upsert(self, bars, *, source):
                    entered.set()
                    release.wait(2)
                    store.upsert(bars, source=source)
                    writes.append('bars')

                def mark_coverage(self, instrument, start, end):
                    store.mark_coverage(instrument, start, end)
                    writes.append('coverage')

            history = HistorySync(BlockingStore(), FakeHistory(rows), now=lambda: rows[-1].end + timedelta(days=1), autostart=False)
            history.request(MinuteHistoryTarget(spec.instrument_id), rows[0].start, rows[-1].end)
            worker = Thread(target=history.run_next)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                began = monotonic()
                self.assertFalse(history.watch_removed(spec.instrument_id, timeout=0))
                self.assertFalse(history.close(timeout=0))
                self.assertLess(monotonic() - began, 0.25)
                self.assertIsNone(history.progress(spec.instrument_id))
                from quantlab.trading.runtime.minute_research_wait import MinuteResearchBudget

                budget = MinuteResearchBudget(datetime.now(timezone.utc) + timedelta(seconds=0.05))
                began = monotonic()
                with self.assertRaisesRegex(DomainError, 'research_timeout'):
                    budget.wait_for_history(history, spec.instrument_id)
                self.assertLess(monotonic() - began, 0.25)

                def cancel():
                    self.assertTrue(history.watch_removed(spec.instrument_id))
                    canceled.set()

                canceler = Thread(target=cancel)
                canceler.start()
                self.assertFalse(canceled.wait(0.03))
                release.set()
                worker.join(1)
                canceler.join(1)
                self.assertTrue(canceled.is_set())
                self.assertEqual(writes, ['bars', 'coverage'])
                self.assertTrue(history.close(timeout=0))
                history.request(MinuteHistoryTarget(spec.instrument_id), rows[0].start, rows[-1].end)
                self.assertFalse(history.run_next())
                self.assertEqual(writes, ['bars', 'coverage'])
            finally:
                release.set()
                worker.join(2)
                history.close()
                store.close()


class MinuteWorkerCancellationTests(unittest.TestCase):
    def test_canceled_running_worker_reaps_only_its_owned_child(self):
        from quantlab.trading.domain.minute_research import complete_minutes
        from quantlab.trading.runtime.research_worker import SpawnResearchRunner, WorkerFault
        from quantlab.trading.runtime.minute_research_wait import MinuteResearchBudget

        strategy, spec, calendar, rows, fees, settings = fixture()
        bars = complete_minutes(rows, spec.instrument_id, calendar, settings, rows[-1].end)
        runner = SpawnResearchRunner(diagnostic_fault=WorkerFault.STALL_AFTER_DECODE)
        cancel, errors = Event(), []

        def run():
            try:
                runner.run(
                    strategy,
                    spec,
                    calendar,
                    bars,
                    fees,
                    minute_settings=settings,
                    cancel_event=cancel,
                    deadline=datetime.now(timezone.utc) + timedelta(seconds=10),
                )
            except DomainError as exc:
                errors.append(exc.code)

        worker = Thread(target=run)
        worker.start()
        until = monotonic() + 3
        while not runner.last_child_ready and worker.is_alive() and monotonic() < until:
            cancel.wait(0.01)
        self.assertTrue(runner.last_child_ready)
        cancel.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ['research_worker_failed'])
        self.assertTrue(runner.last_cleanup_verified)
        runner.close()
        budget = MinuteResearchBudget(datetime.now(timezone.utc) + timedelta(hours=1))
        self.assertLessEqual(budget.remaining(), 900)


class SharedHistoryQuotaTests(unittest.TestCase):
    def test_concurrent_watch_and_minute_workers_share_40_calls_per_ten_seconds(self):
        from collections import Counter
        from quantlab.trading.adapters.storage.kline_store import KlineStore
        from quantlab.trading.application.history_sync import HistorySync
        from quantlab.trading.ports.history import HistoryUsage
        from quantlab.trading.runtime.minute_research import MinuteHistoryTarget

        elapsed, calls = [0.0], []

        class Session:
            def usage(self):
                return HistoryUsage(0, 500 * 1024 * 1024)

            def history(self, instrument, start, end):
                calls.append(elapsed[0])
                return ()

        def wait(seconds):
            elapsed[0] += seconds

        start = datetime(2026, 10, 29, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            store = KlineStore(Path(directory) / 'shared.sqlite3')
            authority = HistorySync(store, Session(), clock=lambda: elapsed[0], wait=wait, autostart=False)
            minute = HistorySync(store, Session(), autostart=False, rate_limiter=authority.reserve_query)
            try:
                for index in range(30):
                    authority.request(MinuteHistoryTarget('watch-' + str(index)), start, start + timedelta(minutes=1))
                    minute.request(MinuteHistoryTarget('minute-' + str(index)), start, start + timedelta(minutes=1))

                def drain(sync):
                    while sync.run_next():
                        pass

                threads = [Thread(target=drain, args=(sync,)) for sync in (authority, minute)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
                self.assertEqual(len(calls), 60)
                self.assertLessEqual(max(Counter(calls).values()), 40)
                self.assertEqual(elapsed[0], 10)
                self.assertEqual(authority.state().history_error, ())
                self.assertEqual(minute.state().history_error, ())
            finally:
                authority.close()
                minute.close()
                store.close()

    def test_daily_returned_bar_budget_is_durable_across_owned_history_workers(self):
        from quantlab.trading.adapters.storage.kline_store import KlineStore
        from quantlab.trading.application.history_sync import HistorySync
        from quantlab.trading.runtime.minute_research import MinuteHistoryTarget
        from tests.test_minute_research_history import FakeHistory

        _, spec, _, rows, _, _ = fixture()
        now = rows[-1].end + timedelta(days=1)
        with TemporaryDirectory() as directory:
            store = KlineStore(Path(directory) / 'shared.sqlite3')
            session = FakeHistory(rows)
            authority = HistorySync(store, session, now=lambda: now, autostart=False)
            try:
                for index in range(2):
                    owned = HistorySync(store, session, now=lambda: now, autostart=False, rate_limiter=authority.reserve_query)
                    try:
                        owned.request(MinuteHistoryTarget(spec.instrument_id), rows[0].start, rows[-1].end, force=True)
                        self.assertTrue(owned.run_next())
                        self.assertEqual(store.queried_bars(now.date()), (index + 1) * len(rows))
                    finally:
                        owned.close()
                self.assertEqual(len(session.calls), 2)
            finally:
                authority.close()
                store.close()
