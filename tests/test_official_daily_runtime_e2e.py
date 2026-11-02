"""Recorded official SQLite data -> actual connected ManualRuntime -> fake SDK.

No synthetic official-history port is installed. Quote/account observations are
explicit SDK doubles, not recordings of market prices or broker financial facts.
The June playback clock is controlled independently of fixture recording time.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_manual_runtime_integration as connected
import test_manual_trading as manual_fixtures
from test_trading_adapters import instrument
from test_trading_sdk_facade import contract
from test_official_daily_import import calendar, FIXTURES

from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding
from quantlab.trading.adapters.shioaji.stock_grid import COMMON_STOCK_BANDS, COMMON_STOCK_RULE, StockGridEvidence
from quantlab.trading.application.account_risk import seed_account_baseline
from quantlab.trading.application.codec import loads
from quantlab.trading.application.context import Catalog
from quantlab.trading.application.contracts import StrategyForm, UiAction
from quantlab.trading.application.manual_contracts import ManualBookForm, ManualOrderForm
from quantlab.trading.application.preflight import record_preflight
from quantlab.trading.application.workflows import run_research
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderStatus, Side
from quantlab.trading.domain.strategy import StrategyParameters
from quantlab.trading.runtime.official_daily_source import OfficialDailyStockSource
from quantlab.trading.runtime.preflight import sinopac_preflight_facts
from quantlab.trading.runtime.protocol import Operation
from quantlab.trading.runtime.sinopac_resources import ContractPriceLimits
from quantlab.trading.runtime.sinopac_transition import account_views
from tools.import_official_daily import import_official_daily

D = Decimal
SIM = Environment.BROKER_SIMULATION
SIGNAL_DAY = date(2025, 6, 12)
OPEN = datetime(2025, 6, 13, 1, 0, tzinfo=timezone.utc)


class RecordedStockSDK(manual_fixtures.MultiAccountManualSDK):
    def __init__(self, spec):
        super().__init__(spec)
        self.stock_item = contract('6225')
        self.stock_info = SimpleNamespace(**vars(self.stock_item), unit=1000, currency='TWD', trading_suspended=False)
        self._contracts = SimpleNamespace(
            get=lambda code: {'TMFL6': self.item, '6225': self.stock_item}[code],
            info=lambda item: self.stock_info if item.code == '6225' else self.info,
        )


class ConnectedOfficialFixture:
    def __init__(self, owner, *, calendar_data=None):
        self.owner_test = owner
        self.calendar = calendar_data or calendar()
        self.case = case = connected.ManualRuntimeIntegrationTests()
        case.sdk_class = RecordedStockSDK
        owner.addCleanup(case.doCleanups)
        case.setUp()
        self.clock = case.clock
        self.clock.value = datetime(2025, 6, 12, 1, 1, tzinfo=timezone.utc)
        self.bundle = case.bundle
        connection = self.bundle.sinopac_connection
        # Explicit test maintenance inputs, checked by the real persisted-key and
        # domain coverage code. These are not secrets or exchange expiry evidence.
        connection.maintenance.set_key_expiry(connection.configuration.key_ref, date(2025, 8, 1))
        months = {day.strftime('%Y%m'): day for day in self.calendar.days}
        expiry_fixture = {
            'data_version': 'SYNTHETIC_MAINTENANCE_TEST_ONLY',
            'expiries': [{'contract_month': month, 'expiry_date': day.isoformat()} for month, day in sorted(months.items())],
        }
        maintenance = patch('quantlab.trading.runtime.stock_maintenance.load_expiries', return_value=expiry_fixture)
        maintenance.start()
        owner.addCleanup(maintenance.stop)
        connection.publish(accounts=account_views(connection))
        self.stock_ref = next(row.alias for row in connection.accounts if row.market is Market.STOCK)
        self.future_ref = case.alias
        self.price = D('11.65')
        self.spec = replace(
            instrument(),
            instrument_id='TWSE:6225',
            underlying='6225',
            effective_at=datetime.combine(self.calendar.days[0], datetime.min.time(), timezone.utc),
            price_bands=COMMON_STOCK_BANDS,
            tick_rule_id=COMMON_STOCK_RULE,
        )
        evidence = StockGridEvidence(
            '6225',
            'TSE',
            'COMMON_STOCK',
            'TW0006225009',
            'ESVUFR',
            'https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2',
            '2025-06-12',
            'a' * 64,
            self.clock.now(),
        )
        stock = replace(
            case.resources,
            catalog=Catalog((self.spec,)),
            bindings=(InstrumentBinding(self.spec, '6225', evidence),),
            calendar=self.calendar,
            accounts=tuple(row for row in connection.accounts if row.alias == self.stock_ref),
            capabilities=(replace(case.resources.capabilities[0], account_ref=self.stock_ref, markets=frozenset((Market.STOCK,))),),
            limits=(ContractPriceLimits(self.spec.instrument_id, D('9'), D('15'), self.clock.now()),),
        )
        future_spec = replace(case.spec, effective_at=self.spec.effective_at)
        future = replace(
            case.resources,
            calendar=self.calendar,
            catalog=Catalog((future_spec,)),
            bindings=tuple(replace(binding, spec=future_spec) for binding in case.resources.bindings),
        )

        def resources(_owner, reference):
            row = stock if reference == self.stock_ref else future
            return replace(
                row,
                capabilities=tuple(replace(cap, checked_at=self.clock.now(), expires_at=self.clock.now() + timedelta(days=1)) for cap in row.capabilities),
                limits=tuple(replace(limit, observed_at=self.clock.now()) for limit in row.limits),
            )

        connection.resource_factory = resources

        def snapshots(contracts, timeout=30000, cb=None):
            case.native._record('snapshots', contracts, timeout=timeout)
            return [
                SimpleNamespace(
                    ts=int(self.clock.now().timestamp() * 1_000_000_000),
                    buy_price=float(self.price - D('.05')) if item.code == '6225' else 24999,
                    sell_price=float(self.price) if item.code == '6225' else 25000,
                    close=float(self.price) if item.code == '6225' else 25000,
                )
                for item in contracts
            ]

        case.native.snapshots = snapshots
        case.ready()  # Actual _materialize, real Ledger, empty confirmed future book.
        self.engine = self.bundle.engine
        state = case.request(Operation.SNAPSHOT, account=self.stock_ref).state
        scope = state.manual.scope
        command = replace(
            case.command(UiAction.ENABLE_MANUAL_BOOK, manual_book=ManualBookForm(scope, D('40000'), True)),
            account_ref=self.stock_ref,
            context_id=scope.context_id,
            context_epoch=scope.context_epoch,
            connection_generation=scope.connection_generation,
            connection_revision=scope.connection_revision,
        )
        owner.assertTrue(case.request(Operation.COMMAND, command, account=self.stock_ref).receipt.accepted)
        prepared = case.request(Operation.COMMAND, case.command(UiAction.TEST_SIM_ORDER))
        owner.assertTrue(prepared.receipt.accepted, prepared.receipt)
        preview = prepared.state.manual.preview
        form = ManualOrderForm(
            preview.scope,
            preview.request_id,
            preview.instrument_id,
            preview.side,
            preview.quantity,
            preview.limit_price,
            preview.stop_price,
            preview.purpose,
            True,
            preview.preview_id,
        )
        receipt = case.request(Operation.COMMAND, case.command(UiAction.TEST_SIM_ORDER, manual_order=form)).receipt
        owner.assertTrue(receipt.accepted, receipt)
        self.bundle.poll_ports()
        owner.assertEqual(case.state().manual.test_status, 'PASSED')
        self.initial_orders = self.placed()

    def placed(self):
        return sum(row[0] == 'place_order' for row in self.case.native._seen)

    def import_through(self, through):
        return import_official_daily(
            self.bundle.kline_store.path,
            self.spec.instrument_id,
            date(2025, 6, 2),
            through + timedelta(days=1),
            manifest=FIXTURES / 'manifest.json',
            clock=self.clock.now,
        )

    def refresh(self, at, price=None):
        self.clock.value = at
        if price is not None:
            self.price = price
        self.bundle.poll_ports()
        self.owner_test.assertEqual(self.bundle.manual_runtime.error, '')

    def deploy(self):
        self.import_through(date(2025, 6, 11))
        return self.deploy_cached()

    def deploy_cached(self):
        form = StrategyForm(
            'recorded-official-through-materialize',
            Market.STOCK,
            HoldingKind.CUSTOM,
            0,
            1,
            Side.BUY,
            self.spec.instrument_id,
            self.stock_ref,
            SIM,
            D('40000'),
            D('.02'),
            'BUY_AND_HOLD',
        )
        reference = self.engine.create_strategy(form, StrategyParameters('1d', D('.01'), D('20000')))
        with self.engine.lock:
            self.engine.validate_strategy(reference)
            run_research(self.engine, reference, ())
            self.engine.deploy(reference)
            # Initial genesis only: the actual adopted accounts/books are empty.
            # Subsequent day rollover must use the real completed-close provider.
            for account_ref in self.engine.gateways:
                self.engine._persist(
                    'offline_empty_confirmed_genesis', replace(self.engine.state, account_daily_baselines=seed_account_baseline(self.engine, account_ref))
                )
                record_preflight(self.engine, account_ref, sinopac_preflight_facts(self.bundle, account_ref))
        receipt = self.case.request(Operation.COMMAND, self.case.command(UiAction.AUTO_RESUME)).receipt
        self.owner_test.assertTrue(receipt.accepted, receipt)
        self.reference = reference
        return self.engine.strategy(reference)

    def close(self):
        for spec in sorted(
            self.engine.catalog.instruments, key=lambda row: calendar_for_instrument(self.engine.calendar, row).day_session(SIGNAL_DAY).closes_at
        ):
            session = calendar_for_instrument(self.engine.calendar, spec).day_session(SIGNAL_DAY)
            self.refresh(session.closes_at - timedelta(seconds=1))
            price = self.price if spec.market is Market.STOCK else D('25000')
            bars = tuple(
                LiveBar(
                    spec.instrument_id,
                    session.opens_at + timedelta(minutes=i),
                    session.opens_at + timedelta(minutes=i + 1),
                    SIGNAL_DAY,
                    'DAY',
                    price,
                    price,
                    price,
                    price,
                    1000,
                    final=True,
                )
                for i in range((session.closes_at - session.opens_at) // timedelta(minutes=1))
            )
            self.clock.value = session.closes_at
            self.bundle.automatic_runtime._enqueue(bars)
            self.bundle.pump()
            self.refresh(session.closes_at + timedelta(seconds=1))
            self.bundle.pump()
        self.owner_test.assertFalse(self.engine.state.automatic.auto_paused, self.engine.state.automatic)


class OfficialDailyRuntimeEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ConnectedOfficialFixture(self)

    def test_real_materialized_connection_owns_real_sqlite_official_source(self):
        fixture = self.fixture
        self.assertIsInstance(fixture.engine.daily_signal_source, OfficialDailyStockSource)
        self.assertIs(fixture.engine.daily_signal_source.store, fixture.bundle.kline_store)
        self.assertTrue(fixture.engine.daily_signal_cached_only)
        self.assertEqual(fixture.case.native.financial_queries, 0)

    def test_recorded_official_cache_reaches_next_open_native_dispatch_once(self):
        fixture = self.fixture
        record = fixture.deploy()
        result = loads(record.research_blob)
        self.assertIsNotNone(result.daily_basis)
        fixture.close()
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())
        self.assertEqual(fixture.placed(), fixture.initial_orders)
        # An explicit import arrives before the next verified open, never inside pump.
        fixture.refresh(OPEN - timedelta(minutes=30))
        fixture.import_through(SIGNAL_DAY)
        fixture.bundle.pump()
        intents = fixture.engine.state.automatic.daily.intents
        self.assertEqual(len(intents), 1, fixture.engine.daily_signal_data_views)
        self.assertEqual((intents[0].phase, intents[0].target_trade_date), ('READY', OPEN.date()))
        self.assertEqual(fixture.placed(), fixture.initial_orders)
        fixture.refresh(OPEN + timedelta(seconds=1), D('12'))
        fixture.bundle.pump()
        self.assertEqual(fixture.placed(), fixture.initial_orders + 1, fixture.engine.state.automatic)
        order = fixture.engine.state.orders[-1]
        self.assertEqual((order.status, order.plan.limit_price, order.plan.quantity), (OrderStatus.ACCEPTED, D('12'), 1000))
        self.assertEqual((order.plan.strategy_id, order.plan.strategy_version), (record.strategy_id, record.version))
        self.assertEqual(fixture.engine.state.automatic.daily.intents[0].phase, 'DISPATCHED')
        fixture.bundle.pump()
        self.assertEqual(fixture.placed(), fixture.initial_orders + 1)
        self.assertEqual(fixture.case.native.financial_queries, 0)

    def test_same_source_arriving_after_next_open_does_not_mint_catchup_order(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.close()
        fixture.refresh(OPEN + timedelta(seconds=1), D('12'))
        fixture.import_through(SIGNAL_DAY)
        fixture.bundle.pump()
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())
        self.assertEqual(fixture.placed(), fixture.initial_orders)
        self.assertFalse(fixture.engine.state.automatic.auto_paused)

    def test_transient_sqlite_read_failure_leaves_engine_healthy_and_next_pump_can_save(self):
        fixture = self.fixture
        fixture.deploy()
        fixture.close()
        fixture.refresh(OPEN - timedelta(minutes=30))
        fixture.import_through(SIGNAL_DAY)
        with patch.object(fixture.bundle.kline_store, 'daily_history', side_effect=sqlite3.OperationalError('explicit offline transient read')):
            fixture.bundle.pump()
        self.assertFalse(fixture.engine.storage_failed)
        self.assertEqual(fixture.engine.state.automatic.daily.intents, ())
        self.assertEqual(fixture.placed(), fixture.initial_orders)
        fixture.bundle.pump()
        self.assertEqual(len(fixture.engine.state.automatic.daily.intents), 1)
        self.assertEqual(fixture.engine.state.automatic.daily.intents[0].phase, 'READY')
        self.assertFalse(fixture.engine.storage_failed)
        self.assertEqual(fixture.placed(), fixture.initial_orders)


if __name__ == '__main__':
    unittest.main()
