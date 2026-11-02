"""Per-account close evidence, immutable day baselines and safe zero genesis."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_trading_adapters as fixtures
from test_live_order_guard import GuardJournal
from test_m2_account_risk import lot, order
from test_trading_execution_environments import LocalEnvironmentPort
from quantlab.trading.adapters.simulated import SimulatedBroker
from quantlab.trading.application.account_risk import account_entry_rejection, halt_account_risk, m2_account_refs, seed_account_baseline
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.manual_book import ManualBook, ManualRequest
from quantlab.trading.application.manual_contracts import ManualPurpose, ManualScope
from quantlab.trading.application.preflight import PreflightFacts, record_preflight
from quantlab.trading.application.sessions import DailyBaselineEvidence, confirm_daily_baseline, fee_fingerprint
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.application.workflows import mark_risk, resume, step
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, OrderStatus, Side
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.risk import AccountDailyBaseline, AccountRiskLimits
from quantlab.trading.domain.strategy import StrategyParameters
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_calendar

D = Decimal
SOURCE = 'FIXTURE_VERIFIED_ACCOUNT_CLOSE'


def baseline_engine(accounts=('test-stock',), *, environment=Environment.BROKER_SIMULATION, adopted=True):
    clock, spec, calendar = fixtures.MutableClock(), fixtures.instrument(), synthetic_calendar()
    brokers = {
        reference: SimulatedBroker(clock, replace(fixtures.account(), account_ref=reference), (spec,), replace(fixtures.capability(), account_ref=reference))
        for reference in accounts
    }
    configuration = ExecutionConfiguration(environment, accounts[0], accounts[1] if len(accounts) > 1 else '', False, True)
    engine = TradingEngine(
        GuardJournal(),
        clock,
        calendar,
        Catalog((spec,)),
        {reference: LocalEnvironmentPort(broker, environment) for reference, broker in brokers.items()},
        configuration=configuration,
        ownership_clock=clock.now,
        fees=FeeSchedule(),
    )
    if adopted:
        records = tuple(
            StrategyRecord(
                'strategy-' + reference,
                1,
                StrategyForm('typed', spec.market, HoldingKind.SWING, 2, 10, Side.BUY, spec.instrument_id, reference, environment, D('10000'), D('.02')),
                HoldingPolicy(HoldingKind.SWING, 2, 10),
                parameters=StrategyParameters('1d', D('.03'), D('10000')),
            )
            for reference in accounts
        )
        engine._persist('fixture_adopted_accounts', replace(engine.state, strategies=records))
    return engine


def close_proof(engine, *, total=D('0'), splits=()):
    day = engine.state.trading_day
    previous = engine.calendar.days[engine.calendar.index(day) - 1]
    return DailyBaselineEvidence(
        engine.configuration.environment,
        tuple(sorted(engine.gateways)),
        previous,
        day,
        engine.calendar.calendar_id,
        engine.calendar.version,
        engine.fees.version,
        fee_fingerprint(engine.fees),
        total,
        engine.calendar.day_session(previous).closes_at,
        SOURCE,
        account_previous_close=splits,
    )


def confirm(engine, proof):
    confirm_daily_baseline(engine, proof, trusted_sources=frozenset((SOURCE,)))


class M2AccountBaselineTests(unittest.TestCase):
    def test_explicit_limits_adopt_manual_only_account_and_cover_alternate_entry_owners(self):
        engine = baseline_engine(adopted=False)
        engine._persist(
            'fixture_explicit_limits_only',
            replace(
                engine.state,
                account_risk_limits=(AccountRiskLimits('test-stock', max_order_notional=D('1')),),
                account_daily_baselines=seed_account_baseline(engine, 'test-stock'),
            ),
        )
        self.assertEqual(m2_account_refs(engine), frozenset(('test-stock',)))
        self.assertFalse(engine.state.strategies)
        for strategy_id in ('legacy-strategy', 'manual-sim-book'):
            with self.subTest(strategy_id=strategy_id):
                intent = replace(fixtures.plan(fixtures.instrument()), strategy_id=strategy_id)
                self.assertEqual(account_entry_rejection(engine, intent, allocated_cash=D('60000')), 'account_order_limit')

    def test_deleted_typed_account_and_distinct_explicit_policy_account_both_stay_adopted(self):
        engine = baseline_engine(('a', 'b'))
        engine._persist(
            'fixture_distinct_adoption_sources',
            replace(engine.state, strategies=(replace(engine.state.strategies[0], state='DELETED'),), account_risk_limits=(AccountRiskLimits('b'),)),
        )
        self.assertEqual(m2_account_refs(engine), frozenset(('a', 'b')))

    def test_explicit_limits_do_not_fabricate_baseline_for_existing_manual_history(self):
        engine = baseline_engine(adopted=False)
        engine._persist(
            'fixture_existing_manual_history',
            replace(engine.state, positions=(lot(quantity=0, realized_pnl=D('-100')),), account_risk_limits=(AccountRiskLimits('test-stock'),)),
        )
        self.assertFalse(seed_account_baseline(engine, 'test-stock'))
        self.assertEqual(account_entry_rejection(engine, fixtures.plan(fixtures.instrument())), 'account_daily_baseline_required')

    def test_empty_ledger_genesis_is_zero_without_sampling_current_mark(self):
        engine = baseline_engine()
        with patch('quantlab.trading.application.account_risk.account_net_mark', side_effect=AssertionError('genesis must not sample current pnl')):
            values = seed_account_baseline(engine, 'test-stock')
        self.assertEqual(values, (AccountDailyBaseline('test-stock', engine.state.trading_day, D('0'), 'EMPTY_LEDGER_GENESIS'),))
        self.assertFalse(engine.state.account_daily_baselines)  # Caller owns the atomic transition.

    def test_seed_never_replaces_existing_account_history_even_from_prior_day(self):
        engine = baseline_engine()
        previous = AccountDailyBaseline('test-stock', engine.state.trading_day - timedelta(days=1), D('123'), SOURCE)
        engine._persist('fixture_prior_baseline', replace(engine.state, account_daily_baselines=(previous,)))
        self.assertEqual(seed_account_baseline(engine, 'test-stock'), (previous,))

    def test_zero_genesis_ignores_other_accounts_history(self):
        engine = baseline_engine()
        previous = AccountDailyBaseline('other-account', engine.state.trading_day, D('123'), SOURCE)
        engine._persist(
            'fixture_unrelated_account_history',
            replace(
                engine.state, account_daily_baselines=(previous,), positions=(lot(account_ref='other-account'),), orders=(order(account_ref='other-account'),)
            ),
        )
        self.assertEqual(
            seed_account_baseline(engine, 'test-stock'),
            (previous, AccountDailyBaseline('test-stock', engine.state.trading_day, D('0'), 'EMPTY_LEDGER_GENESIS')),
        )

    def test_seed_refuses_open_and_closed_position_history(self):
        for quantity in (0, 1000):
            with self.subTest(quantity=quantity):
                engine = baseline_engine()
                engine._persist('fixture_prior_position', replace(engine.state, positions=(lot(quantity=quantity, realized_pnl=D('-300')),)))
                self.assertFalse(seed_account_baseline(engine, 'test-stock'))

    def test_seed_refuses_unproven_order_history(self):
        engine = baseline_engine()
        engine._persist('fixture_old_order', replace(engine.state, orders=(order(status=OrderStatus.CANCELED),)))
        self.assertFalse(seed_account_baseline(engine, 'test-stock'))

    def diagnostic_genesis(self):
        engine = baseline_engine()
        book = ManualBook('manual-sim-fixture', 'test-stock', D('30000'), engine.state.trading_day)
        diagnostic = order('diagnostic', status=OrderStatus.CANCELED)
        diagnostic = replace(diagnostic, plan=replace(diagnostic.plan, strategy_id=book.book_id))
        scope = ManualScope('fixture-context', 1, Environment.BROKER_SIMULATION, 'test-stock', 'generation', 1)
        request = ManualRequest(
            scope,
            'diagnostic-request',
            'SUBMIT',
            'fixture-hash',
            ManualPurpose.DIAGNOSTIC_TMF,
            order_id=diagnostic.order_id,
            outcome_known=True,
            status='CANCELED',
        )
        engine._persist('fixture_confirmed_zero_sim_book', replace(engine.state, manual_books=(book,), orders=(diagnostic,), manual_requests=(request,)))
        return engine

    def test_confirmed_sim_book_allows_only_cancelled_zero_fill_diagnostic_genesis(self):
        engine = self.diagnostic_genesis()
        baseline = seed_account_baseline(engine, 'test-stock')
        self.assertEqual(baseline, (AccountDailyBaseline('test-stock', engine.state.trading_day, D('0'), 'APP_VIRTUAL_SIMULATION_GENESIS'),))

    def test_sim_genesis_requires_current_book_same_environment_and_confirmed_source(self):
        for field, value in (('opening_day', fixtures.NOW.date() - timedelta(days=1)), ('source', 'UNCONFIRMED')):
            with self.subTest(field=field):
                engine = self.diagnostic_genesis()
                engine._persist('fixture_invalid_book', replace(engine.state, manual_books=(replace(engine.state.manual_books[0], **{field: value}),)))
                self.assertFalse(seed_account_baseline(engine, 'test-stock'))
        engine = self.diagnostic_genesis()
        engine.configuration = replace(engine.configuration, environment=Environment.LOCAL)
        self.assertFalse(seed_account_baseline(engine, 'test-stock'))

    def test_sim_genesis_refuses_unknown_filled_costly_or_wrong_owner_diagnostic(self):
        for changes in ({'status': OrderStatus.UNKNOWN}, {'filled': 1}, {'costs': D('1')}, {'plan': replace(order().plan, strategy_id='other-owner')}):
            with self.subTest(changes=changes):
                engine = self.diagnostic_genesis()
                engine._persist('fixture_invalid_diagnostic', replace(engine.state, orders=(replace(engine.state.orders[0], **changes),)))
                self.assertFalse(seed_account_baseline(engine, 'test-stock'))

    def test_sim_genesis_requires_known_diagnostic_receipt_for_same_account(self):
        for changes in (
            {'purpose': ManualPurpose.MANUAL},
            {'outcome_known': False},
            {'order_id': 'other-order'},
            {'scope': ManualScope('fixture-context', 1, Environment.BROKER_SIMULATION, 'other-account', 'generation', 1)},
        ):
            with self.subTest(changes=changes):
                engine = self.diagnostic_genesis()
                engine._persist('fixture_invalid_receipt', replace(engine.state, manual_requests=(replace(engine.state.manual_requests[0], **changes),)))
                self.assertFalse(seed_account_baseline(engine, 'test-stock'))

    def test_sim_genesis_requires_same_verified_trading_day_diagnostic(self):
        engine = self.diagnostic_genesis()
        old = engine.calendar.day_session(engine.calendar.days[engine.calendar.index(engine.state.trading_day) - 1]).opens_at
        previous_order = replace(engine.state.orders[0], plan=replace(engine.state.orders[0].plan, decision_at=old))
        engine._persist('fixture_old_diagnostic', replace(engine.state, orders=(previous_order,)))
        self.assertFalse(seed_account_baseline(engine, 'test-stock'))

    def test_risk_halt_persists_warning_and_only_daily_loss_latches_account(self):
        for code in ('account_order_limit', 'account_position_limit', 'account_daily_loss_limit'):
            with self.subTest(code=code):
                engine = baseline_engine()
                halt_account_risk(engine, fixtures.plan(fixtures.instrument()), code)
                self.assertTrue(engine.state.stopped)
                self.assertIn(code, engine.state.issues)
                self.assertEqual(bool(engine.state.account_daily_locks), code == 'account_daily_loss_limit')
                self.assertFalse(engine.state.orders)

    def test_risk_halt_preserves_previous_locks_and_exempts_reductions(self):
        engine = baseline_engine()
        earlier = ('other-account', engine.state.trading_day - timedelta(days=1))
        engine._persist('fixture_old_lock', replace(engine.state, account_daily_locks=(earlier,), stopped=False))
        before = engine.state
        halt_account_risk(engine, replace(fixtures.plan(fixtures.instrument()), reduce_only=True), 'account_daily_loss_limit')
        self.assertIs(engine.state, before)
        halt_account_risk(engine, fixtures.plan(fixtures.instrument()), 'account_daily_loss_limit')
        halt_account_risk(engine, fixtures.plan(fixtures.instrument()), 'account_daily_loss_limit')
        self.assertEqual(engine.state.account_daily_locks, (earlier, ('test-stock', engine.state.trading_day)))

    def test_risk_halt_preserves_existing_unknown_outcome_issue(self):
        engine = baseline_engine()
        engine._persist('fixture_existing_issue', replace(engine.state, issues=('outcome_unknown',)))
        halt_account_risk(engine, fixtures.plan(fixtures.instrument()), 'account_order_limit')
        self.assertEqual(set(engine.state.issues), {'outcome_unknown', 'account_order_limit'})

    def test_exact_account_splits_commit_with_global_evidence_without_sampling_current_marks(self):
        engine = baseline_engine(('a', 'b'))
        proof = close_proof(engine, total=D('30'), splits=(('a', D('10')), ('b', D('20'))))
        with patch('quantlab.trading.application.workflows.total_mark', return_value=D('999')):
            confirm(engine, proof)
        self.assertEqual({row.account_ref: row.previous_close_pnl for row in engine.state.account_daily_baselines}, {'a': D('10'), 'b': D('20')})
        self.assertEqual(engine.state.daily_baseline_evidence, proof)
        self.assertEqual(engine.state.daily_baseline_pnl, D('30'))
        self.assertEqual(engine.state.daily_pnl, D('969'))
        self.assertNotIn('account_daily_baseline_required', engine.state.issues)
        self.assertTrue(engine.state.stopped)

    def test_old_single_account_proof_derives_sole_mark(self):
        engine = baseline_engine()
        confirm(engine, close_proof(engine, total=D('12')))
        self.assertEqual(engine.state.account_daily_baselines, (AccountDailyBaseline('test-stock', engine.state.trading_day, D('12'), SOURCE),))

    def test_old_wire_proof_without_account_split_field_still_decodes(self):
        engine = baseline_engine()
        raw = json.loads(dumps(close_proof(engine, total=D('12'))))
        del raw['fields']['account_previous_close']
        restored = loads(json.dumps(raw))
        self.assertEqual(restored.account_previous_close, ())
        confirm(engine, restored)
        self.assertEqual(engine.state.account_daily_baselines[0].previous_close_pnl, D('12'))

    def test_multi_account_aggregate_never_fabricates_splits(self):
        engine = baseline_engine(('a', 'b'))
        confirm(engine, close_proof(engine, total=D('30')))
        self.assertFalse(engine.state.account_daily_baselines)
        self.assertIn('account_daily_baseline_required', engine.state.issues)
        self.assertFalse(engine.state.daily_baseline_required)
        self.assertTrue(engine.state.stopped)

    def test_split_boundary_rejects_duplicates_missing_wrong_order_and_extra_accounts(self):
        engine = baseline_engine(('a', 'b'))
        for splits in (
            (('a', D('0')), ('a', D('0'))),
            (('a', D('0')),),
            (('b', D('0')), ('a', D('0'))),
            (('a', D('0')), ('c', D('0'))),
            (('a', D('0')), ('b', D('0')), ('c', D('0'))),
        ):
            with self.subTest(splits=splits), self.assertRaises(DomainError):
                close_proof(engine, splits=splits)

    def test_split_boundary_requires_typed_finite_pairs_and_exact_total(self):
        engine = baseline_engine()
        for splits in (
            [('test-stock', D('0'))],
            (['test-stock', D('0')],),
            (('test-stock',),),
            (('test-stock', '0'),),
            (('test-stock', D('NaN')),),
            (('test-stock', D('Infinity')),),
            (('test-stock', D('1')),),
        ):
            with self.subTest(splits=splits), self.assertRaises(DomainError):
                close_proof(engine, splits=splits)

    def test_split_sum_uses_isolated_decimal_context(self):
        engine = baseline_engine(('a', 'b'))
        with localcontext() as context:
            context.prec = 3
            proof = close_proof(engine, total=D('12345.67'), splits=(('a', D('12345.66')), ('b', D('.01'))))
        self.assertEqual(proof.previous_close_total_pnl, D('12345.67'))

    def test_same_day_baseline_is_immutable_even_when_total_is_unchanged(self):
        engine = baseline_engine(('a', 'b'))
        proof = close_proof(engine, total=D('30'), splits=(('a', D('10')), ('b', D('20'))))
        confirm(engine, proof)
        retained = engine.state.account_daily_baselines
        with self.assertRaises(DomainError) as rejected:
            confirm(engine, close_proof(engine, total=D('30'), splits=(('a', D('11')), ('b', D('19')))))
        self.assertEqual(rejected.exception.code, 'state_conflict')
        self.assertEqual(engine.state.account_daily_baselines, retained)
        confirm(engine, proof)
        self.assertEqual(engine.state.account_daily_baselines, retained)

    def test_new_trading_day_uses_new_attested_close_and_retains_prior_day_lock(self):
        engine = baseline_engine()
        confirm(engine, close_proof(engine, total=D('12')))
        previous_day = engine.state.trading_day
        lock = ('test-stock', previous_day)
        engine._persist('fixture_previous_loss_lock', replace(engine.state, account_daily_locks=(lock,)))
        next_day = engine.calendar.advance(previous_day, 1)
        engine.clock.value = engine.calendar.day_session(next_day).opens_at + timedelta(minutes=5)
        from quantlab.trading.application.sessions import synchronize_session

        synchronize_session(engine)
        confirm(engine, close_proof(engine, total=D('25')))
        self.assertEqual(engine.state.account_daily_baselines, (AccountDailyBaseline('test-stock', next_day, D('25'), SOURCE),))
        self.assertEqual(engine.state.account_daily_locks, (lock,))

    def test_untrusted_proof_never_commits_account_marks(self):
        engine = baseline_engine()
        with self.assertRaises(DomainError):
            confirm_daily_baseline(engine, close_proof(engine), trusted_sources=frozenset(('OTHER_SOURCE',)))
        self.assertFalse(engine.state.account_daily_baselines)

    def test_incomplete_reconciliation_never_commits_account_marks(self):
        engine = baseline_engine()
        with patch('quantlab.trading.application.events.reconcile', return_value=None), self.assertRaises(DomainError) as rejected:
            confirm(engine, close_proof(engine))
        self.assertEqual(rejected.exception.code, 'reconciliation_required')
        self.assertFalse(engine.state.account_daily_baselines)

    def test_account_pending_clears_only_when_every_adopted_account_is_proven_and_locks_remain(self):
        engine = baseline_engine(('a', 'b'))
        latch = ('a', engine.state.trading_day)
        engine._persist('fixture_account_pending', replace(engine.state, issues=('account_daily_baseline_required',), account_daily_locks=(latch,)))
        confirm(engine, close_proof(engine))
        self.assertIn('account_daily_baseline_required', engine.state.issues)
        confirm(engine, close_proof(engine, splits=(('a', D('0')), ('b', D('0')))))
        self.assertNotIn('account_daily_baseline_required', engine.state.issues)
        self.assertEqual(engine.state.account_daily_locks, (latch,))

    def test_restart_keeps_existing_baseline_and_pause_and_never_seeds_missing_proof(self):
        for proven in (False, True):
            with self.subTest(proven=proven):
                engine = baseline_engine()
                if proven:
                    confirm(engine, close_proof(engine, total=D('12')))
                retained = engine.state.account_daily_baselines
                engine._persist('fixture_running_before_restart', replace(engine.state, stopped=False))
                with patch('quantlab.trading.application.account_risk.seed_account_baseline', side_effect=AssertionError('restart must never seed')):
                    restarted = TradingEngine(
                        engine.journal,
                        engine.clock,
                        engine.calendar,
                        engine.catalog,
                        engine.gateways,
                        configuration=engine.configuration,
                        ownership_clock=engine.clock.now,
                        fees=engine.fees,
                    )
                self.assertEqual(restarted.state.account_daily_baselines, retained)
                self.assertTrue(restarted.state.stopped)

    def test_local_step_records_prior_account_mark_before_advancing_and_keeps_locks(self):
        engine = baseline_engine(environment=Environment.LOCAL)
        entry = replace(order('entry', status=OrderStatus.FILLED, costs=D('5')), filled=1000)
        closed = lot('entry', quantity=0, realized_pnl=D('125'))
        engine._persist(
            'fixture_closed_history',
            replace(engine.state, positions=(closed,), orders=(entry,), realized_pnl=D('120'), account_daily_locks=(('test-stock', engine.state.trading_day),)),
        )
        previous_day = engine.state.trading_day
        engine.simulation = SimpleNamespace(advance=lambda day, now: setattr(engine.clock, 'value', now))
        step(engine, {})
        self.assertEqual(engine.state.trading_day, engine.calendar.advance(previous_day, 1))
        self.assertEqual(engine.state.account_daily_baselines, (AccountDailyBaseline('test-stock', engine.state.trading_day, D('120'), 'LOCAL_DAY_ADVANCE'),))
        self.assertEqual(engine.state.account_daily_locks, (('test-stock', previous_day),))

    def test_local_step_samples_account_mark_before_clock_advances(self):
        engine = baseline_engine(environment=Environment.LOCAL)
        before = engine.clock.now()
        engine.simulation = SimpleNamespace(advance=lambda day, now: setattr(engine.clock, 'value', now))

        def previous_mark(current, reference):
            self.assertEqual(current.clock.now(), before)
            return D('120')

        with patch('quantlab.trading.application.workflows.account_net_mark', side_effect=previous_mark):
            step(engine, {})
        self.assertEqual(engine.state.account_daily_baselines[0].previous_close_pnl, D('120'))

    def test_public_local_step_records_failed_new_day_check_and_keeps_entries_stopped(self):
        engine = baseline_engine(environment=Environment.LOCAL)
        engine._persist(
            'fixture_running_local_day',
            replace(engine.state, reconciled=True, stopped=False, account_daily_baselines=seed_account_baseline(engine, 'test-stock')),
        )
        record_preflight(engine, 'test-stock', PreflightFacts(True, True, True, None, True, True, True))
        previous_day = engine.state.trading_day
        engine.simulation = SimpleNamespace(advance=lambda day, now: setattr(engine.clock, 'value', now))
        receipt = LocalFacade(engine).execute(UiCommand(UiAction.STEP, engine.state.version))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'preflight_blocked')
        self.assertEqual(engine.state.trading_day, engine.calendar.advance(previous_day, 1))
        self.assertTrue(engine.state.stopped)
        self.assertIn(('test-stock', engine.state.trading_day), engine.state.preflight_blocks)
        check = next(row for row in engine.state.preflight if row.account_ref == 'test-stock')
        self.assertEqual(check.trade_date, engine.state.trading_day)
        self.assertTrue(check.blocked_today)
        self.assertIn('preflight_market', check.block_reasons)

    def test_broker_context_cannot_advance_or_collect_local_day_preflight(self):
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            with self.subTest(environment=environment):
                engine = baseline_engine(environment=environment)
                engine.simulation = SimpleNamespace(advance=lambda day, now: self.fail('broker context cannot advance a local day'))
                with patch('quantlab.trading.application.workflows.record_preflight') as record, self.assertRaises(DomainError) as rejected:
                    step(engine, {})
                self.assertEqual(rejected.exception.code, 'capability_missing')
                record.assert_not_called()

    def test_global_resume_requires_account_loss_guard_and_preflight_after_old_reconciliation_gate(self):
        engine = baseline_engine(environment=Environment.LOCAL)
        engine._persist('fixture_reconciled', replace(engine.state, reconciled=True, account_daily_baselines=seed_account_baseline(engine, 'test-stock')))
        with self.assertRaises(DomainError) as rejected:
            resume(engine)
        self.assertEqual(rejected.exception.code, 'preflight_blocked')
        record_preflight(engine, 'test-stock', PreflightFacts(True, True, True, None, True, True, True))
        resume(engine)
        self.assertFalse(engine.state.stopped)
        engine._persist('fixture_daily_lock', replace(engine.state, stopped=True, account_daily_locks=(('test-stock', engine.state.trading_day),)))
        with self.assertRaises(DomainError) as rejected:
            resume(engine)
        self.assertEqual(rejected.exception.code, 'account_daily_loss_limit')

    def test_account_monitor_runs_before_generic_mark_even_without_a_signal(self):
        engine = baseline_engine(environment=Environment.LOCAL)
        engine._persist(
            'fixture_account_loss',
            replace(engine.state, account_daily_baselines=(AccountDailyBaseline('test-stock', engine.state.trading_day, D('2000'), SOURCE),)),
        )
        with patch('quantlab.trading.application.workflows._risk_mark', return_value=None):
            mark_risk(engine)
        self.assertIn(('test-stock', engine.state.trading_day), engine.state.account_daily_locks)
        self.assertIn('account_daily_loss_limit', engine.state.issues)
        self.assertTrue(engine.state.stopped)
        self.assertFalse(engine.state.orders)

    def test_zero_allocation_inactive_account_does_not_create_false_daily_loss(self):
        engine = baseline_engine(environment=Environment.LOCAL)
        engine._persist(
            'fixture_retired_zero_allocation',
            replace(
                engine.state,
                settings=replace(engine.state.settings, stock_allocation=D('0')),
                strategies=(replace(engine.state.strategies[0], state='DELETED'),),
                account_daily_baselines=(AccountDailyBaseline('test-stock', engine.state.trading_day, D('0'), SOURCE),),
                stopped=False,
            ),
        )
        before = engine.state
        with patch('quantlab.trading.application.workflows._risk_mark', return_value=None):
            mark_risk(engine)
        self.assertIs(engine.state, before)
        self.assertFalse(engine.state.account_daily_locks)


if __name__ == '__main__':
    unittest.main()
