"""Actual daily research, retained SIM owner and native SDK execution boundaries."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import unittest

import test_m2_automatic_engine as native_fixtures
from official_daily_fixtures import FakeOfficialDailySource, fake_official_history, install_fake_official_source, publish_fake_daily_close
from quantlab.trading.application import automatic
from quantlab.trading.application.daily_execution import continue_daily_session, dispatch_daily, observe_daily
from quantlab.trading.application.account_risk import seed_account_baseline
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import cursor
from quantlab.trading.application.preflight import record_preflight
from quantlab.trading.application.research import entry_signal, exit_signal
from quantlab.trading.application.workflows import run_research
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.auto_cycle import complete_buckets
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingKind, Market, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.strategy import CompletedBar, StrategyParameters
from quantlab.trading.runtime.preflight import sinopac_preflight_facts

D = Decimal
SIM = Environment.BROKER_SIMULATION


class InjectedCrash(BaseException):
    """Process death after a successful durable append, before SDK admission."""


class CrashAfterDailyClaim:
    def __init__(self, journal):
        self.journal, self.crashed = journal, False

    def append(self, kind, payload, now, *, expected_sequence):
        event = self.journal.append(kind, payload, now, expected_sequence=expected_sequence)
        if kind == 'daily_dispatch_claimed' and not self.crashed:
            self.crashed = True
            raise InjectedCrash()
        return event

    def replay(self):
        return self.journal.replay()

    def heartbeat(self, now):
        return self.journal.heartbeat(now)


class DailyNativeFixture:
    """Compose the existing native fixture without importing its TestCase globally.

    Capabilities and quotes are explicit offline input tapes. Reconciliation
    always uses the actual fake SDK observation and ManualTradingService.adopt.
    Only initial zero genesis is seeded; day rollover never rewrites baseline,
    stopped/reconciled/automatic pause state or daily loss latches.
    """

    def __init__(self, add_cleanup, *, stock=True):
        self.base = native_fixtures.AutomaticEngineTests()
        add_cleanup(self.base.doCleanups)
        self.base.setUp()
        if stock:
            self.base.use_stock_fixture()
        self.engine, self.clock = self.base.engine, self.base.clock
        self.bundle, self.runtime = self.base.bundle, self.base.runtime
        self.case = self.base.case
        self.spec = self.base.stock if stock else self.case.spec
        self.account_ref = 'stock-alias' if stock else 'future-alias'
        self.signal_day = self.engine.state.trading_day
        self.initial_native_orders = self.placed()
        self.reference = ''

    def placed(self):
        return self.base.placed()

    def deploy(self, *, entry_amount=D('25000'), allocation=None, interval='1d', entry_below=None, exit_below=None, legacy=False):
        capital = next(book.capital for book in self.engine.state.manual_books if book.account_ref == self.account_ref)
        form = StrategyForm(
            'daily-next-session-native',
            self.spec.market,
            HoldingKind.CUSTOM,
            0,
            10,
            Side.BUY,
            self.spec.instrument_id,
            self.account_ref,
            SIM,
            capital if allocation is None else allocation,
            D('.02'),
            'BUY_AND_HOLD',
        )
        parameters = None if legacy else StrategyParameters(interval, D('.001'), entry_amount)
        if exit_below is not None:
            definition = {
                'schema_version': 2,
                'strategy_id': 'daily-native-exit',
                'version': 1,
                'market': self.spec.market.value,
                'holding_policy': {'kind': HoldingKind.CUSTOM.value, 'min_days': 0, 'max_days': 10, 'night_enabled': False, 'expiry_action': 'EXIT'},
                'bar_interval': interval,
                'direction': 'LONG_ONLY',
                'entry': [
                    {'field': 'close', 'operator': 'LT' if entry_below is not None else 'GT', 'value': str(entry_below) if entry_below is not None else '0'}
                ],
                'exit': [{'field': 'close', 'operator': 'LT', 'value': str(exit_below)}],
                'cost_version': self.engine.fees.version,
                'risk_ref': self.engine.risk().policy.version,
            }
            form = replace(form, rule_kind='STRUCTURED_JSON', draft_json=json.dumps(definition))
        reference = self.engine.create_strategy(form, parameters)
        if self.spec.market is Market.STOCK and interval == '1d' and not legacy:
            # Explicit synthetic official-input tape; generic history alone is not source evidence.
            historical = tuple(bar for bar in self.engine.history[self.spec.instrument_id] if bar.ended_at.date() < self.clock.now().date())
            install_fake_official_source(self.engine, fake_official_history(self.spec.instrument_id, historical, self.clock.now()))
        with self.engine.lock:
            self.engine.validate_strategy(reference)
            run_research(self.engine, reference, self.engine.history[self.spec.instrument_id])
            self.engine.deploy(reference)
            for account in self.engine.gateways:
                self.engine._persist(
                    'daily_fixture_initial_zero_genesis', replace(self.engine.state, account_daily_baselines=seed_account_baseline(self.engine, account))
                )
                record_preflight(self.engine, account, sinopac_preflight_facts(self.bundle, account))
        self.reference = reference
        return self.engine.strategy(reference)

    def start(self):
        self.engine.automatic_owner_stamp = self.runtime.owner_stamp
        automatic.resume_automatic(self.engine)

    def session(self, day=None, spec=None):
        return calendar_for_instrument(self.engine.calendar, spec or self.spec).day_session(day or self.signal_day)

    def next_session(self):
        calendar = calendar_for_instrument(self.engine.calendar, self.spec)
        return calendar.day_session(calendar.advance(self.signal_day, 1))

    def minutes(self, *, day=None, price=D('20'), spec=None):
        spec = spec or self.spec
        session = self.session(day, spec)
        return tuple(
            LiveBar(spec.instrument_id, start, start + timedelta(minutes=1), session.trade_date, 'DAY', price, price, price, price, 1000, final=True)
            for offset in range((session.closes_at - session.opens_at) // timedelta(minutes=1))
            for start in (session.opens_at + timedelta(minutes=offset),)
        )

    def renew_capabilities(self, at):
        # Fake resource-query input, not a preflight PASS or broker funds report.
        for reference, capability in tuple(self.case.adapter.capabilities.items()):
            self.case.adapter.capabilities[reference] = replace(capability, checked_at=at, expires_at=at + timedelta(hours=8))

    def quote(self, spec, at, price):
        self.clock.value = at
        previous = self.engine.quotes[spec.instrument_id]
        tick = D('.01') if spec.market is Market.STOCK else D('1')
        self.engine.quote(replace(previous, bid=price - tick, ask=price, last=price, source_at=at, received_at=at, trade_date=at.date(), source='SHIOAJI'))

    def adopt(self, at):
        self.clock.value = at
        rows = tuple(self.case.adapter.observe_manual(reference, cursor(self.engine, reference)) for reference in self.engine.gateways)
        self.case.service.adopt(rows)

    def refresh(self, at, *, stock_price=D('20'), futures_price=D('25000'), renew=True):
        if renew:
            self.renew_capabilities(at)
        for spec in self.engine.catalog.instruments:
            self.quote(spec, at, stock_price if spec.market is Market.STOCK else futures_price)
        self.adopt(at)
        if self.spec.market is Market.STOCK and getattr(self.engine, 'daily_signal_source', None) is not None:
            session = next(
                (row for row in calendar_for_instrument(self.engine.calendar, self.spec).sessions if row.kind == 'DAY' and row.trade_date == at.date()), None
            )
            if session is not None and at >= session.closes_at:
                self.publish_official_close(day=session.trade_date, price=stock_price)

    def publish_official_close(self, *, day=None, price=D('20')):
        if self.spec.market is Market.STOCK and isinstance(getattr(self.engine, 'daily_signal_source', None), FakeOfficialDailySource):
            publish_fake_daily_close(self.engine, self.spec.instrument_id, day or self.signal_day, price)

    def close(self, *, day=None, price=None):
        session = self.session(day)
        price = price if price is not None else D('20') if self.spec.market is Market.STOCK else D('25000')
        self.refresh(
            session.closes_at - timedelta(seconds=1),
            stock_price=price if self.spec.market is Market.STOCK else D('20'),
            futures_price=price if self.spec.market is not Market.STOCK else D('25000'),
        )
        self.clock.value = session.closes_at
        self.publish_official_close(day=session.trade_date, price=price)
        minutes = self.minutes(day=day, price=price)
        daily = complete_buckets(minutes, '1d', session, self.clock.now())
        observe_daily(self.engine, minutes)
        self.adopt(session.closes_at + timedelta(seconds=1))
        observe_daily(self.engine, ())
        return daily

    def close_other_accounts(self):
        for spec in sorted(self.engine.catalog.instruments, key=lambda row: self.session(spec=row).closes_at):
            if spec.instrument_id == self.spec.instrument_id:
                continue
            session = self.session(spec=spec)
            self.quote(spec, session.closes_at - timedelta(seconds=1), D('20') if spec.market is Market.STOCK else D('25000'))
            self.adopt(self.clock.now())
            self.clock.value = session.closes_at
            observe_daily(self.engine, self.minutes(spec=spec, price=D('20') if spec.market is Market.STOCK else D('25000')))
            self.adopt(session.closes_at + timedelta(seconds=1))
            observe_daily(self.engine, ())

    def next_day(self, *, stock_price=D('12'), futures_price=D('25000'), session=None):
        session = session or self.next_session()
        self.refresh(session.opens_at + timedelta(minutes=1), stock_price=stock_price, futures_price=futures_price)
        facts = tuple((reference, sinopac_preflight_facts(self.bundle, reference)) for reference in sorted(self.engine.gateways))
        continue_daily_session(self.engine, facts)


class DailyNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = DailyNativeFixture(self.addCleanup)

    def test_daily_strategy_uses_real_training_and_deployment_without_submitting(self):
        fixture = self.fixture
        before = fixture.placed()
        record = fixture.deploy()
        self.assertEqual((record.parameters.bar_interval, record.state), ('1d', 'ACTIVE'))
        self.assertTrue(record.evidence_hash)
        self.assertTrue(record.research_blob)
        self.assertEqual(record.evidence, 'OFFICIAL_DAILY_TRAINING')
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())

    def test_legacy_daily_training_keeps_exact_synthetic_evidence_without_official_source(self):
        fixture = self.fixture
        before = fixture.placed()
        record = fixture.deploy(legacy=True)
        self.assertIsNone(record.parameters)
        self.assertEqual(record.evidence, 'LOCAL_SYNTHETIC_TRAINING')
        self.assertIsNone(fixture.engine.daily_signal_source)
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())

    def test_verified_close_saves_next_session_signal_without_reserving_or_sending(self):
        fixture = self.fixture
        record = fixture.deploy()
        fixture.start()
        before = fixture.placed()
        orders, books = fixture.engine.state.orders, fixture.engine.state.manual_books
        bars = fixture.close()
        intents = fixture.engine.state.automatic.daily.intents
        self.assertEqual(len(bars), 1)
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        target = fixture.next_session()
        self.assertEqual((intent.cursor.strategy_id, intent.phase, intent.action), (record.strategy_id, 'READY', 'ENTRY'))
        self.assertEqual((intent.target_trade_date, intent.not_before, intent.deadline), (target.trade_date, target.opens_at, target.closes_at))
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(fixture.engine.state.orders, orders)
        self.assertEqual(fixture.engine.state.manual_books, books)
        observe_daily(fixture.engine, fixture.minutes())
        self.assertEqual(fixture.engine.state.automatic.daily.intents, intents)
        dispatch_daily(fixture.engine)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertEqual(fixture.placed(), before)

    def test_next_verified_session_sizes_from_current_quote_and_dispatches_once(self):
        fixture = self.fixture
        record = fixture.deploy()
        fixture.start()
        fixture.close()
        fixture.close_other_accounts()
        intent = fixture.engine.state.automatic.daily.intents[0]
        before = fixture.placed()
        fixture.next_day(stock_price=D('12'))
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before + 1, fixture.engine.state.automatic)
        order = fixture.engine.state.orders[-1]
        self.assertEqual((order.plan.strategy_id, order.key, order.plan.limit_price, order.plan.quantity), (record.strategy_id, intent.key, D('12'), 2000))
        self.assertEqual(fixture.engine.state.automatic.daily.intents[0].phase, 'DISPATCHED')
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before + 1)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)
        self.assertEqual(fixture.case.native.financial_queries, 0)

    def ready_next_day(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        fixture.close()
        fixture.close_other_accounts()
        fixture.next_day()
        return fixture

    def assert_no_dispatch(self, fixture, code):
        before = fixture.placed()
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before)
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertIn(code, fixture.engine.state.automatic.reasons)

    def test_current_quote_below_one_board_lot_cannot_reuse_close_size(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        fixture.close()
        fixture.close_other_accounts()
        fixture.next_day(stock_price=D('26'))
        before = fixture.placed()
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before)
        intent = fixture.engine.state.automatic.daily.intents[0]
        self.assertEqual(intent.phase, 'KNOWN_NO_ORDER')
        self.assertFalse(intent.order_id)
        self.assertFalse(any(order.key == intent.key for order in fixture.engine.state.orders))

    def test_stale_current_quote_blocks_saved_daily_entry(self):
        fixture = self.ready_next_day()
        fixture.clock.value += timedelta(seconds=11)
        fixture.adopt(fixture.clock.now())
        self.assert_no_dispatch(fixture, 'preflight_market')

    def test_stale_current_observation_blocks_saved_daily_entry(self):
        fixture = self.ready_next_day()
        fixture.clock.value += timedelta(seconds=31)
        for spec in fixture.engine.catalog.instruments:
            fixture.quote(spec, fixture.clock.now(), D('12') if spec.market is Market.STOCK else D('25000'))
        self.assert_no_dispatch(fixture, 'preflight_reconciliation')

    def test_expired_current_capability_blocks_saved_daily_entry(self):
        fixture = self.ready_next_day()
        capability = fixture.case.adapter.capabilities[fixture.account_ref]
        fixture.case.adapter.capabilities[fixture.account_ref] = replace(
            capability, checked_at=fixture.clock.now() - timedelta(minutes=1), expires_at=fixture.clock.now()
        )
        self.assert_no_dispatch(fixture, 'capability_missing')

    def test_owner_change_revokes_saved_daily_entry_before_native_call(self):
        fixture = self.ready_next_day()
        fixture.base.owner_view = replace(fixture.base.owner_view, revision=fixture.base.owner_view.revision + 1)
        before = fixture.placed()
        with self.assertRaises(DomainError):
            dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before)

    def test_direct_submit_cannot_reuse_ready_daily_identity_without_durable_claim(self):
        fixture = self.ready_next_day()
        record = fixture.engine.strategy(fixture.reference)
        intent = fixture.engine.state.automatic.daily.intents[0]
        plan = replace(fixture.base.direct_plan(record, stock=True), limit_price=D('12'), stop_price=D('11.98'))
        before = tuple(fixture.case.native._seen)
        with self.assertRaises(DomainError) as raised:
            fixture.engine.submit(plan, record.policy, intent.key)
        self.assertEqual(raised.exception.code, 'daily_signal_not_authorized')
        self.assertEqual(tuple(fixture.case.native._seen), before)
        self.assertEqual(fixture.engine.state.automatic.daily.intents[0].phase, 'READY')

    def test_unknown_native_daily_submit_keeps_reservation_and_never_resends(self):
        fixture = self.ready_next_day()
        fixture.case.native.place_mode = 'TIMEOUT'
        before = fixture.placed()
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before + 1)
        order = fixture.engine.state.orders[-1]
        intent = fixture.engine.state.automatic.daily.intents[0]
        self.assertEqual((intent.phase, intent.order_id), ('UNKNOWN', order.order_id))
        self.assertGreater(order.reservation.cash, D('0'))
        self.assertTrue(fixture.engine.state.automatic.auto_paused)
        self.assertFalse(fixture.engine.state.automatic.daily.authorized_run)
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before + 1)
        self.assertEqual(fixture.engine.state.orders[-1].reservation, order.reservation)

    def test_actual_restart_preserves_saved_signal_but_revokes_dispatch_authority(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        fixture.close()
        old = fixture.engine
        intents = old.state.automatic.daily.intents
        before = fixture.placed()
        restarted = TradingEngine(
            old.journal,
            fixture.clock,
            old.calendar,
            old.catalog,
            old.gateways,
            configuration=old.configuration,
            ownership_clock=fixture.clock.now,
            source_profile=old.profile,
            fees=old.fees,
            historical_bars=old.history,
            daily_signal_source=old.daily_signal_source,
        )
        self.assertEqual(restarted.state.automatic.daily.intents, intents)
        self.assertTrue(restarted.state.automatic.auto_paused)
        self.assertTrue(restarted.state.stopped)
        self.assertFalse(restarted.state.automatic.daily.authorized_run)
        self.assertIn('program_restarted', restarted.state.automatic.reasons)
        dispatch_daily(restarted)
        self.assertEqual(fixture.placed(), before)

    def test_crash_after_durable_claim_restarts_unknown_without_native_replay(self):
        fixture = self.ready_next_day()
        old = fixture.engine
        old.journal = CrashAfterDailyClaim(old.journal)
        before = fixture.placed()
        with self.assertRaises(InjectedCrash):
            dispatch_daily(old)
        self.assertEqual(fixture.placed(), before)
        restarted = TradingEngine(
            old.journal,
            fixture.clock,
            old.calendar,
            old.catalog,
            old.gateways,
            configuration=old.configuration,
            ownership_clock=fixture.clock.now,
            source_profile=old.profile,
            fees=old.fees,
            historical_bars=old.history,
            daily_signal_source=old.daily_signal_source,
        )
        intent = restarted.state.automatic.daily.intents[0]
        self.assertEqual((intent.phase, intent.code), ('UNKNOWN', 'daily_signal_unresolved'))
        self.assertFalse(intent.order_id)
        self.assertFalse(restarted.state.automatic.daily.authorized_run)
        dispatch_daily(restarted)
        self.assertEqual(fixture.placed(), before)

    def test_saved_signal_expires_at_target_close_without_catch_up_order(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.start()
        fixture.close()
        before = tuple(fixture.case.native._seen)
        fixture.clock.value = fixture.next_session().closes_at
        dispatch_daily(fixture.engine)
        intent = fixture.engine.state.automatic.daily.intents[0]
        self.assertEqual((intent.phase, intent.code, intent.order_id), ('EXPIRED', 'daily_signal_expired', ''))
        fixture.clock.value += timedelta(days=1)
        dispatch_daily(fixture.engine)
        self.assertEqual(tuple(fixture.case.native._seen), before)

    def test_owned_daily_exit_is_saved_at_close_then_uses_next_day_quote_once(self):
        fixture = DailyNativeFixture(self.addCleanup, stock=False)
        self.fixture = fixture
        record = fixture.deploy(entry_amount=D('40000'), entry_below=D('25005'), exit_below=D('24999'))
        fixture.start()
        fixture.close()
        fixture.next_day()
        dispatch_daily(fixture.engine)
        entry = fixture.engine.state.orders[-1]
        self.assertFalse(entry.plan.reduce_only)
        fixture.case.native.fill(fixture.case.native.trades[-1], 1, D('25000'))
        fixture.adopt(fixture.clock.now())
        lot = next(row for row in fixture.engine.state.positions if row.strategy_id == record.strategy_id and row.quantity)
        day = fixture.engine.state.trading_day
        before, reservations = fixture.placed(), fixture.engine.reservations()
        fixture.close(day=day, price=D('24998'))
        saved = [row for row in fixture.engine.state.automatic.daily.intents if row.action == 'EXIT']
        self.assertEqual(len(saved), 1)
        intent = saved[0]
        self.assertEqual((intent.lot_id, intent.phase), (lot.lot_id, 'READY'))
        self.assertTrue(intent.key.endswith(':exit:' + lot.lot_id))
        self.assertEqual(fixture.placed(), before)
        self.assertEqual(fixture.engine.reservations(), reservations)
        calendar = calendar_for_instrument(fixture.engine.calendar, fixture.spec)
        target = calendar.day_session(calendar.advance(day, 1))
        fixture.next_day(session=target, futures_price=D('25010'))
        now = fixture.clock.now()
        current = (CompletedBar(now - timedelta(minutes=1), now, now, D('25010'), D('25010'), 1),)
        self.assertFalse(entry_signal(record, current, now))
        self.assertFalse(exit_signal(record, current, now))
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before + 1, fixture.engine.state.automatic)
        exit_order = fixture.engine.state.orders[-1]
        self.assertEqual((exit_order.key, exit_order.plan.exit_lot_id), (intent.key, lot.lot_id))
        self.assertTrue(exit_order.plan.reduce_only)
        self.assertEqual((exit_order.plan.quantity, exit_order.plan.limit_price), (1, D('25009')))
        dispatch_daily(fixture.engine)
        self.assertEqual(fixture.placed(), before + 1)
        self.assertEqual(next(row.phase for row in fixture.engine.state.automatic.daily.intents if row.key == intent.key), 'DISPATCHED')
        self.assertEqual(fixture.case.native.financial_queries, 0)

    def test_daily_observe_dispatch_and_continuation_reject_live_before_native_call(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.engine.configuration = replace(fixture.engine.configuration, environment=Environment.LIVE)
        before = tuple(fixture.case.native._seen)
        for action in (
            lambda: observe_daily(fixture.engine, fixture.minutes()),
            lambda: dispatch_daily(fixture.engine),
            lambda: continue_daily_session(fixture.engine, ()),
        ):
            with self.subTest(action=action):
                with self.assertRaises(DomainError) as raised:
                    action()
                self.assertEqual(raised.exception.code, 'production_orders_disabled')
                self.assertEqual(tuple(fixture.case.native._seen), before)


if __name__ == '__main__':
    unittest.main()
