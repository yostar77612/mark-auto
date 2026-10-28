"""Market transport bounds and application wiring; no Domain arithmetic tests."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from quantlab.trading.application.codec import MAX_BYTES, dumps, loads
from quantlab.trading.application.contracts import MarketSeriesQuery
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.live_market import LiveMarketService
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.bootstrap import RuntimeBundle
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.context_client import ContextIpcFacade
from quantlab.trading.runtime.ipc import IpcFacade
from quantlab.trading.runtime.protocol import Operation, Request, Response
from quantlab.trading.runtime.server import _dispatch
from test_live_market_wiring import memory_engine
from test_tick_adapters_contract import simulated_connector


class MarketTransportTests(unittest.TestCase):
    def setUp(self):
        broker, self.clock, resolver = simulated_connector()
        self.service = LiveMarketService(broker, self.clock, resolver)
        self.service.allocate(('WATCH:0',))
        self.service.poll(in_session=True)
        self.engine = memory_engine(live_market=self.service)
        self.engine.gateways = {'local-stock': broker}
        self.bundle = RuntimeBundle(RuntimeLaunch(Path.cwd()), LocalFacade(self.engine), (), self.engine)

    def envelope(self, operation, **kwargs):
        return Request('market', Environment.LOCAL, 'local-stock', datetime.now(timezone.utc) + timedelta(seconds=10), operation, **kwargs)

    def test_characterize_existing_snapshot_dispatch_and_small_views(self):
        request = self.envelope(Operation.SNAPSHOT)
        self.assertEqual(loads(dumps(request)), request)
        response = _dispatch(self.bundle, request)
        self.assertEqual(loads(dumps(response)), response)
        self.assertEqual(response.state.market_watch, self.service.views())
        self.assertEqual(self.service.views(), (self.service.watch('WATCH:0'),))

    def test_characterize_context_request_forwarding(self):
        client = ContextIpcFacade(self.bundle.launch)
        response = Response('metrics')
        with patch.object(IpcFacade, 'request', return_value=response) as request:
            self.assertEqual(client.request(Operation.METRICS), response)
            request.assert_called_once_with(Operation.METRICS, command=None, quotes=None)

    def test_full_retention_snapshot_size(self):
        keys = tuple(f'WATCH:{i}' for i in range(20))
        self.service.allocate(keys)
        template = self.service.watch('WATCH:0').bars[0]
        start = self.clock.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
        retained = tuple(
            replace(
                template, start=start + timedelta(minutes=i), end=start + timedelta(minutes=i + 1), trade_date=(start + timedelta(minutes=i)).date(), final=True
            )
            for i in range(30 * 1440)
        )
        for key in keys:
            self.service._buffers[key].history.extend(replace(bar, instrument_id=key) for bar in retained)
        response = _dispatch(self.bundle, self.envelope(Operation.SNAPSHOT))
        size = len(dumps(response).encode('utf-8'))
        self.assertLess(size, MAX_BYTES // 8)
        self.assertEqual(len(response.state.market_watch), 20)
        for view in response.state.market_watch:
            self.assertLessEqual(len(view.bars), self.service.settings.snapshot_bar_tail)
        print(f'Full-retention market snapshot: {size} bytes (wire limit {MAX_BYTES})')

    def test_series_roundtrip_caps_paging_and_preserves_domain_results(self):
        self.service.settings = replace(self.service.settings, series_page_limit=7)
        template = self.service.watch('WATCH:0').bars[0]
        buffer = self.service._buffers['WATCH:0']
        buffer.history.extend(
            replace(template, start=template.start - timedelta(minutes=i), end=template.end - timedelta(minutes=i), final=True) for i in range(90, 10, -1)
        )
        client = ContextIpcFacade(self.bundle.launch)
        before = (self.engine.state, self.engine.quote_count, self.service.market_revision)
        for period in ('1m', '5m', '1d'):
            with self.subTest(period=period):
                expected = self.service.watch('WATCH:0', period=period)
                query = MarketSeriesQuery('WATCH:0', period, limit=10**6)
                received = []
                while True:
                    request = loads(dumps(self.envelope(Operation.MARKET_SERIES, series=query)))
                    response = _dispatch(self.bundle, request)
                    payload = dumps(response)
                    self.assertLess(len(payload.encode('utf-8')), MAX_BYTES)
                    with patch('quantlab.trading.runtime.ipc.read_session') as session, patch('quantlab.trading.runtime.ipc.Client') as connection:
                        session.return_value.key = b'test'
                        wire = connection.return_value.__enter__.return_value

                        def reply(_):
                            envelope = loads(wire.send_bytes.call_args.args[0].decode('utf-8'))
                            return dumps(replace(response, request_id=envelope.request_id)).encode('utf-8')

                        wire.recv_bytes.side_effect = reply
                        page = client.market_series(query)
                        sent = loads(wire.send_bytes.call_args.args[0].decode('utf-8'))
                        self.assertEqual((sent.operation, sent.series), (Operation.MARKET_SERIES, query))
                    self.assertLessEqual(len(page.bars), 7)
                    self.assertEqual((page.period, page.total, page.gaps), (period, len(expected.bars), expected.gaps))
                    received.extend(page.bars)
                    if page.next_offset is None:
                        break
                    query = replace(query, offset=page.next_offset, market_revision=page.market_revision)
                # Compare delegated DTOs, not a second implementation of Domain math.
                self.assertEqual(tuple(received), expected.bars)
        self.assertEqual((self.engine.state, self.engine.quote_count, self.service.market_revision), before)

    def test_series_boundary_rejections_and_empty_page(self):
        for changes in ({'offset': -1}, {'limit': 0}, {'limit': True}, {'period': '2m'}, {'instrument_id': ''}):
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                replace(MarketSeriesQuery('WATCH:0'), **changes)
        for query, code in (
            (MarketSeriesQuery('WATCH:24'), 'capability_missing'),
            (MarketSeriesQuery('WATCH:0', market_revision=self.service.market_revision + 1), 'state_conflict'),
        ):
            with self.subTest(query=query), self.assertRaises(DomainError) as caught:
                _dispatch(self.bundle, self.envelope(Operation.MARKET_SERIES, series=query))
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(DomainError):
            self.envelope(Operation.MARKET_SERIES)
        page = self.service.series(MarketSeriesQuery('WATCH:0', offset=100))
        self.assertEqual((page.bars, page.next_offset), ((), None))

    def test_byte_budget_can_shorten_a_count_capped_page(self):
        template = self.service.watch('WATCH:0').bars[0]
        self.service._buffers['WATCH:0'].history.extend(
            replace(template, start=template.start - timedelta(minutes=i), end=template.end - timedelta(minutes=i), final=True) for i in range(100, 0, -1)
        )
        # A reduced budget exercises the byte bound with ordinary valid bars.
        with patch('quantlab.trading.application.live_market.MAX_BYTES', 8192):
            response = _dispatch(self.bundle, self.envelope(Operation.MARKET_SERIES, series=MarketSeriesQuery('WATCH:0')))
        self.assertLess(len(dumps(response).encode('utf-8')), 8192)
        self.assertLess(len(response.series.bars), response.series.total)
        self.assertEqual(response.series.next_offset, len(response.series.bars))

    def test_old_protocol_defaults(self):
        for envelope in (self.envelope(Operation.SNAPSHOT), Response('older')):
            with self.subTest(envelope=envelope):
                body = json.loads(dumps(envelope))
                del body['fields']['series']
                self.assertEqual(loads(json.dumps(body)), envelope)

    def test_old_snapshot_dashboard_fields_decode_with_defaults(self):
        from decimal import Decimal
        from quantlab.trading.application.contracts import PositionView, StrategyView
        from quantlab.trading.domain.models import HoldingKind, Market, QuantityUnit

        strategy = StrategyView(
            'strategy', 'name', 1, Market.STOCK, 'instrument', HoldingKind.SWING, 'SWING:3-5', 'ACTIVE', 'local-stock', Environment.LOCAL, ''
        )
        position = PositionView(
            'lot', 'instrument', 'strategy', 1, 'SWING:3-5', 1000, QuantityUnit.SHARE, 0, '2026-10-23', 0, 'exit window', '', 'quote time', 'MANAGED'
        )
        state = replace(LocalFacade(self.engine).snapshot(), strategies=(strategy,), positions=(position,), unrealized_pnl=Decimal('5'))
        body = json.loads(dumps(Response('older', state=state)))
        raw_state = body['fields']['state']['fields']
        for field in ('unrealized_pnl', 'remaining_daily_loss', 'today_fill_count'):
            del raw_state[field]
        for collection, fields in (('strategies', ('today_order_count', 'today_pnl', 'activity_state')), ('positions', ('unrealized_pnl', 'quote_freshness'))):
            for field in fields:
                del raw_state[collection]['value'][0]['fields'][field]
        decoded = loads(json.dumps(body)).state
        self.assertEqual(decoded.strategies, (strategy,))
        self.assertEqual(decoded.positions, (position,))
        self.assertEqual((decoded.unrealized_pnl, decoded.remaining_daily_loss, decoded.today_fill_count), (None, None, None))
