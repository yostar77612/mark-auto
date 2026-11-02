"""Bounded daily projections preserve late financial-change and dispatch safety."""

from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal as D
import json
import unittest

import test_m2_automatic as fixtures
import test_m2_daily_closes as closing_fixtures

from quantlab.trading.application.codec import MAX_BYTES, dumps, loads
from quantlab.trading.application.context import ExecutionConfiguration
from quantlab.trading.application.daily_closes import (
    ClosingQuote,
    DailyAccountClose,
    _changed,
    _financial_fingerprint,
    _order_fingerprint,
    daily_close_evidence,
)
from quantlab.trading.application.daily_retention import (
    DAILY_RETENTION_TRADE_DAYS,
    archive_changed,
    compact_daily_projection,
    compact_daily_state,
    order_digest,
)
from quantlab.trading.application.daily_state import DailyIntent
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.auto_cycle import EvaluationCursor, evaluation_key, evaluation_key_matches
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar, calendar_for_instrument
from quantlab.trading.domain.calendar import TradingSession
from quantlab.trading.application.sessions import fee_fingerprint
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, OrderStatus, Quote
from quantlab.trading.ports.storage import StoredEvent


class DailyRetentionTests(unittest.TestCase):
    def setUp(self):
        initialize()
        self.engine = fixtures.MemoryEngine()
        self.spec = self.engine.catalog.instruments[0]
        self.day = self.engine.state.trading_day
        self.current = self.engine.calendar.advance(self.day, 30)
        self.engine.clock.value = self.session(self.current).closes_at
        self.engine.state = replace(self.engine.state, trading_day=self.current)

    def session(self, day):
        return calendar_for_instrument(self.engine.calendar, self.spec).day_session(day)

    def close(self, day=None, *, consumed=True, legacy=False):
        day = day or self.day
        session = self.session(day)
        bar = LiveBar(self.spec.instrument_id, session.opens_at, session.closes_at, day, 'DAY', D('10'), D('10'), D('10'), D('10'), 1, final=True)
        quote = Quote(self.spec.instrument_id, D('10'), D('10'), D('10'), session.closes_at, session.closes_at, day, source='SHIOAJI')
        mark = ClosingQuote('test-stock', day, session.closes_at, quote, bar, _financial_fingerprint(self.engine, 'test-stock', self.spec.instrument_id))
        calendar = automatic_day_calendar(self.engine.calendar, (self.spec,))
        digest, count = order_digest(self.engine, 'test-stock', session.closes_at)
        fingerprints = tuple(
            (row.order_id, _order_fingerprint(self.engine, row)) for row in self.engine.state.orders if row.plan.decision_at <= session.closes_at
        )
        close = DailyAccountClose(
            'test-stock',
            day,
            session.closes_at,
            session.closes_at,
            D('0'),
            (mark,) if legacy else (),
            _financial_fingerprint(self.engine, 'test-stock'),
            fingerprints if legacy else (),
            calendar.calendar_id,
            calendar.version,
            fee_fingerprint(self.engine.fees),
            consumed_on=self.engine.calendar.advance(day, 1) if consumed else None,
            closing_quote_refs=() if legacy else (self.spec.instrument_id,),
            order_digest='' if legacy else digest,
            order_count=0 if legacy else count,
        )
        return close, mark

    def add_close(self, day=None, **kwargs):
        close, mark = self.close(day, **kwargs)
        self.engine.state = replace(
            self.engine.state,
            daily_account_closes=(*self.engine.state.daily_account_closes, close),
            daily_closing_quotes=(*self.engine.state.daily_closing_quotes, mark),
        )
        return close, mark

    def order(self, *, day=None, status=OrderStatus.FILLED, key='owned-old-order'):
        now = self.engine.clock.value
        self.engine.clock.value = self.session(day or self.day).opens_at
        order = self.engine.order(key, status=status)
        self.engine.clock.value = now
        return order

    def intent(self, *, phase='EXPIRED', order_id='', day=None, key_lot=''):
        day = day or self.day
        session = self.session(day)
        previous = self.engine.calendar.days[self.engine.calendar.index(day) - 1]
        cursor = EvaluationCursor('strategy', 1, self.spec.instrument_id, '1d', self.session(previous).closes_at)
        calendar = calendar_for_instrument(self.engine.calendar, self.spec)
        return DailyIntent(
            cursor,
            'test-stock',
            'EXIT' if key_lot else 'ENTRY',
            self.spec.instrument_id,
            key_lot,
            'a' * 64,
            calendar.calendar_id,
            calendar.version,
            day,
            session.opens_at,
            session.closes_at,
            cursor.bar_end,
            phase=phase,
            order_id=order_id,
        )

    def set_intents(self, *intents):
        automatic = self.engine.state.automatic
        self.engine.state = replace(self.engine.state, automatic=replace(automatic, daily=replace(automatic.daily, intents=intents)))

    def test_consumed_old_close_becomes_one_archive_and_drops_its_quote(self):
        close, _ = self.add_close()
        automatic = self.engine.state.automatic
        self.engine.state = replace(
            self.engine.state,
            automatic=replace(
                automatic,
                auto_paused=False,
                reasons=(),
                daily=replace(automatic.daily, authorized_run='authorized-run', owner_stamp='server-owner', waiting_session=True),
            ),
        )
        before = self.engine.state
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_account_closes, ())
        self.assertEqual(self.engine.state.daily_closing_quotes, ())
        self.assertEqual(len(self.engine.state.daily_close_archives), 1)
        archive = self.engine.state.daily_close_archives[0]
        self.assertEqual(
            (archive.account_ref, archive.trade_date, archive.net_pnl, archive.ledger_fingerprint),
            (close.account_ref, close.trade_date, close.net_pnl, close.ledger_fingerprint),
        )
        self.assertFalse(archive_changed(self.engine, archive))
        self.assertEqual(self.engine.state.orders, before.orders)
        self.assertEqual(self.engine.state.positions, before.positions)
        self.assertEqual(self.engine.state.automatic, before.automatic)

    def test_unconsumed_invalidated_and_working_order_closes_are_audit_needed(self):
        for changes in ({'consumed_on': None}, {'invalidated': True}):
            with self.subTest(changes=changes):
                close, mark = self.close()
                close = replace(close, **changes)
                self.engine.state = replace(self.engine.state, daily_account_closes=(close,), daily_closing_quotes=(mark,))
                compact_daily_state(self.engine)
                self.assertEqual(self.engine.state.daily_account_closes, (close,))
                self.assertEqual(self.engine.state.daily_closing_quotes, (mark,))
        self.order(status=OrderStatus.ACCEPTED)
        close, mark = self.close()
        self.engine.state = replace(self.engine.state, daily_account_closes=(close,), daily_closing_quotes=(mark,))
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_account_closes, (close,))

    def test_only_verified_day_age_and_strict_window_boundary_may_prune(self):
        days = tuple(row.trade_date for row in self.engine.calendar.sessions if row.kind == 'DAY')
        cutoff = days[days.index(self.current) - DAILY_RETENTION_TRADE_DAYS + 1]
        close, mark = self.add_close(cutoff)
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_account_closes, (close,))
        self.engine.state = replace(self.engine.state, trading_day=self.day)
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_closing_quotes, (mark,))
        self.engine.state = replace(self.engine.state, trading_day=self.current + timedelta(days=2))
        self.engine.calendar = replace(
            self.engine.calendar, sessions=tuple(row for row in self.engine.calendar.sessions if row.trade_date != self.engine.state.trading_day)
        )
        before = self.engine.state
        try:
            compact_daily_state(self.engine)
        except ValueError as error:
            self.fail(f'missing DAY coverage must retain state without indexing an absent day: {error}')
        self.assertIs(self.engine.state, before)

    def test_uncovered_old_date_and_orphan_quote_are_not_assumed_consumed(self):
        close, mark = self.add_close()
        intent = self.intent()
        self.set_intents(intent)
        self.engine.calendar = replace(self.engine.calendar, sessions=tuple(row for row in self.engine.calendar.sessions if row.trade_date != self.day))
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_account_closes, (close,))
        self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))
        self.engine.state = replace(self.engine.state, daily_account_closes=())
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_closing_quotes, (mark,))

    def test_short_verified_coverage_keeps_rows_until_twenty_sessions_exist(self):
        close, mark = self.add_close()
        self.engine.calendar = replace(self.engine.calendar, sessions=tuple(row for row in self.engine.calendar.sessions if row.trade_date >= self.day))
        self.engine.state = replace(self.engine.state, trading_day=self.engine.calendar.advance(self.day, 1))
        try:
            compact_daily_state(self.engine)
        except IndexError as error:
            self.fail(f'a short verified DAY window must be retained without indexing beyond coverage: {error}')
        self.assertEqual(self.engine.state.daily_account_closes, (close,))
        self.assertEqual(self.engine.state.daily_closing_quotes, (mark,))

    def test_night_only_rows_do_not_age_a_day_retention_window(self):
        close, mark = self.add_close()
        first = self.session(self.day)
        last = self.session(self.current)
        nights = tuple(
            TradingSession(
                self.day + timedelta(days=index),
                first.opens_at.replace(hour=15) + timedelta(days=index),
                first.opens_at.replace(hour=23) + timedelta(days=index),
                'NIGHT',
            )
            for index in range(1, 25)
        )
        self.engine.calendar = replace(self.engine.calendar, sessions=(first, *nights, last))
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_account_closes, (close,))
        self.assertEqual(self.engine.state.daily_closing_quotes, (mark,))

    def test_only_sim_healthy_writer_can_persist_and_noop_is_idempotent(self):
        self.add_close()
        for environment in (Environment.LOCAL, Environment.LIVE):
            self.engine.configuration.environment = environment
            before = self.engine.state
            compact_daily_state(self.engine)
            self.assertIs(self.engine.state, before)
        self.engine.configuration.environment = Environment.BROKER_SIMULATION
        self.engine.storage_failed = True
        before = self.engine.state
        compact_daily_state(self.engine)
        self.assertIs(self.engine.state, before)
        self.engine.storage_failed = False
        self.engine.state = replace(self.engine.state, engine_closed=True)
        before = self.engine.state
        compact_daily_state(self.engine)
        self.assertIs(self.engine.state, before)
        self.engine.state = replace(self.engine.state, engine_closed=False)
        compact_daily_state(self.engine)
        version = self.engine.state.version
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.version, version)
        for gateway in self.engine.gateways.values():
            gateway.snapshot.assert_not_called()
            gateway.refresh.assert_not_called()
            gateway.events.assert_not_called()

    def test_archive_only_moves_forward_and_stays_one_per_account(self):
        self.add_close()
        compact_daily_state(self.engine)
        later = self.engine.calendar.advance(self.day, 1)
        self.add_close(later)
        compact_daily_state(self.engine)
        archive = self.engine.state.daily_close_archives[0]
        self.assertEqual(archive.trade_date, later)
        self.add_close()
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_close_archives, (archive,))

    def test_closed_startup_projection_uses_proposed_financial_state_without_any_write(self):
        order = self.order()
        self.add_close()
        before = self.engine.state
        events = tuple(self.engine.events)
        proposed = replace(before, engine_closed=True)
        compacted = compact_daily_projection(self.engine, proposed)
        self.assertTrue(compacted.engine_closed)
        self.assertEqual(compacted.daily_account_closes, ())
        self.assertEqual(len(compacted.daily_close_archives), 1)
        self.assertIs(self.engine.state, before)
        self.assertEqual(tuple(self.engine.events), events)
        changed = replace(proposed, orders=(replace(order, costs=D('3')),), stopped=False)
        invalidated = compact_daily_projection(self.engine, changed)
        self.assertEqual(len(invalidated.daily_account_closes), 1, 'financially changed authority must be retained, not archived')
        self.assertTrue(invalidated.daily_account_closes[0].invalidated)
        self.assertTrue(invalidated.stopped)
        self.assertTrue(invalidated.automatic.auto_paused)
        self.assertIs(self.engine.state, before)

    def test_actual_engine_first_startup_write_compacts_current_and_legacy_closed_payloads(self):
        test = self

        class SeedJournal:
            def __init__(self, payload):
                self.seed = StoredEvent(1, 'old_closed_state', payload, '', 'seed')
                self.writes = []

            def replay(self):
                return (self.seed,)

            def append(self, kind, payload, now, *, expected_sequence):
                test.assertEqual(expected_sequence, 1 + len(self.writes))
                event = StoredEvent(expected_sequence + 1, kind, payload, '', 'write')
                self.writes.append(event)
                return event

        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                fixture = DailyRetentionTests()
                fixture.setUp()
                close, _ = fixture.add_close(legacy=legacy)
                seed = replace(fixture.engine.state, version=1, engine_closed=True)
                payload = dumps(seed)
                if legacy:
                    raw = json.loads(payload)
                    raw['fields'].pop('daily_close_archives')
                    fields = raw['fields']['daily_account_closes']['value'][0]['fields']
                    for name in ('closing_quote_refs', 'order_digest', 'order_count'):
                        fields.pop(name)
                    payload = json.dumps(raw, sort_keys=True, separators=(',', ':'))
                journal = SeedJournal(payload)
                configuration = ExecutionConfiguration(Environment.BROKER_SIMULATION, 'test-stock', '', False, True)
                engine = TradingEngine(
                    journal,
                    fixture.engine.clock,
                    fixture.engine.calendar,
                    fixture.engine.catalog,
                    fixture.engine.gateways,
                    configuration=configuration,
                    fees=fixture.engine.fees,
                )
                first = journal.writes[0]
                written = loads(first.payload)
                self.assertEqual(first.kind, 'startup_reconciliation_required')
                self.assertEqual(written.daily_account_closes, ())
                self.assertEqual(written.daily_closing_quotes, ())
                self.assertEqual(len(written.daily_close_archives), 1)
                self.assertEqual(written.daily_close_archives[0].trade_date, close.trade_date)
                self.assertLess(len(first.payload.encode()), len(payload.encode()))
                self.assertFalse(written.engine_closed)
                self.assertTrue(written.stopped)
                self.assertFalse(written.reconciled)
                self.assertTrue(written.automatic.auto_paused)
                self.assertEqual(written.automatic.daily.authorized_run, '')
                self.assertEqual(loads(journal.seed.payload).daily_account_closes[0].trade_date, close.trade_date)
                self.assertEqual(engine.state.daily_close_archives, written.daily_close_archives)
                for gateway in fixture.engine.gateways.values():
                    gateway.snapshot.assert_not_called()
                    gateway.refresh.assert_not_called()
                    gateway.events.assert_not_called()

    def test_old_journal_fields_decode_and_legacy_nested_quote_can_be_pruned(self):
        close, mark = self.add_close(legacy=True)
        raw = json.loads(dumps(self.engine.state))
        raw['fields'].pop('daily_close_archives')
        fields = raw['fields']['daily_account_closes']['value'][0]['fields']
        for name in ('closing_quote_refs', 'order_digest', 'order_count'):
            fields.pop(name)
        restored = loads(json.dumps(raw))
        self.assertEqual(restored.daily_close_archives, ())
        self.assertEqual(restored.daily_account_closes[0].closing_quotes, (mark,))
        self.engine.state = restored
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_account_closes, ())
        self.assertFalse(archive_changed(self.engine, self.engine.state.daily_close_archives[0]))

    def test_legacy_and_compact_financial_change_detection_agree_before_and_after_prune(self):
        order = self.order()
        for legacy in (True, False):
            self.engine.state = replace(self.engine.state, orders=(order,), daily_account_closes=(), daily_close_archives=(), issues=())
            close, _ = self.add_close(legacy=legacy)
            self.assertFalse(_changed(self.engine, close))
            compact_daily_state(self.engine)
            archive = self.engine.state.daily_close_archives[0]
            self.assertFalse(archive_changed(self.engine, archive))
            for changes in ({'filled': 1}, {'average_price': D('11')}, {'costs': D('2')}):
                with self.subTest(legacy=legacy, changes=changes):
                    self.engine.state = replace(self.engine.state, orders=(replace(order, **changes),))
                    self.assertTrue(_changed(self.engine, close))
                    self.assertTrue(archive_changed(self.engine, archive))
            self.engine.state = replace(self.engine.state, orders=())
            self.assertTrue(_changed(self.engine, close))
            self.assertTrue(archive_changed(self.engine, archive))

    def test_changed_archive_invalidates_without_reseeding_or_pruning_authority(self):
        order = self.order()
        self.add_close()
        compact_daily_state(self.engine)
        archive = self.engine.state.daily_close_archives[0]
        digest, count = order_digest(self.engine, 'other-account', archive.as_of)
        other = replace(archive, account_ref='other-account', order_digest=digest, order_count=count)
        automatic = self.engine.state.automatic
        self.engine.state = replace(
            self.engine.state,
            orders=(replace(order, costs=D('5')),),
            daily_close_archives=(archive, other),
            stopped=False,
            issues=('preexisting',),
            automatic=replace(
                automatic, auto_paused=False, reasons=(), daily=replace(automatic.daily, authorized_run='run', owner_stamp='owner', waiting_session=True)
            ),
        )
        compact_daily_state(self.engine)
        changed = self.engine.state.daily_close_archives[0]
        self.assertTrue(changed.invalidated)
        self.assertEqual(changed.order_digest, archive.order_digest)
        self.assertIn('daily_close_unverified', self.engine.state.issues)
        self.assertIn('preexisting', self.engine.state.issues)
        self.assertFalse(self.engine.state.daily_close_archives[1].invalidated)
        self.assertTrue(self.engine.state.stopped)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertEqual(self.engine.state.automatic.daily.authorized_run, '')

    def test_changed_close_is_invalidated_before_it_can_be_archived(self):
        order = self.order()
        self.add_close()
        self.engine.state = replace(self.engine.state, orders=(replace(order, filled=1),))
        compact_daily_state(self.engine)
        self.assertEqual(len(self.engine.state.daily_account_closes), 1, 'changed closes must remain available for investigation')
        self.assertTrue(self.engine.state.daily_account_closes[0].invalidated)
        self.assertEqual(self.engine.state.daily_close_archives, ())

    def test_archive_count_and_invalidated_archive_authority_cannot_be_washed(self):
        self.add_close()
        compact_daily_state(self.engine)
        archive = self.engine.state.daily_close_archives[0]
        self.assertTrue(archive_changed(self.engine, replace(archive, order_count=archive.order_count + 1)))
        invalid = replace(archive, invalidated=True)
        self.engine.state = replace(self.engine.state, daily_close_archives=(invalid,))
        close, mark = self.add_close(self.engine.calendar.advance(self.day, 1))
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.daily_close_archives, (invalid,))
        self.assertEqual(self.engine.state.daily_account_closes, (close,))
        self.assertEqual(self.engine.state.daily_closing_quotes, (mark,))

    def test_compact_close_count_and_pending_ledger_fingerprint_still_guard_changes(self):
        close, _ = self.close(consumed=False)
        self.assertTrue(_changed(self.engine, replace(close, order_count=close.order_count + 1)))
        self.assertTrue(_changed(self.engine, replace(close, ledger_fingerprint='different')))
        self.assertFalse(_changed(self.engine, replace(close, consumed_on=self.current, ledger_fingerprint='historical')))

    def test_digest_covers_backdated_new_orders_fees_and_contract_cost_grid(self):
        self.order()
        close, _ = self.add_close()
        compact_daily_state(self.engine)
        archive = self.engine.state.daily_close_archives[0]
        self.order(key='late-backdated')
        self.assertTrue(archive_changed(self.engine, archive))
        self.engine.state = replace(self.engine.state, orders=self.engine.state.orders[:1])
        self.engine.fees = replace(self.engine.fees, buy_rate=D('.001'))
        self.assertTrue(archive_changed(self.engine, archive))
        self.assertTrue(_changed(self.engine, close))
        self.engine.fees = fixtures.MemoryEngine().fees
        self.engine.catalog = type(self.engine.catalog)(
            (replace(self.spec, tick_rule_id=self.spec.tick_rule_id + '-revision'), self.engine.catalog.instruments[1])
        )
        self.assertTrue(archive_changed(self.engine, archive))

    def test_new_later_orders_other_accounts_and_tuple_reordering_do_not_change_old_digest(self):
        first = self.order()
        second = self.order(key='old-second')
        self.add_close()
        compact_daily_state(self.engine)
        archive = self.engine.state.daily_close_archives[0]
        later = self.order(day=self.current, key='later-order')
        other = replace(later, order_id='other-account', plan=replace(later.plan, account_ref='different', decision_at=first.plan.decision_at))
        self.engine.state = replace(self.engine.state, orders=(second, later, other, first))
        self.assertFalse(archive_changed(self.engine, archive))

    def test_current_evidence_is_equal_before_and_after_old_row_retention(self):
        self.add_close()
        previous = self.engine.calendar.days[self.engine.calendar.index(self.current) - 1]
        self.add_close(previous, consumed=False)
        before = daily_close_evidence(self.engine, self.current)
        compact_daily_state(self.engine)
        self.assertEqual(daily_close_evidence(self.engine, self.current), before)

    def test_unknown_claimed_ready_and_active_canonical_dispatches_are_retained(self):
        for phase in ('READY', 'CLAIMED', 'UNKNOWN'):
            with self.subTest(phase=phase):
                intent = self.intent(phase=phase)
                self.set_intents(intent)
                compact_daily_state(self.engine)
                self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))
        for status in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING):
            with self.subTest(status=status):
                intent = self.intent(phase='DISPATCHED')
                order = self.order(status=status, key=intent.key)
                intent = replace(intent, order_id=order.order_id)
                self.set_intents(intent)
                compact_daily_state(self.engine)
                self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))
                self.engine.state = replace(self.engine.state, orders=())

    def test_terminal_intents_require_passed_deadline_and_verified_old_target(self):
        for phase in ('EXPIRED', 'INVALIDATED', 'KNOWN_NO_ORDER'):
            with self.subTest(phase=phase):
                self.set_intents(self.intent(phase=phase))
                compact_daily_state(self.engine)
                self.assertEqual(self.engine.state.automatic.daily.intents, ())
        intent = self.intent()
        for changes in ({'deadline': self.engine.clock.now() + timedelta(seconds=1)}, {'target_trade_date': self.current}):
            candidate = replace(intent, **changes)
            self.set_intents(candidate)
            compact_daily_state(self.engine)
            self.assertEqual(self.engine.state.automatic.daily.intents, (candidate,))
        days = tuple(row.trade_date for row in self.engine.calendar.sessions if row.kind == 'DAY')
        cutoff = days[days.index(self.current) - DAILY_RETENTION_TRADE_DAYS + 1]
        boundary = self.intent(day=cutoff)
        self.set_intents(boundary)
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.automatic.daily.intents, (boundary,))

    def test_dispatch_requires_retained_terminal_canonical_order_not_missing_or_empty_id(self):
        for order_id in ('', 'missing-canonical'):
            intent = self.intent(phase='DISPATCHED', order_id=order_id)
            self.set_intents(intent)
            compact_daily_state(self.engine)
            self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))
        for status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            intent = self.intent(phase='DISPATCHED')
            order = self.order(status=status, key=intent.key)
            self.set_intents(replace(intent, order_id=order.order_id))
            compact_daily_state(self.engine)
            self.assertEqual(self.engine.state.automatic.daily.intents, ())
            self.assertIn(order, self.engine.state.orders)

    def test_terminal_no_order_with_same_key_working_order_is_still_audit_needed(self):
        intent = self.intent(phase='KNOWN_NO_ORDER')
        self.order(status=OrderStatus.ACCEPTED, key=intent.key)
        self.set_intents(intent)
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))

    def test_canonical_id_keeps_active_order_even_when_legacy_key_differs(self):
        order = self.order(status=OrderStatus.ACCEPTED, key='legacy-key-format')
        intent = self.intent(phase='DISPATCHED', order_id=order.order_id)
        self.set_intents(intent)
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))

    def test_semantic_timezone_keys_keep_active_and_unknown_orders_audit_needed(self):
        for phase in ('KNOWN_NO_ORDER', 'EXPIRED'):
            for status in (OrderStatus.ACCEPTED, OrderStatus.UNKNOWN):
                with self.subTest(phase=phase, status=status):
                    self.engine.state = replace(self.engine.state, orders=())
                    intent = self.intent(phase=phase)
                    cursor = intent.cursor
                    timestamp = cursor.bar_end.astimezone(timezone(timedelta(hours=8))).isoformat()
                    legacy_key = f'auto:{cursor.strategy_id}:{cursor.version}:{cursor.instrument_id}:{cursor.interval}:{timestamp}'
                    self.assertNotEqual(legacy_key, intent.key)
                    self.assertTrue(evaluation_key_matches(legacy_key, cursor))
                    order = self.order(status=status, key=legacy_key)
                    self.set_intents(intent)
                    compact_daily_state(self.engine)
                    self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))
                    self.assertIn(order, self.engine.state.orders)

    def test_legacy_exit_suffix_keeps_active_order_audit_needed(self):
        intent = self.intent(phase='EXPIRED', key_lot='owned-exit-lot')
        cursor = intent.cursor
        timestamp = cursor.bar_end.astimezone(timezone(timedelta(hours=8))).isoformat()
        legacy_key = f'auto:{cursor.strategy_id}:{cursor.version}:{cursor.instrument_id}:{cursor.interval}:{timestamp}:exit:{intent.lot_id}'
        self.assertNotEqual(legacy_key, intent.key)
        self.assertTrue(evaluation_key_matches(legacy_key, cursor))
        order = self.order(status=OrderStatus.ACCEPTED, key=legacy_key)
        self.set_intents(intent)
        compact_daily_state(self.engine)
        self.assertEqual(self.engine.state.automatic.daily.intents, (intent,))
        self.assertIn(order, self.engine.state.orders)

    def test_different_cursor_working_order_does_not_pin_unrelated_terminal_intent(self):
        intent = self.intent(phase='EXPIRED')
        variants = (
            replace(intent.cursor, strategy_id='other-strategy'),
            replace(intent.cursor, version=2),
            replace(intent.cursor, instrument_id='TWSE:2330'),
            replace(intent.cursor, bar_end=intent.cursor.bar_end - timedelta(days=1)),
        )
        for cursor in variants:
            with self.subTest(cursor=cursor):
                self.engine.state = replace(self.engine.state, orders=())
                key = evaluation_key(cursor)
                self.assertFalse(evaluation_key_matches(key, intent.cursor))
                order = self.order(status=OrderStatus.ACCEPTED, key=key)
                self.set_intents(intent)
                compact_daily_state(self.engine)
                self.assertEqual(self.engine.state.automatic.daily.intents, ())
                self.assertIn(order, self.engine.state.orders)

    def test_new_seal_stores_refs_and_digest_without_nested_quote_or_order_history(self):
        case = closing_fixtures.DailyClosesTests()
        case.setUp()
        close, quote = case.seal()
        self.assertEqual(close.closing_quotes, ())
        self.assertEqual(close.closing_quote_refs, (quote.instrument_id,))
        self.assertEqual(close.order_fingerprints, ())
        self.assertEqual((close.order_digest, close.order_count), order_digest(case.engine, close.account_ref, close.as_of))
        self.assertIs(case.engine.state.daily_closing_quotes[0].quote, quote)

    def test_250_verified_days_30_instruments_stays_bounded_below_wire_limit(self):
        engine = self.engine
        days = tuple(row.trade_date for row in engine.calendar.sessions if row.kind == 'DAY')
        start = days.index(self.day)
        sizes = []
        first_mark = None
        for day in days[start : start + 250]:
            engine.state = replace(engine.state, trading_day=day)
            engine.clock.value = self.session(day).closes_at
            close, mark = self.close(day)
            marks = tuple(
                replace(mark, quote=replace(mark.quote, instrument_id=f'TWSE:{index:04d}'), bar=replace(mark.bar, instrument_id=f'TWSE:{index:04d}'))
                for index in range(30)
            )
            first_mark = first_mark or marks[0]
            intents = tuple(
                replace(
                    self.intent(day=day),
                    cursor=replace(self.intent(day=day).cursor, instrument_id=row.quote.instrument_id),
                    instrument_id=row.quote.instrument_id,
                )
                for row in marks
            )
            close = replace(close, closing_quote_refs=tuple(row.quote.instrument_id for row in marks))
            daily = replace(engine.state.automatic.daily, intents=(*engine.state.automatic.daily.intents, *intents))
            engine._persist(
                'fixture_daily_signals_saved',
                replace(
                    engine.state,
                    daily_closing_quotes=(*engine.state.daily_closing_quotes, *marks),
                    daily_account_closes=(*engine.state.daily_account_closes, close),
                    automatic=replace(engine.state.automatic, daily=daily),
                ),
            )
            compact_daily_state(engine)
            sizes.append(len(dumps(engine.state).encode()))
        self.assertEqual(len(sizes), 250)
        self.assertLess(max(sizes), MAX_BYTES // 2)
        self.assertLessEqual(len(engine.state.daily_closing_quotes), DAILY_RETENTION_TRADE_DAYS * 30)
        self.assertLessEqual(len(engine.state.automatic.daily.intents), DAILY_RETENTION_TRADE_DAYS * 30)
        self.assertEqual(len(engine.state.daily_close_archives), 1)
        self.assertLess(max(sizes[-100:]) - min(sizes[-100:]), 1000)
        self.assertNotIn(first_mark, engine.state.daily_closing_quotes)
        self.assertTrue(any(first_mark in snapshot.daily_closing_quotes for _, snapshot in engine.events))
        self.assertEqual(loads(dumps(engine.state)), engine.state)


if __name__ == '__main__':
    unittest.main()
