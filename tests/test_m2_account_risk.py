"""pure and application account admission acceptance tests."""

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace
import unittest

from test_trading_adapters import NOW, account, instrument, plan
from quantlab.trading.application.contracts import SettingsForm
from quantlab.trading.application.manual_book import ManualBook
from quantlab.trading.application.state import AppState, LocalOrder
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import HoldingPolicy, Market, OrderStatus, PositionLot, Quote, Reservation, Side
from quantlab.trading.domain.validation import DomainError

from quantlab.trading.domain.risk import AccountDailyBaseline, AccountRiskLimits, check_account_entry
from quantlab.trading.application.account_risk import (
    account_entry_rejection,
    account_net_mark,
    account_position_count,
    account_position_scopes,
    assert_account_resume,
    m2_account_refs,
    observe_account_limits,
)

D = Decimal


@dataclass(frozen=True)
class DraftRiskState(AppState):
    account_daily_locks: tuple = ()
    account_risk_limits: tuple = ()
    account_daily_baselines: tuple = ()


def lot(reference='lot', *, account_ref='test-stock', quantity=1000, instrument_id='TWSE:0050', strategy_id='strategy', realized_pnl=D('0')):
    return PositionLot(
        reference, account_ref, instrument_id, strategy_id, 1, HoldingPolicy(), quantity, D('20'), NOW.date(), quantity, realized_pnl=realized_pnl
    )


def order(
    reference='order', *, account_ref='test-stock', instrument_id='TWSE:0050', status=OrderStatus.ACCEPTED, side=Side.BUY, reduce_only=False, costs=D('0')
):
    intent = replace(plan(instrument()), account_ref=account_ref, instrument_id=instrument_id, reduce_only=reduce_only, side=side)
    reserved = Reservation(reference, account_ref, instrument_id, 'group', D('0'), D('0'), 1000, OrderStatus.RESERVED)
    return LocalOrder(reference, reference, reference, intent, HoldingPolicy(), reserved, status, costs=costs)


def engine_fixture(*, positions=(), orders=(), baselines=None, limits=(), locks=(), strategies=None):
    spec = instrument()
    state = DraftRiskState(
        positions=positions,
        orders=orders,
        trading_day=NOW.date(),
        account_daily_locks=locks,
        account_risk_limits=limits,
        account_daily_baselines=(AccountDailyBaseline('test-stock', NOW.date(), D('0'), 'VERIFIED_CLOSE'),) if baselines is None else baselines,
        strategies=(SimpleNamespace(form=SimpleNamespace(account_ref='test-stock'), parameters=object(), state='ACTIVE'),)
        if strategies is None
        else strategies,
        settings=SettingsForm(D('100000'), D('0'), D('.02')),
        stopped=False,
    )
    engine = SimpleNamespace(
        state=state,
        clock=SimpleNamespace(now=lambda: NOW),
        catalog=SimpleNamespace(resolve=lambda reference: spec),
        account=lambda reference: account(),
        configuration=SimpleNamespace(stock_account_ref='test-stock', futures_account_ref='other-account'),
        fees=FeeSchedule(),
        quotes={spec.instrument_id: Quote(spec.instrument_id, D('19'), D('20'), D('19.5'), NOW, NOW, NOW.date())},
        persisted=[],
    )
    engine._persist = lambda kind, proposed: (setattr(engine, 'state', proposed), engine.persisted.append(kind))
    return engine


