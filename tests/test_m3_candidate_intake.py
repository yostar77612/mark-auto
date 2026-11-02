"""Each intake refusal has an otherwise-valid fixture and a no-write assertion."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab.trading.application.candidate_intake import AutoBuildRequest, build_auto_strategy
from quantlab.trading.application.promotion_service import PromotionService
from quantlab.trading.application.signal_research import ExecutionEvidence
from quantlab.trading.application.research import ResearchTrade
from quantlab.trading.domain.models import Environment, HoldingKind, Side
from quantlab.trading.domain.promotion import ExecutionExpectation
from quantlab.trading.domain.signal_strategy import CandidateEvidence, SignalBar, SizingKind, SizingRule
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import StoredEvent
from quantlab.trading.runtime.build import synthetic_catalog
from tests.test_minute_research import fixture

D = Decimal
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
SPEC = json.dumps({'family': 'trend', 'parameters': {'fast': 1, 'slow': 2, 'quantity': 1}, 'rules': {}, 'schema_version': 1})


class MemoryJournal:
    def __init__(self):
        self.events = []

    def replay(self):
        return tuple(self.events)

    def append(self, kind, payload, now, *, expected_sequence):
        assert expected_sequence == len(self.events)
        event = StoredEvent(len(self.events) + 1, kind, payload, '', '')
        self.events.append(event)
        return event


class Catalog:
    def __init__(self, candidate):
        self.candidate = candidate

    def resolve(self, candidate_ref):
        return self.candidate


def candidate(**changes):
    row = CandidateEvidence('candidate-1', 'campaign-1', 'verified-by-catalog', 'statistical_edge', True, 12, NOW - timedelta(days=1), 'TMF', '1d', SPEC)
    return replace(row, **changes)


def request(**changes):
    row = AutoBuildRequest(
        'candidate-1', 'auto-1', 'account-1', HoldingKind.INTRADAY, 'TMF_NEAR', '1m', SizingRule(SizingKind.FIXED_CONTRACTS, contracts=1), start_in_sim=True
    )
    return replace(row, **changes)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        _, self.spec, self.calendar, rows, self.fees, self.settings = fixture()
        self.bars = tuple(SignalBar(b.start, b.end, b.trade_date, 'day', b.open, b.high, b.low, b.close, b.volume) for b in rows)
        self.journal = MemoryJournal()
        self.service = PromotionService(self.journal, Environment.BROKER_SIMULATION, now=NOW)
        self.evidence = SimpleNamespace(
            completed_trades=10,
            expectation=ExecutionExpectation(D('.01'), D('.001'), D('.5')),
            behavior_hash='behavior',
            source_digest='source',
            dataset_id='dataset',
            result_hash='result',
        )
        self.research = patch('quantlab.trading.application.candidate_intake.research_auto_strategy', side_effect=self.synthetic_evidence).start()
        self.addCleanup(patch.stopall)

    def synthetic_evidence(self, auto, *args, **kwargs):
        count = self.evidence.completed_trades
        trade = ResearchTrade(1, 2, 1, D(100), D(101), D(10), D(1))
        return ExecutionEvidence(
            auto.strategy_id,
            auto.version,
            auto.frozen_hash,
            'dataset',
            'result',
            'behavior',
            'source',
            self.evidence.expectation,
            (trade,) * count,
            D(90),
            D(10),
            20,
            kwargs['allocated_amount'],
            (Side.BUY,) * count,
        )

    def build(self, req=None, evidence=None, **changes):
        args = dict(
            catalog=Catalog(evidence or candidate()),
            source=None,
            spec=self.spec,
            calendar=self.calendar,
            bars=self.bars,
            fees=self.fees,
            allocated_amount=D('100000'),
            now=NOW,
            source_profile=None,
            service=self.service,
            settings=self.settings,
        )
        args.update(changes)
        return build_auto_strategy(req or request(), **args)

    def denied(self, code, **kwargs):
        before = tuple(self.journal.events)
        with self.assertRaises(DomainError) as error:
            self.build(**kwargs)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(tuple(self.journal.events), before)

    def test_build_freezes_records_once_and_never_starts_sim(self):
        result = self.build()
        self.assertEqual(result.record.auto.stage.value, 'BACKTEST')
        self.assertEqual(result.record.auto.thresholds_version, 'm3-thresholds-v1')
        self.assertEqual(result.record.auto.signal_spec_json, SPEC)
        self.assertEqual([e.kind for e in self.journal.events], ['auto_strategy_built'])
        self.assertEqual(self.service.records, (result.record,))
        self.assertFalse(result.record.permits_new_entries)
        self.assertEqual(result.record.auto.revised(protective_stop_pct=D('.02')).version, 2)

    def test_build_consent_type(self):
        with self.assertRaises(DomainError) as error:
            request(start_in_sim=1)
        self.assertEqual(error.exception.code, 'validation_failed')
        self.assertEqual(self.journal.events, [])

    def test_candidate_reference(self):
        self.denied('candidate_unavailable', evidence=candidate(candidate_ref='different'))

    def test_candidate_verdict(self):
        self.denied('candidate_not_passed', evidence=candidate(verdict='not_passed'))

    def test_candidate_consumed(self):
        self.denied('candidate_not_passed', evidence=candidate(oos_consumed=False))

    def test_candidate_samples(self):
        self.denied('candidate_not_passed', evidence=candidate(sample_count=0))

    def test_candidate_dataset(self):
        self.denied('candidate_data_mismatch', evidence=candidate(dataset_family='STOCK'))
        self.denied('candidate_data_mismatch', evidence=candidate(dataset_interval='5m'))

    def test_candidate_shape(self):
        self.denied('candidate_spec_unsupported', evidence=candidate(signal_spec_json='{}'))

    def test_candidate_json(self):
        self.denied('candidate_spec_unsupported', evidence=candidate(signal_spec_json='{'))

    def test_candidate_stop(self):
        body = json.loads(SPEC)
        body['parameters']['stop_ticks'] = 2
        self.denied('candidate_spec_unsupported', evidence=candidate(signal_spec_json=json.dumps(body)))

    def test_candidate_target(self):
        body = json.loads(SPEC)
        body['parameters']['target_ticks'] = 2
        self.denied('candidate_spec_unsupported', evidence=candidate(signal_spec_json=json.dumps(body)))

    def test_candidate_quantity(self):
        for value in (2, True, '1'):
            body = json.loads(SPEC)
            body['parameters']['quantity'] = value
            self.denied('candidate_spec_unsupported', evidence=candidate(signal_spec_json=json.dumps(body)))

    def test_quantity_omitted_is_v1_default_one(self):
        body = json.loads(SPEC)
        del body['parameters']['quantity']
        self.build(evidence=candidate(signal_spec_json=json.dumps(body)))

    def test_build_kind(self):
        self.denied('auto_instrument_not_allowed', req=request(holding_kind=HoldingKind.SWING))

    def test_build_contract(self):
        self.denied(
            'auto_instrument_not_allowed',
            spec=synthetic_catalog().instruments[0],
            req=request(instrument_rule=synthetic_catalog().instruments[0].instrument_id),
        )

    def test_build_instrument(self):
        self.denied('auto_instrument_not_allowed', req=request(instrument_rule='TX_NEAR'))

    def test_build_interval(self):
        self.denied('candidate_data_mismatch', req=request(bar_interval='1d'))

    def test_build_sizing(self):
        self.denied('auto_instrument_not_allowed', req=request(sizing=SizingRule(SizingKind.LOT_AMOUNT, amount=D('100000'))))

    def test_build_busy(self):
        self.build()
        self.denied('auto_instrument_busy', req=request(strategy_id='auto-2', instrument_rule=self.spec.instrument_id))

    def test_alias_contract_does_not_bypass_busy(self):
        self.build()
        alias = replace(self.spec, instrument_id=f'TMF:{self.spec.delivery_month}')
        self.denied('auto_instrument_busy', req=request(strategy_id='auto-2', instrument_rule=alias.instrument_id), spec=alias)

    def test_other_account_does_not_conflict(self):
        self.build()
        self.build(req=request(strategy_id='auto-2', account_ref='account-2'))
        self.assertEqual(len(self.journal.events), 2)

    def test_build_window(self):
        self.denied('auto_execution_data_insufficient', bars=())
        self.denied('auto_execution_data_insufficient', bars=(self.bars[0],) * 5001)

    def test_build_trades(self):
        self.evidence.completed_trades = 9
        self.denied('auto_execution_data_insufficient')

    def test_source_research_failure_has_no_write(self):
        self.research.side_effect = DomainError('auto_execution_data_insufficient')
        self.denied('auto_execution_data_insufficient')

    def test_catalog_failure_has_no_write(self):
        class Unavailable:
            def resolve(self, candidate_ref):
                raise DomainError('candidate_unavailable')

        self.denied('candidate_unavailable', catalog=Unavailable())


class BuildIntegrationTests(unittest.TestCase):
    def test_unmocked_e2_build_then_replay(self):
        from tests.test_m3_signal_research import Source, fixture as research_fixture

        args = research_fixture(days=2)
        args.pop('auto')
        args['source'] = Source((1, -1) * 10)
        journal = MemoryJournal()
        service = PromotionService(journal, Environment.BROKER_SIMULATION, now=args['now'])
        result = build_auto_strategy(request(), catalog=Catalog(candidate()), service=service, **args)
        self.assertGreaterEqual(result.evidence.completed_trades, 10)
        self.assertEqual(result.record.expectation, result.evidence.expectation)
        self.assertEqual(result.record.allocated_amount, args['allocated_amount'])
        self.assertEqual(result.record.auto.frozen_hash, result.evidence.frozen_hash)
        self.assertEqual(result.record.behavior_hash, result.evidence.behavior_hash)
        restored = PromotionService(journal, Environment.BROKER_SIMULATION, now=args['now'])
        self.assertEqual(restored.records, (result.record,))
        self.assertEqual(len(journal.events), 1)

    def test_unmocked_e2_insufficient_trades_no_journal(self):
        from tests.test_m3_signal_research import fixture as research_fixture

        args = research_fixture()
        args.pop('auto')
        journal = MemoryJournal()
        service = PromotionService(journal, Environment.BROKER_SIMULATION, now=args['now'])
        with self.assertRaises(DomainError) as error:
            build_auto_strategy(request(), catalog=Catalog(candidate()), service=service, **args)
        self.assertEqual(error.exception.code, 'auto_execution_data_insufficient')
        self.assertEqual(journal.events, [])
