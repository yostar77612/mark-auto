"""Official daily research uses PIT signals, raw fills and a parent-owned basis."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_m2_automatic as fixtures
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.concurrency import WriterLock
from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.application.research import research, research_fingerprint
from quantlab.trading.application.workflows import run_research
from quantlab.trading.domain.daily_signal_data import DailyResearchBasis, OfficialDailyHistory
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.stock_history import CorporateAction, DailyStockBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import research_worker as worker

D = Decimal


class OfficialDailyResearchTests(unittest.TestCase):
    def setUp(self):
        worker._initialize_types()
        self.engine = fixtures.MemoryEngine()
        self.engine.lock = WriterLock()
        self.calendar = self.engine.calendar
        self.days = self.calendar.days[:40]
        self.engine.clock.value = self.calendar.day_session(self.calendar.advance(self.days[-1], 1)).opens_at
        self.spec = replace(self.engine.catalog.instruments[0], effective_at=self.calendar.day_session(self.days[0]).opens_at)
        self.engine.catalog = type(self.engine.catalog)((self.spec, self.engine.catalog.instruments[1]))
        self.record = self.engine.make_record(interval='1d', state='RULE_VALID')
        self.record = replace(self.record, form=replace(self.record.form, rule_kind='BUY_AND_HOLD'))
        self.engine.record = self.record
        self.engine.state = replace(self.engine.state, strategies=(self.record,))
        bars = tuple(DailyStockBar(self.spec.instrument_id, day, D('100'), D('101'), D('99'), D('100'), 10000, 'a' * 64) for day in self.days)
        self.history = OfficialDailyHistory(self.spec.instrument_id, bars, (), self.engine.clock.now(), 'b' * 64)
        self.raw = self.history.raw_completed(self.calendar)
        manifest = (('quantlab/trading/application/research.py', 'a' * 64),)
        self.profile = ProducerProfile(
            'MARKAUTO-TRADING-V2-PROFILE-1', 2, manifest, sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        )
        self.engine.profile = self.profile
        self.engine.ownership_clock = self.engine.clock.now
        self.engine._strategy_spec = lambda spec, record: spec
        self.engine._strategy_calendar = lambda record, instrument: self.calendar
        self.engine.research_runner = None
        self.engine.daily_signal_source = SimpleNamespace(history=Mock(return_value=self.history))
        self.engine.update_strategy = lambda record, kind: self.engine._persist(kind, replace(self.engine.state, strategies=(record,)))

    def compute(self, history=None, **values):
        history = self.history if history is None else history
        return research(self.record, self.spec, self.calendar, history.raw_completed(self.calendar), self.engine.fees, daily_history=history, **values)

    def job(self, history=None):
        history = self.history if history is None else history
        return worker.ResearchJob(
            '1' * 32, self.record, self.spec, self.calendar, history.raw_completed(self.calendar), self.engine.fees, daily_history=history
        )

    def test_raw_fills_and_dataset_bind_original_official_basis(self):
        result = self.compute()
        basis = self.history.research_basis(self.days[0], self.days[-1])
        self.assertEqual(result.daily_basis, basis)
        self.assertEqual(result.dataset_id, sha256(dumps((self.raw, basis)).encode()).hexdigest())
        self.assertEqual(result.fingerprint, research_fingerprint(self.record, self.spec, self.calendar, self.engine.fees, result.dataset_id, None))
        self.assertEqual(result.trades[0].entry, D('100'))
        self.assertEqual(result.trades[0].exit, D('100'))
        self.assertEqual(tuple((trade.entry_index, trade.exit_index) for trade in result.trades), ((1, 11), (11, 21), (21, 31)))
        self.assertEqual(loads(dumps(result)), result)

    def test_official_raw_execution_uses_the_current_fee_and_slippage_schedule(self):
        self.engine.fees = replace(self.engine.fees, slippage_ticks=2, buy_rate=D('.001'), sell_rate=D('.001'), minimum_fee=D('20'))
        result = self.compute()
        trade = result.trades[0]
        self.assertEqual((trade.entry, trade.exit), (D('100.02'), D('99.98')))
        from quantlab.trading.domain.models import Side

        expected = self.engine.fees.transaction(self.spec, Side.BUY, trade.entry, 1000) + self.engine.fees.transaction(self.spec, Side.SELL, trade.exit, 1000)
        self.assertEqual(trade.costs, expected)

    def test_signals_rebuild_prior_completed_pit_windows_and_exclude_future_events(self):
        event = CorporateAction(self.spec.instrument_id, self.days[25], D('100'), D('90'), 'c' * 64, 'https://www.twse.com.tw/fixture')
        future = replace(event, ex_date=self.days[35], reference_price=D('50'))
        history = replace(self.history, events=(event, future))
        seen = []
        with patch('quantlab.trading.application.research.entry_signal', side_effect=lambda record, bars, now: seen.append((bars, now)) or False):
            self.compute(history)
        before = next(bars for bars, now in seen if now == self.raw[25].opened_at)
        after = next(bars for bars, now in seen if now == self.raw[26].opened_at)
        self.assertEqual(len(after), 20)
        self.assertEqual(before[0].close, D('100'))
        self.assertEqual(after[0].close, D('90'))
        self.assertEqual(after[-1].close, D('100'))
        self.assertTrue(all(bars[-1].available_at < now for bars, now in seen))

    def test_held_position_crossing_ex_date_cannot_invent_entitlements(self):
        event = CorporateAction(self.spec.instrument_id, self.days[5], D('100'), D('90'), 'c' * 64, 'https://www.twse.com.tw/fixture')
        with self.assertRaises(DomainError) as caught:
            self.compute(replace(self.history, events=(event,)))
        self.assertEqual(caught.exception.code, 'stock_entitlement_unknown')

    def test_typed_broker_daily_requires_source_and_rejects_mismatched_raw(self):
        with self.assertRaises(DomainError) as caught:
            research(self.record, self.spec, self.calendar, self.raw, self.engine.fees)
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        with self.assertRaises(DomainError) as caught:
            research(self.record, self.spec, self.calendar, (replace(self.raw[0], close=D('101')), *self.raw[1:]), self.engine.fees, daily_history=self.history)
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')

    def test_wrong_source_scope_or_unobserved_daily_close_is_rejected(self):
        for history in (object(), replace(self.history, observed_at=self.raw[-1].available_at - timedelta(seconds=1))):
            with self.subTest(history=history), self.assertRaises(DomainError):
                research(self.record, self.spec, self.calendar, self.raw, self.engine.fees, daily_history=history)
        local = replace(self.record, form=replace(self.record.form, environment=Environment.LOCAL))
        with self.assertRaises(DomainError):
            research(local, self.spec, self.calendar, self.raw, self.engine.fees, daily_history=self.history)

    def test_legacy_dataset_and_fingerprint_material_are_unchanged(self):
        legacy = replace(self.record, parameters=None, form=replace(self.record.form, environment=Environment.LOCAL))
        result = research(legacy, self.spec, self.calendar, self.raw, self.engine.fees)
        self.assertIsNone(result.daily_basis)
        dataset = sha256(dumps(self.raw).encode()).hexdigest()
        self.assertEqual(result.dataset_id, dataset)
        self.assertEqual(
            result.fingerprint,
            sha256(dumps((legacy.form, legacy.definition, legacy.policy, self.spec, self.calendar, self.engine.fees, dataset, None)).encode()).hexdigest(),
        )

    def test_minute_result_positional_fields_are_not_shifted_by_daily_basis(self):
        from quantlab.trading.application.minute_research import MinuteResearchResult

        result = MinuteResearchResult(
            's', 1, 'a' * 64, 'minute', 'TRAINING', D('0'), D('0'), D('0'), (), 10, 'b' * 64, '', '', None, 'calendar-v', 'fee-v', 'RAW_CONTRACT'
        )
        self.assertIsNone(result.daily_basis)
        self.assertEqual(
            (result.minute_settings, result.calendar_version, result.cost_version, result.price_basis), (None, 'calendar-v', 'fee-v', 'RAW_CONTRACT')
        )

    def test_worker_job_codec_and_parent_verified_basis_dataset_and_fingerprint(self):
        job = self.job()
        self.assertEqual(loads(dumps(job)), job)
        result = self.compute()
        self.assertEqual(worker.SpawnResearchRunner._validate_result(job, result), result)
        for changed in (
            replace(result, daily_basis=None),
            replace(result, daily_basis=replace(result.daily_basis, source_digest='d' * 64)),
            replace(result, dataset_id='e' * 64, fingerprint=research_fingerprint(self.record, self.spec, self.calendar, self.engine.fees, 'e' * 64, None)),
            replace(result, fingerprint='f' * 64),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(DomainError) as caught:
                    worker.SpawnResearchRunner._validate_result(job, changed)
                self.assertEqual(caught.exception.code, 'research_worker_failed')

    def test_worker_job_rejects_source_data_or_minute_mix_and_missing_official_history(self):
        job = self.job()
        with self.assertRaises(DomainError):
            replace(job, daily_history=None)
        with self.assertRaises(DomainError):
            replace(job, daily_history=object())
        from quantlab.trading.domain.minute_research import MinuteResearchSettings

        with self.assertRaises(DomainError):
            replace(job, minute_settings=MinuteResearchSettings(self.days[0], self.days[-1]))
        self.assertTrue(
            {'daily_signal_source_unverified', 'daily_signal_basis_mismatch', 'daily_signal_not_available', 'stock_entitlement_unknown'} <= worker.ERROR_CODES
        )

    def test_parent_rejects_an_official_claim_on_a_legacy_job(self):
        legacy = replace(self.record, parameters=None, form=replace(self.record.form, environment=Environment.LOCAL))
        job = worker.ResearchJob('1' * 32, legacy, self.spec, self.calendar, self.raw, self.engine.fees)
        result = research(legacy, self.spec, self.calendar, self.raw, self.engine.fees)
        forged = replace(result, daily_basis=self.history.research_basis(self.days[0], self.days[-1]))
        with self.assertRaises(DomainError):
            worker.SpawnResearchRunner._validate_result(job, forged)

    def test_workflow_rejects_runner_reply_that_claims_the_wrong_official_basis(self):
        valid = self.compute(source_profile=self.profile)
        for changed in (replace(valid, daily_basis=None), replace(valid, dataset_id='d' * 64)):
            self.engine.research_runner = SimpleNamespace(run=Mock(return_value=changed))
            with self.subTest(changed=changed):
                with self.engine.lock, self.assertRaises(DomainError) as caught:
                    run_research(self.engine, 'strategy:1', ())
                self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')

    def test_runner_admission_forwards_the_official_snapshot_without_extending_deadline(self):
        runner = worker.SpawnResearchRunner(self.engine.clock)
        deadline = self.engine.clock.now() + timedelta(seconds=20)
        with patch.object(runner, '_run', return_value=self.compute()) as run:
            runner.run(self.record, self.spec, self.calendar, self.raw, self.engine.fees, deadline=deadline, daily_history=self.history)
        self.assertIs(run.call_args.args[-1], self.history)
        self.assertEqual(run.call_args.args[5], deadline)

    def test_worker_builds_source_only_job_before_spawning_any_process(self):
        from time import monotonic

        runner = worker.SpawnResearchRunner(self.engine.clock)
        context = SimpleNamespace(Pipe=Mock(return_value=(Mock(), Mock())), Process=Mock(side_effect=RuntimeError('stop-before-spawn')))
        with patch.object(worker.multiprocessing, 'get_context', return_value=context):
            try:
                runner._run(
                    self.record,
                    self.spec,
                    self.calendar,
                    self.raw,
                    self.engine.fees,
                    self.engine.clock.now() + timedelta(seconds=30),
                    None,
                    monotonic() + 30,
                    daily_history=self.history,
                )
            except DomainError as error:
                self.fail('official history lost before process construction: ' + error.code)
            except RuntimeError as error:
                self.assertEqual(str(error), 'stop-before-spawn')
        context.Process.assert_called_once()

    def test_child_preserves_the_explicit_entitlement_error(self):
        event = CorporateAction(self.spec.instrument_id, self.days[5], D('100'), D('90'), 'c' * 64, 'https://www.twse.com.tw/fixture')
        job = self.job(replace(self.history, events=(event,)))
        channel = SimpleNamespace(recv_bytes=lambda limit: dumps(job).encode(), send_bytes=Mock(), close=Mock())
        with patch.object(worker, '_owner_guard', return_value=None):
            worker._research_child(channel, worker.WorkerFault.NONE.value, self.engine.clock.now().isoformat())
        reply = loads(channel.send_bytes.call_args_list[-1].args[0].decode())
        self.assertEqual(reply.error_code, 'stock_entitlement_unknown')
        self.assertIsNone(reply.result)

    def test_workflow_official_runner_receives_immutable_history_and_original_deadline(self):
        deadline = self.engine.clock.now() + timedelta(minutes=15)
        self.engine.research_runner = SimpleNamespace(run=Mock(return_value=self.compute(source_profile=self.profile)))
        with self.engine.lock:
            run_research(self.engine, 'strategy:1', ())
        kwargs = self.engine.research_runner.run.call_args.kwargs
        self.assertEqual(kwargs['daily_history'], self.history)
        self.assertEqual(kwargs['deadline'], deadline)

    def test_child_forwards_source_only_history_and_returns_official_basis(self):
        channel = SimpleNamespace(recv_bytes=lambda limit: dumps(self.job()).encode(), send_bytes=Mock(), close=Mock())
        with patch.object(worker, '_owner_guard', return_value=None):
            worker._research_child(channel, worker.WorkerFault.NONE.value, self.engine.clock.now().isoformat())
        reply = loads(channel.send_bytes.call_args_list[-1].args[0].decode())
        self.assertEqual(reply.error_code, '')
        self.assertIsInstance(reply.result.daily_basis, DailyResearchBasis)

    def test_workflow_fetches_outside_writer_uses_prior_civil_day_and_publishes_official_evidence(self):
        def fetch(*args, **kwargs):
            self.assertEqual(getattr(self.engine.lock._local, 'depth', 0), 0)
            self.assertEqual(kwargs, {'through': self.days[-1], 'start': self.days[0]})
            return self.history

        self.engine.daily_signal_source.history.side_effect = fetch
        with self.engine.lock:
            run_research(self.engine, 'strategy:1', ())
        record = self.engine.state.strategies[0]
        self.assertEqual(record.evidence, 'OFFICIAL_DAILY_TRAINING')
        self.assertIsNotNone(loads(record.research_blob).daily_basis)

    def test_workflow_missing_source_cannot_fallback_to_arbitrary_history(self):
        del self.engine.daily_signal_source
        with self.engine.lock, self.assertRaises(DomainError) as caught:
            run_research(self.engine, 'strategy:1', self.raw)
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        self.assertEqual(self.engine.state.strategies[0].state, 'RULE_VALID')

    def test_workflow_source_or_owner_replacement_prevents_publication(self):
        for replace_owner in (False, True):
            original_source = self.engine.daily_signal_source

            def fetch(*args, **kwargs):
                if replace_owner:
                    self.engine.automatic_owner_stamp = lambda: 'replacement-owner'
                else:
                    self.engine.daily_signal_source = SimpleNamespace(history=Mock(return_value=self.history))
                return self.history

            original_source.history.side_effect = fetch
            with self.subTest(owner=replace_owner):
                with self.engine.lock, self.assertRaises(DomainError) as caught:
                    run_research(self.engine, 'strategy:1', ())
                self.assertEqual(caught.exception.code, 'state_conflict')
                self.assertEqual(self.engine.state.strategies[0].state, 'RULE_VALID')
            self.engine.daily_signal_source = original_source

    def test_workflow_future_observation_or_absent_completed_day_is_not_research_evidence(self):
        self.engine.daily_signal_source.history.return_value = replace(self.history, observed_at=self.engine.clock.now() + timedelta(seconds=1))
        with self.engine.lock, self.assertRaises(DomainError) as caught:
            run_research(self.engine, 'strategy:1', ())
        self.assertEqual(caught.exception.code, 'daily_signal_source_unverified')
        self.engine.clock.value = self.calendar.day_session(self.days[0]).opens_at
        with self.engine.lock, self.assertRaises(DomainError) as caught:
            run_research(self.engine, 'strategy:1', ())
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')

    def test_workflow_parameter_fee_profile_or_lifecycle_race_prevents_publication(self):
        for kind in ('parameters', 'fees', 'profile', 'closed', 'storage'):
            self.setUp()

            def fetch(*args, **kwargs):
                if kind == 'parameters':
                    changed = replace(self.record, parameters=replace(self.record.parameters, stop_fraction=D('.04')))
                    self.engine.state = replace(self.engine.state, strategies=(changed,))
                elif kind == 'fees':
                    self.engine.fees = replace(self.engine.fees, minimum_fee=D('3'))
                elif kind == 'profile':
                    manifest = (('quantlab/trading/application/research.py', 'b' * 64),)
                    self.engine.profile = ProducerProfile(
                        'MARKAUTO-TRADING-V2-PROFILE-1',
                        2,
                        manifest,
                        sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest(),
                    )
                elif kind == 'closed':
                    self.engine.state = replace(self.engine.state, engine_closed=True)
                else:
                    self.engine.storage_failed = True
                return self.history

            self.engine.daily_signal_source.history.side_effect = fetch
            with self.subTest(kind=kind):
                with self.engine.lock, self.assertRaises(DomainError) as caught:
                    run_research(self.engine, 'strategy:1', ())
                self.assertEqual(caught.exception.code, 'state_conflict')
                self.assertNotEqual(self.engine.state.strategies[0].state, 'RESEARCHED')

    def test_workflow_same_owner_callable_with_changed_generation_is_rejected(self):
        value = ['owner-before']
        self.engine.automatic_owner_stamp = lambda: value[0]

        def fetch(*args, **kwargs):
            value[0] = 'owner-after'
            return self.history

        self.engine.daily_signal_source.history.side_effect = fetch
        with self.engine.lock, self.assertRaises(DomainError) as caught:
            run_research(self.engine, 'strategy:1', ())
        self.assertEqual(caught.exception.code, 'state_conflict')

    def test_workflow_completed_current_civil_day_is_still_excluded(self):
        today = self.calendar.advance(self.days[-1], 1)
        self.engine.clock.value = self.calendar.day_session(today).closes_at + timedelta(minutes=1)

        def fetch(*args, **kwargs):
            self.assertEqual(kwargs['through'], self.days[-1])
            return self.history

        self.engine.daily_signal_source.history.side_effect = fetch
        with self.engine.lock:
            run_research(self.engine, 'strategy:1', ())
        self.assertEqual(self.engine.state.strategies[0].state, 'RESEARCHED')

    def test_workflow_detects_revised_semantic_basis_but_accepts_transport_only_change(self):
        changed = replace(self.history, bars=(replace(self.history.bars[0], volume=999), *self.history.bars[1:]))
        self.engine.daily_signal_source.history.side_effect = (self.history, changed)
        with self.engine.lock, self.assertRaises(DomainError) as caught:
            run_research(self.engine, 'strategy:1', ())
        self.assertEqual(caught.exception.code, 'daily_signal_basis_mismatch')
        self.engine.daily_signal_source.history.side_effect = (self.history, replace(self.history, source_digest='d' * 64))
        with self.engine.lock:
            run_research(self.engine, 'strategy:1', ())
        self.assertEqual(self.engine.state.strategies[0].state, 'RESEARCHED')

    def test_daily_basis_wire_omits_only_absent_research_basis_and_preserves_official_value(self):
        result = self.compute()
        payload = json.loads(dumps(result))
        self.assertIn('daily_basis', payload['fields'])
        self.assertEqual(payload['fields']['daily_basis']['@'], 'quantlab.trading.domain.daily_signal_data.DailyResearchBasis')
        self.assertEqual(loads(dumps(result)), result)
        absent = replace(result, daily_basis=None)
        self.assertNotIn('daily_basis', json.loads(dumps(absent))['fields'])
        self.assertEqual(loads(dumps(absent)), absent)
        # Other optional DTO fields stay on the wire; this is a precise legacy result compatibility rule.
        self.assertIn('source_profile', json.loads(dumps(self.job()))['fields'])
        self.assertIsNone(json.loads(dumps(self.job()))['fields']['source_profile'])

    def test_daily_basis_wire_preserves_the_existing_minute_result_schema(self):
        import test_minute_research as minutes
        from quantlab.trading.application.minute_research import research_minutes
        from quantlab.trading.domain.minute_research import complete_minutes

        strategy, spec, calendar, rows, fees, settings = minutes.fixture()
        now = calendar.sessions[-1].closes_at + timedelta(days=1)
        bars = complete_minutes(rows, spec.instrument_id, calendar, settings, now)
        result = research_minutes(strategy, spec, calendar, bars, fees, settings=settings)
        self.assertIsNone(result.daily_basis)
        self.assertNotIn('daily_basis', json.loads(dumps(result))['fields'])
        self.assertEqual(loads(dumps(result)), result)
