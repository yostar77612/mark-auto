"""Real native day rollover keeps shared proof and lifetime capital distinct."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_m2_daily_native as native
import test_manual_trading as legacy
import test_trading_adapters as market_fixtures

from quantlab.trading.application.automatic_baseline import confirm_automatic_baseline
from quantlab.trading.application.daily_closes import SOURCE_ID, daily_close_evidence
from quantlab.trading.application.daily_execution import continue_daily_session, dispatch_daily, observe_daily
from quantlab.trading.application.manual_book import (
    ManualBook,
    ManualRequest,
    assert_manual_plan,
    book_for,
    manual_capacity,
    manual_daily_pnl,
    manual_day_ready,
    manual_net_pnl,
    manual_policy,
    release_manual_day_wait,
)
from quantlab.trading.application.manual_contracts import ManualBookForm
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.account_risk import account_markets_closed, account_net_mark, observe_account_limits
from quantlab.trading.application.automatic_state import AutomaticState
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.daily_state import DailyState
from quantlab.trading.application.state import AppState
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, Market, PositionLot, Quote
from quantlab.trading.domain.risk import AccountDailyBaseline, AccountRiskLimits
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.preflight import sinopac_preflight_facts
from quantlab.trading.runtime.build import synthetic_calendar


class ManualDailyBaselineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native.DailyNativeFixture(self.addCleanup)
        self.record = self.fixture.deploy()
        self.fixture.start()
        self.engine = self.fixture.engine
        self.original_books = self.engine.state.manual_books

    def advance(self, *, attest=True, old_loss=D('0')):
        fixture, engine = self.fixture, self.engine
        if old_loss:
            book = book_for(engine, fixture.account_ref)
            history = PositionLot(
                'recorded-closed-history',
                book.account_ref,
                fixture.spec.instrument_id,
                book.book_id,
                1,
                manual_policy(),
                0,
                D('20'),
                fixture.signal_day,
                0,
                realized_pnl=old_loss,
            )
            engine._persist('recorded_prior_ledger_history', replace(engine.state, positions=(*engine.state.positions, history)))
        fixture.close()
        fixture.close_other_accounts()
        fixture.refresh(fixture.next_session().opens_at + timedelta(minutes=1), stock_price=D('20'))
        self.proof = daily_close_evidence(engine, engine.state.trading_day)
        if attest:
            confirm_automatic_baseline(engine, self.proof, trusted_sources=frozenset((SOURCE_ID,)))
        return book_for(engine, fixture.account_ref)

    def persist(self, **values):
        self.engine._persist('offline_proof_mutation', replace(self.engine.state, **values))

    def release(self):
        with self.engine.lock:
            release_manual_day_wait(self.engine)

    def open_daily_stock(self):
        self.advance(attest=False)
        fixture = self.fixture
        facts = tuple((ref, sinopac_preflight_facts(fixture.bundle, ref)) for ref in sorted(self.engine.gateways))
        continue_daily_session(self.engine, facts)
        self.assertTrue(all(row.consumed_on == self.engine.state.trading_day for row in self.engine.state.daily_account_closes))
        dispatch_daily(self.engine)
        fixture.case.native.fill(fixture.case.native.trades[-1], 1, D('20'))
        fixture.adopt(fixture.clock.now())

    def test_actual_new_day_adopt_does_not_rehalt_after_committed_exact_shared_proof(self):
        self.advance()
        self.assertTrue(all(manual_day_ready(self.engine, book) for book in self.engine.state.manual_books))
        self.assertTrue(all('manual_day_baseline_required' in book.reasons for book in self.engine.state.manual_books))
        native_count = self.fixture.placed()
        self.release()
        self.fixture.adopt(self.engine.clock.now() + timedelta(seconds=1))
        self.assertTrue(all(not book.halted for book in self.engine.state.manual_books))
        self.assertTrue(all('manual_day_baseline_required' not in book.reasons for book in self.engine.state.manual_books))
        self.assertEqual(
            tuple((b.opening_day, b.capital) for b in self.engine.state.manual_books), tuple((b.opening_day, b.capital) for b in self.original_books)
        )
        self.assertEqual(self.fixture.placed(), native_count)

    def test_shared_pool_includes_diagnostic_only_other_account_and_deleted_typed_record(self):
        self.advance(old_loss=D('-12000'))
        self.persist(strategies=tuple(replace(row, state='DELETED') for row in self.engine.state.strategies))
        self.assertTrue(all(manual_day_ready(self.engine, book) for book in self.engine.state.manual_books))
        self.assertTrue(all(manual_daily_pnl(self.engine, book) == D('0') for book in self.engine.state.manual_books))
        self.assertEqual({row.form.account_ref for row in self.engine.state.strategies}, {self.fixture.account_ref})
        self.assertGreater(len(self.engine.state.manual_books), 1)

    def test_pure_manual_old_day_guard_is_not_bypassed_by_persisted_automatic_evidence(self):
        book = self.advance()
        self.persist(strategies=())
        self.assertFalse(manual_day_ready(self.engine, book))
        self.release()
        self.assertTrue(all(row.halted for row in self.engine.state.manual_books))
        self.fixture.adopt(self.engine.clock.now())
        self.assertTrue(all('manual_day_baseline_required' in row.reasons for row in self.engine.state.manual_books))

    def test_original_same_day_manual_readiness_remains_valid_without_daily_evidence(self):
        self.persist(strategies=(), automatic_daily_evidence=None)
        self.assertTrue(all(manual_day_ready(self.engine, book) for book in self.engine.state.manual_books))

    def test_nonvirtual_or_live_context_cannot_adopt_old_day_proof(self):
        book = self.advance(old_loss=D('-12000'))
        self.assertFalse(manual_day_ready(self.engine, replace(book, source='BROKER_BALANCE')))
        self.assertEqual(manual_daily_pnl(self.engine, replace(book, source='BROKER_BALANCE')), D('-12000'))
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE)
        self.persist(automatic_daily_evidence=replace(self.proof, environment=Environment.LIVE))
        self.assertFalse(manual_day_ready(self.engine, book))

    def test_single_account_committed_aggregate_retains_existing_exact_derivation(self):
        self.fixture = native.DailyNativeFixture(self.addCleanup, stock=False)
        self.record = self.fixture.deploy()
        self.fixture.start()
        self.engine = self.fixture.engine
        book = self.advance()
        self.persist(automatic_daily_evidence=replace(self.proof, account_previous_close=()))
        self.assertTrue(manual_day_ready(self.engine, book))

    def test_first_day_shared_daily_mark_still_requires_one_current_account_baseline(self):
        book = book_for(self.engine, self.fixture.account_ref)
        self.assertEqual(manual_daily_pnl(self.engine, book), D('0'))
        rows = self.engine.state.account_daily_baselines
        current = next(row for row in rows if row.account_ref == book.account_ref)
        for changed in (tuple(row for row in rows if row.account_ref != book.account_ref), (*rows, current)):
            self.persist(account_daily_baselines=changed)
            with self.assertRaises(DomainError) as caught:
                manual_daily_pnl(self.engine, book)
            self.assertEqual(caught.exception.code, 'manual_day_baseline_required')

    def test_actual_pure_manual_next_day_still_halts_original_book(self):
        case = legacy.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        case.confirm_test()
        book = book_for(case.engine, 'future-alias')
        day = case.engine.calendar.advance(case.engine.state.trading_day, 1)
        case.clock.value = case.engine.calendar.day_session(day).opens_at + timedelta(minutes=1)
        for ref, capability in case.adapter.capabilities.items():
            case.adapter.capabilities[ref] = replace(capability, checked_at=case.clock.now(), expires_at=case.clock.now() + timedelta(hours=2))
        quote = case.engine.quotes[case.spec.instrument_id]
        case.engine.quote(replace(quote, trade_date=day, source_at=case.clock.now(), received_at=case.clock.now()))
        case.observe()
        current = book_for(case.engine, book.account_ref)
        self.assertTrue(current.halted)
        self.assertIn('manual_day_baseline_required', current.reasons)
        self.assertEqual((current.opening_day, current.capital), (book.opening_day, book.capital))

    def test_missing_attestation_or_account_baseline_keeps_halt_and_current_cache(self):
        book = self.advance(attest=False)
        observations = self.engine.manual_observations
        self.assertFalse(manual_day_ready(self.engine, book))
        self.release()
        self.fixture.adopt(self.engine.clock.now())
        self.assertEqual(self.engine.manual_observations, observations)
        self.assertTrue(book_for(self.engine, book.account_ref).halted)
        self.assertNotIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        with self.assertRaises(DomainError) as caught:
            manual_daily_pnl(self.engine, book)
        self.assertEqual(caught.exception.code, 'manual_day_baseline_required')

    def test_bad_fee_values_same_version_invalidate_old_day_readiness(self):
        book = self.advance()
        self.engine.fees = replace(self.engine.fees, minimum_fee=self.engine.fees.minimum_fee + D('1'))
        self.assertFalse(manual_day_ready(self.engine, book))

    def test_wrong_accounts_calendar_date_or_exact_close_are_not_ready(self):
        book = self.advance()
        proof = self.proof
        subset = proof.account_refs[:1]
        variations = (
            replace(proof, account_refs=subset, account_previous_close=((subset[0], D('0')),)),
            replace(proof, calendar_id='wrong-calendar'),
            replace(proof, calendar_version='wrong-version'),
            replace(proof, trade_date=proof.trade_date + timedelta(days=1)),
            replace(proof, as_of=proof.as_of - timedelta(seconds=1)),
            replace(proof, environment=Environment.LIVE),
        )
        for evidence in variations:
            with self.subTest(evidence=evidence):
                self.persist(automatic_daily_evidence=evidence)
                self.assertFalse(manual_day_ready(self.engine, book))

    def test_aggregate_multiactount_proof_cannot_invent_missing_splits(self):
        book = self.advance()
        self.persist(automatic_daily_evidence=replace(self.proof, account_previous_close=()))
        self.assertFalse(manual_day_ready(self.engine, book))

    def test_source_and_value_must_match_every_committed_account_not_only_target(self):
        book = self.advance()
        rows = self.engine.state.account_daily_baselines
        for field, value in (('source_id', 'wrong-source'), ('previous_close_pnl', D('1'))):
            for index in range(len(rows)):
                with self.subTest(field=field, index=index):
                    changed = tuple(replace(row, **{field: value}) if position == index else row for position, row in enumerate(rows))
                    self.persist(account_daily_baselines=changed)
                    self.assertFalse(manual_day_ready(self.engine, book))
        self.persist(account_daily_baselines=rows, automatic_daily_evidence=replace(self.proof, source_id='unmatched-source'))
        self.assertFalse(manual_day_ready(self.engine, book))

    def test_each_current_account_baseline_is_required_and_unique(self):
        book = self.advance()
        rows = self.engine.state.account_daily_baselines
        for index in range(len(rows)):
            with self.subTest(missing=index):
                self.persist(account_daily_baselines=tuple(row for position, row in enumerate(rows) if position != index))
                self.assertFalse(manual_day_ready(self.engine, book))
        self.persist(account_daily_baselines=(*rows, rows[0]))
        self.assertFalse(manual_day_ready(self.engine, book))
        self.persist(account_daily_baselines=tuple(replace(row, trade_date=row.trade_date - timedelta(days=1)) for row in rows))
        self.assertFalse(manual_day_ready(self.engine, book))

    def test_context_date_must_still_match_committed_baseline_day(self):
        book = self.advance()
        self.persist(trading_day=self.engine.calendar.advance(self.engine.state.trading_day, 1))
        self.assertFalse(manual_day_ready(self.engine, book))

    def test_release_removes_only_day_wait_and_never_resumes_or_grants(self):
        self.advance()
        stopped, automatic, manual_stopped = self.engine.state.stopped, self.engine.state.automatic, self.engine.state.manual_stopped
        self.persist(issues=('manual_day_baseline_required', 'account_daily_loss_limit'))
        self.release()
        self.assertEqual(self.engine.state.issues, ('account_daily_loss_limit',))
        self.assertEqual((self.engine.state.stopped, self.engine.state.automatic, self.engine.state.manual_stopped), (stopped, automatic, manual_stopped))
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertEqual(self.engine.state.automatic.daily.authorized_run, '')
        with self.assertRaises(DomainError) as caught:
            continue_daily_session(self.engine, ())
        self.assertEqual(caught.exception.code, 'daily_signal_not_authorized')

    def test_release_preserves_explicit_user_stop_and_each_unrelated_book_reason(self):
        self.advance()
        for reason in ('risk_rejected', 'outcome_unknown', 'manual_unprotected_position', 'manual_restarted'):
            with self.subTest(reason=reason):
                books = tuple(replace(book, halted=True, reasons=('manual_day_baseline_required', reason)) for book in self.engine.state.manual_books)
                self.persist(manual_books=books, manual_stopped=True, stopped=True, issues=('manual_day_baseline_required', reason))
                self.release()
                self.assertTrue(self.engine.state.manual_stopped)
                self.assertTrue(self.engine.state.stopped)
                self.assertEqual(self.engine.state.issues, (reason,))
                self.assertTrue(all(book.halted and book.reasons == (reason,) for book in self.engine.state.manual_books))

    def test_release_requires_ready_proof_and_does_not_clear_or_bump_state_without_it(self):
        self.advance(attest=False)
        self.persist(issues=('manual_day_baseline_required',))
        before = self.engine.state
        self.release()
        self.assertEqual(self.engine.state, before)

    def test_release_is_idempotent_and_no_book_cannot_clear_an_unattributed_issue(self):
        self.advance()
        self.release()
        before = self.engine.state
        self.release()
        self.assertEqual(self.engine.state, before)
        self.persist(manual_books=(), issues=('manual_day_baseline_required',))
        self.release()
        self.assertEqual(self.engine.state.issues, ('manual_day_baseline_required',))

    def test_shared_daily_loss_excludes_prior_history_without_resetting_cash_or_capital(self):
        book = self.advance(old_loss=D('-12000'))
        self.assertEqual(manual_net_pnl(self.engine, book), D('-12000'))
        self.assertEqual(manual_daily_pnl(self.engine, book), D('0'))
        self.assertEqual(manual_capacity(self.engine, book).settled_cash, book.capital - D('12000'))
        self.assertIn(self.fixture.signal_day, self.engine.state.daily_locks)
        self.assertNotIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.release()
        self.fixture.adopt(self.engine.clock.now())
        self.assertNotIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.assertEqual(book_for(self.engine, book.account_ref).capital, book.capital)
        self.assertEqual(manual_net_pnl(self.engine, book), D('-12000'))

    def test_pure_manual_lifetime_daily_loss_semantics_are_preserved(self):
        book = self.advance(old_loss=D('-12000'))
        self.persist(strategies=())
        self.assertEqual(manual_daily_pnl(self.engine, book), D('-12000'))
        self.fixture.adopt(self.engine.clock.now())
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)

    def test_shared_current_day_loss_still_latches_and_never_falls_back_to_old_history(self):
        book = self.advance()
        loss = PositionLot(
            'new-day-loss',
            book.account_ref,
            self.fixture.spec.instrument_id,
            book.book_id,
            1,
            manual_policy(),
            0,
            D('20'),
            self.engine.state.trading_day,
            0,
            realized_pnl=D('-12000'),
        )
        self.persist(positions=(*self.engine.state.positions, loss))
        self.fixture.adopt(self.engine.clock.now())
        self.assertEqual(manual_daily_pnl(self.engine, book), D('-12000'))
        self.assertIn(self.engine.state.trading_day, self.engine.state.daily_locks)

    def test_missing_shared_proof_does_not_latch_yesterdays_loss_again(self):
        book = self.advance(attest=False, old_loss=D('-12000'))
        self.assertFalse(manual_day_ready(self.engine, book))
        self.assertNotIn(self.engine.state.trading_day, self.engine.state.daily_locks)
        self.assertIn('manual_day_baseline_required', book_for(self.engine, book.account_ref).reasons)

    def test_existing_manual_resume_and_new_plan_accept_proved_day_without_reseeding(self):
        book = self.advance()
        self.release()
        case = self.fixture.case
        receipt = case.service.execute(case.command(UiAction.RESUME, manual_book=ManualBookForm(case.scope, book.capital, True)))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(book_for(self.engine, book.account_ref).opening_day, book.opening_day)
        form = self.fixture.base.direct_plan(self.engine.strategy(self.fixture.reference), stock=True)
        form = replace(form, strategy_id=book.book_id)
        request = ManualRequest(case.scope, 'day-plan', 'SUBMIT', 'fixture-hash', plan=form)
        self.assertEqual(assert_manual_plan(self.engine, request, form), book_for(self.engine, book.account_ref))

    def test_manual_resume_keeps_unknown_guard_after_day_release(self):
        book = self.advance()
        self.release()
        case = self.fixture.case
        request = ManualRequest(case.scope, 'unknown', 'SUBMIT', 'fixture-hash', outcome_known=False)
        self.persist(manual_requests=(*self.engine.state.manual_requests, request))
        receipt = case.service.execute(case.command(UiAction.RESUME, manual_book=ManualBookForm(case.scope, book.capital, True)))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'outcome_unknown')

    def test_resume_and_manual_plan_reject_revoked_day_evidence_after_release(self):
        book = self.advance()
        self.release()
        case = self.fixture.case
        resumed = case.service.execute(case.command(UiAction.RESUME, manual_book=ManualBookForm(case.scope, book.capital, True)))
        self.assertTrue(resumed.accepted, resumed)
        self.persist(automatic_daily_evidence=None)
        receipt = case.service.execute(case.command(UiAction.RESUME, manual_book=ManualBookForm(case.scope, book.capital, True)))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'manual_day_baseline_required')
        plan = replace(self.fixture.base.direct_plan(self.engine.strategy(self.fixture.reference), stock=True), strategy_id=book.book_id)
        request = ManualRequest(case.scope, 'bad-day-plan', 'SUBMIT', 'fixture-hash', plan=plan)
        with self.assertRaises(DomainError) as caught:
            assert_manual_plan(self.engine, request, plan)
        self.assertEqual(caught.exception.code, 'manual_day_baseline_required')

    def test_verified_closed_stock_does_not_erase_fresh_other_market_scopes_at_future_close(self):
        self.open_daily_stock()
        fixture = self.fixture
        day = self.engine.state.trading_day
        close = fixture.session(day=day).closes_at
        fixture.quote(fixture.spec, close - timedelta(seconds=1), D('20'))
        fixture.adopt(fixture.clock.now())
        fixture.clock.value = close
        observe_daily(self.engine, fixture.minutes(day=day, price=D('20')))
        fixture.adopt(close + timedelta(seconds=1))
        observe_daily(self.engine, ())
        self.assertTrue(any(row.account_ref == fixture.account_ref and row.trade_date == day for row in self.engine.state.daily_account_closes))
        future = next(spec for spec in self.engine.catalog.instruments if spec.market is Market.INDEX_FUTURE)
        future_close = fixture.session(day=day, spec=future).closes_at
        fixture.quote(future, future_close - timedelta(seconds=1), D('25000'))
        before = fixture.placed()
        grant = self.engine.state.automatic.daily.authorized_run
        fixture.adopt(fixture.clock.now())
        self.assertEqual(set(self.engine.manual_observations), set(self.engine.gateways))
        self.assertEqual(set(self.engine.manual_protective_observations), set(self.engine.gateways))
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(self.engine.state.automatic.daily.authorized_run, grant)
        self.assertNotIn('stale_quote', book_for(self.engine, fixture.account_ref).reasons)
        with self.assertRaises(DomainError) as caught:
            manual_daily_pnl(self.engine, book_for(self.engine, fixture.account_ref))
        self.assertEqual(caught.exception.code, 'stale_quote')

    def test_open_market_unknown_mark_halts_without_erasing_reconciled_quantity_scopes(self):
        self.open_daily_stock()
        fixture = self.fixture
        fixture.clock.value += timedelta(seconds=31)
        before = fixture.placed()
        fixture.adopt(fixture.clock.now())
        self.assertTrue(self.engine.state.stopped)
        self.assertIn('stale_quote', book_for(self.engine, fixture.account_ref).reasons)
        self.assertEqual(set(self.engine.manual_observations), set(self.engine.gateways))
        self.assertEqual(set(self.engine.manual_protective_observations), set(self.engine.gateways))
        self.assertEqual(fixture.placed(), before)

    def test_pure_manual_stale_valuation_retains_legacy_exception_and_halt_semantics(self):
        case = legacy.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        case.confirm_test()
        form, _ = case.normal('legacy-valuation')
        receipt = case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        case.native.fill(case.native.trades[-1], 1, D('25000'))
        case.observe()
        case.clock.value += timedelta(seconds=31)
        with self.assertRaises(DomainError) as caught:
            case.observe()
        self.assertEqual(caught.exception.code, 'stale_quote')
        self.assertEqual(case.engine.manual_observations, {})

    def test_unknown_account_mark_cannot_be_replaced_with_zero_in_aggregate_loss(self):
        self.open_daily_stock()
        engine, fixture = self.engine, self.fixture
        future = next(book for book in engine.state.manual_books if book.account_ref != fixture.account_ref)
        spec = next(spec for spec in engine.catalog.instruments if spec.market is Market.INDEX_FUTURE)
        recorded = PositionLot(
            'recorded-current-loss',
            future.account_ref,
            spec.instrument_id,
            future.book_id,
            1,
            manual_policy(),
            0,
            D('25000'),
            engine.state.trading_day,
            0,
            realized_pnl=-engine.risk().policy.total_budget,
        )
        self.persist(positions=(*engine.state.positions, recorded))
        fixture.clock.value += timedelta(seconds=31)
        fixture.adopt(fixture.clock.now())
        self.assertIn('stale_quote', book_for(engine, fixture.account_ref).reasons)
        self.assertNotIn(engine.state.trading_day, engine.state.daily_locks)
        self.assertEqual(manual_daily_pnl(engine, future), recorded.realized_pnl)
        self.assertEqual(set(engine.manual_protective_observations), set(engine.gateways))

    def test_revoked_attestation_never_falls_back_to_current_baseline_rows_alone(self):
        book = self.advance()
        self.persist(automatic_daily_evidence=None)
        with self.assertRaises(DomainError) as caught:
            manual_daily_pnl(self.engine, book)
        self.assertEqual(caught.exception.code, 'manual_day_baseline_required')


class AccountWaitingRiskTests(unittest.TestCase):
    """Explicit per-account ledger inputs; this monitor never queries a port."""

    def setUp(self):
        self.stock, self.future = market_fixtures.instrument(), market_fixtures.instrument(Market.INDEX_FUTURE)
        self.calendar = synthetic_calendar()
        day = market_fixtures.NOW.date()
        close = self.calendar.day_session(day).closes_at
        self.now = close.replace(hour=13, minute=44, second=59)
        stock = PositionLot('stock-lot', 'a-stock', self.stock.instrument_id, 'owner', 1, manual_policy(), 1000, D('20'), day, 0)
        future_loss = PositionLot(
            'future-history', 'z-future', self.future.instrument_id, 'manual-future', 1, manual_policy(), 0, D('25000'), day, 0, realized_pnl=D('-1500')
        )
        state = replace(
            AppState(),
            trading_day=day,
            environment=Environment.BROKER_SIMULATION,
            positions=(stock, future_loss),
            account_risk_limits=(AccountRiskLimits('a-stock'), AccountRiskLimits('z-future')),
            account_daily_baselines=(AccountDailyBaseline('a-stock', day, D('0'), 'verified'), AccountDailyBaseline('z-future', day, D('0'), 'verified')),
            manual_books=(ManualBook('manual-stock', 'a-stock', D('60000'), day), ManualBook('manual-future', 'z-future', D('40000'), day)),
            automatic=AutomaticState(auto_paused=False, daily=DailyState(authorized_run='run', owner_stamp='owner', waiting_session=True)),
            stopped=False,
        )
        self.engine = SimpleNamespace(
            state=state,
            clock=SimpleNamespace(now=lambda: self.now),
            calendar=self.calendar,
            catalog=Catalog((self.stock, self.future)),
            fees=FeeSchedule(),
            configuration=SimpleNamespace(stock_account_ref='a-stock', futures_account_ref='z-future'),
            quotes={
                self.stock.instrument_id: Quote(
                    self.stock.instrument_id, D('20'), D('20'), D('20'), close - timedelta(seconds=1), close - timedelta(seconds=1), day
                )
            },
        )
        self.engine._persist = lambda kind, state: setattr(self.engine, 'state', state)

    def test_closed_stock_defer_does_not_hide_later_sorted_open_future_loss(self):
        self.assertTrue(account_markets_closed(self.engine, 'a-stock'))
        observe_account_limits(self.engine)
        self.assertNotIn('stale_quote', self.engine.state.issues)
        self.assertIn(('z-future', self.engine.state.trading_day), self.engine.state.account_daily_locks)
        self.assertIn('account_daily_loss_limit', self.engine.state.issues)

    def test_background_stale_open_market_is_not_a_normal_calendar_wait(self):
        self.now = self.now.replace(hour=13, minute=0)
        quote = self.engine.quotes[self.stock.instrument_id]
        self.engine.quotes[self.stock.instrument_id] = replace(quote, source_at=self.now - timedelta(seconds=31), received_at=self.now - timedelta(seconds=31))
        self.assertFalse(account_markets_closed(self.engine, 'a-stock'))
        observe_account_limits(self.engine)
        self.assertIn('stale_quote', self.engine.state.issues)

    def test_closed_market_without_preserved_run_must_not_silently_defer_fault(self):
        state = self.engine.state
        self.engine.state = replace(state, automatic=replace(state.automatic, daily=replace(state.automatic.daily, authorized_run='')))
        observe_account_limits(self.engine)
        self.assertIn('stale_quote', self.engine.state.issues)

    def test_only_stale_quote_is_calendar_deferred_not_unexpected_valuation_error(self):
        original = account_net_mark

        def failed(engine, ref):
            if ref == 'a-stock':
                raise DomainError('risk_rejected')
            return original(engine, ref)

        with patch('quantlab.trading.application.account_risk.account_net_mark', failed):
            observe_account_limits(self.engine)
        self.assertIn('risk_rejected', self.engine.state.issues)

    def test_market_closure_requires_target_account_positions_and_calendar_coverage(self):
        self.assertFalse(account_markets_closed(self.engine, 'z-future'))
        self.assertTrue(account_markets_closed(self.engine, 'a-stock'))
        original = self.engine.calendar
        self.engine.calendar = replace(original, sessions=tuple(row for row in original.sessions if row.trade_date != self.engine.state.trading_day))
        self.assertFalse(account_markets_closed(self.engine, 'a-stock'))

    def test_verified_open_is_inclusive_close_exclusive_and_every_contract_must_be_closed(self):
        day = self.engine.state.trading_day
        self.now = self.calendar.day_session(day).opens_at
        self.assertFalse(account_markets_closed(self.engine, 'a-stock'))
        self.now = self.calendar.day_session(day).closes_at
        self.assertTrue(account_markets_closed(self.engine, 'a-stock'))
        front = self.future
        successor = replace(front, instrument_id='TAIFEX:TMF:202612', delivery_month='202612', expiry=front.expiry + timedelta(days=28))
        self.engine.catalog = Catalog((self.stock, front, successor))
        self.engine.state = replace(
            self.engine.state,
            trading_day=front.expiry,
            positions=tuple(
                PositionLot(spec.instrument_id, 'z-future', spec.instrument_id, 'owner', 1, manual_policy(), 1, D('25000'), front.expiry, 1)
                for spec in (front, successor)
            ),
        )
        session = self.calendar.day_session(front.expiry)
        self.now = session.opens_at.replace(hour=13, minute=35)
        self.assertFalse(account_markets_closed(self.engine, 'z-future'))
        self.now = self.now.replace(minute=45)
        self.assertTrue(account_markets_closed(self.engine, 'z-future'))


if __name__ == '__main__':
    unittest.main()
