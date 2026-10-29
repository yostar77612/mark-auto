"""Time-dependent read models from explicit synthetic recorded books.

No research, execution permissions, SDK, credentials or broker claims. Domain
records are written to the isolated journal to exercise actual facade reads.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading import TradingWindow
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.domain.models import Environment, HoldingKind, Market, PositionLot, Quote, Side
from quantlab.trading.runtime.build import create_engine


D = Decimal
WORKSPACE = Path(__file__).resolve().parents[1]


class ValuationFreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='valuation-', dir=WORKSPACE / 't')
        self.core = create_engine(Path(self.temp.name))
        self.facade = LocalFacade(self.core)
        self.window = None
        self.specs = tuple(spec for spec in self.core.catalog.instruments if spec.market is Market.STOCK)[:2]
        form = StrategyForm(
            'synthetic-recorded-book',
            Market.STOCK,
            HoldingKind.SWING,
            3,
            5,
            Side.BUY,
            self.specs[0].instrument_id,
            'local-stock',
            Environment.LOCAL,
            D('60000'),
            D('.02'),
        )
        self.reference = self.core.create_strategy(form)
        self.record = self.core.strategy(self.reference)

    def tearDown(self):
        if self.window is not None:
            self.window.close()
            self.window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(self.window))
            self.app.processEvents()
        if self.core.research_runner is not None:
            self.core.research_runner.close()
        self.core.journal.close()
        self.core.simulation.ledger.close()
        self.temp.cleanup()

    def recorded_book(self, *, count=1, closed=False):
        now = self.core.clock.now()
        lots = []
        for number, spec in enumerate(self.specs[:count]):
            # A heterogeneous imported/legacy version must not become a partial
            # valuation if one instrument cannot be priced. This read fixture
            # does not pretend such a version was deployed by today's wizard.
            lots.append(
                PositionLot(
                    f'recorded-{number}',
                    'local-stock',
                    spec.instrument_id,
                    self.record.strategy_id,
                    self.record.version,
                    self.record.policy,
                    0 if closed else 1000,
                    D('10'),
                    self.core.state.trading_day,
                    0 if closed else 1000,
                    realized_pnl=D('129') if closed else D('0'),
                )
            )
            self.core.quotes[spec.instrument_id] = Quote(
                spec.instrument_id, D('11'), D('11.05'), D('11'), now, now, self.core.state.trading_day, source='SYNTHETIC_RECORDED_VALUATION_NOT_BROKER'
            )
        self.core._persist('synthetic_recorded_valuation_book', replace(self.core.state, positions=tuple(lots)))

    def show(self, state):
        self.window = TradingWindow(self.facade, state)
        self.window.poll.stop()
        self.window.setProperty('allow_close_for_tests', True)
        self.window.show()
        self.app.processEvents()

    def test_missing_or_expired_open_quote_is_unknown_without_changing_recorded_results(self):
        self.recorded_book()
        before = self.facade.snapshot()
        self.assertEqual(before.performance[0].unrealized_pnl, D('1000'))
        tracks = self.core.state.performance_tracks
        for missing in (False, True):
            if missing:
                self.core.quotes.pop(self.specs[0].instrument_id)
            else:
                self.core.clock.current += timedelta(seconds=31)
            row = self.facade.snapshot().performance[0]
            self.assertIsNone(row.unrealized_pnl)
            self.assertEqual(
                (row.net_pnl, row.costs, row.drawdown, row.attributed_pnl),
                (before.performance[0].net_pnl, before.performance[0].costs, before.performance[0].drawdown, before.performance[0].attributed_pnl),
            )
            self.assertEqual(self.core.state.performance_tracks, tracks)

    def test_one_missing_instrument_invalidates_whole_version_instead_of_partial_sum(self):
        self.recorded_book(count=2)
        self.assertEqual(self.facade.snapshot().performance[0].unrealized_pnl, D('2000'))
        self.core.quotes.pop(self.specs[1].instrument_id)
        self.assertIsNone(self.facade.snapshot().performance[0].unrealized_pnl)

    def test_closed_version_keeps_proven_zero_without_quote_and_realized_is_historical(self):
        self.recorded_book(closed=True)
        self.core.quotes.clear()
        row = self.facade.snapshot().performance[0]
        self.assertEqual(row.unrealized_pnl, D('0'))
        self.assertEqual(row.net_pnl, D('129'))

    def test_nonlocal_unverified_position_facts_prevent_current_unrealized_even_with_fresh_quote(self):
        self.recorded_book()
        self.core.configuration = replace(self.core.configuration, environment=Environment.BROKER_SIMULATION, read_only=True)
        self.core._persist('synthetic_unverified_broker_tag', replace(self.core.state, environment=Environment.BROKER_SIMULATION))
        state = self.facade.snapshot()
        self.assertFalse(state.financial_facts_verified)
        self.assertIsNone(state.performance[0].unrealized_pnl)
        self.assertEqual(state.performance[0].net_pnl, D('0'))

    def test_pure_time_expiry_repaints_same_stamp_and_keeps_selection_and_unsaved_form(self):
        self.recorded_book()
        unrelated = self.core.catalog.instruments[1]
        old = self.core.quotes[unrelated.instrument_id]
        self.core.quotes[unrelated.instrument_id] = replace(
            old, source_at=old.source_at - timedelta(seconds=60), received_at=old.received_at - timedelta(seconds=60)
        )
        initial = self.facade.snapshot()
        self.assertEqual(initial.quote_status, 'STALE')
        self.show(initial)
        self.window.strategies.selectRow(0)
        selected = self.window.strategies.item(0, 0)
        self.window.stock_budget.setText('54321')
        self.window._dirty_settings()
        self.assertEqual(self.window.performance.item(0, 5).text(), '1000')
        historical_as_of = self.window.performance.item(0, 11).text()
        self.core.clock.current += timedelta(seconds=31)
        expired = self.facade.snapshot()
        self.assertEqual((expired.version, expired.quote_revision, expired.quote_status), (initial.version, initial.quote_revision, initial.quote_status))
        self.window.apply_state(expired)
        self.assertEqual(self.window.performance.item(0, 5).text(), ui_text('v2.valuation_unknown'))
        self.assertEqual(self.window.performance.item(0, 11).text(), historical_as_of)
        self.assertIs(self.window.strategies.item(0, 0), selected)
        self.assertTrue(selected.isSelected())
        self.assertEqual(self.window.stock_budget.text(), '54321')
        self.assertIn(ui_text('v2.performance_freshness_hint'), self.window.performance.horizontalHeaderItem(11).toolTip())

    def test_unknown_finance_dto_repaints_same_stamp_without_formatting_none_as_money(self):
        self.recorded_book()
        initial = self.facade.snapshot()
        self.show(initial)
        row = replace(initial.performance[0], net_pnl=None, unrealized_pnl=None)
        pending = replace(initial, financial_facts_verified=False, daily_pnl=None, remaining_risk=None, performance=(row,))
        self.window.apply_state(pending)
        self.assertEqual(self.window.performance.item(0, 4).text(), ui_text('v2.valuation_unknown'))
        self.assertEqual(self.window.performance.item(0, 5).text(), ui_text('v2.valuation_unknown'))
        self.assertIn('尚未核對', self.window.summary.text())
        self.assertEqual(self.window.overview_status.text(), ui_text('v2.context_facts_pending'))
        self.assertNotIn('None', self.window.summary.text())


if __name__ == '__main__':
    unittest.main()
