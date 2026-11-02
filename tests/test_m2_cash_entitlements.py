"""Explicit synthetic cash facts; no recorded/native entitlement compatibility claim."""

from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from hashlib import sha256
import json
import sqlite3
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from quantlab.trading.adapters.official.stock_data import StockDataSource, events_url, parse_events
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.application.stock_history import StockHistorySync
from quantlab.trading.application.stock_research import CASH_PRODUCER, CashStockResearchArtifact, StockTaxTreatment
from quantlab.trading.application.stock_research_service import StockResearchService
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import Side
from quantlab.trading.domain.stock_history import CashDividendAction, CorporateAction, price_series
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.stock_history import OfficialPayload
from test_m2_stock_history import event_data, native
from test_m2_stock_research import END, ID, START, StockResearchFixture


# Generated on unmodified f0e974fd with this fixed synthetic profile. These are
# immutable historical compatibility expectations, not current-source baselines.
LEGACY_ARTIFACT_SHA = '39af5db377dbc5dfa00d1bb54bc4a9df65c17c10570b9a26888b91ba28dfb4fa'
LEGACY_RESULT_SHA = '5fb5563da808fe89624f3a714e2052453674e2baf3694b3377fe4e7a82e89a75'
LEGACY_EVIDENCE_HASH = 'b935ca2fdb1336d7561cdb1088ec0c3564e2252e9fa51c02fc46fd32a9bd7e54'


def fixed_profile():
    manifest = (('quantlab/trading/synthetic_fixture.py', 'a' * 64),)
    digest = sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return ProducerProfile('MARKAUTO-TRADING-V2-PROFILE-1', 2, manifest, digest)


class FakeCashSource:
    """Trusted port fake with explicit facts, deliberately NOT a native parser."""

    def __init__(self, base, ex_date, payment_date, amount=D('10'), *, previous_close=D('100'), reference_price=D('90')):
        self.base, self.ex_date, self.payment_date, self.amount = base, ex_date, payment_date, amount
        self.previous_close, self.reference_price = previous_close, reference_price

    def month(self, instrument_id, month):
        return self.base.month(instrument_id, month)

    def events(self, instrument_id, start, end):
        raw = json.dumps(
            {
                'fixture': 'synthetic-explicit-facts-not-native-market-data',
                'instrument_id': instrument_id,
                'kind': 'cash-only',
                'ex_date': self.ex_date.isoformat(),
                'payment_date': self.payment_date.isoformat(),
                'cash_per_share': str(self.amount),
                'previous_close': str(self.previous_close),
                'reference_price': str(self.reference_price),
            },
            sort_keys=True,
        ).encode()
        url = events_url(instrument_id, start, end)
        digest = sha256(raw).hexdigest()
        action = CashDividendAction(instrument_id, self.ex_date, self.previous_close, self.reference_price, digest, url, self.amount, self.payment_date)
        return (action,), OfficialPayload(url, digest, raw)


