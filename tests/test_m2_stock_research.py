"""Synthetic official schemas only; actual local stock research, fees and durability."""

from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from quantlab.trading.adapters.official.stock_data import StockDataSource
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.application.stock_history import StockHistorySync, months_between
from quantlab.trading.application.stock_research import StockTaxTreatment
from quantlab.trading.application.stock_research_service import StockResearchService
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, Side
from quantlab.trading.domain.strategy import Rule, StrategyDefinition, StrategyParameters
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.provenance import compute_profile
from quantlab.trading.runtime.stock_research import run_stock_research
from quantlab.trading.runtime.stock_maintenance import StockMaintenanceSettings, StockMaintenanceStore
from test_m2_stock_history import ID, native, event_data
from test_trading_domain import instrument

START, END = date(2020, 1, 1), date(2025, 1, 1)


class Clock:
    def now(self):
        return datetime(2025, 1, 2, tzinfo=timezone.utc)


class StockResearchFixture:
    def setUp(self):
        initialize()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = KlineStore(self.root / 'klines.sqlite')
        self.addCleanup(self.store.close)
        self.clock = Clock()
        self.months = months_between(START, END)
        days = (START - timedelta(days=1), *(month.replace(day=2) for month in self.months), END)
        sessions = tuple(
            TradingSession(
                day,
                datetime.combine(day, datetime.min.time(), timezone.utc),
                datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=6),
            )
            for day in days
        )
        self.calendar = TradingCalendar('synthetic-sparse-calendar', 'fixture-v1', 'synthetic-test-only', sessions)
        self.spec = replace(instrument(), effective_at=sessions[0].opens_at)
        self.calls = []
        self.before_prices = ('100', '102', '98', '100')
        self.sync = StockHistorySync(self.store, StockDataSource(self.transport))
        self.event_day = None
        self.sync.refresh(ID, START, END, today=END, consent=True)

    def transport(self, url):
        self.calls.append(url)
        if 'TWT48U' in url:
            rows = [] if self.event_day is None else [['2330', self.event_day.strftime('%Y/%m/%d'), '100', '90']]
            return event_data(rows)
        value = parse_qs(urlsplit(url).query)['date'][0]
        month = date(int(value[:4]), int(value[4:6]), 1)
        prices = ('90', '92', '88', '90') if self.event_day and month.replace(day=2) >= self.event_day else self.before_prices
        return native(month, prices=prices)

    def strategy(self, *, intraday=False, rule='BUY_AND_HOLD', side=Side.BUY):
        kind = HoldingKind.INTRADAY if intraday else HoldingKind.SWING
        low, high = (0, 0) if intraday else (3, 5)
        form = StrategyForm(
            'stock training', Market.STOCK, kind, low, high, side, ID, 'test-stock', Environment.LOCAL, D('1000000'), D('.02'), rule
        )
        return StrategyRecord('stock-training', 1, form, HoldingPolicy(kind, low, high), 'RULE_VALID')

    def service(self, journal, **kwargs):
        return StockResearchService(self.sync, journal, self.clock, self.calendar, compute_profile(), **kwargs)


