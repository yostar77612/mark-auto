"""Calendar and host wiring regressions; no duplicate Domain calculation rules."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.adapters.simulated.tick_feed import SimulatedTickFeed
from quantlab.trading.application.context import Catalog, ExecutionConfiguration
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.market_cycle import poll_market
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import HistoryBar
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.live_market import CalendarResolver, attach_market
from test_live_market_wiring import memory_engine
from test_tick_adapters_contract import simulated_connector


class MarketRepairTests(unittest.TestCase):
    def test_night_health_uses_each_instruments_session(self):
        engine = memory_engine()
        day = engine.calendar.sessions[0]
        night = TradingSession(day.trade_date + timedelta(days=1), day.closes_at + timedelta(hours=2), day.closes_at + timedelta(hours=12), 'NIGHT')
        engine.calendar = TradingCalendar('test', 'v1', 'EXPLICIT_TEST', (day, night))
        specs = tuple(replace(spec, instrument_id=f'WATCH:{i}') for i, spec in enumerate(engine.catalog.instruments[:2]))
        engine.catalog = Catalog(specs)
        broker, _, _ = simulated_connector()
        engine.gateways = {'local-stock': broker, 'local-futures': broker}
        broker.tick_feed = SimulatedTickFeed(engine.clock, CalendarResolver(engine), start=engine.clock.now(), catch_up=False)
        attach_market(engine)
        poll_market(engine)
        engine.clock.current = night.opens_at + timedelta(minutes=1)
        poll_market(engine)
        views = {view.instrument_id: view for view in engine.live_market.views()}
        self.assertEqual(views[specs[0].instrument_id].health.freshness, 'CLOSED')
        self.assertEqual(views[specs[1].instrument_id].health.freshness, 'LIVE')
        self.assertEqual(engine.state.issues, ())

    def test_broker_cycle_is_independent_of_market_poll(self):
        for readonly in (False, True):
            for failure in (False, True):
                with self.subTest(readonly=readonly, failure=failure):
                    service = Mock()
                    service.settings = LiveMarketSettings()
                    engine = memory_engine(live_market=service)
                    engine.configuration = ExecutionConfiguration(environment=Environment.BROKER_SIMULATION, read_only=readonly)
                    gateway = Mock()
                    gateway.latest.return_value = None
                    engine.gateways = {'local-stock': gateway}
                    bundle = RuntimeBundle(RuntimeLaunch(Path.cwd()), LocalFacade(engine), (), engine)
                    bundle.query_instruments = ('WATCH:0',)
                    if failure:
                        service.poll.side_effect = DomainError('outcome_unknown', 'failed market drain')
                    with (
                        patch('quantlab.trading.application.coordinator.run_cycle') as cycle,
                        patch('quantlab.trading.application.coordinator.run_readonly_cycle') as read_cycle,
                    ):
                        if failure:
                            with self.assertRaises(DomainError):
                                bundle.pump()
                            self.assertIn('outcome_unknown', engine.state.issues)
                            self.assertEqual(engine.state.events[-1], 'live_market_requires_attention')
                        else:
                            bundle.pump()
                        gateway.latest.assert_called_once_with('WATCH:0')
                        (read_cycle if readonly else cycle).assert_called_once()
                        (cycle if readonly else read_cycle).assert_not_called()

    def test_after_close_emits_no_ticks_and_publishes_closed_without_issue(self):
        broker, _, _ = simulated_connector()
        engine = memory_engine()
        engine.catalog = Catalog((broker.resolve('WATCH:0'),))
        engine.gateways = {'local-stock': broker}
        broker.clock = engine.clock
        broker.tick_feed = SimulatedTickFeed(engine.clock, CalendarResolver(engine), start=engine.clock.now(), catch_up=False)
        attach_market(engine)
        poll_market(engine)
        before = engine.live_market.views()[0]
        issues = engine.state.issues
        engine.clock.current = engine.calendar.sessions[0].closes_at + timedelta(minutes=1)
        for _ in range(2):
            poll_market(engine)
            after = LocalFacade(engine).snapshot().market_watch[0]
            self.assertEqual(after.source_at, before.source_at)
            self.assertEqual(after.health.freshness, 'CLOSED')
            self.assertEqual(engine.state.issues, issues)
            engine.clock.current += timedelta(seconds=1)

    def test_published_reference_uses_calendar_trade_date_for_each_instrument(self):
        def at(day, hour):
            return datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=hour)

        friday, monday, wednesday = date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 28)
        calendar = TradingCalendar(
            'test',
            'v1',
            'EXPLICIT_TEST',
            (
                TradingSession(friday, at(friday, 9), at(friday, 13)),
                TradingSession(monday, at(friday, 15), at(friday + timedelta(days=1), 5), 'NIGHT'),
                TradingSession(monday, at(monday, 9), at(monday, 13)),
                # Tuesday is an explicit holiday gap in this test calendar.
                TradingSession(wednesday, at(monday, 15), at(monday + timedelta(days=1), 5), 'NIGHT'),
                TradingSession(wednesday, at(wednesday, 9), at(wednesday, 13)),
            ),
        )
        for spec_index, current, previous in ((1, at(friday, 16), friday), (1, at(monday, 16), monday), (0, at(wednesday, 10), monday)):
            with self.subTest(spec_index=spec_index, current=current):
                engine = memory_engine()
                spec = replace(engine.catalog.instruments[spec_index], instrument_id='WATCH:0')
                broker, _, _ = simulated_connector()
                # Market port boundary fixtures retain the engine's real catalog/session mapping.
                engine.calendar = calendar
                engine.clock.current = current
                engine.gateways = {'local-stock': broker, 'local-futures': broker}
                engine.catalog = Catalog((spec,))
                broker.tick_feed = SimulatedTickFeed(engine.clock, CalendarResolver(engine), start=current, price=Decimal('110'))
                attach_market(engine)
                engine.live_market.allocate((spec.instrument_id,))
                start = at(previous, 12)
                bar = HistoryBar(spec.instrument_id, start, start + timedelta(minutes=1), *(Decimal('100'),) * 4, 1, 'TEST')
                broker.bars[spec.instrument_id] = (bar,)
                engine.live_market.backfill(spec.instrument_id, start, start + timedelta(minutes=1))
                poll_market(engine)
                watch = LocalFacade(engine).snapshot().market_watch[0]
                self.assertEqual(watch.reference_price, Decimal('100'))
                self.assertIsNotNone(watch.change)
                self.assertIsNotNone(watch.change_percent)
                self.assertEqual(watch.trade_date, calendar.session_at(current, allow_night=spec_index == 1).trade_date)