class CashEntitlementTests(StockResearchFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sequence = 0

    def cash_inputs(self, event_index=3, *, payment_date=date(2020, 8, 2), amount=D('10')):
        self.event_day = self.months[event_index].replace(day=2)
        source = FakeCashSource(StockDataSource(self.transport), self.event_day, payment_date, amount)
        self.sync = StockHistorySync(self.store, source)
        return self.sync.refresh(ID, START, END, today=END, consent=True)

    def run_cash(self, strategy=None):
        self.sequence += 1
        with closing(Ledger(self.root / f'cash-{self.sequence}.sqlite', 'synthetic-cash', self.clock.now())) as journal:
            service = StockResearchService(self.sync, journal, self.clock, self.calendar, fixed_profile())
            artifact = service.run(strategy or self.strategy(), self.spec, START, END, FeeSchedule.taiwan(slippage_ticks=0), StockTaxTreatment('STOCK'))
            self.assertEqual(service.history(), (artifact,))
            self.assertEqual(loads(dumps(artifact)), artifact)
            return artifact

    def test_historical_wire_and_artifact_hashes_remain_exact(self):
        event = CorporateAction(ID, date(2020, 4, 2), D('100'), D('90'), 'a' * 64, 'https://www.twse.com.tw/synthetic-fixture')
        expected = (
            '{"@":"quantlab.trading.domain.stock_history.CorporateAction","fields":'
            '{"ex_date":{"@":"date","value":"2020-04-02"},"instrument_id":"TWSE:2330",'
            '"previous_close":{"@":"decimal","value":"100"},"reference_price":{"@":"decimal","value":"90"},'
            '"source_digest":"' + 'a' * 64 + '","source_url":"https://www.twse.com.tw/synthetic-fixture"}}'
        )
        self.assertEqual(dumps(event), expected)
        self.assertEqual(dumps(loads(expected)), expected)
        artifact = self.run_cash()
        self.assertNotIsInstance(artifact, CashStockResearchArtifact)
        self.assertEqual(sha256(dumps(artifact).encode()).hexdigest(), LEGACY_ARTIFACT_SHA)
        self.assertEqual(sha256(dumps(artifact.result).encode()).hexdigest(), LEGACY_RESULT_SHA)
        self.assertEqual(artifact.evidence.result_hash, LEGACY_EVIDENCE_HASH)

    def test_runtime_bundle_research_uses_owned_cash_history_and_preserves_engine(self):
        from quantlab.trading.runtime.bootstrap import build_runtime
        from quantlab.trading.runtime.config import RuntimeLaunch
        from quantlab.trading.runtime.stock_maintenance import StockMaintenanceSettings, StockMaintenanceStore

        bundle = build_runtime(RuntimeLaunch(self.root / 'cash-host'))
        try:
            future = tuple(session for session in bundle.engine.calendar.sessions if session.opens_at > self.calendar.sessions[-1].closes_at)
            bundle.engine.calendar = replace(self.calendar, version='synthetic-cash-host-v1', sessions=self.calendar.sessions + future)
            self.event_day = self.months[3].replace(day=2)

            def host_transport(url):
                self.calls.append(url)
                value = parse_qs(urlsplit(url).query)['date'][0]
                month = date(int(value[:4]), int(value[4:6]), 1)
                prices = ('10', '12', '8', '10') if month.replace(day=2) >= self.event_day else ('20', '22', '18', '20')
                return native(month, prices=prices)

            source = FakeCashSource(StockDataSource(host_transport), self.event_day, date(2026, 12, 2), previous_close=D('20'), reference_price=D('10'))
            sync = StockHistorySync(bundle.kline_store, source)
            batch = sync.refresh(ID, START, END, today=END, consent=True)
            costs = StockMaintenanceSettings(discount=D('.5'), slippage_ticks=0)
            StockMaintenanceStore(bundle.launch.root).save(costs)
            form = replace(self.strategy().form, account_ref='local-stock', allocation=D('30000'))
            with bundle.engine.lock:
                reference = bundle.engine.create_strategy(form)
                bundle.engine.validate_strategy(reference)
                before = bundle.engine.state
            source_calls = tuple(self.calls)
            artifact = bundle.research_stocks(reference, START, END, stock_kind='STOCK')
            self.assertIsInstance(artifact, CashStockResearchArtifact)
            self.assertGreater(artifact.cash_accounting.gross_entitlement, D('0'))
            self.assertEqual(artifact.cash_accounting.gross_payable, D('0'))
            self.assertEqual(artifact.cash_accounting.gross_receivable, artifact.cash_accounting.gross_entitlement)
            self.assertEqual(artifact.strategy, bundle.engine.strategy(reference))
            self.assertEqual(artifact.instrument, bundle.engine.catalog.resolve(ID))
            self.assertEqual(artifact.calendar, bundle.engine.calendar)
            self.assertEqual(artifact.fees, costs.fees(stock_kind='STOCK'))
            self.assertEqual(artifact.events, batch.events)
            self.assertEqual(bundle.kline_store.daily_history(ID, START, END).events, batch.events)
            self.assertEqual(artifact.result.net_pnl, sum((trade.gross - trade.costs for trade in artifact.result.trades), D('0')))
            self.assertEqual(artifact.cash_accounting.raw_net_plus_entitlement, artifact.result.net_pnl + artifact.cash_accounting.gross_entitlement)
            self.assertEqual(bundle.engine.state, before)
            self.assertEqual(tuple(self.calls), source_calls)
            path = bundle.launch.root / 'official-stock-research.sqlite'
            self.assertTrue(path.exists())
            with closing(Ledger(path, 'official-stock-research-v1', bundle.engine.clock.now())) as journal:
                replay = StockResearchService(sync, journal, bundle.engine.clock, bundle.engine.calendar, fixed_profile()).history()
                self.assertEqual(replay, (artifact,))
        finally:
            bundle.close()

    def test_cash_dividend_is_separate_from_raw_trade_price_pnl(self):
        self.cash_inputs()
        artifact = self.run_cash()
        self.assertIsInstance(artifact, CashStockResearchArtifact)
        self.assertEqual(artifact.result.producer, CASH_PRODUCER)
        accounting = artifact.cash_accounting
        trade = artifact.result.trades[0]
        self.assertEqual((trade.entry, trade.exit), (D('100'), D('90')))
        self.assertEqual(trade.gross, (trade.exit - trade.entry) * trade.quantity * self.spec.multiplier)
        self.assertEqual(trade.gross, -D('10') * trade.quantity)
        self.assertEqual(accounting.gross_entitlement, D('10') * trade.quantity)
        self.assertEqual(accounting.raw_net_plus_entitlement, artifact.result.net_pnl + accounting.gross_entitlement)
        self.assertEqual(artifact.result.net_pnl, sum((t.gross - t.costs for t in artifact.result.trades), D('0')))
        self.assertEqual(len(accounting.entitlements), 1)
        row = accounting.entitlements[0]
        self.assertEqual((row.event_index, row.trade_index, row.quantity, row.gross_amount), (0, 0, trade.quantity, accounting.gross_entitlement))
        self.assertEqual(accounting.as_of, self.months[-1].replace(day=2))
        self.assertEqual(accounting.gross_payable, accounting.gross_entitlement)
        self.assertEqual(accounting.gross_receivable, D('0'))

    def test_sell_on_ex_date_retains_entitlement(self):
        self.cash_inputs(event_index=6)
        artifact = self.run_cash()
        self.assertEqual(artifact.result.trades[0].exit_index, 6)
        self.assertEqual(len(artifact.cash_accounting.entitlements), 1)
        self.assertEqual(artifact.cash_accounting.entitlements[0].trade_index, 0)

    def test_buy_on_ex_date_has_no_entitlement(self):
        self.cash_inputs(event_index=1)
        artifact = self.run_cash()
        self.assertEqual(artifact.result.trades[0].entry_index, 1)
        self.assertEqual(artifact.cash_accounting.entitlements, ())
        self.assertEqual(artifact.cash_accounting.gross_entitlement, D('0'))
        self.assertEqual(artifact.cash_accounting.raw_net_plus_entitlement, artifact.result.net_pnl)

    def test_payment_after_exit_and_after_research_horizon_stays_receivable(self):
        self.cash_inputs(payment_date=date(2026, 1, 2))
        artifact = self.run_cash()
        self.assertLess(self.months[artifact.result.trades[0].exit_index], date(2026, 1, 2))
        accounting = artifact.cash_accounting
        self.assertEqual(accounting.gross_payable, D('0'))
        self.assertEqual(accounting.gross_receivable, accounting.gross_entitlement)
        self.assertGreater(accounting.gross_receivable, D('0'))

    def test_payment_on_horizon_is_due_not_a_broker_payment_assertion(self):
        horizon = self.months[-1].replace(day=2)
        self.cash_inputs(payment_date=horizon)
        accounting = self.run_cash().cash_accounting
        self.assertEqual(accounting.gross_payable, accounting.gross_entitlement)
        self.assertEqual(accounting.gross_receivable, D('0'))

    def test_repeated_research_and_refresh_do_not_double_entitlement(self):
        self.cash_inputs()
        first = self.run_cash()
        self.sync.refresh(ID, START, END, today=END, consent=True)
        second = self.run_cash()
        self.assertEqual(first, second)
        self.assertEqual(len(second.cash_accounting.entitlements), 1)

    def test_cash_facts_cannot_fund_otherwise_unaffordable_raw_entry(self):
        self.cash_inputs(amount=D('100000'))
        strategy = self.strategy()
        strategy = replace(strategy, form=replace(strategy.form, allocation=D('1')))
        artifact = self.run_cash(strategy)
        self.assertEqual(artifact.result.trades, ())
        self.assertEqual(artifact.cash_accounting.entitlements, ())
        self.assertEqual(artifact.cash_accounting.gross_entitlement, D('0'))

    def test_unpaid_receivable_does_not_expand_later_static_allocation(self):
        original_transport = self.transport

        def changed_prices(url):
            if 'TWT48U' not in url:
                value = parse_qs(urlsplit(url).query)['date'][0]
                month = date(int(value[:4]), int(value[4:6]), 1)
                if month >= date(2020, 8, 1):
                    return native(month, prices=('105', '107', '103', '105'))
            return original_transport(url)

        self.transport = changed_prices
        self.cash_inputs(payment_date=date(2026, 1, 2))
        strategy = self.strategy()
        strategy = replace(strategy, form=replace(strategy.form, allocation=D('100200')))
        artifact = self.run_cash(strategy)
        self.assertEqual(len(artifact.result.trades), 1)
        self.assertEqual(artifact.cash_accounting.gross_receivable, D('10000'))
        fees = FeeSchedule.taiwan(slippage_ticks=0)
        later_cash = fees.entry_cash(self.spec, D('105'), self.spec.lot_size)
        self.assertGreater(later_cash, strategy.form.allocation)
        self.assertLess(later_cash, strategy.form.allocation + artifact.cash_accounting.gross_receivable)

    def test_short_cash_crossing_still_refuses_and_publishes_nothing(self):
        self.cash_inputs()
        with closing(Ledger(self.root / 'short.sqlite', 'short', self.clock.now())) as journal:
            with self.assertRaises(DomainError) as caught:
                self.service(journal).run(
                    self.strategy(side=Side.SELL), self.spec, START, END, FeeSchedule.taiwan(slippage_ticks=0), StockTaxTreatment('STOCK')
                )
            self.assertEqual(caught.exception.code, 'stock_entitlement_unknown')
            self.assertEqual(journal.replay(), ())

    def test_unknown_event_crossing_is_not_upgraded_by_another_known_cash_event(self):
        batch = self.cash_inputs()
        event = batch.events[0]
        unknown = CorporateAction(ID, self.months[9].replace(day=2), D('90'), D('80'), event.source_digest, event.source_url)
        self.store.import_daily(replace(batch, events=(event, unknown)))
        with closing(Ledger(self.root / 'mixed.sqlite', 'mixed', self.clock.now())) as journal:
            with self.assertRaises(DomainError) as caught:
                self.service(journal).run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(slippage_ticks=0), StockTaxTreatment('STOCK'))
            self.assertEqual(caught.exception.code, 'stock_entitlement_unknown')
            self.assertEqual(journal.replay(), ())

    def test_duplicate_event_is_rejected_without_changing_stored_history(self):
        batch = self.cash_inputs()
        before = self.store.daily_history(ID, START, END)
        with self.assertRaises(DomainError):
            self.store.import_daily(replace(batch, events=batch.events * 2))
        self.assertEqual(self.store.daily_history(ID, START, END), before)

    def test_source_payload_tampering_is_rejected_without_publication(self):
        batch = self.cash_inputs()
        before = self.store.daily_history(ID, START, END)
        bad = replace(batch.payloads[-1], raw=b'changed synthetic issuer facts')
        with self.assertRaises(DomainError):
            self.store.import_daily(replace(batch, payloads=(*batch.payloads[:-1], bad)))
        self.assertEqual(self.store.daily_history(ID, START, END), before)

    def test_atomic_publication_failure_keeps_cash_facts_and_raw_history(self):
        batch = self.cash_inputs()
        before = self.store.daily_history(ID, START, END)
        with closing(sqlite3.connect(self.root / 'klines.sqlite')) as db:
            db.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON corporate_actions BEGIN SELECT RAISE(ABORT, 'synthetic publication failure'); END")
            db.commit()
        with self.assertRaises(DomainError):
            self.store.import_daily(batch)
        self.assertEqual(self.store.daily_history(ID, START, END), before)

    def test_cash_facts_round_trip_and_digest_binds_amount_and_payment_date(self):
        batch = self.cash_inputs()
        stored = self.store.daily_history(ID, START, END)
        self.assertEqual(stored.events, batch.events)
        event = stored.events[0]
        self.assertIsInstance(event, CashDividendAction)
        self.assertEqual(self.store.official_payload(event.source_url, event.source_digest).digest, event.source_digest)
        digest = price_series(batch.bars, batch.events, adjusted=False).events_digest
        for replacement in (replace(event, cash_per_share=D('11')), replace(event, payment_date=date(2020, 9, 2))):
            self.assertNotEqual(price_series(batch.bars, (replacement,), adjusted=False).events_digest, digest)

    def test_cancellation_during_cash_accrual_preserves_previous_artifact(self):
        from quantlab.trading.application import stock_research_service

        self.cash_inputs()
        cancelled = False
        original = stock_research_service.cash_entitlements

        def cancel_at_cash(result, inputs, checkpoint):
            nonlocal cancelled
            cancelled = True
            return original(result, inputs, checkpoint)

        with closing(Ledger(self.root / 'cash-cancel.sqlite', 'cash-cancel', self.clock.now())) as journal:
            service = StockResearchService(self.sync, journal, self.clock, self.calendar, fixed_profile())
            service.run(self.strategy(), self.spec, START, END, FeeSchedule.taiwan(slippage_ticks=0), StockTaxTreatment('STOCK'))
            before = journal.replay()
            with patch.object(stock_research_service, 'cash_entitlements', side_effect=cancel_at_cash):
                with self.assertRaises(DomainError) as caught:
                    service.run(
                        self.strategy(), self.spec, START, END, FeeSchedule.taiwan(slippage_ticks=0), StockTaxTreatment('STOCK'), cancelled=lambda: cancelled
                    )
            self.assertEqual(caught.exception.code, 'research_cancelled')
            self.assertTrue(cancelled)
            self.assertEqual(journal.replay(), before)

    def test_replay_rejects_cash_summary_changed_without_its_evidence_hash(self):
        from quantlab.trading.application.stock_research_service import EVENT_KIND

        self.cash_inputs()
        artifact = self.run_cash()
        changed = replace(artifact, cash_accounting=replace(artifact.cash_accounting, gross_entitlement=artifact.cash_accounting.gross_entitlement + D('1')))
        with closing(Ledger(self.root / 'cash-tamper.sqlite', 'cash-tamper', self.clock.now())) as journal:
            journal.append(EVENT_KIND, dumps(changed), self.clock.now(), expected_sequence=0)
            service = StockResearchService(self.sync, journal, self.clock, self.calendar, fixed_profile())
            with self.assertRaises(DomainError) as caught:
                service.history()
            self.assertEqual(caught.exception.code, 'source_invalid_evidence')

    def test_cached_cash_source_mismatch_or_orphan_is_rejected(self):
        batch = self.cash_inputs()
        for statement in (
            "UPDATE stock_cash_entitlements SET source_digest='" + 'b' * 64 + "'",
            "UPDATE stock_cash_entitlements SET ex_date='2020-05-02'",
        ):
            with self.subTest(statement=statement):
                self.store.import_daily(batch)
                with closing(sqlite3.connect(self.root / 'klines.sqlite')) as db:
                    db.execute(statement)
                    db.commit()
                with self.assertRaises(DomainError) as caught:
                    self.store.daily_history(ID, START, END)
                self.assertEqual(caught.exception.code, 'official_stock_invalid')

    def test_cached_cash_fields_and_reference_corruption_fail_integrity_check(self):
        batch = self.cash_inputs()
        for statement in (
            "UPDATE stock_cash_entitlements SET cash_per_share='11'",
            "UPDATE stock_cash_entitlements SET payment_date='2020-09-02'",
            "UPDATE corporate_actions SET reference_price='89'",
            "UPDATE corporate_actions SET previous_close='101'",
        ):
            with self.subTest(statement=statement):
                self.store.import_daily(batch)
                with closing(sqlite3.connect(self.root / 'klines.sqlite')) as db:
                    db.execute(statement)
                    db.commit()
                with self.assertRaises(DomainError) as caught:
                    self.store.daily_history(ID, START, END)
                self.assertEqual(caught.exception.code, 'official_stock_invalid')

    def test_cash_summary_metadata_distinguishes_schedule_from_paid_bank_cash(self):
        self.cash_inputs()
        metadata = dict(self.run_cash().metadata)
        self.assertIn('gross issuer distribution', metadata['cash_basis'])
        self.assertIn('excludes personal withholding and remittance fees', metadata['cash_basis'])
        self.assertIn('issuer-specific rounding not modeled', metadata['cash_basis'])
        self.assertIn('not verified bank settlement', metadata['cash_payable_basis'])
        self.assertIn('static allocation unchanged', metadata['cash_sizing'])
        self.assertIn('drawdown remain raw-price-only', metadata['cash_performance'])

    def test_native_reference_ratio_parser_does_not_invent_cash_facts(self):
        raw = event_data([['2330', '2020/04/02', '100', '90']])
        events = parse_events(raw, ID, START, END, events_url(ID, START, END))
        self.assertEqual(type(events[0]), CorporateAction)

    def test_invalid_cash_or_payment_date_is_rejected_at_event_boundary(self):
        batch = self.cash_inputs()
        event = batch.events[0]
        for changes in ({'cash_per_share': D('0')}, {'cash_per_share': D('-1')}, {'cash_per_share': D('NaN')}, {'payment_date': date(2020, 1, 1)}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(event, **changes)


if __name__ == '__main__':
    unittest.main()