class OfficialStockResearchTests(StockResearchFixture, unittest.TestCase):
    def test_runtime_stock_daytrade_etf_paths_use_exact_shared_costs_and_durable_evidence(self):
        settings = StockMaintenanceSettings(discount=D('.5'), minimum_fee=D('20'), slippage_ticks=0)
        StockMaintenanceStore(self.root).save(settings)
        original_calls = tuple(self.calls)
        artifacts = []
        for kind, day_trade, expected in (('STOCK', False, D('444')), ('STOCK', True, D('294')), ('ETF', True, D('244'))):
            artifact = run_stock_research(
                self.root,
                self.store,
                self.strategy(intraday=True),
                self.spec,
                self.calendar,
                START,
                END,
                stock_kind=kind,
                day_trade=day_trade,
                clock=self.clock,
            )
            artifacts.append(artifact)
            trade = artifact.result.trades[0]
            self.assertEqual((trade.entry, trade.exit, trade.gross, trade.costs), (D('100'), D('100'), D('0'), expected))
            fees = settings.fees(stock_kind=kind, day_trade=day_trade)
            self.assertEqual(artifact.fees, fees)
            self.assertEqual(trade.costs, fees.round_trip(self.spec, trade.entry, trade.exit, trade.quantity))
            self.assertEqual(artifact.result.net_pnl, -artifact.result.costs)
            self.assertEqual(artifact.treatment, StockTaxTreatment(kind, day_trade))
            self.assertEqual(artifact.evidence.partition, 'TRAINING')
            self.assertEqual(artifact.evidence.dataset_id, artifact.result.dataset_id)
            self.assertEqual(loads(dumps(artifact)), artifact)
        self.assertEqual(tuple(self.calls), original_calls)  # runner never downloads
        with closing(Ledger(self.root / 'official-stock-research.sqlite', 'official-stock-research-v1', self.clock.now())) as journal:
            self.assertEqual(self.service(journal).history(), tuple(artifacts))
        self.assertEqual(len({a.fees.version for a in artifacts}), 3)

    def test_crossing_unknown_cash_share_entitlement_refuses_entire_evidence(self):
        self.event_day = self.months[3].replace(day=2)
        self.sync.refresh(ID, START, END, today=END, consent=True)
        fees = FeeSchedule.taiwan(slippage_ticks=0)
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            with self.assertRaises(DomainError) as caught:
                self.service(journal).run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('STOCK'))
            self.assertEqual(caught.exception.code, 'stock_entitlement_unknown')
            self.assertEqual(journal.replay(), ())  # cannot invent dividend=10 from 100->90 ratio

    def test_adjusted_signal_suppresses_ex_dividend_false_decline_without_changing_raw_fills(self):
        self.event_day = self.months[10].replace(day=2)
        self.sync.refresh(ID, START, END, today=END, consent=True)
        fees = FeeSchedule.taiwan(day_trade=True, slippage_ticks=0)
        strategy = self.strategy(intraday=True, side=Side.SELL, rule='MA_CROSS')
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            artifact = self.service(journal).run(strategy, self.spec, START, END, fees, StockTaxTreatment('STOCK', True))
            self.assertEqual(artifact.result.trades, ())  # all known prices normalize to a flat history
            self.assertEqual(len(artifact.events), 1)
            self.assertIn(('adjustment_method', 'official-reference-ratio-backward-v1'), artifact.metadata)
            ordinary = self.service(journal).run(self.strategy(intraday=True), self.spec, START, END, fees, StockTaxTreatment('STOCK', True))
            after = next(trade for trade in ordinary.result.trades if trade.entry_index == 10)
            self.assertEqual((after.entry, after.exit, after.gross), (D('90'), D('90'), D('0')))

    def test_cost_policy_mismatch_cancel_timeout_and_incomplete_inputs_never_publish(self):
        fees = FeeSchedule.taiwan()
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            service = self.service(journal)
            calls = (
                lambda: service.run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('ETF')),
                lambda: service.run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(day_trade=True), StockTaxTreatment('STOCK', True)),
                lambda: service.run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('STOCK'), cancelled=lambda: True),
                lambda: service.run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('STOCK'), partition='NOT_TRAINING'),
                lambda: service.run(self.strategy(), self.spec, START + timedelta(days=1), END, fees, StockTaxTreatment('STOCK')),
            )
            for call in calls:
                with self.assertRaises(DomainError):
                    call()
                self.assertEqual(journal.replay(), ())
            for interval in ('1m', '1d'):
                typed = replace(self.strategy(), parameters=StrategyParameters(interval, D('.01'), D('10000')))
                with self.assertRaises(DomainError) as unsupported:
                    service.run(typed, self.spec, START, END, fees, StockTaxTreatment('STOCK'))
                self.assertEqual(unsupported.exception.code, 'validation_failed')
                self.assertEqual(journal.replay(), ())
            ticks = iter((0, 900))
            with self.assertRaises(DomainError) as timeout:
                self.service(journal, timer=lambda: next(ticks)).run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('STOCK'))
            self.assertEqual(timeout.exception.code, 'research_timeout')
            self.assertEqual(journal.replay(), ())

    def test_next_open_raw_prices_and_point_in_time_threshold_preserve_pre_event_signals(self):
        self.event_day = self.months[10].replace(day=2)
        self.sync.refresh(ID, START, END, today=END, consent=True)
        fees = FeeSchedule.taiwan(day_trade=True, slippage_ticks=2)
        strategy = self.strategy(intraday=True)
        definition = StrategyDefinition(
            strategy.strategy_id,
            strategy.version,
            Market.STOCK,
            strategy.policy,
            '1d',
            'LONG_ONLY',
            (Rule('close', 'GT', D('95')),),
            (Rule('close', 'LT', D('1')),),
            fees.version,
            'test-risk',
        )
        strategy = replace(strategy, definition=definition)
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            artifact = self.service(journal).run(strategy, self.spec, START, END, fees, StockTaxTreatment('STOCK', True))
            self.assertEqual(tuple(trade.entry_index for trade in artifact.result.trades), tuple(range(1, 11)))
            event_trade = artifact.result.trades[-1]
            self.assertEqual((event_trade.entry, event_trade.exit), (D('90.10'), D('89.90')))
            self.assertEqual(event_trade.gross, D('-200'))
            self.assertEqual(artifact.evidence.strategy_fingerprint, definition.fingerprint)

    def test_failed_publication_keeps_old_artifact_and_changed_fees_make_new_identity(self):
        first_fees, second_fees = FeeSchedule.taiwan(), FeeSchedule.taiwan(discount=D('.5'))
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            service = self.service(journal)
            first = service.run(self.strategy(), self.spec, START, END, first_fees, StockTaxTreatment('STOCK'))
            original_bytes = journal.replay()[0].payload
            journal.fail_writes = True
            with self.assertRaises(DomainError) as failure:
                service.run(self.strategy(), self.spec, START, END, second_fees, StockTaxTreatment('STOCK'))
            self.assertEqual(failure.exception.code, 'journal_failed')
            journal.fail_writes = False
            self.assertEqual(service.history(), (first,))
            changed_source = self.service(journal, profile_reader=lambda: None)
            with self.assertRaises(DomainError) as failure:
                changed_source.run(self.strategy(), self.spec, START, END, second_fees, StockTaxTreatment('STOCK'))
            self.assertEqual(failure.exception.code, 'source_invalid_evidence')
            self.assertEqual(service.history(), (first,))
            second = service.run(self.strategy(), self.spec, START, END, second_fees, StockTaxTreatment('STOCK'))
            self.assertNotEqual(first.result.fingerprint, second.result.fingerprint)
            self.assertNotEqual(first.evidence.result_hash, second.evidence.result_hash)
            self.assertEqual(journal.replay()[0].payload, original_bytes)

    def test_decimal_context_cannot_change_research_and_no_same_bar_entry(self):
        from decimal import localcontext

        fees = FeeSchedule.taiwan(slippage_ticks=1)
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            service = self.service(journal)
            expected = service.run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('STOCK'))
            with localcontext() as context:
                context.prec = 4
                actual = service.run(self.strategy(), self.spec, START, END, fees, StockTaxTreatment('STOCK'))
            self.assertEqual(actual, expected)
            self.assertEqual(actual.result.trades[0].entry_index, 1)
            self.assertTrue(all(trade.exit_index > trade.entry_index for trade in actual.result.trades))

    def test_cancellation_after_processing_has_started_keeps_journal_empty(self):
        calls = []

        def cancelled():
            calls.append(None)
            return len(calls) == 6

        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            with self.assertRaises(DomainError) as failure:
                self.service(journal).run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(), StockTaxTreatment('STOCK'), cancelled=cancelled)
            self.assertEqual(failure.exception.code, 'research_cancelled')
            self.assertEqual(len(calls), 6)
            self.assertEqual(journal.replay(), ())

    def test_durable_sidecar_cannot_relabel_evidence_as_a_different_stage(self):
        from quantlab.trading.application.stock_research_service import EVENT_KIND

        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            service = self.service(journal)
            artifact = service.run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(), StockTaxTreatment('STOCK'))
            altered = replace(artifact, evidence=replace(artifact.evidence, stage='ENABLEABLE'))
            journal.append(EVENT_KIND, dumps(altered), self.clock.now(), expected_sequence=1)
            with self.assertRaises(DomainError) as failure:
                service.history()
            self.assertEqual(failure.exception.code, 'source_invalid_evidence')

    def test_five_year_dense_synthetic_calendar_runs_complete_history_without_network(self):
        import calendar as month_calendar

        days = tuple(START - timedelta(days=1) + timedelta(days=i) for i in range((END - START).days + 2))
        sessions = tuple(
            TradingSession(
                day,
                datetime.combine(day, datetime.min.time(), timezone.utc),
                datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=6),
            )
            for day in days
        )
        calendar = TradingCalendar('dense-synthetic', 'fixture-v1', 'all-days-explicit-synthetic-not-exchange-calendar', sessions)

        def transport(url):
            if 'TWT48U' in url:
                return event_data()
            value = parse_qs(urlsplit(url).query)['date'][0]
            month = date(int(value[:4]), int(value[4:6]), 1)
            rows = [
                [f'{month.year - 1911:03d}/{month.month:02d}/{day:02d}', '1,234', '123400', '100', '102', '98', '100', '0', '123']
                for day in range(1, month_calendar.monthrange(month.year, month.month)[1] + 1)
            ]
            return native(month, rows=rows)

        sync = StockHistorySync(self.store, StockDataSource(transport))
        sync.refresh(ID, START, END, today=END, consent=True)
        result = run_stock_research(self.root, self.store, self.strategy(), self.spec, calendar, START, END, stock_kind='STOCK', clock=self.clock)
        self.assertEqual(result.result.observations, (END - START).days)
        self.assertGreater(len(result.result.trades), 250)
        self.assertEqual(result.evidence.partition, 'TRAINING')

    def test_coverage_marker_with_missing_bar_cannot_replace_prior_research_evidence(self):
        import sqlite3

        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            service = self.service(journal)
            first = service.run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(), StockTaxTreatment('STOCK'))
            original = journal.replay()[0].payload
            with closing(sqlite3.connect(self.store.path)) as db, db:
                db.execute('DELETE FROM bars_1d WHERE trade_date=?', ('2022-01-02',))
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            self.assertTrue(self.store.daily_coverage(ID, START, END))
            with self.assertRaises(DomainError) as failure:
                service.run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(), StockTaxTreatment('STOCK'))
            self.assertEqual(failure.exception.code, 'official_stock_coverage_missing')
            self.assertEqual(service.history(), (first,))
            self.assertEqual(journal.replay()[0].payload, original)

    def test_host_composition_uses_owned_store_strategy_calendar_and_cost_preferences(self):
        from quantlab.trading.runtime.bootstrap import build_runtime
        from quantlab.trading.runtime.config import RuntimeLaunch

        bundle = build_runtime(RuntimeLaunch(self.root / 'host'))
        try:
            future_sessions = tuple(session for session in bundle.engine.calendar.sessions if session.opens_at > self.calendar.sessions[-1].closes_at)
            bundle.engine.calendar = replace(self.calendar, version='fixture-host-v1', sessions=self.calendar.sessions + future_sessions)
            self.before_prices = ('20', '22', '18', '20')
            sync = StockHistorySync(bundle.kline_store, StockDataSource(self.transport))
            sync.refresh(ID, START, END, today=END, consent=True)
            costs = StockMaintenanceSettings(discount=D('.5'), slippage_ticks=0)
            StockMaintenanceStore(bundle.launch.root).save(costs)
            form = replace(self.strategy(intraday=True).form, account_ref='local-stock', allocation=D('30000'))
            with bundle.engine.lock:
                reference = bundle.engine.create_strategy(form)
                with self.assertRaises(DomainError) as ineligible:
                    bundle.engine.validate_strategy(reference)
                self.assertEqual(ineligible.exception.code, 'intraday_eligibility_missing')
                gateway = bundle.engine.gateways['local-stock']
                gateway.capabilities = replace(gateway.capabilities, day_trade=True)  # explicit fake eligibility, never inferred from ticker
                bundle.engine.validate_strategy(reference)
                before = bundle.engine.state
            source_calls = tuple(self.calls)
            artifact = bundle.research_stocks(reference, START, END, stock_kind='ETF', day_trade=True)
            self.assertEqual(artifact.strategy, bundle.engine.strategy(reference))
            self.assertEqual(artifact.instrument, bundle.engine.catalog.resolve(ID))
            self.assertEqual(artifact.calendar, bundle.engine.calendar)
            self.assertEqual(artifact.fees, costs.fees(stock_kind='ETF', day_trade=True))
            self.assertEqual(artifact.result.trades[0].costs, D('60'))
            self.assertEqual(bundle.engine.state, before)  # no trading/deployment side effect
            self.assertEqual(tuple(self.calls), source_calls)
            self.assertTrue((bundle.launch.root / 'official-stock-research.sqlite').exists())
        finally:
            bundle.close()
        with self.assertRaises(DomainError) as closed:
            bundle.research_stocks(reference, START, END, stock_kind='STOCK')
        self.assertEqual(closed.exception.code, 'capability_missing')

    def test_position_cash_admission_uses_raw_not_backward_adjusted_prices(self):
        self.event_day = self.months[10].replace(day=2)
        self.sync.refresh(ID, START, END, today=END, consent=True)
        strategy = self.strategy(intraday=True)
        strategy = replace(strategy, form=replace(strategy.form, allocation=D('95000')))
        with closing(Ledger(self.root / 'research.sqlite', 'stock-test', self.clock.now())) as journal:
            artifact = self.service(journal).run(
                strategy, self.spec, START, END, FeeSchedule.taiwan(day_trade=True, slippage_ticks=0), StockTaxTreatment('STOCK', True)
            )
            # A raw100 x1000 lot exceeds95000 even though its retrospective
            # adjusted price is90. The first affordable raw lot is on ex-date.
            self.assertEqual(artifact.result.trades[0].entry_index, 10)
            self.assertTrue(all(trade.entry_index >= 10 for trade in artifact.result.trades))
            self.assertTrue(all(trade.quantity == 1000 for trade in artifact.result.trades))
