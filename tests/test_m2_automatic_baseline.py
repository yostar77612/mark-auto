"""Existing close-evidence format at the shared SIM provider boundary."""

from dataclasses import replace
from decimal import Decimal as D
from unittest.mock import Mock
import unittest

from test_m2_account_baselines import baseline_engine
from test_m2_account_risk import lot
from quantlab.trading.application.automatic_baseline import confirm_automatic_baseline
from quantlab.trading.application.manual_book import ManualBook
from quantlab.trading.application.sessions import DailyBaselineEvidence, fee_fingerprint
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.risk import AccountDailyBaseline
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation

SOURCE = 'VERIFIED_AUTOMATIC_CLOSE_FIXTURE'


class AutomaticBaselineTests(unittest.TestCase):
    def setUp(self):
        self.engine = baseline_engine(('account-a', 'account-b'))
        engine = self.engine
        engine._persist(
            'confirmed_virtual_books_fixture',
            replace(
                engine.state,
                reconciled=True,
                manual_books=tuple(ManualBook('manual-' + ref, ref, D('10000'), engine.state.trading_day) for ref in engine.gateways),
            ),
        )
        engine.manual_observations = {
            ref: ManualAccountObservation(ref, Environment.BROKER_SIMULATION, (), (), (), engine.clock.now()) for ref in engine.gateways
        }
        engine.automatic_observation_validator = Mock()
        for gateway in engine.gateways.values():
            gateway.snapshot = Mock(side_effect=AssertionError('financial snapshot prohibited'))
            gateway.refresh = Mock(side_effect=AssertionError('financial refresh prohibited'))
            gateway.events = Mock(side_effect=AssertionError('financial event query prohibited'))

    def proof(self, values=(D('-100'), D('100'))):
        engine = self.engine
        calendar = automatic_day_calendar(engine.calendar, engine.catalog.instruments)
        day = engine.clock.now().date()
        previous = calendar.days[calendar.index(day) - 1]
        return DailyBaselineEvidence(
            Environment.BROKER_SIMULATION,
            tuple(sorted(engine.gateways)),
            previous,
            day,
            calendar.calendar_id,
            calendar.version,
            engine.fees.version,
            fee_fingerprint(engine.fees),
            sum(values),
            calendar.day_session(previous).closes_at,
            SOURCE,
            account_previous_close=tuple(zip(sorted(engine.gateways), values)),
        )

    def confirm(self, proof=None, sources=frozenset((SOURCE,))):
        confirm_automatic_baseline(self.engine, proof or self.proof(), trusted_sources=sources)

    def test_exact_close_attribution_persists_evidence_without_financial_queries_or_resume(self):
        engine = self.engine
        self.confirm()
        self.assertEqual(tuple(row.previous_close_pnl for row in engine.state.account_daily_baselines), (D('-100'), D('100')))
        self.assertEqual(engine.state.automatic_daily_evidence, self.proof())
        self.assertTrue(engine.state.stopped)
        self.assertTrue(engine.state.automatic.auto_paused)
        self.assertIn('reconciled_waiting_resume', engine.state.automatic.reasons)
        self.assertTrue(engine.state.daily_baseline_required)
        self.assertEqual(engine.automatic_observation_validator.call_count, 2)

    def test_aggregate_multi_account_total_cannot_invent_a_split(self):
        with self.assertRaises(DomainError) as raised:
            self.confirm(replace(self.proof(), account_previous_close=()))
        self.assertEqual(raised.exception.code, 'account_daily_baseline_required')
        self.assertEqual(self.engine.state.account_daily_baselines, ())

    def test_trusted_source_grant_remains_required(self):
        with self.assertRaises(DomainError) as raised:
            self.confirm(sources=frozenset())
        self.assertEqual(raised.exception.code, 'daily_baseline_required')

    def test_stale_or_unknown_current_observation_cannot_attest(self):
        self.engine.automatic_observation_validator.side_effect = DomainError('state_conflict')
        with self.assertRaises(DomainError) as raised:
            self.confirm()
        self.assertEqual(raised.exception.code, 'state_conflict')
        self.assertIsNone(self.engine.state.automatic_daily_evidence)

    def test_existing_same_day_closing_values_cannot_be_reset(self):
        self.confirm()
        version = self.engine.state.version
        with self.assertRaises(DomainError) as raised:
            self.confirm(self.proof((D('0'), D('0'))))
        self.assertEqual(raised.exception.code, 'state_conflict')
        self.assertEqual(self.engine.state.version, version)

    def test_unknown_current_position_value_cannot_attest_a_close(self):
        engine = self.engine
        engine._persist('unpriced_position_fixture', replace(engine.state, positions=(lot(account_ref='account-a'),)))
        with self.assertRaises(DomainError) as raised:
            self.confirm()
        self.assertEqual(raised.exception.code, 'stale_quote')
        self.assertEqual(engine.state.account_daily_baselines, ())

    def test_local_cannot_use_the_broker_provider_boundary(self):
        proof = self.proof()
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LOCAL)
        with self.assertRaises(DomainError) as raised:
            self.confirm(proof)
        self.assertEqual(raised.exception.code, 'capability_missing')

    def test_same_day_identical_attestation_keeps_loss_latches_and_unrelated_issues(self):
        engine = self.engine
        lock = ('account-a', engine.state.trading_day)
        engine._persist('loss_latched_fixture', replace(engine.state, account_daily_locks=(lock,), issues=('account_daily_baseline_required', 'risk_rejected')))
        self.confirm()
        self.assertEqual(engine.state.account_daily_locks, (lock,))
        self.assertEqual(engine.state.issues, ('risk_rejected',))
        self.confirm()
        self.assertEqual(engine.state.account_daily_locks, (lock,))

    def test_only_confirmed_sim_books_use_this_boundary(self):
        engine = self.engine
        proof = self.proof()
        engine._persist('missing_book_fixture', replace(engine.state, manual_books=()))
        with self.assertRaises(DomainError) as raised:
            self.confirm(proof)
        self.assertEqual(raised.exception.code, 'capability_missing')

    def test_live_rejects_before_any_scope_or_financial_operation(self):
        proof = self.proof()
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE)
        with self.assertRaises(DomainError) as raised:
            self.confirm(proof)
        self.assertEqual(raised.exception.code, 'production_orders_disabled')
        self.engine.automatic_observation_validator.assert_not_called()

    def test_account_history_from_prior_day_is_replaced_by_dated_evidence(self):
        engine = self.engine
        proof = self.proof()
        old = AccountDailyBaseline('account-a', proof.previous_trade_date, D('999'), 'OLD_FIXTURE')
        engine._persist('prior_close_fixture', replace(engine.state, account_daily_baselines=(old,)))
        self.confirm(proof)
        self.assertEqual(len(engine.state.account_daily_baselines), 2)
        self.assertTrue(all(row.trade_date == proof.trade_date for row in engine.state.account_daily_baselines))

    def test_new_calendar_day_invalidates_old_reconciliation_before_accepting_a_close(self):
        engine = self.engine
        next_day = engine.calendar.advance(engine.state.trading_day, 1)
        engine.clock.value = engine.calendar.day_session(next_day).opens_at
        engine.manual_observations = {ref: replace(row, as_of=engine.clock.now()) for ref, row in engine.manual_observations.items()}
        with self.assertRaises(DomainError) as raised:
            self.confirm()
        self.assertEqual(raised.exception.code, 'reconciliation_required')
        self.assertEqual(engine.state.trading_day, next_day)
        self.assertFalse(engine.state.reconciled)

    def test_calendar_rollback_cannot_attest_against_a_later_ledger_day(self):
        engine = self.engine
        proof = self.proof()
        engine._persist('later_ledger_day_fixture', replace(engine.state, trading_day=engine.calendar.advance(engine.state.trading_day, 1)))
        with self.assertRaises(DomainError) as raised:
            self.confirm(proof)
        self.assertEqual(raised.exception.code, 'account_daily_baseline_required')


if __name__ == '__main__':
    unittest.main()
