"""Observed execution drawdown uses durable real fills, never training figures."""

from dataclasses import replace
from contextlib import closing
from datetime import timedelta
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

import test_trading_application as fixtures
from quantlab.trading.adapters.simulated import FaultPlan
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.events import poll_events, reconcile
from quantlab.trading.application.execution import ExecutionService
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.performance import VersionEquityTrack
from quantlab.trading.application.workflows import fill_local_pending, mark_risk, run_research, step, total_mark, transfer
from quantlab.trading.domain.models import HoldingKind, Market, Quote, Side
from quantlab.trading.domain.validation import DomainError

D = Decimal


class ExecutionPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.lab = fixtures.ApplicationLifecycleTests(methodName='runTest')
        self.lab.setUp()

    def tearDown(self):
        self.lab.tearDown()

    @property
    def core(self):
        return self.lab.engine

    def observation(self, reference):
        key, version = reference.rsplit(':', 1)
        return next(track for track in self.core.state.performance_tracks if (track.strategy_id, track.version) == (key, int(version)))

    def price(self, bid):
        spec = next(item for item in self.core.catalog.instruments if item.market is Market.STOCK)
        now = self.core.clock.now()
        self.core.quote(
            Quote(
                spec.instrument_id,
                D(bid),
                D(bid) + spec.tick_size,
                D(bid),
                now,
                now,
                self.core.state.trading_day,
                sequence=self.core.quote_count + 1,
                source='LOCAL_PERFORMANCE_FIXTURE',
            )
        )

    def enter_stock(self):
        reference = self.lab.deploy()
        self.price('9.90')
        self.lab.submit(reference)
        fill_local_pending(self.core)
        mark_risk(self.core)
        return reference

    def test_native_trade_shape_drawdown_170_costs_71_and_realized_129(self):
        reference = self.enter_stock()
        self.assertEqual(self.observation(reference).equity, D('-170'))
        for bid in ('9.95', '10.00', '10.05', '10.10', '10.15'):
            self.price(bid)
            mark_risk(self.core)
        track = self.observation(reference)
        self.assertEqual(track.max_drawdown, D('170'))
        self.assertEqual(track.equity, D('79'))
        step(self.core, self.core.history)
        self.price('10.15')
        lot = next(item for item in self.core.state.positions if item.quantity)
        self.core.exit_lot(lot.lot_id, protective=True)
        fill_local_pending(self.core)
        mark_risk(self.core)
        row = self.lab.facade.snapshot().performance[0]
        self.assertEqual((row.net_pnl, row.costs, row.drawdown), (D('129'), D('71'), D('170')))
        self.assertEqual(row.drawdown_coverage, 'COMPLETE')
        self.assertTrue(row.drawdown_as_of)
        report = loads(self.core.state.strategies[0].research_blob)
        self.assertNotEqual(row.drawdown, report.drawdown, 'execution must not read training drawdown')

    def test_positive_peak_to_later_loss_and_restart_keep_same_observation(self):
        reference = self.enter_stock()
        self.price('10.50')
        mark_risk(self.core)
        self.assertEqual(self.observation(reference).peak, D('428'))
        self.price('10.20')
        mark_risk(self.core)
        before = self.observation(reference)
        self.assertEqual((before.equity, before.max_drawdown), (D('129'), D('299')))
        self.lab.restart()
        self.assertEqual(self.observation(reference), before)
        self.assertEqual(self.lab.facade.snapshot().performance[0].drawdown, D('299'))

    def test_versions_have_independent_peaks_and_new_policy_does_not_reassign_old_lot(self):
        original = self.enter_stock()
        newer = self.lab.deploy(parent=original.split(':')[0], kind=HoldingKind.POSITION, max_days=100)
        mark_risk(self.core)
        self.assertEqual(self.observation(original).max_drawdown, D('170'))
        self.assertEqual(self.observation(newer).max_drawdown, D('0'))
        self.assertEqual(self.observation(newer).equity, D('0'))
        self.assertEqual(self.core.state.positions[0].strategy_version, 1)

    def test_explicit_transfer_moves_book_value_without_false_new_version_profit_or_loss(self):
        original = self.enter_stock()
        newer = self.lab.deploy(parent=original.split(':')[0], kind=HoldingKind.POSITION, max_days=100)
        self.price('10.50')
        mark_risk(self.core)
        old_value = self.observation(original).equity
        lot = self.core.state.positions[0]
        transfer(self.core, lot.lot_id, newer)
        mark_risk(self.core)
        self.assertEqual(self.observation(original).equity, old_value)
        self.assertEqual(self.observation(newer).equity, D('0'))
        self.assertEqual(self.observation(newer).max_drawdown, D('0'))
        self.assertEqual(sum(t.equity for t in self.core.state.performance_tracks), total_mark(self.core))
        self.price('10.20')
        mark_risk(self.core)
        self.assertEqual(self.observation(original).equity, old_value)
        self.assertEqual(self.observation(newer).equity, D('-299'))
        self.assertEqual(self.observation(newer).max_drawdown, D('299'))
        before = self.core.state.performance_tracks
        self.lab.restart()
        self.assertEqual(self.core.state.performance_tracks, before)

    def test_transfer_freezes_book_in_single_owner_append_before_next_price_or_restart(self):
        for restart in (False, True):
            with self.subTest(restart=restart):
                if restart:
                    self.lab.tearDown()
                    self.lab.setUp()
                original = self.enter_stock()
                newer = self.lab.deploy(parent=original.split(':')[0], kind=HoldingKind.POSITION, max_days=100)
                self.price('10.50')
                mark_risk(self.core)
                old_version = self.core.state.version
                lot = self.core.state.positions[0]
                transfer(self.core, lot.lot_id, newer)
                self.assertEqual(self.core.state.version, old_version + 1, 'handoff requires exactly one durable append')
                self.assertEqual(self.core.journal.replay()[-1].kind, 'position_transferred_explicitly')
                self.assertEqual((self.observation(original).equity, self.observation(newer).equity), (D('428'), D('0')))
                if restart:
                    self.lab.restart()
                self.price('10.20')
                mark_risk(self.core)
                self.assertEqual((self.observation(original).equity, self.observation(original).max_drawdown), (D('428'), D('170')))
                self.assertEqual((self.observation(newer).equity, self.observation(newer).max_drawdown), (D('-299'), D('299')))

    def test_failed_transfer_append_preserves_previous_owner_and_equity_tracks(self):
        original = self.enter_stock()
        newer = self.lab.deploy(parent=original.split(':')[0], kind=HoldingKind.POSITION, max_days=100)
        self.price('10.50')
        mark_risk(self.core)
        before = self.core.state
        prefix = self.core.journal.replay()
        with patch.object(self.core.journal, 'append', side_effect=OSError('isolated handoff disk failure')):
            with self.assertRaises(DomainError):
                transfer(self.core, before.positions[0].lot_id, newer)
        self.assertEqual(self.core.state.positions, before.positions)
        self.assertEqual(self.core.state.performance_tracks, before.performance_tracks)
        self.assertEqual(self.core.journal.replay(), prefix)

    def test_partial_executed_close_profit_stays_with_its_order_version_at_handoff(self):
        original = self.enter_stock()
        step(self.core, self.core.history)
        self.price('10.50')
        broker = self.core.gateways['local-stock']
        broker.queue_fault(FaultPlan(partial_quantity=500))
        lot = self.core.state.positions[0]
        close_id = self.core.exit_lot(lot.lot_id, protective=True)
        poll_events(self.core)
        service = ExecutionService(broker, self.core._persist, self.core.fence, self.core.clock.now)
        service.cancel(self.core.state, close_id)
        poll_events(self.core)
        mark_risk(self.core)
        before = self.lab.facade.snapshot().performance[0].net_pnl
        self.assertEqual(before, D('219'))
        newer = self.lab.deploy(parent=original.split(':')[0], kind=HoldingKind.POSITION, max_days=100)
        transfer(self.core, lot.lot_id, newer)
        rows = self.lab.facade.snapshot().performance
        self.assertEqual(rows[0].net_pnl, before)
        self.assertEqual(rows[1].net_pnl, D('0'), 'past executed closes cannot migrate with the remaining shares')
        self.assertEqual(rows[1].attributed_pnl, D('0'))

    def test_unfilled_margin_and_cash_reservations_are_not_drawdown(self):
        reference = self.lab.deploy(Market.INDEX_FUTURE)
        self.lab.submit(reference)
        self.assertGreater(sum(r.cash for r in self.core.reservations()), 0)
        mark_risk(self.core)
        self.assertEqual(self.observation(reference).equity, D('0'))
        self.assertEqual(self.observation(reference).max_drawdown, D('0'))

    def test_partial_duplicate_reports_charge_actual_fees_once_and_do_not_duplicate_marks(self):
        reference = self.lab.deploy()
        self.price('9.90')
        self.lab.submit(reference, fault=FaultPlan(partial_quantity=300, duplicate_event=True))
        poll_events(self.core)
        mark_risk(self.core)
        before = self.observation(reference)
        poll_events(self.core)
        mark_risk(self.core)
        self.assertEqual(self.observation(reference), before)
        self.assertEqual(self.core.state.positions[0].quantity, 300)
        fill_local_pending(self.core)
        mark_risk(self.core)
        self.assertEqual(self.core.state.positions[0].quantity, 1000)
        self.assertEqual(self.core.state.orders[0].costs, D('20'))
        self.assertEqual(self.observation(reference).max_drawdown, D('170'))

    def test_stale_valuation_does_not_create_zero_observation(self):
        reference = self.enter_stock()
        before = self.observation(reference)
        self.core.clock.current += timedelta(seconds=31)
        with self.assertRaises(DomainError) as raised:
            mark_risk(self.core)
        self.assertEqual(raised.exception.code, 'stale_quote')
        self.assertEqual(self.observation(reference), before)

    def test_journal_failure_cannot_publish_uncommitted_peak_or_drawdown(self):
        reference = self.enter_stock()
        before = self.observation(reference)
        self.price('10.50')
        with patch.object(self.core.journal, 'append', side_effect=OSError('isolated disk fault')):
            with self.assertRaises(DomainError) as raised:
                mark_risk(self.core)
        self.assertEqual(raised.exception.code, 'journal_failed')
        self.assertEqual(self.observation(reference), before)

    def test_old_journal_without_tracks_reads_unchanged_and_stays_honestly_unknown(self):
        self.enter_stock()
        old = json.loads(dumps(replace(self.core.state, version=1)))
        del old['fields']['performance_tracks']
        with closing(Ledger(self.lab.root / 'legacy.sqlite', 'legacy-performance', self.core.ownership_clock())) as journal:
            journal.append('legacy_snapshot_fixture', json.dumps(old), self.core.ownership_clock(), expected_sequence=0)
            prefix = journal.replay()[0]
            restored = TradingEngine(
                journal,
                self.core.clock,
                self.core.calendar,
                self.core.catalog,
                self.core.gateways,
                configuration=self.core.configuration,
                ownership_clock=self.core.ownership_clock,
                source_profile=self.core.profile,
                fees=self.core.fees,
                historical_bars=self.core.history,
            )
            for quote in self.core.quotes.values():
                restored.quote(quote)
            self.assertIsNone(LocalFacade(restored).snapshot().performance[0].drawdown)
            mark_risk(restored)
            view = LocalFacade(restored).snapshot().performance[0]
            self.assertIsNone(view.drawdown)
            self.assertEqual(view.drawdown_coverage, 'LEGACY_UNKNOWN')
            source = restored.state.strategies[0]
            new_ref = restored.create_strategy(replace(source.form, parent_strategy_id=source.strategy_id))
            restored.validate_strategy(new_ref)
            with restored.lock:
                run_research(restored, new_ref, restored.history[source.form.instrument_id])
            restored.deploy(new_ref)
            reconcile(restored)
            quote = restored.quotes[source.form.instrument_id]
            restored.quote(replace(quote, bid=D('10.50'), ask=D('10.55'), last=D('10.50'), sequence=(quote.sequence or 0) + 1))
            transfer(restored, restored.state.positions[0].lot_id, new_ref)
            rows = LocalFacade(restored).snapshot().performance
            self.assertIsNone(rows[0].drawdown)
            self.assertIsNone(rows[0].attributed_pnl)
            self.assertEqual((rows[1].drawdown, rows[1].attributed_pnl), (D('0'), D('0')))
            last = restored.quotes[source.form.instrument_id]
            restored.quote(replace(last, bid=D('10.20'), ask=D('10.25'), last=D('10.20'), sequence=(last.sequence or 0) + 1))
            mark_risk(restored)
            rows = LocalFacade(restored).snapshot().performance
            self.assertIsNone(rows[0].drawdown)
            self.assertEqual((rows[1].drawdown, rows[1].attributed_pnl), (D('299'), D('-299')))
            self.assertEqual(journal.replay()[0], prefix, 'old payload and chained digest must not be rewritten')

    def test_liquidation_extraction_preserves_original_portfolio_risk_formula(self):
        self.enter_stock()
        expected = self.core.state.realized_pnl
        for lot in self.core.state.positions:
            if not lot.quantity:
                continue
            spec, quote = self.core.catalog.resolve(lot.instrument_id), self.core.quotes[lot.instrument_id]
            sign = 1 if lot.direction is Side.BUY else -1
            price, side = (quote.bid, Side.SELL) if sign == 1 else (quote.ask, Side.BUY)
            expected += (price - lot.entry_price) * lot.quantity * spec.multiplier * sign
            expected -= self.core.fees.transaction(spec, side, price, lot.quantity) + self.core.fees.slippage(spec, lot.quantity, legs=1)
        self.assertEqual(total_mark(self.core), expected)

    def test_track_rejects_float_money_and_naive_time(self):
        reference = self.enter_stock()
        track = self.observation(reference)
        for change in ({'equity': 0.0}, {'last_at': track.last_at.replace(tzinfo=None)}, {'max_drawdown': D('-1')}):
            with self.subTest(change=change), self.assertRaises(DomainError):
                replace(track, **change)
        self.assertIsInstance(track, VersionEquityTrack)


if __name__ == '__main__':
    unittest.main()