class M2AccountRiskTests(unittest.TestCase):
    def test_default_account_limits(self):
        limits = AccountRiskLimits('test-stock')
        self.assertEqual((limits.daily_loss_fraction, limits.max_order_notional, limits.max_positions), (D('.03'), D('1000000'), 5))

    def test_limit_inputs_validate_at_boundary(self):
        for changes in (
            {'account_ref': ''},
            {'daily_loss_fraction': D('0')},
            {'daily_loss_fraction': D('1.01')},
            {'max_order_notional': D('0')},
            {'max_positions': 0},
            {'max_positions': True},
        ):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(AccountRiskLimits('test-stock'), **changes)

    def test_account_baseline_inputs_validate_at_boundary(self):
        baseline = AccountDailyBaseline('test-stock', NOW.date(), D('0'), 'VERIFIED_CLOSE')
        for changes in ({'account_ref': ''}, {'trade_date': NOW}, {'previous_close_pnl': D('NaN')}, {'source_id': ''}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(baseline, **changes)

    def test_loss_limit_uses_account_allocated_capital_and_triggers_at_equality(self):
        limits = AccountRiskLimits('test-stock')
        self.assertEqual(check_account_entry(limits, D('40000'), D('-1200'), D('100'), 0, True), 'account_daily_loss_limit')
        self.assertEqual(check_account_entry(limits, D('40000'), D('-1199.99'), D('100'), 0, True), '')

    def test_order_notional_cap_allows_exact_limit_and_rejects_above(self):
        limits = AccountRiskLimits('test-stock', max_order_notional=D('20000'))
        self.assertEqual(check_account_entry(limits, D('100000'), D('0'), D('20000'), 0, True), '')
        self.assertEqual(check_account_entry(limits, D('100000'), D('0'), D('20000.01'), 0, True), 'account_order_limit')

    def test_position_cap_reserves_new_slot_at_equality(self):
        limits = AccountRiskLimits('test-stock', max_positions=2)
        self.assertEqual(check_account_entry(limits, D('100000'), D('0'), D('100'), 1, True), '')
        self.assertEqual(check_account_entry(limits, D('100000'), D('0'), D('100'), 2, True), 'account_position_limit')
        self.assertEqual(check_account_entry(limits, D('100000'), D('0'), D('100'), 2, False), '')

    def test_reductions_remain_legal_under_each_limit(self):
        limits = AccountRiskLimits('test-stock', max_order_notional=D('100'), max_positions=1)
        for pnl, notional, count in ((D('-3000'), D('1'), 0), (D('0'), D('101'), 0), (D('0'), D('1'), 1)):
            with self.subTest(pnl=pnl, notional=notional, count=count):
                self.assertNotEqual(check_account_entry(limits, D('100000'), pnl, notional, count, True), '')
                self.assertEqual(check_account_entry(limits, D('100000'), pnl, notional, count, True, reduce_only=True), '')

    def test_decimal_context_does_not_move_loss_boundary(self):
        limits = AccountRiskLimits('test-stock')
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(check_account_entry(limits, D('12345'), D('-370.34'), D('1'), 0, True), '')
            self.assertEqual(check_account_entry(limits, D('12345'), D('-370.35'), D('1'), 0, True), 'account_daily_loss_limit')

    def test_account_mark_includes_manual_retired_and_closed_realized_lots_and_entry_costs(self):
        engine = engine_fixture(
            positions=(
                lot('open', realized_pnl=D('500')),
                lot('manual', quantity=0, strategy_id='manual-sim-book', realized_pnl=D('-200')),
                lot('other', account_ref='other-account', quantity=0, realized_pnl=D('9999')),
            ),
            orders=(
                order('entry', costs=D('29')),
                order('manual-entry', costs=D('20')),
                order('exit', reduce_only=True, costs=D('999')),
                order('other-entry', account_ref='other-account', costs=D('777')),
            ),
        )
        # Executable bid loss -1000; exit fee/tax85 + slippage10; realized300;
        # actual entry costs49. Exit order fees are already in realized PnL.
        self.assertEqual(account_net_mark(engine, 'test-stock'), D('-844'))

    def test_unknown_open_position_mark_does_not_become_zero(self):
        engine = engine_fixture(positions=(lot(),))
        engine.quotes.clear()
        with self.assertRaises(DomainError) as rejected:
            account_net_mark(engine, 'test-stock')
        self.assertEqual(rejected.exception.code, 'stale_quote')

    def test_position_slots_include_every_owner_and_active_entry_but_not_exits_or_terminal_orders(self):
        engine = engine_fixture(
            positions=(
                lot('manual', strategy_id='manual-sim-book'),
                lot('retired', instrument_id='TWSE:2330', strategy_id='retired'),
                lot('closed', quantity=0, instrument_id='TWSE:2308'),
                lot('other', account_ref='other-account', instrument_id='TWSE:2412'),
            ),
            orders=(
                order('same-scope'),
                order('pending', instrument_id='TWSE:2303'),
                order('unknown', instrument_id='TWSE:2317', status=OrderStatus.UNKNOWN),
                order('cancelling', instrument_id='TWSE:2881', status=OrderStatus.CANCEL_PENDING),
                order('exit', instrument_id='TWSE:2882', reduce_only=True),
                order('terminal', instrument_id='TWSE:2891', status=OrderStatus.CANCELED),
                order('other-entry', account_ref='other-account', instrument_id='TWSE:2892'),
            ),
        )
        self.assertEqual(account_position_count(engine, 'test-stock'), 5)
        self.assertNotIn(('TWSE:2882', Side.BUY), account_position_scopes(engine, 'test-stock'))

    def test_missing_or_wrong_day_account_baseline_blocks_entries(self):
        for baselines in (
            (),
            (AccountDailyBaseline('other-account', NOW.date(), D('0'), 'VERIFIED_CLOSE'),),
            (AccountDailyBaseline('test-stock', NOW.date() - timedelta(days=1), D('0'), 'VERIFIED_CLOSE'),),
        ):
            with self.subTest(baselines=baselines):
                self.assertEqual(account_entry_rejection(engine_fixture(baselines=baselines), plan(instrument())), 'account_daily_baseline_required')

    def test_loss_latch_survives_pnl_recovery_and_account_isolation(self):
        engine = engine_fixture(locks=(('test-stock', NOW.date()),))
        self.assertEqual(account_entry_rejection(engine, plan(instrument())), 'account_daily_loss_limit')
        engine.state = replace(engine.state, account_daily_locks=(('other-account', NOW.date()), ('test-stock', NOW.date() - timedelta(days=1))))
        self.assertEqual(account_entry_rejection(engine, plan(instrument())), '')

    def test_daily_pnl_subtracts_attested_close_instead_of_restarting_from_zero(self):
        baseline = AccountDailyBaseline('test-stock', NOW.date(), D('3000'), 'VERIFIED_CLOSE')
        self.assertEqual(account_entry_rejection(engine_fixture(baselines=(baseline,)), plan(instrument())), 'account_daily_loss_limit')

    def test_account_specific_notional_limit_is_used(self):
        limits = (AccountRiskLimits('other-account', max_order_notional=D('100000')), AccountRiskLimits('test-stock', max_order_notional=D('19999')))
        self.assertEqual(account_entry_rejection(engine_fixture(limits=limits), plan(instrument())), 'account_order_limit')

    def test_futures_notional_includes_contract_multiplier(self):
        engine = engine_fixture(limits=(AccountRiskLimits('test-stock', max_order_notional=D('999')),))
        spec = instrument(Market.INDEX_FUTURE)
        engine.catalog.resolve = lambda reference: spec
        self.assertEqual(account_entry_rejection(engine, plan(spec)), 'account_order_limit')

    def test_pending_manual_position_occupies_slot_before_automatic_entry(self):
        engine = engine_fixture(orders=(order('manual-entry', instrument_id='TWSE:2330'),), limits=(AccountRiskLimits('test-stock', max_positions=1),))
        self.assertEqual(account_entry_rejection(engine, plan(instrument())), 'account_position_limit')

    def test_application_reduction_needs_neither_baseline_nor_account_valuation(self):
        engine = SimpleNamespace()  # No mark or baseline exists; reduction guard is first.
        self.assertEqual(account_entry_rejection(engine, replace(plan(instrument()), reduce_only=True)), '')

    def test_explicit_virtual_capacity_skips_unsupported_account_query(self):
        engine = engine_fixture()
        engine.account = lambda reference: self.fail('virtual simulation capacity must not query broker account')
        # PnL-300 reaches 3% of explicit10000 but not default100000.
        engine.state = replace(engine.state, account_daily_baselines=(AccountDailyBaseline('test-stock', NOW.date(), D('300'), 'VERIFIED_CLOSE'),))
        self.assertEqual(account_entry_rejection(engine, plan(instrument()), allocated_cash=D('10000')), 'account_daily_loss_limit')

    def test_unadopted_account_keeps_legacy_manual_admission(self):
        engine = engine_fixture(strategies=(), baselines=())
        self.assertEqual(m2_account_refs(engine), frozenset())
        self.assertEqual(account_entry_rejection(engine, plan(instrument())), '')

    def test_adoption_survives_deleted_strategy_for_legacy_and_manual_entries(self):
        adopted = SimpleNamespace(form=SimpleNamespace(account_ref='test-stock'), parameters=object(), state='DELETED')
        legacy = SimpleNamespace(form=SimpleNamespace(account_ref='other-account'), parameters=None, state='ACTIVE')
        engine = engine_fixture(strategies=(adopted, legacy), limits=(AccountRiskLimits('test-stock', max_order_notional=D('19999')),))
        self.assertEqual(m2_account_refs(engine), frozenset(('test-stock',)))
        for strategy_id in ('legacy-strategy', 'manual-sim-book'):
            self.assertEqual(account_entry_rejection(engine, replace(plan(instrument()), strategy_id=strategy_id)), 'account_order_limit')

    def test_other_instrument_unverified_or_receive_stale_marks_block_account_valuation(self):
        for changes in (
            {'quality': 'UNVERIFIED'},
            {'source_at': NOW - timedelta(seconds=31), 'received_at': NOW - timedelta(seconds=31)},
            {'received_at': NOW + timedelta(seconds=1)},
        ):
            with self.subTest(changes=changes):
                engine = engine_fixture(positions=(lot(instrument_id='TWSE:2330'),))
                original = engine.quotes['TWSE:0050']
                engine.quotes['TWSE:2330'] = replace(original, instrument_id='TWSE:2330', **changes)
                with self.assertRaises(DomainError) as rejected:
                    account_entry_rejection(engine, plan(instrument()))
                self.assertEqual(rejected.exception.code, 'stale_quote')

    def test_observer_latches_loss_without_signal_or_order_and_is_idempotent(self):
        baseline = AccountDailyBaseline('test-stock', NOW.date(), D('3000'), 'VERIFIED_CLOSE')
        engine = engine_fixture(baselines=(baseline,))
        engine.account = lambda reference: self.fail('monitor must use configured capital')
        observe_account_limits(engine)
        self.assertTrue(engine.state.stopped)
        self.assertIn('account_daily_loss_limit', engine.state.issues)
        self.assertIn(('test-stock', NOW.date()), engine.state.account_daily_locks)
        self.assertEqual(engine.state.account_daily_baselines, (baseline,))
        self.assertEqual(engine.persisted, ['account_risk_observed'])
        self.assertFalse(engine.state.orders)
        observe_account_limits(engine)
        self.assertEqual(engine.persisted, ['account_risk_observed'])

    def test_observer_keeps_loss_latched_after_recovery_and_preserves_older_account_locks(self):
        previous = ('other-account', NOW.date() - timedelta(days=1))
        engine = engine_fixture(locks=(previous, ('test-stock', NOW.date())))
        observe_account_limits(engine)
        self.assertTrue(engine.state.stopped)
        self.assertEqual(set(engine.state.account_daily_locks), {previous, ('test-stock', NOW.date())})
        self.assertIn('account_daily_loss_limit', engine.state.issues)

    def test_observer_marks_missing_baseline_pending_without_inventing_baseline_or_loss_lock(self):
        engine = engine_fixture(baselines=())
        observe_account_limits(engine)
        self.assertTrue(engine.state.stopped)
        self.assertIn('account_daily_baseline_required', engine.state.issues)
        self.assertFalse(engine.state.account_daily_baselines)
        self.assertFalse(engine.state.account_daily_locks)

    def test_observer_ignores_unadopted_accounts_and_preserves_healthy_state(self):
        for engine in (engine_fixture(strategies=(), baselines=()), engine_fixture()):
            with self.subTest(engine=engine):
                before = engine.state
                observe_account_limits(engine)
                self.assertIs(engine.state, before)
                self.assertFalse(engine.persisted)

    def test_observer_uses_confirmed_manual_book_capacity_in_shared_sim(self):
        engine = engine_fixture(baselines=(AccountDailyBaseline('test-stock', NOW.date(), D('300'), 'VERIFIED_CLOSE'),))
        engine.state = replace(engine.state, manual_books=(ManualBook('manual-sim-book', 'test-stock', D('10000'), NOW.date()),))
        observe_account_limits(engine)
        self.assertIn(('test-stock', NOW.date()), engine.state.account_daily_locks)

    def test_observer_uses_futures_allocation_for_other_account(self):
        strategy = SimpleNamespace(form=SimpleNamespace(account_ref='other-account'), parameters=object(), state='RETIRED')
        engine = engine_fixture(strategies=(strategy,), baselines=(AccountDailyBaseline('other-account', NOW.date(), D('600'), 'VERIFIED_CLOSE'),))
        engine.state = replace(engine.state, settings=SettingsForm(D('100000'), D('20000'), D('.02')))
        observe_account_limits(engine)
        self.assertIn(('other-account', NOW.date()), engine.state.account_daily_locks)

    def test_another_accounts_manual_capital_cannot_inflate_loss_threshold(self):
        baseline = AccountDailyBaseline('test-stock', NOW.date(), D('300'), 'VERIFIED_CLOSE')
        engine = engine_fixture(baselines=(baseline,))
        engine.state = replace(
            engine.state,
            settings=SettingsForm(D('10000'), D('100000'), D('.02')),
            manual_books=(ManualBook('manual-sim-other', 'other-account', D('100000'), NOW.date()),),
        )
        observe_account_limits(engine)
        self.assertIn(('test-stock', NOW.date()), engine.state.account_daily_locks)

    def test_loss_observation_preserves_existing_unrelated_issue(self):
        engine = engine_fixture(baselines=(AccountDailyBaseline('test-stock', NOW.date(), D('3000'), 'VERIFIED_CLOSE'),))
        engine.state = replace(engine.state, issues=('outcome_unknown',))
        observe_account_limits(engine)
        self.assertEqual(set(engine.state.issues), {'outcome_unknown', 'account_daily_loss_limit'})

    def test_unknown_mark_stops_account_without_hiding_another_accounts_loss_latch(self):
        other = SimpleNamespace(form=SimpleNamespace(account_ref='other-account'), parameters=object(), state='ACTIVE')
        baseline = AccountDailyBaseline('test-stock', NOW.date(), D('3000'), 'VERIFIED_CLOSE')
        other_baseline = AccountDailyBaseline('other-account', NOW.date(), D('0'), 'VERIFIED_CLOSE')
        engine = engine_fixture(positions=(lot('other-lot', account_ref='other-account'),), baselines=(baseline, other_baseline))
        engine.state = replace(engine.state, strategies=(*engine.state.strategies, other))
        engine.quotes.clear()
        observe_account_limits(engine)
        self.assertTrue(engine.state.stopped)
        self.assertIn('stale_quote', engine.state.issues)
        self.assertIn(('test-stock', NOW.date()), engine.state.account_daily_locks)
        self.assertNotIn(('other-account', NOW.date()), engine.state.account_daily_locks)

    def test_scoped_and_global_resume_cannot_clear_today_loss_lock(self):
        for scope in ('test-stock', ''):
            with self.subTest(scope=scope):
                engine = engine_fixture(locks=(('test-stock', NOW.date()),))
                with self.assertRaises(DomainError) as rejected:
                    assert_account_resume(engine, scope)
                self.assertEqual(rejected.exception.code, 'account_daily_loss_limit')
                self.assertIn(('test-stock', NOW.date()), engine.state.account_daily_locks)

    def test_resume_observes_fresh_loss_even_before_monitor_tick(self):
        engine = engine_fixture(baselines=(AccountDailyBaseline('test-stock', NOW.date(), D('3000'), 'VERIFIED_CLOSE'),))
        with self.assertRaises(DomainError) as rejected:
            assert_account_resume(engine)
        self.assertEqual(rejected.exception.code, 'account_daily_loss_limit')
        self.assertIn(('test-stock', NOW.date()), engine.state.account_daily_locks)

    def test_resume_requires_current_account_baseline(self):
        engine = engine_fixture(baselines=())
        with self.assertRaises(DomainError) as rejected:
            assert_account_resume(engine, 'test-stock')
        self.assertEqual(rejected.exception.code, 'account_daily_baseline_required')
        self.assertFalse(engine.state.account_daily_baselines)

    def test_scoped_resume_does_not_confuse_another_account_latch_or_prior_day(self):
        engine = engine_fixture(locks=(('other-account', NOW.date()), ('test-stock', NOW.date() - timedelta(days=1))))
        assert_account_resume(engine, 'test-stock')
        self.assertEqual(len(engine.state.account_daily_locks), 2)

    def test_scoped_resume_assertion_selects_requested_adopted_account(self):
        other = SimpleNamespace(form=SimpleNamespace(account_ref='other-account'), parameters=object(), state='DELETED')
        engine = engine_fixture(locks=(('other-account', NOW.date()),))
        engine.state = replace(
            engine.state,
            strategies=(*engine.state.strategies, other),
            account_daily_baselines=(*engine.state.account_daily_baselines, AccountDailyBaseline('other-account', NOW.date(), D('0'), 'VERIFIED_CLOSE')),
        )
        assert_account_resume(engine, 'test-stock')
        with self.assertRaises(DomainError) as rejected:
            assert_account_resume(engine)
        self.assertEqual(rejected.exception.code, 'account_daily_loss_limit')

    def test_baseline_for_other_account_does_not_satisfy_monitor(self):
        engine = engine_fixture(baselines=(AccountDailyBaseline('other-account', NOW.date(), D('0'), 'VERIFIED_CLOSE'),))
        observe_account_limits(engine)
        self.assertIn('account_daily_baseline_required', engine.state.issues)


if __name__ == '__main__':
    unittest.main()
