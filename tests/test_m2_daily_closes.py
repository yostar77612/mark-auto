"""Closing marks are actual cached quotes plus the normalized app-owned ledger."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_m2_automatic import MemoryEngine
from quantlab.trading.application.account_risk import account_net_mark
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.daily_closes import SOURCE_ID, daily_close_evidence, observe_daily_closes
from quantlab.trading.application.manual_book import ManualBook
from quantlab.trading.application.performance import liquidation_value, unrealized_liquidation
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.sessions import validate_baseline
from quantlab.trading.application.state import replace_order
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar, calendar_for_instrument
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, Market, OrderStatus, PositionLot, Quote, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation

D = Decimal
SIM = Environment.BROKER_SIMULATION


class DailyClosesTests(unittest.TestCase):
    def setUp(self):
        initialize()
        self.engine = MemoryEngine()
        self.stock = self.engine.catalog.instruments[0]
        self.future = self.engine.catalog.instruments[1]
        self.day = self.engine.state.trading_day
        self.lot = self.add_lot('test-stock', self.stock)

    def add_lot(self, reference, spec, *, direction=Side.BUY, costs=D('0')):
        if reference not in self.engine.gateways:
            self.engine.gateways[reference] = SimpleNamespace()
            self.engine.state = replace(
                self.engine.state,
                manual_books=(*self.engine.state.manual_books, ManualBook('book-' + reference, reference, D('20000'), self.day, market=spec.market)),
            )
        self.engine.record = self.engine.make_record(instrument_id=spec.instrument_id, strategy_id='strategy-' + reference + '-' + spec.instrument_id)
        self.engine.state = replace(self.engine.state, strategies=(*self.engine.state.strategies, self.engine.record))
        order = self.engine.order('seed-' + reference + '-' + spec.instrument_id, status=OrderStatus.FILLED)
        quantity = 1000 if spec.market is Market.STOCK else 1
        order = replace(
            order, filled=quantity, average_price=D('10'), costs=costs, plan=replace(order.plan, account_ref=reference, quantity=quantity, side=direction)
        )
        self.engine.state = replace_order(self.engine.state, order)
        lot = PositionLot(
            order.order_id,
            reference,
            spec.instrument_id,
            self.engine.record.strategy_id,
            self.engine.record.version,
            self.engine.record.policy,
            quantity,
            D('10'),
            self.day,
            quantity,
            direction=direction,
        )
        self.engine.state = replace(self.engine.state, positions=(*self.engine.state.positions, lot))
        return lot

    def session(self, spec=None, day=None):
        return calendar_for_instrument(self.engine.calendar, spec or self.stock).day_session(day or self.day)

    def close_clock(self, spec=None, *, seconds=0, observed_at=None):
        session = self.session(spec)
        self.engine.clock.value = session.closes_at + timedelta(seconds=seconds)
        now = self.engine.clock.now()
        self.engine.manual_observations = {
            reference: ManualAccountObservation(reference, SIM, (), (), (), observed_at or now) for reference in self.engine.gateways
        }
        return session

    def bar(self, spec=None, **changes):
        spec = spec or self.stock
        session = self.session(spec)
        return replace(
            LiveBar(spec.instrument_id, session.opens_at, session.closes_at, self.day, 'DAY', D('10'), D('10'), D('10'), D('10'), 100, final=True), **changes
        )

    def quote(self, spec=None, **changes):
        spec = spec or self.stock
        values = dict(
            instrument_id=spec.instrument_id,
            bid=D('9'),
            ask=D('11'),
            last=D('10'),
            source_at=self.session(spec).closes_at,
            received_at=self.engine.clock.now(),
            trade_date=self.day,
            source='SHIOAJI',
        )
        values.update(changes)
        self.engine.quotes[spec.instrument_id] = Quote(**values)
        return self.engine.quotes[spec.instrument_id]

    def seal(self):
        self.close_clock()
        quote = self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertEqual(len(self.engine.state.daily_account_closes), 1)
        return self.engine.state.daily_account_closes[0], quote

    def target(self):
        return self.engine.calendar.advance(self.day, 1)

    def close_marks(self, close):
        marks = tuple(row for row in self.engine.state.daily_closing_quotes if (row.account_ref, row.trade_date) == (close.account_ref, close.trade_date))
        self.assertEqual(tuple(row.quote.instrument_id for row in marks), close.closing_quote_refs)
        self.assertEqual(close.closing_quotes, ())
        return marks

    def test_actual_quote_ledger_and_costs_match_current_net_mark_without_timestamp_changes(self):
        self.engine.fees = FeeSchedule()
        entry = self.engine.state.orders[-1]
        self.engine.state = replace_order(self.engine.state, replace(entry, costs=D('27')))
        closed = replace(self.lot, lot_id='old-closed', quantity=0, sellable_quantity=0, realized_pnl=D('-123'))
        self.engine.state = replace(self.engine.state, positions=(*self.engine.state.positions, closed))
        self.close_clock()
        quote = self.quote()
        expected = account_net_mark(self.engine, 'test-stock')
        observe_daily_closes(self.engine, (self.bar(),))
        close = self.engine.state.daily_account_closes[0]
        self.assertEqual(close.net_pnl, expected)
        self.assertIs(self.close_marks(close)[0].quote, quote)
        self.assertEqual(loads(dumps(close)), close)
        self.assertEqual(close.source_id, SOURCE_ID)

    def test_shared_pure_liquidation_preserves_long_short_and_live_freshness_guard(self):
        self.close_clock()
        quote = self.quote()
        self.engine.fees = FeeSchedule()
        for direction in (Side.BUY, Side.SELL):
            lot = replace(self.lot, direction=direction)
            price, sign, exit_side = (quote.bid, 1, Side.SELL) if direction is Side.BUY else (quote.ask, -1, Side.BUY)
            expected = (price - lot.entry_price) * lot.quantity * sign - self.engine.fees.transaction(self.stock, exit_side, price, lot.quantity)
            expected -= self.engine.fees.slippage(self.stock, lot.quantity, legs=1, prices=(price,))
            self.assertEqual(liquidation_value(self.stock, lot, quote, self.engine.fees), expected)
            self.assertEqual(unrealized_liquidation(self.engine, lot), expected)
        self.engine.clock.value += timedelta(seconds=31)
        with self.assertRaises(DomainError):
            unrealized_liquidation(self.engine, self.lot)
        self.assertIsInstance(liquidation_value(self.stock, self.lot, quote, self.engine.fees), D)

    def test_zero_quantity_needs_no_live_quote_or_spec_lookup(self):
        lot = replace(self.lot, quantity=0, sellable_quantity=0)
        self.engine.quotes = {}
        self.assertEqual(unrealized_liquidation(self.engine, lot), D('0'))
        self.assertEqual(liquidation_value(None, lot, None, None), D('0'))

    def test_postclose_adoption_required_and_candidates_keep_the_original_quote(self):
        session = self.close_clock(observed_at=self.session().closes_at - timedelta(seconds=1))
        original = self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertEqual(len(self.engine.state.daily_closing_quotes), 1)
        self.assertEqual(self.engine.state.daily_account_closes, ())
        self.close_clock(seconds=2)
        self.quote(bid=D('100'), ask=D('101'), last=D('100'))
        observe_daily_closes(self.engine, ())
        close = self.engine.state.daily_account_closes[0]
        self.assertEqual(close.as_of, session.closes_at)
        self.assertIs(self.close_marks(close)[0].quote, original)
        self.assertEqual(close.net_pnl, D('-1000'))

    def test_mixed_stock_and_future_close_independently_then_exact_account_split(self):
        self.add_lot('future', self.future)
        self.close_clock()
        stock_quote = self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertEqual(tuple(row.account_ref for row in self.engine.state.daily_account_closes), ('test-stock',))
        with self.assertRaises(DomainError):
            daily_close_evidence(self.engine, self.target())
        self.close_clock(self.future)
        future_quote = self.quote(self.future)
        observe_daily_closes(self.engine, (self.bar(self.future),))
        evidence = daily_close_evidence(self.engine, self.target())
        self.assertEqual(evidence.as_of, self.session(self.future).closes_at)
        self.assertEqual(dict(evidence.account_previous_close), {'test-stock': D('-1000'), 'future': D('-10')})
        marks = tuple(mark for row in self.engine.state.daily_account_closes for mark in self.close_marks(row))
        self.assertIn(stock_quote, tuple(mark.quote for mark in marks))
        self.assertIn(future_quote, tuple(mark.quote for mark in marks))
        for close in self.engine.state.daily_account_closes:
            expected = self.stock.instrument_id if close.account_ref == 'test-stock' else self.future.instrument_id
            self.assertEqual(tuple(mark.quote.instrument_id for mark in self.close_marks(close)), (expected,))

    def test_repeated_observation_does_not_append_duplicate_quotes_or_closes(self):
        self.seal()
        version = self.engine.state.version
        observe_daily_closes(self.engine, (self.bar(),))
        observe_daily_closes(self.engine, ())
        self.assertEqual(len(self.engine.state.daily_closing_quotes), 1)
        self.assertEqual(len(self.engine.state.daily_account_closes), 1)
        self.assertEqual(self.engine.state.version, version)

    def test_unchanged_captured_quotes_can_finalize_after_verified_day_rollover(self):
        self.close_clock(observed_at=self.session().closes_at - timedelta(seconds=1))
        quote = self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        target = self.target()
        self.engine.state = replace(self.engine.state, trading_day=target)
        self.engine.clock.value = self.session(day=target).opens_at + timedelta(minutes=1)
        self.engine.manual_observations = {'test-stock': ManualAccountObservation('test-stock', SIM, (), (), (), self.engine.clock.now())}
        observe_daily_closes(self.engine, ())
        close = self.engine.state.daily_account_closes[0]
        self.assertEqual(close.trade_date, self.day)
        self.assertEqual(close.net_pnl, D('-1000'))
        self.assertIs(self.close_marks(close)[0].quote, quote)

    def test_expiry_product_quote_freezes_before_later_contract_in_the_same_account(self):
        self.day = self.future.expiry
        later = replace(self.future, instrument_id='TAIFEX:TMF:202612', expiry=self.future.expiry.replace(month=12, day=16), delivery_month='202612')
        self.engine.catalog = type(self.engine.catalog)((self.stock, self.future, later))
        self.engine.state = replace(
            self.engine.state,
            trading_day=self.day,
            positions=(),
            orders=(),
            manual_books=(replace(self.engine.state.manual_books[0], market=Market.INDEX_FUTURE),),
        )
        self.add_lot('test-stock', self.future)
        self.add_lot('test-stock', later)
        self.close_clock(self.future)
        expiring_quote = self.quote(self.future)
        observe_daily_closes(self.engine, (self.bar(self.future),))
        self.assertFalse(self.engine.state.daily_account_closes)
        self.close_clock(later)
        self.quote(later)
        observe_daily_closes(self.engine, (self.bar(later),))
        close = self.engine.state.daily_account_closes[0]
        self.assertEqual(close.as_of.hour, 13)
        self.assertEqual(close.as_of.minute, 45)
        self.assertEqual(close.net_pnl, D('-20'))
        self.assertIs(self.close_marks(close)[0].quote, expiring_quote)
        self.assertEqual(self.close_marks(close)[0].session_close_at.minute, 30)

    def test_realized_only_account_needs_no_synthetic_quote_or_balance(self):
        self.engine.state = replace(self.engine.state, positions=(replace(self.lot, quantity=0, sellable_quantity=0, realized_pnl=D('-37')),))
        self.engine.quotes = {}
        self.close_clock()
        observe_daily_closes(self.engine, ())
        close = self.engine.state.daily_account_closes[0]
        self.assertEqual(close.net_pnl, D('-37'))
        self.assertEqual(close.closing_quotes, ())

    def test_missing_prior_close_cannot_be_reconstructed_from_next_morning_pnl(self):
        self.engine.state = replace(self.engine.state, positions=(replace(self.lot, quantity=0, sellable_quantity=0, realized_pnl=D('999')),))
        self.engine.clock.value = self.session(day=self.target()).opens_at
        self.engine.manual_observations = {'test-stock': ManualAccountObservation('test-stock', SIM, (), (), (), self.engine.clock.now())}
        observe_daily_closes(self.engine, ())
        self.assertFalse(self.engine.state.daily_account_closes)

    def test_new_day_order_cannot_be_folded_into_an_unsealed_prior_close(self):
        self.close_clock(observed_at=self.session().closes_at - timedelta(seconds=1))
        self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        self.engine.clock.value = self.session(day=self.target()).opens_at
        self.engine.manual_observations = {'test-stock': ManualAccountObservation('test-stock', SIM, (), (), (), self.engine.clock.now())}
        extra = replace(self.stock, instrument_id='TWSE:2331', underlying='2331')
        self.engine.catalog = type(self.engine.catalog)((self.stock, self.future, extra))
        order = self.engine.order('new-day-before-close-proof', status=OrderStatus.CANCELED)
        self.engine.state = replace_order(self.engine.state, replace(order, plan=replace(order.plan, instrument_id=extra.instrument_id)))
        observe_daily_closes(self.engine, ())
        self.assertFalse(self.engine.state.daily_account_closes)

    def test_bar_boundary_finality_and_session_are_required(self):
        self.close_clock()
        self.quote()
        for changes in (
            {'final': False},
            {'incomplete': True},
            {'session': 'NIGHT'},
            {'start': self.session().opens_at + timedelta(minutes=1)},
            {'end': self.session().closes_at - timedelta(minutes=1)},
        ):
            with self.subTest(changes=changes):
                observe_daily_closes(self.engine, (self.bar(**changes),))
                self.assertFalse(self.engine.state.daily_closing_quotes)
                self.assertFalse(self.engine.state.daily_account_closes)

    def test_quote_quality_source_day_and_session_are_required(self):
        self.close_clock()
        for changes in ({'quality': 'UNKNOWN'}, {'source': 'LOCAL_SIMULATED'}, {'trade_date': self.day - timedelta(days=1)}, {'session': 'NIGHT'}):
            with self.subTest(changes=changes):
                self.quote(**changes)
                observe_daily_closes(self.engine, (self.bar(),))
                self.assertFalse(self.engine.state.daily_closing_quotes)
                self.assertFalse(self.engine.state.daily_account_closes)

    def test_quote_missing_stale_future_or_after_official_close_is_not_fabricated(self):
        self.close_clock(seconds=2)
        changes = (
            {'source_at': self.session().closes_at - timedelta(seconds=11)},
            {'source_at': self.engine.clock.now() + timedelta(seconds=1), 'received_at': self.engine.clock.now() + timedelta(seconds=1)},
            {'received_at': self.engine.clock.now() + timedelta(seconds=1)},
            {'source_at': self.session().closes_at + timedelta(seconds=1)},
        )
        for values in changes:
            with self.subTest(values=values):
                self.quote(**values)
                observe_daily_closes(self.engine, (self.bar(),))
                self.assertFalse(self.engine.state.daily_closing_quotes)
        self.engine.quotes = {}
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(self.engine.state.daily_account_closes)

    def test_forming_time_cannot_capture_a_future_daily_bar(self):
        self.close_clock(seconds=-1)
        self.quote(source_at=self.engine.clock.now())
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(self.engine.state.daily_closing_quotes)

    def test_missing_owner_guard_or_denied_owner_cannot_capture(self):
        self.close_clock()
        self.quote()
        original = self.engine.automatic_submission_guard
        del self.engine.automatic_submission_guard
        with self.assertRaises(DomainError):
            observe_daily_closes(self.engine, (self.bar(),))
        self.engine.automatic_submission_guard = Mock(side_effect=DomainError('state_conflict'))
        with self.assertRaises(DomainError):
            observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(self.engine.state.daily_closing_quotes)
        self.engine.automatic_submission_guard = original

    def test_owner_guard_spans_journal_and_uses_full_observation_not_protective_partial(self):
        self.close_clock()
        self.quote()
        held = []

        @contextmanager
        def guard(reference, *, reduce_only):
            self.assertEqual((reference, reduce_only), ('test-stock', True))
            held.append(True)
            try:
                yield
            finally:
                held.pop()

        self.engine.automatic_submission_guard = guard
        self.engine.automatic_observation_validator.side_effect = lambda *args: self.assertTrue(held)
        original = self.engine._persist

        def persist(kind, state):
            self.assertTrue(held)
            original(kind, state)

        self.engine._persist = persist
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(held)

    def test_missing_stale_or_unresolved_full_cache_blocks_capture(self):
        self.close_clock()
        self.quote()
        self.engine.manual_observations = {}
        with self.assertRaises(DomainError):
            observe_daily_closes(self.engine, (self.bar(),))
        self.close_clock(observed_at=self.engine.clock.now() - timedelta(seconds=31))
        with self.assertRaises(DomainError):
            observe_daily_closes(self.engine, (self.bar(),))
        self.close_clock()
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], status=OrderStatus.UNKNOWN))
        with self.assertRaises(DomainError):
            observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(self.engine.state.daily_closing_quotes)

    def test_working_orders_and_unresolved_manual_requests_cannot_seal(self):
        self.close_clock()
        self.quote()
        entry = self.engine.state.orders[-1]
        self.engine.state = replace_order(self.engine.state, replace(entry, status=OrderStatus.ACCEPTED))
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(self.engine.state.daily_account_closes)
        self.engine.state = replace_order(self.engine.state, entry)
        self.engine.state = replace(self.engine.state, manual_requests=(SimpleNamespace(scope=SimpleNamespace(account_ref='test-stock'), outcome_known=False),))
        observe_daily_closes(self.engine, ())
        self.assertFalse(self.engine.state.daily_account_closes)
        self.engine.state = replace(self.engine.state, manual_requests=())
        observe_daily_closes(self.engine, ())
        self.assertEqual(len(self.engine.state.daily_account_closes), 1)

    def test_late_economic_delta_invalidates_sealed_close_and_stops_new_risk(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, stopped=False, automatic=replace(self.engine.state.automatic, auto_paused=False, reasons=()))
        order = self.engine.state.orders[-1]
        self.engine.state = replace_order(self.engine.state, replace(order, costs=order.costs + D('1')))
        observe_daily_closes(self.engine, ())
        changed = self.engine.state.daily_account_closes[0]
        self.assertTrue(changed.invalidated)
        self.assertEqual(changed.net_pnl, close.net_pnl)
        self.assertTrue(self.engine.state.stopped)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertIn('daily_close_unverified', self.engine.state.issues)
        with self.assertRaises(DomainError):
            daily_close_evidence(self.engine, self.target())

    def test_each_preclose_order_fill_average_and_fee_delta_invalidates_after_consumption(self):
        close, _ = self.seal()
        base = replace(self.engine.state, daily_account_closes=(replace(close, consumed_on=self.target()),))
        order = self.engine.state.orders[-1]
        for values in ({'filled': order.filled - 1}, {'average_price': D('11')}, {'costs': D('1')}):
            self.engine.state = replace_order(base, replace(order, **values))
            with self.subTest(values=values):
                observe_daily_closes(self.engine, ())
                self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_removed_preclose_order_cannot_be_treated_as_unchanged(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, orders=(), daily_account_closes=(replace(close, consumed_on=self.target()),))
        observe_daily_closes(self.engine, ())
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_status_only_terminal_ack_does_not_invalidate_a_close(self):
        close, _ = self.seal()
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], event_sequence=100, daily_fill_count=99))
        observe_daily_closes(self.engine, ())
        self.assertEqual(self.engine.state.daily_account_closes[0], close)

    def test_missing_or_broker_labeled_book_cannot_certify_an_app_virtual_close(self):
        self.close_clock()
        self.quote()
        for books in ((), (replace(self.engine.state.manual_books[0], source='BROKER_BALANCE'),)):
            self.engine.state = replace(self.engine.state, manual_books=books)
            with self.subTest(books=books), self.assertRaises(DomainError):
                observe_daily_closes(self.engine, (self.bar(),))

    def test_evidence_first_unverified_or_nonprevious_day_is_rejected(self):
        self.seal()
        for day in (self.engine.calendar.days[0], self.day + timedelta(days=1), self.engine.calendar.advance(self.day, 2)):
            with self.subTest(day=day), self.assertRaises(DomainError):
                daily_close_evidence(self.engine, day)

    def test_evidence_detects_unobserved_economic_change_without_mutating_state(self):
        self.seal()
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], costs=D('1')))
        state = self.engine.state
        with self.assertRaises(DomainError):
            daily_close_evidence(self.engine, self.target())
        self.assertIs(self.engine.state, state)

    def test_late_delta_before_postclose_adopt_keeps_candidate_and_never_recaptures(self):
        self.close_clock(observed_at=self.session().closes_at - timedelta(seconds=1))
        quote = self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        self.engine.state = replace_order(self.engine.state, replace(self.engine.state.orders[-1], costs=D('1')))
        self.close_clock(seconds=1)
        observe_daily_closes(self.engine, ())
        self.assertFalse(self.engine.state.daily_account_closes)
        self.assertIs(self.engine.state.daily_closing_quotes[0].quote, quote)
        self.assertIn('daily_close_unverified', self.engine.state.issues)
        observe_daily_closes(self.engine, (self.bar(),))
        self.assertFalse(self.engine.state.daily_account_closes)

    def test_conflicting_final_bar_invalidates_the_candidate_instead_of_overwriting_it(self):
        self.close_clock(observed_at=self.session().closes_at - timedelta(seconds=1))
        self.quote()
        original = self.bar()
        observe_daily_closes(self.engine, (original,))
        self.close_clock(seconds=1)
        observe_daily_closes(self.engine, (replace(original, close=D('11')),))
        self.assertEqual(self.engine.state.daily_closing_quotes[0].bar, original)
        self.assertFalse(self.engine.state.daily_account_closes)

    def test_sellable_t_plus_two_quote_and_state_version_do_not_change_financial_fingerprint(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, positions=(replace(self.lot, sellable_quantity=0),), version=self.engine.state.version + 1)
        self.engine.quotes[self.stock.instrument_id] = replace(self.engine.quotes[self.stock.instrument_id], bid=D('1'), ask=D('100'))
        observe_daily_closes(self.engine, ())
        self.assertEqual(self.engine.state.daily_account_closes[0], close)

    def test_before_consumption_unattributed_position_change_invalidates_close(self):
        self.seal()
        self.engine.state = replace(self.engine.state, positions=(replace(self.lot, realized_pnl=D('1')),))
        observe_daily_closes(self.engine, ())
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_consumed_close_ignores_normal_new_day_orders_and_exits_but_not_old_order_delta(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, daily_account_closes=(replace(close, consumed_on=self.target()),), trading_day=self.target())
        self.engine.clock.value = self.session(day=self.target()).opens_at + timedelta(minutes=1)
        self.engine.manual_observations = {'test-stock': ManualAccountObservation('test-stock', SIM, (), (), (), self.engine.clock.now())}
        self.engine.order('new-day-exit', status=OrderStatus.FILLED, lot=self.lot)
        self.engine.state = replace(self.engine.state, positions=(replace(self.lot, quantity=0, sellable_quantity=0, realized_pnl=D('100')),))
        observe_daily_closes(self.engine, ())
        self.assertFalse(self.engine.state.daily_account_closes[0].invalidated)
        self.assertEqual(daily_close_evidence(self.engine, self.target()).previous_close_total_pnl, close.net_pnl)
        entry = self.engine.state.orders[0]
        self.engine.state = replace_order(self.engine.state, replace(entry, costs=D('99')))
        observe_daily_closes(self.engine, ())
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_late_appearing_old_order_invalidates_even_after_consumption(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, daily_account_closes=(replace(close, consumed_on=self.target()),))
        self.engine.order('late-old-order', status=OrderStatus.CANCELED)
        observe_daily_closes(self.engine, ())
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_read_only_evidence_exact_date_accounts_fee_and_source_without_applying_or_resuming(self):
        close, _ = self.seal()
        state = self.engine.state
        proof = daily_close_evidence(self.engine, self.target())
        self.assertIs(self.engine.state, state)
        calendar = automatic_day_calendar(self.engine.calendar, self.engine.catalog.instruments)
        validate_baseline(
            proof,
            environment=SIM,
            account_refs=tuple(self.engine.gateways),
            calendar=calendar,
            fees=self.engine.fees,
            now=calendar.day_session(self.target()).opens_at,
            trade_date=self.target(),
            trusted_sources=frozenset((SOURCE_ID,)),
        )
        self.assertEqual(proof.previous_trade_date, self.day)
        self.assertEqual(proof.account_previous_close, (('test-stock', close.net_pnl),))
        self.assertIsNone(self.engine.state.automatic_daily_evidence)
        self.assertTrue(self.engine.state.automatic.auto_paused)

    def test_missing_prior_day_partial_accounts_wrong_source_or_calendar_cannot_build_evidence(self):
        with self.assertRaises(DomainError):
            daily_close_evidence(self.engine, self.target())
        close, _ = self.seal()
        for changes in (
            {'invalidated': True},
            {'source_id': 'CLIENT_BOOLEAN'},
            {'calendar_id': 'changed'},
            {'calendar_version': 'changed'},
            {'as_of': close.as_of - timedelta(seconds=1)},
        ):
            self.engine.state = replace(self.engine.state, daily_account_closes=(replace(close, **changes),))
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                daily_close_evidence(self.engine, self.target())

    def test_fee_change_even_same_version_invalidates_the_close(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, daily_account_closes=(replace(close, consumed_on=self.target()),))
        self.engine.fees = replace(self.engine.fees, minimum_fee=D('1'))
        observe_daily_closes(self.engine, ())
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_cost_policy_change_during_postclose_wait_invalidates_the_candidate(self):
        self.close_clock(observed_at=self.session().closes_at - timedelta(seconds=1))
        self.quote()
        observe_daily_closes(self.engine, (self.bar(),))
        self.engine.fees = replace(self.engine.fees, minimum_fee=D('1'))
        self.close_clock(seconds=1)
        observe_daily_closes(self.engine, ())
        self.assertFalse(self.engine.state.daily_account_closes)
        self.assertIn('daily_close_unverified', self.engine.state.issues)

    def test_financial_price_grid_change_invalidates_even_after_consumption(self):
        close, _ = self.seal()
        self.engine.state = replace(self.engine.state, daily_account_closes=(replace(close, consumed_on=self.target()),))
        self.engine.catalog = type(self.engine.catalog)((replace(self.stock, tick_size=self.stock.tick_size * 2), self.future))
        observe_daily_closes(self.engine, ())
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)

    def test_first_day_and_empty_account_scope_have_explicit_failclosed_errors(self):
        self.seal()
        with self.assertRaises(DomainError) as missing_previous:
            daily_close_evidence(self.engine, self.engine.calendar.days[0])
        self.assertEqual(missing_previous.exception.detail, 'no prior verified DAY')
        self.engine.gateways = {}
        with self.assertRaises(DomainError) as missing_accounts:
            daily_close_evidence(self.engine, self.target())
        self.assertEqual(missing_accounts.exception.code, 'daily_close_unverified')

    def test_evidence_local_closed_and_storage_failure_deny_before_returning_cached_fact(self):
        self.seal()
        for environment, closed, failed in ((Environment.LOCAL, False, False), (SIM, True, False), (SIM, False, True)):
            self.engine.configuration.environment = environment
            self.engine.state = replace(self.engine.state, engine_closed=closed)
            self.engine.storage_failed = failed
            with self.subTest(environment=environment, closed=closed, failed=failed), self.assertRaises(DomainError):
                daily_close_evidence(self.engine, self.target())

    def test_live_all_provider_routes_deny_before_owner_or_cache_access(self):
        self.engine.configuration.environment = Environment.LIVE
        for operation in (lambda: observe_daily_closes(self.engine, ()), lambda: daily_close_evidence(self.engine, self.target())):
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'production_orders_disabled')
        self.engine.automatic_submission_guard.assert_not_called()

    def test_local_closed_or_failed_engine_has_no_provider_authority(self):
        for environment, closed, failed in ((Environment.LOCAL, False, False), (SIM, True, False), (SIM, False, True)):
            self.engine.configuration.environment = environment
            self.engine.state = replace(self.engine.state, engine_closed=closed)
            self.engine.storage_failed = failed
            with self.subTest(environment=environment, closed=closed, failed=failed), self.assertRaises(DomainError):
                observe_daily_closes(self.engine, ())

    def test_no_financial_queries_or_order_operations(self):
        self.seal()
        daily_close_evidence(self.engine, self.target())
        for gateway in self.engine.gateways.values():
            gateway.snapshot.assert_not_called()
            gateway.refresh.assert_not_called()
            gateway.events.assert_not_called()
            gateway.cancel.assert_not_called()
