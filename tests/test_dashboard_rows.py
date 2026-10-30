"""Dashboard display contracts only; no Qt or financial rule tests."""

from dataclasses import replace
from decimal import Decimal
import unittest

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.dashboard_rows import (
    status_lights,
    red_summary_text,
    today_summary_items,
    strategy_rows,
    position_rows,
    issue_rows,
    event_rows,
)
from quantlab.trading.application.contracts import MarketHealthView, OverviewMarketSummary, PositionView, StrategyView, UiState
from quantlab.trading.domain.models import Environment, Market, HoldingKind, QuantityUnit


def state(**changes):
    return replace(
        UiState(
            Environment.BROKER_SIMULATION,
            'account',
            'RUNNING',
            'SWING:3-5',
            Decimal('100'),
            None,
            None,
            'NO_DATA',
            1,
            '2026-10-23',
            False,
            reconciliation_verified=True,
            market_connection='CONNECTED',
        ),
        **changes,
    )


class DashboardRowsTests(unittest.TestCase):
    def test_light_rules_and_shared_market_labels(self):
        from desktop_app.features.trading.market_watch_rows import freshness_text

        for freshness, level in (('LIVE', 'live'), ('DELAYED', 'warning'), ('STOPPED', 'red'), ('CLOSED', 'muted'), ('UNKNOWN', 'muted')):
            with self.subTest(freshness=freshness):
                health = MarketHealthView('instrument', freshness)
                lights = {light.key: light for light in status_lights(state(market_health=OverviewMarketSummary((health,))))}
                self.assertEqual(lights['market'].level, level)
                self.assertIn(freshness_text(health)[0], lights['market'].label)
        for changes, key, level in (
            ({'market_connection': 'DISCONNECTED'}, 'broker', 'red'),
            ({'market_connection': 'CONNECTING'}, 'broker', 'warning'),
            ({'market_connection': 'UNKNOWN'}, 'broker', 'muted'),
            ({'environment': Environment.LOCAL, 'market_connection': 'DISCONNECTED'}, 'broker', 'muted'),
            ({'engine_state': 'STOPPED'}, 'engine', 'red'),
            ({'engine_state': 'CLOSED'}, 'engine', 'muted'),
            ({'reconciliation_verified': False}, 'reconciliation', 'red'),
            ({}, 'reconciliation', 'live'),
        ):
            with self.subTest(changes=changes, key=key):
                self.assertEqual({light.key: light.level for light in status_lights(state(**changes))}[key], level)

    def test_red_summary_text(self):
        for changes, labels in (
            ({}, ()),
            ({'market_health': OverviewMarketSummary((MarketHealthView('x', 'DELAYED'),))}, ()),
            (
                {'market_health': OverviewMarketSummary((MarketHealthView('x', 'DELAYED'), MarketHealthView('y', 'STOPPED')))},
                (ui_text('dashboard.status.market').format(ui_text('watch.stopped').format(ui_text('watch.unknown'))),),
            ),
            ({'reconciliation_verified': False}, (ui_text('dashboard.status.pending'),)),
            (
                {'market_connection': 'DISCONNECTED', 'reconciliation_verified': False},
                (ui_text('dashboard.status.broker').format(ui_text('dashboard.status.disconnected')), ui_text('dashboard.status.pending')),
            ),
        ):
            with self.subTest(changes=changes):
                expected = ui_text('dashboard.status.attention').format(' \u00b7 '.join(labels)) if labels else ''
                self.assertEqual(red_summary_text(state(**changes)), expected)

    def test_unknown_rendering_preserves_last_known_positions(self):
        position = PositionView(
            'lot',
            'instrument',
            'strategy',
            1,
            'SWING:3-5',
            2,
            QuantityUnit.CONTRACT,
            2,
            '2026-10-23',
            3,
            '2026-10-28 ~ 2026-10-30',
            '',
            'last quote time',
            'MANAGED',
            unrealized_pnl=Decimal('42'),
        )
        for freshness, text in (
            ('LIVE', '42'),
            ('DELAYED', ui_text('watch.unknown')),
            ('STOPPED', ui_text('watch.unknown')),
            ('CLOSED', ui_text('watch.unknown')),
            ('UNKNOWN', ui_text('watch.unknown')),
        ):
            with self.subTest(freshness=freshness):
                cells = position_rows(state(positions=(replace(position, quote_freshness=freshness),)))[0][1]
                self.assertEqual(cells[6:], (text, 'last quote time'))
                self.assertEqual(cells[4:6], ('3', position.exit_window))
        self.assertTrue(all(text == ui_text('watch.unknown') for _, text in today_summary_items(state())))
        strategy = StrategyView(
            'strategy', 'name', 1, Market.INDEX_FUTURE, 'instrument', HoldingKind.SWING, 'SWING:3-5', 'ACTIVE', 'account', Environment.LOCAL, ''
        )
        self.assertEqual(strategy_rows(state(strategies=(strategy,)))[0][1][-2:], (ui_text('watch.unknown'), ui_text('watch.unknown')))
        self.assertEqual(issue_rows(state(issues=('pending one', 'pending two'))), ('pending one', 'pending two'))
        self.assertEqual(event_rows(state(events=('entries_resumed_explicitly',))), (ui_text('v2.event_resumed'),))


if __name__ == '__main__':
    unittest.main()
