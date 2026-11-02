"""Actual engine, native SDK double, shared virtual book, and automatic wiring."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from threading import Lock, RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_manual_trading as manual

from quantlab.trading.application import automatic
from quantlab.trading.application.account_risk import seed_account_baseline
from quantlab.trading.application.contracts import SettingsForm, StrategyForm, UiAction, UiCommand
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.events import cursor
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualOrderForm
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.preflight import PreflightFacts, record_preflight
from quantlab.trading.application.sinopac_contracts import SinopacAccountView, SinopacConnectionView
from quantlab.trading.application.workflows import run_research
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingKind, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.risk import RiskService
from quantlab.trading.domain.strategy import StrategyParameters
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.automatic import AutomaticRuntime
from quantlab.trading.runtime.build import synthetic_history
from quantlab.trading.runtime.manual_trading import ManualExecutionGateway
from quantlab.trading.runtime.provenance import compute_profile

SIM = Environment.BROKER_SIMULATION


class AutomaticEngineTests(unittest.TestCase):
    def setUp(self):
        self.case = case = manual.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        case.confirm_test()
        self.configure(case)

    def configure(self, case):
        self.engine, self.clock = case.engine, case.clock
        effective = self.engine.calendar.sessions[0].opens_at
        self.engine.catalog = Catalog(tuple(replace(spec, effective_at=effective) for spec in self.engine.catalog.instruments))
        case.spec = self.engine.catalog.resolve(case.spec.instrument_id)
        if hasattr(self, 'stock'):
            self.stock = self.engine.catalog.resolve(self.stock.instrument_id)
        for ref, binding in case.adapter.bindings.items():
            case.adapter.bindings[ref] = replace(binding, spec=self.engine.catalog.resolve(ref))
        for ref, capability in case.adapter.capabilities.items():
            case.adapter.capabilities[ref] = replace(capability, expires_at=self.clock.now() + timedelta(hours=8))
        self.engine.profile = compute_profile()
        self.engine.history = synthetic_history(self.engine.catalog, self.engine.calendar)
        self.engine.quotes = {key: replace(quote, source='SHIOAJI') for key, quote in self.engine.quotes.items()}
        gateway = ManualExecutionGateway(case.adapter, Lock())
        self.engine.gateways = {ref: gateway for ref in self.engine.gateways}
        accounts = tuple(SinopacAccountView(ref, '***' + ref, next(iter(case.adapter.capabilities[ref].markets)), True, True) for ref in self.engine.gateways)
        self.owner_view = SinopacConnectionView(environment=SIM, phase='CONNECTED', generation=case.scope.connection_generation, revision=3, accounts=accounts)
        selected = tuple(sorted(self.engine.gateways))
        owner = SimpleNamespace(lock=RLock(), snapshot=lambda: self.owner_view, selected=selected, shared=case.owner, query_ready=True)
        runtime = SimpleNamespace(owner=owner, stamp=(self.owner_view.generation, 3, selected, case.owner), error='')
        self.bundle = SimpleNamespace(
            engine=self.engine,
            sinopac_connection=owner,
            manual_runtime=runtime,
            launch=SimpleNamespace(environment=SIM),
            closing=False,
            resources_closed=False,
            control_failed=False,
        )
        self.runtime = AutomaticRuntime(self.bundle)
        self.engine.automatic_observation_validator = self.runtime.validate_observation
        self.engine.automatic_entry_validator = self.runtime.validate_entry
        self.engine.automatic_submission_guard = self.runtime.submission_guard

    def deploy(self, *, stock=False, intraday=False, activate=True):
        spec = self.stock if stock else self.case.spec
        account = 'stock-alias' if stock else 'future-alias'
        kind = HoldingKind.INTRADAY if intraday else HoldingKind.CUSTOM
        allocation = next(book.capital for book in self.engine.state.manual_books if book.account_ref == account)
        form = StrategyForm(
            'actual-native-auto', spec.market, kind, 0, 0 if intraday else 10, Side.BUY, spec.instrument_id, account, SIM, allocation, D('.02'), 'BUY_AND_HOLD'
        )
        parameters = StrategyParameters(
            '1m', D('.001'), D('25000') if stock else allocation, stock_intraday_enabled=intraday and stock, stock_intraday_confirmed=intraday and stock
        )
        reference = self.engine.create_strategy(form, parameters)
        with self.engine.lock:
            self.engine.validate_strategy(reference)
            run_research(self.engine, reference, self.engine.history[spec.instrument_id])
            if activate:
                self.engine.deploy(reference)
            for ref in self.engine.gateways:
                self.engine._persist('offline_zero_genesis_proof', replace(self.engine.state, account_daily_baselines=seed_account_baseline(self.engine, ref)))
                record_preflight(self.engine, ref, PreflightFacts(True, True, True, None, True, True, True))
        self.reference = reference
        return self.engine.strategy(reference)

    def refresh(self):
        engine = self.engine
        for quote in tuple(engine.quotes.values()):
            engine.quote(replace(quote, source_at=self.clock.now(), received_at=self.clock.now(), trade_date=self.clock.now().date()))
        observations = tuple(self.case.adapter.observe_manual(ref, cursor(engine, ref)) for ref in engine.gateways)
        self.case.service.adopt(observations)

    def at(self, hour, minute=0, second=0):
        session = calendar_for_instrument(self.engine.calendar, self.case.spec).day_session(self.engine.state.trading_day)
        self.clock.value = session.opens_at.replace(hour=hour, minute=minute, second=second)
        self.refresh()

    def bar(self, *, stock=False, final=True):
        spec = self.stock if stock else self.case.spec
        end = self.clock.now().replace(second=0, microsecond=0)
        price = D('20') if stock else D('25000')
        return LiveBar(spec.instrument_id, end - timedelta(minutes=1), end, end.date(), 'DAY', price, price, price, price, 1000, final=final)

    def placed(self):
        return sum(row[0] == 'place_order' for row in self.case.native._seen)

    def start(self):
        automatic.resume_automatic(self.engine)

    def direct_plan(self, record, *, stock=False):
        spec = self.stock if stock else self.case.spec
        price = D('20') if stock else D('25000')
        return OrderPlan(
            'explicit-native-test',
            record.form.account_ref,
            SIM,
            spec.instrument_id,
            record.strategy_id,
            record.version,
            Side.BUY,
            1000 if stock else 1,
            spec.unit,
            price,
            D('19.98') if stock else D('24975'),
            False,
            self.clock.now(),
            self.clock.now() + timedelta(seconds=30),
            self.engine.state.version,
        )

    def use_stock_fixture(self):
        fixture = manual.ManualStockTests()
        fixture.setUp()
        self.case, self.stock = fixture.case, fixture.stock
        self.addCleanup(self.case.owner.close)
        self.configure(self.case)

    def open_and_fill(self, *, stock=False, intraday=False):
        record = self.deploy(stock=stock, intraday=intraday)
        self.start()
        self.at(9, 1)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(stock=stock),))
        self.assertEqual(self.placed(), before + 1, self.engine.state.automatic)
        self.case.native.fill(self.case.native.trades[-1], 1, D('20') if stock else D('25000'))
        self.refresh()
        return record, self.engine.state.positions[-1]

    def test_completed_bar_reaches_actual_native_sdk_once(self):
        record = self.deploy()
        self.start()
        self.at(9, 1)
        before = self.placed()
        bar = self.bar()
        automatic.on_completed_bars(self.engine, (bar,))
        self.assertEqual(self.placed(), before + 1, self.engine.state.automatic)
        order = self.engine.state.orders[-1]
        self.assertEqual((order.plan.strategy_id, order.plan.quantity, order.status), (record.strategy_id, 1, OrderStatus.ACCEPTED))
        self.assertEqual(self.case.native.trades[-1].order.account, self.case.native.account)
        automatic.on_completed_bars(self.engine, (bar,))
        self.assertEqual(self.placed(), before + 1)
        self.assertEqual(len(self.engine.state.automatic.evaluations), 1)
        self.assertEqual(self.case.native.financial_queries, 0)

    def test_forming_bar_cannot_reach_native_sdk_or_claim_an_evaluation(self):
        self.deploy()
        self.start()
        self.at(9, 1)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(final=False),))
        self.assertEqual(self.placed(), before)
        self.assertEqual(self.engine.state.automatic.evaluations, ())
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before + 1)

    def test_changed_owner_generation_stops_actual_automatic_submission(self):
        self.deploy()
        self.start()
        self.at(9, 1)
        before = self.placed()
        self.owner_view = replace(self.owner_view, generation='changed-login')
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertIn('preflight_permission', self.engine.state.automatic.reasons)

    def test_missing_account_day_baseline_stops_actual_automatic_submission(self):
        self.deploy()
        self.start()
        self.at(9, 1)
        self.engine._persist('offline_missing_close', replace(self.engine.state, account_daily_baselines=()))
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before)
        self.assertIn('account_daily_baseline_required', self.engine.state.automatic.reasons)

    def test_actual_manual_resume_cannot_clear_automatic_pause(self):
        self.deploy()
        self.start()
        automatic.pause_automatic(self.engine, 'disconnected')
        receipt = self.case.service.execute(self.case.command(UiAction.RESUME, manual_book=ManualBookForm(self.case.scope, D('40000'), True)))
        self.assertTrue(receipt.accepted, receipt)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        strategy_view = next(
            row for row in LocalFacade(self.engine).snapshot().strategies if row.strategy_id == self.engine.strategy(self.reference).strategy_id
        )
        self.assertEqual(strategy_view.activity_state, 'PAUSED')
        record = self.engine.strategy(self.reference)
        before = self.placed()
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'paused-direct-native-entry')
        self.assertEqual(rejected.exception.code, 'automatic_paused')
        self.assertEqual(self.placed(), before)
        self.at(9, 1)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before)

    def test_automatic_held_margin_and_manual_order_share_one_confirmed_cash_pool(self):
        self.open_and_fill()
        before = self.placed()
        form, _ = self.case.normal('manual-after-auto-fill')
        receipt = self.case.service.execute(self.case.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertFalse(receipt.accepted)
        self.assertEqual(self.placed(), before)
        self.assertEqual(self.engine.account('future-alias').margin_used, D('35050'))

    def test_manual_held_margin_and_automatic_order_share_one_confirmed_cash_pool(self):
        self.deploy()
        self.start()
        form, _ = self.case.normal('manual-before-auto-fill')
        receipt = self.case.service.execute(self.case.command(UiAction.SUBMIT_MANUAL, manual_order=form))
        self.assertTrue(receipt.accepted, receipt)
        self.case.native.fill(self.case.native.trades[-1], 1, D('25000'))
        self.refresh()
        self.at(9, 1)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertEqual(self.engine.account('future-alias').margin_used, D('35050'))

    def test_tmf_custom_can_enter_at_1335_after_legacy_manual_session_closes(self):
        self.deploy()
        self.at(13, 34)
        self.start()
        self.at(13, 35)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before + 1, self.engine.state.automatic)
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.ACCEPTED)
        self.assertEqual(self.engine.state.trading_day, self.clock.now().date())

    def test_forced_exit_waits_for_cancel_evidence_then_retries_with_new_key(self):
        _, lot = self.open_and_fill(intraday=True)
        self.at(13, 35)
        before = self.placed()
        automatic.pump_automatic(self.engine)
        first = self.engine.state.orders[-1]
        self.assertEqual((first.key, first.plan.exit_lot_id), (f'forced-exit:{lot.lot_id}:1', lot.lot_id))
        self.assertEqual(self.placed(), before + 1)
        automatic.pump_automatic(self.engine)
        self.assertEqual(self.placed(), before + 1)
        self.at(13, 35, 30)
        automatic.pump_automatic(self.engine)
        self.assertEqual(self.placed(), before + 1)
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.CANCEL_PENDING)
        self.refresh()
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.CANCELED)
        automatic.pump_automatic(self.engine)
        self.assertEqual(self.placed(), before + 2, self.engine.state.automatic)
        self.assertEqual(self.engine.state.orders[-1].key, f'forced-exit:{lot.lot_id}:2')

    def test_unknown_forced_exit_keeps_owned_risk_and_never_resends_same_key(self):
        _, lot = self.open_and_fill(intraday=True)
        entry_risk = next(row.reservation.risk for row in self.engine.state.orders if row.order_id == lot.lot_id)
        self.at(13, 35)
        self.case.native.place_mode = 'TIMEOUT'
        before = self.placed()
        automatic.pump_automatic(self.engine)
        unknown = self.engine.state.orders[-1]
        self.assertEqual(unknown.status, OrderStatus.UNKNOWN)
        self.assertEqual(self.placed(), before + 1)
        self.assertEqual(self.engine.exit_lot(lot.lot_id, protective=True, key=unknown.key), unknown.order_id)
        self.clock.value += timedelta(seconds=30)
        automatic.pump_automatic(self.engine)
        self.assertEqual(self.placed(), before + 1)
        self.assertEqual(next(row.reservation.risk for row in self.engine.state.orders if row.order_id == lot.lot_id), entry_risk)
        self.assertEqual(self.engine.state.positions[-1].quantity, 1)

    def test_live_all_new_paths_refuse_before_native_queries_or_orders(self):
        _, lot = self.open_and_fill(intraday=True)
        self.assertIsNotNone(self.engine.exit_lot(lot.lot_id, protective=True, key='known-force-before-live'))
        plan = self.engine.state.orders[-1].plan
        self.engine.configuration = replace(self.engine.configuration, environment=Environment.LIVE)
        before = len(self.case.native._seen)
        operations = (
            lambda: automatic.resume_automatic(self.engine),
            lambda: automatic.pause_automatic(self.engine, 'stop'),
            lambda: automatic.reconcile_automatic(self.engine),
            lambda: automatic.on_completed_bars(self.engine, (self.bar(),)),
            lambda: automatic.pump_automatic(self.engine),
            lambda: self.engine.submit(plan, lot.policy, 'live-retry'),
            lambda: self.engine.exit_lot(lot.lot_id, protective=True, key='live-force'),
            lambda: self.engine.exit_lot(lot.lot_id, protective=True, key='known-force-before-live'),
        )
        for index, operation in enumerate(operations):
            with self.subTest(path=index), self.assertRaises(DomainError) as rejected:
                operation()
            self.assertEqual(rejected.exception.code, 'production_orders_disabled')
        self.assertEqual(len(self.case.native._seen), before)

    def test_stock_typed_fill_has_conservative_t_plus_two_and_no_same_day_exit(self):
        self.use_stock_fixture()
        _, lot = self.open_and_fill(stock=True)
        acquisition = next(row for row in self.engine.state.manual_acquisitions if row.lot_id == lot.lot_id)
        self.assertEqual(acquisition.available_on, self.engine.calendar.advance(self.engine.state.trading_day, 2))
        self.assertEqual(lot.sellable_quantity, 0)
        before = self.placed()
        self.assertIsNone(self.engine.exit_lot(lot.lot_id, protective=True))
        self.assertEqual(self.placed(), before)
        self.clock.value = self.engine.calendar.day_session(acquisition.available_on).opens_at + timedelta(minutes=1)
        for ref, proof in self.case.adapter.capabilities.items():
            self.case.adapter.capabilities[ref] = replace(proof, checked_at=self.clock.now(), expires_at=self.clock.now() + timedelta(hours=8))
        self.refresh()
        self.assertEqual(self.engine.state.positions[-1].sellable_quantity, 1000)
        self.assertIsNotNone(self.engine.exit_lot(lot.lot_id, protective=True))
        self.assertEqual(self.placed(), before + 1)

    def test_stock_intraday_checkboxes_do_not_invent_account_day_trade_permission(self):
        self.use_stock_fixture()
        self.engine.automatic_capabilities = {'stock-alias': self.case.adapter.capabilities['stock-alias']}
        with self.assertRaises(DomainError) as rejected:
            self.deploy(stock=True, intraday=True)
        self.assertEqual(rejected.exception.code, 'intraday_eligibility_missing')

    def test_stock_intraday_explicit_current_permission_allows_owned_same_day_exit(self):
        self.use_stock_fixture()
        proof = self.case.adapter.capabilities['stock-alias']
        self.engine.automatic_capabilities = {'stock-alias': replace(proof, day_trade=True)}
        _, lot = self.open_and_fill(stock=True, intraday=True)
        self.assertEqual(lot.sellable_quantity, 1000)
        before = self.placed()
        self.assertIsNotNone(self.engine.exit_lot(lot.lot_id, protective=True))
        self.assertEqual(self.placed(), before + 1)

    def test_stock_intraday_expired_permission_cannot_be_reused_at_deploy(self):
        self.use_stock_fixture()
        proof = self.case.adapter.capabilities['stock-alias']
        self.engine.automatic_capabilities = {
            'stock-alias': replace(proof, day_trade=True, checked_at=self.clock.now() - timedelta(hours=1), expires_at=self.clock.now())
        }
        with self.assertRaises(DomainError) as rejected:
            self.deploy(stock=True, intraday=True)
        self.assertEqual(rejected.exception.code, 'intraday_eligibility_missing')

    def test_actual_restart_keeps_evaluation_claim_and_requires_explicit_automatic_resume(self):
        self.deploy()
        self.start()
        self.at(9, 1)
        automatic.on_completed_bars(self.engine, (self.bar(),))
        cursors = self.engine.state.automatic.cursors
        old = self.engine
        before = self.placed()
        restarted = TradingEngine(
            old.journal,
            self.clock,
            old.calendar,
            old.catalog,
            old.gateways,
            configuration=old.configuration,
            ownership_clock=self.clock.now,
            source_profile=old.profile,
            fees=old.fees,
            historical_bars=old.history,
        )
        self.assertTrue(restarted.state.automatic.auto_paused)
        self.assertTrue(restarted.state.stopped)
        self.assertIn('program_restarted', restarted.state.automatic.reasons)
        self.assertEqual(restarted.state.automatic.cursors, cursors)
        automatic.on_completed_bars(restarted, (self.bar(),))
        self.assertEqual(self.placed(), before)

    def test_actual_protective_exit_survives_other_account_unknown_and_unverified_quote(self):
        self.use_stock_fixture()
        _, lot = self.open_and_fill()
        case = self.case
        form = ManualOrderForm(case.scope, 'unrelated-stock-timeout', self.stock.instrument_id, Side.BUY, 1000, D('20'), D('19.9'))
        prepared = case.service.execute(case.command(UiAction.PREVIEW_MANUAL, manual_order=form))
        self.assertTrue(prepared.accepted, prepared)
        preview = case.service.snapshot(case.scope).preview
        self.assertTrue(preview.allowed, preview.reasons)
        case.native.place_mode = 'TIMEOUT'
        unknown = case.service.execute(case.command(UiAction.SUBMIT_MANUAL, manual_order=replace(form, confirmed=True, preview_id=preview.preview_id)))
        self.assertEqual(unknown.code, 'outcome_unknown')
        self.assertTrue(self.engine.state.stopped)
        case.native.place_mode = 'Submitted'
        self.engine.quotes[self.stock.instrument_id] = replace(self.engine.quotes[self.stock.instrument_id], quality='UNVERIFIED')
        before = self.placed()
        closed = self.engine.exit_lot(lot.lot_id, protective=True, key='known-scope-protection')
        self.assertIsNotNone(closed)
        self.assertEqual(self.placed(), before + 1)
        self.assertTrue(self.engine.state.orders[-1].plan.reduce_only)

    def test_unified_sim_settings_change_before_first_book_never_queries_broker_funds(self):
        case = manual.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        self.case = case
        self.configure(case)
        before = len(case.native._seen)
        settings = SettingsForm(D('40000'), D('60000'), D('.02'))
        receipt = LocalFacade(self.engine).execute(UiCommand(UiAction.SAVE_SETTINGS, self.engine.state.version, settings=settings))
        self.assertTrue(receipt.accepted, receipt)
        self.assertEqual(self.engine.state.settings, settings)
        self.assertEqual(len(case.native._seen), before)
        confirmed = case.service.execute(case.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(case.scope, D('60000'), True)))
        self.assertTrue(confirmed.accepted, confirmed)
        self.assertEqual(self.engine.state.manual_books[0].capital, D('60000'))

    def test_unified_sim_settings_cannot_reduce_below_confirmed_virtual_book(self):
        self.deploy()
        before = len(self.case.native._seen)
        receipt = LocalFacade(self.engine).execute(
            UiCommand(UiAction.SAVE_SETTINGS, self.engine.state.version, settings=SettingsForm(D('60001'), D('39999'), D('.02')))
        )
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'risk_rejected')
        self.assertEqual(self.engine.state.settings.futures_allocation, D('40000'))
        self.assertEqual(len(self.case.native._seen), before)

    def test_stock_typed_calendar_cannot_open_after_1330(self):
        self.use_stock_fixture()
        record = self.deploy(stock=True)
        self.at(13, 31)
        before = self.placed()
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record, stock=True), record.policy, 'stock-after-close')
        self.assertEqual(rejected.exception.code, 'session_closed')
        self.assertEqual(self.placed(), before)

    def test_nonbroker_future_margin_provenance_uses_same_50000_sizing_and_owned_cash(self):
        case = manual.ManualCoreTests()
        case.setUp()
        self.addCleanup(case.owner.close)
        self.case = case
        self.configure(case)
        settings = SettingsForm(D('40000'), D('60000'), D('.02'))
        receipt = LocalFacade(self.engine).execute(UiCommand(UiAction.SAVE_SETTINGS, self.engine.state.version, settings=settings))
        self.assertTrue(receipt.accepted, receipt)
        confirmed = case.service.execute(case.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(case.scope, D('60000'), True)))
        self.assertTrue(confirmed.accepted, confirmed)
        diagnostic = case.service.execute(case.command(UiAction.TEST_SIM_ORDER, manual_order=case.prepare_test()))
        self.assertTrue(diagnostic.accepted, diagnostic)
        case.observe()
        self.engine.unverified_automatic_margins = frozenset((self.case.spec.instrument_id,))
        record = self.deploy()
        self.start()
        self.at(9, 1)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before + 1, self.engine.state.automatic)
        self.assertGreaterEqual(self.engine.state.orders[-1].reservation.cash, D('50000'))
        case.native.fill(case.native.trades[-1], 1, D('25000'))
        self.refresh()
        self.assertEqual(self.engine._strategy_spec(self.case.spec, record).margin, D('50000'))
        self.assertEqual(self.engine.account('future-alias').margin_used, D('50000'))
        self.assertGreaterEqual(self.engine.state.orders[-1].reservation.risk, D('250'))

    def test_stock_last_minute_uses_stock_calendar_beyond_narrow_manual_calendar(self):
        self.use_stock_fixture()
        self.engine.calendar = replace(
            self.engine.calendar,
            sessions=tuple(replace(session, closes_at=session.closes_at - timedelta(minutes=1)) for session in self.engine.calendar.sessions),
        )
        self.engine.history = synthetic_history(self.engine.catalog, self.engine.calendar)
        self.deploy(stock=True)
        self.at(13, 28)
        self.start()
        self.at(13, 29, 30)
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(stock=True),))
        self.assertEqual(self.placed(), before + 1, self.engine.state.automatic)
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.ACCEPTED)

    def test_unknown_native_ack_becomes_known_only_after_observation_reconcile_and_explicit_resume(self):
        self.deploy()
        self.start()
        self.at(9, 1)
        self.case.native.place_mode = 'TIMEOUT'
        before = self.placed()
        automatic.on_completed_bars(self.engine, (self.bar(),))
        unknown = self.engine.state.orders[-1]
        self.assertEqual(unknown.status, OrderStatus.UNKNOWN)
        self.assertFalse(unknown.broker_ref)
        self.assertIn('outcome_unknown', self.engine.state.issues)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.case.native.trades[-1].status.status = 'Submitted'
        self.refresh()
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.ACCEPTED)
        automatic.reconcile_automatic(self.engine)
        self.assertNotIn('outcome_unknown', self.engine.state.issues)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        automatic.resume_automatic(self.engine)
        self.assertFalse(self.engine.state.automatic.auto_paused)
        self.assertEqual(self.placed(), before + 1)
        self.assertGreater(self.engine.state.orders[-1].reservation.cash, 0)

    def test_cached_preflight_pass_cannot_replace_current_generation_diagnostic_at_direct_submit(self):
        record = self.deploy()
        self.start()
        self.at(9, 1)
        self.assertTrue(all(not row.blocked_today for row in self.engine.state.preflight))
        self.owner_view = replace(self.owner_view, generation='new-login-without-diagnostic')
        self.bundle.manual_runtime.stamp = (self.owner_view.generation, self.owner_view.revision, self.bundle.sinopac_connection.selected, self.case.owner)
        before = len(self.case.native._seen)
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'new-generation-direct-entry')
        self.assertEqual(rejected.exception.code, 'preflight_permission')
        self.assertEqual(len(self.case.native._seen), before)

    def test_direct_entry_rejects_owner_revision_changed_after_current_proof_was_collected(self):
        record = self.deploy()
        self.start()
        self.at(9, 1)
        reads = 0

        def snapshot():
            nonlocal reads
            reads += 1
            if reads == 5:
                self.owner_view = replace(self.owner_view, revision=self.owner_view.revision + 1)
            return self.owner_view

        self.bundle.sinopac_connection.snapshot = snapshot
        before = len(self.case.native._seen)
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'entry-with-obsolete-final-owner')
        self.assertEqual(rejected.exception.code, 'state_conflict')
        self.assertEqual(len(self.case.native._seen), before)

    def late_owner_change(self, **change):
        self.deploy()
        self.start()
        self.at(9, 1)
        original = RiskService.preview

        def preview(service, *args, **kwargs):
            decision = original(service, *args, **kwargs)
            self.assertTrue(decision.allowed, decision)
            self.owner_view = replace(self.owner_view, **change)
            return decision

        before = self.placed()
        with patch.object(RiskService, 'preview', preview):
            automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(self.placed(), before)
        self.assertTrue(self.engine.state.automatic.auto_paused)
        self.assertFalse(any(order.key.startswith('auto:') for order in self.engine.state.orders))

    def test_post_preview_disconnect_is_rechecked_before_actual_native_submission(self):
        self.late_owner_change(phase='DISCONNECTED')

    def test_post_preview_owner_revision_is_rechecked_before_actual_native_submission(self):
        self.late_owner_change(revision=4)

    def test_missing_submission_guard_cannot_fall_back_to_unguarded_native_send(self):
        record = self.deploy()
        self.start()
        del self.engine.automatic_submission_guard
        before = self.placed()
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'missing-owner-submission-guard')
        self.assertEqual(rejected.exception.code, 'capability_missing')
        self.assertEqual(self.placed(), before)

    def test_actual_native_submit_is_inside_owner_lock(self):
        self.deploy()
        self.start()
        self.at(9, 1)
        seen = []
        original = self.case.native._record

        def record(name, *args, **kwargs):
            if name == 'place_order':
                seen.append(self.bundle.sinopac_connection.lock._is_owned())
            return original(name, *args, **kwargs)

        self.case.native._record = record
        automatic.on_completed_bars(self.engine, (self.bar(),))
        self.assertEqual(seen, [True])
        self.assertEqual(self.engine.state.orders[-1].status, OrderStatus.ACCEPTED)

    def test_changed_margin_provenance_invalidates_previously_passed_research_at_deploy(self):
        record = self.deploy(activate=False)
        self.assertEqual(record.state, 'RESEARCHED')
        self.engine.unverified_automatic_margins = frozenset((self.case.spec.instrument_id,))
        before = len(self.case.native._seen)
        with self.assertRaises(DomainError) as rejected:
            self.engine.deploy(self.reference)
        self.assertEqual(rejected.exception.code, 'strategy_evidence_stale')
        self.assertEqual(self.engine.strategy(self.reference).state, 'RESEARCHED')
        self.assertEqual(len(self.case.native._seen), before)

    def test_active_strategy_changed_margin_provenance_cannot_submit_with_old_research(self):
        record = self.deploy()
        self.start()
        self.engine.unverified_automatic_margins = frozenset((self.case.spec.instrument_id,))
        before = len(self.case.native._seen)
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'active-stale-margin-evidence')
        self.assertEqual(rejected.exception.code, 'strategy_evidence_stale')
        self.assertEqual(len(self.case.native._seen), before)

    def test_active_strategy_changed_fee_values_same_version_cannot_submit_with_old_research(self):
        record = self.deploy()
        self.start()
        old_fees = self.engine.fees
        self.engine.fees = replace(old_fees, futures_fee_per_contract=old_fees.futures_fee_per_contract + D('1'))
        self.assertEqual(self.engine.fees.version, old_fees.version)
        before = len(self.case.native._seen)
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'active-stale-fee-evidence')
        self.assertEqual(rejected.exception.code, 'strategy_evidence_stale')
        self.assertEqual(len(self.case.native._seen), before)

    def move_to_contract_settlement(self):
        expiry = self.case.spec.expiry
        session = calendar_for_instrument(self.engine.calendar, self.case.spec).day_session(expiry)
        self.clock.value = session.opens_at.replace(hour=13, minute=27)
        for ref, capability in self.case.adapter.capabilities.items():
            self.case.adapter.capabilities[ref] = replace(capability, checked_at=self.clock.now(), expires_at=self.clock.now() + timedelta(hours=1))
        self.refresh()
        self.assertEqual(self.engine.state.trading_day, expiry)
        self.assertFalse(any(row.trade_date == expiry for row in self.engine.state.account_daily_baselines))

    def test_exact_tmf_cannot_open_on_its_actual_settlement_date(self):
        record = self.deploy()
        self.assertEqual(record.parameters.instrument_rule, 'EXACT')
        self.start()
        self.move_to_contract_settlement()
        before = len(self.case.native._seen)
        with self.assertRaises(DomainError) as rejected:
            self.engine.submit(self.direct_plan(record), record.policy, 'exact-tmf-settlement-entry')
        self.assertEqual(rejected.exception.code, 'strategy_settlement_day')
        self.assertEqual(len(self.case.native._seen), before)

    def test_exact_tmf_owned_protective_exit_remains_legal_on_settlement_date_without_new_baseline(self):
        _, lot = self.open_and_fill(intraday=True)
        self.move_to_contract_settlement()
        before = self.placed()
        closed = self.engine.exit_lot(lot.lot_id, protective=True, key='exact-tmf-settlement-protection')
        self.assertIsNotNone(closed)
        self.assertEqual(self.placed(), before + 1)
        self.assertTrue(self.engine.state.orders[-1].plan.reduce_only)


if __name__ == '__main__':
    unittest.main()
